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


class Puller(Protocol):
    def pull(self, max_messages: int = 10) -> list[tuple[str, dict]]:
        """Return [(ack_id, decoded_chat_event), ...]."""
        ...

    def acknowledge(self, ack_ids: list[str]) -> None: ...


class FakePuller:
    """Test/dev double: preloaded events, records acks."""

    def __init__(self, events: Iterable[dict] = ()):
        self._events = [( f"ack-{i}", e) for i, e in enumerate(events)]
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
            raw = received.get("message", {}).get("data", "")
            try:
                event = json.loads(base64.b64decode(raw).decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                event = {"_undecodable": True}
            out.append((received.get("ackId", ""), event))
        return out

    def acknowledge(self, ack_ids: list[str]) -> None:
        if ack_ids:
            self._post("acknowledge", {"ackIds": ack_ids})


def normalize_event(event: dict) -> dict:
    """Extract the routable core of a Chat event; keep the raw for the app."""
    message = event.get("message") or {}
    thread = message.get("thread") or {}
    sender = message.get("sender") or {}
    space = (event.get("space") or message.get("space") or {}).get("name", "")
    return {
        "event_type": event.get("type", "MESSAGE"),
        "space": space,
        "thread_key": thread.get("threadKey") or None,
        "sender_display": sender.get("displayName", ""),
        "sender_email": sender.get("email"),
        "text": message.get("text", ""),
    }


def dispatch(event: dict, registry: Registry, inbox: Inbox,
             now: dt.datetime | None = None) -> list[str]:
    """Route one decoded Chat event into per-app inboxes. Returns app ids."""
    core = normalize_event(event)
    apps = registry.apps_for_space(core["space"]) or [UNROUTED]
    now = now or dt.datetime.now(dt.timezone.utc)
    for app_id in apps:
        inbox.put(InboundReply(app=app_id, received_at=now, raw=event, **core))
    return apps


class SubscriberLoop:
    """Background pull loop. `last_poll_at` feeds healthz — honest liveness,
    not a hardcoded OK (the claude-mem pilot lesson, aiteam plan F18 gate 2)."""

    def __init__(self, puller: Puller, registry: Registry, inbox: Inbox,
                 interval_seconds: float = 5.0):
        self._puller = puller
        self._registry = registry
        self._inbox = inbox
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_poll_at: dt.datetime | None = None
        self.events_seen = 0

    def poll_once(self) -> int:
        batch = self._puller.pull()
        acks = []
        for ack_id, event in batch:
            dispatch(event, self._registry, self._inbox)
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
