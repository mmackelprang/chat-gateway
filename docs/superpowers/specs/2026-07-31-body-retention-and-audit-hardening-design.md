# CG-65 — Body retention and audit hardening: shrink the journal window, harden the audit trail, and replace the promise before deleting it

| | |
|---|---|
| **Date** | 2026-07-31 |
| **Status** | ✅ **APPROVED — all four decisions taken by the user, 2026-07-31.** §9 records each with the recommendation it was made against. The only remaining gate is sequencing: **CG-68 waits for CG-65 to merge** |
| **Implements** | [ADR-0002](../../architecture/decisions/2026-07-31-journalled-message-bodies.md) §6 — `D + A + D5`, decided by the user 2026-07-31 |
| **Does not revisit** | D1 (compact on drain), D2 (correct the contract), D3 (B and C rejected), D5 (both exposures, one cycle). Those are decided |
| **Answers** | ADR-0002 §9 **Q6**, which the ADR raised and explicitly did not resolve |
| **Hard rules engaged** | #1 (transport, never schemas), #2 (env-var NAMES), #5 (honest `/healthz`), #6 (inbound opt-in) |
| **Base** | `dced002` (CG-61/#50). Suite **247** — rebased 2026-07-31; the spec was drafted on `b8af699`/246 before CG-61 landed |

> ## The one-paragraph version
>
> ADR-0002 decided to shrink how long a delivered message body sits in the queue
> journal (weeks → seconds) and to harden the never-pruned, world-readable
> `inbox-data/` audit trail. The mode fix and the compaction change are
> mechanical. **The pruning half is not, because six places in this repo — one of
> them a live `/healthz` reasons line — tell an operator that the file pruning
> would delete is "the recovery record" and "the only copy."** This spec
> measures that gap, recommends a replacement mechanism that is *stronger* than
> the promise it retires, and splits the work so the safe 90% ships now and the
> one decision the user must make blocks only the last 10%.

---

## 1. What ADR-0002 already settled — cited, not re-derived

Every measurement below marked *(ADR §n)* was taken by the Architect on
2026-07-31 by executing the shipped classes. This spec does not re-measure them.

- A `close` record **does not erase a payload** (ADR §2.2). A delivered body sits
  in `state/queue/delivery.jsonl` until compaction, which at the design's assumed
  traffic shape is **roughly three to eight weeks**.
- `Dispatcher.restore` compacts at boot, so **restart is currently the only
  prompt eraser** (ADR §2.3) — on a deploy target explicitly configured not to
  restart.
- **No credential reaches any of these files** (ADR §2.1). Identity NAMES only,
  re-resolved through the registry. **Hard rule #2 is intact**, which is why this
  is a contract question and not an incident.
- `inbox-data/<app>-<date>.jsonl` is **`0644`, never pruned, and holds whole
  inbound events including `raw`, `text` and `sender_email`** (ADR §2.5) — the
  *larger* of the two exposures, and it predates #45 by months.
- **The state dataset is a plain ZFS dataset — no snapshots, no replication**
  (ADR §2.9, §9 Q4). This is the fact that made D's erase a real erase.
- **No ⚠ flag is cleared, added or reworded by any of this.** The verification
  ledger lives in [`CLAUDE.md`](../../../CLAUDE.md) and is **linked, never
  restated** — every attempt to restate it in this repo has drifted within two
  PRs.

---

## 2. What this spec measured that the ADR did not — first-hand, 2026-07-31

Five findings, taken by executing `Inbox`, `Journal` and `Dispatcher` against a
temporary directory on the WSL2 dev box. Three of them change the design.

### 2.1 There is no join key between an audit line and a journal record

| | |
|---|---|
| audit line fields | `action`, `app`, `dedupe_key`, `envelope_format`, `event_type`, `message_id`, `raw`, `received_at`, `sender_display`, `sender_email`, `space`, `text`, `thread_key`, `thread_name` |
| journal record fields | `id`, `kind`, `op`, `payload`, `ts`, `v` |
| **does any audit field carry the journal `id`?** | **No** |

`Inbox.put` calls `self._audit(reply)` at `inbox.py:68` and mints
`entry_id = next(self._ids)` at `:69` — **the audit line is written before the id
exists.** So from `inbox-data/` alone you **cannot tell whether a reply was ever
polled.**

**This falsifies two of the four options the brief offered for the recovery gap.**
"A longer retention floor for records with no terminal status" and "a narrower
prune that only removes records provably delivered" are both **not implementable
without changing the audit record's schema** — and that schema is what consumers
read. Recorded here rather than discovered by a Builder mid-task.

### 2.2 `Inbox.restore` has no age ceiling — and `Dispatcher.restore` does

| | |
|---|---|
| `Dispatcher.__init__` params | `adapters`, `log`, `now_fn`, `backoff`, `journal`, **`replay_max_age_s`** |
| `Inbox.__init__` params | `audit_dir`, `max_pending`, `journal` — **no age bound of any kind** |
| `Inbox.restore` mentions `max_age` / `expired` / `REPLAY_MAX` | **No** |

Measured directly: a journalled reply with a timestamp **400 days old** restored
cleanly, alongside a fresh one — `restored=2, unrevivable=0`.

**This is the asymmetry that makes the gate sharp.** The outbound journal has a
24h ceiling (`REPLAY_MAX_AGE_S`), so its recovery window is bounded by
construction. **The inbound journal has none**, so a reply can sit unpolled
indefinitely and fail to revive at *any* future boot. A finite retention window
on `inbox-data/` therefore truncates a recovery path that is **unbounded on the
other side**. ADR §4.1 spotted the coupling (*"prune to 7 days and the
`unrevivable_at_boot` recovery path is 7 days deep"*); it did not measure that
the journal side has no matching bound.

### 2.3 At the moment the gateway declares a record lost, it is holding the record

Measured against a journalled payload that no longer validates:

```
journal record still holds the full payload at drop time:  {'app': 'job-hunter', 'NOT': 'an InboundReply'}
restored / unrevivable:                                    (0, 1)
journal lines AFTER boot compaction:                       0
```

`inbox.py:130` has `rec["payload"]` **in hand** inside the `except` branch. It
prints *"the per-app JSONL audit under the inbox dir is the recovery record"*,
drops the record, and boot compaction at `:159` then erases the gateway's own
copy — **leaving the pointer to a `0644` file that this row is about to start
deleting.**

**This is what makes the recommended fix nearly free.** The bytes do not have to
be recovered from anywhere; they only have to not be thrown away.

### 2.4 Modes, re-confirmed on this base commit

| Path | Mode |
|---|---|
| `inbox-data/<app>-<date>.jsonl` | **`0644`** |
| `state/queue/inbox.jsonl` | `0600` |
| `inbox-data/`, `state/queue/` | `0755` |

Consistent with ADR §2.5. Directory modes are **out of scope here** — CG-53's
runbook line (`install -d -m 0750 …`) owns them, and `mkdir(exist_ok=True)`
preserves a pre-created mode.

### 2.5 The promise has SIX live homes, and one of them is `/healthz`

| # | Site | Wording |
|---|---|---|
| 1 | `docs/integration-guide.md:367` | *"never pruned"* |
| 2 | `docs/integration-guide.md:382-383` | *"the audit file is then the only copy"* |
| 3 | `src/chat_gateway/journal.py:10` | *"per-app-per-day, never pruned"* |
| 4 | `src/chat_gateway/inbox.py:111` | *"the per-app JSONL audit beside this queue is the recovery record"* |
| 5 | `src/chat_gateway/inbox.py:136` | the boot console line — *"the recovery record"* |
| 6 | ⚠ `src/chat_gateway/service.py:478` | **a live `/healthz` `reasons` string** — *"The per-app JSONL audit under the inbox dir holds what arrived and is the recovery record"* |

**Site 6 promotes this from a documentation problem to a hard-rule-#5 problem.**
A sweeper that prunes `inbox-data/` makes an unauthenticated health endpoint
instruct an operator to go read a file the gateway itself deleted. Rule #5 exists
because a hardcoded health check hid 11 days of silent failure; an endpoint that
points at a deleted artifact is the same defect with extra steps.

*(`service.py:462` names the JSONL audits **under the state dir** — that is
`state/deliveries/`, which ADR D7 keeps unpruned. It is unaffected.)*

---

## 3. ⚠ The gate — what replaces the recovery guarantee

**Pruning must not merge until something named replaces the "only copy"
guarantee.** Four candidates, costed.

### R1 — Retention floor for records with no terminal status

| | |
|---|---|
| **Costs** | ⛔ **Not implementable as scoped.** §2.1 — the audit line carries no journal id, so "has no terminal status" is not computable from `inbox-data/`. Requires adding an id to the audit record, which changes a schema consumers read |
| **Buys** | Would be precise, if it worked |
| **Verdict** | **Rejected on measurement**, not on taste |

### R2 — Unrevivable quarantine (recommended)

At `inbox.py:131`'s `except` branch, append the whole journal record — which
§2.3 measured is already in hand — to `<state_dir>/quarantine/unrevivable-<date>.jsonl`
at `0600`. **The sweeper never touches this directory.** Count it, surface it at
`/healthz`, and repoint all six promise sites at it.

| | |
|---|---|
| **Costs** | ~15 lines in `inbox.py`, one `/healthz` field, one new directory. The quarantine file is itself unpruned and holds content |
| **Buys** | **A strictly stronger guarantee than the one being retired.** Today the gateway drops bytes it is holding and points at a world-readable file that pruning will delete. After R2 the gateway *keeps* them, owner-only, in a file whose whole purpose is recovery. **Retention and recovery become independent**, so the window in §4 is a pure privacy decision |
| **Breaks** | Nothing. Additive |
| **Growth** | Bounded by **event-driven** arrival, not traffic: records land only on an envelope-drift boot, which is already a `degraded` condition an operator is expected to act on and then clear. Contrast `inbox-data/`, which grows on **every inbound reply** |
| **Rule #1** | Clean — no per-app anything, no content interpretation |
| **Rule #5** | Satisfied and *improved*: site 6's `/healthz` string becomes true again by naming an artifact the gateway guarantees |

### R3 — Operator alert only

| | |
|---|---|
| **Costs** | Nearly zero — `inbox.unrevivable_at_boot` **already** degrades `/healthz` and already prints ids to the console |
| **Buys** | Visibility |
| **Breaks** | ⚠ **Insufficient, and it has a live race.** `*_at_boot` reasons persist for the whole process lifetime (integration guide `:422-425`), so a periodic sweep can delete the very file a **currently displayed** `/healthz` reason is pointing at. It makes the window visible, not longer |
| **Verdict** | **Keep as a companion, reject as the answer** |

### R4 — Narrower prune (only provably delivered)

| | |
|---|---|
| **Verdict** | ⛔ **Rejected on the same measurement as R1** — §2.1, no join key |

### Recommendation

> **R2, with R3's wording strengthened alongside it. R2 must land before or with
> the sweeper — never after.**

**A rejected fifth option, recorded because it looks attractive:** an interlock
making the sweeper refuse to prune while `unrevivable_at_boot > 0`. It closes
R3's race, but because those reasons do not clear until restart — on a host
designed not to restart — it silently disables pruning for weeks. That trades one
unbounded growth for another and hides it behind a counter. **With R2 in place it
is unnecessary**, since the bytes are preserved independently.

---

## 4. Retention window — ✅ approved as proposed, 2026-07-31

> The section is kept as it was written — *proposed*, with its reasoning — because
> the reasoning is what a Builder needs and what a future reader will want when
> the number is questioned. §9 records the verdict.

**Time-bounded in days, never count-bounded.** ADR §4.1 requirement 2 is the
reason and it is not restated here: a count-bound produced a retention nobody can
convert to a date, and *"500 gateway-wide notifies"* cannot go in a contract.

| Bucket | Proposed window | Reasoning |
|---|---|---|
| tenant buckets (`<app>-<date>.jsonl`) | **30 days** | A calendar month is the unit a privacy posture and a subject-access request are written in. It comfortably exceeds any plausible poller-downtime window (jobhunt's host sleeps for *hours*). Crucially, **the gateway does not need to hold a consumer's decision history** — `integration-guide.md:370` already tells consumers this file *"is a forensic record on the gateway host, not something you can re-poll"*, so a consumer needing that history keeps its own. That kills the longer-window argument |
| `_unrouted-<date>.jsonl` | **7 days** | ADR §4.1 pre-authorizes the shortest window here: it *"answers to no tenant"*, accumulates whole unattributable `raw` events, and has no consent story. **Rule-#1-clean because `_unrouted` is the gateway's own bucket** — hard rule #6 reserves the `_` prefix for exactly this — so it is the gateway governing its own artifact, **not** per-app policy, and D6's not-reached question stays not-reached |
| `quarantine/` | **never pruned** | It is the replacement guarantee (§3) |
| `state/deliveries/*.jsonl` | **never pruned** | ADR **D7** scopes its content out. Mode fix only. §8 files a follow-up row rather than widening silently |

**Mechanism:** one env var **NAME**, `CHAT_GATEWAY_INBOX_RETENTION_DAYS`, default
`30`. `_unrouted`'s effective window is `min(configured, 7)` — so lowering the
knob lowers both, and raising it never loosens the ownerless bucket. **`0` means
never prune**, restoring today's behaviour exactly; that escape hatch is what
lets a deployment opt out of the contract amendment without a code change.

**Delete, not redact.** ADR §4.1 left this open. Recommend **unlink the day-file**:
the filename *is* the retention key, so pruning is a directory listing and an
`unlink` — no parsing, no rewrite. Redaction needs field-by-field decisions about
which parts of a human's message are sensitive, which is app-domain reasoning the
gateway must not do (rule #1). ✅ **Approved — unlink** (§9 decision 3).

---

## 5. Scope — source

**No `docs/architecture/` file is touched. No ⚠ flag is cleared, added or
reworded. No adapter is touched.**

| # | Change | File | ADR basis |
|---|---|---|---|
| S1 | Compact when the live set drains | `delivery.py::_finish` | §4 Option D, D1 |
| S2 | Mirror-image compact on drain | `inbox.py::poll` | D1 |
| S3 | Promote `_chmod_quietly` → public `chmod_owner_only`; one home for the primitive | `journal.py` | §4.1 req 1 |
| S4 | `0600` at create, before the first write | `inbox.py::_audit` | §4.1 req 1, D5 |
| S5 | `0600` at create, before the first write | `delivery.py::DeliveryLog.record` | §4.1 req 1, D7 |
| S6 | **Unrevivable quarantine** + counter | `inbox.py::restore` | **§9 Q6 — this spec's answer** |
| S7 | `/healthz` field + `reasons` line for quarantine | `service.py` | rule #5 |
| S8 | Time-bounded sweeper, boot + periodic | new `retention.py`, `__main__.py` | §4.1 req 2–3, D5 |
| S9 | `/healthz` counters for what the sweeper deleted | `service.py` | rule #5 — *"does not distinguish work dropped from work deleted"* |

**S1's honest cost, carried forward from D1 rather than quietly dropped:** a
single stuck job pins every other tenant's delivered body on disk until it
terminates — bounded by the ~73-minute ladder, or 24h across downtime.
`_maybe_compact_locked`'s 1000-append trigger **stays** as the backstop.

---

## 6. Scope — docs

### `docs/consumers/aitrader.md` — seven defects

| Line | Defect | Correction |
|---|---|---|
| `:217` | ⚠ *"no body text of yours is ever written anywhere"* | Replaced by a **bounded, stated retention** — not restored. D2 |
| `:219` | *"Restart drops undelivered jobs. The queue is in-memory."* | False since #45 |
| `:547` | Same, under *"Accepted limitations, agreed in the contract"* | False, and reads as a negotiated term |
| `:418` | *"Nothing about aitrader's traffic is persisted anywhere, in any configuration"* | Needs the `_unrouted` caveat (ADR §2.7) or it is false for a second, narrower, pre-existing reason |
| `:442` | `/healthz` guidance — *"your alerting unaffected"* | Five outbound-queue fields can now degrade it; the paragraph currently trains the reader to ignore exactly the counters that concern them |
| `:569` | env table — `CHAT_GATEWAY_STATE_DIR` as *"heartbeat checks + delivery JSONL"* | No longer says what the directory holds; add the retention env var NAME |
| `:209` | Cites `delivery.py:44-50` for `DeliveryLog.record()` | Now **`delivery.py:77-91`**. The claim is still correct; the pointer lands in `_parse_ts` |
| §2.8 | The `/v1/messages` **inversion** | Must be **corrected, not deleted** — the endpoint the contract says to avoid writes 80 chars *forever*; the one it is built on writes everything, briefly |

### `docs/integration-guide.md`

- **`:382-383`** — *"the audit file is then the only copy"* → names the quarantine
  file as the guaranteed copy. **In CG-65**, because S6 makes it true.
- **`:366`** — *"never pruned"* → the amended retention sentence. **Deferred to
  CG-68**, because it is only true once S8 ships and it needs the approved number.

### `CLAUDE.md`

The CG-54 bullet should **name the retention property, not just "durable."**
One sentence, pointing at the one home for the numbers — not a second copy of
them (the test-count lesson).

### `journal.py:10`

Its *"never pruned"* is site 3. Corrected in **CG-68** with `:366`, same sentence,
same reason.

---

## 7. Hard-rule audit

| Rule | Effect |
|---|---|
| **#1 transport, never schemas** | **Clean, and deliberately kept clean.** The retention window is **global**, not per-app — ADR §7's D5 row warns that a per-tenant window is Option C's shape and would re-open D6's not-reached question. `_unrouted`'s shorter window is the gateway governing **its own** reserved bucket, not tenant policy. "Delete, not redact" (§4) is chosen partly because redaction requires deciding which fields of a human's message are sensitive — app-domain reasoning |
| **#2 secrets are env-only** | **Unaffected.** `configCompleteRedirect*` is blanked before anything is audited (`pubsub.py:150-159`), so no capability URL is in these files to begin with. The new knob is a **count**, not a secret, and is documented as a NAME in every env table alongside the existing ones |
| **#3 adapters + flag discipline** | **Untouched.** Nothing here is Google-facing. **No ⚠ flag is cleared, added or reworded**, and the ledger is linked, never restated |
| **#4 per-app auth + allowlists** | Unchanged. `restore` still re-resolves identities through the registry |
| **#5 `/healthz` stays honest** | **The binding constraint, twice.** (a) The sweeper deletes tenant content and **must** be counted — S9. (b) §2.5 site 6 is a live `reasons` string that pruning would falsify; S6 + S7 are what make it true again rather than merely quieter |
| **#6 inbound opt-in, opt-out absolute** | **Untouched, and nothing widens any inbound surface.** `aitrader` never reaches `inbox.put` — `dispatch` hits `continue` at `pubsub.py:709` before `:727` (ADR §2.7) — so it has no records in `inbox-data/` to prune. `_unrouted` is the gateway's own bucket. No registry key is added, no `allow_inbound` value changes |

---

## 8. Sequencing, and the row split

**The ADR pre-authorizes this split** — §9 Q6: *"the mode half (`0600`) is
unaffected and can proceed."* It is not a widening of scope or a retreat from
D5's "one cycle"; it is one cycle, two PRs, with the approval-gated half isolated.

| Row | Contents | Gate |
|---|---|---|
| **CG-65** (rescoped) | S1–S7 + all of §6 except `:366` and `journal.py:10` | none — ships on green |
| **CG-68** (new) | S8, S9, `:366`, `journal.py:10`, the contract amendment | ⏸ **sequenced**: §9's approvals are ✅ granted; the remaining gate is **CG-65 merged first** (quarantine before pruning) |

**Why the sweeper is not in CG-65:** it is the only part that deletes a tenant's
content, the only part whose correctness depends on a number the user has not yet
approved, and the only part that breaches a published guarantee. Isolating it
means the review that matters is not buried in a 9-file diff.

### Suite

**247 on `main`** (CG-61/#50 added one). Expect **≈ +20 in CG-65** and **≈ +12 in
CG-68** — call it **247 → ~267 → ~279**. Builder measures and reports the real number; this is an
estimate and `CLAUDE.md`'s Layout line remains the one home for the count.

Coverage the tests must include, stated so it is not negotiated later:

- S1/S2: file is 0 lines after the last job drains; a **stuck** job pins the
  others (the honest cost, pinned as a test rather than a comment); the
  1000-append backstop still fires.
- S4/S5: mode is `0600` **before the first payload byte**, matching
  `journal.py`'s existing discipline — not `0644`-then-chmod.
- S6: an unrevivable record's payload reaches quarantine; quarantine is `0600`;
  the sweeper never deletes it.
- S8: a file one day inside the window survives, one day outside is unlinked;
  `_unrouted` uses the shorter window; a malformed filename is left alone, never
  guessed at; `0` disables pruning entirely.

---

## 9. ✅ ANSWERED — all four, by the user, 2026-07-31

> **The questions are kept in their original wording**, with the recommendation
> that was made *before* the answer beside each. A question is an artifact, and
> rewriting one to match its answer erases what was actually asked — the same
> discipline ADR-0002 §9 applied to itself.

| # | Question | Recommendation, as made | Decision |
|---|---|---|---|
| **1** | **The recovery-path replacement.** Approve **R2 (quarantine)** as the answer to ADR §9 Q6? | **Yes** — §3. It is stronger than the promise it retires, and §2.3 shows it is nearly free | ✅ **APPROVED.** Plan Task 6 |
| **2** | **The retention window.** `30` days tenant / `7` days `_unrouted` / `0` disables? | **Yes** — §4. Flagged rather than assumed, as the brief required | ✅ **APPROVED as proposed**, via `CHAT_GATEWAY_INBOX_RETENTION_DAYS`. Plan Task 10 |
| **3** | **Delete or redact?** | **Delete (unlink).** §4 — redaction reintroduces parsing and edges into rule #1 | ✅ **UNLINK.** Plan Task 10 |
| **4** | **Amend the shared contract?** `integration-guide.md:366` is owed to **every** consumer, not just jobhunt | The user has already elected to amend (brief, Q6). Restated here because it is the only item that changes a **published** guarantee, and it should be signed off on that basis | ✅ **AMEND**, signed off on exactly that basis. Plan Task 13a |

**What is still gated, so this is not read as "start anywhere":** CG-68 must not
begin until **CG-65 has merged**. That is sequencing, not approval — Task 6's
quarantine is the mechanism that makes Task 10's pruning safe, and the whole
point of the split is that the replacement lands before the deletion.

**Not reached, and deliberately still not reached:** ADR-0002 D6's hard-rule-#1
question about per-app policy. Decision 2 keeps the window **global**, so it does
not arise. Should a per-*tenant* retention window ever be proposed, argue it from
ADR-0002 §4 Option C's text rather than re-deriving it.

---

## 10. ⚠ The process finding — three instances in one day

Stated because the brief asked for it rather than for a fourth instance.

| # | Change | Promise it invalidated | Where the promise lived |
|---|---|---|---|
| 1 | **#45 / CG-54** — journalled bodies | *"no body text of yours is ever written anywhere"* | `docs/consumers/aitrader.md:217` |
| 2 | **#45 / CG-67** — bodies moved into `state/` | `.gitignore`'s coverage — the ignore rule tracked where bodies **used to be** | `.gitignore` |
| 3 | **CG-65's own prune** — *would have* | *"never pruned"* / *"the only copy"* | `integration-guide.md:366`, `:382`, **and a `/healthz` string** |

**The shape is identical in all three: a change was correct in its own file and
invalidated a guarantee recorded in a file nobody in the loop was reading.** None
was caught by review of the diff, because the diff never contained the sentence
it broke. Instance 3 was caught only because ADR-0002 went looking — and §2.5
shows even that search missed site 6, the `/healthz` string, which is the one
with a hard rule attached.

**The cheap control, and it has precedent in this repo.**
`tests/test_error_surfaces.py` already reads *construction sites* to guard a
property that lives in prose. The same idiom fits here: a **published-promise
inventory** — a test-owned list of absolute claims in `docs/consumers/*.md` and
`docs/integration-guide.md`, each with a pointer to the code that makes it true,
failing when a claim has no owner. It does not prove the claims; it makes the set
**enumerable**, so a durability change can be checked against it in the minute
before merge rather than in an ADR two PRs later.

**Filed as CG-69, not built here** — it is a process control, not part of this
row's scope, and folding it in would be a fourth instance of the same
scope-creep-by-good-idea this repo keeps correcting.

**Concretely, it would have caught all three:** claim 1 names `delivery.py`,
which #45 rewrote; claim 2's owner is `.gitignore`, whose covered paths changed;
claim 3 names `inbox.py::_audit`, which CG-68 modifies.

---

## 11. Handoff

- **No Designer involvement** — no UX surface.
- **Builder ships CG-65 from the plan (Tasks 1–9).** It must not prune anything
  and must not touch `docs/architecture/`.
- **CG-68 (Tasks 10–13) is approved and waits on one thing: CG-65 merging.**
  Sequencing, not sign-off.
- **A Builder must not re-open ADR-0002 §6, and must not re-open §9's four
  decisions.** They were taken by the user on 2026-07-31 with the reasoning
  recorded beside each.
