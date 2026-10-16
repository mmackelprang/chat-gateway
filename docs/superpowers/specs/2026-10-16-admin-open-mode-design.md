# Admin console open mode — no sign-in on a LAN-only box — design

**Date:** 2026-10-16 · brainstormed with the user · branch `feat/CG-91-admin-open-mode`
**Baseline:** `main` at `aeb210b`; suite count measured in §9, not copied from
`CLAUDE.md`.

**Row this spec produces:** **CG-91** — an operator-chosen posture under which
`/admin` asks for no credential at all. Companion row, specified separately:
**CG-92**, the console's management-surface redesign (keys and webhooks across
apps that share identities), brainstormed in the same session.

**No ⚠ verification-ledger flag is cleared, added or reworded by anything in this
document, and none may be by the PR it produces.** Nothing here touches
`adapters/`.

---

## 1. Problem

CG-90's spec §6 keeps the admin key in the page's memory for the life of one
tab: *"a reload asks again"*. That was deliberate — no browser storage, no
cookie, no CSRF surface — and it costs the operator a trip to the key file
(`~/.chat-gateway/admin-key` on the dev box, per `docs/deploy/nas.md` §10) on
every reload, every new tab and every device. The console is published on a
LAN-bound port (CG-55) of a home NAS, and the user's statement is that it
*"will never be exposed to anybody except me"*. They asked for the sign-in to
go.

## 2. Decision (user, 2026-10-16)

| # | Decision | Chosen | Declined, and what it would have given |
|---|---|---|---|
| D1 | How the console stops asking for the key | **Open mode:** an explicit posture flag turns the bearer check off and the page opens straight to the console. Absence of the flag keeps today's behaviour. | *Remember the key in the browser* (recommended in the session; declined): one paste per browser profile into `localStorage`, auth stays on, nothing else on the LAN could write. *Both*: the flag plus remember-me when auth is on; most code and documentation. |

⚠ **The cost was stated before the choice and is recorded plainly.** In open
mode **every device that can reach the port** — on the home LAN, that includes
guests' phones and IoT devices — can perform every console action: mint a key
for any app (and so send as every identity that app holds), rotate any app's key
including `aitrader`'s (its `inbound_locked` guards spaces, not its key — a
rotation silences the real-money tenant's alerting until its config is updated),
change routes, and replace or delete webhooks. **It still cannot read a
secret**, because the console never shows one (hard rule #2). The typed
confirmations (428) remain in force but they are accident guards, not
authentication: a script sends the id. What is left protecting the console is
the LAN bind (CG-55 — the port is published on the LAN address, so a tailnet
peer cannot reach it) and the audit trail, which §3 makes attributable by peer
address where the box preserves it (§7 verifies that). The user accepted this
with the threat model stated above.

## 3. Mechanics

**One new env-var NAME** (hard rule #2 — values in the runtime env):

| Name | Values | Default |
|---|---|---|
| `GATEWAY_ADMIN_AUTH` | `key` — today's bearer check · `open` — no credential | `key` |

- **Absence is `key`** (hard rule #7: a security-relevant value defaults to the
  safe answer). **Any other written value refuses to boot** — `RegistryError`,
  exit 2, naming the variable and the two accepted values — rather than being
  coerced (rule #7's second half). `GATEWAY_ENABLE_ADMIN` keeps its existing
  `== "1"` test; this spec does not change it.
- **Read from the PROCESS environment only**, beside `GATEWAY_ENABLE_ADMIN` at
  `__main__.py:52`, **before** `managed.env` or the hand-written `.env` loads.
  A `GATEWAY_ADMIN_AUTH=open` line in either file is therefore ignored and the
  console stays in `key` mode — the safe direction, and the same hazard note the
  runbook already carries for the sibling flag. *My call, after the builder
  check:* the first draft read it after the env files "so either place works",
  and in the same breath claimed a stale `.env` could not open the console. Only
  one of those is true. The compose is captured into the homelab repo; a file
  that can open the console must be the one that is captured.
- **In `open` mode `CHAT_GATEWAY_ADMIN_KEY` is not required and, if present,
  not consulted.** The fail-closed boot check (`__main__.py:138-141`) applies
  only in `key` mode. Boot prints one stderr line in open mode:
  `admin: WARNING — GATEWAY_ADMIN_AUTH=open: /admin checks no credential;
  anything that can reach the port can use the console.` stderr, so it survives
  a `| jq` pipeline, the convention `registry: WARNING` already follows.
- **`require_admin` in open mode** skips the bearer comparison, the failure rate
  limiter and the rule-#4 "admin key equals a tenant key" check (there is no
  admin key in play). It keeps `Cache-Control: no-store` on every answer.
- **`require_admin` in key mode changes in exactly one way:** a request that
  presents **no** `Authorization` header is still a `401`, but **no longer counts
  toward the rate limiter.** §4's page probe is such a request, and without this
  five reloads in a minute would have answered the operator's *correct* key with
  `429` — a regression the builder check caught. A missing header is not a
  guess; the limiter exists to throttle guesses, and `Bearer wrong` still counts
  (`test_failed_logins_are_rate_limited` is unchanged). *My call.*
- **A same-origin guard runs on every `/admin/api/*` request, in BOTH modes.**
  In `key` mode the bearer header is already what stops a cross-origin page
  driving the console; in `open` mode nothing else would. The rule, in the
  fail-closed-on-evidence shape `mcp.py`'s `_check_origin` uses:
  - if `Sec-Fetch-Site` is present and is not `same-origin` or `none` → `403`;
  - if `Origin` is present and its host:port is not the request's `Host` → `403`;
  - otherwise accept. A non-browser client (curl, a script on the LAN) sends
    neither header and is accepted — that is the posture the user chose, not a
    gap. Scheme is deliberately not compared, so a TLS-terminating proxy in front
    of the gateway would not break the page; the netloc comparison is what
    defeats a page on another origin.
  The 403 is counted through `refuse()` like every other refusal and its
  category lands in `admin.last_write_error`; the message names the header that
  failed and never echoes its value.
- **Audit lines gain two fields, in both modes:** `client` — the peer address
  as the container sees it, `request.client.host` — and `auth` — `"key"` or
  `"open"`, what authenticated the action. With no credential, the address is
  the only attribution left; and after a posture flip the append-only trail
  holds lines from both eras, which without `auth` would read identically.
  `actor` stays `"admin"`: it names the role exercised, not who held it. Never
  a value, never a URL; the line stays names-only otherwise. *My call; the two
  additions beyond the literal ask, included because removing the credential
  removes the actor and the audit should say what it still knows.*
  ⚠ **`client` is a LAN address only if the box's port publish preserves the
  peer** (Docker's DNAT does; a userland proxy would show the bridge gateway
  instead). That is a property of the box, unreadable from here, so §7's rollout
  **checks it** rather than this document asserting it.

## 4. The page

- On load the page requests `GET /admin/api/state` **with no `Authorization`
  header**. `200` → open mode: the login section is never shown and the console
  renders; `401` → `key` mode: the login section shows exactly as today. No new
  endpoint, no posture probe to keep in sync with the server.
- `api()` adds `Authorization` only when a key is held. In open mode it holds
  none for the life of the tab. A `401` arriving in open mode (an operator
  flipped the posture and restarted while a tab was open) falls into today's
  `signOut` path and shows the login — the correct outcome.
- The header shows the posture honestly: a pill reading **`open · no sign-in`**
  beside the registry hash in open mode; nothing new in key mode. Rule #5's
  spirit applied to the page: a console that silently has no lock reads exactly
  like one that does.
- Nothing is stored. `test_the_admin_key_is_never_persisted_by_the_page` stays
  as it is and stays green. The CG-92 redesign restyles this shell; this row
  changes the minimum.

## 5. `/healthz`

The `admin` block gains **`auth`**: `"key"` or `"open"`, present whenever
`enabled` is true. **It does not degrade `status` and does not appear in
`reasons`** — a chosen posture is not a fault, the same per-field verdict this
repo recorded for `suppressed_opt_out` (CG-12) and for `admin.writes`. It is
reported so that a reader of `/healthz` cannot mistake an open console for a
locked one.

## 6. Hard rules

| Rule | How it holds |
|---|---|
| #1 | Untouched — no card, no schema. |
| #2 | No new secret. The flag is a posture, not a credential, and may live in the compose. Refusal messages name headers, never their values. Audit gains an address, never a value. |
| #3 | No Google-facing code; no ledger flag moves. |
| #4 | Per-app auth on tenant routes is unchanged. The admin surface's *own* credential becomes optional by the operator's explicit choice; a tenant key still gets `401` on `/admin/*` in `key` mode, and in `open` mode no key of any kind is read there. |
| #5 | §5. |
| #6 | Unchanged: widening still needs the typed id (428); `inbound_locked` still refuses outright. Open mode removes authentication, not guards. |
| #7 | `GATEWAY_ADMIN_AUTH` defaults to `key`; any value other than the two accepted ones refuses to boot. |

**Relation to CG-90's D2.** D2 chose *"dedicated admin bearer key, LAN-bound
port only"* and declined Google sign-in and a proxy header. This row does not
reopen those: it adds a posture under which the LAN bind is the whole lock. The
CG-90 spec's D2 row and §6's first paragraph get a dated annotation pointing
here and are **left standing**, this repo's convention for a decision that was
right when made.

## 7. Configuration and rollout (operator action — merge is not in effect)

1. Add `"GATEWAY_ADMIN_AUTH": "open"` to the compose `environment:` in
   `docs/deploy/nas.md` §5 and on the box, beside `GATEWAY_ENABLE_ADMIN`.
2. Rebuild (§4 — `app.redeploy` alone does not rebuild) and redeploy.
3. Verify `/healthz` shows `admin.auth: "open"`, then open `/admin` and see the
   console with no sign-in and the `open · no sign-in` pill.
4. **Check the attribution claim on the box:** click *Reload from disk* (a
   harmless write) and read the new `admin_audit.jsonl` line. It must carry
   `auth: "open"` and a `client` that is the browser's LAN address. If `client`
   is the Docker bridge gateway instead, the port publish is not preserving the
   peer: record that in §10 and in the CG-90 subsection, because §2's "audit
   trail" mitigation is then weaker than written.
5. Optionally remove `CHAT_GATEWAY_ADMIN_KEY` from the box `.env` and from
   `~/.chat-gateway/admin-key` on the dev box. Harmless if left: unread.
6. Record the run in `docs/deploy/nas.md` §10.

**Homelab repo (`D:/prj/homelab`, its own PR):** `SECRETS.template.md`'s
`CHAT_GATEWAY_ADMIN_KEY` row gains *"unused while `GATEWAY_ADMIN_AUTH=open`"*;
`nas/services/chat-gateway.md` notes the posture.

## 8. Documentation (this repo, in the CG-91 PR)

- This spec.
- `docs/superpowers/specs/2026-10-15-admin-console-design.md` — dated
  annotations on D2 and §6 ¶1, left standing.
- `docs/deploy/nas.md` — CG-90 subsection: a third row in the env-var table
  (`GATEWAY_ADMIN_AUTH` — compose `environment:`, **not** `.env`, for the same
  read-before-the-env-file reason as `GATEWAY_ENABLE_ADMIN`; set in `.env` it is
  silently ignored and the console stays in `key` mode); the §5 compose block;
  the rollout list above including the attribution check; the stated cost from
  §2 in one sentence.
- `docs/integration-guide.md` — `admin.auth` row in *Durability counters at
  `/healthz`*, verdict "no".
- `docs/registering-an-app.md:15` — *"(LAN port, admin key)"* becomes *"(LAN
  port; admin key, or none under `GATEWAY_ADMIN_AUTH=open`)"*.
- `CLAUDE.md` — one status bullet under the CG-90 bullet pointing here; the
  Layout line's test count re-measured.
- `scripts/admin_uat_server.py` — honours `GATEWAY_ADMIN_AUTH` so the browser
  UAT below can run both postures.

## 9. Testing

Offline pytest, CG-88 style, with the suite count re-measured here before and
after. **Baseline on `main` at `aeb210b`, measured 2026-10-16 with
`.venv/bin/python -m pytest -q` (Python 3.13.13, WSL): 686 passed, 1 failed.**
The failure is pre-existing and unrelated to this row —
`test_docs_and_tests_carry_no_real_identity` flags a LAN address literal at
`docs/deploy/nas.md:1532`, introduced by #82's §10 entry; this PR scrubs it in
its own commit so the gate is green rather than tolerated. (`CLAUDE.md`'s
*"680 passing, 7 skipped"* was measured on the Windows dev box, where
platform-conditional tests skip; the two counts describe two machines.)

- **Posture parsing:** absent → `key`; `open` → open; `KEY`, `yes`, `1`, `true`
  → `RegistryError` at `build_runtime`. **Process env only:**
  `GATEWAY_ADMIN_AUTH=open` written in the file `CHAT_GATEWAY_ENV_FILE` names,
  with nothing in the process env, leaves the console in `key` mode.
- **Limiter:** five no-header requests from one host, then the correct bearer →
  `200`; five `Bearer wrong` requests, then the correct bearer → `429` (the
  existing test, unchanged).
- **Open mode boot:** `GATEWAY_ENABLE_ADMIN=1`, `GATEWAY_ADMIN_AUTH=open`, no
  `CHAT_GATEWAY_ADMIN_KEY` → `build_runtime` wires the console. `key` mode with
  no key still raises (existing test keeps passing).
- **Open mode requests:** no header → `200`; a wrong bearer → still `200`
  (nothing is compared); `Origin: http://evil.example` → `403` on GET and POST;
  `Sec-Fetch-Site: cross-site` and `same-site` → `403`; `same-origin` and
  `none` → `200`; `Origin` whose netloc equals `Host` → `200`. A widening write
  without `confirm_app_id` is still `428`; an `inbound_locked` write is still
  `403` — guards survive the posture.
- **Key mode unchanged:** every existing `test_admin_api.py` and
  `test_admin_page.py` test passes unmodified; plus the guard in key mode: a
  valid bearer **with** a foreign `Origin` → `403`.
- **Audit:** every line written in either mode carries `client` and `auth`
  (`"key"` or `"open"` to match the posture under test); a secret value appears
  in no audit line, log record or `/healthz` body (the existing exposure test,
  extended to both new fields).
- **`/healthz`:** `admin.auth` is `"key"` or `"open"`; `status` is `ok` in both.
- **Page (string tests, the file's existing style):** `admin.js` sends no
  `Authorization` header when no key is held; the initial load probes
  `/admin/api/state` before deciding whether to show the login; the four storage
  APIs are still absent.
- **Single-site mutations, each applied alone with `__pycache__` cleared:**
  (1) the guard dropped → the `Origin` tests go RED; (2) the posture default
  flipped to `open` → the absent-flag test goes RED; (3) the coercion made
  lenient → the `yes`/`true` tests go RED.

**UAT** (tester agent, browser mode, Playwright, against
`scripts/admin_uat_server.py`): in open mode, loading `/admin` shows the
console and the pill with no login form; a create → reveal → test-send round
trip works; in key mode the login form shows and the flow is unchanged.

## 10. Left to the builder

The exact shape of the guard function and where it sits in `admin.py`; how the
peer address reaches `audit.record` (a dependency return value is the obvious
route — a `ContextVar` set in a threadpool dependency does not survive into the
endpoint's thread); the pill's class in `admin.css`; test fixture layout for the
two postures.
