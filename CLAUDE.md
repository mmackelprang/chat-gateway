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
6. **No inbound control path — ever.** The gateway has no mechanism that
   turns a Chat message, reply, reaction, or button into a call against a
   consumer system: inbound is passive polling only, and apps can set
   `allow_inbound: false` to make even that a 403 (aitrader does — its
   contract treats a two-way path as a security hole in a real-money
   system). Do not add reply-forwarding webhooks, "acknowledge to clear"
   actions, or any consumer-callback feature without explicit user sign-off
   naming this rule.

## Layout

`src/chat_gateway/` — envelope / registry / auth / inbox / service / client,
one concern each; `adapters/` — webhook (tier 1), chat_api + pubsub (tier 2);
`iac/` — gcloud script + terraform; `docs/` — Google Cloud setup +
integration guide. Tests: `python3 -m pytest` (offline, 20 passing).

## Current status (2026-07-24)

- Core + all adapters + service + client built and tested offline (31
  tests), including the aitrader contract surface: /v1/notify (severity
  routing/rendering, dedupe windows, async dispatcher with retry backoff +
  per-source delivery log, titles-only logging) and /v1/heartbeat (dead-man
  monitor; tz-aware `weekdays` schedule rolls weekend due-dates to Monday;
  daily repeat; JSON-persisted checks). US market holidays deliberately not
  modeled (contract says widen grace). Queue is in-memory (restart drops
  undelivered jobs — visible in the log; accepted v0).
- ⚠ LIVE-UNVERIFIED: webhook send (verify threadKey param-vs-body mechanics
  and drop the redundant one), Chat API send, Pub/Sub pull/ack, and the
  `chat-api-push@system.gserviceaccount.com` publisher grant in the IaC —
  all pending the Google Cloud setup (docs/google-cloud-setup.md) and first
  live round-trip.
- Consumers registered so far: `aiteam-harness` (via its `notify.py`
  gateway transport, aiteam Stage 6), `aitrader` (contract in
  docs/consumers/aitrader.md — notify + dead-man, `allow_inbound: false`),
  `job-hunter` (planned).
- Deploy target: `/srv/chat-gateway/` on the appserver (homelab conventions:
  off-repo `.env` mode 600, SECRETS.md pointers, service doc + DASHBOARDS +
  Homepage registration).
