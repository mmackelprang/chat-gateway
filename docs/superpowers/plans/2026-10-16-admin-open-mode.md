# Admin Console Open Mode (CG-91) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An operator-chosen `GATEWAY_ADMIN_AUTH=open` posture under which `/admin` asks for no credential, with a same-origin guard, an honest `/healthz` field, and audit lines that say what authenticated each action.

**Architecture:** The posture is read from the process environment at boot beside `GATEWAY_ENABLE_ADMIN`, validated once, and carried on `AdminWiring.auth`. `require_admin` keeps every answer `no-store`, runs a header-based cross-origin check in both postures, skips the bearer comparison in `open`, stops counting header-less requests toward the limiter in `key`, and returns the peer address so write routes can pass it to the audit. The page probes the state endpoint with no key and shows the login only on a 401.

**Tech Stack:** Python 3.10+, FastAPI, pytest (offline), vanilla JS/CSS under a strict CSP. Run tests with `.venv/bin/python -m pytest -q` (WSL) or `python -m pytest -q` (Windows dev box).

**Spec:** `docs/superpowers/specs/2026-10-16-admin-open-mode-design.md`

## Global Constraints

- Env-var NAMES only in code and docs; never a value (hard rule #2). The new name is `GATEWAY_ADMIN_AUTH`; accepted values exactly `key` and `open`; default `key`; any other written value raises `RegistryError` (hard rule #7).
- The posture is read from the **process** environment only, before `managed.env` or `CHAT_GATEWAY_ENV_FILE` loads (`__main__.py:52`).
- No Google-facing code; nothing under `adapters/` changes; no ⚠ ledger flag moves (hard rule #3).
- Refusal messages name a header, never echo its value. Audit lines carry names, a posture string and a peer address — never a value or URL.
- The page stores nothing: `localStorage`, `sessionStorage`, `document.cookie`, `indexedDB`, `innerHTML` and `style=` stay absent from `static/admin/*` (existing tests pin this).
- Hard rule #6 guards are untouched: 428 typed confirmations and `inbound_locked` 403s behave identically in both postures.
- Commit after each task on branch `feat/CG-91-admin-open-mode`; commit messages end with the attribution lines in this session's reminder.

## Review Focus

1. `Origin: null` (a sandboxed iframe or a redirect-stripped origin) must be refused — its netloc is empty, which never equals `Host`. Pinned in Task 2.
2. `GATEWAY_ADMIN_AUTH=""` written as an empty value in the compose must mean `key`, not a refusal: an empty environment entry is how a template says "unset". Pinned in Task 1.
3. `GATEWAY_ADMIN_AUTH=Open` or `OPEN` must refuse to boot — never coerced — so a casing slip cannot silently open or silently lock. Pinned in Task 1.
4. In key mode the page's probe gets a 401 and must show the login with **no** error text; a wrong key typed afterwards must still show its error. Pinned in Task 6.
5. In open mode, `CHAT_GATEWAY_ADMIN_KEY` left set and equal to a tenant key must not 503: no admin key is in play, so rule #4's equality check is skipped. Pinned in Task 3.

---

### Task 1: Posture constants, parser, and the `auth` field on `AdminWiring`

**Files:**
- Modify: `src/chat_gateway/admin.py:35-43` (constants), `:174-188` (`AdminWiring`)
- Test: `tests/test_admin_api.py` (new section `# -- posture ---`)

**Interfaces:**
- Produces: `AUTH_ENV = "GATEWAY_ADMIN_AUTH"`, `AUTH_KEY = "key"`, `AUTH_OPEN = "open"`; `admin_auth_posture(raw: str | None) -> str`; `AdminWiring.auth: str = "key"` (dataclass field, last); `AdminWiring.health()` gains `"auth": self.auth`.

- [ ] **Step 1: Write the failing tests**

```python
from chat_gateway.admin import AUTH_KEY, AUTH_OPEN, admin_auth_posture
from chat_gateway.registry import RegistryError

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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_api.py -q -k posture -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'AUTH_KEY'`

- [ ] **Step 3: Implement**

In `admin.py` beside `RATE_LIMIT_*`: the three constants. `admin_auth_posture(raw)`: `None` or `""` → `AUTH_KEY`; `AUTH_KEY`/`AUTH_OPEN` → itself; otherwise `raise RegistryError(f"{AUTH_ENV}={raw!r} is not one of 'key', 'open' (CG-91; absence means 'key')")`. Import `RegistryError` from `.registry`. Add `auth: str = AUTH_KEY` as the last field of `AdminWiring` and `"auth": self.auth` to `health()`.

- [ ] **Step 4: Run the whole admin suite to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_admin_api.py tests/test_admin_page.py -q -p no:cacheprovider`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/chat_gateway/admin.py tests/test_admin_api.py
git commit -m "feat(CG-91): GATEWAY_ADMIN_AUTH posture — parsed once, never coerced, reported on /healthz"
```

---

### Task 2: The cross-origin guard, in both postures

**Files:**
- Modify: `src/chat_gateway/admin.py` (new module function; `require_admin` at `:273-301`)
- Test: `tests/test_admin_api.py` (new section `# -- cross-origin guard ---`)

**Interfaces:**
- Produces: `cross_origin_reason(headers: Mapping[str, str]) -> str | None` — `None` when accepted; otherwise an authored message naming the header: `"Sec-Fetch-Site is not same-origin"` or `"Origin does not match Host"`. `require_admin` raises `refuse(403, reason, "refused: cross-origin")` before any credential logic.

- [ ] **Step 1: Write the failing tests**

```python
from chat_gateway.admin import cross_origin_reason

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
    ({"origin": "http://gw.local:9000", "host": "gw.local:8085"}, "Origin"),
])
def test_guard_refuses_cross_origin_evidence_and_never_echoes_it(headers, word):
    reason = cross_origin_reason(headers)
    assert word in reason and "evil" not in reason and "9000" not in reason

def test_key_mode_refuses_a_valid_bearer_from_a_foreign_origin(gw):
    client, holder, wiring, tmp = gw
    r = client.get("/admin/api/state", headers={**AUTH, "Origin": "http://evil.example"})
    assert r.status_code == 403 and "evil" not in r.text
    assert client.get("/healthz").json()["admin"]["last_write_error"] == "refused: cross-origin"
    r = client.post("/admin/api/reload", headers={**AUTH, "Sec-Fetch-Site": "cross-site"}, json={})
    assert r.status_code == 403
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_api.py -q -k "guard or foreign_origin" -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'cross_origin_reason'`

- [ ] **Step 3: Implement**

`cross_origin_reason` as a pure module-level function: read `sec-fetch-site` lowercased, refuse unless absent or in `{"same-origin", "none"}`; read `origin`, and if present compare `urlparse(origin).netloc.lower()` to `headers.get("host", "").lower()` (`Origin: null` parses to an empty netloc and fails the comparison). In `require_admin`, call it with `request.headers` right after setting `Cache-Control` and before `limiter.check`; on a reason, `raise refuse(403, reason, "refused: cross-origin")`. `refuse` is defined later in the same closure; that is fine at call time.

- [ ] **Step 4: Run the admin suite to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_admin_api.py tests/test_admin_page.py -q -p no:cacheprovider`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/chat_gateway/admin.py tests/test_admin_api.py
git commit -m "feat(CG-91): same-origin guard on every /admin/api request, both postures"
```

---

### Task 3: `require_admin` honours the posture and returns the peer

**Files:**
- Modify: `src/chat_gateway/admin.py:273-301`
- Test: `tests/test_admin_api.py` (`_build` gains `auth`; new fixture `gw_open`; new section `# -- open mode ---`)

**Interfaces:**
- Consumes: `AdminWiring.auth`, `cross_origin_reason` (Tasks 1–2).
- Produces: `require_admin(...) -> str` returning `request.client.host` (or `"?"`). Open mode: no bearer read, no limiter, no rule-#4 equality check. Key mode: a request with no `Bearer` credential → `401` **without** `limiter.fail`; a presented-but-wrong one still counts.

- [ ] **Step 1: Extend the fixture and write the failing tests**

`_build(tmp_path, monkeypatch, adapter, auth="key")` passes `auth=auth` to `AdminWiring(...)` and `AdminAudit(..., auth=auth)` (the audit kwarg lands in Task 4; until then construct `AdminAudit(path)` and add the kwarg there). Fixture `gw_open` mirrors `gw` with `auth="open"` and **does not set** `CHAT_GATEWAY_ADMIN_KEY`.

```python
def test_open_mode_needs_no_credential(gw_open):
    client, *_ = gw_open
    assert client.get("/admin/api/state").status_code == 200
    assert client.get("/admin/api/state", headers={"Authorization": "Bearer wrong"}).status_code == 200
    assert client.get("/healthz").json()["admin"]["auth"] == "open"

def test_open_mode_skips_the_limiter_and_the_tenant_key_equality_check(gw_open, monkeypatch):
    client, *_ = gw_open
    monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", "cgk_tenant_one")  # equals ADM_K1
    codes = [client.get("/admin/api/state", headers={"Authorization": "Bearer wrong"}).status_code for _ in range(7)]
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_api.py -q -k "open_mode or header_less" -p no:cacheprovider`
Expected: the first three FAIL with `401`; the last FAILS with `429 != 200`

- [ ] **Step 3: Implement**

Reorder `require_admin`: `no-store` → origin guard → `host = ...` → `if wiring.auth == AUTH_OPEN: return host`. Key mode: `limiter.check(host)`; compute `presented`; `if not presented: raise HTTPException(401, "admin key required", headers={"WWW-Authenticate": "Bearer"})` with no `limiter.fail`; then the existing `not expected or not compare_digest` branch counts and raises; then the rule-#4 loop; `return host`. `wiring` must be in scope — `build_admin_router` already receives it as `wiring`.

- [ ] **Step 4: Run the admin suite to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_admin_api.py tests/test_admin_page.py -q -p no:cacheprovider`
Expected: all PASS, including `test_failed_logins_are_rate_limited` and `test_unset_admin_key_refuses_everything` unchanged

- [ ] **Step 5: Commit**

```bash
git add src/chat_gateway/admin.py tests/test_admin_api.py
git commit -m "feat(CG-91): open posture in require_admin; header-less requests no longer count as failed logins"
```

---

### Task 4: Audit lines carry `auth` and `client`

**Files:**
- Modify: `src/chat_gateway/admin_audit.py:18-35`; `src/chat_gateway/admin.py` write routes `:518-765` (nine routes: `create_app_entry`, `update_app_entry`, `rotate_key`, `delete_app_entry`, `create_identity`, `update_identity`, `replace_webhook`, `delete_identity`, `reload`)
- Test: `tests/test_admin_api.py`

**Interfaces:**
- Consumes: `require_admin -> str` (Task 3).
- Produces: `AdminAudit.__init__(self, path: Path, auth: str = "key")`; `AdminAudit.record(self, action: str, target: str, fields: list[str], *, client: str | None = None) -> None`; every line is `{"at", "actor": "admin", "auth", "client", "action", "target", "fields"}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_audit_lines_carry_posture_and_peer(gw, gw_open):
    for fixture, posture in ((gw, "key"), (gw_open, "open")):
        client, holder, wiring, tmp = fixture
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
```

Extend `test_state_carries_no_secret_values` (or the audit assertion at `:184-185`) so the minted key is absent from every audit line **including the new fields**.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_api.py -q -k "audit_lines_carry or every_write_route" -p no:cacheprovider`
Expected: FAIL with `KeyError: 'auth'`

- [ ] **Step 3: Implement**

`AdminAudit` stores `self.auth = auth` and writes `"auth": self.auth, "client": client` into the line. In `admin.py`, each of the nine write routes replaces `dependencies=[Depends(require_admin)]` with a parameter `client: str = Depends(require_admin)` and passes `client=client` on every `audit.record(...)` call in its body (`inbound_widened` lines included). `state()` keeps `dependencies=[...]`. `__main__` and `scripts/admin_uat_server.py` constructors are updated in Task 5.

- [ ] **Step 4: Run the admin suite to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_admin_api.py tests/test_admin_page.py -q -p no:cacheprovider`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/chat_gateway/admin.py src/chat_gateway/admin_audit.py tests/test_admin_api.py
git commit -m "feat(CG-91): audit lines record what authenticated the action and from where"
```

---

### Task 5: Boot wiring and the UAT server

**Files:**
- Modify: `src/chat_gateway/__main__.py:52` (read), `:128-160` (admin block); `scripts/admin_uat_server.py:47-56`
- Test: `tests/test_admin_api.py` (`# -- boot wiring ---` section, `:415-475`)

**Interfaces:**
- Consumes: `admin_auth_posture`, `AUTH_KEY`, `AUTH_OPEN`, `AdminWiring(auth=)`, `AdminAudit(auth=)`.
- Produces: `build_runtime()[6].auth` reflects the process env; open mode boots without `CHAT_GATEWAY_ADMIN_KEY` and prints one stderr line beginning `admin: WARNING — GATEWAY_ADMIN_AUTH=open`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

Also keep `test_admin_enabled_without_key_is_a_config_error` and add `monkeypatch.delenv("GATEWAY_ADMIN_AUTH", raising=False)` to `_boot_env` so a developer's shell cannot leak a posture into the suite.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_api.py -q -k "boots_without or env_file_is_ignored or unknown_posture" -p no:cacheprovider`
Expected: the first FAILS with `RegistryError` naming `CHAT_GATEWAY_ADMIN_KEY`; the second FAILS on `.auth`; the third FAILS with `0 != 2`

- [ ] **Step 3: Implement**

At `__main__.py:52`, beside `admin_enabled`: `admin_auth_raw = os.environ.get("GATEWAY_ADMIN_AUTH")` with a comment that this is the process env **by design** (spec §3). In the `if admin_enabled:` block, first `posture = admin_auth_posture(admin_auth_raw)` (its `RegistryError` already maps to exit 2); make the existing key check `if posture == AUTH_KEY and not os.environ.get(ADMIN_KEY_ENV):`; when `posture == AUTH_OPEN`, `print("admin: WARNING — GATEWAY_ADMIN_AUTH=open: /admin checks no credential; anything that can reach the port can use the console.", file=sys.stderr, flush=True)`; construct `AdminAudit(..., auth=posture)` and `AdminWiring(..., auth=posture)`. In `scripts/admin_uat_server.py`, read `posture = admin_auth_posture(os.environ.get("GATEWAY_ADMIN_AUTH"))`, pass it to both constructors, and print it on the final line (`admin auth: key — admin key: cgk_uat_admin` or `admin auth: open`).

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider`
Expected: all PASS (687 + the new tests)

- [ ] **Step 5: Commit**

```bash
git add src/chat_gateway/__main__.py scripts/admin_uat_server.py tests/test_admin_api.py
git commit -m "feat(CG-91): read GATEWAY_ADMIN_AUTH from the process env at boot; open mode needs no admin key"
```

---

### Task 6: The page — probe first, login only on 401, posture pill

**Files:**
- Modify: `src/chat_gateway/static/admin/index.html:11-21`, `admin.js:51-54` (`api`), `:464-486` (boot), `admin.css:31`
- Test: `tests/test_admin_page.py`

**Interfaces:**
- Consumes: `GET /admin/api/state` answering `200` without a header in open mode (Task 3).
- Produces: `async function probePosture()` in `admin.js`; `#login` starts `hidden`; `<span id="auth-mode" class="pill warn" hidden>open · no sign-in</span>` in `<header>`.

- [ ] **Step 1: Write the failing tests**

```python
def test_page_probes_before_showing_the_login():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    assert '<section id="login" hidden>' in html
    assert 'id="auth-mode" class="pill warn" hidden>open · no sign-in<' in html
    fn = js[js.index("async function probePosture("):]
    fn = fn[:fn.index("\n}\n")]
    assert "await refresh()" in fn and 'e.status === 401' in fn
    # a 401 shows the login silently; any other failure shows its message
    assert '$("login-error").textContent = ""' in fn or "login-error" in fn
    assert 'document.addEventListener("DOMContentLoaded"' in js and "probePosture()" in js

def test_api_sends_no_authorization_header_without_a_key():
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    fn = js[js.index("async function api("):]
    fn = fn[:fn.index("\n}\n")]
    assert 'Authorization: "Bearer " +' not in fn
    assert 'if (k) headers.Authorization = "Bearer " + k;' in fn
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_page.py -q -p no:cacheprovider`
Expected: the two new tests FAIL on the first assertion each

- [ ] **Step 3: Implement**

`index.html`: add `hidden` to `#login`; add the pill span after `#sha`. `admin.js` `api()`: `const headers = {}; const k = key || adminKey; if (k) headers.Authorization = "Bearer " + k;`. New `probePosture()`: `try { await refresh(); $("console").hidden = false; $("auth-mode").hidden = false; board(); } catch (e) { $("login").hidden = false; $("login-error").textContent = e.status === 401 ? "" : e.message; }`. Call it first inside the `DOMContentLoaded` handler. `signOut` additionally sets `$("auth-mode").hidden = true`. `admin.css`: add `.pill.warn { border-color:var(--warn); }`.

- [ ] **Step 4: Run the page suite, then exercise both postures by hand in a browser**

Run: `.venv/bin/python -m pytest tests/test_admin_page.py -q -p no:cacheprovider` — Expected: all PASS.
Run: `GATEWAY_ADMIN_AUTH=open .venv/bin/python scripts/admin_uat_server.py` and open `http://127.0.0.1:8099/admin` — Expected: the board renders with no login form and the pill shows. Then without the env var — Expected: the login form, no error text, and the printed key signs in.

- [ ] **Step 5: Commit**

```bash
git add src/chat_gateway/static/admin tests/test_admin_page.py
git commit -m "feat(CG-91): the page probes the API first and shows the login only on a 401"
```

---

### Task 7: Documentation

**Files:**
- Modify: `docs/deploy/nas.md` (§5 compose block `:257-267`; CG-90 subsection env-var table `:521-524`; rollout list `:619-629`), `docs/integration-guide.md:600-606`, `docs/registering-an-app.md:15`, `docs/superpowers/specs/2026-10-15-admin-console-design.md` (D2 row `:37`; §6 ¶1 `:165-167`), `CLAUDE.md` (status bullet after the CG-90 bullet; the Layout line's test count)

- [ ] **Step 1: nas.md** — compose block gains `"GATEWAY_ADMIN_AUTH": "open"` after `GATEWAY_ENABLE_ADMIN` with one sentence under the block: it is the target, merge changes nothing on the box. Env-var table gains the row: `GATEWAY_ADMIN_AUTH` · compose `environment:`, **not** `.env` · read before the env file like its sibling; set in `.env` it is silently ignored and the console stays in `key` mode (the safe direction); `open` means anything reaching the port can use the console — spec §2 states the accepted cost. Rollout list gains the attribution check (spec §7 step 4) and the optional key removal.
- [ ] **Step 2: integration-guide.md** — row `admin.auth`: `"key"` or `"open"`, what authenticates `/admin`; present whenever `enabled` is true; never degrades; verdict **no**. Update the "seven `admin.*`" count at `:520` to eight.
- [ ] **Step 3: registering-an-app.md:15** — *"(LAN port, admin key)"* → *"(LAN port; admin key, or none under `GATEWAY_ADMIN_AUTH=open` — CG-91)"*.
- [ ] **Step 4: CG-90 spec annotations** — after the D2 row: `⚠ *Annotated 2026-10-16 (CG-91): a third posture exists — \`GATEWAY_ADMIN_AUTH=open\`, no credential, LAN bind as the whole lock. User decision; the row above is left standing.*` After §6 ¶1: `⚠ *Annotated 2026-10-16 (CG-91): under open mode the page sends no \`Authorization\` at all; see that spec §4.*`
- [ ] **Step 5: CLAUDE.md** — one status bullet after the CG-90 bullet: open mode exists since CG-91 (date), user decision, cost recorded in the spec §2, flag read from the process env only, no hard rule changed, no ledger flag moved; design has one home (the spec). Re-measure the suite with `.venv/bin/python -m pytest -q` and update the Layout line's count with the date and machine.
- [ ] **Step 6: Run the scrub and page suites** — `.venv/bin/python -m pytest tests/test_fixtures_scrubbed.py tests/test_admin_page.py -q -p no:cacheprovider` — Expected: all PASS (no LAN literal introduced).
- [ ] **Step 7: Commit**

```bash
git add docs CLAUDE.md
git commit -m "docs(CG-91): open mode — runbook row and rollout, /healthz field, spec annotations, status bullet"
```

---

### Task 8: Verification — mutations, full suite, browser UAT

**Files:** none modified except reverting mutations.

- [ ] **Step 1: Single-site mutations (spec §9), each alone, `__pycache__` cleared between runs** — (1) make `cross_origin_reason` return `None` unconditionally → `test_guard_refuses_*` and `test_key_mode_refuses_a_valid_bearer_from_a_foreign_origin` RED; (2) change `admin_auth_posture`'s default branch to return `AUTH_OPEN` → `test_posture_defaults_to_key_when_absent_or_empty` RED; (3) make the parser `.lower()` its input → `test_posture_is_never_coerced["Open"]` RED. Revert each; record the three RED outcomes in the PR description.
- [ ] **Step 2: Full suite** — `.venv/bin/python -m pytest -q -p no:cacheprovider` — Expected: all PASS; note the count for the PR.
- [ ] **Step 3: Browser UAT** — dispatch the `tester` agent in browser mode against `scripts/admin_uat_server.py` in both postures: open → no login, pill visible, create-app → reveal → test-send round trip, *Reload from disk* works; key → login form with no error text, wrong key shows its error, correct key signs in. Pass/fail punch-list into the PR.
- [ ] **Step 4: Open the PR** against `main` per the finishing-a-development-branch skill, body ending with the attribution lines; list the scrub commit separately.
