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


# --- CG-59: `?strict=1` — the same honesty, in the status code ---------------
#
# The plain form answered 200 for every reason string this endpoint can
# produce, so a Homepage `siteMonitor` tile and a container health check — both
# of which judge by STATUS CODE — read green while inbound is dead. These tests
# pin the three properties that make the fix safe: the code moves, the body does
# not, and the plain form's published contract is untouched.


def test_strict_returns_503_only_when_there_are_reasons(env, monkeypatch):
    client, _, _ = env
    healthy = client.get("/healthz?strict=1")
    assert healthy.status_code == 200 and healthy.json()["reasons"] == []

    monkeypatch.delenv("SVC_HOOK_FW")
    degraded = client.get("/healthz?strict=1")
    assert degraded.status_code == 503
    assert degraded.json()["reasons"], "503 with nothing to explain it"


def test_the_plain_form_still_returns_200_when_degraded(env, monkeypatch):
    """A published contract with existing readers. Deliberately unchanged.

    Flipping the default was considered and rejected: a 503 from a *container*
    health check would make Docker restart a gateway that is degraded but
    working — one unresolved env var on a tier-1-only host.
    """
    client, _, _ = env
    monkeypatch.delenv("SVC_HOOK_FW")
    plain = client.get("/healthz")
    assert plain.status_code == 200
    assert plain.json()["status"] == "degraded" and plain.json()["reasons"]


@pytest.mark.parametrize("degrade", [False, True])
def test_the_strict_body_is_identical_to_the_plain_body(env, monkeypatch, degrade):
    """Same information, different envelope — or an operator comparing the two
    learns something false.

    Byte equality on `.content`, not a `==` on parsed dicts: key order and
    separators are part of what a reader diffing two `curl` outputs sees.
    """
    client, _, _ = env
    if degrade:
        monkeypatch.delenv("SVC_HOOK_FW")

    plain = client.get("/healthz")
    strict = client.get("/healthz?strict=1")
    control = client.get("/healthz")

    # The control proves the comparison is MEANINGFUL. Without it, a body that
    # varied between any two calls (a clock field, say) would make the equality
    # below fail for a reason that has nothing to do with `strict` — and a body
    # that was constant for the wrong reason would make it pass vacuously.
    assert plain.content == control.content, (
        "this fixture's /healthz body is not deterministic between calls, so "
        "the identity assertion below cannot mean what it claims")
    assert strict.content == plain.content
    assert strict.status_code == (503 if degrade else 200)
    assert plain.status_code == 200


def test_strict_is_opt_in_and_a_falsey_value_is_not_strict(env, monkeypatch):
    """`?strict=0` must not 503. The reader chooses; the query string is how."""
    client, _, _ = env
    monkeypatch.delenv("SVC_HOOK_FW")
    assert client.get("/healthz").status_code == 200
    assert client.get("/healthz?strict=0").status_code == 200
    assert client.get("/healthz?strict=false").status_code == 200
    assert client.get("/healthz?strict=1").status_code == 503
    assert client.get("/healthz?strict=true").status_code == 503


def test_an_unparseable_strict_value_is_a_422_and_NOT_a_health_verdict(env):
    """⚠ MEASURED, and recorded rather than smoothed: the ONE input class where
    "identical body either way" does not hold.

    `strict` is a bool query parameter, so a **bare** `?strict` (and `?strict=`,
    and `?strict=banana`) is a FastAPI validation failure: **422, with a
    validation body, not a health body.** A probe misconfigured that way reads
    as DOWN on a healthy gateway.

    Pinned rather than fixed, deliberately. The failure this row exists against
    is a **silent green** over a dead input — the shape that hid 11 days of
    capture failure. A 422 is the loud direction: it is wrong, but it is wrong
    in the way that gets investigated within the hour. Widening the parameter so
    a bare `?strict` means strict is a design change, and the design was decided
    with `strict: bool` — so this is surfaced as a finding, and the handoff that
    repoints the Homepage tile names the exact URL (`?strict=1`).

    The 422 body echoes only the caller's own query value — nothing of this
    gateway's state reaches it, which is what makes an unauthenticated 422 here
    uninteresting under rules #2 and #6.
    """
    client, _, _ = env
    for q in ("?strict", "?strict=", "?strict=banana"):
        resp = client.get("/healthz" + q)
        assert resp.status_code == 422, q
        assert "status" not in resp.json(), (
            f"{q} returned something that could be mistaken for a verdict")


def test_status_and_reasons_cannot_disagree_so_the_trigger_is_the_source(
        env, tmp_path, monkeypatch):
    """`strict` keys on `reasons`, not on `status`. This pins WHY that is safe.

    `status` is computed FROM `reasons` at the sole return, so the two are one
    fact rendered twice and cannot diverge. The test walks several independent
    degradation causes — a registry env var, a subscriber that has never polled,
    and a healthy deployment — and asserts the three-way lock in every one:

        reasons non-empty  <->  status == "degraded"  <->  strict is 503

    If a future change ever introduced a third status word, or a `status` set
    beside `reasons` instead of from it, this fails rather than letting the
    status code quietly stop meaning what the body says.
    """
    _, inbox, adapter = env

    def probe(c):
        plain, strict = c.get("/healthz"), c.get("/healthz?strict=1")
        body = plain.json()
        assert body["status"] in ("ok", "degraded"), body["status"]
        assert (body["status"] == "degraded") == bool(body["reasons"])
        assert (strict.status_code == 503) == bool(body["reasons"])
        return body["status"]

    client, _, _ = env
    assert probe(client) == "ok"
    monkeypatch.delenv("SVC_HOOK_FW")
    assert probe(client) == "degraded"

    # A different subsystem, degrading for an unrelated reason.
    monkeypatch.setenv("SVC_HOOK_FW", "https://x.example/hook")
    registry, loop = _loop_with(tmp_path, inbox)          # never polled
    assert probe(TestClient(
        create_app(registry, inbox, {"webhook": adapter}, loop))) == "degraded"


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
    """Alive + no completed pass past the budget == wedged, one reason only.

    The substring moved in CG-74 and the move is the row landing. It read
    `"either WEDGED or RAISING"` while nothing counted a failed pass, so the
    endpoint could not tell the two apart and said so. A counter branch now sits
    above this one in the chain, so by the time this `elif` is reached "not
    raising" has been MEASURED — and the string says WEDGED without the hedge.
    """
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
        assert len(hits) == 1 and "WEDGED rather than erroring" in hits[0]
    finally:
        dispatch.stop()


def test_a_wedged_heartbeat_monitor_is_stale_but_not_reported_dead(env):
    """The dispatcher's twin, which had no test of its own until now.

    Worth its own case rather than trusting the shared shape: this is the
    dead-man switch's OWN liveness, and while it is wedged every consumer's
    checks stop being evaluated with `missed` and `last_scan_at` both holding
    real values — the failure `heartbeats.thread_alive` was added to catch.

    Substring updated by CG-74 for the reason its dispatcher twin above records:
    `consecutive_scan_failures` now answers "raising?" one branch earlier, so
    this string no longer has to hedge between the two.
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
        assert len(hits) == 1 and "WEDGED rather than erroring" in hits[0]
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

    CG-74 REWROTE THE STRING THIS PINS, and the test keeps its subject rather
    than its assertions. The `not in` below is the whole point of the case: it
    guards a framing that was MEASURED FALSE, and a falsified sentence can be
    reintroduced by any later edit to this reason. That guard is why the row is
    here. What had to change is the positive half: the CG-75 string pointed a
    reader at `audit_write_errors`, and CG-74's does not mention it — the
    counter branch one `elif` up now answers "is it raising?" outright, so the
    staleness reason stops speculating about raise sites and states a wedge.
    The positive assertions therefore move to that clause, which is the thing
    that makes the `not in` meaningful; a `not in` alone would pass against an
    empty string.
    """
    from chat_gateway.service import DISPATCH_FAILURE_THRESHOLD, DISPATCH_STALE_AFTER_SECONDS

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
        assert "WEDGED rather than erroring" in hits[0]
        assert (f"fewer than {DISPATCH_FAILURE_THRESHOLD} consecutive passes "
                "have raised") in hits[0]
        assert "a full disk, which makes the delivery log's own write raise" not in hits[0]
    finally:
        dispatch.stop()


def test_the_heartbeat_staleness_reason_does_not_blame_the_delivery_log(env):
    """The delivery twin above, for the string CG-75 reworded on the OTHER loop.

    RENAMED BY CG-74, from `..._names_the_right_file`, because that name became
    false: the string names no file at all now. What survives, and what this
    case is still for, is the `not in` at the bottom — CG-75 measured that the
    pre-CG-75 sentence pointed an operator at `DeliveryLog.record` for a raise
    that comes from `enqueue`'s journal `open`, and a falsified sentence on an
    unauthenticated endpoint can be reintroduced by any later edit to this
    reason. The guard is the row.

    The two positive assertions it used to carry (`` `enqueue`'s journal write ``
    and "NOT through the delivery log") are gone from the string, not weakened
    here: CG-74's counter branch sits one `elif` above this one, so by the time
    this branch is reached the monitor has been measured NOT to be raising, and
    a clause about where a raise would come from no longer belongs in it. The
    positives move to the clause that replaced them — which is what keeps the
    `not in` meaningful, since a `not in` alone would pass against an empty
    string.

    Modelled on `test_a_wedged_heartbeat_monitor_is_stale_but_not_reported_dead`,
    including reading the budget off `/healthz` rather than hardcoding a copy of
    `monitor_interval`, and stubbing `scan_once` BEFORE `start()` for the reason
    that test's comment gives.
    """
    from chat_gateway.service import SCAN_FAILURE_THRESHOLD

    client, _inbox, _adapter = env
    monitor = client.app.state.monitor
    budget = client.get("/healthz").json()["heartbeats"]["stale_after_seconds"]
    monitor.scan_once = lambda: 0                 # see the wedged-monitor test
    monitor.start()
    try:
        monitor.last_scan_at = (dt.datetime.now(dt.timezone.utc)
                                - dt.timedelta(seconds=budget + 60))
        hits = [r for r in client.get("/healthz").json()["reasons"]
                if r.startswith("heartbeats: ")]
        assert len(hits) == 1
        assert "WEDGED rather than erroring" in hits[0]
        assert (f"fewer than {SCAN_FAILURE_THRESHOLD} consecutive scans "
                "have raised") in hits[0]
        assert "No registered check is being evaluated while this holds" in hits[0]
        assert ("A scan that fires a check enqueues through the delivery log, "
                "so a full disk raises there") not in hits[0]
    finally:
        monitor.stop()


# --- CG-74: the counter branches, at the endpoint ----------------------------
#
# LIVENESS IS STUBBED HERE, NOT STARTED, and that is not laziness — it is the
# only way to assert on a counter. The sibling cases above start a real thread
# with a no-op `process_due`, but `_run` clears `consecutive_pass_failures` on
# every good pass, so a live loop zeroes the field under the assertion. The
# increment-and-clear mechanism is proven against the real `while` loop in
# `tests/test_notify_heartbeat.py`; what is proven here is what `/healthz` does
# with the numbers, which is the half that needs an exact body.

def _pretend_alive(loop):
    """Started AND alive, without a thread. See the block comment above."""
    loop._started = True
    loop.is_alive = lambda: True


def _pretend_dead(loop):
    """Started and NOT alive — the state both chains rank above everything else.

    Reachable with the counters non-zero, and the door is documented on
    `Dispatcher.is_alive`: `_run` survives what the work function raises, but not
    what its own handler raises, and that handler `print`s. Three raising passes
    followed by a `print` that dies (a closed stdout on a detached process is the
    shape) leaves exactly this — a dead thread with `consecutive_*_failures` at
    the threshold.
    """
    loop._started = True
    loop.is_alive = lambda: False


def test_consecutive_pass_failures_degrade_at_the_threshold(env):
    from chat_gateway.service import DISPATCH_FAILURE_THRESHOLD

    client, _inbox, _adapter = env
    dispatch = client.app.state.dispatcher
    _pretend_alive(dispatch)
    # A fresh stamp, so the staleness and never-completed branches stay quiet
    # and the only thing under test is the counter.
    dispatch.last_pass_at = dt.datetime.now(dt.timezone.utc)
    dispatch.consecutive_pass_failures = DISPATCH_FAILURE_THRESHOLD - 1
    dispatch.last_pass_error = "OSError"
    body = client.get("/healthz").json()
    assert body["status"] == "ok", "one under the threshold must not alarm"
    assert body["delivery"]["consecutive_pass_failures"] == DISPATCH_FAILURE_THRESHOLD - 1

    dispatch.consecutive_pass_failures = DISPATCH_FAILURE_THRESHOLD
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    hits = [r for r in body["reasons"] if r.startswith("delivery: ")]
    assert len(hits) == 1 and "consecutive dispatch passes have RAISED" in hits[0]
    assert "(last: OSError)" in hits[0]


def test_pass_failures_alone_does_not_degrade(env):
    """Cumulative is history. Degrading on it would pin `degraded` forever.

    The dispatcher is made started-and-alive with a fresh stamp deliberately: an
    unstarted one is silent in this chain whatever the counters say, so the
    assertion would pass against a `pass_failures` guard that DID degrade. This
    way the only thing that could produce a `delivery:` reason is the field
    under test — and its counterpart, `heartbeats.scan_failures`, is the row
    below, which asserts the opposite for a measured reason.
    """
    client, _inbox, _adapter = env
    dispatch = client.app.state.dispatcher
    _pretend_alive(dispatch)
    dispatch.last_pass_at = dt.datetime.now(dt.timezone.utc)
    dispatch.pass_failures = 99
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["delivery"]["pass_failures"] == 99
    assert not [r for r in body["reasons"] if r.startswith("delivery: ")]


def test_cumulative_scan_failures_DO_degrade(env):
    """The deliberate asymmetry with the row above — `scan_failures` degrades.

    ⚠ THE ASSERTED STRING CHANGED WITH CG-76, AND SO DID THIS DOCSTRING. Both
    used to say a raising scan "has already had `due_alerts` mark its check
    `missed` ... so the alert is suppressed for the 24h repeat window and no
    later scan re-sends it". That was true and measured when CG-74 shipped it,
    and CG-76 reordered exactly that: the mark now happens in `mark_alerted`,
    after the notify is accepted, so a raising scan leaves the check UNMARKED
    and the next scan re-fires it.

    The counter still degrades — the user's D3 decision stands (spec §7.2) —
    but on the weaker reason, so the reason STRING no longer claims a loss.
    This test therefore matches on "DELAYED or DUPLICATED" rather than the
    retired "may already have been lost". It is NOT a loosened assertion: the
    degrade, the count and the outside-the-chain placement are all still pinned,
    and `alerts_undeliverable` is now the counter for an alert actually lost.

    Note this fires with the monitor NEVER STARTED: it is not a liveness signal
    and is not gated on `thread_started`, which is why it lives outside the
    elif chain rather than in it.
    """
    client, _inbox, _adapter = env
    client.app.state.monitor.scan_failures = 1
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    hits = [r for r in body["reasons"] if r.startswith("heartbeats: ")]
    assert len(hits) == 1 and "DELAYED or DUPLICATED" in hits[0]


def test_a_raising_dispatcher_outranks_the_staleness_branch(env):
    """ORDERING, and it is the only thing that makes the staleness string true.

    A raising loop is also a stale one — it never completes a pass, so
    `last_pass_at` freezes. If the staleness branch came first it would report
    "WEDGED rather than erroring" about a loop that is erroring on every pass,
    on an unauthenticated endpoint, which is the exact class of confident wrong
    answer hard rule #5 exists to prevent. Both conditions are true here and
    exactly one reason must come back.
    """
    from chat_gateway.service import (DISPATCH_FAILURE_THRESHOLD,
                                      DISPATCH_STALE_AFTER_SECONDS)

    client, _inbox, _adapter = env
    dispatch = client.app.state.dispatcher
    _pretend_alive(dispatch)
    dispatch.last_pass_at = (dt.datetime.now(dt.timezone.utc)
                             - dt.timedelta(seconds=DISPATCH_STALE_AFTER_SECONDS + 60))
    dispatch.consecutive_pass_failures = DISPATCH_FAILURE_THRESHOLD
    dispatch.last_pass_error = "OSError"
    hits = [r for r in client.get("/healthz").json()["reasons"]
            if r.startswith("delivery: ")]
    assert len(hits) == 1
    assert "RAISED" in hits[0]
    assert "WEDGED rather than erroring" not in hits[0]


def test_a_raising_and_a_wedged_monitor_produce_different_reasons(env):
    """The whole point of CG-74: these two were indistinguishable.

    Same ordering guarantee as the dispatcher row above, and the same reason it
    matters — a raising monitor is also a stale one.

    THE COUNTERS ARE SET THE WAY `_run` SETS THEM, and that is a correction:
    this case used to assign `consecutive_scan_failures` alone and then assert
    `len(...) == 1`. `_run` increments BOTH in one `except`, so
    `consecutive_scan_failures > 0` implies `scan_failures >= consecutive`, and
    the old state was unreachable — the count it pinned was an artefact of the
    setup, not a property of the endpoint. In production a raising monitor
    prints TWO `heartbeats:` reasons, which is the deliberate design and is
    pinned by the row below. What this case is actually for survives unchanged:
    a raising monitor and a wedged one must not produce the SAME reason, so the
    assertions move from counting to content.
    """
    from chat_gateway.service import SCAN_FAILURE_THRESHOLD

    client, _inbox, _adapter = env
    mon = client.app.state.monitor
    _pretend_alive(mon)
    budget = client.get("/healthz").json()["heartbeats"]["stale_after_seconds"]
    mon.last_scan_at = (dt.datetime.now(dt.timezone.utc)
                        - dt.timedelta(seconds=budget + 60))

    # Stale and RAISING — both counters, as one trip through `_run`'s `except`
    # would leave them.
    mon.scan_failures = SCAN_FAILURE_THRESHOLD
    mon.consecutive_scan_failures = SCAN_FAILURE_THRESHOLD
    mon.last_scan_error = "OSError"
    raising = [r for r in client.get("/healthz").json()["reasons"]
               if r.startswith("heartbeats: ")]
    from_chain = [r for r in raising if "consecutive scans have RAISED" in r]
    assert len(from_chain) == 1, "the elif chain must produce exactly one reason"
    assert "(last: OSError)" in from_chain[0]
    assert not [r for r in raising if "WEDGED rather than erroring" in r]

    # Stale and NOT raising — same staleness, different answer. Both counters at
    # zero is the reachable spelling of "this loop has never raised": one is
    # cleared by recovery, the other never had to move.
    mon.scan_failures = 0
    mon.consecutive_scan_failures = 0
    mon.last_scan_error = None
    wedged = [r for r in client.get("/healthz").json()["reasons"]
              if r.startswith("heartbeats: ")]
    assert len(wedged) == 1
    assert "WEDGED rather than erroring" in wedged[0]
    assert wedged[0] != from_chain[0]


def test_a_raising_monitor_prints_two_heartbeat_reasons_not_one(env):
    """The two-reason shape `docs/integration-guide.md` publishes, pinned.

    That guide tells consumers the `heartbeats.*` liveness triple emits **at
    most one** `reasons` entry, and that `heartbeats.scan_failures` can print a
    **second** one beside it because "has an alert already been lost" is a
    different question from "is this loop running". Until now nothing tested it,
    and the case above asserted a one-reason count from a state `_run` cannot
    produce, which is the opposite claim.

    This is also the state an operator actually meets — `_run` moves both
    counters together — and it is what would keep a "fold `scan_failures` into
    the elif chain" refactor honest: that change compiles, keeps the wedged case
    green, and silently deletes the lost-alert warning.
    """
    from chat_gateway.service import SCAN_FAILURE_THRESHOLD

    client, _inbox, _adapter = env
    mon = client.app.state.monitor
    _pretend_alive(mon)
    mon.last_scan_at = dt.datetime.now(dt.timezone.utc)   # fresh: staleness is not the subject
    mon.scan_failures = SCAN_FAILURE_THRESHOLD
    mon.consecutive_scan_failures = SCAN_FAILURE_THRESHOLD
    mon.last_scan_error = "OSError"

    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    hits = [r for r in body["reasons"] if r.startswith("heartbeats: ")]
    assert len(hits) == 2, hits
    live = [r for r in hits if "consecutive scans have RAISED" in r]
    # ⚠ "may already have been lost" until CG-76, which retired that claim: a
    # raising scan no longer marks the check, so the risk is a delayed or
    # duplicated alert rather than a lost one (spec §7.1). The TWO-REASON SHAPE
    # this test exists for is unchanged — only the second string's wording is.
    lost = [r for r in hits if "DELAYED or DUPLICATED" in r]
    assert len(live) == 1 and len(lost) == 1
    assert "(last: OSError)" in live[0]
    assert f"{SCAN_FAILURE_THRESHOLD} scan(s) have raised since start" in lost[0]


def test_a_dead_dispatch_thread_outranks_the_raising_counter(env):
    """ORDERING again, one rung up: dead-thread must beat the counter branch.

    The suite pinned counter-over-staleness on both chains and nothing pinned
    this, so moving the counter branch above the dead-thread one — the obvious
    "match `retention.*`'s order" refactor — went green. It must not: a dead
    thread will never increment another counter, so "3 consecutive passes have
    RAISED" would be a stale reading offered as a live one, and it ends in
    "`pending_jobs` will climb" where the actionable answer is *restart*.
    """
    from chat_gateway.service import (DISPATCH_FAILURE_THRESHOLD,
                                      DISPATCH_STALE_AFTER_SECONDS)

    client, _inbox, _adapter = env
    dispatch = client.app.state.dispatcher
    _pretend_dead(dispatch)
    # Stale as well, because a dead loop stops stamping: all three lower
    # branches are live and exactly one reason may come back.
    dispatch.last_pass_at = (dt.datetime.now(dt.timezone.utc)
                             - dt.timedelta(seconds=DISPATCH_STALE_AFTER_SECONDS + 60))
    dispatch.pass_failures = DISPATCH_FAILURE_THRESHOLD
    dispatch.consecutive_pass_failures = DISPATCH_FAILURE_THRESHOLD
    dispatch.last_pass_error = "OSError"

    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    hits = [r for r in body["reasons"] if r.startswith("delivery: ")]
    assert len(hits) == 1
    assert "NOT RUNNING" in hits[0] and "restart the service" in hits[0]
    assert "RAISED" not in hits[0]
    assert "WEDGED rather than erroring" not in hits[0]


def test_a_dead_scan_thread_outranks_the_raising_counter(env):
    """The heartbeat twin of the row above, and it counts to TWO on purpose.

    The chain still emits exactly one entry and it is still the dead-thread one.
    The second `heartbeats:` line is `scan_failures`, which lives OUTSIDE the
    chain by design — so the assertion is scoped to the chain's three strings
    rather than to the block's total, which would have made this row fail for a
    reason that has nothing to do with ordering.
    """
    from chat_gateway.service import SCAN_FAILURE_THRESHOLD

    client, _inbox, _adapter = env
    mon = client.app.state.monitor
    _pretend_dead(mon)
    budget = client.get("/healthz").json()["heartbeats"]["stale_after_seconds"]
    mon.last_scan_at = (dt.datetime.now(dt.timezone.utc)
                        - dt.timedelta(seconds=budget + 60))
    mon.scan_failures = SCAN_FAILURE_THRESHOLD
    mon.consecutive_scan_failures = SCAN_FAILURE_THRESHOLD
    mon.last_scan_error = "OSError"

    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    hits = [r for r in body["reasons"] if r.startswith("heartbeats: ")]
    assert len(hits) == 2, hits
    # ⚠ The `scan_failures` string this excludes was matched on "may already
    # have been lost" until CG-76 retired that claim (spec §7.1). The exclusion
    # is what scopes this assertion to the CHAIN; the substring is incidental to
    # the ordering question and only its wording moved.
    from_chain = [r for r in hits if "DELAYED or DUPLICATED" not in r]
    assert len(from_chain) == 1
    assert "NOT RUNNING" in from_chain[0] and "restart the service" in from_chain[0]
    assert "consecutive scans have RAISED" not in from_chain[0]
    assert "WEDGED rather than erroring" not in from_chain[0]
