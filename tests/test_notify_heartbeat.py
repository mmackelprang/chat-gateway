"""The aitrader contract's acceptance criteria, as deterministic tests:
severity routing/rendering, dedupe collapse, dead-man weekday logic with no
weekend false alarms, and full delivery-log accounting."""

import datetime as dt
import json
import time

import pytest
from fastapi.testclient import TestClient

from chat_gateway import delivery as delivery_module
from chat_gateway.delivery import DeliveryLog, Dispatcher
from chat_gateway.envelope import TEXT_MAX, DeliveryResult
from chat_gateway.heartbeat import (
    HeartbeatError,
    HeartbeatMonitor,
    HeartbeatStore,
    parse_schedule,
)
from chat_gateway.inbox import Inbox
from chat_gateway.notifications import (
    INFO_BODY_SEPARATOR,
    Deduper,
    Notification,
    dedupe_counter,
    info_max_combined_length,
    render,
    severity_prefix,
)
from chat_gateway.registry import load_registry
from chat_gateway.service import create_app

UTC = dt.timezone.utc

REGISTRY_YAML = """
identities:
  aitrader-alerts:
    display: "aitrader"
    mode: webhook
    webhook_url_env: T_HOOK_ALERTS
  aitrader-reports:
    display: "aitrader reports"
    mode: webhook
    webhook_url_env: T_HOOK_REPORTS
apps:
  aitrader:
    key_env: T_KEY_AITRADER
    identities: [aitrader-alerts, aitrader-reports]
    allow_inbound: false
    routes: {alert: aitrader-alerts, warning: aitrader-reports, info: aitrader-reports}
"""


class Clock:
    def __init__(self, start: dt.datetime):
        self.now = start

    def __call__(self) -> dt.datetime:
        return self.now


class FakeAdapter:
    def __init__(self, fail_times: int = 0):
        self.sent = []
        self.fail_times = fail_times

    def send(self, identity, message):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("chat unreachable")
        self.sent.append((identity.name, message))
        return DeliveryResult(status="delivered", channel="google_chat",
                              identity=identity.name, mode=identity.mode)


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    monkeypatch.setenv("T_KEY_AITRADER", "cgk_trader")
    monkeypatch.setenv("T_HOOK_ALERTS", "https://x.example/alerts")
    monkeypatch.setenv("T_HOOK_REPORTS", "https://x.example/reports")
    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    return load_registry(p)


def make_client(registry, clock, tmp_path, adapter=None, log=None):
    adapter = adapter or FakeAdapter()
    log = log or DeliveryLog()
    dispatcher = Dispatcher({"webhook": adapter}, log, now_fn=clock)
    app = create_app(
        registry, Inbox(), {"webhook": adapter},
        delivery_log=log, dispatcher=dispatcher,
        deduper=Deduper(window_seconds=3600, now_fn=clock),
        heartbeats=HeartbeatStore(tmp_path / "hb.json", now_fn=clock),
    )
    return TestClient(app), app, adapter


AUTH = {"Authorization": "Bearer cgk_trader"}


# --- routing + rendering -----------------------------------------------------

def test_severity_routing_and_rendering(registry, tmp_path):
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    client, app, adapter = make_client(registry, clock, tmp_path)

    r = client.post("/v1/notify", headers=AUTH, json={
        "severity": "alert", "title": "HALT: drawdown breaker",
        "body": "Circuit open.", "action": "Check the guardrails proxy on the dev box"})
    assert r.status_code == 202 and r.json()["status"] == "enqueued"
    r2 = client.post("/v1/notify", headers=AUTH, json={
        "severity": "info", "title": "weekly report posted"})
    assert r2.status_code == 202

    app.state.dispatcher.process_due()
    (ident1, msg1), (ident2, msg2) = adapter.sent
    assert ident1 == "aitrader-alerts" and ident2 == "aitrader-reports"
    assert msg1.cards and "⚠️🔴" in msg1.text and "[ALERT]" in msg1.text
    widgets = msg1.cards[0]["card"]["sections"][0]["widgets"]
    assert any(w.get("decoratedText", {}).get("topLabel") == "What to do" for w in widgets)
    assert not msg2.cards and msg2.text.startswith("ℹ️ [INFO]")


def test_missing_route_is_503(registry, tmp_path):
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    client, _, _ = make_client(registry, clock, tmp_path)
    # registry has no 'default' and we remove alert route via a fresh registry
    bad_yaml = REGISTRY_YAML.replace("routes: {alert: aitrader-alerts, warning: aitrader-reports, info: aitrader-reports}",
                                     "routes: {info: aitrader-reports}")
    p = registry  # keep fixture signature simple; build inline instead
    import chat_gateway.registry as regmod
    from pathlib import Path
    tmp = Path(str(tmp_path)) / "bad.yaml"
    tmp.write_text(bad_yaml, encoding="utf-8")
    bad_registry = regmod.load_registry(tmp)
    client2, _, _ = make_client(bad_registry, clock, tmp_path)
    r = client2.post("/v1/notify", headers=AUTH, json={"severity": "alert", "title": "x"})
    assert r.status_code == 503 and "no notify route" in r.json()["detail"]


# --- the info path's plain-text budget (CG-30) -------------------------------
#
# Boundaries are DERIVED from info_max_combined_length(), never written down as
# 3989: the prefix length is not a number anyone should hardcode (the info emoji
# alone is two code points), and a test carrying its own copy of the bound would
# stop catching drift the moment the prefix changed.

def _info_payload(combined: int) -> dict:
    """An info notification whose len(title) + len(body) is exactly `combined`,
    split so each field stays well inside its OWN max_length."""
    title = "t" * 200
    return {"severity": "info", "title": title, "body": "b" * (combined - len(title))}


def test_info_at_the_combined_limit_is_accepted(registry, tmp_path):
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    client, app, adapter = make_client(registry, clock, tmp_path)

    r = client.post("/v1/notify", headers=AUTH, json=_info_payload(info_max_combined_length()))
    assert r.status_code == 202

    app.state.dispatcher.process_due()
    (_, msg), = adapter.sent
    assert not msg.cards and len(msg.text) == TEXT_MAX  # the budget is exact, not slack


def test_info_one_over_the_limit_is_422_naming_the_limit_not_500(registry, tmp_path):
    """The whole point of CG-30: this range used to raise inside render() and
    surface as an uncaught 500. raise_server_exceptions=False so a regression
    shows up as a 500 response rather than blowing up the test itself."""
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    _, app, _ = make_client(registry, clock, tmp_path)
    client = TestClient(app, raise_server_exceptions=False)

    limit = info_max_combined_length()
    r = client.post("/v1/notify", headers=AUTH, json=_info_payload(limit + 1))
    assert r.status_code != 500
    assert r.status_code == 422
    detail = str(r.json()["detail"])
    assert str(limit) in detail        # the caller is told the limit ...
    assert str(limit + 1) in detail    # ... and the size they sent
    assert str(TEXT_MAX) in detail


def test_alert_and_warning_full_length_bodies_stay_accepted(registry, tmp_path):
    """Regression guard against 'simplifying' CG-30's fix into a global
    Notification.body limit.

    A title-200 + body-4000 alert or warning (4200 combined — well over the info
    path's budget) is ACCEPTED today, because those severities put the body in a
    card widget and only a short fallback line goes through the envelope's text
    field. Lowering body's max_length would be the obvious one-line fix and it
    would start rejecting these. They must stay accepted."""
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    client, app, adapter = make_client(registry, clock, tmp_path)

    over_the_info_budget = 200 + 4000
    assert over_the_info_budget > info_max_combined_length()
    for severity in ("alert", "warning"):
        r = client.post("/v1/notify", headers=AUTH, json={
            "severity": severity, "title": "t" * 200, "body": "b" * 4000,
            "dedupe_key": None})
        assert r.status_code == 202, (severity, r.status_code, r.text)

    app.state.dispatcher.process_due()
    assert len(adapter.sent) == 2
    assert all(msg.cards for _, msg in adapter.sent)


def test_guard_and_renderer_share_one_prefix_construction():
    """severity_prefix() must be what render() actually emits — otherwise the
    budget above would be derived from a string the renderer no longer uses."""
    msg = render(Notification(severity="info", title="x", body="y"), "aitrader")
    assert msg.text.startswith(severity_prefix("info") + "x")
    assert msg.text == severity_prefix("info") + "x" + INFO_BODY_SEPARATOR + "y"


# --- the dedupe counter yields to the app's content (CG-32) ------------------
#
# Same derivation discipline as the CG-30 block above: every boundary here comes
# from info_max_combined_length(), severity_prefix(), or the counter's own
# rendered strings. The ONE deliberate exception is
# test_the_accepted_bound_did_not_move, which pins the literal 3989 on purpose —
# see its docstring.

def _deduped_info_payload(combined: int, dedupe_key: str = "weekly-report") -> dict:
    """`_info_payload` plus a dedupe_key, so repeats collapse and the next
    delivered message carries a count."""
    return {**_info_payload(combined), "dedupe_key": dedupe_key}


def test_deduped_redelivery_at_the_limit_is_202_not_500(registry, tmp_path):
    """CG-32's measured sequence, which used to end 202 / 202 / 202 / **500**.

    A payload accepted at exactly info_max_combined_length() was rendered again
    after the window reopened, this time with " (×3 since last notice)" appended
    — 23 characters past a budget that was already exact — and the resulting
    pydantic ValidationError fired inside the endpoint with nothing to catch it.
    Step 4 is the one that used to be an uncaught 500.

    raise_server_exceptions=False so a regression shows up as a 500 *response*
    rather than blowing up the test itself."""
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    _, app, adapter = make_client(registry, clock, tmp_path)
    client = TestClient(app, raise_server_exceptions=False)

    payload = _deduped_info_payload(info_max_combined_length())

    r1 = client.post("/v1/notify", headers=AUTH, json=payload)
    assert r1.status_code == 202 and r1.json()["status"] == "enqueued"
    assert r1.json()["occurrences"] == 1

    r2 = client.post("/v1/notify", headers=AUTH, json=payload)
    assert r2.status_code == 202 and r2.json() == {"status": "deduped", "occurrences": 1}

    r3 = client.post("/v1/notify", headers=AUTH, json=payload)
    assert r3.status_code == 202 and r3.json() == {"status": "deduped", "occurrences": 2}

    clock.now += dt.timedelta(seconds=3601)  # the window reopens
    r4 = client.post("/v1/notify", headers=AUTH, json=payload)
    assert r4.status_code != 500, r4.text
    assert r4.status_code == 202
    assert r4.json()["occurrences"] == 3  # the count that used to overflow

    # and it really rendered — the 202 is not the whole claim
    app.state.dispatcher.process_due()
    assert len(adapter.sent) == 2
    _, msg = adapter.sent[-1]
    assert len(msg.text) <= TEXT_MAX


def test_the_apps_body_survives_when_the_counter_is_dropped(registry, tmp_path):
    """Hard rule #1: the counter is gateway-generated transport decoration, the
    body is the application's content — so the counter is what yields.

    Nothing of what the caller sent may be truncated to make room for the
    gateway's own parenthetical accounting."""
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    _, app, adapter = make_client(registry, clock, tmp_path)
    client = TestClient(app, raise_server_exceptions=False)

    payload = _deduped_info_payload(info_max_combined_length())
    for _ in range(3):
        assert client.post("/v1/notify", headers=AUTH, json=payload).status_code == 202
    clock.now += dt.timedelta(seconds=3601)
    assert client.post("/v1/notify", headers=AUTH, json=payload).status_code == 202

    app.state.dispatcher.process_due()
    _, msg = adapter.sent[-1]
    assert payload["body"] in msg.text                      # body intact, not clipped
    assert payload["title"] in msg.text                     # title too
    assert msg.text == (severity_prefix("info") + payload["title"]
                        + INFO_BODY_SEPARATOR + payload["body"])
    assert len(msg.text) == TEXT_MAX                        # exactly full: no room left
    assert "since last notice" not in msg.text              # the counter is what went


def test_counter_degrades_full_then_short_then_gone():
    """The three forms, driven directly at boundaries derived from the strings
    themselves rather than from counted characters."""
    full = " (×7 since last notice)"
    short = " (×7)"
    assert dedupe_counter(7, None) == full                 # unbounded -> full form
    assert dedupe_counter(7, len(full)) == full            # exactly enough -> full
    assert dedupe_counter(7, len(full) - 1) == short       # one short -> shorten
    assert dedupe_counter(7, len(short)) == short          # exactly enough -> short
    assert dedupe_counter(7, len(short) - 1) == ""         # one short -> drop
    assert dedupe_counter(7, 0) == ""                      # no room at all -> drop

    # a first occurrence has no count to carry, at any room
    for room in (None, 0, len(short), len(full), 10_000):
        assert dedupe_counter(1, room) == ""


def test_counter_width_is_measured_not_assumed():
    """`×3` and `×10000` are different lengths, so the room calculation must come
    from the rendered string — a fixed-width reservation would be wrong the first
    time a count reached four digits."""
    assert len(dedupe_counter(10_000, None)) > len(dedupe_counter(3, None))

    # a room where the narrow count still gets the full form and the wide one
    # has already been pushed down to the short form — computed, not written down
    room = len(dedupe_counter(3, None))
    assert dedupe_counter(3, room) == dedupe_counter(3, None) == " (×3 since last notice)"
    assert dedupe_counter(10_000, room) == " (×10000)"


def test_the_accepted_bound_did_not_move(registry, tmp_path):
    """CG-32 fixed the renderer, NOT the request-time bound — and this test pins
    the actual number to prove it.

    The literal 3989 is deliberate here and only here: every other boundary in
    this block is derived, but a derivation assert alone would happily follow the
    bound downwards if someone later reserved counter width in
    info_max_combined_length(). That reservation is exactly what option 1
    rejected, because it would shrink the accepted length of every info
    notification including the ones with no dedupe_key that can never grow a
    counter."""
    assert info_max_combined_length() == (
        TEXT_MAX - len(severity_prefix("info")) - len(INFO_BODY_SEPARATOR))
    assert info_max_combined_length() == 3989

    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    _, app, _ = make_client(registry, clock, tmp_path)
    client = TestClient(app, raise_server_exceptions=False)

    limit = info_max_combined_length()
    assert client.post("/v1/notify", headers=AUTH,
                       json=_info_payload(limit)).status_code == 202     # still accepted
    assert client.post("/v1/notify", headers=AUTH,
                       json=_info_payload(limit + 1)).status_code == 422  # CG-30 intact


def test_a_dropped_counter_is_still_recoverable_from_the_delivery_log(
        registry, tmp_path):
    """The claim option 1 rests on: dropping the counter loses the DECORATION,
    not the COUNT. Pinned here rather than left in a review note, because it is
    the whole reason degrading is acceptable instead of merely convenient.

    Two stores with different retention, and the test exercises both:
    `GET /v1/deliveries` reads an in-memory ring buffer that evicts (`keep` is
    200 per source in production; shrunk here so eviction is actually reached),
    while the JSONL mirror `__main__` configures is append-only and complete.
    Eviction is the benign direction — the ordinal a dropped counter would have
    shown is the highest one, so it is the newest entry, the last a ring buffer
    discards."""
    keep = 10
    suppressed = keep * 2 + 5           # deep enough that the ring buffer evicts
    audit_dir = tmp_path / "deliveries"
    log = DeliveryLog(audit_dir=audit_dir, keep=keep)
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    client, app, adapter = make_client(registry, clock, tmp_path, log=log)

    payload = _deduped_info_payload(info_max_combined_length())
    assert client.post("/v1/notify", headers=AUTH, json=payload).status_code == 202
    for _ in range(suppressed):
        assert client.post("/v1/notify", headers=AUTH, json=payload).status_code == 202
    clock.now += dt.timedelta(seconds=3601)
    r = client.post("/v1/notify", headers=AUTH, json=payload)
    assert r.status_code == 202 and r.json()["occurrences"] == suppressed + 1

    # the message itself carries no counter — there was no room for one
    app.state.dispatcher.process_due()
    _, msg = adapter.sent[-1]
    assert "(×" not in msg.text and len(msg.text) == TEXT_MAX

    # ... but the count is right there in the log the docstring points at
    api = client.get("/v1/deliveries?limit=200", headers=AUTH).json()["deliveries"]
    assert len(api) == keep                                  # it really did evict
    visible = [e["detail"] for e in api if e["status"] == "deduped"]
    assert visible[-1] == f"occurrence {suppressed} within window"   # newest survives
    assert "occurrence 1 within window" not in visible               # oldest did not

    lines = [ln for f in sorted(audit_dir.glob("*.jsonl"))
             for ln in f.read_text(encoding="utf-8").splitlines()]
    ordinals = [json.loads(ln)["detail"] for ln in lines
                if json.loads(ln)["status"] == "deduped"]
    assert len(ordinals) == suppressed                       # every one, durably
    assert ordinals[0] == "occurrence 1 within window"
    assert ordinals[-1] == f"occurrence {suppressed} within window"


def test_card_severities_keep_the_full_counter():
    """Degradation is the info path's business only. A card severity's `text` is
    the prefix plus a title capped at 200, thousands of characters clear of
    TEXT_MAX, so its counter never has to give anything up — in the text line or
    in the card header."""
    full = " (×4 since last notice)"
    for severity in ("alert", "warning"):
        msg = render(Notification(severity=severity, title="t" * 200, body="b" * 4000),
                     "aitrader", 4)
        assert msg.text.endswith(full)
        assert full in msg.cards[0]["card"]["header"]["title"]
        assert len(msg.text) <= TEXT_MAX


# --- dedupe (acceptance #2) --------------------------------------------------

def test_dedupe_ten_fires_one_message(registry, tmp_path):
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    client, app, adapter = make_client(registry, clock, tmp_path)

    for i in range(10):
        r = client.post("/v1/notify", headers=AUTH, json={
            "severity": "alert", "title": "HALT still active", "dedupe_key": "halt-1"})
        assert r.status_code == 202
        clock.now += dt.timedelta(minutes=1)
    app.state.dispatcher.process_due()
    assert len(adapter.sent) == 1  # one message despite ten fires

    # window reopens -> next fire delivers and carries the collapsed count
    clock.now += dt.timedelta(hours=1)
    client.post("/v1/notify", headers=AUTH, json={
        "severity": "alert", "title": "HALT still active", "dedupe_key": "halt-1"})
    app.state.dispatcher.process_due()
    assert len(adapter.sent) == 2
    assert "×10 since last notice" in adapter.sent[1][1].text

    log = app.state.delivery_log.query("aitrader", limit=50)
    assert sum(1 for e in log if e["status"] == "deduped") == 9
    assert sum(1 for e in log if e["status"] == "delivered") == 2


# --- dispatcher retries + accounting (acceptance #4) -------------------------

def test_dispatcher_retries_then_delivers_and_log_accounts(registry, tmp_path):
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    adapter = FakeAdapter(fail_times=2)
    client, app, _ = make_client(registry, clock, tmp_path, adapter)
    client.post("/v1/notify", headers=AUTH, json={"severity": "alert", "title": "flaky"})

    assert app.state.dispatcher.process_due() == 1 and not adapter.sent      # attempt 1 fails
    clock.now += dt.timedelta(seconds=31)
    assert app.state.dispatcher.process_due() == 1 and not adapter.sent      # attempt 2 fails
    clock.now += dt.timedelta(seconds=121)
    assert app.state.dispatcher.process_due() == 1 and len(adapter.sent) == 1  # attempt 3 delivers

    statuses = [e["status"] for e in app.state.delivery_log.query("aitrader")]
    assert statuses == ["enqueued", "retrying", "retrying", "delivered"]
    assert app.state.dispatcher.pending() == 0


def test_dispatcher_gives_up_after_backoff_exhausted(registry, tmp_path):
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    adapter = FakeAdapter(fail_times=99)
    client, app, _ = make_client(registry, clock, tmp_path, adapter)
    client.post("/v1/notify", headers=AUTH, json={"severity": "alert", "title": "down"})
    for _ in range(6):
        app.state.dispatcher.process_due()
        clock.now += dt.timedelta(hours=2)
    log = app.state.delivery_log.query("aitrader")
    assert log[-1]["status"] == "failed" and "gave up" in log[-1]["detail"]
    assert app.state.dispatcher.pending() == 0


# --- heartbeat / dead-man (acceptance #3) ------------------------------------

def test_schedule_parsing():
    assert parse_schedule("weekdays") == ("weekdays", 86400)
    assert parse_schedule("every:30m") == ("every", 1800)
    with pytest.raises(HeartbeatError):
        parse_schedule("fortnightly")


def test_weekday_deadman_no_weekend_false_alarm(registry, tmp_path):
    # Friday 2026-07-24 16:30 ET == 20:30 UTC (EDT)
    clock = Clock(dt.datetime(2026, 7, 24, 20, 30, tzinfo=UTC))
    client, app, adapter = make_client(registry, clock, tmp_path)
    r = client.post("/v1/heartbeat", headers=AUTH, json={
        "check_id": "daily-run", "schedule": "weekdays", "grace": "2h"})
    assert r.status_code == 200
    # deadline rolls over the weekend: Monday 16:30 ET + 2h grace = 22:30 UTC
    assert r.json()["next_deadline"].startswith("2026-07-27T22:30")

    # Saturday + Sunday scans: silence is fine
    clock.now = dt.datetime(2026, 7, 25, 20, 0, tzinfo=UTC)
    assert app.state.monitor.scan_once() == 0
    clock.now = dt.datetime(2026, 7, 26, 20, 0, tzinfo=UTC)
    assert app.state.monitor.scan_once() == 0
    # Monday before the grace deadline: still fine
    clock.now = dt.datetime(2026, 7, 27, 21, 0, tzinfo=UTC)  # 17:00 ET
    assert app.state.monitor.scan_once() == 0
    # Monday past 18:30 ET: exactly one alert
    clock.now = dt.datetime(2026, 7, 27, 23, 0, tzinfo=UTC)
    assert app.state.monitor.scan_once() == 1
    app.state.dispatcher.process_due()
    assert len(adapter.sent) == 1
    ident, msg = adapter.sent[0]
    assert ident == "aitrader-alerts" and "heartbeat missed: daily-run" in msg.text
    # repeat suppressed within the daily backoff...
    clock.now += dt.timedelta(minutes=30)
    assert app.state.monitor.scan_once() == 0
    # ...and fires again a day later
    clock.now += dt.timedelta(days=1)
    assert app.state.monitor.scan_once() == 1

    # refresh clears it
    r = client.post("/v1/heartbeat", headers=AUTH, json={
        "check_id": "daily-run", "schedule": "weekdays", "grace": "2h"})
    assert r.status_code == 200
    assert app.state.monitor.scan_once() == 0
    state = client.get("/v1/heartbeat/aitrader", headers=AUTH).json()
    assert state["checks"][0]["status"] == "ok"


def test_heartbeat_every_interval_and_delete(registry, tmp_path):
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    client, app, _ = make_client(registry, clock, tmp_path)
    client.post("/v1/heartbeat", headers=AUTH, json={
        "check_id": "loop", "schedule": "every:30m", "grace": "5m"})
    clock.now += dt.timedelta(minutes=34)
    assert app.state.monitor.scan_once() == 0
    clock.now += dt.timedelta(minutes=2)
    assert app.state.monitor.scan_once() == 1
    r = client.delete("/v1/heartbeat/aitrader/loop", headers=AUTH)
    assert r.status_code == 200
    assert client.get("/v1/heartbeat/aitrader", headers=AUTH).json()["checks"] == []
    assert client.delete("/v1/heartbeat/aitrader/loop", headers=AUTH).status_code == 404


def test_heartbeat_persistence_across_restart(registry, tmp_path):
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    store = HeartbeatStore(tmp_path / "hb.json", now_fn=clock)
    store.refresh("aitrader", "daily-run", "weekdays", "2h")
    store2 = HeartbeatStore(tmp_path / "hb.json", now_fn=clock)
    assert [c.check_id for c in store2.list_for("aitrader")] == ["daily-run"]


# --- enforcement of the no-inbound contract + scoping ------------------------

def test_no_inbound_control_path_enforced(registry, tmp_path):
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    client, _, _ = make_client(registry, clock, tmp_path)
    r = client.get("/v1/inbox", headers=AUTH)
    assert r.status_code == 403
    assert "no-inbound-control" in r.json()["detail"]


def test_heartbeat_source_scoping(registry, tmp_path):
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    client, _, _ = make_client(registry, clock, tmp_path)
    assert client.get("/v1/heartbeat/other-app", headers=AUTH).status_code == 403
    assert client.delete("/v1/heartbeat/other-app/x", headers=AUTH).status_code == 403


# --- CG-74: the failure counters the two loop threads never had --------------
#
# These three drive a REAL loop thread, which nothing in `test_service.py` does
# for the counters: that file stubs liveness so it can pin an exact `/healthz`
# body, and a live `_run` would clear `consecutive_*` under the assertion. The
# increment-and-clear mechanism therefore has to be proven here, against the
# actual `while` loop, or it is only ever proven by assignment.

def _wait_until(predicate, timeout=5.0, what="condition"):
    """Poll `predicate` until true, or fail after `timeout` seconds.

    Module-local rather than in `conftest.py`: this cluster is the only place in
    the suite that watches a loop thread make progress, and a shared fixture
    with one caller is a dependency nobody pays for.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}")


def test_a_raising_pass_is_counted_and_cleared_on_recovery(monkeypatch):
    """Two raises then recovery: history keeps 2, the live signal returns to 0."""
    # `PASS_INTERVAL_S` is a module constant read by `_run` on every iteration,
    # not a per-instance setting, so this is the only way to run four passes
    # without spending four seconds of suite time on a timing assertion that
    # does not depend on the interval.
    monkeypatch.setattr(delivery_module, "PASS_INTERVAL_S", 0.01)
    d = Dispatcher({}, DeliveryLog())
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError(28, "No space left on device")
        return 0

    d.process_due = flaky
    d.start()
    try:
        _wait_until(lambda: calls["n"] >= 4, what="four dispatch passes")
    finally:
        d.stop()
    assert d.pass_failures == 2
    assert d.consecutive_pass_failures == 0, "recovery must clear the consecutive counter"
    assert d.last_pass_error is None, "recovery must clear the error string"


def test_the_pass_error_is_a_type_name_never_a_path(tmp_path, monkeypatch):
    """Hard rule #2: `str(OSError)` embeds the absolute path; this must not.

    `OSError` is deliberately NOT marked in `errors.py`, so `describe_exception`
    renders it by type alone. That is lossy on purpose — the operator loses
    `ENOSPC` vs `EACCES` — and the thing it buys is this: `/healthz` is
    unauthenticated, and a state-dir path is not something it may publish.
    """
    monkeypatch.setattr(delivery_module, "PASS_INTERVAL_S", 0.01)
    d = Dispatcher({}, DeliveryLog())
    secret = tmp_path / "very-secret-dir" / "x.jsonl"
    # ENOSPC deliberately, and not `OSError(2, ...)`: Python refines an errno-2
    # `OSError` into `FileNotFoundError` at construction, so that spelling would
    # have tested a different class than the one the spec names. 28 has no
    # subclass. The third argument is what puts the path into `str()` —
    # asserted below, so this cannot pass because the path was never there.
    leaky = OSError(28, "No space left on device", str(secret))
    assert "very-secret-dir" in str(leaky)

    def boom():
        raise leaky

    d.process_due = boom
    d.start()
    try:
        _wait_until(lambda: d.pass_failures >= 1, what="one failed pass")
    finally:
        d.stop()
    assert d.last_pass_error == "OSError"
    assert "very-secret-dir" not in (d.last_pass_error or "")


def test_a_raising_scan_is_counted_but_the_cumulative_one_never_clears():
    """The asymmetry, pinned. `scan_failures` must survive recovery.

    `Dispatcher.pass_failures` clears nothing either — but it drives nothing, so
    nobody would notice if it did. This one degrades `/healthz`, and the reason
    it may is that the alert a raising scan would have sent is already gone:
    `due_alerts` marked the check before persisting, so no later scan re-sends
    it. See `HeartbeatMonitor.__init__` for the measurement.
    """
    mon = HeartbeatMonitor(HeartbeatStore(), lambda *a: None, interval_seconds=0.01)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError(28, "No space left on device")
        return 0

    mon.scan_once = flaky
    mon.start()
    try:
        _wait_until(lambda: calls["n"] >= 4, what="four scans")
    finally:
        mon.stop()
    assert mon.scan_failures == 2, "cumulative must NOT clear on recovery"
    assert mon.consecutive_scan_failures == 0
    assert mon.last_scan_error is None


# --- CG-74: where the scan counter does NOT reach -----------------------------

ROUTELESS_REGISTRY_YAML = REGISTRY_YAML.replace(
    "    routes: {alert: aitrader-alerts, warning: aitrader-reports, "
    "info: aitrader-reports}\n", "")
assert "routes:" not in ROUTELESS_REGISTRY_YAML  # the replace really landed


def test_a_routeless_alert_is_dropped_without_raising_or_counting(registry, tmp_path):
    """This pins the LIMIT of CG-74's signal, NOT a behaviour worth keeping.

    `HeartbeatMonitor.__init__` claimed `scan_failures` was "the only thing
    standing between a silently-dropped dead-man alert and a green /healthz".
    It is not, and the counter-example is here: an app with no `routes:` block
    at all. `due_alerts` marks the check `missed` and stamps `last_alerted`
    under its lock, then `_monitor_notify` gets an `HTTPException(503)` out of
    `route_for` — no `alert` route, no `default` — CATCHES it, and writes a
    delivery-log line. The alert is gone for the whole 24h repeat window and
    `scan_once` returns normally, so no counter in this file moves and
    `/healthz` stays `ok`.

    **CG-76 is expected to change what this asserts.** When a dropped alert
    becomes visible on `/healthz`, this test is the one that should go red —
    the `scan_failures == 0` and `status == "ok"` assertions below are a record
    of a hole, not a contract. Do not "fix" it by loosening them.
    """
    from pathlib import Path

    import chat_gateway.registry as regmod

    # Friday 2026-07-24 16:30 ET, the same clock the weekday dead-man case uses.
    clock = Clock(dt.datetime(2026, 7, 24, 20, 30, tzinfo=UTC))
    p = Path(str(tmp_path)) / "routeless.yaml"
    p.write_text(ROUTELESS_REGISTRY_YAML, encoding="utf-8")
    client, app, adapter = make_client(regmod.load_registry(p), clock, tmp_path)

    r = client.post("/v1/heartbeat", headers=AUTH, json={
        "check_id": "daily-run", "schedule": "weekdays", "grace": "2h"})
    assert r.status_code == 200

    # Monday past the grace deadline: the check really does come due.
    clock.now = dt.datetime(2026, 7, 27, 23, 0, tzinfo=UTC)
    assert app.state.monitor.scan_once() == 1

    # ...and nothing was sent. Not queued-and-unsent either — `emit_notification`
    # raised before `enqueue`, so draining the dispatcher changes nothing.
    app.state.dispatcher.process_due()
    assert adapter.sent == []
    assert app.state.dispatcher.pending() == 0

    # The check is nonetheless marked alerted, and the suppression is real: the
    # next scan finds nothing due, so this alert is not coming back today.
    state = client.get("/v1/heartbeat/aitrader", headers=AUTH).json()["checks"][0]
    assert state["status"] == "missed" and state["last_alerted"]
    assert app.state.monitor.scan_once() == 0

    # The one trace it left is a delivery-log line — which is NOT a send.
    log = app.state.delivery_log.query("aitrader")
    assert [(e["kind"], e["status"]) for e in log] == [("heartbeat", "failed")]
    assert "no route" in log[0]["detail"]

    # And the part that makes this a defect rather than a curiosity: /healthz.
    assert app.state.monitor.scan_failures == 0
    assert app.state.monitor.consecutive_scan_failures == 0
    assert app.state.monitor.last_scan_error is None
    body = client.get("/healthz").json()
    assert body["heartbeats"]["scan_failures"] == 0
    assert body["heartbeats"]["last_scan_error"] is None
    assert body["status"] == "ok"
    assert not [r for r in body["reasons"] if r.startswith("heartbeats: ")]
