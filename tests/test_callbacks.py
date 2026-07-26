"""jobhunt contract (R1/R3/R4/R6/R7): interaction forwarding, per-user
authorization, structured reasons, fail-loudly-in-thread, tenant opt-out."""

import datetime as dt

import httpx
import pytest

from chat_gateway.adapters.pubsub import NOT_AUTHORIZED_TEXT, dispatch
from chat_gateway.delivery import DeliveryLog
from chat_gateway.forwarder import CallbackForwarder
from chat_gateway.inbox import Inbox
from chat_gateway.registry import RegistryError, load_registry

UTC = dt.timezone.utc

JOBHUNT_YAML = """
identities:
  jobhunt:
    display: "Job Hunter"
    mode: app
    space: "spaces/JH"
apps:
  jobhunt:
    key_env: T_KEY_JOBHUNT
    identities: [jobhunt]
    allow_inbound: true
    callback_url: "http://127.0.0.1:9999/chat-callback"
    allowed_users: [mark@mackelprang.com]
    unreachable_message: "⚠️ couldn't reach jobhunt — use the review UI"
"""

CARD_CLICK = {
    "type": "CARD_CLICKED",
    "space": {"name": "spaces/JH"},
    "user": {"displayName": "Mark", "email": "Mark@Mackelprang.com"},
    "message": {
        "name": "spaces/JH/messages/M1",
        "thread": {"name": "spaces/JH/threads/T1", "threadKey": "digest-2026-07-24"},
    },
    "action": {
        "actionMethodName": "verdict",
        "parameters": [
            {"key": "job_id", "value": "job-123"},
            {"key": "verdict", "value": "reject"},
            {"key": "nonce", "value": "n-9"},
        ],
    },
    "common": {"formInputs": {"reject_reason": {"stringInputs": {"value": ["wrong_seniority"]}}}},
    "_pubsub_message_id": "ps-42",
}


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    monkeypatch.setenv("T_KEY_JOBHUNT", "cgk_jh")
    p = tmp_path / "r.yaml"
    p.write_text(JOBHUNT_YAML, encoding="utf-8")
    return load_registry(p)


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now


def make_forwarder(handler, clock, reply_sink=None):
    log = DeliveryLog()
    reply_fn = None
    if reply_sink is not None:
        reply_fn = lambda space, thread, text: reply_sink.append((space, thread, text))  # noqa: E731
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return CallbackForwarder(log, reply_fn, client=client, now_fn=clock), log


def test_authorized_interaction_forwards_whole(registry):
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200)

    fwd, log = make_forwarder(handler, clock)
    inbox = Inbox()
    delivered = dispatch(CARD_CLICK, registry, inbox, forwarder=fwd)
    assert delivered == ["jobhunt"]
    assert fwd.process_due() == 1

    body = seen["body"]
    assert seen["url"].endswith("/chat-callback")
    assert body["action"]["id"] == "verdict"
    assert body["action"]["params"] == {
        "job_id": "job-123", "verdict": "reject", "nonce": "n-9",
        "reject_reason": "wrong_seniority",   # R6: structured reason rides the params
    }
    assert body["sender_email"] == "Mark@Mackelprang.com"
    assert body["space"] == "spaces/JH" and body["message_id"] == "spaces/JH/messages/M1"
    assert body["dedupe_key"] == "ps-42"     # R3: idempotency key for at-least-once
    statuses = [e["status"] for e in log.query("jobhunt")]
    assert statuses == ["enqueued", "forwarded"]
    assert len(inbox.poll("jobhunt")) == 1   # inbox audit still gets a copy


def test_unauthorized_user_refused_in_thread_never_forwarded(registry):
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    refusals = []
    fwd, log = make_forwarder(lambda r: httpx.Response(200), clock)
    inbox = Inbox()
    event = {**CARD_CLICK, "user": {"displayName": "Eve", "email": "eve@example.com"}}
    delivered = dispatch(event, registry, inbox, forwarder=fwd,
                         reply_fn=lambda s, t, x: refusals.append((s, t, x)))
    assert delivered == []
    assert refusals == [("spaces/JH", "spaces/JH/threads/T1", NOT_AUTHORIZED_TEXT)]
    assert fwd.pending() == 0 and inbox.poll("jobhunt") == []


def test_callback_down_fails_loudly_in_thread(registry):
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    replies = []

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    fwd, log = make_forwarder(down, clock, reply_sink=replies)
    inbox = Inbox()
    dispatch(CARD_CLICK, registry, inbox, forwarder=fwd)
    fwd.process_due()                                    # attempt 1
    clock.now += dt.timedelta(seconds=4)
    fwd.process_due()                                    # attempt 2
    clock.now += dt.timedelta(seconds=8)
    fwd.process_due()                                    # attempt 3 -> give up loudly
    assert replies == [("spaces/JH", "spaces/JH/threads/T1",
                        "⚠️ couldn't reach jobhunt — use the review UI")]
    statuses = [e["status"] for e in log.query("jobhunt")]
    assert statuses[-1] == "failed" and fwd.pending() == 0


def test_opted_out_tenant_cannot_have_callback(tmp_path):
    bad = JOBHUNT_YAML.replace("allow_inbound: true", "allow_inbound: false")
    p = tmp_path / "bad.yaml"
    p.write_text(bad, encoding="utf-8")
    with pytest.raises(RegistryError, match="hard rule #6"):
        load_registry(p)


def test_opted_out_tenant_receives_nothing(registry, tmp_path):
    quiet = JOBHUNT_YAML.replace("allow_inbound: true", "allow_inbound: false").replace(
        '    callback_url: "http://127.0.0.1:9999/chat-callback"\n', "")
    p = tmp_path / "quiet.yaml"
    p.write_text(quiet, encoding="utf-8")
    reg = load_registry(p)
    inbox = Inbox()
    assert dispatch(CARD_CLICK, reg, inbox) == []
    assert inbox.poll("jobhunt") == []


def test_registry_directory_mode_one_file_per_tenant(tmp_path, monkeypatch):
    monkeypatch.setenv("T_KEY_JOBHUNT", "k1")
    d = tmp_path / "tenants.d"
    d.mkdir()
    (d / "jobhunt.yaml").write_text(JOBHUNT_YAML, encoding="utf-8")
    (d / "aitrader.yaml").write_text(
        "identities:\n  aitrader-alerts:\n    display: aitrader\n    mode: webhook\n"
        "    webhook_url_env: T_HOOK_AT\napps:\n  aitrader:\n    key_env: T_KEY_AT\n"
        "    identities: [aitrader-alerts]\n    allow_inbound: false\n",
        encoding="utf-8",
    )
    reg = load_registry(d)
    assert set(reg.apps) == {"jobhunt", "aitrader"}
    dup = d / "zz-dup.yaml"
    dup.write_text("identities: {}\napps:\n  jobhunt:\n    key_env: X\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="duplicate app"):
        load_registry(d)
