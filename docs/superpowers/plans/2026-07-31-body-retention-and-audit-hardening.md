# Plan — CG-65 / CG-68: body retention and audit hardening

| | |
|---|---|
| **Spec** | [`2026-07-31-body-retention-and-audit-hardening-design.md`](../specs/2026-07-31-body-retention-and-audit-hardening-design.md) |
| **ADR** | [ADR-0002](../../architecture/decisions/2026-07-31-journalled-message-bodies.md) — `D + A + D5` |
| **Base** | `dced002` (CG-61/#50), suite **247**. Rebased 2026-07-31 — drafted on `b8af699`/246 |
| **Approved** | ✅ **all four sign-offs granted by the user, 2026-07-31** — see the box below |
| **Rows** | **CG-65** = Tasks 1–9 (ships on green). **CG-68** = Tasks 10–13 (⏸ merge-gated) |

> ## ✅ APPROVED — all four sign-offs granted by the user, 2026-07-31
>
> Recorded as **decisions, not open questions.** The reasoning is kept with each
> verdict, because a Builder needs the *why* — and because leaving "needs
> approval" text in an approved plan is the same drift CG-69 exists to catch.
>
> | # | Decision | Why — kept, not summarized away |
> |---|---|---|
> | **A1** | ✅ **The unrevivable quarantine is the answer to ADR-0002 §9 Q6.** Task 6 | It is **stronger than the guarantee it retires**. Today the gateway drops bytes it is **holding** (`rec["payload"]` is in hand at `inbox.py:130`), boot compaction erases its own copy moments later, and six places then point the operator at a `0644` file the sweeper is entitled to delete — **one of those six being a live `/healthz` `reasons` string**, which makes it hard rule #5, not documentation. Preserving the record costs one append and makes retention and recovery **independent** |
> | **A2** | ✅ **Retention: 30 days tenant / 7 days `_unrouted` / `0` disables**, via `CHAT_GATEWAY_INBOX_RETENTION_DAYS`. Task 10 | **30** because a calendar month is the unit a privacy posture and a subject-access request are written in, and — load-bearing — **`docs/integration-guide.md:370` already tells consumers this file is *"a forensic record on the gateway host, not something you can re-poll"***, so the gateway does **not** need to hold a consumer's decision history; a consumer needing it keeps its own. **7** for `_unrouted` per ADR §4.1: it answers to no tenant and has no consent story. **Time-bounded in days, never count-bounded** — ADR §2.2 is the reason |
> | **A3** | ✅ **Unlink, not redact.** Task 10 | The filename **is** the retention key, so pruning is a directory listing and an `unlink` — no parsing, and nothing ever opens a file holding message bodies to decide whether to delete it. Redaction needs field-by-field judgements about which parts of a person's message are sensitive, which is rule-#1 territory |
> | **A4** | ✅ **Amend the shared contract.** Task 13a | `integration-guide.md:366`'s *"never pruned"* was a v0 over-promise on a file holding a person's `text`, `sender_email` and whole `raw` event forever. It is owed to **every** consumer, not to jobhunt alone — which is why it was signed off explicitly rather than absorbed into a docs pass |
>
> **A2's rule-#1 note, so it is not relitigated in review:** the window is
> **global**. `_unrouted`'s shorter floor is the gateway governing **its own**
> reserved bucket (hard rule #6 reserves the `_` prefix), **not** per-app policy —
> a per-*tenant* window would be ADR-0002 Option C's shape and would re-open the
> question the user deliberately left **not reached** (D6).

> ⚠ **Builder: read this box first.**
>
> 1. **Tasks 10–13 are approved but still sequenced second: CG-65 must MERGE
>    first.** Task 6 (quarantine) is the gate that makes pruning safe. Shipping
>    the sweeper first deletes the last copy of a reply that was never delivered.
>    This is the one remaining gate — the four decisions above are settled.
> 2. **No ⚠ flag may be cleared, added or reworded.** Nothing here touches
>    `adapters/` or any Google seam. Do not restate `CLAUDE.md`'s verification
>    ledger — link to it.
> 3. **Do not touch `docs/architecture/`.** The ADR is decided and is evidence.
> 4. **Do not re-open ADR-0002 §6.**
> 5. Tests: `python3 -m pytest` on POSIX, `python -m pytest` on the Windows dev
>    box. Measure the final count; do not copy the estimate below.

---

# CG-65 — Tasks 1–9

## Task 1 — One home for the owner-only chmod primitive

`journal.py` already applies `0600` correctly — inside the `open()` context,
before the first write. Two more call sites now need it, so promote the helper
rather than copy it.

**`src/chat_gateway/journal.py`** — rename and re-document:

```python
def chmod_owner_only(path: Path) -> None:
    """Owner-only, best effort. Never fatal: a filesystem that cannot express
    the mode (a Windows dev box, an odd bind mount) is not a reason to refuse to
    write — the deploy runbook sets the directory mode, which is the control
    that actually holds on the Linux target.

    Public since CG-65: `inbox.py`'s audit trail and `delivery.py`'s delivery
    log were both created 0644 by doing nothing, and the fix is this exact
    primitive applied in this exact place — inside the `open()` context, before
    the first payload byte, so there is no window at 0644. One home, because a
    second copy of a security control is how the two drift apart.
    """
    try:
        os.chmod(path, _FILE_MODE)
    except OSError:
        pass
```

Update the **three** existing call sites in `journal.py` (`_append`,
`close_many`, `_compact_locked`) from `_chmod_quietly(...)` to
`chmod_owner_only(...)`. There is no alias — a private name kept alive beside
its public replacement is the drift this task exists to prevent.

Also update `_FILE_MODE`'s comment, which says "The journal carries message
bodies", to note it now governs the audit trails too:

```python
#: The journal and both audit trails carry message bodies or whole inbound
#: events (see the module docstring, and CG-65), so they are created owner-only.
#: A no-op for group/other on Windows, which is fine: the mode matters on the
#: Linux deploy target.
_FILE_MODE = 0o600
```

**Verify:** `python3 -m pytest tests/test_journal.py` stays green, and
`grep -rn "_chmod_quietly" src/` returns nothing.

---

## Task 2 — `0600` on the per-app inbound audit trail

The larger of the two exposures (ADR §2.5 finding 3): world-readable, and it
holds `text`, `sender_email` and whole `raw` events.

**`src/chat_gateway/inbox.py`** — add `os` to the imports, import the helper,
and rewrite `_audit`:

```python
import os
```

```python
from .journal import chmod_owner_only
```

```python
    def _audit(self, reply: InboundReply) -> None:
        if self._audit_dir is None:
            return
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        day = dt.date.today().isoformat()
        path = self._audit_dir / f"{reply.app}-{day}.jsonl"
        record = reply.model_dump(mode="json")
        # CG-65 / ADR-0002 D5. This file holds a human's `text`, `sender_email`
        # and whole `raw` event, and it was created 0644 by doing nothing while
        # the journal beside it — holding strictly less — was 0600. The chmod
        # goes INSIDE the open() context and BEFORE the first write, so there is
        # no window in which payload bytes sit world-readable. Same discipline
        # as journal.py; same primitive, not a second copy of it.
        existed = path.exists()
        with path.open("a", encoding="utf-8") as fh:
            if not existed:
                chmod_owner_only(path)
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
```

⚠ **Circular-import check.** `journal.py` imports nothing from `inbox.py`, so
this direction is safe. Confirm with
`python3 -c "import sys; sys.path.insert(0,'src'); import chat_gateway.inbox"`.

**Test** (`tests/test_durability.py`):

```python
def test_inbox_audit_file_is_owner_only_from_the_first_byte(tmp_path):
    """CG-65: the audit trail holds sender_email and raw; 0644 was the larger
    of the two on-disk exposures ADR-0002 measured."""
    ibx = Inbox(audit_dir=tmp_path / "inbox-data")
    ibx.put(_reply(app="job-hunter", text="APPROVE role 42"))
    audit = next((tmp_path / "inbox-data").glob("*.jsonl"))
    assert stat.S_IMODE(audit.stat().st_mode) == 0o600
    # and the mode survives a second append rather than being reset
    ibx.put(_reply(app="job-hunter", text="DECLINE role 43"))
    assert stat.S_IMODE(audit.stat().st_mode) == 0o600
```

---

## Task 3 — `0600` on the delivery log's audit trail

ADR **D7** scopes this file's *content* out (titles-only, permanent, by
decision) but its **mode** in.

**`src/chat_gateway/delivery.py`** — import the helper and rewrite the audit
block of `DeliveryLog.record`:

```python
from .journal import chmod_owner_only
```

```python
        if self._audit_dir:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            path = self._audit_dir / f"deliveries-{source}-{now.date().isoformat()}.jsonl"
            # CG-65 / ADR-0002 D5. Titles-only, so this is a smaller exposure
            # than the inbox audit — but `title[:200]` and `detail[:300]` can
            # still carry sensitive state (aitrader Feature 3 is the reason this
            # class is titles-only in the first place), and there is no reason
            # for it to be the one artifact under the state dir left at 0644.
            existed = path.exists()
            with path.open("a", encoding="utf-8") as fh:
                if not existed:
                    chmod_owner_only(path)
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

**Test:**

```python
def test_delivery_audit_file_is_owner_only(tmp_path):
    log = DeliveryLog(audit_dir=tmp_path / "deliveries")
    log.record("aitrader", "notify", "HALT: AAPL", "enqueued")
    audit = next((tmp_path / "deliveries").glob("*.jsonl"))
    assert stat.S_IMODE(audit.stat().st_mode) == 0o600
```

---

## Task 4 — Compact the outbound journal on drain

ADR-0002 **D1**, off §4 Option D's sketch.

**`src/chat_gateway/delivery.py::_finish`** — replace the whole method:

```python
    def _finish(self, job: Job, status: str, detail: str) -> None:
        self._log.record(job.source, job.kind, job.title, status, detail,
                         entry_id=job.entry_id)
        # THE MID-FLIGHT WINDOW, stated rather than hidden: the send has
        # returned, the log record is written, and the `close` is not. A process
        # killed here replays the job and delivers it TWICE. Deliberate — Chat
        # gives us no idempotency key, so the alternative is a two-phase commit
        # we are not building, and losing an alert is the worse failure.
        self._journal_write(lambda: self._journal.close(job.entry_id, status), "close")
        with self._lock:
            if job in self._jobs:
                self._jobs.remove(job)
            drained = not self._jobs
        # CG-65 / ADR-0002 D1 — compact when the live set drains.
        #
        # A `close` record does NOT erase a payload: it appends a line saying
        # the id is done while the `open` line carrying the body stays where it
        # was. ADR-0002 §2.2 measured the consequence — a DELIVERED body sat on
        # disk for ~500 gateway-wide notifies, which at this design's assumed
        # traffic shape is three to eight WEEKS. A terminal job's payload has no
        # replay value whatsoever, so that retention was a cost with no matching
        # benefit; this collapses it to seconds.
        #
        # `compact([])` truncates the file to zero lines — measured, not assumed.
        # `_maybe_compact_locked`'s 1000-append trigger STAYS as the backstop for
        # a queue that never drains.
        #
        # THE HONEST COST, kept here rather than only in the ADR: one stuck job
        # pins every other tenant's delivered body on disk until it terminates,
        # because the set never empties. Bounded by the ~73-minute retry ladder,
        # or by REPLAY_MAX_AGE_S (24h) across gateway downtime.
        if drained:
            self._journal_write(lambda: self._journal.compact([]), "compact")
```

⚠ `drained` is computed **inside** the lock and acted on outside it, matching
`_journal_write`'s existing posture (it must never be called under the lock — a
journal write can block on fsync).

**Tests:**

```python
def test_delivered_body_is_erased_when_the_queue_drains(tmp_path):
    """ADR-0002 §2.2 measured weeks; D1 makes it seconds."""
    jpath = tmp_path / "delivery.jsonl"
    d = Dispatcher({"webhook": _OkAdapter()}, DeliveryLog(), journal=Journal(jpath))
    d.enqueue("aitrader", "notify", _identity(), _message("HALT AAPL 4200sh"), "HALT")
    assert "HALT AAPL 4200sh" in jpath.read_text()
    d.process_due()
    assert d.pending() == 0
    assert jpath.read_text() == ""            # zero lines, body gone


def test_a_stuck_job_pins_the_other_bodies_until_it_terminates(tmp_path):
    """The honest cost of D1, pinned as a test rather than left as a comment."""
    jpath = tmp_path / "delivery.jsonl"
    adapters = {"webhook": _OkAdapter(), "app": _FailAdapter()}
    d = Dispatcher(adapters, DeliveryLog(), journal=Journal(jpath))
    d.enqueue("jobhunt", "notify", _identity(mode="app"), _message("STUCK"), "stuck")
    d.enqueue("aitrader", "notify", _identity(), _message("QUIET TENANT BODY"), "ok")
    d.process_due()
    # the aitrader job delivered and closed, but the set never drained
    assert d.pending() == 1
    assert "QUIET TENANT BODY" in jpath.read_text()


def test_the_append_count_backstop_still_fires_for_a_queue_that_never_drains(tmp_path):
    jpath = tmp_path / "delivery.jsonl"
    d = Dispatcher({"webhook": _OkAdapter(), "app": _FailAdapter()}, DeliveryLog(),
                   journal=Journal(jpath, compact_after=6))
    d.enqueue("jobhunt", "notify", _identity(mode="app"), _message("STUCK"), "stuck")
    for _ in range(8):
        d.process_due()
    assert d.pending() == 1                   # never drained
    assert len(jpath.read_text().splitlines()) < 8   # backstop compacted anyway
```

---

## Task 5 — Compact the inbox journal on drain

The mirror image, and it carries a trap the outbound side does not.

**`src/chat_gateway/inbox.py::poll`** — replace the whole method:

```python
    def poll(self, app_id: str) -> list[InboundReply]:
        with self._lock:
            q = self._pending[app_id]
            items = list(q)
            q.clear()
            ids = list(self._ids_by_app[app_id])
            self._ids_by_app[app_id].clear()
            # ACROSS EVERY APP, not just this one. There is ONE inbox.jsonl for
            # the whole gateway, so compacting because *this* app's queue is
            # empty would truncate another app's still-pending replies out of
            # existence — a silent inbound loss, which is the exact failure the
            # journal was added to prevent. The outbound twin has no equivalent
            # trap because `_jobs` is already one flat list.
            drained = not any(self._pending.values())
        # One append for the whole batch, so a crash part-way cannot close some
        # of a poll's replies and replay the rest — see Journal.close_many.
        self._journal_write(lambda: self._journal.close_many(ids, "polled"), "close_many")
        # CG-65 / ADR-0002 D1, the mirror image of `Dispatcher._finish`: a
        # POLLED reply has no replay value, and a `close` does not erase its
        # body — only compaction does.
        if drained:
            self._journal_write(lambda: self._journal.compact([]), "compact")
        return items
```

**Tests:**

```python
def test_polled_reply_body_is_erased_when_the_inbox_drains(tmp_path):
    jpath = tmp_path / "inbox.jsonl"
    ibx = Inbox(journal=Journal(jpath))
    ibx.put(_reply(app="job-hunter", text="APPROVE role 42"))
    assert "APPROVE role 42" in jpath.read_text()
    ibx.poll("job-hunter")
    assert jpath.read_text() == ""


def test_polling_one_app_never_erases_another_apps_pending_reply(tmp_path):
    """The one-file trap: compaction is gateway-wide, the poll is per-app."""
    jpath = tmp_path / "inbox.jsonl"
    ibx = Inbox(journal=Journal(jpath))
    ibx.put(_reply(app="job-hunter", text="POLLED SOON"))
    ibx.put(_reply(app="aiteam-harness", text="STILL PENDING"))
    ibx.poll("job-hunter")
    assert "STILL PENDING" in jpath.read_text()
    # and it survives a restart
    revived = Inbox(journal=Journal(jpath))
    assert revived.restore() == 1
    assert revived.pending_counts() == {"aiteam-harness": 1}
```

---

## Task 6 — ⚠ The quarantine: what replaces "the only copy"

**This is the gate.** Spec §3 R2, answering ADR-0002 §9 Q6. Without it, Task 10
deletes the last copy of a reply that was never delivered.

**`src/chat_gateway/inbox.py::__init__`** — add the directory and two counters:

```python
    def __init__(self, audit_dir: str | Path | None = None, max_pending: int = 1000,
                 journal=None, quarantine_dir: str | Path | None = None):
```

```python
        #: Where an unrevivable journal record is preserved. None keeps this
        #: object exactly what it was before CG-65, which is what every offline
        #: test constructs — the same opt-in posture as `journal`.
        self._quarantine_dir = Path(quarantine_dir) if quarantine_dir else None
        #: Unrevivable records successfully preserved, and quarantine writes
        #: that failed. Both reach /healthz: a recovery mechanism that has
        #: silently stopped working is worse than none, because it is trusted.
        self.quarantined = 0
        self.quarantine_write_errors = 0
```

**`src/chat_gateway/inbox.py`** — new method:

```python
    def _quarantine(self, rec: dict) -> bool:
        """Preserve an unrevivable journal record before compaction erases it.

        CG-65, answering ADR-0002 §9 Q6. The per-app audit trail used to be the
        only surviving copy of a reply that could not be revived — and CG-68
        prunes that trail on a time bound. This method is what makes the pruning
        safe: the record, PAYLOAD INCLUDED, is already in hand at the drop site,
        so preserving it costs one append. Without it, `restore` drops the
        record and `compact` erases the journal's copy moments later.

        Never swept — `retention.py` does not look in this directory, and that
        is the point of it existing.

        Best-effort, and counted rather than raised: a quarantine write that
        fails must not stop a boot. The console line below says which branch
        happened, because "the recovery record exists" is exactly the kind of
        claim that must not be asserted when it is false.
        """
        if self._quarantine_dir is None:
            return False
        try:
            self._quarantine_dir.mkdir(parents=True, exist_ok=True)
            path = self._quarantine_dir / f"unrevivable-{dt.date.today().isoformat()}.jsonl"
            existed = path.exists()
            with path.open("a", encoding="utf-8") as fh:
                if not existed:
                    chmod_owner_only(path)
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except Exception as exc:  # noqa: BLE001 — recovery degrades, boot does not stop
            self.quarantine_write_errors += 1
            print(f"inbox: quarantine write FAILED ({describe_exception(exc)}); "
                  "an unrevivable reply has no preserved copy", flush=True)
            return False
        self.quarantined += 1
        return True
```

**`src/chat_gateway/inbox.py::restore`** — replace the `except` branch:

```python
                except Exception as exc:  # noqa: BLE001 — config/envelope drift, not a bug
                    self.unrevivable += 1
                    preserved = self._quarantine(rec)
                    print(f"inbox: journalled reply {rec['id']!r} no longer parses "
                          f"({describe_exception(exc)}) — DROPPED, not delivered; "
                          + ("the whole record was preserved in the quarantine dir "
                             "under the state dir, which is never pruned"
                             if preserved else
                             "NO quarantine copy was written — the per-app JSONL "
                             "audit under the inbox dir is the only recovery record, "
                             "and it is subject to the retention window"),
                          flush=True)
                    continue
```

And update the **docstring** of `restore`, which currently names the audit trail
as the recovery record (promise site 4 — spec §2.5):

```
        **The quarantine file under the state dir is the recovery record** — the
        whole journal record, payload included, is written there before boot
        compaction erases it, and it is never pruned. The per-app JSONL audit
        beside this queue also holds what arrived, but it is subject to a
        retention window (CG-68) and cannot be relied on as the only copy.
```

**`src/chat_gateway/__main__.py::build_runtime`** — wire it:

```python
    inbox = Inbox(audit_dir=os.environ.get("CHAT_GATEWAY_INBOX_DIR", "inbox-data"),
                  journal=Journal(Path(state_dir) / "queue" / "inbox.jsonl"),
                  # CG-65: unrevivable replies are preserved here rather than
                  # only pointed at in another file. Under the state dir, beside
                  # the journals, because it is queue-recovery material — not an
                  # audit record of what arrived.
                  quarantine_dir=Path(state_dir) / "quarantine")
```

**Tests:**

```python
def test_unrevivable_reply_is_preserved_in_quarantine(tmp_path):
    """CG-65 / ADR-0002 Q6: the gateway keeps the bytes it is holding instead of
    pointing at a file the sweeper may delete."""
    jpath = tmp_path / "inbox.jsonl"
    Journal(jpath).open(1, "inbound", {"app": "job-hunter", "NOT": "an InboundReply"})
    ibx = Inbox(journal=Journal(jpath), quarantine_dir=tmp_path / "quarantine")
    assert ibx.restore() == 0
    assert ibx.unrevivable == 1 and ibx.quarantined == 1
    qfile = next((tmp_path / "quarantine").glob("unrevivable-*.jsonl"))
    assert "NOT" in qfile.read_text()
    assert stat.S_IMODE(qfile.stat().st_mode) == 0o600
    assert jpath.read_text() == ""       # journal's own copy is gone, as before


def test_quarantine_is_opt_in_and_absence_is_reported_honestly(tmp_path, capsys):
    jpath = tmp_path / "inbox.jsonl"
    Journal(jpath).open(1, "inbound", {"bad": "record"})
    ibx = Inbox(journal=Journal(jpath))          # no quarantine_dir
    ibx.restore()
    assert ibx.unrevivable == 1 and ibx.quarantined == 0
    assert "NO quarantine copy" in capsys.readouterr().out
```

---

## Task 7 — Surface the quarantine at `/healthz`

Hard rule #5. This is also what makes promise **site 6** true again.

**`src/chat_gateway/service.py`** — extend the `inbox` block:

```python
            "inbox": {"pending": inbox.pending_counts(), "dropped": inbox.dropped,
                      "replayed_at_boot": getattr(inbox, "replayed", 0),
                      # The inbound twin of delivery's `unroutable_at_boot`:
                      # ... (keep the existing comment verbatim)
                      "unrevivable_at_boot": getattr(inbox, "unrevivable", 0),
                      # CG-65. How many of those were preserved. Two numbers,
                      # not one: `unrevivable` is what was lost from the queue,
                      # `quarantined` is what is recoverable, and an operator
                      # reading the first needs the second to know whether to
                      # go looking.
                      "quarantined_at_boot": getattr(inbox, "quarantined", 0),
                      "quarantine_write_errors": getattr(inbox, "quarantine_write_errors", 0)},
```

Replace the `unrevivable_at_boot` reasons block:

```python
        if body["inbox"]["unrevivable_at_boot"]:
            preserved = body["inbox"]["quarantined_at_boot"]
            reasons.append(
                f"inbox replay dropped {body['inbox']['unrevivable_at_boot']} "
                "journalled reply(ies) that no longer parse as an InboundReply — "
                "they were NOT delivered to the owning app and are gone from the "
                "queue journal. An envelope change across a deploy looks like "
                f"this. {preserved} of them were preserved in full under the "
                "state dir's quarantine dir, which is never pruned and is the "
                "recovery record; the ids are on the boot console"
            )
```

Add a reason for a failed quarantine write:

```python
        if body["inbox"]["quarantine_write_errors"]:
            reasons.append(
                f"inbox quarantine: {body['inbox']['quarantine_write_errors']} "
                "write(s) FAILED — at least one unrevivable reply has no "
                "preserved copy, so the per-app JSONL audit under the inbox dir "
                "is its only record and the retention window applies to it. "
                "Check free space and the state dir's permissions"
            )
```

**Test** (`tests/test_service.py`, alongside the existing `/healthz` tests):

```python
def test_healthz_names_the_quarantine_as_the_recovery_record(tmp_path):
    """Promise site 6: this reasons line told an operator to read a file the
    sweeper is about to delete. It now names an artifact the gateway keeps."""
    jpath = tmp_path / "inbox.jsonl"
    Journal(jpath).open(1, "inbound", {"app": "job-hunter", "NOT": "an InboundReply"})
    inbox = Inbox(journal=Journal(jpath), quarantine_dir=tmp_path / "quarantine")
    inbox.restore()
    client = TestClient(_app_with(inbox=inbox))

    body = client.get("/healthz").json()
    assert body["inbox"]["unrevivable_at_boot"] == 1
    assert body["inbox"]["quarantined_at_boot"] == 1
    assert body["inbox"]["quarantine_write_errors"] == 0
    assert body["status"] == "degraded"
    line = next(r for r in body["reasons"] if "unrevivable" in r or "no longer parse" in r)
    assert "quarantine" in line and "never pruned" in line
    # and it must NOT still point at the per-app audit trail as the only copy
    assert "only recovery record" not in line
```

⚠ `_app_with` is this file's existing `create_app` helper — reuse it rather than
building a second one.

---

## Task 8 — `docs/consumers/aitrader.md`: the contract correction

⚠ **Do not soften this into "the journal is secure."** State what reaches disk,
for how long, and at what mode. Eight items, spec §6.

**8a — `:213-217`, the scope note.** The `/v1/messages` carve-out is **inverted**
(ADR §2.8) — correct it, do not delete it. Replace the block ending in *"no body
text of yours is ever written anywhere"* with:

> **One honest scope note, and it now points the other way.** `/v1/messages` —
> which your key can call but your contract does not use — logs `text[:80]` as a
> delivery-log title, and that log is **permanent**. `/v1/notify`, the endpoint
> your contract is built on, writes **more** and keeps it for **less**: since
> 2026-07-31 the durable queue journals the whole rendered message — `text` and
> `cards` — to `<CHAT_GATEWAY_STATE_DIR>/queue/delivery.jsonl`, file mode `0600`.
>
> **How long: only while the alert is undelivered.** Normally well under a
> second. Up to ~73 minutes if it is working through the retry ladder, and up to
> 24 hours if the gateway is down (past that it is closed as `expired` rather
> than sent). The journal is erased the moment the outbound queue drains.
> **One caveat, stated rather than buried:** a single stuck job anywhere on the
> gateway holds that drain open, so a delivered body of yours can persist until
> the stuck job terminates — bounded by the same ~73 minutes, or 24 hours across
> downtime.
>
> **No credential is written.** The journal stores the identity **name** and
> re-resolves it through the registry at boot, so no webhook URL and no API key
> reaches it (hard rule #2).
>
> ⚠ **This replaces a sentence that promised the opposite.** Until 2026-07-31
> this note read *"if you never call `/v1/messages`, no body text of yours is
> ever written anywhere."* That became false when the queue was made durable.
> The decision to keep the durability and rewrite the promise — rather than stop
> journalling your bodies and lose replay for the one tenant with no fallback
> channel — is recorded in
> [ADR-0002](../architecture/decisions/2026-07-31-journalled-message-bodies.md).

**8b — `:219`** — replace *"Restart drops undelivered jobs. The queue is
in-memory."* with the durable behaviour: replayed at boot with the attempt count
preserved; older than 24h closed as `expired`; identity re-resolved so a
withdrawn grant closes it `unroutable`; a mid-flight job may deliver **twice**.
**Do not restate the replay rule in detail** — `delivery.py`'s docstring is its
one home. Link and summarize in one sentence.

**8c — `:547`** — the same claim under *"Accepted limitations, agreed in the
contract."* Replace the bullet with the accepted limitation that is actually
true now: *a mid-flight restart may deliver an alert twice — Chat has no
idempotency key, and losing an alert was judged the worse failure.* Keep "keep
your local fallback log."

**8d — `:418`** — *"Nothing about aitrader's traffic is persisted anywhere, in
any configuration"* needs the `_unrouted` caveat (ADR §2.7) **and** must not
contradict 8a. Rewrite as a scoped claim: nothing about aitrader's traffic
crosses to a consumer or is persisted **as aitrader's** — the `continue` fires
before any `inbox.put` — with the two named exceptions: outbound bodies in the
queue journal (8a), and an event that `normalize_event` cannot parse, which has
no attributable space and is audited under `_unrouted` with its `raw` intact.
**Keep the existing note that this is the claim the contract rests on, and that
it has now survived three corrections.**

**8e — `:442`** — the `/healthz` guidance. It currently says a `degraded`
reading is a tier-2 concern leaving *"your alerting unaffected."* Add that
**five** outbound-queue fields can now degrade it (`expired_at_boot`,
`unroutable_at_boot`, `unrevivable_at_boot`, `journal_skipped_lines`,
`journal_write_errors`) and that each means an aitrader alert was dropped or will
be double-sent. Keep the two identity/key fields as the ones that gate readiness.
⚠ **Five fields, four `reasons` lines** — `expired` and `unroutable` share one.
CG-64's Builder got this count wrong; do not repeat it.

**8f — `:569`** — env table. `CHAT_GATEWAY_STATE_DIR` is no longer *"heartbeat
checks + delivery JSONL"*: it holds heartbeat checks, the delivery log, **the
queue journals (message bodies, `0600`)** and **the quarantine dir**.

**8g — `:209`** — `delivery.py:44-50` → **`delivery.py:77-91`**. The claim is
still correct; only the pointer drifted.

**8h — §10 verification status** — ⚠ **change nothing.** No ⚠ flag is cleared,
added or reworded by this row. If a sentence there needs the ledger, **link** to
`CLAUDE.md`.

---

## Task 9 — `docs/integration-guide.md` + `CLAUDE.md`

**9a — `integration-guide.md:378-383`.** Promise site 2. Replace *"and the audit
file is then the only copy"*:

> Both stay; neither substitutes for the other. One consequence is worth
> planning for: a journalled reply that no longer validates as an `InboundReply`
> at boot — an envelope change across a deploy looks precisely like this — is
> **dropped, not delivered**, and counted at `/healthz` →
> `inbox.unrevivable_at_boot`, which degrades the endpoint. It is not resent.
> **The whole record is preserved**, payload included, under the state dir's
> `quarantine/` directory, which is **never pruned** and is the recovery record;
> `/healthz` → `inbox.quarantined_at_boot` says how many were preserved, and
> `inbox.quarantine_write_errors` is non-zero if that ever failed.

**9b — the `/healthz` durability table.** Add two rows and update the counts.
The section says *"Seven fields arrived with the journals"* and *"five of them
can flip `status`"*; with `quarantined_at_boot` (no) and
`quarantine_write_errors` (**yes**) that becomes **nine fields, six that
degrade**. Recount against `service.py` rather than trusting this sentence.

| Field | What it means | Degrades? |
|---|---|---|
| `inbox.quarantined_at_boot` | unrevivable replies preserved in full under the state dir's `quarantine/`, which is never pruned | no — the recovery mechanism working |
| `inbox.quarantine_write_errors` | quarantine writes that **failed**; an unrevivable reply has no preserved copy | **yes** |

**9c — `CLAUDE.md`, the CG-54 bullet.** Name the retention property, not just
"durable." **One sentence, no second copy of the numbers** — the residency
figures live in ADR-0002 §2.2 and the contract text, and this file's own history
is the argument against a third home. Suggested addition:

> **Retention, not just durability (CG-65, 2026-07-31):** a journalled body now
> lives exactly as long as its job is replayable — the journal compacts when the
> queue drains, so a *delivered* body's residency fell from the weeks ADR-0002
> §2.2 measured to seconds. Both audit trails are created `0600`. An unrevivable
> reply is preserved under `<state_dir>/quarantine/`, which is never pruned,
> because the per-app audit trail stopped being *"the only copy"* the moment it
> gained a retention window. Numbers and reasoning: ADR-0002 — **not restated
> here.**

**9d** — do **not** touch `integration-guide.md:366` in this row. Task 13.

---

## CG-65 gates

- Full suite green. Estimate **247 → ~267**; measure and report the real number.
- `grep -rn "_chmod_quietly" src/` → empty.
- No diff under `docs/architecture/` or `src/chat_gateway/adapters/`.
- `grep -c "LIVE-UNVERIFIED\|SHAPE-VERIFIED" src/ -r` unchanged from base.
- Manual: `python3 -m chat_gateway serve` against a scratch state dir, one
  `/v1/notify`, confirm `state/queue/delivery.jsonl` is empty after delivery and
  every audit file is `0600`.

---

# CG-68 — Tasks 10–13 ⏸ MERGE-GATED

> ✅ **The four decisions are made (A1–A4 above, user, 2026-07-31).** The window
> is **30 / 7 / 0** and the constants in Task 10 are already written to it — they
> and every doc number in Task 13 must not disagree.
>
> ⚠ **One gate remains and it is sequencing, not approval: CG-65 must be MERGED
> before this row starts.** Task 6's quarantine is what makes pruning safe.

## Task 10 — `src/chat_gateway/retention.py`

```python
"""Time-bounded retention for the per-app inbound audit trail.

CG-68 / ADR-0002 D5. `inbox-data/<app>-<date>.jsonl` held a human's `text`,
`sender_email` and whole `raw` event forever. CG-65 fixed the mode; this fixes
the "forever".

TIME-BOUNDED IN DAYS, NEVER COUNT-BOUNDED, and that is not a style choice.
ADR-0002 §2.2 measured that the journal's count-bound yields a retention nobody
can convert to a date — "500 gateway-wide notifies" is not a sentence that can go
in a consumer contract, and turning it into one took a parameterised table and a
paragraph of arithmetic. A retention policy on human message content has to be
expressible as "N days", because that is the unit a contract, a privacy posture
and a subject-access request are all written in.

THE FILENAME IS THE RETENTION KEY. `<app>-<date>.jsonl` is already sharded by
exactly the right dimension, so pruning is a directory listing and an unlink —
no parsing, no rewrite, and nothing here ever opens a file holding message
bodies in order to decide whether to delete it.

WHAT THIS NEVER TOUCHES, and why each one is deliberate:
  - `<state_dir>/quarantine/` — the preserved copy of a reply that could not be
    revived (CG-65). Pruning it would delete the last copy of something that was
    never delivered, which is the whole reason ADR-0002 §9 Q6 was a gate.
  - `<state_dir>/deliveries/` — titles-only and permanent by decision (D7).
  - `<state_dir>/queue/` — the journals compact themselves.

A FILE WHOSE NAME THIS MODULE CANNOT PARSE IS LEFT ALONE, never guessed at.
Deleting an unrecognized file from a directory that holds message bodies is the
one failure mode worse than keeping it too long.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import threading
from pathlib import Path

#: Default window for a tenant's bucket. A calendar month is the unit a privacy
#: posture is written in. The gateway does NOT need to hold a consumer's own
#: decision history: docs/integration-guide.md already tells consumers this file
#: is "a forensic record on the gateway host, not something you can re-poll", so
#: a consumer that needs that history keeps its own.
DEFAULT_RETENTION_DAYS = 30

#: `_unrouted` answers to no tenant — it accumulates whole unattributable `raw`
#: events with no consent story — so it gets the shortest window in the
#: directory. This stays hard-rule-#1-clean because `_unrouted` is the gateway's
#: OWN reserved bucket (hard rule #6 reserves the `_` prefix for exactly this),
#: not per-app policy. A per-TENANT window would be ADR-0002 Option C's shape
#: and would re-open a question the user deliberately left not-reached (D6).
UNROUTED_RETENTION_DAYS = 7

#: How often the background sweep runs. Six hours, not daily: a boot-only sweep
#: is no sweep at all on a host running `restart: unless-stopped` — the same
#: reasoning journal.py gives for not relying on boot compaction.
SWEEP_INTERVAL_S = 6 * 3600

_NAME = re.compile(r"^(?P<app>.+)-(?P<date>\d{4}-\d{2}-\d{2})\.jsonl$")


def retention_days_from_env(environ: dict | None = None) -> int:
    """`CHAT_GATEWAY_INBOX_RETENTION_DAYS`, or the default. **0 disables pruning.**

    The zero case is the escape hatch that restores pre-CG-68 behaviour exactly,
    so a deployment can decline the contract amendment without a code change.

    A malformed value falls back to the default and SAYS SO rather than raising:
    a boot that refuses to start over a typo in a retention knob is a worse
    outcome than one that retains for the documented default.
    """
    env = os.environ if environ is None else environ
    raw = (env.get("CHAT_GATEWAY_INBOX_RETENTION_DAYS") or "").strip()
    if not raw:
        return DEFAULT_RETENTION_DAYS
    try:
        value = int(raw)
    except ValueError:
        print(f"retention: CHAT_GATEWAY_INBOX_RETENTION_DAYS={raw!r} is not an "
              f"integer — using the default of {DEFAULT_RETENTION_DAYS} days",
              flush=True)
        return DEFAULT_RETENTION_DAYS
    return max(0, value)


def window_for(app: str, days: int) -> int:
    """Effective window for one bucket.

    Lowering the configured knob lowers `_unrouted` too; raising it never
    loosens the ownerless bucket past its own floor.
    """
    if app.startswith("_"):
        return min(days, UNROUTED_RETENTION_DAYS)
    return days


class RetentionSweeper:
    """Boot-time + periodic prune of the per-app inbound audit trail.

    Its own thread rather than a hook on the dispatcher's 1s tick: `sweep()`
    stays a pure, directly-testable function, and deletion never sits in the
    delivery hot path. Same start/stop idiom as `Dispatcher` and `SubscriberLoop`.
    """

    def __init__(self, audit_dir: str | Path | None, days: int | None = None,
                 now_fn=None, interval_s: float = SWEEP_INTERVAL_S):
        self._dir = Path(audit_dir) if audit_dir else None
        self._days = DEFAULT_RETENTION_DAYS if days is None else days
        self._now = now_fn or (lambda: dt.datetime.now(dt.timezone.utc))
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        #: Files deleted since start, and unlinks that failed. Both reach
        #: /healthz: hard rule #5 does not distinguish work DROPPED from work
        #: DELETED, and a silent deletion path on an artifact two documents
        #: called "the only copy" is exactly the shape of failure it exists for.
        self.deleted = 0
        self.errors = 0
        self.last_sweep_at: str | None = None

    @property
    def days(self) -> int:
        return self._days

    def sweep(self) -> int:
        """Unlink day-files past their bucket's window. Returns how many."""
        if self._dir is None or self._days <= 0 or not self._dir.exists():
            return 0
        today = self._now().date()
        removed = 0
        for path in sorted(self._dir.glob("*.jsonl")):
            match = _NAME.match(path.name)
            if match is None:
                continue                      # never guess at a name we do not own
            try:
                stamp = dt.date.fromisoformat(match.group("date"))
            except ValueError:
                continue
            if (today - stamp).days <= window_for(match.group("app"), self._days):
                continue
            try:
                path.unlink()
            except OSError as exc:
                self.errors += 1
                print(f"retention: could not remove {path.name} ({exc})", flush=True)
                continue
            removed += 1
        self.deleted += removed
        self.last_sweep_at = self._now().isoformat()
        return removed

    def _run(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self._interval_s)
            if self._stop.is_set():
                break
            try:
                self.sweep()
            except Exception as exc:  # noqa: BLE001 — the loop must survive
                print(f"retention: sweep error (will retry): {exc}", flush=True)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="retention-sweeper",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
```

**Tests** (new `tests/test_retention.py`):

```python
import datetime as dt

from chat_gateway.retention import (DEFAULT_RETENTION_DAYS, RetentionSweeper,
                                    retention_days_from_env, window_for)


def _at(iso_date: str):
    """A fixed `now` — these tests are about date arithmetic, not the clock."""
    return dt.datetime.fromisoformat(iso_date).replace(tzinfo=dt.timezone.utc)


def _touch(d, name, text="{}\n"):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)


def test_prunes_past_the_window_and_keeps_inside_it(tmp_path):
    d = tmp_path / "inbox-data"
    _touch(d, "job-hunter-2026-06-01.jsonl")   # 60 days old
    _touch(d, "job-hunter-2026-07-20.jsonl")   # 11 days old
    s = RetentionSweeper(d, days=30, now_fn=lambda: _at("2026-07-31"))
    assert s.sweep() == 1
    assert [p.name for p in d.glob("*.jsonl")] == ["job-hunter-2026-07-20.jsonl"]


def test_unrouted_gets_the_shorter_window(tmp_path):
    d = tmp_path / "inbox-data"
    _touch(d, "_unrouted-2026-07-20.jsonl")    # 11 days — inside 30, outside 7
    _touch(d, "job-hunter-2026-07-20.jsonl")
    s = RetentionSweeper(d, days=30, now_fn=lambda: _at("2026-07-31"))
    assert s.sweep() == 1
    assert [p.name for p in d.glob("*.jsonl")] == ["job-hunter-2026-07-20.jsonl"]


def test_zero_days_disables_pruning_entirely(tmp_path):
    d = tmp_path / "inbox-data"
    _touch(d, "job-hunter-2020-01-01.jsonl")
    assert RetentionSweeper(d, days=0, now_fn=lambda: _at("2026-07-31")).sweep() == 0
    assert list(d.glob("*.jsonl"))


def test_an_unparseable_filename_is_left_alone_never_guessed_at(tmp_path):
    d = tmp_path / "inbox-data"
    _touch(d, "notes.jsonl")
    _touch(d, "job-hunter-not-a-date.jsonl")
    s = RetentionSweeper(d, days=1, now_fn=lambda: _at("2026-07-31"))
    assert s.sweep() == 0
    assert len(list(d.glob("*.jsonl"))) == 2


def test_the_quarantine_dir_is_never_swept(tmp_path):
    """The CG-65 gate, pinned: retention points at inbox-data, never at state/."""
    q = tmp_path / "state" / "quarantine"
    _touch(q, "unrevivable-2020-01-01.jsonl")
    RetentionSweeper(tmp_path / "inbox-data", days=1,
                     now_fn=lambda: _at("2026-07-31")).sweep()
    assert (q / "unrevivable-2020-01-01.jsonl").exists()


def test_malformed_env_falls_back_to_the_default(capsys):
    assert retention_days_from_env({"CHAT_GATEWAY_INBOX_RETENTION_DAYS": "soon"}) == 30
    assert "not an integer" in capsys.readouterr().out
    assert retention_days_from_env({"CHAT_GATEWAY_INBOX_RETENTION_DAYS": "0"}) == 0
    assert retention_days_from_env({}) == 30
```

## Task 11 — Wire the sweeper

**`src/chat_gateway/__main__.py`** — in `build_runtime`, after `inbox`:

```python
    from .retention import RetentionSweeper, retention_days_from_env

    # CG-68 / ADR-0002 D5. Sweeps the per-app inbound AUDIT trail only — never
    # the quarantine dir, never the delivery log, never the queue journals.
    sweeper = RetentionSweeper(os.environ.get("CHAT_GATEWAY_INBOX_DIR", "inbox-data"),
                               days=retention_days_from_env())
```

Return it from `build_runtime` (extend the tuple and **every** unpack site), and
in the `serve` branch, after `inbox.restore()`:

```python
        swept = sweeper.sweep()
        print(f"retention: inbox audit window is {sweeper.days} day(s) "
              f"({'pruning DISABLED' if sweeper.days == 0 else 'enabled'}); "
              f"removed {swept} expired day-file(s) at boot", flush=True)
        sweeper.start()
```

Pass `sweeper=sweeper` into `create_app`, store it as `app.state.sweeper`, and
stop it beside the dispatcher and monitor.

## Task 12 — `/healthz` counters

Rule #5 — *"does not distinguish work dropped from work deleted."*

**`src/chat_gateway/service.py`** — add the import beside the existing ones, and
accept `sweeper` as a `create_app` keyword defaulting to `None` (same opt-in
posture as `dispatcher` and `subscriber`, so every offline test that builds an
app without one keeps working):

```python
from .retention import UNROUTED_RETENTION_DAYS
```

Then add the block to the `/healthz` body:

```python
            "retention": (
                {"enabled": sweeper.days > 0,
                 "window_days": sweeper.days,
                 "unrouted_window_days": min(sweeper.days, UNROUTED_RETENTION_DAYS),
                 "files_deleted": sweeper.deleted,
                 "delete_errors": sweeper.errors,
                 "last_sweep_at": sweeper.last_sweep_at}
                if sweeper is not None
                else {"enabled": False, "note": "no sweeper configured"}
            ),
```

```python
        if body["retention"]["delete_errors"]:
            reasons.append(
                f"retention: {body['retention']['delete_errors']} audit file(s) "
                "could not be removed — the inbound audit trail is growing past "
                "its stated window. Check the inbox dir's permissions"
            )
```

⚠ **`files_deleted` must NOT degrade `status`** — a retention policy working is
not a fault, and degrading on it teaches an operator to ignore `degraded`. Same
reasoning `CLAUDE.md` records for `suppressed_opt_out`.

## Task 13 — The contract amendment

**13a — `integration-guide.md:366-370`.** Promise site 1. Replace *"never
pruned"*:

> - The per-app **JSONL audit** says what **ARRIVED**. One file per app per day,
>   written before anything is queued, and **retained for a bounded window —
>   30 days by default, 7 days for the gateway's own `_unrouted` bucket**,
>   settable per deployment via `CHAT_GATEWAY_INBOX_RETENTION_DAYS` (`0`
>   disables pruning). It holds no terminal records — nothing in it marks a
>   reply as polled — so **your pending queue cannot be reconstructed from it.**
>   It is a forensic record on the gateway host, not something you can re-poll.
>
>   ⚠ **This changed on 2026-07-31, and it changed a published guarantee.** This
>   line previously read *"never pruned."* That was a v0 over-promise on a file
>   holding a person's message text, `sender_email` and whole `raw` event
>   forever. The window is the amendment; the mechanism that makes it safe is
>   the **quarantine** described below, which is never pruned and holds any
>   reply that could not be revived. Reasoning:
>   [ADR-0002](architecture/decisions/2026-07-31-journalled-message-bodies.md)
>   §4.1 and §9 Q6.

**13b — `journal.py:10`.** Promise site 3, same sentence:

```
NOT THE AUDIT TRAIL, and not a replacement for it. The audit files are
per-app-per-day, retained for a bounded window (retention.py), and carry no
TERMINAL records — they say what ARRIVED, never what LEFT, so pending state
cannot be reconstructed from them. Different question, different file; both stay.
```

**13c — env-var NAME** in `.env.example`, `docs/integration-guide.md`, and
`aitrader.md:569`'s table. ⚠ **`aitrader.md` gets the row but not a window
claim** — aitrader is `allow_inbound: false` and never reaches `inbox.put`
(ADR §2.7), so it has no records in this directory. Say that, so the tenant does
not read a retention window as applying to something of theirs.

**13d — `docs/consumers/jobhunt.md`.** The one tenant with records in this
directory. State the window and point at the quarantine.

## CG-68 gates

- Suite green. Estimate **~266 → ~278**; measure.
- Manual: create dated files by hand in a scratch `inbox-data/`, boot, confirm
  the boot line, the deletions, and that `state/quarantine/` is untouched.
- `grep -rn "never pruned" src/ docs/ --include=*.py --include=*.md` returns
  only the **quarantine** and ADR references.
- No ⚠ flag cleared, added or reworded.
