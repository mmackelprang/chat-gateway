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
