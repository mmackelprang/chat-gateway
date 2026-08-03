"""CHAT_GATEWAY_ENV_FILE — the seam that keeps secrets out of the NAS compose."""

import os
from pathlib import Path

import pytest

from chat_gateway.env_file import EnvFileError, load_env_file, parse_env_file

REGISTRY_YAML = """
identities:
  pm-familyworkspace:
    display: "PM · familyworkspace"
    mode: webhook
    webhook_url_env: TEST_HOOK_FW
apps:
  aiteam-harness:
    key_env: TEST_KEY_AITEAM
    identities: [pm-familyworkspace]
"""


def test_parses_comments_blanks_export_and_quotes():
    parsed = parse_env_file(
        "# a comment\n"
        "\n"
        "PLAIN=value\n"
        "export EXPORTED=exported-value\n"
        'DOUBLE="quoted value"\n'
        "SINGLE='quoted value'\n"
        "EMPTY=\n"
        "SPACED = padded \n"
    )
    assert parsed == {
        "PLAIN": "value",
        "EXPORTED": "exported-value",
        "DOUBLE": "quoted value",
        "SINGLE": "quoted value",
        "EMPTY": "",
        "SPACED": "padded",
    }


def test_a_line_without_an_equals_is_ignored_not_guessed_at():
    assert parse_env_file("JUST_A_WORD\nGOOD=1\n") == {"GOOD": "1"}


def test_an_equals_inside_the_value_survives():
    # A base64 key or a URL query is full of '='. Only the FIRST splits.
    assert parse_env_file("K=a=b=c\n") == {"K": "a=b=c"}


# ---------------------------------------------------------------------------
# Inline comments — the rule this parser shares with docker-compose because the
# SAME FILE is read by both (compose's `env_file: .env` on the dev box, this
# loader on the NAS). See `parse_env_file`'s docstring for why divergence would
# make a working file change meaning at the destination.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("line,expected", [
    ("K=value   # note", "value"),        # whitespace-preceded # ends the value
    ("K=   # note", ""),                  # ...leaving nothing behind
    ("K=#note", ""),                      # first non-whitespace char
    ("K=abc#def", "abc#def"),             # NOT preceded by whitespace: a value
    ('K="a # b"  # note', "a # b"),       # quoting is the escape hatch
    ("K='a # b'", "a # b"),               # either quote character
    ("K=a=b=c", "a=b=c"),                 # only the first `=` splits
    ("K=value", "value"),                 # no comment, nothing to do
    ("export K=value # note", "value"),   # after `export ` is stripped
])
def test_an_inline_comment_ends_the_value_on_composes_rule(line, expected):
    assert parse_env_file(line + "\n") == {"K": expected}


def test_an_unterminated_quote_is_not_guessed_at():
    """Same posture as a line with no `=`: leave it alone rather than invent a
    closing quote and hand back half a credential."""
    assert parse_env_file('K="unclosed\n') == {"K": '"unclosed'}


def test_quoting_still_preserves_deliberate_surrounding_whitespace():
    """The escape hatch has to be worth using. A quoted value keeps its edges —
    unchanged from before inline comments existed."""
    assert parse_env_file('K=" padded "\n') == {"K": " padded "}


def test_the_repos_own_env_example_parses_with_no_comment_inside_a_value():
    """THE REGRESSION TEST, and the one that would have caught this.

    Measured before the fix: 11 of `.env.example`'s 18 keys came back with the
    trailing comment inside the value. The two asserted individually are the
    ones with teeth — `docs/deploy/nas.md` §6 tells the operator to copy this
    file's descendant to the box, where a commented-but-unfilled line yields a
    NON-EMPTY string, `__main__`'s `if not sub or not creds` guard does not
    fire, and the gateway boots looking alive on an unauthenticated `/healthz`
    with no way to reach Google.

    The path is derived from `__file__` so this test travels with the repo
    rather than with one checkout.
    """
    example = Path(__file__).resolve().parent.parent / ".env.example"
    parsed = parse_env_file(example.read_text(encoding="utf-8"))
    assert parsed, "the example file should parse to something"
    leaked = {k: v for k, v in parsed.items() if "#" in v}
    assert leaked == {}, f"comment text leaked into {len(leaked)} value(s)"
    # ...and specifically: the fail-closed guard in `__main__` sees empty.
    assert parsed["GOOGLE_APPLICATION_CREDENTIALS"] == ""
    assert parsed["CHAT_GATEWAY_PUBSUB_SUBSCRIPTION"] == ""


def test_a_utf8_bom_does_not_rename_the_first_key(tmp_path):
    """A BOM is not whitespace to Python, so `.strip()` leaves it attached and
    the first key becomes `﻿KEY` — a credential dropped in silence, on a
    Windows dev box whose editors write one by default."""
    f = tmp_path / "env"
    f.write_bytes(b"\xef\xbb\xbfFIRST_KEY=first\nSECOND_KEY=second\n")
    environ = {}
    assert load_env_file(f, environ) == 2
    assert environ["FIRST_KEY"] == "first"
    assert not any(k.startswith("﻿") for k in environ)


def test_the_environment_wins_over_the_file(tmp_path):
    f = tmp_path / "env"
    f.write_text("KEEP=from-file\nADD=from-file\n", encoding="utf-8")
    environ = {"KEEP": "from-environment"}
    applied = load_env_file(f, environ)
    assert environ["KEEP"] == "from-environment"   # never silently replaced
    assert environ["ADD"] == "from-file"
    assert applied == 1                            # only the one it actually set


def test_a_missing_file_raises_rather_than_booting_without_credentials(tmp_path):
    with pytest.raises(EnvFileError) as excinfo:
        load_env_file(tmp_path / "nope", {})
    assert "CHAT_GATEWAY_ENV_FILE" in str(excinfo.value)


def test_the_error_names_the_path_and_carries_no_value(tmp_path):
    d = tmp_path / "is-a-directory"
    d.mkdir()
    with pytest.raises(EnvFileError) as excinfo:
        load_env_file(d, {})
    assert str(d) in str(excinfo.value)


def test_load_returns_a_count_and_never_the_values(tmp_path, capsys):
    f = tmp_path / "env"
    f.write_text("SECRETISH=SYNTHETIC-NOT-A-REAL-VALUE\n", encoding="utf-8")
    environ = {}
    assert load_env_file(f, environ) == 1
    # nothing printed by the loader itself; the caller prints only the count
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# The wiring, through the REAL `build_runtime()` / `main()`.
#
# The three tests above prove the loader; these prove the seam. The properties
# this row is judged on live in `__main__`, not in `env_file` — "unset is a
# no-op" and "a missing file is FATAL" are both statements about what the
# entrypoint does with the loader, and neither is observable from the module in
# isolation.
#
# The registry fixture is the minimal one `tests/test_core.py` uses, written to
# `tmp_path` — `build_runtime()` resolves `CHAT_GATEWAY_REGISTRY` relative to the
# process's cwd otherwise, which is whatever directory pytest was started in.
# ---------------------------------------------------------------------------


@pytest.fixture()
def boxed_env(tmp_path, monkeypatch):
    """A `build_runtime()`-shaped environment pointed entirely at `tmp_path`.

    `CHAT_GATEWAY_ENV_FILE` is deliberately left UNSET here — the tests that want
    it set it themselves, so "unset" is this fixture's baseline rather than a
    thing each test has to remember to undo.
    """
    reg = tmp_path / "registry.yaml"
    reg.write_text(REGISTRY_YAML, encoding="utf-8")
    monkeypatch.setenv("CHAT_GATEWAY_REGISTRY", str(reg))
    monkeypatch.setenv("CHAT_GATEWAY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHAT_GATEWAY_INBOX_DIR", str(tmp_path / "inbox-data"))
    monkeypatch.delenv("CHAT_GATEWAY_ENV_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("GATEWAY_ENABLE_PUBSUB", raising=False)
    return tmp_path


def test_unset_is_a_no_op_through_the_real_build_runtime(boxed_env, capsys):
    """The claim the whole rest of the suite is the evidence for, asserted once
    directly: with `CHAT_GATEWAY_ENV_FILE` absent, `build_runtime()` loads
    nothing and prints nothing about an env file.

    Every other test in this repo runs with the variable unset, so 359 unchanged
    passes are the broad evidence; this is the narrow one, and it is the only
    place that says *why* they are unchanged.
    """
    from chat_gateway.__main__ import build_runtime

    assert "CHAT_GATEWAY_ENV_FILE" not in os.environ
    build_runtime()
    assert "env:" not in capsys.readouterr().out


def test_a_missing_env_file_is_a_config_error_not_a_traceback(boxed_env, capsys):
    """Loader property #3, end to end through `main()` — the single most
    important behavioural claim in this row.

    A gateway that boots with no credentials answers `degraded` on an
    UNAUTHENTICATED endpoint and otherwise looks alive. Exit 2 with the fault
    named on stderr is the alternative, and it is the same shape a bad registry
    path already gets. Asserted through `main()` rather than `load_env_file`
    because the widened `except` clause is the thing that can regress: the
    loader raising is necessary, and on its own it is a traceback.
    """
    from chat_gateway.__main__ import main

    os.environ["CHAT_GATEWAY_ENV_FILE"] = str(boxed_env / "not-here.env")
    try:
        assert main(["check"]) == 2
    finally:
        os.environ.pop("CHAT_GATEWAY_ENV_FILE", None)
    err = capsys.readouterr().err
    assert err.startswith("config error:")
    assert "Traceback" not in err


def test_the_boot_line_carries_a_COUNT_and_never_a_VALUE(boxed_env, capsys):
    """Hard rule #2 at the one place this row prints anything.

    The value below is synthetic and marked as such; the assertion is that it
    does not reach stdout. The path does — a path is not a credential, and an
    operator debugging a wrong mount needs to see which file was read.
    """
    from chat_gateway.__main__ import build_runtime

    f = boxed_env / "gateway.env"
    f.write_text("CG53_SYNTHETIC_KEY=SYNTHETIC-NOT-A-REAL-VALUE\n", encoding="utf-8")
    os.environ["CHAT_GATEWAY_ENV_FILE"] = str(f)
    try:
        build_runtime()
    finally:
        # The loader writes into the REAL `os.environ` by design, and monkeypatch
        # cannot undo a key it did not set. Popped here so the next test in the
        # session does not inherit it.
        os.environ.pop("CHAT_GATEWAY_ENV_FILE", None)
        os.environ.pop("CG53_SYNTHETIC_KEY", None)
    out = capsys.readouterr().out
    assert f"env: loaded 1 key(s) from {f}" in out
    assert "SYNTHETIC-NOT-A-REAL-VALUE" not in out
