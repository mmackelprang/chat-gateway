"""Per-app inbound-reply inbox: pending queue + JSONL audit trail.

Delivery semantics (v0, documented in the integration guide): polling an
inbox returns and clears its pending replies — at-most-once to the app. The
JSONL file is the permanent audit record either way, one file per app per
day, so nothing is ever silently lost even if an app drops a poll response.

QUEUE STATE PERSISTS when a `Journal` is supplied; without one it is in-memory,
which is what every offline test constructs. **The audit trail and the journal
are different artifacts answering different questions** — this module's own
first line used to say "in-memory queue + JSONL audit trail", which invites
exactly the wrong conclusion: the AUDIT is durable and says what ARRIVED, the
QUEUE is what is still PENDING, and no audit file records a poll, so pending
state cannot be reconstructed from one. Both stay.

Why this queue and not only the dispatcher's: passive polling is the only
inbound path a tenant that has opted out of `callback_url` has, and a consumer
whose host sleeps can leave a tap sitting here for hours. A restart in that
window is a lost Approve, not a delayed one.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import os
import threading
from collections import defaultdict, deque
from pathlib import Path

from .envelope import InboundReply
from .errors import describe_exception
from .journal import chmod_owner_only


class Inbox:
    def __init__(self, audit_dir: str | Path | None = None, max_pending: int = 1000,
                 journal=None, quarantine_dir: str | Path | None = None):
        self._pending: dict[str, deque[InboundReply]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._audit_dir = Path(audit_dir) if audit_dir else None
        self._max_pending = max_pending
        # None keeps this object exactly what it was before persistence
        # existed, which is what every existing test constructs.
        self._journal = journal
        self._ids = itertools.count(1)
        self._ids_by_app: dict[str, deque[int]] = defaultdict(deque)
        self.dropped = 0  # overflow counter, surfaced by healthz
        self.replayed = 0
        #: Journalled replies that no longer validate as an `InboundReply` at
        #: boot. Counted rather than swallowed: the record is DROPPED and boot
        #: compaction then removes it for good, so without this an envelope
        #: change across a deploy would erase a tap with nobody ever told.
        #: The dispatcher's `unroutable` is the same shape; this is its inbound
        #: twin, and both reach /healthz.
        self.unrevivable = 0
        #: Journal writes that failed on the poll path, where raising would
        #: throw away replies already handed to the consumer. Surfaced at
        #: /healthz (hard rule #5).
        self.journal_write_errors = 0
        #: Where an unrevivable journal record is preserved. None keeps this
        #: object exactly what it was before CG-65, which is what every offline
        #: test constructs — the same opt-in posture as `journal`.
        self._quarantine_dir = Path(quarantine_dir) if quarantine_dir else None
        #: Unrevivable records successfully preserved, and quarantine writes
        #: that failed. Both reach /healthz: a recovery mechanism that has
        #: silently stopped working is worse than none, because it is trusted.
        self.quarantined = 0
        self.quarantine_write_errors = 0

    @property
    def journal(self):
        """The journal, or None. Public so /healthz can read its counters
        without reaching into a private attribute across a module boundary."""
        return self._journal

    def put(self, reply: InboundReply) -> None:
        self._audit(reply)
        entry_id = next(self._ids)
        # Not guarded: if the journal cannot accept the reply, raising sends the
        # failure back up the Pub/Sub dispatch path, where it is counted as a
        # dispatch error and the message is left unacked — so Google redelivers
        # it. Swallowing it here would ack an inbound tap we did not persist.
        if self._journal is not None:
            self._journal.open(entry_id, "inbound", reply.model_dump(mode="json"))
        with self._lock:
            q = self._pending[reply.app]
            ids = self._ids_by_app[reply.app]
            dropped_id = None
            if len(q) >= self._max_pending:
                q.popleft()  # oldest dropped from the queue; audit trail keeps it
                dropped_id = ids.popleft() if ids else None
                self.dropped += 1
            q.append(reply)
            ids.append(entry_id)
        if dropped_id is not None:
            self._journal_write(lambda i=dropped_id: self._journal.close(i, "dropped"),
                                "close")

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

    def restore(self) -> int:
        """Re-populate pending replies from the journal. Returns how many.

        A record that no longer validates is DROPPED, counted in
        `unrevivable`, and named on the console by id — never revived, never
        retried. Dropping is the right call and the count is what makes it
        honest: a record that cannot be parsed today cannot be parsed on the
        next boot either, so keeping it would replay-and-fail forever and the
        journal would never shrink.

        **The quarantine file under the state dir is the recovery record** — the
        whole journal record, payload included, is written there before boot
        compaction erases it, and it is never pruned. The per-app JSONL audit
        beside this queue also holds what arrived, but it carries no retention
        guarantee and must not be relied on as the only copy: CG-68 puts it on a
        time-bounded window. **Future tense deliberately** — that row has not
        shipped, and this repo already carries one open defect (CG-66) for a
        docstring that cites an unshipped control in the present tense.

        The console line names the id and the exception TYPE, never the record.
        A pydantic `ValidationError` embeds the input it rejected, and an
        inbound Chat event carries a per-message capability URL — which is why
        it goes through `describe_exception` (CG-29's allowlist) rather than an
        f-string.
        """
        if self._journal is None:
            return 0
        survivors = self._journal.replay()
        revived: list[dict] = []
        highest = 0
        with self._lock:
            for rec in survivors:
                if isinstance(rec["id"], int):
                    highest = max(highest, rec["id"])
                try:
                    reply = InboundReply(**rec["payload"])
                except Exception as exc:  # noqa: BLE001 — config/envelope drift, not a bug
                    self.unrevivable += 1
                    preserved = self._quarantine(rec)
                    print(f"inbox: journalled reply {rec['id']!r} no longer parses "
                          f"({describe_exception(exc)}) — DROPPED, not delivered; "
                          + ("the whole record was preserved in the quarantine dir "
                             "under the state dir, which is never pruned"
                             if preserved else
                             "NO quarantine copy was written — the per-app JSONL "
                             "audit under the inbox dir is the only recovery "
                             "record, and it carries no retention guarantee"),
                          flush=True)
                    continue
                q = self._pending[reply.app]
                if len(q) >= self._max_pending:
                    # `max_pending` is the memory bound this class advertises, and
                    # boot must not be the one path that ignores it. Reachable
                    # when the cap is LOWERED between runs: a journal written
                    # under the old cap would otherwise restore straight past the
                    # new one. Same rule as `put` — oldest goes, and it is closed
                    # so the next boot does not see it again.
                    q.popleft()
                    ids = self._ids_by_app[reply.app]
                    if ids:
                        dropped_id = ids.popleft()
                        revived = [r for r in revived if r["id"] != dropped_id]
                    self.dropped += 1
                q.append(reply)
                self._ids_by_app[reply.app].append(rec["id"])
                revived.append(rec)
            # Continue the id sequence past anything the journal already used, so
            # a restart cannot mint an id that collides with a live record. Set
            # under the lock with the queues it has to stay consistent with.
            self._ids = itertools.count(highest + 1)
        self._journal_write(lambda: self._journal.compact(revived), "compact")
        self.replayed = len(revived)
        return self.replayed

    def pending_counts(self) -> dict[str, int]:
        with self._lock:
            return {app: len(q) for app, q in self._pending.items() if q}

    def _journal_write(self, fn, op: str) -> bool:
        """Best-effort journal write on a path where raising would lose work.

        `poll` has already emptied the queue and is about to hand the replies
        back; raising here would drop them on the floor. Counting instead means
        the un-closed ids replay on the next boot — a duplicate rather than a
        loss, which is the direction the whole design points.

        Returns whether the write actually happened, so a caller can decline to
        act on a write that did not land. `poll` uses that (CG-65): compacting
        after a FAILED `close_many` would truncate away exactly the `open`
        records that failure left standing for replay, turning the counted
        duplicate this method buys into the silent loss it exists to avoid.
        """
        if self._journal is None:
            return False
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — durability degrades, polling does not stop
            self.journal_write_errors += 1
            print(f"inbox: journal {op} failed ({exc}); "
                  "queue durability is degraded for this entry", flush=True)
            return False
        return True

    def _quarantine(self, rec: dict) -> bool:
        """Preserve an unrevivable journal record before compaction erases it.

        CG-65, answering ADR-0002 §9 Q6. The per-app audit trail used to be the
        only surviving copy of a reply that could not be revived — and CG-68
        prunes that trail on a time bound. This method is what makes the pruning
        safe: the record, PAYLOAD INCLUDED, is already in hand at the drop site,
        so preserving it costs one append. Without it, `restore` drops the
        record and `compact` erases the journal's copy moments later.

        Never swept: CG-68's retention sweeper must not look in this directory,
        and that is the point of it existing. **Future tense on purpose** — that
        row is gated behind this one merging, so there is no sweeper in this
        tree yet; its plan pins the rule with
        `test_the_quarantine_dir_is_never_swept`.

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
