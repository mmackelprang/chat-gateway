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
gcloud projects create chat-gateway-prod --name="chat-gateway"
gcloud config set project chat-gateway-prod
```
Chat API and Pub/Sub at this volume sit in the free tier. Billing turned out
**not** to be required for `chat-gateway-prod`: both `chat.googleapis.com` and
`pubsub.googleapis.com` enabled successfully with `billingEnabled: false`
(observed 2026-07-28). That is the result for this project, not a guarantee —
if an `enable` call is rejected for billing, link a billing account and retry.

### 2–4. APIs, service account, Pub/Sub (scripted)

> ✅ **Provisioned for `chat-gateway-prod`** — steps 2–4 ran 2026-07-28: APIs,
> service account, topic, subscription, the topic-publisher and
> subscription-subscriber bindings, and the SA key.
>
> ⚠ **That run was incomplete.** It predated the Workspace Add-ons service
> agent, which did not exist and was therefore never bound — the failure
> documented below. The agent and its publisher binding were added by hand on
> 2026-07-29 and are now part of all three IaC paths, so a re-run is a safe
> no-op. The lesson worth keeping: **"the script exited 0" was not evidence the
> project was complete.**

POSIX:
```bash
cd iac && PROJECT_ID=chat-gateway-prod ./gcloud-setup.sh
```
Windows (PowerShell — see "What can be automated" for why):
```powershell
.\iac\gcloud-setup.ps1 -ProjectId chat-gateway-prod
```
This enables `chat.googleapis.com` + `pubsub.googleapis.com` +
`gsuiteaddons.googleapis.com`, creates the `chat-gateway` service account, the
`chat-gateway-events` topic, the `chat-gateway-sub` pull subscription, grants
**both** publisher principals write on the topic (see below) and the SA
subscribe on the subscription, writes `chat-gateway-sa.json` (owner-only:
`chmod 600` on POSIX, `icacls` on Windows), and prints the `.env` block to copy.

> ⚠ **Publisher principals — what is and is not proven (updated 2026-07-29).**
> Two principals are now granted `roles/pubsub.publisher` on the topic:
> `chat-api-push@system.gserviceaccount.com` (per Google's docs) and the
> Workspace Add-ons service agent
> `service-<PROJECT_NUMBER>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com`.
> A real event **did** reach `chat-gateway-sub` on 2026-07-29, immediately
> after the add-ons service agent was created and bound. But because both
> principals are bound, **we cannot prove which one delivered it** — the
> correlation is strong, the evidence is circumstantial. Do not record this as
> a clean verification of either principal.
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
- **App name:** `Agent Comms` (or your pick — this is the tier-2 sender
  identity users see), avatar URL, description.
- **Interactive features:** enable; check *Receive 1:1 messages* and *Join
  spaces and group conversations*.
- **Connection settings:** **Cloud Pub/Sub** → topic
  `projects/chat-gateway-prod/topics/chat-gateway-events`.
- **Visibility:** make available to your domain.
- Save.

### 6. Spaces + app membership
For each project/app that gets a space: create the space in Chat, then
**⚙ → Apps & integrations → Add apps** → add your Chat app. Grab each
**space ID** (open the space in a browser — the URL ends
`/room/AAAA...` → the ID is `spaces/AAAA...`).

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
  is on the Workspace Add-ons runtime at all**, and that runtime is the reason
  card clicks need the undocumented topic-as-function routing pattern. See
  [ADR-0001](architecture/decisions/2026-07-29-tier2-interaction-model.md) §5
  option D and §14. Do not reinstate the claim; if you are choosing a runtime
  for a new project, read that ADR first.

  **Visibility has a scale limit** worth knowing before you rely on it: *"up to
  five individuals, or one or more Google Groups"*, and dynamic groups are not
  supported. Ample for a single-operator homelab.

  *Known inconsistency, tracked as queue item **CG-19**:* all three IaC paths
  (`iac/gcloud-setup.sh`, `iac/gcloud-setup.ps1`, `iac/terraform/main.tf`)
  still enable `appsmarket-component.googleapis.com` and still carry a comment
  repeating the claim above. Enabling the API is harmless; the comment is not,
  and correcting it touches the IaC path so it ships separately.
- Events arrive in the **Workspace Add-ons envelope** (`commonEventObject` +
  `chat.messagePayload`), not the classic flat format. The gateway parses both
  (`adapters/pubsub.py`), so no action is needed — but if you are eyeballing a
  raw pull, that is what you should expect to see.
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

### 8. What to hand back (and how)
Safe to paste in chat (non-secret): **project id, topic + subscription
names, space IDs**.
**Never paste in chat** (secrets — put them straight into the gateway
host's `.env`, mode 600, with pointers in homelab `SECRETS.md`):
- `chat-gateway-sa.json` (→ `GOOGLE_APPLICATION_CREDENTIALS=/path/to/it`)
- every webhook URL (→ the `GOOGLE_CHAT_WEBHOOK_URL__*` vars)

Then set `GATEWAY_ENABLE_PUBSUB=1`, fill `CHAT_GATEWAY_PUBSUB_SUBSCRIPTION`,
restart, and check `/healthz` — it reports real resolvability per identity
and subscriber liveness, so a wrong env name shows up immediately.

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
| `chat-gateway-sa.json` | `gcloud iam service-accounts keys delete <KEY_ID> --iam-account=chat-gateway@<PROJECT_ID>.iam.gserviceaccount.com`, then re-run the setup script to mint a new one. |
| A per-app API key | `python -m chat_gateway mint-key`, update `.env` and the consuming app. |

**4. Delete the throwaway script when you are done.** It contains no secret, but
it is one edit away from containing one.
