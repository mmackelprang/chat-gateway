# Deploying chat-gateway to the NAS — runbook

**Status: EXECUTED 2026-08-05 (CG-55).** This header read *"PLANNED, not run.
Nothing in this document has been executed"* until then, and the sentence is
quoted rather than deleted because the distinction it drew is the useful one: a
reader tells plan from fact by looking at **§10**, not by guessing. §10 now
carries entries, so the commands above are a record — **with the deviations §10
names.** Nothing here is retroactively true; §10 says what actually ran.

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

## §1 · What this is — the ELEVENTH stack

> ⚠ **This heading said *"the tenth stack"* until 2026-08-05 (CG-79), and the
> section's own body — three lines below — has always disagreed with it.**
> 10 stacks were already running; the gateway is therefore the **eleventh**, and
> the live `app.query` on the box (captured 2026-08-05) lists **11 apps**, which
> settles it by measurement rather than by arithmetic.
>
> **This is not a claim that went stale — it was wrong the day it was written**,
> which makes it a different and worse kind of error than the rest of what CG-79
> corrected. In CG-69's taxonomy it is **category (b), wrong when written**, not
> **(a), falsified by a later change**; §8 of that spec says plainly that no guard
> in this repo can reach category (b).
>
> **Why it survived is the part worth keeping.** The wrong number sat in a
> **heading** and the right one in the **body**, and nobody reads a heading and a
> paragraph as two claims about the same fact — the heading reads as a title, the
> paragraph as data. It then **propagated by quotation**, out of this file and
> into a briefing, before being caught independently by the agent writing the
> homelab-side artifacts. A self-contradicting section is more interesting than a
> typo: the correct value was sitting three lines away the entire time.

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

⚠ **And on the first run it fixed nothing — but the reason changed on
2026-08-05, so the sentence did too.** This read *"The gateway has never been
deployed, so no such file exists anywhere"*; that was true when written and was
**falsified by §10**, which is exactly the stale-second-copy trap this repo keeps
recording. What is true now: the sweep **was** run immediately after creating the
directories (§10), and it printed nothing — because the gateway's own writers
create every file `0600`, and because no file was yet old enough to be
*historical*. It stays **prophylactic**: it earns its place at the first restore
from a pre-CG-65 backup, not on a fresh deploy.

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
    "GATEWAY_ENABLE_PUBSUB": "1",
    "GATEWAY_ENABLE_MCP": "1"
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

**`GATEWAY_ENABLE_MCP: "1"` (CG-80) sits in the compose for the same reason its
sibling does:** it is **non-secret and captured**, so a stale `.env` cannot leave
the surface silently in the wrong state. It differs in one way worth naming — it
has **no companion credential**, so there is nothing for it to fail closed on and
no startup check to add. Adding it changes **nothing** about the secret set: no
new `.env` key, no new stdin transport, and **no new `SECRETS.template.md` row**
(§6's three-row set is unchanged). ⚠ **The flag arms the endpoint; it does not
give it a caller.** `POST /mcp` authenticates with an ordinary per-app key, and
the `agent-mcp` tenant exists only in `registry.example.yaml` — the live
`config/registry.yaml` is gitignored, so minting the key and writing that entry
is an operator action this or any PR cannot perform.

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
names the **env var and the service** rather than a value. **THREE rows**,
structure only:

- **the per-app API keys** — regenerate with `python3 -m chat_gateway mint-key`,
  then update the consumer.
- **the tier-1 webhook URLs** — ⚠ **no rotate-in-place exists.** Recovery is
  delete-and-recreate by hand, per `docs/google-cloud-setup.md` §8a. Say so in
  the rotate column: this project burned every webhook it owns once, on
  2026-07-29, and each one had to be recreated through the console.
- **the Google service-account key JSON** — the credential `GOOGLE_APPLICATION_CREDENTIALS`
  points at, under `secrets/` (mode `600`, mounted read-only at `/secrets`).
  Rotate by `gcloud iam service-accounts keys delete <KEY_ID> --iam-account=…`,
  re-run the setup script, copy the new JSON over **stdin** into a pre-created
  `install -m 0600` target, redeploy — then **re-run the `CREDS-OK` check below**,
  because that is the step that catches a wrong path.
  ⚠ **Do not write the key's FILENAME into that row.** It varies by project, and
  one historical value of it names a **dead** key from the deleted
  `chat-gateway-prod`. Its one home is `docs/google-cloud-setup.md`; a second copy
  is the drift that made the warning necessary. Point at the directory and the doc.

⚠ **This section specified TWO rows until 2026-08-05, and the two-row spec was
the defect.** The homelab Builder wrote exactly what was asked, then surfaced that
a rebuild driven from `SECRETS.md` would **silently omit the one credential tier 2
cannot work without**. The user approved a third row and it has landed in homelab
**PR #21** (`feat/chat-gateway-service-artifacts`). Corrected here, in the spec,
rather than only in the artifact — otherwise the next rebuild of this runbook's
output regenerates the same omission.

**The failure mode is why it is worth this much text: it is silent and it is
partial.** A missing or misplaced key does **not** stop the gateway. It boots
clean, builds the Chat API adapter, **reports the adapter present at `/healthz`**
— which never `stat`s the file — and then fails at every Google call. Tier-1
webhooks keep working throughout, so the box looks *half*-healthy rather than
broken. **A deployment that looks fine and cannot reach Google is the exact shape
hard rule #5 exists because of**, arriving through a gap in a restore procedure
instead of through a hardcoded `OK`.

⚠ **The third row is DIFFERENT IN KIND from the two above it, and the row must
say so.** The other two hold **values**: you paste them into `.env` and redeploy.
This one holds a **path** — the env var is not the secret, it names a file on the
box. **So restoring this entry means restoring a FILE, and the `.env` alone is not
enough.** A restorer who treats all three rows the same recovers two credentials
and a dangling pointer, and gets the silent half-healthy state above.

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
**every** stack on the box — a cross-repo write owned by whoever holds that
working tree. **Request the run; then read what it produced.** A stop means stop.
*(This said* ***"all ten"*** *until 2026-08-05. It was ten before the gateway
existed and is **eleven** now — which is exactly why the rule is stated against
"every stack" rather than a number: the count changes every time this runbook
succeeds. CG-79.)*

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
- **Only `chat-gateway-sa-gw.json` authenticates.** Any *other*
  `chat-gateway-sa*.json` you find — in an old checkout, a backup, a clone, a
  copy someone made before 2026-08-05 — belongs to the **deleted**
  `chat-gateway-prod` project. It will not authenticate, and finding one is not
  configuration. **Confirm by reading the key's own `project_id` field**, never by
  its filename; that is what the deploy actually did (§10 deviation 7).
  ⚠ **REWORDED 2026-08-05 (CG-79), not removed.** This warning named
  `iac/chat-gateway-sa.json` and warned about *"its presence in the repo"*. **That
  file has since been deleted**, so the old phrasing described nothing — but the
  hazard did not go with it, because this repo cannot delete copies that live
  outside it. §10 deviation 7 said this warning *"must not be removed"* and
  CG-55's queue row set the condition: when the deletion lands, **reword, not
  drop** — a warning that simply vanishes is indistinguishable from one nobody
  thought about.
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
| `SECRETS.template.md` rows | **three** rows per §6 — per-app API keys, tier-1 webhook URLs, **and the service-account key JSON** — three columns, naming the **env var and the service**, never a value and never the key's filename. ⚠ *This said "two rows" until 2026-08-05; the third is the credential tier 2 cannot work without, and its absence is **silent** (§6). It is also different in kind: it names a **path**, so restoring it means restoring a **file**.* |
| `nas/scripts/restore-chat-gateway.sh` | the five-line wrapper form its four siblings use over `lib/restore.sh` |
| `nas/DASHBOARDS.md` + Homepage tile | the service registration its siblings all carry. ⚠ **The tile's `siteMonitor` must end up on `/healthz?strict=1`, not on plain `/healthz`** — see the note below |

✅ **Status 2026-08-05: all five are written and open as homelab PR #21**
(`feat/chat-gateway-service-artifacts`) — service doc, restore wrapper, tile,
`DASHBOARDS.md` entry and the `SECRETS.template.md` rows (**three**, per §6).

⚠ **CORRECTED 2026-08-11 by measuring the box — the tile was WRITTEN, and it was
never LIVE.** `/mnt/datapool/apps/homepage/config/services.yaml` on the NAS
carried **eight** tiles in its NAS group and **chat-gateway was not one of them**.
Whether homelab PR #21 merged is not readable from this repo and is not asserted
here; what *is* measured is that the config Homepage actually serves did not
contain the row. **So for six days the sentence *"the tile ships a known-wrong
verdict"* described a tile that was not probing anything at all** — a different
and quieter failure than the one the paragraph below warns about, and the reason
that paragraph is kept rather than rewritten: it was correct about the artifact
in the PR, and the artifact in the PR was not the artifact in production.
✅ **A tile now exists on the box, created 2026-08-11 and pointed at `?strict=1`
from birth** — see §10's 2026-08-11 entry. It was created directly in that file,
which means the **homelab repo does not yet record it**: `capture.sh` has not been
re-run since. That is an outstanding cross-repo handoff and this repo cannot
discharge it.

⚠ **One of them ships a known-wrong verdict, and it is named here rather than
left to be discovered.** The Homepage tile's `siteMonitor` probes **plain
`/healthz`**, which returns **200 whenever `reasons` is non-empty** — including
for *"subscriber is enabled but has never completed a poll — inbound has never
worked on this process"*, the exact string this box emitted at boot (§10 fact 1).
**So the tile reads green while inbound is dead.** That is the claude-mem
hardcoded-health-check failure — the one hard rule #5 exists because of, which hid
11 days of silent capture failure — **occurring one layer up, at the dashboard**,
against an endpoint that is itself scrupulously honest. `/healthz` is not lying;
the thing reading it cannot hear it.

**The fix is split across two repos and both halves are needed:** **CG-59** adds
an additive `GET /healthz?strict=1` returning **503** when `reasons` is non-empty
with an identical body (plain form unchanged — it is a published contract), and
**the tile is then repointed at the strict form in the homelab repo.** Neither
half is worth anything alone: the endpoint without the repoint changes nothing an
operator can see, and the repoint without the endpoint probes a URL that behaves
identically. ⚠ **Recorded as an owned follow-up, not a defect in PR #21** — the
tile is correct against the endpoint that exists today.

✅ **The endpoint half SHIPPED 2026-08-05 (CG-59).** It is in `main`; the plain
form is untouched and still answers 200 while degraded, by decision.

⚠ **THREE things about the handoff, and the first is a SEQUENCING HAZARD that was
measured on this box rather than reasoned about.** Read all three before
repointing anything:

1. ~~**The running container does not have it yet, and it answers 200 to
   `?strict=1` today.**~~ ✅ **DISCHARGED 2026-08-11 — the image was rebuilt and
   redeployed; `?strict=1` is live and the tile now exists pointed at it.** The
   original text, which was true from 2026-08-05 to 2026-08-11, follows because
   its lesson is the durable part: *"Measured 2026-08-05 against the deployed
   instance: plain → `200`, `?strict=1` → `200`, bare `?strict` → `200`. FastAPI
   ignores a query parameter the deployed handler does not declare, so the strict
   URL is **inert** on the image now serving. **Repointing the tile before the
   image is rebuilt therefore changes nothing while looking exactly like the
   fix** — the same silent-green shape, now wearing a URL that reads as
   remediated. **Order: rebuild + redeploy (§4, §7), verify `?strict=1` returns
   503 on a degraded boot, and only then repoint the tile.**"*

   ⚠ **The premise under that hazard was WRONG in a way that made it milder than
   written, and saying so is the point of keeping it.** *"Repointing the tile"*
   presupposes a tile to repoint, and there was none in the config Homepage
   serves (see the correction above). The hazard described a **silent-green
   dashboard row that did not exist**; what actually existed was **no dashboard
   signal at all**, which is the same blindness by a shorter route. ⚠ **The
   ORDER it prescribes is still exactly right and was followed on 2026-08-11** —
   rebuild, verify, then create the tile against the endpoint that now exists —
   so the instruction survives its own premise being falsified. ⚠ **One step of
   it was NOT satisfied and must not be read as done:** *"verify `?strict=1`
   returns 503 on a degraded boot"* has still never happened on this box. A
   genuine degraded window did occur after the 2026-08-11 restart and cleared
   before a `?strict=1` sample could be taken (§10, 2026-08-11). The 503 path is
   proven only in CG-59's driven local test.
2. ⚠ **The redeploy is NOT scheduled by this row, deliberately** — ⚠ **and the
   reason CHANGED on 2026-08-10 without the conclusion changing.** A rebuild
   restarts the container. This hazard read *"the container's uninterrupted uptime
   **is** the evidence CG-59's soak is accruing (§11). Restarting the gateway to
   install a dashboard fix would spend the thing the same row is measuring."*
   **The soak's sampling stopped on 2026-08-06 (§11, CG-82), so that sentence no
   longer describes anything** — but the *uptime itself* is still accruing and is
   still spent by a restart, and it is now the **only** surviving evidence of the
   kind CG-59 wanted. ⚠ **So the hazard stands, harder rather than softer:**
   before any rebuild, capture `docker inspect`'s `StartedAt` and `RestartCount`
   (**CG-82 task 1**). The endpoint still waits for the next redeploy that happens
   for its own reasons — CG-80's, as it turns out.
   ⚠ **AMENDED 2026-08-10, the day CG-80 merged: that redeploy did NOT happen, and
   the sentence above would otherwise read as though it had.** CG-80 shipped its
   code and **deliberately stopped short of the box** — the rebuild was excluded
   from its scope precisely because this hazard's own ordering constraint
   (capture `RestartCount` first, CG-82 task 1) had not been discharged and
   reaching the box was not authorized. So the endpoint waits still, and the
   queue now has **two** rows whose merge does not put them in production:
   CG-59's `?strict=1` and CG-80's `/mcp`, both riding the same next redeploy.
   That is a heavier handoff than either row planned for on its own, and it is
   recorded here rather than in either row because **this** is the document the
   person doing the redeploy reads.

   ⛔ **THE EVIDENCE THIS HAZARD PROTECTED IS GONE, AND NOT BECAUSE A REBUILD
   SPENT IT — corrected 2026-08-11.** Everything above reasons about *spending*
   `RestartCount: 0` deliberately, in exchange for a deploy. That is not what
   happened. **`dockerd` on this box died on 2026-08-10 and the container did not
   survive it** (§10, 2026-08-11). The last moment the streak was **observed**
   alive is the NAS soak stream's final sample, **`2026-08-06T22:29:53Z`** —
   `restart_count: 0`, `started_at: 2026-08-05T16:34:10.039455732Z`, `status:
   running`, so roughly **25 h of witnessed uptime, not the ~5 days repeatedly
   claimed**, and nothing observed the four days between that sample and the
   outage. **CG-82 task 1 is therefore MOOT: it cannot be discharged, and the
   distinction is the whole point of that task — the evidence was LOST, not
   SPENT.** Spent would have bought a deploy; lost bought nothing. ⚠ **Both
   halves of this hazard's ordering constraint are now void** (there is nothing
   left to capture) **while the redeploy it gated has since happened for its own
   reasons.** Do not resurrect a `docker inspect`-first instruction from this
   paragraph. New baselines, both measured 2026-08-11: `StartedAt
   2026-08-11T14:46:00.906461422Z` after the daemon recovery, then
   `2026-08-11T14:56:49.752003098Z` after the redeploy, `RestartCount: 0`.
3. **The URL is `?strict=1` exactly.** `strict` is a boolean query parameter: a
   bare `?strict` or an empty `?strict=` is a **422** once the new image is
   running — non-200, so the tile would read DOWN on a healthy gateway. That is
   the loud failure rather than the silent one and is recorded rather than
   widened (`docs/integration-guide.md`, *"`?strict=1` — for readers that judge
   by status code"*), but it is a real way to get the handoff wrong.

   ✅ **Confirmed on the box 2026-08-11, and the 422 turned out to be a TOOL** —
   this is the useful half of an inconvenience. Because the pre-2026-08-11 image
   did not declare `strict`, it answered **200 to any value**; the current image
   declares it as a bool and answers **422 to `?strict=banana`**. So a
   deliberately-invalid value is a **one-request discriminator for which image is
   live**, and it obtains that answer **without degrading production and without
   waiting for a fault** — you are asking the parser a question, not the gateway.
   Measured both sides of the redeploy: before, `?strict=1` → `200` and no `mcp`
   field; after, `?strict=banana` → **`422`**, `?strict=1` → `200` while healthy,
   `mcp` field present. ⚠ **Do not point a probe at it.** It is a hand-run
   diagnostic; a monitor on `?strict=banana` reads DOWN forever by design. The
   tile's URL is `?strict=1`, exactly as this hazard says.

---

## §10 · Executed

**Run 2026-08-05 by Builder over SSH (CG-55). The gateway is deployed and
serving.** This section read *"Empty. Nothing here has been run"* until then.

⚠ **This section now holds TWO dated runs and they must not be read as one.** The
2026-08-05 entry below is CG-55's first deploy and is left exactly as it was
written. A second entry — **2026-08-11**, an unplanned 23-hour outage, its
recovery, the first upgrade redeploy, and MCP's enablement — is appended at the
end of the section. **Where the two disagree the later one wins, and it says so
at each site**; nothing in the 2026-08-05 entry has been rewritten to match.

Public-repo discipline (top of this file) applies to this section too: the LAN
address, the tailnet address and the SSH destination are **measured values that
are not written here**. `<LAN-IP>` and `<tailnet-IP>` stand for them; their one
home is the homelab repo's `network/reservations.md`.

### The steps

| Date | Step | Result | Notes |
|---|---|---|---|
| 2026-08-05 | §2 pre-flight — C0(b), CG-61 in the **live** registry | **PASS** | `{aiteam-harness: False, job-hunter: True, aitrader: False}` from the real `load_registry` against the gitignored file. Fail-closed script, not a memory test |
| 2026-08-05 | §2 fail-closed `app.query` for `chat-gateway` | **`[]`** | Run twice — once at the start, once in the same shell as `app.create`, so the check and the create could not be separated by anything |
| 2026-08-05 | LAN address resolved **on the box** | matches the static reservation | `ip -4 addr` and `ip route get` agree on one global interface. ⚠ Resolved, not read from a doc — `reservations.md` also carries an unconfirmed contradicting reading, and the bind makes this load-bearing. **The measurement backs the static reservation, not the contradiction** |
| 2026-08-05 | port 8085 free | **free** | The in-use list matched §1's 2026-07-31 measurement exactly, port for port |
| 2026-08-05 | §3 layout created | 0750 root:root ×5 | `install -d`, restrictive on creation |
| 2026-08-05 | §4 source at a pinned commit + local build | `chat-gateway:local`, 174 MB | Cloned the public repo, `git checkout 52710df`, `docker build` |
| 2026-08-05 | §6 secrets over stdin | **3/3 sha256 match**, modes `600` / `600` / `640` | `install -m 0600 /dev/null` then `tee` from stdin. Verified by hash + `stat`. **Nothing was `cat`-ed** |
| 2026-08-05 | §6 `CREDS-OK` check | **CREDS-OK** | The credential path resolves *in the container*, before `app.create` — the silent failure §6 exists to catch |
| 2026-08-05 | §7 `app.create` | **RUNNING** | Published on `<LAN-IP>:8085` only. Two failed attempts first — see *Deviations* |
| 2026-08-05 | §3 historical-mode sweep | **nothing to fix** | The gateway's own writers created every file `0600`; the `! -perm 600` probe printed nothing. As §3 predicted, prophylactic today |
| 2026-08-05 | §8 tailnet ACL (D2) applied? | **NO — not applied** | Recorded as a **fact of the deploy**, per C0(a) as amended. `network/tailscale-acl.hujson` exists only on the unmerged local branch `feat/remote-access`; it is **absent from that repo's `main`**. The live policy could not be read from here — that needs `docker exec` into another stack, which is a 🛑 |

### The five facts

**1 · `/healthz` — `status` and `reasons`, verbatim.** Read on `<LAN-IP>:8085`:

```
"status": "ok"
"reasons": []
```

⚠ **Not the first value it returned, and the first one is the more useful
record.** Sampled ~8 s after a restart, it was:

```
"status": "degraded"
"reasons": ["subscriber is enabled but has never completed a poll — inbound has never worked on this process"]
```

That is **rule #5 working**, not a fault: the gateway refuses to call itself
healthy on a promise it has not yet kept once. It cleared to `ok` on the first
completed poll. An operator watching a boot will see `degraded` for a few
seconds every time — **expect it.**

**2 · Tier 1 — one webhook send through the deployed instance.**
`POST /v1/messages` → **HTTP 200, `"status": "delivered"`**, identity
**`aitrader-reports`**, mode `webhook`. Driven from the dev box against the
deployed socket, so the whole published path was exercised, not a local run. The
API key travelled in an HTTP header — never argv (rule #2).
`aitrader-reports` was chosen because the registry marks it the *quiet reports*
space: a real space, least disruptive.

**3 · Tier 2 — the subscriber, and the thing this proves.** `last_poll_at`
advanced across every sample; `poll_failures: 0`, `consecutive_poll_failures: 0`,
`last_poll_error: null`, `thread_alive: true`.

⚠ **This is the first evidence that any host but the dev box reaches Pub/Sub** —
egress, service-account token mint, and subscription pull, all from the NAS.

⚠ **`seconds_since_last_poll` oscillates to ~24 s, not to ~5 s, and an operator
alarming on it needs to know that before it pages them.** `poll_interval_seconds`
is 5, but `PubSubPuller.pull()` posts `{"maxMessages": N}` with **no
`returnImmediately`**, so Pub/Sub holds the connection open when the subscription
is empty; the observed period is that hold plus the interval. Far inside
`stale_after_seconds: 300`. Measured, and matched to the request shape in
`adapters/pubsub.py` — not inferred from the number alone.

**4 · Restart — CG-54's replay, on real hardware, against a POPULATED journal.**
An empty-journal restart proves the replay path *runs*; it does not prove it
*restores*. So a job was enqueued through the deployed instance and the gateway's
own container killed inside the dispatcher's 1 s pass window, leaving one `open`
entry with no `close` in `state/queue/delivery.jsonl` — confirmed by reading the
journal's **bookkeeping fields only** while the process was down (`{"op": "open",
"id": 2, "kind": "notify"}`; the payload holds a tenant body and was not read).
On the next boot:

```
queue: restored 1 outbound job(s), 0 expired or unroutable; 0 inbound reply(ies)
```

and `/healthz` `delivery.replayed_at_boot: 1`, settling to `pending_jobs: 0` —
replayed **and then delivered**.

⚠ **`docker kill` did NOT trigger `restart: unless-stopped`, and that is Docker,
not a defect here.** An explicit `kill`/`stop` counts as a manual stop, so the
container stayed `exited` (code 137) until `app.start`. The policy **is** set —
`docker inspect` reports `unless-stopped`. **So this run does not test §8's
crash-loop claim**, which is about a process exiting 2 on its own; that stays
unobserved rather than being read as confirmed.

**5 · The capture — requested, NOT run *by this deploy*, and read anyway.**
`capture.sh` is a 🛑 (cross-repo write across **every** stack on the box) and
**was not run here**. ⏸ ~~It is an outstanding request to whoever holds that
working tree; `nas/compose/chat-gateway.config.json` does not exist yet~~ —
✅ **CLOSED: the user ran it on 2026-08-05 and that file now exists** (recorded
2026-08-05, CG-79). The dated record of what *this run* did is left intact above,
because it is a §10 *Executed* entry and its job is to say what happened on the
day; only the forward-looking half — *"outstanding"*, *"does not exist yet"* —
had expired.

**What the capture showed, without reproducing it.** Scanned for the credential
shapes this project's names defeat (`cgw_`, `chat.googleapis.com`, `token=`,
`key=`, `private_key`, PEM headers): **zero hits**; every env var it carries is a
path or a non-secret flag. ⚠ **The file lives in the homelab repo and its counts
are deliberately not copied here** — a first attempt to quote one got the env-var
count wrong (said four, it is six) from a grep pattern that structurally could not
match the two extras. Both extras are non-secret so the verdict never moved, but
the number had no business being in this repo. ⚠ **`clean. safe to commit.` was
not the evidence** — §5 and CG-53 both establish that the script's suffix rule
cannot see these shapes.

**What was read instead is the same bytes from the same source.** `capture.sh`
captures each custom app via `midclt call app.config <name>` — so
`app.config chat-gateway` was pulled read-only and scanned directly:

- **substring** against the real values of all 7 credential env vars loaded from
  the dev `.env` — **zero hits**. That is stronger than any name- or
  shape-based rule: it cannot be fooled by naming.
- **shape** greps for `cgw_`, `chat.googleapis.com`, `token=`, `key=`,
  `private_key`, PEM blocks, `spaces/…` — **zero hits**.

The document carries **paths and env-var names only**, exactly as §5 designed. ⚠
**No `clean. safe to commit.` line was relied on** — per §7, that gate cannot see
this project's shapes.

### C1a · The first drain — `events_seen: 0`

The most valuable observation in the arc returned **nothing**, and the honest
reading matters more than the number. `events_seen: 0`, `unparseable_seen: 0`,
`suppressed_opt_out: 0`, `suppressed_not_authorized: 0`, `inbox.pending: {}`,
`inbox.dropped: 0`, across a sampled soak with `poll_failures: 0` throughout.

⚠ **This does NOT establish that the four spaces are quiet.** The subscription's
retention is 24 h and it was drained by an ad-hoc client on 2026-07-30, so
anything older is simply gone; `0` means *nothing was retained at this moment*,
not *nothing happened*. The capacity-and-shape questions C1a asks — which event
types arrive, whether the 1000-item cap is reachable — are **still unanswered**
and now belong to **CG-59's soak**, which is the row with a clock long enough to
answer them.

### §5's three verification points — all three answered on the box

1. **Does the middleware accept a compose referencing a locally-built image with
   `pull_policy: missing`?** ✅ **Yes.** First of its kind on that box; §9's
   registry path is not needed.
2. **Does `CHAT_GATEWAY_REGISTRY` resolve in the container?** ✅ **Yes** — the
   `.env`-on-its-own-mount correction holds; `/healthz` reports all 4 identities
   and all 3 apps resolved.
3. **Does the renderer honour `mem_limit` in a custom app?** ✅ **Yes, measured
   rather than assumed** — `docker inspect` reports `Memory=536870912` (512 MiB).
   §5 asked for this to be *said either way* because a limit believed present but
   absent is the one that stops anybody looking. It is present.

### Decision 1 (bind the LAN interface) — demonstrated, not asserted

| Probe | Result |
|---|---|
| `ss -tlnp` | one listener, on `<LAN-IP>:8085` |
| `curl <LAN-IP>:8085/healthz` | **200** |
| `curl 127.0.0.1:8085/healthz` **on the box** | **refused** (curl exit 7) — the consequence §5/CG-55 predicted |
| `curl <tailnet-IP>:8085/healthz` **on the box** | **refused** (curl exit 7) |

The tailnet interface is real and up on that host, and the port is not on it.
**"LAN-only" is a property of the socket here, not a convention** — which is the
whole reason the ACL could be deferred. ⚠ **The residual §8 states is unchanged:
anyone on the home LAN still reaches `/healthz` unauthenticated**, and a future
tailnet subnet route re-opens the question (CG-55's row, decision 1's contingency).

### Deviations from this runbook — the point of this section

1. ⚠ **`app.create` was NOT submitted over stdin, and it cannot be.** §7 says
   *"the JSON from §5, over stdin"*. `midclt` has **no stdin argument mode** —
   measured in `truenas_api_client/__init__.py`'s `from_json`, which reads
   **argv only**. The JSON was streamed to the box by `tee` over stdin and then
   passed as `"$(sudo cat …)"`. **Safe precisely because §5's compose carries
   zero secret values** — that is the design earning out. Recorded because
   "over stdin" is not what happened, and the next person will hit the same wall.
2. ⚠ **Two `app.create` attempts failed first, and the middleware's error names
   the wrong cause.** Both returned
   `[EINVAL] Error handling job lock. This is most likely caused by invalid call
   arguments.` The real cause: `$(cat /root/…)` runs in the **unprivileged**
   shell against a **root-only** file, so `cat` failed and midclt received an
   **empty string** — and `from_json` swallows the JSON error and passes the raw
   string through, so `app.create`'s lock lambda did `"".get("app_name")`.
   **Nothing was created** (`app.query` re-checked `[]`, no container). Fixed with
   `sudo cat`. **A silently-degraded argument is exactly the failure mode this
   repo keeps finding** — the parser that returns something plausible rather than
   raising.
3. **The box `.env` was built key by key — 13 keys — not copied.** §6 already
   requires this; what it does not say is that **three keys were deliberately
   OMITTED**: `CHAT_GATEWAY_REGISTRY`, `CHAT_GATEWAY_STATE_DIR` and
   `CHAT_GATEWAY_INBOX_DIR`. §6 notes the compose overrides them, so copying them
   is harmless — but a dev-relative path sitting in a file where it is silently
   overridden is dead text that misleads the next reader. Omitted rather than
   copied-and-overridden. `CHAT_GATEWAY_INBOX_RETENTION_DAYS` was omitted too, so
   the window keeps the **one home** §3 gives it (`retention.py`); the boot line
   confirms the code default applied.
4. ⚠ **§6's third row understates itself: `CHAT_GATEWAY_INTERACTION_ROUTING_TARGET`
   is not "empty in `.env.example`" on the dev box — it is ABSENT ENTIRELY.**
   Same outcome, but a reader diffing the two files looks for a key that is not
   there. Set to a constant (classic — ADR-0001 D3), **not** the topic path the
   `/healthz` reason text still recommends. Confirmed working: `reasons` is empty
   with the subscriber enabled, and `/v1/identities` for the one opted-out app
   returns `interaction.enabled: false` with the **hard-rule-#6** reason rather
   than the unset-target one — the precedence is right.
5. **`env: loaded 12 key(s)`, from a 13-key file — and the missing one is the
   fail-closed lever working.** `GATEWAY_ENABLE_PUBSUB` is set in the compose, so
   *environment wins* and the file's copy is skipped. §5 put it there so a stale
   `.env` could not leave inbound off; the count is the proof it did.
6. **Restart used `docker kill` + `midclt app.start`, not §4's `app.redeploy`** —
   because fact 4 needed a **crash**, not a tidy restart. ~~`app.redeploy` remains
   the documented upgrade step and is untested by this run.~~ ✅ **STILL untested
   by *this* run — and no longer untested at all. `app.redeploy` was exercised for
   real on 2026-08-11** (`sudo midclt call app.redeploy chat-gateway` → job
   **3112** → **SUCCESS**), picking up a locally rebuilt image on a box with no
   registry, which is the case §4 documents and nothing had ever run. **It works.**
   The dated sentence above is kept because it correctly describes 2026-08-05;
   what expired is the *"and is untested"* half, and it expired on the entry
   below rather than on this one.
7. ⚠ **`iac/chat-gateway-sa.json` — the dead key — was STILL PRESENT in the repo
   on the day of this deploy.** It was **not** used; `chat-gateway-sa-gw.json`
   was, and both files' `project_id` fields were read to confirm which is which
   before anything was copied — **which is the deviation worth recording, because
   it means the check did not rely on the filename.**
   ✅ **The file has since been DELETED (2026-08-05, by the user).** §8's warning
   was therefore **reworded, not removed** — this entry said it *"must not be
   removed"* and that instruction is honoured: what §8 now warns against is the
   dead key's **shape**, since copies of it can outlive this working tree in old
   checkouts, backups and clones, while the path cannot. Recorded 2026-08-05,
   CG-79.

### What this run did NOT do

- **`capture.sh`** — 🛑, requested. ✅ **Since RUN by the user, 2026-08-05, output
  verified clean** (CG-79). This bullet said *"outstanding"*; the run genuinely
  did not do it, which is what this list is for, but the status word had expired.
- **Every homelab-side artifact in §9** — ~~⏸ **still outstanding**~~;
  `nas/services/chat-gateway.md`, the
  `SECRETS.template.md` rows (§6), `restore-chat-gateway.sh`, `DASHBOARDS.md`,
  the Homepage tile. Deploy-then-document: they are written **now**, from the
  facts above, in **that** repo.
  ✅ **All five are WRITTEN and open as homelab PR #21** (recorded 2026-08-05).
  Two things came back from writing them, and both are corrections to **this**
  file rather than to that PR: §6 asked for **two** `SECRETS.template.md` rows and
  the answer is **three** — the omitted one is the service-account key, whose
  absence is silent (§6 now carries the reasoning) — and the Homepage tile probes
  plain `/healthz`, which is green while inbound is dead (§9). ⚠ **Deploy-then-document
  found two defects in the document, which is the argument for that convention
  rather than an embarrassment to it.**
- **The tailnet ACL** — deferred (D2), and recorded above as not applied.
- **No ⚠ verification-ledger flag was cleared, added or reworded.** A live deploy
  is a tempting moment to move one and this run moved none; flag movement needs
  the user's explicit hard-rule-#3 sign-off. ⚠ **One CANDIDATE is worth naming
  rather than acting on:** `SubscriberLoop`'s *long-run thread behaviour* row is
  the flag this deployment is now in a position to retire — but by **soak**, which
  is **CG-59's** job, not by a smoke test measured in minutes.
- **No other `ix-*` container was stopped, restarted, exec-ed into or
  reconfigured**; no `docker system prune`; no daemon restart; no pool or TrueNAS
  write outside `/mnt/datapool/apps/chat-gateway/**`. Verified after the fact:
  every other container's uptime is unchanged.

---

### Run 2026-08-11 — a 23-hour outage nobody detected, then the first upgrade redeploy

**Four separable things happened on one day**, and they are kept separate because
only the second and third were planned: a **platform outage** that had already
been running for most of a day when it was found, its **recovery**, the **first
real upgrade redeploy** (CG-80's `/mcp` and CG-59's `?strict=1`, which had both
been merged and neither in production), and the **operator actions** that gave
the MCP surface its first caller.

#### The outage — measured, and its cause is NOT known

| | |
|---|---|
| `dockerd` failed | **2026-08-10 10:17:35 EDT**, killed by **SIGKILL one second after a start attempt** |
| what kept it down | systemd latched: *"Start request repeated too quickly"* — so a **one-second** failure became a **~23 hour** outage |
| blast radius | **`app.query` returned `[]` for EVERY app** — all **11** stacks, not only chat-gateway |
| not the cause | **no kernel OOM.** `datapool` **ONLINE**, 38 % capacity, clean scrub, zero errors; `docker.config` correctly pointed at `datapool/ix-apps` |
| data | intact — `.env`, `config`, `secrets`, `state`, `soak`, `inbox-data`, `src` all survived |
| recovery | **2026-08-11**: `systemctl reset-failed docker.service docker.socket`, then `systemctl start docker`. **16 containers returned** |

⛔ **What was fixed is the LATCH, not the CAUSE. The original SIGKILL is
unexplained and may recur.** Everything in the table above rules something *out*;
nothing in it explains what sent the signal. `reset-failed` clears systemd's
refusal to keep retrying — it says nothing about why the first attempt died one
second in. **Record this as open.** It is also, deliberately, **not a queue row
in this repo**: the daemon is host configuration, and the standing rules put
writes outside `/mnt/datapool/apps/chat-gateway/**` on the 🛑 list. What this
repo owns is the consequence in the next paragraph.

⛔ **THE FINDING THAT OUTRANKS BOTH ROWS DEPLOYED TODAY: the gateway was down
23+ hours and NOTHING TOLD ANYONE.** This project has a dead-man switch — a
careful one, six of whose failure doors were found and closed in CG-76 — and it
watches **tenants'** silence. It has **no monitor for its own absence**, and it
structurally cannot have one built the same way: **`/healthz` cannot report that
it is not answering.** Every liveness signal this gateway publishes is published
*by the process whose liveness is in question*, so the one failure mode that
matters most is the one mode where every signal is simply absent rather than
alarming. Hard rule #5 made the endpoint honest; honesty is not availability.
**Filed as CG-84** — as a row, not as a paragraph, because a gap recorded only in
a runbook's incident write-up is a gap nobody will work.

#### The redeploy

| Step | Result |
|---|---|
| source on box `52710df` → **`1f2d886`** | `git fetch` + `git checkout <pinned>` — §4's upgrade procedure, first real use |
| `docker build -t chat-gateway:local .` | image **`sha256:a1611d399d28274c40ba914a736b377fa0b59b5c07aa9aea780a5e740ee1fc48`** |
| `sudo midclt call app.redeploy chat-gateway` | job **3112** → **SUCCESS** |
| compose gained `GATEWAY_ENABLE_MCP: "1"` via `sudo midclt call app.update` | job **3180** → **SUCCESS** |

✅ **First real exercise of `app.redeploy`** — §10 deviation 6 recorded it as
documented-but-untested since 2026-08-05. It works, against a locally built image
on a box with no registry. That deviation is updated rather than left standing.

**Which image is live — proven by the parser, not by the gateway.** Before, on
the old image: `/healthz?strict=1` → **200**, no `mcp` field. After:
`?strict=banana` → **422**, `?strict=1` → **200** while healthy, `mcp` field
present. ⚠ **The 422 is the load-bearing discriminator and is worth carrying as a
technique**, not just as a result: the old handler did not declare `strict` so it
returned **200 for any value**, and the new one declares it as a bool. A
deliberately-invalid value therefore separates the two images **in one request,
without degrading production and without waiting for a fault** — see §9 hazard 3.

**Body byte-identity re-confirmed on the box:** plain and `?strict=1` are
identical once volatile counters are ignored, which is CG-59's contract holding on
real hardware rather than in a driven local test.

⛔ **STILL UNVERIFIED ON THE BOX: `?strict=1` returning 503.** A genuine transient
degraded window *did* occur after the restart — `reasons: ["subscriber is enabled
but has never completed a poll — inbound has never worked on this process"]`, the
same string §10 fact 1 recorded in 2026-08-05 — **and it cleared before a
`?strict=1` sample could be taken.** So the 503 path remains proven **only** in
CG-59's driven local test and has never been observed on the deployed instance.
Say it that way; a redeploy that verified the 200 half is not a redeploy that
verified the endpoint.

#### MCP enablement — the operator actions a PR cannot perform

CG-80 shipped a surface with **no caller** (its own *"merging is not finishing"*
note). These are the acts that gave it one. **Env-var NAMES only below; no value
of any kind is recorded in this repo.**

- **A key was minted** — 32 random bytes, hex — and appended to
  `/mnt/datapool/apps/chat-gateway/.env` **over stdin**, never argv (rule #2,
  §6's transport). Mode `600 root:root` preserved; **four** `CHAT_GATEWAY_API_KEY__*`
  names are now present in that file.
- **`config/registry.yaml` on the box gained `agent-mcp`** — `key_env:
  CHAT_GATEWAY_API_KEY__AGENT_MCP`, `identities: [pm-familyworkspace]`,
  `allow_inbound: false`. Backup at `.bak-20260811`; the file was re-parsed and
  asserted after writing, not assumed.
- ⚠ **`aitrader-alerts` and `aitrader-reports` were deliberately NOT granted, and
  the identity list is the ONLY control that exists.** Spec §14 **D7** declined a
  registry `allow_mcp` flag, so there is no MCP-specific opt-out to fall back on:
  what an MCP caller may send as is exactly what its app's `identities` list says,
  and nothing else narrows it. Withholding those two was therefore **an act**, not
  a default — and it is the belt-and-braces D7 said the user could ask for,
  obtained through the mechanism that already exists. Recorded so that adding an
  identity to this app later is understood as widening a real-money tenant's
  model-addressable surface.

#### MCP live exercise — all measured 2026-08-11

`/healthz` now reports `mcp: {"enabled": true, "tools": ["send_message"]}`.

| Probe | Result |
|---|---|
| unauthenticated; wrong key | **401**, both |
| **legacy era `2025-11-25`** — `initialize` | negotiated **`2025-11-25`** |
| legacy `ping` | **200** |
| legacy `tools/list` | `['send_message']`, `identity` enum **`['pm-familyworkspace']`** — per-app narrowing works **on the wire**, not only in tests |
| **modern era `2026-07-28`** | requires **all** of: `params._meta` carrying **both** `io.modelcontextprotocol/protocolVersion` **and** `io.modelcontextprotocol/clientCapabilities`; plus headers `MCP-Protocol-Version`, `Mcp-Method` (cross-checked against the body's method) and `Mcp-Name` (against `params.name`, `tools/call` only). **Each omission produced a distinct, specific 400** |
| `server/discover` | **200**; result keys `_meta, cacheScope, capabilities, instructions, resultType, supportedVersions, ttlMs` |
| `cacheScope` | ✅ **`'private'` confirmed on the wire** — the hard-rule-#4 control the spec flagged as a leak vector, verified where it matters rather than in a unit test. `resultType: 'complete'`, `ttlMs: 300000` |
| **a real message delivered** via `tools/call`, **modern** era | `{"status": "delivered", "channel": "google_chat", "identity": "pm-familyworkspace", "mode": "webhook", "thread_key": null}` |
| **hard rule #4 enforced live** | `aitrader-alerts` refused — `"app 'agent-mcp' may not send as 'aitrader-alerts' (allowed: pm-familyworkspace)"`, `isError: true` |
| audit row in `GET /v1/deliveries` | **1 row** — `source: agent-mcp`, `kind: message`, `status: delivered`, title truncated to 80 chars. ✅ **The refused attempt created NO row**, which is correct |

✅ **The delivery-log row confirms CG-80's build-time fix in production.** The
plan's `call_tool` took no `DeliveryLog` and would have made every MCP send
invisible in `GET /v1/deliveries`; that was caught in build rather than review,
and this is the first evidence the wiring holds on the box.

✅ **This ANSWERS the plan's own *"single most valuable thing this task
produces"* — which era is load-bearing — and it should stop being carried as
open.** The answer is **both**, and the asymmetry is the useful part: legacy is
reachable with a bare `initialize` and nothing else, while modern demands three
headers and two `_meta` keys before it will do anything. A server that had picked
one era would have been silently unreachable to half its clients, exactly as D4a
predicted. ⚠ **D4a's dual-era decision is vindicated by measurement, not by
argument** — which is a stronger position than the one it was taken from, and the
distinction is worth keeping.

⛔ **No ⚠ verification-ledger flag moves, and this is precisely the moment the
spec warned a Builder would want to move one.** A message delivered through the
MCP tool is **the same webhook bytes from a different caller**; `webhook.send` was
cleared 2026-07-29 and nothing about a new ingress re-proves or extends it. Not
one row in `CLAUDE.md`'s ledger is cleared, added, re-priced or reworded by
anything on this page. ⚠ **Nor does the redeploy clear the `SubscriberLoop`
long-run row** — the opposite: the outage destroyed the streak that was its best
evidence (§9 hazard 2, and §11).

#### The Homepage tile — created, not repointed

⚠ **`services.yaml` on the box had 8 NAS tiles and chat-gateway was NOT among
them.** §9's hazard about *"repointing the tile"* was describing a tile that had
never been created in the config Homepage serves. Created 2026-08-11 in
`/mnt/datapool/apps/homepage/config/services.yaml` (backup `.bak-20260811`); the
NAS group now holds **9** tiles and the file was validated by parsing it, not by
eye:

- `href` → the gateway's `/healthz` on the LAN address and port 8085
- `siteMonitor` → the same host and port on **`/healthz?strict=1`**
- a comment in the file explaining why it must be exactly `1`: `strict` is a bool
  query parameter, so a bare `?strict` or an invalid value is a **422**, which
  would make the tile read **DOWN on a healthy gateway**

⚠ **Addresses: `<LAN-IP>` per this file's public-repo discipline** (top of file,
CG-78). The literal values live on the box and in the homelab repo's
`network/reservations.md`; the tile is described here by **shape**.

⚠ **This is a change to the HOMELAB box's configuration, not to this repo, and it
is not yet recorded in the homelab repo either.** That repo references
chat-gateway only in `nas/captured-state.md`, and **`capture.sh` has not been
re-run** since the tile was written. So the tile exists in production and in no
git history anywhere. That is an outstanding cross-repo handoff — §9's *"Artifacts
this repo CANNOT create"* is its home, and **this repo cannot discharge it**.

#### What this run did NOT do

- **It did not explain the SIGKILL.** See above; open, and may recur.
- **It did not verify `?strict=1` → 503 on the box.** The window closed first.
- **It did not re-run `capture.sh`**, so neither the tile nor the new compose
  value (`GATEWAY_ENABLE_MCP`) is captured into the homelab repo.
- **It did not restart the soak.** Both streams are dead and a re-run needs a
  durability design first — §11, and **CG-85**.
- **It moved no ⚠ verification-ledger flag.**

---

## §11 · Observation — the CG-59 soak

⚠ **STOPPED — this section said `RUNNING` for four days after it was not.**
Started 2026-08-05 by Builder over SSH (CG-59); the dev-box `/healthz` stream ran
**24 h 12 m of its 72 h target** and no sampler process has been alive since.
Measured 2026-08-10 by reading the file rather than this paragraph. ⚠ **≥24 h was
the design floor (plan Part G §G2), so the run is not void — it is *at* the floor
with no margin**, and the 72 h every downstream plan assumes is not what exists.
**Exact sample count, the stop timestamp, and every finding — including a
`degraded` window nobody read — live in CG-82, which is their one home.** Numbers
are deliberately not repeated here; this section keeps the design and the artifact
locations, which are unaffected.

⚠ **Why it stopped is an INFERENCE, and this paragraph will not upgrade it.** The
*likely* cause is the limitation documented below — a bare background process with
**no systemd unit and no cron** (both on the standing rules' 🛑 list) does not
survive its host going down. ⚠ **But that limitation is written about the NAS-side
`soak/mem_sampler.py`, a different process on a different host.** The dev-box
sampler's own launch mechanism is documented nowhere in this repo, so applying it
here is **an analogy, not a measurement** — what was actually observed is only *no
live process, and a file four days cold*. No dev-box outage was independently
confirmed.

⚠ **BOTH STREAMS ARE DEAD AND THESE ARE FINAL — measured 2026-08-11.** The
paragraph above described the dev-box half only. The **NAS memory stream** stopped
too, and the numbers below are the whole of what that run produced. Nothing more
will be added to either file.

**NAS memory stream** — `/mnt/datapool/apps/chat-gateway/soak/memory.jsonl`, **152
samples**:

| | |
|---|---|
| window | `2026-08-05T21:15:58Z` → `2026-08-06T22:29:53Z`, `soak_elapsed_s: 90835.9` = **25.2 h** of a 72 h ceiling |
| memory | `current_bytes` **52 539 392 → 52 793 344**; **`peak_bytes` 54 362 112 UNCHANGED**; `max_bytes` 536 870 912 (512 MiB) |
| handles | `threads: 6` constant, `open_fds: 9` constant |
| container | `restart_count: 0`, `status: running` throughout |

✅ **Verdict: flat. No memory leak, no fd growth, no thread growth.** That is a
**clean result for the question this half existed to answer** — the OOM-under-a-
512-MiB-cap-with-zero-swap failure mode described below did not begin to develop.
⚠ **Over 25 h, not 72 h**, and the difference is not rhetorical: the reasons the
design gave for wanting 72 h — three midnight rollovers, ~12 retention sweeps,
~70 token refreshes — are the things a 25 h window does **not** buy. Say *flat
over 25 h*; do not round it up to the run that was planned.

**Dev-box `/healthz` stream** — 2886 samples, 24 h 12 m, 2882 `ok` / 4 `degraded`,
`events_seen` `0 → 0`. ⚠ **Detail is deliberately not restated here — it has one
home and it is CG-82**, including the escalating `ConnectError` window nobody read.

⚠ **A NEW OBSERVATION, recorded as an open question rather than a conclusion:
both streams died the same evening, about 90 minutes apart** — dev box
`2026-08-06T21:02:42Z`, NAS `2026-08-06T22:29:53Z`. **Two independent samplers, on
two different hosts, stopping that close together suggests a common cause, and
what that cause was is unexplained.** The inference on offer for each host alone —
*"a bare background process does not survive its host going down"* — is written
below for the NAS sampler and was only ever an **analogy** for the dev-box one
(that process's launch mechanism is documented nowhere in this repo). Neither
inference explains the **coincidence**, and a coincidence is exactly the shape that
looks explained once you have two separate stories for it. ⚠ **This is not
connected to the 2026-08-10 `dockerd` failure by anything but suspicion** — that is
four days later, and asserting a link would be inventing one. Filed as **CG-85**,
with the consequence that matters: **any future long-run evidence needs a capture
that survives a host event, and this project has now lost two runs to not having
one.**

⛔ **AND THE UPTIME EVIDENCE IS GONE — this is the sharpest correction on the
page.** Four files asserted, in the present tense, that `RestartCount: 0` since
`2026-08-05T16:34:10Z` was *"~5 days of live uptime evidence that CG-80's rebuild
will spend"*. **It was not spent. The container did not survive the 2026-08-10
`dockerd` outage** (§10, 2026-08-11). **The last moment the streak was observed
alive is this stream's own final sample, `2026-08-06T22:29:53Z`** — which is
roughly **25 h of witnessed uptime**, with nothing observing the four days
between that sample and the outage. **So CG-82 task 1 is MOOT: it cannot be
discharged.** ⚠ **Lost, not spent — and the difference is the entire point of
that task.** Spent would have meant a deliberate trade for a deploy; lost means
the evidence went, and this project got nothing for it, and *nothing noticed for
a day* (CG-84).

**Results are NOT in this section yet, and this section says so rather than being
written ahead of them.** ⚠ **Partly superseded 2026-08-11 by the block above** —
the raw numbers are now here, because both files are final and a pointer to a
finished artifact nobody will re-open is worse than the four lines it saves. What
is still **not** here, and is genuinely still owed to CG-59, is the **analysis**:
the pass/fail verdict against §G2.5, the §G3′ disk-growth calibration, and the
ledger proposal. The design — why ≥24 h is the floor, what a pass is, and how a quiet
network is told apart from a wedged loop — has **one home**, plan Part G §G2. Do
not restate it here.

### What is being captured, and by whom

Two streams, two cadences, because the fields have two shapes. They are captured
by **different processes on different hosts**, deliberately: a sampler sharing
the machine it measures cannot tell *"the gateway is wedged"* from *"the sampler
is wedged"*.

| Stream | Cadence | Where it is written | Host |
|---|---|---|---|
| the whole `/healthz` body + its HTTP status code | 30 s | `~/cg59-soak/healthz.jsonl` | the **dev box**, over the LAN |
| container RSS, cgroup memory, open fds, thread count, restart count, `du` of each state directory, host swap | 10 min | `/mnt/datapool/apps/chat-gateway/soak/memory.jsonl` | the **NAS**, outside the container |

**The whole body per sample, one JSON object per line, appended.** The field list
in this arc has been wrong three times; a soak that captures a selected subset
cannot be re-read three days later for the field it dropped, and the run is
unrepeatable in a way the analysis is not.

**Neither artifact is committed.** They are inputs to a summary, not
deliverables, and the summary is what lands here. ⚠ Note that `state/` is
gitignored for this class of accident (CG-67) and **the soak files are not under
`state/`** — that guard does not cover them; they are outside the repo entirely
instead.

### Why the memory half exists at all

**The NAS has zero swap** (measured, and re-measured in every sample:
`swap_total_bytes: 0`) and the container's `memory.max` is **512 MiB**. A leak
over 72 h therefore ends in an **OOM kill**, not a slowdown — and under
`restart: unless-stopped` an OOM kill looks *identical to uptime* from `/healthz`
alone, because every counter in the body comes back at a plausible zero. That is
why `restart_count` is read from `docker inspect` rather than inferred from the
body, and why a liveness-only soak would miss the failure mode most likely to
actually occur.

`memory.peak` is sampled alongside `memory.current` for the same reason: it is a
monotonic high-water mark, so a 10-minute cadence cannot step over a spike.

### The sampler, and what it is allowed to touch

`soak/mem_sampler.py` on the box (`0750 root:root`; output `0640`). It is
**read-only against everything it measures** — `docker stats`, `docker inspect`
and `/proc` are reads, and `du` walks directory metadata and never opens a file,
which is what makes it safe over `inbox-data/`: that tree holds tenant message
bodies and this process reads their **sizes**, never their bytes. Numbers and
paths only reach the artifact; no tenant content can, by construction.

It refuses to start if its own pidfile names a live process — two appenders on
one JSONL produce duplicate rows indistinguishable from real readings.

### Durability — what it survives, and what it does not

Launched with `sudo setsid sh -c '…' &`, so it holds **its own session id** and
is not a child of the SSH session. Verified: it kept running across several
subsequent connections.

⚠ **Two limits, stated plainly rather than implied:**

- **It does NOT survive a reboot of the NAS**, or a `kill`. There is no systemd
  unit and no cron entry — installing either is a write to system configuration
  outside `/mnt/datapool/apps/chat-gateway/**`, which the standing rules put on
  the 🛑 list. If the box reboots, the memory stream restarts from zero and the
  run's duration claim resets with it; check `soak_elapsed_s` in the last line
  before trusting any span.
- **It stops on its own after 72 h.** The ceiling is in the script, not in a
  scheduler, so nothing has to remember to stop it. ⚠ **It never reached that
  ceiling — it stopped at 25.2 h** (see the top of this section). The ceiling was
  never the binding constraint on either stream, which is the finding: **both
  runs were ended by their environment, not by their design**, and the design's
  one durability control was aimed at the wrong end of the run.

⚠ **Gotcha for whoever runs the next one: `setsid --fork` does not work on this
box.** It fails with `Function not implemented` (ENOSYS on the child's `execve`),
as does anything launched through it — measured, twice, with two different target
binaries. Plain `setsid` without `--fork` works and is what is used. `nohup … &`
also works. This cost a launch attempt.

### What is already known before the run finishes

⚠ **The run has since ENDED — this heading is left in its original tense because
it dates itself, and every bullet under it is annotated rather than rewritten.**
Final numbers are in the block at the top of this section.

- ~~container start **2026-08-05T16:34:10Z**, `RestartCount: 0` — the soak clock
  and the deployment clock are the same clock, and it has not been reset.~~
  ⛔ **FALSIFIED 2026-08-11: it HAS been reset, and not by anything this project
  chose.** The `dockerd` failure of 2026-08-10 ended it; the streak's last
  **observed** moment is `2026-08-06T22:29:53Z`, not the ~5 days four documents
  went on claiming. Current baselines, measured 2026-08-11: `StartedAt
  2026-08-11T14:46:00.906461422Z` (daemon recovery), then
  `2026-08-11T14:56:49.752003098Z` (redeploy), `RestartCount: 0`. ⚠ **A fresh
  `RestartCount: 0` is not evidence of anything yet** — it is hours old, and
  reading it as continuity with the old streak is the exact mistake this bullet
  now exists to prevent.
- the memory stream's first sample is **2026-08-05T21:15:58Z**, so it starts
  ~4.7 h into the deployment's uptime. **The gap is recorded rather than
  smoothed:** the `/healthz` stream and the container's own uptime both cover
  that window; the memory stream does not, and a trend line drawn through it must
  not be extended backwards.
- at first sample: cgroup `memory.current` **52 539 392 B**, `memory.peak`
  **54 362 112 B** against a **536 870 912 B** limit — ~9.8 % of the cap, 6
  threads, 9 open fds.

⚠ **Nothing above clears, adds or rewords a ⚠ verification-ledger flag, and this
section must not be read as doing so.** The ledger's `SubscriberLoop` *long-run
thread behaviour* row is what this run produces **evidence** for; retiring it is
a hard-rule-#3 decision that needs the user's explicit sign-off, on CG-35's
precedent. ⚠ **And say what the evidence will reach:** `events_seen` was `0` at
deploy and may legitimately still be `0` at the end. A quiet subscription running
for three days proves the thread survives; it proves little about behaviour under
load. The full what-a-quiet-space-cannot-prove table is plan §G2.6 — **do not
summarize it, and do not argue a sign-off on the premise that the subscription is
busy.** It was not.
