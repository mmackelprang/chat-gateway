"""Dead-man monitor: registered checks that alert on SILENCE.

The watcher lives on the gateway's always-on side precisely because consumer
hosts sleep (the aitrader contract's Feature 2). A check is refreshed by
POST /v1/heartbeat; if no refresh arrives within its schedule + grace, the
monitor emits an alert-severity notification through the normal notify
pipeline (source's alert route), repeating on a backoff (default daily)
until the check refreshes or is deleted.

Schedules (v0):
    "every:<N><s|m|h|d>"  — fixed period
    "daily"               — period of one day
    "weekdays"            — one day, but due dates falling on Sat/Sun roll
                            forward to Monday in the check's timezone
                            (default America/New_York), so weekend silence
                            never false-alarms.
US market holidays are NOT modeled (documented limitation per the contract —
widen `grace` to cover long weekends, e.g. "74h" spans a Monday holiday).

State persists to a JSON file so checks survive gateway restarts.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from .errors import describe_exception

DEFAULT_TZ = "America/New_York"
DEFAULT_REPEAT_S = 86400  # missed-alert repeat backoff: daily

_DURATION = re.compile(r"^(?P<n>\d+)(?P<u>[smhd])$")
_UNIT_S = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class HeartbeatError(ValueError):
    pass


def parse_duration(spec: str) -> int:
    m = _DURATION.match(spec.strip())
    if not m:
        raise HeartbeatError(f"bad duration {spec!r} (use e.g. 90s, 30m, 2h, 1d)")
    return int(m.group("n")) * _UNIT_S[m.group("u")]


def parse_schedule(spec: str) -> tuple[str, int]:
    """Returns (kind, period_seconds); kind ∈ every|daily|weekdays."""
    s = spec.strip().lower()
    if s == "daily":
        return "daily", 86400
    if s == "weekdays":
        return "weekdays", 86400
    if s.startswith("every:"):
        return "every", parse_duration(s.removeprefix("every:"))
    raise HeartbeatError(f"bad schedule {spec!r} (use weekdays | daily | every:<N><s|m|h|d>)")


@dataclass
class Check:
    source: str
    check_id: str
    schedule: str
    grace: str
    tz: str = DEFAULT_TZ
    last_seen: str = ""       # ISO datetime, UTC
    last_alerted: str = ""    # ISO datetime, UTC ('' = never)
    status: str = "ok"        # ok | missed

    def next_due(self) -> dt.datetime:
        kind, period = parse_schedule(self.schedule)
        last = dt.datetime.fromisoformat(self.last_seen)
        due = last + dt.timedelta(seconds=period)
        if kind == "weekdays":
            zone = ZoneInfo(self.tz)
            local = due.astimezone(zone)
            while local.weekday() >= 5:  # Sat=5, Sun=6 roll to Monday
                local += dt.timedelta(days=1)
            due = local.astimezone(dt.timezone.utc)
        return due

    def deadline(self) -> dt.datetime:
        return self.next_due() + dt.timedelta(seconds=parse_duration(self.grace))

    def is_missed(self, now: dt.datetime) -> bool:
        return now > self.deadline()

    def alert_due(self, now: dt.datetime, repeat_s: int = DEFAULT_REPEAT_S) -> bool:
        if not self.is_missed(now):
            return False
        if not self.last_alerted:
            return True
        return now - dt.datetime.fromisoformat(self.last_alerted) >= dt.timedelta(seconds=repeat_s)


class HeartbeatStore:
    def __init__(self, path: str | Path | None = None,
                 now_fn: Callable[[], dt.datetime] | None = None):
        self._path = Path(path) if path else None
        self._now = now_fn or (lambda: dt.datetime.now(dt.timezone.utc))
        self._checks: dict[tuple[str, str], Check] = {}
        self._lock = threading.Lock()
        self._load()

    # -- persistence ----------------------------------------------------------
    def _load(self) -> None:
        if self._path and self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for c in data.get("checks", []):
                check = Check(**c)
                self._checks[(check.source, check.check_id)] = check

    def _save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"checks": [asdict(c) for c in self._checks.values()]},
                                  indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # -- API ------------------------------------------------------------------
    def refresh(self, source: str, check_id: str, schedule: str, grace: str,
                tz: str = DEFAULT_TZ) -> Check:
        parse_schedule(schedule)  # validate early
        parse_duration(grace)
        ZoneInfo(tz)  # raises on unknown tz
        now = self._now()
        with self._lock:
            check = Check(source=source, check_id=check_id, schedule=schedule,
                          grace=grace, tz=tz, last_seen=now.isoformat(),
                          last_alerted="", status="ok")
            self._checks[(source, check_id)] = check
            self._save()
        return check

    def delete(self, source: str, check_id: str) -> bool:
        with self._lock:
            existed = self._checks.pop((source, check_id), None) is not None
            self._save()
        return existed

    def list_for(self, source: str) -> list[Check]:
        with self._lock:
            return [c for (s, _), c in sorted(self._checks.items()) if s == source]

    def due_alerts(self, repeat_s: int = DEFAULT_REPEAT_S) -> list[Check]:
        """Checks whose missed-alert should fire now; marks them alerted."""
        now = self._now()
        fired = []
        with self._lock:
            for check in self._checks.values():
                if check.alert_due(now, repeat_s):
                    check.status = "missed"
                    check.last_alerted = now.isoformat()
                    fired.append(check)
            if fired:
                self._save()
        return fired


class HeartbeatMonitor:
    """Scan loop: due_alerts -> alert-severity notifications via the notify
    pipeline (`notify_fn(source, title, body, dedupe_key)`)."""

    def __init__(self, store: HeartbeatStore, notify_fn,
                 interval_seconds: float = 60.0, repeat_s: int = DEFAULT_REPEAT_S):
        self._store = store
        self._notify = notify_fn
        self._interval = interval_seconds
        self._repeat = repeat_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        #: Was `start()` ever called? NOT cleared by `stop()`. See
        #: `Dispatcher.started` — identical contract, identical reasoning.
        self._started = False
        self.last_scan_at: dt.datetime | None = None
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

    def scan_once(self) -> int:
        fired = self._store.due_alerts(self._repeat)
        for check in fired:
            self._notify(
                check.source,
                f"heartbeat missed: {check.check_id}",
                f"No refresh since {check.last_seen} (schedule {check.schedule}, "
                f"grace {check.grace}). Repeats daily until refreshed or deleted.",
                f"hb:{check.check_id}",
            )
        self.last_scan_at = dt.datetime.now(dt.timezone.utc)
        return len(fired)

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

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="heartbeat-monitor", daemon=True)
        self._started = True
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
