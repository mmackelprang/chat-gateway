# chat-gateway tier-2 infrastructure. Equivalent to ../gcloud-setup.sh.
#
# Deliberately NOT managed here: the service-account KEY (a key created by
# Terraform lands in the state file — mint it with gcloud instead) and the
# Chat API Configuration page (no API/Terraform surface exists for it; see
# docs/google-cloud-setup.md §5).
#
# Usage:
#   terraform init
#   terraform apply -var project_id=your-project-id
#
# This config is project-agnostic and names no project on purpose — the id of
# the project this repo actually runs on is deliberately not repeated here; see
# docs/google-cloud-setup.md. The example above used to read
# `chat-gateway-prod`, which was DELETED on 2026-07-30, so copy-pasting it
# aimed the whole apply at a project that no longer exists.

terraform {
  required_providers {
    google = { source = "hashicorp/google", version = ">= 5.0" }
    # google_project_service_identity is beta-only.
    google-beta = { source = "hashicorp/google-beta", version = ">= 5.0" }
  }
}

variable "project_id" { type = string }
variable "topic" {
  type    = string
  default = "chat-gateway-events"
}
variable "subscription" {
  type    = string
  default = "chat-gateway-sub"
}

# ⚠ VERIFY on the Chat API Connection-settings page: the principal Google
# Chat publishes events as. Current documented value:
variable "chat_events_publisher" {
  type    = string
  default = "serviceAccount:chat-api-push@system.gserviceaccount.com"
}

provider "google" {
  project = var.project_id
}

provider "google-beta" {
  project = var.project_id
}

resource "google_project_service" "chat" {
  service            = "chat.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "pubsub" {
  service            = "pubsub.googleapis.com"
  disable_on_destroy = false
}

resource "google_service_account" "gateway" {
  account_id   = "chat-gateway"
  display_name = "chat-gateway"
}

resource "google_pubsub_topic" "events" {
  name       = var.topic
  depends_on = [google_project_service.pubsub]
}

resource "google_pubsub_topic_iam_member" "chat_publishes" {
  topic  = google_pubsub_topic.events.name
  role   = "roles/pubsub.publisher"
  member = var.chat_events_publisher
}

resource "google_project_service" "gsuiteaddons" {
  service            = "gsuiteaddons.googleapis.com"
  disable_on_destroy = false
}

# The Google Workspace Marketplace SDK.
#
# ⚠ CORRECTED 2026-07-30 (CG-19) — DO NOT REINSTATE THE OLD CLAIM. This comment
# used to read "Without it the app never appears under ⚙ → Apps & integrations →
# Add apps". That is FALSE, and it is the exact sentence that put this project on
# the Workspace Add-ons runtime — which is why the correction is left here as a
# warning rather than quietly deleted. If you are choosing a runtime for a NEW
# project, read the ADR cited below BEFORE you apply this.
#
# Installability comes from Chat API → Configuration → Visibility: list your own
# address (or a Google Group) there and you can add the app to a space
# immediately, before any Marketplace publish. Two sources say so and their
# SCOPES DIFFER — do not merge them into one universal sentence, which is the
# exact mistake this comment exists to undo:
#   * classic, which is what this config provisions — "the Chat API lets you
#     share your Chat app with specific people in your Google Workspace
#     organization. The people that you specify can add the Chat app to a space
#     and test its features before you publish it to the Marketplace"
#     https://developers.google.com/workspace/chat/test-interactive-features
#   * add-ons specifically — "To deploy and test an add-on in Chat, you must use
#     the Chat API's Visibility setting. Any visibility or testing settings that
#     you've configured in the Google Workspace Marketplace SDK are ignored"
#     https://developers.google.com/workspace/add-ons/chat
# Marketplace publishing is needed only to reach people BEYOND that Visibility
# list, has no IaC surface, and stays console-only either way.
#
# The API stays enabled: it is harmless, it costs nothing, and it shortens a
# later publish. It is simply not a prerequisite for anything provisioned here.
# Full account: CG-6, which corrected the same claim in
# docs/google-cloud-setup.md, and ADR-0001 §5 option D / §14 —
# docs/architecture/decisions/2026-07-29-tier2-interaction-model.md.
resource "google_project_service" "appsmarket" {
  service            = "appsmarket-component.googleapis.com"
  disable_on_destroy = false
}

# The Workspace Add-ons runtime publishes as a per-project service agent that
# does not exist until it is created. Missing it = the 2026-07-29 field
# failure: Chat reports "<app> is not responding", the add-ons metric logs
# code 13, and nothing reaches the topic. Full signature in
# docs/google-cloud-setup.md.
#
# Honest caveat: with both this principal and chat_events_publisher bound, we
# cannot prove which one delivered the first event — strong correlation,
# circumstantial evidence.
resource "google_project_service_identity" "gsuiteaddons" {
  provider   = google-beta
  service    = "gsuiteaddons.googleapis.com"
  depends_on = [google_project_service.gsuiteaddons]
}

# A freshly minted service agent can take a few seconds to become
# IAM-resolvable, so a first `apply` may fail here with
# "Error 400: ... does not exist". Re-running apply resolves it; the gcloud
# scripts do not hit this because the identity call blocks until it returns.
resource "google_pubsub_topic_iam_member" "addons_publishes" {
  topic  = google_pubsub_topic.events.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_project_service_identity.gsuiteaddons.email}"
}

resource "google_pubsub_subscription" "gateway" {
  name                       = var.subscription
  topic                      = google_pubsub_topic.events.id
  ack_deadline_seconds       = 30
  message_retention_duration = "86400s"
}

resource "google_pubsub_subscription_iam_member" "gateway_subscribes" {
  subscription = google_pubsub_subscription.gateway.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.gateway.email}"
}

output "service_account_email" { value = google_service_account.gateway.email }
output "subscription_path" { value = google_pubsub_subscription.gateway.id }
output "next_steps" {
  value = "Mint the SA key with gcloud (not TF), then do the console-only Chat API Configuration page — docs/google-cloud-setup.md §5-7."
}
