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

**Standing constraint for every item here.** Today's live session cleared two
flags and no more. `PubSubPuller` stays ⚠ LIVE-UNVERIFIED — every live pull used
an ad-hoc client, never our class. The `chat-api-push@system.gserviceaccount.com`
publisher grant stays unproven — both principals are bound and which one
delivered is unknowable. `aitrader` stays `allow_inbound: false`, locked out of
every inbound path; nothing in this queue widens any tenant's inbound surface.

---

## Queue

**Order is the user's, set 2026-07-29**, with one Builder-side correction:
CG-3 was promoted above CG-10 because CG-10 *depends* on it (CG-10 rewrites the
pinning test CG-3 lands, and CG-3's fixture is the only real-data evidence
CG-10's behaviour change can be tested against). A declared dependency
outranks a preference; nothing else was resequenced. CG-3 has since shipped.

Remaining order: **CG-4 → CG-5 → CG-8 → CG-12 → CG-11 → CG-20 →
CG-22 → CG-19 → CG-21 → CG-23** (CG-7 has since shipped). CG-14 is now
`⏸ blocked` (E1 removed its rationale, so it needs a decision, not code);
CG-19, CG-21 and CG-23 carry **merge gates** — pause and report rather than
auto-merging; CG-9 stays blocked on a human; CG-17 and CG-18 stay deferred and
must not be executed.

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

### CG-4 · Clear `webhook.py`'s flag, drop the redundant threadKey mechanism  📋 queued

| | |
|---|---|
| **Spec** | [design §3 (CG-4)](superpowers/specs/2026-07-29-live-verification-followups-design.md), DEC-1, DEC-2 |
| **Plan** | [Part B](superpowers/plans/2026-07-29-live-verification-followups.md) |
| **Depends on** | nothing |

Verified live through the **real** `WebhookAdapter`: plain text → `delivered`;
Cards v2 passed through → `delivered` and rendering confirmed by the user. The
threading experiment (two messages per variant, distinct thread keys,
`thread.name` from Google's response as the objective signal) found both
mechanisms sufficient — query param only → THREADED, body only → THREADED, both
→ THREADED.

**DEC-1 is answered: keep the body `thread.threadKey`, drop the query
parameter** (Planner's recommendation, user-approved 2026-07-29). Reasons:
`chat_api.py` already threads via the body, so both adapters end up expressing
threading identically; the body form is the `spaces.messages.create` shape
rather than a webhook-only affordance; and, weakly, it splices one less
parameter into a URL that embeds `key`+`token`.

⚠ **The caveat is mandatory in the code comment.** All three variants also sent
`messageReplyOption` in the query. The proven statement is exactly *"given
`messageReplyOption` is present, either `threadKey` location suffices."* Whether
`messageReplyOption` is required at all was **not** isolated. The docstring must
not imply otherwise.

Flag clears for the success path only; the non-200 and transport-error branches
were never exercised and the docstring says so in prose (not a third flag word).

---

### CG-5 · Split `chat_api.py`'s flag: `send()` clears, `send_text()` does not  📋 queued

| | |
|---|---|
| **Spec** | [design §3 (CG-5)](superpowers/specs/2026-07-29-live-verification-followups-design.md), DEC-3 |
| **Plan** | [Part C](superpowers/plans/2026-07-29-live-verification-followups.md) |
| **Depends on** | CG-4 (touches the same `CLAUDE.md` lines — sequence to avoid a conflict) |
| **Touches** | docstrings only; the suite must stay at 70 |

`ChatApiAdapter.send()` verified live through the real class and the real
`GoogleServiceAccountTokens` provider: text and a Cards v2 card posted as the
app, response carried `sender: {displayName: "Agent Comms", type: BOT}`. That
clears the provider too.

**`send_text()` keeps its flag.** Different request shape (`thread.name`, not
`thread.threadKey`), never driven — and it is the method that tells a user their
tap did not land (jobhunt R7) and the method that refuses an unauthorized user
(R4). The flag moves from module scope to method scope; be precise about the
split. `send()`'s own threading branch was not exercised either (the live posts
were unthreaded).

---

### CG-8 · Reserve `_`-prefixed app ids (`_unrouted` hole)  📋 queued

| | |
|---|---|
| **Spec** | [design §3 (CG-8)](superpowers/specs/2026-07-29-live-verification-followups-design.md), DEC-10, DEC-11 |
| **Plan** | [Part F](superpowers/plans/2026-07-29-live-verification-followups.md) |
| **Depends on** | nothing |
| **Origin** | deferred to Planner by CG-1's review |

`_unrouted` is not a reserved app id. An app registered under that literal with
`allow_inbound: true` would receive every unroutable and every `UNPARSEABLE`
event from **all** spaces, because the audit path and the `or [UNROUTED]`
fallback bypass the per-app authorization block by design. Pre-existing, needs a
misconfiguration, but a real hole in a multi-tenant transport.

Reserves the whole `_` prefix (so the next internal bucket is safe without anyone
remembering) and rejects at registry load with an error naming the consequence.
`UNROUTED` moves from `adapters/pubsub.py` to `registry.py` — core must not
import from an adapter (hard rule #3) — and the adapter imports it back, so the
eleven existing test references keep working.

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

**Flags: nothing cleared.** The new `PubSubPuller` test uses a mock transport,
which is not a live round-trip; ⚠ LIVE-UNVERIFIED stands everywhere it stood.
89 → 95 tests.

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
