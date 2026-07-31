#!/usr/bin/env bash
# Idempotent Google Cloud setup for chat-gateway tier 2 (two-way Chat app).
# Usage: PROJECT_ID=your-project-id ./gcloud-setup.sh
# Prereq: gcloud auth login; project exists (or uncomment the create line).
#
# This script is project-agnostic and names no project on purpose — the id of
# the project this repo actually runs on is deliberately not repeated here; see
# docs/google-cloud-setup.md. The example above used to read
# `chat-gateway-prod`, which was DELETED on 2026-07-30, so copy-pasting it
# aimed every gcloud call below at a project that no longer exists.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID, e.g. PROJECT_ID=your-project-id}"
TOPIC="${TOPIC:-chat-gateway-events}"
SUBSCRIPTION="${SUBSCRIPTION:-chat-gateway-sub}"
SA_NAME="${SA_NAME:-chat-gateway}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
# The key filename is DERIVED FROM PROJECT_ID (CG-51, user decision 2026-07-30)
# so it can never name a project that does not exist.
#
# It used to default to a flat `chat-gateway-sa.json`, and the "already exists —
# not minting another" branch near the bottom matches on FILENAME ONLY: it
# cannot tell which project a key belongs to, so a key left over from a
# DIFFERENT project satisfied it. That was not hypothetical — the deleted
# `chat-gateway-prod` minted its key under that exact default, so a working tree
# which provisioned it still holds a `chat-gateway-sa.json` that authenticates
# to nothing, and re-running here for a fresh project printed "not minting
# another" and then emitted a .env block pointing
# GOOGLE_APPLICATION_CREDENTIALS at that dead credential.
#
# CG-19 declined to rename the default, with evidence: ANY fixed new name stops
# matching on a host that holds the old key and mints a SECOND service-account
# key, and key sprawl is worse than a documented trap. That objection is
# answered by the GUARD below, not by the derivation — when the derived name is
# absent but a sibling `<SA_NAME>-sa*.json` is present, this script refuses to
# mint, says exactly what it found, and exits non-zero. An unresolved key is
# loud; a second credential nobody knows about is not.
KEY_FILE="${KEY_FILE:-${SA_NAME}-sa-${PROJECT_ID}.json}"
# Deliberate escape hatch for that guard — set it only when you really do want
# a second key beside an existing one (several projects on one host).
ALLOW_SECOND_KEY="${ALLOW_SECOND_KEY:-0}"

# A relative KEY_FILE resolves against THIS SCRIPT'S directory, not the caller's
# working directory, so the key lands in the same place either way — matching
# the .ps1 sibling, which has always resolved against $PSScriptRoot. For the
# documented invocation (`cd iac && ./gcloud-setup.sh`) the two are the same
# directory, so this changes nothing about the usage line at the top.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Windows paths reach this script through Git Bash on the dev box, in EITHER
# separator. Fold to `/` once, up front, so everything below — the case arms,
# dirname, basename, find, the -f test — sees one shape. A POSIX filename
# containing a literal backslash is deliberately not supported.
KEY_FILE="${KEY_FILE//\\//}"
case "${KEY_FILE}" in
  /*)          KEY_PATH="${KEY_FILE}" ;;   # POSIX absolute (and a //server UNC)
  # Windows-absolute. POSIX would call `C:/x` RELATIVE, and prefixing SCRIPT_DIR
  # to it yields a path that cannot exist — measured, it aborted the run. Treat a
  # drive letter as rooted, exactly as the .ps1's IsPathRooted does (which is
  # also true for a drive-relative `C:x`, hence `?*` rather than `/*`).
  #
  # Pattern discipline, because the first draft was WRONG and passed review by
  # reasoning: `[A-Za-z]:\\*` does NOT match `C:\x` in a bash case arm — the
  # backslashes collapse and escape the `*`. Measured, not argued.
  [A-Za-z]:?*) KEY_PATH="${KEY_FILE}" ;;
  *)           KEY_PATH="${SCRIPT_DIR}/${KEY_FILE}" ;;
esac
KEY_DIR="$(dirname "${KEY_PATH}")"
# The .env block at the bottom is a HOST path (/srv/chat-gateway/...), so it
# takes the BASENAME. Concatenating a caller-supplied absolute path emitted
# `GOOGLE_APPLICATION_CREDENTIALS=/srv/chat-gateway/C:/…/key.json` (CG-35b,
# measured, not read). The .ps1 already did `Split-Path -Leaf`; this is the
# parity fix, and it is the .sh that moved.
KEY_NAME="$(basename "${KEY_PATH}")"
KEY_UNRESOLVED=0

# The principal Google Chat publishes events AS. Per Google's docs it is:
CHAT_EVENTS_PUBLISHER="serviceAccount:chat-api-push@system.gserviceaccount.com"
#
# WHICH principal actually published this project's first events is CLOSED BY
# CIRCUMSTANCE, not answered — it is not a gap to close and not a task, and this
# script no longer asks you to settle it (CG-35). Both this principal and the
# Workspace Add-ons service agent (bound further down) were bound on
# `chat-gateway-prod`; that project was DELETED on 2026-07-30, so the question
# can never be settled. See CLAUDE.md, "Verification ledger".
#
# Two reasons it was never answerable from inside this script anyway, and both
# still apply to YOUR project: GCP accepts a binding to a
# *@system.gserviceaccount.com principal WITHOUT validating that it exists, so a
# clean bind proves nothing; and "a real event landed in the subscription" does
# not attribute itself, because both principals are publishers.
#
# THE BINDING BELOW STAYS, and so does the add-ons one further down — a classic
# Chat app (what this script provisions, and what we run) needs the Chat-API
# publisher, and a project that does deploy an add-on needs the other.
#
# On the wording: this comment used to end by declaring the question a pending
# hard-rule-#3 flag. That flag was MISAPPLIED — rule #3's flag marks CODE not yet
# exercised against real Google endpoints, and an unanswerable question about
# which principal published is not that. Dropping it (CG-35, user sign-off
# 2026-07-30) is removing a misapplied flag, NOT clearing a real one, and is no
# precedent for clearing one.

echo "== project: ${PROJECT_ID}"
# gcloud projects create "${PROJECT_ID}" --name="chat-gateway"   # if not created yet
gcloud config set project "${PROJECT_ID}" >/dev/null

# appsmarket-component = the Google Workspace Marketplace SDK.
#
# ⚠ CORRECTED 2026-07-30 (CG-19) — DO NOT REINSTATE THE OLD CLAIM. This comment
# used to read "Without it the app never appears under ⚙ → Apps & integrations
# → Add apps". That is FALSE, and it is the exact sentence that put this project
# on the Workspace Add-ons runtime — which is why the correction is left here as
# a warning rather than quietly deleted. If you are choosing a runtime for a NEW
# project, read the ADR cited below BEFORE you run this script.
#
# Installability comes from Chat API → Configuration → Visibility: list your own
# address (or a Google Group) there and you can add the app to a space
# immediately, before any Marketplace publish. Two sources say so and their
# SCOPES DIFFER — do not merge them into one universal sentence, which is the
# exact mistake this comment exists to undo:
#   * classic, which is what this script provisions — "the Chat API lets you
#     share your Chat app with specific people in your Google Workspace
#     organization. The people that you specify can add the Chat app to a space
#     and test its features before you publish it to the Marketplace"
#     https://developers.google.com/workspace/chat/test-interactive-features
#   * add-ons specifically — "To deploy and test an add-on in Chat, you must use
#     the Chat API's Visibility setting. Any visibility or testing settings that
#     you've configured in the Google Workspace Marketplace SDK are ignored"
#     https://developers.google.com/workspace/add-ons/chat
# Marketplace publishing is needed only to reach people BEYOND that Visibility
# list, and it is console-only either way.
#
# The API stays enabled: it is harmless, it costs nothing, and it shortens a
# later publish. It is simply not a prerequisite for anything provisioned here.
# Full account: CG-6, which corrected the same claim in
# docs/google-cloud-setup.md, and ADR-0001 §5 option D / §14 —
# docs/architecture/decisions/2026-07-29-tier2-interaction-model.md.
echo "== enabling APIs (chat, pubsub, workspace add-ons, marketplace SDK)"
gcloud services enable chat.googleapis.com pubsub.googleapis.com \
  gsuiteaddons.googleapis.com appsmarket-component.googleapis.com

echo "== service account: ${SA_EMAIL}"
gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "${SA_NAME}" --display-name="chat-gateway"

echo "== topic: ${TOPIC}"
gcloud pubsub topics describe "${TOPIC}" >/dev/null 2>&1 || \
  gcloud pubsub topics create "${TOPIC}"

echo "== grant Chat's event publisher on the topic"
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

echo "== grant the add-ons service agent publisher on the topic (${ADDONS_PUBLISHER})"
gcloud pubsub topics add-iam-policy-binding "${TOPIC}" \
  --member="${ADDONS_PUBLISHER}" --role="roles/pubsub.publisher" >/dev/null

echo "== subscription: ${SUBSCRIPTION} (pull)"
gcloud pubsub subscriptions describe "${SUBSCRIPTION}" >/dev/null 2>&1 || \
  gcloud pubsub subscriptions create "${SUBSCRIPTION}" \
    --topic="${TOPIC}" --ack-deadline=30 --message-retention-duration=24h

echo "== grant the gateway SA subscribe"
gcloud pubsub subscriptions add-iam-policy-binding "${SUBSCRIPTION}" \
  --member="serviceAccount:${SA_EMAIL}" --role="roles/pubsub.subscriber" >/dev/null

# Filename-only check — it does not know which project the existing key belongs
# to. That is why the name is derived from PROJECT_ID and why the else-branch
# looks for predecessors. See the KEY_FILE note at the top of this script.
if [[ -f "${KEY_PATH}" ]]; then
  echo "== key file ${KEY_PATH} already exists — not minting another"
else
  # Do not silently mint a SECOND credential (CG-51). A sibling key under the
  # same naming convention almost always means "the key you want is already
  # here under another name" — a rename this script must not guess at.
  # `|| true` and the -d guard are both load-bearing under `set -euo pipefail`:
  # a find over a missing directory exits non-zero, pipefail propagates that
  # through the pipeline, and the failed assignment then kills the whole run.
  # Measured — that is exactly how the first draft of this aborted.
  PREDECESSORS=""
  if [[ -d "${KEY_DIR}" ]]; then
    PREDECESSORS="$(find "${KEY_DIR}" -maxdepth 1 -type f -name "${SA_NAME}-sa*.json" 2>/dev/null \
      | sed 's#.*/##' | sort || true)"
  fi
  if [[ -n "${PREDECESSORS}" && "${ALLOW_SECOND_KEY}" != "1" ]]; then
    echo "!! NOT minting a key. ${KEY_NAME} is absent, but ${KEY_DIR} already holds:"
    while IFS= read -r existing; do
      [[ -n "${existing}" ]] && echo "!!   ${existing}"
    done <<< "${PREDECESSORS}"
    echo "!! Minting now would leave two service-account keys on this host and no"
    echo "!! record of which one is live. Resolve it yourself, then re-run:"
    echo "!!   * reuse an existing key      -> KEY_FILE=<that filename>"
    echo "!!   * it belongs to a dead/other project -> move or delete it"
    echo "!!   * you really do want another -> ALLOW_SECOND_KEY=1 (deliberate)"
    KEY_UNRESOLVED=1
  else
    echo "== minting SA key -> ${KEY_PATH} (keep off-repo; chmod 600; SECRETS.md pointer)"
    gcloud iam service-accounts keys create "${KEY_PATH}" --iam-account="${SA_EMAIL}"
    chmod 600 "${KEY_PATH}"
  fi
fi

cat <<ENV

== done. Console-only steps remain (docs/google-cloud-setup.md §5–7):
   Chat API Configuration page (app name/avatar, Pub/Sub topic), spaces, webhooks.

== .env block for the gateway host:
GATEWAY_ENABLE_PUBSUB=1
GOOGLE_APPLICATION_CREDENTIALS=/srv/chat-gateway/${KEY_NAME}
CHAT_GATEWAY_PUBSUB_SUBSCRIPTION=projects/${PROJECT_ID}/subscriptions/${SUBSCRIPTION}
ENV

if [[ "${KEY_UNRESOLVED}" -eq 1 ]]; then
  echo
  echo "!! Everything above is provisioned, but NO KEY WAS CREATED: the"
  echo "!! GOOGLE_APPLICATION_CREDENTIALS line names ${KEY_NAME}, which does not"
  echo "!! exist. Exiting non-zero so this cannot pass unnoticed — see the !!"
  echo "!! block above. Re-running once you have resolved it is a no-op for"
  echo "!! everything else."
  exit 3
fi
