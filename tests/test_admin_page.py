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
    for f in (p for p in STATIC.iterdir() if p.is_file()):  # avatars/ holds PNGs
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


def test_mcp_snippet_is_gated_on_the_state_flag():
    """CG-90 final review (minor): the reveal panel offers an MCP config only
    when the gateway serves /mcp — otherwise it hands the operator a config for
    a 404."""
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    fn = js[js.index("function reveal("):]
    fn = fn[:fn.index("\n}\n")]
    assert "state.mcp_enabled ?" in fn
    assert fn.count('"MCP client config"') == 1


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


def test_page_probes_before_showing_the_login():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    assert '<section id="login" hidden>' in html
    assert 'id="auth-mode" class="pill warn" hidden>open · no sign-in<' in html
    fn = js[js.index("async function probePosture("):]
    fn = fn[:fn.index("\n}\n")]
    assert "await refresh()" in fn and 'e.status === 401' in fn
    # a 401 shows the login silently; any other failure shows its message
    assert 'e.status === 401 ? "" : e.message' in fn
    assert 'document.addEventListener("DOMContentLoaded"' in js and "probePosture()" in js


def test_hidden_attribute_beats_display_classes():
    """UAT 2026-10-16 found the `open \u00b7 no sign-in` pill visible in key mode:
    `.pill` sets `display`, which outranks the UA `[hidden]{display:none}` rule, so
    neither the markup's `hidden` nor `signOut`'s `.hidden = true` hid it."""
    css = (STATIC / "admin.css").read_text(encoding="utf-8")
    assert "[hidden] { display:none !important; }" in css


def test_api_sends_no_authorization_header_without_a_key():
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    fn = js[js.index("async function api("):]
    fn = fn[:fn.index("\n}\n")]
    assert 'Authorization: "Bearer " +' not in fn
    assert 'if (k) headers.Authorization = "Bearer " + k;' in fn


def test_avatar_route_serves_bundled_icons_and_nothing_else(gw):
    client, *_ = gw
    r = client.get("/admin/static/avatars/alert.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["Content-Security-Policy"]
    assert client.get("/admin/static/avatars/nope.png").status_code == 404
    assert client.get("/admin/static/avatars/..%2Fadmin.py").status_code == 404
    assert client.get("/admin/static/avatars/..%2F..%2Fregistry.py.png").status_code == 404


def test_css_defines_the_cg92_tokens_in_both_schemes():
    css = (STATIC / "admin.css").read_text(encoding="utf-8")
    for token in ("--panel:", "--locked-bg:", "--accent-soft:"):
        assert css.count(token) == 2, f"{token} must be defined in light and dark"
    for needle in (".matrix-wrap", "dialog::backdrop", ".avatar.s40",
                   "@media (max-width: 720px)", "[hidden] { display:none !important; }"):
        assert needle in css, needle


# --- CG-92 Task 6: shell, router, notices, dialog, refusal plumbing ----------

def _js():
    return (STATIC / "admin.js").read_text(encoding="utf-8")


def _html():
    return (STATIC / "index.html").read_text(encoding="utf-8")


def _fn(js, head):
    body = js[js.index(head):]
    return body[:body.index("\n}\n")]


def test_router_knows_the_eight_routes():
    js = _js()
    assert "function routeFromHash(" in js
    fn = _fn(js, "function routeFromHash(")
    for literal in ('"app"', '"identity"', '"room"', '"new-app"', '"new-identity"', '"replace"', '"reveal"', '"board"'):
        assert literal in fn, literal
    for name in ("function navigate(", "function render(", "function guardNavigation(",
                 "function setDirty(", "function notFound(", "function revealView("):
        assert name in js, name
    assert "let dirty = false;" in js
    assert 'addEventListener("hashchange"' in js


def test_unknown_ids_route_to_not_found():
    js = _js()
    assert "state.apps[params.id] || notFound(" in js
    assert "state.identities[params.id] || notFound(" in js
    assert "function appInspector(" in js and "function identityInspector(" in js and "function roomInspector(" in js


def test_typed_confirm_is_a_modal_dialog_with_a_gated_verb():
    js = _js()
    fn = _fn(js, "function typedConfirm(")
    assert "showModal()" in fn
    assert "verbBtn.disabled = " in fn and "expected" in fn
    assert "resolve(null)" in fn or "? null" in fn or ": null" in fn
    assert "focus()" in fn  # focus returns to the trigger
    assert 'class: "card"' not in fn  # the card version is gone
    for opt in ("title", "intro", "reasons", "expected", "verb", "tone"):
        assert opt in js[js.index("function typedConfirm("):][:200], opt


def test_in_page_wording_and_dialog_shell():
    html = _html()
    assert '<dialog id="confirm"' in html and '<dialog id="shortcuts"' in html
    for ident in ("nav-board", "nav-new-app", "nav-new-identity", 'id="filter"', 'id="registry-menu"',
                  "menu-refresh", "menu-reload", "menu-shortcuts", 'id="banners"', 'id="crumbs"',
                  'id="view"', 'id="notices"', 'id="counts"'):
        assert ident in html, ident
    # CG-91 pieces are untouched
    assert '<section id="login" hidden>' in html
    assert 'id="auth-mode" class="pill warn" hidden>open · no sign-in<' in html
    assert "<script>" not in html and "style=" not in html


def test_notices_replace_the_toast():
    js = _js()
    assert "function notify(" in js
    fn = _fn(js, "function notify(")
    assert "6000" in fn and "alert" in fn and "status" in fn
    assert 'role' in fn


def test_api_attaches_category_and_reasons():
    fn = _fn(_js(), "async function api(")
    assert "e.category = data && data.category" in fn or "err.category = data && data.category" in fn
    assert "reasons = data && data.reasons" in fn


def test_explain_is_category_first():
    fn = _fn(_js(), "function explain(")
    assert fn.index("e.category") < fn.index("e.status")


def test_inbound_confirm_passes_reasons_through():
    fn = _fn(_js(), "async function withInboundConfirm(")
    assert "reasons: e.reasons" in fn


def test_probe_resumes_the_hash_and_keys_are_wired():
    js = _js()
    fn = _fn(js, "async function probePosture(")
    assert "render()" in fn and "board()" not in fn
    assert "function onKey(" in js
    keys = _fn(js, "function onKey(")
    assert '"/"' in keys and '"Escape"' in keys and '"?"' in keys
