# Admin Console (CG-90) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An operator console at `/admin` that registers, edits, rotates and removes apps and identities, and applies each change to the running gateway without a redeploy.

**Architecture:** A `RegistryHolder` replaces the boot-time `Registry` everywhere and delegates attribute access to an atomically swappable `.current`, so every existing consumer sees swaps without a signature change. A `RegistryStore` is the single writer of `registry.yaml` (ruamel round-trip, validate-by-real-loader, backup, atomic replace, swap). A `ManagedSecrets` file under the state dir holds page-minted secrets and is loaded before the hand-written `.env`. A FastAPI router behind a dedicated admin key serves the JSON API and a static page.

**Tech Stack:** Python ≥3.10, FastAPI, PyYAML (loader, unchanged), `ruamel.yaml>=0.18` (writer, new), vanilla HTML/JS/CSS (no build, no CDN), pytest + FastAPI `TestClient`, Playwright for UAT.

**Spec:** `docs/superpowers/specs/2026-10-15-admin-console-design.md` — read it before starting any task; this plan argues from it.

**Baseline:** `main` at `f9bcf65`, **527 passed, 6 skipped** (`python -m pytest -q`, Windows dev box). On POSIX use `python3 -m pytest`.

**Branch:** implementation goes on `feat/cg-90-admin-console`, cut from `main` after the spec branch merges. Never commit to `main`.

## Deviations from the spec, stated

1. **The holder delegates (`__getattr__`) instead of every consumer reading `holder.current` once per request.** The subagent map of the code (2026-10-15) found that no consumer captures anything finer than the `registry` reference itself: `create_app`'s routes, `build_mcp_router`, `SubscriberLoop` and `Dispatcher.restore` all hold the object and call methods on it. Passing a delegating holder in that slot makes every one of them observe a swap with **zero** consumer edits and leaves 78 test call sites that pass a plain `Registry` untouched. **What is given up:** a request that makes two registry calls may see two snapshots if a swap lands between them. Each `Registry` method is internally consistent and every lookup re-validates (`identity_for` raises on a withdrawn grant), so the worst case is the request failing as if it had arrived after the swap. Flagged for the user at handoff.
   ⚠ *Corrected 2026-10-15 (CG-90 final review I2a):* **"the worst case is the request failing" was FALSE for inbound dispatch.** `adapters/pubsub.py` `dispatch()` chose candidates from one snapshot and looked each app up in the next; a console delete in between made `app` `None`, which skipped the opt-out check and **put the event in the deleted, opted-out app's inbox** — a hard rule #6 breach, not a failure. Fixed by taking ONE snapshot at the top of `dispatch` (spec §3), with an app-less candidate now skipped rather than put; pinned in `tests/test_registry_holder.py`. Four HTTP handlers had already been found failing the same way (CG-90 C1, a 500 rather than a 401). The general claim stands only for call sites that have been checked; a new two-read site re-opens it.
2. **Spec §5's "the plan verifies whether the dispatcher re-checks grants at dispatch time" — it does not.** `Dispatcher.process_due` sends `job.identity` as resolved at enqueue (`delivery.py:366-370`); only `restore` re-checks (`:507`). Task 3 adds the re-check; without it a page-deleted app's queued and retrying jobs would still send.
3. **`build_runtime` returns a 7-tuple** (the admin wiring, `None` when disabled) so the managed secrets loaded before the hand env file reach `main`. The one test that fakes `build_runtime` (`tests/test_mcp.py:1341-1343`) is updated in Task 6.

## Global Constraints

- Hard rule #2: no secret value (API key, webhook URL) in any log line, audit line, error message, `/healthz` field or API response — except the single mint/rotate response that creates it.
- Hard rule #4: `CHAT_GATEWAY_ADMIN_KEY` is never an app's `key_env`; a tenant key is `401` on `/admin/api/*`; the admin key is `401` on tenant routes.
- Hard rule #7: every `allow_inbound` the console writes is a real YAML boolean; `inbound_locked` defaults to `false`, is refused if non-boolean, and the console never writes it.
- Env-var names: app key `CHAT_GATEWAY_API_KEY__<ID>`, webhook `GOOGLE_CHAT_WEBHOOK_URL__<NAME>`, where `<X>` is the id uppercased with `-` → `_`.
- Console-created ids match `^[a-z0-9][a-z0-9-]{0,62}$` (stricter than the loader; `_`-prefixed ids are therefore impossible).
- New env-var names: `GATEWAY_ENABLE_ADMIN` (`1` = on; default off), `CHAT_GATEWAY_ADMIN_KEY`.
- Files the console writes: `registry.yaml` (+ `registry.yaml.bak-<YYYYMMDD-HHMMSS>` UTC), `<state_dir>/managed.env` (`0600`), `<state_dir>/admin_audit.jsonl` (`0600`).
- No CDN, no inline script; CSP `default-src 'self'` on the page.
- No ⚠ verification-ledger flag in `CLAUDE.md` moves.
- Tests: `python -m pytest -q` (Windows) / `python3 -m pytest -q` (POSIX); offline only.

## Review Focus

1. **Windows line endings in `registry.yaml`.** The dev-box file may be CRLF; a console write must keep the file's newline style, or every save becomes a whole-file diff. → Task 5 `test_crlf_file_stays_crlf`.
2. **Two console tabs racing.** Tab A saves; tab B, loaded earlier, saves a different edit. Expected: B gets `409` and must reload, never a silent overwrite of A. → covered by the sha check; Task 5 `test_write_after_out_of_band_edit_is_409` and Task 6 `test_stale_second_writer_gets_409` (the router passes the client's `registry_sha256`).
3. **Pasting a webhook URL with whitespace or a trailing newline** (copied from the Chat UI). Expected: trimmed and accepted; and the URL never appears in an error. → Task 6 `test_webhook_url_is_trimmed_and_never_echoed`.
4. **Admin key accidentally equal to a tenant key** (operator pastes the wrong value). Expected: admin API refuses with `503` naming the colliding app, not silently granting a tenant admin. → Task 6 `test_admin_key_equal_to_a_tenant_key_is_refused`.
5. **Deleting an identity still referenced by an app or a route.** Expected: `409` naming the referencing apps, nothing written. → Task 6 `test_delete_referenced_identity_is_409`.

---

## File map

| File | Status | Responsibility |
|---|---|---|
| `src/chat_gateway/registry.py` | modify | `inbound_locked` field; reserve `CHAT_GATEWAY_ADMIN_KEY` |
| `src/chat_gateway/registry_holder.py` | create | `RegistryHolder` |
| `src/chat_gateway/delivery.py` | modify | dispatch-time grant re-check, `unroutable_live` |
| `src/chat_gateway/managed_secrets.py` | create | `ManagedSecrets` |
| `src/chat_gateway/registry_store.py` | create | `RegistryStore`, `StoreError` |
| `src/chat_gateway/admin_audit.py` | create | `AdminAudit` |
| `src/chat_gateway/admin.py` | create | `AdminWiring`, router, guards, helpers |
| `src/chat_gateway/static/admin/index.html`, `admin.js`, `admin.css` | create | the page |
| `src/chat_gateway/service.py` | modify | `admin=` kwarg, `/healthz` `admin` block, dispatcher gets registry |
| `src/chat_gateway/__main__.py` | modify | boot order, holder, admin wiring |
| `pyproject.toml` | modify | `ruamel.yaml>=0.18`, package data |
| `tests/test_admin_registry.py`, `test_registry_holder.py`, `test_dispatch_regrant.py`, `test_managed_secrets.py`, `test_registry_store.py`, `test_admin_api.py`, `test_admin_page.py` | create | tests |
| `tests/test_mcp.py` | modify (1 line block) | 7-tuple `build_runtime` fake |
| docs (Task 9), homelab repo (Task 10) | modify | |

---

### Task 1: Registry gains `inbound_locked` and reserves the admin key name

**Files:**
- Modify: `src/chat_gateway/registry.py` (constants near line 37; `App` near line 188; loader near lines 374-399)
- Test: `tests/test_admin_registry.py`

**Interfaces:**
- Produces: `registry.ADMIN_KEY_ENV: str = "CHAT_GATEWAY_ADMIN_KEY"`; `App.inbound_locked: bool` (default `False`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_admin_registry.py
"""CG-90 Task 1: `inbound_locked` and the reserved admin key name."""
import pytest

from chat_gateway.registry import ADMIN_KEY_ENV, RegistryError, load_registry

HEAD = """identities:
  i1:
    display: d
    webhook_url_env: W1
apps:
  a1:
    key_env: K1
    identities: [i1]
"""


def _load(tmp_path, extra=""):
    p = tmp_path / "r.yaml"
    p.write_text(HEAD + extra, encoding="utf-8")
    return load_registry(p)


def test_inbound_locked_defaults_to_false(tmp_path):
    assert _load(tmp_path).apps["a1"].inbound_locked is False


def test_inbound_locked_true_loads(tmp_path):
    assert _load(tmp_path, "    inbound_locked: true\n").apps["a1"].inbound_locked is True


def test_a_quoted_inbound_locked_is_refused_not_coerced(tmp_path):
    with pytest.raises(RegistryError, match="inbound_locked must be a YAML boolean"):
        _load(tmp_path, '    inbound_locked: "true"\n')


def test_no_app_may_use_the_admin_key_env(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(HEAD.replace("key_env: K1", f"key_env: {ADMIN_KEY_ENV}"), encoding="utf-8")
    with pytest.raises(RegistryError, match="reserved for the admin console"):
        load_registry(p)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_admin_registry.py -q`
Expected: FAIL — `ImportError: cannot import name 'ADMIN_KEY_ENV'`.

- [ ] **Step 3: Implement**

In `registry.py`, after `RESERVED_APP_ID_PREFIX = "_"` add:

```python
# CG-90, hard rule #4. The admin console's credential. Reserved so no tenant can
# be registered against it: `authenticate` would otherwise resolve the admin key
# to that tenant, and the console's "a tenant key is 401 here" would invert.
ADMIN_KEY_ENV = "CHAT_GATEWAY_ADMIN_KEY"
```

In `App`, after `unreachable_message`:

```python
    # CG-90 (spec §6.4). When true the admin console refuses every change that
    # WIDENS inbound for this app; only a hand edit of the file can. Default
    # false, never coerced (hard rule #7), and the console never writes it.
    inbound_locked: bool = False
```

In `load_registry`, immediately after the `if not spec.get("key_env"): raise ...` block:

```python
        if spec["key_env"] == ADMIN_KEY_ENV:
            raise RegistryError(
                f"app {app_id!r}: key_env {ADMIN_KEY_ENV} is reserved for the admin "
                "console — a tenant authenticating with the admin key would make the "
                "two credentials one (hard rule #4)"
            )
        raw_locked = spec.get("inbound_locked")
        inbound_locked = False
        if raw_locked is not None:
            _require_bool(app_id, "inbound_locked", raw_locked)
            inbound_locked = raw_locked
```

and pass `inbound_locked=inbound_locked,` in the `App(...)` constructor call after `allow_inbound=allow_inbound,`.

- [ ] **Step 4: Run to verify pass, then the full suite**

Run: `python -m pytest tests/test_admin_registry.py -q` → 4 passed.
Run: `python -m pytest -q` → 531 passed, 6 skipped.

- [ ] **Step 5: Commit**

```bash
git add src/chat_gateway/registry.py tests/test_admin_registry.py
git commit -m "feat(CG-90): registry gains inbound_locked and reserves the admin key name"
```

---

### Task 2: `RegistryHolder`, wired at boot

**Files:**
- Create: `src/chat_gateway/registry_holder.py`
- Modify: `src/chat_gateway/__main__.py:53` (wrap the loaded registry)
- Test: `tests/test_registry_holder.py`

**Interfaces:**
- Produces: `RegistryHolder(registry: Registry)`; `.current -> Registry`; `.swap(new: Registry) -> Registry` (returns the old one); any other public attribute delegates to `.current`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_registry_holder.py
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
```

The `SubscriberLoop` consumer is covered structurally by `build_runtime` passing the same `registry` object to it (`__main__.py:155`); `dispatch()` only calls `apps_for_space` and `apps.get`, both delegated. No `SubscriberLoop` test is added because the existing ones construct it with a plain `Registry` and the delegation is exercised above.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_registry_holder.py -q`
Expected: FAIL — `ModuleNotFoundError: chat_gateway.registry_holder`.

- [ ] **Step 3: Implement**

```python
# src/chat_gateway/registry_holder.py
"""The live registry, swappable at runtime (CG-90).

Every consumer — `create_app`'s routes, the MCP router, `SubscriberLoop`,
`Dispatcher` — was handed ONE `Registry` at boot and keeps that reference for
the life of the process. Passing this holder in its place makes all of them
observe a swap without a signature change: attribute access delegates to
`.current`, which `swap()` replaces with one reference assignment.

The cost, stated (plan deviation 1): a request that makes two registry calls
may see two snapshots if a swap lands between them. Each `Registry` method is
internally consistent and every lookup re-validates, so the worst case is the
request failing as if it had arrived after the swap.
"""

from __future__ import annotations

import threading

from .registry import Registry


class RegistryHolder:
    def __init__(self, registry: Registry):
        self._current = registry
        self._lock = threading.Lock()

    @property
    def current(self) -> Registry:
        return self._current

    def swap(self, new: Registry) -> Registry:
        """Replace the live registry. Returns the one it replaced."""
        with self._lock:
            old, self._current = self._current, new
        return old

    def __getattr__(self, name: str):
        # Only reached for names NOT found on the holder itself. Private and
        # dunder names are refused rather than delegated, so a half-built
        # instance (no `_current` yet) cannot recurse, and protocol probes
        # (`__deepcopy__`, `__len__`) do not silently answer for the Registry.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._current, name)
```

In `__main__.py`, add `from .registry_holder import RegistryHolder` to the imports and change line 53 to:

```python
    registry = RegistryHolder(
        load_registry(os.environ.get("CHAT_GATEWAY_REGISTRY", "config/registry.yaml")))
```

- [ ] **Step 4: Run to verify pass, then the full suite**

Run: `python -m pytest tests/test_registry_holder.py -q` → 6 passed.
Run: `python -m pytest -q` → 537 passed, 6 skipped.

- [ ] **Step 5: Mutation check (do not commit the mutation)**

Temporarily change `create_app`'s first line of body to `registry = getattr(registry, "current", registry)`. Clear caches: `find . -name __pycache__ -prune -exec rm -rf {} +` (POSIX) or `Get-ChildItem -Recurse -Directory __pycache__ | Remove-Item -Recurse -Force` (PowerShell). Run `python -m pytest tests/test_registry_holder.py -q` → `test_rest_routes_observe_a_swap` and `test_healthz_observes_a_swap` and `test_mcp_router_observes_a_swap` FAIL. Revert, clear caches again, re-run → 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/chat_gateway/registry_holder.py src/chat_gateway/__main__.py tests/test_registry_holder.py
git commit -m "feat(CG-90): RegistryHolder — every consumer observes a runtime registry swap"
```

---

### Task 3: The dispatcher re-checks the grant at send time

**Files:**
- Modify: `src/chat_gateway/delivery.py` (`Dispatcher.__init__` ~207-239; `process_due` ~364-370)
- Modify: `src/chat_gateway/service.py:292` (default dispatcher gets the registry) and the `/healthz` `delivery` block (~796)
- Modify: `src/chat_gateway/__main__.py:194-195` (dispatcher gets the registry)
- Test: `tests/test_dispatch_regrant.py`

**Interfaces:**
- Produces: `Dispatcher(..., registry=None)` keyword; `Dispatcher.unroutable_live: int`; `/healthz` `delivery.unroutable_live`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dispatch_regrant.py
"""CG-90 Task 3. A grant withdrawn while a job is queued closes the job as
`unroutable` instead of sending it on a stale permission (hard rule #4) — the
rule `restore` already applies at boot, now applied at every send."""
from chat_gateway.delivery import DeliveryLog, Dispatcher
from chat_gateway.envelope import OutboundMessage
from chat_gateway.registry import App, Identity, Registry
from chat_gateway.registry_holder import RegistryHolder


class _Rec:
    def __init__(self):
        self.sent = []

    def send(self, identity, message):
        self.sent.append(identity.name)
        return {"status": "delivered"}


def _registry(granted: bool) -> Registry:
    ident = Identity(name="i1", display="d", webhook_url_env="W")
    apps = {"a1": App(app_id="a1", key_env="K", identities=["i1"] if granted else [])}
    return Registry(identities={"i1": ident}, apps=apps)


def test_withdrawn_grant_closes_the_job_unroutable_and_does_not_send():
    holder = RegistryHolder(_registry(True))
    log, adapter = DeliveryLog(), _Rec()
    d = Dispatcher({"webhook": adapter}, log, registry=holder)
    d.enqueue("a1", "notify", holder.identity_for("a1", "i1"),
              OutboundMessage(identity="i1", text="hi"), "t")
    holder.swap(_registry(False))
    d.process_due()
    assert adapter.sent == []
    assert d.pending() == 0
    assert d.unroutable_live == 1
    assert log.query("a1")[-1]["status"] == "unroutable"


def test_a_still_granted_job_sends_as_before():
    holder = RegistryHolder(_registry(True))
    adapter = _Rec()
    d = Dispatcher({"webhook": adapter}, DeliveryLog(), registry=holder)
    d.enqueue("a1", "notify", holder.identity_for("a1", "i1"),
              OutboundMessage(identity="i1", text="hi"), "t")
    d.process_due()
    assert adapter.sent == ["i1"]
    assert d.unroutable_live == 0


def test_no_registry_keeps_the_old_behaviour():
    adapter = _Rec()
    d = Dispatcher({"webhook": adapter}, DeliveryLog())
    reg = _registry(True)
    d.enqueue("a1", "notify", reg.identity_for("a1", "i1"),
              OutboundMessage(identity="i1", text="hi"), "t")
    d.process_due()
    assert adapter.sent == ["i1"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_dispatch_regrant.py -q`
Expected: FAIL — `TypeError: Dispatcher.__init__() got an unexpected keyword argument 'registry'`.

- [ ] **Step 3: Implement**

In `Dispatcher.__init__` signature add `registry=None` after `replay_max_age_s`, and in the body after `self._replay_max_age_s = replay_max_age_s`:

```python
        # CG-90. When set, every send re-resolves the job's identity through
        # the LIVE registry, so a grant the admin console withdrew while the job
        # was queued closes it as `unroutable` — the rule `restore` applies at
        # boot (hard rule #4), applied at every send. None keeps the pre-CG-90
        # behaviour for every test that builds a bare Dispatcher.
        self._registry = registry
        #: Jobs closed `unroutable` at SEND time because the live registry no
        #: longer grants their identity. Never degrades /healthz: a withdrawn
        #: grant being honoured is the guard working (CG-12's test).
        self.unroutable_live = 0
```

In `process_due`, as the first statements inside `for job in due:` (before `attempted += 1`):

```python
            if self._registry is not None:
                try:
                    job.identity = self._registry.identity_for(job.source, job.identity.name)
                except RegistryError as exc:
                    self.unroutable_live += 1
                    self._finish(job, "unroutable", f"grant withdrawn while queued: {exc}")
                    continue
```

Add `from .registry import RegistryError` to `delivery.py`'s imports if absent.

In `service.py` line 292 change to `dispatch = dispatcher or Dispatcher(adapters, log, registry=registry)`, and in the `/healthz` `"delivery"` dict, after `"unroutable_at_boot": ...`, add:

```python
                         # CG-90. Send-time sibling of `unroutable_at_boot`: a
                         # queued job whose grant the admin console withdrew.
                         # NOT an input to `status` — a withdrawn grant being
                         # honoured is the guard working, not a fault (CG-12).
                         "unroutable_live": getattr(dispatch, "unroutable_live", 0),
```

In `__main__.py` lines 194-195:

```python
        dispatcher = Dispatcher(adapters, log,
                                journal=Journal(queue_dir / "delivery.jsonl"),
                                registry=registry)
```

- [ ] **Step 4: Run to verify pass, then the full suite**

Run: `python -m pytest tests/test_dispatch_regrant.py -q` → 3 passed.
Run: `python -m pytest -q` → 540 passed, 6 skipped. If a pre-existing test asserts the exact key set of `/healthz`'s `delivery` block, add `unroutable_live` to that expectation — it is an additive field.

- [ ] **Step 5: Commit**

```bash
git add src/chat_gateway/delivery.py src/chat_gateway/service.py src/chat_gateway/__main__.py tests/test_dispatch_regrant.py
git commit -m "fix(CG-90): the dispatcher re-checks the grant at send time, not only at boot replay"
```

---

### Task 4: `ManagedSecrets` and the boot order

**Files:**
- Create: `src/chat_gateway/managed_secrets.py`
- Test: `tests/test_managed_secrets.py`

**Interfaces:**
- Consumes: `env_file.parse_env_file(text: str) -> dict[str, str]`.
- Produces:
  - `ManagedSecrets(path: Path, *, process_env_names: frozenset[str], hand_env_names: frozenset[str] = frozenset(), environ: dict | None = None)`
  - `.load_at_boot() -> int` — applies the file over the environment except names in `process_env_names`; missing file → `0`.
  - `.blocked(name: str) -> bool` — name was in the real process env at boot.
  - `.snapshot(names: Iterable[str]) -> SecretsSnapshot`; `.restore(snap: SecretsSnapshot) -> None`.
  - `.apply(changes: dict[str, str | None]) -> None` — `None` removes; writes the file atomically then the environ.
  - `.source_of(name: str) -> str` — `"process" | "managed" | ".env" | "unset"`.
  - `.shadowed() -> list[str]` — managed names also present in the hand-written `.env`, sorted.
  - `.hand_env_names` is a public, assignable attribute (boot sets it after the hand file loads).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_managed_secrets.py
"""CG-90 Task 4."""
import os
import sys

import pytest

from chat_gateway.env_file import load_env_file
from chat_gateway.managed_secrets import ManagedSecrets


def _ms(tmp_path, environ, process=frozenset(), hand=frozenset()):
    return ManagedSecrets(tmp_path / "state" / "managed.env", process_env_names=process,
                          hand_env_names=hand, environ=environ)


def test_apply_writes_file_and_environ(tmp_path):
    env = {}
    ms = _ms(tmp_path, env)
    ms.apply({"CHAT_GATEWAY_API_KEY__X": "cgk_abc"})
    assert env["CHAT_GATEWAY_API_KEY__X"] == "cgk_abc"
    text = (tmp_path / "state" / "managed.env").read_text(encoding="utf-8")
    assert 'CHAT_GATEWAY_API_KEY__X="cgk_abc"' in text


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_file_is_0600(tmp_path):
    ms = _ms(tmp_path, {})
    ms.apply({"A": "1"})
    assert oct(os.stat(tmp_path / "state" / "managed.env").st_mode & 0o777) == "0o600"


def test_none_removes(tmp_path):
    env = {}
    ms = _ms(tmp_path, env)
    ms.apply({"A": "1", "B": "2"})
    ms.apply({"A": None})
    assert "A" not in env and env["B"] == "2"
    assert "A=" not in (tmp_path / "state" / "managed.env").read_text(encoding="utf-8")


def test_snapshot_restore_rolls_back_file_and_environ(tmp_path):
    env = {"A": "old"}
    ms = _ms(tmp_path, env)
    ms.apply({"A": "v1"})
    snap = ms.snapshot(["A", "NEW"])
    ms.apply({"A": "v2", "NEW": "n"})
    ms.restore(snap)
    assert env["A"] == "v1" and "NEW" not in env
    assert '"v2"' not in (tmp_path / "state" / "managed.env").read_text(encoding="utf-8")


def test_restore_of_a_file_that_did_not_exist_deletes_it(tmp_path):
    env = {}
    ms = _ms(tmp_path, env)
    snap = ms.snapshot(["A"])
    ms.apply({"A": "1"})
    ms.restore(snap)
    assert not (tmp_path / "state" / "managed.env").exists() and "A" not in env


def test_a_value_with_a_quote_or_newline_is_refused(tmp_path):
    ms = _ms(tmp_path, {})
    for bad in ('a"b', "a\nb"):
        with pytest.raises(ValueError):
            ms.apply({"A": bad})


def test_boot_managed_beats_hand_env_and_process_beats_both(tmp_path):
    """Spec §4: a page-rotated key survives a reboot with the OLD value still in
    the read-only hand-written .env; a real process env var is never overridden."""
    env = {"PROC": "from-process"}
    managed = tmp_path / "state" / "managed.env"
    managed.parent.mkdir(parents=True)
    managed.write_text('KEY="new"\nPROC="from-managed"\n', encoding="utf-8")
    hand = tmp_path / "gateway.env"
    hand.write_text("KEY=old\n", encoding="utf-8")
    ms = ManagedSecrets(managed, process_env_names=frozenset(env), environ=env)
    assert ms.load_at_boot() == 1
    load_env_file(hand, environ=env)
    assert env["KEY"] == "new"
    assert env["PROC"] == "from-process"
    assert ms.blocked("PROC") and not ms.blocked("KEY")


def test_source_and_shadowed(tmp_path):
    env = {"P": "x", "H": "y"}
    ms = _ms(tmp_path, env, process=frozenset({"P"}), hand=frozenset({"H", "S"}))
    ms.apply({"S": "z", "M": "m"})
    assert ms.source_of("P") == "process"
    assert ms.source_of("M") == "managed"
    assert ms.source_of("H") == ".env"
    assert ms.source_of("NOPE") == "unset"
    assert ms.shadowed() == ["S"]


def test_missing_file_at_boot_is_zero(tmp_path):
    assert _ms(tmp_path, {}).load_at_boot() == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_managed_secrets.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/chat_gateway/managed_secrets.py
"""Secrets the admin console mints or receives (CG-90, spec §4).

The hand-written env file is mounted read-only and stays the operator's. This
file is the gateway's: `<state_dir>/managed.env`, mode 0600, written atomically,
and loaded at boot BEFORE the hand-written file. `load_env_file` lets an
already-present value win (`env_file.py`), so loading this first is what makes
a console-rotated key survive a reboot. A name set in the real process
environment beats both, by the same rule — the console refuses to manage such a
name rather than write a value that would be ignored at the next boot.

Values are never returned, logged or interpolated. Names are non-secret.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .env_file import parse_env_file


@dataclass(frozen=True)
class SecretsSnapshot:
    file_bytes: bytes | None
    environ: dict[str, str | None]


class ManagedSecrets:
    def __init__(self, path: Path, *, process_env_names: frozenset[str],
                 hand_env_names: frozenset[str] = frozenset(),
                 environ: dict | None = None):
        self._path = Path(path)
        self._process = frozenset(process_env_names)
        self.hand_env_names = frozenset(hand_env_names)
        self._environ = os.environ if environ is None else environ

    # -- reading ---------------------------------------------------------------
    def _entries(self) -> dict[str, str]:
        try:
            return parse_env_file(self._path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return {}

    def load_at_boot(self) -> int:
        applied = 0
        for name, value in self._entries().items():
            if name in self._process:
                continue
            self._environ[name] = value
            applied += 1
        return applied

    def blocked(self, name: str) -> bool:
        return name in self._process

    def source_of(self, name: str) -> str:
        if name in self._process:
            return "process"
        if name in self._entries():
            return "managed"
        if name in self.hand_env_names:
            return ".env"
        return "unset"

    def shadowed(self) -> list[str]:
        return sorted(set(self._entries()) & self.hand_env_names)

    # -- writing ---------------------------------------------------------------
    def snapshot(self, names: Iterable[str]) -> SecretsSnapshot:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            raw = None
        return SecretsSnapshot(raw, {n: self._environ.get(n) for n in names})

    def restore(self, snap: SecretsSnapshot) -> None:
        if snap.file_bytes is None:
            self._path.unlink(missing_ok=True)
        else:
            self._write_bytes(snap.file_bytes)
        for name, value in snap.environ.items():
            if value is None:
                self._environ.pop(name, None)
            else:
                self._environ[name] = value

    def apply(self, changes: dict[str, str | None]) -> None:
        for name, value in changes.items():
            if value is not None and ('"' in value or "\n" in value or "\r" in value):
                # Refused, not escaped: the value is never echoed, so the
                # message names only the variable.
                raise ValueError(f"{name}: value contains a quote or newline")
        entries = self._entries()
        for name, value in changes.items():
            if value is None:
                entries.pop(name, None)
            else:
                entries[name] = value
        body = "".join(f'{n}="{v}"\n' for n, v in sorted(entries.items()))
        self._write_bytes(body.encode("utf-8"))
        for name, value in changes.items():
            if value is None:
                self._environ.pop(name, None)
            else:
                self._environ[name] = value

    def _write_bytes(self, data: bytes) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, self._path)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_managed_secrets.py -q` → all pass (one skipped on Windows).

- [ ] **Step 5: Commit**

```bash
git add src/chat_gateway/managed_secrets.py tests/test_managed_secrets.py
git commit -m "feat(CG-90): ManagedSecrets — the gateway-owned 0600 secrets file, loaded before .env"
```

---

### Task 5: `RegistryStore` — the single writer

**Files:**
- Create: `src/chat_gateway/registry_store.py`
- Modify: `pyproject.toml` (`dependencies` gains `"ruamel.yaml>=0.18",`)
- Test: `tests/test_registry_store.py`

**Interfaces:**
- Consumes: `RegistryHolder` (Task 2), `ManagedSecrets` (Task 4), `load_registry`.
- Produces:
  - `class StoreError(Exception)` with `.status: int` (409 conflict, 422 invalid, 404 not found, 500 rollback failure).
  - `RegistryStore(path: Path, holder: RegistryHolder, secrets: ManagedSecrets, now_fn=None)` — raises `RegistryError` if `path` is a directory.
  - `.sha256 -> str` (of the bytes last loaded/written).
  - `.apply(mutate: Callable[[CommentedMap], None] | None, *, secrets: dict[str, str | None] | None = None, expect_sha256: str | None = None) -> Registry`.
  - `.reload() -> Registry`.
  - `.note_refusal(message: str) -> None`.
  - Counters: `.writes`, `.refused`, `.last_write_error: str | None`, `.memory_disk_diverged: bool`.
  - Module helper `flow_seq(items: list[str]) -> CommentedSeq`.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml` `dependencies`, add `"ruamel.yaml>=0.18",` after `"PyYAML>=6.0",`. Run `python -m pip install -e .` (dev box already has 0.18.17).

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_registry_store.py
"""CG-90 Task 5 — spec §5's write path, step by step."""
from pathlib import Path

import pytest

from chat_gateway.managed_secrets import ManagedSecrets
from chat_gateway.registry import RegistryError, load_registry
from chat_gateway.registry_holder import RegistryHolder
from chat_gateway.registry_store import RegistryStore, StoreError, flow_seq

TEXT = """# top comment survives
identities:
  i1:
    display: d1
    webhook_url_env: W1   # inline comment survives
apps:
  a1:
    key_env: K1
    identities: [i1]
    allow_inbound: false   # hard rule #6
"""


def _store(tmp_path, text=TEXT, newline="\n"):
    p = tmp_path / "registry.yaml"
    p.write_bytes(text.replace("\n", newline).encode("utf-8"))
    holder = RegistryHolder(load_registry(p))
    env = {}
    secrets = ManagedSecrets(tmp_path / "state" / "managed.env",
                             process_env_names=frozenset(), environ=env)
    return RegistryStore(p, holder, secrets), holder, env, p


def _add_a2(tree):
    from ruamel.yaml.comments import CommentedMap
    m = CommentedMap()
    m["key_env"] = "K2"
    m["identities"] = flow_seq(["i1"])
    m["allow_inbound"] = False
    tree["apps"]["a2"] = m


def test_noop_example_registry_round_trips_byte_identical(tmp_path):
    src = Path("config/registry.example.yaml").read_bytes()
    store, *_ , p = _store(tmp_path, src.decode("utf-8").replace("\r\n", "\n"))
    before = p.read_bytes()
    store.apply(lambda tree: None)
    assert p.read_bytes() == before


def test_add_preserves_comments_and_swaps(tmp_path):
    store, holder, _, p = _store(tmp_path)
    reg = store.apply(_add_a2)
    text = p.read_text(encoding="utf-8")
    assert "# top comment survives" in text and "# inline comment survives" in text
    assert "# hard rule #6" in text
    assert "identities: [i1]" in text.split("a2:")[1]
    assert holder.current is reg and "a2" in holder.apps


def test_crlf_file_stays_crlf(tmp_path):
    store, _, _, p = _store(tmp_path, newline="\r\n")
    store.apply(_add_a2)
    raw = p.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")


def test_invalid_edit_is_422_and_nothing_changes(tmp_path):
    store, holder, env, p = _store(tmp_path)
    before, live = p.read_bytes(), holder.current

    def bad(tree):
        tree["apps"]["a1"]["identities"] = flow_seq(["nope"])

    with pytest.raises(StoreError) as e:
        store.apply(bad, secrets={"K1": "cgk_x"})
    assert e.value.status == 422 and "unknown identity" in str(e.value)
    assert p.read_bytes() == before and holder.current is live and "K1" not in env
    assert store.refused == 1 and store.writes == 0


def test_write_after_out_of_band_edit_is_409(tmp_path):
    store, _, _, p = _store(tmp_path)
    p.write_text(TEXT + "# hand edit\n", encoding="utf-8")
    with pytest.raises(StoreError) as e:
        store.apply(_add_a2)
    assert e.value.status == 409


def test_stale_expected_sha_is_409(tmp_path):
    store, *_ = _store(tmp_path)
    with pytest.raises(StoreError) as e:
        store.apply(_add_a2, expect_sha256="0" * 64)
    assert e.value.status == 409


def test_backup_is_written_with_utc_stamp(tmp_path):
    store, _, _, p = _store(tmp_path)
    before = p.read_bytes()
    store.apply(_add_a2)
    baks = list(tmp_path.glob("registry.yaml.bak-*"))
    assert len(baks) == 1 and baks[0].read_bytes() == before


def test_noop_edit_skips_backup_and_same_second_backups_do_not_collide(tmp_path):
    fixed = lambda: __import__("datetime").datetime(2026, 10, 15, 12, 0, 0)  # noqa: E731
    store, *_ = _store(tmp_path)
    store._now = fixed
    store.apply(_add_a2)
    store.apply(lambda t: t["apps"]["a2"].__setitem__("allow_inbound", False))  # no change
    assert len(list(tmp_path.glob("registry.yaml.bak-*"))) == 1
    store.apply(lambda t: t["apps"].pop("a2"))
    names = sorted(p.name for p in tmp_path.glob("registry.yaml.bak-*"))
    assert names == ["registry.yaml.bak-20261015-120000", "registry.yaml.bak-20261015-120000-2"]


def test_a_secret_value_with_a_quote_is_422_and_nothing_written(tmp_path):
    store, holder, env, p = _store(tmp_path)
    before = p.read_bytes()
    with pytest.raises(StoreError) as e:
        store.apply(_add_a2, secrets={"K2": 'bad"value'})
    assert e.value.status == 422 and "bad" not in str(e.value).replace("K2", "")
    assert p.read_bytes() == before and "K2" not in env and "a2" not in holder.apps


def test_secrets_only_change_writes_no_registry_backup(tmp_path):
    store, _, env, p = _store(tmp_path)
    before = p.read_bytes()
    store.apply(None, secrets={"K1": "cgk_new"})
    assert env["K1"] == "cgk_new" and p.read_bytes() == before
    assert list(tmp_path.glob("registry.yaml.bak-*")) == []


def test_failure_at_registry_write_rolls_back_secrets(tmp_path, monkeypatch):
    store, holder, env, p = _store(tmp_path)
    before, live = p.read_bytes(), holder.current
    import chat_gateway.registry_store as rs

    def boom(*a, **kw):
        raise OSError("disk full")

    # `copymode`, not `os.replace`: `os` is one shared module object, so
    # patching `os.replace` would also break ManagedSecrets' own writes and
    # its rollback. `shutil.copymode` is called only by the registry write.
    monkeypatch.setattr(rs.shutil, "copymode", boom)
    with pytest.raises(StoreError) as e:
        store.apply(_add_a2, secrets={"K2": "cgk_two"})
    assert e.value.status == 500
    assert "K2" not in env and p.read_bytes() == before and holder.current is live
    assert store.memory_disk_diverged is False


def test_failed_rollback_marks_divergence(tmp_path, monkeypatch):
    store, *_ = _store(tmp_path)
    import chat_gateway.registry_store as rs
    monkeypatch.setattr(rs.shutil, "copymode", lambda *a, **kw: (_ for _ in ()).throw(OSError("x")))
    monkeypatch.setattr(store._secrets, "restore", lambda snap: (_ for _ in ()).throw(OSError("y")))
    with pytest.raises(StoreError):
        store.apply(_add_a2, secrets={"K2": "cgk_two"})
    assert store.memory_disk_diverged is True


def test_reload_picks_up_a_hand_edit(tmp_path):
    store, holder, _, p = _store(tmp_path)
    p.write_text(TEXT + "  a3:\n    key_env: K3\n    identities: [i1]\n    allow_inbound: false\n",
                 encoding="utf-8")
    store.reload()
    assert "a3" in holder.apps
    store.apply(_add_a2)  # hash re-recorded, so no 409


def test_reload_of_an_invalid_file_is_422_and_keeps_live(tmp_path):
    store, holder, _, p = _store(tmp_path)
    live = holder.current
    p.write_text("apps: {}\n", encoding="utf-8")
    with pytest.raises(StoreError) as e:
        store.reload()
    assert e.value.status == 422 and holder.current is live


def test_directory_registry_is_refused(tmp_path):
    d = tmp_path / "reg.d"
    d.mkdir()
    (d / "a.yaml").write_text(TEXT, encoding="utf-8")
    holder = RegistryHolder(load_registry(d))
    ms = ManagedSecrets(tmp_path / "m.env", process_env_names=frozenset(), environ={})
    with pytest.raises(RegistryError, match="directory"):
        RegistryStore(d, holder, ms)
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_registry_store.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 4: Implement**

```python
# src/chat_gateway/registry_store.py
"""The only writer of registry.yaml (CG-90, spec §5).

Every mutation, under one lock: out-of-band check → edit → serialize → validate
with the REAL loader on the exact bytes → parser agreement → secrets → backup →
atomic write → swap. Any failure before the swap leaves the file, the secrets
and the live registry as they were. The caller audits after success.

ruamel.yaml writes (comments and key order survive — measured byte-identical on
a no-op round trip of both readable registries, 2026-10-15); PyYAML, via
`load_registry`, still reads. Step 5 proves the two agree on every write.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import os
import shutil
import threading
from collections.abc import Callable
from pathlib import Path

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .managed_secrets import ManagedSecrets
from .registry import Registry, RegistryError, load_registry
from .registry_holder import RegistryHolder


class StoreError(Exception):
    """A refused or failed console write. Messages are authored here and name
    ids and env-var NAMES only — never a value (hard rule #2)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def flow_seq(items: list[str]) -> CommentedSeq:
    """A `[a, b]` list — the style every readable registry uses."""
    seq = CommentedSeq(items)
    seq.fa.set_flow_style()
    return seq


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _plain(node):
    if isinstance(node, dict):
        return {k: _plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_plain(v) for v in node]
    return node


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RegistryStore:
    def __init__(self, path: Path, holder: RegistryHolder, secrets: ManagedSecrets,
                 now_fn: Callable[[], dt.datetime] | None = None):
        self._path = Path(path)
        if self._path.is_dir():
            raise RegistryError(
                f"{self._path} is a directory registry; the admin console edits a "
                "single registry.yaml and cannot write the per-tenant directory form"
            )
        self._holder = holder
        self._secrets = secrets
        self._now = now_fn or (lambda: dt.datetime.now(dt.timezone.utc))
        self._lock = threading.Lock()
        self._sha = _sha(self._path.read_bytes())
        self.writes = 0
        self.refused = 0
        self.last_write_error: str | None = None
        self.memory_disk_diverged = False

    @property
    def sha256(self) -> str:
        return self._sha

    def note_refusal(self, message: str) -> None:
        self.refused += 1
        self.last_write_error = message[:300]

    def _refuse(self, status: int, message: str) -> StoreError:
        self.note_refusal(message)
        return StoreError(status, message)

    def apply(self, mutate: Callable[[CommentedMap], None] | None, *,
              secrets: dict[str, str | None] | None = None,
              expect_sha256: str | None = None) -> Registry:
        with self._lock:
            raw = self._path.read_bytes()
            # 1. out-of-band check
            if _sha(raw) != self._sha:
                raise self._refuse(409, "registry.yaml was edited outside the console — "
                                        "reload from disk first")
            if expect_sha256 is not None and expect_sha256 != self._sha:
                raise self._refuse(409, "the registry changed since this page loaded it — "
                                        "refresh and try again")
            crlf = b"\r\n" in raw
            text = raw.decode("utf-8").replace("\r\n", "\n")
            y = _yaml()
            tree = y.load(text)
            # 2. edit
            if mutate is not None:
                try:
                    mutate(tree)
                except StoreError as exc:
                    self.note_refusal(str(exc))
                    raise
            # 3. serialize
            buf = io.StringIO()
            y.dump(tree, buf)
            out = buf.getvalue()
            if crlf:
                out = out.replace("\n", "\r\n")
            candidate = out.encode("utf-8")
            changed = candidate != raw
            # 4. validate with the real loader on the exact bytes
            probe = self._path.with_name(f".{self._path.name}.candidate")
            try:
                probe.write_bytes(candidate)
                new = load_registry(probe)
            except RegistryError as exc:
                raise self._refuse(422, str(exc)) from exc
            finally:
                probe.unlink(missing_ok=True)
            # 5. parser agreement
            if yaml.safe_load(candidate.decode("utf-8")) != _plain(tree):
                raise self._refuse(422, "the YAML writer and loader disagree on this edit; "
                                        "nothing was written")
            # 6. secrets
            snap = self._secrets.snapshot((secrets or {}).keys())
            try:
                if secrets:
                    self._secrets.apply(secrets)
                if changed:
                    # 7. backup  8. atomic write
                    self._backup()
                    tmp = self._path.with_name(f".{self._path.name}.tmp")
                    with open(tmp, "wb") as fh:
                        fh.write(candidate)
                        fh.flush()
                        os.fsync(fh.fileno())
                    shutil.copymode(self._path, tmp)
                    os.replace(tmp, self._path)
            except ValueError as exc:
                # `ManagedSecrets.apply` validates every value BEFORE writing
                # anything, so this refusal has nothing to roll back. A 422,
                # not the 500 below; the message names the variable only.
                raise self._refuse(422, str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 — roll back, then report
                try:
                    self._secrets.restore(snap)
                except Exception:  # noqa: BLE001
                    self.memory_disk_diverged = True
                msg = f"write failed and was rolled back ({type(exc).__name__})"
                if self.memory_disk_diverged:
                    msg = (f"write failed ({type(exc).__name__}) and the rollback of "
                           "managed secrets ALSO failed — restart the gateway")
                raise self._refuse(500, msg) from exc
            # 9. swap
            self._holder.swap(new)
            self._sha = _sha(candidate)
            self.writes += 1
            self.last_write_error = None
            return new

    def reload(self) -> Registry:
        with self._lock:
            raw = self._path.read_bytes()
            try:
                new = load_registry(self._path)
            except RegistryError as exc:
                raise self._refuse(422, str(exc)) from exc
            self._holder.swap(new)
            self._sha = _sha(raw)
            return new

    def _backup(self) -> None:
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        dest = self._path.with_name(f"{self._path.name}.bak-{stamp}")
        n = 2
        while dest.exists():
            dest = self._path.with_name(f"{self._path.name}.bak-{stamp}-{n}")
            n += 1
        shutil.copy2(self._path, dest)
```

- [ ] **Step 5: Run to verify pass, then the full suite**

Run: `python -m pytest tests/test_registry_store.py -q` → all pass.
Run: `python -m pytest -q` → all pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/chat_gateway/registry_store.py tests/test_registry_store.py
git commit -m "feat(CG-90): RegistryStore — validate, back up, write atomically, swap; roll back on failure"
```

---

### Task 6: The admin API, `/healthz` block, and boot wiring

**Files:**
- Create: `src/chat_gateway/admin_audit.py`, `src/chat_gateway/admin.py`
- Modify: `src/chat_gateway/service.py` (`create_app` signature ~288; mount after the MCP mount ~439; `/healthz` body ~777 and reasons before the closing comment ~1511)
- Modify: `src/chat_gateway/__main__.py` (`build_runtime` boot order + 7-tuple; `main` unpack + `create_app(admin=...)`)
- Modify: `tests/test_mcp.py:1342-1343` (7-tuple)
- Test: `tests/test_admin_api.py`

**Interfaces:**
- Consumes: `RegistryHolder`, `RegistryStore`, `StoreError`, `flow_seq`, `ManagedSecrets`, `auth.mint_key`, `registry.ADMIN_KEY_ENV`, `DeliveryLog.query(source, limit)`.
- Produces:
  - `AdminAudit(path: Path)`, `.record(action: str, target: str, fields: list[str]) -> None`.
  - `AdminWiring(store: RegistryStore, secrets: ManagedSecrets, audit: AdminAudit)` dataclass with `.health() -> dict`.
  - `build_admin_router(registry: RegistryHolder, wiring: AdminWiring, *, delivery_log: DeliveryLog, now_fn=None) -> APIRouter`.
  - Helpers: `env_name(prefix: str, ident: str) -> str`, `parse_webhook_space(url: str) -> str`, `widening(old: App | None, new) -> list[str]`.
  - `create_app(..., admin: AdminWiring | None = None)`.
  - HTTP (all `/admin/api/*` need `Authorization: Bearer <admin key>`; mutating bodies may carry `registry_sha256`):
    - `GET /admin/api/state`
    - `POST /admin/api/apps` → `201 {app_id, key_env, key, shadows_env_file}`
    - `PUT /admin/api/apps/{app_id}` → `{app_id}`
    - `POST /admin/api/apps/{app_id}/rotate-key` → `{app_id, key_env, key, shadows_env_file}`
    - `POST /admin/api/apps/{app_id}/delete` body `{confirm_app_id}`
    - `POST /admin/api/identities` body `{name, display, webhook_url}` → `201 {name, webhook_url_env, space}`
    - `PUT /admin/api/identities/{name}` body `{display}`
    - `POST /admin/api/identities/{name}/webhook` body `{webhook_url}`
    - `POST /admin/api/identities/{name}/delete` body `{confirm_name}`
    - `POST /admin/api/reload`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_admin_api.py
"""CG-90 Task 6 — the admin API against a real store in tmp_path."""
import json

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


@pytest.fixture()
def gw(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", ADMIN)
    monkeypatch.setenv("ADM_K1", "cgk_tenant_one")
    monkeypatch.setenv("ADM_W1", "https://x.example/hook")
    p = tmp_path / "registry.yaml"
    p.write_text(TEXT, encoding="utf-8")
    holder = RegistryHolder(load_registry(p))
    import os
    secrets = ManagedSecrets(tmp_path / "state" / "managed.env",
                             process_env_names=frozenset({"CHAT_GATEWAY_ADMIN_KEY"}),
                             environ=os.environ)
    wiring = AdminWiring(store=RegistryStore(p, holder, secrets), secrets=secrets,
                         audit=AdminAudit(tmp_path / "state" / "admin_audit.jsonl"))
    client = TestClient(create_app(holder, Inbox(), {"webhook": object()}, admin=wiring))
    yield client, holder, wiring, tmp_path
    for k in list(os.environ):
        if k.startswith(("CHAT_GATEWAY_API_KEY__", "GOOGLE_CHAT_WEBHOOK_URL__")):
            os.environ.pop(k)


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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_admin_api.py -q`
Expected: FAIL — `ModuleNotFoundError: chat_gateway.admin`.

- [ ] **Step 3: Implement `admin_audit.py`**

```python
# src/chat_gateway/admin_audit.py
"""Append-only record of admin console writes (CG-90). Names only — the
action, the app or identity id, and the FIELD NAMES changed. Never a value,
never a URL (hard rule #2). Mode 0600, like every other audit trail here."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path


class AdminAudit:
    def __init__(self, path: Path):
        self._path = Path(path)

    def record(self, action: str, target: str, fields: list[str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat(),
                           "actor": "admin", "action": action, "target": target,
                           "fields": sorted(fields)}) + "\n"
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
```

- [ ] **Step 4: Implement `admin.py`**

```python
# src/chat_gateway/admin.py
"""The admin console's API (CG-90; spec docs/superpowers/specs/2026-10-15-admin-console-design.md).

Mounted only when `GATEWAY_ENABLE_ADMIN=1`. Authenticated by its OWN key
(`CHAT_GATEWAY_ADMIN_KEY`), never a tenant's (hard rule #4). Every write goes
through `RegistryStore.apply`, so validation, backup, atomic write and swap
have one home. A secret value leaves this module only in the response that
minted it (hard rule #2).
"""

from __future__ import annotations

import datetime as dt
import hmac
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from ruamel.yaml.comments import CommentedMap

from .admin_audit import AdminAudit
from .auth import mint_key
from .delivery import DeliveryLog
from .managed_secrets import ManagedSecrets
from .registry import ADMIN_KEY_ENV, SEVERITIES, App
from .registry_holder import RegistryHolder
from .registry_store import RegistryStore, StoreError, flow_seq

KEY_PREFIX = "CHAT_GATEWAY_API_KEY__"
WEBHOOK_PREFIX = "GOOGLE_CHAT_WEBHOOK_URL__"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_WEBHOOK_PATH = re.compile(r"^/v1/spaces/([A-Za-z0-9_-]+)/messages$")
RATE_LIMIT_FAILURES = 5
RATE_LIMIT_WINDOW_S = 60.0
STATIC_DIR = Path(__file__).parent / "static" / "admin"
RULE_6 = ("Hard rule #6: inbound crosses to a consumer only by that consumer's "
          "explicit registry opt-in.")


def env_name(prefix: str, ident: str) -> str:
    return prefix + ident.upper().replace("-", "_")


def parse_webhook_space(url: str) -> str:
    """Validate an incoming-webhook URL's SHAPE and return `spaces/<id>`.

    Messages never include the URL or any part of it — it embeds key+token.
    """
    u = urlparse(url.strip())
    m = _WEBHOOK_PATH.match(u.path)
    q = parse_qs(u.query)
    if u.scheme != "https" or u.hostname != "chat.googleapis.com" or not m:
        raise ValueError("not a Google Chat incoming-webhook URL "
                         "(https://chat.googleapis.com/v1/spaces/<id>/messages?key=…&token=…)")
    if not q.get("key") or not q.get("token"):
        raise ValueError("the webhook URL is missing its key or token parameter — "
                         "copy the whole URL from the Chat space's webhook settings")
    return f"spaces/{m.group(1)}"


def widening(old: App | None, new) -> list[str]:
    """Which parts of `new` widen inbound relative to `old` (spec §6.4)."""
    reasons: list[str] = []
    old_in = bool(old and old.allow_inbound)
    if new.allow_inbound and not old_in:
        reasons.append("allow_inbound")
    old_cb = old.callback_url if old else ""
    if new.callback_url and new.callback_url != old_cb:
        reasons.append("callback_url")
    if new.allow_inbound:
        old_users = set(old.allowed_users) if old else set()
        new_users = {u.lower() for u in new.allowed_users}
        if old_users and not new_users:
            reasons.append("allowed_users emptied")
        elif old_users and new_users - old_users:
            reasons.append("allowed_users added")
    return reasons


@dataclass
class AdminWiring:
    store: RegistryStore
    secrets: ManagedSecrets
    audit: AdminAudit

    def health(self) -> dict:
        return {"enabled": True, "writes": self.store.writes,
                "refused": self.store.refused,
                "last_write_error": self.store.last_write_error,
                "shadowed_env_names": self.secrets.shadowed(),
                "memory_disk_diverged": self.store.memory_disk_diverged}


class _Limiter:
    def __init__(self, now_fn: Callable[[], float]):
        self._now = now_fn
        self._fails: dict[str, list[float]] = {}

    def _recent(self, host: str) -> list[float]:
        cutoff = self._now() - RATE_LIMIT_WINDOW_S
        recent = [t for t in self._fails.get(host, []) if t > cutoff]
        self._fails[host] = recent
        return recent

    def check(self, host: str) -> None:
        if len(self._recent(host)) >= RATE_LIMIT_FAILURES:
            raise HTTPException(429, "too many failed admin logins — wait a minute")

    def fail(self, host: str) -> None:
        self._recent(host).append(self._now())


# -- request bodies -----------------------------------------------------------
class _Guarded(BaseModel):
    registry_sha256: str | None = None


class AppFields(_Guarded):
    identities: list[str] = Field(default_factory=list)
    routes: dict[str, str] = Field(default_factory=dict)
    allow_inbound: bool = False
    callback_url: str = ""
    allowed_users: list[str] = Field(default_factory=list)
    unreachable_message: str = ""
    confirm_app_id: str = ""


class AppCreate(AppFields):
    app_id: str


# ⚠ Hard rule #2: every field that can carry a webhook URL DEFAULTS to "" and
# is checked by hand. FastAPI's 422 body echoes the offending `input`, and for
# a missing required field that input is the whole request body — webhook URL
# included. With defaults, a missing field never reaches pydantic's echo.
class IdentityCreate(_Guarded):
    name: str = ""
    display: str = ""
    webhook_url: str = ""


class DisplayIn(_Guarded):
    display: str = ""


class WebhookIn(_Guarded):
    webhook_url: str = ""


class ConfirmApp(_Guarded):
    confirm_app_id: str = ""


class ConfirmIdentity(_Guarded):
    confirm_name: str = ""


def build_admin_router(registry: RegistryHolder, wiring: AdminWiring, *,
                       delivery_log: DeliveryLog,
                       now_fn: Callable[[], float] | None = None) -> APIRouter:
    import time

    limiter = _Limiter(now_fn or time.monotonic)
    store, secrets, audit = wiring.store, wiring.secrets, wiring.audit
    router = APIRouter(prefix="/admin")

    def require_admin(request: Request, response: Response,
                      authorization: str | None = Header(default=None)) -> None:
        response.headers["Cache-Control"] = "no-store"
        host = request.client.host if request.client else "?"
        limiter.check(host)
        expected = os.environ.get(ADMIN_KEY_ENV, "")
        presented = ""
        if authorization and authorization.startswith("Bearer "):
            presented = authorization.removeprefix("Bearer ").strip()
        if not expected or not presented or not hmac.compare_digest(presented, expected):
            limiter.fail(host)
            raise HTTPException(401, "admin key required", headers={"WWW-Authenticate": "Bearer"})
        for app in registry.apps.values():
            v = os.environ.get(app.key_env, "")
            if v and hmac.compare_digest(v, expected):
                raise HTTPException(503, f"the admin key equals app {app.app_id!r}'s API key — "
                                         "mint a separate admin key (hard rule #4)")

    def refuse(status: int, message: str) -> HTTPException:
        store.note_refusal(message)
        return HTTPException(status, message)

    def run(mutate, secret_changes=None, *, sha=None):
        try:
            return store.apply(mutate, secrets=secret_changes, expect_sha256=sha)
        except StoreError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        except ValueError as exc:  # ManagedSecrets value refusal — names only
            raise refuse(422, str(exc)) from exc

    def check_id(value: str, kind: str) -> None:
        if not ID_RE.match(value):
            raise refuse(422, f"{kind} id must match {ID_RE.pattern} "
                              "(lowercase letters, digits, hyphens; not starting with '_' or '-')")

    def managed_name(name: str) -> None:
        if secrets.blocked(name):
            raise refuse(409, f"{name} is set in the gateway's process environment, which "
                              "overrides managed.env at boot — change it there, not here")

    def guard_inbound(old: App | None, body: AppFields, app_id: str) -> list[str]:
        reasons = widening(old, body)
        if not reasons:
            return []
        if old is not None and old.inbound_locked:
            raise refuse(403, f"app {app_id!r} is inbound_locked: widening ({', '.join(reasons)}) "
                              "is a registry file edit, not a console action. " + RULE_6)
        if body.confirm_app_id != app_id:
            raise refuse(428, f"widening inbound ({', '.join(reasons)}) requires typing the app id "
                              f"to confirm. {RULE_6}")
        return reasons

    def app_map(target: CommentedMap, body: AppFields, key_env: str | None) -> list[str]:
        """Write `body` into `target` in place; returns the field names written.
        In place, so comments on untouched keys and the hand-only
        `inbound_locked` key survive."""
        if key_env is not None:
            target["key_env"] = key_env
        target["identities"] = flow_seq(list(body.identities))
        target["allow_inbound"] = bool(body.allow_inbound)  # hard rule #7: always written
        routes = CommentedMap()
        for sev in ["default", *SEVERITIES]:
            if body.routes.get(sev):
                routes[sev] = body.routes[sev]
        if routes:
            target["routes"] = routes
        else:
            target.pop("routes", None)
        for key, value in (("callback_url", body.callback_url),
                           ("unreachable_message", body.unreachable_message)):
            if value:
                target[key] = value
            else:
                target.pop(key, None)
        if body.allowed_users:
            target["allowed_users"] = flow_seq([u.lower() for u in body.allowed_users])
        else:
            target.pop("allowed_users", None)
        return ["identities", "allow_inbound", "routes", "callback_url",
                "unreachable_message", "allowed_users"]

    def get_app(app_id: str) -> App:
        app = registry.apps.get(app_id)
        if app is None:
            raise HTTPException(404, f"unknown app {app_id!r}")
        return app

    # -- page ----------------------------------------------------------------
    page_headers = {
        "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self'; "
                                    "img-src 'self' data:; connect-src 'self'; "
                                    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }
    static_files = {"admin.js": "text/javascript", "admin.css": "text/css"}

    @router.get("", include_in_schema=False)
    def page():
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html",
                            headers=page_headers)

    @router.get("/static/{name}", include_in_schema=False)
    def static(name: str):
        if name not in static_files:
            raise HTTPException(404, "not found")
        return FileResponse(STATIC_DIR / name, media_type=static_files[name],
                            headers=page_headers)

    # -- read ------------------------------------------------------------------
    @router.get("/api/state", dependencies=[Depends(require_admin)])
    def state():
        reg = registry.current
        return {
            "registry_sha256": store.sha256,
            "apps": {
                a.app_id: {
                    "identities": a.identities, "routes": a.routes,
                    "allow_inbound": a.allow_inbound, "inbound_locked": a.inbound_locked,
                    "callback_url_set": bool(a.callback_url),
                    "allowed_users": a.allowed_users,
                    "unreachable_message_set": bool(a.unreachable_message),
                    "key_env": a.key_env, "key_configured": a.key_configured(),
                    "key_source": secrets.source_of(a.key_env),
                    "recent_deliveries": delivery_log.query(a.app_id, 5),
                } for a in sorted(reg.apps.values(), key=lambda a: a.app_id)
            },
            "identities": {
                i.name: {
                    "display": i.display, "mode": i.mode, "space": i.space,
                    "webhook_url_env": i.webhook_url_env, "env_resolved": i.env_resolved(),
                    "secret_source": (secrets.source_of(i.webhook_url_env)
                                      if i.webhook_url_env else None),
                } for i in sorted(reg.identities.values(), key=lambda i: i.name)
            },
            "shadowed_env_names": secrets.shadowed(),
            "inbound_defaulted": list(reg.inbound_defaulted),
        }

    # -- apps ------------------------------------------------------------------
    @router.post("/api/apps", status_code=201, dependencies=[Depends(require_admin)])
    def create_app_entry(body: AppCreate):
        check_id(body.app_id, "app")
        if body.app_id in registry.apps:
            raise refuse(409, f"app {body.app_id!r} already exists")
        widened = guard_inbound(None, body, body.app_id)
        key_env = env_name(KEY_PREFIX, body.app_id)
        managed_name(key_env)
        key = mint_key()
        fields: list[str] = []

        def mutate(tree):
            m = CommentedMap()
            fields.extend(app_map(m, body, key_env))
            tree["apps"][body.app_id] = m

        run(mutate, {key_env: key}, sha=body.registry_sha256)
        audit.record("app_created", body.app_id, ["key_env", *fields])
        if widened:
            audit.record("inbound_widened", body.app_id, widened)
        return {"app_id": body.app_id, "key_env": key_env, "key": key,
                "shadows_env_file": key_env in secrets.hand_env_names}

    @router.put("/api/apps/{app_id}", dependencies=[Depends(require_admin)])
    def update_app_entry(app_id: str, body: AppFields):
        old = get_app(app_id)
        widened = guard_inbound(old, body, app_id)
        fields: list[str] = []
        run(lambda tree: fields.extend(app_map(tree["apps"][app_id], body, None)),
            sha=body.registry_sha256)
        audit.record("app_updated", app_id, fields)
        if widened:
            audit.record("inbound_widened", app_id, widened)
        return {"app_id": app_id}

    @router.post("/api/apps/{app_id}/rotate-key", dependencies=[Depends(require_admin)])
    def rotate_key(app_id: str, body: _Guarded | None = None):
        app = get_app(app_id)
        managed_name(app.key_env)
        key = mint_key()
        run(None, {app.key_env: key}, sha=body.registry_sha256 if body else None)
        audit.record("key_rotated", app_id, [app.key_env])
        return {"app_id": app_id, "key_env": app.key_env, "key": key,
                "shadows_env_file": app.key_env in secrets.hand_env_names}

    @router.post("/api/apps/{app_id}/delete", dependencies=[Depends(require_admin)])
    def delete_app_entry(app_id: str, body: ConfirmApp):
        app = get_app(app_id)
        if body.confirm_app_id != app_id:
            raise refuse(428, "deleting an app requires typing its id to confirm")
        remove = {} if secrets.source_of(app.key_env) != "managed" else {app.key_env: None}
        run(lambda tree: tree["apps"].pop(app_id), remove or None, sha=body.registry_sha256)
        audit.record("app_deleted", app_id, [])
        return {"app_id": app_id}

    # -- identities ------------------------------------------------------------
    @router.post("/api/identities", status_code=201, dependencies=[Depends(require_admin)])
    def create_identity(body: IdentityCreate):
        if not body.display.strip() or not body.webhook_url.strip():
            raise refuse(422, "name, display and webhook_url are all required")
        check_id(body.name, "identity")
        if body.name in registry.identities:
            raise refuse(409, f"identity {body.name!r} already exists")
        try:
            space = parse_webhook_space(body.webhook_url)
        except ValueError as exc:
            raise refuse(422, str(exc)) from exc
        url_env = env_name(WEBHOOK_PREFIX, body.name)
        managed_name(url_env)

        def mutate(tree):
            m = CommentedMap()
            m["display"] = body.display
            m["channel"] = "google_chat"
            m["mode"] = "webhook"
            m["webhook_url_env"] = url_env
            m["space"] = space
            tree["identities"][body.name] = m

        run(mutate, {url_env: body.webhook_url.strip()}, sha=body.registry_sha256)
        audit.record("identity_created", body.name, ["display", "webhook_url_env", "space"])
        return {"name": body.name, "webhook_url_env": url_env, "space": space}

    def get_identity(name: str):
        ident = registry.identities.get(name)
        if ident is None:
            raise HTTPException(404, f"unknown identity {name!r}")
        return ident

    @router.put("/api/identities/{name}", dependencies=[Depends(require_admin)])
    def update_identity(name: str, body: DisplayIn):
        get_identity(name)
        run(lambda tree: tree["identities"][name].__setitem__("display", body.display),
            sha=body.registry_sha256)
        audit.record("identity_updated", name, ["display"])
        return {"name": name}

    @router.post("/api/identities/{name}/webhook", dependencies=[Depends(require_admin)])
    def replace_webhook(name: str, body: WebhookIn):
        ident = get_identity(name)
        if ident.mode != "webhook" or not ident.webhook_url_env:
            raise refuse(409, f"identity {name!r} is not a webhook identity")
        try:
            space = parse_webhook_space(body.webhook_url)
        except ValueError as exc:
            raise refuse(422, str(exc)) from exc
        managed_name(ident.webhook_url_env)
        run(lambda tree: tree["identities"][name].__setitem__("space", space),
            {ident.webhook_url_env: body.webhook_url.strip()}, sha=body.registry_sha256)
        audit.record("webhook_replaced", name, [ident.webhook_url_env, "space"])
        return {"name": name, "space": space}

    @router.post("/api/identities/{name}/delete", dependencies=[Depends(require_admin)])
    def delete_identity(name: str, body: ConfirmIdentity):
        ident = get_identity(name)
        if body.confirm_name != name:
            raise refuse(428, "deleting an identity requires typing its name to confirm")
        users = sorted(a.app_id for a in registry.apps.values() if name in a.identities)
        if users:
            raise refuse(409, f"identity {name!r} is still granted to: {', '.join(users)} — "
                              "remove it from those apps first")
        env = ident.webhook_url_env
        remove = {env: None} if env and secrets.source_of(env) == "managed" else None
        run(lambda tree: tree["identities"].pop(name), remove, sha=body.registry_sha256)
        audit.record("identity_deleted", name, [])
        return {"name": name}

    # -- reload ----------------------------------------------------------------
    @router.post("/api/reload", dependencies=[Depends(require_admin)])
    def reload():
        try:
            store.reload()
        except StoreError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        audit.record("reloaded_from_disk", "registry.yaml", [])
        return {"registry_sha256": store.sha256}

    return router
```

Note for the implementer: `rotate_key` takes an optional body; FastAPI treats `body: _Guarded | None = None` as an optional JSON body. If FastAPI rejects the union in this version, change it to `body: _Guarded = _Guarded()` and drop the `if body else None`.

- [ ] **Step 5: Wire into `create_app`**

In `service.py` imports add `from .admin import AdminWiring, build_admin_router` (inside a `TYPE_CHECKING`-free normal import is fine; no cycle — `admin` imports `delivery`, `registry`, `auth`, never `service`).

Add the keyword after `mcp_enabled: bool = False,`:

```python
               # CG-90. None = console off (the default, and every existing test).
               admin: "AdminWiring | None" = None,
```

After the MCP `include_router` block (~line 439):

```python
    # CG-90. Mounted only when wired, the posture `/mcp` set: an operator arms
    # it deliberately. Its own credential, never `authenticate()` (hard rule #4).
    app.state.admin = admin
    if admin is not None:
        app.include_router(build_admin_router(registry, admin, delivery_log=log))
```

In the `/healthz` `body` dict, after the `"mcp": {...},` entry:

```python
            # CG-90 spec §7. Counters never degrade (a refusal is a guard
            # working, CG-12); `shadowed_env_names` is an operator to-do, not a
            # fault. Only `memory_disk_diverged` degrades — below, in `reasons`.
            "admin": admin.health() if admin is not None else {"enabled": False},
```

Immediately before the `# Names, never values:` comment near the end of `healthz`:

```python
        if admin is not None and admin.store.memory_disk_diverged:
            reasons.append(
                "admin console: a failed write could not be fully rolled back, so "
                "registry.yaml / managed.env on disk and the live registry may "
                "disagree — use Reload from disk at /admin, or restart the gateway"
            )
```

- [ ] **Step 6: Wire into `__main__.py`**

Restructure the top of `build_runtime` (after `install_url_redaction()`), replacing the env-file block and moving the `state_dir` read up:

```python
    state_dir = os.environ.get("CHAT_GATEWAY_STATE_DIR", "state")
    # CG-90. Snapshot the REAL process environment before any file touches it:
    # a name in here beats every file at every boot, so the console must refuse
    # to manage it rather than write a value that would be ignored.
    admin_enabled = os.environ.get("GATEWAY_ENABLE_ADMIN", "0") == "1"
    process_env_names = frozenset(os.environ)
    managed = None
    if admin_enabled:
        from .managed_secrets import ManagedSecrets

        managed = ManagedSecrets(Path(state_dir) / "managed.env",
                                 process_env_names=process_env_names)
        # BEFORE the hand-written env file: `load_env_file` lets a present value
        # win, so this order is what makes a console-rotated key survive a boot.
        print(f"admin: loaded {managed.load_at_boot()} managed secret(s)", flush=True)

    env_file = os.environ.get("CHAT_GATEWAY_ENV_FILE", "")
    if env_file:
        from .env_file import load_env_file, parse_env_file

        print(f"env: loaded {load_env_file(env_file)} key(s) from {env_file}", flush=True)
        if managed is not None:
            managed.hand_env_names = frozenset(
                parse_env_file(Path(env_file).read_text(encoding="utf-8-sig")))
```

Keep the existing (now Task-2) `registry = RegistryHolder(load_registry(...))` and the `inbound_defaulted` warning. Delete the later `state_dir = os.environ.get(...)` line (it moved up). After the warning block, add:

```python
    admin = None
    if admin_enabled:
        from .admin import AdminWiring
        from .admin_audit import AdminAudit
        from .registry import ADMIN_KEY_ENV
        from .registry_store import RegistryStore

        if not os.environ.get(ADMIN_KEY_ENV):
            raise RegistryError(
                f"GATEWAY_ENABLE_ADMIN=1 needs {ADMIN_KEY_ENV} (mint one with "
                "`python -m chat_gateway mint-key`; docs/deploy/nas.md)")
        admin = AdminWiring(
            store=RegistryStore(Path(os.environ.get("CHAT_GATEWAY_REGISTRY",
                                                    "config/registry.yaml")),
                                registry, managed),
            secrets=managed,
            audit=AdminAudit(Path(state_dir) / "admin_audit.jsonl"))
```

Change the return to `return registry, inbox, adapters, subscriber, state_dir, sweeper, admin`.

In `main`, change the unpack to `registry, inbox, adapters, subscriber, state_dir, sweeper, admin = build_runtime()` and pass `admin=admin,` to `create_app(...)` after `mcp_enabled=...`.

In `tests/test_mcp.py` lines 1342-1343 change the lambda to return 7 elements:

```python
                        lambda: (registry, Inbox(), {"webhook": FakeAdapter()},
                                 None, str(tmp_path / "state"), _FakeSweeper(), None))
```

Add to `tests/test_admin_api.py`:

```python
def test_admin_enabled_without_key_is_a_config_error(tmp_path, monkeypatch, capsys):
    from chat_gateway.__main__ import main

    reg = tmp_path / "registry.yaml"
    reg.write_text(TEXT, encoding="utf-8")
    monkeypatch.setenv("CHAT_GATEWAY_REGISTRY", str(reg))
    monkeypatch.setenv("CHAT_GATEWAY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHAT_GATEWAY_INBOX_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("GATEWAY_ENABLE_ADMIN", "1")
    monkeypatch.delenv("CHAT_GATEWAY_ADMIN_KEY", raising=False)
    for k in ("CHAT_GATEWAY_ENV_FILE", "GOOGLE_APPLICATION_CREDENTIALS", "GATEWAY_ENABLE_PUBSUB"):
        monkeypatch.delenv(k, raising=False)
    assert main(["check"]) == 2
    assert "CHAT_GATEWAY_ADMIN_KEY" in capsys.readouterr().err


def test_build_runtime_wires_admin_when_enabled(tmp_path, monkeypatch):
    from chat_gateway.__main__ import build_runtime

    reg = tmp_path / "registry.yaml"
    reg.write_text(TEXT, encoding="utf-8")
    monkeypatch.setenv("CHAT_GATEWAY_REGISTRY", str(reg))
    monkeypatch.setenv("CHAT_GATEWAY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHAT_GATEWAY_INBOX_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("GATEWAY_ENABLE_ADMIN", "1")
    monkeypatch.setenv("CHAT_GATEWAY_ADMIN_KEY", ADMIN)
    for k in ("CHAT_GATEWAY_ENV_FILE", "GOOGLE_APPLICATION_CREDENTIALS", "GATEWAY_ENABLE_PUBSUB"):
        monkeypatch.delenv(k, raising=False)
    admin = build_runtime()[6]
    assert isinstance(admin, AdminWiring)
    assert admin.secrets.blocked("CHAT_GATEWAY_ADMIN_KEY")
```

- [ ] **Step 7: Run to verify pass, then the full suite**

Run: `python -m pytest tests/test_admin_api.py -q` → all pass. The page tests (`GET /admin`) are Task 7; the route exists but `index.html` does not yet, so do not request it here.
Run: `python -m pytest -q` → all pass. If a pre-existing test pins the exact top-level key set of `/healthz`, add `admin` to it.

- [ ] **Step 8: Secret-exposure sweep test**

Append to `tests/test_admin_api.py`:

```python
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
```

Run it → PASS.

- [ ] **Step 9: Commit**

```bash
git add src/chat_gateway/admin.py src/chat_gateway/admin_audit.py src/chat_gateway/service.py src/chat_gateway/__main__.py tests/test_admin_api.py tests/test_mcp.py
git commit -m "feat(CG-90): admin API — guarded app/identity CRUD, key rotation, reload, /healthz admin block"
```

---

### Task 7: The page

**Files:**
- Create: `src/chat_gateway/static/admin/index.html`, `admin.js`, `admin.css`
- Modify: `pyproject.toml` (package data)
- Test: `tests/test_admin_page.py`

**Interfaces:**
- Consumes: every `/admin/api/*` endpoint from Task 6; tenant `POST /v1/notify` and `GET /v1/deliveries` with the freshly revealed key.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_admin_page.py
"""CG-90 Task 7 — the shell is static, CSP-locked, and stores nothing."""
import os
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

STATIC = Path("src/chat_gateway/static/admin")
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_admin_page.py -q`
Expected: FAIL — `index.html` missing (500/RuntimeError) and file-read errors.

- [ ] **Step 3: `index.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gateway Admin</title>
<link rel="stylesheet" href="/admin/static/admin.css">
<script src="/admin/static/admin.js" defer></script>
</head>
<body>
<header><h1>chat-gateway admin</h1><span id="sha" class="muted"></span></header>
<main>
  <section id="login">
    <h2>Sign in</h2>
    <p class="muted">The admin key is held in this tab's memory only. Reloading asks again.</p>
    <form id="login-form">
      <label>Admin key <input id="admin-key" type="password" autocomplete="off" required></label>
      <button type="submit">Sign in</button>
    </form>
    <p id="login-error" class="error" role="alert"></p>
  </section>

  <section id="console" hidden>
    <nav>
      <button id="nav-board" type="button">Apps &amp; identities</button>
      <button id="nav-new-app" type="button">New app</button>
      <button id="nav-new-identity" type="button">New identity</button>
      <button id="nav-reload" type="button">Reload from disk</button>
    </nav>
    <p id="banner" class="warn" hidden></p>
    <p id="toast" role="status"></p>
    <div id="view"></div>
  </section>
</main>
</body>
</html>
```

- [ ] **Step 4: `admin.css`**

```css
:root { --bg:#fafafa; --fg:#1b1b1b; --muted:#666; --line:#ddd; --accent:#1a5fb4; --warn:#9a6700; --err:#b3261e; --card:#fff; }
@media (prefers-color-scheme: dark) { :root { --bg:#161616; --fg:#e8e8e8; --muted:#9a9a9a; --line:#333; --accent:#78aeed; --warn:#e5b45b; --err:#f2b8b5; --card:#1f1f1f; } }
* { box-sizing: border-box; }
body { margin:0; font:15px/1.5 system-ui, sans-serif; background:var(--bg); color:var(--fg); }
header { display:flex; gap:1rem; align-items:baseline; padding:1rem 16px; border-bottom:1px solid var(--line); }
h1 { font-size:1.15rem; margin:0; }
main { max-width:1100px; margin:0 auto; padding:1rem 16px; }
nav { display:flex; flex-wrap:wrap; gap:.5rem; margin-bottom:1rem; }
button { font:inherit; padding:.4rem .8rem; border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--fg); cursor:pointer; }
button.primary { background:var(--accent); color:#fff; border-color:var(--accent); }
button.danger { color:var(--err); border-color:var(--err); }
input, select, textarea { font:inherit; padding:.35rem .5rem; border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--fg); width:100%; }
label { display:block; margin:.5rem 0; }
fieldset { border:1px solid var(--line); border-radius:8px; margin:1rem 0; padding:.5rem 1rem 1rem; }
legend { font-weight:600; }
table { width:100%; border-collapse:collapse; margin:.5rem 0 1.5rem; }
th, td { text-align:left; padding:.4rem .5rem; border-bottom:1px solid var(--line); vertical-align:top; }
.table-wrap { overflow-x:auto; }
.muted { color:var(--muted); }
.warn { color:var(--warn); }
.error { color:var(--err); }
.pill { display:inline-block; padding:0 .45rem; border-radius:999px; border:1px solid var(--line); font-size:.85em; }
.ok { color:#2e7d32; } @media (prefers-color-scheme: dark) { .ok { color:#8bd08f; } }
.secret { font-family:ui-monospace, monospace; word-break:break-all; background:var(--card); border:1px solid var(--line); border-radius:6px; padding:.5rem; }
pre { overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:6px; padding:.75rem; font-size:.85em; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:1rem; margin:1rem 0; }
ol.guide li { margin:.25rem 0; }
#toast:empty { display:none; }
```

- [ ] **Step 5: `admin.js`**

```javascript
// chat-gateway admin console (CG-90). No framework, no storage: the admin key
// lives in `adminKey` for the life of this tab only. Every piece of data is
// rendered through textContent, never parsed as HTML, so registry content
// cannot become markup.
"use strict";

let adminKey = "";
let state = null;
const SEVERITIES = ["alert", "warning", "info"];
const RULE_6 = "Hard rule #6: inbound crosses to a consumer only by that consumer's explicit registry opt-in.";

function el(tag, attrs, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "on") for (const [ev, fn] of Object.entries(v)) n.addEventListener(ev, fn);
    else if (k === "text") n.textContent = v;
    else if (v === true) n.setAttribute(k, "");
    else if (v !== false && v != null) n.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c != null) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
}
const $ = (id) => document.getElementById(id);
function toast(msg, isError) { const t = $("toast"); t.textContent = msg || ""; t.className = isError ? "error" : "ok"; }
function view(...nodes) { const v = $("view"); v.replaceChildren(...nodes); }

async function api(method, path, body, key) {
  const headers = { Authorization: "Bearer " + (key || adminKey) };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  let data = null;
  try { data = await r.json(); } catch (_) { data = null; }
  if (!r.ok) {
    const err = new Error((data && data.detail) ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : ("HTTP " + r.status));
    err.status = r.status;
    throw err;
  }
  return data;
}

async function refresh() {
  state = await api("GET", "/admin/api/state");
  $("sha").textContent = "registry " + state.registry_sha256.slice(0, 12);
  const b = $("banner");
  if (state.shadowed_env_names.length) {
    b.hidden = false;
    b.textContent = "Stale secrets in the read-only .env (old values that would revive if managed.env is lost): "
      + state.shadowed_env_names.join(", ") + ". Remove those lines from .env by hand.";
  } else b.hidden = true;
}

// Mutating call: carries the sha the page last saw, so a second tab gets 409.
async function write(method, path, body) {
  const out = await api(method, path, Object.assign({ registry_sha256: state.registry_sha256 }, body || {}));
  await refresh();
  return out;
}

// --------------------------------------------------------------- board ---
function board() {
  const appRows = Object.entries(state.apps).map(([id, a]) => el("tr", {},
    el("td", {}, el("strong", { text: id })),
    el("td", { text: a.identities.join(", ") || "—" }),
    el("td", { text: Object.entries(a.routes).map(([s, i]) => s + "→" + i).join(", ") || "—" }),
    el("td", {}, el("span", { class: "pill", text: a.allow_inbound ? "inbound on" : "inbound off" }),
      a.inbound_locked ? el("span", { class: "pill warn", text: "locked" }) : null),
    el("td", { class: a.key_configured ? "ok" : "error", text: (a.key_configured ? "key set" : "key missing") + " (" + a.key_source + ")" }),
    el("td", { text: a.recent_deliveries.length ? a.recent_deliveries[a.recent_deliveries.length - 1].status : "—" }),
    el("td", {}, el("button", { type: "button", text: "Manage", on: { click: () => appDetail(id) } }))));
  const idRows = Object.entries(state.identities).map(([name, i]) => el("tr", {},
    el("td", {}, el("strong", { text: name })),
    el("td", { text: i.display }),
    el("td", { text: i.space || "—" }),
    el("td", { class: i.env_resolved ? "ok" : "error", text: i.env_resolved ? "ready" : "not resolvable" }),
    el("td", { text: i.secret_source || "—" }),
    el("td", {},
      i.mode === "webhook" ? el("button", { type: "button", text: "Replace webhook", on: { click: () => replaceWebhook(name) } }) : null, " ",
      el("button", { type: "button", text: "Rename display", on: { click: () => renameIdentity(name, i.display) } }), " ",
      el("button", { type: "button", class: "danger", text: "Delete", on: { click: () => deleteIdentity(name) } }))));
  view(
    el("h2", { text: "Apps" }),
    el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, ...["App", "Identities", "Routes", "Inbound", "API key", "Last delivery", ""].map((h) => el("th", { text: h })))),
      el("tbody", {}, appRows))),
    el("h2", { text: "Identities" }),
    el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, ...["Identity", "Display", "Space", "Webhook", "Secret source", ""].map((h) => el("th", { text: h })))),
      el("tbody", {}, idRows))));
}

// ------------------------------------------------------------ app form ---
function appFields(a) {
  const ids = Object.keys(state.identities);
  const idBoxes = ids.map((n) => el("label", {}, el("input", { type: "checkbox", name: "identity", value: n, checked: a.identities.includes(n), style: "width:auto" }), " " + n));
  const routeSel = (sev) => el("label", {}, sev === "default" ? "default (every severity without its own route)" : sev,
    el("select", { name: "route-" + sev }, el("option", { value: "", text: sev === "default" ? "— none —" : "(use default)" }),
      ids.map((n) => el("option", { value: n, text: n, selected: (a.routes[sev] || "") === n }))));
  return el("div", {},
    el("fieldset", {}, el("legend", { text: "Identities this app may send as" }), idBoxes),
    el("fieldset", {}, el("legend", { text: "Notify routes" }),
      el("p", { class: "warn", text: "Severity picks the SPACE, not just the loudness (CG-86): split routes put an all-clear in a different room from the alert it closes." }),
      routeSel("default"), SEVERITIES.map(routeSel)),
    el("fieldset", {}, el("legend", { text: "Inbound" }),
      a.inbound_locked ? el("p", { class: "warn", text: "This app is inbound_locked. Inbound can only be narrowed here; widening is a registry file edit." }) : null,
      el("label", {}, el("input", { type: "checkbox", name: "allow_inbound", checked: a.allow_inbound, style: "width:auto" }), " allow_inbound"),
      el("label", {}, "callback_url (push; blank = poll only)", el("input", { name: "callback_url", placeholder: a.callback_url_set ? "(set — leave blank to remove, or enter a new one)" : "" })),
      el("label", {}, "allowed_users (one email per line; empty = anyone in the space)", el("textarea", { name: "allowed_users", rows: "3" }, (a.allowed_users || []).join("\n"))),
      el("label", {}, "unreachable_message", el("input", { name: "unreachable_message" }))));
}

function readAppFields(form) {
  const routes = {};
  for (const sev of ["default", ...SEVERITIES]) { const v = form.querySelector("[name=route-" + sev + "]").value; if (v) routes[sev] = v; }
  return {
    identities: [...form.querySelectorAll("[name=identity]:checked")].map((x) => x.value),
    routes,
    allow_inbound: form.querySelector("[name=allow_inbound]").checked,
    callback_url: form.querySelector("[name=callback_url]").value.trim(),
    allowed_users: form.querySelector("[name=allowed_users]").value.split("\n").map((s) => s.trim()).filter(Boolean),
    unreachable_message: form.querySelector("[name=unreachable_message]").value.trim(),
  };
}

// A 428 from the server means "this widens inbound": show rule #6 and ask for the typed id.
async function withInboundConfirm(appId, send) {
  try { return await send(""); }
  catch (e) {
    if (e.status !== 428) throw e;
    const typed = await typedConfirm(e.message + "\n\n" + RULE_6, appId);
    if (typed === null) throw new Error("cancelled");
    return await send(typed);
  }
}

function typedConfirm(message, expected) {
  return new Promise((resolve) => {
    const input = el("input", { "aria-label": "Type " + expected + " to confirm" });
    const card = el("div", { class: "card" },
      el("p", { class: "warn", text: message }),
      el("label", {}, "Type ", el("strong", { text: expected }), " to confirm", input),
      el("button", { type: "button", class: "primary", text: "Confirm", on: { click: () => { card.remove(); resolve(input.value); } } }), " ",
      el("button", { type: "button", text: "Cancel", on: { click: () => { card.remove(); resolve(null); } } }));
    $("view").prepend(card);
    input.focus();
  });
}

function appDetail(appId) {
  const a = state.apps[appId];
  const form = el("form", {}, appFields(a), el("button", { type: "submit", class: "primary", text: "Save" }));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await withInboundConfirm(appId, (c) => write("PUT", "/admin/api/apps/" + encodeURIComponent(appId), Object.assign(readAppFields(form), { confirm_app_id: c })));
      toast("Saved " + appId + ". Live now.");
      board();
    } catch (e) { toast(e.message, true); }
  });
  view(el("h2", { text: "App " + appId }),
    el("p", { class: "muted", text: "API key env var: " + a.key_env + " (" + a.key_source + ")" }),
    form,
    el("div", { class: "card" },
      el("h3", { text: "Rotate API key" }),
      el("p", { text: "The current key stops working the moment you confirm. Update the consuming app right after." }),
      el("button", { type: "button", text: "Rotate key", on: { click: async () => {
        const typed = await typedConfirm("Rotate the API key for " + appId + "? The old key dies immediately.", appId);
        if (typed !== appId) return;
        try { const r = await write("POST", "/admin/api/apps/" + encodeURIComponent(appId) + "/rotate-key", {}); reveal(r); }
        catch (e) { toast(e.message, true); }
      } } })),
    el("div", { class: "card" },
      el("h3", { text: "Delete app" }),
      el("button", { type: "button", class: "danger", text: "Delete " + appId, on: { click: async () => {
        const typed = await typedConfirm("Delete app " + appId + "? Its queued messages close as unroutable.", appId);
        if (typed === null) return;
        try { await write("POST", "/admin/api/apps/" + encodeURIComponent(appId) + "/delete", { confirm_app_id: typed }); toast("Deleted " + appId); board(); }
        catch (e) { toast(e.message, true); }
      } } })));
}

// ----------------------------------------------------------- new app ---
function newApp() {
  const blank = { identities: [], routes: {}, allow_inbound: false, inbound_locked: false, callback_url_set: false, allowed_users: [] };
  const idInput = el("input", { name: "app_id", required: true, pattern: "[a-z0-9][a-z0-9-]{0,62}", placeholder: "e.g. rotaryphone" });
  const envHint = el("p", { class: "muted" });
  idInput.addEventListener("input", () => { envHint.textContent = "API key env var: CHAT_GATEWAY_API_KEY__" + idInput.value.toUpperCase().replace(/-/g, "_"); });
  const form = el("form", {},
    el("fieldset", {}, el("legend", { text: "1 · App id" }), el("label", {}, "App id", idInput), envHint),
    el("p", {}, "2 · Need a new Chat space identity first? ",
      el("button", { type: "button", text: "Create an identity", on: { click: newIdentity } })),
    el("p", { class: "muted", text: "3 and 4 · identities, routes and inbound:" }),
    appFields(blank),
    el("button", { type: "submit", class: "primary", text: "Create app and mint key" }));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const appId = idInput.value.trim();
    try {
      const r = await withInboundConfirm(appId, (c) => write("POST", "/admin/api/apps", Object.assign(readAppFields(form), { app_id: appId, confirm_app_id: c })));
      reveal(r);
    } catch (e) { toast(e.message, true); }
  });
  view(el("h2", { text: "New app" }), form);
}

// ------------------------------------------------------ new identity ---
function newIdentity() {
  const form = el("form", {},
    el("ol", { class: "guide" },
      el("li", { text: "Open the Google Chat space this identity should post into." }),
      el("li", { text: "Space name ▸ Apps & integrations ▸ Webhooks ▸ Add webhook." }),
      el("li", { text: "Set the name and avatar now — they are fixed at creation and cannot be changed later without a new webhook." }),
      el("li", { text: "Save, copy the whole URL, and paste it below. It is stored in managed.env and never shown again." })),
    el("label", {}, "Identity name", el("input", { name: "name", required: true, pattern: "[a-z0-9][a-z0-9-]{0,62}", placeholder: "e.g. rotaryphone-alerts" })),
    el("label", {}, "Display name (for /v1/identities)", el("input", { name: "display", required: true })),
    el("label", {}, "Webhook URL", el("input", { name: "webhook_url", type: "password", autocomplete: "off", required: true })),
    el("button", { type: "submit", class: "primary", text: "Create identity" }));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = (n) => form.querySelector("[name=" + n + "]").value;
    try {
      const r = await write("POST", "/admin/api/identities", { name: f("name").trim(), display: f("display").trim(), webhook_url: f("webhook_url") });
      toast("Identity " + r.name + " created in " + r.space + ".");
      newApp();
    } catch (e) { toast(e.message, true); }
  });
  view(el("h2", { text: "New identity (Chat webhook)" }), form);
}

async function replaceWebhook(name) {
  const input = el("input", { type: "password", autocomplete: "off", "aria-label": "New webhook URL" });
  view(el("h2", { text: "Replace webhook for " + name }),
    el("p", { text: "Google Chat has no regenerate button: delete the old webhook in the space, create a new one, paste its URL here." }),
    input,
    el("button", { type: "button", class: "primary", text: "Replace", on: { click: async () => {
      try { await write("POST", "/admin/api/identities/" + encodeURIComponent(name) + "/webhook", { webhook_url: input.value }); toast("Webhook replaced."); board(); }
      catch (e) { toast(e.message, true); }
    } } }));
}

async function renameIdentity(name, current) {
  const input = el("input", { value: current, "aria-label": "Display name" });
  view(el("h2", { text: "Display name for " + name }), input,
    el("button", { type: "button", class: "primary", text: "Save", on: { click: async () => {
      try { await write("PUT", "/admin/api/identities/" + encodeURIComponent(name), { display: input.value.trim() }); board(); }
      catch (e) { toast(e.message, true); }
    } } }));
}

async function deleteIdentity(name) {
  const typed = await typedConfirm("Delete identity " + name + "?", name);
  if (typed === null) return;
  try { await write("POST", "/admin/api/identities/" + encodeURIComponent(name) + "/delete", { confirm_name: typed }); toast("Deleted " + name); board(); }
  catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------- reveal ---
function reveal(r) {
  const base = window.location.origin;
  const key = r.key;
  const curl = "printf 'url = \"%s\"\\nheader = \"Authorization: Bearer %s\"\\nheader = \"Content-Type: application/json\"\\ndata = \"%s\"\\n' \\\n  \"" + base + "/v1/notify\" \"$CHAT_GATEWAY_API_KEY\" '{\\\"severity\\\":\\\"info\\\",\\\"title\\\":\\\"hello\\\"}' \\\n  | curl --config -";
  const py = "from chat_gateway.client import GatewayClient\nimport os\ngw = GatewayClient(\"" + base + "\", api_key=os.environ[\"CHAT_GATEWAY_API_KEY\"])\ngw.notify(\"info\", \"hello\")";
  const mcp = JSON.stringify({ mcpServers: { "chat-gateway": { type: "http", url: base + "/mcp", headers: { Authorization: "Bearer ${CHAT_GATEWAY_API_KEY}" } } } }, null, 2);
  const keyBox = el("div", { class: "secret", text: key });
  const result = el("p", { role: "status" });
  view(
    el("h2", { text: "API key for " + r.app_id }),
    el("p", { class: "warn", text: "This is the only time this key is shown. Copy it into the consuming app's secret store now." }),
    keyBox,
    el("button", { type: "button", text: "Copy key", on: { click: () => navigator.clipboard.writeText(key).then(() => toast("Copied.")) } }),
    r.shadows_env_file ? el("p", { class: "warn", text: "The OLD value of " + r.key_env + " is still in the read-only .env. It is inert now, but would revive if managed.env were lost — remove that line by hand." }) : null,
    el("h3", { text: "Connect" }),
    el("p", {}, "Gateway URL: ", el("code", { text: base }), " · env var in the consumer: ", el("code", { text: "CHAT_GATEWAY_API_KEY" })),
    el("h4", { text: "curl (key stays out of argv)" }), el("pre", { text: curl }),
    el("h4", { text: "Python" }), el("pre", { text: py }),
    el("h4", { text: "MCP client config" }), el("pre", { text: mcp }),
    el("h3", { text: "Send test notification" }),
    el("p", { class: "muted", text: "202 enqueued is not delivery — this waits for the delivery log to say delivered or failed." }),
    el("button", { type: "button", class: "primary", text: "Send test", on: { click: () => testSend(key, result) } }),
    result,
    el("p", {}, el("button", { type: "button", text: "Done", on: { click: board } })));
}

async function testSend(key, out) {
  out.className = ""; out.textContent = "Sending…";
  try {
    const sent = await api("POST", "/v1/notify", { severity: "info", title: "chat-gateway console test", body: "Test notification sent from the admin console." }, key);
    if (sent.status !== "enqueued") { out.textContent = "Not enqueued: " + sent.status; return; }
    for (let i = 0; i < 30; i++) {
      await new Promise((res) => setTimeout(res, 2000));
      const d = await api("GET", "/v1/deliveries?limit=20", undefined, key);
      const mine = d.deliveries.filter((x) => x.id === sent.id);
      const last = mine[mine.length - 1];
      if (last && (last.status === "delivered" || last.status === "failed" || last.status === "unroutable")) {
        out.className = last.status === "delivered" ? "ok" : "error";
        out.textContent = last.status + (last.detail ? " — " + last.detail : "");
        return;
      }
      out.textContent = "Waiting… (" + (last ? last.status : "enqueued") + ")";
    }
    out.className = "error"; out.textContent = "No terminal status after 60s — check GET /v1/deliveries.";
  } catch (e) { out.className = "error"; out.textContent = e.message; }
}

// --------------------------------------------------------------- boot ---
document.addEventListener("DOMContentLoaded", () => {
  $("login-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    adminKey = $("admin-key").value.trim();
    $("admin-key").value = "";
    try {
      await refresh();
      $("login").hidden = true; $("console").hidden = false;
      board();
    } catch (e) { adminKey = ""; $("login-error").textContent = e.message; }
  });
  $("nav-board").addEventListener("click", async () => { await refresh(); board(); });
  $("nav-new-app").addEventListener("click", newApp);
  $("nav-new-identity").addEventListener("click", newIdentity);
  $("nav-reload").addEventListener("click", async () => {
    try { await api("POST", "/admin/api/reload", {}); await refresh(); board(); toast("Reloaded from disk."); }
    catch (e) { toast(e.message, true); }
  });
});
```

- [ ] **Step 6: Package data**

In `pyproject.toml`, after `[tool.setuptools.packages.find]` block add:

```toml
[tool.setuptools.package-data]
chat_gateway = ["static/admin/*"]
```

Then `python -m pip install -e .`.

- [ ] **Step 7: Run to verify pass, then the full suite**

Run: `python -m pytest tests/test_admin_page.py -q` → all pass.
Run: `python -m pytest -q` → all pass.

- [ ] **Step 8: Commit**

```bash
git add src/chat_gateway/static pyproject.toml tests/test_admin_page.py
git commit -m "feat(CG-90): the admin page — board, wizard, webhook guide, one-time reveal, test send"
```

---

### Task 8: UAT in a browser

**Files:**
- Create: `scripts/admin_uat_server.py` — a throwaway local launcher, committed so the UAT is repeatable.

- [ ] **Step 1: Write the launcher**

```python
# scripts/admin_uat_server.py
"""Local UAT gateway for the admin console (CG-90). Fake webhook adapter, a
temp registry, admin enabled. Not a deployment path. Prints the admin key."""
import os
import sys
import tempfile
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chat_gateway.admin import AdminWiring  # noqa: E402
from chat_gateway.admin_audit import AdminAudit  # noqa: E402
from chat_gateway.envelope import DeliveryResult  # noqa: E402
from chat_gateway.inbox import Inbox  # noqa: E402
from chat_gateway.managed_secrets import ManagedSecrets  # noqa: E402
from chat_gateway.registry import load_registry  # noqa: E402
from chat_gateway.registry_holder import RegistryHolder  # noqa: E402
from chat_gateway.registry_store import RegistryStore  # noqa: E402
from chat_gateway.service import create_app  # noqa: E402


class FakeWebhook:
    def send(self, identity, message):
        print(f"[fake webhook] {identity.name}: {message.text[:60]!r}", flush=True)
        return DeliveryResult(status="delivered", channel="google_chat",
                              identity=identity.name, mode=identity.mode)


tmp = Path(tempfile.mkdtemp(prefix="cg-admin-uat-"))
reg = tmp / "registry.yaml"
reg.write_text("""# UAT registry
identities:
  ops:
    display: Ops
    webhook_url_env: UAT_W_OPS
    space: spaces/UATOPS
apps:
  trader:
    key_env: UAT_K_TRADER
    identities: [ops]
    allow_inbound: false   # hard rule #6
    inbound_locked: true
    routes: {default: ops}
""", encoding="utf-8")
os.environ.update({"CHAT_GATEWAY_ADMIN_KEY": "cgk_uat_admin", "UAT_K_TRADER": "cgk_uat_trader",
                   "UAT_W_OPS": "https://chat.googleapis.com/v1/spaces/UATOPS/messages?key=k&token=t"})
holder = RegistryHolder(load_registry(reg))
secrets = ManagedSecrets(tmp / "state" / "managed.env",
                         process_env_names=frozenset({"CHAT_GATEWAY_ADMIN_KEY"}))
wiring = AdminWiring(store=RegistryStore(reg, holder, secrets), secrets=secrets,
                     audit=AdminAudit(tmp / "state" / "admin_audit.jsonl"))
app = create_app(holder, Inbox(), {"webhook": FakeWebhook()}, admin=wiring)
app.state.dispatcher.start()
print(f"UAT dir: {tmp}\nadmin key: cgk_uat_admin\nopen http://127.0.0.1:8099/admin", flush=True)
uvicorn.run(app, host="127.0.0.1", port=8099)
```

- [ ] **Step 2: Dispatch the `tester` agent (browser mode, session model — never Haiku: its deliverable is a verification)**

Prompt: run `python scripts/admin_uat_server.py` in the background; drive `http://127.0.0.1:8099/admin` with Playwright; report pass/fail with a screenshot per step for:
1. Wrong key → error shown; right key (`cgk_uat_admin`) → board lists `trader` (locked) and `ops`.
2. New identity `uat-room` with URL `https://chat.googleapis.com/v1/spaces/UATROOM/messages?key=a&token=b` → created, space `spaces/UATROOM`; the URL appears nowhere on the page afterwards.
3. New app `uat-app`, identity `uat-room`, default route `uat-room`, inbound off → reveal panel shows a `cgk_` key; "Send test" reaches `delivered`.
4. Board → Manage `uat-app` → tick allow_inbound → Save → typed-confirm card with rule #6 text appears; cancel leaves inbound off; confirm with `uat-app` turns it on.
5. Manage `trader` → tick allow_inbound → Save → refused with an `inbound_locked` message.
6. Rotate `uat-app` key → new key revealed; old key gets 401 from `GET /v1/identities` (check via fetch in the console).
7. Hand-edit the UAT `registry.yaml` (append a comment), then Save any app → 409 message; click Reload from disk → Save succeeds.
8. Delete `uat-app` with typed id → gone from board.
9. Reload the browser tab → login shown again (key not persisted).
10. At 375px wide: no horizontal page scroll on the board.

- [ ] **Step 3: Fix every failing item** (each fix gets a test in the owning task's test file first), re-run the failed items, then commit:

```bash
git add scripts/admin_uat_server.py
git commit -m "test(CG-90): repeatable local UAT launcher for the admin console"
```

---

### Task 9: Docs in this repo

**Files:**
- Modify: `docs/registering-an-app.md` (top), `docs/deploy/nas.md` (§5 compose mounts, §6, env names), `docs/integration-guide.md` (`/healthz` field table), `CLAUDE.md` (one status bullet)

- [ ] **Step 1: `docs/registering-an-app.md`** — insert after the intro paragraph (before "**Not covered here:**"):

```markdown
## The console, if it is enabled

Since CG-90 the gateway can do steps 2–5 itself at **`/admin`** (LAN port, admin
key — `docs/deploy/nas.md`). The four decisions in §1 are still yours; the
console asks them as a form, mints the key and shows it **once**, writes the
registry and `managed.env`, and applies the change without a redeploy. Step 6's
live send is its *Send test* button. Step 7 — handing the key to the consumer —
is still yours.

**This runbook stays the fallback** for a gateway without the console, for any
`inbound_locked` app being widened, and for any secret set in the process
environment, which the console refuses to manage.
```

- [ ] **Step 2: `docs/deploy/nas.md`** — in §5's compose document change the config mount to `"/mnt/datapool/apps/chat-gateway/config:/config"` (drop `:ro`), add to `environment:` `"GATEWAY_ENABLE_ADMIN": "1"`, and add a subsection after §6 titled `### The admin console (CG-90)` containing: the two env names and that `CHAT_GATEWAY_ADMIN_KEY` goes in the hand-written `.env` over stdin like any key (§6's procedure); `managed.env` and `admin_audit.jsonl` under the state dir, both `0600`, both to be backed up with the state dir; the boot order (managed before `.env`; process env beats both); the shadowing hazard verbatim from spec §4; the rollout order from spec §10 (lock aitrader **first**); and that the registry's `.bak-*` files now accumulate one per console write and may be pruned by hand.

- [ ] **Step 3: `docs/integration-guide.md`** — in the `/healthz` field table add rows: `admin.enabled`, `admin.writes`, `admin.refused`, `admin.last_write_error`, `admin.shadowed_env_names` (all "never degrades"), `admin.memory_disk_diverged` ("degrades; reason names Reload from disk"), and `delivery.unroutable_live` ("never degrades").

- [ ] **Step 4: `CLAUDE.md`** — add one bullet at the end of "Current status":

```markdown
- **An admin console at `/admin`, since CG-90 (2026-10-15) — default OFF behind
  `GATEWAY_ENABLE_ADMIN`.** It edits the live registry and a gateway-owned
  `managed.env`, and swaps the registry in-process through `RegistryHolder`.
  Design, decisions and the residual risk of its admin key have ONE home:
  `docs/superpowers/specs/2026-10-15-admin-console-design.md`. Do not restate
  them here. ⚠ **Merged is not in effect** — the box rollout is an operator
  action (`docs/deploy/nas.md`, the CG-90 subsection). No ledger flag moved.
```

Also update the Layout section's module list to mention `registry_holder`, `registry_store`, `managed_secrets`, `admin`, `admin_audit`, and the test count to the measured number from the final full run.

- [ ] **Step 5: Commit**

```bash
git add docs/registering-an-app.md docs/deploy/nas.md docs/integration-guide.md CLAUDE.md
git commit -m "docs(CG-90): the console in the runbook, the NAS deploy, /healthz fields, CLAUDE.md"
```

---

### Task 10: Homelab repo handoff (separate repo, separate PR)

**Files (in `D:/prj/homelab`, on a new branch `docs/chat-gateway-admin-console`):**
- Modify: `nas/services/chat-gateway.md`, `SECRETS.template.md`, `nas/DASHBOARDS.md`

- [ ] **Step 1: Branch** — `cd /d/prj/homelab && git switch main && git pull --ff-only && git switch -c docs/chat-gateway-admin-console`. Read `nas/services/_TEMPLATE.md` and the current `nas/services/chat-gateway.md` first.

- [ ] **Step 2: `nas/services/chat-gateway.md`** — within the existing four headers only (no new headers, no `###`):
  - `## Overview (User)`: one sentence — operator console at `http://<nas-lan-ip>:<port>/admin` for registering apps, rotating keys and replacing webhooks; admin key required; off unless `GATEWAY_ENABLE_ADMIN=1`.
  - `## Deployment (Ops)`: the `config` mount is now read-write; `managed.env` and `admin_audit.jsonl` live under the state dir; `CHAT_GATEWAY_ADMIN_KEY` lives in the hand-written `.env`.
  - `## Reinstall / Recovery`: restore `managed.env` with the state dir, or every console-minted key and webhook is lost; if `managed.env` is lost, keys rotated from the console revert to stale `.env` values.
  - `## Gotchas`: aitrader must keep `inbound_locked: true`; the console refuses names set in compose `environment:`; link to chat-gateway's `docs/deploy/nas.md` CG-90 subsection.

- [ ] **Step 3: `SECRETS.template.md`** — add a row in the existing three-column shape: `CHAT_GATEWAY_ADMIN_KEY` · chat-gateway admin console · rotate by minting a new key, replacing the `.env` line over stdin, redeploying. Add a second row: `<state_dir>/managed.env` (a **file**) · chat-gateway console-managed API keys and webhook URLs · restore with the state dir. Never a value, never the app roster.

- [ ] **Step 4: `nas/DASHBOARDS.md`** — add the console URL beside the existing chat-gateway entry, labelled admin, LAN-only.

- [ ] **Step 5: Commit, push and open the PR** (the user's standing branch-and-PR policy applies to that repo too; ask before pushing if that repo's own instructions differ):

```bash
git add nas/services/chat-gateway.md SECRETS.template.md nas/DASHBOARDS.md
git commit -m "docs(chat-gateway): the CG-90 admin console — mounts, managed.env, admin key"
git push -u origin docs/chat-gateway-admin-console
gh pr create --title "docs(chat-gateway): admin console (CG-90)" --body "Records chat-gateway CG-90's admin console: rw config mount, managed.env under the state dir, CHAT_GATEWAY_ADMIN_KEY, and the dashboard link. No secret values."
```

---

## Finish

- [ ] Full suite on the branch: `python -m pytest -q` — record the count in `CLAUDE.md`'s Layout line (Task 9 Step 4).
- [ ] Whole-branch review by a fresh `pr-reviewer` (session model) against the spec and this plan; fix high/medium findings.
- [ ] Open the chat-gateway PR `feat/cg-90-admin-console` → `main`. Merge per the auto-merge policy **only if** every gate is green — this change touches auth and secrets, so per the user's policy **pause and ask before merging**.
- [ ] The box rollout (spec §10) is the user's operator action; do not perform it from this plan.
