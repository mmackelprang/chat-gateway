"""CG-90 Task 4 — `ManagedSecrets`, the gateway-owned 0600 secrets file."""
import os
import sys

import pytest

from chat_gateway.env_file import load_env_file, parse_env_file
from chat_gateway.managed_secrets import ManagedSecrets


def _ms(tmp_path, environ, process=frozenset(), hand=frozenset()):
    return ManagedSecrets(tmp_path / "state" / "managed.env", process_env_names=process,
                          hand_env_names=hand, environ=environ)


def test_apply_writes_file_and_environ(tmp_path):
    env = {}
    ms = _ms(tmp_path, env)
    ms.apply({"CHAT_GATEWAY_API_KEY__X": "cgk_abc"})
    assert env["CHAT_GATEWAY_API_KEY__X"] == "cgk_abc"
    text = (tmp_path / "state" / "managed.env").read_text(encoding="utf-8")
    assert 'CHAT_GATEWAY_API_KEY__X="cgk_abc"' in text


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_file_is_0600(tmp_path):
    ms = _ms(tmp_path, {})
    ms.apply({"A": "1"})
    assert oct(os.stat(tmp_path / "state" / "managed.env").st_mode & 0o777) == "0o600"


def test_none_removes(tmp_path):
    env = {}
    ms = _ms(tmp_path, env)
    ms.apply({"A": "1", "B": "2"})
    ms.apply({"A": None})
    assert "A" not in env and env["B"] == "2"
    assert "A=" not in (tmp_path / "state" / "managed.env").read_text(encoding="utf-8")


def test_snapshot_restore_rolls_back_file_and_environ(tmp_path):
    env = {"A": "old"}
    ms = _ms(tmp_path, env)
    ms.apply({"A": "v1"})
    snap = ms.snapshot(["A", "NEW"])
    ms.apply({"A": "v2", "NEW": "n"})
    ms.restore(snap)
    assert env["A"] == "v1" and "NEW" not in env
    assert '"v2"' not in (tmp_path / "state" / "managed.env").read_text(encoding="utf-8")


def test_restore_reproduces_the_file_byte_for_byte(tmp_path):
    # Rollback must restore the exact bytes, not a re-rendering — on Windows a
    # text-mode fd would turn every "\n" into "\r\n" on the way back out.
    ms = _ms(tmp_path, {})
    ms.apply({"A": "1", "B": "2"})
    path = tmp_path / "state" / "managed.env"
    before = path.read_bytes()
    snap = ms.snapshot(["A"])
    ms.apply({"A": "changed"})
    ms.restore(snap)
    assert path.read_bytes() == before
    assert b"\r" not in before


def test_restore_of_a_file_that_did_not_exist_deletes_it(tmp_path):
    env = {}
    ms = _ms(tmp_path, env)
    snap = ms.snapshot(["A"])
    ms.apply({"A": "1"})
    ms.restore(snap)
    assert not (tmp_path / "state" / "managed.env").exists() and "A" not in env


def test_a_value_with_a_quote_or_newline_is_refused(tmp_path):
    ms = _ms(tmp_path, {})
    for bad in ('a"b', "a\nb"):
        with pytest.raises(ValueError):
            ms.apply({"A": bad})


def test_a_refused_value_is_never_echoed_and_nothing_is_written(tmp_path):
    """The store's contract: validate ALL, then write — a ValueError on the
    second change must leave the file and the environ exactly as they were."""
    env = {}
    ms = _ms(tmp_path, env)
    ms.apply({"KEEP": "k"})
    path = tmp_path / "state" / "managed.env"
    before = path.read_bytes()
    secret = 'sekrit"tail'
    with pytest.raises(ValueError) as exc:
        ms.apply({"GOOD": "fine", "BAD": secret})
    assert secret not in str(exc.value) and "sekrit" not in str(exc.value)
    assert "BAD" in str(exc.value)
    assert path.read_bytes() == before
    assert env == {"KEEP": "k"}


@pytest.mark.parametrize("bad_name", ["", "A=B", "A B", "A\nB", "#A", "1A", "export A"])
def test_a_name_that_would_not_round_trip_is_refused(tmp_path, bad_name):
    env = {}
    ms = _ms(tmp_path, env)
    with pytest.raises(ValueError):
        ms.apply({bad_name: "v"})
    assert not (tmp_path / "state" / "managed.env").exists() and env == {}


def test_written_values_parse_back_exactly(tmp_path):
    """Every value this module accepts must come back byte-identical through the
    one parser the boot path uses — quoted content is the value."""
    values = {
        "PLAIN": "cgk_abc",
        "EMPTY": "",
        "SPACES": "  lead and trail  ",
        "HASH": "a # b#c",
        "SINGLE": "it's",
        "URL": "https://chat.googleapis.com/v1/spaces/X/messages?key=k&token=t=",
    }
    env = {}
    ms = _ms(tmp_path, env)
    ms.apply(values)
    text = (tmp_path / "state" / "managed.env").read_text(encoding="utf-8")
    assert parse_env_file(text) == values
    fresh = {}
    assert ManagedSecrets(tmp_path / "state" / "managed.env", process_env_names=frozenset(),
                          environ=fresh).load_at_boot() == len(values)
    assert fresh == values


def test_boot_managed_beats_hand_env_and_process_beats_both(tmp_path):
    """Spec §4: a page-rotated key survives a reboot with the OLD value still in
    the read-only hand-written .env; a real process env var is never overridden."""
    env = {"PROC": "from-process"}
    managed = tmp_path / "state" / "managed.env"
    managed.parent.mkdir(parents=True)
    managed.write_text('KEY="new"\nPROC="from-managed"\n', encoding="utf-8")
    hand = tmp_path / "gateway.env"
    hand.write_text("KEY=old\n", encoding="utf-8")
    ms = ManagedSecrets(managed, process_env_names=frozenset(env), environ=env)
    assert ms.load_at_boot() == 1
    load_env_file(hand, environ=env)
    assert env["KEY"] == "new"
    assert env["PROC"] == "from-process"
    assert ms.blocked("PROC") and not ms.blocked("KEY")


def test_source_and_shadowed(tmp_path):
    env = {"P": "x", "H": "y"}
    ms = _ms(tmp_path, env, process=frozenset({"P"}), hand=frozenset({"H", "S"}))
    ms.apply({"S": "z", "M": "m"})
    assert ms.source_of("P") == "process"
    assert ms.source_of("M") == "managed"
    assert ms.source_of("H") == ".env"
    assert ms.source_of("NOPE") == "unset"
    assert ms.shadowed() == ["S"]


def test_hand_env_names_is_assignable(tmp_path):
    ms = _ms(tmp_path, {})
    ms.apply({"S": "z"})
    assert ms.shadowed() == []
    ms.hand_env_names = frozenset({"S"})
    assert ms.shadowed() == ["S"]


def test_no_temp_file_is_left_behind(tmp_path):
    ms = _ms(tmp_path, {})
    ms.apply({"A": "1"})
    assert sorted(p.name for p in (tmp_path / "state").iterdir()) == ["managed.env"]


def test_missing_file_at_boot_is_zero(tmp_path):
    assert _ms(tmp_path, {}).load_at_boot() == 0
