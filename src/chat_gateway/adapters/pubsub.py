"""Tier-2 inbound: Google Chat events via a Cloud Pub/Sub pull subscription.

Chat publishes app events (MESSAGE, ADDED_TO_SPACE, ...) to the topic from
the Google Cloud setup; this puller drains the subscription outbound-only —
no public endpoint, no reverse proxy, ever (the whole point of choosing
Pub/Sub for a homelab appserver).

Routing: event space → every registered app owning an identity homed in that
space (registry.apps_for_space). Unroutable events are audited under the
reserved app id "_unrouted" rather than dropped.

⚠ flag CLEARED 2026-07-30 for `PubSubPuller.pull()` and `.acknowledge()` —
both halves, driven against the live subscription through THIS class rather
than an ad-hoc client (which is what every earlier live pull used). See the
method docstrings for the evidence and for what is still NOT covered: the
non-200 branch (`PubSubError`), the undecodable-payload branches, and the
`SubscriberLoop` thread's long-run behaviour.

⚠ SHAPE-VERIFIED 2026-07-29: the add-ons MESSAGE envelope AND the add-ons
buttonClicked (CARD_CLICKED) envelope are both normalized against REAL captured
payloads replayed offline (tests/fixtures/addon-message-event.json,
tests/fixtures/addon-buttonclicked-event.json). Stronger than doc-derived,
weaker than a live round-trip: our normalizer has still never processed an
interaction live — both captures were pulled with an ad-hoc client, not
PubSubPuller.

The interaction capture found a DEFECT rather than confirming the mapping: the
card's routing pattern consumed Google's action-identity slot, so no identity
reached us (see ADDON_ACTION_KEY below). CG-10 FIXED that, and this same fixture
driven through normalize_event today yields action.id None and id_source None —
never "", which is precisely the ambiguity CG-10 removed. The finding stands;
the value it used to produce does not, and it is no longer open work.
Nothing about jobhunt R3/R4 is verified by it.

⚠ SHAPE-VERIFIED 2026-07-30: the CLASSIC envelope, for two event types —
CARD_CLICKED (both trigger kinds: a button tap and a selection widget's
onChangeAction, the latter from a card with no button at all) and
ADDED_TO_SPACE. Real captures from the live project `chat-gateway-gw`, replayed
offline (tests/fixtures/classic-cardclicked-button-event.json,
classic-cardclicked-onchange-event.json, classic-added-to-space-event.json).

Scope, because "the classic path is verified" would be too broad:
classic MESSAGE is still CONSTRUCTED (classic-message-event.json), and nothing
here touches classic `thread.threadKey`, the `commonEventObject.formInputs`
arm of _normalize_classic, APP_COMMAND / slash commands, REMOVED_FROM_SPACE or
WIDGET_UPDATED. Per hard rule #3 this accompanies ⚠ LIVE-UNVERIFIED and clears
nothing on its own.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import re
import threading
import time
from typing import Iterable, Protocol

import httpx

from ..envelope import CG_ACTION_KEY, CG_RESERVED_PREFIX, InboundReply
from ..errors import GatewayAuthoredError, describe_exception
from ..inbox import Inbox
# UNROUTED is imported, not defined here: core must own it (hard rule #3).
# Re-exported by this import so `from ...adapters.pubsub import UNROUTED`
# keeps resolving for the call sites that already do it.
from ..registry import UNROUTED, Registry

PUBSUB_API = "https://pubsub.googleapis.com/v1"
PUBSUB_SCOPE = "https://www.googleapis.com/auth/pubsub"
UNPARSEABLE = "UNPARSEABLE"

# chat.<key> -> normalized event_type. Google models these as a proto union
# ("payload can be only one of the following") with exactly these six members,
# and there is NO chat.type discriminator — the payload key IS the event type.
ADDON_PAYLOAD_TYPES = {
    "messagePayload": "MESSAGE",
    "buttonClickedPayload": "CARD_CLICKED",
    "addedToSpacePayload": "ADDED_TO_SPACE",
    "removedFromSpacePayload": "REMOVED_FROM_SPACE",
    "appCommandPayload": "APP_COMMAND",
    "widgetUpdatedPayload": "WIDGET_UPDATED",
}

# In the add-ons runtime Google passes the card's original action.function
# under this reserved parameter key. commonEventObject.invokedFunction was
# REMOVED from that runtime (add-ons release notes, 2025-05-12) but still
# exists classic-side.
#
# ⚠ CONDITIONAL, as of the real 2026-07-29 capture. That event carried NO
# __action_method_name__ — its button routed via
# action.function = "<a Pub/Sub topic path>", and the runtime sent nothing in
# this slot. So the "same card under either runtime yields the same
# InboundReply" property this key was added for holds only when the key is
# actually sent, which is not always. The fall-through is a silent "" — the
# defect queue item CG-10 exists to fix. Do not read this constant as a
# guarantee.
ADDON_ACTION_KEY = "__action_method_name__"

# --- gateway-reserved action identity (ADR-0001 D2, user-approved 2026-07-29) -
#
# Topic-as-function consumed Google's action-identity slot: under the add-ons
# runtime `action.function` is the interaction's DESTINATION (documented as an
# HTTPS URL), and a card click is not one of the four configurable triggers, so
# a card that wants to reach us must put the Pub/Sub topic path there. Google
# then sends no __action_method_name__, no invokedFunction and no
# payload.action — the identity has nowhere to ride. Either the gateway
# supplies a replacement slot or action.id is permanently dead THERE.
#
# THERE means ADD-ONS — not "the runtime we are actually deployed on", which is
# how this sentence read until CG-37. Production cut over to a CLASSIC Chat app
# on 2026-07-29 and classic supplies action.id natively, so everything above
# this line is add-ons history, not a description of what we run. The key stays
# regardless: `_resolve_action_id` checks it FIRST and unconditionally, so a
# card that carries it still resolves through it on either runtime. Not needed
# is not unused, and that sameness is D3's portability payoff (CLAUDE.md).
#
# HARD RULE #1 CHECK, because this is the subtlest thing in this module.
# Rule #1 forbids the gateway interpreting or owning an APPLICATION's schema.
# The gateway defines this key's NAME and never reads its VALUE: no branch, no
# enum of permitted ids, no validation that jobhunt sends "verdict". The value
# is relocated from params to action.id and forwarded verbatim. That is
# structurally identical to `thread_key` on the outbound side (a
# gateway-defined field whose value is opaque to us), and to Google's own
# __action_method_name__ — a reserved parameter key carrying action identity
# out-of-band. No tenant's vocabulary appears anywhere in this file.
#
# The `__cg_` prefix is RESERVED for gateway transport metadata; apps must not
# use it. Unknown `__cg_*` keys are passed THROUGH, not eaten: the gateway must
# not silently discard what it does not understand.
#
# The two constants are DEFINED in envelope.py and imported at the top of this
# module — core must not import from an adapter, and service.py has to publish
# the key name on /v1/identities. The import binds the names here too, so
# `from chat_gateway.adapters.pubsub import CG_ACTION_KEY` keeps working; same
# pattern as UNROUTED.

# A Pub/Sub topic resource path, e.g. projects/p/topics/t.
#
# This guard is not optional. Under the classic runtime the SAME portable card
# echoes its action.function straight back — and that value is the topic path,
# a routing artifact. Promoting it to action.id would hand a tenant
# `"projects/…/topics/…"` as an action name: a plausible-looking WRONG answer,
# which is strictly worse than an absent one. Applies to Google-native sources
# only; a value an app deliberately declared in __cg_action__ is the app's
# business, and reading it would be the rule #1 violation this design avoids.
TOPIC_PATH_RE = re.compile(r"^projects/[^/]+/topics/[^/]+$")

# A per-message capability URL: visiting it erases the user's prompt, makes
# their private message PUBLIC in the space, and re-delivers it.
# Google spells it ...Uri in the add-ons envelope and ...Url in the classic one.
# Both spellings are now first-hand: the add-ons one from the 2026-07-29
# message capture, the classic one from the 2026-07-30 ADDED_TO_SPACE capture,
# where it sits at the ROOT of the event rather than under a payload.
# Blanked from `raw` before anything is written to the audit trail or POSTed
# to a tenant callback (hard rule #2).
REDACTED = "<redacted-by-gateway>"
CAPABILITY_FIELDS = ("configCompleteRedirectUri", "configCompleteRedirectUrl")


# MARKED gateway-authored as of CG-33, having been excluded by CG-29 for a
# reason that no longer holds. The exclusion was never about this class — it was
# about `_post`, which passed `resp.reason_phrase` (the wire value) as the
# `reason` argument. With that replaced by a local-table lookup the message is
# verb + HTTP status + a phrase out of `httpx.codes`: structurally the same
# string `ChatApiError` and `WebhookDeliveryError` already carry the marker for.
#
# Symmetry is the weaker half of the argument. The load-bearing half is that
# `test_every_marked_message_interpolates_only_names_and_statuses` reads the
# construction sites of MARKED classes only — so while this one sat outside the
# set, the fix below rested on a single behavioural test, where its two siblings'
# identical CG-23 fix was ALSO machine-checked against the next edit. Marking it
# is what enrolls `_post`'s raise site in that guard.
class PubSubError(GatewayAuthoredError, RuntimeError):
    """A Pub/Sub REST call failed, carrying the HTTP status.

    Typed rather than a bare RuntimeError so SubscriberLoop can classify a
    failure without regexing an error message. It also stops echoing
    `resp.text[:200]`: a Google error body can quote the request, and the
    request path names the subscription — hard rule #2 says names, not values.
    The reason phrase is a fixed local string and carries nothing — but only
    because `_post` looks it up in `httpx.codes`. The obvious spelling,
    `resp.reason_phrase`, is NOT fixed: httpx returns the bytes off the HTTP/1.1
    status line whenever the server sends any. This docstring asserted the safe
    property while the code did the unsafe thing — landed with CG-7 on
    2026-07-29, corrected by CG-33 the next day. Read the raise site, not this
    line, if you are checking.

    The cost is honest: we lose Google's error prose. Status + phrase is what
    the loop can act on.

    `RuntimeError` stays second so `except RuntimeError` still catches this.
    """

    def __init__(self, verb: str, status_code: int, reason: str = ""):
        super().__init__(f"pubsub {verb} failed: HTTP {status_code} {reason}".rstrip())
        self.verb = verb
        self.status_code = status_code
        self.reason = reason


class UnrecognizedEventError(GatewayAuthoredError, ValueError):
    """The pulled bytes are not any Chat event envelope this gateway knows.

    Raised, never defaulted. Before 2026-07-29 an unparsed event silently
    normalized into a valid-looking empty MESSAGE — the exact class of silent
    failure hard rule #5 exists to prevent.

    Marked gateway-authored, which is only a formalisation: `dispatch` has
    printed this message in full since that fix, on the strength of the same
    property the marker now names — its raise sites interpolate field NAMES
    (top-level keys, `type(event).__name__`) and never a payload VALUE.
    `ValueError` stays second so `except ValueError` still catches this.
    """


class Puller(Protocol):
    def pull(self, max_messages: int = 10) -> list[tuple[str, dict]]:
        """Return [(ack_id, decoded_chat_event), ...]."""
        ...

    def acknowledge(self, ack_ids: list[str]) -> None: ...


class FakePuller:
    """Test/dev double: preloaded events, records acks."""

    def __init__(self, events: Iterable[dict] = ()):
        self._events = []
        for i, e in enumerate(events):
            e = dict(e)  # never mutate a caller's event
            e.setdefault("_pubsub_message_id", f"m-{i}")
            self._events.append((f"ack-{i}", e))
        self.acked: list[str] = []

    def pull(self, max_messages: int = 10) -> list[tuple[str, dict]]:
        batch, self._events = self._events[:max_messages], self._events[max_messages:]
        return batch

    def acknowledge(self, ack_ids: list[str]) -> None:
        self.acked.extend(ack_ids)


class PubSubPuller:
    """REST pull client. ⚠ flag CLEARED 2026-07-30 — see `pull` / `acknowledge`.

    Verification status is per method here, as in `chat_api.py`:

        pull()         verified live — real (ack_id, event) tuples
        acknowledge()  verified live — and SELECTIVELY, see below
        _post()        the non-200 branch is still UNVERIFIED
    """

    def __init__(self, subscription: str, token_provider, client: httpx.Client | None = None):
        self._sub = subscription.strip("/")
        self._tokens = token_provider
        self._client = client or httpx.Client(timeout=90)

    def _post(self, verb: str, body: dict) -> dict:
        resp = self._client.post(
            f"{PUBSUB_API}/{self._sub}:{verb}",
            json=body,
            headers={"Authorization": f"Bearer {self._tokens()}"},
        )
        if resp.status_code != 200:
            # The phrase comes off the LOCAL table, not `resp.reason_phrase` —
            # that property is the wire value (httpx returns
            # `extensions["reason_phrase"]`, which httpcore fills from the
            # HTTP/1.1 status line). See webhook.py's raise site for the full
            # note. This is the last of the three adapters to be brought onto
            # the local lookup; CG-23 did the other two and could not touch this
            # file — a concurrent Builder owned it — which is why the class
            # docstring above claimed a property this line did not have.
            reason = httpx.codes.get_reason_phrase(resp.status_code)
            raise PubSubError(verb, resp.status_code, reason)
        return resp.json() if resp.text else {}

    def pull(self, max_messages: int = 10) -> list[tuple[str, dict]]:
        """Drain up to `max_messages`, returning (ack_id, event) tuples.

        ⚠ flag CLEARED 2026-07-30. Driven against the live subscription through
        THIS class — every earlier live pull in this project used an ad-hoc
        client, which is exactly why the flag survived until now. Real
        `(ack_id, event)` tuples came back, ack ids were 196 characters, the
        `_pubsub_message_id` injection below happened on real messages, and the
        output was fed straight into `normalize_event` without adaptation.

        NOT covered: the `_undecodable` branches. Nothing on the live
        subscription was malformed, so both remain reasoned-about rather than
        observed.
        """
        data = self._post("pull", {"maxMessages": max_messages})
        out = []
        for received in data.get("receivedMessages", []):
            msg = received.get("message", {})
            raw = msg.get("data", "")
            try:
                event = json.loads(base64.b64decode(raw).decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                event = {"_undecodable": True}
            if not isinstance(event, dict):
                # Valid JSON, but not an event object. Same fate as bytes we
                # could not decode: UNPARSEABLE, counted, acked — never a
                # TypeError escaping pull() and stalling the whole batch.
                event = {"_undecodable": True}
            if msg.get("messageId"):
                event["_pubsub_message_id"] = msg["messageId"]  # at-least-once dedupe key
            out.append((received.get("ackId", ""), event))
        return out

    def acknowledge(self, ack_ids: list[str]) -> None:
        """Ack the given ids. Empty list is a no-op, deliberately.

        ⚠ flag CLEARED 2026-07-30, and on stronger evidence than a smoke test
        could give. Acking message id `20755182577634163` removed **only** that
        message, while two other unacked ids (`21328572002996378`,
        `21339851456542226`) kept redelivering across a 60-second poll.

        That distinction is the point. A batch ack followed by an empty
        subscription proves the subscription *drained* — it does not prove the
        RIGHT message was acked, and an ack that removed too much would look
        identical. Selective redelivery is what separates the two, and it is
        what makes at-least-once dedupe (`_pubsub_message_id` above) trustworthy
        rather than assumed.

        NOT covered: the non-200 branch in `_post` (see `PubSubError`), which is
        exercised only by `httpx.MockTransport` in the tests.
        """
        if ack_ids:
            self._post("acknowledge", {"ackIds": ack_ids})


def detect_envelope(event) -> str:
    """Structural detection -> 'addon' | 'classic'; raises otherwise.

    Order matters: the add-ons shape is the more specific one (a classic event
    has no 'chat' object). A flat dict carrying space/message but no 'type' is
    deliberately UNRECOGNIZED rather than assumed classic — that assumption is
    the bug this replaces.
    """
    if not isinstance(event, dict):
        raise UnrecognizedEventError(f"event is {type(event).__name__}, not an object")
    if event.get("_undecodable"):
        raise UnrecognizedEventError("message data could not be base64/JSON decoded")
    if isinstance(event.get("chat"), dict):
        return "addon"
    if isinstance(event.get("type"), str) and event["type"]:
        return "classic"
    # Field NAMES only, never values — payloads carry capability URLs (rule #2).
    raise UnrecognizedEventError(
        "unrecognized Chat envelope: no 'chat' object (Workspace Add-ons "
        "runtime) and no non-empty 'type' string (classic); top-level keys: "
        f"{sorted(k for k in event if not k.startswith('_'))[:10]}"
    )


def _derive_event_type(payload_key: str) -> str:
    """'widgetUpdatedPayload' -> 'WIDGET_UPDATED'.

    For payload types Google adds after this was written: named honestly from
    the wire, never defaulted to MESSAGE.
    """
    stem = payload_key[: -len("Payload")] if payload_key.endswith("Payload") else payload_key
    out: list[str] = []
    for ch in stem:
        if ch.isupper() and out:
            out.append("_")
        out.append(ch.upper())
    return "".join(out) or "UNKNOWN"


def _shape(*, envelope_format: str, event_type: str, space: str, message: dict,
           sender: dict, action: dict | None, dedupe_key: str | None) -> dict:
    """The ONE internal shape both formats normalize into. Keeping this
    identical to v0.1 (plus the additive envelope_format) is what leaves
    forwarder.py / inbox.py / registry.py untouched.

    `or ""` rather than a .get() default on the str-declared fields: a .get()
    default only fires when the key is ABSENT, so an explicit JSON null on the
    wire would sail through as None and make InboundReply(**core) raise. That
    raise is caught (the subscription still drains), but a caught event is an
    ACKED, DROPPED event — normalizing the null is strictly better than losing
    the message.
    """
    thread = message.get("thread") or {}
    return {
        "event_type": event_type,
        "space": space,
        "thread_key": thread.get("threadKey") or None,
        "thread_name": thread.get("name") or None,
        "message_id": message.get("name") or None,
        "sender_display": sender.get("displayName") or "",
        "sender_email": sender.get("email"),
        "text": message.get("text") or "",
        "action": action,
        "dedupe_key": dedupe_key,
        "envelope_format": envelope_format,
    }


def _action_params(raw_params) -> dict:
    """Classic sends action.parameters as a LIST of {"key","value"}; the
    add-ons runtime sends commonEventObject.parameters as a flat string->string
    MAP. Accept either. The map form is capture-confirmed (2026-07-29); the
    list branch is still doc-derived FROM THE ADD-ONS RUNTIME, which has never
    sent it — but it is capture-confirmed on the CLASSIC side as of 2026-07-30
    (tests/fixtures/classic-cardclicked-button-event.json carries
    action.parameters == [{"key": "jobId", "value": "mig-001"}])."""
    if isinstance(raw_params, dict):
        return dict(raw_params)
    params: dict = {}
    for p in raw_params or []:
        if isinstance(p, dict) and p.get("key"):
            params[p["key"]] = p.get("value")
    return params


def _resolve_action_id(params: dict, *native) -> tuple[str | None, str | None]:
    """Where a card interaction's action identity comes from (ADR-0001 D2).

    Order, highest first:

      1. ``params["__cg_action__"]`` — app-declared, authoritative when present.
         POPPED, exactly as ``__action_method_name__`` is, so a tenant never
         sees gateway transport plumbing mixed in with its own parameters.
      2. Google-native sources, in the order the caller passes them —
         ``__action_method_name__``, ``action.actionMethodName`` /
         ``action.function``, ``commonEventObject.invokedFunction``. A value
         that is a Pub/Sub topic path is DISCARDED here (see TOPIC_PATH_RE):
         it is a routing artifact, not an identity.
      3. ``None`` — semantically ABSENT.

    Never ``""``. A tenant receiving an empty string cannot distinguish "no
    action" from "an action named empty string", and that ambiguity IS the
    defect this function exists to remove — the silent-failure class CG-1
    eliminated one layer further out.

    Returns ``(id, id_source)``. ``id_source`` is transport metadata in the
    same spirit as ``envelope_format``, and its real value is as a DETECTOR:
    if Google ever starts populating ``__action_method_name__`` under the
    topic-as-function pattern, ``id_source`` flips from ``"cg_param"`` to
    ``"google"`` and we learn the runtime changed under us BEFORE it breaks
    something. That converts a silent behaviour change into an observable.
    """
    declared = params.pop(CG_ACTION_KEY, None)
    if isinstance(declared, str) and declared:
        return declared, "cg_param"
    for value in native:
        if isinstance(value, str) and value and not TOPIC_PATH_RE.match(value):
            return value, "google"
    return None, None


def _merge_form_inputs(container, params: dict) -> None:
    """formInputs nests identically in both runtimes —
    {name: {stringInputs: {value: [...]}}} — only the parent differs.
    (The extra [""] level in Google's samples is Apps Script only; over
    Pub/Sub the flat form is what arrives.)"""
    for name, spec in (container or {}).items():
        values = ((spec or {}).get("stringInputs") or {}).get("value") or []
        params.setdefault(name, values[0] if len(values) == 1 else values)


def redact_capability_urls(event):
    """Return a deep copy of `event` with capability URLs blanked.

    `raw` is written to the JSONL audit trail and POSTed whole to tenant
    callbacks, so an unredacted configCompleteRedirect* would hand every
    opted-in tenant the ability to make a user's private message public.

    Rule #1 check: this matches Google-owned field NAMES exactly — never
    anything an application placed in the payload — so no app-domain
    knowledge enters the gateway.
    """
    if isinstance(event, dict):
        return {
            # Key match alone decides — NOT the value's type. If the field ever
            # arrives wrapped in an object or list, recursing into it would
            # preserve the URL inside; blanking the whole node cannot.
            k: (REDACTED if k in CAPABILITY_FIELDS else redact_capability_urls(v))
            for k, v in event.items()
        }
    if isinstance(event, list):
        return [redact_capability_urls(v) for v in event]
    return event


def _normalize_classic(event: dict) -> dict:
    """Classic Chat app envelope: flat type/space/message/user."""
    message = event.get("message") or {}
    sender = event.get("user") or message.get("sender") or {}
    space = (event.get("space") or message.get("space") or {}).get("name") or ""
    common = event.get("common") or {}
    action = None
    if event.get("type") == "CARD_CLICKED" or event.get("action"):
        act = event.get("action") or {}
        params = _action_params(act.get("parameters"))
        for k, v in _action_params(common.get("parameters")).items():
            params.setdefault(k, v)
        # Reserved add-ons key; popped here too so the two formats round-trip
        # to identical params if a classic event ever carries it (spec §4.5).
        # It is now also USED as a native candidate rather than merely
        # discarded — ADR-0001 D2 lists one native order for both runtimes.
        native_key = params.pop(ADDON_ACTION_KEY, None)
        # CARD_CLICKED puts form values under common.formInputs, but
        # SUBMIT_FORM (app home) uses commonEventObject.formInputs — the
        # classic envelope is not internally uniform, so check both parents.
        _merge_form_inputs(common.get("formInputs"), params)
        _merge_form_inputs((event.get("commonEventObject") or {}).get("formInputs"), params)
        # act.function is the classic runtime's echo of a portable card's
        # routing target, so TOPIC_PATH_RE earns its keep on THIS branch in
        # particular — see _resolve_action_id.
        action_id, id_source = _resolve_action_id(
            params, native_key, act.get("actionMethodName"), act.get("function"),
            common.get("invokedFunction"))
        action = {"id": action_id, "id_source": id_source, "params": params}
    return _shape(envelope_format="classic", event_type=event["type"],
                  space=space, message=message, sender=sender, action=action,
                  dedupe_key=event.get("_pubsub_message_id") or None)


def _normalize_addon(event: dict) -> dict:
    """Google Workspace Add-ons envelope: commonEventObject + chat.<x>Payload.

    ⚠ The CARD_CLICKED path is now SHAPE-VERIFIED against a real 2026-07-29
    capture — and that capture showed the action-id extraction below FAILING to
    an empty string (queue item CG-10). Kept deliberately tolerant until CG-10
    decides where action identity should live.
    """
    chat = event.get("chat") or {}
    common = event.get("commonEventObject") or {}
    # Prefer a known payload key (stable order); else take any *Payload
    # deterministically, so a type Google adds later still routes.
    payload_key = next((k for k in ADDON_PAYLOAD_TYPES if isinstance(chat.get(k), dict)), None)
    if payload_key is None:
        payload_key = next((k for k in sorted(chat)
                            if k.endswith("Payload") and isinstance(chat[k], dict)), None)
    if payload_key is None:
        raise UnrecognizedEventError(
            "add-ons envelope carries no '*Payload' object under 'chat' "
            f"(keys: {sorted(chat)[:10]}) — nothing to route on"
        )
    payload = chat[payload_key]
    event_type = ADDON_PAYLOAD_TYPES.get(payload_key) or _derive_event_type(payload_key)
    message = payload.get("message") or {}
    # widgetUpdatedPayload carries ONLY space, and chat.space is a documented
    # non-payload sibling — three sources, and never assume message exists.
    space = (payload.get("space") or chat.get("space")
             or message.get("space") or {}).get("name") or ""
    sender = chat.get("user") or message.get("sender") or {}

    params = _action_params(common.get("parameters"))
    native_key = params.pop(ADDON_ACTION_KEY, None)
    action = None
    if (event_type == "CARD_CLICKED" or native_key or CG_ACTION_KEY in params
            or common.get("formInputs")):
        _merge_form_inputs(common.get("formInputs"), params)
        # invokedFunction was REMOVED from this runtime in 2025-05 and the real
        # 2026-07-29 capture carried none of these three; kept as tolerant
        # fallbacks so a card style we have not seen still resolves natively.
        #
        # Order is ADR-0001 D2's, and it is deliberately the SAME as the classic
        # branch's: __action_method_name__, then the action object's own name,
        # then invokedFunction last. The pre-CG-10 code had the last two
        # reversed; that only ever mattered for a shape we have not seen, which
        # is exactly the shape a tolerant fallback exists for.
        action_id, id_source = _resolve_action_id(
            params, native_key, (payload.get("action") or {}).get("actionMethodName"),
            common.get("invokedFunction"))
        action = {"id": action_id, "id_source": id_source, "params": params}
    return _shape(envelope_format="addon", event_type=event_type, space=space,
                  message=message, sender=sender, action=action,
                  dedupe_key=event.get("_pubsub_message_id") or None)


def normalize_event(event: dict) -> dict:
    """Extract the routable core of a Chat event; the raw rides along.

    Supports BOTH Google runtimes, because both will coexist for years while
    Google migrates and different consumers may sit behind different ones:

      * Workspace Add-ons  — commonEventObject + chat.<x>Payload
      * Classic Chat app   — flat type / space / message / user

    Normalizing a transport envelope is transport's job (hard rule #1 forbids
    owning an APPLICATION's schema, not recognizing Google's wire formats).

    Raises UnrecognizedEventError on anything else — never a silent MESSAGE.
    """
    if detect_envelope(event) == "addon":
        return _normalize_addon(event)
    return _normalize_classic(event)


NOT_AUTHORIZED_TEXT = "⛔ Not authorized for this action."

# CG-12. The `reason` values `dispatch` passes to `on_suppressed`, named so a
# raw string literal added later is visibly out of place.
REASON_OPT_OUT = "opt_out"
REASON_NOT_AUTHORIZED = "not_authorized"
# THE WHOLE SET. Adding a member means adding a counter in
# `SubscriberLoop._count_suppressed`; nothing else counts it and the miss is
# silent at runtime, so `test_every_suppression_reason_reaches_a_counter`
# iterates this tuple and fails the moment one arrives without a counter.
SUPPRESSION_REASONS = (REASON_OPT_OUT, REASON_NOT_AUTHORIZED)


def _unparseable_core(event) -> dict:
    dedupe = event.get("_pubsub_message_id") if isinstance(event, dict) else None
    return _shape(envelope_format="unparseable", event_type=UNPARSEABLE,
                  space="", message={}, sender={}, action=None,
                  dedupe_key=dedupe or None)


def dispatch(event: dict, registry: Registry, inbox: Inbox,
             forwarder=None, reply_fn=None,
             now: dt.datetime | None = None,
             on_unparseable=None, on_missing_action_id=None,
             on_suppressed=None) -> list[str]:
    """Route one decoded Chat event. Per app: authorization allowlist check
    (jobhunt R4 — unauthorized users get an in-thread refusal and are never
    forwarded), then inbox + optional callback push (tenant opt-in).
    Returns the app ids that actually received the event.

    An event we cannot parse is audited under `_unrouted` as UNPARSEABLE and
    is NEVER attributed to a registered app: it has no space, so it cannot be
    routed, and a parse failure must not widen anyone's inbound surface
    (hard rule #6). `on_unparseable` lets the subscriber loop count it for
    /healthz without re-parsing.

    `on_suppressed(app_id, reason)` fires once per CANDIDATE APP that declines
    the event — `allow_inbound: false`, or a sender not on that app's
    `allowed_users` — independently of what the other candidates did. An
    opted-out owner fires it even when a co-owner of the same space RECEIVES
    that same event, so it reports declining APPS, never lost events. A
    declining app gets no inbox entry and no `_unrouted` record, because
    writing one would start persisting the traffic of a tenant that opted out
    of everything (CG-12 option B, rejected); the callback lets the subscriber
    loop count it for /healthz without anything about the event being retained.
    `reason` is one of SUPPRESSION_REASONS.

    The callback runs INSIDE the candidate loop, so it must not raise: an
    exception aborts delivery to LATER candidates. That fails closed — it can
    only narrow inbound, never widen it, so hard rule #6 is not at risk — but
    it silently costs a co-owner its copy.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    # Non-dict events (a bare list, a string) redact to themselves, and
    # InboundReply(raw=<non-dict>) would then raise INSIDE the except handler —
    # escaping dispatch and poll_once, which is the exact poison-pill wedge
    # this whole path exists to prevent. `{}` keeps dispatch total.
    raw = redact_capability_urls(event) if isinstance(event, dict) else {}
    try:
        core = normalize_event(event)
    except Exception as exc:  # noqa: BLE001
        # Deliberately broad. A malformed event must never wedge the
        # subscription in a poison-pill redelivery loop (the caller still
        # acks), and must never be silent either: audited under _unrouted,
        # counted for /healthz, and printed. Three signals, permanently.
        # Our own error prints field NAMES only, so its message is safe to
        # echo. `except Exception` is broader than that by design, and another
        # exception's message could carry a payload VALUE — a capability URL,
        # a user's text — so anything else is named by type alone (rule #2).
        # That rule used to be an `isinstance(exc, UnrecognizedEventError)`
        # ternary written out here; it is `describe_exception` now, because the
        # second copy of it (in poll_once) is what CG-29 was filed against.
        print(f"subscriber: UNPARSEABLE event, audited under {UNROUTED}: "
              f"{describe_exception(exc)}", flush=True)
        inbox.put(InboundReply(app=UNROUTED, received_at=now, raw=raw,
                               **_unparseable_core(event)))
        if on_unparseable is not None:
            on_unparseable(exc)
        return [UNROUTED]
    if core["action"] is not None and core["action"]["id"] is None:
        # ADR-0001 D4. The event is still FORWARDED: rule #6 says forward whole
        # and let the tenant enforce, so a parse-quality problem must not become
        # a silent drop. What changes is that the tenant can now reject
        # explicitly instead of guessing, and that /healthz can see it.
        #
        # This is also the detector for topic-as-function breaking. If Google
        # withdraws that undocumented routing the likely observable is nothing
        # at all on our side; a rising count here is one of the few signals that
        # something changed under us (ADR-0001 §8).
        print(f"subscriber: interaction with NO resolvable action identity "
              f"({core['event_type']}, {core['envelope_format']} envelope) — "
              "forwarded with action.id=null; producer should set "
              f"{CG_ACTION_KEY!r}", flush=True)
        if on_missing_action_id is not None:
            on_missing_action_id(core)
    candidates = registry.apps_for_space(core["space"]) or [UNROUTED]
    delivered = []
    for app_id in candidates:
        reply = InboundReply(app=app_id, received_at=now, raw=raw, **core)
        app = registry.apps.get(app_id)
        if app is not None:
            if not app.allow_inbound:
                # COUNTED, never recorded (CG-12). This fires for THIS app
                # declining; a co-owner of the same space can still receive the
                # event two iterations down. The gap CG-12 was filed for is the
                # case where every owner opts out: the `or [UNROUTED]` fallback
                # above never fires — the space HAS owners — so an
                # aitrader-shaped registry discarded every event in its space
                # with nothing written to the inbox, nothing under `_unrouted`
                # and nothing at /healthz, which is the silent discard hard
                # rule #5 exists to make impossible.
                if on_suppressed is not None:
                    on_suppressed(app_id, REASON_OPT_OUT)
                continue  # opted-out tenant: nothing crosses, ever (hard rule #6)
            sender = (core["sender_email"] or "").lower()
            if app.allowed_users and sender not in app.allowed_users:
                if reply_fn and core["space"]:
                    reply_fn(core["space"], core["thread_name"], NOT_AUTHORIZED_TEXT)
                # AFTER the refusal, deliberately: if reply_fn raises, the loop
                # counts a dispatch_error and this suppression is not also
                # counted — one fault, one counter FOR THIS APP. Not for the
                # event: the raise aborts the candidate loop, so an earlier
                # candidate already counted keeps its increment, and one event
                # can leave both `suppressed_opt_out: 1` and
                # `dispatch_errors: 1`. A refused human is a different fact from
                # an opted-out tenant (jobhunt R4 turning somebody away, versus
                # rule #6 working as designed), so the loop keeps them in
                # separate integers.
                if on_suppressed is not None:
                    on_suppressed(app_id, REASON_NOT_AUTHORIZED)
                continue
        inbox.put(reply)
        if app is not None and app.resolved_callback_url() and forwarder is not None:
            forwarder.enqueue(app, reply)
        delivered.append(app_id)
    return delivered


class SubscriberLoop:
    """Background pull loop. `last_poll_at` feeds healthz — honest liveness,
    not a hardcoded OK (the claude-mem pilot lesson, aiteam plan F18 gate 2).

    As of CG-7 the failure counters below feed it too: they are what /healthz
    computes `status` FROM, so a loop whose every poll has failed can no longer
    be reported green. Reporting a counter nobody reads is how the endpoint
    stayed dishonest while looking honest."""

    def __init__(self, puller: Puller, registry: Registry, inbox: Inbox,
                 interval_seconds: float = 5.0, forwarder=None, reply_fn=None):
        self._puller = puller
        self._registry = registry
        self._inbox = inbox
        self._interval = interval_seconds
        self.forwarder = forwarder
        self.reply_fn = reply_fn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_poll_at: dt.datetime | None = None
        self.events_seen = 0
        self.unparseable_seen = 0   # honest health: silent discards must show
        # Separate on purpose: "parsed fine, delivery blew up" is a different
        # hunt from "could not parse". Folding them together would send an
        # operator looking for malformed events that do not exist (rule #5).
        self.dispatch_errors = 0
        # ADR-0001 D4. An interaction that parsed fine but carried no
        # resolvable action identity. Distinct from unparseable_seen (the event
        # is valid and its params are usable) and from dispatch_errors (nothing
        # failed). A non-zero value means some producer's cards are missing
        # `__cg_action__` — or that Google changed the runtime underneath us.
        self.interactions_without_action_id = 0
        # CG-12. Two BARE integers: no space, no app id, no content, no
        # timestamp, no dedupe key. Three things a reader has to know before
        # touching either.
        #
        # 1. EACH COUNTS CANDIDATE APPS THAT DECLINED AN EVENT — not events that
        #    went nowhere. `on_suppressed` fires per candidate, independently of
        #    the others, so an opted-out owner increments this even when a
        #    co-owner of the same space RECEIVED that same event, and one event
        #    with two opted-out owners increments by two. Read either as an
        #    event count and you will both overstate inbound volume and go
        #    hunting for a delivered event you think was lost; `events_seen` is
        #    the event count. The gap CG-12 was filed for — a space where EVERY
        #    owner opted out, so the `or [UNROUTED]` fallback never fires and the
        #    discard leaves no inbox entry, no `_unrouted` record and nothing
        #    here — is one CASE of this, not its definition.
        # 2. NO APP ID — and NOT because app ids are secret. They are not:
        #    `registry.health()` has published them since v0.1 and
        #    `inbox.pending` publishes observed inbound volume keyed by app id,
        #    both on this same unauthenticated endpoint (service.py, "Names,
        #    never values"). The operative principle is narrower: no
        #    observed-traffic attribution for a tenant that opted OUT. Those two
        #    only ever name apps that opted IN (plus `_unrouted`), so naming one
        #    here discloses what neither does — which is what sank the rejected
        #    alternatives (a full `_unrouted` audit record; a metadata-only
        #    record carrying space + event type) and would sink a future
        #    `last_suppressed_app` or per-space breakdown. Accepted with eyes
        #    open: with exactly ONE opted-out tenant registered — today's
        #    deployment — this is a de-facto unauthenticated activity meter for
        #    that tenant BY INFERENCE, though no field names it. Taken as
        #    VOLUME-only and marginal: `events_seen` already publishes total
        #    inbound volume here. That "exactly ONE" is what CG-61's decision D1
        #    ends — but NOT YET: a PR cannot edit the gitignored live registry,
        #    which still granted `aiteam-harness` inbound when this was written
        #    (2026-07-31). Once it carries D1, a second tenant is opted out and
        #    this integer POOLS their traffic instead of decomposing to one —
        #    PARTIAL mitigation, and not a reason to skip the /healthz ACL
        #    (production-readiness arc spec §7 D2). CLAUDE.md's CG-12 bullet
        #    carries the same "not yet" and expires on the same operator edit;
        #    whoever makes it owns both.
        # 3. THE TWO REASONS ARE DISTINCT PHENOMENA, which is why this is two
        #    counters and not one. `opt_out` is hard rule #6 working exactly as
        #    designed — an app installed in a space it will never serve.
        #    `not_authorized` is a real human being refused (jobhunt R4):
        #    somebody tapped a card and got ⛔ in the thread. Merged, an operator
        #    could not tell "five hundred people were refused" from "five hundred
        #    events landed in a space nobody serves" — completely different
        #    investigations. Watch `suppressed_opt_out` in particular: a refusal
        #    announces itself to the affected human in-thread (wherever a tier-2
        #    reply path is configured), so a misconfigured `allowed_users` is
        #    self-revealing, while an opt-out has no signal anywhere but this
        #    integer — the person who tapped gets silence.
        self.suppressed_opt_out = 0
        self.suppressed_not_authorized = 0
        # Poll-level failure tracking. poll_once() raising means the
        # SUBSCRIPTION is unreachable — a revoked key, a deleted subscription, a
        # wrong CHAT_GATEWAY_PUBSUB_SUBSCRIPTION, or free-tier quota exhaustion.
        # All four look identical from in here and all four fail CLOSED: inbound
        # simply stops. Before this existed, healthz reported "ok" throughout
        # (hard rule #5, the failure it was written after).
        self.poll_failures = 0
        self.consecutive_poll_failures = 0
        # "<ExceptionType> HTTP <status>" — a TYPE and a STATUS, never a message
        # body (rule #2). Cleared on the first success so recovery is visible.
        self.last_poll_error: str | None = None
        # Was start() ever called? Distinct from "is the thread alive", and the
        # distinction is what makes the two health reasons unambiguous: a loop
        # that was never started has never polled either (already a reason),
        # whereas a loop that WAS started and is now dead is a different and
        # much more alarming fact. Without this flag /healthz could not tell
        # them apart, and every offline test — none of which starts a thread —
        # would look like a corpse.
        self._started = False

    @property
    def interval_seconds(self) -> float:
        """The configured poll interval, readable by /healthz.

        Public because staleness is only judgeable relative to how often this
        loop is *supposed* to poll; `service.py` must not guess it or hardcode
        a copy that drifts.
        """
        return self._interval

    @property
    def started(self) -> bool:
        """Was `start()` ever called? NOT cleared by `stop()` — see below."""
        return self._started

    def is_alive(self) -> bool:
        """Is the polling thread actually running right now?

        The DIRECT liveness signal, and the one hard rule #5 names explicitly
        ("monitor/subscriber liveness"). Every other subscriber field is
        inferential: counters tell you what happened when a poll last ran, not
        whether any poll will ever run again. A daemon thread that has died —
        `_run` catches `Exception`, so a `BaseException` such as `MemoryError`
        escaping, or an interpreter-shutdown race, kills it silently — leaves
        every counter frozen at a plausible value and `last_poll_at` fixed at a
        real timestamp. That reads as perfect health forever, which is the exact
        11-day-silent-failure shape rule #5 was written after.

        Read TOGETHER with `started`, never alone: alone it cannot tell a loop
        that was never started from one that was started and died, and those are
        very different facts. `/healthz` only complains about the second.
        """
        return self._thread is not None and self._thread.is_alive()

    def _count_unparseable(self, exc: Exception) -> None:
        self.unparseable_seen += 1

    def _count_missing_action_id(self, core: dict) -> None:
        # Counts only. The core is passed for future signal, never stored —
        # it carries the user's text and their space (hard rule #2).
        self.interactions_without_action_id += 1

    def _count_suppressed(self, app_id: str, reason: str) -> None:
        # Counts only. NEITHER argument is stored anywhere: `app_id` would
        # attribute observed traffic to an opted-out tenant on an
        # unauthenticated endpoint (point 2 above), and `reason` only selects
        # which integer moves.
        #
        # No `else`, deliberately. Raising would abort dispatch's candidate loop
        # mid-way on a code-defect path, and a default bucket would corrupt the
        # very distinction point 3 exists to preserve — so an unrecognized
        # reason is dropped silently HERE, and caught instead by the test that
        # iterates SUPPRESSION_REASONS.
        if reason == REASON_OPT_OUT:
            self.suppressed_opt_out += 1
        elif reason == REASON_NOT_AUTHORIZED:
            self.suppressed_not_authorized += 1

    def poll_once(self) -> int:
        batch = self._puller.pull()
        acks = []
        for ack_id, event in batch:
            try:
                dispatch(event, self._registry, self._inbox,
                         forwarder=self.forwarder, reply_fn=self.reply_fn,
                         on_unparseable=self._count_unparseable,
                         on_missing_action_id=self._count_missing_action_id,
                         on_suppressed=self._count_suppressed)
            except Exception as exc:  # noqa: BLE001
                # Parsing is not the only thing that can fail: reply_fn talks
                # to Google, inbox/delivery-log writes touch disk, and pydantic
                # validates. Any of those escaping would leave the whole batch
                # un-acked and wedge the subscription in a redelivery loop —
                # the outage this module exists to prevent. Count it, name it,
                # ack it, keep going.
                #
                # TYPE NAME ONLY for anything foreign: a pydantic
                # ValidationError embeds the offending input value in its
                # message, and these events carry capability URLs (hard rule
                # #2 — names, never values). CG-29: it used to be type-name
                # only for EVERYTHING, which threw away the distinction CG-25
                # had just created one layer down — `reply_fn` is
                # `ChatApiAdapter.send_text` in production, and after CG-25 a
                # transport failure and a non-200 both arrive here as
                # `ChatApiError`, distinguishable only by the message this line
                # was discarding. `describe_exception` prints it for the marked
                # types and nothing but the type name for the rest.
                self.dispatch_errors += 1
                print(f"subscriber: dispatch failed, event acked and dropped: "
                      f"{describe_exception(exc)}", flush=True)
            self.events_seen += 1
            if ack_id:
                acks.append(ack_id)
        self._puller.acknowledge(acks)
        self.last_poll_at = dt.datetime.now(dt.timezone.utc)
        return len(batch)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
                self.consecutive_poll_failures = 0
                self.last_poll_error = None
                if self.forwarder is not None:
                    self.forwarder.process_due()
            except Exception as exc:  # noqa: BLE001 — the loop must survive
                self.poll_failures += 1
                self.consecutive_poll_failures += 1
                self.last_poll_error = (
                    f"{type(exc).__name__} HTTP {exc.status_code}"
                    if isinstance(exc, PubSubError) else type(exc).__name__
                )
                # NOT `describe_exception`, on purpose — do not "unify" this
                # with the two sites above (CG-29). ONE reason, and it is
                # sufficient on its own: this string is `/healthz`'s
                # `last_poll_error`, `/healthz` is UNAUTHENTICATED, and its
                # audience is not the console's — so the field format is a
                # published surface rather than a log line, pinned as an exact
                # string in `test_adapters.py` and `test_service.py`.
                #
                # CG-29 gave a second reason and CG-33 removed it. That reason
                # was "`PubSubError` is unmarked, so describe_exception would
                # drop the HTTP status"; `PubSubError` is marked now, and the
                # helper would render it in full — `PubSubError: pubsub pull
                # failed: HTTP 403 Forbidden`, status included. Do not go
                # looking for the argument that is no longer here.
                #
                # Type + status only. The previous version printed the exception
                # message, which for a Pub/Sub failure embedded resp.text[:200].
                print(f"subscriber: poll error (will retry): {self.last_poll_error}",
                      flush=True)
            self._stop.wait(self._interval)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="pubsub-subscriber", daemon=True)
        self._started = True
        self._thread.start()

    def stop(self) -> None:
        # `_started` is deliberately NOT cleared here. It would be tempting —
        # "an intentional stop is not a failure" — but it would make /healthz lie
        # in the one case that matters: a subscriber that is still enabled in
        # configuration and is no longer polling. Whether that happened by
        # accident or on purpose does not change the fact that inbound is dead,
        # and during a real shutdown nobody is reading /healthz anyway. Reporting
        # it is the honest choice (hard rule #5).
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
