# Consumer contract — jobhunt (two-way tenant)

Recorded 2026-07-24. jobhunt is the gateway's second tenant and the first
two-way one: pre-rendered job cards out, button interactions back. Service-
level integration only (R8) — appserver-local HTTP + one tenant config file;
no code imports either direction; jobhunt keeps working (tier-1 webhook +
its review UI) if the gateway is down or never ships (R9).

## Requirements → implementation

| R | Requirement | Where |
|---|---|---|
| R1 | Multi-tenant dumb pipe; one config file per tenant | registry directory mode (`load_registry` on a `tenants.d/`); per-app `callback_url` |
| R2 | Rendering stays with the producer; validate + size-limit only | envelope passes `cardsV2` through verbatim; 30KB cards cap; gateway never rewrites |
| R3 | Interactions forwarded whole with idempotency key | `InboundReply`: `action.id` + merged `params`, sender identity, space, `message_id`, `thread_*`, `dedupe_key` = Pub/Sub message id (at-least-once ⇒ tenant callbacks must be idempotent — buttons should carry self-contained tokens) |
| R4 | AuthZ at the gateway | events arrive only via our private topic/subscription (only Chat's publisher is granted); per-tenant `allowed_users` email allowlist — anyone else gets an in-thread "⛔ Not authorized" and is **never forwarded**. Tenant re-enforces downstream (its own verdict write-path) |
| R5 | Digest / instant lane / retro / health | all producer-side; instant lane = `POST /v1/messages` (synchronous) or `/v1/notify` |
| R6 | Structured reject reason | in-card `selectionInput` — the chosen value arrives merged into `action.params` (e.g. `reject_reason`). **True modal dialogs are NOT possible over Pub/Sub transport** (they require a synchronous HTTP interaction endpoint); the selection-widget path is the supported one |
| R7 | Fail loudly in-thread | callback retries are short (0s/3s/7s); on exhaustion the gateway posts the tenant's `unreachable_message` into the thread and logs `failed`. Tier-1-only deployments can't post the notice (no Chat app) — logged as `failed-silent`; full R7 requires tier 2 |
| R8/R9 | Separability / migration | HTTP-only; tier-1 webhook identity works today; adopting tier 2 changes transport + adds the callback, nothing else |

> **Runtime note (2026-07-29):** interactions are normalized identically under
> both Google runtimes — under the Workspace Add-ons runtime the action id
> arrives as the reserved `__action_method_name__` parameter and is lifted into
> `action.id`, so jobhunt's handler needs no change. ⚠ This path is
> documentation-derived and **not yet capture-verified** — no real card tap has
> been observed (queue item CG-3). R3/R4 must not be called verified until it is.

> **⚠ R3 deviation — one field is no longer forwarded whole (2026-07-29).**
> R3 says events forward *whole*. As of this date exactly one field is blanked
> to `<redacted-by-gateway>` before an event is audited or POSTed to your
> callback: Google's `configCompleteRedirectUri` (add-ons runtime) and its
> classic-runtime spelling `configCompleteRedirectUrl`. Everything else in
> `raw` is untouched, and no normalized field is affected.
>
> Why: it is an unguessable, per-message, state-changing capability URL.
> Visiting it makes the user's **private message public in the space** and
> re-delivers it. Forwarding it would hand every opted-in tenant that ability,
> which hard rule #2's "never log or echo them" covers in spirit even though
> Google's docs never call it a credential. This is a deliberate, documented,
> single-field exception taken on security grounds — recorded here rather than
> left as an undisclosed gap between the contract and the implementation.

## Tenant config (one file in the registry directory)

```yaml
identities:
  jobhunt:
    display: "Job Hunter"
    mode: app                    # tier 2 (webhook mode until then)
    space: "spaces/XXXX"
apps:
  jobhunt:
    key_env: CHAT_GATEWAY_API_KEY__JOBHUNT
    identities: [jobhunt]
    allow_inbound: true
    callback_url: "http://127.0.0.1:8710/chat-callback"   # appserver-local
    allowed_users: [mark@mackelprang.com]                 # exactly one (R4)
    unreachable_message: "⚠️ couldn't reach jobhunt — use the review UI"
```

## Acceptance status

Encoded as deterministic tests (`tests/test_callbacks.py`): authorized tap →
whole-event callback with dedupe key and structured reason; unauthorized tap
→ in-thread refusal only; callback down → visible in-thread failure after
~10s of retries; opted-out tenants receive nothing and can't even configure
a callback. The phone-tap-to-verdict-in-seconds end-to-end run needs the
tier-2 Google Cloud setup (LIVE-UNVERIFIED seams) — first smoke test once
the Chat app + subscription exist.
