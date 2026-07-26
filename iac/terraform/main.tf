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
