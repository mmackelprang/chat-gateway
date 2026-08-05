# Production-readiness arc — design spec

**Date:** 2026-07-31 · **Status:** proposed, awaiting user review
**Queue rows:** CG-53 … CG-59
**Plan:** [`../plans/2026-07-31-production-readiness-arc.md`](../plans/2026-07-31-production-readiness-arc.md)

---

## 0. The premise

> ⚠ **THE PREMISE OF THIS WHOLE SECTION EXPIRED ON 2026-08-05, and the section is
> kept verbatim below because it is the record of the state this arc set out to
> change.** The gateway is **deployed and serving** on the NAS since 2026-08-05
> (CG-55, PR [#66](https://github.com/mmackelprang/chat-gateway/pull/66),
> `4ddd6f5`, Builder-executed over SSH). `main` has moved far past `670a5d8`, and
> the test count is **not** 202 — that number's one home is `CLAUDE.md`'s Layout
> section and it is deliberately not restated here, which is the mistake this
> paragraph made and which `CLAUDE.md` itself records having made twice.
>
> **What the deploy established has exactly one home: `docs/deploy/nas.md` §10
> *Executed*.** The five facts, the seven deviations and the counters are not
> summarized here — they are the most copy-tempting numbers this project has
> produced and every one of them moves.
>
> **Read every future tense in §0 through §4 as the tense of 2026-07-31.** Where a
> specific claim went on to be falsified rather than merely fulfilled, it carries
> its own dated correction inline. This banner is not a substitute for those; it
> is the reason they exist.

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

## 0.1 Premise correction (2026-07-31) — the Chat app is in FOUR spaces, not one

This spec was first written against the premise *"Tier 2 is live in the JobHunt
space ONLY."* **That is false**, and the correction changes enough that it sits
here rather than in a footnote.

**The corrected facts — a dated user statement about the Google Chat console, not
something this repository can prove or has measured:**

- The classic app **"Agent Comms" is DEPRECATED.** It was workspace-specific.
- It has been replaced by an app named **"Chat Gateway"** — same functionality,
  better interaction support in the space.
- **"Chat Gateway" participates in four spaces**: FamilyWorkspace, Ai Trader,
  Ai Trader Reports, and JobHunt.

No source file, no registry entry and no test records which spaces an app has
been added to. The registry's `space:` per identity is a **posting target** —
where the gateway *sends* — and is not a record of membership; the two can
disagree in either direction. So this is recorded exactly as
`docs/google-cloud-setup.md` already teaches: a console snapshot, dated, that
goes stale the moment somebody changes it.

### 0.1.1 The consequence that matters — and it was PREDICTED

Re-derived here by running the real `apps_for_space` against the **live**
(gitignored) `config/registry.yaml`, not by reading it, and reported without
reproducing any space id:

| Space (anonymised) | `apps_for_space` | `allow_inbound` |
|---|---|---|
| S1 | `['aitrader']` | **false** |
| S2 | `['job-hunter']` | true |
| S3 | `['aitrader']` | **false** |
| S4 | `['aiteam-harness']` | true |

**Four distinct spaces are configured, and every one has a `space:` already
filled in.** The registry was already wired for all four; the app's *absence*
from three of them was the only thing keeping events from flowing.

So: **every event in either Ai Trader space now increments `suppressed_opt_out`
on an unauthenticated `/healthz`.** Hard rule #6 still holds absolutely —
nothing crosses to aitrader, the `continue` fires before any `inbox.put` — but
CG-12's recorded caveat, *"a de-facto unauthenticated activity meter for that
tenant by inference"*, has gone from hypothetical to a **live property of the
deployment**.

**`docs/consumers/aitrader.md` predicted this exact trigger, in these words:**

> So the safeguard is **one step away, not two.** … In the live registry the
> `space:` is **already filled** — adding the Chat app to an aitrader space would
> be sufficient on its own, and it is a console action that leaves no trace in
> version control.

**The prediction fired.** That reframes the repo-wide correction (CG-60): its job
is not merely to delete a sentence that went false, but to convert a documented
*prediction* into a documented *live state* — which is a stronger and more useful
edit, and one that vindicates rather than embarrasses the file.

### 0.1.2 A second consequence the correction brief did not name

The same re-derivation shows **S4 → `['aiteam-harness']`, `allow_inbound: true`,
and `allowed_users` empty** (empty = no restriction).

⚠ **A dated measurement, correct on 2026-07-31 and superseded on 2026-08-03** —
kept as written, because a measurement with a date is a record and rewriting it
would destroy the evidence that made D1 worth taking. The live file now carries
`allow_inbound: false` for this app, **written explicitly rather than defaulted**,
which is exactly the distinction D1 was about (§4.0b, and the plan's Part I2).

`dispatch()` is **event-type agnostic** — it filters on space ownership, opt-in
and allowlist, never on event type, and calls `inbox.put(reply)` for whatever
arrives. So events in the FamilyWorkspace space are now **enqueued to
`aiteam-harness`'s inbox and written to the JSONL audit trail on disk**, with no
sender restriction and no evidence anyone is draining that inbox.

Consequences, each stated at its real confidence:

- **Certain, from the code:** an undrained inbox fills to `max_pending: 1000`,
  then silently drops its oldest (`inbox.dropped` counts). The JSONL audit keeps
  everything, forever, unpruned.
- **Certain, and it cuts against complacency:** under **CG-54** this content
  becomes *persisted across restarts* rather than lost. Durability makes this
  finding bigger, not smaller.
- **NOT knowable from this repo:** *which* events Google actually sends. A
  classic app in a room conventionally receives a MESSAGE only when @mentioned,
  which would make this near-empty; if it receives more, it is a family
  workspace's message content sitting in an unread queue and an unpruned audit
  file. **This repo cannot answer that, and must not guess.**

> ✅ **RESOLVED by user decision D1 (2026-07-31): `aiteam-harness` is set
> `allow_inbound: false`, filed as CG-61 (§4.0b).** Once that lands, events in
> that space are **discarded entirely** — verified against `dispatch()`: an
> opted-out owner's event cannot reach `_unrouted` either, because the
> `or [UNROUTED]` fallback only fires when a space has **no** owner. Nothing
> reaches the inbox, nothing reaches disk, only the counter moves.
>
> **Two consequences for the rest of this spec, applied rather than left
> dangling:** the first-drain privacy observation (§4.3) is now about
> **`job-hunter` only** — the FamilyWorkspace framing is withdrawn there; and
> audit-log growth (§4.7) now accrues from one tenant, which is part of D5's
> reasoning for measuring before setting a retention window.
>
> ⚠ **Ordering matters and is easy to miss:** CG-55 streams the live registry to
> the NAS. If CG-61 has not landed in that file first, the deployed gateway runs
> with `allow_inbound: true` and the first drain writes this content to disk —
> the exact outcome D1 exists to prevent. §4.3 makes it a **fail-closed
> pre-flight assertion**, not a thing to remember.
>
> ✅ **BOTH HAPPENED, in the right order — corrected 2026-08-05.** The operator
> edit landed **2026-08-03**; the pre-flight ran on the box on **2026-08-05** and
> **PASSED** (`{aiteam-harness: False, job-hunter: True, aitrader: False}`,
> `docs/deploy/nas.md:644`). **The deployed gateway runs `allow_inbound: false`
> for `aiteam-harness`.** ⚠ **This paragraph and §4.3's copy of it are the two
> sentences in this file that now read as live security claims about a running
> host, and both were false.** The full framing — including why being false in the
> *safe* direction here is luck rather than design — is stated once, in the plan
> at Part C, under prerequisite **(b)**. Do not restate it; there are already
> three copies of the claim and one copy of the correction is the right ratio.
>
> ⚠ **Neither of these two was on CG-79's routed list.** That row grepped for the
> claims it knew about and re-checked every coordinate it published, which is why
> its list is trustworthy — but a routing list is a floor, never a ceiling, and
> this is the evidence. The plan's copy was routed; the spec's two were not.

### 0.1.3 What does NOT change

- **Decisions A and B stand**, unmodified.
- **`aitrader` stays `allow_inbound: false`.** Nothing here widens any inbound
  surface; hard rule #6 is doing exactly its job, visibly.
- **No ⚠ flag is cleared, added or reworded.** In particular `CLAUDE.md`'s ledger
  row recording `sender: {displayName: "Agent Comms"}` is a **correct historical
  observation** — that response really did carry that name on 2026-07-29. The
  observation is not rewritten; CG-60 adds a dated note that the app has since
  been replaced.

---

## 0.2 Second premise correction (2026-07-31) — the NAS, measured rather than described

Two further corrections arrived, and both were **probed read-only against the box
rather than taken on description.** Everything in this section is measured.

### 0.2.1 The deploy can be EXECUTED — `ssh claude@nas`, passwordless sudo

`ssh nas` works with `BatchMode`, `id -nG` returns
`claude builtin_administrators builtin_users`, and **`sudo` is passwordless —
effectively root.** TrueNAS Scale on Debian 12 bookworm, kernel
`6.12.91-production+truenas`, Docker `28.3.1`, storage driver `overlay2`.
`claude` is **not** in a `docker` group, so every docker call needs `sudo`.

This changes CG-53 and CG-55 from *"write instructions and hand over"* to
*"execute and verify"* — and it makes the SSH policy in §4.3.1 a required part of
the plan rather than a courtesy.

### 0.2.2 The NAS is NOT "backup target only" — so this is NOT a role change

That framing came from jobhunt's `two-host-split.md`, whose column header is
*"Role **here**"* — its role in **jobhunt's** pipeline, not globally. My earlier
draft repeated it and built a "blast radius of making the NAS an app host"
section on top. **Both are withdrawn.**

Measured: **15 running containers across 10 app stacks** — beszel (×2), calibre,
calibre-web, claude-mem (×5, including Postgres), czkawka, homepage, jellyfin,
pihole, tailscale, upsnap. Every one named `ix-<app>-<service>-1`, which
independently confirms §1.1's custom-app/middleware model. Config under
`/mnt/datapool/apps`; pools `boot-pool` + `datapool`.

**The real blast-radius question is narrower and answerable with numbers: what
does an *eleventh* stack do to a box already running these?**

⚠ **This said *"a tenth stack"*, and so did §4.1's heading and body — wrong when
written, corrected 2026-08-05.** The **10 app stacks** measured three lines above
are the ones already there, so the gateway is the **eleventh**; the live
`app.query` now lists 11. The right number and the wrong one sat within three
lines of each other, in this file and in `nas.md` §1, for five days — **because a
heading reads as a title and a paragraph reads as data, and nobody compares
them.** It then propagated by quotation into `nas.md`'s §1 heading, a briefing and
a sibling agent's task, and was caught only because that agent counted the live
`app.query` instead of trusting what it had been told. **CG-69 category (b)** —
wrong when written, not gone stale — which that spec's §8 says plainly no guard in
this repo can reach. Full account: queue § CG-79, *"Fact 6"*.
**The measured `10 app stacks / 15 containers` is correct and is left alone**;
only the ordinal derived from it was ever wrong.

| Measured | Value | Reading |
|---|---|---|
| RAM total / available | 31.9 GB / **20.8 GB available** | a small Python service is noise |
| Load (1/5/15m) | 0.29 / 0.42 / 0.39 on **16 cores** | effectively idle |
| `datapool` | 13 TB, **1% used** | journals and audit JSONL are irrelevant at this scale |
| Heaviest tenant | jellyfin, 1.23 GiB (of a 4 GiB cap) | nothing is near a limit |
| **Swap** | **0** | ⚠ **the one real finding** |

⚠ **Zero swap is the whole of the risk.** There is no cushion: a memory spike
anywhere is an OOM kill, and the box hosts claude-mem's Postgres. So the
gateway's compose **should declare a memory limit** — and that is a **deliberate
deviation from house style**, because it was measured that **no existing custom
app declares one** (`mem_limit` is unset on all of beszel, homepage, upsnap,
pihole, czkawka and every claude-mem service; the 4 GiB caps visible on jellyfin,
calibre, calibre-web and tailscale are TrueNAS's own, applied to *catalog* apps).
✅ **Decided: set one (D6, §7)** — recorded as a deliberate deviation rather than adopted silently.

**Measured port facts**, replacing the list this spec previously took from the
homelab docs. In use: `22 53 80 139 443 445 3000 5357 5800 6000 6999 8081 8090
8098 30013 30014 31067 32014 32015 32016 37877 41175 62716`. **`8085` is free.**
The app name `chat-gateway` is also free — `app.query` returns `[]`, a
fail-closed check that must be re-run at deploy time rather than trusted from
here.

### 0.2.3 Tailscale is a container — and the probe INVERTS the concern

The concern was that `ix-tailscale-tailscale-1` being a container means tailnet
exposure is *not* simply binding a host interface, and would need a subnet
router, userspace proxy, sidecar, or `serve`/`funnel`. **Measured, it needs none
of those:**

| Probe | Result |
|---|---|
| `HostConfig.NetworkMode` | **`host`** |
| `Devices` | **`/dev/net/tun`** |
| `CapAdd` | `CAP_NET_ADMIN`, `CAP_NET_RAW`, `CAP_SYS_MODULE`, … |
| `TS_USERSPACE` | **`false`** |
| `ip link` on the **host** | **`tailscale0` present, global-scope address, kernel-mode** |
| `TS_EXTRA_ARGS` | `--advertise-exit-node=false --reset=false --accept-routes=false` |

The container runs `tailscaled` in **kernel mode inside the host network
namespace**, so it creates a **real `tailscale0` interface on the host**. A
published container port bound to `0.0.0.0` is therefore reachable over the
tailnet with **no additional plumbing at all** — exactly the "usual host-daemon
assumption", which happens to hold here.

**But it holds for a non-obvious reason, and that reason is load-bearing**: if
this app were ever reconfigured to `TS_USERSPACE=true`, or off host networking,
`tailscale0` would disappear from the host and every service's tailnet
reachability would silently vanish with it. That is a dependency worth writing
down in the runbook's Gotchas, because nothing in the gateway's own config would
show it. It also confirms the node is a **plain tailnet node** — not an exit node,
not a subnet router, not accepting routes — so nothing here is routing for anyone
else.

`tailscale` is **not on the host PATH**; any tailnet inspection goes through
`sudo docker exec ix-tailscale-tailscale-1 tailscale …`, which §4.3.1 classifies
as touching another stack.

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
| 0 | **CG-60** repo-wide correction of the one-space premise | **New, and it goes first.** Docs-only, no dependencies — and `docs/consumers/aitrader.md` currently tells that tenant's operator something **false about their own privacy posture** (§0.1.1). A live-false claim in a consumer contract outranks preparatory work; CG-27 set that precedent by shipping exactly this kind of removal as its own item. |
| 0b | **CG-61** close `aiteam-harness`'s inbound path (D1) | **New.** Behaviour change, so it is not folded into CG-60 (§4.0b). **Must land before CG-55**, which streams the live registry to the box. ✅ **It did — PR [#50](https://github.com/mmackelprang/chat-gateway/pull/50) merged 2026-07-31, and the operator's live-registry edit followed on 2026-08-03**, two days before CG-55 ran. |
| 1 | **CG-53** deployment artifacts + secret-safety proof (**no deploy**) | Largest unknowns, and it carries the §1.2 leak finding. That finding must not wait behind two code PRs. Produces the image strategy, the on-box layout, the `CHAT_GATEWAY_ENV_FILE` loader, and the runbook — all offline-verifiable. |
| 2 | **CG-54** queue + inbox durability | The **only hard prerequisite** for an always-on deploy. `restart: unless-stopped` means the thing restarts by itself; every restart silently empties both queues. A trusted always-on service that loses work on restart is worse than a hand-run one that does, because nobody is watching. Offline-testable. |
| 3 | **CG-55** first NAS deploy + live smoke (~~**user-executed**~~ → ⚠ **BUILDER-executed over SSH** — this cell was already contradicted by §4.3's opening line in the same file, which says in so many words that it *"supersedes the earlier user-executed … framing"*; the sequencing table simply never got the edit. It ran that way on 2026-08-05) | Everything after this benefits from being observed on a running instance, and **the soak clock starts here** — so CG-59 harvests days of real uptime instead of beginning a wait. ✅ **It landed 2026-08-05 (`4ddd6f5`) and the clock has been running since.** |
| 4 | **CG-56** inbox delivery semantics (at-most-once → ack) — ✅ **approved, D3** | Before the contract doc is rewritten, so it is written once. |
| 5 | **CG-57** jobhunt `callback_url` → passive polling | Documents the *final* semantics, whichever way CG-56 resolves. |
| 6 | **CG-58** structured adapter failures + `Retry-After` | Improves a running system; needs no deploy to test (fakes can return 429 + `Retry-After`), and benefits from real traffic having been seen. |
| 7 | **CG-59** long-run observation + what a **deployed** `/healthz` needs | Strictly after a deploy. Harvests the soak from step 3. ✅ **The deploy happened 2026-08-05; nothing blocks this row and the clock is running.** ⚠ Its `?strict=1` half became *more* urgent that day, not less — the homelab Homepage tile now probes plain `/healthz`, which answers 200 while degraded (§4.7). |

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

**Does four live spaces change the sequence?** It adds CG-60 at the front and
otherwise **reinforces the existing order rather than disturbing it**:

- **CG-54 before the deploy gets stronger, not weaker.** Inbound is no longer
  hypothetical — three of the four spaces now route to an opted-in or opted-out
  owner, and the first deploy will drain a real backlog into a queue that is
  in-memory today.
- **The deploy's blast radius grew**, which is an argument for the artifacts
  (CG-53) and durability (CG-54) preceding it, not for hurrying it.
- **CG-59's soak got more valuable**, because the subscription is no longer quiet
  (§4.7).
- Nothing argues for moving CG-56, CG-57 or CG-58.

**Nothing in this arc widens any tenant's inbound surface.** `aitrader` stays
`allow_inbound: false`. Decision A *narrows* jobhunt's. Hard rule #6 holds
throughout, and CG-57 is the row that touches it — narrowing only.

---

## 4. Workstream specs

### 4.0 CG-60 — repo-wide correction of the one-space premise

**Sequenced first** (§3). Documentation only; no code, no registry change.

The claims below went false when the app was replaced and added to four spaces
(§0.1). They were **located by text** and must be **re-derived, not trusted from
this list** — line numbers move, and this repo's own convention (CG-52) is to
find a paragraph by its words.

| File | Claim | Why it is now wrong |
|---|---|---|
| **`docs/consumers/aitrader.md`** | *"the Chat app is not in aitrader's spaces, so no Pub/Sub event originates from them"* | **Highest priority.** The reasoning is falsified, and this is a **consumer contract** telling that tenant's operator something untrue about their own privacy posture |
| `docs/google-cloud-setup.md` | the dated *"JobHunt space only"* console observation; the app-name guidance; the sender table | superseded console facts |
| `docs/integration-guide.md`, `docs/consumers/jobhunt.md`, `docs/consumers/jobhunt-handoff.md` | *"Agent Comms"* as the live identity | the app is now **"Chat Gateway"** |
| `docs/BUILDER_QUEUE.md` | several | **judge claims vs records** — shipped rows are history and stay |

#### The aitrader edit is a promotion, not a retraction

That file already contains the prediction, in its own words:

> So the safeguard is **one step away, not two.** … adding the Chat app to an
> aitrader space would be sufficient on its own, and it is a console action that
> leaves no trace in version control.

**It came true.** So the edit converts a documented prediction into a documented
**live state** — and the surrounding table (`registry.example.yaml` → `[]` vs
`registry.yaml` → `['aitrader']`, *"would increment `suppressed_opt_out`"*) needs
only its tense changed from conditional to present. That is a far better edit
than deleting a sentence, and it vindicates the file.

It must also state plainly what has **not** changed: hard rule #6 holds, the
`continue` fires before any `inbox.put`, and **nothing crosses to aitrader**. The
disclosure is a volume counter on an unauthenticated endpoint (D2, §7), not a
data path.

#### The historical observations stay

⚠ `CLAUDE.md`'s ledger row recording `sender: {displayName: "Agent Comms"}` — and
the identical sentences in `adapters/chat_api.py`'s docstrings — are **correct
observations of what happened on 2026-07-29**. They are evidence, not claims
about today.

**Do not rewrite them. Do not reword or clear any ⚠ flag** — that needs the
user's explicit sign-off naming hard rule #3, which this row does not have. Add a
**dated note** that the app has since been replaced, adjacent to the observation,
leaving the observation intact. This is the CG-50 shape exactly: the finding is
kept, the currency pointer is what changes.

Record the new facts as a **dated user statement about the console**, in the
voice `docs/google-cloud-setup.md` already uses — not as something measured.
What *is* measured, and should be labelled as such, is the `apps_for_space`
re-derivation in §0.1.1.

**Merge gate: yes** — consumer contracts, and it works next to the ledger.

---

### 4.0b CG-61 — close `aiteam-harness`'s inbound path (decision D1)

**Sequenced second, and it MUST land before CG-55.** Registry + documentation.

Set `allow_inbound: false` on `aiteam-harness`. Reasoning and the verification
behind it are in D1 (§7); it is **not restated here** — this section covers only
what the row must do.

#### Why a separate row rather than folding it into CG-60

CG-60 is a **documentation correction with no behaviour change**. This **changes
behaviour**: events in that space stop being enqueued and stop reaching disk.

**This repo has an established split for exactly that pair.** CG-19 was scoped
comments-and-illustrative-defaults-only and **explicitly declined** to change
emitted behaviour, filing the behaviour change as CG-51 with its own gate. Mixing
them makes the docs PR unreviewable *as docs* and buries a live-config change in
a sweep of prose edits. The gates differ too: CG-60's is consumer contracts;
this one narrows a tenant's inbound surface — hard rule #6 territory.

It also carries a sequencing constraint CG-60 does not: **it must precede CG-55's
config transfer.**

#### What the row can and cannot touch

⚠ **`config/registry.yaml` is gitignored.** A PR **cannot** change the live file.
The row therefore delivers:

1. `config/registry.example.yaml` — `allow_inbound: false` on `aiteam-harness`,
   with the reasoning in a comment (default corrected, not a verdict; reversible
   in one line).
2. The documentation: `CLAUDE.md`'s consumer list, and any place describing that
   app's inbound posture.
3. **A recorded operator action**: the live registry on the dev box must be
   edited to match. Verified 2026-07-31 that it currently reads
   `allow_inbound=True`, so this is a real edit, not a no-op.
   ✅ **DONE 2026-08-03** (mtime `2026-08-03T20:34:06Z`); `allow_inbound: false`
   is now written **explicitly**, not defaulted, and CG-55's fail-closed
   pre-flight confirmed it on the box on 2026-08-05. The 2026-07-31 measurement
   is left as written — it is dated, and it was true. **Only the tense is
   corrected, and the plan's Part I2 holds the account of the four days in
   between.**
4. A test proving an opted-out owner's event reaches **neither** the app's inbox
   **nor** `_unrouted` — pinning the property D1's benefit rests on, so a future
   refactor cannot quietly reintroduce the disk write.

#### Collision note

CG-57 also edits `config/registry.example.yaml` (removing `job-hunter`'s
`callback_url`). They are **independent in content and sequential in time** —
CG-61 before CG-55, CG-57 after — so the queue's standing warning about two rows
touching one file does not bite here. Recorded because that warning exists and a
reader comparing the two should not have to re-derive this.

**Merge gate: yes** — a live-config change narrowing a tenant's inbound surface.

---

### 4.1 CG-53 — deployment artifacts and the secret-safety proof

**Ships no deploy.** It ships the artifacts, the layout, the one small code
change that makes rule #2 hold on the NAS, and a runbook.

#### Blast radius — the ELEVENTH stack, not a role change

⚠ **This section previously read "the role change, stated" and claimed the NAS
was backup-target-only. That was wrong and is withdrawn — see §0.2.2.** The box
already runs **10 app stacks / 15 containers**, including a five-container
claude-mem deployment with Postgres. The gateway is an **eleventh stack on an
established app host**, so the question is capacity, not precedent. *(Said
"tenth" — heading and body both — until 2026-08-05; it was wrong when written.
The ordinal, not the measurement: see §0.2.2's correction note.)*

Measured (§0.2.2): **20.8 GB RAM available, load 0.29 on 16 cores, `datapool` 1%
used.** A small Python service is noise against that.

**The one real finding is that the box has zero swap**, so any memory spike is an
OOM kill on a host running someone else's Postgres. Mitigations, in order of
force:

- **Declare a memory limit on the gateway service** — a deliberate deviation from
  house style, since it was measured that no existing *custom* app sets one.
  Open question 6.
- A distinct non-colliding published port. **`8085` is free, measured** — the
  in-use set is in §0.2.2, and it is *not* the set this spec previously quoted
  from the homelab docs.
- **No `network_mode: host`** — the gateway needs one port, not the box's network
  namespace.
- No new capabilities; bind mounts confined to `/mnt/datapool/apps/chat-gateway`.
- No change to any existing app's config — §4.3.1 makes that a hard stop.

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

**DECIDED: option 1, build on the box (D4).** No registry, no credentials, no
external dependency in the deploy path. Two consequences the runbook owns: **the
box needs the source** — a `git clone` of this public repo at a pinned commit is
the auditable form, with a tarball over stdin as the fallback if the box lacks
egress — and **a rebuild is a manual step**, so the runbook carries the upgrade
procedure. Option 2 stays named as the upgrade path if rebuilding ever becomes
the annoyance.

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
  ⚠ **Re-tested 2026-08-03 against the degrade machinery that did not exist when
  this was written** (CG-72, CG-74, CG-75, and CG-76, which landed as #63 the
  same day this was re-tested). The obvious
  challenge is that `/healthz` is far better at reporting trouble now, so
  "boot degraded and complain loudly" might have become the better option.
  **It has not, and the reason is sharper than the original one.** The channel
  built to notice silence is the **dead-man switch**, and it reports by *sending
  a Chat message* — which is precisely what a gateway with no credentials cannot
  do. A credential-less boot would therefore be invisible in the one place
  designed to catch invisibility, which is CG-76's entire finding applied to
  startup. Refusing to start is the only failure mode that cannot be swallowed.
  **Second-order effect, accepted and recorded rather than discovered:** under
  `restart: unless-stopped` a fatal config error is a **crash loop**. That is
  cheap — the process exits before the dispatcher is constructed, so it generates
  **no** Google traffic and cannot reset any backoff ladder — but it means the
  operator's first diagnostic is `docker logs`, not `/healthz`, and the runbook
  must say so or a restarting container reads as a bug.
- **Values are never logged.** The loader reports the count of keys loaded and
  the path, never a key's value. Key *names* are non-secret (they are in the
  committed `.env.example`); values are the whole point.

- **Environment wins is not just a test-ergonomics property — it is load-bearing
  on the box.** ⚠ **Added 2026-08-03.** The `.env` transferred to the NAS is the
  dev box's, so it carries dev-relative paths. The compose sets the three
  container paths, and "environment wins" is what makes those override the file's
  stale values rather than the reverse. **Two keys are NOT in the compose and so
  are not saved by it** — `GOOGLE_APPLICATION_CREDENTIALS` (whose filename is
  deliberately never pinned in compose, per CG-19/CG-51) and
  `GATEWAY_ENABLE_PUBSUB`. Both must be corrected on the box; the runbook owns
  the check. This is a **direct consequence of property #1**, so it belongs
  beside it rather than being discovered during a deploy.

Result: `custom_compose_config` carries **`CHAT_GATEWAY_ENV_FILE` and a handful
of non-secret paths, and nothing else.** `capture.sh` is then clean *by
construction* — the redactor's suffix list stops being load-bearing for us.

⚠ **The suffix-list premise RE-MEASURED 2026-08-03, and it holds.** It is the one
load-bearing fact in this row that lives in a repo this project does not control
(`/mnt/d/prj/homelab`, read-only), which is exactly the "external world" category
CG-69 classifies as unwatchable by any guard here — so it is checked, not quoted.
Running that repo's real `is_secret_key` over this project's real key names: all
seven credential vars **miss**; `GOOGLE_APPLICATION_CREDENTIALS` is the only
catch, and it is a path. End to end through the real redactor and the real scan
gate, a payload carrying a live-shaped API key and webhook URL came back **with
both values intact and the gate exited 0**, while a `POSTGRES_PASSWORD` control
in the same payload was redacted — which is what makes the green console line
persuasive rather than merely wrong.

**One correction to how this row states the finding.** The claim has been *"the
`__<SUFFIX>` convention defeats the suffix rule, on exactly the two families that
are real credentials."* Both families do leak, but **for different reasons, and
only one of them is the convention's doing**:

| Var | Bare form | With `__<SUFFIX>` | So the cause is |
|---|---|---|---|
| `CHAT_GATEWAY_API_KEY__<APP>` | ✅ caught (`API_KEY`) | ❌ missed | **the convention** |
| `GOOGLE_CHAT_WEBHOOK_URL__<IDENTITY>` | ❌ **missed anyway** | ❌ missed | **the list has no `URL` entry** (only `DATABASE_URL`) |

**This matters because it kills the cheap fix.** *"Rename the vars so the suffix
rule catches them"* would work for the API keys and do **nothing** for the
webhook URLs — the higher-value secret of the two, since a webhook URL is a
bearer credential with **no rotate-in-place**. Nor does any value-based rule
help: the URL-credential regex looks for `scheme://user:pass@host`, and a webhook
carries `key`/`token` as **query parameters**. Structural containment is not the
convenient answer here; it is the only one.

⚠ **The list changed on 2026-08-03 — check what changed before trusting this.**
That repo's `lib/redact_json.py` was edited the same day this was re-measured,
but `SECRET_KEY_SUFFIXES` itself was **not** touched (18 entries, unchanged since
before 2026-07-31); the commit added *reference* exemptions (`{{VAR}}`, `$(…)`,
angle-bracket placeholders). **The direction of travel is toward more exemptions,
not more catches**, which is a reason to keep this measured on a date rather than
assumed to be improving.

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

Any `chat-gateway-sa*.json` that is **not** `chat-gateway-sa-gw.json` is **dead**
— it belongs to the deleted `chat-gateway-prod` project. The runbook says so at
the step where an operator would otherwise reach for it, and says to confirm by
the key's own `project_id` rather than by its filename.

⚠ **REWORDED 2026-08-05, not dropped.** This named one path,
`iac/chat-gateway-sa.json`, and **the user deleted that file on 2026-08-05** — so
a warning phrased around its presence now describes nothing, which is worse than
saying nothing, because a reader who does not find the file concludes the hazard
is gone. It is not: copies live in old checkouts, backups and clones, and
`iac/gcloud-setup.sh` and its `.ps1` sibling **still default `KEY_FILE` to that
exact filename**, so re-running setup writes it back. **A warning keyed on a path
this repo has deleted protects nobody; one keyed on the shape survives the
deletion.** CG-55's row set the rewording-not-dropping condition before the
deletion landed; CG-79 carried it out elsewhere in the repo and routed this file
here. The deploy itself is the proof the shape rule is the right one — §10
deviation 7 records that both keys' `project_id` fields were read to tell them
apart, so **the check never relied on the filename.**

#### Getting `.env` and `registry.yaml` onto the box

Both are gitignored dev-box files. Neither may enter the repo, and neither may
enter the compose document. They are `scp`'d from the dev box over the existing
homelab SSH path (user and key are defined in `nas/scripts/lib/common.sh`; this
spec names that file rather than reproducing the values), then `chmod`'d.

The runbook states the ordering constraint that makes this safe: **create the
directory tree with restrictive modes first, then copy** — never copy into a
world-readable directory and tighten afterwards.

#### Tailnet exposure — resolved by measurement (§0.2.3)

**Publishing `8085` is sufficient.** `ix-tailscale-tailscale-1` runs host-networked
with `/dev/net/tun` and `TS_USERSPACE=false`, so `tailscale0` is a **real host
interface** and a port bound to `0.0.0.0` is tailnet-reachable with **no subnet
router, userspace proxy, sidecar, `serve` or `funnel`.**

⚠ **Record the dependency, because nothing in the gateway's config reveals it:**
that reachability is a property of *another app's* configuration. If tailscale is
ever switched to userspace mode or off host networking, `tailscale0` disappears
from the host and every service's tailnet reachability silently goes with it.
Runbook Gotcha, not a footnote.

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
discovery.

✅ **RESOLVED 2026-08-03 — and this section proposed the answer that was taken.**
It read: *"the mitigation available today at zero cost is to bind the published
port and let the ACL work land in the homelab repo on its own schedule; if the
user wants `/healthz` restricted, that is a separate item and is listed in §7 as
an open question rather than decided here."* The user decided exactly that:
**the D2 ACL is deferred, and CG-55 binds the LAN address instead of `0.0.0.0`.**
So *"publishing `8085` is sufficient"* above is still true as a **measurement**
about tailnet reachability, and is no longer the **plan** — the deployment
declines that reachability deliberately. ⚠ **The two halves are one decision:**
the bind is what makes the deferral sound rather than merely approximately sound,
and the bind does **not** replace the ACL — it removes tailnet reach to *this
port* and says nothing about the rest of that box. Reasoning, residual, and the
exact artifacts CG-55 must change live in **one** home:
`docs/BUILDER_QUEUE.md` § CG-55, *"Two user decisions, 2026-08-03"*. Not restated
here, and **not implemented by CG-53** — this row ships no deploy.

#### Deliverables

- `CHAT_GATEWAY_ENV_FILE` support in `__main__`, with tests.
- `docs/deploy/nas.md` — the runbook. Owned by this repo: it can test its own
  claims and the homelab repo cannot, and one home beats two.
  ⚠ **The justification stated here was FALSE and is withdrawn — corrected
  2026-08-03.** It read *"in the shape of the existing `docs/consumers/*-handoff.md`
  files … That split matches both repos' conventions."* Measured, it matches
  **neither**: that glob names exactly one file in this repo (its siblings are
  `aitrader.md` and `jobhunt.md`), and **no** `nas/services/*.md` in the homelab
  repo links out to another repo — all ten keep operational detail inline, and
  every link there is intra-repo and relative. **The decision stands; it is a
  deliberate deviation from that repo's house style, not a match to it**, and the
  runbook must say so rather than claim a convention it invented. The homelab-side
  file is still a four-header `nas/services/chat-gateway.md` (per that repo's
  `_TEMPLATE.md`) pointing here — ⚠ **written by the user, not by this row**; a
  chat-gateway Builder does not write that repo.
  ✅ **It has been written: homelab PR #21 (`feat/chat-gateway-service-artifacts`,
  open as of 2026-08-05) carries `nas/services/chat-gateway.md`, the restore
  wrapper, the `DASHBOARDS.md` entry, the Homepage tile and the `SECRETS.template.md`
  rows.** ⚠ **And it falsifies the measurement in this very bullet as it lands:**
  *"no `nas/services/*.md` links out to another repo — all ten keep operational
  detail inline"* was true when measured and stops being true the moment the
  eleventh file merges, **because this bullet commissioned the exception**. That
  is the deliberate deviation, doing exactly what the paragraph says it is — and
  it is recorded here rather than left for someone to re-measure and read as a
  contradiction. **CG-79 examined this line and correctly left it alone** (it
  counts a different set of ten and was accurate on the day); the thing that moved
  it is not one of CG-79's six facts at all.
- `.env.example` gains `CHAT_GATEWAY_ENV_FILE` with the "environment wins"
  semantics stated.
- `docker-compose.yml`'s header gains one clause scoping it as the **dev-box /
  local** path, so a reader does not take it for the NAS artifact. Its dated SA
  key comment is resolved to point at `docs/google-cloud-setup.md`.

**Merge gate: yes** — secret-handling path, and IaC-adjacent. Same gate CG-23,
CG-33, CG-34 and CG-51 carried. ⏸ **Held. Only the user releases it.**

#### What releasing this gate actually approves — stated 2026-08-03 so the decision is a real one

A gate nobody can describe is a rubber stamp. Precisely four things, and **none
of them is a deploy** — this row ships no deploy, touches no live registry, and
creates nothing on the NAS:

1. **A new code path that reads a file into the process environment at startup**
   — the first mechanism in this repo whose *purpose* is to move credentials.
   Its blast radius is bounded by the four properties above, each with a test.
2. **The judgement that the guarantee belongs in OUR code rather than compose's
   `env_file:`.** Approving this is approving that a hard-rule-#2 guarantee
   should not rest on an unverified property of a third-party renderer, at the
   cost of ~20 lines this repo now maintains forever.
3. **A published on-box layout and runbook** stating, in a public repo, where a
   deployment's secrets live, what modes they carry, and which four directories
   hold tenant message bodies. It names **paths and env-var NAMES only** — no
   values, no hostnames, no key filenames — but it is a real description of a
   real box's shape.
4. **The accepted residual:** `/healthz` stays unauthenticated, and after CG-55's
   LAN bind it is reachable by anyone on the home LAN. The tailnet ACL that would
   have narrowed the tailnet half is **deferred** (user, 2026-08-03).

**What it does NOT approve, and must not be read as approving:** the deploy
itself (CG-55, separately gated), the live-registry operator edit (CG-61), any
change to a ⚠ verification flag (none — this row exercises nothing against
Google), or the homelab-repo artifacts, which land in a repo this project does
not write.

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

#### What durability does NOT cover — say it, or the name oversells it

**"Queue durability" does not mean "no inbound event is ever lost."** The
subscription is created with `--message-retention-duration=24h` (both setup
scripts and the Terraform agree). A gateway that is **down for more than 24
hours loses inbound events at Pub/Sub, before any journal exists to protect
them** — the ceiling is set by the subscription, not by us, and no amount of
local persistence raises it.

This is worth writing down now precisely because §0.1 makes inbound real: three
of four spaces route somewhere, so "the gateway was off for a weekend" stops
being a thought experiment. The journal protects what the gateway has
**accepted**; nothing protects what it never pulled.

Two things follow, and both are deliberately *not* actions in this row: whether
24h is the right retention is an operator decision on the Google side, and a
gateway-down alarm is what the aitrader dead-man monitor already does for
consumers — pointing it at the gateway itself would be a **new item with its own
justification**, not a quiet widening of this one.

**Merge gate: no.** No secret handling, no IaC, no Google-facing code.

### 4.3 CG-55 — first NAS deploy and live smoke

**Builder-executed over SSH, within a declared blast radius** (§0.2.1). This
supersedes the earlier "user-executed, CG-15/CG-16 pattern" framing: the account
exists, works with `BatchMode`, and has passwordless sudo, so Builder can both
run and *verify* the deploy rather than hand over instructions and hope.

**That capability is also the largest one this arc introduces**, so it is bounded
before it is used.

#### 4.3.1 What a Builder may and may not do over that connection

Passwordless root on a box running 10 live stacks *(as measured 2026-07-31; **11
since the gateway joined them on 2026-08-05** — the blast-radius argument is
unchanged, and the number is recorded rather than silently left)* — including claude-mem's
Postgres — is a large blast radius. `claude` is not in a `docker` group, so
**every** docker call is `sudo docker`, i.e. root: a single `-v /:/host` would be
total host compromise. The policy therefore names *operations*, not tools.

| | Allowed | Examples |
|---|---|---|
| ✅ | **Read-only probing, unattended** | `docker ps`, `docker stats --no-stream`, `docker inspect`, `midclt call app.query`, `free`, `df`, `ss -tln`, `ip link` |
| ✅ | **Creating the gateway's OWN app, dataset, directories and config** — only within the declared paths | `/mnt/datapool/apps/chat-gateway/**`, and the single app name `chat-gateway` |
| ✅ | **Building and running the gateway's own image** | `docker build`, `midclt call app.create` for `chat-gateway` only |
| 🛑 | **Anything touching another stack** | never restart, stop, exec into, or reconfigure any other `ix-*` container — including `sudo docker exec ix-tailscale-tailscale-1 tailscale …` |
| 🛑 | **Anything global to the Docker daemon** | **never** `docker system prune`, `docker network prune`, `docker volume prune`, daemon restart, or image cleanup |
| 🛑 | **Anything touching the pools or TrueNAS itself** | no dataset changes outside the gateway's own path, no pool operations, no `midclt` write calls against another app |
| 🛑 | **The homelab repo's captured state** | `capture.sh` rewrites `nas/compose/*.json` for **every** custom app — it is a cross-repo write and belongs to whoever owns that working tree |

**Two additions to the position I was given, both from measurement rather than
principle:**

1. **Check the app name is free, fail-closed, immediately before creating it.**
   `midclt call app.query '[["name","=","chat-gateway"]]'` returns `[]` today —
   but this arc has already been wrong twice about what is on that box, and a
   non-empty result must abort rather than proceed. Same fail-closed discipline
   the homelab's own `restore.sh` uses.
2. **`capture.sh` is explicitly a STOP**, which the position I was given did not
   name. It looks like a verification step — CG-53 even makes reading its output
   a gate — but it writes files for **every stack on the box** into another repo.
   *(Said "all ten" until 2026-08-05. The count changes every time this runbook
   succeeds, which is why the rule is stated against the scope and not a number —
   `nas.md` §7 and the plan's standing-rules table make the same correction.)*

**On stopping:** a stop means *stop and report*, not *work around*. If the
gateway's app cannot be created without touching something on the 🛑 list, that
is a finding for the user, not an obstacle to route around.

#### 4.3.2 Getting the secrets onto the box — the highest-risk step in the arc

Real per-app API keys and webhook URLs (which embed `key`+`token` and **are**
bearer credentials with no rotate-in-place) must reach a live host. This is hard
rule #2 executed rather than described.

**The rule: secret material travels over stdin or as a file copy — never as a
command-line argument.** An argument lands in the local shell's history, in the
remote shell's history, and in `ps` output on a box other people's software runs
on. `sudo` logs the command it ran, not what was piped into it.

```
FORBIDDEN   ssh nas "echo '<secret>' > /path/.env"
FORBIDDEN   ssh nas "sudo sh -c 'echo <secret> >> /path/.env'"
REQUIRED    ssh nas 'sudo tee /path/.env >/dev/null' < ./.env
```

Ordering matters and is part of the rule — **create restrictive, then fill**,
never fill and then tighten:

1. `sudo install -d -m 0750 …/chat-gateway` and its subdirectories.
2. `sudo install -m 0600 /dev/null …/.env` — an **empty file, already 0600**.
3. Stream the content in over **stdin** with `sudo tee`, which does not change
   the existing mode.
4. Same three steps for the service-account key JSON, mode `0600`.

**Verify without printing.** Compare `sha256sum` on both ends and check
`stat -c '%a %U:%G'` — that proves the transfer and the mode without a byte of
secret material reaching any log, terminal or transcript. **Never `cat` the file
to check it landed.**

The registry (`config/registry.yaml`) holds env-var **names**, not values, so it
is not secret material — but it is gitignored and still travels the same way, at
`0640`.

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

⚠ **Step 5 as written is a 🛑 and must not be run by a Builder** — the plan's
standing rules and §4.3.1's table both say so, and this numbered list is the one
place in the arc that reads like an instruction to run it. **Request it, then
read the output.** ✅ **That is what happened: CG-55 requested it, the user ran it
on 2026-08-05, and its output was read and is clean** (`nas.md` §10 fact 5, which
also records what the deploy read *instead* while waiting — the same bytes from
the same source, via a read-only `app.config`).

#### Two prerequisites this row now depends on

> ⚠ **BOTH RESOLVED before the 2026-08-05 deploy, and neither the way this
> section expected — corrected 2026-08-05.** **(a)** was **deferred** by the user
> on 2026-08-03: still wanted, no longer gating. It was **not applied**, the
> deploy went ahead without it, and that is recorded as a fact of the run
> (`nas.md:654`). What fences the endpoint instead is the paired decision of the
> same day — **the published port binds the LAN address, not `0.0.0.0`** —
> demonstrated on the box rather than asserted (`nas.md:787`: `curl` against both
> loopback and the tailnet address is refused). ⚠ **The bind is a narrower
> guarantee than the ACL was**, and the residual §7 D2 states is unchanged: anyone
> on the home **LAN** still reaches `/healthz` unauthenticated. **(b)** was
> satisfied on 2026-08-03 and the fail-closed pre-flight **passed** on the box.
> Both decisions, their reasoning and the residual have one home:
> `docs/BUILDER_QUEUE.md` § CG-55, *"Two user decisions, 2026-08-03"*.

**(a) The homelab tailnet ACL must be applied first (D2).** The endpoint is
**fenced from the start, never fenced afterwards**. ⚠ This is **work in the
homelab repo that a chat-gateway Builder cannot perform** — it is an external
blocker on this row, not a task within it. It must be validated through
`network/tailscale-acl.hujson`'s `tests` block, which the Tailscale console
enforces on save, so the **other stacks'** reachability is machine-checked rather
than carefully read. **CG-60, CG-61, CG-53 and CG-54 can all proceed in
parallel with it** — only this row waits.

**(b) CG-61 must already be in the live registry (D1).** This row streams
`config/registry.yaml` to the box; if the opt-out is not in that file, the
deployed gateway runs with `allow_inbound: true` and the first drain writes
FamilyWorkspace content to disk. **Make it a fail-closed pre-flight, not a
memory test** — assert the expected opt-in map before transferring, and abort on
any mismatch:

```
for each configured space: apps_for_space(space) -> owners, and each owner's
allow_inbound must equal the expected map. Expected 2026-07-31:
  two spaces -> ['aitrader']        allow_inbound False
  one  space -> ['aiteam-harness']  allow_inbound False   <- CG-61
  one  space -> ['job-hunter']      allow_inbound True
Anything else: STOP. Do not transfer, do not deploy.
```

#### The sixth observation — the first drain

**The highest-value observation of the whole deploy.** The gateway has never
pulled while the app was in four spaces, so the first successful poll drains
**up to 24 hours** of accumulated backlog (the subscription's retention) from all
four at once. Record before and after:

| Observe | Why it is the interesting number |
|---|---|
| `events_seen` | the backlog's actual size — the first real measurement of this deployment's inbound volume |
| `suppressed_opt_out` | now pooled across **three** opted-out spaces (D1). Its magnitude is what D2's residual LAN exposure is judged against |
| `inbox.pending` / `inbox.dropped` | **`job-hunter` only** now. Non-zero `dropped` means the 1000-item cap was hit by the backlog |
| **which event types actually arrived** | §0.1.2's question. ⚠ **Now about `job-hunter` only** — D1 closed the FamilyWorkspace path, so this is no longer a privacy question about a family space, it is a capacity-and-shape question about the one open tenant |
| `interactions_without_action_id`, `unparseable_seen` | three of these spaces have never had a single event parsed from them |

⚠ **Do not record any space id, sender identity or message content** when writing
this up. Counts and app ids only — the same discipline `/healthz` itself follows,
and for the same reason.

**Merge gate: yes** — deploy + secret-handling path.

### 4.4 CG-56 — inbox delivery semantics ✅ approved (D3)

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

**APPROVED by the user (D3, §7).** The reason recorded there is decision A: polling
is jobhunt's only inbound path, so a read lost mid-processing is a lost Approve.
The blast radius is real and enumerable: `client.py:64`'s
`poll_inbox`, `README.md`'s endpoint table, `docs/integration-guide.md` §
*Inbound replies*, `docs/consumers/aitrader.md`'s comparison row (which cites
`service.py` line numbers), and the pinning test above.

Compatibility shape, if approved: keep clear-on-read as the default so no
existing caller breaks, and make ack-mode explicit and opt-in per request. The
alternative — flip the default — is cleaner but silently changes behaviour for
any caller that does not ack, turning a working consumer into an infinitely
growing queue. Given the gateway is about to become always-on, growing-forever is
the worse default.

**The declined branch is now moot** — it read *"if the user declines, CG-57
documents at-most-once explicitly."* D3 approved acks, so CG-57 documents
at-least-once with an explicit ack, and it is written once.

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
`SubscriberLoop`. This row is that run. ~~Depends on CG-55; the clock starts when
CG-55 lands.~~ ✅ **CG-55 landed 2026-08-05 (`4ddd6f5`) and the clock started with
it. Nothing blocks this row.**

⚠ **This section was written 2026-07-31, before eight PRs and the deploy, and it
has been REFRESHED — twelve drifts, on the CG-53/Part A precedent. The drift
audit lives in the plan (Part G §G0) and is not duplicated here.** Two of its
findings are corrections to *this section's own text* and are marked inline
below; the rest are against the plan's field lists and code citations.

#### The deployed-only finding: `/healthz` returns 200 while degraded

```
src/chat_gateway/service.py — the sole `return JSONResponse(...)` in the file,
inside the `@app.get("/healthz")` handler.  ⚠ This read `service.py:469-471`
until 2026-08-05; those lines are now `GET /v1/heartbeat/{source}`, a different
endpoint. Anchor on the decorator, never on a line number (CG-69: 8 of 14
line-anchored citations in the live contracts point at the wrong code).
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

> ⚠ **THE TILE EXISTS NOW, so this stopped being preventative on 2026-08-05.**
> Homelab **PR #21** adds a Homepage row for the gateway whose `siteMonitor` is
> `http://<LAN-IP>:8085/healthz` — **the plain form**, which answers **200 for
> every reason string this endpoint can produce**, including the *"subscriber …
> has never completed a poll"* text the box really emitted eight seconds after
> boot (`nas.md:665`). **The tile therefore reads green while inbound is dead** —
> the claude-mem failure reproduced at the dashboard, in this project, against the
> endpoint written to prevent it. ⚠ **Repointing the tile is a homelab-repo
> change and therefore a HANDOFF, not a task in this row** — but shipping
> `?strict=1` without it changes nothing an operator can see, which would retire
> the finding without fixing it. Both halves are named in plan Part G §G1 and in
> `nas.md` §9.

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
authority.

~~**§0.1 materially improves what this soak can prove, and the row should say so
rather than inherit the old caveat.** This spec first read *"a quiet subscription
running for three days proves the thread survives; it does not prove much about
behaviour under load."* **The subscription is no longer quiet** — four spaces feed
it, two of them generating suppression traffic and two enqueueing. The soak now
exercises the pull loop against **real, continuous, multi-space traffic**, which
is a materially stronger claim than a quiet loop staying alive.~~

~~It is still not a load *test*, and the sign-off request must say so rather than
smooth it: this measures the loop under **organic** traffic from four spaces over
days, not under deliberate pressure. That is exactly what the evidence reaches —
no more.~~

> ⚠ **FALSIFIED BY MEASUREMENT — struck 2026-08-05, and this is the most
> consequential correction in the refresh.** The first reading from the deployed
> box was **`events_seen: 0`, `unparseable_seen: 0`, `suppressed_opt_out: 0`,
> `suppressed_not_authorized: 0`**, across a sampled window with `poll_failures: 0`
> throughout (`docs/deploy/nas.md:759`). **The subscription was quiet.** The
> paragraph this replaces was a 2026-07-31 *prediction* written in the present
> tense, and it instructed the row to argue its sign-off on a premise the deploy
> disproved four days later.
>
> ⚠ **The original caveat it withdrew was RIGHT, and is hereby restored:** *a
> quiet subscription running for three days proves the thread survives; it proves
> little about behaviour under load.* Withdrawing a correct caveat on the strength
> of a prediction is a worse failure than never having written it, because the
> prediction reads as a measurement to everyone downstream.
>
> ⚠ **A second error, independent of the first and wrong on its own terms:**
> *"two of them generating suppression traffic and two enqueueing"* has been wrong
> since **D1** landed. Three spaces are opted out (one `aiteam-harness`, two
> `aitrader`) and **one** enqueues (`job-hunter`). The sentence describes a
> four-space split that has not existed since 2026-08-03.
>
> ⚠ **And `0` does not mean the spaces are silent** — the subscription's retention
> is 24 h and it was drained by an ad-hoc client on 2026-07-30, so `0` means
> *nothing was retained at this moment* (`nas.md:766`). **A soak measures the
> gateway, not the spaces**, and the pull loop is exercised either way because
> polling is unconditional.
>
> **What the soak can and cannot establish is now designed rather than asserted:
> plan Part G, §G2.5 (pass/fail, and how a quiet network differs from a wedge —
> quiet is a sawtooth, wedged is a ramp) and §G2.6 (the explicit
> can/cannot table).** Not restated here.

#### Also in scope

~~Disk growth. The audit JSONL files (`inbox-data/`, `state/deliveries/`) are
per-app-per-day and **never pruned** — fine on the dev box, a slow leak on a host
meant to run for years. The row reports measured growth per day and **proposes** a
retention rule.~~

~~**DECIDED (D5): measure first, set no window now, decide here with real
numbers.**~~ Two reasons, both recorded: with `aiteam-harness` closed (D1) only
`job-hunter` accumulates, so growth is likely modest — and **pruning by age
before knowing the volume is itself a way to silently lose the thing the trail
exists to prevent.** A retention policy on an audit trail whose entire purpose is
that *"nothing is ever silently lost"* has a rule-#5 flavour, which is why it
gets numbers before it gets a policy.

> ⚠ **OVERTAKEN BY CG-68 (2026-08-02) — corrected 2026-08-05.** *"Never pruned"*
> is false, and D5's *"decide here"* was decided three days before this row could
> reach it, under CG-68's own sign-offs A2/A3/A5. **The two directories now
> differ and the struck text collapsed them:** `inbox-data/` **is** pruned;
> `state/deliveries/` is unpruned **by decision** (ADR-0002 **D7**), as is
> `state/quarantine/`, which is what makes the sweep safe. **The window's numbers
> have one home — `retention.py`'s constants** — and are deliberately not copied
> here.
>
> **The reasoning above is left standing on purpose**: it is the argument CG-68
> went on to adopt, and it is why that row asked for sign-off rather than picking
> a number quietly. Only the *status* moved.
>
> **What survives for this row is CALIBRATION, not mechanism** — is 30 days right
> against real volume, and is `state/deliveries/` growing forever acceptable on a
> host meant to run for years, which **D7 decided on content grounds and never on
> size**. ⚠ **`files_deleted: 0` over a 72 h soak is the expected result and
> proves nothing about deletion** — the window is 30 days and the deployment is
> days old. Full treatment: plan Part G §G3′.

~~**Merge gate: no** for the `?strict=1` code; the observation half is
user-executed.~~
**Merge gate: no** for the `?strict=1` code. ⚠ **The observation half is
*Builder*-executed over SSH** — corrected 2026-08-05. *"User-executed"* predates
CG-55, which superseded that framing for the deploy itself and proved the
connection works unattended; a soak is `curl`-and-append, squarely ✅ *"read-only
probing, unattended"* on §4.3.1's own table. ⚠ **Any ledger change still needs
the user's explicit hard-rule-#3 sign-off** — that is unchanged and is a
different gate from who runs the script.

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

## 7. Decisions (user, 2026-07-31) — FINAL, do not re-litigate

All six open questions this spec raised are answered. Each is recorded with its
reasoning so the answer survives without the argument being had again.

### D1 · `aiteam-harness` (FamilyWorkspace) — set `allow_inbound: false`

**Decided: close it.** This spec's §0.1.2 finding, acted on.

**Reasoning.** Inbound was on **only because `true` is the default**
(`registry.py`: `allow_inbound=bool(spec.get("allow_inbound", True))`). That app
has no `callback_url`, no `allowed_users`, and `CLAUDE.md` describes it as a
`notify.py` **outbound** transport. **It never asked for inbound.** Hard rule #6
is default-deny in spirit; this makes it so in fact.

**The stated benefit is verified, not assumed.** `dispatch()` discards an
opted-out owner's event entirely — the `or [UNROUTED]` fallback cannot fire
because the space *has* an owner — so **nothing reaches the inbox, nothing
reaches `_unrouted`, nothing reaches disk.** Only the counter moves. FamilyWorkspace
content therefore never lands in a JSONL audit file.

**Reversible in one registry line** if aiteam ever wants inbound. This is a
default being corrected, **not a judgement about that consumer** — and the row
must say so in those words, or a future reader will mistake a default for a
verdict.

**Filed as its own row, CG-61 — see §4.0b for why it is not folded into CG-60.**

### D2 · `/healthz` exposure — land the drafted homelab ACL **before** CG-55

> ⚠ **SUPERSEDED 2026-08-03, and CG-55 shipped without it — recorded 2026-08-05.**
> The user **deferred** this ACL: still wanted, no longer gating the deploy. The
> decision below is kept as the record of D2 as taken on 2026-07-31, because the
> *reasoning* is unchanged and the residual it names is now the live posture.
> **What replaced the ACL as the fence is the paired decision of 2026-08-03: bind
> the published port to the LAN address rather than `0.0.0.0`.** It is stronger
> than the ACL on this one port — a tailnet peer cannot reach the socket whatever
> the policy says, demonstrated on the box (`nas.md:787`) — and **narrower**: it
> governs this port and nothing else on that host. ⚠ **The caveat three bullets
> down is now the operative statement of the residual, not a hypothetical**:
> anyone on the home LAN still reaches `/healthz` unauthenticated. One home for
> both halves: `docs/BUILDER_QUEUE.md` § CG-55, *"Two user decisions, 2026-08-03"*.
> ⚠ **`CLAUDE.md` carried the falsified version of this** — *"D2 responds by
> fencing `/healthz` behind the ACL **before** the first deploy"* — until CG-79
> corrected it. This heading is the sentence that spawned it.

**Decided: fence it from the start, not afterwards.** My re-priced
recommendation, taken.

Two constraints, both accepted, and one honest caveat this spec adds:

- **It is homelab-repo work.** A chat-gateway Builder cannot do it. It is
  therefore an **external prerequisite that blocks CG-55**, not a row in this
  queue — §4.3 records it as a dependency with a named owner.
- **It must not break tailnet reachability for the stacks already there** *(said
  "the ten stacks" until 2026-08-05; scope, not a count — see §0.2.2)*.
  The mechanism already exists: `network/tailscale-acl.hujson` carries a `tests`
  block the Tailscale console **enforces on save**. Extend that block to assert
  the existing services stay reachable for the owner's own devices. That is a
  machine-checked guarantee, not a careful read.
- ⚠ **The caveat: the ACL governs the TAILNET ONLY.** Anyone on the home **LAN**
  still reaches `:8085/healthz` unauthenticated. Saying "the ACL fixes the
  exposure" would over-claim, and this repo has corrected that shape repeatedly.
  The residual is LAN-local unauthenticated access to the counters; on a home LAN
  that is a reasonable place to land, but it is **stated, not glossed.**

**Reconciling the ACL with CG-55's first-drain observation — it does not "fall
out", it is a deliberate choice of vantage point.** Neither reader of `/healthz`
that matters is a tailnet peer:

| Reader | Path | Affected by the ACL? |
|---|---|---|
| CG-55's first-drain observation | `curl 127.0.0.1:8085/healthz` **on the NAS, over SSH** | **No** — loopback inside the box is not tailnet traffic |
| Homepage `siteMonitor` | the **LAN IP**, by homelab convention (that container has no Tailscale and cannot resolve `.ts.net`) | **No** |
| A tailnet peer | tailnet | **Yes — which is the point** |

**A partial mitigation D1 creates, worth recording because it is real but
incomplete.** With three of four spaces opted out, `suppressed_opt_out` **pools
three spaces' traffic into one integer**, so it no longer decomposes to aitrader
specifically. That genuinely reduces attributability — but an observer watching
*timing* across market hours can still infer. **Partial, not complete**, and it
is not a reason to skip the ACL.

### D3 · CG-56 — YES: ack-based at-least-once, opt-in per request

**Unblocked.** The published contract must keep working **unchanged** for any
caller that does not ask for acks.

**The user's reasoning, recorded:** decision A makes polling jobhunt's **only**
inbound path, so a read lost mid-processing is a **lost Approve**. That was
tolerable when the inbox was a fallback behind push. It is not now.

### D4 · Image — build on the box

**Decided.** No registry, no credentials, no external dependency in the deploy
path — consistent with a service whose whole design is not to be publicly
reachable.

Two consequences to record rather than discover: **the box needs the source**,
and **a rebuild is a manual step** (the runbook owns that procedure).

### D5 · Audit retention — measure first, decide at CG-59

> ⚠ **RESOLVED EARLIER AND ELSEWHERE — recorded 2026-08-05.** *"Decide at CG-59"*
> did not happen: **CG-68 decided it on 2026-08-02**, before CG-55 deployed and
> before CG-59 was unblocked, under its own user sign-offs (A2/A3/A5).
> `inbox-data/` is pruned on a time bound; `state/deliveries/` and
> `state/quarantine/` are not, **by decision**. **The reasoning below is what
> CG-68 adopted** — it is not superseded, it was acted on early — so it is kept
> intact and only the routing is corrected. What is left for CG-59 is
> **calibration against real volume**, not the policy: §4.7's *Also in scope* and
> plan Part G §G3′.

**Decided: set no window now.**

**Reasoning.** With `aiteam-harness` closed (D1), only `job-hunter` accumulates,
so growth is likely modest — and **pruning by age before knowing the volume is
itself a way to silently lose the thing the trail exists to prevent.** CG-59
proposes with real numbers.

### D6 · `mem_limit` — YES, set one

**Decided**, and recorded explicitly as a **deliberate deviation from local
convention: no existing custom app on that box sets one** (measured; the 4 GiB
caps on jellyfin, calibre, calibre-web and tailscale are TrueNAS's own, applied
to *catalog* apps).

**Reasoning.** An unbounded Python service on a **swapless** box is a neighbour
that takes others down, and **the OOM killer picks its own victim — possibly
claude-mem's Postgres.** CG-53 still verifies the renderer honours it; a limit
believed present but silently dropped is worse than none.

---

## 7.1 Still genuinely open — one item, and it is not blocking

**jobhunt's OD9** (§2.2). No action needed here: decision A stands on
topology-independence regardless of which host jobhunt lands on. Recorded so
that if OD9 is accepted, this spec's *stated reason* does not read as falsified.
Whether jobhunt's own contract doc records both reasons is jobhunt's call.

## 8. Merge gates

Per this queue's standing convention — IaC, deploy and secret-handling paths
pause and report before merging. **A row without a declared gate is not a
guarantee that none applies** (the CG-34 note); hard rule #2 territory pauses
regardless.

| Row | Gate | Why |
|---|---|---|
| CG-60 | ⏸ **yes** | consumer contracts, and it works in the ledger's neighbourhood |
| CG-61 | ⏸ **yes** | live-config change narrowing a tenant's inbound surface (hard rule #6 territory) |
| CG-53 | ⏸ **yes** | secret handling (`.env` on-box layout, SA key mount), IaC-adjacent |
| CG-54 | no | core code, no secrets, no Google surface |
| CG-55 | ⏸ **yes** | deploy + secret handling; **Builder-executed over SSH under §4.3.1**. ~~⚠ **Externally blocked on the homelab ACL (D2) and on CG-61 being in the live registry (D1)**~~ ✅ **Neither blocker survived to the deploy — corrected 2026-08-05.** D2 was **deferred** by the user 2026-08-03 (not satisfied — *removed as a gate*, and the deploy went ahead without it); D1's live-registry edit was **done** 2026-08-03 and the fail-closed pre-flight passed on the box. ⚠ **The two resolved by opposite mechanisms, and collapsing them into "unblocked" loses the difference that matters**: one prerequisite was met, the other was dropped, and only the first one leaves a guarantee behind. The gate itself was **released by the user and #66 merged 2026-08-05.** |
| CG-56 | no | published-contract change, **approved (D3)** — default path unchanged |
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
