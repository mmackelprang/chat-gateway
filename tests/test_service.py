"""The HTTP surface end to end, with a fake delivery adapter."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from chat_gateway.envelope import DeliveryResult, InboundReply
from chat_gateway.inbox import Inbox
from chat_gateway.registry import load_registry
from chat_gateway.service import create_app

REGISTRY_YAML = """
identities:
  pm-familyworkspace:
    display: "PM · familyworkspace"
    mode: webhook
    webhook_url_env: SVC_HOOK_FW
    space: "spaces/AAA"
apps:
  aiteam-harness:
    key_env: SVC_KEY_AITEAM
    identities: [pm-familyworkspace]
"""


class FakeAdapter:
    def __init__(self):
        self.sent = []

    def send(self, identity, message):
        self.sent.append((identity.name, message))
        return DeliveryResult(status="delivered", channel="google_chat",
                              identity=identity.name, mode=identity.mode,
                              thread_key=message.thread_key)


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SVC_KEY_AITEAM", "cgk_test_key")
    monkeypatch.setenv("SVC_HOOK_FW", "https://x.example/hook")
    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    registry = load_registry(p)
    inbox = Inbox()
    adapter = FakeAdapter()
    app = create_app(registry, inbox, {"webhook": adapter})
    return TestClient(app), inbox, adapter


AUTH = {"Authorization": "Bearer cgk_test_key"}


def test_send_happy_path(env):
    client, _, adapter = env
    resp = client.post("/v1/messages", headers=AUTH, json={
        "identity": "pm-familyworkspace", "text": "hello", "thread_key": "t1"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "delivered"
    assert adapter.sent[0][0] == "pm-familyworkspace"


def test_auth_and_permission_errors(env):
    client, _, _ = env
    assert client.post("/v1/messages", json={"identity": "x", "text": "hi"}).status_code == 401
    assert client.post("/v1/messages", headers={"Authorization": "Bearer nope"},
                       json={"identity": "x", "text": "hi"}).status_code == 401
    resp = client.post("/v1/messages", headers=AUTH,
                       json={"identity": "other-identity", "text": "hi"})
    assert resp.status_code == 403
    assert "may not send as" in resp.json()["detail"]


def test_validation_and_unconfigured_mode(env, tmp_path, monkeypatch):
    client, _, _ = env
    assert client.post("/v1/messages", headers=AUTH, json={"identity": "pm-familyworkspace",
                                                           "text": ""}).status_code == 422
    # a mode with no adapter -> 503
    registry_yaml = REGISTRY_YAML.replace("mode: webhook", "mode: app").replace(
        "webhook_url_env: SVC_HOOK_FW", "webhook_url_env: SVC_HOOK_FW")
    p = tmp_path / "r2.yaml"
    p.write_text(registry_yaml, encoding="utf-8")
    app2 = create_app(load_registry(p), Inbox(), {"webhook": FakeAdapter()})
    c2 = TestClient(app2)
    resp = c2.post("/v1/messages", headers=AUTH,
                   json={"identity": "pm-familyworkspace", "text": "hi"})
    assert resp.status_code == 503
    assert "tier not enabled" in resp.json()["detail"]


def test_inbox_and_identities(env):
    client, inbox, _ = env
    inbox.put(InboundReply(app="aiteam-harness", space="spaces/AAA", text="yes",
                           received_at=dt.datetime.now(dt.timezone.utc)))
    resp = client.get("/v1/inbox", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert resp.json()["replies"][0]["text"] == "yes"
    assert client.get("/v1/inbox", headers=AUTH).json()["count"] == 0  # poll clears
    idents = client.get("/v1/identities", headers=AUTH).json()["identities"]
    assert idents == [{"name": "pm-familyworkspace", "display": "PM · familyworkspace",
                       "mode": "webhook", "ready": True}]


def test_healthz_honest(env, monkeypatch):
    client, _, _ = env
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["registry"]["identities"]["pm-familyworkspace"]["env_resolved"] is True
    assert body["subscriber"]["enabled"] is False
    monkeypatch.delenv("SVC_HOOK_FW")
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"


def test_healthz_reports_real_subscriber_counters(env, tmp_path, monkeypatch):
    """Hard rule #5: the subscriber block must read the loop's REAL counters.
    A defaulted getattr() would report a hardcoded 0 forever after a rename —
    exactly the silent-health failure this rule exists to prevent.

    The exact-dict assertion is deliberate: a subset check would let a silent
    rename ship."""
    from chat_gateway.adapters.pubsub import FakePuller, SubscriberLoop

    monkeypatch.setenv("GATEWAY_GCP_BILLING", "disabled")
    _, inbox, adapter = env
    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    registry = load_registry(p)
    loop = SubscriberLoop(FakePuller(), registry, inbox, interval_seconds=5.0)
    loop.events_seen, loop.unparseable_seen, loop.dispatch_errors = 9, 2, 3
    loop.interactions_without_action_id = 5
    # Distinct values, and distinct from every other counter here: the two CG-12
    # integers must be reported separately, and a copy-paste that reported one
    # of them twice would pass against a shared value.
    loop.suppressed_opt_out, loop.suppressed_not_authorized = 11, 4
    # A FIXED past instant, so `seconds_since_last_poll` is computed from the
    # real clock and cannot be a hardcoded 0 — the same reasoning as the
    # counters. Asserted as a range, because it is genuinely time-dependent.
    loop.last_poll_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=42)

    client = TestClient(create_app(registry, inbox, {"webhook": adapter}, loop))
    sub = client.get("/healthz").json()["subscriber"]
    since = sub.pop("seconds_since_last_poll")
    assert 42.0 <= since < 60.0, f"staleness is not being measured: {since}"
    assert sub == {
        "enabled": True, "last_poll_at": loop.last_poll_at.isoformat(),
        "events_seen": 9, "unparseable_seen": 2, "dispatch_errors": 3,
        "interactions_without_action_id": 5,
        "suppressed_opt_out": 11, "suppressed_not_authorized": 4,
        "poll_failures": 0, "consecutive_poll_failures": 0, "last_poll_error": None,
        # Never started, so not alive — and /healthz must not call that a death.
        "thread_alive": False, "thread_started": False,
        "poll_interval_seconds": 5.0, "stale_after_seconds": 300.0,
        "billing_declared": "disabled",
        "quota_note": ("free-tier exhaustion fails CLOSED — inbound stops with no "
                       "other symptom; consecutive_poll_failures is the signal"),
    }


# --- honest liveness: status is computed FROM reasons (CG-7) ------------------


def _loop_with(tmp_path, inbox, **attrs):
    from chat_gateway.adapters.pubsub import FakePuller, SubscriberLoop

    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    registry = load_registry(p)
    loop = SubscriberLoop(FakePuller(), registry, inbox)
    for k, v in attrs.items():
        setattr(loop, k, v)
    return registry, loop


def test_healthz_degrades_when_subscriber_has_never_polled(env, tmp_path):
    """The claude-mem failure shape, exactly: green health over a dead input.

    An enabled subscriber with last_poll_at=None has never successfully reached
    Pub/Sub on this process. Before this, healthz reported "ok" indefinitely.
    """
    _, inbox, adapter = env
    registry, loop = _loop_with(tmp_path, inbox)          # last_poll_at stays None
    client = TestClient(create_app(registry, inbox, {"webhook": adapter}, loop))
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    assert any("never completed a poll" in r for r in body["reasons"])


def test_healthz_degrades_on_consecutive_poll_failures_and_recovers(
        env, tmp_path, monkeypatch):
    """Quota exhaustion, a revoked key and a deleted subscription are
    indistinguishable from in-process and all fail CLOSED — so the signal is the
    failure run, not the cause. And it must clear on recovery, not stick."""
    from chat_gateway.service import POLL_FAILURE_THRESHOLD, ROUTING_TARGET_ENV

    # A configured deployment, so the poll-failure run is the ONLY reason and
    # the recovery assertion below is about it and nothing else.
    monkeypatch.setenv(ROUTING_TARGET_ENV, "projects/p/topics/t")
    _, inbox, adapter = env
    registry, loop = _loop_with(
        tmp_path, inbox,
        last_poll_at=dt.datetime(2026, 7, 29, 12, 0, tzinfo=dt.timezone.utc),
        poll_failures=7,
        consecutive_poll_failures=POLL_FAILURE_THRESHOLD,
        last_poll_error="PubSubError HTTP 429",
    )
    client = TestClient(create_app(registry, inbox, {"webhook": adapter}, loop))
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    assert any("HTTP 429" in r and "inbound is DOWN" in r for r in body["reasons"])

    loop.consecutive_poll_failures = 0
    loop.last_poll_error = None
    body = client.get("/healthz").json()
    assert body["status"] == "ok" and body["reasons"] == []
    assert body["subscriber"]["poll_failures"] == 7      # history is not erased


def test_healthz_degrades_when_tier2_is_on_but_no_routing_target(
        env, tmp_path, monkeypatch):
    """CG-13's leftover. Tier 2 enabled with no routing target is not an
    unconfigured extra: card interactions are IMPOSSIBLE, /v1/identities already
    tells every producer so, and nothing else on this endpoint would show it."""
    from chat_gateway.service import ROUTING_TARGET_ENV

    monkeypatch.delenv(ROUTING_TARGET_ENV, raising=False)
    _, inbox, adapter = env
    registry, loop = _loop_with(
        tmp_path, inbox,
        last_poll_at=dt.datetime(2026, 7, 29, 12, 0, tzinfo=dt.timezone.utc),
    )
    client = TestClient(create_app(registry, inbox, {"webhook": adapter}, loop))
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    reason = next(r for r in body["reasons"] if ROUTING_TARGET_ENV in r)
    assert "topics/<TOPIC>" in reason          # says what to set, not just that it is unset

    # ...and it is not raised when tier 2 is off: with no subscriber there is no
    # inbound path for a routing target to be missing from.
    off = TestClient(create_app(registry, inbox, {"webhook": adapter})).get("/healthz").json()
    assert off["status"] == "ok" and off["reasons"] == []


def test_healthz_degrades_when_the_polling_thread_died(env, tmp_path, monkeypatch):
    """THE HOLE THE COUNTERS CANNOT SEE — rule #5's founding shape, one layer in.

    A loop that has stopped RAISING as well as stopped working increments
    nothing. `consecutive_poll_failures` sits at 0, `last_poll_error` stays
    None, `last_poll_at` holds a real recent timestamp — every counter reads
    healthy — and inbound is dead forever. CG-7's original two reasons ("never
    polled" / "N consecutive failures") are both blind to it, so before this
    check `/healthz` reported "ok" indefinitely, exactly as it did before CG-7.

    `_run` catches `Exception`, so reaching this needs a `BaseException` (e.g.
    MemoryError) or an interpreter-shutdown race — unlikely, but the failure is
    unbounded and silent, which is the combination rule #5 refuses to accept.
    """
    from chat_gateway.service import ROUTING_TARGET_ENV

    monkeypatch.setenv(ROUTING_TARGET_ENV, "projects/p/topics/t")
    _, inbox, adapter = env
    registry, loop = _loop_with(
        tmp_path, inbox,
        # Fresh: no failures, and a poll that succeeded one second ago.
        last_poll_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1),
    )
    client = TestClient(create_app(registry, inbox, {"webhook": adapter}, loop))

    # Not started yet: not alive, but that is NOT a death — nothing to report.
    body = client.get("/healthz").json()
    assert body["subscriber"]["thread_alive"] is False
    assert body["subscriber"]["thread_started"] is False
    assert body["status"] == "ok", "an unstarted loop must not be called a corpse"

    # Now start it for real, then kill the thread the way a BaseException would.
    loop.start()
    assert loop.is_alive() and loop.started
    assert client.get("/healthz").json()["status"] == "ok"
    loop.stop()                                   # thread exits; `started` stays True
    assert not loop.is_alive()

    body = client.get("/healthz").json()
    assert body["subscriber"]["thread_started"] is True
    assert body["subscriber"]["thread_alive"] is False
    # The counters still look perfect — that is the whole point.
    assert body["subscriber"]["consecutive_poll_failures"] == 0
    assert body["subscriber"]["last_poll_error"] is None
    assert body["status"] == "degraded", "a dead polling thread reported healthy"
    assert any("NOT RUNNING" in r for r in body["reasons"]), body["reasons"]


def test_healthz_degrades_when_polls_go_silent_without_failing(
        env, tmp_path, monkeypatch):
    """A thread that is alive but wedged: no failures, no progress.

    Distinct from the dead-thread case above and from the failure-run case —
    here `is_alive()` is True and every counter is clean, so the ONLY available
    signal is wall-clock distance from `last_poll_at`. Before this, that
    timestamp was reported but never compared to the clock, so a three-week-old
    value read exactly like a three-second-old one on an endpoint whose
    docstring claims "real liveness".
    """
    from chat_gateway.service import (POLL_STALE_AFTER_SECONDS, ROUTING_TARGET_ENV)

    monkeypatch.setenv(ROUTING_TARGET_ENV, "projects/p/topics/t")
    _, inbox, adapter = env
    registry, loop = _loop_with(tmp_path, inbox)
    loop.start()
    try:
        client = TestClient(create_app(registry, inbox, {"webhook": adapter}, loop))
        loop.last_poll_at = dt.datetime.now(dt.timezone.utc)
        assert client.get("/healthz").json()["status"] == "ok"

        # Just inside the budget: still healthy, so this is a real boundary and
        # not a check that fires on any nonzero staleness.
        loop.last_poll_at = (dt.datetime.now(dt.timezone.utc)
                             - dt.timedelta(seconds=POLL_STALE_AFTER_SECONDS - 30))
        body = client.get("/healthz").json()
        assert body["status"] == "ok", body["reasons"]

        # Just outside it.
        loop.last_poll_at = (dt.datetime.now(dt.timezone.utc)
                             - dt.timedelta(seconds=POLL_STALE_AFTER_SECONDS + 30))
        body = client.get("/healthz").json()
        sub = body["subscriber"]
        assert loop.is_alive() and sub["thread_alive"] is True
        assert sub["consecutive_poll_failures"] == 0 and sub["last_poll_error"] is None
        assert sub["seconds_since_last_poll"] > sub["stale_after_seconds"]
        assert body["status"] == "degraded", "a wedged subscriber reported healthy"
        assert any("wedged rather than erroring" in r for r in body["reasons"])
    finally:
        loop.stop()


def test_healthz_staleness_budget_scales_with_a_slow_interval(env, tmp_path):
    """A deployment that deliberately polls slowly must not alarm forever.

    The budget is max(floor, multiple x interval), so a 10-minute interval gets
    a proportionate budget rather than the 300s floor.
    """
    from chat_gateway.adapters.pubsub import FakePuller, SubscriberLoop
    from chat_gateway.service import (POLL_STALE_AFTER_SECONDS,
                                      POLL_STALE_INTERVAL_MULTIPLE)

    _, inbox, adapter = env
    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    registry = load_registry(p)
    slow = SubscriberLoop(FakePuller(), registry, inbox, interval_seconds=600.0)
    slow.last_poll_at = dt.datetime.now(dt.timezone.utc)

    sub = TestClient(create_app(registry, inbox, {"webhook": adapter}, slow)) \
        .get("/healthz").json()["subscriber"]
    assert sub["poll_interval_seconds"] == 600.0
    assert sub["stale_after_seconds"] == 600.0 * POLL_STALE_INTERVAL_MULTIPLE
    assert sub["stale_after_seconds"] > POLL_STALE_AFTER_SECONDS


def test_healthz_reasons_explain_a_degraded_registry(env, monkeypatch):
    """`degraded` with no explanation makes an operator diff the body against a
    known-good copy. Say why."""
    client, _, _ = env
    monkeypatch.delenv("SVC_HOOK_FW")
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    assert any("does not resolve" in r for r in body["reasons"])


def test_healthz_names_the_quarantine_as_the_recovery_record(tmp_path, monkeypatch):
    """Promise site 6: this reasons line told an operator to read a file the
    sweeper is about to delete. It now names an artifact the gateway keeps."""
    from chat_gateway.inbox import Inbox
    from chat_gateway.journal import Journal

    monkeypatch.setenv("SVC_KEY_AITEAM", "cgk_test_key")
    monkeypatch.setenv("SVC_HOOK_FW", "https://x.example/hook")
    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")

    jpath = tmp_path / "inbox.jsonl"
    Journal(jpath).open(1, "inbound", {"app": "aiteam-harness", "NOT": "an InboundReply"})
    inbox = Inbox(journal=Journal(jpath), quarantine_dir=tmp_path / "quarantine")
    inbox.restore()
    client = TestClient(create_app(load_registry(p), inbox, {"webhook": FakeAdapter()}))

    body = client.get("/healthz").json()
    assert body["inbox"]["unrevivable_at_boot"] == 1
    assert body["inbox"]["quarantined_at_boot"] == 1
    assert body["inbox"]["quarantine_write_errors"] == 0
    assert body["status"] == "degraded"
    line = next(r for r in body["reasons"] if "no longer parse" in r)
    assert "quarantine" in line and "never pruned" in line
    # ...and it must NOT still point at the per-app audit trail as the only copy
    assert "the per-app JSONL audit under the inbox dir" not in line


def test_healthz_degrades_when_a_quarantine_write_FAILED(tmp_path, monkeypatch):
    """Rule #5. A recovery mechanism that has silently stopped working is worse
    than none, because it is trusted — so the failure gets its own reason, not
    just its own number. Two counters, two investigations."""
    from chat_gateway.inbox import Inbox
    from chat_gateway.journal import Journal
    from chat_gateway.retention import RetentionSweeper

    monkeypatch.setenv("SVC_KEY_AITEAM", "cgk_test_key")
    monkeypatch.setenv("SVC_HOOK_FW", "https://x.example/hook")
    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")

    jpath = tmp_path / "inbox.jsonl"
    Journal(jpath).open(1, "inbound", {"app": "aiteam-harness", "NOT": "an InboundReply"})
    blocker = tmp_path / "blocked"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    inbox = Inbox(journal=Journal(jpath), quarantine_dir=blocker / "quarantine")
    inbox.restore()
    # CG-68 pre-merge review: an ENABLED sweeper, because the two tails below
    # assert a running delete timer. They used to assert it with no sweeper at
    # all, which is the defect the two tests after this one now pin.
    sweeper = RetentionSweeper(tmp_path / "inbox-data", days=30)
    client = TestClient(create_app(load_registry(p), inbox,
                                   {"webhook": FakeAdapter()}, sweeper=sweeper))

    body = client.get("/healthz").json()
    assert body["inbox"]["quarantined_at_boot"] == 0
    assert body["inbox"]["quarantine_write_errors"] == 1
    assert body["status"] == "degraded"
    assert any("quarantine" in r and "FAILED" in r for r in body["reasons"])
    # The unrevivable line stays honest about how many were preserved: none.
    # And it must not go on to call the quarantine "the recovery record" — that
    # claim is true only of a dir that actually received the bytes, and site 6
    # became a rule-#5 problem precisely by pointing an operator somewhere they
    # would find nothing.
    line = next(r for r in body["reasons"] if "no longer parse" in r)
    assert "0 of them were preserved" in line
    assert "is the recovery record" not in line
    assert "the per-app JSONL audit under the inbox dir" in line
    # CG-68. Both of these lines told an operator the audit file "carries no
    # retention guarantee" — accurate until `retention.py` shipped, and after
    # it an unauthenticated endpoint describing machinery this process is not
    # running. The file it points at is now on a delete timer, and both lines
    # have to say so.
    assert "IS PRUNED" in line
    assert "carries no retention guarantee" not in line
    q_line = next(r for r in body["reasons"] if "quarantine" in r and "FAILED" in r)
    assert "DELETE TIMER" in q_line
    assert "carries no retention guarantee" not in q_line


def test_healthz_inbox_quarantine_fields_exist_without_a_quarantine_dir(env):
    """Every offline caller builds an `Inbox()` with no quarantine dir, and the
    block must still report real zeros rather than vanish — a field that
    disappears is a field an operator's dashboard reads as null forever."""
    client, _, _ = env
    inbox_block = client.get("/healthz").json()["inbox"]
    assert inbox_block["quarantined_at_boot"] == 0
    assert inbox_block["quarantine_write_errors"] == 0


# --- CG-68: the retention sweeper at /healthz --------------------------------

def _app_with_sweeper(tmp_path, monkeypatch, sweeper=None):
    """The file's own idiom (REGISTRY_YAML + a monkeypatched key env), with one
    knob. Not a refactor of the tests above — they build their own inboxes and
    journals, and folding them onto a shared helper would hide exactly the
    per-test wiring those tests exist to exercise."""
    monkeypatch.setenv("SVC_KEY_AITEAM", "cgk_test_key")
    monkeypatch.setenv("SVC_HOOK_FW", "https://x.example/hook")
    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    app = create_app(load_registry(p), Inbox(), {"webhook": FakeAdapter()},
                     sweeper=sweeper)
    return TestClient(app)


def test_healthz_answers_when_no_sweeper_is_configured(tmp_path, monkeypatch):
    """Audit F0: this raised KeyError, taking the whole endpoint down. Every
    offline caller builds an app without a sweeper, so the reasons block has to
    bind-then-gate rather than index the else-branch."""
    resp = _app_with_sweeper(tmp_path, monkeypatch).get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["retention"] == {"enabled": False, "note": "no sweeper configured"}
    assert body["status"] == "ok"


def test_healthz_degrades_on_a_sweeper_that_stopped_working(tmp_path, monkeypatch):
    from chat_gateway.retention import RetentionSweeper

    s = RetentionSweeper(tmp_path / "inbox-data", days=30)
    s.sweep_failures = 2
    s.consecutive_sweep_failures = 2
    s.last_sweep_error = "PermissionError"
    body = _app_with_sweeper(tmp_path, monkeypatch, s).get("/healthz").json()
    assert body["status"] == "degraded"
    line = next(r for r in body["reasons"] if "sweep pass(es) FAILED" in r)
    assert "PermissionError" in line


def test_healthz_stops_degrading_once_a_sweep_pass_recovers(tmp_path, monkeypatch):
    """The lifetime counter is history, not a fault. Gating the reason on it
    pinned `status` at `degraded` for the life of the process after ONE
    transient failure — and rendered the already-cleared `last_sweep_error` as
    the literal "(None)" in a line claiming "nothing is being pruned" while the
    sweeper was demonstrably still pruning. Same split as `poll_failures` vs
    `consecutive_poll_failures` ten lines below it in `service.py`."""
    from chat_gateway.retention import RetentionSweeper

    s = RetentionSweeper(tmp_path / "inbox-data", days=30)
    s.sweep_failures = 1              # it DID fail once, and that stays visible
    s.consecutive_sweep_failures = 0  # ...and then it recovered
    s.deleted = 12
    body = _app_with_sweeper(tmp_path, monkeypatch, s).get("/healthz").json()
    assert body["retention"]["sweep_failures"] == 1
    assert body["status"] == "ok"
    assert not any("retention" in r for r in body["reasons"])


def test_healthz_degrades_when_the_sweep_thread_died(tmp_path, monkeypatch):
    """Hard rule #5's founding shape, in the retention block: a dead thread
    freezes every field here at a plausible value and no counter ever moves
    again. `last_sweep_at` holds a REAL timestamp, which is what makes it read
    as healthy — so `null` is not the dead-sweeper signature, a frozen non-null
    is."""
    from chat_gateway.retention import RetentionSweeper

    s = RetentionSweeper(tmp_path / "inbox-data", days=30)
    s.last_sweep_at = dt.datetime.now(dt.timezone.utc)
    s._started = True                 # started, and the thread is not running
    body = _app_with_sweeper(tmp_path, monkeypatch, s).get("/healthz").json()
    assert body["retention"]["thread_started"] is True
    assert body["retention"]["thread_alive"] is False
    assert body["retention"]["last_sweep_at"] is not None
    assert body["status"] == "degraded"
    assert any("NOT RUNNING" in r and "retention" in r for r in body["reasons"])


def test_healthz_degrades_when_the_last_sweep_is_past_its_budget(tmp_path, monkeypatch):
    """`last_sweep_at` was published and never compared to the clock, so a
    three-week-old stamp read exactly like a three-second-old one."""
    from chat_gateway.retention import (SWEEP_STALE_INTERVAL_MULTIPLE,
                                        RetentionSweeper)

    s = RetentionSweeper(tmp_path / "inbox-data", days=30, interval_s=3600)
    s.last_sweep_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
    s.start()
    try:
        body = _app_with_sweeper(tmp_path, monkeypatch, s).get("/healthz").json()
    finally:
        s.stop()
    ret = body["retention"]
    assert ret["thread_alive"] is True
    assert ret["stale_after_seconds"] == 3600 * SWEEP_STALE_INTERVAL_MULTIPLE
    assert ret["seconds_since_last_sweep"] > ret["stale_after_seconds"]
    assert body["status"] == "degraded"
    assert any("wedged rather than erroring" in r for r in body["reasons"])


def test_healthz_does_not_shout_about_a_sweeper_that_was_never_started(tmp_path,
                                                                      monkeypatch):
    """The counterweight to the two tests above, and the reason `thread_started`
    is published beside `thread_alive`: every offline caller builds a sweeper it
    never starts, and that is not a fault."""
    from chat_gateway.retention import RetentionSweeper

    s = RetentionSweeper(tmp_path / "inbox-data", days=30)
    body = _app_with_sweeper(tmp_path, monkeypatch, s).get("/healthz").json()
    assert (body["retention"]["thread_started"],
            body["retention"]["thread_alive"]) == (False, False)
    assert body["status"] == "ok"


def test_healthz_tells_no_audit_dir_apart_from_nothing_to_delete(tmp_path, monkeypatch):
    """`files_deleted: 0` reads identically for both, and one of them means the
    audit trail is switched off entirely."""
    from chat_gateway.retention import RetentionSweeper

    off = _app_with_sweeper(tmp_path, monkeypatch,
                            RetentionSweeper("", days=30)).get("/healthz").json()
    assert off["retention"]["audit_dir_configured"] is False
    on = _app_with_sweeper(tmp_path, monkeypatch,
                           RetentionSweeper(tmp_path / "inbox-data", days=30)
                           ).get("/healthz").json()
    assert on["retention"]["audit_dir_configured"] is True


def test_healthz_degrades_when_an_audit_file_could_not_be_removed(tmp_path, monkeypatch):
    """The other half of the split: one file the OS refused is a trail growing
    past its stated window, which is a different investigation from the whole
    pass dying."""
    from chat_gateway.retention import RetentionSweeper

    s = RetentionSweeper(tmp_path / "inbox-data", days=30)
    s.errors = 3
    body = _app_with_sweeper(tmp_path, monkeypatch, s).get("/healthz").json()
    assert body["status"] == "degraded"
    assert any("could not be removed" in r for r in body["reasons"])


def test_healthz_does_not_degrade_merely_because_files_were_deleted(tmp_path, monkeypatch):
    """A retention policy working is not a fault. Same reasoning CLAUDE.md
    records for `suppressed_opt_out`: degrading on a guarantee doing its job
    teaches an operator to read `degraded` as normal."""
    from chat_gateway.retention import RetentionSweeper

    s = RetentionSweeper(tmp_path / "inbox-data", days=30)
    s.deleted = 400
    body = _app_with_sweeper(tmp_path, monkeypatch, s).get("/healthz").json()
    assert body["retention"]["files_deleted"] == 400
    assert body["status"] == "ok"
    assert not any("retention" in r for r in body["reasons"])


def test_healthz_publishes_the_unrouted_floor_from_its_one_home(tmp_path, monkeypatch):
    """Audit F5: `/healthz` must not re-derive the floor rule. If `window_for`
    changes and this line does not, the endpoint publishes a window the sweeper
    stopped using."""
    from chat_gateway.retention import RetentionSweeper, window_for

    s = RetentionSweeper(tmp_path / "inbox-data", days=30)
    body = _app_with_sweeper(tmp_path, monkeypatch, s).get("/healthz").json()
    assert body["retention"]["window_days"] == 30
    assert body["retention"]["unrouted_window_days"] == window_for("_unrouted", 30)
    assert body["retention"]["unrouted_window_days"] < 30


@pytest.mark.parametrize("window", [None, 0], ids=["no-sweeper", "window-0"])
def test_healthz_claims_no_delete_timer_when_retention_is_not_in_force(
        tmp_path, monkeypatch, window):
    """Task 14's own defect shape, pointed the other way.

    Both tails asserted deletion UNCONDITIONALLY, so an operator running the
    documented `CHAT_GATEWAY_INBOX_RETENTION_DAYS=0` escape hatch — which
    "restores pre-CG-68 behaviour exactly" — was told on an unauthenticated
    endpoint that their last-copy audit file was on a delete timer. With no
    sweeper at all both lines additionally pointed at `retention.window_days`,
    a field that does not exist in that branch of the body.
    """
    from chat_gateway.inbox import Inbox
    from chat_gateway.journal import Journal
    from chat_gateway.retention import RetentionSweeper

    monkeypatch.setenv("SVC_KEY_AITEAM", "cgk_test_key")
    monkeypatch.setenv("SVC_HOOK_FW", "https://x.example/hook")
    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")

    jpath = tmp_path / "inbox.jsonl"
    Journal(jpath).open(1, "inbound", {"app": "aiteam-harness", "NOT": "an InboundReply"})
    blocker = tmp_path / "blocked"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    inbox = Inbox(journal=Journal(jpath), quarantine_dir=blocker / "quarantine")
    inbox.restore()
    sweeper = (None if window is None
               else RetentionSweeper(tmp_path / "inbox-data", days=window))
    body = TestClient(create_app(load_registry(p), inbox,
                                 {"webhook": FakeAdapter()}, sweeper=sweeper)) \
        .get("/healthz").json()

    line = next(r for r in body["reasons"] if "no longer parse" in r)
    q_line = next(r for r in body["reasons"] if "quarantine" in r and "FAILED" in r)
    for text in (line, q_line):
        assert "not on a delete timer" in text
        assert "retention.window_days" not in text   # absent in the None branch
        assert "IS PRUNED" not in text and "DELETE TIMER" not in text
        # ...and the Task 14 phrase must not creep back in as the fix for this.
        assert "carries no retention guarantee" not in text


def test_healthz_reports_a_disabled_window_as_disabled_not_absent(tmp_path, monkeypatch):
    """`0` is the documented escape hatch, and an operator who set it needs to
    see that it took — a sweeper that is present but pruning nothing must not
    read the same as no sweeper at all."""
    from chat_gateway.retention import RetentionSweeper

    s = RetentionSweeper(tmp_path / "inbox-data", days=0)
    body = _app_with_sweeper(tmp_path, monkeypatch, s).get("/healthz").json()
    assert body["retention"]["enabled"] is False
    assert body["retention"]["window_days"] == 0
    assert "note" not in body["retention"]


# --- CG-12: suppression is visible, bare, and not a fault --------------------

# A registry whose only owner of `spaces/SECRETSPACE` will never serve it — the
# aitrader shape — with an app id, a space id and (below) a sender chosen to be
# unmistakable if any of them ever appears in a health response.
SUPPRESSION_PIN_YAML = """
identities:
  opted-out-identity:
    display: "Opted Out"
    mode: webhook
    webhook_url_env: PIN_HOOK
    space: "spaces/SECRETSPACE"
apps:
  opted-out-tenant:
    key_env: PIN_KEY
    identities: [opted-out-identity]
    allow_inbound: false
"""

# The other suppression reason, same space: an app that DID opt in, refusing a
# sender who is not on its `allowed_users`. Present so `not_authorized` is
# driven end to end through /healthz exactly as `opt_out` is — the reasons are
# equals, and a leak pin that covers only one of them covers half the surface.
REFUSAL_PIN_YAML = """
identities:
  guarded-identity:
    display: "Guarded"
    mode: webhook
    webhook_url_env: PIN_HOOK
    space: "spaces/SECRETSPACE"
apps:
  guarded-tenant:
    key_env: PIN_KEY
    identities: [guarded-identity]
    allow_inbound: true
    allowed_users: [mark@mackelprang.com]
"""

SECRET_SPACE_EVENT = {
    "type": "CARD_CLICKED",
    "space": {"name": "spaces/SECRETSPACE"},
    # NOT "Eve": that is a prefix of "Event", so any future health string
    # containing "Eventually"/"Events" would fail this pin for a reason that has
    # nothing to do with leakage — and the failure would read as a security
    # regression. A display name no health string can accidentally contain.
    "user": {"displayName": "Eve-SUPPRESSION-PIN", "email": "eve@example.com"},
    "message": {"name": "spaces/SECRETSPACE/messages/M1",
                "thread": {"name": "spaces/SECRETSPACE/threads/T1"}},
    "action": {"actionMethodName": "verdict",
               "parameters": [{"key": "job_id", "value": "job-secret"}]},
    "_pubsub_message_id": "ps-secret-1",
}

# Space, sender, dedupe key, event TYPE, and the action's param key AND value.
# The type and the param key are here because "space + event type" was the
# rejected metadata-only alternative — the pin has to cover what was turned
# down, not just what was obviously secret.
SUPPRESSION_LEAK_STRINGS = (
    "spaces/SECRETSPACE", "eve@example.com", "Eve-SUPPRESSION-PIN",
    "ps-secret-1", "job-secret", "verdict", "CARD_CLICKED", "job_id",
)


def _assert_suppression_leaks_nothing(body, app_id):
    """Read the ENTIRE response body as text, not the fields we happen to know
    about today — the point is that a later `last_suppressed_app` or per-space
    breakdown added "for debugging" fails here.

    The app id is asserted only against the `subscriber` block, deliberately:
    `registry.health()` has published app ids since v0.1 and they live in the
    committed registry. "Which apps are configured" is static, non-secret
    configuration; "which app is currently declining events, and from where" is
    observed traffic, and that is the thing that must not appear.
    """
    import json

    whole = json.dumps(body, ensure_ascii=False)
    for leaked in SUPPRESSION_LEAK_STRINGS:
        assert leaked not in whole, f"{leaked!r} reached an unauthenticated endpoint"
    assert app_id not in json.dumps(body["subscriber"]), \
        "the subscriber block must not attribute a suppression to an app"
    assert app_id in whole, \
        "sanity: the registry block still names configured apps, as it always has"


def _healthz_after_suppression(env, tmp_path, monkeypatch, yaml_text, reply_fn=None):
    from chat_gateway.adapters.pubsub import FakePuller, SubscriberLoop
    from chat_gateway.service import ROUTING_TARGET_ENV

    monkeypatch.setenv("PIN_HOOK", "https://x.example/hook")
    monkeypatch.setenv("PIN_KEY", "cgk_pin")
    monkeypatch.setenv(ROUTING_TARGET_ENV, "projects/p/topics/t")
    _, inbox, adapter = env
    p = tmp_path / "pin.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    registry = load_registry(p)

    loop = SubscriberLoop(FakePuller([SECRET_SPACE_EVENT]), registry, inbox,
                          reply_fn=reply_fn)
    assert loop.poll_once() == 1
    body = TestClient(create_app(registry, inbox, {"webhook": adapter}, loop)) \
        .get("/healthz").json()
    return inbox, loop, body


def test_suppression_counters_leak_no_space_sender_or_dedupe_key_to_healthz(
        env, tmp_path, monkeypatch):
    """THE RULE-6 PIN: prove structurally that the callback's arguments stop.

    `/healthz` is UNAUTHENTICATED, which is the whole reason CG-12 chose a bare
    counter over an `_unrouted` audit record or a metadata-only record. That
    choice is worth nothing if a later maintainer adds `last_suppressed_app` or
    a per-space breakdown "for debugging" — so this drives a real suppression
    through the real loop and then sweeps the whole response body.
    """
    inbox, loop, body = _healthz_after_suppression(
        env, tmp_path, monkeypatch, SUPPRESSION_PIN_YAML)
    assert loop.suppressed_opt_out == 1, "the suppression under test did not happen"
    _assert_suppression_leaks_nothing(body, "opted-out-tenant")

    # ...and the event genuinely went nowhere: not to the tenant, not to
    # `_unrouted`, not to disk. The counter is the only thing that changed.
    assert inbox.pending_counts() == {}
    assert body["subscriber"]["suppressed_opt_out"] == 1


def test_a_refusal_leaks_nothing_to_healthz_either(env, tmp_path, monkeypatch):
    """The SAME sweep for `not_authorized`, because the two reasons are equals.

    This one carries strictly more attributable data than an opt-out — a named
    human was refused — and it takes a different code path to the same callback,
    so covering only `opt_out` would leave the reason with more to leak untested.
    """
    refusals = []
    inbox, loop, body = _healthz_after_suppression(
        env, tmp_path, monkeypatch, REFUSAL_PIN_YAML,
        reply_fn=lambda s, t, x: refusals.append((s, t, x)))
    assert loop.suppressed_not_authorized == 1, "the refusal under test did not happen"
    assert loop.suppressed_opt_out == 0
    _assert_suppression_leaks_nothing(body, "guarded-tenant")

    assert len(refusals) == 1, "the human was still told, in-thread"
    assert inbox.pending_counts() == {}
    assert body["subscriber"]["suppressed_not_authorized"] == 1


def test_healthz_does_not_degrade_on_suppression_however_large(
        env, tmp_path, monkeypatch):
    """Suppression is CORRECT behaviour, so it must never colour `status`.

    `opt_out` is hard rule #6 doing exactly its job and `not_authorized` is
    jobhunt's R4 allowlist doing exactly its job. Degrading on either — or on a
    threshold of either — would train an operator to read "degraded" as normal,
    which is the ignored-warning failure mode rule #5 was written after. The
    numbers here are deliberately huge: there is no magnitude at which a working
    guarantee becomes a fault.
    """
    from chat_gateway.service import ROUTING_TARGET_ENV

    monkeypatch.setenv(ROUTING_TARGET_ENV, "projects/p/topics/t")
    _, inbox, adapter = env
    registry, loop = _loop_with(
        tmp_path, inbox,
        last_poll_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1),
        suppressed_opt_out=5000, suppressed_not_authorized=500,
    )
    client = TestClient(create_app(registry, inbox, {"webhook": adapter}, loop))
    body = client.get("/healthz").json()

    assert body["subscriber"]["suppressed_opt_out"] == 5000
    assert body["subscriber"]["suppressed_not_authorized"] == 500
    assert body["status"] == "ok", body["reasons"]
    assert body["reasons"] == [], "suppression must not produce a reason"


# --- the portable card convention (CG-13 / ADR-0001 D3) ----------------------

OPTED_OUT_YAML = REGISTRY_YAML + """  locked-out:
    key_env: SVC_KEY_LOCKED
    identities: [pm-familyworkspace]
    allow_inbound: false
"""


def _client_for(tmp_path, yaml_text):
    p = tmp_path / "r2.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    registry = load_registry(p)
    return TestClient(create_app(registry, Inbox(), {"webhook": FakeAdapter()}))


def test_identities_publishes_the_routing_target(env, monkeypatch):
    """ADR-0001 D3. Producers must not hardcode the topic path — fetching it is
    what makes a deployment-model migration cost zero producer card changes."""
    from chat_gateway.service import ROUTING_TARGET_ENV

    monkeypatch.setenv(ROUTING_TARGET_ENV, "projects/p/topics/t")
    client, _, _ = env
    body = client.get("/v1/identities", headers=AUTH).json()
    assert body["interaction"]["enabled"] is True
    assert body["interaction"]["routing_target"] == "projects/p/topics/t"
    assert body["interaction"]["action_key"] == "__cg_action__"


def test_published_action_key_is_the_one_the_parser_actually_pops():
    """A published constant that drifts from the parser is worse than none:
    every producer would wire cards to a key nothing reads."""
    from chat_gateway.adapters.pubsub import CG_ACTION_KEY, normalize_event

    core = normalize_event({
        "type": "CARD_CLICKED", "space": {"name": "spaces/AAA"},
        "user": {"email": "m@example.com"}, "message": {},
        "action": {"parameters": [{"key": CG_ACTION_KEY, "value": "verdict"}]},
    })
    assert core["action"]["id"] == "verdict"
    assert CG_ACTION_KEY not in core["action"]["params"]


def test_unset_routing_target_says_so_instead_of_guessing(env, monkeypatch):
    """A producer that builds cards against a guessed target ships cards whose
    taps go nowhere — and finds out in front of a user."""
    from chat_gateway.service import ROUTING_TARGET_ENV

    monkeypatch.delenv(ROUTING_TARGET_ENV, raising=False)
    client, _, _ = env
    interaction = client.get("/v1/identities", headers=AUTH).json()["interaction"]
    assert interaction["enabled"] is False
    assert ROUTING_TARGET_ENV in interaction["reason"]
    assert "routing_target" not in interaction      # no half-answer to copy


def test_opted_out_tenants_are_never_given_a_routing_target(tmp_path, monkeypatch):
    """Hard rule #6. Narrower than ADR-0001 D3 requires, deliberately: handing
    an opted-out tenant a routing target invites it to build cards whose
    interactions the gateway would then discard. Saying so plainly beats a
    value that silently means nothing. This is aitrader's shape."""
    from chat_gateway.service import ROUTING_TARGET_ENV

    monkeypatch.setenv(ROUTING_TARGET_ENV, "projects/p/topics/t")
    monkeypatch.setenv("SVC_KEY_LOCKED", "cgk_locked")
    monkeypatch.setenv("SVC_KEY_AITEAM", "cgk_test_key")
    monkeypatch.setenv("SVC_HOOK_FW", "https://x.example/hook")
    client = _client_for(tmp_path, OPTED_OUT_YAML)

    interaction = client.get(
        "/v1/identities", headers={"Authorization": "Bearer cgk_locked"}
    ).json()["interaction"]
    assert interaction["enabled"] is False
    assert "hard rule #6" in interaction["reason"]
    assert "routing_target" not in interaction
    assert "projects/p/topics/t" not in str(interaction)

    # ...while the opted-IN app on the same gateway still gets it
    opted_in = client.get(
        "/v1/identities", headers={"Authorization": "Bearer cgk_test_key"}
    ).json()["interaction"]
    assert opted_in["routing_target"] == "projects/p/topics/t"


# --- CG-72: the dispatcher and the heartbeat monitor at /healthz -------------
#
# Ten tests, kept together — six shipped with the row, four added by its
# pre-merge review, which found the delivery chain exercised and the heartbeats
# chain trusted to be its mirror. The two threads `/healthz` could not see: a
# dead `delivery-dispatcher` silently stops every outbound notification, and a
# dead `heartbeat-monitor` kills the dead-man switch — both with every published
# field frozen at a real-looking value. Rule #5's founding shape, twice.
#
# All three branches of BOTH `elif` chains are executed here, and each asserts
# `len(hits) == 1` rather than `any(...)`: the chain's guarantee is at most one
# reason per fault, and `any` cannot fail when that breaks.
#
# These use the file's own `env` fixture rather than a new helper: it already
# builds a registry, an inbox, a fake adapter and an app with NO subscriber and
# NO sweeper, which is the 23-bare-TestClient shape these tests are about.


def test_a_dispatcher_that_was_never_started_is_silent_not_degraded(env):
    """The 23 offline apps. `thread_alive` is false and it is NOT a fault."""
    client, _inbox, _adapter = env
    body = client.get("/healthz").json()
    assert body["delivery"]["thread_started"] is False
    assert body["delivery"]["thread_alive"] is False
    assert body["heartbeats"]["thread_started"] is False
    assert not any("delivery: the dispatch thread" in r for r in body["reasons"])
    assert not any("heartbeats: the scan thread" in r for r in body["reasons"])


def test_a_dispatch_thread_that_started_and_died_degrades_healthz(env):
    """The founding rule-#5 shape: every field frozen at a plausible value."""
    client, _inbox, _adapter = env
    dispatch = client.app.state.dispatcher
    dispatch.start()
    dispatch.stop()                               # thread is now dead
    assert dispatch.started is True
    assert dispatch.is_alive() is False
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    # `len(hits) == 1`, not `any(...)`: a dead thread also reads as stale and as
    # never having completed a pass, and the whole point of the `elif` chain is
    # that one fault prints one reason. `any` passes just as happily when all
    # three fire, which is the regression this branch's ordering exists to
    # prevent — so it is pinned on every branch, not only the wedged one.
    hits = [r for r in body["reasons"] if r.startswith("delivery: ")]
    assert len(hits) == 1
    assert "the dispatch thread was started and is NOT RUNNING" in hits[0]


def test_a_scan_thread_that_started_and_died_degrades_healthz(env):
    client, _inbox, _adapter = env
    monitor = client.app.state.monitor
    monitor.start()
    monitor.stop()
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    hits = [r for r in body["reasons"] if r.startswith("heartbeats: ")]
    assert len(hits) == 1                         # see the dispatcher twin above
    assert "the scan thread was started and is NOT RUNNING" in hits[0]


def test_an_empty_pass_still_stamps_last_pass_at():
    """Otherwise 'healthy and idle' is byte-identical to 'dead' for hours.

    This is the assertion that makes the staleness branch mean anything at
    this gateway's traffic shape, where nearly every pass is empty.
    """
    from chat_gateway.delivery import DeliveryLog, Dispatcher

    d = Dispatcher({}, DeliveryLog())
    assert d.last_pass_at is None
    assert d.process_due() == 0                   # nothing due, nothing to do
    assert d.last_pass_at is not None


def test_a_wedged_dispatcher_is_stale_but_not_reported_dead(env):
    """Alive + no completed pass past the budget == wedged, one reason only."""
    from chat_gateway.service import DISPATCH_STALE_AFTER_SECONDS

    client, _inbox, _adapter = env
    dispatch = client.app.state.dispatcher
    # STUBBED BEFORE `start()`, and it must stay that way: the real `_run` calls
    # `process_due` every 1.0s and that stamps `last_pass_at` even on an empty
    # pass, so a live loop re-stamps the antique timestamp below and the
    # assertion flips to `ok` on any pause over a second. A no-op `process_due`
    # lets the thread spin — `is_alive()` is still True, which is the half of
    # this branch the stub must not break — while nothing moves the clock.
    dispatch.process_due = lambda: 0
    dispatch.start()
    try:
        assert dispatch.is_alive() is True
        dispatch.last_pass_at = (dt.datetime.now(dt.timezone.utc)
                                 - dt.timedelta(seconds=DISPATCH_STALE_AFTER_SECONDS + 60))
        body = client.get("/healthz").json()
        assert body["status"] == "degraded"
        hits = [r for r in body["reasons"] if r.startswith("delivery: ")]
        assert len(hits) == 1 and "either WEDGED or RAISING" in hits[0]
    finally:
        dispatch.stop()


def test_a_wedged_heartbeat_monitor_is_stale_but_not_reported_dead(env):
    """The dispatcher's twin, which had no test of its own until now.

    Worth its own case rather than trusting the shared shape: this is the
    dead-man switch's OWN liveness, and while it is wedged every consumer's
    checks stop being evaluated with `missed` and `last_scan_at` both holding
    real values — the failure `heartbeats.thread_alive` was added to catch.
    """
    client, _inbox, _adapter = env
    monitor = client.app.state.monitor
    # Read the budget from the endpoint before starting, so this does not
    # hardcode a copy of `monitor_interval`'s default (`_scan_stale_after`
    # floors six intervals at 300s, and both halves are settable).
    budget = client.get("/healthz").json()["heartbeats"]["stale_after_seconds"]
    monitor.scan_once = lambda: 0                 # see the dispatcher twin above
    monitor.start()
    try:
        assert monitor.is_alive() is True
        monitor.last_scan_at = (dt.datetime.now(dt.timezone.utc)
                                - dt.timedelta(seconds=budget + 60))
        body = client.get("/healthz").json()
        assert body["status"] == "degraded"
        assert body["heartbeats"]["seconds_since_last_scan"] > budget
        hits = [r for r in body["reasons"] if r.startswith("heartbeats: ")]
        assert len(hits) == 1 and "either WEDGED or RAISING" in hits[0]
    finally:
        monitor.stop()


def test_a_started_dispatcher_with_no_completed_pass_degrades(env):
    """The MIDDLE `elif` of the delivery chain, untested until now.

    Alive, started, and `seconds_since_last_pass` still `null`. The reason
    string calls this impossible on purpose: the loop stamps even an empty pass
    (`PASS_INTERVAL_S`), so a `null` here means the first pass never returned —
    which is a wedge the staleness branch cannot see, because staleness needs a
    timestamp to be stale relative to.
    """
    client, _inbox, _adapter = env
    dispatch = client.app.state.dispatcher
    dispatch.process_due = lambda: 0              # never stamps -> stays None
    dispatch.start()
    try:
        body = client.get("/healthz").json()
        assert body["delivery"]["thread_alive"] is True
        assert body["delivery"]["last_pass_at"] is None
        assert body["delivery"]["seconds_since_last_pass"] is None
        assert body["status"] == "degraded"
        hits = [r for r in body["reasons"] if r.startswith("delivery: ")]
        assert len(hits) == 1 and "no pass has ever completed" in hits[0]
    finally:
        dispatch.stop()


def test_a_started_monitor_with_no_completed_scan_degrades(env):
    """The same middle `elif` in the heartbeats chain. Both, not one.

    The two chains are the same shape but not the same code, and the branch
    that was never executed is exactly the one a copy-paste slip survives in.
    """
    client, _inbox, _adapter = env
    monitor = client.app.state.monitor
    monitor.scan_once = lambda: 0                 # never stamps -> stays None
    monitor.start()
    try:
        body = client.get("/healthz").json()
        assert body["heartbeats"]["thread_alive"] is True
        assert body["heartbeats"]["last_scan_at"] is None
        assert body["heartbeats"]["seconds_since_last_scan"] is None
        assert body["status"] == "degraded"
        hits = [r for r in body["reasons"] if r.startswith("heartbeats: ")]
        assert len(hits) == 1 and "no scan has ever completed" in hits[0]
    finally:
        monitor.stop()


def test_the_liveness_timestamps_are_serialized_in_the_healthz_body(env):
    """Asserted AT THE ENDPOINT, which no other test in this block does.

    `test_an_empty_pass_still_stamps_last_pass_at` reads the attribute off a
    bare `Dispatcher`, so a body that dropped `last_pass_at`, published it under
    another key, or emitted a `datetime` where a consumer expects an ISO string
    would sail past it. These four fields are the ones the guide tells consumers
    to read, so the endpoint is where they have to be checked.
    """
    from chat_gateway.delivery import PASS_INTERVAL_S
    from chat_gateway.service import DISPATCH_STALE_AFTER_SECONDS

    client, _inbox, _adapter = env
    dispatch = client.app.state.dispatcher
    monitor = client.app.state.monitor
    assert dispatch.process_due() == 0             # one real, empty pass...
    assert monitor.scan_once() == 0                # ...and one real, empty scan
    body = client.get("/healthz").json()
    d, hb = body["delivery"], body["heartbeats"]

    assert d["last_pass_at"] == dispatch.last_pass_at.isoformat()
    assert isinstance(d["seconds_since_last_pass"], float)
    assert 0.0 <= d["seconds_since_last_pass"] < 60.0
    assert d["stale_after_seconds"] == DISPATCH_STALE_AFTER_SECONDS
    assert d["pass_interval_seconds"] == PASS_INTERVAL_S

    assert hb["last_scan_at"] == monitor.last_scan_at.isoformat()
    assert isinstance(hb["seconds_since_last_scan"], float)
    assert 0.0 <= hb["seconds_since_last_scan"] < 60.0

    # Neither thread was ever started, so a fresh stamp is not a fault and
    # neither chain may speak — the 23-offline-apps guarantee, re-checked here
    # because this is the one test that puts a real timestamp in both blocks.
    assert not any(r.startswith(("delivery: ", "heartbeats: "))
                   for r in body["reasons"])


def test_the_delivery_and_heartbeat_stale_budgets_follow_their_intervals(
        env, tmp_path):
    """`service.py` must not hardcode a copy of either interval."""
    from chat_gateway.delivery import PASS_INTERVAL_S

    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    app = create_app(load_registry(p), Inbox(), {}, monitor_interval=600.0)
    body = TestClient(app).get("/healthz").json()
    assert body["heartbeats"]["scan_interval_seconds"] == 600.0
    assert body["heartbeats"]["stale_after_seconds"] == 3600.0   # 6 * 600
    assert body["delivery"]["pass_interval_seconds"] == PASS_INTERVAL_S


# --------------------------------------------------------------------------
# CG-75: the audit-write counter, and the strings this row falsified
# --------------------------------------------------------------------------

def test_audit_write_errors_is_published_and_degrades(env):
    """Rule #5: the write is swallowed now, so this counter is the only witness."""
    client, _inbox, _adapter = env
    body = client.get("/healthz").json()
    assert body["delivery"]["audit_write_errors"] == 0

    client.app.state.delivery_log.audit_write_errors = 2
    body = client.get("/healthz").json()
    assert body["delivery"]["audit_write_errors"] == 2
    assert body["status"] == "degraded"
    hits = [r for r in body["reasons"] if r.startswith("delivery log: ")]
    assert len(hits) == 1 and "NO on-disk record" in hits[0]


def test_audit_write_errors_sums_a_dispatcher_carrying_its_own_log(tmp_path):
    """`_audit_write_errors`'s second owner is not hypothetical.

    An injected dispatcher brings its own `DeliveryLog`; `create_app` builds a
    different one when `delivery_log` is not also passed. Reading either alone
    reports zero while the other is losing records.
    """
    from chat_gateway.delivery import DeliveryLog, Dispatcher

    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    other = DeliveryLog()
    other.audit_write_errors = 3
    app = create_app(load_registry(p), Inbox(), {"webhook": FakeAdapter()},
                     dispatcher=Dispatcher({}, other))
    assert app.state.delivery_log is not other      # two objects, as designed
    body = TestClient(app).get("/healthz").json()
    assert body["delivery"]["audit_write_errors"] == 3


def test_the_delivery_staleness_reason_no_longer_blames_a_full_disk(env):
    """Rule #5: CG-75 makes the old example false, so it must not still be there.

    Same shape as `test_a_wedged_dispatcher_is_stale_but_not_reported_dead` —
    including the stub-before-`start()` note there, which applies unchanged.
    """
    from chat_gateway.service import DISPATCH_STALE_AFTER_SECONDS

    client, _inbox, _adapter = env
    dispatch = client.app.state.dispatcher
    dispatch.process_due = lambda: 0
    dispatch.start()
    try:
        dispatch.last_pass_at = (dt.datetime.now(dt.timezone.utc)
                                 - dt.timedelta(seconds=DISPATCH_STALE_AFTER_SECONDS + 60))
        hits = [r for r in client.get("/healthz").json()["reasons"]
                if r.startswith("delivery: ")]
        assert len(hits) == 1
        assert "either WEDGED or RAISING" in hits[0]
        assert "audit_write_errors" in hits[0]
        assert "a full disk, which makes the delivery log's own write raise" not in hits[0]
    finally:
        dispatch.stop()
