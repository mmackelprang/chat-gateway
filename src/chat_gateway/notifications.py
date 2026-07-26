"""/v1/notify: the gateway-owned GENERIC notification shape + severity
rendering + dedupe.

This is deliberately generic (source, severity, title, body, action) — it
carries no consumer semantics (hard rule #2 of the aitrader contract: what a
HALT means stays the consumer's problem). Severity only controls routing and
how loud the rendering is:

  alert   -> card with ⚠️🔴 header, prominent "What to do" section
  warning -> card with 🟠 header
  info    -> plain text (no card)

Dedupe: identical (source, dedupe_key) within the window collapses — the
first occurrence delivers, repeats are counted, and the count is carried on
the *next* delivered message after the window reopens (one-way webhooks
cannot edit an already-posted message; the delivery log records every
occurrence either way).
"""

from __future__ import annotations

import datetime as dt
import threading
from typing import Callable

from pydantic import BaseModel, Field, field_validator

from .envelope import OutboundMessage

SEVERITIES = ["alert", "warning", "info"]
SEVERITY_EMOJI = {"alert": "⚠️🔴", "warning": "🟠", "info": "ℹ️"}
DEFAULT_DEDUPE_WINDOW_S = 3600


class Notification(BaseModel):
    source: str | None = Field(default=None,
                               description="informational; the authenticated app is authoritative")
    severity: str
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=4000)
    action: str = Field(default="", max_length=200,
                        description="one-line 'what to do' — rendered prominently on alerts")
    dedupe_key: str | None = Field(default=None, max_length=128)
    thread_key: str | None = Field(default=None, max_length=128)
    timestamp: dt.datetime | None = None

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: str) -> str:
        if v not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        return v


def render(n: Notification, app_id: str, occurrences: int = 1) -> OutboundMessage:
    """Notification -> envelope. Alerts/warnings get a card; info is text."""
    emoji = SEVERITY_EMOJI[n.severity]
    counter = f" (×{occurrences} since last notice)" if occurrences > 1 else ""
    text = f"{emoji} [{n.severity.upper()}] {n.title}{counter}"
    if n.severity == "info":
        body_text = text + (f"\n{n.body}" if n.body else "")
        return OutboundMessage(identity="-", text=body_text, thread_key=n.thread_key)

    widgets: list[dict] = []
    if n.body:
        widgets.append({"textParagraph": {"text": n.body}})
    if n.action:
        widgets.append({"decoratedText": {"topLabel": "What to do", "text": f"<b>{n.action}</b>"}})
    if n.timestamp:
        widgets.append({"textParagraph": {"text": f"<i>at {n.timestamp.isoformat()}</i>"}})
    card = {
        "cardId": n.dedupe_key or "notification",
        "card": {
            "header": {"title": f"{emoji} {n.severity.upper()}{counter}", "subtitle": f"{app_id}: {n.title}"},
            "sections": [{"widgets": widgets or [{"textParagraph": {"text": n.title}}]}],
        },
    }
    return OutboundMessage(identity="-", text=text, cards=[card], thread_key=n.thread_key)


class Deduper:
    """(source, dedupe_key) collapse within a rolling window."""

    def __init__(self, window_seconds: int = DEFAULT_DEDUPE_WINDOW_S,
                 now_fn: Callable[[], dt.datetime] | None = None):
        self._window = dt.timedelta(seconds=window_seconds)
        self._now = now_fn or (lambda: dt.datetime.now(dt.timezone.utc))
        self._state: dict[tuple[str, str], tuple[dt.datetime, int]] = {}
        self._lock = threading.Lock()

    def check(self, source: str, dedupe_key: str | None) -> tuple[bool, int]:
        """Returns (deliver_now, occurrences_including_this_one).

        No dedupe_key -> always deliver. Within the window -> suppressed
        (counted). After the window -> deliver, carrying the count since the
        last delivered message, and reset."""
        if not dedupe_key:
            return True, 1
        key = (source, dedupe_key)
        now = self._now()
        with self._lock:
            last_delivered, suppressed = self._state.get(key, (None, 0))
            if last_delivered is not None and now - last_delivered < self._window:
                self._state[key] = (last_delivered, suppressed + 1)
                return False, suppressed + 1
            occurrences = suppressed + 1
            self._state[key] = (now, 0)
            return True, occurrences
