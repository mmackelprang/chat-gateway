# The dead-man switch's doors — implementation plan

**Row:** CG-76 · **Spec:**
[`2026-08-03-dead-man-alert-loss-design.md`](../specs/2026-08-03-dead-man-alert-loss-design.md)

**Baseline:** `main` at `d09a07c`, suite **345 passing** — re-measured with
`python3 -m pytest -q`. **Re-measure both ends yourself; do not copy this number
into a row.**

---

## Standing rules for this row

1. **Branch first.** `fix/cg-76-dead-man-alert-loss`. One PR.
2. **`adapters/` is untouched.** Verify before pushing:
   `git diff main -- src/ | grep -c "LIVE-UNVERIFIED\|SHAPE-VERIFIED"` → **`0`**.
   No ⚠ verification-ledger flag is cleared, added or reworded.
3. **`docs/architecture/` is off-limits.**
4. **Hard rule #2.** No new exception message is printed in full unless its class
   is marked in `errors.py`. This row marks nothing new — `HTTPException` and
   `OSError` both stay unmarked, so both render as the type name alone through
   `describe_exception`. Do not widen the allowlist here.
5. **Hard rule #5 vs CG-12.** `/healthz` is **unauthenticated**. Every field this
   row adds is a **bare integer**. No app id, no check id, no space, no
   timestamp. The identifying detail already lives on the authenticated
   `GET /v1/deliveries`.
6. **Order matters.** Task A1 → A2 → A3 must land together; A2 reads the API A1
   creates and A3 supplies the boolean A2 branches on. A4–A7 are independent of
   each other but all depend on A1–A3.
7. **Do not "fix" `tests/test_notify_heartbeat.py:687` by loosening it.** Its
   docstring says CG-76 should turn it red. Task A8 rewrites it into a positive
   assertion and keeps the history.

---

# Part A — CG-76 · every door to a silently-dropped dead-man alert

## Task A1 · `HeartbeatStore` splits SELECTING from MARKING

**File:** `src/chat_gateway/heartbeat.py`

**Why:** spec §3 (D1). `due_alerts` currently records *"I have alerted"* at a
moment when nothing has been alerted. Split the selector from the mark so the
caller can mark only what it actually got accepted.

Replace `due_alerts` (currently lines 154–166) with:

```python
    def due_alerts(self, repeat_s: int = DEFAULT_REPEAT_S) -> list[Check]:
        """Checks whose missed-alert should fire now. **Mutates NOTHING.**

        THE MUTATION USED TO LIVE HERE, AND THAT WAS CG-76. This method set
        `status = "missed"` and `last_alerted = now` under the lock and then
        `_save()`d, all BEFORE returning to `HeartbeatMonitor.scan_once` — the
        caller that actually notifies. The mark is a promise about the future
        ("an alert will be sent") persisted as a statement about the past ("an
        alert was sent"), and every way the future failed to arrive dropped the
        alert for the whole `DEFAULT_REPEAT_S` window with `/healthz` green.
        Six such ways were measured; five of them raise nothing at all, and one
        moves no /healthz field whatsoever. See the spec's §2.

        Selecting is now free of side effects, so a caller may call it, fail,
        and call it again. `mark_alerted` is the second half.
        """
        now = self._now()
        with self._lock:
            return [c for c in self._checks.values() if c.alert_due(now, repeat_s)]

    def mark_alerted(self, checks: list[Check]) -> None:
        """Record that these checks' alerts were ACCEPTED for delivery.

        Called by `scan_once` with only the checks whose notify actually got as
        far as the durable queue — never with a check whose alert was refused,
        deduped, or raised. Empty list is a no-op and does not touch the disk.

        AT-LEAST-ONCE, DELIBERATELY. If `_save()` raises here — or the process
        dies between the notify and this call — the check is not marked and the
        next scan alerts AGAIN. That is a duplicate, not a drop, and it is the
        posture every neighbouring mechanism in this repo already took for the
        reason each of them records: `_finish`'s mid-flight window
        (delivery.py, "losing an alert is the worse failure"), `_journal_write`
        ("at most one duplicate on the next boot"), and `Inbox._audit` (unacked,
        so Google redelivers). A duplicate "heartbeat missed" costs one
        redundant phone notification; a dropped one costs the whole feature,
        silently, for 24 hours.

        `_save()` stays UNGUARDED on purpose. It is now on the far side of the
        notify, so raising is honest — the alert is already queued and the raise
        costs at most a duplicate. Wrapping it would re-create CG-76 in a
        quieter form.
        """
        if not checks:
            return
        now = self._now().isoformat()
        with self._lock:
            for check in checks:
                check.status = "missed"
                check.last_alerted = now
            self._save()
```

⚠ **`due_alerts` keeps its name.** Renaming it would silently break any caller
this plan has not enumerated; the docstring carries the change of contract.

## Task A2 · `scan_once` marks only what was accepted, per check

**File:** `src/chat_gateway/heartbeat.py`

**Why:** spec §3 and §2.7. The loop must survive one check's failure so a
routeless tenant cannot strand another tenant's alert — measured: one
`RuntimeError` stranded a third app's alert entirely, and all three checks were
marked alerted anyway.

Replace `scan_once` (currently lines 223–234) with:

```python
    def scan_once(self) -> int:
        """One pass: select due checks, notify each, mark only what was accepted.

        Returns how many alerts were ACCEPTED for delivery — not how many were
        due. The two used to be the same number because marking happened before
        notifying; they are different now, and the difference is the point.

        PER CHECK, NOT PER BATCH, and the reason is cross-tenant. `fired` can
        hold checks owned by DIFFERENT apps — the store is gateway-wide, keyed
        (source, check_id). Before CG-76 this loop had no `try` inside it, so
        one app's failing notify aborted the loop and left every LATER check
        unnotified while `due_alerts` had already marked all of them alerted.
        Measured: a routeless `job-hunter` check suppressed `aiteam-harness`'s
        dead-man alert for 24h. That is the isolation instinct hard rules #4
        and #6 apply to inbound, and it costs one `try`.
        """
        fired = self._store.due_alerts(self._repeat)
        accepted: list = []
        undeliverable = 0
        first_error: Exception | None = None
        for check in fired:
            try:
                if self._notify(
                    check.source,
                    f"heartbeat missed: {check.check_id}",
                    f"No refresh since {check.last_seen} (schedule {check.schedule}, "
                    f"grace {check.grace}). Repeats daily until refreshed or deleted.",
                    f"hb:{check.check_id}",
                ):
                    accepted.append(check)
                else:
                    # The notify returned WITHOUT accepting — a route refusal
                    # (spec §2.2) or a dedupe (§2.4). Not an exception, so it
                    # must be counted here or it is invisible. The check is NOT
                    # marked, so it re-fires next scan and self-heals the moment
                    # the registry is fixed.
                    undeliverable += 1
            except Exception as exc:  # noqa: BLE001 — one tenant must not strand another
                undeliverable += 1
                if first_error is None:
                    first_error = exc
        # Mark BEFORE re-raising: the alerts that DID get accepted must not be
        # re-sent because a different check failed.
        self._store.mark_alerted(accepted)
        self.alerts_undeliverable += undeliverable
        self.checks_undeliverable = undeliverable
        if first_error is not None:
            raise first_error
        self.last_scan_at = dt.datetime.now(dt.timezone.utc)
        return len(accepted)
```

⚠ **`last_scan_at` still stamps only on a clean pass** — unchanged behaviour,
and `_run`'s `except` still catches. The `raise` is deliberately **after**
`mark_alerted` so a partial success is durable.

Add the two counters to `HeartbeatMonitor.__init__`, immediately after
`self.last_scan_error = None` (currently line 221):

```python
        #: CG-76. Alerts that came due and could NOT be accepted for delivery,
        #: over the life of the process. This is the counter `scan_failures`
        #: was mistaken for: a dead-man alert can be dropped WITHOUT any scan
        #: raising, and three separate paths do it (spec §2.2–§2.4) — a notify
        #: refused for want of a route, and a notify deduped against an earlier
        #: outage's alert. Both return normally, so nothing else sees them.
        #:
        #: CUMULATIVE and DEGRADING. Cumulative because an alert refused now is
        #: not re-sent by a later scan once the check is eventually marked;
        #: degrading because this names a guarantee BREAKING on aitrader's
        #: contract surface — the exact opposite of `suppressed_opt_out`, which
        #: names a guarantee WORKING and is correctly inert (CG-12).
        #:
        #: A BARE INTEGER. No app id, no check id: /healthz is unauthenticated
        #: and CG-12 rejected metadata-only records on exactly that ground. The
        #: operator who needs to know WHICH check reads the authenticated
        #: `GET /v1/deliveries`, where `_monitor_notify` already writes the
        #: identifying line.
        self.alerts_undeliverable = 0
        #: The same fact as a GAUGE: how many checks were undeliverable on the
        #: LAST scan. Returns to 0 when the registry is fixed, so it is the live
        #: signal beside the cumulative history — `RetentionSweeper`'s split,
        #: and CG-74 measured why one number cannot do both jobs.
        self.checks_undeliverable = 0
```

## Task A3 · `_monitor_notify` reports acceptance instead of swallowing it

**File:** `src/chat_gateway/service.py`

**Why:** spec §2.2 and §2.4 (D2 runtime half, D4 backstop). Today this returns
`None` unconditionally and discards `emit_notification`'s return value, so a
refusal and a dedupe are both indistinguishable from a delivery.

Replace `_monitor_notify` (currently lines 294–300) with:

```python
    def _monitor_notify(source: str, title: str, body: str,
                        dedupe_key: str | None) -> bool:
        """Emit a dead-man alert. Returns whether it was ACCEPTED for delivery.

        THE RETURN VALUE IS THE FIX (CG-76). This function used to return None
        and swallow two different failures:

        1. `except HTTPException` — the comment said "no alert route
           configured", but the CATCH is wider than the comment. Every
           `RegistryError` becomes an HTTPException in `emit_notification`, and
           `route_for` raises it on FOUR conditions: the source app is not
           registered, there is no `alert` route and no `default`, the app may
           not send as the routed identity, or that identity no longer exists.
           All four were logged and then forgotten.
        2. `{"status": "deduped"}` — returned, and discarded. Spec §2.4
           measures a genuinely NEW outage being deduped against the PREVIOUS
           outage's alert, one hour earlier.

        Still catches rather than raising: a permanent registry
        misconfiguration must not kill the scan loop, and it must not be
        reported as a transient fault either. `scan_once` counts the `False`
        and declines to mark the check, so the alert re-fires next scan and
        self-heals the moment the route is restored.
        """
        try:
            result = emit_notification(source, Notification(
                severity="alert", title=title, body=body, dedupe_key=dedupe_key,
            ))
        except HTTPException as exc:  # registry cannot route this alert
            log.record(source, "heartbeat", title, "failed", f"no route: {exc.detail}")
            return False
        if result.get("status") != "enqueued":
            # Belt and braces. D4 removes the only cause of this by passing no
            # dedupe_key from the dead-man path, so on today's code this branch
            # is unreachable — kept because the failure it guards is SILENT and
            # a future severity/route change could reintroduce it.
            log.record(source, "heartbeat", title, "failed",
                       f"not accepted for delivery: {result.get('status')}")
            return False
        return True
```

## Task A4 · The dead-man path stops using the deduper, and `POST /v1/heartbeat` refuses an unroutable check

**Files:** `src/chat_gateway/heartbeat.py`, `src/chat_gateway/service.py`

**Why:** spec §6 (D4) and §4.2 (D2 registration half).

**A4a — drop the `dedupe_key`.** In the `scan_once` body written in Task A2,
change the fourth argument from `f"hb:{check.check_id}"` to `None`, and put the
reasoning at the call site:

```python
                    # NO DEDUPE KEY — CG-76 door 4, and the removal is total
                    # rather than retuned. `alert_due()` IS this path's dedupe:
                    # it already guarantees at most one alert per check per
                    # `DEFAULT_REPEAT_S` (86400s). `Deduper`'s window is
                    # `DEFAULT_DEDUPE_WINDOW_S` (3600s). Since 86400 > 3600 the
                    # deduper can NEVER suppress an actual duplicate here — the
                    # monitor does not emit one — so every suppression it
                    # performed on this path was a FALSE POSITIVE. Measured: a
                    # source that died, recovered, refreshed its check, and died
                    # again inside the hour produced TWO outages and ONE alert.
                    # This is not a control with a trade-off; it is a control
                    # with no upside case. Pinned by
                    # `test_repeat_window_must_exceed_the_dedupe_window`.
                    None,
```

**A4b — refuse at registration.** Replace `refresh_heartbeat` (currently lines
340–349) with:

```python
    @app.post("/v1/heartbeat")
    def refresh_heartbeat(h: HeartbeatIn, app_id: str = Depends(current_app_id)):
        # CG-76 / spec §4.2. A dead-man check whose alert could never be routed
        # is a check that will go missed and tell nobody. Refuse it HERE — at
        # the moment the mistake is made, to the party who can fix it — rather
        # than discovering it 24h into an outage. `registry.example.yaml` gives
        # `aiteam-harness` and `job-hunter` no `routes:` block at all, so this
        # is not hypothetical for two of the three registered consumers.
        #
        # NOT "at boot": checks arrive at runtime and persist across restarts,
        # so registration is this object's equivalent of boot. And a snapshot
        # cannot be the whole fix — a route can be removed AFTER a check is
        # registered — which is why `alerts_undeliverable` exists as well.
        #
        # `str(exc)` is safe: `RegistryError`'s message is authored in
        # `registry.py` and names identities, never URLs (hard rule #2).
        try:
            registry.route_for(app_id, "alert")
        except RegistryError as exc:
            raise HTTPException(
                status_code=422,
                detail=(f"cannot register a dead-man check: this app has no "
                        f"route for alert-severity notifications, so a missed "
                        f"check could never be delivered ({exc}). Add "
                        f"routes: {{alert: <identity>}} to the registry"),
            ) from exc
        try:
            check = checks.refresh(app_id, h.check_id, h.schedule, h.grace, h.tz)
        except (HeartbeatError, Exception) as exc:
            if isinstance(exc, HeartbeatError):
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            raise HTTPException(status_code=422, detail=f"bad tz or check spec: {exc}") from exc
        return {"status": "ok", "check_id": check.check_id,
                "next_deadline": check.deadline().isoformat()}
```

## Task A5 · `Dispatcher` counts terminal delivery failures

**File:** `src/chat_gateway/delivery.py`

**Why:** spec §5 (D3). Measured: a heartbeat alert accepted, the ladder run to
exhaustion, **zero** sends to Google — and `scan_failures`, `pass_failures`,
`expired_at_boot` and `unroutable_at_boot` all stayed `0` with `/healthz` `ok`.

Add to `Dispatcher.__init__`, immediately after `self.last_pass_error = None`
(currently line 263):

```python
        #: Jobs that reached a TERMINAL `failed` — the retry ladder exhausted —
        #: over the life of the process. CG-76 door 3.
        #:
        #: `expired` and `unroutable` beside this count boot-replay losses and
        #: are published as `*_at_boot`. This is the same fact arriving by the
        #: other route: a job the gateway returned 202 ACCEPTED for, and then
        #: did not deliver, and will not retry. It was the one variant of that
        #: family with no counter at all, so ~73 minutes of Google being
        #: unreachable discarded a dead-man alert with nothing on /healthz.
        #:
        #: NOT scoped to `kind == "heartbeat"`, deliberately. A terminal failure
        #: on ANY accepted notification is a broken promise, and CG-12's "a
        #: guarantee working is not a fault" test does not apply — this is a
        #: guarantee breaking. The authenticated delivery log carries the
        #: per-source breakdown; this is a bare integer (hard rule #5 vs the
        #: unauthenticated endpoint).
        #:
        #: ⚠ POST-CG-75 THIS PATH IS SILENT, which is why the counter is needed
        #: now and was not before. Until CG-75, `_finish` on a full disk RAISED
        #: here and produced the 1/second send storm, which tripped staleness.
        #: CG-75 guarded that write — correctly — and in doing so removed the
        #: only thing that made ladder exhaustion loud.
        self.delivery_failures = 0
```

Then in `_finish` (currently line 389), count before the log write:

```python
    def _finish(self, job: Job, status: str, detail: str) -> None:
        if status == "failed":
            # CG-76 door 3. Counted BEFORE `record`, which is guarded (CG-75)
            # and therefore cannot be relied on to have happened.
            self.delivery_failures += 1
        self._log.record(job.source, job.kind, job.title, status, detail,
                         entry_id=job.entry_id)
```

## Task A6 · `/healthz` publishes the four new fields and degrades on them

**File:** `src/chat_gateway/service.py`

**A6a — body.** In the `heartbeats` block (currently ends at line 533), after
`"last_scan_error"`:

```python
                           # CG-76. What `scan_failures` could not say: an alert
                           # can be dropped without any scan raising. Three
                           # paths did it — a route refusal, a dedupe, and a
                           # ladder exhaustion — and all three returned
                           # normally. Bare integers: /healthz is
                           # unauthenticated (CG-12), and the identifying detail
                           # is on the authenticated GET /v1/deliveries.
                           "alerts_undeliverable": getattr(
                               monitor, "alerts_undeliverable", 0),
                           "checks_undeliverable": getattr(
                               monitor, "checks_undeliverable", 0),
                           # CG-76 door 5. `hb_all` above filters the census
                           # through `registry.apps`, so a check whose source
                           # was renamed or removed drops out of BOTH `checks`
                           # and `missed` — measured: `checks: 1 -> 0` on a
                           # rename, while the store still held it, still
                           # scanned it, and its alert still died through the
                           # `unknown app` branch of `route_for`. Under-
                           # reporting coverage is worse than reporting none:
                           # `checks: 0` reads as "nothing to worry about".
                           #
                           # A SECOND NUMBER, not an unfiltered `hb_all` —
                           # widening that would silently change what `checks`
                           # and `missed` mean, and three docs describe them.
                           "checks_orphaned": _checks_orphaned(registry, checks)},
```

...replacing the `}` that currently closes that dict after `last_scan_error`.

Add the helper beside `_scan_stale_after` (currently line 153):

```python
def _checks_orphaned(registry, checks) -> int:
    """Registered dead-man checks whose source is no longer a registered app.

    A bare count, never the ids (CG-12: /healthz is unauthenticated, and an
    orphaned check's `source` is a FORMER TENANT's app id). The authenticated
    `GET /v1/deliveries` carries the failing alerts under that id.

    `HeartbeatStore` has no "all sources" accessor by design — `list_for` is
    per-source, which is what keeps the endpoint's own authorization honest —
    so this reads the private map under the store's lock via `list_all`.
    """
    return sum(1 for c in checks.list_all() if c.source not in registry.apps)
```

...which needs one accessor on `HeartbeatStore`, beside `list_for`
(`heartbeat.py:150`):

```python
    def list_all(self) -> list[Check]:
        """Every check, regardless of source. For /healthz's census only.

        Deliberately NOT exposed through any HTTP route: `GET /v1/heartbeat/
        {source}` is per-source and authorization-checked, and this would be a
        cross-tenant read. `/healthz` uses it to COUNT, never to name.
        """
        with self._lock:
            return list(self._checks.values())
```

In the `delivery` block, after `"unroutable_at_boot"` (currently line 465):

```python
                         # CG-76 door 3. The in-process sibling of the two
                         # `*_at_boot` counters above: a job accepted with a
                         # 202 whose retry ladder then ran out. Same family,
                         # same reason, and it was the one member with no
                         # counter.
                         "delivery_failures": getattr(dispatch, "delivery_failures", 0),
```

**A6b — reasons.** Immediately after the existing `if hb["scan_failures"]:`
block (currently ends line 968), add:

```python
        # OUTSIDE the liveness elif-chain, beside `scan_failures` and for the
        # same reason: the chain answers "is this loop running", this answers
        # "has an alert already been lost", and both can be true at once.
        #
        # TWO NUMBERS, and they say different things. The gauge is the live
        # signal — a registry the operator can fix right now. The cumulative one
        # is the report of loss and does not clear.
        if hb["checks_undeliverable"]:
            reasons.append(
                f"heartbeats: {hb['checks_undeliverable']} registered check(s) "
                "came due and their alert could NOT be routed — the source has "
                "no `alert` route, no `default` route, or its routed identity "
                "is gone from the registry. Those sources are silently "
                "unmonitored: the check will keep re-firing and will deliver "
                "as soon as the registry is fixed. `GET /v1/deliveries` names "
                "which"
            )
        if hb["alerts_undeliverable"]:
            reasons.append(
                f"heartbeats: {hb['alerts_undeliverable']} dead-man alert(s) "
                "could not be accepted for delivery since start — a source that "
                "went silent was not reported on. CUMULATIVE and will not clear "
                "while this process runs; `checks_undeliverable` is the live "
                "signal. `GET /v1/deliveries` names which"
            )
        if hb["checks_orphaned"]:
            reasons.append(
                f"heartbeats: {hb['checks_orphaned']} registered check(s) "
                "belong to a source that is NOT a registered app — renamed, "
                "removed, or a registry block that failed to load. They are "
                "still scanned and their alerts still fail, but they are "
                "excluded from `checks` and `missed` above, so those two "
                "numbers UNDER-REPORT this deployment's dead-man coverage. "
                "`GET /v1/deliveries` names which"
            )
```

And after the existing `expired_at_boot`/`unroutable_at_boot` reason block
(currently ends line 811):

```python
        if queue["delivery_failures"]:
            reasons.append(
                f"delivery: {queue['delivery_failures']} accepted job(s) "
                "exhausted the retry ladder and were DROPPED — the gateway "
                "returned 202 for them and did not deliver them. Roughly 73 "
                "minutes of a Chat endpoint being unreachable is the shape. "
                "CUMULATIVE; `GET /v1/deliveries` names which"
            )
```

## Task A7 · Correct the strings and docstrings CG-76 falsifies

**Files:** `src/chat_gateway/heartbeat.py`, `src/chat_gateway/service.py`

**Why:** spec §7 (D5). This is the loud part. `scan_failures` **keeps
degrading** — the user's D3 decision stands and CG-74 validated it on a real
server. What expires is its stated **justification**.

**A7a.** In `HeartbeatMonitor.__init__`, replace the `scan_failures` docstring
block (currently lines 185–217) with:

```python
        #: Scans that RAISED, and scans that have raised since the last good
        #: one. `Dispatcher`'s twin — with ONE deliberate asymmetry:
        #: `scan_failures` is CUMULATIVE **and degrading**, where
        #: `Dispatcher.pass_failures` is cumulative and inert.
        #:
        #: ⚠ THE ORIGINAL REASON FOR THAT ASYMMETRY EXPIRED WITH CG-76. It read:
        #: "a failed SCAN is not [recoverable] — `due_alerts` marks the check
        #: before persisting, and `scan_once` only notifies what `due_alerts`
        #: returned, so a raise leaves the check marked alerted and the alert
        #: never sent." That was true and measured when CG-74 shipped it. CG-76
        #: reordered exactly that: the mark now happens in `mark_alerted`, AFTER
        #: the notify is accepted, so a scan that raises has NOT marked the
        #: check and the next scan re-fires it. A failed scan is now
        #: RECOVERABLE — which is precisely the property that makes
        #: `pass_failures` inert.
        #:
        #: IT STAYS DEGRADING ANYWAY, AND THE REASON IS NOW THE WEAKER ONE —
        #: say so rather than keep quoting the strong one (the discipline
        #: CLAUDE.md applies to `__cg_action__`). A loop that keeps raising is
        #: still a dead-man monitor that is not completing scans, on aitrader's
        #: contract surface, and the conservative posture there is to degrade.
        #: What a raise now risks is a DELAYED or DUPLICATED alert, not a lost
        #: one. Flipping this to inert is defensible after CG-76 and is
        #: deliberately NOT done here — it is a separate user decision with its
        #: own measurement, not a fold-in (spec §7.2).
        #:
        #: THIS IS NOT THE DROPPED-ALERT COUNTER. `alerts_undeliverable` is.
        #: An alert can be dropped with nothing raising at all.
```

**A7b.** Replace the `scan_failures` reason string (currently lines 960–968):

```python
        if hb["scan_failures"]:
            reasons.append(
                f"heartbeats: {hb['scan_failures']} scan(s) have raised since "
                "start — since CG-76 a raising scan does NOT drop the alert "
                "(the check is no longer marked before the notify is accepted), "
                "so the risk is a DELAYED or DUPLICATED alert rather than a "
                "lost one. CUMULATIVE and will not clear while this process "
                "runs; `consecutive_scan_failures` is the live signal, and "
                "`alerts_undeliverable` is the counter for an alert actually "
                "lost"
            )
```

**A7c.** `HeartbeatMonitor.is_alive`'s docstring (currently 252–264) is
**correct and stays** — it is about a dead thread, which CG-76 does not touch.
Do not edit it.

## Task A8 · Tests

**File:** `tests/test_notify_heartbeat.py` unless noted.

**A8a — rewrite the test that is supposed to go red.** Replace
`test_a_routeless_alert_is_dropped_without_raising_or_counting` (line 687) with:

```python
def test_a_routeless_alert_is_counted_and_degrades_healthz(registry, tmp_path):
    """CG-76 door 2. THIS TEST USED TO ASSERT THE OPPOSITE, on purpose.

    Its previous name was
    `test_a_routeless_alert_is_dropped_without_raising_or_counting`, and its
    docstring said: "CG-76 is expected to change what this asserts. When a
    dropped alert becomes visible on /healthz, this test is the one that should
    go red — the `scan_failures == 0` and `status == "ok"` assertions below are
    a record of a hole, not a contract."

    This is that change. The hole is closed: the alert is still not delivered —
    there is genuinely no route — but it is now COUNTED, /healthz DEGRADES, and
    the check is NOT marked, so it re-fires and will deliver the moment a route
    is added.
    """
    from pathlib import Path

    import chat_gateway.registry as regmod

    clock = Clock(dt.datetime(2026, 7, 24, 20, 30, tzinfo=UTC))
    p = Path(str(tmp_path)) / "routeless.yaml"
    p.write_text(ROUTELESS_REGISTRY_YAML, encoding="utf-8")
    client, app, adapter = make_client(regmod.load_registry(p), clock, tmp_path)

    # Registration itself is now refused (Task A4b) — so drive the store
    # directly to reach the runtime path this test is about.
    app.state.heartbeats.refresh("aitrader", "daily-run", "weekdays", "2h")

    clock.now = dt.datetime(2026, 7, 27, 23, 0, tzinfo=UTC)
    assert app.state.monitor.scan_once() == 0          # 0 ACCEPTED, not 0 due

    app.state.dispatcher.process_due()
    assert adapter.sent == []

    # The check is NOT marked, so it re-fires rather than going quiet for 24h.
    state = client.get("/v1/heartbeat/aitrader", headers=AUTH).json()["checks"][0]
    assert state["status"] == "ok" and state["last_alerted"] is None
    assert len(app.state.heartbeats.due_alerts()) == 1

    body = client.get("/healthz").json()
    assert body["heartbeats"]["alerts_undeliverable"] == 1
    assert body["heartbeats"]["checks_undeliverable"] == 1
    assert body["heartbeats"]["scan_failures"] == 0     # nothing RAISED
    assert body["status"] == "degraded"
    assert any("could NOT be routed" in r for r in body["reasons"])
```

**A8b — door 4, the flapping case.**

```python
def test_a_second_outage_inside_the_dedupe_window_is_still_alerted(registry, tmp_path):
    """CG-76 door 4. Two distinct outages used to produce ONE alert.

    A source dies, is alerted on, recovers and refreshes its check (which
    clears `last_alerted`), then dies AGAIN inside the deduper's 3600s window.
    The second alert used to be deduped against the first outage's — a false
    positive, because `alert_due` already guarantees at most one alert per check
    per 86400s, so the deduper could never suppress a real duplicate here.
    """
    clock = Clock(dt.datetime(2026, 7, 24, 20, 30, tzinfo=UTC))
    client, app, adapter = make_client(registry, clock, tmp_path)

    client.post("/v1/heartbeat", headers=AUTH, json={
        "check_id": "daily-run", "schedule": "every:60s", "grace": "60s"})
    clock.now += dt.timedelta(seconds=300)
    assert app.state.monitor.scan_once() == 1
    app.state.dispatcher.process_due()
    assert len(adapter.sent) == 1

    # Recovered, refreshed — a brand-new check with `last_alerted` cleared.
    clock.now += dt.timedelta(seconds=60)
    client.post("/v1/heartbeat", headers=AUTH, json={
        "check_id": "daily-run", "schedule": "every:60s", "grace": "60s"})

    # ...and dies again, still well inside DEFAULT_DEDUPE_WINDOW_S.
    clock.now += dt.timedelta(seconds=300)
    assert app.state.monitor.scan_once() == 1
    app.state.dispatcher.process_due()
    assert len(adapter.sent) == 2, "the second real outage must alert"
    assert client.get("/healthz").json()["heartbeats"]["alerts_undeliverable"] == 0


def test_repeat_window_must_exceed_the_dedupe_window(registry, tmp_path):
    """Pins the REASONING behind dropping the dead-man path's dedupe_key.

    The key was removed because `alert_due`'s repeat window is strictly longer
    than the deduper's, so the deduper could only ever produce false positives
    on that path. If someone inverts these constants that argument stops
    holding, and this test is where they are told.
    """
    from chat_gateway.heartbeat import DEFAULT_REPEAT_S
    from chat_gateway.notifications import DEFAULT_DEDUPE_WINDOW_S

    assert DEFAULT_REPEAT_S > DEFAULT_DEDUPE_WINDOW_S
```

**A8c — door 3, ladder exhaustion.**

```python
def test_an_exhausted_retry_ladder_is_counted_and_degrades_healthz(registry, tmp_path):
    """CG-76 door 3. An accepted alert that never lands used to be invisible.

    `expired`/`unroutable` are BOOT-REPLAY counters (`*_at_boot`); a job that
    exhausts the ladder in-process had none. Post-CG-75 this path is silent —
    until CG-75 it raised and produced the send storm, which is the only thing
    that ever made it loud.
    """
    clock = Clock(dt.datetime(2026, 7, 24, 20, 30, tzinfo=UTC))
    adapter = FakeAdapter(fail_times=99)
    client, app, _ = make_client(registry, clock, tmp_path, adapter=adapter)

    client.post("/v1/heartbeat", headers=AUTH, json={
        "check_id": "daily-run", "schedule": "every:60s", "grace": "60s"})
    clock.now += dt.timedelta(seconds=300)
    assert app.state.monitor.scan_once() == 1

    for _ in range(len(delivery_module.BACKOFF_S) + 2):
        app.state.dispatcher.process_due()
        clock.now += dt.timedelta(seconds=4000)

    assert adapter.sent == []
    assert app.state.dispatcher.pending() == 0
    body = client.get("/healthz").json()
    assert body["delivery"]["delivery_failures"] == 1
    assert body["delivery"]["pass_failures"] == 0        # nothing RAISED
    assert body["status"] == "degraded"
    assert any("exhausted the retry ladder" in r for r in body["reasons"])
```

**A8d — the amplifier: cross-tenant isolation.**

```python
def test_one_tenants_failing_notify_does_not_strand_anothers_alert(tmp_path):
    """CG-76 §2.7. Measured before the fix: a routeless `job-hunter` check
    aborted the loop, `aiteam-harness`'s alert was NEVER ATTEMPTED, and all
    three checks were marked alerted anyway — so the next scan fired zero."""
    clock = Clock(dt.datetime(2026, 7, 24, 12, 0, tzinfo=UTC))
    store = HeartbeatStore(tmp_path / "hb.json", now_fn=clock)
    for src in ("aitrader", "job-hunter", "aiteam-harness"):
        store.refresh(src, "c", "every:60s", "60s")

    sent = []

    def notify(source, title, body, key):
        if source == "job-hunter":
            raise RuntimeError("no route")
        sent.append(source)
        return True

    monitor = HeartbeatMonitor(store, notify)
    clock.now += dt.timedelta(seconds=300)
    with pytest.raises(RuntimeError):
        monitor.scan_once()

    assert sorted(sent) == ["aiteam-harness", "aitrader"]
    # The two that succeeded are marked; the one that failed is not, and
    # re-fires on the next scan.
    assert [c.source for c in store.due_alerts()] == ["job-hunter"]
    assert monitor.alerts_undeliverable == 1
```

**A8e — door 1, the reordering itself.**

```python
def test_a_failing_save_no_longer_suppresses_the_alert(registry, tmp_path, monkeypatch):
    """CG-76 door 1. The alert is now SENT before the mark is attempted, so a
    failing `_save()` costs at most a duplicate on the next scan — never a drop.

    ⚠ This is the scenario CG-74's UAT used, and it now produces a DIFFERENT
    and better result. There, `main` sent zero notifications and answered `ok`
    while the branch sent zero and answered `degraded`. Here the alert is
    actually DELIVERED. `scan_failures` still moves; what it accompanies is no
    longer a lost alert (spec §7.3).
    """
    clock = Clock(dt.datetime(2026, 7, 24, 20, 30, tzinfo=UTC))
    client, app, adapter = make_client(registry, clock, tmp_path)
    client.post("/v1/heartbeat", headers=AUTH, json={
        "check_id": "daily-run", "schedule": "every:60s", "grace": "60s"})

    def boom():
        raise OSError("disk full")

    monkeypatch.setattr(app.state.heartbeats, "_save", boom)
    clock.now += dt.timedelta(seconds=300)
    with pytest.raises(OSError):
        app.state.monitor.scan_once()

    app.state.dispatcher.process_due()
    assert len(adapter.sent) == 1, "the alert must be sent before the mark"
    # Unmarked, so it re-fires — at-least-once, never at-most-once.
    assert len(app.state.heartbeats.due_alerts()) == 1
```

**A8f — registration refusal (A4b).**

```python
def test_registering_a_check_with_no_alert_route_is_refused(tmp_path):
    """CG-76 §4.2. `aiteam-harness` and `job-hunter` have no `routes:` block in
    the example registry, so this is the live shape, not a contrived one."""
    from pathlib import Path

    import chat_gateway.registry as regmod

    clock = Clock(dt.datetime(2026, 7, 24, 20, 30, tzinfo=UTC))
    p = Path(str(tmp_path)) / "routeless.yaml"
    p.write_text(ROUTELESS_REGISTRY_YAML, encoding="utf-8")
    client, _, _ = make_client(regmod.load_registry(p), clock, tmp_path)

    r = client.post("/v1/heartbeat", headers=AUTH, json={
        "check_id": "daily-run", "schedule": "weekdays", "grace": "2h"})
    assert r.status_code == 422
    assert "no route for alert" in r.json()["detail"] or \
           "no route" in r.json()["detail"]
    assert "http" not in r.json()["detail"].lower(), "hard rule #2: never a URL"
```

**A8g — door 5, the vanishing check.**

```python
def test_a_check_whose_source_left_the_registry_is_counted_not_hidden(
        registry, tmp_path):
    """CG-76 door 5. Measured before the fix: renaming the app took the check
    out of BOTH `checks` and `missed` — `checks: 1 -> 0` — while the store
    still held it, still scanned it, and its alert still died through
    `route_for`'s `unknown app` branch. `/healthz` claimed zero dead-man
    coverage, which reads as "nothing to worry about"."""
    clock = Clock(dt.datetime(2026, 7, 24, 20, 30, tzinfo=UTC))
    client, app, adapter = make_client(registry, clock, tmp_path)
    client.post("/v1/heartbeat", headers=AUTH, json={
        "check_id": "daily-run", "schedule": "every:60s", "grace": "60s"})
    assert client.get("/healthz").json()["heartbeats"]["checks"] == 1

    # The tenant leaves the registry; the state file is untouched.
    app.state.heartbeats._checks[("ghost", "orphan")] = \
        app.state.heartbeats._checks[("aitrader", "daily-run")]
    del app.state.heartbeats._checks[("aitrader", "daily-run")]

    body = client.get("/healthz").json()
    assert body["heartbeats"]["checks"] == 0        # still excluded, by design
    assert body["heartbeats"]["checks_orphaned"] == 1
    assert body["status"] == "degraded"
    assert any("NOT a registered app" in r for r in body["reasons"])
    assert "ghost" not in json.dumps(body), "hard rule #5 vs CG-12: count, never name"
```

**A8h — door 6, the repeat alert that used to move nothing.**

```python
def test_a_failed_REPEAT_alert_is_counted_even_though_missed_does_not_move(
        registry, tmp_path):
    """CG-76 door 6 — the worst of the six, and the one that survived the first
    deliberate sweep.

    `heartbeats.missed` is derived from `check.status`, which `due_alerts` set
    to "missed" on the FIRST fire. So when the 24h REPEAT — the alert that
    exists to keep shouting — dies, `missed` was already 1 and did not move.
    Measured on `main`: NOT ONE FIELD in the whole /healthz body changed.

    ⚠ This is why `alerts_undeliverable` counts per ALERT ATTEMPT and never
    references `check.status`. Do not "simplify" it into a derivation from
    check state — that refactor looks like tidying and reopens this door.
    """
    clock = Clock(dt.datetime(2026, 7, 24, 20, 30, tzinfo=UTC))
    adapter = FakeAdapter()
    client, app, _ = make_client(registry, clock, tmp_path, adapter=adapter)
    client.post("/v1/heartbeat", headers=AUTH, json={
        "check_id": "daily-run", "schedule": "every:60s", "grace": "60s"})

    # First alert: delivered. `missed` goes 0 -> 1 and now STAYS there.
    clock.now += dt.timedelta(seconds=300)
    assert app.state.monitor.scan_once() == 1
    app.state.dispatcher.process_due()
    assert len(adapter.sent) == 1
    assert client.get("/healthz").json()["heartbeats"]["missed"] == 1

    # Chat becomes unreachable, and the 24h REPEAT comes due.
    adapter.fail_times = 99
    clock.now += dt.timedelta(seconds=86401)
    assert app.state.monitor.scan_once() == 1, "the repeat must re-fire"
    for _ in range(len(delivery_module.BACKOFF_S) + 2):
        app.state.dispatcher.process_due()
        clock.now += dt.timedelta(seconds=4000)

    body = client.get("/healthz").json()
    assert len(adapter.sent) == 1, "the repeat never landed"
    # THE POINT: `missed` is unchanged — it was already 1 — and on `main` that
    # was the whole of the observable state. Now something else moved.
    assert body["heartbeats"]["missed"] == 1
    assert body["delivery"]["delivery_failures"] == 1
    assert body["status"] == "degraded"
    assert any("exhausted the retry ladder" in r for r in body["reasons"])
```

⚠ **A8h note for the implementer:** the assertion that matters is
`missed == 1` **while** something else degrades. If you find yourself making
`missed` move to get this green, stop — §2.8 of the spec measured that `missed`
moves identically on a *delivered* alert, so it cannot be the signal.

**A8i — `mark_alerted` is a no-op on an empty list** (guards the disk write):

```python
def test_mark_alerted_with_nothing_does_not_touch_the_disk(tmp_path):
    store = HeartbeatStore(tmp_path / "hb.json")
    store.refresh("aitrader", "c", "every:60s", "60s")
    before = (tmp_path / "hb.json").stat().st_mtime_ns
    store.mark_alerted([])
    assert (tmp_path / "hb.json").stat().st_mtime_ns == before
```

**A8j — sweep the existing suite.** Any test asserting the OLD contract must be
updated with a docstring saying why, not silently loosened. Expect at minimum:
- tests asserting `scan_once()` returns the number **due** rather than
  **accepted**;
- tests asserting a check is marked `missed` immediately after `scan_once`
  when the notify fails;
- any test constructing a `notify_fn` for `HeartbeatMonitor` — **every fake
  notify must now return `True`**, or it will read as undeliverable.

Run `python3 -m pytest -q -k heartbeat` first to find them.

## Task A9 · Docs

**A9a — `docs/integration-guide.md`.** In the `/healthz` field table (rows added
around line 495), after `heartbeats.last_scan_error`:

```markdown
| `heartbeats.alerts_undeliverable` | dead-man alerts that came due and could **not be accepted for delivery**, over the life of the process. This is the dropped-alert counter — `scan_failures` is not, and said so until CG-76. An alert is dropped here without anything raising: the source has no `alert`/`default` route, or its routed identity is gone. **Cumulative and does not reset.** A bare integer by design — `GET /v1/deliveries` (authenticated) names which check | **yes** |
| `heartbeats.checks_undeliverable` | how many checks were in that state on the **last** scan. Returns to `0` when the registry is fixed, so this is the live signal beside the cumulative row above | **yes** |
| `heartbeats.checks_orphaned` | registered checks whose `source` is **not a registered app** — renamed, removed, or a registry block that failed to load. ⚠ **`checks` and `missed` above EXCLUDE these**, so without this row those two under-report the deployment's dead-man coverage while the checks are still scanned and their alerts still fail. A bare count, never the ids | **yes** |
| `delivery.delivery_failures` | accepted jobs that **exhausted the retry ladder** and were dropped. The in-process sibling of `expired_at_boot` / `unroutable_at_boot`: the gateway returned `202` and then did not deliver. **Cumulative** | **yes** |
```

And correct the existing `heartbeats.scan_failures` row (line 495) — it
currently says a raising scan *"has already dropped that alert"*, which CG-76
falsifies:

```markdown
| `heartbeats.scan_failures` | scans that **raised**, over the life of the process — and unlike its `delivery.*` counterpart this one **degrades**. ⚠ **Its original justification expired with CG-76**: before that row a raising scan had already marked the check and dropped the alert; now the mark happens only after the alert is accepted, so a raise risks a **delayed or duplicated** alert rather than a lost one. It stays degrading on the weaker reason — a monitor that keeps raising is not evaluating checks — and `heartbeats.alerts_undeliverable` is the counter for an alert actually lost. **Cumulative and does not reset** | **yes** |
```

**A9b — `docs/consumers/aitrader.md`.** In §7 (dead-man), after the refresh
semantics paragraph (~line 292):

```markdown
**Registration now fails fast if we could never alert you.** `POST /v1/heartbeat`
resolves your `alert` route before storing the check and returns **422** if
there isn't one. A dead-man check whose alert could never be routed is a check
that goes missed and tells nobody, which is the one failure this feature exists
to prevent (CG-76).

**Alerts are at-least-once, not at-most-once.** A check is marked alerted only
after its notification is accepted into the durable queue. If the gateway dies
between sending and recording, you get the alert **twice** rather than not at
all — the same trade the delivery queue's replay already makes, and for the same
reason: a duplicate "heartbeat missed" costs you one redundant notification, a
dropped one costs you the feature.
```

**A9c — `CLAUDE.md`.** Add one bullet to *Current status*. **Do not restate the
door list** — link it. One home per moving fact:

```markdown
- **The dead-man switch had FOUR doors to a silently-dropped alert, not one
  (CG-76, 2026-08-03).** `HeartbeatStore.due_alerts` recorded *"I have alerted"*
  before anything was alerted — a promise about the future persisted as a
  statement about the past — and each door was a different way for the future
  not to arrive: a raise downstream, a notify refused for want of a route, a
  retry ladder exhausted, and a genuinely new outage **deduped** against the
  previous one's alert. **Three of the four raised nothing**, so `scan_failures`
  stayed `0` and `/healthz` answered `ok`. The mark now happens in
  `mark_alerted`, after the alert is accepted into the durable queue, which
  moves this path from at-most-once to **at-least-once** — the posture
  `_finish`, `_journal_write` and `Inbox._audit` each already took, for the
  reason each of them records. ⚠ **`scan_failures` still degrades but its
  ORIGINAL justification expired**, and the weaker surviving one is stated at
  `HeartbeatMonitor.__init__` rather than the strong one being re-quoted — the
  same discipline this file applies to `__cg_action__`. Do not summarize the
  four doors anywhere; the enumeration and its measurements have one home,
  `docs/superpowers/specs/2026-08-03-dead-man-alert-loss-design.md` §2.
```

---

## Verification

Run all of this before opening the PR, and **paste real output** into the PR
body. Evidence before assertions.

```bash
# 1. Full suite, both ends re-measured (baseline was 345 at d09a07c).
python3 -m pytest -q

# 2. The flag constraint. MUST print 0.
git diff main -- src/ | grep -c "LIVE-UNVERIFIED\|SHAPE-VERIFIED"

# 3. Nothing under adapters/ or docs/architecture/ changed. MUST be empty.
git diff --name-only main -- src/chat_gateway/adapters/ docs/architecture/

# 4. errors.py's allowlist untouched. MUST be empty.
git diff main -- src/chat_gateway/errors.py

# 5. No app id, check id or space reaches the unauthenticated endpoint.
#    Read every new reason string and every new field: bare integers only.
python3 -m pytest -q -k "healthz or heartbeat" 
```

**UAT — a real uvicorn server, real loop threads, real HTTP.** Do not accept a
monkeypatched substitute; every measurement in the spec was taken this way, and
`main` must be run as the control.

| # | Scenario | `main` | expected on branch |
|---|---|---|---|
| 1 | app with no `routes:`, register a check | 200, check stored | **422**, refused |
| 2 | same app, check forced into the store, goes missed | `ok`, `reasons: []`, 0 sent | **`degraded`**, `alerts_undeliverable: 1`, check **unmarked** |
| 3 | add the route, wait one scan interval | still nothing | **alert delivered**, gauge back to `0` |
| 4 | source dies → alert → refresh → dies again inside 3600s | **1** send for 2 outages | **2** sends |
| 5 | Chat endpoint refusing every send, walk the full ladder | `ok`, no counter moves | **`degraded`**, `delivery_failures: 1` |
| 6 | `chmod a-w` the state dir, check goes missed | 0 sent, alert lost | **alert DELIVERED**, `scan_failures: 1`, check unmarked → duplicate risk only |

⚠ **Scenario 6 is CG-74's own UAT and it now produces a different result on
purpose** (spec §7.3). It is not a regression. Record both sides.

---

## Docs Impact (for the PR body)

| File | Change |
|---|---|
| `docs/integration-guide.md` | three new `/healthz` rows; **one existing row corrected** (`scan_failures`) |
| `docs/consumers/aitrader.md` | §7 — registration now 422s without an alert route; alerts are at-least-once |
| `CLAUDE.md` | one *Current status* bullet, linking the enumeration rather than restating it |
| `docs/BUILDER_QUEUE.md` | CG-76 → ✅ done; banner |
| `docs/superpowers/specs/2026-08-03-delivery-write-path-robustness-design.md` | ⚠ **already corrected by the planning PR** — §5's false absolute. Do not re-edit |
