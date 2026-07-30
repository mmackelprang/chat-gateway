"""Envelope, registry, auth, inbox — the offline core."""

import datetime as dt

import pytest
from pydantic import ValidationError

from chat_gateway.auth import AuthError, authenticate, mint_key
from chat_gateway.envelope import InboundReply, OutboundMessage
from chat_gateway.inbox import Inbox
from chat_gateway.registry import RegistryError, load_registry

REGISTRY_YAML = """
identities:
  pm-familyworkspace:
    display: "PM · familyworkspace"
    mode: webhook
    webhook_url_env: TEST_HOOK_FW
    space: "spaces/AAA"
  job-hunter:
    display: "Job Hunter"
    mode: webhook
    webhook_url_env: TEST_HOOK_JH
apps:
  aiteam-harness:
    key_env: TEST_KEY_AITEAM
    identities: [pm-familyworkspace]
  job-hunter:
    key_env: TEST_KEY_JH
    identities: [job-hunter]
"""


@pytest.fixture()
def registry(tmp_path):
    p = tmp_path / "registry.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    return load_registry(p)


def test_envelope_validation():
    ok = OutboundMessage(identity="x", text="hello", cards=[{"cardId": "c", "card": {}}],
                         thread_key="t-1")
    assert ok.thread_key == "t-1"
    with pytest.raises(ValidationError):
        OutboundMessage(identity="x", text="")
    with pytest.raises(ValidationError):
        OutboundMessage(identity="x", text="hi", cards=[{"nope": 1}])
    with pytest.raises(ValidationError):
        OutboundMessage(identity="x", text="hi", thread_key="   ")


def test_registry_validation_errors(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("identities:\n  a:\n    mode: webhook\napps: {}\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="webhook_url_env"):
        load_registry(bad)
    bad.write_text(
        "identities: {}\napps:\n  x:\n    key_env: K\n    identities: [ghost]\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryError, match="unknown identity"):
        load_registry(bad)


def test_identity_permissions(registry):
    ident = registry.identity_for("aiteam-harness", "pm-familyworkspace")
    assert ident.display.startswith("PM")
    with pytest.raises(RegistryError, match="may not send as"):
        registry.identity_for("job-hunter", "pm-familyworkspace")
    with pytest.raises(RegistryError, match="unknown app"):
        registry.identity_for("nope", "job-hunter")


def test_env_indirection_and_health(registry, monkeypatch):
    ident = registry.identities["pm-familyworkspace"]
    with pytest.raises(RegistryError, match="TEST_HOOK_FW"):
        ident.webhook_url()
    monkeypatch.setenv("TEST_HOOK_FW", "https://chat.googleapis.com/v1/spaces/AAA/messages?key=k")
    assert ident.webhook_url().endswith("key=k")
    health = registry.health()
    assert health["identities"]["pm-familyworkspace"]["env_resolved"] is True
    assert health["identities"]["job-hunter"]["env_resolved"] is False
    assert health["apps"]["aiteam-harness"]["key_configured"] is False


def test_space_routing(registry):
    assert registry.apps_for_space("spaces/AAA") == ["aiteam-harness"]
    assert registry.apps_for_space("spaces/ZZZ") == []
    assert registry.apps_for_space("") == []


def test_auth_constant_time_lookup(registry, monkeypatch):
    key = mint_key()
    assert key.startswith("cgk_") and len(key) > 30
    monkeypatch.setenv("TEST_KEY_AITEAM", key)
    assert authenticate(registry, f"Bearer {key}") == "aiteam-harness"
    with pytest.raises(AuthError):
        authenticate(registry, "Bearer wrong")
    with pytest.raises(AuthError):
        authenticate(registry, None)
    with pytest.raises(AuthError):
        authenticate(registry, "Basic abc")


def test_inbox_poll_clears_and_audits(tmp_path):
    inbox = Inbox(audit_dir=tmp_path / "audit")
    reply = InboundReply(app="aiteam-harness", space="spaces/AAA", text="ship it",
                         received_at=dt.datetime(2026, 7, 24, 1, 0, tzinfo=dt.timezone.utc))
    inbox.put(reply)
    inbox.put(reply.model_copy(update={"text": "second"}))
    assert inbox.pending_counts() == {"aiteam-harness": 2}
    polled = inbox.poll("aiteam-harness")
    assert [r.text for r in polled] == ["ship it", "second"]
    assert inbox.poll("aiteam-harness") == []
    audit_files = list((tmp_path / "audit").glob("aiteam-harness-*.jsonl"))
    assert len(audit_files) == 1
    assert audit_files[0].read_text(encoding="utf-8").count("\n") == 2


def test_inbox_overflow_drops_oldest():
    inbox = Inbox(max_pending=2)
    now = dt.datetime.now(dt.timezone.utc)
    for i in range(4):
        inbox.put(InboundReply(app="a", space="s", text=str(i), received_at=now))
    polled = inbox.poll("a")
    assert [r.text for r in polled] == ["2", "3"]
    assert inbox.dropped == 2


# --- reserved app ids (CG-8) --------------------------------------------------


def test_reserved_app_ids_are_rejected(tmp_path):
    """`_unrouted` is the audit bucket for unroutable and UNPARSEABLE events,
    and the paths that write to it bypass the per-app authorization block by
    design. An app registered under it would drain every one of them, from every
    space. Pre-existing hole; needs a misconfiguration; real in a multi-tenant
    transport."""
    from chat_gateway.registry import UNROUTED

    for bad_id in (UNROUTED, "_internal", "_"):
        p = tmp_path / "r.yaml"
        p.write_text(
            "identities:\n"
            "  pm:\n"
            "    display: PM\n"
            "    webhook_url_env: HOOK\n"
            "apps:\n"
            f"  {bad_id}:\n"
            "    key_env: KEY\n"
            "    identities: [pm]\n"
            "    allow_inbound: true\n",
            encoding="utf-8",
        )
        with pytest.raises(RegistryError) as exc:
            load_registry(p)
        assert "reserved" in str(exc.value)
        assert "hard rule #6" in str(exc.value)


def test_ordinary_app_ids_with_underscores_still_load(tmp_path):
    """Only the PREFIX is reserved — `aiteam_harness` must keep working."""
    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n"
        "  pm:\n"
        "    display: PM\n"
        "    webhook_url_env: HOOK\n"
        "apps:\n"
        "  aiteam_harness:\n"
        "    key_env: KEY\n"
        "    identities: [pm]\n",
        encoding="utf-8",
    )
    assert "aiteam_harness" in load_registry(p).apps


def test_unrouted_still_importable_from_the_adapter(tmp_path):
    """The constant moved to core; the adapter re-exports it. Existing call
    sites import it from the adapter and must not break."""
    from chat_gateway.adapters.pubsub import UNROUTED as from_adapter
    from chat_gateway.registry import UNROUTED as from_core

    assert from_adapter is from_core == "_unrouted"


def test_the_hole_CG8_closes_is_real_and_now_shut(tmp_path, monkeypatch):
    """Not just "the id is rejected" — prove WHAT it would have drained.

    The plan's tests assert the rejection. This one demonstrates the
    consequence, because a reader six months from now will want to know whether
    the guard is protecting against something real or is defensive noise.

    Registers `_unrouted` as a normal-looking tenant with allow_inbound: true,
    bypasses the registry guard to build it anyway, and shows that an
    UNPARSEABLE event from a space that tenant owns NOTHING in still lands in
    its inbox — with no hard-rule-#6 authorization check having run.
    """
    from chat_gateway.adapters.pubsub import UNROUTED, dispatch
    from chat_gateway.inbox import Inbox
    from chat_gateway.registry import App, Registry

    monkeypatch.setenv("KEY", "cgk_x")
    monkeypatch.setenv("HOOK", "https://x.example/h")

    # Construct what the registry now REFUSES to load, to show why it refuses.
    attacker = App(app_id=UNROUTED, key_env="KEY", identities=[],
                   allow_inbound=True)
    reg = Registry(identities={}, apps={UNROUTED: attacker})
    inbox = Inbox()

    # An event the gateway cannot parse — no space, so nothing to authorize on.
    dispatch({"totally": "unrecognized"}, reg, inbox)

    stolen = inbox.poll(UNROUTED)
    assert stolen, "the hole is not real — this test would be pointless"
    # It arrives as a pollable InboundReply attributed to this app, i.e. exactly
    # what GET /v1/inbox would hand a caller holding that app's key.
    assert stolen[0].app == UNROUTED
    assert stolen[0].event_type == "UNPARSEABLE"
    # ...and that is precisely why the id may no longer be registered:
    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n  pm:\n    display: PM\n    webhook_url_env: HOOK\n"
        f"apps:\n  {UNROUTED}:\n    key_env: KEY\n    identities: [pm]\n"
        "    allow_inbound: true\n", encoding="utf-8")
    with pytest.raises(RegistryError):
        load_registry(p)
