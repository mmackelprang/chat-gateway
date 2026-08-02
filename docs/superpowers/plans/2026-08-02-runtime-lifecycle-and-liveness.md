# Runtime lifecycle and thread liveness — implementation plan

**Spec:** [`2026-08-02-runtime-lifecycle-and-liveness-design.md`](../specs/2026-08-02-runtime-lifecycle-and-liveness-design.md)
**Baseline:** `main` at `36fac22`, suite **314 passing** (re-measured, not quoted).
**Rows:** Part A = **CG-72**, Part B = **CG-71**. **Two PRs, A first.**

⚠ **Read the spec's §2.2 before Part B.** A `try/finally` around `uvicorn.run()`
is measurably a no-op on SIGTERM. If Part B's implementer reaches for one, the
plan has failed to communicate and the work should stop.

⚠ **No ⚠ verification-ledger flag may be cleared, added or reworded by either
part.** Nothing here changes what an adapter sends, receives, retries or prints.
`docs/architecture/` is off-limits.

**Sequencing:** Parts A and B touch the same two classes (`Dispatcher`,
`HeartbeatMonitor`) and the same file (`service.py`). **They must not run
concurrently.** A lands, merges, then B branches from it.

---

# Part A — CG-72 · `/healthz` liveness for the dispatcher and the monitor

## Task A1 · `Dispatcher` gains the liveness triple

**File:** `src/chat_gateway/delivery.py`

Add the module constant beside the existing ones (after `REPLAY_MAX_AGE_S` on
line 42):

```python
#: How long `_run` sleeps between passes. Promoted from the literal that used to
#: sit inside `_run` because /healthz must judge staleness against the interval
#: this loop is actually supposed to run at, and a second copy of that number in
#: `service.py` is how the two drift apart (`RetentionSweeper.interval_seconds`
#: says the same thing about the same problem).
PASS_INTERVAL_S = 1.0
```

In `Dispatcher.__init__`, immediately after `self._thread: threading.Thread | None = None`:

```python
        #: Was `start()` ever called? NOT cleared by `stop()`. Same contract and
        #: same reasoning as `SubscriberLoop.started` and
        #: `RetentionSweeper.started`: `is_alive()` alone cannot tell a loop that
        #: was never started from one that started and died, and only the second
        #: is a fault. Every offline test builds a Dispatcher and never starts it.
        self._started = False
        #: When the last pass COMPLETED. The direct analogue of
        #: `last_poll_at` / `last_sweep_at`, and the field this class did not
        #: have — `process_due()` returned a count and stamped nothing, so a
        #: dispatcher that had stopped dispatching was indistinguishable from
        #: one with nothing to do, on the endpoint whose job is telling those
        #: two apart (hard rule #5).
        self.last_pass_at: dt.datetime | None = None
```

Add the three members next to `pending()` (anywhere in the public block; put
them immediately before `_run`):

```python
    @property
    def interval_seconds(self) -> float:
        """The pass interval, readable by `/healthz`. See `PASS_INTERVAL_S`."""
        return PASS_INTERVAL_S

    @property
    def started(self) -> bool:
        """Was `start()` ever called? NOT cleared by `stop()` — see `__init__`."""
        return self._started

    def is_alive(self) -> bool:
        """Is the dispatch thread actually running right now?

        The DIRECT liveness signal (hard rule #5), and it is not redundant with
        `pending_jobs`. `_run`'s `except Exception` covers `process_due`; it does
        NOT cover an exception raised inside its own handler — a `print()` to a
        closed or blocked stdout is the realistic one — which escapes the
        `while` and kills the thread. Every field in the delivery block then
        freezes at a plausible value: the boot counters hold real numbers,
        `pending_jobs` holds a real number and grows, and NOTHING IS EVER
        DELIVERED AGAIN. That is the 11-day-silent-failure shape rule #5 was
        written after, and it is the finding `RetentionSweeper.is_alive` records
        for the sweeper, through the same door.
        """
        return self._thread is not None and self._thread.is_alive()
```

Stamp the timestamp at the end of `process_due`. Replace:

```python
            else:
                self._finish(job, "delivered", f"after {job.attempts + 1} attempt(s)")
        return attempted
```

with:

```python
            else:
                self._finish(job, "delivered", f"after {job.attempts + 1} attempt(s)")
        # STAMPED EVEN WHEN `due` WAS EMPTY, deliberately, and for the reason
        # `RetentionSweeper.sweep` records in its own comment: a pass that had
        # nothing to do is still a pass that RAN. The gateway's traffic shape is
        # tens of messages a day (journal.py), so the overwhelming majority of
        # passes are empty — if only a non-empty pass stamped, "healthy and idle"
        # would be byte-identical to "the thread is dead" for hours at a time.
        self.last_pass_at = now
        return attempted
```

`now` is already bound at the top of `process_due`; do not call `self._now()` a
second time.

Finally, in `start()`, record that it happened, and use the constant in `_run`:

```python
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_due()
            except Exception as exc:  # noqa: BLE001 — the loop must survive
                print(f"dispatcher: pass error (will retry): {exc}", flush=True)
            self._stop.wait(PASS_INTERVAL_S)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="delivery-dispatcher", daemon=True)
        self._started = True
        self._thread.start()
```

⚠ Leave the `{exc}` interpolation on that `print` **exactly as it is**. It is a
real finding and it is **CG-73's**, not this row's — changing it here would put
a hard-rule-#2 control change inside a `/healthz` row, unreviewed by anyone
looking for one.

---

## Task A2 · `HeartbeatMonitor` gains the same triple

**File:** `src/chat_gateway/heartbeat.py`

In `HeartbeatMonitor.__init__`, after `self._thread: threading.Thread | None = None`:

```python
        #: Was `start()` ever called? NOT cleared by `stop()`. See
        #: `Dispatcher.started` — identical contract, identical reasoning.
        self._started = False
```

`self.last_scan_at` already exists and is already stamped by `scan_once`; it
needs no change. That is the whole reason this class is cheaper than the
dispatcher — it already had its "last completed pass" timestamp.

Add, immediately before `_run`:

```python
    @property
    def interval_seconds(self) -> float:
        """The configured scan interval, readable by `/healthz`.

        Public for the reason `RetentionSweeper.interval_seconds` gives:
        staleness is judgeable only relative to how often this loop is supposed
        to run, and `service.py` must not hardcode a copy that drifts from the
        constructor argument (`create_app`'s `monitor_interval` is settable).
        """
        return self._interval

    @property
    def started(self) -> bool:
        """Was `start()` ever called? NOT cleared by `stop()`."""
        return self._started

    def is_alive(self) -> bool:
        """Is the scan thread actually running right now?

        Hard rule #5, and on this class it is the dead-man switch's own dead-man
        switch. `_run` survives what `scan_once` raises; it does not survive
        what its own handler raises. A dead scan thread leaves `last_scan_at`
        frozen at a REAL timestamp and `missed` frozen at a real count, which is
        precisely why it looks healthy — and every heartbeat check registered by
        every consumer silently stops being evaluated. aitrader's contract
        surface is a dead-man monitor; one that dies quietly is the worst
        available failure of that feature.
        """
        return self._thread is not None and self._thread.is_alive()
```

And in `start()`:

```python
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="heartbeat-monitor", daemon=True)
        self._started = True
        self._thread.start()
```

⚠ Same instruction as A1: leave `heartbeat.py`'s `{exc}` print untouched (CG-73).

---

## Task A3 · `/healthz` — constants and helpers

**File:** `src/chat_gateway/service.py`

After `POLL_STALE_INTERVAL_MULTIPLE = 6` (line 72), add:

```python
#: Silence before /healthz calls OUTBOUND DELIVERY dead.
#:
#: The floor is chosen against a real bound, as `POLL_STALE_AFTER_SECONDS`'s is,
#: and the bound here is worse: `process_due` walks every due job SEQUENTIALLY
#: and each `adapter.send` is bounded only by its client timeout — 30s for both
#: `webhook` and `chat_api`. A backlog of N jobs all timing out therefore holds
#: `last_pass_at` still for ~30N seconds while the dispatcher is working
#: perfectly. 600s clears twenty consecutive timing-out sends, which is far past
#: any realistic pass at this gateway's traffic shape (tens of messages a day,
#: journal.py) and is still one dashboard refresh rather than eleven days.
#:
#: Stated rather than glossed: this is a LOOSER detector than the subscriber's.
#: Ten minutes to notice a dead delivery thread is the price of not crying wolf
#: at every slow Google call, and it is bought against a baseline of NEVER.
DISPATCH_STALE_AFTER_SECONDS = 600.0
DISPATCH_STALE_INTERVAL_MULTIPLE = 60

#: Silence before /healthz calls the HEARTBEAT MONITOR dead. `scan_once` does no
#: network I/O — it reads the store and hands work to `Dispatcher.enqueue`,
#: which appends and returns — so a scan is fast and bounded, and this needs no
#: allowance for a slow remote call. Six intervals matches the subscriber's
#: multiple; the 300s floor keeps a deployment that sets a very short
#: `monitor_interval` from alarming on ordinary jitter.
SCAN_STALE_AFTER_SECONDS = 300.0
SCAN_STALE_INTERVAL_MULTIPLE = 6
```

After `_sweep_stale_after` (ends line 88), add:

```python
def _dispatch_stale_after(dispatch) -> float:
    """Seconds of silence tolerated before the last completed pass is stale."""
    return max(DISPATCH_STALE_AFTER_SECONDS,
               DISPATCH_STALE_INTERVAL_MULTIPLE * dispatch.interval_seconds)


def _scan_stale_after(monitor) -> float:
    """Seconds of silence tolerated before the last completed scan is stale."""
    return max(SCAN_STALE_AFTER_SECONDS,
               SCAN_STALE_INTERVAL_MULTIPLE * monitor.interval_seconds)
```

---

## Task A4 · `/healthz` — body fields

**File:** `src/chat_gateway/service.py`, inside `healthz()`.

Replace the `delivery` block's closing lines. Current:

```python
                         "journal_skipped_lines": _journal_skipped(dispatch, inbox),
                         "journal_write_errors": _journal_write_errors(dispatch, inbox)},
```

becomes:

```python
                         "journal_skipped_lines": _journal_skipped(dispatch, inbox),
                         "journal_write_errors": _journal_write_errors(dispatch, inbox),
                         # CG-72. The third way of judging outbound, and the one
                         # nothing else can substitute for. `pending_jobs` cannot
                         # do it: a dead dispatcher and a busy one both show a
                         # non-zero number, and an idle deployment shows zero
                         # either way. Counters see nothing when a loop stops
                         # raising as well as stops working.
                         "thread_alive": dispatch.is_alive(),
                         # ...and without this, `thread_alive: false` is
                         # ambiguous: a dispatcher that was never started looks
                         # identical to one that died, and only the second is a
                         # fault. Every offline test is the first case.
                         "thread_started": dispatch.started,
                         "last_pass_at": (dispatch.last_pass_at.isoformat()
                                          if dispatch.last_pass_at else None),
                         "seconds_since_last_pass": (
                             round((now - dispatch.last_pass_at).total_seconds(), 1)
                             if dispatch.last_pass_at else None),
                         "stale_after_seconds": _dispatch_stale_after(dispatch),
                         "pass_interval_seconds": dispatch.interval_seconds},
```

Replace the `heartbeats` block. Current:

```python
            "heartbeats": {"checks": len(hb_all),
                           "missed": sum(1 for c in hb_all if c.status == "missed"),
                           "last_scan_at": monitor.last_scan_at.isoformat() if monitor.last_scan_at else None},
```

becomes:

```python
            "heartbeats": {"checks": len(hb_all),
                           "missed": sum(1 for c in hb_all if c.status == "missed"),
                           "last_scan_at": monitor.last_scan_at.isoformat() if monitor.last_scan_at else None,
                           # CG-72. `last_scan_at` was already published and
                           # already frozen-at-a-real-timestamp when the thread
                           # dies, which is exactly what made it read as healthy.
                           # These three are what turn it into a signal.
                           "thread_alive": monitor.is_alive(),
                           "thread_started": monitor.started,
                           "seconds_since_last_scan": (
                               round((now - monitor.last_scan_at).total_seconds(), 1)
                               if monitor.last_scan_at else None),
                           "stale_after_seconds": _scan_stale_after(monitor),
                           "scan_interval_seconds": monitor.interval_seconds},
```

---

## Task A5 · `/healthz` — the two reason chains

**File:** `src/chat_gateway/service.py`, in the `reasons` section.

Insert **immediately after** the existing
`if queue["expired_at_boot"] or queue["unroutable_at_boot"]:` block and
**before** the `if ret["enabled"]:` line:

```python
        # CG-72. Outbound delivery's liveness, in the subscriber block's shape
        # and for the subscriber block's reason. Not gated on `enabled` — there
        # is no such thing as a deployment without outbound delivery; it is
        # gated on `thread_started`, because the 23 offline tests that build an
        # app and never start a thread must stay silent (CG-68 audit F0 is the
        # same lesson with a KeyError instead of a false alarm).
        #
        # An `elif` chain: a dead thread also looks stale, and two reasons for
        # one fault is noise.
        if queue["thread_started"] and not queue["thread_alive"]:
            reasons.append(
                "delivery: the dispatch thread was started and is NOT RUNNING — "
                "nothing queued will ever be sent and no counter in this block "
                "will move again. `pending_jobs` will climb and every other "
                "field is frozen at a real value, which is why this looks "
                "healthy; restart the service"
            )
        elif queue["thread_started"] and queue["seconds_since_last_pass"] is None:
            reasons.append(
                "delivery: the dispatch thread was started but no pass has ever "
                "completed — the loop runs every "
                f"{queue['pass_interval_seconds']}s and stamps even an empty "
                "pass, so this should be impossible and nothing is being "
                "delivered"
            )
        elif queue["thread_started"] and queue["thread_alive"] and (
                queue["seconds_since_last_pass"] > queue["stale_after_seconds"]):
            reasons.append(
                f"delivery: the thread is alive but the last completed pass was "
                f"{queue['seconds_since_last_pass']}s ago, over the "
                f"{queue['stale_after_seconds']}s budget — passes are neither "
                "completing nor raising, so it is wedged rather than erroring. "
                "A send blocked past its client timeout looks like this"
            )
        # ...and the dead-man switch's own liveness. Same chain, same order.
        # A heartbeat monitor that has died stops evaluating every consumer's
        # checks while `missed` and `last_scan_at` both hold real values.
        hb = body["heartbeats"]
        if hb["thread_started"] and not hb["thread_alive"]:
            reasons.append(
                "heartbeats: the scan thread was started and is NOT RUNNING — "
                "no registered check is being evaluated, so a source that has "
                "gone silent will never be alerted on. `missed` and "
                "`last_scan_at` are frozen at real values; restart the service"
            )
        elif hb["thread_started"] and hb["seconds_since_last_scan"] is None:
            reasons.append(
                "heartbeats: the scan thread was started but no scan has ever "
                "completed — the dead-man monitor has never run on this process"
            )
        elif hb["thread_started"] and hb["thread_alive"] and (
                hb["seconds_since_last_scan"] > hb["stale_after_seconds"]):
            reasons.append(
                f"heartbeats: the thread is alive but the last completed scan "
                f"was {hb['seconds_since_last_scan']}s ago, over the "
                f"{hb['stale_after_seconds']}s budget for a "
                f"{hb['scan_interval_seconds']}s-interval loop — the dead-man "
                "monitor is wedged rather than erroring"
            )
```

`queue` is already bound in that section (it is what the `expired_at_boot`
branch reads). `body["heartbeats"]` is bound as `hb` here because `hb_all` is
already taken by the check list higher up — do not shadow it.

---

## Task A6 · Tests

**File:** `tests/test_service.py` (or a new `tests/test_liveness.py`; either is
fine, but keep all six together).

```python
def test_a_dispatcher_that_was_never_started_is_silent_not_degraded():
    """The 23 offline apps. `thread_alive` is false and it is NOT a fault."""
    client, _inbox, _adapter = _client()          # existing helper
    body = client.get("/healthz").json()
    assert body["delivery"]["thread_started"] is False
    assert body["delivery"]["thread_alive"] is False
    assert body["heartbeats"]["thread_started"] is False
    assert not any("delivery: the dispatch thread" in r for r in body["reasons"])
    assert not any("heartbeats: the scan thread" in r for r in body["reasons"])


def test_a_dispatch_thread_that_started_and_died_degrades_healthz():
    """The founding rule-#5 shape: every field frozen at a plausible value."""
    client, _inbox, _adapter = _client()
    dispatch = client.app.state.dispatcher
    dispatch.start()
    dispatch.stop()                               # thread is now dead
    assert dispatch.started is True
    assert dispatch.is_alive() is False
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    assert any("the dispatch thread was started and is NOT RUNNING" in r
               for r in body["reasons"])


def test_a_scan_thread_that_started_and_died_degrades_healthz():
    client, _inbox, _adapter = _client()
    monitor = client.app.state.monitor
    monitor.start()
    monitor.stop()
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    assert any("the scan thread was started and is NOT RUNNING" in r
               for r in body["reasons"])


def test_an_empty_pass_still_stamps_last_pass_at():
    """Otherwise 'healthy and idle' is byte-identical to 'dead' for hours.

    This is the assertion that makes the staleness branch mean anything at
    this gateway's traffic shape, where nearly every pass is empty.
    """
    d = Dispatcher({}, DeliveryLog())
    assert d.last_pass_at is None
    assert d.process_due() == 0                   # nothing due, nothing to do
    assert d.last_pass_at is not None


def test_a_wedged_dispatcher_is_stale_but_not_reported_dead():
    """Alive + no completed pass past the budget == wedged, one reason only."""
    client, _inbox, _adapter = _client()
    dispatch = client.app.state.dispatcher
    dispatch.start()
    try:
        dispatch.last_pass_at = (dt.datetime.now(dt.timezone.utc)
                                 - dt.timedelta(seconds=DISPATCH_STALE_AFTER_SECONDS + 60))
        body = client.get("/healthz").json()
        assert body["status"] == "degraded"
        hits = [r for r in body["reasons"] if r.startswith("delivery: ")]
        assert len(hits) == 1 and "wedged rather than erroring" in hits[0]
    finally:
        dispatch.stop()


def test_the_delivery_and_heartbeat_stale_budgets_follow_their_intervals():
    """`service.py` must not hardcode a copy of either interval."""
    app = create_app(_registry(), Inbox(), {}, monitor_interval=600.0)
    body = TestClient(app).get("/healthz").json()
    assert body["heartbeats"]["scan_interval_seconds"] == 600.0
    assert body["heartbeats"]["stale_after_seconds"] == 3600.0   # 6 * 600
    assert body["delivery"]["pass_interval_seconds"] == PASS_INTERVAL_S
```

Imports to add at the top of whichever file holds these: `datetime as dt`,
`DISPATCH_STALE_AFTER_SECONDS` and `create_app` from `chat_gateway.service`,
`PASS_INTERVAL_S`, `Dispatcher`, `DeliveryLog` from `chat_gateway.delivery`,
`Inbox` from `chat_gateway.inbox`, `TestClient` from `fastapi.testclient`. Reuse
the file's existing `_client()` / `_registry()` helpers rather than writing new
ones.

---

## Task A7 · Docs

- `CLAUDE.md` — **no new bullet.** Add one clause to the existing CG-12 /
  `/healthz` material only if a reviewer asks; the endpoint's field list has no
  home in `CLAUDE.md` today and creating one is the two-homes trap.
- `docs/integration-guide.md` — if it documents `/healthz`'s body, add the new
  fields there. **Measure first** (`grep -n "thread_alive\|last_poll_at"
  docs/integration-guide.md`); do not add a section that does not exist.
- `docs/BUILDER_QUEUE.md` — mark CG-72 done, record the measured suite delta.

## Part A verification

```
python3 -m pytest -q            # expect 314 + the six above = 320
grep -c "thread_alive" src/chat_gateway/service.py     # 8 -> 12
git diff main -- src/ | grep -c "LIVE-UNVERIFIED\|SHAPE-VERIFIED"   # must be 0
```

---

# Part B — CG-71 · One shutdown path, in the one place that runs

Branch from a merged Part A.

## Task B1 · `start()` idempotency, all four classes

**Files:** `delivery.py`, `heartbeat.py`, `retention.py`, `adapters/pubsub.py`.

The identical edit in each. Shown for `Dispatcher`; apply verbatim, adjusting
only the thread name and the class named in the message:

```python
    def start(self) -> None:
        """Idempotent while running; REFUSES to restart after a stop.

        Two different hazards, and only one of them is fixed here.

        Calling `start()` twice built a SECOND thread and overwrote
        `self._thread`, orphaning the first — it kept running and was no longer
        reachable by `stop()`. Two dispatchers is two sends of every job.
        Returning early is the whole fix.

        `start()` AFTER `stop()` is the other one, and it is made LOUD rather
        than made to work. `_stop` is never cleared, so the new thread's
        `while not self._stop.is_set()` exited on its first evaluation: the
        caller got a `start()` that returned normally, a `started` of True, and
        a dead thread. Clearing `_stop` here would 'fix' it by inventing restart
        semantics for a component that has abandoned in-flight work — out of
        scope by decision (spec §5.3). A caller who wants a fresh loop builds a
        fresh object, which is what `__main__` does.
        """
        if self._thread is not None and self._thread.is_alive():
            return
        if self._stop.is_set():
            raise RuntimeError(
                "Dispatcher.start() after stop(): this loop cannot be restarted; "
                "construct a new one"
            )
        self._thread = threading.Thread(target=self._run, name="delivery-dispatcher", daemon=True)
        self._started = True
        self._thread.start()
```

For `RetentionSweeper` and `SubscriberLoop`, keep their existing `self._started = True`
placement (before `self._thread.start()`) — it is already correct. For
`HeartbeatMonitor` and `Dispatcher`, Part A added it.

⚠ **`stop()` is not touched in any of the four.** Spec §2.7 measured it as
already idempotent and already safe on a never-started component, and that is
precisely what lets B2 call it unconditionally.

## Task B2 · The lifespan shutdown hook

**File:** `src/chat_gateway/service.py`

Add to the imports at the top:

```python
import contextlib
```

Inside `create_app`, **replace** the `app = FastAPI(...)` construction (line 171)
with the hook plus the constructor:

```python
    @contextlib.asynccontextmanager
    async def _lifespan(app: FastAPI):
        yield
        # -- shutdown ---------------------------------------------------------
        # THE ONLY HOOK THAT RUNS. Measured, 2026-08-02, against uvicorn 0.42:
        # `Server.capture_signals` restores the DEFAULT signal disposition and
        # then re-raises the captured signal, so on SIGTERM the process dies
        # inside `uvicorn.run()` and never returns. A `try/finally` in
        # `__main__`, an `atexit` hook, and the code after `uvicorn.run(...)`
        # were all confirmed NOT to execute; the ASGI lifespan shutdown ran,
        # because it happens inside `serve()` before that re-raise. Do not
        # "simplify" this into a finally block in `__main__` — that is the
        # obvious shape, it reviews cleanly, and it is a silent no-op.
        #
        # STOP-ONLY, deliberately asymmetric with start(). Starting here would
        # spawn four real threads in every test that enters an app context, and
        # would move `__main__`'s boot ordering — restore, then boot-sweep, then
        # start, which CG-68 comments at length about getting right — into the
        # ASGI lifecycle where it is no longer readable top to bottom.
        #
        # UNCONDITIONAL on all four, which is safe because every `stop()` is a
        # no-op on a component that was never started: it sets an Event nobody
        # is waiting on, and `if self._thread:` skips the join.
        for component in (dispatch, monitor, subscriber, app.state.sweeper):
            if component is None:
                continue
            try:
                component.stop()
            except Exception as exc:  # noqa: BLE001 — one bad stop must not skip the rest
                # Never `{exc}`: CG-29's allowlist governs what a failure may
                # print, and nothing here knows what type this is.
                print(f"shutdown: {type(component).__name__}.stop() failed "
                      f"({describe_exception(exc)})", flush=True)

    app = FastAPI(
        title="chat-gateway",
        version=__version__,
        description=(
            "First-class chat identities for agentic applications. Apps render "
            "their own content; the gateway owns identity, delivery, threading, "
            "notifications, dead-man checks, and inbound reply routing."
        ),
        lifespan=_lifespan,
    )
```

Two notes for the implementer:

- `dispatch` is bound at line 167, before the constructor. `monitor` is bound at
  line 210, **after** it — that is fine and intended: `_lifespan` is a closure
  over `create_app`'s scope and resolves `monitor` when it *runs*, which is long
  after `create_app` has returned. Do not restructure `create_app` to move the
  monitor up; do not read `dispatch`/`monitor` off `app.state` instead (they are
  there, but `subscriber` is not, and mixing the two sources is how the fifth
  thread gets forgotten).
- `app.state.sweeper` rather than the `sweeper` parameter, purely for symmetry
  with how `/healthz` reads it. Either works; pick one and do not mix.

Add the import for `describe_exception` if `service.py` does not already have it:

```python
from .errors import describe_exception
```

(Check first — `grep -n "describe_exception" src/chat_gateway/service.py`.)

## Task B3 · `__main__` — say that the stops exist elsewhere

**File:** `src/chat_gateway/__main__.py`

The four `.start()` calls do not move. Add, immediately before
`uvicorn.run(...)` on line 189:

```python
        # The matching stops are NOT here, and the asymmetry is deliberate
        # (CG-71). `uvicorn.run()` does not return on SIGTERM — uvicorn restores
        # the default disposition and re-raises, so the process dies inside this
        # call. Anything written after it, in a `finally` around it, or in an
        # `atexit` hook does not run; all three were measured. The shutdown path
        # is the ASGI lifespan hook in `create_app`, which is the one hook that
        # executes before that re-raise.
```

## Task B4 · Tests

**File:** `tests/test_lifecycle.py` (new).

```python
def test_the_lifespan_shutdown_stops_every_thread_it_was_given():
    """`with TestClient(app)` is what runs lifespan — a bare one does not.

    All 23 pre-existing TestClient constructions in this suite are bare, which
    is why this hook is invisible to them and why this test must opt in.
    """
    sweeper = RetentionSweeper("", days=0)
    app = create_app(_registry(), Inbox(), {}, sweeper=sweeper)
    dispatch, monitor = app.state.dispatcher, app.state.monitor
    dispatch.start()
    monitor.start()
    sweeper.start()
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert dispatch.is_alive() and monitor.is_alive() and sweeper.is_alive()
    assert not dispatch.is_alive()
    assert not monitor.is_alive()
    assert not sweeper.is_alive()


def test_shutdown_is_a_no_op_on_components_that_were_never_started():
    """The 23 bare apps' shape, entered as a context manager anyway."""
    app = create_app(_registry(), Inbox(), {})       # no sweeper, no subscriber
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
    assert app.state.dispatcher.is_alive() is False


def test_a_second_start_does_not_orphan_the_first_thread():
    d = Dispatcher({}, DeliveryLog())
    d.start()
    try:
        first = d._thread
        d.start()
        assert d._thread is first, "a second start() built a second thread"
    finally:
        d.stop()


def test_start_after_stop_raises_rather_than_returning_a_dead_thread():
    """The silent-failure half of the idempotency finding."""
    d = Dispatcher({}, DeliveryLog())
    d.start()
    d.stop()
    with pytest.raises(RuntimeError, match="cannot be restarted"):
        d.start()


@pytest.mark.parametrize("make", [
    lambda: Dispatcher({}, DeliveryLog()),
    lambda: HeartbeatMonitor(HeartbeatStore(), lambda *a: None),
    lambda: RetentionSweeper("", days=0),
])
def test_stop_without_start_and_double_stop_are_both_safe(make):
    """What lets the lifespan hook call stop() unconditionally on all four."""
    c = make()
    c.stop()
    c.stop()
    assert c.is_alive() is False


def test_a_failing_stop_does_not_prevent_the_others(capsys):
    """One bad component must not leave three threads running."""
    class Bad:
        def stop(self): raise RuntimeError("nope")
    app = create_app(_registry(), Inbox(), {}, subscriber=Bad())
    dispatch = app.state.dispatcher
    dispatch.start()
    with TestClient(app):
        pass
    assert dispatch.is_alive() is False
    out = capsys.readouterr().out
    assert "Bad.stop() failed" in out
    assert "nope" not in out, "CG-29: an unmarked exception prints by type only"
```

`SubscriberLoop` is deliberately absent from the parametrize list — constructing
one needs a puller, and `tests/test_pubsub.py`'s existing fakes are the right
place for its copy of that assertion. Add it there rather than importing a fake
across test files.

## Task B5 · Docs

- `CLAUDE.md` — **one short bullet is warranted here**, because the uvicorn
  re-raise is a non-obvious property of the runtime that a future session will
  otherwise re-derive or get wrong. Keep it to the fact and its consequence; do
  not restate the measurement (it lives in this plan's spec, §2.2).
- `docs/BUILDER_QUEUE.md` — mark CG-71 done, record the measured suite delta.

## Part B verification

```
python3 -m pytest -q
grep -n "\.stop()" src/chat_gateway/service.py     # the hook exists
git diff main -- src/chat_gateway/adapters/ | wc -l   # expect only start() in pubsub.py
git diff main | grep -c "LIVE-UNVERIFIED\|SHAPE-VERIFIED"   # must be 0
```

**UAT, and it must be a real process — a unit test cannot prove B2.** Run
`python3 -m chat_gateway serve` against a scratch state dir, `kill -TERM` it, and
confirm the shutdown hook's effects appear before the process dies. If nothing
appears, the hook is in the wrong place and §2.2 is the reason.

---

# Plan self-review

- **Spec coverage** — §4 → Tasks A1–A6; §5.1/5.2 → B2; §5.3 → B1; §5.4 →
  the ⚠ notes in A1, A2, B1 and both verification blocks. §6 (CG-70) and §7
  (CG-73) are queue rows, deliberately not tasks here.
- **Placeholders** — none. Every task carries literal code; no "as above", no
  "similar to Task N". The three places that say *measure first* (A7's
  integration-guide grep, B2's `describe_exception` import check, B1's per-class
  thread names) are instructions to check an anchor, not deferred decisions.
- **Type consistency** — `last_pass_at` is `dt.datetime | None`, matching
  `last_poll_at`, `last_sweep_at` and `last_scan_at`; both new `interval_seconds`
  are `float`, matching the two existing ones; `started` is `bool`.
- **Anchors** — line numbers cited (42, 72, 88, 167, 171, 189, 210) are against
  `36fac22`. Part B branches from a merged Part A and **its line numbers will
  have moved**; every Part B anchor is also given by symbol name for that reason.
