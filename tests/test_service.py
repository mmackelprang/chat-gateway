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
    loop = SubscriberLoop(FakePuller(), registry, inbox)
    loop.events_seen, loop.unparseable_seen, loop.dispatch_errors = 9, 2, 3
    loop.interactions_without_action_id = 5
    loop.last_poll_at = dt.datetime(2026, 7, 29, 12, 0, tzinfo=dt.timezone.utc)

    client = TestClient(create_app(registry, inbox, {"webhook": adapter}, loop))
    sub = client.get("/healthz").json()["subscriber"]
    assert sub == {
        "enabled": True, "last_poll_at": "2026-07-29T12:00:00+00:00",
        "events_seen": 9, "unparseable_seen": 2, "dispatch_errors": 3,
        "interactions_without_action_id": 5,
        "poll_failures": 0, "consecutive_poll_failures": 0, "last_poll_error": None,
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


def test_healthz_reasons_explain_a_degraded_registry(env, monkeypatch):
    """`degraded` with no explanation makes an operator diff the body against a
    known-good copy. Say why."""
    client, _, _ = env
    monkeypatch.delenv("SVC_HOOK_FW")
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    assert any("does not resolve" in r for r in body["reasons"])


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
