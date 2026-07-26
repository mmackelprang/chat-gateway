"""Accept-fast delivery: enqueue -> background dispatch with retries -> log.

The aitrader contract sets the semantics: a send returns 2xx on ENQUEUE in
under 2s; the gateway owns retries; consumers never assume guaranteed
receipt (they keep their own fallback log). The delivery log answers "did
the alert actually reach Chat?" per source.

Privacy: the log stores titles and statuses, never bodies or cards (titles
may reference sensitive state; bodies definitely can — aitrader Feature 3).
Queue state is in-memory: a gateway restart drops undelivered jobs, visible
in the log as enqueued-without-terminal-status. Documented, accepted for v0.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .envelope import OutboundMessage
from .registry import Identity

BACKOFF_S = (0, 30, 120, 600, 3600)  # attempt spacing; after the last -> failed


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class DeliveryLog:
    """Per-source ring buffer + JSONL audit. Titles only — never bodies."""

    def __init__(self, audit_dir: str | Path | None = None, keep: int = 200):
        self._entries: dict[str, deque[dict]] = defaultdict(lambda: deque(maxlen=keep))
        self._lock = threading.Lock()
        self._audit_dir = Path(audit_dir) if audit_dir else None
        self._ids = itertools.count(1)

    def record(self, source: str, kind: str, title: str, status: str,
               detail: str = "", entry_id: int | None = None,
               now: dt.datetime | None = None) -> int:
        now = now or _utcnow()
        entry_id = entry_id if entry_id is not None else next(self._ids)
        entry = {"id": entry_id, "ts": now.isoformat(), "source": source, "kind": kind,
                 "title": title[:200], "status": status, "detail": detail[:300]}
        with self._lock:
            self._entries[source].append(entry)
        if self._audit_dir:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            path = self._audit_dir / f"deliveries-{source}-{now.date().isoformat()}.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry_id

    def query(self, source: str, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(self._entries[source])[-limit:]


@dataclass
class Job:
    entry_id: int
    source: str
    kind: str
    identity: Identity
    message: OutboundMessage
    title: str
    attempts: int = 0
    next_attempt_at: dt.datetime = field(default_factory=_utcnow)


class Dispatcher:
    """Background sender. Deterministic core (`process_due`) + a thread loop.

    `adapters` maps identity mode -> adapter with .send(identity, message).
    """

    def __init__(self, adapters: dict, log: DeliveryLog,
                 now_fn: Callable[[], dt.datetime] | None = None,
                 backoff: tuple = BACKOFF_S):
        self._adapters = adapters
        self._log = log
        self._now = now_fn or _utcnow
        self._backoff = backoff
        self._jobs: list[Job] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def enqueue(self, source: str, kind: str, identity: Identity,
                message: OutboundMessage, title: str) -> int:
        entry_id = self._log.record(source, kind, title, "enqueued")
        with self._lock:
            self._jobs.append(Job(entry_id=entry_id, source=source, kind=kind,
                                  identity=identity, message=message, title=title,
                                  next_attempt_at=self._now()))
        return entry_id

    def pending(self) -> int:
        with self._lock:
            return len(self._jobs)

    def process_due(self) -> int:
        """One pass over due jobs. Returns how many were attempted."""
        now = self._now()
        with self._lock:
            due = [j for j in self._jobs if j.next_attempt_at <= now]
        attempted = 0
        for job in due:
            attempted += 1
            adapter = self._adapters.get(job.identity.mode)
            try:
                if adapter is None:
                    raise RuntimeError(f"no adapter for mode {job.identity.mode!r}")
                adapter.send(job.identity, job.message)
            except Exception as exc:  # noqa: BLE001 — categorize, retry or fail
                job.attempts += 1
                if job.attempts >= len(self._backoff):
                    self._finish(job, "failed", f"gave up after {job.attempts} attempts: {exc}")
                else:
                    job.next_attempt_at = now + dt.timedelta(seconds=self._backoff[job.attempts])
                    self._log.record(job.source, job.kind, job.title, "retrying",
                                     f"attempt {job.attempts}: {exc}", entry_id=job.entry_id)
            else:
                self._finish(job, "delivered", f"after {job.attempts + 1} attempt(s)")
        return attempted

    def _finish(self, job: Job, status: str, detail: str) -> None:
        self._log.record(job.source, job.kind, job.title, status, detail,
                         entry_id=job.entry_id)
        with self._lock:
            if job in self._jobs:
                self._jobs.remove(job)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_due()
            except Exception as exc:  # noqa: BLE001 — the loop must survive
                print(f"dispatcher: pass error (will retry): {exc}", flush=True)
            self._stop.wait(1.0)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="delivery-dispatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
