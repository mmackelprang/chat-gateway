# Builder queue — chat-gateway

**Last updated:** 2026-07-30 (Builder — **CG-33 shipped, [PR #39](https://github.com/mmackelprang/chat-gateway/pull/39) OPEN and NOT merged**:
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

Remaining order: **the prioritized list is now empty** (CG-7, CG-4, CG-5, CG-24,
CG-8, CG-22+CG-9, CG-25, CG-12, CG-27, CG-28, CG-11+CG-20, CG-30, CG-23, CG-19,
CG-32, CG-21, CG-34, CG-31, CG-29, CG-36, CG-42 and CG-26 have since shipped).
What remains — CG-33, CG-35, CG-37 — was **appended last and unprioritized**;
the user sets their order. **CG-33** was filed
by Builder from CG-23's pre-merge review, **CG-35** by Builder from CG-19,
**CG-36** by Builder from CG-32's docs pass, **CG-37** by Builder from
CG-21's inventory, and **CG-42** by Builder from CG-31's UAT; all five were
appended last, unprioritized — the user sets priority. **CG-36 and CG-42 have
since shipped**; CG-33, CG-35 and CG-37 remain queued. CG-14 is **✖ closed as obsolete**
(user decision 2026-07-30 — the migration removed its premise; never built);
CG-35 carries a **merge gate** — pause and report rather than
auto-merging; CG-17 and CG-18 stay deferred and must not be executed.

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

### CG-33 · `PubSubError`'s docstring makes a claim about its own reason phrase that is false  ✅ shipped 2026-07-30 · [PR #39](https://github.com/mmackelprang/chat-gateway/pull/39) — **OPEN, merge gate held**

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
merged.

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

### CG-35 · Two IaC leftovers CG-19 was forbidden to touch  📋 queued · ⏸ merge gate

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

### CG-37 · Two `src/` comments still name **add-ons** as the runtime we are deployed on  🔨 in flight

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

### CG-17 · E3 — do slash commands reach the topic?  ⏸ deferred · lower value after E1

Was the bridge's escape hatch. Less interesting now: the escape hatch is the
classic migration, which is proven and **done** (2026-07-29). Keep filed — slash commands
land differently on classic (a MESSAGE carrying `message.slashCommand`, versus
add-ons' `appCommandPayload`) so if they are ever wanted, the normalizer needs
the classic shape, not this one.

### CG-18 · E4 — does `onChangeAction` work with the topic path as its function?  ⏸ deferred · largely answered sideways

Asked whether select-to-act is recoverable *under the bridge*. E1 answered the
question that actually mattered: `onChangeAction` **fires natively on classic**,
so the two-tap cost disappeared at migration regardless. Its remaining condition
— *"only worth running if the add-ons deployment has to be lived with longer
than expected"* — **can no longer be met**: the add-ons deployment is gone, not
merely superseded.

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
