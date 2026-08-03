# A published-promise inventory — design

**Date:** 2026-08-03 · **Planner** · branch `docs/cg-69-promise-inventory`
**Baseline:** `main` at `d09a07c`, suite **345 passing** (re-measured here with
`python3 -m pytest -q` — `345 passed in 33.10s`; not copied from a queue row or
from `CLAUDE.md`).

**Row this spec designs:** CG-69 (a published-promise inventory — the process
control). **One row, not two** — §10 records why the stale-citation repair the
guard demands stays inside it.

**No ⚠ verification-ledger flag is cleared, added or reworded by anything in
this document,** and nothing here touches a Google seam. `docs/architecture/` is
untouched — and §6 explains why it is also deliberately outside the guard's
scope rather than merely outside this PR's.

---

## 1. What the row asked for, and what changed

CG-69's row proposes *"a test-owned **inventory of absolute claims** in
`docs/consumers/*.md` and `docs/integration-guide.md`, each paired with the code
that makes it true, failing when a claim has no owner"*, on the reasoning that
*"none was caught by reviewing the diff, because the diff never contained the
sentence it broke"* — so the control's job is to make the claim set **enumerable
at diff time**.

Three things were measured before designing anything, and each moved the design:

1. **The row's stated cause is false.** There are clean counterexamples where the
   diff contained the sentence — one where the hunks *bracketed* it — and it was
   missed anyway (§3).
2. **The pairing mechanism the row proposes has already been tried by hand in
   this repo, and has already rotted.** 8 of the 14 code citations in the live
   consumer docs point at the wrong code **today** (§2.2). One of them is in the
   hard-rule-#6 enforcement table of a real-money tenant's contract.
3. **The row's own bug report has drifted by the mechanism it describes** (§2.1).

The conclusion is *build it*, but **inverted and much smaller** than the row
imagines: not an inventory of prose, but an **executable anchor** on the
pairings the docs already contain, plus two pins on code-side sets that are
measurably tiny. §5 states it; §8 states what it deliberately does not catch.

---

## 2. What was measured

Every number below was produced on this branch's baseline commit. The scripts
live in the session scratchpad, not in the repo; each is described precisely
enough to re-run with `grep`, `ast` and `pytest`.

### 2.1 The row cites three promise sites. All three have drifted.

| Row's citation | What the row says is there | What is there at `d09a07c` |
|---|---|---|
| `docs/consumers/aitrader.md:217` | *"no body text of yours is ever written anywhere"* | *"your contract is built on, writes **more** and keeps it for **less**"* — the quoted sentence no longer exists in that file at all; ADR-0002 replaced it |
| `docs/integration-guide.md:366` | *"never pruned"* | a blank line; the amended retention sentence is at `:375` |
| `docs/integration-guide.md:382` | *"the only copy"* | *"The **queue journal** says what is still **PENDING**"*; the surviving *"the audit file is then the only copy"* narration is at `:400` |

**This is not a criticism of the row — it is the row's own thesis, reproducing
inside the row.** A bug report about promises going stale, whose pointers went
stale in two days. It is recorded here because it is the cheapest available
demonstration that **the anchor form is the problem**, not the diligence of
whoever wrote it.

### 2.2 Line anchors vs name anchors — an A/B inside this repo

Every `<module>.py:<line>` citation in the **live** contract documents
(`docs/consumers/*.md`, `docs/integration-guide.md`, `CLAUDE.md`), checked by
reading the cited lines and comparing them to the sentence that cites them:

| # | Citation | The sentence claims it points at | What is actually at those lines | |
|---|---|---|---|---|
| 1 | `aitrader.md:37` → `auth.py:22-38` | bearer auth | `authenticate()`, lines 22-38 | ✅ |
| 2 | `aitrader.md:42` → `notifications.py:35-52` | the `/v1/notify` **Request** model | `SEVERITIES`, `SEVERITY_EMOJI`, `severity_prefix()` | ❌ `Notification` is at `:81` |
| 3 | `aitrader.md:93` → `service.py:215-216` | the tier-2 routing-target check | the tail of `_interaction_config`'s docstring | ❌ |
| 4 | `aitrader.md:106` → `registry.py:148-159` | `route_for` | `route_for` | ✅ |
| 5 | `aitrader.md:125` → `notifications.py:55-78` | *"One function"* — the **renderer** | `info_max_combined_length()` | ❌ `render` is at `:189` |
| 6 | `aitrader.md:154` → `notifications.py:81-108` | **`Deduper`** | the `Notification` pydantic model | ❌ `Deduper` is at `:230` |
| 7 | `aitrader.md:210` → `delivery.py:78-100` | *"`DeliveryLog.record()` has **no body or card parameter at all**"* | class docstring + `__init__`; `def record` begins at `:99` | ⚠ one edit from stale |
| 8 | `aitrader.md:276` → `heartbeat.py:75-85` | the weekend roll | `next_due()`'s weekend roll | ✅ |
| 9 | `aitrader.md:334` → `service.py:242-247` | `GET /v1/inbox` → **403**, hard rule #6 enforcement point 1 | the `create_app()` signature | ❌ the 403 is at `:383` |
| 10 | `aitrader.md:335` → `registry.py:272-276` | `callback_url` validation error, enforcement point 2 | exactly that | ✅ |
| 11 | `aitrader.md:336` → `adapters/pubsub.py:648-660` | the opt-out skip, enforcement point 3 | the `_unrouted` / `UNPARSEABLE` except handler | ❌ `if not app.allow_inbound:` is at `:697` |
| 12 | `aitrader.md:337` → `service.py:85-88` | the `interaction` block, enforcement point 4 | `POLL_STALE_AFTER_SECONDS` constants | ❌ `_interaction_config` is at `:210`, its reason string at `:220` |
| 13 | `aitrader.md:371` → `registry.py:161-172` | `apps_for_space` | `apps_for_space` | ✅ |
| 14 | `CLAUDE.md:328` → `adapters/pubsub.py:376` | *"app-declared, authoritative when present"* — quoted as the authority for `__cg_action__`'s behaviour on classic | a comment about `envelope_format` | ❌ the quoted line is at `:424` |

**8 clearly stale, 1 marginal, 5 accurate — a 57% rot rate.**

⚠ **The criterion, stated because two people counting this got different
answers.** A citation is **stale** when the code the sentence describes is *not
inside the cited range*; **accurate** when the range contains it, even if the
range also covers a line or two of something else; **marginal** when the range
contains only the target's opening line and is one edit from excluding it.
Row 8 (`heartbeat.py:75-85`) is **accurate** under that rule and was
independently read as stale by a second reviewer, because the range *opens* on
`status: str = "ok"` — a field declaration. It then runs through `next_due()`'s
weekend roll at `:81-85`, which is exactly what the sentence claims, so a reader
following it lands on the right code. Row 7 (`delivery.py:78-100`) is
**marginal** rather than accurate under the same rule, and the difference is not
arbitrary: `record` begins at `:99`, so 21 of the range's 23 lines are
`__init__`. **A count this row publishes must be reproducible, and "which end of
the range you read from" is precisely the ambiguity that made it not.** Under a
stricter opens-on-the-target rule the figure is **9 of 14**; under the rule above
it is 8. Either way the conclusion is unchanged and the name-anchored comparison
below is untouched.

Rows 9, 11 and 12 are three of the **four enforcement points** `aitrader.md` §13 lists under
*"Non-goal 1 — no inbound control path, **enforced** not omitted"*. That table is
this repo's answer to hard rule #6 for a tenant whose contract calls any two-way
path a security hole in a real-money system, and three quarters of it points
somewhere else.

Now the same documents' **name** anchors — a test function named in backticks:

| Name cited | Cited in | Resolves? |
|---|---|---|
| `test_card_parameters_are_an_array_in_the_real_captured_card` | `jobhunt-handoff.md:439`, `integration-guide.md:190`, `CLAUDE.md:351` | ✅ `tests/test_adapters.py:1211` |
| `test_inbound_parameter_shape_is_a_runtime_property_not_a_direction_rule` | `jobhunt-handoff.md:440`, `integration-guide.md:191`, `CLAUDE.md:352` | ✅ `:1283` |
| `test_normalize_real_classic_onchange_with_no_button_at_all` | `jobhunt-handoff.md:256`, `CLAUDE.md:466` | ✅ `:1360` |
| `test_a_job_survives_an_ABRUPT_kill_of_a_real_process` | spec `2026-08-02…:148` | ✅ `tests/test_durability.py:112` |

**8 occurrences, 4 distinct names, 0 stale.** Same documents, same authors, same
two-day window, same amount of churn underneath — and a 57%/0% split on the
anchor form alone. That is the whole argument for §5's Part 1.

⚠ **The name anchors were not GUARDED, they were merely luckier.** Nothing
checks them today; they survived because renaming a function is rarer and more
visible than a line moving. The form is doing the work, not a control. Making it
a control is cheap precisely because the form already holds.

### 2.3 The repo already has the durable convention — in the wrong documents

`<module>.py::<QualifiedName>` appears **46 times** in this repo:

| Tree | Uses |
|---|---|
| `docs/superpowers/specs/**` | 22 |
| `docs/BUILDER_QUEUE.md` | 16 |
| `docs/superpowers/plans/**` | 7 |
| `src/chat_gateway/` | 1 (`retention.py:120` → `inbox.py::_quarantine`) |
| `docs/architecture/` | 0 |
| **`docs/consumers/*.md` + `docs/integration-guide.md` + `CLAUDE.md`** | **0** |

The **working** documents — read once, by one agent, then superseded — use the
form that survives refactoring. The **durable, tenant-facing contracts** use the
form that rots, exclusively: all 14 of §2.2's citations are line numbers and not
one is a symbol. This is exactly backwards, and correcting it requires inventing
nothing: CG-69's own row already writes `inbox.py::_audit`.

### 2.4 The prose-side population, and why the row's shape is unaffordable

Lines carrying an absolute (`never`, `always`, `only`, `cannot`, `nothing`,
`guarantee`) in the row's proposed scope:

| File | Lines |
|---|---|
| `docs/integration-guide.md` | 70 |
| `docs/consumers/aitrader.md` | 76 |
| `docs/consumers/jobhunt-handoff.md` | 51 |
| `docs/consumers/jobhunt.md` | 29 |
| **total** | **226** (306 occurrences) |

226 registrations is not the real problem. **The real problem is that the same
promise text is deliberately repeated in places that must NOT be corrected.**
`grep -rho "never pruned\|the only copy" docs/ src/ CLAUDE.md` returns **93
occurrences** — one promise family — and only **7** of them are in a live
tenant contract. The other 86 are records this repo keeps verbatim on purpose:

- `docs/superpowers/plans/2026-07-31-body-retention-and-audit-hardening.md` — **24**, including *quoted test source and quoted assertions*;
- `docs/architecture/decisions/2026-07-31-journalled-message-bodies.md` — **12**, a dated decision record;
- `docs/BUILDER_QUEUE.md` — **10**, in shipped rows;
- `docs/integration-guide.md:375` — *"line previously read **"never pruned."**"*, a correction that must contain the false sentence to be a correction at all.

A guard keyed on claim TEXT cannot tell a live promise from a record of a
retired one, and this repo's most consistent editorial practice — *"the
observation stands and is deliberately left byte-for-byte as written"* — means
the retired ones outnumber the live ones. **A text-keyed guard would fight the
house style, and the fix a reader reaches for at that point is to delete the
guard.** (`tests/test_fixtures_scrubbed.py` already states this failure mode in
its own scope note: *"a guard that cries wolf is a guard that gets disabled,
which is the one failure mode this whole file exists to avoid."*)

### 2.5 The code-side populations are tiny

| Set | Count at `d09a07c` | Enumerated by |
|---|---|---|
| filesystem **path-removal** call sites in `src/` | **1** — `retention.py:441` `path.unlink()` | `grep -rn "unlink\|rmtree\|os.remove"` |
| **tenant-data directory roots** defaulted in `__main__.py` | **2** — `state` (`CHAT_GATEWAY_STATE_DIR`), `inbox-data` (`CHAT_GATEWAY_INBOX_DIR`) | `__main__.py:40,47` |
| filesystem **write** sites in `src/` | 14 | `grep` for `open(`/`write_text` |
| `/healthz` leaf keys | 42 (sweeper unconfigured) | live response |
| `/healthz` rows in the guide's table | 43 | `docs/integration-guide.md` |

**Exactly one delete site in this repo's entire history.** Instance 3 — the
*"never pruned"* breach — is a claim about that set having size zero. Pinning a
set of size 1 costs nothing and fires exactly once, on the next PR that adds a
second.

### 2.6 A plausible design, killed by measurement

Instance 7's claim — *"this counter is the only thing standing between a
silently-dropped aitrader alert and a green `/healthz`"* — is a claim about the
set of paths that swallow an exception without counting. The obvious pin is
therefore "every `except` handler that does not re-raise".

Measured: **41 `except` handlers in `src/`, 26 of which never raise.** Twenty-six
is not a pinnable set — it is a third of the error handling in the package, it
changes most PRs, and almost every member is correct. **Dropped.** §8 records
what this costs.

### 2.7 File-level anchoring would be noise

Across the last 30 commits on `main` (squash merges — one commit per PR), 15
touch `src/`:

| Module | Touched in |
|---|---|
| `service.py` | 7 of 15 (47%) |
| `delivery.py` | 5 of 15 (33%) |
| `adapters/pubsub.py` | 5 of 15 (33%) |

A control that surfaces every claim anchored to a **file** would fire on roughly
half of all code PRs, carrying dozens of rows each time. That is the alert
fatigue the brief names, arriving on day one. **Anchors must be symbol-grained,
and §5's are.**

---

## 3. Two failure modes, and the row's cause is not the discriminator

A full history sweep found **41 instances**, and the split matters more than the
total because it is what shows the control's reach:

| Category | Count | What it is |
|---|---|---|
| **(a)** a live claim about code behaviour, falsified by a **later code change** | **19** | the row's three, the four in the brief, and ten more |
| **(b)** a claim that was **wrong when written** | **11** | including today's spec §5 |
| **(c)** a **moving fact with two homes** | **4** | the test count; the `/healthz` table's own field counts |
| **(d)** an **external-world** fact that changed outside the repo | **7** | the deleted project, the renamed Chat app, the gitignored live registry |

**19 is the denominator this control is measured against** — category (a) is what
a test in this repo can see. Categories (b) and (d) are outside any guard's
reach (§8 says so plainly), and (c) is the two-homes defect the repo already
fights by hand. A headline of 41 without that split would overstate what §5
buys by a factor of two.

⚠ **Provenance, because a number's origin is part of the number.** The 41-row
enumeration is the sweep's, read back from its own table. The rows this spec's
conclusions rest on were **re-verified here by hand**, and those are the ones to
trust without further work: instance 7's reclassification to (b)
(`git log -S"except HTTPException"` → `e2602e9`, **2026-07-26**, against the
sentence's `5625c70`, **2026-08-03** — eight days); the CG-10 counterexample
(`2262bf1` / **#11** changed **150 lines** of `adapters/pubsub.py`, the file
whose docstring named *"queue item CG-10"* as open work, and `670a5d8` / **#42**
fixed it under the commit line *"pubsub.py's docstring states CG-10's defect as
current, and CG-10 shipped"*); and every row of §2.2's citation audit. **The
41-row total itself has not been re-derived here** and is carried as the sweep's
count, not as an independently reproduced one.

#### ⚠ This section shipped a false claim about its own contents. Twice.

**Recorded rather than quietly corrected, because it is the best evidence this
row will ever have for why it exists.**

The first draft carried **two different totals in one document** — *"the row's
three instances plus 19 more"* here (implying **22**) and *"any of the 26
instances"* in §4 — and neither was right. It also enumerated category (a) as
*"instances 1, 2, 3 and rows 8-17"*, which is **13**, while the table supports
**19**; six rows were dropped from the count.

The **19** was the origin of the error, and the way it went wrong is instructive:
19 is the category-(a) **total**, which already *includes* the row's three. It
was then written into an **"in addition to"** sentence, where it can never
belong. A correct number, moved one clause to the left, becomes a wrong one.

**How it was found:** not by review, and not by anyone reading the spec. It was
found when the Explore subagent that produced the sweep was asked to read its own
table back, and the numbers did not match what had been written from it — then
verified against the branch by the coordinator. **Nobody reading this document
would have caught it**, because both figures are plausible and neither is
checkable from the text. That is category (c) — a moving fact with two homes —
occurring inside the section that defines category (c), in a spec whose entire
thesis is that published numbers rot. §2.1 records the same shape happening to
CG-69's own citations; this is the second time this row has demonstrated its own
premise on itself, and it will not be the last.

**What the control would have done about it: nothing.** §5's guard reads code,
not prose, and would no more check this arithmetic than it would check a
sentence. What catches this class is Part 4 and a second reader — which is
exactly what happened. Recorded here so the limit is not overstated later.

The rows behind each, so the arithmetic above is checkable rather than asserted:

- **(a)** — rows 1, 1b, 1c, 2, 3, 3b, 4, 5, 6 (**9**, the row's three and the
  brief's four, split where one change falsified sentences in more than one
  place) **+ rows 8-17** (**10**, found by the sweep) = **19**. ⚠ *An earlier
  draft wrote this as "instances 1, 2, 3 and rows 8-17" and got 13 — the six
  sub-lettered and brief-supplied rows were simply dropped.*
- **(b)** — instance 7 **+ rows 18-27** = **11**. ⚠ **Instance 7 belongs here,
  not in (a)**, and the distinction is load-bearing rather than pedantic:
  `service.py::_monitor_notify`'s `HTTPException` catch dates to `e2602e9`
  (v0.1.0, 2026-07-26), **eight days before** the sentence claiming otherwise was
  written. Filing it under (a) would imply a control that watches for code
  changes could have caught it. Nothing changed. Nothing could have.
- **(c)** — rows 28-31 = **4**: the test count (stale at 98, 140, 190, 202, 268,
  333) and the `/healthz` table's own field counts, **wrong five times** (CG-64
  4→5; CG-65 5/4→6/5; CG-68 →17/8/7; CG-72 12 rows vs 11 keys; CG-74
  →43/18/21/14).
- **(d)** — rows 32-38 = **7**: the deleted `chat-gateway-prod`, the renamed Chat
  app, the gitignored live registry, and four more.

**Of the 41, fourteen were supplied in the brief and twenty-seven were found by
the sweep** — but six of those fourteen were named by exact wording from
`CLAUDE.md`, so **27 is the figure that survives challenge** as independently
found, not 41.

### 3.1 The diff-containment hypothesis is falsified

Four counterexamples, strongest first:

1. **CG-10 (#11) — the killer.** `adapters/pubsub.py`'s module docstring said the
   real capture *"yields `action.id == ""`"* and named *"queue item CG-10"* as
   **open work**. CG-10 then rewrote 150 lines of **that same file** and made
   both sentences false. The false text sat at `:26-27`, `:73` and `:316-318`;
   the diff's hunks landed one line after `:73` and bracketed `:316-318`. The
   diff contained the file, the author had it open, and the sentence **named the
   row being executed**. Missed — then missed **again** by CG-21's dedicated
   inventory sweep, and not fixed until #42, two days and ten PRs later.
2. **CG-72 (#56).** Two `/healthz` staleness strings were **written and falsified
   inside one PR** — same file, same author, same session. Only pre-merge review
   caught them.
3. **CG-32 (#32).** The diff *did* contain a consumer doc — 44 lines of
   `aitrader.md` describing the very behaviour — and still missed the one-line
   summary of the same behaviour in `integration-guide.md`.
4. **Instance 7.** The falsifying code (`service.py::_monitor_notify`) has behaved
   that way since `e2602e9`, the v0.1.0 initial build, **eight days before** the
   sentence was written. Diff-containment is undefined; the claim was asserted
   without measurement.

**Diff-containment is neither necessary nor sufficient.** A control built on
*"did the diff touch the file holding the sentence"* would have caught none of
these four.

### 3.2 What actually separates caught from missed

Every catch in the history traces to one of four mechanisms, and **none of them
is diff review**:

1. **A falsification bullet pre-declared in the queue row, before any code.**
   CG-75's row carried *"⚠ It falsifies two unauthenticated `/healthz` strings
   and must correct them in its own PR"*; CG-74's plan step B4 is literally
   *"two strings lose their hedge"*. Both: caught, zero residue. Cost: one
   bullet at planning time. **This is the cheapest and most reliable mechanism
   in the entire record, and it is free.**
2. **A standalone enumeration exercise** — ADR-0002 §2.5's *"the promise has SIX
   live homes"*; the 2026-08-01 pre-execution audit that became CG-68's Task 14.
   Note that audit found five strings the plan's own Task 13 *listed none of* —
   the same planner had already looked and come up empty.
3. **A reviewer reading the code the sentence describes.** The only thing that
   caught the two hardest cases (instance 7, and CG-72's same-PR defect).
4. **A post-hoc residue sweep of files the PR did not own.** Works, but always
   one PR late — a recovery mechanism, not a prevention one.

**Misses cluster on file OWNERSHIP, not on the diff.** Everything on `/healthz`
after CG-68 was caught *in its own PR*, because **hard rule #5 makes the
unauthenticated endpoint a named category every row is obliged to check**,
backed by exact-string tests. Everything in `docs/consumers/*` before CG-65 was
missed, because **nothing named that category and nothing tested it**.

**The design follows directly from that sentence.** The control's job is not to
enumerate claims at diff time. It is to do for the consumer contracts what rule
#5 did for `/healthz`: **make them a named category with a test-backed
obligation, so that a change underneath them turns the suite red rather than
relying on somebody choosing to go looking.**

---

## 4. Options considered

**Option A — the row as written: a registry of absolute claims, each paired
with an owning code path, failing when a claim has no owner.**
Rejected. 226 candidate claims (§2.4); the pairing rots at 57% (§2.2); a
text-keyed guard cannot distinguish a live promise from a deliberately-preserved
retired one (§2.4); and *"failing when a claim has no owner"* fires only when a
file disappears, which is not what happened in a single instance the sweep found.

**Option B — a `docs/PROMISES.md` inventory file, maintained by hand.**
Rejected on this repo's own most-repeated lesson: a second home for a moving
fact drifts. The test count did it six times; the `/healthz` table's self-count
did it five. An inventory file is a second home for every promise in it.

**Option C — a diff-time reporter: print every registered claim whose owning
file the diff touches.**
Rejected on §2.7 — `service.py` alone is in 47% of code PRs — and on §3.1, since
diff-containment is not the discriminator.

**Option D — make the pairings the docs already contain executable, and pin the
two code-side sets that absence-promises are about.** **Chosen.** It adds no new
artifact, uses a convention the repo already writes 37 times, has an existence
check as its only assertion (so rewording is free), and its measured populations
are 14, 1 and 2.

---

## 5. The design

Three tests in one new module, `tests/test_published_promises.py`, plus one
process change that costs nothing and has the best record in §3.2.

### Part 1 — executable anchors in the live contract documents

**Convention.** In the guarded files, a reference to code is written
`` `<module>.py::<QualifiedName>` `` — module path relative to
`src/chat_gateway/`, then `::`, then a dotted qualified name resolvable by
`ast`. Examples, all of which are the correct replacement for a stale row in
§2.2: `` `delivery.py::DeliveryLog.record` ``,
`` `adapters/pubsub.py::dispatch` ``, `` `service.py::_interaction_config` ``,
`` `notifications.py::Deduper` ``, `` `notifications.py::SEVERITY_EMOJI` ``
(module-level assignments resolve too). A test function is anchored the same
way: `` `tests/test_adapters.py::test_…` ``.

**The test asserts three things**, in the `test_error_surfaces.py` idiom —
source-level, so nothing depends on what happens to be imported:

1. **Every anchor resolves.** Parse the named module, walk `ClassDef` /
   `FunctionDef` / `AsyncFunctionDef` / module-level `Assign` building dotted
   qualnames, assert the anchor is among them. A rename or a move fails here,
   and that is the intended fire: a rename is exactly when the sentence needs
   re-reading.
2. **No bare `file.py:LINE` form survives in the guarded files.** Without this
   the rotting form creeps straight back, and the guard would report the
   converted subset as if it were the whole.
3. **The anchor count is pinned**, per file. A guard that inspects nothing
   passes everything — the same reason
   `test_the_guard_above_actually_finds_the_construction_sites` exists.

**Guarded files** (§6 argues the boundary): `docs/consumers/*.md`,
`docs/integration-guide.md`, `CLAUDE.md`.

### Part 2 — the absence-promise pins

An absence claim (*"never pruned"*, *"no body of yours is ever written"*) has no
symbol to anchor to, because it is a claim that a **set is empty or unchanged**.
So it anchors to the set.

**2a — the delete-site pin.** Every call in `src/chat_gateway/` that removes a
filesystem path (`Path.unlink`, `os.remove`, `os.unlink`, `shutil.rmtree`,
`Path.rmdir`), pinned by `module → qualified scope`. Today: exactly one,
`retention.py::RetentionSweeper` (§2.5). The failure message names the live
*"never pruned"* / *"the only copy"* promise **locations** — file plus section
heading, never a quoted sentence and never a line number, so the message cannot
itself rot the way §2.1 shows.

**2b — the tenant-data root pin.** Every directory root `__main__.py` defaults a
`CHAT_GATEWAY_*_DIR` environment variable to must be matched by a `.gitignore`
pattern. Today: `state` and `inbox-data`, both covered. This is instance 2
exactly — bodies moved into `state/` while `.gitignore` still tracked where they
used to be — and it is the one instance whose promise lived in a file that is
not prose at all.

### Part 3 — the `/healthz` table keeps its own count honest

Every leaf key of a **fully configured** `/healthz` response either has a row in
`docs/integration-guide.md`'s *Durability counters* table or appears in an
explicit exemption list with a one-line reason, and the table's stated totals
(*"forty-three rows"*, *"eighteen carry `**yes**`"*, *"twenty-one participate"*)
match what is actually there.

⚠ **Two measurements the implementer must not skip.** With no sweeper
configured, 14 documented `retention.*` rows are simply absent from the
response — so a test built on a default app would be wrong in the loud
direction. And 13 present keys (`status`, `version`, `reasons`, `registry.*`,
`inbox.pending`, `heartbeats.checks`, …) are **deliberately** not in a table
titled *Durability counters*; they are the exemption list's day-one content.

**Part 3 is the weakest of the three and is scheduled last.** It automates the
one category that is currently being caught by hand (instances 4, 5, 6). Its
justification is not those catches but the fact that this table has been wrong
about **its own field counts five times** — a self-counting table asking for a
test.

### Part 4 — the process half, which is free

Add a **`Falsifies`** field to the queue-row shape: *"which published sentences
does this row make false, and where do they live."* Empty is a valid answer;
absent is not.

§3.2's mechanism 1 is the best-performing control in this repo's entire history
and it is a bullet of prose. CG-75's row carried one and shipped with zero
residue. This costs a Planner one line and is the **only** mechanism in the
record that catches a promise **before the code that breaks it exists** —
including the type-(b) births that no test in Parts 1-3 can see.

---

## 6. Scope — what is guarded, what is not, and why

**Guarded:**

| Tree | Why |
|---|---|
| `docs/consumers/*.md` | live tenant contracts; where every un-recovered miss landed; §2.2's rot is entirely here |
| `docs/integration-guide.md` | the shared contract, owed to every consumer, amended under explicit sign-off (A4) |
| `CLAUDE.md` | the constitution, most-edited document in the repo, already holds one stale anchor (§2.2 row 14). `tests/test_fixtures_scrubbed.py` brought it inside a guard for the same reason and measured zero cost |

**Not guarded, and these are decisions rather than omissions:**

- **`docs/superpowers/specs/**` and `docs/superpowers/plans/**`.** Dated design
  records. This repo deliberately leaves their wording standing after it stops
  being true — instance 7's false sentence was found at #60's review and
  **left unedited on purpose**, recorded as *"Planner's artifact"*, and it is
  still false at `d09a07c`. A guard here would demand editing history to go
  green, and the first person to hit that would delete the guard. **This is the
  answer to "today's miss was in a spec": the spec is out of scope, and the
  reason is that the repo has already decided specs are not amended.** What
  serves that class is Part 4, at the moment the sentence is written.
- **`docs/architecture/`.** Same property, one degree stronger — an ADR is a
  decision record with a status banner, and ADR-0002 alone contains 12 copies of
  a promise it retired. Also off-limits to edit in this PR, which would make any
  red it produced unfixable here.
- **`docs/BUILDER_QUEUE.md`.** 589 absolute-carrying lines, nearly all in shipped
  rows that are history.
- **`docs/google-cloud-setup.md`.** Its load-bearing content is type (d) —
  external-world facts (console state, project existence) that no in-repo test
  can verify. Guarding anchors there would imply a coverage it cannot have.
- **The 226 absolute claims themselves.** §2.4. Not registered, not counted, not
  scanned.

**Rule #1 and rule #5 are why the two tenant documents and `CLAUDE.md` are in
and everything else is out.** A `/healthz` string is a promise to an operator
about an unauthenticated endpoint; a consumer-contract sentence is a promise to
a tenant whose contract treats a breach as a security finding. Both have a named
party who is owed the sentence. A spec's reader is the next agent in the chain,
who is owed the *reasoning* — and who is served by the reasoning staying as it
was written.

---

## 7. False positives — the question that decides whether this is theatre

**How does a claim get registered?** It does not. There is no registry. The
pairings already exist in the prose; Part 1 only changes their *form*, from a
line number to a symbol. The population is whatever the docs already cite —
14 today.

**Who maintains the pairing?** Whoever renames the symbol, at the moment they
rename it, prompted by a red suite that names the doc and line. That is one
find-and-replace. Compare the status quo: nobody maintains it, and it is 57%
wrong.

**What happens when a claim is legitimately reworded?** Nothing. **The guard
never reads a claim for meaning.** Part 1 checks that a name exists; Parts 2a/2b
check set membership. A sentence can be rewritten, softened, moved between
sections or deleted outright without turning anything red. This is the single
most important property of the design and the reason Option A was rejected:
Option A's assertions are *about the prose*, and prose in this repo changes for
good reasons weekly.

**When does it fire falsely?** Part 1: on a rename or move — which is precisely
when the sentence must be re-read, so it is not false. Part 2a: on a new delete
site — once, ever, in this repo's history so far. Part 2b: on a new tenant-data
directory. Part 3 has the only real exemption list, and it is bounded by the
13 keys measured in §2.5 and modelled on `APPROVED_INTERPOLATIONS` (7 entries,
one comment each, stable since CG-29).

**What stops the guard being emptied?** Part 1 assertion 3 pins the anchor count
per file, and assertion 2 forbids the old form. Both are lifted from
`test_error_surfaces.py`, which pins its construction-site count for the
identical reason.

---

## 8. What this does NOT catch — stated, not claimed away

- **Type (b), a claim wrong when written.** Nothing in Parts 1-3 sees it: the
  anchor resolves, the sets are unchanged, and the sentence is simply false.
  Instance 7 and rows 18-27 are all this. §2.6 measured and rejected the one
  pin that might have covered instance 7 specifically (26 swallow sites). What
  serves this class is Part 4 and a reviewer reading the code — mechanisms 1
  and 3 in §3.2 — and it is dishonest to imply a test covers it.
- **Type (d), the external world.** No in-repo test can verify a Google console
  fact. §6 keeps `google-cloud-setup.md` out for this reason.
- **Whether a claim is TRUE.** Part 1 proves a symbol exists, not that it does
  what the sentence says. `aitrader.md`'s *"`DeliveryLog.record()` has no body
  parameter"* would still pass if a `body=` parameter were added — the anchor
  resolves either way. Making *that* assertion executable is possible for this
  one claim (inspect the signature) and is **not** proposed: it is one bespoke
  test per claim, which is Option A's cost model wearing a different hat.
- **The other four consumers' documents that do not exist yet.** The guard
  covers a glob, so a new `docs/consumers/*.md` is covered automatically — but
  only for anchors it chooses to write.

---

## 9. Does `test_error_surfaces.py`'s idiom generalise? Precisely.

**Not as the row states it, and yes in an inverted form.**

What that file actually reads is **Python AST** — class definitions, call sites,
f-string slots — and it checks a property that is *decidable from the source*.
It never parses English. The prose it is described as guarding lives in the
**assertion message**, not in the assertions:

> *"Confirm the new expression carries a NAME or an HTTP STATUS and never a
> response body… then add it to APPROVED_INTERPOLATIONS."*

That is the transferable part, and Parts 2a/2b are built on exactly it: pin a
small code-side set, and put the prose obligation in the failure text.

**The cost of teaching it one new shape is on the record and it is high.**
CG-33 needed `PubSubError` — a class that builds its own f-string in
`__init__` — to join the marked set. That required `_message_assemblers`,
`_bind`, `_literal_parameters`, `_Scope` and `_super_init_calls`: roughly 180
lines of new AST machinery plus a dedicated test
(`test_a_parameter_only_resolves_for_a_scope_whose_callers_are_all_in_package`),
for **one** additional assembly shape. That is affordable only because the
guarded population is 12 construction sites and 4 classes.

**So the idiom generalises to sets of tens, not to sets of hundreds** — which is
why §2.5's populations (1, 2, 14) are in and §2.4's (226) is out. And the
closer precedent for reading *documents* is not `test_error_surfaces.py` at all:
it is **`tests/test_fixtures_scrubbed.py`**, which already scans
`docs/**/*.md`, `tests/**/*.py`, `tests/**/*.md` and root markdown. Its scope
note is the doctrine this spec follows:

> *"Scanning trees no incident has ever touched buys coverage of an unmeasured
> risk while widening the false-positive surface — and a guard that cries wolf
> is a guard that gets disabled."*

§6's exclusions are that sentence applied to promises.

---

## 10. Sequencing, and why the repair does not become a second row

Parts 1, 2 and 4 are one row — CG-69 — in that order. **Part 3 is the last task
and may be dropped** without invalidating the row; it is the only part that
needs a fully-configured runtime fixture and the only one automating a category
already being caught.

**Part 1 turns the suite red on its first run**, because 8 of the 14 anchors are
wrong (§2.2). The repair is Task 1 of the same row.

**That is the opposite of what this spec's first draft said, and the reason is
this repo's own precedent.** Splitting it off was tempting — a content edit to
two tenant contracts and to `CLAUDE.md`, including three of the four
hard-rule-#6 enforcement citations, is not obviously a test row's business, and
CG-69's own row warns about folding good ideas into open rows. But **CG-75's row
settled this exact question in the other direction**: *"⚠ It falsifies two
unauthenticated `/healthz` strings and must correct them in its own PR — rule #5
does not permit leaving a false statement standing for the duration of a second
PR."* Three of the eight stale citations are in a real-money tenant's
hard-rule-#6 enforcement table. A second row means shipping a guard that names
them and then leaving them wrong until someone clears the next row.

The scope-creep warning CG-69's row raises is about folding in a second *design*.
Task 1 is not a design — it changes **pointers, never claims**. Not one promise
is amended, softened or restated; every sentence in §2.2's table keeps its exact
wording and gains a different anchor.

---

## 11. Recommendation

**Build it — at roughly one fifth the size the row imagines, and inverted.**

- **Do build**: Part 1 (executable symbol anchors, 14 today), Part 2 (two pins
  of size 1 and 2), Part 4 (a `Falsifies` field in the queue-row shape, free).
- **Build last, droppable**: Part 3 (`/healthz` table self-count).
- **Do not build**: an inventory of absolute prose claims, in any form — not as
  a test-owned registry, not as a `docs/PROMISES.md`, not as a diff-time
  reporter. §2.4 and §4 give the measurements.

**If only one thing ships, ship Part 4.** It is a line of prose in a template,
it costs a Planner one bullet, it is the only mechanism in the record that fires
before the breaking code exists, and every row that carried one shipped with
zero residue.
