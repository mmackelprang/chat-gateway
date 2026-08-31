# ADR-0001 — Tier-2 interaction model: topic-as-function, action identity, and the undocumented dependency

| | |
|---|---|
| **Date** | 2026-07-29 |
| **Status** | **Superseded by its own outcome** — see the banner below. All five §12 questions are answered (recorded 2026-07-30); none is open. |
| **Decides** | N1 … N4 from [the live-verification spec](../../superpowers/specs/2026-07-29-live-verification-followups-design.md) §2 |
| **Unblocks** | `CG-10` (empty `action.id`) — **shipped 2026-07-29**; `CG-11` (selection-widget wording) — **shipped 2026-07-30**, and it corrected §7 rather than adopting it |
| **Hard rules engaged** | #1 (transport, never schemas), #2 (secrets), #3 (adapters + flag discipline), #5 (honest `/healthz`), #6 (inbound opt-in) |

> ## ⚠ Status: SUPERSEDED BY ITS OWN OUTCOME — 2026-07-29, later the same day
>
> **This ADR's recommendation was "adopt the bridge now, treat classic as the
> destination, settle it with E1." E1 ran, passed decisively, and the migration
> to classic is COMPLETE and live-verified. Production no longer depends on
> undocumented behaviour at all.**
>
> Read the body below as the *record of how that was decided*, not as an open
> recommendation. In particular §3 (the "is the undocumented bet worth it"
> analysis) and §5's option comparison are settled history; §8's detector was
> superseded before it was built; §10's experiments have run; §12's questions are
> all answered.
>
> | Item | Outcome |
> |---|---|
> | **D2** `__cg_action__` | **APPROVED** and shipped (CG-10) — then **reframed to an add-ons compatibility fallback.** On classic it is *inert*; kept because it is load-bearing on add-ons and still wins when present, so one card works on either runtime. |
> | **D6** third flag word | **NO.** `⚠ SHAPE-VERIFIED` stays the only addition. |
> | **D3** portable card convention | Shipped (CG-13), and it **paid for itself immediately**: the migration below cost **zero producer card changes**. The card `parameters` example in D2 was **wrong** and is corrected in place — see the callout there. |
> | **§8** interaction dead-man | Approved, then **superseded before being built.** E1 removed its rationale; **nothing was implemented.** Now `⏸ blocked` pending a user decision on whether a general inbound-quietness detector is wanted instead. |
> | **E1** classic + Pub/Sub `CARD_CLICKED` | **PASSED.** Native delivery, `action.id` populated (`'approve'`), and `onChangeAction` **fires**. §11 trigger 1 fired. |
> | **E2** add-on toggle reversibility | **Answered: NO.** The toggle is **create-time only** — §5 option D's "contradictory" note is settled, and D7's parallel-project path was the *only* available one, not merely the prudent one. |
> | **D7 / migration to option D** | **DONE and live-verified 2026-07-29.** `chat-gateway-gw` (`#860649224827`), classic Chat app, real card through our real `ChatApiAdapter`: `action.id: 'approve'`, `envelope_format: 'classic'`, params `{"jobId": "mig-001", "reason": "good_fit"}`. Tracked as CG-21. |
>
> **The load-bearing consequence: §3's risk analysis no longer applies to
> production.** The undocumented topic-as-function dependency is gone from the
> live path — not mitigated, *removed*. What remains of the bridge is
> compatibility code for a runtime we no longer deploy on.
>
> One thing the migration taught that no experiment predicted: a dropdown's value
> arrived on the **button click's** form inputs with **no `onChangeAction` at
> all**, so the recommended pattern yields **one event per user decision instead
> of two**. §7 framed *widgets for input, one button to submit* as an add-ons
> limitation; it is actually the better design on classic too.
>
> **Every project that produced the add-ons-runtime evidence is now gone.**
> `chat-gateway-prod` and E1's own project (`chat-gw-e1-20260729`) were both
> **deleted** on 2026-07-30, leaving exactly one live project
> (`chat-gateway-gw`). So none of the add-ons behaviour recorded below can be
> re-observed by anybody, ever — §2's captures, the code-13 failures, and E1's
> capability table survive **only** in this ADR and in the committed fixtures.
> That makes CG-20 and CG-22 load-bearing rather than tidy, and it is why a
> reader must not be told to go reproduce any of it.
>
> One consequence is worth stating as a closed question rather than an open one:
> the `chat-api-push@system.gserviceaccount.com` publisher-grant question is
> **permanently unresolvable.** Both candidate principals were bound in
> `chat-gateway-prod`; that project no longer exists, so which one actually
> delivered the first event can never be determined. Closed by circumstance, not
> answered — do not carry it as outstanding work.

---

## 1. Context

jobhunt is the gateway's first two-way tenant. Its R3/R4 contract
(`docs/consumers/jobhunt.md`) assumes a human taps **Approve** or **Reject** on a
card and the interaction arrives at the gateway over Cloud Pub/Sub, is
authorized, and is forwarded whole to the tenant's callback. Every piece of that
path is built and unit-tested. Until 2026-07-29 none of it had ever been fed a
real card tap.

The Chat app is deployed under the **Google Workspace Add-ons runtime**
(`gsuiteaddons.googleapis.com`) with Cloud Pub/Sub as its connection setting.
Pub/Sub was chosen deliberately and the reason is recorded in
`adapters/pubsub.py`: *"no public endpoint, no reverse proxy, ever (the whole
point of choosing Pub/Sub for a homelab appserver)."* The gateway runs on
`/srv/chat-gateway/` on an appserver with no public ingress.

On 2026-07-29 the user probed that deployment live. The results invalidate part
of the design, validate another part more strongly than before, and surface an
**undocumented Google behaviour** that the entire interaction contract now rests
on. This ADR decides whether to build on it.

---

## 2. Evidence — all first-hand, 2026-07-29

§2.1–2.3 and §2.5–2.6 were observed against the real deployment; none of it is
doc-derived. §2.4 (why it fails) and §2.7 (community reports) are explicitly
labelled as documentation and third-party evidence, kept in this section because
they explain the observations rather than replace them.

### 2.1 What reaches the Pub/Sub topic

| Event | Evidence |
|---|---|
| `messagePayload` — a user typing a message | confirmed 12:55:58Z; landed as a fixture (`tests/fixtures/addon-message-event.json`) |
| `addedToSpacePayload` — app added to a space | confirmed twice, 17:30 and 17:31 |

### 2.2 What does NOT reach it

| Attempt | Failure |
|---|---|
| Card action button, ordinary function name | `gsuiteaddons` **code 13**, "Unspecified error invoking the add-on", `deploymentFunction: approve` / `reject` |
| Selection widget `onChangeAction` | identical: code 13, `deploymentFunction: cgSelectProbe` |

In both cases the runtime tried to resolve a **destination** from that literal
name and found nothing — there is no function or endpoint to find, because the
connection setting is a Pub/Sub topic. So under this deployment, **a card's
interactive elements cannot trigger the app by the documented mechanism at
all.** §2.4 explains why, and it is not an accident.

### 2.3 The discovery — topic-as-function

Setting `onClick.action.function` to the **Pub/Sub topic path itself** —
`projects/chat-gateway-prod/topics/chat-gateway-events` — causes the runtime to
route the interaction to that topic instead of failing the lookup. A real
`buttonClickedPayload` landed in the subscription at **17:55:44Z** with no error.

This was found by guessing. **Google does not document it.** A two-pass research
sweep (Google Chat + Workspace Add-ons docs, both changelogs back to 2023,
`googleworkspace/google-chat-samples`, `googleworkspace/add-ons-samples`,
StackOverflow, discuss.google.dev) found **zero** sources describing, mentioning
or hinting at a topic path in `action.function`. Stated precisely, because the
distinction matters: **no source affirms it and no source denies it — it is
simply undocumented.**

### 2.4 Why it fails, and why the workaround is less arbitrary than it looks

The research resolved the root cause, and it changes how fragile this should be
considered. Two documented facts:

> "You can optionally configure per-event endpoints in the Google Cloud console,
> but this **doesn't include card click events**."
> "add-ons use a **full HTTP URL** for a card's `action.function`, while Chat apps
> built with Google Chat API interaction events use a **function name**."
> — <https://developers.google.com/workspace/add-ons/chat/convert>

And the add-ons runtime exposes exactly **four** configurable triggers — Added to
space, Message, Removed from space, App command
(<https://developers.google.com/workspace/add-ons/chat/configure>). **A card click
is not among them.**

So under the add-ons runtime, `action.function` is not a callback name at all —
it is the interaction's **destination**, and a click's destination comes from
nowhere else. Our `approve` / `cgSelectProbe` failures were the runtime being
handed something that is neither a URL nor resolvable, exactly as designed.

That reframes the discovery: we did not bypass a function lookup, we **supplied a
destination in an undocumented form** — a Pub/Sub topic resource path where a
URL is documented. It is an undocumented *extension of a documented mechanism*
rather than an accidental hole, which is a meaningfully better fragility profile
than "a guess that happened to work". It is still undocumented, and still carries
no stability guarantee.

### 2.5 What `normalize_event()` produced from the real tap

```json
{"event_type":"CARD_CLICKED","space":"spaces/AAQAmzgydeI",
 "thread_name":"spaces/AAQAmzgydeI/threads/UJ9ssq1vGbY",
 "message_id":"spaces/AAQAmzgydeI/messages/UJ9ssq1vGbY.UJ9ssq1vGbY",
 "sender_email":"mark@mackelprang.com",
 "action":{"id":"","params":{"probe":"topic-as-fn","decision":"approve"}},
 "dedupe_key":"20751388131856523","envelope_format":"addon"}
```

Space, thread, message id, sender and dedupe key are all correct. The routing and
authorization path therefore works end to end on real data. **`action.id` is
empty.**

### 2.6 Three consequences

**C1 — the action-identity slot is gone.** The function slot was consumed as a
routing target, so no action name arrives. There is no `__action_method_name__`
parameter either — the spec predicted it as the add-ons location and it is
**absent** under this pattern (Google injects it when it invokes a *function*;
here it never invokes one). `commonEventObject.invokedFunction` was removed from
the add-ons runtime in the 2025-05-12 release notes, and `payload.action` is
absent. `_normalize_addon` consults exactly those three sources and falls through
its `or ""`. Action identity must therefore be carried in `parameters`.

**C2 — under *this* runtime selection widgets work as form inputs, not as
triggers.** The dropdown value arrived as `"decision":"approve"`, harvested from
`commonEventObject.formInputs` at button-submit time and merged into
`action.params` by the existing `_merge_form_inputs`. So `CLAUDE.md`'s
*"selection widgets are the supported path"* is **wrong as written** — under
add-ons a widget is not an interaction trigger — but right in spirit: widgets are
the supported way to collect *structured input*, which is what jobhunt R6
actually needs. **Scope this to add-ons and nothing further:** on classic a widget
*is* a trigger, which §7's correction banner covers. Restated precisely in §7.

**C3 — a fallback exists but is unproven.** Slash commands (`/approve 123`) are
message-class, and message-class events demonstrably reach the topic (§2.1). The
normalizer already maps `appCommandPayload` → `APP_COMMAND`. **No
`appCommandPayload` has ever been observed here.** It is promising, not proven —
see E3 (§10).

### 2.7 One community corroboration, unverified by us

A third party hit this exact wall and was told their project *"got configured as
a Workspace Add-on instead of a Chat App"*
(<https://stackoverflow.com/questions/79843986>); a second report shows
CARD_CLICKED silently absent while messages work
(<https://stackoverflow.com/questions/79812648>, score 4, **no accepted
answer**). ⚠ Neither was read directly — StackOverflow blocked the research
fetch, so these are search-result leads, not verified citations. They are
recorded because they point at option D (§5) and because a third party reaching
the same diagnosis independently is worth more than our single data point.

Note also: Google's troubleshooting pages contain **no error-code table and no
entry for code 13**, and code 13 is a generic bucket (a third report shows a
different code-13 string entirely). Following the docs' own troubleshooting path
would never have found this.

---

## 3. The tension

Buttons and selection widgets are materially better UX than typed commands —
especially on a phone, which is the entire premise of jobhunt's
tap-to-verdict-in-seconds flow. They work today. They work only because of
undocumented behaviour that Google can change without notice and without a
changelog entry.

The question is not "is undocumented bad" — obviously — but **what is the blast
radius when it breaks, how fast would we find out, and what does the alternative
cost.**

### 3.1 Blast radius, honestly bounded

| | |
|---|---|
| **Breaks** | jobhunt's tap-to-verdict path (R3/R4). Nothing else. |
| **Unaffected** | `aitrader` (`allow_inbound: false`, no interaction path by contract), `aiteam-harness` (outbound only), every tier-1 webhook identity, `/v1/notify`, `/v1/heartbeat`, the message-class inbound path |
| **Not a single point of failure** | jobhunt keeps its own review UI (R9) — verdicts are still possible without the gateway. What is lost is convenience, not capability. |
| **Gateway code affected** | **none.** See §3.2 |
| **Volume** | homelab scale, a handful of taps/day — which is what makes the detection design in §8 proportionate |

### 3.2 The dependency is producer-side, not gateway-side

This is the observation that most changes the risk calculus, and it is easy to
miss.

The gateway does not depend on topic-as-function **in code**. It parses whatever
arrives. The undocumented behaviour is invoked by the *card*, and cards are
rendered by the producing application — hard rule #1's "rendering stays with the
producer". So the dependency lives in a **card-rendering convention documented in
the integration guide**, not in `adapters/pubsub.py`.

Migrating away from it means changing a convention and re-rendering cards. It
does not mean rewriting the inbound path. A bet whose exit cost is "change one
documented convention" is a much cheaper bet than one whose exit cost is a
parser rewrite — and §6's D3 makes that exit cost approximately zero.

---

## 4. Prior decisions this must not relitigate

- **Pub/Sub over HTTP ingress** — chosen because the gateway runs on a homelab
  appserver with no public endpoint (`adapters/pubsub.py` module docstring).
  Option C reopens it; this ADR does not overturn it.
- **`allow_inbound: false` is absolute** (hard rule #6). `aitrader` stays locked
  out under every option below. No option here widens any tenant's inbound
  surface; §9 audits this.
- **Events forward whole** (jobhunt R3), with exactly one documented redaction
  (`configCompleteRedirect*`). Nothing here adds a second.
- **Flag vocabulary is capped** at `⚠ LIVE-UNVERIFIED` plus `⚠ SHAPE-VERIFIED`
  (hard rule #3, amended 2026-07-29). D6 respects the cap rather than quietly
  adding a third word.

---

## 5. Options considered

### Option A — slash commands only

Drop card interactions; jobhunt users type `/approve job-123`.

| | |
|---|---|
| ✅ | Message-class, so it rides the path proven to work (§2.1). No undocumented dependency. |
| ✅ | Action identity is native: the command id is structural, not a convention we invent. |
| ❌ | **UX regression that guts the feature.** Tap-to-verdict on a phone becomes type-an-opaque-id on a phone. Job ids must be read off a card and retyped or copy-pasted. |
| ❌ | **Kills R6.** Structured reject reasons become free text. The selection-widget mechanism that *is* capture-verified (C2) has no home — a slash command carries no form inputs. |
| ❌ | **Unproven here, and the docs disagree with themselves.** No `appCommandPayload` has ever been observed (C3). Google's add-ons Pub/Sub quickstart says *"A user interacts with the Chat app by, for example, sending it a message, **issuing a command**… Chat sends the message to a Pub/Sub topic"* — but the commands page says *"The event object is sent to the HTTP endpoint or Apps Script function that you specified when you configured the App command trigger"*, naming neither Pub/Sub nor a default. **No document reconciles the two.** App command *is* one of the four configurable triggers, and triggers are framed as optional fan-out (*"To receive event objects to more than one endpoint or function…"*), which favours the topic being the default destination — but that is a reading, not a citation. Slash commands may hit the same code-13 wall buttons did. |
| ❌ | Choosing A on the strength of an untested assumption would repeat the mistake this ADR exists to avoid. |

### Option B — topic-as-function, with slash commands as a fallback

Keep buttons + widgets via the discovered pattern; keep a proven typed-command
path as the escape hatch.

| | |
|---|---|
| ✅ | Best available UX, working today, on real captured evidence. |
| ✅ | Preserves R6's structured-reason mechanism exactly as capture-verified. |
| ✅ | Gateway-side cost is zero code; exit cost is one convention (§3.2). |
| ❌ | Depends on undocumented behaviour with no stability guarantee. |
| ❌ | **The fallback is only worth something if it is proven**, and today it is an assumption — with doc counter-evidence (option A). D5 therefore requires E3 to be run immediately rather than treating the escape hatch as given; until it returns, B is really "topic-as-function with no floor". |
| ⚠ | Requires the gateway to define where action identity lives (§6 D2) — the subtlest call in this ADR. |

### Option C — HTTP endpoint deployment

Reconfigure the app to POST interactions to a public HTTPS endpoint.

| | |
|---|---|
| ✅ | Fully documented and supported. Interactions, `onChangeAction`, **and true modal dialogs** all work — the only option that unlocks dialogs. |
| ✅ | Action identity is native (`action.function` carries it, unconsumed). |
| ❌ | **Requires public ingress to a homelab appserver.** New TLS, DNS, reverse proxy, and request-authentication surface (Google's bearer tokens must be verified) — the exact thing Pub/Sub was chosen to avoid. |
| ❌ | Contradicts a recorded design rationale without new information justifying it. A gateway with a public endpoint is also the shape `aitrader`'s contract treats as a security hole, and while it would not *widen* any tenant's authorization surface, it changes the system's own exposure. |
| ⏸ | **Not rejected forever.** If the homelab ever gains a hardened ingress (e.g. an authenticated tunnel), C becomes the strongest option on capability grounds. It is rejected *now*, on cost. |

### Option D — classic (non-add-on) Chat app deployment

Configure the app directly under the Chat API, with Cloud Pub/Sub as its
connection setting and the *"Build this Chat app as a Google Workspace add-on"*
box **cleared**.

This option changed shape during research. It was on the list as a long shot;
it came back as the likely destination.

**The premise that put us on the add-ons runtime is wrong.**
`docs/google-cloud-setup.md` records: *"The app will not appear under ⚙ → Apps &
integrations → Add apps until the Google Workspace Marketplace SDK … is enabled
and the app is published."* Google's own documentation contradicts this —
installability comes from the **Chat API Visibility setting**, and on an
*add-ons* page Google states the Marketplace SDK is ignored for Chat entirely:

> "To deploy and test an add-on in Chat, you must use the Chat API's Visibility
> setting. Any visibility or testing settings that you've configured in the
> Google Workspace Marketplace SDK **are ignored**."
> — <https://developers.google.com/workspace/add-ons/chat>

> "the Chat API lets you share your Chat app with specific people in your Google
> Workspace organization. The people that you specify **can add the Chat app to a
> space** and test its features before you publish it to the Marketplace."
> — <https://developers.google.com/workspace/chat/test-interactive-features>

| | |
|---|---|
| ✅ | **The installability objection is removed — VERIFIED.** Marketplace publishing is required only to reach people beyond the Visibility list. |
| ✅ | **Google's own current Pub/Sub quickstart makes clearing the add-on box step one** (*"Clear Build this Chat app as a Google Workspace add-on… click Disable"*, <https://developers.google.com/workspace/chat/quickstart/pub-sub>, updated 2026-05-06). The officially documented way to build exactly what we are building is classic, not add-ons. |
| ✅ | **Classic is not deprecated.** A full grep of the Chat release notes for `deprecat\|sunset\|turndown\|no longer` finds exactly one deprecation in the product's history — Cards v1, 2022. Two independent passes, same result. Google still presents both frameworks as a live choice. |
| ✅ | Pub/Sub remains a documented classic connection setting (<https://developers.google.com/workspace/chat/receive-respond-interactions>, 2026-04-20). |
| ✅ | Action identity becomes native — `action.function` is a function *name* again, unconsumed — and `onChangeAction` **does return**: first-hand on classic (E1, 2026-07-29, and again in a live capture 2026-07-30 — §10.0), including on a card carrying **no button at all**. §7's two-tap UX cost is removed, not merely likely to be. This row read *"plausibly returns"* until the experiments ran. |
| ✅ | **Q2 is SETTLED — experiment E1, 2026-07-29.** Classic Pub/Sub apps **do** receive `CARD_CLICKED`: it arrived natively in a throwaway project, with `action.id` populated (`'approve'`) and `onChangeAction` firing. This row previously read *"Q2 is still unverified… the load-bearing assumption of the whole option"*, and it was — that classic Pub/Sub apps receive card clicks was an inference both research passes reached and neither could cite. The indirect evidence read correctly: the classic quickstart's own limitations (*"Can't use dialogs"*, *"Can't update individual cards with a synchronous response. Instead, update the entire message by calling the `patch` method"*) only make sense if clicks arrive. |
| ❌ | **Reversibility is SETTLED — experiment E2, 2026-07-29 — and the answer is NO.** The *"Build this Chat app as a Google Workspace add-on"* toggle is **create-time only**: it cannot be cleared on an existing app. This row previously called reversibility *"contradictory"* — Google's explicit clear-and-confirm flow in two live quickstarts versus a third-party vendor doc warning *"This setting cannot be disabled once saved… you must create a new Google Cloud Project"* (CloudM, 2026-03-16). The quickstarts describe a **never-saved** state on a fresh app; CloudM described ours, and CloudM was right. Consequence: escaping add-ons needs a **new Chat app**, and Chat app config is per-project, so it needs a **new GCP project**. D7's parallel-project path was the **only** available one, not merely the prudent one. |
| ⚠ | **Visibility scale limit:** *"Up to five individuals, or one or more Google Groups"*, and dynamic groups are unsupported. Ample for a single-operator homelab; a constraint to remember if the gateway ever fronts a wider audience. |
| ⚠ | Slash commands land differently: classic delivers them as a **MESSAGE** event carrying `message.slashCommand`, whereas add-ons uses `appCommandPayload` (a breaking change, add-ons release notes 2024-12-18). A migration would need the normalizer to handle both — additive, but real. |
| ✅ | **Both unknowns were settled by the scratch-project experiments (E1, E2 in §10), which ran 2026-07-29.** D7 removed the reversibility risk from the critical path *before* the answer was known; E2 then showed the risk was real. |

### Option E — do nothing (leave `action.id` empty)

Rejected. The real capture normalizes to `action: {"id": "", …}` and is forwarded
to a tenant callback **as though it carried an action identity**. A tenant
receiving `id: ""` cannot distinguish "no action" from "an action named empty
string". That is the silent-failure class CG-1 existed to eliminate, one layer
further in — and hard rule #5's founding incident was exactly this: a system
reporting fine while capturing nothing.

---

## 6. Decision

**Summary: adopt option B now as an explicit bridge; treat option D as the
destination and settle it with two cheap experiments.** The decisions below are
ordered so that everything built for the bridge is also correct after the
migration.

### D1 — Adopt topic-as-function now, as an explicitly time-boxed bridge, not the terminal design

Ship jobhunt's interaction path on the discovered pattern. The justification is
narrow and should be read as such: the gateway-side cost is zero code (§3.2), we
have real captured evidence rather than a doc reading, and the option that now
looks likely to dominate it (D) still rests on one uncited assumption (Q2/E1)
that must be settled in a scratch project — **not** on the production deployment
that currently works.

This is a bridge with a stated exit (§11), not a preference for the hack. The
research strengthened the case for leaving it: the premise that put us on the
add-ons runtime — that the Marketplace SDK was needed for installability — is
contradicted by Google's documentation (§5, option D). We are on this runtime by
mistake, not by design.

### D2 — Action identity lives in a gateway-reserved parameter key, `__cg_action__`

Producers set, on every interactive card element:

> **⚠ CORRECTED 2026-07-29 (by CG-13, before the convention shipped).** This
> example originally rendered `parameters` as a JSON **object**. That is **not
> valid Cards v2**: in a card, `action.parameters` is an **array** of
> `{"key": …, "value": …}`. The map form is what the *inbound* add-ons event
> carries (`commonEventObject.parameters`) — two different shapes, and the
> sketch below conflated them. Both are settled by first-hand capture:
> `tests/fixtures/addon-buttonclicked-event.json` holds the card we really sent
> *and* the event we really received, side by side. Corrected in place because
> `docs/integration-guide.md`, `docs/consumers/jobhunt.md` and
> `src/chat_gateway/service.py` all cite this ADR as ground truth, so a reader
> who comes here first would have copied a broken card. Pinned by
> `test_card_parameters_are_an_array_in_the_real_captured_card`.

```jsonc
"onClick": {
  "action": {
    "function": "<the value the gateway publishes as interaction_routing_target>",
    // An ARRAY of {key, value} — this is the Cards v2 shape. See the note above.
    "parameters": [
      {"key": "__cg_action__", "value": "verdict"},  // the action identity —
                                                     // opaque to the gateway
      {"key": "job_id", "value": "job-123"},         // the app's own params,
      {"key": "nonce",  "value": "n-9"}              // untouched
    ]
  }
}
```

Resolution order in `_normalize_addon` / `_normalize_classic`, highest first:

1. `parameters["__cg_action__"]` — app-declared, authoritative when present.
2. Google-native sources, unchanged: `__action_method_name__`,
   `action.actionMethodName` / `action.function`, `commonEventObject.invokedFunction`.
3. Otherwise **`None`**, not `""` (see D4).

With one guard rail that is not optional: **a step-2 value matching
`^projects/[^/]+/topics/[^/]+$` is a routing artifact and must be discarded, never
promoted to `action.id`.** Under the classic runtime the same card would echo the
topic path back in `action.function`; without this rule a portable card yields
`action.id == "projects/…/topics/…"` — a plausible-looking wrong answer, which is
worse than an empty one.

Keys the gateway lifts are popped out of `params`, exactly as
`__action_method_name__` is today, so tenants never see transport plumbing mixed
with their own parameters. The `__cg_` prefix is **reserved** for gateway
transport metadata; apps must not use it. Unknown `__cg_*` keys are passed
through rather than eaten — the gateway must not silently discard what it does
not understand.

#### Why this does not violate hard rule #1

This is the subtlest question in this ADR and it deserves the full argument
rather than an assertion.

Rule #1 forbids the gateway **interpreting or owning an application's message
schema**. The test the envelope spec itself proposed is: *does any new branch key
off a consumer's vocabulary?*

- The gateway defines the **name**. It never reads the **value** — no branch, no
  enum of permitted ids, no validation that jobhunt sends `verdict`. The value is
  relocated from `params` to `action.id` and forwarded verbatim.
- It is structurally identical to `thread_key`: a gateway-defined field
  ~~an application must set~~ **an application sets on its own messages**, whose
  value is opaque to the gateway. ⚠ **Narrowed 2026-08-31 (CG-86)**: the
  gateway now composes a `thread_key` of its own on one path — the dead-man
  monitor threads every message about a check on `hb:<source>:<check_id>`
  (`heartbeat.py::thread_key_for`), which no application sets or sees. **The
  load-bearing half is untouched and is what this bullet is actually citing:
  the gateway never reads the value.** No branch keys off it anywhere; it is
  passed through to Chat's threading mechanics whoever wrote it. That the
  gateway may now also AUTHOR one, for its own subject, strengthens the
  transport argument rather than weakening it — authoring an opaque routing
  token is not interpreting a tenant's vocabulary. That precedent has
  existed on the outbound side since v0.1. The inbound side never needed one
  because *Google* supplied the slot. Topic-as-function consumed Google's slot;
  either the gateway supplies a replacement or `action.id` is permanently dead
  under the dominant runtime.
- It is structurally identical to Google's own `__action_method_name__` — a
  reserved parameter key carrying action identity out-of-band. We are
  re-implementing a mechanism Google itself uses for the same purpose. That is
  transport, by demonstration.
- Rule #1's own escape hatch is *"extend the envelope generically"*. This is
  generic: no tenant's vocabulary appears anywhere in the gateway.

The honest cost, stated rather than glossed: applications must now know a
gateway-defined key when rendering cards. That is a small widening of the
gateway's surface into producer-side rendering, and it is the **first
inbound-direction envelope field**. It is an envelope change, so it gets the same
explicit user yes that `envelope_format` (DEC-3) got. See §12.

**Rejected alternatives**

| Alternative | Why not |
|---|---|
| Let each tenant use its own key (`verdict`, `decision`, …) | Kills cross-runtime parity, leaves the advertised `action.id` permanently `""`, and pushes wire-format detection into every tenant — the exact thing DEC-3 rejected. |
| Reuse Google's `__action_method_name__` spelling | Collides with a Google-owned reserved name for a *different* mechanism. If Google ever starts populating it, "who wrote this" becomes unanswerable. |
| Derive the id from the echoed `message.cardsV2` | Requires interpreting the app's card content — a real rule #1 violation — and the echo does not identify *which* button was tapped. Dead end. |
| Encode the action in the topic path (one topic per action) | Multiplies cloud resources, couples IAM to app vocabulary, and puts app-domain knowledge in the IaC. |

### D3 — The card convention is deployment-portable, and the gateway publishes the routing target

Producers must not hardcode the topic path. The gateway publishes it per-app on
the existing authenticated `/v1/identities` response as
`interaction_routing_target`, alongside the reserved-key name.

This is what makes D1 a cheap bet rather than a trap. Because identity always
rides in `__cg_action__` and the function slot always holds a
gateway-published constant, **the same card works under every option in §5**:

| Deployment | `interaction_routing_target` | Where `action.id` comes from |
|---|---|---|
| Add-ons + Pub/Sub (production **until** 2026-07-29) | the topic path — an undocumented destination form | `__cg_action__` |
| Classic + Pub/Sub (option D — production **since** 2026-07-29) | any constant — classic echoes `action.function` and invokes nothing | `__cg_action__`; step 2 would also work, and the topic-path guard makes a stale card's echo harmless |
| HTTP endpoint (option C) | the endpoint URL (add-ons) or a function name (classic) | `__cg_action__` still wins; step 2 available as a native fallback |

A migration between deployment models therefore requires **zero producer card
changes** — one registry/config value moves. That is the payoff that justifies
defining a reserved key at all, and it is why D2 is worth doing even under
options that do not need it.

> **The two runtime rows carried the label `(today)` on add-ons until CG-21
> (2026-07-30); they are dated now.** This table is not settled history like the
> rest of §5 — it is cited as live producer guidance by
> `docs/integration-guide.md` and by step 8 of `docs/google-cloud-setup.md`,
> both of which CG-21 corrected. A row reading "(today)" would have contradicted
> them the day they shipped. **The prediction in the sentence above held:** the
> migration cost zero producer card changes, observed rather than argued.

The topic path is not a secret: `docs/google-cloud-setup.md` step 8 explicitly
classifies topic and subscription names as safe to paste. Rule #2 is unaffected.

### D4 — Missing action identity is `None` and counted, never `""`

An interaction event whose action identity cannot be resolved from any source
yields `action["id"] = None` — semantically *absent*, distinguishable from an
action legitimately named empty-string — plus:

- a `/healthz` counter (`subscriber.interactions_without_action_id`),
- the existing `interaction:?` rendering in `CallbackForwarder._title`,
- the event **still forwarded**. Rule #6 says forward whole and let the tenant
  enforce; a parse-quality problem must not become a silent drop. The tenant can
  now reject explicitly instead of guessing.

Planner offered three shapes for CG-10 (raise → `UNPARSEABLE`; `None` + marker +
counter; keep `""` + count). `UNPARSEABLE` is wrong — the event parses and its
params are usable. Keeping `""` preserves the ambiguity that is the defect.

**Optional, recommended:** carry `action["id_source"]` — `"cg_param"` |
`"google"` | `null` — as transport metadata in the same spirit as
`envelope_format`. Its real value is as a **detector**: if Google ever starts
populating `__action_method_name__` under this pattern, `id_source` flips from
`cg_param` to `google` and we learn the runtime changed under us *before* it
breaks something. Cheap, and it converts a silent behaviour change into an
observable.

### D5 — Slash commands are the fallback, and must be proven before they count as one

Do **not** build a slash-command path now. **Do** run E3 (§10) now, because an
unproven fallback is not a fallback — it is a hope, and B's entire risk argument
rests on having somewhere to land. E3 is one console change and one typed
message.

If E3 succeeds, file the implementation (surfacing `appCommandId` and the typed
argument text into `action`) as a queued item, unbuilt, with the design settled.
If E3 fails, B loses its escape hatch and option D's experiments (E1/E2) become
urgent rather than merely valuable.

### D6 — `⚠ SHAPE-VERIFIED` is the right flag; the fragility goes in prose, not a third flag word

`⚠ SHAPE-VERIFIED 2026-07-29` correctly describes the interaction *parse*: real
captured bytes replayed offline. That claim is genuinely earned for
`buttonClickedPayload`.

It is **not sufficient** on its own, because it says nothing about the
undocumented routing that caused those bytes to exist. Two different risks:
*"we parse these bytes correctly"* versus *"these bytes only arrive because of
unsupported behaviour"*. Letting a green shape flag imply stability is exactly
the kind of quiet overclaim rule #3 exists to prevent.

The tempting fix — a third flag word, e.g. `⚠ UNDOCUMENTED-ROUTING` — is
**rejected**, because hard rule #3 caps the vocabulary explicitly: *"One further
flag word, and only one."* Adding a third silently would undercut the discipline
the rule encodes. Instead the fragility is recorded as prose adjacent to the
flags in `adapters/pubsub.py`, pointing at this ADR, and made observable at
`/healthz` (§8). If the user wants a third word, that is an amendment to rule #3
and needs an explicit yes (§12).

### D7 — If we migrate to classic, build a parallel project and cut over; never toggle production

The reversibility question (§5 option D) is unresolved and probably
unresolvable in advance: Google's clear-and-disable flow is documented for
*fresh* projects where the box appears checked by default, which may only
describe clearing a never-saved state. It says nothing about un-toggling a
project that already has a live `gsuiteaddons` deployment — ours.

So do not answer it. **Sidestep it.** Stand up a second Cloud project configured
classic from the start, verify it end to end, then cut over — leaving
`chat-gateway-prod` untouched and working until the moment it is retired.

- The IaC is idempotent and parameterized by `PROJECT_ID`
  (`iac/gcloud-setup.sh` / `.ps1` / terraform), so a fresh project is close to
  free. This is the payoff for having written it.
- Rollback is switching two env values back
  (`CHAT_GATEWAY_PUBSUB_SUBSCRIPTION`, `GOOGLE_APPLICATION_CREDENTIALS`).
- Tier-1 webhook identities are per-space and entirely unaffected — every
  consumer's outbound path keeps working throughout.
- Costs to state honestly: re-adding the app to each space by hand (step 6 of
  the setup doc, console-only), a new tier-2 sender identity, and a window where
  both apps exist. All bounded, none irreversible.

This converts a possibly-one-way door into a reversible migration, which is what
makes recommending D at all responsible.

> ## ⚠ D7 was followed, and its reversibility has since been SPENT — 2026-07-30 (CG-21)
>
> The plan above is what happened: `chat-gateway-gw` was stood up classic from
> the start, verified end to end, and cut over on **2026-07-29**. What follows
> is the one bullet whose truth has changed.
>
> **"Rollback is switching two env values back" is no longer available.**
> `chat-gateway-prod` was **deleted on 2026-07-30**, so there is no project for
> `CHAT_GATEWAY_PUBSUB_SUBSCRIPTION` and `GOOGLE_APPLICATION_CREDENTIALS` to
> point back at, and E2 established that a classic app cannot be toggled back to
> add-ons. Reverting now would mean **provisioning a third project** and
> re-doing the console work — a fresh migration, not a rollback.
>
> That is not a defect in D7. Reversibility was real for the day both projects
> existed, and it was the point: it is what made cutting over safe. It was then
> **deliberately spent** by deleting the old project. Recorded because the bullet
> above, read today, promises an escape hatch that no longer exists — and because
> the sentence *"All bounded, none irreversible"* two lines up is now the
> opposite of the situation.
>
> | D7 bullet | Outcome |
> |---|---|
> | parallel project, cut over, never toggle production | **followed exactly** — and E2 later proved toggling was never available anyway |
> | rollback by switching two env values | **expired 2026-07-30** with the deletion of `chat-gateway-prod` |
> | tier-1 webhook identities entirely unaffected | **held**, and is now empirical rather than predicted — see `CLAUDE.md`'s verification ledger for the evidence and its exact scope |
> | console costs: re-add the app per space, new tier-2 sender identity | **still outstanding, and console-only.** What is actually deployed is a dated console observation in [step 6 of the setup doc](../../google-cloud-setup.md) — not something this repo can prove. |

---

## 7. Restating the selection-widget claim (unblocks CG-11)

> ### ⚠ CORRECTED 2026-07-30 — this section's own replacement wording was wrong
>
> The block quote below originally read **"A selection widget is not an
> interaction trigger"** with no runtime scope, and told CG-11 to adopt it
> *verbatim*. That is false on the runtime this project now runs, and it
> contradicted this ADR's own status banner above, which records E1's opposite
> result. The file disagreed with itself for a day.
>
> **The disproof is a real capture from the live project `chat-gateway-gw`:**
> changing a dropdown on a card with **no button on it at all** produced a whole
> `CARD_CLICKED`, carrying the widget's own `onChangeAction.function`
> (`onVerdictChanged`) as the action identity and the changed value harvested
> into params. Landed as
> `tests/fixtures/classic-cardclicked-onchange-event.json` and pinned by
> `test_normalize_real_classic_onchange_with_no_button_at_all`.
>
> **Nothing below is deleted — it is re-scoped.** The add-ons statements were
> true, and they are now the only surviving record of a runtime whose projects
> have all been deleted (see the status banner). They apply to the add-ons
> runtime, which is where the evidence came from and the only place it ever
> applied.
>
> **Why the original was wrong is worth naming, because it is a repeatable
> mistake.** Every observation in §2 came from an add-ons deployment, and §7
> generalised from it to *"over Pub/Sub transport"* — the **transport**, not the
> **runtime**. Pub/Sub was never the constraint. The add-ons runtime was. The
> same substitution is what makes the dialog claim below sound stronger than it
> is, so the two are kept apart deliberately.

`CLAUDE.md` and `docs/consumers/jobhunt.md` R6 said *"modal dialogs are
impossible over Pub/Sub transport — selection widgets are the supported path."*
The sentence put a proven claim and an untested one on either side of one
confident dash, and got the proven half's scope wrong as well. Replacement
wording, corrected 2026-07-30 and adopted by CG-11:

> **Under the Workspace Add-ons runtime** a card's interactive elements cannot
> trigger the app by the documented mechanism: `action.function` is the
> interaction's *destination* (documented as an HTTPS URL), and a card click is
> not one of the four configurable triggers — so `onClick.action` and
> `onChangeAction` both fail with `gsuiteaddons` code 13 unless routed by the
> topic-as-function pattern (ADR-0001). **On that runtime a selection widget is
> not an interaction trigger.**
>
> **Under a classic Chat app on Pub/Sub — the runtime this project runs — a
> selection widget IS an interaction trigger.** A dropdown's `onChangeAction`
> fires the moment the value changes, delivering its own function name as
> `action.id`, on a card with no button at all. A card carrying both fires
> **twice** per user decision: once on change, once on submit.
>
> ***Widgets for input, one button to submit* is therefore the portable
> pattern** — the only one that works on add-ons, and still the better default
> on classic, because it yields **one event per user decision** instead of two:
> fewer events to make idempotent, and one obvious commit point. Widget values
> arrive in the event's form inputs and are merged into `action.params` at
> submit time. That is what jobhunt R6 actually needs. `onChangeAction` is there
> for genuine live reactivity, not as the default.
>
> True modal dialogs are **believed** impossible over Pub/Sub transport, because
> they require the app to answer the interaction synchronously over HTTP and
> Pub/Sub delivery gives the gateway no response channel at all. That is
> **doc-derived inference and has never been tested, on either runtime.** Do not
> restate it as an observation.

Four labels, kept apart, because the original collapsed them into two:

| Claim | Status |
|---|---|
| a widget cannot trigger an interaction **under add-ons** | **proven false as a general claim, true as an add-ons claim** — code 13, `deploymentFunction: cgSelectProbe`, 2026-07-29 |
| a widget **can** trigger an interaction **under classic** | **capture-verified** 2026-07-30, on a card with no button at all |
| a widget's **value** rides the submit event's form inputs | **capture-verified on both runtimes** |
| true modal dialogs are impossible | **doc-derived inference, never tested** on either runtime |

**UX implication, flagged not specified** (Designer's call, not mine): under
add-ons, cards needed an explicit submit button and select-to-act was
unavailable — a one-tap flow became two taps. Under classic that cost is
**optional**: select-to-act works, so the submit button is now a design choice
about event volume and commit points, not a workaround for a runtime limitation.

---

## 8. Detection — how we find out before the user complains (hard rule #5)

If Google removes topic-as-function routing, the likely observable is code-13
errors on Google's side and **nothing at all on ours**: no event reaches the
topic, so `events_seen` does not move, no counter increments, no exception is
raised, and `/healthz` reports `ok`. The absence of an event is invisible.

That is precisely the failure shape rule #5 exists for — a sibling system's
hardcoded health check hid 11 days of silent capture failure. Adopting D1
without a detector would rebuild that trap in a new place.

**Primary — interaction dead-man (reuses existing machinery).** Register a
gateway-internal heartbeat check `interaction-canary` on schedule `every:7d`
(the existing vocabulary is `weekdays | daily | every:<N><s|m|h|d>` — there is no
`weekly`), cleared by **any** `CARD_CLICKED` arriving on the subscription.
`HeartbeatStore` / `HeartbeatMonitor` already exist and already alert through
`/v1/notify`. If a week passes with no interaction, the operator is told. The
remediation *is* the probe: "go tap a button." An alert that instructs the exact
action needed to confirm or refute it is a good alert.

- Detection latency: ≤ 7 days + grace, versus unbounded today.
- False positives: a quiet week. Acceptable at homelab volume, and the schedule
  is configurable. A false positive costs one tap.
- Deliberately accepts *any* interaction as proof of life — no canary card to
  post, no gateway-authored content, nothing to maintain.

**Secondary — Google-side log alert.** A log-based alert on
`gsuiteaddons.googleapis.com` error code 13 catches the failure at its source and
near-instantly. Weaker than it sounds: code 13 is a generic bucket (§2.6), so it
will fire on unrelated faults, and it lives in Cloud Monitoring rather than in a
system we control. Complementary, not primary — and note that
`pubsub.googleapis.com/topic/send_request_count` is already documented in
`google-cloud-setup.md` as untrustworthy, so no detector should be built on it.

**Tertiary — `id_source` drift** (D4): catches a behaviour change that still
delivers events, which neither detector above would notice.

---

## 9. Hard-rule audit

| Rule | Effect |
|---|---|
| **#1 transport, never schemas** | Argued at length in D2. The gateway defines a key name and relocates its value; it never branches on the value. No tenant vocabulary enters the gateway. The one honest cost — producers must know a gateway-defined key — is an envelope extension, which rule #1 explicitly permits, and is flagged for sign-off. |
| **#2 secrets are env-only** | Unaffected. The topic path is classified non-secret by `google-cloud-setup.md` step 8. No new value is logged; the existing `configCompleteRedirect*` redaction is untouched. |
| **#3 adapters + flags** | All changes land in `adapters/pubsub.py`. D6 respects the two-word flag cap rather than expanding it. |
| **#5 honest `/healthz`** | Strengthened, not weakened: §8 adds a detector for a failure mode that is currently invisible, plus D4's counter. Adopting D1 *without* §8 would violate this rule in spirit. |
| **#6 inbound opt-in, opt-out absolute** | **Untouched.** No option here changes `apps_for_space` → `allow_inbound` → `allowed_users`. `aitrader` remains locked out of every inbound path under every option. Option C would change the gateway's *own* network exposure but still not any tenant's authorization surface — and C is not being adopted. |

---

## 10. Experiments that would settle what we could not verify

> **All four experiments are resolved or deferred; none is outstanding.** E1 and
> E2 **ran on 2026-07-29** and their results are recorded in each subsection
> below and summarised in the status banner at the top of this ADR. E3 and E4
> are **deferred and must not be executed** — E1 lowered the value of both, since
> each probes a limitation of the add-ons runtime this project no longer deploys
> on. Tracked as CG-15 / CG-16 (ran) and CG-17 / CG-18 (deferred).

### 10.0 What the two runtimes can actually do — the capability comparison

Recorded here because **every project that produced the add-ons evidence has
been deleted** (see the status banner), so none of the left-hand column can ever
be re-observed by anybody. This table and the committed fixtures are the only
surviving record.

| Capability | Workspace Add-ons + Pub/Sub | Classic Chat app + Pub/Sub | Evidence |
|---|---|---|---|
| Card **button** click reaches the topic | **No** by the documented mechanism — `gsuiteaddons` code 13, `deploymentFunction: approve`. Works **only** via the undocumented topic-as-function pattern (§2.3) | **Yes, natively**, with an ordinary function name | first-hand on both — §2.2/§2.3 (add-ons), E1 + the migration verification (classic) |
| Selection widget `onChangeAction` | **No** — code 13, `deploymentFunction: cgSelectProbe`, identical to a button | **Yes, it fires** — including on a card with **no button on it at all**, delivering the widget's own function name | first-hand on both — §2.2 (add-ons), E1 2026-07-29 plus a live capture 2026-07-30 (classic) |
| Action identity (`action.id`) | **Absent.** The function slot is consumed as the routing destination, so no action name arrives; identity must ride in `__cg_action__` (D2) | **Native** — `action.function` is a function name again and echoes back as `action.id` | real captures on both — §2.5 (`action.id: ""`), E1 (`action.id: 'approve'`) |
| Envelope format | `commonEventObject` + `chat.<x>Payload` — reported as `envelope_format: "addon"` | flat `type` / `space` / `message` / `user` — reported as `envelope_format: "classic"` | real captures on both; the gateway normalizes either |
| Slash-command shape | `chat.appCommandPayload` | a **MESSAGE** event carrying `message.slashCommand` | **documentation only — never observed here, on either runtime.** Add-ons release notes 2024-12-18 record the difference as a breaking change. E3 (§10, CG-17) is the experiment that would settle it and it is deferred |
| True modal dialogs | believed impossible | believed impossible | **doc-derived inference, never tested on either runtime.** Dialogs need a synchronous HTTP interaction endpoint; Pub/Sub gives the gateway no response channel. This one is a property of the **transport**, not the runtime — the only row here for which that is true |

**Four of those six rows are first-hand on both runtimes. Two are not, and the
distinction is deliberate.** The slash-command row is read off Google's release
notes and has never been exercised here; the dialog row has never been tested at
all. A summary of this table that calls it "the two live-verified capability
tables" over-claims by exactly those two rows — which is why they carry their
evidence in the same table rather than in a footnote somebody can drop.

### E1 — Does a classic Pub/Sub Chat app actually receive `CARD_CLICKED`? *(~20 min, decides option D)*

**RAN 2026-07-29 · PASSED.** Delivery was native, `action.id` came through as
`'approve'`, and `onChangeAction` fired. §11 trigger 1 has fired; the recipe
below is kept as the record of what was run.

**Scratch GCP project only. Never `chat-gateway-prod`.**

1. New project; enable Google Chat API + Pub/Sub API.
2. `gcloud pubsub topics create chat-test` /
   `gcloud pubsub subscriptions create chat-test-sub --topic=chat-test`
3. Chat API → **Configuration**:
   - **Clear** *"Build this Chat app as a Google Workspace add-on"* → confirm **Disable**.
   - App name / avatar / description (anything); interactive features **on**;
     Functionality = *Join spaces and group conversations*.
   - Connection settings = **Cloud Pub/Sub**, topic `projects/<ID>/topics/chat-test`.
   - Visibility = your own email. Logs = *Log errors to Logging*. **Save**.
4. **Copy the service-account email shown under Connection settings and grant it
   `roles/pubsub.publisher` on `chat-test`.** Skipping this reproduces exactly the
   silent-failure trap already documented in `google-cloud-setup.md` — Chat
   cannot publish, and nothing says so.
5. **Baseline first:** DM the app, then
   `gcloud pubsub subscriptions pull chat-test-sub --auto-ack --limit=10`.
   A MESSAGE event must arrive. If it does not, the wiring is wrong and step 7's
   result would be meaningless.
6. Post a card into that DM with an **ordinary** function name:
   `{"onClick":{"action":{"function":"approve","parameters":[{"key":"id","value":"t1"}]}}}`
7. Tap it; pull again.

| Outcome | Meaning |
|---|---|
| **PASS** — a message arrives containing `"type": "CARD_CLICKED"` | Option D is real. Also record whether `common.invokedFunction == "approve"` and whether parameters survive — that determines whether our existing classic dispatch path works unchanged. |
| **FAIL** — nothing on the topic, and/or Chat shows *"App is unable to process your request"* | Option D collapses; the bridge becomes the design and §8's detector becomes load-bearing rather than prudent. |

Capture the raw pulled JSON either way — it settles Q2 permanently and becomes a
fixture.

### E2 — Is the add-on toggle reversible? *(~2 min, ride-along on E1)*

**RAN 2026-07-29 · ANSWERED: NO.** The toggle is create-time only — see §5
option D. The stated limit below turned out not to matter: the answer was
negative even on a project whose add-on was never deployed via `gsuiteaddons`,
which is the *weaker* case.

In the same scratch project after E1: tick the add-on box, Save, then try to
clear it and Save again. **Stated limit, which is the whole point:** this tests a
project whose add-on was never *deployed* via `gsuiteaddons`. A clean clear is a
positive signal about the CloudM warning being stale — it is **not** clearance
for our real project, which has a live deployment. D7 exists precisely so that
E2's answer does not gate anything.

### E3 — Do slash commands reach the topic? *(~10 min, decides whether B has a fallback)*

**DEFERRED — do not run** (CG-17). It was the bridge's escape hatch; the escape
hatch is now the classic migration, which is proven and done. Kept filed because
slash commands land differently on classic (see §10.0), so the normalizer would
need the classic shape, not this one.

On the **current** deployment: configure an App command trigger, type
`/approve 123`, pull. Record (a) whether anything arrives at all, (b) the command
id — expected `chat.appCommandPayload.appCommandMetadata.appCommandId`, which is
VERIFIED in the field reference, and (c) where the typed argument text lands —
expected `chat.appCommandPayload.message.argumentText`, **unconfirmed**: Google
documents `argumentText` as *"Plain-text body of the message with all Chat app
mentions stripped out"* and never states that the command token itself is
stripped. Do not assume the exact string.

Also worth knowing: **no fully-expanded `appCommandPayload` example exists in
Google's documentation** — the only published JSON is a three-field skeleton.
This is a genuine doc gap; nobody should fill it from memory.

### E4 — Does `onChangeAction` work with the topic path as its function? *(~5 min)*

**DEFERRED — do not run** (CG-18), and largely answered sideways. E1 settled the
question that mattered: `onChangeAction` fires natively on classic, so §7's
two-tap cost disappeared at migration regardless of whether it was recoverable
under the bridge.

Re-run the failed `cgSelectProbe` with `function` set to the topic path instead
of a name. Settles whether select-to-act is recoverable — i.e. whether §7's
two-tap UX cost is permanent under the bridge.

### Ordering

E1 (+E2) first: they decide the destination. E3 next: it decides whether the
bridge has a floor. E4 is a UX nicety, last.

One unread source could settle E1 outright without any experiment: **Issue
Tracker 175772204**, *"Support button click events in Hangouts Chat …"* (title
truncated in search results). It requires a signed-in browser, which the research
tooling did not have.

---

## 11. Triggers to revisit

Revisit this ADR when **any** of these fires:

1. **E1 comes back PASS** → migrate to option D via D7's parallel project;
   demote topic-as-function to a historical note. This is now the *expected*
   outcome, not a remote one, and it is the reason D1 is framed as a bridge.
   E2 does not gate this — D7 removes it from the critical path.
2. **The interaction dead-man fires and a manual tap confirms breakage** →
   topic-as-function is gone; fall back to slash commands (if E3 proved them) or
   escalate to D/C.
3. **`id_source` starts reporting `google`** → Google changed the runtime's
   behaviour underneath us while still delivering. Re-verify before it degrades.
4. **Google documents either behaviour** (topic-as-function, or classic Pub/Sub
   CARD_CLICKED) → the risk calculus changes materially in one direction or the
   other.
5. **The classic deployment model gets a deprecation date** → option D acquires
   an expiry and the calculus inverts.
6. **The homelab gains a hardened public ingress** → option C becomes available
   on capability grounds, and it is the only option that unlocks modal dialogs.
7. **A second two-way tenant appears** → the blast radius in §3.1 is no longer
   "jobhunt only", and this trade-off is re-priced.

---

## 12. Open questions — need an explicit user yes

> ### ⚠ ALL FIVE ARE ANSWERED — none of this is outstanding (updated 2026-07-30)
>
> This section's title is kept for referential stability (D2, D6 and the queue
> all cite "§12"), but nothing below awaits a user. The decisions are recorded in
> `docs/BUILDER_QUEUE.md`'s decisions table, which is authoritative if these ever
> disagree.
>
> | # | Question | Answer |
> |---|---|---|
> | 1 | **D2** — `__cg_action__` as a gateway-reserved key | **APPROVED** 2026-07-29, including the topic-path guard; shipped as CG-10. Since **reframed to an add-ons compatibility fallback**: on classic, action identity is native and `__cg_action__` is inert. It is kept because it is load-bearing on add-ons and still outranks the native slot, so one card behaves identically on both runtimes. |
> | 2 | **D6** — a third flag word | **NO.** `⚠ SHAPE-VERIFIED` stays the only addition; hard rule #3's cap holds. Routing fragility lives in prose and `/healthz`, never a new flag word. |
> | 3 | **E1 / E2 authorization** | **GRANTED**, and both ran 2026-07-29 in a throwaway project. The prohibition on running them against `chat-gateway-prod` was honoured — and is now moot, because `prod` and E1's own project were both deleted 2026-07-30. |
> | 4 | **§8's `interaction-canary` dead-man** | **APPROVED, then closed as obsolete before it was built** (CG-14, user decision 2026-07-30). **Nothing was implemented.** E1 removed its premise: it was designed to detect silent breakage of *undocumented* routing, and classic has no undocumented dependency to break. CG-7's subscriber-liveness checks cover the residual failure modes faster and more precisely. |
> | 5 | **Migrate to option D in principle** | **YES** — and it is **done and live-verified**, 2026-07-29, on `chat-gateway-gw`. E2 then showed D7's parallel-project path was the only one available anyway. Tracked as CG-21. |

1. **D2 — approve `__cg_action__` as a gateway-reserved parameter key?** This
   changes the shared envelope contract in the inbound direction and asks
   producers to know a gateway-defined key. Recommended **yes**; the rule #1
   argument is in D2, including its honest cost. *(Same class of decision as
   DEC-3, which was correctly escalated rather than assumed.)*
2. **D6 — confirm no third flag word.** Recommended: keep the rule #3 cap, record
   the fragility in prose + `/healthz`. If you want `⚠ UNDOCUMENTED-ROUTING` as a
   third word, that is an amendment to hard rule #3 and needs to be said
   explicitly.
3. **E1 / E2 authorization.** These need a scratch GCP project and a human in the
   console. Confirm they may be run — and confirm the prohibition on running them
   against `chat-gateway-prod`. **This is the highest-value question here:** E1
   is ~20 minutes and it decides whether the undocumented dependency is a bridge
   or the permanent design.
4. **§8 primary detector** — approve the weekly `interaction-canary` dead-man,
   accepting that a genuinely quiet week produces a false alarm whose remediation
   is one tap?
5. **Is a migration to option D wanted in principle**, assuming E1 passes? D7's
   parallel-project path costs a fresh Cloud project and re-adding the app to
   each space by hand. Recommended **yes** — it trades a console afternoon for
   removing an undocumented dependency from the two-way contract permanently —
   but it is your time, so it is your call.

---

## 13. What this ADR could not verify

Recorded plainly, because an unrecorded gap becomes a silent assumption:

> **Two of these gaps have since been CLOSED by experiment — E1 and E2, both
> 2026-07-29 — and are rewritten below rather than deleted.** They stayed in
> their original wording until 2026-07-30, which meant the one section a reader
> consults for *what is still open* was handing back the pre-experiment answer
> while §5, §10.0, §12 and the status banner all said otherwise. The rest of
> this list still stands.

- **Topic-as-function is undocumented.** Not contradicted — *absent*. Two
  research passes across ~50 pages, both changelogs, two sample repos and
  multiple search engines found nothing. That is strong but not proof of absence;
  the sitemap crawl was not exhaustive.
- **Classic Pub/Sub CARD_CLICKED delivery — SETTLED, first-hand, 2026-07-29**
  (E1). This bullet previously read *"inferred, never cited… the indirect
  evidence is good and two passes reached it independently; that neither could
  cite it is itself informative — probably real, genuinely undocumented."* It is
  now observed, not inferred: a real card click arrived natively in a throwaway
  classic project with `action.id: 'approve'`, and it has since been re-observed
  on the live `chat-gateway-gw` (§5 option D, §10.0). **The bullet's own
  observation held up** — "probably real, genuinely undocumented" was the right
  read of the silence. Neither research pass could cite it because Google does
  not document it, not because the inference was weak; the behaviour and its
  absence from the documentation are independent facts, which is the same pairing
  §2.3 found from the other direction.
- **Slash commands over Pub/Sub are unobserved here** (E3). Delivery is
  documented in prose but contradicted by the commands page, and the two are
  unreconciled anywhere. The command-id field is verified in the field
  reference; the argument-text field is expected, not confirmed. No expanded
  `appCommandPayload` example exists in Google's docs at all.
- **Add-on toggle reversibility — SETTLED, and the answer is NO** (E2,
  2026-07-29). This bullet previously read *"contradictory — Google's
  quickstarts versus one third-party vendor doc, with no Google statement
  covering the post-deployment case that is actually ours. D7 routes around it
  rather than resolving it."* D7 did route around it, and that was the right
  call; the contradiction is now resolved rather than merely avoided. The toggle
  is **create-time only** — it cannot be cleared once the app has been saved. Of
  the two contradicting sources it was the **third-party vendor doc (CloudM) that
  was right**: Google's quickstarts describe a never-saved state on a fresh app,
  which is a different case from ours. Escaping add-ons therefore needs a new
  Chat app and, because Chat app config is per-project, a new GCP project — see
  §5 option D.
- **The StackOverflow corroborations in §2.7 were not read directly** — the
  research fetch was blocked. Leads, not citations.
- **Research coverage was ~50 pages plus multi-engine search across two passes,
  not an exhaustive site sweep.** "Not documented" here means "not found by a
  substantial search", which is strong but is not proof of absence.
- **`tests/fixtures/addon-card-clicked-event.json` is fiction on one point:** it
  contains `__action_method_name__`, which the real capture proves absent under
  this pattern. CG-3 already decided to keep it, relabelled as *unobserved
  tolerance coverage* rather than *the shape we expect Google sends* — that
  relabelling is now mandatory, not optional.

---

## 14. Related decisions and handoff

- [Live-verification follow-ups spec](../../superpowers/specs/2026-07-29-live-verification-followups-design.md)
  §2 N1–N4 — the four decisions deferred to this ADR, all answered here.
- [Envelope normalization spec](../../superpowers/specs/2026-07-29-chat-event-envelope-normalization-design.md)
  §4.5 — the `__action_method_name__` prediction this ADR **supersedes**, and
  DEC-3, whose reasoning D2 follows deliberately.
- `docs/consumers/jobhunt.md` — R3 (`action.id` semantics), R6 (structured
  reasons). **Both restated — CG-11, 2026-07-30.** R6 carried §7's original,
  unscoped *"a selection widget is not an interaction trigger"*; §7 itself was
  corrected in the same item, so what R6 now restates is the runtime-scoped
  version rather than the add-ons-derived one.
- `docs/integration-guide.md` — the inbound example at line 87 showed
  `"action":{"id":"verdict",…}`, unreachable under the add-ons runtime without
  D2. **Corrected — CG-13, 2026-07-29**, alongside the card convention (D3),
  which shipped in the same item.
- `docs/google-cloud-setup.md` — **contained a factual error this ADR corrects;
  both halves are now fixed.** The note under step 7 (*"The app will not appear
  under ⚙ → Apps & integrations → Add apps until the Google Workspace
  Marketplace SDK … is enabled and the app is published"*) is contradicted by
  Google's own documentation: installability comes from Chat API **Visibility**,
  and the Marketplace SDK's settings are explicitly *ignored* for Chat (§5,
  option D). That error is why we were on the add-ons runtime at all — so it
  needed correcting whether or not the migration happened, and it was:
  **CG-6, 2026-07-29**, kept in place as a `⚠ CORRECTED` block rather than
  quietly deleted. Step 5 changed under option D as predicted here —
  **CG-20, 2026-07-30** — which also added the create-time-only toggle trap
  beside it (E2).

**Queue impact — all of it is now resolved; this paragraph is kept as the record
of what was implied at the time.** It read *"Planner's call, not written
here"* and listed the following as open. CG-10 (unblocked by D2 + D4) **shipped
2026-07-29**; CG-11 (unblocked by §7's wording) **shipped 2026-07-30**, and it
corrected §7 rather than adopting it. Of the four then-unqueued implications: D3
(`interaction_routing_target` on `/v1/identities` + the card convention in the
integration guide) **shipped as CG-13**; §8's interaction dead-man was queued as
CG-14 and **closed as obsolete without being built** (E1 removed its premise);
E1 and E2 **ran** as CG-15 / CG-16 while E3 and E4 are **deferred, do-not-run**
as CG-17 / CG-18; and the `google-cloud-setup.md` correction shipped in two
parts, **CG-6** (the Marketplace error) and **CG-20** (step 5, the deleted
project, and the toggle trap).
