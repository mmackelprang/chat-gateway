# Test fixtures — Chat event envelopes

Provenance matters here: some of these are real bytes off the wire, some are
constructed. Do not blur the two — the project's ⚠ LIVE-UNVERIFIED discipline
depends on knowing which is which.

| File | Provenance |
|---|---|
| `addon-message-event.json` | **REAL** — captured from `chat-gateway-sub` on 2026-07-29, the first genuine Chat event this project ever received. Structure is byte-faithful to the wire; leaf values are anonymized (see below). |
| `addon-buttonclicked-event.json` | **REAL** — captured 2026-07-29, the first genuine card *interaction*. A card posted by our own `ChatApiAdapter`, a dropdown changed, a button tapped. Pins what Google actually sends, including the empty `action.id` defect (queue item CG-10). |
| `classic-cardclicked-button-event.json` | **REAL** — captured 2026-07-30 from the live project `chat-gateway-gw`, in the real consumer space, after the classic migration. A card posted by our own `ChatApiAdapter`; a dropdown changed, then a button tapped. The classic counterpart of the add-ons capture above, and the contrast is the point: `action.id` resolves **natively** here (`approve`, `id_source: "google"`) where the add-ons capture resolves to `None`. |
| `classic-cardclicked-onchange-event.json` | **REAL** — captured 2026-07-30, and **the card had no button**. Changing a selection widget was itself the interaction: `onChangeAction.function` arrived as the action identity and the changed value was harvested into params. There is no add-ons equivalent — an `onChangeAction` dies under that runtime with `gsuiteaddons.googleapis.com/errors` code 13 — so this is new coverage, not parity coverage. Pulled off the live subscription through the real `PubSubPuller`, so its `_pubsub_message_id` is a real one. **Carrying that field is not by itself evidence of `PubSubPuller` provenance** — `addon-buttonclicked-event.json` carries one and was pulled with an ad-hoc client, and `classic-added-to-space-event.json` carries one too. |
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

## What the guard enforces, per rule and per directory

`test_fixtures_scrubbed.py` holds **two** scans (CG-26). They share a file on
purpose — one rule vocabulary, and the fact that the guard now reads its own
source is visible at the point where the leak was.

**On `tests/fixtures/**/*.json`** — every string leaf, carrying its JSON path,
one parametrized test per file:

| Rule | Rejects | Precision basis |
|---|---|---|
| `SUSPECT_KEY` | any value under a path matching `token\|secret\|password\|credential\|redirecturi\|redirecturl\|api_key` that is not a `<SCRUBBED>`-style placeholder | the whole JSON path is matched, not the leaf key, so `{"token": {"value": …}}` cannot hide under the innocent name `value` |
| `SUSPECT_VALUE` | an embedded `token=`/`secret:`/… pair, or a `BEGIN … PRIVATE KEY` header, **wherever it sits** | value-shaped, so a credential pasted into free text is caught without a field name |
| `PII` | the author's surname; `users/<id>` or `members/<id>` where the id does not start with `0`; any mention of `googleusercontent.com` | `(?!0)` — a real Google user id never starts with `0`, so zero-padded synthetic ids are structurally distinguishable and no path allowlist is needed |
| `TENANT_KEY` | a `.domainId` / `.customer` value not containing `example` | RFC 2606 marker; a real Workspace tenant id cannot contain `example` |
| `EMAIL` / `EXAMPLE_DOMAIN` | any address whose domain is not an RFC 2606 `example.*` one | `fullmatch`, not `search` — `…@example.com.realcorp.net` is a real domain wearing a reserved one as camouflage |

**On `docs/**/*.md`, `tests/**/*.py`, `tests/**/*.md` and every root-level
`*.md`** — every line, **including `test_fixtures_scrubbed.py`'s own source and
this file**:

| Rule | Rejects | Precision basis |
|---|---|---|
| `DOC_USER_ID` | a real `users/<id>` or `members/<id>` | identical `(?!0)` lookahead, so a document may quote the synthetic `users/000…001`, which the docs do constantly |
| `DOC_AVATAR` | a real `https://…googleusercontent.com/` URL | narrowed — see the asymmetry below |
| `DOC_PEM` | an armoured `-----BEGIN … PRIVATE KEY-----` header | the `-----` armour is required, so describing the rule is not violating it |
| `DOC_CUSTOMER` | `customers/C<alnum>` without an `example` marker | same RFC 2606 convention as `TENANT_KEY`; the `{3,}` floor lets a document write the elided `customers/C0…` |
| `DOC_TENANT_ASSIGN` | a `domainId`/`customer` key, a `:`/`=`/`,` separator, and a quoted value of 4+ identifier characters, without an `example` marker | the shape incident 2 was literally written in — a Python tuple of `(key, value)` pairs. A `(?<!\w)` left boundary keeps it from matching the key as the *suffix* of a longer identifier; every real target shape has a quote, punctuation, whitespace or line-start in front of the key, so the boundary costs no detection. No opacity test here, unlike `DOC_URL_CRED`: a tenant id has no entropy signature to test |
| `DOC_TENANT_TABLE` | the same two keys in a markdown **table row** — `\| key \| value \|` — where the value cell is backticked, without an `example` marker | the cell form `DOC_TENANT_ASSIGN` structurally cannot see, because the separator is `\|` and not `[:=,]`. Precision comes from requiring the value's backticks: this repo always backticks a literal in a table cell, so demanding them costs no detection, while a *prose* cell beside these two field names is common and would otherwise be captured as a tenant id |
| `DOC_URL_CRED` | a credential in a URL query or fragment, when the value is opaque | the narrowed replacement for a `SUSPECT_KEY`/`SUSPECT_VALUE` port — see below |
| `DOC_PRIVATE_IP` | an RFC1918 or CGNAT address literal — `10/8`, `172.16/12`, `192.168/16`, `100.64/10` | scoped to the **private** ranges and never "any dotted quad", which is the entire precision argument: `0.0.0.0`, `127.0.0.1`, netmasks and the RFC 5737 documentation nets (`192.0.2.x`, `198.51.100.x`, `203.0.113.x`) are all things this repo writes on purpose, and none is private. Four full octets with boundaries on both ends, so version strings and outline numbers cannot match. Placeholders are `<LAN-IP>` / `<tailnet-IP>` / `<LAN-subnet>` |

⚠ **`DOC_PRIVATE_IP` guards the working tree, not the published history.** It
was added by CG-78 after CG-55's planning prose put this homelab's real LAN
address into `docs/BUILDER_QUEUE.md` on a **public** repo. The scrub cleaned
those documents; it did **not** un-publish anything, because the literals are in
committed history and a `git log -S` finds them. Removing them for real needs a
history rewrite, which was considered and **rejected** by the user — it would
invalidate every merge record this project uses as its audit trail, to buy down
exposure of addresses that are not routable from the internet. The rule stops
the *next* one. Read it that way; the stronger reading is false.

Scope, stated because it is easy to assume otherwise, and because the previous
version of this paragraph is now false: the second scan's trees are
`docs/**/*.md`, `tests/**/*.py`, `tests/**/*.md` and root-level `*.md`
(**non**-recursive at the root, so it cannot wander into `.claude/worktrees/`),
**plus two individually-named deploy-config files** — `docker-compose.yml` and
`.env.example` (CG-78). Those two are named one at a time rather than by a tree
because the reason for each is specific: the compose file is where CG-55's own
decision table sends a LAN address (`"<LAN-IP>:8085:8085"`), so a guard skipping
it would be blind exactly where the next literal lands; and `.env.example` is
the file most likely in this repo to receive a pasted **real credential**, which
until CG-78 put it outside the credential rules too, not just the address one.
`src/` and `iac/` stay out — measured at zero findings for all eight rules
(21 files and 3 respectively), so that is a scope decision rather than a gap.
**This README is scanned** — it used to be exempt for the accidental reason that
it is a `.md` outside `docs/`, which also left `CLAUDE.md` and the root
`README.md` outside. The point worth stating: the document that explains the
guard is now covered by the guard, so an example written here carelessly fails
the suite rather than being published. The fixtures beside it stay covered by
the first scan.

### The deliberate asymmetry: same concern, two precisions

Inside a JSON fixture, **any** mention of `googleusercontent.com` is a leak. A
proxy avatar URL is by construction some real person's, and no fixture has a
reason to name that host at all, so the blunt rule costs nothing.

In prose the host is a legitimate **subject** — in rule tables, in quoted regex
sources, in scrub notes. The counts here are re-measured rather than inherited,
because the pair written down first were both wrong. **4** mentions sat in the
scanned trees on the day the prose rule was written, all four of them in
`docs/`. **14** sit there now: 4 in `docs/`, 6 in `test_fixtures_scrubbed.py`,
and 4 in this file — which the widened trees have just brought inside the guard
— because documenting a rule means naming what it hunts. The figures this
replaces, nine and seventeen, counted the bare
token `googleusercontent`, which sweeps up regex-source spellings a blunt rule
could never match, and so overstated the exact quantity the number exists to
size. A blunt port would still have flagged every one of them on the guard's
first run, and the fix a reader reaches for at that point is to delete the rule.
So `DOC_AVATAR` demands a real URL: scheme, host, path separator.

The same reasoning, weaker, applies to `DOC_PEM`'s `-----` armour, and it is
worth stating precisely rather than by analogy: every place this repo discusses
that header today writes it elided or bracketed (`BEGIN … PRIVATE KEY`,
`BEGIN [A-Z ]*PRIVATE KEY`), which even the blunt form would miss. The
armour is **prophylactic**, not load-bearing — it defends against the natural
unelided prose one keystroke away ("a key file begins with the line BEGIN RSA
PRIVATE KEY"). All three spellings are in the guard's tolerance sample.

## What review owns, because the guard cannot

Each of these is a **review obligation**, not an apology. The measured reason
comes with it, so nobody re-files it as a gap.

- **Display names.** `"Test User"` and a real name are indistinguishable to a
  regex, and a list of real names committed to a public repo would be a worse
  artifact than the problem. `PII` protects exactly one human — this author —
  and does it by literal surname, which is why
  `test_guard_rejects_the_author_identity_literal` uses a display name to prove
  that arm fires in isolation from the email rule.
- **A capability URL carrying its token in the URL *path*, under a key that does
  not match `redirecturi|redirecturl`.** Catching it needs a
  high-entropy-path-segment rule, which would fire on the space and message ids
  that `docs/google-cloud-setup.md` step 8 classifies as non-secret. Both real
  spellings Google uses put the token in a `token=` query parameter, and both
  are caught twice over. The **key** half of that sentence is not merely
  asserted: `test_guard_rejects_an_unscrubbed_capability_url`'s third case is a
  path-borne token under a matching key, and it is rejected. So the hole is
  specifically "path-borne token **and** innocent key", not "path-borne token".
- **Space / message / thread ids, everywhere.** The Anonymization section below
  has always said these are deliberately unguarded; it has never said whose job
  they are. **They are review's.** `docs/google-cloud-setup.md` step 8
  classifies space ids as non-secret, and a guard that contradicts our own
  published classification would lose that argument, correctly. Anonymizing them
  in fixtures stays a convention — followed, never enforced.
- **Email addresses, in the scanned trees.** The `EMAIL`/`EXAMPLE_DOMAIN`
  rule is **deliberately not ported** out of `tests/fixtures/`, and the
  measurements are the reason rather than a shrug:
  - It would have caught **neither** incident. Incident 1's leaked address is
    the author's own — which the guard is *required* to tolerate, since it is in
    the authorship metadata of every commit. Incident 2 had no email in it at
    all.
  - Of the **81** addresses in the scanned trees today, **40** occurrences
    across **8 distinct values** are not `example.*`. Two of those are spellings
    of the author's own address (16 occurrences) and two are Google
    service-account addresses (13) — four mandatory tolerances. Every one that
    remains is a deliberately-fake bait value out of a test:
    `someone@realcorp.io`, `alice.smith@partner.co.uk` and
    `someone@example.com.realcorp.net` from this guard's own negative cases (9,
    three of them the mentions in this very bullet), plus `a@b.test` from
    `tests/test_log_redaction.py` (2, one of them here) — whose reserved `.test`
    TLD is RFC 2606 as well, just not one `EXAMPLE_DOMAIN` recognises. **100%
    false positives, on values those tests need to keep working.**
  - These figures are re-measured, not carried forward. The ones printed here
    before — 71 / 32 / 7 distinct, with 13 for the author — reproduce at the
    point *before* `tests/test_log_redaction.py` merged into these trees, which
    is what brought the eighth distinct value in; the widening then moved them
    again. Method, so the next reader can reproduce rather than trust:
    `EMAIL.findall` over every scanned file, then `EXAMPLE_DOMAIN.fullmatch` on
    each result — the guard's own two regexes, no hand-filtering.
  - Any allowlist wide enough to pass those is wide enough to pass a real leak.
- **`SUSPECT_KEY` / `SUSPECT_VALUE`, ported only in the narrowed URL form.** The
  fixture rule keys off a JSON path, and prose has none. A naive port scores
  **62 hits across the scanned trees today** — every one a false positive,
  mostly documentation of the rule itself. Method, because the two figures
  printed here before (39, and 28 "before this item") were taken by different
  methods at different moments and neither reproduced afterwards: apply
  `SUSPECT_VALUE` to every line of every scanned file and count the matches.
  Expect it to climb — this bullet is one of the things it counts.
  `DOC_URL_CRED` replaces it with the shape that actually leaks: a credential in
  a URL query or fragment. The fragment half is not theoretical — an OAuth
  implicit-flow token arrives there, and `tests/test_log_redaction.py` redacts
  it there.

## The judgement the guard is making, and where it fails

`DOC_URL_CRED` is the only rule that has to decide whether a value is
**real-looking** or **obviously fake**, and it decides **by the value alone** —
no annotation, no path allowlist, nothing a scrub can forget to update. Two
independent clearances, either of which passes a value:

1. **An explicit fake-marker word** in the value: `example`, `test`, `fake`,
   `dummy`, `sample`, `placeholder`, `scrubbed`, `redacted`, `notreal`,
   `changeme`, `your`.
2. **Failing the machine-generated test**: fewer than 24 characters after `%XX`
   escapes are stripped, or drawn from fewer than 3 of lower / upper / digit.
   Escapes are stripped *first* because a URL-encoded value is padded by its own
   encoding (`%3D%3D` is six characters of two), and counting the padding toward
   the threshold would let a short secret hide behind its escaping.

**Why no annotation-based exemption.** An `# allow` marker would have to be
added to files this item does not own — `tests/test_log_redaction.py` is
CG-34's (PR #33, **merged** onto main during this cycle) and
`tests/test_adapters.py` is CG-23's — so the guard has to tolerate those values
*by design*, not by annotation. It does, and the merge upgraded the evidence
rather than retiring the argument: `test_log_redaction.py` is now **inside the
scanned trees**, so `test_docs_and_tests_carry_no_real_identity` re-proves the
tolerance on every run instead of a side check having proved it once. Given the
guard must work without annotations anyway, adding them anywhere would be a
second mechanism doing the first one's job, and an exemption marker is precisely
what a future scrub forgets to remove.

**Where it fails, stated plainly:**

- A real credential **shorter than 24 characters**, or drawn from a **single
  character class**, passes. That is the accepted cost of tolerating
  `?key=K&token=T` and `?key=SECRETKEYVALUE&…` — the literal values the two
  hard-rule-#2 test files are built on.
- A real value that happens to contain the substring `test` passes.
- Conversely, a genuinely fake value that is long, mixed-case and marker-free
  **will be flagged** — the false-positive direction. The fix is to add a marker
  word, which is exactly why the marker vocabulary is generous.
- One false-positive shape was found by measurement rather than predicted, and
  then **fixed**: `DOC_TENANT_ASSIGN` used to fire on a **Python identifier
  ending in a tenant key** followed by a separator and a quoted string, because
  the rule cannot tell a variable name from a JSON key. It fired twice on
  CG-26's own source — once on a variable, once on the comment explaining the
  variable — and firing twice on one change is the evidence that the rule was
  too wide rather than the names unlucky. The `(?<!\w)` left boundary now
  requires the key to *start* an identifier; measured across every scanned file,
  not one existing finding moved.
- The narrow blind spot that boundary leaves, stated rather than left to be
  rediscovered: a **compound** identifier assignment — `tenantDomainId = "…"` —
  is no longer matched at all. For the customer spelling that is mitigated by
  `DOC_CUSTOMER`, which needs no lookbehind of its own because its
  eleven-character literal prefix makes a suffix collision implausible. For a
  bare `domainId` value it is genuinely uncovered, and that is the price of the
  false-positive class above being gone.
- `DOC_TENANT_TABLE` misses an **unbackticked** value cell. That is the same
  trade in the other direction: requiring the backticks is what keeps the rule
  off a prose cell sitting beside those two field names, and this repo always
  backticks a literal in a table.

**The convention that keeps all of this working: negative-case bait is composed
at runtime, never inlined.** Every value the scan must reject is assembled from
fragments in `test_fixtures_scrubbed.py`, so the file's own source carries no
matchable literal while the tests still see whole, unmarked, real-shaped values.
Inline one instead and the file fails its own scan — which is the feature, and
`test_an_inlined_tenant_literal_would_be_flagged_in_this_very_file` proves it
rather than asserting it. The one exception is the author's surname, which
cannot be invented without proving the opposite of what is wanted.

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

Email addresses must use an RFC 2606 `example.*` domain, enforced structurally
by `EMAIL` / `EXAMPLE_DOMAIN` in `test_fixtures_scrubbed.py` — every string leaf
is checked, not just `user.email`, because an address can ride in message text.
The reserved domain must be the whole address's domain, not a suffix of it.

`domainId` and `customer` are Workspace tenant identifiers with no structure to
key off, so fixtures mark them instead: their values must contain `example`
(RFC 2606, which a real tenant id cannot contain). Enforced by `TENANT_KEY` in
`test_fixtures_scrubbed.py`.

Space / message / thread ids are anonymized by convention and deliberately have
**no** guard rule: `docs/google-cloud-setup.md` step 8 classifies space IDs as
non-secret, and a guard that contradicts our own published classification would
be worse than the convention. Unguarded means **owned by review** — see "What
review owns, because the guard cannot" above, where it is stated as an
obligation rather than left as an absence.

One value is kept real on purpose:
`action.function = "projects/chat-gateway-prod/topics/chat-gateway-events"` in
the buttonClicked fixture. Project ids are non-secret per the same step 8, and
that value **is** the finding — remove it and the fixture stops demonstrating
why `action.id` is empty.

`test_fixtures_scrubbed.py` enforces all of the above recursively on every file
in this directory — **and, since CG-26, scans `docs/**/*.md`, `tests/**/*.py`,
`tests/**/*.md` and root-level `*.md` as well, including its own source, this
README and `CLAUDE.md`.** The widening is not tidiness: neither of this
project's two PII incidents was in a fixture, so
everything the first scan enforces was, for both of them, aimed at the wrong
directory. None of it is a checklist item — it is a test, because the checklist
version already failed once.
