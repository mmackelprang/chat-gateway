"""Webhook payload/threading, Chat API body, Pub/Sub decode + routing."""

import base64
import datetime as dt
import json

import httpx
import pytest

from chat_gateway.adapters.chat_api import ChatApiAdapter, ChatApiError
from chat_gateway.adapters.pubsub import (
    UNROUTED, FakePuller, SubscriberLoop, dispatch, normalize_event,
)
from chat_gateway.adapters.webhook import (
    WebhookAdapter, WebhookDeliveryError, build_params, build_payload,
)
from chat_gateway.envelope import OutboundMessage
from chat_gateway.inbox import Inbox
from chat_gateway.registry import Identity, load_registry

MSG = OutboundMessage(
    identity="pm-familyworkspace",
    text="Review needed",
    cards=[{"cardId": "c1", "card": {"header": {"title": "PM · familyworkspace"}}}],
    thread_key="review-PC-12",
)


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_webhook_payload_and_params():
    payload = build_payload(MSG)
    assert payload["text"] == "Review needed"
    assert payload["cardsV2"][0]["cardId"] == "c1"
    assert payload["thread"] == {"threadKey": "review-PC-12"}
    params = build_params(MSG)
    assert params["threadKey"] == "review-PC-12"
    assert params["messageReplyOption"] == "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
    bare = OutboundMessage(identity="x", text="hi")
    assert "thread" not in build_payload(bare) and build_params(bare) == {}


def test_webhook_send_success_and_error(monkeypatch):
    monkeypatch.setenv("HOOK", "https://chat.googleapis.com/v1/spaces/A/messages?key=SECRET")
    ident = Identity(name="pm", display="PM", webhook_url_env="HOOK")
    seen = {}

    def ok(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"name": "spaces/A/messages/1"})

    result = WebhookAdapter(mock_client(ok)).send(ident, MSG)
    assert result.status == "delivered" and result.mode == "webhook"
    assert "key=SECRET" in seen["url"] and "threadKey=review-PC-12" in seen["url"]
    assert seen["body"]["text"] == "Review needed"

    def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    with pytest.raises(WebhookDeliveryError) as exc:
        WebhookAdapter(mock_client(fail)).send(ident, MSG)
    assert "SECRET" not in str(exc.value)  # never leak the URL


def test_chat_api_adapter_body_and_space_guard():
    ident = Identity(name="pm", display="PM", mode="app", space="spaces/AAA")
    seen = {}

    def ok(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"name": "spaces/AAA/messages/9"})

    adapter = ChatApiAdapter(lambda: "tok-123", mock_client(ok))
    result = adapter.send(ident, MSG)
    assert result.mode == "app"
    assert seen["auth"] == "Bearer tok-123"
    assert seen["url"].startswith("https://chat.googleapis.com/v1/spaces/AAA/messages")
    assert seen["body"]["thread"] == {"threadKey": "review-PC-12"}

    with pytest.raises(ChatApiError, match="no space"):
        adapter.send(Identity(name="x", display="X", mode="app", space=""), MSG)


CHAT_EVENT = {
    "type": "MESSAGE",
    "space": {"name": "spaces/AAA"},
    "message": {
        "text": "approved — ship it",
        "thread": {"name": "spaces/AAA/threads/T", "threadKey": "review-PC-12"},
        "sender": {"displayName": "Mark", "email": "mark@mackelprang.com"},
    },
}

REGISTRY_YAML = """
identities:
  pm-familyworkspace:
    display: "PM"
    mode: webhook
    webhook_url_env: H
    space: "spaces/AAA"
apps:
  aiteam-harness:
    key_env: K
    identities: [pm-familyworkspace]
"""


@pytest.fixture()
def registry(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    return load_registry(p)


def test_normalize_event():
    core = normalize_event(CHAT_EVENT)
    assert core == {
        "event_type": "MESSAGE",
        "space": "spaces/AAA",
        "thread_key": "review-PC-12",
        "thread_name": "spaces/AAA/threads/T",
        "message_id": None,
        "sender_display": "Mark",
        "sender_email": "mark@mackelprang.com",
        "text": "approved — ship it",
        "action": None,
        "dedupe_key": None,
    }


def test_dispatch_routes_by_space(registry):
    inbox = Inbox()
    assert dispatch(CHAT_EVENT, registry, inbox) == ["aiteam-harness"]
    replies = inbox.poll("aiteam-harness")
    assert replies[0].thread_key == "review-PC-12"
    assert replies[0].raw["type"] == "MESSAGE"
    # unroutable space -> audited under _unrouted, never dropped
    other = {**CHAT_EVENT, "space": {"name": "spaces/ZZZ"}}
    assert dispatch(other, registry, inbox) == [UNROUTED]
    assert inbox.poll(UNROUTED)[0].space == "spaces/ZZZ"


def test_subscriber_loop_poll_once_acks(registry):
    inbox = Inbox()
    puller = FakePuller([CHAT_EVENT, {**CHAT_EVENT, "message": {"text": "second"}}])
    loop = SubscriberLoop(puller, registry, inbox)
    assert loop.poll_once() == 2
    assert loop.events_seen == 2 and loop.last_poll_at is not None
    assert puller.acked == ["ack-0", "ack-1"]
    assert len(inbox.poll("aiteam-harness")) == 2


def test_pubsub_wire_decode(registry):
    """PubSubPuller's decode path via a mocked REST transport."""
    from chat_gateway.adapters.pubsub import PubSubPuller

    encoded = base64.b64encode(json.dumps(CHAT_EVENT).encode()).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(":pull"):
            return httpx.Response(200, json={"receivedMessages": [
                {"ackId": "a1", "message": {"data": encoded}}]})
        assert request.url.path.endswith(":acknowledge")
        assert json.loads(request.content) == {"ackIds": ["a1"]}
        return httpx.Response(200, json={})

    puller = PubSubPuller("projects/p/subscriptions/s", lambda: "tok",
                          client=mock_client(handler))
    batch = puller.pull()
    assert batch[0][0] == "a1" and batch[0][1]["type"] == "MESSAGE"
    puller.acknowledge(["a1"])
