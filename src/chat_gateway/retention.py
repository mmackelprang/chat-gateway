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
