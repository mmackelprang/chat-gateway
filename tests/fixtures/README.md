# Test fixtures — Chat event envelopes

Provenance matters here: some of these are real bytes off the wire, some are
constructed. Do not blur the two — the project's ⚠ LIVE-UNVERIFIED discipline
depends on knowing which is which.

| File | Provenance |
|---|---|
| `addon-message-event.json` | **REAL** — captured from `chat-gateway-sub` on 2026-07-29, the first genuine Chat event this project ever received. Structure is byte-faithful to the wire; leaf values are anonymized (see below). |
| `addon-buttonclicked-event.json` | **REAL** — captured 2026-07-29, the first genuine card *interaction*. A card posted by our own `ChatApiAdapter`, a dropdown changed, a button tapped. Pins what Google actually sends, including the empty `action.id` defect (queue item CG-10). |
| `classic-cardclicked-button-event.json` | **REAL** — captured 2026-07-30 from the live project `chat-gateway-gw`, in the real consumer space, after the classic migration. A card posted by our own `ChatApiAdapter`; a dropdown changed, then a button tapped. The classic counterpart of the add-ons capture above, and the contrast is the point: `action.id` resolves **natively** here (`approve`, `id_source: "google"`) where the add-ons capture resolves to `None`. |
| `classic-cardclicked-onchange-event.json` | **REAL** — captured 2026-07-30, and **the card had no button**. Changing a selection widget was itself the interaction: `onChangeAction.function` arrived as the action identity and the changed value was harvested into params. There is no add-ons equivalent — an `onChangeAction` dies under that runtime with `gsuiteaddons.googleapis.com/errors` code 13 — so this is new coverage, not parity coverage. The only classic capture pulled through the real `PubSubPuller`, which is why it is the only one carrying `_pubsub_message_id`. |
| `classic-added-to-space-event.json` | **REAL** — captured 2026-07-30T00:24:51Z, the Chat app removed from a space and re-added. First real bytes for a non-MESSAGE, non-CARD_CLICKED event, and the first real capture ever to carry a live `configCompleteRedirectUrl` (scrubbed here per DEC-7). ⚠ It is a **DM** (`spaceType: DIRECT_MESSAGE`), not a ROOM — see below. |
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

## Anonymization

This repository is **public**. Real captures keep their structure exactly —
every key, every nesting level — and change only leaf values: user ids,
avatar URLs, domain ids, space/message/thread ids, and email addresses.

Synthetic user ids are deliberately **zero-padded** (`users/000…001`). A real
Google user id is a long digit string that never starts with `0`, so the
`PII` guard in `test_fixtures_scrubbed.py` can tell a fixture id from a real
one structurally, without a path allowlist.

`configCompleteRedirectUri` (add-ons) / `configCompleteRedirectUrl` (classic) is
a per-message capability URL: visiting it makes the user's private message
public in the space and re-delivers it. Its value is always `<SCRUBBED>` here.
The classic spelling sits at the **root** of the event, not nested under a
payload; that placement is first-hand as of the 2026-07-30 ADDED_TO_SPACE
capture, and `test_guard_rejects_an_unscrubbed_capability_url` proves the guard
rejects an unscrubbed one in either spelling.

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
