# Builder queue — chat-gateway

**Last updated:** 2026-07-29 (Planner)

This is the work list Builder clears, one PR per item. Planner appends; the
user sets priority. Builder claims the topmost `📋 queued` item whose
dependencies are all met, ships it as a PR, and marks it `✅ shipped`.

Status legend: `📋 queued` · `🔨 in flight` · `⏸ blocked` · `✅ shipped`

Before claiming anything, read `CLAUDE.md` — the six hard rules govern every
item here, and item CG-1 in particular is constrained by rules #1, #2, #3, #5
and #6 simultaneously.

---

## Queue

### CG-1 · Dual-format Chat event envelope normalization  📋 queued  · P0

| | |
|---|---|
| **Spec** | [`superpowers/specs/2026-07-29-chat-event-envelope-normalization-design.md`](superpowers/specs/2026-07-29-chat-event-envelope-normalization-design.md) |
| **Plan** | [`superpowers/plans/2026-07-29-chat-event-envelope-normalization.md`](superpowers/plans/2026-07-29-chat-event-envelope-normalization.md) |
| **Depends on** | nothing |
| **Blast radius** | `adapters/pubsub.py`, `envelope.py` (one additive field), `service.py` (one healthz key), tests + fixtures, docs. `forwarder.py` / `inbox.py` / `registry.py` untouched. |

Real bug, confirmed live on 2026-07-29: the first genuine Chat event arrived
in a **Workspace Add-ons** envelope (`commonEventObject` + `chat.messagePayload`)
and `normalize_event()` — written for the **classic** flat format — returned an
empty husk. Three defects: it fails silently (looks like a valid empty
MESSAGE), inbound routing is dead (`space` is `""`), and `CARD_CLICKED` is
broken (jobhunt's whole R3/R4 interaction path).

Ships a shape-detecting normalizer supporting **both** formats, fail-loudly on
unrecognized envelopes without wedging the subscription, and a real captured
payload as a test fixture.

**Gates beyond the usual suite-green:** the recursive fixture secret-scan test
must pass (hard rule #2 — a path-guess scrub already leaked a live token to
disk once), and the "unparseable never routes to a registered tenant" test
must pass (hard rule #6 — `aitrader` stays locked out).

**Do not** clear any ⚠ LIVE-UNVERIFIED flag beyond what spec §8 authorizes.

⚠ **Approval gate — check before claiming.** Spec §10 carries four open
questions for the user. Two change the code: **DEC-3** (add `envelope_format`
to the shared `InboundReply`) and **DEC-7** (redact `configCompleteRedirectUri`
from forwarded/audited `raw`, a deliberate exception to jobhunt R3's "forward
whole"). The plan assumes both approved and spells out exactly what to drop if
either is declined. If the user has not answered, ask — do not guess, and do
not silently ship a change to the shared envelope or to a tenant contract.

---

### CG-2 · Workspace Add-ons service agent grant + setup failure signature  📋 queued  · P1

| | |
|---|---|
| **Spec** | [`superpowers/specs/2026-07-29-chat-event-envelope-normalization-design.md`](superpowers/specs/2026-07-29-chat-event-envelope-normalization-design.md) §9 |
| **Plan** | [`superpowers/plans/2026-07-29-chat-event-envelope-normalization.md`](superpowers/plans/2026-07-29-chat-event-envelope-normalization.md) — **Part B** |
| **Depends on** | nothing (independent of CG-1; may ship in either order) |
| **Blast radius** | `iac/gcloud-setup.sh`, `iac/gcloud-setup.ps1`, `iac/terraform/main.tf`, `docs/google-cloud-setup.md`. No `src/` changes. |

The live failure that started all of this was caused by the Google Workspace
Add-ons **service agent never being provisioned**. All three IaC paths grant
publisher only to `chat-api-push@system.gserviceaccount.com`. Every fresh
deployment hits the same wall.

Also documents the failure signature so it costs the next person a minute
instead of an hour, including the Cloud Monitoring metric that proved
**useless** during diagnosis.

**Note honestly in the change:** both principals are now bound, so we cannot
prove which one delivered the event. The fix correlates strongly but the
evidence is circumstantial — the doc must say so rather than claim a clean
verification.

**No unit tests are possible** for this item (cloud IAM). The merge gate is
review + doc accuracy, not a green suite. Called out because the auto-merge
policy's "tests pass" gate does not apply cleanly here.

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

_(nothing yet — this queue was created 2026-07-29)_
