"""Inbound push: per-tenant callback forwarding, failing LOUDLY in-thread.

Tenants opt in with `callback_url` (requires `allow_inbound: true` — an
opted-out tenant gets no inbound path at all, hard rule #6). Events forward
WHOLE as InboundReply JSON (jobhunt R3), carrying the Pub/Sub message id as
`dedupe_key` because delivery is at-least-once — tenant callbacks must be
idempotent.

Retries are short and latency-shaped — a human just tapped a button. Three
attempts, and `BACKOFF_S` holds the **gaps between them, not the times they
land at**: the last is due about **10s** after the tap (0s / 3s / 10s), and in
the running gateway they land at **0s / 5s / 15s**, because `process_due()`
only runs after a subscriber poll and each due time therefore rounds up to the
next tick. Both numbers are measured. The second is an observation, not a
timetable: it assumes the default 5s interval AND a fast-failing attempt,
because a poll cycle is the attempt's own duration plus the interval — a slow
one stretches it. Full treatment: `docs/consumers/jobhunt-handoff.md` §7.

When the attempts exhaust, the user must SEE the failure (jobhunt R7), so the
forwarder posts the tenant's `unreachable_message` into the thread via
`reply_fn` and records `failed` in the delivery log. Never silent.
"""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field
from typing import Callable

import httpx

from .delivery import DeliveryLog
from .envelope import InboundReply
from .registry import App

# GAPS, not attempt times — index i is the wait AFTER attempt i fails, so the
# three attempts fall due at 0s / 3s / 10s. Length sets the attempt count.
BACKOFF_S = (0, 3, 7)

# reply_fn(space, thread_name, text) — wired to the Chat API adapter's
# send_text in tier-2 deployments; None means R7's in-thread reply can't be
# made (tier 1 only) and the failure is log-only. Documented limitation.
ReplyFn = Callable[[str, str | None, str], None]


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@dataclass
class CallbackJob:
    app: App
    reply: InboundReply
    entry_id: int
    attempts: int = 0
    next_attempt_at: dt.datetime = field(default_factory=_utcnow)


class CallbackForwarder:
    def __init__(self, log: DeliveryLog, reply_fn: ReplyFn | None = None,
                 client: httpx.Client | None = None,
                 now_fn: Callable[[], dt.datetime] | None = None,
                 backoff: tuple = BACKOFF_S):
        self._log = log
        self._reply = reply_fn
        self._client = client or httpx.Client(timeout=10)
        self._now = now_fn or _utcnow
        self._backoff = backoff
        self._jobs: list[CallbackJob] = []
        self._lock = threading.Lock()

    @staticmethod
    def _title(reply: InboundReply) -> str:
        if reply.action:
            return f"interaction:{reply.action.get('id') or '?'}"
        return f"reply:{(reply.text or '')[:60]}"

    def enqueue(self, app: App, reply: InboundReply) -> int:
        entry_id = self._log.record(app.app_id, "callback", self._title(reply), "enqueued")
        with self._lock:
            self._jobs.append(CallbackJob(app=app, reply=reply, entry_id=entry_id,
                                          next_attempt_at=self._now()))
        return entry_id

    def pending(self) -> int:
        with self._lock:
            return len(self._jobs)

    def process_due(self) -> int:
        now = self._now()
        with self._lock:
            due = [j for j in self._jobs if j.next_attempt_at <= now]
        attempted = 0
        for job in due:
            attempted += 1
            url = job.app.resolved_callback_url()
            try:
                resp = self._client.post(url, json=job.reply.model_dump(mode="json"))
                ok = 200 <= resp.status_code < 300
                detail = f"HTTP {resp.status_code}"
            except httpx.HTTPError as exc:
                ok, detail = False, type(exc).__name__
            if ok:
                self._finish(job, "forwarded", detail)
            else:
                job.attempts += 1
                if job.attempts >= len(self._backoff):
                    self._finish(job, "failed", f"gave up after {job.attempts} attempts ({detail})")
                    self._fail_loudly(job)
                else:
                    job.next_attempt_at = now + dt.timedelta(seconds=self._backoff[job.attempts])
        return attempted

    def _finish(self, job: CallbackJob, status: str, detail: str) -> None:
        self._log.record(job.app.app_id, "callback", self._title(job.reply), status,
                         detail, entry_id=job.entry_id)
        with self._lock:
            if job in self._jobs:
                self._jobs.remove(job)

    def _fail_loudly(self, job: CallbackJob) -> None:
        """R7: the user who tapped must see it didn't land."""
        if self._reply is None or not job.reply.space:
            self._log.record(job.app.app_id, "callback", self._title(job.reply),
                             "failed-silent", "no reply_fn (tier 1) — in-thread notice impossible",
                             entry_id=job.entry_id)
            return
        text = job.app.unreachable_message or (
            f"⚠️ Couldn't reach {job.app.app_id} — your action did NOT land. "
            "Use its fallback UI."
        )
        try:
            self._reply(job.reply.space, job.reply.thread_name, text)
        except Exception as exc:  # noqa: BLE001 — best effort, but never silent in the log
            self._log.record(job.app.app_id, "callback", self._title(job.reply),
                             "failed-silent", f"in-thread notice also failed: {exc}",
                             entry_id=job.entry_id)
