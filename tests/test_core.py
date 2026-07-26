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
