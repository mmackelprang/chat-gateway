# chat-gateway → aitrader — consumer handoff

**Read the direction first.**
`D:\prj\aitrader\docs\chat-gateway-requirements.md` (2026-07-26) is what aitrader
sent **to** this gateway. **This file is the gateway's answer back**: what is
implemented, how to integrate against it, and what is verified versus merely
tested offline. Where the two disagree, this file describes the code and the
requirements doc describes the ask.

aitrader consumes the gateway strictly as an HTTP service — no code imports in
either direction, as its contract requires. The gateway receives generic
`severity`/`title`/`body` and never learns trading semantics (gateway hard
rule #1).

Curl cookbook: [`../integration-guide.md`](../integration-guide.md). Full
schemas: `GET /docs` (OpenAPI). Optional stdlib-only client:
`src/chat_gateway/client.py` — vendor the single file if you want it; you do not
need it, every endpoint is one `POST` with a bearer header.

---

## 1. What you get

| | |
|---|---|
| **Tier** | **1 only** — both aitrader identities are `mode: webhook`. No Google Cloud project, no service account, no Pub/Sub. See §9 for why that matters. |
| **Outbound** | `POST /v1/notify` (async, deduped, retried), `POST /v1/heartbeat` (dead-man) |
| **Read-back** | `GET /v1/deliveries`, `GET /v1/heartbeat/{source}`, `GET /healthz` |
| **Inbound** | **none, permanently** — `allow_inbound: false`. See §8. |
| **Auth** | `Authorization: Bearer <your app key>`, one key, revocable by rotating one env var |

---

## 2. Endpoints — the actual contracts

Auth on every `/v1/*` call is `Authorization: Bearer <key>`, compared in constant
time (`auth.py:22-38`). Failures: `401` `{"detail": "missing bearer token"}` /
`"empty bearer token"` / `"unknown API key"`.

### `POST /v1/notify` → **202**

Request (`notifications.py:35-52`):

| Field | Type | Req? | Limit | Notes |
|---|---|---|---|---|
| `severity` | str | **yes** | `alert` \| `warning` \| `info` | anything else → **422** before routing |
| `title` | str | **yes** | 1–200 chars | |
| `body` | str | no | ≤ 4000 | markdown. On `info` only, `len(title) + len(body)` must also be ≤ **3989** — a **422** naming the limit; **see §11** |
| `action` | str | no | ≤ 200 | the "what to do" line; **rendered only on `alert`/`warning`** |
| `dedupe_key` | str | no | ≤ 128 | see §5 |
| `thread_key` | str | no | ≤ 128 | same key → same Chat thread |
| `timestamp` | datetime | no | — | **rendered only on `alert`/`warning`** |
| `source` | str | no | — | **accepted and ignored.** The authenticated app is authoritative — the gateway uses your key-derived app id everywhere (routing, dedupe, the delivery log). Keep sending it if your client already does; it changes nothing. |

Unknown extra fields are ignored, not rejected.

Responses:

```jsonc
{"status": "enqueued", "id": 17, "occurrences": 1}   // accepted for delivery
{"status": "deduped",  "occurrences": 4}             // collapsed into the open window
```

Both are **202** — a `deduped` response is a success, not a rejection. `id` is
the delivery-log entry id and is stable across that message's whole lifecycle.

Other failures: **422** on validation; **503** when your registry has no route
for a valid severity, with an actionable detail — `app 'aitrader' has no notify
route for severity 'warning' (add routes: {severity: identity} to the registry)`.

### `POST /v1/heartbeat` → **200**

`{"check_id": str(1-100), "schedule": str, "grace": str, "tz": str = "America/New_York"}`
→ `{"status": "ok", "check_id": "...", "next_deadline": "<iso8601>"}`.
Bad `schedule`/`grace`/`tz` → **422** with the parser's own message. Registering
and refreshing are the **same call** — see §7.

### `GET /v1/heartbeat/{source}` → **200**

```jsonc
{"source": "aitrader", "checks": [
  {"check_id": "daily-trading-run", "schedule": "weekdays", "grace": "2h",
   "tz": "America/New_York", "last_seen": "<iso>", "status": "ok" | "missed",
   "next_deadline": "<iso>", "last_alerted": "<iso>" | null}]}
```

### `DELETE /v1/heartbeat/{source}/{check_id}` → **200**

`{"status": "deleted", "check_id": "..."}`; **404** `no such check '<id>'`.

Both scoped endpoints enforce own-source-only: `{source}` ≠ your authenticated
app id → **403** `a source may only read its own checks` (or `...delete...`),
`service.py:215-216, 227-228`. `POST /v1/heartbeat` needs no such check — the
source is never client-supplied.

### `GET /v1/deliveries?limit=50` → **200**

`limit` defaults to 50 and is clamped to **[1, 200]**. Always scoped to your own
app; there is no way to read another app's log. See §6.

---

## 3. Severity routing — config, not code

Resolution is `routes[severity]`, falling back to `routes["default"]` if you ever
add one (`registry.py:148-159`), then re-checked against your identity allowlist
(hard rule #4). As committed in `config/registry.example.yaml`:

| `severity` | identity | space |
|---|---|---|
| `alert` | **`aitrader-alerts`** | phone-visible, loud |
| `warning` | **`aitrader-reports`** | quiet |
| `info` | **`aitrader-reports`** | quiet |

Both identities are `mode: webhook`. Two failure modes, deliberately different:
an **unknown** severity is a **422** at model validation and never reaches
routing; a **valid** severity with no route is a **503** naming the fix. A route
pointing at an identity you are not granted is rejected at **registry load**, not
at request time.

---

## 4. Rendering — what actually lands in the space

One function, `notifications.py:55-78`. Emoji are the only "loudness" mechanism —
there is no colour field on a Chat card, so `SEVERITY_EMOJI` is it:
`{"alert": "⚠️🔴", "warning": "🟠", "info": "ℹ️"}`.

**`alert` and `warning` → Cards v2.** Identical structure; only the emoji and the
`[SEVERITY]` word differ.

- header `title`: `⚠️🔴 ALERT` (plus the dedupe counter, §5)
- header `subtitle`: `aitrader: <your title>`
- widgets, in order and only when non-empty: `body` as a `textParagraph`; `action`
  as a `decoratedText` with `topLabel: "What to do"` and the text **bolded**;
  `timestamp` as an italic line
- `cardId` is your `dedupe_key`, falling back to the literal `"notification"`
- if `body`, `action` and `timestamp` are all empty, the card falls back to a
  single paragraph containing the title — a card is never rendered empty

**`info` → plain text, no card.** `ℹ️ [INFO] <title>` plus `\n<body>` — all of it
in the envelope's single 4000-char text field, which is why this severity alone
carries a *combined* title+body limit (§11).

> **Two fields are silently dropped on `info`:** `action` and `timestamp` are
> **not rendered at all** on the plain-text path. If the "what to do" line
> matters, send `warning` — it is a card and costs you nothing but the quiet
> route, which is the same space `info` uses.

---

## 5. Dedupe — one message per window, count on the *next* one

`Deduper`, `notifications.py:81-108`.

- **Key** is `(authenticated app id, dedupe_key)`. **Severity, title and
  `thread_key` are not part of it** — two different alerts sharing one
  `dedupe_key` collapse into one. Choose keys per *condition*, not per message.
- **Window** default **3600s (1h)**, `DEFAULT_DEDUPE_WINDOW_S`. It is a
  **constructor argument with no env var and no registry key** — changing it
  today means a code change or an injected `Deduper`.
- **No `dedupe_key` → always delivered**, never counted, never suppressed.
- The window is **fixed from the last delivery, not sliding**: a suppressed
  message does not push the window out. Fire the same HALT every minute forever
  and you get one message per hour, not silence.

| Event | Delivered? | Logged as |
|---|---|---|
| first occurrence | yes | `enqueued` → … → `delivered` |
| within the window | **no** | `deduped`, detail `occurrence N within window` |
| first one after the window | yes, carrying the count | `enqueued` → … → `delivered` |

The collapsed count rides on the **next delivered** message as
`(×N since last notice)` — in the card header and the fallback text. It is not
back-patched onto the first message, because one-way webhooks cannot edit an
already-posted message (§11). On an `info` notification long enough that the
counter will not fit, it shortens to `(×N)` or is dropped rather than the
message being truncated — see §11, and read the count off the log below.

Every suppressed occurrence is still **logged**, so `GET /v1/deliveries` accounts
for messages you never saw in Chat. That is acceptance criteria 2 and 4 together.
The endpoint serves the last 200 entries per source; the complete record is the
append-only JSONL under `<CHAT_GATEWAY_STATE_DIR>/deliveries/` (§6).

---

## 6. Delivery — accept fast, retry, account for everything

`POST /v1/notify` returns **202 on enqueue** and never blocks on Chat. A
background dispatcher (`delivery.py`) wakes every 1.0s and owns delivery.

**Backoff is `BACKOFF_S = (0, 30, 120, 600, 3600)`** — first attempt immediate,
then 30s, 2m, 10m, 1h. **Five attempts over ~1h13m**, then terminal `failed`.

| Status | Terminal? | Detail |
|---|---|---|
| `enqueued` | no | — |
| `retrying` | no | `attempt N: <exception>` |
| `deduped` | — | `occurrence N within window` |
| `delivered` | **yes** | `after N attempt(s)` |
| `failed` | **yes** | `gave up after N attempts: <exception>` |

**The delivery log** (`GET /v1/deliveries`) stores exactly seven fields per entry:
`id`, `ts`, `source`, `kind`, `title` (truncated to 200), `status`, `detail`
(truncated to 300). An in-memory ring buffer keeps the **last 200 per source**,
mirrored to append-only JSONL under `<CHAT_GATEWAY_STATE_DIR>/deliveries/`.

**Bodies are never logged on this path, structurally — not by convention.**
`DeliveryLog.record()` has **no body or card parameter at all**
(`delivery.py:44-50`); there is nowhere to put one. The rendered message goes to
the adapter, only `title` goes to the log.

> **One honest scope note.** That guarantee covers the `/v1/notify` and
> `/v1/heartbeat` path — everything in your contract. The separate raw-envelope
> endpoint `/v1/messages`, which your key *can* also call but your contract does
> not use, logs `text[:80]` as its title. If you never call `/v1/messages`, no
> body text of yours is ever written anywhere.

**Restart drops undelivered jobs.** The queue is in-memory. Those entries stay
`enqueued`/`retrying` in the log with no terminal status — visible, not silent.
Keep your local fallback log; the contract already assumes you do.

---

## 7. Dead-man monitor — the critical one

Lives on the gateway (always-on side), exactly as the contract requires; your
host may sleep. `heartbeat.py`.

**`schedule` — the complete grammar.** Input is stripped and lowercased.

| Value | Period |
|---|---|
| `daily` | 24h |
| `weekdays` | 24h, with the weekend roll below |
| `every:<N><s\|m\|h\|d>` | N × unit |

Anything else → `bad schedule '<x>' (use weekdays | daily | every:<N><s|m|h|d>)`.

**`grace` is required — there is no default.** Format `^\d+[smhd]$`: digits, one
unit suffix. It is stripped but **not** lowercased, so `2h` works and **`2H`
fails** with `bad duration '2H' (use e.g. 90s, 30m, 2h, 1d)`.

**The weekend roll** (`heartbeat.py:75-85`), which is the no-false-alarm
guarantee: the due date is computed, converted into `tz`, and then
`while local.weekday() >= 5: local += 1 day` — Saturday and Sunday both roll
forward to Monday, in **your** timezone, default **`America/New_York`**. The
deadline is `next_due + grace`.

**Repeat** is daily (`DEFAULT_REPEAT_S = 86400`) until you refresh or delete, and
the repeats collapse through the same deduper (`dedupe_key: "hb:<check_id>"`).
The alert is `severity: alert`, so it takes your **alert** route:

```
title: heartbeat missed: daily-trading-run
body:  No refresh since <iso> (schedule weekdays, grace 2h).
       Repeats daily until refreshed or deleted.
```

**Refresh semantics worth knowing:** `POST /v1/heartbeat` builds a **brand-new
check** each call. So a refresh clears `status` back to `ok` and resets
`last_alerted`, **and** lets you change `schedule`, `grace` or `tz` in place —
there is no separate update call. Validation runs before any mutation, so a bad
refresh leaves the existing check untouched.

**Persistence:** `<CHAT_GATEWAY_STATE_DIR>/heartbeats.json`, written atomically
(temp file + replace). Checks survive a gateway restart.

**US market holidays are deliberately not modeled.** This is a decision, not an
oversight, and your contract pre-agreed the remedy: **widen `grace`**. A holiday
Monday means the Friday run's next weekday due-date lands on a closed market —
`grace: "74h"` covers it. Modeling an exchange calendar would put domain
knowledge in the gateway, which hard rule #1 forbids.

**If your alert route is missing when a check fires**, the monitor does not
crash: it records the alert in the delivery log as `failed` with
`no route: <detail>`.

---

## 8. No inbound path — the guarantee, restated on its real basis

> **⚠ Corrected 2026-07-30 (CG-27). The previous version of this section was
> wrong, and it is worth saying exactly how.** It claimed *"the gateway design
> has NO callback/webhook-to-consumer mechanism at all — inbound (where enabled
> for other apps) is passive polling only."* **That has been false since
> 2026-07-24**, when a per-tenant `callback_url` push path landed for another
> tenant. Hard rule #6 names **two** inbound opt-in paths, not one.
>
> **aitrader's guarantee never changed** — but the old sentence grounded a
> correct conclusion in a false premise, which is worse than it looks: a reader
> who discovered the callback path existed would reasonably conclude the
> guarantee was wrong too. It is not. It rests on something stronger.

**The real basis: the mechanism exists, and this app is locked out of every part
of it — at load time, at the door, and at dispatch.** That is a stronger claim
than "no such mechanism exists", because it survives the gateway growing more
inbound features. It is enforced in code, not merely omitted:

| # | Path | Enforcement | Where |
|---|---|---|---|
| 1 | **Passive polling** | `GET /v1/inbox` → **403** `inbound is disabled for this app (no-inbound-control contract — gateway hard rule #6)` | `service.py:242-247` |
| 2 | **`callback_url` push** | Setting `callback_url` on this app is a **registry validation error at process start** — the gateway refuses to boot: `app 'aitrader': callback_url requires allow_inbound: true — an opted-out tenant gets NO inbound path (hard rule #6)` | `registry.py:272-276` |
| 3 | **Event dispatch** | An opted-out app is skipped before anything is written: nothing to the inbox, nothing forwarded, nothing to the audit trail | `adapters/pubsub.py:648-660` |
| 4 | **Card convention** | `GET /v1/identities` returns `interaction: {"enabled": false, "reason": "inbound is disabled for this app (hard rule #6) — card interactions from it are never routed anywhere"}` — this app is never even handed a routing target | `service.py:85-88` |

Point 2 is the one that makes this a *contract* rather than a setting: the
gateway **will not start** in a configuration that gives aitrader an inbound
path. There is no runtime state in which a misconfiguration quietly opens one.

Widening this requires explicit user sign-off naming hard rule #6. Your own
contract's reasoning — a two-way path is a security hole in a system placing
real-money trades; the brakes release only at the machine — is recorded in the
committed registry beside the flag, so nobody removes it thinking it was a
default.

### What `/healthz` now shows, and what it does not (CG-12, shipped 2026-07-30)

`/healthz` gained two **bare integers** under `subscriber`:
`suppressed_opt_out` and `suppressed_not_authorized`. They exist because a space
whose registered owners **all** opted out used to discard events with *zero*
trace anywhere — hard rule #6 satisfied, hard rule #5 (honest health) not.

Read carefully, because two things about them are easy to get wrong:

1. **They count candidate apps that DECLINED an event — not events that went
   nowhere.** The decision is made per candidate app, so `suppressed_opt_out`
   increments for an opted-out owner **even when a co-owner of the same space
   received that same event**. It is not a lost-event counter;
   `subscriber.events_seen` is the event count.
2. **They store nothing attributable — no app id, no space, no sender, no
   content, no timestamp — because `/healthz` is unauthenticated.** A
   metadata-only record and a full audit record were both considered and
   **rejected**. Neither counter is an input to `status`; suppression never makes
   the gateway report `degraded`, because a guarantee working is not a fault.

**What this means for aitrader specifically, stated precisely rather than
reassuringly.** A "candidate" is an app owning an identity **homed in the event's
space** (`registry.apps_for_space`, `registry.py:161-172`), and an identity with
an empty `space` is homed nowhere.

⚠ **CORRECTED 2026-07-30, and the correction matters more than the original
claim.** This section first said *"both aitrader identities ship with
`space: ""` … so aitrader cannot increment either counter at all"*, and derived
the guarantee from that. **The premise is true only of the committed template.**
`config/registry.example.yaml` ships `space: ""`; the live `config/registry.yaml`
(gitignored) homes **both** aitrader identities:

| Registry | `apps_for_space("spaces/…")` for either aitrader space | Effect |
|---|---|---|
| `registry.example.yaml` (committed) | `[]` | never nominated |
| `registry.yaml` (**live**) | `['aitrader']`, `allow_inbound: false` | **would increment `suppressed_opt_out`** |

Verified by running the real `apps_for_space` against both files, not by reading
them. This is the second time in one day a claim about this project was derived
from the committed example while the live registry said otherwise — check which
file you are looking at.

**What actually holds today, and why.** No inbound event has ever named aitrader
as a candidate, but the reason is **not** the registry — it is that the tier-2
Chat app is not in aitrader's spaces, so no Pub/Sub event originates from them.
Those identities are `mode: webhook`, and a webhook is one-way: it needs no app
membership to deliver, and produces no inbound events. That is a **console**
fact, not a config one, and it is not verifiable from this repo.

So the safeguard is **one step away, not two.** The original text said this
changes only if an operator both fills in a `space:` *and* adds the Chat app to
that space. In the live registry the `space:` is **already filled** — adding the
Chat app to an aitrader space would be sufficient on its own, and it is a console
action that leaves no trace in version control.

In that configuration each event in that space would add 1 to
`suppressed_opt_out` — a bare volume integer, pooled with any other opted-out
tenant, on an unauthenticated endpoint. Still no attribution, still nothing
persisted, and marginal next to `events_seen`, which already publishes total
inbound volume on the same endpoint. **`allow_inbound: false` is unaffected
throughout** — nothing crosses to aitrader in any of these configurations; the
only question is whether a bare integer moves.

Recorded because "nothing about aitrader is observable" should be true for a
**stated and correct** reason, not by assumption — and the first stated reason
was wrong.

**Nothing about aitrader's traffic is persisted anywhere, in any configuration.**

---

## 9. Tier 1 is the floor under your alerting — empirically, not by design intent

A Google Chat webhook URL is issued **by the space**, not by a Cloud project.
That was always the design claim; on **2026-07-30 it became an observation**: all
four webhook identities — `aitrader-alerts` among them — returned `delivered`
through the real `WebhookAdapter` **immediately after the tier-2 Cloud project
was deleted**.

**So no tier-2 change can take this consumer's alerting down.** Not a project
migration, not a deleted project, not a revoked service-account key, not Pub/Sub
quota exhaustion — aitrader's path touches none of them.

This matters more for aitrader than for any other consumer, and for a specific
reason: **it is the one tenant with no inbound path to fall back on** (§8). There
is no "tap to acknowledge", no reply channel, no second route by which a missed
alert could surface. The outbound webhook is the entire channel, so its
independence from the rest of the system *is* the reliability argument.

Practical consequence for your runbook: if `/healthz` reports `degraded` for a
tier-2 reason (`subscriber.*`), **your alerting is unaffected**. The two fields
that actually gate your path are
`registry.identities["aitrader-alerts"].env_resolved` and
`registry.apps["aitrader"].key_configured`.

---

## 10. Verification status — what has actually met Google

The webhook **send** path is live-verified: text and Cards v2 delivered and
confirmed rendering (2026-07-29, re-confirmed 2026-07-30 — see §9). That is the
success path your alerts travel.

**For the complete and current list of what is still unexercised against Google,
read the verification ledger in [`../../CLAUDE.md`](../../CLAUDE.md)
("Verification ledger").** It is deliberately **not** summarized here. That file
records that every attempt to restate it in this repo has drifted within two PRs
— including one summary that was wrong twice in the same way — so this doc links
it instead of copying it. Read it there; it is the single authoritative list.

Everything in §§2–7 is pinned by deterministic offline tests in
`tests/test_notify_heartbeat.py`, whose docstring is *"The aitrader contract's
acceptance criteria, as deterministic tests"* — including your acceptance
criteria 2 (dedupe 10×→1), 3 (weekday dead-man, weekend silence, daily repeat)
and 4 (full delivery-log accounting). Criterion 1's remaining half is a **human
observation** — *curl → loud card visible in the alert space within seconds* — a
judgement about rendering and latency, not a code seam. Run it as your first
smoke test.

---

## 11. Sharp edges and accepted limitations

**Sharp edges — behaviours that will surprise you:**

- **`info` has a combined length limit that `alert` does not.** On the `info`
  path the title and body are concatenated into one 4000-char text field, so
  **`len(title) + len(body)` must be ≤ 3989** — even though `body` alone
  validates at 4000. Over that, the request is a **422** naming both the limit
  and the size you sent; `body`'s own 4000 limit and `title`'s own 200 are
  unchanged and still reported separately. `alert` and `warning` are unaffected
  (their body becomes a card widget, so only the short fallback line goes
  through the text field) — a title-200 + body-4000 payload is accepted on
  those two and rejected on `info`.

  The 3989 is not a number to hardcode: it is `4000` minus the rendered prefix
  `"ℹ️ [INFO] "` (10 characters — the emoji is two code points) minus the
  newline. The gateway derives it from the same construction the renderer uses,
  so relabelling a severity moves it. Read it off the 422 rather than computing
  it yourself.

  Measured at the endpoint, before and after **CG-30** (2026-07-30):

  | severity | `len(title) + len(body)` | before | after |
  |---|---|---|---|
  | `info` | 3989 | 202 | 202 |
  | `info` | 3990 | **500** | **422** |
  | `alert` | 4200 | 202 | 202 |
  | `warning` | 4200 | 202 | 202 |

  **What changed is the status code, not the limit.** Before CG-30 the overflow
  raised inside the renderer, after validation had already passed, and surfaced
  as an uncaught **500**. Nothing that was accepted before is rejected now. If
  your weekly report can run long, either keep it on `warning` (a card, no
  combined limit) or split it — but you no longer have to guess, because the
  rejection tells you the limit and your size.

- **A very long deduped `info` message may show a shortened counter, or none at
  all** (CG-32, 2026-07-30 — this step used to be a **500**). A deduped
  re-delivery has the gateway's `" (×N since last notice)"` appended by the
  renderer, and on an `info` payload near the 3989 bound there is nowhere to put
  it: the message is already exactly as long as the field allows. The renderer
  now degrades **its own** counter rather than overflowing — full form, then
  `" (×N)"`, then nothing — so this sequence is 202 throughout where its last
  step used to raise inside the renderer and surface as an uncaught 500:

  | step (combined 3989, with a `dedupe_key`) | before | after |
  |---|---|---|
  | first delivery | 202 | 202 |
  | repeats within the window (suppressed, counted) | 202 | 202 |
  | after the window reopens, `occurrences=3` | **500** | **202** |

  **Your content is never what gets shortened.** The counter is the gateway's
  own accounting of its own dedupe window — transport decoration, not your
  schema (hard rule #1) — so it is what yields; your title and body are
  delivered byte-for-byte. The "leave ~40 characters of slack under 3989"
  workaround this section used to recommend is **no longer needed**, and 3989 is
  **unchanged**: nothing accepted before is rejected now.

  **The count is not lost when the counter is dropped — it is in the log.**
  Every suppressed occurrence is recorded as `deduped` / `occurrence N within
  window` (§5). `GET /v1/deliveries` serves the last 200 per source (`limit`
  defaults to 50); the complete record is the append-only JSONL under
  `<CHAT_GATEWAY_STATE_DIR>/deliveries/`. Measured 250 suppressions deep: the
  ordinal a dropped counter would have shown is the **highest**, hence the
  newest entry, hence the last thing the ring buffer evicts.
- **`action` and `timestamp` are dropped on `info`** (§4).
- **`grace` is case-sensitive** — `2H` is a 422 (§7).
- **`dedupe_key` ignores severity** — an `info` and an `alert` sharing a key
  collapse into one (§5).
- **`source` in your payload is ignored** (§2).

**Accepted limitations, agreed in the contract:**

- **US market holidays are not modeled** — widen `grace`; `74h` covers a Monday
  holiday from a Friday run (§7).
- **The queue is in-memory** — a restart drops undelivered jobs, visibly (§6).
  Keep your local fallback log.
- **Webhooks cannot edit a posted message**, so a dedupe window shows its
  collapsed count on the *next* delivered message rather than by mutating the
  first (§5).
- **The dedupe window is not runtime-configurable** — no env var, no registry
  key (§5).

---

## 12. Operator checklist — env var NAMES only

Per hard rule #2 this repo commits **names**, never values. Webhook URLs embed
`key`+`token` and *are* credentials; they live only in the runtime env
(`/srv/chat-gateway/.env`, mode 600), never on a command line, in a chat message,
or in an assistant prompt.

| Env var **name** | Purpose |
|---|---|
| `CHAT_GATEWAY_API_KEY__AITRADER` | aitrader's bearer key. **Rotate this to revoke** — that is the whole revocation mechanism, and it is per-app. |
| `GOOGLE_CHAT_WEBHOOK_URL__AITRADER_ALERTS` | the loud, phone-visible space |
| `GOOGLE_CHAT_WEBHOOK_URL__AITRADER_REPORTS` | the quiet reports space |
| `CHAT_GATEWAY_STATE_DIR` | heartbeat checks + delivery JSONL (default `state`) |
| `CHAT_GATEWAY_REGISTRY` | identities + apps config (default `config/registry.yaml`) |

Mint a key with `python3 -m chat_gateway mint-key`. Confirm readiness without
auth at `GET /healthz`: `registry.identities` reports `env_resolved` per identity
and `registry.apps` reports `key_configured` — booleans and names, never values.

---

## 13. Requirement → implementation map

| Requirement (aitrader, 2026-07-26) | Where it is met |
|---|---|
| Single authenticated POST, curl-able, stdlib-only | `POST /v1/notify`, bearer header, no SDK required (§2) |
| Accept fast (<2s), 2xx on enqueue, gateway owns retries | 202 on enqueue + async dispatcher, backoff 0s/30s/2m/10m/1h → `failed` (§6) |
| Routing is config, not code: (source, severity) → space | registry `apps.aitrader.routes` → `aitrader-alerts` / `aitrader-reports` (§3) |
| Severity rendering — alert loud, info plain | `notifications.render` — card + ⚠️🔴 + prominent "What to do"; info plain text (§4) |
| Dedupe window with occurrence counter (default 1h) | `Deduper`, 3600s; count on the next delivery; every occurrence in the log (§5) |
| Threading via `thread_key` | passed through to Chat thread mechanics (§2) |
| Dead-man checks on the always-on side | `POST /v1/heartbeat` + gateway-resident monitor (§7) |
| Weekday awareness, no weekend false alarms | `schedule: weekdays`, Sat/Sun roll to Monday in `tz` (§7) |
| Missed alerts repeat on backoff until refreshed/deleted | daily repeat, dedupe-collapsed (§7) |
| US-market-holiday awareness (nice-to-have) | **not modeled, documented** — widen `grace` (§7, §11) |
| Check states queryable | `GET /v1/heartbeat/{source}`, own source only (§2) |
| Decommission | `DELETE /v1/heartbeat/{source}/{check_id}` (§2) |
| Versioned paths, schemas, one curl per endpoint | `/v1/*`, `GET /docs`, [integration guide](../integration-guide.md) |
| Per-source revocable tokens | per-app key env var — rotate to revoke (§12) |
| Delivery log (enqueued → delivered/failed) | `GET /v1/deliveries`, last 200 per source (§6) |
| Bodies never logged | `DeliveryLog.record()` has no body parameter (§6) |
| **Non-goal 1** — no inbound control path, enforced not omitted | **enforced at four points, incl. refusing to boot** (§8) |
| **Non-goal 2** — no consumer semantics in the gateway | notify shape is generic; rendering varies only by severity (hard rule #1) |

---

*Companion docs: [`jobhunt-handoff.md`](jobhunt-handoff.md) — the same answer-back
for the **two-way** tenant, and the sharpest available contrast with §8 — plus
[`jobhunt.md`](jobhunt.md), its contract of record. Note the two consumers are
laid out differently: jobhunt keeps contract and handoff as separate files, while
aitrader's are merged into this one. Gateway constitution:
[`../../CLAUDE.md`](../../CLAUDE.md).*
