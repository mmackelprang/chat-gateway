# Delivery write-path robustness — design

**Date:** 2026-08-03 · **Planner** · branch `docs/cg-74-cg-75-delivery-robustness`
**Baseline:** `main` at `696a8cd`, suite **324 passing** — re-measured here with
`python3 -m pytest -q` (`324 passed in 32.66s`), not copied from a queue row.

**Rows this spec produces:** **CG-75** (the unguarded write that becomes a send
storm) and **CG-74** (the failure counters the two threads never got).
**Row this spec files:** **CG-76** — a *third* consequence of the same root
cause, on the dead-man switch, which **neither** CG-74 nor CG-75 fixes.
**Rows this spec re-scopes:** **CG-73** (narrowed by two sites) and **CG-55**
(gains CG-75 as a dependency, per the user's decision of 2026-08-02).

**No ⚠ verification-ledger flag is cleared, added or reworded by anything in
this document, and none may be by either PR it produces.** Nothing here touches
a Google seam: every change is to what the gateway writes to its own disk and
what it publishes at `/healthz`. `adapters/` and `docs/architecture/` are
untouched by the planning PR and off-limits to both implementation PRs.

---

## 1. Where this came from

CG-72's Builder filed two rows out of its own pre-merge review (M1). They were
filed separately, and they are separately correct — but they are **one root
cause seen from two angles**:

> `DeliveryLog.record` performs a raw `mkdir` / `open` / `write` with no guard,
> on the delivery hot path.

CG-75 is that fact's **control-flow** consequence: the exception escapes
`_finish`, escapes `process_due`, and leaves an already-delivered job in `_jobs`
and still due — so the next pass sends it again.

CG-74 is its **observability** consequence: neither `Dispatcher` nor
`HeartbeatMonitor` counts a failed pass, so `/healthz` cannot distinguish a loop
that is wedged from one that is raising — and two unauthenticated `/healthz`
strings currently say so **in words**, naming this exact mechanism as the
example.

Planning them in one pass is what stops two designs being written over the same
function.

---

## 2. What was measured

Every number below was produced on this machine against `696a8cd`. The harness
is a scratchpad script (`measure.py`, `measure2.py`); each experiment is
described precisely enough to re-run, and each is turned into a repo test by the
plan.

The technique in all five: a `DeliveryLog` subclass whose `record()` raises
`OSError(28, "No space left on device")`, an injected clock, and a counting
fake adapter. No network, no real disk.

### 2.1 The brief's line numbers are correct

| Claim | Verified |
|---|---|
| `_finish` at `delivery.py:294` | ✅ |
| `self._log.record(...)` at `:295` | ✅ |
| `_journal_write(... close ...)` at `:302` | ✅ |
| job leaves `_jobs` at `:304–306` | ✅ |
| `DeliveryLog.record` at `:85` | ✅ |
| raw `self._audit_dir.mkdir(...)` at `:95`, no guard | ✅ |
| the mid-flight comment at `:297–301` | ✅ — and it is load-bearing; see §6 |

`_finish` is called from `process_due` at line 256 (the `except` branch, giving
up) and 266 (the `else` branch, delivered). **The `else` branch of a `try` is
not covered by its own `except`** — so a raise from `_finish` on the delivered
path propagates straight out of `process_due`. Confirmed by experiment.

### 2.2 The delivered path: 60 sends in 60 seconds, from one message

```
A. DELIVERED path: _log.record raises AFTER a successful send
  passes run           : 60
  passes that RAISED   : 60
  SENDS TO GOOGLE      : 60
  jobs still queued    : 1
  last_pass_at         : None
```

One enqueued notification, one successful send, then a full disk. Sixty passes,
**sixty sends to Google**, and the job never leaves `_jobs`. This is CG-75's
claim, reproduced exactly, and the row's severity call (**HIGH on impact**) is
right.

`last_pass_at` is `None` here only because this dispatcher had never completed a
pass before the disk filled. On a gateway that has been running, it holds a real
frozen timestamp and the **staleness** branch fires instead — but only after the
600s `DISPATCH_STALE_AFTER_SECONDS` budget, i.e. **after roughly 600 duplicate
sends**. Liveness catches this late and after the damage. That is the honest
reading of what CG-72 shipped: it is not nothing, and it is not a fix.

### 2.3 The retrying path: CG-74's claim is right — for 72 minutes

CG-74's row says the staleness branch *"never fires at all"* on the retry path.
Measured over 400 simulated seconds:

```
B. RETRYING path: send fails, _log.record('retrying') raises
  passes run           : 400
  passes that RAISED   : 3
  SENDS TO GOOGLE      : 3
  WORST staleness seen : 1.0s  (budget is 600s)
  -> staleness branch fires? False
```

**Confirmed.** The raise happens at line 263, *after* line 258 has already
pushed `next_attempt_at` out by the backoff, so the job is 30s / 120s / 600s /
3600s from being due again. Every pass in between is empty, and every empty pass
stamps `last_pass_at` (deliberately — `process_due`'s own comment at 267–272).
Worst observed staleness: **1.0 second**, against a 600s budget. `/healthz`
reports `ok` throughout.

**But the row overstates it, and the correction matters.** Run past the ladder:

```
C. RETRYING path run to exhaustion
  SENDS TO GOOGLE      : 1654 over 6000 simulated seconds
  send timestamps (s)  : [0, 30, 150, 750, 4350, 4351, 4352, 4353, 4354, ...]
  WORST staleness      : 1650.0s (budget 600s) -> fires? True
```

`BACKOFF_S = (0, 30, 120, 600, 3600)` plays out to **t=4350s** (72.5 minutes).
At that attempt `job.attempts` reaches `len(self._backoff)`, so `process_due`
takes the give-up branch and calls `_finish(job, "failed", ...)` — which raises
before removing the job, exactly as the delivered path does. **The retry path
degenerates into the same 1/second storm**, and only then does staleness fire.

So the precise statement, which neither row makes:

> On the retry path, the staleness branch does not fire for **the whole 72.5
> minutes of the backoff ladder**. It fires afterwards — because by then the
> retry path *has become* the delivered path's storm.

That is a **narrowing** of CG-74's claim, not a refutation: the window in which
`/healthz` is blind is bounded and long, and the thing that ends the blindness
is the failure getting worse.

### 2.4 The sibling sweep — one more defect, and one deliberate non-defect

`grep -rn "mkdir\|open(" src/chat_gateway/` returns four filesystem write sites
outside `journal.py` (which routes everything through its own guarded helpers):

| Site | Guarded? | Verdict |
|---|---|---|
| `delivery.py:95` — `DeliveryLog.record`'s audit write | ❌ | **CG-75.** The defect. |
| `inbox.py:297` — `Inbox._quarantine` | ✅ `try/except`, counts `quarantine_write_errors` | fine |
| `inbox.py:317` — `Inbox._audit` | ❌ | **deliberate, and correct** — see below |
| `heartbeat.py:121` — `HeartbeatStore._save` | ❌ | **CG-76.** A new finding. |

**`inbox.py::_audit` is unguarded on purpose and must stay that way.** It is the
first statement of `Inbox.put`, whose own comment (lines 81–84) states the
posture: a reply the gateway cannot persist must **not** be acked, so the raise
travels back up the Pub/Sub dispatch path, the message is left unacked, and
Google redelivers it. Raising is the honest answer there because there is a
retry channel. Do not "fix" it.

**`heartbeat.py::_save` is a genuinely new defect, and it is worse in kind than
CG-75.** `HeartbeatStore.due_alerts` mutates the check (`status = "missed"`,
`last_alerted = now`) **under the lock, before** calling `_save()`, and
`HeartbeatMonitor.scan_once` only calls `_notify` on what `due_alerts` returns.
So:

```
D. HeartbeatStore._save() raising inside due_alerts
  scan_once raised     : OSError (caught by _run's handler)
  notifications sent   : 0
  check.status in mem  : missed
  check.last_alerted   : '2026-08-03T12:03:20+00:00'
  --- disk recovers, next scan ---
  alerts fired now     : 0
  notifications total  : 0
  last_scan_at         : 2026-08-03 15:03:30+00:00  <- stamps again
  ==> MISSED ALERT SILENTLY DROPPED: True
```

The check is marked alerted, the alert is never sent, `alert_due` then returns
`False` for the whole `DEFAULT_REPEAT_S` window (**24 hours**), and the next
idle scan re-stamps `last_scan_at` so `/healthz` goes green. **A dead-man
switch that silently stops being a dead-man switch** — the feature aitrader's
contract exists for, failing in exactly the shape hard rule #5 was written
after.

The durable variant is worse:

```
E. _save() SUCCEEDS but the notify's enqueue->_log.record raises
  jobs enqueued        : 0
  last_alerted PERSISTED to disk: True
  after RESTART, alerts due: 0
```

`_save()` lands, then `_notify` → `emit_notification` → `dispatch.enqueue` →
`self._log.record` raises. `_monitor_notify` catches `HTTPException` only, so
the `OSError` escapes. The suppression is now **on disk** and survives a
restart.

**And CG-75's fix does not rescue it** — measured separately (`measure2.py`),
with the audit write guarded and a journal whose writes fail:

```
scan_once raised     : OSError from enqueue's journal.open (post-CG-75)
jobs enqueued        : 0
last_alerted on disk : '2026-08-03T12:03:20+00:00'
after RESTART, due   : 0
next scan fired      : 0
last_scan_at now     : ... <- stamps, /healthz green
==> CG-75's fix does NOT rescue the dead-man alert: True
```

`Dispatcher.enqueue`'s journal `open` is unguarded **by design** (its comment,
lines 219–224: a job we cannot persist must be refused). So the drop survives
CG-75 through a different door. This is why it is **CG-76 and not a fold-in**:
fixing it means reordering `due_alerts` / `scan_once` so the persist and the
notify cannot succeed independently, which is a different design question from
`_finish`'s, on a different class, with its own compensating-action decision.

### 2.5 A method note on the flag counts

CG-72's banner records `docs/architecture/ 5=5`. Measured today at both
`3526d50` and `696a8cd`: **6** occurrences, on **5** lines —
`docs/architecture/decisions/2026-07-29-tier2-interaction-model.md:267` carries
both `LIVE-UNVERIFIED` and `SHAPE-VERIFIED` on one line. Nothing moved and no
claim in that banner is false; the *number* is method-dependent and the banner
does not say which method. Baseline for this arc, with the command, so the next
reader is not left guessing:

```
$ for d in CLAUDE.md src docs/architecture docs/consumers tests; do
    printf "%-22s %s\n" "$d" "$(grep -rEo 'LIVE-UNVERIFIED|SHAPE-VERIFIED' $d | wc -l)"
  done
CLAUDE.md              8
src                    4
docs/architecture      6
docs/consumers         2
tests                  3
```

---

## 3. Decision D1 — the failure posture for the unguarded write

Three options were considered for what `DeliveryLog.record` should do when its
file write fails.

**(a) Guard the file write inside `record`, count it, keep going.** ✅ **Chosen.**

**(b) Keep raising, but remove the job from `_jobs` first.** ❌ Rejected. It
stops the storm, but only by inverting the deliberate ordering at `_finish`
lines 297–301: the log record is written *before* the `close` precisely so a
process killed in that window replays rather than loses. Moving the removal
above the record changes what `drained` is computed from and re-opens CG-65's
compaction race. Paying a data-loss risk to fix an availability bug is the wrong
direction.

**(c) Treat an audit-write failure as a retryable condition — hold the job and
back it off without re-sending.** ❌ Rejected. It requires splitting "send" from
"finalize" across passes, which is a state machine this class does not have, for
a condition in which the disk is full and everything else is failing too.

### Why (a) is not merely the easy one

The guard goes **inside `DeliveryLog.record`, around the file block only** —
not around the call sites. That placement is what makes the swallow cheap, and
it is a property of the existing code rather than a hope:

`record` appends to the in-memory ring buffer at lines 92–93, **before** it
touches the disk at 94–106. Guard only the second half and:

- `record` always returns an `entry_id`; `_finish` and `enqueue` can no longer
  raise from this site at all.
- `query()` — and therefore `GET /v1/deliveries` — still answers *"did this
  alert reach Chat?"* correctly **for the life of the process**. The loss is the
  on-disk copy, not the answer.
- `enqueue`'s refuse-the-work posture is untouched, because that posture belongs
  to the **journal** `open` at line 226, not to the audit trail. On a genuinely
  full disk `enqueue` still 500s and the consumer's own fallback log still takes
  over — exactly as the aitrader contract requires. **The guard does not hide a
  full disk. It stops work that has already been accepted from storming.**

### What it costs, stated rather than argued away

1. **The on-disk delivery audit line for that entry is gone forever.** A later
   pass cannot recreate it. After a restart there is no record on disk that the
   message was delivered — and `journal.py`'s docstring is explicit that the
   per-app audit files cannot answer this question, because they record what
   ARRIVED, never what LEFT. This is a real hole in the forensic record, and the
   counter in §5 is the only thing that makes it visible.
2. **The job is now removed from `_jobs` even though nothing was persisted.** On
   a full disk the `close` at line 302 also fails (already guarded), so the
   journal entry stays open and the job is **replayed at the next boot and may
   deliver twice.**

Cost 2 is not a new risk being introduced — it is the *identical* trade
`_journal_write`'s own docstring already blessed, in these words:

> *"Counting it instead costs at most one duplicate on the next boot — the same
> at-least-once outcome replay already has — and the counter is what keeps the
> degradation visible."*

And `service.py`'s `_journal_write_errors` helper says the same thing from the
other end: *"raising there would turn a full disk into a re-send storm."* This
row is that sentence applied to the one write on the path that never got it.
**The fix makes `record` behave like every other write around it.** One
duplicate at next boot, versus one send per second indefinitely.

---

## 4. Decision D2 — one PR or two

**Two PRs. CG-75 first, then CG-74. They must not run concurrently.**

### Why two

1. **CG-75 is a pre-deploy blocker (user decision, 2026-08-02) and CG-74 is
   not.** Coupling a blocker to a non-blocker means the blocker inherits the
   other's review risk.
2. **CG-74 carries a decision; CG-75 carries a bug fix.** CG-72's own code
   comment (`service.py:779–782`) says it in as many words: adding the counters
   *"is a new degrade input on an endpoint consumers alarm on, which is a
   decision, not a wording fix."* A pushback on the counter design must not
   block the storm fix.
3. **The repo has precedent for exactly this split** — CG-67 was split out of
   CG-66 and promoted because it was the live-path half; CG-68 was split out of
   CG-65 for the same reason.

### Why CG-75 must go first, not second

CG-74's whole deliverable is a set of `/healthz` reason strings describing what
a failing pass does. CG-75 **changes what a failing pass does**. Writing the
counter strings against a defect that is about to be removed would mean writing
them twice, and the second rewrite would be invisible in CG-74's own diff.

### The cost of splitting, and why it is accepted

**Both `/healthz` staleness strings get edited twice.** CG-75 edits them
minimally; CG-74 rewrites them. That is a real cost and it is paid on purpose,
because rule #5 does not permit leaving a false statement standing on an
unauthenticated endpoint for the duration of a second PR:

- **The delivery string** (`service.py:804–815`) ends *"a full disk, which makes
  the delivery log's own write raise, is the other one."* After CG-75 that is
  **false** — the delivery log's write no longer raises. CG-75 must delete that
  example in its own PR.
- **The heartbeat string** (`service.py:834–845`) ends *"A scan that fires a
  check enqueues through the delivery log, so a full disk raises there while an
  idle scan still stamps."* After CG-75 that stays **true but by a different
  mechanism** — the raise now comes from `enqueue`'s journal `open` (measured,
  §2.4E), not from the delivery log. A true sentence naming the wrong mechanism
  sends an operator to the wrong file, so CG-75 must correct the mechanism.

This is a *sequential* correction of one fact, not the two-homes-for-a-moving-
fact trap CLAUDE.md warns about: after each PR there is exactly one statement
and it is true.

Note also that the long comment block at `service.py:764–775`, which explains
*why* those strings are hedged, describes CG-75's defect in the present tense.
CG-75 must update it or it becomes stale in a PR that did not touch it.

---

## 5. Decision D3 — which counters degrade, and which do not (rule #5)

Hard rule #5 and CLAUDE.md's recorded reasoning (`suppressed_opt_out` and
`files_deleted` must **not** degrade — a guarantee working is not a fault) mean
every new counter needs an explicit verdict. Three go in.

| Counter | Owner | Cumulative / consecutive | Degrades? |
|---|---|---|---|
| `audit_write_errors` | `DeliveryLog` | cumulative | ✅ **yes** |
| `pass_failures` / `consecutive_pass_failures` | `Dispatcher` | both | cumulative ❌ / consecutive ✅ (≥3) |
| `scan_failures` / `consecutive_scan_failures` | `HeartbeatMonitor` | both | **cumulative ✅** / consecutive ✅ (≥3) |

### `audit_write_errors` — cumulative and degrading

Shaped on `journal_write_errors` (`service.py:639`, degrades at ≥1) and
`RetentionSweeper.errors` (`delete_errors`, likewise), **not** on
`poll_failures` / `sweep_failures`. The distinguishing test is
`retention.py`'s own recorded one: *"there is nothing for a later pass to
'recover' from."* A delivery-log line that never reached disk is never written
by a later pass. A counter that could return to zero would be a lie about a
permanent loss.

### `pass_failures` — cumulative, body only; `consecutive_pass_failures` degrades at ≥3

The consecutive/cumulative split, and the rule that **only the consecutive one
may drive `status`**, are copied from `RetentionSweeper`'s own docstring
(retention.py:245–256), where the pre-merge review of 2026-08-02 measured the
alternative: a cumulative degrading counter pinned `degraded` for the life of
the process after one transient failure that had already recovered.

Threshold **3**, matching `POLL_FAILURE_THRESHOLD`, not the sweeper's ≥1. The
reason is the loop interval, and it is the same reason the subscriber has a
threshold and the sweeper does not: the sweeper runs every six hours, so one
failure is already a real signal; the dispatcher runs every **1.0s**
(`PASS_INTERVAL_S`), where a single transient blip should not flip an alarm on
an endpoint consumers page on. Three passes is three seconds — the threshold
costs nothing in detection time and buys the whole of the anti-flap.

### `scan_failures` — cumulative **and degrading**, and the asymmetry is deliberate

This is the one place the two blocks do **not** mirror each other, and it must
not be smoothed for symmetry's sake. A failed dispatcher pass is recoverable:
the due job is still in `_jobs` and the next pass retries it. **A failed
heartbeat scan is not** — §2.4 measures it: the check has already been marked
alerted, so the missed-alert is dropped for the 24-hour repeat window, durably
in variant E. That is `retention.errors`'s test again — nothing for a later
scan to recover — so it earns the same posture.

Two supporting observations rather than one argument:

- **This adds almost no new pinning in practice.** Both realistic causes of a
  scan failure are disk conditions that already set `journal_write_errors`,
  which already degrades cumulatively. What the new reason line adds is that it
  **names the dead-man switch**, which is the actionable half.
- **The counter is not the fix.** CG-76 is. ⚠ **The sentence that followed this
  one was FALSE. See the correction immediately below — do not read the struck
  text as this spec's position.**

  > ~~Until CG-76 lands, this counter is the only thing standing between a
  > silently-dropped aitrader alert and a green `/healthz`.~~

#### ⚠ CORRECTION, 2026-08-03 — that absolute was false, and it shipped

**What it said** is struck above, verbatim rather than deleted: *"this counter is
the only thing standing between a silently-dropped aitrader alert and a green
`/healthz`."*

**Why it is wrong.** `scan_failures` is the only `/healthz` signal for a scan
that **RAISES**. It is not a signal for *"a dropped dead-man alert"*, and the gap
is not marginal — **three separate doors drop the alert without raising
anything**, leaving `scan_failures` at `0` and `/healthz` at `ok`:

| Door | Where | Raises? |
|---|---|---|
| a notify **refused for want of a route** — `_monitor_notify` catches `HTTPException` and only logs it | `service.py:294–300` | no |
| the **retry ladder exhausts** — `_finish(job, "failed")` writes a log line and no counter moves | `delivery.py:351` | no |
| the alert is **deduped** against a previous outage's alert, and `_monitor_notify` discards the return value | `service.py:285–289`, `heartbeat.py:231` | no |

**How it was found**, recorded because the *how* is the reusable part. The first
door was measured by **CG-74's Builder during that row's UAT**, and then found
**independently** by that PR's pre-merge reviewer, reading `_monitor_notify`
rather than running anything — logged as CG-74's finding **M2**. Neither found it
by reviewing a diff: **the diff never contained the sentence it broke.** The
Builder narrowed the claim where it lived in `heartbeat.py`, pinned it with
`test_a_routeless_alert_is_dropped_without_raising_or_counting`, and deliberately
did **not** edit this Planner artifact — correct on lanes. The remaining two
doors were found by CG-76's Planner sweeping the path on purpose, and are
measured in
[`2026-08-03-dead-man-alert-loss-design.md`](2026-08-03-dead-man-alert-loss-design.md)
§2.3 and §2.4.

**What is true instead:**

> `scan_failures` is the only `/healthz` signal for a scan that **raises**. A
> scan can drop a dead-man alert without raising, and until CG-76 lands there is
> **no** `/healthz` signal for those three paths at all.

**What does NOT change.** The decision this section records — `scan_failures`
cumulative **and** degrading — is unaffected, and CG-74's Builder validated it on
a real server: at the moment of a real drop `consecutive_scan_failures` read `0`,
so the cumulative counter was the only thing holding `degraded`. The rejected
body-only alternative would have gone green on that run. **The counter was right;
the sentence claiming it was sufficient was wrong.**

⚠ Corrected in place rather than rewritten, per this repo's standing discipline
for its own stale claims (`CLAUDE.md` passim). A silently-edited absolute teaches
a reader that this repo's absolutes are safe to trust — which is the belief that
produced this one. ⚠ This is the **fifth** merged claim to go false this week and
be caught only because somebody independently went looking; it is logged as
evidence on **CG-69**, the published-promise inventory, which still has no plan.

⚠ **This is the one item in this spec the user may want to overrule at
checkpoint.** The conservative alternative is body-only until CG-76 lands. It is
recorded as the alternative rather than hidden: choosing it means accepting that
a dropped dead-man alert produces no `/healthz` signal at all.

### `last_pass_error` / `last_scan_error` and hard rule #2

Both are rendered with `describe_exception` (`errors.py:63`), following
`RetentionSweeper.last_sweep_error` — **not** `SubscriberLoop`'s hand-rolled
format, which CLAUDE.md says must not be unified onto the helper and which is
therefore precedent for nothing new.

`OSError` is not a `GatewayAuthoredError`, so these fields will read exactly
`"OSError"` — no `errno`, no path. **That is deliberate and it is lossy**, and
naming the loss is the point: the useful detail (`ENOSPC` vs `EACCES`) is gone
from an operator's view. Widening `errors.py`'s allowlist to mark `OSError`
would recover it and would also enlist its raise sites in
`tests/test_error_surfaces.py` — but CLAUDE.md records that the allowlist has
never been widened without a stated reason, and `retention.py`'s
`RetentionConfigError` docstring sets the precedent for how to handle the
temptation: *"say so as its own decision; do not fold it in here."* **Not folded
in.** `OSError` embeds absolute paths in its `str()` — `retention.py:444–447`
records measuring exactly that — so marking it is a hard-rule-#2 question, not a
convenience.

---

## 6. Interaction with CG-65's compaction and CG-54's replay

Asked explicitly, and the answer is checkable rather than argued: **the fix does
not move the job's removal from `_jobs`, so nothing in either mechanism
changes.**

The entire CG-75 change is inside `DeliveryLog.record`. `_finish`'s sequence —
record → `close` → remove from `_jobs` → compute `drained` → compact — is
**byte-identical** after the fix. Therefore:

- `drained` still means *"the live set is empty as observed under `self._lock`"*.
  No re-derivation is needed.
- CG-65's `compact()`-recomputes-its-survivors race fix is untouched, as is the
  `closed` gate that stops a failed `close` from truncating away the `open`
  record it left standing.
- CG-54's open-minus-close replay is untouched, including the preserved attempt
  count.
- The mid-flight window comment at lines 297–301 is untouched and **must not be
  edited** — the log record still precedes the `close`, for the reason it always
  did.

The one second-order effect, already stated as cost 2 in §3: post-fix, a job
whose audit write failed *does* reach the `close`, which on a full disk also
fails and is counted — so the journal entry stays open and replays. Pre-fix it
also stayed open, because `_finish` raised before reaching the `close`. **Replay
behaviour on a full disk is unchanged.** What changed is that the job also
leaves memory instead of storming.

---

## 7. Scope — what these two rows do NOT do

- **They do not fix the dead-man drop.** That is CG-76, filed by this spec, with
  the measurement in §2.4. CG-74 makes it *visible*; nothing here makes it not
  happen.
- **They do not clear, add or reword any ⚠ flag.** No adapter changes what it
  sends, receives, retries or reports.
- **They do not touch `adapters/` or `docs/architecture/`.**
- **They do not widen `errors.py`'s allowlist** (§5).
- **They do not fix `inbox.py::_audit`** — §2.4 explains why it must stay
  unguarded.
- **They partially overlap CG-73 and narrow it rather than colliding with it.**
  CG-73 lists five raw-`{exc}` sites. CG-74 rewrites `Dispatcher._run`'s and
  `HeartbeatMonitor._run`'s print statements to render through
  `describe_exception`, which closes **two** of the five. The remaining three
  are `delivery.py`'s `_journal_write` print and its **two persisted-to-the-
  delivery-log** interpolations (`process_due:264`, `_finish` via `:256`). CG-73's
  row is updated to say three, not five — a count with two homes is this repo's
  own recorded failure mode.

---

## 8. Rows

| Row | Change |
|---|---|
| **CG-75** | gains a spec + plan link, **and is recorded as a dependency of CG-55** (user decision, 2026-08-02) |
| **CG-74** | gains a spec + plan link; sequenced **after** CG-75; its *"never fires at all"* claim narrowed to the 72.5-minute ladder window (§2.3) |
| **CG-55** | gains **CG-75** in its dependency list |
| **CG-73** | narrowed from five sites to three |
| **CG-76** | **new** — the dead-man switch's silent alert drop |

**CG-55's new dependency, in the user's own accepted reasoning:** the gateway
has never run on a box with a real disk that can fill, so *"low likelihood"* is
an artifact of never having been deployed. CG-55 is precisely the event that
changes it. A first deploy that can turn a full disk into an unbounded send
storm against Google is a first deploy that should not happen.
