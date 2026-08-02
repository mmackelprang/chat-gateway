"""The HTTP surface. Thin by design: auth → registry checks → pipeline.

Everything interesting is injectable (registry, inbox, adapters, dispatcher,
deduper, heartbeat store), so tests drive the real app with fakes and
deterministic clocks; __main__.py wires the real pieces and starts the
background threads (dispatcher, heartbeat monitor, optional Pub/Sub
subscriber).

Contract notes baked in here:
- /v1/notify and /v1/heartbeat implement the aitrader consumer contract
  (docs/consumers/aitrader.md): accept-fast 202 semantics, dedupe, per-source
  delivery log, dead-man checks.
- /v1/inbox honors per-app `allow_inbound: false` — the no-inbound-control
  guarantee (gateway hard rule #6) enforced, not just omitted.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .auth import AuthError, authenticate
from .delivery import DeliveryLog, Dispatcher
from .envelope import CG_ACTION_KEY, DeliveryResult, OutboundMessage
from .heartbeat import (
    DEFAULT_TZ, HeartbeatError, HeartbeatMonitor, HeartbeatStore,
)
from .inbox import Inbox
from .notifications import Deduper, Notification, render
from .registry import Registry, RegistryError
from .retention import SWEEP_STALE_INTERVAL_MULTIPLE, window_for


#: Where a producer's card must point its `onClick.action.function` for the
#: interaction to reach this gateway. DEPLOYMENT-level, not per-app: there is
#: one inbound route. Declared in the environment rather than derived from
#: CHAT_GATEWAY_PUBSUB_SUBSCRIPTION, because the two were only ever
#: coincidentally related, and only under ADD-ONS at that: topic-as-function
#: made the routing target look like it fell out of the subscription. On
#: CLASSIC — production since 2026-07-29 — it is any constant, and under an
#: HTTP-endpoint deployment it splits by runtime too: the endpoint URL under
#: add-ons, a function name under classic (ADR-0001 D3's portability table).
ROUTING_TARGET_ENV = "CHAT_GATEWAY_INTERACTION_ROUTING_TARGET"

#: Consecutive failed polls before /healthz calls inbound dead. Three at the
#: default 5s interval is ~15s — long enough to ride out a blip, short enough
#: that a real outage is visible within one dashboard refresh.
POLL_FAILURE_THRESHOLD = 3

#: Silence — as opposed to failure — before /healthz calls inbound dead.
#:
#: This exists because failure counters cannot detect a loop that has stopped
#: RAISING as well as stopped working. A dead thread, or one wedged somewhere
#: that never returns, increments nothing: `consecutive_poll_failures` sits at 0
#: and `last_poll_at` stays frozen at a real timestamp. Counter-based reasons
#: alone therefore reproduce rule #5's founding failure — green health over a
#: dead input — one layer further in than the defect CG-7 was filed for.
#:
#: Five minutes, and the floor is chosen against a real bound rather than taste:
#: `PubSubPuller`'s client timeout is 90s, so the slowest a HEALTHY poll can
#: leave this timestamp untouched is ~90s plus dispatch. 300s clears that with
#: room and still surfaces a silent death inside one coffee break. Scaled by the
#: configured interval too, so a deployment that deliberately polls slowly does
#: not get permanent false alarms.
POLL_STALE_AFTER_SECONDS = 300.0
POLL_STALE_INTERVAL_MULTIPLE = 6


def _stale_after(subscriber) -> float:
    """Seconds of silence tolerated before the last poll is called stale."""
    return max(POLL_STALE_AFTER_SECONDS,
               POLL_STALE_INTERVAL_MULTIPLE * subscriber.interval_seconds)


def _sweep_stale_after(sweeper) -> float:
    """Seconds of silence tolerated before the last completed sweep is stale.

    Same shape as `_stale_after` above, no floor beside it. The multiple, and
    why this loop does not need the floor the poll loop does, live with the
    constant in `retention.py` — one home, not two.
    """
    return SWEEP_STALE_INTERVAL_MULTIPLE * sweeper.interval_seconds


def _journal_skipped(dispatch, inbox) -> int:
    """Unparseable journal lines across both queues; 0 when unjournalled.

    Read through the public `journal` property rather than the private
    attribute, so /healthz does not reach through either class.
    """
    total = 0
    for owner in (dispatch, inbox):
        journal = getattr(owner, "journal", None)
        if journal is not None:
            total += getattr(journal, "skipped_lines", 0)
    return total


def _journal_write_errors(dispatch, inbox) -> int:
    """Journal writes that FAILED on a path that could not raise.

    A close or a reschedule that cannot reach disk does not stop
    delivery — raising there would turn a full disk into a re-send storm
    — so the only thing that makes it visible is this counter. A durable
    queue whose durability has silently stopped working is worse than an
    in-memory one, because it is trusted.
    """
    return sum(getattr(owner, "journal_write_errors", 0)
               for owner in (dispatch, inbox))


def _interaction_config(registry: Registry, app_id: str) -> dict | None:
    """The card convention, published so producers never hardcode it.

    Returns None — with the reason — rather than a half-answer, because a
    producer that builds cards against a missing routing target ships cards
    whose taps go nowhere, and finding that out at tap time is the failure this
    endpoint exists to prevent.
    """
    if not registry.apps[app_id].allow_inbound:
        return {"enabled": False,
                "reason": "inbound is disabled for this app (hard rule #6) — "
                          "card interactions from it are never routed anywhere"}
    target = os.environ.get(ROUTING_TARGET_ENV, "")
    if not target:
        return {"enabled": False,
                "reason": f"the operator has not set {ROUTING_TARGET_ENV} — "
                          "card interactions cannot be routed until they do; "
                          "do not guess a value"}
    return {
        "enabled": True,
        "routing_target": target,
        "action_key": CG_ACTION_KEY,
        "note": "put routing_target in onClick.action.function and your action "
                "identity in parameters[action_key]; never hardcode either. "
                "The gateway pops action_key out of the params it forwards.",
    }


class HeartbeatIn(BaseModel):
    check_id: str = Field(min_length=1, max_length=100)
    schedule: str = Field(description="weekdays | daily | every:<N><s|m|h|d>")
    grace: str = Field(description="duration, e.g. 2h, 90m, 1d")
    tz: str = Field(default=DEFAULT_TZ)


def create_app(registry: Registry, inbox: Inbox, adapters: dict[str, Any],
               subscriber: Any | None = None, *,
               delivery_log: DeliveryLog | None = None,
               dispatcher: Dispatcher | None = None,
               deduper: Deduper | None = None,
               heartbeats: HeartbeatStore | None = None,
               # CG-68. Opt-in and defaulting to None, the same posture as
               # `dispatcher` and `subscriber`: every offline test builds an app
               # without one, and /healthz must answer 200 for those (audit F0).
               sweeper: Any | None = None,
               monitor_interval: float = 60.0) -> FastAPI:
    """`adapters` maps identity mode -> adapter with .send(identity, message)."""

    log = delivery_log or DeliveryLog()
    dispatch = dispatcher or Dispatcher(adapters, log)
    dedupe = deduper or Deduper()
    checks = heartbeats or HeartbeatStore()

    app = FastAPI(
        title="chat-gateway",
        version=__version__,
        description=(
            "First-class chat identities for agentic applications. Apps render "
            "their own content; the gateway owns identity, delivery, threading, "
            "notifications, dead-man checks, and inbound reply routing."
        ),
    )

    def current_app_id(authorization: str | None = Header(default=None)) -> str:
        try:
            return authenticate(registry, authorization)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    # -- notify pipeline (shared by the endpoint and the heartbeat monitor) ---
    def emit_notification(app_id: str, n: Notification) -> dict:
        try:
            identity = registry.route_for(app_id, n.severity)
        except RegistryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        deliver, occurrences = dedupe.check(app_id, n.dedupe_key)
        if not deliver:
            log.record(app_id, "notify", n.title, "deduped",
                       f"occurrence {occurrences} within window")
            return {"status": "deduped", "occurrences": occurrences}
        message = render(n, app_id, occurrences)
        entry_id = dispatch.enqueue(app_id, "notify", identity, message, n.title)
        return {"status": "enqueued", "id": entry_id, "occurrences": occurrences}

    def _monitor_notify(source: str, title: str, body: str, dedupe_key: str) -> None:
        try:
            emit_notification(source, Notification(
                severity="alert", title=title, body=body, dedupe_key=dedupe_key,
            ))
        except HTTPException as exc:  # no alert route configured — log, don't die
            log.record(source, "heartbeat", title, "failed", f"no route: {exc.detail}")

    monitor = HeartbeatMonitor(checks, _monitor_notify, interval_seconds=monitor_interval)

    # expose the moving parts for __main__ and tests
    app.state.dispatcher = dispatch
    app.state.monitor = monitor
    app.state.delivery_log = log
    app.state.heartbeats = checks
    app.state.sweeper = sweeper

    # -- raw envelope send (synchronous; aiteam notify.py path) ---------------
    @app.post("/v1/messages", response_model=DeliveryResult)
    def send_message(message: OutboundMessage, app_id: str = Depends(current_app_id)):
        try:
            identity = registry.identity_for(app_id, message.identity)
        except RegistryError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        adapter = adapters.get(identity.mode)
        if adapter is None:
            raise HTTPException(
                status_code=503,
                detail=f"no adapter for mode {identity.mode!r} (tier not enabled on this deployment)",
            )
        try:
            result = adapter.send(identity, message)
        except RegistryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            log.record(app_id, "message", message.text[:80], "failed", str(exc)[:200])
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        log.record(app_id, "message", message.text[:80], "delivered")
        return result

    # -- notifications (accept-fast, async delivery, dedupe) ------------------
    @app.post("/v1/notify", status_code=202)
    def notify(n: Notification, app_id: str = Depends(current_app_id)):
        return emit_notification(app_id, n)

    # -- dead-man heartbeat checks --------------------------------------------
    @app.post("/v1/heartbeat")
    def refresh_heartbeat(h: HeartbeatIn, app_id: str = Depends(current_app_id)):
        try:
            check = checks.refresh(app_id, h.check_id, h.schedule, h.grace, h.tz)
        except (HeartbeatError, Exception) as exc:
            if isinstance(exc, HeartbeatError):
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            raise HTTPException(status_code=422, detail=f"bad tz or check spec: {exc}") from exc
        return {"status": "ok", "check_id": check.check_id,
                "next_deadline": check.deadline().isoformat()}

    @app.get("/v1/heartbeat/{source}")
    def list_heartbeats(source: str, app_id: str = Depends(current_app_id)):
        if source != app_id:
            raise HTTPException(status_code=403, detail="a source may only read its own checks")
        out = []
        for c in checks.list_for(source):
            out.append({"check_id": c.check_id, "schedule": c.schedule, "grace": c.grace,
                        "tz": c.tz, "last_seen": c.last_seen, "status": c.status,
                        "next_deadline": c.deadline().isoformat(),
                        "last_alerted": c.last_alerted or None})
        return {"source": source, "checks": out}

    @app.delete("/v1/heartbeat/{source}/{check_id}")
    def delete_heartbeat(source: str, check_id: str, app_id: str = Depends(current_app_id)):
        if source != app_id:
            raise HTTPException(status_code=403, detail="a source may only delete its own checks")
        if not checks.delete(source, check_id):
            raise HTTPException(status_code=404, detail=f"no such check {check_id!r}")
        return {"status": "deleted", "check_id": check_id}

    # -- delivery log ---------------------------------------------------------
    @app.get("/v1/deliveries")
    def deliveries(limit: int = 50, app_id: str = Depends(current_app_id)):
        limit = max(1, min(limit, 200))
        return {"source": app_id, "deliveries": log.query(app_id, limit)}

    # -- inbound --------------------------------------------------------------
    @app.get("/v1/inbox")
    def poll_inbox(app_id: str = Depends(current_app_id)):
        if not registry.apps[app_id].allow_inbound:
            raise HTTPException(
                status_code=403,
                detail="inbound is disabled for this app (no-inbound-control contract "
                       "— gateway hard rule #6)",
            )
        replies = inbox.poll(app_id)
        return {"app": app_id, "count": len(replies),
                "replies": [r.model_dump(mode="json") for r in replies]}

    @app.get("/v1/identities")
    def list_identities(app_id: str = Depends(current_app_id)):
        """What you may send as — plus, for two-way tenants, how to make a card
        interaction come back (ADR-0001 D3).

        `interaction.routing_target` is the value a producer must put in a
        card's `onClick.action.function`. **Producers must not hardcode it.**
        Fetching it is what makes a deployment-model migration cost zero
        producer card changes: identity always rides in `interaction.action_key`
        (`__cg_action__`), the function slot always holds whatever the gateway
        publishes here, and only this one value moves. That portability is the
        entire reason the topic-as-function bridge is a cheap bet rather than a
        trap — do not let it rot.

        Not a secret: `docs/google-cloud-setup.md` step 8 classifies topic and
        subscription names as safe to paste, and this endpoint is authenticated
        regardless (hard rule #2 unaffected).

        **Withheld from `allow_inbound: false` tenants** — narrower than the ADR
        requires, deliberately. Handing an opted-out tenant a routing target
        invites it to build cards whose interactions the gateway would then
        discard; saying so plainly is better than a value that silently means
        nothing. `aitrader` gets `null` and the reason (hard rule #6).
        """
        allowed = registry.apps[app_id].identities
        return {
            "app": app_id,
            "identities": [
                {"name": n, "display": registry.identities[n].display,
                 "mode": registry.identities[n].mode,
                 "ready": registry.identities[n].env_resolved()}
                for n in allowed if n in registry.identities
            ],
            "interaction": _interaction_config(registry, app_id),
        }

    @app.get("/healthz")
    def healthz():
        """Honest health: real resolvability + real liveness — never a
        hardcoded OK (claude-mem pilot lesson; aiteam plan F18 gate 2).

        `status` is computed FROM `reasons`, not alongside it. Anything that can
        make this endpoint degraded must be able to say so in words, because an
        operator seeing "degraded" and no reason has to diff the body against a
        known-good copy to learn anything.

        Inbound is judged three independent ways, because each one is blind to
        the others' failure mode: whether polls have ever SUCCEEDED, whether
        they are currently FAILING (counters), and whether they are still
        HAPPENING AT ALL (thread liveness + wall-clock staleness). Counters see
        nothing when a loop stops raising as well as stops working.
        """
        now = dt.datetime.now(dt.timezone.utc)
        hb_all = [c for s in registry.apps for c in checks.list_for(s)]
        body = {
            "version": __version__,
            "registry": registry.health(),
            "inbox": {"pending": inbox.pending_counts(), "dropped": inbox.dropped,
                      "replayed_at_boot": getattr(inbox, "replayed", 0),
                      # The inbound twin of delivery's `unroutable_at_boot`:
                      # a journalled reply that no longer parses is dropped
                      # and boot compaction then removes it for good, so
                      # this counter is the only thing standing between a
                      # lost tap and nobody knowing. Rule #5.
                      "unrevivable_at_boot": getattr(inbox, "unrevivable", 0),
                      # CG-65. How many of those were preserved. Two numbers,
                      # not one: `unrevivable` is what was lost from the queue,
                      # `quarantined` is what is recoverable, and an operator
                      # reading the first needs the second to know whether to
                      # go looking.
                      "quarantined_at_boot": getattr(inbox, "quarantined", 0),
                      "quarantine_write_errors": getattr(inbox, "quarantine_write_errors", 0)},
            "delivery": {"pending_jobs": dispatch.pending(),
                         "replayed_at_boot": getattr(dispatch, "replayed", 0),
                         "expired_at_boot": getattr(dispatch, "expired", 0),
                         "unroutable_at_boot": getattr(dispatch, "unroutable", 0),
                         # Journal lines that did not parse, and journal
                         # writes that failed. A torn trailing line is
                         # the expected shape after a power loss and is
                         # deliberately not fatal (journal.py) — but a
                         # mechanism whose whole purpose is surviving
                         # something nobody watched must say when it lost
                         # something. Rule #5.
                         "journal_skipped_lines": _journal_skipped(dispatch, inbox),
                         "journal_write_errors": _journal_write_errors(dispatch, inbox)},
            "heartbeats": {"checks": len(hb_all),
                           "missed": sum(1 for c in hb_all if c.status == "missed"),
                           "last_scan_at": monitor.last_scan_at.isoformat() if monitor.last_scan_at else None},
            "subscriber": (
                {"enabled": True,
                 "last_poll_at": subscriber.last_poll_at.isoformat() if subscriber.last_poll_at else None,
                 "events_seen": subscriber.events_seen,
                 "unparseable_seen": subscriber.unparseable_seen,
                 "dispatch_errors": subscriber.dispatch_errors,
                 # ADR-0001 D4: interactions that parsed but carried no
                 # resolvable action identity. Non-zero means some producer's
                 # cards are missing `__cg_action__` — or Google changed the
                 # runtime under us. Rising counts here are one of the few
                 # observables if topic-as-function routing ever breaks.
                 "interactions_without_action_id":
                     subscriber.interactions_without_action_id,
                 # CG-12: each counts CANDIDATE APPS THAT DECLINED an event —
                 # `allow_inbound: false`, or a sender not on that app's
                 # allowlist — not events that went nowhere. An opted-out owner
                 # increments even when a co-owner of the same space RECEIVED
                 # that same event, and one event with two opted-out owners
                 # increments by two; `events_seen` is the event count. BARE
                 # integers — no space, no app id, no content — because this
                 # endpoint is UNAUTHENTICATED. Full reasoning, and the
                 # all-owners-opted-out gap this was filed for, sit with the
                 # counters in adapters/pubsub.py; do not restate them here.
                 #
                 # They are deliberately NOT inputs to `status` and never add a
                 # `reasons` entry, at any magnitude. Both are CORRECT behaviour:
                 # `opt_out` is hard rule #6 doing its job, `not_authorized` is
                 # jobhunt's R4 allowlist doing its job. Degrading on a system
                 # working as designed would teach an operator that "degraded" is
                 # the normal reading, and an ignored warning is the failure mode
                 # rule #5 was written after. Do not add a threshold here.
                 "suppressed_opt_out": subscriber.suppressed_opt_out,
                 "suppressed_not_authorized": subscriber.suppressed_not_authorized,
                 "poll_failures": subscriber.poll_failures,
                 "consecutive_poll_failures": subscriber.consecutive_poll_failures,
                 "last_poll_error": subscriber.last_poll_error,
                 # DIRECT liveness, not inferred from counters. Every field above
                 # describes what happened the last time a poll ran; none of them
                 # says whether a poll will ever run again. A dead thread freezes
                 # all of them at plausible values (rule #5's founding failure).
                 "thread_alive": subscriber.is_alive(),
                 # Reported alongside, because `thread_alive: false` alone is
                 # ambiguous — a loop that was never started looks identical to
                 # one that died. Only the second is a fault worth shouting
                 # about; the first is already covered by "never completed a
                 # poll", and every offline test constructs a loop it never
                 # starts.
                 "thread_started": subscriber.started,
                 # How stale the last completed poll is, in seconds. Reported as
                 # a NUMBER rather than left for the reader to subtract two
                 # timestamps: `last_poll_at` was already being reported before
                 # this and it was never compared to the clock, which is how a
                 # three-week-old timestamp read exactly like a three-second-old
                 # one on an endpoint whose docstring claims "real liveness".
                 "seconds_since_last_poll": (
                     round((now - subscriber.last_poll_at).total_seconds(), 1)
                     if subscriber.last_poll_at else None),
                 "stale_after_seconds": _stale_after(subscriber),
                 # Reported so the staleness budget above is checkable rather
                 # than magic: an operator can see the interval it was derived
                 # from instead of trusting the number.
                 "poll_interval_seconds": subscriber.interval_seconds,
                 # DECLARED, not detected — the field name says so. Detecting it
                 # means calling Cloud Billing / Service Usage: more scopes, more
                 # IAM, more calls. And on 2026-07-29 Google's own
                 # pubsub.googleapis.com/topic/send_request_count read ZERO after
                 # a message had provably published, which is a standing argument
                 # against trusting its telemetry for this. Recorded with its
                 # architectural consequence ("no automated health check in this
                 # project may be built on that metric") at
                 # docs/google-cloud-setup.md:117, under "Failure signature".
                 "billing_declared": os.environ.get("GATEWAY_GCP_BILLING", "unknown"),
                 "quota_note": (
                     "free-tier exhaustion fails CLOSED — inbound stops with no "
                     "other symptom; consecutive_poll_failures is the signal"
                 )}
                if subscriber is not None
                else {"enabled": False, "note": "tier 2 not enabled (GATEWAY_ENABLE_PUBSUB=0)"}
            ),
            # CG-68 / ADR-0002 D5. Rule #5 does not distinguish work DROPPED
            # from work DELETED: a deletion path running against a directory of
            # message bodies has to be as legible as the queue counters above.
            "retention": (
                {"enabled": sweeper.days > 0,
                 "window_days": sweeper.days,
                 # `window_for`, not a second `min(...)` (audit F5). The floor
                 # rule has ONE home; re-deriving it here is how /healthz ends
                 # up publishing a window the sweeper stopped using. CLAUDE.md's
                 # test count is this repo's own worked example.
                 "unrouted_window_days": window_for("_unrouted", sweeper.days),
                 # DELIBERATELY not an input to `status`, at any magnitude —
                 # same reasoning CLAUDE.md records for `suppressed_opt_out`. A
                 # retention policy working is not a fault, and degrading on it
                 # teaches an operator that "degraded" is the normal reading.
                 "files_deleted": sweeper.deleted,
                 "delete_errors": sweeper.errors,
                 # Whether there is an audit directory to sweep at all. Without
                 # it, `files_deleted: 0` is the ONLY signal, and it reads
                 # identically for "no audit trail is configured on this
                 # deployment" and "the trail is configured and nothing has
                 # expired yet" (pre-merge review, 2026-08-02). A BOOLEAN, never
                 # the path: this endpoint is UNAUTHENTICATED.
                 "audit_dir_configured": sweeper.audit_dir_configured,
                 # CG-68 audit F3. `last_sweep_at` alone could not tell an idle
                 # sweeper from a dead one, and a raising sweep was printed but
                 # never counted — so the fields below travel together.
                 #
                 # CUMULATIVE, and deliberately NOT what degrades — the same
                 # relationship `poll_failures` has to `consecutive_poll_failures`
                 # in the block above. It never returns to zero, so degrading on
                 # it pinned `status` at `degraded` for the life of the process
                 # after a single failure that had already recovered.
                 "sweep_failures": sweeper.sweep_failures,
                 "consecutive_sweep_failures": sweeper.consecutive_sweep_failures,
                 # A TYPE NAME, never a filesystem path — this endpoint is
                 # UNAUTHENTICATED, and `str(OSError)` from a failed unlink
                 # embeds the absolute path of a file named after a tenant.
                 # `_run` builds this through `describe_exception` (CG-29's
                 # allowlist, audit F4), which is what makes printing it here
                 # and interpolating it into a `reasons` line safe.
                 "last_sweep_error": sweeper.last_sweep_error,
                 "last_sweep_at": (sweeper.last_sweep_at.isoformat()
                                   if sweeper.last_sweep_at else None),
                 # DIRECT liveness, exactly as the subscriber block above, and
                 # for the same reason stated there: every counter describes
                 # what happened the last time a pass ran, none of them says
                 # whether a pass will ever run again. `_run`'s `except` covers
                 # the sweep, not its own handler — a `print()` to a blocked
                 # stdout escapes the loop and kills the thread with every field
                 # here frozen at a plausible value.
                 "thread_alive": sweeper.is_alive(),
                 # Read WITH the row above, never alone: a loop that was never
                 # started looks identical to one that died, and only the second
                 # is a fault. Every offline test builds a sweeper it never
                 # starts.
                 "thread_started": sweeper.started,
                 # A NUMBER, not two timestamps for the reader to subtract. The
                 # first version of this block published `last_sweep_at` and
                 # never compared it to the clock, so a three-week-old stamp read
                 # exactly like a three-second-old one.
                 "seconds_since_last_sweep": (
                     round((now - sweeper.last_sweep_at).total_seconds(), 1)
                     if sweeper.last_sweep_at else None),
                 "stale_after_seconds": _sweep_stale_after(sweeper),
                 # Published so the budget above is checkable rather than magic.
                 "sweep_interval_seconds": sweeper.interval_seconds}
                if sweeper is not None
                else {"enabled": False, "note": "no sweeper configured"}
            ),
        }

        reasons: list[str] = []
        for name, i in body["registry"]["identities"].items():
            if not i["env_resolved"]:
                reasons.append(f"identity {name!r}: env var does not resolve")
        for app_id, a in body["registry"]["apps"].items():
            if not a["key_configured"]:
                reasons.append(f"app {app_id!r}: key env var is not set")
        # CG-54. Three ways queue durability can have lost work, and all
        # three are silent by construction — they happen at boot or on a
        # background thread, with nobody watching. A number in the body is
        # not enough: `status` is computed FROM `reasons`, so anything that
        # should make an operator look has to be able to say so in words.
        queue = body["delivery"]
        if queue["journal_skipped_lines"]:
            reasons.append(
                f"queue journal: {queue['journal_skipped_lines']} unparseable "
                "line(s) skipped at boot — at least one queued item was lost to "
                "a torn or corrupt write. The JSONL audit files under the state "
                "dir are the recovery record"
            )
        if queue["journal_write_errors"]:
            reasons.append(
                f"queue journal: {queue['journal_write_errors']} write(s) FAILED "
                "since start — the queues are still running but are no longer "
                "durable, so a restart will lose or double-send the affected "
                "entries. Check free space and the state dir's permissions"
            )
        # CG-68. BIND THEN GATE ON `enabled` — the else-branch of the retention
        # block has no `delete_errors` key, and indexing it unconditionally
        # raised KeyError on every app built without a sweeper, which is the
        # normal offline case (audit F0, HIGH). The endpoint hard rule #5 exists
        # to keep honest would not have answered at all. Same two-branch shape,
        # same idiom, as the `subscriber` block below.
        #
        # BOUND HERE, above the inbox lines, rather than beside the retention
        # reasons further down: the two inbox tails describe the retention
        # window and have to branch on the same flag (pre-merge review,
        # 2026-08-02). Both asserted deletion unconditionally, so with
        # `CHAT_GATEWAY_INBOX_RETENTION_DAYS=0` — the documented escape hatch —
        # or with no sweeper at all, an unauthenticated endpoint told an
        # operator their last-copy audit file was on a delete timer that is not
        # running, and pointed at a `window_days` field that does not exist in
        # the no-sweeper branch. That is Task 14's own defect shape pointed the
        # other way.
        ret = body["retention"]
        if body["inbox"]["unrevivable_at_boot"]:
            preserved = body["inbox"]["quarantined_at_boot"]
            # CG-65. The tail BRANCHES on `preserved`, and that is hard rule #5,
            # not phrasing. This line is spec §2.5's promise site 6 — the one
            # that made pruning a rule-#5 problem rather than a docs problem —
            # and it earned that status by naming an artifact the reader could
            # be sent to in vain. Asserting "the quarantine dir is the recovery
            # record" when nothing was preserved (no `quarantine_dir` wired, or
            # every write failed) would reproduce the exact defect on the exact
            # line, pointing an operator at a directory that may not even exist.
            #
            # CG-68 changed the `else` TAIL and nothing else. It read "carries
            # no retention guarantee", which was true on 2026-08-01 and false
            # the moment `retention.py` shipped — an unauthenticated endpoint
            # describing machinery the process is not running. The `preserved`
            # conditional is untouched: it is the rule-#5 control, not phrasing.
            #
            # That tail then had to branch a SECOND time, on `ret["enabled"]`,
            # for the identical reason in the identical direction: the first
            # version asserted the delete timer unconditionally, so a deployment
            # that set the window to `0` was told its last copy was being pruned.
            # Same control, same rule, one more axis.
            reasons.append(
                f"inbox replay dropped {body['inbox']['unrevivable_at_boot']} "
                "journalled reply(ies) that no longer parse as an InboundReply — "
                "they were NOT delivered to the owning app and are gone from the "
                "queue journal. An envelope change across a deploy looks like "
                f"this. {preserved} of them were preserved in full under the "
                "state dir's quarantine dir"
                + (", which is never pruned and is the recovery record"
                   if preserved else
                   " — so the per-app JSONL audit under the inbox dir is the "
                   "only record of what arrived, AND THAT FILE IS PRUNED on "
                   "the retention window (retention.window_days above), so it "
                   "will not be there indefinitely"
                   if ret["enabled"] else
                   " — so the per-app JSONL audit under the inbox dir is the "
                   "only record of what arrived. Pruning is NOT in force on "
                   "this deployment (retention.enabled above), so that file is "
                   "not on a delete timer — but nothing else records the reply")
                + "; the ids are on the boot console"
            )
        if body["inbox"]["quarantine_write_errors"]:
            # The louder of the two CG-68 tense flips: the quarantine write
            # already failed, so this really IS the last copy — and since this
            # row it has a delete timer on it. "Copy it now" is the actionable
            # half, and it was not sayable while the file was permanent.
            #
            # It is sayable only when the timer is RUNNING, which is why this
            # branches on `ret["enabled"]` too. Urgency an operator cannot act
            # on is the same defect as a missing warning: it teaches them the
            # line is boilerplate.
            reasons.append(
                f"inbox quarantine: {body['inbox']['quarantine_write_errors']} "
                "write(s) FAILED — at least one unrevivable reply has no "
                "preserved copy, so the per-app JSONL audit under the inbox dir "
                "is its only record"
                + (" AND THAT FILE IS ON A DELETE TIMER "
                   "(retention.window_days above). Copy it now if you need it."
                   if ret["enabled"] else
                   ". Pruning is NOT in force on this deployment "
                   "(retention.enabled above), so that file is not on a delete "
                   "timer — it is still the only copy.")
                + " Check free space and the state dir's permissions"
            )
        if queue["expired_at_boot"] or queue["unroutable_at_boot"]:
            reasons.append(
                f"queue replay dropped {queue['expired_at_boot']} expired and "
                f"{queue['unroutable_at_boot']} unroutable job(s) at boot — they were "
                "queued and were NOT delivered. Expired means older than the "
                "replay ceiling (posting a stale alert now would mislead); "
                "unroutable means the registry no longer grants that identity "
                "(hard rule #4). Both are in the delivery log by id. This is a "
                "fact about THIS boot and will not change while the process runs "
                "— boot compaction already removed the records, so the next "
                "restart clears it"
            )
        # `ret` is bound above the inbox lines, which need the same flag.
        if ret["enabled"]:
            if ret["delete_errors"]:
                reasons.append(
                    f"retention: {ret['delete_errors']} audit file(s) could not "
                    "be removed — the inbound audit trail is growing past its "
                    "stated window. Check the inbox dir's permissions"
                )
            # CONSECUTIVE, not cumulative — the counter that returns to zero on
            # the next good pass. `sweep_failures` stays in the body as the
            # lifetime figure and drives nothing, exactly as `poll_failures`
            # does below. Gating on the cumulative one degraded forever after a
            # single recovered failure and rendered the already-cleared
            # `last_sweep_error` as the literal "(None)" while the sweeper was
            # demonstrably still pruning.
            if ret["consecutive_sweep_failures"]:
                reasons.append(
                    f"retention: {ret['consecutive_sweep_failures']} consecutive "
                    f"sweep pass(es) FAILED ({ret['last_sweep_error']}) — nothing "
                    "is being pruned, so `files_deleted` and `delete_errors` are "
                    "both sitting at a reassuring number while the window is not "
                    "being enforced. The audit trail holds message text and "
                    "sender addresses"
                )
            # The two silence checks, in the subscriber block's order and for
            # the subscriber block's reason: a loop that is loudly failing has a
            # more actionable reason already, and a dead thread will also look
            # stale — a dead thread and a frozen timestamp are ONE fault, so
            # they must not produce two reasons.
            #
            # A SWEEPER THAT WAS STARTED AND IS NO LONGER RUNNING moves no
            # counter and no timestamp, so nothing above can see it. `_run`
            # catches what `sweep()` raises; it does not catch what its own
            # handler raises.
            elif ret["thread_started"] and not ret["thread_alive"]:
                reasons.append(
                    "retention: the sweep thread was started and is NOT RUNNING "
                    "— the audit trail is no longer being pruned and no counter "
                    "in this block will ever move again. `last_sweep_at` is "
                    "frozen at a real timestamp, which is why it looks healthy; "
                    "restart the service"
                )
            # ...and a thread that is alive but no longer completing passes.
            # `seconds_since_last_sweep` is None only before the first pass;
            # `__main__` sweeps once at boot BEFORE `start()`, so on a real
            # deployment a started sweeper with no completed pass is itself the
            # fault, not a startup race.
            elif ret["thread_started"] and ret["seconds_since_last_sweep"] is None:
                reasons.append(
                    "retention: the sweep thread was started but no pass has "
                    "ever completed — the boot sweep runs before the thread "
                    "does, so this should be impossible and the window is not "
                    "being enforced"
                )
            elif ret["thread_alive"] and (
                    ret["seconds_since_last_sweep"] > ret["stale_after_seconds"]):
                reasons.append(
                    f"retention: the thread is alive but the last completed "
                    f"sweep was {ret['seconds_since_last_sweep']}s ago, over the "
                    f"{ret['stale_after_seconds']}s budget for a "
                    f"{ret['sweep_interval_seconds']}s-interval loop — passes are "
                    "neither completing nor raising, so it is wedged rather than "
                    "erroring. The audit trail holds message text and sender "
                    "addresses"
                )
        sub = body["subscriber"]
        if sub["enabled"]:
            if sub["last_poll_at"] is None:
                reasons.append(
                    "subscriber is enabled but has never completed a poll — "
                    "inbound has never worked on this process"
                )
            elif sub["consecutive_poll_failures"] >= POLL_FAILURE_THRESHOLD:
                reasons.append(
                    f"subscriber: {sub['consecutive_poll_failures']} consecutive "
                    f"poll failures (last: {sub['last_poll_error']}) — inbound is "
                    "DOWN. Revoked key, deleted subscription, wrong subscription "
                    "name, or quota exhaustion all look like this and all fail closed"
                )
            # The two silence checks. Ordered after the failure check because a
            # loop that is loudly failing has a more actionable reason already,
            # and a dead thread will also look stale — reporting both would be
            # two reasons for one fault.
            #
            # A LOOP THAT WAS STARTED AND IS NO LONGER RUNNING increments no
            # counter and moves no timestamp, so nothing above can see it.
            elif sub["thread_started"] and not sub["thread_alive"]:
                reasons.append(
                    "subscriber: the polling thread was started and is NOT "
                    "RUNNING — inbound is dead and no counter will ever move "
                    "again. Every field in this block is frozen at its last "
                    "value, so they look healthy; restart the service"
                )
            # ...and a thread that is alive but no longer completing polls.
            # Gated on `thread_alive` because staleness is only meaningful for a
            # loop that is actually running: for one that is not, the reason
            # above (or "never completed a poll") is the accurate diagnosis, and
            # a second reason for one fault is noise.
            elif sub["thread_alive"] and (
                    sub["seconds_since_last_poll"] > sub["stale_after_seconds"]):
                reasons.append(
                    f"subscriber: the thread is alive but the last completed poll "
                    f"was {sub['seconds_since_last_poll']}s ago, over the "
                    f"{sub['stale_after_seconds']}s budget for a "
                    f"{sub['poll_interval_seconds']}s-interval loop — polls are "
                    "neither succeeding nor raising, so it is wedged rather than "
                    "erroring"
                )
            # CG-13 left this to CG-7 rather than colliding with the rewrite.
            # It DEGRADES, deliberately: with tier 2 on and no routing target,
            # inbound interactions are not merely unconfigured, they are
            # impossible — /v1/identities already tells every producer
            # `interaction.enabled: false`, so a half-built deployment can look
            # healthy while no card any tenant ships can ever work. That is the
            # silent-inbound shape rule #5 exists for, so it is a reason and not
            # a footnote. The text names the variable and the value to set,
            # because "unset" alone sends an operator to the docs.
            if not os.environ.get(ROUTING_TARGET_ENV, ""):
                reasons.append(
                    f"subscriber is enabled but {ROUTING_TARGET_ENV} is unset — "
                    "card interactions cannot reach this gateway at all and "
                    "/v1/identities reports interaction.enabled=false to every "
                    "producer; set it to the Pub/Sub TOPIC path "
                    "(projects/<PROJECT_ID>/topics/<TOPIC>) — the topic, NOT the "
                    "subscription"
                )
        # Names, never values: identity names and app ids are non-secret (they
        # live in the committed registry); the poll error is a type and a status.
        # Load-bearing, because this endpoint is UNAUTHENTICATED.
        return JSONResponse(status_code=200,
                            content={"status": "degraded" if reasons else "ok",
                                     "reasons": reasons, **body})

    return app
