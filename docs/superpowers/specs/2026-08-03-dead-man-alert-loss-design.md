# The dead-man switch's doors — design

| | |
|---|---|
| **Row** | **CG-76** — a failed heartbeat scan silently drops the dead-man alert. **Widened by user decision, 2026-08-03**, from one door to every door |
| **Status** | spec, awaiting review |
| **Baseline** | `main` at `d09a07c`, suite **345 passing** — re-measured with `python3 -m pytest -q`, not copied from a row |
| **Hard rule** | **#5** — `/healthz` stays honest |
| **Contract surface** | aitrader's. `docs/consumers/aitrader.md` §7 — a real-money system whose entire gateway relationship is *"tell me when a source goes quiet"* |
| **Pre-deploy blocker** | **yes** (user decision 2026-08-02). On **CG-55**'s dependency list |

---

## 0. The shape of the finding, before any detail

CG-76 was filed as an **ordering defect** in `HeartbeatStore.due_alerts`. The
user widened it, on the reasoning that fixing one door while leaving another
open ships a row that does not close the failure it names.

That instinct was right, and it was **understated**. The answer to *"is the count
two?"* is **no — and it is not four either.** This spec found **six** distinct
ways a registered dead-man alert is never delivered while `GET /healthz` answers
`status: ok` with `reasons: []`, plus two amplifiers and two adjacent findings
that belong to other rows.

**Three of the six need no disk fault, no exception, and no misconfiguration.**
They fire in ordinary operation, on the default configuration, against a healthy
disk.

### ⚠ How the count moved, because the process finding is worth more than the number

| Sweep | Found | By |
|---|---|---|
| accident, week 1 | door 1 | CG-76's filing Planner, sweeping unguarded **writes** for CG-75 |
| accident, week 2 | door 2 | CG-74's Builder during UAT, then independently by its reviewer |
| **deliberate sweep #1** | doors 3, 4 + the batch amplifier | this spec, looking on purpose |
| **deliberate sweep #2** | **doors 5, 6** + 2 adjacent | an **independent** re-sweep of the same path, commissioned because the brief asked whether two was the complete count |

⚠ **The second deliberate sweep found two more doors than the first deliberate
sweep — and door 6 is the worst of all six.** That is the finding to carry out of
this row. It is not that the original count was two; it is that *four rounds of
looking produced four different answers*, and the only reason the count is now
six rather than four is that somebody was asked to check the checker. **This is
CG-69's thesis restated as evidence rather than argument** (§1.1).

The enumeration below is exhaustive against the path as it exists at `d09a07c`
**to the limit of two independent sweeps**, and §2.11 records what was tested and
**falsified**, so the boundary of the claim is visible rather than implied. It is
stated at that confidence and no higher.

---

## 1. Where this came from

| | |
|---|---|
| **Door 1** | filed as CG-76 by CG-74/CG-75's Planner, 2026-08-03, from the sibling-write sweep |
| **Door 2** | found by **CG-74's Builder** during that row's UAT, then found **independently** by its pre-merge reviewer reading the code. Recorded as CG-74's finding **M2** and pinned by a test |
| **Doors 3 + 4** | found by this spec's first sweep, 2026-08-03. Measured, not reasoned about — output in §2.3 and §2.4 |
| **Doors 5 + 6** | found by an **independent second sweep** of the same path, same day, commissioned because the brief asked whether two was the complete count. Door 6 moves **zero** `/healthz` fields and is the worst of the six |

### 1.1 ⚠ A merged claim that was false, and the correction it owes

`docs/superpowers/specs/2026-08-03-delivery-write-path-robustness-design.md` §5,
line 421, says — and still said on `main` at `d09a07c` when this spec was
written:

> **The counter is not the fix.** CG-76 is. Until CG-76 lands, this counter is
> the only thing standing between a silently-dropped aitrader alert and a green
> `/healthz`.

**The second sentence is false.** `scan_failures` is the only `/healthz` signal
for a scan that **RAISES**. It is not a signal for "a dropped dead-man alert",
and the gap is not marginal: **five of the six doors in §2 drop the alert without
raising anything at all**, so `scan_failures` stays `0` and `/healthz` stays `ok`
through every one of them. On door 6 **not a single field in the entire body
moves.**

**How it was found, recorded because the *how* is the reusable part.** CG-74's
Builder hit door 2 during that row's UAT; its pre-merge reviewer then found the
same thing independently, by reading `_monitor_notify` rather than by running
anything. Neither found it by reviewing a diff — **the diff never contained the
sentence it broke**, which is CG-69's whole thesis. The Builder narrowed the
claim where it lived in `heartbeat.py`, pinned it with
`test_a_routeless_alert_is_dropped_without_raising_or_counting`, and
**deliberately did not edit this Planner artifact** — correct on lanes, which is
why the correction lands here.

**What is true instead**, and it is the sentence that should have been written:

> `scan_failures` is the only `/healthz` signal for a scan that **raises**. A
> scan can drop a dead-man alert without raising — by refusing it for want of a
> route (§2.2), by exhausting the retry ladder (§2.3), by having it deduped
> (§2.4), by belonging to a source the registry no longer lists (§2.5), or by
> being a **repeat** of an alert already counted (§2.6) — and in all five
> `scan_failures` stays `0`.

The false sentence is **corrected in place in that spec, not deleted**: the
original wording is quoted, marked wrong, attributed to how it was found, and
followed by the true statement. Same discipline `CLAUDE.md` applies to its own
stale bullets — a silently rewritten claim teaches a reader that this repo's
absolutes are safe to trust, which is the belief that produced the false one.

⚠ **This is the FIFTH merged claim to go false this week and be caught only
because somebody independently went looking.** That is **CG-69**'s territory —
the published-promise inventory — and CG-69 **still has no plan**. This spec does
**not** plan CG-69. It adds today's instance to that row's evidence table, so
whoever eventually plans it inherits the real list rather than reconstructing it.

---

## 2. What was measured — six doors

Every measurement below builds a **real** `create_app`, a **real** `Dispatcher`,
a **real** `HeartbeatStore` on a real temp file, and drives `/healthz` through a
real `TestClient`. Nothing is monkeypatched except the clock, which is the
injectable `now_fn` the classes already take.

Path swept, end to end:

```
HeartbeatStore.due_alerts  ->  HeartbeatMonitor.scan_once  ->  HeartbeatMonitor._run
   ->  service._monitor_notify  ->  service.emit_notification
   ->  Deduper.check / render  ->  Dispatcher.enqueue
   ->  Dispatcher.process_due  ->  Dispatcher._finish  ->  DeliveryLog.record
```

### 2.1 Door 1 — the mark lands before the alert does

`heartbeat.py:154–166`. `due_alerts` sets `check.status = "missed"` and
`check.last_alerted = now` at **`:161–162`**, under the lock, then `_save()`s at
**`:165`** — **all before returning `fired`** to `scan_once`, which is the caller
that actually notifies (`heartbeat.py:223–234`).

A raise anywhere downstream therefore leaves the check marked alerted and the
alert never sent. `alert_due` then returns `False` for the whole
`DEFAULT_REPEAT_S` window — **24 hours** — and the next idle scan re-stamps
`last_scan_at`, so `/healthz` recovers to green while the alert is gone.

Two variants, both previously measured by CG-76's filing Planner and reproduced
here:

- **D** — `_save()` raises inside `due_alerts`. The marks are set in memory
  **before** the save, so they survive the failure. `scan_once` raises before
  notifying anything.
- **E** — `_save()` lands, then the notify's `enqueue` hits the journal `open`
  (unguarded **by design**). **The suppression is on disk and survives a
  restart.**

**Both variants DO move `scan_failures`** — CG-74 shipped that signal and
validated it on a real server against a real kernel `PermissionError`. Door 1 is
therefore the **one door of the four that is currently visible at `/healthz`**.
It is still a defect: the alert is lost, and the counter reports the loss rather
than preventing it.

⚠ **`_save()` is `heartbeat.py:120–127` and is unguarded.** The sibling sweep in
the CG-75 spec classified it as this row's business, and it still is — but §3
resolves it by **moving the write**, not by wrapping it.

### 2.2 Door 2 — the route refusal that never re-raises

`service.py:294–300`:

```python
def _monitor_notify(source: str, title: str, body: str, dedupe_key: str) -> None:
    try:
        emit_notification(source, Notification(
            severity="alert", title=title, body=body, dedupe_key=dedupe_key,
        ))
    except HTTPException as exc:  # no alert route configured — log, don't die
        log.record(source, "heartbeat", title, "failed", f"no route: {exc.detail}")
```

The `except` at **`:299`** falls through to a `log.record` at **`:300`** and
**nothing else. It never re-raises.** So `scan_once` completes normally,
`last_scan_at` stamps, `scan_failures` never increments, and `/healthz` stays
`ok` while the dead-man alert is gone — suppressed for 24h by the mark door 1
already applied.

⚠ **The comment is NARROWER THAN THE CATCH, and that matters.** It says *"no
alert route configured"*. The catch is `HTTPException`, and `emit_notification`
converts **every** `RegistryError` into one (`service.py:283–284`). `route_for`
raises `RegistryError` on **four** distinct conditions
(`registry.py:148–159` and the `identity_for` it delegates to at `:139–146`):

| Condition | `registry.py` |
|---|---|
| the source app is not in the registry at all | `:150–151` |
| no `alert` route and no `default` route | `:153–158` |
| the app may not send as the routed identity (allowlist changed) | `:139–141` |
| the routed identity is not registered (identity deleted) | `:143–145` |

All four are silently swallowed here. A reader who trusts the comment would look
for one cause and find four.

⚠ **This is not hypothetical for two of the three registered consumers.**
`config/registry.example.yaml` — the committed example, mirrored by the live
gitignored file — gives **`aiteam-harness` (`:51`) and `job-hunter` (`:67`) no
`routes:` block at all**. Only `aitrader` (`:73`) has one. If either of the other
two ever registers a dead-man check, **every alert it ever generates is dropped
through this door, permanently, with `/healthz` green.** The endpoint that
registers the check (`POST /v1/heartbeat`, `service.py:340–349`) accepts it
without checking that an alert could ever be routed.

### 2.3 Door 3 — the retry ladder runs out and nothing counts it

**A new finding.** `BACKOFF_S = (0, 30, 120, 600, 3600)` (`delivery.py:39`). When
a send keeps failing, `process_due` walks the ladder and finally calls
`_finish(job, "failed", ...)` at **`delivery.py:351`**. That writes a delivery-log
line and removes the job. **No `/healthz` counter moves.**

`delivery.expired` and `delivery.unroutable` exist — but they are published as
**`expired_at_boot` / `unroutable_at_boot`** (`service.py:464–465`) and are only
ever incremented by **boot replay**. There is **no counter anywhere for a
terminal in-process `failed` delivery.**

Measured on a real app, real dispatcher, adapter failing every send, clock walked
past the full ladder:

```
H1 — RETRY-LADDER EXHAUSTION: alert enqueued, every send fails
  scan_once fired            : 1
  sends that reached Google  : 0
  jobs still pending         : 0
  delivery-log terminal state: ['enqueued', 'retrying', 'retrying', 'retrying', 'retrying', 'failed']
  heartbeats.scan_failures   : 0
  delivery.pass_failures     : 0
  delivery.expired_at_boot   : 0
  delivery.unroutable_at_boot: 0
  check.status/last_alerted  : missed / 2026-07-27T23:00:00+00:00
  /healthz status            : ok
  /healthz reasons           : []
  ==> ALERT DROPPED, /healthz GREEN: True
```

**`pass_failures` stays `0` because nothing raises** — `process_due` catches the
send exception inside its own loop (`delivery.py:348`) and categorises it. This
is the loop working exactly as designed; the design simply has no terminal-loss
counter.

⚠ **Note what this door means for the aitrader contract specifically.** Google
Chat being unreachable for ~73 minutes is the single most likely real cause of
this, and it is *precisely* the window in which a dead-man alert matters. The
alert is discarded at the end of it with no trace on the endpoint aitrader
alarms on.

⚠ **This door is CG-75-adjacent and must not be confused with it.** Before CG-75,
`_finish` on this path *raised* (a full disk), which produced the 1/second storm
and **did** trip staleness. CG-75 guarded that write — correctly. The
consequence, stated here rather than left for a reader to trip over: **post-CG-75
the ladder exhausting is silent**, because the only thing that used to make it
loud was a bug.

### 2.4 Door 4 — the deduper suppresses a genuinely new outage

**A new finding, and the sharpest of the four**, because it needs no fault of any
kind — no disk error, no misconfiguration, no exception, no unreachable Google.

`scan_once` passes `dedupe_key=f"hb:{check.check_id}"` (`heartbeat.py:231`).
`emit_notification` runs that through `Deduper.check` (`service.py:285`), whose
window is `DEFAULT_DEDUPE_WINDOW_S = 3600` (`notifications.py:38`). When it
suppresses, `emit_notification` **returns** `{"status": "deduped"}`
(`service.py:289`) — and `_monitor_notify` **discards the return value entirely**
(`service.py:296`). A suppressed alert is indistinguishable from a sent one at
every layer above.

The realistic sequence, and it is the **flapping** case:

1. A source goes quiet. The check goes missed, an alert fires and is delivered.
2. The consumer recovers and `POST /v1/heartbeat` refreshes the check. Per
   `docs/consumers/aitrader.md` §7, refresh builds a **brand-new check** —
   `status` back to `ok`, **`last_alerted` cleared** (`heartbeat.py:136–142`).
   The dead-man's own 24h suppression is now correctly reset.
3. The source dies **again**, inside the deduper's 1-hour window.
4. `due_alerts` correctly fires. `emit_notification` **dedupes it against the
   first outage's alert** and returns `"deduped"`. `_monitor_notify` ignores
   that. The check is marked alerted for another 24h.

Measured:

```
H2 — DEDUPE: missed -> alert -> refresh -> missed again inside 3600s
  alert #1 sends             : 1
  after refresh              : status=ok last_alerted=None
  2nd outage: scan fired     : 1
  TOTAL sends to Google      : 1   (expected 2)
  delivery-log statuses      : ['enqueued', 'delivered', 'deduped']
  check.status/last_alerted  : missed / 2026-07-24T20:41:00+00:00
  heartbeats.scan_failures   : 0
  /healthz status            : ok
  /healthz reasons           : []
  ==> 2nd REAL OUTAGE DROPPED, /healthz GREEN: True
```

**Two distinct outages, one alert.** The second one is exactly the event a
real-money system most needs to hear about — a source that came back and died
again — and it is the one the gateway swallows.

⚠ **The root cause is that two independent suppression mechanisms are stacked on
one alert, and they do not compose.** `alert_due()` (`heartbeat.py:95–100`)
**already is** the dead-man's dedupe: it guarantees at most one alert per check
per `DEFAULT_REPEAT_S` (24h). The `Deduper`'s window is 1h. Since 24h > 1h, the
deduper can **never** suppress an actual duplicate on this path — the monitor
never emits one. **Every suppression it performs on this path is a false
positive.** The `dedupe_key` here is pure downside; it has no upside case at all.

### 2.5 Door 5 — the check whose source left the registry vanishes from `/healthz`

**Found by the independent second sweep.** Two invisibilities compounding.

`/healthz` builds its heartbeat census as
`hb_all = [c for s in registry.apps for c in checks.list_for(s)]`
(`service.py:443`) — **filtered through the registry**. But the store is keyed by
the app id **as it was at registration time** (`heartbeat.py:140`) and persists
to `heartbeats.json` under `CHAT_GATEWAY_STATE_DIR`, untouched by any registry
edit.

So if a tenant is renamed, removed, or its registry block fails to load:

```
before rename: heartbeats {"checks": 1, "missed": 0, ...}
after rename : heartbeats {"checks": 0, "missed": 0, ...}   <-- the check has VANISHED
but the store still holds it: ['loop']
scan_once -> 1 fired; adapter.sent=[]
delivery log under the DEAD source id: [... "status":"failed", "detail":"no route: unknown app 'aitrader'"]
status 'ok' -> 'ok'
```

**The check is still scanned, still comes due, and its alert still dies** — via
door 2's `unknown app` branch (`registry.py:150–151`). Meanwhile `/healthz` says
there are **zero registered checks**, which is a stronger and more misleading
claim than saying nothing: an operator reading `checks: 0` concludes the
deployment has no dead-man coverage to worry about, at the exact moment it has
coverage that is silently broken.

### 2.6 ⚠ Door 6 — the 24-hour REPEAT alert drops with ZERO fields moving

**Found by the independent second sweep. This is the worst of the six**, and it
is the one that would still have been open had this row shipped on the first
sweep's four.

`heartbeats.missed` is computed as
`sum(1 for c in hb_all if c.status == "missed")` (`service.py:512`).
`due_alerts` sets `status = "missed"` on the **first** fire. Every subsequent
repeat — the daily re-alert that exists precisely to **keep shouting** while a
source stays silent — fires against a check that is **already counted**.

So when a repeat alert dies (revoked webhook, ladder exhaustion, dedupe, any
door above), `missed` does not move, because it was already `1`:

```
first alert delivered: 1
repeat scan -> 1 fired; adapter.attempts=6; sent still 1
delivery log tail: {..."status":"failed","detail":"gave up after 5 attempts: chat unreachable"}
status 'ok' -> 'ok'
FIELDS THAT CHANGED (excluding clock-driven timestamps):
  (NONE — literally nothing moved)
```

**Not one field in the entire `/healthz` body changes.** The source has now been
silent for over a day, the mechanism designed to keep reminding you has stopped
reminding you, and the endpoint aitrader alarms on is byte-identical to a healthy
deployment.

⚠ **Every other door in this spec at least moves `heartbeats.missed` from `0` to
`1`. Door 6 does not, and §2.8 shows why that was never worth anything anyway.**

### 2.7 ⚠ The amplifier — one tenant's fault strands another tenant's alert

Not a fifth door: it is door 1's mechanism applied **across tenants**, and it
multiplies the blast radius of all four.

`scan_once` (`heartbeat.py:225–232`) iterates `fired` with **no `try` inside the
loop**, and `fired` can hold checks belonging to **different apps** — `hb_all` at
`service.py:443` confirms the store is gateway-wide, keyed `(source, check_id)`.
If check #1's notify raises, checks #2..N are **never attempted** — yet
`due_alerts` has already marked **all of them** alerted.

Measured with three checks owned by three different apps, the middle one
routeless:

```
  scan_once RAISED           : RuntimeError
  notifies that succeeded    : ['aitrader']
  checks marked alerted      : [('aitrader', 'missed', True), ('job-hunter', 'missed', True), ('aiteam-harness', 'missed', True)]
  last_scan_at stamped       : None
  NEXT scan fires            : 0 check(s)
  ==> ONE tenant's fault stranded 1 OTHER tenant(s): True
```

**`aiteam-harness`'s alert was never attempted, is marked alerted, and the next
scan fires zero checks.** A misconfiguration in `job-hunter`'s registry
block — §2.2 shows both of those apps have no `routes:` at all — silently
suppresses `aiteam-harness`'s dead-man alert for 24 hours. `scan_failures` does
move here (the raise reaches `_run`), so `/healthz` degrades — but it degrades
saying *a scan raised*, not *another tenant's alert was eaten*.

⚠ This is why D1's marking must be **per check, not per batch** (§3), and it is
an isolation argument of the kind hard rules #4 and #6 already apply to inbound.

⚠ **`scan_failures` counts per SCAN, not per ALERT.** Three lost alerts, **one**
increment. The existing reason string's *"at least one dead-man alert may already
have been lost"* is technically accurate and materially understates it. The
per-alert counter D2 adds (`alerts_undeliverable`) is incremented **per check**,
which is the shape this needed.

### 2.8 ⚠ The control — `heartbeats.missed` is not a signal, and never was

Measured deliberately as a control, and it is the reason no fix in this spec
leans on that field:

> A **successfully delivered** alert produces the *identical* `/healthz` diff to
> a dropped one — `heartbeats.missed: 0 -> 1`, plus liveness timestamps.

`missed` says *a registered check is currently in the missed state*. It says
nothing whatsoever about whether anybody was told. It is inert (it feeds no
`reasons` branch, appearing only inside reason **strings**), it moves identically
on success and on every door, and on door 6 it does not move at all.

**Any fix that tried to make `missed` the dropped-alert signal would be wrong in
both directions.** The counters in §8 are per-alert-attempt for this reason.

### 2.9 ⚠ Adjacent findings — real, measured, and deliberately OUT of scope

The second sweep surfaced two further defects on neighbouring surfaces. They are
recorded here **with their measurements** and filed as their own rows rather than
folded in — folding a good finding into an open row is the scope creep this queue
keeps correcting, and neither is a *dropped alert* in the sense the other six
are.

**A · Clock skew silently disarms the dead-man — filed as CG-77.**
`is_missed` compares against `last_seen + period + grace` and `alert_due` against
`now - last_alerted` (`heartbeat.py:92–100`); **both timestamps are persisted**
(`:107, :138–139, :162`). A host whose clock ran ahead when `refresh()` last
wrote — a VM resumed from snapshot, a pre-NTP boot, container drift — then
corrected backwards, leaves a check that **never becomes due**:

```
last_seen=2026-07-27T12:00 (3 days ahead)  deadline=2026-07-27T12:10  now=2026-07-24T12:00
  at now +1h: is_missed=False  due_alerts fired=0
  at now +1d: is_missed=False  due_alerts fired=0
last_alerted a month in the future, check IS missed: due_alerts fired=0
```

`/healthz` never publishes a deadline at all — the only place one is visible is
the **authenticated** `GET /v1/heartbeat/{source}` (`service.py:359`). ⚠ **Out of
scope because it is a different defect class:** the other six drop an alert that
became due; this one prevents it *becoming* due. The fix is a bounded-future
sanity check on persisted timestamps, which is its own design question.

**B · Every `delivery` reason is gated on `thread_started` — CG-72's family, not
this row's.** All four branches at `service.py:882, 890, 898, 906` begin
`queue["thread_started"] and ...`, so a dispatcher that was never started shows
`pending_jobs=1, thread_started=False, status='ok', reasons=[]`. ⚠ **That gate is
deliberate and CG-72 documented why** — every offline test builds an app without
starting one, and a never-started loop is not a fault. Narrow in production
(`__main__.py:187` starts it, and a `start()` that itself raised leaves
`_started=True` and trips the dead-thread reason). **Recorded as residue on
CG-72's design, not reopened here.**

### 2.10 The one thing all six doors share

> **`due_alerts` records "I have alerted" at a moment when nothing has been
> alerted.**

The mark is a **promise about the future** — *an alert will be sent* — persisted
as a **statement about the past** — *an alert was sent*. Every door is a
different way for the future to fail to arrive, and doors 5 and 6 are two ways
for `/healthz` not to notice even so.

That is the same defect class CG-65 named in its own title — *replace the promise
before deleting it* (`8d6a5d6`) — and it is why the six doors are one row rather
than six. §3 fixes the shared cause; §4–§6 close the residue each door leaves
once the shared cause is fixed, and §8's counters are what make the residue
visible.

### 2.11 ⚠ What was tested and FALSIFIED — the boundary of the claim

Recorded so the enumeration is bounded rather than merely asserted. A reader
should be able to see what was ruled **out**, not just what was ruled in.

| Hypothesis | Verdict |
|---|---|
| `Notification(...)` in `_monitor_notify` can raise `ValidationError` on a long `check_id`, dropping the alert | **FALSE via the endpoint.** `HeartbeatIn.check_id` is `max_length=100` (`service.py:239`); the title is `f"heartbeat missed: {check_id}"` = ≤118 against `Notification.title`'s `max_length=200` (`notifications.py:85`), and `dedupe_key` is ≤103 against `max_length=128` (`:89`). Bounded by the front door. A hand-corrupted `heartbeats.json` could still exceed it — `HeartbeatStore._load` (`:113–118`) does no length validation — but that raise **does** propagate and **is** counted, so it is not a silent door |
| A terminal `failed` delivery degrades `/healthz` via some other field | **FALSE.** Measured in §2.3 — `pass_failures`, `expired_at_boot`, `unroutable_at_boot` all stayed `0`, `reasons` was `[]` |
| `journal_write_errors` / `audit_write_errors` cover doors 3 and 4 | **FALSE.** Neither door touches a failing write. §2.3 and §2.4 ran on a healthy disk |
| The staleness branch catches any of these | **FALSE.** `last_scan_at` stamps at `heartbeat.py:233` on every completed scan, and doors 2/3/4 all complete normally |

---

## 3. Decision D1 — where the "alerted" mark belongs

**Chosen: mark the check alerted only after the alert has been ACCEPTED INTO THE
DURABLE QUEUE.**

`due_alerts` is split into a **selector** that mutates nothing and an explicit
**`mark_alerted`** that `scan_once` calls with the checks whose notify actually
succeeded.

### What "accepted" means, precisely

`emit_notification` returned `{"status": "enqueued", ...}`. At that instant:

- `Dispatcher.enqueue` has written the journal `open` record
  (`delivery.py:320–324`) — **unguarded on purpose**, so a queue that cannot
  persist the job refuses it rather than accepting it;
- the job is in `_jobs`;
- from there the retry ladder and boot replay own it.

**This is the same seam the gateway already gives an external consumer.**
`POST /v1/notify` returns **202 accepted** at exactly this point
(`service.py:335–337`). The dead-man monitor is an internal caller of the same
pipeline, and giving it a *different*, weaker contract than a paying consumer
gets is the anomaly. D1 removes the anomaly rather than inventing a seam.

### Which returns count as accepted

| `emit_notification` returns | Marked alerted? |
|---|---|
| `{"status": "enqueued"}` | **yes** |
| `{"status": "deduped"}` | **no** — and §6 removes this case from the path entirely |
| raises (`HTTPException` or anything else) | **no** |

`_monitor_notify` today discards the return value. It must stop.

### The failure mode this creates, named rather than discovered later

**A notify that succeeds but whose mark is lost re-alerts.** Concretely: the
alert is enqueued, then `mark_alerted`'s `_save()` fails, or the process is
killed between the two. On the next scan — or the next boot — the check is still
unmarked and **alerts again**. That is a **duplicate alert**, not a dropped one.

### ⚠ Checked against this project's recorded precedent, not decided fresh

The brief asked for this check specifically, and the precedent is unambiguous and
in three places:

| Precedent | Wording |
|---|---|
| `delivery.py:392–396` — `_finish`'s mid-flight window | *"A process killed here replays the job and delivers it TWICE. Deliberate — Chat gives us no idempotency key, so the alternative is a two-phase commit we are not building, and **losing an alert is the worse failure**."* |
| `delivery.py:283–297` — `_journal_write` | a failed `close` costs *"at most one duplicate on the next boot — the same at-least-once outcome replay already has"* |
| `inbox.py` — `_audit` unguarded by design | a reply that cannot be persisted is **not acked**, so Google **redelivers** it. At-least-once, chosen |
| `CLAUDE.md` — the durability bullet | replay preserves the attempt count precisely so at-least-once does not degenerate into a storm |

**D1 moves the dead-man path from at-most-once to at-least-once**, which is the
posture every neighbouring mechanism already took, for the reason every one of
them records. It is not a new trade being made here; it is an existing trade
being **applied to the one path that was left out of it**.

And the asymmetry is stark on this particular surface: a duplicate *"heartbeat
missed: daily-trading-run"* costs aitrader one redundant phone notification. A
dropped one costs it the entire feature, silently, for 24 hours.

### Rejected alternatives

| | Why not |
|---|---|
| **Roll the mark back in an `except`** | Does not cover doors 2, 3 or 4 — none of them raises. And it cannot roll back a `_save()` that already landed, so variant E's on-disk suppression survives it. Fixes the narrowest door only |
| **Two-phase mark (`alerting` → `alerted`)** | Real durability, and far more machinery than this store has anywhere else. The at-least-once trade above buys the same safety for one reordering |
| **Keep marking first, add a counter** | This is exactly what CG-74 shipped, and §1.1 is the record of it being mistaken for a fix. A counter reports the loss; it does not prevent it |

### Per-check, not per-batch — and the reason is cross-tenant

`scan_once` iterates `fired`, which can hold checks belonging to **different
apps**. If check #1's notify raises, checks #2..N — already marked alerted by
today's `due_alerts` — are never attempted.

So `scan_once` must **attempt every candidate**, collect successes and failures
separately, mark only the successes, and report the failures afterwards. A
routeless `job-hunter` check must not be able to suppress `aitrader`'s alert.
That is the same isolation instinct hard rules #4 and #6 apply to inbound, and
it costs one `try` inside the loop.

---

## 4. Decision D2 — door 2: refuse at registration, **and** count at runtime

The brief asked whether door 2 wants a counter, a re-raise, or a refusal at boot.
**It wants two of the three, and "boot" is the wrong moment for the refusal.**

### 4.1 ⚠ Why not "at boot"

Dead-man checks are **not** registered at boot. They arrive at runtime via
`POST /v1/heartbeat` (`service.py:340–349`) and persist across restarts. A
boot-time refusal would fail a process for a check registered days earlier, and
would say nothing about a check registered five minutes from now. **The
equivalent of "boot" for this object is registration.**

### 4.2 Chosen — (a) refuse at registration

`POST /v1/heartbeat` resolves the source's alert route **before** storing the
check, and returns **422** when it cannot. The message names the missing
`routes:` block, not any URL (hard rule #2).

This is CG-72/CG-74's posture — *a component that cannot do its job must not look
like one that can* — applied at the front door, to the party who can actually fix
it, at the moment the mistake is made. `aiteam-harness` and `job-hunter` (§2.2)
would be told immediately, instead of discovering it 24 hours into an outage.

⚠ **A registration-time check is a snapshot and cannot be the whole fix.** The
registry is reloadable and operator-edited. All four `RegistryError` conditions
in §2.2 can arise **after** a check is registered — a route removed, an identity
deleted, an allowlist narrowed. So:

### 4.3 Chosen — (b) count at runtime, as well

`_monitor_notify` keeps catching `HTTPException` — it must not kill the scan
loop — but it now **counts** the refusal and **tells `scan_once` the alert was
not accepted**, so D1 declines to mark the check. Two consequences, both wanted:

1. `/healthz` degrades on a real number rather than staying green.
2. The check stays unmarked, so it **re-fires on the next scan** and
   **self-heals the moment the route is restored**, instead of being suppressed
   for 24h from a fault that was fixed in two minutes.

### 4.4 ⚠ Rejected as the *sole* fix — (c) bare re-raise

Re-raising folds door 2 into `scan_failures` for one line of change, and it is
tempting. Rejected because it **conflates a permanent configuration error with a
transient disk fault** — the operator reading `consecutive_scan_failures: 3,
last_scan_error: 'HTTPException'` learns nothing about a missing `routes:`
block — and because, once D1 stops marking the check, a routeless check would
raise out of the loop **every 60 seconds forever**, printing to the console each
time. The counter in 4.3 says the true thing; the re-raise says a misleading one
loudly.

### 4.5 ⚠ Hard rule #2 / CG-12 — what the counter may and may not say

`/healthz` is **unauthenticated**. CG-12 considered and **rejected** metadata-only
records on exactly this ground, and its decision stands: the new counter is a
**bare integer**. No app id, no check id, no space, no timestamp.

The operator who needs to know *which* check reads the **authenticated**
`GET /v1/deliveries` — `_monitor_notify` already writes the identifying line
there (`service.py:300`), and that endpoint is behind per-app auth. So the
`/healthz` reason names the number and **points at the authenticated read-back**.
Rule #5 is satisfied without widening unauthenticated disclosure by one field.

---

## 5. Decision D3 — door 3: count the terminal delivery failure

**Chosen: `Dispatcher` gains a cumulative `delivery_failures` counter,
incremented in `_finish` when `status == "failed"`, published at `/healthz` and
degrading.**

`expired_at_boot` and `unroutable_at_boot` already exist for **boot-replay**
losses, and their `/healthz` reason (`service.py:805–811`) already says *"queue
replay dropped N ... they were accepted and are not coming back"*. A job that
exhausts the ladder in-process is **the same fact arriving by a different route**
— accepted, not delivered, not coming back — and it is the one variant with no
counter. The three belong to one family and this completes it.

⚠ **Deliberately NOT scoped to heartbeat jobs.** `Job.kind` distinguishes
`"notify"` from `"heartbeat"`, and it is tempting to count only the latter since
this row is about the dead-man switch. Rejected: a terminal `failed` on **any**
accepted notification is a silent loss of something the gateway returned **202
accepted** for, and CG-12's *"a guarantee working is not a fault"* test does not
apply — this is a guarantee **breaking**. One counter, all kinds, and the
authenticated delivery log carries the breakdown.

⚠ **This makes an existing `/healthz` string incomplete, which the plan must
correct.** The replay reason at `service.py:805–811` currently implies that
boot replay is the only way an accepted job is dropped. After D3 it is not.

---

## 6. Decision D4 — door 4: the dead-man path stops using the deduper

**Chosen: `scan_once` passes no `dedupe_key`.** The dead-man alert bypasses
`Deduper` entirely.

The reasoning is in §2.4 and is unusually clean for a removal: since
`DEFAULT_REPEAT_S` (86400s) is strictly greater than `DEFAULT_DEDUPE_WINDOW_S`
(3600s), and `alert_due` already guarantees at most one alert per check per
repeat window, **the deduper cannot ever suppress an actual duplicate on this
path.** Every suppression it performs here is a false positive. It is not a
control with a trade-off; it is a control with no upside case.

`alert_due()` **is** the dead-man's dedupe. Stacking a second, shorter,
independently-clocked window on top of it produced door 4 and can produce nothing
else.

### ⚠ Two guards this decision needs, because "the windows are ordered today"

1. **The relationship must be asserted, not assumed.** `repeat_s` is a
   constructor argument on both `HeartbeatMonitor` and `Deduper`; a deployment
   could set them the other way round. The plan pins the reasoning with a test
   that fails if `DEFAULT_REPEAT_S <= DEFAULT_DEDUPE_WINDOW_S`, so the next
   person to change a constant is told *why* this key was removed.
2. **`_monitor_notify` still treats a `"deduped"` return as not-accepted**
   (§3). D4 removes the *cause*; the D1 check is the *backstop*, and belt-and-
   braces is correct on a contract surface where the failure is silent.

---

## 6a. Decision D4b — door 5: a check whose source left the registry is COUNTED, not hidden

**Chosen: `/healthz` publishes `heartbeats.checks_orphaned` — checks in the store
whose `source` is not a registered app — and degrades on it.**

`hb_all` (`service.py:443`) filters the census through `registry.apps`, so an
orphaned check drops out of `checks` **and** out of `missed`. §2.5 measured
`checks: 1 -> 0` on a rename while the store still held and still scanned it.

⚠ **The fix is a second number, not an unfiltered `hb_all`.** Widening `hb_all`
would silently change what `checks` and `missed` mean — two fields three docs
already describe — to fix a third thing. `checks` keeps meaning *checks this
registry knows about*; `checks_orphaned` is the count it excludes.

**A bare integer, for CG-12's reason** (§4.5): naming the orphaned app id on an
unauthenticated endpoint would disclose a former tenant's identity. The reason
string points at the authenticated `GET /v1/deliveries`, where the failing
alerts already appear under the dead source id.

⚠ **This row COUNTS the condition; it does not resolve it.** Whether an orphaned
check should be deleted, retained, or refuse to load is a data-lifecycle
question with a privacy dimension (that check's `source` is a former tenant's
id, persisted under the state dir) and it is **not decided here**. Counting it
is what hard rule #5 requires today; deciding its fate is its own row.

---

## 6b. Decision D4c — door 6: the counters are per-ALERT-ATTEMPT, not per-CHECK-STATE

**Chosen: nothing new. This decision records that D2's counter shape already
closes door 6, and WHY the obvious alternative does not.**

Door 6 — the 24h repeat alert that moves **zero** fields — exists because
`heartbeats.missed` is derived from `check.status`, which is already `"missed"`
by the time a repeat fires (§2.6). The tempting fix is to make `missed` smarter.

⚠ **Rejected, and §2.8 is the measurement that rejects it.** `missed` moves
**identically on a successful alert and on a dropped one**. It is a statement
about check *state*, not about whether anyone was told, and no amount of
refinement makes a state gauge answer a delivery question.

`alerts_undeliverable` (D2) is incremented **once per alert attempt that was not
accepted** — inside `scan_once`'s per-check loop, with no reference to
`check.status`. A repeat alert is an attempt like any other, so door 6 moves it
exactly as door 2 does. Door 6 needed no new mechanism; it needed the counter to
be shaped per-attempt rather than per-state, and that shape is now load-bearing
rather than incidental.

⚠ **Do not "simplify" `alerts_undeliverable` into a derivation from check state.**
That refactor looks like tidying and silently reopens door 6. The plan pins it
with a test that fires a **repeat** alert into a broken route and asserts the
counter moves while `missed` does not.

---

## 7. ⚠ Decision D5 — what happens to CG-74's `scan_failures`

**The brief asked for this loudly, and it deserves the volume.** CG-74 shipped
`scan_failures` as **cumulative and degrading**, against its sibling
`Dispatcher.pass_failures` which is cumulative and **inert**. The user made that
call as decision D3 of the previous spec. CG-74's Builder then **validated** it
on a real server: at the moment of a real drop, `consecutive_scan_failures` read
**0** — one scan raised, the next found nothing due and cleared it — so **the
cumulative counter was the only thing still holding `degraded`.** The rejected
body-only alternative would have gone green on that exact run.

**Nothing in this spec may make that signal unreliable.** Two things must be
said, and only the first is a change.

### 7.1 The counter's stated JUSTIFICATION expires. The counter does not.

`HeartbeatMonitor.__init__` (`heartbeat.py:189–200`) and the `/healthz` reason
string (`service.py:960–968`) both justify the cumulative degrade with:

> a scan that raises after marking a check MISSED drops that alert for the repeat
> window (24h) and no later scan re-sends it

**D1 falsifies that.** After the reordering, a scan that raises has **not**
marked the check, so the next scan **does** re-fire it. A failed scan becomes
*recoverable* — which is precisely the property that made `pass_failures` inert.
The strong justification is gone.

### 7.2 Chosen: `scan_failures` **keeps** degrading, on the weaker reason, and the change is stated

**Recommendation: do not flip it to inert in this row.** A raising scan loop
still means the dead-man monitor is not completing scans, on aitrader's contract
surface, and the conservative posture there is to keep degrading. What changes is
the **wording**, which must stop asserting a loss that D1 has prevented.

This is exactly the discipline `CLAUDE.md` records for `__cg_action__` —

> *"It stays anyway, and the reason is now the weaker one — say so rather than
> keep quoting the strong one."*

— and the plan applies it verbatim: the reason string and the `__init__`
docstring are rewritten to say *"scans are raising and at least one alert may be
DELAYED or DUPLICATED"*, not *"lost"*.

⚠ **Flipping `scan_failures` to inert is a separate user decision and is
deliberately NOT taken here.** It would be defensible after D1, and if the user
wants it, it belongs in its own row with its own measurement — not folded into
this one. Folding it in is the scope creep this queue keeps correcting.

### 7.3 ⚠ What D1 changes about CG-74's own UAT scenario — stated so it is not a surprise

CG-74's demonstration was: `chmod a-w` on the state dir, a check goes missed,
`main` answers `ok` and the branch answers `degraded`, **zero notifications sent
on both sides.**

**Re-run after CG-76, that scenario produces a different and better result.**
`due_alerts` no longer writes during selection, so variant D **ceases to exist**;
the save moves to `mark_alerted`, which runs *after* the notify. The alert is
**actually delivered**, `_save()` then fails, `scan_failures` reaches 1, and the
residual risk is a **duplicate at next boot** rather than a loss.

The plan must therefore expect the CG-74 UAT harness to change what it proves,
and must **not** be read as CG-76 having broken it. The counter still moves; the
outcome it accompanies is no longer a lost alert. Any test asserting *"zero
notifications sent"* under that fault is asserting the **old** behaviour and is
listed for update in the plan.

### 7.4 The one test that is SUPPOSED to go red

`tests/test_notify_heartbeat.py:687` —
`test_a_routeless_alert_is_dropped_without_raising_or_counting` — carries a
docstring saying so in as many words:

> **CG-76 is expected to change what this asserts.** When a dropped alert becomes
> visible on `/healthz`, this test is the one that should go red — the
> `scan_failures == 0` and `status == "ok"` assertions below are a record of a
> hole, not a contract. Do not "fix" it by loosening them.

The plan rewrites it into the positive assertion and keeps the history in its
docstring.

---

## 8. Rule #5 — which counters degrade, and which do not

Every new counter is a deliberate degrade input or deliberately not one, with
reasoning, per the brief and per `CLAUDE.md`'s record of why `suppressed_opt_out`
and `files_deleted` must **not** degrade.

| Counter | Cumulative? | Degrades? | Why |
|---|---|---|---|
| `heartbeats.alerts_undeliverable` (D2) | yes | **YES** | Names a dead-man alert that could not be accepted. This is a guarantee **breaking** on aitrader's contract surface — the exact opposite of `suppressed_opt_out`, which is a guarantee **working** and therefore correctly inert. Cumulative because a refused alert is never re-sent by a later scan once the check is finally marked |
| `heartbeats.checks_undeliverable` (D2, gauge) | no — gauge | **YES** | How many registered checks are, right now, in a state where their alert could not be routed. Returns to `0` when the registry is fixed, so it is the **live** signal beside the cumulative history — the split `RetentionSweeper` established and CG-74 measured the need for |
| `heartbeats.checks_orphaned` (D4b, gauge) | no — gauge | **YES** | A registered check whose source is not a registered app. Today it vanishes from `checks` **and** `missed`, so `/healthz` under-reports coverage while still scanning and still dropping (§2.5). A gauge because it is a live registry condition an operator can fix |
| `delivery.delivery_failures` (D3) | yes | **YES** | A job the gateway returned **202 accepted** for, and then did not deliver. Same family as `expired_at_boot` / `unroutable_at_boot`, which already degrade for the identical reason |
| `heartbeats.scan_failures` (existing) | yes | **YES — unchanged** | §7.2. Kept, on a weaker justification, with corrected wording |
| `heartbeats.missed` (existing) | gauge | **NO — unchanged** | §2.8. It moves identically on a delivered alert and a dropped one, and not at all on a repeat. Inert today and **must stay inert**: promoting it would alarm on the dead-man switch working correctly, which is the mistake `suppressed_opt_out` exists as precedent against |

⚠ **`alerts_deduped` is deliberately NOT added.** D4 removes the cause; a counter
for a path that no longer exists is a field an operator has to learn in order to
discover it is always zero. The §6 constant-ordering test is the guard instead.

⚠ **Four new degrade inputs on an endpoint consumers alarm on is the largest
single addition this queue has made, and it is flagged for the user rather than
slipped in.** CG-72's own comment calls a new degrade input *"a decision, not a
wording fix."* The justification for all four is the same and it is narrow: each
names a **dead-man alert that was not delivered**, on the one contract surface
where silence is the failure mode. None of them fires on a guarantee working —
that test is what keeps `suppressed_opt_out`, `files_deleted` and `missed` inert.
If the user wants fewer, **`checks_orphaned` is the one to demote to body-only**:
it is the least likely to fire and the only one that does not, on its own, mean
an alert was already lost.

---

## 9. Scope — what this row does NOT do

- **It does not touch `adapters/`.** No ⚠ verification-ledger flag is cleared,
  added or reworded. Verified with
  `git diff main -- src/ | grep -c "LIVE-UNVERIFIED\|SHAPE-VERIFIED"` → must
  print `0`.
- **It does not touch `docs/architecture/`.**
- **It does not plan CG-69** (§1.1). Today's instance is added to that row's
  evidence table and nothing else.
- **It does not flip `scan_failures` to inert** (§7.2).
- **It does not change `DEFAULT_REPEAT_S`, `DEFAULT_DEDUPE_WINDOW_S` or
  `BACKOFF_S`.** D4 removes a *use* of the deduper on one path; it does not
  retune anything.
- **It does not make `HeartbeatStore._save` guarded.** D1 moves the write to a
  point where raising is honest — after the alert is safely queued — which is
  the `inbox.py::_audit` posture, not the `DeliveryLog.record` one. Wrapping it
  as well would re-create door 1 in a quieter form.
- **It does not add modal/interaction surface**, touch the registry schema, or
  change any consumer's inbound posture (hard rule #6 untouched).
- **It does not fix clock skew** (§2.9 A) — filed as **CG-77**.
- **It does not reopen `thread_started` gating** (§2.9 B) — CG-72's recorded
  trade-off, residue noted there.
- **It does not decide what happens to an orphaned check's persisted data**
  (§6a). It counts the condition; the lifecycle question is its own row.
- **It does not promote `heartbeats.missed` to a degrade input** (§2.8, §8).

---

## 10. Rows

| Row | This spec |
|---|---|
| **CG-76** | all of it. Doors 1–6, the two amplifiers, decisions D1–D5 |
| **CG-77** | ⚠ **NEW — filed by this spec.** Clock skew silently disarms the dead-man switch (§2.9 A). Measured, not folded in |
| **CG-69** | §1.1's fifth instance **and** §0's count-moved table are added as evidence only. **No plan** |
| **CG-55** | unchanged dependency — CG-76 remains a pre-deploy blocker on its list |
| **CG-74** | shipped. §7 records what this row changes about its counter's justification, its UAT scenario, and one of its tests |
| **CG-72** | shipped. §2.9 B is recorded as residue on its `thread_started` gate; **not reopened** |
| **CG-73** | untouched. `heartbeat.py`'s raw `{exc}` print sites are **not** in this row's scope |
