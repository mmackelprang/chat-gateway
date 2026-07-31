# Production-readiness arc — design spec

**Date:** 2026-07-31 · **Status:** proposed, awaiting user review
**Queue rows:** CG-53 … CG-59
**Plan:** [`../plans/2026-07-31-production-readiness-arc.md`](../plans/2026-07-31-production-readiness-arc.md)

---

## 0. The premise

**It has never been deployed.** `Dockerfile` and `docker-compose.yml` exist and
are carefully commented, and neither has ever been exercised. Every verification
across 2026-07-29/30 was hand-run from the Windows dev box. `/srv/chat-gateway/`
appears throughout the repo as an *aspirational* target — no such directory
exists on any host. `docs/` holds five files and none of them is a deploy doc or
a runbook.

`main` is at `670a5d8`, clean, **202 tests passing**, and the builder queue is
empty — 31 items shipped over two days. The gateway is well-tested software that
has never run for more than the length of a hand-run session.

This spec plans the arc that changes that, across four workstreams the user
named: **deploy to the NAS**, **queue durability**, **error-path hardening**, and
**long-run observation**.

**On the verification ledger.** `CLAUDE.md` holds the single authoritative list
of what is and is not exercised against Google. It is **linked, never restated**
here — that file records that every restatement of it in this repo has drifted
within two PRs, and this spec is not going to be the sixth.

---

## 1. Three findings that contradict the brief

These are recorded first, and prominently, because a plan built on the brief's
version of them would have been wrong in ways that only surface on the box.

### 1.1 There is no `nas/compose/<service>.yaml` convention — and our compose file cannot deploy as written

The brief specified *"Compose files: `nas/compose/<service>.yaml`"*. That
directory contains **no YAML at all**. It holds minified JSON captured from the
TrueNAS middleware API (`midclt call app.config <name>`), written by
`nas/scripts/capture.sh`, with secrets redacted.

The real mechanism is: a service is deployed as a **TrueNAS custom app** via
`midclt call app.create` with an inline `custom_compose_config`, and *then*
`capture.sh` writes `nas/compose/<name>.config.json`. The repo documents
reality; it does not declare intent. You do not author a compose file — you
deploy, then capture.

Three consequences for `docker-compose.yml` as it stands today:

| Line | Why it does not survive the transition |
|---|---|
| `build: .` | A custom app is rendered from a JSON compose document sent over the API. There is no build context on the NAS. Every captured config in the homelab repo uses `image:`. |
| `env_file: .env` | `env_file` is used by **no** service in the homelab repo; every one inlines `environment:`. Whether the TrueNAS renderer honours `env_file` at all is unverified. |
| `./config:/config:ro` | Relative host paths have no meaning in an API-submitted compose document. Every homelab bind mount is an absolute path under `/mnt/datapool/apps/<app>/`. |

The repo's `docker-compose.yml` is not deleted — it stays as the **local /
dev-box** path, which is genuinely useful and is what `build:` is for. The NAS
gets a separate, captured artifact. This is stated because "we already have a
compose file" is the obvious wrong conclusion.

### 1.2 The homelab secret redactor will NOT redact this gateway's secrets — this is a live cross-repo leak hazard

This is the most important finding in this document.

`lib/redact_json.py` in the homelab repo decides a key is secret by
**upper-cased suffix match** — `…PASSWORD`, `…TOKEN`, `…SECRET`, `…API_KEY`,
`…APIKEY`, `…CREDENTIALS`, `…DATABASE_URL`, and a handful more. It then writes
`<REDACTED-see-SECRETS.md>` in place of the value, and `capture.sh` ends by
printing `clean. safe to commit.`

Now match that against this gateway's secret env-var names, whose shapes are
fixed by `.env.example` and by each registry entry's `key_env` / `webhook_url_env`:

| Env var shape | Ends with | Redacted? |
|---|---|---|
| `CHAT_GATEWAY_API_KEY__<APP>` | the app id | ❌ **NO** |
| `GOOGLE_CHAT_WEBHOOK_URL__<IDENTITY>` | the identity name | ❌ **NO** |
| `GOOGLE_APPLICATION_CREDENTIALS` | `CREDENTIALS` | ✅ yes (and it is only a path) |

The suffix rule is defeated by the `__<SUFFIX>` naming convention this project
uses to get one env var per app and per identity. The two var families that are
**actually** credentials — a per-app API key, and a webhook URL that embeds
`key`+`token` and *is* a bearer credential with no rotate-in-place — are exactly
the two the redactor misses.

So the naive path (inline `environment:` in the custom app, house style, then
`capture.sh`) ends with **every per-app API key and every webhook URL committed
in plaintext to the homelab repo**, under a script that printed
`clean. safe to commit.`

That is the CG-23 / CG-34 defect class, one repo over, and worse: recovery from
a leaked webhook URL is delete-and-recreate by hand in the Chat UI
(`docs/google-cloud-setup.md` §8a), and this project has already burned every
webhook it owns once, on 2026-07-29, for a smaller mistake.

**The design answer is that secrets never enter `custom_compose_config` at
all** — see §4.1. Not "name the vars better", not "remember to check the
capture": by construction, so that the redactor's suffix list is irrelevant to
us and a future operator cannot get it wrong by following house style.

A **cross-repo note** (not a change we make — that repo is read-only to us) is
recorded in the runbook: homelab's suffix list would not catch these shapes, and
if that repo ever wants defence in depth, a `*_API_KEY__*` / `*_WEBHOOK_URL__*`
substring rule is the shape that would.

### 1.3 `SECRETS.md` is gitignored and holds real values; the tracked pointer file is `SECRETS.template.md`

The brief said *"Secrets: pointers only in `SECRETS.md` at the homelab root"*.
Half right, and the half that is wrong is the half you would commit to.
`SECRETS.md` is gitignored (`.gitignore` line 2) and contains real credentials.
`SECRETS.template.md` is the tracked map — three columns, no values. Service
docs carry pointers **into** `SECRETS.md`.

So the homelab-side change is: a row in the tracked `SECRETS.template.md`, and
the value filled into the operator's untracked local `SECRETS.md`.

---

## 2. Two more findings that reshape the workstreams

### 2.1 jobhunt's push receiver was never built — decision A costs nothing to unwind

Decision A switches `job-hunter` from `callback_url` push to passive inbox
polling. Surveying jobhunt (read-only) shows there is **no receiver to remove**:
no `/chat-callback` route exists, `pipeline/review_ui.py`'s route table is ten
entries and none of them is it, and a repo-wide search for any gateway or
callback symbol in `*.py` returns nothing. The port is unimplemented on both
sides of the mismatch.

This is favourable timing, and it makes the change a **contract correction
before first use** rather than a migration. Nothing is deleted on either side;
`CallbackForwarder` and its R7 path stay, per the user's instruction and per
hard rule #6, which names both inbound paths.

**The `8710` vs `8763` port mismatch (CG-42's finding) becomes moot**, exactly as
the user predicted — there is no receiver to point at. jobhunt's own open
question on that port can be closed as moot by jobhunt, in jobhunt's repo.

### 2.2 The premise of decision A is itself under review in jobhunt — and the decision survives anyway

Decision A's stated justification is that jobhunt's receiver would live with its
database on `marksdevbox`, **which sleeps**. That is true of jobhunt's *accepted*
topology ADR (OD8, 2026-07-29), which puts the database and review UI on the
sleeping dev box and says so bluntly in six places.

But jobhunt has a **newer, proposed** topology ADR — OD9, dated 2026-07-30,
status *proposed, awaiting user sign-off* — whose recommendation is to collapse
the database, the review UI and the `/chat-callback` receiver **onto
`appserver`, which is always on**. If OD9 is accepted, the sleeping-host premise
evaporates and push becomes viable again.

This is flagged rather than glossed because this repo's culture is that
"obsolete" is never a bare status word (CG-14 is the precedent: the premise a
migration removed is written down, not just the status). A spec whose stated
reason is falsified a week later, with nothing recorded, is how CG-21 happened.

**The decision stands, and it should — but on its stronger reason.** Polling
wins under *both* topologies:

| | push | polling |
|---|---|---|
| Consumer host sleeps (OD8) | R7 fires on most taps; a warning seen constantly stops being read | events wait in the inbox |
| Consumer always-on (OD9) | works — but the gateway must know the consumer's address, port and liveness | gateway needs to know nothing about consumer topology |
| Port agreement | required, and a mismatch is indistinguishable from no receiver | not required |
| Gateway coupling | the gateway holds a URL into another project's process layout | the gateway holds nothing |

The durable argument is the last row: **push couples the gateway to a consumer's
deployment topology; polling does not.** That reason survives OD9 either way,
where "marksdevbox sleeps" might not. The spec records both, and says which one
is load-bearing.

### 2.3 Decision A makes queue durability load-bearing, and the brief's scope for it was too narrow

The brief scopes durability to `delivery.py:10` — *"a gateway restart drops
undelivered jobs"*. But `inbox.py` has the **same defect and a worse blast
radius under decision A**:

```
src/chat_gateway/inbox.py:22   self._pending: dict[str, deque[InboundReply]] = defaultdict(deque)
```

The inbox is in-memory too. Under push, an inbound tap left the gateway within
~10s. Under **polling by a consumer whose host sleeps**, a tap can sit in that
deque for hours — and a restart in that window drops it. The JSONL audit file
keeps a copy, but nothing reads it back; recovery is an operator reading
newline-delimited JSON by hand.

So: **decision A points jobhunt's only inbound path at an in-memory queue.**
Durability must cover `Inbox` as well as `Dispatcher`, and durability must land
*before* the contract change is documented as safe. This is a scope correction to
the brief, not a preference.

There is a second, independent inbox defect in the same area — `poll()` **clears
on read**, i.e. at-most-once — which is a contract question rather than a
durability one. It is §5.

---

## 3. Recommended sequence, and why

The brief listed four workstreams and said *"sequence them, do not assume my
order is right"*. The brief's order was: deploy → durability → error paths →
long-run.

**Recommended order:**

| # | Row | Why here |
|---|---|---|
| 1 | **CG-53** deployment artifacts + secret-safety proof (**no deploy**) | Largest unknowns, and it carries the §1.2 leak finding. That finding must not wait behind two code PRs. Produces the image strategy, the on-box layout, the `CHAT_GATEWAY_ENV_FILE` loader, and the runbook — all offline-verifiable. |
| 2 | **CG-54** queue + inbox durability | The **only hard prerequisite** for an always-on deploy. `restart: unless-stopped` means the thing restarts by itself; every restart silently empties both queues. A trusted always-on service that loses work on restart is worse than a hand-run one that does, because nobody is watching. Offline-testable. |
| 3 | **CG-55** first NAS deploy + live smoke (**user-executed**) | Everything after this benefits from being observed on a running instance, and **the soak clock starts here** — so CG-59 harvests days of real uptime instead of beginning a wait. |
| 4 | **CG-56** inbox delivery semantics (at-most-once → ack) — ⏸ **needs user sign-off** | Before the contract doc is rewritten, so it is written once. |
| 5 | **CG-57** jobhunt `callback_url` → passive polling | Documents the *final* semantics, whichever way CG-56 resolves. |
| 6 | **CG-58** structured adapter failures + `Retry-After` | Improves a running system; needs no deploy to test (fakes can return 429 + `Retry-After`), and benefits from real traffic having been seen. |
| 7 | **CG-59** long-run observation + what a **deployed** `/healthz` needs | Strictly after a deploy. Harvests the soak from step 3. |

**Where this departs from the brief's order, and why.**

*The deploy moves from first to third.* The brief's reasoning was right — *"3 and
4 cannot be observed at all until something runs continuously"* — and it still
holds for workstream 4. But workstream 3 is offline-testable (we cannot make
Google return 429 on demand either way; a fake transport is the *only* way to
exercise it), and durability is a genuine prerequisite rather than a
nice-to-have. Two PRs is a small delay against deploying a service that
silently drops an approval tap on every restart.

*Durability moves from second to second — but widens.* Per §2.3 it covers the
inbox too.

*The jobhunt contract change is new to the sequence* (it was a user decision, not
a numbered workstream) and lands after the semantics it must describe are
settled.

**Nothing in this arc widens any tenant's inbound surface.** `aitrader` stays
`allow_inbound: false`. Decision A *narrows* jobhunt's. Hard rule #6 holds
throughout, and CG-57 is the row that touches it — narrowing only.

---

## 4. Workstream specs

### 4.1 CG-53 — deployment artifacts and the secret-safety proof

**Ships no deploy.** It ships the artifacts, the layout, the one small code
change that makes rule #2 hold on the NAS, and a runbook.

#### The role change, stated

The NAS is **"backup target only"** today. This is a role change, not just a
deploy: it becomes the first always-on *application* host in that repo's NAS
tree that other projects depend on. Blast radius on existing NAS services is a
real consideration and is addressed as: a distinct non-colliding port, no
`network_mode: host`, no new capabilities, bind mounts confined to one app
directory, and no change to any existing app's config. Port `8085` is free —
the in-use set on that box is `3000, 5800, 8081, 8090, 8098, 30013, 31067,
32015, 32016, 37877`, with `80`/`443` owned by the TrueNAS UI and `53` by its
dnsmasq.

#### Image strategy

TrueNAS custom apps take an `image:`, not a `build:`. Two options:

1. **Build on the box** — `docker build` over SSH, tag locally, reference the
   tag with `pull_policy: missing` so it is never pulled. No registry, no
   registry auth, nothing published. **Recommended for v0**: it matches the
   "no public ingress, nothing published" posture, and it keeps the whole
   deployment inside the two hosts that already trust each other.
2. **Publish to a registry** (GHCR) and pull. Cleaner reproducibility, but adds
   a registry, an auth path, and a published artifact for a service whose entire
   design is *not* to be publicly reachable.

Option 1, with option 2 named in the runbook as the upgrade path if rebuilding
on the box ever becomes the annoyance.

⚠ **Verify on the box, do not assume:** that the middleware accepts a compose
referencing a locally-present image with `pull_policy: missing`. This is a
first-of-its-kind deployment in that repo (every existing custom app pulls a
public image) and it is the single most likely thing to fail. If it is rejected,
fall back to option 2 — recorded in the runbook as a decision point, not
discovered live.

#### Secrets: `CHAT_GATEWAY_ENV_FILE`, and why the fix is in *our* code

Per §1.2, secrets must never enter `custom_compose_config`. The obvious lever is
compose's `env_file:` — but no homelab service uses it and whether the TrueNAS
renderer honours it is unverified. Depending on an unverified property of
someone else's renderer for a **hard rule #2** guarantee is the wrong place to
put the load.

So the guarantee moves into code we own and test offline: `__main__` gains
support for `CHAT_GATEWAY_ENV_FILE`. If set, the named file is read at startup
and each `KEY=VALUE` line that is **not already present in the environment** is
loaded into it.

Four properties, each deliberate:

- **Environment wins over file.** An operator's `docker exec -e` or a compose
  `environment:` override must not be silently replaced by the file. Also makes
  the loader a no-op in every existing test and on the dev box.
- **No new dependency.** ~20 lines: strip comments, split on the first `=`,
  strip one layer of matching quotes. `python-dotenv` is not worth a dependency
  for this, and the durability workstream is making the same call about
  persistence (§4.2).
- **Missing file is fatal, not ignored.** If `CHAT_GATEWAY_ENV_FILE` names a
  file that does not exist, the process exits with a message naming the path. A
  gateway that boots with no credentials and reports `degraded` on an
  unauthenticated endpoint is a worse outcome than one that refuses to start —
  and it is the exact shape of the `/healthz`-that-lies failure rule #5 exists
  for.
- **Values are never logged.** The loader reports the count of keys loaded and
  the path, never a key's value. Key *names* are non-secret (they are in the
  committed `.env.example`); values are the whole point.

Result: `custom_compose_config` carries **`CHAT_GATEWAY_ENV_FILE` and a handful
of non-secret paths, and nothing else.** `capture.sh` is then clean *by
construction* — the redactor's suffix list stops being load-bearing for us.

#### On-box layout

```
/mnt/datapool/apps/chat-gateway/
├── .env                  0600  — every secret; never in git, never in compose
├── config/registry.yaml  0640  — env-var NAMES only (rule #2), still not in git
├── secrets/<sa-key>.json 0600  — mounted read-only
├── state/                0750  — heartbeats.json, deliveries/, queue/  (rw)
└── inbox-data/           0750  — inbound JSONL audit                   (rw)
```

The SA key filename is **not written into the compose file or this spec**.
CG-51 changed the setup scripts to *derive* `KEY_FILE` from `PROJECT_ID` and
added a refuse-and-exit-3 guard against minting a second key; a filename pinned
in a compose comment is exactly what CG-19 found stale and CG-51 removed. The
compose mounts the `secrets/` **directory** read-only and `.env` names the file
via `GOOGLE_APPLICATION_CREDENTIALS`. The live filename is recorded in
`docs/google-cloud-setup.md`; the compose comment points there rather than
repeating it.

`iac/chat-gateway-sa.json` is **dead** — it belongs to the deleted
`chat-gateway-prod` project. The runbook says so at the step where an operator
would otherwise reach for it.

#### Getting `.env` and `registry.yaml` onto the box

Both are gitignored dev-box files. Neither may enter the repo, and neither may
enter the compose document. They are `scp`'d from the dev box over the existing
homelab SSH path (user and key are defined in `nas/scripts/lib/common.sh`; this
spec names that file rather than reproducing the values), then `chmod`'d.

The runbook states the ordering constraint that makes this safe: **create the
directory tree with restrictive modes first, then copy** — never copy into a
world-readable directory and tighten afterwards.

#### Tailnet exposure — what per-app keys do and do not protect

The gateway needs **no public ingress**: Pub/Sub is an outbound pull. Tailnet
reachability exists only so consumer apps can call `/v1/*`. `docker-compose.yml`'s
own header already says never to publish it through a reverse proxy, and that
stands.

What the per-app API keys (hard rule #4) protect: every `/v1/*` endpoint. An
app may only send as identities the registry grants it; there are no shared keys
and no identity wildcards.

**What they do not protect:**

- **`/healthz` is unauthenticated by design** — the code says so, and CG-12's
  decision that its counters stay bare integers rests on it. Anyone who can
  reach the port can enumerate **app ids, identity names, per-identity mode,
  whether each env var resolves, and every counter**. No secrets, no space ids,
  no message content — but it is a real inventory of who this gateway serves.
- **The tailnet ACL is drafted but NOT applied.** The homelab repo records
  (2026-07-28) that the live policy is still default allow-all. So today, any
  tailnet peer — including accounts in the teammates group that exists for an
  unrelated service — can reach any port on the NAS that binds `0.0.0.0`.

Neither is a blocker and neither is a reason to skip the deploy. Both are
recorded in the runbook's Gotchas so the exposure is a decision rather than a
discovery. The mitigation available today at zero cost is to bind the published
port and let the ACL work land in the homelab repo on its own schedule; if the
user wants `/healthz` restricted, that is a separate item and is listed in §7 as
an open question rather than decided here.

#### Deliverables

- `CHAT_GATEWAY_ENV_FILE` support in `__main__`, with tests.
- `docs/deploy/nas.md` — the runbook. Owned by this repo, in the shape of the
  existing `docs/consumers/*-handoff.md` files: this repo owns the operational
  detail, and homelab's four-header `nas/services/chat-gateway.md` links to it.
  That split matches both repos' conventions and gives the fact one home.
- `.env.example` gains `CHAT_GATEWAY_ENV_FILE` with the "environment wins"
  semantics stated.
- `docker-compose.yml`'s header gains one clause scoping it as the **dev-box /
  local** path, so a reader does not take it for the NAS artifact. Its dated SA
  key comment is resolved to point at `docs/google-cloud-setup.md`.

**Merge gate: yes** — secret-handling path, and IaC-adjacent. Same gate CG-23,
CG-33, CG-34 and CG-51 carried.

### 4.2 CG-54 — queue and inbox durability

**Decision B, as given:** append-only JSONL under `CHAT_GATEWAY_STATE_DIR`,
matching the existing delivery log. One persistence idiom, no new dependency,
operator-readable during an incident.

`heartbeat.py` already JSON-persists (write `.tmp`, `os.replace` — atomic) and
`delivery.py` / `inbox.py` already write JSONL audit lines. This is the **third**
use of those two primitives and deliberately not a third idiom.

#### A new module, `src/chat_gateway/journal.py`

One class, used twice. Both queues get the same replay semantics, and there is
one place to reason about a torn write.

**Why not reuse the existing audit JSONL as the journal.** The audit files are
per-app-per-day, never pruned, and carry **no terminal records** — they say what
arrived, never what left. Reconstructing pending state from them would require
knowing what had already been polled or delivered, which they do not record.
Different question, different file. The journal is queue *state*; the audit is
the permanent record. Both stay.

#### Record shape

Three ops, versioned:

| op | carries | when |
|---|---|---|
| `open` | `id`, `kind`, full payload, `ts` | on enqueue / on inbound put |
| `update` | `id`, `attempts`, `next_attempt_at`, `ts` | on each retry reschedule |
| `close` | `id`, `status`, `ts` | on terminal (delivered / failed / polled / acked) |

Append-only is preserved: a retry does not rewrite the `open`, it appends an
`update`. Replay folds in file order and the **last** `update` for an id wins.

#### The replay-on-boot rule — settled

- **Replayed:** every id with an `open` and no `close`, **with its attempt count
  preserved**. Preserving `attempts` is not a detail: without it, a crash-loop
  resets the backoff ladder on every restart and hammers Google forever. That
  turns a persistence feature into an outage amplifier.
- **Discarded:** every id with a `close`, whatever its status.
- **A job mid-flight at kill time** — an `open` with no `close` whose HTTP request
  may or may not have reached Google — is **replayed, and may therefore deliver
  twice.** Stated plainly rather than hidden: Chat has no idempotency key, so
  the alternative is a two-phase commit we are not building, and losing the job
  is the worse failure for an alert. Notification dedupe already collapses
  repeats within its window, and the re-attempt is visible in the delivery log.
- **A job older than `REPLAY_MAX_AGE_S` (default 24h) is closed as `expired` at
  boot**, with a log entry — not silently dropped, and not blindly sent. An
  alert enqueued three days ago and posted now is actively misleading; silence
  about it is the thing rule #5 exists to prevent. Both failure modes are bad;
  this picks the one that is visible.
- **A torn trailing line — a partial write at power loss — is skipped, not
  fatal.** So is any unparseable line anywhere in the file. The count is kept and
  surfaced at `/healthz` as a journal-skipped counter. **A gateway that refuses
  to boot because of a half-written byte is a worse outcome than one that loses a
  record and says so**, and "refuse to start" on an always-on host with
  `restart: unless-stopped` is a crash loop.

#### Compaction — settled

- **On boot, after replay**: rewrite the journal as one `open` per surviving job,
  payload merged with its last `update`. Atomic, via the heartbeat idiom (`.tmp`
  + `os.replace`). Boot is the only time the file is read, so this is sufficient
  for correctness on its own.
- **During a long run**: compact when appended lines since the last compaction
  exceed a threshold (default 1000). This exists because the deployed process is
  meant to run for weeks — the workstream-4 case — and boot-only compaction on a
  process that never boots is no compaction at all.
- Compaction never blocks a send: it holds the same lock as the queue mutation
  and writes a bounded file.

#### Scope

Both `Dispatcher` (outbound) and `Inbox` (inbound) gain a journal, wired from
`__main__` under `CHAT_GATEWAY_STATE_DIR/queue/`. Both take the journal as an
**optional constructor argument defaulting to `None`**, so every existing
offline test constructs an unchanged in-memory object and the 202-test suite
does not need rewriting to accommodate persistence.

`/healthz` gains the skipped-line counter and a replayed-at-boot count — honest
reporting of a mechanism whose whole purpose is to survive something nobody
watched (rule #5).

**Merge gate: no.** No secret handling, no IaC, no Google-facing code.

### 4.3 CG-55 — first NAS deploy and live smoke

**User-executed**, in the pattern of CG-15 / CG-16 (the E1/E2 experiments the
user ran while Builder prepared them). Builder prepares exact commands and the
observation checklist; the user runs them against real hardware. Builder does
not deploy to production hardware unattended, and this queue has no precedent
for it.

Deploy-then-document is the homelab convention — *"the repo documents reality;
it does not declare intent"* — so the homelab-side artifacts (`nas/services/`
doc, `SECRETS.template.md` row, Homepage tile, `DASHBOARDS.md` row,
`restore-chat-gateway.sh`, and the captured config) are produced **after** the
box is running, from observed facts. Those land in the **homelab** repo, not
this one. This row's chat-gateway-side deliverable is the runbook being marked
as *executed, with the date and what actually happened* — including anything
that differed from plan.

**The gate that decides success is `capture.sh` printing `clean. safe to commit.`
with the captured JSON containing zero secret values** — verified by reading it,
not by trusting the script, precisely because §1.2 shows the script cannot see
this project's secret shapes.

Smoke checklist (each is a fact to observe, not a box to tick):

1. Container up; `/healthz` reachable on the LAN address; `status` and `reasons`
   read and recorded verbatim.
2. Tier 1 — one webhook send through the deployed instance to a real space.
3. Tier 2 — `GATEWAY_ENABLE_PUBSUB=1`, subscriber thread alive,
   `seconds_since_last_poll` moving. **This is the first time the pull loop runs
   from a host that is not the dev box**, so it is also the first evidence that
   the NAS's egress reaches Pub/Sub.
4. Restart the app; confirm the journal replays and the counters say so. This is
   CG-54's proof on real hardware, and it is the point of doing it here.
5. `capture.sh`, then **read the captured JSON**.

**Merge gate: yes** — deploy + secret-handling path.

### 4.4 CG-56 — inbox delivery semantics ⏸ needs user sign-off

`Inbox.poll()` **clears on read**:

```
src/chat_gateway/inbox.py:37-42   items = list(q); q.clear(); return items
```

At-most-once to the app, documented as such in the module docstring and pinned
by `tests/test_service.py:99` (`# poll clears`). If the HTTP response carrying a
batch is lost in flight, those events are gone from the queue — recoverable only
by an operator reading the audit JSONL by hand.

That was a defensible v0 when the inbox was a secondary path and push was the
primary one. **Decision A makes it jobhunt's only inbound path**, and a tap that
silently vanishes is precisely the failure jobhunt's own doctrine (its finding
J14) and this gateway's R7 exist to prevent.

**Recommended: `GET /v1/inbox` stops clearing; `POST /v1/inbox/ack` removes by
id.** At-least-once, which is what R3 already assumes — it demanded a
`dedupe_key` and committed jobhunt to idempotent handling, precisely because
Pub/Sub is at-least-once. The gateway already speaks this idiom in
`PubSubPuller.pull()` / `.acknowledge()`; this is the same shape one layer out,
not a new concept.

**It is flagged for sign-off rather than decided, because it changes a published
contract**, and the blast radius is real and enumerable: `client.py:64`'s
`poll_inbox`, `README.md`'s endpoint table, `docs/integration-guide.md` §
*Inbound replies*, `docs/consumers/aitrader.md`'s comparison row (which cites
`service.py` line numbers), and the pinning test above.

Compatibility shape, if approved: keep clear-on-read as the default so no
existing caller breaks, and make ack-mode explicit and opt-in per request. The
alternative — flip the default — is cleaner but silently changes behaviour for
any caller that does not ack, turning a working consumer into an infinitely
growing queue. Given the gateway is about to become always-on, growing-forever is
the worse default.

If the user declines: CG-57 documents at-most-once **explicitly, with this risk
stated in the jobhunt contract**, so jobhunt builds its poller knowing it. Either
answer is workable; what is not workable is jobhunt building a poller against an
unstated guarantee.

**Merge gate: no**, but **dispatch is blocked on the user's answer.**

### 4.5 CG-57 — jobhunt: `callback_url` → passive inbox polling

Registry and documentation only. No code path is deleted.

#### `job-hunter`'s registry entry loses `callback_url`

The live `config/registry.yaml` is a gitignored dev-box file; the committed
`config/registry.example.yaml` and the snippets in the two jobhunt docs are what
this row edits. The runbook's on-box registry must match.

#### What `allowed_users` and `unreachable_message` still mean — decided, not glossed

**`allowed_users` (R4) keeps its full meaning and its full force.** It is
evaluated at *ingress*, in the subscriber's authorization block, before anything
is queued — not at forwarding time. The `/healthz` counter documents this
precisely: `suppressed_not_authorized` counts *candidate apps that declined an
event*. Under polling, an unauthorized tap is still refused in-thread and still
**never enqueued**, so it never appears in the inbox for jobhunt to poll. The
only wording that changes is R4's *"never forwarded"* → *"never enqueued"*. The
guarantee is identical; the verb was push-shaped.

**`unreachable_message` (R7) becomes inert for `job-hunter`, and should be
removed from its entry rather than left as decoration.** R7's in-thread notice
fires from `CallbackForwarder._fail_loudly`, on callback exhaustion. With no
`callback_url` there is no forwarder job, no exhaustion, and no notice — the
field would be configuration that reads as active and can never fire. This repo
has corrected that exact shape three times (CG-37, CG-50, CG-52: a comment or a
value that states a defunct state as current).

**But the field is not removed from the schema, and R7 is not removed from the
contract** — both remain live for any future always-on tenant using the push
path, which hard rule #6 explicitly preserves.

**What replaces R7's guarantee under polling, stated honestly:** *nothing at the
gateway, and that is correct.* Under push the gateway could observe that the
consumer was unreachable, because it was the party making the call. Under polling
the gateway cannot distinguish "jobhunt is asleep" from "jobhunt has crashed" —
both look like nobody polling — and inventing a detector would mean the gateway
holding an expectation about a consumer's schedule, which is consumer semantics
and squarely against hard rule #1.

The gap moves to jobhunt, and this must be written into the handoff rather than
left implicit: **jobhunt needs its own staleness detection on its poller**, which
its `pipeline/health.py` watchdog is the natural home for, and which its own J14
doctrine already demands. On the gateway side the observable is
`/healthz` → `inbox.pending`, which rises when nobody is draining; that is
material for an operator, not a guarantee to a tenant.

#### Documents to revise

`docs/consumers/jobhunt.md` (R3/R4/R7 rows, the tenant-config snippet, the
acceptance table), `docs/consumers/jobhunt-handoff.md` (§4 R3, §5 R4, §7 R7,
§9.3 the registry block, §10 the live blocker — which becomes *moot*),
`docs/integration-guide.md` (the `callback_url` opt-in paragraph gains the
choose-your-path framing), `config/registry.example.yaml`.

**`docs/consumers/aitrader.md` is checked and left alone** unless its wording
requires otherwise: aitrader's guarantee rests on `allow_inbound: false` locking
it out of *every* path, and that is unchanged by narrowing another tenant's.
CG-27 already had to remove a false claim from that file about the mechanism's
existence; this row must not introduce its mirror image.

#### jobhunt's side — recorded, not actioned

`D:\prj\jobhunt\docs\chat-gateway-requirements.md` is **read-only to this
project**. The spec records what jobhunt must change and jobhunt's own project
acts:

- R1's *"registered callback URL"* and R3 entirely (forwarding → polling+ack).
- R6's *"the callback returns the chosen value"* → the inbox event carries it.
  The selection-widget mechanism is unaffected.
- R7 restated as jobhunt-side poller staleness (above).
- R8's *"HTTP on the appserver LAN/tailnet"* → outbound HTTP from jobhunt only.
- R9's *"the new inbound callback"* → the new inbound poller.
- Its OD9 port question (`8763`) can be closed as **moot**.
- **No code to delete** — the receiver was never built (§2.1).

**Merge gate: no**, but it is hard-rule-#6 territory. It **narrows** jobhunt's
inbound surface, which the user's decision A authorizes explicitly. It widens
nothing.

### 4.6 CG-58 — structured adapter failures and `Retry-After`

#### The defect is larger than the brief stated, and cheaper to fix than it looks

The brief: *"both retry paths ignore `Retry-After`"* — `delivery.py` at
`BACKOFF_S = (0, 30, 120, 600, 3600)` and `forwarder.py` at `(0, 3, 7)`.
Confirmed, both.

But the reason is structural, and fixing the *reason* fixes more than the
symptom. **The adapters do not carry the status code anywhere a retry policy can
reach it.** `WebhookDeliveryError` and `ChatApiError` render the status into
their message string and keep no attribute; `Dispatcher.process_due` catches bare
`Exception`. (`PubSubError` is the exception — it already carries
`.status_code`, and it is the model for the others.)

So the dispatcher cannot distinguish, today:

| | today | should be |
|---|---|---|
| `429 Retry-After: 120` | generic failure, retried on **our** schedule | wait what Google asked |
| `503` | generic failure | retry, ladder |
| **`403`** — webhook deleted, app removed from space, key revoked | **retried across the full ladder: 30s, 2m, 10m, 1h — over an hour of pointless calls before it reports `failed`** | permanent; fail on the first attempt |

The 4xx row is the one worth naming: it is a **current, observable defect in our
own logic**, needing no Google error response to demonstrate, and it makes the
gateway noisiest exactly when a credential has been revoked.

#### Design

1. `WebhookDeliveryError` and `ChatApiError` gain optional keyword `status_code`
   and `retry_after_s` attributes, defaulting to `None` so every existing
   message-only raise site is untouched. This is the `PubSubError` shape,
   applied to its two siblings — the same direction CG-23 and CG-33 already
   moved this file family.
2. A new `src/chat_gateway/retry_policy.py`, shared by both retry paths:
   retryable-status set; a `Retry-After` parser handling **both** legal forms
   (delta-seconds and HTTP-date); and `next_delay(...)` returning `None` to mean
   *permanent — stop now*.
3. Both `Dispatcher` and `CallbackForwarder` consult it.

#### Rules, and the reasoning for each

- **Non-retryable 4xx is permanent.** Fail on the first attempt with the reason
  named. Fixes the 403 row above.
- **`Retry-After` is honoured as `max(ladder_step, retry_after)`.** Never
  shorter than our own ladder — a hostile or buggy `Retry-After: 0` must not turn
  a retry into a hot loop against Google.
- **Clamped to a ceiling** (1h outbound). An absurd value must not park a job
  past the point anyone cares.
- **In `forwarder.py`, a `Retry-After` beyond that path's short horizon counts as
  exhaustion**, and R7's in-thread notice fires. A human tapped a button; a
  tenant asking the gateway to wait an hour has, for this purpose, failed.
- **⚠ The header is parsed to a float and the raw string is never carried into
  any message, log or exception.** `Retry-After` is server-controlled bytes,
  which is precisely the CG-33 lesson: `PubSubError` read `resp.reason_phrase`
  off the wire and had to be corrected to a local lookup. A new header read is a
  new instance of the same hazard and gets the same discipline from the start —
  parse, validate, discard the string.

#### What this does *not* claim

It does not clear anything from the verification ledger. Every branch it touches
is a branch **no Google error response has ever exercised** — that is the whole
premise of the workstream. Tests drive fakes returning 429 / 503 / 403 with and
without `Retry-After`; that is a *stronger* test suite, not evidence against
Google, and the row says so in those words so nobody reads a passing suite as a
cleared flag.

**Merge gate: no.** No secrets, no IaC. It touches `adapters/`, so hard rule #3's
flag discipline applies: **no ⚠ flag may be cleared, added or reworded.**

### 4.7 CG-59 — long-run observation, and what a deployed `/healthz` needs

`CLAUDE.md`'s ledger records that no multi-hour live run has happened for
`SubscriberLoop`. This row is that run. Depends on CG-55; the clock starts when
CG-55 lands.

#### The deployed-only finding: `/healthz` returns 200 while degraded

```
src/chat_gateway/service.py:469-471
    return JSONResponse(status_code=200,
                        content={"status": "degraded" if reasons else "ok", ...})
```

Hardcoded 200, always. For a hand-run gateway that is fine and arguably correct —
you read the JSON. For a **deployed** one this is a real gap, because Homepage's
`siteMonitor` and Beszel both judge by status code: the tile is **green while
inbound is dead**.

That is the claude-mem hardcoded-health-check failure — the one hard rule #5
exists because of, the one that hid 11 days of silent capture failure — occurring
one layer up, at the dashboard, against an endpoint that is itself scrupulously
honest. `/healthz` is not lying; the dashboard reading it cannot hear it.

**Recommended: add `GET /healthz?strict=1`, returning 503 when `reasons` is
non-empty and 200 otherwise, with an identical body.** Additive — no existing
consumer changes — and the homelab Homepage tile points its `siteMonitor` at the
strict form. `/healthz` plain keeps its current contract.

Chosen over changing the default because the default is a published contract with
existing readers, and because a 503 from a container health check would make
Docker restart a gateway that is *degraded but working* — e.g. one env var
unresolved on a tier-1-only host. Opt-in puts the choice with the reader.

#### The soak

Sample `/healthz` on an interval for **≥24h, targeting ≥72h**, recording:
`seconds_since_last_poll` (max, not mean — the mean hides a wedge),
`poll_failures` and `consecutive_poll_failures`, `thread_alive` / `thread_started`,
`events_seen`, `dispatch_errors`, container RSS, journal file size across at least
one compaction, and `inbox.pending` / `inbox.dropped`.

Deliverable: a dated observation section in the runbook — measured, not asserted,
in this queue's house style.

⚠ **Whether this clears the ledger's `SubscriberLoop` long-run row is a hard rule
#3 question and needs the user's explicit sign-off**, on the CG-35 precedent. The
row must present the evidence and **propose**; it must not clear a flag on its own
authority. A quiet subscription running for three days proves the thread
survives; it does not prove much about behaviour under load, and the difference
should be stated rather than smoothed.

#### Also in scope

Disk growth. The audit JSONL files (`inbox-data/`, `state/deliveries/`) are
per-app-per-day and **never pruned** — fine on the dev box, a slow leak on a host
meant to run for years. The row reports measured growth per day and **proposes** a
retention rule; it does not implement one, because a retention policy on an audit
trail whose entire purpose is that *"nothing is ever silently lost"* is a decision
with a rule-#5 flavour and belongs to the user.

**Merge gate: no** for the `?strict=1` code; the observation half is
user-executed.

---

## 5. Testing

Every row lands with tests in the existing offline style. Nothing in this arc
requires network access to test, including the deploy artifacts.

| Row | What is tested offline |
|---|---|
| CG-53 | env-file loader: precedence (environment wins), quote handling, comments, blank lines, missing-file-is-fatal, and **that no value is ever logged** |
| CG-54 | replay of open/update/close folds; attempts survive a restart; torn trailing line skipped and counted; unparseable mid-file line skipped and counted; compaction is byte-atomic and preserves exactly the surviving set; `REPLAY_MAX_AGE_S` expiry closes rather than sends; `journal=None` leaves every existing behaviour identical |
| CG-56 | ack removes only the acked ids; unacked redeliver on the next poll; default clear-on-read path unchanged |
| CG-57 | registry loads without `callback_url`; `allowed_users` still refuses at ingress and still never enqueues; a push-path tenant still validates and still forwards (proving nothing was ripped out) |
| CG-58 | 429 with delta-seconds; 429 with an HTTP-date; `Retry-After: 0` does not shorten the ladder; absurd value clamps; 403 fails on attempt 1 instead of burning the ladder; transport errors still use the ladder; **the raw header string appears in no message, log or exception** |
| CG-59 | `?strict=1` returns 503 iff `reasons` is non-empty, with a body identical to the plain form |

The suite is **202** on `main`. Each row states its own before/after count in its
PR rather than this spec predicting them.

---

## 6. Non-goals

- **Not rewriting `docker-compose.yml` out of existence.** It stays as the
  dev-box path; the NAS artifact is separate and captured.
- **Not deleting `CallbackForwarder` or the R7 path.** Explicit user instruction,
  and hard rule #6 names both inbound paths.
- **Not widening any inbound surface.** `aitrader` stays `allow_inbound: false`.
- **Not touching Terraform.** Never applied, not installed on the dev box,
  cannot be validated here — same scope call CG-51 made.
- **Not modifying anything outside chat-gateway.** `D:\prj\jobhunt` and
  `D:\prj\homelab` are read-only. Their required changes are recorded for their
  own projects to act on.
- **Not clearing any ⚠ flag.** CG-59 may *propose* one, with sign-off.
- **Not implementing audit-log retention.** CG-59 measures and proposes.

---

## 7. Open questions — for the user, deliberately not decided here

1. **CG-56 — inbox at-most-once → ack-based at-least-once?** Recommended, opt-in
   per request so nothing breaks. Changes a published contract, so it is the
   user's call. **Blocks CG-56's dispatch; does not block anything else** —
   CG-57 can document either answer.
2. **`/healthz` exposure on an allow-all tailnet.** It is unauthenticated by
   design (CG-12's bare-counter decision rests on it) and enumerates app ids and
   identity names to anyone who can reach the port. The homelab's restricting ACL
   is drafted but unapplied. Accept as-is and record it in Gotchas (recommended,
   and what this spec assumes), or file a separate item to restrict it?
3. **Image strategy** — build-on-box (recommended) vs publish to GHCR. Reversible
   either way; worth a nod before CG-53 ships, since it sets what the runbook
   says.
4. **Audit-log retention.** CG-59 will produce measured growth. The policy is the
   user's, because pruning a trail whose stated purpose is that nothing is
   silently lost is a rule-#5-flavoured decision.
5. **jobhunt's OD9 (§2.2).** No action needed here — decision A stands on
   topology-independence regardless. Flagged only so that if OD9 is accepted, the
   spec's *stated reason* does not read as falsified. Whether jobhunt's contract
   doc should record both reasons is jobhunt's call.

---

## 8. Merge gates

Per this queue's standing convention — IaC, deploy and secret-handling paths
pause and report before merging. **A row without a declared gate is not a
guarantee that none applies** (the CG-34 note); hard rule #2 territory pauses
regardless.

| Row | Gate | Why |
|---|---|---|
| CG-53 | ⏸ **yes** | secret handling (`.env` on-box layout, SA key mount), IaC-adjacent |
| CG-54 | no | core code, no secrets, no Google surface |
| CG-55 | ⏸ **yes** | deploy + secret handling; **user-executed** |
| CG-56 | no — but **dispatch blocked** on open question 1 | published-contract change |
| CG-57 | no | registry + docs; hard rule #6 territory, narrowing only |
| CG-58 | no | touches `adapters/`; **no ⚠ flag may be cleared, added or reworded** |
| CG-59 | no for code | any ledger change needs **explicit hard-rule-#3 sign-off** (CG-35 precedent) |

---

## 9. A note on identity literals in this arc

CG-26 extended the secret-scanning guard to `docs/**/*.md`, `tests/**/*.py` and
root `*.md`. **It will scan this spec, the plan, and the queue rows.**

This is not hypothetical. The first draft of the CG-22 + CG-9 plan hardcoded a
real name, email, Google user ids, tenant ids **and a live capability-URL bearer
token** into a file staged for this **public** repo; it was caught before push
and the commit discarded. The fix was to name JSON paths instead of values.

Every artifact in this arc follows that rule: **sources and paths, never
values.** Concretely, and deliberately:

- No emails, no `users/…` ids, no `domainId` / `customer` values, no tokens, no
  space ids, no webhook URLs.
- The SA key **filename** is not pinned in the compose file or in this spec —
  `docs/google-cloud-setup.md` records it, and CG-51 made the setup scripts
  derive it.
- **Homelab addressing is named by its source file, not by value.** The NAS LAN
  address, tailnet hostname and SSH user/key are defined in
  `nas/scripts/lib/common.sh` and `network/tailnet.md` in the homelab repo; the
  runbook in this **public** repo references those files and uses placeholders.
  That is not vagueness — it keeps another project's internal addressing out of a
  public repo, and it gives the values one home rather than two that can drift.
