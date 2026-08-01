"""Append-only JSONL journal for queue STATE — the third use of one idiom.

`heartbeat.py` persists JSON atomically (write a sibling `.tmp`, `os.replace`)
and `delivery.py` / `inbox.py` already append JSONL audit lines. This module is
those two primitives applied to queue *state*, and deliberately NOT a third
idiom: no new dependency, one file per queue, readable with `tail` during an
incident.

NOT THE AUDIT TRAIL, and not a replacement for it. The audit files are
per-app-per-day, never pruned, and carry no TERMINAL records — they say what
ARRIVED, never what LEFT, so pending state cannot be reconstructed from them.
Different question, different file; both stay.

Durability is chosen over throughput deliberately: every append is flushed and
fsync'd. The traffic shape this serves is tens of messages a day (the jobhunt
contract's R5), so the cost is invisible and the guarantee is the point.

WHAT REACHES DISK, AND WHY THAT IS NOT A RULE #2 VIOLATION. The journal holds
whole payloads — outbound `text` + `cards`, and whole inbound events including
`raw`. That is CONTENT, and it is more than the delivery log keeps on purpose:
the log is titles-only because it is a permanent record nobody needs the bodies
of, while a queue cannot be replayed without them. What the journal does NOT
hold is any credential: it stores an identity NAME, and `Dispatcher.restore`
re-resolves that name through the registry at boot, so no webhook URL (which
embeds `key`+`token`) and no per-app API key is ever written here. Treat the
file as content-sensitive — it is created 0600, and the deploy runbook puts the
state dir at 0750.

PORTABILITY. The deploy target is Linux and development happens on Windows, so
this module uses only primitives that behave the same on both: no `fcntl`, no
advisory locking (a `threading.Lock` is enough — one process owns each file),
and `os.replace`, which is atomic on POSIX and on Windows. It deliberately does
NOT fsync the containing directory after the rename: that needs an fd on a
directory, which Windows does not provide, and the failure it would guard leaves
the OLD journal in place — a superset of the live set, which replays safely.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
from pathlib import Path
from typing import Callable

SCHEMA_VERSION = 1

#: Appends since the last compaction before one is triggered inline. Boot-time
#: compaction alone is not enough for a process meant to run for weeks — on one
#: that never reboots, boot-only compaction is no compaction at all.
DEFAULT_COMPACT_AFTER = 1000

#: The journal and both audit trails carry message bodies or whole inbound
#: events (see the module docstring, and CG-65), so they are created owner-only.
#: A no-op for group/other on Windows, which is fine: the mode matters on the
#: Linux deploy target.
_FILE_MODE = 0o600


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class JournalWriteError(RuntimeError):
    """A journal append or compaction failed.

    Raised only where refusing the work is the honest answer (enqueue / put).
    On terminal and reschedule paths the caller swallows it and counts it —
    see `Dispatcher._journal_write` for why a failed `close` must never become
    an infinite re-send loop.
    """


class Journal:
    """`open` / `update` / `close` records for one queue.

    Replay is every id with an `open` and no `close`, with the LAST `update`
    applied. Append-only is preserved: a retry APPENDS an `update`, it never
    rewrites the `open`.
    """

    def __init__(self, path: str | Path, *,
                 compact_after: int = DEFAULT_COMPACT_AFTER,
                 now_fn: Callable[[], dt.datetime] | None = None):
        self._path = Path(path)
        self._compact_after = compact_after
        self._now = now_fn or _utcnow
        self._lock = threading.RLock()
        self._since_compaction = 0
        #: Journal lines this PROCESS could not parse, cumulative. Surfaced at
        #: /healthz rather than swallowed — see `replay()` for why they are not
        #: fatal. Compaction re-reads the file without counting (it would count
        #: the same torn line twice), and boot compaction removes the offending
        #: lines anyway, so this stays an honest count of what was lost.
        self.skipped_lines = 0

    @property
    def path(self) -> Path:
        return self._path

    # -- writing --------------------------------------------------------------
    def _append(self, record: dict) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            existed = self._path.exists()
            with self._path.open("a", encoding="utf-8") as fh:
                if not existed:
                    chmod_owner_only(self._path)
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            raise JournalWriteError(f"journal {self._path.name}: {exc}") from exc
        self._since_compaction += 1

    def open(self, entry_id: int, kind: str, payload: dict) -> None:
        with self._lock:
            self._append({"v": SCHEMA_VERSION, "op": "open", "id": entry_id,
                          "kind": kind, "payload": payload,
                          "ts": self._now().isoformat()})

    def update(self, entry_id: int, attempts: int, next_attempt_at: str) -> None:
        """Record a RESCHEDULE.

        `attempts` must survive a restart or a crash-loop resets the backoff
        ladder every time and hammers the far end forever — which turns a
        durability feature into an outage amplifier.
        """
        with self._lock:
            self._append({"v": SCHEMA_VERSION, "op": "update", "id": entry_id,
                          "attempts": attempts, "next_attempt_at": next_attempt_at,
                          "ts": self._now().isoformat()})
            self._maybe_compact_locked()

    def close(self, entry_id: int, status: str) -> None:
        with self._lock:
            self._append({"v": SCHEMA_VERSION, "op": "close", "id": entry_id,
                          "status": status, "ts": self._now().isoformat()})
            self._maybe_compact_locked()

    def close_many(self, entry_ids: list[int], status: str) -> None:
        """Close a whole batch in ONE append, then one fsync.

        `Inbox.poll` hands a batch of replies to a consumer and closes them all.
        Closing them one line at a time means a crash part-way through loses the
        already-closed ones (the consumer never got the response) while replaying
        the rest — a PARTIAL loss, which is the one outcome this row exists to
        avoid. One write means a crash either lands the batch or tears the last
        line, and a torn line is skipped by `replay()`, so its id stays open and
        is replayed. Both outcomes redeliver rather than drop, which is the
        direction the at-least-once contract already points.
        """
        if not entry_ids:
            return
        ts = self._now().isoformat()
        blob = "".join(
            json.dumps({"v": SCHEMA_VERSION, "op": "close", "id": entry_id,
                        "status": status, "ts": ts}, ensure_ascii=False) + "\n"
            for entry_id in entry_ids
        )
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                existed = self._path.exists()
                with self._path.open("a", encoding="utf-8") as fh:
                    if not existed:
                        chmod_owner_only(self._path)
                    fh.write(blob)
                    fh.flush()
                    os.fsync(fh.fileno())
            except OSError as exc:
                raise JournalWriteError(f"journal {self._path.name}: {exc}") from exc
            self._since_compaction += len(entry_ids)
            self._maybe_compact_locked()

    # -- replay ---------------------------------------------------------------
    def replay(self) -> list[dict]:
        """Surviving jobs, oldest first: `open` payloads with their last `update`.

        A line that does not parse is SKIPPED AND COUNTED, wherever it sits in
        the file. A torn trailing line is the EXPECTED shape — a partial write at
        power loss — and a gateway that refuses to boot over a half-written byte
        is a crash loop on a host running `restart: unless-stopped`. Losing one
        record and SAYING SO beats not starting; the count goes to /healthz.
        """
        return self._read(count_skips=True)

    def _read(self, *, count_skips: bool) -> list[dict]:
        if not self._path.exists():
            return []
        live: dict[int, dict] = {}
        order: list[int] = []
        with self._path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    if count_skips:
                        self.skipped_lines += 1
                    continue
                if not isinstance(rec, dict) or "op" not in rec or "id" not in rec:
                    if count_skips:
                        self.skipped_lines += 1
                    continue
                op, entry_id = rec["op"], rec["id"]
                if op == "open":
                    if entry_id not in live:
                        order.append(entry_id)
                    live[entry_id] = {
                        "id": entry_id,
                        "kind": rec.get("kind", ""),
                        "payload": rec.get("payload") or {},
                        "attempts": rec.get("attempts", 0),
                        "next_attempt_at": rec.get("next_attempt_at") or rec.get("ts", ""),
                        "opened_at": rec.get("ts", ""),
                    }
                elif op == "update" and entry_id in live:
                    live[entry_id]["attempts"] = rec.get("attempts", 0)
                    live[entry_id]["next_attempt_at"] = rec.get("next_attempt_at", "")
                elif op == "close":
                    live.pop(entry_id, None)
        return [live[i] for i in order if i in live]

    # -- compaction -----------------------------------------------------------
    def compact(self, survivors: list[dict] | None = None) -> None:
        with self._lock:
            self._compact_locked(survivors)

    def _maybe_compact_locked(self) -> None:
        """Compact inline once enough garbage has accumulated.

        Checked after `update` and `close` and NOT after `open`, because those
        are the only two ops that supersede an earlier line. A journal holding
        nothing but opens is exactly as large as its live set — rewriting it
        would reclaim nothing and churn the disk on a queue that is merely busy.
        """
        if self._since_compaction >= self._compact_after:
            self._compact_locked()

    def _compact_locked(self, survivors: list[dict] | None = None) -> None:
        """Rewrite as one `open` (+ one `update` if attempted) per survivor.

        Atomic, via `heartbeat.py`'s idiom: write a sibling `.tmp`, then
        `os.replace`. A reader either sees the whole old file or the whole new
        one — never a half-written journal, which is the one corruption this
        module must not itself create. `os.replace` gives that on POSIX and on
        Windows alike.

        The guarantee during compaction: the caller holds this lock, so no
        append can interleave; and until `os.replace` returns, the old file is
        the live one. A crash at any point leaves either the pre-compaction
        journal (a superset — replays safely) or the compacted one. It never
        leaves a subset.
        """
        if survivors is None:
            # count_skips=False: this is a re-read of a file whose unparseable
            # lines were already counted at boot. Counting them again would
            # inflate the /healthz number every time the threshold fires.
            survivors = self._read(count_skips=False)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.parent / (self._path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            chmod_owner_only(tmp)
            for job in survivors:
                fh.write(json.dumps({
                    "v": SCHEMA_VERSION, "op": "open", "id": job["id"],
                    "kind": job["kind"], "payload": job["payload"],
                    "next_attempt_at": job["next_attempt_at"],
                    "ts": job.get("opened_at") or self._now().isoformat(),
                }, ensure_ascii=False) + "\n")
                if job["attempts"]:
                    fh.write(json.dumps({
                        "v": SCHEMA_VERSION, "op": "update", "id": job["id"],
                        "attempts": job["attempts"],
                        "next_attempt_at": job["next_attempt_at"],
                        "ts": self._now().isoformat(),
                    }, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self._path)
        self._since_compaction = 0


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
