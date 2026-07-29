# Implementation plan — dual-format Chat event envelope normalization

Date: 2026-07-29
Spec: [`../specs/2026-07-29-chat-event-envelope-normalization-design.md`](../specs/2026-07-29-chat-event-envelope-normalization-design.md)
Queue: [`../../BUILDER_QUEUE.md`](../../BUILDER_QUEUE.md)

Three work items, two shippable PRs plus one blocked follow-up:

| Part | Item | PR |
|---|---|---|
| **A** (Phases 1–5) | **CG-1** — dual-format normalizer | `fix/chat-event-envelope-normalization` |
| **B** (Phase 6) | **CG-2** — add-ons service agent + setup doc | `fix/addons-service-agent-iac` |
| **C** (Phase 7) | **CG-3** — live interaction capture | blocked on a human |

Read `CLAUDE.md` first. Hard rules #1, #2, #3, #5, #6 all bear on Part A.

**Approval gates before starting.** Spec §10 carries four open questions. Two
change what you write:
- **DEC-3** (`envelope_format` on `InboundReply`) — assumed **approved** below.
  If declined: drop the `envelope_format` key from `_shape()`, the field in
  `envelope.py`, and its assertions in tests. Nothing else changes.
- **DEC-7** (redact `configCompleteRedirectUri`) — assumed **approved** below.
  If declined: drop Task 2.4 and Task 3.2's `raw=raw`, passing `raw=event`
  as today, and drop test 15.

---

# Part A — CG-1: dual-format normalizer

## Phase 1 — Branch, baseline, fixtures, and the secret guard

The scrub guard lands **first**, before any fixture is committed. A
path-targeted scrub already failed once on 2026-07-29 and briefly wrote a live
token to disk; the guard is what makes that unrepeatable.

### Task 1.1 — Branch and baseline

```bash
cd /d/prj/chat-gateway
git checkout -b fix/chat-event-envelope-normalization
python -m pytest -q          # Windows dev box; python3 -m pytest on POSIX
```

Record the baseline count. It must be **37 passing**. If it is not, stop and
report — this plan assumes a green baseline.

### Task 1.2 — Fixture provenance README

Create `tests/fixtures/README.md`. JSON cannot carry comments, and provenance
is exactly what ⚠ LIVE-UNVERIFIED discipline needs to stay honest.

```markdown
# Test fixtures — Chat event envelopes

Provenance matters here: some of these are real bytes off the wire, some are
constructed. Do not blur the two — the project's ⚠ LIVE-UNVERIFIED discipline
depends on knowing which is which.

| File | Provenance |
|---|---|
| `addon-message-event.json` | **REAL** — captured from `chat-gateway-sub` on 2026-07-29, the first genuine Chat event this project ever received. Structure is byte-faithful to the wire; leaf values are anonymized (see below). |
| `classic-message-event.json` | **CONSTRUCTED** — the same logical event in the classic Chat app envelope, so both parser paths are covered symmetrically. |
| `addon-card-clicked-event.json` | **CONSTRUCTED, ⚠ UNVERIFIED** — assembled from Google's documented add-on interaction shape. No card button has ever been tapped against this deployment. Replace with a real capture (queue item CG-3) and tighten the parser to match. |

## Anonymization

This repository is **public**. Real captures keep their structure exactly —
every key, every nesting level — and change only leaf values: user ids,
avatar URLs, domain ids, space/message/thread ids, and email addresses.

`configCompleteRedirectUri` is a per-message capability URL: visiting it makes
the user's private message public in the space and re-delivers it. Its value is
always `<SCRUBBED>` here.

`test_fixtures_scrubbed.py` enforces all of the above recursively on every
file in this directory. It is not a checklist item — it is a test, because the
checklist version already failed once.
```

### Task 1.3 — The recursive secret guard (write this test BEFORE committing fixtures)

Create `tests/test_fixtures_scrubbed.py`:

```python
"""Hard rule #2 guard: no fixture may carry a live secret or real identity.

This is a TEST, not a scrub script, and it walks the whole structure rather
than named paths — on 2026-07-29 a path-guess scrub missed a live token in
`configCompleteRedirectUri` and briefly wrote it to disk. Path guessing is the
failure mode; recursion is the fix.
"""

import json
import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# A value under one of these keys MUST be a placeholder.
SUSPECT_KEY = re.compile(r"token|secret|password|credential|redirecturi|redirecturl|api_?key", re.I)
# ...and any value that looks like an embedded credential is rejected wherever it sits.
SUSPECT_VALUE = re.compile(
    r"(token|secret|password|bearer|api[_-]?key)\s*[=:]\s*\S|BEGIN [A-Z ]*PRIVATE KEY", re.I
)
PLACEHOLDER = re.compile(r"<(SCRUBBED|REDACTED|FAKE)[^>]*>", re.I)
# Real identities that must never reach a public repo via a fixture.
PII = re.compile(r"mackelprang|users/\d{10,}|googleusercontent\.com", re.I)


def _walk(node, path="$"):
    """Yield (json_path, key, value) for every string leaf."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, path.rsplit(".", 1)[-1], node


def fixture_files():
    files = sorted(FIXTURES.glob("*.json"))
    assert files, "no fixtures found — this guard must never pass vacuously"
    return files


@pytest.mark.parametrize("path", fixture_files(), ids=lambda p: p.name)
def test_fixture_contains_no_secrets(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    for json_path, key, value in _walk(data):
        if SUSPECT_KEY.search(key) or SUSPECT_VALUE.search(value):
            assert PLACEHOLDER.search(value), (
                f"{path.name}{json_path} looks like a credential and is not "
                f"scrubbed to a <SCRUBBED>/<REDACTED> placeholder"
            )
        assert not PII.search(value), (
            f"{path.name}{json_path} carries a real identity ({value[:40]}...) — "
            "anonymize it; this repo is public"
        )
```

Note the `fixture_files()` assertion: a guard that silently passes on an empty
directory is worse than no guard.

### Task 1.4 — The real captured add-on fixture (anonymized)

Create `tests/fixtures/addon-message-event.json`. Structure is byte-faithful to
the 2026-07-29 capture; only leaf values are anonymized.

```json
{
  "commonEventObject": {
    "userLocale": "en",
    "hostApp": "CHAT",
    "platform": "WEB",
    "timeZone": {
      "id": "America/New_York",
      "offset": -14400000
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
    "eventTime": "2026-07-29T12:55:58.782511Z",
    "messagePayload": {
      "space": {
        "name": "spaces/AAAAtestSpace",
        "type": "DM",
        "singleUserBotDm": true,
        "spaceThreadingState": "THREADED_MESSAGES",
        "spaceType": "DIRECT_MESSAGE",
        "spaceHistoryState": "HISTORY_ON",
        "lastActiveTime": "2026-07-29T12:55:58.782511Z",
        "membershipCount": {
          "joinedDirectHumanUserCount": 1
        },
        "spaceUri": "https://chat.google.com/dm/AAAAtestSpace?cls=11"
      },
      "message": {
        "name": "spaces/AAAAtestSpace/messages/MSG1.MSG1",
        "sender": {
          "name": "users/000000000000000000001",
          "displayName": "Test User",
          "avatarUrl": "https://example.com/avatar.png",
          "email": "agent-user@example.com",
          "type": "HUMAN",
          "domainId": "example1"
        },
        "createTime": "2026-07-29T12:55:58.782511Z",
        "text": "Another test message.",
        "thread": {
          "name": "spaces/AAAAtestSpace/threads/MSG1",
          "retentionSettings": {
            "state": "PERMANENT"
          }
        },
        "space": {
          "name": "spaces/AAAAtestSpace",
          "type": "DM",
          "singleUserBotDm": true,
          "spaceThreadingState": "THREADED_MESSAGES",
          "spaceType": "DIRECT_MESSAGE",
          "spaceHistoryState": "HISTORY_ON",
          "lastActiveTime": "2026-07-29T12:55:58.782511Z",
          "membershipCount": {
            "joinedDirectHumanUserCount": 1
          },
          "spaceUri": "https://chat.google.com/dm/AAAAtestSpace?cls=11"
        },
        "argumentText": "Another test message.",
        "retentionSettings": {
          "state": "PERMANENT"
        },
        "messageHistoryState": "HISTORY_ON",
        "formattedText": "Another test message.",
        "markupSyntax": "MARKUP_SYNTAX_CHAT"
      },
      "configCompleteRedirectUri": "https://chat.google.com/api/bot_config_complete?token=<SCRUBBED>"
    }
  }
}
```

**Verification step — do not skip.** The original capture may still exist at
`C:\Users\mark\AppData\Local\Temp\cg-fixture\addon-message-event.json`. If it
does, confirm the committed fixture's *key structure* matches it exactly
(values will differ — that is the anonymization):

```bash
python - <<'PY'
import json, pathlib
def keys(n, p="$"):
    if isinstance(n, dict):
        for k, v in n.items():
            yield f"{p}.{k}"; yield from keys(v, f"{p}.{k}")
    elif isinstance(n, list):
        for i, v in enumerate(n): yield from keys(v, f"{p}[{i}]")
orig = pathlib.Path(r"C:\Users\mark\AppData\Local\Temp\cg-fixture\addon-message-event.json")
if not orig.exists():
    print("original capture is gone — structure check skipped (note it in the PR)"); raise SystemExit
a = set(keys(json.loads(orig.read_text(encoding="utf-8"))))
b = set(keys(json.loads(pathlib.Path("tests/fixtures/addon-message-event.json").read_text(encoding="utf-8"))))
print("MISSING from fixture:", sorted(a - b) or "none")
print("EXTRA in fixture:", sorted(b - a) or "none")
PY
```

Both lists must be empty. If they are not, fix the fixture — a structurally
wrong fixture would let a broken parser pass.

### Task 1.5 — Classic counterpart fixture

Create `tests/fixtures/classic-message-event.json` — the same logical event in
the classic envelope, so the two paths are testable symmetrically:

```json
{
  "type": "MESSAGE",
  "eventTime": "2026-07-29T12:55:58.782511Z",
  "space": {
    "name": "spaces/AAAAtestSpace",
    "type": "DM",
    "singleUserBotDm": true
  },
  "user": {
    "name": "users/000000000000000000001",
    "displayName": "Test User",
    "email": "agent-user@example.com",
    "type": "HUMAN"
  },
  "message": {
    "name": "spaces/AAAAtestSpace/messages/MSG1.MSG1",
    "sender": {
      "name": "users/000000000000000000001",
      "displayName": "Test User",
      "email": "agent-user@example.com",
      "type": "HUMAN"
    },
    "createTime": "2026-07-29T12:55:58.782511Z",
    "text": "Another test message.",
    "thread": {
      "name": "spaces/AAAAtestSpace/threads/MSG1"
    },
    "argumentText": "Another test message."
  },
  "configCompleteRedirectUrl": "https://chat.google.com/api/bot_config_complete?token=<SCRUBBED>"
}
```

Note the `Url`/`Uri` spelling difference from the add-on fixture. That is not a
typo — Google genuinely spells it `configCompleteRedirectUrl` in the classic
envelope and `configCompleteRedirectUri` in the add-ons one. Both fixtures
exist partly to pin that down.

### Task 1.6 — Synthetic add-on interaction fixture

Create `tests/fixtures/addon-card-clicked-event.json`. ⚠ Constructed from
Google's documented shape, **not** captured:

```json
{
  "commonEventObject": {
    "userLocale": "en",
    "hostApp": "CHAT",
    "platform": "WEB",
    "parameters": {
      "__action_method_name__": "verdict",
      "job_id": "job-123",
      "verdict": "reject",
      "nonce": "n-9"
    },
    "formInputs": {
      "reject_reason": {
        "stringInputs": {
          "value": ["wrong_seniority"]
        }
      }
    }
  },
  "chat": {
    "user": {
      "name": "users/000000000000000000001",
      "displayName": "Test User",
      "email": "agent-user@example.com",
      "type": "HUMAN"
    },
    "eventTime": "2026-07-29T13:10:00.000000Z",
    "buttonClickedPayload": {
      "space": {
        "name": "spaces/AAAAtestSpace",
        "type": "DM"
      },
      "message": {
        "name": "spaces/AAAAtestSpace/messages/MSG1.MSG1",
        "thread": {
          "name": "spaces/AAAAtestSpace/threads/MSG1"
        }
      },
      "isDialogEvent": false
    }
  }
}
```

### Task 1.7 — Confirm the guard actually guards

```bash
python -m pytest tests/test_fixtures_scrubbed.py -q
```

Then prove it is not vacuous — temporarily add a file with a live-looking
token, confirm the test **fails**, then delete it:

```bash
printf '{"configCompleteRedirectUri":"https://x/y?token=ya29.REALLOOKING"}' > tests/fixtures/_tmp-bad.json
python -m pytest tests/test_fixtures_scrubbed.py -q   # MUST fail
rm tests/fixtures/_tmp-bad.json
python -m pytest tests/test_fixtures_scrubbed.py -q   # MUST pass
```

A guard nobody has seen fail is not a guard. Do not commit `_tmp-bad.json`.

---

## Phase 2 — The normalizer

All of this is in `src/chat_gateway/adapters/pubsub.py` (hard rule #3:
Google-facing code lives only in `adapters/`).

### Task 2.1 — Module docstring and constants

Replace the module docstring's LIVE-UNVERIFIED paragraph:

```python
⚠ LIVE-UNVERIFIED: REST pull/acknowledge against the documented Pub/Sub v1
surface, written off-site. The FakePuller below is what the tests drive.
The 2026-07-29 live pull used an ad-hoc client, NOT PubSubPuller — this class
is still unexercised against Google.

⚠ SHAPE-VERIFIED 2026-07-29: the add-ons MESSAGE envelope is normalized against
a REAL captured payload replayed offline (tests/fixtures/addon-message-event.json).
Stronger than doc-derived, weaker than a live round-trip — the add-on
CARD_CLICKED path remains fully unverified (queue item CG-3).
```

> If spec §8's `⚠ SHAPE-VERIFIED` vocabulary was **declined** by the user,
> keep the plain `⚠ LIVE-UNVERIFIED` wording and describe the capture evidence
> in prose instead. Do not invent flag words on your own initiative.

Then add, after the existing `UNROUTED = "_unrouted"`:

```python
UNPARSEABLE = "UNPARSEABLE"

# chat.<key> -> normalized event_type. Google models these as a proto union
# ("payload can be only one of the following") with exactly these six members,
# and there is NO chat.type discriminator — the payload key IS the event type.
ADDON_PAYLOAD_TYPES = {
    "messagePayload": "MESSAGE",
    "buttonClickedPayload": "CARD_CLICKED",
    "addedToSpacePayload": "ADDED_TO_SPACE",
    "removedFromSpacePayload": "REMOVED_FROM_SPACE",
    "appCommandPayload": "APP_COMMAND",
    "widgetUpdatedPayload": "WIDGET_UPDATED",
}

# In the add-ons runtime Google passes the card's original action.function
# under this reserved parameter key. commonEventObject.invokedFunction was
# REMOVED from that runtime (add-ons release notes, 2025-05-12) but still
# exists classic-side — which makes assuming it a silent way to get
# action.id == "". Popped into action.id so the same card tapped under either
# runtime yields the same InboundReply.
ADDON_ACTION_KEY = "__action_method_name__"

# A per-message capability URL: visiting it erases the user's prompt, makes
# their private message PUBLIC in the space, and re-delivers it. Google spells
# it ...Uri in the add-ons envelope and ...Url in the classic one. Blanked from
# `raw` before anything is written to the audit trail or POSTed to a tenant
# callback (hard rule #2).
REDACTED = "<redacted-by-gateway>"
CAPABILITY_FIELDS = ("configCompleteRedirectUri", "configCompleteRedirectUrl")


class UnrecognizedEventError(ValueError):
    """The pulled bytes are not any Chat event envelope this gateway knows.

    Raised, never defaulted. Before 2026-07-29 an unparsed event silently
    normalized into a valid-looking empty MESSAGE — the exact class of silent
    failure hard rule #5 exists to prevent.
    """
```

### Task 2.2 — Envelope detection

Add above `normalize_event`:

```python
def detect_envelope(event) -> str:
    """Structural detection -> 'addon' | 'classic'; raises otherwise.

    Order matters: the add-ons shape is the more specific one (a classic event
    has no 'chat' object). A flat dict carrying space/message but no 'type' is
    deliberately UNRECOGNIZED rather than assumed classic — that assumption is
    the bug this replaces.
    """
    if not isinstance(event, dict):
        raise UnrecognizedEventError(f"event is {type(event).__name__}, not an object")
    if event.get("_undecodable"):
        raise UnrecognizedEventError("message data could not be base64/JSON decoded")
    if isinstance(event.get("chat"), dict):
        return "addon"
    if isinstance(event.get("type"), str) and event["type"]:
        return "classic"
    # Field NAMES only, never values — payloads carry capability URLs (rule #2).
    raise UnrecognizedEventError(
        "unrecognized Chat envelope: no 'chat' object (Workspace Add-ons "
        "runtime) and no non-empty 'type' string (classic); top-level keys: "
        f"{sorted(k for k in event if not k.startswith('_'))[:10]}"
    )
```

### Task 2.3 — Shared helpers

```python
def _derive_event_type(payload_key: str) -> str:
    """'widgetUpdatedPayload' -> 'WIDGET_UPDATED'.

    For payload types Google adds after this was written: named honestly from
    the wire, never defaulted to MESSAGE.
    """
    stem = payload_key[: -len("Payload")] if payload_key.endswith("Payload") else payload_key
    out: list[str] = []
    for ch in stem:
        if ch.isupper() and out:
            out.append("_")
        out.append(ch.upper())
    return "".join(out) or "UNKNOWN"


def _shape(*, envelope_format: str, event_type: str, space: str, message: dict,
           sender: dict, action: dict | None, dedupe_key: str | None) -> dict:
    """The ONE internal shape both formats normalize into. Keeping this
    identical to v0.1 (plus the additive envelope_format) is what leaves
    forwarder.py / inbox.py / registry.py untouched."""
    thread = message.get("thread") or {}
    return {
        "event_type": event_type,
        "space": space,
        "thread_key": thread.get("threadKey") or None,
        "thread_name": thread.get("name") or None,
        "message_id": message.get("name") or None,
        "sender_display": sender.get("displayName", ""),
        "sender_email": sender.get("email"),
        "text": message.get("text", ""),
        "action": action,
        "dedupe_key": dedupe_key,
        "envelope_format": envelope_format,
    }


def _action_params(raw_params) -> dict:
    """Classic sends action.parameters as a LIST of {"key","value"}; the
    add-ons runtime sends commonEventObject.parameters as a flat string->string
    MAP. Accept either — the add-on interaction shape is documented but not yet
    capture-verified (CG-3)."""
    if isinstance(raw_params, dict):
        return dict(raw_params)
    params: dict = {}
    for p in raw_params or []:
        if isinstance(p, dict) and p.get("key"):
            params[p["key"]] = p.get("value")
    return params


def _merge_form_inputs(container, params: dict) -> None:
    """formInputs nests identically in both runtimes —
    {name: {stringInputs: {value: [...]}}} — only the parent differs.
    (The extra [""] level in Google's samples is Apps Script only; over
    Pub/Sub the flat form is what arrives.)"""
    for name, spec in (container or {}).items():
        values = ((spec or {}).get("stringInputs") or {}).get("value") or []
        params.setdefault(name, values[0] if len(values) == 1 else values)
```

### Task 2.4 — Capability-URL redaction (DEC-7)

```python
def redact_capability_urls(event):
    """Return a deep copy of `event` with capability URLs blanked.

    `raw` is written to the JSONL audit trail and POSTed whole to tenant
    callbacks, so an unredacted configCompleteRedirect* would hand every
    opted-in tenant the ability to make a user's private message public.

    Rule #1 check: this matches Google-owned field NAMES exactly — never
    anything an application placed in the payload — so no app-domain
    knowledge enters the gateway.
    """
    if isinstance(event, dict):
        return {
            k: (REDACTED if k in CAPABILITY_FIELDS and isinstance(v, str)
                else redact_capability_urls(v))
            for k, v in event.items()
        }
    if isinstance(event, list):
        return [redact_capability_urls(v) for v in event]
    return event
```

### Task 2.5 — The two format extractors

```python
def _normalize_classic(event: dict) -> dict:
    """Classic Chat app envelope: flat type/space/message/user."""
    message = event.get("message") or {}
    sender = event.get("user") or message.get("sender") or {}
    space = (event.get("space") or message.get("space") or {}).get("name", "")
    common = event.get("common") or {}
    action = None
    if event.get("type") == "CARD_CLICKED" or event.get("action"):
        act = event.get("action") or {}
        params = _action_params(act.get("parameters"))
        for k, v in _action_params(common.get("parameters")).items():
            params.setdefault(k, v)
        # CARD_CLICKED puts form values under common.formInputs, but
        # SUBMIT_FORM (app home) uses commonEventObject.formInputs — the
        # classic envelope is not internally uniform, so check both parents.
        _merge_form_inputs(common.get("formInputs"), params)
        _merge_form_inputs((event.get("commonEventObject") or {}).get("formInputs"), params)
        action = {
            "id": act.get("actionMethodName") or act.get("function")
                  or common.get("invokedFunction") or "",
            "params": params,
        }
    return _shape(envelope_format="classic", event_type=event["type"],
                  space=space, message=message, sender=sender, action=action,
                  dedupe_key=event.get("_pubsub_message_id") or None)


def _normalize_addon(event: dict) -> dict:
    """Google Workspace Add-ons envelope: commonEventObject + chat.<x>Payload.

    ⚠ The CARD_CLICKED path here is documentation-derived, NOT capture-
    verified — no card button has been tapped against this deployment. Kept
    deliberately tolerant until queue item CG-3 confirms it.
    """
    chat = event.get("chat") or {}
    common = event.get("commonEventObject") or {}
    # Prefer a known payload key (stable order); else take any *Payload
    # deterministically, so a type Google adds later still routes.
    payload_key = next((k for k in ADDON_PAYLOAD_TYPES if isinstance(chat.get(k), dict)), None)
    if payload_key is None:
        payload_key = next((k for k in sorted(chat)
                            if k.endswith("Payload") and isinstance(chat[k], dict)), None)
    if payload_key is None:
        raise UnrecognizedEventError(
            "add-ons envelope carries no '*Payload' object under 'chat' "
            f"(keys: {sorted(chat)[:10]}) — nothing to route on"
        )
    payload = chat[payload_key]
    event_type = ADDON_PAYLOAD_TYPES.get(payload_key) or _derive_event_type(payload_key)
    message = payload.get("message") or {}
    # widgetUpdatedPayload carries ONLY space, and chat.space is a documented
    # non-payload sibling — three sources, and never assume message exists.
    space = (payload.get("space") or chat.get("space")
             or message.get("space") or {}).get("name", "")
    sender = chat.get("user") or message.get("sender") or {}

    params = _action_params(common.get("parameters"))
    action_id = params.pop(ADDON_ACTION_KEY, "")
    action = None
    if event_type == "CARD_CLICKED" or action_id or common.get("formInputs"):
        _merge_form_inputs(common.get("formInputs"), params)
        action = {
            "id": action_id
                  # invokedFunction was removed from this runtime in 2025-05;
                  # kept purely as a tolerant fallback until CG-3 confirms.
                  or common.get("invokedFunction")
                  or (payload.get("action") or {}).get("actionMethodName")
                  or "",
            "params": params,
        }
    return _shape(envelope_format="addon", event_type=event_type, space=space,
                  message=message, sender=sender, action=action,
                  dedupe_key=event.get("_pubsub_message_id") or None)
```

### Task 2.6 — Replace `normalize_event`

Replace the whole existing function (old lines 101–126) with:

```python
def normalize_event(event: dict) -> dict:
    """Extract the routable core of a Chat event; the raw rides along.

    Supports BOTH Google runtimes, because both will coexist for years while
    Google migrates and different consumers may sit behind different ones:

      * Workspace Add-ons  — commonEventObject + chat.<x>Payload
      * Classic Chat app   — flat type / space / message / user

    Normalizing a transport envelope is transport's job (hard rule #1 forbids
    owning an APPLICATION's schema, not recognizing Google's wire formats).

    Raises UnrecognizedEventError on anything else — never a silent MESSAGE.
    """
    if detect_envelope(event) == "addon":
        return _normalize_addon(event)
    return _normalize_classic(event)
```

---

## Phase 3 — Wiring: dispatch, loop, envelope, healthz

### Task 3.1 — Additive envelope field (DEC-3)

In `src/chat_gateway/envelope.py`, inside `InboundReply`, after `event_type`:

```python
    event_type: str = "MESSAGE"
    envelope_format: str = "classic"  # classic | addon | unparseable — which
                                      # Google runtime produced this event;
                                      # transport metadata, not app domain
```

### Task 3.2 — `dispatch` fails loudly without wedging the subscription

Replace the head of `dispatch` (through `core = normalize_event(event)`), and
change both `InboundReply(...)` constructions to pass the redacted `raw`:

```python
def _unparseable_core(event) -> dict:
    dedupe = event.get("_pubsub_message_id") if isinstance(event, dict) else None
    return _shape(envelope_format="unparseable", event_type=UNPARSEABLE,
                  space="", message={}, sender={}, action=None,
                  dedupe_key=dedupe or None)


def dispatch(event: dict, registry: Registry, inbox: Inbox,
             forwarder=None, reply_fn=None,
             now: dt.datetime | None = None,
             on_unparseable=None) -> list[str]:
    """Route one decoded Chat event. Per app: authorization allowlist check
    (jobhunt R4 — unauthorized users get an in-thread refusal and are never
    forwarded), then inbox + optional callback push (tenant opt-in).
    Returns the app ids that actually received the event.

    An event we cannot parse is audited under `_unrouted` as UNPARSEABLE and
    is NEVER attributed to a registered app: it has no space, so it cannot be
    routed, and a parse failure must not widen anyone's inbound surface
    (hard rule #6). `on_unparseable` lets the subscriber loop count it for
    /healthz without re-parsing.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    raw = redact_capability_urls(event)
    try:
        core = normalize_event(event)
    except Exception as exc:  # noqa: BLE001
        # Deliberately broad. A malformed event must never wedge the
        # subscription in a poison-pill redelivery loop (the caller still
        # acks), and must never be silent either: audited under _unrouted,
        # counted for /healthz, and printed. Three signals, permanently.
        print(f"subscriber: UNPARSEABLE event, audited under {UNROUTED}: "
              f"{type(exc).__name__}: {exc}", flush=True)
        inbox.put(InboundReply(app=UNROUTED, received_at=now, raw=raw,
                               **_unparseable_core(event)))
        if on_unparseable is not None:
            on_unparseable(exc)
        return [UNROUTED]
    candidates = registry.apps_for_space(core["space"]) or [UNROUTED]
    delivered = []
    for app_id in candidates:
        reply = InboundReply(app=app_id, received_at=now, raw=raw, **core)
```

The rest of the loop body (allow_inbound check, allowed_users check,
`inbox.put`, forwarder enqueue) is **unchanged**. Do not touch it — that is
the hard-rule-#6 authorization path.

### Task 3.3 — `SubscriberLoop` counter

In `__init__`, after `self.events_seen = 0`:

```python
        self.unparseable_seen = 0   # honest health: silent discards must show
```

In `poll_once`, pass the callback:

```python
        for ack_id, event in batch:
            dispatch(event, self._registry, self._inbox,
                     forwarder=self.forwarder, reply_fn=self.reply_fn,
                     on_unparseable=self._count_unparseable)
            self.events_seen += 1
            if ack_id:
                acks.append(ack_id)
```

And add the method:

```python
    def _count_unparseable(self, exc: Exception) -> None:
        self.unparseable_seen += 1
```

Acking is already unconditional on parse success, which is what drains the
poison pill — confirm you have not changed that.

### Task 3.4 — Honest healthz (hard rule #5)

In `src/chat_gateway/service.py`, the `subscriber` block of `healthz`:

```python
            "subscriber": (
                {"enabled": True,
                 "last_poll_at": subscriber.last_poll_at.isoformat() if subscriber.last_poll_at else None,
                 "events_seen": subscriber.events_seen,
                 "unparseable_seen": getattr(subscriber, "unparseable_seen", 0)}
                if subscriber is not None
                else {"enabled": False, "note": "tier 2 not enabled (GATEWAY_ENABLE_PUBSUB=0)"}
            ),
```

`getattr` with a default because `subscriber` is an injected `Any` and tests
pass doubles. Per spec §10 Q5, a non-zero count does **not** flip `status` to
`degraded` — that stays reserved for unresolvable config.

---

## Phase 4 — Tests

Extend `tests/test_adapters.py`. Add at the top:

```python
import json
from pathlib import Path

from chat_gateway.adapters.pubsub import (
    UNPARSEABLE, UnrecognizedEventError, detect_envelope, redact_capability_urls,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
```

### Task 4.1 — Update the existing classic test

`test_normalize_event` asserts exact dict equality and will fail on the new
key. Add `"envelope_format": "classic",` to its expected dict. Change nothing
else — the classic path's behaviour must be provably unaltered.

### Task 4.2 — The regression test that pins the actual bug

```python
def test_normalize_addon_message_from_real_capture():
    """The 2026-07-29 live bug: this real payload used to normalize into an
    empty husk with space="" and text="", which looked like a valid MESSAGE."""
    core = normalize_event(fixture("addon-message-event.json"))
    assert core == {
        "event_type": "MESSAGE",
        "space": "spaces/AAAAtestSpace",          # was "" — D2, routing dead
        "thread_key": None,                        # add-ons echoes no threadKey
        "thread_name": "spaces/AAAAtestSpace/threads/MSG1",
        "message_id": "spaces/AAAAtestSpace/messages/MSG1.MSG1",
        "sender_display": "Test User",
        "sender_email": "agent-user@example.com",
        "text": "Another test message.",           # was ""
        "action": None,
        "dedupe_key": None,
        "envelope_format": "addon",
    }


def test_both_formats_agree_on_the_same_logical_event():
    addon = normalize_event(fixture("addon-message-event.json"))
    classic = normalize_event(fixture("classic-message-event.json"))
    assert addon.pop("envelope_format") == "addon"
    assert classic.pop("envelope_format") == "classic"
    assert addon == classic
```

The second test is the real guarantee: consumers cannot tell which runtime
they are behind.

### Task 4.3 — Interaction parity

```python
def test_normalize_addon_card_clicked():
    """⚠ Documentation-derived shape (CG-3 replaces this with a real capture).
    The action id arrives as the reserved __action_method_name__ parameter —
    commonEventObject.invokedFunction was removed from this runtime in 2025-05.
    """
    core = normalize_event(fixture("addon-card-clicked-event.json"))
    assert core["event_type"] == "CARD_CLICKED"
    assert core["space"] == "spaces/AAAAtestSpace"
    assert core["action"] == {
        "id": "verdict",
        "params": {"job_id": "job-123", "verdict": "reject", "nonce": "n-9",
                   "reject_reason": "wrong_seniority"},
    }
    # the reserved key must NOT leak through to the tenant
    assert "__action_method_name__" not in core["action"]["params"]


def test_action_id_parity_across_formats():
    """Same card, same tap, same InboundReply — whichever runtime we sit behind."""
    from tests.test_callbacks import CARD_CLICK  # classic-format equivalent
    classic = normalize_event(CARD_CLICK)
    addon = normalize_event(fixture("addon-card-clicked-event.json"))
    assert classic["action"]["id"] == addon["action"]["id"] == "verdict"
    assert classic["action"]["params"] == addon["action"]["params"]


def test_addon_action_parameters_tolerate_list_form():
    """Defensive: we have never seen a real add-on interaction event. If Google
    sends the legacy list-of-{key,value} shape, we must still parse it."""
    event = fixture("addon-card-clicked-event.json")
    event["commonEventObject"]["parameters"] = [
        {"key": "__action_method_name__", "value": "verdict"},
        {"key": "job_id", "value": "job-123"},
    ]
    core = normalize_event(event)
    assert core["action"]["id"] == "verdict"
    assert core["action"]["params"]["job_id"] == "job-123"
```

> If importing `CARD_CLICK` across test modules is awkward under the project's
> pytest layout, copy the literal dict into `test_adapters.py` instead —
> do not weaken the assertion.

### Task 4.4 — Fail-loudly

```python
@pytest.mark.parametrize("bad", [
    {},
    {"foo": 1},
    {"space": {"name": "spaces/AAA"}, "message": {"text": "no type field"}},
    {"type": ""},
    {"chat": {}},                              # add-ons shell, no *Payload
    {"chat": {"user": {}, "eventTime": "x"}},  # non-payload fields only
    {"_undecodable": True},                    # pull() could not decode
    [],
    "not-an-object",
])
def test_unrecognized_envelope_raises(bad):
    """Never a silent MESSAGE default — that is defect D1."""
    with pytest.raises(UnrecognizedEventError):
        normalize_event(bad)


def test_detect_envelope_labels_both_formats():
    assert detect_envelope(fixture("addon-message-event.json")) == "addon"
    assert detect_envelope(fixture("classic-message-event.json")) == "classic"


def test_addon_unknown_payload_type_is_named_not_defaulted():
    """A payload type Google adds later must route, with an honest name."""
    core = normalize_event({
        "commonEventObject": {},
        "chat": {"user": {"displayName": "T"},
                 "somethingNewPayload": {"space": {"name": "spaces/AAAAtestSpace"}}},
    })
    assert core["event_type"] == "SOMETHING_NEW"   # never "MESSAGE"
    assert core["space"] == "spaces/AAAAtestSpace"
```

### Task 4.5 — Routing, containment, and the anti-poison-pill test

```python
ADDON_REGISTRY_YAML = REGISTRY_YAML.replace('spaces/AAA"', 'spaces/AAAAtestSpace"')


@pytest.fixture()
def addon_registry(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(ADDON_REGISTRY_YAML, encoding="utf-8")
    return load_registry(p)


def test_addon_event_routes_to_owning_app(addon_registry):
    """D2 fixed at the routing layer, not just the parsing layer."""
    inbox = Inbox()
    assert dispatch(fixture("addon-message-event.json"), addon_registry, inbox) == [
        "aiteam-harness"]
    reply = inbox.poll("aiteam-harness")[0]
    assert reply.text == "Another test message."
    assert reply.envelope_format == "addon"


def test_unparseable_is_audited_and_never_routed_to_a_tenant(registry):
    """Hard rule #6 guard: a parse failure must not widen anyone's inbound
    surface. It goes to _unrouted, labelled, and nowhere else."""
    inbox = Inbox()
    assert dispatch({"garbage": True}, registry, inbox) == [UNROUTED]
    assert inbox.pending_counts() == {UNROUTED: 1}
    audited = inbox.poll(UNROUTED)[0]
    assert audited.event_type == UNPARSEABLE
    assert audited.envelope_format == "unparseable"
    assert audited.space == ""
    assert audited.raw == {"garbage": True}      # nothing lost


def test_poll_once_acks_unparseable_events(registry):
    """Anti-poison-pill: garbage must not stall well-formed events behind it."""
    inbox = Inbox()
    puller = FakePuller([CHAT_EVENT, {"garbage": True}, CHAT_EVENT])
    loop = SubscriberLoop(puller, registry, inbox)
    assert loop.poll_once() == 3
    assert puller.acked == ["ack-0", "ack-1", "ack-2"]   # ALL acked
    assert loop.unparseable_seen == 1
    assert len(inbox.poll("aiteam-harness")) == 2        # good ones delivered
```

### Task 4.6 — Dedupe key and redaction

```python
def test_dedupe_key_survives_both_formats():
    for name in ("addon-message-event.json", "classic-message-event.json"):
        event = {**fixture(name), "_pubsub_message_id": "ps-99"}
        assert normalize_event(event)["dedupe_key"] == "ps-99"


def test_capability_url_is_redacted_in_both_spellings():
    """DEC-7: `raw` is audited to disk and POSTed whole to tenant callbacks.
    That URL makes a private message public — it must not travel."""
    for name, field in (("addon-message-event.json", "configCompleteRedirectUri"),
                        ("classic-message-event.json", "configCompleteRedirectUrl")):
        raw = redact_capability_urls(fixture(name))
        flat = json.dumps(raw)
        assert "bot_config_complete?token=" not in flat
        assert flat.count("<redacted-by-gateway>") == 1
        assert field in json.dumps(raw)          # key kept, value blanked


def test_dispatch_stores_redacted_raw(addon_registry):
    inbox = Inbox()
    dispatch(fixture("addon-message-event.json"), addon_registry, inbox)
    reply = inbox.poll("aiteam-harness")[0]
    assert reply.raw["chat"]["messagePayload"]["configCompleteRedirectUri"] == \
        "<redacted-by-gateway>"
    # everything else survives — forwarded "whole" minus one capability field
    assert reply.raw["chat"]["messagePayload"]["message"]["text"] == "Another test message."
```

### Task 4.7 — Full suite

```bash
python -m pytest -q
```

Expect **37 baseline + ~20 new**, all passing. If any pre-existing test broke,
stop and report rather than editing the assertion to match — the classic path
is supposed to be unchanged, so a classic-path failure is a real regression.

---

## Phase 5 — Docs for CG-1

### Task 5.1 — `docs/integration-guide.md`

After the "Rules of the road" paragraph (~line 97), add:

```markdown
### Which Google runtime you are behind

Google delivers Chat events in two envelope formats, depending on whether the
Chat app is deployed on the **Workspace Add-ons** runtime (`commonEventObject`
+ `chat.<x>Payload`) or as a **classic Chat app** (flat `type`/`space`/
`message`/`user`). Both are supported and normalize to the identical
`InboundReply` — you should never need to care which you are behind.

`envelope_format` (`classic` | `addon` | `unparseable`) tells you anyway, for
debugging.

Two real differences worth knowing:

- **`thread_key` may be `null` under the add-ons runtime.** Google echoes it
  only when the sender set one. Thread against `thread_name` if you need a
  stable handle for inbound events.
- **`raw.…configCompleteRedirectUri` / `…Url` arrives blanked** as
  `<redacted-by-gateway>`. It is a per-message capability URL — visiting it
  makes the user's private message public in the space — so the gateway does
  not propagate it. Everything else in `raw` is untouched.

An event the gateway cannot parse is never delivered to you: it is audited
under the reserved `_unrouted` id with `event_type: "UNPARSEABLE"` and counted
at `/healthz` → `subscriber.unparseable_seen`. It is never silently reshaped
into an empty `MESSAGE`.
```

### Task 5.2 — `docs/consumers/jobhunt.md`

Append to the R3 row's cell, or add below the table:

> **Runtime note (2026-07-29):** interactions are normalized identically under
> both Google runtimes — under the Workspace Add-ons runtime the action id
> arrives as the reserved `__action_method_name__` parameter and is lifted into
> `action.id`, so jobhunt's handler needs no change. ⚠ This path is
> documentation-derived and **not yet capture-verified** — no real card tap has
> been observed (queue item CG-3). R3/R4 must not be called verified until it is.

### Task 5.3 — `CLAUDE.md` status block

Update "Current status" — replace the date, and amend the LIVE-UNVERIFIED
bullet to reflect reality after this PR:

```markdown
## Current status (2026-07-29)

- **First real Chat event received 2026-07-29.** It arrived in the Workspace
  Add-ons envelope (`commonEventObject` + `chat.messagePayload`), which the
  v0.1 parser — written for the classic flat format — silently normalized into
  an empty MESSAGE husk. Fixed: `normalize_event` now detects and normalizes
  BOTH envelope formats to one internal shape, and raises rather than
  defaulting on anything it does not recognize. Unparseable events are audited
  under `_unrouted` as `UNPARSEABLE`, counted at `/healthz`, and still acked so
  they cannot wedge the subscription.
- ⚠ LIVE-UNVERIFIED (updated honestly):
  - Events DO reach `chat-gateway-sub` — proven 2026-07-29.
  - **Not** proven: which principal published them. Both
    `chat-api-push@system.gserviceaccount.com` and the add-ons service agent
    `service-<PROJECT_NUMBER>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com` are
    now bound, so the evidence is circumstantial.
  - `PubSubPuller.pull()/acknowledge()` — still unexercised; the live pull used
    an ad-hoc client, not our class.
  - Add-on **CARD_CLICKED** — no interaction event has ever been captured.
  - Chat API **send** and webhook **send** — unchanged, still unverified.
```

Do **not** delete any other ⚠ flag.

### Task 5.4 — Close out CG-1

Update `docs/BUILDER_QUEUE.md`: move CG-1 to **Recently shipped** with the PR
link and date, and refresh the last-updated banner.

PR body must include a **Docs Impact** section listing 5.1–5.4, and must state
plainly which ⚠ flags this PR clears (only the add-on MESSAGE shape, and only
as SHAPE-VERIFIED) and which it does not.

---

# Part B — CG-2: add-ons service agent + setup failure signature

Separate branch, separate PR: `fix/addons-service-agent-iac`. No `src/`
changes, and **no unit tests are possible** — the merge gate is review and doc
accuracy, not a green suite.

### Task 6.1 — `iac/gcloud-setup.sh`

Change the API-enable line (line 22–23):

```bash
echo "== enabling APIs (chat, pubsub, workspace add-ons)"
gcloud services enable chat.googleapis.com pubsub.googleapis.com gsuiteaddons.googleapis.com
```

Then insert immediately **after** the existing publisher grant (after line 35):

```bash
# ---------------------------------------------------------------------------
# The Workspace Add-ons runtime publishes as a PER-PROJECT service agent that
# DOES NOT EXIST until you create it. Omitting this is the failure that cost an
# hour on 2026-07-29: Chat shows "<app> is not responding", the add-ons metric
# logs code 13, and NOTHING ever reaches the topic.
#
# Honest caveat: after applying this, BOTH this principal and
# chat-api-push@system.gserviceaccount.com are bound, so we cannot prove which
# one actually delivered the first event. The correlation is strong but the
# evidence is circumstantial.
# ---------------------------------------------------------------------------
echo "== ensure the Workspace Add-ons service agent exists"
gcloud beta services identity create --service=gsuiteaddons.googleapis.com \
  --project="${PROJECT_ID}" >/dev/null

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
ADDONS_PUBLISHER="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"

echo "== grant the add-ons service agent publisher on the topic"
gcloud pubsub topics add-iam-policy-binding "${TOPIC}" \
  --member="${ADDONS_PUBLISHER}" --role="roles/pubsub.publisher" >/dev/null
```

`gcloud beta` requires the beta component; if it is missing gcloud prompts to
install it. Note that in the doc (Task 6.4).

### Task 6.2 — `iac/gcloud-setup.ps1`

Line 161–162 becomes:

```powershell
Write-Host '== enabling APIs (chat, pubsub, workspace add-ons)'
Invoke-Gcloud @('services', 'enable', 'chat.googleapis.com', 'pubsub.googleapis.com', 'gsuiteaddons.googleapis.com')
```

Insert after the existing publisher grant (after line 178):

```powershell
# The Workspace Add-ons runtime publishes as a per-project service agent that
# does not exist until created — omitting it is the 2026-07-29 field failure
# ("<app> is not responding", nothing in the subscription). See the .sh sibling
# for the full note, including why the fix is circumstantial evidence only.
Write-Host '== ensure the Workspace Add-ons service agent exists'
Invoke-Gcloud @('beta', 'services', 'identity', 'create',
    '--service=gsuiteaddons.googleapis.com', "--project=$ProjectId") -Quiet

$ProjectNumber = (& $script:Gcloud @('projects', 'describe', $ProjectId,
    '--format=value(projectNumber)') | Select-Object -First 1).ToString().Trim()
if (-not $ProjectNumber) {
    throw "could not resolve the project number for $ProjectId — cannot bind the add-ons service agent"
}
$AddonsPublisher = "serviceAccount:service-$ProjectNumber@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"

Write-Host "== grant the add-ons service agent publisher on the topic ($AddonsPublisher)"
Invoke-Gcloud @(
    'pubsub', 'topics', 'add-iam-policy-binding', $Topic,
    "--member=$AddonsPublisher", '--role=roles/pubsub.publisher'
) -Quiet
```

The `throw` is deliberate: a blank project number would silently bind
`service-@gcp-sa-…`, which GCP may accept without validating — reproducing
exactly the class of false-confidence the existing `chat-api-push` comment
already warns about.

Before editing, re-read `Invoke-Gcloud` / `Test-GcloudResource` at the top of
the file and match their calling convention; the snippet above assumes
`Invoke-Gcloud @(args) -Quiet` and direct `& $script:Gcloud` for value capture.

### Task 6.3 — `iac/terraform/main.tf`

Add `google-beta` to `required_providers` (`google_project_service_identity` is
beta-only):

```hcl
terraform {
  required_providers {
    google      = { source = "hashicorp/google", version = ">= 5.0" }
    google-beta = { source = "hashicorp/google-beta", version = ">= 5.0" }
  }
}
```

Add a provider block next to the existing one:

```hcl
provider "google-beta" {
  project = var.project_id
}
```

And after `google_pubsub_topic_iam_member.chat_publishes`:

```hcl
resource "google_project_service" "gsuiteaddons" {
  service            = "gsuiteaddons.googleapis.com"
  disable_on_destroy = false
}

# The Workspace Add-ons runtime publishes as a per-project service agent that
# does not exist until it is created. Missing it = the 2026-07-29 field
# failure: Chat reports "<app> is not responding" and nothing reaches the topic.
resource "google_project_service_identity" "gsuiteaddons" {
  provider   = google-beta
  service    = "gsuiteaddons.googleapis.com"
  depends_on = [google_project_service.gsuiteaddons]
}

resource "google_pubsub_topic_iam_member" "addons_publishes" {
  topic  = google_pubsub_topic.events.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_project_service_identity.gsuiteaddons.email}"
}
```

Validate offline: `cd iac/terraform && terraform init -backend=false && terraform validate`.

### Task 6.4 — `docs/google-cloud-setup.md`

Replace the existing "⚠ One VERIFY item" block (lines 65–72) with an honest
post-mortem, and extend steps 5–7:

```markdown
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

### Failure signature: "<app> is not responding"

If Chat replies **"<app> is not responding"** and nothing arrives in the
subscription, this is almost certainly the missing add-ons service agent.
Confirm by matching all four:

| Signal | Value |
|---|---|
| In Chat | `<app> is not responding` |
| `chat.googleapis.com/errors` | code **3**, "Can't post a reply" |
| `gsuiteaddons.googleapis.com/errors` | code **13**, "Unspecified error invoking the add-on" |
| `gcloud pubsub subscriptions pull chat-gateway-sub` | **zero** messages |

Fix (now built into both setup scripts, so this is only needed for projects
provisioned before 2026-07-29):

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
> pointed the wrong way. The only reliable signal is pulling the subscription:
>
> ```bash
> gcloud pubsub subscriptions pull chat-gateway-sub --limit=5 --auto-ack
> ```

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
```

### Task 6.5 — Close out CG-2

Move CG-2 to **Recently shipped** in `docs/BUILDER_QUEUE.md`, refresh the
banner, and add a Docs Impact section to the PR body.

---

# Part C — CG-3: live interaction capture (blocked on a human)

Not executable by Builder. Recorded so an unverified guess cannot quietly
become permanent.

**Recipe once a human can drive Chat:**

1. Send a card with a button to the app's space, e.g. via
   `POST /v1/messages` with a `cardsV2` payload carrying an `onClick.action`
   with `function: "verdict"` plus parameters and a `selectionInput`.
2. Tap the button in Google Chat.
3. Capture the raw envelope **before** the gateway sees it:
   ```bash
   gcloud pubsub subscriptions pull chat-gateway-sub --limit=1 --format=json > capture.json
   ```
4. Scrub it recursively — do **not** target paths by hand; run the committed
   guard over it after copying it into `tests/fixtures/`.
5. Replace `tests/fixtures/addon-card-clicked-event.json`, update
   `tests/fixtures/README.md` to mark it REAL with the capture date, and tighten
   `_normalize_addon` to what Google actually sends — in particular whether
   `__action_method_name__` is really how the action id arrives, and whether
   `parameters` is really a map.
6. Only then may the add-on CARD_CLICKED ⚠ flag be cleared, and only then may
   jobhunt R3/R4 be described as verified.

---

## Self-review

- **The Part A logic in this plan was executed against the REAL captured
  payload before the plan was handed over** (Planner-side, in a scratchpad —
  no repo code was written). All 35 checks passed, including: `space` and
  `text` extracted from the real add-on capture (defects D2/D1), classic ↔
  add-on parity on the same logical event, interaction parity on `action.id`
  and `action.params`, the legacy list-parameter tolerance, unknown-payload
  naming, `widgetUpdatedPayload` (space-only, no `message`) not crashing, all
  nine fail-loudly cases raising, dedupe-key survival in both formats, and
  redaction in both spellings without mutating the input. The code blocks above
  are therefore validated, not merely drafted — but they still need to be
  re-run inside the real module against the real test suite.
- **Spec coverage:** G1 (Phase 2), G2 (`_shape` unchanged; Phase 6 blast-radius
  list), G3 (Tasks 2.2/3.2/4.4), G4 (Tasks 2.5/4.3 + Part C), G5 (Task 4.6),
  G6 (Phase 1).
- **No placeholders:** every task carries literal code or a literal command.
  The two conditional branches (DEC-3, DEC-7 declined) are spelled out at the
  top rather than left as TBD.
- **Type consistency:** `normalize_event` returns the same dict keys from both
  paths because both go through `_shape()`; `InboundReply(**core)` therefore
  keeps working, and `envelope_format` is the only added key.
- **Untouched by design:** `forwarder.py`, `inbox.py`, `registry.py`,
  `auth.py`, `client.py`, `delivery.py`, `heartbeat.py`, `notifications.py`,
  `adapters/webhook.py`, `adapters/chat_api.py`, `__main__.py`, and the
  authorization loop inside `dispatch`.
- **Known risk:** the add-on interaction mapping is doc-confirmed but not
  capture-verified. It is tolerant by construction and tracked as CG-3. Nobody
  may claim it verified before that lands.
