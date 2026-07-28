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
`python` is 3.13.7) — offline, 37 passing.

## Current status (2026-07-28)

- Core + all adapters + service + client built and tested offline (37
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
- ⚠ LIVE-UNVERIFIED (unchanged by the provisioning above): webhook send
  (verify threadKey param-vs-body mechanics and drop the redundant one), Chat
  API send, Pub/Sub pull/ack, and the
  `chat-api-push@system.gserviceaccount.com` publisher grant in the IaC. The
  publisher binding applied cleanly, but GCP accepts bindings to
  `*@system.gserviceaccount.com` principals **without validating they exist**,
  so a clean apply is not evidence. That flag clears only when the principal
  is confirmed on the Chat API "Connection settings" console page AND a real
  event lands in the subscription; the others clear only on a real round-trip.
  Console steps 5–7 (docs/google-cloud-setup.md) are still outstanding.
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
