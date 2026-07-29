# chat-gateway tier-2 infrastructure. Equivalent to ../gcloud-setup.sh.
#
# Deliberately NOT managed here: the service-account KEY (a key created by
# Terraform lands in the state file — mint it with gcloud instead) and the
# Chat API Configuration page (no API/Terraform surface exists for it; see
# docs/google-cloud-setup.md §5).
#
# Usage:
#   terraform init
#   terraform apply -var project_id=chat-gateway-prod

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

# The Google Workspace Marketplace SDK. Without it the app never appears under
# ⚙ → Apps & integrations → Add apps (docs/google-cloud-setup.md §6).
# *Publishing* the app has no IaC surface and stays console-only.
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
