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


def _swap_after_auth(monkeypatch, module, h, to):
    """Authenticate against the CURRENT registry, then swap before the handler
    runs — the console deleting an app between a request's auth and its body."""
    real = module.authenticate

    def racing(registry, authorization):
        app_id = real(registry, authorization)
        h.swap(to)
        return app_id

    monkeypatch.setattr(module, "authenticate", racing)


def test_rest_app_deleted_between_auth_and_handler_is_401_not_500(tmp_path, monkeypatch):
    """CG-90 C1. Answer as a request arriving after the swap would: 401."""
    import chat_gateway.service as service

    _env(monkeypatch)
    one = _reg(tmp_path, ONE, "one.yaml")
    two = _reg(tmp_path, TWO, "two.yaml")
    auth = {"Authorization": "Bearer cgk_hold_two"}
    for path in ("/v1/inbox", "/v1/identities"):
        h = RegistryHolder(two)
        client = TestClient(create_app(h, Inbox(), {"webhook": _Adapter()}),
                            raise_server_exceptions=False)
        _swap_after_auth(monkeypatch, service, h, one)
        r = client.get(path, headers=auth)
        assert r.status_code == 401, (path, r.status_code)


def test_mcp_app_deleted_between_auth_and_handler_is_401_not_500(tmp_path, monkeypatch):
    """CG-90 C1. Same answer `mcp_post` gives an unknown key: a 401 with a
    JSON-RPC error body, never a 500."""
    import chat_gateway.mcp as mcp

    _env(monkeypatch)
    monkeypatch.delenv("CHAT_GATEWAY_MCP_ALLOWED_ORIGINS", raising=False)
    one = _reg(tmp_path, ONE, "one.yaml")
    two = _reg(tmp_path, TWO, "two.yaml")
    auth = {"Authorization": "Bearer cgk_hold_two"}
    bodies = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},           # send_message_schema
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",            # call_tool's refusal
         "params": {"name": "send_message",
                    "arguments": {"identity": "nope", "text": "hi"}}},
    ]
    for body in bodies:
        h = RegistryHolder(two)
        client = TestClient(create_app(h, Inbox(), {"webhook": _Adapter()}, mcp_enabled=True),
                            raise_server_exceptions=False)
        _swap_after_auth(monkeypatch, mcp, h, one)
        r = client.post("/mcp", headers=auth, json=body)
        assert r.status_code == 401, (body["method"], r.status_code)
        assert r.headers.get("WWW-Authenticate") == "Bearer"
        assert r.json()["error"]["message"] == "unknown API key"


TORN_A = """identities:
  i:
    display: d
    webhook_url_env: TORN_W
    space: spaces/TORN
apps:
  optedout:
    key_env: TORN_K
    identities: [i]
    allow_inbound: false
"""
TORN_B = """identities:
  i:
    display: d
    webhook_url_env: TORN_W
    space: spaces/TORN
  j:
    display: e
    webhook_url_env: TORN_W2
apps:
  other:
    key_env: TORN_K2
    identities: [j]
    allow_inbound: false
"""


def _torn_event():
    import json
    from pathlib import Path

    fx = Path(__file__).parent / "fixtures" / "classic-cardclicked-button-event.json"
    ev = json.loads(fx.read_text(encoding="utf-8"))
    ev["space"]["name"] = "spaces/TORN"
    return ev


def test_dispatch_reads_one_snapshot_so_a_mid_event_delete_cannot_leak_inbound(tmp_path):
    """CG-90 final review I2a. `dispatch` chose candidates from one snapshot and
    looked each app up in the NEXT: a console delete in between left `app` None,
    skipped the opt-out check, and put the event in the deleted (opted-out)
    app's inbox. Swap the holder between those two reads."""
    from chat_gateway.adapters.pubsub import REASON_OPT_OUT, dispatch

    ra, rb = _reg(tmp_path, TORN_A, "a.yaml"), _reg(tmp_path, TORN_B, "b.yaml")
    h = RegistryHolder(ra)
    real = ra.apps_for_space

    def swapping(space):
        out = real(space)
        h.swap(rb)
        return out

    ra.apps_for_space = swapping
    inbox = Inbox()
    suppressed = []
    got = dispatch(_torn_event(), h, inbox, on_suppressed=lambda a, r: suppressed.append((a, r)))
    assert got == []
    assert inbox.pending_counts() == {}
    assert suppressed == [("optedout", REASON_OPT_OUT)]


def test_dispatch_never_puts_for_a_candidate_with_no_app(tmp_path):
    """Belt and braces for I2a: whatever the snapshot says, a candidate id that
    is not a registered app (and is not `_unrouted`) is skipped, never put."""
    from chat_gateway.adapters.pubsub import dispatch

    ra = _reg(tmp_path, TORN_A, "a.yaml")
    ra.apps_for_space = lambda space: ["ghost"]
    inbox = Inbox()
    suppressed = []
    got = dispatch(_torn_event(), RegistryHolder(ra), inbox,
                   on_suppressed=lambda a, r: suppressed.append((a, r)))
    assert got == [] and inbox.pending_counts() == {}
    assert [a for a, _ in suppressed] == ["ghost"]


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
