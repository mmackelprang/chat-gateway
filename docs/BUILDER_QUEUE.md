# Builder queue — chat-gateway

**Last updated:** 2026-07-29 (Builder — CG-6, CG-3, CG-10, CG-13, CG-7 shipped.
**Experiment E1 RAN AND PASSED and E2 is answered**, so the deferral below is
superseded: see "What E1 and E2 settled". CG-20 … CG-22 filed.)

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

Remaining order: **CG-25 → CG-12 → CG-11 → CG-20 →
CG-22 → CG-19 → CG-21 → CG-23** (CG-7, CG-4, CG-5, CG-24 and CG-8 have since shipped). CG-14 is now
`⏸ blocked` (E1 removed its rationale, so it needs a decision, not code);
CG-19, CG-21 and CG-23 carry **merge gates** — pause and report rather than
auto-merging; CG-9 stays blocked on a human; CG-17 and CG-18 stay deferred and
must not be executed.

**CG-23 and CG-24 were filed 2026-07-30 by Builder.** CG-23 is CG-7's review
fallout; CG-24 exists because the 2026-07-30 live session clears a flag that **no
existing queue item owns** — CG-4 is `webhook.py` and CG-5 is `chat_api.py`, so
`adapters/pubsub.py`'s module flag had no home. Neither is a re-plan: CG-23 is
one file's error text, CG-24 is a docstring whose evidence already exists.

**CG-11 is still open, and was omitted from the user's 2026-07-30 priority
list** — recorded here rather than silently skipped or silently built. The wrong
claim it exists to fix is live in `CLAUDE.md` and in `docs/consumers/jobhunt.md`
R6 as of that date, so Builder is treating it as genuinely queued. If it was
meant to be closed, say so and it comes straight back out.

---

### CG-14 · Interaction dead-man (`interaction-canary`)  ⏸ blocked · rationale superseded by E1

| | |
|---|---|
| **Policy** | [ADR-0001](architecture/decisions/2026-07-29-tier2-interaction-model.md) **§8** |
| **Blocked by** | its own justification, which E1 largely removed. Needs a decision before any code. |
| **Built?** | **No.** Nothing was implemented — flagged here rather than quietly kept. |

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

---

### CG-12 · Forensic trace for spaces owned only by opted-out tenants  📋 queued *(was ⏸ blocked · user decision)*

| | |
|---|---|
| **Spec** | [design §3 (CG-12)](superpowers/specs/2026-07-29-live-verification-followups-design.md) |
| **Plan** | **not written** — the decision below settles it; mechanism note in the plan's blocked-items section |
| **Decision** | **Option A**, user, 2026-07-29 — see the decisions table at the top |
| **Origin** | deferred to Planner by CG-1's review |

A space with registered owners who are **all** `allow_inbound: false` discards
events with zero forensic trace: `candidates` is non-empty so the `_unrouted`
fallback never fires, every candidate hits the authorization `continue`, and
nothing is written anywhere — no inbox entry, no `_unrouted` record, no counter,
nothing at `/healthz`. `aitrader`'s registry shape is exactly this.

Hard rule #6 is satisfied. Rule #5's spirit is not.

| | Stores | Rule-6 exposure |
|---|---|---|
| **A. Counter only** | one integer at `/healthz` — no space, no app id, no content | none |
| **C. Counter + metadata record** | space, event type, timestamp, dedupe key | small but real |
| **B. Counter + full audit record** | the whole redacted event under `_unrouted` | **material** — aitrader's traffic starts being persisted |

**Decided: option A.** A bare counter on `/healthz` — no space id, no app id,
no content. Pure rule-5 visibility with zero rule-6 surface change; `aitrader`'s
traffic is still never persisted anywhere. The caveat the user asked to be
carried into the code: **`/healthz` is currently unauthenticated**, which is
precisely why option A stores nothing attributable.

Mechanism (from the plan's blocked-items note): an additive
`on_suppressed(app_id, reason)` callback on `dispatch`, mirroring the existing
`on_unparseable`, with reasons `"opt_out"` and `"not_authorized"` — the
counter is incremented from it and the arguments go no further.

---

### CG-11 · Correct `CLAUDE.md`'s selection-widget claim  📋 queued *(was ⏸ blocked · ADR)*

| | |
|---|---|
| **Spec** | [design §3 (CG-11)](superpowers/specs/2026-07-29-live-verification-followups-design.md) |
| **Plan** | [Part G](superpowers/plans/2026-07-29-live-verification-followups.md) |
| **Unblocked by** | ADR-0001 merged to `main` as `22a8119`; adopt its §7 wording verbatim |

`CLAUDE.md` says *"modal dialogs are impossible over Pub/Sub transport —
selection widgets are the supported path."* **Proven wrong as written.** A
selection widget's `onChangeAction` fails exactly like a button's
(`gsuiteaddons.googleapis.com/errors` code 13, `deploymentFunction:
cgSelectProbe`) — a widget is not an interaction trigger.

What *is* true, and is now better evidenced than the claim it replaces: a
widget's **value** arrives in `commonEventObject.formInputs`, harvested at
button-submit time; on real captured data the normalizer merged
`"decision": "approve"` into `action.params`. So the pattern is *widgets for
input, one button to submit.* The modal-dialog half was never tested and stays
labelled as doc-derived inference — the old sentence's real sin was conflating
the two under one confident dash.

The facts are settled and independent of the ADR; only the **wording** needed
coordinating, because the ADR owns jobhunt's interaction model and `CLAUDE.md` is
the constitution. ADR-0001 §7 supplies the replacement wording and agrees with
this finding on all three labels (proven false / capture-verified / doc-derived
inference), so Part G adopts §7 rather than paraphrasing it.

---

### CG-20 · Document E1 + E2: the create-time-only toggle and the two capability tables  📋 queued

| | |
|---|---|
| **Origin** | E1/E2 results, 2026-07-29 — newly implied, filed by CG-13 |
| **Depends on** | nothing |
| **Touches** | `docs/google-cloud-setup.md`, `docs/architecture/decisions/2026-07-29-tier2-interaction-model.md` — docs only |

> **⚠ SCOPE WIDENED 2026-07-30, and this half is now the more urgent one.**
> CG-5's review caught that this item's original scope — record the E1/E2
> findings — did **not** cover the fact that `chat-gateway-prod` is **deleted**,
> even though `docs/google-cloud-setup.md` is the file that asserts it exists.
> CG-5 corrected `CLAUDE.md`; deferring the rest here was only legitimate if
> this row actually owned it, and it did not. It does now:
>
> | Location | Currently says | Reality |
> |---|---|---|
> | step 1 (~L34) | `gcloud projects create chat-gateway-prod` | the live project is `chat-gateway-gw` (`#860649224827`) |
> | steps 2–4 (~L45) | ✅ **Provisioned for `chat-gateway-prod`** | that project no longer exists — the ✅ is **false** |
> | step 5 (~L143) | point the console at `projects/chat-gateway-prod/topics/…` | wrong project |
> | step 8 (~L235, ~L315) | hand back / rotate `chat-gateway-sa.json` | the live key is `chat-gateway-sa-gw.json`; `iac/chat-gateway-sa.json` is **dead** |
>
> A reader following this doc today would create a second project named after a
> deleted one and wire credentials by a dead filename. Also record that the app
> is the classic **"Agent Comms"** in the **JobHunt space only**, and that tier 1
> is project-independent (four identities delivered immediately after the project
> deletion) — the doc asserts that already; it is now observed.
>
> Do **not** silently reuse the ✅ box. A provisioning claim for a deleted project
> should be rewritten as history, dated, not left looking current.

Two traps cost real time on this project and together they are the whole story
of how it ended up on the wrong runtime. CG-6 corrected the first (the
Marketplace SDK does **not** gate installability). This records the second,
**right next to it**: the *"Build this Chat app as a Google Workspace add-on"*
toggle is **create-time only** — it cannot be cleared on an existing app, so
escaping the add-ons runtime requires a new Chat app and therefore a new GCP
project.

Also record the two **live-verified** capability tables (add-ons vs classic:
card clicks, `onChangeAction`, action identity, envelope format, slash-command
shape) so nobody rediscovers any of it, and update ADR-0001 §5 option D — which
currently calls reversibility "contradictory" — plus §10/§12, whose open
questions E1/E2 have now answered.

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
| **Depends on** | CG-20 (write the findings down before acting on them) |
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

Do not start this until CG-20 lands and the user says go.

---

### CG-22 · Land the real **classic** `CARD_CLICKED` fixture  📋 queued

| | |
|---|---|
| **Origin** | E1's capture — the first real classic-format event this project has ever had |
| **Depends on** | nothing |
| **Source** | `%LOCALAPPDATA%\Temp\cg-fixture\classic-cardclicked-event.json` (already redacted at capture time) |

CG-1 built the classic parser from documentation and CG-3 could only land an
add-ons capture, so `classic-message-event.json` is **CONSTRUCTED** and the
classic `CARD_CLICKED` path had no real bytes at all. E1 produced them, and the
normalizer handled them correctly live — but an unrecorded observation is
indistinguishable from a guess in three weeks, which is exactly why the fixture
README tracks provenance.

Same handling rules as CG-3, no exceptions: **extend the guard first**, land the
fixture second, never hand-scrub by path. The capture arrives pre-redacted,
which is *not* a reason to skip the guard — run it and let it prove the file
clean. Then pin `envelope_format == "classic"`, the natively-populated
`action.id`, and the `onChangeAction` event shape (which has no add-ons
equivalent and is therefore new coverage, not parity coverage).

This also converts the classic normalizer from doc-derived to
⚠ SHAPE-VERIFIED — a real upgrade, and the last one available before CG-21.

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

### CG-25 · `send_text()` has no transport-error guard, unlike `send()`  📋 queued

| | |
|---|---|
| **Origin** | filed by CG-5's review — a code asymmetry found while checking the docstring split |
| **Depends on** | nothing (CG-5 shipped the docstrings; this is the behaviour) |
| **Touches** | `src/chat_gateway/adapters/chat_api.py` + a test |

`ChatApiAdapter.send()` wraps its POST in `try/except httpx.HTTPError` and
re-raises as `ChatApiError`, naming the identity. **`send_text()` does not wrap
it at all** — a connection reset, DNS failure or read timeout propagates as a raw
`httpx` exception.

Not a crash: `CallbackForwarder` catches broad `Exception` and logs, so nothing
goes silent. The defect is that the failure arrives **untyped**, in the one method
whose entire job is to be reliable about telling a user something went wrong:

- jobhunt **R7** — the in-thread notice that a tap did not land.
- jobhunt **R4** — the refusal shown to an unauthorized user.

So the delivery log records `ConnectError` where every other adapter path records
`ChatApiError`, and a caller cannot distinguish "Google refused us" from "we never
reached Google" without string-matching an exception type. That is the same
class of ambiguity `PubSubError` was introduced to remove in CG-7.

Expected shape: mirror `send()`'s guard — `except httpx.HTTPError` → `ChatApiError`
carrying the type name only, never the response body (that is CG-23's separate
concern, and `send_text()`'s non-200 branch is already correct on it). One test
driving a transport failure through `httpx.MockTransport`.

Note this does **not** re-open CG-5's flag clear: both of `send_text()`'s
*threading* branches were verified live. The transport-error branch was never
exercised against Google and CG-5's docstring says so.

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

### CG-9 · `ADDED_TO_SPACE` regression fixture  ⏸ blocked · needs a human

| | |
|---|---|
| **Spec** | [design §3 (CG-9)](superpowers/specs/2026-07-29-live-verification-followups-design.md) |
| **Plan** | [recipe](superpowers/plans/2026-07-29-live-verification-followups.md#cg-9--added_to_space-fixture--blocked-on-a-human) |
| **Blocked by** | a human removing and re-adding the Chat app to a space — Builder cannot do this |

The normalizer was run against a **live** `addedToSpacePayload` on 2026-07-29 and
handled it correctly — `ADDED_TO_SPACE` derived, space and sender extracted — for
an event type it had never seen. That exercised three doc-derived paths at once:
the `ADDON_PAYLOAD_TYPES` entry, the `chat.space` non-payload-sibling arm of the
three-source space resolution, and `_shape` with an empty `message`.

**The bytes were not kept**, so there is nothing to scrub. Filed rather than
dropped because an unrecorded observation is indistinguishable from a guess three
weeks from now — which is the whole reason the fixture README tracks provenance.
~60 seconds of human time; see the recipe.

---

## In flight

_(nothing)_

---

## Recently shipped

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
