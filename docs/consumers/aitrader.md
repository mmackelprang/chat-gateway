# Consumer contract — aitrader (notification + dead-man)

Recorded 2026-07-24 from the aitrader project's request. aitrader consumes
the gateway strictly as an HTTP service — no code imports either direction;
the gateway receives generic severity/title/body and never learns trading
semantics.

## How each requirement is met

| Requirement | Where |
|---|---|
| Single authenticated POST, curl-able, stdlib-only | `POST /v1/notify` (integration guide) |
| Accept fast, 2xx on enqueue, gateway owns retries | 202 + async dispatcher, backoff 0s/30s/2m/10m/1h → `failed` in log |
| Routing is config: (source, severity) → space | registry `apps.aitrader.routes` → `aitrader-alerts` / `aitrader-reports` identities |
| Severity rendering (alert loud, info plain) | `notifications.render` — alert card w/ ⚠️🔴 + prominent "What to do"; info plain text |
| Dedupe window w/ counter (default 1h) | `Deduper` — one delivered message per window; count carried on next delivery; every occurrence in the log |
| Threading via `thread_key` | passed through to Chat thread mechanics |
| Dead-man checks on the always-on side | `POST /v1/heartbeat` + gateway-resident monitor |
| Weekday awareness (no weekend false alarms) | `schedule: weekdays` — due dates on Sat/Sun roll to Monday in `tz` (default America/New_York) |
| Missed alerts repeat on backoff until refreshed/deleted | daily repeat, dedupe-collapsed |
| Check states queryable | `GET /v1/heartbeat/{source}` (own source only) |
| Decommission | `DELETE /v1/heartbeat/{source}/{check_id}` |
| Versioned paths, schemas, curls | `/v1/*`, `GET /docs`, integration guide |
| Per-source revocable tokens | per-app key env vars — rotate to revoke |
| Delivery log (enqueued→delivered/failed) | `GET /v1/deliveries` |
| Bodies never logged | delivery log stores titles + statuses only |

## Hard non-goals — enforced

1. **No inbound control path**: `apps.aitrader.allow_inbound: false` makes
   `GET /v1/inbox` a 403 for this key, and the gateway design has NO
   callback/webhook-to-consumer mechanism at all — inbound (where enabled
   for other apps) is passive polling only. A Chat message can never trigger
   an action in a consumer system through this gateway. (Gateway CLAUDE.md
   hard rule #6.)
2. **No consumer semantics in the gateway**: the notify shape is generic
   (severity/title/body/action); rendering varies only by severity.

## Documented limitations (accepted in the contract)

- **US market holidays are not modeled** — widen `grace` (e.g. `74h` covers
  a Monday holiday from a Friday run).
- **Queue is in-memory**: a gateway restart drops undelivered jobs; the log
  shows `enqueued`/`retrying` without a terminal status. aitrader keeps its
  local fallback log per its own design.
- Webhooks can't edit posted messages, so a dedupe window shows its
  collapsed count on the *next* delivered message, not by mutating the first.

## Acceptance status

Criteria 2–4 (dedupe 10×→1, weekday dead-man incl. weekend silence + daily
repeat, full delivery-log accounting) are encoded as deterministic tests in
`tests/test_notify_heartbeat.py` — passing. Criterion 1 (curl → loud card in
the alert space within seconds) needs the live webhook (LIVE-UNVERIFIED seam)
— run it as the first smoke test once the `aitrader-alerts` webhook URL is in
the env.
