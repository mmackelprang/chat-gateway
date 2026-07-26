"""Tier-2 delivery: the Google Chat API (two-way Chat app identity).

Sends `spaces.messages.create` as the gateway's Chat app, authenticated with
the service account from the Google Cloud setup (docs/google-cloud-setup.md).
Identity presentation at this tier: the app is one sender; per-agent flavor
rides in the message content (cards can carry per-PM headers) unless/until
per-identity apps are ever justified.

⚠ LIVE-UNVERIFIED end to end: written off-site with no Google Cloud project.
The token provider uses google-auth's standard service-account flow (scope
`chat.bot`); the request shape follows the documented REST surface. Exercise
against the real project before trusting — and keep this adapter the only
place Chat API calls exist.
"""

from __future__ import annotations

from typing import Callable, Protocol

import httpx

from ..envelope import DeliveryResult, OutboundMessage
from ..registry import Identity

CHAT_API = "https://chat.googleapis.com/v1"
CHAT_SCOPE = "https://www.googleapis.com/auth/chat.bot"

TokenProvider = Callable[[], str]


class ChatApiError(RuntimeError):
    pass


class GoogleServiceAccountTokens:
    """Standard google-auth service-account flow. Lazy imports so offline
    tests never need google-auth's transport dependencies."""

    def __init__(self, credentials_path: str, scope: str = CHAT_SCOPE):
        self._path = credentials_path
        self._scope = scope
        self._creds = None

    def __call__(self) -> str:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        if self._creds is None:
            self._creds = service_account.Credentials.from_service_account_file(
                self._path, scopes=[self._scope]
            )
        if not self._creds.valid:
            self._creds.refresh(Request())
        return self._creds.token


class ChatApiAdapter:
    def __init__(self, token_provider: TokenProvider, client: httpx.Client | None = None):
        self._tokens = token_provider
        self._client = client or httpx.Client(timeout=30)

    def send(self, identity: Identity, message: OutboundMessage) -> DeliveryResult:
        if not identity.space:
            raise ChatApiError(f"identity {identity.name!r} has no space set (required for mode: app)")
        body: dict = {"text": message.text}
        if message.cards:
            body["cardsV2"] = message.cards
        params = {}
        if message.thread_key:
            body["thread"] = {"threadKey": message.thread_key}
            params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
        try:
            resp = self._client.post(
                f"{CHAT_API}/{identity.space}/messages",
                json=body,
                params=params,
                headers={"Authorization": f"Bearer {self._tokens()}"},
            )
        except httpx.HTTPError as exc:
            raise ChatApiError(f"Chat API send failed for {identity.name}: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise ChatApiError(
                f"Chat API returned HTTP {resp.status_code} for {identity.name}: {resp.text[:200]}"
            )
        return DeliveryResult(
            status="delivered", channel=identity.channel, identity=identity.name,
            mode="app", thread_key=message.thread_key,
        )

    def send_text(self, space: str, thread_name: str | None, text: str) -> None:
        """Bare in-thread text (authorization refusals, R7 failure notices).
        Matches the forwarder's ReplyFn signature."""
        body: dict = {"text": text}
        params = {}
        if thread_name:
            body["thread"] = {"name": thread_name}
            params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
        resp = self._client.post(
            f"{CHAT_API}/{space}/messages", json=body, params=params,
            headers={"Authorization": f"Bearer {self._tokens()}"},
        )
        if resp.status_code != 200:
            raise ChatApiError(f"in-thread reply failed: HTTP {resp.status_code}")
