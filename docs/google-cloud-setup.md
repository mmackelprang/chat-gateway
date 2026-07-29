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

### Also easy to miss in steps 5–7

- Steps 6 and 7 happen in **chat.google.com**, not the Cloud Console. Looking
  for them in the Console is a dead end.
- The app will not appear under **⚙ → Apps & integrations → Add apps** until
  the **Google Workspace Marketplace SDK**
  (`appsmarket-component.googleapis.com`) is enabled *and* the app is
  published. Enabling the Chat API alone is not enough.
- Events arrive in the **Workspace Add-ons envelope** (`commonEventObject` +
  `chat.messagePayload`), not the classic flat format. The gateway parses both
  (`adapters/pubsub.py`), so no action is needed — but if you are eyeballing a
  raw pull, that is what you should expect to see.

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
