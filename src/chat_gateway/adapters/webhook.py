"""Tier-1 delivery: Google Chat incoming webhooks (one-way, named identity).

The webhook itself carries the identity (display name + avatar are fixed at
webhook creation in the Chat UI); this adapter only builds the message body
and posts it.

Threading: we send the app's thread_key both as the `threadKey` query
parameter and as `thread.threadKey` in the body, with
`messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD` — the documented
mechanisms for webhook thread affinity. ⚠ LIVE-UNVERIFIED: written off-site
without a real webhook; verify both mechanisms against a throwaway space on
first live use, and drop whichever is redundant.
"""

from __future__ import annotations

import httpx

from ..envelope import DeliveryResult, OutboundMessage
from ..registry import Identity


class WebhookDeliveryError(RuntimeError):
    pass


def build_payload(message: OutboundMessage) -> dict:
    payload: dict = {"text": message.text}
    if message.cards:
        payload["cardsV2"] = message.cards
    if message.thread_key:
        payload["thread"] = {"threadKey": message.thread_key}
    return payload


def build_params(message: OutboundMessage) -> dict:
    if not message.thread_key:
        return {}
    return {
        "threadKey": message.thread_key,
        "messageReplyOption": "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD",
    }


class WebhookAdapter:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=30)

    def send(self, identity: Identity, message: OutboundMessage) -> DeliveryResult:
        url = identity.webhook_url()  # resolved from env at send time, never logged
        # merge thread params into the URL's EXISTING query — the webhook URL
        # embeds key+token params that a plain `params=` would clobber
        target = httpx.URL(url)
        thread_params = build_params(message)
        if thread_params:
            target = target.copy_merge_params(thread_params)
        try:
            resp = self._client.post(target, json=build_payload(message))
        except httpx.HTTPError as exc:
            raise WebhookDeliveryError(f"webhook POST failed for {identity.name}: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            # never echo the URL (it embeds credentials) — name the identity instead
            raise WebhookDeliveryError(
                f"webhook for {identity.name} returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return DeliveryResult(
            status="delivered", channel=identity.channel, identity=identity.name,
            mode="webhook", thread_key=message.thread_key,
        )
