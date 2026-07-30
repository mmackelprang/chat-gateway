# Google Cloud setup — step by step

What you create, in order, with what can be scripted vs. what is console-only.
**Tier 1 (named webhooks) needs NONE of this** — only tier 2 (the two-way
Chat app + Pub/Sub events) does. Everything here is doable from any browser;
nothing requires being on the homelab network.

## What can be automated

- [`../iac/gcloud-setup.sh`](../iac/gcloud-setup.sh) — idempotent gcloud CLI
  script: project services, service account, topic, subscription, IAM, key.
- [`../iac/gcloud-setup.ps1`](../iac/gcloud-setup.ps1) — the same steps for
  **Windows**. Use this one there: under Git Bash, MSYS rewrites slash-bearing
  args like `--role="roles/pubsub.publisher"` into Windows paths and silently
  breaks the IAM bindings, and the bash script's `chmod 600` on the minted key
  is a no-op on NTFS (the `.ps1` uses `icacls` to lock the key to its owner).
- [`../iac/terraform/`](../iac/terraform/) — the same resources as Terraform
  (key creation deliberately left to gcloud so the private key never lands in
  TF state).
- **Console-only, no API/IaC exists:** the Chat API *Configuration* page
  (step 5) and per-space webhook creation (step 7).

## Steps

### 0. Prereqs
- A Google account in your Workspace (`mackelprang.com`) with permission to
  create GCP projects; you'll also want Workspace-admin visibility settings
  for the Chat app.
- `gcloud` CLI installed and authenticated (`gcloud auth login`) — or do
  steps 1–4 in the console following the same names.

### 1. Project
```bash
gcloud projects create chat-gateway-gw --name="chat-gateway"
gcloud config set project chat-gateway-gw
```

> **`chat-gateway-gw` (`#860649224827`) is the live project, and it is the only
> one.** This document used to name **`chat-gateway-prod`** here and in five
> other places. **That project was deleted on 2026-07-30**, so following the old
> text would have created a second project named after a deleted one. Substitute
> your own id throughout — the name is an example, not a requirement, and the
> IaC is parameterized by `PROJECT_ID`.

Chat API and Pub/Sub at this volume sit in the free tier. Billing turned out
**not** to be required: `chat.googleapis.com` and `pubsub.googleapis.com` both
enabled with `billingEnabled: false` — observed 2026-07-28 on
`chat-gateway-prod` (**deleted 2026-07-30**), and again on `chat-gateway-gw`
when the setup script ran clean there on 2026-07-29. That is the result for those two projects, not a
guarantee — if an `enable` call is rejected for billing, link a billing account
and retry.

### 2–4. APIs, service account, Pub/Sub (scripted)

> ### The provisioning claim that used to sit here was for a deleted project
>
> This box read **✅ Provisioned for `chat-gateway-prod`** — present tense,
> describing a run on 2026-07-28. **`chat-gateway-prod` was deleted on
> 2026-07-30.** A green check for a project that does not exist is worse than no
> check at all, so it is rewritten as dated history rather than reused.
>
> | Date | Project | What happened |
> |---|---|---|
> | 2026-07-28 | `chat-gateway-prod` — **deleted 2026-07-30** | steps 2–4 ran: APIs, service account, topic, subscription, the topic-publisher and subscription-subscriber bindings, and the SA key. **The run was incomplete**: it predated the Workspace Add-ons service agent, which did not exist and was therefore never bound — the failure documented below. The agent and its publisher binding were added by hand on 2026-07-29 and are now in all three IaC paths, so a re-run is a safe no-op. |
> | 2026-07-29 | `chat-gw-e1-20260729` — **deleted 2026-07-30** | experiment E1's throwaway classic project. Never production. |
> | 2026-07-29 | **`chat-gateway-gw` (`#860649224827`) — the live project** | the setup script ran **clean end to end**, including the add-ons service-agent step. This was the second virgin-project run, which is what turned the IaC from reviewed-by-reading into genuinely exercised. **The Terraform path is still unapplied** — only the script path has run. |
>
> Two lessons, both paid for. From the 2026-07-28 run: **"the script exited 0"
> was not evidence the project was complete.** From this box: a provisioning
> record needs a date *and* a project id, or it silently becomes a claim about
> whatever project the reader happens to be holding.

POSIX:
```bash
cd iac && PROJECT_ID=chat-gateway-gw ./gcloud-setup.sh
```
Windows (PowerShell — see "What can be automated" for why):
```powershell
.\iac\gcloud-setup.ps1 -ProjectId chat-gateway-gw
```
This enables `chat.googleapis.com` + `pubsub.googleapis.com` +
`gsuiteaddons.googleapis.com`, creates the `chat-gateway` service account, the
`chat-gateway-events` topic, the `chat-gateway-sub` pull subscription, grants
**both** publisher principals write on the topic (see below) and the SA
subscribe on the subscription, writes the service-account key (owner-only:
`chmod 600` on POSIX, `icacls` on Windows), and prints the `.env` block to copy.

> **⚠ The key filename is a variable, and one value of it in this repo is dead.**
> The scripts default `KEY_FILE` / `-KeyFile` to `chat-gateway-sa.json`. The key
> actually in use on `chat-gateway-gw` is **`chat-gateway-sa-gw.json`**, and
> **`iac/chat-gateway-sa.json` belongs to the deleted `chat-gateway-prod`** — it
> is dead, it will not authenticate, and its presence on disk is not
> configuration. Point `GOOGLE_APPLICATION_CREDENTIALS` at the key you actually
> minted, by full path. *(The scripts' default filename and example project id
> are corrected under queue item **CG-19**, which touches `iac/` and therefore
> ships separately.)*

> **Publisher principals — what is granted, and one question that is now
> permanently closed (updated 2026-07-30).**
> Two principals are granted `roles/pubsub.publisher` on the topic:
> `chat-api-push@system.gserviceaccount.com` (per Google's docs) and the
> Workspace Add-ons service agent
> `service-<PROJECT_NUMBER>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com`.
>
> **Which one delivered the first real event can never be established.** It
> arrived 2026-07-29 on `chat-gateway-prod`, immediately after the add-ons
> service agent was created and bound — strong correlation, but the variable was
> never isolated — and **that project was deleted on 2026-07-30.** This is closed
> by circumstance, not answered. Do not carry it as open work and do not file a
> task against it.
>
> **What an operator of a new project actually needs — stated as the inference
> it is, not as an observation.** A **classic** Chat app has no `gsuiteaddons`
> deployment at all, so the add-ons service agent has nothing to publish through:
> on a classic project the Chat-API-side publisher is the operative one, and the
> add-ons binding is **vestigial**. That is a deduction from the deployment
> model, not an observation of who wrote a message. **Both** bindings are kept in
> all three IaC paths, with comments explaining why, so a fresh-project operator
> is not stranded by the question being closed.
>
> Note also that GCP accepts IAM bindings to `*@system.gserviceaccount.com`
> principals **without validating that they exist**, so a clean
> `add-iam-policy-binding` was never evidence of anything on its own.

### Failure signature: "\<app\> is not responding"

If Chat replies **"\<app\> is not responding"** and nothing arrives in the
subscription, this is almost certainly the missing add-ons service agent.
Confirm by matching all four:

| Signal | Value |
|---|---|
| In Chat | `<app> is not responding` |
| `chat.googleapis.com/errors` | code **3**, "Can't post a reply" |
| `gsuiteaddons.googleapis.com/errors` | code **13**, "Unspecified error invoking the add-on" |
| `gcloud pubsub subscriptions pull chat-gateway-sub` | **zero** messages |

> This is the remediation applied on 2026-07-29, immediately after which a real
> event arrived. Per the caveat above that is strong correlation, not proof:
> the diagnosis matched all four signals, but the variable was never isolated.

Remediation (now built into both setup scripts and the Terraform, so this is
only needed for projects provisioned before 2026-07-29):

```bash
gcloud beta services identity create --service=gsuiteaddons.googleapis.com --project=<PROJECT_ID>
# -> service-<PROJECT_NUMBER>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com

gcloud pubsub topics add-iam-policy-binding <TOPIC> \
  --member="serviceAccount:service-<PROJECT_NUMBER>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
```

(`gcloud beta` needs the beta component; gcloud offers to install it on first use.)

> **Do not trust `pubsub.googleapis.com/topic/send_request_count`.** During
> this diagnosis that Cloud Monitoring metric reported **zero** publishes even
> after a message had demonstrably been published and pulled. It cost time and
> pointed the wrong way. The only reliable signal is pulling the subscription
> directly:
>
> ```bash
> gcloud pubsub subscriptions pull chat-gateway-sub --limit=5 --auto-ack
> ```
>
> The consequence is architectural, not just diagnostic: **no automated health
> check in this project may be built on that metric.** It is why `/healthz`
> reports billing/quota as a *declared* env value (`GATEWAY_GCP_BILLING`) rather
> than detecting it live — detection would mean trusting exactly the telemetry
> that read zero while a message was demonstrably flowing, on top of extra
> scopes and extra API calls. Quota exhaustion is caught the way every other
> subscription failure is caught: the poll fails, and consecutive poll failures
> degrade `/healthz`.

### 5. Chat app configuration — console only
Console → **APIs & Services → Google Chat API → Configuration**:
- **FIRST — clear *"Build this Chat app as a Google Workspace add-on"*** →
  confirm **Disable**. Do this **before** the first Save: clearing it is fine and
  reversible right up until you save, but **the choice you save is permanent**
  — a saved add-on app can never be turned back into a classic one. Read the
  callout below **before** you save anything on this page.
- **App name:** `Agent Comms` (or your pick — this is the tier-2 sender
  identity users see), avatar URL, description.
- **Interactive features:** enable; check *Receive 1:1 messages* and *Join
  spaces and group conversations*.
- **Connection settings:** **Cloud Pub/Sub** → topic
  `projects/<PROJECT_ID>/topics/chat-gateway-events` — on the live project,
  `projects/chat-gateway-gw/topics/chat-gateway-events`.
- **Visibility:** make available to your domain, or list individuals (note the
  scale limit recorded further down: up to five individuals, or Google Groups).
- Save.

> ### ⚠ The add-on toggle is CREATE-TIME ONLY — the second trap this project paid for
>
> **Answered by experiment E2, 2026-07-29, first-hand.** *"Build this Chat app as
> a Google Workspace add-on"* **cannot be cleared once the app has been saved.**
> Before the first Save it is an ordinary checkbox; after it, add-on → classic is
> not a toggle you can flip back.
>
> **This is the twin of the Marketplace-SDK correction under *"Also easy to miss
> in steps 5–7"* further down** — that one explains why this project chose the
> add-ons runtime, this one explains why the choice could not be undone. Read
> both or neither; separately they each look like a footnote.
>
> The consequence is expensive: escaping the add-ons runtime requires a **new
> Chat app**, and Chat app configuration is
> **per-project**, so it requires a **new GCP project**. ADR-0001 D7's
> parallel-project-and-cut-over path was therefore the *only* available path, not
> merely the prudent one — and that is exactly what happened here:
> `chat-gateway-prod` → `chat-gateway-gw`, after which `prod` was deleted.
>
> Before E2 ran this was recorded as *contradictory*: Google documents an
> explicit clear-and-confirm flow in two live quickstarts, while a third-party
> vendor doc (CloudM, 2026-03-16) warned *"This setting cannot be disabled once
> saved… you must create a new Google Cloud Project."* The quickstarts describe a
> **never-saved** state on a fresh app. CloudM described ours, and CloudM was
> right.
>
> **So decide the runtime before you press Save the first time.** Which runtime
> you get changes what a card can do — the capability comparison is in
> [ADR-0001](architecture/decisions/2026-07-29-tier2-interaction-model.md) §10.

### 6. Spaces + app membership
For each project/app that gets a space: create the space in Chat, then
**⚙ → Apps & integrations → Add apps** → add your Chat app. Grab each
**space ID** (open the space in a browser — the URL ends
`/room/AAAA...` → the ID is `spaces/AAAA...`).

> **What is deployed today — a console observation dated 2026-07-30, not
> something this repository can prove.** The live Chat app is the **classic** app
> named **"Agent Comms"** on `chat-gateway-gw`, and it has been added to the
> **JobHunt space only**. That is a fact about the Google Chat console and is
> readable nowhere in this repo: no source file, no registry entry and no test
> records which spaces an app has been added to. (The registry does carry a
> `space` per identity — but that is a *posting target*, where the gateway sends;
> it is not a record of which spaces the Chat app has been **added to**, and the
> two can disagree in either direction.) Treat it as a snapshot that goes
> stale the moment somebody adds the app to a second space — re-check the
> console, not this line.

### 7. Tier-1 named webhooks (per identity, console only, ~1 min each)
Space → **⚙ → Apps & integrations → Webhooks → Add webhook** → name it as
the identity should appear (e.g. `PM · familyworkspace`, `aitrader`) + an
avatar URL → copy the webhook URL.

> **The name is not optional.** Messages posted through a webhook come back
> from Google with `sender: null` — there is no sender object at all. Chat
> renders the webhook's *configured display name* instead, so a webhook created
> without one appears in the space as **"Unknown User"**. Name and avatar are
> fixed at creation time and are the only identity a tier-1 message has.
> (Observed 2026-07-29 against a real webhook.)

> **⚠ The URL you copy is a credential.** It embeds `key` and `token` and is
> sufficient to post into that space as that identity. Read §8a before you paste
> it anywhere — including into a terminal or an AI-assistant prompt.

### Also easy to miss in steps 5–7

- Steps 6 and 7 happen in **chat.google.com**, not the Cloud Console. Looking
  for them in the Console is a dead end.
- **⚠ CORRECTED 2026-07-29 — this document was wrong, and the mistake was
  expensive.** It used to say: *"The app will not appear under ⚙ → Apps &
  integrations → Add apps until the Google Workspace Marketplace SDK
  (`appsmarket-component.googleapis.com`) is enabled and the app is published."*
  **That is false.** Installability comes from the **Chat API → Configuration →
  Visibility** setting: list your own address (or a Google Group) there and you
  can add the app to a space immediately. Marketplace publishing is required
  only to reach people *beyond* that list — and on an add-ons deployment
  Google states its settings are ignored for Chat outright:

  > "To deploy and test an add-on in Chat, you must use the Chat API's
  > Visibility setting. Any visibility or testing settings that you've
  > configured in the Google Workspace Marketplace SDK **are ignored**."
  > — <https://developers.google.com/workspace/add-ons/chat>

  > "the Chat API lets you share your Chat app with specific people in your
  > Google Workspace organization. The people that you specify **can add the
  > Chat app to a space** and test its features before you publish it to the
  > Marketplace."
  > — <https://developers.google.com/workspace/chat/test-interactive-features>

  This matters beyond a doc nit: the false prerequisite is **why this project
  ended up on the Workspace Add-ons runtime at all**, and that runtime is the
  reason card clicks needed the undocumented topic-as-function routing pattern.
  (Past tense deliberately: production has been **classic** since 2026-07-29 —
  see the envelope bullet below.) See
  [ADR-0001](architecture/decisions/2026-07-29-tier2-interaction-model.md) §5
  option D and §14. Do not reinstate the claim; if you are choosing a runtime
  for a new project, read that ADR first.

  **This is the first of two traps, and the second is up in step 5.** This one
  put the project on the add-ons runtime; the **create-time-only add-on toggle**
  (E2 — *"⚠ The add-on toggle is CREATE-TIME ONLY"*, in step 5 above) is why it
  could not simply be switched back, and why the escape cost a whole new GCP
  project (`chat-gateway-prod`, since **deleted 2026-07-30** → `chat-gateway-gw`,
  the live one). Together they are the entire
  story of how this project ended up on the wrong runtime and what it cost to
  leave — which is why each one points at the other rather than standing alone.

  **Visibility has a scale limit** worth knowing before you rely on it: *"up to
  five individuals, or one or more Google Groups"*, and dynamic groups are not
  supported. Ample for a single-operator homelab.

  *Known inconsistency, tracked as queue item **CG-19**:* all three IaC paths
  (`iac/gcloud-setup.sh`, `iac/gcloud-setup.ps1`, `iac/terraform/main.tf`)
  still enable `appsmarket-component.googleapis.com` and still carry a comment
  repeating the claim above. Enabling the API is harmless; the comment is not,
  and correcting it touches the IaC path so it ships separately.
- **Which envelope you get is a property of the runtime, and this project
  changed runtimes.** A classic Chat app delivers the **flat** format
  (`type` / `space` / `message` / `user`); the Workspace Add-ons runtime delivers
  `commonEventObject` + `chat.<x>Payload`. Production was add-ons until
  2026-07-29 and has been **classic** since. The gateway parses both
  (`adapters/pubsub.py`) and reports which it saw as `envelope_format`, so no
  action is needed — but if you are eyeballing a raw pull on a classic app,
  expect the flat format. This bullet used to say events arrive in the add-ons
  envelope full stop, which stopped being true the day production migrated.
- **Which tier gives which identity** — both halves were observed live on
  2026-07-29, so this is a measured trade-off, not a design note:

  | | Tier 1 (named webhooks) | Tier 2 (Chat app) |
  |---|---|---|
  | Identities available | as many as you create webhooks | exactly one — the app |
  | `sender` in Google's response | `null` | real: `{displayName: "Agent Comms", type: "BOT"}` |
  | What Chat displays | the webhook's configured name + avatar | the app's configured name + avatar |
  | Inbound events | none | Pub/Sub |

  Neither tier dominates. Tier 1 buys per-agent names at the cost of any sender
  identity in the response and any inbound path at all; tier 2 buys a real,
  attributable sender and two-way traffic at the cost of collapsing every agent
  into one name. Running both is the intended configuration, not a migration
  step.

  **Tier 1 is project-independent, and that is now empirical rather than
  asserted.** On 2026-07-30, immediately after `chat-gateway-prod` was deleted,
  all four webhook identities were re-run through the real `WebhookAdapter` and
  all four returned `delivered`. The claim at the top of this document — *"Tier 1
  (named webhooks) needs NONE of this"* — has now been tested by deleting the
  project it does not need. No tier-2 deployment change can take the notification
  path down.

### 8. What to hand back (and how)
Safe to paste in chat (non-secret): **project id, topic + subscription
names, space IDs**.
**Never paste in chat** (secrets — put them straight into the gateway
host's `.env`, mode 600, with pointers in homelab `SECRETS.md`):
- the service-account key JSON you minted (→ `GOOGLE_APPLICATION_CREDENTIALS=/path/to/it`). On the live project that is **`chat-gateway-sa-gw.json`**; **`iac/chat-gateway-sa.json` is a dead key for the deleted `chat-gateway-prod`** and must not be used or copied to the host
- every webhook URL (→ the `GOOGLE_CHAT_WEBHOOK_URL__*` vars)

Then set `GATEWAY_ENABLE_PUBSUB=1`, fill `CHAT_GATEWAY_PUBSUB_SUBSCRIPTION`,
restart, and check `/healthz` — it reports real resolvability per identity
and subscriber liveness, so a wrong env name shows up immediately.

**Also set `CHAT_GATEWAY_INTERACTION_ROUTING_TARGET`** if any tenant sends
interactive cards. The gateway publishes it to opted-in apps on
`GET /v1/identities` so no producer hardcodes it. Leave it unset and interactive
cards cannot work: `/v1/identities` will report `interaction.enabled: false`
with the reason, which is the intended failure — a producer that guesses ships
cards whose taps go nowhere. See
[ADR-0001](architecture/decisions/2026-07-29-tier2-interaction-model.md) D3.

> **Its value depends on the deployment model, and this paragraph used to give
> only the add-ons answer.** It read *"It is the **topic** path … — not the
> subscription"*, unconditionally. That was right for the runtime this project
> ran until 2026-07-29 and is not the classic answer, so an operator setting up
> the **live** project from this document was being handed the wrong shape.
>
> | Deployment | Value |
> |---|---|
> | **classic + Pub/Sub — production since 2026-07-29** | **any constant.** Classic echoes `action.function` back as `action.id` and invokes nothing. |
> | add-ons + Pub/Sub — production until 2026-07-29 | the **topic** path, `projects/<PROJECT_ID>/topics/chat-gateway-events` — ***not*** the subscription. The original caution, kept because it is the trap that made this paragraph worth writing. |
> | HTTP endpoint | the endpoint URL (add-ons) or a function name (classic) |
>
> A card still carrying the **topic path under classic is harmless**, not
> broken: the gateway discards topic-path-shaped values arriving from
> Google-native sources rather than promote `projects/…/topics/…` into an action
> name. It costs the native identity slot, so identity must then ride in
> `__cg_action__`. Neither shape is a secret — step 8 classifies topic names as
> safe to paste.

### 8a. Verifying locally — where the secrets go on *your* machine

Step 8 covers the appserver. It used to say nothing about the laptop you verify
from, and on **2026-07-29 that gap cost real credentials**: webhook URLs were
pasted into an AI-assistant chat transcript in order to run a one-off send. A
Chat webhook URL embeds `key` and `token` — it is a bearer credential for
posting into that space as that identity. Every exposed webhook had to be
deleted in Chat and recreated. There is no rotate-in-place.

Do it this way instead.

**1. Values go in `.env`, and nowhere else.**

```bash
cp .env.example .env      # .env is gitignored; .env.example never holds values
```

Paste each webhook URL into its `GOOGLE_CHAT_WEBHOOK_URL__<IDENTITY>` line, the
service-account key path into `GOOGLE_APPLICATION_CREDENTIALS`, and stop there.

**2. Drive verification through code that reads the environment.** Never through
a command-line argument, a chat message, an assistant prompt, or anything that
lands in shell history. Write a throwaway script — not a one-liner with the URL
in it:

```python
# verify_webhook.py — NOT gitignored (only .env* and *.log are). Delete it when
# you are done; see step 4.
import os
from pathlib import Path

from chat_gateway.adapters.webhook import WebhookAdapter
from chat_gateway.envelope import OutboundMessage
from chat_gateway.registry import Identity

# Minimal .env loader — stdlib only, no python-dotenv dependency.
# Inline comments are stripped only at " #" (space-hash), never at a bare "#":
# a credential may legitimately contain "#", and silently truncating one would
# produce a wrong value that fails in a confusing way instead of an obvious one.
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    os.environ.setdefault(key.strip(), value.split(" #", 1)[0].strip())

ENV_VAR = "GOOGLE_CHAT_WEBHOOK_URL__AITRADER_ALERTS"   # a NAME, never a value
assert os.environ.get(ENV_VAR), f"{ENV_VAR} is not set — put it in .env"

identity = Identity(name="probe", display="probe", mode="webhook",
                    webhook_url_env=ENV_VAR)
result = WebhookAdapter().send(
    identity, OutboundMessage(identity="probe", text="local verification probe"))
print(result)          # DeliveryResult names the identity, never the URL
```

`WebhookAdapter` already names the identity rather than the URL on failure (hard
rule #2). Hold ad-hoc probes to the same standard: they take an env-var **name**,
they never accept a URL as an argument, and they never print one.

**3. If a value is exposed anyway, treat it as burned.**

| Secret | Recovery |
|---|---|
| Webhook URL | Space → **⚙ → Apps & integrations → Webhooks → ⋮ → Delete**, then create a new webhook with the same name and avatar, then update `.env`. The old URL cannot be revoked any other way. |
| The service-account key JSON | `gcloud iam service-accounts keys delete <KEY_ID> --iam-account=chat-gateway@<PROJECT_ID>.iam.gserviceaccount.com`, then re-run the setup script to mint a new one. |
| A per-app API key | `python -m chat_gateway mint-key`, update `.env` and the consuming app. |

**4. Delete the throwaway script when you are done.** It contains no secret, but
it is one edit away from containing one.
