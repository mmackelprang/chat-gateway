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
~~repeating daily until you refresh or delete~~ **repeating on an escalating
backoff — 1d, 2d, 4d, then weekly — until you refresh or delete (corrected
2026-08-31, CG-86)**. Schedules: `weekdays` (due
dates falling Sat/Sun roll to Monday in `tz`, default America/New_York —
**US market holidays are NOT modeled; widen `grace` to cover them**, e.g.
`74h` spans a Monday holiday), `daily`, `every:<N><s|m|h|d>`.

⚠ **The FIRST transition into `missed` is unaffected and alerts on the very
next scan.** CG-86 changed the cadence of REMINDERS only; no backoff, ceiling
or alert count can delay a first miss. Nothing is suppressed either — the
reminder keeps arriving, and each carries a fresh elapsed delta in its title,
so no two are the same message. The cause was a check that had not changed
state in seven days producing four consecutive days of byte-identical alerts.

**One Chat thread per check, and an all-clear (CG-86).** Every message about a
check shares one `thread_key`, `hb:<source>:<check_id>`: a thread root posted
once at the first alert, the alert, its reminders, and — new — a **recovery
notice on the `missed` → `ok` transition only**. A refresh of a check that was
already `ok` delivers nothing.

⚠ **ALL OF THEM ARE ROUTED BY YOUR `alert` ROUTE, WHATEVER THEY RENDER AS.**
Severity picks the destination SPACE as well as the loudness
(`route_for(app, severity)`), and threading is per-space — so a thread root or
an all-clear routed by its own quiet render severity would post into a
different space from the alert it belongs to, where nobody watching that alert
would see it. The thread root and the recovery therefore **render `info` and
route `alert`**: expect quiet-looking messages in your alert space.

⚠ **Titles carry no severity word or emoji.** They are `[<app>] <subject> —
<what changed>`; the gateway's own `severity_prefix()` supplies the severity,
and a title repeating it renders it twice. Bodies open with a UTC timestamp
line and close with an `Action:` line, including when the action is `none`.

```bash
curl -s $GW/v1/heartbeat -H "$AUTH" -H "$JSON" -d '{
  "check_id": "daily-trading-run", "schedule": "weekdays", "grace": "2h"}'
# -> {"status":"ok","check_id":"daily-trading-run","next_deadline":"2026-07-27T22:30:00+00:00"}

curl -s $GW/v1/heartbeat/aitrader -H "$AUTH"            # your checks + states
curl -s -X DELETE $GW/v1/heartbeat/aitrader/daily-trading-run -H "$AUTH"
```

**422s on this endpoint.** A bad `schedule`/`grace`/`tz` returns the parser's
own message. Since CG-76 there is a second one: **registering a `check_id` you
do not already have, while your app has no `alert` (or `default`) route, is
refused** — a dead-man check whose alert could never be routed is a check that
goes missed and tells nobody.

⚠ **It applies to registration only.** Because register and refresh are the same
call, a **refresh of an existing check is your liveness ping and is always
accepted**, even after the route disappears — refusing it would freeze
`last_seen`, drive the check into the missed state, and manufacture a
missed-check alert for a source that never died (⚠ this named the alert by its
title, `"heartbeat missed"`, until **2026-08-31** — CG-86 retired that wire
shape, and titles now lead with your app id and carry the elapsed delta; the
guarantee is unchanged). A route removed *after*
registration is covered at runtime instead: `heartbeats.alerts_undeliverable`
and `heartbeats.checks_undeliverable` degrade `/healthz`, and the check is left
unmarked so it delivers the moment the route is restored.

⚠ **The same registry fault is 503 on `/v1/notify` and 422 here, on purpose.**
503 says *the gateway cannot serve this right now*; 422 says *this request is
wrong and the caller can fix it*. Registering a dead-man check with no alert
route really is wrong at the moment it is made, so this endpoint chose the
status that points at the party holding the registry (CG-76 spec §4.2).

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
curl -s $GW/healthz?strict=1            # same body, but 503 when degraded
```

### `?strict=1` — for readers that judge by status code (CG-59, 2026-08-05)

`GET /healthz` returns **200 whatever it says** — including `"status":
"degraded"` with a full list of reasons. That is right for a human reading the
JSON and wrong for a **dashboard tile or a container health check**, which look
at the status code and never open the body. One of those went green over a dead
inbound path, which is what this parameter exists for.

**`?strict=1` returns 503 when `reasons` is non-empty, 200 otherwise — with a
byte-identical body.** Nothing else changes: same fields, same values, same key
order. If you diff the two responses you will find no difference, which is
deliberate; an operator comparing them must not learn anything false.

**Which one to point at:**

| Reader | Form | Why |
|---|---|---|
| a human, or anything that parses the body | plain `/healthz` | you are already reading `status` and `reasons` — the code adds nothing |
| a dashboard uptime probe (Homepage `siteMonitor`, Uptime Kuma, …) | **`?strict=1`** | it judges by code, so plain `/healthz` is green while inbound is dead |
| a **container** health check / orchestrator restart probe | plain `/healthz` | ⚠ deliberately. A 503 here makes the runtime restart a gateway that is *degraded but working* — one unresolved env var on a tier-1-only host is not a reason to kill a process that is delivering |

**The plain form's contract is unchanged and will stay unchanged** — it is opt-in
precisely so no existing reader has to move.

⚠ **The URL is `?strict=1`, and the exact spelling matters.** `strict` is a
boolean query parameter, so a bare `?strict`, an empty `?strict=`, or anything
unparseable is a **422 with a validation body** — not a health verdict, and a
probe misconfigured that way reads DOWN on a healthy gateway. `1`, `true`, `yes`
and `on` all work; `0`, `false`, `no`, `off` and omitting it entirely are all
non-strict.

### Durability counters at `/healthz`

This is where the queue journals — and, since 2026-08-02, the retention sweeper,
the outbound dispatcher and the heartbeat monitor — report themselves **to you**.
A boot line on the gateway's console says some of it as well, but that is the
operator's copy and you cannot read it. The table below has **forty-three**
rows: **nine** arrived with the journals on 2026-07-31, **fifteen** with the
sweeper, **twelve** with the two thread liveness blocks on 2026-08-02 — though
only **eleven** of that twelve are new **keys** in the body — **one** with
CG-75's audit-write guard on 2026-08-03, and **six** with CG-74's failure
counters the same day.
`heartbeats.last_scan_at` was already published and is documented for the first
time here, because it is the row that made a dead monitor look healthy. If you
diff the JSON across that date you will see eleven additions, not twelve; the
distinction is rows-in-this-table versus fields-in-the-response.

Of the forty-three rows, **eighteen carry `**yes**` in the Degrades? column**.
Counted as *fields* the number is **twenty-one**, and both are right: each of the
three liveness triples (`delivery.*`, `retention.*`, `heartbeats.*`) is read in
**combination**, so its `thread_started` row — marked *"no on its own"* — is part
of the judgement that degrades. Eighteen is what the column says; twenty-one is
what participates. A consumer that alarms on `status` should know what they mean
before one fires at 03:00. `status` is computed **from** `reasons`: anything that
can degrade this endpoint says so in words, because a number nobody reads is not
honest health.

⚠ **Two of those degrade paths are new on 2026-08-02, and a consumer already
alarming on `status` will meet them first.** Until then `/healthz` answered `ok`
with a dead outbound dispatcher and with a dead heartbeat monitor — `pending_jobs`
climbing, `last_scan_at` frozen at a real timestamp, and nothing saying so. Both
now degrade. If you alarm on `status`, expect these two reasons to be possible
where previously the endpoint was silent; that silence was the bug, not a
contract.

⚠ **Three more arrived on 2026-08-03, for the same reason.** Neither loop
counted a failed pass, so a dispatcher raising on every pass and one wedged
mid-send produced the same `/healthz` — and the staleness reasons said so in
words rather than answering. `delivery.consecutive_pass_failures`,
`heartbeats.consecutive_scan_failures` and `heartbeats.scan_failures` are the
answer, and the last of the three degrades **cumulatively**: see its row.

| Field | What it means | Degrades? |
|---|---|---|
| `delivery.replayed_at_boot` | outbound jobs restored from the journal at boot, attempt count preserved | no — the feature working |
| `inbox.replayed_at_boot` | pending inbound replies restored at boot; still yours to poll | no — same |
| `delivery.expired_at_boot` | queued jobs older than the 24h replay ceiling, **closed rather than posted** — a three-day-old alert delivered now actively misleads | **yes** |
| `delivery.unroutable_at_boot` | queued jobs that could not be rebuilt at boot: the registry no longer grants that identity (never sent on a withdrawn permission), **or** the stored payload no longer validates as an envelope — the outbound twin of `unrevivable` | **yes** |
| `delivery.delivery_failures` | accepted jobs that **exhausted the retry ladder** and were dropped. The in-process sibling of `expired_at_boot` / `unroutable_at_boot` above: the gateway returned `202` and then did not deliver. **Cumulative** | **yes** |
| `inbox.unrevivable_at_boot` | journalled replies that no longer parse as an `InboundReply`; dropped, not delivered | **yes** |
| `inbox.quarantined_at_boot` | how many of those were preserved in full — payload included — under the state dir's `quarantine/`, which is never pruned. Read it **against** the field above: that one is what left the queue, this one is what you can still recover | no — the recovery mechanism working |
| `inbox.quarantine_write_errors` | quarantine writes that **failed**. At least one unrevivable reply has **no preserved copy**, so only the per-app audit trail records that it ever arrived | **yes** |
| `delivery.journal_skipped_lines` | journal lines that did not parse. A torn trailing line is the *expected* shape after a power loss and is deliberately not fatal — a gateway that refuses to boot over a half-written byte is a crash loop | **yes** |
| `delivery.journal_write_errors` | journal writes that **failed** since start. The queues keep running — raising there would turn a full disk into a re-send storm — so while this is non-zero they are running **without** durability, and a reply you already polled can be delivered to you a second time after a restart | **yes** |
| `delivery.audit_write_errors` | delivery-log **audit file** writes that failed since start. Those deliveries have no on-disk record at all, and the per-app inbound audit files cannot substitute — they record what **arrived**, never what **left**. Delivery itself keeps working: this write is swallowed rather than raised, because raising it turned a full disk into an unbounded re-send storm against Google. **Cumulative and does not reset** — a line that never reached disk is never written by a later pass | **yes** |
| `delivery.thread_alive` | whether the **dispatch** thread is running **right now**. The direct signal, and nothing else in this table substitutes for it: `pending_jobs` reads non-zero for a busy dispatcher and a dead one alike, and zero for an idle deployment either way | **yes** — read with `thread_started` |
| `delivery.thread_started` | whether that thread was ever started. Read **with** the row above: alone, "not alive" cannot tell a dispatcher that was never started from one that died, and only the second is a fault | no on its own |
| `delivery.last_pass_at` | when a dispatch pass last **completed**. A pass that found nothing due **still stamps it** — deliberately, because at this gateway's traffic shape almost every pass is empty, and if only a non-empty pass stamped then "healthy and idle" would be byte-identical to "the thread is dead" for hours | no |
| `delivery.seconds_since_last_pass` | how stale `last_pass_at` is, as a **number**. `null` before the first pass | **yes** — past the budget below |
| `delivery.stale_after_seconds` | the silence budget: **600s**, and deliberately looser than the poll loop's. `process_due` walks due jobs sequentially and each send is bounded by a 30s client timeout — plus, for `mode: app` sends, a token refresh that runs on google-auth's own transport and is **not** bounded by it (no number is published for that leg because none has been measured). So a backlog all timing out holds the timestamp still while the dispatcher works perfectly. Ten minutes to notice a dead delivery thread is the price of not crying wolf at every slow Google call — and it is bought against a baseline of **never noticing at all** | no |
| `delivery.pass_interval_seconds` | the interval the budget is derived from — one second | no |
| `delivery.pass_failures` | dispatch passes that **raised**, over the life of the process. History, not a live fault — read it beside the row below, which is the one that degrades | no — see the next row |
| `delivery.consecutive_pass_failures` | passes that have raised **since the last good one**, so it returns to `0` on recovery. This is what tells a **raising** dispatcher from a **wedged** one; until 2026-08-03 nothing here could, and the staleness reason said so in words | **yes** — at 3 |
| `delivery.last_pass_error` | the exception **type** from the last failed pass — a type name, never a path or a message. Companion to the row above, not an independent signal, and cleared on recovery | no — reported with the row above |
| `retention.enabled` | whether the audit trail is being pruned at all. `false` means either no sweeper is wired or the window is `0` — the two are distinguishable: only the first carries a `note` and omits every field below | no |
| `retention.window_days` | the tenant window actually in force on this deployment, in days. Read this rather than assuming the 30-day default — it is one env var | no |
| `retention.unrouted_window_days` | the shorter floor applied to the gateway's own `_unrouted` bucket. Not per-tenant policy: `_unrouted` holds unattributable events that answer to nobody | no |
| `retention.files_deleted` | day-files pruned since this process started. **Deliberately not a fault at any magnitude** — a retention policy working is not a failure, and degrading on it would teach you to ignore `degraded` | no — the feature working |
| `retention.audit_dir_configured` | whether there is an audit directory to sweep at all. `false` means the deployment keeps **no** inbound audit trail (`CHAT_GATEWAY_INBOX_DIR` empty), which is a different fact from an empty window — without this row, `files_deleted: 0` reads the same for both | no |
| `retention.delete_errors` | day-files the OS **refused** to unlink. The trail is growing past the window this guide states, so the retention promise above is not currently being kept. **Cumulative and does not reset** — a file the OS refused is still sitting there past its window until a human intervenes | **yes** |
| `retention.sweep_failures` | whole sweep passes that **raised**, over the life of the process. History, not a live fault: read it beside the row below, which is the one that degrades | no — see the next row |
| `retention.consecutive_sweep_failures` | sweep passes that have raised **since the last good one**, so it returns to `0` on recovery. Louder than `delete_errors`: nothing is being pruned at all, so `files_deleted` and `delete_errors` both sit at a reassuring number while the window is not enforced | **yes** |
| `retention.last_sweep_error` | the exception **type** from the last failed pass — a type name, never a path. Companion to the row above, not an independent signal, and cleared on recovery | no — reported with the row above |
| `retention.last_sweep_at` | when a pass last **completed**. A pass that found nothing — no directory yet, or none configured — still stamps it, so this is **not** how you spot a dead sweeper: a dead one leaves a real, frozen, non-`null` timestamp here. Use the four rows below | no |
| `retention.thread_alive` | whether the sweep thread is running **right now**. The direct signal; every counter above only says what happened when a pass last ran | **yes** — read with `thread_started` |
| `retention.thread_started` | whether the thread was ever started. Read **with** the row above: alone, "not alive" cannot tell a sweeper that was never started from one that died, and only the second is a fault | no on its own |
| `retention.seconds_since_last_sweep` | how stale `last_sweep_at` is, as a **number** rather than two timestamps for you to subtract. `null` before the first pass | **yes** — past the budget below |
| `retention.stale_after_seconds` | the silence budget: twice the sweep interval. Published so the row above is checkable rather than magic | no |
| `retention.sweep_interval_seconds` | the configured interval the budget is derived from — six hours by default | no |
| `heartbeats.last_scan_at` | when the dead-man monitor last **completed** a scan. Like `retention.last_sweep_at`, this is **not** how you spot a dead monitor: a dead one leaves a real, frozen, non-`null` timestamp here, which is exactly what made it read as healthy. Use the three rows below | no |
| `heartbeats.thread_alive` | whether the **scan** thread is running right now. This is the dead-man switch's own dead-man switch: while it is `false`, **no registered check is being evaluated**, so a source that has gone silent will never be alerted on — and `missed` stops moving because nothing is scanning, not because nothing is wrong | **yes** — read with `thread_started` |
| `heartbeats.thread_started` | whether that thread was ever started. Same pairing as the two blocks above; a deployment that registers checks but never starts the monitor is a different fact from one whose monitor died | no on its own |
| `heartbeats.seconds_since_last_scan` | how stale `last_scan_at` is, as a number. `null` before the first scan | **yes** — past the budget below |
| `heartbeats.stale_after_seconds` | the silence budget: six scan intervals, floored at 300s. `scan_once` does no network I/O, so unlike delivery this needs no allowance for a slow remote call | no |
| `heartbeats.scan_interval_seconds` | the configured scan interval the budget is derived from — sixty seconds by default, and settable per deployment, which is why the budget is published rather than assumed | no |
| `heartbeats.scan_failures` | scans that **raised**, over the life of the process — and unlike its `delivery.*` counterpart this one **degrades**. ⚠ **Its original justification expired with CG-76**: before that row a raising scan had already marked the check and dropped the alert; now the mark happens only after the alert is accepted, so a raise risks a **delayed or duplicated** alert rather than a lost one. It stays degrading on the weaker reason — a monitor that keeps raising is not evaluating checks — and `heartbeats.alerts_undeliverable` is the counter for an alert actually lost. **Cumulative and does not reset** | **yes** |
| `heartbeats.consecutive_scan_failures` | scans that have raised **since the last good one**, returning to `0` on recovery. The live signal: the monitor is evaluating **no** registered check while this is climbing | **yes** — at 3 |
| `heartbeats.last_scan_error` | the exception **type** from the last failed scan. Companion to the row above; cleared on recovery | no — reported with the row above |
| `heartbeats.alerts_undeliverable` | dead-man alert **attempts** that came due and could **not be accepted for delivery**, over the life of the process. This is the dropped-alert counter — `scan_failures` is not, and said so until CG-76. An alert is dropped here without anything raising: the source has no `alert`/`default` route, or its routed identity is gone. ⚠ **Attempts, not distinct alerts, and the difference is large.** A check whose route stays broken is deliberately re-attempted on **every scan** so that it self-heals the moment the route returns — measured at **one increment (and one `GET /v1/deliveries` line) per scan, ≈1440/day at the 60s default interval, for a single misconfigured check.** Read `checks_undeliverable` for how big the fault is; read this for whether one ever happened. **Cumulative and does not reset.** A bare integer by design — `GET /v1/deliveries` (authenticated) names which check | **yes** |
| `heartbeats.checks_undeliverable` | how many **distinct checks** were in that state on the **last** scan — the number to size the fault by, where the row above sizes the retry cadence. Returns to `0` when the registry is fixed, so this is the live signal beside the cumulative row above | **yes** |
| `registry.inbound_defaulted` | app ids whose registry entry says **nothing** about `allow_inbound` and therefore inherit the loader's default, which is **deny** (CG-88, 2026-08-31; before that date the default was `true`, so omitting the key GRANTED inbound). Empty is the correct state. It exists because an operator diffing the three copies of the registry — two of them off-repo — has nothing else that says which posture came from a file and which came from the loader. **Not a fault at any length**: the gateway is denying, which is the safe answer, and degrading on a guarantee working would teach you to ignore `degraded` — the same verdict `retention.files_deleted` and `subscriber.suppressed_opt_out` already have | no — the safe default working |
| `heartbeats.checks_orphaned` | registered checks whose `source` is **not a registered app** — renamed, removed, or a registry block that failed to load. ⚠ **`checks` and `missed` above EXCLUDE these**, so without this row those two under-report the deployment's dead-man coverage while the checks are still scanned and their alerts still fail. A bare count, never the ids | **yes** |

Four things the field names do not tell you:

- **Two of the `delivery.*` fields count both queues.**
  `journal_skipped_lines` and `journal_write_errors` are sums across the
  outbound *and* inbox journals — despite the prefix. The other **thirteen**
  `delivery.*` fields, and **all four** `inbox.*` fields, are per-queue exactly
  as their prefixes say — including the six added on 2026-08-02 and the four
  added on 2026-08-03, all ten of which describe the outbound dispatch thread
  and nothing else. (This read *"the other three"* until 2026-08-02, which was
  true of the five-row block it was written for, *"the other nine"* until
  2026-08-03, and *"the other twelve"* until CG-76 added `delivery_failures`
  the same day.) Do not read the prefix as a guarantee on those two.
- **`delivery.audit_write_errors` is summed too, but in a different sense, and
  the two must not be folded together.** It is not a sum across two *queues* —
  the inbox has no delivery log. It is a sum across two `DeliveryLog`
  **objects**: a deployment that injects its own dispatcher gives that
  dispatcher a delivery log, and the gateway builds a second one for the HTTP
  surface unless it is handed the same instance. `/healthz` reads both and
  dedupes by identity, so the ordinary one-object deployment is not
  double-counted. Everything the prefix says about *which queue* still holds:
  it is outbound-only.
- **Twenty-five degrading fields — the field count from above, not the
  twenty-two rows the column marks — and the map to `reasons` lines is
  one-to-one in neither direction.** `expired_at_boot` and `unroutable_at_boot` share one
  entry: both mean "queued, then not delivered", and one investigation reads
  them together. In the other direction the `retention.*` liveness fields —
  `thread_started`, `thread_alive`, `seconds_since_last_sweep` — are read in
  **combination**, and produce exactly **one** entry between them at any moment:
  a dead thread also looks stale, and one fault must not print two reasons. **The
  `delivery.*` and `heartbeats.*` liveness triples added on 2026-08-02 behave
  identically** — same three fields, same at-most-one-entry guarantee — which is
  why they are three rows each rather than one, and why you should alarm on
  `status` rather than on any single row. Their `elif` **ordering** is no longer
  `retention.*`'s, and 2026-08-03 is where the two diverged: retention asks its
  failure counter first, these two ask `thread_alive` first, because a dead
  thread increments no counter and a restart is the more actionable answer. The
  at-most-one guarantee is identical; the order is not, and neither is a copy of
  the other. **One counter sits outside a chain entirely:**
  `heartbeats.scan_failures` can print a **second** `heartbeats:` reason beside
  whichever the chain produced, because "has an alert already been lost" is a
  different question from "is this loop running" and both can be true at once.
  **Since CG-76 there are four such outside-the-chain counters, not one**, and
  three of them are the ones that actually answer that first question —
  `alerts_undeliverable`, `checks_undeliverable` and `checks_orphaned` — so a
  `heartbeats:` block can now print several lines at once. That is deliberate:
  they are different investigations, not one fault described four ways.
  (It was five fields and four lines until 2026-07-31;
  `quarantine_write_errors` added one of each,
  `retention.*` added five fields and three lines on 2026-08-02, the two
  thread blocks added six fields and two lines the same day — 17 and 10 —
  CG-75's `audit_write_errors` added one of each on 2026-08-03: 18 and 11 —
  CG-74's failure counters added three fields and three lines the same day —
  21 and 14 — and CG-76 added four fields and four lines the same day again:
  **25 and 18**. CG-74's three lines are the two consecutive counters and
  `scan_failures`; its three cumulative-or-companion rows
  (`delivery.pass_failures`, `delivery.last_pass_error`,
  `heartbeats.last_scan_error`) add neither. CG-76's four are
  `heartbeats.alerts_undeliverable`, `heartbeats.checks_undeliverable`,
  `heartbeats.checks_orphaned` and `delivery.delivery_failures` — one line
  each, none of them a liveness signal and none of them in an `elif` chain.
  Recount against `service.py`'s `reasons` chain rather than trusting this
  sentence — a
  copied count is what `CLAUDE.md`'s test-count note is about — but count the way
  this table does, or you will land on a third number: **fields that participate
  in a degrade**, which includes each triple's `thread_started`, and **`reasons`
  entries**, of which a triple can emit at most one.)
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

---

## MCP server surface — `POST /mcp` (opt-in)

The gateway is also a Model Context Protocol server, so an MCP-speaking agent
sends through it with the same per-app key, the same identity allowlist and the
same delivery log as any other consumer. Off unless the operator sets
`GATEWAY_ENABLE_MCP=1`.

**It is another ingress to the send path above, not a new capability.** A
`send_message` tool call reaches the same `identity_for` check and the same
adapter that `POST /v1/messages` does, and writes the same `GET /v1/deliveries`
row. Nothing below the tool call is different code.

**One tool, `send_message`.** Its `inputSchema` is generated from the same
envelope `POST /v1/messages` takes, and its `identity` property carries an
`enum` of exactly the identities your key is allowed to use — so an agent
cannot form a call naming someone else's identity. That is defence in depth:
the same `identity_for` check still runs at call time, because a client may
call a tool it never listed. The enum's description reports each identity's
live readiness from the same function `/healthz` reads, so the two cannot
disagree about whether an identity is configured.

### Wiring a client — and the one way to get it wrong that leaks your key

**The scope you choose decides which file your API key lands in, and one of
those files is inside your git repository.** This is the whole of the hazard;
everything else here is typing.

Claude Code, the form that was used to wire this gateway's first agent tenant:

```bash
claude mcp add --scope local --transport http chat-gateway \
  http://<gateway-host>:8085/mcp \
  --header "Authorization: Bearer <your-key>"
```

⚠ **`--scope local` is load-bearing, not a default worth accepting quietly.**
Local scope writes the server — **including the literal header you just typed** —
into `~/.claude.json`, outside any repository. **`--scope project` writes
`.mcp.json` into the project directory**, which is a tracked file in most repos,
so the same command would put a live credential on a branch and, one `git add -A`
later, in your history. `claude mcp add` stores the header **verbatim**; it does
not substitute an environment variable for you. **Check afterwards** — `ls
.mcp.json` returning nothing is a one-second confirmation and it is worth taking.

If you *do* want the server committed so a team shares it, commit the **shape**
and never the secret — project scope with an environment reference:

```json
{
  "mcpServers": {
    "chat-gateway": {
      "type": "http",
      "url": "http://<gateway-host>:8085/mcp",
      "headers": {"Authorization": "Bearer ${CHAT_GATEWAY_API_KEY}"}
    }
  }
}
```

That file is safe to commit **only because the key is a reference**. The
distinction is exactly this gateway's own hard rule #2 — the registry holds env
var *names*, the environment holds values — applied one layer out, at the client.

Or by hand, which is also how you check a deployment answers at all:

```bash
curl -s $GW/mcp -H "$AUTH" -H "$JSON" -d '{
  "jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### Errors you will see, and which kind they are

MCP separates a **protocol** error (a JSON-RPC `error` — the request was
malformed) from a **tool** error (a normal `result` with `isError: true` — the
tool ran and refused). The split is not cosmetic: a protocol error is invisible
to the model, so it cannot self-correct.

| What happened | What you get |
|---|---|
| bad or absent bearer key | HTTP **401**, bare `WWW-Authenticate: Bearer` |
| your key is not granted that identity | HTTP 200, `isError: true`, text naming what you **may** use |
| arguments fail envelope validation | HTTP 200, `isError: true` |
| delivery failed | HTTP 200, `isError: true` |
| unknown tool name | HTTP 200, JSON-RPC `-32602` |
| unimplemented RPC method | HTTP **404**, `-32601` |
| body is not JSON, or is nested past Python's recursion limit | HTTP **400**, `-32700` |
| body is an array (batching), or a bare scalar | HTTP **400**, `-32600` |
| `jsonrpc` missing or not `"2.0"`; `method` missing or not a string | HTTP **400**, `-32600` |
| `params` present and not an object | HTTP **400**, `-32602` |
| a **notification** — any message with no `id`, any method, either era | HTTP **202**, **empty body** |

An identity refusal is deliberately a *tool* error: you asked a legitimate
question and got a legitimate refusal naming the alternatives, which is
something an agent can act on.

Two shapes worth calling out because clients get them wrong. A `params` of
`null` is treated as *absent*, not as malformed — a great many serializers emit
it that way. And a `notifications/*` method that carries an `id` is a `-32600`
rather than a `202`: it is a notification sent as a request, and answering it is
better than leaving the caller waiting for a reply that is never coming.

An argument-validation failure names the **field**: `invalid arguments for
send_message: ValidationError: text: Field required [missing]`. The offending
*value* is deliberately never echoed back.

### `/healthz` says whether it is armed

`GET /healthz` gains one field — `mcp: {"enabled": <bool>, "tools": [...]}` — and
it is a **config echo, not a counter**. It is never an input to `status` and
never adds a `reasons` entry at any value: a surface being switched off is a
configuration, not a fault. What it is *for* is telling an operator that the
running image both **has** this surface and **has it on**, which is two facts
you otherwise cannot get by probing.

✅ **That earned out on the first upgrade, 2026-08-11**: the field's absence and
then its presence were what distinguished the old image from the new one either
side of a redeploy. If you are checking whether a gateway you did not deploy can
serve you, `GET /healthz` and look for `mcp.enabled` — a `401` from `POST /mcp`
and a *surface not enabled* answer are not the same problem and this tells you
which you have.

### What it does NOT do, and why

**There is no inbound tool, and there will not be one that works the way you
would want.** MCP gives a server no way to push: a server cannot send a request,
cannot send an unsolicited notification, and cannot cause a model turn. An
inbound MCP tool could only ever be polling that an agent remembers to do. If
you need to react to a human's reply, use the per-tenant `callback_url` push or
`GET /v1/inbox` — both are better at it, and both are covered above.

**It is send-only in another sense too:** no `notify`, no `heartbeat`, no
delivery-log tool. `POST /v1/messages` is synchronous, so an agent gets an
answer it can act on; `POST /v1/notify` returns `202 enqueued`, which it cannot.
Dead-man checks are deliberately absent — a check registered by an agent session
goes missed the moment that session ends, and then ~~pages a human daily~~
**pages a human on the escalating backoff, forever: 1d, 2d, 4d, then weekly,
and it never stops on its own** (corrected 2026-08-31, CG-86). ⚠ **The backoff
does not weaken this rationale, it sharpens it.** The exclusion never rested on
the cadence; it rests on there being no session left to refresh or delete the
check, so the reminders run until a human intervenes — and a *weekly* reminder
about a job nobody remembers registering is easier to ignore than a daily one,
not harder to accumulate.

**`cards` is an opaque array here exactly as it is on `POST /v1/messages`.** The
gateway does not build cards and does not describe their structure to a model;
render your own and pass them through.

### Protocol notes

Streamable HTTP on a single endpoint, stateless, tools-only, JSON only —
`GET /mcp` and `DELETE /mcp` are `405`, because there is no stream and no
session. **Dual-era**: both the `2025-11-25` handshake protocol and the
`2026-07-28` stateless one are served on the same URL, because a client
speaking one cannot talk to a server speaking only the other. The era is
decided per request from modern-only signals — the `_meta` protocol version,
the `Mcp-Method` header, or an `MCP-Protocol-Version` header naming the modern
revision — so a modern client is never quietly served a legacy-shaped answer.
An `initialize` naming a version we do not support is answered with
**`2025-11-25`**, not the newest we speak: `initialize` exists only in the
legacy era, so the newest revision would be a version the asking client cannot
speak by construction. `server/discover` publishes the full list.
Authentication is
a static per-app bearer key, not OAuth; a `401` carries a bare
`WWW-Authenticate: Bearer` with no `resource_metadata` pointer, because there is
no authorization server to discover.

A present-but-unrecognised `Origin` header is refused with **403** — a protocol
MUST, and it fails closed because this server has no browser client.
`CHAT_GATEWAY_MCP_ALLOWED_ORIGINS` widens it if you ever need one. A request
with **no** `Origin`, which is what every non-browser MCP client sends, is
unaffected.
