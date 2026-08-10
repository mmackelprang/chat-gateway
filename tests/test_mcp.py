"""The MCP server surface, end to end, with a fake delivery adapter.

Offline: no network, no Google. Same idiom as tests/test_service.py.
"""

import pytest
from fastapi.testclient import TestClient

from chat_gateway.envelope import DeliveryResult
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
  agent-notes:
    display: "Agent notes"
    mode: webhook
    webhook_url_env: SVC_HOOK_AGENT
    space: "spaces/AAA"
  other-only:
    display: "Someone else's identity"
    mode: webhook
    webhook_url_env: SVC_HOOK_OTHER
    space: "spaces/BBB"
apps:
  aiteam-harness:
    key_env: SVC_KEY_AITEAM
    identities: [pm-familyworkspace, agent-notes]
  job-hunter:
    key_env: SVC_KEY_JOBHUNT
    identities: [other-only]
"""

AUTH = {"Authorization": "Bearer cgk_test_key"}
OTHER_AUTH = {"Authorization": "Bearer cgk_other_key"}


class FakeAdapter:
    """Records sends; can be told to raise. Mirrors tests/test_service.py::FakeAdapter."""

    def __init__(self):
        self.sent = []
        self.raises = None

    def send(self, identity, message):
        if self.raises is not None:
            raise self.raises
        self.sent.append((identity.name, message))
        return DeliveryResult(status="delivered", channel="google_chat",
                              identity=identity.name, mode=identity.mode,
                              thread_key=message.thread_key)


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SVC_KEY_AITEAM", "cgk_test_key")
    monkeypatch.setenv("SVC_KEY_JOBHUNT", "cgk_other_key")
    monkeypatch.setenv("SVC_HOOK_FW", "https://x.example/hook")
    monkeypatch.setenv("SVC_HOOK_OTHER", "https://y.example/hook")
    # SVC_HOOK_AGENT deliberately unset: it drives the readiness rendering in
    # the tool schema AND /healthz's `reasons`, from the same env_resolved().
    monkeypatch.delenv("SVC_HOOK_AGENT", raising=False)
    monkeypatch.delenv("CHAT_GATEWAY_MCP_ALLOWED_ORIGINS", raising=False)
    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    registry = load_registry(p)
    inbox = Inbox()
    adapter = FakeAdapter()
    app = create_app(registry, inbox, {"webhook": adapter}, mcp_enabled=True)
    return TestClient(app), adapter


def _registry_of(env):
    """The Registry the fixture's app was built from."""
    client, _ = env
    return client.app.state.registry


def rpc(client, body, headers=None, **kw):
    """POST one JSON-RPC message with the default auth header."""
    h = dict(AUTH)
    h.update(headers or {})
    return client.post("/mcp", headers=h, json=body, **kw)


# ---------------------------------------------------------------- group 1 ---
def test_mcp_requires_a_bearer_key_on_every_request_including_the_handshake(env):
    client, _ = env
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_mcp_rejects_an_unknown_key(env):
    client, _ = env
    r = client.post("/mcp", headers={"Authorization": "Bearer nope"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r.status_code == 401


def test_the_www_authenticate_header_does_NOT_advertise_resource_metadata(env):
    """Spec §5. A `resource_metadata` pointer would send a conformant client
    down an OAuth discovery path that dead-ends here — we mint our own keys."""
    client, _ = env
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert "resource_metadata" not in r.headers["www-authenticate"]


# ---------------------------------------------------------------- group 7 ---
def test_get_and_delete_on_the_mcp_endpoint_are_405(env):
    """Conformant in BOTH eras: 2025-11-25 makes 405 the explicit alternative
    to offering an SSE stream, and 2026-07-28 says a modern-only server SHOULD
    answer GET and DELETE with 405. We have nothing to stream."""
    client, _ = env
    assert client.get("/mcp", headers=AUTH).status_code == 405
    assert client.delete("/mcp", headers=AUTH).status_code == 405


def test_a_jsonrpc_batch_array_is_refused(env):
    """Batching was removed in 2025-06-18 and 2026-07-28 re-states it as a
    transport MUST: the POST body MUST be a single request or notification."""
    client, _ = env
    r = rpc(client, [{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32600


def test_an_unparseable_body_is_a_parse_error(env):
    client, _ = env
    r = client.post("/mcp", headers={**AUTH, "Content-Type": "application/json"},
                    content=b"{not json")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32700


# ---------------------------------------------------------- Origin (§6.3) ---
def test_a_request_with_no_origin_header_is_NOT_refused(env):
    """The spec's MUST fires only when Origin is PRESENT and invalid. A
    non-browser MCP client sends none, and refusing those would lock out
    every client we care about."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code != 403


def test_a_present_origin_is_refused_when_no_allowlist_is_configured(env):
    """Fail closed. We serve no browser client, and DNS-rebinding protection
    is a MUST — so an unrecognised Origin is 403 rather than waved through."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_an_allowlisted_origin_is_accepted(env, monkeypatch):
    client, _ = env
    monkeypatch.setenv("CHAT_GATEWAY_MCP_ALLOWED_ORIGINS",
                       "https://ok.example, https://also-ok.example")
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Origin": "https://also-ok.example"})
    assert r.status_code != 403
