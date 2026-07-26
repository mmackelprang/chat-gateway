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
