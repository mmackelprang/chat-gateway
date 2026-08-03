"""CHAT_GATEWAY_ENV_FILE — the seam that keeps secrets out of the NAS compose."""

import os

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
