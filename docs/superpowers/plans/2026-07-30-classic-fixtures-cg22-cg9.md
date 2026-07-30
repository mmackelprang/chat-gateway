# Implementation plan — CG-22 + CG-9: the real classic fixtures

**Items:** CG-22 (classic `CARD_CLICKED` fixture) + CG-9 (`ADDED_TO_SPACE`
regression fixture), shipped as **ONE PR**.
**Spec ancestry:** [`../specs/2026-07-29-live-verification-followups-design.md`](../specs/2026-07-29-live-verification-followups-design.md)
§3 (CG-9); CG-22's queue row is its own spec. No new spec is written — this plan
supersedes the CG-9 recipe in
[`2026-07-29-live-verification-followups.md`](2026-07-29-live-verification-followups.md#cg-9--added_to_space-fixture--blocked-on-a-human),
for the reason in §1.3 below.
**Baseline:** `python -m pytest -q` → **113 passed** (Windows dev box: `python`,
not `python3`). Take the real count from the suite, not from this line.
**Branch:** `feat/classic-fixtures` → PR → auto-merge eligible (no IaC, no
deploy path, no secret-handling *runtime* code — see §7 on why the guard change
does not trip the merge gate).

Hard rules 1, 2, 3 and 6 govern this work; **rule #2 is the load-bearing one**
and §2 is entirely about it. Rule #6 is untouched: nothing here widens any
tenant's inbound surface, and `aitrader` stays `allow_inbound: false`.

---

## 1. What changed since these two rows were written — read before executing

Both rows predate the 2026-07-30 live session. Five of their statements are now
wrong, and each correction below was **verified against the artifacts**, not
inferred. Builder should not execute the rows as written.

### 1.1 CG-22's stated source is not what its row claims

> CG-22's row: *"**Source** `…\cg-fixture\classic-cardclicked-event.json`
> (already redacted at capture time)"* … *"The capture arrives pre-redacted,
> which is not a reason to skip the guard — run it and let it prove the file
> clean."*

**It is not redacted.** Running the current guard's predicates against that file
flags **nine** leaves — the same nine kinds the raw formharvest capture carries:

```
PII    $.message.sender.name        <app user id>
PII    $.message.sender.avatarUrl   <googleusercontent proxy avatar URL>
TENANT $.message.space.customer     <customer id>
PII    $.user.name                  <human user id>
PII    $.user.displayName           <human display name>
PII    $.user.avatarUrl             <googleusercontent avatar URL>
PII    $.user.email                 <human email address>
TENANT $.user.domainId              <domain id>
TENANT $.space.customer             <customer id>
```

> **The flagged values are deliberately NOT reproduced in this document.** This
> repo is public, and a plan about scrubbing PII is not exempt from the rule it
> is enforcing. Run the guard yourself against the capture to see them — the
> paths above are what you need in order to do that, and the values are not.

This is exactly the situation the "extend the guard first, land the fixture
second, never hand-scrub by path" rule exists for, and it is the second time on
this project that a capture believed clean was not. The row's parenthetical is
struck in §8's queue edit.

### 1.2 A better capture exists, and the row does not know about it

`RAW-peek-01.json`, 2026-07-30: a `CARD_CLICKED` produced by **changing a
dropdown on a card that has no button at all**. Pulled off the live
subscription through the real `PubSubPuller` (pull only — deliberately not
acked, so it is still on the subscription and will redeliver; that is harmless
and is not a task). Its message text says so out loud: *"chat-gateway: change
the dropdown (no button) to capture the onChangeAction event shape."*

E1 showed `onChangeAction` fires on classic **in a throwaway project**. This is
the first observation of it on the production project `chat-gateway-gw`, in a
real consumer space, through our own puller. It is the capture CG-22's third
pinning requirement ("the `onChangeAction` event shape") actually needs, and the
row's named source does not contain it.

### 1.3 CG-9 is unblocked — and its target has changed runtime

The row is `⏸ blocked · needs a human` on *"a human removing and re-adding the
Chat app to a space."* **That happened on 2026-07-30T00:24:51Z**;
`RAW-classic-addedtospace.json` is the result.

But the row and the plan recipe both describe the **add-ons** shape and must be
rewritten, not merely unblocked:

| Row / recipe says | The capture we have |
|---|---|
| land it as `addon-added-to-space-event.json` | it is a **classic** event (`type: ADDED_TO_SPACE`, flat) |
| pins the `ADDON_PAYLOAD_TYPES` entry | classic never consults that table — `event["type"]` is used directly |
| pins the `chat.space` non-payload-sibling arm of the three-source space resolution | that arm is add-ons-only; classic resolves from `event["space"]` |
| pins `_shape` with an empty `message` | ✅ still true, and it is the one the row cared most about |

**The add-ons variant is now uncapturable.** `chat-gateway-prod` is deleted and
`chat-gateway-gw` runs a classic app with no `gsuiteaddons` deployment, so no
add-ons `addedToSpacePayload` can ever be produced again. That is the same class
of closure as the publisher-principal question — closed by circumstance, not
answered. Recorded so nobody re-files it as a gap.

**Honest limit of what did arrive:** the space is a **DM**
(`spaceType: DIRECT_MESSAGE`, `type: DM`, `singleUserBotDm: true`), not a
`ROOM`. Do not gloss this. It cuts two ways, and both go in the fixture README:

- *In its favour* — a DM `ADDED_TO_SPACE` carries **no `message` object at
  all**, which is precisely the `_shape` empty-message arm the item was filed
  to pin. A ROOM capture would not necessarily exercise it any harder.
- *Against* — a ROOM variant is **not** covered and differs at minimum in
  carrying `space.displayName`. Whether a ROOM `ADDED_TO_SPACE` can also carry a
  `message` (e.g. when the app is added by @mention) is **not observed here and
  must not be asserted either way**. Label it unobserved; do not label it
  impossible.

### 1.4 The guard does **not** need extending for `configCompleteRedirectUrl`

This is the correction most likely to be executed wrongly, because the intuition
is right and the fact is not. The ADDED_TO_SPACE capture does carry a live
capability URL:

```
"configCompleteRedirectUrl": "https://chat.google.com/api/bot_config_complete?token=<REDACTED>"
```

> The real token is a live bearer credential and is **not** reproduced here, not
> even as a prefix. It is in the raw capture, which never leaves the off-repo
> capture directory.

…and **the current guard already rejects it.** Two independent rules fire:
`SUSPECT_KEY` matches `redirecturl` inside the path `$.configCompleteRedirectUrl`,
and `SUSPECT_VALUE` matches `token=A`. Probed five ways against the real guard:

| Probe | Current guard |
|---|---|
| classic `configCompleteRedirectUrl` + `?token=…` | **REJECTED** |
| add-ons `configCompleteRedirectUri` + `?token=…` | **REJECTED** |
| same URL under a renamed, innocent key | **REJECTED** (via `SUSPECT_VALUE`) |
| token in the URL **path**, key still `…RedirectUrl` | **REJECTED** (via `SUSPECT_KEY`) |
| token in the path **and** the key renamed | ⚠ **passes** — see below |
| correctly scrubbed `?token=<SCRUBBED>` | passes (discrimination proven) |

Do **not** write a decorative "extension" that reimplements coverage that
already exists — that produces a guard that looks stronger and is not, which is
this project's recurring failure mode rather than a hypothetical one.

The last row is a real hole and is deliberately **not** closed here: catching it
needs a rule against high-entropy path segments, which would fire on space ids
and message ids that this repo has published a classification saying are
non-secret. It is written down in the README as a known limit (Task 3) rather
than papered over.

What the guard genuinely lacks is in §2.

### 1.5 An existing test hand-transcribes a capture that never landed

`tests/test_adapters.py::test_inbound_parameter_shape_is_a_runtime_property_not_a_direction_rule`
builds its classic half from an **inline dict typed out by hand** from the
formharvest capture (`"jobId": "mig-001"`, `"reason": "good_fit"`), and its own
docstring says *"Real captures land in CG-22."* This PR is CG-22. The
transcription is replaced with the fixture in Task 5.

That test also carries a comment the new capture refutes:

> `# the widget value rode along on the BUTTON's form inputs, with no`
> `# onChangeAction anywhere: one event per decision, not two.`

True of *that card*, which had no `onChangeAction`. Read as a general property
of the classic runtime it is false — a widget with an `onChangeAction` fires its
own event, and E1 saw both `onDecision` and `approve` arrive. Corrected in
Task 5. The wider doc consequences are routed in §6, **not** absorbed here.

---

## 2. What the guard actually needs, and why

Two changes. Both are guard-first: they land in the same commit as the fixtures
but **before** them in the diff order, and the fixtures must be added only once
the guard passes on them.

### 2.1 The capability-URL rule has never been proven to fire

`test_guard_rejects_unmarked_tenant_identifiers` exists because a scrub once
missed a tenant id, and its docstring makes the argument explicitly: *"A guard
that has never failed is a guard nobody has tested."*

That argument was never applied to the **capability-URL** rule — which exists
because a path-guess scrub wrote a **live bearer token** to disk, the worse of
the two 2026-07-29 incidents. DEC-7 is a documented single-field exception to
jobhunt R3 with **zero** test proving the guard enforces it. Until now no real
fixture had ever carried one: `classic-message-event.json`'s `<SCRUBBED>` value
was typed by a human into a CONSTRUCTED file, so the rule had never had to work.
CG-9's capture is the first real one.

### 2.2 The PII rule protects exactly one human, by name

```python
PII = re.compile(r"mackelprang|(?:users|members)/(?!0)\d{10,}|googleusercontent\.com", re.I)
```

The user-id half is structural — that is the design the fixtures README is
proud of. The `mackelprang` half is a **literal**, and it is the only rule in
the file that contradicts the file's own stated philosophy ("structural, not a
path allowlist"). Every classic capture carries `user.email`, and jobhunt R4 is
explicitly a **multi-user** authorization feature, so the next capture may
carry a different person's address — which the literal sails straight past.

An email **is** structurally detectable by the same RFC 2606 trick already used
for `domainId`/`customer`. A display **name** is not, and gets no rule: "Test
User" and a real name are indistinguishable to a regex, and a list of real names
committed to a public repo would be a worse artifact than the problem. That
limit is documented, not hidden.

> **Scope note for the user — this one is a judgement call.** The email rule
> catches **nothing** in today's three captures (the captured address is
> already caught by the existing literal rule). Its entire value is the *next*
> capture. It is
> included because this PR is the guard-first step for two fixtures that both
> carry a real email, and because the rule is eight lines. If you would rather
> it went in CG-26 (§8.4), drop Task 1b — nothing else in this plan depends on
> it.

---

## 3. Landing decision for the four staged captures

All four live in `%LOCALAPPDATA%\Temp\cg-fixture`.

| Capture | Decision | Why |
|---|---|---|
| `classic-cardclicked-formharvest.json` | **LAND** as `tests/fixtures/classic-cardclicked-button-event.json` | button-triggered classic `CARD_CLICKED` from the **live** project + real consumer space. It is also the capture an existing test already hand-transcribes (§1.5), so landing it deletes a transcription rather than adding a file. |
| `RAW-peek-01.json` | **LAND** as `tests/fixtures/classic-cardclicked-onchange-event.json` | the `onChangeAction` shape — CG-22's third pinning requirement, no add-ons equivalent, and the only classic capture pulled through the real `PubSubPuller` (it is the only one carrying `_pubsub_message_id`). |
| `RAW-classic-addedtospace.json` | **LAND** as `tests/fixtures/classic-added-to-space-event.json` | CG-9. |
| `classic-cardclicked-event.json` (E1's) | **DO NOT LAND** — *verify first, see below* | structurally redundant with formharvest, and from a **deleted throwaway project** rather than production. |

### 3.1 Builder must verify the redundancy rather than trust this table

Run this before deleting E1's capture from consideration. It compares the two
button-click captures by **key/type tree**, ignoring leaf values:

```python
# scratch script, not committed
import json
import re
from pathlib import Path

SRC = Path(r"C:\Users\mark\AppData\Local\Temp\cg-fixture")


def tree(node, path="$"):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            out.update(tree(v, f"{path}.{k}"))
        return out
    if isinstance(node, list):
        out = {}
        for i, v in enumerate(node):
            out.update(tree(v, f"{path}[]"))     # index collapsed: shape, not length
        return out
    return {path: type(node).__name__}


# A widget's NAME is the producer's choice, not a shape difference: E1's card
# named its dropdown `decision` and the migration card named it `reason`, so
# `common.formInputs.<name>` differs between ANY two cards. Collapsing it is
# what makes this a structural comparison rather than a card-content one.
NAMED = re.compile(r"(\.formInputs)\.[^.]+")


def norm(t):
    return {NAMED.sub(r"\1.<widget>", k): v for k, v in t.items()}


e1 = norm(tree(json.loads((SRC / "classic-cardclicked-event.json").read_text(encoding="utf-8"))))
fh = norm(tree(json.loads((SRC / "classic-cardclicked-formharvest.json").read_text(encoding="utf-8"))))

only_e1 = sorted(k for k in e1 if k not in fh)
only_fh = sorted(k for k in fh if k not in e1)
print("only in E1         :", json.dumps(only_e1, indent=2))
print("only in formharvest :", json.dumps(only_fh, indent=2))
print("outside echoed card :", [k for k in only_e1 + only_fh if ".cardsV2" not in k] or "NONE")
```

**Expected result** (this is the real output, run Planner-side):

```
only in E1         : [
  "$.message.cardsV2[].card.sections[].widgets[].selectionInput.onChangeAction.function"
]
only in formharvest : []
outside echoed card : NONE
```

One difference, and it is inside the *echoed card definition* — which the
normalizer never reads. There is **no** difference anywhere under `$.action`,
`$.common`, `$.user`, `$.space` or `$.thread`.

**Decision rule, so Builder does not have to judge:**

- If the diff is confined to the echoed card, **do not land E1's capture.**
  Record in the fixtures README that it was considered and why it was not landed
  (§ Task 3).
- If the diff shows any **event-level** key present in one and absent in the
  other, land **both**, name the differing key in the README, and say in the PR
  body that this plan's expected result did not hold.

E1's evidentiary role does not depend on the bytes being committed: it is
recorded in the queue's "What E1 and E2 settled" section and is CG-20's to write
into the ADR. A fixture is for pinning parser behaviour, and E1's pins nothing
that formharvest does not.

---

## 4. Anonymization — the exact mapping

DEC-5 (full anonymization) applies. Structure is preserved exactly: **every key,
every nesting level**; only leaf values change.

> **This table names SOURCES, never real values** — it is the fix for the leak
> described in §0.1. Each row says which JSON path in the raw capture holds the
> value to replace, so the mapping is fully executable without a single real
> identity literal entering this public repo. The scrub script in §7 builds its
> mapping by reading these paths, exactly as it already did for the app avatar.

| Source — path in the raw capture | Fixture value | Rule |
|---|---|---|
| `$.user.name` | `users/000000000000000000001` | zero-padded synthetic id (README convention) |
| `$.user.displayName` | `Test User` | |
| `$.user.avatarUrl` | `https://example.com/avatar.png` | |
| `$.user.email` | `agent-user@example.com` | RFC 2606 |
| `$.user.domainId` | `example1` | `TENANT_KEY` marker |
| `$.space.customer` | `customers/Cexample1` | `TENANT_KEY` marker |
| `$.message.sender.name` (the app) | `users/000000000000000000002` | matches `addon-buttonclicked-event.json`'s bot id |
| `$.message.sender.avatarUrl` (the app's `…/proxy/…`) | `https://example.com/app-avatar.png` | |
| `$.space.displayName` | `Test Room` | |
| `$.space.name` (+ its `spaceUri`, message and thread ids) — the ROOM captures | `spaces/AAAAclassicRoom` / `…/messages/MIG1.MIG1` / `…/messages/ONCH1.ONCH1` / `…/threads/MIG1` / `…/threads/ONCH1` | convention only — no guard rule, per README |
| `$.space.name` (+ its `spaceUri`) — the DM capture | `spaces/_AAAAtestDm` | **keeps the leading `_`** — a real DM space id starts with one, and CG-8 has just made `_` a reserved prefix for *app ids*. A fixture that quietly dropped it would remove the only real-shaped example of the near-collision. |
| `$.configCompleteRedirectUrl` | `?token=<SCRUBBED>` | DEC-7, identical to `classic-message-event.json` |

**Deliberately kept real:** `eventTime` / `createTime` / `lastActiveTime`
(timestamps, non-secret, and they *are* the provenance);
`_pubsub_message_id` (`20759411966000501`, `21339851456542226` — non-secret
message ids, and `addon-buttonclicked-event.json` keeps its own); the app's
display name `Chat Gateway` (an application's name, not a person's — same
precedent as `Agent Comms` in the landed add-ons fixture); every non-identity
value in the echoed card (`jobId`, `mig-001`, `good_fit`, `onVerdictChanged`,
`onchange-001`, `verdict`, `approve`) — those are the finding.

The three fixture files in Task 2 are the **result** of applying this table and
have already been run through the real guard and the real normalizer. Task 2.4
re-derives them from the raw captures and diffs, so the committed bytes are
proven faithful rather than trusted.

---

## Task 1 — Extend the guard, FIRST

**File:** `tests/test_fixtures_scrubbed.py`. Nothing else in this PR may be
committed before this task's tests pass.

### Task 1a — the capability-URL regression test

Append to the end of the file:

```python
# The real shape, from the 2026-07-30 ADDED_TO_SPACE capture: a `token=` query
# parameter carrying a long opaque bearer value. The value below is INVENTED —
# a real one must never be committed, not even inside a test that rejects it.
CAPABILITY_URL_SHAPE = (
    "https://chat.google.com/api/bot_config_complete?token="
    "AAAAtestNotARealTokenAAAAtestNotARealTokenAAAAtestNotARealToken%3D%3D"
)


def test_guard_rejects_an_unscrubbed_capability_url(tmp_path):
    """DEC-7 has been a documented rule since CG-1 and was never proven to fire.

    The tenant rule above got a regression test because a scrub had already
    missed a tenant id. The capability-URL rule — which exists because a
    path-guess scrub wrote a LIVE token to disk, the worse of the two incidents —
    got none. Until the 2026-07-30 classic ADDED_TO_SPACE capture, no real
    fixture had ever carried one, so the rule had never had to work.

    Both spellings, because Google uses `...Uri` in the add-ons envelope and
    `...Url` in the classic one, and the classic one is the one that has now
    actually arrived. Calls the real guard, for the reason in the docstring
    above.
    """
    for key, payload in (
        ("configCompleteRedirectUrl",
         {"type": "ADDED_TO_SPACE", "configCompleteRedirectUrl": CAPABILITY_URL_SHAPE}),
        ("configCompleteRedirectUri",
         {"chat": {"messagePayload": {"configCompleteRedirectUri": CAPABILITY_URL_SHAPE}}}),
    ):
        bad = tmp_path / f"bad-{key}.json"
        bad.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(AssertionError, match="looks like a credential"):
            test_fixture_contains_no_secrets(bad)

    ok = tmp_path / "ok-capability.json"
    ok.write_text(json.dumps({
        "configCompleteRedirectUrl":
            "https://chat.google.com/api/bot_config_complete?token=<SCRUBBED>"}),
        encoding="utf-8")
    test_fixture_contains_no_secrets(ok)
```

### Task 1b — the structural email rule *(droppable; see §2.2)*

Insert immediately after the `TENANT_KEY` block:

```python
# Email addresses — the same structural trick as TENANT_KEY, and it is here
# because PII above catches this author's address by LITERAL NAME
# (`mackelprang`), which protects exactly one human. Every classic capture
# carries `user.email`, and jobhunt R4 is explicitly a MULTI-USER authorization
# feature, so the next capture may well carry somebody else's address — which
# the literal would sail straight past. An email IS structurally detectable, so
# fixtures must use an RFC 2606 reserved domain and the guard enforces it.
#
# A display NAME is deliberately given no rule: "Test User" and a real name are
# indistinguishable to a regex, and a list of real names in a public repo is a
# worse artifact than the problem. That limit is recorded in fixtures/README.md
# rather than papered over.
EMAIL = re.compile(r"[\w.+%-]+@[\w-]+(?:\.[\w-]+)+")
EXAMPLE_DOMAIN = re.compile(r"@(?:[\w-]+\.)*example\.(?:com|org|net)\b", re.I)
```

Inside `test_fixture_contains_no_secrets`, insert immediately **before** the
`if TENANT_KEY.search(json_path):` block:

```python
        for addr in EMAIL.findall(value):
            assert EXAMPLE_DOMAIN.search(addr), (
                f"{path.name}{json_path} carries a real-looking email address "
                f"({addr}) — fixtures must use an RFC 2606 `example.*` domain; "
                "this repo is public"
            )
```

Append its regression test:

```python
def test_guard_rejects_a_non_example_email_address(tmp_path):
    """The literal-name rule protects one human; this protects the next one.

    The second case is a free-text leaf rather than an `email` key, because an
    address can ride in message text and the guard keys off value shape, not
    field name.
    """
    bad = tmp_path / "bad-email.json"
    bad.write_text(json.dumps(
        {"user": {"email": "someone@realcorp.io"},
         "message": {"text": "ping alice.smith@partner.co.uk about this"}}),
        encoding="utf-8")
    with pytest.raises(AssertionError, match="real-looking email"):
        test_fixture_contains_no_secrets(bad)

    ok = tmp_path / "ok-email.json"
    ok.write_text(json.dumps(
        {"user": {"email": "agent-user@example.com"},
         "message": {"text": "cc test@sub.example.org"}}), encoding="utf-8")
    test_fixture_contains_no_secrets(ok)
```

### Task 1c — prove it before going further

```
python -m pytest -q tests/test_fixtures_scrubbed.py
```

Must be green **with the existing four fixtures only**. If Task 1b makes any
already-landed fixture fail, stop — that is a finding about the landed
fixtures, not a reason to loosen the rule. (Verified Planner-side: all four
pass.)

---

## Task 2 — Land the three fixtures

### Task 2.1 — `tests/fixtures/classic-cardclicked-button-event.json`

```json
{
  "type": "CARD_CLICKED",
  "eventTime": "2026-07-30T00:26:59.445482Z",
  "message": {
    "name": "spaces/AAAAclassicRoom/messages/MIG1.MIG1",
    "sender": {
      "name": "users/000000000000000000002",
      "displayName": "Chat Gateway",
      "avatarUrl": "https://example.com/app-avatar.png",
      "type": "BOT"
    },
    "createTime": "2026-07-30T00:26:52.650943Z",
    "text": "chat-gateway: classic migration check - pick a reason, then Approve",
    "thread": {
      "name": "spaces/AAAAclassicRoom/threads/MIG1",
      "retentionSettings": {
        "state": "PERMANENT"
      }
    },
    "space": {
      "name": "spaces/AAAAclassicRoom",
      "type": "ROOM",
      "displayName": "Test Room",
      "spaceThreadingState": "THREADED_MESSAGES",
      "spaceType": "SPACE",
      "spaceHistoryState": "HISTORY_ON",
      "lastActiveTime": "2026-07-30T00:26:52.650943Z",
      "membershipCount": {
        "joinedDirectHumanUserCount": 1
      },
      "customer": "customers/Cexample1",
      "spaceUri": "https://chat.google.com/room/AAAAclassicRoom?cls=11"
    },
    "argumentText": "chat-gateway: classic migration check - pick a reason, then Approve",
    "cardsV2": [
      {
        "cardId": "migration-verify",
        "card": {
          "header": {
            "title": "chat-gateway",
            "subtitle": "classic migration verification"
          },
          "sections": [
            {
              "widgets": [
                {
                  "decoratedText": {
                    "text": "Pick a reason, then tap <b>Approve</b>.",
                    "wrapText": true
                  }
                },
                {
                  "selectionInput": {
                    "name": "reason",
                    "label": "Reason",
                    "type": "DROPDOWN",
                    "items": [
                      {
                        "text": "(choose)",
                        "value": "none",
                        "selected": true
                      },
                      {
                        "text": "Good fit",
                        "value": "good_fit"
                      },
                      {
                        "text": "Salary",
                        "value": "salary"
                      }
                    ]
                  }
                },
                {
                  "buttonList": {
                    "buttons": [
                      {
                        "text": "Approve",
                        "onClick": {
                          "action": {
                            "function": "approve",
                            "parameters": [
                              {
                                "key": "jobId",
                                "value": "mig-001"
                              }
                            ]
                          }
                        }
                      },
                      {
                        "text": "Reject",
                        "onClick": {
                          "action": {
                            "function": "reject",
                            "parameters": [
                              {
                                "key": "jobId",
                                "value": "mig-001"
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
    "formattedText": "chat-gateway: classic migration check - pick a reason, then Approve",
    "markupSyntax": "MARKUP_SYNTAX_CHAT"
  },
  "user": {
    "name": "users/000000000000000000001",
    "displayName": "Test User",
    "avatarUrl": "https://example.com/avatar.png",
    "email": "agent-user@example.com",
    "type": "HUMAN",
    "domainId": "example1"
  },
  "space": {
    "name": "spaces/AAAAclassicRoom",
    "type": "ROOM",
    "displayName": "Test Room",
    "spaceThreadingState": "THREADED_MESSAGES",
    "spaceType": "SPACE",
    "spaceHistoryState": "HISTORY_ON",
    "lastActiveTime": "2026-07-30T00:26:52.650943Z",
    "membershipCount": {
      "joinedDirectHumanUserCount": 1
    },
    "customer": "customers/Cexample1",
    "spaceUri": "https://chat.google.com/room/AAAAclassicRoom?cls=11"
  },
  "action": {
    "actionMethodName": "approve",
    "parameters": [
      {
        "key": "jobId",
        "value": "mig-001"
      }
    ]
  },
  "common": {
    "userLocale": "en",
    "hostApp": "CHAT",
    "timeZone": {
      "id": "America/New_York",
      "offset": -14400000
    },
    "formInputs": {
      "reason": {
        "stringInputs": {
          "value": [
            "good_fit"
          ]
        }
      }
    },
    "parameters": {
      "jobId": "mig-001"
    },
    "invokedFunction": "approve"
  },
  "thread": {
    "name": "spaces/AAAAclassicRoom/threads/MIG1"
  }
}
```

### Task 2.2 — `tests/fixtures/classic-cardclicked-onchange-event.json`

```json
{
  "type": "CARD_CLICKED",
  "eventTime": "2026-07-30T12:48:52.884583Z",
  "message": {
    "name": "spaces/AAAAclassicRoom/messages/ONCH1.ONCH1",
    "sender": {
      "name": "users/000000000000000000002",
      "displayName": "Chat Gateway",
      "avatarUrl": "https://example.com/app-avatar.png",
      "type": "BOT"
    },
    "createTime": "2026-07-30T02:31:09.634223Z",
    "text": "chat-gateway: change the dropdown (no button) to capture the onChangeAction event shape",
    "thread": {
      "name": "spaces/AAAAclassicRoom/threads/ONCH1",
      "retentionSettings": {
        "state": "PERMANENT"
      }
    },
    "space": {
      "name": "spaces/AAAAclassicRoom",
      "type": "ROOM",
      "displayName": "Test Room",
      "spaceThreadingState": "THREADED_MESSAGES",
      "spaceType": "SPACE",
      "spaceHistoryState": "HISTORY_ON",
      "lastActiveTime": "2026-07-30T02:31:09.634223Z",
      "membershipCount": {
        "joinedDirectHumanUserCount": 1
      },
      "customer": "customers/Cexample1",
      "spaceUri": "https://chat.google.com/room/AAAAclassicRoom?cls=11"
    },
    "argumentText": "chat-gateway: change the dropdown (no button) to capture the onChangeAction event shape",
    "cardsV2": [
      {
        "cardId": "onchange-capture",
        "card": {
          "header": {
            "title": "chat-gateway",
            "subtitle": "onChangeAction capture — change the dropdown ONLY"
          },
          "sections": [
            {
              "widgets": [
                {
                  "decoratedText": {
                    "text": "Just <b>change the dropdown</b>. There is no button on purpose — the dropdown itself is what we need to capture.",
                    "wrapText": true
                  }
                },
                {
                  "selectionInput": {
                    "name": "verdict",
                    "label": "Verdict",
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
                      "function": "onVerdictChanged",
                      "parameters": [
                        {
                          "key": "jobId",
                          "value": "onchange-001"
                        }
                      ]
                    }
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
    "formattedText": "chat-gateway: change the dropdown (no button) to capture the onChangeAction event shape",
    "markupSyntax": "MARKUP_SYNTAX_CHAT"
  },
  "user": {
    "name": "users/000000000000000000001",
    "displayName": "Test User",
    "avatarUrl": "https://example.com/avatar.png",
    "email": "agent-user@example.com",
    "type": "HUMAN",
    "domainId": "example1"
  },
  "space": {
    "name": "spaces/AAAAclassicRoom",
    "type": "ROOM",
    "displayName": "Test Room",
    "spaceThreadingState": "THREADED_MESSAGES",
    "spaceType": "SPACE",
    "spaceHistoryState": "HISTORY_ON",
    "lastActiveTime": "2026-07-30T02:31:09.634223Z",
    "membershipCount": {
      "joinedDirectHumanUserCount": 1
    },
    "customer": "customers/Cexample1",
    "spaceUri": "https://chat.google.com/room/AAAAclassicRoom?cls=11"
  },
  "action": {
    "actionMethodName": "onVerdictChanged",
    "parameters": [
      {
        "key": "jobId",
        "value": "onchange-001"
      }
    ]
  },
  "common": {
    "userLocale": "en",
    "hostApp": "CHAT",
    "timeZone": {
      "id": "America/New_York",
      "offset": -14400000
    },
    "formInputs": {
      "verdict": {
        "stringInputs": {
          "value": [
            "approve"
          ]
        }
      }
    },
    "parameters": {
      "jobId": "onchange-001"
    },
    "invokedFunction": "onVerdictChanged"
  },
  "thread": {
    "name": "spaces/AAAAclassicRoom/threads/ONCH1"
  },
  "_pubsub_message_id": "20759411966000501"
}
```

### Task 2.3 — `tests/fixtures/classic-added-to-space-event.json`

```json
{
  "type": "ADDED_TO_SPACE",
  "eventTime": "2026-07-30T00:24:51.910485Z",
  "user": {
    "name": "users/000000000000000000001",
    "displayName": "Test User",
    "avatarUrl": "https://example.com/avatar.png",
    "email": "agent-user@example.com",
    "type": "HUMAN",
    "domainId": "example1"
  },
  "space": {
    "name": "spaces/_AAAAtestDm",
    "type": "DM",
    "singleUserBotDm": true,
    "spaceThreadingState": "THREADED_MESSAGES",
    "spaceType": "DIRECT_MESSAGE",
    "spaceHistoryState": "HISTORY_ON",
    "lastActiveTime": "2026-07-30T00:24:51.910485Z",
    "membershipCount": {
      "joinedDirectHumanUserCount": 1
    },
    "spaceUri": "https://chat.google.com/dm/_AAAAtestDm?cls=11"
  },
  "configCompleteRedirectUrl": "https://chat.google.com/api/bot_config_complete?token=<SCRUBBED>",
  "_pubsub_message_id": "21339851456542226"
}
```

### Task 2.4 — prove the committed bytes are faithful, don't trust the transcription

The three blocks above are a transcription into a markdown file, which is
exactly the artifact class this repo distrusts. Re-derive them from the raw
captures and diff. Scratch script, not committed:

```python
import json
from pathlib import Path

SRC = Path(r"C:\Users\mark\AppData\Local\Temp\cg-fixture")
DST = Path(r"D:\prj\chat-gateway\tests\fixtures")
CAP = "https://chat.google.com/api/bot_config_complete?token=<SCRUBBED>"

# --- the mapping is DERIVED, never typed -------------------------------------
# NO REAL IDENTITY LITERAL APPEARS IN THIS FILE. Every real value is read out of
# a raw capture by path (the paths are 4's table). This repo is PUBLIC, and a
# scrub script that hardcodes what it is scrubbing publishes exactly what it
# exists to remove — which is precisely how the first draft of this plan leaked
# (0.1). The captures never leave the off-repo capture directory, so the real
# values stay there and the executable mapping still works.
_seed = json.loads((SRC / "classic-cardclicked-formharvest.json").read_text(
    encoding="utf-8"))                       # the only capture carrying all paths
_user, _space, _bot = _seed["user"], _seed["space"], _seed["message"]["sender"]

COMMON = {
    _user["name"]:         "users/000000000000000000001",
    _user["displayName"]:  "Test User",
    _user["avatarUrl"]:    "https://example.com/avatar.png",
    _user["email"]:        "agent-user@example.com",
    _user["domainId"]:     "example1",
    _space["customer"]:    "customers/Cexample1",
    _bot["name"]:          "users/000000000000000000002",
    _bot["avatarUrl"]:     "https://example.com/app-avatar.png",
    _space["displayName"]: "Test Room",
}


def space_map(raw, synthetic):
    """{space id, spaceUri} -> synthetic, read off the capture rather than typed."""
    name = raw["space"]["name"]                       # e.g. spaces/<real>
    real = name.split("/", 1)[1]
    m = {name: f"spaces/{synthetic}"}
    uri = raw["space"].get("spaceUri")
    if uri:
        m[uri] = uri.replace(real, synthetic)
    return m


def msg_map(raw, synthetic, tag):
    """message + thread ids -> synthetic. Empty when the event carries no message."""
    msg = raw.get("message") or {}
    m = {}
    if msg.get("name"):
        m[msg["name"]] = f"spaces/{synthetic}/messages/{tag}.{tag}"
    thread = ((msg.get("thread") or raw.get("thread")) or {}).get("name")
    if thread:
        m[thread] = f"spaces/{synthetic}/threads/{tag}"
    return m


def sub(node, mapping):
    if isinstance(node, dict):
        return {k: (CAP if k in ("configCompleteRedirectUrl", "configCompleteRedirectUri")
                    else sub(v, mapping)) for k, v in node.items()}
    if isinstance(node, list):
        return [sub(v, mapping) for v in node]
    if isinstance(node, str):
        for a, b in mapping.items():
            node = node.replace(a, b)
        return node
    return node


def leaves(node, path="$"):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from leaves(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from leaves(v, f"{path}[{i}]")
    else:
        yield path, node


# (raw name, landed name, synthetic space id, message/thread tag, leaves, changed)
JOBS = [
    ("classic-cardclicked-formharvest.json", "classic-cardclicked-button-event.json",
     "AAAAclassicRoom", "MIG1", 76, 18),
    ("RAW-peek-01.json", "classic-cardclicked-onchange-event.json",
     "AAAAclassicRoom", "ONCH1", 72, 18),
    ("RAW-classic-addedtospace.json", "classic-added-to-space-event.json",
     "_AAAAtestDm", None, 19, 8),
]

for raw_name, out_name, space_syn, tag, want_leaves, want_changed in JOBS:
    raw = json.loads((SRC / raw_name).read_text(encoding="utf-8"))
    mapping = {**COMMON, **space_map(raw, space_syn)}
    if tag:
        mapping.update(msg_map(raw, space_syn, tag))
    # longest keys first, so message/thread ids beat the bare space id
    ordered = dict(sorted(mapping.items(), key=lambda kv: -len(kv[0])))
    derived = sub(raw, ordered)

    rl, dl = list(leaves(raw)), list(leaves(derived))
    assert [k for k, _ in rl] == [k for k, _ in dl], f"{out_name}: key/type tree CHANGED"
    changed = sum(1 for (_, a), (_, b) in zip(rl, dl) if a != b)
    assert len(rl) == want_leaves, f"{out_name}: {len(rl)} leaves, expected {want_leaves}"
    assert changed == want_changed, f"{out_name}: {changed} changed, expected {want_changed}"

    committed = json.loads((DST / out_name).read_text(encoding="utf-8"))
    assert committed == derived, f"{out_name}: committed bytes DIFFER from re-derived"
    print(f"{out_name}: {len(rl)} leaves both sides, identical key/type tree, "
          f"{changed} changed leaf values, committed == re-derived")
```

Expected output (verified Planner-side):

```
classic-cardclicked-button-event.json: 76 leaves both sides, identical key/type tree, 18 changed leaf values, committed == re-derived
classic-cardclicked-onchange-event.json: 72 leaves both sides, identical key/type tree, 18 changed leaf values, committed == re-derived
classic-added-to-space-event.json: 19 leaves both sides, identical key/type tree, 8 changed leaf values, committed == re-derived
```

If the raw captures are no longer on disk, skip this task and say so in the PR
body — the guard plus the tests in Tasks 4–6 still stand on their own, but the
faithfulness claim does not, and must not be made.

### Task 2.5 — run the guard against the raw captures, then the landed ones

```
python -m pytest -q tests/test_fixtures_scrubbed.py
```

Now 7 fixture files → 7 parametrized cases, all green. Then confirm the guard
would have *caught* each raw capture (scratch, not committed) — expected counts
**6 / 9 / 9** violations for addedtospace / peek-01 / formharvest respectively.
A guard that passes the clean file but was never shown to fail on the dirty one
proves nothing.

---

## Task 3 — `tests/fixtures/README.md`

Add three rows to the provenance table, immediately after the
`addon-buttonclicked-event.json` row:

```markdown
| `classic-cardclicked-button-event.json` | **REAL** — captured 2026-07-30 from the live project `chat-gateway-gw`, in the real consumer space, after the classic migration. A card posted by our own `ChatApiAdapter`; a dropdown changed, then a button tapped. The classic counterpart of the add-ons capture above, and the contrast is the point: `action.id` resolves **natively** here (`approve`, `id_source: "google"`) where the add-ons capture resolves to `None`. |
| `classic-cardclicked-onchange-event.json` | **REAL** — captured 2026-07-30, and **the card had no button**. Changing a selection widget was itself the interaction: `onChangeAction.function` arrived as the action identity and the changed value was harvested into params. There is no add-ons equivalent — an `onChangeAction` dies under that runtime with `gsuiteaddons.googleapis.com/errors` code 13 — so this is new coverage, not parity coverage. The only classic capture pulled through the real `PubSubPuller`, which is why it is the only one carrying `_pubsub_message_id`. |
| `classic-added-to-space-event.json` | **REAL** — captured 2026-07-30T00:24:51Z, the Chat app removed from a space and re-added. First real bytes for a non-MESSAGE, non-CARD_CLICKED event, and the first real capture ever to carry a live `configCompleteRedirectUrl` (scrubbed here per DEC-7). ⚠ It is a **DM** (`spaceType: DIRECT_MESSAGE`), not a ROOM — see below. |
```

Then add these two sections before `## Anonymization`:

```markdown
### What the ADDED_TO_SPACE capture does and does not prove

It exercises, on real bytes, the classic path with **no `message` object at
all**: `_shape`'s empty-message arm resolves `thread_key`, `thread_name` and
`message_id` to `None` and `text` to `""` without a KeyError, and `action`
stays `None` because the event is neither `CARD_CLICKED` nor carries an
`action` object. That empty-message arm is the thing queue item CG-9 was filed
to pin.

It does **not** cover the ROOM variant, which differs at minimum in carrying
`space.displayName`. Whether a ROOM `ADDED_TO_SPACE` can also carry a `message`
— for instance when the app is added by @mention — is **not observed** and is
not asserted either way here.

CG-9 originally asked for the **add-ons** shape (`chat.addedToSpacePayload`),
which would have pinned the `ADDON_PAYLOAD_TYPES` entry and the `chat.space`
non-payload-sibling arm. Those bytes can never be captured now: the add-ons
project is deleted and the live project runs a classic app. Closed by
circumstance, like the publisher-principal question — not a gap anyone should
re-file.

### E1's capture, considered and deliberately not landed

A third classic `CARD_CLICKED` exists — E1's 2026-07-29 probe, from a throwaway
project that has since been deleted. It was diffed against
`classic-cardclicked-button-event.json` by key/type tree and the only
differences sit inside the **echoed card definition**, which the normalizer
never reads. It pins nothing the landed capture does not, and it comes from a
project that no longer exists. E1's evidentiary role is recorded in
`docs/BUILDER_QUEUE.md` and belongs to ADR-0001, not to a fixture.

### Known limits of the guard, stated rather than implied

- **Display names are not structurally detectable.** `"Test User"` and a real
  name are indistinguishable to a regex, and a list of real names committed to a
  public repo would be a worse artifact than the problem. Anonymizing them is a
  convention enforced by review, not by the guard.
- **A capability URL carrying its token in the URL *path*, under a key that does
  not match `redirecturi|redirecturl`, would pass.** Catching it needs a
  high-entropy-path-segment rule, which would fire on the space and message ids
  that `docs/google-cloud-setup.md` step 8 classifies as non-secret. Both real
  spellings Google uses put the token in a `token=` query parameter, and both
  are caught twice over.
```

Finally, in the `## Anonymization` section, extend the `configCompleteRedirectUri`
paragraph — it names only the add-ons spelling and the classic one has now
actually arrived:

```markdown
`configCompleteRedirectUri` (add-ons) / `configCompleteRedirectUrl` (classic) is
a per-message capability URL: visiting it makes the user's private message
public in the space and re-delivers it. Its value is always `<SCRUBBED>` here.
The classic spelling sits at the **root** of the event, not nested under a
payload; that placement is first-hand as of the 2026-07-30 ADDED_TO_SPACE
capture, and `test_guard_rejects_an_unscrubbed_capability_url` proves the guard
rejects an unscrubbed one in either spelling.
```

---

## Task 4 — the classic `CARD_CLICKED` tests

**File:** `tests/test_adapters.py`. Append after the existing
`# --- the real add-on interaction capture (CG-3) ---` block.

```python
# --- the real CLASSIC captures (CG-22) ---------------------------------------


def test_normalize_real_classic_button_click():
    """REAL capture, 2026-07-30, live project `chat-gateway-gw`, real consumer space.

    The classic counterpart of `test_normalize_real_addon_button_click`, and the
    contrast is the point: the add-ons capture resolves `action.id` to None
    because topic-as-function ate the identity slot, and this one resolves it
    NATIVELY from `action.actionMethodName`.
    """
    core = normalize_event(fixture("classic-cardclicked-button-event.json"))
    assert core["envelope_format"] == "classic"
    assert core["event_type"] == "CARD_CLICKED"
    assert core["space"] == "spaces/AAAAclassicRoom"
    assert core["thread_name"] == "spaces/AAAAclassicRoom/threads/MIG1"
    assert core["message_id"] == "spaces/AAAAclassicRoom/messages/MIG1.MIG1"
    # the TAPPER, not the BOT that posted the card
    assert core["sender_display"] == "Test User"
    assert core["action"] == {
        "id": "approve",
        "id_source": "google",
        # jobId from action.parameters (the ARRAY), reason harvested from
        # common.formInputs at submit time — one event, both sources merged.
        "params": {"jobId": "mig-001", "reason": "good_fit"},
    }


def test_classic_supplies_action_identity_natively_unlike_the_addon_capture():
    """E1's headline result, now pinned against real bytes from BOTH runtimes.

    `__cg_action__` is the FALLBACK that keeps a card working on the add-ons
    side; this is why it is a fallback and not the mechanism. Neither capture
    carries `__cg_action__` — the difference is entirely Google's.
    """
    classic = normalize_event(fixture("classic-cardclicked-button-event.json"))
    addon = normalize_event(fixture("addon-buttonclicked-event.json"))
    assert (classic["action"]["id"], classic["action"]["id_source"]) == ("approve", "google")
    assert (addon["action"]["id"], addon["action"]["id_source"]) == (None, None)


def test_normalize_real_classic_onchange_with_no_button_at_all():
    """REAL capture, 2026-07-30 — and the card had NO BUTTON.

    A selection widget is ITSELF an interaction trigger on the classic runtime:
    changing the dropdown produced this whole event, with the widget's own
    `onChangeAction.function` as the action identity and the changed value
    harvested into params. There is no add-ons equivalent — under add-ons an
    `onChangeAction` dies with `gsuiteaddons.googleapis.com/errors` code 13 —
    so this is NEW coverage, not parity coverage.

    Note `dedupe_key`: this is the only classic capture pulled through the real
    `PubSubPuller`, which is what injects `_pubsub_message_id`.
    """
    event = fixture("classic-cardclicked-onchange-event.json")

    # the card really had no button — otherwise this proves nothing
    widgets = event["message"]["cardsV2"][0]["card"]["sections"][0]["widgets"]
    assert not any("buttonList" in w for w in widgets)
    selection = next(w["selectionInput"] for w in widgets if "selectionInput" in w)
    assert selection["onChangeAction"]["function"] == "onVerdictChanged"

    core = normalize_event(event)
    assert core["envelope_format"] == "classic"
    assert core["event_type"] == "CARD_CLICKED"
    assert core["action"] == {
        "id": "onVerdictChanged",
        "id_source": "google",
        "params": {"jobId": "onchange-001", "verdict": "approve"},
    }
    assert core["dedupe_key"] == "20759411966000501"


def test_detect_envelope_labels_the_real_classic_captures():
    for name in ("classic-cardclicked-button-event.json",
                 "classic-cardclicked-onchange-event.json",
                 "classic-added-to-space-event.json"):
        assert detect_envelope(fixture(name)) == "classic"
```

---

## Task 5 — replace the hand-transcription in the parameter-shape test

**File:** `tests/test_adapters.py`. Replace the whole of
`test_inbound_parameter_shape_is_a_runtime_property_not_a_direction_rule`
(currently ~line 927) with:

```python
def test_inbound_parameter_shape_is_a_runtime_property_not_a_direction_rule():
    """The correction to a correction, and worth pinning precisely.

    It is tempting to summarize the shapes as "you send an array, you receive a
    map". That is WRONG, and it was briefly written down that way. The map is an
    **add-ons-runtime** quirk, not a property of the inbound direction:

        outbound, every runtime -> ARRAY of {"key","value"}   (Cards v2)
        inbound, classic        -> ARRAY under action.parameters (symmetric!)
        inbound, add-ons        -> MAP under commonEventObject.parameters

    Both inbound shapes are now first-hand AND landed: the add-ons map from
    addon-buttonclicked-event.json, the classic array from
    classic-cardclicked-button-event.json. This test previously hand-transcribed
    the classic half from a capture that had not been committed; CG-22 landed the
    fixture and the transcription is gone.

    The reason this matters to a reader rather than only to us: a producer
    debugging a raw classic event who had been told "inbound is a map" would
    conclude the gateway was broken.
    """
    addon_cap = fixture("addon-buttonclicked-event.json")
    classic_cap = fixture("classic-cardclicked-button-event.json")

    assert isinstance(addon_cap["commonEventObject"]["parameters"], dict)
    assert isinstance(classic_cap["action"]["parameters"], list)
    assert classic_cap["action"]["parameters"] == [{"key": "jobId", "value": "mig-001"}]

    # ...and both inbound shapes flatten to the same kind of thing, which is why
    # a producer never has to know any of the above.
    assert normalize_event(classic_cap)["action"]["params"] == {
        "jobId": "mig-001", "reason": "good_fit"}
    assert _action_params(addon_cap["commonEventObject"]["parameters"]) == {
        "probe": "topic-as-fn"}
```

**The deleted comment matters more than the deleted dict.** The old body ended
with:

```python
        # the widget value rode along on the BUTTON's form inputs, with no
        # onChangeAction anywhere: one event per decision, not two.
```

That describes *that card* correctly and the *runtime* incorrectly, and
`classic-cardclicked-onchange-event.json` now sits three tests above it proving
the general form false. It is removed here rather than reworded, because the
correct wording is a doc change that belongs to CG-11 — see §6.

`CLAUDE.md`'s parameter-shape table cites this test by name and its claims are
unchanged and now better evidenced, so **no `CLAUDE.md` edit is needed for the
table.**

---

## Task 6 — the `ADDED_TO_SPACE` tests (CG-9)

**File:** `tests/test_adapters.py`, appended after Task 4's block.

```python
# --- the real CLASSIC ADDED_TO_SPACE capture (CG-9) ---------------------------


def test_normalize_real_classic_added_to_space():
    """REAL capture, 2026-07-30T00:24:51Z — the app added to a DM space.

    Whole-dict equality on purpose: the value of this fixture is the fields that
    are ABSENT. There is no `message` at all, so `_shape`'s empty-message arm
    runs for real — thread/message ids resolve to None and `text` to "" without
    a KeyError — and `action` stays None because the event is neither
    CARD_CLICKED nor carries an `action` object.

    A DM, not a ROOM. That is not a weaker case for this particular arm — a DM
    ADDED_TO_SPACE carries no message object at all — but the ROOM variant is
    genuinely uncovered; see tests/fixtures/README.md.
    """
    assert normalize_event(fixture("classic-added-to-space-event.json")) == {
        "event_type": "ADDED_TO_SPACE",
        "space": "spaces/_AAAAtestDm",
        "thread_key": None,
        "thread_name": None,
        "message_id": None,
        "sender_display": "Test User",
        "sender_email": "agent-user@example.com",
        "text": "",
        "action": None,
        "dedupe_key": "21339851456542226",
        "envelope_format": "classic",
    }


def test_classic_added_to_space_carries_the_capability_url_at_the_ROOT():
    """`CAPABILITY_FIELDS`' classic spelling was doc-derived until this capture.

    The placement is the fact worth pinning: Google puts
    `configCompleteRedirectUrl` at the TOP LEVEL of a classic event, not nested
    under a payload as the add-ons `...Uri` is. `redact_capability_urls`
    recurses, so either placement works — but a reader hunting for the field
    should not have to guess, and the CONSTRUCTED classic fixture guessed the
    root and turns out to have been right.

    The value here is `<SCRUBBED>`, so this proves the KEY match. That the
    redactor blanks a token-bearing VALUE is covered by
    `test_capability_url_is_redacted_in_both_spellings`.
    """
    raw = fixture("classic-added-to-space-event.json")
    assert "configCompleteRedirectUrl" in raw            # root, not nested
    redacted = redact_capability_urls(raw)
    assert redacted["configCompleteRedirectUrl"] == "<redacted-by-gateway>"
```

---

## Task 7 — docstrings and the flag ledger

Hard rule #3 keeps flags in docstrings. Three edits, all narrow.

### Task 7.1 — `src/chat_gateway/adapters/pubsub.py`, module docstring

Insert immediately after the existing `⚠ SHAPE-VERIFIED 2026-07-29` paragraph:

```
⚠ SHAPE-VERIFIED 2026-07-30: the CLASSIC envelope, for two event types —
CARD_CLICKED (both trigger kinds: a button tap and a selection widget's
onChangeAction, the latter from a card with no button at all) and
ADDED_TO_SPACE. Real captures from the live project `chat-gateway-gw`, replayed
offline (tests/fixtures/classic-cardclicked-button-event.json,
classic-cardclicked-onchange-event.json, classic-added-to-space-event.json).

Scope, because "the classic path is verified" would be too broad:
classic MESSAGE is still CONSTRUCTED (classic-message-event.json), and nothing
here touches classic `thread.threadKey`, the `commonEventObject.formInputs`
arm of _normalize_classic, APP_COMMAND / slash commands, REMOVED_FROM_SPACE or
WIDGET_UPDATED. Per hard rule #3 this accompanies ⚠ LIVE-UNVERIFIED and clears
nothing on its own.
```

### Task 7.2 — `_action_params` docstring

Replace its last sentence. Current:

```
    list branch is still doc-derived and has never been seen from the add-ons
    runtime."""
```

becomes:

```
    list branch is still doc-derived FROM THE ADD-ONS RUNTIME, which has never
    sent it — but it is capture-confirmed on the CLASSIC side as of 2026-07-30
    (tests/fixtures/classic-cardclicked-button-event.json carries
    action.parameters == [{"key": "jobId", "value": "mig-001"}])."""
```

### Task 7.3 — the `CAPABILITY_FIELDS` comment

Replace `Google spells it ...Uri in the add-ons envelope and ...Url in the
classic one.` with:

```
# Google spells it ...Uri in the add-ons envelope and ...Url in the classic one.
# Both spellings are now first-hand: the add-ons one from the 2026-07-29
# message capture, the classic one from the 2026-07-30 ADDED_TO_SPACE capture,
# where it sits at the ROOT of the event rather than under a payload.
```

### Task 7.4 — `CLAUDE.md`'s verification ledger: ONE new bullet

Add immediately after the existing *"The add-on **MESSAGE** and
**buttonClicked** shapes are ⚠ SHAPE-VERIFIED 2026-07-29…"* bullet:

```markdown
  - The **classic** envelope is ⚠ SHAPE-VERIFIED 2026-07-30 for **CARD_CLICKED**
    (both trigger kinds — a button tap, and a selection widget's
    `onChangeAction` on a card with **no button at all**) and for
    **ADDED_TO_SPACE** (real captures from `chat-gateway-gw`, replayed offline:
    `tests/fixtures/classic-cardclicked-button-event.json`,
    `classic-cardclicked-onchange-event.json`,
    `classic-added-to-space-event.json`). Scoped deliberately: classic
    **MESSAGE** is still CONSTRUCTED, and classic `thread.threadKey`,
    APP_COMMAND, REMOVED_FROM_SPACE and WIDGET_UPDATED are untouched. Like every
    ⚠ SHAPE-VERIFIED entry this **clears nothing** — the events were replayed
    offline, and while two of them were also normalized live off the
    subscription, that was an ad-hoc diagnostic script, not the gateway's
    `dispatch` path.
```

> **Do not touch the ledger's unverified-surfaces table.** `CLAUDE.md` says
> *"Do not re-summarize this table anywhere. Link to it."* Nothing in this PR
> changes a row in it, and nothing in this PR may restate it. This task adds a
> sibling bullet recording a new SHAPE-VERIFIED fact; that is all.

---

## Task 8 — `docs/BUILDER_QUEUE.md`

Planner has already applied the queue reconciliation on this branch (CG-9
unblocked and rescoped, CG-22 corrected, CG-11 amended, CG-26 filed). Builder's
only queue edit is to move both rows to **Recently shipped** with the usual
write-up, update the last-updated banner, and correct the remaining-order line.

---

## 5. Flag discipline — what this PR does and does not license

This section exists because CG-22's row makes a claim that is **too broad**, and
because the live session that produced these captures is easy to over-read.

### 5.1 CG-22's claim, assessed

> *"This also converts the classic normalizer from doc-derived to
> ⚠ SHAPE-VERIFIED."*

**Directionally right, materially too broad.** ⚠ SHAPE-VERIFIED means real
captured bytes replayed offline, which is exactly what Tasks 2 and 4–6 do. But
"the classic normalizer" is one function covering many shapes, and only some now
have real bytes:

| Classic surface | After this PR |
|---|---|
| `detect_envelope`'s classic arm | ⚠ SHAPE-VERIFIED |
| `_normalize_classic`, `CARD_CLICKED` — button-triggered | ⚠ SHAPE-VERIFIED |
| `_normalize_classic`, `CARD_CLICKED` — `onChangeAction`-triggered | ⚠ SHAPE-VERIFIED (new coverage; no add-ons equivalent exists) |
| `_action_params`' **list** branch, classic side | ⚠ SHAPE-VERIFIED |
| `common.parameters` map merge + `common.formInputs` harvest | ⚠ SHAPE-VERIFIED |
| `_resolve_action_id`'s native order, classic side | ⚠ SHAPE-VERIFIED |
| `_normalize_classic` with **no message** (`ADDED_TO_SPACE`) | ⚠ SHAPE-VERIFIED |
| `CAPABILITY_FIELDS`' classic `…Url` spelling | ⚠ SHAPE-VERIFIED |
| classic **MESSAGE** | still **CONSTRUCTED** — no real bytes exist |
| classic `thread.threadKey` | never observed; all classic captures thread by `thread.name` |
| `_normalize_classic`'s `commonEventObject.formInputs` arm (SUBMIT_FORM / app home) | never observed |
| classic `__cg_action__` / `__action_method_name__` | never observed; constructed-only |
| classic APP_COMMAND, REMOVED_FROM_SPACE, WIDGET_UPDATED | never observed |

So: land the upgrade, scope it, and **do not** write "the classic normalizer is
verified" anywhere.

### 5.2 What the live run does and does not license

The user pulled these events off the live subscription through the real
`PubSubPuller` and fed them straight into the real `normalize_event` — but via
an **ad-hoc diagnostic script**, not the gateway's dispatch path.

**It licenses nothing beyond what the fixtures license, and that is not a
technicality worth glossing.** `normalize_event` is a pure function of its
input, so running it on bytes as they come off the wire and replaying the same
bytes offline are the same experiment. "Live" adds evidential weight for a
function that talks to a network; it adds none for one that does not.

**Not exercised, and therefore not licensed:**

- `dispatch()` — space→app routing, the per-app authorization block,
  `redact_capability_urls` on the audit-write path, inbox persistence.
- `CallbackForwarder` — no tenant callback was invoked, so **jobhunt R3/R4 stay
  unverified**, exactly as `CLAUDE.md` already says.
- `SubscriberLoop.poll_once()` / `_run` — never entered.
- Acknowledgement — the `onChangeAction` message was **deliberately not acked**.
  `PubSubPuller.acknowledge()` was separately and selectively cleared by CG-24;
  nothing here adds to or subtracts from that.

**Flags cleared by this PR: none.** `PubSubPuller.pull()` was already cleared by
CG-24 and this is a re-exercise, not a new clear. For the current residue, read
`CLAUDE.md`'s verification ledger — it is the single authoritative list and this
plan deliberately does not restate it.

---

## 6. The no-button finding — routed to CG-11, not absorbed here

**Recommendation: the doc correction belongs in CG-11. Flagging rather than
deciding.**

The finding refines the producer convention CG-13 shipped —
*"widgets for input, one button to submit"* — which is correct for add-ons and
**incomplete for classic**, where a widget is itself a trigger and a card with
an `onChangeAction` produces an event on change *and* another on submit.

Locations carrying the now-incomplete wording:

| Location | Owner |
|---|---|
| `CLAUDE.md` — *"modal dialogs are impossible over Pub/Sub transport — selection widgets are the supported path"* | **CG-11**, explicitly |
| `docs/consumers/jobhunt.md` R6 | **CG-11** (the queue names it) |
| the integration guide's producer convention (CG-13) | **CG-11** |
| CG-11's **own row text** — *"a widget is not an interaction trigger"*, *"the pattern is widgets for input, one button to submit"* | **CG-11** |
| `tests/test_adapters.py`'s *"one event per decision, not two"* comment | **this PR** — Task 5 rewrites that test to consume the new fixture and cannot leave a refuted sentence in it |

**Why not fold CG-11 in.** CG-11's row instructs adopting **ADR-0001 §7's
wording verbatim** — and §7 was written from add-ons evidence, so it is now
itself incomplete for classic. Correcting it properly means editing the ADR,
which runs straight into CG-20's scope (ADR §5 option D, §10, §12). That is a
three-document chain, and this PR is a fixture-landing PR. Folding it in trades a
clean, verifiable change for a documentation refactor.

**What this PR owes CG-11 instead:** the evidence, landed and named. §8.3's queue
edit hands CG-11 the fixture path, the finding, the exact list above, and — the
part Builder must not miss — **a warning that Part G can no longer be a verbatim
adoption of ADR §7.** That is a genuine invalidation of CG-11's existing plan
and it must be visible in the row, not discovered mid-PR.

**Cost of deferring, stated honestly:** between this PR and CG-11 the repo
contains a fixture that contradicts a sentence in `CLAUDE.md`. That is
uncomfortable but not dangerous — the sentence's practical advice ("use
selection widgets, not modals") stays correct on both runtimes; only its
*mechanism* claim is incomplete. If you would rather close that window
immediately, say so and CG-11 gets promoted ahead of the queue's current order
rather than folded into this PR.

---

## 7. Verification

Run in order. Nothing may be committed until the step above it is green.

1. `python -m pytest -q tests/test_fixtures_scrubbed.py` — after Task 1, with
   only the **four existing** fixtures present. Proves the guard change is not
   a regression before any new bytes exist. *(Planner-side: green.)*
2. Task 2.5's raw-capture probe — expected **6 / 9 / 9** violations. A guard
   never shown to fail on the dirty file proves nothing.
3. Task 2.4's re-derivation diff — identical key/type trees, **76 / 72 / 19**
   leaves, **18 / 18 / 8** changed leaf values, committed bytes equal to
   re-derived.
4. `python -m pytest -q` — full suite. **Expected 124** (113 + 3 new
   parametrized guard cases + 2 new guard regression tests + 6 new normalizer
   tests; Task 5 rewrites a test in place and adds none). Take the real number
   from the suite.
5. **Mutation-test the two new guard rules**, per this project's standing
   practice:
   - delete the `assert PLACEHOLDER.search(value)` line →
     `test_guard_rejects_an_unscrubbed_capability_url` must fail.
   - delete the `EMAIL.findall` loop →
     `test_guard_rejects_a_non_example_email_address` must fail.
   - Neither deletion may leave the suite green. Restore afterwards.
6. **No UAT.** Nothing user-facing changes and no Google endpoint is contacted.
   The offline suite is the gate — which is exactly what the auto-merge policy
   means by "for backend/library changes the test suite stands in for UAT".

**Merge gate: none.** This PR touches `tests/` plus docstrings, the fixtures
README and `CLAUDE.md`. It does not touch `iac/`, the deploy path, or runtime
secret-handling code. The guard is a **test**, not a runtime secret path — it
makes the repo's rule-#2 posture stricter, and gating a strictness increase
behind a pause would be backwards. Auto-merge on green gates applies.

---

## 8. Queue reconciliation (Planner has already applied these)

### 8.1 CG-9 — unblocked and rescoped

Moves out of `## Blocked` into the queue proper as `📋 queued`, retitled to name
the classic shape, with the DM caveat and the "add-ons variant is now
uncapturable" closure written into the row. The old add-ons recipe in the
CG-3…CG-12 plan is marked superseded by this plan.

### 8.2 CG-22 — corrected

The *"already redacted at capture time"* parenthetical is struck (§1.1), the
source list is replaced with the real landing decision (§3), and the
"converts the classic normalizer to ⚠ SHAPE-VERIFIED" sentence is scoped to
what §5.1 supports. The row is merged into CG-9's as a single combined item.

### 8.3 CG-11 — amended with this PR's evidence

Gains the no-button finding, the fixture path, the location list from §6, and
the explicit warning that Part G's *"adopt ADR-0001 §7 verbatim"* instruction no
longer holds because §7 is itself incomplete for classic.

### 8.4 CG-26 — new row, filed rather than folded in

Fixture-quality debt. **Deliberately not folded into this PR** — none of it is
the same change, and one of its findings is that a prior session's claim about
this debt does not reproduce.

---

## Self-review

- **Item coverage.** CG-22's four stated pins → Tasks 4, 5 (envelope_format,
  native `action.id`, the `onChangeAction` shape, the classic ARRAY). CG-9's
  three stated pins → Task 6 (`ADDED_TO_SPACE` derived, space + sender
  extracted, `_shape` with an empty message) — with §1.3 recording that its two
  *add-ons-specific* pins are now uncapturable rather than pretending they were
  covered. Guard-first → Task 1, gated by Task 1c.
- **No placeholders.** Every task carries literal JSON, literal Python, literal
  markdown or a literal command. Nothing says "similar to", "TBD" or "as
  needed".
- **Executed against the real artifacts before hand-off** (Planner-side, in a
  scratchpad — no repo source was written):
  - The three fixtures in Task 2 were produced by Task 2.4's script and are
    the exact bytes it emits; the diff assertions and the 76/72/19 and 18/18/8
    counts are its real output.
  - The extended guard from Task 1 was run over all **seven** fixtures plus its
    two new regression tests: **10 passed**.
  - Every assertion in Tasks 4, 5 and 6 was executed against those fixtures with
    the **current** `normalize_event`: **7 passed**. No assertion in this plan is
    drafted from memory.
  - The five-way capability-URL probe in §1.4 and the six/nine/nine raw-capture
    violation counts in Task 2.5 are real outputs of the current guard.
  - §3.1's redundancy diff was run, and running it **corrected this plan**: the
    first version compared raw json-paths and reported a difference at
    `$.common.formInputs.<name>` — which is only the producer's widget name
    (`decision` vs `reason`), not a shape difference. Left as written it would
    have sent Builder down the "land both captures" branch for no reason. The
    script now collapses that segment, and the expected output in §3.1 is its
    real output.
  - The three JSON blocks in Task 2 were parsed back out of **this file** and
    compared to the guard-validated bytes: equal. The transcription is checked,
    not trusted.
- **Type consistency.** `action.id`/`id_source` are `None` (never `""`) on the
  add-ons capture and `str` on both classic ones — asserted as a tuple in
  `test_classic_supplies_action_identity_natively_unlike_the_addon_capture` so a
  regression to `""` cannot pass. `dedupe_key` is `str` on the two captures that
  carry `_pubsub_message_id` and `None` on the one that does not; both are
  asserted rather than skipped.
- **Scope check.** Two things are deliberately *not* here and are named as
  such: the CG-11 doc corrections (§6) and the CG-26 fixture-quality work
  (§8.4). One thing is here as an explicit judgement call the user can drop
  without unpicking anything else: Task 1b (§2.2).
- **Ambiguity check.** The one place Builder must judge — whether E1's capture
  is redundant — is given a script, an expected result, and a decision rule for
  both outcomes (§3.1), so it is a verification, not a judgement.
