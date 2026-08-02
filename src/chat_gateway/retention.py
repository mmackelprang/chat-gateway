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

WHAT THIS NEVER TOUCHES — and, since audit F2, what enforces each one. The
mechanism is named per line on purpose: a reader must be able to point at the
code for any guarantee stated here.
  - `<state_dir>/quarantine/` — the preserved copy of a reply that could not be
    revived (CG-65). Pruning it would delete the last copy of something that was
    never delivered, which is the whole reason ADR-0002 §9 Q6 was a gate.
    **Enforced TWICE, in code:** `_check_disjoint` refuses a sweep directory
    that is, contains or sits inside it, and `_sweep_dir` skips
    `QUARANTINE_STEM` by name. Belt and braces on purpose — this is the one
    deletion in this repo with no second copy anywhere.
  - `<state_dir>/deliveries/` — titles-only and permanent by decision (D7).
    **Enforced by PATH only.** Its day-files match `_NAME` (see below), so the
    path guard is the whole of it.
  - `<state_dir>/queue/` — the journals compact themselves. **Path, plus an
    accident of naming that is worth stating rather than relying on:**
    `inbox.jsonl` and `delivery.jsonl` carry no `<app>-<date>` stem, so `_NAME`
    does not match them either way.
The path guard is ONE check covering all three — `_check_disjoint` refuses a
sweep directory overlapping the WHOLE state dir, which is where all three live.
The quarantine keeps its own path check beside it, running first, purely so an
operator who trips both gets the message naming the artifact with no second copy.

⚠ THAT LIST USED TO BE TRUE ONLY BY WHERE THE PATHS HAPPEN TO POINT (audit F2,
2026-08-01). It read as an enforced property and was not one. Measured: the
quarantine's own `unrevivable-<date>.jsonl` MATCHES `_NAME` below with
`app='unrevivable'` — which does not start with `_`, so it would draw the FULL
tenant window, not the 7-day floor — and `deliveries-<source>-<date>.jsonl`
matches too, with `app='deliveries-<source>'`. Nothing but a non-recursive glob
and two sibling directories stood between a one-line env change and deleting the
only copy of replies that were never delivered.

⚠ AND THE FIRST FIX ONLY COVERED ONE OF THE THREE (pre-merge review,
2026-08-02). It fenced the quarantine twice, then closed with *"it is now
enforced twice, in code"* — a sentence about the whole list, backed by two
quarantine-only mechanisms. Measured: `CHAT_GATEWAY_INBOX_DIR=state/deliveries`
is a SIBLING of `state/quarantine`, so both guards passed, the sweeper unlinked
the delivery log's day-files, and `files_deleted` — deliberately not a fault —
published it at `/healthz` as the feature working. The guard now refuses any
overlap with the state dir itself, which is a strict superset of the quarantine
check: the only NEW refusals are directories inside the state dir, which are
exactly the dangerous ones.

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

#: Multiples of the sweep interval tolerated before `/healthz` calls the last
#: completed pass stale. Shaped like `service._stale_after` but with NO floor
#: constant beside it, and that is the difference between the two loops rather
#: than an omission: the subscriber polls every few seconds, where a bare
#: multiple would flap on one slow poll, so it carries a 300s floor. This one
#: runs every six hours, so 2x is already twelve hours of grace. Six — the
#: subscriber's multiple — would be a day and a half of a dead sweeper going
#: unreported.
SWEEP_STALE_INTERVAL_MULTIPLE = 2

_NAME = re.compile(r"^(?P<app>.+)-(?P<date>\d{4}-\d{2}-\d{2})\.jsonl$")

#: `inbox.py::_quarantine`'s filename stem. Skipped by name as well as by path
#: (audit F2): `unrevivable-<date>.jsonl` matches `_NAME` cleanly as an app
#: called "unrevivable", and it would draw the full tenant window. One home for
#: the literal — if `_quarantine` ever renames its files, this constant is the
#: thing that has to move with it, and a test pins the pair.
QUARANTINE_STEM = "unrevivable-"


def _overlaps(a: Path, b: Path) -> bool:
    """Do these two RESOLVED directories contain one another, either way round?

    One home for the containment test, because `_check_disjoint` now applies it
    twice and a second copy of a comparison is how the two answers drift apart.
    Both arguments must already be `resolve()`d — `.parents` is a pure string
    walk and would be fooled by a symlink otherwise, which is the whole reason
    the callers resolve.
    """
    return a == b or b in a.parents or a in b.parents


class RetentionConfigError(ValueError):
    """The sweep directory overlaps something that must never be swept.

    Raised at construction, so it lands at boot and not six hours later on a
    thread. `retention_days_from_env` deliberately does the OPPOSITE for a
    malformed window — falls back and says so — and the asymmetry is the point:
    a bad window over-retains, which is recoverable, while a bad directory
    deletes the only copy of replies that were never delivered, which is not.

    ⚠ Deliberately NOT a `GatewayAuthoredError`, and this is the reason so it is
    not relitigated in review: it mirrors `RegistryError` (`registry.py`, also a
    plain `ValueError`), it is raised at boot and printed by `main`'s
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
        # The NAME, never the value. Not a hard-rule-#2 breach — a retention
        # window is not a credential, and this goes to the console rather than
        # `/healthz` — but it was the only place in this package that echoed an
        # env var's value at all, and `install_url_redaction` guards the
        # `logging` module, not `print`. The message loses nothing: an operator
        # who set the variable can read it back themselves.
        print("retention: CHAT_GATEWAY_INBOX_RETENTION_DAYS is not an integer — "
              f"using the default of {DEFAULT_RETENTION_DAYS} days", flush=True)
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
                 quarantine_dir: str | Path | None = None,
                 state_dir: str | Path | None = None, today_fn=None):
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
        #: The whole state dir, not just the quarantine under it (pre-merge
        #: review, 2026-08-02). Optional so every existing caller and test that
        #: passes only `quarantine_dir` keeps the narrower — and strictly
        #: weaker — check; `build_runtime` passes both.
        self._state = Path(state_dir).resolve() if state_dir else None
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        #: Files deleted since start, unlinks that failed, and whole passes that
        #: raised. All three reach /healthz: hard rule #5 does not distinguish
        #: work DROPPED from work DELETED, and a silent deletion path on an
        #: artifact two documents called "the only copy" is exactly the shape of
        #: failure it exists for.
        #:
        #: SEPARATE numbers rather than one, for CLAUDE.md's stated reason (the
        #: `suppressed_opt_out` / `suppressed_not_authorized` split): they are
        #: different investigations. `errors` is one file the OS refused to
        #: delete — the trail grows past its window. `sweep_failures` is the
        #: whole pass dying, which means NOTHING is being pruned and the counter
        #: above will sit reassuringly at zero while it happens.
        #:
        #: `sweep_failures` is CUMULATIVE and `consecutive_sweep_failures`
        #: resets on the next good pass — the same split `SubscriberLoop` draws
        #: between `poll_failures` and `consecutive_poll_failures`, and for the
        #: same measured reason (pre-merge review, 2026-08-02). Only the
        #: consecutive one may drive `/healthz`'s `status`: a cumulative count
        #: never returns to zero, so one transient failure that recovered
        #: pinned `degraded` for the life of the process — and printed the
        #: already-cleared `last_sweep_error` as the literal "(None)" while the
        #: sweeper was demonstrably still pruning. `errors` stays cumulative AND
        #: degrading on purpose: a file the OS refused is still sitting there
        #: past its window until a human intervenes, so there is nothing for a
        #: later pass to "recover" from.
        self.deleted = 0
        self.errors = 0
        self.sweep_failures = 0
        self.consecutive_sweep_failures = 0
        #: A `datetime`, not the ISO string it used to be — `/healthz` has to
        #: compare it to the clock, and `service.py` serializes it exactly where
        #: it serializes `SubscriberLoop.last_poll_at`. Kept as one attribute
        #: rather than a datetime beside a pre-rendered string: two copies of a
        #: moving fact is this repo's own recorded lesson (CLAUDE.md's test
        #: count), and the sibling loop already establishes the idiom.
        self.last_sweep_at: dt.datetime | None = None
        self.last_sweep_error: str | None = None
        self._check_disjoint()

    def _check_disjoint(self) -> None:
        """Refuse a sweep directory that overlaps the state dir (audit F2).

        Both paths come from operator-settable env vars (`CHAT_GATEWAY_INBOX_DIR`
        and `CHAT_GATEWAY_STATE_DIR`) and nothing else in the process compares
        them. `resolve()` on both, so a symlink or a `..` cannot walk around it.

        Checked in BOTH directions, and neither is hypothetical padding: the
        sweep dir being the quarantine deletes preserved replies outright, and
        the quarantine sitting under the sweep dir is one `rglob` refactor away
        from the same thing.

        TWO CHECKS, QUARANTINE FIRST, so the strongest message wins when both
        apply. The quarantine's message is the one an operator most needs to
        read, and it is the one a test pins by the word "quarantine".

        ⚠ REFUSE rather than warn, and STRICTER than the non-recursive glob
        strictly requires — a **signed-off user decision, 2026-08-02**, not an
        open judgement call, so do not soften it in review. `glob("*.jsonl")`
        never descends, so `CHAT_GATEWAY_INBOX_DIR=state` (an operator putting
        everything in one place) would not corrupt anything **today** and is
        nonetheless refused at boot. The reasoning the user accepted: "currently
        harmless" is a property of one line of code staying non-recursive, and
        the guarantee that line carries is the one deletion in this repo with no
        second copy anywhere. A warning nobody reads becomes tenant data loss
        the day someone reaches for `rglob`. The message names both env vars so
        the operator is not left guessing which one to move.

        ⚠ THE STATE-DIR CHECK WIDENS THAT DECISION, it does not narrow it
        (pre-merge review, 2026-08-02). Every layout the quarantine check
        refused is still refused; the only ADDITIONS are directories inside the
        state dir — `state/deliveries`, `state/queue` — which are precisely the
        ones the docstring's "what this never touches" list promised and the
        quarantine check silently missed. `CHAT_GATEWAY_INBOX_DIR=state` was
        already refused (as the quarantine's parent), so the strictness the user
        signed off on is untouched. The shipped `inbox-data`-beside-`state`
        layout is a sibling pair and still boots; a test pins that.
        """
        if self._dir is None:
            return
        swept = self._dir.resolve()
        if self._quarantine is not None and _overlaps(swept, self._quarantine):
            raise RetentionConfigError(
                f"retention: refusing to sweep {swept} — it overlaps the "
                f"quarantine at {self._quarantine}, which holds the only copy of "
                "replies that were never delivered (CG-65). Point "
                "CHAT_GATEWAY_INBOX_DIR and CHAT_GATEWAY_STATE_DIR at "
                "directories that do not contain one another"
            )
        if self._state is not None and _overlaps(swept, self._state):
            raise RetentionConfigError(
                f"retention: refusing to sweep {swept} — it overlaps the state "
                f"dir at {self._state}, which holds the queue journals (they "
                "carry whole message bodies), the delivery log and the "
                "quarantine. None of those is this sweeper's to prune, and the "
                "delivery log's day-files match its filename key exactly. Point "
                "CHAT_GATEWAY_INBOX_DIR and CHAT_GATEWAY_STATE_DIR at "
                "directories that do not contain one another"
            )

    @property
    def days(self) -> int:
        return self._days

    @property
    def interval_seconds(self) -> float:
        """The configured sweep interval, readable by `/healthz`.

        Public for the same reason `SubscriberLoop.interval_seconds` is:
        staleness is only judgeable relative to how often this loop is
        *supposed* to run, and `service.py` must not hardcode a copy that
        drifts from the constructor argument.
        """
        return self._interval_s

    @property
    def audit_dir_configured(self) -> bool:
        """Is there an audit directory to sweep at all?

        Reported at `/healthz` so *"no audit trail on this deployment"* does not
        have to be inferred from `files_deleted: 0`, which is also what a
        perfectly healthy sweep of a directory with nothing expired looks like.
        `CHAT_GATEWAY_INBOX_DIR=""` is the natural way an operator says it, and
        `Inbox` reads an empty value the same way (`Inbox(audit_dir="")` writes
        no audit records either), so the two agree.
        """
        return self._dir is not None

    @property
    def started(self) -> bool:
        """Was `start()` ever called? NOT cleared by `stop()`.

        Same contract, and the same reasoning, as `SubscriberLoop.started`:
        `is_alive()` alone cannot tell a loop that was never started from one
        that started and died, and only the second is a fault.
        """
        return self._started

    def is_alive(self) -> bool:
        """Is the sweep thread actually running right now?

        The DIRECT liveness signal (hard rule #5), and it is not redundant with
        the counters. `_run`'s `except Exception` covers the sweep; it does NOT
        cover an exception raised inside its own handler — a `print()` to a
        closed or blocked stdout is the realistic one — which escapes the
        `while` and kills the thread. Every retention field then freezes at a
        plausible value: `last_sweep_at` holds a real timestamp, `sweep_failures`
        holds a real number, and nothing ever moves again. That is the
        11-day-silent-failure shape rule #5 was written after, which is why the
        subscriber grew this pair first and why the review that found it here
        called it the same finding through a different door.
        """
        return self._thread is not None and self._thread.is_alive()

    def sweep(self) -> int:
        """Unlink day-files past their bucket's window. Returns how many."""
        if self._days <= 0:
            return 0
        # NEITHER of the two no-op cases is folded into the guard above, and
        # both were found the same way (audit F3, then pre-merge review
        # 2026-08-02). A pass that had nothing to do is still a pass that RAN,
        # and it must stamp `last_sweep_at` — otherwise "the sweeper is working
        # and idle" is byte-identical to "the sweeper thread is dead" on the one
        # endpoint whose job is telling those two apart.
        #   - the directory does not exist yet: normal on a deployment with no
        #     inbound traffic.
        #   - no directory is CONFIGURED at all: `CHAT_GATEWAY_INBOX_DIR=""`
        #     reaches `build_runtime` as `None`, which is how an operator turns
        #     the audit trail off. That branch reported `last_sweep_at: null`
        #     FOREVER, which is exactly the reportable dead-sweeper signature
        #     this finding says must not exist. `audit_dir_configured` is what
        #     keeps the two legible apart, not the stamp.
        # `days <= 0` is deliberately NOT in that list: pruning is off by
        # operator decision, `enabled` says so unambiguously at /healthz, and
        # stamping a sweep that is switched off would be its own small lie.
        removed = (self._sweep_dir()
                   if self._dir is not None and self._dir.exists() else 0)
        self.last_sweep_at = self._now()
        return removed

    def _sweep_dir(self) -> int:
        today = self._today()
        removed = 0
        for path in sorted(self._dir.glob("*.jsonl")):
            # `glob` matches DIRECTORIES too, and `unlink()` raises
            # `IsADirectoryError` on one — which counted an error on every pass,
            # forever, with no recovery path, because `delete_errors` is
            # cumulative and degrading (pre-merge review, 2026-08-02). Skipping
            # is the same posture as the unparseable-name branch below: a thing
            # this module did not write is a thing it leaves alone.
            if not path.is_file():
                continue
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
                # RECOVERY CLEARS BOTH, and the second one is what stops
                # `/healthz` degrading for the life of the process after a
                # transient failure (pre-merge review, 2026-08-02). Clearing
                # `last_sweep_error` while leaving a degrading counter set is
                # worse than not clearing it: the reason line then rendered the
                # cleared value as the literal "(None)".
                self.last_sweep_error = None
                self.consecutive_sweep_failures = 0
            except Exception as exc:  # noqa: BLE001 — the loop must survive
                # COUNTED, not just printed (audit F3). The first draft printed
                # and moved on, so a sweeper throwing every six hours reported
                # `errors: 0` and a frozen `last_sweep_at`, and /healthz never
                # degraded. That is the founding rule-#5 failure with a
                # different noun.
                self.sweep_failures += 1
                self.consecutive_sweep_failures += 1
                self.last_sweep_error = describe_exception(exc)
                print(f"retention: sweep FAILED (will retry): "
                      f"{self.last_sweep_error}", flush=True)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="retention-sweeper",
                                        daemon=True)
        self._started = True
        self._thread.start()

    def stop(self) -> None:
        # `_started` is deliberately NOT cleared, exactly as `SubscriberLoop`
        # does not clear its own: a sweeper still configured and no longer
        # sweeping is a fact /healthz must report, and whether it stopped on
        # purpose does not change that the window is no longer being enforced.
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
