"""Queue durability: the journal, its replay rule, and its compaction.

Every value in here is synthetic. Nothing in this file names a real space, a
real identity or a real credential — the CG-26 guard scans `tests/**/*.py`.
"""

import json

from chat_gateway.journal import Journal


def test_open_then_close_leaves_nothing_to_replay(tmp_path):
    j = Journal(tmp_path / "q.jsonl")
    j.open(1, "notify", {"title": "t"})
    j.close(1, "delivered")
    assert j.replay() == []


def test_open_without_close_survives(tmp_path):
    j = Journal(tmp_path / "q.jsonl")
    j.open(7, "notify", {"title": "t"})
    survivors = j.replay()
    assert [s["id"] for s in survivors] == [7]
    assert survivors[0]["payload"] == {"title": "t"}


def test_attempts_survive_a_restart(tmp_path):
    # Without this a crash-loop resets the backoff ladder every boot and
    # hammers the far end forever — a durability feature turned into an
    # outage amplifier.
    path = tmp_path / "q.jsonl"
    j = Journal(path)
    j.open(1, "notify", {"title": "t"})
    j.update(1, 3, "2026-07-31T13:00:00+00:00")
    reopened = Journal(path).replay()
    assert reopened[0]["attempts"] == 3
    assert reopened[0]["next_attempt_at"] == "2026-07-31T13:00:00+00:00"


def test_the_last_update_wins(tmp_path):
    j = Journal(tmp_path / "q.jsonl")
    j.open(1, "notify", {})
    j.update(1, 1, "2026-07-31T12:01:00+00:00")
    j.update(1, 2, "2026-07-31T12:05:00+00:00")
    assert j.replay()[0]["attempts"] == 2


def test_a_torn_trailing_line_is_skipped_and_counted_not_fatal(tmp_path):
    # The expected shape of a power loss. Refusing to boot over a half-written
    # byte is a crash loop on a host running `restart: unless-stopped`.
    path = tmp_path / "q.jsonl"
    j = Journal(path)
    j.open(1, "notify", {"title": "kept"})
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"v": 1, "op": "open", "id": 2, "payl')   # torn
    reopened = Journal(path)
    survivors = reopened.replay()
    assert [s["id"] for s in survivors] == [1]
    assert reopened.skipped_lines == 1


def test_an_unparseable_line_mid_file_is_also_skipped(tmp_path):
    path = tmp_path / "q.jsonl"
    path.write_text(
        json.dumps({"v": 1, "op": "open", "id": 1, "payload": {}}) + "\n"
        "}{ not json at all\n"
        + json.dumps({"v": 1, "op": "open", "id": 2, "payload": {}}) + "\n",
        encoding="utf-8")
    j = Journal(path)
    assert [s["id"] for s in j.replay()] == [1, 2]
    assert j.skipped_lines == 1


def test_a_record_that_is_json_but_not_a_record_is_skipped(tmp_path):
    path = tmp_path / "q.jsonl"
    path.write_text('[1, 2, 3]\n{"no": "op or id"}\n', encoding="utf-8")
    j = Journal(path)
    assert j.replay() == []
    assert j.skipped_lines == 2


def test_inline_compaction_does_not_reset_the_skipped_count(tmp_path):
    # Compaction re-reads the file. If that re-read counted skips, the /healthz
    # number would either double or — when compaction runs after the offending
    # line is gone — silently reset to 0, which is the one number rule #5 must
    # not be able to lose.
    path = tmp_path / "q.jsonl"
    path.write_text('{"broken\n', encoding="utf-8")
    j = Journal(path, compact_after=2)
    j.replay()
    assert j.skipped_lines == 1
    for i in range(4):
        j.open(i, "notify", {})
        j.close(i, "delivered")
    assert j.skipped_lines == 1


def test_compaction_preserves_exactly_the_survivors(tmp_path):
    path = tmp_path / "q.jsonl"
    j = Journal(path)
    for i in (1, 2, 3):
        j.open(i, "notify", {"n": i})
    j.update(2, 1, "2026-07-31T12:01:00+00:00")
    j.close(1, "delivered")
    j.close(3, "failed")
    before = j.replay()
    j.compact()
    after = Journal(path).replay()
    assert [s["id"] for s in before] == [2]
    assert [s["id"] for s in after] == [2]
    assert after[0]["attempts"] == 1
    assert after[0]["payload"] == {"n": 2}


def test_compaction_preserves_the_open_timestamp_so_age_survives_it(tmp_path):
    # The replay ceiling is measured from `opened_at`. If compaction stamped
    # "now" instead, a job could outlive the ceiling forever by being compacted
    # often enough — and the expiry rule would quietly never fire.
    path = tmp_path / "q.jsonl"
    j = Journal(path)
    j.open(1, "notify", {})
    opened_at = j.replay()[0]["opened_at"]
    j.compact()
    assert Journal(path).replay()[0]["opened_at"] == opened_at


def test_compaction_shrinks_the_file(tmp_path):
    path = tmp_path / "q.jsonl"
    j = Journal(path)
    for i in range(50):
        j.open(i, "notify", {"n": i})
        j.close(i, "delivered")
    fat = path.stat().st_size
    j.compact()
    assert path.stat().st_size < fat
    assert Journal(path).replay() == []


def test_compaction_is_atomic_leaving_no_tmp_behind(tmp_path):
    path = tmp_path / "q.jsonl"
    j = Journal(path)
    j.open(1, "notify", {})
    j.compact()
    assert list(tmp_path.glob("*.tmp")) == []


def test_inline_compaction_fires_at_the_threshold(tmp_path):
    path = tmp_path / "q.jsonl"
    j = Journal(path, compact_after=4)
    for i in range(10):
        j.open(i, "notify", {})
        j.close(i, "delivered")
    # A process that never reboots would otherwise never compact.
    assert path.stat().st_size < 400
    assert Journal(path).replay() == []


def test_opens_alone_never_trigger_compaction(tmp_path):
    # An `open` supersedes nothing, so a journal of pure opens is already
    # exactly its live set. Compacting it would rewrite the whole file to
    # reclaim zero bytes, on a queue whose only sin is being busy.
    path = tmp_path / "q.jsonl"
    j = Journal(path, compact_after=2)
    for i in range(10):
        j.open(i, "notify", {})
    assert [s["id"] for s in j.replay()] == list(range(10))


def test_close_many_is_one_batch_and_replays_nothing(tmp_path):
    path = tmp_path / "q.jsonl"
    j = Journal(path)
    for i in (1, 2, 3):
        j.open(i, "inbound", {"n": i})
    j.close_many([1, 2, 3], "polled")
    assert Journal(path).replay() == []


def test_a_torn_batch_close_replays_the_unclosed_rest_rather_than_losing_it(tmp_path):
    # Simulates a crash part-way through writing a poll's closes. The surviving
    # direction must be REDELIVER, never a silent partial drop.
    path = tmp_path / "q.jsonl"
    j = Journal(path)
    for i in (1, 2, 3):
        j.open(i, "inbound", {"n": i})
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"v": 1, "op": "close", "id": 1, "status": "polled"}) + "\n")
        fh.write('{"v": 1, "op": "close", "id": 2, "sta')   # torn mid-batch
    reopened = Journal(path)
    assert [s["id"] for s in reopened.replay()] == [2, 3]
    assert reopened.skipped_lines == 1


def test_close_many_with_no_ids_writes_nothing(tmp_path):
    path = tmp_path / "q.jsonl"
    Journal(path).close_many([], "polled")
    assert not path.exists()


def test_a_missing_journal_file_replays_empty(tmp_path):
    assert Journal(tmp_path / "never-written.jsonl").replay() == []


def test_the_journal_is_readable_by_eye_during_an_incident(tmp_path):
    # Half the reason for the format: an operator reads it with `tail`. One
    # self-describing JSON object per line, no framing, no length prefix.
    path = tmp_path / "q.jsonl"
    j = Journal(path)
    j.open(1, "notify", {"title": "disk almost full"})
    j.close(1, "delivered")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["op"] for line in lines] == ["open", "close"]
    assert json.loads(lines[0])["payload"]["title"] == "disk almost full"


def test_a_write_failure_raises_rather_than_pretending_to_have_persisted(tmp_path):
    # The journal never lies about having written. Callers decide what to do
    # with that — delivery.py refuses the enqueue, and swallows-and-counts on
    # the paths where raising would be worse.
    from chat_gateway.journal import JournalWriteError

    blocker = tmp_path / "blocked"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    j = Journal(blocker / "q.jsonl")
    try:
        j.open(1, "notify", {})
    except JournalWriteError:
        pass
    else:  # pragma: no cover - only reached if the guard regresses
        raise AssertionError("a journal that cannot write must say so")
