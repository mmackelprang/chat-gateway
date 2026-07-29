# Builder queue — chat-gateway

**Last updated:** 2026-07-29 (Planner — CG-2 status swept to shipped; CG-3
unblocked and rescoped; CG-4 … CG-12 queued from the first live Google Cloud
verification)

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

### CG-6 · Documentation gaps: local verification, webhook sender, tier trade-off  📋 queued

| | |
|---|---|
| **Spec** | [design §3 (CG-6)](superpowers/specs/2026-07-29-live-verification-followups-design.md) |
| **Plan** | [Part A](superpowers/plans/2026-07-29-live-verification-followups.md) |
| **Depends on** | nothing |
| **Touches** | `docs/google-cloud-setup.md`, `docs/integration-guide.md`, `.env.example` — no source, no tests |

**First because it is the credential-exposure fix.** Step 8 documents where
secrets go on the appserver and says nothing about the machine you verify from.
On 2026-07-29 that gap cost real credentials: webhook URLs were pasted into an
AI-assistant chat transcript to run a one-off send, and every one had to be
deleted in Chat and recreated. A webhook URL embeds `key`+`token` — it is a
bearer credential for posting into that space as that identity.

Adds an explicit local `.env` flow (values in `.env` only; probes take an
env-var **name**, never a URL; burn-and-recreate table), documents that Google
returns `sender: null` for webhook sends so a nameless webhook renders as
**"Unknown User"**, and records the tier trade-off both halves of which were
observed today: tier 1 gives many named identities and no sender; tier 2 gives a
real sender (`Agent Comms`, `type: BOT`) and exactly one identity.

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

**Planner recommends keeping the body `thread.threadKey` and dropping the query
parameter**, because `chat_api.py` already threads via the body, so both
adapters end up expressing threading identically; because the body form is the
`spaces.messages.create` shape rather than a webhook-only affordance; and,
weakly, because it splices one less parameter into a URL that embeds
`key`+`token`. **DEC-1 is an open question for the user** (spec §8) — confirm
before shipping.

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

### CG-3 · Land the real add-on interaction capture  📋 queued *(was ⏸ blocked — the human tapped)*

| | |
|---|---|
| **Spec** | [design §3 (CG-3)](superpowers/specs/2026-07-29-live-verification-followups-design.md), DEC-4 … DEC-7; supersedes the earlier [envelope spec §4.5, §8](superpowers/specs/2026-07-29-chat-event-envelope-normalization-design.md) |
| **Plan** | [Part D](superpowers/plans/2026-07-29-live-verification-followups.md) (supersedes the earlier plan's Part C) |
| **Depends on** | nothing |
| **Was blocked by** | a human tapping a real card button — **done 2026-07-29** |

Rescoped: the parser-tightening half moves to CG-10 (ADR-gated); this item lands
the evidence. Source capture at
`C:\Users\mark\AppData\Local\Temp\cg-fixture\addon-buttonclicked-event.json`.

Note `addon-message-event.json` is **already landed** (CG-1, PR #5) and is
byte-identical in structure to the temp copy of the same event — nothing to do
for it.

Same handling rules as CG-1: **recursive** scrub-and-verify as a **test**, not a
script, and full anonymization — this repo is public and the capture carries a
real numeric user id, an avatar token, a domain id, a customer id and an email.
A path-guessing scrub already failed once today and briefly wrote a live token to
disk; the guard is extended (`domainId`, `customer` — both new classes, the
latter appearing **twice**) rather than the fixture hand-edited.

**Does not replace the constructed fixture — both are kept.** Overwriting would
destroy the add-on ↔ classic parity coverage and silently rewrite a broken value
into an assertion of correctness. The constructed one is relabelled from "the
shape Google sends" to "a shape we have not observed," and three test docstrings
become conditional statements. Adds a test pinning `action.id == ""` as a named
defect (CG-10 rewrites it).

**Flags:** `buttonClickedPayload` joins ⚠ SHAPE-VERIFIED 2026-07-29. Nothing is
cleared. **jobhunt R3/R4 stay unverified** — the capture found a defect rather
than confirming the mapping.

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

Billing is disabled on `chat-gateway-prod` and the free tier is enormous (a real
event measured 1,926 bytes → ~2.8M events within Pub/Sub's 10 GiB/month), so
cost is a non-issue. What matters is that exhaustion fails **closed** — and for a
gateway delivering `aitrader` alerts, silent death at a quota boundary is exactly
what rule 5 exists to prevent.

Adds a typed `PubSubError` carrying status (and stops echoing `resp.text[:200]`,
a pre-existing rule-#2 smell), failure counters on the loop, and a `reasons` list
that `status` is computed from. Billing is **declared** via env, not detected —
detection means more scopes and calls, and today `topic/send_request_count` read
zero after a message had provably published.

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

## Blocked

### CG-11 · Correct `CLAUDE.md`'s selection-widget claim  ⏸ blocked · ADR

| | |
|---|---|
| **Spec** | [design §3 (CG-11)](superpowers/specs/2026-07-29-live-verification-followups-design.md) |
| **Plan** | [Part G](superpowers/plans/2026-07-29-live-verification-followups.md) — written; shipping gated |
| **Blocked by** | the ADR under `docs/architecture/` landing on `main` |

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

The facts are settled and independent of the ADR; only the **wording** needs
coordinating, because the ADR owns jobhunt's interaction model and `CLAUDE.md` is
the constitution. Part G's first task is to read the ADR and adopt its wording —
or stop and return to Planner if it contradicts this finding.

---

### CG-10 · Empty `action.id` on add-on interactions  ⏸ blocked · ADR

| | |
|---|---|
| **Spec** | [design §3 (CG-10)](superpowers/specs/2026-07-29-live-verification-followups-design.md), DEC-12 |
| **Plan** | **not written — deliberately.** Planner writes it when the ADR lands |
| **Depends on** | CG-3 (the pinning test it rewrites) |
| **Blocked by** | the ADR under `docs/architecture/` |

The real capture normalizes to `action: {"id": "", "params": {…}}`. The card's
button routed via `action.function = "<a Pub/Sub topic path>"`, so the add-ons
runtime sent no `__action_method_name__`, no `invokedFunction`, and no
`payload.action` — `_normalize_addon` consults exactly those three and falls
through `or ""` to an empty string. **Silently**, into an `InboundReply` that
looks structurally valid and would be forwarded to a tenant callback as though it
carried an action identity. That is the silent-failure class CG-1 existed to
eliminate, one layer further in.

**The *policy* — where action identity should live — is the ADR's call, not
Planner's.** Queued here is the mechanical work only: detect, fail loudly or
surface explicitly, test. A plan is not written because a plan must carry literal
code and writing one now would mean inventing the policy or filling it with
placeholders.

---

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

### CG-12 · Forensic trace for spaces owned only by opted-out tenants  ⏸ blocked · user decision

| | |
|---|---|
| **Spec** | [design §3 (CG-12)](superpowers/specs/2026-07-29-live-verification-followups-design.md) |
| **Plan** | **not written** — pending the decision |
| **Blocked by** | a user decision, because it changes hard-rule-#6 semantics |
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

**Planner recommends A**, with C available if the user wants space-level
attribution. B is not recommended. Caveat that applies to all three: `/healthz`
is unauthenticated. Planner will not implement anything here without a decision
that names hard rule #6.

---

## In flight

_(nothing)_

---

## Recently shipped

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
