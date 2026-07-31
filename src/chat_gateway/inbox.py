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
import threading
from collections import defaultdict, deque
from pathlib import Path

from .envelope import InboundReply


class Inbox:
    def __init__(self, audit_dir: str | Path | None = None, max_pending: int = 1000,
                 journal=None):
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
        #: Journal writes that failed on the poll path, where raising would
        #: throw away replies already handed to the consumer. Surfaced at
        #: /healthz (hard rule #5).
        self.journal_write_errors = 0

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
        # One append for the whole batch, so a crash part-way cannot close some
        # of a poll's replies and replay the rest — see Journal.close_many.
        self._journal_write(lambda: self._journal.close_many(ids, "polled"), "close_many")
        return items

    def restore(self) -> int:
        """Re-populate pending replies from the journal. Returns how many."""
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
                except Exception:  # noqa: BLE001 — a record we cannot revive is not fatal
                    continue
                self._pending[reply.app].append(reply)
                self._ids_by_app[reply.app].append(rec["id"])
                revived.append(rec)
        # Continue the id sequence past anything the journal already used, so a
        # restart cannot mint an id that collides with a live record.
        self._ids = itertools.count(highest + 1)
        self._journal_write(lambda: self._journal.compact(revived), "compact")
        self.replayed = len(revived)
        return self.replayed

    def pending_counts(self) -> dict[str, int]:
        with self._lock:
            return {app: len(q) for app, q in self._pending.items() if q}

    def _journal_write(self, fn, op: str) -> None:
        """Best-effort journal write on a path where raising would lose work.

        `poll` has already emptied the queue and is about to hand the replies
        back; raising here would drop them on the floor. Counting instead means
        the un-closed ids replay on the next boot — a duplicate rather than a
        loss, which is the direction the whole design points.
        """
        if self._journal is None:
            return
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — durability degrades, polling does not stop
            self.journal_write_errors += 1
            print(f"inbox: journal {op} failed ({exc}); "
                  "queue durability is degraded for this entry", flush=True)

    def _audit(self, reply: InboundReply) -> None:
        if self._audit_dir is None:
            return
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        day = dt.date.today().isoformat()
        path = self._audit_dir / f"{reply.app}-{day}.jsonl"
        record = reply.model_dump(mode="json")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
