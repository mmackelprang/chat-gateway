# Chat-room avatars

Circular avatars for Google Chat incoming webhooks and Chat apps. Every app
registered with the gateway can pick one, so a shared space reads at a glance.

![preview](preview.png)

## Using one

In the Chat space: **Apps & integrations → Webhooks → Add webhook**, then paste
the PNG URL below into **Avatar URL**. The name and avatar are fixed when the
webhook is created; changing them later means a new webhook (see
`docs/registering-an-app.md`).

URLs serve from `main` of this public repository; they work once this
directory is merged.

| | Name | Use for | Avatar URL |
|---|---|---|---|
| <img src="png/alert.png" width="40"> | Alert | Loud lane: things that need action now | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/alert.png` |
| <img src="png/warning.png" width="40"> | Warning | Degraded, watch it | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/warning.png` |
| <img src="png/info.png" width="40"> | Info | Quiet lane: status, digests, no action | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/info.png` |
| <img src="png/resolved.png" width="40"> | Resolved | All-clear threads and closed incidents | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/resolved.png` |
| <img src="png/heartbeat.png" width="40"> | Heartbeat | Dead-man checks and liveness | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/heartbeat.png` |
| <img src="png/report.png" width="40"> | Report | Scheduled reports and summaries | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/report.png` |
| <img src="png/trading.png" width="40"> | Trading | Markets, positions, fills | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/trading.png` |
| <img src="png/jobs.png" width="40"> | Jobs | Job search, applications, careers | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/jobs.png` |
| <img src="png/agent.png" width="40"> | Agent | AI agents and automated assistants | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/agent.png` |
| <img src="png/deploy.png" width="40"> | Deploy | Releases, rollouts, deploys | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/deploy.png` |
| <img src="png/build.png" width="40"> | Build | CI, builds, jobs and pipelines | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/build.png` |
| <img src="png/security.png" width="40"> | Security | Auth, access, secrets, audits | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/security.png` |
| <img src="png/database.png" width="40"> | Database | Data, storage, backups | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/database.png` |
| <img src="png/calendar.png" width="40"> | Calendar | Schedules, reminders, due dates | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/calendar.png` |
| <img src="png/home.png" width="40"> | Home | Family, household, home automation | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/home.png` |
| <img src="png/messages.png" width="40"> | Messages | Conversations, inbound replies, chat bridges | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/messages.png` |
| <img src="png/finance.png" width="40"> | Finance | Money, billing, budgets, P&L | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/finance.png` |
| <img src="png/phone.png" width="40"> | Phone | Telephony, calls, voicemail | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/phone.png` |
| <img src="png/server.png" width="40"> | Server | Infrastructure, hosts, homelab | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/server.png` |
| <img src="png/search.png" width="40"> | Search | Research, monitoring, discovery | `https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/search.png` |

## Changing or adding one

Edit the `ICONS` table in `build.py` and run `python assets/avatars/build.py`.
It rewrites `svg/`, `png/`, `preview.png` and this README. It needs PyMuPDF
and Pillow, which are build-time tools only. Keep glyphs within about 70px of
the centre, because Chat crops avatars to a circle.
