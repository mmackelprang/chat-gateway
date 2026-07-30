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
            "inbox": {"pending": inbox.pending_counts(), "dropped": inbox.dropped},
            "delivery": {"pending_jobs": dispatch.pending()},
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
        }

        reasons: list[str] = []
        for name, i in body["registry"]["identities"].items():
            if not i["env_resolved"]:
                reasons.append(f"identity {name!r}: env var does not resolve")
        for app_id, a in body["registry"]["apps"].items():
            if not a["key_configured"]:
                reasons.append(f"app {app_id!r}: key env var is not set")
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
