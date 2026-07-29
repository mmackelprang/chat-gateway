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

echo "== enabling APIs (chat, pubsub, workspace add-ons)"
gcloud services enable chat.googleapis.com pubsub.googleapis.com gsuiteaddons.googleapis.com

echo "== service account: ${SA_EMAIL}"
gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "${SA_NAME}" --display-name="chat-gateway"

echo "== topic: ${TOPIC}"
gcloud pubsub topics describe "${TOPIC}" >/dev/null 2>&1 || \
  gcloud pubsub topics create "${TOPIC}"

echo "== grant Chat's event publisher on the topic (VERIFY principal — see comment)"
gcloud pubsub topics add-iam-policy-binding "${TOPIC}" \
  --member="${CHAT_EVENTS_PUBLISHER}" --role="roles/pubsub.publisher" >/dev/null

# ---------------------------------------------------------------------------
# The Workspace Add-ons runtime publishes as a PER-PROJECT service agent that
# DOES NOT EXIST until you create it. Omitting this is the failure that cost an
# hour on 2026-07-29: Chat shows "<app> is not responding", the add-ons metric
# logs code 13, and NOTHING ever reaches the topic. See
# docs/google-cloud-setup.md for the full failure signature.
#
# Honest caveat: after applying this, BOTH this principal and
# chat-api-push@system.gserviceaccount.com are bound, so we cannot prove which
# one actually delivered the first event. The correlation is strong but the
# evidence is circumstantial.
#
# `gcloud beta` needs the beta component; gcloud offers to install it on first
# use. Re-running is a no-op — the command returns the existing identity.
# ---------------------------------------------------------------------------
echo "== ensure the Workspace Add-ons service agent exists"
gcloud beta services identity create --service=gsuiteaddons.googleapis.com \
  --project="${PROJECT_ID}" >/dev/null

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
# A blank project number would bind `service-@gcp-sa-...`, which GCP may accept
# without validating — reproducing exactly the false confidence the
# chat-api-push comment above already warns about. Fail instead.
: "${PROJECT_NUMBER:?could not resolve the project number for ${PROJECT_ID} — cannot bind the add-ons service agent}"
ADDONS_PUBLISHER="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"

echo "== grant the add-ons service agent publisher on the topic"
gcloud pubsub topics add-iam-policy-binding "${TOPIC}" \
  --member="${ADDONS_PUBLISHER}" --role="roles/pubsub.publisher" >/dev/null

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
