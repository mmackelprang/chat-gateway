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
    _action_params, detect_envelope, dispatch, normalize_event,
    redact_capability_urls,
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
    """One threading mechanism, not two (proven redundant live 2026-07-29).

    The body carries thread affinity; the query carries only
    messageReplyOption, whose necessity was never isolated and which therefore
    stays. See the module docstring for exactly what the experiment proved.
    """
    payload = build_payload(MSG)
    assert payload["text"] == "Review needed"
    assert payload["cardsV2"][0]["cardId"] == "c1"
    assert payload["thread"] == {"threadKey": "review-PC-12"}
    params = build_params(MSG)
    assert params == {"messageReplyOption": "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"}
    assert "threadKey" not in params          # dropped: redundant with the body
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
    assert "key=SECRET" in seen["url"]                    # existing query survives
    assert "threadKey=" not in seen["url"]                # dropped 2026-07-29
    assert "messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD" in seen["url"]
    assert seen["body"]["thread"] == {"threadKey": "review-PC-12"}   # the sole mechanism
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


def test_send_text_wraps_transport_failure_as_chat_api_error():
    """CG-25: send_text() is jobhunt R7's in-thread failure notice and R4's
    authorization refusal — the one method whose entire job is telling a user
    something went wrong. Before this, a connection reset, DNS failure or read
    timeout propagated as a raw httpx exception, so a caller could only tell
    "Google refused us" from "we never reached Google" by string-matching an
    exception type instead of catching ChatApiError like every other adapter
    path. This drives a transport failure (never a response) through
    MockTransport and asserts the raw exception no longer escapes, the message
    names the exception TYPE only (never a body, URL or space — that shape is
    CG-23's separate scope), and `from exc` is preserved so a debugger still
    has the original traceback.
    """
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    adapter = ChatApiAdapter(lambda: "tok-123", mock_client(unreachable))
    with pytest.raises(ChatApiError) as exc:
        adapter.send_text("spaces/AAA", "spaces/AAA/threads/T", "you are not authorized")

    assert "ConnectError" in str(exc.value)
    assert isinstance(exc.value.__cause__, httpx.ConnectError)


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


# --- poll-failure visibility (CG-7) -----------------------------------------
#
# NOTE: the tests below drive PubSubPuller / SubscriberLoop with a MOCK
# transport and a fake puller. That is not a live round-trip and clears nothing.
#
# Scoped precisely, because the blanket version of this comment went stale:
# `pull()` and `acknowledge()` WERE cleared live on 2026-07-30 (CG-24). What
# these tests exercise is `_post`'s NON-200 branch, which is still
# ⚠ LIVE-UNVERIFIED — no Google error response has ever been observed. Driving a
# 429 through MockTransport does not change that.


def test_pubsub_error_carries_status_not_response_body():
    """Hard rule #2: a Google error body can quote the request, and the request
    path names the subscription. Status and reason phrase only."""
    from chat_gateway.adapters.pubsub import PubSubError, PubSubPuller

    def quota_exhausted(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="RESOURCE_EXHAUSTED on projects/p/subscriptions/s")

    puller = PubSubPuller("projects/p/subscriptions/s", lambda: "tok",
                          mock_client(quota_exhausted))
    with pytest.raises(PubSubError) as exc:
        puller.pull()
    assert exc.value.status_code == 429
    assert "RESOURCE_EXHAUSTED" not in str(exc.value)
    assert "projects/p/subscriptions/s" not in str(exc.value)


def test_run_loop_counts_poll_failures_and_clears_the_run_on_recovery(registry):
    """The CG-7 defect lived HERE, not only in /healthz: `_run` swallowed every
    poll exception with a print, so a subscription that had never worked moved
    NO counter at all — healthz had nothing it could have reported honestly.

    Also pins the recovery semantics /healthz depends on: the RUN resets, the
    lifetime total does not (an operator needs to see it flapped)."""
    from chat_gateway.adapters.pubsub import PubSubError

    inbox = Inbox()

    class Failing:
        """Raises once, then stops the loop so `_run` executes one iteration."""

        def pull(self, max_messages: int = 10):
            loop._stop.set()
            raise PubSubError("pull", 429, "Too Many Requests")

        def acknowledge(self, ack_ids):  # pragma: no cover — never reached
            raise AssertionError("acknowledge after a failed pull")

    loop = SubscriberLoop(Failing(), registry, inbox, interval_seconds=0)
    loop._run()
    assert loop.poll_failures == 1 and loop.consecutive_poll_failures == 1
    # A TYPE and a STATUS — never Google's prose (rule #2).
    assert loop.last_poll_error == "PubSubError HTTP 429"
    assert loop.last_poll_at is None            # no poll has ever succeeded

    class Recovering(FakePuller):
        def pull(self, max_messages: int = 10):
            loop._stop.set()
            return super().pull(max_messages)

    loop._puller = Recovering([CHAT_EVENT])
    loop._stop.clear()
    loop._run()
    assert loop.consecutive_poll_failures == 0 and loop.last_poll_error is None
    assert loop.poll_failures == 1               # lifetime history is not erased
    assert loop.last_poll_at is not None


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
    """CONSTRUCTED fixture — a shape we have NOT observed.

    The real 2026-07-29 capture (addon-buttonclicked-event.json) contained no
    `__action_method_name__` at all. This fixture is kept as tolerance coverage
    for a card style we have not seen — one whose action.function is an
    ordinary function name rather than a topic path — not as a statement about
    what the add-ons runtime sends. Do not "fix" it to match the real capture;
    they cover different things.
    """
    core = normalize_event(fixture("addon-card-clicked-event.json"))
    assert core["event_type"] == "CARD_CLICKED"
    assert core["space"] == "spaces/AAAAtestSpace"
    assert core["action"] == {
        "id": "verdict",
        "id_source": "google",          # native slot, not __cg_action__ (CG-10)
        "params": {"job_id": "job-123", "verdict": "reject", "nonce": "n-9",
                   "reject_reason": "wrong_seniority"},
    }
    # the reserved key must NOT leak through to the tenant
    assert "__action_method_name__" not in core["action"]["params"]


def test_action_id_parity_across_formats():
    """Parity holds GIVEN the add-ons runtime supplies __action_method_name__.

    That condition was previously implicit and read as a guarantee. The real
    2026-07-29 capture did not satisfy it — the add-on side yielded
    action.id == "" — so this asserts a conditional property of a constructed
    fixture, not an observed one. See test_real_button_click_action_id_is_
    empty_KNOWN_DEFECT and queue item CG-10.
    """
    from test_callbacks import CARD_CLICK  # classic-format equivalent

    classic = normalize_event(CARD_CLICK)
    addon = normalize_event(fixture("addon-card-clicked-event.json"))
    assert classic["action"]["id"] == addon["action"]["id"] == "verdict"
    assert classic["action"]["params"] == addon["action"]["params"]


def test_addon_action_parameters_tolerate_list_form():
    """Defensive. The one real add-on interaction we have captured sent
    `parameters` as a flat MAP (2026-07-29), so this list branch has still
    never been seen in the wild. Kept because Google's classic runtime does
    send the list form and _action_params is shared."""
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


# --- the real add-on interaction capture (CG-3) ------------------------------


def test_normalize_real_addon_button_click():
    """REAL capture, 2026-07-29 — the first genuine card interaction this
    project has ever received. Pins what Google ACTUALLY sends, as opposed to
    what the constructed fixture assumes.

    Note `text`: on an interaction it is the CARD's message text, not anything
    the user typed. A consumer reading it as user intent will be wrong.
    """
    core = normalize_event(fixture("addon-buttonclicked-event.json"))
    assert core["event_type"] == "CARD_CLICKED"
    assert core["envelope_format"] == "addon"
    assert core["space"] == "spaces/AAAAtestRoom"
    assert core["thread_name"] == "spaces/AAAAtestRoom/threads/MSG2"
    assert core["message_id"] == "spaces/AAAAtestRoom/messages/MSG2.MSG2"
    assert core["sender_display"] == "Test User"          # the tapper, not the app
    assert core["sender_email"] == "agent-user@example.com"
    assert core["text"] == "probe 2: change the dropdown, then tap the button"
    assert core["dedupe_key"] == "20751388131856523"


def test_real_button_click_merges_selection_widget_value_into_params():
    """The selection-widget truth, on real data.

    A selectionInput's *value* arrives in commonEventObject.formInputs and is
    harvested at button-submit time, merged alongside the button's own action
    parameters. This is what makes jobhunt R6's structured reject reason work —
    and it is NOT the same as a widget being an interaction trigger, which was
    disproven the same day (onChangeAction fails exactly like a button:
    gsuiteaddons code 13).

    Also confirms `parameters` really does arrive as a flat map in this runtime;
    the list-form tolerance in _action_params remains untested against reality.
    """
    core = normalize_event(fixture("addon-buttonclicked-event.json"))
    assert core["action"]["params"] == {"probe": "topic-as-fn", "decision": "approve"}


def test_real_button_click_action_id_is_absent_not_empty():
    """REWRITTEN by CG-10 (it pinned `action.id == ""` as a named defect).

    The defect was the ambiguity, not the missing value. This capture genuinely
    carries no action identity — the card's button routed via
    `action.function = "projects/chat-gateway-prod/topics/chat-gateway-events"`,
    so the add-ons runtime sent no `__action_method_name__`, no
    `invokedFunction` and no `payload.action`. What was wrong is that the
    gateway reported that as `""`, which a tenant cannot distinguish from an
    action legitimately NAMED empty-string.

    Now it is `None` — semantically absent — with `id_source` also None, and
    the event is still forwarded (ADR-0001 D4: a parse-quality problem must not
    become a silent drop). Producers fix it by setting `__cg_action__`.
    """
    core = normalize_event(fixture("addon-buttonclicked-event.json"))
    assert core["action"]["id"] is None
    assert core["action"]["id_source"] is None
    assert core["action"]["params"] == {"probe": "topic-as-fn", "decision": "approve"}


def test_cg_action_key_supplies_identity_and_is_popped():
    """ADR-0001 D2, the bridge's whole point: the producer declares identity in
    a gateway-reserved parameter, because topic-as-function ate Google's slot.

    `id_source == "cg_param"` is the detector — if Google ever starts filling
    the native slot again it flips to "google" and we find out before it
    breaks something.
    """
    event = fixture("addon-buttonclicked-event.json")
    event["commonEventObject"]["parameters"] = {
        "__cg_action__": "verdict", "job_id": "job-123", "nonce": "n-9"}
    core = normalize_event(event)
    assert core["action"]["id"] == "verdict"
    assert core["action"]["id_source"] == "cg_param"
    # popped: a tenant never sees gateway transport plumbing in its own params
    assert core["action"]["params"] == {
        "job_id": "job-123", "nonce": "n-9", "decision": "approve"}


def test_unknown_cg_prefixed_keys_pass_through_rather_than_being_eaten():
    """ADR-0001 D2 reserves the whole `__cg_` prefix but only CONSUMES the keys
    it understands. Silently discarding an unrecognized one would be the
    gateway destroying data it does not understand — the same instinct that
    made an unparsed event normalize into an empty MESSAGE."""
    event = fixture("addon-buttonclicked-event.json")
    event["commonEventObject"]["parameters"] = {
        "__cg_action__": "verdict", "__cg_future__": "something-we-dont-know-yet"}
    core = normalize_event(event)
    assert core["action"]["id"] == "verdict"
    assert core["action"]["params"]["__cg_future__"] == "something-we-dont-know-yet"


def test_topic_path_from_a_native_source_is_never_promoted_to_action_id():
    """ADR-0001 D2's mandatory guard, and it is a CLASSIC-runtime hazard.

    A portable card sets action.function to the gateway-published routing
    target. Under the add-ons runtime the runtime consumes it; under classic
    the SAME card echoes it straight back in action.function, where the native
    resolution order would promote it. `action.id == "projects/…/topics/…"` is
    a plausible-looking WRONG answer, and a wrong answer is worse than an
    absent one — a tenant would happily branch on it.
    """
    event = {
        "type": "CARD_CLICKED",
        "space": {"name": "spaces/JH"},
        "user": {"displayName": "Mark", "email": "mark@example.com"},
        "message": {"name": "spaces/JH/messages/M1"},
        "action": {"function": "projects/chat-gateway-prod/topics/chat-gateway-events",
                   "parameters": [{"key": "job_id", "value": "job-123"}]},
    }
    core = normalize_event(event)
    assert core["action"]["id"] is None, "a topic path must never become an action id"
    assert core["action"]["id_source"] is None
    assert core["action"]["params"] == {"job_id": "job-123"}

    # ...and the same card WITH the reserved key resolves, proving the guard
    # discards only the artifact and not the interaction. This is D3's payoff:
    # one card, both deployment models, zero producer changes.
    event["action"]["parameters"].append({"key": "__cg_action__", "value": "verdict"})
    core = normalize_event(event)
    assert core["action"]["id"] == "verdict"
    assert core["action"]["id_source"] == "cg_param"


def test_a_real_function_name_is_still_accepted_from_the_native_slot():
    """The guard must not be over-broad: an ordinary function name, and even a
    project-shaped string that is NOT a topic path, still resolve natively."""
    base = {
        "type": "CARD_CLICKED", "space": {"name": "spaces/JH"},
        "user": {"email": "mark@example.com"}, "message": {},
    }
    for fn in ("approve", "projects/p/subscriptions/s",
               "projects/p/topics/t/extra", "projectsX/p/topics/t"):
        core = normalize_event({**base, "action": {"function": fn}})
        assert core["action"]["id"] == fn, f"{fn!r} should resolve natively"
        assert core["action"]["id_source"] == "google"


def test_native_source_priority_is_identical_in_both_runtimes():
    """ADR-0001 D2 lists ONE native order for both runtimes:
    __action_method_name__, then the action object's own name, then
    invokedFunction last. Two normalizers silently disagreeing is how the same
    card starts yielding different action ids depending on which Google runtime
    happens to deliver it — the exact parity CG-1 was written to guarantee.

    Every candidate is populated with a distinct value, so the assertion is
    about ORDER and cannot pass by coincidence.
    """
    addon = normalize_event({
        "commonEventObject": {
            "parameters": {"__action_method_name__": "from_reserved_key"},
            "invokedFunction": "from_invoked_function"},
        "chat": {"user": {"email": "m@example.com"},
                 "buttonClickedPayload": {
                     "space": {"name": "spaces/AAA"}, "message": {},
                     "action": {"actionMethodName": "from_action_object"}}},
    })
    classic = normalize_event({
        "type": "CARD_CLICKED", "space": {"name": "spaces/AAA"},
        "user": {"email": "m@example.com"}, "message": {},
        "action": {"actionMethodName": "from_action_object",
                   "parameters": [{"key": "__action_method_name__",
                                   "value": "from_reserved_key"}]},
        "common": {"invokedFunction": "from_invoked_function"},
    })
    assert addon["action"]["id"] == classic["action"]["id"] == "from_reserved_key"

    # ...and with the reserved key gone, the action object still outranks
    # invokedFunction on BOTH sides. This is the pair that was reversed.
    addon2 = normalize_event({
        "commonEventObject": {"parameters": {},
                              "invokedFunction": "from_invoked_function"},
        "chat": {"user": {"email": "m@example.com"},
                 "buttonClickedPayload": {
                     "space": {"name": "spaces/AAA"}, "message": {},
                     "action": {"actionMethodName": "from_action_object"}}},
    })
    classic2 = normalize_event({
        "type": "CARD_CLICKED", "space": {"name": "spaces/AAA"},
        "user": {"email": "m@example.com"}, "message": {},
        "action": {"actionMethodName": "from_action_object"},
        "common": {"invokedFunction": "from_invoked_function"},
    })
    assert addon2["action"]["id"] == classic2["action"]["id"] == "from_action_object"
    assert addon2["action"]["id_source"] == classic2["action"]["id_source"] == "google"


def test_missing_action_id_is_counted_and_still_forwarded(registry):
    """ADR-0001 D4. Both halves matter.

    Counted, because if topic-as-function routing ever breaks the likely
    observable on our side is nothing at all (ADR §8) — this is one of the few
    signals. Still FORWARDED, because hard rule #6 says forward whole and let
    the tenant enforce: a parse-quality problem must not silently become a drop.
    """
    inbox = Inbox()
    event = {**fixture("addon-buttonclicked-event.json")}
    event["chat"]["buttonClickedPayload"]["space"]["name"] = "spaces/AAA"
    event["chat"]["buttonClickedPayload"]["message"]["space"]["name"] = "spaces/AAA"

    loop = SubscriberLoop(FakePuller([event]), registry, inbox)
    assert loop.poll_once() == 1
    assert loop.interactions_without_action_id == 1
    assert loop.unparseable_seen == 0 and loop.dispatch_errors == 0

    delivered = inbox.poll("aiteam-harness")
    assert len(delivered) == 1, "an unidentified action must still reach the tenant"
    assert delivered[0].action["id"] is None
    assert delivered[0].action["params"]["decision"] == "approve"


def test_resolved_action_id_does_not_touch_the_counter(registry):
    """The counter must mean what it says, or it is worse than nothing."""
    inbox = Inbox()
    event = {**fixture("addon-buttonclicked-event.json")}
    event["chat"]["buttonClickedPayload"]["space"]["name"] = "spaces/AAA"
    event["chat"]["buttonClickedPayload"]["message"]["space"]["name"] = "spaces/AAA"
    event["commonEventObject"]["parameters"] = {"__cg_action__": "verdict"}

    loop = SubscriberLoop(FakePuller([event]), registry, inbox)
    loop.poll_once()
    assert loop.interactions_without_action_id == 0


def test_card_parameters_are_an_array_in_the_real_captured_card():
    """PINS THE OUTBOUND SHAPE against a real card that really worked.

    `parameters` has two shapes and the asymmetry is a live tripwire:

        the CARD you send      -> an ARRAY of {"key", "value"}   (Cards v2)
        the EVENT you get back -> a MAP under commonEventObject  (add-ons)

    docs/integration-guide.md's card convention originally showed the MAP shape
    in the card, copied from an illustrative sketch. A producer following it
    would have built a card that is not valid Cards v2 — failing at render or
    tap time, in front of a user. Caught in review before it shipped.

    The authority here is not documentation: this fixture is a card WE sent,
    that Google accepted, that a human tapped, echoed back verbatim in the
    interaction event. If the guide ever drifts from this shape again, this
    fails.
    """
    cap = fixture("addon-buttonclicked-event.json")
    card = cap["chat"]["buttonClickedPayload"]["message"]["cardsV2"][0]
    buttons = [w["buttonList"]["buttons"]
               for s in card["card"]["sections"] for w in s["widgets"]
               if "buttonList" in w]
    assert buttons, "fixture must still contain a button to pin"
    sent = buttons[0][0]["onClick"]["action"]["parameters"]

    assert isinstance(sent, list), (
        "a CARD's action.parameters is an ARRAY of {key, value} — if this ever "
        "becomes a dict, docs/integration-guide.md is wrong and so is this test"
    )
    assert all(set(p) == {"key", "value"} for p in sent)

    # ...and the INBOUND side of the same event is the map form.
    assert isinstance(cap["commonEventObject"]["parameters"], dict)

    # Both shapes normalize identically, which is why a producer never has to
    # think about the inbound one.
    assert _action_params(sent) == _action_params(
        cap["commonEventObject"]["parameters"]) == {"probe": "topic-as-fn"}


def test_the_documented_card_convention_round_trips_on_both_runtimes():
    """Builds a card EXACTLY as docs/integration-guide.md instructs — array
    parameters, routing target in `function`, identity in `__cg_action__` — and
    drives it through both normalizers. A doc that produces a card which
    silently fails is worse than no doc, so the doc's literal shape is the
    input here, not a convenient paraphrase of it."""
    from chat_gateway.adapters.pubsub import CG_ACTION_KEY

    routing_target = "projects/chat-gateway-prod/topics/chat-gateway-events"
    card_params = [
        {"key": CG_ACTION_KEY, "value": "verdict"},
        {"key": "job_id", "value": "job-123"},
    ]

    classic = normalize_event({
        "type": "CARD_CLICKED", "space": {"name": "spaces/JH"},
        "user": {"email": "m@example.com"}, "message": {},
        # classic echoes the card's own array form back, routing target included
        "action": {"function": routing_target, "parameters": card_params},
    })
    addon = normalize_event({
        # the add-ons runtime consumes `function` and flattens params to a map
        "commonEventObject": {"parameters": {p["key"]: p["value"] for p in card_params}},
        "chat": {"user": {"email": "m@example.com"},
                 "buttonClickedPayload": {"space": {"name": "spaces/JH"}, "message": {}}},
    })

    assert classic["action"] == addon["action"] == {
        "id": "verdict", "id_source": "cg_param", "params": {"job_id": "job-123"}}


def test_inbound_parameter_shape_is_a_runtime_property_not_a_direction_rule():
    """The correction to a correction, and worth pinning precisely.

    It is tempting to summarize the shapes as "you send an array, you receive a
    map". That is WRONG, and it was briefly written down that way. The map is an
    **add-ons-runtime** quirk, not a property of the inbound direction:

        outbound, every runtime -> ARRAY of {"key","value"}   (Cards v2)
        inbound, classic        -> ARRAY under action.parameters (symmetric!)
        inbound, add-ons        -> MAP under commonEventObject.parameters

    Both inbound shapes are now first-hand AND landed: the add-ons map from
    addon-buttonclicked-event.json, the classic array from
    classic-cardclicked-button-event.json. This test previously hand-transcribed
    the classic half from a capture that had not been committed; CG-22 landed the
    fixture and the transcription is gone.

    The reason this matters to a reader rather than only to us: a producer
    debugging a raw classic event who had been told "inbound is a map" would
    conclude the gateway was broken.
    """
    addon_cap = fixture("addon-buttonclicked-event.json")
    classic_cap = fixture("classic-cardclicked-button-event.json")

    assert isinstance(addon_cap["commonEventObject"]["parameters"], dict)
    assert isinstance(classic_cap["action"]["parameters"], list)
    assert classic_cap["action"]["parameters"] == [{"key": "jobId", "value": "mig-001"}]

    # ...and both inbound shapes flatten to the same kind of thing, which is why
    # a producer never has to know any of the above.
    assert normalize_event(classic_cap)["action"]["params"] == {
        "jobId": "mig-001", "reason": "good_fit"}
    assert _action_params(addon_cap["commonEventObject"]["parameters"]) == {
        "probe": "topic-as-fn"}


# --- the real CLASSIC captures (CG-22) ---------------------------------------


def test_normalize_real_classic_button_click():
    """REAL capture, 2026-07-30, live project `chat-gateway-gw`, real consumer space.

    The classic counterpart of `test_normalize_real_addon_button_click`, and the
    contrast is the point: the add-ons capture resolves `action.id` to None
    because topic-as-function ate the identity slot, and this one resolves it
    NATIVELY from `action.actionMethodName`.
    """
    core = normalize_event(fixture("classic-cardclicked-button-event.json"))
    assert core["envelope_format"] == "classic"
    assert core["event_type"] == "CARD_CLICKED"
    assert core["space"] == "spaces/AAAAclassicRoom"
    assert core["thread_name"] == "spaces/AAAAclassicRoom/threads/MIG1"
    assert core["message_id"] == "spaces/AAAAclassicRoom/messages/MIG1.MIG1"
    # the TAPPER, not the BOT that posted the card
    assert core["sender_display"] == "Test User"
    assert core["action"] == {
        "id": "approve",
        "id_source": "google",
        # jobId from action.parameters (the ARRAY), reason harvested from
        # common.formInputs at submit time — one event, both sources merged.
        "params": {"jobId": "mig-001", "reason": "good_fit"},
    }


def test_classic_supplies_action_identity_natively_unlike_the_addon_capture():
    """E1's headline result, now pinned against real bytes from BOTH runtimes.

    `__cg_action__` is the FALLBACK that keeps a card working on the add-ons
    side; this is why it is a fallback and not the mechanism. Neither capture
    carries `__cg_action__` — the difference is entirely Google's.
    """
    classic = normalize_event(fixture("classic-cardclicked-button-event.json"))
    addon = normalize_event(fixture("addon-buttonclicked-event.json"))
    assert (classic["action"]["id"], classic["action"]["id_source"]) == ("approve", "google")
    assert (addon["action"]["id"], addon["action"]["id_source"]) == (None, None)


def test_normalize_real_classic_onchange_with_no_button_at_all():
    """REAL capture, 2026-07-30 — and the card had NO BUTTON.

    A selection widget is ITSELF an interaction trigger on the classic runtime:
    changing the dropdown produced this whole event, with the widget's own
    `onChangeAction.function` as the action identity and the changed value
    harvested into params. There is no add-ons equivalent — under add-ons an
    `onChangeAction` dies with `gsuiteaddons.googleapis.com/errors` code 13 —
    so this is NEW coverage, not parity coverage.

    Note `dedupe_key`: this capture came off the live subscription through the
    real `PubSubPuller`, which is what injects `_pubsub_message_id`, so the
    value is a real message id rather than a synthetic one. Carrying that field
    is NOT itself a provenance signal — `classic-added-to-space-event.json`
    carries one too, and `addon-buttonclicked-event.json` carries one despite
    having been pulled with an ad-hoc client. `classic-cardclicked-button-event.json`
    carries none, which is why its `dedupe_key` is None.
    """
    event = fixture("classic-cardclicked-onchange-event.json")

    # The card really had no button — otherwise this proves nothing. Scan EVERY
    # section, and the fixedFooter too: a Cards v2 button can sit in a footer
    # without ever appearing in a `buttonList`, so checking one section's
    # widgets would let the docstring's claim outrun the assertion.
    card = event["message"]["cardsV2"][0]["card"]
    assert "fixedFooter" not in card
    widgets = [w for section in card["sections"] for w in section["widgets"]]
    assert not any("buttonList" in w for w in widgets)
    selection = next(w["selectionInput"] for w in widgets if "selectionInput" in w)
    assert selection["onChangeAction"]["function"] == "onVerdictChanged"

    core = normalize_event(event)
    assert core["envelope_format"] == "classic"
    assert core["event_type"] == "CARD_CLICKED"
    assert core["action"] == {
        "id": "onVerdictChanged",
        "id_source": "google",
        "params": {"jobId": "onchange-001", "verdict": "approve"},
    }
    assert core["dedupe_key"] == "20759411966000501"


def test_detect_envelope_labels_the_real_classic_captures():
    for name in ("classic-cardclicked-button-event.json",
                 "classic-cardclicked-onchange-event.json",
                 "classic-added-to-space-event.json"):
        assert detect_envelope(fixture(name)) == "classic"


# --- the real CLASSIC ADDED_TO_SPACE capture (CG-9) ---------------------------


def test_normalize_real_classic_added_to_space():
    """REAL capture, 2026-07-30T00:24:51Z — the app added to a DM space.

    Whole-dict equality on purpose: the value of this fixture is the fields that
    are ABSENT. There is no `message` at all, so `_shape`'s empty-message arm
    runs for real — thread/message ids resolve to None and `text` to "" without
    a KeyError — and `action` stays None because the event is neither
    CARD_CLICKED nor carries an `action` object.

    A DM, not a ROOM. That is not a weaker case for this particular arm — a DM
    ADDED_TO_SPACE carries no message object at all — but the ROOM variant is
    genuinely uncovered; see tests/fixtures/README.md.
    """
    assert normalize_event(fixture("classic-added-to-space-event.json")) == {
        "event_type": "ADDED_TO_SPACE",
        "space": "spaces/_AAAAtestDm",
        "thread_key": None,
        "thread_name": None,
        "message_id": None,
        "sender_display": "Test User",
        "sender_email": "agent-user@example.com",
        "text": "",
        "action": None,
        "dedupe_key": "21339851456542226",
        "envelope_format": "classic",
    }


def test_classic_added_to_space_carries_the_capability_url_at_the_ROOT():
    """`CAPABILITY_FIELDS`' classic spelling was doc-derived until this capture.

    The placement is the fact worth pinning: Google puts
    `configCompleteRedirectUrl` at the TOP LEVEL of a classic event, not nested
    under a payload as the add-ons `...Uri` is. `redact_capability_urls`
    recurses, so either placement works — but a reader hunting for the field
    should not have to guess, and the CONSTRUCTED classic fixture guessed the
    root and turns out to have been right.

    The value here is `<SCRUBBED>`, so this proves the KEY match. That the
    redactor blanks a token-bearing VALUE is covered by
    `test_capability_url_is_redacted_in_both_spellings`.
    """
    raw = fixture("classic-added-to-space-event.json")
    assert "configCompleteRedirectUrl" in raw            # root, not nested
    redacted = redact_capability_urls(raw)
    assert redacted["configCompleteRedirectUrl"] == "<redacted-by-gateway>"
