"""Accept-fast delivery: enqueue -> background dispatch with retries -> log.

The aitrader contract sets the semantics: a send returns 2xx on ENQUEUE in
under 2s; the gateway owns retries; consumers never assume guaranteed
receipt (they keep their own fallback log). The delivery log answers "did
the alert actually reach Chat?" per source.

Privacy: the log stores titles and statuses, never bodies or cards (titles
may reference sensitive state; bodies definitely can — aitrader Feature 3).

Queue state PERSISTS when a `Journal` is supplied (`state/queue/delivery.jsonl`),
which is what the deployed gateway does; without one it stays in-memory, which is
what every offline test does. Replay is open-minus-close with the attempt count
preserved. A job whose send may or may not have reached Google at kill time is
REPLAYED and may therefore deliver twice — Chat has no idempotency key, notify
dedupe collapses repeats within its window, and losing an alert is the worse
failure. A job older than `REPLAY_MAX_AGE_S` is closed as `expired` at boot
rather than posted: an alert from three days ago, delivered now, actively
misleads. The journal holds whole payloads and this log does not — that
asymmetry is deliberate, and journal.py explains it.
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
from .journal import chmod_owner_only
from .registry import Identity

BACKOFF_S = (0, 30, 120, 600, 3600)  # attempt spacing; after the last -> failed

#: Replayed jobs older than this are closed as `expired` at boot, not sent. Both
#: outcomes are bad; this is the visible one.
REPLAY_MAX_AGE_S = 86400.0


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_ts(value, fallback: dt.datetime) -> dt.datetime:
    """An ISO timestamp out of the journal, or `fallback`.

    Tolerant on purpose: the journal is a file an operator may have looked at,
    and a boot path that raises on a malformed timestamp is a crash loop for the
    same reason a torn line is (journal.py). A naive timestamp is read as UTC —
    subtracting one from an aware `now` raises TypeError, which is exactly the
    boot-time failure this must not have.
    """
    if not isinstance(value, str) or not value:
        return fallback
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


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
        return entry_id

    def query(self, source: str, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(self._entries[source])[-limit:]

    def advance_ids_past(self, highest: int) -> None:
        """Continue the id sequence past anything the journal already used.

        Without this a restarted gateway mints id 1 for its first new
        notification while a replayed job is still carrying id 1, and the two
        share a line in the delivery log an operator is reading to find out what
        the restart did.
        """
        if highest > 0:
            self._ids = itertools.count(highest + 1)


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
                 backoff: tuple = BACKOFF_S,
                 journal=None,
                 replay_max_age_s: float = REPLAY_MAX_AGE_S):
        self._adapters = adapters
        self._log = log
        self._now = now_fn or _utcnow
        self._backoff = backoff
        # None keeps this object exactly what it was before persistence existed,
        # which is what every existing test constructs. Opt-in, not opt-out.
        self._journal = journal
        self._replay_max_age_s = replay_max_age_s
        self._jobs: list[Job] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.replayed = 0
        self.expired = 0
        self.unroutable = 0
        #: Journal writes that FAILED on a path where raising would be worse.
        #: Surfaced at /healthz: a durable queue whose durability has silently
        #: stopped working is worse than an in-memory one, because it is
        #: trusted (hard rule #5).
        self.journal_write_errors = 0

    @property
    def journal(self):
        """The journal, or None. Public so /healthz can read its counters
        without reaching into a private attribute across a module boundary."""
        return self._journal

    def _journal_write(self, fn: Callable[[], None], op: str) -> bool:
        """Best-effort journal write on a path where raising is the worse bug.

        A failed `close` must NEVER propagate: `_finish` would abort before
        removing the job from `_jobs`, the loop would retry the same job a
        second later, and a full disk would become an unbounded re-send storm
        against Google. Counting it instead costs at most one duplicate on the
        next boot — the same at-least-once outcome replay already has — and the
        counter is what keeps the degradation visible.

        Returns whether the write actually happened, so a caller can decline to
        act on a write that did not land. `_finish` uses that (CG-65):
        compacting after a FAILED `close` would truncate away the very `open`
        record the failure left standing for replay, converting a counted
        degradation into a silent loss.
        """
        if self._journal is None:
            return False
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — durability degrades, delivery does not stop
            self.journal_write_errors += 1
            print(f"dispatcher: journal {op} failed ({exc}); "
                  "queue durability is degraded for this entry", flush=True)
            return False
        return True

    def enqueue(self, source: str, kind: str, identity: Identity,
                message: OutboundMessage, title: str) -> int:
        entry_id = self._log.record(source, kind, title, "enqueued")
        now = self._now()
        # Deliberately NOT wrapped in _journal_write: if the journal cannot
        # accept the job, the honest answer is to refuse it, so the caller's 5xx
        # tells the consumer its alert was not accepted and the consumer's own
        # fallback log takes over (the aitrader contract). Accepting work we
        # cannot persist, on a queue advertised as durable, is the silent
        # failure this row exists to remove.
        if self._journal is not None:
            self._journal.open(entry_id, kind, {
                "source": source, "kind": kind, "identity": identity.name,
                "message": message.model_dump(mode="json"), "title": title,
            })
        with self._lock:
            self._jobs.append(Job(entry_id=entry_id, source=source, kind=kind,
                                  identity=identity, message=message, title=title,
                                  next_attempt_at=now))
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
                    self._journal_write(
                        lambda j=job: self._journal.update(
                            j.entry_id, j.attempts, j.next_attempt_at.isoformat()),
                        "update")
                    self._log.record(job.source, job.kind, job.title, "retrying",
                                     f"attempt {job.attempts}: {exc}", entry_id=job.entry_id)
            else:
                self._finish(job, "delivered", f"after {job.attempts + 1} attempt(s)")
        return attempted

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
        # Gated on `closed` as well: if the `close` above did not land, this
        # job's `open` line is still the queue's record of it, and truncating
        # would turn a counted durability failure into a silent loss.
        if drained and closed:
            self._journal_write(lambda: self._journal.compact([]), "compact")

    def restore(self, registry) -> tuple[int, int]:
        """Re-queue what the journal says never finished.

        Returns `(restored, not_restored)`, where `not_restored` is `expired +
        unroutable`. The two are counted separately on the instance because they
        mean different things to an operator: one is age, the other is a
        permission the registry no longer grants.

        Identities are RE-RESOLVED from the registry rather than revived from
        the journal: the journal stores an identity NAME, and the registry is
        the only thing that knows whether that app may still send as it (hard
        rule #4). A job whose app or identity has since been removed, or whose
        allowlist no longer covers it, is closed as `unroutable` — never sent on
        the strength of a permission the registry no longer grants.
        """
        if self._journal is None:
            return (0, 0)
        now = self._now()
        restored = expired = unroutable = 0
        highest = 0
        survivors: list[dict] = []
        for rec in self._journal.replay():
            payload = rec["payload"]
            entry_id = rec["id"]
            if isinstance(entry_id, int):
                highest = max(highest, entry_id)
            source = payload.get("source", "")
            title = payload.get("title", "")
            kind = payload.get("kind", rec.get("kind", ""))
            opened = _parse_ts(rec.get("opened_at"), now)
            if (now - opened).total_seconds() > self._replay_max_age_s:
                self._log.record(source, kind, title, "expired",
                                 f"older than {self._replay_max_age_s:.0f}s at restart "
                                 "— not delivered", entry_id=entry_id)
                self._journal_write(lambda i=entry_id: self._journal.close(i, "expired"),
                                    "close")
                expired += 1
                continue
            try:
                identity = registry.identity_for(source, payload.get("identity", ""))
                message = OutboundMessage(**payload["message"])
            except Exception as exc:  # noqa: BLE001 — config drift, not a bug
                self._log.record(source, kind, title, "unroutable",
                                 f"not restored after restart: {exc}", entry_id=entry_id)
                self._journal_write(lambda i=entry_id: self._journal.close(i, "unroutable"),
                                    "close")
                unroutable += 1
                continue
            job = Job(entry_id=entry_id, source=source, kind=kind, identity=identity,
                      message=message, title=title, attempts=rec["attempts"],
                      next_attempt_at=_parse_ts(rec.get("next_attempt_at"), now))
            with self._lock:
                self._jobs.append(job)
            survivors.append(rec)
            restored += 1
        # Boot-time compaction: the file is only READ here, so this is the point
        # at which everything terminal can go.
        self._journal_write(lambda: self._journal.compact(survivors), "compact")
        self._log.advance_ids_past(highest)
        self.replayed, self.expired, self.unroutable = restored, expired, unroutable
        return (restored, expired + unroutable)

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
