"""/v1/notify: the gateway-owned GENERIC notification shape + severity
rendering + dedupe.

This is deliberately generic (source, severity, title, body, action) — it
carries no consumer semantics (hard rule #2 of the aitrader contract: what a
HALT means stays the consumer's problem). Severity only controls routing and
how loud the rendering is:

  alert   -> card with ⚠️🔴 header, prominent "What to do" section
  warning -> card with 🟠 header
  info    -> plain text (no card)

That last row costs `info` a budget the others do not pay: its title AND body
share the envelope's single plain-text field, so the two together must fit
`info_max_combined_length()`. See that function and `Notification`'s validator.

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

from pydantic import BaseModel, Field, field_validator, model_validator

from .envelope import TEXT_MAX, OutboundMessage

SEVERITIES = ["alert", "warning", "info"]
SEVERITY_EMOJI = {"alert": "⚠️🔴", "warning": "🟠", "info": "ℹ️"}
DEFAULT_DEDUPE_WINDOW_S = 3600

#: What `render` joins an info notification's title and body with.
INFO_BODY_SEPARATOR = "\n"


def severity_prefix(severity: str) -> str:
    """The lead-in `render` puts in front of every notification's title.

    One construction, used by both the renderer and the info-path budget below,
    so the guard cannot drift from what is actually emitted. Its length is not a
    constant anyone should write down: "ℹ️" alone is two code points, and a
    relabelled severity would move the bound silently.
    """
    return f"{SEVERITY_EMOJI[severity]} [{severity.upper()}] "


def info_max_combined_length() -> int:
    """Longest `len(title) + len(body)` the info path can render.

    Info is the one severity whose body does NOT become a card widget — prefix,
    title and body are concatenated into the envelope's single plain-text field,
    which the transport caps at `TEXT_MAX`. Derived, never hardcoded, so this
    and `render` are the same arithmetic. (The dedupe counter `render` may also
    append is deliberately NOT reserved here — see `Notification`'s validator.)
    """
    return TEXT_MAX - len(severity_prefix("info")) - len(INFO_BODY_SEPARATOR)


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

    @model_validator(mode="after")
    def _info_fits_one_text_field(self) -> "Notification":
        """Reject an info notification that cannot be rendered (CG-30).

        Scoped to `info` on purpose. Only that severity concatenates title and
        body into the envelope's single plain-text field; `alert` and `warning`
        put the body in a card widget, so all that reaches `text` is the short
        fallback line — a title-200 + body-4000 alert is accepted today, and
        must stay accepted. Which is exactly why the fix is NOT to tighten
        `body`'s own `max_length`: that would start rejecting payloads the
        gateway delivers fine.

        Without this the ValidationError fires later, inside `render`, where
        nothing catches it and the caller gets a 500. Here, it is a 422 like
        every other malformed request.

        Not covered: `render` also appends a "(×N since last notice)" counter to
        deduped re-deliveries, which can push an accepted payload back over the
        cap. Request-time validation cannot reserve room for it without
        rejecting payloads that succeed today — filed separately.
        """
        if self.severity != "info":
            return self
        limit = info_max_combined_length()
        size = len(self.title) + len(self.body)
        if size > limit:
            # Names the offending field pair, the size and the limit, so a
            # caller can act without bisecting — and never quotes the content
            # itself (the gateway's error paths name identities, not payloads).
            raise ValueError(
                f"severity 'info' renders title and body as one plain-text message, "
                f"which the transport caps at {TEXT_MAX} characters: "
                f"len(title) + len(body) is {size}, limit is {limit}. "
                f"Shorten the body, or send 'warning'/'alert', whose body becomes "
                f"a card widget instead."
            )
        return self


def render(n: Notification, app_id: str, occurrences: int = 1) -> OutboundMessage:
    """Notification -> envelope. Alerts/warnings get a card; info is text.

    The info branch spends the envelope's whole plain-text budget on title +
    body, which is why `Notification` guards it at `info_max_combined_length()`.
    """
    emoji = SEVERITY_EMOJI[n.severity]
    counter = f" (×{occurrences} since last notice)" if occurrences > 1 else ""
    text = f"{severity_prefix(n.severity)}{n.title}{counter}"
    if n.severity == "info":
        body_text = text + (f"{INFO_BODY_SEPARATOR}{n.body}" if n.body else "")
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
