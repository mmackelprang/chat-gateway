# CLAUDE.md — chat-gateway

Project memory, loaded for every session here. Companion context: this repo
was extracted from the aiteam project's Google Chat design (aiteam
`docs/implementation-plan.md` findings F14 → F19) to serve **multiple**
agentic applications; aiteam's harness is the first consumer, not the owner.

## Hard rules — do not violate without explicit user sign-off

1. **Transport, never schemas.** The gateway owns identities, delivery,
   threading, and inbound routing. It never interprets or owns an
   application's message schema — apps send rendered content (text +
   Cards v2) in the envelope (`envelope.py`, the only shared shape). If a
   feature seems to need app-domain knowledge in the gateway, the answer is
   no — extend the envelope generically or keep it app-side.
2. **Secrets are env-only.** The committed registry holds env-var NAMES;
   webhook URLs (they embed `key`+`token`) and per-app API keys live only in
   the runtime env. Never log or echo them — error paths name the identity,
   not the URL.
3. **Google-facing code lives only in `adapters/`,** behind injectable
   transports with fakes for tests. Anything not yet exercised against real
   Google endpoints carries a ⚠ LIVE-UNVERIFIED docstring flag; remove the
   flag only after a real round-trip, and note the verification date.
   One further flag word, and only one: **⚠ SHAPE-VERIFIED `<date>`** means
   real captured bytes replayed offline — stronger than doc-derived, weaker
   than a live round-trip. It never replaces LIVE-UNVERIFIED, it accompanies
   it, and it clears nothing on its own.
4. **Per-app auth + identity allowlists.** Every request maps to one app via
   its key; an app may only send as identities the registry grants it. No
   shared keys, no identity wildcards.
5. **`/healthz` stays honest.** It reports real resolvability (env vars,
   keys, queue depth, monitor/subscriber liveness) — never a hardcoded OK.
   This rule exists because a sibling system's hardcoded health check hid
   11 days of silent capture failure (aiteam plan F18 gate 2).
6. **Inbound crosses to a consumer only by that consumer's explicit
   registry opt-in — and opt-out is absolute.** Two opt-in paths exist:
   passive inbox polling, and per-tenant `callback_url` push (added
   2026-07-24 for jobhunt's R3, at the user's direction). ⚠ **Since CG-88
   (2026-08-31) the opt-in is MECHANICAL rather than aspirational: the loader
   defaults `allow_inbound` to `false`, so an entry that says nothing grants
   nothing — rule #7 below.** `allow_inbound:
   false` disables *every* inbound path — inbox is a 403, events are never
   forwarded, and `callback_url` on such an app is a registry validation
   error (aitrader is locked out this way; its contract treats any two-way
   path as a security hole in a real-money system). The gateway never
   interprets an interaction into consumer semantics — it forwards whole
   events with a dedupe key; what an Approve *means* is enforced by the
   consumer's own write-path (jobhunt R4). Do not widen any tenant's
   inbound surface without explicit user sign-off naming this rule.
   App ids beginning with `_` are **reserved** for the gateway's own audit
   buckets (`_unrouted`) and are rejected at registry load. Registering one would
   have drained every unroutable and every `UNPARSEABLE` event, from every space,
   straight past this rule's checks — because the paths that write to that bucket
   bypass the per-app authorization block *by design* (an unparseable event has
   no space and cannot be authorized against anything).
7. **A security-relevant registry value defaults to the SAFE answer, and a
   written one is never coerced.** ⚠ **Added 2026-08-31 (CG-88) — numbered 7
   rather than inserted, because "hard rule #6" is cited across this repo and
   in two consumer contracts; renumbering would silently re-point every one of
   them.** It exists because its absence had already cost something twice over.
   `allow_inbound` defaulted to `True` for the life of this project, so rule
   #6's *"explicit registry opt-in"* was aspirational: `aiteam-harness` ran open
   for its whole life because it never mentioned inbound (CG-61), and
   `aitrader`'s published no-inbound guarantee was held by ONE YAML line in a
   file with three copies, only one of them in git. **Absence is now refusal.**
   And a written value must be a real boolean — `bool("false")` is `True`, so a
   quoted scalar used to grant exactly what it spelled a refusal of;
   `load_registry` refuses a non-boolean rather than coercing, which is
   `_require_id_str`'s existing treatment of the same YAML trap.
   ⚠ **The reliance is REPORTED, not fatal.** `Registry.inbound_defaulted` names
   every app that left the decision to the loader, on `/healthz` and as a boot
   warning. Making the key *required* was the stronger shape and was declined:
   a registry omitting it would refuse to load, and two of the three copies are
   unreadable from any checkout — `docs/consumers/pmtrader-registration-handoff.md`
   §6. **Reported is not enforced, and no document may say otherwise.**
   ⚠⚠ **ONE FIELD WAS FIXED, NOT THE CLASS. `allowed_users` is still
   *empty = anyone*** (`adapters/pubsub.py`'s `if app.allowed_users and …`) —
   filed as **CG-89** and deliberately not changed here, because unlike
   `allow_inbound: true` that default was CHOSEN and documented at the field.
   It is now reachable only behind an explicit inbound opt-in, which is
   narrower than it was, and **narrower is not closed**.

## Layout

`src/chat_gateway/` — envelope / registry / auth / inbox / service / client,
one concern each, plus `errors.py`, which owns which exception messages may be
printed in full (see below), and `mcp.py`, the opt-in MCP server surface (CG-80)
— a second ingress to `service.py`'s send path, not a second send path;
`adapters/` — webhook (tier 1), chat_api + pubsub (tier 2);
`iac/` — gcloud script (`.sh` + Windows `.ps1` sibling) + terraform; `docs/` —
Google Cloud setup + integration guide. Tests: `python3 -m pytest` on POSIX,
`python -m pytest` on the Windows dev box (its msys `python3` has no pytest;
`python` is 3.13.7) — offline, 511 passing.

## Current status (2026-07-31)

- **First real Chat event received 2026-07-29.** It arrived in the Workspace
  Add-ons envelope (`commonEventObject` + `chat.messagePayload`), which the
  v0.1 parser — written for the classic flat format — silently normalized into
  an empty MESSAGE husk. Fixed: `normalize_event` now detects and normalizes
  BOTH envelope formats to one internal shape, and raises rather than
  defaulting on anything it does not recognize. Unparseable events are audited
  under `_unrouted` as `UNPARSEABLE`, counted at `/healthz`, and still acked so
  they cannot wedge the subscription.
- Core + all adapters + service + client built and tested offline (the count
  lives in **one** place — the Layout section above; it was stale at `98` here
  while that line read `202`, which is what a second copy of a moving number
  always does), including the aitrader contract surface: /v1/notify (severity
  routing/rendering, dedupe windows, async dispatcher with retry backoff +
  per-source delivery log, titles-only logging) and /v1/heartbeat (dead-man
  monitor; tz-aware `weekdays` schedule rolls weekend due-dates to Monday;
  ~~daily repeat~~ **escalating repeat, one Chat thread per check and an
  all-clear on recovery — corrected 2026-08-31 (CG-86)**; JSON-persisted
  checks). US market holidays deliberately not
  modeled (contract says widen grace).
- **BOTH queues are durable, since CG-54 (#45, 2026-07-31)** — outbound
  delivery *and* the inbound inbox, which the brief's scope missed. Undelivered
  jobs and unpolled replies are journalled as JSONL under
  `CHAT_GATEWAY_STATE_DIR/queue/` (env-var NAME, hard rule #2) and **replayed at
  boot with the attempt count preserved** — preserving it is what stops a crash
  loop from resetting the backoff ladder every boot and hammering Google.
  This bullet read *"Queue is in-memory (restart drops undelivered jobs —
  visible in the log; accepted v0)"* until 2026-07-31; that was true for v0 and
  false the moment #45 landed. It was left standing for hours **on purpose** —
  CG-60 was rewriting this same file concurrently, and a stale bullet for a few
  hours is cheaper than a merge conflict eating a careful edit — and corrected
  as CG-64.
  **The replay rule and the journal's rationale have one home each, and neither
  is here:** `delivery.py`'s
  docstring states it (open-minus-close; `expired` past the ceiling;
  `unroutable` when the registry no longer grants the identity, hard rule #4;
  mid-flight replayed and therefore possibly delivered twice), and
  `journal.py`'s says why the per-app audit files cannot answer the same
  question — they record what ARRIVED, never what LEFT. Do not restate either
  here; a second copy of this is exactly what the test count above did.
  **Retention, not just durability (CG-65, 2026-07-31):** a journalled body now
  lives exactly as long as its job is replayable — the journal compacts when the
  queue drains, so a *delivered* body's residency fell from the weeks ADR-0002
  §2.2 measured to seconds. Both audit trails are created `0600`. An unrevivable
  reply is preserved under `<state_dir>/quarantine/`, which is never pruned,
  because the per-app audit trail should never have been *"the only copy"* of a
  record the gateway was holding in its own hands at the moment it dropped it.
  Numbers and reasoning: ADR-0002 — **not restated here.**
  **And the "forever" ended too (CG-68, 2026-08-02) — the first change in this
  repo that DELETES a tenant's content.** `inbox-data/<app>-<date>.jsonl` is now
  swept on a time bound; the filename **is** the retention key, so pruning is a
  directory listing and an `unlink`, and nothing ever opens a file holding
  message bodies to decide whether to delete it. **The window has one home and
  it is not this file** — `retention.py`'s constants, quoted to consumers at
  `docs/integration-guide.md:366`, which is the *published* guarantee this row
  amended from *"never pruned"* (sign-off A4). Do not copy the numbers here;
  that is precisely what the test count above did.
  **What must NOT be inferred from the sentence above:** `<state_dir>/quarantine/`
  is still never pruned — it is what makes the sweep safe — and
  `<state_dir>/deliveries/` is untouched by decision (ADR-0002 **D7**). Both are
  now enforced in **code**, not by where two env vars happen to point: the
  sweeper **refuses to boot** if its directory overlaps the state dir, and skips
  the quarantine's filename by name even then. That refusal is deliberately
  stricter than the non-recursive glob requires — **a user decision, 2026-08-02**
  (queue CG-68, decision 4), on the reasoning that "currently harmless" is a
  property of one line of code and a warning nobody reads becomes tenant data
  loss. `/healthz` publishes `files_deleted`, which **never** degrades `status`
  — a retention policy working is not a fault, the same reasoning recorded for
  `suppressed_opt_out` below — while `delete_errors`, consecutive sweep failures
  and a dead sweep thread all do.
- **The dead-man switch had SIX doors to a silently-dropped alert, not one
  (CG-76, 2026-08-03).** `HeartbeatStore.due_alerts` recorded *"I have alerted"*
  before anything was alerted — a promise about the future persisted as a
  statement about the past — and each door was a different way for the future
  not to arrive, or for `/healthz` not to notice that it hadn't. **Five of the
  six raised nothing**, so `scan_failures` stayed `0` and `/healthz` answered
  `ok`; on the worst of them **not one field in the entire body moved.** The
  mark now happens in `mark_alerted`, after the alert is accepted into the
  durable queue, which moves this path from at-most-once to **at-least-once** —
  the posture `_finish`, `_journal_write` and `Inbox._audit` each already took,
  for the reason each of them records. ⚠ **`scan_failures` still degrades but
  its ORIGINAL justification expired**, and the weaker surviving one is stated
  at `HeartbeatMonitor.__init__` rather than the strong one being re-quoted —
  the same discipline this file applies to `__cg_action__`. Do not summarize the
  six doors anywhere; the enumeration and its measurements have one home,
  `docs/superpowers/specs/2026-08-03-dead-man-alert-loss-design.md` §2. ⚠ **The
  count itself is the finding worth carrying:** four rounds of looking produced
  four different answers, and it is six rather than four only because somebody
  was asked to check the checker (spec §0).
- **And it alerted into the void for its whole life — the dead-man path never
  set a `thread_key` (CG-86, 2026-08-31).** `Notification.thread_key` is a
  declared field and `render` propagates it on both branches; `_monitor_notify`
  simply never set one, so every dead-man alert this project ever sent was an
  unthreaded top-level post, re-posted byte-identically every 24h for as long as
  a check stayed missed. **There was also no all-clear at all** — a missed→ok
  transition delivered nothing. ⚠ **The finding worth carrying is not the
  threading, it is that SEVERITY PICKS THE SPACE:** `route_for` is
  `routes.get(severity) or routes.get("default")`, and `aitrader`'s `alert` and
  `info` routes are two different identities, so a quiet-rendered all-clear
  would have posted into a room where nobody watching the alert could see it.
  `emit_notification` gained `route_severity` and every monitor message now
  routes `alert` whatever it renders as — **threading and routing are one
  decision, and anything that splits them re-opens this.** Do not restate the
  cadence here; it has one home, `docs/consumers/aitrader.md` §7, and the design
  is `docs/superpowers/specs/2026-08-31-dead-man-message-policy-design.md`.
- **`allow_inbound` defaulted to `True` — omitting the key was "on", not "off"
  (CG-88, 2026-08-31, owner ruling).** The rule has ONE home and it is **hard
  rule #7 above**; do not restate it here. What belongs in a status list is what
  the change measured. ⚠ **TEN existing tests failed the moment the default
  flipped** — six in `test_adapters.py`, four in `test_service.py` — every one
  of them an *inbound* assertion that had been resting on a default nobody
  chose. That is the honest size of what the old value was holding up, and it
  was invisible until it moved. ⚠ **And one new control was GREEN on its first
  mutation:** flipping the `App` dataclass default back to `True` left the whole
  suite passing, because `load_registry` now passes the field explicitly on
  every path — two sites, and only one of them was bound (0h). It has its own
  test now. ⛔ **AND ONE MEASURED OUTAGE PATH, which is NOT the quoted boolean:**
  an app with a `callback_url` and **no** `allow_inbound` **loaded before this
  change and refuses after it** — `callback_url requires allow_inbound: true`
  now fires, and here a registry that does not load means `main` exits 2 and the
  gateway does not start. **Producible by OMISSION**, so it is the realistic one;
  both readable copies are safe and the third cannot be read (0d). The refusal
  names CG-88 and the one-line fix. ⚠ **Merged is not in effect, again**
  (CG-61's lesson, CG-80's repeat): the default is applied at **load**, so a
  running gateway keeps the posture it booted with and the NAS gets this at its
  next redeploy — **which is also when this outage path would first be able to
  bite.**
- **The live project is `chat-gateway-gw` (`#860649224827`), and it is the only
  one.** `chat-gateway-prod` — which every "Cloud resources now exist" note in
  this file used to describe — was **deleted 2026-07-30**, along with E1's
  throwaway project. Chat + Pub/Sub APIs enabled (no billing needed), the
  `chat-gateway` SA, the topic and the pull subscription all exist on `gw`; the
  live SA key is **`chat-gateway-sa-gw.json`**. ⚠ **The key that authenticates is
  that one and only that one.** Any *other* `chat-gateway-sa*.json` — in an old
  checkout, a backup, a stale clone — belongs to the deleted `chat-gateway-prod`
  and will not authenticate; do not try, and do not treat finding one as
  configuration.
  ⚠ **REWORDED 2026-08-05 (CG-79), not dropped.** This read *"`iac/chat-gateway-sa.json`
  is **dead** … do not treat **its presence** as configuration"* — and **that file
  has since been deleted**, so a warning phrased around its presence now describes
  nothing. CG-55's row set the condition explicitly (*"the deletion is the user's;
  when it lands, both need **rewording, not dropping** — a warning that simply
  vanishes is indistinguishable from one nobody thought about"*) and CG-55's
  Builder deliberately left it standing because the deletion had not landed then.
  It has. **The warning is now phrased against the key SHAPE rather than one path,
  because the path is gone and the hazard is not:** copies of that dead key exist
  outside this working tree and nothing here can delete those.
  **Provisioning is not verification** — see below.
- **The live Chat app is in FOUR spaces, not one — corrected 2026-07-31 (CG-60).**
  A **user statement about the Google Chat console**, which this repo cannot
  verify and has not measured: **"Agent Comms" is deprecated** (it was
  workspace-specific), replaced by an app named **"Chat Gateway"** — same
  functionality, better interaction support — participating in FamilyWorkspace,
  Ai Trader, Ai Trader Reports and JobHunt. Space membership is readable nowhere
  in this repo (the registry's `space:` is a *posting target*, not a membership
  record), so the dated snapshot has exactly **one** home:
  `docs/google-cloud-setup.md` step 6. Do not copy it here — that is the same
  two-homes-for-a-moving-fact trap as the test count above, and this one went
  stale in a single day.
  **The consequence IS measured, and it is the part that bites.** Running the
  real `apps_for_space` against the **live** (gitignored) `config/registry.yaml` —
  not the example, which differs and has caught three people — returns
  `['aitrader']` with `allow_inbound: false` for **both** Ai Trader spaces. So
  **every message or card interaction there now increments `suppressed_opt_out`
  on an unauthenticated `/healthz`.** Hard rule #6 is untouched: the `continue`
  fires before any `inbox.put`, so nothing crosses to aitrader. What moved is a
  bare counter — see the CG-12 bullet below, whose recorded caveat this promotes
  from hypothetical to live. `docs/consumers/aitrader.md` §8 **predicted this
  exact trigger** and now records it as live; the prediction is kept there
  verbatim rather than deleted.
- **The add-ons → classic migration is DONE, and it is now IRREVERSIBLE**
  (ADR-0001 D7; reconciled 2026-07-30 as CG-21). Production cut over
  **2026-07-29** to a classic Chat app; `action.id` arrives natively and the
  undocumented topic-as-function dependency is gone from the live path. D7's
  stated rollback — *"switching two env values back"* — **expired** when
  `chat-gateway-prod` was deleted a day later: there is nothing left to point
  `CHAT_GATEWAY_PUBSUB_SUBSCRIPTION` and `GOOGLE_APPLICATION_CREDENTIALS` at,
  and E2 proved a classic app cannot be toggled back. Reverting now means a
  **third project** plus fresh console work — a new migration, not a rollback.
  Reversibility was real while both projects existed, which is what made cutting
  over safe; it was then spent deliberately. Env-var NAMES only here — values
  live in the runtime env (hard rule #2).
- **Verification ledger** (was "⚠ LIVE-UNVERIFIED"; renamed 2026-07-30 because
  most of it is now cleared and a list titled after the flag invites a reader to
  assume everything under it still carries one).

  **What is still unexercised against Google — the complete list, because a
  one-line summary of this was drafted as "every adapter's error branches, and
  nothing else" and that was FALSE:**

  | Surface | Note |
  |---|---|
  | every adapter's **non-200** branches (`webhook.send`, `chat_api.send`, `chat_api.send_text`, `pubsub._post`) | no Google error response has ever been observed |
  | `webhook.send`, `chat_api.send` and `chat_api.send_text`'s **`httpx.HTTPError`** branches | none of the three has ever been exercised against Google |
  | **`chat_api.send()`'s `thread.threadKey` threading branch** | a **success** path, not an error path. The live `send()` posts were unthreaded, and `send_text()`'s clear does not reach it — different field, different request shape. |
  | **`pubsub.pull()`'s `_undecodable` branches** | malformed-payload handling. Nothing on the live subscription was malformed, so both stay reasoned-about. |
  | **`SubscriberLoop`'s long-run thread behaviour** | not a branch at all — no multi-hour live run has happened. |
  | **whether `messageReplyOption` is required at all** (webhook threading) | not a branch either — an unisolated *variable*. All three live threading variants included it, so "either `threadKey` location suffices" is only proven *given* it is present. The fourth variant was never run. |

  **Scope of this table: every surface where behaviour against Google is not
  established — not "code branches".** Two rows are not branches at all, and
  that is deliberate: an unisolated experimental variable and an unobserved
  long-run behaviour are both things a reader could otherwise assume were
  settled.

  Kept as a table rather than a sentence precisely because the sentence was
  wrong twice. First draft: *"every adapter's error branches, and nothing
  else"* — which omitted the two success-path rows. Second: the same shorthand
  survived in `docs/consumers/jobhunt.md` after being corrected here. "Error
  branches" is the *majority* of the residue, which is exactly what makes the
  shorthand tempting and inaccurate. **Do not re-summarize this table anywhere.
  Link to it.**
  - Events DO reach the subscription — proven 2026-07-29, and re-proven
    2026-07-30 through our own `PubSubPuller` rather than an ad-hoc client.
  - **CLOSED BY CIRCUMSTANCE, not answered — stop carrying it as open work:**
    which principal published those events. Both
    `chat-api-push@system.gserviceaccount.com` and the add-ons service agent
    `service-<PROJECT_NUMBER>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com` were
    bound in `chat-gateway-prod`, and **that project is deleted**, so the
    question can never be settled. (GCP also accepts bindings to
    `*@system.gserviceaccount.com` principals **without validating they exist**,
    so a clean apply was never evidence either.) It is not a flag, not a gap to
    close, and not a task — it is an unanswerable question about a system that no
    longer exists. The IaC still binds **both** principals and its comments
    explain why, so a fresh-project operator is not stranded by this being closed.
  - **Narrowed by architecture on the live project, though — labelled as
    inference, not verification.** `chat-gateway-gw` runs a **classic** Chat app
    with **no `gsuiteaddons` deployment at all**, so the add-ons service agent has
    nothing to publish through there. Events demonstrably arrive (proven through
    our own `PubSubPuller`, 2026-07-30). It therefore follows that the
    **Chat-API-side publisher is the operative one on `gw`**, and that the
    add-ons binding the setup script also applies is **vestigial** on a classic
    project. That is a deduction from the deployment model, not an observation of
    which principal wrote the message — it does not clear anything, and it does
    not retroactively answer the `prod` question. It is recorded because it is
    the actionable half: a fresh classic project needs the Chat-API publisher
    binding, and the add-ons one is carried only for a runtime we no longer
    deploy on (see CG-19).
  - `PubSubPuller.pull()` / `.acknowledge()` — ⚠ flag CLEARED 2026-07-30, both
    halves, through the real class. `pull()` returned real `(ack_id, event)`
    tuples fed straight into `normalize_event`. `acknowledge()` was proven
    **selectively**: acking one id removed only that message while two other
    unacked ids kept redelivering across a 60s poll — which proves the *right*
    message was acked, not merely that the subscription drained. Not covered:
    `_post`'s non-200 branch and the `_undecodable` branches.
  - Add-on **CARD_CLICKED** — a real interaction WAS captured 2026-07-29 and is
    now ⚠ SHAPE-VERIFIED (tests/fixtures/addon-buttonclicked-event.json). It
    found a defect rather than confirming the mapping: `action.id` normalizes to
    "" because the card's routing pattern consumed the function slot. Params
    (including selection-widget values) are correct. Not a live-round-trip clear
    — the capture was pulled with an ad-hoc client. jobhunt R3/R4 remain
    unverified; see queue item CG-10.
  - Webhook **send** — ⚠ flag CLEARED 2026-07-29, re-confirmed 2026-07-30.
    Verified through the real `WebhookAdapter`: text delivered, Cards v2 passed
    through and confirmed rendering. The threadKey param-vs-body question is
    settled — both work, we keep the body form. **Tier 1 is
    project-independent, now empirically:** all four webhook identities returned
    `delivered` through the real class *immediately after* `chat-gateway-prod`
    was deleted, so no tier-2 deployment change can take the notification path
    down. Not covered: the non-200 and transport-error branches. Whether
    `messageReplyOption` is required at all was NOT isolated.
  - Chat API **send()** — ⚠ flag CLEARED 2026-07-29 (real `ChatApiAdapter` +
    real `GoogleServiceAccountTokens`; text and Cards v2 posted as the app;
    response carried `sender: {displayName: "Agent Comms", type: BOT}`). Not
    covered: its `thread.threadKey` threading branch — the live posts were
    unthreaded — and its error branches.
  - **Naming note, 2026-07-31 — NOT a ledger entry, and it moves NO flag.** The
    `displayName` in the row above is what that response really carried on
    2026-07-29; the observation stands and is deliberately left byte-for-byte as
    written. What has changed since is the app, not the evidence: per a **user
    statement about the Google Chat console** — which this repo cannot verify and
    has not measured — **"Agent Comms" is deprecated** (it was workspace-specific)
    and the live app is named **"Chat Gateway"**. The dated console snapshot lives
    in `docs/google-cloud-setup.md` step 6 and is **not copied here**, because a
    console fact with two homes drifts (the same lesson as the test count above).
    **Nothing is cleared, added or reworded by this note.** Whether replacing the
    app re-prices any clear in this ledger is a hard-rule-#3 question requiring
    the user's explicit sign-off; it is **filed as CG-62**, not decided by a docs
    row.
  - Chat API **send_text()** — ⚠ flag CLEARED 2026-07-30, **both branches**:
    in-thread (`spaces/AAQAgjGR7J4/threads/_CWBxuQ8MlU`) and top-level
    (`thread_name=None`). They matter separately — in-thread is jobhunt R7's
    failure notice and R4's authorization refusal, top-level is the no-thread
    fallback. This **supersedes the CG-5 plan**, which predated the live session
    and expected this method to keep its flag. It threads by `thread.name`, so
    this clear does **not** extend to `send()`'s `thread.threadKey` branch. Not
    covered: its non-200 branch.
  - The add-on **MESSAGE** and **buttonClicked** shapes are ⚠ SHAPE-VERIFIED
    2026-07-29 (real captured bytes replayed offline,
    `tests/fixtures/addon-message-event.json`,
    `tests/fixtures/addon-buttonclicked-event.json`). That is not a
    live-round-trip clear and does not remove any flag above.
  - The **classic** envelope is ⚠ SHAPE-VERIFIED 2026-07-30 for **CARD_CLICKED**
    (both trigger kinds — a button tap, and a selection widget's
    `onChangeAction` on a card with **no button at all**) and for
    **ADDED_TO_SPACE** (real captures from `chat-gateway-gw`, replayed offline:
    `tests/fixtures/classic-cardclicked-button-event.json`,
    `classic-cardclicked-onchange-event.json`,
    `classic-added-to-space-event.json`). Scoped deliberately: classic
    **MESSAGE** is still CONSTRUCTED, and classic `thread.threadKey`,
    APP_COMMAND, REMOVED_FROM_SPACE and WIDGET_UPDATED are untouched. Like every
    ⚠ SHAPE-VERIFIED entry this **clears nothing** — the events were replayed
    offline, and while two of them were also normalized live off the
    subscription, that was an ad-hoc diagnostic script, not the gateway's
    `dispatch` path.
- **`__cg_action__` — the one inbound-direction envelope field** (ADR-0001 D2,
  user-approved 2026-07-29; shipped as CG-10). Under the add-ons runtime a
  card's `action.function` is the interaction's *destination*, so a card that
  routes to our Pub/Sub topic consumes Google's action-identity slot and none
  arrives. Producers therefore declare identity in a gateway-reserved card
  parameter; the gateway lifts it into `action.id` and pops it out of `params`.
  Rule #1 holds because the gateway defines the key NAME and never reads the
  VALUE — no branch, no permitted-id enum — exactly as `thread_key` works
  outbound. The whole `__cg_` prefix is reserved; unknown `__cg_*` keys pass
  through rather than being eaten. Unresolvable identity is `None`, never `""`,
  is counted at `/healthz`, and is still forwarded.
  **Reframed 2026-07-29 after experiment E1 passed: this is a FALLBACK, not the
  primary mechanism.** A classic (non-add-on) Chat app on Pub/Sub supplies
  action identity *natively* — live-verified, an ordinary function name
  `approve` arrived as `action.id: 'approve'`.
  **The migration is DONE — corrected 2026-07-30 (CG-21).** This paragraph said
  classic was "the preferred destination", that "a migration is underway", and
  that `__cg_action__` was "load-bearing on the runtime deployed **today**".
  Classic is not a destination, it is **production, since 2026-07-29**. Every
  project that ran add-ons is deleted, so nothing in production *depends* on
  this key.
  **It stays anyway, and the reason is now the weaker one — say so rather than
  keep quoting the strong one.** On classic it is **not needed**: identity
  arrives natively without it. **"Not needed" is not "not used", and the two
  must not be collapsed** — ADR-0001 (D2 row, §12) and
  `docs/integration-guide.md` all say *"inert"*, always paired in the same
  breath with *"still wins when present"*, and that pairing is load-bearing. The
  key is checked **first and unconditionally** — *"app-declared, authoritative
  when present"* (`adapters/pubsub.py:376`) — so on a card that carries it, it
  is still the operative source of `action.id` on classic. Read *"inert"*
  anywhere in this repo as *"a producer need not add it"*, never as *"the
  gateway ignores it"*. That is exactly why it stays: one card behaves
  identically on either runtime, which is the whole D3 portability payoff and
  what made the migration cost zero producer card changes. Same support-both
  posture as the two envelope formats — **do not rip it out**, but do not
  justify it as load-bearing either.
- **The gateway is an MCP server too, since CG-80 (2026-08-10) — send-only, and
  that is a decision rather than a stage.** `POST /mcp` is another ingress to the
  path `POST /v1/messages` already uses: same `authenticate()`, same
  `registry.identity_for`, same adapter, **same `DeliveryLog` row**. Default OFF
  behind `GATEWAY_ENABLE_MCP` (env-var NAME; it holds no credential, so it is a
  compose value rather than a secret). **Hard rule #1 holds mechanically, not by
  taste** — the one tool's `inputSchema` is GENERATED from
  `OutboundMessage.model_json_schema()` and a test compares it for equality, so a
  hand-edited property turns the suite red. `cards` stays an opaque array; a
  card-builder tool is the thing rule #1 exists to refuse.
  ⚠ **The audit row is the one place the plan's code contradicted the plan's own
  goal, and it was caught in build rather than in review.** The spec's §2 table
  and the plan's Goal line both promise an MCP caller inherits audit journalling;
  the plan's `call_tool` took no `DeliveryLog` and wrote nothing. Fixed in the
  shipping code with `describe_exception` on the failure detail rather than the
  `str(exc)[:200]` its `/v1/messages` sibling still uses — **a new write site gets
  the current rule, and the old one was deliberately not touched** (spec §15
  forbids changing that route).
  **There is no inbound tool and the reason is protocol-level, not a backlog
  item:** MCP servers cannot send requests, cannot send unsolicited notifications
  and cannot cause a model turn, so an inbound tool could only be polling. It is
  also blocked on `Inbox.poll` draining — until CG-56, an MCP reader and a
  tenant's poller are competing DESTRUCTIVE consumers of one queue. **Do not
  restate the rule #6 argument here; it is argued both ways in
  `docs/superpowers/specs/2026-08-06-mcp-server-surface-design.md` §7**, and
  `read_inbox` is filed as CG-81 needing the user's explicit sign-off.
  ⚠ **Dual-era, and that is load-bearing rather than belt-and-braces.** Revision
  `2026-07-28` deleted `initialize`, `ping` and sessions; a modern client cannot
  talk to a legacy server and a legacy client cannot talk to a modern one, so
  serving one era would make this endpoint **silently unreachable** to the other.
  Which revision is "current" is a moving external fact and gets **no copy here**
  — the two dated identifiers are pinned as constants in `mcp.py` and nowhere
  else.
  ⚠ **`CACHE_SCOPE` is `"private"` and it is a hard rule #4 control, not a
  performance knob** — the tool list varies by API key, so `"public"` would let
  an intermediary serve one tenant's identity allowlist to another. Reasoning
  has one home, that constant's own comment.
  ⚠ **Merged is not in effect, again.** The surface ships with **no caller**:
  `registry.example.yaml` gains an `agent-mcp` template, but minting the key and
  writing the app into the gitignored `config/registry.yaml` is an operator
  action. CG-61's lesson, and ~~**it is not deployed** — this row was merged
  deliberately without a rebuild, because the rebuild spends uptime evidence
  CG-82 task 1 must capture first.~~
  ✅ **IT IS DEPLOYED, ENABLED AND EXERCISED SINCE 2026-08-11 — the struck clause
  was true for one day.** The operator minted the key, wrote `agent-mcp` into the
  live registry and turned the surface on; it has since **delivered a real
  message** and **refused an identity it was not granted, live**. The record has
  ONE home and it is not this file: `docs/deploy/nas.md` §10, the **2026-08-11**
  entry. Do not copy its job ids, image digest or probe results here.
  ⚠ **The struck reason is worse than expired, and that is the part worth
  carrying:** the rebuild did **not** spend the uptime evidence. `dockerd` on the
  NAS died on 2026-08-10 and the container did not survive, so the streak was
  **lost rather than spent** and **CG-82 task 1 cannot be discharged**. A
  sentence that reads *"deferred for a good reason"* can be falsified by the
  reason evaporating rather than by the decision being wrong.
  ⚠ **One live consequence for a real-money tenant, recorded because D7 declined
  the alternative:** there is no registry `allow_mcp` flag, so an app's
  `identities:` list is the **only** thing narrowing what an MCP caller may send
  as. `agent-mcp` was granted **one** identity and `aitrader-*` deliberately not.
  Hard rule #6 is untouched — this is strictly outbound — but adding an identity
  to that app is widening a model-addressable surface, not editing a config line.
  ✅ **Dual-era is answered by measurement, not argument: BOTH eras are
  load-bearing**, and asymmetrically — legacy negotiates from a bare
  `initialize`, modern refuses to move without three headers and two `_meta`
  keys. D4a is settled; stop carrying it as an open question.
  **No ⚠ verification-ledger flag moved** — ⚠ **including on the day of the live
  round trip, which is exactly when the spec predicted somebody would want to
  move one.** This sits above `adapters/` and makes
  no Google call of its own; a live round-trip through the tool is the same bytes
  from a different caller and clears nothing.
- **Card `parameters` shapes — outbound is fixed, inbound is a property of the
  RUNTIME.** Confusing them ships a broken card.

  | Direction / runtime | Where | Shape |
  |---|---|---|
  | outbound, every runtime | `onClick.action.parameters` | **array** of `{key, value}` (Cards v2) |
  | inbound, **classic** | `action.parameters` | **array** — symmetric with what you sent |
  | inbound, **add-ons** | `commonEventObject.parameters` | **map** |

  Every row is first-hand. Do **not** compress this to *"you send an array, you
  receive a map"* — that was briefly written down and it is wrong: the map is an
  add-ons quirk, not a property of the inbound direction, and a producer
  debugging a raw classic event after being told otherwise would conclude the
  gateway was broken. `_action_params` normalizes either, so producers only ever
  need the first row. Pinned by
  `test_card_parameters_are_an_array_in_the_real_captured_card` and
  `test_inbound_parameter_shape_is_a_runtime_property_not_a_direction_rule`.
- **Suppressed inbound is COUNTED, never RECORDED** (CG-12; user decision
  option A, 2026-07-29). A space whose registered owners are **all**
  `allow_inbound: false` used to discard events with **zero** forensic trace:
  `candidates` is non-empty so the `_unrouted` fallback never fires, every
  candidate hits an authorization `continue`, and nothing was written anywhere.
  Hard rule #6 was satisfied; rule #5's spirit was not. `dispatch` now takes an
  additive `on_suppressed(app_id, reason)` callback — mirroring `on_unparseable`
  — feeding two **bare integers** at `/healthz`: `subscriber.suppressed_opt_out`
  and `subscriber.suppressed_not_authorized`. No space, no app id, no content,
  no timestamp, because **`/healthz` is unauthenticated**; the alternatives (a
  metadata-only record, a full `_unrouted` audit record) were considered and
  **rejected**, so `aitrader`'s traffic is still never persisted anywhere.
  Accepted with eyes open, and recorded rather than claimed away: with exactly
  **one** `allow_inbound: false` tenant registered — today's deployment —
  `suppressed_opt_out` is a de-facto unauthenticated activity meter for that
  tenant **by inference**, though no field names it. Taken as **volume-only**,
  and marginal beside `events_seen`, which already publishes total inbound
  volume on the same endpoint.
  ⚠ **That caveat stopped being hypothetical on 2026-07-31** (CG-60): the Chat
  app is now in both Ai Trader spaces, so the counter **does** move on that
  tenant's traffic rather than merely *would if*. The accepted-with-eyes-open
  reasoning above is unchanged and is why this is a note rather than a reopening —
  what changed is the tense, and ~~the user's D2 decision responds to it by fencing
  `/healthz` behind the homelab tailnet ACL **before** the first deploy.~~
  ⚠ **That last clause is FALSE and is corrected here, 2026-08-05 (CG-79).** The
  user **deferred** D2's ACL on 2026-08-03 — still wanted, no longer gating — and
  the first deploy went ahead on 2026-08-05 **without it**. What actually fences
  the endpoint is the paired decision taken the same day: **CG-55 binds the
  published port to the LAN address rather than `0.0.0.0`**, so a tailnet peer
  cannot reach `/healthz` whatever the ACL says. Both halves, their reasoning and
  the residual have **one home** — `docs/BUILDER_QUEUE.md` § CG-55, *"Two user
  decisions, 2026-08-03"*. **Read the residual there, because the bind is a
  narrower guarantee than the ACL was:** `/healthz` is unauthenticated and
  reachable by anyone on the **home LAN**, which the ACL never governed either.
  ✅ **The "exactly ONE tenant" condition is ENDED — CG-61's operator edit landed
  2026-08-03** (`config/registry.yaml` mtime `2026-08-03T20:34:06Z`; re-measured
  through the real `load_registry` on 2026-08-05, `aiteam-harness
  allow_inbound=False`, with `allow_inbound: false` now **written explicitly**
  rather than defaulted). ~~**but NOT YET.** A PR
  cannot touch the gitignored `config/registry.yaml`, which when measured
  2026-07-31 still granted `aiteam-harness` inbound — **by the default; the key
  is absent from that file**, which is D1's whole reasoning.~~ **So a second
  tenant is now opted out and `suppressed_opt_out` POOLS their traffic — it no
  longer decomposes to `aitrader`.** That is a real change to what this
  unauthenticated endpoint discloses, and it is the mitigation this paragraph
  predicted, now in the past tense. **Partial mitigation, not complete**, and not
  a reason to skip the ACL: arc spec §7 D2. That operator edit falsified the
  "not yet" in **two** places — here and `adapters/pubsub.py`'s counter comment —
  ✅ **and both were corrected together on 2026-08-05, which is the only reason
  the second one moved at all.**
  Two integers rather than one because the reasons are different investigations
  — `opt_out` is rule #6 working as designed, `not_authorized` is a real human
  refused (jobhunt R4, newly reachable in production since `job-hunter` gained
  an `allowed_users` list). Each counts **candidate apps that declined an
  event**, not events that went nowhere: an opted-out owner increments even when
  a co-owner of the same space *received* that same event, and `events_seen` is
  the event count. Deliberately **not** inputs to `status` — a guarantee working
  is not a fault, and degrading on one teaches an operator to ignore `degraded`.
  That per-counter verdict is now a standing requirement rather than this
  bullet's one-off: every counter added since is decided explicitly, one at a
  time, and the reasoning for the delivery and heartbeat loops' failure counters
  — including why one of them degrades cumulatively where its twin does not —
  lives in `docs/superpowers/specs/2026-08-03-delivery-write-path-robustness-design.md`
  §5, with the field-by-field table in `docs/integration-guide.md`. One home
  each; do not restate either here.
- **An exception message is printed in full only if this repo wrote every byte
  of it** (CG-29, 2026-07-30). Hard rule #2 made the subscriber name exceptions
  by TYPE — a pydantic `ValidationError` embeds the input it rejected, and these
  events carry capability URLs — and CG-23 went further, stripping
  `resp.text[:200]` out of two adapters after a real 403 put a webhook's `key`
  and `token` into three artifacts. That rule then discarded what CG-25 had just
  paid for: `send_text()` gained a typed transport error, so transport failure
  and non-200 both reached the console as `ChatApiError` and nothing else.
  `errors.py` now marks the classes whose messages this repo authors
  (`ChatApiError`, `WebhookDeliveryError`, `UnrecognizedEventError`, and
  `PubSubError` since CG-33) and `describe_exception` prints those in full,
  everything else by type alone.
  **An ALLOWLIST, deliberately** — a denylist of known-unsafe types prints the
  next unanticipated exception once, and losing detail is recoverable where a
  webhook credential is not.
  **`PubSubError` was excluded by CG-29 and joined the set in CG-33
  (2026-07-30) — one decision, made twice, and the second time is not a
  reversal of the first.** CG-29 kept it out because `_post` passed
  `resp.reason_phrase`, which httpcore fills from the literal HTTP status line,
  so its `str()` carried server-controlled bytes — measured, and the opposite of
  what its own docstring claimed. CG-33 replaced that with the same local
  `httpx.codes` lookup CG-23 gave the two sibling adapters, and the class
  qualified. **The two halves are coupled and the order is load-bearing:**
  marking it while `_post` still read the wire would hand those bytes to any
  print site through `describe_exception` — measured as the counterfactual, so
  never split the marker from the lookup.
  **What marking BUYS is not symmetry, it is the guard.**
  `tests/test_error_surfaces.py` reads the construction sites of marked classes
  **only**, so an unmarked class's raise sites are unguarded; joining the set is
  how they get read. Doing that meant teaching the guard a second
  message-assembly shape — a class that takes fields and builds its f-string in
  `__init__`, where half the message is chosen at a call site three frames from
  the literal text.
  `SubscriberLoop._run` keeps its own format for `/healthz`'s `last_poll_error`
  and must not be "unified" onto the helper — but on **one** reason now, not the
  two CG-29 gave. The surviving one is that `last_poll_error` is an
  unauthenticated `/healthz` field, pinned as an exact string in two test files
  and interpolated into a `reasons` line. The other — *"`PubSubError` is
  unmarked, so the helper would drop the HTTP status"* — **CG-33 removed**; do
  not go looking for it. Nothing in either row clears, adds or rewords a ⚠ flag:
  `poll_once`'s error paths and `_post`'s non-200 branch remain unexercised
  against Google, and this changed what they PRINT, not what is verified.
- Consumers registered so far: `aiteam-harness` (via its `notify.py`
  gateway transport, aiteam Stage 6 — `allow_inbound: false` **in the live
  registry AND in `registry.example.yaml`** as of CG-61, user decision D1: a
  **default corrected, not a verdict** about that consumer, and reversible in that
  one registry line; reasoning lives in the production-readiness arc spec §7 D1.
  ⚠ **CORRECTED 2026-08-05 (CG-79).** This said *"`allow_inbound: false` **in
  `registry.example.yaml`**"* with the caveat *"the live edit is CG-61's recorded
  operator action, and **until it is done this app is still open inbound in
  production**. `aitrader`'s entry beside it describes the live file; **this one
  does not yet**."* **The operator made the edit on 2026-08-03**
  (`config/registry.yaml` mtime `2026-08-03T20:34:06Z`), so this entry now
  describes the live file exactly as `aitrader`'s does — measured through the real
  `load_registry` on 2026-08-05, with the key **explicitly present** rather than
  defaulted. The caveat is recorded rather than deleted because it was the
  **correct** thing to say for three days and its shape recurs: a PR cannot change
  a gitignored file, so *"merged"* and *"in effect"* are two different facts here
  and always will be), `aitrader` (docs/consumers/aitrader.md
  — notify + dead-man, `allow_inbound: false`), `jobhunt`
  (docs/consumers/jobhunt.md — the first two-way tenant: whole-event
  callback forwarding with per-user authorization, structured reasons via
  selection widgets, fail-loudly-in-thread).
- **Selection widgets and modal dialogs — two claims, two different confidence
  levels** (CG-11, 2026-07-30). The sentence that used to sit in the jobhunt
  parenthetical above — *"modal dialogs are impossible over Pub/Sub transport —
  selection widgets are the supported path"* — put a proven claim and an untested
  one on either side of one confident dash, and got the proven half's **scope**
  wrong as well. Precisely:
  - **A selection widget IS an interaction trigger on classic**, the runtime we
    run. Changing a dropdown on a card with **no button at all** produced a whole
    `CARD_CLICKED` carrying the widget's own `onChangeAction.function` as the
    action identity (`tests/fixtures/classic-cardclicked-onchange-event.json`,
    pinned by `test_normalize_real_classic_onchange_with_no_button_at_all`).
    Under **add-ons** it is not — `onChangeAction` dies there with `gsuiteaddons`
    code 13, exactly like a button. This is a property of the **runtime**, not of
    Pub/Sub transport; conflating the two is precisely what made the old sentence
    wrong.
  - ***Widgets for input, one button to submit* stays the recommendation** — now
    because it is **portable** (the only thing that works on add-ons) and because
    it yields **one event per user decision** instead of two, not because it is
    the only option. A card carrying an `onChangeAction` fires on change *and*
    again on submit.
  - **Modal dialogs are BELIEVED impossible over Pub/Sub transport** — they need
    a synchronous HTTP interaction endpoint, and Pub/Sub delivery gives the
    gateway no response channel. **Doc-derived inference, never tested on either
    runtime.** Do not restate it as an observation. Full wording, with the
    add-ons/classic split: ADR-0001 §7.
- **Deploy target — this bullet named the WRONG HOST for the whole arc, corrected
  2026-08-03 (CG-53).** It read *"`/srv/chat-gateway/` on the appserver (homelab
  conventions: off-repo `.env` mode 600, SECRETS.md pointers, service doc +
  DASHBOARDS + Homepage registration)"*, and `docker-compose.yml`'s header said
  the same. That was the v0 intent and it was never revisited; the entire
  production-readiness arc — spec, plan, and every queue row from CG-53 to CG-59
  — targets the **NAS**, as a **TrueNAS custom app**. Two of the three things the
  old wording implied are actively false there: a custom app's compose is
  submitted over an API, so there is **no build context and no relative mount**,
  and it is then **captured into the homelab repo** by a script whose secret
  detection this project's key names defeat — which is the whole reason
  `env_file.py` exists. The homelab conventions in the parenthetical **do still
  apply**; only the host and the mechanism changed, which is precisely why a
  silent path swap would have read as harmless.
  **The on-box layout has ONE home and it is not here:** `docs/deploy/nas.md`
  (§3 the tree, §5 the compose document, §6 what differs from the dev box). Do
  not copy the tree into this file — four of its six state entries hold tenant
  message bodies and the set has already grown twice, which is the same
  two-homes-for-a-moving-fact trap as the test count above.
  ⚠ **IT IS DEPLOYED, since 2026-08-05 (CG-55) — and this bullet said the
  opposite until that day.** It read *"Nothing here is deployed. That runbook's
  §10 Executed is empty by design and is filled by CG-55; until it has entries,
  'deploy target' is an intention, not a fact."* Both halves are now false: §10
  has entries, and "deploy target" is a fact. Quoted rather than deleted, because
  the **test** it proposed is the good part and still works — *look at §10, do not
  guess* — and because a claim that silently flips is how this file has gone
  stale before.
  **What the deploy established, and where it lives: `docs/deploy/nas.md` §10
  *Executed*, which is its ONE home.** Do not summarize it here — not the five
  facts, not the seven deviations, not the counters. They are the most
  copy-tempting numbers this project has produced and every one of them moves.
  ⚠ **Nothing in the verification ledger above moved.** A first live deploy is a
  tempting moment to clear a ⚠ flag and CG-55 cleared none; §10 names the one
  candidate (`SubscriberLoop`'s long-run row) and leaves it for CG-59's soak,
  because retiring it needs the user's explicit hard-rule-#3 sign-off and a clock,
  not a smoke test.
  ⚠ **§10 NOW HOLDS TWO DATED RUNS, and the *"look at §10, do not guess"* test
  above is how you tell them apart.** The second is **2026-08-11**: a **23-hour
  outage nobody detected** (`dockerd` SIGKILLed on 2026-08-10, cause unexplained,
  systemd then latching), its recovery, the **first upgrade redeploy** — which
  put CG-80's `/mcp` and CG-59's `?strict=1` on the box — and MCP's enablement
  and live exercise. Its facts, deviations and probe results are **not summarized
  here** for exactly the reason the paragraph above gives.
  ⛔ **Two things from it that a reader of THIS file must not get wrong, because
  both contradict what other bullets used to say.** (1) *"Deployed"* has not meant
  *"continuously serving"* since 2026-08-10 — **this gateway has had a
  multi-hour outage**, and the reason nobody knew is a genuine architectural gap
  filed as **CG-84**: the dead-man switch watches **tenants'** silence, and
  **`/healthz` cannot report that it is not answering.** (2) The container's
  uptime streak is **gone, lost rather than spent** — so any sentence anywhere
  offering *"~5 days of `RestartCount: 0`"* as evidence toward the
  `SubscriberLoop` flag is false, and **CG-82 task 1 is moot**.
  ⚠ **Still no ledger flag moved on 2026-08-11 either**, and it was a far more
  tempting day than 2026-08-05: a real message went through the MCP tool to a
  real Chat space. **That is the same webhook bytes from a different caller** —
  `webhook.send` cleared 2026-07-29 — and a new ingress neither re-proves nor
  extends it. The `SubscriberLoop` candidate moved the **wrong** way: the run
  that was to be its evidence is dead (**CG-85**).
