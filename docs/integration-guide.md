# Integration guide — one curl per endpoint

Everything is a versioned JSON endpoint under `/v1/` with
`Authorization: Bearer <your app key>`. Keys are per-app (revocable by
rotating the env var), minted by the operator: `python3 -m chat_gateway
mint-key`. Full schemas: `GET /docs` (OpenAPI). Stdlib-only Python client:
`src/chat_gateway/client.py` (vendor the single file if you prefer).

Set for the examples:

```bash
GW=http://appserver:8085
AUTH="Authorization: Bearer $MY_APP_KEY"
JSON="Content-Type: application/json"
```

## Send a raw envelope (synchronous delivery)

You render the content (text + optional Cards v2); the gateway sends it as
one of your allowed identities. Returns 200 on delivered, 502 on failure.

```bash
curl -s $GW/v1/messages -H "$AUTH" -H "$JSON" -d '{
  "identity": "pm-familyworkspace",
  "text": "Review needed: deploy gate for v2.4",
  "cards": [{"cardId":"r1","card":{"header":{"title":"PM · familyworkspace"}}}],
  "thread_key": "review-PC-12"}'
```

## Notify (accept-fast, async, deduped) — `POST /v1/notify` → 202

The gateway renders by severity (`alert` → loud card with the `action`
prominent; `warning` → mild card; `info` → plain text), routes by your app's
`routes:` config, enqueues, and owns retries (backoff 0s/30s/2m/10m/1h, then
`failed` in the log). Identical `(source, dedupe_key)` within the window
(default 1h) collapses: one delivered message; the collapsed count rides on
the next delivery ("×N since last notice"). Never assume guaranteed receipt
— keep a local fallback log and check `/v1/deliveries`.

```bash
curl -s $GW/v1/notify -H "$AUTH" -H "$JSON" -d '{
  "severity": "alert",
  "title": "HALT: daily drawdown breaker tripped",
  "body": "Circuit opened at 13:42Z. No further orders will be placed.",
  "action": "Review the guardrails log on the dev box, then re-arm.",
  "dedupe_key": "halt-drawdown",
  "thread_key": "run-2026-07-24"}'
# -> {"status":"enqueued","id":17,"occurrences":1}   (or {"status":"deduped",...})
```

## Dead-man heartbeat — `POST /v1/heartbeat`

Register/refresh in one call. If no refresh arrives by `schedule + grace`,
the gateway fires an `alert`-severity notification on your alert route,
repeating daily until you refresh or delete. Schedules: `weekdays` (due
dates falling Sat/Sun roll to Monday in `tz`, default America/New_York —
**US market holidays are NOT modeled; widen `grace` to cover them**, e.g.
`74h` spans a Monday holiday), `daily`, `every:<N><s|m|h|d>`.

```bash
curl -s $GW/v1/heartbeat -H "$AUTH" -H "$JSON" -d '{
  "check_id": "daily-trading-run", "schedule": "weekdays", "grace": "2h"}'
# -> {"status":"ok","check_id":"daily-trading-run","next_deadline":"2026-07-27T22:30:00+00:00"}

curl -s $GW/v1/heartbeat/aitrader -H "$AUTH"            # your checks + states
curl -s -X DELETE $GW/v1/heartbeat/aitrader/daily-trading-run -H "$AUTH"
```

## Delivery log — `GET /v1/deliveries?limit=50`

Per-source accounting: `enqueued → retrying* → delivered | failed` (plus
`deduped` occurrences). Titles and statuses only — bodies are never logged.

```bash
curl -s "$GW/v1/deliveries?limit=20" -H "$AUTH"
```

## Inbound interaction callbacks (tier 2, per-tenant opt-in)

Set `callback_url` (+ `allow_inbound: true`) in your tenant config and the
gateway POSTs each authorized event to it, whole:

```json
{"app":"jobhunt","space":"spaces/XXXX","thread_key":"digest-2026-07-24",
 "thread_name":"spaces/XXXX/threads/T1","message_id":"spaces/XXXX/messages/M1",
 "sender_display":"Mark","sender_email":"mark@mackelprang.com","text":"",
 "action":{"id":"verdict","id_source":"cg_param",
           "params":{"job_id":"job-123","verdict":"approve","nonce":"n-9"}},
 "dedupe_key":"ps-42","event_type":"CARD_CLICKED","received_at":"...","raw":{...}}
```

**`action.id` can be `null`, and you must handle that.** It means the gateway
could not resolve an action identity from any source — not that the action was
named empty string. It is never `""`; that ambiguity was a real defect, removed
2026-07-29. Reject a `null` explicitly rather than guessing; the event is still
delivered to you deliberately, because a parse-quality problem must not become
a silent drop.

The usual cause is a card that did not set the reserved `__cg_action__`
parameter. `action.id_source` tells you where
the value came from: `"cg_param"` (your `__cg_action__`), `"google"` (a native
Chat action slot), or `null`. It is transport metadata, like `envelope_format`;
you can ignore it, but a change in it means the runtime beneath you moved.

Rules of the road: delivery is **at-least-once** (`dedupe_key` = the Pub/Sub
message id — make your handler idempotent; self-contained button tokens
help); selection-widget values arrive merged into `action.params`; users not
on your `allowed_users` list are refused in-thread and never reach you; if
your callback is down, retries span ~10s and then the gateway posts your
`unreachable_message` into the thread — the user always sees a tap that
didn't land. Return any 2xx quickly; do your work async.

### Making a card button actually come back — the card convention

**Read this before you render an interactive card.** A card whose buttons are
wired the way Google's own documentation shows will not reach this gateway.

Ask the gateway how to wire it, per app:

```bash
curl -s $GW/v1/identities -H "$AUTH"
# -> {"app":"jobhunt", "identities":[...],
#     "interaction":{"enabled":true,
#                    "routing_target":"projects/<PROJECT>/topics/<TOPIC>",
#                    "action_key":"__cg_action__", "note":"..."}}
```

Then build every interactive element like this:

```jsonc
"onClick": {
  "action": {
    // The value the gateway published as interaction.routing_target.
    // NEVER hardcode this, and never derive it from a doc you read once.
    "function": "<interaction.routing_target>",
    // NOTE THE SHAPE: in a CARD, parameters is an ARRAY of {key, value}.
    "parameters": [
      {"key": "__cg_action__", "value": "verdict"},   // your action identity
      {"key": "job_id",        "value": "job-123"},   // your own params, untouched
      {"key": "nonce",         "value": "n-9"}
    ]
  }
}
```

> ### ⚠ `parameters` shapes — outbound is fixed, inbound depends on the runtime
>
> **Outbound is always an ARRAY** of `{"key": …, "value": …}`. That is the
> Cards v2 schema, on every runtime, with no exceptions. Write the array — a
> card built with a map is not valid Cards v2 and you find out at render or tap
> time, in front of a user.
>
> **Inbound varies, and it is a property of the runtime, not of the direction:**
>
> | Runtime | Where the params arrive | Shape |
> |---|---|---|
> | **classic** (production since 2026-07-29) | `action.parameters` | an **ARRAY** — byte-identical to what you sent |
> | **add-ons** | `commonEventObject.parameters` | a **MAP**, `{"key": "value"}` |
>
> So classic is *symmetric* (array out, array back, with widget values arriving
> separately under `common.formInputs`), and the map is an **add-ons-runtime
> quirk** rather than "what inbound looks like". Every shape in both tables is
> from a first-hand capture, not documentation.
>
> **You should not need any of this.** The gateway flattens all of it and hands
> you `action.params` as a plain object either way — that normalization is the
> whole point. It is documented only so that nobody reading a raw event
> concludes the guide is wrong. Pinned by
> `test_card_parameters_are_an_array_in_the_real_captured_card` and
> `test_inbound_parameter_shape_is_a_runtime_property_not_a_direction_rule`.

Two rules, and the reasons matter:

- **`function` carries the routing target, not your action name.** Under the
  Workspace Add-ons runtime `action.function` is the interaction's
  *destination*, not a callback name — so it is spoken for. That is also why a
  button wired with an ordinary function name fails with
  `gsuiteaddons.googleapis.com/errors` code 13 and nothing reaches the topic.
  **Under a classic Chat app this is not true** — see the runtime note below —
  but you do not need to care, because you are fetching the value either way.
- **Your action identity rides in `__cg_action__`.** The gateway lifts it into
  `action.id` and **pops it out** of the `params` you receive, so your handler
  sees only its own parameters. The whole `__cg_` prefix is reserved for the
  gateway; unknown `__cg_*` keys are passed through to you rather than
  discarded, but do not invent your own.

**Why fetch instead of hardcode.** Because identity always rides in
`__cg_action__` and the function slot always holds a gateway-published
constant, the *same card* works under every deployment model this gateway could
move to — add-ons + Pub/Sub today, a classic Chat app, or an HTTP endpoint.
Migrating costs **zero producer card changes**: one value moves, on the gateway
side. Hardcode the topic path and you have signed up to re-render every card
the day it moves — **and it is moving**: see the runtime note below. See
[ADR-0001](architecture/decisions/2026-07-29-tier2-interaction-model.md) D3.

#### Runtime note: `__cg_action__` is an add-ons compatibility fallback (updated 2026-07-29)

This matters for how much weight to put on the reserved key.

**Production migrated to a classic (non-add-on) Chat app on 2026-07-29, and
classic supplies action identity natively.** Live-verified through our real
`ChatApiAdapter` on the production configuration: a card with **ordinary**
function names delivered

```
type: CARD_CLICKED   action.id: 'approve'   envelope_format: 'classic'
params: {"jobId": "mig-001", "reason": "good_fit"}
```

No topic-as-function, no reserved key needed — `action.id` is simply populated.

So, plainly:

- **On classic, `__cg_action__` is inert.** You do not need it. Give your
  buttons ordinary function names and read `action.id`.
- **It is not removed, and it still wins when present.** It stays load-bearing
  under the add-ons runtime, and a card that sets it behaves identically on
  either runtime. This is the same support-both posture the gateway takes on the
  two envelope formats — the gateway does not force you to know which runtime
  you are behind, and that guarantee is worth more than tidiness.
- **Keep fetching `interaction.routing_target` regardless.** On classic it is
  just a constant the runtime echoes back unused, and fetching it is what made
  this migration cost **zero producer card changes**. That already paid for
  itself once.

If `interaction.enabled` is `false`, read the `reason`: either your app is
`allow_inbound: false` (interactions from it are never routed anywhere) or the
operator has not configured a routing target yet. **Do not guess a value** — a
card built against a guess fails at tap time, in front of a user.

#### Collecting structured input: widgets for input, one button to submit

**Under the add-ons runtime (deployed today)** a `selectionInput` is **not** an
interaction trigger. Its `onChangeAction` fails exactly like a plain button's
(`gsuiteaddons` code 13). What works is the widget's **value**: Chat harvests
`commonEventObject.formInputs` when a **button** is tapped, and the gateway
merges those values into `action.params` alongside the button's own parameters.
Capture-verified 2026-07-29 on real data — a dropdown's `"decision": "approve"`
arrived merged.

So: put your widgets on the card, and give the user one button to submit. It
costs a second tap; select-to-act is not available on this runtime.

**Under a classic Chat app, `onChangeAction` does fire** — live-verified
2026-07-29 (`action.id: 'onDecision'`, `params: {"decision": "approve"}`), so
select-to-act is available on production now.

**Use it sparingly, and prefer the submit button anyway.** Verified live on the
production configuration: a dropdown value (`reason: "good_fit"`) arrived on the
**button click's** form inputs with **no `onChangeAction` on the dropdown at
all**. That means *widgets for input, one button to submit* produces **one event
per user decision** instead of two — fewer events to make idempotent, fewer
half-finished interactions, and one obvious commit point. `onChangeAction` is
there when you genuinely want live reactivity, not as the default.

The pattern is therefore not a workaround you will have to undo: it is the
better design on the runtime we now run, and it also happens to be the only one
that works on add-ons.

True modal dialogs are **believed** impossible over Pub/Sub transport (they need
a synchronous HTTP interaction endpoint) — that half is doc-derived inference
and has never been tested, on either runtime.

### Which Google runtime you are behind

Google delivers Chat events in two envelope formats, depending on whether the
Chat app is deployed on the **Workspace Add-ons** runtime (`commonEventObject`
+ `chat.<x>Payload`) or as a **classic Chat app** (flat `type`/`space`/
`message`/`user`). Both are supported and normalize to the identical
`InboundReply` — you should never need to care which you are behind.

`envelope_format` (`classic` | `addon` | `unparseable`) tells you anyway, for
debugging.

Two real differences worth knowing:

- **`thread_key` may be `null` under the add-ons runtime.** Google echoes it
  only when the sender set one. Thread against `thread_name` if you need a
  stable handle for inbound events.
- **`raw.…configCompleteRedirectUri` / `…Url` arrives blanked** as
  `<redacted-by-gateway>`. It is a per-message capability URL — visiting it
  makes the user's private message public in the space — so the gateway does
  not propagate it. Everything else in `raw` is untouched.

An event the gateway cannot parse is never delivered to you: it is audited
under the reserved `_unrouted` id with `event_type: "UNPARSEABLE"` and counted
at `/healthz` → `subscriber.unparseable_seen`. It is never silently reshaped
into an empty `MESSAGE`. Its sibling `subscriber.dispatch_errors` counts the
other failure: an event that parsed fine but could not be delivered (callback
enqueue, in-thread reply, or audit write blew up) — it is acked and dropped
rather than left to wedge the subscription.

Two further counters cover the events that parsed and routed fine but reached
nobody. `subscriber.suppressed_opt_out` counts events landing in a space whose
registered owners all have `allow_inbound: false` — the tenant opted out, so
the event goes nowhere, by design. `subscriber.suppressed_not_authorized`
counts events refused by an app's `allowed_users` list; that user got an
in-thread `⛔ Not authorized for this action.` and nothing was forwarded.
Neither is a fault and neither makes `/healthz` report `degraded` — they are
guarantees working, not failures — but both used to happen with no trace
anywhere at all, which is what they exist to fix.

They are **bare integers by design**: no space, no app id, no sender, no
content, no timestamp. `/healthz` needs no authentication, so anything
attributable reported here would be readable by anyone who can reach the port.
Two other things follow from that. They count **suppressions, not events** — the
decision is made per candidate app, so one event arriving in a space with two
opted-out owners increments by two — and if you need to know *which* space or
*which* user, `/healthz` is not where you will find it; that is a deliberate
omission, not a gap.

## Inbound replies — `GET /v1/inbox` (tier 2, opt-in)

Polling returns and clears your app's replies (each carries `space`,
`thread_key`, sender, text, raw event); a JSONL audit keeps everything.
Apps with `allow_inbound: false` in the registry get a hard **403** —
the no-inbound-control contract is enforced, not just omitted, and the
gateway never turns Chat input into calls against a consumer system.

```bash
curl -s $GW/v1/inbox -H "$AUTH"
```

## Identities + health

```bash
curl -s $GW/v1/identities -H "$AUTH"    # what you may send as, with readiness
curl -s $GW/healthz                     # honest health — no auth required
```

### Which identity your message shows as

- **Tier 1 (`mode: webhook`)** — the webhook's own configured display name and
  avatar. Google returns `sender: null` for these sends; Chat substitutes the
  webhook's name, and a webhook created without one renders as **"Unknown
  User"**. One webhook per identity, as many as you like.
- **Tier 2 (`mode: app`)** — the Chat app itself, one sender for every
  identity routed through it (`Agent Comms` on this deployment, `type: BOT`).
  Per-agent flavour has to ride in the message content — a card header, a
  prefix — because the sender is fixed.

Both verified live 2026-07-29.
