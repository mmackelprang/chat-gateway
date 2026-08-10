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

#: Consecutive raising passes before /healthz calls outbound delivery DOWN.
#:
#: Three, matching `POLL_FAILURE_THRESHOLD` and NOT the sweeper's implicit one,
#: and the difference is the loop interval rather than taste. The sweeper runs
#: every six hours, so one failed pass is already a real signal. This loop runs
#: every `PASS_INTERVAL_S` — one second — where a single transient blip should
#: not flip an alarm on an endpoint consumers page on. Three passes is three
#: seconds: the threshold costs nothing in detection time and buys the whole of
#: the anti-flap.
DISPATCH_FAILURE_THRESHOLD = 3

#: The same number for the scan loop, and it is NOT a copy for symmetry's sake:
#: `monitor_interval` is settable per deployment (`create_app`), so this is a
#: count of scans, not of seconds, exactly as the two above are.
SCAN_FAILURE_THRESHOLD = 3

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

#: Silence before /healthz calls OUTBOUND DELIVERY dead.
#:
#: The floor is chosen against a real bound, as `POLL_STALE_AFTER_SECONDS`'s is,
#: and the bound here is worse: `process_due` walks every due job SEQUENTIALLY
#: and each `adapter.send` is bounded by a 30s client timeout — plus, for
#: `chat_api`, a token refresh that is NOT bounded by it. `send` evaluates
#: `self._tokens()` inside the `headers=` argument, i.e. before `client.post` is
#: entered, and `GoogleServiceAccountTokens.__call__` refreshes on google-auth's
#: own transport, which the httpx timeout does not reach. No number is quoted
#: for that leg because none has been measured — it is named so a reader does
#: not take 30s as the whole of a send. A backlog of N jobs all timing out
#: therefore holds `last_pass_at` still for at least ~30N seconds while the
#: dispatcher is working perfectly. 600s clears twenty consecutive timing-out
#: sends, which is far past any realistic pass at this gateway's traffic shape
#: (tens of messages a day, journal.py) and is still one dashboard refresh
#: rather than eleven days.
#:
#: Stated rather than glossed: this is a LOOSER detector than the subscriber's.
#: Ten minutes to notice a dead delivery thread is the price of not crying wolf
#: at every slow Google call, and it is bought against a baseline of NEVER.
DISPATCH_STALE_AFTER_SECONDS = 600.0
#: INERT AT TODAY'S INTERVAL, and carried anyway — the one constant in this file
#: whose multiple never wins. `Dispatcher.interval_seconds` returns the module
#: constant `PASS_INTERVAL_S` (1.0) and is not per-instance settable, unlike the
#: sweeper's and the monitor's, so `max(600.0, 60 * 1.0)` is always the floor.
#: It exists so the budget still tracks the loop if `PASS_INTERVAL_S` ever
#: moves: at a 10s pass the floor stops meaning "twenty timing-out sends" and
#: this takes over. Deleting it would leave a bare 600.0 with nothing tying it
#: to the interval it was derived from.
DISPATCH_STALE_INTERVAL_MULTIPLE = 60

#: Silence before /healthz calls the HEARTBEAT MONITOR dead. `scan_once` does no
#: network I/O — it reads the store and hands work to `Dispatcher.enqueue`,
#: which appends and returns — so a scan is fast and bounded, and this needs no
#: allowance for a slow remote call. Six intervals matches the subscriber's
#: multiple; the 300s floor keeps a deployment that sets a very short
#: `monitor_interval` from alarming on ordinary jitter.
SCAN_STALE_AFTER_SECONDS = 300.0
SCAN_STALE_INTERVAL_MULTIPLE = 6


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


def _dispatch_stale_after(dispatch) -> float:
    """Seconds of silence tolerated before the last completed pass is stale."""
    return max(DISPATCH_STALE_AFTER_SECONDS,
               DISPATCH_STALE_INTERVAL_MULTIPLE * dispatch.interval_seconds)


def _scan_stale_after(monitor) -> float:
    """Seconds of silence tolerated before the last completed scan is stale."""
    return max(SCAN_STALE_AFTER_SECONDS,
               SCAN_STALE_INTERVAL_MULTIPLE * monitor.interval_seconds)


def _checks_orphaned(registry, checks) -> int:
    """Registered dead-man checks whose source is no longer a registered app.

    A bare count, never the ids (CG-12: /healthz is unauthenticated, and an
    orphaned check's `source` is a FORMER TENANT's app id). The authenticated
    `GET /v1/deliveries` carries the failing alerts under that id.

    `HeartbeatStore` has no "all sources" accessor by design — `list_for` is
    per-source, which is what keeps the endpoint's own authorization honest —
    so this reads the private map under the store's lock via `list_all`.

    `getattr` with a default, like every neighbouring /healthz read, and for
    the reason CG-68's audit finding F0 recorded: `create_app` takes an
    injected `heartbeats`, so a duck-typed store without this accessor would
    500 the endpoint rather than report a zero. An unconditional lookup on this
    endpoint is exactly what that finding cost.
    """
    list_all = getattr(checks, "list_all", None)
    if list_all is None:
        return 0
    return sum(1 for c in list_all() if c.source not in registry.apps)


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


def _audit_write_errors(dispatch, log) -> int:
    """Delivery-log audit writes that FAILED, across every log /healthz can reach.

    Two owners rather than one, for the reason `_journal_write_errors` has two —
    and here the second is not hypothetical. `create_app` builds its own
    `DeliveryLog` when none is injected (`log = delivery_log or DeliveryLog()`),
    while an injected `dispatcher` carries whichever log IT was built with, and
    `create_app(dispatcher=Dispatcher(adapters, other_log))` is a shape the
    tests already build. Reading one of the two would report zero while the
    other was losing records.

    Deduped by IDENTITY, so the ordinary case — one object doing both jobs — is
    not double-counted. `getattr` with a default, like its sibling, so an
    injected test double without the attribute reads as zero rather than
    breaking the endpoint (CG-68 audit F0 is what an unconditional lookup on
    this endpoint costs).
    """
    seen: dict[int, object] = {}
    for owner in (getattr(dispatch, "delivery_log", None), log):
        if owner is not None:
            seen[id(owner)] = owner
    return sum(getattr(owner, "audit_write_errors", 0) for owner in seen.values())


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
               # CG-80. Default OFF, the same posture GATEWAY_ENABLE_PUBSUB
               # takes for a new surface: an operator arms it deliberately, and
               # /healthz then says whether the running image both HAS it and
               # HAS IT ON — two separate facts, which is the lesson CG-59 paid
               # for when a deployed container answered 200 to a query parameter
               # it did not have.
               mcp_enabled: bool = False,
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

    def _monitor_notify(source: str, title: str, body: str,
                        dedupe_key: str | None) -> bool:
        """Emit a dead-man alert. Returns whether it was ACCEPTED for delivery.

        THE RETURN VALUE IS THE FIX (CG-76). This function used to return None
        and swallow two different failures:

        1. `except HTTPException` — the comment said "no alert route
           configured", but the CATCH is wider than the comment. Every
           `RegistryError` becomes an HTTPException in `emit_notification`, and
           `route_for` raises it on FOUR conditions: the source app is not
           registered, there is no `alert` route and no `default`, the app may
           not send as the routed identity, or that identity no longer exists.
           All four were logged and then forgotten.
        2. `{"status": "deduped"}` — returned, and discarded. Spec §2.4
           measures a genuinely NEW outage being deduped against the PREVIOUS
           outage's alert, one hour earlier.

        Still catches rather than raising: a permanent registry
        misconfiguration must not kill the scan loop, and it must not be
        reported as a transient fault either. `scan_once` counts the `False`
        and declines to mark the check, so the alert re-fires next scan and
        self-heals the moment the route is restored.
        """
        try:
            result = emit_notification(source, Notification(
                severity="alert", title=title, body=body, dedupe_key=dedupe_key,
            ))
        except HTTPException as exc:  # registry cannot route this alert
            log.record(source, "heartbeat", title, "failed", f"no route: {exc.detail}")
            return False
        if result.get("status") != "enqueued":
            # Belt and braces. D4 removes the only cause of this by passing no
            # dedupe_key from the dead-man path, so on today's code this branch
            # is unreachable — kept because the failure it guards is SILENT and
            # a future severity/route change could reintroduce it.
            log.record(source, "heartbeat", title, "failed",
                       f"not accepted for delivery: {result.get('status')}")
            return False
        return True

    monitor = HeartbeatMonitor(checks, _monitor_notify, interval_seconds=monitor_interval)

    # expose the moving parts for __main__ and tests
    app.state.dispatcher = dispatch
    app.state.monitor = monitor
    app.state.delivery_log = log
    app.state.heartbeats = checks
    app.state.sweeper = sweeper

    # CG-80. Mounted, not always-on: `/mcp` is a new authenticated surface and
    # this repo's posture on those is conservative. The router depends on the
    # SAME authenticate() every /v1/ route depends on — hard rule #4 satisfied
    # by reuse rather than by a second implementation that could drift.
    app.state.mcp_enabled = mcp_enabled
    if mcp_enabled:
        from .mcp import build_router

        app.include_router(build_router(registry, adapters))

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
        # CG-76 / spec §4.2. A dead-man check whose alert could never be routed
        # is a check that will go missed and tell nobody. Refuse it HERE — at
        # the moment the mistake is made, to the party who can fix it — rather
        # than discovering it 24h into an outage. `registry.example.yaml` gives
        # `aiteam-harness` and `job-hunter` no `routes:` block at all, so this
        # is not hypothetical for two of the three registered consumers.
        #
        # ⚠ ONLY WHEN THE CHECK DOES NOT ALREADY EXIST, and that condition is
        # load-bearing rather than an optimization. THIS ENDPOINT IS ALSO THE
        # LIVENESS PING — "Registering and refreshing are the **same call**"
        # (docs/consumers/aitrader.md §2). Spec §4.2 reasons entirely about
        # REGISTRATION and never considered that the same route carries the
        # heartbeat itself.
        #
        # A blanket refusal was measured end-to-end against a real server:
        # remove a LIVE source's alert route, and its on-schedule pings start
        # returning 422 — so `last_seen` freezes, the check drifts into
        # `is_missed`, and the moment the route is restored the gateway
        # delivers `[ALERT] heartbeat missed: daily-run` for a source that
        # never stopped pinging. A registry misconfiguration becomes a
        # FABRICATED outage, on the very source this feature exists to watch.
        # The dead-man switch must never be the thing that invents the death.
        #
        # So the split is: a NEW check with no alert route is a mistake being
        # made right now, by the party who can fix it, and is refused. An
        # EXISTING check's refresh is a LIVENESS SIGNAL and is always accepted.
        # A route removed AFTER registration is covered by the RUNTIME half of
        # D2 (§4.3) — `alerts_undeliverable` degrades /healthz, and the check
        # is left unmarked so it self-heals the moment the route returns.
        #
        # NOT "at boot": checks arrive at runtime and persist across restarts,
        # so registration is this object's equivalent of boot. And a snapshot
        # cannot be the whole fix — a route can be removed AFTER a check is
        # registered — which is why `alerts_undeliverable` exists as well.
        #
        # Read through the public per-source `list_for`, not the store's map:
        # the same accessor `GET /v1/heartbeat/{source}` uses, already scoped
        # to one tenant, so this cannot become a cross-tenant read.
        #
        # `str(exc)` is safe: `RegistryError`'s message is authored in
        # `registry.py` and names identities, never URLs (hard rule #2).
        if not any(c.check_id == h.check_id for c in checks.list_for(app_id)):
            try:
                registry.route_for(app_id, "alert")
            except RegistryError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=(f"cannot register a dead-man check: this app has no "
                            f"route for alert-severity notifications, so a missed "
                            f"check could never be delivered ({exc}). Add "
                            f"routes: {{alert: <identity>}} to the registry"),
                ) from exc
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
    def healthz(strict: bool = False):
        """Honest health: real resolvability + real liveness — never a
        hardcoded OK (claude-mem pilot lesson; aiteam plan F18 gate 2).

        `status` is computed FROM `reasons`, not alongside it. Anything that can
        make this endpoint degraded must be able to say so in words, because an
        operator seeing "degraded" and no reason has to diff the body against a
        known-good copy to learn anything.

        **`?strict=1` returns 503 when `reasons` is non-empty, 200 otherwise —
        with a BYTE-IDENTICAL body** (CG-59). The plain form always answered
        200, which is correct for a hand-run gateway (a human reads the JSON)
        and a real gap for a deployed one: a Homepage `siteMonitor` tile and a
        container health check both judge by STATUS CODE, so the tile reads
        green while inbound is dead. That is the claude-mem failure rule #5
        exists because of, occurring one layer up — against an endpoint that is
        itself scrupulously honest. `/healthz` is not lying; the thing reading
        it cannot hear it.

        **Additive, and NOT the default**, for two reasons that point the same
        way: the plain form is a published contract with existing readers, and
        a 503 from a *container* health check would make Docker restart a
        gateway that is degraded but WORKING — one unresolved env var on a
        tier-1-only host. Opt-in puts the choice with the reader.

        The trigger is `reasons` being non-empty, not `status` — `status` is
        derived from `reasons` two lines below the only return in this
        function, so the two cannot disagree, and keying on the source rather
        than on the rendering keeps it that way if a third status word is ever
        added. This adds a status code and no data: rules #2 and #6 are
        untouched because nothing new is emitted at all.

        ⚠ **`strict` is a BOOL, so `?strict=1` is the URL a probe must use.** A
        bare `?strict`, an empty `?strict=`, or anything unparseable is a 422
        with a validation body — the one input class where "identical body
        either way" does not hold, and a probe misconfigured that way reads
        DOWN on a healthy gateway. Recorded rather than widened: that is the
        LOUD direction, and this endpoint's whole subject is the silent one.
        Pinned by
        `test_an_unparseable_strict_value_is_a_422_and_NOT_a_health_verdict`.

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
                         # CG-76 door 3. The in-process sibling of the two
                         # `*_at_boot` counters above: a job accepted with a
                         # 202 whose retry ladder then ran out. Same family,
                         # same reason, and it was the one member with no
                         # counter.
                         "delivery_failures": getattr(dispatch, "delivery_failures", 0),
                         # Journal lines that did not parse, and journal
                         # writes that failed. A torn trailing line is
                         # the expected shape after a power loss and is
                         # deliberately not fatal (journal.py) — but a
                         # mechanism whose whole purpose is surviving
                         # something nobody watched must say when it lost
                         # something. Rule #5.
                         "journal_skipped_lines": _journal_skipped(dispatch, inbox),
                         "journal_write_errors": _journal_write_errors(dispatch, inbox),
                         # CG-75. Audit-file writes that failed. Sibling of the
                         # line above and counted for the same reason: this
                         # write used to RAISE, which turned a full disk into an
                         # unbounded re-send storm. It no longer raises, so this
                         # counter is the only thing that says so.
                         "audit_write_errors": _audit_write_errors(dispatch, log),
                         # CG-74. What `thread_alive` and `last_pass_at`
                         # together still could not say: whether a loop that has
                         # stopped completing passes is WEDGED or RAISING.
                         # Cumulative is history and drives nothing; consecutive
                         # returns to zero on the next good pass and is the one
                         # that degrades — `RetentionSweeper`'s split, for
                         # `RetentionSweeper`'s measured reason.
                         "pass_failures": getattr(dispatch, "pass_failures", 0),
                         "consecutive_pass_failures": getattr(
                             dispatch, "consecutive_pass_failures", 0),
                         "last_pass_error": getattr(dispatch, "last_pass_error", None),
                         # CG-72. The third way of judging outbound, and the one
                         # nothing else can substitute for. `pending_jobs` cannot
                         # do it: a dead dispatcher and a busy one both show a
                         # non-zero number, and an idle deployment shows zero
                         # either way. Counters see nothing when a loop stops
                         # raising as well as stops working.
                         "thread_alive": dispatch.is_alive(),
                         # ...and without this, `thread_alive: false` is
                         # ambiguous: a dispatcher that was never started looks
                         # identical to one that died, and only the second is a
                         # fault. Every offline test is the first case.
                         "thread_started": dispatch.started,
                         "last_pass_at": (dispatch.last_pass_at.isoformat()
                                          if dispatch.last_pass_at else None),
                         "seconds_since_last_pass": (
                             round((now - dispatch.last_pass_at).total_seconds(), 1)
                             if dispatch.last_pass_at else None),
                         "stale_after_seconds": _dispatch_stale_after(dispatch),
                         "pass_interval_seconds": dispatch.interval_seconds},
            "heartbeats": {"checks": len(hb_all),
                           "missed": sum(1 for c in hb_all if c.status == "missed"),
                           "last_scan_at": monitor.last_scan_at.isoformat() if monitor.last_scan_at else None,
                           # CG-72. `last_scan_at` was already published and
                           # already frozen-at-a-real-timestamp when the thread
                           # dies, which is exactly what made it read as healthy.
                           # These three are what turn it into a signal.
                           "thread_alive": monitor.is_alive(),
                           "thread_started": monitor.started,
                           "seconds_since_last_scan": (
                               round((now - monitor.last_scan_at).total_seconds(), 1)
                               if monitor.last_scan_at else None),
                           "stale_after_seconds": _scan_stale_after(monitor),
                           "scan_interval_seconds": monitor.interval_seconds,
                           # CG-74. The dispatcher's twin, with one asymmetry:
                           # `scan_failures` DEGRADES cumulatively where
                           # `pass_failures` is inert. ⚠ The REASON it does
                           # expired with CG-76 and the surviving one is
                           # weaker; it has ONE home and this is not it —
                           # `HeartbeatMonitor.__init__`. Do not restate it
                           # here, which is what the copy this replaced did.
                           "scan_failures": getattr(monitor, "scan_failures", 0),
                           "consecutive_scan_failures": getattr(
                               monitor, "consecutive_scan_failures", 0),
                           "last_scan_error": getattr(monitor, "last_scan_error", None),
                           # CG-76. What `scan_failures` could not say: an alert
                           # can be dropped without any scan raising. Three
                           # paths did it — a route refusal, a dedupe, and a
                           # ladder exhaustion — and all three returned
                           # normally. Bare integers: /healthz is
                           # unauthenticated (CG-12), and the identifying detail
                           # is on the authenticated GET /v1/deliveries.
                           "alerts_undeliverable": getattr(
                               monitor, "alerts_undeliverable", 0),
                           "checks_undeliverable": getattr(
                               monitor, "checks_undeliverable", 0),
                           # CG-76 door 5. `hb_all` above filters the census
                           # through `registry.apps`, so a check whose source
                           # was renamed or removed drops out of BOTH `checks`
                           # and `missed` — measured: `checks: 1 -> 0` on a
                           # rename, while the store still held it, still
                           # scanned it, and its alert still died through the
                           # `unknown app` branch of `route_for`. Under-
                           # reporting coverage is worse than reporting none:
                           # `checks: 0` reads as "nothing to worry about".
                           #
                           # A SECOND NUMBER, not an unfiltered `hb_all` —
                           # widening that would silently change what `checks`
                           # and `missed` mean, and three docs describe them.
                           "checks_orphaned": _checks_orphaned(registry, checks)},
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
        if queue["audit_write_errors"]:
            reasons.append(
                f"delivery log: {queue['audit_write_errors']} audit write(s) "
                "FAILED since start — those deliveries have NO on-disk record, "
                "and the per-app inbound audit files cannot substitute because "
                "they record what arrived, never what left. Delivery itself is "
                "unaffected (the write is deliberately swallowed rather than "
                "raised, CG-75). CUMULATIVE and will not clear while this "
                "process runs. Check free space and the state dir's permissions"
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
        if queue["delivery_failures"]:
            reasons.append(
                f"delivery: {queue['delivery_failures']} accepted job(s) "
                "exhausted the retry ladder and were DROPPED — the gateway "
                "returned 202 for them and did not deliver them. Roughly 73 "
                "minutes of a Chat endpoint being unreachable is the shape. "
                "CUMULATIVE; `GET /v1/deliveries` names which"
            )
        # CG-72. Outbound delivery's liveness, in the subscriber block's shape
        # and for the subscriber block's reason. Not gated on `enabled` — there
        # is no such thing as a deployment without outbound delivery; it is
        # gated on `thread_started`, because the 23 offline tests that build an
        # app and never start a thread must stay silent (CG-68 audit F0 is the
        # same lesson with a KeyError instead of a false alarm).
        #
        # An `elif` chain: a dead thread also looks stale, and two reasons for
        # one fault is noise.
        #
        # WHAT THE COUNTER BRANCH BUYS THE STALENESS STRING BELOW, AND WHY THE
        # TWO MUST NOT BE REORDERED. The subscriber's and the sweeper's
        # staleness lines end *"neither completing nor raising, so it is wedged
        # rather than erroring"*. They may say that because a failure-counter
        # branch sits ABOVE them in the same chain (`consecutive_poll_failures`,
        # `consecutive_sweep_failures`), so by the time their `elif` is reached
        # "not raising" has already been measured. Until CG-74 `Dispatcher` and
        # `HeartbeatMonitor` counted nothing, so both strings here hedged in
        # words: they said the loop was "either WEDGED or RAISING" and that this
        # block could not tell you which. CG-74 added
        # `consecutive_pass_failures` / `consecutive_scan_failures` and the two
        # branches that read them, so the hedge is gone and the WEDGED wording
        # below is EARNED BY THE BRANCH ABOVE IT rather than asserted. Move the
        # counter branch under the staleness branch and both strings become
        # claims this endpoint cannot support again (hard rule #5).
        #
        # WHERE THE ORDERING DEPARTS FROM THE CHAIN IT OTHERWISE MIRRORS, AND
        # WHY IT MUST NOT BE "UNIFIED" ONTO IT. This chain — and the heartbeat
        # one below, which matches it — runs dead-thread → counter →
        # never-completed → stale. The subscriber's runs never-polled → counter
        # → dead-thread → stale. Deliberate: a dead thread increments no counter
        # and is the most actionable of the four (restart), while a raising loop
        # EXPLAINS "no pass has ever completed" when it is the cause, so the
        # counter has to be asked before that branch swallows the event. Each
        # order is recorded where it lives; neither is a copy of the other.
        #
        # REACHABLE, and it WAS reachable through this exact door until CG-75.
        # `DeliveryLog.record` did a raw `mkdir`/`open`/`write` with no guard, so
        # a full disk raised `OSError` straight out of `process_due` — and only
        # on passes that HAD work. Measured at the time: one message, one
        # successful send, then sixty sends to Google in sixty seconds, because
        # the job never left `_jobs` and the delivered path never advances
        # `next_attempt_at`. On the RETRY path the opposite: the raise landed
        # after the backoff had already been applied, so the job sat 30s or more
        # from its next attempt, every pass in between was empty, every empty
        # pass stamped, and this branch did not fire for the whole 72.5-minute
        # backoff ladder.
        #
        # THAT BLINDNESS WAS BOUNDED, NOT PERMANENT — measured, and said plainly
        # so nobody reads CG-74 as the only thing that would ever have surfaced
        # it. Run past the ladder and `job.attempts` reaches its length, the
        # give-up branch calls `_finish`, and the retry path degenerates into the
        # delivered path's one-send-per-second storm; staleness then fires. The
        # window in which /healthz was blind was long (72.5 minutes) and finite,
        # and the thing that ended it was the failure getting WORSE. That is a
        # narrowing of CG-74's filed claim, not a refutation of it.
        #
        # CG-75 closed that door: the audit write is guarded inside
        # `DeliveryLog.record` and counted at `delivery.audit_write_errors`,
        # which degrades. A full disk now shows up there and at
        # `journal_write_errors`, not as a storm and not as silence. The counter
        # branch below is for everything ELSE that can raise out of this loop —
        # which is what made it a decision (a new degrade input on an endpoint
        # consumers alarm on) rather than a wording fix, and why it shipped as
        # its own row.
        if queue["thread_started"] and not queue["thread_alive"]:
            reasons.append(
                "delivery: the dispatch thread was started and is NOT RUNNING — "
                "nothing queued will ever be sent and no counter in this block "
                "will move again. `pending_jobs` will climb and every other "
                "field is frozen at a real value, which is why this looks "
                "healthy; restart the service"
            )
        elif queue["thread_started"] and (
                queue["consecutive_pass_failures"] >= DISPATCH_FAILURE_THRESHOLD):
            reasons.append(
                f"delivery: {queue['consecutive_pass_failures']} consecutive "
                f"dispatch passes have RAISED (last: {queue['last_pass_error']}) "
                "— outbound is failing loudly rather than silently. Queued jobs "
                "are not being sent and `pending_jobs` will climb"
            )
        elif queue["thread_started"] and queue["seconds_since_last_pass"] is None:
            reasons.append(
                "delivery: the dispatch thread was started but no pass has ever "
                "completed — the loop runs every "
                f"{queue['pass_interval_seconds']}s and stamps even an empty "
                "pass, so this should be impossible and nothing is being "
                "delivered"
            )
        elif queue["thread_started"] and queue["thread_alive"] and (
                queue["seconds_since_last_pass"] > queue["stale_after_seconds"]):
            reasons.append(
                f"delivery: the thread is alive but the last completed pass was "
                f"{queue['seconds_since_last_pass']}s ago, over the "
                f"{queue['stale_after_seconds']}s budget, and fewer than "
                f"{DISPATCH_FAILURE_THRESHOLD} consecutive passes have raised — "
                "so passes are neither completing nor raising, and the loop is "
                "WEDGED rather than erroring. A send blocked past its client "
                "timeout is the shape: `process_due` walks due jobs "
                "sequentially, so one hung send holds the whole loop"
            )
        # ...and the dead-man switch's own liveness. Same chain, same order.
        # A heartbeat monitor that has died stops evaluating every consumer's
        # checks while `missed` and `last_scan_at` both hold real values.
        hb = body["heartbeats"]
        if hb["thread_started"] and not hb["thread_alive"]:
            reasons.append(
                "heartbeats: the scan thread was started and is NOT RUNNING — "
                "no registered check is being evaluated, so a source that has "
                "gone silent will never be alerted on. `missed` and "
                "`last_scan_at` are frozen at real values; restart the service"
            )
        elif hb["thread_started"] and (
                hb["consecutive_scan_failures"] >= SCAN_FAILURE_THRESHOLD):
            reasons.append(
                f"heartbeats: {hb['consecutive_scan_failures']} consecutive "
                f"scans have RAISED (last: {hb['last_scan_error']}) — the "
                "dead-man monitor is not evaluating any registered check, so a "
                "source that has gone silent will never be alerted on"
            )
        elif hb["thread_started"] and hb["seconds_since_last_scan"] is None:
            reasons.append(
                "heartbeats: the scan thread was started but no scan has ever "
                "completed — the dead-man monitor has never run on this process"
            )
        elif hb["thread_started"] and hb["thread_alive"] and (
                hb["seconds_since_last_scan"] > hb["stale_after_seconds"]):
            reasons.append(
                f"heartbeats: the thread is alive but the last completed scan "
                f"was {hb['seconds_since_last_scan']}s ago, over the "
                f"{hb['stale_after_seconds']}s budget for a "
                f"{hb['scan_interval_seconds']}s-interval loop, and fewer than "
                f"{SCAN_FAILURE_THRESHOLD} consecutive scans have raised — so "
                "scans are neither completing nor raising, and the dead-man "
                "monitor is WEDGED rather than erroring. No registered check is "
                "being evaluated while this holds"
            )
        # OUTSIDE the elif chain above, deliberately. The chain answers "is this
        # loop running", at most one reason. This answers a different question —
        # "has an alert already been lost" — and both can be true at once. It is
        # the one cumulative counter in these two blocks that degrades; the
        # asymmetry with `delivery.pass_failures` is recorded at
        # `HeartbeatMonitor.__init__` and is measured, not stylistic.
        if hb["scan_failures"]:
            reasons.append(
                f"heartbeats: {hb['scan_failures']} scan(s) have raised since "
                "start — since CG-76 a raising scan does NOT drop the alert "
                "(the check is no longer marked before the notify is accepted), "
                "so the risk is a DELAYED or DUPLICATED alert rather than a "
                "lost one. CUMULATIVE and will not clear while this process "
                "runs; `consecutive_scan_failures` is the live signal, and "
                "`alerts_undeliverable` is the counter for an alert actually "
                "lost"
            )
        # OUTSIDE the liveness elif-chain, beside `scan_failures` and for the
        # same reason: the chain answers "is this loop running", this answers
        # "has an alert already been lost", and both can be true at once.
        #
        # TWO NUMBERS, and they say different things. The gauge is the live
        # signal — a registry the operator can fix right now. The cumulative one
        # is the report of loss and does not clear.
        if hb["checks_undeliverable"]:
            reasons.append(
                f"heartbeats: {hb['checks_undeliverable']} registered check(s) "
                "came due and their alert could NOT be routed — the source has "
                "no `alert` route, no `default` route, or its routed identity "
                "is gone from the registry. Those sources are silently "
                "unmonitored: the check will keep re-firing and will deliver "
                "as soon as the registry is fixed. `GET /v1/deliveries` names "
                "which"
            )
        if hb["alerts_undeliverable"]:
            reasons.append(
                f"heartbeats: {hb['alerts_undeliverable']} dead-man alert "
                "ATTEMPT(s) were not accepted for delivery since start — a "
                "source that went silent was not reported on. This counts "
                "ATTEMPTS, not distinct alerts: a check whose route stays "
                "broken is deliberately re-attempted on EVERY scan so it "
                "self-heals, so one unreported source contributes one count "
                "per scan interval (~1440/day at the 60s default). "
                "`checks_undeliverable` above is how many distinct CHECKS are "
                "affected — read that for the size of the fault. CUMULATIVE "
                "and will not clear while this process runs. "
                "`GET /v1/deliveries` names which"
            )
        if hb["checks_orphaned"]:
            reasons.append(
                f"heartbeats: {hb['checks_orphaned']} registered check(s) "
                "belong to a source that is NOT a registered app — renamed, "
                "removed, or a registry block that failed to load. They are "
                "still scanned and their alerts still fail, but they are "
                "excluded from `checks` and `missed` above, so those two "
                "numbers UNDER-REPORT this deployment's dead-man coverage. "
                "`GET /v1/deliveries` names which"
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
            # The three silence checks — one `elif` chain with the failure check
            # above it, in the subscriber block's order and for the subscriber
            # block's reason: a loop that is loudly failing has a more
            # actionable reason already, and a dead thread will also look stale.
            # A dead thread and a frozen timestamp are ONE fault, so at most one
            # of these four may speak at a time.
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
        #
        # CG-59: the code is the ONLY thing `strict` changes. The content dict
        # is built once and handed to both paths, so a reader diffing the two
        # forms cannot find a difference — if it could, an operator comparing
        # them would learn something false.
        return JSONResponse(status_code=503 if (strict and reasons) else 200,
                            content={"status": "degraded" if reasons else "ok",
                                     "reasons": reasons, **body})

    return app
