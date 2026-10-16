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
    # D5: the board's expanded-rooms set and the selected app are page variables
    # (lost on reload by design), so the storage ban above covers them too.
    assert "let expanded = new Set();" in js and "let selectedApp = null;" in js


def test_api_responses_are_no_store(gw):
    client, *_ = gw
    assert client.get("/admin/api/state", headers=AUTH).headers["cache-control"] == "no-store"


def test_avatar_url_is_handed_to_the_operator_and_nothing_is_loaded_cross_origin():
    """The picker hands the operator the public raw PNG URL to paste into Chat; the
    page never fetches or embeds anything from GitHub (CSP img-src/connect-src
    stay 'self'). The gallery link is gone: the picker replaced it."""
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    assert "AVATAR_GALLERY" not in js and "github.com/mmackelprang" not in js
    assert not re.search(r"""\bsrc\s*[:=]\s*["'`]?https?:""", js)
    assert "new Image" not in js
    assert not re.search(r"""fetch\(\s*["'`]https?:""", js)
    # The only <img> the page builds is the bundled avatar, served same-origin
    # (D6); the raw GitHub URL exists once, as the constant handed to the operator.
    for m in re.finditer(r"""el\("img",\s*\{([^}]*)\}""", js):
        assert 'src: "/admin/static/avatars/"' in m.group(1), m.group(0)
    raw = "https://raw.githubusercontent.com/"
    assert js.count(raw) == 1
    assert f'AVATAR_PNG_PATTERN = "{raw}' in js
    for line in js.splitlines():
        if "https://" in line:
            assert line.lstrip().startswith("const AVATAR_PNG_PATTERN =") or 'startsWith("https://")' in line, line


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
    assert "note: has || !/hard rule #6/i.test(e.message) ? RULE_6 : null" in fn


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
    assert "state.apps[params.id]) || notFound(" in js
    assert "state.identities[params.id]) || notFound(" in js
    assert "Object.hasOwn(state.apps, params.id)" in js and "Object.hasOwn(state.identities, params.id)" in js
    assert "function appInspector(" in js and "function identityInspector(" in js and "function roomInspector(" in js


def test_typed_confirm_is_a_modal_dialog_with_a_gated_verb():
    js = _js()
    fn = _fn(js, "function typedConfirm(")
    assert "showModal()" in fn
    assert "verbBtn.disabled = " in fn and "expected" in fn
    assert 'v === "ok" ? input.value : null' in fn
    assert "trigger.focus()" in js[js.index("function dialogClosed("):js.index("function typedConfirm(")]
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


def test_route_key_is_the_single_normalisation():
    js = _js()
    assert 'function routeKey(hash) { return hash || "#/"; }' in js
    assert "shownHash = routeKey(window.location.hash)" in js
    assert "const target = routeKey(window.location.hash)" in js
    nav = _fn(js, "function navigate(")
    assert "routeKey(window.location.hash) === routeKey(hash)) render()" in nav


def test_hrefFor_is_the_only_route_builder():
    js = _js()
    assert "function hrefFor(name, id)" in js
    outside = js.replace(_fn(js, "function hrefFor("), "")
    assert '"#/app/"' not in outside and '"#/identity/"' not in outside and '"#/room/"' not in outside


def test_show_key_bypasses_the_guard_and_sign_out_clears_dirty():
    js = _js()
    sk = _fn(js, "function showKey(")
    assert "setDirty(false)" in sk and "navigate(" not in sk and "guardNavigation" not in sk
    assert "setDirty(false)" in _fn(js, "function signOut(")


def test_dialog_copy_prefers_reasons_over_detail():
    js = _js()
    assert 'REFUSED_INTRO = "The server refused this save until you confirm:"' in js
    assert "intro: has ? REFUSED_INTRO : e.message" in _fn(js, "async function withInboundConfirm(")
    assert "intro: has ? REFUSED_INTRO : e.message" in _fn(js, "function replaceWebhook(")


def test_view_is_not_a_live_region_and_toast_rule_is_gone():
    assert "aria-live" not in _html()
    css = (STATIC / "admin.css").read_text(encoding="utf-8")
    assert "#toast" not in css and "kbd {" in css


# --- CG-92 Task 7: the board — grant matrix, bounded region, collapsible rooms

CAPTION = ("Which app may send as which identity, grouped by room. A column with two or more dots "
           "is a shared identity; a collapsed room shows one column, and a dot there means the app "
           "sends into that room.")


def test_board_is_a_real_table_in_a_bounded_region():
    js = _js()
    fn = _fn(js, "function board(")
    assert 'class: "matrix"' in js and 'class: "matrix-wrap"' in js
    assert 'el("caption"' in js and CAPTION in js
    assert 'scope: "colgroup"' in js and 'scope: "col"' in js and 'scope: "row"' in js
    assert '"table-wrap"' not in fn  # the two old tables are gone
    assert "state.rooms" in fn  # D2: the page never re-derives rooms


def test_rooms_collapse_by_default_in_page_memory_only():
    js = _js()
    assert "let expanded = new Set();" in js and "let selectedApp = null;" in js
    for name in ("function toggleRoom(", "function expandAll(", "function collapseAll(", "function expandRoomsOf("):
        assert name in js, name
    assert '"aria-expanded"' in js
    assert '"any identity here"' in js
    assert '"Expand all rooms"' in js and '"Collapse all rooms"' in js
    assert '" room groups expanded · remembered for this session only"' in js
    assert "Enter expands the room" in js
    # a collapsed group header shows the id WITHOUT `spaces/`; the full id stays in the title and the expanded header
    fn = _fn(js, "function groupHeaderCell(")
    assert 'const shortLabel = g.space ? roomSegment(g.space) : "no room";' in fn
    assert 'title: roomLabel(g.space), text: collapsed ? shortLabel : roomLabel(g.space)' in fn
    assert "cannot route inbound; not covered by any lock" in js
    assert 'id: "expand-all"' in js and 'id: "collapse-all"' in js


def test_avatar_mark_is_same_origin_or_a_dashed_circle():
    js = _js()
    fn = _fn(js, "function avatarMark(")
    assert 'src: "/admin/static/avatars/"' in fn and 'alt: ""' in fn
    assert "createElementNS" in fn and '"custom avatar URL"' in fn and '"no avatar recorded"' in fn
    assert "state.avatars" in fn  # a bundled NAME, decided by the server's list, not by shape
    assert "function relTime(" in js


def test_filter_is_a_plain_substring_never_a_regexp():
    js = _js()
    fn = _fn(js, "function applyFilter(")
    assert ".toLowerCase().includes(" in fn
    assert "new RegExp(" not in js
    assert '" apps · "' in fn and '" identities match "' in fn


def test_grid_keyboard_contract():
    js = _js()
    fn = _fn(js, "function gridKeydown(")
    for key in ('"ArrowLeft"', '"ArrowRight"', '"Home"', '"End"', '"ArrowUp"', '"ArrowDown"', '"Enter"', '" "'):
        assert key in fn, key
    assert "setRovingStop(cells, target)" in fn  # one stop: the moved-to cell gets tabindex 0
    assert "tabIndex = -1" in _fn(js, "function setRovingStop(") and "tabIndex = 0" in _fn(js, "function setRovingStop(")
    # Up/Down between the group row and the identity row ride on the group's span;
    # a collapsed column (header or cell) expands on Enter/click.
    assert "dataset.span" in fn and "cur.dataset.collapsed" in fn
    assert '"data-span": g.start + "," + g.end' in js and '"data-collapsed": collapsed ? "1" : null' in js
    assert "cell.dataset.collapsed" in _fn(js, "function gridClick(")
    # edges: the arrow is claimed before the target search, so the page never scrolls under the grid
    assert fn.index("ev.preventDefault()") < fn.index("const cells = ")
    # after a toggle the matrix re-renders and focus returns to that room's header
    assert "focusRoomHeader(" in _fn(js, "function toggleRoom(")
    assert 'x.dataset.grid.startsWith("0,")' in _fn(js, "function focusRoomHeader(")


def test_board_states_are_worded_as_the_spec():
    js = _js()
    assert '"aria-busy": "true"' in js and "Loading registry…" in js
    assert "Nothing registered yet. An app needs an identity to send as, so start there." in js
    assert "identities, no apps. Nothing can send until an app is registered and granted one." in js
    assert "apps and nothing to send as. Every grant list is empty." in js
    assert "Could not load the registry view (HTTP " in js and 'text: "Retry", on: { click: reloadView }' in js
    assert "reloadView()" in js[js.index('$("menu-refresh")'):]  # a failed Refresh view is the card, not a stale board
    assert 'class: "cards"' in js  # phone rendering of the same data
    css = (STATIC / "admin.css").read_text(encoding="utf-8")
    assert css.count("var(--group-h)") == 2 and "--group-h:" in css  # one height for the group row and the identity row's top


# --- CG-92 Task 8: the app inspector — grants by room, consequences before Save

def test_app_inspector_replaces_app_detail_and_tracks_dirty():
    js = _js()
    assert "function appInspector(" in js and "function appDetail(" not in js
    fn = _fn(js, "function appInspector(")
    assert "expandRoomsOf(" in fn  # D5: entry expands the app's rooms and selects its row
    assert "setDirty(" in fn
    assert '"Unsaved changes"' in js and '"No changes"' in js
    assert 'class: "savebar"' in js
    assert "ungrant" in fn  # `?ungrant=<name>` enters with that box unchecked and the bar dirty
    assert 'addEventListener("input"' in fn and 'addEventListener("change"' in fn


def test_app_inspector_copy_is_the_specs():
    js = _js()
    # API key card: one status line by key_source; rotate/mint disabled when the process env owns the key
    assert 'key_source === "process"' in js
    assert "Missing — this app cannot authenticate. Mint a key to fix it." in js
    assert "which overrides managed.env at boot — rotate it in the compose environment, not here" in js
    assert "is still in the read-only .env — inert now, but it would come back if managed.env were lost. Remove that line by hand." in js
    # Sends as: the three dynamic notes and the locked callout
    assert "New room for an inbound app — Save will ask you to confirm (rule #6)" in js
    assert "Also removes its routes: " in js and "Severities left without a route return 503 at /v1/notify" in js
    assert " — an inbound app cannot be granted an identity here." in js
    assert "Grants on an inbound_locked app are a registry file edit, not a console action. Routes and display names stay editable here." in js
    assert "held by no other app" in js and "also held by " in js
    # Routes: the computed CG-86 line, four variants
    assert "an all-clear will land in a different room from the alert it closes" in js
    assert "All severities post to one room." in js
    assert "No routes — every /v1/notify returns 503. Set a default at least" in js
    # Inbound
    assert "Receives inbound from:" in js and "nothing (inbound off)" in js
    assert "Inbound can be narrowed here, never widened." in js
    assert "turning this on asks for a typed confirmation" in js
    # Recent deliveries, danger zone
    assert "No deliveries since the gateway started. The log is in memory; the newest five are shown." in js
    assert "inbox_pending" in js and "poll or drain its inbox first" in js
    assert "Deleting an inbound_locked app is a registry file edit" in js
    assert "queued messages close as unroutable" in js


def test_read_app_fields_keeps_the_ordered_identities_rule_and_the_put_body():
    js = _js()
    fn = _fn(js, "function readAppFields(")
    assert "if (a.inbound_locked) identities = a.identities.slice();" in fn
    for key in ("identities,", "routes,", "allow_inbound:", 'callback_url: readOptional(form, "callback_url")',
                "allowed_users:", 'unreachable_message: readOptional(form, "unreachable_message")'):
        assert key in fn, key
    save = _fn(js, "function appInspector(")
    assert 'withInboundConfirm(appId, (c) => write("PUT", "/admin/api/apps/" + encodeURIComponent(appId), Object.assign(readAppFields(form, a), { confirm_app_id: c })))' in save


def test_router_parses_the_query_string():
    fn = _fn(_js(), "function routeFromHash(")
    assert "URLSearchParams" in fn


# --- CG-92 Task 9: identity and room inspectors, avatar picker, replace webhook

def test_identity_and_room_inspectors_and_picker_copy():
    js = _js()
    for head in ("function identityInspector(", "function roomInspector(", "function avatarPicker(", "function replaceWebhook("):
        assert head in js, head
    assert "function renameIdentity(" not in js  # the inspector renames inline
    assert "aria-pressed" in _fn(js, "function avatarPicker(")
    assert "avatarMark(" in _fn(js, "function avatarPicker(") and ", 40)" in _fn(js, "function avatarPicker(")
    assert '"Recorded: bundled icon' in js and "Remove it from" in js and "Select URL" in js
    assert "AVATAR_PNG_PATTERN.replace(" in js and 'startsWith("https://")' in js
    assert "Recording an avatar here does not change the webhook." in js
    assert "Not granted to any app. Nothing can send as this identity" in js
    assert "?ungrant=" in js and "Consequences" in js
    fn = _fn(js, "function identityInspector(")
    assert 'write("PUT", url, { avatar: pending })' in fn and '"/admin/api/identities/" + encodeURIComponent(name)' in fn
    assert "Delete identity" in js or "deleteIdentity(" in fn


# --- CG-92 Task 10: new app draft, identity stepper, reveal, discard guard

def test_new_app_draft_return_ticket_and_stepper():
    js = _js()
    assert "?return=new-app" in js and "let draft = null;" in js
    assert '"Discard the unsaved new app?"' in js and '"Discard unsaved changes?"' in js
    assert '"Back to new app (pre-granted)"' in js
    ni = _fn(js, "function newIdentity(")
    assert "avatarPicker(" in ni and "avatar" in ni
    assert 'query.get("return") === "new-app"' in ni and "Open identity" in js  # never an unconditional jump
    assert "Never shown again" in js


def test_reveal_view_selects_on_http_and_done_is_the_only_way_out():
    js = _js()
    fn = _fn(js, "function reveal(")
    assert "window.isSecureContext" in js and "Copy — selects on HTTP" in fn
    assert '"Select key"' in fn and "details" in fn and '"Done — I have stored the key"' in js
    assert "Leave this page and the key is gone" in js


def test_stale_page_panel_picks_the_recovery_by_category():
    js = _js()
    fn = _fn(js, "function stalePanel(")
    assert "Refresh view" in fn and "Reload from disk" in fn
    assert "The registry changed since this page loaded. Your edits are kept." in js
    assert "refused: edited outside the console" in fn
