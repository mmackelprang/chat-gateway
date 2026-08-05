# Implementation plan — live-verification follow-ups (CG-3 … CG-12)

**Spec:** [`../specs/2026-07-29-live-verification-followups-design.md`](../specs/2026-07-29-live-verification-followups-design.md)
**Baseline:** `python -m pytest -q` → **70 passed** (Windows dev box: `python`,
not `python3` — its msys `python3` has no pytest).

Six parts are executable now, one per PR, in queue order. Four items are blocked
and carry no plan text beyond their gate — CG-9 (human re-capture), CG-10 (ADR),
CG-11 (ADR wording — plan written, shipping gated), CG-12 (user decision).

Every part starts by branching from an up-to-date `main` and ends by updating
`docs/BUILDER_QUEUE.md`. Hard rules 1, 2, 3, 5 and 6 govern all of it; rule 6 in
particular is untouched by every part here — `aitrader` stays `allow_inbound:
false` and locked out of every inbound path.

---

# Part A — CG-6: documentation gaps

Placed first: it is the credential-exposure fix. Docs only, no source, no tests.

Branch: `docs/local-verification-and-identity-tiers`

### Task A.1 — `docs/google-cloud-setup.md`, step 7: name the webhook

Replace the step 7 block:

```markdown
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
```

### Task A.2 — `docs/google-cloud-setup.md`, step 8: the local `.env` flow

Insert immediately after the existing step 8 block, before its closing
`/healthz` paragraph is left intact:

```markdown
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
# verify_webhook.py  (gitignored by the .env.* / *.log rules? NO — delete it after)
import os
from dotenv import load_dotenv
from chat_gateway.adapters.webhook import WebhookAdapter
from chat_gateway.envelope import OutboundMessage
from chat_gateway.registry import Identity

load_dotenv()
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
| The service-account key JSON (⚠ **filename varies by project — derive it, do not copy this row's**) | `gcloud iam service-accounts keys delete <KEY_ID> --iam-account=chat-gateway@<PROJECT_ID>.iam.gserviceaccount.com`, then re-run the setup script to mint a new one. |
| A per-app API key | `python -m chat_gateway mint-key`, update `.env` and the consuming app. |

**4. Delete the throwaway script when you are done.** It contains no secret, but
it is one edit away from containing one.
```

⚠ **The key row above named the literal filename `chat-gateway-sa.json` until
2026-08-05 — routed here by CG-79 and corrected rather than left.** That filename
belongs to the **deleted** `chat-gateway-prod` project; the live key is
`chat-gateway-sa-gw.json`, and **the file the old name pointed at was deleted by
the user on 2026-08-05**. A rotation recipe keyed on a dead project's filename is
worse than one that names no file at all: it would have an operator delete a key
id that authenticates to nothing while the live key stays exposed. CG-51 made both
setup scripts **derive** `KEY_FILE` from `PROJECT_ID` for exactly this reason, so
the recipe now points at the mechanism rather than at a name. ⚠ **The scripts still
default that variable to the dead filename**, so re-running setup can recreate it
— confirm which key you hold by its own `project_id`, never by its name.

### Task A.3 — `docs/google-cloud-setup.md`: the tier trade-off

Append to the "Also easy to miss in steps 5–7" section:

```markdown
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
```

### Task A.4 — `docs/integration-guide.md`: the same trade-off, reader-facing

Append to the "Identities + health" section:

```markdown
### Which identity your message shows as

- **Tier 1 (`mode: webhook`)** — the webhook's own configured display name and
  avatar. Google returns `sender: null` for these sends; Chat substitutes the
  webhook's name, and a webhook created without one renders as **"Unknown
  User"**. One webhook per identity, as many as you like.
- **Tier 2 (`mode: app`)** — the Chat app itself, one sender for every
  identity routed through it (`Agent Comms` on this deployment, `type: BOT`).
  Per-agent flavour has to ride in the message content — a card header, a
  prefix — because the sender is fixed.

Both verified live 2026-07-29.
```

### Task A.5 — `.env.example`: point at §8a

Replace the header comment:

```bash
# Copy to .env (gitignored). Never commit real values; on the appserver these
# live in /srv/chat-gateway/.env (mode 600) with pointers in homelab SECRETS.md.
#
# LOCAL verification uses this same file — see docs/google-cloud-setup.md §8a.
# A webhook URL embeds key+token and IS a credential: it belongs in .env and
# nowhere else. Never a command-line argument, a chat message, an AI-assistant
# prompt, or a shell-history line. (2026-07-29: that mistake burned every
# webhook in the project and each one had to be recreated by hand.)
```

### Task A.6 — verify and close out

```bash
python -m pytest -q          # must still be 70 passed — this part touches no source
```

Mark CG-6 shipped in `docs/BUILDER_QUEUE.md`.

---

# Part B — CG-4: clear the webhook flag, drop the redundant threadKey mechanism

Branch: `fix/webhook-threadkey-single-mechanism`

### Task B.1 — `src/chat_gateway/adapters/webhook.py` module docstring

Replace lines 1–13 entirely:

```python
"""Tier-1 delivery: Google Chat incoming webhooks (one-way, named identity).

The webhook itself carries the identity: display name and avatar are fixed at
webhook creation in the Chat UI, and Chat renders THAT name. Google returns
`sender: null` for a webhook send — there is no sender object — so a webhook
created without a name shows in the space as "Unknown User". This adapter only
builds the message body and posts it.

Verified live 2026-07-29 through THIS class against a real webhook (not a
reimplementation): plain-text send -> HTTP 200, `delivered`; a Cards v2 payload
passed through unchanged -> HTTP 200, and rendering confirmed in the space by
the user. Scope of that clear: the success path. The non-200 branch and the
httpx.HTTPError branch below have never been exercised against Google.

Threading — the experiment, and exactly what it proved. Two messages per
variant, distinct thread keys, using `thread.name` from Google's response as
the objective signal:

    threadKey query param + body thread.threadKey  ->  THREADED
    threadKey query param only                     ->  THREADED
    body thread.threadKey only                     ->  THREADED

The two mechanisms are redundant, so we now send exactly one: the body form.
Reason: `thread.threadKey` in the body is the `spaces.messages.create` request
shape, which is what chat_api.py already sends — one threading idiom across
both adapters means a future threading bug is one thing to reason about, not
two. It also means one less parameter spliced into a URL that embeds key+token.

⚠ WHAT THIS EXPERIMENT DID NOT ESTABLISH. All three variants above also carried
`messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD` in the query. The
proven statement is precisely:

    given messageReplyOption is present, either threadKey location suffices.

Whether `messageReplyOption` is required AT ALL was never isolated — the
fourth variant (threadKey with no messageReplyOption) was not run. Do not read
this result as license to drop messageReplyOption.
"""
```

### Task B.2 — `build_params`

Replace the function:

```python
def build_params(message: OutboundMessage) -> dict:
    """Query parameters. `messageReplyOption` only, as of 2026-07-29.

    The `threadKey` query parameter used to be sent here as well; it was proven
    redundant with the body's `thread.threadKey` (see the module docstring) and
    dropped. `messageReplyOption` stays because its necessity was never
    isolated — every variant of that experiment included it.
    """
    if not message.thread_key:
        return {}
    return {"messageReplyOption": "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"}
```

`build_payload` is unchanged — it already emits `thread: {"threadKey": …}`,
which is now the sole mechanism.

`WebhookAdapter.send` is unchanged. Its `copy_merge_params` machinery and the
comment explaining it stay correct and still necessary: `messageReplyOption`
must be merged into the URL's existing query without clobbering `key`+`token`.

### Task B.3 — update the two affected tests

In `tests/test_adapters.py`, replace `test_webhook_payload_and_params`:

```python
def test_webhook_payload_and_params():
    """One threading mechanism, not two (verified redundant 2026-07-29).

    The body carries thread affinity; the query carries only
    messageReplyOption, whose necessity was never isolated and which therefore
    stays.
    """
    payload = build_payload(MSG)
    assert payload["text"] == "Review needed"
    assert payload["cardsV2"][0]["cardId"] == "c1"
    assert payload["thread"] == {"threadKey": "review-PC-12"}
    params = build_params(MSG)
    assert params == {"messageReplyOption": "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"}
    assert "threadKey" not in params          # dropped: redundant with the body
    bare = OutboundMessage(identity="x", text="hi")
    assert "thread" not in build_payload(bare) and build_params(bare) == {}
```

and in `test_webhook_send_success_and_error`, replace the URL assertion line:

```python
    assert result.status == "delivered" and result.mode == "webhook"
    assert "key=SECRET" in seen["url"]                    # existing query survives
    assert "threadKey=" not in seen["url"]                # dropped 2026-07-29
    assert "messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD" in seen["url"]
    assert seen["body"]["thread"] == {"threadKey": "review-PC-12"}   # the sole mechanism
    assert seen["body"]["text"] == "Review needed"
```

### Task B.4 — `CLAUDE.md` status block

In the ⚠ LIVE-UNVERIFIED list, replace:

```
  - Chat API **send** and webhook **send** (including the threadKey
    param-vs-body question) — unchanged, still unverified.
```

with:

```
  - Webhook **send** — ⚠ flag CLEARED 2026-07-29. Verified through the real
    `WebhookAdapter`: text delivered, Cards v2 passed through and confirmed
    rendering. The threadKey param-vs-body question is settled — both work, we
    keep the body form. Not covered: the non-200 and transport-error branches.
    Whether `messageReplyOption` is required at all was NOT isolated.
  - Chat API **send** — see CG-5.
```

### Task B.5 — verify and close out

```bash
python -m pytest -q          # 70 passed
```

Mark CG-4 shipped in `docs/BUILDER_QUEUE.md`.

---

# Part C — CG-5: split the `chat_api.py` flag

Branch: `docs/chat-api-flag-split`. Docstrings only — no behaviour changes, no
test changes, the suite must stay at 70.

### Task C.1 — module docstring

Replace lines 1–14 of `src/chat_gateway/adapters/chat_api.py`:

```python
"""Tier-2 delivery: the Google Chat API (two-way Chat app identity).

Sends `spaces.messages.create` as the gateway's Chat app, authenticated with
the service account from the Google Cloud setup (docs/google-cloud-setup.md).

Identity at this tier: the app is ONE sender, and a real one — verified live
2026-07-29, the response carried
`sender: {"displayName": "Agent Comms", "type": "BOT"}`. That is the trade-off
against tier 1, which gives as many named identities as you create webhooks and
no sender object at all. Per-agent flavour therefore rides in the message
content (cards can carry per-PM headers) unless per-identity apps are ever
justified.

⚠ Verification status is PER METHOD here, not per module — the halves of this
file have different evidence behind them. Read each docstring; do not
generalize from one to another. Keep this adapter the only place Chat API calls
exist (hard rule #3).
"""
```

### Task C.2 — `GoogleServiceAccountTokens`

```python
class GoogleServiceAccountTokens:
    """Standard google-auth service-account flow. Lazy imports so offline
    tests never need google-auth's transport dependencies.

    Verified live 2026-07-29: this provider minted the token that
    `ChatApiAdapter.send()` used to post as the app. ⚠ flag cleared.
    """
```

### Task C.3 — `ChatApiAdapter.send`

Insert as the method's docstring, above `if not identity.space:`:

```python
    def send(self, identity: Identity, message: OutboundMessage) -> DeliveryResult:
        """Post a message as the Chat app.

        ⚠ flag CLEARED 2026-07-29. Verified through THIS class and the real
        GoogleServiceAccountTokens provider (not a reimplementation): a text
        message and a Cards v2 card both posted as the app, and the response
        carried `sender: {"displayName": "Agent Comms", "type": "BOT"}`.

        Scope of that clear — the success path for text and cards. NOT covered:
        the `thread.threadKey` + `messageReplyOption` branch below (the live
        posts were unthreaded), the non-200 branch, and the HTTPError branch.
        """
```

### Task C.4 — `ChatApiAdapter.send_text`

Replace the existing docstring:

```python
    def send_text(self, space: str, thread_name: str | None, text: str) -> None:
        """Bare in-thread text (authorization refusals, R7 failure notices).
        Matches the forwarder's ReplyFn signature.

        ⚠ LIVE-UNVERIFIED. `send()` above was cleared on 2026-07-29; this
        method was NOT, and the distinction is deliberate: it builds a
        different request (`thread.name`, not `thread.threadKey`) and nothing
        has ever driven it against Google.

        It matters more than its size suggests. This is the method that tells a
        user their tap did not land (jobhunt R7) and the method that refuses an
        unauthorized user (jobhunt R4). A silent failure here is a silent
        failure of exactly the guarantees those requirements exist to provide —
        so do not clear this flag on the strength of send() working.
        """
```

### Task C.5 — `CLAUDE.md` status block

Replace the `- Chat API **send** — see CG-5.` line left by Part B with:

```
  - Chat API **send()** — ⚠ flag CLEARED 2026-07-29 (real `ChatApiAdapter` +
    real `GoogleServiceAccountTokens`; text and Cards v2 posted as the app;
    response carried `sender: {displayName: "Agent Comms", type: BOT}`). Not
    covered: its threading branch (the live posts were unthreaded) and its
    error branches.
  - Chat API **send_text()** — still ⚠ LIVE-UNVERIFIED. Different request
    shape (`thread.name`), never driven. It is the jobhunt R7 failure-notice
    and R4 refusal path.
```

### Task C.6 — verify and close out

```bash
python -m pytest -q          # 70 passed — this part changes no code
```

Mark CG-5 shipped in `docs/BUILDER_QUEUE.md`.

---

# Part D — CG-3: land the real interaction capture

Branch: `fix/real-addon-interaction-fixture`

The source capture is at
`C:\Users\mark\AppData\Local\Temp\cg-fixture\addon-buttonclicked-event.json`.
It is **raw** — it carries a real numeric user id, a real avatar token, a real
email, a real domain id and a real customer id, twice over in places. This repo
is public.

> **Do not hand-scrub by path.** That is the failure mode that on 2026-07-29
> wrote a live token to disk. Write the guard extension (Task D.1) **first**,
> then land the fixture, then run the guard. If the guard passes on a file you
> have not finished anonymizing, the guard is wrong — fix the guard, not the
> assertion.

Note also: `tests/fixtures/addon-message-event.json` is **already landed** (CG-1,
PR #5) and is byte-identical in structure to the temp copy of the same event.
There is nothing to do for it.

### Task D.1 — extend the scrub guard FIRST

In `tests/test_fixtures_scrubbed.py`, add after the `PII` definition:

```python
# Tenant identifiers. A real Google domainId / customer id is an opaque
# alphanumeric string with no structure to key off — unlike a user id, there is
# no "never starts with 0" trick available. So the fixture side carries the
# marker instead: the value must contain `example`, which RFC 2606 reserves and
# a real Workspace tenant id cannot contain. Structural, not a path allowlist —
# same reason as the zero-padded user ids above.
#
# These arrived with the 2026-07-29 buttonClicked capture, which carries
# `chat.user.domainId` and `<space>.customer` (the latter TWICE — once under the
# payload, once inside the message's echoed space object). Nothing in the
# previous guard would have caught either.
TENANT_KEY = re.compile(r"\.(domainId|customer)$")
```

and inside `test_fixture_contains_no_secrets`, after the `PII` assertion:

```python
        if TENANT_KEY.search(json_path):
            assert "example" in value.lower(), (
                f"{path.name}{json_path} = {value!r} looks like a real Google "
                "domain/customer id — fixtures must use an `example`-marked "
                "synthetic value (RFC 2606); this repo is public"
            )
```

Add a second test in the same file, so the guard is proven to *reject*, not just
to pass:

```python
def test_guard_rejects_unmarked_tenant_identifiers(tmp_path, monkeypatch):
    """A guard that has never failed is a guard nobody has tested.

    Both spellings, because the buttonClicked capture carries both and a scrub
    that fixed only one would still ship a real tenant id.
    """
    for key, value in (("domainId", _TENANT_BAIT), ("customer", _CUSTOMER_ID_BAIT)):
        bad = tmp_path / f"bad-{key}.json"
        bad.write_text(json.dumps({"chat": {"user": {key: value}}}), encoding="utf-8")
        data = json.loads(bad.read_text(encoding="utf-8"))
        offenders = [p for p, v in _walk(data)
                     if TENANT_KEY.search(p) and "example" not in v.lower()]
        assert offenders, f"guard failed to flag a real {key}"
```

> [**Scrubbed forward 2026-07-30 under queue item CG-26.** The two bait values in
> the loop above were the real Workspace tenant identifiers off the capture; they
> are now the invented constants the landed test composes at import time. Fix
> forward, not a history rewrite — the user's decision, and the reasoning, are in
> the CG-26 row of `docs/BUILDER_QUEUE.md`. This line is *why* the guard now scans
> `docs/**/*.md` and `tests/**/*.py` and not only `tests/fixtures/`.]

### Task D.2 — land the anonymized fixture

Create `tests/fixtures/addon-buttonclicked-event.json`. Structure is byte-faithful
to the capture; only leaf values change.

Anonymization applied — human `users/1129…953` → `users/000000000000000000001`
(the same synthetic human as the message fixture), display name → `Test User`,
avatar → `https://example.com/avatar.png`, email → `agent-user@example.com`,
`domainId` → `example1`, `customer` → `customers/Cexample1`, space
`spaces/AAQAmzgydeI` → `spaces/AAAAtestRoom` (and its `spaceUri`), space display
name `Ai Trader` → `Test Room` (**deliberate** — landing a fixture named after
`aitrader`'s space in a repo where aitrader is `allow_inbound: false` invites
exactly the wrong inference), message/thread ids → `MSG2`, and the **app's own
sender** `users/1115…012` → `users/000000000000000000002` with its
`googleusercontent.com` proxy avatar → `https://example.com/app-avatar.png`.

Kept real, deliberately: `Agent Comms` (the app name, published in
`docs/google-cloud-setup.md` step 5, and load-bearing here — it is the tier-2
sender), the topic path in `action.function` (project ids are classified
non-secret by step 8, and this value *is the finding*), the timestamps, and
`_pubsub_message_id` (a delivery id, and the first fixture to exercise
`dedupe_key`).

```json
{
  "commonEventObject": {
    "userLocale": "en",
    "hostApp": "CHAT",
    "platform": "WEB",
    "timeZone": {
      "id": "America/New_York",
      "offset": -14400000
    },
    "formInputs": {
      "decision": {
        "stringInputs": {
          "value": [
            "approve"
          ]
        }
      }
    },
    "parameters": {
      "probe": "topic-as-fn"
    }
  },
  "chat": {
    "user": {
      "name": "users/000000000000000000001",
      "displayName": "Test User",
      "avatarUrl": "https://example.com/avatar.png",
      "email": "agent-user@example.com",
      "type": "HUMAN",
      "domainId": "example1"
    },
    "eventTime": "2026-07-29T17:55:44.703463Z",
    "buttonClickedPayload": {
      "space": {
        "name": "spaces/AAAAtestRoom",
        "type": "ROOM",
        "displayName": "Test Room",
        "spaceThreadingState": "THREADED_MESSAGES",
        "spaceType": "SPACE",
        "spaceHistoryState": "HISTORY_ON",
        "lastActiveTime": "2026-07-29T17:50:23.086351Z",
        "membershipCount": {
          "joinedDirectHumanUserCount": 1
        },
        "customer": "customers/Cexample1",
        "spaceUri": "https://chat.google.com/room/AAAAtestRoom?cls=11"
      },
      "message": {
        "name": "spaces/AAAAtestRoom/messages/MSG2.MSG2",
        "sender": {
          "name": "users/000000000000000000002",
          "displayName": "Agent Comms",
          "avatarUrl": "https://example.com/app-avatar.png",
          "type": "BOT"
        },
        "createTime": "2026-07-29T17:50:23.086351Z",
        "text": "probe 2: change the dropdown, then tap the button",
        "thread": {
          "name": "spaces/AAAAtestRoom/threads/MSG2",
          "retentionSettings": {
            "state": "PERMANENT"
          }
        },
        "space": {
          "name": "spaces/AAAAtestRoom",
          "type": "ROOM",
          "displayName": "Test Room",
          "spaceThreadingState": "THREADED_MESSAGES",
          "spaceType": "SPACE",
          "spaceHistoryState": "HISTORY_ON",
          "lastActiveTime": "2026-07-29T17:50:23.086351Z",
          "membershipCount": {
            "joinedDirectHumanUserCount": 1
          },
          "customer": "customers/Cexample1",
          "spaceUri": "https://chat.google.com/room/AAAAtestRoom?cls=11"
        },
        "argumentText": "probe 2: change the dropdown, then tap the button",
        "cardsV2": [
          {
            "cardId": "cg-probe-2",
            "card": {
              "header": {
                "title": "chat-gateway",
                "subtitle": "probe 2 - selection widget + topic-as-function"
              },
              "sections": [
                {
                  "widgets": [
                    {
                      "decoratedText": {
                        "text": "<b>1.</b> Change the dropdown below.",
                        "wrapText": true
                      }
                    },
                    {
                      "selectionInput": {
                        "name": "decision",
                        "label": "Decision",
                        "type": "DROPDOWN",
                        "items": [
                          {
                            "text": "(choose)",
                            "value": "none",
                            "selected": true
                          },
                          {
                            "text": "Approve",
                            "value": "approve"
                          },
                          {
                            "text": "Reject",
                            "value": "reject"
                          }
                        ],
                        "onChangeAction": {
                          "function": "cgSelectProbe"
                        }
                      }
                    },
                    {
                      "decoratedText": {
                        "text": "<b>2.</b> Then tap the button.",
                        "wrapText": true
                      }
                    },
                    {
                      "buttonList": {
                        "buttons": [
                          {
                            "text": "Topic-as-function probe",
                            "onClick": {
                              "action": {
                                "function": "projects/chat-gateway-prod/topics/chat-gateway-events",
                                "parameters": [
                                  {
                                    "key": "probe",
                                    "value": "topic-as-fn"
                                  }
                                ]
                              }
                            }
                          }
                        ]
                      }
                    }
                  ]
                }
              ]
            }
          }
        ],
        "retentionSettings": {
          "state": "PERMANENT"
        },
        "messageHistoryState": "HISTORY_ON",
        "formattedText": "probe 2: change the dropdown, then tap the button",
        "markupSyntax": "MARKUP_SYNTAX_CHAT"
      }
    }
  },
  "_pubsub_message_id": "20751388131856523"
}
```

Then, immediately:

```bash
python -m pytest -q tests/test_fixtures_scrubbed.py
```

It must pass on all four fixtures. If it does not, the anonymization is
incomplete — fix the fixture, never the guard's assertion.

### Task D.3 — tests against the real capture

Append to `tests/test_adapters.py`:

```python
def test_normalize_real_addon_button_click():
    """REAL capture, 2026-07-29 — the first genuine card interaction this
    project has ever received. Pins what Google ACTUALLY sends, as opposed to
    what the constructed fixture assumes.

    Note `text`: on an interaction it is the CARD's message text, not anything
    the user typed. A consumer reading it as user intent will be wrong.
    """
    core = normalize_event(fixture("addon-buttonclicked-event.json"))
    assert core["event_type"] == "CARD_CLICKED"
    assert core["envelope_format"] == "addon"
    assert core["space"] == "spaces/AAAAtestRoom"
    assert core["thread_name"] == "spaces/AAAAtestRoom/threads/MSG2"
    assert core["message_id"] == "spaces/AAAAtestRoom/messages/MSG2.MSG2"
    assert core["sender_display"] == "Test User"          # the tapper, not the app
    assert core["sender_email"] == "agent-user@example.com"
    assert core["text"] == "probe 2: change the dropdown, then tap the button"
    assert core["dedupe_key"] == "20751388131856523"


def test_real_button_click_merges_selection_widget_value_into_params():
    """The selection-widget truth, on real data.

    A selectionInput's *value* arrives in commonEventObject.formInputs and is
    harvested at button-submit time, merged alongside the button's own action
    parameters. This is what makes jobhunt R6's structured reject reason work —
    and it is NOT the same as a widget being an interaction trigger, which was
    disproven the same day (onChangeAction fails exactly like a button:
    gsuiteaddons code 13).

    Also confirms `parameters` really does arrive as a flat map in this runtime;
    the list-form tolerance in _action_params remains untested against reality.
    """
    core = normalize_event(fixture("addon-buttonclicked-event.json"))
    assert core["action"]["params"] == {"probe": "topic-as-fn", "decision": "approve"}


def test_real_button_click_action_id_is_empty_KNOWN_DEFECT():
    """PINS A DEFECT. This is not desired behaviour — see queue item CG-10.

    The card's button routed via
    `action.function = "projects/chat-gateway-prod/topics/chat-gateway-events"`,
    so the add-ons runtime sent NO `__action_method_name__` parameter, no
    `invokedFunction`, and no `payload.action`. _normalize_addon consults
    exactly those three sources, finds none, and falls through `or ""` to an
    empty string — silently, into an InboundReply that looks structurally valid
    and would be forwarded to a tenant callback as though it carried an action
    identity. That is the silent-failure class CG-1 existed to eliminate, one
    layer further in.

    When CG-10 lands this test MUST be rewritten, not deleted: the fixture is
    real, and the behaviour it pins is precisely the behaviour that has to
    change.
    """
    core = normalize_event(fixture("addon-buttonclicked-event.json"))
    assert core["action"]["id"] == ""
```

### Task D.4 — correct the constructed fixture's three tests

The constructed fixture stays — it is unobserved, not disproven, and it carries
the only coverage of the `__action_method_name__` shape and the classic-parity
path. What changes is that its docstrings stop describing it as reality.

Replace `test_normalize_addon_card_clicked`'s docstring:

```python
def test_normalize_addon_card_clicked():
    """CONSTRUCTED fixture — a shape we have NOT observed.

    The real 2026-07-29 capture (addon-buttonclicked-event.json) contained no
    `__action_method_name__` at all. This fixture is kept as tolerance coverage
    for a card style we have not seen — one whose action.function is an
    ordinary function name rather than a topic path — not as a statement about
    what the add-ons runtime sends. Do not "fix" it to match the real capture;
    they cover different things.
    """
```

Replace `test_action_id_parity_across_formats`'s docstring:

```python
def test_action_id_parity_across_formats():
    """Parity holds GIVEN the add-ons runtime supplies __action_method_name__.

    That condition was previously implicit and read as a guarantee. The real
    2026-07-29 capture did not satisfy it — the add-on side yielded
    action.id == "" — so this asserts a conditional property of a constructed
    fixture, not an observed one. See test_real_button_click_action_id_is_
    empty_KNOWN_DEFECT and queue item CG-10.
    """
```

Replace `test_addon_action_parameters_tolerate_list_form`'s docstring:

```python
def test_addon_action_parameters_tolerate_list_form():
    """Defensive. The one real add-on interaction we have captured sent
    `parameters` as a flat MAP (2026-07-29), so this list branch has still
    never been seen in the wild. Kept because Google's classic runtime does
    send the list form and _action_params is shared.
    """
```

### Task D.5 — `tests/fixtures/README.md`

Replace the provenance table and add the near-miss note:

```markdown
| File | Provenance |
|---|---|
| `addon-message-event.json` | **REAL** — captured from `chat-gateway-sub` on 2026-07-29, the first genuine Chat event this project ever received. Structure is byte-faithful to the wire; leaf values are anonymized (see below). |
| `addon-buttonclicked-event.json` | **REAL** — captured 2026-07-29, the first genuine card *interaction*. A card posted by our own `ChatApiAdapter`, a dropdown changed, a button tapped. Pins what Google actually sends, including the empty `action.id` defect (queue item CG-10). |
| `classic-message-event.json` | **CONSTRUCTED** — the same logical event in the classic Chat app envelope, so both parser paths are covered symmetrically. |
| `addon-card-clicked-event.json` | **CONSTRUCTED, ⚠ NOT OBSERVED** — assembled from Google's documented add-on interaction shape, carrying `__action_method_name__`. The real capture above did **not** contain that key. Kept as tolerance coverage for a card style we have not seen (one whose `action.function` is an ordinary function name), not as a claim about the runtime. |

### The near-miss worth remembering

The buttonClicked capture carries two things a path-guessing scrub would have
walked straight past:

- the **app's own sender block** (`…message.sender`) holds a real numeric user id
  and a `googleusercontent.com` proxy avatar URL. The message capture had no bot
  sender at all, so no previous scrub ever had to think about one.
- the space object is echoed **twice** — once under the payload, once nested
  inside the message. Fixing one and shipping the other is a single-character
  mistake.

Both are why the guard walks the whole structure. It is a test, not a checklist,
because the checklist version already failed once.
```

Extend the anonymization section:

```markdown
`domainId` and `customer` are Workspace tenant identifiers with no structure to
key off, so fixtures mark them instead: their values must contain `example`
(RFC 2606, which a real tenant id cannot contain). Enforced by `TENANT_KEY` in
`test_fixtures_scrubbed.py`.

Space / message / thread ids are anonymized by convention and deliberately have
**no** guard rule: `docs/google-cloud-setup.md` step 8 classifies space IDs as
non-secret, and a guard that contradicts our own published classification would
be worse than the convention.

One value is kept real on purpose:
`action.function = "projects/chat-gateway-prod/topics/chat-gateway-events"` in
the buttonClicked fixture. Project ids are non-secret per the same step 8, and
that value **is** the finding — remove it and the fixture stops demonstrating
why `action.id` is empty.
```

### Task D.6 — correct the four now-stale comments in `adapters/pubsub.py`

Module docstring, replace the SHAPE-VERIFIED paragraph:

```python
⚠ SHAPE-VERIFIED 2026-07-29: the add-ons MESSAGE envelope AND the add-ons
buttonClicked (CARD_CLICKED) envelope are both normalized against REAL captured
payloads replayed offline (tests/fixtures/addon-message-event.json,
tests/fixtures/addon-buttonclicked-event.json). Stronger than doc-derived,
weaker than a live round-trip: our normalizer has still never processed an
interaction live — both captures were pulled with an ad-hoc client, not
PubSubPuller.

The interaction capture found a DEFECT rather than confirming the mapping: the
real event yields action.id == "" (see ADDON_ACTION_KEY below and queue item
CG-10). Nothing about jobhunt R3/R4 is verified by it.
```

`ADDON_ACTION_KEY`, replace its comment:

```python
# In the add-ons runtime Google passes the card's original action.function
# under this reserved parameter key. commonEventObject.invokedFunction was
# REMOVED from that runtime (add-ons release notes, 2025-05-12) but still
# exists classic-side.
#
# ⚠ CONDITIONAL, as of the real 2026-07-29 capture. That event carried NO
# __action_method_name__ — its button routed via
# action.function = "<a Pub/Sub topic path>", and the runtime sent nothing in
# this slot. So the "same card under either runtime yields the same
# InboundReply" property this key was added for holds only when the key is
# actually sent, which is not always. The fall-through is a silent "" — the
# defect queue item CG-10 exists to fix. Do not read this constant as a
# guarantee.
ADDON_ACTION_KEY = "__action_method_name__"
```

`_action_params`, replace the trailing sentence:

```python
def _action_params(raw_params) -> dict:
    """Classic sends action.parameters as a LIST of {"key","value"}; the
    add-ons runtime sends commonEventObject.parameters as a flat string->string
    MAP. Accept either. The map form is capture-confirmed (2026-07-29); the
    list branch is still doc-derived and has never been seen from the add-ons
    runtime."""
```

`_normalize_addon`, replace its docstring's second paragraph:

```python
    ⚠ The CARD_CLICKED path is now SHAPE-VERIFIED against a real 2026-07-29
    capture — and that capture showed the action-id extraction below FAILING to
    an empty string (queue item CG-10). Kept deliberately tolerant until CG-10
    decides where action identity should live.
```

### Task D.7 — `docs/consumers/jobhunt.md`, the R3 runtime note

Replace the 2026-07-29 runtime note. It currently says the path is
documentation-derived and unverified; the update must **not** upgrade that to
verified, because the capture found a defect:

```markdown
> **Runtime note (updated 2026-07-29, after a real capture).** Interactions were
> designed to normalize identically under both Google runtimes: under the
> Workspace Add-ons runtime the action id arrives as the reserved
> `__action_method_name__` parameter and is lifted into `action.id`. A real card
> tap has now been captured (`tests/fixtures/addon-buttonclicked-event.json`)
> and it did **not** work that way — the runtime sent no such parameter and
> `action.id` came through **empty**. `action.params` was correct, including a
> selection widget's value merged in from `commonEventObject.formInputs`.
>
> **R3 and R4 are therefore still NOT verified**, and the reason is now a known
> defect rather than an untested path: R3 requires the whole interaction plus an
> idempotency key, and the action identity is missing. Queue item CG-10 tracks
> it; it is blocked on the architecture decision that owns where action identity
> should live.
```

### Task D.8 — `CLAUDE.md` status bullet

Replace:

```
  - Add-on **CARD_CLICKED** — no interaction event has ever been captured.
```

with:

```
  - Add-on **CARD_CLICKED** — a real interaction WAS captured 2026-07-29 and is
    now ⚠ SHAPE-VERIFIED (tests/fixtures/addon-buttonclicked-event.json). It
    found a defect rather than confirming the mapping: `action.id` normalizes to
    "" because the card's routing pattern consumed the function slot. Params
    (including selection-widget values) are correct. Not a live-round-trip clear
    — the capture was pulled with an ad-hoc client. jobhunt R3/R4 remain
    unverified; see queue item CG-10.
```

### Task D.9 — verify and close out

```bash
python -m pytest -q          # expect 70 + 3 new adapter tests + 1 new guard test = 74
```

Mark CG-3 shipped in `docs/BUILDER_QUEUE.md`, and move it out of **Blocked**.

---

# Part E — CG-7: `/healthz` must degrade when inbound is dead

Branch: `fix/healthz-subscriber-liveness`

The hole, restated so the implementer sees it before touching anything:
`SubscriberLoop._run` swallows every poll exception; `last_poll_at` is only
assigned after a *successful* `poll_once`; and `healthz`'s `degraded` expression
reads only identity env-resolution and app keys. A gateway whose every poll has
failed since boot therefore reports `"last_poll_at": null` next to
`"status": "ok"`, forever.

### Task E.1 — typed Pub/Sub error

In `src/chat_gateway/adapters/pubsub.py`, add after `UNPARSEABLE`:

```python
class PubSubError(RuntimeError):
    """A Pub/Sub REST call failed, carrying the HTTP status.

    Typed rather than a bare RuntimeError so SubscriberLoop can classify a
    failure without regexing an error message. It also stops echoing
    `resp.text[:200]`: a Google error body can quote the request, and the
    request path names the subscription — hard rule #2 says names, not values.
    The reason phrase is a fixed HTTP string and carries nothing.

    The cost is honest: we lose Google's error prose. Status + phrase is what
    the loop can act on.
    """

    def __init__(self, verb: str, status_code: int, reason: str = ""):
        super().__init__(f"pubsub {verb} failed: HTTP {status_code} {reason}".rstrip())
        self.verb = verb
        self.status_code = status_code
        self.reason = reason
```

and replace `PubSubPuller._post`'s failure branch:

```python
    def _post(self, verb: str, body: dict) -> dict:
        resp = self._client.post(
            f"{PUBSUB_API}/{self._sub}:{verb}",
            json=body,
            headers={"Authorization": f"Bearer {self._tokens()}"},
        )
        if resp.status_code != 200:
            raise PubSubError(verb, resp.status_code, resp.reason_phrase)
        return resp.json() if resp.text else {}
```

### Task E.2 — `SubscriberLoop` counters

Add to `__init__`, after `self.dispatch_errors = 0`:

```python
        # Poll-level failure tracking. poll_once() raising means the
        # SUBSCRIPTION is unreachable — a revoked key, a deleted subscription, a
        # wrong CHAT_GATEWAY_PUBSUB_SUBSCRIPTION, or free-tier quota exhaustion.
        # All four look identical from in here and all four fail CLOSED: inbound
        # simply stops. Before this existed, healthz reported "ok" throughout
        # (hard rule #5, the failure it was written after).
        self.poll_failures = 0
        self.consecutive_poll_failures = 0
        # "<ExceptionType> HTTP <status>" — a TYPE and a STATUS, never a message
        # body (rule #2). Cleared on the first success so recovery is visible.
        self.last_poll_error: str | None = None
```

Replace `_run`:

```python
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
                self.consecutive_poll_failures = 0
                self.last_poll_error = None
                if self.forwarder is not None:
                    self.forwarder.process_due()
            except Exception as exc:  # noqa: BLE001 — the loop must survive
                self.poll_failures += 1
                self.consecutive_poll_failures += 1
                self.last_poll_error = (
                    f"{type(exc).__name__} HTTP {exc.status_code}"
                    if isinstance(exc, PubSubError) else type(exc).__name__
                )
                # Type + status only. The previous version printed the exception
                # message, which for a Pub/Sub failure embedded resp.text[:200].
                print(f"subscriber: poll error (will retry): {self.last_poll_error}",
                      flush=True)
            self._stop.wait(self._interval)
```

### Task E.3 — `service.py`: reasons, and a status computed from them

Add `import os` to the imports, and these module constants after the existing
imports:

```python
# Consecutive failed polls before /healthz calls inbound dead. Three at the
# default 5s interval is ~15s — long enough to ride out a blip, short enough
# that a real outage is visible within one dashboard refresh.
POLL_FAILURE_THRESHOLD = 3
```

Replace the `healthz` endpoint body:

```python
    @app.get("/healthz")
    def healthz():
        """Honest health: real resolvability + real liveness — never a
        hardcoded OK (claude-mem pilot lesson; aiteam plan F18 gate 2).

        `status` is computed FROM `reasons`, not alongside it. Anything that can
        make this endpoint degraded must be able to say so in words, because an
        operator seeing "degraded" and no reason has to diff the body against a
        known-good copy to learn anything.
        """
        hb_all = [c for s in registry.apps for c in checks.list_for(s)]
        body = {
            "version": __version__,
            "registry": registry.health(),
            "inbox": {"pending": inbox.pending_counts(), "dropped": inbox.dropped},
            "delivery": {"pending_jobs": dispatch.pending()},
            "heartbeats": {"checks": len(hb_all),
                           "missed": sum(1 for c in hb_all if c.status == "missed"),
                           "last_scan_at": monitor.last_scan_at.isoformat() if monitor.last_scan_at else None},
            "subscriber": (
                {"enabled": True,
                 "last_poll_at": subscriber.last_poll_at.isoformat() if subscriber.last_poll_at else None,
                 "events_seen": subscriber.events_seen,
                 "unparseable_seen": subscriber.unparseable_seen,
                 "dispatch_errors": subscriber.dispatch_errors,
                 "poll_failures": subscriber.poll_failures,
                 "consecutive_poll_failures": subscriber.consecutive_poll_failures,
                 "last_poll_error": subscriber.last_poll_error,
                 # DECLARED, not detected — the field name says so. Detecting it
                 # means calling Cloud Billing / Service Usage: more scopes, more
                 # IAM, more calls. And on 2026-07-29 Google's own
                 # topic/send_request_count read ZERO after a message had
                 # provably published, which is a standing argument against
                 # trusting its telemetry for this.
                 "billing_declared": os.environ.get("GATEWAY_GCP_BILLING", "unknown"),
                 "quota_note": (
                     "free-tier exhaustion fails CLOSED — inbound stops with no "
                     "other symptom; consecutive_poll_failures is the signal"
                 )}
                if subscriber is not None
                else {"enabled": False, "note": "tier 2 not enabled (GATEWAY_ENABLE_PUBSUB=0)"}
            ),
        }

        reasons: list[str] = []
        for name, i in body["registry"]["identities"].items():
            if not i["env_resolved"]:
                reasons.append(f"identity {name!r}: env var does not resolve")
        for app_id, a in body["registry"]["apps"].items():
            if not a["key_configured"]:
                reasons.append(f"app {app_id!r}: key env var is not set")
        sub = body["subscriber"]
        if sub["enabled"]:
            if sub["last_poll_at"] is None:
                reasons.append(
                    "subscriber is enabled but has never completed a poll — "
                    "inbound has never worked on this process"
                )
            elif sub["consecutive_poll_failures"] >= POLL_FAILURE_THRESHOLD:
                reasons.append(
                    f"subscriber: {sub['consecutive_poll_failures']} consecutive "
                    f"poll failures (last: {sub['last_poll_error']}) — inbound is "
                    "DOWN. Revoked key, deleted subscription, wrong subscription "
                    "name, or quota exhaustion all look like this and all fail closed"
                )
        # Names, never values: identity names and app ids are non-secret (they
        # live in the committed registry); the poll error is a type and a status.
        return JSONResponse(status_code=200,
                            content={"status": "degraded" if reasons else "ok",
                                     "reasons": reasons, **body})
```

### Task E.4 — `.env.example`

Append to the tier-2 block:

```bash
GATEWAY_GCP_BILLING=disabled                 # disabled | enabled | unknown — DECLARED, not
                                             # detected. Surfaced at /healthz so an operator
                                             # knows quota exhaustion will fail CLOSED.
```

### Task E.5 — tests

Replace `test_healthz_reports_real_subscriber_counters` in
`tests/test_service.py` (its exact-dict assertion is deliberate — do not loosen
it to a subset, that is what lets a rename go unnoticed):

```python
def test_healthz_reports_real_subscriber_counters(env, tmp_path, monkeypatch):
    """Hard rule #5: the subscriber block must read the loop's REAL counters.
    A defaulted getattr() would report a hardcoded 0 forever after a rename —
    exactly the silent-health failure this rule exists to prevent."""
    from chat_gateway.adapters.pubsub import FakePuller, SubscriberLoop

    monkeypatch.setenv("GATEWAY_GCP_BILLING", "disabled")
    _, inbox, adapter = env
    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    registry = load_registry(p)
    loop = SubscriberLoop(FakePuller(), registry, inbox)
    loop.events_seen, loop.unparseable_seen, loop.dispatch_errors = 9, 2, 3
    loop.last_poll_at = dt.datetime(2026, 7, 29, 12, 0, tzinfo=dt.timezone.utc)

    client = TestClient(create_app(registry, inbox, {"webhook": adapter}, loop))
    sub = client.get("/healthz").json()["subscriber"]
    assert sub == {
        "enabled": True, "last_poll_at": "2026-07-29T12:00:00+00:00",
        "events_seen": 9, "unparseable_seen": 2, "dispatch_errors": 3,
        "poll_failures": 0, "consecutive_poll_failures": 0, "last_poll_error": None,
        "billing_declared": "disabled",
        "quota_note": ("free-tier exhaustion fails CLOSED — inbound stops with no "
                       "other symptom; consecutive_poll_failures is the signal"),
    }
```

Append to `tests/test_service.py`:

```python
def _loop_with(tmp_path, inbox, **attrs):
    from chat_gateway.adapters.pubsub import FakePuller, SubscriberLoop

    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    registry = load_registry(p)
    loop = SubscriberLoop(FakePuller(), registry, inbox)
    for k, v in attrs.items():
        setattr(loop, k, v)
    return registry, loop


def test_healthz_degrades_when_subscriber_has_never_polled(env, tmp_path):
    """The claude-mem failure shape, exactly: green health over a dead input.

    An enabled subscriber with last_poll_at=None has never successfully reached
    Pub/Sub on this process. Before this, healthz reported "ok" indefinitely.
    """
    _, inbox, adapter = env
    registry, loop = _loop_with(tmp_path, inbox)          # last_poll_at stays None
    client = TestClient(create_app(registry, inbox, {"webhook": adapter}, loop))
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    assert any("never completed a poll" in r for r in body["reasons"])


def test_healthz_degrades_on_consecutive_poll_failures_and_recovers(env, tmp_path):
    """Quota exhaustion, a revoked key and a deleted subscription are
    indistinguishable from in-process and all fail CLOSED — so the signal is the
    failure run, not the cause. And it must clear on recovery, not stick."""
    from chat_gateway.service import POLL_FAILURE_THRESHOLD

    _, inbox, adapter = env
    registry, loop = _loop_with(
        tmp_path, inbox,
        last_poll_at=dt.datetime(2026, 7, 29, 12, 0, tzinfo=dt.timezone.utc),
        poll_failures=7,
        consecutive_poll_failures=POLL_FAILURE_THRESHOLD,
        last_poll_error="PubSubError HTTP 429",
    )
    client = TestClient(create_app(registry, inbox, {"webhook": adapter}, loop))
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    assert any("HTTP 429" in r and "inbound is DOWN" in r for r in body["reasons"])

    loop.consecutive_poll_failures = 0
    loop.last_poll_error = None
    body = client.get("/healthz").json()
    assert body["status"] == "ok" and body["reasons"] == []
    assert body["subscriber"]["poll_failures"] == 7      # history is not erased


def test_healthz_reasons_explain_a_degraded_registry(env, monkeypatch):
    """`degraded` with no explanation makes an operator diff the body against a
    known-good copy. Say why."""
    client, _, _ = env
    monkeypatch.delenv("SVC_HOOK_FW")
    body = client.get("/healthz").json()
    assert body["status"] == "degraded"
    assert any("does not resolve" in r for r in body["reasons"])
```

And in `tests/test_adapters.py`, a rule-#2 regression:

```python
def test_pubsub_error_carries_status_not_response_body():
    """Hard rule #2: a Google error body can quote the request, and the request
    path names the subscription. Status and reason phrase only."""
    from chat_gateway.adapters.pubsub import PubSubError, PubSubPuller

    def quota_exhausted(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="RESOURCE_EXHAUSTED on projects/p/subscriptions/s")

    puller = PubSubPuller("projects/p/subscriptions/s", lambda: "tok",
                          mock_client(quota_exhausted))
    with pytest.raises(PubSubError) as exc:
        puller.pull()
    assert exc.value.status_code == 429
    assert "RESOURCE_EXHAUSTED" not in str(exc.value)
    assert "projects/p/subscriptions/s" not in str(exc.value)
```

> Note for the implementer: this test drives `PubSubPuller.pull()` with a mock
> transport. That is **not** a live round-trip and does **not** clear
> `PubSubPuller`'s ⚠ LIVE-UNVERIFIED flag. Leave the flag alone.

### Task E.6 — verify and close out

```bash
python -m pytest -q          # expect the Part D total (74) + 4 new = 78
```

Mark CG-7 shipped in `docs/BUILDER_QUEUE.md`.

---

# Part F — CG-8: reserve `_`-prefixed app ids

Branch: `fix/reserve-internal-app-ids`

### Task F.1 — `registry.py`: own the constant

Add after `MODES`:

```python
# App ids the gateway reserves for its own audit buckets. `_unrouted` is where
# unroutable and UNPARSEABLE events are filed, and the paths that write to it —
# the except branch in dispatch(), and the `or [UNROUTED]` fallback — bypass the
# per-app authorization block BY DESIGN, because an unparseable event has no
# space and cannot be authorized against anything. An app registered under that
# id with allow_inbound: true would therefore drain every unroutable and every
# UNPARSEABLE event from every space through /v1/inbox, with no hard-rule-#6
# check ever running.
#
# The whole `_` prefix is reserved, not just the one literal, so the next
# internal bucket is safe without anyone remembering to add it here.
#
# This constant lives in core, not in adapters/pubsub.py where it started:
# registry.py must not import from an adapter (hard rule #3 puts Google-facing
# code in adapters/, and core reaching into it inverts the layering). The
# adapter imports it from here, which is the direction that already exists.
UNROUTED = "_unrouted"
RESERVED_APP_ID_PREFIX = "_"
```

### Task F.2 — `registry.py`: reject at load

As the first statement inside `load_registry`'s `for app_id, spec in …` loop:

```python
    for app_id, spec in (data["apps"] or {}).items():
        if app_id.startswith(RESERVED_APP_ID_PREFIX):
            raise RegistryError(
                f"app id {app_id!r} is reserved: ids beginning with "
                f"{RESERVED_APP_ID_PREFIX!r} are gateway-internal audit buckets "
                f"(e.g. {UNROUTED!r}). An app registered under one would receive "
                "every unroutable and every UNPARSEABLE event from every space, "
                "bypassing the per-app inbound authorization check (hard rule #6)."
            )
        spec = spec or {}
```

### Task F.3 — `adapters/pubsub.py`: import instead of define

Replace the import line and delete the local definition:

```python
from ..registry import Registry, UNROUTED
```

and remove `UNROUTED = "_unrouted"` from the constants block, leaving:

```python
PUBSUB_API = "https://pubsub.googleapis.com/v1"
PUBSUB_SCOPE = "https://www.googleapis.com/auth/pubsub"
UNPARSEABLE = "UNPARSEABLE"
```

`from chat_gateway.adapters.pubsub import UNROUTED` keeps working — the import
binds the name on the module — so the eleven existing test references need no
change.

### Task F.4 — tests

Append to `tests/test_core.py`:

```python
def test_reserved_app_ids_are_rejected(tmp_path):
    """`_unrouted` is the audit bucket for unroutable and UNPARSEABLE events,
    and the paths that write to it bypass the per-app authorization block by
    design. An app registered under it would drain every one of them, from every
    space. Pre-existing hole; needs a misconfiguration; real in a multi-tenant
    transport."""
    from chat_gateway.registry import UNROUTED

    for bad_id in (UNROUTED, "_internal", "_"):
        p = tmp_path / "r.yaml"
        p.write_text(
            "identities:\n"
            "  pm:\n"
            "    display: PM\n"
            "    webhook_url_env: HOOK\n"
            "apps:\n"
            f"  {bad_id}:\n"
            "    key_env: KEY\n"
            "    identities: [pm]\n"
            "    allow_inbound: true\n",
            encoding="utf-8",
        )
        with pytest.raises(RegistryError) as exc:
            load_registry(p)
        assert "reserved" in str(exc.value)
        assert "hard rule #6" in str(exc.value)


def test_ordinary_app_ids_with_underscores_still_load(tmp_path):
    """Only the PREFIX is reserved — `aiteam_harness` must keep working."""
    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n"
        "  pm:\n"
        "    display: PM\n"
        "    webhook_url_env: HOOK\n"
        "apps:\n"
        "  aiteam_harness:\n"
        "    key_env: KEY\n"
        "    identities: [pm]\n",
        encoding="utf-8",
    )
    assert "aiteam_harness" in load_registry(p).apps


def test_unrouted_still_importable_from_the_adapter(tmp_path):
    """The constant moved to core; the adapter re-exports it. Eleven existing
    test call sites import it from the adapter and must not break."""
    from chat_gateway.adapters.pubsub import UNROUTED as from_adapter
    from chat_gateway.registry import UNROUTED as from_core

    assert from_adapter == from_core == "_unrouted"
```

> No new imports are needed at the top of `tests/test_core.py` — `pytest`,
> `load_registry` and `RegistryError` are all already in scope there (verified
> 2026-07-29). The two `UNROUTED` imports are deliberately function-local, so
> the module-level import list is untouched.

### Task F.5 — `CLAUDE.md` hard rule #6

Append one sentence to rule 6, since this closes a hole in it:

```
   inbound surface without explicit user sign-off naming this rule. App ids
   beginning with `_` are reserved for the gateway's own audit buckets
   (`_unrouted`) and rejected at registry load — registering one would have
   drained every unroutable and UNPARSEABLE event past this rule's checks.
```

### Task F.6 — verify and close out

```bash
python -m pytest -q          # expect the Part E total (78) + 3 new = 81
```

Mark CG-8 shipped in `docs/BUILDER_QUEUE.md`.

---

# Part G — CG-11: correct the selection-widget claim (BLOCKED on the ADR)

Branch: `docs/selection-widget-correction`

> **Do not start this part until the ADR under `docs/architecture/` has landed
> on `main`.** The facts below are settled and independent of it, but the ADR
> owns jobhunt's interaction model, and two documents asserting the same fact in
> different words is how drift starts. `CLAUDE.md` is this project's
> constitution; it should quote the ADR, not paraphrase it.

### Task G.1 — read the ADR first

```bash
ls docs/architecture/
```

Read it end to end. Then:

- If it states the same facts as Tasks G.2–G.3, **adopt its exact wording** in
  place of the text below and link to it.
- If it contradicts the finding below, **stop.** Do not reconcile it yourself —
  return the conflict to Planner. One of the two is wrong about observed
  behaviour and that has to be settled, not averaged.

### Task G.2 — `CLAUDE.md`, the jobhunt consumer bullet

Replace the parenthetical:

```
  (docs/consumers/jobhunt.md — the first two-way tenant: whole-event
  callback forwarding with per-user authorization, structured reasons via
  selection widgets, fail-loudly-in-thread; note: modal dialogs are
  impossible over Pub/Sub transport — selection widgets are the supported
  path).
```

with:

```
  (docs/consumers/jobhunt.md — the first two-way tenant: whole-event
  callback forwarding with per-user authorization, structured reasons via
  selection widgets, fail-loudly-in-thread).
  **On selection widgets, precisely** (the previous wording here was wrong and
  was disproven 2026-07-29): a widget is NOT an interaction trigger — its
  `onChangeAction` fails exactly like a button's (`gsuiteaddons.googleapis.com/
  errors` code 13, `deploymentFunction: cgSelectProbe`). What works is the
  widget's VALUE: `commonEventObject.formInputs` is harvested at button-submit
  time, and on real captured data the normalizer merged `"decision": "approve"`
  into `action.params` alongside the button's own parameters. So the supported
  pattern is *widgets for input, one button to submit* — capture-verified, not
  doc-derived. Modal dialogs are separately believed impossible (they need a
  synchronous HTTP interaction endpoint, which Pub/Sub transport does not
  provide) — that half is doc-derived inference and has never been tested; do
  not restate it as an observation.
```

### Task G.3 — `docs/consumers/jobhunt.md`, the R6 row

Replace the R6 table cell:

```markdown
| R6 | Structured reject reason | in-card `selectionInput`; the chosen value arrives merged into `action.params` (e.g. `reject_reason`) — **capture-verified 2026-07-29** on real data. Note the mechanism precisely: the widget is an input, **not** a trigger. Its `onChangeAction` fails exactly like a button's (gsuiteaddons code 13); the value is harvested from `commonEventObject.formInputs` when a **button** is tapped. Pattern: widgets for input, one button to submit. True modal dialogs are separately believed impossible over Pub/Sub transport (they need a synchronous HTTP interaction endpoint) — doc-derived, untested |
```

### Task G.4 — verify and close out

```bash
python -m pytest -q          # unchanged — docs only
```

Mark CG-11 shipped in `docs/BUILDER_QUEUE.md`.

---

# Blocked items — no plan text, by design

### CG-9 — `ADDED_TO_SPACE` fixture · blocked on a human

The bytes were never kept, so there is nothing to scrub. Recipe for whoever can
drive Chat:

1. In a test space: **⚙ → Apps & integrations**, remove the Chat app, then add
   it back.
2. `gcloud pubsub subscriptions pull chat-gateway-sub --limit=1 --format=json > capture.json`
3. Anonymize it under the Part D rules (guard first, fixture second, never a
   path-guess scrub), land it as `tests/fixtures/addon-added-to-space-event.json`,
   and add a test asserting `event_type == "ADDED_TO_SPACE"`, a space extracted
   from `chat.space` (the non-payload sibling — this payload has no `message`),
   and a sender from `chat.user`.

It covers three currently doc-derived paths at once: the `ADDON_PAYLOAD_TYPES`
entry, the three-source space resolution's `chat.space` arm, and `_shape` with an
empty `message`. All three ran correctly against the live event on 2026-07-29 —
but as an unrecorded observation, which in three weeks is indistinguishable from
a guess.

### CG-10 — Empty `action.id` · blocked on the ADR

Spec §3 (CG-10) states the mechanical requirements — detect, surface, test — and
enumerates the three available shapes. **No plan is written on purpose.** A plan
must carry literal code for every step; writing one before the ADR decides where
action identity lives would mean either inventing the policy or filling the plan
with placeholders. Planner writes it when the ADR lands.

### CG-12 — Forensic trace for opted-out-only spaces · blocked on the user

Spec §3 (CG-12) lays out options A / C / B with their rule-6 exposure. Planner
recommends **A** (a counter at `/healthz`, no space, no app id, no content) and
will not implement anything here without a decision that names hard rule #6.
Whichever option is chosen, the mechanism is an additive
`on_suppressed(app_id, reason)` callback on `dispatch`, mirroring the existing
`on_unparseable`, with reasons `"opt_out"` and `"not_authorized"`.

---

## Self-review

- **Spec coverage.** G1 → Parts B, C. G2 → Part D. G3 → CG-10 (blocked, by
  design). G4 → Part A. G5 → Part E. G6 → Part F plus CG-12 (blocked, by
  design).
- **No placeholders.** Every executable task carries literal code, literal
  markdown, or a literal command. The four blocked items carry no task text at
  all rather than TBD-shaped task text — that distinction is deliberate and is
  the point of DEC-12.
- **Executed against the real artifacts before hand-off, not drafted from
  memory** (Planner-side, in a scratchpad — no repo code was written):
  - Task D.2's fixture was parsed out of this plan and fed to the **current**
    `normalize_event`. Every assertion in Task D.3 holds exactly as written:
    `CARD_CLICKED`, space/thread/message ids, `sender_display == "Test User"`
    (the tapper, not the BOT sender), `dedupe_key == "20751388131856523"`,
    `params == {"probe": "topic-as-fn", "decision": "approve"}` (the
    `commonEventObject.parameters` map merged with the `formInputs` harvest),
    and `action.id == ""` falling through all three id sources.
  - Task D.1's guard was run three ways. It reports the anonymized fixture
    **clean**; it flags the **raw** capture on nine leaves; and the three
    `TENANT` hits among them —
    `$.chat.user.domainId`, `$.chat.buttonClickedPayload.space.customer` and
    `$.chat.buttonClickedPayload.message.space.customer` — are exactly the ones
    the committed guard misses today. That third path is the "echoed twice"
    near-miss the README note describes, confirmed rather than assumed. All
    three existing committed fixtures still pass the extended guard.
  - Task E.5's rule-#2 assertion was checked against `httpx`: a 429 yields
    `"pubsub pull failed: HTTP 429 Too Many Requests"` — no response body, no
    subscription path.
  - Task B.3 and Task E.5 were written against the live test bodies at
    `tests/test_adapters.py:35-67` and `tests/test_service.py:116-133`, both of
    which assert exact values today and must be **edited**, not left to fail.
  The code blocks are therefore validated, not merely drafted — but they still
  need to be re-run inside the real modules against the real suite.
- **Type consistency.** No normalized shape changes anywhere: `_shape()` is
  untouched, so `InboundReply(**core)` keeps working. `build_params` still
  returns `dict`. `healthz` gains one top-level key (`reasons: list[str]`) and
  four subscriber keys; `status` keeps its two values.
- **Untouched by design:** `envelope.py`, `forwarder.py`, `inbox.py`, `auth.py`,
  `client.py`, `delivery.py`, `heartbeat.py`, `notifications.py`, `__main__.py`,
  the `iac/` tree, and the authorization block inside `dispatch`. No part here
  changes what crosses to a consumer.
- **Flag discipline.** Parts B and C clear exactly two things and scope both in
  prose. Part D adds a ⚠ SHAPE-VERIFIED and clears nothing. `PubSubPuller` stays
  ⚠ LIVE-UNVERIFIED even though Part E adds a mock-transport test against it —
  called out inline in Task E.5 because that is precisely the moment someone
  would be tempted. The `chat-api-push` grant is not mentioned anywhere because
  nothing here bears on it.
- **Known risk.** Part D's fixture must be transcribed exactly; a hand-edit that
  drops a nesting level would make the test suite green against a shape Google
  never sent, which is the failure the fixture exists to prevent. Task D.2's
  guard-run is the check, and Task D.3's assertions are structural enough that a
  flattened copy fails them.
</content>
</invoke>
