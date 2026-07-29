# Test fixtures — Chat event envelopes

Provenance matters here: some of these are real bytes off the wire, some are
constructed. Do not blur the two — the project's ⚠ LIVE-UNVERIFIED discipline
depends on knowing which is which.

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

Both were confirmed rather than assumed: running the extended guard against the
**raw** capture flags nine leaves, and the three `TENANT` hits among them —
`$.chat.user.domainId`, `$.chat.buttonClickedPayload.space.customer` and
`$.chat.buttonClickedPayload.message.space.customer` — are exactly the ones the
pre-CG-3 guard missed. The landed fixture was also diffed against the raw
capture structurally: **78 leaves on both sides, identical key/type tree, and
exactly 17 changed leaf values**, all of them identity, tenant or space names.

## Anonymization

This repository is **public**. Real captures keep their structure exactly —
every key, every nesting level — and change only leaf values: user ids,
avatar URLs, domain ids, space/message/thread ids, and email addresses.

Synthetic user ids are deliberately **zero-padded** (`users/000…001`). A real
Google user id is a long digit string that never starts with `0`, so the
`PII` guard in `test_fixtures_scrubbed.py` can tell a fixture id from a real
one structurally, without a path allowlist.

`configCompleteRedirectUri` is a per-message capability URL: visiting it makes
the user's private message public in the space and re-delivers it. Its value is
always `<SCRUBBED>` here.

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

`test_fixtures_scrubbed.py` enforces all of the above recursively on every
file in this directory. It is not a checklist item — it is a test, because the
checklist version already failed once.
