"""Tier-2 delivery: the Google Chat API (two-way Chat app identity).

Sends `spaces.messages.create` as the gateway's Chat app, authenticated with
the service account from the Google Cloud setup (docs/google-cloud-setup.md).

Identity at this tier: the app is ONE sender, and a real one — verified live
2026-07-29, the response carried
`sender: {"displayName": "Agent Comms", "type": "BOT"}`. That is the trade-off
against tier 1, which gives as many named identities as you create webhooks and
no sender object at all. Per-agent flavour therefore rides in the message
content (cards can carry per-PM headers) unless per-identity apps are ever
justified.

⚠ Verification status is PER METHOD here, not per module — the halves of this
file have different evidence behind them. Read each docstring; do not
generalize from one to another. Keep this adapter the only place Chat API calls
exist (hard rule #3).

Summary as of 2026-07-30, against project `chat-gateway-gw`:

    GoogleServiceAccountTokens   verified (minted the token send() used)
    send()                       verified — text + Cards v2, UNTHREADED only
    send_text()                  verified — BOTH branches, in-thread and top-level

What remains unexercised against Google, in either method: the `thread.threadKey`
+ `messageReplyOption` branch of `send()` (a different field from the
`thread.name` branch `send_text()` uses, so send_text's clear does NOT cover
it), the non-200 branches, and the `httpx.HTTPError` branches.
"""

from __future__ import annotations

from typing import Callable, Protocol

import httpx

from ..envelope import DeliveryResult, OutboundMessage
from ..errors import GatewayAuthoredError
from ..registry import Identity

CHAT_API = "https://chat.googleapis.com/v1"
CHAT_SCOPE = "https://www.googleapis.com/auth/chat.bot"

TokenProvider = Callable[[], str]


class ChatApiError(GatewayAuthoredError, RuntimeError):
    """A Chat API call failed: the verb/identity, the HTTP status, and no body.

    `GatewayAuthoredError` is the load-bearing base, not decoration: it is what
    lets `SubscriberLoop.poll_once` print this message in FULL instead of the
    bare type name, which is the whole of CG-29 — CG-25 put the distinguishing
    detail (transport failure versus non-200) in here and the console threw it
    away. The mixin asserts the property every raise site below already has:
    names and statuses, never a response body. `RuntimeError` stays second so
    `except RuntimeError` still catches this.

    Same rule-#2 discipline as `WebhookDeliveryError` — read that docstring for
    the full argument, which applies with MORE force there: a webhook URL is
    itself a bearer credential, where this adapter's URL embeds only a space id
    (non-secret, per `docs/google-cloud-setup.md` step 8). Lower severity, same
    class of defect, so the same treatment: the response body is never
    interpolated on either method, because a Google error body can quote the
    request and the gateway does not control what comes back.

    The cost, stated as CG-7 stated it for `PubSubError`: Google's error prose
    is lost. Status plus reason phrase is what a caller can act on.
    """


class GoogleServiceAccountTokens:
    """Standard google-auth service-account flow. Lazy imports so offline
    tests never need google-auth's transport dependencies.

    ⚠ flag CLEARED 2026-07-29: this provider minted the token that
    `ChatApiAdapter.send()` used to post as the app. Re-exercised 2026-07-30
    against `chat-gateway-gw` with the current key (`chat-gateway-sa-gw.json`;
    the older `iac/chat-gateway-sa.json` belongs to a deleted project and is
    dead).
    """

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
        """Post a message as the Chat app.

        ⚠ flag CLEARED 2026-07-29. Verified through THIS class and the real
        `GoogleServiceAccountTokens` provider (not a reimplementation): a text
        message and a Cards v2 card both posted as the app, and the response
        carried `sender: {"displayName": "Agent Comms", "type": "BOT"}`.

        Scope of that clear — the success path for text and cards. NOT covered:
        the `thread.threadKey` + `messageReplyOption` branch below, because the
        live posts were UNTHREADED. Note that `send_text()`'s 2026-07-30 clear
        does not extend here: it threads by `thread.name`, a different field on
        a different request shape. Also not covered: the non-200 branch and the
        `httpx.HTTPError` branch.
        """
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
            # No body, and the phrase is looked up locally rather than taken
            # from `resp.reason_phrase` (which httpx reads off the wire) — see
            # webhook.py's raise site for the full note. Deliberately
            # byte-symmetric with the transport branch above and with
            # send_text()'s pair below: one failure shape across this file.
            reason = httpx.codes.get_reason_phrase(resp.status_code)
            raise ChatApiError(
                f"Chat API send failed for {identity.name}: "
                f"HTTP {resp.status_code} {reason}".rstrip()
            )
        return DeliveryResult(
            status="delivered", channel=identity.channel, identity=identity.name,
            mode="app", thread_key=message.thread_key,
        )

    def send_text(self, space: str, thread_name: str | None, text: str) -> None:
        """Bare in-thread text (authorization refusals, R7 failure notices).
        Matches the forwarder's ReplyFn signature.

        ⚠ flag CLEARED 2026-07-30 — **both branches**, which is the point.
        The plan for this item (Part C / CG-5) said this method would keep its
        flag; that was written before the live session and is superseded by it.

        The two branches were driven separately because they fail separately and
        each one is load-bearing for a different guarantee:

            thread_name set   -> posted into
                                 spaces/AAQAgjGR7J4/threads/_CWBxuQ8MlU.
                                 This is jobhunt R7's in-thread failure notice
                                 AND R4's authorization refusal — the paths that
                                 tell a user their tap did not land, or that they
                                 were not allowed to make it. A silent failure
                                 here is a silent failure of exactly those
                                 guarantees.
            thread_name None  -> posted at top level. The fallback when an event
                                 carries no thread, where a naive
                                 implementation would send `{"thread": {"name":
                                 null}}` and be rejected.

        NOT covered: the non-200 branch below. It raises with the status ONLY,
        which used to be deliberately unlike `send()` above — that method
        interpolated `resp.text[:200]`, and the contradiction inside one file
        was queue item CG-23. CG-23 closed it by making `send()` match THIS
        method rather than the reverse; the body is now gone from both.
        One residual asymmetry, left deliberately: `send()` and `webhook.send`
        append a locally-derived reason phrase ("HTTP 403 Forbidden") and this
        branch still does not ("HTTP 403"). CG-23 scoped itself to removing the
        body and would not touch a method that landed the same day — CG-25's
        byte-symmetry between this branch and the transport branch above is
        load-bearing for the R7 delivery-log strings.
        Also NOT covered: the `httpx.HTTPError` branch added by CG-25 — a
        transport failure has never been exercised against Google here either.
        """
        body: dict = {"text": text}
        params = {}
        if thread_name:
            body["thread"] = {"name": thread_name}
            params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
        try:
            resp = self._client.post(
                f"{CHAT_API}/{space}/messages", json=body, params=params,
                headers={"Authorization": f"Bearer {self._tokens()}"},
            )
        except httpx.HTTPError as exc:
            raise ChatApiError(f"in-thread reply failed: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise ChatApiError(f"in-thread reply failed: HTTP {resp.status_code}")
