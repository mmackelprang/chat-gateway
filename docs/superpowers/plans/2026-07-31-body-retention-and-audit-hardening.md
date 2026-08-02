# Plan — CG-65 / CG-68: body retention and audit hardening

| | |
|---|---|
| **Spec** | [`2026-07-31-body-retention-and-audit-hardening-design.md`](../specs/2026-07-31-body-retention-and-audit-hardening-design.md) |
| **ADR** | [ADR-0002](../../architecture/decisions/2026-07-31-journalled-message-bodies.md) — `D + A + D5` |
| **Base** | Tasks 1–9: `dced002` (CG-61/#50), suite **247**. **Tasks 10–14: `4fbd634` (CG-65/#52), suite 268** |
| **Approved** | ✅ **four sign-offs granted by the user 2026-07-31, plus a fifth (A5) on 2026-08-02** — see the box below |
| **Rows** | **CG-65** = Tasks 1–9 — ✅ **shipped as #52**. **CG-68** = Tasks **10–14** — 📋 queued, gate released |
| **Corrected** | **2026-08-01** — Tasks 4 & 5 rewritten to match what shipped (a data-loss race their literal code contained), Tasks 10–12 amended from a pre-execution audit, **Task 14 added**. See the two ⚠ CORRECTED boxes and § *CG-68 pre-execution audit* |

> ## ✅ APPROVED — all four sign-offs granted by the user, 2026-07-31
>
> Recorded as **decisions, not open questions.** The reasoning is kept with each
> verdict, because a Builder needs the *why* — and because leaving "needs
> approval" text in an approved plan is the same drift CG-69 exists to catch.
>
> | # | Decision | Why — kept, not summarized away |
> |---|---|---|
> | **A1** | ✅ **The unrevivable quarantine is the answer to ADR-0002 §9 Q6.** Task 6 | It is **stronger than the guarantee it retires**. Today the gateway drops bytes it is **holding** (`rec["payload"]` is in hand at `inbox.py:130`), boot compaction erases its own copy moments later, and six places then point the operator at a `0644` file the sweeper is entitled to delete — **one of those six being a live `/healthz` `reasons` string**, which makes it hard rule #5, not documentation. Preserving the record costs one append and makes retention and recovery **independent** |
> | **A2** | ✅ **Retention: 30 days tenant / 7 days `_unrouted` / `0` disables**, via `CHAT_GATEWAY_INBOX_RETENTION_DAYS`. Task 10 | **30** because a calendar month is the unit a privacy posture and a subject-access request are written in, and — load-bearing — **`docs/integration-guide.md:370` already tells consumers this file is *"a forensic record on the gateway host, not something you can re-poll"***, so the gateway does **not** need to hold a consumer's decision history; a consumer needing it keeps its own. **7** for `_unrouted` per ADR §4.1: it answers to no tenant and has no consent story. **Time-bounded in days, never count-bounded** — ADR §2.2 is the reason |
> | **A3** | ✅ **Unlink, not redact.** Task 10 | The filename **is** the retention key, so pruning is a directory listing and an `unlink` — no parsing, and nothing ever opens a file holding message bodies to decide whether to delete it. Redaction needs field-by-field judgements about which parts of a person's message are sensitive, which is rule-#1 territory |
> | **A4** | ✅ **Amend the shared contract.** Task 13a | `integration-guide.md:366`'s *"never pruned"* was a v0 over-promise on a file holding a person's `text`, `sender_email` and whole `raw` event forever. It is owed to **every** consumer, not to jobhunt alone — which is why it was signed off explicitly rather than absorbed into a docs pass |
> | **A5** ⚠ *added **2026-08-02**, mid-execution* | ✅ **F2's boot guard REFUSES, not warns** — `_check_disjoint` stays stricter than the non-recursive glob strictly requires, so `CHAT_GATEWAY_INBOX_DIR=state` fails at boot. Task 10 | **This was Planner's own judgement call and is now the user's decision** — it sat outside A1–A4, phrased as a trade the plan had chosen, which is exactly the shape a reviewer softens. The reasoning the user accepted: *"currently harmless" depends on ONE LINE staying non-recursive.* A future `rglob` removes that safety silently, and **a warning nobody reads becomes tenant data loss.** Full wording at the ✅ box above Task 10's tests |
>
> **A2's rule-#1 note, so it is not relitigated in review:** the window is
> **global**. `_unrouted`'s shorter floor is the gateway governing **its own**
> reserved bucket (hard rule #6 reserves the `_` prefix), **not** per-app policy —
> a per-*tenant* window would be ADR-0002 Option C's shape and would re-open the
> question the user deliberately left **not reached** (D6).

> ⚠ **Builder: read this box first.**
>
> 0. ⚠ **THIS DOCUMENT WAS CORRECTED ON 2026-08-01 AND TASKS 1–9 ARE ALREADY
>    SHIPPED.** You are here for **Tasks 10–14** (CG-68). Tasks 1–9 are kept as
>    the record of what #52 built, **including two ⚠ CORRECTED boxes recording
>    that Tasks 4 and 5 shipped literal code that was wrong.** Read those boxes
>    before Task 10: the defect they describe is a *shape*, CG-68 touches the
>    same paths, and CG-68 **deletes tenant content** where CG-65 only compacted
>    replayable state. Then read § *CG-68 pre-execution audit*, which is the
>    verdict on whether Tasks 10–13 carried the same shape (**they did not**)
>    and the six neighbouring findings that are now folded into them.
> 1. ✅ **The sequencing gate is RELEASED.** It read *"CG-65 must MERGE first"*;
>    CG-65 merged 2026-07-31 as **#52** (`4fbd634`). Task 6's quarantine exists.
>    Nothing gates CG-68 now.
> 2. **No ⚠ flag may be cleared, added or reworded.** Nothing here touches
>    `adapters/` or any Google seam. Do not restate `CLAUDE.md`'s verification
>    ledger — link to it.
> 3. **Do not touch `docs/architecture/`.** The ADR is decided and is evidence.
>    ⚠ This is why **ADR-0002:463 still shows `compact([])`** even though that
>    line is now known to be a data-loss bug. It is labelled *"shape, not
>    implementation"* and is a dated record of what was believed on 2026-07-31.
>    **Do not fix it and do not copy from it.**
> 4. **Do not re-open ADR-0002 §6.**
> 5. Tests: `python3 -m pytest` on POSIX, `python -m pytest` on the Windows dev
>    box. Measure the final count; do not copy the estimate below.

---

# CG-65 — Tasks 1–9

## Task 1 — One home for the owner-only chmod primitive

`journal.py` already applies `0600` correctly — inside the `open()` context,
before the first write. Two more call sites now need it, so promote the helper
rather than copy it.

**`src/chat_gateway/journal.py`** — rename and re-document:

```python
def chmod_owner_only(path: Path) -> None:
    """Owner-only, best effort. Never fatal: a filesystem that cannot express
    the mode (a Windows dev box, an odd bind mount) is not a reason to refuse to
    write — the deploy runbook sets the directory mode, which is the control
    that actually holds on the Linux target.

    Public since CG-65: `inbox.py`'s audit trail and `delivery.py`'s delivery
    log were both created 0644 by doing nothing, and the fix is this exact
    primitive applied in this exact place — inside the `open()` context, before
    the first payload byte, so there is no window at 0644. One home, because a
    second copy of a security control is how the two drift apart.
    """
    try:
        os.chmod(path, _FILE_MODE)
    except OSError:
        pass
```

Update the **three** existing call sites in `journal.py` (`_append`,
`close_many`, `_compact_locked`) from `_chmod_quietly(...)` to
`chmod_owner_only(...)`. There is no alias — a private name kept alive beside
its public replacement is the drift this task exists to prevent.

Also update `_FILE_MODE`'s comment, which says "The journal carries message
bodies", to note it now governs the audit trails too:

```python
#: The journal and both audit trails carry message bodies or whole inbound
#: events (see the module docstring, and CG-65), so they are created owner-only.
#: A no-op for group/other on Windows, which is fine: the mode matters on the
#: Linux deploy target.
_FILE_MODE = 0o600
```

**Verify:** `python3 -m pytest tests/test_journal.py` stays green, and
`grep -rn "_chmod_quietly" src/` returns nothing.

---

## Task 2 — `0600` on the per-app inbound audit trail

The larger of the two exposures (ADR §2.5 finding 3): world-readable, and it
holds `text`, `sender_email` and whole `raw` events.

**`src/chat_gateway/inbox.py`** — add `os` to the imports, import the helper,
and rewrite `_audit`:

```python
import os
```

```python
from .journal import chmod_owner_only
```

```python
    def _audit(self, reply: InboundReply) -> None:
        if self._audit_dir is None:
            return
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        day = dt.date.today().isoformat()
        path = self._audit_dir / f"{reply.app}-{day}.jsonl"
        record = reply.model_dump(mode="json")
        # CG-65 / ADR-0002 D5. This file holds a human's `text`, `sender_email`
        # and whole `raw` event, and it was created 0644 by doing nothing while
        # the journal beside it — holding strictly less — was 0600. The chmod
        # goes INSIDE the open() context and BEFORE the first write, so there is
        # no window in which payload bytes sit world-readable. Same discipline
        # as journal.py; same primitive, not a second copy of it.
        existed = path.exists()
        with path.open("a", encoding="utf-8") as fh:
            if not existed:
                chmod_owner_only(path)
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
```

⚠ **Circular-import check.** `journal.py` imports nothing from `inbox.py`, so
this direction is safe. Confirm with
`python3 -c "import sys; sys.path.insert(0,'src'); import chat_gateway.inbox"`.

**Test** (`tests/test_durability.py`):

```python
def test_inbox_audit_file_is_owner_only_from_the_first_byte(tmp_path):
    """CG-65: the audit trail holds sender_email and raw; 0644 was the larger
    of the two on-disk exposures ADR-0002 measured."""
    ibx = Inbox(audit_dir=tmp_path / "inbox-data")
    ibx.put(_reply(app="job-hunter", text="APPROVE role 42"))
    audit = next((tmp_path / "inbox-data").glob("*.jsonl"))
    assert stat.S_IMODE(audit.stat().st_mode) == 0o600
    # and the mode survives a second append rather than being reset
    ibx.put(_reply(app="job-hunter", text="DECLINE role 43"))
    assert stat.S_IMODE(audit.stat().st_mode) == 0o600
```

---

## Task 3 — `0600` on the delivery log's audit trail

ADR **D7** scopes this file's *content* out (titles-only, permanent, by
decision) but its **mode** in.

**`src/chat_gateway/delivery.py`** — import the helper and rewrite the audit
block of `DeliveryLog.record`:

```python
from .journal import chmod_owner_only
```

```python
        if self._audit_dir:
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
```

**Test:**

```python
def test_delivery_audit_file_is_owner_only(tmp_path):
    log = DeliveryLog(audit_dir=tmp_path / "deliveries")
    log.record("aitrader", "notify", "HALT: AAPL", "enqueued")
    audit = next((tmp_path / "deliveries").glob("*.jsonl"))
    assert stat.S_IMODE(audit.stat().st_mode) == 0o600
```

---

## Task 4 — Compact the outbound journal on drain

ADR-0002 **D1**, off §4 Option D's sketch.

> ## ⚠ CORRECTED 2026-08-01 — this task's literal code contained a data-loss race
>
> **What this task told a Builder to write was wrong, and it was caught in
> review, not in production.** The correction is below; the wrong version and
> its counterfactual are kept here rather than edited away, because CG-68's
> Tasks 10–13 touch these same paths and a reader needs to know which pattern
> was rejected and why.
>
> **What the plan said:** `self._journal.compact([])`, annotated *"`compact([])`
> truncates the file to zero lines — measured, not assumed."* That measurement
> was true. The **conclusion drawn from it** was not.
>
> **The race.** `Dispatcher.enqueue` writes its journal `open` to disk **before**
> taking `self._lock` — deliberately, so a job that cannot be persisted is
> refused rather than queued. So a record can already be on disk while `drained`
> is being computed from the in-memory `_jobs`. `compact([])` **asserts** that
> the survivor set is empty. Passing that stale assertion erases a job
> `enqueue` had already answered `202` for.
>
> **The fix, shipped in #52:** `compact()` with **no argument** recomputes
> open-minus-close from the file itself, under the **journal's own** `RLock`
> (`journal.py:229` → `_compact_locked`), which `Journal.open` also holds. The
> two serialize: the racing record is either recomputed as a survivor and
> rewritten, or it lands after the `os.replace`. On a genuine drain it still
> truncates to zero lines, because everything really is closed.
>
> **The general rule, since CG-68 gets to re-learn it or not:** *never assert an
> emptiness or survivor set computed under one lock to a destructive operation
> protected by a different one.* Recompute under the lock that guards the thing
> you are about to destroy.
>
> **Two related things this correction did NOT change.** The honest-cost
> paragraph about a stuck job pinning other tenants' bodies is untouched and
> still true — it is a property of the drain gate, not of the survivor set.
> And **`docs/architecture/decisions/2026-07-31-journalled-message-bodies.md:463`
> still shows `compact([])`** — deliberately. That ADR block is labelled *"shape,
> not implementation"* and is **dated evidence of what was believed on
> 2026-07-31**, not instructions. Do not edit it (Builder box, item 3); do not
> copy from it either.
>
> Pinned by two tests that were confirmed to **fail** against `compact([])`.

**`src/chat_gateway/delivery.py::_finish`** — replace the whole method:

```python
    def _finish(self, job: Job, status: str, detail: str) -> None:
        self._log.record(job.source, job.kind, job.title, status, detail,
                         entry_id=job.entry_id)
        # THE MID-FLIGHT WINDOW, stated rather than hidden: the send has
        # returned, the log record is written, and the `close` is not. A process
        # killed here replays the job and delivers it TWICE. Deliberate — Chat
        # gives us no idempotency key, so the alternative is a two-phase commit
        # we are not building, and losing an alert is the worse failure.
        closed = self._journal_write(lambda: self._journal.close(job.entry_id, status),
                                     "close")
        with self._lock:
            if job in self._jobs:
                self._jobs.remove(job)
            drained = not self._jobs
        # CG-65 / ADR-0002 D1 — compact when the live set drains.
        #
        # A `close` record does NOT erase a payload: it appends a line saying
        # the id is done while the `open` line carrying the body stays where it
        # was. ADR-0002 §2.2 measured the consequence — a DELIVERED body sat on
        # disk for ~500 gateway-wide notifies, which at this design's assumed
        # traffic shape is three to eight WEEKS. A terminal job's payload has no
        # replay value whatsoever, so that retention was a cost with no matching
        # benefit; this collapses it to seconds.
        #
        # `compact([])` truncates the file to zero lines — measured, not assumed.
        # `_maybe_compact_locked`'s 1000-append trigger STAYS as the backstop for
        # a queue that never drains.
        #
        # THE HONEST COST, kept here rather than only in the ADR: one stuck job
        # pins every other tenant's delivered body on disk until it terminates,
        # because the set never empties. Bounded by the ~73-minute retry ladder,
        # or by REPLAY_MAX_AGE_S (24h) across gateway downtime.
        #
        # ⚠ `compact()` RECOMPUTES its survivors — it is NOT `compact([])`, and
        # that difference is a data-loss bug, not a style choice. `enqueue`
        # writes its `open` to disk BEFORE taking `self._lock` (deliberately —
        # a job we cannot persist must be refused, not queued), so a record can
        # be on disk while `drained` is being computed from `_jobs`. Asserting
        # an empty survivor set from that snapshot would erase a job that
        # `enqueue` had already 202'd. Recomputing reads open-minus-close under
        # the JOURNAL's own lock, which `Journal.open` also holds, so the two
        # serialize: the racing record is either a survivor and is rewritten,
        # or it lands after the `os.replace`. On a genuine drain it still
        # truncates to zero lines, because everything is closed.
        #
        # Same reasoning covers a FAILED `close`: that entry is still
        # open-minus-close, so it survives rather than being truncated away —
        # which is the point of counting the failure instead of raising.
        # `closed` is kept as the cheap first gate.
        if drained and closed:
            self._journal_write(lambda: self._journal.compact(), "compact")
```

⚠ `drained` is computed **inside** the lock and acted on outside it, matching
`_journal_write`'s existing posture (it must never be called under the lock — a
journal write can block on fsync). That posture is *why* the survivor set must
be recomputed rather than snapshotted: the gap between reading `_jobs` and
touching the file is exactly where the racing `open` lands.

⚠ **`closed` is a second gate the first draft did not have.** `_journal_write`
returns `False` when the `close` failed, and a failed `close` leaves the entry
open **on purpose** so it replays. Compacting anyway would recompute it as a
survivor and rewrite it — correct, but the gate is kept as the cheap first
check so the common failure path never touches the file at all.

**Tests:**

```python
def test_delivered_body_is_erased_when_the_queue_drains(tmp_path):
    """ADR-0002 §2.2 measured weeks; D1 makes it seconds."""
    jpath = tmp_path / "delivery.jsonl"
    d = Dispatcher({"webhook": _OkAdapter()}, DeliveryLog(), journal=Journal(jpath))
    d.enqueue("aitrader", "notify", _identity(), _message("HALT AAPL 4200sh"), "HALT")
    assert "HALT AAPL 4200sh" in jpath.read_text()
    d.process_due()
    assert d.pending() == 0
    assert jpath.read_text() == ""            # zero lines, body gone


def test_a_stuck_job_pins_the_other_bodies_until_it_terminates(tmp_path):
    """The honest cost of D1, pinned as a test rather than left as a comment."""
    jpath = tmp_path / "delivery.jsonl"
    adapters = {"webhook": _OkAdapter(), "app": _FailAdapter()}
    d = Dispatcher(adapters, DeliveryLog(), journal=Journal(jpath))
    d.enqueue("jobhunt", "notify", _identity(mode="app"), _message("STUCK"), "stuck")
    d.enqueue("aitrader", "notify", _identity(), _message("QUIET TENANT BODY"), "ok")
    d.process_due()
    # the aitrader job delivered and closed, but the set never drained
    assert d.pending() == 1
    assert "QUIET TENANT BODY" in jpath.read_text()


def test_the_append_count_backstop_still_fires_for_a_queue_that_never_drains(tmp_path):
    jpath = tmp_path / "delivery.jsonl"
    d = Dispatcher({"webhook": _OkAdapter(), "app": _FailAdapter()}, DeliveryLog(),
                   journal=Journal(jpath, compact_after=6))
    d.enqueue("jobhunt", "notify", _identity(mode="app"), _message("STUCK"), "stuck")
    for _ in range(8):
        d.process_due()
    assert d.pending() == 1                   # never drained
    assert len(jpath.read_text().splitlines()) < 8   # backstop compacted anyway
```

---

## Task 5 — Compact the inbox journal on drain

The mirror image, and it carries a trap the outbound side does not.

> ## ⚠ CORRECTED 2026-08-01 — same race, reached by a different route
>
> **This task's first draft had the same `compact([])` defect as Task 4, plus
> two gates it was missing entirely.** Recorded rather than quietly rewritten,
> for the same reason: CG-68's sweeper touches this directory's neighbour and a
> reader needs the rejected pattern, not just the accepted one.
>
> **Why `drained` alone does not close it here.** `Inbox.put` writes its `open`
> to disk **before** taking `self._lock` (deliberately — an unpersisted tap must
> not be acked), so **another app's** reply can be on disk while `drained` is
> read from `_pending`. The `drained` check cannot see it, because the racing
> record **is not yet in `_pending` at all**. This is the same one-file trap the
> existing comment describes, arrived at from the other side.
>
> **Two further gates found by measurement, not reasoning** — both are in the
> shipped code and neither was in the first draft:
>
> - **`ids`** — a poll that closed nothing has reclaimed nothing, and `compact`
>   writes-and-renames unconditionally. An empty poll would therefore **create**
>   a journal file for a gateway that has never queued a reply. That broke
>   `test_an_opted_out_owner_reaches_neither_its_inbox_nor_unrouted_nor_disk`,
>   which pins hard rule #6's *"nothing reached disk"* — so this gate is
>   load-bearing on a hard rule, not a tidiness point. It would also truncate an
>   unrestored journal.
> - **`closed`** — a `close_many` that FAILED left those ids open on purpose so
>   they replay. Truncating there turns the counted duplicate this method buys
>   into the silent loss it exists to avoid.
>
> `Dispatcher._finish` needs no `ids` equivalent: it is only ever called with a
> job that just terminated.

**`src/chat_gateway/inbox.py::poll`** — replace the whole method:

```python
    def poll(self, app_id: str) -> list[InboundReply]:
        with self._lock:
            q = self._pending[app_id]
            items = list(q)
            q.clear()
            ids = list(self._ids_by_app[app_id])
            self._ids_by_app[app_id].clear()
            # ACROSS EVERY APP, not just this one. There is ONE inbox.jsonl for
            # the whole gateway, so compacting because *this* app's queue is
            # empty would truncate another app's still-pending replies out of
            # existence — a silent inbound loss, which is the exact failure the
            # journal was added to prevent. The outbound twin has no equivalent
            # trap because `_jobs` is already one flat list.
            drained = not any(self._pending.values())
        # One append for the whole batch, so a crash part-way cannot close some
        # of a poll's replies and replay the rest — see Journal.close_many.
        closed = self._journal_write(lambda: self._journal.close_many(ids, "polled"),
                                     "close_many")
        # CG-65 / ADR-0002 D1, the mirror image of `Dispatcher._finish`: a
        # POLLED reply has no replay value, and a `close` does not erase its
        # body — only compaction does.
        #
        # Gated on `ids` and `closed` as well as on the drain, and both gates
        # were MEASURED rather than reasoned about. `ids`: a poll that closed
        # nothing has reclaimed nothing, and `compact` writes-and-renames
        # unconditionally — so an empty poll would CREATE a journal file for a
        # gateway that has never queued a reply (it broke
        # `test_an_opted_out_owner_reaches_neither_its_inbox_nor_unrouted_nor_disk`,
        # which pins hard rule #6's "nothing reached disk"), and would truncate
        # an unrestored one. `closed`: a `close_many` that FAILED left those ids
        # open ON PURPOSE so they replay — see `_journal_write` — and truncating
        # here would turn that counted duplicate into a silent loss.
        # `Dispatcher._finish` needs no `ids` equivalent: it is only ever called
        # with a job that just terminated.
        #
        # ⚠ And `compact()` RECOMPUTES its survivors — it is NOT `compact([])`.
        # `put` writes its `open` to disk BEFORE taking `self._lock`
        # (deliberately — an unpersisted tap must not be acked), so ANOTHER
        # app's reply can be on disk while `drained` is being read from
        # `_pending`. Asserting an empty survivor set from that snapshot would
        # erase a tap that was already journalled and is about to be queued —
        # the same one-file trap as the comment above, reached by a different
        # route, and the `drained` check alone does not close it because the
        # racing record is not yet IN `_pending`. Recomputing reads
        # open-minus-close under the JOURNAL's own lock, which `Journal.open`
        # also holds, so the two serialize. A genuine drain still truncates to
        # zero lines, and a FAILED `close_many` survives rather than being
        # truncated away.
        if ids and drained and closed:
            self._journal_write(lambda: self._journal.compact(), "compact")
        return items
```

**Tests:**

```python
def test_polled_reply_body_is_erased_when_the_inbox_drains(tmp_path):
    jpath = tmp_path / "inbox.jsonl"
    ibx = Inbox(journal=Journal(jpath))
    ibx.put(_reply(app="job-hunter", text="APPROVE role 42"))
    assert "APPROVE role 42" in jpath.read_text()
    ibx.poll("job-hunter")
    assert jpath.read_text() == ""


def test_polling_one_app_never_erases_another_apps_pending_reply(tmp_path):
    """The one-file trap: compaction is gateway-wide, the poll is per-app."""
    jpath = tmp_path / "inbox.jsonl"
    ibx = Inbox(journal=Journal(jpath))
    ibx.put(_reply(app="job-hunter", text="POLLED SOON"))
    ibx.put(_reply(app="aiteam-harness", text="STILL PENDING"))
    ibx.poll("job-hunter")
    assert "STILL PENDING" in jpath.read_text()
    # and it survives a restart
    revived = Inbox(journal=Journal(jpath))
    assert revived.restore() == 1
    assert revived.pending_counts() == {"aiteam-harness": 1}
```

---

## Task 6 — ⚠ The quarantine: what replaces "the only copy"

**This is the gate.** Spec §3 R2, answering ADR-0002 §9 Q6. Without it, Task 10
deletes the last copy of a reply that was never delivered.

**`src/chat_gateway/inbox.py::__init__`** — add the directory and two counters:

```python
    def __init__(self, audit_dir: str | Path | None = None, max_pending: int = 1000,
                 journal=None, quarantine_dir: str | Path | None = None):
```

```python
        #: Where an unrevivable journal record is preserved. None keeps this
        #: object exactly what it was before CG-65, which is what every offline
        #: test constructs — the same opt-in posture as `journal`.
        self._quarantine_dir = Path(quarantine_dir) if quarantine_dir else None
        #: Unrevivable records successfully preserved, and quarantine writes
        #: that failed. Both reach /healthz: a recovery mechanism that has
        #: silently stopped working is worse than none, because it is trusted.
        self.quarantined = 0
        self.quarantine_write_errors = 0
```

**`src/chat_gateway/inbox.py`** — new method:

```python
    def _quarantine(self, rec: dict) -> bool:
        """Preserve an unrevivable journal record before compaction erases it.

        CG-65, answering ADR-0002 §9 Q6. The per-app audit trail used to be the
        only surviving copy of a reply that could not be revived — and CG-68
        prunes that trail on a time bound. This method is what makes the pruning
        safe: the record, PAYLOAD INCLUDED, is already in hand at the drop site,
        so preserving it costs one append. Without it, `restore` drops the
        record and `compact` erases the journal's copy moments later.

        Never swept — `retention.py` does not look in this directory, and that
        is the point of it existing.

        ⚠ SHIPPED DIFFERENTLY, and the shipped text is the one to edit. #52's
        review rewrote this paragraph into the FUTURE tense ("CG-68's retention
        sweeper must not look…; there is no sweeper in this tree yet") because
        `retention.py` did not exist. It exists after Task 10, so the paragraph
        inverts again — **that is Task 14, row 5**, which also has the stronger
        wording now available ("cannot", not "must not").

        Best-effort, and counted rather than raised: a quarantine write that
        fails must not stop a boot. The console line below says which branch
        happened, because "the recovery record exists" is exactly the kind of
        claim that must not be asserted when it is false.
        """
        if self._quarantine_dir is None:
            return False
        try:
            self._quarantine_dir.mkdir(parents=True, exist_ok=True)
            path = self._quarantine_dir / f"unrevivable-{dt.date.today().isoformat()}.jsonl"
            existed = path.exists()
            with path.open("a", encoding="utf-8") as fh:
                if not existed:
                    chmod_owner_only(path)
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except Exception as exc:  # noqa: BLE001 — recovery degrades, boot does not stop
            self.quarantine_write_errors += 1
            print(f"inbox: quarantine write FAILED ({describe_exception(exc)}); "
                  "an unrevivable reply has no preserved copy", flush=True)
            return False
        self.quarantined += 1
        return True
```

**`src/chat_gateway/inbox.py::restore`** — replace the `except` branch:

```python
                except Exception as exc:  # noqa: BLE001 — config/envelope drift, not a bug
                    self.unrevivable += 1
                    preserved = self._quarantine(rec)
                    print(f"inbox: journalled reply {rec['id']!r} no longer parses "
                          f"({describe_exception(exc)}) — DROPPED, not delivered; "
                          + ("the whole record was preserved in the quarantine dir "
                             "under the state dir, which is never pruned"
                             if preserved else
                             "NO quarantine copy was written — the per-app JSONL "
                             "audit under the inbox dir is the only recovery record, "
                             "and it is subject to the retention window"),
                          flush=True)
                    continue
```

And update the **docstring** of `restore`, which currently names the audit trail
as the recovery record (promise site 4 — spec §2.5):

```
        **The quarantine file under the state dir is the recovery record** — the
        whole journal record, payload included, is written there before boot
        compaction erases it, and it is never pruned. The per-app JSONL audit
        beside this queue also holds what arrived, but it is subject to a
        retention window (CG-68) and cannot be relied on as the only copy.
```

**`src/chat_gateway/__main__.py::build_runtime`** — wire it:

```python
    inbox = Inbox(audit_dir=os.environ.get("CHAT_GATEWAY_INBOX_DIR", "inbox-data"),
                  journal=Journal(Path(state_dir) / "queue" / "inbox.jsonl"),
                  # CG-65: unrevivable replies are preserved here rather than
                  # only pointed at in another file. Under the state dir, beside
                  # the journals, because it is queue-recovery material — not an
                  # audit record of what arrived.
                  quarantine_dir=Path(state_dir) / "quarantine")
```

**Tests:**

```python
def test_unrevivable_reply_is_preserved_in_quarantine(tmp_path):
    """CG-65 / ADR-0002 Q6: the gateway keeps the bytes it is holding instead of
    pointing at a file the sweeper may delete."""
    jpath = tmp_path / "inbox.jsonl"
    Journal(jpath).open(1, "inbound", {"app": "job-hunter", "NOT": "an InboundReply"})
    ibx = Inbox(journal=Journal(jpath), quarantine_dir=tmp_path / "quarantine")
    assert ibx.restore() == 0
    assert ibx.unrevivable == 1 and ibx.quarantined == 1
    qfile = next((tmp_path / "quarantine").glob("unrevivable-*.jsonl"))
    assert "NOT" in qfile.read_text()
    assert stat.S_IMODE(qfile.stat().st_mode) == 0o600
    assert jpath.read_text() == ""       # journal's own copy is gone, as before


def test_quarantine_is_opt_in_and_absence_is_reported_honestly(tmp_path, capsys):
    jpath = tmp_path / "inbox.jsonl"
    Journal(jpath).open(1, "inbound", {"bad": "record"})
    ibx = Inbox(journal=Journal(jpath))          # no quarantine_dir
    ibx.restore()
    assert ibx.unrevivable == 1 and ibx.quarantined == 0
    assert "NO quarantine copy" in capsys.readouterr().out
```

---

## Task 7 — Surface the quarantine at `/healthz`

Hard rule #5. This is also what makes promise **site 6** true again.

> ⚠ **SHIPPED DIFFERENTLY in two ways; `service.py` on `4fbd634` is the text to
> edit, not the block below.** #52's review (a) made the `reasons` tail
> **branch on `preserved`**, because asserting *"the quarantine is the recovery
> record"* when nothing was preserved reproduces the exact defect this task
> exists to fix, on the exact line — the comment at `service.py:480-487` is that
> reasoning's one home; and (b) rewrote both `else` branches to say the audit
> trail *"carries no retention guarantee"* rather than *"is subject to the
> retention window"*, since no window shipped. **(b) inverts when Task 10 lands
> — that is Task 14, rows 1 and 2.** (a) does not change and must survive.

**`src/chat_gateway/service.py`** — extend the `inbox` block:

```python
            "inbox": {"pending": inbox.pending_counts(), "dropped": inbox.dropped,
                      "replayed_at_boot": getattr(inbox, "replayed", 0),
                      # The inbound twin of delivery's `unroutable_at_boot`:
                      # ... (keep the existing comment verbatim)
                      "unrevivable_at_boot": getattr(inbox, "unrevivable", 0),
                      # CG-65. How many of those were preserved. Two numbers,
                      # not one: `unrevivable` is what was lost from the queue,
                      # `quarantined` is what is recoverable, and an operator
                      # reading the first needs the second to know whether to
                      # go looking.
                      "quarantined_at_boot": getattr(inbox, "quarantined", 0),
                      "quarantine_write_errors": getattr(inbox, "quarantine_write_errors", 0)},
```

Replace the `unrevivable_at_boot` reasons block:

```python
        if body["inbox"]["unrevivable_at_boot"]:
            preserved = body["inbox"]["quarantined_at_boot"]
            reasons.append(
                f"inbox replay dropped {body['inbox']['unrevivable_at_boot']} "
                "journalled reply(ies) that no longer parse as an InboundReply — "
                "they were NOT delivered to the owning app and are gone from the "
                "queue journal. An envelope change across a deploy looks like "
                f"this. {preserved} of them were preserved in full under the "
                "state dir's quarantine dir, which is never pruned and is the "
                "recovery record; the ids are on the boot console"
            )
```

Add a reason for a failed quarantine write:

```python
        if body["inbox"]["quarantine_write_errors"]:
            reasons.append(
                f"inbox quarantine: {body['inbox']['quarantine_write_errors']} "
                "write(s) FAILED — at least one unrevivable reply has no "
                "preserved copy, so the per-app JSONL audit under the inbox dir "
                "is its only record and the retention window applies to it. "
                "Check free space and the state dir's permissions"
            )
```

**Test** (`tests/test_service.py`, alongside the existing `/healthz` tests):

```python
def test_healthz_names_the_quarantine_as_the_recovery_record(tmp_path):
    """Promise site 6: this reasons line told an operator to read a file the
    sweeper is about to delete. It now names an artifact the gateway keeps."""
    jpath = tmp_path / "inbox.jsonl"
    Journal(jpath).open(1, "inbound", {"app": "job-hunter", "NOT": "an InboundReply"})
    inbox = Inbox(journal=Journal(jpath), quarantine_dir=tmp_path / "quarantine")
    inbox.restore()
    client = TestClient(_app_with(inbox=inbox))

    body = client.get("/healthz").json()
    assert body["inbox"]["unrevivable_at_boot"] == 1
    assert body["inbox"]["quarantined_at_boot"] == 1
    assert body["inbox"]["quarantine_write_errors"] == 0
    assert body["status"] == "degraded"
    line = next(r for r in body["reasons"] if "unrevivable" in r or "no longer parse" in r)
    assert "quarantine" in line and "never pruned" in line
    # and it must NOT still point at the per-app audit trail as the only copy
    assert "only recovery record" not in line
```

⚠ `_app_with` is this file's existing `create_app` helper — reuse it rather than
building a second one.

---

## Task 8 — `docs/consumers/aitrader.md`: the contract correction

⚠ **Do not soften this into "the journal is secure."** State what reaches disk,
for how long, and at what mode. Eight items, spec §6.

**8a — `:213-217`, the scope note.** The `/v1/messages` carve-out is **inverted**
(ADR §2.8) — correct it, do not delete it. Replace the block ending in *"no body
text of yours is ever written anywhere"* with:

> **One honest scope note, and it now points the other way.** `/v1/messages` —
> which your key can call but your contract does not use — logs `text[:80]` as a
> delivery-log title, and that log is **permanent**. `/v1/notify`, the endpoint
> your contract is built on, writes **more** and keeps it for **less**: since
> 2026-07-31 the durable queue journals the whole rendered message — `text` and
> `cards` — to `<CHAT_GATEWAY_STATE_DIR>/queue/delivery.jsonl`, file mode `0600`.
>
> **How long: only while the alert is undelivered.** Normally well under a
> second. Up to ~73 minutes if it is working through the retry ladder, and up to
> 24 hours if the gateway is down (past that it is closed as `expired` rather
> than sent). The journal is erased the moment the outbound queue drains.
> **One caveat, stated rather than buried:** a single stuck job anywhere on the
> gateway holds that drain open, so a delivered body of yours can persist until
> the stuck job terminates — bounded by the same ~73 minutes, or 24 hours across
> downtime.
>
> **No credential is written.** The journal stores the identity **name** and
> re-resolves it through the registry at boot, so no webhook URL and no API key
> reaches it (hard rule #2).
>
> ⚠ **This replaces a sentence that promised the opposite.** Until 2026-07-31
> this note read *"if you never call `/v1/messages`, no body text of yours is
> ever written anywhere."* That became false when the queue was made durable.
> The decision to keep the durability and rewrite the promise — rather than stop
> journalling your bodies and lose replay for the one tenant with no fallback
> channel — is recorded in
> [ADR-0002](../architecture/decisions/2026-07-31-journalled-message-bodies.md).

**8b — `:219`** — replace *"Restart drops undelivered jobs. The queue is
in-memory."* with the durable behaviour: replayed at boot with the attempt count
preserved; older than 24h closed as `expired`; identity re-resolved so a
withdrawn grant closes it `unroutable`; a mid-flight job may deliver **twice**.
**Do not restate the replay rule in detail** — `delivery.py`'s docstring is its
one home. Link and summarize in one sentence.

**8c — `:547`** — the same claim under *"Accepted limitations, agreed in the
contract."* Replace the bullet with the accepted limitation that is actually
true now: *a mid-flight restart may deliver an alert twice — Chat has no
idempotency key, and losing an alert was judged the worse failure.* Keep "keep
your local fallback log."

**8d — `:418`** — *"Nothing about aitrader's traffic is persisted anywhere, in
any configuration"* needs the `_unrouted` caveat (ADR §2.7) **and** must not
contradict 8a. Rewrite as a scoped claim: nothing about aitrader's traffic
crosses to a consumer or is persisted **as aitrader's** — the `continue` fires
before any `inbox.put` — with the two named exceptions: outbound bodies in the
queue journal (8a), and an event that `normalize_event` cannot parse, which has
no attributable space and is audited under `_unrouted` with its `raw` intact.
**Keep the existing note that this is the claim the contract rests on, and that
it has now survived three corrections.**

**8e — `:442`** — the `/healthz` guidance. It currently says a `degraded`
reading is a tier-2 concern leaving *"your alerting unaffected."* Add that
**five** outbound-queue fields can now degrade it (`expired_at_boot`,
`unroutable_at_boot`, `unrevivable_at_boot`, `journal_skipped_lines`,
`journal_write_errors`) and that each means an aitrader alert was dropped or will
be double-sent. Keep the two identity/key fields as the ones that gate readiness.
⚠ **Five fields, four `reasons` lines** — `expired` and `unroutable` share one.
CG-64's Builder got this count wrong; do not repeat it.

**8f — `:569`** — env table. `CHAT_GATEWAY_STATE_DIR` is no longer *"heartbeat
checks + delivery JSONL"*: it holds heartbeat checks, the delivery log, **the
queue journals (message bodies, `0600`)** and **the quarantine dir**.

**8g — `:209`** — `delivery.py:44-50` → **`delivery.py:77-91`**. The claim is
still correct; only the pointer drifted.

**8h — §10 verification status** — ⚠ **change nothing.** No ⚠ flag is cleared,
added or reworded by this row. If a sentence there needs the ledger, **link** to
`CLAUDE.md`.

---

## Task 9 — `docs/integration-guide.md` + `CLAUDE.md`

**9a — `integration-guide.md:378-383`.** Promise site 2. Replace *"and the audit
file is then the only copy"*:

> Both stay; neither substitutes for the other. One consequence is worth
> planning for: a journalled reply that no longer validates as an `InboundReply`
> at boot — an envelope change across a deploy looks precisely like this — is
> **dropped, not delivered**, and counted at `/healthz` →
> `inbox.unrevivable_at_boot`, which degrades the endpoint. It is not resent.
> **The whole record is preserved**, payload included, under the state dir's
> `quarantine/` directory, which is **never pruned** and is the recovery record;
> `/healthz` → `inbox.quarantined_at_boot` says how many were preserved, and
> `inbox.quarantine_write_errors` is non-zero if that ever failed.

**9b — the `/healthz` durability table.** Add two rows and update the counts.
The section says *"Seven fields arrived with the journals"* and *"five of them
can flip `status`"*; with `quarantined_at_boot` (no) and
`quarantine_write_errors` (**yes**) that becomes **nine fields, six that
degrade**. Recount against `service.py` rather than trusting this sentence.

| Field | What it means | Degrades? |
|---|---|---|
| `inbox.quarantined_at_boot` | unrevivable replies preserved in full under the state dir's `quarantine/`, which is never pruned | no — the recovery mechanism working |
| `inbox.quarantine_write_errors` | quarantine writes that **failed**; an unrevivable reply has no preserved copy | **yes** |

**9c — `CLAUDE.md`, the CG-54 bullet.** Name the retention property, not just
"durable." **One sentence, no second copy of the numbers** — the residency
figures live in ADR-0002 §2.2 and the contract text, and this file's own history
is the argument against a third home. Suggested addition:

> **Retention, not just durability (CG-65, 2026-07-31):** a journalled body now
> lives exactly as long as its job is replayable — the journal compacts when the
> queue drains, so a *delivered* body's residency fell from the weeks ADR-0002
> §2.2 measured to seconds. Both audit trails are created `0600`. An unrevivable
> reply is preserved under `<state_dir>/quarantine/`, which is never pruned,
> because the per-app audit trail stopped being *"the only copy"* the moment it
> gained a retention window. Numbers and reasoning: ADR-0002 — **not restated
> here.**

**9d** — do **not** touch `integration-guide.md:366` in this row. Task 13.

---

## CG-65 gates

- Full suite green. Estimate **247 → ~267**; measure and report the real number.
- `grep -rn "_chmod_quietly" src/` → empty.
- No diff under `docs/architecture/` or `src/chat_gateway/adapters/`.
- `grep -c "LIVE-UNVERIFIED\|SHAPE-VERIFIED" src/ -r` unchanged from base.
- Manual: `python3 -m chat_gateway serve` against a scratch state dir, one
  `/v1/notify`, confirm `state/queue/delivery.jsonl` is empty after delivery and
  every audit file is `0600`.

---

# CG-68 — Tasks 10–14

> ✅ **The four decisions are made (A1–A4 above, user, 2026-07-31).** The window
> is **30 / 7 / 0** and the constants in Task 10 are already written to it — they
> and every doc number in Task 14 must not disagree.
>
> ✅ **The merge gate is RELEASED.** It read *"CG-65 must be MERGED before this
> row starts"*; CG-65 merged **2026-07-31 as #52** (`4fbd634`), suite **268**.
> The quarantine exists (`inbox.py:264`, `<state_dir>/quarantine/`). Kept as a
> released gate rather than deleted, so a reader can tell the difference between
> a gate that was satisfied and one that was never there.
>
> **Base for this row is `4fbd634`, suite 268** — not the `~266` the CG-68 gates
> section estimated before CG-65 shipped. Measured, not copied.

---

## ⚠ CG-68 pre-execution audit — 2026-08-01

Tasks 10–13 were audited before execution for the **CG-65 defect shape** — *an
emptiness or survivor set computed under one lock, asserted to a destructive
operation protected by a different one* — because CG-68 **deletes tenant
content** where CG-65 only compacted replayable state. A stale read here is
unrecoverable, not merely wasteful.

### The headline: **NO. Tasks 10–13 do not carry that shape.**

`RetentionSweeper.sweep()` derives **nothing** from in-memory state. It reads the
directory — the authority itself — and decides each file independently from that
file's **own name**. There is no global survivor assertion, so there is no
snapshot that can go stale against the disk. The two designs are structurally
different, and that difference is A3's *"the filename **is** the retention key"*
paying off a second time: a per-file decision keyed on the file cannot be raced
by the creation of a *different* file.

**The one latent analogue, named so it is not rediscovered as a surprise:**
`Inbox._audit` (`inbox.py:297`) and `sweep()` write and delete in the same
directory with **no shared lock**. It is safe only because `_audit` writes
**today's** file and `sweep()` never targets a file inside its window. That
safety is arithmetic, not synchronization — and finding **F1** below is the one
input that can make the arithmetic wrong.

### What the audit DID find — six neighbours, folded into the tasks below

| # | Sev | Where | Finding |
|---|---|---|---|
| **F0** | **HIGH** | Task 12 | `/healthz` raises **`KeyError`** whenever `sweeper is None` |
| **F1** | MED | Task 10 vs `inbox.py:301` | The retention key is **written in local-time and read in UTC** — two calendars |
| **F2** | MED | Task 10 | *"What this never touches"* is a **path arrangement, not a code property** — and the quarantine's filename matches the sweeper's own regex |
| **F3** | MED | Task 10 / 12 | A sweeper that has **silently stopped** is invisible at `/healthz` — the exact rule-#5 founding failure |
| **F4** | LOW | Task 10 | Two `print(... {exc})` sites bypass **CG-29's allowlist** |
| **F5** | LOW | Task 12 | `unrouted_window_days` **re-derives** `window_for`'s rule instead of calling it |

**F0 — `/healthz` KeyError when no sweeper is configured. HIGH; it takes the
endpoint down.** Task 12 renders the `retention` block as
`{...} if sweeper is not None else {"enabled": False, "note": ...}` — an
else-branch with **no `delete_errors` key** — and then indexes
`body["retention"]["delete_errors"]` unconditionally. Every offline test that
builds an app without a sweeper, which Task 12 explicitly says is the point of
the `None` default, would 500 on `/healthz`. The endpoint that hard rule #5
exists to keep honest cannot answer at all. The existing `subscriber` block
(`service.py:449-452`) has the identical two-branch shape and **guards it**:
`sub = body["subscriber"]` then `if sub["enabled"]:`. Task 12 now copies that
guard.

**F1 — the retention key is written in one calendar and read in another.
MED.** `Inbox._audit` names the file with `dt.date.today()` (`inbox.py:301`) —
**local, naive**. `RetentionSweeper._now` defaults to
`dt.datetime.now(dt.timezone.utc)` and compares against `.date()` — **UTC**. On
any host west of UTC the local date lags the UTC date for part of every day, so
a file is up to one day *older* by the sweeper's reckoning than by the reckoning
that named it. At **30 / 7** this costs a few hours of window and nothing else.
It matters because the *design* rests on the filename being an exact key, and a
key produced by one clock and consumed by another is not exact — and because it
is the one input that could put today's file inside the delete set, which is the
only way the unlocked `_audit`/`sweep` pair above can collide. Fixed by giving
`RetentionSweeper` the **same** calendar as the writer, with the mismatch
recorded in the module rather than left for someone to re-derive.

**F2 — *"what this never touches"* is true by path arrangement, not by code.
MED.** Task 10's module docstring lists `quarantine/`, `deliveries/` and
`queue/` under **WHAT THIS NEVER TOUCHES**, which reads as an enforced property.
It is not. Measured:

- `unrevivable-2026-07-31.jsonl` **matches** `_NAME` → `app='unrevivable'`.
  That does not start with `_`, so it draws the **full 30-day tenant window**,
  not the 7-day floor.
- `deliveries-aitrader-2026-07-20.jsonl` **matches** too →
  `app='deliveries-aitrader'`. ADR **D7**'s *"permanent by decision"* is
  likewise unenforced.

What actually protects both today is that `glob("*.jsonl")` is **non-recursive**
and `__main__.py` puts them in sibling directories: the sweep dir is
`CHAT_GATEWAY_INBOX_DIR` (default `inbox-data`), the quarantine is
`<CHAT_GATEWAY_STATE_DIR>/quarantine` (`__main__.py:50`), the delivery log
`<state_dir>/deliveries` (`__main__.py:104`). **So the plan's claim is true on
the default configuration** — but it is one env-var away from false, and both
vars are operator-settable with nothing comparing them. Given that quarantine
files hold replies that were **never delivered** and are by construction *old*,
that is the one deletion in this repo with no second copy anywhere. Task 10 now
makes the guarantee a code property: refuse a sweep directory that is, contains,
or sits inside the quarantine, and skip the quarantine's own filename outright.

**F3 — a stopped sweeper is invisible. MED, hard rule #5.** Two gaps:
`sweep()` sets `last_sweep_at` only *after* its early-return guard, so a
deployment with no `inbox-data/` yet reports `enabled: true, last_sweep_at:
null` **forever** — indistinguishable from a dead thread. And `_run` catches
every sweep exception, prints it, and **counts nothing**, so a sweeper throwing
every six hours reports `errors: 0` with a frozen `last_sweep_at` and never
degrades `/healthz`. That is precisely the failure rule #5 was written after: a
health check that reads plausible while the machinery behind it is dead. Task 10
now records `last_sweep_at` on every completed pass and keeps a
`last_sweep_error`; Task 12 surfaces both.

**F4 — two print sites bypass CG-29's allowlist. LOW.** Task 10 prints
`({exc})` for an unlink `OSError` and for a sweep failure. `str(OSError)` from
`Path.unlink()` embeds the **absolute path** (`[Errno 13] Permission denied:
'/srv/.../job-hunter-2026-06-01.jsonl'`), and `OSError` is not a class
`errors.py` marks. No credential is exposed — hard rule #2 is not breached — but
CLAUDE.md's CG-29/CG-33 rule is *"printed in full only if this repo wrote every
byte of it"*, and the whole point of an **allowlist** is that the next
unanticipated exception is not the one that teaches you. Task 10 now uses
`describe_exception`. `path.name` is kept: it was already deliberately `.name`
rather than the full path.

**F5 — `window_for`'s rule gets a second home. LOW.** Task 12 computes
`min(sweeper.days, UNROUTED_RETENTION_DAYS)` inline, duplicating `window_for`.
If the floor rule ever changes, `/healthz` publishes the old one. This file's own
history is the argument (CLAUDE.md's test count, twice). Task 12 now calls
`window_for("_unrouted", sweeper.days)`.

### What the audit found OUTSIDE Tasks 10–13 → new **Task 14**

CG-65's pre-merge review rewrote three strings that asserted, in the **present**
tense, a retention window and a `retention.py` that had not shipped. Those fixes
are on `main` and are correct **today** — and each one becomes **false in the
opposite direction the moment this row ships**. Five strings, **two of them on
the unauthenticated `/healthz`**. Task 13 did not list any of them. See Task 14.

---

## Task 10 — `src/chat_gateway/retention.py`

```python
"""Time-bounded retention for the per-app inbound audit trail.

CG-68 / ADR-0002 D5. `inbox-data/<app>-<date>.jsonl` held a human's `text`,
`sender_email` and whole `raw` event forever. CG-65 fixed the mode; this fixes
the "forever".

TIME-BOUNDED IN DAYS, NEVER COUNT-BOUNDED, and that is not a style choice.
ADR-0002 §2.2 measured that the journal's count-bound yields a retention nobody
can convert to a date — "500 gateway-wide notifies" is not a sentence that can go
in a consumer contract, and turning it into one took a parameterised table and a
paragraph of arithmetic. A retention policy on human message content has to be
expressible as "N days", because that is the unit a contract, a privacy posture
and a subject-access request are all written in.

THE FILENAME IS THE RETENTION KEY. `<app>-<date>.jsonl` is already sharded by
exactly the right dimension, so pruning is a directory listing and an unlink —
no parsing, no rewrite, and nothing here ever opens a file holding message
bodies in order to decide whether to delete it.

WHAT THIS NEVER TOUCHES, and why each one is deliberate:
  - `<state_dir>/quarantine/` — the preserved copy of a reply that could not be
    revived (CG-65). Pruning it would delete the last copy of something that was
    never delivered, which is the whole reason ADR-0002 §9 Q6 was a gate.
  - `<state_dir>/deliveries/` — titles-only and permanent by decision (D7).
  - `<state_dir>/queue/` — the journals compact themselves.

⚠ THAT LIST USED TO BE TRUE ONLY BY WHERE THE PATHS HAPPEN TO POINT (audit F2,
2026-08-01). It read as an enforced property and was not one. Measured: the
quarantine's own `unrevivable-<date>.jsonl` MATCHES `_NAME` below with
`app='unrevivable'` — which does not start with `_`, so it would draw the FULL
tenant window, not the 7-day floor — and `deliveries-<source>-<date>.jsonl`
matches too, with `app='deliveries-<source>'`. Nothing but a non-recursive glob
and two sibling directories stood between a one-line env change and deleting the
only copy of replies that were never delivered. It is now enforced twice, in
code: `__init__` REFUSES a sweep directory that is, contains, or sits inside the
quarantine, and the loop skips the quarantine's filename outright. Belt and
braces on purpose — this is the one deletion in this repo with no second copy
anywhere.

THE RETENTION KEY IS WRITTEN IN LOCAL TIME, SO IT IS READ IN LOCAL TIME (audit
F1). `Inbox._audit` names the file with `dt.date.today()` — naive, local. Reading
it back against a UTC date, which the first draft did, makes a file up to one day
OLDER by the reader's reckoning than by the reckoning that named it, on every
host west of UTC. At 30/7 that costs hours and nothing else, but the design rests
on the filename being an EXACT key, and a key minted by one clock and consumed by
another is not exact. `today_fn` defaults to the identical call the writer makes,
so the two cannot drift apart without someone changing both. The separate
`now_fn` timestamps `last_sweep_at` for an operator and is tz-aware; they are
different questions and are deliberately two parameters.

A FILE WHOSE NAME THIS MODULE CANNOT PARSE IS LEFT ALONE, never guessed at.
Deleting an unrecognized file from a directory that holds message bodies is the
one failure mode worse than keeping it too long.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import threading
from pathlib import Path

from .errors import describe_exception

#: Default window for a tenant's bucket. A calendar month is the unit a privacy
#: posture is written in. The gateway does NOT need to hold a consumer's own
#: decision history: docs/integration-guide.md already tells consumers this file
#: is "a forensic record on the gateway host, not something you can re-poll", so
#: a consumer that needs that history keeps its own.
DEFAULT_RETENTION_DAYS = 30

#: `_unrouted` answers to no tenant — it accumulates whole unattributable `raw`
#: events with no consent story — so it gets the shortest window in the
#: directory. This stays hard-rule-#1-clean because `_unrouted` is the gateway's
#: OWN reserved bucket (hard rule #6 reserves the `_` prefix for exactly this),
#: not per-app policy. A per-TENANT window would be ADR-0002 Option C's shape
#: and would re-open a question the user deliberately left not-reached (D6).
UNROUTED_RETENTION_DAYS = 7

#: How often the background sweep runs. Six hours, not daily: a boot-only sweep
#: is no sweep at all on a host running `restart: unless-stopped` — the same
#: reasoning journal.py gives for not relying on boot compaction.
SWEEP_INTERVAL_S = 6 * 3600

_NAME = re.compile(r"^(?P<app>.+)-(?P<date>\d{4}-\d{2}-\d{2})\.jsonl$")

#: `inbox.py::_quarantine`'s filename stem. Skipped by name as well as by path
#: (audit F2): `unrevivable-<date>.jsonl` matches `_NAME` cleanly as an app
#: called "unrevivable", and it would draw the full tenant window. One home for
#: the literal — if `_quarantine` ever renames its files, this constant is the
#: thing that has to move with it, and a test pins the pair.
QUARANTINE_STEM = "unrevivable-"


class RetentionConfigError(ValueError):
    """The sweep directory overlaps something that must never be swept.

    Raised at construction, so it lands at boot and not six hours later on a
    thread. `retention_days_from_env` deliberately does the OPPOSITE for a
    malformed window — falls back and says so — and the asymmetry is the point:
    a bad window over-retains, which is recoverable, while a bad directory
    deletes the only copy of replies that were never delivered, which is not.

    ⚠ Deliberately NOT a `GatewayAuthoredError`, and this is the reason so it is
    not relitigated in review: it mirrors `RegistryError` (`registry.py:40`,
    also a plain `ValueError`), it is raised at boot and printed by `main`'s
    `config error:` path rather than through `describe_exception`, and CG-29's
    marker set is a deliberately short allowlist. Marking it would also enlist
    it in `tests/test_error_surfaces.py`'s raise-site guard, which is a real
    benefit — but that is a change to the allowlist, and CLAUDE.md records that
    the set has never been widened without a stated reason. If review wants it
    marked, say so as its own decision; do not fold it in here.
    """


def retention_days_from_env(environ: dict | None = None) -> int:
    """`CHAT_GATEWAY_INBOX_RETENTION_DAYS`, or the default. **0 disables pruning.**

    The zero case is the escape hatch that restores pre-CG-68 behaviour exactly,
    so a deployment can decline the contract amendment without a code change.

    A malformed value falls back to the default and SAYS SO rather than raising:
    a boot that refuses to start over a typo in a retention knob is a worse
    outcome than one that retains for the documented default.
    """
    env = os.environ if environ is None else environ
    raw = (env.get("CHAT_GATEWAY_INBOX_RETENTION_DAYS") or "").strip()
    if not raw:
        return DEFAULT_RETENTION_DAYS
    try:
        value = int(raw)
    except ValueError:
        print(f"retention: CHAT_GATEWAY_INBOX_RETENTION_DAYS={raw!r} is not an "
              f"integer — using the default of {DEFAULT_RETENTION_DAYS} days",
              flush=True)
        return DEFAULT_RETENTION_DAYS
    return max(0, value)


def window_for(app: str, days: int) -> int:
    """Effective window for one bucket.

    Lowering the configured knob lowers `_unrouted` too; raising it never
    loosens the ownerless bucket past its own floor.
    """
    if app.startswith("_"):
        return min(days, UNROUTED_RETENTION_DAYS)
    return days


class RetentionSweeper:
    """Boot-time + periodic prune of the per-app inbound audit trail.

    Its own thread rather than a hook on the dispatcher's 1s tick: `sweep()`
    stays a pure, directly-testable function, and deletion never sits in the
    delivery hot path. Same start/stop idiom as `Dispatcher` and `SubscriberLoop`.
    """

    def __init__(self, audit_dir: str | Path | None, days: int | None = None,
                 now_fn=None, interval_s: float = SWEEP_INTERVAL_S, *,
                 quarantine_dir: str | Path | None = None, today_fn=None):
        self._dir = Path(audit_dir) if audit_dir else None
        self._days = DEFAULT_RETENTION_DAYS if days is None else days
        #: Two clocks, two questions (audit F1). `today_fn` is the RETENTION
        #: KEY's calendar and must stay identical to `Inbox._audit`'s
        #: `dt.date.today()`. `now_fn` only timestamps `last_sweep_at` for an
        #: operator, where tz-aware UTC is the right answer. Collapsing them is
        #: what put a UTC reader on a local-time key in the first draft.
        self._today = today_fn or dt.date.today
        self._now = now_fn or (lambda: dt.datetime.now(dt.timezone.utc))
        self._quarantine = Path(quarantine_dir).resolve() if quarantine_dir else None
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        #: Files deleted since start, unlinks that failed, and whole passes that
        #: raised. All three reach /healthz: hard rule #5 does not distinguish
        #: work DROPPED from work DELETED, and a silent deletion path on an
        #: artifact two documents called "the only copy" is exactly the shape of
        #: failure it exists for.
        #:
        #: THREE numbers rather than one, for CLAUDE.md's stated reason (the
        #: `suppressed_opt_out` / `suppressed_not_authorized` split): they are
        #: different investigations. `errors` is one file the OS refused to
        #: delete — the trail grows past its window. `sweep_failures` is the
        #: whole pass dying, which means NOTHING is being pruned and the counter
        #: above will sit reassuringly at zero while it happens.
        self.deleted = 0
        self.errors = 0
        self.sweep_failures = 0
        self.last_sweep_at: str | None = None
        self.last_sweep_error: str | None = None
        self._check_disjoint()

    def _check_disjoint(self) -> None:
        """Refuse a sweep directory that overlaps the quarantine (audit F2).

        Both paths come from operator-settable env vars (`CHAT_GATEWAY_INBOX_DIR`
        and `CHAT_GATEWAY_STATE_DIR`) and nothing else in the process compares
        them. `resolve()` on both, so a symlink or a `..` cannot walk around it.

        Checked in BOTH directions, and neither is hypothetical padding: the
        sweep dir being the quarantine deletes preserved replies outright, and
        the quarantine sitting under the sweep dir is one `rglob` refactor away
        from the same thing.
        """
        if self._dir is None or self._quarantine is None:
            return
        swept = self._dir.resolve()
        if swept == self._quarantine or self._quarantine in swept.parents \
                or swept in self._quarantine.parents:
            raise RetentionConfigError(
                f"retention: refusing to sweep {swept} — it overlaps the "
                f"quarantine at {self._quarantine}, which holds the only copy of "
                "replies that were never delivered (CG-65). Point "
                "CHAT_GATEWAY_INBOX_DIR and CHAT_GATEWAY_STATE_DIR at "
                "directories that do not contain one another"
            )

    @property
    def days(self) -> int:
        return self._days

    def sweep(self) -> int:
        """Unlink day-files past their bucket's window. Returns how many."""
        if self._dir is None or self._days <= 0:
            return 0
        # NOT folded into the guard above (audit F3). A directory that does not
        # exist yet is a sweep that ran and found nothing — a normal state on a
        # deployment with no inbound traffic — and it must still stamp
        # `last_sweep_at`. Returning early without stamping made "the sweeper is
        # working and idle" byte-identical to "the sweeper thread is dead" on an
        # endpoint whose whole job is telling those two apart.
        removed = self._sweep_dir() if self._dir.exists() else 0
        self.last_sweep_at = self._now().isoformat()
        return removed

    def _sweep_dir(self) -> int:
        today = self._today()
        removed = 0
        for path in sorted(self._dir.glob("*.jsonl")):
            # Skipped by NAME as well as by path (audit F2). `unrevivable-<date>`
            # parses cleanly as an app called "unrevivable" and would draw the
            # full tenant window. `_check_disjoint` already makes this
            # unreachable in a sane layout; it is here for the layout nobody
            # predicted, because the cost of the check is one string compare and
            # the cost of being wrong is unrecoverable.
            if path.name.startswith(QUARANTINE_STEM):
                continue
            match = _NAME.match(path.name)
            if match is None:
                continue                      # never guess at a name we do not own
            try:
                stamp = dt.date.fromisoformat(match.group("date"))
            except ValueError:
                continue
            if (today - stamp).days <= window_for(match.group("app"), self._days):
                continue
            try:
                path.unlink()
            except OSError as exc:
                self.errors += 1
                # CG-29's allowlist, not an f-string on the exception (audit F4).
                # `str(OSError)` from `unlink()` embeds the ABSOLUTE path, and
                # `OSError` is not a class `errors.py` marks. `path.name` is kept
                # deliberately — the file's own name is this repo's to print.
                print(f"retention: could not remove {path.name} "
                      f"({describe_exception(exc)})", flush=True)
                continue
            removed += 1
        self.deleted += removed
        return removed

    def _run(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self._interval_s)
            if self._stop.is_set():
                break
            try:
                self.sweep()
                self.last_sweep_error = None
            except Exception as exc:  # noqa: BLE001 — the loop must survive
                # COUNTED, not just printed (audit F3). The first draft printed
                # and moved on, so a sweeper throwing every six hours reported
                # `errors: 0` and a frozen `last_sweep_at`, and /healthz never
                # degraded. That is the founding rule-#5 failure with a
                # different noun.
                self.sweep_failures += 1
                self.last_sweep_error = describe_exception(exc)
                print(f"retention: sweep FAILED (will retry): "
                      f"{self.last_sweep_error}", flush=True)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="retention-sweeper",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
```

⚠ **The split into `sweep()` / `_sweep_dir()` is deliberate and is audit F3's
fix.** `sweep()` owns the *"a pass completed"* stamp; `_sweep_dir()` owns the
work. Do not re-merge them — the whole defect was that the early return for a
missing directory skipped the stamp, and a single method invites that back.

> ## ✅ SIGNED OFF BY THE USER, 2026-08-02 — F2's boot guard REFUSES, and that is now a decision rather than the Planner's judgement call
>
> **Recorded because of what it was before.** The paragraph below was written by
> Planner as a *trade it had chosen*, in a plan whose approval box (A1–A4) did
> not cover it — so a Builder or a reviewer could reasonably have read it as
> open and softened it to a warning. It is not open. The user was asked directly
> and elected **refuse**, and the reasoning they accepted is the reasoning to
> quote if it is ever questioned again:
>
> *"currently harmless" is a property of ONE LINE of code staying non-recursive.*
> `glob("*.jsonl")` is what makes `CHAT_GATEWAY_INBOX_DIR=state` safe today — not
> the guard, not the layout. The day someone reaches for `rglob` for an unrelated
> reason, that safety evaporates silently, and **a warning nobody reads becomes
> tenant data loss.** Refusing at boot costs an operator one clear error message
> naming both env vars; the alternative costs the only copy of replies that were
> never delivered.
>
> ⚠ **Do not soften this in review.** Bugs *in* the guard are still findings; the
> strictness is not one. Pinned in both directions by
> `test_a_safe_but_all_in_one_layout_is_refused_on_purpose` and its counterweight
> `test_the_default_sibling_layout_is_NOT_refused`, so neither half can drift.

⚠ **`_check_disjoint` is deliberately STRICTER than the glob requires, and one
plausible config now fails at boot that would not have corrupted anything.**
Measured on the three layouts plus the default: the default (`inbox-data` beside
`state/quarantine`) is **not** refused, but setting
`CHAT_GATEWAY_INBOX_DIR=state` — *"put everything in one place"*, a thing an
operator might reasonably try — **is** refused, even though `glob("*.jsonl")` is
non-recursive and would never have reached `state/quarantine/`. That is the
intended trade: the non-recursive glob is a **property of one line of code**, and
the guarantee it currently carries is the one deletion in this repo with no
second copy. Refusing a layout that is safe-today-by-accident is cheaper than a
future `rglob` making it unsafe silently. The error message names both env vars
so the operator is not left guessing.

**Tests** (new `tests/test_retention.py`):

```python
import datetime as dt

import pytest

from chat_gateway.inbox import Inbox
from chat_gateway.retention import (DEFAULT_RETENTION_DAYS, QUARANTINE_STEM,
                                    RetentionConfigError, RetentionSweeper,
                                    retention_days_from_env, window_for)


def _on(iso_date: str):
    """A fixed retention-key calendar. These tests are about date arithmetic.

    `today_fn`, NOT `now_fn` (audit F1): the window is measured against the same
    calendar `Inbox._audit` names the file in.
    """
    return lambda: dt.date.fromisoformat(iso_date)


def _touch(d, name, text="{}\n"):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)


def test_prunes_past_the_window_and_keeps_inside_it(tmp_path):
    d = tmp_path / "inbox-data"
    _touch(d, "job-hunter-2026-06-01.jsonl")   # 60 days old
    _touch(d, "job-hunter-2026-07-20.jsonl")   # 11 days old
    s = RetentionSweeper(d, days=30, today_fn=_on("2026-07-31"))
    assert s.sweep() == 1
    assert [p.name for p in d.glob("*.jsonl")] == ["job-hunter-2026-07-20.jsonl"]


def test_unrouted_gets_the_shorter_window(tmp_path):
    d = tmp_path / "inbox-data"
    _touch(d, "_unrouted-2026-07-20.jsonl")    # 11 days — inside 30, outside 7
    _touch(d, "job-hunter-2026-07-20.jsonl")
    s = RetentionSweeper(d, days=30, today_fn=_on("2026-07-31"))
    assert s.sweep() == 1
    assert [p.name for p in d.glob("*.jsonl")] == ["job-hunter-2026-07-20.jsonl"]


def test_zero_days_disables_pruning_entirely(tmp_path):
    d = tmp_path / "inbox-data"
    _touch(d, "job-hunter-2020-01-01.jsonl")
    assert RetentionSweeper(d, days=0, today_fn=_on("2026-07-31")).sweep() == 0
    assert list(d.glob("*.jsonl"))


def test_an_unparseable_filename_is_left_alone_never_guessed_at(tmp_path):
    d = tmp_path / "inbox-data"
    _touch(d, "notes.jsonl")
    _touch(d, "job-hunter-not-a-date.jsonl")
    s = RetentionSweeper(d, days=1, today_fn=_on("2026-07-31"))
    assert s.sweep() == 0
    assert len(list(d.glob("*.jsonl"))) == 2


def test_the_quarantine_dir_is_never_swept(tmp_path):
    """The CG-65 gate, pinned: retention points at inbox-data, never at state/."""
    q = tmp_path / "state" / "quarantine"
    _touch(q, "unrevivable-2020-01-01.jsonl")
    RetentionSweeper(tmp_path / "inbox-data", days=1,
                     today_fn=_on("2026-07-31"), quarantine_dir=q).sweep()
    assert (q / "unrevivable-2020-01-01.jsonl").exists()


# -- audit F2: the guarantee above is now a CODE property, not a path accident --

def test_a_quarantine_filename_would_otherwise_parse_as_a_tenant_bucket():
    """Why the two new guards exist, stated as a measurement.

    `unrevivable-<date>.jsonl` is a legal `<app>-<date>.jsonl`, and 'unrevivable'
    does not start with '_', so it would draw the FULL tenant window — not the
    7-day floor. Nothing about the name marks it as untouchable.
    """
    from chat_gateway.retention import _NAME
    m = _NAME.match("unrevivable-2026-07-31.jsonl")
    assert m is not None and m.group("app") == "unrevivable"
    assert window_for("unrevivable", 30) == 30      # NOT the _unrouted floor


def test_the_quarantine_stem_matches_what_inbox_actually_writes(tmp_path):
    """One home for the literal: if `_quarantine` renames its files, this fails."""
    jpath = tmp_path / "inbox.jsonl"
    from chat_gateway.journal import Journal
    Journal(jpath).open(1, "inbound", {"NOT": "an InboundReply"})
    q = tmp_path / "quarantine"
    ibx = Inbox(journal=Journal(jpath), quarantine_dir=q)
    ibx.restore()
    written = next(q.glob("*.jsonl"))
    assert written.name.startswith(QUARANTINE_STEM)


def test_a_quarantine_file_inside_the_sweep_dir_is_skipped_by_name(tmp_path):
    """Belt to `_check_disjoint`'s braces: the layout nobody predicted."""
    d = tmp_path / "inbox-data"
    _touch(d, "unrevivable-2020-01-01.jsonl")      # ancient, and must survive
    _touch(d, "job-hunter-2020-01-01.jsonl")
    s = RetentionSweeper(d, days=30, today_fn=_on("2026-07-31"))
    assert s.sweep() == 1
    assert (d / "unrevivable-2020-01-01.jsonl").exists()


@pytest.mark.parametrize("layout", ["same", "quarantine_under_sweep",
                                    "sweep_under_quarantine"])
def test_construction_refuses_a_sweep_dir_overlapping_the_quarantine(tmp_path, layout):
    """Fails at BOOT, loudly — the opposite posture from a malformed window,
    because a bad window over-retains and a bad directory deletes the only copy."""
    q = tmp_path / "state" / "quarantine"
    sweep = {"same": q,
             "quarantine_under_sweep": tmp_path / "state",
             "sweep_under_quarantine": q / "nested"}[layout]
    q.mkdir(parents=True, exist_ok=True)
    sweep.mkdir(parents=True, exist_ok=True)
    with pytest.raises(RetentionConfigError) as exc:
        RetentionSweeper(sweep, days=30, quarantine_dir=q)
    assert "quarantine" in str(exc.value)


# -- audit F3: a stopped sweeper must not read as a working one ---------------

def test_a_pass_over_a_missing_directory_still_stamps_last_sweep_at(tmp_path):
    """`enabled: true, last_sweep_at: null` used to mean BOTH 'idle' and 'dead'."""
    s = RetentionSweeper(tmp_path / "does-not-exist", days=30)
    assert s.sweep() == 0
    assert s.last_sweep_at is not None


def test_a_failing_sweep_is_counted_not_just_printed(tmp_path, capsys):
    s = RetentionSweeper(tmp_path / "inbox-data", days=30, interval_s=0.01)
    s.sweep = lambda: (_ for _ in ()).throw(RuntimeError("disk gone"))
    s.start()
    try:
        deadline = dt.datetime.now() + dt.timedelta(seconds=3)
        while s.sweep_failures == 0 and dt.datetime.now() < deadline:
            pass
    finally:
        s.stop()
    assert s.sweep_failures >= 1
    assert s.last_sweep_error is not None
    assert "sweep FAILED" in capsys.readouterr().out


def test_an_unlink_failure_is_counted_and_named_through_the_allowlist(tmp_path, capsys):
    """Audit F4: `str(OSError)` embeds the ABSOLUTE path; `describe_exception`
    is this repo's rule for a class `errors.py` does not mark."""
    d = tmp_path / "inbox-data"
    _touch(d, "job-hunter-2020-01-01.jsonl")
    s = RetentionSweeper(d, days=1, today_fn=_on("2026-07-31"))
    import pathlib
    original = pathlib.Path.unlink

    def boom(self, *a, **kw):
        raise PermissionError(13, "Permission denied", str(self))

    pathlib.Path.unlink = boom
    try:
        assert s.sweep() == 0
    finally:
        pathlib.Path.unlink = original
    assert s.errors == 1
    out = capsys.readouterr().out
    assert "job-hunter-2020-01-01.jsonl" in out      # the name IS ours to print
    assert str(d) not in out                          # the absolute path is not


def test_malformed_env_falls_back_to_the_default(capsys):
    assert retention_days_from_env({"CHAT_GATEWAY_INBOX_RETENTION_DAYS": "soon"}) == 30
    assert "not an integer" in capsys.readouterr().out
    assert retention_days_from_env({"CHAT_GATEWAY_INBOX_RETENTION_DAYS": "0"}) == 0
    assert retention_days_from_env({}) == 30
```

⚠ **Builder, on `test_an_unlink_failure_is_counted_and_named_through_the_allowlist`:**
it monkeypatches `pathlib.Path.unlink` by hand so the intent is visible. Use
`monkeypatch.setattr` if this file already has the fixture in scope — the
assertions are the contract, the patching style is not.

⚠ **On `test_a_failing_sweep_is_counted_not_just_printed`:** it drives a real
thread with a 3-second ceiling and a `finally: stop()`. If that reads as flaky in
review, call `_run`'s body once directly instead. What must be pinned either way:
a raising sweep increments `sweep_failures`, sets `last_sweep_error`, and the
loop survives.

## Task 11 — Wire the sweeper

**`src/chat_gateway/__main__.py`** — in `build_runtime`, after `inbox` (which
already computes `state_dir` at `:37` and wires `quarantine_dir` at `:50`):

```python
    from .retention import (RetentionConfigError, RetentionSweeper,
                            retention_days_from_env)

    # CG-68 / ADR-0002 D5. Sweeps the per-app inbound AUDIT trail only — never
    # the quarantine dir, never the delivery log, never the queue journals.
    #
    # `quarantine_dir` is passed for ONE reason: so the sweeper can refuse to
    # run if the two overlap (audit F2). Before this, "never the quarantine dir"
    # was true only because these two env vars happen to point at sibling
    # directories, and nothing in the process compared them — one `.env` edit
    # away from deleting the only copy of replies that were never delivered.
    # It must be the SAME expression as the `Inbox(...)` call above; if that
    # ever moves, hoist it to a local rather than writing it twice.
    try:
        sweeper = RetentionSweeper(
            os.environ.get("CHAT_GATEWAY_INBOX_DIR", "inbox-data"),
            days=retention_days_from_env(),
            quarantine_dir=Path(state_dir) / "quarantine",
        )
    except RetentionConfigError as exc:
        # Re-raised as the type `main` already handles, so a misconfiguration
        # prints `config error: ...` and exits 2 — the same treatment
        # GATEWAY_ENABLE_PUBSUB's missing-companion check gets, rather than a
        # traceback. Refusing to boot is the SAFE direction here; see the class.
        raise RegistryError(str(exc)) from exc
```

Return it from `build_runtime` — the tuple is
`registry, inbox, adapters, subscriber, state_dir` (`__main__.py:76`) and there
is exactly **one** unpack site, `main` at `__main__.py:88`. Extend both to
`registry, inbox, adapters, subscriber, state_dir, sweeper`. ⚠ Re-grep before
editing; `check` and `mint-key` share that unpack.

In the `serve` branch, after `inbox.restore()`:

```python
        swept = sweeper.sweep()
        print(f"retention: inbox audit window is {sweeper.days} day(s) "
              f"({'pruning DISABLED' if sweeper.days == 0 else 'enabled'}); "
              f"removed {swept} expired day-file(s) at boot", flush=True)
        sweeper.start()
```

Pass `sweeper=sweeper` into `create_app` (Task 12 adds the keyword), store it as
`app.state.sweeper` beside `app.state.dispatcher` (`service.py:198-201`), and
stop it where the dispatcher and monitor are stopped.

## Task 12 — `/healthz` counters

Rule #5 — *"does not distinguish work dropped from work deleted."*

**`src/chat_gateway/service.py`** — add the import beside the existing ones, and
accept `sweeper` as a `create_app` keyword defaulting to `None` (same opt-in
posture as `dispatcher` and `subscriber`, so every offline test that builds an
app without one keeps working):

```python
from .retention import window_for
```

Then add the block to the `/healthz` body:

```python
            "retention": (
                {"enabled": sweeper.days > 0,
                 "window_days": sweeper.days,
                 # `window_for`, not a second `min(...)` (audit F5). The floor
                 # rule has ONE home; re-deriving it here is how /healthz ends
                 # up publishing a window the sweeper stopped using. CLAUDE.md's
                 # test count is this repo's own worked example.
                 "unrouted_window_days": window_for("_unrouted", sweeper.days),
                 "files_deleted": sweeper.deleted,
                 "delete_errors": sweeper.errors,
                 # CG-68 audit F3. `last_sweep_at` alone could not tell an idle
                 # sweeper from a dead one, and a raising sweep was printed but
                 # never counted — so the three fields below travel together.
                 "sweep_failures": sweeper.sweep_failures,
                 "last_sweep_error": sweeper.last_sweep_error,
                 "last_sweep_at": sweeper.last_sweep_at}
                if sweeper is not None
                else {"enabled": False, "note": "no sweeper configured"}
            ),
```

⚠ **The reasons block MUST test `enabled` first (audit F0, HIGH).** The first
draft indexed `body["retention"]["delete_errors"]` unconditionally against an
else-branch that has no such key — so `/healthz` raised **`KeyError`** on every
app built without a sweeper, which Task 12 itself says is the normal offline
case. The endpoint hard rule #5 exists to keep honest would not have answered at
all. `service.py:522-523` already shows the correct idiom for the identically
shaped `subscriber` block: bind, then gate on `enabled`.

```python
        ret = body["retention"]
        if ret["enabled"]:
            if ret["delete_errors"]:
                reasons.append(
                    f"retention: {ret['delete_errors']} audit file(s) could not "
                    "be removed — the inbound audit trail is growing past its "
                    "stated window. Check the inbox dir's permissions"
                )
            if ret["sweep_failures"]:
                reasons.append(
                    f"retention: {ret['sweep_failures']} sweep pass(es) FAILED "
                    f"({ret['last_sweep_error']}) — nothing is being pruned, so "
                    "`files_deleted` and `delete_errors` are both sitting at a "
                    "reassuring number while the window is not being enforced. "
                    "The audit trail holds message text and sender addresses"
                )
```

⚠ **`files_deleted` must NOT degrade `status`** — a retention policy working is
not a fault, and degrading on it teaches an operator to ignore `degraded`. Same
reasoning `CLAUDE.md` records for `suppressed_opt_out`. `delete_errors` and
`sweep_failures` **do** degrade: they are the policy *not* working.

⚠ **`last_sweep_error` is on an unauthenticated endpoint** — which is why
`_run` builds it with `describe_exception` (audit F4) and it reaches this line
as a type name, never a filesystem path.

**Tests** (`tests/test_service.py`):

```python
def test_healthz_answers_when_no_sweeper_is_configured(tmp_path):
    """Audit F0: this raised KeyError, taking the whole endpoint down."""
    body = TestClient(_app_with()).get("/healthz").json()
    assert body["retention"] == {"enabled": False, "note": "no sweeper configured"}
    assert "status" in body


def test_healthz_degrades_on_a_sweeper_that_stopped_working(tmp_path):
    s = RetentionSweeper(tmp_path / "inbox-data", days=30)
    s.sweep_failures = 2
    s.last_sweep_error = "PermissionError"
    body = TestClient(_app_with(sweeper=s)).get("/healthz").json()
    assert body["status"] == "degraded"
    assert any("sweep pass(es) FAILED" in r for r in body["reasons"])


def test_healthz_does_not_degrade_merely_because_files_were_deleted(tmp_path):
    s = RetentionSweeper(tmp_path / "inbox-data", days=30)
    s.deleted = 400
    body = TestClient(_app_with(sweeper=s)).get("/healthz").json()
    assert body["retention"]["files_deleted"] == 400
    assert not any("retention" in r for r in body["reasons"])


def test_healthz_publishes_the_unrouted_floor_from_its_one_home(tmp_path):
    s = RetentionSweeper(tmp_path / "inbox-data", days=30)
    body = TestClient(_app_with(sweeper=s)).get("/healthz").json()
    assert body["retention"]["window_days"] == 30
    assert body["retention"]["unrouted_window_days"] == window_for("_unrouted", 30)
```

## Task 13 — The contract amendment

**13a — `integration-guide.md:366-370`.** Promise site 1. Replace *"never
pruned"*:

> - The per-app **JSONL audit** says what **ARRIVED**. One file per app per day,
>   written before anything is queued, and **retained for a bounded window —
>   30 days by default, 7 days for the gateway's own `_unrouted` bucket**,
>   settable per deployment via `CHAT_GATEWAY_INBOX_RETENTION_DAYS` (`0`
>   disables pruning). It holds no terminal records — nothing in it marks a
>   reply as polled — so **your pending queue cannot be reconstructed from it.**
>   It is a forensic record on the gateway host, not something you can re-poll.
>
>   ⚠ **This changed on 2026-07-31, and it changed a published guarantee.** This
>   line previously read *"never pruned."* That was a v0 over-promise on a file
>   holding a person's message text, `sender_email` and whole `raw` event
>   forever. The window is the amendment; the mechanism that makes it safe is
>   the **quarantine** described below, which is never pruned and holds any
>   reply that could not be revived. Reasoning:
>   [ADR-0002](architecture/decisions/2026-07-31-journalled-message-bodies.md)
>   §4.1 and §9 Q6.

**13b — `journal.py:10`.** Promise site 3, same sentence:

```
NOT THE AUDIT TRAIL, and not a replacement for it. The audit files are
per-app-per-day, retained for a bounded window (retention.py), and carry no
TERMINAL records — they say what ARRIVED, never what LEFT, so pending state
cannot be reconstructed from them. Different question, different file; both stay.
```

**13c — env-var NAME** in `.env.example`, `docs/integration-guide.md`,
`aitrader.md:569`'s table, **and `__main__.py`'s module docstring** (`:7-9`
lists the env vars this entrypoint reads and would otherwise be one short).
⚠ **`aitrader.md` gets the row but not a window claim** — aitrader is
`allow_inbound: false` and never reaches `inbox.put` (ADR §2.7), so it has no
records in this directory. Say that, so the tenant does not read a retention
window as applying to something of theirs.

**13d — `docs/consumers/jobhunt.md`.** The one tenant with records in this
directory. State the window and point at the quarantine.

**13e — `docs/integration-guide.md`'s `/healthz` durability table.** Task 9b
took it to **nine fields, six that degrade**. This row adds `retention.*`.
⚠ **Recount against `service.py` rather than trusting either sentence** — that
table has been wrong about its own count twice (CG-64, and Task 8e's five-fields
/ four-reasons trap).

---

## Task 14 — ⚠ The tense flip: five strings that CG-65 made true and this row makes false

**Found by the 2026-08-01 pre-execution audit. Task 13 did not list any of
these, and two of them are on the unauthenticated `/healthz`.**

CG-65's pre-merge review caught three strings asserting a retention window and a
`retention.py` in the **present** tense when neither had shipped — the CG-66
defect shape. It fixed them by rewriting them in the **absent/future** tense.
Those fixes are on `main` (`4fbd634`) and are correct **today**. Every one of
them becomes **false in the opposite direction the moment Task 10 lands** —
because after this row the audit trail *does* carry a retention guarantee, and
the sweeper *does* exist.

**This is a hard rule #5 item, not a docs item, for the same reason CG-65's
quarantine was:** two of the five are `/healthz` `reasons` strings, and an
unauthenticated endpoint that tells an operator *"this file carries no retention
guarantee"* about a file the gateway deletes on a 30-day timer is describing
machinery that does not match the machinery it is running.

⚠ **Do this in the SAME PR as Tasks 10–12.** Splitting it re-creates the exact
window CG-65 spent a review finding closing, just pointed the other way.

| # | File:line (on `4fbd634`) | Says today | Must say after this row |
|---|---|---|---|
| 1 | `service.py:497-499` — `/healthz` `reasons`, the `unrevivable_at_boot` tail's `else` branch | *"the per-app JSONL audit under the inbox dir is the only record of what arrived, and it **carries no retention guarantee**"* | it is the only record **and it is pruned on the retention window**, so the copy may not be there later. ⚠ Keep the branch on `preserved` — that conditional IS the rule-#5 control CG-65 added, and the comment at `service.py:480-487` explains why. Change the tail only |
| 2 | `service.py:506-508` — `/healthz` `reasons`, `quarantine_write_errors` | *"…is its only record and that file **carries no retention guarantee**"* | same correction. This is the louder of the two: the quarantine write already failed, so this really is the last copy, and it now has a delete timer on it |
| 3 | `inbox.py:166-170` — `restore()` docstring | *"…it carries no retention guarantee and must not be relied on as the only copy: **CG-68 puts it on** a time-bounded window. **Future tense deliberately** — that row has not shipped…"* | present tense, and **delete the "Future tense deliberately" sentence** (`:168-170`) — it is scaffolding whose whole purpose was to mark an unshipped control, and leaving it in is a second copy of a fact that just changed. ⚠ Its reference to **CG-66** goes with it; CG-66 is a separate open row and must not be implied to be closed |
| 4 | `inbox.py:197-199` — the boot console line's `else` branch | *"…is the only recovery record, and it **carries no retention guarantee**"* | present tense; name the window's env var so an operator reading the boot log knows how long they have |
| 5 | `inbox.py:266-270` — `_quarantine()` docstring | *"**Never swept: CG-68's retention sweeper must not look** in this directory… **Future tense on purpose** — that row is gated behind this one merging, so **there is no sweeper in this tree yet**"* | present tense — and it can now say something stronger than *"must not"*: **it cannot**. `RetentionSweeper.__init__` refuses an overlapping directory and the loop skips `QUARANTINE_STEM` (audit F2). Point at those two guards by name and delete the future-tense sentence (`:267-270`) |

**Two things Task 14 must NOT do.**

1. ⚠ **`journal.py:10`'s *"never pruned"* is Task 13b, not this task.** Different
   defect (a live over-promise, not a tense marker) and it is already assigned.
   Do not fix it twice and do not leave it to this list.
2. ⚠ **No ⚠ verification-ledger flag is cleared, added or reworded by any of
   this.** None of the five strings is a ledger entry; all five are about
   on-disk retention, and nothing here touches `adapters/` or a Google seam.

**Verify** — this is the grep that finds a missed one:

```bash
grep -rn "carries no retention guarantee\|Future tense\|no sweeper in this tree" src/
```

Must return **nothing** when this task is done. Run it before opening the PR;
it is cheaper than the review that found the first three.

## CG-68 gates

- Suite green. **Base is `4fbd634` / 268** — measured after CG-65 merged, not the
  `~266` this line estimated beforehand. Estimate **268 → ~292** (Task 10's tests
  roughly doubled in the audit, and Task 12 gained four); **measure and report the
  real number.**
- Manual: create dated files by hand in a scratch `inbox-data/`, boot, confirm
  the boot line, the deletions, and that `state/quarantine/` is untouched.
- Manual, audit F2: point `CHAT_GATEWAY_INBOX_DIR` at `state/quarantine` and
  confirm the gateway **refuses to boot** with `config error: retention:
  refusing to sweep …` rather than starting and deleting.
- `grep -rn "never pruned" src/ docs/ --include=*.py --include=*.md` returns
  only the **quarantine** and ADR references.
- `grep -rn "carries no retention guarantee\|Future tense\|no sweeper in this tree" src/`
  returns nothing (Task 14).
- `/healthz` answers **200 with no sweeper configured** (audit F0) — the offline
  test suite is the check, and it must be green before anything else counts.
- No ⚠ flag cleared, added or reworded.
