# Admin console management surface — keys and webhooks across apps that share identities — design

**Date:** 2026-10-16 · brainstormed with the user · designer agent, task CG-91/92
**Baseline:** `main` at `aeb210b`, plus CG-91 (open mode) which lands first;
suite count measured in §9, not copied from `CLAUDE.md`.

**Row this spec produces:** **CG-92** — the console at `/admin` redrawn around
the resource several apps share (an identity, and the room it posts into), with
an app inspector, an identity inspector and a room inspector, and lifecycle
flows that return the operator to where they started. Companion row, specified
separately and shipping before this one: **CG-91**, open mode
(`2026-10-16-admin-open-mode-design.md`).

**Handoff package:** `docs/design-handoffs/admin-console-ux/` — `overview.md`
(the critique and the three IA options), `mockups/index.html` (a clickable
throwaway mockup of the chosen option, fake data, `file://`), and two renders,
`mockups/mockup-board.png` and `mockups/mockup-app-aitrader.png`. The mockup is
a visual reference, not product code: it uses inline script, which the product
page's CSP forbids.

**No ⚠ verification-ledger flag is cleared, added or reworded by anything in
this document, and none may be by the PR it produces.** The console adds no
Google-facing code; its test-send is the existing adapters' bytes from a new
caller, the reasoning CG-80 and CG-90 both recorded.

**Follows / extends / deviates.** This design `follows` `admin.css` — every
token it ships, system-ui at 15 px, 6/8 px radii, `prefers-color-scheme` dark
mode, the `.pill` / `.card` / `.secret` / `pre` primitives — and the handoff's
`overview.md` §3. It `extends` `admin.css` with three tokens (§6) and six
primitives. It `deviates` from the shipped page in one visual-language respect:
typed confirmations move from a card prepended into the main view
(`admin.js:264`) to a native `<dialog>`, argued in §4.6. Nothing else in the
shipped look is discarded; the shell CG-91 ships — the login section in `key`
mode, the `open · no sign-in` pill in open mode — is restyled, not redesigned.

---

## 1. Problem

CG-90's page is a correct two-table status board. Its weakness is structural:
the operator manages six apps that share a handful of identities, and *sharing*
is a relationship the two flat tables never draw. Nothing shows which apps hold
an identity (`admin.js:143-161`; the only inversion is `lockedHolders`,
`:122-129`, used to disable one button). Nothing shows who else posts into a
room — `space` is a raw `spaces/XXXX` string per row (`:154`) — although the
server's most important safety rule is *about* rooms (`locked_space_violations`,
`admin.py:137-163`). Deleting an identity asks for a typed name and is then
refused because an app still holds it (`:393-398`; `admin.py:742-745`).
Granting an identity shows a bare name, so the widening the server guards is
discovered from a 428 after Save (`:193-194`; `widening()`, `admin.py:86-91`).
Routes show identity names without rooms and the CG-86 room-split warning is
printed unconditionally (`:195-204`). The new-app wizard bounces to "New
identity" and back, destroying the draft (`:314-315`, `:351-354`). The full
critique, twenty findings each cited to a line, is the handoff's `overview.md`
§1; its heuristic baseline is 24/40.

## 2. Decisions

**User, 2026-10-16** (brainstormed from the handoff's three options and three
questions):

| # | Decision | Chosen | Declined, and what it would have given |
|---|---|---|---|
| D1 | Information architecture | **Option C — grant matrix + inspectors.** Rows are apps, columns are identities grouped under their room; a shared identity is a column with two or more marks; locked rooms are shaded. Row, column and room headers open three inspectors. | *A — app-centric, tightened*: today's tables repaired (holders column, rooms beside names, delivery time, pre-disabled refusals); smallest change, the room stays a string. *B — room-centric*: rooms → identities → holders; makes the lock literal, but puts the key lifecycle — the most frequent task — two levels down. |
| D2 | Where the room / holder relationships are computed | **The server publishes** a derived `rooms` block in `state()`, built from the same functions it enforces with (`apps_for_space`, `locked_space_violations`), so the board shows exactly what the server refuses. Additive API change; shape in §5. | *Page-computed* from today's `state()`: no API change, but a second implementation of the lock and inbound-routing logic that could drift from the one that refuses writes. |
| D3 | Deleting an identity that apps still hold | **Review each holder.** The identity inspector lists holders with a *Remove grant…* link into each app's inspector, where the operator sees the routes that go with it and saves. The server's 409 stays as the backstop. | *A transactional "ungrant everywhere and delete" endpoint*: one click; hides that removing a grant can also remove routes (`registry.py:452-457`). *Chained client PUTs* were rejected outright — each carries a sha and any one can 409 midway. |
| D4 | Naming a room the gateway knows only by id | **Identity display names are the room's proxy label**, and the new-identity guide suggests room-named identities (`"PM · familyworkspace"`). | *A registry label*: there is no space entity to hang it on, so it would be a schema change on the identity or a sidecar file. |
| D5 | Board width (user, 2026-10-16, after reviewing the mockup: the bottom scrollbar was *"often off the page"* and reaching it via the page scrollbar was awkward) | **Bounded-height matrix + collapsible rooms.** The matrix scrolls in its own region sized to the viewport, so its horizontal scrollbar is always on screen; sticky app column and sticky room/identity headers; each room group collapses to one narrow column (a per-app "sends here" mark, the room's lock shading) until expanded; per-room toggle plus expand-all / collapse-all; remembered for the session only, no storage. §4.2. | *Bounded height alone*: the scrollbar is reachable but a wide registry is still a long scroll. *Transpose* (identities as rows): rows are then the shared resource, but the app — the unit of the key lifecycle — becomes a column and the row header's status strip is lost. |
| D6 | Avatars (user, 2026-10-16) | **Picker + remembered in the registry.** The gateway serves its twenty bundled icons itself; the new-identity stepper and the identity inspector show them as a picker; picking one gives the public URL to paste into Chat's avatar field (select-to-copy) and records an optional `avatar` on the identity — a bundled name or a custom `https` URL; the board and inspectors show the bundled icon beside the identity and a neutral mark for custom or none. §4.2, §4.4, §4.6, §5. The icon Chat shows is still set in Chat's webhook dialog — the gateway cannot set it. | *Picker with nothing stored*: the URL is handed over once and the board cannot show which identity carries which icon, and a webhook recreation has no record of what to paste again. |

**Controller's calls, 2026-10-16** (recorded as such, not as user decisions):

| # | Call | Chosen | Declined |
|---|---|---|---|
| C1 | Delivery health | **Keep five records.** The status strip shows the last record's status and relative time; the inspector lists five. | Raising the limit or adding per-status counts to `state()`. |
| C2 | Refusal bodies | **Yes:** 4xx bodies gain an additive machine-readable `category` beside `detail`, so the page can offer the one right recovery (§4.6). Shape left to the builder (§5). | Routing on message text. |
| C3 | Pre-disabling Delete on an app with unpolled replies | **Yes:** `state()` gains `inbox_pending` per app (§5). | Showing the 409 after the click. |
| C4 | Recent admin-audit entries in the console | **Deferred** to a later row — a new read endpoint. | — |
| C5 | Hash routes across reload | **Yes:** the page resumes the hash it was opened on, in both auth modes; nothing is stored. | — |

**Not reopened here:** CG-90's D1–D7 and CG-91's D1. CG-91's shell — the
`GET /admin/api/state` probe with no header, the login section in `key` mode,
the `open · no sign-in` pill — is kept exactly as CG-91 ships it (its §4) and
restyled only by the shared tokens.

---

## 3. Components

One concern each; the product page stays one HTML, one JS, one CSS file with no
build step and no CDN, under the CSP at `admin.py:462-469` — no inline script or
style. `<dialog>` and hash routing need neither.

| Unit | Does | Depends on |
|---|---|---|
| `static/admin/index.html` | Shell: header (title, sha, counts, CG-91 pill), three-item nav, filter, `Registry` menu, banner row, breadcrumb, `#view`, notice stack, two `<dialog>` elements (confirm, help). Login section unchanged from CG-91. | — |
| `static/admin/admin.js` — router | Hash routes (§4.1) → one render function each; resumes the hash after the CG-91 probe. | `state` |
| `admin.js` — board | The grant matrix and its phone collapse (§4.2), filter, roving-tabindex grid (§4.7). | `state.rooms` |
| `admin.js` — inspectors | App (§4.3), identity (§4.4), room (§4.5). | `state`, `holders()` |
| `admin.js` — flows | New app with return ticket, new identity stepper, replace webhook with consequences, rotate → reveal (§4.6). | existing `write()`, `reveal()`, `testSend()` |
| `admin.js` — confirm / notices | `typedConfirm()` on `<dialog>`; notice stack; inline callouts keyed by `category` (§4.6). | `explain()` |
| `admin.css` | Existing tokens + §6's three; six primitives. | — |
| `admin.py` — `state()` | Gains `rooms` and `inbox_pending` (§5). | `registry.apps_for_space`, `locked_space_violations`, `Inbox.pending_counts` |
| `admin.py` — `refuse()` / `StoreError` → HTTP | 4xx bodies gain `category` (§5). | `registry_store.category_for` |

---

## 4. The page

Mode: an operator tool. Familiar controls, restrained colour, density where it
helps, one type family, motion only for focus/hover (150 ms) and the dialog's
fade. Mockups: the handoff's `mockups/index.html`, with `#/states` as a
reference page for every state in §4.6.

### 4.1 Shell and navigation

- **Routes in the URL hash:** `#/` board · `#/app/<id>` · `#/identity/<name>` ·
  `#/room/<space-id>` (the part after `spaces/`; `none` for identities with no
  room) · `#/new-app` · `#/new-identity` · `#/identity/<name>/replace` ·
  `#/reveal`. Back/Forward and deep links come free; nothing is stored (C5).
  `#/reveal` is in-memory only — reloading it lands on the board with *"A key
  is shown exactly once … rotate again to get a new one."* App and identity ids
  are not secrets; they are on `/healthz` already.
- **Nav:** Board · New app · New identity, with `aria-current="page"`.
  **"Reload from disk" moves into a `Registry` menu** beside the sha, with
  *Refresh view* (GET state — "picks up a change made from another tab"), *Reload
  from disk* (POST reload — "validates registry.yaml as it is on disk and swaps
  it live, after a hand edit") and *Keyboard shortcuts*. Rare operations, one
  click further, named by what they do.
- **Header line:** title, `registry <sha12>`, `N apps · N identities · N rooms`
  (rooms excludes `none`), and in open mode CG-91's pill.
- **Banner row** carries operator to-dos only — shadowed env names,
  `inbound_defaulted` apps, the "saved but view refresh failed" warning
  (`admin.js:112-116`) — each naming and linking the apps concerned, **and those
  rows carry the same mark on the board.**
- **Notices** replace the single toast: a fixed stack, `role="status"` for
  successes (auto-dismiss 6 s), `role="alert"` for refusals (stay until
  dismissed). Refusals also render inline at the control (§4.6).

### 4.2 The board — grant matrix

A real `<table class="matrix">` with a `<caption>` (*"Which app may send as which
identity, grouped by room. A column with two or more dots is a shared
identity."*), two header rows and one row per app. Render: `mockup-board.png`.

- **Group header row** — one `<th scope="colgroup">` per entry in `state.rooms`,
  in order (ids ascending, `none` last): the room id linked to `#/room/…`; a
  `locked by <app>` pill and `--locked-bg` shading when `locked_by` is set; for
  `none`, the note *"cannot route inbound; not covered by any lock"*.
- **Identity header row** — per identity: status dot (webhook ready / URL not
  set / tier-2 neutral, with text in `title`), the **avatar mark** (D6: the
  bundled icon at 16 px from `/admin/static/avatars/<name>.png`; a neutral
  dashed circle with `title` *"custom avatar URL"* / *"no avatar recorded"*
  otherwise), the name linked to `#/identity/…`, an `unused` pill when no app
  holds it, the display name below. The same mark appears beside identities in
  the inspectors' lists and the phone chips.
- **Row header** (`<th scope="row">`) — app id linked to `#/app/…`, pills
  (`inbound on|off`, `locked`), and a status strip: key state (*key ok*, *key ok
  (managed)*, *key ok (process)*, *key missing* in `--err`), last delivery as
  *status + relative time* with the ISO `ts` in `title` (C1), and row marks —
  *routes span N rooms* (CG-86, computed from `routes → identity → space`),
  *stale .env value*, *inbound defaulted*.
- **Cell** — a filled accent dot when the app holds the identity, plus a chip
  per severity routed there (`default`, `alert`, `warning`, `info`); empty
  otherwise. Each cell's `title` is the sentence it encodes; a visually-hidden
  *"may send as"* makes the dot readable. **Cells are not toggles** — writes
  happen in the inspector with an explicit Save, so the 428 flow and the
  ordered-identities rule keep one home.
- **Legend** under the table: dot, chip, locked shading, the two status dots.
- **Filter** (`/`): substring on app id, identity name, display, room id; hides
  non-matching rows and columns and recomputes colspans; reports *"3 of 6 apps ·
  2 of 8 identities match 'trader'"*. Typing in the filter from an inspector
  returns to the board.
- **Bounded region (D5).** The table sits in a scroll region (`overflow: auto`)
  whose max height is the viewport minus the header, tools and legend
  (`calc(100vh - ~250px)`, min ~260 px), so **its horizontal scrollbar is always
  on screen and the page never scrolls to reach it**. The app column is sticky
  on the left; both header rows are sticky on top (the identity row offset by
  the group row's fixed height). Sticky cells need **opaque** backgrounds —
  the locked shading on sticky header cells is `--locked-bg` composed over
  `--panel` into a solid colour, or scrolled content shows through.
- **Collapsible rooms (D5).** Every room group has a toggle (*expand* /
  *collapse*, `aria-expanded`) in its header, and the tools row above the
  matrix has **Expand all rooms** / **Collapse all rooms** with *"N of M rooms
  expanded · remembered for this session only"*. **Default: all rooms
  collapsed**; opening an app inspector expands the rooms that hold that app's
  grants, and that app's row is highlighted on return. The expanded set lives
  in page memory only — no storage, lost on reload. A **collapsed room is one
  narrow column**: the group header shows the room id, lock pill and *"· N
  identities"*; the identity-row cell reads *"any identity here"*; each app's
  cell shows the filled dot when the app holds **any** identity in the room,
  with chips for every severity routed into the room, and the room's lock
  shading; its `title` reads *"pmtrader sends into spaces/… as pmtrader-alerts —
  Enter expands the room"*. The caption and legend say what a dot means in a
  collapsed column. Clicking a collapsed column (header or cell) expands it;
  clicking the room link still opens the room inspector.
- **Phone (≤ 720 px):** the table is hidden and the same data renders as
  stacked app cards — id, pills, status strip, then identity chips grouped
  under room labels (locked rooms shaded), each chip carrying its route
  severities and linking to the identity inspector.

### 4.3 App inspector — `#/app/<id>`

Render: `mockup-app-aitrader.png`. One form, one **Save** in a sticky save bar
(disabled until something changed, with *No changes* / *Unsaved changes*), a
**Discard** that re-renders from state.

1. **Header** — id, pills, `code` of `key_env`.
2. **API key** card — one status line, one action:
   *Configured · from managed.env | the hand-written .env | the process
   environment*, or *Missing — this app cannot authenticate. Mint a key to fix
   it* in `--err`. **Rotate key…** (or **Mint a key…** when missing; same
   endpoint, different verb because nothing dies) is **disabled with the reason
   when `key_source` is `process`**: *"Set in the gateway's process environment,
   which overrides managed.env at boot — rotate it in the compose environment,
   not here"* (`admin.py:322-325`). If `shadowed_env_names` contains `key_env`,
   a `--warn` callout: *"An older value of … is still in the read-only .env —
   inert now, but it would come back if managed.env were lost. Remove that line
   by hand."*
3. **Sends as** — identities grouped by room (`state.rooms` order), each row a
   checkbox, name, display, `URL not set` pill when unresolved, and a meta line:
   *also held by X, Y* or *held by no other app*. Dynamic notes before Save:
   checking an identity in a room an **inbound** app does not already post in →
   *"New room for an inbound app — Save will ask you to confirm (rule #6)"*;
   unchecking a route target → *"Also removes its routes: alert → X. Severities
   left without a route return 503 at /v1/notify"* (`registry.py:452-457`); a
   room locked by another app, on an inbound app → checkbox disabled, *"Room
   locked by aitrader — an inbound app cannot be granted an identity here."* On
   a locked app the section is read-only with the callout *"Grants on an
   inbound_locked app are a registry file edit, not a console action. Routes and
   display names stay editable here."*
4. **Routes** — `default` plus the three severities; each `<select>` lists
   **granted** identities only as *name — room*; a selection that is unchecked
   above is dropped. A computed line replaces the static warning: *"All
   severities post to one room."* · *"alert → spaces/A, everything else →
   spaces/B — an all-clear will land in a different room from the alert it
   closes (CG-86)"* in `--warn` · *"No routes — every /v1/notify returns 503.
   Set a default at least"* in `--err` · severities with neither route nor
   default named.
5. **Inbound** — `allow_inbound` (*"turning this on asks for a typed
   confirmation"* while off), `callback_url` and `unreachable_message` as
   today's absent-means-unchanged fields, `allowed_users`. A derived line:
   *"Receives inbound from: spaces/… — every message and card interaction in
   those rooms"* / *"nothing (inbound off)"*, from `state.rooms[*].inbound_apps`.
   Locked: *"Inbound can be narrowed here, never widened."*
6. **Recent deliveries** — the five records, newest first: when (relative, ISO
   in `title`), kind, status coloured, detail-or-title. Empty: *"No deliveries
   since the gateway started. The log is in memory; the newest five are shown."*
7. **Danger zone** — *Delete app…*; disabled with reason on a locked app
   (*"Deleting an inbound_locked app is a registry file edit"*) and when
   `inbox_pending > 0` (*"2 unpolled inbound replies — poll or drain its inbox
   first"*, C3). The dialog copy names the consequences: queued messages close
   as unroutable; a managed key is removed from managed.env.

**Save** sends today's `PUT` body (ordered identities on a locked app,
`admin.js:222-232`; `callback_url`/`unreachable_message` only when edited). A
428 opens the typed dialog with the server's reasons; a 403 renders inline.

### 4.4 Identity inspector — `#/identity/<name>`

1. **Header** — name, `room locked by …` pill, `unused` pill; room link and
   `webhook_url_env` as `code`. Status line: *Webhook ready · <source>* /
   *Webhook URL not set — <env> is unset; sends as this identity fail at
   dispatch* / for `mode: app`: *Chat-app identity — sends through the service
   account; no webhook to replace here.* Display name with an inline **Rename…**
   (input, Save, Cancel; `PUT /api/identities/<name>`), and the sentence *"The
   sender name and avatar Chat shows are fixed by the webhook itself; the display
   name is what /v1/identities reports."*
   **Avatar card (D6):** the mark at 20 px (the inspector size; the header's
   mark beside the identity name is 20 px too), *"Recorded: bundled icon “phone” /
   custom URL — https://… / none recorded"*, and **Change avatar…**, which
   swaps the card for the picker (§4.6) with **Save avatar** / **Cancel**
   (`PUT /api/identities/<name>` with `avatar`). Copy under it: *"The icon Chat
   shows is set in the webhook's dialog in Google Chat; the gateway cannot set
   it. What is recorded here is which icon you chose, so the board can show it
   and you can paste its URL again when the webhook is recreated."* The picker
   view adds the callout *"Recording an avatar here does not change the
   webhook. Open the webhook in Google Chat and paste the URL above into its
   Avatar URL field."*
2. **Held by** — one row per holder: app link, pills, the severities it routes
   here (*"granted, no route"* otherwise), and **Remove grant…** → `#/app/<id>?ungrant=<name>`
   (the app inspector opens with that box unchecked, the routes note shown and
   Save enabled). Locked holders show *file edit* instead. Empty: *"Not granted
   to any app. Nothing can send as this identity — grant it from an app, or
   delete it."*
3. **Also posting into this room** — sibling identities linked; the lock callout
   when `locked_by` is set; for `none`: *"No room recorded … Replacing the
   webhook records the room."*
4. **Actions** — **Replace webhook…** (disabled with reason: held by a locked
   app, `admin.py:703-708`; URL in the process environment, `:694`; not a
   webhook identity) and **Delete…** (enabled only when *Held by* is empty,
   D3; otherwise *"Remove it from N apps first. Use Remove grant… beside each
   holder above."*). Each disabled reason is also printed as a callout under
   the buttons.

### 4.5 Room inspector — `#/room/<space-id>`

Header with the room id and lock pill. For a real room: *"The gateway knows this
Chat room only by its id, derived from webhook URLs. Posting here: <display
names>."* (D4). Three cards: identities posting here (dot, name, display,
holders); apps posting here; inbound — *"Received by X — every message and card
interaction here"* or *"No app receives inbound from this room; its events are
counted as suppressed and never stored"* — plus the lock callout spelling out
what the console refuses in that room. For `none`: the `--warn` callout *"These
identities have no space recorded. They cannot route inbound and are not covered
by any inbound_locked app's lock. Replacing an identity's webhook records its
room."*

### 4.6 Lifecycle flows, confirmations and states

**New app — `#/new-app`.** One page: *1 · App id* (env-var name derived live;
pattern and duplicate errors inline), *2 · Sends as* with a link **create a new
identity (you will come back here)**, then grants, routes, inbound (§4.3's
components with a blank app), and a save bar with **Discard draft** and **Create
app and mint key**. The link stores the draft in page memory (never storage) and
routes to `#/new-identity?return=new-app`; on return the new identity is
pre-checked and the save bar says so. Leaving the draft another way asks once
(*"Discard the unsaved new app?"*). An app created with inbound on confirms in
the dialog first. Success → reveal.

**Unsaved edits in an app inspector** (*controller's call, 2026-10-16*). The
same one-shot *"Discard unsaved changes?"* dialog the new-app draft gets fires on
**any** navigation away while the save bar is dirty — Escape, `/`, typing in the
filter, a breadcrumb or nav click, Back/Forward. Inside that dialog Escape
cancels back to the inspector with the edits intact; **Discard** completes the
navigation. A clean save bar navigates without asking. The hash is not changed
until the operator chooses, so Back/Forward is intercepted by re-pushing the
current route and asking, not by letting the view change first.

**New identity — `#/new-identity`.** A three-step stepper on one view: *Pick an
avatar, then create the webhook in Google Chat* (D6 — the **avatar picker**
first: the bundled icons from `state.avatars` as `aria-pressed` buttons — each
a ~40 px tile with the icon's name under it — plus *none*, a *custom https URL* field, and a read-only URL box *"Paste this into
the webhook's Avatar URL in Google Chat"* with a **Select URL** button, since
the clipboard API is unavailable over plain HTTP; then the existing guide,
`admin.js:333-340`, with its third step reworded *"Set the name; paste the
avatar URL above into Avatar URL. Both are fixed at creation and cannot be
changed later without a new webhook"*, and the GitHub gallery link gone because
the picker replaces it — **the URL in the box is the PUBLIC GitHub raw URL**
built from `AVATAR_PNG_PATTERN` (`admin.js:16`), never a gateway URL: Google's
servers fetch the avatar and this gateway is LAN-bound (CG-55), so a same-origin
URL would give the webhook a blank icon fixed at creation (*controller's ruling
R1, 2026-10-16*); intro: *"The name and avatar of a webhook
are fixed when it is created in Chat; the gateway cannot set them. Choose the
icon first so you have its URL ready to paste"*), *Name it here* (name with
env-var name derived live;
display name with the D4 tip), *Paste the URL* (password field; shape error
inline from the server's 422, never echoing the value; *"Stored in managed.env.
Never shown again."*). Result card: *"Identity X created · room spaces/…"*,
*"Not granted to any app yet"*, and **Back to new app (pre-granted)** when a
return ticket exists, else **Open identity** / **Board**. Never an unconditional
jump.

**Replace webhook — `#/identity/<name>/replace`.** The guide (delete the old
webhook, create a new one with the same name, set the avatar again — the
recorded avatar's URL is shown as `code` to paste, or *"No avatar is recorded
for this identity; pick one on the identity page if you want its URL kept"* —
then paste),
then a **Consequences** card computed before anything is typed: who holds it;
*same room — nothing else changes; a rotated webhook moves nothing* / *different
room — inbound apps X start receiving that room's messages; you will be asked to
type the identity name*. Then the paste field and **Replace webhook**. A 428
(`admin.py:719-728`) opens the typed dialog with the server's text. A locked
holder renders the 403 callout instead of the form.

**Rotate / mint → reveal.** Dialog, then the reveal view, content as today
(`admin.js:415-441`) with: the key in a read-only `<input class="secret">`;
**Select key** (always works — selects and says *"Key selected — press Ctrl+C
(or ⌘C) to copy"*) and **Copy — selects on HTTP** (label chosen by
`window.isSecureContext`; falls through to select on the plain-HTTP LAN page);
snippets in `<details>` (curl, Python, MCP when `mcp_enabled`); the test send
with its terminal-status poll; **Done — I have stored the key** as the only way
out, with *"Leave this page and the key is gone; rotate again to get a new one."*

**Typed confirmation — native `<dialog>` (the deviation).** `showModal()`,
backdrop, focus on the input, Escape cancels, Enter confirms when the text
matches, focus returns to the trigger. Two tones by `data-tone`: `warn` for
widening (a 428 from Save, create, or a webhook move), `danger` for rotate and
delete. Title *"Confirm: widen inbound for job-hunter"*; intro *"The server
refused this save until you confirm:"*; the server's reasons as a list; rule #6
in muted text (added only if the server's detail lacks it, as today); *"Type
job-hunter to confirm"*; **Cancel** and the verb button (**Widen inbound**,
**Rotate key**, **Delete app**, **Delete identity**, **Replace webhook**)
**disabled until the text matches** — the mismatch toast at `admin.js:289`
disappears because a mismatch cannot be submitted. Why a dialog: a typed
confirmation needs protected focus and an interruption; the shipped card
interrupts nothing and leaves the view live underneath.

**Refusals, keyed by `category` (C2) with `detail` as the text:**

| Status | Presentation | Copy |
|---|---|---|
| 403 "file edit" | Inline callout at the control, muted tone (information, not a fault). Wherever predictable (locked holders, process-env secrets, locked app's grants/delete) the control is **disabled with the same text**, so the callout is the exception. | *"Not a console action — aitrader is inbound_locked. Change its identities by editing registry.yaml on the box, then use Registry › Reload from disk. Still editable here: routes, display names."* |
| 409 conflict (page stale vs. server) | Panel above the form, **form contents kept**; the category selects the one right button; both offered with explanations when the category is absent. | *"The registry changed since this page loaded. Your edits are kept."* **Refresh view** — *"pick up a change made from another tab or the console"* · **Reload from disk** — *"pick up a hand edit to registry.yaml — validates the file, then swaps it live"* · *"Then compare and Save again."* |
| 409 other | Alert notice + inline callout with the server's words and the recovery. | identity still granted → links to holders and *Remove grant…*; unpolled inbound → *"poll or drain its inbox first"*; env name in use → *"pick another id — the variable name is derived from it"*; process-env secret → change it there. |
| 422 | At the field when it maps (webhook URL shape, id pattern, unknown identity in routes); otherwise form-top. Never a toast alone. | the server's `detail` |
| 428 | The dialog above. | bullets from `reasons` when the body carries it (§5); otherwise `detail` verbatim |
| 401 | Unchanged: CG-91's `signOut` path. | — |

**Loading.** Header paints with the sha slot empty; the board shows six
skeleton rows with `aria-busy="true"` and a visually-hidden *"Loading
registry…"*; a deep-linked inspector shows the same. No spinner in content.

**Empty.** Both empty: *"Nothing registered yet. An app needs an identity to
send as, so start there."* → **Create an identity** (primary), **Register an
app**, and *"Prefer the manual runbook? docs/registering-an-app.md"*. Identities
but no apps: *"N identities, no apps. Nothing can send until an app is
registered and granted one."* Apps but no identities: *"N apps and nothing to
send as. Every grant list is empty."* An identity with no holders carries an
`unused` pill in its column header.

**Error on load.** Full view: *"Could not load the registry view (HTTP 503 —
…)"* → **Retry**; sha and counts stay empty rather than stale.

⚠ *Controller note 2026-10-16 (CG-92): the initial probe's non-401 failure keeps
CG-91's behaviour (login section with the message, a pinned invariant). The
full-view error card with Retry applies to failures after the console is
visible (Refresh view, board re-entry).*

### 4.7 Keyboard, screen reader, touch

- Tab order: nav → filter → matrix tools (expand/collapse all) → matrix (one
  stop) → view. The matrix uses a **roving tabindex** over three kinds of grid
  cell — the room header row, the identity header row, and the app rows:
  Left/Right and Home/End move within a row; Up from an identity cell lands on
  the room header that **spans** it; Down from a room header lands on its first
  column; **Enter** opens the app / identity / room under the focused header or
  cell; **Space on a room header toggles** that room (the toggle button inside
  is `tabindex=-1`, so the header is the single stop and the button is for the
  mouse); **Enter on a collapsed room's column expands it**. After a toggle the
  matrix re-renders and focus returns to that room's header (D5). A collapsed
  room is exactly one column in every row, so arrow movement needs no special
  case beyond the column count changing. Real
  `<th scope>` headers and the caption make a cell read as *"pmtrader,
  pm-familyworkspace: may send as; default route"* — from text, never colour.
- **Three shortcuts only:** `/` filter, `Escape` back to the board from any view
  (and Cancel in a dialog; no effect on the reveal view), `?` the shortcut list
  (a second `<dialog>`). No single-letter verbs for writes.
- Dialogs as §4.6; notices with `role="status"` / `role="alert"`; inline
  callouts referenced by `aria-describedby` from the control they explain.
- Every dot and pill has text; `::selection` is themed on `--accent` in both
  schemes because selection *is* the copy mechanism on HTTP.
- ≤ 720 px: stacked cards (§4.2), full-width inspectors, sticky save bar, ≥ 44 px
  buttons, the dialog as a bottom sheet, nav as three equal buttons, the
  Registry menu as a disclosure, the reveal view with **Select key** directly
  under the key box and snippets collapsed.

---

## 5. Open interfaces the server must provide — for the planner to resolve

These are **additive** changes to `/admin/api/state` and to refusal bodies. The
shapes below are what the page consumes; names are proposals, the planner fixes
them and the builder implements them.

**`state.rooms`** (D2) — one entry per distinct `space` across identities, plus
one for the empty space, keyed by the space id:

```
rooms: {
  "<space id or empty string>": {
    identities:   [name, …],      # identities whose `space` is this room, name order
    posting_apps: [app_id, …],    # every app holding any of those identities
    inbound_apps: [app_id, …],    # apps_for_space(space) ∩ allow_inbound — empty for the empty space
    locked_by:    app_id | null   # the inbound_locked app whose identity is homed here,
                                  #   chosen as locked_space_violations chooses it; null for the empty space
  }
}
```

Built from `Registry.apps_for_space` (`registry.py:256-267`) and the same
`locked` derivation as `locked_space_violations` (`admin.py:149-154`) —
**the page never re-derives these**; its only inversion is `holders(name)`,
which stays client-side because it is a plain lookup on `apps[*].identities`.

**`state.apps[*].inbox_pending`** (C3) — integer, `Inbox.pending_counts()` for
the app, `0` when no inbox is wired; the same number the delete refusal reads
(`admin.py:621`).

**Refusal `category`** (C2) — every 4xx the admin router raises carries, beside
`detail`, a machine-readable string. The store already names categories for
`/healthz` (`registry_store.category_for`, `note_refusal`); the planner decides
whether those strings are reused verbatim or a page-facing set is minted. The
page needs to distinguish at least: `conflict` (sha mismatch — Refresh view),
`disk changed` (file edited outside the console — Reload from disk), `file edit`
(the 403 class), `still granted`, `unpolled inbound`, `env name in use`,
`secret in process env`, `needs confirmation` (428), and a generic fallback.
Hard rule #2 applies: a category is a fixed string, never interpolated.

**Avatars (D6, user decision)** — four additive pieces, names proposed:

- **Registry:** `identities.<name>.avatar`, optional. Validated at load (and by
  the console before writing): either the stem of a bundled icon
  (`assets/avatars/png/<name>.png` — the twenty from PR #80) or an `https://`
  URL; anything else refuses, the way `inbound_locked` refuses a non-boolean
  (hard rule #7's shape). Absent = none. **Hard rule #2:** the value is an icon
  name or a public image URL — never a secret, never a webhook URL — so it may
  appear in `state`, in audit field lists and on the page.
- **Served icons — for the PAGE's rendering only** (*controller's ruling R1,
  2026-10-16*): the gateway serves the bundled PNGs itself, e.g.
  `GET /admin/static/avatars/<name>.png`, unauthenticated with the existing
  static route's headers, same-origin so the page's CSP `img-src 'self'` holds
  with no CSP change; a custom https URL is never fetched by the page and renders
  as the neutral mark. **The URL handed to the operator to paste into Chat is
  the public GitHub raw URL**, `AVATAR_PNG_PATTERN` (`admin.js:16`) with the
  name substituted — Google fetches avatars from the public internet and the
  gateway is published on the LAN address only (CG-55). The gallery link may
  go; the raw-URL pattern stays as the constant the page builds from. A custom
  URL equal to a bundled icon's raw URL **normalises to that bundled name on
  save** (loader or write path — planner's choice), so the board never shows a
  neutral mark for an icon it has. `state.avatars` is the **sorted listing of
  the packaged directory at boot**, so the picker never hard-codes names and
  the validator matches a name against that list — never joins it onto a path.
- **Packaging** (*controller's ruling R2, 2026-10-16*): `assets/avatars/png/`
  stays where it is — the public URLs are pinned to that path and the README
  promises it. The generator `assets/avatars/build.py` writes the same PNGs to
  a second output, `src/chat_gateway/static/admin/avatars/`; `pyproject`
  package-data gains `static/admin/avatars/*`; a test asserts the two
  directories are byte-identical by name so the two homes cannot drift (the
  test is the guard, CG-88 style). Declined: moving the PNGs (breaks published
  URLs); shipping a top-level `assets/` in the wheel/Dockerfile (a different
  layout for twenty files).
- **Builder's decidables, accepted as written:** `avatar` is allowed on
  `mode: app` identities too; `update_identity` treats `display` as
  absent-means-unchanged so an avatar-only save need not resend it.
- **`state.identities[*].avatar`:** the recorded value or `null`.
- **Write path:** `POST /api/identities` accepts `avatar`; the identity `PUT`
  (today `DisplayIn`, display only) accepts `avatar` as absent-means-unchanged,
  `""`/`null` to clear — the same shape `callback_url` uses. Audit records the
  field name `avatar`, never the value's URL form beyond what the registry
  already holds.

*Controller's calls, 2026-10-16, after the builder check — three amendments to
the interface above:*

- **One vocabulary, the store's.** `category` strings are the ones
  `registry_store.category_for` / `note_refusal` already produce for
  `/healthz`; the page-facing set is not a second vocabulary. Two refusals the
  page must tell apart today fall to `refused: conflict` and need **new authored
  categories**, names left to the planner: `delete_identity` while the identity
  is still granted (`admin.py:742-745`), and `managed_name`'s process-env
  refusal (`:322-325`). **The fix site for carrying categories into bodies is
  `run()`** (`admin.py:309-315`): it re-raises `StoreError` as
  `HTTPException(exc.status, str(exc))` and drops `StoreError.category` on the
  floor. **401 and 429 get NO category**: both are raised outside `refuse()`
  (`require_admin`, `_Limiter.check`), are deliberately uncounted, and the page
  routes them by status alone.
- **`reasons` on 428 bodies — additive.** Wherever the server already holds a
  list, the 428 body carries `reasons: [...]` beside `detail`: `guard_inbound`'s
  widening reasons (`admin.py:385-394`) and `replace_webhook`'s moving apps
  (`:721-727`). The two delete 428s (`:603`, `:741`) carry none. `detail` keeps
  its current text unchanged. The dialog renders bullets when `reasons` is
  present and `detail` verbatim otherwise.

**What this spec does not decide:** Python module boundaries, pydantic model
names, whether `rooms` is memoised, and how `category` and `reasons` reach the
response body beyond the `run()` fix site. Those are the plan's.

---

## 6. Tokens and primitives (`extends admin.css`)

| Token | Light / dark | Why a token |
|---|---|---|
| `--panel` | `#f1f1f1` / `#1b1b1b` | A third neutral for matrix headers, the header bar, the notice stack and the dialog surface; `--bg` is the page and `--card` is content on it |
| `--locked-bg` | `--warn` at ~8–10 % alpha | Column-group shading for locked rooms; derived from `--warn` (a lock is caution, not a fault) |
| `--accent-soft` | `--accent` at ~10–14 % alpha | Focused/hovered matrix cell, current nav item, route chips |

Primitives, all from existing tokens: `.dot` (10 px status circle, `ok` /
`err` / neutral, always beside text), `.avatar` (a bundled icon is an
`<img src="/admin/static/avatars/<name>.png" alt="">` with `border-radius:
50%`, sized to its row — 16 px in matrix and list headers, 20 px in inspector
headers and the Avatar card, 40 px tiles with the name beneath in the picker
grid; custom URL or none is a dashed-circle SVG of the same size with a
`title`, never a fetched image), `.matrix` (sticky first column, group
headers), `.chip` (a smaller `.pill`), `.callout` (1 px `--line` border,
`--panel` fill, no coloured left bar), `dialog` (border, 8 px radius,
`--panel`, 40 % backdrop), `.skeleton`, `.notice`. Typography, radii, button
shapes, `.secret` and `pre` are unchanged.

---

## 7. Hard rules

| Rule | How it holds |
|---|---|
| #1 | The page builds no cards and reads no message content. The matrix, inspectors and `rooms` block are registry structure only. Test send stays fixed plain text through `/v1/notify`. |
| #2 | No stored secret or webhook URL is ever displayed: the page shows configured / missing, the source name, and the room id derived from the URL. The key leaves the server once, in the mint/rotate response, as today. `category` strings are fixed, never interpolated. Hash routes carry app and identity ids only. An identity's `avatar` is a bundled icon name or a public `https` image URL — never a secret and never a webhook URL — which is why it may be shown on the page and listed in `state` (D6). |
| #3 | No Google-facing code; no ledger flag moves. |
| #4 | Unchanged — CG-91's auth posture applies; tenant keys are still refused on `/admin/*` in `key` mode. |
| #5 | The `/healthz` field set is untouched. `admin.last_write_error` becomes more specific for the two refusals §5 gives new authored categories — still a fixed authored string, never a message (CG-90 fix round I2). Counting (`writes`, `refused`) is unchanged. *Controller's call, 2026-10-16; this row read "untouched" before the builder check.* |
| #6 | Widening still needs the typed id (428) and `inbound_locked` still refuses outright; the page now **says so before the write** and disables what it can predict, which narrows accidents without replacing any guard. `rooms.inbound_apps` is `apps_for_space` ∩ `allow_inbound`, the rule's own definition. |
| #7 | The page keeps writing `allow_inbound` as a real boolean on every save and never writes `inbound_locked`. |

---

## 8. Carries over unchanged

`el()` / `toNodes()` and the textContent-only rendering (`admin.js:18-39`);
`api()`, `detailText()`, `write()` with the sha and the *nothing-after-success-
may-throw* rule (`:44-63`, `:99-118`); `explain()` / `fail()` structure
(extended by `category`, not replaced); CG-91's probe, `signOut` and pill;
`lockedHolders()` generalised to `holders()`; `optionalField` / `readOptional`
absent-means-unchanged (`:177-188`, `:213-218`); `readAppFields` and its
ordered-identities rule for locked apps (`:220-241`); `withInboundConfirm`
(`:244-254`, now resolving through the dialog); the webhook guide and avatar
gallery link (`:14-15`, `:333-340`); `reveal()` content and `testSend()`
(`:415-462`); `copyKey` / `selectBox` (`:401-413`); `RULE_6`, `FILE_EDIT`; the
CSP headers; every existing endpoint and request body.

---

## 9. Testing

Offline pytest in the CG-88 style, then UAT with the tester agent.

- **`rooms` agrees with enforcement:** for a registry fixture with a shared
  identity, a locked tenant, two identities in one room and an identity with no
  space, `state().rooms[*].locked_by` equals the `locked` map
  `locked_space_violations` derives, `inbound_apps` equals `apps_for_space` ∩
  `allow_inbound`, and the empty-space entry has `inbound_apps == []` and
  `locked_by is None`. A single-site mutation of the derivation (e.g. dropping
  the `allow_inbound` filter) goes RED, applied alone with `__pycache__` cleared.
- **`inbox_pending`** equals `Inbox.pending_counts()` per app and is `0` with
  no inbox wired.
- **`category` on every refusal:** each 4xx the router raises carries a
  `category` from the agreed set; a test enumerates the raise sites (the
  `test_error_surfaces.py` technique) and fails on a site that lacks one.
  Secret-exposure test extended: no `category` string contains admin-supplied
  text.
- **Additivity:** every existing `state()` field is present and unchanged in
  shape; existing admin tests stay green without edits.
- **No stored secret in the page:** the existing exposure test extended to the
  new fields — `rooms`, `inbox_pending`, `category` never carry a value or URL.
- **CG-91's `test_the_admin_key_is_never_persisted_by_the_page` stays green**;
  a new assertion that no `localStorage`/`sessionStorage`/`document.cookie`
  reference appears in `admin.js` (hash routing stores nothing).
- **Static page checks:** `index.html` and `admin.js` contain no inline
  `on*=` handlers or `style=` attributes (CSP); `admin.css` defines the three
  §6 tokens in both schemes.
- **Avatar validation (D6):** the loader accepts a bundled name and an
  `https://` URL, refuses `http://`, a path, an unknown name and a non-string;
  `POST /api/identities` and the identity `PUT` apply the same rule before
  writing (422 with the field named); absent means unchanged on `PUT`;
  `state.identities[*].avatar` round-trips; the icon route serves exactly the
  bundled files and 404s anything else (no path traversal — a name is matched
  against the list, not joined onto a path); a custom URL equal to a bundled
  icon's raw URL is stored as the bundled name (R1).
- **Two homes, one guard (R2):** `assets/avatars/png/` and
  `src/chat_gateway/static/admin/avatars/` contain the same file names with
  byte-identical contents; `state.avatars` equals the sorted stems of the
  packaged directory.
- **No storage for board state (D5):** the collapsed-rooms set and selected
  app are page variables; the storage-reference test above covers them.
- **Suite count** measured on the branch at merge time and written here, not
  copied from `CLAUDE.md`: _to be filled by the builder_.

**UAT** (tester agent, browser mode, against `python scripts/admin_uat_server.py`
on `http://127.0.0.1:8099/admin`, whose fixture registry should be extended to
the handoff mockup's shape — six apps, a shared identity, a locked tenant, an
identity with no space — so each state below is reachable):

1. Board: the shared identity shows as a column with two dots; the locked
   tenant's rooms are shaded with the `locked by` pill; the no-room group
   carries its note; filter narrows rows and columns and reports counts;
   arrow keys move the focused cell and Enter opens the right inspector.
2. App inspector: unchecking a route target shows the routes note; checking a
   new-room identity on an inbound app shows the rule-#6 note and Save opens the
   dialog with the server's reasons; Confirm is disabled until the id matches;
   Escape cancels and focus returns to Save.
3. Locked app: grants read-only with the callout, Delete disabled with its
   reason, routes still saveable.
4. Identity inspector: Delete disabled while held; *Remove grant…* opens the app
   with the box unchecked and Save enabled; after saving, Delete enables and the
   dialog deletes. Replace webhook disabled with reason on a locked holder.
5. New app → *create a new identity* → back with the identity pre-checked and
   the draft intact → create → reveal: Select key selects, Copy falls through
   on HTTP, test send reaches a terminal status, Done returns to the app.
6. Hand-edit the UAT registry → Save from the page → 409 panel offers *Reload
   from disk* (by category) with the form kept → reload → Save succeeds.
7. ≤ 720 px viewport: cards replace the matrix; the dialog is a bottom sheet;
   the save bar is sticky.
8. Open mode (CG-91 flag set): no login, pill present, deep link `#/app/<id>`
   resumes after load; key mode: login shows, then the deep link resumes.
9. Dirty app inspector: change a route, then press Escape, type in the filter,
   click Board, and press browser Back — each opens *"Discard unsaved
   changes?"*; Escape in that dialog returns to the inspector with the edit
   intact; Discard completes the navigation; a clean inspector navigates
   without asking.
10. Board width (D5): on a laptop viewport the matrix's horizontal scrollbar is
    visible without scrolling the page; the app column and both header rows
    stay put while scrolling the region; all rooms start collapsed and show
    one column each; opening an app and returning expands only its rooms and
    highlights its row; Space on a focused room header toggles it and focus
    stays on that header; Enter on a collapsed column expands it; Expand all /
    Collapse all work and the count line updates; a reload returns to
    all-collapsed (nothing stored).
11. Avatars (D6): the new-identity stepper shows the picker first; picking an
    icon fills the URL box with the public
    `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/<name>.png`
    URL (never a gateway URL) and **Select URL** selects it; the board renders
    the same icon from the gateway's own `/admin/static/avatars/<name>.png`
    (check the request in the network tab); the created identity carries the icon on
    the board; on an identity page **Change avatar…** → pick → **Save avatar**
    round-trips through `state`; a custom `http://` URL is refused at the
    field; an identity with none shows the dashed mark.

---

## 10. Documentation

**This repo** (in the CG-92 PR):
- `docs/design-handoffs/admin-console-ux/` — stays as the visual reference;
  `overview.md` gains a dated line pointing here as the decided spec.
- `docs/registering-an-app.md` — the "console, if it is enabled" section
  describes the board and inspectors in two sentences; the runbook stays the
  fallback.
- `docs/integration-guide.md` — `/admin/api/state`'s `rooms` and
  `inbox_pending` fields, and the `category` list, if the guide documents the
  admin API; otherwise the CG-90 spec's §6 gains a dated annotation pointing
  here.
- `docs/superpowers/specs/2026-10-15-admin-console-design.md` §6 — a dated
  annotation: the page's shape is superseded by this spec; left standing.
- `docs/deploy/nas.md` — the CG-90 subsection notes that the console's UI
  changed and nothing about mounts, flags or secrets did.
- `CLAUDE.md` — one status bullet pointing here; nothing restated.
- `config/registry.example.yaml` — one identity gains `avatar: <bundled name>`
  with a comment naming the rule (bundled name or https URL; never a secret);
  `docs/consumers/pmtrader-registration-handoff.md` §3 (the field-by-field
  schema, written against `registry.py`) gains the `avatar` row; the runbook's
  §1 identity row drops the GitHub gallery URL in favour of the console's
  picker, keeping the gallery as the fallback for a gateway without the console.
- `assets/avatars/README.md` (or wherever `build.py` is documented) — the
  second output directory and the drift test (R2); `pyproject.toml` —
  package-data for `static/admin/avatars/*`.

**Homelab repo:** no change — no new env name, mount or secret.

**Sequencing** (*controller's call, 2026-10-16*): CG-92 branches from CG-91's
merge commit, not from `aeb210b`. CG-91's page tests pin exact substrings of
`index.html` and `admin.js`, and the rewrite treats them as **byte-for-byte
invariants**: `probePosture(`, `id="auth-mode"`, `<section id="login" hidden>`,
and the `api()` header lines that add `Authorization` only when a key is held.
A rewrite that renames or reflows any of them turns CG-91's suite red for a
reason that is not a regression; keep them verbatim and build around them.

**Rollout:** a rebuild and redeploy (`nas.md` §4); no registry or env change.
Merge is not in effect until the box runs the image; record the run in `nas.md`
§10.
