# Delivery write-path robustness — implementation plan

**Spec:** [`2026-08-03-delivery-write-path-robustness-design.md`](../specs/2026-08-03-delivery-write-path-robustness-design.md)
**Baseline:** `main` at `696a8cd`, suite **324 passing** (re-measured, not quoted).
**Rows:** Part A = **CG-75**, Part B = **CG-74**. **Two PRs, A first.**

⚠ **Read spec §3 before Part A and spec §5 before Part B.** Part A's guard goes
**inside** `DeliveryLog.record`, around the file block only — not around the call
sites. Part B's `scan_failures` is deliberately **cumulative and degrading**
while its dispatcher twin is not; that asymmetry is measured (spec §2.4) and must
not be smoothed for symmetry.

⚠ **Parts A and B touch the same two functions and the same two `/healthz`
strings. They must not run concurrently.** A lands, merges, then B branches from
it — the same constraint CG-71/CG-72 carried.

⚠ **No ⚠ verification-ledger flag may be cleared, added or reworded by either
part.** Nothing here changes what an adapter sends, receives, retries or prints.
`adapters/` and `docs/architecture/` are off-limits.

⚠ **`_finish`'s mid-flight comment (`delivery.py:297–301`) must not be edited by
either part.** The log record precedes the `close` on purpose; spec §6.

---

# Part A — CG-75 · the unguarded write that becomes a send storm

## Task A1 · `DeliveryLog` guards its own file write and counts the failure

**File:** `src/chat_gateway/delivery.py`

Add the import beside the existing one (currently `from .journal import
chmod_owner_only`):

```python
from .errors import describe_exception
from .journal import chmod_owner_only
```

⚠ **Do not opportunistically convert the other `{exc}` sites in this file while
you are here.** `_journal_write`'s print and the two interpolations that persist
into the delivery log (`process_due`'s `"attempt {job.attempts}: {exc}"` and
`_finish`'s `"gave up after {job.attempts} attempts: {exc}"`) are **CG-73**, a
separate row with its own review. Touching them here makes this PR's diff
un-reviewable against its own row.

Replace `DeliveryLog.__init__` (currently lines 79–83) with:

```python
    def __init__(self, audit_dir: str | Path | None = None, keep: int = 200):
        self._entries: dict[str, deque[dict]] = defaultdict(lambda: deque(maxlen=keep))
        self._lock = threading.Lock()
        self._audit_dir = Path(audit_dir) if audit_dir else None
        self._ids = itertools.count(1)
        #: Audit-file writes that FAILED. The delivery-log twin of
        #: `Dispatcher.journal_write_errors`, and it exists for the identical
        #: reason: raising on this path turned a full disk into an unbounded
        #: re-send storm against Google (CG-75). Surfaced at /healthz because a
        #: forensic record that has silently stopped being written is worse than
        #: none, since it is trusted (hard rule #5).
        #:
        #: CUMULATIVE and never reset. A line that did not reach disk is never
        #: written by a later pass — the same test `RetentionSweeper.errors`
        #: applies to a file the OS refused to unlink: there is nothing for a
        #: later pass to recover from, so a counter that could return to zero
        #: would be a lie about a permanent loss.
        self.audit_write_errors = 0
```

Replace the body of `record` from `if self._audit_dir:` through the `return`
(currently lines 94–107) with:

```python
        if self._audit_dir:
            # GUARDED, and the guard is INSIDE this method around the FILE half
            # only — not around the call sites (CG-75).
            #
            # The placement is what makes swallowing cheap, and it is a property
            # of the two lines above rather than a hope: the in-memory ring
            # buffer has ALREADY been appended to under `self._lock`, so
            # `query()` — and therefore `GET /v1/deliveries` — still answers
            # "did this alert reach Chat?" correctly for the life of the
            # process. What is lost is the on-disk copy, not the answer.
            #
            # WHAT RAISING COST, measured rather than argued (spec §2.2): one
            # enqueued notification, one successful send, then a full disk
            # produced SIXTY sends to Google in sixty seconds, because the
            # OSError escaped `_finish` before the job left `_jobs` and the
            # delivered path never advances `next_attempt_at`. `_journal_write`'s
            # docstring has always said raising here would do exactly that; this
            # was the one write on the path that never got the guard, and
            # `service._journal_write_errors` says the same thing from the other
            # end ("raising there would turn a full disk into a re-send storm").
            #
            # WHAT SWALLOWING COSTS, kept here rather than only in the spec:
            # (1) this entry's on-disk delivery record is gone for good — and
            # `journal.py` is explicit that the per-app audit files cannot
            # substitute, because they record what ARRIVED, never what LEFT;
            # (2) the job now reaches `_finish`'s `close`, which on a full disk
            # also fails and is also counted, so the journal entry stays open
            # and REPLAYS at the next boot — possibly delivering twice. That is
            # the identical at-least-once trade `_journal_write` already blessed
            # ("at most one duplicate on the next boot"), and one duplicate at
            # next boot beats one send per second indefinitely.
            #
            # NOT a reason to relax `enqueue`'s journal `open`, which stays
            # unguarded: refusing work we cannot persist belongs to the
            # DURABILITY mechanism, not to the audit trail. On a genuinely full
            # disk `enqueue` still 500s and the consumer's fallback log still
            # takes over. This guard does not hide a full disk — it stops work
            # that was already accepted from storming.
            try:
                self._audit_dir.mkdir(parents=True, exist_ok=True)
                path = self._audit_dir / f"deliveries-{source}-{now.date().isoformat()}.jsonl"
                # CG-65 / ADR-0002 D5. Titles-only, so this is a smaller exposure
                # than the inbox audit — but `title[:200]` and `detail[:300]` can
                # still carry sensitive state (aitrader Feature 3 is the reason this
                # class is titles-only in the first place), and there is no reason
                # for it to be the one artifact under the state dir left at 0644.
                existed = path.exists()
                with path.open("a", encoding="utf-8") as fh:
                    if not existed:
                        chmod_owner_only(path)
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as exc:  # noqa: BLE001 — the audit degrades, delivery does not stop
                self.audit_write_errors += 1
                # `describe_exception`, not an f-string on the exception (hard
                # rule #2 via CG-29's allowlist). `str(OSError)` embeds the
                # ABSOLUTE path — `retention.py` measured exactly that — and
                # `OSError` is not a class `errors.py` marks, so this prints the
                # type name alone. Deliberately lossy: `ENOSPC` and `EACCES`
                # read identically here. Widening the allowlist would recover it
                # and is its own decision, not this row's (spec §5).
                print(f"delivery log: audit write FAILED ({describe_exception(exc)}); "
                      "this delivery's on-disk record is lost. The in-memory ring "
                      "buffer still has it until restart", flush=True)
        return entry_id
```

## Task A2 · `/healthz` publishes `audit_write_errors` and degrades on it

**File:** `src/chat_gateway/service.py`

Add the helper immediately after `_journal_write_errors` (currently ends line
167):

```python
def _audit_write_errors(dispatch, log) -> int:
    """Delivery-log audit writes that FAILED, across every log /healthz can reach.

    Two owners rather than one, for the reason `_journal_write_errors` has two —
    and here the second is not hypothetical. `create_app` builds its own
    `DeliveryLog` when none is injected (`log = delivery_log or DeliveryLog()`),
    while an injected `dispatcher` carries whichever log IT was built with, and
    `create_app(dispatcher=Dispatcher(adapters, other_log))` is a shape the
    tests already build. Reading one of the two would report zero while the
    other was losing records.

    Deduped by IDENTITY, so the ordinary case — one object doing both jobs — is
    not double-counted. `getattr` with a default, like its sibling, so an
    injected test double without the attribute reads as zero rather than
    breaking the endpoint (CG-68 audit F0 is what an unconditional lookup on
    this endpoint costs).
    """
    seen: dict[int, object] = {}
    for owner in (getattr(dispatch, "delivery_log", None), log):
        if owner is not None:
            seen[id(owner)] = owner
    return sum(getattr(owner, "audit_write_errors", 0) for owner in seen.values())
```

Give `Dispatcher` the public accessor that helper reads. **File:**
`src/chat_gateway/delivery.py`, immediately after the existing `journal`
property:

```python
    @property
    def delivery_log(self):
        """The delivery log this dispatcher writes through.

        Public for the reason `journal` above is: /healthz has to read a counter
        off it and must not reach through a private attribute across a module
        boundary. It is NOT necessarily the same object as `create_app`'s own
        `log` — an injected dispatcher brings its own — which is exactly why
        `service._audit_write_errors` sums over both.
        """
        return self._log
```

Back in `service.py`, add the body field to the `delivery` block, immediately
after the `"journal_write_errors"` line (currently 434):

```python
                         # CG-75. Audit-file writes that failed. Sibling of the
                         # line above and counted for the same reason: this
                         # write used to RAISE, which turned a full disk into an
                         # unbounded re-send storm. It no longer raises, so this
                         # counter is the only thing that says so.
                         "audit_write_errors": _audit_write_errors(dispatch, log),
```

Add the degrade reason immediately after the `journal_write_errors` reason
(currently ends line 645):

```python
        if queue["audit_write_errors"]:
            reasons.append(
                f"delivery log: {queue['audit_write_errors']} audit write(s) "
                "FAILED since start — those deliveries have NO on-disk record, "
                "and the per-app inbound audit files cannot substitute because "
                "they record what arrived, never what left. Delivery itself is "
                "unaffected (the write is deliberately swallowed rather than "
                "raised, CG-75). CUMULATIVE and will not clear while this "
                "process runs. Check free space and the state dir's permissions"
            )
```

## Task A3 · Correct the two `/healthz` strings this fix falsifies

**File:** `src/chat_gateway/service.py`

**A3a — the explanatory block above the delivery chain.** Replace the paragraph
that currently begins `# REACHABLE, not theoretical:` (lines 764–775) with:

```python
        # REACHABLE, and it WAS reachable through this exact door until CG-75.
        # `DeliveryLog.record` did a raw `mkdir`/`open`/`write` with no guard, so
        # a full disk raised `OSError` straight out of `process_due` — and only
        # on passes that HAD work. Measured at the time: one message, one
        # successful send, then sixty sends to Google in sixty seconds, because
        # the job never left `_jobs` and the delivered path never advances
        # `next_attempt_at`. On the RETRY path the opposite: the raise landed
        # after the backoff had already been applied, so the job sat 30s or more
        # from its next attempt, every pass in between was empty, every empty
        # pass stamped, and this branch did not fire for the whole 72.5-minute
        # backoff ladder.
        #
        # CG-75 closed that door: the audit write is guarded inside
        # `DeliveryLog.record` and counted at `delivery.audit_write_errors`,
        # which degrades. A full disk now shows up there and at
        # `journal_write_errors`, not as a storm and not as silence.
        #
        # WHAT IS STILL UNRESOLVED is why these two strings are hedged, and it
        # is narrower than it was: `Dispatcher` and `HeartbeatMonitor` count no
        # failed passes at all, so if something ELSE raises out of the loop this
        # endpoint still cannot tell a wedged loop from a raising one. Adding
        # those counters is CG-74, filed by this row's Builder off this row's own
        # review: it is a new degrade input on an endpoint consumers alarm on,
        # which is a decision, not a wording fix. Until it lands, honest
        # ambiguity beats a confident wrong answer — and when it lands, BOTH
        # strings below must lose their "counts no failures" clause, which is why
        # that clause names the gap rather than merely hedging.
```

**A3b — the delivery staleness string.** Its last sentence names a mechanism
this PR removes. Replace the reason body (currently 804–815) with:

```python
            reasons.append(
                f"delivery: the thread is alive but the last completed pass was "
                f"{queue['seconds_since_last_pass']}s ago, over the "
                f"{queue['stale_after_seconds']}s budget — so the loop is "
                "either WEDGED or RAISING on every pass, and nothing in this "
                "block can tell you which, because it counts no failures. The "
                "gateway's console can: a wedged pass is silent, a raising one "
                "prints `dispatcher: pass error (will retry)` once a second. A "
                "send blocked past its client timeout is the wedged shape. A "
                "full disk is NOT the other one any more — since CG-75 it "
                "raises nowhere in this loop and reports at "
                "`audit_write_errors` and `journal_write_errors` instead"
            )
```

**A3c — the heartbeat staleness string.** Its full-disk claim stays true but
names the wrong file. Replace the tail of the reason body (currently 834–845)
with:

```python
            reasons.append(
                f"heartbeats: the thread is alive but the last completed scan "
                f"was {hb['seconds_since_last_scan']}s ago, over the "
                f"{hb['stale_after_seconds']}s budget for a "
                f"{hb['scan_interval_seconds']}s-interval loop — so the "
                "dead-man monitor is either WEDGED or RAISING on every scan, "
                "and nothing in this block can tell you which, because it "
                "counts no failures. The gateway's console can: a raising scan "
                "prints `heartbeat: scan error (will retry)` once an interval. "
                "A full disk still raises through a scan that fires a check — "
                "but through `enqueue`'s journal write, which is unguarded on "
                "purpose, NOT through the delivery log, which CG-75 guarded. An "
                "idle scan stamps either way"
            )
```

## Task A4 · Tests

**File:** `tests/test_delivery.py` (or wherever the existing `Dispatcher` tests
live — put these beside them, do not start a new file).

```python
class _FullDiskLog(DeliveryLog):
    """A DeliveryLog whose audit file write fails, exactly as a full disk would.

    Subclasses rather than monkeypatching `Path`, so the guard being tested is
    the real one in the real method.
    """

    def __init__(self, tmp_path):
        super().__init__(audit_dir=tmp_path / "deliveries")
        self.fail = False

    def _write_audit(self, *a, **k):  # pragma: no cover - see note below
        raise AssertionError("unused; the failure is injected via audit_dir")


def _breaking_log(tmp_path, monkeypatch):
    """A real DeliveryLog whose audit directory cannot be created."""
    log = DeliveryLog(audit_dir=tmp_path / "deliveries")
    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(Path, "mkdir", boom)
    return log


def test_a_failing_audit_write_does_not_raise_out_of_record(tmp_path, monkeypatch):
    log = _breaking_log(tmp_path, monkeypatch)
    entry_id = log.record("aitrader", "notify", "t", "delivered")
    assert isinstance(entry_id, int)
    assert log.audit_write_errors == 1


def test_a_failing_audit_write_still_populates_the_in_memory_ring(tmp_path, monkeypatch):
    """The whole reason swallowing is cheap: the answer survives, the file does not."""
    log = _breaking_log(tmp_path, monkeypatch)
    log.record("aitrader", "notify", "close-of-day", "delivered")
    entries = log.query("aitrader")
    assert len(entries) == 1 and entries[0]["status"] == "delivered"


def test_a_failing_audit_write_does_not_resend_the_job(tmp_path, monkeypatch):
    """CG-75, the whole row. Pre-fix this was 60 sends in 60 passes — measured.

    One enqueued notification, one successful send, then the disk fills. Every
    subsequent pass must send NOTHING.
    """
    log = DeliveryLog(audit_dir=tmp_path / "deliveries")
    adapter = _CountingAdapter()
    clock = _Clock(dt.datetime(2026, 8, 3, tzinfo=dt.timezone.utc))
    d = Dispatcher({"webhook": adapter}, log, now_fn=clock)
    d.enqueue("aitrader", "notify", _IDENTITY, _MESSAGE, "t")

    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(Path, "mkdir", boom)

    for _ in range(60):
        d.process_due()                      # must not raise
        clock.advance(seconds=1)

    assert adapter.sends == 1, "the delivered job was re-sent"
    assert d.pending() == 0, "the job never left _jobs"
    assert log.audit_write_errors >= 1
    assert d.last_pass_at is not None, "a raising pass never stamps"


def test_a_failing_audit_write_on_the_retry_path_keeps_the_backoff(tmp_path, monkeypatch):
    """The other half of the measurement (spec §2.3): the ladder must still work.

    Pre-fix this path did not storm for 72.5 minutes and then did. Post-fix the
    send count over the whole ladder is exactly the ladder.
    """
    log = DeliveryLog(audit_dir=tmp_path / "deliveries")
    adapter = _CountingAdapter(fail=True)
    clock = _Clock(dt.datetime(2026, 8, 3, tzinfo=dt.timezone.utc))
    d = Dispatcher({"webhook": adapter}, log, now_fn=clock)
    d.enqueue("aitrader", "notify", _IDENTITY, _MESSAGE, "t")

    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(Path, "mkdir", boom)

    for _ in range(6000):
        d.process_due()
        clock.advance(seconds=1)

    assert adapter.sends == len(BACKOFF_S), (
        f"expected exactly {len(BACKOFF_S)} attempts, got {adapter.sends}")
    assert d.pending() == 0


def test_enqueue_still_refuses_work_it_cannot_journal(tmp_path, monkeypatch):
    """The guard must NOT have relaxed the refuse-the-work posture (spec §3)."""
    class _FullDiskJournal:
        def open(self, *a, **k):
            raise OSError(28, "No space left on device")
        def replay(self):
            return []
    log = DeliveryLog()
    d = Dispatcher({"webhook": _CountingAdapter()}, log,
                   journal=_FullDiskJournal())
    with pytest.raises(OSError):
        d.enqueue("aitrader", "notify", _IDENTITY, _MESSAGE, "t")
```

**File:** `tests/test_service.py`

```python
def test_audit_write_errors_is_published_and_degrades(env):
    client, _inbox, _adapter = env
    body = client.get("/healthz").json()
    assert body["delivery"]["audit_write_errors"] == 0

    client.app.state.delivery_log.audit_write_errors = 2
    body = client.get("/healthz").json()
    assert body["delivery"]["audit_write_errors"] == 2
    assert body["status"] == "degraded"
    hits = [r for r in body["reasons"] if r.startswith("delivery log: ")]
    assert len(hits) == 1 and "NO on-disk record" in hits[0]


def test_audit_write_errors_sums_a_dispatcher_carrying_its_own_log(env_factory):
    """`_audit_write_errors`'s second owner is not hypothetical — spec §5.

    An injected dispatcher brings its own DeliveryLog; `create_app` builds a
    different one when `delivery_log` is not also passed. Reading either alone
    reports zero while the other is losing records.
    """
    other = DeliveryLog()
    other.audit_write_errors = 3
    client = env_factory(dispatcher=Dispatcher({}, other))
    assert client.get("/healthz").json()["delivery"]["audit_write_errors"] == 3


def test_the_delivery_staleness_reason_no_longer_blames_a_full_disk(env):
    """Rule #5: CG-75 makes the old example false, so it must not still be there."""
    client, _inbox, _adapter = env
    dispatch = client.app.state.dispatcher
    dispatch.process_due = lambda: 0
    dispatch.start()
    try:
        dispatch.last_pass_at = (dt.datetime.now(dt.timezone.utc)
                                 - dt.timedelta(seconds=DISPATCH_STALE_AFTER_SECONDS + 60))
        hits = [r for r in client.get("/healthz").json()["reasons"]
                if r.startswith("delivery: ")]
        assert len(hits) == 1
        assert "either WEDGED or RAISING" in hits[0]
        assert "audit_write_errors" in hits[0]
        assert "a full disk, which makes the delivery log's own write raise" not in hits[0]
    finally:
        dispatch.stop()
```

⚠ The two existing tests at `tests/test_service.py:1038` and `:1067` assert
`"either WEDGED or RAISING" in hits[0]`. Both substrings survive A3b/A3c
unchanged — **verify that rather than assuming it**; if either breaks, the
replacement string is wrong, not the test.

## Task A5 · Docs

**File:** `docs/integration-guide.md`

Add a row to the `/healthz` field table immediately after
`delivery.journal_write_errors` (line 454):

```
| `delivery.audit_write_errors` | delivery-log **audit file** writes that failed since start. Those deliveries have no on-disk record at all, and the per-app inbound audit files cannot substitute — they record what **arrived**, never what **left**. Delivery itself keeps working: this write is swallowed rather than raised, because raising it turned a full disk into an unbounded re-send storm against Google. **Cumulative and does not reset** — a line that never reached disk is never written by a later pass | **yes** |
```

⚠ **Recount, do not increment.** The sentence beginning *"Seventeen degrading
fields"* (line 493) and the parenthetical tally at 504–512 both need updating,
and the guide's own instruction is to *"recount against `service.py`'s `reasons`
chain rather than trusting this sentence."* Do that. This row adds one degrading
field and one `reasons` entry.

⚠ Also check the bullet at 485–492 (*"Two of the `delivery.*` fields count both
queues"* / *"the other **nine**"*). `audit_write_errors` is a **third** summed
field — it sums across two `DeliveryLog` objects, not across two queues, which
is a different sense of "summed" and must be written as such rather than folded
into the existing sentence.

**File:** `CLAUDE.md` — no change. The durability bullet already states the
journal's posture; this row is the audit trail's, and spec §3 is its home.

---

# Part B — CG-74 · the failure counters the two threads never got

**Branches from Part A's merge commit.** Do not start it before A is on `main`.

## Task B1 · `Dispatcher` counts failed passes

**File:** `src/chat_gateway/delivery.py`

Add to `Dispatcher.__init__`, immediately after `journal_write_errors`:

```python
        #: Passes that RAISED, and passes that have raised since the last good
        #: one. CG-74, the counter half of CG-68's F3 — the liveness half
        #: shipped as CG-72 and left this block unable to tell a wedged loop
        #: from a raising one, which two `/healthz` strings said in words.
        #:
        #: TWO NUMBERS, and only the CONSECUTIVE one may drive `status`. The
        #: reasoning is `RetentionSweeper`'s, measured in its pre-merge review:
        #: a cumulative counter never returns to zero, so one transient failure
        #: that had already recovered pinned `degraded` for the life of the
        #: process. The cumulative one stays as history in the body.
        self.pass_failures = 0
        self.consecutive_pass_failures = 0
        #: The exception TYPE from the last failed pass, via
        #: `describe_exception` (hard rule #2 / CG-29's allowlist), following
        #: `RetentionSweeper.last_sweep_error`. Deliberately NOT
        #: `SubscriberLoop`'s hand-rolled format, which CLAUDE.md records must
        #: not be unified onto the helper and is therefore precedent for
        #: nothing new. Cleared on recovery, with the counter beside it.
        self.last_pass_error: str | None = None
```

Replace `_run` (currently lines 434–440) with:

```python
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_due()
                # RECOVERY CLEARS BOTH, and the second is what stops /healthz
                # degrading for the life of the process after a transient
                # failure. `RetentionSweeper._run` records the measurement:
                # clearing the error string while leaving a degrading counter
                # set is worse than not clearing it, because the reason line
                # then renders the cleared value as the literal "(None)".
                self.last_pass_error = None
                self.consecutive_pass_failures = 0
            except Exception as exc:  # noqa: BLE001 — the loop must survive
                # COUNTED, not just printed. A dispatcher throwing every pass
                # reported nothing at all and /healthz never degraded — the
                # founding rule-#5 failure with a different noun, and the same
                # finding audit F3 recorded against the sweeper.
                self.pass_failures += 1
                self.consecutive_pass_failures += 1
                self.last_pass_error = describe_exception(exc)
                print(f"dispatcher: pass error (will retry): "
                      f"{self.last_pass_error}", flush=True)
            self._stop.wait(PASS_INTERVAL_S)
```

⚠ This rewrite renders through `describe_exception` and therefore closes **one**
of CG-73's five sites. Say so in the PR body; do not touch the other four.

## Task B2 · `HeartbeatMonitor` counts failed scans

**File:** `src/chat_gateway/heartbeat.py`

Add the import:

```python
from .errors import describe_exception
```

Add to `HeartbeatMonitor.__init__`, immediately after `self.last_scan_at`:

```python
        #: Scans that RAISED, and scans that have raised since the last good
        #: one. `Dispatcher`'s twin — with ONE deliberate asymmetry, stated here
        #: rather than left for a reviewer to "fix":
        #:
        #: `scan_failures` is CUMULATIVE **and degrading**, where
        #: `Dispatcher.pass_failures` is cumulative and inert. A failed dispatch
        #: pass is recoverable — the due job is still in `_jobs` and the next
        #: pass retries it. A failed SCAN is not. `HeartbeatStore.due_alerts`
        #: marks the check (`status = "missed"`, `last_alerted = now`) under its
        #: lock BEFORE persisting, and `scan_once` only notifies what
        #: `due_alerts` returned — so a raise anywhere downstream leaves the
        #: check marked alerted and the alert never sent, suppressed for the
        #: whole `DEFAULT_REPEAT_S` window. Measured, both variants, including
        #: one that persists the suppression and survives a restart. That is
        #: `RetentionSweeper.errors`'s test — nothing for a later pass to
        #: recover from — so it takes `RetentionSweeper.errors`'s posture.
        #:
        #: THE COUNTER IS NOT THE FIX. **CG-76** is. Until it lands this is the
        #: only thing standing between a silently-dropped dead-man alert and a
        #: green /healthz on an unauthenticated endpoint.
        self.scan_failures = 0
        self.consecutive_scan_failures = 0
        #: See `Dispatcher.last_pass_error` — same helper, same reasoning.
        self.last_scan_error: str | None = None
```

Replace `_run` (currently lines 227–233) with:

```python
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
                # Only the CONSECUTIVE counter clears. `scan_failures` is
                # cumulative and degrading on purpose — see `__init__`: the
                # alert that scan would have sent is already gone.
                self.last_scan_error = None
                self.consecutive_scan_failures = 0
            except Exception as exc:  # noqa: BLE001 — the loop must survive
                self.scan_failures += 1
                self.consecutive_scan_failures += 1
                self.last_scan_error = describe_exception(exc)
                print(f"heartbeat: scan error (will retry): "
                      f"{self.last_scan_error}", flush=True)
            self._stop.wait(self._interval)
```

⚠ Closes a **second** CG-73 site. Same note in the PR body.

## Task B3 · `/healthz` publishes all six fields

**File:** `src/chat_gateway/service.py`

Add the threshold beside `POLL_FAILURE_THRESHOLD` (line 54):

```python
#: Consecutive raising passes before /healthz calls outbound delivery DOWN.
#:
#: Three, matching `POLL_FAILURE_THRESHOLD` and NOT the sweeper's implicit one,
#: and the difference is the loop interval rather than taste. The sweeper runs
#: every six hours, so one failed pass is already a real signal. This loop runs
#: every `PASS_INTERVAL_S` — one second — where a single transient blip should
#: not flip an alarm on an endpoint consumers page on. Three passes is three
#: seconds: the threshold costs nothing in detection time and buys the whole of
#: the anti-flap.
DISPATCH_FAILURE_THRESHOLD = 3

#: The same number for the scan loop, and it is NOT a copy for symmetry's sake:
#: `monitor_interval` is settable per deployment (`create_app`), so this is a
#: count of scans, not of seconds, exactly as the two above are.
SCAN_FAILURE_THRESHOLD = 3
```

Add to the `delivery` block, immediately after `"audit_write_errors"`:

```python
                         # CG-74. What `thread_alive` and `last_pass_at`
                         # together still could not say: whether a loop that has
                         # stopped completing passes is WEDGED or RAISING.
                         # Cumulative is history and drives nothing; consecutive
                         # returns to zero on the next good pass and is the one
                         # that degrades — `RetentionSweeper`'s split, for
                         # `RetentionSweeper`'s measured reason.
                         "pass_failures": getattr(dispatch, "pass_failures", 0),
                         "consecutive_pass_failures": getattr(
                             dispatch, "consecutive_pass_failures", 0),
                         "last_pass_error": getattr(dispatch, "last_pass_error", None),
```

Add to the `heartbeats` block, immediately after `"scan_interval_seconds"`:

```python
                           # CG-74. The dispatcher's twin, with one asymmetry:
                           # `scan_failures` DEGRADES cumulatively, because a
                           # scan that raised has already dropped the alert it
                           # was going to send and no later scan re-sends it.
                           # `HeartbeatMonitor.__init__` carries the measurement.
                           "scan_failures": getattr(monitor, "scan_failures", 0),
                           "consecutive_scan_failures": getattr(
                               monitor, "consecutive_scan_failures", 0),
                           "last_scan_error": getattr(monitor, "last_scan_error", None),
```

## Task B4 · The reason branches, and the two strings finally earn their wording

**File:** `src/chat_gateway/service.py`

**B4a — insert the counter branch into the delivery chain**, between the
dead-thread branch and the never-completed branch:

```python
        elif queue["thread_started"] and (
                queue["consecutive_pass_failures"] >= DISPATCH_FAILURE_THRESHOLD):
            reasons.append(
                f"delivery: {queue['consecutive_pass_failures']} consecutive "
                f"dispatch passes have RAISED (last: {queue['last_pass_error']}) "
                "— outbound is failing loudly rather than silently. Queued jobs "
                "are not being sent and `pending_jobs` will climb"
            )
```

⚠ **Ordering, and it deliberately does NOT match the subscriber's chain.** The
subscriber orders never-polled → counter → dead-thread → stale. This chain is
dead-thread → counter → never-completed → stale, because a dead thread
increments no counter and is the most actionable of the four (restart), while a
raising loop *explains* "no pass has ever completed" when it is the cause. Do
not "unify" the two orders in review — each is recorded where it is.

**B4b — the delivery staleness string** now has a counter branch above it, so it
may say what its siblings say. Replace the reason body from A3b with:

```python
            reasons.append(
                f"delivery: the thread is alive but the last completed pass was "
                f"{queue['seconds_since_last_pass']}s ago, over the "
                f"{queue['stale_after_seconds']}s budget, and fewer than "
                f"{DISPATCH_FAILURE_THRESHOLD} consecutive passes have raised — "
                "so passes are neither completing nor raising, and the loop is "
                "WEDGED rather than erroring. A send blocked past its client "
                "timeout is the shape: `process_due` walks due jobs "
                "sequentially, so one hung send holds the whole loop"
            )
```

**B4c — the heartbeat staleness string**, same treatment:

```python
            reasons.append(
                f"heartbeats: the thread is alive but the last completed scan "
                f"was {hb['seconds_since_last_scan']}s ago, over the "
                f"{hb['stale_after_seconds']}s budget for a "
                f"{hb['scan_interval_seconds']}s-interval loop, and fewer than "
                f"{SCAN_FAILURE_THRESHOLD} consecutive scans have raised — so "
                "scans are neither completing nor raising, and the dead-man "
                "monitor is WEDGED rather than erroring. No registered check is "
                "being evaluated while this holds"
            )
```

**B4d — insert the monitor's counter branch** into the heartbeat chain, in the
same position B4a used:

```python
        elif hb["thread_started"] and (
                hb["consecutive_scan_failures"] >= SCAN_FAILURE_THRESHOLD):
            reasons.append(
                f"heartbeats: {hb['consecutive_scan_failures']} consecutive "
                f"scans have RAISED (last: {hb['last_scan_error']}) — the "
                "dead-man monitor is not evaluating any registered check, so a "
                "source that has gone silent will never be alerted on"
            )
```

**B4e — the cumulative scan counter, as its own `if`, outside the chain.** It is
not a liveness signal and must be able to fire beside one:

```python
        # OUTSIDE the elif chain above, deliberately. The chain answers "is this
        # loop running", at most one reason. This answers a different question —
        # "has an alert already been lost" — and both can be true at once. It is
        # the one cumulative counter in these two blocks that degrades; the
        # asymmetry with `delivery.pass_failures` is recorded at
        # `HeartbeatMonitor.__init__` and is measured, not stylistic.
        if hb["scan_failures"]:
            reasons.append(
                f"heartbeats: {hb['scan_failures']} scan(s) have raised since "
                "start — a scan that raises after marking a check MISSED drops "
                "that alert for the repeat window (24h) and no later scan "
                "re-sends it, so at least one dead-man alert may already have "
                "been lost. CUMULATIVE and will not clear while this process "
                "runs; `consecutive_scan_failures` is the live signal"
            )
```

## Task B5 · Tests

**File:** `tests/test_delivery.py` and `tests/test_heartbeat.py`

```python
def test_a_raising_pass_is_counted_and_cleared_on_recovery():
    log = DeliveryLog()
    d = Dispatcher({}, log)
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError(28, "No space left on device")
        return 0
    d.process_due = flaky
    d.start()
    try:
        _wait_until(lambda: calls["n"] >= 4, timeout=5)
    finally:
        d.stop()
    assert d.pass_failures == 2
    assert d.consecutive_pass_failures == 0, "recovery must clear the consecutive counter"
    assert d.last_pass_error is None, "recovery must clear the error string"


def test_the_pass_error_is_a_type_name_never_a_path(tmp_path):
    """Hard rule #2: `str(OSError)` embeds the absolute path; this must not."""
    log = DeliveryLog()
    d = Dispatcher({}, log)
    secret = tmp_path / "very-secret-dir" / "x.jsonl"
    def boom():
        raise OSError(2, "No such file", str(secret))
    d.process_due = boom
    d.start()
    try:
        _wait_until(lambda: d.pass_failures >= 1, timeout=5)
    finally:
        d.stop()
    assert d.last_pass_error == "OSError"
    assert "very-secret-dir" not in (d.last_pass_error or "")


def test_a_raising_scan_is_counted_but_the_cumulative_one_never_clears():
    """The asymmetry, pinned. `scan_failures` must survive recovery."""
    store = HeartbeatStore()
    mon = HeartbeatMonitor(store, lambda *a: None, interval_seconds=0.01)
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError(28, "No space left on device")
        return 0
    mon.scan_once = flaky
    mon.start()
    try:
        _wait_until(lambda: calls["n"] >= 4, timeout=5)
    finally:
        mon.stop()
    assert mon.scan_failures == 2, "cumulative must NOT clear on recovery"
    assert mon.consecutive_scan_failures == 0
    assert mon.last_scan_error is None
```

**File:** `tests/test_service.py`

```python
def test_consecutive_pass_failures_degrade_at_the_threshold(env):
    client, _inbox, _adapter = env
    dispatch = client.app.state.dispatcher
    dispatch.consecutive_pass_failures = DISPATCH_FAILURE_THRESHOLD - 1
    dispatch.last_pass_error = "OSError"
    dispatch._started = True
    assert client.get("/healthz").json()["status"] == "ok"

    dispatch.consecutive_pass_failures = DISPATCH_FAILURE_THRESHOLD
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    hits = [r for r in body["reasons"] if r.startswith("delivery: ")]
    assert len(hits) == 1 and "consecutive dispatch passes have RAISED" in hits[0]


def test_pass_failures_alone_does_not_degrade(env):
    """Cumulative is history. Degrading on it would pin `degraded` forever."""
    client, _inbox, _adapter = env
    client.app.state.dispatcher.pass_failures = 99
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["delivery"]["pass_failures"] == 99


def test_cumulative_scan_failures_DO_degrade(env):
    """The deliberate asymmetry with the row above — a lost alert is not history."""
    client, _inbox, _adapter = env
    client.app.state.monitor.scan_failures = 1
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    hits = [r for r in body["reasons"] if r.startswith("heartbeats: ")]
    assert len(hits) == 1 and "may already have been lost" in hits[0]


def test_a_raising_and_a_wedged_monitor_produce_different_reasons(env):
    """The whole point of CG-74: these two were indistinguishable."""
    client, _inbox, _adapter = env
    mon = client.app.state.monitor
    mon._started = True
    mon.consecutive_scan_failures = SCAN_FAILURE_THRESHOLD
    mon.last_scan_error = "OSError"
    raising = [r for r in client.get("/healthz").json()["reasons"]
               if r.startswith("heartbeats: ") and "RAISED" in r]
    assert len(raising) == 1
```

⚠ **The two existing assertions at `tests/test_service.py:1038` and `:1067`
break here, and that is the row landing.** `"either WEDGED or RAISING"` becomes
`"WEDGED rather than erroring"`. Update both to the new substring — do **not**
weaken them to a shorter match.

⚠ Also re-check `tests/test_service.py:331` and `:556`, which assert `"wedged
rather than erroring"`. Those are the subscriber's and the sweeper's strings and
must be **untouched**; if either now matches a delivery or heartbeat reason as
well, the assertion needs a prefix filter, not a reworded string.

## Task B6 · Docs

**File:** `docs/integration-guide.md` — six rows into the field table.

After `delivery.pass_interval_seconds` (line 460):

```
| `delivery.pass_failures` | dispatch passes that **raised**, over the life of the process. History, not a live fault — read it beside the row below, which is the one that degrades | no — see the next row |
| `delivery.consecutive_pass_failures` | passes that have raised **since the last good one**, so it returns to `0` on recovery. This is what tells a **raising** dispatcher from a **wedged** one; until 2026-08-03 nothing here could, and the staleness reason said so in words | **yes** — at 3 |
| `delivery.last_pass_error` | the exception **type** from the last failed pass — a type name, never a path or a message. Companion to the row above, not an independent signal, and cleared on recovery | no — reported with the row above |
```

After `heartbeats.scan_interval_seconds` (line 481):

```
| `heartbeats.scan_failures` | scans that **raised**, over the life of the process — and unlike its `delivery.*` counterpart this one **degrades**. A scan that raises after marking a check `missed` has already dropped that alert for the 24h repeat window, and no later scan re-sends it, so this is a report of loss rather than of history. **Cumulative and does not reset** | **yes** |
| `heartbeats.consecutive_scan_failures` | scans that have raised **since the last good one**, returning to `0` on recovery. The live signal: the monitor is evaluating **no** registered check while this is climbing | **yes** — at 3 |
| `heartbeats.last_scan_error` | the exception **type** from the last failed scan. Companion to the row above; cleared on recovery | no — reported with the row above |
```

⚠ **Recount the two tallies again** (guide lines 493 and 504–512), against
`service.py`'s `reasons` chain, exactly as Part A did. This part adds six fields,
of which **three** degrade, and **three** `reasons` entries — but count it
yourself; a copied count is what `CLAUDE.md`'s test-count note is about.

⚠ **`CLAUDE.md`** — the `/healthz` honesty story now has a second chapter. Add
**one** sentence to the existing CG-12 / rule-#5 material pointing at this spec;
do **not** restate the counter table, which has one home in the integration
guide.

---

## Verification for both parts

```
python3 -m pytest -q          # POSIX; `python -m pytest` on the Windows box
```

Baseline **324**. Report both ends measured, never quoted.

**Rule #5 self-check before opening either PR** — every new field must have an
explicit verdict in the guide's degrade column, and the verdict must match the
`reasons` chain. Grep for the field name in `service.py` and confirm it either
appears in a `reasons.append` guard or is documented as `no`.

**Flag self-check** — this must print the same numbers before and after:

```
for d in CLAUDE.md src docs/architecture docs/consumers tests; do
  printf "%-22s %s\n" "$d" "$(grep -rEo 'LIVE-UNVERIFIED|SHAPE-VERIFIED' $d | wc -l)"
done
```

Baseline at `696a8cd`: `8 / 4 / 6 / 2 / 3`. (Counts **occurrences**, not lines —
`docs/architecture/decisions/2026-07-29-tier2-interaction-model.md:267` carries
two flag words on one line, which is why CG-72's banner recorded `5` for that
directory. Nothing moved then either; spec §2.5.)
