"""CG-90 Task 6 — the admin API against a real store in tmp_path."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from chat_gateway.admin import (AUTH_KEY, AUTH_OPEN, AdminWiring, admin_auth_posture,
                                cross_origin_reason, env_name, parse_webhook_space, widening)
from chat_gateway.admin_audit import AdminAudit
from chat_gateway.inbox import Inbox
from chat_gateway.managed_secrets import ManagedSecrets
from chat_gateway.registry import App, RegistryError, load_registry
from chat_gateway.registry_holder import RegistryHolder
from chat_gateway.registry_store import RegistryStore
from chat_gateway.service import create_app

ADMIN = "cgk_admin_secret_for_tests"
AUTH = {"Authorization": f"Bearer {ADMIN}"}
HOOK = "https://chat.googleapis.com/v1/spaces/AAAA1234/messages?key=KEYVAL&token=TOKVAL"
HOOK_LOCKED = "https://chat.googleapis.com/v1/spaces/LOCKED/messages?key=KEYVAL&token=TOKVAL"
# `locked` posts through its OWN identity in its own space. Fix round 1 (I3)
# made locked SPACES the guarantee, so sharing `i1` with `a1` would make every
# a1 widening a locked-space violation — that is the rule working, not a fixture
# the inbound-guard tests below can use.
TEXT = """identities:
  i1:
    display: d1
    webhook_url_env: ADM_W1
    space: spaces/OLD1
  il:
    display: dl
    webhook_url_env: ADM_WL
    space: spaces/LOCKED
apps:
  a1:
    key_env: ADM_K1
    identities: [i1]
    allow_inbound: false
  locked:
    key_env: ADM_KL
    identities: [il]
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


def _build(tmp_path, monkeypatch, adapter, auth="key"):
    if auth == "key":
        monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", ADMIN)
    else:
        # Open posture reads no credential: prove it by not providing one.
        monkeypatch.delenv("CHAT_GATEWAY_ADMIN_KEY", raising=False)
    monkeypatch.setenv("ADM_K1", "cgk_tenant_one")
    monkeypatch.setenv("ADM_W1", "https://x.example/hook")
    p = tmp_path / "registry.yaml"
    p.write_text(TEXT, encoding="utf-8")
    holder = RegistryHolder(load_registry(p))
    secrets = ManagedSecrets(tmp_path / "state" / "managed.env",
                             process_env_names=frozenset({"CHAT_GATEWAY_ADMIN_KEY"}),
                             environ=os.environ)
    wiring = AdminWiring(store=RegistryStore(p, holder, secrets), secrets=secrets,
                         audit=AdminAudit(tmp_path / "state" / "admin_audit.jsonl", auth=auth),
                         auth=auth)
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


@pytest.fixture()
def gw_open(tmp_path, monkeypatch):
    client, holder, wiring = _build(tmp_path, monkeypatch, object(), auth="open")
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


# -- posture ----------------------------------------------------------------
def test_wiring_and_audit_default_to_key_posture(tmp_path):
    """CG-88 lesson: pin the dataclass/constructor defaults themselves, not just the
    loader that passes the value explicitly on every path."""
    assert AdminWiring.__dataclass_fields__["auth"].default == AUTH_KEY == "key"
    assert AdminAudit(tmp_path / "a.jsonl").auth == "key"


def test_posture_defaults_to_key_when_absent_or_empty():
    assert admin_auth_posture(None) == AUTH_KEY
    assert admin_auth_posture("") == AUTH_KEY


def test_posture_accepts_exactly_the_two_values():
    assert admin_auth_posture("key") == AUTH_KEY
    assert admin_auth_posture("open") == AUTH_OPEN


@pytest.mark.parametrize("raw", ["Open", "OPEN", "KEY", "yes", "1", "true", " open"])
def test_posture_is_never_coerced(raw):
    with pytest.raises(RegistryError) as e:
        admin_auth_posture(raw)
    assert "GATEWAY_ADMIN_AUTH" in str(e.value) and "'key'" in str(e.value) and "'open'" in str(e.value)


def test_wiring_defaults_to_key_and_reports_it(gw):
    client, holder, wiring, tmp = gw
    assert wiring.auth == AUTH_KEY
    assert client.get("/healthz").json()["admin"]["auth"] == "key"


# -- cross-origin guard -----------------------------------------------------
@pytest.mark.parametrize("headers", [
    {}, {"sec-fetch-site": "same-origin"}, {"sec-fetch-site": "none"},
    {"origin": "http://gw.local:8085", "host": "gw.local:8085"},
    {"origin": "http://GW.LOCAL:8085", "host": "gw.local:8085"},
])
def test_guard_accepts_same_origin_and_non_browser_requests(headers):
    assert cross_origin_reason(headers) is None


@pytest.mark.parametrize("headers,word", [
    ({"sec-fetch-site": "cross-site"}, "Sec-Fetch-Site"),
    ({"sec-fetch-site": "same-site"}, "Sec-Fetch-Site"),
    ({"origin": "http://evil.example", "host": "gw.local:8085"}, "Origin"),
    ({"origin": "null", "host": "gw.local:8085"}, "Origin"),
    ({"origin": "null"}, "Origin"),
    ({"origin": "http://gw.local:9000", "host": "gw.local:8085"}, "Origin"),
])
def test_guard_refuses_cross_origin_evidence_and_never_echoes_it(headers, word):
    reason = cross_origin_reason(headers)
    assert word in reason and "evil" not in reason and "9000" not in reason


def test_key_mode_refuses_a_valid_bearer_from_a_foreign_origin(gw):
    client, holder, wiring, tmp = gw
    r = client.get("/admin/api/state", headers={**AUTH, "Origin": "http://evil.example"})
    assert r.status_code == 403 and "evil" not in r.text
    admin = client.get("/healthz").json()["admin"]
    assert admin["cross_origin_refused"] == 1
    # The guard must not touch the store's slot: an unauthenticated host would
    # otherwise be able to mask a real store failure (latest-wins).
    assert admin["last_write_error"] is None and admin["refused"] == 0
    r = client.post("/admin/api/reload", headers={**AUTH, "Sec-Fetch-Site": "cross-site"}, json={})
    assert r.status_code == 403
    admin = client.get("/healthz").json()["admin"]
    assert admin["cross_origin_refused"] == 2
    assert admin["last_write_error"] is None and admin["refused"] == 0


def test_guard_runs_before_the_limiter_and_is_not_a_failed_login(gw):
    client, holder, wiring, tmp = gw
    bad = {"Authorization": "Bearer wrong"}
    foreign = {**AUTH, "Origin": "http://evil.example"}
    # Four failures, then cross-origin refusals: if those counted, the fifth
    # wrong bearer below would already be locked out.
    assert [client.get("/admin/api/state", headers=bad).status_code for _ in range(4)] == [401] * 4
    assert [client.get("/admin/api/state", headers=foreign).status_code for _ in range(3)] == [403] * 3
    assert client.get("/admin/api/state", headers=bad).status_code == 401   # 5th real failure
    # Now locked out: a same-origin request is 429, a cross-origin one is
    # still the guard's 403 (it runs first), and neither changes the lockout.
    assert client.get("/admin/api/state", headers=AUTH).status_code == 429
    assert client.get("/admin/api/state", headers=foreign).status_code == 403
    assert client.get("/admin/api/state", headers=bad).status_code == 429


# -- open mode --------------------------------------------------------------
def test_open_mode_needs_no_credential(gw_open):
    client, *_ = gw_open
    assert client.get("/admin/api/state").status_code == 200
    assert client.get("/admin/api/state", headers={"Authorization": "Bearer wrong"}).status_code == 200
    assert client.get("/healthz").json()["admin"]["auth"] == "open"


def test_open_mode_skips_the_limiter_and_the_tenant_key_equality_check(gw_open, monkeypatch):
    client, *_ = gw_open
    monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", "cgk_tenant_one")  # equals ADM_K1
    codes = [client.get("/admin/api/state", headers={"Authorization": "Bearer wrong"}).status_code
             for _ in range(7)]
    assert codes == [200] * 7


def test_open_mode_keeps_the_guards(gw_open):
    client, *_ = gw_open
    assert client.get("/admin/api/state", headers={"Origin": "http://evil.example"}).status_code == 403
    r = client.post("/admin/api/apps/a1/delete", json={"confirm_app_id": "nope"})
    assert r.status_code == 428
    r = client.post("/admin/api/apps/locked/delete", json={"confirm_app_id": "locked"})
    assert r.status_code == 403


def test_key_mode_header_less_requests_do_not_burn_the_limiter(gw):
    client, *_ = gw
    assert [client.get("/admin/api/state").status_code for _ in range(6)] == [401] * 6
    assert client.get("/admin/api/state", headers=AUTH).status_code == 200


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
    for raw in audit.splitlines():  # the new fields carry names, never a value
        line = json.loads(raw)
        assert key not in json.dumps(line)
        assert line["auth"] == "key" and line["client"] == "testclient"
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
    # Fix round 2: a locked app's GRANTS are console-immutable, so the outbound
    # edit this pins is a route edit on its existing identity (was: a switch to
    # i1, which is now — correctly — a 403).
    r = client.put("/admin/api/apps/locked", headers=AUTH,
                   json={"identities": ["il"], "routes": {"default": "il"},
                         "allow_inbound": False})
    assert r.status_code == 200
    assert holder.apps["locked"].routes == {"default": "il"}
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
    # CG-90 Task 9 review: the flag is latched and `reload()` never clears it,
    # so the reason must send the operator to a RESTART, not to Reload.
    reason = next(r for r in h["reasons"] if "admin console" in r)
    assert "restart the gateway" in reason and "use Reload" not in reason


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
    # A developer's shell must not leak a posture into the suite.
    monkeypatch.delenv("GATEWAY_ADMIN_AUTH", raising=False)


def test_open_mode_boots_without_an_admin_key_and_warns(tmp_path, monkeypatch, capsys):
    from chat_gateway.__main__ import build_runtime
    _boot_env(tmp_path, monkeypatch)
    monkeypatch.delenv("CHAT_GATEWAY_ADMIN_KEY", raising=False)
    monkeypatch.setenv("GATEWAY_ADMIN_AUTH", "open")
    admin = build_runtime()[6]
    assert admin.auth == "open" and admin.audit.auth == "open"
    assert "admin: WARNING — GATEWAY_ADMIN_AUTH=open" in capsys.readouterr().err


def test_posture_in_the_env_file_is_ignored(tmp_path, monkeypatch):
    from chat_gateway.__main__ import build_runtime
    _boot_env(tmp_path, monkeypatch)
    monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", ADMIN)
    monkeypatch.delenv("GATEWAY_ADMIN_AUTH", raising=False)
    hand = tmp_path / "hand.env"
    hand.write_text("GATEWAY_ADMIN_AUTH=open\n", encoding="utf-8")
    monkeypatch.setenv("CHAT_GATEWAY_ENV_FILE", str(hand))
    try:
        assert build_runtime()[6].auth == "key"
    finally:
        os.environ.pop("GATEWAY_ADMIN_AUTH", None)


def test_unknown_posture_is_a_config_error(tmp_path, monkeypatch, capsys):
    from chat_gateway.__main__ import main
    _boot_env(tmp_path, monkeypatch)
    monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", ADMIN)
    monkeypatch.setenv("GATEWAY_ADMIN_AUTH", "yes")
    assert main(["check"]) == 2
    assert "GATEWAY_ADMIN_AUTH" in capsys.readouterr().err


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


def test_audit_lines_carry_posture_and_peer(gw, gw_open, monkeypatch):
    for fixture, posture in ((gw, "key"), (gw_open, "open")):
        client, holder, wiring, tmp = fixture
        # Both fixtures share one environment and gw_open's build removed the
        # admin key: put it back for the key iteration, remove it for open.
        if posture == "key":
            monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", ADMIN)
        else:
            monkeypatch.delenv("CHAT_GATEWAY_ADMIN_KEY", raising=False)
        headers = AUTH if posture == "key" else {}
        assert client.post("/admin/api/reload", headers=headers, json={}).status_code == 200
        line = json.loads((tmp / "state" / "admin_audit.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        assert line["auth"] == posture and line["actor"] == "admin"
        assert line["client"] == "testclient"
        assert set(line) == {"at", "actor", "auth", "client", "action", "target", "fields"}


def test_every_write_route_records_the_peer(gw):
    client, holder, wiring, tmp = gw
    _new_app(client)
    client.post("/admin/api/apps/newapp/rotate-key", headers=AUTH, json={})
    client.post("/admin/api/identities", headers=AUTH, json={"name": "i9", "display": "d", "webhook_url": HOOK})
    for line in (tmp / "state" / "admin_audit.jsonl").read_text(encoding="utf-8").splitlines():
        assert json.loads(line)["client"] == "testclient"


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


# ============================================================================
# Fix round 1
# ============================================================================
CB = "https://cb.example/secret-token-XYZ"


def _clean(text: str) -> bool:
    return not any(s in text for s in ("KEYVAL", "TOKVAL", "secret-token-XYZ",
                                        "chat.googleapis.com"))


# -- I1: no 422 under /admin echoes request input ------------------------------
def test_i1_list_typed_webhook_url_is_not_echoed(gw):
    client, *_ = gw
    r = client.post("/admin/api/identities", headers=AUTH,
                    json={"name": "n", "display": "d", "webhook_url": [HOOK]})
    assert r.status_code == 422 and _clean(r.text)


def test_i1_non_json_content_type_is_not_echoed(gw):
    client, *_ = gw
    r = client.post("/admin/api/identities",
                    headers={**AUTH, "Content-Type": "text/plain"},
                    content=f'{{"name":"n","display":"d","webhook_url":"{HOOK}"}}')
    assert r.status_code == 422 and _clean(r.text)


def test_i1_bare_json_string_body_is_not_echoed(gw):
    client, *_ = gw
    r = client.post("/admin/api/identities/i1/webhook", headers=AUTH, json=HOOK)
    assert r.status_code == 422 and _clean(r.text)


def test_i1_app_create_missing_app_id_does_not_echo_the_body(gw):
    client, *_ = gw
    r = client.post("/admin/api/apps", headers=AUTH,
                    json={"callback_url": CB, "allow_inbound": True})
    assert r.status_code == 422 and _clean(r.text)
    assert r.json()["detail"][0]["loc"] == ["body", "app_id"]


def test_i1_a_secret_in_a_dict_KEY_is_not_echoed_through_loc(gw):
    client, *_ = gw
    r = client.put("/admin/api/apps/a1", headers=AUTH,
                   json={"identities": ["i1"], "routes": {HOOK: 5}, "allow_inbound": False})
    assert r.status_code == 422 and _clean(r.text)


def test_i1_non_admin_422_contract_is_unchanged(gw):
    client, *_ = gw
    r = client.post("/v1/notify", headers={"Authorization": "Bearer cgk_tenant_one"},
                    json={"severity": "info"})
    assert r.status_code == 422 and "input" in r.json()["detail"][0]


# -- I2: /healthz publishes a category, never registry free text ---------------
def test_i2_a_url_in_identities_is_refused_before_apply_and_healthz_is_clean(gw):
    client, *_ = gw
    r = client.put("/admin/api/apps/a1", headers=AUTH,
                   json={"identities": ["i1", HOOK], "routes": {}, "allow_inbound": False})
    assert r.status_code == 422 and _clean(r.text)
    assert _clean(client.get("/healthz").text)


def test_i2_unknown_identity_and_route_key_are_refused(gw):
    client, *_ = gw
    r = client.put("/admin/api/apps/a1", headers=AUTH,
                   json={"identities": ["nosuch"], "routes": {}, "allow_inbound": False})
    assert r.status_code == 422 and "nosuch" in r.json()["detail"]
    r = client.put("/admin/api/apps/a1", headers=AUTH,
                   json={"identities": ["i1"], "routes": {"critical": "i1"},
                         "allow_inbound": False})
    assert r.status_code == 422
    r = client.put("/admin/api/apps/a1", headers=AUTH,
                   json={"identities": ["i1"], "routes": {"default": HOOK},
                         "allow_inbound": False})
    assert r.status_code == 422 and _clean(r.text)


def test_i2_a_registry_validation_refusal_shows_only_its_category(gw):
    client, *_ = gw
    # callback_url with inbound OFF: confirmed widening, then the REAL loader
    # refuses it — a RegistryError, whose text the authenticated 422 keeps.
    r = client.put("/admin/api/apps/a1", headers=AUTH,
                   json={"identities": ["i1"], "routes": {}, "allow_inbound": False,
                         "callback_url": CB, "confirm_app_id": "a1"})
    assert r.status_code == 422 and "callback_url" in r.json()["detail"]
    admin = client.get("/healthz").json()["admin"]
    assert admin["last_write_error"] == "refused: registry validation"
    assert _clean(client.get("/healthz").text)


# -- I3: inbound_locked is a guarantee about SPACES -----------------------------
def test_i3_deleting_a_locked_app_is_403(gw):
    client, holder, *_ = gw
    r = client.post("/admin/api/apps/locked/delete", headers=AUTH,
                    json={"confirm_app_id": "locked"})
    assert r.status_code == 403 and "inbound_locked" in r.json()["detail"]
    assert "locked" in holder.apps


def test_i3_granting_a_locked_identity_to_an_inbound_app_is_403(gw):
    client, holder, *_ = gw
    r = _new_app(client, identities=["il"], routes={}, allow_inbound=True,
                 confirm_app_id="newapp")
    assert r.status_code == 403
    assert "locked" in r.json()["detail"] and "hard rule #6" in r.json()["detail"]
    assert "newapp" not in holder.apps


def test_i3_a_new_identity_in_a_locked_space_cannot_carry_inbound(gw):
    client, holder, *_ = gw
    assert client.post("/admin/api/identities", headers=AUTH,
                       json={"name": "inlock", "display": "x",
                             "webhook_url": HOOK_LOCKED}).status_code == 201
    r = _new_app(client, identities=["inlock"], routes={}, allow_inbound=True,
                 confirm_app_id="newapp")
    assert r.status_code == 403 and "newapp" not in holder.apps
    # Outbound only is fine — the guarantee is about inbound.
    r = _new_app(client, identities=["inlock"], routes={}, allow_inbound=False)
    assert r.status_code == 201


def test_i3_widening_an_app_already_in_a_locked_space_is_403(gw):
    client, holder, *_ = gw
    _new_app(client, identities=["il"], routes={}, allow_inbound=False)
    r = client.put("/admin/api/apps/newapp", headers=AUTH,
                   json={"identities": ["il"], "routes": {}, "allow_inbound": True,
                         "confirm_app_id": "newapp"})
    assert r.status_code == 403 and holder.apps["newapp"].allow_inbound is False


def test_i3_webhook_replace_into_a_locked_space_is_403(gw):
    client, holder, *_ = gw
    assert client.put("/admin/api/apps/a1", headers=AUTH,
                      json={"identities": ["i1"], "routes": {}, "allow_inbound": True,
                            "confirm_app_id": "a1"}).status_code == 200
    r = client.post("/admin/api/identities/i1/webhook", headers=AUTH,
                    json={"webhook_url": HOOK_LOCKED})
    assert r.status_code == 403 and holder.identities["i1"].space == "spaces/OLD1"


# -- I4: absent = unchanged for the fields the state view hides -----------------
def _with_callback(client):
    r = client.put("/admin/api/apps/a1", headers=AUTH,
                   json={"identities": ["i1"], "routes": {}, "allow_inbound": True,
                         "callback_url": CB, "unreachable_message": "down",
                         "confirm_app_id": "a1"})
    assert r.status_code == 200


def test_i4_put_without_callback_keeps_it(gw):
    client, holder, wiring, tmp = gw
    _with_callback(client)
    r = client.put("/admin/api/apps/a1", headers=AUTH,
                   json={"identities": ["i1"], "routes": {}, "allow_inbound": True})
    assert r.status_code == 200
    assert holder.apps["a1"].callback_url == CB
    assert holder.apps["a1"].unreachable_message == "down"
    assert CB in (tmp / "registry.yaml").read_text(encoding="utf-8")


def test_i4_put_with_empty_string_removes_it(gw):
    client, holder, *_ = gw
    _with_callback(client)
    r = client.put("/admin/api/apps/a1", headers=AUTH,
                   json={"identities": ["i1"], "routes": {}, "allow_inbound": True,
                         "callback_url": "", "unreachable_message": ""})
    assert r.status_code == 200
    assert holder.apps["a1"].callback_url == "" and holder.apps["a1"].unreachable_message == ""


def test_i4_changing_the_callback_is_still_a_widening(gw):
    client, holder, *_ = gw
    _with_callback(client)
    r = client.put("/admin/api/apps/a1", headers=AUTH,
                   json={"identities": ["i1"], "routes": {}, "allow_inbound": True,
                         "callback_url": "https://other.example/cb"})
    assert r.status_code == 428 and holder.apps["a1"].callback_url == CB


# -- M2 / M3 / M6 -----------------------------------------------------------------
def test_m2_a_non_ascii_bearer_is_a_counted_401_not_a_500(gw):
    client, *_ = gw
    tc = TestClient(client.app, raise_server_exceptions=False)
    r = tc.get("/admin/api/state", headers={"Authorization": b"Bearer caf\xe9"})
    assert r.status_code == 401


def test_m3_an_audit_failure_does_not_lose_the_minted_key(tmp_path, monkeypatch, capsys):
    client, holder, wiring = _build(tmp_path, monkeypatch, object())
    try:
        # A directory where the audit FILE should be: every append fails.
        (tmp_path / "state" / "admin_audit.jsonl").mkdir(parents=True)
        r = _new_app(client)
        assert r.status_code == 201 and r.json()["key"].startswith("cgk_")
        assert "newapp" in holder.apps
        h = client.get("/healthz").json()
        assert h["admin"]["audit_write_errors"] >= 1
        assert not any("admin" in reason for reason in h["reasons"])
        err = capsys.readouterr().err
        assert "admin audit" in err and r.json()["key"] not in err
    finally:
        _clean_minted_env()


def test_m6_mint_and_rotate_responses_are_no_store(gw):
    client, *_ = gw
    r = _new_app(client)
    assert r.status_code == 201 and r.headers["Cache-Control"] == "no-store"
    r = client.post("/admin/api/apps/newapp/rotate-key", headers=AUTH, json={})
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store"


# ============================================================================
# Fix round 2 — a locked app's grants are console-immutable (I3)
# ============================================================================
def test_r2_regranting_a_locked_app_is_403_so_its_space_stays_locked(gw):
    """Probe sequence 1, step 1: moving `locked` off `il` used to un-lock
    spaces/LOCKED, after which a new inbound app could take `il`."""
    client, holder, *_ = gw
    r = client.put("/admin/api/apps/locked", headers=AUTH,
                   json={"identities": ["i1"], "routes": {}, "allow_inbound": False})
    assert r.status_code == 403 and "file edit" in r.json()["detail"]
    assert holder.apps["locked"].identities == ["il"]
    # Additions are refused too — symmetric and simple.
    r = client.put("/admin/api/apps/locked", headers=AUTH,
                   json={"identities": ["il", "i1"], "routes": {}, "allow_inbound": False})
    assert r.status_code == 403
    # ...and the follow-up the bypass needed is still refused.
    assert _new_app(client, identities=["il"], routes={}, allow_inbound=True,
                    confirm_app_id="newapp").status_code == 403


def test_r2_moving_a_locked_apps_identity_out_of_its_space_is_403(gw):
    """Probe sequence 2, step 1: replacing `il`'s webhook used to move the lock
    elsewhere and free spaces/LOCKED for a new identity + inbound app."""
    client, holder, *_ = gw
    r = client.post("/admin/api/identities/il/webhook", headers=AUTH, json={"webhook_url": HOOK})
    assert r.status_code == 403 and "file edit" in r.json()["detail"]
    assert holder.identities["il"].space == "spaces/LOCKED"


def test_r2_locked_app_route_edit_and_identity_rename_still_work(gw):
    client, holder, *_ = gw
    r = client.put("/admin/api/apps/locked", headers=AUTH,
                   json={"identities": ["il"], "routes": {"alert": "il"}, "allow_inbound": False})
    assert r.status_code == 200 and holder.apps["locked"].routes == {"alert": "il"}
    r = client.put("/admin/api/identities/il", headers=AUTH, json={"display": "Renamed"})
    assert r.status_code == 200 and holder.identities["il"].display == "Renamed"


def _hand_violation(client, tmp):
    """A hand edit puts `hand` inbound in the locked space; the console reloads."""
    p = tmp / "registry.yaml"
    p.write_text(p.read_text(encoding="utf-8") +
                 "  hand:\n    key_env: ADM_KH\n    identities: [il]\n    allow_inbound: true\n",
                 encoding="utf-8")
    assert client.post("/admin/api/reload", headers=AUTH, json={}).status_code == 200


def test_r2_a_hand_written_violation_tolerates_an_unrelated_write(gw):
    client, holder, wiring, tmp = gw
    _hand_violation(client, tmp)
    r = client.put("/admin/api/apps/a1", headers=AUTH,
                   json={"identities": ["i1"], "routes": {"default": "i1"},
                         "allow_inbound": False})
    assert r.status_code == 200


def test_r2_touching_the_violating_app_must_narrow_it(gw):
    client, holder, wiring, tmp = gw
    _hand_violation(client, tmp)
    keep = {"identities": ["il"], "routes": {"default": "il"}, "allow_inbound": True}
    r = client.put("/admin/api/apps/hand", headers=AUTH, json=keep)
    assert r.status_code == 403 and "locked" in r.json()["detail"]
    r = client.put("/admin/api/apps/hand", headers=AUTH, json={**keep, "allow_inbound": False})
    assert r.status_code == 200 and holder.apps["hand"].allow_inbound is False


# ============================================================================
# Final-review fix wave (CG-90 final review: C1, I1, I2b, I3, I4, minors)
# ============================================================================
FINAL = """identities:
  pmtrader-alerts:
    display: pm
    webhook_url_env: GOOGLE_CHAT_WEBHOOK_URL__PMTRADER
    space: spaces/PMSPACE
  other:
    display: o
    webhook_url_env: FIN_W_OTHER
    space: spaces/OTHERTENANT
  mine:
    display: m
    webhook_url_env: FIN_W_MINE
    space: spaces/MINE
apps:
  pmtrader:
    key_env: FIN_K_PMTRADER
    identities: [pmtrader-alerts]
    allow_inbound: false
    inbound_locked: true
  legacy:
    key_env: CHAT_GATEWAY_API_KEY__NEWAPP
    identities: [other]
    allow_inbound: false
  consumer:
    key_env: FIN_K_CONSUMER
    identities: [mine]
    allow_inbound: true
"""
PM_ORIG = "https://chat.googleapis.com/v1/spaces/PMSPACE/messages?key=ORIG&token=ORIG"
HOOK_ELSEWHERE = "https://chat.googleapis.com/v1/spaces/ELSEWHERE/messages?key=KEYVAL&token=TOKVAL"


def _build_final(tmp_path, monkeypatch, *, inbox=None, mcp_enabled=False):
    monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", ADMIN)
    monkeypatch.setenv("GOOGLE_CHAT_WEBHOOK_URL__PMTRADER", PM_ORIG)
    monkeypatch.setenv("CHAT_GATEWAY_API_KEY__NEWAPP", "cgk_legacy_key")
    monkeypatch.setenv("FIN_K_CONSUMER", "cgk_consumer_key")
    monkeypatch.setenv("FIN_W_MINE", "https://x.example/mine")
    p = tmp_path / "registry.yaml"
    p.write_text(FINAL, encoding="utf-8")
    holder = RegistryHolder(load_registry(p))
    secrets = ManagedSecrets(tmp_path / "state" / "managed.env",
                             process_env_names=frozenset({"CHAT_GATEWAY_ADMIN_KEY"}),
                             environ=os.environ)
    wiring = AdminWiring(store=RegistryStore(p, holder, secrets), secrets=secrets,
                         audit=AdminAudit(tmp_path / "state" / "admin_audit.jsonl"))
    client = TestClient(create_app(holder, inbox if inbox is not None else Inbox(),
                                   {"webhook": object()}, admin=wiring,
                                   mcp_enabled=mcp_enabled))
    return client, holder, wiring


@pytest.fixture()
def fin(tmp_path, monkeypatch):
    client, holder, wiring = _build_final(tmp_path, monkeypatch)
    yield client, holder, wiring, tmp_path
    _clean_minted_env()


def _audit_actions(tmp):
    path = tmp / "state" / "admin_audit.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# -- C1: a derived env-var name already in use is refused ------------------------
def test_c1_identity_whose_derived_name_is_another_identitys_variable_is_409(fin):
    """The measured shape: `pmtrader` derives GOOGLE_CHAT_WEBHOOK_URL__PMTRADER,
    which locked identity `pmtrader-alerts` already reads. Creating it used to
    re-point the locked identity's webhook, bypassing its immutability."""
    client, holder, *_ = fin
    r = client.post("/admin/api/identities", headers=AUTH,
                    json={"name": "pmtrader", "display": "x", "webhook_url": HOOK_ELSEWHERE})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "GOOGLE_CHAT_WEBHOOK_URL__PMTRADER" in detail and "pmtrader-alerts" in detail
    assert _clean(r.text)
    assert os.environ["GOOGLE_CHAT_WEBHOOK_URL__PMTRADER"] == PM_ORIG
    assert "pmtrader" not in holder.identities
    assert holder.identities["pmtrader-alerts"].space == "spaces/PMSPACE"


def test_c1_app_whose_derived_key_env_is_another_apps_variable_is_409(fin):
    client, holder, *_ = fin
    r = client.post("/admin/api/apps", headers=AUTH,
                    json={"app_id": "newapp", "identities": ["mine"], "routes": {},
                          "allow_inbound": False})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "CHAT_GATEWAY_API_KEY__NEWAPP" in detail and "legacy" in detail
    assert os.environ["CHAT_GATEWAY_API_KEY__NEWAPP"] == "cgk_legacy_key"
    assert "newapp" not in holder.apps
    assert client.get("/v1/identities",
                      headers={"Authorization": "Bearer cgk_legacy_key"}).status_code == 200


def test_c1_a_derived_name_already_set_outside_the_registry_is_409(gw):
    """No registry entry claims it, but managed.env or the hand .env does: an
    orphan the console would silently adopt (and later pop)."""
    client, holder, wiring, tmp = gw
    wiring.secrets.apply({"CHAT_GATEWAY_API_KEY__NEWAPP": "cgk_orphan"})
    r = _new_app(client)
    assert r.status_code == 409 and "CHAT_GATEWAY_API_KEY__NEWAPP" in r.json()["detail"]
    assert "cgk_orphan" not in r.text
    assert os.environ["CHAT_GATEWAY_API_KEY__NEWAPP"] == "cgk_orphan"
    wiring.secrets.hand_env_names = frozenset({"GOOGLE_CHAT_WEBHOOK_URL__NEWID"})
    r = client.post("/admin/api/identities", headers=AUTH,
                    json={"name": "newid", "display": "N", "webhook_url": HOOK})
    assert r.status_code == 409 and "GOOGLE_CHAT_WEBHOOK_URL__NEWID" in r.json()["detail"]
    assert _clean(r.text) and "newid" not in holder.identities


# -- I1: an inbound app gaining a space is a widening ----------------------------
def test_i1_inbound_app_gaining_another_tenants_space_needs_confirmation(fin):
    client, holder, wiring, tmp = fin
    body = {"identities": ["mine", "other"], "routes": {"default": "mine"},
            "allow_inbound": True}
    r = client.put("/admin/api/apps/consumer", headers=AUTH, json=body)
    assert r.status_code == 428 and "identity spaces added" in r.json()["detail"]
    assert holder.apps["consumer"].identities == ["mine"]
    assert holder.apps_for_space("spaces/OTHERTENANT") == ["legacy"]
    r = client.put("/admin/api/apps/consumer", headers=AUTH,
                   json={**body, "confirm_app_id": "consumer"})
    assert r.status_code == 200
    widened = [a for a in _audit_actions(tmp) if a["action"] == "inbound_widened"]
    assert widened and "identity spaces added" in widened[-1]["fields"]


def test_i1_an_outbound_app_gaining_a_space_needs_no_confirmation(fin):
    client, holder, *_ = fin
    r = client.put("/admin/api/apps/legacy", headers=AUTH,
                   json={"identities": ["other", "mine"], "routes": {}, "allow_inbound": False})
    assert r.status_code == 200


def test_i1_webhook_move_of_an_inbound_apps_identity_needs_confirmation(fin):
    client, holder, wiring, tmp = fin
    r = client.post("/admin/api/identities/mine/webhook", headers=AUTH,
                    json={"webhook_url": HOOK_ELSEWHERE})
    assert r.status_code == 428
    assert "consumer" in r.json()["detail"] and _clean(r.text)
    assert holder.identities["mine"].space == "spaces/MINE"
    assert os.environ["FIN_W_MINE"] == "https://x.example/mine"
    r = client.post("/admin/api/identities/mine/webhook", headers=AUTH,
                    json={"webhook_url": HOOK_ELSEWHERE, "confirm_name": "mine"})
    assert r.status_code == 200 and holder.identities["mine"].space == "spaces/ELSEWHERE"
    widened = [a for a in _audit_actions(tmp) if a["action"] == "inbound_widened"]
    assert widened and widened[-1]["target"] == "consumer"


def test_i1_webhook_replace_in_the_same_space_needs_no_confirmation(fin):
    client, holder, *_ = fin
    same = "https://chat.googleapis.com/v1/spaces/MINE/messages?key=KEYVAL&token=TOKVAL"
    r = client.post("/admin/api/identities/mine/webhook", headers=AUTH, json={"webhook_url": same})
    assert r.status_code == 200


# -- I2b: an app with unpolled inbound cannot be deleted --------------------------
def test_i2b_deleting_an_app_with_unpolled_inbound_is_409(tmp_path, monkeypatch):
    from pathlib import Path

    from chat_gateway.adapters.pubsub import dispatch

    inbox = Inbox()
    client, holder, wiring = _build_final(tmp_path, monkeypatch, inbox=inbox)
    try:
        fx = Path(__file__).parent / "fixtures" / "classic-cardclicked-button-event.json"
        ev = json.loads(fx.read_text(encoding="utf-8"))
        ev["space"]["name"] = "spaces/MINE"
        assert dispatch(ev, holder, inbox) == ["consumer"]
        r = client.post("/admin/api/apps/consumer/delete", headers=AUTH,
                        json={"confirm_app_id": "consumer"})
        assert r.status_code == 409 and "1 unpolled" in r.json()["detail"]
        assert "consumer" in holder.apps
        polled = client.get("/v1/inbox", headers={"Authorization": "Bearer cgk_consumer_key"})
        assert polled.status_code == 200
        r = client.post("/admin/api/apps/consumer/delete", headers=AUTH,
                        json={"confirm_app_id": "consumer"})
        assert r.status_code == 200 and "consumer" not in holder.apps
    finally:
        _clean_minted_env()


# -- minor: rotate against an app gone from the file ------------------------------
def test_rotate_of_an_app_gone_from_the_file_is_404_and_mints_nothing(gw):
    client, holder, wiring, tmp = gw
    import dataclasses
    holder.current.apps["ghost"] = dataclasses.replace(holder.apps["a1"], app_id="ghost",
                                                       key_env="ADM_KGHOST")
    tc = TestClient(client.app, raise_server_exceptions=False)
    r = tc.post("/admin/api/apps/ghost/rotate-key", headers=AUTH, json={})
    assert r.status_code == 404 and "unknown" in r.json()["detail"]
    assert wiring.secrets.source_of("ADM_KGHOST") == "unset"
    assert "ADM_KGHOST" not in os.environ


# -- minor: the MCP snippet follows the MCP flag ----------------------------------
def test_state_carries_the_mcp_flag(tmp_path, monkeypatch):
    for enabled in (False, True):
        sub = tmp_path / str(enabled)
        sub.mkdir()
        client, *_ = _build_final(sub, monkeypatch, mcp_enabled=enabled)
        assert client.get("/admin/api/state", headers=AUTH).json()["mcp_enabled"] is enabled


# -- I3 / I4 / boot probe -----------------------------------------------------------
def _boot_off(tmp_path, monkeypatch):
    _boot_env(tmp_path, monkeypatch)
    monkeypatch.delenv("GATEWAY_ENABLE_ADMIN")
    monkeypatch.delenv("ADM_K1", raising=False)


def test_i3_console_off_still_loads_an_existing_managed_env(tmp_path, monkeypatch, capsys):
    """Turning the console off must not revive the .env value a console rotation
    replaced: managed.env loads whenever it exists."""
    from chat_gateway.__main__ import build_runtime

    _boot_off(tmp_path, monkeypatch)
    state = tmp_path / "state"
    state.mkdir()
    (state / "managed.env").write_text('ADM_K1="cgk_rotated"\n', encoding="utf-8")
    hand = tmp_path / "hand.env"
    hand.write_text("ADM_K1=cgk_stale_hand\n", encoding="utf-8")
    monkeypatch.setenv("CHAT_GATEWAY_ENV_FILE", str(hand))
    try:
        assert build_runtime()[6] is None
        assert os.environ["ADM_K1"] == "cgk_rotated"
        out = capsys.readouterr().out
        assert "1 managed secret(s)" in out and "ADM_K1" not in out and "cgk_rotated" not in out
    finally:
        os.environ.pop("ADM_K1", None)


def test_i3_console_off_and_no_managed_env_is_a_no_op(tmp_path, monkeypatch, capsys):
    from chat_gateway.__main__ import build_runtime

    _boot_off(tmp_path, monkeypatch)
    build_runtime()
    assert "managed" not in capsys.readouterr().out
    assert not (tmp_path / "state" / "managed.env").exists()


def test_i4_state_dir_set_only_in_the_env_file_is_honoured_with_the_console_off(
        tmp_path, monkeypatch):
    from chat_gateway.__main__ import build_runtime

    _boot_off(tmp_path, monkeypatch)
    monkeypatch.delenv("CHAT_GATEWAY_STATE_DIR")
    want = tmp_path / "from-env-file"
    hand = tmp_path / "hand.env"
    hand.write_text(f"CHAT_GATEWAY_STATE_DIR={want}\n", encoding="utf-8")
    monkeypatch.setenv("CHAT_GATEWAY_ENV_FILE", str(hand))
    try:
        rt = build_runtime()
        assert rt[4] == str(want)
        assert rt[1]._journal.path == want / "queue" / "inbox.jsonl"
    finally:
        os.environ.pop("CHAT_GATEWAY_STATE_DIR", None)


def test_i4_console_on_with_a_state_dir_the_env_file_moves_is_exit_2(
        tmp_path, monkeypatch, capsys):
    from chat_gateway.__main__ import main

    _boot_env(tmp_path, monkeypatch)
    monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", ADMIN)
    # `load_env_file` never overwrites a present value, so for the two reads to
    # differ the process must NOT carry the variable: managed.env is then
    # resolved against the default, and the env file sets it afterwards.
    monkeypatch.delenv("CHAT_GATEWAY_STATE_DIR")
    hand = tmp_path / "hand.env"
    hand.write_text(f"CHAT_GATEWAY_STATE_DIR={tmp_path / 'elsewhere'}\n", encoding="utf-8")
    monkeypatch.setenv("CHAT_GATEWAY_ENV_FILE", str(hand))
    try:
        assert main(["check"]) == 2
        err = capsys.readouterr().err
        assert "CHAT_GATEWAY_STATE_DIR" in err and "CHAT_GATEWAY_ENV_FILE" in err
    finally:
        os.environ.pop("CHAT_GATEWAY_STATE_DIR", None)


def test_boot_probe_refuses_an_unwritable_registry_directory(tmp_path, monkeypatch, capsys):
    from chat_gateway.__main__ import main

    _boot_env(tmp_path, monkeypatch)
    monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", ADMIN)
    real_open = os.open

    def refusing(path, *a, **k):
        if ".registry.yaml.writable" in str(path):
            raise PermissionError(13, "Permission denied")
        return real_open(path, *a, **k)

    monkeypatch.setattr(os, "open", refusing)
    assert main(["check"]) == 2
    err = capsys.readouterr().err
    assert "not writable" in err and str(tmp_path) in err


# -- rooms ------------------------------------------------------------------------
ROOMS_TEXT = """identities:
  i1:
    display: d1
    webhook_url_env: RM_W1
    space: spaces/A
  i2:
    display: d2
    webhook_url_env: RM_W2
    space: spaces/A
  il:
    display: dl
    webhook_url_env: RM_WL
    space: spaces/LOCKED
  i0:
    display: d0
    webhook_url_env: RM_W0
  iu:
    display: du
    webhook_url_env: RM_WU
    space: spaces/U
apps:
  a1:
    key_env: RM_K1
    identities: [i1]
    allow_inbound: true
  a2:
    key_env: RM_K2
    identities: [i1, i2]
    allow_inbound: false
  locked:
    key_env: RM_KL
    identities: [il]
    allow_inbound: false
    inbound_locked: true
"""


def _build_rooms(tmp_path, monkeypatch, *, inbox=None):
    monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", ADMIN)
    p = tmp_path / "registry.yaml"
    p.write_text(ROOMS_TEXT, encoding="utf-8")
    holder = RegistryHolder(load_registry(p))
    secrets = ManagedSecrets(tmp_path / "state" / "managed.env",
                             process_env_names=frozenset({"CHAT_GATEWAY_ADMIN_KEY"}),
                             environ=os.environ)
    wiring = AdminWiring(store=RegistryStore(p, holder, secrets), secrets=secrets,
                         audit=AdminAudit(tmp_path / "state" / "admin_audit.jsonl"))
    client = TestClient(create_app(holder, inbox if inbox is not None else Inbox(),
                                   {"webhook": object()}, admin=wiring))
    return client, holder


def test_rooms_group_identities_by_space_with_the_unhomed_room_last(tmp_path, monkeypatch):
    client, _ = _build_rooms(tmp_path, monkeypatch)
    rooms = client.get("/admin/api/state", headers=AUTH).json()["rooms"]
    assert list(rooms) == ["spaces/A", "spaces/LOCKED", "spaces/U", ""]
    assert rooms["spaces/A"] == {"identities": ["i1", "i2"], "posting_apps": ["a1", "a2"],
                                 "inbound_apps": ["a1"], "locked_by": None}
    assert rooms["spaces/LOCKED"]["locked_by"] == "locked"
    assert rooms["spaces/U"] == {"identities": ["iu"], "posting_apps": [],
                                 "inbound_apps": [], "locked_by": None}
    assert rooms[""]["identities"] == ["i0"]
    assert rooms[""]["inbound_apps"] == [] and rooms[""]["locked_by"] is None


def test_rooms_agree_with_the_enforcements_own_derivation(tmp_path, monkeypatch):
    from chat_gateway.admin import _shape

    client, holder = _build_rooms(tmp_path, monkeypatch)
    rooms = client.get("/admin/api/state", headers=AUTH).json()["rooms"]
    reg = holder.current
    apps, spaces = _shape(reg)
    locked: dict[str, str] = {}
    for app_id, (_, is_locked, idents) in sorted(apps.items()):
        if is_locked:
            for n in idents:
                if spaces.get(n):
                    locked.setdefault(spaces[n], app_id)
    for space, room in rooms.items():
        assert room["locked_by"] == locked.get(space)
        if space:
            assert room["inbound_apps"] == [a for a in reg.apps_for_space(space)
                                            if reg.apps[a].allow_inbound]


def test_inbox_pending_is_zero_without_an_inbox_and_counts_with_one(tmp_path, monkeypatch):
    from pathlib import Path

    from chat_gateway.adapters.pubsub import dispatch

    client, _ = _build_rooms(tmp_path, monkeypatch)
    apps = client.get("/admin/api/state", headers=AUTH).json()["apps"]
    assert {a: v["inbox_pending"] for a, v in apps.items()} == {"a1": 0, "a2": 0, "locked": 0}

    inbox = Inbox()
    client, holder = _build_rooms(tmp_path, monkeypatch, inbox=inbox)
    fx = Path(__file__).parent / "fixtures" / "classic-cardclicked-button-event.json"
    ev = json.loads(fx.read_text(encoding="utf-8"))
    ev["space"]["name"] = "spaces/A"
    assert dispatch(ev, holder, inbox) == ["a1"]
    apps = client.get("/admin/api/state", headers=AUTH).json()["apps"]
    assert apps["a1"]["inbox_pending"] == inbox.pending_counts()["a1"] == 1
    assert apps["a2"]["inbox_pending"] == 0


# -- refusal bodies: a fixed category beside detail, reasons only when a list ---
def test_refusal_bodies_still_granted_has_a_category_and_no_reasons(gw):
    client, *_ = gw
    r = client.post("/admin/api/identities/i1/delete", headers=AUTH, json={"confirm_name": "i1"})
    assert r.status_code == 409
    body = r.json()
    assert body["category"] == "refused: still granted"
    assert "a1" in body["detail"] and "reasons" not in body
    # (g) /healthz publishes the same authored category and nothing else.
    assert client.get("/healthz").json()["admin"]["last_write_error"] == "refused: still granted"


def test_refusal_bodies_widening_428_lists_its_reasons(gw):
    client, *_ = gw
    r = _new_app(client, allow_inbound=True)
    assert r.status_code == 428
    body = r.json()
    assert body["category"] == "refused: confirmation required"
    assert body["reasons"] == ["allow_inbound"]


def test_refusal_bodies_webhook_move_428_lists_the_moving_apps(fin):
    client, *_ = fin
    r = client.post("/admin/api/identities/mine/webhook", headers=AUTH,
                    json={"webhook_url": HOOK_ELSEWHERE})
    assert r.status_code == 428
    body = r.json()
    assert body["category"] == "refused: confirmation required"
    assert body["reasons"] == ["consumer"]


def test_refusal_bodies_a_typed_confirmation_428_has_no_reasons_key(gw):
    client, *_ = gw
    r = client.post("/admin/api/apps/a1/delete", headers=AUTH, json={"confirm_app_id": "nope"})
    assert r.status_code == 428
    assert r.json()["category"] == "refused: confirmation required"
    assert "reasons" not in r.json()


def test_refusal_bodies_out_of_band_409_has_the_stores_own_category(gw):
    client, holder, wiring, tmp = gw
    p = tmp / "registry.yaml"
    p.write_text(p.read_text(encoding="utf-8") + "# hand edit\n", encoding="utf-8")
    r = _new_app(client)
    assert r.status_code == 409
    assert r.json()["category"] == "refused: edited outside the console"
    assert r.json()["category"] != "refused: still granted"


def test_refusal_bodies_401_and_429_carry_no_category(gw):
    client, *_ = gw
    bad = {"Authorization": "Bearer wrong"}
    codes, bodies = [], []
    for _ in range(7):
        r = client.get("/admin/api/state", headers=bad)
        codes.append(r.status_code)
        bodies.append(r.json())
    assert 401 in codes and 429 in codes
    assert all("category" not in b and "reasons" not in b for b in bodies)


# -- avatars ---------------------------------------------------------------
def _audit_lines(tmp):
    return [json.loads(x) for x in
            (tmp / "state" / "admin_audit.jsonl").read_text(encoding="utf-8").splitlines()]


def _new_identity(client, **over):
    body = {"name": "av1", "display": "Av One", "webhook_url": HOOK}
    body.update(over)
    return client.post("/admin/api/identities", headers=AUTH, json=body)


def test_avatars_create_with_a_bundled_name_shows_in_state(gw):
    from chat_gateway.registry import AVATAR_NAMES
    client, holder, wiring, tmp = gw
    r = _new_identity(client, avatar="phone")
    assert r.status_code == 201 and r.json()["avatar"] == "phone"
    st = client.get("/admin/api/state", headers=AUTH).json()
    assert st["identities"]["av1"]["avatar"] == "phone"
    assert st["identities"]["i1"]["avatar"] is None
    assert st["avatars"] == list(AVATAR_NAMES)
    assert "avatar" in _audit_lines(tmp)[-1]["fields"]


def test_avatars_create_without_one_writes_no_key_and_audits_no_field(gw):
    client, holder, wiring, tmp = gw
    assert _new_identity(client).status_code == 201
    assert "avatar" not in (tmp / "registry.yaml").read_text(encoding="utf-8")
    assert "avatar" not in _audit_lines(tmp)[-1]["fields"]


def test_avatars_create_with_a_bad_value_is_422_naming_the_field_not_the_value(gw):
    client, *_ = gw
    for bad in ("Phone", "http://leak.example/secret.png"):
        r = _new_identity(client, avatar=bad)
        assert r.status_code == 422
        assert "avatar" in r.text and bad not in r.text and "leak.example" not in r.text


def test_avatars_put_url_is_stored_and_display_unchanged(gw):
    client, holder, wiring, tmp = gw
    url = "https://x.example/a.png"
    assert client.put("/admin/api/identities/i1", headers=AUTH, json={"avatar": url}).status_code == 200
    st = client.get("/admin/api/state", headers=AUTH).json()["identities"]["i1"]
    assert st["avatar"] == url and st["display"] == "d1"
    assert _audit_lines(tmp)[-1]["fields"] == ["avatar"]


def test_avatars_put_empty_clears_it(gw):
    client, *_ = gw
    client.put("/admin/api/identities/i1", headers=AUTH, json={"avatar": "alert"})
    r = client.put("/admin/api/identities/i1", headers=AUTH, json={"avatar": ""})
    assert r.status_code == 200
    assert client.get("/admin/api/state", headers=AUTH).json()["identities"]["i1"]["avatar"] is None


def test_avatars_put_display_alone_leaves_avatar_alone(gw):
    client, holder, wiring, tmp = gw
    client.put("/admin/api/identities/i1", headers=AUTH, json={"avatar": "alert"})
    r = client.put("/admin/api/identities/i1", headers=AUTH, json={"display": "New"})
    assert r.status_code == 200
    st = client.get("/admin/api/state", headers=AUTH).json()["identities"]["i1"]
    assert st["avatar"] == "alert" and st["display"] == "New"
    assert _audit_lines(tmp)[-1]["fields"] == ["display"]


def test_avatars_put_blank_display_still_422_and_empty_body_is_422(gw):
    client, *_ = gw
    r = client.put("/admin/api/identities/i1", headers=AUTH, json={"display": ""})
    assert r.status_code == 422 and "display is required" in r.text
    r = client.put("/admin/api/identities/i1", headers=AUTH, json={})
    assert r.status_code == 422 and "nothing to change" in r.text
    assert "display is required" not in r.text


def test_avatars_put_raw_base_url_is_stored_as_the_bundled_name(gw):
    from chat_gateway.registry import AVATAR_RAW_BASE
    client, *_ = gw
    r = client.put("/admin/api/identities/i1", headers=AUTH,
                   json={"avatar": AVATAR_RAW_BASE + "alert.png"})
    assert r.status_code == 200
    assert client.get("/admin/api/state", headers=AUTH).json()["identities"]["i1"]["avatar"] == "alert"


def test_avatars_put_bad_value_is_422_without_echo(gw):
    client, *_ = gw
    r = client.put("/admin/api/identities/i1", headers=AUTH,
                   json={"avatar": "ftp://leak.example/x.png"})
    assert r.status_code == 422 and "avatar" in r.text and "leak.example" not in r.text
