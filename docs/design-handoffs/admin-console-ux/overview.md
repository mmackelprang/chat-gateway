# Admin console — a management surface for many apps sharing identities

**Task:** CG-91 · **Date:** 2026-10-16 · **Author:** Designer agent
**Scope:** the `/admin` console shell and views *after* sign-in. The login screen is
being decided separately and is not designed here.
**Companion:** `mockup/index.html` in this directory — a clickable, throwaway
static mockup of the recommended option with fake data. Open it from `file://`.

## 0. What exists, and what this follows

This project keeps **no design handoffs** — there is no `docs/design-handoffs/`
anywhere in the repo, and no Claude Design package. The only visual language is
the shipped console itself: `src/chat_gateway/static/admin/admin.css` (38 lines
of tokens and primitives) plus the structure `admin.js` renders. Per my own
operating rules, when handoffs are absent I say so once and then propose options
rather than inventing a visual world alone. That is what §2 does.

**Declaration.** This proposal `follows` `admin.css` — its tokens (`--bg --fg
--muted --line --accent --warn --err --card --ok`), system-ui at 15px, 6/8 px
radii, `prefers-color-scheme` dark mode, the `.pill` / `.card` / `.secret` / `pre`
primitives — and `extends` it with three tokens (§3.9) and a handful of new
primitives (status dot, matrix cell, dialog, callout). It `deviates` from the
shipped page in exactly one visual-language respect, argued in §3.6: typed
confirmations move from a card prepended into the main view (`admin.js:264`) to a
native `<dialog>`.

Everything here is designed within the data `state()` returns (`admin.py:486-515`)
and the nine endpoints `admin.py:518-765` expose. Where a better design would
need more, it is an **open question** in §5 with the degraded form stated.

The spec's decisions D1–D7 (`docs/superpowers/specs/2026-10-15-admin-console-design.md`
§2) are taken as given. Nothing here relitigates write scope, apply model, auth
model, or what the lock covers.

---

## 1. Current state, from the multi-app / shared-resource point of view

The page is a correct, careful v1 of a **two-table status board** (spec §6.1). Its
weakness is structural: both tables are flat, and the thing the operator asked
about — *resources shared between apps* — is a relationship, so it is never
drawn. Each finding below is cited; severities use the P0–P3 scale (P0 blocks a
task, P1 causes real difficulty, P2 annoyance with a workaround, P3 polish).

### 1.1 The shared resource is invisible where decisions are made

| # | Finding | Where | Sev |
|---|---|---|---|
| F1 | **Nothing shows which apps hold an identity.** The identities table has Identity / Display / Space / Webhook / Secret source / actions — no holders column. The data to invert is already on the page (`state.apps[*].identities`), and the page *does* invert it once, but only for locked holders (`lockedHolders()`, `admin.js:122-129`), and only to disable one button. | `admin.js:143-161`, `:170-171` | P1 |
| F2 | **Nothing shows who else posts into a space.** `space` renders as a raw `spaces/XXXX` string per identity row (`:154`); two identities in one room appear as unrelated rows. The server's most important safety rule is *about spaces* (`locked_space_violations`, `admin.py:137-163`; `apps_for_space`, `registry.py:256-267`), yet the page has no space concept at all, and never says "this room is locked". | `admin.js:154` | P1 |
| F3 | **Deleting an identity asks for a typed name, then the server refuses.** `deleteIdentity` goes straight to `typedConfirm` (`:393-394`); if any app holds the identity the server answers 409 "still granted to: …" (`admin.py:742-745`). The operator types a name to confirm something that cannot happen. The page could know in advance. | `admin.js:393-398` | P1 |
| F4 | **Grant checkboxes show bare names.** Granting an identity to an app is the moment sharing happens, and the checkbox list (`:193-194`) shows neither the identity's room nor "also granted to X". For an inbound app this is precisely the widening the server guards (`widening()`, `admin.py:86-91`): the operator learns about it from a 428 after Save, not before. | `admin.js:193-194` | P1 |
| F5 | **Route selects name identities without rooms, and the CG-86 warning is static.** The warning (`:203`) is printed unconditionally; the selects (`:195-197`) show identity names only. Whether *this app's* routes actually span two rooms is computable from `routes → identity → space` and never computed. | `admin.js:195-204` | P2 |
| F6 | **Ungranting an identity can silently break routes.** The loader refuses a route that points at an identity the app does not hold (`registry.py:452-457`), so unchecking a granted identity that is also a route target produces a 422 at Save with the loader's message, rather than a pre-write explanation. | `admin.js:229-232` | P2 |

### 1.2 Cells that pack facts, and facts that are missing

| # | Finding | Where | Sev |
|---|---|---|---|
| F7 | **"API key" packs three facts in one cell** — configured-or-not, source, and a colour — as `"key set (.env)"` (`:140`). On the detail page the same facts are a muted line (`:280-281`). Neither says what a missing key *means* (the app cannot authenticate, `auth.py:33-36` via the runbook §0) or what to do about it. | `admin.js:140`, `:280-281` | P2 |
| F8 | **"Last delivery" is a bare status word with no time** (`:141`), though each record carries `ts`, `kind`, `title`, `detail` (`delivery.py:104-105`) and `state()` hands the page five of them (`admin.py:499`). "delivered" with no "when" cannot answer "is this app alive?". No page-side reason exists for the loss. | `admin.js:141` | P2 |
| F9 | **The identities table's "Webhook" column is wrong for tier-2 identities.** `env_resolved` for `mode: app` means `GOOGLE_APPLICATION_CREDENTIALS` is set (`registry.py:154-157`), not that a webhook exists; the header says "Webhook" regardless (`:171`) and the row offers no replace action (`:146-149`) without saying why. | `admin.js:146-149`, `:171` | P3 |
| F10 | **Refusals the page can predict are discovered by clicking.** "Rotate key" is always enabled (`:286`) and "Replace webhook" is enabled unless locked (`:147-149`), but both are refused with 409 when the secret is set in the process environment (`managed_name`, `admin.py:322-325`). `key_source` / `secret_source` are already on the page. | `admin.js:286`, `:147-149` | P2 |

### 1.3 Flows that lose the operator's place

| # | Finding | Where | Sev |
|---|---|---|---|
| F11 | **The new-app wizard bounces.** Step 2 is a button to `newIdentity` (`:314-315`); creating the identity calls `newApp()` unconditionally (`:351`), which `view()`-replaces the DOM (`:39`, `:354`) — the half-typed app id, grants and routes are gone, and the new identity is not pre-checked. If the operator arrived at "New identity" from the nav rather than from the wizard, they are still dropped into a blank New-app form they did not ask for. | `admin.js:314-315`, `:351-354` | P1 |
| F12 | **Typed confirmations are prepended into the main view**, not shown as a dialog (`:264`). There is no backdrop, no Escape, no focus return, and the card lands above whatever view is showing, so on the board it appears above the "Apps" heading with the tables still live underneath. | `admin.js:256-267` | P2 |
| F13 | **Row actions are inconsistent between the two tables.** Identity rows carry up to three inline buttons including a red Delete (`:157-160`); app rows carry one "Manage" (`:142`). The destructive identity action is one click from the board; the destructive app action is two clicks and a typed id. Same class of object, different distance to danger. | `admin.js:142`, `:157-160` | P2 |
| F14 | **The 409 message hard-codes two different recoveries as one sentence** — "Open 'Apps & identities' to refresh, or 'Reload from disk' if registry.yaml was edited by hand" (`:69`). They fix different problems (page stale vs. server stale, spec §5 steps 1 and "Reload from disk"); the operator has to diagnose which. The form is also not kept. | `admin.js:69` | P2 |
| F15 | **"Reload from disk" sits in the nav as a peer of "New app"** (`index.html:24-29`). It is a recovery operation that re-validates and hot-swaps the file (spec §5), appropriate after a hand edit; placed as primary navigation it invites casual clicks. The nav also has no current-location state. | `index.html:24-29` | P3 |

### 1.4 States

| # | Finding | Where | Sev |
|---|---|---|---|
| F16 | **No loading state.** `refresh()` awaits `/admin/api/state` (`:88-89`) with nothing rendered meanwhile; after sign-in the console section appears empty until the board paints. | `admin.js:88-97` | P3 |
| F17 | **No empty state.** Zero apps or zero identities renders two tables with headers and no rows (`:163-172`). A fresh deployment's first visit — the runbook's whole audience — gets no "start here". | `admin.js:163-172` | P2 |
| F18 | **Global warnings are not attached to the rows they concern.** Shadowed env names go to a top banner (`:92-96`); `inbound_defaulted` to a paragraph above the table (`:165`). Neither marks the affected app row, so the operator reads a name at the top and scans for it below. | `admin.js:92-96`, `:162-165` | P3 |
| F19 | **One toast, no dismiss, errors and successes in the same slot** (`:38`), cleared on any nav click (`:478-481`). A long 428 or 409 message in a single `<p>` is the only record of what was refused. | `admin.js:38` | P3 |
| F20 | **Phone:** `.table-wrap table { min-width: 640px }` (`admin.css:25`) forces horizontal scroll on the 7-column apps table; the identities table has 6 columns plus three inline buttons. | `admin.css:25` | P2 |

### 1.5 What is already right (keep it — §4 lists it fully)

- Every byte of registry content reaches the DOM through `textContent` (`admin.js:1-4`, `el()`/`toNodes()`).
- The write path carries the sha the page saw, and **nothing after a successful mutation may throw** (`admin.js:99-118`) — a minted key always reaches `reveal()`.
- Locked apps' identities are sent back in their exact order (`:222-232`), because the server compares ordered lists (`admin.py:560-561`).
- `callback_url` / `unreachable_message` use absent-means-unchanged (`:177-188`, `:213-218`; `admin.py:219-226`).
- The clipboard fallback is honest about the plain-HTTP LAN (`:401-413`).
- The reveal panel's content — one-time warning, `curl --config -`, Python, MCP gated on `mcp_enabled`, and a test send that polls for a *terminal* status (`:415-462`) — is exactly right.

### 1.6 Heuristic baseline (Nielsen, 0–4; Operate surface, all ten apply)

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Visibility of system status | 2 | F8, F16; no active nav state |
| 2 | Match system / real world | 3 | Operator vocabulary is right; "space" is a raw id (F2) |
| 3 | User control and freedom | 2 | F11 (lost draft), F12 (no Escape) |
| 4 | Consistency and standards | 2 | F13; confirm UI differs from platform dialogs |
| 5 | Error prevention | 2 | F3, F4, F6, F10 — server guards exist, page does not pre-empt |
| 6 | Recognition rather than recall | 2 | F1, F2, F4 — relationships must be remembered |
| 7 | Flexibility and efficiency | 2 | No keyboard path beyond Tab; no filter |
| 8 | Aesthetic and minimalist | 3 | Restrained and honest; cells over-packed (F7) |
| 9 | Error recovery | 3 | Server messages are good; F14 muddles the fix |
| 10 | Help and documentation | 3 | Webhook guide inline; rule #6 quoted; CG-86 warning present |
| | **Total** | **24/40** | Acceptable — the foundation is sound, the IA is the gap |

Cognitive-load checklist failures: *working memory* (F1/F2/F4 — the operator carries
the holders map in their head), *context switch* (F11), *inconsistent pattern*
(F13). Three of eight — moderate.

---

## 2. Information-architecture options

Three honest shapes. All three keep the nine endpoints, the write path, and the
reveal panel; they differ in what the home screen *is*.

### Option A — App-centric, tightened

Today's two tables, repaired: a "Granted to" column on identities, "Room" shown
beside each identity in grants and routes, delivery time added, pre-disabled
buttons for predictable refusals, a real dialog, a return ticket for the wizard.

- **Buys:** smallest change; builder touches `board()`, `appFields()`,
  `typedConfirm()`, `newIdentity()`. Every finding in §1 except F2 can be closed.
- **Costs:** the space stays a string. Who-posts-where and which-room-is-locked
  remain things the operator reconstructs by reading two tables. At six apps and
  eight identities that reconstruction is still a few seconds of work per
  decision; the console was built to remove exactly that kind of work.

### Option B — Room-centric (space → identities → holders)

Home is a list of rooms. Each room card lists its identities, and under each
identity the apps that hold it. Apps are reached through the identities they hold.

- **Buys:** the lock model becomes literal — a locked room is one shaded card.
  Shared identities are obvious (two holders under one identity). CG-86 is
  explained by the structure itself.
- **Costs:** the operator's *job* starts from the app — register, mint, rotate,
  check deliveries — and an app with identities in two rooms (aitrader) appears
  in two places. Apps with no identity and identities with no room need an
  "unplaced" bucket. The key lifecycle, the most frequent task, is two levels down.

### Option C — Grant matrix + inspectors (recommended)

Home is **one matrix**: rows are apps, columns are identities **grouped under
their room**. A cell says whether the app may send as that identity and which
severities route there. A locked room's column group is shaded and labelled.
Clicking a row header opens the **app inspector**; a column header opens the
**identity inspector**; a room header opens the **room inspector**. Every
inspector is a full-width route with a breadcrumb back to the board. The three
lifecycle flows (new app, new identity, replace webhook) are separate routes
with a return ticket to where they were launched from.

- **Buys:** every shared resource is a column with two or more marks — visible
  without reading. Every room is a column group — the lock model and the CG-86
  room-split are drawn, not described. The app remains the row, so the key
  lifecycle stays one click away. Deleting an identity with holders is visibly
  impossible before anyone types. All of it is computed client-side from
  `state()` as it is today (§5 Q1).
- **Costs:** a matrix widens with identities; at ~15 columns it needs horizontal
  scroll on a laptop. On a phone it must collapse to stacked app cards with
  identity chips (designed in §3.8). The matrix is also a new primitive the
  builder has to get right for keyboard and screen-reader use (§3.7). At the
  live scale — six apps, a handful of identities, two shared — it is the densest
  honest picture available, and it degrades to Option A's table below 720px.

**Recommendation: C.** The operator's own words were "managing multiple apps with
potentially shared resources"; a matrix is the one view in which a shared
resource is a *shape* rather than a fact to look up. B optimises for the lock
model and C gets the lock model for free as a column shading. A is the right
fallback if the builder's budget is a single afternoon, and §3 is written so
that each inspector stands alone — A is C with the matrix replaced by the two
repaired tables.

---

## 3. The recommended design

> **Decided 2026-10-16** — Option C was chosen; the authoritative spec is
> `docs/superpowers/specs/2026-10-16-admin-console-ux-design.md`. Where this
> section and the spec differ, the spec wins. Two later user decisions are
> folded in below as dated amendments: D5 (bounded-height matrix + collapsible
> rooms) and D6 (avatar picker, remembered in the registry). The new-identity
> stepper (§3.5) now opens with the avatar picker; the gateway serves the
> bundled icons for the page's own rendering, but the URL the picker hands the
> operator to paste into Chat is the **public GitHub raw URL** (Google fetches
> it; the gateway is LAN-bound — spec §5, ruling R1). The gallery link is gone
> from the guide.

Mode: **Operate**. Familiar controls, restrained colour, density where the
operator benefits, brand in the details. No motion beyond a 150 ms focus/hover
transition and the dialog's fade. One family (system-ui), as today.

### 3.1 Shell and navigation

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ chat-gateway admin   registry 91bbcb1c…   6 apps · 8 identities · 6 rooms    │
│ [Board] [New app] [New identity]              [Filter apps and identities /] │
│                                                            Registry ▾ (menu) │
├──────────────────────────────────────────────────────────────────────────────┤
│ ⚠ banner row (only when something needs the operator)                        │
│ Board › App aitrader                                   ← breadcrumb on routes │
│ …view…                                                                       │
└──────────────────────────────────────────────────────────────────────────────┘
```

- **Routes live in the URL hash** — `#/`, `#/app/<id>`, `#/identity/<name>`,
  `#/room/<space-id>`, `#/new-app`, `#/new-identity`, `#/identity/<name>/replace`,
  `#/reveal` (in-memory only; a reload of `#/reveal` lands on the board — the
  key is gone, and the page says so). Hash routing gives Back/Forward and a
  bookmarkable deep link for free, stores nothing (the no-browser-storage rule
  at `admin.js:1-2` is about the key and is untouched), and after sign-in the
  page resumes the hash it was opened on. App and identity ids are not secrets;
  they already appear on `/healthz`.
- **Three nav items**, with a current-location state: Board, New app, New
  identity. **"Reload from disk" moves into a `Registry` menu** at the right of
  the header beside the sha: *Refresh view* (GET state), *Reload from disk* (POST
  reload, with its one-line explanation), *Copy sha*. Rare operations, one click
  further, named by what they do.
- **Banner row** carries only operator to-dos: shadowed env names, apps still on
  the loader's default, the "saved but view refresh failed" warning (`admin.js:112-116`).
  Each banner names the rows it concerns **and those rows carry the same mark**
  (F18).
- **Notices** replace the single toast: a stack at the top-right of `<main>`,
  `role="status"` for successes (auto-dismiss 6 s), `role="alert"` for refusals
  (stay until dismissed, with a Dismiss button). Refusals also render **inline at
  the control that caused them** (§3.6); the notice is the record, the inline
  callout is the explanation.

### 3.2 The board — grant matrix

```
                  │ Room spaces/AAQAfam01        │ spaces/AAQApmt03 │ Room spaces/AAQAtrdA1 · spaces/AAQAtrdR2  LOCKED by aitrader │ …
                  │ pm-familyworkspace  family-… │ pmtrader-alerts  │ aitrader-alerts    aitrader-reports                            │
──────────────────┼──────────────────────────────┼──────────────────┼────────────────────────────────────────────────────────────────┼──
aiteam-harness    │ ● default                    │                  │                                                                │
  inbound off · key ok · delivered 2 d ago
agent-mcp         │ ●                   ●        │                  │                                                                │
  inbound off · key ok (process) · delivered 2 d ago
aitrader  LOCKED  │                              │                  │ ● alert            ● warning info                              │
  inbound off · key ok · delivered 12 min ago
pmtrader          │ ● default                    │ ● alert          │                                                                │  ⚠ routes span 2 rooms
  inbound off (defaulted) · KEY MISSING · no deliveries
```

- **Row header** = app id, pills (`inbound on/off`, `locked`), and a one-line
  status strip: key state (§3.3), last delivery as *status + relative time*
  (`ts` from `recent_deliveries`, F8), and any row mark (shadowed key, defaulted
  inbound, routes spanning rooms). Click → app inspector.
- **Column group header** = room: `spaces/<id>` plus, as its human proxy, the
  display names of the identities in it (the gateway knows no room name — §5 Q3).
  Locked rooms are shaded with `--locked-bg` and carry a `locked by aitrader`
  pill. A final group **"No room recorded"** holds identities with `space: ""`,
  with a short note: *cannot route inbound; not covered by any lock*
  (`registry.py:258`, `nas.md:601`). Click → room inspector.
- **Column header** = identity name, display name, and a status dot (webhook
  ready / not resolvable / tier-2). Click → identity inspector.
- **Cell** = a filled dot when the app may send as the identity, plus small
  chips for each severity routed there (`default`, `alert`, `warning`, `info`).
  An empty cell is empty. Cells are **not** toggles — writes happen in the
  inspector with an explicit Save, so the 428 flow and the ordered-identities
  rule keep one home. Hovering or focusing a cell shows the sentence it encodes:
  *"pmtrader may send as pm-familyworkspace · default route"*.
- **A shared identity is a column with two or more dots.** No legend needed
  beyond the one-line key under the matrix: *filled dot — may send as · chips —
  severities routed there · shaded group — room locked by an inbound_locked app*.
- **Filter** (`/`) narrows rows and columns by substring on app id, identity
  name, display name, or room id; the matrix hides non-matching rows and columns
  and says *"3 of 6 apps · 2 of 8 identities match 'trader'"*.
- Below the matrix, nothing else on the board. The two tables are gone; their
  facts live in the inspectors.
- **Amended 2026-10-16 after the user reviewed the mockup (spec D5, D6).** The
  matrix scrolls in its own viewport-bounded region with a sticky app column and
  sticky room/identity headers, so its horizontal scrollbar is always on screen
  (the user: the bottom scrollbar was *"often off the page"*). Every room group
  **collapses to one narrow column** — a per-app "sends into this room" dot,
  the severities routed there, the room's lock shading — with a per-room toggle
  and *Expand all / Collapse all*; **all collapsed by default**, the rooms
  holding the last-opened app's grants expanded on return; remembered for the
  session only, no storage. Space on a focused room header toggles it; Enter on
  a collapsed column expands it. The identity header also carries the identity's
  **avatar mark** (bundled icon, or a neutral dashed circle for custom/none).
  The ASCII sketch above predates this; `mockups/index.html` is current.

### 3.3 App inspector — `#/app/<id>`

Sections in order, each a `fieldset`-style card with a heading; one form, one
**Save** button pinned at the bottom (sticky on phone), disabled until something
changed, with a *"Unsaved changes"* note.

1. **Header:** app id, pills, env-var name as `code`.
2. **API key.** One status line, one action.
   - *Configured · from .env* / *Configured · managed.env* — button **Rotate key…**
   - *Configured · process environment* — Rotate disabled, note: *"Set in the
     gateway's process environment, which overrides managed.env at boot — rotate
     it in the compose environment, not here."* (`admin.py:322-325`, F10)
   - *Missing — this app cannot authenticate* (error colour) — button **Mint a
     key…** (same endpoint as rotate; different verb because nothing dies).
   - If `shadowed_env_names` contains this key: *"An older value is still in
     the read-only .env — inert now, but it would come back if managed.env were
     lost. Remove that line by hand."*
3. **Sends as** (grants). One row per registered identity: checkbox, identity
   name, display, **room**, and *"also held by agent-mcp, aiteam-harness"* (F1,
   F4). Grouped by room, so a grant into a new room is visibly a new room. On an
   inbound app, checking an identity in a room the app does not already post in
   shows an inline note before Save: *"New room for an inbound app — Save will ask
   you to confirm (rule #6)."* On a locked app the whole section is read-only
   with: *"Grants on an inbound_locked app are a registry file edit."*
   Unchecking an identity that is a route target shows: *"Also removes its
   routes: alert → pmtrader-alerts. Severities left without a route return 503 at
   /v1/notify."* (F6; `registry.py:452-457`, runbook §1.)
4. **Routes.** `default` plus the three severities; each select lists *granted*
   identities only, as *"identity — room"*. A computed line under the selects
   replaces the static warning (F5): *"All severities post to one room."* or
   *"alert → spaces/AAQApmt03, everything else → spaces/AAQAfam01 — an all-clear
   will land in a different room from the alert it closes (CG-86)."* in `--warn`.
   Omitted-route consequence stated once: *"A severity with no route and no
   default returns 503."*
5. **Inbound.** As today: `allow_inbound`, `callback_url` (set/not, replace,
   remove), `allowed_users`, `unreachable_message`. The widening rules are stated
   *before* the write: a small note under each field that would widen —
   *"Turning this on asks for a typed confirmation."* Locked: *"Inbound can be
   narrowed here, never widened."* Below the fields, derived and read-only:
   *"Receives inbound from: spaces/AAQAjob02 (via job-hunter)"* — the output of
   `apps_for_space` from the app's side.
6. **Recent deliveries.** The five records as a small table: time (relative,
   `title` attr with ISO), kind, status (coloured), detail. Empty: *"No deliveries
   since the gateway started. The log is in memory; the newest five are shown."*
7. **Danger zone.** *Rotate key…* (also here, with the same dialog) and *Delete
   app…*. On a locked app Delete is disabled: *"Deleting a locked app is a
   registry file edit."* The dialog copy warns about queued messages
   (`admin.js:298`) and, for a managed key, that it is removed from managed.env.

### 3.4 Identity inspector — `#/identity/<name>`

1. **Header:** name, display name (inline-editable: pencil → input → Save/Cancel,
   `PUT /api/identities/<name>`), room link, status dot and line:
   - *Webhook ready · managed.env* / *· .env* / *· process environment*
   - *Webhook URL not set — GOOGLE_CHAT_WEBHOOK_URL__LEGACY_NOTIFY is unset; sends
     as this identity fail at dispatch.*
   - tier-2: *Chat-app identity (mode: app) — sends through the service account;
     no webhook to replace here.* (F9)
   **Avatar card (amended 2026-10-16, spec D6):** the recorded avatar — a
   bundled icon served by the gateway itself, a custom https URL, or none —
   with **Change avatar…** opening the same picker the new-identity stepper
   uses; picking gives the public URL to paste into Chat's webhook dialog
   (select-to-copy) and records `avatar` on the identity. The gateway cannot set
   the webhook's icon; the record is what lets the board show it and lets a
   recreated webhook get the same URL.
2. **Held by.** Apps granted this identity, each with the severities they route
   to it, linked. Empty: *"Not granted to any app. Nothing can send as this
   identity — grant it from an app, or delete it."*
3. **Also posting into this room.** Sibling identities, linked. If the room is
   locked: *"Locked by aitrader."*
4. **Actions.**
   - **Replace webhook…** → `#/identity/<name>/replace` (§3.5). Disabled with
     reason when held by a locked app (*"Held by inbound_locked app aitrader —
     replacing its webhook is a registry file edit."*, `admin.py:703-708`) or
     when the URL is in the process environment (`admin.py:694`).
   - **Delete…** Enabled only when *Held by* is empty (F3; `admin.py:742-745`).
     Otherwise disabled with *"Remove it from 2 apps first"* and, beside each
     holder above, a **Remove grant** button that opens that app's inspector with
     the checkbox already cleared and the routes note shown — the operator
     reviews and saves there. No chained writes (§5 Q2).

### 3.5 Lifecycle flows

**New app — `#/new-app`.** One page, four numbered sections (the runbook's §1
decisions): *App id* (env-var name derived live, `_` and `-` prefixes refused
inline), *Sends as* (the grants list from §3.3, plus a **Create a new identity**
link), *Routes*, *Inbound* (off by default). Primary button **Create app and
mint key** → reveal. The link to create an identity carries a **return ticket**:
the draft (id, checked grants, routes, inbound fields) is kept in page memory —
a JS object, never storage — and on return the new identity is pre-checked
(F11). Leaving the draft by any other route asks: *"Discard the unsaved new
app?"* (one native `confirm` is acceptable here; it is not a destructive write).

**New identity — `#/new-identity`.** A three-step stepper, one view:
1. *In Google Chat* — the existing numbered guide (`admin.js:333-340`), verbatim.
2. *Name it here* — identity name (env-var name derived live), display name
   (*"what /v1/identities reports; the sender name Chat shows is fixed by the
   webhook, not by this"*).
3. *Paste the URL* — password field; shape errors inline (`parse_webhook_space`,
   `admin.py:50-64`), never echoing the value. Note: *"Stored in managed.env.
   Never shown again."*
Result: *"Identity rotaryphone-alerts created · room spaces/AAQArot05."* with
three buttons: **Back to new app** (if a return ticket exists, primary), **Open
identity**, **Board**. Never an unconditional jump.

**Replace webhook — `#/identity/<name>/replace`.** Guide first (*"Google Chat has
no regenerate button: delete the old webhook in the space, create a new one, paste
its URL here."*), then a **Consequences** card computed before anything is typed:
*"Held by pmtrader, agent-mcp. Same room → nothing else changes. Different room →
inbound apps holding it (none / job-hunter) start receiving that room's messages;
you will be asked to type the identity name."* Then the paste field and
**Replace**. The 428 path (`admin.py:719-728`) opens the typed dialog with the
server's text.

**Rotate / mint — dialog → reveal.** Dialog (§3.6) with: *"Rotate the key for
rotaryphone? The current key stops working the instant you confirm. The new key
is shown once."* Button **Rotate key**. On success the reveal view is identical
in content to today's (`admin.js:415-441`) with these changes:
- The key is a read-only `<input>` with `.secret` styling, plus two buttons:
  **Select key** (always works; selects the input's contents and says *"Selected —
  press Ctrl+C / ⌘C"*) and **Copy** (tries the clipboard; on a plain-HTTP LAN page
  it falls through to Select, and the button label *says* "Copy — selects on
  HTTP" so the fallback is not a surprise). `window.isSecureContext` decides.
- Snippets collapse into `<details>` (*curl*, *Python*, *MCP client config* when
  enabled) so the key, the warning and *Send test* fit one screen.
- *Send test* keeps the poll and the *"202 enqueued is not delivery"* line; the
  result shows status, time and detail.
- **Done — I have stored the key** returns to the app inspector. There is no
  Escape or Back out of the reveal that does not pass this button; the copy
  under it says *"Leave this page and the key is gone; rotate again to get a new
  one."*

### 3.6 Confirmation and refusal states

**Typed confirmation — native `<dialog>` (the one deviation).** Modal, with a
backdrop, `showModal()`, focus on the input, Escape = Cancel, Enter = confirm
when the typed value matches, focus returned to the trigger on close. Two
tones, by `data-tone`: `warn` for widening (428 from a Save or a webhook move),
`danger` for rotate/delete. Layout:

```
┌ Confirm: widen inbound for job-hunter ───────────────────────┐
│ The server refused this save until you confirm:              │
│   • allow_inbound                                            │
│   • identity spaces added                                    │
│ Inbound crosses to a consumer only by that consumer's        │
│ explicit registry opt-in (hard rule #6).                     │
│ Type job-hunter to confirm   [__________________]            │
│                               [Cancel]  [Widen inbound]      │
└──────────────────────────────────────────────────────────────┘
```

The confirm button is disabled until the input equals the expected id — the
mismatch toast at `admin.js:289` disappears because the mismatch cannot be
submitted. The server's `detail` is shown verbatim as the reasons list (it
already quotes rule #6; the page adds it only when absent, as today).

Why a dialog and not the inline card: a typed confirmation needs protected focus
and an interruption — it is the one case the Operate guidance exempts from
"exhaust inline first". The shipped card interrupts nothing (`admin.js:264`
prepends and leaves the view live).

**403 — "a registry file edit".** Inline callout at the control, `--muted` tone
(it is information, not an error): *"Not a console action — aitrader is
inbound_locked. Change its identities by editing registry.yaml on the box, then
use Registry › Reload from disk. Still editable here: routes, display names."*
Wherever the page can predict the 403 (locked holders, process-env secrets) the
control is **disabled with the same text** so the callout is the exception, not
the discovery (F10).

**409 — conflict.** A panel above the form, form contents kept (F14):
*"The registry changed since this page loaded. Your edits are kept."* Two
buttons with one-line explanations: **Refresh view** (*"pick up a change made
from another tab or the console"*) and **Reload from disk** (*"pick up a hand edit
to registry.yaml — validates the file, then swaps it live"*). After either, the
panel says *"Compare and Save again."* The other 409s are specific and keep the
server's text: identity still granted (with links to the holders), unpolled
inbound replies (*"poll or drain its inbox first"*), env name already in use
(*"pick another id — the variable name is derived from it"*), process-env secret.
See §5 Q5 for making the page pick the right button automatically.

**422.** Field-level where the message maps to a field (webhook URL shape, id
pattern, unknown identity in routes); otherwise a form-top error. Never a toast
alone.

**401.** Unchanged: sign out with the message (`admin.js:77`). Out of scope here.

**Loading.** Header paints immediately with the sha slot empty; the board shows
a skeleton of six grey rows and `aria-busy="true"` with a visually-hidden
*"Loading registry…"*. Inspectors reached by deep link show the same skeleton.
Never a spinner in the middle of content.

**Empty.**
- No apps and no identities: a single card — *"Nothing registered yet. An app
  needs an identity to send as, so start there."* → **Create an identity**, then
  **Register an app**. The runbook link beneath: *"Prefer the manual runbook?
  docs/registering-an-app.md."*
- Identities but no apps: *"8 identities, no apps. Nothing can send until an app
  is registered and granted one."* → **Register an app**.
- Apps but no identities: *"6 apps and nothing to send as. Every grant list is
  empty."* → **Create an identity**.
- Identity with no holders: in its column header, a small *unused* pill.

**Error on load.** Full-view: *"Could not load the registry view (HTTP 503 —
…)."* → **Retry**. The sha and counts stay empty rather than stale.

### 3.7 Keyboard and screen reader

- **Tab order:** header nav → filter → matrix → (route content). The matrix is
  one tab stop with a **roving tabindex**: arrows move between cells, Home/End to
  row ends, PageUp/PageDown between room groups; **Enter** on a row header opens
  the app, on a column header the identity, on a group header the room, on a
  cell the app with that identity's grant row focused. The matrix is a real
  `<table>` with `<th scope="row">` and `<th scope="col">` and a `<caption>`
  (*"Which app may send as which identity, grouped by room"*), so a screen reader
  announces *"pmtrader, pm-familyworkspace: may send as; default route"* from the
  cell's text, not from colour.
- **Shortcuts, three only:** `/` focus filter, `Escape` back to the board from any
  inspector (and Cancel in a dialog), `?` list the shortcuts. No single-letter
  verbs for writes.
- **Dialogs:** focus into the input, Escape cancels, Enter confirms when valid,
  focus returns to the trigger. Confirm is a real `<button disabled>` until the
  text matches, so the state is announced.
- **Notices:** `role="status"` and `role="alert"` as in §3.1; inline callouts
  are `aria-describedby` targets of the control they explain.
- **Colour never alone:** every dot and pill has text (`ok`, `missing`, `locked`,
  `unused`); the shaded locked group has a `locked by …` pill.
- **Selection and focus are themed from the palette** (`::selection` on the
  accent, the existing 2px outline) — the key box relies on selection as the
  copy mechanism on HTTP, so the selection must be visible in both schemes.

### 3.8 Touch and phone (≤ 720 px)

- The matrix becomes **stacked app cards**: app id + pills + status strip, then
  identity chips grouped under room labels (locked rooms shaded), each chip
  carrying its route letters. A column-wise question (*who holds X?*) is answered
  by the identity inspector, which is one tap on any chip.
- Inspectors are full-width; the Save bar is sticky at the bottom; every button
  is full-width and ≥ 44 px tall; the dialog is a bottom sheet (`<dialog>` with a
  media-query layout).
- Nav collapses to three equal buttons under the title; the Registry menu is a
  disclosure.
- The reveal view puts **Select key** directly under the key box and the
  snippets stay collapsed — the key and the test send fit one phone screen.

### 3.9 Tokens and primitives (`extends`)

New tokens, each justified:

| Token | Light / dark | Why a token |
|---|---|---|
| `--panel` | `#f1f1f1` / `#1b1b1b` | Second neutral for the matrix headers, the notice stack and the dialog surface; `--card` is already "content on page" and `--bg` is the page — a header row needs a third step |
| `--locked-bg` | `rgba(154,103,0,.08)` / `rgba(229,180,91,.10)` — `--warn` at low alpha | Column-group shading for locked rooms; derived from `--warn` so it reads as "caution", never from `--err` (a lock is not a fault) |
| `--accent-soft` | `rgba(26,95,180,.10)` / `rgba(120,174,237,.14)` | Selected row / focused matrix cell background and the `::selection` colour; derived from `--accent` |

New primitives, all composed from existing tokens: `.dot` (10 px status circle
with `ok` / `err` / `muted` classes and adjacent text), `.matrix` (table with
sticky first column and group headers), `.chip` (a smaller `.pill` for route
severities), `.callout` (an inline refusal/consequence block: 1px `--line` border,
`--panel` fill, no coloured left bar), `dialog` (border, radius 8, `--panel`,
backdrop `rgba(0,0,0,.4)`), `.skeleton` (grey bar, no animation needed), `.notice`
stack.

Nothing else changes: typography, radii, button shapes, the `.secret` box and
`pre` styling carry over.

---

## 4. What carries over unchanged (do not touch)

- `el()`, `toNodes()`, the textContent-only rendering discipline (`admin.js:18-39`).
- `api()`, `detailText()`, `write()` with the sha and the *nothing-after-success-may-throw* rule (`:44-63`, `:99-118`); `refresh()`'s banner for a failed post-write refresh.
- `explain()` / `fail()` structure (`:65-79`) — extended with the new 409/403 presentation, not replaced; 401 → `signOut` untouched.
- `lockedHolders()` (`:122-129`) — generalised into a `holders()` map, same logic.
- `optionalField` / `readOptional` absent-means-unchanged semantics (`:177-188`, `:213-218`).
- `readAppFields` and its **ordered identities rule for locked apps** (`:220-241`).
- `withInboundConfirm` 428 loop (`:244-254`) — now resolving through the dialog.
- The webhook guide text and the avatar gallery link (`:14-15`, `:333-340`).
- `reveal()` content: warning text, `curl --config -`, Python, MCP gated on `state.mcp_enabled`, `testSend` polling for a terminal status (`:415-462`).
- `copyKey` / `selectBox` and the `isSecureContext` test (`:401-413`).
- The strings `RULE_6`, `FILE_EDIT` (`:12`, `:16`).
- `index.html`'s `<section id="login">` and the CSP headers (`admin.py:462-469`): no inline script or style; `<dialog>` and hash routing need neither.
- `admin.css` tokens and primitives (§0).
- Every endpoint and request body in `admin.py` — this design adds no API.

---

## 5. Open questions for the user — most consequential first

**Q1. Should `state()` grow a derived `holders` / `rooms` shape, or does the page keep computing it?**
Everything in §3 is computable client-side from today's `state()` (invert
`apps[*].identities`; group identities by `space`; locked rooms from locked apps'
identities). Keeping it client-side means no API change and one source of truth
(the registry) — but the page's "who is locked / who receives" logic would be a
*second implementation* of `locked_space_violations` and `apps_for_space`. A
server-provided `rooms: {space: {identities, posting_apps, inbound_apps,
locked_by}}` block would make the board show exactly what the server enforces.
**Without it:** the page computes; the proposal and mockup assume this, and the
builder should port the two functions' logic verbatim with tests against
`admin.py:137-163` and `registry.py:256-267`.

**Q2. Deleting an identity that is still held — chained writes or review-each?**
The server refuses (409) while any app holds it. §3.4 sends the operator to each
holder's inspector to review (because removing a grant may also remove routes,
`registry.py:452-457`). The alternative is a server-side **"ungrant from all
holders and delete"** in one transaction — a new endpoint. Chaining N client PUTs
is rejected here: each carries a sha and any one can 409 midway, leaving the
registry half-changed. **Without the endpoint:** review-each, as designed.

**Q3. Rooms have no human name. Add an operator-set `label` to… what?**
`space` is `spaces/AAQAxxxx`. The gateway cannot learn the Chat room's name on
tier 1 and hard rule #1 does not help. The board uses the display names of the
identities in the room as a proxy. A real label would be a registry change
(where? the identity carries `space`; there is no space entity) or an
admin-side sidecar file. **Without it:** proxy labels, as mocked. A cheap
middle: let the operator's identity `display` carry the room ("PM ·
familyworkspace" already does) and say so in the new-identity guide.

**Q4. Delivery health beyond five records.**
`recent_deliveries` is five entries; enough for *last status + when*, not for
*"3 of the last 50 failed"*. Raising the limit or adding per-status counts is a
`state()` change (the `DeliveryLog` keeps 200 per source). **Without it:** the
status strip shows the last record's status and time, and the inspector lists
five.

**Q5. Machine-readable refusal category in 4xx bodies.**
The store already classifies refusals (`category_for`, `note_refusal`) for
`/healthz`. If the 409 body carried `{"detail": …, "category": "refused:
conflict" | "refused: disk changed" | …}` the page could offer the one right
button in §3.6 instead of two. **Without it:** two buttons with explanations, as
designed.

**Q6. Pending inbox count per inbound app in `state()`.**
Deleting an app with unpolled replies is refused (`admin.py:621-625`). If
`state()` carried `inbox_pending`, the inspector could show *"2 unpolled
replies"* and disable Delete with the reason. **Without it:** the 409's text is
shown with recovery copy.

**Q7. Recent admin-audit entries in the console.**
`admin_audit.jsonl` records action, ids and field names — never values. A
read-only *"Recent changes"* panel per app/identity (last five entries) would
answer *"what changed and when"* without the box. New read endpoint. **Without
it:** nothing; the operator reads the file.

**Q8. Return ticket for the login round-trip.**
Out of scope for this design, but worth deciding together with the login
decision: should a reload mid-flow return to the hash it was on (`#/app/x`)
after re-authentication? The design assumes yes; it costs nothing and stores
nothing.

---

## 6. About the mockup

`mockup/index.html` is one self-contained file: inline CSS and JS, no external
resources, renders from `file://`, hash-routed. It shows the board, the three
inspectors, new app (with the return ticket), new identity (stepper), replace
webhook (with consequences), rotate → reveal (with Select / Copy fallback and a
fake test send), the `<dialog>` confirmations, the 403 / 409 / 428 / empty /
loading states on a `#/states` reference page, and the ≤ 720 px collapse. Writes
toast and change nothing. Fake data mirrors `registry.example.yaml` plus
`rotaryphone`, `pmtrader` (sharing `pm-familyworkspace`), and an unused identity
with no room. It is a visual reference for planning and for Polisher, not
product code — it uses inline script, which the product page's CSP forbids.
