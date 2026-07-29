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
 "action":{"id":"verdict","params":{"job_id":"job-123","verdict":"approve","nonce":"n-9"}},
 "dedupe_key":"ps-42","event_type":"CARD_CLICKED","received_at":"...","raw":{...}}
```

Rules of the road: delivery is **at-least-once** (`dedupe_key` = the Pub/Sub
message id — make your handler idempotent; self-contained button tokens
help); selection-widget values arrive merged into `action.params`; users not
on your `allowed_users` list are refused in-thread and never reach you; if
your callback is down, retries span ~10s and then the gateway posts your
`unreachable_message` into the thread — the user always sees a tap that
didn't land. Return any 2xx quickly; do your work async.

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
into an empty `MESSAGE`.

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
