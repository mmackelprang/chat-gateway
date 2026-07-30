# Builder queue — chat-gateway

**Last updated:** 2026-07-30 (Builder — **CG-11 + CG-20 shipped as ONE PR**
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
| **Migration to option D** | **APPROVED IN PRINCIPLE** if E1 later passes — and it did. Migration is now **underway** (a fresh project is provisioned; see below). D3's portable card convention shipped as CG-13, so the exit stays cheap and must be kept that way. |
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

**Migration status: underway.** New project `chat-gateway-gw` (`#860649224827`)
is provisioned. The CG-2 setup script ran **clean end to end** on it, including
the add-ons service-agent step. That is the **second virgin-project run**, which
matters for flag discipline: CG-2's IaC was previously reviewed-by-reading only
and is now genuinely exercised. (The Terraform path is still unapplied — only
the script path has run.)

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

Remaining order: **CG-19 → CG-21 → CG-23 → CG-26** (CG-7, CG-4, CG-5, CG-24,
CG-8, CG-22+CG-9, CG-25, CG-12, CG-27, CG-28 and CG-11+CG-20 have since
shipped). **CG-29** was filed by Builder from CG-25's UAT,
**CG-30** by Builder from CG-27's verification pass, and **CG-31** by Builder
from CG-11+CG-20's pre-merge review; all three are
appended last, unprioritized — the user sets priority. CG-14 is **✖ closed as obsolete**
(user decision 2026-07-30 — the migration removed its premise; never built);
CG-19, CG-21 and CG-23 carry **merge gates** — pause and report rather than
auto-merging; CG-17 and CG-18 stay deferred and must not be executed.

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

### CG-21 · Migrate to the classic deployment (`chat-gateway-gw`)  ⚠ DONE LIVE · needs reconciliation, not execution

> **Status correction, 2026-07-30.** This row still reads as unstarted work
> below; it is not. **The migration has been executed and live-verified** — see
> ADR-0001's status banner, which records a real card through our real
> `ChatApiAdapter` on `chat-gateway-gw` returning `action.id: 'approve'` and
> `envelope_format: 'classic'`. `chat-gateway-prod` has since been **deleted**.
> Nothing here is left to build: what remains is reconciling the docs to the
> live state. Read the body below as the plan that was followed, and note that
> the merge gate still applies to the reconciliation PR because it touches the
> deploy/secret-handling path.

| | |
|---|---|
| **Policy** | [ADR-0001](architecture/decisions/2026-07-29-tier2-interaction-model.md) **D7** — parallel project, then cut over; never toggle production |
| **Depends on** | CG-20 (write the findings down before acting on them) — **met: CG-20 shipped 2026-07-30** |
| **Merge gate** | **touches the IaC / deploy / secret-handling path — Builder must pause and report before merging** |

E1 passed and E2 proved the toggle is one-way, so D7's parallel-project path is
the only one available. `chat-gateway-gw` (`#860649224827`) is provisioned and
the setup script ran clean on it.

Gateway-side cost should be near zero — that was CG-13's whole purpose. Expected
scope: two env values (`CHAT_GATEWAY_PUBSUB_SUBSCRIPTION`,
`GOOGLE_APPLICATION_CREDENTIALS`) plus
`CHAT_GATEWAY_INTERACTION_ROUTING_TARGET`, and **zero producer card changes**.
Console-only work (re-adding the app to each space, a new tier-2 sender
identity) is the user's. Rollback is switching the env values back. Tier-1
webhook identities are per-space and unaffected throughout.

**CG-20 shipped 2026-07-30, so this row's one dependency is met** — the findings
are written down, and `docs/google-cloud-setup.md` now names `chat-gateway-gw`
as the live project rather than the deleted `chat-gateway-prod`. That does not
make this startable. It still needs the user's **explicit go**, and it still
carries its **merge gate**: what remains is reconciliation on the deploy and
secret-handling path, which is exactly the class of change that pauses.

---

### CG-19 · Correct the Marketplace-SDK comment in all three IaC paths  📋 queued · ⏸ merge gate

| | |
|---|---|
| **Policy** | [ADR-0001](architecture/decisions/2026-07-29-tier2-interaction-model.md) §5 option D, §14 |
| **Depends on** | CG-6 (shipped — it corrected the same claim in the prose doc) |
| **Origin** | filed by CG-6: correcting the doc left the IaC contradicting it |
| **Merge gate** | **touches the IaC path — Builder must pause and report before merging**, per the session merge policy |

`iac/gcloud-setup.sh:28`, `iac/gcloud-setup.ps1:163` and
`iac/terraform/main.tf:76` each enable `appsmarket-component.googleapis.com`
under a comment repeating the claim CG-6 just corrected ("Without it the app
never appears under…"). Enabling the API is harmless and can stay; the comment
is the defect, because it is exactly the sentence that put this project on the
add-ons runtime.

Scope is comments only — no resource changes, no behaviour change. It is filed
separately rather than folded into CG-6 because touching `iac/` requires a user
pause, and CG-6 was the credential fix that had to ship first.

**Scope widened 2026-07-30** (CG-5's review, LOW): while in these three files,
also update the illustrative project name and key filename. `iac/gcloud-setup.sh:3,7`,
`iac/gcloud-setup.ps1:25,49` and `iac/terraform/main.tf:10` use
`PROJECT_ID=chat-gateway-prod` as the example and default `KEY_FILE` to
`chat-gateway-sa.json`. These are genuinely parameterized examples, not status
claims — which is why this is LOW and not the same finding as CG-20's false ✅
box — but an operator copy-pasting them would reuse a project name this repo has
just declared deleted and a key filename it has declared dead. Still
comments/defaults only; no resource changes.

> **⚠ Builder-filed 2026-07-30, from CG-20 — there is a FOURTH location, and it
> is not under `iac/`.** `docker-compose.yml:23` carries a commented-out mount
> `- /srv/chat-gateway/chat-gateway-sa.json:/secrets/sa.json:ro`, so the dead key
> filename survives in a file the scope line above does not name.
>
> **Left unfixed deliberately**, on three grounds: it is outside CG-20's declared
> scope, it is a deploy-path artifact rather than an IaC one, and this row already
> owns the illustrative-filename sweep — so folding it in here keeps one item
> responsible for the whole filename rather than splitting it across two PRs.
>
> **LOW, and the reason is specific:** it is a **host-side example path**, not a
> repo file. It is commented out, and `/srv/chat-gateway/` is the appserver
> deploy target where the operator puts whatever key they actually minted. It
> misleads a reader about the *filename*; it cannot cause the compose file to
> mount a dead key, because nothing is mounted until somebody uncomments it and
> edits the path anyway.

---

### CG-23 · The `resp.text[:200]` echo survives in both sibling adapters  📋 queued · ⏸ merge gate

| | |
|---|---|
| **Rule** | **hard rule #2** — secrets are env-only; error paths name the identity, not the URL |
| **Origin** | filed by CG-7: fixing this in `PubSubError` left two siblings with the identical defect |
| **Depends on** | nothing (CG-4 and CG-5 touch these files' docstrings only and do not collide) |
| **Merge gate** | **touches the secret-handling path — Builder must pause and report before merging**, per the session merge policy |

CG-7 removed `resp.text[:200]` from the Pub/Sub error path on the grounds that
**a Google error body can quote the request, and the request path names the
subscription.** That argument applies with *more* force two files over:

| Location | What the URL embeds |
|---|---|
| `src/chat_gateway/adapters/webhook.py:64` | `key` **and** `token` — the webhook URL *is* a bearer credential for posting as that identity |
| `src/chat_gateway/adapters/chat_api.py:83` | a space id (non-secret) — lower severity, same class |

Two things make this worth its own item rather than a shrug:

1. **The same file already does it correctly.** `chat_api.py:103`
   (`send_text`, the jobhunt R7 / R4 path) raises with **status only**. So the
   file contradicts itself, and the wrong half is the one on the
   credential-bearing adapter.
2. **We do not control the body.** Whether Google echoes the request today is
   not the question — rule #2 is written so the answer does not have to be
   known. `docs/google-cloud-setup.md` §8a exists because a webhook URL leaked
   once already, and there is no rotate-in-place: recovery is delete-and-recreate
   the webhook by hand.

Expected shape: the `PubSubError` treatment applied to `WebhookError` and
`ChatApiError` — verb/identity + HTTP status + reason phrase, no body. State the
cost honestly, as CG-7 did: Google's error prose is lost, and status + phrase is
what a caller can act on. Not folded into CG-4/CG-5 because those are docstring
and flag-scope changes that auto-merge, while this changes runtime error text on
the secret-handling path and therefore needs a pause.

---

### CG-26 · The fixture guard's remaining rules have never been proven to fire  📋 queued

| | |
|---|---|
| **Rule** | **hard rule #2** — no fixture may carry a live secret or real identity |
| **Origin** | filed by Planner 2026-07-30 while planning CG-22+CG-9; **appended last, not prioritized** |
| **Depends on** | CG-22+CG-9 (which adds the first two of these regression tests) |
| **Touches** | `tests/test_fixtures_scrubbed.py`, `tests/fixtures/README.md`, `docs/superpowers/plans/2026-07-29-live-verification-followups.md` — tests and docs only |

`test_fixtures_scrubbed.py` carries four rule families and, before CG-22+CG-9,
had a negative test for exactly **one** of them (`TENANT_KEY`). Its own docstring
makes the argument — *"A guard that has never failed is a guard nobody has
tested"* — and then applies it once. CG-22+CG-9 adds regression tests for the
capability-URL rule and the new email rule because both are load-bearing for the
fixtures it lands. This item finishes the job:

| Rule | Proven to fire? |
|---|---|
| `TENANT_KEY` | ✅ since CG-3 |
| `SUSPECT_KEY` / `SUSPECT_VALUE` (capability URLs) | ✅ as of CG-22+CG-9 |
| `EMAIL` / `EXAMPLE_DOMAIN` | ✅ as of CG-22+CG-9 |
| `PII` — the `users/…` / `members/…` long-digit-id shape | ❌ never |
| `PII` — the `googleusercontent.com` avatar host | ❌ never |
| the `PLACEHOLDER` discrimination on a `BEGIN … PRIVATE KEY` value | ❌ never |
| `fixture_files()`'s own must-not-pass-vacuously assertion | ❌ never |

The last one is worth its own thought: `assert files, "no fixtures found — this
guard must never pass vacuously"` protects against the whole guard silently
passing on an empty directory, and nothing proves *that* assertion works either.

**Also in scope, and it is a documentation task rather than a regex task:**
record which anonymization obligations the guard genuinely **cannot** enforce,
so review knows what it is responsible for. CG-22+CG-9 starts this list with
display names and path-embedded capability tokens; it should also cover space /
message / thread ids, which the README already declares deliberately unguarded
(`docs/google-cloud-setup.md` step 8 classifies them non-secret) but does not
list as a *review* obligation anywhere.

**SCOPE WIDENED 2026-07-30 — the guard's blind spot is `docs/`, and it has now
cost us twice.** The guard walks `tests/fixtures/` only. **Nothing scans
`docs/`.** Both of this project's PII incidents landed in `docs/`, not in a
fixture — so every rule family above, however well proven, was pointed at the
wrong directory.

| | Incident | Outcome |
|---|---|---|
| 1 | the **first draft of the CG-22+CG-9 plan** hardcoded the real→synthetic mapping — real name, email, Google user ids, tenant ids and a **live capability-URL bearer token** — in a file staged for this **public** repo | caught **before push**; rewritten to name source paths, nothing reached the remote |
| 2 | `docs/superpowers/plans/2026-07-29-live-verification-followups.md:484` hardcodes the real `domainId` and `customers/C0…` as sample *"bad"* data — inside `test_guard_rejects_unmarked_tenant_identifiers` | **already public**; fix forward |

`TENANT_KEY` would have flagged incident 2 instantly *in a fixture*. In a plan
document nothing looks at it. That is the whole finding.

> **⚠ AMENDED 2026-07-30 by Builder (CG-22+CG-9) — incident 2 has a SECOND
> location, and it is not a doc.** The row above says the real tenant ids sit in
> a *plan document*. They also sit in the **live test file**:
> `tests/test_fixtures_scrubbed.py`'s `test_guard_rejects_unmarked_tenant_identifiers`
> uses the real `domainId` and `customers/C0…` as its negative-case values.
> Verified by exact-substring comparison against the raw captures; **pre-existing
> on `main`**, landed in `a2a894b` (CG-3, PR #10), and untouched by the
> CG-22+CG-9 diff. The plan doc at `:484` is a *quotation of that test*, not an
> independent leak — which is why fixing only `:484` would leave the original in
> place.
>
> It survives for a reason worth writing down: **the guard only scans
> `tests/fixtures/*.json`, so it never scans itself.** Task (a) below is scoped
> to `docs/`; on this evidence it should cover `tests/**/*.py` too, or the guard
> stays blind to the one file most likely to carry a real value on purpose —
> a negative test needs something that *looks* real, and reaching for the actual
> capture is the path of least resistance.
>
> Left unfixed deliberately: it is pre-existing, out of this PR's plan, and the
> user's fix-forward decision below already governs it. Not fixed silently, and
> not fixed unilaterally.
>
> **And a second class of value in the same directory, which the rationale above
> does NOT cover.** `tests/test_adapters.py` and `tests/test_callbacks.py` carry
> the author's real email as inline **positive-path** test data — allowlist
> values a test needs to *accept*, not realistic-looking bait for a negative
> case. The caveat further down this row already rules that a docs/tests guard
> **must tolerate the author's own name and email**, since they are in the
> authorship metadata of every commit. So these lines are **accepted, not debt**:
> whoever builds the guard must not design it to fire on them, or it gets
> disabled in a week. Recorded here precisely so they are not mistaken for the
> tenant-id finding above, which *is* debt.

Two tasks: **(a)** extend the guard (or add a sibling) to walk `docs/**/*.md` for
the same rule families — fenced code blocks and table cells included, since both
incidents hid there, **and `tests/**/*.py`, per the amendment above**;
**(b)** scrub `:484` **and the test it quotes** to synthetic values.

**User decision 2026-07-30: fix forward, do NOT rewrite public history.** A
Workspace customer id is not a credential — there is nothing to rotate — and a
force-push on a public repo breaks every clone, fork and PR ref to purge a value
that may already be indexed. Rewriting is not the same as un-publishing. Recorded
so this is not silently re-litigated.

⚠ **The docs guard must tolerate what this repo deliberately publishes**, or it
will be disabled within a week: space / message / thread ids (declared non-secret
by `docs/google-cloud-setup.md` step 8) and the author's own name and email,
which are in the authorship metadata of **every commit** and cannot be removed by
scrubbing prose. Flagging those is the failure mode to design against, not an
oversight to fix later.

**What this item is NOT.** A prior session reported PII in already-landed
fixtures. **That does not reproduce** — all four landed fixtures were swept on
2026-07-30 and every identity leaf is synthetic (`users/000…001`,
`agent-user@example.com`, `example1`, `customers/Cexample1`,
`https://example.com/…`). The debt is that the guard's coverage is unproven, not
that it failed. Recorded here so the claim is not carried forward unchallenged.

A byte-identical duplicate capture in the staging directory was also reported and
has already been deleted; there is nothing to fix. Filing a staging-directory
manifest convention was considered and **rejected** — the staging directory is
outside the repo, transient, and a convention nobody can enforce is worse than
none. The guard is the control that matters, and it runs on what lands.

---


---

### CG-29 · `poll_once`'s type-name-only print swallows the detail CG-25 just created  📋 queued

| | |
|---|---|
| **Origin** | filed by Builder 2026-07-30 from **CG-25's UAT** — measured, not predicted |
| **Depends on** | nothing (CG-25 shipped the guard that exposes it) |
| **Touches** | `src/chat_gateway/adapters/pubsub.py` — one print, plus whatever import shape the fix needs |
| **Priority** | **appended last, unprioritized.** The user sets order. |

CG-25 made `send_text()` raise `ChatApiError` on transport failure instead of a
raw `httpx` exception. That is right for callers, and it is a **measured
improvement** in the R7 delivery log. But `SubscriberLoop.poll_once`
(`adapters/pubsub.py:750`) prints `type(exc).__name__` and **discards the
message** — which is exactly where CG-25 put the distinguishing detail. On the R4
path (an authorization refusal to a non-allowlisted sender) the console line
therefore lost specificity:

| Failure | Before CG-25 | After CG-25 |
|---|---|---|
| transport (reset / DNS / timeout) | `ConnectError` | `ChatApiError` |
| non-200 from Google | `ChatApiError` | `ChatApiError` |

Two distinguishable console lines collapsed into one. Both UAT-observed, not
reasoned about — see the CG-25 PR body for the transcript. The detail is not
destroyed, only unprinted: the full message is `in-thread reply failed:
ConnectError` and `__cause__` is the original `httpx` exception.

**Do not "fix" this by widening the print.** The type-name-only rule at that line
is deliberate and hard rule #2 is its reason: a pydantic `ValidationError` embeds
the offending input value, and these events carry capability URLs. The comment
above the line says so.

**The open question, which is a design call and deliberately NOT decided here:**
gateway-authored exceptions (`ChatApiError`, `PubSubError`, `WebhookDeliveryError`)
carry messages this repo constructs and which are provably rule-#2-clean — type
name or HTTP status, never a body. Whether `poll_once` should print `str(exc)` for
*those* and stay type-only for everything else — and if so, whether the
discrimination is an `isinstance` check, a marker base class, or something that
avoids `adapters/pubsub.py` importing `adapters/chat_api.py` — is Planner's call,
not Builder's. Filed with the observation, not a prescription.

Note the R7 path does **not** have this problem: `forwarder.py:_fail_loudly` logs
the full `{exc}`, so it gained detail where `poll_once` lost it.

---

### CG-30 · `info` severity 500s on a payload every other severity accepts  🔨 in flight

| | |
|---|---|
| **Origin** | filed by Builder 2026-07-30 from **CG-27's** verification pass — **measured, not predicted** |
| **Depends on** | nothing |
| **Touches** | `src/chat_gateway/notifications.py` (`render`'s info branch), plus a test |
| **Priority** | **appended last, unprioritized.** The user sets order. |

`Notification.body` validates at `max_length=4000` (`notifications.py:40`) for
every severity. But on the **`info`** path `render` concatenates the prefix, the
title and the body into a single string and hands it to `OutboundMessage.text`,
which is capped at **4000** (`envelope.py:40-41`):

```python
body_text = text + (f"\n{n.body}" if n.body else "")   # notifications.py:61
```

`alert` and `warning` are unaffected — their body becomes a card widget, so only
the short fallback line goes through `text`.

**So a `Notification` that passes its own validation cannot be rendered**, and
the resulting `pydantic.ValidationError` is raised *inside* the request handler
where nothing catches it. The caller gets an uncaught **HTTP 500**, not the
422 that every other bad payload produces.

Measured at the endpoint through `TestClient(..., raise_server_exceptions=False)`,
not reasoned about:

| severity | `len(title) + len(body)` | Result |
|---|---|---|
| `info` | 3989 | **202** |
| `info` | 3990 | **500** |
| `alert` | 4200 | 202 |
| `warning` | 4200 | 202 |

The bound is exactly `4000 - 11`; the 11 is `"ℹ️ [INFO] "` (10 — the emoji is two
code points) plus the `\n`.

**Not fixed here because the right fix is a design call, not a one-liner**, and
CG-27 was docs-only. At least three options, with different contracts:

1. **Truncate** the body on the info path — silent data loss, but never fails.
2. **Tighten `Notification.body`'s limit** so the model rejects at 422 — honest
   status code, but the limit then differs per severity, which is surprising in
   the other direction and would need documenting.
3. **Render `info` as a card too** when it overflows — no loss, no new limit, but
   it breaks the contract's "info renders as plain text" (aitrader Feature 1).

Option 2 is probably right, but it changes an accepted request into a rejected
one, so it is the user's/Planner's call, not Builder's.

**Documented as a sharp edge in `docs/consumers/aitrader.md` §11 in the
meantime**, with the workaround (send `warning`, or truncate). aitrader is the
consumer that would hit this — its contract sends `info` for weekly reports,
which is the plausible long-body case.

> **⚠ Dev-box note for whoever builds this — you will think you broke the
> gateway, and you will not have.** Reproducing the 500 against a real uvicorn on
> the **Windows** dev box does not return a 500 to the client: the request hangs,
> and the server then stops answering *everything*, `/healthz` included, while the
> process stays alive.
>
> **That is not this bug and not a gateway defect.** It was isolated during
> CG-27's UAT: a **minimal FastAPI app containing no gateway code at all**, whose
> handler does nothing but `raise RuntimeError("tiny")`, wedges the same way on
> the same box. Any unhandled exception in a sync endpoint does it, at any
> message size. The gateway's own behaviour is the plain 500 — uvicorn logs
> `"POST /v1/notify HTTP/1.1" 500 Internal Server Error` before wedging, and
> in-process `TestClient(..., raise_server_exceptions=False)` returns 500
> cleanly.
>
> Practical consequence: **test this case in-process, not over TCP**, or you will
> lose the server on every run. Whether the wedge also happens on the Linux
> deploy target was **not** determined — it was out of CG-27's scope, and it is
> not needed to characterize CG-30.

---

### CG-31 · `forwarder.py`'s docstring names the retry **gaps** as if they were attempt times  📋 queued

| | |
|---|---|
| **Origin** | filed by Builder 2026-07-30 from **CG-11+CG-20's** pre-merge review — **measured, not reasoned** |
| **Depends on** | nothing |
| **Touches** | `src/chat_gateway/forwarder.py` — one docstring line |
| **Priority** | **appended last, unprioritized.** The user sets order. |

`src/chat_gateway/forwarder.py:9` says retries are *"short and latency-shaped
(0s/3s/7s — a human just tapped a button)"*. `BACKOFF_S = (0, 3, 7)`
(`forwarder.py:28`) is a sequence of **gaps**, not attempt times, so the three
attempts actually land at **0s / 3s / 10s** — and at **0s / 5s / 15s** in the
running gateway, because `process_due()` only runs when a poll comes round and
`SubscriberLoop`'s default `interval_seconds` is `5.0`
(`adapters/pubsub.py:695`).

**The wrong reading is the natural one.** *"latency-shaped"* invites the docstring
to be read as a schedule of *when* attempts land — which is precisely the thing
it does not say. The intent (retries are cheap and fast because a human is
waiting) is right and should survive the fix; only the numbers' meaning needs to
be unambiguous.

**Measured, not derived from the constant.** The 0/5/15 figure came from driving
the real `CallbackForwarder` with a fake clock against a genuinely closed port —
not from reading `BACKOFF_S` and adding it up.

The identical text in `docs/consumers/jobhunt.md` R7 and
`docs/consumers/jobhunt-handoff.md` **was already corrected** by CG-11+CG-20,
which was a docs-only PR and could not touch `src/`. This row is the remaining
half: the docstring is now the only place in the repo that still states it the
misleading way.

---

## Experiments

CG-15 and CG-16 **ran on 2026-07-29** and are recorded below with their results.
CG-17 and CG-18 remain deferred — and E1 lowered their value, since both probe
limitations of the add-ons runtime this project is migrating off.

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
classic migration, which is proven and underway. Keep filed — slash commands
land differently on classic (a MESSAGE carrying `message.slashCommand`, versus
add-ons' `appCommandPayload`) so if they are ever wanted, the normalizer needs
the classic shape, not this one.

### CG-18 · E4 — does `onChangeAction` work with the topic path as its function?  ⏸ deferred · largely answered sideways

Asked whether select-to-act is recoverable *under the bridge*. E1 answered the
question that actually mattered: `onChangeAction` **fires natively on classic**,
so the two-tap cost disappears at migration regardless. Only worth running if
the add-ons deployment has to be lived with longer than expected.

---


## Blocked

_(nothing — **CG-9 moved out on 2026-07-30** and has since shipped with CG-22.
Its scope changed as well as its status: the capture that arrived is **classic**,
not add-ons. Read the entry under **Recently shipped** rather than assuming the
old one.)_

---

## In flight

**CG-30** — claimed 2026-07-30 by Builder, branch `fix/cg-30-info-render-budget`.
Single worktree, one Builder. The user's fix decision is **option 2, scoped to
`info` only** — see that row.

_(Previously: **CG-11 + CG-20 shipped** as one PR on 2026-07-30, and CG-27 and
CG-28 before them. **CG-27 was worked in parallel** by a second Builder in its
own worktree; per the CG-25 concurrency incident, one worktree per Builder and
never a shared working directory.)_

---

## Recently shipped

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
