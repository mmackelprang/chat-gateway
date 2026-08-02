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
the next delivery ("×N since last notice") — **when there is room for it.** The
counter is the gateway's own decoration, so on a long `info` payload it yields
rather than truncating your content; how exactly it degrades is in
[the aitrader consumer doc,
§11](consumers/aitrader.md#11-sharp-edges-and-accepted-limitations), and the
count is in the delivery log either way. Never assume guaranteed receipt
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

Two further terminal statuses appear **only at boot**, written by queue replay:
`expired` (queued longer than the 24h replay ceiling — posting it now would
mislead) and `unroutable` (the job could not be rebuilt: identity no longer
granted, or a payload that no longer validates). Both mean *accepted from you
and then never sent*, both name the id, and both also show up as counters on
`/healthz` — see [Durability counters](#durability-counters-at-healthz). Switch
on the full set, not the four above.

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
your callback is down, retries span ~10s **by contract** and then the gateway
posts your `unreachable_message` into the thread — the user always sees a tap
that didn't land. Return any 2xx quickly; do your work async.

**"By contract" is load-bearing there: `~10s` is the forwarder's retry
schedule, not what your user waits.** Attempts fire on subscriber poll ticks, so
a callback that hangs rather than refusing pushes every later attempt out — and
exhaustion is the only route to the in-thread notice, which makes the slow case
the one worth sizing a timeout against. The measured figures live in
[the jobhunt handoff, §7](consumers/jobhunt-handoff.md#7-r7--fail-loudly-in-thread)
and are deliberately not repeated here.

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
move to — a classic Chat app (production since 2026-07-29), add-ons + Pub/Sub,
or an HTTP endpoint.
Migrating costs **zero producer card changes**: one value moves, on the gateway
side. Hardcode the topic path and you have signed up to re-render every card
the day it moves — **and it has already moved once**, at no cost to any
producer: see the runtime note below. See
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

**Under the add-ons runtime** (which this project left on 2026-07-29) a `selectionInput` is **not** an
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

Two further counters cover events that parsed and routed fine but were
declined. Each counts **candidate apps that declined an event**, not events
that went nowhere: the decision is made per candidate app, so an opted-out
owner increments a counter even when another owner of the same space *received*
that same event, and one event landing in a space with two opted-out owners
increments by two. `subscriber.events_seen` is the event count.
`subscriber.suppressed_opt_out` counts owners declining because they are
`allow_inbound: false`; `subscriber.suppressed_not_authorized` counts owners
refusing a sender who is not on their `allowed_users` list — nothing was
forwarded and, when a tier-2 reply path is configured, that user got an
in-thread `⛔ Not authorized for this action.` Neither is a fault and neither
makes `/healthz` report `degraded` — they are guarantees working, not failures
— but the case that motivated them, a space whose registered owners **all**
opted out, used to discard events with no trace anywhere at all.

Watch `suppressed_opt_out` in particular. A `not_authorized` suppression
announces itself to the affected human in the thread, so a misconfigured
`allowed_users` is self-revealing; an `opt_out` has no signal anywhere except
that integer — the person who tapped gets silence.

They are **bare integers by design**: no space, no app id, no sender, no
content, no timestamp. `/healthz` needs no authentication, so anything
attributable reported here would be readable by anyone who can reach the port.
If you need to know *which* space or *which* user, `/healthz` is not where you
will find it; that is a deliberate omission, not a gap.

## Inbound replies — `GET /v1/inbox` (tier 2, opt-in)

Polling returns and clears your app's **pending** replies (each carries `space`,
`thread_key`, sender, text, raw event). Delivery to you is **at-most-once**: the poll
empties the queue while it assembles the response, so a response that never
lands — a dropped connection, a crash in your handler — is a reply you do not
get again. (One exception, and it points the other way: if the journal write
that retires a polled batch **fails**, those replies stay open in the journal
and replay at the next boot. `/healthz` → `delivery.journal_write_errors` is
non-zero when that has happened; see below.)
Apps with `allow_inbound: false` in the registry get a hard **403** —
the no-inbound-control contract is enforced, not just omitted, and the
gateway never turns Chat input into calls against a consumer system.

```bash
curl -s $GW/v1/inbox -H "$AUTH"
```

### A gateway restart no longer drops your unpolled replies

This section used to say *"a JSONL audit keeps everything"*, which reads like an
answer to that question and never was one. There are **two** files answering
**two** questions, and only the second one is about durability:

- The per-app **JSONL audit** says what **ARRIVED**. One file per app per day,
  written before anything is queued, and **retained for a bounded window —
  30 days by default, 7 days for the gateway's own `_unrouted` bucket**,
  settable per deployment via `CHAT_GATEWAY_INBOX_RETENTION_DAYS` (`0`
  disables pruning). It holds no terminal records — nothing in it marks a
  reply as polled — so **your pending queue cannot be reconstructed from it.**
  It is a forensic record on the gateway host, not something you can re-poll.

  ⚠ **This changed on 2026-08-02, and it changed a published guarantee.** This
  line previously read *"never pruned."* That was a v0 over-promise on a file
  holding a person's message text, `sender_email` and whole `raw` event
  forever. The window is the amendment; the mechanism that makes it safe is
  the **quarantine** described below, which is never pruned and holds any
  reply that could not be revived. Reasoning:
  [ADR-0002](architecture/decisions/2026-07-31-journalled-message-bodies.md)
  §4.1 and §9 Q6.
- The **queue journal** says what is still **PENDING**. Since 2026-07-31 the
  inbox queue is journalled under `CHAT_GATEWAY_STATE_DIR/queue/` and replayed
  at boot, so a restart while your poller is asleep no longer loses the taps
  waiting for you. **Before that date it did, silently** — which mattered most
  for exactly the tenants that poll rather than take a callback, because a host
  that sleeps can leave a tap sitting in that queue for hours.

Both stay; neither substitutes for the other. One consequence is worth planning
for: a journalled reply that no longer validates as an `InboundReply` at boot —
an envelope change across a deploy looks precisely like this — is **dropped, not
delivered**, and counted at `/healthz` → `inbox.unrevivable_at_boot`, which
degrades the endpoint. It is not resent. **The whole record is preserved**,
payload included, under the state dir's `quarantine/` directory, which is
**never pruned** and is the recovery record; `/healthz` →
`inbox.quarantined_at_boot` says how many were preserved, and
`inbox.quarantine_write_errors` is non-zero if that ever failed.

⚠ **This replaced a weaker sentence on 2026-07-31.** It used to read *"and the
audit file is then the only copy"* — which pointed you at a file the gateway
merely happened not to delete, rather than at one it guarantees. The gateway is
**holding** the lost record at the moment it declares it lost, so it now keeps
it instead of pointing elsewhere.

## Identities + health

```bash
curl -s $GW/v1/identities -H "$AUTH"    # what you may send as, with readiness
curl -s $GW/healthz                     # honest health — no auth required
```

### Durability counters at `/healthz`

This is where the queue journals — and, since 2026-08-02, the retention
sweeper — report themselves **to you**. A boot line on the gateway's console
says some of it as well, but that is the operator's copy and you cannot read
it. **Nine** fields arrived with the journals on 2026-07-31 and **eight more**
with the sweeper; **eight of the seventeen can flip `status` to `degraded`** —
so a consumer that alarms on `status` should know what they mean before one
fires at 03:00. `status` is computed **from** `reasons`: anything that can
degrade this endpoint says so in words, because a number nobody reads is not
honest health.

| Field | What it means | Degrades? |
|---|---|---|
| `delivery.replayed_at_boot` | outbound jobs restored from the journal at boot, attempt count preserved | no — the feature working |
| `inbox.replayed_at_boot` | pending inbound replies restored at boot; still yours to poll | no — same |
| `delivery.expired_at_boot` | queued jobs older than the 24h replay ceiling, **closed rather than posted** — a three-day-old alert delivered now actively misleads | **yes** |
| `delivery.unroutable_at_boot` | queued jobs that could not be rebuilt at boot: the registry no longer grants that identity (never sent on a withdrawn permission), **or** the stored payload no longer validates as an envelope — the outbound twin of `unrevivable` | **yes** |
| `inbox.unrevivable_at_boot` | journalled replies that no longer parse as an `InboundReply`; dropped, not delivered | **yes** |
| `inbox.quarantined_at_boot` | how many of those were preserved in full — payload included — under the state dir's `quarantine/`, which is never pruned. Read it **against** the field above: that one is what left the queue, this one is what you can still recover | no — the recovery mechanism working |
| `inbox.quarantine_write_errors` | quarantine writes that **failed**. At least one unrevivable reply has **no preserved copy**, so only the per-app audit trail records that it ever arrived | **yes** |
| `delivery.journal_skipped_lines` | journal lines that did not parse. A torn trailing line is the *expected* shape after a power loss and is deliberately not fatal — a gateway that refuses to boot over a half-written byte is a crash loop | **yes** |
| `delivery.journal_write_errors` | journal writes that **failed** since start. The queues keep running — raising there would turn a full disk into a re-send storm — so while this is non-zero they are running **without** durability, and a reply you already polled can be delivered to you a second time after a restart | **yes** |
| `retention.enabled` | whether the audit trail is being pruned at all. `false` means either no sweeper is wired or the window is `0` — the two are distinguishable: only the first carries a `note` and omits every field below | no |
| `retention.window_days` | the tenant window actually in force on this deployment, in days. Read this rather than assuming the 30-day default — it is one env var | no |
| `retention.unrouted_window_days` | the shorter floor applied to the gateway's own `_unrouted` bucket. Not per-tenant policy: `_unrouted` holds unattributable events that answer to nobody | no |
| `retention.files_deleted` | day-files pruned since this process started. **Deliberately not a fault at any magnitude** — a retention policy working is not a failure, and degrading on it would teach you to ignore `degraded` | no — the feature working |
| `retention.delete_errors` | day-files the OS **refused** to unlink. The trail is growing past the window this guide states, so the retention promise above is not currently being kept | **yes** |
| `retention.sweep_failures` | whole sweep passes that **raised**. Louder than the row above: nothing is being pruned, so `files_deleted` and `delete_errors` both sit at a reassuring number while the window is not enforced at all | **yes** |
| `retention.last_sweep_error` | the exception **type** from the last failed pass — a type name, never a path. Companion to the row above, not an independent signal | no — reported with `sweep_failures` |
| `retention.last_sweep_at` | when a pass last **completed**. A pass over a directory that does not exist still stamps this, so `null` on a running gateway means the sweeps are not happening, not that there was nothing to do | no |

Four things the field names do not tell you:

- **Two of the `delivery.*` fields count both queues.**
  `journal_skipped_lines` and `journal_write_errors` are sums across the
  outbound *and* inbox journals — despite the prefix. The other three
  `delivery.*` fields, and **all four** `inbox.*` fields, are per-queue exactly
  as their prefixes say. Do not read the prefix as a guarantee on those two.
- **Eight degrading fields, seven `reasons` lines.** `expired_at_boot` and
  `unroutable_at_boot` share one entry: both mean "queued, then not delivered",
  and one investigation reads them together. (It was five and four until
  2026-07-31; `quarantine_write_errors` added one of each, and the two
  `retention.*` faults added one each on 2026-08-02 — they do **not** share a
  line, because one file the OS refused and the whole pass dying are different
  investigations. Recount against `service.py` rather than trusting this
  sentence — a copied count is what `CLAUDE.md`'s test-count note is about.)
- **`retention.*` is about the audit trail, not about your queue.** Everything
  else in this table describes work that was queued and might have been lost.
  These describe a file being **deleted on schedule**, which is the intended
  behaviour — only the two fault rows mean anything is wrong. Nothing the
  sweeper does can affect a pending reply: it never opens the queue journals
  and it never touches the quarantine.
- **The `*_at_boot` reasons will not clear while the process runs.** They
  describe this boot, and boot compaction has already removed the records, so a
  restart clears them. `journal_write_errors` is the opposite — it is live, and
  a rising one means the durability above has stopped being true.

### Which identity your message shows as

- **Tier 1 (`mode: webhook`)** — the webhook's own configured display name and
  avatar. Google returns `sender: null` for these sends; Chat substitutes the
  webhook's name, and a webhook created without one renders as **"Unknown
  User"**. One webhook per identity, as many as you like.
- **Tier 2 (`mode: app`)** — the Chat app itself, one sender for every
  identity routed through it (`Chat Gateway` on this deployment, `type: BOT`).
  Per-agent flavour has to ride in the message content — a card header, a
  prefix — because the sender is fixed.

Both verified live 2026-07-29 — when the tier-2 app was named `Agent Comms`. That
app is **deprecated** and the live one is `Chat Gateway` (a **user statement about
the Google Chat console, dated 2026-07-31**, which this repo cannot verify; see
[`google-cloud-setup.md`](google-cloud-setup.md) step 6). The rename changes only
the string a reader sees in the space: the gateway never reads `displayName`, and
"one sender for every tier-2 identity" is the part that matters here.
