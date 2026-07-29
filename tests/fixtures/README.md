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

Synthetic user ids are deliberately **zero-padded** (`users/000…001`). A real
Google user id is a long digit string that never starts with `0`, so the
`PII` guard in `test_fixtures_scrubbed.py` can tell a fixture id from a real
one structurally, without a path allowlist.

`configCompleteRedirectUri` is a per-message capability URL: visiting it makes
the user's private message public in the space and re-delivers it. Its value is
always `<SCRUBBED>` here.

`test_fixtures_scrubbed.py` enforces all of the above recursively on every
file in this directory. It is not a checklist item — it is a test, because the
checklist version already failed once.
