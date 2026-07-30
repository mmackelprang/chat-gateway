# Gateway → jobhunt · integration handoff

**Date:** 2026-07-30 · **From:** chat-gateway · **To:** jobhunt
**Answers:** jobhunt's `docs/chat-gateway-requirements.md` (R1–R9, 2026-07-24)

**Direction matters.** That requirements document is what jobhunt sent *to* the
gateway. This file is the answer *back*: what is built, how to wire against it,
what has been proven against Google and what has not.

Two files, deliberately not one:

| File | What it is |
|---|---|
| [`jobhunt.md`](jobhunt.md) | the **contract** — requirement → implementation map, plus the recorded deviations |
| this file | the **handoff** — how jobhunt builds against it today, and the state of each guarantee |

---

## 1. Status at a glance

| R | Requirement | Gateway status |
|---|---|---|
| R1 | multi-tenant dumb pipe, one config file per tenant | **implemented** — registry directory mode, per-app `callback_url` |
| R2 | rendering stays with the producer | **implemented** — `cardsV2` passes through verbatim; the gateway validates shape and caps size, never rewrites |
| R3 | interactions forwarded whole, with an idempotency key | **implemented**; **never exercised end to end** — see §10 |
| R4 | authZ at the gateway, again at the tenant | **implemented** — `allowed_users`, in-thread refusal, never forwarded |
| R5 | traffic shape (digest, instant lane, retro, health) | **producer-side**; the instant lane is `POST /v1/messages` (synchronous) or `POST /v1/notify` (accept-fast) |
| R6 | structured reject reason | **implemented** — selection-widget values arrive merged into `action.params` |
| R7 | fail loudly in-thread | **implemented**; the one inbound link today's configuration actually exercises — see §10 |
| R8 | separability | **implemented** — HTTP only, no code imports either direction |
| R9 | migration continuity | **held, twice** — see §8 |

"Implemented" means the code exists and is covered by deterministic offline
tests. It does **not** mean the path has met Google. §11 says which links have.

---

## 2. R1 — a multi-tenant dumb pipe

**One config file per tenant.** `load_registry` accepts either a single YAML
file or a **directory**: every `*.yaml` in it is merged, and a duplicate
identity or app name across files is a load error rather than a silent
last-writer-wins. That is the `notification_routing/` one-file-per-project
convention R1 asked for. The live deployment currently uses the single-file
form; switching to directory mode is an operator change of one env var
(`CHAT_GATEWAY_REGISTRY`) and needs nothing from jobhunt.

**No jobhunt semantics live in the gateway.** The gateway owns identity,
delivery, threading and inbound routing. It never parses a card, never learns
what `approve` means, and never renders on jobhunt's behalf — gateway hard rule
#1. The single exception to "forwards everything untouched" is one Google-owned
field, documented in §4.

**Your app id is `job-hunter`, with a hyphen.** The contract doc's sample
config and the integration guide's sample callback body both say `jobhunt`;
the **live registry** registers the app and the identity as `job-hunter`, so
that is the value that arrives in the callback's `app` field. Worth knowing
before a receiver is written against the example payload.

---

## 3. R2 / R5 — outbound

`POST /v1/messages` takes the envelope and delivers synchronously:

```json
{"identity": "job-hunter",
 "text": "3 shortlisted roles — 2026-07-30",
 "cards": [{"cardId": "digest-2026-07-30", "card": { }}],
 "thread_key": "digest-2026-07-30"}
```

- `text` is required (1–4000 chars) even when cards are present — Chat uses it
  as the notification fallback, so it is what a phone shows on the lock screen.
- `cards` is passed through **verbatim**. The gateway checks only that each
  entry is a Cards v2 wrapper (a dict with a `card` key) and that the whole list
  serializes under **30KB**, which is Chat's own message limit. Either failure is
  a **422** — naming the offending index, or naming the limit — never a silent
  truncation.
- `thread_key` is jobhunt's own conversation key, echoed back on inbound events.

`POST /v1/notify` is the accept-fast lane (202 on enqueue, async delivery with
backoff, dedupe window, delivery log). jobhunt's rare health alerts (its J14
zero-yield scans) fit it; the latency-sensitive instant-lane pings of R5 are
better served by `/v1/messages`, which returns the delivery result inline.

---

## 4. R3 — interactions forwarded whole

Set `callback_url` on the app (§9.3) and every **authorized** event is POSTed
to it as one JSON body:

```json
{"app": "job-hunter",
 "space": "spaces/XXXX",
 "thread_key": "digest-2026-07-30",
 "thread_name": "spaces/XXXX/threads/T1",
 "message_id": "spaces/XXXX/messages/M1",
 "sender_display": "Mark",
 "sender_email": "mark@mackelprang.com",
 "text": "",
 "action": {"id": "verdict", "id_source": "cg_param",
            "params": {"job_id": "job-123", "nonce": "n-9", "reject_reason": "comp_low"}},
 "dedupe_key": "20759411966000501",
 "event_type": "CARD_CLICKED",
 "envelope_format": "classic",
 "received_at": "2026-07-30T12:48:52.884583Z",
 "raw": {"...": "the whole Google event, one field redacted — see below"}}
```

### `dedupe_key`, and why jobhunt's callback MUST be idempotent

`dedupe_key` is the **Pub/Sub message id**. Pub/Sub delivery is
**at-least-once** — that is a property of the transport, not a gateway
shortcoming, and no amount of gateway code removes it. A tap can therefore
arrive at jobhunt's callback **more than once**, and the gateway's own retry
policy (§7) makes that strictly more likely, not less: a callback that times
out after doing the work still gets retried.

So: **jobhunt's callback must be idempotent, keyed on `dedupe_key`.** R3
already anticipated this — self-contained button tokens (`job_id + verdict +
nonce`) are the belt to `dedupe_key`'s braces, and jobhunt's single verdict
write-path is the natural place to enforce "record this verdict once".

Return **any 2xx quickly** and do the work asynchronously. A 2xx is what stops
the retry clock; anything else, including a slow success that trips the 10s
client timeout, counts as a failure and moves the job toward R7's loud failure.

### The one field that is not forwarded whole

R3 says *whole*. Exactly one field is blanked to `<redacted-by-gateway>` before
an event is audited or POSTed: Google's `configCompleteRedirectUri` (add-ons
spelling) and `configCompleteRedirectUrl` (classic spelling). It is an
unguessable, per-message, state-changing capability URL — visiting it makes the
user's private message **public in the space** and re-delivers it. Forwarding it
would hand every opted-in tenant that capability. Nothing else in `raw` is
touched and no normalized field is affected. This is a deliberate, disclosed
single-field exception, recorded here and in the contract doc rather than left
as a silent gap.

### `action.id` can be `null`, and jobhunt must handle it

`null` means the gateway could not resolve an action identity from any source.
It is **never** `""` — that ambiguity was a real defect and was removed. Reject a
`null` explicitly rather than guessing; the event is still delivered on purpose,
because a parse-quality problem must not become a silent drop. `action.id_source`
reports `"cg_param"`, `"google"` or `null` and is transport metadata: jobhunt can
ignore it, but a change in it means the runtime underneath moved.

---

## 5. R4 — authorization at the gateway

`allowed_users` on the app is an email allowlist, compared **case-insensitively**
(the registry lower-cases on load, and the sender's address is lower-cased on
arrival). jobhunt's list is exactly one address, as R4 specified. An empty list
means no restriction.

A sender who is not on the list:

1. is **never forwarded** — no callback, no `/v1/inbox` entry, no `_unrouted`
   audit record;
2. gets an in-thread reply reading **`⛔ Not authorized for this action.`**;
3. increments `/healthz` → `subscriber.suppressed_not_authorized`.

Three details worth having:

- **The refusal is posted by the Chat app, not by the "Job Hunter" identity.**
  In-thread replies go out through the Chat API as the gateway's Chat app
  (`Agent Comms`, `type: BOT`) — the tier-1 webhook identity cannot reply. A
  refused user therefore sees the refusal from the app, in their thread.
- **It needs a tier-2 reply path.** The reply function is wired whenever
  `GOOGLE_APPLICATION_CREDENTIALS` is set, independently of whether jobhunt's
  identity is `mode: webhook` or `mode: app`. Without credentials the user is
  still never forwarded — the guarantee holds — but they are told nothing.
- **The counter is per candidate app, not per event.** It counts *apps that
  declined an event*, so it is not a count of events that went nowhere; in a
  space with more than one registered owner, one owner can decline while another
  receives the same event. `subscriber.events_seen` is the event count.
  These counters are **bare integers** — no space, no app id, no sender, no
  content, no timestamp — because `/healthz` is **unauthenticated**. If you need
  to know *which* user was refused, `/healthz` is deliberately not where you will
  find it.

R4's second half is jobhunt's: the gateway forwards, it never interprets. What
an Approve *means* — recording a green-light verdict tagged `via: chat`, and
never triggering a submission — is enforced by jobhunt's own write-path. Gateway
hard rule #6 is written that way on purpose.

**If the refusal itself fails to post** (Chat unreachable), the exception escapes
`dispatch`, the event is acked and dropped, `subscriber.dispatch_errors`
increments, and the gateway console prints the exception **type name only** —
`ChatApiError`. The type-name-only rule is deliberate (an exception message can
embed a payload value; hard rule #2), so the console is not where the detail
lives. This one is worth knowing because it is the case where a refusal is
neither delivered nor visible to the refused human.

---

## 6. R6 — structured reject reasons

jobhunt's reject verdict needs one of its enum reasons
(`comp_low / wrong_seniority / wrong_domain / location / company / meh`). Put a
`selectionInput` on the card; its chosen value arrives merged into
`action.params` under the widget's `name`, alongside the button's own
parameters. The gateway does not know what a reject reason is — it merges
Google's form inputs into the params dict and forwards, which is exactly what
R6 needs and no more.

**Two ways a value can reach jobhunt, and which to prefer:**

| Pattern | What happens | When |
|---|---|---|
| **widgets for input, one button to submit** | Chat harvests the widget values on the **button** tap and the gateway merges them into `action.params` — **one event per user decision** | the default; portable across both Google runtimes |
| **`onChangeAction` on the widget itself** | the widget fires its own interaction the moment the value changes | only when live reactivity is genuinely wanted |

**On the classic runtime a selection widget IS an interaction trigger.**
Verified 2026-07-30 on a real capture from the live project: changing a dropdown
on a card that had **no button on it at all** produced a whole `CARD_CLICKED`
event, with the widget's own `onChangeAction.function` arriving as `action.id`
(`id_source: "google"`) and the changed value harvested into params. Landed as
`tests/fixtures/classic-cardclicked-onchange-event.json` and pinned by
`test_normalize_real_classic_onchange_with_no_button_at_all`.

That corrects an older claim, derived from the **add-ons** runtime, that a
widget is never an interaction trigger — under add-ons its `onChangeAction`
does fail (`gsuiteaddons` code 13), and that scoping was lost when the sentence
was written down. **The correction has not yet reached every document.**
`CLAUDE.md`, `docs/consumers/jobhunt.md` R6, ADR-0001 §7 and the integration
guide's producer convention still carry the older wording; queue item **CG-11**
owns fixing all of them and had not shipped when this file was written. Where
they and this file disagree about whether a widget can trigger an interaction,
**this file and the fixture are right** — but do not take that as licence to
assume the rest of those documents are stale.

**True modal dialogs.** They are believed impossible over Pub/Sub transport,
because a dialog requires the app to answer the interaction **synchronously**
over HTTP and Pub/Sub delivery gives the gateway no response channel at all.
Label that honestly: it is **doc-derived inference and has never been tested**,
on either runtime. The practical answer is unchanged either way — build R6 on
selection widgets, which are proven to work and are what jobhunt actually needs.

---

## 7. R7 — fail loudly in-thread

When a callback cannot be reached, the forwarder makes **three attempts**,
spaced `0s / 3s / 7s` — those are the **gaps**, not offsets from the tap: the
first attempt is immediate, the second 3s after it fails, the third 7s after
that. The last attempt is therefore due about **10 seconds** after the tap.
On exhaustion:

1. records `failed` in the delivery log with
   `gave up after 3 attempts (ConnectError)`;
2. posts the app's `unreachable_message` into **the same thread the user tapped
   in**, so the person who tapped sees that it did not land.

Silent failure is R7's one unacceptable outcome, and this is the path that
prevents it.

**That schedule is a floor, not a timer.** Due jobs are processed by the
subscriber loop, immediately after each successful poll — so an attempt fires on
the first poll tick at or after its due time, never earlier. Measured at the
loop's default 5s interval, the three attempts land at **0s / 5s / 15s**, so the
in-thread notice arrives around 15 seconds after the tap rather than 10. Short
and human-shaped either way: a person is standing there having just tapped a
button.

**Failure of the failure notice is itself typed and logged, as of 2026-07-30**
(CG-25). If the in-thread notice cannot be posted either, the log records
`failed-silent` with `in-thread notice also failed: in-thread reply failed:
ConnectError`. Before that change the same line read a bare `connection refused`
sitting one row under `gave up after 3 attempts (ConnectError)`, where it was
easy to misread as a fourth callback retry. It now names the operation and the
exception type. The doubled prefix is real and was left alone rather than
quietly reworded.

**Tier-1-only deployments cannot post the notice.** With no Chat app credentials
there is no reply path, and the outcome is logged as `failed-silent` with
`no reply_fn (tier 1) — in-thread notice impossible`. **Full R7 requires tier
2.** This is a documented limitation, not a defect: `GET /v1/deliveries` still
shows every callback attempt and its terminal status, so the failure is never
invisible to an operator — only to the person who tapped.

---

## 8. R9 — migration continuity, twice over

**Adopting the gateway costs jobhunt no rendering change.** jobhunt already
produces Cards v2 payloads; the gateway accepts them verbatim. Today the
`job-hunter` identity is registered `mode: webhook`, so the digest still goes out
over the tier-1 named incoming webhook exactly as it did before — R9's
"until you ship" state is still the live one for outbound. Moving outbound to
tier 2 is a **registry-side** change (`mode: webhook` → `mode: app`); jobhunt's
payload does not move.

**And the runtime migration underneath cost zero card changes.** Between
2026-07-29 and 2026-07-30 the gateway's Chat app moved from the Workspace
Add-ons runtime to a classic Chat app on a different GCP project. Producers that
had followed the fetch-don't-hardcode convention (§9) needed no card edits at
all. That is the whole reason the convention exists, and it has now paid for
itself once.

**Tier 1 is project-independent, empirically.** All four webhook identities
delivered through the real adapter *immediately after* the old GCP project was
deleted. No tier-2 deployment change can take jobhunt's outbound digest down.

---

## 9. Building the card, and what jobhunt must configure

### 9.1 Fetch the wiring — never hardcode it

```bash
curl -s "$GW/v1/identities" -H "Authorization: Bearer $CHAT_GATEWAY_API_KEY__JOB_HUNTER"
# -> {"app": "job-hunter",
#     "identities": [{"name": "job-hunter", "display": "Job Hunter", "mode": "webhook", "ready": true}],
#     "interaction": {"enabled": true,
#                     "routing_target": "<gateway-published value>",
#                     "action_key": "__cg_action__",
#                     "note": "..."}}
```

- `interaction.routing_target` → the card's `onClick.action.function`.
- `interaction.action_key` (`__cg_action__`) → the parameter carrying jobhunt's
  own action identity. The gateway lifts it into `action.id` and **pops it out**
  of the params jobhunt receives, so the handler sees only its own parameters.

If `interaction.enabled` is `false`, read the `reason` — either the app is
`allow_inbound: false`, or the operator has not set a routing target yet.
**Do not guess a value.** A card built against a guess fails at tap time, in
front of a user.

The whole `__cg_` prefix is reserved for the gateway. Unknown `__cg_*` keys are
passed through rather than eaten, but do not invent your own.

### 9.2 The `parameters` shapes — read this table, do not summarize it

```jsonc
"onClick": {
  "action": {
    "function": "<interaction.routing_target>",
    "parameters": [                                    // an ARRAY, always
      {"key": "__cg_action__", "value": "verdict"},
      {"key": "job_id",        "value": "job-123"},
      {"key": "nonce",         "value": "n-9"}
    ]
  }
}
```

| Direction / runtime | Where | Shape |
|---|---|---|
| **outbound**, every runtime | `onClick.action.parameters` | an **array** of `{key, value}` — the Cards v2 schema |
| **inbound**, **classic** | `action.parameters` | an **array** — symmetric with what was sent |
| **inbound**, **add-ons** | `commonEventObject.parameters` | a **map** |

Every row is from a first-hand capture. **Do not compress this to "you send an
array, you receive a map."** The map is an **add-ons-runtime quirk**, not a
property of the inbound direction — someone debugging a raw classic event after
reading the short version would conclude the gateway was broken. That exact
compression has been written down and corrected in this repo before, which is
why `CLAUDE.md` pins both halves with tests
(`test_card_parameters_are_an_array_in_the_real_captured_card`,
`test_inbound_parameter_shape_is_a_runtime_property_not_a_direction_rule`).

jobhunt should not need any of this: the gateway normalizes both into a plain
`action.params` object. It is documented so that nobody reading a raw event
concludes the guide is wrong.

### 9.3 Required registry configuration

Four values on the app, three of them jobhunt's to specify:

```yaml
apps:
  job-hunter:
    key_env: CHAT_GATEWAY_API_KEY__JOB_HUNTER     # env-var NAME; the key lives in .env
    identities: [job-hunter]
    allow_inbound: true                            # already the default; explicit once inbound is live
    callback_url: "http://127.0.0.1:8710/chat-callback"    # appserver-local
    allowed_users: [mark@mackelprang.com]          # R4 — exactly one
    unreachable_message: "⚠️ couldn't reach jobhunt — use the review UI"   # R7
```

And the identity, whose `space` is what makes inbound routing resolve:

```yaml
identities:
  job-hunter:
    display: "Job Hunter"
    mode: webhook                                  # tier 1 today; `app` when tier 2 is adopted
    webhook_url_env: GOOGLE_CHAT_WEBHOOK_URL__JOB_HUNTER   # env-var NAME
    space: "spaces/XXXX"                           # the JobHunt space
```

**Secrets are env-only** (hard rule #2). The registry holds env-var **names**;
the webhook URL — which embeds `key` and `token` and *is* a bearer credential —
and the per-app API key live only in the runtime environment. If jobhunt's
callback URL ever needs to carry a token, put it behind indirection:
`callback_url: "${CHAT_GATEWAY_CALLBACK_URL__JOB_HUNTER}"` is resolved from the
environment at call time.

`callback_url` on an `allow_inbound: false` app is a **registry validation
error**, not a silently ignored field.

---

## 10. The live blocker — stated precisely

Two things are true at once, and collapsing them has already produced one wrong
description of this situation.

**Routing resolves today.** Against the live registry,
`apps_for_space('spaces/AAQAgjGR7J4')` returns `['job-hunter']`. `callback_url`
genuinely is the only registry value that was missing. An earlier claim that the
identity's `space` was *also* missing was **wrong** — that check had been run
against `config/registry.example.yaml`, not against the live gitignored
`config/registry.yaml`.

**But jobhunt has no receiver.** `pipeline/review_ui.py` is jobhunt's only HTTP
listener, and it serves `/verdict`, `/recheck`, `/override` and `/applied`.
There is no `/chat-callback`. So configuring `callback_url` today does not prove
R3 — it proves **R7**: every tap produces three failed POSTs and then
*"⚠️ couldn't reach jobhunt — use the review UI"* in the thread.

**What was actually done, and where.** On 2026-07-30, at the user's direction,
`job-hunter` was given `callback_url`, `allowed_users` and `unreachable_message`
in the **local development registry only** (`config/registry.yaml`, which is
gitignored) — deliberately, to exercise R7, the one link in the chain that had
never actually happened. **The appserver deployment at `/srv/chat-gateway/` does
not have this configuration.** Read §9.3 as the configuration jobhunt's
integration *requires*, and the paragraph above as a dated observation of a dev
box — not as a description of production.

**The remaining work is jobhunt's, and it is small.** Add a `/chat-callback`
endpoint to `review_ui.py` that (a) returns 2xx immediately, (b) keys on
`dedupe_key`, and (c) routes `action.id` + `action.params` into the existing
verdict write-path. When it lands, nothing in the gateway's configuration
changes — the same `callback_url` starts succeeding, and the delivery log flips
from `failed` to `forwarded`.

---

## 11. What is verified against Google, and what is not

Per link in jobhunt's chain:

| Link | Status |
|---|---|
| the interaction **parse** | ⚠ SHAPE-VERIFIED — real captured bytes, replayed offline (both runtimes; classic `CARD_CLICKED` from both trigger kinds) |
| the **inbound pull** (`PubSubPuller`) | ✅ verified live 2026-07-30 — `pull()` returned real events through the gateway's own class, and `acknowledge()` was proven *selectively*: one id acked while two others kept redelivering, which is what makes `dedupe_key` trustworthy |
| the **in-thread reply** (`ChatApiAdapter.send_text`) | ✅ verified live 2026-07-30, **both branches** — in-thread and top-level, the in-thread one in the JobHunt space itself. This is R4's refusal and R7's failure notice |
| the **outbound webhook** (tier 1) | ✅ verified live 2026-07-29, re-confirmed 2026-07-30 — text and Cards v2, rendering confirmed |
| an interaction reaching **a jobhunt callback** | ❌ still never happened — §10 |

For everything that is still unexercised against Google, read **`CLAUDE.md`'s
verification ledger**. That is the single authoritative list and this file does
**not** keep a copy: every restatement of it in this repo has drifted within two
PRs, and the tempting one-line summary ("the adapters' error branches") is
demonstrably false — it omits success-path rows.

Offline, the guarantees above are pinned by deterministic tests in
`tests/test_callbacks.py`: authorized tap → whole-event callback with dedupe key
and structured reason; unauthorized tap → in-thread refusal only, never
forwarded; callback down → visible in-thread failure after the retries;
opted-out tenants receive nothing and cannot even configure a callback;
registry directory mode, one file per tenant.
