"""CG-90 Task 7 — the shell is static, CSP-locked, and stores nothing."""
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chat_gateway.admin import AdminWiring
from chat_gateway.admin_audit import AdminAudit
from chat_gateway.inbox import Inbox
from chat_gateway.managed_secrets import ManagedSecrets
from chat_gateway.registry import load_registry
from chat_gateway.registry_holder import RegistryHolder
from chat_gateway.registry_store import RegistryStore
from chat_gateway.service import create_app

STATIC = Path(__file__).resolve().parents[1] / "src" / "chat_gateway" / "static" / "admin"
ADMIN = "cgk_admin_page_tests"
AUTH = {"Authorization": f"Bearer {ADMIN}"}


@pytest.fixture()
def gw(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", ADMIN)
    p = tmp_path / "registry.yaml"
    p.write_text("identities:\n  i1:\n    display: d\n    webhook_url_env: PG_W\n"
                 "apps:\n  a1:\n    key_env: PG_K\n    identities: [i1]\n"
                 "    allow_inbound: false\n", encoding="utf-8")
    holder = RegistryHolder(load_registry(p))
    secrets = ManagedSecrets(tmp_path / "state" / "managed.env",
                             process_env_names=frozenset(), environ=os.environ)
    wiring = AdminWiring(store=RegistryStore(p, holder, secrets), secrets=secrets,
                         audit=AdminAudit(tmp_path / "state" / "admin_audit.jsonl"))
    return (TestClient(create_app(holder, Inbox(), {"webhook": object()}, admin=wiring)),)


def test_page_is_served_with_strict_headers(gw):
    client, *_ = gw
    r = client.get("/admin")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp
    assert r.headers["cache-control"] == "no-store"


def test_only_known_static_files_are_served(gw):
    client, *_ = gw
    assert client.get("/admin/static/admin.js").status_code == 200
    assert client.get("/admin/static/admin.css").status_code == 200
    assert client.get("/admin/static/..%2Fadmin.py").status_code == 404
    assert client.get("/admin/static/index.html").status_code == 404


def test_no_inline_script_and_no_third_party_origin():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html and "onclick=" not in html
    for f in STATIC.iterdir():
        text = f.read_text(encoding="utf-8")
        assert "http://" not in text and "cdn" not in text.lower()


def test_the_admin_key_is_never_persisted_by_the_page():
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    for api in ("localStorage", "sessionStorage", "document.cookie", "indexedDB"):
        assert api not in js
    assert "innerHTML" not in js  # all data rendered via textContent


def test_api_responses_are_no_store(gw):
    client, *_ = gw
    assert client.get("/admin/api/state", headers=AUTH).headers["cache-control"] == "no-store"


def test_avatar_gallery_is_a_link_and_nothing_is_loaded_cross_origin():
    """The webhook guide links the avatar gallery; the page never fetches or
    embeds anything from GitHub (CSP img-src/connect-src stay 'self')."""
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    gallery = "https://github.com/mmackelprang/chat-gateway/tree/main/assets/avatars"
    assert f'AVATAR_GALLERY = "{gallery}"' in js
    assert 'el("a", { href: AVATAR_GALLERY, target: "_blank", rel: "noopener noreferrer"' in js
    assert not re.search(r"""\bsrc\s*[:=]\s*["'`]?https?:""", js)
    assert 'el("img"' not in js and "new Image" not in js
    assert not re.search(r"""fetch\(\s*["'`]https?:""", js)


def test_write_never_throws_after_the_mutation_succeeded():
    """A minted or rotated key is committed server-side before `refresh()` runs;
    if that follow-up GET threw, the caller would never reach `reveal()` and the
    key would be lost (for a rotation, the old one is already dead)."""
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    body = js[js.index("async function write("):]
    body = body[:body.index("\n}\n")]
    assert "try { await refresh(); }" in body
    assert body.count("await refresh()") == 1
    assert body.rstrip().endswith("return out;")


def test_conditional_children_never_render_as_literal_null():
    """UAT (Task 8) saw a literal "null" on the board and the reveal panel:
    DOM append/prepend/replaceChildren stringify null. Every such call must go
    through the one helper that skips null/undefined."""
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    helper = js[js.index("function toNodes("):]
    helper = helper[:helper.index("\n}\n")]
    assert "if (c != null)" in helper
    assert "function view(...nodes) { $(\"view\").replaceChildren(...toNodes(nodes)); }" in js
    calls = re.findall(r"\.(append|prepend|replaceChildren)\(([^)]*)", js)
    assert calls, "expected DOM insertion calls"
    for method, arg in calls:
        assert arg.startswith("...toNodes("), f".{method}({arg}) bypasses toNodes"


def test_rule_6_is_stated_once_in_the_typed_confirm():
    """The server's 428 detail already quotes hard rule #6; the page appends its
    own copy only when the server's text lacks it."""
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    fn = js[js.index("async function withInboundConfirm("):]
    fn = fn[:fn.index("\n}\n")]
    assert '/hard rule #6/i.test(e.message) ? e.message : e.message + "\\n\\n" + RULE_6' in fn


def test_replace_webhook_handles_the_inbound_428():
    """CG-90 final review I1: moving an inbound app's identity to a new space is
    a 428; the page answers it with one typed confirmation of the identity name."""
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    fn = js[js.index("function replaceWebhook("):]
    fn = fn[:fn.index("\n}\n")]
    assert "e.status !== 428" in fn and "typedConfirm(" in fn and "confirm_name" in fn


def test_no_inline_style_attribute_the_csp_would_block():
    """The page's CSP is `style-src 'self'` with no 'unsafe-inline', which blocks
    `style="…"` attributes — including ones set through setAttribute. A styled
    element that silently renders unstyled is the failure; classes in admin.css
    are the fix."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    assert "style=" not in html and "<style" not in html
    assert not re.search(r"""\bstyle\s*:\s*["']""", js)
    assert "setAttribute(\"style\"" not in js and "setAttribute('style'" not in js
