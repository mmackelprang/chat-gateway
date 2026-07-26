#!/usr/bin/env bash
# Idempotent Google Cloud setup for chat-gateway tier 2 (two-way Chat app).
# Usage: PROJECT_ID=chat-gateway-prod ./gcloud-setup.sh
# Prereq: gcloud auth login; project exists (or uncomment the create line).
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID, e.g. PROJECT_ID=chat-gateway-prod}"
TOPIC="${TOPIC:-chat-gateway-events}"
SUBSCRIPTION="${SUBSCRIPTION:-chat-gateway-sub}"
SA_NAME="${SA_NAME:-chat-gateway}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
KEY_FILE="${KEY_FILE:-chat-gateway-sa.json}"

# ⚠ VERIFY on the Chat API Configuration page when you wire the topic:
# the principal Google Chat publishes events AS. Per current docs it is:
CHAT_EVENTS_PUBLISHER="serviceAccount:chat-api-push@system.gserviceaccount.com"

echo "== project: ${PROJECT_ID}"
# gcloud projects create "${PROJECT_ID}" --name="chat-gateway"   # if not created yet
gcloud config set project "${PROJECT_ID}" >/dev/null

echo "== enabling APIs (chat, pubsub)"
gcloud services enable chat.googleapis.com pubsub.googleapis.com

echo "== service account: ${SA_EMAIL}"
gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "${SA_NAME}" --display-name="chat-gateway"

echo "== topic: ${TOPIC}"
gcloud pubsub topics describe "${TOPIC}" >/dev/null 2>&1 || \
  gcloud pubsub topics create "${TOPIC}"

echo "== grant Chat's event publisher on the topic (VERIFY principal — see comment)"
gcloud pubsub topics add-iam-policy-binding "${TOPIC}" \
  --member="${CHAT_EVENTS_PUBLISHER}" --role="roles/pubsub.publisher" >/dev/null

echo "== subscription: ${SUBSCRIPTION} (pull)"
gcloud pubsub subscriptions describe "${SUBSCRIPTION}" >/dev/null 2>&1 || \
  gcloud pubsub subscriptions create "${SUBSCRIPTION}" \
    --topic="${TOPIC}" --ack-deadline=30 --message-retention-duration=24h

echo "== grant the gateway SA subscribe"
gcloud pubsub subscriptions add-iam-policy-binding "${SUBSCRIPTION}" \
  --member="serviceAccount:${SA_EMAIL}" --role="roles/pubsub.subscriber" >/dev/null

if [[ -f "${KEY_FILE}" ]]; then
  echo "== key file ${KEY_FILE} already exists — not minting another"
else
  echo "== minting SA key -> ${KEY_FILE} (keep off-repo; chmod 600; SECRETS.md pointer)"
  gcloud iam service-accounts keys create "${KEY_FILE}" --iam-account="${SA_EMAIL}"
  chmod 600 "${KEY_FILE}"
fi

cat <<ENV

== done. Console-only steps remain (docs/google-cloud-setup.md §5–7):
   Chat API Configuration page (app name/avatar, Pub/Sub topic), spaces, webhooks.

== .env block for the gateway host:
GATEWAY_ENABLE_PUBSUB=1
GOOGLE_APPLICATION_CREDENTIALS=/srv/chat-gateway/${KEY_FILE}
CHAT_GATEWAY_PUBSUB_SUBSCRIPTION=projects/${PROJECT_ID}/subscriptions/${SUBSCRIPTION}
ENV
