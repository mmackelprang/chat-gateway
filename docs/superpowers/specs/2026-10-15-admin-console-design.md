# A self-service admin console for the gateway — design

**Date:** 2026-10-15 · brainstormed with the user · branch `docs/admin-console-spec`
**Baseline:** `main` at `f9bcf65`, suite **527 passed, 6 skipped** — measured here
with `python -m pytest -q` on the Windows dev box, not copied from `CLAUDE.md`.

**Row this spec produces:** **CG-90** — an operator console at `/admin` that
registers, edits, rotates and removes apps and identities, and applies the
change to the running gateway without a redeploy.

**No ⚠ verification-ledger flag is cleared, added or reworded by anything in
this document, and none may be by the PR it produces.** The console adds no
Google-facing code (§8, rule #3); its test-send is the existing adapters'
bytes from a new caller, exactly the reasoning CG-80 recorded for MCP.

**Every decision below was taken by the user in the brainstorming session**
(§2). They are recorded so they are not re-litigated, and so the declined
options do not disappear from the record.

---

## 1. Problem

Onboarding a tenant today is `docs/registering-an-app.md`: seven manual steps
across two machines — mint a key, hand-edit a gitignored YAML file read down
over base64, append secrets to a `0600` env file over stdin, redeploy, verify
four ways, hand the key over. Every step has a recorded failure mode, two of
them silent (a key in two of three places looks like a typo; copying the dev
registry over the box's deleted `agent-mcp`). The user wants one page that
does this — tokens, webhook setup and URLs from one place — and applies it.

## 2. Decisions (user, 2026-10-15)

| # | Decision | Chosen | Declined, and what it would have given |
|---|---|---|---|
| D1 | Scope | **Full self-service admin** — the gateway writes its own registry and secrets and applies them | *Guide + generate* (no gateway write access to its own config, keeps one manual install step); *consumer docs page* (no registration at all) |
| D2 | Admin auth | **Dedicated admin bearer key, LAN-bound port only** | *Google sign-in* (per-person identity; new LIVE-UNVERIFIED Google code + OAuth client); *proxy/tailnet header* (no login code; trust in an untestable proxy, D2-ACL deferred) |
| D3 | Write scope | **Manage everything**, including hand-written apps (aitrader, jobhunt, agent-mcp) | *Add + manage own* (hand-written apps read-only — a leaked admin key could not touch aitrader); *add only* |
| D4 | Inbound fields | **Editable, with guard** — typed confirmation, rule #6 text, audit; `inbound_locked` apps cannot be widened from the page | *Read-only in UI* (two-way tenants not self-service); *fully editable* (rule #6 sign-off becomes a checkbox) |
| D5 | Apply model | **In-process hot-swap** via a `RegistryHolder` | *Write then self-restart* (no holder refactor; seconds of downtime per click, RestartCount climbs, soak evidence spent); *admin sidecar + `app.redeploy`* (gateway never writes its config; a TrueNAS credential able to redeploy apps) |
| D6 | YAML comments | **Add `ruamel.yaml`** round-trip editing | *Accept loss* (file becomes machine-owned); *`notes:` field* (schema change + migration) |
| D7 | Homelab | **The homelab repo is updated** with the console's deployment, secret and dashboard facts (§10) | — added by the user at §2 approval |

⚠ **D3 is the decision with the largest consequence and is recorded plainly:**
the admin key controls every app that is not `inbound_locked`, including the
real-money tenant's identities and routes. `inbound_locked` (D4) protects
aitrader's **inbound** guarantee only — not its outbound identities or routes.

## 3. Components

One concern per module, following the repo's layout.

| Unit | Does | Depends on |
|---|---|---|
| `registry_holder.py` — `RegistryHolder` | Holds the live `Registry`; `.current` is replaced atomically (single reference assignment under a lock). | `registry.Registry` |
| `registry_store.py` — `RegistryStore` | The **only** writer of `registry.yaml`. Structured edits via `ruamel.yaml`; validate → backup → atomic write → swap (§5). Tracks the sha256 it loaded. | holder, `load_registry`, `ruamel.yaml` |
| `managed_secrets.py` — `ManagedSecrets` | Owns `<state_dir>/managed.env` (`0600`). Writes a name, then sets `os.environ`. Never returns a value except to the mint/rotate caller. | `env_file.parse_env_file` |
| `admin.py` — router | `/admin` (page + static assets) and `/admin/api/*` JSON. Mounted only when `GATEWAY_ENABLE_ADMIN=1`. Admin auth, rate limit, audit. | store, secrets, holder, `auth.mint_key` |
| `admin_audit.py` | Append-only `<state_dir>/admin_audit.jsonl`, `0600`. Records actor=`admin`, UTC time, action, app/identity ids, **field names** changed. Never values, never URLs. | — |
| `static/admin/` | One HTML file + one JS file + one CSS file. No build step, no CDN. | — |

**Consumers refactored to read through the holder** (each reads
`holder.current` once per request/event/scan and uses that snapshot
throughout): `create_app` routes, `SubscriberLoop` / `dispatch`
(`adapters/pubsub.py:746`, `:914`), the delivery `Dispatcher` and its replay
check, `HeartbeatMonitor`, and `mcp.py`'s tool listing and `call_tool`. The
plan must enumerate every site that holds a `Registry` reference by grep, not
from this list — this list is a starting point.

## 4. Configuration and deployment

New env-var NAMES (hard rule #2; values in the runtime env only):

| Name | Holds |
|---|---|
| `GATEWAY_ENABLE_ADMIN` | `1` to mount `/admin`. Default off. Not a credential. |
| `CHAT_GATEWAY_ADMIN_KEY` | The admin bearer key, `cgk_`-shaped, minted with `mint-key`. Never granted to an app. |

**Boot order changes:** `managed.env` is loaded **before** the hand-written
`CHAT_GATEWAY_ENV_FILE`. `load_env_file` lets the already-present value win
(`env_file.py:129`), so loading managed first is what makes a page-rotated key
survive a reboot. The real process environment (compose `environment:`) still
beats both, by that same rule.

**Names the page will not manage:** a secret name set in the real process
environment at boot cannot be overridden by `managed.env` on the next boot, so
the page **refuses** to rotate or replace it and says why. Such names are
reported (names only) on the status board.

⚠ **Shadowing hazard, stated rather than hidden.** Rotating a name whose old
value lives in the read-only hand-written `.env` writes the new value to
`managed.env`, which shadows it. The **old value stays on disk** in `.env`,
inert — and becomes live again if `managed.env` is ever lost. The page says
this at rotation time, and `/healthz` reports `admin.shadowed_env_names`
(names only) until the operator removes the stale line by hand.

**NAS mounts** (`docs/deploy/nas.md` §5): `config/` becomes `rw`; the
hand-written `.env` and `secrets/` stay `:ro`. `managed.env` and
`admin_audit.jsonl` live under the existing state dir.

## 5. The write path

Every mutation, in order, under one process-wide lock:

1. **Out-of-band check.** sha256 of the file on disk must equal the hash the
   store last loaded or wrote. If not, refuse (`409`) with "registry.yaml was
   edited outside the console — reload from disk first". Never merge silently.
2. **Edit.** Apply the structured change to the `ruamel.yaml` tree. New
   `allow_inbound` values are always written as real booleans.
3. **Serialize** to candidate bytes.
4. **Validate** by running the real `load_registry` on those exact bytes (temp
   file in the same directory). Any `RegistryError` → refuse (`422`) with its
   message; nothing written.
5. **Parser agreement.** `yaml.safe_load(candidate_bytes)` (PyYAML, what the
   loader uses) must equal the edited `ruamel` tree converted to plain
   dicts/lists. A difference means the two parsers read the file differently —
   refuse, nothing written.
6. **Secrets first.** If the change mints or receives a secret, write
   `managed.env` (temp + fsync + rename, `0600`) and set `os.environ`.
7. **Backup** current `registry.yaml` to `registry.yaml.bak-<YYYYMMDD-HHMMSS>`
   (UTC; the runbook's convention).
8. **Write** registry: temp + fsync + `os.replace`, preserving mode.
9. **Swap** `holder.current` to the validated `Registry`.
10. **Audit** one line.

**Rollback.** A failure after step 6 restores the previous `managed.env` bytes
and `os.environ` entries; after step 8, restores the backup. If rollback itself
fails, `admin.memory_disk_diverged` goes true (§7) — the only state that
degrades `/healthz`.

**"Reload from disk"** runs steps 4–5 and 9 against the file as it is, then
records its hash. This also gives hand edits a hot-swap with no redeploy.

**Removal semantics.** Deleting an app or identity needs no new rule: queued
jobs it no longer grants are closed `unroutable` by the replay rule already in
`delivery.py` (472–514). The dispatcher must apply that check against
`holder.current` at dispatch time, not only at boot replay — the plan verifies
whether it does today.

## 6. The page

All `/admin/api/*` calls carry `Authorization: Bearer <admin key>` from page
memory. The key is never put in `localStorage`, `sessionStorage` or a cookie, so
a reload asks again; that also means no CSRF surface.

1. **Status board** (read-only): per app and identity — `key_configured`,
   `env_resolved`, `space_set`, `allow_inbound`, `inbound_locked`, routes,
   secret **source** (`managed` / `.env` / `process`), recent `DeliveryLog`
   outcomes. No values, no URLs.
2. **New app wizard**, the runbook's §1 decisions as steps:
   - *App id* → env-var name derived by convention
     (`CHAT_GATEWAY_API_KEY__<ID>`); `_`-prefixed ids refused.
   - *Identity* → pick existing or create. Creating opens the **webhook
     guide**: numbered steps for creating an incoming webhook in the Chat space,
     the warning that display name and avatar are fixed at creation, and a
     paste field. The pasted URL is validated for shape
     (`https://chat.googleapis.com/v1/spaces/<id>/messages` with `key` and
     `token` query parameters) and **never echoed back**; `space:` is derived
     from it.
   - *Routes* → `default` plus optional per-severity overrides, with CG-86's
     warning inline: severity picks the space.
   - *Inbound* → off by default; turning it on is the guard (item 4).

   On submit: mint (`"cgk_" + secrets.token_urlsafe(32)`, the same function
   `mint-key` uses), write and swap (§5), then the **one-time reveal panel**:
   the key with copy button and "this is the only time it is shown"; the gateway
   base URL; snippets for this app — `curl` via `--config -` (key out of argv),
   Python `GatewayClient`, and MCP client config if MCP is enabled; and a
   **Send test notification** button that posts `/v1/notify` with fixed plain
   text and polls `/v1/deliveries` until `delivered` or failed, stating that
   `202 enqueued` is not delivery.
3. **App detail:** edit identities and routes; **rotate key** (mint, swap,
   reveal once; the old key dies immediately — confirmed before); **replace
   webhook URL**; **delete** (typed app id).
4. **Inbound guard.** A *widening* change — `allow_inbound` false→true, adding
   `callback_url`, emptying `allowed_users` — shows hard rule #6's text and
   requires typing the app id; it is audited as `inbound_widened`. An app with
   `inbound_locked: true` cannot be widened from the page at all; the page says
   it is a file edit. `inbound_locked` is a new optional registry boolean
   (default `false`, non-boolean refused per hard rule #7); the page can never
   set or clear it.

**Out of scope:** creating webhooks programmatically (Google offers no API for
incoming webhooks); Pub/Sub, Chat-app or Cloud config; heartbeat check
management; displaying any stored secret.

## 7. `/healthz`

New `admin` block, present always (`enabled: false` when off):
`enabled`, `writes`, `refused`, `last_write_error` (authored message, via
`describe_exception`), `shadowed_env_names`, `memory_disk_diverged`.

Per-counter verdict, as this repo requires: `writes` and `refused` never
degrade — a guard working is not a fault (CG-12). `last_write_error` does not
degrade (the write was refused or rolled back cleanly). `shadowed_env_names`
neither degrades nor appears in `reasons` — it is an operator to-do, not a
fault. **Only `memory_disk_diverged` degrades `status`.**

## 8. Hard rules

| Rule | How it holds |
|---|---|
| #1 | The page never builds cards or reads message content. Test send is fixed plain text through `/v1/notify`. |
| #2 | Secrets leave the server only in the mint/rotate response, once. Audit, errors, `/healthz` and the status board carry names, never values or URLs. Webhook URLs are never echoed. Strict CSP on `/admin` (`default-src 'self'`, no inline script). Admin request bodies are not logged. |
| #3 | No Google-facing code is added. No ledger flag moves. |
| #4 | Admin key is its own credential: a tenant key gets `401` on `/admin/*`; the admin key gets `401` on tenant routes. Failed admin auth is rate-limited per client address. |
| #5 | §7. |
| #6 | Widening is guarded and audited; `inbound_locked` blocks it outright. |
| #7 | The page always writes `allow_inbound` explicitly as a boolean; `inbound_locked` defaults to the safe answer and is never coerced. |

**Residual, accepted with D3:** whoever holds the admin key controls every
unlocked app's outbound configuration. Mitigations: LAN-only bind, the key never
leaves the operator, the audit log.

## 9. Testing

Offline pytest, in the CG-88 style:

- `ruamel` round-trip: every file the store writes loads identically through
  PyYAML; comments and key order on untouched nodes survive.
- Rollback: a forced failure at each of steps 6–9 leaves file bytes, `managed.env`
  bytes, `os.environ` and `holder.current` unchanged.
- Out-of-band edit → `409`; reload-from-disk swaps and re-hashes.
- **Holder adoption:** for each consumer, a test that a swap is observed; and
  single-site mutations (a consumer reverted to a captured reference) go RED,
  each applied alone with `__pycache__` cleared.
- Auth isolation both directions; rate limit.
- Inbound guard: widening without confirmation refused; `inbound_locked`
  refuses widening even with confirmation; narrowing needs no confirmation.
- Secret exposure: a secret value appears in no response except the
  mint/rotate one, and in no audit line, log record or `/healthz` body.
- Boot order: a page-rotated key survives a simulated reboot with the old value
  still in the hand-written `.env`.

**UAT** (tester agent, browser mode, Playwright) on a local gateway with fake
adapters: wizard → reveal → test send; rotate; delete; widening blocked on a
locked app; reload-from-disk after a hand edit.

## 10. Documentation and rollout

**This repo** (in the CG-90 PR):
- `docs/registering-an-app.md` — an "Or use `/admin`" path at the top; the
  manual runbook stays as the fallback.
- `docs/deploy/nas.md` — the mount change, `managed.env`, the two new env
  names, admin-key minting, and §6's shadowing hazard.
- `docs/integration-guide.md` — the `/healthz` `admin` block.
- `CLAUDE.md` — one status bullet pointing here; nothing restated.
- `pyproject.toml` — `ruamel.yaml`.

**Homelab repo** (`D:/prj/homelab`, its own branch and PR — D7):
- `nas/services/chat-gateway.md` — Overview and Deployment updated for the
  console, the `rw` `config` mount and `managed.env`, within the four-header
  template (`nas/services/_TEMPLATE.md`).
- `SECRETS.template.md` — a row for `CHAT_GATEWAY_ADMIN_KEY`, and a note that
  page-managed secrets live in `<state_dir>/managed.env` (a file to restore).
- `nas/DASHBOARDS.md` — an admin console entry.

**Box rollout — an operator action, not discharged by merge:**
1. Set `inbound_locked: true` on `aitrader` in the box's registry **before**
   enabling the console.
2. Mint the admin key; install it over stdin into the hand-written `.env`.
3. Change the `config` mount to `rw`.
4. Rebuild (`nas.md` §4 — `app.redeploy` alone does not rebuild), set
   `GATEWAY_ENABLE_ADMIN=1`, redeploy.
5. Verify `/healthz` shows `admin.enabled: true`, then open `/admin`.
6. Record the run in `nas.md` §10.
