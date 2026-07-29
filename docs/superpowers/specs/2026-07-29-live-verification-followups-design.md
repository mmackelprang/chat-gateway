# Design spec — follow-ups from the first live Google Cloud verification

**Date:** 2026-07-29
**Status:** proposed — awaiting user review
**Queue items:** CG-3 (rescoped), CG-4 … CG-12
**Companion plan:** [`../plans/2026-07-29-live-verification-followups.md`](../plans/2026-07-29-live-verification-followups.md)
**External dependency:** the ADR under `docs/architecture/` (in flight, owned by
Architect). Four items here reference it; none of them re-decide it.

---

## 1. What happened, and why this spec exists

2026-07-29 was the first session in which this project's own code talked to real
Google endpoints. Until today every adapter was written off-site against
documentation, and every claim about them was doc-derived. That session:

- **cleared two ⚠ LIVE-UNVERIFIED seams** with evidence — the webhook send path
  and the Chat API send path, both exercised through the real classes rather
  than a reimplementation;
- **settled the threadKey param-vs-body question** that has carried a "verify on
  first live use" note since v0.1;
- **captured the project's first real card interaction**, which had been queue
  item CG-3's blocker since it was filed;
- **found three defects**, one of which (an empty `action.id`) is the exact
  silent-failure class CG-1 was written to eliminate;
- **cost a real credential exposure** — webhook URLs were pasted into an agent
  chat transcript to run a one-off send, and every one had to be deleted in Chat
  and recreated. That was a documentation gap, not an accident.

None of that is shippable as one change. This spec decomposes it into ten
independently reviewable queue items, states precisely which flags each may and
may not clear, and marks the four that are not Planner's to decide.

### 1.1 Framing: this is a flag-discipline exercise

Hard rule #3 gives this project exactly two flag words — ⚠ LIVE-UNVERIFIED and
⚠ SHAPE-VERIFIED — and one rule for using them: a flag comes off only for a real
round-trip, and it comes off only for what the round-trip actually covered. The
temptation after a successful live session is to clear more than was proven. §7
is the accounting that stops that, and every item below is scoped to what the
evidence supports and no further.

---

## 2. Goals / non-goals

**Goals**

- G1 — Retire the flags today's evidence genuinely retires, and split the ones
  it only partly retires, per method rather than per module.
- G2 — Land the real interaction capture as a permanent fixture under the same
  recursive scrub-and-verify discipline CG-1 established, extended to the new
  identifier classes this capture carries.
- G3 — Make the empty-`action.id` defect *visible* rather than silent, without
  deciding where action identity should live (the ADR's call).
- G4 — Close the documentation gap that caused a credential exposure, and record
  the tier-1 / tier-2 identity trade-off the session made concrete.
- G5 — Make `/healthz` degrade on inbound death, including the quota-exhaustion
  variety, instead of merely describing it in the response body.
- G6 — Close the `_unrouted` misconfiguration hole, and surface (not resolve)
  the opted-out-space forensic-trace trade-off.

**Non-goals**

- N1 — Deciding whether to depend on topic-as-function routing. **ADR.**
- N2 — Deciding jobhunt's interaction model. **ADR.**
- N3 — Deciding whether slash commands become the primary interaction path.
  **ADR.**
- N4 — Deciding where action identity should live. **ADR.** CG-10 queues the
  mechanical work only and is blocked until the ADR lands.
- N5 — Widening any tenant's inbound surface. Hard rule #6 is untouched by every
  item here; CG-12 is filed precisely *because* it would touch it, and is
  therefore blocked on the user rather than proposed as a patch.
- N6 — Clearing `PubSubPuller`'s flag. Every live pull today used an ad-hoc
  client. Our class remains unexercised and stays flagged.
- N7 — Clearing the `chat-api-push@system.gserviceaccount.com` publisher grant.
  Both principals are bound; which one delivered is unknowable. Unchanged.
- N8 — Rewriting the interaction *parser*. CG-3 pins what Google sent; CG-10
  changes behaviour, and only after the ADR.

---

## 3. Item-by-item design

### CG-3 — Land the real add-on interaction capture (rescoped, no longer blocked)

CG-3 has sat in **Blocked** since it was filed, waiting on "a human tapping a
real card button in Google Chat." That happened. The item is unblocked and its
scope narrows: the parser-tightening half moves to CG-10 (ADR-gated), and CG-3
becomes the evidence-landing item.

**What was captured.** A real `chat.buttonClickedPayload` from a card this
project's own `ChatApiAdapter` posted, with a `selectionInput` changed and then a
button tapped. Structurally:

| Wire location | Value class | Why it matters |
|---|---|---|
| `chat.buttonClickedPayload` | payload key | `ADDON_PAYLOAD_TYPES` maps it to `CARD_CLICKED` — correct |
| `chat.user` | the human who tapped | sender extraction is correct |
| `commonEventObject.parameters` | flat `{str: str}` map | confirms the map form; the list-form tolerance was never exercised |
| `commonEventObject.formInputs` | `{name: {stringInputs: {value: [...]}}}` | the selection widget's value, flat — no Apps Script `[""]` level |
| `commonEventObject` | **no `__action_method_name__`** | the reason `action.id` is `""` |
| `chat.buttonClickedPayload.message.cardsV2` | the whole card echoed back | the button's `action.function` is visible in it |
| `_pubsub_message_id` | present | first fixture that exercises `dedupe_key` |

**Do not replace the constructed fixture — keep both.** The obvious move is to
overwrite `addon-card-clicked-event.json` with the real bytes. That would be
wrong twice over:

1. Three existing tests depend on the constructed shape, and one of them
   (`test_action_id_parity_across_formats`) asserts add-on ↔ classic parity on
   `action.id`. On the real capture that parity **does not hold** — the add-on
   side yields `""`. Overwriting would either delete the parity coverage or,
   worse, quietly rewrite it to assert the broken value as if it were correct.
2. The constructed fixture's shape is not disproven, only unobserved. A card
   whose `action.function` is an ordinary function name may well produce
   `__action_method_name__`. Today's card routed via the topic name, which is a
   different card style, not a different runtime.

So: the real capture lands as `addon-buttonclicked-event.json`, and
`addon-card-clicked-event.json` stays — **relabelled** from "the shape we expect
Google sends" to "a shape we have not observed, kept as tolerance coverage."
Three test docstrings become conditional statements rather than assertions about
reality. That relabelling is the substance of CG-3, not a side effect.

**Scrub guard extension.** The capture carries two identifier classes the
message capture did not, and the committed guard catches neither:

- `chat.user.domainId` — an opaque Workspace domain id.
- `…space.customer` — `customers/C…`, the same tenant under another name, and it
  appears twice (payload space, and the message's echoed space).

Both need a rule in the *structural, not path-allowlist* style CG-1 established.
Real Google domain/customer ids are opaque alphanumerics with no shape to key
off, so the fixture side carries the marker instead: the value must contain
`example`, which RFC 2606 reserves and a real tenant id cannot contain. Same
trick as the zero-padded user ids, same reason — the guard must be able to tell a
fixture from a real capture without being told where to look.

Two things the capture carries that the **existing** guard already catches, and
that a path-guessing scrub would have missed — worth naming in the fixture README
because they are the near-miss:

- the **app's own sender block** (`…message.sender`) carries a real numeric user
  id and a `googleusercontent.com` proxy avatar URL. The message fixture had no
  bot sender at all, so nothing in the previous scrub had to think about it.
- the space object is echoed **twice**, once under the payload and once nested
  inside the message. A hand-scrub that fixed one would have shipped the other.

**Deliberately NOT scrubbed**, with reasons, so a reviewer does not read them as
misses:

- `projects/chat-gateway-prod/topics/chat-gateway-events`, inside the card's
  `action.function`. The project id is classified non-secret by
  `docs/google-cloud-setup.md` step 8 and already appears throughout the repo,
  and this value **is the finding** — remove it and the fixture stops
  demonstrating why `action.id` is empty.
- Space / message / thread ids are anonymized by README convention but get **no
  guard rule**, because the same step 8 classifies space IDs as safe to paste.
  Writing a guard that contradicts our own published classification would be
  worse than the convention.
- The `_pubsub_message_id`. It is a delivery id, not an identity, and keeping it
  real is what lets the fixture exercise `dedupe_key`.

One anonymization choice deserves its own line: the captured space is displayed
as `Ai Trader`. That is not a secret, but landing a fixture whose space is
`aitrader`'s would invite exactly the wrong inference in a repo where `aitrader`
is `allow_inbound: false`. It becomes `Test Room`.

**The defect gets pinned, not fixed.** CG-3 adds a test asserting
`action["id"] == ""` on the real capture, named and documented as pinning a
defect. The alternative — leaving the real behaviour untested until CG-10 —
means the one piece of ground truth we bought today sits in the repo with no
assertion on it. When CG-10 lands, that test is rewritten deliberately, which is
the point.

**Flags.** `buttonClickedPayload` joins the ⚠ SHAPE-VERIFIED 2026-07-29 line in
`adapters/pubsub.py`. That is all it earns: real bytes replayed offline. It does
**not** clear anything for jobhunt — see §7.

---

### CG-4 — Clear `webhook.py`'s flag and drop the redundant threadKey mechanism

The adapter has sent thread affinity two ways since v0.1, with a docstring note
to "verify both mechanisms against a throwaway space on first live use, and drop
whichever is redundant." That happened: two messages per variant, distinct thread
keys, `thread.name` from Google's response as the objective signal.

| Variant | Result |
|---|---|
| `threadKey` query param **and** body `thread.threadKey` (current code) | THREADED |
| `threadKey` query param only | THREADED |
| body `thread.threadKey` only | THREADED |

**Recommendation: keep the body form, drop the query parameter.**

1. **Cross-adapter uniformity, which is the strongest reason and a codebase
   reason rather than a Google one.** `chat_api.py` already expresses threading
   in the body — `body["thread"] = {"threadKey": …}` in `send()` and
   `body["thread"] = {"name": …}` in `send_text()`. Keeping the body form here
   means both adapters express threading identically, so a future threading bug
   is one idiom to reason about instead of two. Hard rule #3 confines
   Google-facing code to `adapters/` specifically to keep that surface small and
   comparable; two spellings of one concept works against it.
2. **It is the API-surface form, not the webhook-only affordance.** Body
   `thread.threadKey` mirrors the documented `spaces.messages.create` request
   body. The query parameter is webhook-specific sugar over the same call. If
   Google ever narrows one, the webhook-only spelling is the more likely
   casualty.
3. **Less splicing into a credential-bearing URL.** `WebhookAdapter.send` merges
   params into the webhook URL's existing query because that URL embeds `key` and
   `token`. Every parameter merged in is one more mutation of a secret-bearing
   string. This is a *reduction*, not an elimination — `messageReplyOption` keeps
   `copy_merge_params` alive — so it is weighted last, honestly.

The counter-argument, stated so it is on the record: the query parameter pairs
with `messageReplyOption`, which is also a query parameter, and Google documents
the two together for webhooks. Splitting them across body and query is mildly
less tidy against Google's docs. That is real but it is outweighed by (1), and it
does not change what we send — `messageReplyOption` stays either way.

**The caveat that must land in the code, stated precisely.** All three variants
carried `messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD` in the query.
The proven statement is exactly:

> *given `messageReplyOption` is present, either `threadKey` location suffices.*

Whether `messageReplyOption` is required at all was **not isolated** — a fourth
variant (threadKey with no `messageReplyOption`) was never run. The docstring
must say this in as many words, because the failure mode is a future reader
reasoning "we proved threading works from the body, so the query is unnecessary"
and dropping `messageReplyOption` too.

**Flag scope.** The send path is verified for the success case: plain text
delivered, Cards v2 passed through and confirmed rendering by the user, both
through the real `WebhookAdapter`. Not exercised: the non-200 branch and the
`httpx.HTTPError` branch. Those stay described in prose rather than under a
retained ⚠ flag — hard rule #3 permits exactly two flag words and inventing a
"partly verified" third would be worse than a precise sentence.

---

### CG-5 — Split `chat_api.py`'s flag: `send()` clears, `send_text()` does not

The module carries one ⚠ LIVE-UNVERIFIED covering everything in it. Today's
evidence covers part of it, so the flag moves from module scope to method scope.

**Cleared — `ChatApiAdapter.send()`**, verified through the real class and the
real `GoogleServiceAccountTokens` provider: a text message and a Cards v2 card
both posted as the app, and the response carried
`sender: {displayName: "Agent Comms", type: "BOT"}`. That also clears
`GoogleServiceAccountTokens` — it minted the token those calls used.

Scope, stated in the method docstring: the success path for text and cards. The
live posts were unthreaded, so `send()`'s own `thread.threadKey` +
`messageReplyOption` branch was not exercised, and neither were the non-200 or
`HTTPError` branches.

**Not cleared — `send_text()`.** It is a different request shape: `thread.name`,
not `thread.threadKey`. Nothing has ever driven it. It matters more than its size
suggests, and the docstring should say why: it is the method that tells a user
their tap did not land (jobhunt R7) and the method that refuses an unauthorized
user (jobhunt R4). A silent failure in it is a silent failure of precisely the
guarantees those requirements exist to provide.

The session also made the tier-2 identity fact concrete — one sender, a real one
— which is half of the trade-off CG-6 documents. The module docstring is the
right place to state it, since that is where a reader asks "what identity does
this send as?"

---

### CG-6 — Documentation gaps

**(a) Local verification — the gap that cost credentials.**
`docs/google-cloud-setup.md` step 8 says where secrets go *on the appserver* and
says nothing about the machine you verify from. Today that gap was filled
improvisationally: webhook URLs were pasted into an agent chat transcript to run
a one-off send. A Chat webhook URL embeds `key` and `token` — it is a bearer
credential for posting into that space as that identity. All of them had to be
deleted in Chat and recreated; there is no rotate-in-place.

The fix is a new step-8 subsection covering the local `.env` flow explicitly:
copy `.env.example` to the gitignored `.env`, put values only there, and drive
verification through code that reads `os.environ` — never a command line, a chat
message, an agent prompt, or a shell-history line that carries the value itself.
`WebhookAdapter` already names the identity rather than the URL on failure (hard
rule #2); an ad-hoc probe must be held to the same standard. The burn-and-recreate
procedure gets written down too, because it is what actually had to be done.

**(b) `sender: null` and the "Unknown User" trap.** Webhook sends return
`sender: null` from Google. Chat renders the webhook's *configured display name*
instead, so a webhook created without a name shows in the space as **"Unknown
User"**. The name and avatar are fixed at creation time and are the only identity
a tier-1 message has. Step 7 currently says "name it as the identity should
appear" without saying that omitting it produces a visibly broken result.

**(c) The tier-1 / tier-2 identity trade-off, now concrete.** Tier 1 gives as
many named identities as you create webhooks, and no sender in the response.
Tier 2 gives a real, attributable sender (`Agent Comms`, `type: BOT`) and exactly
one identity. Both halves were observed today, which turns a design note into a
documented fact. Neither tier dominates and the guide should say so rather than
implying tier 2 is simply the upgrade.

**(d) Queue hygiene.** `docs/BUILDER_QUEUE.md` still shows CG-2 as `🔨 PR open`
though PR #6 merged. Planner owns that file and sweeps it in **this** planning
PR rather than queueing it as work for Builder.

---

### CG-7 — `/healthz`: subscriber liveness and quota exhaustion must affect `status`

The brief for this item was "make `/healthz` aware of billing/quota." Reading the
code to size that turned up something larger and better-evidenced, so the item is
framed around it.

**The hole as it stands today.** `SubscriberLoop._run` catches every poll
exception, prints, and retries. `last_poll_at` is only assigned at the end of a
*successful* `poll_once`. And `healthz`'s `degraded` computation reads only
identity env-resolution and app key configuration — the subscriber block is
*reported* but feeds nothing.

So a gateway whose subscription has failed on every single poll since boot
reports `"subscriber": {"enabled": true, "last_poll_at": null}` alongside
`"status": "ok"`, indefinitely. That is the claude-mem failure shape hard rule #5
was written after: a health check that is green while the thing it monitors is
dead. Quota exhaustion is one way to reach that state; a revoked key, a deleted
subscription, and a wrong `CHAT_GATEWAY_PUBSUB_SUBSCRIPTION` are others, and all
four look identical from inside the process.

**Design.**

1. `PubSubPuller._post` raises a typed `PubSubError` carrying the HTTP status and
   reason phrase instead of a bare `RuntimeError` whose message embeds
   `resp.text[:200]`. Two wins: the loop can classify a failure without regexing
   a message, and a response body — which can quote the request, and the request
   path names the subscription — stops being echoed into a print. That echo is a
   pre-existing hard-rule-#2 smell; this removes it. The trade-off, stated
   plainly: we lose Google's error prose. Status plus reason phrase is what the
   loop can act on, and the reason phrase is a fixed HTTP string that never
   carries a value.
2. `SubscriberLoop` tracks `poll_failures`, `consecutive_poll_failures`, and
   `last_poll_error` — the last formatted as type name plus status, never a
   message body. A successful poll resets the consecutive counter and clears the
   error, so recovery is visible rather than sticky.
3. `/healthz` gains a `reasons` list and computes `status` from it. An enabled
   subscriber that has never completed a poll is a reason. So is a run of
   consecutive failures at or over a small threshold. Existing reasons (an
   unresolvable identity env var, an unset app key) move into the same list, so
   an operator learns *why* it is degraded without diffing the body against a
   known-good copy.
4. Billing is **declared, not detected** — an env var surfaced as
   `billing_declared`. Detection would mean calling the Cloud Billing or Service
   Usage API: more scopes, more IAM, more calls, against a project whose stated
   preference is fewer calls — and today's session is a direct argument against
   trusting Google's own telemetry for this, since
   `pubsub.googleapis.com/topic/send_request_count` reported zero publishes after
   a message had provably published. A declared value is weak evidence and the
   field name says so.

**Why this is the honest answer to "make healthz aware of quota."** Billing is
disabled on `chat-gateway-prod` and the free tier is enormous — a real event
measured 1,926 bytes on the wire, so Pub/Sub's 10 GiB/month is roughly 2.8M
events. Cost is a non-issue. What matters is that exhaustion fails **closed**:
pulls start failing and inbound simply stops, with no other symptom. For a
gateway that delivers `aitrader` alerts, that is the exact silent death rule #5
exists to prevent — and the signal for it is consecutive poll failures, not a
billing API.

---

### CG-8 — Reserve `_`-prefixed app ids

Deferred to Planner by CG-1's review. `_unrouted` is the audit bucket for
unroutable and `UNPARSEABLE` events, and the paths that write to it — the
`except` branch in `dispatch` and the `or [UNROUTED]` fallback — bypass the
per-app authorization block by design, because an unparseable event has no space
and cannot be authorized against anything. An app registered under that literal
id with `allow_inbound: true` would therefore receive every unroutable and every
unparseable event from every space, through `/v1/inbox`, with no rule-#6 check
ever running. It is pre-existing and needs a misconfiguration, but in a
multi-tenant transport it is a real hole.

**Design:** reserve the whole `_` prefix rather than the one literal, so the next
internal bucket is safe without anyone remembering to add it, and reject at
registry load with an error that explains the consequence rather than just
naming the rule.

**Layering note.** `UNROUTED` currently lives in `adapters/pubsub.py`, and
`registry.py` must not import from an adapter — hard rule #3 puts Google-facing
code in `adapters/`, and core reaching into it inverts the dependency. The
constant moves to `registry.py` (it is a routing concept, not a Google one) and
`adapters/pubsub.py` imports it, which is the direction that already exists for
`Registry`. Existing `from …adapters.pubsub import UNROUTED` call sites keep
working, since the import rebinds the name on the module.

---

### CG-9 — `ADDED_TO_SPACE` regression fixture (blocked: needs a human)

During today's session the normalizer was run against a live
`addedToSpacePayload` and handled it correctly — `ADDED_TO_SPACE` derived, space
and sender extracted — for an event type it had never seen and for which no
fixture exists. That exercised three doc-derived paths at once: the
`ADDON_PAYLOAD_TYPES` entry, the `chat.space` non-payload sibling fallback in
`_normalize_addon`'s three-source space resolution, and `_shape` with an empty
`message`.

**The bytes were not kept.** Unlike the MESSAGE and buttonClicked captures, this
one exists only as an observation, so there is nothing to scrub and commit. The
item is blocked on a human re-capture: remove the app from a test space, re-add
it, pull the subscription. That is a 60-second action and Builder cannot do it.

Filing it rather than dropping it is the point — an unrecorded observation is
indistinguishable from a guess three weeks from now, which is the whole reason
the fixture README tracks provenance.

---

### CG-10 — The empty `action.id` (blocked: ADR)

The real capture normalizes to `action: {"id": "", "params": {…}}`. The mechanism
is now fully understood: the card's button routed via
`action.function = "projects/chat-gateway-prod/topics/chat-gateway-events"`, so
the add-ons runtime sent no `__action_method_name__` parameter, no
`invokedFunction`, and no `payload.action`. `_normalize_addon` consults exactly
those three sources, finds none, and falls through its `or ""` to an empty
string — silently, into an `InboundReply` that looks structurally valid and is
forwarded to a tenant callback as though it carried an action identity.

That is the same silent-failure class CG-1 existed to eliminate. CG-1 made the
*parser* fail loudly on an unrecognized envelope; this is one layer in, where the
envelope parses fine and a field inside it is empty rather than absent.

**Planner's scope is the mechanism, not the policy.** *Where action identity
should live* — whether we depend on topic-as-function routing at all, whether
identity rides in `parameters`, whether slash commands displace buttons — is the
ADR's decision and appears in this spec's non-goals. What is Planner's:

- **Detect.** An interaction event where no known action-id source yields a value
  must be recognized as such, not silently emptied.
- **Surface.** It must be visible without reading the JSONL by hand — a
  `/healthz` counter at minimum, and an unambiguous signal in the forwarded
  `InboundReply` so a tenant can reject rather than guess. `CallbackForwarder._title`
  already renders `interaction:?` for this case, which is the only place it
  currently shows at all, and only in the delivery log.
- **Test.** CG-3's pinning test is rewritten against whatever the ADR chooses.

Three shapes are available and the choice is genuinely ADR-dependent: raise and
route to `UNPARSEABLE` (wrong — the event parses and its params are usable);
`id: None` plus an explicit missing-marker and a counter; or keep `""` and count
plus log. **No plan is written for this item, deliberately.** A plan must contain
literal code for every step, and writing one now would mean either inventing the
policy or filling it with placeholders. Planner writes it when the ADR lands.

---

### CG-11 — Correct the selection-widget claim (blocked: ADR wording)

`CLAUDE.md` says, of jobhunt: *"modal dialogs are impossible over Pub/Sub
transport — selection widgets are the supported path."* `docs/consumers/jobhunt.md`
R6 says the same. As written it is wrong, and it is wrong in a way that would
have sent an implementer down a dead end.

**What was proven false.** A selection widget's `onChangeAction` fails *exactly
like a button's* — `gsuiteaddons.googleapis.com/errors` code 13,
`deploymentFunction: cgSelectProbe`. Widgets are not an interaction path.

**What is actually true, and better than the claim it replaces.** A selection
widget's **value** arrives in `commonEventObject.formInputs`, harvested at
button-submit time. On real captured data the normalizer merged
`"decision": "approve"` into `action.params` alongside the button's own
parameters. So the supported pattern is *widgets for input, one button to
submit* — which is what jobhunt's structured-reason requirement (R6) actually
needs, and it is now capture-verified rather than doc-derived.

**What was never tested, and must not be restated as fact.** The modal-dialog
half. Dialogs are believed impossible over Pub/Sub because they require a
synchronous HTTP interaction endpoint that this transport does not provide —
which is a documentation-derived inference, not an observation. The old sentence's
real sin was conflating a doc-derived claim with a false one under a single
confident dash. The replacement keeps them apart and labels each.

**Why it is blocked.** The ADR owns jobhunt's interaction model. The *facts* here
are settled and independent of it, but two documents asserting the same fact in
different words is how drift starts, and `CLAUDE.md` is this project's
constitution. The plan's first task is therefore to read the ADR and adopt its
wording — or stop and return to Planner if it contradicts this finding.

---

### CG-12 — Forensic trace for opted-out-only spaces (blocked: user decision)

The second finding CG-1's review deferred. In `dispatch`, `candidates =
registry.apps_for_space(space) or [UNROUTED]`. When a space *has* registered
owners but every one of them is `allow_inbound: false`, `candidates` is non-empty
— so the `_unrouted` fallback never fires — and each candidate hits the `continue`
in the authorization block. `delivered` comes back empty and **nothing is written
anywhere**: no inbox entry, no `_unrouted` record, no counter, nothing at
`/healthz`. `aitrader`'s registry shape is exactly this.

Hard rule #6 is satisfied — nothing crossed to a consumer, which is the guarantee
aitrader's contract buys. Hard rule #5's spirit is not: events are being
discarded and the system cannot tell you it is happening.

**This is a rule-6 semantics question, so Planner recommends and does not
decide.** Three options:

| | What it stores | Rule-6 exposure |
|---|---|---|
| **A. Counter only** | one integer at `/healthz`; no space, no app id, no content | none — nothing about the event is retained |
| **B. Counter + full `_unrouted` audit record** | the whole redacted event on disk under `_unrouted` | **material.** `aitrader`'s traffic starts being persisted, and before CG-8 lands an app registered as `_unrouted` could poll it |
| **C. Counter + metadata-only record** | space, event type, timestamp, dedupe key — no text, no sender, no raw | small but real: an opted-out tenant's space-level activity becomes retained data |

**Recommendation: A, with C available if the user wants space-level
attribution.** A is a pure rule-5 fix with no rule-6 surface change and is a
handful of lines. C answers "which space is dropping events, and how many," which
is the question an operator would actually ask, at the cost of retaining metadata
about a tenant that opted out of everything. B is not recommended: persisting an
opted-out tenant's event content is against the spirit of a contract that treats
any two-way path as a security hole in a real-money system.

**One caveat that applies to all three:** `/healthz` has no `Depends(current_app_id)`
— it is unauthenticated. The deployment is appserver-local, but "it is only a
counter" is a weaker argument than it looks if that port is ever exposed.

**Mechanism, whichever option is chosen.** `dispatch` gains an optional
`on_suppressed(app_id, reason)` callback mirroring the existing `on_unparseable`,
with two reasons: `"opt_out"` and `"not_authorized"`. Counting authorization
refusals separately is additive and rule-5-aligned — a refusal firing five
hundred times is operationally interesting and today invisible.

---

## 4. Decisions

| # | Decision | Alternative rejected | Why |
|---|---|---|---|
| DEC-1 | Keep body `thread.threadKey`, drop the query param | Keep the query param, drop the body | Cross-adapter uniformity with `chat_api.py`; body is the `spaces.messages.create` form; marginally less splicing into a credential-bearing URL |
| DEC-2 | State the `messageReplyOption` non-isolation in the docstring, verbatim | Note it in the spec only | The failure mode is a future reader over-generalizing at the code; the caveat has to be where they are reading |
| DEC-3 | Per-method flags in `chat_api.py` | Keep one module flag, clear or don't | A module flag forces a binary choice on a module whose halves have different evidence |
| DEC-4 | Add the real capture as a **new** fixture; keep the constructed one, relabelled | Overwrite the constructed fixture | Overwriting destroys parity coverage and silently rewrites a broken value into an assertion of correctness |
| DEC-5 | Pin `action.id == ""` as an explicitly-named defect test | Leave it untested until CG-10 | Today's ground truth would otherwise sit in the repo with nothing asserting on it |
| DEC-6 | `example`-marker guard for `domainId` / `customer` | Path allowlist for those two fields | Path guessing is the failure mode CG-1 named; RFC 2606 marker keeps it structural |
| DEC-7 | No guard rule for space / message / thread ids | Guard them like user ids | `google-cloud-setup.md` step 8 classifies space IDs non-secret; a guard contradicting our own doc is worse than convention |
| DEC-8 | `/healthz` `status` computed from a `reasons` list | Keep the boolean `degraded` expression | An operator needs *why*, not just *that*; and the list is what makes subscriber death expressible |
| DEC-9 | Billing **declared** via env, not detected via API | Call Cloud Billing / Service Usage | More scopes and calls, against a fewer-calls project — and today proved Google's own publish metric can read zero while publishing |
| DEC-10 | Reserve the whole `_` prefix | Reserve the literal `_unrouted` | The next internal bucket is then safe without anyone remembering |
| DEC-11 | `UNROUTED` moves to `registry.py` | Import it from the adapter into core | Core importing an adapter inverts hard rule #3's layering |
| DEC-12 | CG-10 gets a spec and **no plan** | Write a plan with the policy as TBD | A plan with placeholders is what wastes Builder's cycle; the ADR is days away, not weeks |

---

## 5. Blast radius

| Item | Touches | Does not touch |
|---|---|---|
| CG-3 | `tests/fixtures/*`, `tests/test_fixtures_scrubbed.py`, `tests/test_adapters.py`, docstrings in `adapters/pubsub.py`, `docs/consumers/jobhunt.md` R3 note, `CLAUDE.md` status bullet | any normalizer **behaviour** |
| CG-4 | `adapters/webhook.py`, its two tests | `chat_api.py`, routing, the registry |
| CG-5 | `adapters/chat_api.py` docstrings only | any code path |
| CG-6 | `docs/google-cloud-setup.md`, `docs/integration-guide.md`, `.env.example` | source |
| CG-7 | `adapters/pubsub.py` (`PubSubError`, loop counters), `service.py` healthz, `.env.example`, two tests | `dispatch`, routing, authorization |
| CG-8 | `registry.py`, `adapters/pubsub.py` import line | authorization logic, `dispatch` |
| CG-9 | fixtures + one test (when unblocked) | source |
| CG-10 | `adapters/pubsub.py` `_normalize_addon`, `service.py` healthz, CG-3's pinning test | **ADR-gated** |
| CG-11 | `CLAUDE.md`, `docs/consumers/jobhunt.md` R6 | source |
| CG-12 | `dispatch` signature (additive callback), `SubscriberLoop`, healthz | **user-gated**; rule-6 enforcement itself is unchanged in options A and C |

Nothing in CG-3 … CG-9 or CG-11 changes what crosses to a consumer. `aitrader`
stays `allow_inbound: false` and locked out of every inbound path throughout.

---

## 6. Test plan

Everything is offline and deterministic; `python -m pytest -q` from 70 passing.

- **CG-3** — real-capture normalization (event type, space, thread, message id,
  sender, dedupe key); formInputs+parameters merge on real data; the named
  defect test on `action.id == ""`; the extended scrub guard rejecting an
  unmarked `domainId` and an unmarked `customer`; the guard still passing on all
  four fixtures.
- **CG-4** — `build_params` returns `messageReplyOption` only; `build_payload`
  still carries `thread.threadKey`; the send test asserts `threadKey=` is
  **absent** from the URL and `messageReplyOption=` present; the existing
  never-leak-the-URL assertion unchanged.
- **CG-5** — none. Docstrings only; the suite must stay at its current count.
- **CG-6** — none. Docs only.
- **CG-7** — enabled subscriber with `last_poll_at is None` → `degraded` with the
  never-polled reason; consecutive failures at threshold → `degraded`, reason
  names the last error; one success resets both counter and error → `ok`;
  `PubSubError`'s message carries no response body; the existing exact-dict
  subscriber assertion updated deliberately, not loosened to a subset.
- **CG-8** — `_unrouted` as an app id raises; `_anything` raises; the error text
  names the consequence; ordinary ids unaffected; `UNROUTED` still importable
  from `adapters.pubsub`.

---

## 7. ⚠ Flag accounting — what may and may not be cleared

**Cleared by this work, with evidence:**

| Flag | Cleared by | Evidence |
|---|---|---|
| `webhook.py` send | CG-4 | Real `WebhookAdapter`, real webhook: text → `delivered`; Cards v2 → `delivered` + user-confirmed rendering; threading confirmed via `thread.name`, three variants |
| `chat_api.py` `send()` | CG-5 | Real `ChatApiAdapter` + real `GoogleServiceAccountTokens`: text and Cards v2 posted as the app; response carried `sender: {displayName: "Agent Comms", type: BOT}` |
| `GoogleServiceAccountTokens` | CG-5 | It minted the token those calls used |

**Downgraded to ⚠ SHAPE-VERIFIED 2026-07-29, not cleared:**

| Path | Why not cleared |
|---|---|
| add-on `buttonClickedPayload` normalization (CG-3) | Real bytes, replayed offline. Our normalizer has still never processed an interaction *live* — the capture was pulled with an ad-hoc client |

**Explicitly NOT cleared, and why:**

| Path | Why |
|---|---|
| `PubSubPuller.pull()` / `.acknowledge()` | Every live pull today used an ad-hoc client. Our class remains unexercised |
| `chat-api-push@system.gserviceaccount.com` publisher grant | Both principals bound; which delivered is unknowable. Unchanged from CG-2 |
| `ChatApiAdapter.send_text()` | Never driven. Different request shape (`thread.name`) |
| `send()`'s threading branch | The live posts were unthreaded |
| Both adapters' error branches | Only success paths were exercised |
| jobhunt R3 / R4 | **A capture is not a verification, and this one found a defect.** The interaction round-trip reached us, but `action.id` arrives empty — R3 says interactions forward *whole with an idempotency key*, and the action identity is missing. R3/R4 must not be described as verified until CG-10 lands |
| add-on interaction **parameter list-form tolerance** | The real capture sent a map. The list branch stays untested against reality |

---

## 8. Open questions for the reviewer

1. **DEC-1** — the threadKey recommendation is a judgment call with a real
   counter-argument (§3, CG-4). Confirm before Builder ships it.
2. **CG-12** — options A / C / B. Planner recommends A and will not implement
   anything here without a decision that names hard rule #6.
3. **Item ordering.** The queue below is Planner's suggested order, not a
   priority ruling. CG-6 is placed first because it is the credential-exposure
   fix, ahead of items that are technically larger.
4. **CG-9** — worth the 60-second re-capture, or drop the item and accept that
   `ADDED_TO_SPACE` stays covered only by an unrecorded observation?
</content>
</invoke>
