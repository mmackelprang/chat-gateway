# Admin Console Management Surface (CG-92) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redraw `/admin` around the resource several apps share — an identity and the room it posts into — as a grant matrix with app, identity and room inspectors, with avatars recorded per identity, on top of four additive server changes.

**Architecture:** Server first: `state()` gains a server-derived `rooms` block and per-app `inbox_pending`; refusals carry a machine-readable `category` (and `reasons` on the two list-bearing 428s) through one `AdminRefusal` exception and one handler; identities gain an optional `avatar` validated at load, with the bundled PNGs served same-origin from the package. Then the page: one hash router, a `<dialog>`-based confirm, a notice stack, the matrix board with a bounded scroll region and collapsible rooms, three inspectors, and lifecycle flows with return tickets — vanilla JS/CSS under the existing CSP, keeping CG-91's probe, pill and `api()` lines byte-for-byte.

**Tech Stack:** Python 3.10+, FastAPI, pydantic, `ruamel.yaml`, pytest (offline; `.venv/bin/python -m pytest -q -p no:cacheprovider`), vanilla HTML/JS/CSS, Playwright via the tester agent for UAT.

**Spec:** `docs/superpowers/specs/2026-10-16-admin-console-ux-design.md` · handoff `docs/design-handoffs/admin-console-ux/` (mockup `mockups/index.html`, renders)

## Global Constraints

- Hard rule #2: no stored secret or webhook URL is ever displayed or returned; `category` strings are fixed literals, never interpolated; an identity's `avatar` is a bundled icon name or a public `https://` URL and never a webhook URL. Env-var NAMES only. No LAN IP literal anywhere (`<LAN-IP>` in docs; a test enforces it).
- Hard rule #6: 428 typed confirmations and `inbound_locked` 403s are unchanged in behaviour; the page only predicts and explains them.
- Hard rule #7: `avatar` is validated exactly — a known bundled name (case-sensitive) or `https://…`; anything else refuses at load and at write.
- `/healthz` field set is unchanged; `last_write_error` may become more specific via two new authored categories: `refused: still granted` and `refused: secret in process env`.
- All server changes are additive: every existing `state()` field keeps its shape; every existing request body keeps working; existing admin tests pass without edits (except where a test pins the old `DisplayIn` class name).
- CG-91 invariants in the page, byte-for-byte: `async function probePosture(`, `id="auth-mode" class="pill warn" hidden>open · no sign-in<`, `<section id="login" hidden>`, `if (k) headers.Authorization = "Bearer " + k;`, `e.status === 401 ? "" : e.message`, `[hidden] { display:none !important; }`.
- Page: no `localStorage`/`sessionStorage`/`document.cookie`/`indexedDB`/`innerHTML`, no `style=` attributes, no inline `<script>`/`<style>`, no `http://` literal, no CDN; every DOM insertion through `toNodes`; the only `https://` constant is `AVATAR_PNG_PATTERN`'s base.
- The public avatar URL handed to the operator is `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/<name>.png`; the page renders icons from `/admin/static/avatars/<name>.png`.
- Commit after each task on branch `feat/CG-92-admin-console-ux`; messages end with the attribution lines in this session's reminder.

## Review Focus

1. A deep link to an unknown app or identity (`#/app/nope`) must render a "not found" view with a Board link, never a blank page or a thrown error in the console. Pinned in Task 6 (P1).
2. Filter text containing regex metacharacters (`trader.*`, `(`) must be treated as a plain substring. Pinned in Task 7 (P2).
3. `avatar: Alert` (wrong case) must refuse at load and at write; never lower-cased into `alert`. Pinned in Task 3 (S3a).
4. A refusal body must omit `reasons` entirely when there are none (never `"reasons": null`), so the dialog never renders a literal "null" bullet. Pinned in Task 2 (S2).
5. An identity with `space` set but held by no app must appear in `rooms` with `posting_apps: []`, and a room whose only identities are unheld must still list them. Pinned in Task 1 (S1).

---

### Task 1 (S1): `state.rooms` and `state.apps[*].inbox_pending`

**Files:**
- Modify: `src/chat_gateway/admin.py` (module function near `_shape`/`locked_space_violations` ~`:166-201`; `state()` ~`:545-576`)
- Test: `tests/test_admin_api.py` (new section `# -- rooms ---`)

**Interfaces:**
- Produces: `rooms_for(reg: Registry) -> dict[str, dict]` — keys are space ids ascending with `""` last; each value `{"identities": [name…] (name order), "posting_apps": [app_id…] (sorted), "inbound_apps": [app_id…] (= reg.apps_for_space(space) filtered by allow_inbound; [] for ""), "locked_by": app_id | None}` where `locked_by` is the first `inbound_locked` app (sorted by id) holding an identity homed there — the same `setdefault` order `locked_space_violations` uses. `state()` adds `"rooms": rooms_for(reg)` and, per app, `"inbox_pending": inbox.pending_counts().get(app_id, 0) if inbox is not None else 0`.

- [ ] **Step 1: Write the failing tests** — a fixture registry `ROOMS_TEXT` with: identities `i1` (space `spaces/A`), `i2` (space `spaces/A`), `il` (space `spaces/LOCKED`), `i0` (no space), `iu` (space `spaces/U`, held by nobody); apps `a1` (inbound true, `[i1]`), `a2` (inbound false, `[i1, i2]`), `locked` (inbound false, locked, `[il]`). Assert: `rooms` keys == `["spaces/A", "spaces/LOCKED", "spaces/U", ""]`; `rooms["spaces/A"] == {"identities": ["i1","i2"], "posting_apps": ["a1","a2"], "inbound_apps": ["a1"], "locked_by": None}`; `rooms["spaces/LOCKED"]["locked_by"] == "locked"`; `rooms["spaces/U"] == {"identities": ["iu"], "posting_apps": [], "inbound_apps": [], "locked_by": None}`; `rooms[""]["identities"] == ["i0"]`, `inbound_apps == []`, `locked_by is None`. A second test asserts `locked_by` for every room equals the `locked` map a reimplementation of `locked_space_violations`'s first loop derives from `_shape(reg)`, and `inbound_apps` equals `[a for a in reg.apps_for_space(s) if reg.apps[a].allow_inbound]` for every non-empty room. A third: `inbox_pending` is `0` for every app with no inbox wired, and equals `Inbox.pending_counts()[app]` after `inbox.put(...)` for an inbound app (use the existing `Inbox` fixture pattern from the delete-refusal test).
- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_admin_api.py -q -k rooms -p no:cacheprovider` → FAIL with `KeyError: 'rooms'`.
- [ ] **Step 3: Implement** `rooms_for` as a pure module function using `reg.identities`, `reg.apps`, `reg.apps_for_space`; wire `state()`. Do not touch `locked_space_violations`.
- [ ] **Step 4: Run the admin suite** — `tests/test_admin_api.py tests/test_admin_page.py` → PASS; every pre-existing test unchanged.
- [ ] **Step 5: Commit** — `feat(CG-92): state() publishes rooms and inbox_pending, derived with the enforcement's own rules`

---

### Task 2 (S2): `category` and `reasons` on refusal bodies

**Files:**
- Modify: `src/chat_gateway/registry_store.py:40-60` (`_DEFAULT_CATEGORY`, `StoreError`), `src/chat_gateway/admin.py` (`refuse` `:363`, `run` `:369`, `managed_name` `:382`, `guard_inbound` `:440`, `delete_identity` `:798`, `replace_webhook` `:746`), `src/chat_gateway/service.py:280-300, :493-500` (handler registration)
- Test: `tests/test_admin_api.py` (new section `# -- refusal bodies ---`), `tests/test_error_surfaces.py` (one enumeration test)

**Interfaces:**
- Produces: `class AdminRefusal(HTTPException)` in `admin.py` with `category: str` and `reasons: list[str] | None`; `StoreError.__init__(status, message, category=None, reasons=None)`; `CATEGORIES: tuple[str, ...]` in `registry_store.py` = the five `_DEFAULT_CATEGORY` values plus every explicitly named category in the store and router (including the two new ones `refused: still granted`, `refused: secret in process env`); `_admin_refusal_handler` in `service.py` registered with `app.add_exception_handler(AdminRefusal, …)` beside the validation handler, returning `{"detail": …, "category": …}` plus `"reasons": […]` only when `reasons` is a non-empty list. `refuse()` returns `AdminRefusal(status, message, category or category_for(status))`; `run()` re-raises `StoreError` as `AdminRefusal(exc.status, str(exc), exc.category or category_for(exc.status), exc.reasons)`. `delete_identity`'s still-granted 409 uses `refused: still granted`; `managed_name`'s 409 uses `refused: secret in process env`. `guard_inbound`'s 428 passes its reasons list; `replace_webhook`'s 428 passes `movers`. 401 and 429 stay plain `HTTPException` with no category.

- [ ] **Step 1: Write the failing tests** — (a) a 409 from `delete_identity` while granted has `category == "refused: still granted"` and no `reasons` key; (b) a create with `allow_inbound: true` and no confirm → 428 with `category == "refused: confirmation required"` and `reasons == ["allow_inbound"]` (match `widening()`'s actual strings — read it); (c) a webhook move on an inbound holder → 428 whose `reasons` lists the moving app ids; (d) a delete-app 428 has `"reasons" not in body`; (e) an out-of-band sha 409 has the category the store already uses for it (read `registry_store.py`; assert that exact string and that it differs from the still-granted one); (f) 401 and 429 bodies have no `category`; (g) `/healthz` `admin.last_write_error` after (a) equals `"refused: still granted"`; (h) in `test_error_surfaces.py`, an `ast` walk over `admin.py` finds every `refuse(` call and every `StoreError(` construction with a status of 403/409/422/428 and asserts each one's resulting category is in `CATEGORIES` (for `refuse(status, msg)` with no third arg the category is `category_for(status)`), and that no category string contains an f-string interpolation.
- [ ] **Step 2: Run to verify they fail** — `-k "refusal_bodies or categor"` → FAIL (`KeyError: 'category'`).
- [ ] **Step 3: Implement** per the Interfaces block. The handler lives in `service.py` because that is where the validation handler lives; keep `_admin_safe_validation_handler` untouched.
- [ ] **Step 4: Run the full suite** → PASS; confirm `test_admin_api.py`'s existing `detail` assertions (strings) still hold because `detail` is unchanged.
- [ ] **Step 5: Commit** — `feat(CG-92): refusals carry a fixed category, and the two list-bearing 428s carry reasons`

---

### Task 3 (S3a): `avatar` in the registry, the packaged icons, and the drift guard

**Files:**
- Modify: `src/chat_gateway/registry.py:135-158` (`Identity`), `:334-357` (loader), `assets/avatars/build.py:22-30`, `pyproject.toml:30-31`, `assets/avatars/README.md`, `config/registry.example.yaml` (one identity)
- Create: `src/chat_gateway/static/admin/avatars/*.png` (generated — run `build.py`, or copy the twenty from `assets/avatars/png/` if the generator needs tools this machine lacks; say which in the report), `tests/test_avatars.py`
- Test: `tests/test_avatars.py`, `tests/test_admin_registry.py`

**Interfaces:**
- Produces in `registry.py`: `AVATAR_DIR = Path(__file__).parent / "static" / "admin" / "avatars"`; `AVATAR_NAMES: tuple[str, ...] = tuple(sorted(p.stem for p in AVATAR_DIR.glob("*.png")))`; `AVATAR_RAW_BASE = "https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/"`; `normalize_avatar(raw) -> str | None` — `None`/`""` → `None`; a `str` in `AVATAR_NAMES` → itself; a `str` equal to `AVATAR_RAW_BASE + name + ".png"` for a bundled `name` → `name`; any other `str` starting with `https://` → itself; anything else → `ValueError` (message names the rule: "a bundled icon name or an https URL"); `Identity.avatar: str | None = None`; the loader sets `avatar=` via `normalize_avatar`, wrapping `ValueError` in `RegistryError(f"identity {name!r}: avatar must be a bundled icon name or an https URL")`.
- Produces in `build.py`: `PKG_PNG_DIR = HERE.parents[1] / "src" / "chat_gateway" / "static" / "admin" / "avatars"`; every PNG is written to both `PNG_DIR` and `PKG_PNG_DIR`.
- `pyproject.toml` package-data: `chat_gateway = ["static/admin/*", "static/admin/avatars/*"]`.

- [ ] **Step 1: Write the failing tests** — `tests/test_avatars.py`: (a) `AVATAR_NAMES` has 20 entries and includes `"alert"`, `"home"`, `"phone"`; (b) `sorted(p.name for p in Path("assets/avatars/png").glob("*.png")) == sorted(p.name for p in AVATAR_DIR.glob("*.png"))` and each pair is byte-identical (`read_bytes()`); (c) `normalize_avatar` table: `None→None`, `""→None`, `"alert"→"alert"`, `AVATAR_RAW_BASE+"alert.png"→"alert"`, `"https://x.example/a.png"→"https://x.example/a.png"`; raises for `"Alert"`, `"http://x.example/a.png"`, `"../alert"`, `"alert.png"`, `42`. `tests/test_admin_registry.py`: a registry with `avatar: phone` loads with `identities["x"].avatar == "phone"`; `avatar: Phone` raises `RegistryError` naming the identity; absent → `None`; `avatar` on a `mode: app` identity is accepted.
- [ ] **Step 2: Run to verify they fail** — `tests/test_avatars.py tests/test_admin_registry.py -q` → FAIL (`ImportError: AVATAR_NAMES`).
- [ ] **Step 3: Implement** the registry side; update `build.py` and regenerate (or copy) so `PKG_PNG_DIR` holds the twenty files; update `pyproject.toml`; add one `avatar: home` line with the rule comment to `pm-familyworkspace` in `config/registry.example.yaml`; one paragraph in `assets/avatars/README.md` naming the second output and the drift test.
- [ ] **Step 4: Run** `tests/test_avatars.py tests/test_admin_registry.py tests/test_core.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(CG-92): identities may record an avatar — bundled name or https URL — and the icons ship in the package`

---

### Task 4 (S3b): avatars over the admin API, and the icon route

**Files:**
- Modify: `src/chat_gateway/admin.py` (`IdentityCreate` `:283`, `DisplayIn` `:289` → `IdentityUpdate`, static route `:537-542`, `state()`, `create_identity` `:694`, `update_identity` `:731`), `scripts/admin_uat_server.py:33-46` (fixture registry)
- Test: `tests/test_admin_api.py` (new section `# -- avatars ---`), `tests/test_admin_page.py` (route test)

**Interfaces:**
- Produces: `IdentityCreate.avatar: str = ""`; `class IdentityUpdate(_Guarded): display: str | None = None; avatar: str | None = None` (`display` absent = unchanged, `""` → 422 "display is required"; `avatar` absent = unchanged, `""` = clear, else validated through `normalize_avatar` → 422 naming the field on `ValueError`); `state()["avatars"] = list(AVATAR_NAMES)` and `state()["identities"][name]["avatar"]`; `GET /admin/static/avatars/{name}.png` serves `AVATAR_DIR / f"{name}.png"` with `media_type="image/png"` and `page_headers` only when `name in AVATAR_NAMES`, else 404 — the name is matched, never joined onto a path. Audit field name `avatar` on create (when set) and update. The UAT fixture registry grows to the mockup's shape: six apps (`agent-mcp`, `aiteam-harness`, `aitrader` locked with two identities in two rooms, `job-hunter` inbound, `pmtrader` sharing `pm-familyworkspace`, `rotaryphone`), identities with avatars, one identity with no space, one unused; env values for every key/webhook env name the fixture names (fake `https://chat.googleapis.com/...` URLs are fine; they are never shown).

- [ ] **Step 1: Write the failing tests** — create with `avatar: "phone"` → 201 and `state` shows it; create with `avatar: "Phone"` → 422 whose `detail` names `avatar` and does not echo a URL; `PUT` with `{"avatar": "https://x.example/a.png"}` → stored, `display` unchanged; `PUT` with `{"avatar": ""}` → `None`; `PUT` with `{"display": "New"}` leaves `avatar` as it was; `PUT` with `{"avatar": AVATAR_RAW_BASE + "alert.png"}` stores `"alert"`; `GET /admin/static/avatars/alert.png` → 200 `image/png`; `GET /admin/static/avatars/nope.png` and `/admin/static/avatars/..%2Fadmin.py` → 404; `state()["avatars"] == list(AVATAR_NAMES)`; audit line for the update lists `"avatar"` in `fields`.
- [ ] **Step 2: Run to verify they fail** — `-k avatars` → FAIL.
- [ ] **Step 3: Implement**; keep the existing `update_identity` display path's behaviour. Extend the UAT fixture; run `GATEWAY_ADMIN_AUTH=open .venv/bin/python scripts/admin_uat_server.py` for five seconds to see it boot with the new registry (loader must accept it).
- [ ] **Step 4: Run the full suite** → PASS.
- [ ] **Step 5: Commit** — `feat(CG-92): avatar over the admin API, bundled icons served same-origin, UAT fixture at the mockup's shape`

---

### Task 5 (P0): CSS tokens and primitives

**Files:**
- Modify: `src/chat_gateway/static/admin/admin.css`
- Test: `tests/test_admin_page.py`

**Interfaces:**
- Produces the §6 tokens in both schemes — `--panel` (`#f1f1f1` / `#1b1b1b`), `--locked-bg`, `--accent-soft` — and classes `.dot`, `.avatar` (+ size modifiers `.s16`, `.s20`, `.s40`), `.matrix` (sticky first column and header rows, `.matrix-wrap` with `overflow:auto; max-height: calc(100vh - 250px); min-height: 260px`), `.chip`, `.callout`, `dialog` (+ `::backdrop`), `.skeleton`, `.notice`/`.notices`, `.savebar`, `.locked` (opaque composed colour for sticky cells), `.cards` (≤ 720 px), `::selection` themed on `--accent`. `[hidden] { display:none !important; }` stays first.

- [ ] **Step 1: Write the failing test** — `test_css_defines_the_cg92_tokens_in_both_schemes`: `--panel:`, `--locked-bg:`, `--accent-soft:` each appear twice (light and dark); `.matrix-wrap`, `dialog::backdrop`, `.avatar.s40`, `@media (max-width: 720px)` present; the `[hidden]` rule still present.
- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Implement** in `admin.css`, keeping every existing rule; no color literal outside `:root` blocks except the composed locked colour.
- [ ] **Step 4: Run** `tests/test_admin_page.py` → PASS.
- [ ] **Step 5: Commit** — `feat(CG-92): tokens and primitives for the matrix, dialog, notices and avatars`

---

### Task 6 (P1): Shell, router, notices, dialog, refusal plumbing

**Files:**
- Modify: `src/chat_gateway/static/admin/index.html`, `admin.js` (shell and plumbing; existing views re-homed under routes without redesign yet)
- Test: `tests/test_admin_page.py`

**Interfaces:**
- `index.html`: header (`<h1>`, `#sha`, `#counts`, `#auth-mode` pill unchanged), `<nav>` with buttons `#nav-board`, `#nav-new-app`, `#nav-new-identity`, filter `<input id="filter">`, `<details id="registry-menu">` with buttons `#menu-refresh`, `#menu-reload`, `#menu-shortcuts`; `#banners`, `#crumbs`, `#view`, `<div id="notices">`, `<dialog id="confirm">` and `<dialog id="shortcuts">`; `#login` unchanged from CG-91.
- `admin.js` produces: `routeFromHash() -> {name, params}` for the eight routes in spec §4.1; `navigate(hash)`; `render()` dispatching to `board`, `appInspector`, `identityInspector`, `roomInspector`, `newApp`, `newIdentity`, `replaceWebhook`, `revealView`, and `notFound(kind, id)`; `guardNavigation(fn)` that consults a module-level `dirty` flag and opens the discard dialog; `notify(msg, {kind: "status"|"alert"})` (status auto-dismisses after 6000 ms); `typedConfirm({title, intro, reasons, expected, verb, tone}) -> Promise<string|null>` on `<dialog id="confirm">` with the verb button disabled until the input equals `expected`, Escape → `null`, focus returned to the trigger; `explain(e)` keyed by `e.category` first then status; `api()` attaches `e.category` and `e.reasons` from the body; the CG-91 probe resumes the hash it was opened on. Keyboard: `/` focuses filter, `Escape` → board (or dialog cancel), `?` opens shortcuts. Views not yet redesigned (board, app, newApp, newIdentity, replace, reveal) keep their current rendering, called through the router.

- [ ] **Step 1: Write the failing tests** — string tests: `routeFromHash(` and the eight route literals present; `typedConfirm(` uses `showModal()` and `"disabled"` toggling; `function notify(`; `e.category` read in `api()`; the six CG-91 invariants still present; no `localStorage|sessionStorage|document.cookie|indexedDB|innerHTML|style=`; `id="confirm"` and `id="shortcuts"` dialogs in `index.html`; `notFound(` exists and `#/app/` with an unknown id routes to it (string: `state.apps[params.id] || notFound(`).
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement**; keep `el`/`toNodes`/`api`/`write`/`refresh`/`signOut`/`probePosture` as they are except the additions named. Replace the old `typedConfirm` (card) with the dialog version; `withInboundConfirm` passes `reasons` through.
- [ ] **Step 4: Run** `tests/test_admin_page.py` → PASS; load the page against the UAT server in open mode and confirm every route renders without console errors (describe what you saw in the report).
- [ ] **Step 5: Commit** — `feat(CG-92): hash router, notice stack, dialog confirmations, category-aware refusals`

---

### Task 7 (P2): The board — grant matrix with bounded region and collapsible rooms

**Files:**
- Modify: `src/chat_gateway/static/admin/admin.js` (`board()` and helpers)
- Test: `tests/test_admin_page.py`

**Interfaces:**
- Produces: `board()` rendering `<table class="matrix">` inside `.matrix-wrap` per spec §4.2 from `state.rooms`; `expanded: Set<string>` and `selectedApp: string|null` as page variables; `toggleRoom(space)`, `expandAll()`, `collapseAll()`; tools row with `#expand-all`, `#collapse-all` and the count line; `applyFilter(text)` as plain substring (lower-cased `includes`, never `RegExp`) over app id, identity name, display, room id, reporting `"N of M apps · N of M identities match 'x'"`; roving tabindex per §4.7 (`Space` toggles on a room header, `Enter` opens or expands); `avatarMark(value, size)` returning an `<img class="avatar sN" src="/admin/static/avatars/<name>.png" alt="">` for a bundled name or a dashed-circle `<svg>` with `title` otherwise; `relTime(iso)`; phone cards under `.cards`; legend; empty/loading/error states from §4.6.

- [ ] **Step 1: Write the failing tests** — strings: `class: "matrix"`, `.matrix-wrap`, `scope="colgroup"`, `aria-expanded`, `expandAll(`/`collapseAll(`, `"any identity here"`, the caption text, `avatarMark(`, `/admin/static/avatars/`, `.toLowerCase().includes(` in the filter and no `new RegExp(` in the file; no `img` with an `https://` `src`; `test_the_admin_key_is_never_persisted_by_the_page` and the avatar-gallery test updated so the raw-URL constant is permitted only as `AVATAR_PNG_PATTERN`.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** per spec §4.2 and §4.7; default all rooms collapsed; opening an app inspector (Task 8) will add its rooms to `expanded` — expose `expandRoomsOf(appId)` now.
- [ ] **Step 4: Run** the page suite → PASS; manual check in the UAT server: scrollbar visible without page scroll on a 1366×768 viewport, sticky column and headers, Space/Enter behaviour (report).
- [ ] **Step 5: Commit** — `feat(CG-92): the grant matrix — rooms as column groups, collapsed by default, in a bounded scroll region`

---

### Task 8 (P3): App inspector

**Files:**
- Modify: `src/chat_gateway/static/admin/admin.js` (`appInspector(id)` replacing `appDetail`, reusing `appFields`/`readAppFields` logic)
- Test: `tests/test_admin_page.py`

**Interfaces:**
- Produces: `appInspector(id)` per spec §4.3 — header, API key card (Rotate/Mint disabled with reason when `key_source === "process"`, shadowed callout), *Sends as* grouped by `state.rooms` with the three dynamic notes and `holders(name)`, routes selects listing granted identities only with the computed CG-86 line, inbound fieldset with the derived "receives from" line, recent deliveries table, danger zone (Delete disabled with reason when locked or `inbox_pending > 0`); sticky save bar with `dirty` tracking (`setDirty(bool)`), Discard, Save → existing `write("PUT", …)` with `withInboundConfirm`; `?ungrant=<name>` query handled on entry; on entry `selectedApp = id` and `expandRoomsOf(id)`.

- [ ] **Step 1: Write the failing tests** — strings: `function appInspector(`, `"Unsaved changes"`, `"No changes"`, `inbox_pending`, `key_source === "process"`, the CG-86 sentence fragment `"an all-clear will land in a different room"`, `"Receives inbound from:"`, `ungrant`, `setDirty(`; `readAppFields` ordered-identities rule retained (`a.identities.slice()`).
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement**; the PUT body is unchanged from today.
- [ ] **Step 4: Run** the page suite → PASS; manual check against the UAT server: unchecking a route target shows the routes note; Save on a widening opens the dialog with bullets; locked app read-only (report).
- [ ] **Step 5: Commit** — `feat(CG-92): app inspector — grants by room with consequences before Save`

---

### Task 9 (P4): Identity and room inspectors, replace-webhook flow

**Files:**
- Modify: `src/chat_gateway/static/admin/admin.js`
- Test: `tests/test_admin_page.py`

**Interfaces:**
- Produces: `identityInspector(name)` per §4.4 (header with avatar mark at 20 px, status line by mode/source, inline Rename, Avatar card with `Change avatar…` → `avatarPicker({value, onChange})` + Save avatar/Cancel → `write("PUT", "/admin/api/identities/<name>", {avatar})`, Held by with `Remove grant…` → `#/app/<id>?ungrant=<name>`, siblings, Actions with disabled reasons, Delete enabled only when unheld); `roomInspector(space)` per §4.5; `replaceWebhook(name)` per §4.6 with the Consequences card computed from `state.rooms` and the recorded avatar's public URL as `code`; `avatarPicker` renders `state.avatars` as `aria-pressed` 40 px tiles plus *none*, a custom `https://` field (client-side check: must start with `https://`), and the read-only URL box filled from `AVATAR_PNG_PATTERN` with **Select URL**.

- [ ] **Step 1: Write the failing tests** — strings: `function identityInspector(`, `function roomInspector(`, `function avatarPicker(`, `aria-pressed`, `"Recorded: bundled icon"`, `"Remove it from"`, `"Select URL"`, `AVATAR_PNG_PATTERN.replace(` (or equivalent build from the constant), `startsWith("https://")`; the raw-URL constant appears exactly once as a literal.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the page suite → PASS; manual check: Change avatar round-trips through `state`; Delete disabled while held; Remove grant lands on the app with the box unchecked (report).
- [ ] **Step 5: Commit** — `feat(CG-92): identity and room inspectors, avatar card and picker, replace-webhook with consequences`

---

### Task 10 (P5): New app, new identity stepper, reveal, discard guard, states

**Files:**
- Modify: `src/chat_gateway/static/admin/admin.js`, `index.html` if a container is missing
- Test: `tests/test_admin_page.py`

**Interfaces:**
- Produces: `newApp()` with an in-memory `draft` and the `#/new-identity?return=new-app` ticket; `newIdentity()` three-step stepper with the picker first and `avatar` in the POST body, result card with `Back to new app (pre-granted)` when a ticket exists; `revealView()` from the stored result with `Select key`, `Copy — selects on HTTP` labelled by `window.isSecureContext`, snippets in `<details>`, `Done — I have stored the key`; the discard guard wired to Escape, `/`, filter typing, nav, breadcrumb and `hashchange` (re-push current route, ask, then proceed); loading skeleton, empty states, error-on-load with Retry.

- [ ] **Step 1: Write the failing tests** — strings: `?return=new-app`, `"Discard the unsaved new app?"`, `"Discard unsaved changes?"`, `"Back to new app (pre-granted)"`, `window.isSecureContext`, `"Done — I have stored the key"`, `aria-busy="true"`, `"Nothing registered yet."`, `hashchange`; `write(` still contains exactly one `await refresh()` inside `try` (existing test).
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full suite → PASS; manual: new app → create identity → back pre-checked → create → reveal → test send (report).
- [ ] **Step 5: Commit** — `feat(CG-92): new-app draft with return ticket, identity stepper with avatar picker, reveal and discard guard`

---

### Task 11 (D): Documentation

**Files:**
- Modify: `docs/registering-an-app.md` (the console section; §1 identity row's gallery sentence), `docs/integration-guide.md` (if it documents `/admin/api/state`; else annotate), `docs/superpowers/specs/2026-10-15-admin-console-design.md` §6 (dated annotation), `docs/deploy/nas.md` (CG-90 subsection: UI changed, nothing about mounts/flags/secrets did; `registry.yaml` may now carry `avatar:`), `docs/consumers/pmtrader-registration-handoff.md` §3 (`avatar` row), `docs/design-handoffs/admin-console-ux/overview.md` (dated line pointing at the spec), `CLAUDE.md` (one status bullet; re-measure the Layout count line for this machine)

- [ ] **Step 1** each site per spec §10, in the house style (dated annotations, pointers not restatement, no IP literal).
- [ ] **Step 2** `.venv/bin/python -m pytest tests/test_fixtures_scrubbed.py tests/test_admin_page.py -q -p no:cacheprovider` → PASS.
- [ ] **Step 3: Commit** — `docs(CG-92): console redesign — runbook, schema row, spec annotations, status bullet`

---

### Task 12 (V): Verification

- [ ] **Step 1: Mutations, each alone, `__pycache__` cleared** — (1) drop the `allow_inbound` filter in `rooms_for` → Task 1 tests RED; (2) make `normalize_avatar` lower-case its input → `"Alert"` test RED; (3) remove `reasons` from the create 428 → Task 2 test RED; (4) make the avatar route join `name` onto the path without the list check → traversal test RED. Revert each; record in the PR.
- [ ] **Step 2: Full suite** → PASS; note the count and write it into spec §9's blank.
- [ ] **Step 3: Browser UAT** — tester agent, both postures, the eleven steps of spec §9 against `scripts/admin_uat_server.py`; punch-list into the PR.
- [ ] **Step 4: PR** against `main` per finishing-a-development-branch; body lists decisions D1–D6, rulings, mutation results, UAT; attribution lines.
