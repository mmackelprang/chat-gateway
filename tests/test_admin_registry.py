"""CG-90 Task 1: `inbound_locked` and the reserved admin key name."""
import pytest

from chat_gateway.registry import ADMIN_KEY_ENV, RegistryError, load_registry

HEAD = """identities:
  i1:
    display: d
    webhook_url_env: W1
apps:
  a1:
    key_env: K1
    identities: [i1]
"""


def _load(tmp_path, extra=""):
    p = tmp_path / "r.yaml"
    p.write_text(HEAD + extra, encoding="utf-8")
    return load_registry(p)


def test_inbound_locked_defaults_to_false(tmp_path):
    assert _load(tmp_path).apps["a1"].inbound_locked is False


def test_inbound_locked_true_loads(tmp_path):
    assert _load(tmp_path, "    inbound_locked: true\n").apps["a1"].inbound_locked is True


def test_a_quoted_inbound_locked_is_refused_not_coerced(tmp_path):
    with pytest.raises(RegistryError, match="inbound_locked must be a YAML boolean"):
        _load(tmp_path, '    inbound_locked: "true"\n')


def test_no_app_may_use_the_admin_key_env(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(HEAD.replace("key_env: K1", f"key_env: {ADMIN_KEY_ENV}"), encoding="utf-8")
    with pytest.raises(RegistryError, match="reserved for the admin console"):
        load_registry(p)


# CG-92 Task 3: identities may record an avatar.
def _avatar_load(tmp_path, line):
    p = tmp_path / "r.yaml"
    p.write_text(HEAD.replace("    webhook_url_env: W1\n", f"    webhook_url_env: W1\n{line}"),
                 encoding="utf-8")
    return load_registry(p)


def test_avatar_loads_a_bundled_name(tmp_path):
    assert _avatar_load(tmp_path, "    avatar: phone\n").identities["i1"].avatar == "phone"


def test_avatar_absent_is_none(tmp_path):
    assert _load(tmp_path).identities["i1"].avatar is None


def test_a_wrong_case_avatar_is_refused_naming_the_identity(tmp_path):
    with pytest.raises(RegistryError, match="identity 'i1': avatar must be a bundled icon name"):
        _avatar_load(tmp_path, "    avatar: Phone\n")


def test_avatar_is_accepted_on_an_app_mode_identity(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n  i1:\n    display: d\n    mode: app\n    space: spaces/X\n"
        "    avatar: home\napps:\n  a1:\n    key_env: K1\n    identities: [i1]\n",
        encoding="utf-8",
    )
    assert load_registry(p).identities["i1"].avatar == "home"
