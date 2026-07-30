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
   2026-07-24 for jobhunt's R3, at the user's direction). `allow_inbound:
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

## Layout

`src/chat_gateway/` — envelope / registry / auth / inbox / service / client,
one concern each; `adapters/` — webhook (tier 1), chat_api + pubsub (tier 2);
`iac/` — gcloud script (`.sh` + Windows `.ps1` sibling) + terraform; `docs/` —
Google Cloud setup + integration guide. Tests: `python3 -m pytest` on POSIX,
`python -m pytest` on the Windows dev box (its msys `python3` has no pytest;
`python` is 3.13.7) — offline, 140 passing.

## Current status (2026-07-30)

- **First real Chat event received 2026-07-29.** It arrived in the Workspace
  Add-ons envelope (`commonEventObject` + `chat.messagePayload`), which the
  v0.1 parser — written for the classic flat format — silently normalized into
  an empty MESSAGE husk. Fixed: `normalize_event` now detects and normalizes
  BOTH envelope formats to one internal shape, and raises rather than
  defaulting on anything it does not recognize. Unparseable events are audited
  under `_unrouted` as `UNPARSEABLE`, counted at `/healthz`, and still acked so
  they cannot wedge the subscription.
- Core + all adapters + service + client built and tested offline (98
  tests), including the aitrader contract surface: /v1/notify (severity
  routing/rendering, dedupe windows, async dispatcher with retry backoff +
  per-source delivery log, titles-only logging) and /v1/heartbeat (dead-man
  monitor; tz-aware `weekdays` schedule rolls weekend due-dates to Monday;
  daily repeat; JSON-persisted checks). US market holidays deliberately not
  modeled (contract says widen grace). Queue is in-memory (restart drops
  undelivered jobs — visible in the log; accepted v0).
- **The live project is `chat-gateway-gw` (`#860649224827`), and it is the only
  one.** `chat-gateway-prod` — which every "Cloud resources now exist" note in
  this file used to describe — was **deleted 2026-07-30**, along with E1's
  throwaway project. Chat + Pub/Sub APIs enabled (no billing needed), the
  `chat-gateway` SA, the topic and the pull subscription all exist on `gw`; the
  live SA key is **`chat-gateway-sa-gw.json`**. ⚠ `iac/chat-gateway-sa.json` is
  **dead** — it belongs to the deleted project; do not try to authenticate with
  it and do not treat its presence as configuration.
  **Provisioning is not verification** — see below.
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
  Classic is not a destination, it is **production, since 2026-07-29**, and the
  runtime deployed today is the one on which this key is **inert**. Every
  project that ran add-ons is deleted, so nothing in production depends on it.
  **It stays anyway, and the reason is now the weaker one — say so rather than
  keep quoting the strong one.** It still **outranks** the native slot, so a
  single card behaves identically on either runtime; that is the whole D3
  portability payoff, and it is what made the migration cost zero producer card
  changes. Same support-both posture as the two envelope formats — **do not rip
  it out**, but do not justify it as load-bearing either.
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
  Two integers rather than one because the reasons are different investigations
  — `opt_out` is rule #6 working as designed, `not_authorized` is a real human
  refused (jobhunt R4, newly reachable in production since `job-hunter` gained
  an `allowed_users` list). Each counts **candidate apps that declined an
  event**, not events that went nowhere: an opted-out owner increments even when
  a co-owner of the same space *received* that same event, and `events_seen` is
  the event count. Deliberately **not** inputs to `status` — a guarantee working
  is not a fault, and degrading on one teaches an operator to ignore `degraded`.
- Consumers registered so far: `aiteam-harness` (via its `notify.py`
  gateway transport, aiteam Stage 6), `aitrader` (docs/consumers/aitrader.md
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
- Deploy target: `/srv/chat-gateway/` on the appserver (homelab conventions:
  off-repo `.env` mode 600, SECRETS.md pointers, service doc + DASHBOARDS +
  Homepage registration).
