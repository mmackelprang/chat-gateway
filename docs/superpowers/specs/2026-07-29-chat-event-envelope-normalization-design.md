# Design spec — dual-format Chat event envelope normalization

Date: 2026-07-29
Status: **awaiting review**
Author: Planner
Affected hard rules: #1 (transport not schemas), #2 (secrets), #3 (adapters +
LIVE-UNVERIFIED discipline), #5 (honest healthz), #6 (inbound opt-in)

---

## 1. Problem — empirically confirmed, not hypothesized

On 2026-07-29 the first real Google Chat event landed in `chat-gateway-sub`
after console steps 5–7 were completed. The gateway's inbound parser does not
understand it.

Google delivered a **Workspace Add-ons runtime** envelope:

```json
{ "commonEventObject": { "userLocale": "en", "hostApp": "CHAT", "platform": "WEB", "timeZone": {...} },
  "chat": { "user": {...}, "eventTime": "2026-07-29T12:55:58.782511Z",
            "messagePayload": { "space": {...}, "message": {...},
                                "configCompleteRedirectUri": "...token=<live>..." } } }
```

`normalize_event()` in `src/chat_gateway/adapters/pubsub.py` (line 101) was
written off-site against the **classic Chat app** format — top-level `type`,
`space`, `message`, `user`. Feeding the real payload through the real function
returned an empty husk:

```json
{"event_type":"MESSAGE","space":"","thread_key":null,"thread_name":null,"message_id":null,
 "sender_display":"","sender_email":null,"text":"","action":null,"dedupe_key":null}
```

### Three defects, severity-ordered

| # | Defect | Code | Consequence |
|---|--------|------|-------------|
| D1 | **Silent failure.** `event.get("type", "MESSAGE")` turns a totally-unparsed event into a plausible-looking empty MESSAGE. | `pubsub.py:116` | Violates the project's fail-loudly ethos. The same class of bug (a system reporting OK while capturing nothing) is why hard rule #5 exists. |
| D2 | **Inbound routing dead.** `space` normalizes to `""`. | `pubsub.py:106` | `registry.apps_for_space("")` returns `[]` → every real event is audited under `_unrouted`. No consumer ever receives anything. |
| D3 | **`CARD_CLICKED` broken.** The interaction branch tests top-level `type`/`action`; neither exists in the add-ons envelope. | `pubsub.py:108` | jobhunt's entire Approve/Reject path (R3/R4, `docs/consumers/jobhunt.md`) is non-functional under this runtime. |

Note on the reproduction: the husk showed `dedupe_key: null` only because the
replay bypassed `pull()`, which injects `_pubsub_message_id`. That is a test
artifact, **not** a fourth defect.

---

## 2. Goals / non-goals

**Goals**

- G1. Parse **both** envelope formats. Not add-on-specific, not classic-specific.
- G2. Normalize both to the **one existing internal shape** so downstream code
  (`forwarder.py`, `inbox.py`, `registry.py`, `service.py` routing) is untouched.
- G3. Fail **loudly and visibly** on an envelope we do not recognize — never
  silently default to MESSAGE.
- G4. Handle interaction events in both formats, with honest flagging of the
  add-on interaction path, which we have **not** captured live.
- G5. Preserve dedupe-key behaviour (`_pubsub_message_id` → `dedupe_key`).
- G6. Lock the real captured payload into the test suite without committing a
  secret.

**Non-goals**

- Not switching runtimes. Both stay supported indefinitely.
- Not interpreting any consumer's domain semantics (hard rule #1).
- Not clearing any ⚠ LIVE-UNVERIFIED flag that this work does not earn (§8).
- Not changing which tenants may receive inbound (hard rule #6 — §3.1).

---

## 3. Framing: this is a *runtime* distinction, and it is transport's job

The two formats are **not** a "Workspace user vs consumer user" distinction.
They are which runtime the Chat app is deployed under:

| Runtime | Envelope |
|---|---|
| **Google Workspace Add-ons** | `commonEventObject` + `chat.<something>Payload` |
| **Classic Chat app** | flat `type` / `space` / `message` / `user` |

Both will coexist for years while Google migrates. chat-gateway is
multi-tenant transport; different consumers may end up deployed under
different runtimes, and the gateway must not care which.

### 3.1 Hard-rule #1 compliance — stated explicitly

Rule #1 forbids the gateway owning or interpreting **an application's message
schema**. It does not forbid recognizing **Google's own wire formats**.
Normalizing a transport envelope is precisely transport's job — the same job
the gateway already does when it maps `message.thread.name` to `thread_name`.

The test for whether this fix has leaked app-domain knowledge:

> Does any new branch key off a *consumer's* vocabulary (a jobhunt verdict, an
> aitrader severity, a card id one app happens to use)?

The answer must stay **no**. What lands in `action.params` is passed through
verbatim as opaque key/value data, exactly as it is today. The gateway learns
Google's field names, never a tenant's.

### 3.2 Hard-rule #6 compliance

This change touches only *parsing*, never *authorization*. Routing continues
to run through `registry.apps_for_space()` → `allow_inbound` → `allowed_users`
in `dispatch()`, unmodified. `aitrader` (`allow_inbound: false`) remains
locked out of every inbound path. The new unparseable-event path (§4.3)
routes to the reserved `_unrouted` audit id **only**, and can never reach a
registered app — that must be asserted by a test, not merely intended.

---

## 4. Design

### 4.1 Shape-detecting normalizer

Replace the single-format `normalize_event()` with: a detector, two
format-specific extractors, and a thin public dispatcher that keeps the exact
same name and return contract.

```
normalize_event(event)
  ├─ detect_envelope(event) -> "addon" | "classic" | raise UnrecognizedEventError
  ├─ _normalize_addon(event)    ─┐
  └─ _normalize_classic(event)  ─┴─> identical dict shape
```

Detection is **structural**, in this order:

1. `event.get("_undecodable")` is truthy → `UnrecognizedEventError`
   (the base64/JSON decode already failed upstream in `pull()`; §4.4).
2. `event["chat"]` is a dict → **addon**. (The classic format has no `chat`
   key; the add-ons format always has one.)
3. `event["type"]` is a non-empty string → **classic**.
4. anything else → `UnrecognizedEventError`.

Ordering matters: addon is checked first because it is the more specific
shape. A flat dict carrying `space`/`message` but **no** `type` is treated as
unrecognized rather than guessed — that guess is exactly defect D1.

### 4.2 Add-on payload types — three outcomes, not two

Inside `chat`, the event kind is carried by *which* `*Payload` key is
present. There is **no** `chat.type` discriminator — confirmed against
Google's event-object reference, which models the payload as a proto union
("payload can be only one of the following") with exactly six members, and
against the migration guide, whose mapping table records classic `type` as
"N/A — the event type can be deduced from the trigger."

Alongside the payload union, `chat` also carries the non-payload fields
`user`, `space`, and `eventTime`.

The parser therefore uses a mapping table plus a generic fallback:

| `chat.<key>` | normalized `event_type` |
|---|---|
| `messagePayload` | `MESSAGE` |
| `buttonClickedPayload` | `CARD_CLICKED` |
| `addedToSpacePayload` | `ADDED_TO_SPACE` |
| `removedFromSpacePayload` | `REMOVED_FROM_SPACE` |
| `appCommandPayload` | `APP_COMMAND` |
| `widgetUpdatedPayload` | `WIDGET_UPDATED` |
| *any other* `*Payload` | derived: `fooBarPayload` → `FOO_BAR` |

This gives three outcomes rather than a binary parse/fail:

1. **recognized envelope + known payload** → normalize.
2. **recognized envelope + unknown payload** → normalize *generically*
   (every add-on payload observed carries `space` and usually `message`), with
   a derived `event_type`. Honest, never defaulted to `MESSAGE`, and Google
   adding a payload type does not break routing.
3. **unrecognized envelope** → raise (§4.3).

An add-ons envelope with a `chat` object containing **no** `*Payload` key at
all is outcome 3 — there is nothing to route on.

### 4.3 Fail loudly *without* wedging the subscription

This is the subtlest decision in the design, and it is where a naive
"just raise" would create a worse bug than the one being fixed.

If `normalize_event()` raises and the exception escapes `poll_once()`, the
batch's ack ids are never sent, Pub/Sub redelivers, `SubscriberLoop._run()`
catches and retries forever — a **poison-pill redelivery loop** that stalls
every well-formed event behind it. That trades a silent failure for a total
inbound outage.

Chosen behaviour — loud at the seam, contained at the loop:

- `normalize_event()` **raises** `UnrecognizedEventError`. Loud, testable, and
  the correct contract for a library function.
- `dispatch()` catches it in exactly one place, and records an explicit
  marker into the `_unrouted` inbox: `event_type="UNPARSEABLE"`, empty
  `space`, the raw event preserved. It returns `[UNROUTED]`. It never returns
  a registered app id for an unparseable event.
- `SubscriberLoop.poll_once()` increments `unparseable_seen` and **still
  acks**, so the subscription drains.
- `/healthz` reports `subscriber.unparseable_seen`.

"Loud" therefore means: a distinct `UNPARSEABLE` event type in the JSONL
audit trail, a stderr line, and a non-zero counter on `/healthz` — all three,
permanently. It does **not** mean an empty MESSAGE, and it does **not** mean a
stalled subscription. This satisfies hard rule #5's requirement that health
reflect reality: a gateway silently discarding events would now show it.

### 4.4 Consistency with the existing `_undecodable` path

`pull()` (line 88) already emits `{"_undecodable": True}` when base64/JSON
decoding fails, and today that husk flows into the same silent-empty-MESSAGE
path as everything else. Folding it into rule 1 of the detector unifies the
two: **bytes we could not decode** and **structure we do not recognize** both
become `UNPARSEABLE`, counted and audited identically. One concept, one
counter, one code path.

### 4.5 Interaction (`CARD_CLICKED`) extraction

**Classic** (unchanged, already covered by `tests/test_callbacks.py`):
`action.actionMethodName` / `action.function`; `action.parameters` as a
**list** of `{"key","value"}`; form inputs at
`common.formInputs.<name>.stringInputs.value` (a list).

**Add-ons** — the interaction envelope is `chat.buttonClickedPayload`
(sub-fields `message`, `space`, `isDialogEvent`, `dialogEventType`), with the
action metadata carried on `commonEventObject`.

> **A documentation check overturned the obvious guess here, and it is worth
> recording why.** The natural assumption — mirroring the classic
> `action.actionMethodName` — is that the add-ons runtime exposes
> `commonEventObject.invokedFunction`. **It does not.** Google's add-ons
> release notes (2025-05-12) state that `invoked_function` "is no longer part
> of the Common event object" for add-ons extending Chat. The field still
> exists *classic-side*, which makes it a near-perfect trap: a parser written
> from classic samples looks right and silently yields `action.id == ""`.

Confirmed add-on mapping (Google docs, high confidence — see the migration
guide's legacy→add-on mapping table):

| normalized | add-ons source |
|---|---|
| `action.id` | `commonEventObject.parameters["__action_method_name__"]` — Google injects the original `action.function` under this reserved key |
| `action.params` | the rest of `commonEventObject.parameters`, a flat **string→string map** (the list-of-`{key,value}` form is classic-only) |
| form values | `commonEventObject.formInputs.<name>.stringInputs.value` (a **list**) |

Two parser traps documented and deliberately avoided:

- The `[""]` extra nesting (`formInputs.<name>[""].stringInputs.value`) is
  **Apps Script only**. Over Pub/Sub we get the flat form. Do not code for it.
- Classic `CARD_CLICKED` uses `common.formInputs`, but classic `SUBMIT_FORM`
  (app home) uses `commonEventObject.formInputs` — the *classic* envelope is
  not internally uniform either. The classic extractor therefore checks both
  parents, and also merges `common.parameters` (a map that coexists with the
  `action.parameters` list).

**Round-trip parity is the acceptance criterion.** `__action_method_name__` is
popped out into `action.id` rather than left in `params`, so that the same
card, tapped under either runtime, produces the **same** `InboundReply`.
Consumers must never need to know which runtime they are behind — that is the
entire point of doing this in the gateway.

> ⚠ **Still not capture-verified.** The mapping above is now
> documentation-*confirmed* rather than guessed, but we have a real MESSAGE
> event and **no** real interaction event — no card button has ever been
> tapped against this deployment. The implementation stays deliberately
> tolerant (accept `parameters` as map **or** list; fall back to
> `invokedFunction` and to payload-local action fields if the reserved key is
> absent), carries a ⚠ LIVE-UNVERIFIED flag naming *this specific path*, and
> is closed out by a real capture (work item **CG-3**, §9).

Because the classic and add-on form-input shapes are nested identically below
their differing parents, one shared `_merge_form_inputs(container, params)`
helper serves both.

**Out of scope, but named so it is a known gap rather than a silent one:**
`appCommandPayload.appCommandMetadata.appCommandId` (slash commands) is not
surfaced into `action`. It normalizes to `event_type == "APP_COMMAND"` with
the metadata reachable via `raw`. Surfacing slash commands is a separate
feature decision, not a bug fix.

### 4.6 Normalized output shape

Unchanged keys — this is what keeps blast radius small:

```
event_type, space, thread_key, thread_name, message_id,
sender_display, sender_email, text, action, dedupe_key
```

Plus **one additive field** (see decision DEC-3): `envelope_format` —
`"classic"` | `"addon"` | `"unparseable"`.

Add-on field mapping:

| normalized | add-ons source |
|---|---|
| `space` | `chat.<payload>.space.name`, falling back to `chat.space.name`, then `chat.<payload>.message.space.name`. Three sources because `widgetUpdatedPayload` carries **only** `space`, while `chat.space` is a documented non-payload sibling — the chain must not assume `message` exists |
| `message_id` | `chat.<payload>.message.name` |
| `thread_name` | `chat.<payload>.message.thread.name` |
| `thread_key` | `chat.<payload>.message.thread.threadKey` (absent in the captured sample — Google echoes it only when the sender set one; `None` is correct) |
| `text` | `chat.<payload>.message.text` |
| `sender_display` | `chat.user.displayName`, falling back to `...message.sender.displayName` |
| `sender_email` | `chat.user.email`, falling back to `...message.sender.email` |
| `dedupe_key` | `event._pubsub_message_id` (unchanged, format-independent) |

`thread_key` deserving a note: the captured payload's `thread` object contains
only `name` and `retentionSettings`. Threading for gateway-sent messages is
keyed by `thread_key`, so consumers relying on it for add-on-runtime inbound
must fall back to `thread_name`. That is a real behavioural difference between
the runtimes and belongs in the integration guide, not in a workaround.

---

## 5. Decisions (with alternatives considered)

**DEC-1 — Where does dual-format knowledge live?**
Chosen: entirely inside `adapters/pubsub.py`.
Rejected: a shared `envelope.py` normalizer (would put Google wire-format
knowledge in the one channel-agnostic module — hard rule #3 says Google-facing
code lives only in `adapters/`); a new `adapters/chat_events.py` module
(cleaner in isolation, but splits one ~80-line concern across two files and
churns imports in tests for no functional gain — revisit only if a second
channel adapter appears).

**DEC-2 — Fail-loudly mechanism.**
Chosen: raise at the normalizer, catch once in `dispatch()`, audit as
`UNPARSEABLE`, still ack, surface a counter.
Rejected: (a) let the exception propagate — poison-pill redelivery loop,
strictly worse than the bug being fixed; (b) return a sentinel dict without
raising — callers can ignore a dict, which is how D1 happened in the first
place; (c) drop the event — unacceptable, the audit trail is the project's
"nothing is ever silently lost" guarantee.

**DEC-3 — Add `envelope_format` to `InboundReply`?**
Chosen: **yes**, additive with a default.
Rationale: it is transport metadata (which Google runtime produced this),
not app-domain data, so rule #1 is satisfied; it makes the JSONL audit trail
self-describing during exactly the migration period this spec exists for; and
it is backward-compatible for the single callback tenant (jobhunt), which
ignores unknown fields.
Rejected: leave it out and let consumers introspect `raw` — workable but
pushes wire-format detection into every tenant, which is the opposite of what
a gateway is for.
**This one is worth an explicit user yes/no**, because it changes the shared
envelope, and `envelope.py` is described in CLAUDE.md as "the only shared
shape".

**DEC-4 — Strictness on classic detection.**
Chosen: classic requires a non-empty string `type`. A flat dict with
`space`/`message` but no `type` is unparseable.
Rationale: leniency here reintroduces D1. All existing test fixtures
(`test_adapters.CHAT_EVENT`, `test_callbacks.CARD_CLICK`) carry `type`, so
this is safe against the current suite — verified by reading them, not assumed.

**DEC-5 — Fixture anonymization.**
Chosen: **anonymize**. `github.com/mmackelprang/chat-gateway` is a **public**
repo (verified via `gh repo view`).
Scrub the token (already done), and additionally replace: the numeric user id
`users/1129…`, the `avatarUrl` (it embeds an opaque profile token),
`domainId`, and the space/message/thread ids. Keep the email as a clearly
synthetic `agent-user@example.com`.
Nuance for honesty: `mark@mackelprang.com` is *already* published in
`docs/integration-guide.md:86` and `docs/consumers/jobhunt.md:36`, so the email
is not a new disclosure — but a stable Google user id, a profile-photo token
and a real domain id are, and none of them are needed for the test to be
meaningful. **Structure must stay byte-for-byte faithful**; only leaf values
change. That is what the fixture is for.

**DEC-6 — Scrub enforcement is a test, not a step.**
A path-targeted scrub already failed once today and briefly wrote a live token
to disk. A checklist item repeats that failure mode. Chosen: a committed test
that walks **every** fixture recursively — all keys and all string values —
rejecting anything matching `token`, `redirectUri`, `secret`, `key=`,
`Bearer `, or a private-key header. Permanent, CI-enforced, no path guessing.

**DEC-7 — Redact `configCompleteRedirectUri` from `raw` at runtime.**
Surfaced by the research pass; **not** part of the original bug report, but
caused by it — we are about to start successfully parsing a payload we have
never successfully parsed before, and `raw` rides along everywhere.

The exposure: `InboundReply.raw` is (a) written to the JSONL audit trail on
disk by `inbox.py`, and (b) POSTed **whole** to every opted-in tenant callback
by `forwarder.py` (jobhunt R3). Under the add-ons runtime, `raw` contains
`chat.messagePayload.configCompleteRedirectUri`, whose live token we had to
scrub from the fixture today.

Why it matters even though Google's docs never call it a credential: per
Google's own description, redirecting to that URL causes Chat to erase the
user's prompt, **convert the original private message to public in the space**,
and re-deliver it. It is an unguessable, per-message, state-changing URL —
functionally a bearer capability. Hard rule #2's spirit ("never log or echo
them") covers it.

Chosen: redact the value to `"<redacted-by-gateway>"` in a **copy** of `raw`
before it is audited or forwarded, covering both spellings — add-on
`configCompleteRedirectUri` **and** classic `configCompleteRedirectUrl`
(Google genuinely uses `Uri` in one format and `Url` in the other; the parser
must guard both).
Rule #1 check: this redacts a **Google-owned transport field by exact name**,
not anything an application put there. No app-domain knowledge leaks.
Rejected: forward it untouched — literally hands every tenant a capability to
publicise a user's private message; leave it on disk only — the callback path
is the worse of the two exposures.
**Tension to flag for the reviewer:** jobhunt R3 says events forward
*whole*. This is a deliberate, single-field, documented exception. It needs an
explicit yes, and if declined, the task is dropped without affecting the rest
of CG-1.

---

## 6. Blast radius

**Changed**

| File | Change |
|---|---|
| `src/chat_gateway/adapters/pubsub.py` | detector + two extractors + `UnrecognizedEventError`; `dispatch()` gains one try/except; `SubscriberLoop` gains `unparseable_seen` |
| `src/chat_gateway/envelope.py` | **one** additive optional field on `InboundReply` (DEC-3) |
| `src/chat_gateway/service.py` | **one** key added to the `healthz` subscriber block |
| `tests/test_adapters.py` | existing `test_normalize_event` updated for the new key; new dual-format tests |
| `tests/fixtures/*.json` | new — real add-on capture + classic counterpart |
| `tests/test_fixtures_scrubbed.py` | new — recursive secret scan |
| `docs/integration-guide.md`, `docs/consumers/jobhunt.md`, `CLAUDE.md` | doc updates |

**Deliberately untouched**

`forwarder.py`, `inbox.py`, `registry.py`, `auth.py`, `client.py`,
`delivery.py`, `heartbeat.py`, `notifications.py`, `adapters/webhook.py`,
`adapters/chat_api.py`, `__main__.py`, and the whole routing/authorization
path inside `dispatch()`.

`normalize_event` has exactly one production caller (`dispatch`, line 139) and
two test callers — verified by grep, which is what makes this containable.

---

## 7. Test plan

Both formats, symmetric, plus the failure modes:

1. `test_normalize_classic_message` — existing coverage, extended with `envelope_format`.
2. `test_normalize_addon_message_from_real_fixture` — loads the **real captured payload** and asserts every normalized field, including `space == "spaces/…"` (D2) and `text` (the husk's headline symptom).
3. `test_normalize_classic_card_clicked` — list-form params + `common.formInputs`.
4. `test_normalize_addon_card_clicked` — map-form params + `commonEventObject.formInputs`; built from a **synthetic** fixture, explicitly labelled unverified (§4.5).
5. `test_normalize_addon_card_clicked_list_parameters` — the map-or-list tolerance.
6. `test_unrecognized_envelope_raises` — `{}`, `{"foo": 1}`, `{"space": {...}}` with no `type`, `{"chat": {}}` → all raise.
7. `test_undecodable_event_raises` — the `_undecodable` husk raises too (§4.4).
8. `test_dispatch_unparseable_audits_and_never_routes_to_a_tenant` — lands in `_unrouted` as `UNPARSEABLE`; asserts no registered app id is returned. **This is the hard-rule-#6 guard.**
9. `test_poll_once_acks_unparseable_events` — the anti-poison-pill test: a batch of [good, garbage, good] acks all three, dispatches both good ones, and increments `unparseable_seen`.
10. `test_addon_unknown_payload_type_is_named_not_defaulted` — an invented `chat.somethingNewPayload` normalizes with a derived type, never `MESSAGE`.
11. `test_dedupe_key_survives_both_formats` — `_pubsub_message_id` → `dedupe_key` (G5).
12. `test_fixtures_contain_no_secrets` — the recursive scrub guard (DEC-6).
13. `test_addon_event_routes_to_owning_app` — end-to-end through `dispatch()` with a registry whose identity is homed in the fixture's space: proves D2 is actually fixed at the routing layer, not just the parsing layer.
14. `test_action_id_parity_across_formats` — the same logical button tap in both formats yields the same `action.id` and the same `action.params`, and `__action_method_name__` does **not** leak into `params` (§4.5 round-trip parity).
15. `test_config_complete_redirect_uri_is_redacted` — DEC-7, both spellings, asserting the audited/forwarded `raw` no longer carries the value while the rest of `raw` survives intact.

Current suite is 37 passing; all must stay green.

---

## 8. ⚠ LIVE-UNVERIFIED accounting — what this work may and may not clear

Rule #3 says flags clear only on real round-trips. Honest state after today:

| Seam | Status | May this work clear it? |
|---|---|---|
| Chat → topic → subscription **publish** | Real evidence: an event arrived. | **Partially.** We may state that events do reach `chat-gateway-sub`. |
| `chat-api-push@system.gserviceaccount.com` publisher grant | **Both** that principal and the add-ons service agent are now bound. | **No.** We cannot prove which one delivered. The correlation is strong but circumstantial and must be written down as such. |
| `PubSubPuller.pull()` / `.acknowledge()` | The live pull used an **ad-hoc client**, not our class. | **No.** Our class is still unexercised. |
| `normalize_event` — add-on **MESSAGE** | Will be verified against real captured bytes, offline. | **Not a live-round-trip clear.** See below. |
| `normalize_event` — add-on **CARD_CLICKED** | No capture exists. | **No.** CG-3 exists to clear it. |
| Chat API **send** | Untouched. | No. |
| Webhook **send** | Untouched. | No. |

**Proposed new flag vocabulary — needs user sign-off.** Replaying real
captured bytes offline is genuinely stronger than "written off-site against
docs" but genuinely weaker than a live round-trip. Neither existing state
describes it. Proposal:

```
⚠ SHAPE-VERIFIED 2026-07-29 (real captured payload replayed offline);
  LIVE-UNVERIFIED (no round-trip through PubSubPuller)
```

Introducing a second flag word silently would undercut rule #3's discipline,
so it is raised here as an explicit decision rather than assumed. If declined,
the fallback is to keep the plain ⚠ LIVE-UNVERIFIED flag and describe the
capture evidence in prose.

**Builder must not remove any ⚠ flag other than as authorized above.**

---

## 9. Work items and why they split this way

| ID | Scope | Priority |
|---|---|---|
| **CG-1** | Dual-format normalizer, fail-loudly, fixtures, tests, docs | P0 |
| **CG-2** | IaC add-ons service agent grant + setup-doc failure signature | P1 |
| **CG-3** | Live interaction capture → verify/correct the add-on CARD_CLICKED mapping | blocked on a human |

**Why CG-2 is not folded into CG-1.** Different language, different files,
and — decisively — a **different risk profile**. CG-1 is pure Python, fully
offline-testable, and gated by a green suite. CG-2 touches cloud IAM and
cannot be unit-tested at all. Merging them makes the auto-merge gate
("tests pass") ambiguous for the untestable half, and delays the urgent fix
(jobhunt's interaction path is dead today) behind infra hygiene that only
affects the *next* fresh deployment. They are causally related but not
code-coupled.

**Why the IaC change and the doc change *are* folded together (both CG-2).**
They describe the same failure. A reviewer reading the new IAM binding wants
the failure-signature paragraph in the same diff — the doc is the binding's
rationale. Splitting them would land an IaC change with no narrative and a doc
change referencing a binding, in either order. Strong coupling; one PR.

**Why CG-3 is queued although Builder cannot execute it.** It requires a human
tapping a real card button. Leaving it unqueued is how an unverified guess
becomes permanent. It is queued as blocked, with the capture recipe attached.

---

## 10. Open questions for the reviewer

1. **DEC-3** — approve adding `envelope_format` to `InboundReply`?
2. **§8** — approve the `⚠ SHAPE-VERIFIED` flag vocabulary, or keep plain
   LIVE-UNVERIFIED?
3. **DEC-5** — approve full anonymization of the captured fixture (recommended,
   the repo is public), or keep real ids for fidelity?
4. **DEC-7** — approve redacting `configCompleteRedirectUri` / `…Url` from
   forwarded and audited `raw`? This is a deliberate exception to jobhunt R3's
   "forward whole", taken because the field is a capability URL that can make a
   private message public. Recommended **yes**; declining costs nothing else in
   CG-1.
5. Should `UNPARSEABLE` events also raise the `/healthz` status to `degraded`
   once the counter is non-zero? Recommendation: **not in this change** —
   `degraded` currently means "config not resolvable", and one malformed event
   should not flip a deployment's health state permanently. A visible counter
   is the honest signal; a threshold-based alarm is a separate decision.
