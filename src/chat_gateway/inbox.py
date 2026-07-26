"""Per-app inbound-reply inbox: in-memory queue + JSONL audit trail.

Delivery semantics (v0, documented in the integration guide): polling an
inbox returns and clears its pending replies — at-most-once to the app. The
JSONL file is the permanent audit record either way, one file per app per
day, so nothing is ever silently lost even if an app drops a poll response.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from collections import defaultdict, deque
from pathlib import Path

from .envelope import InboundReply


class Inbox:
    def __init__(self, audit_dir: str | Path | None = None, max_pending: int = 1000):
        self._pending: dict[str, deque[InboundReply]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._audit_dir = Path(audit_dir) if audit_dir else None
        self._max_pending = max_pending
        self.dropped = 0  # overflow counter, surfaced by healthz

    def put(self, reply: InboundReply) -> None:
        self._audit(reply)
        with self._lock:
            q = self._pending[reply.app]
            if len(q) >= self._max_pending:
                q.popleft()  # oldest dropped from the queue; audit trail keeps it
                self.dropped += 1
            q.append(reply)

    def poll(self, app_id: str) -> list[InboundReply]:
        with self._lock:
            q = self._pending[app_id]
            items = list(q)
            q.clear()
        return items

    def pending_counts(self) -> dict[str, int]:
        with self._lock:
            return {app: len(q) for app, q in self._pending.items() if q}

    def _audit(self, reply: InboundReply) -> None:
        if self._audit_dir is None:
            return
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        day = dt.date.today().isoformat()
        path = self._audit_dir / f"{reply.app}-{day}.jsonl"
        record = reply.model_dump(mode="json")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
