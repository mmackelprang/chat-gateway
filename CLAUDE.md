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

## Layout

`src/chat_gateway/` — envelope / registry / auth / inbox / service / client,
one concern each; `adapters/` — webhook (tier 1), chat_api + pubsub (tier 2);
`iac/` — gcloud script (`.sh` + Windows `.ps1` sibling) + terraform; `docs/` —
Google Cloud setup + integration guide. Tests: `python3 -m pytest` on POSIX,
`python -m pytest` on the Windows dev box (its msys `python3` has no pytest;
`python` is 3.13.7) — offline, 63 passing.

## Current status (2026-07-29)

- **First real Chat event received 2026-07-29.** It arrived in the Workspace
  Add-ons envelope (`commonEventObject` + `chat.messagePayload`), which the
  v0.1 parser — written for the classic flat format — silently normalized into
  an empty MESSAGE husk. Fixed: `normalize_event` now detects and normalizes
  BOTH envelope formats to one internal shape, and raises rather than
  defaulting on anything it does not recognize. Unparseable events are audited
  under `_unrouted` as `UNPARSEABLE`, counted at `/healthz`, and still acked so
  they cannot wedge the subscription.
- Core + all adapters + service + client built and tested offline (63
  tests), including the aitrader contract surface: /v1/notify (severity
  routing/rendering, dedupe windows, async dispatcher with retry backoff +
  per-source delivery log, titles-only logging) and /v1/heartbeat (dead-man
  monitor; tz-aware `weekdays` schedule rolls weekend due-dates to Monday;
  daily repeat; JSON-persisted checks). US market holidays deliberately not
  modeled (contract says widen grace). Queue is in-memory (restart drops
  undelivered jobs — visible in the log; accepted v0).
- Cloud resources now EXIST for `chat-gateway-prod` (steps 2–4, 2026-07-28):
  chat + pubsub APIs enabled (no billing needed), `chat-gateway` SA, the
  `chat-gateway-events` topic, the `chat-gateway-sub` pull subscription, both
  IAM bindings, SA key minted to `iac/chat-gateway-sa.json` (gitignored,
  ACL-locked to its owner). **Provisioning is not verification** — see below.
- ⚠ LIVE-UNVERIFIED (updated honestly):
  - Events DO reach `chat-gateway-sub` — proven 2026-07-29.
  - **Not** proven: which principal published them. Both
    `chat-api-push@system.gserviceaccount.com` and the add-ons service agent
    `service-<PROJECT_NUMBER>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com` are
    now bound, so the evidence is circumstantial. GCP also accepts bindings to
    `*@system.gserviceaccount.com` principals **without validating they
    exist**, so a clean apply was never evidence either.
  - `PubSubPuller.pull()/acknowledge()` — still unexercised; the live pull used
    an ad-hoc client, not our class.
  - Add-on **CARD_CLICKED** — a real interaction WAS captured 2026-07-29 and is
    now ⚠ SHAPE-VERIFIED (tests/fixtures/addon-buttonclicked-event.json). It
    found a defect rather than confirming the mapping: `action.id` normalizes to
    "" because the card's routing pattern consumed the function slot. Params
    (including selection-widget values) are correct. Not a live-round-trip clear
    — the capture was pulled with an ad-hoc client. jobhunt R3/R4 remain
    unverified; see queue item CG-10.
  - Chat API **send** and webhook **send** (including the threadKey
    param-vs-body question) — unchanged, still unverified.
  - The add-on **MESSAGE** and **buttonClicked** shapes are ⚠ SHAPE-VERIFIED
    2026-07-29 (real captured bytes replayed offline,
    `tests/fixtures/addon-message-event.json`,
    `tests/fixtures/addon-buttonclicked-event.json`). That is not a
    live-round-trip clear and does not remove any flag above.
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
  `approve` arrived as `action.id: 'approve'`. Classic is the preferred
  destination and a migration is underway; `__cg_action__` stays supported
  because it is load-bearing on the runtime deployed **today**, and because it
  still outranks the native slot, so one card behaves identically on both sides
  of the migration. Same support-both posture as the two envelope formats — do
  not rip it out.
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
- Consumers registered so far: `aiteam-harness` (via its `notify.py`
  gateway transport, aiteam Stage 6), `aitrader` (docs/consumers/aitrader.md
  — notify + dead-man, `allow_inbound: false`), `jobhunt`
  (docs/consumers/jobhunt.md — the first two-way tenant: whole-event
  callback forwarding with per-user authorization, structured reasons via
  selection widgets, fail-loudly-in-thread; note: modal dialogs are
  impossible over Pub/Sub transport — selection widgets are the supported
  path).
- Deploy target: `/srv/chat-gateway/` on the appserver (homelab conventions:
  off-repo `.env` mode 600, SECRETS.md pointers, service doc + DASHBOARDS +
  Homepage registration).
