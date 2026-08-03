"""Restart survival for both queues — the point of CG-54.

Everything here is synthetic: the identities, the env-var names, the app ids.
Nothing names a real space, a real credential or a real person; the CG-26 guard
scans `tests/**/*.py`.

The centrepiece is `test_a_job_survives_an_ABRUPT_kill_of_a_real_process`, which
does not assert that a file exists — it starts a second Python process, has it
enqueue against a failing adapter, kills it uncatchably, and then replays from
the same state directory in this one. Asserting the file exists proves the
journal wrote; only killing a process proves the queue survives.
"""

import contextlib
import datetime as dt
import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from chat_gateway.delivery import BACKOFF_S, DeliveryLog, Dispatcher
from chat_gateway.envelope import InboundReply, OutboundMessage
from chat_gateway.inbox import Inbox
from chat_gateway.journal import Journal
from chat_gateway.registry import App, Identity, Registry

from conftest import assert_owner_only

SRC = str(Path(__file__).resolve().parents[1] / "src")


class BoomAdapter:
    """Never delivers. Stands in for an unreachable webhook."""

    def send(self, identity, message):
        raise RuntimeError("synthetic transport failure")


class OkAdapter:
    def __init__(self):
        self.sent = []

    def send(self, identity, message):
        self.sent.append((identity.name, message.text))


def _registry():
    ident = Identity(name="ident-a", display="A", mode="webhook",
                     webhook_url_env="TEST_WEBHOOK_URL_ENV_NOT_REAL")
    app = App(app_id="app-a", key_env="TEST_APP_KEY_ENV_NOT_REAL",
              identities=["ident-a"])
    return Registry(identities={"ident-a": ident}, apps={"app-a": app})


def _message(text="hello", identity="ident-a"):
    return OutboundMessage(identity=identity, text=text)


def _reply(app="app-a", text="tapped"):
    return InboundReply(app=app, space="", text=text,
                        received_at=dt.datetime(2026, 7, 31, 12, tzinfo=dt.timezone.utc))


# --------------------------------------------------------------------------
# The kill/restart proof
# --------------------------------------------------------------------------

_CHILD = """
import sys
sys.path.insert(0, {src!r})
from chat_gateway.delivery import DeliveryLog, Dispatcher
from chat_gateway.envelope import InboundReply, OutboundMessage
from chat_gateway.inbox import Inbox
from chat_gateway.journal import Journal
from chat_gateway.registry import App, Identity, Registry
import datetime as dt

ident = Identity(name="ident-a", display="A", mode="webhook",
                 webhook_url_env="TEST_WEBHOOK_URL_ENV_NOT_REAL")
reg = Registry(identities={{"ident-a": ident}},
               apps={{"app-a": App(app_id="app-a", key_env="TEST_APP_KEY_ENV_NOT_REAL",
                                   identities=["ident-a"])}})


class Boom:
    def send(self, identity, message):
        raise RuntimeError("synthetic transport failure")


d = Dispatcher({{"webhook": Boom()}}, DeliveryLog(),
               journal=Journal({outbound!r}))
for n in range(3):
    d.enqueue("app-a", "notify", ident,
              OutboundMessage(identity="ident-a", text="job %d" % n), "t%d" % n)
d.process_due()

inbox = Inbox(journal=Journal({inbound!r}))
inbox.put(InboundReply(app="app-a", space="", text="approve",
                       received_at=dt.datetime.now(dt.timezone.utc)))

print("READY", flush=True)
import time
time.sleep(600)
"""


def test_a_job_survives_an_ABRUPT_kill_of_a_real_process(tmp_path):
    """Enqueue in another process, SIGKILL it, replay here.

    `Popen.kill()` is `SIGKILL` on POSIX and `TerminateProcess` on Windows —
    uncatchable on both, so no atexit hook, no `finally`, and no graceful
    flush can run. Whatever survives, survived because it was already on disk.
    """
    outbound = tmp_path / "queue" / "delivery.jsonl"
    inbound = tmp_path / "queue" / "inbox.jsonl"
    script = _CHILD.format(src=SRC, outbound=str(outbound), inbound=str(inbound))

    child = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(script)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    try:
        line = child.stdout.readline()
        assert line.strip() == "READY", (line, child.stderr.read() if child.poll() else "")
    finally:
        child.kill()
        child.wait(timeout=30)

    assert child.poll() is not None, "the child must actually be dead"

    # --- restart, same state dir -------------------------------------------
    reg = _registry()
    ok = OkAdapter()
    # The child's failed pass put all three into the 30s backoff step, and that
    # survived the kill — so a dispatcher booting at the same instant correctly
    # finds NOTHING due. Stepping a minute forward is what makes them due; it is
    # also the assertion that a crash-loop cannot reset the ladder.
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=1)
    revived = Dispatcher({"webhook": ok}, DeliveryLog(), journal=Journal(outbound),
                         now_fn=lambda: later)
    restored, not_restored = revived.restore(reg)
    assert (restored, not_restored) == (3, 0)
    assert [j.attempts for j in revived._jobs] == [1, 1, 1]

    revived_inbox = Inbox(journal=Journal(inbound))
    assert revived_inbox.restore() == 1
    assert [r.text for r in revived_inbox.poll("app-a")] == ["approve"]

    # ...and they drain EXACTLY ONCE, not once per restored record.
    revived.process_due()
    assert sorted(text for _, text in ok.sent) == ["job 0", "job 1", "job 2"]
    assert revived.pending() == 0

    # A third boot has nothing left: the drain closed them, and boot compaction
    # after the second one had already removed the terminal records.
    third = Dispatcher({"webhook": OkAdapter()}, DeliveryLog(), journal=Journal(outbound))
    assert third.restore(reg) == (0, 0)
    assert Inbox(journal=Journal(inbound)).restore() == 0


def test_the_killed_process_left_a_journal_a_human_can_read(tmp_path):
    """Half the reason for JSONL: an operator reads it during an incident."""
    outbound = tmp_path / "queue" / "delivery.jsonl"
    inbound = tmp_path / "queue" / "inbox.jsonl"
    script = _CHILD.format(src=SRC, outbound=str(outbound), inbound=str(inbound))
    child = subprocess.Popen([sys.executable, "-c", textwrap.dedent(script)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    try:
        assert child.stdout.readline().strip() == "READY"
    finally:
        child.kill()
        child.wait(timeout=30)

    text = outbound.read_text(encoding="utf-8")
    assert '"op": "open"' in text
    assert '"op": "update"' in text          # the failed pass rescheduled them
    assert "job 0" in text                   # payloads are legible, not encoded
    # ...and no credential is in there. The journal carries an identity NAME;
    # the URL that name resolves to never reaches disk (hard rule #2).
    assert '"identity": "ident-a"' in text
    assert "TEST_WEBHOOK_URL_ENV_NOT_REAL" not in text
    assert "http" not in text


# --------------------------------------------------------------------------
# Outbound queue
# --------------------------------------------------------------------------

def test_an_undelivered_job_survives_a_restart(tmp_path):
    reg = _registry()
    path = tmp_path / "delivery.jsonl"
    first = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog(), journal=Journal(path))
    first.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    first.process_due()                       # fails, reschedules
    assert first.pending() == 1

    ok = OkAdapter()
    second = Dispatcher({"webhook": ok}, DeliveryLog(), journal=Journal(path))
    restored, not_restored = second.restore(reg)
    assert (restored, not_restored) == (1, 0)
    assert second.pending() == 1


def test_the_attempt_count_survives_so_backoff_is_not_reset(tmp_path):
    reg = _registry()
    path = tmp_path / "delivery.jsonl"
    first = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog(), journal=Journal(path))
    first.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    first.process_due()
    first.process_due()                       # not due yet — attempts stays 1

    second = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog(), journal=Journal(path))
    second.restore(reg)
    assert second._jobs[0].attempts == 1


def test_a_delivered_job_is_not_replayed(tmp_path):
    reg = _registry()
    path = tmp_path / "delivery.jsonl"
    first = Dispatcher({"webhook": OkAdapter()}, DeliveryLog(), journal=Journal(path))
    first.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    first.process_due()
    assert first.pending() == 0

    second = Dispatcher({"webhook": OkAdapter()}, DeliveryLog(), journal=Journal(path))
    assert second.restore(reg) == (0, 0)


def test_a_job_that_was_MID_FLIGHT_at_kill_time_is_replayed_and_may_send_twice(tmp_path):
    """The one case most likely to be hand-waved, pinned as DELIBERATE.

    The kill window is between the adapter returning and the `close` reaching
    disk. Reproduced exactly: an adapter that delivers and then dies. The job
    reached Chat once and the journal never learned, so replay sends it again.
    Chat has no idempotency key, notify dedupe collapses repeats within its
    window, and losing an alert is the worse failure — so at-least-once is the
    contract, not an accident.
    """
    reg = _registry()
    path = tmp_path / "delivery.jsonl"
    delivered = []

    class DiesAfterDelivering:
        def send(self, identity, message):
            delivered.append(message.text)
            raise KeyboardInterrupt("the process dies here, after the send")

    first = Dispatcher({"webhook": DiesAfterDelivering()}, DeliveryLog(),
                       journal=Journal(path))
    first.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    try:
        first.process_due()
    except KeyboardInterrupt:
        pass
    assert delivered == ["hello"]             # it DID reach the far end...

    ok = OkAdapter()
    second = Dispatcher({"webhook": ok}, DeliveryLog(), journal=Journal(path))
    assert second.restore(reg) == (1, 0)      # ...and the journal never knew
    second.process_due()
    assert [text for _, text in ok.sent] == ["hello"]   # the second delivery


def test_a_job_older_than_the_replay_ceiling_expires_rather_than_sending(tmp_path):
    # An alert from three days ago, posted now, actively misleads. Both outcomes
    # are bad; this is the visible one — it lands in the delivery log as expired.
    reg = _registry()
    path = tmp_path / "delivery.jsonl"
    old = dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)
    first = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog(),
                       now_fn=lambda: old, journal=Journal(path, now_fn=lambda: old))
    first.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")

    ok = OkAdapter()
    log = DeliveryLog()
    second = Dispatcher({"webhook": ok}, log, journal=Journal(path))
    restored, not_restored = second.restore(reg)
    assert (restored, not_restored) == (0, 1)
    assert (second.expired, second.unroutable) == (1, 0)
    second.process_due()
    assert ok.sent == []
    assert log.query("app-a")[-1]["status"] == "expired"


def test_an_expired_job_is_closed_so_the_next_boot_does_not_see_it_again(tmp_path):
    reg = _registry()
    path = tmp_path / "delivery.jsonl"
    old = dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)
    first = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog(),
                       now_fn=lambda: old, journal=Journal(path, now_fn=lambda: old))
    first.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    Dispatcher({"webhook": OkAdapter()}, DeliveryLog(), journal=Journal(path)).restore(reg)

    third = Dispatcher({"webhook": OkAdapter()}, DeliveryLog(), journal=Journal(path))
    assert third.restore(reg) == (0, 0)


def test_a_job_whose_identity_left_the_registry_is_not_sent_on_a_stale_grant(tmp_path):
    # Hard rule #4: the registry decides what an app may send as, at send time.
    # The journal stores a NAME precisely so this re-check is possible.
    reg = _registry()
    path = tmp_path / "delivery.jsonl"
    first = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog(), journal=Journal(path))
    first.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")

    narrowed = _registry()
    narrowed.apps["app-a"].identities = []      # grant withdrawn between runs
    ok = OkAdapter()
    log = DeliveryLog()
    second = Dispatcher({"webhook": ok}, log, journal=Journal(path))
    restored, not_restored = second.restore(narrowed)
    assert (restored, not_restored) == (0, 1)
    assert (second.expired, second.unroutable) == (0, 1)
    second.process_due()
    assert ok.sent == []
    assert log.query("app-a")[-1]["status"] == "unroutable"


def test_the_journal_never_holds_a_credential_only_an_identity_name(tmp_path):
    # Hard rule #2 executed rather than described: the payload that reaches disk
    # carries content and a NAME. The webhook URL — which embeds key+token —
    # is resolved from the env at send time and is never written.
    reg = _registry()
    path = tmp_path / "delivery.jsonl"
    d = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog(), journal=Journal(path))
    d.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    record = path.read_text(encoding="utf-8")
    assert '"identity": "ident-a"' in record
    assert "webhook_url_env" not in record
    assert "TEST_WEBHOOK_URL_ENV_NOT_REAL" not in record
    assert "TEST_APP_KEY_ENV_NOT_REAL" not in record


def test_a_failed_close_does_not_become_a_resend_storm(tmp_path):
    # A journal write that fails on the terminal path must not keep the job in
    # the queue: the loop would retry it every second and a full disk would turn
    # into an unbounded re-send against Google. It degrades and COUNTS instead.
    reg = _registry()

    class BrokenJournal(Journal):
        def close(self, entry_id, status):
            raise OSError("no space left on device")

    ok = OkAdapter()
    d = Dispatcher({"webhook": ok}, DeliveryLog(),
                   journal=BrokenJournal(tmp_path / "delivery.jsonl"))
    d.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    d.process_due()
    assert d.pending() == 0
    assert d.journal_write_errors == 1
    d.process_due()
    assert len(ok.sent) == 1                  # sent once, not once per pass


def test_a_failed_enqueue_write_refuses_the_job_rather_than_pretending(tmp_path):
    # The opposite decision, on purpose: refusing tells the consumer its alert
    # was not accepted, so its own fallback log takes over. Accepting work we
    # cannot persist, on a queue advertised as durable, is the silent failure.
    reg = _registry()

    class BrokenJournal(Journal):
        def open(self, entry_id, kind, payload):
            raise OSError("no space left on device")

    d = Dispatcher({"webhook": OkAdapter()}, DeliveryLog(),
                   journal=BrokenJournal(tmp_path / "delivery.jsonl"))
    try:
        d.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    except OSError:
        pass
    else:  # pragma: no cover - only reached if the guard regresses
        raise AssertionError("an unpersistable enqueue must not report success")
    assert d.pending() == 0


def test_delivery_log_ids_continue_past_the_replayed_ones(tmp_path):
    # Otherwise a restarted gateway mints id 1 for its first new notification
    # while a replayed job still carries id 1, and an operator reading the log
    # to find out what the restart did sees two rows sharing an id.
    reg = _registry()
    path = tmp_path / "delivery.jsonl"
    first = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog(), journal=Journal(path))
    for _ in range(3):
        first.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")

    log = DeliveryLog()
    second = Dispatcher({"webhook": BoomAdapter()}, log, journal=Journal(path))
    second.restore(reg)
    new_id = second.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    assert new_id > 3


# --------------------------------------------------------------------------
# Retention: what the queues KEEP, and for how long (CG-65 / ADR-0002 D1, D5)
# --------------------------------------------------------------------------

def test_delivery_audit_file_is_owner_only(tmp_path):
    # CG-65 / ADR-0002 D5. Titles-only, so a smaller exposure than the inbox
    # audit — but `title[:200]` and `detail[:300]` can still carry sensitive
    # state, and there was no reason for it to be the one artifact under the
    # state dir left at 0644.
    log = DeliveryLog(audit_dir=tmp_path / "deliveries")
    log.record("app-a", "notify", "HALT: SYNTHETIC-TICKER", "enqueued")
    audit = next((tmp_path / "deliveries").glob("*.jsonl"))
    assert_owner_only(audit)
    # and the mode survives a second append rather than being reset
    log.record("app-a", "notify", "HALT: SYNTHETIC-TICKER", "delivered")
    assert_owner_only(audit)


def test_delivered_body_is_erased_when_the_queue_drains(tmp_path):
    """ADR-0002 §2.2 measured weeks; D1 makes it seconds.

    A `close` does NOT erase a payload — it appends a line saying the id is
    done while the `open` line carrying the body stays where it was. Only
    compaction erases it.
    """
    reg = _registry()
    jpath = tmp_path / "delivery.jsonl"
    d = Dispatcher({"webhook": OkAdapter()}, DeliveryLog(), journal=Journal(jpath))
    d.enqueue("app-a", "notify", reg.identities["ident-a"],
              _message("SYNTHETIC BODY 4200"), "t")
    assert "SYNTHETIC BODY 4200" in jpath.read_text(encoding="utf-8")
    d.process_due()
    assert d.pending() == 0
    assert jpath.read_text(encoding="utf-8") == ""      # zero lines, body gone


def test_a_stuck_job_pins_the_other_bodies_until_it_terminates(tmp_path):
    """The honest cost of D1, pinned as a test rather than left as a comment.

    Compaction is on DRAIN and there is one journal for the whole gateway, so
    one stuck job holds every other source's delivered body on disk until it
    terminates. Bounded by the retry ladder, or by REPLAY_MAX_AGE_S across
    downtime. `app-a` / `app-b` are two synthetic tenants, per this file's rule.
    """
    reg = _registry()
    jpath = tmp_path / "delivery.jsonl"
    stuck = Identity(name="ident-b", display="B", mode="app")
    d = Dispatcher({"webhook": OkAdapter(), "app": BoomAdapter()}, DeliveryLog(),
                   journal=Journal(jpath))
    d.enqueue("app-b", "notify", stuck, _message("STUCK", identity="ident-b"), "stuck")
    d.enqueue("app-a", "notify", reg.identities["ident-a"],
              _message("QUIET TENANT BODY"), "ok")
    d.process_due()
    # the app-a job delivered and closed, but the set never drained
    assert d.pending() == 1
    assert "QUIET TENANT BODY" in jpath.read_text(encoding="utf-8")


def test_the_append_count_backstop_still_fires_for_a_queue_that_never_drains(tmp_path):
    """D1 compacts on drain; `_maybe_compact_locked` STAYS for what never does.

    `backoff=(0,) * 20` keeps every retry immediately due, so one job stays in
    the live set while its `update` lines pile up — exactly the shape the
    append-count trigger exists for, and the reason compacting on drain does
    not replace it.
    """
    reg = _registry()
    jpath = tmp_path / "delivery.jsonl"
    d = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog(), backoff=(0,) * 20,
                   journal=Journal(jpath, compact_after=6))
    d.enqueue("app-a", "notify", reg.identities["ident-a"], _message("STUCK"), "stuck")
    for _ in range(12):
        d.process_due()
    assert d.pending() == 1                   # never drained
    # 1 open + 12 updates would be 13 lines without the backstop
    assert len(jpath.read_text(encoding="utf-8").splitlines()) < 13


def test_a_failed_close_does_not_let_compaction_erase_the_open_record(tmp_path):
    """The `closed` gate on D1's compaction, which the plan's `if drained:` left
    open. A failed `close` is COUNTED so the entry replays on the next boot; a
    compaction fired on the same drain would delete it instead, converting a
    visible degradation into a silent loss.
    """
    reg = _registry()
    jpath = tmp_path / "delivery.jsonl"

    class BrokenJournal(Journal):
        def close(self, entry_id, status):
            raise OSError("no space left on device")

    d = Dispatcher({"webhook": OkAdapter()}, DeliveryLog(), journal=BrokenJournal(jpath))
    d.enqueue("app-a", "notify", reg.identities["ident-a"], _message("SURVIVES"), "t")
    d.process_due()
    assert d.pending() == 0 and d.journal_write_errors == 1
    assert "SURVIVES" in jpath.read_text(encoding="utf-8")
    assert Dispatcher({"webhook": OkAdapter()}, DeliveryLog(),
                      journal=Journal(jpath)).restore(reg) == (1, 0)


def test_without_a_journal_the_dispatcher_is_exactly_what_it_was(tmp_path):
    reg = _registry()
    d = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog())
    d.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    d.process_due()
    assert d.restore(reg) == (0, 0)
    assert d.pending() == 1
    assert d.journal is None


# --------------------------------------------------------------------------
# Inbound queue — the half the original brief did not scope
# --------------------------------------------------------------------------

def test_an_unpolled_inbound_reply_survives_a_restart(tmp_path):
    # Passive polling is the only inbound path an opted-out tenant has, and a
    # consumer's host sleeps — a reply can wait hours, across restarts.
    path = tmp_path / "inbox.jsonl"
    first = Inbox(journal=Journal(path))
    first.put(_reply())
    second = Inbox(journal=Journal(path))
    assert second.restore() == 1
    assert len(second.poll("app-a")) == 1


def test_a_polled_reply_is_not_replayed(tmp_path):
    path = tmp_path / "inbox.jsonl"
    first = Inbox(journal=Journal(path))
    first.put(_reply())
    first.poll("app-a")
    second = Inbox(journal=Journal(path))
    assert second.restore() == 0
    assert second.poll("app-a") == []


def test_a_restored_reply_keeps_its_whole_payload(tmp_path):
    # Hard rule #6's forward-the-whole-event promise has to survive a restart
    # too, or the consumer gets a thinner event than the one that arrived.
    path = tmp_path / "inbox.jsonl"
    rich = InboundReply(app="app-a", space="", text="approve",
                        action={"id": "approve", "params": {"n": "1"}},
                        dedupe_key="synthetic-dedupe-key",
                        received_at=dt.datetime(2026, 7, 31, 12, tzinfo=dt.timezone.utc),
                        raw={"anything": "the normalizer dropped"})
    Inbox(journal=Journal(path)).put(rich)
    revived = Inbox(journal=Journal(path))
    revived.restore()
    got = revived.poll("app-a")[0]
    assert got.action == {"id": "approve", "params": {"n": "1"}}
    assert got.dedupe_key == "synthetic-dedupe-key"
    assert got.raw == {"anything": "the normalizer dropped"}


def test_ids_continue_past_the_journal_so_a_restart_cannot_collide(tmp_path):
    path = tmp_path / "inbox.jsonl"
    first = Inbox(journal=Journal(path))
    first.put(_reply())
    first.put(_reply())
    second = Inbox(journal=Journal(path))
    second.restore()
    second.put(_reply())
    second.poll("app-a")
    assert Inbox(journal=Journal(path)).restore() == 0


def test_an_overflow_drop_is_closed_so_it_does_not_come_back_at_boot(tmp_path):
    path = tmp_path / "inbox.jsonl"
    first = Inbox(max_pending=2, journal=Journal(path))
    for n in range(4):
        first.put(_reply(text=f"tap {n}"))
    assert first.dropped == 2
    second = Inbox(max_pending=2, journal=Journal(path))
    assert second.restore() == 2
    assert [r.text for r in second.poll("app-a")] == ["tap 2", "tap 3"]


def test_a_journalled_reply_that_no_longer_parses_is_COUNTED_not_silently_erased(tmp_path):
    """Pre-merge review finding. The drop is right; the silence was not.

    A record that cannot be revived is dropped and boot compaction then removes
    it for good — so without a counter, an envelope change across a deploy
    erases a tap and nobody is ever told. This is the inbound twin of the
    dispatcher's `unroutable`, which had a counter, a log entry and a /healthz
    reason from the start.
    """
    path = tmp_path / "inbox.jsonl"
    good = Inbox(journal=Journal(path))
    good.put(_reply(text="survives"))
    # A record from a hypothetical future envelope: valid JSON, valid journal
    # record, no longer a valid InboundReply.
    Journal(path).open(999, "inbound", {"app": "app-a", "not": "an InboundReply"})

    revived = Inbox(journal=Journal(path))
    assert revived.restore() == 1
    assert revived.unrevivable == 1
    assert [r.text for r in revived.poll("app-a")] == ["survives"]
    # ...and it is gone from the journal rather than replay-failing every boot.
    assert Inbox(journal=Journal(path)).restore() == 0


def test_an_unrevivable_reply_is_reported_at_healthz_as_a_reason_not_a_number(tmp_path):
    # Rule #5: `status` is computed FROM `reasons`, so a counter nobody turns
    # into words cannot make an operator look.
    from fastapi.testclient import TestClient

    from chat_gateway.service import create_app

    path = tmp_path / "inbox.jsonl"
    Journal(path).open(1, "inbound", {"app": "app-a", "not": "an InboundReply"})
    inbox = Inbox(journal=Journal(path))
    inbox.restore()
    assert inbox.unrevivable == 1

    app = create_app(_registry(), inbox, {"webhook": OkAdapter()})
    body = TestClient(app).get("/healthz").json()
    assert body["inbox"]["unrevivable_at_boot"] == 1
    assert body["status"] == "degraded"
    assert any("no longer parse" in r for r in body["reasons"]), body["reasons"]


def test_restore_honours_max_pending_when_the_cap_was_LOWERED_between_runs(tmp_path):
    # `max_pending` is the memory bound this class advertises, and boot must not
    # be the one path that ignores it. A journal written under a wider cap would
    # otherwise restore straight past the new one.
    path = tmp_path / "inbox.jsonl"
    wide = Inbox(max_pending=5, journal=Journal(path))
    for n in range(5):
        wide.put(_reply(text=f"tap {n}"))

    narrow = Inbox(max_pending=2, journal=Journal(path))
    assert narrow.restore() == 2
    assert [r.text for r in narrow.poll("app-a")] == ["tap 3", "tap 4"]
    # ...and the three it shed are gone from the journal, not waiting for the
    # next boot to blow the cap all over again.
    assert Inbox(max_pending=2, journal=Journal(path)).restore() == 0


def test_a_failed_poll_close_redelivers_rather_than_losing_the_batch(tmp_path):
    # `poll` has already emptied the queue when the close is written. Raising
    # would drop the replies on the floor; counting means they replay.
    path = tmp_path / "inbox.jsonl"

    class BrokenJournal(Journal):
        def close_many(self, entry_ids, status):
            raise OSError("no space left on device")

    first = Inbox(journal=BrokenJournal(path))
    first.put(_reply())
    assert len(first.poll("app-a")) == 1
    assert first.journal_write_errors == 1
    assert Inbox(journal=Journal(path)).restore() == 1


def test_inbox_audit_file_is_owner_only_from_the_first_byte(tmp_path):
    """CG-65: the audit trail holds sender_email and raw; 0644 was the larger
    of the two on-disk exposures ADR-0002 measured."""
    ibx = Inbox(audit_dir=tmp_path / "inbox-data")
    ibx.put(_reply(text="APPROVE synthetic-role-42"))
    audit = next((tmp_path / "inbox-data").glob("*.jsonl"))
    assert_owner_only(audit)
    # and the mode survives a second append rather than being reset
    ibx.put(_reply(text="DECLINE synthetic-role-43"))
    assert_owner_only(audit)


def test_polled_reply_body_is_erased_when_the_inbox_drains(tmp_path):
    # The mirror image of the outbound side: a POLLED reply has no replay
    # value, and a `close` does not erase its body — only compaction does.
    jpath = tmp_path / "inbox.jsonl"
    ibx = Inbox(journal=Journal(jpath))
    ibx.put(_reply(text="APPROVE synthetic-role-42"))
    assert "APPROVE synthetic-role-42" in jpath.read_text(encoding="utf-8")
    ibx.poll("app-a")
    assert jpath.read_text(encoding="utf-8") == ""


def test_polling_one_app_never_erases_another_apps_pending_reply(tmp_path):
    """The one-file trap: compaction is gateway-wide, the poll is per-app.

    There is ONE inbox.jsonl, so compacting because the POLLED app's queue is
    empty would truncate another app's still-pending replies out of existence —
    a silent inbound loss, which is the exact failure the journal was added to
    prevent. The outbound twin has no equivalent trap: `_jobs` is one flat list.
    """
    jpath = tmp_path / "inbox.jsonl"
    ibx = Inbox(journal=Journal(jpath))
    ibx.put(_reply(app="app-a", text="POLLED SOON"))
    ibx.put(_reply(app="app-b", text="STILL PENDING"))
    ibx.poll("app-a")
    assert "STILL PENDING" in jpath.read_text(encoding="utf-8")
    # and it survives a restart
    revived = Inbox(journal=Journal(jpath))
    assert revived.restore() == 1
    assert revived.pending_counts() == {"app-b": 1}


def test_a_failed_poll_close_does_not_let_compaction_erase_the_batch(tmp_path):
    # The inbound half of the same gate as the dispatcher's. `close_many`
    # failing leaves those ids open ON PURPOSE so they replay; a compaction
    # fired on the same drain would delete them instead.
    jpath = tmp_path / "inbox.jsonl"

    class BrokenJournal(Journal):
        def close_many(self, entry_ids, status):
            raise OSError("no space left on device")

    ibx = Inbox(journal=BrokenJournal(jpath))
    ibx.put(_reply(text="REDELIVERED"))
    assert len(ibx.poll("app-a")) == 1
    assert ibx.journal_write_errors == 1
    assert "REDELIVERED" in jpath.read_text(encoding="utf-8")
    assert Inbox(journal=Journal(jpath)).restore() == 1


def test_an_empty_poll_does_not_create_or_truncate_a_journal(tmp_path):
    """Hard rule #6's "nothing reached disk" runs through here.

    A poll that closed nothing has reclaimed nothing, and `compact` writes and
    renames unconditionally — so compacting on an empty poll would create a
    journal file for a gateway that has never queued a reply. An opted-out
    space's suppressed event is exactly that shape.
    """
    jpath = tmp_path / "queue" / "inbox.jsonl"
    ibx = Inbox(journal=Journal(jpath))
    assert ibx.poll("app-a") == []
    assert not jpath.exists()


def test_unrevivable_reply_is_preserved_in_quarantine(tmp_path):
    """CG-65 / ADR-0002 Q6: the gateway keeps the bytes it is holding instead of
    pointing at a file the sweeper may delete."""
    jpath = tmp_path / "inbox.jsonl"
    Journal(jpath).open(1, "inbound", {"app": "app-a", "NOT": "an InboundReply"})
    ibx = Inbox(journal=Journal(jpath), quarantine_dir=tmp_path / "quarantine")
    assert ibx.restore() == 0
    assert ibx.unrevivable == 1 and ibx.quarantined == 1
    qfile = next((tmp_path / "quarantine").glob("unrevivable-*.jsonl"))
    assert "NOT" in qfile.read_text(encoding="utf-8")
    assert_owner_only(qfile)
    assert jpath.read_text(encoding="utf-8") == ""   # journal's own copy is gone, as before


def test_the_quarantine_keeps_the_PAYLOAD_not_just_the_id(tmp_path):
    # The whole point of Q6: the record is already in hand at the drop site, so
    # preserving it costs one append. An id alone would point at nothing.
    jpath = tmp_path / "inbox.jsonl"
    Journal(jpath).open(7, "inbound",
                        {"app": "app-a", "text": "APPROVE synthetic-role-42",
                         "from_a_future_envelope": True})
    ibx = Inbox(journal=Journal(jpath), quarantine_dir=tmp_path / "quarantine")
    ibx.restore()
    preserved = json.loads(
        next((tmp_path / "quarantine").glob("*.jsonl")).read_text(encoding="utf-8"))
    assert preserved["id"] == 7
    assert preserved["payload"]["text"] == "APPROVE synthetic-role-42"


def test_quarantine_is_opt_in_and_absence_is_reported_honestly(tmp_path, capsys):
    jpath = tmp_path / "inbox.jsonl"
    Journal(jpath).open(1, "inbound", {"bad": "record"})
    ibx = Inbox(journal=Journal(jpath))          # no quarantine_dir
    ibx.restore()
    assert ibx.unrevivable == 1 and ibx.quarantined == 0
    assert "NO quarantine copy" in capsys.readouterr().out


def test_a_failed_quarantine_write_is_counted_and_never_stops_a_boot(tmp_path, capsys):
    # A recovery mechanism that has silently stopped working is worse than
    # none, because it is trusted. So: counted, said out loud, boot continues.
    jpath = tmp_path / "inbox.jsonl"
    Journal(jpath).open(1, "inbound", {"bad": "record"})
    blocker = tmp_path / "blocked"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")

    ibx = Inbox(journal=Journal(jpath), quarantine_dir=blocker / "quarantine")
    assert ibx.restore() == 0                    # the boot completed
    assert ibx.unrevivable == 1
    assert (ibx.quarantined, ibx.quarantine_write_errors) == (0, 1)
    out = capsys.readouterr().out
    assert "quarantine write FAILED" in out
    assert "NO quarantine copy" in out


def test_without_a_journal_the_inbox_is_exactly_what_it_was():
    inbox = Inbox()
    inbox.put(_reply())
    assert inbox.restore() == 0
    assert len(inbox.poll("app-a")) == 1
    assert inbox.journal is None


# -- the drain-compaction race (CG-65 pre-merge review, finding H1) ------------
#
# BOTH producers write their journal `open` to disk BEFORE taking the queue
# lock, and that ordering is deliberate on both sides: a job we cannot persist
# must be refused rather than queued, and a tap we cannot persist must not be
# acked. The consequence is that a record can be ON DISK while a drain check is
# reading in-memory state that does not contain it yet. Compacting with an
# ASSERTED empty survivor set then erases work the gateway has already accepted
# — a 202'd alert, or an acked inbound tap.
#
# These two tests drive that interleaving DETERMINISTICALLY, by having the
# terminal journal write itself open a racing record — which is precisely the
# window — rather than racing real threads and hoping to lose.
#
# Both fail if `compact()` is written as `compact([])`.


def test_a_reply_journalled_during_a_poll_survives_the_drain_compaction(tmp_path):
    jpath = tmp_path / "inbox.jsonl"
    journal = Journal(jpath)
    ibx = Inbox(journal=journal)
    ibx.put(_reply(app="app-a", text="POLLED AND DONE"))

    racer = _reply(app="app-b", text="JOURNALLED MID POLL")
    real_close_many = journal.close_many

    def close_many_then_race(ids, status):
        real_close_many(ids, status)
        # `Inbox.put` for app-b reaches exactly here: on disk, not yet in
        # `_pending`, so the drain check has already read "everything empty".
        journal.open(999, "inbound", racer.model_dump(mode="json"))

    journal.close_many = close_many_then_race
    ibx.poll("app-a")

    assert "JOURNALLED MID POLL" in jpath.read_text(encoding="utf-8")
    revived = Inbox(journal=Journal(jpath))
    assert revived.restore() == 1
    assert revived.pending_counts() == {"app-b": 1}


def test_a_job_journalled_during_a_finish_survives_the_drain_compaction(tmp_path):
    reg = _registry()
    jpath = tmp_path / "delivery.jsonl"
    journal = Journal(jpath)
    d = Dispatcher({"webhook": OkAdapter()}, DeliveryLog(), journal=journal)
    d.enqueue("app-a", "notify", reg.identities["ident-a"],
              _message("DELIVERED AND DONE"), "done")

    real_close = journal.close

    def close_then_race(entry_id, status):
        real_close(entry_id, status)
        # `Dispatcher.enqueue` for a second job reaches exactly here.
        journal.open(999, "notify", {
            "source": "app-a", "kind": "notify", "identity": "ident-a",
            "title": "racer",
            "message": _message("ENQUEUED MID FINISH").model_dump(mode="json"),
        })

    journal.close = close_then_race
    d.process_due()

    assert d.pending() == 0                       # the first job really drained
    assert "ENQUEUED MID FINISH" in jpath.read_text(encoding="utf-8")
    revived = Dispatcher({"webhook": OkAdapter()}, DeliveryLog(), journal=Journal(jpath))
    assert revived.restore(reg) == (1, 0)


# --------------------------------------------------------------------------
# CG-75: the audit write that used to raise out of `_finish`
#
# `DeliveryLog.record` did a raw `mkdir`/`open`/`write` with no guard, on the
# delivery hot path. The exception escaped `_finish` BEFORE the job left
# `_jobs`, and the delivered path never advances `next_attempt_at` — so the
# next pass sent the same message again, one second later, forever. Measured
# before the fix: one enqueued notification, one successful send, SIXTY sends
# to Google in sixty passes.
#
# The failure is injected with REAL mode bits rather than a monkeypatched
# `Path.mkdir`, so what is exercised is the real method meeting a real kernel
# refusal. `ENOSPC` and `EACCES` reach `record` identically — both are an
# `OSError` out of `mkdir`/`open` — so an unwritable parent is a faithful
# stand-in for the full disk that cannot be staged in a unit test.
#
# TWO injection helpers, and picking the wrong one is how these tests stopped
# reproducing the defect once already. `_unwritable_audit_dir` breaks the path
# BEFORE any `DeliveryLog` exists — the right shape for `record` in isolation
# and for the enqueue-refuses case. `_break_audit_dir` breaks an audit dir that
# is already populated, which is the only way to reach the storm, because the
# disk has to fill AFTER the enqueue that the storm re-sends.
# --------------------------------------------------------------------------

@contextlib.contextmanager
def _unwritable_audit_dir(tmp_path):
    """Yield an audit_dir whose every write really fails, and restore the mode.

    The directory itself is deliberately NOT created: an existing directory
    inside an unwritable parent still satisfies `mkdir(parents=True,
    exist_ok=True)` — measured — so only the missing-dir case actually refuses.

    Restored in a `finally` so pytest can clean `tmp_path` up.
    """
    if sys.platform == "win32":  # pragma: no cover - POSIX mode bits
        pytest.skip("POSIX mode bits; a Windows ACL is a different mechanism")
    if os.getuid() == 0:  # pragma: no cover - root ignores the mode bits
        pytest.skip("running as root — an unwritable directory does not bite")
    parent = tmp_path / "state"
    parent.mkdir()
    os.chmod(parent, stat.S_IRUSR | stat.S_IXUSR)
    try:
        yield parent / "deliveries"
    finally:
        os.chmod(parent, stat.S_IRWXU)


@contextlib.contextmanager
def _break_audit_dir(audit_dir: Path):
    """Make an ALREADY-POPULATED audit dir refuse every further write.

    The sibling above cannot serve the storm tests. It breaks the path before
    the `DeliveryLog` is even constructed, and `Dispatcher.enqueue`'s very first
    statement is `self._log.record(...)` — so on PRE-FIX code those tests raised
    out of `enqueue` and never reached a single `process_due`. Red, but for the
    wrong reason. The CG-75 sequence needs the enqueue to succeed first: one
    accepted job, one successful send, and only THEN a disk that will not take
    the record.

    Why the day FILE is chmodded and not only the directory — measured, not
    assumed: `Path.mkdir(parents=True, exist_ok=True)` on an EXISTING directory
    does not raise even inside an unwritable parent, because CPython returns
    early when `exist_ok and self.is_dir()` and swallows the EACCES. That is the
    same measurement that made the sibling leave its directory uncreated, and
    here the directory necessarily exists — the enqueue made it. So the refusal
    has to come from `record`'s `path.open("a")` on a read-only day file. The
    directory's own `r-x` is the second half: it stops a NEW day file from being
    created, so a UTC date roll mid-test cannot quietly restore writability
    (`record` names its file after `_utcnow()`, not after the injected clock).

    Both modes are restored in a `finally` so pytest can clean `tmp_path` up.
    """
    if sys.platform == "win32":  # pragma: no cover - POSIX mode bits
        pytest.skip("POSIX mode bits; a Windows ACL is a different mechanism")
    if os.getuid() == 0:  # pragma: no cover - root ignores the mode bits
        pytest.skip("running as root — an unwritable directory does not bite")
    day_files = sorted(audit_dir.iterdir())
    assert day_files, "nothing to break: the enqueue wrote no day file"
    for day_file in day_files:
        os.chmod(day_file, stat.S_IRUSR)              # 0400: open("a") raises
    os.chmod(audit_dir, stat.S_IRUSR | stat.S_IXUSR)  # r-x: no new day file either
    try:
        yield audit_dir
    finally:
        os.chmod(audit_dir, stat.S_IRWXU)
        for day_file in day_files:
            os.chmod(day_file, stat.S_IRUSR | stat.S_IWUSR)


class CountingBoomAdapter(BoomAdapter):
    """`BoomAdapter`, but it says how many times it was asked.

    The retry-ladder test needs the count of ATTEMPTS, and a failing adapter
    has no `sent` list to measure it with.
    """

    def __init__(self):
        self.attempts = 0

    def send(self, identity, message):
        self.attempts += 1
        super().send(identity, message)


class _Clock:
    """An injected clock, so a 72.5-minute backoff ladder costs no wall time."""

    def __init__(self, start: dt.datetime):
        self.now = start

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += dt.timedelta(seconds=seconds)


def test_a_failing_audit_write_does_not_raise_out_of_record(tmp_path):
    with _unwritable_audit_dir(tmp_path) as audit_dir:
        log = DeliveryLog(audit_dir=audit_dir)
        entry_id = log.record("app-a", "notify", "SYNTHETIC TITLE", "delivered")
    assert isinstance(entry_id, int)
    assert log.audit_write_errors == 1


def test_a_failing_audit_write_still_populates_the_in_memory_ring(tmp_path):
    """The whole reason swallowing is cheap: the answer survives, the file does not.

    The guard sits around the FILE half only, below the ring-buffer append, so
    `query()` — and therefore `GET /v1/deliveries` — still answers "did this
    alert reach Chat?" for the life of the process.
    """
    with _unwritable_audit_dir(tmp_path) as audit_dir:
        log = DeliveryLog(audit_dir=audit_dir)
        log.record("app-a", "notify", "close-of-day", "delivered")
    entries = log.query("app-a")
    assert len(entries) == 1 and entries[0]["status"] == "delivered"
    assert log.audit_write_errors == 1


def test_a_failing_audit_write_does_not_resend_the_job(tmp_path):
    """CG-75, the whole row. Pre-fix this was 60 sends in 60 passes — measured.

    One enqueued notification, one successful send, and an audit trail that
    cannot be written. Every subsequent pass must send NOTHING.

    THE ORDERING IS THE TEST, and it is not incidental: the `enqueue` happens
    while the audit dir is still writable, and only then does the disk fill.
    An audit dir broken from the start raised out of `enqueue`'s own opening
    `record(...)` on pre-fix code, so the job was never accepted, `process_due`
    was never reached, and the storm this row exists to stop was never
    exercised. That version of this test went red — for the wrong reason.

    What the pre-fix red looks like HERE is the raise escaping `_finish` on the
    FIRST pass, not sixty sends: the sixty are what a caller that catches
    per-pass sees, and `Dispatcher._run` is exactly such a caller (it prints
    `dispatcher: pass error (will retry)` and goes round again a second later).
    Calling `process_due` directly surfaces the escape itself, which is the same
    defect one frame earlier.
    """
    reg = _registry()
    ok = OkAdapter()
    clock = _Clock(dt.datetime(2026, 8, 3, tzinfo=dt.timezone.utc))
    audit_dir = tmp_path / "deliveries"
    log = DeliveryLog(audit_dir=audit_dir)
    d = Dispatcher({"webhook": ok}, log, now_fn=clock)
    d.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    assert log.audit_write_errors == 0, "the enqueue's own audit write must succeed"
    with _break_audit_dir(audit_dir):
        for _ in range(60):
            d.process_due()               # must not raise
            clock.advance(1)

    assert len(ok.sent) == 1, "the delivered job was re-sent"
    assert d.pending() == 0, "the job never left _jobs"
    assert log.audit_write_errors >= 1
    assert d.last_pass_at is not None, "a raising pass never stamps"


def test_a_failing_audit_write_on_the_retry_path_keeps_the_backoff(tmp_path):
    """The other half of the measurement: the ladder must still be the ladder.

    Pre-fix this path did not storm for the whole 72.5 minutes of `BACKOFF_S`
    and then degenerated into the delivered path's one-per-second storm. Now
    the send count over the whole ladder is exactly the ladder.

    Same ordering as its delivered-path twin above, for the same reason: the
    enqueue must be ACCEPTED before the disk fills, or nothing ever reaches the
    retry branch whose `record("retrying", ...)` is the write under test.
    """
    reg = _registry()
    adapter = CountingBoomAdapter()
    clock = _Clock(dt.datetime(2026, 8, 3, tzinfo=dt.timezone.utc))
    audit_dir = tmp_path / "deliveries"
    log = DeliveryLog(audit_dir=audit_dir)
    d = Dispatcher({"webhook": adapter}, log, now_fn=clock)
    d.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    assert log.audit_write_errors == 0, "the enqueue's own audit write must succeed"
    with _break_audit_dir(audit_dir):
        for _ in range(6000):
            d.process_due()
            clock.advance(1)

    assert adapter.attempts == len(BACKOFF_S), (
        f"expected exactly {len(BACKOFF_S)} attempts, got {adapter.attempts}")
    assert d.pending() == 0
    assert log.audit_write_errors >= 1


def test_enqueue_still_refuses_work_it_cannot_journal(tmp_path):
    """The guard must NOT have relaxed the refuse-the-work posture.

    Distinct from `test_a_failed_enqueue_write_refuses_the_job_rather_than_
    pretending` above, which predates CG-75: here the audit write ALSO fails,
    which is the realistic full-disk shape and the case where a swallow could
    plausibly mask the journal's raise. It must not. Refusing belongs to the
    DURABILITY mechanism, not to the audit trail — the consumer's 5xx is what
    hands the alert back to its own fallback log (the aitrader contract).
    """
    reg = _registry()

    class BrokenJournal(Journal):
        def open(self, entry_id, kind, payload):
            raise OSError(28, "No space left on device")

    with _unwritable_audit_dir(tmp_path) as audit_dir:
        d = Dispatcher({"webhook": OkAdapter()}, DeliveryLog(audit_dir=audit_dir),
                       journal=BrokenJournal(tmp_path / "delivery.jsonl"))
        with pytest.raises(OSError):
            d.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    assert d.pending() == 0
