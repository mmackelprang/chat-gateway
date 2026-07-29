"""Tier-2 inbound: Google Chat events via a Cloud Pub/Sub pull subscription.

Chat publishes app events (MESSAGE, ADDED_TO_SPACE, ...) to the topic from
the Google Cloud setup; this puller drains the subscription outbound-only —
no public endpoint, no reverse proxy, ever (the whole point of choosing
Pub/Sub for a homelab appserver).

Routing: event space → every registered app owning an identity homed in that
space (registry.apps_for_space). Unroutable events are audited under the
reserved app id "_unrouted" rather than dropped.

⚠ LIVE-UNVERIFIED: REST pull/acknowledge against the documented Pub/Sub v1
surface, written off-site. The FakePuller below is what the tests drive.
The 2026-07-29 live pull used an ad-hoc client, NOT PubSubPuller — this class
is still unexercised against Google.

⚠ SHAPE-VERIFIED 2026-07-29: the add-ons MESSAGE envelope is normalized against
a REAL captured payload replayed offline (tests/fixtures/addon-message-event.json).
Stronger than doc-derived, weaker than a live round-trip — the add-on
CARD_CLICKED path remains fully unverified (queue item CG-3).
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import threading
import time
from typing import Iterable, Protocol

import httpx

from ..envelope import InboundReply
from ..inbox import Inbox
from ..registry import Registry

PUBSUB_API = "https://pubsub.googleapis.com/v1"
PUBSUB_SCOPE = "https://www.googleapis.com/auth/pubsub"
UNROUTED = "_unrouted"
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
# exists classic-side — which makes assuming it a silent way to get
# action.id == "". Popped into action.id so the same card tapped under either
# runtime yields the same InboundReply.
ADDON_ACTION_KEY = "__action_method_name__"

# A per-message capability URL: visiting it erases the user's prompt, makes
# their private message PUBLIC in the space, and re-delivers it. Google spells
# it ...Uri in the add-ons envelope and ...Url in the classic one. Blanked from
# `raw` before anything is written to the audit trail or POSTed to a tenant
# callback (hard rule #2).
REDACTED = "<redacted-by-gateway>"
CAPABILITY_FIELDS = ("configCompleteRedirectUri", "configCompleteRedirectUrl")


class UnrecognizedEventError(ValueError):
    """The pulled bytes are not any Chat event envelope this gateway knows.

    Raised, never defaulted. Before 2026-07-29 an unparsed event silently
    normalized into a valid-looking empty MESSAGE — the exact class of silent
    failure hard rule #5 exists to prevent.
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
    """REST pull client (⚠ LIVE-UNVERIFIED — see module docstring)."""

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
            raise RuntimeError(f"pubsub {verb} HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json() if resp.text else {}

    def pull(self, max_messages: int = 10) -> list[tuple[str, dict]]:
        data = self._post("pull", {"maxMessages": max_messages})
        out = []
        for received in data.get("receivedMessages", []):
            msg = received.get("message", {})
            raw = msg.get("data", "")
            try:
                event = json.loads(base64.b64decode(raw).decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                event = {"_undecodable": True}
            if msg.get("messageId"):
                event["_pubsub_message_id"] = msg["messageId"]  # at-least-once dedupe key
            out.append((received.get("ackId", ""), event))
        return out

    def acknowledge(self, ack_ids: list[str]) -> None:
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
    forwarder.py / inbox.py / registry.py untouched."""
    thread = message.get("thread") or {}
    return {
        "event_type": event_type,
        "space": space,
        "thread_key": thread.get("threadKey") or None,
        "thread_name": thread.get("name") or None,
        "message_id": message.get("name") or None,
        "sender_display": sender.get("displayName", ""),
        "sender_email": sender.get("email"),
        "text": message.get("text", ""),
        "action": action,
        "dedupe_key": dedupe_key,
        "envelope_format": envelope_format,
    }


def _action_params(raw_params) -> dict:
    """Classic sends action.parameters as a LIST of {"key","value"}; the
    add-ons runtime sends commonEventObject.parameters as a flat string->string
    MAP. Accept either — the add-on interaction shape is documented but not yet
    capture-verified (CG-3)."""
    if isinstance(raw_params, dict):
        return dict(raw_params)
    params: dict = {}
    for p in raw_params or []:
        if isinstance(p, dict) and p.get("key"):
            params[p["key"]] = p.get("value")
    return params


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
            k: (REDACTED if k in CAPABILITY_FIELDS and isinstance(v, str)
                else redact_capability_urls(v))
            for k, v in event.items()
        }
    if isinstance(event, list):
        return [redact_capability_urls(v) for v in event]
    return event


def _normalize_classic(event: dict) -> dict:
    """Classic Chat app envelope: flat type/space/message/user."""
    message = event.get("message") or {}
    sender = event.get("user") or message.get("sender") or {}
    space = (event.get("space") or message.get("space") or {}).get("name", "")
    common = event.get("common") or {}
    action = None
    if event.get("type") == "CARD_CLICKED" or event.get("action"):
        act = event.get("action") or {}
        params = _action_params(act.get("parameters"))
        for k, v in _action_params(common.get("parameters")).items():
            params.setdefault(k, v)
        # CARD_CLICKED puts form values under common.formInputs, but
        # SUBMIT_FORM (app home) uses commonEventObject.formInputs — the
        # classic envelope is not internally uniform, so check both parents.
        _merge_form_inputs(common.get("formInputs"), params)
        _merge_form_inputs((event.get("commonEventObject") or {}).get("formInputs"), params)
        action = {
            "id": act.get("actionMethodName") or act.get("function")
                  or common.get("invokedFunction") or "",
            "params": params,
        }
    return _shape(envelope_format="classic", event_type=event["type"],
                  space=space, message=message, sender=sender, action=action,
                  dedupe_key=event.get("_pubsub_message_id") or None)


def _normalize_addon(event: dict) -> dict:
    """Google Workspace Add-ons envelope: commonEventObject + chat.<x>Payload.

    ⚠ The CARD_CLICKED path here is documentation-derived, NOT capture-
    verified — no card button has been tapped against this deployment. Kept
    deliberately tolerant until queue item CG-3 confirms it.
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
             or message.get("space") or {}).get("name", "")
    sender = chat.get("user") or message.get("sender") or {}

    params = _action_params(common.get("parameters"))
    action_id = params.pop(ADDON_ACTION_KEY, "")
    action = None
    if event_type == "CARD_CLICKED" or action_id or common.get("formInputs"):
        _merge_form_inputs(common.get("formInputs"), params)
        action = {
            "id": action_id
                  # invokedFunction was removed from this runtime in 2025-05;
                  # kept purely as a tolerant fallback until CG-3 confirms.
                  or common.get("invokedFunction")
                  or (payload.get("action") or {}).get("actionMethodName")
                  or "",
            "params": params,
        }
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


def _unparseable_core(event) -> dict:
    dedupe = event.get("_pubsub_message_id") if isinstance(event, dict) else None
    return _shape(envelope_format="unparseable", event_type=UNPARSEABLE,
                  space="", message={}, sender={}, action=None,
                  dedupe_key=dedupe or None)


def dispatch(event: dict, registry: Registry, inbox: Inbox,
             forwarder=None, reply_fn=None,
             now: dt.datetime | None = None,
             on_unparseable=None) -> list[str]:
    """Route one decoded Chat event. Per app: authorization allowlist check
    (jobhunt R4 — unauthorized users get an in-thread refusal and are never
    forwarded), then inbox + optional callback push (tenant opt-in).
    Returns the app ids that actually received the event.

    An event we cannot parse is audited under `_unrouted` as UNPARSEABLE and
    is NEVER attributed to a registered app: it has no space, so it cannot be
    routed, and a parse failure must not widen anyone's inbound surface
    (hard rule #6). `on_unparseable` lets the subscriber loop count it for
    /healthz without re-parsing.
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
        print(f"subscriber: UNPARSEABLE event, audited under {UNROUTED}: "
              f"{type(exc).__name__}: {exc}", flush=True)
        inbox.put(InboundReply(app=UNROUTED, received_at=now, raw=raw,
                               **_unparseable_core(event)))
        if on_unparseable is not None:
            on_unparseable(exc)
        return [UNROUTED]
    candidates = registry.apps_for_space(core["space"]) or [UNROUTED]
    delivered = []
    for app_id in candidates:
        reply = InboundReply(app=app_id, received_at=now, raw=raw, **core)
        app = registry.apps.get(app_id)
        if app is not None:
            if not app.allow_inbound:
                continue  # opted-out tenant: nothing crosses, ever (hard rule #6)
            sender = (core["sender_email"] or "").lower()
            if app.allowed_users and sender not in app.allowed_users:
                if reply_fn and core["space"]:
                    reply_fn(core["space"], core["thread_name"], NOT_AUTHORIZED_TEXT)
                continue
        inbox.put(reply)
        if app is not None and app.resolved_callback_url() and forwarder is not None:
            forwarder.enqueue(app, reply)
        delivered.append(app_id)
    return delivered


class SubscriberLoop:
    """Background pull loop. `last_poll_at` feeds healthz — honest liveness,
    not a hardcoded OK (the claude-mem pilot lesson, aiteam plan F18 gate 2)."""

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

    def _count_unparseable(self, exc: Exception) -> None:
        self.unparseable_seen += 1

    def poll_once(self) -> int:
        batch = self._puller.pull()
        acks = []
        for ack_id, event in batch:
            dispatch(event, self._registry, self._inbox,
                     forwarder=self.forwarder, reply_fn=self.reply_fn,
                     on_unparseable=self._count_unparseable)
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
                if self.forwarder is not None:
                    self.forwarder.process_due()
            except Exception as exc:  # noqa: BLE001 — the loop must survive
                print(f"subscriber: poll error (will retry): {exc}", flush=True)
            self._stop.wait(self._interval)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="pubsub-subscriber", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
