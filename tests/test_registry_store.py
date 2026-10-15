"""CG-90 Task 5 — spec §5's write path, step by step."""
from pathlib import Path

import pytest

from chat_gateway.managed_secrets import ManagedSecrets
from chat_gateway.registry import RegistryError, load_registry
from chat_gateway.registry_holder import RegistryHolder
from chat_gateway.registry_store import RegistryStore, StoreError, flow_seq

TEXT = """# top comment survives
identities:
  i1:
    display: d1
    webhook_url_env: W1   # inline comment survives
apps:
  a1:
    key_env: K1
    identities: [i1]
    allow_inbound: false   # hard rule #6
"""


def _store(tmp_path, text=TEXT, newline="\n"):
    p = tmp_path / "registry.yaml"
    p.write_bytes(text.replace("\n", newline).encode("utf-8"))
    holder = RegistryHolder(load_registry(p))
    env = {}
    secrets = ManagedSecrets(tmp_path / "state" / "managed.env",
                             process_env_names=frozenset(), environ=env)
    return RegistryStore(p, holder, secrets), holder, env, p


def _add_a2(tree):
    from ruamel.yaml.comments import CommentedMap
    m = CommentedMap()
    m["key_env"] = "K2"
    m["identities"] = flow_seq(["i1"])
    m["allow_inbound"] = False
    tree["apps"]["a2"] = m


def test_noop_example_registry_round_trips_byte_identical(tmp_path):
    src = Path("config/registry.example.yaml").read_bytes()
    store, *_ , p = _store(tmp_path, src.decode("utf-8").replace("\r\n", "\n"))
    before = p.read_bytes()
    store.apply(lambda tree: None)
    assert p.read_bytes() == before


def test_add_preserves_comments_and_swaps(tmp_path):
    store, holder, _, p = _store(tmp_path)
    reg = store.apply(_add_a2)
    text = p.read_text(encoding="utf-8")
    assert "# top comment survives" in text and "# inline comment survives" in text
    assert "# hard rule #6" in text
    assert "identities: [i1]" in text.split("a2:")[1]
    assert holder.current is reg and "a2" in holder.apps


def test_crlf_file_stays_crlf(tmp_path):
    store, _, _, p = _store(tmp_path, newline="\r\n")
    store.apply(_add_a2)
    raw = p.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")


def test_invalid_edit_is_422_and_nothing_changes(tmp_path):
    store, holder, env, p = _store(tmp_path)
    before, live = p.read_bytes(), holder.current

    def bad(tree):
        tree["apps"]["a1"]["identities"] = flow_seq(["nope"])

    with pytest.raises(StoreError) as e:
        store.apply(bad, secrets={"K1": "cgk_x"})
    assert e.value.status == 422 and "unknown identity" in str(e.value)
    assert p.read_bytes() == before and holder.current is live and "K1" not in env
    assert store.refused == 1 and store.writes == 0


def test_write_after_out_of_band_edit_is_409(tmp_path):
    store, _, _, p = _store(tmp_path)
    p.write_text(TEXT + "# hand edit\n", encoding="utf-8")
    with pytest.raises(StoreError) as e:
        store.apply(_add_a2)
    assert e.value.status == 409


def test_stale_expected_sha_is_409(tmp_path):
    store, *_ = _store(tmp_path)
    with pytest.raises(StoreError) as e:
        store.apply(_add_a2, expect_sha256="0" * 64)
    assert e.value.status == 409


def test_backup_is_written_with_utc_stamp(tmp_path):
    store, _, _, p = _store(tmp_path)
    before = p.read_bytes()
    store.apply(_add_a2)
    baks = list(tmp_path.glob("registry.yaml.bak-*"))
    assert len(baks) == 1 and baks[0].read_bytes() == before


def test_noop_edit_skips_backup_and_same_second_backups_do_not_collide(tmp_path):
    fixed = lambda: __import__("datetime").datetime(2026, 10, 15, 12, 0, 0)  # noqa: E731
    store, *_ = _store(tmp_path)
    store._now = fixed
    store.apply(_add_a2)
    store.apply(lambda t: t["apps"]["a2"].__setitem__("allow_inbound", False))  # no change
    assert len(list(tmp_path.glob("registry.yaml.bak-*"))) == 1
    store.apply(lambda t: t["apps"].pop("a2"))
    names = sorted(p.name for p in tmp_path.glob("registry.yaml.bak-*"))
    assert names == ["registry.yaml.bak-20261015-120000", "registry.yaml.bak-20261015-120000-2"]


def test_a_secret_value_with_a_quote_is_422_and_nothing_written(tmp_path):
    store, holder, env, p = _store(tmp_path)
    before = p.read_bytes()
    with pytest.raises(StoreError) as e:
        store.apply(_add_a2, secrets={"K2": 'bad"value'})
    assert e.value.status == 422 and "bad" not in str(e.value).replace("K2", "")
    assert p.read_bytes() == before and "K2" not in env and "a2" not in holder.apps


def test_secrets_only_change_writes_no_registry_backup(tmp_path):
    store, _, env, p = _store(tmp_path)
    before = p.read_bytes()
    store.apply(None, secrets={"K1": "cgk_new"})
    assert env["K1"] == "cgk_new" and p.read_bytes() == before
    assert list(tmp_path.glob("registry.yaml.bak-*")) == []


def test_failure_at_registry_write_rolls_back_secrets(tmp_path, monkeypatch):
    store, holder, env, p = _store(tmp_path)
    before, live = p.read_bytes(), holder.current
    import chat_gateway.registry_store as rs

    def boom(*a, **kw):
        raise OSError("disk full")

    # `copymode`, not `os.replace`: `os` is one shared module object, so
    # patching `os.replace` would also break ManagedSecrets' own writes and
    # its rollback. `shutil.copymode` is called only by the registry write.
    monkeypatch.setattr(rs.shutil, "copymode", boom)
    with pytest.raises(StoreError) as e:
        store.apply(_add_a2, secrets={"K2": "cgk_two"})
    assert e.value.status == 500
    assert "K2" not in env and p.read_bytes() == before and holder.current is live
    assert store.memory_disk_diverged is False


def test_failed_rollback_marks_divergence(tmp_path, monkeypatch):
    store, *_ = _store(tmp_path)
    import chat_gateway.registry_store as rs
    monkeypatch.setattr(rs.shutil, "copymode", lambda *a, **kw: (_ for _ in ()).throw(OSError("x")))
    monkeypatch.setattr(store._secrets, "restore", lambda snap: (_ for _ in ()).throw(OSError("y")))
    with pytest.raises(StoreError):
        store.apply(_add_a2, secrets={"K2": "cgk_two"})
    assert store.memory_disk_diverged is True


def test_reload_picks_up_a_hand_edit(tmp_path):
    store, holder, _, p = _store(tmp_path)
    p.write_text(TEXT + "  a3:\n    key_env: K3\n    identities: [i1]\n    allow_inbound: false\n",
                 encoding="utf-8")
    store.reload()
    assert "a3" in holder.apps
    store.apply(_add_a2)  # hash re-recorded, so no 409


def test_reload_of_an_invalid_file_is_422_and_keeps_live(tmp_path):
    store, holder, _, p = _store(tmp_path)
    live = holder.current
    p.write_text("apps: {}\n", encoding="utf-8")
    with pytest.raises(StoreError) as e:
        store.reload()
    assert e.value.status == 422 and holder.current is live


def test_directory_registry_is_refused(tmp_path):
    d = tmp_path / "reg.d"
    d.mkdir()
    (d / "a.yaml").write_text(TEXT, encoding="utf-8")
    holder = RegistryHolder(load_registry(d))
    ms = ManagedSecrets(tmp_path / "m.env", process_env_names=frozenset(), environ={})
    with pytest.raises(RegistryError, match="directory"):
        RegistryStore(d, holder, ms)
