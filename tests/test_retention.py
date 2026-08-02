"""CG-68: the inbound audit trail's retention window, and the two guards that
keep the sweeper away from the one directory with no second copy."""

import datetime as dt
import os
import pathlib
import sys
import time

import pytest

from chat_gateway.envelope import InboundReply
from chat_gateway.inbox import Inbox
from chat_gateway.journal import Journal
from chat_gateway.retention import (QUARANTINE_STEM, RetentionConfigError,
                                    RetentionSweeper, retention_days_from_env,
                                    window_for)


def _on(iso_date: str):
    """A fixed retention-key calendar. These tests are about date arithmetic.

    `today_fn`, NOT `now_fn` (audit F1): the window is measured against the same
    calendar `Inbox._audit` names the file in.
    """
    return lambda: dt.date.fromisoformat(iso_date)


def _touch(d, name, text="{}\n"):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)


def test_prunes_past_the_window_and_keeps_inside_it(tmp_path):
    d = tmp_path / "inbox-data"
    _touch(d, "job-hunter-2026-06-01.jsonl")   # 60 days old
    _touch(d, "job-hunter-2026-07-20.jsonl")   # 11 days old
    s = RetentionSweeper(d, days=30, today_fn=_on("2026-07-31"))
    assert s.sweep() == 1
    assert [p.name for p in d.glob("*.jsonl")] == ["job-hunter-2026-07-20.jsonl"]


def test_unrouted_gets_the_shorter_window(tmp_path):
    d = tmp_path / "inbox-data"
    _touch(d, "_unrouted-2026-07-20.jsonl")    # 11 days — inside 30, outside 7
    _touch(d, "job-hunter-2026-07-20.jsonl")
    s = RetentionSweeper(d, days=30, today_fn=_on("2026-07-31"))
    assert s.sweep() == 1
    assert [p.name for p in d.glob("*.jsonl")] == ["job-hunter-2026-07-20.jsonl"]


def test_zero_days_disables_pruning_entirely(tmp_path):
    d = tmp_path / "inbox-data"
    _touch(d, "job-hunter-2020-01-01.jsonl")
    assert RetentionSweeper(d, days=0, today_fn=_on("2026-07-31")).sweep() == 0
    assert list(d.glob("*.jsonl"))


def test_an_unparseable_filename_is_left_alone_never_guessed_at(tmp_path):
    d = tmp_path / "inbox-data"
    _touch(d, "notes.jsonl")
    _touch(d, "job-hunter-not-a-date.jsonl")
    s = RetentionSweeper(d, days=1, today_fn=_on("2026-07-31"))
    assert s.sweep() == 0
    assert len(list(d.glob("*.jsonl"))) == 2


def test_the_retention_key_matches_the_filename_inbox_actually_mints(tmp_path):
    """The loop the whole design rests on, and the one nothing closed.

    Every other test here hand-writes filenames with `_touch`, so all of them
    would stay green if `Inbox._audit` changed its filename shape — and the
    sweeper would then prune NOTHING while `/healthz` published `enabled: true,
    delete_errors: 0, files_deleted: 0` and tenant bodies accumulated forever.
    Every published signal green is exactly the failure hard rule #5 exists for.
    `test_the_quarantine_stem_matches_what_inbox_actually_writes` above closes
    this loop for the quarantine; this closes it for the retention key itself.

    A REAL `put()`, so `_audit` mints the name, and a real `unlink` deletes it.
    """
    from chat_gateway.retention import _NAME

    d = tmp_path / "inbox-data"
    Inbox(audit_dir=d).put(
        InboundReply(app="job-hunter", space="spaces/X", text="APPROVE 42",
                     received_at=dt.datetime(2026, 6, 1, 12, tzinfo=dt.timezone.utc)))
    minted = next(d.glob("*.jsonl"))
    match = _NAME.match(minted.name)
    assert match is not None and match.group("app") == "job-hunter"

    # `_audit` names the file with the LOCAL date the write happened, NOT the
    # reply's `received_at` — so the window is measured from the name, and the
    # sweep clock is derived from that same name rather than hardcoded. That is
    # what keeps this test off the calendar it happens to run on (audit F1).
    stamp = dt.date.fromisoformat(match.group("date"))
    s = RetentionSweeper(d, days=30, today_fn=lambda: stamp + dt.timedelta(days=31))
    assert s.sweep() == 1
    assert not minted.exists()


@pytest.mark.parametrize("age_days,survives", [(29, True), (30, True), (31, False)])
def test_the_window_boundary_is_inclusive_of_the_nth_day(tmp_path, age_days, survives):
    """`(today - stamp).days <= window` keeps day N and deletes day N+1.

    Pinned at the boundary because the tests above use 60 and 11 days against a
    30-day window — nowhere near it — and because `docs/consumers/jobhunt.md`
    stated the off-by-one wrong until this row's review.
    """
    d = tmp_path / "inbox-data"
    today = dt.date(2026, 7, 31)
    name = f"job-hunter-{(today - dt.timedelta(days=age_days)).isoformat()}.jsonl"
    _touch(d, name)
    RetentionSweeper(d, days=30, today_fn=_on(today.isoformat())).sweep()
    assert (d / name).exists() is survives


def test_todays_file_survives_even_at_a_one_day_window(tmp_path):
    """The audit's headline safety argument, pinned: `_audit` and `sweep()` share
    a directory with NO shared lock, and that is safe only because `_audit`
    writes TODAY's file and `sweep()` never targets a file inside its window.
    Arithmetic, not synchronization — so the arithmetic gets a test at its
    tightest legal setting."""
    d = tmp_path / "inbox-data"
    _touch(d, "job-hunter-2026-07-31.jsonl")
    assert RetentionSweeper(d, days=1, today_fn=_on("2026-07-31")).sweep() == 0
    assert (d / "job-hunter-2026-07-31.jsonl").exists()


def test_a_directory_named_like_a_day_file_is_skipped_not_counted_as_an_error(tmp_path):
    """`glob("*.jsonl")` matches DIRECTORIES, and `unlink()` raises
    `IsADirectoryError` on one. `delete_errors` is cumulative AND degrading with
    no recovery path, so one such directory pinned /healthz at `degraded`
    forever, incrementing on every pass."""
    d = tmp_path / "inbox-data"
    (d / "job-hunter-2020-01-01.jsonl").mkdir(parents=True)
    s = RetentionSweeper(d, days=1, today_fn=_on("2026-07-31"))
    assert s.sweep() == 0 and s.errors == 0
    assert s.sweep() == 0 and s.errors == 0      # and it does not accumulate
    assert (d / "job-hunter-2020-01-01.jsonl").is_dir()


def test_the_quarantine_dir_is_never_swept(tmp_path):
    """The CG-65 gate, pinned: retention points at inbox-data, never at state/."""
    q = tmp_path / "state" / "quarantine"
    _touch(q, "unrevivable-2020-01-01.jsonl")
    RetentionSweeper(tmp_path / "inbox-data", days=1,
                     today_fn=_on("2026-07-31"), quarantine_dir=q).sweep()
    assert (q / "unrevivable-2020-01-01.jsonl").exists()


# -- audit F2: the guarantee above is now a CODE property, not a path accident --

def test_a_quarantine_filename_would_otherwise_parse_as_a_tenant_bucket():
    """Why the two new guards exist, stated as a measurement.

    `unrevivable-<date>.jsonl` is a legal `<app>-<date>.jsonl`, and 'unrevivable'
    does not start with '_', so it would draw the FULL tenant window — not the
    7-day floor. Nothing about the name marks it as untouchable.
    """
    from chat_gateway.retention import _NAME
    m = _NAME.match("unrevivable-2026-07-31.jsonl")
    assert m is not None and m.group("app") == "unrevivable"
    assert window_for("unrevivable", 30) == 30      # NOT the _unrouted floor


def test_the_quarantine_stem_matches_what_inbox_actually_writes(tmp_path):
    """One home for the literal: if `_quarantine` renames its files, this fails."""
    jpath = tmp_path / "inbox.jsonl"
    Journal(jpath).open(1, "inbound", {"NOT": "an InboundReply"})
    q = tmp_path / "quarantine"
    ibx = Inbox(journal=Journal(jpath), quarantine_dir=q)
    ibx.restore()
    written = next(q.glob("*.jsonl"))
    assert written.name.startswith(QUARANTINE_STEM)


def test_a_quarantine_file_inside_the_sweep_dir_is_skipped_by_name(tmp_path):
    """Belt to `_check_disjoint`'s braces: the layout nobody predicted."""
    d = tmp_path / "inbox-data"
    _touch(d, "unrevivable-2020-01-01.jsonl")      # ancient, and must survive
    _touch(d, "job-hunter-2020-01-01.jsonl")
    s = RetentionSweeper(d, days=30, today_fn=_on("2026-07-31"))
    assert s.sweep() == 1
    assert (d / "unrevivable-2020-01-01.jsonl").exists()


@pytest.mark.parametrize("layout", ["same", "quarantine_under_sweep",
                                    "sweep_under_quarantine"])
def test_construction_refuses_a_sweep_dir_overlapping_the_quarantine(tmp_path, layout):
    """Fails at BOOT, loudly — the opposite posture from a malformed window,
    because a bad window over-retains and a bad directory deletes the only copy."""
    q = tmp_path / "state" / "quarantine"
    sweep = {"same": q,
             "quarantine_under_sweep": tmp_path / "state",
             "sweep_under_quarantine": q / "nested"}[layout]
    q.mkdir(parents=True, exist_ok=True)
    sweep.mkdir(parents=True, exist_ok=True)
    with pytest.raises(RetentionConfigError) as exc:
        RetentionSweeper(sweep, days=30, quarantine_dir=q)
    assert "quarantine" in str(exc.value)


def test_a_safe_but_all_in_one_layout_is_refused_on_purpose(tmp_path):
    """The strictness is a signed-off decision (2026-08-02), so it is pinned.

    `glob("*.jsonl")` is non-recursive, so sweeping `state/` while the
    quarantine sits at `state/quarantine/` would not delete anything today. It
    is refused anyway: "currently harmless" is a property of one line of code
    staying non-recursive, and the thing it protects has no second copy. The
    message names both env vars, because an operator who is refused at boot has
    to know which of the two to move.
    """
    q = tmp_path / "state" / "quarantine"
    q.mkdir(parents=True)
    with pytest.raises(RetentionConfigError) as exc:
        RetentionSweeper(tmp_path / "state", days=30, quarantine_dir=q)
    assert "CHAT_GATEWAY_INBOX_DIR" in str(exc.value)
    assert "CHAT_GATEWAY_STATE_DIR" in str(exc.value)


def test_the_default_sibling_layout_is_NOT_refused(tmp_path):
    """The counterweight to the test above: the shipped default must still boot."""
    q = tmp_path / "state" / "quarantine"
    q.mkdir(parents=True)
    s = RetentionSweeper(tmp_path / "inbox-data", days=30, quarantine_dir=q,
                         state_dir=tmp_path / "state")
    assert s.days == 30


@pytest.mark.parametrize("sub", ["deliveries", "queue", "somewhere-else"])
def test_a_sweep_dir_anywhere_under_the_state_dir_is_refused(tmp_path, sub):
    """The quarantine check missed every SIBLING of the quarantine.

    `CHAT_GATEWAY_INBOX_DIR=state/deliveries` passed both quarantine guards —
    it is neither inside the quarantine nor a parent of it — and the sweeper
    unlinked the delivery log's day-files, which `deliveries-<source>-<date>`
    matches exactly. `files_deleted` deliberately does not degrade, so /healthz
    published the loss as the feature working. ADR D7 calls that log permanent.
    """
    state = tmp_path / "state"
    q = state / "quarantine"
    q.mkdir(parents=True)
    with pytest.raises(RetentionConfigError) as exc:
        RetentionSweeper(state / sub, days=30, quarantine_dir=q, state_dir=state)
    assert "state dir" in str(exc.value)
    assert "CHAT_GATEWAY_INBOX_DIR" in str(exc.value)
    assert "CHAT_GATEWAY_STATE_DIR" in str(exc.value)


def test_the_quarantine_message_wins_when_both_guards_apply(tmp_path):
    """Order is load-bearing: the strongest message is the one an operator gets.

    `CHAT_GATEWAY_INBOX_DIR=state` trips BOTH checks. The quarantine's wording
    names the one artifact with no second copy anywhere, so it is checked first.
    """
    state = tmp_path / "state"
    q = state / "quarantine"
    q.mkdir(parents=True)
    with pytest.raises(RetentionConfigError) as exc:
        RetentionSweeper(state, days=30, quarantine_dir=q, state_dir=state)
    assert "quarantine" in str(exc.value)
    assert "state dir" not in str(exc.value)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="symlink creation needs privilege on Windows")
def test_a_symlink_cannot_walk_around_the_guard(tmp_path):
    """`_check_disjoint`'s docstring claims `resolve()` defeats this. Measured,
    because an untested comment rots — and `.parents` is a pure string walk that
    would be fooled without the resolve."""
    q = tmp_path / "state" / "quarantine"
    q.mkdir(parents=True)
    link = tmp_path / "looks-innocent"
    os.symlink(q, link, target_is_directory=True)
    with pytest.raises(RetentionConfigError):
        RetentionSweeper(link, days=30, quarantine_dir=q)


def test_a_dotdot_traversal_cannot_walk_around_the_guard(tmp_path):
    """The other half of the same claim: a path that only LOOKS disjoint."""
    q = tmp_path / "state" / "quarantine"
    q.mkdir(parents=True)
    sneaky = tmp_path / "inbox-data" / ".." / "state" / "quarantine"
    with pytest.raises(RetentionConfigError):
        RetentionSweeper(sneaky, days=30, quarantine_dir=q)


# -- audit F3: a stopped sweeper must not read as a working one ---------------

def test_a_pass_over_a_missing_directory_still_stamps_last_sweep_at(tmp_path):
    """`enabled: true, last_sweep_at: null` used to mean BOTH 'idle' and 'dead'."""
    s = RetentionSweeper(tmp_path / "does-not-exist", days=30)
    assert s.sweep() == 0
    assert s.last_sweep_at is not None


def test_a_pass_with_NO_directory_configured_still_stamps_last_sweep_at(tmp_path):
    """The same finding through the door the first fix missed.

    `CHAT_GATEWAY_INBOX_DIR=""` reaches `build_runtime` as `None` — the natural
    way to say "no audit trail on this deployment", and how `Inbox` reads it too.
    That branch returned BEFORE the stamp, so it reported
    `enabled: true, last_sweep_at: null` forever: byte-identical to a dead
    thread, which is the precise condition audit F3 says must never be
    reportable. `audit_dir_configured` is what tells the two apart, not the
    absence of a stamp.
    """
    s = RetentionSweeper("", days=30)
    assert s.sweep() == 0
    assert s.last_sweep_at is not None
    assert s.audit_dir_configured is False
    # ...and the configured-but-empty case still reports True, so the field is
    # answering the question it claims to.
    assert RetentionSweeper(tmp_path / "inbox-data", days=30).audit_dir_configured


def test_a_disabled_window_does_NOT_stamp_a_sweep_it_did_not_run(tmp_path):
    """The counterweight: `days=0` is pruning switched off by operator decision,
    `enabled: false` says so unambiguously at /healthz, and stamping a pass that
    was never made would be its own small lie."""
    s = RetentionSweeper(tmp_path / "inbox-data", days=0)
    assert s.sweep() == 0
    assert s.last_sweep_at is None


def test_a_recovered_sweep_clears_the_degradation_but_not_the_history(tmp_path):
    """One transient failure used to degrade /healthz for the life of the
    process — and print the already-cleared `last_sweep_error` as the literal
    "(None)" while the sweeper was demonstrably still pruning. The lifetime
    count survives (it is real history); only the consecutive one resets."""
    s = RetentionSweeper(tmp_path / "inbox-data", days=30, interval_s=0.01)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk gone")
        return 0

    s.sweep = flaky
    s.start()
    try:
        deadline = time.monotonic() + 3
        while calls["n"] < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        s.stop()
    assert s.sweep_failures == 1                 # history is kept
    assert s.consecutive_sweep_failures == 0     # the degrading counter is not
    assert s.last_sweep_error is None


# The escaping `BaseException` below IS the scenario, so pytest's warning about
# it is the test working rather than something to fix.
@pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_started_thread_that_died_is_visible(tmp_path):
    """The gap audit F3 left open: counters see nothing when a loop stops
    raising as well as stops working. `_run`'s `except` covers `sweep()`, not
    its own handler — a `print()` to a blocked stdout escapes the `while`."""
    s = RetentionSweeper(tmp_path / "inbox-data", days=30, interval_s=0.01)
    assert (s.started, s.is_alive()) == (False, False)   # never started != died
    s.sweep = lambda: (_ for _ in ()).throw(BaseException("uncatchable"))
    s.start()
    deadline = time.monotonic() + 3
    while s.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert s.started is True
    assert s.is_alive() is False


def test_a_failing_sweep_is_counted_not_just_printed(tmp_path, capsys):
    s = RetentionSweeper(tmp_path / "inbox-data", days=30, interval_s=0.01)
    s.sweep = lambda: (_ for _ in ()).throw(RuntimeError("disk gone"))
    s.start()
    try:
        deadline = time.monotonic() + 3
        while s.sweep_failures == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        s.stop()
    assert s.sweep_failures >= 1
    assert s.last_sweep_error is not None
    assert "sweep FAILED" in capsys.readouterr().out


def test_an_unlink_failure_is_counted_and_named_through_the_allowlist(
        tmp_path, capsys, monkeypatch):
    """Audit F4: `str(OSError)` embeds the ABSOLUTE path; `describe_exception`
    is this repo's rule for a class `errors.py` does not mark."""
    d = tmp_path / "inbox-data"
    _touch(d, "job-hunter-2020-01-01.jsonl")
    s = RetentionSweeper(d, days=1, today_fn=_on("2026-07-31"))

    def boom(self, *a, **kw):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(pathlib.Path, "unlink", boom)
    assert s.sweep() == 0
    assert s.errors == 1
    out = capsys.readouterr().out
    assert "job-hunter-2020-01-01.jsonl" in out      # the name IS ours to print
    assert str(d) not in out                          # the absolute path is not


def test_malformed_env_falls_back_to_the_default(capsys):
    assert retention_days_from_env({"CHAT_GATEWAY_INBOX_RETENTION_DAYS": "soon"}) == 30
    assert "not an integer" in capsys.readouterr().out
    assert retention_days_from_env({"CHAT_GATEWAY_INBOX_RETENTION_DAYS": "0"}) == 0
    assert retention_days_from_env({}) == 30
