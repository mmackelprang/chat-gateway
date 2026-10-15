"""CG-90 Task 2. Every consumer must observe a swap. One test per consumer
family, because a consumer that captured `holder.current` instead of the holder
would pass every other test in the suite."""
from fastapi.testclient import TestClient

from chat_gateway.inbox import Inbox
from chat_gateway.registry import load_registry
from chat_gateway.registry_holder import RegistryHolder
from chat_gateway.service import create_app

ONE = """identities:
  i1:
    display: d1
    webhook_url_env: HOLD_W1
apps:
  a1:
    key_env: HOLD_K1
    identities: [i1]
    allow_inbound: false
"""
TWO = ONE + """  a2:
    key_env: HOLD_K2
    identities: [i1]
    allow_inbound: false
"""


class _Adapter:
    def send(self, identity, message):
        raise AssertionError("not used")


def _reg(tmp_path, text, name):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return load_registry(p)


def _env(monkeypatch):
    monkeypatch.setenv("HOLD_K1", "cgk_hold_one")
    monkeypatch.setenv("HOLD_K2", "cgk_hold_two")
    monkeypatch.setenv("HOLD_W1", "https://x.example/hook")


def test_attributes_delegate_to_current(tmp_path):
    reg = _reg(tmp_path, ONE, "one.yaml")
    h = RegistryHolder(reg)
    assert h.current is reg
    assert h.apps is reg.apps
    assert h.identity_for("a1", "i1").name == "i1"


def test_swap_returns_old_and_replaces_current(tmp_path):
    one, two = _reg(tmp_path, ONE, "one.yaml"), _reg(tmp_path, TWO, "two.yaml")
    h = RegistryHolder(one)
    assert h.swap(two) is one
    assert h.current is two and "a2" in h.apps


def test_rest_routes_observe_a_swap(tmp_path, monkeypatch):
    _env(monkeypatch)
    h = RegistryHolder(_reg(tmp_path, ONE, "one.yaml"))
    client = TestClient(create_app(h, Inbox(), {"webhook": _Adapter()}))
    auth = {"Authorization": "Bearer cgk_hold_two"}
    assert client.get("/v1/identities", headers=auth).status_code == 401
    h.swap(_reg(tmp_path, TWO, "two.yaml"))
    assert client.get("/v1/identities", headers=auth).status_code == 200


def test_mcp_router_observes_a_swap(tmp_path, monkeypatch):
    _env(monkeypatch)
    monkeypatch.delenv("CHAT_GATEWAY_MCP_ALLOWED_ORIGINS", raising=False)
    h = RegistryHolder(_reg(tmp_path, ONE, "one.yaml"))
    client = TestClient(create_app(h, Inbox(), {"webhook": _Adapter()}, mcp_enabled=True))
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    auth = {"Authorization": "Bearer cgk_hold_two"}
    assert client.post("/mcp", headers=auth, json=body).status_code == 401
    h.swap(_reg(tmp_path, TWO, "two.yaml"))
    assert client.post("/mcp", headers=auth, json=body).status_code != 401


def test_healthz_observes_a_swap(tmp_path, monkeypatch):
    _env(monkeypatch)
    h = RegistryHolder(_reg(tmp_path, ONE, "one.yaml"))
    client = TestClient(create_app(h, Inbox(), {"webhook": _Adapter()}))
    assert "a2" not in client.get("/healthz").json()["registry"]["apps"]
    h.swap(_reg(tmp_path, TWO, "two.yaml"))
    assert "a2" in client.get("/healthz").json()["registry"]["apps"]


def test_build_runtime_hands_out_a_holder(tmp_path, monkeypatch):
    from chat_gateway.__main__ import build_runtime

    reg = tmp_path / "registry.yaml"
    reg.write_text(ONE, encoding="utf-8")
    monkeypatch.setenv("CHAT_GATEWAY_REGISTRY", str(reg))
    monkeypatch.setenv("CHAT_GATEWAY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHAT_GATEWAY_INBOX_DIR", str(tmp_path / "inbox-data"))
    for k in ("CHAT_GATEWAY_ENV_FILE", "GOOGLE_APPLICATION_CREDENTIALS",
              "GATEWAY_ENABLE_PUBSUB", "GATEWAY_ENABLE_ADMIN"):
        monkeypatch.delenv(k, raising=False)
    registry = build_runtime()[0]
    assert isinstance(registry, RegistryHolder)
