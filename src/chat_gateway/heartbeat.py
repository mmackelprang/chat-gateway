"""Dead-man monitor: registered checks that alert on SILENCE.

The watcher lives on the gateway's always-on side precisely because consumer
hosts sleep (the aitrader contract's Feature 2). A check is refreshed by
POST /v1/heartbeat; if no refresh arrives within its schedule + grace, the
monitor emits an alert-severity notification through the normal notify
pipeline (source's alert route), repeating on an ESCALATING backoff
(`repeat_after`: 1d, 2d, 4d, then weekly) until the check refreshes or is
deleted.

MESSAGE POLICY (CG-86). Every message about a check — the thread root, the
first alert, each reminder, and the recovery notice — carries ONE
`thread_key` (`thread_key_for`), because the check is the durable subject the
owner's chat policy threads on. Titles lead with the source and carry the
DELTA (`[<source>] heartbeat <id> — still missed, 7d02h`), never a severity
word: the gateway's own `severity_prefix()` supplies that, and a title that
repeats it renders it twice. This module composes those strings; `service.py`
routes and renders them.

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
import hashlib
import json
import re
import threading
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from .errors import describe_exception

DEFAULT_TZ = "America/New_York"
DEFAULT_REPEAT_S = 86400  # missed-alert repeat backoff: the FIRST interval, 1d

#: The ceiling `repeat_after` escalates to: one week. Past here an unchanged
#: check is a standing fact, not news, and the policy's "never post an
#: unchanged state" outweighs the reminder — but it is a CEILING, never a
#: suppression: the reminder keeps arriving, weekly, carrying a fresh elapsed
#: delta in its title. CG-86 D5 refuses plain suppression explicitly.
MAX_REPEAT_S = 604800

#: `notifications.Notification.thread_key`'s `max_length`, and
#: `Notification.title`'s. Declared here rather than imported so that this
#: module keeps importing nothing from the render layer it composes for; both
#: are pinned against the real pydantic fields by
#: `test_the_composition_caps_match_the_notification_model`, so they cannot
#: drift silently.
#:
#: THE CAPS ARE LOAD-BEARING, NOT TIDINESS (CG-86 D1). A `ValidationError`
#: raised inside `service._monitor_notify` is not an `HTTPException`, so it
#: escapes to `scan_once`'s per-check `except`, is counted undeliverable, and
#: the alert is never sent FOR THE LIFE OF THAT CHECK. Neither `source` nor
#: the rendered elapsed delta is length-bounded anywhere upstream — the
#: registry puts no cap on an app id — so both a long source and a long
#: `check_id` (`HeartbeatIn` allows 100) have to be absorbed here.
MAX_THREAD_KEY_LEN = 128
MAX_TITLE_LEN = 200

_DURATION = re.compile(r"^(?P<n>\d+)(?P<u>[smhd])$")
_UNIT_S = {"s": 1, "m": 60, "h": 3600, "d": 86400}

#: How far `repeat_after` will ever shift before the ceiling binds. Bounding
#: the EXPONENT rather than the product keeps a check missed for years from
#: turning a backoff lookup into arbitrary-precision arithmetic: with
#: `base >= 1`, `2 ** MAX_REPEAT_S.bit_length()` already exceeds the ceiling,
#: so no larger shift can change the answer.
_MAX_BACKOFF_SHIFT = MAX_REPEAT_S.bit_length()


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


# --- CG-86 message-policy primitives -----------------------------------------

def thread_key_for(source: str, check_id: str) -> str:
    """The one thread every message about this check belongs to.

    `hb:<source>:<check_id>` — the durable subject is the CHECK, which is why
    the key is derived from its identity and from nothing that moves. A
    percentage, a timestamp or an alert ordinal in here would start a new
    thread on every post, which is the defect CG-86 exists to close.

    ⚠ CAPPED, AND THE CAP IS THE POINT. See `MAX_THREAD_KEY_LEN` for what an
    over-long key costs. On overflow the key is truncated and given a
    `-<sha256(full)[:8]>` tail, so two distinct checks whose keys share a
    128-character prefix still get two threads rather than silently sharing
    one. The digest is over the FULL key, never over the truncated head — the
    head is exactly what the colliding pair has in common.
    """
    full = f"hb:{source}:{check_id}"
    if len(full) <= MAX_THREAD_KEY_LEN:
        return full
    tail = "-" + hashlib.sha256(full.encode("utf-8")).hexdigest()[:8]
    return full[:MAX_THREAD_KEY_LEN - len(tail)] + tail


def repeat_after(alert_count: int, base: int = DEFAULT_REPEAT_S) -> int:
    """How long to wait before the NEXT reminder, given how many have gone out.

    `min(base * 2 ** (alert_count - 1), MAX_REPEAT_S)` — 1d, 2d, 4d, then
    weekly forever (CG-86 D5). `alert_count <= 1` is `base`: nothing has been
    sent yet, or exactly one has, and the first reminder is due on the plain
    window.

    ⚠ IT ONLY EVER LENGTHENS THE INTERVAL, which is what preserves
    `test_repeat_window_must_exceed_the_dedupe_window` a fortiori: the
    dead-man path's repeat window was already strictly longer than the
    deduper's, and backoff cannot bring it back down.

    The observed defect this replaces was four consecutive days of
    byte-identical top-level alerts on a check that had not changed state in
    seven. Suppression was refused as the remedy — a stale check would go
    invisible — so what changes is the CADENCE, while every reminder still
    carries a fresh elapsed delta in its title.
    """
    if alert_count <= 1:
        return base
    shift = min(alert_count - 1, _MAX_BACKOFF_SHIFT)
    return min(base * 2 ** shift, MAX_REPEAT_S)


def format_elapsed(seconds: float) -> str:
    """A duration in the owner's chat-policy spelling: `45m`, `2h14m`, `7d02h`.

    Two significant units, largest first, the smaller zero-padded — the shape
    the policy's own examples use (`stalled 2h14m`, `ETA slipped 9d07h`). Under
    a minute it degrades to seconds so that a fast `every:30s` check does not
    report a real outage as `0m`.

    Truncating, never rounding: `1d23h59m` reads `1d23h`, and a duration that
    has not yet reached the next unit must never be reported as though it had.
    A negative input (a clock that went backwards) clamps to zero rather than
    rendering a minus sign into a chat title.
    """
    total = int(max(0.0, seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d{hours:02d}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"


def _utc_stamp(moment: dt.datetime) -> str:
    """The `2026-08-31T15:47:52Z` line every threaded reply opens with.

    ONE TIMEZONE, NAMED — the policy's own rule. `moment` is converted rather
    than assumed: the monitor's clock is UTC in every deployment, and a body
    that silently printed a local time under a `Z` would be worse than one
    that printed the offset.
    """
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _title(source: str, subject: str, delta: str) -> str:
    """`[<app>] <subject> - <what changed>`, capped at `MAX_TITLE_LEN`.

    ⚠ NO SEVERITY WORD AND NO SEVERITY EMOJI. `notifications.severity_prefix()`
    is prepended to this by the renderer, so a title carrying its own severity
    renders it twice — which is exactly what the owner's policy forbids and
    what the observed defect showed (`⚠️ 🔴 [ALERT] heartbeat missed: ...`).

    ⚠ THE CAP IS A DROPPED-ALERT GUARD, not cosmetic. `MAX_TITLE_LEN` says
    what an overflow costs. Truncation takes the TAIL because the head is the
    identifying half — `[source] heartbeat <check_id>` — and losing the
    elapsed delta from a title still leaves the body, which carries it in
    full and is four thousand characters wide.
    """
    full = f"[{source}] {subject} — {delta}"
    if len(full) <= MAX_TITLE_LEN:
        return full
    return full[:MAX_TITLE_LEN - 1] + "…"


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
    #: Has this check's chat thread been opened? CG-86 D3. Set only after a
    #: thread-root message is ACCEPTED for delivery, so a root that could not
    #: be posted is retried rather than assumed.
    #:
    #: ⚠ NOT the `/healthz` field of the same name. `heartbeats.thread_started`
    #: there is the MONITOR THREAD's lifecycle flag (`HeartbeatMonitor.started`,
    #: an OS thread); this is a chat thread on ONE check and is never published
    #: at `/healthz`. Two different objects, one English word.
    #:
    #: ⚠ IT MUST SURVIVE `refresh()`, which builds a brand-new `Check` on every
    #: call — that is its documented semantics, and a field left to this default
    #: would re-post a thread root on EVERY heartbeat ping. `refresh` carries it
    #: over explicitly;
    #: `test_the_thread_root_is_posted_once_per_check_and_not_after_a_refresh`
    #: pins it. (That name was wrong here until 2026-08-31 — it cited a test
    #: that has never existed, so the pin it promises was unverifiable by
    #: anyone following the citation.)
    thread_started: bool = False
    #: How many alerts this outage has produced. Drives `repeat_after`'s
    #: escalating backoff, and distinguishes the first miss from a reminder.
    #: RESET by `refresh` (a recovery ends the outage, so the next one starts a
    #: fresh ladder) — unlike `thread_started`, which does not.
    alert_count: int = 0

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
        """Should this check alert on this scan?

        ⚠ THE FIRST TRANSITION INTO `missed` IS UNCONDITIONAL — `last_alerted`
        is empty and this returns True regardless of the backoff. CG-86 changed
        the CADENCE OF REMINDERS and nothing else; a check that has just gone
        silent still alerts on the very next scan, and no backoff, ceiling or
        alert count can delay it.

        `repeat_s` is the FIRST interval, not the flat one. `repeat_after`
        escalates it by `alert_count`.
        """
        if not self.is_missed(now):
            return False
        if not self.last_alerted:
            return True
        window = dt.timedelta(seconds=repeat_after(self.alert_count, repeat_s))
        return now - dt.datetime.fromisoformat(self.last_alerted) >= window

    def thread_key(self) -> str:
        return thread_key_for(self.source, self.check_id)

    def elapsed_since_seen(self, now: dt.datetime) -> str:
        """How long this check has been silent, in the policy's spelling."""
        last = dt.datetime.fromisoformat(self.last_seen)
        return format_elapsed((now - last).total_seconds())


# --- CG-86 message composition -----------------------------------------------
#
# Four messages, one thread. Every body opens with its own UTC timestamp line
# and closes with an `Action:` line — including when the action is `none`,
# because "no action needed" is information and silence is not (the owner's
# chat policy, §Hygiene). The thread ROOT is the one exception to the timestamp
# line: it is a Thread Title, not a reply, and the policy gives it its own
# fixed shape, quoted in `thread_root_message` below.

def thread_root_message(check: Check) -> tuple[str, str]:
    """(title, body) for the message that OPENS a check's thread.

    Posted lazily, at the first alert rather than at registration: a check that
    never misses must never post anything. Rendered `info` (quiet) and routed
    `alert` (CG-86 D2), so it lands in the same space as the alert it is about
    — threading is per-space, and a root in another room threads nothing.
    """
    key = check.thread_key()
    title = f"[{check.source}] 🧵 Heartbeat {check.check_id}"
    body = (
        f"Subject: dead-man check {check.check_id} for {check.source} "
        f"(schedule {check.schedule}, grace {check.grace}, tz {check.tz}).\n"
        f"Closes when: the check refreshes, or is deleted.\n"
        f"Identifiers: source {check.source}, check_id {check.check_id}, "
        f"thread {key}.\n"
        f"Action: none — this message opens the thread."
    )
    return title[:MAX_TITLE_LEN], body


def alert_message(check: Check, now: dt.datetime,
                  repeat_s: int = DEFAULT_REPEAT_S) -> tuple[str, str]:
    """(title, body) for a missed-check alert — first miss or reminder.

    ⚠ A REMINDER IS NOT AN "UNCHANGED STATE" POST, which is what makes it
    policy-legal: its title carries the elapsed delta, so two reminders about
    one outage are never byte-identical. The observed CG-86 defect was four
    that were.

    The two are distinguished by `alert_count`, not by `status`: `status` is
    already `missed` by the time a reminder is composed, so branching on it
    would call every alert a reminder.
    """
    elapsed = check.elapsed_since_seen(now)
    first = check.alert_count == 0
    subject = f"heartbeat {check.check_id}"
    title = _title(check.source, subject,
                   f"missed, no refresh for {elapsed}" if first
                   else f"still missed, {elapsed}")
    nxt = format_elapsed(repeat_after(check.alert_count + 1, repeat_s))
    # ⚠ `alert_count`, NOT `alert_count + 1`. The count is how many alerts have
    # ALREADY gone out, so the first reminder — the second alert — is reminder
    # ONE. It was labelled `(reminder 2)` until 2026-08-31: a human-facing
    # ordinal that started at two, because it was counting alerts under a word
    # that means something else.
    lead = (f"missed, no refresh for {elapsed}" if first
            else f"still missed, {elapsed} (reminder {check.alert_count})")
    body = (
        f"{_utc_stamp(now)} · {lead}\n"
        f"No refresh since {check.last_seen} (schedule {check.schedule}, "
        f"grace {check.grace}, tz {check.tz}).\n"
        f"Next reminder in {nxt} if it is still missed.\n"
        f"Action: refresh this check, or delete it if the job is retired."
    )
    return title, body


def recovery_message(previous: Check, now: dt.datetime) -> tuple[str, str]:
    """(title, body) for the missed -> ok transition. CG-86 D6.

    `previous` is the check as it stood BEFORE the refresh — the refresh has
    already replaced it in the store, and `last_seen` on the new one is `now`,
    which would make every outage report as zero. The elapsed figure is the
    length of the SILENCE: the old `last_seen` to now.

    Rendered `info` (the policy's quiet lane) and routed `alert`, so it threads
    under the alert it closes. That routing is not a nicety: `RESOLVED` is quiet
    ONLY because it threads under an alert the reader was already notified
    about, so an all-clear in a different space is an all-clear nobody sees.
    """
    elapsed = previous.elapsed_since_seen(now)
    title = _title(previous.source, f"heartbeat {previous.check_id}",
                   f"recovered after {elapsed}")
    body = (
        f"{_utc_stamp(now)} · recovered after {elapsed}\n"
        f"A refresh arrived; the check is ok again (schedule "
        f"{previous.schedule}, grace {previous.grace}, tz {previous.tz}).\n"
        f"Action: none — this closes the missed-check alert above."
    )
    return title, body


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
        """Read the persisted checks. UNKNOWN KEYS ARE IGNORED, DELIBERATELY.

        ⚠ THIS IS A ROLLBACK GUARD, AND IT POINTS FORWARD — say which
        direction, because the obvious reading is the one it cannot deliver. It
        does NOT rescue a rollback to a PRE-CG-86 image: that image ships its
        own `_load`, which is `Check(**c)`, and it will still die inside
        `create_app` with (MEASURED on 3.10.12) `TypeError: Check.__init__()
        got an unexpected keyword argument 'thread_started'` — a boot failure
        on a file this release wrote. Nothing committed here can change code
        that already shipped.

        What it does buy: from this release on, a state file written by a
        NEWER one loads, so the next field addition cannot turn a rollback to
        this image into a boot failure the way CG-86's two fields would have.
        It is the same posture as `normalize_event`'s two envelope formats —
        tolerate what you can name, and do not let an unknown extra be fatal.

        ⚠ IT IS NOT A VALIDATOR AND MUST NOT BE READ AS ONE. The values of the
        keys it DOES know are still unchecked — `scan_once`'s docstring records
        that a corrupt `last_seen` makes selection raise before the loop is
        entered, and that residue is untouched here. Only the KEY SET is
        filtered.
        """
        if self._path and self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            known = {f.name for f in fields(Check)}
            for c in data.get("checks", []):
                check = Check(**{k: v for k, v in c.items() if k in known})
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
    def now(self) -> dt.datetime:
        """The store's clock, readable by the monitor that composes messages.

        `scan_once` needs it to render an elapsed delta against the same clock
        `due_alerts` selected on — a message that said "no refresh for 7d02h"
        off the wall clock while the check was selected off an injected one
        would be untestable and, on a fake clock, wrong. `last_scan_at` still
        uses real wall time, deliberately: it is a LIVENESS stamp for
        `/healthz`, not a fact about a check.
        """
        return self._now()

    def refresh(self, source: str, check_id: str, schedule: str, grace: str,
                tz: str = DEFAULT_TZ) -> Check:
        """Register or refresh a check. A thin wrapper — see `refresh_seen`.

        Kept at this exact signature and return type on purpose: every existing
        caller and test uses it, and CG-86 needed only the ONE extra fact
        `refresh_seen` returns.
        """
        return self.refresh_seen(source, check_id, schedule, grace, tz)[0]

    def refresh_seen(self, source: str, check_id: str, schedule: str, grace: str,
                     tz: str = DEFAULT_TZ) -> tuple[Check, Check | None]:
        """Refresh, and hand back the check as it stood BEFORE this call.

        Returns `(new_check, previous)`; `previous` is `None` when there was no
        such check, which is how a registration is told from a refresh.

        ⚠ A SNAPSHOT COPY, NOT THE STORED OBJECT, AND NOT MERELY ITS STATUS.
        CG-86 D6 specifies "a method returning `(new_check, previous_status)`",
        and a bare status is not enough to build the message it exists for: the
        recovery title is "recovered after <elapsed>", whose elapsed is the old
        check's `last_seen` to now, and the old `last_seen` is gone from the
        store the instant this method returns. Handing back the LIVE object
        instead would re-open the CG-76 window from the other side — a
        concurrent `mark_alerted` holding that same object from an earlier
        `due_alerts` can stamp `status = "missed"` onto it after the caller
        reads it. `dataclasses.replace` freezes every field under the lock, so
        the caller's transition test reads what was true at the swap.

        ⚠ THE PREVIOUS STATUS IS READ UNDER THE SAME LOCK THAT WRITES THE NEW
        CHECK, and that is the whole reason this method exists rather than a
        `list_for` read at the call site. CG-86 D6 emits the recovery notice on
        the missed -> ok TRANSITION only; reading the old status outside the
        lock lets two concurrent pings both observe `missed` and both post an
        all-clear, or lets a scan interleave and make one of them observe `ok`
        and post nothing.

        ⚠ `thread_started` IS CARRIED OVER AND NOTHING ELSE IS. This method
        keeps `refresh`'s documented semantics — a brand-new `Check`, so a
        refresh clears `status` and `last_alerted` and may change `schedule`,
        `grace` or `tz` in place — and that construct-fresh property is load
        bearing beyond readability: it is what makes the CG-76 selection race
        safe (`test_a_refresh_between_selection_and_marking_leaves_the_check_ok`).
        `alert_count` therefore resets: a recovery ENDS an outage, and the next
        one starts its backoff ladder from the top. `thread_started` does not,
        because the thread's durable subject is the CHECK, not the outage —
        letting it reset would re-post a thread root on every ping.
        """
        parse_schedule(schedule)  # validate early
        parse_duration(grace)
        ZoneInfo(tz)  # raises on unknown tz
        now = self._now()
        with self._lock:
            previous = self._checks.get((source, check_id))
            check = Check(source=source, check_id=check_id, schedule=schedule,
                          grace=grace, tz=tz, last_seen=now.isoformat(),
                          last_alerted="", status="ok",
                          thread_started=bool(previous and previous.thread_started))
            self._checks[(source, check_id)] = check
            self._save()
            snapshot = replace(previous) if previous is not None else None
        return check, snapshot

    def delete(self, source: str, check_id: str) -> bool:
        with self._lock:
            existed = self._checks.pop((source, check_id), None) is not None
            self._save()
        return existed

    def list_for(self, source: str) -> list[Check]:
        with self._lock:
            return [c for (s, _), c in sorted(self._checks.items()) if s == source]

    def list_all(self) -> list[Check]:
        """Every check, regardless of source. For /healthz's census only.

        Deliberately NOT exposed through any HTTP route: `GET /v1/heartbeat/
        {source}` is per-source and authorization-checked, and this would be a
        cross-tenant read. `/healthz` uses it to COUNT, never to name.
        """
        with self._lock:
            return list(self._checks.values())

    def due_alerts(self, repeat_s: int = DEFAULT_REPEAT_S) -> list[Check]:
        """Checks whose missed-alert should fire now. **Mutates NOTHING.**

        THE MUTATION USED TO LIVE HERE, AND THAT WAS CG-76. This method set
        `status = "missed"` and `last_alerted = now` under the lock and then
        `_save()`d, all BEFORE returning to `HeartbeatMonitor.scan_once` — the
        caller that actually notifies. The mark is a promise about the future
        ("an alert will be sent") persisted as a statement about the past ("an
        alert was sent"), and every way the future failed to arrive dropped the
        alert for the whole `DEFAULT_REPEAT_S` window with `/healthz` green.
        Six such ways were measured; five of them raise nothing at all, and one
        moves no /healthz field whatsoever. See the spec's §2.

        Selecting is now free of side effects, so a caller may call it, fail,
        and call it again. `mark_alerted` is the second half.
        """
        now = self._now()
        with self._lock:
            return [c for c in self._checks.values() if c.alert_due(now, repeat_s)]

    def mark_alerted(self, checks: list[Check]) -> None:
        """Record that these checks' alerts were ACCEPTED for delivery.

        Called by `scan_once` with only the checks whose notify actually got as
        far as the durable queue — never with a check whose alert was refused,
        deduped, or raised. Empty list is a no-op and does not touch the disk.

        AT-LEAST-ONCE, DELIBERATELY. If `_save()` raises here — or the process
        dies between the notify and this call — the check is not marked and the
        next scan alerts AGAIN. That is a duplicate, not a drop, and it is the
        posture every neighbouring mechanism in this repo already took for the
        reason each of them records: `_finish`'s mid-flight window
        (delivery.py, "losing an alert is the worse failure"), `_journal_write`
        ("at most one duplicate on the next boot"), and `Inbox._audit` (unacked,
        so Google redelivers). A duplicate reminder costs one redundant phone
        notification; a dropped one costs the whole feature, silently, for
        `repeat_after(alert_count)` — 24h only at the first rung, and up to a
        WEEK at `MAX_REPEAT_S`. ⚠ That figure read a flat "24 hours" and quoted
        the retired `heartbeat missed: <id>` title until 2026-08-31; CG-86's
        own backoff widened the cost of a drop by up to 7×, which makes THIS
        argument stronger, not weaker. It is the whole justification for
        leaving `_save()` unguarded below, so the number has to be the real
        one.

        `_save()` stays UNGUARDED on purpose. It is now on the far side of the
        notify, so raising is honest — the alert is already queued and the raise
        costs at most a duplicate. Wrapping it would re-create CG-76 in a
        quieter form.
        """
        if not checks:
            return
        now = self._now().isoformat()
        with self._lock:
            for check in checks:
                check.status = "missed"
                check.last_alerted = now
                # CG-86 D5. The backoff ladder's rung, advanced in the SAME
                # place and under the SAME lock as the timestamp it is read
                # beside — `alert_due` compares `now - last_alerted` against
                # `repeat_after(alert_count)`, so a count that moved without
                # the stamp (or the reverse) would compute a window against a
                # rung nothing had reached.
                check.alert_count += 1
            self._save()

    def mark_thread_started(self, checks: list[Check]) -> None:
        """Record that these checks' thread ROOTS were accepted for delivery.

        Same at-least-once posture as `mark_alerted`, and the same unguarded
        `_save()`, for the same reason: on the far side of the notify, so a
        raise costs at most a duplicate thread root on the next scan rather
        than a thread that never opens.

        ⚠ CALLED AFTER `mark_alerted`, NEVER BEFORE. Both saves are unguarded,
        so the first one to raise stops the second. Marking the root first
        would leave a delivered alert unmarked and re-fire it every scan
        interval for as long as the disk stayed full — an unbounded re-send
        storm, which is the failure `mark_alerted`'s own docstring cites
        `_journal_write` about. Failing this way round costs one duplicate
        root instead.
        """
        if not checks:
            return
        with self._lock:
            for check in checks:
                check.thread_started = True
            self._save()


class HeartbeatMonitor:
    """Scan loop: due_alerts -> notifications via the notify pipeline.

    `notify_fn(source, title, body, dedupe_key, thread_key, *, severity="alert")`
    -> bool, where the bool is whether the message was ACCEPTED for delivery
    (CG-76).

    ⚠ `severity` IS THE RENDER SEVERITY, NOT THE ROUTE. Every message this
    monitor emits is ROUTED as `alert` by the `notify_fn` — CG-86 D2 — because
    severity selects the destination SPACE as well as the rendering, and
    threading is per-space: a thread root or an all-clear rendered AND routed
    `info` would land in a different Chat room from the alert it belongs to,
    where nobody watching that alert would ever see it. This parameter moves
    only the rendering.
    """

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
        #: one. `Dispatcher`'s twin — with ONE deliberate asymmetry:
        #: `scan_failures` is CUMULATIVE **and degrading**, where
        #: `Dispatcher.pass_failures` is cumulative and inert.
        #:
        #: ⚠ THE ORIGINAL REASON FOR THAT ASYMMETRY EXPIRED WITH CG-76. It read:
        #: "a failed SCAN is not [recoverable] — `due_alerts` marks the check
        #: before persisting, and `scan_once` only notifies what `due_alerts`
        #: returned, so a raise leaves the check marked alerted and the alert
        #: never sent." That was true and measured when CG-74 shipped it. CG-76
        #: reordered exactly that: the mark now happens in `mark_alerted`, AFTER
        #: the notify is accepted, so a scan that raises has NOT marked the
        #: check and the next scan re-fires it. A failed scan is now
        #: RECOVERABLE — which is precisely the property that makes
        #: `pass_failures` inert.
        #:
        #: IT STAYS DEGRADING ANYWAY, AND THE REASON IS NOW THE WEAKER ONE —
        #: say so rather than keep quoting the strong one (the discipline
        #: CLAUDE.md applies to `__cg_action__`). A loop that keeps raising is
        #: still a dead-man monitor that is not completing scans, on aitrader's
        #: contract surface, and the conservative posture there is to degrade.
        #: What a raise now risks is a DELAYED or DUPLICATED alert, not a lost
        #: one. Flipping this to inert is defensible after CG-76 and is
        #: deliberately NOT done here — it is a separate user decision with its
        #: own measurement, not a fold-in (spec §7.2).
        #:
        #: THIS IS NOT THE DROPPED-ALERT COUNTER. `alerts_undeliverable` is.
        #: An alert can be dropped with nothing raising at all.
        self.scan_failures = 0
        self.consecutive_scan_failures = 0
        #: See `Dispatcher.last_pass_error` — same helper, same reasoning.
        self.last_scan_error: str | None = None
        #: CG-76. Alerts that came due and could NOT be accepted for delivery,
        #: over the life of the process. This is the counter `scan_failures`
        #: was mistaken for: a dead-man alert can be dropped WITHOUT any scan
        #: raising, and three separate paths do it (spec §2.2–§2.4) — a notify
        #: refused for want of a route, and a notify deduped against an earlier
        #: outage's alert. Both return normally, so nothing else sees them.
        #:
        #: ⚠ COUNTS ATTEMPTS, NOT DISTINCT ALERTS — and the docstring here said
        #: otherwise until the CG-76 pre-merge review. It read: "CUMULATIVE and
        #: DEGRADING. Cumulative because *an alert refused now is not re-sent by
        #: a later scan once the check is eventually marked*". The italicised
        #: half is FALSE, and §4.3's self-heal design is what falsifies it: a
        #: refused alert leaves the check UNMARKED precisely so it re-fires, so
        #: a permanently routeless check is re-attempted on EVERY scan. Measured
        #: at the 60s default: one increment (and one `GET /v1/deliveries` line)
        #: per scan — ~1440/day for ONE misconfigured check.
        #:
        #: What is true instead: this is the count of alert ATTEMPTS that were
        #: not accepted for delivery. `checks_undeliverable` beside it is the
        #: number of distinct checks in that state on the last scan, and is the
        #: number an operator should read as "how big is this".
        #:
        #: STILL CUMULATIVE, STILL DEGRADING, and the reason is the second half
        #: of the old sentence rather than the first: this names a guarantee
        #: BREAKING on aitrader's contract surface — the exact opposite of
        #: `suppressed_opt_out`, which names a guarantee WORKING and is
        #: correctly inert (CG-12). A number that only ever grew while a source
        #: was unmonitored is the honest shape for that, even when it grows a
        #: thousand times for one fault; the re-attempt cadence it counts is
        #: required by §4.3 and must not be retuned to make this number smaller.
        #:
        #: ⚠ PER ALERT ATTEMPT, never derived from `check.status` (spec §6b,
        #: D4c). That shape is what closes door 6 — the 24h repeat that moved
        #: zero /healthz fields — so "simplifying" it into a check-state
        #: derivation looks like tidying and silently reopens it.
        #:
        #: A BARE INTEGER. No app id, no check id: /healthz is unauthenticated
        #: and CG-12 rejected metadata-only records on exactly that ground. The
        #: operator who needs to know WHICH check reads the authenticated
        #: `GET /v1/deliveries`, where `_monitor_notify` already writes the
        #: identifying line.
        self.alerts_undeliverable = 0
        #: The same fact as a GAUGE: how many checks were undeliverable on the
        #: LAST scan. Returns to 0 when the registry is fixed, so it is the live
        #: signal beside the cumulative history — `RetentionSweeper`'s split,
        #: and CG-74 measured why one number cannot do both jobs.
        self.checks_undeliverable = 0

    def scan_once(self) -> int:
        """One pass: select due checks, notify each, mark only what was accepted.

        Returns how many alerts were ACCEPTED for delivery — not how many were
        due. The two used to be the same number because marking happened before
        notifying; they are different now, and the difference is the point.

        PER CHECK, NOT PER BATCH, and the reason is cross-tenant. `fired` can
        hold checks owned by DIFFERENT apps — the store is gateway-wide, keyed
        (source, check_id). Before CG-76 this loop had no `try` inside it, so
        one app's failing notify aborted the loop and left every LATER check
        unnotified while `due_alerts` had already marked all of them alerted.
        Measured: a routeless `job-hunter` check suppressed `aiteam-harness`'s
        dead-man alert for 24h. That is the isolation instinct hard rules #4
        and #6 apply to inbound, and it costs one `try`.

        ⚠ THE ISOLATION COVERS THE NOTIFY, AND ONLY THE NOTIFY. This docstring
        used to promise, flatly, that one app's failure cannot strand another —
        which overclaims what the per-check `try` delivers. SELECTION is still
        shared fate: `due_alerts`'s comprehension calls `alert_due -> is_missed
        -> deadline -> next_due`, which runs `parse_schedule`, `fromisoformat`,
        `parse_duration` and `ZoneInfo` on the PERSISTED fields, and `_load`
        validates none of them. So one corrupt row in `heartbeats.json` makes
        selection raise before the loop is ever entered, and NO tenant is
        notified on that scan.

        That residue is deliberately left as-is here and is NOT a silent door:
        the raise reaches `_run`, `scan_failures` and `consecutive_scan_failures`
        move, `last_scan_error` is set and `/healthz` degrades — spec §2.11's
        posture. Hardening selection itself is adjacent to CG-77 and is not
        folded in here.
        """
        fired = self._store.due_alerts(self._repeat)
        now = self._store.now()
        accepted: list = []
        rooted: list = []
        undeliverable = 0
        first_error: Exception | None = None
        for check in fired:
            try:
                # ⚠ INSIDE THE `try`, and it sat outside it until 2026-08-31.
                # CG-76's invariant is that one check cannot strand another,
                # and that invariant is POSITIONAL: every line in this loop
                # body has to be under the isolation, or the isolation is a
                # property of where somebody happened to put a statement.
                # Honest about reachability rather than overclaiming — no
                # JSON-representable `source` or `check_id` is known to make
                # `thread_key_for` raise (an f-string and a sha256 accept
                # anything `json.loads` produces), so this is moved for the
                # invariant and NOT because a raise was found.
                key = check.thread_key()
                if not check.thread_started:
                    # CG-86 D3. The Thread Title, posted once per check, before
                    # the alert that will reply to it.
                    #
                    # ⚠ ITS OWN `try`, AND THAT IS THE WHOLE DESIGN OF THIS
                    # BLOCK. A root that cannot be posted must not be able to
                    # strand the ALERT — the alert is the thing this feature
                    # exists to deliver, and a decorative message swallowing it
                    # would be a new CG-76-class silent door opened by the fix
                    # for one. So the root's failure is captured and the alert
                    # is attempted regardless.
                    #
                    # ⚠ A FAILED ROOT DOES **NOT** INCREMENT
                    # `alerts_undeliverable`. That counter is documented as
                    # alert ATTEMPTS not accepted for delivery, and a thread
                    # root is not an alert; feeding it in would inflate the
                    # dropped-ALERT number with something no alert was lost to.
                    # It is not thereby invisible. A root and its alert share
                    # one ROUTE — both are routed `alert` (D2) — so a route
                    # refusal refuses the alert one line later and IS counted;
                    # and a root that RAISES sets `first_error`, degrading
                    # /healthz through `scan_failures` exactly as any other
                    # per-check failure does.
                    #
                    # ⚠ THEY DO NOT SHARE A RENDER SEVERITY, and this comment
                    # claimed they shared "one route and one severity" until
                    # 2026-08-31. The universal form is false and the exception
                    # is live: `Notification`'s `_info_fits_one_text_field`
                    # validator applies to `info` and NOT to `alert`, so a root
                    # can be refused by validation where its alert passes on
                    # the identical strings. MEASURED — the root's title caps
                    # at 200 and its body carries the source twice, the
                    # check_id twice and the ≤128 thread key against
                    # `info_max_combined_length()` = 3989, so the shortest
                    # breaching app id is 1,621 characters at `check_id` = 100,
                    # and the registry caps app ids nowhere. Unreachable in
                    # practice, and narrowed rather than machined: such a root
                    # RAISES, so `first_error` still degrades /healthz, and
                    # what goes uncounted is only the ALERT-shaped counter —
                    # which is exactly the intent.
                    try:
                        root_title, root_body = thread_root_message(check)
                        if self._notify(check.source, root_title, root_body,
                                        None, key, severity="info"):
                            rooted.append(check)
                    except Exception as exc:  # noqa: BLE001 — never strand the alert
                        if first_error is None:
                            first_error = exc
                title, body = alert_message(check, now, self._repeat)
                if self._notify(
                    check.source,
                    title,
                    body,
                    # NO DEDUPE KEY — CG-76 door 4, and the removal is total
                    # rather than retuned. `alert_due()` IS this path's dedupe:
                    # it already guarantees at most one alert per check per
                    # `DEFAULT_REPEAT_S` (86400s). `Deduper`'s window is
                    # `DEFAULT_DEDUPE_WINDOW_S` (3600s). Since 86400 > 3600 the
                    # deduper can NEVER suppress an actual duplicate here — the
                    # monitor does not emit one — so every suppression it
                    # performed on this path was a FALSE POSITIVE. Measured: a
                    # source that died, recovered, refreshed its check, and died
                    # again inside the hour produced TWO outages and ONE alert.
                    # This is not a control with a trade-off; it is a control
                    # with no upside case. Pinned by
                    # `test_repeat_window_must_exceed_the_dedupe_window`.
                    None,
                    # ⚠ THE SAME THREAD KEY AS THE ROOT AND THE RECOVERY. One
                    # thread per durable subject, and the subject is the check.
                    key,
                ):
                    accepted.append(check)
                else:
                    # The notify returned WITHOUT accepting — a route refusal
                    # (spec §2.2) or a dedupe (§2.4). Not an exception, so it
                    # must be counted here or it is invisible. The check is NOT
                    # marked, so it re-fires next scan and self-heals the moment
                    # the registry is fixed.
                    undeliverable += 1
            except Exception as exc:  # noqa: BLE001 — one tenant must not strand another
                undeliverable += 1
                if first_error is None:
                    first_error = exc
        # COUNTERS BEFORE `mark_alerted`, and that ordering is a fix, not a
        # style choice. `mark_alerted`'s `_save()` is UNGUARDED by design, so it
        # can raise — and while it sat above these two lines, a scan in which an
        # alert was genuinely lost AND the disk was full discarded the loss
        # permanently: `alerts_undeliverable` never took the increment, and the
        # `checks_undeliverable` GAUGE stuck at the previous scan's value, so
        # /healthz went on reporting checks as unroutable against a registry
        # that was fine. That is the exact class of dishonest number this row
        # exists to remove (hard rule #5).
        #
        # The ordering constraint the comment below states is `mark_alerted`
        # before the RE-RAISE. It says nothing about the counters, and nothing
        # requires them to be second.
        self.alerts_undeliverable += undeliverable
        self.checks_undeliverable = undeliverable
        # Mark BEFORE re-raising: the alerts that DID get accepted must not be
        # re-sent because a different check failed.
        self._store.mark_alerted(accepted)
        # AFTER `mark_alerted`, never before — `mark_thread_started`'s docstring
        # carries the measurement of what the other order costs.
        self._store.mark_thread_started(rooted)
        if first_error is not None:
            raise first_error
        self.last_scan_at = dt.datetime.now(dt.timezone.utc)
        return len(accepted)

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
                # cumulative and degrading on purpose — see `__init__`, which
                # is the one home of WHY. ⚠ This comment used to restate that
                # reason ("the alert that scan would have sent is already
                # gone") and CG-76 falsified it: the check is no longer marked
                # before the notify, so a raising scan re-fires next pass.
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
