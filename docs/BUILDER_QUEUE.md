# Builder queue — chat-gateway

**Last updated:** 2026-08-03 (Builder — **CG-76 SHIPPED**: all six doors closed,
each demonstrated against a real uvicorn server with `main` run as the control).
Suite **359** on the CG-76 branch, measured with `python3 -m pytest -q`, not
copied from the row below.

⚠ **Pre-merge review found a SEVENTH way to break the dead-man switch — one the
fix itself introduced.** The new registration-time 422 fired on *every* `POST
/v1/heartbeat`, and that endpoint is also the **liveness ping**. An operator
removing an alert route therefore froze `last_seen` on a healthy consumer,
drifted its check into `missed`, and delivered a **fabricated** *"heartbeat
missed"* the moment the route came back — measured end to end on a source that
never died. Not one of the six (nothing is *dropped*, and `/healthz` degrades
throughout), and caught only because the reviewer read the endpoint's OTHER
caller rather than the diff. The guard now applies only to a check that does not
already exist; a refresh is never refused.

**Also 2026-08-03 (Planner — CG-53's plan refreshed; the row is now
DISPATCHABLE).** **CG-53's premise was re-run rather than re-quoted** — it is the
one load-bearing fact in that row and it lives in a repo this one does not
control, which is precisely CG-69's "external world" category. It **holds**, and
one sentence of it was wrong in a way that matters: renaming our env vars would
fix the API-key family and do **nothing** for the webhook family. **Ten drifts
corrected in plan Part A across the NINE PRs that merged since it was written —
two of them would have failed at runtime, not at review**, because
`build_runtime()` grew a sixth return value and the deploy compose mounted the
registry where its own env var did not point. ⚠ **The merge gate is NOT
released** — it is the user's — but the row now states exactly what releasing it
approves.
⚠ *That paragraph said "eight PRs" and "still **345**" when it was written hours
ago. **CG-76 landed as #63 mid-refresh** and falsified both — nine now, and the
suite is **359**. Corrected on rebase rather than left standing, which is the
same failure this queue keeps catching: a count copied into a second home.*

⚠ **The count moved four times, and that is the finding worth more than the
number.** Door 1 was found by accident sweeping unguarded *writes* for CG-75.
Door 2 by accident during CG-74's UAT, then independently by its reviewer.
Doors 3 + 4 by this row's first deliberate sweep. **Doors 5 + 6 by an
INDEPENDENT SECOND SWEEP of the same path, commissioned only because the brief
asked whether two was the complete count** — and door 6 is the worst of the six.
**Five of the six drop the alert without raising anything**, and on door 6 **not
one field in the entire `/healthz` body moves.** Enumeration and measurements
have one home: [spec](superpowers/specs/2026-08-03-dead-man-alert-loss-design.md)
§2. Do not re-summarize it — link it.

⚠ **A merged claim was false and is CORRECTED, not rewritten.** The delivery
write-path spec §5 said `scan_failures` was *"the only thing standing between a
silently-dropped aitrader alert and a green `/healthz`."* It is the only signal
for a scan that **RAISES**; five of six doors raise nothing. The original wording
is struck in place with how it was found and what is true instead. ⚠ **Fifth
instance this week** — logged on **CG-69**. ⚠ *That sentence ended "which still
has no plan" when it was written hours ago, and the CG-69 PR below falsified it
the same day. Corrected here rather than left standing — which is the control
CG-69 designs, applied to a sentence about CG-69.*

⚠ **CG-77 filed** (clock skew silently disarms the dead-man switch) — measured,
deliberately **not** folded in: it is a different defect class, preventing an
alert from *becoming* due rather than dropping one that did.

⚠ **CG-55 gains CG-76 as a dependency — and it was NOT there.** The user's
2026-08-02 decision makes CG-76 a pre-deploy blocker on CG-55's list; measured
2026-08-03, **no CG-55 row in this file named CG-76 at all** (`grep -n "CG-76"`
returned nothing under either CG-55 entry). Added now, with the gap recorded
rather than quietly closed — a decision that exists but is written down nowhere
is the same failure mode CG-69 exists to catch.

**Also 2026-08-03 (Planner — CG-69 designed).** The published-promise control is
specced and planned, **inverted and much smaller than the row proposed**: not an
inventory of prose claims but executable `module.py::Symbol` anchors in the live
contracts, plus two pins on code-side sets of size 1 and 2. Measured on
`d09a07c`, suite **345** (re-run, not copied): **8 of the 14 code citations in
`docs/consumers/` and `CLAUDE.md` point at the wrong code today** — three of them
in `aitrader.md`'s hard-rule-#6 enforcement table — while the same files'
name-anchored citations are **0 of 8** wrong. No `src/` change, no ⚠ flag
touched, `docs/architecture/` untouched.

**Previously (Builder, same day): CG-74 shipped ([#60](https://github.com/mmackelprang/chat-gateway/pull/60)):
`/healthz` can tell a WEDGED loop from a RAISING one, and a dropped dead-man
alert no longer reads green.** Suite **333 → 345**, both ends re-measured with
`python3 -m pytest -q`, neither copied from a row.

**Demonstrated on a real server against a real kernel `PermissionError`, not a
monkeypatch, and the control ran the same harness on `main`.** `chmod a-w` on
the state dir while a registered dead-man check went missed: on `main`
`/healthz` answered **`ok`** while the check on disk read `status: missed` with
`last_alerted` stamped and **zero notifications sent** — the alert suppressed
for 24h with nothing anywhere saying so. On the branch, **`degraded`**, with a
reason naming the loss.

⚠ **The asymmetry was VALIDATED by that run, not merely implemented.**
`consecutive_scan_failures` read **0** at the moment of the drop, correctly —
one scan raised, the next found nothing due and cleared it. **The cumulative
counter was the only thing still holding `degraded`.** The rejected
body-only-until-CG-76 alternative would have gone green on that exact run. The
user's D3 decision is the reason there is a signal at all.

**Both CG-76 variants move the counter**, checked separately: variant D
(`_save()` raises inside `due_alerts`) and the durable variant E (`_save()`
lands, then the notify's `enqueue` hits the journal `open`) — the second leaving
the suppression **on disk**. Nothing swallows the raise between `HeartbeatStore`
and `_run`'s handler.

⚠ **One thing DOES, and it was measured before review found it by reading — so
the counter's own docstring is now narrower than the spec's.** A notify
**refused for want of a route** (`route_for` finds neither `alert` nor
`default`) becomes an `HTTPException(503)` that `_monitor_notify` **catches**.
The alert is dropped, `scan_once` completes, **no counter moves and `/healthz`
answers `ok`.** So `scan_failures` is the only signal for a scan that **RAISES**,
not for "a dropped dead-man alert" — `HeartbeatMonitor.__init__` now says that
and `test_a_routeless_alert_is_dropped_without_raising_or_counting` pins it.
**Spec §5 line 421 still carries the absolute wording**; it is a Planner artifact
and this PR did not edit it. **Planner: reconcile, and consider whether CG-76's
scope covers this door.**

⚠ **CG-73's confidence statement is now split.** Its row calls its sites *"drift
in a hard-rule-#2 control, **not a proven leak**"*. For the **two sites CG-74
closes** that is settled the other way: on `main`, the same fault put an
**absolute filesystem path** on the console (`[Errno 13] Permission denied:
'…/state/heartbeats.tmp'`) where the branch prints `PermissionError`. The
residue of three is untouched by this and keeps the original confidence.

**Previously (Builder, same day): CG-75 shipped (#58) — the unguarded
delivery-log write no longer storms Google.** Suite **324 → 333**, both ends
re-measured with `python3 -m pytest -q`, neither copied from a row.

**The storm was reproduced against a real kernel `PermissionError`, not a
monkeypatch, at both ends of the fix:** 60 sends in 60 passes → **1** on the
delivered path, and 1654 sends over 6000 passes → **5** (exactly `len(BACKOFF_S)`)
on the retry path. The other half of the row mattered as much: `POST /v1/notify`
**still returns 500 on a full disk** — verified on a real uvicorn server with the
state tree chmod'd read-only — because `enqueue`'s journal `open` stays unguarded
on purpose. The guard stops *already-accepted* work from storming; it must never
hide a full disk, and it does not.

⚠ **CG-55's CG-75 dependency is now satisfied.** CG-61's live-registry operator
action and the D2 tailnet ACL still gate it.

⚠ **Amended 2026-08-03 (Planner, user decision): the D2 tailnet ACL is DEFERRED
and no longer gates CG-55.** The line above is left standing as the record of
where the arc stood when CG-75 shipped; this is the currency pointer. **CG-61's
live-registry operator action still gates CG-55** — measured against the real
loader at **2026-08-03 19:15:56Z (15:15 EDT)** and **not yet done**. Deferred is
not cancelled and not deleted, and it does not stand alone: the same day the user
also decided **CG-55 binds its published port to the LAN interface rather than
`0.0.0.0`**, which is what makes the deferral sound rather than merely
approximately sound. Both decisions, their reasoning, and what they do and do not
buy are recorded together in **CG-55's row**.

**Previously (Planner, same day): CG-74 + CG-75 specced and planned; CG-76 filed;
CG-55 gained a dependency.**

**Two rows, one root cause, two PRs.** CG-72's Builder filed CG-74 and CG-75
separately and both were separately right — but they are the same unguarded
write on the delivery path seen from two angles: CG-75 is its **control-flow**
consequence, CG-74 its **observability** consequence. Planned in one pass so two
designs are not written over the same function; **shipped as two PRs, CG-75
first**, because CG-75 is a pre-deploy blocker and CG-74 is a new degrade input
on an endpoint consumers alarm on — which CG-72's own comment calls *"a decision,
not a wording fix"*. A blocker must not inherit a decision's review risk.

⚠ **CG-75 now blocks CG-55 — user decision, 2026-08-02.** The accepted
reasoning: this gateway has never run on a box with a real disk that can fill,
so *"low likelihood"* is an artifact of never having been deployed, and CG-55 is
precisely the event that changes it.

**Measured, not reasoned about.** One notification, one successful send, then a
full disk: **60 passes, 60 sends to Google, in 60 seconds.** On the retry path
the opposite failure — worst staleness **1.0s** against a 600s budget over 400
passes, `/healthz` `ok` throughout — until the backoff ladder exhausts at
**t=4350s** and the retry path *becomes* the storm. That second half **narrows
CG-74's own row**, which said the staleness branch *"never fires at all"*: it
does, eventually, and what makes it fire is the failure getting worse.

⚠ **A third defect, found by the sibling sweep and NOT fixed by either row —
filed as CG-76.** `HeartbeatStore.due_alerts` marks a check alerted *before* it
persists, and `scan_once` only notifies what it returned, so a raise anywhere
downstream **silently drops the dead-man alert** for 24 hours while the next idle
scan re-stamps `last_scan_at` and `/healthz` goes green. One variant persists the
suppression and survives a restart. **CG-75's fix does not rescue it** — measured
separately: post-fix the raise arrives from `enqueue`'s journal `open`, which is
unguarded by design. The dead-man switch is aitrader's contract surface.

⚠ **CG-73 counted down from five sites to three** — CG-74 closes two of them as a
side effect. Counted down rather than left standing: a count with two homes is
this repo's own recorded failure mode.

**No ⚠ verification-ledger flag cleared, added or reworded.** This PR touches no
`src/`, `adapters/`, `docs/architecture/` or `docs/consumers/` file, so no flag
can move. Baseline recorded for both implementation PRs, **with the command**,
because CG-72's banner recorded `docs/architecture/ 5=5` where an
occurrence-count reads **6** — one line in that directory carries two flag words,
so the number is method-dependent and the banner did not say which method.
Nothing was wrong then; the command is now written down so it cannot be.

Previously 2026-08-02 (Builder — **CG-72 shipped as
[#56](https://github.com/mmackelprang/chat-gateway/pull/56)**). Suite **314 → 324**,
both ends measured here.

**`/healthz` can now see all four threads.** A dead `delivery-dispatcher` and a
dead `heartbeat-monitor` were, until today, reported as `status: ok` — the
11-day-silent-capture-failure shape hard rule #5 was written after, live on every
deployment. **Demonstrated rather than argued:** both threads killed in a real
uvicorn server through the documented hole (an exception raised inside `_run`'s
own handler, not `.stop()`), same harness on both sides — `main` answered `ok`
with `reasons: []`; the branch answered `degraded` with exactly one reason each.

⚠ **Review's sharpest finding was a sentence that outlived its evidence.** Both
new staleness reasons said *"neither completing nor raising, so it is wedged
rather than erroring"* — copied from the subscriber and retention chains, where
it is true **only because a failure-counter branch sits above it**. These two
blocks count nothing. Reworded; the counters are filed as **CG-74**, and two
`/healthz` strings now name that gap in words.

⚠ **A plan line that silently changed a field's meaning.** *"do not call
`self._now()` a second time"* made `last_pass_at` publish the pass **start** while
three other places defined it as **completion** — halving the 600s budget's real
headroom. Fixed; the deviation is recorded at the code comment, its one home.

**Two new rows filed from this row's review:** **CG-74** (the counter half of
CG-68's F3, on the two threads that only got the liveness half) and **CG-75**
(pre-existing: a raising `_finish` re-sends the same job every second, unbounded
— a disk-full condition becomes a send storm against Google).

**No ⚠ verification-ledger flag cleared, added or reworded** — proven by diff on
every ledger-bearing surface: `CLAUDE.md` 8=8, `src/` 4=4, `docs/architecture/`
5=5, `docs/consumers/` 2=2, `tests/` 3=3. The whole-repo count *does* move
(103 → 106) and that is **not** a flag change: every one of the four added lines
is a grep **pattern** inside the shell snippet that fixes Part B's broken guard.
`adapters/` and `docs/architecture/` untouched.

Previously 2026-08-02 (Planner — **CG-68's deferred L4 measured; three rows
filed, one decided**). No `src/` change: spec, plan and this file only. Suite
**314**, re-measured there (`314 passed in 58.76s`) rather than quoted from the
row below.
[spec](superpowers/specs/2026-08-02-runtime-lifecycle-and-liveness-design.md) ·
[plan](superpowers/plans/2026-08-02-runtime-lifecycle-and-liveness.md).

⚠ **CG-68's deferral was right to refuse, and it understated the problem.**
`__main__` has **four `.start()` and zero `.stop()`** — no `finally`, no
`atexit`, no signal handler. Not a retention row's missing cleanup: four
long-lived threads with no shutdown path, of which CG-68 added the fourth.

⚠ **The obvious fix is a measured no-op.** uvicorn 0.42 restores the default
signal disposition and **re-raises**, so `uvicorn.run()` never returns on
SIGTERM. A child with all four hook shapes installed exited `rc=-15` and printed
**only** `LIFESPAN_SHUTDOWN` — the `try/finally`, the `atexit` handler and the
line after `uvicorn.run(...)` all failed to run. **`try: uvicorn.run(app)
finally: dispatcher.stop()` passes every unit test, reviews cleanly, and never
executes.** The shutdown path must be an ASGI lifespan hook (**CG-71**).

⚠ **The bigger finding is not the shutdown gap — it is what turned up while
measuring it.** `subscriber` and `sweeper` publish `thread_alive` /
`thread_started` at `/healthz` and degrade on a dead thread; **`dispatcher` and
`monitor` publish neither and cannot degrade.** A dead dispatcher silently stops
every outbound notification while `pending_jobs` climbs and `status` stays `ok`;
a dead heartbeat monitor kills the dead-man switch while `last_scan_at` sits
frozen at a real timestamp. That is CG-68's own F3/M3b finding on the two threads
nobody went looking at, and it is the 11-day-silent-failure shape rule #5 exists
for. Filed as **CG-72** and **sequenced ahead of CG-71** — it is live today, on
every deployment, including the one CG-55 makes.

**The shutdown gap itself is LATENT, and the row says so rather than inflating
itself.** Daemon threads, ~0.16s exit, nothing hangs. **Durability is not the
justification: CG-54's SIGKILL proof already covers that half.** Every journal
append is `write`→`flush`→`fsync` inside one `open()`, and a hammering daemon
thread killed by SIGTERM *and* by SIGKILL left a clean parseable journal both
times. The only uncovered window is a kill mid-send, which `_finish` already
documents as deliberate at-least-once.

✅ **CG-70 decided — option (a), and the row's own argument against it was
measurably wrong.** It preferred (b) because (a) *"adds a `stat` per append to a
path that deliberately has none"*. `strace` on the real `Journal` shows one
`newfstatat` per append **already there** — `existed = path.exists()` *is* that
stat — **and the kernel already returns the mode in it**. (a) costs zero extra
syscalls in the steady state. Severity unchanged (LOW); the reason changed from
*"defer, it is low"* to *"do it, it is free"*.

**Five user sign-offs are outstanding (L1–L5)** — spec §8.

**No ⚠ verification-ledger flag cleared, added or reworded**; `docs/architecture/`
untouched.

Previously 2026-08-02 (Builder — **CG-68 shipped as [#54](https://github.com/mmackelprang/chat-gateway/pull/54)**).
Suite **268 → 314**.

**The first row that DELETES a tenant's content**, and the "forever" on
`inbox-data/<app>-<date>.jsonl` is over: **30 days / 7 for `_unrouted` / `0`
disables**, via `CHAT_GATEWAY_INBOX_RETENTION_DAYS`. `integration-guide.md:366`'s
published *"never pruned"* is amended (sign-off A4) — the promise was owed to
every consumer, not to jobhunt alone.

✅ **A fifth sign-off, A5, taken mid-execution (2026-08-02).** The boot guard
**refuses** rather than warns and is stricter than the non-recursive glob
requires. The plan carried that as a trade **Planner had chosen**, phrased
outside the A1–A4 box — the exact shape a reviewer softens on "currently
harmless" grounds. Reasoning the user accepted, kept rather than the verdict
alone: *"currently harmless" is a property of one line of code staying
non-recursive*, and **a warning nobody reads becomes tenant data loss** the day
someone reaches for `rglob`. Recorded in three places, including
`_check_disjoint`'s own docstring so it travels with the code.

⚠ **Pre-merge review found 0 HIGH, 6 MEDIUM, 6 LOW, and the sharpest one was
this row's guarantee being half-built.** The module docstring listed three
directories under *"what this never touches"* and closed *"it is now enforced
twice, in code"* — backed by two **quarantine-only** mechanisms. Measured:
`CHAT_GATEWAY_INBOX_DIR=state/deliveries` is a **sibling** of the quarantine, so
both guards passed and the sweeper pruned the **delivery log** — ADR-0002 **D7**,
*"permanent by decision"* — and `files_deleted`, which deliberately never
degrades, published it at `/healthz` as the feature working. The guard now
refuses overlap with the whole state dir: a **widening** of A5, never a
narrowing. Two more worth carrying forward: a **recovered** sweep failure pinned
`degraded` for the life of the process and printed the cleared error as the
literal `(None)`; and both Task 14 `/healthz` tails asserted a delete timer
**unconditionally**, so a deployment with `RETENTION_DAYS=0` was told its last
copy was being pruned — **Task 14's own defect shape, pointed the other way**.

**One deferral, knowingly:** the sweeper's `start()`/`stop()` are not idempotent
and it is never stopped. Byte-for-byte the `Dispatcher` idiom, and Task 11's
*"stop it where the dispatcher and monitor are stopped"* names a place that
**does not exist** — `__main__` stops neither. A shutdown path for three
components is not a retention row's to invent.

**No ⚠ verification-ledger flag cleared, added or reworded** — proven by diff,
not memory: zero flag-word occurrences in `git diff main`, and identical
per-file counts on both sides. `docs/architecture/` untouched.

Previously 2026-08-01 (Planner — **CG-68's plan corrected before Builder
runs it**). No `src/` change; the plan document and this row only.

⚠ **Read CG-68's row before starting it.** A Planner pass re-read
[the plan](superpowers/plans/2026-07-31-body-retention-and-audit-hardening.md)
end-to-end against what #52 actually shipped, because CG-68 **deletes tenant
content** where CG-65 only compacted replayable state. **Tasks 4 and 5 were
corrected** — their literal code carried the data-loss race #52's review caught,
and the plan now records the wrong version and its counterfactual rather than
looking as though it was always right. **Tasks 10–13 do NOT carry that same
shape** (measured; the sweeper derives nothing from memory) — but the audit
found **six neighbours**, one **HIGH**: `/healthz` would have raised `KeyError`
whenever no sweeper was configured. **Task 14 is new** — five strings, two on the
unauthenticated `/healthz`, that CG-65 made true and CG-68 makes false again.
**No ⚠ verification-ledger flag cleared, added or reworded.**

Previously 2026-07-31 (Builder — **CG-65 shipped as #52; CG-70 filed**).
Compact-on-drain, `0600` on both audit trails, the **unrevivable quarantine** and
the contract correction are in. Suite **247 → 268**. **CG-68 is now unblocked on
sequencing** — the quarantine it waits for exists — but read CG-65's row first:
its pre-merge review found a data-loss race in compact-on-drain that the plan's
literal code contained, and CG-68 touches the same paths.
[spec](superpowers/specs/2026-07-31-body-retention-and-audit-hardening-design.md) ·
[plan](superpowers/plans/2026-07-31-body-retention-and-audit-hardening.md).

✅ **All four sign-offs granted by the user, 2026-07-31** — the quarantine as
ADR-0002 §9 Q6's answer; the **30 / 7 / 0** window via
`CHAT_GATEWAY_INBOX_RETENTION_DAYS`; **unlink** rather than redact; and amending
the contract owed to every consumer. Spec §9 and plan Tasks 10–13 record each
with its reasoning, not just its verdict. **CG-68's merge gate is now only
"CG-65 must merge first"** — the quarantine is what makes pruning safe.

⚠ **The pruning half was SPLIT OUT as CG-68, deliberately.** ADR-0002 §9 Q6 asked
whether pruning `inbox-data/` breaches `docs/integration-guide.md:366`'s *"never
pruned"*. Planning found the promise has **six live homes — and one is a
`/healthz` `reasons` string** (`service.py:478`), which makes it a
hard-rule-**#5** problem rather than a docs problem: a sweeper would leave an
unauthenticated health endpoint telling an operator to read a file the gateway
itself deleted. **CG-65 answers it with a mechanism before CG-68 deletes
anything** — an unrevivable reply's whole record is preserved under
`<state_dir>/quarantine/`, never swept. Measured while planning: `restore` is
**holding** that record when it declares it lost, and boot compaction erases it
moments later, so preserving it costs one append.

**Two measurements that killed two plausible designs:** the per-app audit line
carries **no journal id** (written before the id is minted), so "prune only what
was polled" is not implementable without a schema change consumers read; and
**`Inbox.restore` has no age ceiling** where `Dispatcher` has a 24h one — a
400-day-old unpolled reply restores cleanly, so a finite audit window truncates a
recovery path that is unbounded on the other side.

**CG-69 files the process finding rather than repeating it:** three changes in
one day invalidated a guarantee recorded in a file nobody in the loop was
reading. **No ⚠ flag cleared, added or reworded**; `docs/architecture/` untouched.

Previously 2026-07-31 (Builder — **CG-61 shipped as [PR #50](https://github.com/mmackelprang/chat-gateway/pull/50)**,
`dced002`. It narrows a tenant's inbound surface, which hard rule #6 says needs
explicit sign-off naming that rule; narrowing is still a change to the surface.
**The gate was released by the user and the PR merged.**

⚠ **The banner below was written PRE-MERGE and said "open, NOT merged". That
half is now stale and is corrected here rather than preserved verbatim — but its
second half is NOT stale and is the reason this row is not simply done:**

⚠ **The row is not finished now that the PR has merged.** `config/registry.yaml` is
gitignored, so the PR changes only the EXAMPLE. Measured today with the real
`load_registry` against the real live file: `aiteam-harness` is still
`allow_inbound=True`, and the **key is absent** — the default is doing the work,
which is decision D1's entire argument. Until an operator edits that file the
app is **still open inbound in production**, and **CG-55 depends on the live
file, not on the example**. The PR body carries the edit and its verification
snippet.

**Pre-merge review caught one HIGH, and it was this PR asserting its own
outcome:** `CLAUDE.md`'s consumer bullet stated `allow_inbound: false` as the
LIVE posture — beside an `aitrader` entry that genuinely describes the live
registry — while this same file's CG-12 bullet fifty lines above correctly said
*"NOT YET"*. One file, two tenses, the load-bearing one wrong. One MEDIUM with
it (`allow_inbound: True` written in YAML-key syntax, reading as a quote of
bytes that are not there) and four LOW, all fixed.

**The disk claim was proven against its own counterfactual, not asserted.** The
real `dispatch` + real `Inbox` + real `Journal`, same event, two registries:
with the CG-61 line, nothing anywhere and only the counter moves; without it,
that event lands in **both** disk surfaces — the per-app audit JSONL *and*
`state/queue/inbound.jsonl` — carrying text, sender email and whole raw event.
Rule #6's three absolutes were also driven against a **serving** gateway: inbox
403 naming the rule, `interaction.enabled: false`, and `callback_url` a load
error. Suite **246 → 247**. **No ⚠ flag cleared, added or reworded** — proven by
reading the diff: the `adapters/` hunk has zero non-comment lines.

Previously 2026-07-31 (Builder — **CG-67 shipped as [#48](https://github.com/mmackelprang/chat-gateway/pull/48)**:
`state/` is ignored, so a local run can no longer stage tenant message bodies.
**Split out of CG-66 and promoted by the user**, which leaves CG-66 doc-only.

⚠ **The scoping brief said `inbox-data/` "appears to be a dead directory name —
confirm nothing writes it, and if so remove it." It is LIVE, and removing it
would have inverted this row into the defect it exists to prevent.** It is
`CHAT_GATEWAY_INBOX_DIR`'s default, it is written by `Inbox._audit` on every
inbound reply, and it holds a human's `text`, `sender_email` and whole `raw`
event — content the concurrent Architect agent independently measured as the
*larger* of the two on-disk exposures. Confirming-before-deleting is the only
reason this row shipped an addition rather than a regression, and it is why the
block now records *why* each pattern is there.

**Proven by running the gateway, not by editing a file.** A clean clone was
served with the documented `python3 -m chat_gateway serve`, a real `/v1/notify`
returned 202, and the resulting body-bearing `state/queue/*.jsonl` was shown
ignored — then the `state/` line was removed from that same clone and the same
three files immediately became stageable. Suite re-measured: **246**.
**No ⚠ flag cleared, added or reworded** — the diff touches no Google seam and
no ledger row.

Previously 2026-07-31 (Builder — **CG-64 shipped as [#46](https://github.com/mmackelprang/chat-gateway/pull/46)**:
the four claims CG-54 falsified are corrected, and CG-60's bookkeeping caught up
with its own merge.

**The suite was RUN, not trusted** — the row said 246 and the row was right, but
`CLAUDE.md`'s Layout line is the one home for that number precisely because
copies of it drift, so it was re-measured (`246 passed`) rather than copied from
a queue row that was itself a copy.

⚠ **The row said FOUR `/healthz` fields can degrade. Reading `service.py` says
FIVE**, and the guide ships five. `expired_at_boot` and `unroutable_at_boot`
share ONE `reasons` entry, so there are four lines of text and five fields that
produce them — an easy off-by-one to make from the reason blocks, and exactly
the kind of thing a consumer alarming on `status` would find the hard way. The
count in the CG-64 row below is left as written with the correction beside it.

**Pre-merge review caught one HIGH, and it was this PR's own claim:** the CG-60
**detail heading** still read `📋 queued` while the table row and the banner both
said shipped — a merged item still advertising the marker Builder claims on. Two
MEDIUMs with it, both measured against the source: `/v1/deliveries` gained two
terminal statuses at #45 (`expired`, `unroutable`) that its section never
listed, and a count of `*_at_boot` fields was ambiguous in the one section whose
job is getting counts right. All fixed here.

**Two new rows filed rather than raced — CG-65 and CG-66.** The sweep that
checked CG-64's scope found the same staleness concentrated in
`docs/consumers/aitrader.md`, and ⚠ **one of those four is a PRIVACY claim, not
a durability one**: that contract still promises *"no body text of yours is ever
written anywhere"* while `Dispatcher.enqueue` now journals whole `text` + `cards`
on every `/v1/notify`. Hard rule #2 is intact — no credential reaches the
journal — but the tenant was told something that is no longer true, so it is
**their** decision to re-take. CG-66 collects the rest, including the one
non-doc item (`.gitignore` does not ignore `state/`, which now holds bodies).
**CG-63 was never allocated** — a gap in the numbering, not a lost row.

**No ⚠ flag cleared, added or reworded** — verified by reading the diff, not
from memory: the diff touches no Google seam and no ledger row.

Also 2026-07-31 (Builder — **CG-54 shipped as #45**: both queues
are durable. `journal.py` is new, the replay rule and the mid-flight
double-send answer are written down rather than implied, and the suite is
**202 → 246**.

**Proven by killing a process, not by asserting a file exists** — a serving
gateway was SIGKILLed with three jobs queued, the journal read by eye, and the
restarted process agreed with `/healthz`. The torn-line, expired and unroutable
paths were each driven against a live process too, and each produced `degraded`
with a `reasons` entry rather than a silent number (rule #5).

**Pre-merge review caught one HIGH and it was real:** `Inbox.restore()` dropped
a journalled reply that no longer parsed — silently — and boot compaction then
erased it. The drop is right; the silence was not, and the asymmetry with the
outbound twin (`unroutable`, which had a counter, a log record and a reason
from the start) was the actual defect. Fixed and mutation-verified.

**It filed CG-64 rather than racing CG-60.** As of that PR `CLAUDE.md` still
said the queue was in-memory and still reported 202 tests, and
`docs/integration-guide.md`'s inbox section still made the audit-versus-queue
conflation — but both files were CG-60's, so the correction was a row, not a
gamble. (**All four are fixed as of #46**; the past tense here is CG-64's doing.)
**No ⚠ flag cleared, added or reworded**: CG-54 touched no Google seam.

Also 2026-07-31 (Builder — **CG-60 shipped as #44**. It waited at a user-imposed
merge gate first — deliberately open and **not** merged, because it touches
consumer contracts and works in the verification ledger's neighbourhood — and
the user released that gate the same day. **The gate is spent, not standing.**
This paragraph read *"CG-60 is in flight and PAUSED AT ITS MERGE GATE"* until
CG-64 corrected it, which is the same shape of staleness CG-64 exists for: a
status sentence outliving the status.

**What it is:** the repo-wide correction of the one-space premise. Documentation
plus **one dated docstring note** in `adapters/chat_api.py`; suite **202 → 202**,
unmoved; **no ⚠ flag cleared, added or reworded**, proven by reading the diff
rather than by memory.

**The premise was re-derived, not taken on trust** — the real `apps_for_space`
run against the **live** gitignored `config/registry.yaml` returned exactly what
the plan predicted: four distinct spaces, two → `['aitrader']` with
`allow_inbound: false`, one → `['job-hunter']`, one → `['aiteam-harness']`.
Re-deriving also turned up **two locations the brief's list did not name**
(`docs/assets/README.md`), which is the whole reason CG-52's find-by-text rule
exists.

⚠ **It filed CG-62 rather than answering it.** Every ⚠ flag in this repo was
cleared through the Chat app that is now deprecated. Whether those clears survive
the app's replacement is a **hard-rule-#3 question needing the user's sign-off** —
so CG-60 shipped currency pointers beside untouched observations (the CG-50
shape) and left every flag where it found it.

Previously 2026-07-31 (Planner — **the production-readiness arc is filed
and DISPATCHABLE: CG-53 … CG-61**, one shared
[spec](superpowers/specs/2026-07-31-production-readiness-arc-design.md) ·
[plan](superpowers/plans/2026-07-31-production-readiness-arc.md), Parts A–G
mapping one-to-one onto the rows. **It has never been deployed** — `Dockerfile`
and `docker-compose.yml` have never been exercised, and every verification across
2026-07-29/30 was hand-run from the dev box.

**Three findings contradict the brief this arc was planned from, and are recorded
rather than planned around.** (1) There is **no `nas/compose/<service>.yaml`
convention** — NAS services are TrueNAS *custom apps* created over the middleware
API and then *captured* to `nas/compose/<name>.config.json`, so this repo's
`docker-compose.yml` cannot deploy as written (`build:`, `env_file:` and relative
mounts all fail there). (2) **The homelab secret redactor cannot see this
project's secrets** — it matches env-var name *suffixes*, and
`CHAT_GATEWAY_API_KEY__<APP>` ends with the app id while
`GOOGLE_CHAT_WEBHOOK_URL__<IDENTITY>` ends with the identity name, so the naive
house-style deploy would commit every API key and every webhook URL in plaintext
to a sibling repo **under a script that prints `clean. safe to commit.`** (3)
`SECRETS.md` is **gitignored and holds real values**; the tracked pointer file is
`SECRETS.template.md`.

**Two more findings reshaped the workstreams.** jobhunt's push receiver **was
never built** — no route, no port, no code — so decision A is a contract
correction *before first use*, not a migration. And `inbox.py`'s queue is
**in-memory too**, which the brief's durability scope (`delivery.py` only)
missed: decision A points jobhunt's *only* inbound path at it, and a consumer
whose host sleeps leaves taps sitting there for hours.

**Two further premise corrections arrived 2026-07-31, and both are folded in —
see spec §0.1 and §0.2.** (a) The classic app **"Agent Comms" is DEPRECATED**,
replaced by **"Chat Gateway"**, which is in **FOUR** spaces — not the JobHunt
space only. Re-derived against the **live** registry: both Ai Trader spaces
resolve to `['aitrader']` with `allow_inbound: false`, so **every event there now
increments `suppressed_opt_out` on an unauthenticated `/healthz`** — CG-12's
recorded caveat has gone from hypothetical to live, and
`docs/consumers/aitrader.md` **predicted this exact trigger**. Filed as
**CG-60**. (b) The NAS is **NOT "backup target only"** — measured, it already
runs **10 app stacks / 15 containers** including claude-mem's Postgres, so this
is a *tenth stack*, not a role change. Probed read-only: **20.8 GB RAM free,
load 0.29/16 cores, `datapool` 1%, and ZERO swap** — the swap is the only real
risk. **`ssh claude@nas` with passwordless sudo exists**, so CG-53/CG-55 are now
**executable**, under a declared blast radius the plan states rather than
assumes. Tailscale runs as a **container** — but host-networked with
`TS_USERSPACE=false` and a real `tailscale0` **host** interface, so publishing a
port is tailnet-reachable with no extra plumbing.

**All six open questions the spec raised are ANSWERED by the user, 2026-07-31 —
recorded as D1–D6 in spec §7 with their reasoning, so none is re-litigated.**
D1 closes `aiteam-harness`'s inbound path (**new row CG-61**, and Planner's
finding acted on); D2 lands the drafted homelab tailnet ACL **before** CG-55, so
`/healthz` is fenced from the start; D3 approves CG-56's acks, opt-in per
request; D4 builds the image on the box; D5 measures audit growth before setting
any retention window; D6 sets a `mem_limit` as an explicit deviation from local
convention. **The arc is dispatchable.**

Previously (2026-07-30, Builder): **CG-51, CG-35, CG-50 and CG-52 shipped as
ONE PR, [PR #42](https://github.com/mmackelprang/chat-gateway/pull/42)** — since
**MERGED** (2026-07-31), per a user-imposed gate on the IaC / secret-handling
path.

**One PR because CG-51 and CG-35(b) rewrite the same `KEY_FILE` handling in the
same two files** — the CG-11+CG-20 and CG-22+CG-9 reasoning. CG-50 and CG-52 rode
along as independent one-file docs fixes.

**CG-51 changes emitted behaviour, so CG-19's byte-identical-output proof was NOT
reused.** The key filename derives from `PROJECT_ID` now, and CG-19's objection —
any *fixed* new default mints a SECOND key on a host holding the old one — is
answered by a **guard**, not by the derivation: derived name absent + sibling
`<SA_NAME>-sa*.json` present ⇒ refuse, name the file found, **exit 3**, with
`ALLOW_SECOND_KEY=1` as the deliberate hatch. Measured against a stubbed `gcloud`:
the trap scenario went from *"already exists — not minting another"* + **exit 0** +
a `.env` pointing at the **dead** `chat-gateway-prod` credential, to a refusal that
cannot pass unnoticed.

**CG-35(a) removed a MISAPPLIED flag, and that is not a precedent for clearing a
real one** — user sign-off 2026-07-30 on exact terms. Rule #3's flag marks *code
not yet exercised against real Google endpoints*; this marked an unanswerable
question about which principal published, which `CLAUDE.md` records as CLOSED BY
CIRCUMSTANCE. **Reworded, never deleted** — the both-principals explanation is
load-bearing for a fresh-project operator. The matching `(VERIFY principal — see
comment)` in the emitted echo went with it, or the output would contradict the
comment it points at.

**Parity proven mechanically across EIGHT scenarios per script**, not asserted:
normalized `.sh` and `.ps1` output is byte-identical. CG-35(b)'s
`/srv/chat-gateway/C:/…/key.json` is now `/srv/chat-gateway/<basename>`; the `.sh`
is the half that moved. **The comparison carries a non-vacuous-output guard,
because an earlier run of this same check passed by diffing two EMPTY files.**

**Pre-merge review's one HIGH was real but its stated mechanism was wrong**, and
the defect underneath was worse: `[A-Za-z]:\\*` does not match `C:\x` at all in a
bash case arm, so a backslash path fell through to the *relative* branch. Two UAT
scenarios added for the gap that let it through.

**CG-50 measured, not read** — the fixture through the real `normalize_event`
gives `action.id` `None`, not `""`; the finding is kept, the value and the
open-work pointer are what changed, and the diff is confined to three lines
between two untouched ⚠ SHAPE-VERIFIED blocks. **CG-52 added ZERO figures** — it
qualifies `~10s` as *"by contract"* and links jobhunt-handoff §7, whose anchor was
verified against GitHub's own rendering rather than derived by hand.

Suite **202 → 202**, unmoved; no test added, and the reason is stated in the PR
rather than left implicit. Two flag removals branch-wide, both CG-35(a); none
added, none reworded. `CLAUDE.md`'s verification ledger is linked, not restated.

Previously: **CG-37 shipped,
[PR #40](https://github.com/mmackelprang/chat-gateway/pull/40)**: two source
comments, and nothing else. Both still named the **add-ons** runtime as the one
we are deployed on; production has been a **classic** Chat app since
2026-07-29. **Re-scoped, not deleted** — the add-ons statements were *true of
add-ons*, and `__cg_action__` remains a supported fallback `CLAUDE.md` says must
not be ripped out, so the correction names the runtime each sentence is about
and then says which one we run.

**Proven comments-only mechanically, not asserted:** `ast.parse` output of both
files is byte-identical to `main`'s (`#` comments are not AST nodes; a docstring
edit *would* have shown). Suite **202 → 202**, unmoved. No ⚠ flag cleared, added
or reworded, and `CLAUDE.md`'s verification ledger is untouched and not restated.
**UAT for a comment-accuracy PR is the accuracy of the sentences**, so all six
claims the new text makes were driven through the real code: the real classic
capture yields `action.id='approve'` natively (`id_source='google'`), the real
add-ons capture yields `None`, and `__cg_action__` still **beats** a live native
`'approve'` on both runtimes and is popped from `params`.

**Pre-merge review's one MEDIUM was PRE-EXISTING text inside the comment being
corrected** — `service.py`'s flat *"under an HTTP-endpoint deployment it is a
URL"*, where the ADR row it cites splits by runtime. Fixed rather than deferred,
because the correction left it as the only un-split clause in a sentence about
exactly that distinction; recorded because it is the one place this PR went past
its two stale sentences.

**`CLAUDE.md`'s test-count line was checked and is already correct** at 202 — the
first time today it has not needed moving, because only one Builder was running.
**CG-50 filed** — a third stale comment of the same family, which CG-21's
inventory missed.

Previously: **CG-33 shipped, [PR #39](https://github.com/mmackelprang/chat-gateway/pull/39) — MERGED** (`9daa672`; the
banner below was written while the gate was still held and said "OPEN and NOT
merged"):
`PubSubError` stops carrying the wire, and then joins the marked set. `_post`
looked the reason phrase up on the wire (`resp.reason_phrase` — httpcore fills it
from the literal HTTP/1.1 status line); it uses `httpx.codes` now, as CG-23's two
siblings already did. Measured over real TCP against a hostile status line:
`... HTTP 403 Forbidden key=FAKEKEYVALUE&token=FAKETOKENVALUE` → `... HTTP 403
Forbidden`. **The allowlist call the dispatch reserved for Builder: admit it** —
not for symmetry but because the structural guard reads MARKED classes only, so
an unmarked class's raise sites are unguarded. That meant teaching the guard a
second message-assembly shape. **Ordering is load-bearing and was measured as a
counterfactual** — the marker without the lookup hands the wire bytes to
`describe_exception`; they ship in one commit. **UAT confirms the row's own LOW
severity rather than inflating it:** a real `SubscriberLoop` against a real
uvicorn leaked nothing *before* the fix either — the danger was the docstring
telling the next person the value was safe to print. `_run`'s two reasons for
keeping its own `/healthz` format are **one** now, and the file says which one
went. Nine mutations, nine caught, including a control proving the three
pre-existing marked classes did not get weaker. Suite **201 → 202** (it was
190 → 191 before rebasing onto CG-26). No ⚠ flag touched. **Merge gate: user-imposed — the secret-handling path.**

Previously: **CG-26 shipped**
([PR #38](https://github.com/mmackelprang/chat-gateway/pull/38)): every rule family
in the fixture guard now has a test that proves it **fires** and a case that proves
it **discriminates** — and the guard finally reads the directories that actually
leaked. **The row's per-rule table was verified against the file rather than
trusted, and it was incomplete**: it named three unproven rules, but `PII` has a
**fourth** arm — the author-identity literal — with no test either.

**The widened half is the load-bearing one.** Both PII incidents landed *outside*
`tests/fixtures/`, so every rule above was aimed at the wrong directory. The scan
now also covers `docs/**/*.md`, `tests/**/*.py`, `tests/**/*.md` and root-level
`*.md` — **including itself**, which is the entire finding of incident 2: the real
tenant ids sat in this guard's own negative case, on `main`, and nothing had ever
read the guard. Scrubbed forward in both locations; **no history rewrite**, per the
user's decision. 0 lines added by the branch carry the real identifier, 3 removed.

**The rule set is deliberately NOT a naive port, because a false-positive guard is
a deleted guard.** `EMAIL` is not ported — it would have caught *neither* incident
(incident 1's leaked address is the author's own, which the guard must tolerate)
and would flag only this guard's own bait. `SUSPECT_VALUE` is not ported as
written — it keys off a JSON path prose does not have, and scores **62 false
positives**. Both are recorded as *review's* obligations with their measurements,
which is the documentation half the row asked for. `SECRETKEYVALUE` /
`SECRETTOKENVALUE` are tolerated **by design, not by annotation**, because the
files carrying them belong to CG-23 and CG-34.

**UAT reconstructed incident 1** — never previously tested against the guard — and
it **missed a `domainId` in a markdown table cell**, which the row explicitly
required. `DOC_TENANT_TABLE` added; 6 findings became 8. Pre-merge review caught
`DOC_TENANT_ASSIGN` matching any identifier *ending* in `customer`/`domainId` (it
had fired twice on this PR's own source and been worked around by renaming) —
fixed with a `(?<!\w)` lookbehind. **Five wrong counts** in the new prose were
found and re-measured. Suite **190 → 201**. No ⚠ flag cleared, added or reworded.

Previously: **CG-42 shipped**
([PR #37](https://github.com/mmackelprang/chat-gateway/pull/37)): two consumer docs
stated `0s / 5s / 15s` as when the three callback attempts land in the running
gateway. §7's *rule* was already right — *"an attempt fires on the first poll tick
at or after its due time, never earlier"* — but the worked example beneath it read
as a timetable, and it is **systematically optimistic in the exhaustion case**,
which is the only case those sections describe. `_run` polls, *then* calls
`process_due()`, *then* waits, so a poll cycle costs the attempt's own duration
**plus** the interval; an unreachable host times out rather than refusing, so every
attempt in that scenario is slow by definition.

**Four measured rows replace one worked example, and every row was re-measured
here** — including CG-31's two, because a number two documents got wrong is worth
a second independent measurement rather than a citation. Through the real
`CallbackForwarder` over real `httpx`: `0.3 / 3.3 / 10.4` free-running (the
contract), `0 / 5 / 15` on the fake clock (where the old figure came from), and on
a real `SubscriberLoop` thread at its real 5.0s interval `0.0 / 7.1 / 14.1`
(CG-31's figure, reproduced) and `0.0 / 15.0 / 30.1` against a callback that hangs
to the production 10s client timeout — **in-thread notice at 40.1s, against a
documented 15**. That last row was a *prediction* in CG-42's own body; it is
measured now. The rule is kept verbatim, `jobhunt.md` R7 links to §7 rather than
restating it, `BACKOFF_S`/retry logic/poll interval are untouched, suite unchanged
at **190**, and no ⚠ flag was cleared, added or reworded. **Two findings reported
not fixed** — *"retries span ~10s"* in `integration-guide.md`'s interaction
rules-of-the-road paragraph (CG-36's file, and **not** the paragraph CG-36 just
corrected) and a real email as an example value in `jobhunt.md`'s registry snippet
(CG-26's scrub).

Previously: **CG-36 shipped**
([PR #36](https://github.com/mmackelprang/chat-gateway/pull/36)): one clause and a
link, in one paragraph of `docs/integration-guide.md`. The `/v1/notify` summary
stated the collapsed dedupe count unconditionally; CG-32 made it degrade on an
`info` payload with no room. **The ladder is deliberately NOT reproduced there** —
the guide now says *that* the counter yields, *why* (hard rule #1: it is the
gateway's own decoration, so it is what gives), and *where* the count survives,
and links `docs/consumers/aitrader.md` §11 for *how*. Link-don't-re-summarize is
the whole point of the row, not a size preference: this repo has corrected the
"adapters' error branches" shorthand three times. Drift surface reduced to zero —
if the ladder changes, that paragraph stays true unedited. The link is the only
breakable thing in the PR and it was tested both ends against GitHub's own
renderer, not asserted: the paragraph emits **one** `href` despite the newline
inside its link text, and the live-rendered `aitrader.md` really carries that
anchor. Suite **190**, unmoved. No ⚠ flag cleared, added or reworded.

Previously: **CG-29 shipped**
([PR #35](https://github.com/mmackelprang/chat-gateway/pull/35)): `poll_once` prints
the detail CG-25 created, and still nothing else. A marker base class
(`src/chat_gateway/errors.py`, core-owned so `pubsub.py` need not import
`chat_api.py`) plus one `describe_exception` helper: the classes whose messages
this repo authors print in full, everything else prints its type name alone.
**An allowlist, because the shapes fail in opposite directions** — a denylist
prints the next unanticipated exception once, and a webhook credential has no
rotate-in-place.

**The load-bearing result is who got EXCLUDED.** `PubSubError` is not marked:
`_post` passes `resp.reason_phrase`, which httpcore takes off the HTTP status
line, so its `str()` carries server-controlled bytes — measured through the real
`PubSubPuller`. That is **CG-33**, still queued, and admitting it here would have
done exactly what that row predicts. A test pins the exclusion *and* the
measurement, so CG-33's author decides in the open.

Before/after measured over **real TCP** on the real R4 chain, not MockTransport:
`ChatApiError` / `ChatApiError` became `ChatApiError: in-thread reply failed:
ConnectError` / `... HTTP 403`, while a `google.auth`-shaped failure and a
pydantic `ValidationError` carrying a capability URL both still print their type
and nothing more. Pre-merge review found **two real bypasses** of the new
structural guard (construct-then-raise; subclassing a marked class) — both fixed
before merge and both now mutation-tested. **Nine mutations, nine caught.** Suite
**178 → 190**. The design call the row reserved for Planner was delegated to
Builder at dispatch; see the row. No ⚠ flag cleared, added or reworded.

Previously: **CG-31 shipped**
([PR #34](https://github.com/mmackelprang/chat-gateway/pull/34)): comments only, in
one file. `forwarder.py`'s docstring named `BACKOFF_S = (0, 3, 7)` as if those were
attempt times; they are **gaps**, so the three callback attempts fall due at
**0s / 3s / 10s**, and at **0s / 5s / 15s** in the running gateway because
`process_due()` runs only after a successful poll at the subscriber's default 5s
interval. Both re-measured here against a genuinely closed port — and a **third**
measurement is why the shipped wording is hedged: a **real** `SubscriberLoop` gave
**0s / 7s / 14s**, because a poll cycle is the attempt's own duration *plus* the
interval. **CG-42 filed** for that qualification in the two docs carrying the worked
example. `BACKOFF_S`, the retry logic and the poll interval are untouched; no ⚠ flag
touched; adds and removes no test.

Previously: **CG-34 shipped**
([PR #33](https://github.com/mmackelprang/chat-gateway/pull/33)): `httpx` logged
the whole request URL — `key` **and** `token` — on **every** request, success
included. Fixed by **redacting, not silencing**: a `logging.Filter` on the `httpx`
logger blanks every query and fragment VALUE and any userinfo password, so an
operator who deliberately set DEBUG keeps method, host, path, status and the
parameter NAMES and loses only the secret. Measured against the real gateway under
`logging.basicConfig(level=DEBUG)` — the credential was in the console **twice**
per run before, in **no** artifact after; both requests returned 200/202, because
this fires on the **happy path**. Pre-merge review caught the first draft leaving
`#token=SECRET` intact after the `#`; that shape is in the tests now. Suite
**151 → 178**. **Merge gate: user-imposed, this is the secret-handling path.**

Previously: **CG-21 shipped: reconciliation, not
execution.** The add-ons → classic migration was executed and live-verified
**2026-07-29**, outside any PR — the row never had code in it. Four documents
still described it as pending, or named add-ons as production: `CLAUDE.md`
(*"a migration is underway"*), `.env.example` (the routing-target block labelled
add-ons *"(today)"*), `docs/google-cloud-setup.md` step 8 (which gave the
add-ons answer for `CHAT_GATEWAY_INTERACTION_ROUTING_TARGET` unconditionally —
**not** part of CG-20's rewrite), and `docs/integration-guide.md` (which
contradicted itself within ten lines).

**The load-bearing finding: rollback has expired.** ADR-0001 D7 promised it as
*"switching two env values back"*, and both the ADR and the CG-21 row still said
so. `chat-gateway-prod` was deleted 2026-07-30, so there is nothing to point
those env names at, and E2 already proved classic cannot be toggled back —
reverting now means a **third project**. Not a defect in D7: the reversibility
was real while both projects existed, and it was spent deliberately. **CG-37
filed** — two `src/` comments still name add-ons as the runtime we are deployed
on. Docs only; this PR adds and removes no test (suite **151** on `main`).

> **⚠ Renumbered on merge, 2026-07-30.** CG-21's finding was filed as CG-35 in
> its own branch, but CG-19 had already taken **CG-35** and CG-32 took **CG-36**
> while all three were in flight. There is no allocator for these numbers — three
> parallel Builders each take "the next free one" and the collision is invisible
> until rebase. CG-21's is now **CG-37**.
>
> **CG-42 skipped 38-41 on purpose** (2026-07-30). CG-31's Builder was handed a
> **reserved range** at dispatch rather than left to pick the next free number —
> the first thing in this queue that has actually prevented a collision instead
> of recording one. The gap is not a lost row; it is the other concurrent
> Builders' reservations. **Numbers here are identifiers, not a sequence** — do
> not renumber to close it.

Previously: **CG-32 shipped**
([PR #32](https://github.com/mmackelprang/chat-gateway/pull/32)): the
dedupe counter now **yields to the app's content** instead of overflowing it.
`render` appending `" (×N since last notice)"` to a deduped re-delivery could
push an `info` payload the gateway had **already accepted with a 202** back over
the field cap, and the uncaught `ValidationError` landed in the same place CG-30
had just emptied — measured 202 / 202 / 202 / **500**, now 202 throughout. Per
the user's option-1 decision: full form, then `" (×N)"`, then nothing. **Hard
rule #1 is the justification and it is in the code** — the counter is the
gateway's own transport decoration, so it is what gives, never the app's body.
`info_max_combined_length()` is **unchanged at 3989** and a test pins the
literal, because no request that succeeds today may start failing. Suite
**144 → 151**. **CG-36 filed** from its docs pass.

Previously: **CG-19 shipped**
([PR #30](https://github.com/mmackelprang/chat-gateway/pull/30)): the
Marketplace-SDK comment is corrected in all three IaC paths, as a **warning that
stays in the file** rather than a deletion — it is the exact sentence that put
this project on the add-ons runtime. Enabling the API stays; only the
prerequisite claim goes. Comments and illustrative defaults only, proven
mechanically: stripping comments leaves **one** changed line repo-wide, and both
scripts produce **byte-identical output** to `main` when run end to end against a
stubbed `gcloud`. Suite unchanged at **144**. The `KEY_FILE` default is
deliberately **not** renamed — see the row. **CG-35 filed.**

Previously: **CG-23 shipped**
([PR #29](https://github.com/mmackelprang/chat-gateway/pull/29)): the
`resp.text[:200]` echo is gone from `webhook.send` and `chat_api.send`. Measured,
not argued: driving a real 403 through the real gateway over real TCP put the
webhook's `key` AND `token` into **three** artifacts before the fix — the HTTP
502 body handed back to the calling app, the delivery log, and the JSONL audit
file on disk — and into **none** after. Suite **140 → 144**. **CG-33 and CG-34
filed** — `PubSubError` makes a false claim about its own reason phrase, and
`httpx` logs the whole webhook URL at INFO.

Previously: **CG-30 shipped**
([PR #28](https://github.com/mmackelprang/chat-gateway/pull/28)): the `info`
render path's combined title+body overflow is a **422 naming the limit and the
size**, where it was an uncaught **500**. Scoped to `info` and derived, not
hardcoded — `Notification.body`'s global `max_length` is untouched, because
`alert`/`warning` at title-200 + body-4000 are **accepted today** and had to stay
accepted. Measured before *and* after at the endpoint; suite **136 → 140**.
**CG-32 was filed** from its verification pass and has now shipped, above.

Previously: **CG-11 + CG-20 shipped as ONE PR**
([PR #27](https://github.com/mmackelprang/chat-gateway/pull/27)), per the user's
combine decision: CG-11's job was to adopt ADR-0001
§7, and §7 carried the very error CG-11 existed to fix, so the ADR had to be
corrected before it could be adopted — and the ADR is CG-20's file.

**The correction.** *"A selection widget is not an interaction trigger"* was
add-ons-scoped evidence written up as a universal claim. On **classic** — the
runtime this project now runs — a widget's `onChangeAction` **is** an
interaction trigger and fires on a card with no button at all. The old sentence
also blamed **Pub/Sub transport** for what is a property of the **runtime**, and
welded that to the untested modal-dialog inference with one confident dash. The
two claims are now stated separately, at their two different confidence levels,
in ADR-0001 §7, `CLAUDE.md` and `docs/consumers/jobhunt.md` R6.
`docs/integration-guide.md`'s section was **already correct** and exactly one
stale parenthetical changed there.

**The `docs/google-cloud-setup.md` half was the urgent one and did not get
crowded out.** That document still described **`chat-gateway-prod`** — deleted
2026-07-30 — as the live project, in a `gcloud projects create` command, a ✅
present-tense provisioning box, the console's topic path and the key filename to
hand back. A reader following it would have created a second project named after
a deleted one and wired credentials by a dead key. Rewritten as dated history,
per project, with the live project named. **CG-31 filed** from this item's
pre-merge review — `forwarder.py`'s docstring still names the retry *gaps* as if
they were attempt times, which this docs-only PR corrected everywhere except
`src/`.

Previously: **CG-27 and CG-28 shipped in parallel**,
one Builder each, in separate worktrees.

**CG-27**: the aitrader consumer handoff doc, and with it the removal of a
**false claim** that had been live in `docs/consumers/aitrader.md` since
2026-07-24 — that the gateway has no callback-to-consumer mechanism at all.
aitrader's guarantee was never affected; it is now stated on its real and
stronger basis, that the mechanism exists and this app is locked out of every
part of it. **CG-30 filed** from that item's verification pass — `info` severity
500s on a payload `alert` accepts; measured, not predicted.

**CG-28**: the jobhunt consumer
handoff doc lands as a *sibling* of the contract doc, so CG-11's five prose
locations were not touched; its live blocker is stated as "routing resolves,
`callback_url` is the only missing value, and jobhunt has no receiver — so
configuring it proves R7, not R3", and the 2026-07-30 dev-registry change is
recorded as a dated observation rather than deployed state. Two findings filed
for jobhunt from its review: `callback_url`'s port does not match
`review_ui.py`'s default, and `/v1/notify` would 503 for `job-hunter` for want
of a `routes` map. Previously: **CG-12 shipped**: suppressed inbound is
now counted at `/healthz` and still recorded nowhere, per the user's option-A
decision, and the "reached nobody" reading of the counters was refuted in review.
**CG-25 shipped**: `send_text()` now has the transport-error guard `send()`
always had, so jobhunt R7/R4's reply path fails *typed*. **CG-29 filed** from its
UAT — the fix is a net win in the R7 delivery log and a measured loss on one R4
console line; both are evidenced, not argued. Previously: CG-22 + CG-9 shipped as
one PR — the three real classic
captures are landed, scrubbed and re-derived, and the guard gained the two rules
that had never been proven to fire. CG-4, CG-5, CG-8, CG-24 also shipped; CG-14
closed as obsolete. **CG-26 gained a finding** — see its row.)

## User decisions on ADR-0001 (2026-07-29) — final, do not re-ask

The ADR's §12 open questions are answered. Recorded here because they are what
unblocks half this queue.

| ADR ref | Decision |
|---|---|
| **D2** — `__cg_action__` as the gateway-reserved action-identity key | **APPROVED**, including the guard that discards topic-path-shaped values arriving from Google-native sources. Unblocks CG-10. |
| **D6** — a third flag word | **NO.** `⚠ SHAPE-VERIFIED` stays the only addition; hard rule #3 caps the vocabulary. Routing fragility is recorded in prose + `/healthz`, never a new flag. |
| **§8** — interaction dead-man | **APPROVED** at `every:7d`, cleared by any `CARD_CLICKED`. A genuinely quiet week raising a false alarm is accepted; the remediation is one tap. Filed as CG-14. |
| **E1 / E2** — classic-deployment experiments | ~~DEFERRED, do not run~~ — **SUPERSEDED 2026-07-29: the user authorized them, E1 RAN AND PASSED, E2 is answered.** See the section below. CG-15 / CG-16 are closed as executed; CG-17 / CG-18 remain deferred. |
| **Migration to option D** | **APPROVED IN PRINCIPLE** if E1 later passes — and it did. Migration is **DONE**: production cut over **2026-07-29** and it is live-verified. *(This cell read "now **underway** (a fresh project is provisioned)" until CG-21 reconciled it on 2026-07-30 — provisioning was the last state anyone wrote down, not the last state that happened.)* D3's portable card convention shipped as CG-13 and **paid for itself**: the migration cost zero producer card changes. The exit is no longer cheap in one direction, though — see CG-21 under **Recently shipped** for what rollback costs now. |
| **DEC-1** (CG-4 threadKey) | Keep the body `thread.threadKey`, drop the query parameter. The `messageReplyOption` caveat is mandatory in the docstring. |
| **CG-12** shape | **Option A** — a bare counter on `/healthz`. No space id, no app id, no content. Pure rule-5 visibility, zero rule-6 surface change; note in code that `/healthz` is unauthenticated. |
| **CG-12** — one counter or two? *(2026-07-30)* | **KEEP BOTH.** CG-12 shipped `suppressed_opt_out` and `suppressed_not_authorized` while the row above says "a bare counter" (singular). Reviewed and settled: the spec sanctions the split explicitly, option A's constraint governs what is **stored** (no space, no app id, no content — which two ints satisfy), and one number cannot distinguish *"500 people were refused"* from *"500 events landed in a space nobody serves"*. Two different investigations. **Do not collapse them.** |
| **CG-11 + CG-20** — combine? *(2026-07-30)* | **YES — ONE PR.** CG-11 adopts ADR-0001 §7, but §7 carries the same add-ons-derived error the no-button `onChangeAction` capture disproved, so §7 must be corrected *before* it is adopted — and correcting the ADR overlaps CG-20, which owns §5/§10/§12. Two sequential PRs would mean the second contradicts the first. Same reasoning that made CG-22+CG-9 one PR. |

## What E1 and E2 settled (2026-07-29) — supersedes the deferral above

The user authorized the experiments after this queue was written. Both returned
results, and they change the framing of the whole bridge.

**E1 — PASSED, decisively.** In a throwaway project with a **classic**
(non-add-on) Chat app on Pub/Sub, live:

| Probe | Result |
|---|---|
| Card button with an **ordinary** function name (`approve`) | `CARD_CLICKED` **reached Pub/Sub natively** — no topic-as-function needed |
| `action.id` | **populated: `'approve'`.** Native action identity works |
| Selection widget `onChangeAction` | **FIRED** (`action.id: 'onDecision'`, `params: {"decision": "approve"}`) — the thing that dies with `code 13` under add-ons |
| Button event params | carried its own parameter *and* the harvested form input: `{"jobId": "e1-001", "decision": "approve"}` |
| Envelope format | the **classic flat** format; CG-1's normalizer parsed it correctly and tagged `envelope_format: 'classic'` — **first live exercise of that path**, and it works |

**Two consequences, both already applied in CG-13:**

1. **`__cg_action__` is a FALLBACK, not the primary mechanism.** It stays — it
   is load-bearing on the runtime deployed *today*, it still outranks the native
   slot so one card behaves identically on both sides of a migration, and this
   is the same support-both posture the gateway already takes on the two
   envelope formats. Do **not** rip it out. Its framing in `CLAUDE.md` and the
   integration guide now says classic gives native identity and is preferred.
2. **CG-14's justification largely evaporates** — see its row, now `⏸ blocked`.

**E2 — answered, definitively, and it is a harder answer than the ADR expected.**
The Workspace-Add-on toggle is **create-time only**: add-on → classic **cannot**
be toggled on an existing app. ADR-0001 §5 option D recorded this as
"contradictory evidence"; it is now settled. A migration therefore requires a
**new Chat app**, which means a **new GCP project** (Chat app config is
per-project). ADR D7's parallel-project-and-cut-over approach was therefore not
merely prudent — it was the only available path.

**Migration status: DONE and live-verified 2026-07-29** — corrected 2026-07-30
by CG-21, which found this line still reading *"underway"* a day after cutover.
Project `chat-gateway-gw` (`#860649224827`) is the live one and the only one.
The CG-2 setup script ran **clean end to end** on it, including the add-ons
service-agent step. That is the **second virgin-project run**, which matters for
flag discipline: CG-2's IaC was previously reviewed-by-reading only and is now
genuinely exercised. (The Terraform path is still unapplied — only the script
path has run.)

**Provisioning was never the finish line, which is how this line went stale:**
it recorded the last thing written down rather than the last thing that
happened. `chat-gateway-prod` was deleted 2026-07-30, so the migration is also
now **irreversible** — see CG-21 under **Recently shipped**.

This is the work list Builder clears, one PR per item. Planner appends; the
user sets priority. Builder claims the topmost `📋 queued` item whose
dependencies are all met, ships it as a PR, and marks it `✅ shipped`.

Status legend: `📋 queued` · `🔨 in flight` · `⏸ blocked` · `✅ shipped`

Before claiming anything, read `CLAUDE.md` — the six hard rules govern every
item here.

**Shared spec + plan for CG-3 … CG-12:**
[spec](superpowers/specs/2026-07-29-live-verification-followups-design.md) ·
[plan](superpowers/plans/2026-07-29-live-verification-followups.md).
The plan's Parts A–G map one-to-one onto the queued items below; each Part is
one PR. The plan's stated baseline (`python -m pytest -q` → **70 passed**) is
the count from when it was written and moves with every shipped item — it is
**95** as of CG-7. Take the real count from the suite, not from the plan. (On
the Windows dev box use `python`, not `python3`.)

**Standing constraint for every item here — REWRITTEN 2026-07-30.** The previous
version said *"today's live session cleared two flags and no more; `PubSubPuller`
stays ⚠ LIVE-UNVERIFIED"*, which is superseded: the 2026-07-30 session cleared
four flags, `PubSubPuller` among them (CG-24). It was a dated snapshot phrased as
a forward-looking rule, which is why it aged into a contradiction with the order
list eleven lines below it. What actually still stands:

- **`aitrader` stays `allow_inbound: false`**, locked out of every inbound path.
  Nothing in this queue widens any tenant's inbound surface. This is the one that
  is genuinely permanent — hard rule #6, and it needs explicit user sign-off
  naming that rule to change.
- **Do not clear a flag this session's evidence does not reach.** For the current
  residue read `CLAUDE.md`'s verification ledger, which is the single
  authoritative list — do **not** restate it here, because every restatement of
  it in this repo has drifted within two PRs.
- **The `chat-api-push@system.gserviceaccount.com` grant is CLOSED, not open.**
  Both principals were bound in `chat-gateway-prod`, which is deleted, so it is
  unanswerable rather than unproven. It is not a task; do not file work against
  it.

---

## Queue

**Order is the user's, set 2026-07-29**, with one Builder-side correction:
CG-3 was promoted above CG-10 because CG-10 *depends* on it (CG-10 rewrites the
pinning test CG-3 lands, and CG-3's fixture is the only real-data evidence
CG-10's behaviour change can be tested against). A declared dependency
outranks a preference; nothing else was resequenced. CG-3 has since shipped.

**The production-readiness arc — CG-53 … CG-59, filed 2026-07-31 by Planner.**
Shared [spec](superpowers/specs/2026-07-31-production-readiness-arc-design.md) ·
[plan](superpowers/plans/2026-07-31-production-readiness-arc.md); the plan's
Parts A–G map one-to-one onto these rows, one PR each.

| Item | State | Note |
|---|---|---|
| **CG-60** · repo-wide correction of the one-space premise | ✅ done (#44) | Plan Part H. Merge gate **released by the user 2026-07-31**; merged the same day. Consumer contracts. **Sequenced FIRST.** Filed **CG-62** |
| **CG-61** · close `aiteam-harness`'s inbound path (decision D1) | ✅ merged (#50) · ⏸ **operator action outstanding** | Gate released by the user; merged 2026-07-31 as `dced002`. ⚠ **Merging is not finishing** — the PR changed only `registry.example.yaml`; the **live gitignored registry edit is a separate operator action**, and **CG-55 depends on the live file**. ⚠ **Still outstanding — measured, not assumed:** `load_registry("config/registry.yaml")` at **2026-08-03 19:15:56Z** returned `aiteam-harness allow_inbound=True`, and the `allow_inbound` key is **absent** from that app's block (file mtime `2026-07-30T15:49:24Z`), so the `True` is the loader default — exactly D1's reasoning. Re-measure rather than trusting this line; it dates from before the edit, not after it. Suite 246 → 247. Plan Part I |
| **CG-53** · deployment artifacts + secret-safety proof (**no deploy**) | 📋 queued · ✅ **plan refreshed 2026-08-03** | ⏸ **merge gate** — secret-handling path; **held, the user's to release**, and the row now states exactly what releasing it approves (four things, **none of them a deploy**). ✅ **The premise was RE-MEASURED, not re-quoted** — it is the one load-bearing fact here and it lives in a repo this one does not control: through the homelab redactor's **real** `is_secret_key`, all seven credential vars still miss, and end to end through the **real** scan gate a payload keeping a live-shaped API key and webhook URL **exited 0**. ⚠ One correction: *"the `__<SUFFIX>` convention defeats it"* is only half right — bare `GOOGLE_CHAT_WEBHOOK_URL` is missed **anyway** (no `URL` suffix), so **renaming would not fix the webhook family**, the one secret with no rotate-in-place. ⚠ **Ten drifts found and corrected in Part A** across eight merged PRs — **two would have failed at runtime**: A2's `build_runtime()` unpack is now a **6**-tuple (CG-68's `sweeper`), and §5's compose mounted the registry where its own env var did not point. Also folded in: **CG-70's owed runbook line** (that row stays **open**), the real state tree (**four** directories hold tenant bodies; `quarantine/` is never swept), **D2's deferral** replacing an *"ACL lands BEFORE deploy"* claim, and `202`→**345**. Plan Part A |
| **CG-54** · queue **and inbox** durability (JSONL under `CHAT_GATEWAY_STATE_DIR`) | ✅ done (#45) | Part B. Shipped 2026-07-31: `journal.py`, both queues, replay + compaction + the mid-flight answer. 246 tests |
| **CG-64** · post-CG-54 stale durability claims in `CLAUDE.md` + `docs/integration-guide.md` | ✅ done (#46) | Filed by CG-54's Builder. Shipped 2026-07-31 after CG-60 (#44) cleared the way. Item 4's "four fields degrade" was **five** — measured, and the row records both |
| **CG-55** · first NAS deploy + live smoke | 📋 queued | ⏸ **merge gate** + **Builder-executed over SSH**. Depends on CG-53, CG-54, **CG-61**, **CG-75**, **CG-76** (⚠ **the CG-76 dependency was NOT recorded on this row until 2026-08-03** — the user's 2026-08-02 pre-deploy-blocker decision existed, and `grep` found it named nowhere under either CG-55 entry. A first deploy whose dead-man switch has six ways to drop an alert with `/healthz` green is a first deploy that should not happen, and aitrader's contract surface is exactly that switch), **CG-75** (⚠ **added 2026-08-03, user decision** — this gateway has never run on a box with a real disk that can fill, so CG-75's *"low likelihood"* is an artifact of never having been deployed, and **CG-55 is the event that changes it**; a first deploy that can turn a full disk into an unbounded send storm against Google is a first deploy that should not happen), and ~~⚠ an **external homelab-repo prerequisite (D2)**~~ — ⏸ **D2's tailnet ACL is DEFERRED by the user, 2026-08-03. It no longer gates this row; the dependency is recorded, not deleted.** ⚠ **Paired with a second decision the same day that this row must BUILD: bind the published port to the LAN interface, not `0.0.0.0`** (both, with reasoning and residual, in the row). Part C |
| **CG-56** · inbox delivery semantics: at-most-once → ack | 📋 queued | ✅ **APPROVED (D3)** — opt-in per request; default path unchanged. Part D |
| **CG-57** · jobhunt `callback_url` → passive inbox polling | 📋 queued | Depends on CG-54 and **CG-56 (approved, D3)** so the contract doc is written once. Part E |
| **CG-58** · structured adapter failures + `Retry-After` | 📋 queued | Part F. Touches `adapters/` — **no ⚠ flag may be touched** |
| **CG-59** · long-run observation + a deployed `/healthz` | 📋 queued | Depends on **CG-55** — the soak clock starts when it lands. Part G |
| **CG-62** · does replacing the Chat app re-price the ledger? | 📋 queued | **Filed by CG-60's Builder, deliberately NOT answered.** ⏸ needs **explicit hard-rule-#3 sign-off** — a Builder docs row may not decide it. No plan yet |
| **CG-65** · shrink the journal's body window, harden both audit trails, and correct `aitrader.md` | ✅ done (#52) | Compact-on-drain, `0600` on both audit trails, the **unrevivable quarantine**, and the contract correction. Pre-merge review found a **data-loss race** in compact-on-drain — both producers journal the `open` before taking the queue lock, so `compact([])` could erase a record already on disk; fixed by recomputing survivors under the journal's own lock. Suite **247 → 268**. [Spec](superpowers/specs/2026-07-31-body-retention-and-audit-hardening-design.md) · [plan](superpowers/plans/2026-07-31-body-retention-and-audit-hardening.md) Tasks 1–9 |
| **CG-68** · time-bounded pruning of the inbound audit trail | ✅ done (#54) | **The first row that DELETES a tenant's content.** 30/7/0 via `CHAT_GATEWAY_INBOX_RETENTION_DAYS`; the filename is the retention key, so pruning never opens a file holding message bodies. Amends `integration-guide.md:366`'s published *"never pruned"* (A4). ⚠ **New user decision A5** — the boot guard **refuses** rather than warns, and is stricter than the non-recursive glob requires (decision 4 below). Review found **0 HIGH, 6 MEDIUM, 6 LOW**; the sharpest was **M2** — the sweeper would have pruned `state/deliveries/` (ADR D7, permanent by decision), because the guard only fenced the quarantine and `state/deliveries` is its *sibling*. Suite **268 → 314**. Plan Tasks **10–14** |
| **CG-69** · published-promise inventory (process control) | 📋 queued · ⚠ **evidence list now at FIVE** · ✅ **designed 2026-08-03** | Filed by CG-65's Planner. Three changes in one day invalidated a guarantee recorded in a file nobody in the loop was reading. ⚠ **Instances 4 and 5 added 2026-08-03 by CG-76's Planner** — #4 CG-74 falsifying its own spec's `/healthz` strings, #5 CG-76 finding the delivery write-path spec §5's *"the only thing standing between a silently-dropped aitrader alert and a green `/healthz`"* to be false. **Every one was caught only because somebody independently went looking**, and #5 took two independent sweeps of the same code path to find its last two doors. ⚠ *That entry ended "**Still no plan**" when it was written; this PR falsified it hours later and it is corrected rather than left standing.* **Designed the same day — inverted and one fifth the size the row proposed**, because measurement falsified the row's stated cause (**instances 4 and 5 are both inside the sweep's own list**, and the sweep found counterexamples where the diff *did* contain the sentence) and showed the row's proposed pairing has already rotted: **8 of the 14 code citations in the live contracts point at the wrong code**, three of them in `aitrader.md`'s hard-rule-#6 enforcement table, while the same files' name-anchored citations are 0 of 8 wrong. [spec](superpowers/specs/2026-08-03-published-promise-inventory-design.md) · [plan](superpowers/plans/2026-08-03-published-promise-inventory.md) |
| **CG-70** · the `0600` chmod is create-only — a pre-existing `0644` day-file keeps its mode | 📋 queued · **decided** | Filed by CG-65's Builder (LOW). ✅ **Planner call made 2026-08-02: option (a), and the row's own argument against it was measurably wrong.** `strace` shows every append already issues the stat and the kernel already returns the mode in it — (a) costs **zero** extra syscalls in the steady state. (b) goes to CG-53 for the files (a) provably cannot reach; (c) rejected. Severity unchanged; the reason changed from *"defer, it is low"* to *"do it, it is free"*. Spec §6 |
| **CG-72** · `/healthz` cannot see two of the four threads (rule #5) | ✅ done (#56) | `dispatcher` and `monitor` now publish `thread_alive`/`thread_started` + staleness and **degrade**. Proven by killing both threads in a **real** server through the documented hole — an exception raised inside `_run`'s own handler, not `.stop()`: on `main` `/healthz` answered `status: ok`, `reasons: []`; on the branch, `degraded` with one reason each. Suite **314 → 324**. Review found **0 HIGH, 3 MEDIUM, 6 LOW** — the sharpest, **M1**, was a reason string asserting *"neither completing nor raising"* on two blocks that **count no failures**, copied from siblings where a counter branch made it true; reworded, and the counters filed as **CG-74**. **M2**: `last_pass_at` stamped the pass **start** while three places defined it as completion — the plan's own "do not call `self._now()` twice" had silently changed the field's meaning. [spec](superpowers/specs/2026-08-02-runtime-lifecycle-and-liveness-design.md) §2.6/§4 · [plan](superpowers/plans/2026-08-02-runtime-lifecycle-and-liveness.md) Part A |
| **CG-75** · a raising `_finish` re-sends the same job every second, unbounded | ✅ done (#58) | **Pre-existing; surfaced by CG-72's review, not caused by it.** `_finish` calls `self._log.record(...)` **before** the job leaves `_jobs`, and the delivered path never advances `next_attempt_at`. `DeliveryLog.record` does raw `mkdir`/`open`/`write` with **no guard** — so an `OSError` there propagates out of `process_due` with the job still due, and the next pass **sends it again**, once a second, forever. **Measured 2026-08-03, not reasoned about: one message, one successful send, then 60 passes → 60 SENDS TO GOOGLE in 60 seconds.** Exactly the failure `_journal_write`'s docstring exists to prevent for the journal, on the one write path that never got it. Severity **HIGH on impact**; the *"low likelihood"* half is now recorded as **an artifact of never having been deployed** — hence the CG-55 dependency (user decision 2026-08-02). [spec](superpowers/specs/2026-08-03-delivery-write-path-robustness-design.md) §3 · [plan](superpowers/plans/2026-08-03-delivery-write-path-robustness.md) **Part A** |
| **CG-74** · `Dispatcher` and `HeartbeatMonitor` count no failures — CG-68's F3, counter half | ✅ done ([#60](https://github.com/mmackelprang/chat-gateway/pull/60)) | **Filed by CG-72's Builder from its own pre-merge review (M1).** The liveness half shipped; the counter half did not. `retention.py` and `pubsub.py` both carry `*_failures` / `consecutive_*_failures` and a reason branch **above** their staleness branch — which is the only reason their *"wedged rather than erroring"* wording is true. ⚠ **Two `/healthz` strings now point at this row's absence in words**; building it means correcting them. ⚠ **The row's own claim is NARROWED by measurement (2026-08-03):** *"the staleness branch never fires at all"* holds for the **whole 72.5-minute backoff ladder** (measured worst staleness **1.0s** against a 600s budget over 400 passes) and then **stops holding** — at t=4350s the ladder exhausts, `_finish(job, "failed")` raises, and the retry path degenerates into CG-75's 1/second storm, which *does* trip staleness. The blindness is bounded and long, and what ends it is the failure getting worse. ⚠ Ships **after CG-75**, never concurrently — same two functions, same two strings. [spec](superpowers/specs/2026-08-03-delivery-write-path-robustness-design.md) §5 · [plan](superpowers/plans/2026-08-03-delivery-write-path-robustness.md) **Part B** |
| **CG-76** · the dead-man switch's SIX doors to a silently-dropped alert | ✅ done (PR #63, 2026-08-03) · ⚠ **WIDENED by user decision** | ✅ **All six closed, and each was DEMONSTRATED rather than asserted** — a real uvicorn server, real loop threads, real HTTP, with `main` run as the control on every scenario. Door 6 on `main` reproduced its spec finding verbatim: *"(NONE — literally nothing moved)"*; on the branch `delivery_failures` moves and `status` flips, while `missed` correctly stays `1`. Suite 345 → **359**. ⚠ **Pre-merge review then found a seventh way to break this switch — one the FIX introduced**, and it is recorded in the banner above rather than here because it is not one of the six: the new 422 fired on the **liveness ping**, so a removed alert route froze `last_seen` on a healthy consumer and delivered a **fabricated** *"heartbeat missed"* once the route returned (measured end to end). Fixed before merge — the guard now only refuses a check that does not already exist. ⚠ **`alerts_undeliverable` counts ATTEMPTS, not distinct alerts**: an unmarked check re-fires every scan (that is the self-heal), which measured at **1 increment + 1 delivery-audit line per scan ≈ 1440/day** for ONE misconfigured check, into `<state_dir>/deliveries/`, which ADR-0002 D7 never prunes. The counter shape is required by D4c and was NOT changed; what changed is that the field and its `/healthz` reason now say *attempts*, and `checks_undeliverable` is the distinct-check number beside it. **Filed as ONE ordering defect. The user widened it to TWO. It is SIX**, and the count moving four times is the finding worth more than the number — doors 5 and 6 were found only by an **independent second sweep** commissioned because the brief asked whether two was complete. **Five of the six raise nothing**, so `scan_failures` stays `0` and `/healthz` answers `ok`; on **door 6** — a failed 24h REPEAT alert — **not one field in the whole body moves**, because `heartbeats.missed` was already `1` from the first fire. ⚠ **`missed` is not a signal and never was:** measured as a control, it moves *identically* on a DELIVERED alert and a dropped one. **Three of the six need no fault at all** — no disk error, no misconfiguration, no exception. Shared cause: `due_alerts` records *"I have alerted"* before anything is alerted — a promise about the future persisted as a statement about the past. Fix moves the mark to `mark_alerted`, **after** the alert is accepted into the durable queue, taking this path from at-most-once to **at-least-once** — the posture `_finish`, `_journal_write` and `Inbox._audit` each already took, quoted rather than re-decided. ⚠ **CG-74's `scan_failures` keeps degrading but its ORIGINAL justification EXPIRES** (the weaker surviving one is stated, not the strong one re-quoted) and **its UAT scenario now produces a better result on purpose** — the alert gets delivered. ⚠ **Four new degrade inputs on an endpoint consumers alarm on** — flagged for the user, not slipped in. **CG-55 depends on this** (pre-deploy blocker, user decision 2026-08-02 — ⚠ which no CG-55 row actually recorded until now). [spec](superpowers/specs/2026-08-03-dead-man-alert-loss-design.md) · [plan](superpowers/plans/2026-08-03-dead-man-alert-loss.md) **Part A** |
| **CG-77** · clock skew silently disarms the dead-man switch | 📋 queued | **Filed by CG-76's Planner, 2026-08-03**, from that row's independent second sweep. Every timestamp `Check` reasons about is **persisted**, so a clock that was wrong once stays wrong forever: a host whose clock ran ahead when `refresh()` wrote, then corrected back, leaves a check that **never becomes due** — measured, `is_missed=False` a full day past the real deadline; and a future `last_alerted` suppresses the alert on a check that IS missed. ⚠ **`/healthz` publishes no deadline at all**, so nothing says so — the only view is the authenticated `GET /v1/heartbeat/{source}`. ⚠ **Deliberately NOT folded into CG-76**: those six doors drop an alert that became due, this stops it **becoming** due, and CG-76's fix does nothing for it. Needs a design decision (clamp / reject / re-stamp / degrade-and-leave) before a plan. No plan yet. [spec](superpowers/specs/2026-08-03-dead-man-alert-loss-design.md) §2.9 A |
| **CG-71** · four `.start()`, zero `.stop()` — the runtime has no shutdown path | 📋 queued | CG-68's deferred L4, **measured and found broader**: not the retention row's missing cleanup but four threads with no shutdown path at all. ⚠ **`uvicorn.run()` does not return on SIGTERM** — a `try/finally` is a measured no-op. Depends on **CG-72** (same two classes; must not run concurrently). [spec](superpowers/specs/2026-08-02-runtime-lifecycle-and-liveness-design.md) §5 · [plan](superpowers/plans/2026-08-02-runtime-lifecycle-and-liveness.md) Part B |
| **CG-73** · ~~five~~ **three** print/persist sites bypass CG-29's allowlist | 📋 queued · ⚠ **narrowed 2026-08-03** | Filed by CG-71's Planner, **not folded in**. `retention.py` uses `describe_exception`; `delivery.py` and `heartbeat.py` interpolate a raw `{exc}`. **Drift in a hard-rule-#2 control, not a proven leak** — stated at that confidence. `test_error_surfaces.py` cannot see it: it reads construction sites of *marked* classes; these are print sites of unmarked ones. ⚠ **CG-74 closes TWO of the five as a side effect** — it rewrites both `_run` handlers to render `last_pass_error` / `last_scan_error` through `describe_exception`, and those handlers' prints are two of this row's sites. **The residue is three, all in `delivery.py`:** `_journal_write`'s print, and the **two that persist into the delivery log** (`process_due`'s `"attempt {n}: {exc}"` and `_finish`'s `"gave up after {n} attempts: {exc}"`) — which are the sharper two anyway, because they reach disk rather than a console. Counted down here rather than left at five: a count with two homes is this repo's own recorded failure mode. ⚠ **The *"not a proven leak"* above is now scoped to these three.** For the **two CG-74 closed** it was settled the other way on 2026-08-03 — measured, `main` vs branch, one home for the measurement and it is CG-74's row. No plan yet. CG-71 spec §7 |
| **CG-66** · post-#45 residue outside the two CG-64 files | 📋 queued | Filed by CG-64's Builder. `README.md`'s **98**-test count, `__init__.py`'s module map, `journal.py`'s citation of a runbook line that does not exist, `.env.example`. ⚠ **now doc-only** — its one non-doc item was split out and shipped ahead of it as **CG-67** |
| **CG-67** · `.gitignore` — stop `state/` from ever being committed | ✅ done (#48) | **Split out of CG-66 and promoted by the user**, because it is a live path to committing message bodies and CG-53/CG-55 are the rows that first run the gateway from the repo root. Config-only |

**Recommended order is the table order, and it is NOT the order the arc was
briefed in.** The brief had deploy first. Three rows move ahead of it:

**All six open questions were answered by the user on 2026-07-31 (D1–D6) and are
recorded in spec §7 with their reasoning. Two of them change this sequence:**
**CG-61** is new and must precede CG-55, and **CG-55 gains an external blocker**
— the drafted homelab tailnet ACL, applied first, so `/healthz` is *fenced from
the start rather than fenced afterwards*. That is **homelab-repo work a
chat-gateway Builder cannot perform**; CG-60, CG-61, CG-53 and CG-54 all proceed
in parallel with it, and only CG-55 waits.

⚠ **The ACL half of that paragraph was AMENDED by the user on 2026-08-03 — the
paragraph is kept because it records what was decided on 2026-07-31, and this is
what changed since.** The ACL is **deferred, not cancelled**: it is still wanted,
it is simply no longer a blocker on CG-55, so **CG-55 no longer waits on
homelab-repo work.** What still gates it is all **in this queue**: **CG-53**
(📋 queued) and **CG-61's live-registry operator action** (measured outstanding —
see its row). CG-54 and CG-75 are done. The reasoning and the accepted residual
live in **CG-55's row** — one home, not three.

⚠ **A second exception to "the table order", added 2026-08-03: CG-75 must
precede CG-55**, exactly as CG-61 does, and for a structurally identical reason —
it is a prerequisite that was filed after the row it blocks, so appending it left
it below. **The rows have deliberately NOT been reshuffled** (the user sets
priority; Planner appends), so the dependency is recorded in three places instead:
CG-55's own row, CG-75's row, and here. **CG-74 must follow CG-75** — same two
functions, same two `/healthz` strings, never concurrently, the same constraint
CG-71/CG-72 carried.

⚠ **A third, added 2026-08-03: CG-76 must precede CG-55**, for the same
filed-after-the-row-it-blocks reason, and the rows are again **not reshuffled**.
This one is worse than the other two, because **the dependency was decided by the
user on 2026-08-02 and then written down nowhere** — measured 2026-08-03,
`grep -n "CG-76"` named it under neither CG-55 entry. Now recorded in CG-55's
row, CG-76's row, and here. **CG-76 must also follow CG-74** — same class, same
two counters, same `/healthz` strings, and CG-76 *rewrites* what CG-74's
`scan_failures` reason claims. CG-74 is done, so this is satisfied.

⚠ **CG-77 does NOT gate anything** and is explicitly **not** a CG-55 blocker.
It is a real measured defect in the same file, filed rather than folded in, and
the user may well want it before a deploy — but that is a decision to take, not
one Planner has taken.

- **CG-60 first.** Docs-only, no dependencies — and
  `docs/consumers/aitrader.md` currently tells that tenant's operator something
  **false about their own privacy posture**. A live-false claim in a consumer
  contract outranks preparatory work; CG-27 set that precedent by shipping
  exactly this kind of removal as its own item.
- **CG-53 next** because its unknowns are the largest *and* it carries the
  secret-redaction finding above. That finding should not wait behind two code
  PRs.
- **CG-54 before the deploy** because it is the **only hard prerequisite** for an
  always-on instance. `restart: unless-stopped` means the thing restarts by
  itself, and today every restart silently empties both queues. A trusted
  always-on service that loses work on restart is worse than a hand-run one that
  does, because nobody is watching. It is also fully offline-testable, so it
  costs no live time.
- **CG-58 after the deploy**, against the brief's order, because it needs no
  running instance to test — Google cannot be made to return 429 on demand either
  way, so a fake transport is the *only* way to exercise it.

**The deploy sits third rather than last on purpose: the soak clock starts
there**, so CG-59 harvests days of real uptime instead of beginning a wait.

**Nothing in this arc widens any tenant's inbound surface.** `aitrader` stays
`allow_inbound: false`; CG-57 **narrows** jobhunt's, per the user's decision.

**Previously: everything had shipped.** CG-1 through CG-13, CG-19 through CG-37,
CG-42 and CG-50 through CG-52 — 31 items on 2026-07-29/30, suite 37 → **202**.
PR #42 was open under a gate when the last banner was written and **has since
merged** (2026-07-31); its four rows stand as shipped.

**Three rows are closed rather than shipped**, each with its premise recorded so
"obsolete" is never a bare status word: **CG-14** (the migration removed the
failure mode its detector was designed for), and **CG-17 / CG-18** (user decision
2026-07-30 — both probe the add-ons runtime, which is deleted, so neither can be
run as written; see their rows for what was worth keeping).

✅ **The two gated IaC rows are done — and the collision this note predicted was
avoided by shipping them together.** CG-51 and CG-35 touched the same two setup
scripts, and CG-35 additionally needed explicit hard-rule-#3 sign-off to reword a
⚠ flag. The user granted that sign-off on exact terms and dispatched both in one
PR, so the predicted collision never happened. **The note is kept, not deleted:
its prediction was correct, and the next pair of rows touching one file pair
should be read the same way.**

> **CG-34 carried a merge gate its row did not declare.** The Coordinator imposed
> one at dispatch, on the ground that it is the **secret-handling path** — the same
> rule and the same credential that gated CG-23. Recorded because the gates in this
> queue are otherwise per-row, and a reader comparing the row to the history would
> otherwise find an unexplained pause. **A row without a declared gate is not a
> guarantee that none applies**; hard rule #2 territory pauses regardless.

**CG-21 shipped 2026-07-30 as documentation reconciliation only.** The migration
it names was executed and live-verified **2026-07-29**, outside any PR; the row
had no code in it. Its entry under **Recently shipped** records what the row's
future-tense body used to promise and which parts held — including the one that
did not: **rollback has expired**, because `chat-gateway-prod` was deleted.

**CG-9 was unblocked and shipped on 2026-07-30**, merged into CG-22's slot
because the two items land the same kind of artifact behind the same guard. Its
scope changed as well as its status — the capture that arrived is **classic**,
not add-ons, and the add-ons variant it originally asked for is now
uncapturable. See the combined entry under **Recently shipped**.

**CG-26 was filed 2026-07-30 by Planner** while planning the above: fixture
guard-coverage debt that no existing row owns. Appended last, not inserted —
the user sets priority.

**CG-23 and CG-24 were filed 2026-07-30 by Builder.** CG-23 is CG-7's review
fallout; CG-24 exists because the 2026-07-30 live session clears a flag that **no
existing queue item owns** — CG-4 is `webhook.py` and CG-5 is `chat_api.py`, so
`adapters/pubsub.py`'s module flag had no home. Neither is a re-plan: CG-23 is
one file's error text, CG-24 is a docstring whose evidence already exists.

**CG-11 was omitted from the user's 2026-07-30 priority list** — recorded here
rather than silently skipped or silently built. Builder treated it as genuinely
queued, because the wrong claim it existed to fix was live in `CLAUDE.md` and in
`docs/consumers/jobhunt.md` R6 on that date. It shipped 2026-07-30, combined
with CG-20.

---

### CG-14 · Interaction dead-man (`interaction-canary`)  ✖ CLOSED AS OBSOLETE · user decision 2026-07-30

**Never built. Nothing to remove.** Closed by user decision, and the reason is
recorded here rather than left as a status word, because "obsolete" without a
premise is indistinguishable from "we forgot".

**The premise the migration removed.** ADR-0001 §8 designed this detector for one
specific failure: silent breakage of **undocumented** routing. Under the add-ons
runtime a card reached the gateway only via the topic-as-function pattern, which
Google does not document. If Google withdrew it, no event would reach the topic,
no counter would move, no exception would be raised, and `/healthz` would report
`ok` indefinitely. A weekly dead-man cleared by any `CARD_CLICKED` was a
proportionate answer to an *invisible* failure.

**Production migrated to a classic Chat app, so that failure mode does not
exist.** Card clicks arrive by Google's own documented mechanism with
`action.id` populated natively. There is no undocumented dependency left to
break — ADR-0001's banner puts it as "not mitigated, *removed*". The detector
would now be watching for the disappearance of something that cannot disappear
the way it was designed to.

**And the residual value it might still have had is already delivered, more
precisely, by CG-7.** The weaker general question — *should the gateway alert when
inbound goes quiet?* — is answered better than a 7-day canary ever could:

| CG-14 would have caught | CG-7 catches it as | Latency |
|---|---|---|
| a dead subscription / revoked key / wrong subscription name / quota exhaustion | `N consecutive poll failures`, naming the HTTP status | ~15s |
| a polling thread that died | `the polling thread was started and is NOT RUNNING` | immediate |
| a thread alive but wedged | `seconds_since_last_poll` over budget | ≤ 5 min |

Every one of those is **more specific and 2000× faster** than "no interaction in
7 days", and none of them raises a false alarm on a genuinely quiet week — which
was the accepted-but-real cost of the canary design.

**What is genuinely NOT covered, stated so this closure is honest:** an app
removed from a space, or a producer that stops shipping interactive cards. Both
leave polling perfectly healthy and inbound legitimately silent. Neither is
currently detected. If that ever matters it is a **new** item with its own
justification — do not reopen this row, whose rationale was specific to a runtime
this project no longer deploys on.

<details>
<summary>Original blocked-item text, kept for the record</summary>

**Do not build this yet.** Its entire purpose was detecting *silent breakage of
undocumented routing*: if Google withdrew topic-as-function, no event would
reach the topic, no counter would move, and `/healthz` would report `ok`
forever. E1 passed, so the destination is a **classic** deployment, which has no
undocumented dependency to break. The failure mode the canary was designed for
does not exist there.

What is left is a weaker, more general question — *should the gateway alert when
inbound goes quiet for a week, whatever the cause?* That may still be worth
something (it would also catch a dead subscription, a revoked key, or an app
removed from a space), but it is a different feature with a different
justification, and the accepted false-positive cost was priced against the old
one. It also overlaps CG-7, which makes a *dead* subscriber visible immediately
and much more precisely.

**Planner/user call.** Either re-justify it as a general inbound-quietness
detector, or close it as obsoleted by E1 + CG-7. Builder should not decide this.

</details>

> **Markdown fix, 2026-07-30.** The `</details>` above used to sit ~350 lines
> lower, after CG-23 — so **seven live queued rows** (CG-12, CG-11, CG-20, CG-21,
> CG-22+CG-9, CG-19, CG-23) rendered *collapsed inside CG-14's "kept for the
> record" fold*, under a summary describing a closed item. On GitHub the queue
> appeared to contain nothing but a closed row, CG-25 and CG-26, which
> contradicted the order line at the top of this section. Content unchanged; only
> the closing tag moved.

---


### CG-35 · Two IaC leftovers CG-19 was forbidden to touch  ✅ shipped 2026-07-30 · [PR #42](https://github.com/mmackelprang/chat-gateway/pull/42) · ⏸ gate held

> **Shipped with CG-51 in one PR.** (a) landed on the user's exact sign-off terms
> — **the flag word dropped, the explanation kept, and the PR says in those words
> that this is removing a MISAPPLIED flag, not clearing a real one.** (b) landed
> as *"the `.sh` adopts basename"*: the row left that choice open, and the `.env`
> block being a **host** path settles it. Both re-measured here, not cited.

| | |
|---|---|
| **Origin** | filed by Builder 2026-07-30 from **CG-19** — both found while editing these files, both **measured** |
| **Depends on** | nothing (CG-19 shipped the sweep that surfaced them) |
| **Touches** | `iac/gcloud-setup.sh`, `iac/gcloud-setup.ps1` |
| **Merge gate** | **touches the IaC path — Builder must pause and report before merging** |
| **Priority** | **appended last, unprioritized.** The user sets order. |

Two defects in the files CG-19 owned. Neither was fixed there, and the reason is
the same in both cases: CG-19's scope was **comments and illustrative defaults
only**, and each of these needs something CG-19 was explicitly barred from doing.

**(a) The `⚠ LIVE-UNVERIFIED` comment now contradicts `CLAUDE.md`.**
`iac/gcloud-setup.sh:40` and `iac/gcloud-setup.ps1:93` say the Chat events
publisher *"stays ⚠ LIVE-UNVERIFIED until the principal is confirmed on the Chat
API Connection settings page"*. `CLAUDE.md` records that question as **CLOSED BY
CIRCUMSTANCE, not answered** — both principals were bound in `chat-gateway-prod`,
that project is deleted, so it *"is not a flag, not a gap to close, and not a
task"*. The IaC therefore still presents as open work something the project has
closed, under the one flag word hard rule #3 caps.

**Why CG-19 left it:** resolving it means clearing or rewording a `⚠` flag, and
CG-19 was told to clear, add and reword none. **This is a hard-rule-#3 change and
needs the user's explicit sign-off** — which is exactly why it is a row and not a
Builder fix.

**Do not "fix" it by deleting the comment.** `CLAUDE.md` notes the IaC binds
**both** principals *"and its comments explain why, so a fresh-project operator is
not stranded by this being closed"* — the explanation is load-bearing. What is
stale is the *pending-work framing*, not the content.

**(b) The `.sh` and `.ps1` diverge on an absolute `KEY_FILE`.** The two scripts
are meant to be siblings — the `.ps1`'s own header says *"same steps, same order,
same output"*. They are not, for one input:

| | Emits, for an absolute key path |
|---|---|
| `.ps1` | `GOOGLE_APPLICATION_CREDENTIALS=/srv/chat-gateway/<basename>` — it does `Split-Path -Leaf` |
| `.sh` | `GOOGLE_APPLICATION_CREDENTIALS=/srv/chat-gateway/C:/…/key.json` — it concatenates `${KEY_FILE}` raw |

**Measured, not derived from reading.** Both scripts were run end to end during
CG-19's UAT against a stubbed `gcloud` with an absolute `KEY_FILE`; the mangled
line is copied from the `.sh`'s real output.

Low severity on its own — the `.env` block is a convenience the operator edits
anyway — but it is a **parity** defect in a file pair whose entire contract is
parity, and CG-19's new comments actively encourage passing a per-project
`KEY_FILE`, which makes the input more likely, not less.

**Why CG-19 left it:** fixing it changes emitted output, i.e. behaviour, which
CG-19 forbade.

**Not prescribed here:** whether the `.sh` should adopt `basename` or the `.ps1`
should stop stripping. The `.ps1`'s behaviour looks more useful, but the `.env`
block is a **host** path, and the two scripts may reasonably differ on whether a
caller-supplied absolute path means *"the key is here now"* or *"the key will be
there on the host"*. Filed with the observation, not the answer.

---


### CG-50 · `pubsub.py`'s module docstring states CG-10's defect as current, and CG-10 shipped  ✅ shipped 2026-07-30 · [PR #42](https://github.com/mmackelprang/chat-gateway/pull/42)

> **Verified by running the fixture, as the row required, not by trusting it:**
> `action.id` is `None` and `id_source` is `None`. The **finding** is kept — the
> capture did find a defect rather than confirm the mapping; the **value** and the
> open-work pointer are what changed. The diff is confined to those three lines
> and both adjacent ⚠ SHAPE-VERIFIED blocks are untouched.

| | |
|---|---|
| **Origin** | filed by Builder 2026-07-30 from **CG-37's** sweep — **measured against the real fixture, not read** |
| **Depends on** | nothing |
| **Touches** | `src/chat_gateway/adapters/pubsub.py` — module docstring, comment only |
| **Priority** | **appended last, unprioritized.** The user sets order. |

**A third comment of exactly the family CG-37 was filed for, which CG-21's
inventory missed.** CG-37 corrected the two comments that named the wrong
*runtime*; this one names a *defect* that has since been fixed.
`adapters/pubsub.py:27-29` says:

> The interaction capture found a DEFECT rather than confirming the mapping: the
> real event yields `action.id == ""` (see `ADDON_ACTION_KEY` below and queue
> item CG-10).

**Both halves are stale.** CG-10 shipped, and what it shipped is precisely this:
`CLAUDE.md` records *"Unresolvable identity is `None`, never `""`"*. Measured
here by feeding that exact fixture — `tests/fixtures/addon-buttonclicked-event.json`
— through the real `normalize_event`: `action.id` is **`None`**, `id_source` is
`None`. So the docstring states a value the code no longer produces, and points
a reader at a queue item that is closed.

**Why CG-37 did not fix it.** Two reasons, and both are why this is a row rather
than a Builder fix. It is outside CG-37's declared scope — that row named exactly
two comments and the dispatch was explicit that a small accurate PR was the
wanted outcome. And it sits **between two ⚠ SHAPE-VERIFIED blocks** in the
module docstring, which is hard-rule-#3 territory: the sentence immediately above
it scopes the 2026-07-29 add-ons capture and the one below opens the 2026-07-30
classic block.

**Do not fix it by deleting the sentence.** What it records is still true and
still load-bearing — the add-ons capture *did* find a defect rather than confirm
the mapping, and *"Nothing about jobhunt R3/R4 is verified by it"* (the next line)
is unaffected either way. What is stale is the **value** and the **open-work
pointer**, not the finding. **No flag may be cleared, added or reworded**;
`jobhunt` R3/R4 remain unverified regardless.

---

### CG-51 · Derive `KEY_FILE` from `PROJECT_ID` in both setup scripts  ✅ shipped 2026-07-30 · [PR #42](https://github.com/mmackelprang/chat-gateway/pull/42) · ⏸ gate held

> **All three of the row's requirements were met and evidenced.** (1) The new
> emitted output is shown in the PR with a before/after table — CG-19's
> byte-identical proof was **not** reused. (2) The script does not silently mint:
> derived name absent + plausible predecessor present ⇒ refuse, name it, **exit
> 3**, with `ALLOW_SECOND_KEY=1` as the deliberate hatch. (3) `.sh`/`.ps1` parity
> is proven mechanically across **eight** scenarios rather than claimed — and the
> row's *"if the two rows collide, say so"* did not arise, because the user
> dispatched them as one PR.
>
> **One thing the row did not anticipate, recorded because it is the interesting
> half:** the guard is only as good as the directory it scans, so the `.sh` also
> had to start resolving a relative `KEY_FILE` against the script's own directory
> — which the `.ps1` has always done. That is a **behaviour change beyond the
> row's literal text**, and it is a no-op for the documented invocation.

| | |
|---|---|
| **Decision** | **user, 2026-07-30** — chosen over "leave it" and over hardcoding `chat-gateway-sa-gw.json` |
| **Origin** | CG-19 deliberately did NOT do this and asked; this row is the answer |
| **Touches** | `iac/gcloud-setup.sh`, `iac/gcloud-setup.ps1` — **emitted behaviour, not comments** |
| **Merge gate** | **touches the IaC / secret-handling path — pause and report before merging** |

CG-19's scope line told it to update the illustrative key filename. It **declined,
with evidence**, and the reasoning is why this is its own gated row rather than a
one-line diff: `iac/chat-gateway-sa.json` belongs to the **deleted**
`chat-gateway-prod` (confirmed by reading `project_id` out of the file), and the
scripts' existence check is **filename-only** — so the trap is real. But the live
key is `chat-gateway-sa-gw.json`, so *any* fixed new default stops matching on a
host holding the old one and **mints a second service-account key**. Key sprawl
is a worse outcome than a documented trap, which is why CG-19 documented it and
stopped.

**The decision: derive the filename from `PROJECT_ID`** so it can never name a
project that does not exist. That is the only option of the three that fixes the
trap without hardcoding a project-specific name into a parameterized script.

Three things this must get right:

1. **It changes emitted script behaviour.** CG-19 proved its own change inert by
   showing both scripts produce byte-identical output against a stubbed `gcloud`.
   **That proof cannot be reused here** — output *will* differ, deliberately. Show
   the new output and say what changed.
2. **Do not silently mint a key.** If the derived filename is absent but a
   plausible predecessor is present, the script should **say so** rather than
   quietly create a second credential. Recovery from a leaked webhook URL is
   delete-and-recreate by hand (§8a); extra SA keys are the same class of mess.
3. **`.sh` and `.ps1` must stay at parity.** CG-35 already records that they
   diverge on an absolute `KEY_FILE`; do not widen that gap. If the two rows
   collide, say so rather than half-fixing both.

Terraform is **not** in scope and cannot be validated here anyway — it is not
installed on this box and that path has never been applied.

---

### CG-52 · `integration-guide.md`'s *"retries span ~10s"* is the same defect one audience up  ✅ shipped 2026-07-30 · [PR #42](https://github.com/mmackelprang/chat-gateway/pull/42)

> **Shipped with ZERO figures carried up**, which is stricter than the row's
> *"qualify in a clause and point there"* and deliberately so: the row's own table
> was tempting to quote, and quoting even one number would have created the second
> thing to drift it warns about. `~10s` stays, re-labelled *"by contract"*. The
> paragraph was found by its text — **no line number recorded**, per the row — and
> it is the interaction paragraph, not the `/v1/notify` one CG-36 fixed. The
> anchor into jobhunt-handoff §7 was verified against GitHub's own rendering.

| | |
|---|---|
| **Origin** | filed by Builder 2026-07-30 from **CG-42's** sweep — reported, not fixed, because CG-36 owned the file at the time |
| **Depends on** | nothing (CG-36 and CG-42 both shipped; the file is free) |
| **Touches** | `docs/integration-guide.md` — the interaction rules-of-the-road paragraph, **not** the `/v1/notify` one CG-36 shipped |

The guide tells a producer *"if your callback is down, retries span ~10s and then
the gateway posts your unreachable message"*. **`~10s` is the contract, not what a
user waits** — exactly the confusion CG-42 corrected in the two jobhunt docs, one
audience up and in a different paragraph.

Measured on a real `SubscriberLoop` (CG-42, first-hand, four setups):

| How the callback fails | attempts land at |
|---|---|
| `process_due()` called freely | 0s / 3s / 10s — the contract |
| refuses fast (`ConnectError`, closed port) | 0.0 / 7.1 / 14.1, notice at **16.2s** |
| hangs to the production 10s client timeout | 0.0 / 15.0 / 30.1, notice at **40.1s** |

A producer sizing a timeout against `~10s` is wrong by **4×** in the case that
actually matters — exhaustion is the only route to the in-thread notice, and an
unreachable host times out rather than refusing.

**Link, do not restate.** `docs/consumers/jobhunt-handoff.md` §7 owns the measured
table and the rule that predicts it. This is a general-audience summary; qualify
the claim in a clause and point there, exactly as CG-36 did for the dedupe
counter. Reproducing the table here creates a second thing to drift.

⚠ **Do not record a line number.** It was 109, then 114 under CG-36's merge. Find
the paragraph by its text.

---

### CG-60 · Repo-wide correction of the one-space premise  ✅ shipped 2026-07-31 · [PR #44](https://github.com/mmackelprang/chat-gateway/pull/44) · ⏸ gate released

| | |
|---|---|
| **Origin** | user correction 2026-07-31, relayed via Coordinator. The `apps_for_space` consequence was **re-derived against the live registry**, not taken on description |
| **Depends on** | nothing |
| **Touches** | `docs/consumers/aitrader.md` (**highest priority**), `docs/google-cloud-setup.md`, `docs/integration-guide.md`, `docs/consumers/jobhunt.md`, `docs/consumers/jobhunt-handoff.md`, **`docs/assets/README.md`** (added by Builder — the re-derivation found it; the list was not exhaustive, which is the point of H0), `CLAUDE.md` + `adapters/chat_api.py` (**a dated note only** — see below), `docs/BUILDER_QUEUE.md` |
| **Merge gate** | ⏸ **YES — consumer contracts, and it works in the ledger's neighbourhood** |
| **Spec / plan** | [spec §0.1 + §4.0](superpowers/specs/2026-07-31-production-readiness-arc-design.md) · [plan Part H](superpowers/plans/2026-07-31-production-readiness-arc.md) |

**The corrected facts — a dated user statement about the Google Chat console,
not something this repo can prove or has measured.** The classic app **"Agent
Comms" is DEPRECATED** (it was workspace-specific) and is replaced by an app
named **"Chat Gateway"** — same functionality, better interaction support — which
participates in **four** spaces: FamilyWorkspace, Ai Trader, Ai Trader Reports
and JobHunt. So *"Tier 2 is live in the JobHunt space ONLY"* is **false**, along
with every repo claim resting on it.

**The consequence, and this half IS measured** — re-derived by running the real
`apps_for_space` against the **live** (gitignored) `config/registry.yaml`,
reported without reproducing any space id: **four distinct spaces are
configured, every one with `space:` already filled.** Two resolve to
`['aitrader']` with `allow_inbound: false`; one to `['job-hunter']`; one to
`['aiteam-harness']`.

**So every event in either Ai Trader space now increments `suppressed_opt_out`
on an unauthenticated `/healthz`.** Hard rule #6 holds absolutely — the
`continue` fires before any `inbox.put`, nothing crosses to aitrader — but
CG-12's recorded caveat, *"a de-facto unauthenticated activity meter for that
tenant by inference"*, is now a **live property of the deployment**.

**`docs/consumers/aitrader.md` predicted this exact trigger:** *"the safeguard is
one step away, not two … adding the Chat app to an aitrader space would be
sufficient on its own, and it is a console action that leaves no trace in version
control."* **The prediction fired.** So this row's job is to convert a documented
*prediction* into a documented *live state* — tense change plus the dated fact —
which is a stronger edit than a deletion and **vindicates the file. Do not delete
the prediction paragraph**; it named the trigger, and leaving it visible is what
makes the next warning believable.

⚠ **A second consequence, not in the correction brief, found by the same
re-derivation.** The FamilyWorkspace space resolves to `['aiteam-harness']` with
`allow_inbound: **true**` and **no `allowed_users`**. `dispatch()` filters on
space ownership, opt-in and allowlist — **never on event type** — so events there
are now **enqueued and written to the JSONL audit**, with no sender restriction
and no evidence anyone drains that inbox. An undrained inbox fills to
`max_pending: 1000` and silently drops its oldest; **CG-54 makes that content
persist across restarts rather than vanish.** *Which* events Google actually
sends is **not knowable from this repo** — a classic app in a room conventionally
sees a MESSAGE only when @mentioned — so it is the highest-value observation on
CG-55's first drain, and it is a **privacy** question, not just an operational
one. Do not guess it here.

⚠ **The historical observations are CORRECT and must not be rewritten.**
`CLAUDE.md`'s ledger row recording `sender: {displayName: "Agent Comms"}`, and
the identical sentences in `adapters/chat_api.py`, are accurate observations of
**2026-07-29**. They are evidence, not claims about today. **No ⚠ flag may be
cleared, added or reworded** — that needs the user's explicit sign-off naming
hard rule #3, which this row does **not** have. Add a **dated note adjacent to**
the observation that the app has since been replaced, leaving the observation
intact. **This is the CG-50 shape exactly:** the finding is kept, the currency
pointer is what changes, and the diff stays confined between untouched flag
blocks.

**Find the claims by TEXT, not by line number** (CG-52's rule), and **re-derive
rather than trusting any list** — including the one in the plan. In
`docs/BUILDER_QUEUE.md`, **judge claims vs records**: shipped rows are history
and stay.

**This also re-priced what became decision D2** (`/healthz` on an allow-all
tailnet). It is no longer app-id enumeration — it is another tenant's live
traffic volume and timing, on a real-money system whose whole contract is that it
takes no inbound path. See the spec; the recommendation there **changed** as a
result.

---

### CG-62 · Does replacing the Chat app re-price the verification ledger?  📋 queued · **needs user sign-off**

| | |
|---|---|
| **Origin** | **filed by CG-60's Builder, 2026-07-31**, from a question CG-60 raised and deliberately did not answer |
| **Depends on** | nothing in code. Depends on a **user decision** |
| **Touches** | potentially `CLAUDE.md`'s verification ledger and `adapters/chat_api.py`'s ⚠ blocks — **nothing until the decision exists** |
| **Merge gate** | ⏸ **YES** — hard rule #3, the CG-35 precedent |

**The question, stated once and not answered here.** Every ⚠ flag this repo has
cleared against Google was cleared through the classic Chat app then named
**"Agent Comms"** — `send()` and `send_text()` on 2026-07-29/30, `PubSubPuller`'s
`pull()`/`acknowledge()` on 2026-07-30. That app is now **deprecated**, replaced
by one named **"Chat Gateway"** (user statement about the console, 2026-07-31).
**Does a clear obtained through the old app still hold for the new one?**

**Why CG-60 refused to decide it, rather than merely running out of scope.**
Hard rule #3 says a flag clears *only* after a real round-trip, and CG-35(a) set
the precedent that even removing a **misapplied** flag needed the user's explicit
sign-off on exact terms. Answering this either way *is* a flag decision:

- If the answer is *"the clears still hold"*, that is an assertion that the two
  apps are equivalent for these code paths — which this repo **cannot observe**.
  Nothing in the console is readable from here, including whether "Chat Gateway"
  is a new Chat app resource on the same project or a rename of the same one.
  Those two possibilities have **different** answers and the difference is not
  derivable from any file in this repo.
- If the answer is *"they need re-verification"*, that **adds** flags — equally
  out of a Builder's authority, and it would land on `adapters/` mid-arc.

So CG-60 shipped the **naming notes** (currency pointers beside untouched
observations, the CG-50 shape) and left every flag exactly where it found it.
The notes in `CLAUDE.md` and `adapters/chat_api.py` both say in terms that they
decide nothing and point here.

⚠ **This row must NOT be picked up by a Builder without the user's sign-off
naming hard rule #3.** It is filed so the question is visible and dated, not so
it gets cleared by whoever reaches it. **A tenable third answer** — that a
display-name change is cosmetic and touches no verified code path, since nothing
in this repo reads `displayName` — is the *likely* one and is **still a user
call**, because "likely" is the exact word rule #3 exists to refuse.

---

### CG-61 · Close `aiteam-harness`'s inbound path  ✅ merged ([#50](https://github.com/mmackelprang/chat-gateway/pull/50), `dced002`) · ⏸ **OPERATOR ACTION OUTSTANDING** · **BEFORE CG-55**

| | |
|---|---|
| **Decision** | **user, 2026-07-31 (D1)** — from Planner's finding while correcting the four-spaces premise |
| **Depends on** | nothing. **CG-55 depends on THIS** being in the live registry |
| **Touches** | `config/registry.example.yaml`, `CLAUDE.md` (consumer list), one new test. ⚠ the **live** `config/registry.yaml` is gitignored — an operator action, recorded |
| **Merge gate** | ⏸ **YES — a live-config change narrowing a tenant's inbound surface** (hard rule #6 territory) |
| **Spec / plan** | [spec §4.0b + §7 D1](superpowers/specs/2026-07-31-production-readiness-arc-design.md) · [plan Part I](superpowers/plans/2026-07-31-production-readiness-arc.md) |

Set `allow_inbound: false` on `aiteam-harness`.

**Why: inbound was on ONLY because `true` is the default** — `registry.py` reads
`allow_inbound=bool(spec.get("allow_inbound", True))`. That app has no
`callback_url`, no `allowed_users`, and `CLAUDE.md` describes it as a `notify.py`
**outbound** transport. **It never asked for inbound.** Hard rule #6 is
default-deny in spirit; this makes it so in fact.

**The benefit is verified, not assumed.** `dispatch()` discards an opted-out
owner's event **entirely**: the `or [UNROUTED]` fallback **cannot** fire, because
it only triggers for a space with **no** owner and this space has one. So
**nothing reaches the inbox, nothing reaches `_unrouted`, nothing reaches disk** —
only the counter moves. FamilyWorkspace content therefore never lands in a JSONL
audit file. (Read the comment at that `continue` in `adapters/pubsub.py`; it is
the same gap CG-12 was filed for.)

⚠ **A DEFAULT CORRECTED, NOT A VERDICT** about that consumer, and **reversible in
one registry line** if aiteam ever wants inbound. The row must say so in those
words — otherwise a future reader mistakes a default for a judgement.

**Why its own row rather than folded into CG-60.** CG-60 is a **documentation
correction with no behaviour change**; this **changes behaviour**. This repo has
an established split for exactly that pair: **CG-19** was scoped
comments-and-defaults-only and *explicitly declined* to change emitted behaviour,
filing that as **CG-51** with its own gate. Mixing them makes the docs PR
unreviewable as docs and buries a live-config change in a prose sweep. The gates
differ too, and this row carries a sequencing constraint CG-60 does not.

⚠ **The live registry is gitignored, so a PR cannot change it.** Verified
2026-07-31: it still reads `allow_inbound=True`, so this is a real edit, not a
no-op. **CG-55 streams that file to the NAS** — if this has not landed there
first, the deployed gateway runs with inbound open and the first drain writes
that content to disk. CG-55 carries a **fail-closed pre-flight** asserting the
opt-in map rather than trusting anyone to remember.

**Collision note:** CG-57 also edits `config/registry.example.yaml` (removing
`job-hunter`'s `callback_url`). Independent in content, sequential in time —
CG-61 before CG-55, CG-57 after — so the queue's standing two-rows-one-file
warning does not bite. Recorded so a reader need not re-derive it.

**Ships a test** pinning that an opted-out owner's event reaches neither the
app's inbox nor `_unrouted` nor disk, so a refactor cannot quietly undo it.

**Builder, 2026-07-31 — [PR #50](https://github.com/mmackelprang/chat-gateway/pull/50)
MERGED as `dced002`** (written pre-merge as *"open at the gate"*; the gate was
released by the user and the tense is corrected here, not the content). Two notes,
and the second is why this row is **not** closed:

- **The pre-state was re-measured, not copied from this row.** The real
  `load_registry` against the real live file returns `aiteam-harness
  allow_inbound=True` today, and the key is **absent** — so the default is what
  granted inbound, exactly as D1 argues. This row's ⚠ paragraph above was right.
- ⚠ **Merging is not finishing.** The PR changes `registry.example.yaml`; the
  live edit is the operator action, and it **falsifies a dated "not yet" in two
  files** — `CLAUDE.md`'s CG-12 bullet and `adapters/pubsub.py`'s counter
  comment, each of which now names the other so neither is missed. The plan's
  I3 sketch was also one disk surface short (it predates #45's journal); the
  shipped test asserts **both**, and a mutation that wrote only the journal was
  used to prove that half bites.

---

### CG-53 · Deployment artifacts and the secret-safety proof (**no deploy**)  📋 queued · ✅ **plan refreshed 2026-08-03 — DISPATCHABLE**

| | |
|---|---|
| **Origin** | Planner 2026-07-31, from the production-readiness brief — **surveyed against the homelab repo, not assumed** |
| **Depends on** | nothing |
| **Touches** | `src/chat_gateway/env_file.py` (new), `__main__.py`, `.env.example`, `docker-compose.yml` (header + one comment), `docs/deploy/nas.md` (new) |
| **Merge gate** | ⏸ **YES — secret-handling path, IaC-adjacent.** The gate CG-23, CG-33, CG-34 and CG-51 carried |
| **Spec / plan** | [spec §4.1](superpowers/specs/2026-07-31-production-readiness-arc-design.md) · [plan Part A](superpowers/plans/2026-07-31-production-readiness-arc.md) |

**Ships no deploy.** It ships the artifacts, the on-box layout, one small code
change that makes hard rule #2 hold on the NAS, and a runbook.

**The finding that makes this row first, and gated.** The homelab capture script
decides a key is secret by **upper-cased suffix match** — `…PASSWORD`, `…TOKEN`,
`…API_KEY`, `…CREDENTIALS` and a handful more. Match that against this project's
env-var shapes:

| Env var | Ends with | Redacted? |
|---|---|---|
| `CHAT_GATEWAY_API_KEY__<APP>` | the app id | ❌ **NO** |
| `GOOGLE_CHAT_WEBHOOK_URL__<IDENTITY>` | the identity name | ❌ **NO** |
| `GOOGLE_APPLICATION_CREDENTIALS` | `CREDENTIALS` | ✅ yes — and it is only a path |

The `__<SUFFIX>` convention this project uses to get one env var per app and per
identity **defeats the suffix rule**, and it does so on exactly the two families
that are real credentials. A webhook URL embeds `key`+`token`, *is* a bearer
credential, and has **no rotate-in-place** — recovery is delete-and-recreate by
hand (`docs/google-cloud-setup.md` §8a), and this project already burned every
webhook it owns once, on 2026-07-29, for a smaller mistake.

✅ **RE-MEASURED 2026-08-03 — the premise HOLDS.** This is the single load-bearing
fact in the row and **it lives in a file this project does not control**
(`/mnt/d/prj/homelab`, read-only) — the "external world" category CG-69 classifies
as watchable by no guard here — so it is re-run, not re-quoted. Through that
repo's **real** `is_secret_key`: all seven credential vars miss;
`GOOGLE_APPLICATION_CREDENTIALS` is the only catch and it is a path. End to end
through the **real** redactor and the **real** scan gate, a payload carrying a
live-shaped API key and webhook URL came back **with both values intact and the
gate exited 0** — while a `POSTGRES_PASSWORD` control in the same payload was
redacted, which is what makes that green console line persuasive rather than
merely wrong. ⚠ The file **was edited on 2026-08-03**, but `SECRET_KEY_SUFFIXES`
itself was untouched (18 entries, unchanged since before 2026-07-31); the commit
added *reference* exemptions. **The direction of travel is toward more exemptions,
not more catches.**

⚠ **One correction to the sentence above, and it kills the cheap fix.** *"Exactly
the two families"* is right that both leak, but **the two leak for different
reasons and only one is the convention's doing**: bare `CHAT_GATEWAY_API_KEY`
**is** caught, so `__<APP>` is what defeats it there — but bare
`GOOGLE_CHAT_WEBHOOK_URL` is **missed anyway**, because the list has no `URL`
entry (only `DATABASE_URL`). So *"rename the vars so the rule catches them"*
would fix the API keys and do **nothing** for the webhook URLs — the
higher-value secret, the one with no rotate-in-place. No value-based rule saves
it either: the URL-credential regex wants `scheme://user:pass@host`, and a
webhook carries `key`/`token` as **query parameters**. Structural containment is
not the convenient answer; it is the only one.

⚠ **And the capture is not opt-in.** That script derives its app set live from
`app.query` filtered on `custom_app`, so `nas/compose/chat-gateway.config.json`
appears **automatically** on the first capture after the app exists. Nobody
chooses to capture the gateway; the leak would be a default.

So the house-style deploy (inline `environment:`, then `capture.sh`) ends with
**every API key and every webhook URL committed in plaintext to a sibling repo,
under a script that printed `clean. safe to commit.`** That is the CG-23 / CG-34
defect class, one repo over.

**The answer is structural, not a reminder.** Secrets never enter the compose
document at all: `__main__` gains `CHAT_GATEWAY_ENV_FILE`, naming an off-repo
file (mode 600) that the compose only *points at*. The capture is then clean **by
construction** and the redactor's suffix list stops being load-bearing for us.

⚠ **The fix belongs in our code, not in compose's `env_file:`.** No homelab
service uses `env_file`, and whether the TrueNAS renderer honours it is
unverified. **Do not put a hard-rule-#2 guarantee on an unverified property of
someone else's compose renderer.**

Four properties the loader must have, each with a reason: **the environment wins**
over the file (an operator's override is never silently replaced, and it makes
this a no-op in all **345** existing tests — `202` until 2026-08-03, and the
count belongs to the suite, not to this row); **no new dependency** (~20 lines);
**a missing file is fatal** — a gateway that boots with no credentials answers
`degraded` on an *unauthenticated* endpoint and otherwise looks alive, which is
the shape rule #5 exists for; and **values are never logged**, only a count.

✅ **All four re-tested 2026-08-03 against the codebase they did not grow up in**
(CG-72/74/75/76 built the `/healthz` degrade machinery after they were written).
**All four survive.** The *"missing file is fatal"* justification comes back
**stronger and for a different reason**: the channel built to notice silence is
the dead-man switch, and it reports by *sending a Chat message* — exactly what a
credential-less gateway cannot do. Booting degraded would be invisible in the one
place designed to catch invisibility, which is CG-76's finding applied to
startup. Second-order effect now recorded rather than left to be discovered: under
`restart: unless-stopped` a fatal config error is a **crash loop** — cheap (the
process dies before the dispatcher exists, so **no** Google traffic) but it makes
`docker logs` the first diagnostic, not `/healthz`.

⚠ **"Environment wins" turned out to be load-bearing on the box, not just in
tests — and it does NOT cover everything.** The `.env` transferred to the NAS is
the dev box's, so the compose's three container paths correctly override its
stale relative ones. **Two keys are not in the compose and so are not saved by
it:** `GATEWAY_ENABLE_PUBSUB` (dev default `0` → inbound silently **off**) and
`GOOGLE_APPLICATION_CREDENTIALS` (dev path → **boots clean, fails every tier-2
call**, because `GoogleServiceAccountTokens.__init__` only stores the path and
nothing stats the credential file, so `/healthz` cannot see it). The plan now
declares the flag in the compose so the first fails **closed**, and carries an
explicit in-container check for the second.

**Also settled here, and each one is a correction to the brief:**

- **There is no `nas/compose/<service>.yaml` to write.** NAS services are TrueNAS
  **custom apps** created via the middleware API with an inline
  `custom_compose_config`, and *then* captured to
  `nas/compose/<name>.config.json`. **`docker-compose.yml` cannot deploy as
  written** — `build:` has no build context there, relative mounts have no
  meaning, and `env_file` is used by no service in that repo. It is **not
  deleted**; it is scoped as the dev-box path, which is what `build:` is for.
- **`SECRETS.md` is gitignored and holds real values.** The tracked pointer file
  is `SECRETS.template.md`. That is the one a PR adds a row to.
- **The SA key filename is deliberately NOT pinned** in the compose or the
  runbook. CG-51 made the setup scripts *derive* it from `PROJECT_ID`; a filename
  in a comment is exactly what CG-19 found stale. Mount the `secrets/`
  **directory**; `docs/google-cloud-setup.md` records the name.
  **`iac/chat-gateway-sa.json` is DEAD** — deleted project.
- **Port `8085` is free — measured** 2026-07-31, not read from the homelab docs
  (whose implied set was incomplete). In use: `22 53 80 139 443 445 3000 5357
  5800 6000 6999 8081 8090 8098 30013 30014 31067 32014 32015 32016 37877 41175
  62716`. The app name `chat-gateway` is free too (`app.query` → `[]`) — **re-run
  that fail-closed check at deploy time rather than trusting it from here.**
- ⚠ **The NAS is NOT "backup target only", and this is NOT a role change.** That
  came from another project's *pipeline-scoped* table and is **withdrawn**;
  any "blast radius of making the NAS an app host" framing goes with it.
  Measured: **10 app stacks / 15 containers** already run there, including
  claude-mem's Postgres. The real question is what a **tenth stack** costs, and
  it is answerable: **20.8 GB RAM available of 31.9 GB, load 0.29 on 16 cores,
  `datapool` 1% of 13 TB.** A small Python service is noise.
- ⚠ **ZERO swap — the one real finding.** A memory spike is an OOM kill on a box
  hosting someone else's Postgres, so the compose should declare a `mem_limit`.
  That is a **deliberate deviation from house style** — measured, no existing
  *custom* app sets one (the 4 GiB caps on jellyfin/calibre/calibre-web/tailscale
  are TrueNAS's own, on *catalog* apps). ✅ **Decided: set one (D6)** — recorded as
  a deliberate deviation, not adopted silently; verify the renderer honours it — a limit believed present but
  silently dropped is worse than none.
- **Tailnet exposure needs NO extra plumbing, and that was measured rather than
  assumed.** `ix-tailscale-tailscale-1` is a *container*, which looked like it
  would need a subnet router / userspace proxy / sidecar / `serve` — but it runs
  `network_mode: host` with `/dev/net/tun`, `CAP_NET_ADMIN` and
  `TS_USERSPACE=false`, and **`tailscale0` is a real host interface**. Publishing
  `8085` on `0.0.0.0` is tailnet-reachable, full stop. ⚠ **Record the dependency
  in Gotchas:** that reachability is a property of *another app's* config — flip
  it to userspace mode and `tailscale0` vanishes from the host, taking every
  service's tailnet reachability with it, with nothing in our config to show why.
  ⚠ **The measurement stands; its CONSEQUENCE inverted on 2026-08-03.** Being
  reachable on every interface is now the thing to avoid, not the free win:
  **CG-55 binds the LAN address**, so this port is deliberately **not**
  tailnet-reachable, and the D2 ACL that would have fenced it is **deferred**.
  One home for both halves — `docs/BUILDER_QUEUE.md` § CG-55, *"Two user
  decisions, 2026-08-03"*. **CG-53 does not implement either**; it must only stop
  asserting the old posture, which is what the Part A refresh did to the runbook's
  Gotchas and the dev compose header.
  `tailscale` is **not** on the host PATH, so inspecting it means `docker exec`
  into another stack — which the plan's standing rules make a 🛑.

**State plainly in `docs/deploy/nas.md` what per-app keys do and do not protect.**
They protect every `/v1/*` endpoint (hard rule #4). They do **not** protect
`/healthz`, which is **unauthenticated by design** — CG-12's bare-counter decision
rests on that — and which enumerates app ids, identity names, per-identity mode,
env-var resolvability and every counter to anyone who can reach the port. And the
homelab's **restricting tailnet ACL is drafted but NOT applied** (recorded there
2026-07-28), so the live policy is default allow-all today. Neither is a blocker;
both belong in Gotchas so the exposure is a decision rather than a discovery.

⚠ **Two things to verify on the box, not assume** — recorded in the runbook as
decision points so they are not discovered live: that the middleware accepts a
locally-built image with `pull_policy: missing` (every existing custom app pulls a
public image, so this is first-of-its-kind there), and that the nested registry
path resolves under the read-only `/config` mount.

**Terraform is not in scope** and cannot be validated here — not installed, never
applied. Same scope call CG-51 made.

#### ✅ Plan Part A refreshed 2026-08-03 — the drift, found before a Builder hit it

Part A was written 2026-07-31; **eight PRs merged before it was dispatched.**
Nothing was built (`env_file.py` and `docs/deploy/` still do not exist), so every
correction below is to the plan, not to code. **Two of these would have failed at
runtime, not at review.**

| # | Drift | Severity |
|---|---|---|
| 1 | **A2's `build_runtime()` unpack is a 5-tuple; it is now SIX** (CG-68 added `sweeper`). Retyping the plan's line drops it and `serve` dies at `sweeper.sweep()`. A2 now edits the `except` clause **only** | ⚠ would break |
| 2 | **§5's compose could not have booted.** `CHAT_GATEWAY_REGISTRY=/config/registry.yaml` with the `config` dir mounted at `/config/config` → file at `/config/config/registry.yaml` → `RegistryError`, exit 2. Filed as *"verify it resolves"* when it was a thing to **fix**. `.env` now has its own mount point; nothing nests | ⚠ would break |
| 3 | **The dev `.env` is not usable verbatim** — see the two-key table above. Part A said "scp `.env`" as though it were | ⚠ silent |
| 4 | **§7 said "Run `capture.sh`" — that contradicts this plan's own standing rules**, where it is a 🛑 (it rewrites all ten stacks' files). Part C already had it right. Now: request the run, read the output | process |
| 5 | **§8 carried D2 as decided-and-gating** (*"the ACL lands BEFORE this is deployed"*). **Deferred by the user 2026-08-03.** Corrected, with the LAN bind named as the replacing half | expired |
| 6 | **§3's state tree was missing `quarantine/` and the retention sweep** (CG-65, CG-68). Now names **four** locations holding tenant bodies, which are swept and which never are | stale |
| 7 | **CG-70's runbook line was absent** — that row's 2026-08-02 decision routes option (b) here explicitly. Folded into §3, with the disjoint-sets reasoning and ⚠ **it does not close CG-70** | owed |
| 8 | **The split's justification was FALSE.** *"Matches both repos' conventions"* — measured, it matches neither: no `nas/services/*.md` links out of that repo, and `docs/consumers/*-handoff.md` names one file here. Decision unchanged, honesty restored | false claim |
| 9 | **`202` → 345**, and A7 now says take it from the suite | stale |
| 10 | **§8 said durability arrives "once Part B lands."** Part B landed as CG-54 (#45) | stale |

**Also recorded, not fixed here:** Part C's C0 says *"the custom-app JSON
**below**"* — that JSON is **above**, in Part A. Left for CG-55's Builder rather
than edited, since that note is CG-55's. And `CLAUDE.md`'s final bullet still
names `/srv/chat-gateway/` **on the appserver** as the deploy target, which the
whole arc contradicts — untouched here because a Builder holds that file.

**Deliberately NOT changed:** `"ports": ["8085:8085"]` in §5 stays the `0.0.0.0`
form. It is **CG-55's** to change and is already recorded in that row.

#### ⏸ What releasing the merge gate approves — so the decision is a real one

**None of it is a deploy.** This row creates nothing on the NAS, touches no live
registry, and clears/adds/rewords **no ⚠ verification flag**. Four things:

1. **A new code path that reads a file into the process environment at startup** —
   the first mechanism here whose *purpose* is to move credentials. Bounded by the
   four properties, each with a test.
2. **The judgement that this guarantee belongs in our code, not compose's
   `env_file:`** — i.e. that a hard-rule-#2 guarantee must not rest on an
   unverified property of a third-party renderer, at the price of ~20 lines this
   repo maintains forever.
3. **Publishing an on-box layout in a public repo** — paths, modes, and which four
   directories hold tenant message bodies. **Env-var NAMES and paths only**; no
   values, no hostnames, no key filenames.
4. **The accepted residual:** `/healthz` stays unauthenticated and, after CG-55's
   LAN bind, is reachable by anyone on the home LAN. The tailnet ACL is deferred.

**Not approved by releasing it:** the deploy (CG-55, separately gated), the
live-registry edit (CG-61), or the homelab-repo artifacts.

---

### CG-54 · Queue **and inbox** durability — append-only JSONL under `CHAT_GATEWAY_STATE_DIR`  ✅ done (#45)

| | |
|---|---|
| **Decision** | **user, 2026-07-31** — JSONL matching the existing delivery log; one persistence idiom, no new dependency, operator-readable during an incident |
| **Depends on** | nothing (ships before the deploy on purpose — see below) |
| **Touches** | `journal.py` (new), `delivery.py`, `inbox.py`, `__main__.py`, `service.py` (`/healthz`) |
| **Merge gate** | no |
| **Spec / plan** | [spec §4.2](superpowers/specs/2026-07-31-production-readiness-arc-design.md) · [plan Part B](superpowers/plans/2026-07-31-production-readiness-arc.md) |

`delivery.py:10` — *"a gateway restart drops undelivered jobs"* — accepted for
v0, and volume plus restarts is when it stops being acceptable.

**⚠ The brief scoped this to `delivery.py`. That scope is too narrow, and the
correction is the point of the row.** `inbox.py:22` holds its pending replies in a
`defaultdict(deque)` — **in memory too**. Under push, an inbound tap left the
gateway within ~10s. Under **decision A** it becomes jobhunt's *only* inbound
path, polled by a consumer **whose host sleeps**, so a tap can sit in that deque
for hours — and a restart in that window drops it. The JSONL audit keeps a copy
but nothing reads it back; recovery is an operator reading newline-delimited JSON
by hand. **Decision A points jobhunt's only inbound path at an in-memory queue**,
so durability must cover `Inbox` as well as `Dispatcher`.

**Why this ships before the deploy.** `restart: unless-stopped` means the thing
restarts by itself, and a NAS-resident always-on service is *trusted* in a way a
hand-run one is not. It is fully offline-testable, so it costs no live time.

**Reuse the idiom, do not invent a third.** `heartbeat.py` already persists JSON
atomically (`.tmp` + `os.replace`) and `delivery.py`/`inbox.py` already append
JSONL. One new module applies both primitives to queue *state*.

**Not the audit trail, and not a replacement for it.** The audit files are
per-app-per-day, never pruned, and carry **no terminal records** — they say what
ARRIVED, never what LEFT, so pending state cannot be reconstructed from them.
Different question, different file; both stay. Say this in the module docstring,
because "we already write JSONL" is the obvious wrong conclusion.

**The replay-on-boot rule — settled here, not left to Builder:**

- **Replayed:** every id with an `open` and no `close`, **attempt count
  preserved**. Not a detail: without it a crash-loop resets the backoff ladder
  every boot and hammers Google forever — **a durability feature turned into an
  outage amplifier**.
- **Discarded:** every id with a `close`, whatever its status.
- **Mid-flight at kill time** — an `open` with no `close` whose request may or may
  not have reached Google — is **replayed, and may therefore deliver twice.**
  Stated, not hidden: Chat has no idempotency key, notify dedupe collapses
  repeats within its window, and losing an alert is the worse failure.
- **Older than `REPLAY_MAX_AGE_S` (24h) is closed as `expired` at boot** — not
  silently dropped, not blindly sent. An alert from three days ago posted now
  actively misleads; both outcomes are bad and this is the visible one.
- **A torn trailing line is skipped and counted, never fatal.** A partial write at
  power loss is the *expected* shape, and **a gateway that refuses to boot over a
  half-written byte is a crash loop** on a host running `restart: unless-stopped`.
  The count goes to `/healthz` — and it adds a `reasons` entry, because a
  mechanism whose whole purpose is surviving something nobody watched must say
  when it lost something (rule #5).

**Compaction — settled:** on boot after replay (the only time the file is read,
so this suffices for correctness), **plus** an inline threshold, because the
deployed process is meant to run for weeks and **boot-only compaction on a process
that never boots is no compaction at all**. Atomic, via the heartbeat idiom.

**Both journals are optional constructor arguments defaulting to `None`**, so
every existing offline test constructs an unchanged in-memory object and the
202-test suite does not need rewriting to accommodate persistence.

**Re-resolve identities from the registry on replay, never from the journal.**
The journal stores an identity *name*; only the registry knows whether that app
may still send as it (hard rule #4). A job whose grant has since been withdrawn is
closed as `unroutable` — **never sent on the strength of a permission the registry
no longer grants.**

**UAT must include a real restart**, not only unit tests: SIGKILL a serving
gateway with work queued, read the journal by eye (it must be readable during an
incident — that is half the reason for the format), restart, and confirm
`/healthz` agrees with the boot line.

**Shipped 2026-07-31 (#45).** `journal.py` (new) + both queues + `/healthz`.
202 → **246 tests**. The UAT above was performed as written: a real
`python -m chat_gateway serve` was SIGKILLed with three jobs queued, the journal
was read by eye, and the restarted process reported
`queue: restored 3 outbound job(s), 0 expired or unroutable` with `/healthz`
agreeing (`replayed_at_boot: 3`). The torn-line, expired and unroutable paths
were each exercised against a serving process too, and each produced `degraded`
with a `reasons` entry rather than a silent number.

**Three deviations from the plan, all deliberate and all in the PR body:**
`Journal.close_many()` (a per-id close loop could lose a SUBSET of one poll on a
crash — the one outcome this row exists to prevent); `_journal_write()` guards
that swallow-and-count on terminal paths (a `close` that RAISED inside `_finish`
would leave the job queued and the 1s loop would re-send it every second — a
full disk becoming a re-send storm against Google); and `expired` vs
`unroutable` counted separately, because they are different investigations.

⚠ **`CLAUDE.md` and `docs/integration-guide.md` were deliberately NOT
updated** — they are CG-60's files and CG-60 was running concurrently. Both now
carry claims this row falsified. Filed as **CG-64**.

---

### CG-64 · Stale durability claims left behind by CG-54  ✅ done (#46)

| | |
|---|---|
| **Origin** | filed by CG-54's Builder, 2026-07-31, rather than raced |
| **Depends on** | **CG-60** — same two files, and CG-60 is the larger rewrite |
| **Touches** | `CLAUDE.md`, `docs/integration-guide.md` |
| **Merge gate** | no |

CG-54 made both queues durable. Two documents still describe the system it
replaced, and **CG-54's Builder did not fix them because both files belong to
CG-60, which was running concurrently** — racing a doc rewrite to correct three
sentences is how a merge conflict eats a careful edit.

1. `CLAUDE.md`, status bullet: *"Queue is in-memory (restart drops undelivered
   jobs — visible in the log; accepted v0)"*. **False as of #45.** Undelivered
   jobs are journalled under `CHAT_GATEWAY_STATE_DIR/queue/` and replayed at
   boot, with the attempt count preserved.
2. `CLAUDE.md`, Layout: the test count reads `202 passing`; it is **246**. That
   line is deliberately the ONLY place the number lives, which is exactly why a
   stale copy of it there is worth one line of work.
3. `docs/integration-guide.md`, `GET /v1/inbox`: *"Polling returns and clears
   your app's replies… a JSONL audit keeps everything."* This is the
   audit-versus-queue conflation CG-54 exists to correct — the audit says what
   ARRIVED, the journal says what is still PENDING, and a consumer reading only
   this sentence cannot tell whether a gateway restart drops their unpolled
   replies. It no longer does; say so.
4. `docs/integration-guide.md`, the `/healthz` field list gains seven entries:
   `delivery.{replayed_at_boot, expired_at_boot, unroutable_at_boot,
   journal_skipped_lines, journal_write_errors}` and
   `inbox.{replayed_at_boot, unrevivable_at_boot}`. **Four** of them can make
   `/healthz` report `degraded`, so a consumer that alarms on `status` should
   know what they mean.

⚠ **Do not restate the verification ledger while in `CLAUDE.md`** — nothing
here clears, adds or rewords a ⚠ flag. CG-54 touched no Google seam.

**Shipped 2026-07-31 (#46).** All four corrections landed, plus the CG-60 row
and header paragraph this row's own dependency left stale.

⚠ **Item 4's count was wrong, and the guide ships the measured number.** This
row says **four** fields can make `/healthz` report `degraded`; `service.py`
says **five** — `delivery.{expired_at_boot, unroutable_at_boot,
journal_skipped_lines, journal_write_errors}` and `inbox.unrevivable_at_boot`.
The two `replayed_at_boot` counters are the only pair that cannot. The row's
four is the count of `reasons` **entries**: `expired_at_boot` and
`unroutable_at_boot` append one line between them, because both mean *queued,
then not delivered* and one investigation reads them together. Four reasons,
five fields. The wrong number is kept above rather than edited away — a
consumer alarming on `status` is precisely who would have found this by being
paged for a field the doc said was inert.

**Item 2 was re-measured, not copied.** The Layout line is the single home for
the test count *because* copies of it drift, so taking 246 from a queue row —
itself a copy — would have reproduced the exact defect this item corrects.
`python -m pytest -q` → **246 passed**.

---

### CG-65 · shrink the journal's body window, harden both audit trails, and correct `aitrader.md`  ✅ done (#52)

> **Shipped 2026-07-31 as #52.** Suite **247 → 268** (`/usr/bin/python3` 3.10.12,
> pytest 9.0.2). Tasks 1–9; **nothing was pruned** — CG-68 stays gated behind
> this merging.
>
> ⚠ **The pre-merge review found a data-loss race that the plan's literal code
> contained**, and it is worth reading before CG-68 touches these paths. Both
> producers write their journal `open` to disk **before** taking the queue lock
> (deliberately, on both sides), so a record can be on disk while the drain check
> reads in-memory state that does not contain it yet — and `compact([])` then
> erased it. `compact()` recomputes open-minus-close under the **journal's own**
> lock, which `Journal.open` also holds, so the two serialize. Pinned by two
> tests that were confirmed to FAIL against `compact([])`.
>
> Three smaller review findings were also fixed: three `/healthz`/docstring
> strings asserted a retention window and a `retention.py` in the **present**
> tense when neither ships until CG-68 (the CG-66 defect shape, and two of them
> on the unauthenticated endpoint); exact-mode assertions would have gone red on
> the Windows dev box CLAUDE.md documents as supported; and the Layout line's
> test count. One finding was **deferred and filed as CG-70**.

| | |
|---|---|
| **Origin** | filed by CG-64's Builder, 2026-07-31, rather than raced |
| **Rescoped** | **2026-07-31 by ADR-0002 (#49)** — `D + A + D5`. Was doc-only; is now source **and** docs |
| **Depends on** | nothing |
| **Touches** | `delivery.py`, `inbox.py`, `journal.py`, `service.py`, `__main__.py`, `docs/consumers/aitrader.md`, `docs/integration-guide.md`, `CLAUDE.md` |
| **Spec / plan** | [spec](superpowers/specs/2026-07-31-body-retention-and-audit-hardening-design.md) · [plan](superpowers/plans/2026-07-31-body-retention-and-audit-hardening.md) **Tasks 1–9** |
| **Merge gate** | no |

> ⚠ **The row grew, and the original filing is kept below rather than rewritten.**
> It was filed as four stale sentences in a consumer contract. ADR-0002 measured
> *why* they were stale, the user decided `D + A` (keep the durability, rewrite
> the promise) and then **widened the row a second time** to cover the
> `inbox-data/` exposure as well. So the doc correction below is now **item 6 of
> 6**, not the whole row — and it is the last task, because the contract text has
> to describe the retention the first five tasks create.
>
> **What the row now ships, in order:**
> 1. **Compact on drain** (`delivery.py`, `inbox.py`) — a *delivered* body's
>    residency falls from the weeks ADR-0002 §2.2 measured to seconds. ⚠ The
>    inbox half carries a trap the outbound half does not: there is **one**
>    `inbox.jsonl` for the whole gateway, so the drain check must be across
>    **every** app or polling one app truncates another's pending replies.
> 2. **`0600` at create** on `inbox-data/*.jsonl` and `deliveries/*.jsonl` — both
>    were `0644` by doing nothing, beside a journal holding strictly less at
>    `0600`. A straight lift of `journal.py`'s existing primitive, promoted to
>    one public home rather than copied.
> 3. ⚠ **The unrevivable quarantine — the gate, and the reason CG-68 is a
>    separate row.** Six places in this repo tell an operator the per-app audit
>    trail is *"the recovery record"* / *"the only copy"*, and **one of them is a
>    live `/healthz` `reasons` string** (`service.py:478`) — which makes pruning
>    a hard-rule-**#5** problem, not just a docs problem. Measured while
>    planning: at the moment `restore` declares a record lost it is **holding
>    that record** (`rec["payload"]`), and boot compaction erases it moments
>    later. So the gateway keeps it instead — `<state_dir>/quarantine/`, `0600`,
>    never swept. **Stronger than the promise it retires.**
> 4. `/healthz` fields for the quarantine (rule #5).
> 5. — *(the sweeper is NOT here; it is CG-68)*
> 6. The contract correction below, **plus** three defects the original filing
>    did not list: `:209`'s drifted line pointer, the `/v1/messages` **inversion**
>    (ADR §2.8 — correct it, do not delete it), and `CLAUDE.md`'s CG-54 bullet,
>    which should name the *retention* property and not just "durable".
>
> **Two planning measurements a Builder should not have to rediscover:** the
> per-app audit line carries **no journal id** (it is written before the id is
> minted), so "prune only what was polled" is not implementable without a schema
> change; and **`Inbox.restore` has no age ceiling** where `Dispatcher` has a 24h
> one — a 400-day-old unpolled reply restores cleanly. Both are in spec §2.

CG-64 was scoped to `CLAUDE.md` + `docs/integration-guide.md`. A sweep run
beside it found the same staleness concentrated somewhere worse: **a consumer
contract**, four claims, and the loudest one is not about durability at all.

1. **`:219`** — *"**Restart drops undelivered jobs.** The queue is in-memory."*
   False since #45. This is §6's load-bearing durability sentence and a tenant
   sizes its own fallback machinery on it.
2. **`:547`** — the same falsehood under **"Accepted limitations, agreed in the
   contract"**, which reads as a negotiated term rather than a description.
3. ⚠ **`:217`** — *"If you never call `/v1/messages`, no body text of yours is
   ever written anywhere."* **This is a privacy guarantee and it is now false.**
   `Dispatcher.enqueue` (`delivery.py:189-192`) writes
   `message.model_dump(mode="json")` — whole `text` + `cards` — to the journal on
   **every** `/v1/notify`. `journal.py`'s own docstring says so in capitals
   ("WHAT REACHES DISK"). The sentences immediately before it are still true of
   `DeliveryLog`, which is what makes this one dangerous: the reader is walked
   up to a true claim and handed a false absolute.
4. ⚠ **`:418`** — *"**Nothing about aitrader's traffic is persisted anywhere, in
   any configuration.**"* Framed at `:414-417` as *"the claim your contract
   actually rests on"*, i.e. the sentence that already survived two corrections.
   Its §8 context is inbound; its wording is unqualified, and outbound bodies now
   sit in `state/queue/delivery.jsonl` for up to the backoff ladder — or up to
   the 24h ceiling if the gateway is down.

Plus one that is stale rather than false: **`:442`** tells the operator that the
only two `/healthz` fields gating their path are `env_resolved` and
`key_configured`, and that a `degraded` reading is a tier-2 concern leaving
*"your alerting unaffected"*. Since #45 four outbound-queue reasons can degrade
it, and every one of them means an aitrader alert was dropped or will be
double-sent. That paragraph now trains the reader to ignore exactly the counters
that concern them. **`:569`**'s env table describes `CHAT_GATEWAY_STATE_DIR` as
*"heartbeat checks + delivery JSONL"*, which no longer says what the directory
holds.

**Item 3 and item 4 are why this is filed as its own row and not deferred into a
sweep.** Rule #2 is not violated — no credential reaches the journal, and
`journal.py` is explicit that identities are stored as NAMES and re-resolved
through the registry — but a tenant was told its message bodies are never
written down, and they now are. That is the tenant's decision to re-take, not a
Builder's to paper over. **Do not soften the correction into "the journal is
secure"; state what reaches disk, for how long, and at what mode.**

---

### CG-68 · Time-bounded pruning of the inbound audit trail  ✅ done ([PR #54](https://github.com/mmackelprang/chat-gateway/pull/54))

| | |
|---|---|
| **Origin** | filed by CG-65's Planner, 2026-07-31. Answers ADR-0002 §9 **Q6**, which that ADR raised and explicitly did not resolve |
| **Depends on** | ✅ **nothing — the gate is released.** It read *"CG-65 must be MERGED first"*; CG-65 merged 2026-07-31 as **#52** (`4fbd634`) and the quarantine exists (`inbox.py:264`) |
| **Base** | `4fbd634`, suite **268** |
| **Touches** | new `src/chat_gateway/retention.py`, `__main__.py`, `service.py`, **`inbox.py` (Task 14)**, `journal.py:10`, `docs/integration-guide.md:366`, `docs/consumers/jobhunt.md`, `docs/consumers/aitrader.md:569`, `.env.example` |
| **Spec / plan** | [spec](superpowers/specs/2026-07-31-body-retention-and-audit-hardening-design.md) §4 · [plan](superpowers/plans/2026-07-31-body-retention-and-audit-hardening.md) **Tasks 10–14** |
| **Merge gate** | none |

> ## ⚠ The plan was corrected on 2026-08-01, BEFORE this row runs. Read the plan's audit section first.
>
> A Planner pass re-read the plan end-to-end against what CG-65 actually shipped,
> because this row **deletes tenant content** where CG-65 only compacted
> replayable state — a stale read here is unrecoverable, not merely wasteful.
> Three outcomes:
>
> **1. Tasks 4 and 5 were corrected, and the correction is recorded rather than
> tidied away.** Their literal code said `compact([])`; #52's pre-merge review
> found that asserts an empty survivor set computed from in-memory state while
> both producers write their journal `open` to disk *before* taking the queue
> lock, so it could erase a job already `202`'d. The shipped fix is `compact()`
> — no argument — which recomputes open-minus-close under the **journal's own**
> lock (`journal.py:229`), serializing with `Journal.open`. Two gates the plan
> also lacked (`closed`, and `ids` on the inbox side) are now in it; the `ids`
> gate is load-bearing on **hard rule #6**. The plan now carries the wrong
> version, the counterfactual, and the general rule. ⚠ **ADR-0002:463 still
> shows `compact([])` on purpose** — it is labelled *"shape, not
> implementation"* and is dated evidence. Do not fix it; do not copy from it.
>
> **2. The headline for THIS row: Tasks 10–13 did NOT carry that shape.**
> `RetentionSweeper.sweep()` derives nothing from memory — it reads the
> directory and decides each file from that file's own name, so there is no
> snapshot to go stale. That is A3's *"the filename **is** the retention key"*
> paying off twice.
>
> **3. But the audit found six neighbours, now folded into Tasks 10–12** —
> one **HIGH**: `/healthz` raised **`KeyError`** whenever `sweeper is None`
> (the block's `else` branch has no `delete_errors` key and the reasons line
> indexed it unconditionally), which would 500 the endpoint hard rule #5 exists
> to keep honest, on every offline test. Plus: the retention key is **written in
> local time and read in UTC**; *"what this never touches"* was a **path
> arrangement, not a code property** — `unrevivable-<date>.jsonl` matches the
> sweeper's own regex as an app called `unrevivable` and would draw the **full
> tenant window**; a **silently dead sweeper** was indistinguishable from an idle
> one at `/healthz`; two prints bypassed **CG-29's allowlist**; and
> `unrouted_window_days` re-derived `window_for`. Severities, evidence and fixes:
> plan § *CG-68 pre-execution audit*.
>
> **4. Task 14 is new.** CG-65's review rewrote three strings that asserted a
> retention window and a `retention.py` in the **present** tense before either
> shipped. Those fixes are correct on `main` **today** and every one of them
> becomes false in the **opposite** direction the moment Task 10 lands. The
> audit found **five**, not three, and **two are `/healthz` `reasons` strings** —
> so this is hard rule #5, not a docs pass. ⚠ **Task 14 ships in the SAME PR as
> Tasks 10–12**; splitting it re-creates the window the review just closed,
> pointed the other way. Guard grep:
> `grep -rn "carries no retention guarantee\|Future tense\|no sweeper in this tree" src/`
> must return nothing.
>
> **No ⚠ verification-ledger flag is cleared, added or reworded by any of this,
> and no `src/` file was touched by the correction pass** — Planner edits the
> plan and this row; Builder writes the code.

`inbox-data/<app>-<date>.jsonl` holds a human's `text`, `sender_email` and whole
`raw` event, and has held them **forever**. CG-65 fixes the mode; this fixes the
"forever."

⚠ **Why this is its own row and not the tail of CG-65.** It is the only part that
**deletes a tenant's content**, the only part whose correctness depends on a
number the user has not yet approved, and the only part that **breaches a
published guarantee**: `docs/integration-guide.md:366` promises *every* consumer
that this file is *"never pruned."* The user has elected to amend the shared
contract rather than accept unbounded growth — but amending a published promise
is a decision that deserves its own reviewable diff, not a paragraph buried in a
nine-file PR. **ADR-0002 §9 Q6 pre-authorizes exactly this split:** *"the mode
half (`0600`) is unaffected and can proceed."*

✅ **All three of this row's decisions were granted by the user, 2026-07-31**
(spec §9, plan A1–A4). Recorded with their reasoning, not just their verdict:

1. ✅ **Retention window: 30 days** for tenant buckets, **7 days** for
   `_unrouted`, **`0` disables** — via `CHAT_GATEWAY_INBOX_RETENTION_DAYS`. The
   gateway does **not** need to hold a consumer's decision history, because
   `integration-guide.md:370` already tells consumers this file is *"a forensic
   record on the gateway host, not something you can re-poll."*
2. ✅ **Unlink, not redact.** ADR-0002 §4.1 left this open. The filename is the
   retention key, so pruning needs no parsing and never opens a file holding
   message bodies. Redaction needs field-by-field judgements about which parts of
   a person's message are sensitive, which is rule-#1 territory.
3. ✅ **Amending the shared contract is signed off**, on the basis that it is
   owed to every consumer rather than to jobhunt alone.
4. ✅ **Added 2026-08-02, mid-execution — F2's boot guard REFUSES rather than
   warns.** `RetentionSweeper._check_disjoint` stays **stricter than the
   non-recursive glob strictly requires**: `CHAT_GATEWAY_INBOX_DIR=state` — an
   operator putting everything in one place — fails at boot even though
   `glob("*.jsonl")` would never have descended into `state/quarantine/`.
   ⚠ **This was the Planner's own judgement call, phrased in the plan as a trade
   it had chosen, and it sat outside the three sign-offs above** — which is
   precisely the shape a reviewer softens on the grounds that it is "currently
   harmless". The user was asked directly and elected refuse. The reasoning they
   accepted, kept rather than summarized: *"currently harmless" is a property of
   **one line of code** staying non-recursive.* The day someone reaches for
   `rglob` for an unrelated reason that safety evaporates silently, and **a
   warning nobody reads becomes tenant data loss.** Refusing costs one clear
   boot error naming both env vars; the alternative costs the only copy of
   replies that were never delivered. Pinned in **both** directions
   (`test_a_safe_but_all_in_one_layout_is_refused_on_purpose` and
   `test_the_default_sibling_layout_is_NOT_refused`) so neither half drifts.

⚠ **What remained was sequencing, not approval — and it is now DONE.** That
line read *"CG-65 must merge first"*; #52 merged 2026-07-31. Kept as a released
gate rather than deleted, so a reader can tell a gate that was **satisfied**
from one that was never there.

**Rule #1 note, so it is not rediscovered in review:** the window is **global**.
`_unrouted`'s shorter floor is the gateway governing **its own** reserved bucket
(hard rule #6 reserves the `_` prefix), **not** per-app policy — a per-*tenant*
window would be ADR-0002 Option C's shape and would re-open the question the user
deliberately left **not reached** (D6).

**Rule #5 note:** the sweeper deletes tenant content, so it must be counted at
`/healthz` — rule #5 does not distinguish work *dropped* from work *deleted*. But
`files_deleted` must **not** degrade `status`: a retention policy working is not
a fault, and degrading on it teaches an operator to ignore `degraded` (the same
reasoning `CLAUDE.md` records for `suppressed_opt_out`).

---

### CG-69 · A published-promise inventory — the process control  📋 queued · ✅ **designed 2026-08-03**

| | |
|---|---|
| **Origin** | filed by CG-65's Planner, 2026-07-31 |
| **Depends on** | nothing |
| **Touches** | `tests/` (one new guard module), `docs/consumers/aitrader.md`, `CLAUDE.md`, this file. **No `src/` change at all** |
| **Merge gate** | no |
| **Falsifies** | nothing. Task 1 changes *pointers*, never claims; every sentence keeps its exact wording |
| **Spec** | [design](superpowers/specs/2026-08-03-published-promise-inventory-design.md) |
| **Plan** | [implementation](superpowers/plans/2026-08-03-published-promise-inventory.md) — 6 tasks, Task 6 droppable |

**Three changes in one day invalidated a guarantee recorded in a file nobody in
the loop was reading.** The shape is identical in all three, and it is not
carelessness — each change was correct in its own file:

| # | Change | Promise it invalidated | Where the promise lived |
|---|---|---|---|
| 1 | **#45 / CG-54** — journalled bodies | *"no body text of yours is ever written anywhere"* | `docs/consumers/aitrader.md:217` |
| 2 | **#45 / CG-67** — bodies moved into `state/` | `.gitignore`'s coverage: the ignore rule tracked where bodies **used to be** | `.gitignore` |
| 3 | **CG-68's prune** — *would have* | *"never pruned"* / *"the only copy"* | `integration-guide.md:366`, `:382`, **and a `/healthz` string** |
| 4 | **CG-74** — the counters it added | two `/healthz` reason strings that hedged *"neither completing nor raising"* on blocks that counted nothing | `service.py`, its own spec |
| 5 | **CG-74 again**, found by **CG-76** | *"this counter is **the only thing** standing between a silently-dropped aitrader alert and a green `/healthz`"* | `2026-08-03-delivery-write-path-robustness-design.md:421` |

⚠ **Instances 4 and 5 added 2026-08-03 by CG-76's Planner.** Instance 5 is the
sharpest yet and extends this row's thesis in a direction the original three did
not reach:

- The false absolute was **written by a Planner in a spec**, then **measured false
  by that row's own Builder during UAT**, then found **independently again** by
  that PR's reviewer reading the code — and **still shipped**, because the
  Builder correctly stayed in its lane and did not edit a Planner artifact. **The
  process worked and the claim still went out false.** An inventory is what
  routes that finding back to the artifact.
- **Five of the six doors CG-76 then found raise nothing at all**, so the very
  counter the sentence was defending could not have seen them.
- ⚠ **It took TWO independent sweeps of the same code path to find the last two
  doors.** The first deliberate sweep confidently enumerated four. That is the
  strongest available argument that *"someone will notice"* is not a control.

**None was caught by reviewing the diff, because the diff never contained the
sentence it broke.** Instance 3 was caught only because ADR-0002 went looking —
and CG-65's planning found that even that search **missed** `service.py:478`, the
one site with a hard rule attached.

**The proposed control, and it has precedent here.**
`tests/test_error_surfaces.py` already reads *construction sites* to guard a
property that lives in prose. Same idiom: a test-owned **inventory of absolute
claims** in `docs/consumers/*.md` and `docs/integration-guide.md`, each paired
with the code that makes it true, failing when a claim has no owner. It does not
prove the claims — it makes the set **enumerable**, so a durability change can be
checked against it in the minute before merge rather than in an ADR two PRs later.

**Concretely, it would have caught all three:** claim 1 names `delivery.py`,
which #45 rewrote; claim 2's owner is `.gitignore`, whose covered paths changed;
claim 3 names `inbox.py::_audit`, which CG-68 modifies.

⚠ **Filed, not folded into CG-65.** Folding a good idea into an open row is the
scope creep this queue keeps correcting — and it would be a fourth instance of
shipping something whose consequences nobody had written down.

#### ✅ The Planner call, 2026-08-03 — build it, **inverted and one fifth the size**

**Everything above stands as the problem statement. Two things in it are
falsified by measurement, and both change the design.** Reasoning and every
number: [spec](superpowers/specs/2026-08-03-published-promise-inventory-design.md).

1. **"The diff never contained the sentence it broke" is not the discriminator.**
   A full history sweep found **41** instances — **19** category (a), a live
   claim falsified by a later code change; **11** wrong when written; **4**
   moving facts with two homes; **7** external-world. ⚠ **Instances 4 and 5
   above are both already inside that list**, and **19 is the denominator this
   control is measured against** — the other 22 are outside any guard's reach.
   Four are counterexamples. The sharpest: `adapters/pubsub.py`'s docstring named
   *"queue item CG-10"* as open work; **CG-10 then rewrote 150 lines of that same
   file**, with hunks landing one line from one false sentence and bracketing
   another. Missed — then missed **again** by CG-21's dedicated sweep, unfixed
   for ten PRs. What actually separates caught from missed is **file ownership**:
   `/healthz` stopped drifting once hard rule #5 made it a *named category every
   row must check, backed by tests*; `docs/consumers/*` kept drifting because
   nothing named it. The control's job is to do for the contracts what rule #5
   did for `/healthz`, not to enumerate claims at diff time.

2. **The pairing mechanism this row proposes has already been tried here by
   hand, and has already rotted.** Of the 14 `file.py:LINE` citations in the live
   contract docs, **8 point at unrelated code today** — including **three of the
   four enforcement points `aitrader.md` §8 lists under hard rule #6**, the
   clause a real-money tenant treats as a security guarantee. Over the same
   window the same files' **name**-anchored citations are **0 of 8 wrong**. The
   anchor form is the entire difference. ⚠ **This row's own three citations have
   drifted too** — `aitrader.md:217` no longer holds the sentence it quotes.

**So: not an inventory of prose. An executable anchor on the pairings the docs
already contain, plus two pins on code-side sets that are measurably tiny.**

- **Do build.** (1) `module.py::Qualified.Name` anchors in `docs/consumers/*.md`,
  `docs/integration-guide.md` and `CLAUDE.md`, with a test that every anchor
  resolves and the line-number form cannot return — the convention this repo
  already writes **45 times in its working documents and 0 times in its
  contracts**. (2) A pin on the set of places `src/` can delete a file — **one
  member today**, and *"never pruned"* / *"the only copy"* are claims about
  exactly that set. (3) A pin that every default tenant-data directory is
  `.gitignore`d — instance 2, mechanically. (4) A **`Falsifies`** field in this
  row shape: free, and the best-performing control in the whole record.
- **Do NOT build** an inventory of absolute prose claims, in any form. 226
  absolute-carrying lines in the proposed scope; and the one promise family
  *"never pruned"* / *"the only copy"* has **93 occurrences repo-wide of which 7
  are live contract** — the other 86 are ADR-0002, the retention plan and
  shipped rows, which this repo keeps verbatim on purpose. A text-keyed guard
  cannot tell a live promise from a retired one and would be deleted.

**Honest limits, recorded rather than claimed away.** None of this catches a
claim that was **wrong when written** — the largest category in the sweep, and
the class today's spec-§5 defect belongs to. The one pin that might have (every
`except` that never re-raises) was measured at **26 sites** and dropped. That
class is served by the `Falsifies` field and by a reviewer reading the code, and
saying otherwise would be the same over-promise this row exists to prevent.

⚠ **The stale-citation repair is Task 1 of THIS row, not a follow-up.** CG-75
settled it: *"rule #5 does not permit leaving a false statement standing for the
duration of a second PR."* Three of the eight are in a tenant's hard-rule-#6
table.

---

### CG-70 · The `0600` chmod is create-only, so a pre-existing `0644` file keeps its mode  📋 queued · ✅ **decided 2026-08-02**

| | |
|---|---|
| **Origin** | filed by **CG-65's Builder**, 2026-07-31, out of that PR's own pre-merge review (finding L3) |
| **Depends on** | nothing — CG-65 (#52) shipped the create-time half |
| **Touches** | `journal.py::_append` + its batch-close sibling, `inbox.py::_audit` + the quarantine append, `delivery.py::DeliveryLog.record` — **four sites, not two** |
| **Merge gate** | no |
| **Decision** | **(a). Reasoning + measurements: [spec](superpowers/specs/2026-08-02-runtime-lifecycle-and-liveness-design.md) §6** |

CG-65 applies `chmod_owner_only` **only when the file did not already exist** —
that guard is what keeps the chmod off the hot path, one syscall per *file*
rather than per *append*. The consequence is that a day-file created by an
earlier build, by a different umask, or by anything else, **keeps `0644`
forever**. Only files created after CG-65 are `0600`.

**Why this is LOW and was deferred rather than folded in:** the gateway has
never been deployed (ADR-0002 §8), so no such file exists in production, and the
window is bounded by one day — the filename is date-sharded, so tomorrow's file
is created fresh at `0600`. The queue journals escape the problem entirely
because compaction replaces the inode (`journal.py`), which also upgrades a
legacy `0644` journal for free.

**Two candidate fixes, not chosen here.** (a) `stat` the existing file and chmod
when the mode is wrong — correct and self-healing, but adds a `stat` per append
to a path that deliberately has none. (b) A one-time `chmod 0600` line in the
CG-53 deploy runbook, beside the `install -d -m 0750` that already owns the
directory modes — no hot-path cost, but it does not help a dev box. **(b) looks
right given the runbook already owns this class of control**, but it is a
Planner call, not a Builder's.

#### ✅ The Planner call, 2026-08-02 — **(a)**, and the paragraph above is wrong

The row's reason for preferring (b) is *"adds a `stat` per append to a path that
deliberately has none."* **That path already has one.** `existed = path.exists()`
**is** a stat, and it runs on every append at all four sites. Measured at the
syscall level with `strace` on the real `Journal`, three consecutive appends:

```
newfstatat(AT_FDCWD, ".../sc.jsonl", 0x7ffcf59ff2f0, 0) = -1 ENOENT
openat(AT_FDCWD, ".../sc.jsonl", O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC, 0666) = 3
chmod(".../sc.jsonl", 0600) = 0
newfstatat(AT_FDCWD, ".../sc.jsonl", {st_mode=S_IFREG|0600, st_size=113, ...}, 0) = 0
openat(...) = 3
newfstatat(AT_FDCWD, ".../sc.jsonl", {st_mode=S_IFREG|0600, st_size=226, ...}, 0) = 0
openat(...) = 3
```

One `newfstatat` per append, already there — **and the kernel already hands back
the mode in it** (`st_mode=S_IFREG|0600`). `Path.exists()` discards that and
keeps one bit. So (a) is not "one more syscall"; it is *read the field the
syscall you already make already returned*. Steady state: **identical syscall
count.** One-time: exactly one `chmod` per wrong-moded file, ever.

**Honesty in the other direction — (a) cannot reach every affected file.** The
write paths are date-sharded and only ever open **today's** file, so a `0644`
day-file from three days ago is never reopened and (a) will never touch it. It
sits at `0644` until the sweeper deletes it — up to `retention.window_days`, and
**forever** where `CHAT_GATEWAY_INBOX_RETENTION_DAYS=0`. **(a) and (b) cover
disjoint sets; the row presented them as alternatives and they are not.**

**A third option was considered and rejected.** (c) a one-time chmod pass at
boot, beside the boot sweep `__main__` already runs — reachable, and unlike (b)
it works on a dev box. Rejected because it would be the **third home** for a
file-mode control, against `chmod_owner_only`'s own docstring (*"One home,
because a second copy of a security control is how the two drift apart"*), and
because it adds a second boot-time walker with different exclusion logic over
the same trees the sweeper deletes from — which is buying a repeat of CG-68's M2
for a set of files that is **empty today**.

**Outcome:**
- **(a) is the mechanism**, at all four `existed = path.exists()` sites.
- **(b) becomes one line in CG-53's runbook**, for the historical files (a)
  cannot reach — it belongs there because CG-53 already owns
  `install -d -m 0750`, not because it is better than (a).
  ✅ **Written 2026-08-03** into plan **Part A §3**, with the disjoint-sets
  reasoning and a verify pass that must print nothing. ⚠ **That does not close
  this row and must not be read as closing it** — (b) covers only the historical
  files, **(a) is still unbuilt**, and this row stays open for the four `src/`
  sites. Part A says so in as many words, so a Builder reading either row alone
  cannot conclude the other half is done.
- **(c) rejected.**
- **The row stays open and is NOT folded into CG-53.** Closing it was considered
  and is a legitimate outcome — it is LOW, no such file exists anywhere today,
  and date-sharding bounds it. It is kept because **(a) is a `src/` change across
  four files with tests and CG-53 is a merge-gated deploy row**; folding a
  four-file code change into the row that handles secrets makes the gated PR
  bigger, which is the opposite of what a merge gate is for.
- **Severity unchanged — still LOW. The reason to do it changed**, from *"defer
  it, it is low"* to **"do it, it is free."** The row was deferred on a cost that
  does not exist.

---

### CG-72 · `/healthz` cannot see two of the four threads  ✅ done (#56)

⚠ **Shipped 2026-08-02. Suite 314 → 324** (re-measured on `3526d50` before starting;
never copied from a row). Everything below is the row as filed; what actually
shipped, and the two review findings that changed it, are recorded after it.

**Proven, not asserted.** Both threads were killed in a **real** `uvicorn`
server through the hole `is_alive()`'s docstring names — an exception raised
inside `_run`'s own handler (its `__str__` raises, which is what a `print()` to a
closed stdout does), **not** `.stop()`. Same fault, same harness, both sides:

| | `main` @`3526d50` | this branch |
|---|---|---|
| `status` | **`ok`** | **`degraded`** |
| `reasons` | `[]` | one per dead thread, no more |
| `delivery.thread_alive` | *field does not exist* | `false` |
| `heartbeats.last_scan_at` | frozen at a real timestamp | frozen — **and now labelled** |

The four states are distinguishable at the endpoint, which was the whole point:
never-started `(False, False)` → **silence**; running `(True, True)` → silence;
started-then-died `(True, False)` → one reason; alive-but-stale → a *different*
one reason. Note the third case shipped with `seconds_since_last_pass: 0.0` — a
perfectly healthy staleness number on a dead thread, which is exactly why
`thread_alive` is not redundant with the timestamp.

**Review: 0 HIGH, 3 MEDIUM, 6 LOW.** Two are worth carrying forward:

- **M1 — the sentence that outlived its evidence.** Both new staleness reasons
  said *"passes are neither completing nor raising, so it is wedged rather than
  erroring."* That wording was copied from the subscriber and retention chains,
  where it is true **only because a failure-counter branch sits above it**.
  `Dispatcher` and `HeartbeatMonitor` count nothing, so the claim arrived without
  the thing that made it true — a `/healthz` string telling an operator the
  opposite of what the console was saying, on the endpoint whose charter is not
  doing that. Reworded to *"either WEDGED or RAISING"* with a pointer to the
  console line; the counters are **CG-74**.
- **M2 — the plan's micro-optimisation that changed a meaning.** The plan said
  *"`now` is already bound at the top of `process_due`; do not call `self._now()`
  a second time"*, so `last_pass_at` published when the pass **began** while
  `__init__`'s docstring, the integration guide and this row's own 600s budget
  arithmetic all defined it as when the pass **completed** — halving the budget's
  real headroom and making this the one place the row invented a fourth idiom
  while naming the two classes it was copying. One line; deviation recorded at
  the code comment, which is its one home.

**L3 was signed off by the user during this row and deliberately NOT built** —
it is Part B's. Recorded with its reasoning and a blast-radius check in the
[plan](superpowers/plans/2026-08-02-runtime-lifecycle-and-liveness.md).

---

#### The row as filed  · **sequenced before CG-71**

| | |
|---|---|
| **Origin** | filed by CG-71's Planner, 2026-08-02, found while measuring CG-68's deferred L4 |
| **Depends on** | nothing. **CG-71 depends on THIS** — same two classes, must not run concurrently |
| **Touches** | `delivery.py::Dispatcher`, `heartbeat.py::HeartbeatMonitor`, `service.py::healthz` |
| **Merge gate** | no |
| **Docs** | [spec](superpowers/specs/2026-08-02-runtime-lifecycle-and-liveness-design.md) §2.6 + §4 · [plan](superpowers/plans/2026-08-02-runtime-lifecycle-and-liveness.md) **Part A**, Tasks A1–A7 |

Hard rule #5 says `/healthz` reports real liveness. It does, for half the
threads. Measured on `36fac22`:

| thread | `thread_alive` | `thread_started` | staleness | can degrade `status`? |
|---|---|---|---|---|
| `pubsub-subscriber` | ✅ | ✅ | ✅ | ✅ |
| `retention-sweeper` | ✅ | ✅ | ✅ | ✅ |
| `delivery-dispatcher` | ❌ | ❌ | ❌ | **❌** |
| `heartbeat-monitor` | ❌ | ❌ | ❌ | **❌** |

`grep -c thread_alive src/chat_gateway/service.py` → **8**, every one of them in
the subscriber or retention block. In the `delivery` block, **every**
`reasons.append` is gated on `journal_skipped_lines`, `journal_write_errors` or
`expired_at_boot`/`unroutable_at_boot`; **`pending_jobs` gates nothing.** In the
`heartbeats` block, **no reason references `last_scan_at` at all.**

Both `_run` loops swallow per-pass exceptions and continue, which is right —
neither catches what its own handler raises, which is the hole
`RetentionSweeper.is_alive`'s docstring was written about (*"a `print()` to a
closed or blocked stdout is the realistic one"*). So today:

- **A dead `delivery-dispatcher` means every outbound notification silently
  stops.** `pending_jobs` climbs and `/healthz` answers `ok` forever.
- **A dead `heartbeat-monitor` means the dead-man switch is dead.**
  `last_scan_at` freezes at a *real* timestamp — which is what makes it look
  healthy — and `missed` stops moving because nothing scans. aitrader's contract
  surface is a dead-man monitor.

**This is CG-68's F3/M3b finding, on the two threads that never got it** — the
sweeper grew `started` + `is_alive()` because a reviewer went looking; nobody
went looking here. It is the 11-day-silent-capture-failure shape rule #5 was
written after, present twice.

⚠ **Two things the plan makes non-negotiable.** `Dispatcher` has no "last
completed pass" timestamp at all (`process_due` returns a count and stamps
nothing), so one is added — and it **must stamp on an empty pass too**, or
"healthy and idle" stays byte-identical to "dead" at this gateway's traffic
shape. And an app whose dispatcher was never started (all 23 bare-`TestClient`
tests) must render as **silence, not a reason** — CG-68's audit F0 is the same
lesson with a `KeyError` instead of a false alarm.

---

### CG-75 · A raising `_finish` re-sends the same job every second  ✅ done (#58)

| | |
|---|---|
| **Origin** | filed by CG-72's Builder from its own pre-merge review, 2026-08-02; specced 2026-08-03 |
| **Depends on** | nothing. **CG-55 and CG-74 both depend on THIS** |
| **Touches** | `delivery.py::DeliveryLog.record`, `service.py::healthz` (body field + one reason + two string corrections) |
| **Merge gate** | no |
| **Docs** | [spec](superpowers/specs/2026-08-03-delivery-write-path-robustness-design.md) §2.2/§3/§6 · [plan](superpowers/plans/2026-08-03-delivery-write-path-robustness.md) **Part A**, Tasks A1–A5 |
| **Shipped** | **#58**, 2026-08-03. Suite **324 → 333** |

✅ **Shipped, and the storm was measured gone rather than asserted gone.** The
same harness that produced the 60/60 above was re-run against the branch with a
**real kernel `PermissionError` (errno 13)** — an unwritable directory, not a
monkeypatched `Path.mkdir`, so what met the refusal was the real method:
**60 sends → 1** on the delivered path, and **1654 sends over 6000 passes → 5**
on the retry path, which is `len(BACKOFF_S)` exactly. `pending()` reaches 0 and
`last_pass_at` stamps again, where pre-fix it was frozen at `None`.

**The half that could have been broken silently was checked too:** on a real
uvicorn server wired like `__main__ serve`, with the whole state tree chmod'd
read-only mid-flight, `POST /v1/notify` **still returns 500**. `enqueue`'s
journal `open` is untouched, so a genuinely full disk still hands the alert back
to the consumer's fallback log. The in-flight job already accepted was delivered
**once** across 20+ subsequent passes, `/healthz` went `degraded` with one
`delivery log:` reason, and `GET /v1/deliveries` still answered `delivered` off
the in-memory ring — which is the whole reason the guard sits below the ring
append rather than around the call sites.

Review found **0 HIGH, 2 MEDIUM, 0 LOW**, both fixed before merge and both about
test fidelity rather than the fix. **M1** is the sharper one and is worth keeping:
the two storm tests chmod'd the audit dir unwritable *before* the `DeliveryLog`
existed, so on pre-fix code they raised out of `enqueue`'s first `record` and
**never reached `process_due` at all** — red, but for the wrong reason, and
therefore not a pin on this row's defect. Restructured to the measured sequence
(enqueue succeeds, *then* the disk fills) and proven red-then-green by removing
the guard in a working tree. **M2**: the reworded heartbeat `/healthz` string had
no test while its delivery twin had one — a corrected rule-#5 string with no pin.

A measured constraint fell out of M1 and now lives in the test helper's docstring:
`Path.mkdir(parents=True, exist_ok=True)` on an **existing** directory does not
raise even inside an unwritable parent (CPython returns early on `exist_ok and
self.is_dir()`), so a mid-run break has to chmod the day **file**, not the
directory. That is why the two helpers in `test_durability.py` inject the failure
differently on purpose — do not unify them.

⚠ **CG-74 and CG-76 remain open and neither is closed by this.** CG-76 in
particular was measured *not* to be rescued: post-CG-75 the dead-man alert's drop
arrives from `enqueue`'s journal `open`, which is unguarded by design.

**Measured on `696a8cd`, suite 324, before anything was designed.** One enqueued
notification, one successful send, then a full disk:

```
passes run           : 60
passes that RAISED   : 60
SENDS TO GOOGLE      : 60
jobs still queued    : 1
```

`_finish` calls `self._log.record(...)` at `delivery.py:295`, before the
`_journal_write(... close ...)` at `:302` and before the job leaves `_jobs` at
`:304–306`. `DeliveryLog.record` does a raw `mkdir` at `:95` with **no guard**.
`_finish` is called from the `else:` branch of `process_due`'s `try`, **which its
own `except` does not cover**, so the `OSError` escapes `process_due` entirely,
the job stays due, and the next pass sends it again.

**The fix is one guard, and its placement is the whole design.** It goes
**inside `DeliveryLog.record`, around the file block only** — not around the
call sites. The in-memory ring buffer is appended to *before* the disk is
touched, so `query()` and `GET /v1/deliveries` still answer *"did this alert
reach Chat?"* correctly for the life of the process. What is lost is the on-disk
copy, not the answer.

**Two options rejected, recorded so they are not re-proposed.** (b) *remove the
job from `_jobs` before raising* — stops the storm by inverting `_finish`'s
deliberate ordering (the log record precedes the `close` so a mid-flight kill
replays rather than loses) and re-opens CG-65's compaction race; paying a
data-loss risk to fix an availability bug is the wrong direction. (c) *treat the
audit failure as retryable and hold the job* — needs a send/finalize state
machine this class does not have, for a condition in which the disk is full and
everything else is failing too.

**What swallowing costs, stated rather than argued away.** The entry's on-disk
delivery record is gone for good — and `journal.py` is explicit that the per-app
audit files cannot substitute, because they record what **arrived**, never what
**left**. And the job now reaches the `close`, which on a full disk also fails
and is also counted, so the journal entry stays open and **replays at the next
boot, possibly delivering twice**. That second cost is not new: it is the
identical at-least-once trade `_journal_write`'s docstring already blessed
(*"at most one duplicate on the next boot"*), and `service._journal_write_errors`
says the same thing from the other end — *"raising there would turn a full disk
into a re-send storm."* **This row is that sentence applied to the one write on
the path that never got the guard.**

⚠ **It falsifies two unauthenticated `/healthz` strings and must correct them in
its own PR** (rule #5 does not permit leaving a false statement standing for the
duration of a second PR). The delivery staleness reason ends *"a full disk, which
makes the delivery log's own write raise, is the other one"* — **false** after
this. The heartbeat one ends *"a scan that fires a check enqueues through the
delivery log, so a full disk raises there"* — **true but naming the wrong file**;
after this the raise comes from `enqueue`'s journal `open`. So does the
explanatory comment at `service.py:764–775`, which describes this defect in the
present tense.

⚠ **Nothing in `_finish` moves.** The record → `close` → remove → `drained` →
compact sequence is byte-identical after the fix, so CG-65's compact-on-drain and
CG-54's replay are untouched and `drained` needs no re-derivation. **Do not edit
the mid-flight comment at `:297–301`.**

---

### CG-74 · `Dispatcher` and `HeartbeatMonitor` count no failures  ✅ done ([#60](https://github.com/mmackelprang/chat-gateway/pull/60))

| | |
|---|---|
| **Origin** | filed by CG-72's Builder from its own pre-merge review (M1), 2026-08-02; specced 2026-08-03 |
| **Depends on** | **CG-75** — same two functions, same two `/healthz` strings. **Must not run concurrently** |
| **Touches** | `delivery.py::Dispatcher`, `heartbeat.py::HeartbeatMonitor`, `service.py::healthz`, `docs/integration-guide.md` |
| **Merge gate** | no — but it is a **new degrade input on an endpoint consumers alarm on**, which CG-72's own comment calls *"a decision, not a wording fix"* |
| **Docs** | [spec](superpowers/specs/2026-08-03-delivery-write-path-robustness-design.md) §5 · [plan](superpowers/plans/2026-08-03-delivery-write-path-robustness.md) **Part B**, Tasks B1–B6 |

**The row's own claim, measured and narrowed.** It says the staleness branch
*"never fires at all"* on the retry path. Over 400 simulated seconds that is
exactly right — 3 raises, 3 sends, **worst observed staleness 1.0s against a 600s
budget**, `/healthz` `ok` throughout, because the raise lands *after* the backoff
has been applied and every empty pass in between still stamps. Run past the
ladder and it stops being right: `BACKOFF_S` exhausts at **t=4350s (72.5
minutes)**, `_finish(job, "failed")` raises before removing the job, and the
retry path becomes CG-75's 1/second storm — 1654 sends over 6000 seconds, worst
staleness 1650s, which **does** trip the branch. The blindness is bounded and
long; what ends it is the failure getting worse.

**Three counters, three explicit rule-#5 verdicts.**

| Counter | Cumulative / consecutive | Degrades? |
|---|---|---|
| `Dispatcher.pass_failures` / `consecutive_pass_failures` | both | cumulative ❌ / consecutive ✅ at 3 |
| `HeartbeatMonitor.scan_failures` / `consecutive_scan_failures` | both | **cumulative ✅** / consecutive ✅ at 3 |

**The asymmetry is the decision, and it is measured, not stylistic.** A failed
dispatch pass is recoverable — the due job is still in `_jobs` and the next pass
retries it. A failed **scan** is not: `due_alerts` marks the check before
persisting, so the alert it would have sent is already dropped for the 24h repeat
window and no later scan re-sends it. That is `RetentionSweeper.errors`'s own
test — *"nothing for a later pass to recover from"* — so it takes
`RetentionSweeper.errors`'s posture. ⚠ **This is the item most worth the user
overruling at checkpoint;** the conservative alternative is body-only until CG-76
lands, which means accepting that a dropped dead-man alert produces no `/healthz`
signal at all.

**Threshold 3, not the sweeper's implicit 1,** because the sweeper runs every six
hours and this loop runs every **1.0s** — a single blip must not flip an alarm on
an endpoint consumers page on. Three passes is three seconds.

`last_pass_error` / `last_scan_error` render through `describe_exception`
(`RetentionSweeper.last_sweep_error`'s precedent, **not** `SubscriberLoop`'s
hand-rolled format, which CLAUDE.md says must not be unified onto the helper).
⚠ `OSError` is unmarked, so these read exactly `"OSError"` — no `errno`, no path.
**Deliberately lossy.** Marking `OSError` would recover it *and* enlist its raise
sites in `test_error_surfaces.py`, but `str(OSError)` embeds absolute paths
(`retention.py:444–447` measured it), so that is a hard-rule-#2 decision of its
own. **Not folded in** — the same posture `RetentionConfigError`'s docstring
sets.

⚠ **Closes two of CG-73's five sites** as a side effect (both `_run` prints).
CG-73's row is counted down to three, not left at five.

---

**SHIPPED as [#60](https://github.com/mmackelprang/chat-gateway/pull/60),
2026-08-03. Suite 333 → 345**, both ends measured, neither copied. Six fields,
three of which degrade, each with its verdict in the guide's Degrades? column
and a matching guard (or deliberate absence of one) in `service.py`'s chain.

**The row's headline claim, demonstrated rather than argued.** Real uvicorn
server, real loop threads, real HTTP, and a real kernel `PermissionError` from
`chmod a-w` on the state dir — same harness on `main` as a control. A registered
dead-man check went missed while the store could not persist:

| | `main` (`74b457b`) | branch |
|---|---|---|
| `/healthz` `status` | **`ok`** | **`degraded`** |
| `heartbeats.scan_failures` | *(no such field)* | `1` |
| heartbeat `reasons` | *none* | names the loss |
| `check.status` / `last_alerted` on disk | `missed` / stamped | `missed` / stamped |
| notifications actually sent | **0** | **0** |

Both sides drop the alert — that is **CG-76**, untouched here. What changed is
that `main` called it healthy.

**The dispatcher half, same method:** a real `OSError` out of the real `_run`
loop drove `pass_failures` / `consecutive_pass_failures` to 6 with
`last_pass_error: 'OSError'`, and at ≥3 the RAISED reason **replaced** the
staleness reason — the ordering, observed live rather than only in a test.
⚠ Note what this also confirms: post-CG-75 **no environmental fault reaches this
counter**, because every filesystem write inside `process_due`/`_finish` is
guarded. The dispatcher branch is defence-in-depth for *everything else that can
raise*, and the demonstration had to raise deliberately to reach it. Said here
rather than left for a reader to assume the disk door still exists.

**Review: 0 HIGH, 2 MEDIUM, 3 LOW. Both MEDIUMs fixed** — neither a correctness
bug, both rule-#5 honesty defects, which is the one class this row could not
ship with.
- **M2 — an absolute claim that was false, and it had already been measured.**
  `scan_failures` was documented as *"the only thing standing between a
  silently-dropped dead-man alert and a green /healthz"*. It is not: a notify
  **refused for want of a route** raises `HTTPException(503)`, which
  `_monitor_notify` **catches** — alert dropped, `scan_once` completes, no
  counter moves, `/healthz` `ok`. Narrowed in `heartbeat.py` (wording only) and
  pinned by `test_a_routeless_alert_is_dropped_without_raising_or_counting`,
  whose docstring records that it is a hole rather than a contract and that
  **CG-76 should turn it red**. ⚠ **Spec §5 still carries the absolute
  sentence** — Planner's artifact, deliberately not edited here.
- **M1 — two tests asserted a one-reason count from a state `_run` cannot
  produce.** `_run` moves both scan counters in one `except`, so the real state
  emits **two** `heartbeats:` reasons — the deliberate design, published in the
  integration guide, and previously **untested**. A "fold `scan_failures` into
  the elif chain" refactor would have stayed green while deleting the lost-alert
  warning. Now pinned.
- **L3 taken** (dead-thread must outrank the counter branch — reachable, and
  nothing ranked it). **L1 deferred** (the reason's `pending_jobs` clause is
  inherited verbatim from the sibling dead-thread string; tightening one alone
  creates the inconsistency it would fix). **L2 deferred deliberately** — the
  clear-order window that can render `(last: None)` is **byte-identical to
  `RetentionSweeper._run`**; matching the established idiom is the point, and it
  is recorded so the copy is a decision.

**The reviewer also settled the ordering STRUCTURALLY, not just by test:**
`_dispatch_stale_after` is 600 pass intervals and `_scan_stale_after` is ≥6 scan
intervals for any settable `monitor_interval`, against a threshold of **3** on
both. Every iteration either stamps or increments, so a raising loop trips the
counter branch strictly before staleness is reachable. Reaching the staleness
branch under threshold therefore *requires* a loop that is neither completing
nor raising — which is exactly what the string now asserts.

**No ⚠ verification-ledger flag cleared, added or reworded.**
`git diff main -- src/ | grep -c "LIVE-UNVERIFIED\|SHAPE-VERIFIED"` → **0**;
the full baseline `8 / 4 / 6 / 2 / 3` prints identically either side.
`adapters/`, `docs/architecture/` and `errors.py`'s allowlist untouched —
`OSError` stays unmarked, so both new error fields read exactly `"OSError"`,
which is the lossy-on-purpose half of spec §5.

---

### CG-76 · The dead-man switch's SIX doors to a silently-dropped alert  📋 queued · ✅ **specced + planned 2026-08-03**

| | |
|---|---|
| **Origin** | filed as **one ordering defect** by CG-74/CG-75's Planner, 2026-08-03. ⚠ **WIDENED by the user to "both doors"**, then found by this row's own sweeps to be **six** |
| **Depends on** | nothing. **Not fixed by CG-75** — measured. **CG-55 depends on THIS** |
| **Touches** | `heartbeat.py` (`due_alerts` split, `scan_once`, counters, `list_all`), `service.py` (`_monitor_notify`, `refresh_heartbeat`, `/healthz` body + reasons), `delivery.py` (`_finish` counter) |
| **Merge gate** | no — ⚠ **but it adds FOUR degrade inputs to an endpoint consumers alarm on**, which CG-72's own comment calls *"a decision, not a wording fix"*. Flagged for the user at checkpoint, not slipped in |
| **Pre-deploy blocker** | **yes** (user decision 2026-08-02) |
| **Docs** | [spec](superpowers/specs/2026-08-03-dead-man-alert-loss-design.md) · [plan](superpowers/plans/2026-08-03-dead-man-alert-loss.md) **Part A** |

#### ⚠ The count moved four times, and that is worth more than the number

| Sweep | Found | How |
|---|---|---|
| accident, week 1 | **door 1** | CG-76's filing Planner, sweeping unguarded **writes** for CG-75 — looking at something else |
| accident, week 2 | **door 2** | CG-74's Builder during UAT, then **independently** by its pre-merge reviewer reading the code |
| deliberate sweep #1 | **doors 3, 4** + the batch amplifier | this row's Planner, looking on purpose |
| **deliberate sweep #2** | **doors 5, 6** + 2 adjacent findings | an **independent** re-sweep of the same path, commissioned *only* because the brief asked whether two was the complete count |

**Four rounds of looking produced four different answers.** The row would have
shipped a four-door fix and left door 6 — the worst of them — standing. This is
**CG-69's thesis as evidence rather than argument**.

#### The six doors — every one measured, none reasoned about

All six produce the identical outcome: **a registered dead-man alert is never
delivered and `GET /healthz` answers `status: ok`, `reasons: []`.**

| # | Door | file:line | Raises? | Any `/healthz` field? |
|---|---|---|---|---|
| 1 | the **mark lands before the alert** — `status="missed"` + `last_alerted` set, then `_save()`, all before `scan_once` notifies | `heartbeat.py:159–165` | yes | `scan_failures` — **the only visible door** |
| 2 | **route refusal never re-raises** — `except HTTPException` logs and falls through | `service.py:299–300` | **no** | none |
| 3 | **retry ladder exhausts** — `_finish(job,"failed")` records and counts nothing | `delivery.py:351`, `:389` | **no** | none |
| 4 | **deduped** against the previous outage's alert; return value discarded | `service.py:285–289`, `heartbeat.py:231` | **no** | none |
| 5 | **source left the registry** — check vanishes from the `/healthz` census while still scanned and still failing | `service.py:443` | **no** | `checks: 1 → 0` (worse than none) |
| 6 | **the 24h REPEAT alert** — `missed` was already `1`, so nothing moves | `service.py:512` | **no** | ⚠ **NOTHING AT ALL** |

⚠ **Three of the six need no fault of any kind** — no disk error, no
misconfiguration, no exception, healthy disk, default config. Doors 3, 4 and 6.

⚠ **Door 4 is not the exotic one it sounds like.** `DEFAULT_DEDUPE_WINDOW_S` is
3600s; it bites any check whose `schedule + grace < 1h` — e.g. an
`every:5m`/`5m` check. Measured: a source died, was alerted on, **recovered and
refreshed** (which correctly clears `last_alerted`), then died **again** inside
the hour. **Two distinct outages, one alert.** The second death — the one a
real-money system most needs — was never announced.

⚠ **Door 6 is the worst and was invisible to the first deliberate sweep.**
```
repeat scan -> 1 fired; adapter.attempts=6; sent still 1
delivery log tail: {..."status":"failed","detail":"gave up after 5 attempts"}
FIELDS THAT CHANGED (excluding clock-driven timestamps):
  (NONE — literally nothing moved)
```

#### ⚠ `heartbeats.missed` is not a signal, and never was — the control that proves it

A **successfully delivered** alert produces the *identical* `/healthz` diff to a
dropped one: `missed: 0 → 1` plus liveness timestamps. It reports check *state*,
never whether anyone was told; it is inert; and on door 6 it does not move at
all. **No fix in this row leans on it, and it must stay inert** — promoting it
would alarm on the dead-man switch working correctly, the mistake
`suppressed_opt_out` stands as precedent against.

#### Two amplifiers, and they are not doors

- **Cross-tenant stranding.** `scan_once`'s loop has no `try` inside it, so one
  app's failing notify abandons every later check — all already marked. Measured
  with three tenants: a routeless `job-hunter` check **suppressed
  `aiteam-harness`'s alert entirely** for 24h, and the next scan fired **zero**.
  Fixed by marking **per check**, an isolation argument of the kind hard rules
  #4 and #6 already apply to inbound.
- **`scan_failures` counts per SCAN, not per ALERT.** Three lost alerts, **one**
  increment. The existing reason's *"at least one"* is accurate and materially
  understates it.

#### The shared cause, and the fix shape

> **`due_alerts` records *"I have alerted"* at a moment when nothing has been
> alerted** — a promise about the future persisted as a statement about the past.

Every door is a different way for the future not to arrive; doors 5 and 6 are two
ways for `/healthz` not to notice even so. The same defect class CG-65 named in
its own title — *replace the promise before deleting it* — which is why six doors
are one row.

**D1: the mark moves to `mark_alerted`, after the alert is ACCEPTED into the
durable queue** (`emit_notification` returned `enqueued`, i.e. the journal `open`
landed). That is **the same seam `POST /v1/notify` already gives an external
consumer with its 202** — the anomaly was the internal caller getting a weaker
contract than a paying one.

⚠ **This moves the dead-man path from at-most-once to AT-LEAST-ONCE, and that
was checked against precedent rather than decided fresh** — `_finish`'s
mid-flight window (*"losing an alert is the worse failure"*), `_journal_write`
(*"at most one duplicate on the next boot"*), and `Inbox._audit` (unacked, so
Google redelivers). A duplicate *"heartbeat missed"* costs one redundant phone
notification; a dropped one costs the whole feature, silently, for 24h.

**D2** refuses at **registration** (422 — not "at boot": checks arrive at
runtime, so registration is this object's boot) **and** counts at runtime, since
a route can be removed *after* a check is registered. ⚠ `aiteam-harness` and
`job-hunter` have **no `routes:` block at all** in `registry.example.yaml`, so
door 2 is live for two of three consumers. **D3** counts terminal delivery
failures. **D4** drops the dead-man `dedupe_key` entirely — since 86400s > 3600s,
the deduper could *never* suppress a real duplicate there, so every suppression
it performed was a false positive.

#### ⚠ What this does to CG-74, stated loudly because the brief asked

- **`scan_failures` KEEPS degrading — but its original justification EXPIRES.**
  It read *"a raise leaves the check marked alerted and the alert never sent."*
  D1 falsifies exactly that: the check is no longer marked, so the next scan
  re-fires it and a failed scan becomes **recoverable** — the very property that
  makes `pass_failures` inert. It stays degrading **on the weaker reason, which
  is stated rather than the strong one being re-quoted** (`CLAUDE.md`'s
  `__cg_action__` discipline). Flipping it to inert is defensible and is
  **deliberately left as a separate user decision.**
- ⚠ **CG-74's own UAT scenario now produces a different, better result** —
  `chmod a-w` on the state dir with a check going missed **delivers the alert**,
  `scan_failures` still reaches 1, and the residual risk is a duplicate at next
  boot rather than a loss. **Not a regression.** Any test asserting *"zero
  notifications sent"* under that fault asserts the old behaviour and is listed
  for update.
- **`test_a_routeless_alert_is_dropped_without_raising_or_counting` is SUPPOSED
  to go red.** Its own docstring says so. The plan rewrites it into the positive
  assertion and keeps the history; it must not be loosened.

#### Rule #5 — every new counter is a deliberate degrade input, or deliberately not

| Counter | Shape | Degrades? |
|---|---|---|
| `heartbeats.alerts_undeliverable` | cumulative | **yes** — names a guarantee BREAKING, the opposite of `suppressed_opt_out` |
| `heartbeats.checks_undeliverable` | gauge | **yes** — the live, self-healing signal |
| `heartbeats.checks_orphaned` | gauge | **yes** — ⚠ the one to **demote to body-only** if the user wants fewer than four |
| `delivery.delivery_failures` | cumulative | **yes** — same family as `expired_at_boot` / `unroutable_at_boot` |
| `heartbeats.missed` | gauge | **NO — unchanged, and must stay so** |

⚠ **All bare integers.** `/healthz` is unauthenticated and CG-12 rejected
metadata-only records on exactly that ground; the identifying detail is on the
authenticated `GET /v1/deliveries`, which `_monitor_notify` already writes to.

⚠ **`alerts_undeliverable` counts per ALERT ATTEMPT and never reads
`check.status`.** That shape is what closes door 6 and is load-bearing —
"simplifying" it into a derivation from check state looks like tidying and
silently reopens it. Pinned by a test.

#### Deliberately scoped OUT

- **Clock skew** — persisted future timestamps mean a check that never becomes
  due (`heartbeat.py:92–100`; `/healthz` publishes no deadline at all). Measured,
  filed as **CG-77**. A different defect class: it prevents an alert *becoming*
  due rather than dropping one that did.
- **`thread_started` gating every `delivery` reason** (`service.py:882–906`) —
  CG-72's deliberate, documented trade-off. Residue noted there, **not reopened**.
- **What happens to an orphaned check's persisted data** — counted, not resolved.
  A former tenant's app id under the state dir is a lifecycle *and* privacy
  question, and its own row.
- **CG-73's raw `{exc}` print sites in `heartbeat.py`** — untouched.

---

### CG-77 · Clock skew silently disarms the dead-man switch  📋 queued

| | |
|---|---|
| **Origin** | filed by **CG-76's Planner**, 2026-08-03, from that row's independent second sweep. **Measured, not reasoned about** |
| **Depends on** | nothing. Independent of CG-76 — different defect class, same file |
| **Touches** | `heartbeat.py` (`Check.next_due` / `is_missed` / `alert_due`), probably `/healthz` |
| **Merge gate** | no plan yet — **it needs a design decision first** |

**Every timestamp this class reasons about is PERSISTED, so a clock that was
wrong once stays wrong forever.** `last_seen` is written at `refresh()`
(`heartbeat.py:138`) and `last_alerted` inside the marking path (`:162`), both
from `dt.datetime.now(utc)`. `is_missed` compares against
`last_seen + period + grace` and `alert_due` against `now - last_alerted`
(`:92–100`). A host whose clock ran **ahead** when one of those wrote — a VM
resumed from snapshot, a pre-NTP boot, container drift — and then corrected
backwards leaves a check that **never becomes due**:

```
last_seen=2026-07-27T12:00 (3 days ahead)  deadline=2026-07-27T12:10  now=2026-07-24T12:00
  at now +1h: is_missed=False  due_alerts fired=0
  at now +1d: is_missed=False  due_alerts fired=0
  at now +2d: is_missed=True   due_alerts fired=1
last_alerted a month in the future, check IS missed (is_missed=True): due_alerts fired=0
```

**Nothing on `/healthz` says so.** `checks` shows the check, `missed` stays `0`,
`last_scan_at` stays fresh, `status: ok`. ⚠ **`/healthz` never publishes a
deadline at all** — the only place one is visible is the **authenticated**
`GET /v1/heartbeat/{source}` (`service.py:359`), so an operator cannot see the
disarming even if they suspect it.

⚠ **Deliberately NOT folded into CG-76**, and the reason is the defect class, not
the size. CG-76's six doors all **drop an alert that became due**; this one stops
it **becoming due**. CG-76's fix — moving the mark to after acceptance — does
nothing here, because `due_alerts` never selects the check in the first place.
Folding it in would have been the scope creep this queue keeps correcting.

**The design decision this needs before a plan:** a bounded-future sanity check
on load or on write (clamp? reject? re-stamp? degrade `/healthz` and leave the
data alone?), and whether the same treatment is owed to the delivery journal's
`next_attempt_at`, which `_parse_ts` (`delivery.py:70`) already handles the
other way — it falls back to `now` on a bad timestamp, erring toward *replaying*,
which is the safe direction and may be the precedent to copy.

No plan yet. [spec](superpowers/specs/2026-08-03-dead-man-alert-loss-design.md) §2.9 A

---

### CG-71 · Four `.start()`, zero `.stop()` — the runtime has no shutdown path  📋 queued

| | |
|---|---|
| **Origin** | CG-68's Builder deferred it as L4; re-measured and re-scoped by Planner 2026-08-02 |
| **Depends on** | **CG-72** — same two classes and the same file; **do not run them concurrently** |
| **Touches** | `service.py::create_app`, `__main__.py` (comment only), `start()` in `delivery.py`, `heartbeat.py`, `retention.py`, `adapters/pubsub.py` |
| **Merge gate** | no — but see the ⚠ flag constraint below |
| **Docs** | [spec](superpowers/specs/2026-08-02-runtime-lifecycle-and-liveness-design.md) §5 · [plan](superpowers/plans/2026-08-02-runtime-lifecycle-and-liveness.md) **Part B**, Tasks B1–B5 |

**The deferral was right to refuse and it understated the problem.** CG-68's
Builder declined Task 11's *"stop it where the dispatcher and monitor are
stopped"* because that place does not exist. Measured:

```
$ grep -n "\.start()\|\.stop()" src/chat_gateway/__main__.py
171:        sweeper.start()
179:            subscriber.start()
187:        app.state.dispatcher.start()
188:        app.state.monitor.start()
```

Four starts, zero stops, no `finally`, no `atexit`, no signal handler. **This is
not a retention row's missing cleanup — it is four long-lived threads with no
shutdown path, and CG-68 added the fourth.**

#### ⚠ The trap, measured — `uvicorn.run()` never returns on SIGTERM

uvicorn 0.42's `Server.capture_signals` restores the **default** disposition and
then `signal.raise_signal(captured_signal)`. Confirmed by experiment against a
child with all four hook shapes installed:

```
rc=-15  (killed by SIGTERM, not a clean return)
rest: 'LIFESPAN_SHUTDOWN\n'
```

**`RUN_RETURNED` did not print. `FINALLY` did not print. `ATEXIT` did not
print.** Exactly one hook ran — the **ASGI lifespan shutdown hook**, because it
executes inside `serve()` before the re-raise.

So the shape Task 11's wording implies — `try: uvicorn.run(app) finally:
dispatcher.stop()` — **is a silent no-op on the only signal that matters.** It
passes every unit test and reviews cleanly. The plan says this three times on
purpose.

#### Is it a problem today?

**No — it is latent, and the row says so rather than overselling itself.** All
four threads are daemons, the process exits in ~0.16s on SIGTERM, nothing hangs.
**Durability is not the justification:** every journal append is
`write`→`flush`→`fsync` inside one `open()` context, so nothing is buffered for
a graceful stop to flush, and a hammering daemon thread killed by SIGTERM *and*
by SIGKILL produced a clean parseable journal both times.

**CG-54's SIGKILL proof covers the durability half** —
`test_a_job_survives_an_ABRUPT_kill_of_a_real_process` kills a real child
uncatchably and proves replay with the attempt count preserved. SIGKILL is
strictly more abrupt than anything a SIGTERM path produces, so **the shutdown
gap cannot violate any promise in `delivery.py`'s or `journal.py`'s docstrings.**
What it does not cover is a kill *during* a send — and `_finish` already
documents that window as deliberate at-least-once (*"Chat gives us no
idempotency key"*). A graceful stop **narrows** it and changes no guarantee.

**What CG-55 changes is frequency, not kind.** `restart: unless-stopped` on a
TrueNAS custom app means every deploy, reboot and config change is a kill landing
mid-pass — a fresh draw on that documented window each time, i.e. an occasional
duplicate Chat message after a restart. A quality cost, bounded and already
written down.

#### Scope

- **One lifespan hook in `create_app`**, stopping all four. `create_app` already
  holds every one of them. Not four hooks, and not a `finally`.
- **Stop-only, asymmetric with `start()` by decision** — starting in the hook
  would spawn four threads in every context-managed test and would move
  `__main__`'s boot ordering (restore → boot-sweep → start, which CG-68 comments
  at length about) into the ASGI lifecycle.
- **`stop()` is NOT touched.** Measured as already idempotent and already safe on
  a never-started component, which is exactly what lets the hook call it
  unconditionally on all four.
- **`start()` idempotency** in all four: a second `start()` currently orphans the
  first thread. `start()` after `stop()` **raises** rather than silently
  returning a dead thread — `_stop` is never cleared, so today the caller gets a
  normal return, `started == True`, and a thread that exits on its first loop
  check. Clearing `_stop` would invent restart semantics for a component that has
  abandoned in-flight work; out of scope by decision.

⚠ **No ⚠ verification-ledger flag may be cleared, added or reworded.** The
shutdown path stops the thread owning `PubSubPuller` and the thread driving the
outbound adapters, which puts it one call from `adapters/`. It must not change
what any adapter sends, receives, retries or prints. If implementation appears to
need an adapter change, **stop and raise it.**

⚠ **A unit test cannot prove the hook.** UAT must SIGTERM a real
`python3 -m chat_gateway serve`. All 23 existing `TestClient` constructions are
bare, and Starlette runs lifespan only for a context-managed client — which is
both why this hook has zero blast radius on the 314 existing tests and why it is
invisible to them unless a test opts in with `with TestClient(app):`.

---

### CG-73 · Five sites bypass CG-29's print allowlist  📋 queued

| | |
|---|---|
| **Origin** | filed by CG-71's Planner, 2026-08-02, found while reading the `_run` loops for CG-72 |
| **Depends on** | nothing |
| **Touches** | `delivery.py` (4 sites), `heartbeat.py` (1), possibly `errors.py` |
| **Merge gate** | no |

`CLAUDE.md`'s CG-29 rule: an exception message is printed in full only if this
repo wrote every byte of it, enforced by `errors.py`'s marked set and
`describe_exception`. `retention.py` — the newest of the four loops — applies it
at both its print sites, with a comment explaining that `str(OSError)` from
`unlink()` embeds the absolute path. The older code does not:

| site | what it does |
|---|---|
| `delivery.py:190` | `f"dispatcher: journal {op} failed ({exc})"` — printed |
| `delivery.py:368` | `f"dispatcher: pass error (will retry): {exc}"` — printed |
| `heartbeat.py:199` | `f"heartbeat: scan error (will retry): {exc}"` — printed |
| `delivery.py::process_due` | `f"gave up after {job.attempts} attempts: {exc}"` — **persisted to the delivery log** |
| `delivery.py::process_due` | `f"attempt {job.attempts}: {exc}"` — **persisted to the delivery log** |

**Stated at the confidence it deserves: this is drift in a hard-rule-#2 control,
not a proven leak.** No live credential exposure was demonstrated — the adapters
wrap transport errors into marked classes and CG-23's tests pin that those
messages never carry a URL. The concrete half is `JournalWriteError`, which is
**not** in the marked set and whose own message embeds `str(OSError)`.

**What makes it a row is the shape, not any one site.** CG-29 chose an
**allowlist** precisely so *"the next unanticipated exception type"* prints by
type alone; these five are a denylist by omission, and the last two persist the
result to a queryable artifact rather than only printing it.
`tests/test_error_surfaces.py` cannot see any of them — it reads the construction
sites of *marked* classes, and these are print sites of unmarked ones.

⚠ **Deliberately NOT folded into CG-71 or CG-72**, and both plans instruct their
implementer to leave these strings untouched: a hard-rule-#2 control change
inside a `/healthz` row would be reviewed by nobody looking for one.

---

### CG-66 · Post-#45 residue outside CG-64's two files  📋 queued

| | |
|---|---|
| **Origin** | filed by CG-64's Builder, 2026-07-31 |
| **Depends on** | nothing |
| **Touches** | `README.md`, `src/chat_gateway/__init__.py`, `src/chat_gateway/journal.py`, `.env.example` |
| **Merge gate** | no |

Everything the CG-64 sweep found that is neither CG-64's two files nor a
consumer contract (CG-65). Small, but two of them are the exact defect shapes
this queue keeps re-learning:

- **`README.md:54` — *"98 tests"*.** A **second home** for the number whose one
  home is `CLAUDE.md`'s Layout line, and it is stale by 148. It predates #45;
  #45 only widened the gap. This is the same defect CG-64 item 2 fixed, in the
  copy nobody looked at — which is the argument for one home, made twice.
- **`src/chat_gateway/__init__.py:8` — *"inbox.py — inbound-reply queue per app
  (memory + JSONL audit)"*.** CG-54 rewrote `inbox.py`'s own first line
  *specifically* to kill this framing (`inbox.py:10-14`: it *"invites exactly
  the wrong conclusion"*), and the retracted wording survives verbatim in the
  package's module map — the first thing a reader of `chat_gateway` sees.
- **`src/chat_gateway/journal.py:26` and `:290` cite a control that has not
  shipped**: *"the deploy runbook puts the state dir at 0750."* There is no
  `docs/deploy/` in this repo. The mode **is** specified — in CG-53/CG-55's
  plan and spec (`2026-07-31-production-readiness-arc.md:411`) — so this is a
  forward-dated claim, not an invented one, and it becomes true when CG-53
  lands. **Sequencing choice, not a bug to fix twice:** either tense it now or
  let CG-53 make it true, but a content-sensitive file should not cite its
  compensating control in the present tense before that control exists.
- **`.env.example:15`** describes `CHAT_GATEWAY_STATE_DIR` as *"heartbeat checks
  + delivery audit JSONL"* — incomplete the same way `aitrader.md:569` is.
- ~~⚠ **`.gitignore` — the one non-doc item.**~~ **Split out as CG-67 and
  shipped ahead of this row** (user's promotion, 2026-07-31). The finding was
  right as written; what it could not know is that the sibling entry it sat
  beside was live, not dead — see CG-67. **This row is now doc-only**, which is
  the only thing the split changed about it.

---

### CG-67 · Stop `state/` from ever being committed  ✅ shipped 2026-07-31 · [PR #48](https://github.com/mmackelprang/chat-gateway/pull/48)

| | |
|---|---|
| **Origin** | split out of CG-66 by the user, 2026-07-31, and promoted ahead of it |
| **Depends on** | nothing |
| **Touches** | `.gitignore` |
| **Merge gate** | no |

**Why its own row rather than a CG-66 bullet.** CG-66 is documentation
staleness; this is a live path to putting tenant message bodies into git
history, and history is the one artifact this repo cannot correct with a later
PR. The user's sequencing reason, recorded as theirs rather than re-derived
here: CG-53 and CG-55 are the rows that will first run the gateway *from the
repo root*, so the window closes ahead of them or not at all. Nothing had fired
yet — there was no `state/` in the worktree — which is what made it cheap.

**Why CG-67 and not CG-63.** CG-63 is a documented gap (#46's banner: *"never
allocated — a gap in the numbering, not a lost row"*). Filling it would turn
that sentence into a description of a row that has nothing to do with what a
reader was told to expect. A gap costs nothing; a re-used gap costs a reader.

**What was measured, from the repo root, through `build_runtime()` itself** —
so the paths came from `__main__.py`'s own env defaults rather than from strings
retyped into a test:

- `CHAT_GATEWAY_STATE_DIR` defaults to `state`, **relative to the working
  directory**. A run from the repo root produced `state/queue/delivery.jsonl`,
  `state/queue/inbox.jsonl`, `state/deliveries/*.jsonl` and
  `state/heartbeats.json` in the worktree, and `git status` listed `?? state/`.
  The journal line carried the whole `OutboundMessage` — `text` and `cards` —
  as `Dispatcher.enqueue` writes it (named, not line-cited: this repo has been
  bitten by drifting line numbers often enough to stop adding new ones).
- ⚠ **`inbox-data/` is NOT a dead entry, and the brief that scoped this row
  believed it was.** It is live at `__main__.py`'s `CHAT_GATEWAY_INBOX_DIR`
  default, documented on `.env.example`'s `CHAT_GATEWAY_INBOX_DIR` line, and
  written by `Inbox._audit` on
  every inbound reply. Removing it as stale would have opened a **second** leak
  path on the **more sensitive side**: that file holds a human's `text`, their
  `sender_email`, and the whole `raw` event. The entry stays, and the block now
  says why so the next reader does not re-derive "looks unused" from a name.

**The fix, and the two judgement calls in it.** One added pattern (`state/`),
one kept (`inbox-data/`), and a comment block naming both env vars and both
writers.

- **Unanchored, not `/state/`.** The working directory is not knowable from
  `.gitignore`; a `state/` one level down leaks exactly as much as one at the
  root, and was verified ignored too. The cost is that a future source package
  named `state` would need `git add -f` — a loud error at the moment someone
  adds it, against a silent irreversible leak. It also matches how every other
  runtime pattern in this file is already written.
- **No `.gitkeep`.** Every writer already does
  `mkdir(parents=True, exist_ok=True)` (`journal.py`, `inbox.py`,
  `delivery.py`, `heartbeat.py`), so a placeholder buys nothing operationally
  and would put the directory back into the worktree it is being kept out of.
  Considered because the row asked for it to be considered, and declined with
  the reason recorded in the file a person editing that block will actually
  read.

**No test was added, deliberately.** The guard would have to shell out to `git
check-ignore`, making the first git-dependent test in an otherwise offline suite
of 246 — a real dependency to take on for a config file. The exercise is in the
PR body instead: the tree was created, `git status` and `git check-ignore -v`
recorded before and after, and then removed. **If that trade looks wrong later,
the follow-up is a test, not a rewrite.**

**Two findings seen and deliberately NOT acted on**, recorded so neither reads
as unnoticed:

- **`inbox-data/*.jsonl` is mode 0644 and is never pruned**, and it holds whole
  inbound events including `raw`. Measured by the concurrent **Architect**
  agent, not by this row, and it belongs to the **CG-65 decision the user has
  not yet taken**. This row ignores the directory; it does not change what the
  directory contains or how it is protected. ⚠ **Both halves of that first
  sentence are now false, and it is left standing as the dated record of what
  this row saw rather than edited into agreement with today:** the mode became
  `0600` in **CG-65** (#52) and the "never pruned" ended in **CG-68**
  (2026-08-02). The decision named here as untaken was taken. (This Builder's own `stat` read
  `777` on every file — an artifact of the dev box's 9p `/mnt/d` mount, which
  does not honour POSIX modes. That is a **measurement-environment artifact,
  not a contradiction** of Architect's 0644.)
- **CG-53 and CG-55 do not declare a `Depends on: CG-67`** even though this
  row's rationale is that it must precede them. Left alone because CG-67 lands
  first, which makes the edge moot, and adding it would mean editing two rows
  this row does not own. Worth adding only if this queue is ever dispatched
  mechanically rather than read top-down by a human.

---

### CG-55 · First NAS deploy and live smoke  📋 queued · **BUILDER-EXECUTED over SSH**

| | |
|---|---|
| **Depends on** | **CG-53** (artifacts), **CG-54** (durability), **CG-75** (the storming write path), **CG-76** (⚠ **added 2026-08-03 — the dependency was NOT recorded here.** The user's 2026-08-02 pre-deploy-blocker decision existed; measured the same day, `grep -n "CG-76"` named it nowhere under either CG-55 entry. aitrader's whole gateway relationship is the dead-man switch, and that switch has **six** measured ways to drop an alert while `/healthz` answers `ok` — three of them needing no fault at all. A first deploy should not ship that), **CG-61** (in the LIVE registry — D1), and ~~⚠ an **external prerequisite in the homelab repo: the drafted tailnet ACL, applied (D2)**~~ — ⏸ **DEFERRED by the user 2026-08-03, paired with a bind-to-LAN design decision this row must honour: see *"Two user decisions, 2026-08-03"* below.** No external prerequisite remains |
| **Touches** | `docs/deploy/nas.md` § *Executed* only. The homelab-side artifacts land in **that** repo |
| **Merge gate** | ⏸ **YES — deploy + secret-handling path** |
| **Spec / plan** | [spec §4.3 + §4.3.1](superpowers/specs/2026-07-31-production-readiness-arc-design.md) · [plan Part C + standing rules](superpowers/plans/2026-07-31-production-readiness-arc.md) |

#### ✅ Two user decisions, 2026-08-03 — read BOTH before building this row

**They are one decision in two halves, not two decisions.** D2's tailnet ACL is
**deferred**; CG-55 **binds to the LAN interface** instead of `0.0.0.0`. The bind
is what makes the deferral sound rather than merely approximately sound, so
neither half reads correctly on its own.

##### 1 · ✅ Bind the published port to the LAN interface, not `0.0.0.0`

**A design decision this row must honour when it is built.** `0.0.0.0` publishes
on *every* interface the host has, and that box has a real `tailscale0`
(spec §0.2.3). Binding the LAN address makes **"LAN-only" true in fact rather
than by convention** — a tailnet peer cannot reach `/healthz` whatever the ACL
says. That is what converts the ACL from a security gate this project carries
debt on into a **remote-access enabler for later**.

⚠ **Nothing is leaking today, and this must not be read as though something is.**
The gateway **has never been deployed** (ADR-0002 §8); **this row is the first
deploy and it is still queued.** This decides what CG-55 *does*, not what some
running instance stops doing.

⚠ **The bind does not replace the ACL — any more than CG-61's registry edit
does.** It removes tailnet reach **to this port**. It says nothing about the rest
of that box or the rest of the tailnet, and `network/tailnet.md`'s own line —
*"the ACL is the only boundary between tailnet peers and other NAS services"* —
stays true and is **not this row's business**.

**What this row must change when built** — recorded so it is not rediscovered on
the box:

| Artifact | Today | Must become |
|---|---|---|
| arc plan **Part C**, the TrueNAS custom-app JSON | `"ports": ["8085:8085"]` — Docker binds `0.0.0.0` | the LAN-address form, `"<LAN-IP>:8085:8085"` |
| arc spec **§7 D2**'s vantage-point table | *"`curl 127.0.0.1:8085/healthz` **on the NAS, over SSH**"* | ⚠ **loopback is NOT bound under a LAN-address publish** — the smoke curl must use the LAN address |

**Already consistent — no change:** plan Part C's smoke item 1 already says
*"`/healthz` on the **LAN address**"*, and the Homepage tile's `siteMonitor` was
always on the LAN IP by homelab convention. That convention is now
**load-bearing** rather than incidental.

**Resolve the address on the box; do not hardcode it out of a document.** The
homelab records `192.168.86.47` as static and *"load-bearing — everything
references `.47`"*, and `reservations.md` also carries an **unconfirmed**
router-side reading that contradicts it. Fail closed on the real interface, the
same way this row already fails closed on the app name.

**Not built here.** If honouring this needs anything beyond the app JSON's port
form, that is **CG-55's** work to build — a bookkeeping row records decisions, it
does not write config.

> **Note — a caveat to revisit later, not a qualification of the decision above.**
> The bind fences the tailnet **while no tailnet subnet route to
> `192.168.86.0/24` exists** — which is the state measured in the homelab repo on
> 2026-08-03: **~2 tailnet devices** (the NAS and Mark's admin device), with
> **appserver still `(planned — Task 2)`**, that being the node whose job is to
> advertise exactly that `/24`. **If that route goes live, a tailnet peer can
> reach the LAN address through it, and the ACL — not the bind — is the boundary
> again.** The drafted ACL already anticipates it: its `tests` block **denies**
> teammates `192.168.86.47:443` and siblings *"via the LAN subnet route"*. **So
> D2's re-trigger is the subnet router** — the same event the user's own trigger
> names, since the remote-access work *is* the subnet router. **Revisit then;
> nothing to do now.**

##### 2 · ⏸ D2's tailnet ACL is DEFERRED — still wanted, no longer gating

**Recorded with its reasoning rather than compressed to a status word.** The ACL
was D2's mitigation and it is **still wanted**; what changed is that it no longer
blocks this deploy.

> **"The first several weeks/months of usage will all be on the local network
> before a remote team member will need access. We don't want to lose tailscale
> accessibility, but should deprioritize it for now."**

**Deferred is not cancelled, and the dependency is struck through rather than
deleted.** A deleted dependency is indistinguishable from one nobody thought
about. Same shape as CG-60's *"merge gate released by the user"* and CG-68's
*"sequencing only"*: the gate is named, the release is dated and attributed, and
the thing gated stays on the map.

**Why the deferral is sound — because of decision 1, not despite the residual.**
The stated reasoning bounds where **we** connect from, not who can reach a
`0.0.0.0`-bound port; a review of the live tailnet state surfaced that gap, and
the user closed it **by changing the bind** rather than by accepting it. With the
LAN bind, *"the first several weeks/months are local"* stops being a description
of intended usage and becomes a property of the socket.

**The exposure that remains has ONE home, and it is not this row.** `/healthz` is
unauthenticated by design, and the reasoning for why `suppressed_opt_out` is a
de-facto activity meter for `aitrader` **by inference** lives in `CLAUDE.md`'s
**CG-12 bullet** (*"Suppressed inbound is COUNTED, never RECORDED"*). **Read it
there — it is deliberately not restated here.** A moving fact with two homes is
this repo's own recorded failure mode (the test count, the space membership).

**What the deferral still accepts, stated rather than glossed:** LAN-local
unauthenticated reach to the counters — which **the ACL never governed anyway**
(spec §7 D2 states that residual in terms), so the ACL was never the control for
it; plus tailnet reach again the moment a subnet route to the LAN exists, per
decision 1's contingency. Measured state of the ACL itself, 2026-08-03: the live
policy is still the **default allow-all** captured 2026-07-28 (a single
`{src:["*"], dst:["*"], ip:["*"]}` grant); the tightening exists only as
`network/tailscale-acl.hujson` on the **unmerged, local-only** branch
`feat/remote-access`; its applier script is **untracked** on `main`; and the draft
**cannot be pasted as-is** — a deliberate `PLACEHOLDER-teammate@example.com`
fails console validation on purpose.

**CG-61's live-registry edit does NOT replace the ACL either, and this row must
not be read as though it does.** Once `aiteam-harness` is also opted out,
`suppressed_opt_out` pools more than one tenant and stops decomposing to
`aitrader` — real, and already recorded in `CLAUDE.md` and in **arc spec §7 D2**,
which says it in terms: ***"Partial, not complete", and "it is not a reason to
skip the ACL."*** Nothing here weakens that. The registry edit narrows
attributability; it does not authenticate the endpoint.

**Re-priced by an event, not a date — and the two candidate events are the same
event.** The user's trigger is *"before a remote team member will need access"*;
decision 1's trigger is the subnet router. Remote access **is** the subnet router.
The draft, the applier and the `tests` block all already exist in the homelab
repo, so landing it then is paste-and-validate, not design.

⚠ **The plan's `C0 · Two prerequisites` still tells a Builder to STOP if the ACL
is not applied.** That instruction predates this decision; it is amended in place
by a dated note at plan **Part C, C0(a)**. Prerequisite **(b) — CG-61 in the live
registry — is unchanged and still fail-closed. Run it.**

**Builder-executed over SSH.** ⚠ **This supersedes the "USER-EXECUTED, CG-15/CG-16
pattern" this row carried until 2026-07-31.** `ssh claude@nas` works with
`BatchMode` and **`sudo` is passwordless — effectively root**, so Builder can both
run and *verify* the deploy instead of handing over instructions and hoping.

⚠ **That capability is the largest thing this arc introduces, and it is bounded
before it is used.** Passwordless root on a box running **10 live stacks** —
including claude-mem's Postgres — is a large blast radius, and `claude` is **not**
in a `docker` group, so every docker call is `sudo docker`, i.e. root: a single
`-v /:/host` would be total host compromise. **The plan's standing rules are not
optional** and are what make this row safe to execute:

- ✅ **read-only probing, unattended**; ✅ **creating the gateway's own app, dirs
  and config**, but only under `/mnt/datapool/apps/chat-gateway/**` and only the
  app name `chat-gateway`.
- 🛑 **another stack** — never stop, restart, exec into or reconfigure any other
  `ix-*` container. 🛑 **Docker global state** — never `system prune`, never a
  daemon restart. 🛑 **pools / TrueNAS writes** outside the gateway's own path.
- 🛑 **`capture.sh`** — it rewrites `nas/compose/*.json` for **all ten** stacks.
  It looks like verification and is a **cross-repo write**; request it, read what
  it produced, do not run it.
- **A stop means stop and report — never work around.**
- **Fail-closed on the app name** immediately before creating it (`app.query`
  must return `[]`). This arc has already been wrong twice about that box.

⚠ **Secrets reaching a live host is the highest-risk step in the whole arc, and
it is hard rule #2 executed rather than described. Secret material travels over
stdin or as a file copy — NEVER as a command-line argument**, because an argument
lands in local history, remote history, and `ps` output on a box other people's
software runs on. **Create restrictive, then fill** (`install -m 0600 /dev/null`,
then `sudo tee` from stdin — `tee` does not change an existing mode), and
**verify by comparing `sha256sum` and reading `stat`, never by `cat`.**

**Deploy-then-document is the homelab convention** — *"the repo documents reality;
it does not declare intent."* Its artifacts (the four-header `nas/services/`
doc, the `SECRETS.template.md` row, the Homepage tile with `siteMonitor` on the
**LAN IP**, the `DASHBOARDS.md` row, `restore-chat-gateway.sh`, and the captured
config) are produced **after** the box is running, from observed facts, in **that
repo**. This row's chat-gateway-side deliverable is the runbook's *Executed*
section filled in with what actually happened — **including anything that
differed from plan.**

**The gate that decides success:** `capture.sh` run, and then the captured JSON
**read by eye**, containing **zero** secret values. ⚠ **Do not accept
`clean. safe to commit.` as the answer** — CG-53 establishes that the script's
suffix rule cannot see this project's secret shapes, so that assurance is worth
nothing here.

Five facts to observe (not boxes to tick): `/healthz` `status` + `reasons`
**verbatim**; one tier-1 webhook send through the deployed instance; tier-2
subscriber alive with `seconds_since_last_poll` moving — **the first evidence
that any host but the dev box can reach Pub/Sub**; a restart proving CG-54's
replay on real hardware; and the capture.

**Must not happen:** a secret in `custom_compose_config` (stop and fix the layout
*before* capturing — a capture commits it to a sibling repo); `network_mode:
host`; any change to an existing NAS app; or reaching for the dead
`iac/chat-gateway-sa.json`.

---

### CG-56 · Inbox delivery semantics: at-most-once → ack-based at-least-once  📋 queued · ✅ APPROVED (D3)

| | |
|---|---|
| **Decision** | **user, 2026-07-31 (D3) — APPROVED.** Opt-in per request; the published contract must keep working **unchanged** for any caller that does not ask for acks |
| **Depends on** | CG-54 |
| **Touches** | `inbox.py`, `service.py`, `client.py`, `README.md`, `docs/integration-guide.md`, `docs/consumers/aitrader.md` (a row citing line numbers), `tests/test_service.py` |
| **Merge gate** | no |
| **Spec / plan** | [spec §4.4](superpowers/specs/2026-07-31-production-readiness-arc-design.md) · [plan Part D](superpowers/plans/2026-07-31-production-readiness-arc.md) |

`Inbox.poll()` **clears on read** (`inbox.py:37-42`) — at-most-once, documented as
such and pinned by `tests/test_service.py:99` (`# poll clears`). If the HTTP
response carrying a batch is lost in flight, those events are **gone from the
queue**, recoverable only by an operator reading the audit JSONL by hand.

Defensible when the inbox was a secondary path and push was primary. **Decision A
makes it jobhunt's only inbound path**, and a tap that silently vanishes is
precisely the failure jobhunt's own J14 doctrine and this gateway's R7 exist to
prevent.

**Recommended:** `GET /v1/inbox` stops clearing when asked not to;
`POST /v1/inbox/ack` removes by id. At-least-once is **what R3 already assumes** —
it demanded a `dedupe_key` and committed jobhunt to idempotent handling precisely
because Pub/Sub is at-least-once. The gateway already speaks this idiom in
`PubSubPuller.pull()` / `.acknowledge()`; this is the same shape one layer out,
not a new concept.

**Keep clear-on-read as the DEFAULT and make ack-mode explicitly opt-in.**
Flipping the default is cleaner but silently turns any non-acking caller's queue
into one that grows forever — the worse failure on a host that now runs
continuously.

**If the user declines:** CG-57 documents at-most-once **explicitly, with this
risk stated in the jobhunt contract**, so jobhunt builds its poller knowing it.
Either answer is workable. What is not workable is jobhunt building a poller
against an unstated guarantee.

⚠ `docs/consumers/aitrader.md`'s comparison row cites `service.py` line numbers
that **will move**. Re-derive them by reading the file; do not adjust by
arithmetic.

---

### CG-57 · jobhunt: `callback_url` → passive inbox polling  📋 queued

| | |
|---|---|
| **Decision** | **user, 2026-07-31** — final, do not re-litigate |
| **Depends on** | **CG-54**; reads better after **CG-56** resolves *either way*, so the contract doc is written once |
| **Touches** | `config/registry.example.yaml`, `docs/consumers/jobhunt.md`, `docs/consumers/jobhunt-handoff.md`, `docs/integration-guide.md` |
| **Merge gate** | no — but **hard rule #6 territory**, narrowing only |
| **Spec / plan** | [spec §4.5](superpowers/specs/2026-07-31-production-readiness-arc-design.md) · [plan Part E](superpowers/plans/2026-07-31-production-readiness-arc.md) |

**Registry and documentation only. No code path is deleted.**
`CallbackForwarder` and its R7 path **stay** — `allow_inbound` + `callback_url`
remains supported for any future always-on tenant, and hard rule #6 names **both**
inbound paths. Do not rip it out.

**jobhunt's receiver was never built** — no route, no listener, no code
(`review_ui.py`'s route table has ten entries and none is it). So this is a
**contract correction before first use**, not a migration: nothing to delete on
either side. **The `8710` vs `8763` port mismatch (CG-42's finding) becomes
moot** — there is no receiver to point at. Do not "fix" the port; delete the
question.

**What `allowed_users` and `unreachable_message` still mean — decided, not left
inferable:**

- **`allowed_users` (R4) is UNCHANGED in force.** It is evaluated at **ingress**,
  in the subscriber's authorization block, before anything is enqueued — which is
  exactly what `/healthz`'s `suppressed_not_authorized` counter already
  describes. An unauthorized tap is still refused in-thread and still never
  reaches any queue, so it never appears in the inbox to be polled. **Only the
  verb changes: "never forwarded" → "never enqueued."**
- **`unreachable_message` (R7) becomes inert for this tenant and is REMOVED from
  its entry** rather than left as decoration. R7's notice fires from callback
  exhaustion; with no callback there is no exhaustion, so the field would read as
  active while never being able to fire. **This repo has corrected that exact
  shape three times** (CG-37, CG-50, CG-52). The **field and R7 stay in the
  schema and the contract** for push-path tenants.
- **What replaces R7's guarantee under polling: nothing at the gateway, and that
  is correct.** The gateway cannot distinguish "jobhunt is asleep" from "jobhunt
  crashed" — both look like nobody polling — and a detector would mean the gateway
  holding an expectation about a consumer's schedule, which is consumer semantics
  and **against hard rule #1**. The gap moves to jobhunt, whose own J14 doctrine
  already demands it. The gateway-side observable is `/healthz` →
  `inbox.pending`, which rises when nobody drains: **operator material, not a
  tenant guarantee.** Write that into the handoff; do not leave it implicit.

**⚠ Record, do not act on, jobhunt's side.** `D:\prj\jobhunt` is **READ ONLY**.
Its R1, R3, R6, R7, R8 and R9 all need revision and **its own project must do
it** — the list is in the plan's E4.

**⚠ A premise worth recording, in the CG-14 tradition.** Decision A's stated
reason is that jobhunt's receiver would live on `marksdevbox`, **which sleeps** —
true of jobhunt's *accepted* topology ADR. But jobhunt has a **newer, proposed**
one (2026-07-30, awaiting sign-off) that would collapse the database, review UI
and receiver onto its **always-on** host, which would falsify that premise within
days. **The decision stands — but on its stronger reason:** *push couples the
gateway to a consumer's deployment topology (address, port, liveness); polling
couples it to nothing.* That survives either topology. Write **that** as the
justification, and the sleeping host as the occasion. A spec whose stated reason
is falsified a week later, with nothing recorded, is how CG-21 happened.

**`docs/consumers/aitrader.md` is checked and left alone** unless its wording
forces otherwise — aitrader's guarantee rests on `allow_inbound: false` locking it
out of *every* path, untouched by narrowing another tenant. **CG-27 already had to
remove a false claim from that file about this mechanism's existence; do not
introduce its mirror image.**

One test must prove the push path **still works**, through the real
`CallbackForwarder` rather than a stub. Its whole job is to prove nothing was
ripped out.

---

### CG-58 · Structured adapter failures and `Retry-After`  📋 queued

| | |
|---|---|
| **Origin** | the production-readiness brief — **both retry paths confirmed to ignore `Retry-After`**, and the reason found to be larger |
| **Depends on** | CG-54 (touches the same `process_due` branch — sequence to avoid a collision) |
| **Touches** | `retry_policy.py` (new), `adapters/webhook.py`, `adapters/chat_api.py`, `delivery.py`, `forwarder.py` |
| **Merge gate** | no — **but it touches `adapters/`: no ⚠ flag may be cleared, added or reworded** |
| **Spec / plan** | [spec §4.6](superpowers/specs/2026-07-31-production-readiness-arc-design.md) · [plan Part F](superpowers/plans/2026-07-31-production-readiness-arc.md) |

Confirmed: `delivery.py`'s `BACKOFF_S = (0, 30, 120, 600, 3600)` and
`forwarder.py`'s `(0, 3, 7)` both ignore `Retry-After`; a 429 is treated as a
generic failure and retried on our schedule, not Google's.

**But the reason is structural, and fixing the reason fixes more than the
symptom.** The adapters do not carry the status anywhere a retry policy can reach
it: `WebhookDeliveryError` and `ChatApiError` render it into a *message string*
and keep no attribute, and `Dispatcher.process_due` catches a bare `Exception`.
(`PubSubError` already carries `.status_code` — it is the model for the others,
and the direction CG-23 and CG-33 already moved this family.)

**The headline defect is not the missing `Retry-After`:**

| | today | should be |
|---|---|---|
| `429` + `Retry-After: 120` | generic failure, **our** schedule | wait what Google asked |
| `503` | generic failure | retry, ladder |
| **`403`** — webhook deleted, app removed from space, key revoked | **burns the full ladder: 30s, 2m, 10m, 1h — over an hour of calls that can never succeed** before reporting `failed` | **permanent; fail on attempt 1** |

That 4xx row is a **current, observable defect in our own logic**, needs no Google
error response to demonstrate, and makes the gateway noisiest exactly when a
credential has been revoked.

**Rules, each with its reason:** non-retryable 4xx is permanent; `Retry-After` is
honoured as **`max(ladder, retry_after)`** — never *shorter*, so a hostile or
buggy `Retry-After: 0` cannot turn a retry into a hot loop against Google;
clamped to a ceiling; and in `forwarder.py` a value beyond that path's short
horizon counts as **exhaustion**, firing R7 — a human tapped a button, and a
tenant asking the gateway to wait an hour has for this purpose failed.

⚠ **`Retry-After` is server-controlled bytes. Parse it to a float and never carry
the raw string into any message, log or attribute.** This is **CG-33's exact
lesson** applied on first use rather than after the fact: `PubSubError` read
`resp.reason_phrase` off the wire and had to be corrected to a local lookup. A new
header read is a new instance of the same hazard, and a test must prove a hostile
value reaches nowhere.

**Preserve the exhausted-ladder log string byte for byte** — existing tests assert
on it. The permanent case gets its own wording rather than one message carrying
two meanings.

⚠ **`send_text`'s documented non-200 asymmetry** (status only, no reason phrase)
is **deliberate** and CG-23 explicitly declined to change it. Add the attributes
without touching the message.

**Say in the PR body, in these words: every branch this touches is one no Google
error response has ever exercised.** The tests drive fakes. That is a stronger
suite, **not** evidence against Google, and it clears nothing. For the current
residue, **link `CLAUDE.md`'s verification ledger — do not restate it.**

---

### CG-59 · Long-run observation, and what a **deployed** `/healthz` needs  📋 queued

| | |
|---|---|
| **Depends on** | **CG-55** — the soak clock starts when it lands |
| **Touches** | `service.py` (`?strict=1`), `docs/deploy/nas.md` (the observation section) |
| **Merge gate** | no for the code; **any ledger change needs explicit hard-rule-#3 sign-off** |
| **Spec / plan** | [spec §4.7](superpowers/specs/2026-07-31-production-readiness-arc-design.md) · [plan Part G](superpowers/plans/2026-07-31-production-readiness-arc.md) |

`CLAUDE.md`'s verification ledger records that **no multi-hour live run has
happened** for `SubscriberLoop`. This row is that run.

**The deployed-only finding.** `service.py:469-471` returns
`status_code=200` **hardcoded**, including when `status` is `degraded`. Correct
for a hand-run gateway — you read the JSON. A real gap for a deployed one,
because Homepage's `siteMonitor` and container health checks judge by **status
code**: the tile is **green while inbound is dead**. That is the claude-mem
hardcoded-health-check failure — the one hard rule #5 exists because of, which hid
11 days of silent capture failure — occurring **one layer up**, at the dashboard,
against an endpoint that is itself scrupulously honest. `/healthz` is not lying;
the dashboard reading it cannot hear it.

**Recommended: add `GET /healthz?strict=1`**, returning **503** when `reasons` is
non-empty and 200 otherwise, with an **identical body**. Additive — no existing
consumer changes — and the Homepage tile points `siteMonitor` at the strict form.
Chosen over flipping the default because the plain form is a published contract
with existing readers, and because a 503 from a *container* health check would
make Docker restart a gateway that is degraded but **working** (one unresolved env
var on a tier-1-only host). Opt-in puts the choice with the reader.

**The soak:** sample `/healthz` for **≥24h, targeting ≥72h**, recording
`seconds_since_last_poll` (**max, not mean** — a mean hides a wedge),
`poll_failures` / `consecutive_poll_failures`, `thread_alive` / `thread_started`,
`events_seen`, `dispatch_errors`, container RSS, journal size **across at least one
compaction**, and `inbox.pending` / `inbox.dropped`.

⚠ **Whether this clears the ledger's `SubscriberLoop` long-run row is a hard rule
#3 question and needs the user's explicit sign-off**, on CG-35's precedent. The row
**presents evidence and proposes**; it does not clear a flag on its own authority.
**A quiet subscription running for three days proves the thread survives; it
proves little about behaviour under load** — say which of those the evidence
reaches.

**Disk growth: measure and propose, do not implement.** The audit JSONL files are
per-app-per-day — invisible on the dev box, a slow leak on a host meant to run
for years. A retention policy on an audit trail whose stated purpose is that
*"nothing is ever silently lost"* is a rule-#5-flavoured decision and **belongs
to the user**.

⚠ **Half of this was overtaken by CG-68 on 2026-08-02, and the brief above is
corrected rather than left to mislead.** It said both directories are *"never
pruned"*, and named the decision as one the user had not taken. Now:

- **`inbox-data/` IS pruned** — 30 days by default, 7 for the gateway's own
  `_unrouted` bucket, `0` disables, via `CHAT_GATEWAY_INBOX_RETENTION_DAYS`.
  The decision this row wanted to hand to the user **was** handed to the user
  and taken (sign-offs A2/A3/A5).
- **`state/deliveries/` is NOT pruned**, and that is a decision rather than an
  omission — titles-only and permanent per ADR-0002 **D7**. CG-68 made it a
  code property as well as a policy: the sweeper refuses to boot if its
  directory overlaps the state dir at all.

**What is left for this row is what it measures BEYOND the window**: whether 30
days is the right number against real volume, and whether `state/deliveries/`
growing forever is acceptable on a host meant to run for years — which D7
decided on content grounds, never on size.

---

## Experiments

CG-15 and CG-16 **ran on 2026-07-29** and are recorded below with their results.
CG-17 and CG-18 remain deferred — and E1 lowered their value, since both probe
limitations of the add-ons runtime this project **left on 2026-07-29**.

> **Their premise weakened further than "lower value", and CG-21 is recording
> that rather than acting on it (2026-07-30).** Both rows were written while
> add-ons was production. It is not: every project that ran it is deleted, so
> neither experiment is *runnable* even if wanted. **Status unchanged — both stay
> `⏸ deferred` and must not be executed.** Whether a deferred item whose runtime
> no longer exists should be closed like CG-14 or kept filed for its
> classic-shaped residue is a **Planner/user call**, not Builder's; the tense
> below is corrected, the decision is not.

### CG-15 · E1 — does a classic Pub/Sub Chat app receive `CARD_CLICKED`?  ✅ RAN 2026-07-29 · **PASSED**

Executed by the user in a throwaway project. **Yes** — natively, with
`action.id` populated and `onChangeAction` firing. Results in "What E1 and E2
settled" above; ADR §11 trigger 1 has fired. Nothing further to build here; the
consequences are tracked as CG-14 (blocked), CG-20 and CG-21.

### CG-16 · E2 — is the add-on toggle reversible?  ✅ RAN 2026-07-29 · **NO**

Answered definitively: the add-on toggle is **create-time only**. Add-on →
classic cannot be toggled on an existing app, so a migration needs a new Chat
app and therefore a new GCP project. ADR D7's parallel-project path was the only
available one, not merely the prudent one.

### CG-17 · E3 — do slash commands reach the topic?  ✖ CLOSED AS OBSOLETE · user decision 2026-07-30

**The premise is unrunnable, and that is why this closes rather than staying
deferred.** E3 asked whether slash commands reach the topic **under the add-ons
bridge**. Production cut over to a classic Chat app on 2026-07-29 and
`chat-gateway-prod` was deleted on 2026-07-30, so there is no add-ons deployment
left to run the experiment on. Running it would require standing up a third
project to measure a runtime this repo no longer targets.

**What was genuinely useful in it is preserved, because it is not the
experiment.** Slash commands land differently on classic — a MESSAGE carrying
`message.slashCommand`, versus add-ons' `appCommandPayload`. So if slash commands
are ever wanted, the normalizer needs **the classic shape**, and that is a new
item with its own justification, not this one resumed. Do not reopen this row to
get at that fact; it is written here.

<details>
<summary>Original deferred text, kept for the record</summary>

Was the bridge's escape hatch. Less interesting now: the escape hatch is the
classic migration, which is proven and **done** (2026-07-29). Keep filed — slash commands
land differently on classic (a MESSAGE carrying `message.slashCommand`, versus
add-ons' `appCommandPayload`) so if they are ever wanted, the normalizer needs
the classic shape, not this one.

</details>

### CG-18 · E4 — does `onChangeAction` work with the topic path as its function?  ✖ CLOSED AS OBSOLETE · user decision 2026-07-30

**Closed for the same reason as CG-17, and its own text already said so.** Its
stated condition was *"only worth running if the add-ons deployment has to be
lived with longer than expected"* — that condition **can no longer be met**. The
add-ons deployment is gone, not merely superseded.

**And the question it existed to answer has been answered by better evidence than
the experiment would have produced.** E4 asked whether select-to-act was
recoverable *under the bridge*. On 2026-07-30 a real classic capture showed a
selection widget's `onChangeAction` firing on a card with **no button at all** —
`action.id='onVerdictChanged'`, populated natively, value harvested into params.
Landed as `tests/fixtures/classic-cardclicked-onchange-event.json` and pinned by
`test_normalize_real_classic_onchange_with_no_button_at_all`. So the two-tap cost
E4 was scoped to price disappeared at migration, and the prose that said
otherwise was corrected by CG-11+CG-20.

An experiment whose question is settled and whose runtime is deleted is not
deferred work. It is history.

<details>
<summary>Original deferred text, kept for the record</summary>

Asked whether select-to-act is recoverable *under the bridge*. E1 answered the
question that actually mattered: `onChangeAction` **fires natively on classic**,
so the two-tap cost disappeared at migration regardless. Its remaining condition
— *"only worth running if the add-ons deployment has to be lived with longer
than expected"* — **can no longer be met**: the add-ons deployment is gone, not
merely superseded.

</details>

---


## Blocked

_(nothing — **CG-9 moved out on 2026-07-30** and has since shipped with CG-22.
Its scope changed as well as its status: the capture that arrived is **classic**,
not add-ons. Read the entry under **Recently shipped** rather than assuming the
old one.)_

---

## In flight

_(nothing — **CG-21 shipped** on 2026-07-30 as reconciliation only, and
**CG-32**, **CG-19**, **CG-23** and **CG-30** before it, with **CG-11 + CG-20**
as one PR before those.

**Four Builders ran concurrently at the peak**, one git worktree each, per the
CG-25 concurrency incident: one worktree per Builder, never a shared working
directory. Two costs of that parallelism are recorded rather than glossed:
queue-row **number collisions** — CG-32 through CG-37 were each claimed as "the
next free number" by a different Builder, and every collision surfaced only at
rebase — and repeated `docs/BUILDER_QUEUE.md` conflicts, resolved by keeping
every item's content and re-applying only the resolver's own row.)_

---

## Recently shipped

### CG-37 · Two `src/` comments still name **add-ons** as the runtime we are deployed on  ✅ shipped 2026-07-30 · [PR #40](https://github.com/mmackelprang/chat-gateway/pull/40)

> **Renumbered from CG-35 on merge, 2026-07-30.** CG-19 had already taken CG-35
> and CG-32 took CG-36 while all three ran in parallel. Queue numbers have no
> allocator; each Builder takes "the next free one" and collisions surface only
> at rebase.

| | |
|---|---|
| **Origin** | filed by Builder 2026-07-30 from **CG-21's** inventory — found, deliberately not fixed |
| **Depends on** | nothing |
| **Touches** | `src/chat_gateway/adapters/pubsub.py`, `src/chat_gateway/service.py` — comments only, no behaviour |
| **Priority** | **appended last, unprioritized.** The user sets order. |

**Shipped as two comments and nothing else.** Both were **re-scoped, not
deleted** — the add-ons statements were *true of add-ons*, so the correction
names the runtime each sentence is about and then says which one we run. The
shipped text, verbatim:

`adapters/pubsub.py` — the last sentence of the topic-as-function paragraph now
ends *"…or action.id is permanently dead THERE"*, followed by:

> THERE means ADD-ONS — not "the runtime we are actually deployed on", which is
> how this sentence read until CG-37. Production cut over to a CLASSIC Chat app
> on 2026-07-29 and classic supplies action.id natively, so everything above
> this line is add-ons history, not a description of what we run. The key stays
> regardless: `_resolve_action_id` checks it FIRST and unconditionally, so a
> card that carries it still resolves through it on either runtime. Not needed
> is not unused, and that sameness is D3's portability payoff (CLAUDE.md).

`service.py` — `ROUTING_TARGET_ENV`:

> …because the two were only ever coincidentally related, and only under ADD-ONS
> at that: topic-as-function made the routing target look like it fell out of
> the subscription. On CLASSIC — production since 2026-07-29 — it is any
> constant, and under an HTTP-endpoint deployment it splits by runtime too: the
> endpoint URL under add-ons, a function name under classic (ADR-0001 D3's
> portability table).

**"Comments only" was PROVEN, not asserted.** `ast.parse` output of both files
is byte-identical to `main`'s — `#` comments are not AST nodes, and a docstring
edit *would* have shown up, so this is a real check and not a tautology. Suite
**202 → 202**, unmoved.

**UAT for a comment-accuracy PR is the accuracy of the sentences**, so each
clause was driven through the real code rather than reasoned about — 6/6:

| Claim in the new text | Measured |
|---|---|
| classic supplies `action.id` natively | real classic capture → `action.id='approve'`, `id_source='google'` |
| under add-ons the native slot was dead — the paragraph's subject | real add-ons capture → `action.id=None`, `id_source=None` |
| `__cg_action__` is checked first and still WINS | beat a live native `'approve'` → `('verdict', 'cg_param')` |
| the same card behaves identically on either runtime (D3) | both runtimes → `'verdict'` |
| the key is POPPED, so no plumbing reaches a tenant | `params` after resolution: `{'jobId': …}` |
| on classic the routing target is unrelated to the subscription | env constant `'handleInteraction'` vs a wholly different resource path |

**Pre-merge review's one MEDIUM was PRE-EXISTING text inside the comment being
corrected, and it was fixed rather than deferred** — recorded because it is the
one place this PR went past its two stale sentences. `service.py`'s
HTTP-endpoint clause read *"under an HTTP-endpoint deployment it is a URL"*,
flat, where ADR-0001 D3's option-C row it cites says *"the endpoint URL
(add-ons) or a function name (classic)"*. Untouched by the first draft — the
diff's removed lines stop at *"and under an"*. It was fixed anyway because the
correction made every **other** clause in that comment carefully runtime-split,
which left this one as the only flat claim in a sentence about exactly that
distinction. One clause; still AST-identical; suite still 202.

**Flags: none cleared, added or reworded.** Neither edited region contains a ⚠
flag — every `⚠` in `pubsub.py` lives in the module docstring, the
`PubSubPuller`/`pull`/`acknowledge` docstrings, `ADDON_ACTION_KEY`'s comment and
`_normalize_addon`'s docstring, all untouched. `CLAUDE.md`'s verification ledger
is untouched and **not restated** anywhere in this PR.

**`CLAUDE.md`'s test-count line was checked and needed nothing** — it already
read 202, which is what the suite measures. It had been stale all day (136, 140,
190 against a moving suite) because parallel Builders kept moving it; this is
the first cycle with only one Builder running, and it was already correct.

**CG-50 filed** from this row's sweep — `pubsub.py`'s module docstring states
CG-10's defect as current (`action.id == ""`) and points at CG-10 as open work.
CG-10 shipped, and the same fixture now yields `None`. A third comment of this
exact family that CG-21's inventory missed; left alone here because it sits
between two ⚠ SHAPE-VERIFIED blocks and this row was scoped to two comments.

<details><summary>The row as filed</summary>

CG-21 reconciled every *document* that still described the add-ons → classic
migration as pending. Two **source comments** say the same stale thing and were
left alone, because CG-21 was a docs-only row and `adapters/` is hard-rule-#3
territory where the flag discipline lives.

| Location | Text | Why it is wrong |
|---|---|---|
| `src/chat_gateway/adapters/pubsub.py:104-105` | *"…or `action.id` is permanently dead under the **runtime we are actually deployed on**."* | The runtime we are actually deployed on is **classic**, where `action.id` arrives natively. The sentence is true of **add-ons**, which production left on 2026-07-29. |
| `src/chat_gateway/service.py:42-44` | *"the two are only coincidentally related **today** — **under a classic deployment** it is any constant"* | Mechanically correct, but it positions classic as the hypothetical alternative when classic **is** production. Milder than the first. |

**Neither is a defect in behaviour** — the guard and the env indirection both do
the right thing, and `TOPIC_PATH_RE` (`pubsub.py:136`) is explicitly written for
the classic runtime already. This is comment tense only.

**Fixing them must not disturb the surrounding reasoning.** The `pubsub.py` block
is the `__cg_action__` rule-#1 justification, which is load-bearing prose; the
correction is that add-ons is where `action.id` was dead, not "the runtime we are
deployed on". **No verification flag is involved and none may be touched.**

</details>

---

### CG-33 · `PubSubError`'s docstring makes a claim about its own reason phrase that is false  ✅ shipped 2026-07-30 · [PR #39](https://github.com/mmackelprang/chat-gateway/pull/39) — **MERGED** (`9daa672`)

**The docstring was made TRUE, not accurate** — `_post` looks the phrase up in
`httpx.codes` now, exactly as CG-23 did in the two sibling adapters. And the
second half, which the row did not contain: **`PubSubError` joined the
`GatewayAuthoredError` set.** Measured through the real `PubSubPuller` over real
TCP, against a stand-in Pub/Sub sending a hostile HTTP/1.1 status line:

| | before | after |
|---|---|---|
| `exc.reason` | `Forbidden key=FAKEKEYVALUE&token=FAKETOKENVALUE` | `Forbidden` |
| `str(PubSubError)` | `pubsub pull failed: HTTP 403 Forbidden key=FAKEKEYVALUE&token=FAKETOKENVALUE` | `pubsub pull failed: HTTP 403 Forbidden` |
| `describe_exception` | `PubSubError` (type only — it was unmarked) | `PubSubError: pubsub pull failed: HTTP 403 Forbidden` |

**Severity is exactly what the row said, and UAT confirmed it rather than
inflating it.** A real `SubscriberLoop` thread polling a 403 through real
uvicorn, checked at `/healthz`, in its `reasons` prose and on the gateway
console, leaked **nothing before the fix either** — `last_poll_error` was
`PubSubError HTTP 403` on both sides. The wire bytes lived in `str(exc)` and
`.reason`, which no consumer renders. What was dangerous was the **docstring**,
telling the next person the value was safe to print.

**Which makes the ordering of the two halves load-bearing, and it was
measured as a counterfactual:** with the marker applied but `_post` still
reading the wire, `describe_exception` returns
`PubSubError: pubsub pull failed: HTTP 403 Forbidden key=FAKEKEYVALUE&token=FAKETOKENVALUE`.
Marking a class is what makes its message printable, so the lookup must never be
split from the marker. They ship in one commit.

**The allowlist decision, which the dispatch reserved for Builder.** Admit it —
and the reason is not symmetry with its two siblings, though it is now
structurally identical to them. `test_every_marked_message_interpolates_only_names_and_statuses`
reads the construction sites of **marked classes only**. Left out, `PubSubError`'s
raise site would sit outside that guard forever and this fix would rest on one
behavioural test, where its siblings' identical CG-23 fix is *also*
machine-checked. **Joining the set is how a class's raise sites get enrolled in
the guard**, and that is what the marker buys. The fail-closed objection — every
addition widens what may be printed — is real and is answered by the same guard:
membership is checked, not promised.

**The honest cost, recorded rather than glossed.** `SubscriberLoop._run` gave
**two independent reasons** not to unify `/healthz`'s `last_poll_error` onto
`describe_exception`. CG-33 **removes one**: the helper no longer drops the HTTP
status, because a marked `PubSubError` prints in full. The survivor is
sufficient alone — `last_poll_error` is an unauthenticated `/healthz` field
whose exact string is pinned in `test_adapters.py` and `test_service.py` and
which is interpolated into a `reasons` line — and the comment and its test now
stand on that one and say plainly which one went.

**Teaching the guard the second message shape was the real work.** The guard
assumed a marked class takes its finished message as its single constructor
argument (`ChatApiError(f"...")`). `PubSubError(verb, status_code, reason)`
builds its f-string inside `__init__`, so the literal text is in the class and
the values are chosen at a call site three frames away; reading either half
alone reads nothing. It reads both now. `verb` is a bare parameter, and rather
than approve the bare NAME — a hole, since a twice-bound `verb = resp.text`
resolves to nothing and would then match — a new `_literal_parameters` proves it
constant at every in-package call.

**Pre-merge review's one caveat was enforced, not documented.** That proof is
only as wide as the scan, and the scan is `src/chat_gateway/` — which is "every
call" for an underscore-private function and nothing like it for a public one,
whose callers live in consumer code. Restricted to private names, pinned by a
test, because that branch has no observable effect on the real tree and nothing
else would catch its removal.

**Nine mutations, nine caught** — each applied to a clean tree and run against
the full suite:

| | reverted | failures |
|---|---|---|
| M1 | `_post` back to `resp.reason_phrase` — the defect | 2 |
| M2 | `PubSubError(..., resp.text)` | 3 |
| M3 | construct-then-raise hiding the wire value | 2 |
| M4 | a `_post` caller stops passing a literal verb | 2 |
| M5 | the marker removed from `PubSubError` | 3 |
| M6 | `__init__` interpolates something not from its parameters | 3 |
| M7 | `_run` unified onto `describe_exception` | 3 |
| M8 | the privacy restriction removed from `_literal_parameters` | 1 |
| M9 | **control** — `ChatApiError` smuggles `resp.text` | 3 |

M9 is the one that matters beyond this row: the shape-1 path was rewritten in
place, and M9 proves the three pre-existing marked classes did not get weaker
for it.

**Flags: none cleared, added or reworded.** `_post`'s non-200 branch is still
unexercised against Google — every measurement above drives a stand-in server,
not Google — and this changed what that branch *says*, not what is verified.
`CLAUDE.md`'s verification ledger is untouched and not restated anywhere.
Suite **201 → 202** — **190 → 191** on the `main` this branch was cut from, and
re-measured rather than re-asserted after rebasing onto CG-26, whose new scan
covers `tests/**/*.py` and `docs/**/*.md` and therefore reads this row and this
PR's test file. Both pass it unchanged; the fake values here were written to
the convention CG-26 was extending.

**Merge gate: user-imposed at dispatch.** The row declared none; the user added
one because this is the secret-handling path and the leak is now measured — the
same rule and the same class of value that gated CG-23 and CG-34. PR opened, not
merged — **and then merged 2026-07-30 as `9daa672` once the gate was released.**
(Corrected by CG-37, which found this row and the banner still saying "OPEN"
while `main` already carried the commit.)

<details><summary>The row as filed</summary>

| | |
|---|---|
| **Rule** | **hard rule #2** |
| **Origin** | filed by Builder 2026-07-30 from **CG-23's** pre-merge review — **verified against httpx's source, not reasoned** |
| **Depends on** | nothing |
| **Touches** | `src/chat_gateway/adapters/pubsub.py` — one docstring, and possibly one argument |
| **Priority** | **appended last, unprioritized.** The user sets order. |

`PubSubError`'s docstring (`adapters/pubsub.py:157`) says:

> The reason phrase is a fixed HTTP string and carries nothing.

**It is not a fixed string.** `httpx.Response.reason_phrase` returns
`extensions["reason_phrase"]` when present — which httpcore populates from the
literal **HTTP/1.1 status line** — and falls back to the local table only when
the server sent none. `_post` (`pubsub.py:228`) passes that wire value straight
into the exception:

```python
raise PubSubError(verb, resp.status_code, resp.reason_phrase)
```

So `PubSubError.reason` and its `str()` carry **server-controlled bytes**, and
the docstring asserts the opposite. Verified on httpx 0.28.1: a response built
with `extensions={"reason_phrase": b"Attacker Controlled"}` returns exactly that
from `.reason_phrase`, while `httpx.codes.get_reason_phrase(403)` — a pure local
enum lookup — returns `"Forbidden"`.

**Severity today is genuinely LOW, and saying so is not a hedge:** every current
consumer of `PubSubError` was traced, and none renders `str(exc)`.
`SubscriberLoop._run` (`pubsub.py:879-889`) and `/healthz`'s `last_poll_error`
use `type(exc).__name__` + `exc.status_code` only. Nothing exposes the smuggled
text anywhere. What is wrong is the **docstring**, which tells the next person
the value is safe to render — and the next person who prints `str(exc)` in a log
line is doing what the docstring says is fine.

**CG-23 fixed the two sibling adapters this way** (`httpx.codes.get_reason_phrase(status)`,
pinned by `test_reason_phrase_is_looked_up_locally_not_read_off_the_wire`) and
deliberately did **not** touch `pubsub.py` — a concurrent Builder owned that file.
Either make the docstring true by switching to the local lookup, or make it
accurate by saying the phrase comes off the wire. Not both, and not neither.

</details>

---

### CG-42 · `0s / 5s / 15s` is stated as a timetable in two docs; a slow attempt stretches it  ✅ shipped 2026-07-30 · [PR #37](https://github.com/mmackelprang/chat-gateway/pull/37)

| | |
|---|---|
| **Origin** | filed by Builder 2026-07-30 from **CG-31's** own UAT — **measured on a real `SubscriberLoop`, not reasoned** |
| **Depends on** | nothing (CG-31 shipped the `src/` half and already carries the caveat) |
| **Touches** | `docs/consumers/jobhunt-handoff.md` §7, `docs/consumers/jobhunt.md` R7 |
| **Priority** | **appended last, unprioritized.** The user sets order. |

**Shipped as a four-row measured table replacing one worked example.** Every row
was re-measured first-hand in this PR through the real `CallbackForwarder` over
real `httpx` — including the two CG-31 had already taken, because a number two
documents got wrong is worth a second independent measurement rather than a
citation. The bottom two ran on a real `SubscriberLoop` thread at its real 5.0s
`interval_seconds`:

| How the callback fails | attempts land at |
|---|---|
| fails faster than the next gap, `process_due()` called freely | 0.3 / 3.3 / 10.4 → **0s / 3s / 10s**, the contract |
| duration cannot count — exact 5s ticks of a fake clock | **0s / 5s / 15s** — where the old figure came from |
| refuses fast — `ConnectError` to a closed port (~2s here) | **0.0 / 7.1 / 14.1**, notice at 16.2s — CG-31's figure, reproduced |
| hangs to the forwarder's production 10s client timeout | **0.0 / 15.0 / 30.1**, notice at **40.1s** |

**The bottom row is the one the row was filed for, and it was a prediction until
now.** CG-42's body said a hang "would push it far further"; measured, it is
**40 seconds** of silence for the person who tapped, against a documented 15.
That is why the correction is stated as *`0s / 5s / 15s` is systematically
optimistic in the exhaustion case* rather than as a numeric fix — exhaustion is
the only route to the in-thread notice, and an unreachable host times out rather
than refusing, so every attempt in the one scenario these sections describe is
slow by definition.

**The rule was already right and is kept verbatim** — *"an attempt fires on the
first poll tick at or after its due time, never earlier"* predicts all four rows.
What changed is the illustration beneath it. `jobhunt.md` R7 links to §7 rather
than restating it, and §4's existing 10s-client-timeout warning now points there
too. `BACKOFF_S`, the retry logic and the poll interval are untouched; suite
unchanged at **190**; no ⚠ flag cleared, added or reworded, and `CLAUDE.md`'s
verification ledger is linked-not-restated (nothing here was measured against
Google — it is loop arithmetic against a local port, and the docs say so).

**Two findings, neither fixed here — both outside this row's file boundary while
three Builders ran concurrently:**
- `docs/integration-guide.md`, the interaction rules-of-the-road paragraph —
  *"if your callback is down, retries span ~10s"* is the same defect one audience
  up: `~10s` is the contract, not what a user waits. **CG-36's file**, and a
  different paragraph from the `/v1/notify` one CG-36 shipped; reported, not
  touched. (Line number deliberately omitted — it moved from 109 to 114 under
  CG-36's merge while this PR was open.)
- `docs/consumers/jobhunt.md`'s registry snippet carries a real email address as
  an example value (`allowed_users`). In this row's own file, but **CG-26's docs
  scrub** — left alone rather than conflict with it.
- Checked and **correct, no row needed**: `docs/consumers/aitrader.md` §6 reads
  the *dispatcher's* `BACKOFF_S = (0, 30, 120, 600, 3600)` as gaps and sums them
  to ~1h13m. Same constant name, different constant, and it does not repeat this
  mistake — the 1.0s dispatcher wake makes the rounding negligible at that scale.

Both docs say the three callback attempts land at **0s / 5s / 15s** in the
running gateway. CG-31 reproduced that — but only with a **fake clock**, calling
`process_due()` on exact 5s ticks. Driving a **real `SubscriberLoop`** at its
real 5.0s interval against a genuinely closed port measured **0s / 7s / 14s**.

**Not a contradiction of the model — a missing variable in the illustration.**
`_run` (`adapters/pubsub.py:871-878`) calls `poll_once()`, *then*
`forwarder.process_due()`, *then* waits the interval. So a poll cycle is **the
attempt's own duration plus the interval**, not the interval. A `ConnectError`
to a closed localhost port costs ~2s on the Windows dev box, so every subsequent
tick shifted by that. jobhunt-handoff §7's own rule — *"an attempt fires on the
first poll tick at or after its due time, never earlier"* — predicts 0/7/14
correctly; it is the worked example beneath it that reads as a timetable.

**Why this matters for R7 specifically and is not pedantry.** The number an
operator actually cares about is when the *in-thread failure notice* reaches the
person who tapped, and the exhaustion case is exactly the case where every
attempt is slow — an unreachable callback is the only way to get there. So the
illustrated 15s is systematically optimistic in the one scenario it describes.
A callback that hangs to a 10s client timeout rather than refusing fast would
push it far further.

**Deliberately not fixed inside CG-31.** That row is `src/`-scoped, these two
docs were corrected by CG-11+CG-20 and are the alignment target — editing them
from a `src/` row would have meant contradicting the thing being aligned to
while a second Builder had docs open. CG-31's docstring states the caveat and
links here; the fix is to add the same qualification to §7's worked example.

---

### CG-26 · The fixture guard's remaining rules have never been proven to fire  ✅ shipped 2026-07-30 · [PR #38](https://github.com/mmackelprang/chat-gateway/pull/38)

`test_fixtures_scrubbed.py` carried four rule families and a negative test for
**one**. Its own docstring makes the argument — *"A guard that has never failed is
a guard nobody has tested"* — and then applied it once.

**The row's per-rule table was verified against the file rather than trusted, and
it was incomplete.** It named three unproven rules; `PII` has a **fourth** arm,
the author-identity literal, with no test either. All four now have a case that
proves the rule **fires** and a case that proves it **discriminates** — the
`(?!0)` lookahead admitting `users/000…001`, the `PLACEHOLDER` clearing a
`BEGIN … PRIVATE KEY` value. Two rules are isolated deliberately: the PEM case
sits under an *innocent* key so only the value arm can fire, and the author-literal
case uses a display name so the email rule cannot be what fires. `fixture_files()`'s
must-not-pass-vacuously assertion is exercised by monkeypatching the module global,
so it tests the real default path rather than a copy.

**The widened half is the one that mattered.** Both PII incidents landed *outside*
`tests/fixtures/`, so every rule above was aimed at the wrong directory. The scan
now also reads `docs/**/*.md`, `tests/**/*.py`, `tests/**/*.md` and root-level
`*.md` — **including itself**. That is the entire finding of incident 2: the real
Workspace tenant ids sat in this guard's own negative case, on `main`, since CG-3,
and nothing had ever read the guard. Both locations scrubbed forward; **no history
rewrite**, per the user's decision. The branch **adds 0 lines** carrying the real
identifier and removes 3.

**The rule set is deliberately not a naive port, and the omissions are the
documentation deliverable.** A false-positive guard is a deleted guard, so each
non-port is recorded as *review's* obligation with its measurement:

| Rule | Ported? | Measured reason |
|---|---|---|
| `EMAIL` / `EXAMPLE_DOMAIN` | **no** | would have caught **neither** incident — incident 1's leaked address is the author's own, which the guard is *required* to tolerate; incident 2 had no email. Of 81 addresses in the scanned trees, the only ones it would flag are this guard's own bait |
| `SUSPECT_KEY` / `SUSPECT_VALUE` | **narrowed** | they key off a JSON path and prose has none; a naive port scores **62 hits, all false positives**. `DOC_URL_CRED` replaces them with the shape that leaks — a credential in a URL query or fragment |
| `googleusercontent.com` | **narrowed** | blunt inside a fixture, URL-scoped in prose: 14 prose and regex-source mentions exist, so a blunt port was a 14-hit storm on day one |
| display names, space/message/thread ids | **no** | unchanged, but now stated as a review *obligation* rather than left as an absence — which the row asked for |

**"Real-looking" vs "obviously fake" is decided by the value alone** — an explicit
fake-marker word, or failing a machine-generated test (< 24 chars after `%XX`
escapes are stripped, or fewer than 3 of lower/upper/digit). **Annotation-based
exemptions were considered and rejected**: they would have to be added to
`tests/test_adapters.py` (CG-23's) and `tests/test_log_redaction.py` (CG-34's), so
the guard has to tolerate `SECRETKEYVALUE` / `SECRETTOKENVALUE` **by design**. It
does — and since CG-34 merged mid-cycle, that file is now *inside* the scanned
trees, so the tolerance is proven by the shipped test on every run rather than by a
side check.

**UAT reconstructed incident 1** — the plan draft that hardcoded a live
capability-URL bearer token — which had never been tested against the guard. It
caught 5 of 7 leaked classes and **missed a `domainId` in a markdown table cell**,
which the row explicitly required. `DOC_TENANT_TABLE` added, requiring a
backtick-delimited cell: without that requirement it captures `Path` out of the
`DEC-6` row and is itself a false positive. Re-run: **6 findings became 8**. The
two remaining misses are display names and emails — the two classes documented as
review's. UAT also found **root-level `CLAUDE.md` unscanned**, this repo's
most-edited public document; now covered, and it scanned clean, so the widening
cost nothing.

**Pre-merge review found the false-positive class the row warned about.**
`DOC_TENANT_ASSIGN` had no left word boundary, so it matched `customer`/`domainId`
as a *suffix of any identifier* — it had already fired twice on this PR's own
source and been worked around by **renaming the variable**. Fixed with `(?<!\w)`;
the prose that documented the workaround was corrected, because a rename is not a
fix. **Five wrong counts** in the new prose were found and re-measured against the
tree — four by review, a fifth (64 vs a measured 62) afterwards. The email bullet
now self-checks against its own stated total.

**One convention holds it up: negative-case bait is composed at runtime, never
inlined**, so the file carries no literal its own scan can match. Inline one and
the file fails its own scan — which is the feature, and is pinned by a test rather
than asserted in a comment.

Suite **190 → 201**. **No ⚠ flag cleared, added or reworded**; `CLAUDE.md`'s
verification ledger is untouched and not restated.

**Left for someone else:** `CLAUDE.md`'s test-count line is stale at 190 — a
standing collision point while parallel Builders are active. And **CG-42's shipped
row is stranded in the `## Queue` section** rather than under `## Recently
shipped`; it is marked ✅ so the protocol still skips it, but it belongs to that
item's author to move.

---

### CG-36 · `integration-guide.md` stated the dedupe counter unconditionally  ✅ shipped 2026-07-30 · [PR #36](https://github.com/mmackelprang/chat-gateway/pull/36)

One clause and a link, in one paragraph. `docs/integration-guide.md`'s `/v1/notify`
summary said the collapsed count *"rides on the next delivery (`×N since last
notice`)"* full stop; since CG-32 it degrades when an `info` payload leaves no room.
It now reads *"— **when there is room for it.**"* plus two sentences of *why* and
*where*, and links `docs/consumers/aitrader.md` §11 for the rest.

**The row's real content was the SHAPE of the fix, and it was honoured: the
degradation ladder is not reproduced in the guide.** The paragraph carries only
what does not change — that the counter yields, that hard rule #1 is why it is the
counter and never the app's body that gives, and that the count is in the delivery
log regardless. `" (×N)"` and the ordering of the fallbacks stay in §11, which owns
them. So a future change to the ladder or to the room calculus cannot make this
paragraph wrong: **the drift surface is zero, not merely smaller.** That is the
standing discipline `CLAUDE.md` states about the verification ledger, and it is not
theoretical here — the "adapters' error branches" shorthand has been written and
corrected **three** times in this repo, and CG-32's own docs pass filed this row
rather than fix it in passing for the same reason.

**A general-audience summary is not a guarantee a consumer builds against.** That
distinction is what makes "link" the right answer rather than "copy the precise
version here".

**UAT was the link, because the link is the only thing in the PR that can break** —
and it was measured at both ends against GitHub's own renderer rather than reasoned
about. The paragraph POSTed to the `/markdown` API emits exactly one
`href="consumers/aitrader.md#11-sharp-edges-and-accepted-limitations"`, which
settles the live question of whether the newline inside the link *text* splits it
(it does not); and the live-rendered `aitrader.md` on `main` carries
`user-content-11-sharp-edges-and-accepted-limitations`, so the anchor exists rather
than being a slug derived correctly by luck.

Pre-merge review returned **no HIGH and no MEDIUM**, having checked each claim
against `notifications.py` as well as §5/§11 — `room` is derived from the app's own
strings and the counter returns `""` before it will shorten them, and card
severities cannot overflow at all, which is why the clause is `info`-scoped. One
LOW taken (gerund, matching the two sibling statements of this behaviour). Docs
only: suite **190**, unmoved; adds and removes no test; no ⚠ flag cleared, added or
reworded; no `CLAUDE.md` change, because CG-32 already recorded the behaviour.

Swept for the same drift elsewhere and found **none** — §5 already points at §11,
`notifications.py`'s docstrings are correct, and `README.md`'s *"dedupe windows with
occurrence counters"* makes no claim about the counter always riding. Nothing to
hand to the concurrent CG-26 / CG-33 / CG-42 Builders.

### CG-29 · `poll_once`'s type-name-only print swallowed the detail CG-25 created  ✅ shipped 2026-07-30 · [PR #35](https://github.com/mmackelprang/chat-gateway/pull/35)

`SubscriberLoop.poll_once` printed `type(exc).__name__` and discarded the
message, so CG-25's typed transport error arrived at the operator's console
indistinguishable from a non-200. Measured on the real jobhunt R4 chain
(`reply_fn = ChatApiAdapter.send_text`, as `__main__.py` wires it) over **real
TCP** — a genuinely closed port for the transport branch, a real HTTP server
answering 403 for the other — not through MockTransport:

| Failure | Before (main @ `724124c`) | After |
|---|---|---|
| transport (closed port) | `ChatApiError` | `ChatApiError: in-thread reply failed: ConnectError` |
| non-200 (real 403) | `ChatApiError` | `ChatApiError: in-thread reply failed: HTTP 403` |
| `google.auth`-shaped refresh failure | `RefreshError` | `RefreshError` — unchanged |
| pydantic `ValidationError` (capability URL) | `ValidationError` | `ValidationError` — unchanged |

**The design call the row reserved for Planner was delegated to Builder at
dispatch**, with the considerations named there (are the gateway's own types now
safe to render; should foreign ones stay type-only; does the discrimination
belong at the raise site or the print site; prefer the shape that fails safe).
Recorded because the row still reads *"Planner's call, not Builder's"* and
pre-merge review correctly flagged the mismatch.

**The answer is an ALLOWLIST, and the reason is asymmetry, not taste.** A
denylist of known-unsafe types fails OPEN — the next exception class nobody
anticipated prints in full, once, and a webhook URL has no rotate-in-place. An
allowlist fails CLOSED — an unfamiliar exception prints a bare type name, which
is exactly what an operator had before. Same reasoning CG-34 applied to
redaction by position.

`src/chat_gateway/errors.py` holds the marker `GatewayAuthoredError` and
`describe_exception`. It lives in **core**, not an adapter, so `pubsub.py` reads
it without importing `chat_api.py` — the constraint the row named, and the same
reason `UNROUTED` is core-owned (hard rule #3). The marker is mixed in *beside*
the concrete builtin, so `except RuntimeError` / `except ValueError` handlers
are untouched.

**`PubSubError` is deliberately NOT marked, and that exclusion is the load-bearing
result.** `_post` passes `resp.reason_phrase`; httpcore populates it from the
literal HTTP status line, so its `str()` carries server-controlled bytes.
Measured through the real `PubSubPuller`, not inferred. Its own docstring claims
the opposite — that is **CG-33**, still queued — and admitting it here would have
done precisely what that row predicts: *"the next person who prints `str(exc)`
in a log line is doing what the docstring says is fine."* A test pins the
exclusion **and the measurement that justifies it**, so CG-33's author gets a red
test and an explicit decision rather than an inherited assumption.

`SubscriberLoop._run` keeps its own `type + HTTP status` format and the file now
says why in two independent reasons, so it is not "unified" later: `PubSubError`
is unmarked, so the helper would drop the HTTP status — the one actionable fact
in a poll failure — and `last_poll_error` is published at **unauthenticated**
`/healthz`, whose field format is a surface, not a log line. Its exact string is
already pinned in `test_adapters.py` and `test_service.py`.

**The safety claim is a test, not a comment**, as the row's open question
implies: printing these messages is only safe while the constructors stay
names-and-statuses-only. A structural guard reads every **construction site** of
every marked class across `src/` and checks each interpolated expression against
an allowlist, resolving single-assignment locals so
`httpx.codes.get_reason_phrase(...)` (a local table) is distinguishable from
`resp.reason_phrase` (the wire).

**Pre-merge review found two real bypasses of that guard, both fixed before
merge**, and both are now mutation-tested:

- **construct-then-raise.** The guard matched `raise <Class>(...)` nodes, so
  `err = ChatApiError(f"...{resp.text}")` / `raise err` was never inspected —
  the raise's `.exc` is a bare Name. It reads construction sites now.
- **subclassing.** `describe_exception` asks `isinstance`, which is MRO-aware,
  so `class ChatApiTimeoutError(ChatApiError)` was marked while the membership
  test — looking for a literal `GatewayAuthoredError` base — reported the set
  unchanged. Membership is a fixed point over the inheritance graph now.

Two more from the same review: expressions compare by **parsed AST** rather than
source text with parens stripped (no collisions, and both sides parse on the
same interpreter, so `ast`'s cross-version formatting cancels at
`requires-python = ">=3.10"`), and `_single_assignments` no longer descends into
nested functions, lambdas or comprehensions.

**Nine mutations, each caught by the test that claims it:**

| | reverted | result |
|---|---|---|
| M1 | the `poll_once` print — the defect itself | 3 failed |
| M2 | the marker on `ChatApiError` | 4 failed |
| M3 | `describe_exception` → a denylist | 5 failed |
| M4 | `resp.text` smuggled into a marked message | 3 failed |
| M5 | message hidden behind a local variable | **1 failed — the guard alone** |
| M6 | `PubSubError` admitted to the set | 3 failed |
| M7 | `_run` unified onto the helper | 3 failed |
| M8 | construct-then-raise with `resp.text` | 3 failed |
| M9 | subclass a marked class and leak from it | 6 failed |

M5 is the guard's whole justification: the message is byte-identical, so no
behavioural test can see it, and the next edit to that local is unguarded.

**Flag discipline: nothing cleared, added or reworded.** `poll_once`'s error
paths are still unexercised against Google; this changed what they PRINT, not
what is verified. The `CLAUDE.md` verification ledger was **not** restated
anywhere — the new entry links to it.

**Rebased onto `origin/main` after CG-34 and CG-31 merged**, and re-measured
rather than re-asserted: the suite, all nine mutations and the four real-TCP
console lines were re-run on the rebased tree and are unchanged. CG-34's
`log_redaction` filter is orthogonal — it redacts `httpx`'s own `logging`
records; these lines are `print`, and the allowlist means foreign text never
reaches them in the first place, so there is no second mechanism here. The one
merge conflict was an import block in `webhook.py`; both imports kept.
`CLAUDE.md`'s test count, which CG-31's row flagged as stale again, is corrected
here.

Docs: `docs/consumers/jobhunt-handoff.md` had documented this exact console line
as *"type name only — `ChatApiError`"*, which is the one audience doc the change
falsifies; it now shows both lines and keeps the type-only rule stated for
everything else. `docs/integration-guide.md`'s mention was checked and needed
nothing — it describes the `dispatch_errors` counter, not the printed format.
`CLAUDE.md`'s test count was **stale at 140** (main was already 151) and is
corrected to **163**.

Suite **178 → 190**. No ⚠ flag touched.
### CG-31 · `forwarder.py`'s docstring named the retry **gaps** as if they were attempt times  ✅ shipped 2026-07-30 · [PR #34](https://github.com/mmackelprang/chat-gateway/pull/34)

**Comments only, in one file, and that is the whole PR.** The module docstring
said retries were *"short and latency-shaped (0s/3s/7s)"*, which reads as a
schedule of when the three attempts land. `BACKOFF_S = (0, 3, 7)` is a sequence
of **gaps**. Both numbers now appear, because they are two different facts:

| | |
|---|---|
| **0s / 3s / 10s** | the forwarder's own contract, `process_due()` called freely |
| **0s / 5s / 15s** | what an operator observes — `process_due()` runs only after a successful poll (`adapters/pubsub.py:871-878`) and `SubscriberLoop`'s default `interval_seconds` is `5.0`, so each due time rounds up to the next tick |

**Re-measured, not restated.** Both figures were reproduced in this PR's UAT by
driving the real `CallbackForwarder` over real `httpx` against a genuinely
closed TCP port. The third attempt lands at 15s rather than 12s because
`process_due()` captures `now` at the **top** of the call, so the last gap
compounds on the poll tick attempt 2 actually ran on, not on its due time.

**A third measurement is why the shipped wording is hedged.** A **real**
`SubscriberLoop` at its real 5.0s interval gave **0s / 7s / 14s** — a poll cycle
is the attempt's own duration *plus* the interval, and a `ConnectError` to a
closed localhost port costs ~2s here. Consistent with the model, but it means
0/5/15 is an observation under a fast-failing attempt, not a timetable. The
docstring says so; **CG-42 filed** for the same qualification in the two docs
that carry the worked example.

**Aligned with `docs/consumers/jobhunt-handoff.md` §7 and `docs/consumers/jobhunt.md`
R7, which CG-11+CG-20 had already corrected** — that PR was docs-only and could
not reach `src/`, which is the entire reason this row existed. The docstring
links to §7 rather than re-summarizing it.

A two-line comment also went on `BACKOFF_S` itself — beyond the row's stated
"one docstring line", and deliberately: the constant is where a reader lands
when they grep, and it is the thing that was misread. `BACKOFF_S`'s values, the
retry logic and the poll interval are **untouched**. No ⚠ flag cleared, added or
reworded. The suite is unchanged by this PR — **151** on the `main` this branch
was cut from, **178** after rebasing onto CG-34; it adds and removes no test,
and a docstring is not assertable. A test pinning 0/3/10 was considered and
rejected: it would pin `BACKOFF_S`'s values, which are a tunable this row was
forbidden to touch.

### CG-34 · `httpx` logs the whole webhook URL — key and token — at INFO  ✅ shipped 2026-07-30 · [PR #33](https://github.com/mmackelprang/chat-gateway/pull/33)

`httpx` logs one line per request through its own module-level logger, carrying
the full request URL. For a tier-1 send that URL embeds `key` **and** `token` —
it IS a bearer credential for posting as that identity, with no rotate-in-place.
Nothing in this repo put it there and no gateway code had to be wrong for it to
happen.

**The mechanism: redact, do not silence.** A `logging.Filter` on the `httpx`
logger (`src/chat_gateway/log_redaction.py`) rewrites every URL in the record so
query values, fragment values and any userinfo password become `REDACTED`, and
leaves method, scheme, host, path, status and the parameter NAMES alone:

```
HTTP Request: POST http://127.0.0.1:62996/v1/spaces/AAA/messages
              ?key=REDACTED&token=REDACTED&messageReplyOption=REDACTED "HTTP/1.0 200 OK"
```

**Why the row's three options all lost, stated because the row asked.**
`setLevel(WARNING)` is cheaper and works, but it silently fights an operator who
deliberately asked for DEBUG — they get no httpx logs and no explanation — and it
costs more than the problem requires, because only the **webhook** URL carries a
credential; a `chat_api` URL carries a space id and a `pubsub` URL a subscription
name, both non-secret and both useful. A per-client suppression was checked in
the installed source rather than assumed, and **is not available**: the log call
lives in `httpx._client._send_single_request` against a module-level
`logging.getLogger("httpx")` (`_client.py:117,1025`), so a `Client` instance has
no logger of its own to configure — reaching it would mean overriding a private
method. Documenting it as an operator
constraint fails on the row's own argument — a rule that depends on nobody ever
adding `basicConfig` is not enforced. A note in the deploy doc is still worth
having *alongside* the code, and is left to CG-21, which owns that file.

**Values, not named parameters.** Redacting `key` and `token` by name would be a
denylist of secrets, and the parameter nobody has thought of yet is the one that
leaks. The measured cost of taking every value is nil — the only query parameter
the gateway itself sends is `messageReplyOption`, our own constant — and the
generality is load-bearing rather than tidy, because the same logger carries
`forwarder.py`'s POSTs to tenant `callback_url`s, whose shape the gateway does
not control. The filter never needs to know what the secret IS: it holds no env
var, reads no registry, compares against nothing, and redacts by POSITION.

**Measured against the real gateway, under the dangerous config**
(`logging.basicConfig(level=DEBUG)` in a wrapper around the real entrypoint, real
uvicorn, real TCP to a stand-in Google, one `/v1/messages` and one `/v1/notify`):

| Artifact | before | after |
|---|---|---|
| gateway console | `key`+`token`, **twice per run** | clean |
| `GET /v1/deliveries` | clean | clean |
| the JSONL audit file on disk | clean | clean |
| `/healthz` | clean | clean |

Both requests returned **200 / 202**. That is the point of the item: unlike
CG-23's error-body leak this fires on the **happy path**, so it would have
published the credential on every notification the gateway ever sent. The run
also settles two things that were otherwise assumptions — uvicorn's own
`dictConfig`, applied at `run()` *after* the guard is armed, does not remove it
(`dictConfig` clears a logger's handlers, never its filters), and the async
dispatcher's background thread is covered too, which is where the second line
came from.

**Scope, measured rather than assumed.** 13 records were emitted at DEBUG and
exactly **one** carried the credential — the `httpx` INFO line. httpcore's traces
do not: a request appears as `<Request [b'POST']>`, `connect_tcp.started` carries
host and port, and the header trace is of the RESPONSE headers. So the filter is
installed on the `httpx` logger and nowhere else. Because that is an observation
about httpcore 1.0.9 and not a law, the tests assert over records from **every**
logger, so a future httpcore that starts emitting the target fails them.

**The pre-merge review found a real hole and it is the instructive part.** The
first draft returned `?key=REDACTED#token=SECRET` — the denylist argument had
been applied to parameter NAMES and then not to parameter LOCATION. Not
hypothetical: an OAuth implicit-flow callback puts its token after the `#`,
`str(request.url)` keeps the fragment and httpx logs it, and a tenant
`callback_url` is an unvalidated string. Reparsed with `urlsplit`, which also
fixed `https://host?key=K` (a query with no path, previously untouched because
the authority was taken as everything up to the first `/`) and IPv6 authorities.
A second finding corrected a docstring that credited `client.py` — which is
`urllib`-based and never touches the `httpx` logger at all.

**The residue, named rather than implied to be handled:** a credential in a URL
**path** is not redacted. Redacting paths would destroy the diagnostic the
redaction exists to preserve, and no URL the gateway constructs is shaped that
way — a tenant `callback_url` could be. Pinned by a test so it stays a decision.

**Flags: none cleared, added or reworded.** This is local logging behaviour and
touches no Google seam's verification status; `CLAUDE.md`'s verification ledger
is untouched and not restated. Suite **151 → 178**; mutation-tested at the source
(removing the install fails exactly the two load-bearing tests, with the
credential visible in the failure output), and the mutation is kept **in** the
suite as `test_the_test_above_can_actually_detect_the_leak` so it can never pass
vacuously.

**One thing this PR could not do:** `CLAUDE.md`'s test-count line is stale again,
and a note in `docs/google-cloud-setup.md` §8a — the section that exists because a
webhook URL leaked once already — would be worth having. Both files are CG-21's
this session and were left alone.

### CG-32 · The dedupe counter overflowed an `info` payload the gateway had just accepted  ✅ shipped 2026-07-30 · [PR #32](https://github.com/mmackelprang/chat-gateway/pull/32)

CG-30's request-time bound — `len(title) + len(body)` ≤ **3989** — deliberately
did not reserve the dedupe counter, so `render` appending
`" (×N since last notice)"` to a deduped re-delivery could push a payload the
gateway had **already accepted with a 202** back over the field cap, and the
`pydantic.ValidationError` fired in the same uncaught place CG-30 had just
emptied. Suite **144 → 151**.

**Measured at `/v1/notify` in-process, before and after** (combined 3989, with a
`dedupe_key`, clock advanced past the window):

| step | before | after |
|---|---|---|
| 1. first delivery | 202 | 202 |
| 2. repeat within the window (suppressed) | 202 | 202 |
| 3. repeat within the window (suppressed) | 202 | 202 |
| 4. window reopens, `occurrences=3` | **500** | **202** |

The filed row's table showed three steps; it takes **two** suppressions to reach
`occurrences=3`, so the reproduction has four. Same defect, same numbers — the
row's middle line was repeats plural.

**The user's decision was option 1, "shorten then drop"** (2026-07-30). Three
forms, tried in order: the full `" (×N since last notice)"`, the short `" (×N)"`
(~5 characters instead of 23, so it fits in essentially every real case), then
nothing at all. **Hard rule #1 is the justification, and it is written into the
code rather than only into this row:** the counter is gateway-generated
transport decoration — the gateway's accounting of its own dedupe window — not
app-domain content. When something has to give against the transport's field
cap, it is ours, not theirs. The app's title and body are delivered
byte-for-byte, asserted by exact string equality rather than by a length check.

**`info_max_combined_length()` is unchanged at 3989, and a test pins the
literal.** That was the user's binding condition on CG-30 and it carried forward
verbatim: no request that succeeds today may start failing. Every other boundary
in the new test block is derived — this one is hardcoded deliberately, because a
purely derived assert would happily follow the bound *downwards* if someone
later reserved counter width, which is precisely the option (3) this decision
rejected.

**The room calculation cannot drift from what is emitted.** `render`'s info
branch is split at the seam the counter goes into — `head` = prefix + title,
`tail` = separator + body — and the room is `TEXT_MAX - len(head) - len(tail)`,
computed from the very strings about to be concatenated rather than from a
second copy of the arithmetic. N's width is measured from the rendered string,
never reserved at a fixed size: `×3` and `×10000` differ, and a fixed allowance
would be wrong the first time a count reached four digits.

**The claim the decision rested on was verified rather than assumed — and it
needed qualifying.** Option 1 was chosen partly because a dropped count is not
actually lost: every suppressed occurrence is already recorded in the delivery
log. True — `service.emit_notification` records `deduped` / `occurrence N within
window` unconditionally. But pre-merge review caught the first docstring
flattening **recording** and **retrieval** into one claim, and retrieval is two
stores with different retention. Measured 250 suppressions deep:
`GET /v1/deliveries` serves the in-memory ring buffer (200 per source, `limit`
defaulting to 50) and **does** evict the oldest ordinals; the append-only JSONL
under `<CHAT_GATEWAY_STATE_DIR>/deliveries/` that `__main__` configures held all
250. Eviction is the benign direction here: the ordinal a dropped counter would
have shown is the **highest**, hence the newest entry, hence the last thing a
ring buffer discards. Now pinned by a test rather than left in a review note.

**UAT ran over real TCP**, as CG-30's did and for the same reason: post-fix
there is no unhandled exception left on this path, so the dev box's
wedge-on-uncaught-exception trap no longer applies. The pre-fix 500 was driven
**in-process only**, per the filed row's warning box. Live uvicorn, real
`WebhookAdapter` posting to a local sink that captured what actually went on the
wire, real dispatcher thread, real `DeliveryLog` with its JSONL audit dir. One
injection only — `Deduper(window_seconds=3)`, a constructor argument with no env
var, so "the window reopens" is reachable in a UAT rather than an hour away.

**All three forms were observed on the wire, not inferred from the arithmetic**
— the counter sits at the head/tail seam, so the sink captured the 40 characters
following the 200-character title:

| room left | seam on the wire | `len(text)` |
|---|---|---|
| 23 | `ttttt (×2 since last notice)\nbbbbbbbbbbb` | 4000 |
| 6 | `ttttt (×2)\nbbbbbbbbbbbbbbbbbbbbbbbbbbbbb` | 3999 |
| 0 | `ttttt\nbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb` | 4000 |

The body starts immediately after the seam in every row — nothing of the app's
content was moved aside to make room. **Zero 500s and zero tracebacks** across
the whole run, `/healthz` 200 before and after, and CG-30's 422 still fires at
3990 with the limit and the size named.

**Flags: none cleared, none added, none reworded** — offline behaviour, no
Google seam touched. `CLAUDE.md`'s verification ledger is untouched and not
restated; only its test count moved.

**CG-36 filed** from this item's docs pass: `docs/integration-guide.md`'s
one-line notify summary still says the collapsed count "rides on the next
delivery" with no mention of the degradation. A general-audience summary rather
than a false guarantee, and outside this item's file boundary with three
Builders running concurrently — so filed rather than fixed in passing.
### CG-19 · The Marketplace-SDK comment that chose this project's runtime  ✅ shipped 2026-07-30 · [PR #30](https://github.com/mmackelprang/chat-gateway/pull/30)

All three IaC paths enabled `appsmarket-component.googleapis.com` under a comment
repeating the claim CG-6 corrected. **Enabling the API stays** — harmless, free,
and it shortens a later publish; only the *prerequisite* claim goes. Comments and
illustrative defaults only; suite unchanged at **144**.

**The correction is written to stay in the file, not to remove the words.** This
is the sentence that put the project on the add-ons runtime, so each of the three
now carries `⚠ CORRECTED 2026-07-30 (CG-19) — DO NOT REINSTATE THE OLD CLAIM`,
mirroring the `⚠ CORRECTED` block CG-6 landed in `docs/google-cloud-setup.md`, and
tells a reader choosing a runtime for a *new* project to read ADR-0001 first.

**Worth recording, because it explains why the API is enabled at all:** CG-2's
review caught that `appsmarket-component.googleapis.com` was *"declared a
prerequisite while no IaC path enabled it"* and added the enable calls to resolve
that — on the strength of the false claim. CG-6 then corrected the claim in the
prose doc. This is the third act: the IaC keeps the harmless resource and loses
the false reason.

**Review caught the fix overclaiming in exactly the way the fix exists to
correct**, and that is the entry's most useful line. The first draft quoted Google
as saying the Marketplace SDK's settings *"are ignored for Chat outright"* and
cited the add-ons page — but the repo's own source scopes that quote **"on an
add-ons deployment"**, and the quotation had been truncated so it no longer
carried the *"To deploy and test an add-on in Chat"* sentence that self-discloses
the scope. Add-ons-derived evidence restated as universal, in files that now
provision **classic** — the same failure class as CG-11's widget claim. Both
sources are now quoted **with their scopes named and marked "do not merge them"**,
and the classic-applicable citation leads.

**The `KEY_FILE` / `-KeyFile` default is deliberately NOT renamed**, which
deviates from the row's widening, and the reason is measured rather than argued.
The `"already exists — not minting another"` branch matches on **filename only**;
read out of the real key files (the `project_id` field only), `chat-gateway-sa.json`
→ `chat-gateway-prod`, the **deleted** project, and the check returns True for any
`-ProjectId`. So the trap is real. But the live key is `chat-gateway-sa-gw.json`,
so **any** new default stops matching it too and the script would **mint a second
service-account key** on every host that already has one. A comment fix must not
create credentials as a side effect. Both scripts now document the trap at the
default *and* at the check instead.

**Comments-only was proven mechanically, not asserted.** Stripping comment lines
at `origin/main` and on the branch and diffing the remainder leaves **one** changed
line repo-wide — the `PROJECT_ID` unset-error message — and both scripts, run end
to end against a stubbed `gcloud`, produce **byte-identical output** to `main`.
The `.ps1` keeps its UTF-8 **BOM** and its exact non-ASCII inventory (`– — § ⚠`).

**The examples now name no project at all**, rather than naming the live one:
`chat-gateway-gw` would have been accurate, but an operator copy-pasting a usage
line verbatim would then be running the setup script against **production**.
`docker-compose.yml:23`'s fourth copy of the dead key filename is a placeholder.

**⚠ Terraform was NOT validated and could not be** — it is not installed on this
box, `terraform validate` has never run here, and that path has never been
applied. The `.tf` edit is **reviewed by reading only**, exactly as CG-2 recorded.
The comments-only proof covers it *textually*; it establishes nothing about the
HCL's validity, which is exactly as verified (or not) as before.

**Flags: none cleared, none added, none reworded** — `CLAUDE.md`'s verification
ledger is neither restated nor summarized. **CG-35 filed** for the two things this
item was forbidden to touch: the IaC's `⚠ LIVE-UNVERIFIED` comment now contradicts
`CLAUDE.md`'s "closed by circumstance" record, and the `.sh`/`.ps1` diverge on an
absolute `KEY_FILE` — the latter surfaced by the UAT run, measured not predicted.

### CG-23 · The `resp.text[:200]` echo survives in both sibling adapters  ✅ shipped 2026-07-30 · [PR #29](https://github.com/mmackelprang/chat-gateway/pull/29)

CG-7's argument — *a Google error body can quote the request, and the request
path names the subscription* — applied with more force two files over, and both
non-200 branches now raise **verb/identity + HTTP status + reason phrase**:

```
webhook POST failed for pm-familyworkspace: HTTP 403 Forbidden
Chat API send failed for agent-comms: HTTP 403 Forbidden
```

**The blast radius was measured, not asserted, and it was wider than the row
described.** The row said the defect was the adapter's error text. UAT drove a
real 403 through the **real gateway over real TCP** (a `ThreadingHTTPServer`
standing in for Google, returning a body that quotes the request URL — the case
rule #2 exists for) and found the webhook's `key` **and** `token` in three
artifacts:

| Artifact | Before | After |
|---|---|---|
| the HTTP **502 body returned to the calling app** (`service.py:191-192`) | `key`+`token` | clean |
| the delivery log / `GET /v1/deliveries` | `key`+`token` | clean |
| the **JSONL audit file on disk** (`delivery.py:124,128`) | `key`+`token`, **once per retry** | clean |
| `/healthz` | clean | clean |
| gateway console at default log level | clean | clean |

The 502 row is the one that reframes the item: the credential was handed **back
across the tenant boundary** to whichever app called `/v1/messages`, not merely
written to a log the operator owns. The audit-file row is the durable one — on
the `/v1/notify` path the dispatcher writes `{exc}` on every retry, so one failing
notification persisted the credential to disk three times.

**The reason phrase is looked up LOCALLY, and that is not a stylistic choice.**
`resp.reason_phrase` is **not** a fixed string: httpx returns
`extensions["reason_phrase"]`, which httpcore fills from the HTTP/1.1 status
line, falling back to the local table only when the server sent none. Using it
would have re-admitted server-controlled bytes in the very item whose premise is
that the response is not trusted. Both adapters call
`httpx.codes.get_reason_phrase(status)` — a pure local enum lookup — pinned by a
test that hands back a hostile status line. **The same defect is live in
`PubSubError`, whose docstring claims the opposite; filed as CG-33** rather than
fixed, because a concurrent Builder owned `pubsub.py`.

**The cost, stated as CG-7 stated it and not glossed:** Google's error prose is
**lost**. A 403 no longer distinguishes "webhook deleted" from "space archived"
from "sender blocked"; that now has to come from the space itself or Google's own
logs. Status plus phrase is what a caller can act on — retry, alert, give up —
and the prose was only ever useful to a human reading a log.

**CG-25 was not undone**, and there is a test that says so rather than a claim.
`send_text`'s two branches keep their deliberate byte-symmetry and their exact
strings (`in-thread reply failed: HTTP 403` / `: ConnectError`), which are
load-bearing for jobhunt's R7 delivery-log line. That leaves one **residual
asymmetry inside the file** — `send()` and `webhook.send` say `HTTP 403
Forbidden`, `send_text` says `HTTP 403`. Deliberate, scoped, and now **pinned by
a test** so it stays a decision rather than drifting; the review called it a wart
worth naming, and naming it is what that test does. Its non-200 format had no
coverage at all before.

**Flags: none cleared, added or reworded.** Both non-200 branches remain
⚠ LIVE-UNVERIFIED — this changes what they *say*, not what is verified against
Google, and the new tests drive `MockTransport`, not Google. `CLAUDE.md`'s
verification ledger is untouched and not restated. Suite **140 → 144**;
mutation-tested (reverting the two raise sites fails exactly the three new
rule-#2 tests). **CG-34 also filed** from UAT: `httpx` logs the entire webhook
URL at INFO — dropped by default, one `basicConfig` call away from a happy-path
leak.

**One thing this PR could not do:** `CLAUDE.md`'s "136 passing" line is now stale
(144), but that file is owned by CG-21 this session and was left alone.

### CG-30 · `info` severity 500s on a payload every other severity accepts  ✅ shipped 2026-07-30 · [PR #28](https://github.com/mmackelprang/chat-gateway/pull/28)

The `info` render path concatenated prefix + title + body into
`OutboundMessage.text`, which is capped at the same 4000 as `Notification.body`
itself — so a notification that passed its own validation could not be rendered,
and the `pydantic.ValidationError` fired inside the request handler where nothing
catches it. **Uncaught 500.** Now a **422 naming both the limit and the size
sent**. Suite **136 → 140**.

**The constraint that shaped the fix, and the reason it is not the one-liner it
looks like.** The obvious implementation is to lower `Notification.body`'s global
`max_length`. That is wrong, and measurably: `alert` and `warning` at title-200 +
body-4000 (4200 combined) are **accepted today**, because those severities put the
body in a **card widget** and only a short fallback line reaches the text field.
The user's decision (option 2) was explicitly conditioned on **every request that
succeeds today must still succeed** — only the range that currently 500s changes,
and it changes to 422. So the guard is a `model_validator` scoped to
`severity == "info"`, and `body`'s limit is untouched.

Measured at the endpoint before *and* after, in-process and again over real TCP
against a live uvicorn:

| severity | `len(title) + len(body)` | before | after |
|---|---|---|---|
| `info` | 3989 | 202 | 202 |
| `info` | 3990 | **500** | **422** |
| `alert` | 4200 | 202 | 202 |
| `warning` | 4200 | 202 | 202 |

**Derived, not hardcoded — and that is load-bearing, not fastidiousness.** The
bound is `TEXT_MAX - len(severity_prefix("info")) - len(INFO_BODY_SEPARATOR)`.
`severity_prefix()` is now the single construction `render` itself uses, so the
guard cannot drift from what is emitted, and a relabelled severity moves the
bound automatically. `"ℹ️ [INFO] "` is **10** characters, not 9 — the emoji is
two code points — which is exactly the sort of constant that rots if written
down. `4000` also stopped being a bare literal: it is `envelope.TEXT_MAX` now,
commented as a **transport** limit on the envelope, which is the hard-rule-#1
framing this whole item needs (the gateway is budgeting its own rendered
message, not knowing anything about an app's schema). The tests derive their
boundary from `info_max_combined_length()` too, so the pair cannot silently
drift apart, and one of them pins that `render` really does emit
`severity_prefix("info")`.

**The regression test is the point of the exercise.** `alert` and `warning` at
4200 → 202, with a docstring saying in words that it exists to stop a later
"simplification" into a global `body` limit. Without it, the wrong fix passes
review in six months.

**Hard rule #2 held under measurement, not assertion:** the 422 the gateway
constructs names the field pair, the size and the limit and **quotes no content**
— asserted against a body of 3790 `b`s and a title of 200 `t`s, neither of which
appears in the message. (FastAPI's own 422 envelope echoes the caller's `input`
back to the caller who sent it; pre-existing for every validation error on this
endpoint, not a log path, and out of scope.)

**UAT was run over real TCP, which the row's own warning box says to avoid — and
that inversion is the finding.** The warning is about reproducing the *500*: any
unhandled exception in a sync endpoint wedges this Windows box, `/healthz`
included, while the process stays alive. Post-fix the overflow is an ordinary
**422**, so it does not wedge anything — which is itself worth proving rather
than assuming. Against a live uvicorn: 4×202, 5×422, `/healthz` answering 200
before and after, **zero 500s and zero tracebacks** in the server log. The
pre-fix 500 and the CG-32 case below were driven **in-process only**.

**Flags: none cleared, none added, none reworded** — this is offline behaviour
and touches no Google seam. `CLAUDE.md`'s verification ledger is untouched and
not restated; only its test count moved.

**CG-32 filed** from the verification pass: a deduped `info` re-delivery has
`" (×N since last notice)"` appended by `render`, which can push an **accepted**
payload back over the field cap — 202, 202, then **500** at `occurrences=3`,
measured. Request-time validation provably cannot cover it without rejecting
payloads that succeed today, which is the one thing this item was forbidden to
do, so it is a separate row rather than a silent gap. It is now the only
remaining 500 on this path, and `docs/consumers/aitrader.md` §11 says so rather
than claiming the 500 is gone.

---

### CG-21 · Migrate to the classic deployment (`chat-gateway-gw`)  ✅ shipped 2026-07-30 · [PR #31](https://github.com/mmackelprang/chat-gateway/pull/31)

**The migration itself was executed and live-verified on 2026-07-29 — outside a
PR, by the user in the Google Cloud console plus a live round-trip.** This row
never had code in it. What shipped under its number is the **documentation
reconciliation**, and the row is retired here rather than deleted because its
body was a *plan in future tense* for work already finished, and that text is
what needed correcting.

**What the row used to say, and why each line had to go:**

| Row text | Status |
|---|---|
| *"`chat-gateway-gw` is provisioned and the setup script ran clean on it"* | Provisioning was the last thing **written down**, not the last thing that **happened**. Cutover followed on 2026-07-29. |
| *"Expected scope: two env values … plus `CHAT_GATEWAY_INTERACTION_ROUTING_TARGET`"* | Correct, and it held. Names only — the values are runtime env (hard rule #2). |
| *"zero producer card changes"* | **Held, observed rather than predicted.** D3's portable card convention (CG-13) paid for itself. |
| *"Console-only work … is the user's"* | **Still true and still outstanding** — see below. |
| *"Rollback is switching the env values back"* | **Expired.** The one genuinely load-bearing correction in this PR — see below. |
| *"Tier-1 webhook identities are per-space and unaffected throughout"* | **Held**, and is now empirical rather than predicted. Evidence and its exact scope: `CLAUDE.md`'s verification ledger — linked, not restated. |

**The migration is now IRREVERSIBLE, and no document said so.** D7 offered
rollback as *"switching two env values back"*
(`CHAT_GATEWAY_PUBSUB_SUBSCRIPTION`, `GOOGLE_APPLICATION_CREDENTIALS`), and both
ADR-0001 §D7 and this row still promised it. `chat-gateway-prod` was **deleted
2026-07-30**, so there is nothing to point those names back at, and E2 already
proved a classic app cannot be toggled to add-ons. Reverting today means
provisioning a **third** project and redoing the console work — a fresh
migration, not a rollback. That is **not a defect in D7**: reversibility was real
while both projects existed, which is exactly what made cutting over safe, and it
was then spent deliberately. Recorded in ADR-0001 §D7, `CLAUDE.md` and here,
because *"All bounded, none irreversible"* sat two lines above the rollback
bullet and is now the opposite of the situation.

**What CG-20 had already fixed, and this PR deliberately did NOT re-touch:**
`docs/google-cloud-setup.md`'s project names, its dated provisioning-history
table, step 5's topic path, the dead-key callout for `iac/chat-gateway-sa.json`,
and ADR-0001 §5/§7/§10/§12/§13 and §2.6 C2. The largest risk on this row was
redundant or contradictory work, so the inventory came first and CG-20's
territory was left alone.

**What was genuinely left — four documents still describing the migration as
pending, or add-ons as production:**

- `CLAUDE.md` — *"a migration is underway"*, and `__cg_action__` justified as
  *"load-bearing on the runtime deployed **today**"*. On classic it is **not
  needed**, which is not the same as **not used** — the key is checked first and
  unconditionally (*"app-declared, authoritative when present"*,
  `adapters/pubsub.py:376`), so a card that carries it still gets its `action.id`
  from it. Pre-merge review flagged the risk of collapsing the two, so CLAUDE.md
  now glosses the repo's existing shorthand *"inert"* — used in ADR-0001 and the
  integration guide, always paired with *"still wins when present"* — rather
  than contradicting it. The keep-it instruction is unchanged; its
  *justification* is now the weaker one, and the file says so instead of quoting
  the strong one.
- `.env.example` — the routing-target block labelled the add-ons row **"(today)"**
  and defaulted its hint to the topic path. Rows are **dated** now, and the
  classic answer (any constant) leads. A stale topic path under classic is
  **harmless** — the gateway discards topic-path-shaped values from
  Google-native sources rather than promote one into an action name — it merely
  costs the native slot.
- `docs/google-cloud-setup.md` step 8 — gave the topic path as *the*
  `CHAT_GATEWAY_INTERACTION_ROUTING_TARGET` answer, unconditionally. That is the
  add-ons answer, in the document an operator sets up the **live** project from.
  Now a per-deployment table. This paragraph was **not** part of CG-20's rewrite.
- `docs/integration-guide.md` — *"add-ons + Pub/Sub today"* and *"**and it is
  moving**"*, seven lines above its own correct *"Production migrated … on
  2026-07-29"*. The file contradicted itself.

Plus the queue's own stale status: the ADR-decisions table, the E1/E2 section's
*"Migration status: underway"*, and the CG-17/CG-18 premise (below).

**Still console work for the user — this repo cannot verify any of it.** Adding
the classic app to each space, and the new tier-2 sender identity. The one dated
observation that exists is CG-20's, in step 6 of the setup doc: as of
**2026-07-30** the classic app **"Agent Comms"** was in the **JobHunt space
only**, so tier 2 is not live in the aitrader or FamilyWorkspace spaces. That is
a console snapshot, not repository state, and it is linked rather than repeated.

**No deployed state is asserted anywhere in this PR.** `config/registry.yaml` and
`.env` are gitignored dev-box files and the deploy target `/srv/chat-gateway/`
has its own copies; this worktree contains only `config/registry.example.yaml`,
so no claim is made from it. Docs only — `src/`, `tests/`, `iac/` and `config/`
untouched; **this PR adds and removes no test**, and the suite stands at **144**
where main leaves it (136 → 140 by CG-30, → 144 by CG-23, both of which merged
while this branch was open). No verification flag added, cleared or reworded,
and `CLAUDE.md`'s ledger is linked rather than restated.

**Two findings filed rather than fixed** (both in `src/`, both out of scope for a
docs row): see **CG-35**.

> **Renumbered during rebase, recorded rather than quietly fixed.** This row's
> finding was filed as **CG-32** and had to become **CG-35**: CG-30's Builder
> claimed CG-32 and CG-23's claimed CG-33 + CG-34 while this branch was open.
> Three Builders appending to one queue in parallel will collide on the next
> free number, and the collision is invisible until rebase — worth knowing the
> next time two run at once.

### CG-11 + CG-20 · The selection-widget claim, E1/E2, and a deleted project  ✅ shipped 2026-07-30 · [PR #27](https://github.com/mmackelprang/chat-gateway/pull/27)

One PR, per the user's combine decision: CG-11's job was to adopt ADR-0001 §7,
and §7 carried the very error CG-11 existed to fix, so §7 had to be corrected
before it could be adopted — and the ADR is CG-20's file. Two sequential PRs
would have had the second contradict the first. Docs only; suite unchanged at
**136**.

**CG-11's own row body was half wrong, and retiring the row is how that text got
corrected.** It stated *"a widget is not an interaction trigger"* and *"the
pattern is widgets for input, one button to submit"* as universal claims. Both
were **add-ons-scoped**. On classic — the runtime this project runs — a widget's
`onChangeAction` fires on a card with **no button at all**
(`tests/fixtures/classic-cardclicked-onchange-event.json`), and the one-button
pattern is the *portable*, *lower-event-volume* choice rather than the only one.
The row's own amendment block had already flagged this against itself, so the
row was carrying a claim its own amendment contradicted; deleting it is the fix,
and this entry is where that text now lives.

**The row's "locations to fix" list was wrong too**, and the corrected
per-location table was re-verified against the files in this PR rather than
copied forward a third time. `docs/integration-guide.md`'s *"Collecting
structured input"* section is **already correct** — runtime-scoped, and already
recording that `onChangeAction` fires on classic. Exactly one thing changed
there: the parenthetical `(deployed today)`, which named add-ons as the current
runtime. CG-28's Builder copied the bad list on trust and nearly shipped a
paragraph telling consumers to distrust that correct section; this PR did not
repeat it.

**What the correction says**, in the locations that were genuinely wrong: a
widget-as-trigger is capture-verified **false under add-ons and true under
classic** — a property of the **runtime**, never of Pub/Sub transport, and that
substitution is precisely what made the original sentence wrong — while modal
dialogs being impossible remains **doc-derived inference, never tested on either
runtime**. The old sentence welded the two together with one confident dash.
`CLAUDE.md`, `docs/consumers/jobhunt.md` R6 and ADR-0001 §7 now state them
separately, §7 with a banner recording why it generalised from add-ons evidence;
`docs/consumers/jobhunt-handoff.md`'s per-location table was updated to record
the fixes rather than contradict them. Also carried forward: jobhunt R7's
`0s/3s/7s` retry text, which named the **gaps** as if they were attempt times.
The same sentence lives in `src/chat_gateway/forwarder.py:9`'s docstring, which
a docs-only PR cannot touch — **filed as CG-31** rather than left implied.

**The `google-cloud-setup.md` half was the more urgent one and did not get
crowded out.** That document named `chat-gateway-prod` — deleted 2026-07-30 — in
a `gcloud projects create` command, a ✅ present-tense provisioning box, the
console's Pub/Sub topic path and the key filename to hand back. A reader
following it would have created a second project named after a deleted one and
wired credentials by a dead key. The ✅ box is now a dated three-row history
(`chat-gateway-prod`, E1's throwaway `chat-gw-e1-20260729`, and the live
`chat-gateway-gw`) rather than a green check for something that no longer
exists — because a provisioning record without a date *and* a project id
silently becomes a claim about whatever project the reader is holding.

**E1/E2 recorded where they are load-bearing.** The add-on toggle is
**create-time only** (E2), which is why D7's parallel-project path was the *only*
available one rather than merely the prudent one — written up as the explicit
**twin** of the Marketplace-SDK correction, each pointing at the other by section
name, because together the two traps are the whole story of how this project
ended up on the wrong runtime and what leaving it cost. (They sit in different
sections of `google-cloud-setup.md` and always did; the first draft *asserted*
adjacency instead of building the cross-reference, which the review caught.)
ADR §10 gained a six-row
add-ons-vs-classic capability comparison, kept because every project that
produced the add-ons evidence is deleted and this table plus the fixtures are the
only surviving record. **Two of its six rows are explicitly not first-hand**
(slash-command shape, modal dialogs) and carry their evidence in-table, so the
row's own phrase *"the two live-verified capability tables"* is not reintroduced
by a later summary. ADR §5 option D's two unsettled rows and §12's five open
questions are marked answered; §12's heading is kept for referential stability.

**One thing deliberately not claimed:** nothing here asserts anything about
registry state. The step-6 note that the classic **"Agent Comms"** app is in the
**JobHunt space only** is labelled a **console observation dated 2026-07-30**
that this repository cannot prove — no source file, registry entry or test
records which spaces an app has been added to. The note names the near-miss
explicitly: the registry's per-identity `space` is a **posting target**, not an
installation record, so a reader who greps for `space` does not conclude the
sentence is wrong.

**Flags: none cleared, none added, none reworded**, and `CLAUDE.md`'s
verification ledger is untouched and not restated. **Filed for CG-19:**
a fourth copy of the dead key filename lives at `docker-compose.yml:23`, outside
`iac/` — see that row.

### CG-28 · Consumer handoff doc — **jobhunt**  ✅ shipped 2026-07-30 · [PR #24](https://github.com/mmackelprang/chat-gateway/pull/24)

`docs/consumers/jobhunt-handoff.md` — the gateway's answer back to jobhunt's
R1–R9. Landed as a **sibling** of `docs/consumers/jobhunt.md` rather than an
edit to it, which is what kept CG-11 unraced: the contract doc stays the
contract, and the only change to it is a five-line pointer block that touches
nothing CG-11 owns. Docs only; suite unchanged at **136**.

**The live blocker, stated the way the row demanded.** Routing already resolves
— `apps_for_space('spaces/AAQAgjGR7J4')` → `['job-hunter']`, run against the
live gitignored `config/registry.yaml` — and `callback_url` genuinely is the
only missing registry value; the earlier claim that `space` was also missing was
a check run against `registry.example.yaml`. But jobhunt has **no receiver**
(`pipeline/review_ui.py` serves `/verdict`, `/recheck`, `/override`, `/applied`,
verified read-only in that repo), so configuring `callback_url` today proves
**R7**, not R3. The 2026-07-30 dev-registry configuration is written up as a
**dated observation of a development box**, with `/srv/chat-gateway/` explicitly
named as not having it — never as deployed state.

**Two findings for jobhunt, filed in the doc rather than fixed here** — both are
in another repo or belong to the operator:

| Finding | Detail |
|---|---|
| `callback_url`'s port is not agreed | the contract doc and the dev registry say `8710`; `pipeline/review_ui.py` defaults to **`8763`** and is where the doc recommends the receiver live. A port mismatch is **indistinguishable from having no receiver** — both are a refused connection — so it is called out rather than silently "corrected" in someone else's config |
| `/v1/notify` would 503 for `job-hunter` | notify routing is `(app, severity) → identity` from a `routes` map, and this app has none. R3/R4/R7 do not need it; the doc says what to ask for if the lane is wanted |

**CG-11 was not raced, and the review is the reason that claim is trustworthy.**
The first draft asserted that four documents still carried the "a selection
widget is not an interaction trigger" wording. **Only ADR-0001 §7's body does.**
`docs/integration-guide.md` is already runtime-scoped and already records that
`onChangeAction` fires on classic (its only staleness is calling add-ons "the
runtime deployed today"); `CLAUDE.md` and `jobhunt.md` R6 carry a *different*
defect — the modal-dialog inference stated as settled fact. The bad list had
been copied from CG-11's own row without re-checking each location, and it
shipped a sentence telling consumers to distrust a correct section of the
integration guide. Replaced with a per-location table. **CG-11's scope is
unchanged**, and the four locations it owns are untouched by this PR.

**One claim the review killed outright:** the doc said `thread_key` is "echoed
back on inbound events", with a populated sample. **No capture has ever carried
`thread.threadKey`** — it normalizes to `null` on every real event — so a
jobhunt receiver correlating on it would have got nothing. Corrected, sample set
to `null`, and `thread_name` named as the stable inbound handle. Three more
present-tense registry assertions that could only have been read on the dev box
were dated or scoped, and the R7 status row was softened because the *composed*
R7 chain (tap → 3 failed callbacks → notice delivered) has never run live —
CG-25's UAT drove it with the Chat API also down.

**UAT was run, and it is what the doc's numbers come from** — 46 checks across
two harnesses, all green, using the real classes: a real `ThreadingHTTPServer`
receiver for the R3 happy path, genuinely closed ports for R7 and for the Chat
API, and a real uvicorn server for the HTTP surface. It corrected the doc twice.
`BACKOFF_S = (0, 3, 7)` is a sequence of **gaps**, so the three attempts fall at
absolute **0s / 3s / 10s**, not 0/3/7 — and because `process_due()` only runs
after a successful poll, at the loop's default 5s interval they actually land at
**0s / 5s / 15s**, measured. Also confirmed end to end: `dedupe_key` is the
Pub/Sub message id; `__cg_action__` is lifted into `action.id` and **popped**
from params; `action.id` is `None` and counted, never `""`, when nothing
resolves; `configCompleteRedirectUrl` arrives `<redacted-by-gateway>`; the R4
refusal posts `⛔ Not authorized for this action.` into the tapped thread and
increments only `suppressed_not_authorized`; the CG-25 line reads
`in-thread notice also failed: in-thread reply failed: ConnectError`; the tier-1
line reads `no reply_fn (tier 1) — in-thread notice impossible`; `/healthz`
leaks no key, no webhook URL and no `allowed_users`; `/v1/inbox` is 403 for the
opted-out tenant; and `callback_url` on an `allow_inbound: false` app is a
registry validation error.

**Flags: none cleared, none added, none reworded.** `CLAUDE.md`'s verification
ledger is **linked, not restated** — the doc's §11 is a per-link table for
jobhunt's own chain (parse / pull / reply / outbound / callback), the same shape
the contract doc already carries, and it explicitly refuses to copy the residue.

### CG-27 · Consumer handoff doc — **aitrader**  ✅ shipped 2026-07-30 · [PR #25](https://github.com/mmackelprang/chat-gateway/pull/25)

`docs/consumers/aitrader.md` rewritten from a thin requirement→where table into
the handoff the row asked for: the gateway's answer **back** to
`D:\prj\aitrader\docs\chat-gateway-requirements.md`. Thirteen sections — the
endpoint contracts as actually coded (every field, limit, status code and error
string), severity routing/rendering, dedupe, the dispatcher + delivery log, the
dead-man monitor, the inbound guarantee, tier-1 independence, verification
status, sharp edges, an operator env-var checklist, and the requirement→
implementation map. Docs only; no source touched. Suite unchanged at **136**.

**The false claim was the urgent half, and the correction is stronger than the
sentence it replaces.** Non-goal 1 said the gateway has *"NO
callback/webhook-to-consumer mechanism at all — inbound is passive polling
only."* False since 2026-07-24. aitrader's guarantee was never affected, but it
was resting on a premise a reader could disprove in one grep — and would then
reasonably doubt the guarantee too. Restated on its real basis: **the mechanism
exists and this app is locked out of every part of it**, at four enforcement
points (`/v1/inbox` 403; the registry-load rejection of `callback_url`; the
dispatch skip; `/v1/identities` withholding a routing target). That claim
*survives the gateway growing more inbound features*, which "no such mechanism
exists" never could. Point 2 is the load-bearing one: the gateway **refuses to
boot** in a configuration that would give aitrader an inbound path, so there is
no runtime state in which a misconfiguration quietly opens one.

**CG-12 is covered with both of the traps its own review caught** — the counters
count *candidate apps that declined*, not events that went nowhere (an opted-out
owner increments even when a co-owner **received** that same event), and they
store nothing attributable because `/healthz` is unauthenticated.

**Plus a precondition that neither `CLAUDE.md` nor CG-12's row states, and it
narrows CG-12's own residue claim.** `apps_for_space` (`registry.py:161-172`)
only nominates an app whose identity has a **non-empty `space`**. Both aitrader
identities ship `space: ""` — they are one-way webhooks. **So as the registry is
committed, aitrader cannot increment either counter at all.** CG-12 recorded that
`suppressed_opt_out` is "a de-facto unauthenticated activity meter for that
tenant by inference"; that is true only in a configuration where an operator has
*also* filled in a space for an aitrader identity **and** added the Chat app to
it. Not a contradiction of CG-12 — a missing precondition, documented in the
consumer doc with the hedge rather than left as an assumption. Recorded here so
the next reader of CG-12's residue paragraph knows what it is conditional on.

**Ledger discipline held:** §10 **links** `CLAUDE.md`'s verification ledger and
does not restate or summarize it, per that file's own instruction. **No ⚠ flag
was cleared, added or reworded.** Env-var **names** only, per hard rule #2 — no
webhook URL, no key, anywhere in the diff.

**A real defect was found and filed rather than fixed — CG-30.** On the `info`
path `render` concatenates title + body into one field capped at 4000, while
`Notification.body` alone validates at 4000, so a payload that passes its own
validation cannot be rendered and the uncaught `ValidationError` surfaces as
**HTTP 500** instead of a 422. Measured at the endpoint, not inferred: `info`
title+body 3989 → **202**, 3990 → **500**; `alert`/`warning` at 4200 → 202. The
fix has at least three options with different contracts, so it is Planner's call;
documented as a sharp edge with a workaround in the meantime.

**Review caught one HIGH and it was real:** the doc said *"Filed as CG-30"* while
no such row existed — a fabricated tracking reference, exactly the
confidently-wrong-citation failure this repo keeps logging. Fixed by actually
filing CG-30 in this same PR rather than by softening the sentence.

### CG-12 · Suppressed inbound is COUNTED, and still recorded nowhere  ✅ shipped 2026-07-30 · [PR #23](https://github.com/mmackelprang/chat-gateway/pull/23)

**Option A**, user decision 2026-07-29, implemented as decided — a bare counter
at `/healthz`. Options B and C were not built and nothing was added "while we
were there". `dispatch` gained an additive `on_suppressed(app_id, reason)`
callback mirroring `on_unparseable`, fired at both suppression sites, feeding
bare integers on `SubscriberLoop`. **No behaviour change:** the only `-` lines
in the whole diff are `dispatch`'s signature and its one call site; `delivered`,
`inbox.put`, `forwarder.enqueue` and `reply_fn` are byte-identical to `main`.

**Two integers, not one, and the queue's decision row says "a bare counter"
(singular) — so this is flagged rather than slipped in.** The linked spec
sanctions it explicitly (design §3, CG-12: *"Counting authorization refusals
separately is additive and rule-5-aligned"*), and option A's actual constraint
is about what is **stored** — no space, no app id, no content — which two
`int`s satisfy exactly. Merging them would make the endpoint *less* honest: one
number cannot distinguish "five hundred people were refused" from "five hundred
events landed in a space nobody serves", which are completely different
investigations. Both reasons are first-class in the tests, deliberately —
`not_authorized` became reachable in production for the first time on
2026-07-30, when `job-hunter` gained `allowed_users`.

**Review refuted one of this PR's own claims, and it had been written into five
places.** The first draft said the counters mean the event *"reached nobody" /
"goes nowhere" / "every owner opted out"*. **False.** `on_suppressed` fires per
**candidate app**, independent of the others — so in a space co-owned by an
opted-out app and an active one, `suppressed_opt_out` increments **for an event
that was delivered**. An operator reading the original prose would have gone
hunting for a lost event that was never lost. All five copies now lead with
*candidate apps that declined an event*, and the all-owners-opted-out case is
recorded as the **gap CG-12 was filed for**, not as the counter's definition.
Pinned by `test_a_co_owner_still_receives_an_event_that_another_owner_declined`,
which did not exist until review asked for it — every prior test had both owners
opted out, so the suite could not tell the two meanings apart.

**Deliberately NOT an input to `status`, at any magnitude, and the reasoning is
in the code so nobody "fixes" it with a threshold.** Both are correct behaviour:
`opt_out` is hard rule #6 doing its job, `not_authorized` is jobhunt's R4
allowlist doing its job. Degrading on a working guarantee teaches an operator
that `degraded` is the normal reading, which is the ignored-warning failure mode
rule #5 was written after. Review stress-tested the obvious counter-argument — a
misconfigured `allowed_users` locking out the legitimate user — and it does not
hide: `reply_fn` is unconditionally wired whenever tier 2 is on (creds are
required for Pub/Sub, and creds imply the Chat adapter), so every
`not_authorized` suppression puts ⛔ in front of the affected human.

**The unauthenticated caveat is carried in the code, as the user asked** — but
the first draft's *reason* was wrong and was corrected: the app id is withheld
**not because app ids are secret**. They are not, and `/healthz` says so itself
("Names, never values") while `inbox.pending` already publishes observed inbound
volume keyed by app id on the same open endpoint. The operative principle is
narrower: **no observed-traffic attribution for a tenant that opted OUT** —
those two only ever name apps that opted **in**. Recorded because a maintainer
applying the original wording literally would have found `/healthz` "violating"
it twice and concluded the comment was stale.

**One residue accepted with eyes open rather than claimed away:** with exactly
one `allow_inbound: false` tenant registered — today's deployment —
`suppressed_opt_out` is a de-facto unauthenticated activity meter for that
tenant **by inference**, though no field names it. Taken as **volume-only**, and
marginal beside `events_seen`, which already publishes total inbound volume on
the same endpoint. "Stores nothing attributable" is literally true; "zero rule-6
exposure" was slightly stronger than the facts.

**Flags cleared: none, as expected** — this is offline behaviour and no Google
endpoint is contacted. `aitrader` stays `allow_inbound: false` and locked out of
every inbound path; its traffic is still persisted nowhere.

**UAT run against a real uvicorn server over real TCP**, not TestClient: five
events through one poll (two into an all-owners-opted-out space, one refused,
one authorized, one into a mixed-ownership space) gave `suppressed_opt_out: 3`,
`suppressed_not_authorized: 1`, `events_seen: 5`, `status: "ok"`, `reasons: []`.
Every space id, sender email, display name, dedupe key and action param was
confirmed absent from the whole response body. Rule-6 guarantees re-verified
unchanged: `/v1/inbox` still 403 for the opted-out tenant, the refused user
still told in-thread, and the on-disk audit directory contains files **only** for
the two apps that received something — no file exists for either declining app.

Suite **124 → 135**.

**A finding for CG-27, filed rather than fixed.** `docs/consumers/aitrader.md`
non-goal 1 states *"the gateway design has NO callback/webhook-to-consumer
mechanism at all — inbound (where enabled for other apps) is passive polling
only."* That has been false since the per-tenant `callback_url` push path landed
2026-07-24; hard rule #6 names **two** opt-in paths. aitrader's guarantee is
unaffected — it is still `allow_inbound: false`, and `callback_url` on such an
app is a registry validation error — but the doc grounds that guarantee in "no
such mechanism exists" rather than "the mechanism exists and this app is locked
out of it", which is the weaker and now-wrong argument. Pre-existing, out of
this PR's scope, and CG-27 owns that file.

### CG-25 · `send_text()`'s transport-error guard — the untyped-failure hole  ✅ shipped 2026-07-30 · PR-PENDING

`ChatApiAdapter.send_text()` now wraps its POST in `try/except httpx.HTTPError`
and re-raises `ChatApiError(f"in-thread reply failed: {type(exc).__name__}") from
exc`, mirroring `send()`. Five lines of behaviour, one test, two docstring
corrections and one `CLAUDE.md` ledger row.

**Message shape held deliberately narrow.** Type name only — no body, no URL, no
space. It is byte-symmetric with the sibling non-200 branch three lines below it
(`in-thread reply failed: HTTP {status}`), because the *shape* of this file's
error text is **CG-23's** scope and that row explicitly records `send_text` as
"the half that was already right". Adding the space id here would have preempted
it. `from exc` is preserved, so `__cause__` is still the original `httpx`
exception for anyone who needs it.

**Flag discipline: nothing cleared, nothing reworded.** This does not re-open
CG-5's clear — `send_text()`'s two *threading* branches stay verified-live
2026-07-30. A branch that has never met Google was *added* to a method whose
verified claims are unchanged, so the module docstring's "the `httpx.HTTPError`
branch" became "branches", `send_text()`'s docstring records the new uncovered
branch, and the ledger row that said *"`send_text` has none at all — that is
CG-25"* now names all three methods. The ledger was **not** restated anywhere.

**UAT was run, and it is the reason CG-29 exists.** Not gates — the actual
jobhunt R7 chain, driven through production wiring (`reply_fn =
chat_adapter.send_text`, as `__main__.py` wires it): callback unreachable ×3 →
`_fail_loudly` → `send_text` → Chat API *also* unreachable. Run twice, once with
the guard monkey-removed, so before/after are observed rather than argued:

| Path | Before | After |
|---|---|---|
| R7 delivery log (`forwarder.py` logs full `{exc}`) | `in-thread notice also failed: connection refused` | `in-thread notice also failed: in-thread reply failed: ConnectError` |
| R4 console (`poll_once` prints type name ONLY) | `ConnectError` | `ChatApiError` |

The R7 line **gained**: `connection refused` sat one line under `gave up after 3
attempts (ConnectError)` and did not say *which* connection — a reader could take
it for a fourth callback retry. It now names the operation and the type. The
stutter is real and was accepted rather than silently designed away, because
`forwarder.py` was out of scope.

The R4 line **lost**: two distinguishable types collapsed to one, because
`poll_once` discards the message that now carries the distinction. Filed as
**CG-29**, not fixed here — it lives in `adapters/pubsub.py`, which a second
Builder held for CG-12, and the fix is a design call (how to discriminate
gateway-authored messages from value-embedding ones without breaking hard rule
#2) rather than a one-liner.

**Pre-existing gap left alone, stated so it is not mistaken for coverage:**
`self._tokens()` is evaluated *inside* the new `try`, but a `google.auth` failure
is not an `httpx.HTTPError`, so it still escapes untyped. Exactly symmetric with
`send()`, which has always had the same hole. Out of CG-25's stated scope
("mirror `send()`'s guard"); not a regression, not fixed, not hidden.

Suite **124 → 125**. The guard was mutation-tested: deleting the `try/except`
fails the new test and nothing else compensates.

> **⚠ Concurrency incident, recorded because it nearly shipped the wrong diff.**
> CG-12 was worked in **parallel in the same working directory**, and git
> worktrees are per-directory: the two sessions checked branches out over each
> other. Three CG-12 commits (`0b65758`, `5887745`, `e309357`) landed on
> **`fix/cg25-send-text-transport-guard`**, this item's branch, because the shared
> tree was left pointing at it. Nothing was lost and nothing was force-pushed —
> CG-25 shipped from `fix/cg25-transport-guard`, a clean branch cut at commit
> `92f1d54` in a **separate `git worktree`**, verified to contain only this item's
> four files. **Two Builders must not share one working directory.** Use
> `git worktree add` per item, or run them sequentially.

### CG-22 + CG-9 · The real **classic** fixtures — `CARD_CLICKED` ×2 and `ADDED_TO_SPACE`  ✅ shipped 2026-07-30 · [PR #20](https://github.com/mmackelprang/chat-gateway/pull/20)

Plan: [`superpowers/plans/2026-07-30-classic-fixtures-cg22-cg9.md`](superpowers/plans/2026-07-30-classic-fixtures-cg22-cg9.md).
One PR for both items. Three real captures from the live project
`chat-gateway-gw` land as `classic-cardclicked-button-event.json`,
`classic-cardclicked-onchange-event.json` and
`classic-added-to-space-event.json`. Before this, **every classic path in the
parser was doc-derived** — `classic-message-event.json` is CONSTRUCTED, so CG-1's
classic normalizer had never met a real byte.

**Guard first, and the order was enforced rather than asserted.** The guard
commit is separate and precedes the fixtures commit, and the fixture files were
added only after the extended guard was green on the four pre-existing ones. Two
rules gained the regression tests they never had:

- **the capability-URL rule.** It exists because a path-guess scrub wrote a
  **live bearer token** to disk on 2026-07-29 — the worse of that day's two
  incidents — and it had **zero** tests. Be precise about which half was
  untested, because review caught the tempting summary ("no real fixture had
  ever carried one") being **false**: `addon-message-event.json` is a REAL
  capture and has carried a scrubbed `configCompleteRedirectUri` since
  2026-07-29, so the rule's **pass** side has run on real bytes every test run
  since. What had zero tests was the **reject** side. The rule was **not**
  extended: it already rejects
  `configCompleteRedirectUrl` twice over (`SUSPECT_KEY` on `redirecturl`,
  `SUSPECT_VALUE` on `token=`), and writing a decorative third rule would have
  produced a guard that looks stronger and is not.
- **a structural email rule** (`EMAIL` / `EXAMPLE_DOMAIN`), replacing sole
  reliance on `PII`'s `mackelprang` **literal** — a rule that protects exactly
  one human, in a repo whose next capture may carry somebody else's address
  (jobhunt R4 is explicitly multi-user). Flagged in the plan as droppable and
  called out in the PR body as such; it catches nothing in today's captures and
  its whole value is the next one.

Both were **mutation-tested**: deleting `assert PLACEHOLDER.search(value)` and
deleting the `EMAIL.findall` loop each made exactly its own regression test fail.
Neither deletion left the suite green.

**The bytes are proven faithful, not trusted.** The fixtures were **derived**
from the raw captures by a mapping that reads every real value out of the capture
**by path** — no real literal exists in the derivation at all — and then diffed
against the raws: identical key/type trees, **76 / 72 / 19** leaves, **18 / 18 /
8** changed leaf values, **zero** real identity values surviving. The plan's own
transcribed JSON blocks were parsed back out of the markdown and compared equal
to the landed bytes, so the transcription is checked in both directions. The
guard was also run against the three **raw** captures and flags **6 / 9 / 9**
violating leaves — a guard shown to pass the clean file but never to fail on the
dirty one proves nothing.

**Three of the row's own claims were wrong and were corrected before execution,
not during it** — recorded because two of them would have shipped a defect:

1. *"already redacted at capture time"* was **false**; the named source carries
   nine violating leaves.
2. A better capture existed that the row did not know about — the
   `onChangeAction` shape, which is CG-22's third pinning requirement and which
   the named source does not contain.
3. *"converts the classic normalizer to ⚠ SHAPE-VERIFIED"* was **too broad**.

**E1's capture was considered and deliberately not landed.** Re-verified rather
than trusted: diffed by key/type tree, the only difference is
`selectionInput.onChangeAction.function` **inside the echoed card definition**,
which the normalizer never reads. It pins nothing the landed capture does not and
it comes from a deleted throwaway project.

**Flags cleared: none, and that is the point.** ⚠ SHAPE-VERIFIED accompanies
⚠ LIVE-UNVERIFIED and clears nothing on its own (hard rule #3). The new claim is
scoped in both `pubsub.py` and `CLAUDE.md` to `CARD_CLICKED` (both trigger kinds)
and `ADDED_TO_SPACE`; classic **MESSAGE** stays CONSTRUCTED, and classic
`thread.threadKey`, the `commonEventObject.formInputs` arm, APP_COMMAND,
REMOVED_FROM_SPACE and WIDGET_UPDATED stay unobserved. The ledger's
unverified-surfaces table was **not** edited and **not** restated.

**The `ADDED_TO_SPACE` capture is a DM, not a ROOM**, and the fixture README says
so out loud. That is not a weaker case for the arm CG-9 was filed to pin — a DM
`ADDED_TO_SPACE` carries no `message` object *at all*, which is exactly the
empty-message arm — but the ROOM variant is genuinely uncovered, and whether a
ROOM one can carry a `message` is **unobserved and asserted neither way**. The
add-ons variant CG-9 originally asked for is **uncapturable forever**: closed by
circumstance, not a gap, do not re-file it.

**One hand-transcription deleted.** `test_inbound_parameter_shape_is_a_runtime_property_not_a_direction_rule`
built its classic half from an inline dict typed out by hand, with a docstring
saying *"Real captures land in CG-22."* It now consumes the fixture, and its
assertion tightened from `isinstance(..., dict)` to exact equality. The refuted
comment *"one event per decision, not two"* went with it — true of that card,
false of the classic runtime, and `classic-cardclicked-onchange-event.json` now
sits three tests above it proving so. The rest of that correction is **CG-11's**
and was routed there, not absorbed.

**A finding for CG-26, filed rather than fixed** — see its amended row: the real
Workspace tenant ids are not only in the plan document `:484`, they are in the
**live test file**, as `test_guard_rejects_unmarked_tenant_identifiers`'
negative-case values. Pre-existing on `main` since `a2a894b`, untouched by this
diff, and it survives because **the guard only scans `tests/fixtures/*.json` — it
never scans itself.**

Suite **113 → 124**. No UAT: nothing user-facing changes and no Google endpoint
is contacted.

### CG-8 · Reserve `_`-prefixed app ids (the `_unrouted` hole)  ✅ shipped 2026-07-30 · PR-PENDING

Plan **Part F**. A real hole in a multi-tenant transport, closed at registry
load. `_unrouted` was never a reserved id, so an app registered under that
literal with `allow_inbound: true` would have received **every** unroutable and
**every** `UNPARSEABLE` event from **all** spaces — because the two paths that
write to that bucket (the `except` branch in `dispatch()`, and the
`or [UNROUTED]` fallback) bypass the per-app authorization block **by design**.
That design is correct: an unparseable event has no space, so there is nothing to
authorize it against. The bug was that the bucket's name was claimable.

Reserves the **whole `_` prefix** rather than the one literal, so the next
internal bucket is safe without anyone remembering to come back here. The error
names the consequence, not just the rule — it says the app would bypass hard rule
#6 — because a rejection an operator does not understand gets worked around.

`UNROUTED` moved from `adapters/pubsub.py` to `registry.py`: core must not import
from an adapter (hard rule #3), and the constant is core's to own now that
`load_registry` validates against it. The adapter imports and re-exports it, so
every existing `from ...adapters.pubsub import UNROUTED` call site keeps
resolving — pinned by a test asserting both spellings are the *same object*.

**One test beyond the plan, and it is the one worth having.** The plan asserts
the id is rejected. That proves the guard fires; it does not show a reader why
the guard exists, and in six months "is this defensive noise?" is the question
that gets asked. So `test_the_hole_CG8_closes_is_real_and_now_shut` constructs
the `App` the registry now refuses, dispatches an unparseable event, and
demonstrates it lands in that app's inbox as a pollable `InboundReply` with
`app == "_unrouted"` and `event_type == "UNPARSEABLE"` — i.e. exactly what
`GET /v1/inbox` would hand anyone holding that app's key, with no rule-#6 check
having run. Then it shows the registry rejecting the same config.

**The guard introduced a crash, and adversarial testing of it caught that before
review did.** `app_id.startswith(...)` assumes a string, but **YAML coerces
unquoted mapping keys** — `1:` is an `int`, `true:` a `bool`, `null:` a `None`,
`1.5:` a `float`. All four raised `AttributeError`, which escapes
`load_registry` as an unhandled traceback instead of the config error an operator
can act on. Before CG-8 those configs loaded; after it they crashed the process at
startup. **A validation guard must not convert a tolerable misconfiguration into a
boot failure.**

Fixed with `_require_id_str`, applied to **both** app ids and identity names
(identities are cross-referenced from every app's `identities:` list, so a
coerced name breaks that lookup for a reason invisible in the file). It also
rejects **surrounding whitespace**: `" aitrader"` is a different dict key from
`"aitrader"`, looks identical in review, and would silently fail to match the id
the consuming app sends — a per-app allowlist that quietly matches nothing, which
is the shape hard rule #4 exists to prevent. Whitespace is *not* a route to the
`_unrouted` bucket (`" _unrouted"` is simply a different key), so this is
correctness rather than a second security hole.

**Then the same question asked once more turned up a pre-existing sibling.** If a
coerced key should arrive as a `RegistryError` rather than an `AttributeError`,
so should malformed YAML — and it did not: `load_registry` caught only `OSError`
around `yaml.safe_load`, so a `ScannerError` or `ConstructorError` killed the
gateway at startup with a parser traceback naming no file. Fixed in both the
single-file and the directory branch (the directory branch had no `try` at all),
plus empty-string ids rejected. Pre-existing, in scope because it is
indistinguishable in kind from the defect this item introduced and fixed one
function below.

Now exhaustive and parameterized: **nine** malformed shapes — unhashable
sequence and mapping keys, a YAML date, an empty id, int / bool / null,
tab-padding, and unparseable YAML — every one asserted to arrive as
`RegistryError`, with a valid-config control so the suite proves discrimination
rather than blanket rejection. Rule #5's spirit applied to startup: a gateway
that dies with a parser traceback has told the operator almost nothing.

**All four guards mutation-tested.** Removing the reserved-id `raise` and
widening the prefix each fail `test_reserved_app_ids_are_rejected` *and* the
hole-demonstration test; dropping `_require_id_str` fails 7 cases; reverting the
`yaml.YAMLError` catch fails 3. Nothing passes with a guard deleted.

Hard rule #6 in `CLAUDE.md` gained a sentence, since this closes a hole in it.

98 → **113** tests.

### CG-24 · Clear `PubSubPuller`'s flag — `pull()` **and** `acknowledge()`  ✅ shipped 2026-07-30 · PR-PENDING

The flag `adapters/pubsub.py` had carried since CG-1: *"the live pull used an
ad-hoc client, NOT PubSubPuller — this class is still unexercised against
Google."* Driven through the real class on 2026-07-30 and cleared, both halves.

**`acknowledge()` is the half worth dwelling on, because the evidence is
stronger than a smoke test can produce.** Acking message id
`20755182577634163` removed **only** that message, while two other unacked ids
(`21328572002996378`, `21339851456542226`) kept redelivering across a 60-second
poll. A batch ack followed by an empty subscription would have proven the
subscription *drained* — not that the **right** message was acked, and an ack
that removed too much would look identical. Selective redelivery is what
separates those, and it is what makes the `_pubsub_message_id` dedupe key
trustworthy rather than assumed.

**Also closed here, deliberately as a non-task:** the
`chat-api-push@system.gserviceaccount.com` publisher grant. Both candidate
principals were bound in `chat-gateway-prod`; that project is **deleted**, so
which one delivered the first event can never be determined. `CLAUDE.md` now
says **CLOSED BY CIRCUMSTANCE, not answered — stop carrying it as open work**,
because it had been sitting in a list titled after the ⚠ flag and reading like a
gap someone should close. It is an unanswerable question about a system that no
longer exists.

**Flag-drift sweep, prompted by CG-4's review having caught exactly this once
already** — and this time the stale table was Builder's own, written two PRs
earlier:

- `README.md`'s per-seam table listed Chat API send and Pub/Sub pull/ack as
  `⚠ LIVE-UNVERIFIED`. Both had been cleared by CG-5 and this item. Rewritten,
  and it now points at `CLAUDE.md` as authoritative instead of restating detail
  that will drift again.
- `docs/consumers/jobhunt.md` said the end-to-end run *"needs the tier-2 Google
  Cloud setup (LIVE-UNVERIFIED seams) — first smoke test once the Chat app +
  subscription exist."* Three things wrong at once: the seams are verified, the
  app and subscription **exist**, and the actual blocker is one missing
  `callback_url`. Corrected to say so.
- `CLAUDE.md`'s list heading was literally *"⚠ LIVE-UNVERIFIED (updated
  honestly)"* while most entries under it were cleared — a title that invites a
  reader to assume every child still carries the flag. Renamed to
  **Verification ledger**, with the residue stated in one line up front: **every
  adapter's error branches, and nothing else.**

Docstrings and docs only. Suite unchanged at **98**.

### CG-5 · Split `chat_api.py`'s flag — and BOTH halves cleared, not one  ✅ shipped 2026-07-30 · PR-PENDING

**The plan for this item is superseded by evidence, and that is recorded rather
than quietly acted on.** Part C said `send()` clears and `send_text()` **keeps**
its flag, with the instruction *"be precise about the split."* That was written
before the 2026-07-30 live session, which cleared `send_text()` too. Builder did
not decide this — the evidence did, and the user named it explicitly.

| Seam | Status |
|---|---|
| `GoogleServiceAccountTokens` | ✅ cleared — minted the token `send()` used; re-exercised 2026-07-30 with the live key |
| `send()` | ✅ cleared 2026-07-29 — text + Cards v2 posted as the app, response carried `sender: {displayName: "Agent Comms", type: BOT}` |
| `send_text()` | ✅ cleared 2026-07-30 — **both branches** |

**Why `send_text()`'s two branches were driven separately, and why that matters
more than the count of flags cleared.** They fail separately and each carries a
different guarantee:

- `thread_name` set → posted into `spaces/AAQAgjGR7J4/threads/_CWBxuQ8MlU`. This
  is jobhunt **R7**'s in-thread failure notice *and* **R4**'s authorization
  refusal — the paths that tell a user their tap did not land, or that they were
  not allowed to make it. A silent failure here is a silent failure of exactly
  those guarantees, which is why the plan singled this method out as the one not
  to clear cheaply.
- `thread_name=None` → posted at top level. The no-thread fallback, where a naive
  implementation sends `{"thread": {"name": null}}` and is rejected.

**What did NOT clear, stated because a per-method flag invites exactly this
mistake:** `send()`'s `thread.threadKey` + `messageReplyOption` branch. The live
`send()` posts were unthreaded, and `send_text()`'s clear does **not** reach it —
that method threads by `thread.name`, a different field on a different request
shape. Both non-200 branches and the `httpx.HTTPError` branch also stay
unexercised. The module docstring now carries a three-line status table so the
next reader cannot generalize from one method to the other.

Noted while in the file, and it is the contrast that makes **CG-23** concrete:
`send_text()`'s error path already raises with the HTTP **status only**, while
`send()` twelve lines above still interpolates `resp.text[:200]`. One file,
two standards, and the lax one is on the method that handles arbitrary content.

**Also corrected here, because it is actively dangerous rather than merely
stale:** `CLAUDE.md` described the Cloud resources of `chat-gateway-prod` and
pointed at `iac/chat-gateway-sa.json` as the SA key. That project is **deleted**
and that key is **dead**. A reader following it would try to authenticate with a
credential for a project that no longer exists. Replaced with `chat-gateway-gw`
(`#860649224827`) and `chat-gateway-sa-gw.json`, with the dead path named as dead
so its presence on disk is not mistaken for configuration.

`docs/consumers/jobhunt.md`'s R3/R4 status was split into a per-link table for the
same reason: "live-unverified end to end" was covering a verified parse, a
now-verified reply transport, and one link that genuinely has never happened —
an interaction reaching a jobhunt callback, which is outstanding for a
**configuration** reason (`job-hunter` has no `callback_url` set) rather than a
code one.

Docstrings and docs only. Suite unchanged at **98**.

### CG-4 · Clear `webhook.py`'s flag, drop the redundant threadKey mechanism  ✅ shipped 2026-07-30 · PR-PENDING

**The first ⚠ LIVE-UNVERIFIED flag this project has ever removed.** Verified
through the **real** `WebhookAdapter`, not a reimplementation: plain text →
`delivered`; Cards v2 passed through → `delivered`, rendering confirmed in the
space by the user.

**DEC-1 answered — the body `thread.threadKey` stays, the query parameter is
dropped.** The threading experiment (two messages per variant, distinct thread
keys, `thread.name` from Google's response as the objective signal) found all
three variants THREADED, so the two mechanisms are redundant. The body form wins
because `chat_api.py` already threads that way — one threading idiom across both
adapters means a future threading bug is one thing to reason about, not two — and
because it splices one less parameter into a URL that embeds `key`+`token`.

⚠ **The caveat is in the docstring, mandatorily.** All three variants also
carried `messageReplyOption` in the query, so the proven statement is exactly
*"given `messageReplyOption` is present, either `threadKey` location suffices."*
The fourth variant was never run; the docstring says so and says not to read the
result as license to drop `messageReplyOption`.

**Newly recorded, and it is the more valuable half: tier 1 is
project-independent, empirically.** On 2026-07-30, **immediately after the
`chat-gateway-prod` Cloud project was deleted**, all four webhook identities were
re-run through the real `WebhookAdapter` and all four returned `delivered`.
`docs/google-cloud-setup.md` asserted this; it is now observed. It is
load-bearing rather than trivia — a webhook URL is issued by the **space**, not by
a Cloud project, so no tier-2 change (migration, project deletion, credential
rotation, subscription breakage) can take the notification path down. That is what
makes tier 1 the floor under `aitrader`'s alerting, and `aitrader` is the tenant
with no inbound path at all.

Scope of the clear, stated rather than glossed: **the success path only.** The
non-200 branch and the `httpx.HTTPError` branch have never been exercised against
Google, and the docstring says so in prose — not a third flag word (ADR-0001 D6,
hard rule #3's cap).

Suite unchanged at **98**: docstrings, one function, two test edits.

### CG-7 · `/healthz`: subscriber liveness + quota exhaustion must affect `status`  ✅ shipped 2026-07-29 · PR-PENDING

| | |
|---|---|
| **Spec** | [design §3 (CG-7)](superpowers/specs/2026-07-29-live-verification-followups-design.md), DEC-8, DEC-9 |
| **Plan** | [Part E](superpowers/plans/2026-07-29-live-verification-followups.md) |

The brief was "make `/healthz` aware of billing/quota." Sizing it found
something larger: **a gateway whose every poll had failed since boot reported
`"status": "ok"` indefinitely** — `SubscriberLoop._run` swallowed every poll
exception with a print, `last_poll_at` was only set after a *successful* poll,
and `healthz`'s `degraded` expression read only identity env-resolution and app
keys. The subscriber block was reported and fed nothing, under a docstring
claiming "real liveness". The claude-mem failure shape hard rule #5 was written
after.

**Demonstrated, not asserted.** The same construction — a `SubscriberLoop`
driven until every poll had failed, `last_poll_at is None`, served over a real
`TestClient` — returned `"status": "ok"` with no `reasons` key before the change
and `"status": "degraded"` with two explanatory reasons after. Both new health
signals were also mutation-tested: neutering either one fails exactly its own
test and nothing else.

`status` is now computed **FROM** a `reasons` list, so nothing can degrade this
endpoint without saying why in words. Reasons cover an unresolvable identity env
var, an unset app key, an enabled subscriber that has never completed a poll, and
`POLL_FAILURE_THRESHOLD` (3) consecutive failures naming the last error's type +
status. A revoked key, a deleted subscription, a wrong subscription name and
quota exhaustion are indistinguishable from inside the loop and all fail
**closed**, so the signal is the failure *run*, not the cause.

**CG-13's leftover is in:** tier 2 enabled with
`CHAT_GATEWAY_INTERACTION_ROUTING_TARGET` unset **degrades**, because card
interactions are then impossible rather than merely unconfigured and
`/v1/identities` already reports `interaction.enabled: false`. The reason names
the variable and the value to set.

Billing stays **declared** via `GATEWAY_GCP_BILLING`, never detected — detection
would mean trusting the very metric (`topic/send_request_count`) that read zero
while a message was demonstrably flowing; the code cites where that is recorded.
Rule #2 tightened on the way past: `PubSubError` carries verb + status + reason
phrase and `resp.text[:200]` is gone, so `last_poll_error` is a TYPE and a
STATUS, never a message body — load-bearing, because `/healthz` is
unauthenticated.

**Then review found the same defect one layer in, and it is the more
interesting half.** The two counter-based reasons above are blind to a loop that
has stopped **raising** as well as stopped working. A dead polling thread — or
one wedged where it never returns — increments nothing: `consecutive_poll_failures`
sits at `0`, `last_poll_error` stays `None`, `last_poll_at` holds a real recent
timestamp. Every field reads healthy and inbound is dead **forever**. That is
rule #5's founding shape rebuilt inside the fix for rule #5's founding shape.

The root cause was that `last_poll_at` was *reported* but never compared to the
clock, so a three-week-old timestamp read exactly like a three-second-old one on
an endpoint whose docstring claims "real liveness". Closed with two signals that
are deliberately independent of the counters:

| Signal | Catches | Why the others miss it |
|---|---|---|
| `thread_alive` + `thread_started` | a thread that was started and is **not running** | direct liveness; the only non-inferential field in the block. Reported as a pair because `thread_alive: false` alone cannot distinguish a corpse from a loop nobody started — and every offline test constructs the latter |
| `seconds_since_last_poll` vs `stale_after_seconds` | a thread that is **alive but wedged** | `thread_alive` says the thread exists, not that it is progressing |

The staleness budget is `max(300s, 6 × interval)`, and the floor is chosen
against a real bound rather than taste: `PubSubPuller`'s client timeout is 90s,
so the longest a *healthy* poll can leave the timestamp untouched is ~90s plus
dispatch. 300s clears that with room and still surfaces a silent death inside one
coffee break. It scales with the interval so a deliberately slow deployment does
not alarm forever. `stop()` deliberately does **not** clear `thread_started`: a
subscriber still enabled in configuration and no longer polling is dead
regardless of who asked for it, and during a real shutdown nobody is reading
`/healthz`.

Found twice independently — by Builder while reasoning about the threshold
window, and by the pre-merge reviewer, which scored it below its reporting bar
but named it anyway as "the one theoretical way this design could still repeat
the claude-mem shape". Two independent paths to the same hole settled it.

**Verification.** All five health signals mutation-tested: neutering any one
fails exactly its own test and nothing else, and replacing
`seconds_since_last_poll` with a hardcoded `0.0` — the rule-#5 smell itself —
fails two. UAT was **40/40 against real Google endpoints**: a real `PubSubPuller`
against the real Pub/Sub REST API with a junk token returns HTTP 401, the real
`_run` loop records the failure run as `PubSubError HTTP 401`, `/healthz` on a
real uvicorn server degrades, the still-running loop then recovers on its own and
clears **only** the subscriber reasons, and finally killing the thread degrades
again with every counter still reading perfectly healthy.

**Flags: nothing cleared.** The new `PubSubPuller` test uses a mock transport,
and the UAT's real 401 proves only that a request was formed and dispatched — not
that pull/ack *semantics* work, since no message was returned and nothing was
acked. ⚠ LIVE-UNVERIFIED stands everywhere it stood; clearing it is CG-24.
89 → 98 tests.

### CG-13 · Publish `interaction_routing_target`; the portable card convention  ✅ shipped 2026-07-29 · [PR #12](https://github.com/mmackelprang/chat-gateway/pull/12)

**ADR-0001 D3 — the item that keeps the bridge cheap to leave.** `GET
/v1/identities` now returns `interaction.routing_target` (what a card puts in
`onClick.action.function`) and `interaction.action_key`, and the integration
guide documents the producer convention that consumes them, including *widgets
for input, one button to submit*.

Narrower than the ADR requires, deliberately: **opted-out tenants are never
given a routing target.** Handing one to an `allow_inbound: false` app invites
it to build cards whose interactions the gateway would discard; `aitrader` gets
`enabled: false` and the reason names hard rule #6. An unset routing target
likewise returns `enabled: false` with the reason rather than a half-answer — a
producer that guesses ships cards whose taps fail in front of a user.

UAT closed the loop the docs promise rather than asserting it: fetch the
convention over real HTTP → build a card from **only** those values → have
Google echo that card back under **both** runtimes → identical `action.id` and
identical params, with the classic runtime's echoed topic path correctly
discarded. Then the routing target was changed to an HTTPS URL and the same
producer code produced a correct card — D3's "zero producer card changes on
migration" demonstrated, not claimed. 82 → 86 tests.

### CG-10 · `__cg_action__` — action identity survives topic-as-function  ✅ shipped 2026-07-29 · [PR #11](https://github.com/mmackelprang/chat-gateway/pull/11)

Implements **ADR-0001 D2 + D4**. There was deliberately no Planner plan; the
ADR was the spec.

Resolution order: `params["__cg_action__"]` (app-declared, authoritative,
popped) → Google-native sources → **`None`**, never `""`. Plus D2's mandatory
guard: a native value shaped `^projects/[^/]+/topics/[^/]+$` is a routing
artifact and is discarded — a classic-runtime hazard, because the same portable
card echoes its routing target back in `action.function` where promoting it
would yield a plausible-looking *wrong* action id, worse than an absent one.
The guard deliberately does **not** apply to `__cg_action__`; reading a value an
app declared would be the rule-#1 violation this design avoids.

D4: unresolved identity is counted at
`/healthz → subscriber.interactions_without_action_id`, rendered `interaction:?`
by the existing forwarder title, and **still forwarded** — rule #6 says forward
whole and let the tenant enforce, so a parse-quality problem must not become a
silent drop. `id_source` (`cg_param` | `google` | `null`) is the drift detector
ADR §11 trigger 3 depends on.

Review caught a real one (HIGH): `_normalize_addon` checked `invokedFunction`
*before* `payload.action.actionMethodName`, reversing D2's native order and
contradicting this PR's own inline claim that both runtimes share one order —
inherited from the pre-CG-10 code. Fixed, and pinned by a test that populates
every candidate with a distinct value so it cannot pass by coincidence.

CG-3's known-defect test was **rewritten, not deleted**, as CG-3 required.
75 → 82 tests. Flags: none cleared.

### CG-3 · Land the real add-on interaction capture  ✅ shipped 2026-07-29 · [PR #10](https://github.com/mmackelprang/chat-gateway/pull/10)

The first genuine card interaction this project has ever received, landed as
`tests/fixtures/addon-buttonclicked-event.json` behind an extended recursive
scrub guard. Guard first, fixture second — the order is the point, because a
path-guessing scrub had already failed once that day.

Verified rather than asserted: run against the **raw** capture the extended
guard flags **nine** leaves, and the three `TENANT` hits among them
(`$.chat.user.domainId` and `…space.customer` **twice**, once under the payload
and once inside the message's echoed space) are exactly the ones the previous
guard missed. The landed fixture was diffed structurally against the raw
capture — **78 leaves both sides, identical key/type tree, exactly 17 changed
leaf values**, all identity/tenant/space names.

The capture found a **defect**, not a confirmation: `action.id` normalizes to
`""` because the card routed via a Pub/Sub topic path in `action.function`,
consuming the slot Google would otherwise fill. Pinned as a named known-defect
test that CG-10 rewrites. The constructed fixture is **kept** — three of its
test docstrings were relabelled from "the shape Google sends" to "a shape we
have not observed".

Review caught a real one: the plan's own guard-regression test **re-derived**
the guard's predicate instead of invoking it, so it would have passed even with
the production assertion deleted. Rewritten to call the guard, extended to a
list-nested `customer` and to a positive case, and **mutation-tested** —
neutering the real assertion now fails the test; under the plan's version it
did not.

**Flags: nothing cleared.** `buttonClickedPayload` joins ⚠ SHAPE-VERIFIED
2026-07-29. Both captures were pulled with an ad-hoc client, not
`PubSubPuller`, which stays ⚠ LIVE-UNVERIFIED; jobhunt R3/R4 stay unverified.
70 → 75 tests.

### CG-6 · Documentation gaps: local verification, webhook sender, tier trade-off  ✅ shipped 2026-07-29 · [PR #9](https://github.com/mmackelprang/chat-gateway/pull/9)

The credential-exposure fix. Adds `docs/google-cloud-setup.md` **§8a** — an
explicit local `.env` flow (values in `.env` only; probes take an env-var
**name**, never a URL; a burn-and-recreate table, because a webhook URL cannot
be rotated in place). Documents that Google returns `sender: null` for webhook
sends, so a nameless webhook renders as **"Unknown User"**, and records the
tier trade-off with both halves observed live: tier 1 gives many named
identities and no sender, tier 2 gives a real sender (`Agent Comms`,
`type: BOT`) and exactly one identity.

**Also corrects a factual error ADR-0001 identified** — the claim that the
Google Workspace Marketplace SDK gates installability. It does not:
installability comes from the Chat API **Visibility** setting, and Google
states the Marketplace SDK's visibility/testing settings are *ignored* for
Chat. That error is why this project is on the add-ons runtime at all, so the
correction cites the ADR and warns a future reader off repeating the choice.
Also records that `pubsub.googleapis.com/topic/send_request_count` is
disqualified as a health signal, which is *why* CG-7 declares billing rather
than detecting it.

Docs + `.env.example` only; suite unchanged at 70. Review found one real
defect: the doc cited a queue item (**CG-19**) that did not exist — it does
now, filed with an explicit merge gate because it touches the IaC path. The
plan's `verify_webhook.py` snippet imported `python-dotenv`, which is not a
project dependency; replaced with a stdlib loader and **executed** against a
stub webhook to prove the example runs and that `print(result)` leaks no URL.

### CG-2 · Workspace Add-ons service agent grant + setup failure signature  ✅ shipped 2026-07-29 · [PR #6](https://github.com/mmackelprang/chat-gateway/pull/6)

Merged as `2d886e6`. (This row read `🔨 PR open` until 2026-07-29 — swept by
Planner.)

Adds the Workspace Add-ons service agent + publisher binding at parity across
`.sh` / `.ps1` / terraform, plus the failure signature: "\<app\> is not
responding", `chat.googleapis.com/errors` code 3,
`gsuiteaddons.googleapis.com/errors` code 13, zero messages in the
subscription. Records that `pubsub.googleapis.com/topic/send_request_count`
reported **zero** publishes after a message had provably published — the metric
is useless for this diagnosis; pull the subscription instead.

Review caught that the doc's pre-existing "✅ Done as of 2026-07-28" box had
become actively misleading in light of the new text, and that
`appsmarket-component.googleapis.com` was declared a prerequisite while no IaC
path enabled it — this PR's own bug class. Both fixed.

**Evidence is circumstantial, and the change says so.** Both publisher
principals are now bound, so which one delivered the first event is unprovable.
No ⚠ flag cleared.

**Known gap:** `terraform validate` was **not** run — Terraform is not
installed on the dev box. The `.tf` changes are reviewed-by-reading only, and
that path has never been applied in this project.

**Upgraded 2026-07-29: the script path is now genuinely proven.** The setup
script ran **clean end to end on a second virgin project** (`chat-gateway-gw`,
`#860649224827`), including the add-ons service-agent step this item added. Two
independent virgin-project runs is real evidence, not review-by-reading — for
the `.sh`/`.ps1` path. The Terraform path remains unapplied and unproven.

### CG-1 · Dual-format Chat event envelope normalization  ✅ shipped 2026-07-29 · [PR #5](https://github.com/mmackelprang/chat-gateway/pull/5)

Shape-detecting normalizer for **both** Google runtimes (Workspace Add-ons and
classic), raising instead of defaulting on anything unrecognized, with the real
2026-07-29 capture locked in as an anonymized fixture behind a recursive
secret-scan test. 37 → 70 tests.

Approval gate cleared by the user before implementation: DEC-3
(`envelope_format` on `InboundReply`), the `⚠ SHAPE-VERIFIED` flag vocabulary
(now defined in CLAUDE.md hard rule #3), DEC-5 (full fixture anonymization) and
DEC-7 (capability-URL redaction — a documented single-field exception to
jobhunt R3, recorded in `docs/consumers/jobhunt.md`).

Pre-merge review + UAT caught that the poison-pill protection was incomplete:
`dispatch()` was guarded only around parsing, and `poll_once()` called it
unguarded, so a `reply_fn` failure (Google 5xx on the authorization-refusal
path), a disk-write failure, or an explicit JSON `null` would leave the whole
batch un-acked and wedge inbound. `PubSubPuller.pull()` had the same wedge one
layer higher on valid-but-non-object JSON. Both fixed, with `dispatch_errors`
as a counter distinct from `unparseable_seen`.

**Flags: nothing cleared beyond spec §8.** Events demonstrably reach
`chat-gateway-sub`; the `chat-api-push@…` grant stays unproven (both principals
bound — circumstantial); `PubSubPuller` stays LIVE-UNVERIFIED; add-on
CARD_CLICKED stays unverified pending CG-3; both send paths untouched.

**Two findings deferred to Planner** — both now queued: the `_unrouted`
reserved-id hole as **CG-8**, and the opted-out-space forensic-trace trade-off as
**CG-12** (blocked on a user decision, because it changes rule-6 semantics).
