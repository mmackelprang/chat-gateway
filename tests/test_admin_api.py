"""CG-90 Task 6 — the admin API against a real store in tmp_path."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from chat_gateway.admin import AdminWiring, env_name, parse_webhook_space, widening
from chat_gateway.admin_audit import AdminAudit
from chat_gateway.inbox import Inbox
from chat_gateway.managed_secrets import ManagedSecrets
from chat_gateway.registry import App, load_registry
from chat_gateway.registry_holder import RegistryHolder
from chat_gateway.registry_store import RegistryStore
from chat_gateway.service import create_app

ADMIN = "cgk_admin_secret_for_tests"
AUTH = {"Authorization": f"Bearer {ADMIN}"}
HOOK = "https://chat.googleapis.com/v1/spaces/AAAA1234/messages?key=KEYVAL&token=TOKVAL"
TEXT = """identities:
  i1:
    display: d1
    webhook_url_env: ADM_W1
    space: spaces/OLD1
apps:
  a1:
    key_env: ADM_K1
    identities: [i1]
    allow_inbound: false
  locked:
    key_env: ADM_KL
    identities: [i1]
    allow_inbound: false
    inbound_locked: true
"""


class RecordingAdapter:
    """Records every send, so a job that should have been refused is visible."""

    def __init__(self):
        self.sent = []

    def send(self, identity, message):
        self.sent.append((identity.name, message))
        return {"status": "delivered"}


def _build(tmp_path, monkeypatch, adapter):
    monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", ADMIN)
    monkeypatch.setenv("ADM_K1", "cgk_tenant_one")
    monkeypatch.setenv("ADM_W1", "https://x.example/hook")
    p = tmp_path / "registry.yaml"
    p.write_text(TEXT, encoding="utf-8")
    holder = RegistryHolder(load_registry(p))
    secrets = ManagedSecrets(tmp_path / "state" / "managed.env",
                             process_env_names=frozenset({"CHAT_GATEWAY_ADMIN_KEY"}),
                             environ=os.environ)
    wiring = AdminWiring(store=RegistryStore(p, holder, secrets), secrets=secrets,
                         audit=AdminAudit(tmp_path / "state" / "admin_audit.jsonl"))
    client = TestClient(create_app(holder, Inbox(), {"webhook": adapter}, admin=wiring))
    return client, holder, wiring


def _clean_minted_env():
    for k in list(os.environ):
        if k.startswith(("CHAT_GATEWAY_API_KEY__", "GOOGLE_CHAT_WEBHOOK_URL__")):
            os.environ.pop(k)


@pytest.fixture()
def gw(tmp_path, monkeypatch):
    client, holder, wiring = _build(tmp_path, monkeypatch, object())
    yield client, holder, wiring, tmp_path
    _clean_minted_env()


def _new_app(client, **over):
    body = {"app_id": "newapp", "identities": ["i1"], "routes": {"default": "i1"},
            "allow_inbound": False}
    body.update(over)
    return client.post("/admin/api/apps", headers=AUTH, json=body)


# -- helpers ---------------------------------------------------------------
def test_env_name_convention():
    assert env_name("CHAT_GATEWAY_API_KEY__", "job-hunter") == "CHAT_GATEWAY_API_KEY__JOB_HUNTER"


def test_parse_webhook_space():
    assert parse_webhook_space("  " + HOOK + "\n") == "spaces/AAAA1234"
    for bad in ("http://chat.googleapis.com/v1/spaces/A/messages?key=k&token=t",
                "https://evil.example/v1/spaces/A/messages?key=k&token=t",
                "https://chat.googleapis.com/v1/spaces/A/messages?key=k"):
        with pytest.raises(ValueError) as e:
            parse_webhook_space(bad)
        assert "k&token" not in str(e.value) and "evil" not in str(e.value)


def test_widening_cases():
    old = App(app_id="x", key_env="K", allow_inbound=True, allowed_users=["a@x"])

    class N:
        def __init__(self, **k):
            self.allow_inbound = k.get("allow_inbound", True)
            self.callback_url = k.get("callback_url", "")
            self.allowed_users = k.get("allowed_users", ["a@x"])

    assert widening(None, N(allow_inbound=False, allowed_users=[])) == []
    assert widening(None, N(allowed_users=[])) == ["allow_inbound"]
    assert widening(old, N()) == []
    assert widening(old, N(allowed_users=[])) == ["allowed_users emptied"]
    assert widening(old, N(allowed_users=["a@x", "b@x"])) == ["allowed_users added"]
    assert widening(old, N(callback_url="https://cb")) == ["callback_url"]
    assert widening(old, N(allow_inbound=False, allowed_users=[])) == []


# -- auth -------------------------------------------------------------------
def test_state_requires_the_admin_key(gw):
    client, *_ = gw
    assert client.get("/admin/api/state").status_code == 401
    assert client.get("/admin/api/state",
                      headers={"Authorization": "Bearer cgk_tenant_one"}).status_code == 401
    assert client.get("/admin/api/state", headers=AUTH).status_code == 200


def test_admin_key_is_401_on_tenant_routes(gw):
    client, *_ = gw
    assert client.get("/v1/identities", headers=AUTH).status_code == 401


def test_admin_key_equal_to_a_tenant_key_is_refused(gw, monkeypatch):
    client, *_ = gw
    monkeypatch.setenv("ADM_K1", ADMIN)
    r = client.get("/admin/api/state", headers=AUTH)
    assert r.status_code == 503 and "a1" in r.json()["detail"]


def test_failed_logins_are_rate_limited(gw):
    client, *_ = gw
    bad = {"Authorization": "Bearer wrong"}
    codes = [client.get("/admin/api/state", headers=bad).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    assert client.get("/admin/api/state", headers=AUTH).status_code == 429


def test_unset_admin_key_refuses_everything(gw, monkeypatch):
    client, *_ = gw
    monkeypatch.delenv("CHAT_GATEWAY_ADMIN_KEY")
    assert client.get("/admin/api/state", headers=AUTH).status_code == 401


# -- state never leaks ------------------------------------------------------
def test_state_carries_no_secret_values(gw, monkeypatch):
    client, *_ = gw
    body = client.get("/admin/api/state", headers=AUTH).text
    assert "cgk_tenant_one" not in body and "x.example" not in body and ADMIN not in body
    s = json.loads(body)
    assert s["apps"]["a1"]["key_source"] in {"process", "managed", ".env", "unset"}
    assert s["apps"]["locked"]["inbound_locked"] is True
    assert len(s["registry_sha256"]) == 64


# -- create / rotate / delete ----------------------------------------------
def test_create_app_mints_once_and_it_authenticates(gw):
    client, holder, wiring, tmp = gw
    r = _new_app(client)
    assert r.status_code == 201
    key = r.json()["key"]
    assert key.startswith("cgk_") and r.json()["key_env"] == "CHAT_GATEWAY_API_KEY__NEWAPP"
    assert "newapp" in holder.apps
    assert client.get("/v1/identities",
                      headers={"Authorization": f"Bearer {key}"}).status_code == 200
    assert key not in client.get("/admin/api/state", headers=AUTH).text
    audit = (tmp / "state" / "admin_audit.jsonl").read_text(encoding="utf-8")
    assert "app_created" in audit and key not in audit
    written = (tmp / "registry.yaml").read_text(encoding="utf-8").split("newapp:")[1]
    assert "allow_inbound: false" in written  # hard rule #7: written, never defaulted


def test_create_rejects_bad_and_reserved_ids(gw):
    client, *_ = gw
    for bad in ("_unrouted", "Upper", "has space", ""):
        assert _new_app(client, app_id=bad).status_code == 422
    assert _new_app(client, app_id="a1").status_code == 409


def test_rotate_kills_the_old_key(gw):
    client, *_ = gw
    old = _new_app(client).json()["key"]
    r = client.post("/admin/api/apps/newapp/rotate-key", headers=AUTH, json={})
    new = r.json()["key"]
    assert new != old
    assert client.get("/v1/identities", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert client.get("/v1/identities", headers={"Authorization": f"Bearer {new}"}).status_code == 200


def test_rotate_accepts_no_body_at_all(gw):
    """The body is optional (it only carries `registry_sha256`)."""
    client, *_ = gw
    _new_app(client)
    r = client.post("/admin/api/apps/newapp/rotate-key", headers=AUTH)
    assert r.status_code == 200 and r.json()["key"].startswith("cgk_")


def test_rotating_a_process_env_name_is_refused(gw, monkeypatch):
    client, holder, wiring, _ = gw
    wiring.secrets._process = frozenset({"ADM_K1"})
    r = client.post("/admin/api/apps/a1/rotate-key", headers=AUTH, json={})
    assert r.status_code == 409 and "process environment" in r.json()["detail"]


def test_delete_needs_the_typed_id(gw):
    client, holder, *_ = gw
    _new_app(client)
    assert client.post("/admin/api/apps/newapp/delete", headers=AUTH,
                       json={"confirm_app_id": "nope"}).status_code == 428
    assert client.post("/admin/api/apps/newapp/delete", headers=AUTH,
                       json={"confirm_app_id": "newapp"}).status_code == 200
    assert "newapp" not in holder.apps


# -- inbound guard ----------------------------------------------------------
def test_widening_needs_confirmation(gw):
    client, holder, *_ = gw
    body = {"identities": ["i1"], "routes": {}, "allow_inbound": True}
    r = client.put("/admin/api/apps/a1", headers=AUTH, json=body)
    assert r.status_code == 428 and "hard rule #6" in r.json()["detail"]
    assert holder.apps["a1"].allow_inbound is False
    r = client.put("/admin/api/apps/a1", headers=AUTH, json={**body, "confirm_app_id": "a1"})
    assert r.status_code == 200 and holder.apps["a1"].allow_inbound is True


def test_locked_app_cannot_be_widened_even_with_confirmation(gw):
    client, holder, *_ = gw
    r = client.put("/admin/api/apps/locked", headers=AUTH,
                   json={"identities": ["i1"], "routes": {}, "allow_inbound": True,
                         "confirm_app_id": "locked"})
    assert r.status_code == 403 and "inbound_locked" in r.json()["detail"]
    assert holder.apps["locked"].allow_inbound is False


def test_locked_app_can_still_be_edited_outbound_and_lock_survives(gw):
    client, holder, wiring, tmp = gw
    r = client.put("/admin/api/apps/locked", headers=AUTH,
                   json={"identities": ["i1"], "routes": {"default": "i1"},
                         "allow_inbound": False})
    assert r.status_code == 200
    assert holder.apps["locked"].inbound_locked is True
    assert "inbound_locked: true" in (tmp / "registry.yaml").read_text(encoding="utf-8")


def test_narrowing_needs_no_confirmation(gw):
    client, holder, *_ = gw
    client.put("/admin/api/apps/a1", headers=AUTH,
               json={"identities": ["i1"], "routes": {}, "allow_inbound": True,
                     "confirm_app_id": "a1"})
    r = client.put("/admin/api/apps/a1", headers=AUTH,
                   json={"identities": ["i1"], "routes": {}, "allow_inbound": False})
    assert r.status_code == 200 and holder.apps["a1"].allow_inbound is False


def test_widening_is_audited(gw):
    client, *_, tmp = gw
    client.put("/admin/api/apps/a1", headers=AUTH,
               json={"identities": ["i1"], "routes": {}, "allow_inbound": True,
                     "confirm_app_id": "a1"})
    lines = (tmp / "state" / "admin_audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(l)["action"] == "inbound_widened" for l in lines)


# -- identities -------------------------------------------------------------
def test_webhook_url_is_trimmed_and_never_echoed(gw):
    client, holder, *_ = gw
    r = client.post("/admin/api/identities", headers=AUTH,
                    json={"name": "newid", "display": "New", "webhook_url": "  " + HOOK + "\n"})
    assert r.status_code == 201
    assert "KEYVAL" not in r.text and "TOKVAL" not in r.text
    assert r.json()["space"] == "spaces/AAAA1234"
    assert holder.identities["newid"].env_resolved()
    bad = client.post("/admin/api/identities", headers=AUTH,
                      json={"name": "bad", "display": "B",
                            "webhook_url": "https://evil.example/x?key=KEYVAL&token=TOKVAL"})
    assert bad.status_code == 422 and "KEYVAL" not in bad.text


def test_a_missing_field_never_echoes_the_webhook_url(gw):
    client, *_ = gw
    r = client.post("/admin/api/identities", headers=AUTH, json={"webhook_url": HOOK})
    assert r.status_code == 422 and "KEYVAL" not in r.text and "TOKVAL" not in r.text


def test_replace_webhook_updates_space(gw):
    client, holder, *_ = gw
    r = client.post("/admin/api/identities/i1/webhook", headers=AUTH, json={"webhook_url": HOOK})
    assert r.status_code == 200 and holder.identities["i1"].space == "spaces/AAAA1234"


def test_delete_referenced_identity_is_409(gw):
    client, *_ = gw
    r = client.post("/admin/api/identities/i1/delete", headers=AUTH, json={"confirm_name": "i1"})
    assert r.status_code == 409 and "a1" in r.json()["detail"]


# -- concurrency / reload / healthz ------------------------------------------
def test_stale_second_writer_gets_409(gw):
    client, *_ = gw
    sha = client.get("/admin/api/state", headers=AUTH).json()["registry_sha256"]
    assert _new_app(client, registry_sha256=sha).status_code == 201
    assert _new_app(client, app_id="other", registry_sha256=sha).status_code == 409


def test_reload_from_disk(gw):
    client, holder, wiring, tmp = gw
    p = tmp / "registry.yaml"
    p.write_text(p.read_text(encoding="utf-8") +
                 "  hand:\n    key_env: ADM_KH\n    identities: [i1]\n    allow_inbound: false\n",
                 encoding="utf-8")
    assert _new_app(client).status_code == 409
    assert client.post("/admin/api/reload", headers=AUTH, json={}).status_code == 200
    assert "hand" in holder.apps


def test_healthz_admin_block(gw):
    client, *_ = gw
    _new_app(client, app_id="a1")  # refused 409
    h = client.get("/healthz").json()
    assert h["admin"]["enabled"] is True and h["admin"]["refused"] >= 1
    assert h["admin"]["memory_disk_diverged"] is False
    assert h["status"] in {"ok", "degraded"}
    assert not any("admin" in r for r in h["reasons"])


def test_healthz_admin_disabled_without_wiring(tmp_path, monkeypatch):
    p = tmp_path / "r.yaml"
    p.write_text(TEXT, encoding="utf-8")
    client = TestClient(create_app(load_registry(p), Inbox(), {"webhook": object()}))
    assert client.get("/healthz").json()["admin"] == {"enabled": False}
    assert client.get("/admin/api/state", headers=AUTH).status_code == 404


def test_divergence_degrades_healthz(gw):
    client, holder, wiring, _ = gw
    wiring.store.memory_disk_diverged = True
    h = client.get("/healthz").json()
    assert h["status"] == "degraded" and any("admin console" in r for r in h["reasons"])


# -- C2: the production wiring of the send-time re-check ----------------------
def test_a_job_queued_by_a_deleted_app_is_unroutable_not_sent(tmp_path, monkeypatch):
    """CG-90 C2. `create_app`'s DEFAULT dispatcher, end to end: a job accepted
    while the app existed must not be sent once the console has deleted it."""
    adapter = RecordingAdapter()
    client, holder, wiring = _build(tmp_path, monkeypatch, adapter)
    try:
        key = _new_app(client).json()["key"]
        r = client.post("/v1/notify", headers={"Authorization": f"Bearer {key}"},
                        json={"severity": "info", "title": "queued before delete"})
        assert r.status_code == 202 and r.json()["status"] == "enqueued"
        entry_id = r.json()["id"]
        assert client.post("/admin/api/apps/newapp/delete", headers=AUTH,
                           json={"confirm_app_id": "newapp"}).status_code == 200
        client.app.state.dispatcher.process_due()
        assert adapter.sent == []
        rows = [e for e in client.app.state.delivery_log.query("newapp") if e["id"] == entry_id]
        assert rows and rows[-1]["status"] == "unroutable"
        assert client.get("/healthz").json()["delivery"]["unroutable_live"] == 1
    finally:
        _clean_minted_env()


# -- C4: mutators refuse with StoreError(404), never KeyError ------------------
def test_an_app_or_identity_gone_from_the_file_is_404_not_500(gw):
    """CG-90 C4. The router's existence check reads the HOLDER; the mutator edits
    the FILE's tree under the store lock. Make them disagree — the holder knows
    a `ghost` the file does not — and every write path must answer 404."""
    client, holder, *_ = gw
    import dataclasses
    holder.current.apps["ghost"] = dataclasses.replace(holder.apps["a1"], app_id="ghost")
    holder.current.identities["ghostid"] = dataclasses.replace(
        holder.identities["i1"], name="ghostid", webhook_url_env="ADM_WG")
    calls = [
        ("put", "/admin/api/apps/ghost",
         {"identities": ["i1"], "routes": {}, "allow_inbound": False}),
        ("post", "/admin/api/apps/ghost/delete", {"confirm_app_id": "ghost"}),
        ("put", "/admin/api/identities/ghostid", {"display": "G"}),
        ("post", "/admin/api/identities/ghostid/webhook", {"webhook_url": HOOK}),
        ("post", "/admin/api/identities/ghostid/delete", {"confirm_name": "ghostid"}),
    ]
    tc = TestClient(client.app, raise_server_exceptions=False)
    for method, path, body in calls:
        r = getattr(tc, method)(path, headers=AUTH, json=body)
        assert r.status_code == 404, (path, r.status_code, r.text)
        assert "unknown" in r.json()["detail"]
        assert "KEYVAL" not in r.text


# -- boot wiring ---------------------------------------------------------------
def _boot_env(tmp_path, monkeypatch):
    reg = tmp_path / "registry.yaml"
    reg.write_text(TEXT, encoding="utf-8")
    monkeypatch.setenv("CHAT_GATEWAY_REGISTRY", str(reg))
    monkeypatch.setenv("CHAT_GATEWAY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHAT_GATEWAY_INBOX_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("GATEWAY_ENABLE_ADMIN", "1")
    for k in ("CHAT_GATEWAY_ENV_FILE", "GOOGLE_APPLICATION_CREDENTIALS", "GATEWAY_ENABLE_PUBSUB"):
        monkeypatch.delenv(k, raising=False)


def test_admin_enabled_without_key_is_a_config_error(tmp_path, monkeypatch, capsys):
    from chat_gateway.__main__ import main

    _boot_env(tmp_path, monkeypatch)
    monkeypatch.delenv("CHAT_GATEWAY_ADMIN_KEY", raising=False)
    assert main(["check"]) == 2
    assert "CHAT_GATEWAY_ADMIN_KEY" in capsys.readouterr().err


def test_build_runtime_wires_admin_when_enabled(tmp_path, monkeypatch):
    from chat_gateway.__main__ import build_runtime

    _boot_env(tmp_path, monkeypatch)
    monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", ADMIN)
    admin = build_runtime()[6]
    assert isinstance(admin, AdminWiring)
    assert admin.secrets.blocked("CHAT_GATEWAY_ADMIN_KEY")


def test_build_runtime_admin_is_none_when_disabled(tmp_path, monkeypatch):
    from chat_gateway.__main__ import build_runtime

    _boot_env(tmp_path, monkeypatch)
    monkeypatch.delenv("GATEWAY_ENABLE_ADMIN")
    assert build_runtime()[6] is None


def test_managed_secrets_load_before_and_beat_the_hand_env_file(tmp_path, monkeypatch):
    """The boot order is the whole point: `load_env_file` lets a present value
    win, so managed.env must be applied FIRST for a console-rotated key to
    survive a reboot — and the hand file's names are then recorded as shadowed."""
    from chat_gateway.__main__ import build_runtime

    _boot_env(tmp_path, monkeypatch)
    monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", ADMIN)
    monkeypatch.delenv("ADM_K1", raising=False)
    state = tmp_path / "state"
    state.mkdir()
    (state / "managed.env").write_text('ADM_K1="cgk_rotated"\n', encoding="utf-8")
    hand = tmp_path / "hand.env"
    hand.write_text("ADM_K1=cgk_stale_hand\n", encoding="utf-8")
    monkeypatch.setenv("CHAT_GATEWAY_ENV_FILE", str(hand))
    try:
        admin = build_runtime()[6]
        assert os.environ["ADM_K1"] == "cgk_rotated"
        assert admin.secrets.shadowed() == ["ADM_K1"]
        assert admin.secrets.source_of("ADM_K1") == "managed"
    finally:
        os.environ.pop("ADM_K1", None)


# -- secret-exposure sweep ------------------------------------------------------
def test_no_secret_value_reaches_any_non_mint_surface(gw, capsys):
    client, holder, wiring, tmp = gw
    key = _new_app(client).json()["key"]
    client.post("/admin/api/identities", headers=AUTH,
                json={"name": "newid", "display": "N", "webhook_url": HOOK})
    surfaces = [client.get("/admin/api/state", headers=AUTH).text,
                client.get("/healthz").text,
                (tmp / "state" / "admin_audit.jsonl").read_text(encoding="utf-8"),
                (tmp / "registry.yaml").read_text(encoding="utf-8"),
                capsys.readouterr().out]
    for s in surfaces:
        for secret in (key, "KEYVAL", "TOKVAL", ADMIN):
            assert secret not in s
