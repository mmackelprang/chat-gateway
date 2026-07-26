# Google Cloud setup — step by step

What you create, in order, with what can be scripted vs. what is console-only.
**Tier 1 (named webhooks) needs NONE of this** — only tier 2 (the two-way
Chat app + Pub/Sub events) does. Everything here is doable from any browser;
nothing requires being on the homelab network.

## What can be automated

- [`../iac/gcloud-setup.sh`](../iac/gcloud-setup.sh) — idempotent gcloud CLI
  script: project services, service account, topic, subscription, IAM, key.
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
Link a billing account if prompted (Chat API and Pub/Sub at this volume sit
in the free tier, but some APIs refuse to enable without billing attached).

### 2–4. APIs, service account, Pub/Sub (scripted)
```bash
cd iac && PROJECT_ID=chat-gateway-prod ./gcloud-setup.sh
```
This enables `chat.googleapis.com` + `pubsub.googleapis.com`, creates the
`chat-gateway` service account, the `chat-gateway-events` topic, the
`chat-gateway-sub` pull subscription, grants Chat's publisher account write
on the topic and the SA subscribe on the subscription, writes
`chat-gateway-sa.json` (chmod 600), and prints the `.env` block to copy.

> ⚠ One VERIFY item (flagged in the script): the Google-side identity that
> publishes Chat events (`chat-api-push@system.gserviceaccount.com`) is per
> Google's docs at time of writing — confirm the exact principal on the
> Chat API "Connection settings" page when you do step 5; the console names
> it there if it differs.

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
