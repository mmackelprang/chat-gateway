# CG-86 — the dead-man alert obeys the message policy: one thread per check

**Status:** design, 2026-08-31. Owner-reported defect; the owner's Google Chat
message policy is the spec.

## 0. The defect, as observed

The monitor posted **four consecutive days** of byte-identical alerts, each a
**new top-level message**:

```
⚠️ 🔴 [ALERT] heartbeat missed: candle-crawl
  ⚠️ 🔴 ALERT
  aitrader: heartbeat missed: candle-crawl
  No refresh since 2026-08-24T14:45:55.348463+00:00 (schedule every:15m, grace 45m).
  Repeats daily until refreshed or deleted.
```

Measured against the live gateway: that check's `last_alerted` was
`2026-08-31T15:47:52Z` against a `last_seen` of `2026-08-24T14:45:55Z` — it
re-alerts daily on a check that has not changed state in seven days.

## 1. What the code actually does — measured, because the brief's model was half wrong

The brief said *"`heartbeat.py` raises the alert; `delivery.py` renders and
posts it."* The first half is right and the second is not.

| Module | What it actually does |
|---|---|
| `heartbeat.py` | Owns the check state machine and the scan loop. Composes the alert's title and body. Calls `notify_fn(source, title, body, dedupe_key)`. |
| `service.py` `_monitor_notify` | The `notify_fn`. Wraps those strings in a `Notification(severity="alert", …)` and calls `emit_notification`. |
| `notifications.py` `render` | **The renderer.** Notification → `OutboundMessage`; applies `severity_prefix()` and builds the card. |
| `delivery.py` | The async dispatcher: enqueue, retry/backoff, journal, post via the adapter. **It imports no renderer** (`grep -n render src/chat_gateway/delivery.py` finds one unrelated comment). |

**Did the monitor's alerts use `thread_key` before? No.** The primitive exists
end-to-end and this path alone never used it: `Notification.thread_key` is a
declared field (`notifications.py:90`), `render` propagates it into
`OutboundMessage` on **both** branches (`:206`, `:227`), and the webhook
adapter's threading is live-verified. `_monitor_notify` simply never set it, so
every dead-man alert was an unthreaded top-level post. That is the gap.

**There is no recovery notification at all.** No `resolved` / all-clear path
exists anywhere in `src/`. A missed→ok transition currently delivers *nothing*;
`refresh()` silently resets `status` and `last_alerted`. So the brief's "prove a
state change (missed → ok) still delivers" could not have passed — there was
nothing to deliver.

## 2. The constraint that shaped the whole design — severity picks the SPACE

`registry.route_for(app_id, severity)` is `routes.get(severity) or
routes.get("default")`. In the shipped registry template, `aitrader` is:

```yaml
routes:
  alert: aitrader-alerts      # phone-visible space — loud
  warning: aitrader-reports
  info: aitrader-reports      # a DIFFERENT space
```

So **severity selects both the rendering and the destination space.** Emitting a
thread root or an all-clear as `severity: info` would post it into a different
Chat space from the alert it belongs to. Threading is per-space, so the thread
would not merely be wrong — the all-clear would land in a room where nobody
watching the alert would ever see it. That is the policy's *"a `RESOLVED` that
starts a new thread is a bug"* in a worse form, and it is why `RESOLVED` is
routed quiet in the first place.

**Therefore every message in a check's thread is routed as `alert`, whatever it
renders as.** D2 below decouples the two. This also inherits CG-76's
registration guard, which resolves the `alert` route before a check may be
stored — so a routed thread message is *more* reliable than an `info` one, not
less.

## 3. Decisions

### D1 — one thread per durable subject: the check

`heartbeat.thread_key_for(source, check_id) -> "hb:<source>:<check_id>"`.

⚠ **Capped at 128 characters, and the cap is load-bearing.**
`Notification.thread_key` is `max_length=128` and `HeartbeatIn.check_id` is
`max_length=100`, so a long source overflows it. A `ValidationError` raised
inside `_monitor_notify` is not an `HTTPException`, so it would escape to
`scan_once`'s per-check `except Exception`, be counted undeliverable, and the
alert would **never be sent, for the life of that check** — a new CG-76-class
silent door, opened by the fix for one. Over the cap, the key truncates and
appends `-<sha256(full)[:8]>` so distinct ids cannot collide.

### D2 — route severity and render severity are decoupled, for this path only

`emit_notification(app_id, n, *, route_severity: str | None = None)` routes by
`route_severity or n.severity` and renders by `n.severity`. Defaulting to
`None` leaves every existing caller byte-identical. Only `_monitor_notify` passes
it.

### D3 — the thread root, posted once per check

New persisted field `Check.thread_started: bool = False`. On the first alert for
a check that has none, `scan_once` emits the Thread Title first, then the alert,
both on the same `thread_key`. Rendered `info` (quiet), routed `alert`.

```
[<source>] 🧵 Heartbeat <check_id>
Subject: dead-man check <check_id> for <source> (schedule <s>, grace <g>, tz <tz>).
Closes when: the check refreshes, or is deleted.
Identifiers: source <source>, check_id <check_id>, thread <thread_key>.
Action: none — this message opens the thread.
```

⚠ **`thread_started` must survive `refresh()`.** `refresh()` constructs a
brand-new `Check` on every call — that is its documented semantics — so a field
left to its default would re-post a thread root **on every heartbeat ping**.
Carried over explicitly, and pinned by a test.

Lazily at first alert rather than at registration: a check that never misses
must never post anything.

### D4 — titles follow the policy format

`[<app>] <subject> — <what changed>`, app first, **no severity in the title**
(the gateway's `severity_prefix()` supplies it):

| Event | Title |
|---|---|
| first miss | `[<source>] heartbeat <check_id> — missed, no refresh for <elapsed>` |
| reminder | `[<source>] heartbeat <check_id> — still missed, <elapsed>` |
| recovery | `[<source>] heartbeat <check_id> — recovered after <elapsed>` |

Every body opens with its own UTC timestamp line and closes with an `Action:`
line, including when the action is `none`.

Leading with `<source>` has a second payoff the brief asked about: a check
misfiled under the wrong project announces that in its own title. The observed
`candle-crawl` was registered under `aitrader` while nothing in aitrader
produced it; `[aitrader] heartbeat candle-crawl — …` makes that visible on
sight, without building any new mechanism.

### D5 — the unchanged-state repeat: escalating backoff carrying the delta

`Check.alert_count: int` increments in `mark_alerted`.
`repeat_after(n, base) = min(base * 2**(n-1), MAX_REPEAT_S=604800)` → 1d, 2d,
4d, 7d, 7d… `alert_due` uses it in place of the flat window.

**Chosen over the two alternatives, deliberately:**

- *Plain suppression* is refused: the brief forbids dropping the reminder
  without a replacement, and a stale check would go invisible.
- *A separate cross-check digest* is refused because the policy's first rule is
  one thread per durable subject and the durable subject is the **check**. A
  digest necessarily spans checks, so it would have to live in a different
  thread from the alerts it summarises — splitting the subject and orphaning the
  all-clear, which is the same defect this PR exists to close.

The reminder is not an "unchanged state" post: its title carries the elapsed
delta, which is precisely the policy's own `stalled 2h14m` example. Backoff is
what stops it being a drip.

Effect on the observed defect: four identical top-level messages over four days
becomes one thread root, one alert, and two threaded reminders (day 1 and day 3)
whose titles each carry a different elapsed time.

⚠ `test_repeat_window_must_exceed_the_dedupe_window` is preserved a fortiori —
backoff only ever lengthens the interval.

### D6 — RESOLVED, threaded under the alert it closes

On `POST /v1/heartbeat` for a check whose **stored** status is `missed`, emit a
recovery message: rendered `info` (the policy's quiet lane), routed `alert` (D2,
so it lands in the alert's space), on the check's `thread_key`.

⚠ **Only on the missed→ok transition.** A refresh of an `ok` check must deliver
nothing. This is the highest-risk line in the change: registering and refreshing
are the same call, aitrader pings on schedule, and a bug here posts to Chat on
every ping. Pinned by a test that asserts zero sends across repeated healthy
refreshes.

The previous status is read under the same lock that writes the new check —
`HeartbeatStore` gains a method returning `(new_check, previous_status)`;
`refresh()` stays a thin wrapper with its existing signature so no existing
caller or test moves.

⚠ **The recovery notify must never break the refresh route.** It is wrapped so a
routing failure is logged and swallowed. Refreshing *is* the liveness ping;
failing it would freeze `last_seen` and manufacture the false outage
`refresh_heartbeat`'s existing comment records as measured end-to-end.

## 4. Out of scope, raised rather than fixed

**The `⚠️ 🔴` rendered twice is `notifications.render`, not this path.** The
`text` field carries `severity_prefix()` and the card header carries the emoji
and severity word again — for **every severity and every tenant**, not just the
dead-man path. The monitor's own authored title contains no severity, so it
already satisfies the policy clause the brief cites it under; the duplication is
the gateway rendering its own severity twice in one message. Changing it alters
every tenant's rendered output and is pinned across two test files. Filed as
**CG-87** for the user's call, with options, rather than folded in here.
