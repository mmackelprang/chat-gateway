"""Webhook payload/threading, Chat API body, Pub/Sub decode + routing."""

import base64
import datetime as dt
import json
from pathlib import Path

import httpx
import pytest

from chat_gateway.adapters.chat_api import ChatApiAdapter, ChatApiError
from chat_gateway.adapters.pubsub import (
    UNPARSEABLE, UNROUTED, FakePuller, SubscriberLoop, UnrecognizedEventError,
    detect_envelope, dispatch, normalize_event, redact_capability_urls,
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


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


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
        "envelope_format": "classic",
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


# --- dual-format normalization (CG-1) ---------------------------------------


def test_normalize_addon_message_from_real_capture():
    """The 2026-07-29 live bug: this real payload used to normalize into an
    empty husk with space="" and text="", which looked like a valid MESSAGE."""
    core = normalize_event(fixture("addon-message-event.json"))
    assert core == {
        "event_type": "MESSAGE",
        "space": "spaces/AAAAtestSpace",          # was "" — D2, routing dead
        "thread_key": None,                        # add-ons echoes no threadKey
        "thread_name": "spaces/AAAAtestSpace/threads/MSG1",
        "message_id": "spaces/AAAAtestSpace/messages/MSG1.MSG1",
        "sender_display": "Test User",
        "sender_email": "agent-user@example.com",
        "text": "Another test message.",           # was ""
        "action": None,
        "dedupe_key": None,
        "envelope_format": "addon",
    }


def test_both_formats_agree_on_the_same_logical_event():
    addon = normalize_event(fixture("addon-message-event.json"))
    classic = normalize_event(fixture("classic-message-event.json"))
    assert addon.pop("envelope_format") == "addon"
    assert classic.pop("envelope_format") == "classic"
    assert addon == classic


def test_normalize_addon_card_clicked():
    """⚠ Documentation-derived shape (CG-3 replaces this with a real capture).
    The action id arrives as the reserved __action_method_name__ parameter —
    commonEventObject.invokedFunction was removed from this runtime in 2025-05.
    """
    core = normalize_event(fixture("addon-card-clicked-event.json"))
    assert core["event_type"] == "CARD_CLICKED"
    assert core["space"] == "spaces/AAAAtestSpace"
    assert core["action"] == {
        "id": "verdict",
        "params": {"job_id": "job-123", "verdict": "reject", "nonce": "n-9",
                   "reject_reason": "wrong_seniority"},
    }
    # the reserved key must NOT leak through to the tenant
    assert "__action_method_name__" not in core["action"]["params"]


def test_action_id_parity_across_formats():
    """Same card, same tap, same InboundReply — whichever runtime we sit behind."""
    from test_callbacks import CARD_CLICK  # classic-format equivalent

    classic = normalize_event(CARD_CLICK)
    addon = normalize_event(fixture("addon-card-clicked-event.json"))
    assert classic["action"]["id"] == addon["action"]["id"] == "verdict"
    assert classic["action"]["params"] == addon["action"]["params"]


def test_addon_action_parameters_tolerate_list_form():
    """Defensive: we have never seen a real add-on interaction event. If Google
    sends the legacy list-of-{key,value} shape, we must still parse it."""
    event = fixture("addon-card-clicked-event.json")
    event["commonEventObject"]["parameters"] = [
        {"key": "__action_method_name__", "value": "verdict"},
        {"key": "job_id", "value": "job-123"},
    ]
    core = normalize_event(event)
    assert core["action"]["id"] == "verdict"
    assert core["action"]["params"]["job_id"] == "job-123"


@pytest.mark.parametrize("bad", [
    {},
    {"foo": 1},
    {"space": {"name": "spaces/AAA"}, "message": {"text": "no type field"}},
    {"type": ""},
    {"chat": {}},                              # add-ons shell, no *Payload
    {"chat": {"user": {}, "eventTime": "x"}},  # non-payload fields only
    {"_undecodable": True},                    # pull() could not decode
    [],
    "not-an-object",
])
def test_unrecognized_envelope_raises(bad):
    """Never a silent MESSAGE default — that is defect D1."""
    with pytest.raises(UnrecognizedEventError):
        normalize_event(bad)


def test_detect_envelope_labels_both_formats():
    assert detect_envelope(fixture("addon-message-event.json")) == "addon"
    assert detect_envelope(fixture("classic-message-event.json")) == "classic"


def test_addon_unknown_payload_type_is_named_not_defaulted():
    """A payload type Google adds later must route, with an honest name."""
    core = normalize_event({
        "commonEventObject": {},
        "chat": {"user": {"displayName": "T"},
                 "somethingNewPayload": {"space": {"name": "spaces/AAAAtestSpace"}}},
    })
    assert core["event_type"] == "SOMETHING_NEW"   # never "MESSAGE"
    assert core["space"] == "spaces/AAAAtestSpace"


@pytest.mark.parametrize("fmt,event", [
    ("addon", {"chat": {"user": {"displayName": None},
                        "messagePayload": {"space": {"name": None},
                                           "message": {"text": None}}}}),
    ("classic", {"type": "MESSAGE", "space": {"name": None},
                 "user": {"displayName": None}, "message": {"text": None}}),
])
def test_explicit_json_null_normalizes_instead_of_dropping_the_event(fmt, event, registry):
    """A .get() default only fires on an ABSENT key, so an explicit null on the
    wire used to reach InboundReply's str-declared fields and raise. That raise
    is caught now, but a caught event is an ACKED, DROPPED event — so the
    normalizer coerces instead, and the message is actually delivered."""
    core = normalize_event(event)
    assert core["envelope_format"] == fmt
    assert core["space"] == "" and core["text"] == "" and core["sender_display"] == ""

    # ...and it survives the full dispatch path rather than being counted lost.
    inbox = Inbox()
    assert dispatch(event, registry, inbox) == [UNROUTED]      # null space => unroutable
    audited = inbox.poll(UNROUTED)[0]
    assert audited.event_type == "MESSAGE"                     # NOT "UNPARSEABLE"
    assert audited.text == "" and audited.sender_display == ""


ADDON_REGISTRY_YAML = REGISTRY_YAML.replace('spaces/AAA"', 'spaces/AAAAtestSpace"')


@pytest.fixture()
def addon_registry(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(ADDON_REGISTRY_YAML, encoding="utf-8")
    return load_registry(p)


def test_addon_event_routes_to_owning_app(addon_registry):
    """D2 fixed at the routing layer, not just the parsing layer."""
    inbox = Inbox()
    assert dispatch(fixture("addon-message-event.json"), addon_registry, inbox) == [
        "aiteam-harness"]
    reply = inbox.poll("aiteam-harness")[0]
    assert reply.text == "Another test message."
    assert reply.envelope_format == "addon"


def test_unparseable_is_audited_and_never_routed_to_a_tenant(registry):
    """Hard rule #6 guard: a parse failure must not widen anyone's inbound
    surface. It goes to _unrouted, labelled, and nowhere else."""
    inbox = Inbox()
    assert dispatch({"garbage": True}, registry, inbox) == [UNROUTED]
    assert inbox.pending_counts() == {UNROUTED: 1}
    audited = inbox.poll(UNROUTED)[0]
    assert audited.event_type == UNPARSEABLE
    assert audited.envelope_format == "unparseable"
    assert audited.space == ""
    assert audited.raw == {"garbage": True}      # nothing lost


def test_dispatch_survives_a_non_dict_event(registry):
    """dispatch() must be total. redact_capability_urls returns a non-dict
    unchanged, so an unguarded raw= would make InboundReply raise INSIDE the
    except handler — escaping poll_once and wedging the subscription in the
    very poison-pill loop this path exists to prevent."""
    inbox = Inbox()
    for bad in ([], "not-an-object", 7):
        assert dispatch(bad, registry, inbox) == [UNROUTED]
    audited = inbox.poll(UNROUTED)
    assert len(audited) == 3
    assert {r.event_type for r in audited} == {UNPARSEABLE}
    assert [r.raw for r in audited] == [{}, {}, {}]


def test_poll_once_acks_unparseable_events(registry):
    """Anti-poison-pill: garbage must not stall well-formed events behind it."""
    inbox = Inbox()
    puller = FakePuller([CHAT_EVENT, {"garbage": True}, CHAT_EVENT])
    loop = SubscriberLoop(puller, registry, inbox)
    assert loop.poll_once() == 3
    assert puller.acked == ["ack-0", "ack-1", "ack-2"]   # ALL acked
    assert loop.unparseable_seen == 1
    assert len(inbox.poll("aiteam-harness")) == 2        # good ones delivered


GUARDED_REGISTRY_YAML = """
identities:
  guarded:
    display: "Guarded"
    mode: app
    space: "spaces/AAA"
apps:
  guarded-app:
    key_env: K
    identities: [guarded]
    allow_inbound: true
    allowed_users: [mark@mackelprang.com]
"""


class ScriptedPuller:
    """Hands out one preloaded batch per pull(), so a test can prove the loop
    keeps polling real work after a failure (FakePuller drains in one call)."""

    def __init__(self, batches):
        self._batches = [
            [(f"b{b}-ack-{i}", dict(e)) for i, e in enumerate(batch)]
            for b, batch in enumerate(batches)
        ]
        self.acked: list[str] = []

    def pull(self, max_messages: int = 10) -> list[tuple[str, dict]]:
        return self._batches.pop(0) if self._batches else []

    def acknowledge(self, ack_ids: list[str]) -> None:
        self.acked.extend(ack_ids)


def test_poll_once_acks_when_dispatch_raises(tmp_path):
    """Poison-pill part two: parsing is not the only thing that can fail.

    reply_fn is ChatApiAdapter.send_text in production and raises ChatApiError
    on any non-200. Reached here down the REAL path — an authorization refusal
    to a non-allowlisted sender — not by monkeypatching internals. If that
    escapes poll_once, the whole batch goes un-acked and Pub/Sub redelivers it
    forever: a total inbound outage.
    """
    p = tmp_path / "guarded.yaml"
    p.write_text(GUARDED_REGISTRY_YAML, encoding="utf-8")
    reg = load_registry(p)
    inbox = Inbox()

    def boom(space, thread_name, text):
        raise ChatApiError("chat send HTTP 403")   # what the live adapter raises

    stranger = {**CHAT_EVENT, "user": {"displayName": "Eve", "email": "eve@example.com"}}
    puller = ScriptedPuller([[CHAT_EVENT, stranger, CHAT_EVENT], [CHAT_EVENT]])
    loop = SubscriberLoop(puller, reg, inbox, reply_fn=boom)

    assert loop.poll_once() == 3                       # did not propagate
    assert puller.acked == ["b0-ack-0", "b0-ack-1", "b0-ack-2"]   # ALL of them
    assert loop.dispatch_errors == 1
    assert loop.unparseable_seen == 0                  # separate concerns, separate counters
    assert loop.events_seen == 3
    # the event AFTER the failing one was still processed
    assert len(inbox.poll("guarded-app")) == 2

    # ...and the loop is still alive for the next batch
    assert loop.poll_once() == 1
    assert puller.acked[-1] == "b1-ack-0"
    assert loop.dispatch_errors == 1 and loop.events_seen == 4
    assert len(inbox.poll("guarded-app")) == 1


def test_pull_survives_valid_but_non_object_json(registry):
    """Valid JSON that is not an object ([], "x", 7, null) used to make pull()
    raise TypeError on the messageId assignment — before a single ack id was
    collected, wedging the batch one layer above dispatch()."""
    from chat_gateway.adapters.pubsub import PubSubPuller

    bodies = [b"[]", b'"x"', b"7", b"null"]
    encoded = [base64.b64encode(b).decode() for b in bodies]

    acked: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(":pull"):
            return httpx.Response(200, json={"receivedMessages": [
                {"ackId": f"a{i}", "message": {"data": d, "messageId": f"m{i}"}}
                for i, d in enumerate(encoded)]})
        acked.append(json.loads(request.content)["ackIds"])
        return httpx.Response(200, json={})

    puller = PubSubPuller("projects/p/subscriptions/s", lambda: "tok",
                          client=mock_client(handler))
    batch = puller.pull()                                  # must not raise
    assert [a for a, _ in batch] == ["a0", "a1", "a2", "a3"]
    for _, event in batch:
        with pytest.raises(UnrecognizedEventError):
            normalize_event(event)

    # ...and each one takes the existing UNPARSEABLE path: audited, acked,
    # never attributed to a registered app (hard rule #6).
    inbox = Inbox()
    loop = SubscriberLoop(puller, registry, inbox)
    assert loop.poll_once() == 4
    assert acked == [["a0", "a1", "a2", "a3"]]
    assert loop.unparseable_seen == 4 and loop.dispatch_errors == 0
    assert {r.event_type for r in inbox.poll(UNROUTED)} == {UNPARSEABLE}


def test_classic_action_params_drop_reserved_action_key():
    """Parity (spec §4.5): the add-ons runtime pops __action_method_name__ out
    of params, so a classic event carrying it must not leak it to the tenant."""
    event = {**CHAT_EVENT, "type": "CARD_CLICKED",
             "action": {"actionMethodName": "verdict", "parameters": []},
             "common": {"parameters": [{"key": "__action_method_name__", "value": "verdict"},
                                       {"key": "job_id", "value": "job-123"}]}}
    core = normalize_event(event)
    assert core["action"]["id"] == "verdict"
    assert core["action"]["params"] == {"job_id": "job-123"}


def test_capability_field_redacted_even_when_not_a_string():
    """Redaction keys off the FIELD NAME, never the value's type: a wrapped
    object or list must not smuggle the capability URL past the guard."""
    url = "https://chat.google.com/bot_config_complete?token=LIVE"
    raw = redact_capability_urls({
        "chat": {"messagePayload": {
            "configCompleteRedirectUri": {"url": url, "nested": {"also": url}},
            "configCompleteRedirectUrl": [url],
        }},
    })
    flat = json.dumps(raw)
    assert "bot_config_complete?token=" not in flat
    assert flat.count("<redacted-by-gateway>") == 2


def test_dedupe_key_survives_both_formats():
    for name in ("addon-message-event.json", "classic-message-event.json"):
        event = {**fixture(name), "_pubsub_message_id": "ps-99"}
        assert normalize_event(event)["dedupe_key"] == "ps-99"


def test_capability_url_is_redacted_in_both_spellings():
    """DEC-7: `raw` is audited to disk and POSTed whole to tenant callbacks.
    That URL makes a private message public — it must not travel."""
    for name, field in (("addon-message-event.json", "configCompleteRedirectUri"),
                        ("classic-message-event.json", "configCompleteRedirectUrl")):
        raw = redact_capability_urls(fixture(name))
        flat = json.dumps(raw)
        assert "bot_config_complete?token=" not in flat
        assert flat.count("<redacted-by-gateway>") == 1
        assert field in json.dumps(raw)          # key kept, value blanked


def test_dispatch_stores_redacted_raw(addon_registry):
    inbox = Inbox()
    dispatch(fixture("addon-message-event.json"), addon_registry, inbox)
    reply = inbox.poll("aiteam-harness")[0]
    assert reply.raw["chat"]["messagePayload"]["configCompleteRedirectUri"] == \
        "<redacted-by-gateway>"
    # everything else survives — forwarded "whole" minus one capability field
    assert reply.raw["chat"]["messagePayload"]["message"]["text"] == "Another test message."
