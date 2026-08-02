# Runtime lifecycle and thread liveness — design

**Date:** 2026-08-02 · **Planner** · branch `docs/cg-71-lifecycle-and-cg-70`
**Baseline:** `main` at `36fac22`, suite **314 passing** (re-measured here with
`python3 -m pytest -q` — `314 passed in 58.76s`; not taken from a queue row).

**Rows this spec produces:** CG-71 (shutdown path), CG-72 (`/healthz` liveness
for the dispatcher and the heartbeat monitor), CG-73 (CG-29 allowlist residue).
**Row this spec re-scopes:** CG-70 (the create-only `0600` chmod).

**No ⚠ verification-ledger flag is cleared, added or reworded by anything in
this document.** Nothing here touches a Google seam: the shutdown path stops
threads that own adapters, it does not change what any adapter sends, receives
or reports. `docs/architecture/` is untouched.

---

## 1. Where this came from

CG-68's Builder deferred one finding, L4: the retention sweeper's
`start()`/`stop()` are not idempotent and nothing ever stops the sweeper. It
declined to fix it because Task 11's instruction — *"stop it where the
dispatcher and monitor are stopped"* — names a place that does not exist.

That deferral is correct, and **it understates the problem in one direction and
overstates it in another.** Both halves were measured before any of this was
designed, because the deferral note is the only prior art and it was written
from inside a retention row.

---

## 2. What was measured

Every number and behaviour below was produced on this machine, on this branch's
baseline commit. The experiment scripts live in the session scratchpad, not in
the repo; each is described precisely enough to re-run.

### 2.1 There is no shutdown path at all — four starts, zero stops

```
$ grep -n "\.start()\|\.stop()" src/chat_gateway/__main__.py
171:        sweeper.start()
179:            subscriber.start()
187:        app.state.dispatcher.start()
188:        app.state.monitor.start()
```

Four `.start()`, zero `.stop()`. No `finally`, no `atexit`, no signal handler,
no lifespan hook anywhere in the file. **This is not "the retention row forgot
its cleanup" — it is four long-lived threads with no shutdown path, and CG-68
merely added the fourth.**

The four are `retention-sweeper`, `pubsub-subscriber`, `delivery-dispatcher` and
`heartbeat-monitor`. All four are `daemon=True`, and all four use the identical
`threading.Event` + `join(timeout=5)` idiom, so the deferral's *"byte-for-byte
the `Dispatcher` idiom"* is accurate.

`SubscriberLoop.stop()`'s own docstring already reasons about *"a real
shutdown"* — *"during a real shutdown nobody is reading `/healthz` anyway"* —
which is a docstring written for a caller that has never existed.

### 2.2 ⚠ The obvious fix does not run — `uvicorn.run()` never returns on SIGTERM

This is the single most important measurement in this document, because it
invalidates the shape a Builder would reach for first.

Read from the installed uvicorn (0.42.0), `Server.capture_signals`:

```python
        original_handlers = {sig: signal.signal(sig, self.handle_exit) for sig in HANDLED_SIGNALS}
        try:
            yield
        finally:
            for sig, handler in original_handlers.items():
                signal.signal(sig, handler)
        # If we did gracefully shut down due to a signal, try to
        # trigger the expected behaviour now; multiple signals would be
        # done LIFO, see https://stackoverflow.com/questions/48434964
        for captured_signal in reversed(self._captured_signals):
            signal.raise_signal(captured_signal)
```

uvicorn restores the **default** disposition and then **re-raises** the signal,
so the process dies by SIGTERM rather than returning. Confirmed by experiment —
a child running `uvicorn.run()` with a daemon thread, an `atexit` handler, a
`try/finally` around the call, and an ASGI lifespan shutdown hook, sent SIGTERM
after it was serving:

```
first: READY
rc=-15  (negative == killed by that signal; 0 == clean return)
rest: 'LIFESPAN_SHUTDOWN\n'
```

`rc=-15` is death by SIGTERM. **`RUN_RETURNED` did not print. `FINALLY` did not
print. `ATEXIT` did not print.** Exactly one hook ran: the **ASGI lifespan
shutdown hook**, because it executes inside `serve()`, before `capture_signals`
exits and re-raises.

**Consequence for the design, stated plainly so it is not re-derived:** a
`try: ... finally: dispatcher.stop()` in `__main__.main()` — the shape Task 11's
wording implies and the shape any reviewer would nod at — **is a silent no-op on
the only signal that matters.** It would pass every unit test, look correct in
review, and never execute in production. A shutdown path for this process must
be an **ASGI lifespan hook**, or nothing.

### 2.3 Blast radius of a lifespan hook: zero on the current suite

Starlette's `TestClient` runs lifespan **only** when used as a context manager.

```
with-block clients: 0
bare clients:       23
```

All 23 `TestClient` constructions in the suite are bare. Adding a lifespan
shutdown hook therefore cannot perturb any of the 314 existing tests — and, the
same fact pointed the other way, **the hook is invisible to the existing test
idiom**, so its own test must use `with TestClient(app):` deliberately. Both
halves are load-bearing and both are recorded because the second is how a
lifespan hook ships untested.

### 2.4 Durability: an abrupt death loses no journalled state

`Journal._append` (and the batch-close path beside it) does, inside one
`open()` context: `write()` → `flush()` → `os.fsync()`. Nothing is buffered
across appends, so there is no unflushed window for a graceful stop to flush.

Measured directly rather than reasoned about. A child process hammering
`Journal.open()` from a **daemon thread** was killed two ways, and the resulting
journal parsed both times:

```
[SIGTERM] rc=0 bytes=2671 parseable_records=23 torn_trailing_line=False
[SIGKILL] rc=-9 bytes=1384 parseable_records=12 torn_trailing_line=False
```

Neither produced a torn record. That is a property of the write shape — one
`write()` of ~116 bytes to an `O_APPEND` fd — not luck, and `journal.py` already
tolerates a torn trailing line anyway (`journal_skipped_lines` at `/healthz`,
pinned by `test_a_torn_trailing_line_is_skipped_and_counted_not_fatal`).

### 2.5 Whether CG-54's SIGKILL proof already covers this

**Partly — and the gap it leaves is one the design already accepts, not one a
shutdown path would close.**

`tests/test_durability.py::test_a_job_survives_an_ABRUPT_kill_of_a_real_process`
starts a real child, enqueues three jobs and one inbound reply, and
`Popen.kill()`s it — *"`SIGKILL` on POSIX and `TerminateProcess` on Windows —
uncatchable on both, so no atexit hook, no `finally`, and no graceful flush can
run."* It then proves replay with the attempt count preserved, exactly-once
drain, and a clean third boot.

**What it covers:** the durability guarantee itself. Journalled state survives
an uncatchable kill and replays correctly. Since SIGKILL is strictly more abrupt
than anything a SIGTERM path can produce, **the shutdown gap cannot violate any
promise in `delivery.py`'s or `journal.py`'s docstrings.**

**What it does not cover, and why that is fine:** the child calls
`process_due()` **synchronously** and then sleeps, so the kill lands with no
append and no send in flight. The genuinely uncovered window is a kill *during*
a send — and `Dispatcher._finish` already documents that window as deliberate:

> THE MID-FLIGHT WINDOW, stated rather than hidden: the send has returned, the
> log record is written, and the `close` is not. A process killed here replays
> the job and delivers it TWICE. Deliberate — Chat gives us no idempotency key,
> so the alternative is a two-phase commit we are not building, and losing an
> alert is the worse failure.

A graceful stop **narrows** that window; it does not close it and it changes no
guarantee. **So the durability half of CG-71 is small, and this spec says so
plainly rather than inflating it.** The row is not justified by durability.

### 2.6 The part that IS a live defect: `/healthz` cannot see two of the four threads

Hard rule #5 says `/healthz` reports real liveness. Measured across the four:

| thread | `thread_alive` | `thread_started` | staleness | can degrade `status`? |
|---|---|---|---|---|
| `pubsub-subscriber` | ✅ | ✅ | ✅ | ✅ |
| `retention-sweeper` | ✅ | ✅ | ✅ | ✅ |
| `delivery-dispatcher` | ❌ | ❌ | ❌ | **❌** |
| `heartbeat-monitor` | ❌ | ❌ | ❌ | **❌** |

`grep -c thread_alive src/chat_gateway/service.py` → **8**, all of them in the
subscriber and retention blocks. The `delivery` block publishes `pending_jobs`,
the boot counters and the journal error counters; **every `reasons.append` in
that block is gated on `journal_skipped_lines`, `journal_write_errors`, or
`expired_at_boot`/`unroutable_at_boot`. `pending_jobs` gates nothing.** The
`heartbeats` block publishes `checks`, `missed` and `last_scan_at`, and **no
reason references `last_scan_at` at all.**

Both `_run` loops swallow per-pass exceptions and continue — which is right —
but neither catches what its own handler raises, which is the precise hole
`RetentionSweeper.is_alive`'s docstring was written about:

> `_run`'s `except Exception` covers the sweep; it does NOT cover an exception
> raised inside its own handler — a `print()` to a closed or blocked stdout is
> the realistic one — which escapes the `while` and kills the thread.

So today:

- **A dead `delivery-dispatcher` means every outbound notification silently
  stops.** `pending_jobs` climbs, and `/healthz` answers `ok` forever. Nothing
  is delivered; nothing says so.
- **A dead `heartbeat-monitor` means the dead-man switch is dead.**
  `last_scan_at` freezes at a real timestamp — which is what makes it look
  healthy — and `missed` stops moving because nothing scans. aitrader's contract
  surface is a dead-man monitor; a dead-man monitor that dies silently is the
  worst available failure of that feature.

**That is the 11-day-silent-capture-failure shape hard rule #5 was written
after, present twice, on the two threads nobody added a liveness field to.** It
is a bigger and more current problem than the shutdown gap that led me to it.
CG-68's audit found exactly this shape for the sweeper (F3 / M3b) and closed it
there; the same finding through the same door exists for the other two and was
never opened.

### 2.7 Idempotency, measured across all four

- **`stop()` is already effectively idempotent** in all four classes:
  `self._stop.set()` is idempotent, and `if self._thread:` makes a stop without a
  prior start a no-op. Calling `stop()` twice, or stopping a component that was
  never started, is safe today. This matters: it is what lets a single shutdown
  path call `stop()` on all four unconditionally, including the `subscriber`
  that is `None` when Pub/Sub is off and the `sweeper` on an app built without
  one.
- **`start()` is not idempotent, in all four.** A second `start()` builds a
  second thread and overwrites `self._thread`, orphaning the first — it keeps
  running and is no longer joinable. Nothing calls `start()` twice today, so
  this is latent.
- **`start()` after `stop()` is broken, in all four.** `_stop` is never cleared,
  so the new thread's `while not self._stop.is_set()` exits on its first
  evaluation. A component that has been stopped cannot be restarted, and it
  fails **silently** — `start()` returns, `_started` is `True`, and the thread
  is dead. On the two classes that publish liveness this renders as *"started
  and is NOT RUNNING"*, which is at least honest; on the other two it renders as
  nothing.

### 2.8 Does the shutdown gap matter today, or is it CG-55 that makes it real?

**Today: no.** All four threads are daemon threads, the process dies on SIGTERM
in ~0.16s (measured above), nothing hangs, and no journalled state is lost
(§2.4, §2.5). There is no operator-visible symptom.

**At CG-55: still not a hang, but it starts to cost something real.** The deploy
target is a TrueNAS custom app, `restart: unless-stopped`, so the container is
stopped and restarted by `docker stop` — SIGTERM, then SIGKILL after the grace
period. Because uvicorn re-raises, the container will always stop promptly; the
grace period is never reached. What changes is frequency: every deploy, every
host reboot, every config change becomes a kill landing at an arbitrary point in
a dispatcher pass, and each one is a fresh draw on the mid-flight window in
§2.5 — i.e. an occasional duplicate Chat message after a restart. That is a
**quality** cost, bounded and already-documented, not a correctness one.

**Verdict, stated so the row is not oversold: the shutdown gap is LATENT.** It
is worth closing because closing it is cheap and because the alternative shape
(§2.2) is a trap that will otherwise be walked into. It is **not** worth closing
because of durability, and this spec declines to claim that.

**The `/healthz` gap in §2.6 is not latent.** It is live on every deployment,
including the one CG-55 is about to make.

---

## 3. Decision: split into two rows, and sequence the liveness one first

**CG-72 — `/healthz` liveness for the dispatcher and the heartbeat monitor.**
Rule #5, live today, independent of shutdown, offline-testable, and the same
mechanical shape CG-68 already shipped twice. This is the row that should land.

**CG-71 — the shutdown path.** The lifespan hook, `stop()` for all four,
`start()` idempotency. Latent, and it carries the one genuine design decision
(§2.2).

**Why split rather than one PR.** They touch the same two classes, so they must
not run concurrently — but they are not the same kind of change. CG-72 is a
correctness fix with no open questions. CG-71 is a design call about where a
shutdown hook lives, and it is exactly the kind of thing that draws review
discussion. Putting a must-land rule-#5 fix behind a design conversation is how
the must-land fix waits a week. **CG-72 first, CG-71 second, neither concurrent
with the other.**

**Why not fold either into CG-55.** CG-55 is the deploy row and is
Builder-executed over SSH behind a merge gate. A `src/` change to the delivery
and heartbeat paths does not belong inside the PR that first runs the gateway on
the NAS.

---

## 4. CG-72 design — make the other two threads legible

**Follows the existing pattern exactly; invents nothing.** `SubscriberLoop` and
`RetentionSweeper` already define `started` (a property, *not* cleared by
`stop()`) and `is_alive()` (the direct signal), and `/healthz` already renders
both plus a staleness check in a four-branch `elif` chain. CG-72 gives
`Dispatcher` and `HeartbeatMonitor` the same two members and `/healthz` the same
chain.

**Design points, each with its reason:**

1. **`started` is not cleared by `stop()`,** matching both existing classes and
   for their stated reason: a component still configured and no longer running
   is a fact `/healthz` must report, and whether it stopped on purpose does not
   change that.

2. **The staleness signal differs per component, and must not be invented where
   none exists.**
   - `HeartbeatMonitor` already stamps `last_scan_at` on every completed scan.
     That is a true "last completed pass" timestamp and is the direct analogue of
     `last_poll_at` / `last_sweep_at`. Use it.
   - `Dispatcher` has **no** such timestamp. `process_due()` returns a count and
     stamps nothing. **CG-72 adds `last_pass_at`,** stamped at the end of every
     `process_due()` — including a pass that had nothing to do, for the reason
     `RetentionSweeper.sweep` records in its own comment: *"a pass that had
     nothing to do is still a pass that RAN"*, and an idle dispatcher must not be
     byte-identical to a dead one on the endpoint whose job is telling them
     apart.

3. **Both new blocks degrade `status`.** A dead delivery thread and a dead
   dead-man monitor are faults, unambiguously. This is the opposite of the
   `suppressed_*` counters, which deliberately do not degrade because a
   guarantee working is not a fault.

4. **At most one reason per fault**, using the same `elif` ordering the
   subscriber and retention blocks already use: never-ran → dead-thread →
   stale-but-alive. A dead thread also looks stale, and two reasons for one
   fault is noise.

5. **Both must tolerate absence.** `/healthz` must answer 200 for an app built
   without a dispatcher-with-threads (the 23 bare-`TestClient` tests are exactly
   that shape), and CG-68's audit F0 found a `KeyError` of precisely this kind
   when a sweeper was absent. `Dispatcher` and `HeartbeatMonitor` are always
   constructed by `create_app`, so the objects always exist — but they are
   usually **never started**, and `started == False` must render as silence, not
   as a reason.

**Explicitly out of scope for CG-72:** the shutdown path, `start()` idempotency,
and anything in `adapters/`.

---

## 5. CG-71 design — one shutdown path, in the one place that runs

### 5.1 Shape

A single **ASGI lifespan shutdown hook** registered in `create_app`, stopping
all four components. Not a `finally`, not `atexit`, not a signal handler of our
own — §2.2 measured all three and only this one runs.

`create_app` already holds references to every one of the four: `dispatch`
(built or injected), `monitor` (built internally), `subscriber` (a parameter),
`sweeper` (a parameter since CG-68). **One shutdown path, not four**, because
all four are the same idiom, the order does not matter (they share no state and
each `stop()` is independent), and four separate hooks would be four places to
forget the fifth thread.

### 5.2 Stop-only, deliberately asymmetric

The hook stops; it does **not** start. Starts stay exactly where they are in
`__main__`.

**Why, recorded because the symmetry is tempting and wrong here.** Moving
`start()` into the lifespan *startup* hook would make every test that uses
`with TestClient(app):` spawn four real threads, and would make the boot
ordering in `__main__` — `inbox.restore()` → `sweeper.sweep()` → `start()`,
which CG-68 comments at length about getting right — a property of ASGI
lifecycle rather than of code a reader can follow top to bottom. The
asymmetry costs one comment; the symmetry costs the boot order.

This is safe precisely because §2.7 measured `stop()` as already idempotent and
safe on a never-started component: the hook can stop all four unconditionally.

### 5.3 `start()` idempotency

Make `start()` a no-op when the thread is already alive, in all four classes.
This closes the orphaned-thread hazard in §2.7.

**Do NOT make `start()` after `stop()` work by clearing `_stop`.** It is
tempting — it is the other half of §2.7 — and it is out of scope: nothing
restarts a component, a restartable component needs a defined semantics for the
in-flight work it abandoned, and inventing that inside a lifecycle row is how a
row grows a second feature. **The right treatment is to make the broken case
loud rather than silent:** `start()` after `stop()` raises. A caller that wants
a fresh loop constructs a fresh object, which is what `__main__` does anyway.

### 5.4 What CG-71 must not do

- **No ⚠ verification-ledger flag may be cleared, added or reworded.** The
  shutdown path stops the thread that owns `PubSubPuller` and the thread that
  drives the outbound adapters, which puts it one call away from `adapters/`. It
  must not change what any adapter sends, receives, retries or prints. If
  implementation appears to require an adapter change, **stop and raise it** —
  do not proceed.
- **No change to the mid-flight window's semantics.** A graceful stop narrows
  it; `delivery.py`'s docstring stays exactly as written, because at-least-once
  is still the guarantee.
- **No `join()` timeout increase.** All four use `join(timeout=5)`; the
  dispatcher's pass can block on an adapter HTTP call, so a stop can take up to
  the adapter's own timeout. Five seconds is a bound on *waiting*, not a promise
  the thread finished — and since the process is dying anyway, a thread still
  running at the timeout is no worse than today's unconditional abandonment.

---

## 6. CG-70 — the decision

### 6.1 The row's own argument, and the measurement that overturns it

The row scopes two candidates and recommends (b):

> (a) `stat` the existing file and chmod when the mode is wrong — correct and
> self-healing, but **adds a `stat` per append to a path that deliberately has
> none**. (b) A one-time `chmod 0600` line in the CG-53 deploy runbook … **(b)
> looks right given the runbook already owns this class of control**.

**The emphasised clause is false, and this is what decides the row.** Every one
of the four write sites already performs a stat on every append — that is what
`existed = path.exists()` *is*:

```python
        existed = path.exists()
        with path.open("a", encoding="utf-8") as fh:
            if not existed:
                chmod_owner_only(path)
```

Confirmed at the syscall level with `strace` on the real `Journal`, three
consecutive appends:

```
newfstatat(AT_FDCWD, ".../sc.jsonl", 0x7ffcf59ff2f0, 0) = -1 ENOENT
openat(AT_FDCWD, ".../sc.jsonl", O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC, 0666) = 3
chmod(".../sc.jsonl", 0600) = 0
newfstatat(AT_FDCWD, ".../sc.jsonl", {st_mode=S_IFREG|0600, st_size=113, ...}, 0) = 0
openat(...) = 3
newfstatat(AT_FDCWD, ".../sc.jsonl", {st_mode=S_IFREG|0600, st_size=226, ...}, 0) = 0
openat(...) = 3
```

One `newfstatat` per append, already there — **and the kernel already returns
the mode in it** (`st_mode=S_IFREG|0600`). `Path.exists()` throws that away and
keeps one bit.

So option (a) is not "one extra syscall per append". It is **"read the field the
syscall you already make already returned"**: replace `path.exists()` with a
`path.stat()`, compare `st_mode & 0o777`, and chmod when it is wrong. Steady
state: **identical syscall count.** One-time: exactly one extra `chmod` per
wrong-moded file, ever, after which the comparison passes forever.

### 6.2 The other measurement — (a) cannot reach every affected file

Honesty in the other direction, because this is what stops (a) from being the
whole answer. **Option (a) only ever heals a file the process appends to**, and
the write paths are date-sharded: the code only ever opens *today's* file. A
`0644` day-file from three days ago is never reopened, so (a) will never touch
it. It sits at `0644` until the retention sweeper deletes it — up to
`retention.window_days`, i.e. 30 days for a tenant bucket, and **forever** on a
deployment that has set `CHAT_GATEWAY_INBOX_RETENTION_DAYS=0`.

**So (a) and (b) cover disjoint sets of files.** The row presented them as
alternatives; they are not.

### 6.3 The third option, considered and rejected

**(c) a one-time chmod pass at boot,** beside the boot sweep `__main__` already
runs. It is reachable — `__main__` already walks this territory — it covers
exactly the historical set (b) covers, and unlike (b) it works on a dev box.

**Rejected**, for two reasons:

1. It would be the **third home** for a file-mode control (create-time
   `chmod_owner_only`, the runbook's `install -d -m 0750`, and this). This
   repo's own recorded lesson — the test count, the space-membership snapshot —
   is that a fact with two homes drifts, and `chmod_owner_only`'s docstring
   already says *"One home, because a second copy of a security control is how
   the two drift apart."* A boot pass is that second copy.
2. It is a directory walk with `chmod` in it, at boot, over the same directory
   the sweeper deletes from. CG-68's review found the sweeper pruning
   `state/deliveries/` because a guard was narrower than the docstring claimed.
   Adding a second boot-time walker over the same trees, with different
   exclusion logic, is buying a repeat of that finding for a set of files that
   is **empty today**.

### 6.4 Decision

**CG-70 stays as its own row, re-scoped to (a), with (b) handed to CG-53 as a
one-line runbook addition.**

- **(a) is the mechanism**, in all four `existed = path.exists()` sites
  (`inbox.py::_audit`, `inbox.py`'s quarantine append, `delivery.py::DeliveryLog.record`,
  `journal.py::_append`; the batch-close path in `journal.py` shares the same
  shape and gets the same treatment). Free in the steady state (§6.1), and it
  makes the guarantee a property of the code rather than of an operator
  remembering a runbook step.
- **(b) is a one-line addition to CG-53's runbook**, covering the historical
  files (a) provably cannot reach (§6.2). It belongs in CG-53 because CG-53
  already owns `install -d -m 0750` and is where a one-time deployment migration
  goes — not because (b) is better than (a).
- **(c) is rejected** (§6.3).

**Not folded into CG-53 and not closed.** Closing it was a legitimate outcome
and was considered: the row is LOW, no such file exists anywhere today, and the
window is bounded by date-sharding. It is kept as a row for one reason — **(a)
is a `src/` change across four files with tests, and CG-53 is a merge-gated
deploy-artifacts row.** Folding a four-file code change into the row that
handles secrets makes the gated row bigger and harder to review, which is the
opposite of what a merge gate is for.

**The severity is unchanged — still LOW. What changed is the reason to do it:**
not *"defer it, it is low"* but **"do it, it is free."** The row was deferred on
a cost that does not exist.

---

## 7. CG-73 — CG-29 allowlist residue (filed, not planned here)

Found while reading the `_run` loops for §2.6, and filed rather than folded in.

`CLAUDE.md`'s CG-29 rule: *an exception message is printed in full only if this
repo wrote every byte of it*, enforced by `errors.py`'s marked set and
`describe_exception`. `retention.py` — the newest of the four loops — applies it:
`describe_exception(exc)` at both its print sites, with a comment explaining that
`str(OSError)` from `unlink()` embeds the absolute path. The older code does not.
Five sites interpolate a raw foreign exception:

| site | what it prints |
|---|---|
| `delivery.py:190` | `f"dispatcher: journal {op} failed ({exc})"` |
| `delivery.py:368` | `f"dispatcher: pass error (will retry): {exc}"` |
| `heartbeat.py:199` | `f"heartbeat: scan error (will retry): {exc}"` |
| `delivery.py`, `process_due` | `f"gave up after {job.attempts} attempts: {exc}"` — **persisted** to the delivery log |
| `delivery.py`, `process_due` | `f"attempt {job.attempts}: {exc}"` — **persisted** to the delivery log |

**Stated at the confidence it deserves: this is drift in a hard-rule-#2 control,
not a proven leak.** No live credential exposure was demonstrated. The adapters
wrap their transport errors into marked classes with clean messages, and CG-23's
tests pin that those messages never carry a URL. `JournalWriteError` is *not* in
the marked set and its own message embeds `str(OSError)` (absolute path), which
is the concrete half.

What makes it worth a row is the shape rather than any one site: CG-29 chose an
**allowlist** precisely so that *"the next unanticipated exception type"* prints
by type alone. Five sites bypass it, and the last two **persist** the result to
a queryable artifact rather than only printing it. `tests/test_error_surfaces.py`
cannot see any of this — it reads the construction sites of marked classes, and
these are print sites of unmarked ones.

---

## 8. Sign-offs needed from the user

None of these is a Planner call.

| # | Question | Planner's recommendation |
|---|---|---|
| **L1** | CG-72 adds `Dispatcher.last_pass_at` and makes both new blocks degrade `status`. A deployment that has never started its dispatcher (any bare-`TestClient` app) must stay silent. Agreed? | yes — it is CG-68's F3 finding on the two threads that never got it |
| **L2** | CG-71's shutdown hook is **stop-only** and asymmetric with `start()` (§5.2). Accept the asymmetry? | yes — symmetry costs the boot order |
| **L3** | `start()` after `stop()` **raises** rather than silently producing a dead thread (§5.3). This is a new exception on a path nothing currently takes. | yes — the alternative is a silent dead thread |
| **L4** | CG-70 re-scoped to (a), (b) handed to CG-53, (c) rejected, row **not** closed (§6.4). | as written |
| **L5** | CG-73 filed as a row at LOW, framed as drift rather than a leak (§7). | file it; do not fold it into CG-71 or CG-72 |

---

## 9. Self-review

- **Placeholder scan** — no `TBD`, no "similar to", no unresolved reference.
- **Every number re-measured on this branch's baseline**: 314 tests, 4 starts /
  0 stops, `rc=-15`, 8 `thread_alive` occurrences, 0 `with TestClient` blocks,
  23 bare ones, the `strace` output. None taken from a queue row.
- **Scope check** — three new rows, one re-scoped row, no `src/` change in this
  PR. `docs/architecture/` untouched.
- **⚠ flags** — none cleared, added or reworded. §5.4 makes that a constraint on
  CG-71's implementation, not just a claim about this document.
- **Where this document is wrong about something previously written down, it
  says so and how it found out**: the deferral note (§2.1, understated), the
  `try/finally` shape Task 11 implies (§2.2), and CG-70's own cost argument
  (§6.1).
