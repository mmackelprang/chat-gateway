"""jobhunt contract (R1/R3/R4/R6/R7): interaction forwarding, per-user
authorization, structured reasons, fail-loudly-in-thread, tenant opt-out."""

import datetime as dt

import httpx
import pytest

from chat_gateway.adapters.pubsub import (
    NOT_AUTHORIZED_TEXT, FakePuller, SubscriberLoop, dispatch,
)
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


# --- CG-12: suppression is counted, never recorded --------------------------
#
# The counters live on SubscriberLoop, so these drive the real loop rather than
# calling dispatch() directly: the wiring from the callback to the integer is
# part of what has to hold, and a test that passed its own lambda would prove
# the callback fires without proving anything reaches /healthz.


def _opted_out_registry(tmp_path, monkeypatch):
    """The aitrader shape: a space with a registered owner that will never
    serve it. `callback_url` is stripped because the registry refuses to load
    one on an `allow_inbound: false` app (hard rule #6, enforced at load)."""
    monkeypatch.setenv("T_KEY_JOBHUNT", "cgk_jh")
    quiet = JOBHUNT_YAML.replace("allow_inbound: true", "allow_inbound: false").replace(
        '    callback_url: "http://127.0.0.1:9999/chat-callback"\n', "")
    p = tmp_path / "quiet.yaml"
    p.write_text(quiet, encoding="utf-8")
    return load_registry(p)


def test_opted_out_space_is_counted_and_still_receives_nothing(tmp_path, monkeypatch):
    """CG-12: the one discard that used to leave NO trace at all.

    A space with registered owners never reaches the `or [UNROUTED]` fallback,
    and every owner here hits the opt-out `continue` — so before this counter
    the event vanished with no inbox entry, no `_unrouted` record and nothing at
    /healthz. Both halves are asserted: the discard is now visible, and it is
    still a discard (hard rule #6 is observation-only here — nothing crosses,
    and nothing about the event is written down either).
    """
    inbox = Inbox()
    reg = _opted_out_registry(tmp_path, monkeypatch)
    loop = SubscriberLoop(FakePuller([CARD_CLICK]), reg, inbox)

    assert loop.poll_once() == 1
    assert loop.suppressed_opt_out == 1
    assert loop.suppressed_not_authorized == 0, "an opt-out is not a refusal"
    assert loop.unparseable_seen == 0 and loop.dispatch_errors == 0
    # Nothing delivered and nothing audited — not to the tenant, not to
    # `_unrouted`. The counter is the ONLY new artifact.
    assert inbox.pending_counts() == {}


def test_refused_user_is_counted_separately_from_an_opted_out_tenant(registry):
    """The reasons are two different investigations, so they are two integers.

    `not_authorized` is a real human being turned away (jobhunt R4) — newly
    reachable in production now that `job-hunter` carries an `allowed_users`
    list, since any other member of that space who taps a card lands here. An
    operator seeing one merged number could not tell that from "events keep
    arriving in a space nobody serves".
    """
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    refusals = []
    fwd, _ = make_forwarder(lambda r: httpx.Response(200), clock)
    inbox = Inbox()
    event = {**CARD_CLICK, "user": {"displayName": "Eve", "email": "eve@example.com"}}
    loop = SubscriberLoop(FakePuller([event]), registry, inbox, forwarder=fwd,
                          reply_fn=lambda s, t, x: refusals.append((s, t, x)))

    assert loop.poll_once() == 1
    assert loop.suppressed_not_authorized == 1
    assert loop.suppressed_opt_out == 0, "a refusal is not an opt-out"
    # ...and every pre-existing guarantee of this branch is untouched: the user
    # is still told in-thread, and the event still goes nowhere.
    assert refusals == [("spaces/JH", "spaces/JH/threads/T1", NOT_AUTHORIZED_TEXT)]
    assert fwd.pending() == 0
    assert inbox.pending_counts() == {}


def test_a_raising_reply_fn_counts_a_dispatch_error_and_not_a_suppression(registry):
    """CALLBACK ORDER is load-bearing: `on_suppressed` fires AFTER `reply_fn`.

    Moving it two lines up — an obvious-looking "group the suppression handling
    together" cleanup — is invisible to every other test in this change, and it
    would count one fault for this app twice. The refusal never reached the
    thread, so a `suppressed_not_authorized` here would assert a human was told
    something they were not; `dispatch_errors` is the honest reading.
    """
    def boom(space, thread, text):
        raise RuntimeError("chat api unreachable")

    inbox = Inbox()
    event = {**CARD_CLICK, "user": {"displayName": "Eve", "email": "eve@example.com"}}
    loop = SubscriberLoop(FakePuller([event]), registry, inbox, reply_fn=boom)

    assert loop.poll_once() == 1
    assert loop.dispatch_errors == 1
    assert loop.suppressed_not_authorized == 0, "one fault, one counter for this app"
    assert loop.suppressed_opt_out == 0
    assert inbox.pending_counts() == {}


def test_an_authorized_delivery_touches_neither_suppression_counter(registry):
    """A counter must mean what it says or it is worse than nothing — the same
    argument as `test_resolved_action_id_does_not_touch_the_counter`. If the
    happy path incremented either of these, every deployment would show a
    permanent non-zero suppression count and an operator would learn to ignore
    both."""
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    fwd, _ = make_forwarder(lambda r: httpx.Response(200), clock)
    inbox = Inbox()
    loop = SubscriberLoop(FakePuller([CARD_CLICK]), registry, inbox, forwarder=fwd)

    assert loop.poll_once() == 1
    assert loop.suppressed_opt_out == 0
    assert loop.suppressed_not_authorized == 0
    assert len(inbox.poll("jobhunt")) == 1     # it really was a delivery


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
