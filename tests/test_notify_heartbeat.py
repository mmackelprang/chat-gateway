"""The aitrader contract's acceptance criteria, as deterministic tests:
severity routing/rendering, dedupe collapse, dead-man weekday logic with no
weekend false alarms, and full delivery-log accounting."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from chat_gateway.delivery import DeliveryLog, Dispatcher
from chat_gateway.envelope import DeliveryResult
from chat_gateway.heartbeat import HeartbeatError, HeartbeatStore, parse_schedule
from chat_gateway.inbox import Inbox
from chat_gateway.notifications import Deduper, Notification, render
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


def make_client(registry, clock, tmp_path, adapter=None):
    adapter = adapter or FakeAdapter()
    log = DeliveryLog()
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
