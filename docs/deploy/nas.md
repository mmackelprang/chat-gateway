# Deploying chat-gateway to the NAS — runbook

**Status: PLANNED, not run.** Nothing in this document has been executed. §10
*Executed* is empty on purpose and is filled by the deploy row (CG-55); until it
carries entries, every command below is a plan.

---

## Why this file is here, and why that is a deviation

The runbook lives in **this** repo rather than the homelab one because this repo
can test its own claims — the loader property in §6, the mount arithmetic in §5
and the layout in §3 are all things the suite here checks and the homelab repo
cannot.

⚠ **Say the rest plainly rather than claim a convention:** owning it here is a
**deliberate deviation** from the homelab repo's house style, not a pattern
being followed. Measured 2026-08-03 — all ten of that repo's `nas/services/*.md`
keep operational detail **inline**, and every link in that directory is
intra-repo and relative. **No `nas/services/*.md` links out to another repo.** A
homelab doc pointing here is a **new pattern there**. The nearest precedent is
not even under `nas/`: `appserver/services/familyworkspace.md` scopes itself to
infra-and-deploy while still writing every deploy command out inline.

The homelab-side artifact is therefore a **four-header**
`nas/services/chat-gateway.md` carrying the inline minimum its siblings do and
pointing here for the rest. **Writing it is not this repo's work** — see §9.

### Public-repo discipline

This repository is public. Every command below carries **paths and env-var
NAMES only**: no host, no user, no key path, no IP, no port-forwarding address,
no credential value. `<nas>` below stands for the SSH destination — the host and
user pair, and the key that reaches it, are recorded in the homelab repo at
**`nas/scripts/lib/common.sh`**, which is the one source for them. Substitute
your own configured destination when running these.

---

## §1 · What this is — the tenth stack

The gateway becomes an additional app stack on a box that is already busy. ⚠
**This is not a role change for that machine.** An earlier draft of this plan
called the NAS a *backup target only*; that came from another project's
pipeline-scoped table and is **withdrawn**.

Measured 2026-07-31: the box already runs **10 app stacks / 15 containers**
(beszel ×2, calibre, calibre-web, claude-mem ×5 including its Postgres, czkawka,
homepage, jellyfin, pihole, tailscale, upsnap), all named `ix-<app>-<service>-1`.

Capacity, measured the same day: **20.8 GB RAM available of 31.9 GB**, load
**0.29** across 16 cores, `datapool` at **1% of 13 TB**. A small Python service
is noise against that.

⚠ **The box has ZERO swap.** A memory spike is not a slowdown there, it is an OOM
kill — on a host running someone else's Postgres. The blast-radius controls this
runbook applies, all of them deliberate:

- a **memory limit** (§5) — a deviation from local convention, and §5 says why;
- published port **8085**, measured free (in use at the time of measurement:
  `22 53 80 139 443 445 3000 5357 5800 6000 6999 8081 8090 8098 30013 30014
  31067 32014 32015 32016 37877 41175 62716`);
- **no `network_mode: host`**;
- no added capabilities;
- mounts confined to one app directory;
- **no change to any existing app.**

---

## §2 · Prerequisites

- The TrueNAS **Apps pool is initialized**.
- SSH to the box works unattended (`BatchMode`, passwordless sudo — verified
  2026-07-31). **Host, user and key values are not written here**; their one
  source is `nas/scripts/lib/common.sh` in the homelab repo.
- `docs/google-cloud-setup.md` is **completed**, and the live service-account key
  is present on the dev box. The filename is recorded there, not here — CG-51
  made the setup scripts derive it from `PROJECT_ID`, and a filename pinned in a
  second place is exactly what CG-19 found stale.
- The registry the box will run is the **live** `config/registry.yaml`, which is
  gitignored. It is not `config/registry.example.yaml`; the two differ and that
  difference has caught three people.

**Re-run the fail-closed app-name check before anything else.** It must return
`[]`:

```bash
ssh <nas> "sudo midclt call app.query '[[\"name\",\"=\",\"chat-gateway\"]]'"
# MUST be []. Anything else -> STOP and report. It was [] as of 2026-07-31, but
# this arc has already been wrong twice about what is on that box.
```

⚠ **A stop means stop and report — never work around.** If the app cannot be
created without touching another stack, Docker's global state, or a pool
operation outside the gateway's own path, that is a finding for the user, not an
obstacle to route around.

---

## §3 · On-box layout

**Create restrictive first, then copy in.** Never copy into a world-readable
directory and tighten afterwards — `tee` does not change an existing file's mode,
which is the whole reason the `install` step exists separately below.

```bash
ssh <nas> 'sudo install -d -m 0750 /mnt/datapool/apps/chat-gateway/{config,secrets,state,inbox-data}'
```

The tree the running gateway expects, measured against `__main__.build_runtime`:

```
/mnt/datapool/apps/chat-gateway/
├── .env                      0600  every secret; never in git, never in compose
├── config/registry.yaml      0640  env-var NAMES only (rule #2)
├── secrets/<sa-key>.json     0600  mounted read-only; filename per google-cloud-setup.md
├── state/                    0750  (rw)  CHAT_GATEWAY_STATE_DIR
│   ├── heartbeats.json             dead-man checks — no message content
│   ├── deliveries/                 per-source delivery log
│   ├── queue/delivery.jsonl        outbound journal   ⚠ TENANT BODIES
│   ├── queue/inbox.jsonl           inbound journal    ⚠ TENANT BODIES
│   └── quarantine/                 unrevivable-*      ⚠ TENANT BODIES — NEVER PRUNED
└── inbox-data/               0750  (rw)  CHAT_GATEWAY_INBOX_DIR
    └── <app>-<date>.jsonl          per-app audit      ⚠ TENANT BODIES — swept on a timer
```

**Three facts to take from that, not a diagram:**

1. **Four locations hold tenant message bodies**, not one:
   `state/queue/delivery.jsonl`, `state/queue/inbox.jsonl`, `state/quarantine/`
   and `inbox-data/`. Anyone sizing a backup, writing a snapshot policy or
   answering a support request needs all four.
2. **Only `inbox-data/` is ever swept.** `state/quarantine/` is **never** pruned
   — that is what makes the sweep safe to run at all — and `state/deliveries/` is
   untouched by decision. Both are enforced **in code**, not by where two env
   vars happen to point: the sweeper **refuses to boot** if its directory
   overlaps the state dir, and skips the quarantine by name even then. So an
   operator who "tidies up" by pointing `CHAT_GATEWAY_INBOX_DIR` at a state
   subdirectory gets a **refusal to start**, not a silent deletion. Expect it —
   that refusal looks like a bug at 2am and is not one.
3. **The retention window is not written here.** Its one home is `retention.py`'s
   constants, quoted to consumers in `docs/integration-guide.md`. What this
   runbook names is the **env var** — `CHAT_GATEWAY_INBOX_RETENTION_DAYS` — and
   the one operational fact about it: **`0` disables pruning entirely.** Do not
   copy the number here; a duplicated moving number is this repo's own
   most-repeated lesson.

Reasoning and measurements for all of the above: **ADR-0002**
([`../architecture/decisions/2026-07-31-journalled-message-bodies.md`](../architecture/decisions/2026-07-31-journalled-message-bodies.md)).
Not restated.

### The historical-mode sweep

Files this project writes are created `0600` by the code that writes them, and
the append sites self-heal **today's** date-sharded file. Nothing reopens
yesterday's. So a `0644` day-file from three days ago is never corrected by the
code, and sits there until the sweeper deletes it — or **forever**, where
`CHAT_GATEWAY_INBOX_RETENTION_DAYS=0`. Run this **once after creating the
directories**, and again after any restore from a backup that predates CG-65:

```bash
# Historical day-files only. The in-code fix self-heals today's; nothing
# reopens yesterday's.
ssh <nas> 'sudo find /mnt/datapool/apps/chat-gateway/state /mnt/datapool/apps/chat-gateway/inbox-data \
  -type f ! -perm 600 -exec chmod 0600 {} +'
ssh <nas> 'sudo find /mnt/datapool/apps/chat-gateway/state /mnt/datapool/apps/chat-gateway/inbox-data \
  -type f ! -perm 600 -print'   # MUST print nothing
```

⚠ **This does NOT close CG-70, and must not be read as though it does.** That row
stays **open** for the `src/` half — an in-code stat-and-chmod at the four append
sites — which is deliberately not folded into this merge-gated secret-handling
change. The two cover **disjoint sets**: the code half only ever reopens today's
file, this sweep only ever fixes what already exists.

⚠ **And today it fixes nothing, because nothing exists.** The gateway has never
been deployed, so no such file exists anywhere. The line above is
**prophylactic** — it earns its place at the moment of the first restore, not
now.

---

## §4 · Build the image on the box

✅ **Decided (D4): build locally, no registry.** No registry, no credentials, no
external dependency in the deploy path. §9 keeps the registry alternative as the
upgrade path if the middleware refuses a locally-built image.

**Getting the source there.** `git clone` this **public** repo at a **pinned
commit** is the auditable form: it records exactly what was built and carries no
secret.

```bash
ssh <nas> 'sudo git clone <this-repo-url> /mnt/datapool/apps/chat-gateway/src'
ssh <nas> 'cd /mnt/datapool/apps/chat-gateway/src && sudo git checkout <pinned-commit>'
ssh <nas> 'cd /mnt/datapool/apps/chat-gateway/src && sudo docker build -t chat-gateway:local .'
```

**Fallback if the box lacks egress:** stream a tarball over stdin — the same
no-argv transport the secret rules require, though source is not secret:

```bash
git archive --format=tar <pinned-commit> | ssh <nas> 'sudo tar -x -C /mnt/datapool/apps/chat-gateway/src'
```

The image is tagged **locally only**; `pull_policy: missing` in §5 means it is
never pulled.

⚠ **A rebuild is a MANUAL step.** There is no CI to this box and none is wanted.
The upgrade procedure is therefore part of this runbook rather than an
improvisation at the time:

1. re-clone (or re-archive) at the **new pinned commit**;
2. `sudo docker build -t chat-gateway:local .`;
3. `sudo midclt call app.redeploy chat-gateway`.

State directories are untouched by a rebuild; both queues replay at boot (§8).

---

## §5 · The compose document

A TrueNAS **custom app**: the document below is submitted as
`custom_compose_config`, and it carries **paths only** — every secret is in the
file `CHAT_GATEWAY_ENV_FILE` names, which is why §7's capture is clean by
construction rather than by trusting someone else's redactor.

```json
{"services": {"chat-gateway": {
  "environment": {
    "TZ": "America/Denver",
    "CHAT_GATEWAY_ENV_FILE": "/env/gateway.env",
    "CHAT_GATEWAY_REGISTRY": "/config/registry.yaml",
    "CHAT_GATEWAY_STATE_DIR": "/data/state",
    "CHAT_GATEWAY_INBOX_DIR": "/data/inbox",
    "GATEWAY_ENABLE_PUBSUB": "1"
  },
  "image": "chat-gateway:local",
  "mem_limit": "512m",
  "ports": ["8085:8085"],
  "pull_policy": "missing",
  "restart": "unless-stopped",
  "volumes": [
    "/mnt/datapool/apps/chat-gateway/.env:/env/gateway.env:ro",
    "/mnt/datapool/apps/chat-gateway/config:/config:ro",
    "/mnt/datapool/apps/chat-gateway/secrets:/secrets:ro",
    "/mnt/datapool/apps/chat-gateway/state:/data/state",
    "/mnt/datapool/apps/chat-gateway/inbox-data:/data/inbox"
  ]}}}
```

⚠ **Nothing nests, and that is the correction.** An earlier draft of this block
**could not have booted.** It mounted the config *directory* at `/config` while
`.env` sat inside it, and set `CHAT_GATEWAY_REGISTRY: /config/registry.yaml` —
which resolved to `/config/config/registry.yaml` on the box, i.e. a
`RegistryError` and **exit 2**. The fix is `.env` on its **own** mount point, so
every env value maps to exactly one mount — rather than deepening the registry
path, which resolves but reads like a typo and invites the next person to "fix"
it back.

⚠ **`"ports": ["8085:8085"]` is left in the `0.0.0.0` form ON PURPOSE.** Changing
it to the LAN-address form is **CG-55's** job, recorded in that row. Do not
change it here, and do not read the surviving `0.0.0.0` as endorsement — §8 says
what it costs.

⚠ **Where this JSON lives, for whoever is looking for it.** The deploy row's own
notes say *"the custom-app JSON **below**"*. It is **above** — here, in the
artifacts row (CG-53), not in the deploy row. Recorded so nobody searches the
wrong document.

**`GATEWAY_ENABLE_PUBSUB: "1"` is new here, and it is a fail-closed lever, not a
convenience.** It is declared in the **compose** — where it is non-secret and
captured — precisely so a stale `.env` cannot leave inbound silently **off**.
With the flag on, a missing `CHAT_GATEWAY_PUBSUB_SUBSCRIPTION` or
`GOOGLE_APPLICATION_CREDENTIALS` raises `RegistryError` and the process exits 2,
naming the fault. Without it, the copied dev-box default `0` wins by the loader's
own *environment wins* rule and the gateway boots **healthy with no subscriber at
all** — the exact shape hard rule #5 exists to prevent. See §6.

**House style, matched:** `restart: unless-stopped`, `pull_policy: missing`, `TZ`
set, bind mounts under `/mnt/datapool/apps/<app>/`, **no** `container_name`
(TrueNAS names it `ix-chat-gateway-chat-gateway-1`), **no** `labels`, **no**
`env_file`, **no** `logging`.

✅ **`mem_limit` — decided (D6): set one.** Recorded explicitly as a **deliberate
deviation from local convention: no existing *custom* app on that box sets one**
(measured; the 4 GiB caps on jellyfin, calibre, calibre-web and tailscale are
TrueNAS's own, on *catalog* apps). The reason is §1's: an unbounded Python
service on a **swapless** box is a neighbour that takes others down, and **the
OOM killer picks its own victim — possibly claude-mem's Postgres.**

⚠ **Three things to verify on the box rather than assume**, recorded here as
decision points so they are not discovered live:

1. that the middleware accepts a compose referencing a **locally-built** image
   with `pull_policy: missing`. Every existing custom app there pulls a public
   image, so this is first-of-its-kind on that box. If rejected → §9's registry
   path.
2. that `CHAT_GATEWAY_REGISTRY` resolves **in the container** — the correction
   above is reasoned from the mount list, and the boot is what proves it.
3. **that the renderer honours `mem_limit` in a custom app.** If it is silently
   dropped, **say so** — a limit believed present but absent is worse than no
   limit at all, because it is the one that stops anybody looking.

---

## §6 · Secrets onto the box

**Secret material goes over stdin or by file copy — NEVER as a command-line
argument.** An argument lands in local shell history, remote shell history, and
`ps` output on a box other people's software runs on. `sudo` logs the command it
ran, not what was piped into it.

```bash
# FORBIDDEN — the value is in argv, and therefore in history and in ps
ssh <nas> "echo '<secret>' > /mnt/datapool/apps/chat-gateway/.env"

# REQUIRED — create restrictive FIRST, then stream content over stdin
ssh <nas> 'sudo install -m 0600 /dev/null /mnt/datapool/apps/chat-gateway/.env'
ssh <nas> 'sudo tee /mnt/datapool/apps/chat-gateway/.env >/dev/null' < ./.env

# same shape for the service-account key (filename per docs/google-cloud-setup.md)
ssh <nas> 'sudo install -m 0600 /dev/null /mnt/datapool/apps/chat-gateway/secrets/<sa-key>.json'
ssh <nas> 'sudo tee /mnt/datapool/apps/chat-gateway/secrets/<sa-key>.json >/dev/null' < ./iac/<sa-key>.json

# the registry holds env-var NAMES, not values — not secret, same transport, 0640
ssh <nas> 'sudo install -m 0640 /dev/null /mnt/datapool/apps/chat-gateway/config/registry.yaml'
ssh <nas> 'sudo tee /mnt/datapool/apps/chat-gateway/config/registry.yaml >/dev/null' < ./config/registry.yaml
```

**Verify without printing:**

```bash
ssh <nas> 'sudo sha256sum /mnt/datapool/apps/chat-gateway/.env' | cut -d" " -f1
sha256sum ./.env | cut -d" " -f1            # compare by eye; equal == landed intact
ssh <nas> 'sudo stat -c "%a %U:%G %n" /mnt/datapool/apps/chat-gateway/.env'
```

⚠ **Never `cat` these files to check them.** A hash proves the transfer and
`stat` proves the mode, with no secret byte reaching a terminal, a log, or a
transcript.

### The dev box's `.env` is NOT usable verbatim

An earlier draft said *"copy `.env`"* as though it were. *Environment wins* makes
the compose authoritative for the three path vars it sets, so the copied dev
values for `CHAT_GATEWAY_REGISTRY`, `CHAT_GATEWAY_STATE_DIR` and
`CHAT_GATEWAY_INBOX_DIR` are harmlessly overridden. **Three keys' dev-box values
are WRONG on the box and are NOT overridden:**

| Key | Dev-box value | Must be, on the box | If not corrected |
|---|---|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | a dev-relative path | `/secrets/<sa-key>.json` | ⚠ **boots clean, fails at every tier-2 call** |
| `GATEWAY_ENABLE_PUBSUB` | `0` in `.env.example` | `1` | inbound silently off — now caught by §5's compose flag |
| `CHAT_GATEWAY_INTERACTION_ROUTING_TARGET` | empty in `.env.example` | any constant (classic — ADR-0001 D3) | ⚠ **`/healthz` DEGRADES**: with tier 2 on, card interactions are impossible, not merely unconfigured (CG-7) |

⚠ **The sentence above used to read *"Two keys are not in the compose"*, and
that was a miscount — measured 2026-08-03, **thirteen** of `.env.example`'s
eighteen keys are absent from §5's `environment:` block** (it sets five of them,
plus `TZ`). Every API key and every webhook URL is in that thirteen, and being
absent is the *point* — that is the whole reason `CHAT_GATEWAY_ENV_FILE` exists.
So "not in the compose" was never the property worth listing. The claim is now
scoped to the one that is: **not overridden, and wrong here**. The old sentence
was wrong twice over — the count it stated is thirteen, and the narrower count
it *meant* is three, because recounting is what turned up the third row.

That row is verified against the code, not inferred from the comment in
`.env.example`: `service.py`'s `/healthz` appends a `reasons` entry — and
therefore returns `status: degraded` — whenever `subscriber.enabled` is true and
`CHAT_GATEWAY_INTERACTION_ROUTING_TARGET` is unset, and `/v1/identities` reports
`interaction.enabled: false` to every producer in the same state. §5's compose
sets `GATEWAY_ENABLE_PUBSUB: "1"`, so **that condition is true on this box by
construction** — leave the key empty and the first `/healthz` after boot is
`degraded`.

⚠ **Not fixed here, and worth knowing before you follow the machine's advice:**
that `/healthz` reason text tells the operator to set the variable to the
Pub/Sub **topic path**. That is the **add-ons-era** answer; production has been
classic since 2026-07-29, where the correct value is any constant (ADR-0001 D3,
and the dated table in `.env.example`). A topic path is harmless-but-costly on
classic — it consumes the native action-identity slot, which is what forces
identity into `__cg_action__`. Set the constant, not the topic path.

**The first one is the dangerous one, and it is silent by construction.**
`GoogleServiceAccountTokens.__init__` only *stores* the path — the key file is
not opened until the first token mint. So a wrong path produces a gateway that
starts, builds the Chat API adapter, and reports it present; **`/healthz` does
not check that the file exists** (`registry.health()` reports identity env-var
resolution and per-app key configuration, and no code path stats the credential
file). It looks alive and cannot talk to Google.

That is this row's own loader property #3 one level up, so it is closed the same
way — with an explicit check rather than a reminder:

```bash
# after transferring .env, BEFORE app.create — proves the path resolves IN the
# container, without printing a single byte of the file
ssh <nas> 'sudo docker run --rm --env-file /mnt/datapool/apps/chat-gateway/.env \
  -v /mnt/datapool/apps/chat-gateway/secrets:/secrets:ro \
  chat-gateway:local sh -c "test -r \"\$GOOGLE_APPLICATION_CREDENTIALS\" \
  && echo CREDS-OK || echo CREDS-MISSING"'
```

`CREDS-MISSING` is a **stop**. Fix the path in `.env`, re-transfer, re-check.
Keep the table above up to date as the record of what differs, so the next
transfer is a diff rather than a rediscovery.

### Register the secrets in the homelab repo

`SECRETS.template.md` is the **tracked** file (`.gitignore` carries the
`!SECRETS.template.md` negation); `SECRETS.md` is gitignored and holds real
values. Rows are three columns — `| Secret | Where it lives on the box | How to
regenerate / rotate |` — and the model to copy is the existing Chroma row, which
names the **env var and the service** rather than a value. Two rows, structure
only:

- **the per-app API keys** — regenerate with `python3 -m chat_gateway mint-key`,
  then update the consumer.
- **the tier-1 webhook URLs** — ⚠ **no rotate-in-place exists.** Recovery is
  delete-and-recreate by hand, per `docs/google-cloud-setup.md` §8a. Say so in
  the rotate column: this project burned every webhook it owns once, on
  2026-07-29, and each one had to be recreated through the console.

Writing those rows is a homelab-repo change — see §9.

---

## §7 · Verify — the gate

Bring the app up:

```bash
ssh <nas> 'sudo midclt call app.create <the JSON from §5, over stdin>'
ssh <nas> 'sudo docker logs ix-chat-gateway-chat-gateway-1 --tail 50'
```

The boot lines to look for, in order: the env-file **count** (`env: loaded N
key(s) from /env/gateway.env` — a count, never a value), the queue replay line,
and the retention line.

### The capture gate

⚠ **Do NOT run `capture.sh` yourself.** It rewrites `nas/compose/*.json` for
**all ten** stacks — a cross-repo write owned by whoever holds that working tree.
**Request the run; then read what it produced.** A stop means stop.

The file to read is **`nas/compose/chat-gateway.config.json`**. The pattern is
`nas/compose/<app-name>.config.json`, and the app set is derived live from
`app.query` filtered on `custom_app`, so **this file appears automatically on the
first capture after the app exists.** Nobody opts in — which is exactly what
makes the leak this design prevents a **default** rather than a mistake.

It must contain **zero** secret values.

⚠ **Do not trust the `clean. safe to commit.` console line.** Re-measured
2026-08-03 end to end through that repo's real redactor and real scan gate: a
payload carrying a live-shaped `CHAT_GATEWAY_API_KEY__*` and a
`GOOGLE_CHAT_WEBHOOK_URL__*` came back **with both values intact** and the scan
**exited 0**. A `POSTGRES_PASSWORD` in the same payload *was* redacted — which is
precisely what makes the green gate persuasive and useless here. **Grep the
captured file** for the redaction marker and for this project's own key prefixes
rather than reading the console line.

**Cross-repo note, not our change:** if the homelab repo ever wants defence in
depth, a `*_API_KEY__*` / `*_WEBHOOK_URL__*` substring rule is the shape that
would catch these. ⚠ **Note the second-order risk before proposing it there:**
that repo's `lib/restore.sh --strip-redacted` **drops every marker-valued key
from a deploy payload**, so a false positive silently deletes real config on
restore — which is why its suffix list is anchored and conservative. This
design does not need that rule, and must not be justified by it.

---

## §8 · Gotchas

- **Tailnet reachability would be FREE on this box — and the deploy declines it
  on purpose.** Measured 2026-07-31: the tailscale container runs
  `network_mode: host` with `/dev/net/tun`, `CAP_NET_ADMIN` and
  `TS_USERSPACE=false`, so `tailscale0` is a **real host interface** and a port
  on `0.0.0.0` is tailnet-reachable with **no** subnet router, userspace proxy,
  sidecar, `serve` or `funnel`. That is exactly **why binding `0.0.0.0` is the
  thing not to do**: it publishes on every interface the host has, including that
  one. The deploy binds the **LAN address** instead. Reasoning and residual have
  one home — `../BUILDER_QUEUE.md` § CG-55, *"Two user decisions, 2026-08-03"*.
  ⚠ **Record the dependency anyway**, because it governs any future decision to
  re-expose: if that app is switched to userspace mode or off host networking,
  `tailscale0` vanishes from the host and every service's tailnet reachability
  goes silently with it — nothing in the gateway's own config shows it.
- **`tailscale` is NOT on the host PATH.** Any tailnet inspection means
  `docker exec` into another stack's container, which is a **STOP**, not a
  workaround.
- **`/healthz` is UNAUTHENTICATED by design** — and since 2026-07-31 that matters
  more than app-id enumeration. With the Chat app live in both Ai Trader spaces
  and `allow_inbound: false`, a suppression counter increments once per event
  there, making the endpoint a live **activity meter** for another tenant's
  private spaces: volume and timing, no content and no attribution. Hard rule #6
  is working — nothing crosses. Per-app API keys (rule #4) protect `/v1/*` and
  nothing else.
  ⚠ **DO NOT ENUMERATE `/healthz`'s FIELDS HERE.** What it exposes is durability
  and liveness counters, plus which of them degrade `status`. The field-by-field
  table has exactly **one** home:
  [`docs/integration-guide.md` § *Durability counters at `/healthz`*](../integration-guide.md#durability-counters-at-healthz).
  That table's own counts have been wrong **five** times, and it changed again on
  2026-08-03 (CG-76 added degrade inputs and new fields). A list copied here is a
  list that is wrong on somebody else's schedule — the two-homes-for-a-moving-fact
  trap `CLAUDE.md` opens with.
- ⚠ **The tailnet ACL (D2) is DEFERRED, not applied.** An earlier draft said it
  *"lands BEFORE this is deployed, so the endpoint is fenced from the start."*
  **That is no longer true.** The user deferred it on 2026-08-03: still wanted,
  **no longer gating the deploy**, and no external homelab prerequisite remains.
  **The LAN bind is what replaces it**, and the two are one decision in two
  halves — neither reads correctly alone. One home for both:
  `../BUILDER_QUEUE.md` § CG-55.
  ⚠ **The bind does not make the ACL unnecessary.** It removes tailnet reach **to
  this port** and says nothing about the rest of that box or the rest of the
  tailnet; the live policy is still default allow-all (recorded 2026-07-28).
  **Accepted residual, stated rather than glossed: anyone on the home LAN still
  reaches `/healthz` unauthenticated.** §10 records whether the ACL was applied
  at deploy time, so the posture is a fact there rather than an assumption here.
- ⚠ **A config error under `restart: unless-stopped` is a CRASH LOOP, and that is
  the intended behaviour — read it that way or it reads as a bug.** A missing or
  unreadable `CHAT_GATEWAY_ENV_FILE`, a bad registry path, or a retention/state
  directory overlap all exit **2** with `config error: …` on **stderr**, and
  TrueNAS restarts the container. The operator sees a restarting app, and **the
  reason is in `docker logs`, not in `/healthz` — there is no `/healthz` to
  read, which is the entire point.** A gateway that booted without credentials
  would answer `degraded` on an unauthenticated endpoint and otherwise look
  alive; refusing to start names the fault while it can still be fixed.
  **It costs nothing:** the process dies before the dispatcher exists, so a crash
  loop generates **no** Google traffic. First diagnostic is the logs, not the
  endpoint.
- **Zero swap.** An unbounded container OOM-kills a neighbour, and one neighbour
  is claude-mem's Postgres. See `mem_limit` in §5.
- **No public ingress is needed or wanted.** Pub/Sub is an outbound **pull**.
  Never put this behind the public reverse proxy.
- **`iac/chat-gateway-sa.json` is DEAD.** It belongs to the deleted
  `chat-gateway-prod` project. Do not authenticate with it, and do not treat its
  presence in the repo as configuration.
- **Restarting drops nothing.** Both queues are durable and are replayed at boot
  **with the attempt count preserved** — which is what stops a crash loop from
  resetting the backoff ladder every boot and hammering Google. The replay rule
  and its edge cases have one home each: `delivery.py`'s docstring and
  `journal.py`'s. Link; do not restate.

---

## §9 · Alternatives, rollback, and the homelab-side handoff

### Alternative: a registry image

If the middleware refuses a compose referencing a locally-built image (§5,
verification point 1), push `chat-gateway:<tag>` to a registry the box can reach
and drop `pull_policy: missing`. That reintroduces a credential and an external
dependency into the deploy path, which is why D4 chose the local build; it is
kept as the **upgrade path**, not the default.

### Rollback

```bash
ssh <nas> 'sudo midclt call app.delete chat-gateway'
```

⚠ **What that does NOT undo.** The bind-mounted directories persist —
**deliberately**, and per §3 **four of them hold tenant message bodies**. *"Delete
the app"* is not *"delete the data"*. Removing the data is a separate, explicit
act against `/mnt/datapool/apps/chat-gateway/`, and it destroys the quarantine —
which is the only copy of replies the gateway was holding when it dropped them.

Rolling **back a version** is §4's upgrade procedure with an older pinned commit:
re-clone, rebuild, `app.redeploy`. There is no image history to roll back to,
because there is no registry.

### Artifacts this repo CANNOT create — a handoff, not an omission

These live in the **homelab repo**. A chat-gateway change must not write them,
so they are named here for the user to pick up:

| Artifact | Shape |
|---|---|
| `nas/services/chat-gateway.md` | **four headers only**, per `nas/services/_TEMPLATE.md`: `## Overview (User)`, `## Deployment (Ops)`, `## Reinstall / Recovery`, `## Gotchas`. No extra headers, no `###`. Carries the inline minimum its siblings do and links here for the rest — ⚠ which is a **new pattern** in that directory (see the deviation note at the top of this file) |
| a `SECRETS.template.md` row | two rows per §6 — per-app API keys, tier-1 webhook URLs — three columns, naming the **env var and the service**, never a value |
| `nas/scripts/restore-chat-gateway.sh` | the five-line wrapper form its four siblings use over `lib/restore.sh` |
| `nas/DASHBOARDS.md` + Homepage tile | the service registration its siblings all carry |

---

## §10 · Executed

**Empty. Nothing here has been run.**

This section is filled by the deploy row (CG-55) — one dated entry per step
actually executed, including whether the tailnet ACL (§8) was applied at deploy
time. Until it has entries, everything above is **planned**, and a reader can
tell the two apart by looking here rather than by guessing.

| Date | Step | Result | Notes |
|---|---|---|---|
| _(none yet)_ | | | |
