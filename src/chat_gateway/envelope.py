"""The channel-agnostic message envelope — the only schema the gateway owns.

Applications render their own content (text + Google Chat Cards v2 blocks —
or whatever a future channel adapter accepts) and hand it over inside this
envelope. The gateway never interprets or owns an application's domain
schema; it delivers, threads, and routes.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field, field_validator

THREAD_KEY_MAX = 128


class OutboundMessage(BaseModel):
    """What an app POSTs to /v1/messages. The sending app is derived from the
    API key server-side — it is never a client-supplied claim."""

    identity: str = Field(description="registered identity to send as (e.g. pm-familyworkspace)")
    text: str = Field(min_length=1, max_length=4000,
                      description="plain-text body; also the notification fallback when cards are present")
    cards: list[dict[str, Any]] = Field(
        default_factory=list,
        description="optional Google Chat cardsV2 entries, passed through verbatim",
    )
    thread_key: str | None = Field(
        default=None, max_length=THREAD_KEY_MAX,
        description="app-chosen conversation key; replies to the thread come back tagged with it",
    )

    @field_validator("thread_key")
    @classmethod
    def _thread_key_shape(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("thread_key must be non-empty when provided")
        return v

    @field_validator("cards")
    @classmethod
    def _cards_shape(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        import json as _json

        for i, card in enumerate(v):
            if "card" not in card:
                raise ValueError(f"cards[{i}] must be a cardsV2 entry (dict with 'card', usually 'cardId')")
        if v and len(_json.dumps(v)) > 30_000:
            raise ValueError("cards payload exceeds 30KB (Chat's message limit) — trim the card")
        return v


class DeliveryResult(BaseModel):
    status: str  # delivered | failed
    channel: str
    identity: str
    mode: str  # webhook | app
    thread_key: str | None = None
    detail: str = ""


class InboundReply(BaseModel):
    """A human's reply or card interaction, normalized from a Chat event and
    routed to the owning app(s) — forwarded WHOLE (jobhunt R3): the `raw`
    event rides along for anything normalization loses."""

    app: str
    space: str
    thread_key: str | None = None
    thread_name: str | None = None   # spaces/X/threads/Y — for in-thread replies
    message_id: str | None = None    # spaces/X/messages/Z
    sender_display: str = ""
    sender_email: str | None = None
    text: str = ""
    action: dict[str, Any] | None = None  # CARD_CLICKED: {"id", "params"} incl. formInputs
    dedupe_key: str | None = None    # Pub/Sub message id — at-least-once => idempotent callbacks
    received_at: dt.datetime
    event_type: str = "MESSAGE"
    envelope_format: str = "classic"  # classic | addon | unparseable — which
                                      # Google runtime produced this event;
                                      # transport metadata, not app domain
    raw: dict[str, Any] = Field(default_factory=dict)
