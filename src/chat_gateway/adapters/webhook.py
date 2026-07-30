"""Tier-1 delivery: Google Chat incoming webhooks (one-way, named identity).

The webhook itself carries the identity: display name and avatar are fixed at
webhook creation in the Chat UI, and Chat renders THAT name. Google returns
`sender: null` for a webhook send — there is no sender object — so a webhook
created without a name shows in the space as "Unknown User". This adapter only
builds the message body and posts it.

⚠ flag CLEARED 2026-07-29, and independently re-confirmed 2026-07-30. Verified
through THIS class against real webhooks (not a reimplementation): plain-text
send -> HTTP 200, `delivered`; a Cards v2 payload passed through unchanged ->
HTTP 200, with rendering confirmed in the space by the user.

TIER 1 IS PROJECT-INDEPENDENT, and that is now empirical rather than asserted.
On 2026-07-30, IMMEDIATELY AFTER the `chat-gateway-prod` Cloud project was
deleted, all four webhook identities were re-run through this class and all four
returned `delivered`. `docs/google-cloud-setup.md` claimed this; it is now
observed. It is load-bearing, not trivia: a webhook URL is issued by the SPACE,
not by a Cloud project, so **no tier-2 deployment change — migration, project
deletion, credential rotation, subscription breakage — can take the notification
path down.** That is what makes tier 1 the floor under `aitrader`'s alerting.

Scope of the clear: the success path. The non-200 branch and the httpx.HTTPError
branch below have never been exercised against Google.

The URL never has to reach a log for it to be logged. `httpx` writes the whole
request URL — key and token — through its own logger on EVERY request, success
included, and nothing in this file put it there. `WebhookAdapter.__init__`
therefore arms `log_redaction.install_url_redaction()`; see that module for what
is redacted, what is not, and why the logger is not simply silenced (CG-34).

Threading — the experiment, and exactly what it proved. Two messages per
variant, distinct thread keys, using `thread.name` from Google's response as the
objective signal:

    threadKey query param + body thread.threadKey  ->  THREADED
    threadKey query param only                     ->  THREADED
    body thread.threadKey only                     ->  THREADED

The two mechanisms are redundant, so we now send exactly one: the body form.
Reason: `thread.threadKey` in the body is the `spaces.messages.create` request
shape, which is what chat_api.py already sends — one threading idiom across
both adapters means a future threading bug is one thing to reason about, not
two. It also means one less parameter spliced into a URL that embeds key+token.

⚠ WHAT THIS EXPERIMENT DID NOT ESTABLISH. All three variants above also carried
`messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD` in the query. The
proven statement is precisely:

    given messageReplyOption is present, either threadKey location suffices.

Whether `messageReplyOption` is required AT ALL was never isolated — the
fourth variant (threadKey with no messageReplyOption) was not run. Do not read
this result as license to drop messageReplyOption.
"""

from __future__ import annotations

import httpx

from ..envelope import DeliveryResult, OutboundMessage
from ..errors import GatewayAuthoredError
from ..log_redaction import install_url_redaction
from ..registry import Identity


class WebhookDeliveryError(GatewayAuthoredError, RuntimeError):
    """A webhook POST failed: the identity, the HTTP status, and nothing else.

    `GatewayAuthoredError` marks the message as safe to render in full — see
    that class and `describe_exception` (CG-29). This class earns it the hard
    way: CG-23 measured a real 403 putting this webhook's `key` AND `token`
    into three artifacts through the `resp.text[:200]` echo that used to be
    here, so what the mixin claims about this message is a claim that was
    tested against real TCP rather than reasoned about.

    The response body is never interpolated. A webhook URL embeds `key` AND
    `token` — it IS a bearer credential for posting as that identity — and a
    Google error body is free to quote the request that produced it. Hard rule
    #2 says error paths name the identity, not the URL, and it is written so
    that whether Google echoes the request TODAY never has to be known.
    `docs/google-cloud-setup.md` §8a exists because a webhook URL leaked once
    already, and there is no rotate-in-place: recovery is delete-and-recreate
    the webhook by hand, in the Chat UI.

    The cost is real, and stated rather than glossed (CG-7 set this precedent
    for `PubSubError`): Google's error prose is LOST. A 403 no longer says
    which of "webhook deleted", "space archived" or "sender blocked" it was;
    that now has to come from the space itself or from Google's own logs.
    Status plus reason phrase is what a caller can actually act on — retry,
    alert, or give up — and the prose was only ever useful to a human reading
    a log. It is not worth a credential.
    """


def build_payload(message: OutboundMessage) -> dict:
    payload: dict = {"text": message.text}
    if message.cards:
        payload["cardsV2"] = message.cards
    if message.thread_key:
        payload["thread"] = {"threadKey": message.thread_key}
    return payload


def build_params(message: OutboundMessage) -> dict:
    """Query parameters. `messageReplyOption` only, as of 2026-07-29.

    The `threadKey` query parameter used to be sent here as well; it was proven
    redundant with the body's `thread.threadKey` (see the module docstring) and
    dropped. `messageReplyOption` stays because its necessity was never
    isolated — every variant of that experiment included it.
    """
    if not message.thread_key:
        return {}
    return {"messageReplyOption": "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"}


class WebhookAdapter:
    def __init__(self, client: httpx.Client | None = None):
        # CG-34. Constructing the one object in the repo that resolves a
        # credential-bearing URL arms the logging guard, because httpx logs the
        # whole URL — key and token — at INFO, on the success path as well as
        # the failure path. Here rather than only at the entrypoint so it also
        # holds in tests, in `client.py`, and in the ad-hoc scripts that are how
        # the leak was found. Idempotent; see `log_redaction` for why redaction
        # rather than silencing the logger.
        install_url_redaction()
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
            # Never echo the URL (it embeds key+token) OR the body — name the
            # identity instead. See WebhookDeliveryError's docstring for why the
            # body goes too: we do not control what Google puts in it, and here
            # the request it may quote IS the credential.
            #
            # The phrase is looked up LOCALLY from the status code, not read off
            # `resp.reason_phrase` — httpx returns the wire value from
            # `extensions["reason_phrase"]` when the server sends one, so that
            # property is server-controlled bytes. This lookup is a fixed table
            # and carries nothing. Same rule, applied to the last field that
            # could still have smuggled a response in.
            reason = httpx.codes.get_reason_phrase(resp.status_code)
            raise WebhookDeliveryError(
                f"webhook POST failed for {identity.name}: "
                f"HTTP {resp.status_code} {reason}".rstrip()
            )
        return DeliveryResult(
            status="delivered", channel=identity.channel, identity=identity.name,
            mode="webhook", thread_key=message.thread_key,
        )
