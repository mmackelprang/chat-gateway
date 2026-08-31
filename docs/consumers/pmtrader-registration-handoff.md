# Registering `pmtrader` as its own gateway app — handoff

**Date:** 2026-08-31 · **From:** chat-gateway (Builder) · **To:** whichever agent
team executes the registration · **Status:** nothing is registered, nothing is
decided, no code changed.

The owner has decided **that** `pmtrader` becomes its own app in this gateway's
registry. This file exists so the team that executes it does not have to
rediscover the shape of the problem. Every factual claim below was measured
against this checkout at `0c0d8e3`; §1 gives the method for each.

---

## 0. What this document is, and what it is not

| It is | It is not |
|---|---|
| a handoff — the facts, the surface, and the decision list | a plan or a spec. There are no tasks and no sequencing |
| an inventory of what pmtrader borrows from `aitrader` today | a recommendation. **No values are proposed here** — not a space, not an env-var name, not a route |
| a statement of which choices are the owner's | an ADR. Nothing has been decided by writing it |

**No queue row was filed and no CG id was minted.** This is deliberate: a row is
a commitment to ship, and the owner has said the team ships it, not this pass.

⚠ **`docs/consumers/pmtrader.md` does not exist and this file is not it.** That
slot holds the *consumer contract* — the gateway's answer to a consumer's
requirements, as `aitrader.md` and `jobhunt.md` do. pmtrader has no contract
because pmtrader is not a consumer of this gateway; it is a client written
against this gateway's documentation. **The contract lands with the
registration, not before it.**

---

## 1. The finding, re-measured here

**Method.** Commands run from the repo root at `0c0d8e3`, POSIX, the repo's
documented test/dev interpreter (`python3`, `CLAUDE.md` § Layout).

| # | Claim | How it was checked | Result |
|---|---|---|---|
| 1 | pmtrader is not a registered app | `grep -rn pmtrader config/ src/ docs/` | **exit 1, zero hits.** `git grep -n pmtrader` — zero hits |
| 2 | the registry registers exactly three apps | `load_registry("config/registry.yaml")` — the **real loader**, not a YAML read | `['aiteam-harness', 'job-hunter', 'aitrader']` |
| 3 | the app id comes from the key, never from the request | read `auth.py:22-38` | `authenticate` iterates `registry.apps`, constant-time-compares the presented bearer against `os.environ[app.key_env]`, and **returns the registry's YAML key** for the first match |
| 4 | the client's `source` cannot override it | read `notifications.py:82-83`, `service.py:466-467` | `source` is `str | None`, described *"informational; the authenticated app is authoritative"*; `notify()` calls `emit_notification(app_id, n)` and **`n.source` is read by nothing on the path** |
| 5 | the consumer doc says so in the same words | `docs/consumers/aitrader.md:53` | *"**accepted and ignored.** The authenticated app is authoritative — the gateway uses your key-derived app id everywhere (routing, dedupe, the delivery log)."* |

**So: pmtrader authenticates with `aitrader`'s bearer token, and the gateway sees
every pmtrader message as `aitrader`.** `pmtrader`'s own `DEFAULT_SOURCE =
"pmtrader"` is inert — it reaches a field the gateway stores and never consults.

⚠ **The inference reads no credential and none was read.** It follows from the
code path alone: a token either resolves to a registered app or it is a `401`
and nothing is delivered. Alerting demonstrably works, and `pmtrader` is not a
registered app.

---

## 2. What pmtrader borrows from `aitrader` — end to end

Ten surfaces, each with the site that makes it so. This is the cost the
registration buys back. (**Ten**, counted off the table below — this repo has
been bitten enough times by a prose count that disagrees with its own list.)

| Borrowed | Site | What it means today |
|---|---|---|
| the **bearer key** | `auth.py:22-38` | one secret authenticates both projects; rotating it for one silently disables the other |
| the **app id** | `auth.py:34-37` | `aitrader` is the id used for everything below |
| the **destination spaces** | `registry.route_for`, `registry.py:148-159` | pmtrader's alerts land in `aitrader`'s alert space and its quiet traffic in `aitrader`'s reports space |
| the **dedupe namespace** | `service.py:335`, `notifications.py:231-248` | dedupe is keyed `(app_id, dedupe_key)`; the window and the occurrence counters are `aitrader`'s |
| the **delivery log** | `service.py:337, 341, 633-635` | `GET /v1/deliveries` is per-source and capped; each project's traffic evicts the other's history |
| the **heartbeat namespace** | `service.py:519, 611-621, 623-629` | checks are keyed on the app id; `GET /v1/heartbeat/aitrader` would list pmtrader's checks, and a `check_id` collision is two systems refreshing one check |
| the **dead-man thread key** | `heartbeat.thread_key_for`, `heartbeat.py:110-128` | `hb:<source>:<check_id>` — so a pmtrader check threads under `hb:aitrader:…` |
| the **dead-man title** | `heartbeat._title`, `heartbeat.py:194-211`; thread root `heartbeat.py:312` | `[aitrader] heartbeat <check_id> — …` and `[aitrader] 🧵 Heartbeat <check_id>` — **the gateway's own messages carry the wrong project's name** |
| the **card subtitle label** | `notifications.py:223` | `f"{app_id}: {n.title}"` → `aitrader: <pmtrader's subject>` |
| the **consumer doc** | `docs/consumers/aitrader.md` | pmtrader's operators read another project's contract, and any deviation pmtrader needs has nowhere to be recorded |

⚠ **The card subtitle is the card branch only.** `render` (`notifications.py:189-227`)
builds a card for `alert` and `warning`; **`info` returns plain text and
references `app_id` nowhere.** This matters in §7 and it is the single easiest
fact here to get backwards.

---

## 3. The registry shape, as it actually is

Read off `registry.py`'s dataclasses (`Identity` at `:81-87`, `App` at
`:109-117`) and the loader's validation (`registry.py:265-287`), not off an
example.

### `identities:` — **destinations.** Where a message can go.

| Key | Type | Default | Notes |
|---|---|---|---|
| `display` | str | the identity's own name | ⚠ **cosmetic here.** `adapters/webhook.py:3-7`: *"display name and avatar are fixed at webhook creation in the Chat UI, and Chat renders THAT name."* Setting it in the registry does **not** change what a space shows |
| `channel` | str | `google_chat` | |
| `mode` | str | `webhook` | tier 1. `aitrader`'s two identities are both `webhook` — no Google Cloud project, no service account |
| `webhook_url_env` | str \| None | `None` | the **env-var NAME**. The URL embeds `key`+`token` and is a secret (hard rule #2) |
| `space` | str | `""` | `spaces/…` — a posting target, **not** a membership record |

### `apps:` — **senders.** Who may send, and where they may send.

| Key | Type | Default | Notes |
|---|---|---|---|
| `key_env` | str | **required** — `RegistryError` if absent | the env-var NAME of that app's bearer key |
| `identities` | list[str] | `[]` | the hard-rule-#4 allowlist. Every name must exist, or load fails |
| `allow_inbound` | bool | ⚠ **`True`** | see the trap below |
| `routes` | dict | `{}` | severity → identity, for `/v1/notify`. Every routed identity must be in this app's own `identities` |
| `callback_url` | str | `""` | inbound push. **Requires `allow_inbound: true`** — otherwise a load-time `RegistryError` |
| `allowed_users`, `unreachable_message` | | | two-way tenants only; not relevant to a notify-only app |

⚠⚠ **`allow_inbound` defaults to `True`, so omitting it is not "off".** This is
not hypothetical: `aiteam-harness` had inbound on for its whole life *because
`true` is the default* — it never asked for it — and CG-61 exists to write the
`false` explicitly. `registry.example.yaml:77` records the lesson at the
`agent-mcp` entry: *"`allow_inbound: false` and it is WRITTEN, not defaulted
(CG-61's lesson)."* **Whatever the owner decides in §4.3, write it.**

### The worked example — `aitrader`, redacted

Verbatim from the live `config/registry.yaml`, **with the space ids removed**.
Space ids are not on hard rule #2's secret list, but all four `space:` values in
the committed `registry.example.yaml` are `""` and this repo is public; the
values are read from the gitignored live file, not from here. The env-var
**names** are shown, which is the convention `docs/consumers/aitrader.md` §12
already uses — *"Operator checklist — env var NAMES only"*.

```yaml
identities:
  aitrader-alerts:                     # phone-visible space — loud
    display: "aitrader"
    channel: google_chat
    mode: webhook
    webhook_url_env: GOOGLE_CHAT_WEBHOOK_URL__AITRADER_ALERTS
    space: "spaces/…"                  # redacted here — Ai Trader

  aitrader-reports:                    # quiet reports space
    display: "aitrader reports"
    channel: google_chat
    mode: webhook
    webhook_url_env: GOOGLE_CHAT_WEBHOOK_URL__AITRADER_REPORTS
    space: "spaces/…"                  # redacted here — Ai Trader Reports, muted

apps:
  # notify + dead-man only; NO inbound control path — enforced, not omitted.
  aitrader:
    key_env: CHAT_GATEWAY_API_KEY__AITRADER
    identities: [aitrader-alerts, aitrader-reports]
    allow_inbound: false               # hard rule #6
    routes:
      alert: aitrader-alerts
      warning: aitrader-reports
      info: aitrader-reports
```

**Two identities, three routes, and `warning` and `info` deliberately share the
quiet one.** That is the shape a notify-plus-dead-man tenant takes here. It is
shown as the worked example, **not as a template to copy** — see §4.1.

---

## 4. The decisions the owner must make

Five. Each is stated as a decision with its consequences, and **none of them has
a recommended answer in this file.**

### 4.1 New Chat spaces, or reuse `aitrader`'s?

**This is an owner act either way, and only one of the two branches needs work
no agent can do.**

- **New spaces** need Google Chat webhooks, and **a webhook is created in the
  Google Chat UI by a person.** No agent in this repo can create one. Each new
  webhook then needs its URL in the runtime env under a new variable name, and
  the identity's `display` name and avatar are set **at webhook creation**, not
  in the registry (`adapters/webhook.py:3-7`).
- **Reusing `aitrader`'s identities** is a legal registry configuration —
  nothing forbids two apps listing the same identity — and it needs **no new
  webhook and no new space.** It fixes attribution (`app_id` becomes `pmtrader`
  everywhere in §2's table) and it fixes every namespacing row. **What it does
  not fix: both projects' traffic still arrives in one room.** ⚠ It also makes
  that space have **two owning apps** for inbound routing —
  `registry.apps_for_space` (`registry.py:161-172`) returns every app owning an
  identity homed in a space, and `adapters/pubsub.py:691` fans out to all of
  them. Inert today, because both apps would be `allow_inbound: false`; it
  stops being inert the moment either one is flipped.

⚠ The two halves of the problem are separable and the decision should say which
one it is solving. Registration fixes *identity*; new spaces fix *separation*.

### 4.2 Routes per severity

`routes` is not required by the loader, and skipping it fails in two different
places at two different times:

- **`/v1/notify` with no route for that severity → `503`**, not a silent drop.
  `route_for` raises (`registry.py:154-158`) and `emit_notification` converts it
  (`service.py:332-334`). The detail is actionable and names the fix — the message with its two
  interpolations shown as placeholders:
  `app '<app_id>' has no notify route for severity '<severity>' (add routes: {severity: identity} to the registry)`.
- **`POST /v1/heartbeat` registering a *new* `check_id` with no `alert` route →
  `422`** (`service.py:519-529`), because a check whose missed-alert could never
  be delivered must not be registered at all.

⚠ **The loud failure is worth stating plainly, because a team that meets a 503
without expecting one will look for a bug.** It is the design working:
`aiteam-harness` and `job-hunter` both carry `routes: {}` today and are in
exactly that state.

`routes: {default: <identity>}` satisfies every severity —
`route_for` is `routes.get(severity) or routes.get("default")`.

**What the decision has to cover:** which severities are routed, and to which
identity each. Note that `route_for` makes **severity pick the space**, not just
the loudness (CG-86), so routing `info` and `alert` to different identities puts
an all-clear in a different room from the alert it closes unless the sender
compensates.

### 4.3 `allow_inbound`

`aitrader` is `false` (hard rule #6 — its contract treats any two-way path as a
security hole in a real-money system). `job-hunter` is `true`.

**pmtrader has no inbound need on record.** Measured 2026-08-31, read-only,
over `~/prj/pmtrader`: `grep -rn 'v1/notify|v1/heartbeat|v1/messages|v1/deliveries'`
over its `src/` returns hits for **`/v1/notify` and `/v1/heartbeat` only**
(`watch.py:1532`, `:1578`, `:1620`; `report.py:1665`), and `v1/inbox`,
`callback_url` and `allow_inbound` appear nowhere in its `src/` at all. Its own
`docs/OPERATOR_ALERTING.md:230` already writes `allow_inbound: false` into its
draft. **That is an observation about pmtrader as it stands, not a decision.**
The owner confirms it, and the answer gets **written**, not defaulted (§3).

### 4.4 A new bearer token, its env-var name, and the pmtrader-side change

Four moving parts, and the last one is in a different repository:

1. mint a key — `python3 -m chat_gateway mint-key` (`auth.py:17-19`)
2. choose the env-var **name** for it and put it in the app's `key_env`
3. set that variable's value in the gateway's runtime env, and restart
4. give the same value to pmtrader as its gateway key

⚠ **Step 4 is a change in `~/prj/pmtrader`, not here.** Until it lands, pmtrader
keeps sending as `aitrader`. Registration alone changes nothing about what
pmtrader's messages look like.

### 4.5 Whether `docs/consumers/pmtrader.md` is written in the same PR

The other three consumers each have one and it is where a deviation is recorded.
Writing it late is how a consumer ends up documented by another consumer's file —
which is the state pmtrader is in now.

---

## 5. The migration surface — currently **EMPTY**, and that is why now is cheap

Every borrowed namespace in §2 is *live state keyed on the app id*. Changing the
app id does not migrate any of it; it **abandons** it and starts a new one. So
the cost of registering pmtrader is proportional to how much `aitrader`-keyed
pmtrader state exists at cutover.

**Right now that is nothing.** The owner deleted the only `aitrader`-sourced
heartbeat check, `candle-crawl`, on 2026-08-31, reporting **HTTP 200** — ⚠ **the
owner's report, not a measurement from this repository; see the end of this
section for what was and was not checked.**

**What would otherwise have had to move, and what each would have cost:**

| State | If it existed at cutover |
|---|---|
| dead-man check registration | the check would have to be re-registered under the new app id; the old one keeps ticking under `aitrader` and eventually alerts as a **fabricated outage** on a source that never stopped |
| dead-man **thread key** | `hb:aitrader:candle-crawl` → `hb:pmtrader:candle-crawl`. ⚠⚠ **An incident open across the cutover would post its all-clear into a brand-new thread** — the exact *"a RESOLVED that starts a new thread is a bug"* failure — the owner's message policy, quoted in-repo at `service.py:324-325` — arriving through a rename rather than through a missing key |
| dedupe window state | in-window suppression resets; the first post-cutover message re-delivers rather than collapsing |
| delivery-log history | pmtrader's history stays under `aitrader` and is unreachable from `GET /v1/deliveries` with the new key |

⚠⚠ **The window closes on its own.** `POST /v1/heartbeat` **registers on
first ping** — the same call refreshes and creates (`service.py:519-532`). So
the moment pmtrader's crawl runs again while still holding `aitrader`'s key,
`candle-crawl` is re-registered under `aitrader` and the migration surface stops
being empty. **Nobody has to do anything wrong for that to happen; it is the
normal operation of the thing.**

### What §5 was and was not verified against

⚠ **The deletion itself is the owner's report and cannot be verified from this
repository.** Heartbeat state lives in `CHAT_GATEWAY_STATE_DIR` on the box
(`docs/deploy/nas.md:141` — `heartbeats.json`), and this checkout's `state/`
holds only `queue/delivery.jsonl` and `queue/inbox.jsonl`. What **was** verified
here: `DELETE /v1/heartbeat/{source}/{check_id}` exists, is scoped to
`source == app_id` with a `403` otherwise, `404`s an unknown check and returns
`{"status": "deleted", …}` on success (`service.py:623-629`); and the repo's own
CG-86 record shows `candle-crawl` alive under this gateway as recently as
`last_alerted 2026-08-31T15:47:52Z`. **Confirm the check list is empty before
relying on §5** — `GET /v1/heartbeat/aitrader`, authenticated, sends nothing.

---

## 6. Three copies of the registry, and CG-61's lesson

⚠⚠ **The largest execution hazard here is not the YAML. It is that "merged" and
"in effect" are different events, and this repo has already paid for the
difference.**

There are three registry files and only one of them is in git:

| Copy | Tracked? | Role |
|---|---|---|
| `config/registry.example.yaml` | **yes** | the template. A PR can change this |
| `config/registry.yaml` (dev box) | **no** — `.gitignore:7` | the live file this checkout loads |
| `/mnt/datapool/apps/chat-gateway/config/registry.yaml` (NAS) | **no** | what the running service reads |

`registry.example.yaml:82-85` states the rule at the site, for the `agent-mcp`
tenant: *"⚠ REGISTERING THIS FOR REAL IS AN OPERATOR ACTION, NOT A PR. The live
`config/registry.yaml` is gitignored and the key is a new secret, so this example
is a template and nothing more. Until an operator mints a key, writes the entry
and restarts, the MCP surface has no caller."*

**CG-61 is the cautionary precedent.** Its PR changed only
`registry.example.yaml`; the live edit was a separate operator action that landed
**78 minutes after** a measurement that had recorded it as still outstanding, and
the queue carried the wrong state in between. `docs/BUILDER_QUEUE.md` § CG-61
records it as *"⚠ **Merging is not finishing**"*.

### ⚠ A drift observation, offered as a hazard rather than a finding

Measured here: this checkout's `config/registry.yaml` has an mtime of
**2026-08-03 16:34:06 −0400** and loads three apps — **no `agent-mcp`**. The
queue records (2026-08-11, flattened-text match, because the sentence wraps and
a plain `grep` misses it) that *"an operator minted the key and wrote the
registry entry on 2026-08-11"*, and `docs/deploy/nas.md`'s install step is

```bash
ssh <nas> 'sudo tee /mnt/datapool/apps/chat-gateway/config/registry.yaml >/dev/null' < ./config/registry.yaml
```

— i.e. **it overwrites the box's registry with this checkout's copy.**

⚠ **If the box's registry carries `agent-mcp` and this one does not, running that
step as written deletes it.** I cannot read the box, so this is a hazard with
its evidence and its limit stated, not a measured drift. **Whoever executes the
registration should diff the two before installing either.** `docs/deploy/nas.md:103-105`
already warns that the live and example files differ and that *"that difference
has caught three people."*

---

## 7. What registering pmtrader unblocks — and what it does not

pmtrader's **BQ-031** is filed `🛑 blocked`, awaiting an operator call between
three options. Its subject is an operator ruling to drop the `[pmtrader]` token
from pmtrader's message titles on the premise that the gateway already supplies
the app name. pmtrader measured that premise against this repo's source, found
it fails, changed no title, and filed the question. It records **three numbered
findings**, which reduce to **two independent grounds**: the subtitle is
card-only (its findings 1 and 2 — the mechanism and its consequence for
pmtrader's four title sites), and the app id is `aitrader` (its finding 3).

BQ-031's option **(b)** is *"register a `pmtrader` app in the gateway"*, and it
is described there as fixing the misattribution **"for the card branch only"**.

**What registration removes:** the misattribution half. Today, dropping the
token would render `aitrader: <pmtrader's subject>` on the alert — another
project's name on pmtrader's incident, in a space that already carries
`aitrader`'s traffic. After registration the subtitle reads `pmtrader:` and that
objection is gone.

⚠⚠ **What registration does not remove, and this must not be blurred:** the
`info` branch **has no subtitle at all.** `render` (`notifications.py:189-227`)
emits a card for `alert` and `warning` only; `info` is plain text that never
references `app_id`. Three of pmtrader's four title sites are `info` — the
all-clear, the status report and the 🧵 Thread Title. **For all three, the app
name would come from the title or from nowhere, registered or not.**

⚠ **So registration does not settle BQ-031.** It removes one of the two grounds
the measurement rested on and leaves the other exactly where it was. BQ-031
remains the owner's call between (a), (b) and (c), and (b) is not a synonym for
"the token can now be dropped".

⚠ Corroborating, from this side: the gateway's **own** dead-man titles keep a
bracketed app token for the same reason. `heartbeat.py:202-206` protects it from
truncation on the ground that *"the head is the identifying half"*. The
transport and the consumer reached the same conclusion independently.

---

## 8. Verifying a registration without sending a message

Three checks, none of which posts to a Chat space:

1. **Load it.** `load_registry("config/registry.yaml")` raises `RegistryError`
   on an unknown identity, a route that does not point at one of the app's own
   identities, an unknown severity, a missing `key_env`, or a `callback_url`
   without `allow_inbound` (`registry.py:265-287`). A registry that loads has
   already passed hard rule #4's shape.
2. **`GET /healthz`.** Carries `registry.health()` (`service.py:777`), which
   reports per app `key_configured` — is the `key_env` variable set — and per
   identity `env_resolved` and `space_set`. **Booleans only; no values, no URLs**
   (`registry.py:174-187`).
3. **`GET /v1/identities`** with the new key. Authenticated, so a `200` proves
   the key resolves to the new app id, and the body names the app id it resolved
   to plus each identity's `ready` flag (`service.py:650-684`).

⚠ None of these proves a *delivery*. A webhook URL that resolves is not a
webhook that posts, and `env_resolved` is exactly the boolean that says which of
those two was checked.

---

## 9. Cross-references

| Where | What it holds |
|---|---|
| `~/prj/pmtrader` `docs/OPERATOR_ALERTING.md` §3 | *"The registration problem — read this before minting a key."* **Option A — register `pmtrader` as its own app (recommended)** and **Option B — reuse `aitrader`'s key**, with six named costs. Written from pmtrader's end, and accurate about this repo. ⚠ **No document in THIS repo had recorded any of it before now** — that is measurable and was measured: `grep -rn pmtrader` here returns nothing (§1) |
| `~/prj/pmtrader` `docs/BUILDER_QUEUE.md` § BQ-031 | the blocked row and its three options — see §7 |
| this repo `docs/consumers/aitrader.md` | the shape a notify + dead-man consumer contract takes here; §7 carries the dead-man cadence |
| this repo `docs/consumers/jobhunt-handoff.md` | the shape of a *consumer* handoff, for whoever writes pmtrader's contract |
| this repo `docs/integration-guide.md` | the curl cookbook a new tenant is pointed at |
| this repo `docs/deploy/nas.md` §6 (*Secrets onto the box*) | how the live registry reaches the box, and the mode bits it is installed with. §6, not §2 — checked, because a wrong section number here sends someone to the compose document |

⚠ **§3 Option A already contains a draft registry block with concrete identity
names, env-var names, routes and a key name.** It is **pmtrader's proposal**,
written from the far end — it is not this repo's recommendation and it is not a
decision. **The values in it are exactly the ones §4 reserves to the owner.**
It is cited here because it is the best existing statement of the *shape*, and
flagged because a reader in a hurry will otherwise copy it.

---

## 10. What is open, and what could not be checked from here

- **Every item in §4.** No value is proposed in this file.
- **The deletion of `candle-crawl` (§5)** — the owner's report; heartbeat state
  is on the box.
- **Whether the NAS registry has drifted from this checkout's (§6)** — stated as
  a hazard with its evidence and its limit.
- **BQ-031's disposition (§7)** — the owner's, and registration does not decide it.
