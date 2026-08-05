# Consumer contract — jobhunt (two-way tenant)

Recorded 2026-07-24. jobhunt is the gateway's second tenant and the first
two-way one: pre-rendered job cards out, button interactions back. Service-
level integration only (R8) — appserver-local HTTP + one tenant config file;
no code imports either direction; jobhunt keeps working (tier-1 webhook +
its review UI) if the gateway is down or never ships (R9).

> **Building against this?** [`jobhunt-handoff.md`](jobhunt-handoff.md) is the
> companion **handoff** doc — the gateway's answer back to jobhunt's R1–R9, with
> the card convention, the required registry configuration, and the state of
> each guarantee. This file stays the contract.

## Requirements → implementation

| R | Requirement | Where |
|---|---|---|
| R1 | Multi-tenant dumb pipe; one config file per tenant | registry directory mode (`load_registry` on a `tenants.d/`); per-app `callback_url` |
| R2 | Rendering stays with the producer; validate + size-limit only | envelope passes `cardsV2` through verbatim; 30KB cards cap; gateway never rewrites |
| R3 | Interactions forwarded whole with idempotency key | `InboundReply`: `action.id` + merged `params`, sender identity, space, `message_id`, `thread_*`, `dedupe_key` = Pub/Sub message id (at-least-once ⇒ tenant callbacks must be idempotent — buttons should carry self-contained tokens) |
| R4 | AuthZ at the gateway | events arrive only via our private topic/subscription (only Chat's publisher is granted); per-tenant `allowed_users` email allowlist — anyone else gets an in-thread "⛔ Not authorized" and is **never forwarded**. Tenant re-enforces downstream (its own verdict write-path) |
| R5 | Digest / instant lane / retro / health | all producer-side; instant lane = `POST /v1/messages` (synchronous) or `/v1/notify` |
| R6 | Structured reject reason | in-card `selectionInput` — the chosen value arrives merged into `action.params` (e.g. `reject_reason`), capture-verified on both runtimes. Default to *widgets for input, one button to submit*: it is portable across runtimes and yields **one event per user decision**. On classic (the runtime we run) a widget's `onChangeAction` is **itself** an interaction trigger and fires on change as well — a card carrying both fires twice. True modal dialogs are **believed** impossible over Pub/Sub transport (they need a synchronous HTTP interaction endpoint) — **doc-derived inference, never tested on either runtime**, not an observation. Full wording: [ADR-0001 §7](../architecture/decisions/2026-07-29-tier2-interaction-model.md) |
| R7 | Fail loudly in-thread | callback retries are short — three attempts at **0s / 3s / 10s** (`BACKOFF_S = (0, 3, 7)` is a sequence of *gaps*, not attempt times). What an operator observes is later and **variable**: attempts fire on subscriber poll ticks, and a poll cycle costs the attempt's own duration *plus* the 5s interval. **`0s / 5s / 15s` is a fast-failure illustration, not a schedule — and it is optimistic for the unreachable-callback case this requirement is about**, because an unreachable host times out rather than refusing (measured 0s/15s/30s, notice at ~40s). Worked figures: [handoff §7](jobhunt-handoff.md). On exhaustion the gateway posts the tenant's `unreachable_message` into the thread and logs `failed`. Tier-1-only deployments can't post the notice (no Chat app) — logged as `failed-silent`; full R7 requires tier 2 |
| R8/R9 | Separability / migration | HTTP-only; tier-1 webhook identity works today; adopting tier 2 changes transport + adds the callback, nothing else |

> **Runtime note (updated 2026-07-29, after a real capture).** Interactions were
> designed to normalize identically under both Google runtimes: under the
> Workspace Add-ons runtime the action id arrives as the reserved
> `__action_method_name__` parameter and is lifted into `action.id`. A real card
> tap has now been captured (`tests/fixtures/addon-buttonclicked-event.json`)
> and it did **not** work that way — the runtime sent no such parameter and
> `action.id` came through **empty**. `action.params` was correct, including a
> selection widget's value merged in from `commonEventObject.formInputs`.
>
> **R3 and R4 are therefore still NOT verified**, and the reason was a known
> defect rather than an untested path: R3 requires the whole interaction plus an
> idempotency key, and the action identity was missing.
>
> **Resolved 2026-07-29 (CG-10, ADR-0001 D2/D4) — with an action required of
> jobhunt.** Action identity now rides in a gateway-reserved card parameter,
> `__cg_action__`, which the gateway lifts into `action.id` and pops out of
> `params`. **jobhunt's cards must set it**; a card that does not will deliver
> with `action.id: null` (never `""`), be counted at
> `/healthz → subscriber.interactions_without_action_id`, and still be
> forwarded — so a missing identity is visible and rejectable rather than
> silently plausible. `action.id_source` reports `"cg_param"` | `"google"` |
> `null`.
>
> **Card `parameters` is an ARRAY of `{key, value}` in the card you send** — on
> every runtime, no exceptions. Write the array; a card built with a map is not
> valid Cards v2 and you find out at render or tap time, in front of a user.
>
> The **inbound** shape is a property of the *runtime*, not of the direction:
> classic delivers an **array** under `action.parameters` (symmetric with what
> you sent), the add-ons runtime delivers a **map** under
> `commonEventObject.parameters`. This line previously said "a map in the event
> you receive" full stop, which is wrong and would have had you reading a raw
> classic event and concluding the gateway was broken. You should not need any
> of it — the gateway normalizes both into `action.params` — see the runtime
> table in `docs/integration-guide.md`.
>
> **Fetch the wiring, do not hardcode it** (CG-13, ADR-0001 D3).
> `GET /v1/identities` returns `interaction.routing_target` (what goes in a
> card's `onClick.action.function`) and `interaction.action_key`. Because
> identity always rides in the key and the function slot always holds a
> gateway-published constant, the same jobhunt card works under every
> deployment model the gateway could move to — a migration costs jobhunt
> **zero card changes**. Hardcode the topic path and you have signed up to
> re-render every card the day it moves.
>
> R3/R4 remain **live-unverified end to end** — but the gap is now narrower and
> worth stating precisely, because "unverified" was covering two very different
> things:
>
> | Link in the chain | Status |
> |---|---|
> | the interaction parse | ⚠ SHAPE-VERIFIED on real captured bytes |
> | **the reply transport** (`ChatApiAdapter.send_text`) | ✅ **verified live 2026-07-30, both branches** — in-thread and top-level. This is R4's authorization refusal and R7's failure notice: the gateway can now demonstrably tell a user their tap was refused or did not land (CG-5). |
> | **the inbound pull** (`PubSubPuller`) | ✅ **verified live 2026-07-30** — `pull()` returned real events through our own class, and `acknowledge()` was proven *selectively*: one id acked while two others kept redelivering, which is what makes the dedupe key trustworthy (CG-24). |
> | **an interaction reaching a jobhunt callback** | ❌ still never happened. No `callback_url` is configured for `job-hunter`, so nothing has traversed the full chain. |
>
> So the *last* link is the outstanding one, and it is outstanding for a
> configuration reason rather than a code one.

> **⚠ R3 deviation — one field is no longer forwarded whole (2026-07-29).**
> R3 says events forward *whole*. As of this date exactly one field is blanked
> to `<redacted-by-gateway>` before an event is audited or POSTed to your
> callback: Google's `configCompleteRedirectUri` (add-ons runtime) and its
> classic-runtime spelling `configCompleteRedirectUrl`. Everything else in
> `raw` is untouched, and no normalized field is affected.
>
> Why: it is an unguessable, per-message, state-changing capability URL.
> Visiting it makes the user's **private message public in the space** and
> re-delivers it. Forwarding it would hand every opted-in tenant that ability,
> which hard rule #2's "never log or echo them" covers in spirit even though
> Google's docs never call it a credential. This is a deliberate, documented,
> single-field exception taken on security grounds — recorded here rather than
> left as an undisclosed gap between the contract and the implementation.

## Tenant config (one file in the registry directory)

```yaml
identities:
  jobhunt:
    display: "Job Hunter"
    mode: app                    # tier 2 (webhook mode until then)
    space: "spaces/XXXX"
apps:
  jobhunt:
    key_env: CHAT_GATEWAY_API_KEY__JOBHUNT
    identities: [jobhunt]
    allow_inbound: true
    callback_url: "http://127.0.0.1:8710/chat-callback"   # appserver-local
    allowed_users: [mark@mackelprang.com]                 # exactly one (R4)
    unreachable_message: "⚠️ couldn't reach jobhunt — use the review UI"
```

## Retention of your inbound records (CG-68, 2026-08-02)

In `config/registry.example.yaml`, jobhunt is the **only** tenant with records
in the gateway's inbound audit directory — the only one with
`allow_inbound: true` — so this amendment is addressed to you before anyone
else. ⚠ **Scoped to the example registry deliberately.** The live registry is
gitignored and cannot be read from a PR; `CLAUDE.md` records that CG-61's
`allow_inbound: false` for `aiteam-harness` landed in the **example** file and
that the live edit was a separate recorded operator action. ~~with the key absent
from the live file and the default doing the work until then. So a second tenant
may still have records in that directory on the running deployment.~~
✅ **That operator edit landed 2026-08-03** (corrected 2026-08-05, CG-79):
`aiteam-harness` now carries an **explicit** `allow_inbound: false` in the live
file, so **you are once again the only tenant whose events are being written to
that directory.** ⚠ **The conclusion this paragraph drew still half-holds, and
the surviving half is the one that affects your data:** records that tenant
generated **before** 2026-08-03 can still be sitting in that directory, and they
age out on the same global 30-day window described below — nothing was
retroactively deleted. What changed is the *reason* — the default is no longer
doing the work — not the possibility that older files exist. Nothing
about the window below is tenant-specific — it is global (ADR-0002 D6) — so
this changes who else should read this section, not what it says.

Every event routed to you is appended to `<CHAT_GATEWAY_INBOX_DIR>/<app-id>-<date>.jsonl`
before anything is queued, and that file holds the tapper's `text`,
`sender_email` and the **whole** `raw` Chat event. It used to be kept forever;
the integration guide said *"never pruned"*. It is now **kept for 30 days after
the day it covers and deleted on the 31st** (`CHAT_GATEWAY_INBOX_RETENTION_DAYS`,
`0` disables), and the deletion is an `unlink` of the whole day-file — never a
rewrite, and nothing ever opens it to decide. The off-by-one is stated precisely
because this page stated it wrong first (*"deleted 30 days after the day it
covers"*): the test is `(today - file_date).days <= 30 → keep`, so a file dated
**D** survives through **D+30** and goes on **D+31** — plus up to six hours,
since the sweep runs on an interval rather than at midnight.

**What this does and does not change for you:**

- **Nothing about delivery.** The audit trail was never a queue and never
  re-pollable — it records what ARRIVED, never what LEFT, so no decision
  history of yours was ever reconstructible from it. If you need your own
  record of a tap beyond 30 days, keep it on your side; that was already true
  when the file was permanent.
- **The one artifact that IS a recovery record is still never pruned.** A
  journalled reply that no longer validates at boot is preserved in full,
  payload included, under `<CHAT_GATEWAY_STATE_DIR>/quarantine/`. The sweeper
  refuses to start if that directory overlaps the one it sweeps, and skips
  quarantine filenames by name even then — two guards, deliberately, because
  it is the one deletion in this repo with no second copy anywhere.
- **You can watch it.** `/healthz` → `retention.window_days` is the window
  actually in force. `retention.delete_errors` and
  `retention.consecutive_sweep_failures` degrade the endpoint when the policy
  stops being kept — the second is the *consecutive* count, so it clears on
  recovery, while the lifetime `sweep_failures` beside it is history and
  degrades nothing. `retention.thread_alive` / `seconds_since_last_sweep` catch
  the quieter failure, a sweeper that stopped without raising. `files_deleted`
  deliberately degrades nothing at any magnitude.

Reasoning: [ADR-0002](../architecture/decisions/2026-07-31-journalled-message-bodies.md)
§4.1 and §9 Q6.

## Acceptance status

Encoded as deterministic tests (`tests/test_callbacks.py`): authorized tap →
whole-event callback with dedupe key and structured reason; unauthorized tap
→ in-thread refusal only; callback down → visible in-thread failure after
~10s of retries; opted-out tenants receive nothing and can't even configure
a callback. That `~10s` is the forwarder's contract — these tests drive
`process_due()` on a fake clock, so it is what the retry schedule guarantees,
**not** what a user waits in the running gateway. For that, see R7 above.

**The end-to-end run is no longer blocked on unverified seams or missing
infrastructure — it is blocked on one config value.** The Chat app
(classic, "Chat Gateway") and the subscription **exist** on `chat-gateway-gw`, and
as of 2026-07-30 every transport link in the chain is verified live: the inbound
pull and its selective ack, and the in-thread reply both branches. What is
missing is a `callback_url` for `job-hunter` — see the per-link table above.

**Naming note, 2026-07-31.** That app was named **"Agent Comms"** when the
2026-07-29/30 verifications above were run; per a **user statement about the
Google Chat console** (which this repo cannot verify) it is now **deprecated**,
replaced by an app named **"Chat Gateway"** that also participates in three more
spaces. Recorded as a **name change only** — this row deliberately does not
re-price any verification above, because what that would take is
`CLAUDE.md`'s ⚠-flag sign-off, not a docs sweep. Nothing in the gateway reads the
app's display name.

For what is still unverified, read `CLAUDE.md`'s **verification ledger** rather
than a summary here. Deliberately a pointer and not a restatement: the sentence
that used to live in this spot said the residue was "the adapters' error
branches", and that is **false** — it omits `chat_api.send()`'s
`thread.threadKey` branch, which is a success path. That exact shorthand has now
been written and corrected three times in this repo, so this file no longer
keeps its own copy.
