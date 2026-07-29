# Builder queue — chat-gateway

**Last updated:** 2026-07-29 (Builder — CG-6 shipped; the user's ADR decisions
recorded below unblock CG-10, CG-11 and CG-12; CG-13 … CG-19 filed for the
newly-implied ADR work, the four experiments, and one IaC follow-up)

## User decisions on ADR-0001 (2026-07-29) — final, do not re-ask

The ADR's §12 open questions are answered. Recorded here because they are what
unblocks half this queue.

| ADR ref | Decision |
|---|---|
| **D2** — `__cg_action__` as the gateway-reserved action-identity key | **APPROVED**, including the guard that discards topic-path-shaped values arriving from Google-native sources. Unblocks CG-10. |
| **D6** — a third flag word | **NO.** `⚠ SHAPE-VERIFIED` stays the only addition; hard rule #3 caps the vocabulary. Routing fragility is recorded in prose + `/healthz`, never a new flag. |
| **§8** — interaction dead-man | **APPROVED** at `every:7d`, cleared by any `CARD_CLICKED`. A genuinely quiet week raising a false alarm is accepted; the remediation is one tap. Filed as CG-14. |
| **E1 / E2** — classic-deployment experiments | **DEFERRED.** Ship the bridge first. Do **not** create GCP projects or run experiments. Filed unexecuted as CG-15 … CG-18. |
| **Migration to option D** | **APPROVED IN PRINCIPLE** if E1 later passes. Nothing to build now — but do not make the bridge harder to leave: D3's portable card convention exists to keep the exit cheap and must be honoured (CG-13). |
| **DEC-1** (CG-4 threadKey) | Keep the body `thread.threadKey`, drop the query parameter. The `messageReplyOption` caveat is mandatory in the docstring. |
| **CG-12** shape | **Option A** — a bare counter on `/healthz`. No space id, no app id, no content. Pure rule-5 visibility, zero rule-6 surface change; note in code that `/healthz` is unauthenticated. |

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
one PR. Baseline for all of them: `python -m pytest -q` → **70 passed** (on the
Windows dev box use `python`, not `python3`).

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

Remaining order: **CG-10 → CG-13 → CG-14 → CG-7 → CG-4 → CG-5 → CG-8
→ CG-12 → CG-11 → CG-19.** CG-15 … CG-18 are filed deferred and must not be
executed. CG-9 stays blocked on a human.

---

### CG-10 · Empty `action.id` on add-on interactions — `__cg_action__`  📋 queued *(was ⏸ blocked · ADR)*

| | |
|---|---|
| **Spec** | [design §3 (CG-10)](superpowers/specs/2026-07-29-live-verification-followups-design.md), DEC-12 |
| **Policy** | [ADR-0001](architecture/decisions/2026-07-29-tier2-interaction-model.md) **D2** + **D4** — approved by the user 2026-07-29 |
| **Depends on** | CG-3 (the pinning test it rewrites) |

The real capture normalizes to `action: {"id": "", "params": {…}}` — the card's
button routed via `action.function = "<a Pub/Sub topic path>"`, so the add-ons
runtime sent no `__action_method_name__`, no `invokedFunction` and no
`payload.action`, and `_normalize_addon` fell through `or ""` **silently** into
an `InboundReply` that looks structurally valid.

Now unblocked and the policy is settled. Implement ADR D2's resolution order
(`parameters["__cg_action__"]` → Google-native sources → `None`), D2's mandatory
guard discarding `^projects/[^/]+/topics/[^/]+$` values arriving from the native
sources, and D4 (`None` not `""`, a `/healthz` counter, `id_source`, and the
event **still forwarded** — a parse-quality problem must not become a silent
drop).

---

### CG-13 · Publish `interaction_routing_target`; document the portable card convention  📋 queued

| | |
|---|---|
| **Policy** | [ADR-0001](architecture/decisions/2026-07-29-tier2-interaction-model.md) **D3** |
| **Depends on** | CG-10 (the reserved key must exist first) |
| **Origin** | newly implied by the ADR, unqueued until now |

Producers must not hardcode the topic path. The gateway publishes it per-app on
the authenticated `/v1/identities` response as `interaction_routing_target`,
alongside the reserved-key name, and the integration guide documents the card
convention that consumes it.

**This is the item that keeps the bridge cheap to leave.** Because identity
always rides in `__cg_action__` and the function slot always holds a
gateway-published constant, migrating deployment models requires **zero producer
card changes** — one config value moves. The user approved migration in
principle if E1 later passes; honouring D3 is what makes that approval cheap.

---

### CG-14 · Interaction dead-man (`interaction-canary`)  📋 queued

| | |
|---|---|
| **Policy** | [ADR-0001](architecture/decisions/2026-07-29-tier2-interaction-model.md) **§8** — approved by the user 2026-07-29 |
| **Depends on** | nothing (reuses `HeartbeatStore` / `HeartbeatMonitor`) |
| **Origin** | newly implied by the ADR, unqueued until now |

If Google removes topic-as-function routing the observable is **nothing at
all**: no event reaches the topic, no counter moves, no exception is raised,
`/healthz` says `ok`. That is the hard-rule-#5 failure shape exactly, and
adopting the bridge without a detector would rebuild it in a new place.

Register a gateway-internal check on `every:7d`, cleared by **any**
`CARD_CLICKED` arriving on the subscription. Accepted trade-off (user, final): a
genuinely quiet week raises a false alarm whose remediation is one tap — and an
alert that names the exact action needed to confirm or refute it is a good
alert.

---

### CG-7 · `/healthz`: subscriber liveness + quota exhaustion must affect `status`  📋 queued

| | |
|---|---|
| **Spec** | [design §3 (CG-7)](superpowers/specs/2026-07-29-live-verification-followups-design.md), DEC-8, DEC-9 |
| **Plan** | [Part E](superpowers/plans/2026-07-29-live-verification-followups.md) |
| **Depends on** | nothing |

The brief was "make `/healthz` aware of billing/quota." Sizing it found
something larger: **a gateway whose every poll has failed since boot reports
`"status": "ok"` indefinitely.** `SubscriberLoop._run` swallows poll exceptions,
`last_poll_at` is only set after a *successful* poll, and `healthz`'s `degraded`
expression reads only identity env-resolution and app keys — the subscriber block
is reported but feeds nothing. That is the claude-mem failure shape hard rule #5
was written after.

Independently re-verified 2026-07-29 (user): `adapters/pubsub.py:486` sets
`last_poll_at` only after `pull()` succeeds, `_run` (~line 495) swallows every
exception, and `service.py:220–222`'s `degraded` expression never reads the
subscriber block at all — while the docstring at `service.py:199` claims "real
liveness". A revoked key, a deleted subscription, a wrong subscription name and
quota exhaustion all fail this way and look identical.

Billing is disabled on `chat-gateway-prod` and the free tier is enormous (a real
event measured 1,926 bytes → ~2.8M events within Pub/Sub's 10 GiB/month), so
cost is a non-issue. What matters is that exhaustion fails **closed** — and for a
gateway delivering `aitrader` alerts, silent death at a quota boundary is exactly
what rule 5 exists to prevent.

Adds a typed `PubSubError` carrying status (and stops echoing `resp.text[:200]`,
a pre-existing rule-#2 smell), failure counters on the loop, and a `reasons` list
that `status` is computed from. Billing is **declared** via env, not detected —
detection means more scopes and calls, and today `topic/send_request_count` read
zero after a message had provably published (now recorded in
`docs/google-cloud-setup.md` as disqualifying that metric for any health check).

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

## Deferred — filed, NOT to be executed

The user's decision, 2026-07-29: **ship the bridge first.** Do not create GCP
projects and do not run these. They are recorded so the ADR's experiment design
is not lost, and so that a future PASS on CG-15 has somewhere to land.

### CG-15 · E1 — does a classic Pub/Sub Chat app receive `CARD_CLICKED`?  ⏸ deferred · user

Decides ADR option D, and therefore whether the topic-as-function bridge is
temporary or permanent. **Scratch GCP project only — never `chat-gateway-prod`.**
Full recipe: [ADR-0001 §10 E1](architecture/decisions/2026-07-29-tier2-interaction-model.md).
~20 minutes of console time. If it ever returns PASS, ADR §11 trigger 1 fires and
the migration is approved in principle already.

### CG-16 · E2 — is the add-on toggle reversible?  ⏸ deferred · user

Ride-along on CG-15, ~2 minutes. Gates nothing by design: ADR D7 routes around
the reversibility question with a parallel project and a cutover.

### CG-17 · E3 — do slash commands reach the topic?  ⏸ deferred · user

Decides whether the bridge has a proven floor. Until it runs, ADR option B is
"topic-as-function with no fallback" — which is why CG-14's dead-man matters
more, not less, while this stays deferred.

### CG-18 · E4 — does `onChangeAction` work with the topic path as its function?  ⏸ deferred · user

UX nicety, last in the ADR's own ordering. Settles whether §7's two-tap
choose-then-submit cost is permanent under the bridge.

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

### CG-3 · Land the real add-on interaction capture  ✅ shipped 2026-07-29 · PR-PLACEHOLDER

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
</content>
</invoke>
