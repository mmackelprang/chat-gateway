# Builder queue — chat-gateway

**Last updated:** 2026-07-29 (Builder — CG-1 shipped PR #5; CG-2 open as PR #6,
awaiting the user's merge call)

This is the work list Builder clears, one PR per item. Planner appends; the
user sets priority. Builder claims the topmost `📋 queued` item whose
dependencies are all met, ships it as a PR, and marks it `✅ shipped`.

Status legend: `📋 queued` · `🔨 in flight` · `⏸ blocked` · `✅ shipped`

Before claiming anything, read `CLAUDE.md` — the six hard rules govern every
item here.

---

## Queue

_(empty — CG-3 below is blocked on a human)_

---

## Blocked

### CG-3 · Live capture of a real interaction event  ⏸ blocked · needs a human

| | |
|---|---|
| **Spec** | [`superpowers/specs/2026-07-29-chat-event-envelope-normalization-design.md`](superpowers/specs/2026-07-29-chat-event-envelope-normalization-design.md) §4.5, §8 |
| **Depends on** | CG-1 (parser must exist), CG-2 (fresh-deploy path must work) |
| **Blocked by** | a human tapping a real card button in Google Chat — Builder cannot do this |

We have a real **MESSAGE** event. We have **no** real interaction event. The
add-on `CARD_CLICKED` mapping in CG-1 is documentation-derived and deliberately
tolerant (accepts map-or-list parameters, multiple action-id locations), and
carries a ⚠ LIVE-UNVERIFIED flag naming that specific path.

This item closes it: send a card with a button, tap it, capture the raw
envelope off the subscription, scrub it recursively, commit it as a fixture,
and tighten the parser to what Google actually sends.

Until this lands, **nobody may claim jobhunt's R3/R4 path is verified.**

---

## In flight

_(nothing)_

---

## Recently shipped

### CG-2 · Workspace Add-ons service agent grant + setup failure signature  🔨 PR open · [PR #6](https://github.com/mmackelprang/chat-gateway/pull/6)

**Not merged — deliberately paused for the user.** It touches the IaC /
secret-handling path, which falls under the user's "pause on sensitive" carve-out
from the auto-merge policy. Gates are green (review clean after fixes; the
Python suite is unaffected at 70 passing), but the merge call is the user's.

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

**Two findings deferred to Planner** (surfaced, not silently dropped — both sit
outside CG-1's blast radius and one changes rule-6 semantics):

1. `_unrouted` is not a reserved app id. An app registered under that id with
   `allow_inbound: true` would receive every unroutable and every `UNPARSEABLE`
   event from *all* spaces, because the audit path and the `or [UNROUTED]`
   fallback bypass the per-app authorization block by design. Pre-existing,
   needs a misconfiguration, one-line guard in `load_registry` — but
   `registry.py` was explicitly out of CG-1's blast radius.
2. A space owned *only* by opted-out tenants discards events with **zero**
   forensic trace: no inbox entry, no `_unrouted` record, no counter, nothing
   at `/healthz`. Rule #6 is satisfied; rule #5's spirit is not. `aitrader`'s
   registry shape is exactly this. Wants a decision, not a unilateral patch.
