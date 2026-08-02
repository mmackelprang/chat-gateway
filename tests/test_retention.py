"""CG-68: the inbound audit trail's retention window, and the two guards that
keep the sweeper away from the one directory with no second copy."""

import datetime as dt
import pathlib
import time

import pytest

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
    s = RetentionSweeper(tmp_path / "inbox-data", days=30, quarantine_dir=q)
    assert s.days == 30


# -- audit F3: a stopped sweeper must not read as a working one ---------------

def test_a_pass_over_a_missing_directory_still_stamps_last_sweep_at(tmp_path):
    """`enabled: true, last_sweep_at: null` used to mean BOTH 'idle' and 'dead'."""
    s = RetentionSweeper(tmp_path / "does-not-exist", days=30)
    assert s.sweep() == 0
    assert s.last_sweep_at is not None


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
