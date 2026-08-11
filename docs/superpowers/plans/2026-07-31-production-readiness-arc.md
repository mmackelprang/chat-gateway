# Production-readiness arc — implementation plan

**Spec:** [`../specs/2026-07-31-production-readiness-arc-design.md`](../specs/2026-07-31-production-readiness-arc-design.md)
**Date:** 2026-07-31 · **Queue rows:** CG-53 … CG-59

**Parts A–G map one-to-one onto the queue rows. Each Part is one PR.**

Baseline on `main` (`670a5d8`): **202 passing**. That number moves with every
shipped item — **take the real count from the suite, not from this plan.** On the
Windows dev box the runner is `python -m pytest -q`; on POSIX it is
`python3 -m pytest -q`.

**Before any Part: read `CLAUDE.md`.** Six hard rules govern every task here.
Rule #3's flag discipline applies to Parts F and G in particular: **no ⚠ flag may
be cleared, added or reworded** without the user's explicit sign-off naming the
rule.

> ⚠ **Identity-literal discipline.** CG-26's guard scans `docs/**/*.md`,
> `tests/**/*.py` and root `*.md`. **No real identity literal may enter any file
> this plan touches** — no emails, no `users/…` ids, no `domainId`/`customer`
> values, no tokens, no space ids, no webhook URLs, no homelab addressing values.
> Name **sources and paths**. Every fixture value below is synthetic.

---

# ⚠ Standing rules for the SSH connection (Parts A, C and H0)

`ssh nas` works with `BatchMode` and **`sudo` is passwordless — effectively
root** — on a box running **10 live app stacks / 15 containers**, including
claude-mem's Postgres. `claude` is **not** in a `docker` group, so every docker
call is `sudo docker`, i.e. root. These rules bound that, and they apply to every
command in this plan.

| | Allowed | Concretely |
|---|---|---|
| ✅ | read-only probing, unattended | `docker ps`, `docker stats --no-stream`, `docker inspect`, `midclt call app.query`, `free`, `df`, `ss -tln`, `ip link` |
| ✅ | create the gateway's **own** app / dirs / config | only under `/mnt/datapool/apps/chat-gateway/**`, only the app name `chat-gateway` |
| ✅ | build and run the gateway's own image | `docker build`, `midclt call app.create` for `chat-gateway` |
| 🛑 | another stack | never stop / restart / exec / reconfigure any other `ix-*` container — **including** `sudo docker exec ix-tailscale-tailscale-1 tailscale …` |
| 🛑 | Docker global state | **never** `system prune`, `network prune`, `volume prune`, daemon restart, image cleanup |
| 🛑 | pools / TrueNAS | no dataset work outside the gateway's path, no pool ops, no `midclt` **write** against another app |
| 🛑 | `capture.sh` | it rewrites `nas/compose/*.json` for **every stack on the box** — a cross-repo write, owned by whoever holds that working tree |

⚠ **The row above said *"all ten"* until 2026-08-05, and so did three more places
in this file** (Part A §7, Part C's header, Part C's *What must NOT happen*).
**The count was wrong when written and is wronger now.** Ten was the *pre-existing*
stack count measured 2026-07-31; the gateway makes **eleven**, and the live
`app.query` confirms it. This is **CG-69 category (b)** — wrong when written, not
gone stale — and it propagated by quotation into `nas.md` §1's heading, a briefing,
and a sibling agent's task before anybody counted (CG-79, queue § CG-79 *"Fact 6"*).

**The fix is not to write eleven.** The number changes every time this runbook
succeeds, which is precisely what makes it the wrong thing to pin in a rule. All
four sites now state the scope — *every stack on the box* — and `nas.md` §7 makes
the same correction in the same words, for the same reason. A rule keyed on a
count invites a reader to check the count; a rule keyed on the scope does not need
checking.

**A stop means stop and report — never work around.** If the gateway cannot be
created without touching something on the 🛑 list, that is a finding for the
user, not an obstacle to route around.

**Fail-closed before creating the app:**

```bash
ssh nas "sudo midclt call app.query '[[\"name\",\"=\",\"chat-gateway\"]]'"
# MUST be []. Anything else -> STOP and report. It is [] as of 2026-07-31,
# but this arc has already been wrong twice about what is on that box.
```

## Secret material — stdin or file copy, NEVER a command-line argument

An argument lands in local shell history, remote shell history, and `ps` output
on a box other people's software runs on. `sudo` logs the command it ran, not
what was piped into it.

```bash
# FORBIDDEN — the value is in argv, and therefore in history and in ps
ssh nas "echo '<secret>' > /mnt/datapool/apps/chat-gateway/.env"
ssh nas "sudo sh -c 'echo <secret> >> /mnt/datapool/apps/chat-gateway/.env'"

# REQUIRED — create restrictive FIRST, then stream content over stdin
ssh nas 'sudo install -d -m 0750 /mnt/datapool/apps/chat-gateway/{config,secrets,state,inbox-data}'
ssh nas 'sudo install -m 0600 /dev/null /mnt/datapool/apps/chat-gateway/.env'
ssh nas 'sudo tee /mnt/datapool/apps/chat-gateway/.env >/dev/null' < ./.env

# same shape for the service-account key (filename per docs/google-cloud-setup.md)
ssh nas 'sudo install -m 0600 /dev/null /mnt/datapool/apps/chat-gateway/secrets/sa.json'
ssh nas 'sudo tee /mnt/datapool/apps/chat-gateway/secrets/sa.json >/dev/null' < ./iac/<sa-key>.json

# the registry holds env-var NAMES, not values — not secret, same transport, 0640
ssh nas 'sudo install -m 0640 /dev/null /mnt/datapool/apps/chat-gateway/config/registry.yaml'
ssh nas 'sudo tee /mnt/datapool/apps/chat-gateway/config/registry.yaml >/dev/null' < ./config/registry.yaml
```

**Create restrictive, then fill — never fill and then tighten.** `tee` does not
change an existing file's mode, which is why step 2 exists.

**Verify without printing:**

```bash
ssh nas 'sudo sha256sum /mnt/datapool/apps/chat-gateway/.env' | cut -d" " -f1
sha256sum ./.env | cut -d" " -f1            # compare by eye; equal == landed intact
ssh nas 'sudo stat -c "%a %U:%G %n" /mnt/datapool/apps/chat-gateway/.env'
```

⚠ **Never `cat` these files to check them.** A hash proves the transfer and
`stat` proves the mode, with no secret byte reaching a terminal, a log, or this
transcript.

---

# Part A — CG-53 · Deployment artifacts and the secret-safety proof

**Ships no deploy.** ⏸ **Merge gate: secret-handling path.**

## A1 · `src/chat_gateway/env_file.py` (new)

```python
"""Load a KEY=VALUE file into the environment — the deployment's rule-#2 seam.

WHY THIS IS IN OUR CODE rather than compose's `env_file:`. The deploy target is
a TrueNAS custom app: its compose document is submitted over an API and then
CAPTURED into a sibling repo by a script whose secret detection is an
upper-cased SUFFIX match. That match does not fire on this project's shapes —
`CHAT_GATEWAY_API_KEY__<APP>` ends with the app id and
`GOOGLE_CHAT_WEBHOOK_URL__<IDENTITY>` ends with the identity name. Secrets placed
in `environment:` would therefore be captured in PLAINTEXT under a script that
prints "clean. safe to commit."

RE-MEASURED 2026-08-03 (the premise lives in a repo this one does not control,
so it is checked rather than quoted): still true, and RENAMING IS NOT AN ESCAPE
HATCH. Running that repo's real `is_secret_key` over this project's real key
names, all seven credential vars miss; `GOOGLE_APPLICATION_CREDENTIALS` (a path,
not a credential) is the only one caught. The two families fail for DIFFERENT
reasons, which the one-line version of this hides: bare `CHAT_GATEWAY_API_KEY`
IS caught, so the `__<APP>` suffix is what defeats it there — but bare
`GOOGLE_CHAT_WEBHOOK_URL` is MISSED TOO, because that list has no `URL` entry
(only `DATABASE_URL`). The webhook family would leak under any naming scheme.
Nor does any value-based rule save it: a webhook URL carries `key`/`token` as
QUERY PARAMETERS, not `user:pass@`, so the URL-credential regex does not match
either. End to end through the real redactor and the real scan gate: the
credentials survive verbatim and the gate exits 0.

Keeping every secret in a file the compose document only NAMES makes that capture
clean by construction, and puts a hard-rule-#2 guarantee on code this repo tests
rather than on an unverified property of someone else's compose renderer.

No dependency: `python-dotenv` is not worth one for twenty lines, and the same
call is made for the delivery journal's persistence (Part B).
"""

from __future__ import annotations

import os
from pathlib import Path


class EnvFileError(RuntimeError):
    """The named env file could not be used. Names the PATH, never a value."""


def parse_env_file(text: str) -> dict[str, str]:
    """`KEY=VALUE` lines. Honours `#` comments, blanks, `export `, and ONE layer
    of matching surrounding quotes.

    A line with no `=` is ignored rather than guessed at: this file is written by
    an operator under time pressure during a deploy, and inventing a meaning for
    a malformed line is how a credential ends up half-set.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def load_env_file(path: str | Path, environ: dict | None = None) -> int:
    """Load `path` into `environ` (default `os.environ`). Returns keys APPLIED.

    THE ENVIRONMENT WINS. A key already present is left alone, so an operator's
    explicit override is never silently replaced by the file — and so this is a
    no-op in every existing test and on the dev box.

    A MISSING FILE RAISES. A gateway that boots with no credentials answers
    `degraded` on an UNAUTHENTICATED endpoint and otherwise looks alive; refusing
    to start names the fault while it can still be fixed. That is the same
    reasoning rule #5 rests on.

    Values are never returned, logged or interpolated — only a COUNT. Key names
    are non-secret (they are in the committed `.env.example`); values are the
    entire point of this module.
    """
    environ = os.environ if environ is None else environ
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise EnvFileError(
            f"CHAT_GATEWAY_ENV_FILE={p} could not be read: {type(exc).__name__}"
        ) from exc
    applied = 0
    for key, value in parse_env_file(text).items():
        if key in environ:
            continue
        environ[key] = value
        applied += 1
    return applied
```

## A2 · Wire it into `__main__.build_runtime`

It must run **before** `load_registry`, which reads env-indirected names, and
before any adapter is constructed.

In `src/chat_gateway/__main__.py`, replace:

```python
    install_url_redaction()

    registry = load_registry(os.environ.get("CHAT_GATEWAY_REGISTRY", "config/registry.yaml"))
```

with:

```python
    install_url_redaction()

    # Deployment seam (hard rule #2). On the NAS every secret lives in an
    # off-repo file mode 600 that the compose document only NAMES, so nothing
    # secret is ever in the compose — see env_file.py for the capture-script
    # suffix gap that makes this structural rather than stylistic. Before
    # load_registry, which resolves env-indirected names. Unset on the dev box
    # and in tests, where this is a no-op.
    env_file = os.environ.get("CHAT_GATEWAY_ENV_FILE", "")
    if env_file:
        from .env_file import load_env_file

        print(f"env: loaded {load_env_file(env_file)} key(s) from {env_file}", flush=True)

    registry = load_registry(os.environ.get("CHAT_GATEWAY_REGISTRY", "config/registry.yaml"))
```

And in `main()`, widen the startup error handler so a bad env file exits like a
config error rather than a traceback.

⚠ **REFRESHED 2026-08-03 — the tuple this Part was written against has grown.**
When Part A was drafted `build_runtime()` returned **five** values; CG-68 added a
sixth (`sweeper`). Measured on `main` (`4e55368`), `__main__.py:127` reads:

```python
        registry, inbox, adapters, subscriber, state_dir, sweeper = build_runtime()
```

So the edit is to the **`except` clause only** — do **not** retype the unpack
line from an older draft of this plan, or you will silently drop the sweeper and
`serve` will fail at `sweeper.sweep()`. Change:

```python
    except RegistryError as exc:
```

to:

```python
    except (RegistryError, EnvFileError) as exc:
```

with the import at module top:

```python
from .env_file import EnvFileError
```

⚠ **Re-measure the unpack before editing.** This is the second time this Part's
snapshot of that line has aged out in three days; take it from the file, not from
here.

Update the module docstring's env list to include `CHAT_GATEWAY_ENV_FILE`. That
list currently names seven vars and is already missing `CHAT_GATEWAY_STATE_DIR`
(read at `__main__.py:40`) — adding it is in scope for this Part, since the
docstring is the thing this task is editing anyway.

## A3 · `tests/test_env_file.py` (new)

```python
"""CHAT_GATEWAY_ENV_FILE — the seam that keeps secrets out of the NAS compose."""

import pytest

from chat_gateway.env_file import EnvFileError, load_env_file, parse_env_file


def test_parses_comments_blanks_export_and_quotes():
    parsed = parse_env_file(
        "# a comment\n"
        "\n"
        "PLAIN=value\n"
        "export EXPORTED=exported-value\n"
        'DOUBLE="quoted value"\n'
        "SINGLE='quoted value'\n"
        "EMPTY=\n"
        "SPACED = padded \n"
    )
    assert parsed == {
        "PLAIN": "value",
        "EXPORTED": "exported-value",
        "DOUBLE": "quoted value",
        "SINGLE": "quoted value",
        "EMPTY": "",
        "SPACED": "padded",
    }


def test_a_line_without_an_equals_is_ignored_not_guessed_at():
    assert parse_env_file("JUST_A_WORD\nGOOD=1\n") == {"GOOD": "1"}


def test_an_equals_inside_the_value_survives():
    # A base64 key or a URL query is full of '='. Only the FIRST splits.
    assert parse_env_file("K=a=b=c\n") == {"K": "a=b=c"}


def test_the_environment_wins_over_the_file(tmp_path):
    f = tmp_path / "env"
    f.write_text("KEEP=from-file\nADD=from-file\n", encoding="utf-8")
    environ = {"KEEP": "from-environment"}
    applied = load_env_file(f, environ)
    assert environ["KEEP"] == "from-environment"   # never silently replaced
    assert environ["ADD"] == "from-file"
    assert applied == 1                            # only the one it actually set


def test_a_missing_file_raises_rather_than_booting_without_credentials(tmp_path):
    with pytest.raises(EnvFileError) as excinfo:
        load_env_file(tmp_path / "nope", {})
    assert "CHAT_GATEWAY_ENV_FILE" in str(excinfo.value)


def test_the_error_names_the_path_and_carries_no_value(tmp_path):
    d = tmp_path / "is-a-directory"
    d.mkdir()
    with pytest.raises(EnvFileError) as excinfo:
        load_env_file(d, {})
    assert str(d) in str(excinfo.value)


def test_load_returns_a_count_and_never_the_values(tmp_path, capsys):
    f = tmp_path / "env"
    f.write_text("SECRETISH=SYNTHETIC-NOT-A-REAL-VALUE\n", encoding="utf-8")
    environ = {}
    assert load_env_file(f, environ) == 1
    # nothing printed by the loader itself; the caller prints only the count
    assert capsys.readouterr().out == ""
```

## A4 · `.env.example` — add the new key

⚠ **SCOPE, measured 2026-08-03: ONE key. Add it and change nothing else.**
`.env.example` is already complete against the code — every one of the ten
non-secret config vars the source reads has an entry, including CG-68's
`CHAT_GATEWAY_INBOX_RETENTION_DAYS` and the two read indirectly
(`retention_days_from_env()` and `service.ROUTING_TARGET_ENV`), plus the three
API-key and four webhook-URL slots. `CHAT_GATEWAY_ENV_FILE` is the **only**
addition this Part makes to that file. If a draft of this task grows into
"refresh `.env.example`", stop — that is a different row.

Insert immediately under the `# --- gateway ---` block:

```
# Set on the NAS deployment ONLY. Names a file (mode 600, off-repo) holding every
# secret below, so the container's compose document carries PATHS and nothing
# else. THE ENVIRONMENT WINS: a key already set is never replaced by the file.
# A path that cannot be read is a startup failure, not a warning — a gateway with
# no credentials looks alive on an unauthenticated /healthz.
# Unset locally; this file IS the local path.
CHAT_GATEWAY_ENV_FILE=
```

## A5 · `docker-compose.yml` — scope it, and resolve the dated comment

⚠ **REFRESHED 2026-08-03 for the bind-to-LAN decision.** The header this Part
originally wrote ended *"LAN/tailnet only"* — inherited verbatim from the file it
replaces. That clause is now **wrong about the NAS in a way that matters**: the
user's 2026-08-03 decision has CG-55 publish on the **LAN address**, which
deliberately removes tailnet reach *to this port*. A header saying "LAN/tailnet"
would read as a promise that the NAS artifact is tailnet-reachable, which is the
opposite of what CG-55 builds.

**This Part does NOT change the port line.** `ports: "8085:8085"` stays here —
this is the dev box, a different host, and re-binding it is neither this row's
decision nor its business. What changes is that the header stops **generalizing**
a dev-box property into a claim about the deployment. The one home for the bind
decision is `docs/BUILDER_QUEUE.md` § CG-55, *"Two user decisions, 2026-08-03"*;
point at it, do not restate it.

Replace the header and the SA-key comment block:

```yaml
# LOCAL / DEV-BOX path. `build: .` and the relative bind mounts below are what
# make this convenient here and unusable on the NAS: that target is a TrueNAS
# CUSTOM APP, whose compose document is submitted over an API (no build context,
# absolute mounts only) and then captured into the homelab repo. The NAS artifact
# and its runbook are docs/deploy/nas.md — do not adapt this file by hand.
#
# The publish form below is the DEV BOX's, and does not describe the deployment:
# "8085:8085" binds 0.0.0.0, every interface. The NAS publishes on the LAN
# ADDRESS by decision (queue CG-55, "Two user decisions, 2026-08-03"), so that
# port is not tailnet-reachable there. Do not copy this line to the box and do
# not read it as the deployed posture.
#
# No public ingress, on either host — Pub/Sub is an outbound pull, so nothing
# here ever needs to be reachable from the internet. Never publish this through a
# reverse proxy.
services:
  chat-gateway:
    build: .
    container_name: chat-gateway
    restart: unless-stopped
    env_file: .env
    environment:
      CHAT_GATEWAY_REGISTRY: /config/registry.yaml
      CHAT_GATEWAY_STATE_DIR: /data/state
      CHAT_GATEWAY_INBOX_DIR: /data/inbox
    ports:
      - "8085:8085"
    volumes:
      - ./config:/config:ro
      - /data/chat-gateway:/data
      # tier 2: mount the SA key read-only and point
      # GOOGLE_APPLICATION_CREDENTIALS at it in .env. The FILENAME is deliberately
      # not written here: CG-51 made the setup scripts DERIVE it from PROJECT_ID,
      # and a filename pinned in a comment is what CG-19 found stale. The live one
      # is recorded in docs/google-cloud-setup.md. Note that any
      # `chat-gateway-sa*.json` OTHER than `chat-gateway-sa-gw.json` is DEAD — it
      # belongs to the deleted `chat-gateway-prod` project. (This named the path
      # `iac/chat-gateway-sa.json` until 2026-08-05; the user deleted that file,
      # so the warning is keyed on the SHAPE now — copies outlive the path, and
      # the setup scripts still default KEY_FILE to that name. Confirm by the
      # key's own project_id, not by its filename.)
      # - ./secrets:/secrets:ro
```

## A6 · `docs/deploy/nas.md` (new) — the runbook

**The path `docs/deploy/nas.md` is confirmed** — checked 2026-08-03 rather than
taken from this plan's word. It is a new directory in **this** repo, which no
homelab convention governs, and it sits beside the existing `docs/consumers/`,
`docs/google-cloud-setup.md` and `docs/integration-guide.md`. Nothing collides.

⚠ **But this Part's stated JUSTIFICATION for the split was FALSE, and is
withdrawn.** It read: *"in the shape of `docs/consumers/*-handoff.md`: … the
homelab repo's four-header `nas/services/chat-gateway.md` **links** here rather
than duplicating it,"* and §4.1 of the spec called that *"a split that matches
both repos' conventions."* Measured in the homelab repo 2026-08-03, it matches
**neither**:

- **This repo has no `*-handoff.md` shape to be in.** That glob matches exactly
  one file (`docs/consumers/jobhunt-handoff.md`); its siblings are
  `aitrader.md` and `jobhunt.md`. There is no convention here to follow.
- **No `nas/services/*.md` links out to another repo.** All ten keep operational
  detail **inline**; every link in that directory is intra-repo and relative. A
  homelab doc pointing at a chat-gateway-owned runbook is a **new pattern there,
  not an existing one.** The nearest precedent is not even in `nas/` — it is
  `appserver/services/familyworkspace.md`, which scopes itself (*"This doc covers
  infra + deploy only — app source … live in the FamilyWorkspace repo"*) while
  still writing every deploy command out inline.

**The decision does not change; its honesty does.** Owning the runbook here is
still right — this repo can test its own claims and the homelab repo cannot — but
it is a **deliberate deviation** from that repo's house style, and the runbook
must say so rather than claim a convention it invented. The homelab-side artifact
is a **four-header** `nas/services/chat-gateway.md` (`## Overview (User)`,
`## Deployment (Ops)`, `## Reinstall / Recovery`, `## Gotchas` — per
`nas/services/_TEMPLATE.md`, no extra headers, no `###`), which carries the
inline minimum its siblings do and points here for the rest.

⚠ **Writing that file is NOT this row's work.** It lands in the homelab repo,
which a chat-gateway Builder does not write (standing rules). Name it as a
deliverable **for the user**, in this runbook's §9, so it is a handoff rather
than an omission.

Required sections and their load-bearing content:

**§1 What this is — the ELEVENTH stack.** ⚠ **Said *"the tenth stack"* until
2026-08-05, and it was wrong when written, not gone stale.** The **10 app stacks**
measured below are the ones already there; the gateway is an addition, so it is
the eleventh — and the live `app.query` now lists 11. The right number sat three
lines under the wrong one for five days, in this file and in the `nas.md` §1
heading this paragraph specifies, and survived because **a heading reads as a
title and a paragraph reads as data, so nobody compares them** (CG-79 fact 6;
CG-69 category (b), which that spec §8 says no guard in this repo can reach).
⚠ **Not a role change.** An earlier draft
called the NAS *backup target only*; that came from another project's
pipeline-scoped table and is withdrawn. Measured 2026-07-31: the box already runs
**10 app stacks / 15 containers** (beszel ×2, calibre, calibre-web, claude-mem
×5 incl. Postgres, czkawka, homepage, jellyfin, pihole, tailscale, upsnap), all
named `ix-<app>-<service>-1`.

Capacity, measured: **20.8 GB RAM available of 31.9 GB**, load **0.29** on 16
cores, `datapool` **1% of 13 TB**. A small Python service is noise.

⚠ **The box has ZERO swap** — a memory spike is an OOM kill on a host running
someone else's Postgres. Blast-radius controls: a **memory limit** (see §5),
published port **8085** (measured free; in use are `22 53 80 139 443 445 3000
5357 5800 6000 6999 8081 8090 8098 30013 30014 31067 32014 32015 32016 37877
41175 62716`), **no `network_mode: host`**, no new capabilities, mounts confined
to one app directory, and **no change to any existing app**.

**§2 Prerequisites.** TrueNAS Apps pool initialized. `ssh nas` (`BatchMode`,
passwordless sudo — verified 2026-07-31). `docs/google-cloud-setup.md` completed
and the live SA key present on the dev box. **Name
`nas/scripts/lib/common.sh` in the homelab repo as the source of host, user and
key values; do not reproduce them here** — this runbook is in a public repo.
Re-run the fail-closed app-name check from the standing rules before proceeding.

**§3 On-box layout** — create with restrictive modes **first**, then copy in.
Never copy into a world-readable directory and tighten afterwards.

⚠ **REFRESHED 2026-08-03 — the state tree grew two subdirectories after this
Part was written** (CG-65's quarantine, CG-68's retention sweep), and the old
four-line sketch would have had an operator reasoning about the wrong disk.
Measured against `__main__.build_runtime` on `main` (`4e55368`):

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

**What an operator must take from that tree — three facts, not a diagram:**

1. **Four locations hold tenant message bodies**, not one. Anyone sizing a
   backup, a snapshot policy or a support request needs all four.
2. **Only `inbox-data/` is ever swept.** `quarantine/` is **never** pruned — that
   is what makes the sweep safe to run at all — and `deliveries/` is untouched by
   decision. Both are enforced in code: the sweeper **refuses to boot** if its
   directory overlaps the state dir. So an operator who "tidies up" by pointing
   `CHAT_GATEWAY_INBOX_DIR` at a state subdirectory gets a **refusal to start**,
   not a silent deletion. Say so — that refusal looks like a bug at 2am.
3. **The retention window is not written here.** It has one home,
   `retention.py`'s constants, quoted to consumers at `docs/integration-guide.md`.
   The runbook names the env var (`CHAT_GATEWAY_INBOX_RETENTION_DAYS`) and the
   fact that `0` disables pruning; it does **not** copy the number. A duplicated
   moving number is this repo's own most-repeated lesson.

Reasoning and measurements for all of the above: **ADR-0002.** Do not restate.

⚠ **The `0644` line CG-70 owes this runbook — decided 2026-08-02, add it here.**
CG-70's Planner call chose **(a)**, an in-code stat-and-chmod at the four append
sites, and explicitly routed its **(b)** half to this row: *"(b) becomes one line
in CG-53's runbook … it belongs there because CG-53 already owns
`install -d -m 0750`."* The two cover **disjoint sets** — (a) only ever reopens
*today's* date-sharded file, so a `0644` day-file from three days ago is never
touched by it and sits there until the sweeper deletes it, or **forever** where
`CHAT_GATEWAY_INBOX_RETENTION_DAYS=0`. The runbook line is therefore a **sweep of
what already exists**, run once after the directories are created and again after
any restore from a backup that predates CG-65:

```bash
# Historical day-files only. (a) self-heals today's; nothing reopens yesterday's.
ssh nas 'sudo find /mnt/datapool/apps/chat-gateway/state /mnt/datapool/apps/chat-gateway/inbox-data \
  -type f ! -perm 600 -exec chmod 0600 {} +'
ssh nas 'sudo find /mnt/datapool/apps/chat-gateway/state /mnt/datapool/apps/chat-gateway/inbox-data \
  -type f ! -perm 600 -print'   # MUST print nothing
```

⚠ **This does not close CG-70 and must not be written as though it does.** That
row stays open for the `src/` half and is deliberately **not** folded into this
one — a four-file code change does not belong in a merge-gated secret-handling
PR. State the dependency direction plainly: **no such file exists anywhere today**
(the gateway has never been deployed), so this line is prophylactic.

⚠ **The parenthetical is FALSE since 2026-08-05 — the gateway is deployed and
serving** (CG-55, PR [#66](https://github.com/mmackelprang/chat-gateway/pull/66),
`4ddd6f5`). ✅ **The prediction it was supporting held anyway, and that is the
part worth keeping:** §3's historical-mode sweep ran on the box and printed
nothing — *"the gateway's own writers created every file `0600`"*
(`nas.md:653`), so the line really was prophylactic on this deploy. **It stays
prophylactic rather than becoming unnecessary**, because CG-70's `src/` half is
still open: the `0600` chmod is create-only, so a pre-existing `0644` file keeps
its mode, and a *restored* directory is exactly where that arises. Corrected
rather than deleted, because a claim that quietly flips is how this arc has gone
stale before.

**§4 Build the image on the box** — ✅ **DECIDED (D4)**; §9 keeps the registry
alternative as the upgrade path. No registry, no credentials, no external
dependency in the deploy path.

Getting the source there: `git clone` this **public** repo at a **pinned
commit** is the auditable form — it records exactly what was built and carries no
secret. Fallback if the box lacks egress: stream a tarball over stdin (`git
archive` | `ssh nas 'tar -x -C …'`), which is the same no-argv transport the
standing rules require, though source is not secret. Then `sudo docker build -t
chat-gateway:local .` and tag locally; `pull_policy: missing` means it is never
pulled.

⚠ **A rebuild is a MANUAL step.** There is no CI to the NAS and none is wanted.
The upgrade procedure — re-clone at the new commit, rebuild, `app.redeploy` —
belongs in this runbook, or the first upgrade is an improvisation.

**§5 The compose document** — `custom_compose_config`, carrying **paths only**:

⚠ **CORRECTED 2026-08-03 — the previous JSON could not have booted.** Two env
values did not match the mounts beside them, and the old §5 filed the first as
*"verify that `CHAT_GATEWAY_REGISTRY` resolves"* — a thing to check, when it was
a thing to fix. Traced against the mount list rather than read past:

| Was | Mounted at | Result |
|---|---|---|
| `CHAT_GATEWAY_REGISTRY: /config/registry.yaml` | `config` dir → `/config/config` | file is at `/config/config/registry.yaml` — **`RegistryError`, exit 2** |
| `CHAT_GATEWAY_ENV_FILE: /config/.env` | `.env` file → `/config/.env` | correct, but only via a mount **nested inside** the one above |

Fixed by giving `.env` its own mount point so **nothing nests and every env value
maps to exactly one mount** — rather than by deepening the registry path to
`/config/config/registry.yaml`, which resolves but reads like a typo and invites
the next person to "fix" it.

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

⚠ **`"ports": ["8085:8085"]` above is LEFT AS THE `0.0.0.0` FORM ON PURPOSE.** It
is **CG-55's** to change to the LAN-address form, and that is already recorded in
that row and in Part C's C0 note. Do not change it here; do not let the surviving
`0.0.0.0` in this block be read as endorsement.
⚠ **Part C's C0 says "the custom-app JSON *below*" — it is ABOVE it, here in Part
A.** Recorded so CG-55's Builder does not go looking in Part C for a block that
lives in Part A.

**`GATEWAY_ENABLE_PUBSUB: "1"` is new here, and it is a fail-closed lever, not a
convenience.** It is declared in the compose — where it is non-secret and
captured — precisely so a stale `.env` cannot leave inbound silently **off**:
with the flag on, a missing `CHAT_GATEWAY_PUBSUB_SUBSCRIPTION` or
`GOOGLE_APPLICATION_CREDENTIALS` raises `RegistryError` and the process exits 2,
naming the fault. Without it, the copied dev-box default `0` wins by the loader's
own "environment wins" rule and the gateway boots **healthy with no subscriber at
all** — the exact shape hard rule #5 exists to prevent. See §6.

Matches house style: `restart: unless-stopped`, `pull_policy: missing`, `TZ` set,
bind mounts under `/mnt/datapool/apps/<app>/`, **no** `container_name` (TrueNAS
names it `ix-chat-gateway-chat-gateway-1`), **no** `labels`, **no** `env_file`,
**no** `logging`.

✅ **`mem_limit` — DECIDED (D6): set one.** Recorded explicitly as a **deliberate
deviation from local convention: no existing *custom* app on that box sets one**
(measured; the 4 GiB caps on jellyfin, calibre, calibre-web and tailscale are
TrueNAS's own, on *catalog* apps). The reason: an unbounded Python service on a
**swapless** box is a neighbour that takes others down, and **the OOM killer
picks its own victim — possibly claude-mem's Postgres.**

⚠ **Three things to verify on the box rather than assume**, recorded as decision
points so they are not discovered live:
1. that the middleware accepts a compose referencing a **locally-built** image
   with `pull_policy: missing` — every existing custom app pulls a public image,
   so this is first-of-its-kind there. If rejected → §9's registry path.
2. that `CHAT_GATEWAY_REGISTRY` resolves; the registry path nests under the
   read-only `/config` mount alongside `.env`.
3. **that the renderer honours `mem_limit` in a custom app.** If it is silently
   dropped, say so — a limit believed present but absent is worse than none.

**§6 Secrets onto the box.** Transfer `.env` and `registry.yaml` by the stdin
form in the standing rules — never as a command-line argument — and create
restrictive, then fill, per §3.

⚠ **ADDED 2026-08-03 — the dev box's `.env` is NOT usable verbatim, and this
Part said "scp `.env`" as though it were.** "Environment wins" makes the compose
authoritative for the three path vars it sets, so the copied dev values for
`CHAT_GATEWAY_REGISTRY`, `CHAT_GATEWAY_STATE_DIR` and `CHAT_GATEWAY_INBOX_DIR` are
harmlessly overridden. **Two keys are not in the compose, so the file's dev-box
values win — and both are wrong on the box:**

| Key | Dev-box value | On the box | If not corrected |
|---|---|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | a dev-relative path | `/secrets/<sa-key>.json` | ⚠ **boots clean, fails at every tier-2 call** |
| `GATEWAY_ENABLE_PUBSUB` | `0` in `.env.example` | `1` | inbound silently off — now caught by §5's compose flag |

**The first one is the dangerous one, and it is silent by construction.**
`GoogleServiceAccountTokens.__init__` only *stores* the path — the key file is
not opened until the first token mint. So a wrong path produces a gateway that
starts, builds the Chat API adapter, and reports it present; **`/healthz` does
not check that the file exists** (`registry.health()` reports identity env-var
resolution and per-app key configuration, and no code path stats the credential
file). It looks alive and cannot talk to Google. That is the same failure this
row's own loader property #3 exists to prevent, one level up — so the runbook
closes it the same way, with an explicit check rather than a reminder:

```bash
# after transferring .env, BEFORE app.create — proves the path resolves IN the
# container, without printing a single byte of the file
ssh nas 'sudo docker run --rm --env-file /mnt/datapool/apps/chat-gateway/.env \
  -v /mnt/datapool/apps/chat-gateway/secrets:/secrets:ro \
  chat-gateway:local sh -c "test -r \"\$GOOGLE_APPLICATION_CREDENTIALS\" \
  && echo CREDS-OK || echo CREDS-MISSING"'
```

Record the edited keys in the runbook as a **table of what differs between the
dev `.env` and the box's**, so the next transfer is a diff rather than a
rediscovery.

**Then register the secret in the homelab repo** — `SECRETS.template.md` is the
**tracked** one (`.gitignore` carries the `!SECRETS.template.md` negation);
`SECRETS.md` is gitignored and holds real values. Its rows are three columns,
`| Secret | Where it lives on the box | How to regenerate / rotate |`, and the
model to copy is the existing Chroma row, which names the **env var and the
service** rather than a value. **THREE rows**, structure only:

- the per-app API keys — regenerate with `python3 -m chat_gateway mint-key`, then
  update the consumer;
- the tier-1 webhook URLs — ⚠ **no rotate-in-place exists.** Recovery is
  delete-and-recreate by hand per `docs/google-cloud-setup.md` §8a. Say so in the
  rotate column; this project burned every webhook it owns once, on 2026-07-29.
- the **service-account key JSON** — never its filename; the directory and
  `docs/google-cloud-setup.md`.

⚠ **This said "two rows" until 2026-08-05, and the spec was the defect, not the
artifact.** The homelab Builder wrote exactly the two rows asked for, then
surfaced that a rebuild driven from `SECRETS.md` would silently omit the one
credential **tier 2 cannot work without**. A wrong or missing key is **silent**: the
gateway boots clean, reports the Chat API adapter present at `/healthz` (which
never `stat`s the file), fails every Google call, and keeps delivering tier-1
webhooks the whole time — half-healthy, which hides. **The third row is also
different in kind: the env var holds a PATH, so restoring it means restoring a
FILE and the `.env` alone is not enough.** The full reasoning has one home,
`docs/deploy/nas.md` §6; the user approved it and it landed in homelab PR #21.

**§7 Verify — the gate.**

⚠ **CORRECTED 2026-08-03: do NOT run `capture.sh`.** This Part said *"Run
`capture.sh`"*, which **contradicts this plan's own standing rules**, where it is
a 🛑 — it rewrites `nas/compose/*.json` for **every stack on the box**, a
cross-repo write owned by whoever holds that working tree (*"all ten"* until
2026-08-05 — see the standing-rules table's correction note). Part C already has this right
(*"request it, then read what it produced"*). **Request the run; then read the
output.** A stop means stop.

The file to read is **`nas/compose/chat-gateway.config.json`** — the pattern is
`nas/compose/<app-name>.config.json`, and the app set is derived live from
`app.query` filtered on `custom_app`, so **this file appears automatically on the
first capture after the app exists.** Nobody opts in; that is what makes the leak
this row prevents a default rather than a mistake.

It must contain **zero** secret values. ⚠ **Do not trust `clean. safe to
commit.`** — re-measured 2026-08-03 end to end through that repo's real redactor
and real scan gate: a payload carrying a live-shaped `CHAT_GATEWAY_API_KEY__*`
and a `GOOGLE_CHAT_WEBHOOK_URL__*` came back **with both values intact** and the
scan **exited 0**. A `POSTGRES_PASSWORD` in the same payload was redacted, which
is exactly what makes the green gate persuasive. Grep the captured file for the
literal marker and for our own key prefixes rather than reading the console line.

**Cross-repo note, not our change:** if the homelab repo ever wants defence in
depth, a `*_API_KEY__*` / `*_WEBHOOK_URL__*` substring rule is the shape that
would catch these. ⚠ **Note the second-order risk before proposing it there:**
that repo's `lib/restore.sh --strip-redacted` **drops every marker-valued key
from a deploy payload**, so a false positive silently deletes real config on
restore — which is precisely why its suffix list is anchored and conservative.
Our design does not need that rule, and this row must not be justified by it.

**§8 Gotchas** — in the homelab house voice (a hard-won lesson with its cost):
- **Tailnet reachability would be FREE here — and CG-55 declines it on purpose.**
  ⚠ **REFRESHED 2026-08-03: the measurement stands, its consequence inverted.**
  Measured 2026-07-31: `ix-tailscale-tailscale-1` runs `network_mode: host` with
  `/dev/net/tun`, `CAP_NET_ADMIN` and `TS_USERSPACE=false`, so **`tailscale0` is a
  real host interface**, and a port on `0.0.0.0` is tailnet-reachable with **no
  subnet router, userspace proxy, sidecar, `serve` or `funnel`.** That is exactly
  **why binding `0.0.0.0` is the thing not to do**: it publishes on every
  interface the host has, including that one. **CG-55 binds the LAN address**, so
  the port is not tailnet-reachable whatever the ACL says. Reasoning and residual
  have one home — `docs/BUILDER_QUEUE.md` § CG-55, *"Two user decisions,
  2026-08-03"*. ⚠ **Still record the dependency**, because it governs any future
  decision to re-expose: if that app is switched to userspace mode or off host
  networking, `tailscale0` vanishes from the host and every service's tailnet
  reachability goes silently with it — nothing in the gateway's own config shows
  it.
- **`tailscale` is NOT on the host PATH.** Any tailnet inspection means
  `docker exec` into another stack's container, which the standing rules classify
  as a STOP.
- **`/healthz` is UNAUTHENTICATED by design** — and since 2026-07-31 that matters
  more than app-id enumeration. With the Chat app live in both Ai Trader spaces
  and `allow_inbound: false`, **`suppressed_opt_out` increments once per event
  there**, making the endpoint a live activity meter for another tenant's private
  trading spaces: volume and timing, no content and no attribution. Hard rule #6
  is working — nothing crosses. Per-app API keys (rule #4) protect `/v1/*` and
  nothing else.
  ⚠ **DO NOT ENUMERATE `/healthz`'s FIELDS IN THIS RUNBOOK.** Name the endpoint,
  say what class of thing it exposes, and **link** to the one home: the
  field-by-field table in `docs/integration-guide.md` § *Durability counters at
  `/healthz`*. That table's own counts have been wrong **five** times (CG-69's
  spec, category (c)) and **CG-76 landed as #63 on 2026-08-03**, adding four
  degrade inputs and new fields — ⚠ *this sentence read "is in flight right now …
  wrong the day CG-76 lands" and was falsified within hours of being written,
  which is the point it was making.* A list copied here is a list that is wrong
  on someone else's schedule — the two-homes-for-a-moving-fact trap `CLAUDE.md`
  opens with.
- ⚠ **The D2 tailnet ACL is DEFERRED — corrected 2026-08-03.** This Part said
  *"✅ Decided (D2): the drafted homelab tailnet ACL lands BEFORE this is
  deployed, so the endpoint is fenced from the start."* **That is no longer
  true.** The user deferred the ACL on 2026-08-03: still wanted, **no longer
  gating the deploy**, and no external homelab prerequisite remains on CG-55. The
  **LAN bind is what replaces it** — and the two are one decision in two halves,
  so neither reads correctly alone. One home for both:
  `docs/BUILDER_QUEUE.md` § CG-55.
  ⚠ **The bind does not make the ACL unnecessary.** It removes tailnet reach **to
  this port** and says nothing about the rest of that box or the rest of the
  tailnet. The live policy is still default allow-all (homelab recorded that
  2026-07-28). **Accepted residual, stated rather than glossed: anyone on the home
  LAN still reaches `/healthz` unauthenticated.** Part C records whether the ACL
  was applied at deploy time, so the posture is a fact in the *Executed* section
  rather than an assumption here.
- **Zero swap.** An unbounded container OOM-kills a neighbour, and one neighbour
  is claude-mem's Postgres. See `mem_limit` in §5.
- **No public ingress is needed or wanted.** Pub/Sub is an outbound pull. Never
  put this behind the public reverse proxy.
- **Any `chat-gateway-sa*.json` that is NOT `chat-gateway-sa-gw.json` is DEAD** —
  deleted project. Do not authenticate with it, and **confirm which key you hold
  by its own `project_id`, never by its filename.**
  ⚠ **REWORDED 2026-08-05, not dropped.** This said *"`iac/chat-gateway-sa.json`
  is DEAD … its **presence** is not configuration"*, and the user **deleted that
  file on 2026-08-05** — so a warning keyed on its presence now describes nothing,
  which is worse than silence: a reader who does not find it concludes the hazard
  is gone. It is not. Copies survive in old checkouts, backups and clones, and
  **`iac/gcloud-setup.sh` and its `.ps1` sibling still default `KEY_FILE` to that
  exact filename**, so re-running setup writes it back. **The path is gone; the
  hazard is not.** This is the fourth of five sites CG-55's row required to be
  reworded rather than dropped — a warning that simply vanishes is
  indistinguishable from one nobody thought about.
- **Restarting drops nothing.** ⚠ **REFRESHED 2026-08-03 — this said *"once Part
  B lands, and drops everything before it,"* and Part B LANDED** (CG-54, #45,
  2026-07-31). There is no interim build to warn about: both queues are durable
  and are replayed at boot **with the attempt count preserved**, which is what
  stops a crash loop from resetting the backoff ladder and hammering Google.
  The rule and its edge cases have one home each — `delivery.py`'s docstring and
  `journal.py`'s. Link; do not restate.
- ⚠ **A config error under `restart: unless-stopped` is a CRASH LOOP, and that is
  the intended behaviour — say so, or it reads as a bug.** A missing
  `CHAT_GATEWAY_ENV_FILE`, a bad registry path or a retention/state directory
  overlap all exit **2** with `config error: …` on stderr, and TrueNAS restarts
  the container. The operator sees a restarting app, and the reason is in
  `docker logs`, not in `/healthz` — **there is no `/healthz` to read, which is
  the entire point** (loader property #3). It costs nothing: the process dies
  before the dispatcher exists, so a crash loop generates **no** Google traffic.
  First diagnostic is the logs, not the endpoint.

**§9 Alternatives, rollback, and the homelab-side handoff.** Registry-image path;
`midclt call app.delete`; what a rollback does *not* undo (state directories
persist — deliberately, and per §3 four of them hold tenant bodies, so "delete
the app" is not "delete the data").

⚠ **Also list, explicitly, the artifacts this repo CANNOT create** — they are in
the homelab repo, and a chat-gateway Builder writing them is a standing-rules
violation. Naming them here makes this a handoff rather than an omission:
`nas/services/chat-gateway.md` (four-header, per `_TEMPLATE.md`), a
`SECRETS.template.md` row per §6, `nas/scripts/restore-chat-gateway.sh` (the
five-line wrapper form its four siblings use over `lib/restore.sh`), and the
`nas/DASHBOARDS.md` / Homepage tile registration.

**§10 Executed** — empty, dated and filled by Part C. Says so, so a reader can
tell "planned" from "ran".

## A7 · Verify Part A

⚠ **The baseline is 359, not this plan's `202`.** That number moves with every
shipped item — **take it from the suite, not from here.** Measured on `main`
(`7086482`) 2026-08-03: **359 passed.** Nine PRs merged between this Part being
written and being dispatched.

⚠ **This line has now been stale TWICE, hours apart.** It was refreshed to
`345` (`4e55368`) earlier the same day and CG-76 landed as #63 before the refresh
was even pushed, taking it to 359. **That is the argument for the instruction,
not an exception to it:** re-run the suite, do not read this number.

```bash
python -m pytest -q                           # the current baseline + the new tests
python -m pytest -q tests/test_env_file.py
python -c "import chat_gateway.__main__"      # import-time wiring is sound
```

Confirm `CHAT_GATEWAY_ENV_FILE` unset ⇒ byte-identical behaviour to `main`. That
is what makes the loader a no-op in **every** existing test and on the dev box —
and it is a **claim to verify, not to assert**: the whole suite passing unchanged
is the evidence.

⚠ **Hard rule #3: this Part clears, adds and rewords NO ⚠ verification flag.** It
adds a loader, a runbook and two doc edits; it exercises nothing against Google.
Verify before opening the PR:

```bash
git diff main -- src/ | grep -c "LIVE-UNVERIFIED\|SHAPE-VERIFIED"   # MUST be 0
```

---

# Part B — CG-54 · Queue and inbox durability

No merge gate. Offline-testable throughout.

## B1 · `src/chat_gateway/journal.py` (new)

```python
"""Append-only JSONL journal for queue state — the THIRD use of one idiom.

`heartbeat.py` persists JSON atomically (write `.tmp`, `os.replace`) and
`delivery.py` / `inbox.py` append JSONL audit lines. This module is those two
primitives applied to queue STATE, and deliberately NOT a third idiom: no new
dependency, one file per queue, readable with `tail` during an incident.

NOT THE AUDIT TRAIL, and not a replacement for it. The audit files are
per-app-per-day, never pruned, and carry no TERMINAL records — they say what
ARRIVED, never what LEFT, so pending state cannot be reconstructed from them.
Different question, different file; both stay.

Durability is chosen over throughput deliberately: every append is flushed and
fsync'd. The traffic shape this serves is tens of messages a day (the jobhunt
contract's R5), so the cost is invisible and the guarantee is the point.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
from pathlib import Path
from typing import Callable

SCHEMA_VERSION = 1

#: Appends since the last compaction before one is triggered inline. Boot-time
#: compaction alone is not enough for a process meant to run for weeks — on one
#: that never reboots, boot-only compaction is no compaction at all.
DEFAULT_COMPACT_AFTER = 1000


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Journal:
    """`open` / `update` / `close` records for one queue.

    Replay is every id with an `open` and no `close`, with the LAST `update`
    applied. Append-only is preserved: a retry APPENDS an `update`, it never
    rewrites the `open`.
    """

    def __init__(self, path: str | Path, *,
                 compact_after: int = DEFAULT_COMPACT_AFTER,
                 now_fn: Callable[[], dt.datetime] | None = None):
        self._path = Path(path)
        self._compact_after = compact_after
        self._now = now_fn or _utcnow
        self._lock = threading.Lock()
        self._since_compaction = 0
        #: Lines the last replay could not parse. Surfaced at /healthz rather
        #: than swallowed — see replay() for why they are not fatal.
        self.skipped_lines = 0

    # -- writing --------------------------------------------------------------
    def _append(self, record: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._since_compaction += 1

    def open(self, entry_id: int, kind: str, payload: dict) -> None:
        with self._lock:
            self._append({"v": SCHEMA_VERSION, "op": "open", "id": entry_id,
                          "kind": kind, "payload": payload,
                          "ts": self._now().isoformat()})

    def update(self, entry_id: int, attempts: int, next_attempt_at: str) -> None:
        """Record a RESCHEDULE. `attempts` must survive a restart or a crash-loop
        resets the backoff ladder every time and hammers the far end forever —
        which turns a durability feature into an outage amplifier."""
        with self._lock:
            self._append({"v": SCHEMA_VERSION, "op": "update", "id": entry_id,
                          "attempts": attempts, "next_attempt_at": next_attempt_at,
                          "ts": self._now().isoformat()})

    def close(self, entry_id: int, status: str) -> None:
        with self._lock:
            self._append({"v": SCHEMA_VERSION, "op": "close", "id": entry_id,
                          "status": status, "ts": self._now().isoformat()})
            if self._since_compaction >= self._compact_after:
                self._compact_locked()

    # -- replay ---------------------------------------------------------------
    def replay(self) -> list[dict]:
        """Surviving jobs, oldest first: `open` payloads with their last `update`.

        A line that does not parse is SKIPPED AND COUNTED, wherever it sits in
        the file. A torn trailing line is the EXPECTED shape — a partial write at
        power loss — and a gateway that refuses to boot over a half-written byte
        is a crash loop on a host running `restart: unless-stopped`. Losing one
        record and SAYING SO beats not starting; the count goes to /healthz.
        """
        self.skipped_lines = 0
        if not self._path.exists():
            return []
        live: dict[int, dict] = {}
        order: list[int] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    self.skipped_lines += 1
                    continue
                if not isinstance(rec, dict) or "op" not in rec or "id" not in rec:
                    self.skipped_lines += 1
                    continue
                op, entry_id = rec["op"], rec["id"]
                if op == "open":
                    if entry_id not in live:
                        order.append(entry_id)
                    live[entry_id] = {
                        "id": entry_id,
                        "kind": rec.get("kind", ""),
                        "payload": rec.get("payload") or {},
                        "attempts": 0,
                        "next_attempt_at": rec.get("next_attempt_at") or rec.get("ts", ""),
                        "opened_at": rec.get("ts", ""),
                    }
                elif op == "update" and entry_id in live:
                    live[entry_id]["attempts"] = rec.get("attempts", 0)
                    live[entry_id]["next_attempt_at"] = rec.get("next_attempt_at", "")
                elif op == "close":
                    live.pop(entry_id, None)
        return [live[i] for i in order if i in live]

    # -- compaction -----------------------------------------------------------
    def compact(self, survivors: list[dict] | None = None) -> None:
        with self._lock:
            self._compact_locked(survivors)

    def _compact_locked(self, survivors: list[dict] | None = None) -> None:
        """Rewrite as one `open` (+ one `update` if attempted) per survivor.

        Atomic, via `heartbeat.py`'s idiom: write a sibling `.tmp`, then
        `os.replace`. A reader either sees the whole old file or the whole new
        one — never a half-written journal, which is the one corruption this
        module must not itself create.
        """
        if survivors is None:
            survivors = self.replay()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for job in survivors:
                fh.write(json.dumps({
                    "v": SCHEMA_VERSION, "op": "open", "id": job["id"],
                    "kind": job["kind"], "payload": job["payload"],
                    "next_attempt_at": job["next_attempt_at"],
                    "ts": job.get("opened_at") or self._now().isoformat(),
                }, ensure_ascii=False) + "\n")
                if job["attempts"]:
                    fh.write(json.dumps({
                        "v": SCHEMA_VERSION, "op": "update", "id": job["id"],
                        "attempts": job["attempts"],
                        "next_attempt_at": job["next_attempt_at"],
                        "ts": self._now().isoformat(),
                    }, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self._path)
        self._since_compaction = 0
```

## B2 · `delivery.py` — journal the dispatcher

Replace the module docstring's accepted-limitation paragraph:

```python
Queue state is in-memory: a gateway restart drops undelivered jobs, visible
in the log as enqueued-without-terminal-status. Documented, accepted for v0.
```

with:

```python
Queue state PERSISTS when a `Journal` is supplied (`state/queue/delivery.jsonl`),
which is what the deployed gateway does; without one it stays in-memory, which is
what every offline test does. Replay is open-minus-close with the attempt count
preserved. A job whose send may or may not have reached Google at kill time is
REPLAYED and may therefore deliver twice — Chat has no idempotency key, notify
dedupe collapses repeats within its window, and losing an alert is the worse
failure. A job older than `REPLAY_MAX_AGE_S` is closed as `expired` at boot
rather than posted: an alert from three days ago, delivered now, actively
misleads. See journal.py.
```

Add the constant beside `BACKOFF_S`:

```python
#: Replayed jobs older than this are closed as `expired` at boot, not sent. Both
#: outcomes are bad; this is the visible one.
REPLAY_MAX_AGE_S = 86400.0
```

Extend `Dispatcher.__init__`:

```python
    def __init__(self, adapters: dict, log: DeliveryLog,
                 now_fn: Callable[[], dt.datetime] | None = None,
                 backoff: tuple = BACKOFF_S,
                 journal=None,
                 replay_max_age_s: float = REPLAY_MAX_AGE_S):
        self._adapters = adapters
        self._log = log
        self._now = now_fn or _utcnow
        self._backoff = backoff
        # None keeps this object exactly what it was before persistence existed,
        # which is what every existing test constructs. Opt-in, not opt-out.
        self._journal = journal
        self._replay_max_age_s = replay_max_age_s
        self._jobs: list[Job] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.replayed = 0
        self.expired = 0
```

`enqueue` — journal after the log record, before the job is visible:

```python
    def enqueue(self, source: str, kind: str, identity: Identity,
                message: OutboundMessage, title: str) -> int:
        entry_id = self._log.record(source, kind, title, "enqueued")
        now = self._now()
        if self._journal is not None:
            self._journal.open(entry_id, kind, {
                "source": source, "kind": kind, "identity": identity.name,
                "message": message.model_dump(mode="json"), "title": title,
            })
        with self._lock:
            self._jobs.append(Job(entry_id=entry_id, source=source, kind=kind,
                                  identity=identity, message=message, title=title,
                                  next_attempt_at=now))
        return entry_id
```

In `process_due`, journal the reschedule:

```python
                else:
                    job.next_attempt_at = now + dt.timedelta(seconds=self._backoff[job.attempts])
                    if self._journal is not None:
                        self._journal.update(job.entry_id, job.attempts,
                                             job.next_attempt_at.isoformat())
                    self._log.record(job.source, job.kind, job.title, "retrying",
                                     f"attempt {job.attempts}: {exc}", entry_id=job.entry_id)
```

In `_finish`, journal the close:

```python
    def _finish(self, job: Job, status: str, detail: str) -> None:
        self._log.record(job.source, job.kind, job.title, status, detail,
                         entry_id=job.entry_id)
        if self._journal is not None:
            self._journal.close(job.entry_id, status)
        with self._lock:
            if job in self._jobs:
                self._jobs.remove(job)
```

New `restore`:

```python
    def restore(self, registry) -> tuple[int, int]:
        """Re-queue what the journal says never finished. Returns (restored, expired).

        Identities are RE-RESOLVED from the registry rather than unpickled from
        the journal: the journal stores an identity NAME, and the registry is the
        only thing that knows whether that app may still send as it (hard rule
        #4). A job whose app or identity has since been removed, or whose
        allowlist no longer covers it, is closed as `unroutable` — never sent on
        the strength of a permission the registry no longer grants.
        """
        if self._journal is None:
            return (0, 0)
        now = self._now()
        restored = expired = 0
        survivors: list[dict] = []
        for rec in self._journal.replay():
            payload = rec["payload"]
            entry_id = rec["id"]
            source = payload.get("source", "")
            title = payload.get("title", "")
            kind = payload.get("kind", rec.get("kind", ""))
            try:
                opened = dt.datetime.fromisoformat(rec.get("opened_at") or "")
            except ValueError:
                opened = now
            if (now - opened).total_seconds() > self._replay_max_age_s:
                self._log.record(source, kind, title, "expired",
                                 f"older than {self._replay_max_age_s:.0f}s at restart "
                                 "— not delivered", entry_id=entry_id)
                self._journal.close(entry_id, "expired")
                expired += 1
                continue
            try:
                identity = registry.identity_for(source, payload.get("identity", ""))
                message = OutboundMessage(**payload["message"])
            except Exception as exc:  # noqa: BLE001 — config drift, not a bug
                self._log.record(source, kind, title, "unroutable",
                                 f"not restored after restart: {exc}", entry_id=entry_id)
                self._journal.close(entry_id, "unroutable")
                expired += 1
                continue
            try:
                next_at = dt.datetime.fromisoformat(rec["next_attempt_at"])
            except ValueError:
                next_at = now
            job = Job(entry_id=entry_id, source=source, kind=kind, identity=identity,
                      message=message, title=title, attempts=rec["attempts"],
                      next_attempt_at=next_at)
            with self._lock:
                self._jobs.append(job)
            survivors.append(rec)
            restored += 1
        # Boot-time compaction: the file is only READ here, so this is the point
        # at which everything terminal can go.
        self._journal.compact(survivors)
        self.replayed, self.expired = restored, expired
        return (restored, expired)
```

## B3 · `inbox.py` — journal the inbox

The spec's §2.3 correction: decision A makes this the *only* inbound path for
jobhunt, so its in-memory queue matters as much as the dispatcher's.

Docstring gains:

```python
Queue state PERSISTS when a `Journal` is supplied; the JSONL audit beside it is
a different artifact answering a different question (what arrived, not what is
still pending) and both stay. Without a journal this is in-memory, which is what
every offline test constructs.
```

```python
    def __init__(self, audit_dir: str | Path | None = None, max_pending: int = 1000,
                 journal=None):
        self._pending: dict[str, deque[InboundReply]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._audit_dir = Path(audit_dir) if audit_dir else None
        self._max_pending = max_pending
        self._journal = journal
        self._ids = itertools.count(1)
        self._ids_by_app: dict[str, deque[int]] = defaultdict(deque)
        self.dropped = 0
        self.replayed = 0

    def put(self, reply: InboundReply) -> None:
        self._audit(reply)
        entry_id = next(self._ids)
        if self._journal is not None:
            self._journal.open(entry_id, "inbound", reply.model_dump(mode="json"))
        with self._lock:
            q = self._pending[reply.app]
            ids = self._ids_by_app[reply.app]
            if len(q) >= self._max_pending:
                q.popleft()
                dropped_id = ids.popleft() if ids else None
                if dropped_id is not None and self._journal is not None:
                    self._journal.close(dropped_id, "dropped")
                self.dropped += 1
            q.append(reply)
            ids.append(entry_id)

    def poll(self, app_id: str) -> list[InboundReply]:
        with self._lock:
            q = self._pending[app_id]
            items = list(q)
            q.clear()
            ids = list(self._ids_by_app[app_id])
            self._ids_by_app[app_id].clear()
        if self._journal is not None:
            for entry_id in ids:
                self._journal.close(entry_id, "polled")
        return items

    def restore(self) -> int:
        """Re-populate pending replies from the journal. Returns how many."""
        if self._journal is None:
            return 0
        survivors = self._journal.replay()
        highest = 0
        with self._lock:
            for rec in survivors:
                try:
                    reply = InboundReply(**rec["payload"])
                except Exception:  # noqa: BLE001 — a record we cannot revive is not fatal
                    continue
                self._pending[reply.app].append(reply)
                self._ids_by_app[reply.app].append(rec["id"])
                highest = max(highest, rec["id"])
        # Continue the id sequence past anything the journal already used, so a
        # restart cannot mint an id that collides with a live record.
        self._ids = itertools.count(highest + 1)
        self._journal.compact(survivors)
        self.replayed = len(survivors)
        return self.replayed
```

Add `import itertools` to the module imports.

## B4 · `__main__.py` — build the journals

In the `serve` branch, before `create_app`:

```python
        from .delivery import Dispatcher
        from .journal import Journal

        queue_dir = Path(state_dir) / "queue"
        log = DeliveryLog(audit_dir=Path(state_dir) / "deliveries")
        inbox._journal = Journal(queue_dir / "inbox.jsonl")   # see note below
        dispatcher = Dispatcher(adapters, log, journal=Journal(queue_dir / "delivery.jsonl"))
        restored, expired = dispatcher.restore(registry)
        inbound_restored = inbox.restore()
        print(f"queue: restored {restored} outbound job(s), {expired} expired; "
              f"{inbound_restored} inbound reply(ies)", flush=True)
```

⚠ **Do not assign a private attribute from outside the class.** Build the `Inbox`
with its journal in `build_runtime` instead, and pass `state_dir` through:

```python
    state_dir = os.environ.get("CHAT_GATEWAY_STATE_DIR", "state")
    from .journal import Journal

    inbox = Inbox(audit_dir=os.environ.get("CHAT_GATEWAY_INBOX_DIR", "inbox-data"),
                  journal=Journal(Path(state_dir) / "queue" / "inbox.jsonl"))
```

(with `from pathlib import Path` lifted to module scope) and in `serve` pass
`dispatcher=dispatcher` to `create_app`, which already accepts it.

## B5 · `service.py` — report it at `/healthz`

Inside `body`, replace the `inbox` / `delivery` entries:

```python
            "inbox": {"pending": inbox.pending_counts(), "dropped": inbox.dropped,
                      "replayed_at_boot": getattr(inbox, "replayed", 0)},
            "delivery": {"pending_jobs": dispatch.pending(),
                         "replayed_at_boot": getattr(dispatch, "replayed", 0),
                         "expired_at_boot": getattr(dispatch, "expired", 0),
                         # Journal lines that did not parse. A torn trailing line
                         # is expected after a power loss and is deliberately not
                         # fatal (journal.py) — but a mechanism whose whole
                         # purpose is surviving something nobody watched must say
                         # when it lost something. Rule #5.
                         "journal_skipped_lines": _journal_skipped(dispatch, inbox)},
```

with a module-level helper beside `_stale_after`:

```python
def _journal_skipped(dispatch, inbox) -> int:
    """Unparseable journal lines across both queues, or 0 when unjournaled."""
    total = 0
    for owner in (dispatch, inbox):
        journal = getattr(owner, "_journal", None)
        if journal is not None:
            total += getattr(journal, "skipped_lines", 0)
    return total
```

And add a `reasons` entry, so a lost record is never merely a number:

```python
        if body["delivery"]["journal_skipped_lines"]:
            reasons.append(
                f"queue journal: {body['delivery']['journal_skipped_lines']} "
                "unparseable line(s) skipped at boot — at least one queued item "
                "was lost to a torn or corrupt write; the JSONL audit files under "
                "the state dir are the recovery record"
            )
```

## B6 · `tests/test_journal.py` (new)

```python
"""Queue durability: the journal, its replay rule, and its compaction."""

import datetime as dt
import json

from chat_gateway.journal import Journal


def _fixed(ts="2026-07-31T12:00:00+00:00"):
    moment = dt.datetime.fromisoformat(ts)
    return lambda: moment


def test_open_then_close_leaves_nothing_to_replay(tmp_path):
    j = Journal(tmp_path / "q.jsonl")
    j.open(1, "notify", {"title": "t"})
    j.close(1, "delivered")
    assert j.replay() == []


def test_open_without_close_survives(tmp_path):
    j = Journal(tmp_path / "q.jsonl")
    j.open(7, "notify", {"title": "t"})
    survivors = j.replay()
    assert [s["id"] for s in survivors] == [7]
    assert survivors[0]["payload"] == {"title": "t"}


def test_attempts_survive_a_restart(tmp_path):
    # Without this a crash-loop resets the backoff ladder every boot and
    # hammers the far end forever.
    path = tmp_path / "q.jsonl"
    j = Journal(path)
    j.open(1, "notify", {"title": "t"})
    j.update(1, 3, "2026-07-31T13:00:00+00:00")
    reopened = Journal(path).replay()
    assert reopened[0]["attempts"] == 3
    assert reopened[0]["next_attempt_at"] == "2026-07-31T13:00:00+00:00"


def test_the_last_update_wins(tmp_path):
    j = Journal(tmp_path / "q.jsonl")
    j.open(1, "notify", {})
    j.update(1, 1, "2026-07-31T12:01:00+00:00")
    j.update(1, 2, "2026-07-31T12:05:00+00:00")
    assert j.replay()[0]["attempts"] == 2


def test_a_torn_trailing_line_is_skipped_and_counted_not_fatal(tmp_path):
    # The expected shape of a power loss. Refusing to boot over a half-written
    # byte is a crash loop on a host running `restart: unless-stopped`.
    path = tmp_path / "q.jsonl"
    j = Journal(path)
    j.open(1, "notify", {"title": "kept"})
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"v": 1, "op": "open", "id": 2, "payl')   # torn
    reopened = Journal(path)
    survivors = reopened.replay()
    assert [s["id"] for s in survivors] == [1]
    assert reopened.skipped_lines == 1


def test_an_unparseable_line_mid_file_is_also_skipped(tmp_path):
    path = tmp_path / "q.jsonl"
    path.write_text(
        json.dumps({"v": 1, "op": "open", "id": 1, "payload": {}}) + "\n"
        "}{ not json at all\n"
        + json.dumps({"v": 1, "op": "open", "id": 2, "payload": {}}) + "\n",
        encoding="utf-8")
    j = Journal(path)
    assert [s["id"] for s in j.replay()] == [1, 2]
    assert j.skipped_lines == 1


def test_a_record_that_is_json_but_not_a_record_is_skipped(tmp_path):
    path = tmp_path / "q.jsonl"
    path.write_text('[1, 2, 3]\n{"no": "op or id"}\n', encoding="utf-8")
    j = Journal(path)
    assert j.replay() == []
    assert j.skipped_lines == 2


def test_compaction_preserves_exactly_the_survivors(tmp_path):
    path = tmp_path / "q.jsonl"
    j = Journal(path)
    for i in (1, 2, 3):
        j.open(i, "notify", {"n": i})
    j.update(2, 1, "2026-07-31T12:01:00+00:00")
    j.close(1, "delivered")
    j.close(3, "failed")
    before = j.replay()
    j.compact()
    after = Journal(path).replay()
    assert [s["id"] for s in before] == [2]
    assert [s["id"] for s in after] == [2]
    assert after[0]["attempts"] == 1
    assert after[0]["payload"] == {"n": 2}


def test_compaction_shrinks_the_file(tmp_path):
    path = tmp_path / "q.jsonl"
    j = Journal(path)
    for i in range(50):
        j.open(i, "notify", {"n": i})
        j.close(i, "delivered")
    fat = path.stat().st_size
    j.compact()
    assert path.stat().st_size < fat
    assert Journal(path).replay() == []


def test_compaction_is_atomic_leaving_no_tmp_behind(tmp_path):
    path = tmp_path / "q.jsonl"
    j = Journal(path)
    j.open(1, "notify", {})
    j.compact()
    assert list(tmp_path.glob("*.tmp")) == []


def test_inline_compaction_fires_at_the_threshold(tmp_path):
    path = tmp_path / "q.jsonl"
    j = Journal(path, compact_after=4)
    for i in range(10):
        j.open(i, "notify", {})
        j.close(i, "delivered")
    # A process that never reboots would otherwise never compact.
    assert path.stat().st_size < 400
    assert Journal(path).replay() == []


def test_a_missing_journal_file_replays_empty(tmp_path):
    assert Journal(tmp_path / "never-written.jsonl").replay() == []
```

## B7 · `tests/test_durability.py` (new) — the queues, end to end

```python
"""Restart survival for both queues — the point of Part B."""

import datetime as dt

import pytest

from chat_gateway.delivery import DeliveryLog, Dispatcher
from chat_gateway.envelope import InboundReply, OutboundMessage
from chat_gateway.inbox import Inbox
from chat_gateway.journal import Journal
from chat_gateway.registry import Identity, Registry, App


class BoomAdapter:
    def send(self, identity, message):
        raise RuntimeError("nope")


class OkAdapter:
    def __init__(self):
        self.sent = []

    def send(self, identity, message):
        self.sent.append((identity.name, message.text))


def _registry():
    ident = Identity(name="ident-a", display="A", mode="webhook",
                     webhook_url_env="SYNTHETIC_ENV_NAME")
    app = App(app_id="app-a", key_env="SYNTHETIC_KEY_ENV", identities=["ident-a"])
    return Registry(identities={"ident-a": ident}, apps={"app-a": app})


def _message():
    return OutboundMessage(identity="ident-a", text="hello")


def test_an_undelivered_job_survives_a_restart(tmp_path):
    reg = _registry()
    path = tmp_path / "delivery.jsonl"
    first = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog(), journal=Journal(path))
    first.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    first.process_due()                       # fails, reschedules
    assert first.pending() == 1

    ok = OkAdapter()
    second = Dispatcher({"webhook": ok}, DeliveryLog(), journal=Journal(path))
    restored, expired = second.restore(reg)
    assert (restored, expired) == (1, 0)
    assert second.pending() == 1


def test_the_attempt_count_survives_so_backoff_is_not_reset(tmp_path):
    reg = _registry()
    path = tmp_path / "delivery.jsonl"
    first = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog(), journal=Journal(path))
    first.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    first.process_due()
    first.process_due()                       # not due yet — attempts stays 1

    second = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog(), journal=Journal(path))
    second.restore(reg)
    assert second._jobs[0].attempts == 1


def test_a_delivered_job_is_not_replayed(tmp_path):
    reg = _registry()
    path = tmp_path / "delivery.jsonl"
    first = Dispatcher({"webhook": OkAdapter()}, DeliveryLog(), journal=Journal(path))
    first.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    first.process_due()
    assert first.pending() == 0

    second = Dispatcher({"webhook": OkAdapter()}, DeliveryLog(), journal=Journal(path))
    assert second.restore(reg) == (0, 0)


def test_a_job_older_than_the_replay_ceiling_expires_rather_than_sending(tmp_path):
    # An alert from three days ago, posted now, actively misleads. Both outcomes
    # are bad; this is the visible one — it lands in the delivery log as expired.
    reg = _registry()
    path = tmp_path / "delivery.jsonl"
    old = dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)
    first = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog(),
                       now_fn=lambda: old, journal=Journal(path, now_fn=lambda: old))
    first.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")

    ok = OkAdapter()
    log = DeliveryLog()
    second = Dispatcher({"webhook": ok}, log, journal=Journal(path))
    restored, expired = second.restore(reg)
    assert (restored, expired) == (0, 1)
    second.process_due()
    assert ok.sent == []
    assert log.query("app-a")[-1]["status"] == "expired"


def test_a_job_whose_identity_left_the_registry_is_not_sent_on_a_stale_grant(tmp_path):
    # Hard rule #4: the registry decides what an app may send as, at send time.
    reg = _registry()
    path = tmp_path / "delivery.jsonl"
    first = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog(), journal=Journal(path))
    first.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")

    narrowed = _registry()
    narrowed.apps["app-a"].identities = []      # grant withdrawn between runs
    ok = OkAdapter()
    second = Dispatcher({"webhook": ok}, DeliveryLog(), journal=Journal(path))
    restored, expired = second.restore(narrowed)
    assert (restored, expired) == (0, 1)
    second.process_due()
    assert ok.sent == []


def test_without_a_journal_the_dispatcher_is_exactly_what_it_was(tmp_path):
    reg = _registry()
    d = Dispatcher({"webhook": BoomAdapter()}, DeliveryLog())
    d.enqueue("app-a", "notify", reg.identities["ident-a"], _message(), "t")
    d.process_due()
    assert d.restore(reg) == (0, 0)
    assert d.pending() == 1


def _reply(app="app-a", text="tapped"):
    return InboundReply(app=app, space="", text=text)


def test_an_unpolled_inbound_reply_survives_a_restart(tmp_path):
    # Decision A makes this jobhunt's ONLY inbound path, and its consumer's host
    # sleeps — a reply can wait hours, across restarts.
    path = tmp_path / "inbox.jsonl"
    first = Inbox(journal=Journal(path))
    first.put(_reply())
    second = Inbox(journal=Journal(path))
    assert second.restore() == 1
    assert len(second.poll("app-a")) == 1


def test_a_polled_reply_is_not_replayed(tmp_path):
    path = tmp_path / "inbox.jsonl"
    first = Inbox(journal=Journal(path))
    first.put(_reply())
    first.poll("app-a")
    second = Inbox(journal=Journal(path))
    assert second.restore() == 0
    assert second.poll("app-a") == []


def test_ids_continue_past_the_journal_so_a_restart_cannot_collide(tmp_path):
    path = tmp_path / "inbox.jsonl"
    first = Inbox(journal=Journal(path))
    first.put(_reply())
    first.put(_reply())
    second = Inbox(journal=Journal(path))
    second.restore()
    second.put(_reply())
    second.poll("app-a")
    assert Inbox(journal=Journal(path)).restore() == 0


def test_without_a_journal_the_inbox_is_exactly_what_it_was():
    inbox = Inbox()
    inbox.put(_reply())
    assert inbox.restore() == 0
    assert len(inbox.poll("app-a")) == 1
```

> If `InboundReply` requires fields beyond `app` / `space` / `text`, build the
> fixture from `envelope.py`'s model rather than adjusting the model. **Use
> synthetic values only** — no real space id.

## B8 · Verify Part B

```bash
python -m pytest -q
python -m pytest -q tests/test_journal.py tests/test_durability.py
```

Then a **real restart**, not only unit tests — the row's own UAT:

```bash
# 1. serve with a state dir, enqueue against an unreachable webhook, SIGKILL
# 2. inspect the journal by eye — it must be readable during an incident
cat state/queue/delivery.jsonl
# 3. serve again; confirm the boot line reports the restore and /healthz agrees
curl -s localhost:8085/healthz | python -m json.tool | grep -A4 '"delivery"'
```

---

# Part C — CG-55 · First NAS deploy and live smoke

⏸ **Merge gate: deploy + secret handling. BUILDER-EXECUTED over SSH**, under the
**standing rules** at the top of this plan — which are not optional and are the
reason this row is safe to execute at all.

This supersedes the earlier "user-executed, CG-15/CG-16 pattern" framing: the
account exists and works, so Builder both runs *and verifies* the deploy instead
of handing over instructions. **The 🛑 list still applies** — most of what could
go wrong on that box is out of scope for this row by construction.

Builder's deliverables: the executed deploy, the observations below, and the
runbook's **§10 Executed** section filled in with **what actually happened**,
including anything that differed from plan. Homelab-side artifacts
(`nas/services/chat-gateway.md`, the `SECRETS.template.md` row, the Homepage
tile, `DASHBOARDS.md`, `restore-chat-gateway.sh`, the captured config) land in
**that** repo, after the box is running, from observed facts — deploy-then-document
is its convention. ⚠ **`capture.sh` is a 🛑**: it rewrites captured state for
**every stack on the box** (*"all ten"* until 2026-08-05 — see the standing-rules
table). Report that it needs running; do not run it. ✅ **It was reported, and the
user ran it on 2026-08-05; the output was read and is clean.** `nas.md` §10 fact 5
carries what it showed and deliberately does not reproduce it.

## C1 · Observation checklist — facts to record, not boxes to tick

| # | Observe | Record |
|---|---|---|
| 1 | container up; `/healthz` on the LAN address | `status` and `reasons`, **verbatim** |
| 2 | tier 1 — one webhook send through the deployed instance | delivered? which identity? |
| 3 | tier 2 — `GATEWAY_ENABLE_PUBSUB=1`; `thread_alive`, `seconds_since_last_poll` moving | **first evidence the NAS's egress reaches Pub/Sub** — no host but the dev box has ever pulled |
| 4 | restart the app; journal replays | the boot line and the `/healthz` `replayed_at_boot` — Part B's proof on real hardware |
| 5 | the captured JSON, **read by eye** | that it holds **zero** secret values |
| 6 | **THE FIRST DRAIN** — see below | the most valuable observation in the arc |

**Item 5 is the gate.** Do not accept `clean. safe to commit.` as the answer —
the spec's §1.2 shows that script's suffix rule cannot see this project's secret
shapes, so the assurance is worth exactly nothing here. Read the file. (Running
`capture.sh` itself is a 🛑 — request it, then read what it produced.)

### C0 · Two prerequisites — check BOTH before anything else

> ⚠ **AMENDED 2026-08-03 — (a) IS NO LONGER A STOP.** The user **deferred** the
> tailnet ACL: still wanted, no longer gating this deploy. The paragraph below is
> kept as the record of D2 as decided on 2026-07-31; **this note is the currency
> pointer.** Do **not** stop on (a). Instead **observe and record** whether the
> ACL is applied, and write the answer into the runbook's *Executed* section, so
> the deploy's exposure posture is a stated fact rather than an assumption. The
> decision, the user's reasoning, and what the deferral accepts live in **one**
> place: `docs/BUILDER_QUEUE.md` § CG-55, *"Two user decisions, 2026-08-03"*. Do
> not restate them here.
> ⚠ **Read that section before building Part C regardless** — it carries a second
> decision of the same day that this Part must BUILD: **the published port binds
> the LAN interface, not `0.0.0.0`.** The custom-app JSON **above** — in Part A,
> under §A6's *§5 The compose document*, not in this Part — still says
> `"ports": ["8085:8085"]`; that is the `0.0.0.0` form and it is what changes.
> **(b) is untouched and still a STOP.**
>
> ⚠ **RE-DATED 2026-08-05. Part C RAN — everything in this note is now past
> tense, and two of its clauses have resolved.** (a) was observed and recorded:
> the ACL was **not** applied (`docs/deploy/nas.md:654`), which is exactly the
> "stated fact rather than an assumption" this note asked for. The LAN bind was
> built and **demonstrated** — `curl` against both loopback and the tailnet
> address on the box is refused (`nas.md:787`). **(b) is satisfied for that run**
> — see the note under (b) below.
>
> ⚠ **This note called itself *"the currency pointer"*, and that is the shape
> CG-79 named as the one that ages worst.** Two sentences in this repo aged worse
> than any other and both certified their own currency; this is a third of the
> same family, and it survived CG-79's sweep for a reason worth recording: the
> phrase is **wrapped across a line break** (`currency` / `pointer`), so a
> line-oriented `grep` for the string found the queue's copy and not this one.
> **A self-certifying sentence is read as verified rather than as merely
> current** — it gets examined less — and this one additionally could not be
> found by the tool that was looking for exactly it. The label is left in place
> with this attached, because deleting it would remove the only warning that the
> shape recurs.

**(a) The homelab tailnet ACL must already be applied (D2).** The endpoint is
fenced from the start, never afterwards. ⚠ **This is homelab-repo work a
chat-gateway Builder cannot do** — if it is not done, **STOP and report**; do not
deploy and fence later. It is validated through that repo's
`network/tailscale-acl.hujson` `tests` block, which the Tailscale console
enforces on save.

**(b) CG-61 must be in the live registry (D1).** This Part streams
`config/registry.yaml` to the box. If the opt-out is not in that file, the
deployed gateway runs `allow_inbound: true` and the first drain writes
FamilyWorkspace content to disk — the exact outcome D1 exists to prevent. **Make
it fail-closed, not a memory test:**

> ✅ **SATISFIED, and the sentence above is now FALSE about production — corrected
> 2026-08-05 (CG-59's Planner; routed here by CG-79).** The operator edit landed
> **2026-08-03** (`config/registry.yaml` mtime `2026-08-03T20:34:06Z`), the
> pre-flight below **ran on the box on 2026-08-05 and PASSED**
> (`{aiteam-harness: False, job-hunter: True, aitrader: False}`,
> `docs/deploy/nas.md:644`)~~, and the gateway has been serving since~~. **The
> deployed gateway runs `allow_inbound: false` for `aiteam-harness`.**
>
> ⛔ **THAT STRUCK CLAUSE IS FALSE — corrected 2026-08-11.** *"Serving since"*
> asserts continuity and there was none: `dockerd` on the NAS died on
> **2026-08-10** and the gateway was **absent for ~23 hours** before being
> recovered on 2026-08-11. **The registry finding is untouched** — the pre-flight
> really did run and pass on the box on 2026-08-05, and the deployed gateway really
> does run `allow_inbound: false` for `aiteam-harness`. ⚠ **The shape is worth
> naming, because it is the same one this correction block already diagnoses from
> the other end:** the load-bearing half of the sentence was **measured** and the
> trailing half was **assumed** — dropped in as an aside, in a paragraph about
> something else — and it is the assumed half that rotted. One home for the outage:
> `docs/deploy/nas.md` §10's **2026-08-11** entry.
>
> ⚠ **Why this line is the one to fix first: it is security-shaped and it is
> written in the present tense about a gateway that now exists.** When this was
> drafted, *"the deployed gateway"* named a hypothetical. It names a real host
> now, and a reader who drops the conditional — which is what a reader of a
> two-line antecedent does — reads a live claim that a production gateway is open
> inbound on a hard-rule-#6 path. That is a claim about the posture of a running
> system, and it is wrong.
>
> ⚠ **It is wrong in the SAFE direction, and that is luck, not design — say so
> rather than let it read as a near-miss that was handled.** Nothing about this
> sentence made the outcome safe. Its truth value gated nothing: had the operator
> edit *not* landed, the prose here would read **identically**, and the deploy
> would still have aborted — because the thing that stopped it is the script below,
> which re-derives the map from the file every time and cannot go stale. The
> sentence is the part that could rot; the executable check one paragraph down is
> the part that could not. **That asymmetry is the whole finding**, and it is the
> same one CG-79 recorded from the other end: the CG-61 row survived four days of
> a false status line only because somebody had written *"re-measure rather than
> trusting this line"* into it.
>
> **The paragraph is kept, not rewritten,** because it is still the correct
> instruction for the *next* deploy — a fresh box, a restored `.env`, a second
> project. The prerequisite is satisfied **for the 2026-08-05 run**, not
> permanently: `config/registry.yaml` is gitignored, so nothing in this repo can
> hold it satisfied.

```bash
python - <<'PY'
import sys; sys.path.insert(0, "src")
from chat_gateway.registry import load_registry
r = load_registry("config/registry.yaml")
expected = {"aitrader": False, "aiteam-harness": False, "job-hunter": True}
actual = {a: app.allow_inbound for a, app in r.apps.items()}
assert actual == expected, f"STOP — registry opt-in map is {actual}, expected {expected}"
print("pre-flight OK:", actual)
PY
# Non-zero exit => do NOT transfer, do NOT deploy.
```

## C1a · Item 6 — the first drain

The gateway has **never** pulled while the Chat app was in four spaces
(spec §0.1). The first successful poll drains **up to 24 hours** of accumulated
backlog — the subscription's `--message-retention-duration` — from all four at
once. Sample `/healthz` **immediately before and after**:

| Field | Why it is the interesting number |
|---|---|
| `events_seen` | the backlog's real size — the first measurement of this deployment's inbound volume, ever |
| `suppressed_opt_out` | now pooled across **three** opted-out spaces (D1), so it no longer decomposes to aitrader. Its magnitude is what D2's residual **LAN** exposure is judged against |
| `inbox.pending` | **`job-hunter` only** now — D1 closed the other open path |
| `inbox.dropped` | **non-zero on the first drain means the 1000-item cap was hit by the backlog** |
| **which event types arrived** | spec §0.1.2's question. ⚠ **Now about `job-hunter` only** — D1 made this a capacity-and-shape question about the one open tenant, not a privacy question about a family space. **Only the box can answer it.** |
| `unparseable_seen`, `interactions_without_action_id` | three of these spaces have never had an event parsed from them |

⚠ **Record counts and app ids only — never a space id, a sender identity, or
message content.** The same discipline `/healthz` itself follows, for the same
reason, and this write-up lands in a public repo.

## C2 · What must NOT happen

- **The standing rules at the top of this plan apply in full** — the 🛑 list, the
  fail-closed app-name check, and the stdin-only secret transfer.
- No secret in `custom_compose_config`. If one is there, stop and fix the layout
  before anything is captured — a capture commits it to a sibling repo.
- No `network_mode: host`. The gateway needs one published port, not the box's
  whole network namespace.
- No change to any existing NAS app's config, and **no restart of any other
  `ix-*` container** — one of them is claude-mem's Postgres.
- Do not reach for **any `chat-gateway-sa*.json` that is not
  `chat-gateway-sa-gw.json`** — those belong to the deleted `chat-gateway-prod`
  and authenticate to nothing.
  ⚠ **REWORDED 2026-08-05, not dropped.** This named the path
  `iac/chat-gateway-sa.json`, and **that file was deleted by the user on
  2026-08-05**, so a warning phrased around it now describes nothing. The hazard
  outlived the path: copies sit in old checkouts, backups and clones, and
  `iac/gcloud-setup.sh` and its `.ps1` sibling still default `KEY_FILE` to that
  exact filename, so re-running setup writes it back. **Confirm by the key's own
  `project_id`, never by its name** — which is what the deploy actually did
  (`nas.md` §10 deviation 7). CG-55's row set the rewording-not-dropping condition
  in advance; CG-79 carried it out across the rest of the repo and routed this
  file here.
- **Do not run `capture.sh`.** Cross-repo write covering **every stack on the box**
  (*"all ten"* until 2026-08-05 — see the standing-rules table). ✅ Requested and
  run by the user 2026-08-05; output clean.

---

# Part D — CG-56 · Inbox delivery semantics ✅ APPROVED (D3)

**Unblocked** by user decision D3 (spec §7). The published contract must keep
working **unchanged** for any caller that does not ask for acks — a requirement
of the approval, not an implementation preference.

The reason, recorded so it is not re-argued: decision A makes polling jobhunt's
**only** inbound path, so a read lost mid-processing is a **lost Approve**.
Tolerable when the inbox was a fallback behind push; not now.

## D1 · Opt-in ack mode, so nothing breaks

Default stays clear-on-read. Ack mode is explicit per request, because flipping
the default silently turns any non-acking caller's queue into one that grows
forever — the worse failure on a host that now runs continuously.

```python
    @app.get("/v1/inbox")
    def poll_inbox(ack: bool = True, app_id: str = Depends(current_app_id)):
        """`ack=true` (default) clears on read — at-most-once, the v0 contract.

        `ack=false` LEAVES the replies pending and returns each with an `_id`;
        the caller then POSTs /v1/inbox/ack with the ids it durably stored. That
        is at-least-once, which is what the jobhunt contract's R3 already assumes
        — it demanded a `dedupe_key` and committed the tenant to idempotent
        handling precisely because Pub/Sub is at-least-once. Same pull/ack idiom
        as `PubSubPuller`, one layer out.
        """
```

with `Inbox.peek(app_id)` alongside `poll`, and `Inbox.ack(app_id, ids)` closing
those journal records. The full method bodies mirror `poll`/`put` above; the
journal `close` status becomes `"acked"`.

## D2 · Documents

`README.md`'s endpoint row, `docs/integration-guide.md` § *Inbound replies*, and
**`docs/consumers/aitrader.md`'s comparison row — which cites `service.py` line
numbers that will move.** Re-derive those line numbers by reading the file; do
not adjust them by arithmetic.

`tests/test_service.py:99`'s `# poll clears` assertion stays valid (the default is
unchanged) and gains a sibling proving `ack=false` does not clear.

---

# Part E — CG-57 · jobhunt: `callback_url` → passive inbox polling

Registry and documentation only. **No code path is deleted** —
`CallbackForwarder` and R7 stay for any future always-on tenant, per hard rule #6
and the user's explicit instruction.

## E1 · `config/registry.example.yaml`

Remove `callback_url` and `unreachable_message` from the `job-hunter` app; keep
`allow_inbound: true` and `allowed_users`. Add:

```yaml
  job-hunter:
    key_env: CHAT_GATEWAY_API_KEY__JOB_HUNTER
    identities: [job-hunter]
    allow_inbound: true
    # Passive inbox polling, not callback push (user decision 2026-07-31).
    # Push couples the gateway to a consumer's deployment topology — its address,
    # its port, its liveness. Polling couples it to nothing, which is why this
    # holds whichever host jobhunt's receiver ends up on.
    # `callback_url` and `unreachable_message` are therefore ABSENT rather than
    # blank: R7's in-thread notice fires from callback exhaustion, so with no
    # callback there is no exhaustion and the field would read as active while
    # never being able to fire.
    # Both remain supported for an always-on tenant — hard rule #6 names BOTH
    # inbound paths and neither is being removed.
    allowed_users: ["<one-authorized-address>"]   # placeholder — real value only in the ungitignored registry
```

## E2 · `allowed_users` and `unreachable_message` — the decided semantics

**Write this into the docs, do not leave it inferable.**

- **`allowed_users` (R4) is unchanged in force.** It is evaluated at **ingress**,
  in the subscriber's authorization block, before anything is enqueued. An
  unauthorized tap is still refused in-thread and still never reaches any queue,
  so it never appears in the inbox to be polled. The `/healthz`
  `suppressed_not_authorized` counter already describes exactly this ("candidate
  apps that declined an event"). **Only the verb changes: "never forwarded" →
  "never enqueued."**
- **`unreachable_message` (R7) becomes inert for this tenant and is removed from
  its entry**, for the reason in E1. The **field and R7 stay in the contract** for
  push-path tenants.
- **What replaces R7's guarantee under polling: nothing at the gateway, and that
  is correct.** The gateway cannot distinguish "jobhunt is asleep" from "jobhunt
  has crashed" — both look like nobody polling — and a detector would mean the
  gateway holding an expectation about a consumer's schedule, which is consumer
  semantics and against hard rule #1. **The gap moves to jobhunt**, whose own J14
  doctrine already demands it; its `pipeline/health.py` watchdog is the natural
  home. The gateway-side observable is `/healthz` → `inbox.pending`, which rises
  when nobody drains — operator material, not a tenant guarantee.

## E3 · Documents to revise

| File | What changes |
|---|---|
| `docs/consumers/jobhunt.md` | R3 row, R4 verb, R7 row, tenant-config snippet, acceptance table |
| `docs/consumers/jobhunt-handoff.md` | §4 (R3), §5 (R4 verb), §7 (R7 — **link, do not restate, CG-52's rule**), §9.3 registry block, §10 the live blocker → **moot** |
| `docs/integration-guide.md` | the `callback_url` opt-in paragraph gains choose-your-path framing |
| `config/registry.example.yaml` | E1 |

**`docs/consumers/aitrader.md` is checked and left alone** unless its wording
forces a change. aitrader's guarantee rests on `allow_inbound: false` locking it
out of *every* path, and narrowing another tenant does not touch that. CG-27
already had to remove a false claim from that file about this mechanism's
existence — **do not introduce its mirror image.**

**The `8710` / `8763` port mismatch becomes moot** and is recorded as such: there
is no receiver to point at. Do not "fix" the port; delete the question.

## E4 · What jobhunt must change — recorded, not actioned

`D:\prj\jobhunt` is **READ ONLY**. Record in the handoff, for jobhunt to act on:

- R1's *"registered callback URL"*; R3 entirely (forwarding → polling + ack).
- R6's *"the callback returns the chosen value"* → the inbox event carries it.
  The selection-widget mechanism is unaffected.
- R7 → jobhunt-side poller staleness detection (E2).
- R8's *"HTTP on the appserver LAN/tailnet"* → outbound HTTP from jobhunt only.
- R9's *"the new inbound callback"* → the new inbound poller.
- Its own open port question can be closed as **moot**.
- **No code to delete: the receiver was never built.** A repo-wide search for any
  gateway or callback symbol in `*.py` returns nothing, and `review_ui.py`'s
  route table has no such route. This is a contract correction *before first
  use*, not a migration.

## E5 · Tests

```python
def test_the_registry_loads_a_polling_tenant_with_no_callback_url():
    # The push fields are ABSENT, not blank — and that is still valid config.
    ...

def test_an_unauthorized_sender_is_refused_at_ingress_and_never_enqueued():
    # R4 is unchanged in force; only the verb in the docs changed.
    ...

def test_a_push_path_tenant_still_validates_and_still_forwards():
    # Proves nothing was ripped out. Hard rule #6 names BOTH inbound paths.
    ...
```

Build the third from the existing forwarder tests so it genuinely exercises
`CallbackForwarder`, not a stub — its whole job is to prove the path survives.

---

# Part F — CG-58 · Structured adapter failures and `Retry-After`

No merge gate. **Touches `adapters/` — no ⚠ flag may be cleared, added or
reworded.**

## F1 · `src/chat_gateway/retry_policy.py` (new)

```python
"""Shared retry policy: what a failure MEANS, separately from how it is logged.

Two retry paths existed with two ladders and no shared notion of "is this worth
retrying at all": `delivery.py`'s (0, 30, 120, 600, 3600) and `forwarder.py`'s
(0, 3, 7). Neither read `Retry-After`, and neither COULD — the adapters rendered
the status into a message string and kept no attribute, so `Dispatcher` caught a
bare `Exception` and could not tell 429 from 403.

The consequence worth naming is not the missing `Retry-After`. It is that a 403 —
webhook deleted, app removed from the space, key revoked — burned the full
outbound ladder, over an HOUR of calls that could never succeed, before reporting
`failed`. That is a defect in our own logic, observable without any Google error
response, and it makes the gateway noisiest exactly when a credential has been
revoked.

⚠ `Retry-After` IS SERVER-CONTROLLED BYTES. It is parsed to a float here and the
raw string is never stored, logged, or interpolated into any message. That is
CG-33's lesson applied on first use rather than after the fact: `PubSubError`
read `resp.reason_phrase` off the wire — httpcore fills it from the HTTP/1.1
status line — and had to be corrected to a local lookup. A new header read is a
new instance of the same hazard.
"""

from __future__ import annotations

import datetime as dt
from email.utils import parsedate_to_datetime

#: Statuses worth another attempt. Everything else in 4xx is permanent: 401, 403
#: and 404 are not going to start succeeding in an hour.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

#: Ceiling on an honoured `Retry-After`, outbound. An absurd value must not park
#: a job past the point anyone still cares about it.
RETRY_AFTER_MAX_S = 3600.0


def parse_retry_after(value, now: dt.datetime | None = None) -> float | None:
    """RFC 9110 permits BOTH forms: delta-seconds, and an HTTP-date.

    Returns a non-negative float, or None if absent or unparseable. NEVER RAISES:
    a malformed header is not a reason to fail a send differently than it would
    have failed anyway.
    """
    if not value:
        return None
    text = str(value).strip()
    if text.isdigit():
        return float(text)
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    now = now or dt.datetime.now(dt.timezone.utc)
    return max(0.0, (when - now).total_seconds())


def is_permanent(status_code: int | None) -> bool:
    """A 4xx we should stop on rather than retry."""
    if status_code is None:
        return False
    return 400 <= status_code < 500 and status_code not in RETRYABLE_STATUS


def next_delay(status_code: int | None, retry_after_s: float | None,
               attempts: int, backoff, *, cap: float = RETRY_AFTER_MAX_S) -> float | None:
    """Seconds to wait before the next attempt, or None meaning STOP NOW.

    None covers both a permanent status and an exhausted ladder; the caller
    treats both as terminal and does not need to know which, though it reports
    which.

    `Retry-After` is honoured as max(ladder, retry_after) — NEVER SHORTER than
    our own schedule, so a hostile or buggy `Retry-After: 0` cannot turn a retry
    into a hot loop against Google.
    """
    if is_permanent(status_code):
        return None
    if attempts >= len(backoff):
        return None
    delay = float(backoff[attempts])
    if retry_after_s is not None:
        delay = max(delay, min(float(retry_after_s), cap))
    return delay
```

## F2 · The two error classes carry structure

`PubSubError` already does; this brings its siblings to the same shape — the
direction CG-23 and CG-33 already moved this family.

In `adapters/webhook.py`, append to `WebhookDeliveryError` (keep the existing
docstring **in full** — it is load-bearing and CG-23-measured):

```python
    def __init__(self, message: str, *, status_code: int | None = None,
                 retry_after_s: float | None = None):
        super().__init__(message)
        #: For retry_policy. The MESSAGE keeps the human-readable status; these
        #: exist because parsing a message string to decide a retry is how the
        #: 403-burns-the-ladder defect survived.
        self.status_code = status_code
        #: Parsed seconds ONLY. The raw header never reaches this object.
        self.retry_after_s = retry_after_s
```

and at the non-200 raise site, keeping the existing comment block:

```python
            reason = httpx.codes.get_reason_phrase(resp.status_code)
            raise WebhookDeliveryError(
                f"webhook POST failed for {identity.name}: "
                f"HTTP {resp.status_code} {reason}".rstrip(),
                status_code=resp.status_code,
                retry_after_s=parse_retry_after(resp.headers.get("Retry-After")),
            )
```

with `from ..retry_policy import parse_retry_after` at the imports.

Identical treatment for `ChatApiError` and both of its raise sites in
`adapters/chat_api.py` (`send` and `send_text`).

⚠ **Do not touch any `⚠ flag CLEARED` / `⚠ LIVE-UNVERIFIED` / `⚠ SHAPE-VERIFIED`
sentence in either file.** The `send_text` non-200 branch's documented asymmetry
(status only, no reason phrase) is **deliberate** and CG-23 explicitly declined to
change it — add the attributes without touching the message.

## F3 · Both retry paths consult the policy

`delivery.py` — `process_due`'s except branch:

```python
            except Exception as exc:  # noqa: BLE001 — categorize, retry or fail
                job.attempts += 1
                delay = next_delay(getattr(exc, "status_code", None),
                                   getattr(exc, "retry_after_s", None),
                                   job.attempts, self._backoff)
                if delay is None:
                    if is_permanent(getattr(exc, "status_code", None)):
                        # Do not burn the ladder on a status that cannot recover.
                        detail = f"permanent failure on attempt {job.attempts}: {exc}"
                    else:
                        detail = f"gave up after {job.attempts} attempts: {exc}"
                    self._finish(job, "failed", detail)
                else:
                    job.next_attempt_at = now + dt.timedelta(seconds=delay)
                    if self._journal is not None:
                        self._journal.update(job.entry_id, job.attempts,
                                             job.next_attempt_at.isoformat())
                    self._log.record(job.source, job.kind, job.title, "retrying",
                                     f"attempt {job.attempts}: {exc}", entry_id=job.entry_id)
```

**The exhausted-ladder string is preserved byte for byte** — existing tests assert
on it, and the new permanent case gets its own wording rather than overloading
one message with two meanings.

`forwarder.py` — same shape, with the tenant-callback horizon:

```python
#: A tenant asking the gateway to wait longer than this has, for this path,
#: failed: a human tapped a button and is waiting. Beyond it, R7's in-thread
#: notice is the honest answer.
CALLBACK_RETRY_AFTER_MAX_S = 30.0
```

`resp.status_code` is already in hand there, so the forwarder reads
`resp.headers.get("Retry-After")` directly and calls `next_delay(...,
cap=CALLBACK_RETRY_AFTER_MAX_S)`; `None` means exhaustion → `_fail_loudly`.

Update `forwarder.py`'s docstring — carefully. **CG-31 and CG-42 both corrected
this exact docstring**; it now states `BACKOFF_S` as gaps and links
`docs/consumers/jobhunt-handoff.md` §7 for the measured table. **Add a clause,
carry no figures, and keep the link** — CG-52's rule.

## F4 · Tests — `tests/test_retry_policy.py` (new)

```python
"""Retry policy: what a failure means, and what `Retry-After` is allowed to do."""

import datetime as dt
from email.utils import format_datetime

import pytest

from chat_gateway.retry_policy import (
    RETRY_AFTER_MAX_S, is_permanent, next_delay, parse_retry_after)

LADDER = (0, 30, 120, 600, 3600)


@pytest.mark.parametrize("status", [401, 403, 404, 400, 422])
def test_a_non_retryable_4xx_is_permanent(status):
    # The defect this row exists for: a 403 used to burn 30s + 2m + 10m + 1h.
    assert is_permanent(status)
    assert next_delay(status, None, 1, LADDER) is None


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_retryable_statuses_still_use_the_ladder(status):
    assert not is_permanent(status)
    assert next_delay(status, None, 1, LADDER) == 30


def test_a_transport_error_with_no_status_still_uses_the_ladder():
    assert next_delay(None, None, 2, LADDER) == 120


def test_an_exhausted_ladder_stops():
    assert next_delay(429, None, len(LADDER), LADDER) is None


def test_delta_seconds_is_parsed():
    assert parse_retry_after("120") == 120.0


def test_an_http_date_is_parsed():
    now = dt.datetime(2026, 7, 31, 12, 0, tzinfo=dt.timezone.utc)
    later = format_datetime(now + dt.timedelta(seconds=90))
    assert parse_retry_after(later, now=now) == pytest.approx(90.0, abs=1.0)


def test_a_past_http_date_clamps_to_zero_not_negative():
    now = dt.datetime(2026, 7, 31, 12, 0, tzinfo=dt.timezone.utc)
    assert parse_retry_after(format_datetime(now - dt.timedelta(hours=1)), now=now) == 0.0


@pytest.mark.parametrize("value", ["", None, "soon", "-5", "12x"])
def test_a_malformed_header_is_none_and_never_raises(value):
    assert parse_retry_after(value) is None


def test_retry_after_is_honoured_when_longer_than_the_ladder():
    assert next_delay(429, 300.0, 1, LADDER) == 300.0


def test_retry_after_zero_cannot_shorten_the_ladder_into_a_hot_loop():
    # A hostile or buggy header must not turn a retry into a hammer.
    assert next_delay(429, 0.0, 1, LADDER) == 30


def test_an_absurd_retry_after_is_clamped():
    assert next_delay(429, 999_999.0, 1, LADDER) == RETRY_AFTER_MAX_S


def test_the_callback_horizon_clamps_shorter():
    # A human tapped a button; an hour is not a wait, it is a failure.
    assert next_delay(429, 600.0, 1, (0, 3, 7), cap=30.0) == 30.0
```

## F5 · Tests — the adapters carry it, and never carry the string

Extend the existing adapter tests (`MockTransport`, as they already do):

```python
def test_a_429_carries_its_status_and_parsed_retry_after():
    # Through the REAL adapter, not a reimplementation.
    ...
    assert exc.status_code == 429
    assert exc.retry_after_s == 120.0


def test_the_raw_retry_after_string_reaches_no_message_log_or_attribute():
    # CG-33's lesson, applied on first use: the header is server-controlled.
    # Drive a hostile value and assert it appears NOWHERE.
    hostile = "120; key=SYNTHETICKEYVALUE&token=SYNTHETICTOKENVALUE"
    ...
    assert "SYNTHETICKEYVALUE" not in str(exc)
    assert "SYNTHETICTOKENVALUE" not in repr(exc.__dict__)
    assert exc.retry_after_s is None      # unparseable -> None, not the string
```

And a dispatcher-level test proving the headline defect is fixed:

```python
def test_a_403_fails_on_the_first_attempt_instead_of_burning_the_ladder():
    # Before: 5 attempts across 0s / 30s / 2m / 10m / 1h. After: one.
    ...
    assert adapter.calls == 1
    assert log.query("app-a")[-1]["status"] == "failed"
    assert "permanent" in log.query("app-a")[-1]["detail"]
```

## F6 · What Part F does NOT claim

State this in the PR body, in these words: **every branch this touches is one no
Google error response has ever exercised.** The tests drive fakes. That is a
stronger suite, **not** evidence against Google, and **no ⚠ flag is cleared,
added or reworded.** For the current residue, link `CLAUDE.md`'s verification
ledger — **do not restate it.**

---

# Part G — CG-59 · Long-run observation and a deployed `/healthz`

~~Depends on Part C. The soak clock starts when C lands.~~
✅ **Part C landed 2026-08-05 (`4ddd6f5`)** ~~**and the gateway has been serving
since. Nothing blocks this Part; the clock is already running.**~~

> ⛔ **BOTH STRUCK CLAIMS ARE FALSE — corrected 2026-08-11, and this Part must be
> read against the correction rather than the header.**
>
> **The gateway has not been serving since.** `dockerd` on the NAS died on
> **2026-08-10** — SIGKILLed one second after a start attempt, then latched by
> systemd's *"start request repeated too quickly"*, which is how a one-second
> failure became a **~23 hour** absence. It was not this app: `app.query` returned
> `[]` for **all 11 stacks**. Recovered 2026-08-11, data intact. ⛔ **The finding
> that outranks the outage: nothing told anyone.** This project has a dead-man
> switch for *tenants'* silence and **no monitor for its own absence** — `/healthz`
> cannot report that it is not answering. **CG-84.**
>
> **The clock is not running; it stopped on 2026-08-06.** Both streams are dead and
> **final**: the dev-box `/healthz` half ran **24 h 12 m**, the NAS memory half
> **25.2 h of a 72 h ceiling**. ✅ The memory half is a **clean** answer to its own
> question — flat, no leak, no fd or thread growth — **over 25 h, not 72 h.**
> ⚠ Both died the same evening ~90 minutes apart on **two different hosts**: an
> unexplained possible common cause, recorded as an **open question**, filed as
> **CG-85**, whose subject is that long-run evidence needs a capture that survives
> a host event.
>
> ⛔ **And the fallback evidence is GONE — LOST, not SPENT.** The container's
> uptime streak did not survive the outage; last **observed** alive 2026-08-06,
> ~25 h witnessed. **CG-82 task 1 — the `docker inspect` before CG-80's rebuild —
> is MOOT**: by the time the rebuild ran there was nothing left to spend.
> ⚠ **So "nothing blocks this Part" is now wrong in the other direction too** — a
> credible re-run is blocked on CG-85. **Every number has one home:
> `docs/deploy/nas.md` §11, and §10's 2026-08-11 entry.**

> ## G0 · ⚠ REFRESHED 2026-08-05 — this Part was written 2026-07-31, before eight PRs and the deploy
>
> **Refreshed the way Part A was refreshed for CG-53** (#64 found ten drifts
> across nine merged PRs, two of which would have failed at runtime). **Twelve
> drifts here.** They are listed rather than silently fixed, because the point of
> the Part A precedent is that a plan written before the code it plans against
> *ages*, and the count is the evidence.
>
> | # | Part G said | Measured 2026-08-05 | Bite |
> |---|---|---|---|
> | 1 | the return is at `service.py:469-471` | **`service.py:1291-1293`.** Lines 469-471 are now the **`GET /v1/heartbeat/{source}` handler** — a different endpoint entirely | ⚠ **runtime.** A line-anchored edit lands in the wrong route. Exactly CG-69's finding: **8 of 14** line citations in the live contracts point at the wrong code, while name-anchored ones are 0 of 8 wrong. **Anchor on `@app.get("/healthz")`, never on a number** |
> | 2 | `inbox.pending` is a number to record | **`inbox.pending_counts()` — a `dict[str, int]`, per app** | ⚠ **runtime.** A sampler that treats it as a scalar (a CSV column, a `max()`) breaks or silently coerces `{}` to something plausible |
> | 3 | record `thread_alive` / `thread_started` | there are **four** such pairs now — `subscriber`, `delivery`, `heartbeats`, `retention` | ⚠ **defeats the soak.** Sampling only the subscriber's reproduces the exact blindness **CG-72** was filed to fix |
> | 4 | G3: both audit trails are *"never pruned"* | **`inbox-data/` IS pruned** since **CG-68** (2026-08-02) — 30 days, 7 for `_unrouted`, `0` disables. `state/deliveries/` is unpruned **by decision** (ADR-0002 **D7**) | ⚠ **would have shipped a wrong conclusion.** A Builder measuring "growth of an unpruned trail" measures a trail that is being swept |
> | 5 | G3: *"propose a retention rule; do not implement one"* | the rule **exists and ships**. D5's *"decide at CG-59"* was decided earlier, as CG-68's sign-offs A2/A3/A5 | the row would propose what already exists |
> | 6 | — | `/healthz` has a whole **`retention`** block (`files_deleted`, `delete_errors`, `sweep_failures`, `consecutive_sweep_failures`, `audit_dir_configured`, `last_sweep_at`, `thread_alive`) that answers G3 directly | absent from G2's list |
> | 7 | — | **CG-74/75/76** added `pass_failures`, `consecutive_pass_failures`, `delivery_failures`, `audit_write_errors`, `journal_write_errors`, `journal_skipped_lines`, `scan_failures`, `alerts_undeliverable`, `checks_undeliverable`, `checks_orphaned` | absent from G2's list. `audit_write_errors` is the **disk-full** counter, on the row whose other half is disk growth |
> | 8 | `seconds_since_last_poll` implicitly tracks the 5 s interval | **it sawtooths to ~24 s** — `pull()` sends no `returnImmediately`, so Pub/Sub long-polls an empty subscription (`nas.md:693`) | ⚠ **runtime.** A soak alarming on "max ≫ interval" fires on **every** sample. The budget is `stale_after_seconds`, measured **300** |
> | 9 | the spec's §4.7: *"the subscription is no longer quiet … a materially stronger claim than a quiet loop staying alive"* | **`events_seen: 0`, `suppressed_opt_out: 0`, `suppressed_not_authorized: 0` at deploy** (`nas.md:759`). It was quiet | ⚠ **the sign-off would have overclaimed** — see G2's pass/fail |
> | 10 | §4.7: *"two spaces generating suppression traffic and two enqueueing"* | after **D1**, **three** spaces are opted out and **one** enqueues | wrong on its own terms, independent of drift 9 |
> | 11 | §4.7: *"the observation half is user-executed"* | CG-55 ran **Builder-executed over SSH**, and a soak is `curl`-and-record — squarely ✅ *"read-only probing, unattended"* on §4.3.1's table | see G2's *Who runs it* |
> | 12 | — | ~~the homelab **Homepage tile now exists** and its `siteMonitor` probes **plain `/healthz`** (PR #21)~~ ⛔ **FALSIFIED 2026-08-11: it did not exist.** `services.yaml` on the box held **eight** NAS tiles and chat-gateway was not one of them | ~~⚠ **G1 is now urgent, not preventative** — see G1~~ ⛔ **the urgency was real and the reason given for it was not** — see the note below this table |
>
> ⚠ **Drifts 9 and 10 are the ones to read twice.** They are not stale prose; they
> are a **plan instructing its executor to make a claim the deploy has already
> falsified.** §4.7 tells this row to say the soak is stronger than a quiet-loop
> result *because* the subscription is busy — and the first measurement from the
> box says it is not busy. **A ledger sign-off argued on that basis would be
> asking the user to retire a ⚠ flag on a premise this repo can already disprove.**
> G2 replaces the claim with the evidence.
>
> ⛔ **DRIFT 12 WAS ITSELF A DRIFT — corrected 2026-08-11, and this is the one that
> should sting.** §G0 exists because *"a plan written before the code it plans
> against ages"*, and its remedy is **re-measure, do not read**. Drift 12 was
> entered as a finding *from* that exercise — and it was never measured. It was
> read off an **open pull request in another repo**, in the present tense, as
> though authoring a tile and serving one were the same state. Measured on the box
> 2026-08-11: `/mnt/datapool/apps/homepage/config/services.yaml` carried **eight**
> tiles in its NAS group and **chat-gateway was not among them.** Whether PR #21
> merged is not readable from this repo and is **not asserted either way**; the
> live file is what was measured. **The mechanism that is supposed to catch exactly
> this produced the error** — because the thing being checked was in a repo §G0
> cannot reach, and nothing in the drift-audit habit says *stop when the evidence
> is out of reach*. The chain's origin, and the fullest correction, is the spec's
> **§4.1 `docs/deploy/nas.md` deliverable bullet — the PR #21 ✅.**
>
> ⚠ **Do not read the correction as "so G1 was not urgent."** It argued the
> **milder** of two failures. A tile on the plain form is green while inbound is
> dead; **no tile at all is nothing while the gateway is gone** — the state the box
> was in for ~23 hours from 2026-08-10, with no human told (**CG-84**).
> ✅ **G1's remedy shipped anyway and its ORDER survived its own premise:**
> rebuild → verify → point at the strict form, followed 2026-08-11, except that
> the third step was **create**, not repoint, and the verify step **could not be
> completed** (see §G1).

## G1 · `?strict=1` — the deployed-only finding

```
src/chat_gateway/service.py   the sole `return JSONResponse(...)` inside the
                              `@app.get("/healthz")` handler — status_code=200,
                              hardcoded, always
```

⚠ **Anchored on the decorator, not on a line number.** This block read
`service.py:469-471` from 2026-07-31 until 2026-08-05; those lines are now the
`GET /v1/heartbeat/{source}` handler. Locate it with
`grep -n 'JSONResponse' src/chat_gateway/service.py` — there is exactly **one**
match in the file, which is why the anchor is safe and the number was not.

Hardcoded 200, always — including when `status` is `degraded`. Correct for a
hand-run gateway (you read the JSON); a real gap for a deployed one, because
Homepage's `siteMonitor` and container health checks judge by **status code**.
~~The tile is~~ ⚠ ***any* `siteMonitor` on the plain form would be** — corrected
2026-08-11, and the correction below says why — **green while inbound is dead** —
the claude-mem hardcoded-health-check failure, one layer up, against an endpoint
that is itself scrupulously honest. `/healthz` is not lying; the dashboard reading
it cannot hear it.

> ⚠ **Only the SUBJECT of that sentence was wrong, which is why two words are
> struck and the rest is not.** *"The tile"* is written in the present about a tile
> that did not exist on the box (measured 2026-08-11; full correction below the
> next block). The **mechanism** — status-code judging, silent green — is exactly
> right, and it is why the tile eventually created was pointed at `?strict=1` from
> birth instead of pointed and then fixed.

> ~~⚠ **THE TILE NOW EXISTS, so this stopped being preventative on 2026-08-05.**~~
> ⛔ **FALSIFIED 2026-08-11 — IT DID NOT EXIST. Everything in this block describes
> an artifact in an open PR in another repo, never anything Homepage was serving.
> The correction follows the block; do not act on the block alone.**
> Homelab **PR #21** (`feat/chat-gateway-service-artifacts`, open) adds a Homepage
> row for the gateway whose `siteMonitor` is
> `http://<LAN-IP>:8085/healthz` — **the plain form.** Against the code as it
> stands, that probe returns **200 for every reason string `/healthz` can
> produce**, including *"subscriber is enabled but has never completed a poll —
> inbound has never worked on this process"*, which is the literal text the box
> emitted eight seconds after boot (`nas.md:665`).
>
> **So the tile reads green while inbound is dead.** That is the claude-mem
> failure — the one hard rule #5 exists because of, the one that hid **11 days**
> of silent capture failure — **reproduced at the dashboard**, in this project,
> against the endpoint that was written to prevent it. It is not a hypothetical in
> a spec any more; it is a live monitoring surface with a known-wrong verdict.
>
> ⚠ **This Part must therefore ship a second deliverable it did not previously
> have: the tile has to be REPOINTED at `?strict=1`.** That is a homelab-repo
> change, so **a chat-gateway Builder does not make it** — it is a handoff, named
> here and in `nas.md` §9 so it is an owned action rather than an omission. **The
> `?strict=1` endpoint landing without the tile moving changes nothing an operator
> can see**, and shipping only the half in this repo would be the more dangerous
> outcome of the two, because it retires the finding without fixing it.

> ⛔ **THE CORRECTION TO THE BLOCK ABOVE — 2026-08-11, from measuring the box
> rather than reading the PR.** `/mnt/datapool/apps/homepage/config/services.yaml`
> carried **eight** tiles in its NAS group and **chat-gateway was not one of
> them.** So *"a live monitoring surface with a known-wrong verdict"* named a
> surface that was not in the config Homepage serves, and the second deliverable
> this block invented — *"the tile has to be REPOINTED"* — presupposed something to
> repoint. Whether PR #21 merged is not readable from this repo and is **not
> asserted either way**; the live file is what was measured. Origin of the chain,
> and the fullest correction: the spec's **§4.1 `docs/deploy/nas.md` deliverable
> bullet — the PR #21 ✅.**
>
> ⚠ **This was the MILDER of two failures, not a false alarm.** Green-while-dead is
> a wrong answer; **no tile is no answer**, which is what ~23 hours of a dead
> `dockerd` from 2026-08-10 looked like to every human involved. **CG-84.**
>
> ✅ **THE DELIVERABLE WAS DISCHARGED 2026-08-11 — by CREATE, not REPOINT.** A tile
> was created directly in that file (backed up first, NAS group now nine, YAML
> validated by parsing) with `href` on plain `/healthz` and `siteMonitor` on
> **`/healthz?strict=1`**, carrying a comment recording that the `1` is
> load-bearing: the rebuilt handler declares `strict` as a bool, so an invalid
> value is a **422** and a typo'd probe would read **DOWN on a healthy gateway.**
> ✅ **The endpoint half reached the box the same day** on CG-80's redeploy — so
> *"the `?strict=1` endpoint landing without the tile moving"* never became the
> outcome this block feared. ⚠ **Two residuals, both open:** `capture.sh` has
> **not** been re-run, so the homelab repo does not record the tile (the far half
> of the handoff, which this repo cannot discharge), and **`?strict=1` returning
> 503 has never been observed on the box** — a genuine degraded window occurred
> after the 2026-08-11 restart and cleared before it could be sampled, so the 503
> path is proven only in the driven local test below. One home for both:
> `docs/deploy/nas.md` §9 and §10's **2026-08-11** entry.

```python
    @app.get("/healthz")
    def healthz(strict: bool = False):
        """...(existing docstring kept in full)...

        `?strict=1` returns **503** when `reasons` is non-empty, with an
        IDENTICAL body. Additive: the plain form keeps its contract and its
        existing readers. Not the default, for two reasons — the plain form is
        published and read today, and a 503 from a container health check would
        make Docker restart a gateway that is degraded but WORKING (one
        unresolved env var on a tier-1-only host). Opt-in puts the choice with
        the reader; the homelab Homepage tile points its `siteMonitor` here.
        """
```

> ✅ **That docstring's last clause BECAME TRUE on 2026-08-11 — marked confirmed,
> not corrected.** When it was drafted it was a *proposal* about a tile that did not
> exist (correction above); it now describes the box. ⚠ **And it became true by a
> tile being CREATED on the strict form from birth, never by one being repointed**
> — which is worth recording, because *repointed* is the word every passage in this
> Part used and it implies a predecessor that was never there.
>
> ⚠ **One thing the drafted docstring could not have known, and it makes the `1`
> load-bearing rather than stylistic:** `strict: bool = False` means an **invalid**
> value is a **422**, so a tile probing `?strict=banana` — or any typo — reads
> **DOWN on a perfectly healthy gateway.** The tile created on 2026-08-11 carries a
> comment saying exactly this. ✅ **That 422 also turned out to be a TOOL:** the
> pre-2026-08-11 image did not declare the parameter and so answered **200 to any
> `strict` value**, which makes a deliberately-invalid value a **one-request
> discriminator for which image is live, without degrading production**
> (`docs/deploy/nas.md` §10, **2026-08-11**).

and at the return:

```python
        return JSONResponse(status_code=503 if (strict and reasons) else 200,
                            content={"status": "degraded" if reasons else "ok",
                                     "reasons": reasons, **body})
```

Tests:

```python
def test_strict_returns_503_only_when_there_are_reasons():
    ...

def test_the_strict_body_is_identical_to_the_plain_body():
    # Same information, different envelope — or an operator comparing the two
    # learns something false.
    ...

def test_the_plain_form_still_returns_200_when_degraded():
    # A published contract with existing readers. Unchanged.
    ...
```

## G2 · The soak — designed, not assumed

**The original G2 was four lines: a duration, a field list, and a deliverable.**
It did not say what makes a duration long *enough*, how observations get captured
without somebody watching a terminal, what a **pass** is, or — the one that
matters most — what a **failure** looks like as distinct from a quiet network.
Those are the parts the ledger sign-off turns on, so they are established here
against measured periods rather than chosen as round numbers.

### G2.1 · Duration — derived from real periods, not from a round number

**The ledger row is `SubscriberLoop`'s *long-run thread behaviour*.** So the
question is not "how many hours feels serious" but **which failure modes need
wall-clock time to appear at all**, and what period each one is keyed to. Every
figure below is read out of this repo's own code:

| Failure mode a short run cannot reach | Keyed to | Measured period | Soak must span |
|---|---|---|---|
| **SA access-token expiry on the PULL path** | Google's token lifetime (~1 h) | `PubSubPuller.__init__` takes the **same `token_provider`** as `ChatApiAdapter` (`adapters/pubsub.py:255`), and `GoogleServiceAccountTokens.__call__` refreshes on google-auth's own transport | ⚠ **the single most important one.** A short smoke test runs entirely inside one token. **≥3 refreshes** so a refresh is not a coincidence |
| **Audit-file date rollover** | local midnight | the audit trail is `<app>-<date>.jsonl` — **the filename is the retention key** (`retention.py:15`) | **≥1 local-midnight crossing**; ≥2 to see a second file open |
| **A retention sweep actually running** | `SWEEP_INTERVAL_S` | **6 h** (`retention.py:106`) — four sweeps a day | **≥2 sweeps**, i.e. ≥12 h, or `last_sweep_at` never moves and proves nothing |
| **Sweep staleness detection** | `SWEEP_STALE_INTERVAL_MULTIPLE` × interval | **2 × 6 h = 12 h** (`retention.py:116`) | ≥12 h before `/healthz` could even complain |
| **A wedge, as distinct from a blip** | `POLL_STALE_AFTER_SECONDS` | **300 s**, `max(300, 6 × interval)` (`service.py:87`) | minutes — cheap, and the only one a short run reaches |
| **Slow leaks** (RSS, fds, journal, audit bytes) | none — a rate | — | long enough for a **trend line**, not two points |

**Floor: ≥24 h. Target: ≥72 h.** The original numbers survive — but they are now
*derived* rather than asserted, and the derivation changes what a short soak
means. ⚠ **24 h is the floor because of the 12 h sweep interval and the midnight
rollover, not because a day sounds respectable.** A 12 h soak crosses at most one
sweep and possibly no midnight, so it cannot speak to the sweeper at all.
**72 h buys the thing a floor cannot: three midnights, ~12 sweeps and ~70 token
refreshes — enough that "it worked once" and "it works repeatedly" separate.**

> ⚠ **WHAT WAS ACTUALLY RUN — 2026-08-11. This derivation is now the yardstick the
> run is measured against, and the run is at the floor.** The dev-box `/healthz`
> stream reached **24 h 12 m**; the NAS memory stream **25.2 h** of its 72 h
> ceiling. **Both are dead and final** — see the correction at the head of this
> Part. So *"it worked once"* and *"it works repeatedly"* did **not** separate, and
> this table is the reason it is possible to say so precisely rather than call the
> result "nearly a soak". ⚠ **The one thing the target's derivation buys us now is
> the honest way to report the shortfall:** three midnights, ~12 sweeps and ~70
> token refreshes are named here, so nobody has to guess what a 25 h window failed
> to reach.

### G2.2 · Cadence — two rates, because the fields have two shapes

**One sample rate is wrong for both halves.** `seconds_since_last_poll` is a
sawtooth that must be caught near its peak; `files_deleted` is a step function
that moves four times a day.

| Stream | Rate | Why that rate |
|---|---|---|
| **`/healthz`, whole body** | **every 30 s** | The sawtooth peaks at **~24 s** (G0 drift 8), so 30 s is just above one period: samples land at unaligned phases and the observed **max converges on the true max** rather than on whatever phase a slower poll happened to hit. 60 s would alias against a ~24 s wave and systematically under-report the peak — which is the number the wedge detector is judged against |
| **container RSS + disk** (`docker stats --no-stream`, `du -sb`) | **every 10 min** | A memory *leak* is a slope over days; sampling it at 30 s buys nothing and multiplies the artifact size ~20×. `du` walks the tree, so it is the one probe with a cost |

⚠ **Do not derive the poll cadence from `poll_interval_seconds` (5 s).** That is
the loop's own interval and it is **not** the period of the field being observed —
conflating them is the same mistake as reading the sawtooth as a fault.

### G2.3 · What is captured — the whole body, appended, on the box

**Record the entire `/healthz` JSON per sample, one object per line, not a
selected subset.** The field list has been wrong three times in this arc already
(G0 drifts 3, 6, 7 are all *"a counter that exists and was not in the list"*), and
**a soak that discards a field cannot be re-read for it three days later.** The
run is unrepeatable in a way the analysis is not.

```
# on the box, detached; no human watches a terminal for three days
#   - append-only JSONL, one whole /healthz body per line, plus a sample clock
#   - a SEPARATE file for the 10-minute RSS/disk stream
#   - systemd timer, cron, or `nohup` + a loop — any of the three; the choice is
#     the operator's and the runbook records which was used
#   - the gateway's own container is NOT modified: this is `curl` from outside it
```

⚠ **Three constraints on the artifact, all load-bearing:**

1. **It lands in this PUBLIC repo, so it obeys `/healthz`'s own discipline** —
   counts and app ids only. `/healthz` already emits no space id, no sender and
   no content by construction (CG-12), so capturing the **whole body** is safe
   *because of* that design, not in spite of it. ⚠ **`inbox.pending` is a
   per-app map** (G0 drift 2) — app ids are non-secret (they are in the committed
   registry), so it stays; nothing else in the body needs a decision.
2. **Sample it from a host that is not the gateway's container.** A sampler
   sharing the process it measures cannot distinguish "the gateway is wedged"
   from "the sampler is wedged".
3. **Keep the raw JSONL out of `git`.** Summarize into `nas.md`; the run's
   artifact is an input, not a deliverable. ⚠ `state/` is gitignored for exactly
   this class of accident (CG-67) — **the soak artifact is not under `state/`**,
   so that guard does not cover it. Write it somewhere ignored, deliberately.

### G2.4 · What is observed — the current field set, not 2026-07-31's

The original list named 9 fields. **`/healthz` now publishes four subsystems.**
Capturing the whole body (G2.3) means this table is an *analysis* checklist, not
a collection one — which is the point.

| Subsystem | Fields that carry the long-run signal |
|---|---|
| `subscriber` | `seconds_since_last_poll` (**max, not mean** — a mean hides a wedge), `poll_failures`, `consecutive_poll_failures`, `last_poll_error`, `thread_alive`, `thread_started`, `events_seen`, `unparseable_seen`, `dispatch_errors`, `interactions_without_action_id`, `suppressed_opt_out`, `suppressed_not_authorized`, `stale_after_seconds` |
| `delivery` (**CG-72/74/75/76**) | `thread_alive`, `thread_started`, `seconds_since_last_pass`, `pass_failures`, `consecutive_pass_failures`, `last_pass_error`, `delivery_failures`, `pending_jobs`, `journal_skipped_lines`, `journal_write_errors`, **`audit_write_errors`** |
| `heartbeats` (**CG-72/74/76**) | `thread_alive`, `thread_started`, `seconds_since_last_scan`, `scan_failures`, `consecutive_scan_failures`, `alerts_undeliverable`, `checks_undeliverable`, `checks_orphaned` |
| `retention` (**CG-68**) | `thread_alive`, `last_sweep_at`, `files_deleted`, `delete_errors`, `sweep_failures`, `consecutive_sweep_failures`, `audit_dir_configured` |
| `inbox` | `pending` (**a map**), `dropped`, `replayed_at_boot`, `unrevivable_at_boot`, `quarantined_at_boot`, `quarantine_write_errors` |
| off-body | container **RSS**, journal size **across ≥1 compaction**, `du` of each state directory, container restart count |

⚠ **All four `thread_alive` flags, not just the subscriber's.** CG-72 exists
because `/healthz` could not see two of these four at all, and a soak that
re-narrows to one re-creates the blindness that row closed.

### G2.5 · Pass, fail, and the difference between a failure and a quiet network

**This is the section the original G2 did not have, and it is the one the
sign-off turns on.** Every threshold is a measured constant from this repo, cited.

**PASS — all of:**

| # | Condition | Why this and not something stricter |
|---|---|---|
| 1 | all four `thread_alive` **true** in every sample; no `thread_started` flips false | thread death is the ledger row's literal subject |
| 2 | `max(seconds_since_last_poll)` **< `stale_after_seconds`** (300 at a 5 s interval) | ⚠ **judged against the budget the code publishes, NOT against `poll_interval_seconds`.** The observed ceiling is ~24 s (G0 drift 8); a max in the 20-30 s band is **healthy long-polling** |
| 3 | `consecutive_poll_failures` returns to **0** after any excursion | the cumulative counter is history; the consecutive one is the live condition |
| 4 | `status: "ok"` and `reasons: []` in every sample **after** the first completed poll | ⚠ **the boot window is EXPECTED to be `degraded`** — `nas.md:665` records ~8 s of *"has never completed a poll"*, and that is rule #5 working. A soak that counts it as a failure has misread its own instrument |
| 5 | `last_sweep_at` advances **≥2 times**; `sweep_failures`, `delete_errors`, `consecutive_sweep_failures` all **0** | ≥2 is what distinguishes a running sweeper from one that ran once at boot |
| 6 | RSS **flat or converged** across the run — a slope, not two endpoints | a leak is a rate; a single before/after pair cannot see one |
| 7 | container restart count **unchanged** | ⚠ `restart: unless-stopped` makes a silent restart look identical to uptime from `/healthz` alone, because every counter resets to a plausible zero. **This is the one check that must come from `docker`, not from the body** |
| 8 | `journal_write_errors`, `audit_write_errors`, `delete_errors`, `quarantine_write_errors` all **0** | the write-path counters CG-75/CG-65 added precisely so a silent failure has a number |

**FAIL — any of:** a `thread_alive` false; `seconds_since_last_poll` over
`stale_after_seconds`; `consecutive_poll_failures` that never returns to 0; a
non-null `last_poll_error` that repeats; monotonically rising RSS; any non-zero
write-error counter; an unexplained restart.

⚠ **The distinction that is easy to get backwards.** A **quiet network** and a
**wedged loop** look nearly identical in the fields an operator watches first —
`events_seen` flat, `poll_failures` 0, `status: ok`. They are told apart by
exactly one field, and it is the reason that field was added:

> **`seconds_since_last_poll` keeps SAWTOOTHING when the subscription is empty,
> and FREEZES when the loop is wedged.** A quiet network still completes polls —
> Pub/Sub returns empty after its long-poll hold and `last_poll_at` advances. A
> wedged loop stops advancing it, and the number climbs monotonically. **Quiet is
> a sawtooth; wedged is a ramp.** The *shape* is the signal, not the value, which
> is why every sample is kept and why the cadence sits just above one period.

**This is also the answer to "what if nothing ever arrives".** A three-day soak
over four silent spaces still fully exercises the pull loop, the token refresh,
the sweeper and all four threads — because **polling is unconditional.** The
evidence does not depend on traffic.

### G2.6 · ⚠ What a quiet space CANNOT prove — state this, do not smooth it

**`events_seen` was `0` at deploy** across a sampled window with `poll_failures: 0`
throughout (`nas.md:759`), and **a 72 h soak may legitimately return `0` again.**
Zero is a real reading, not a broken sampler. What it does and does not license:

| A `0`-event soak **does** establish | It does **not** establish |
|---|---|
| the pull loop survives days, across dozens of token refreshes | anything about **dispatch under inbound load** — `dispatch()` may not run once |
| all four threads stay alive and keep completing passes | `inbox.dropped` / the 1000-item cap — **unreachable at zero volume** |
| the sweeper runs on schedule and errs zero times | that **30 days is the right window** — the row's own remaining question needs volume |
| `status`/`reasons` stay honest over days | which **event types** the four spaces actually send — still open from `nas.md` C1a |
| RSS and fd behaviour at idle | RSS under load |
| the ~24 s long-poll period is stable, not a one-off | queue depth or backlog behaviour |

⚠ **And `0` does not mean the spaces are silent.** The subscription's retention is
**24 h** and it was drained by an ad-hoc client on 2026-07-30, so anything older
is simply gone: `0` means *nothing was retained at this moment*, not *nothing
happened* (`nas.md:766`). **A soak measures the gateway, not the spaces.**

⚠ **The spec's §4.7 says the opposite of all this and must not be quoted.** It
claims the subscription *"is no longer quiet"* and that the soak therefore
exercises *"real, continuous, multi-space traffic"* — **written 2026-07-31 as a
prediction, and falsified by the first measurement from the box.** G0 drift 9.
**The PR must state what the evidence reaches and nothing beyond it.**

### G2.7 · Who runs it

**Builder, over SSH, under the standing rules at the top of this plan.** Sampling
`/healthz` is `curl` and append — squarely ✅ *"read-only probing, unattended"* on
§4.3.1's table, which is the row that names this exact capability. ⚠ **The spec
still says the observation half is *"user-executed"*** (§4.7); that framing
predates CG-55, which superseded it for the deploy itself and proved the
connection works unattended. **Recorded as a drift rather than silently
inverted** — G0 drift 11 — because it is the kind of scope change that should be
visible, and because CG-79 examined that same line and reasonably left it alone.

### G2.8 · Deliverable

A dated observation section in `docs/deploy/nas.md` — measured, in this queue's
house style, **with the raw artifact summarized rather than committed.**

⚠ **Whether this clears the ledger's `SubscriberLoop` long-run row is a hard rule
#3 question needing the user's explicit sign-off** (CG-35's precedent: the flag
word dropped, the explanation kept, and the PR says in those words what is being
removed). **This Part plans the EVIDENCE. It does not plan the clearing, and it
must not be written as though the two are the same step.** The row **presents and
proposes**; it does not move a flag on its own authority, and a clean 72 h result
is an argument for the user to consider, not a clearance that follows from it.

**The proposal must name its own limit in the same breath as its result** — the
G2.6 table is that limit. *"The loop survived 72 hours, ~70 token refreshes and
three midnights over a subscription that delivered zero events"* is a true and
useful sentence. *"The loop is proven under load"* is not, and no amount of
uptime makes it one.

> ⛔ **THAT EXEMPLAR SENTENCE CANNOT BE WRITTEN — corrected 2026-08-11.** It was
> offered as a *template* for how the sign-off should be phrased, and it describes
> a run that never happened. What exists: the NAS memory stream, **152 samples over
> 25.2 h** of a 72 h ceiling, and the dev-box `/healthz` stream, **24 h 12 m**.
> **Both are dead and final** — nothing is accruing toward the missing hours. So
> *"72 hours"*, *"~70 token refreshes"* and *"three midnights"* are each
> unavailable, and they are unavailable for the reason §G2.1 gave when it derived
> them: they are exactly what a 72 h window buys and a floor-length one does not.
>
> ⚠ **The sentence's STRUCTURE survives, which is why this is annotated rather than
> deleted** — name the duration, name what recurred inside it, name what the
> subscription delivered, then stop. Rebuilt honestly it claims materially less,
> and **the row must claim what the run reaches: a soak *at* the floor with no
> margin**, not the one every downstream sentence assumes.
>
> ✅ **One result inside that window is clean and should be stated plainly rather
> than lost in the shortfall:** memory, file descriptors and threads were **flat**
> across the NAS half, with no restart — **no leak** — over **25 h, not 72 h.**
> ⛔ **And the strongest fallback input is not short, it is GONE:** the container's
> uptime streak was destroyed by the 2026-08-10 `dockerd` outage — **LOST, not
> SPENT on a deliberate rebuild** — so it cannot be offered to the user at all, and
> **CG-82 task 1 is moot.** ⚠ **A credible re-run needs CG-85 first.** Every number
> has one home: `docs/deploy/nas.md` §11.

## G3 · Disk growth — measure, propose, do not implement

~~The audit JSONL files (`inbox-data/`, `state/deliveries/`) are per-app-per-day and
**never pruned** — invisible on the dev box, a slow leak on a host meant to run
for years. Report measured growth per day and **propose** a retention rule.~~

~~**Do not implement one.** A retention policy on an audit trail whose stated
purpose is that *"nothing is ever silently lost"* is a rule-#5-flavoured decision
and belongs to the user — ✅ **decided (D5): measure first, propose here with real
numbers.** With `aiteam-harness` closed (D1) only `job-hunter` accumulates.~~

> ⚠ **STRUCK 2026-08-05: `never pruned` is FALSE, and D5's *"decide at CG-59"*
> was decided three days early — by CG-68 on 2026-08-02.** G0 drifts 4 and 5.
> Struck rather than deleted because the *shape* of the reasoning is what CG-68
> went on to adopt, and a Builder who finds only the conclusion will not know the
> premise moved. The two directories now differ, and **collapsing them is exactly
> what the struck text did**:
>
> | Directory | Pruned? | By what |
> |---|---|---|
> | `inbox-data/` | ✅ **YES**, since CG-68 | `DEFAULT_RETENTION_DAYS = 30`; `UNROUTED_RETENTION_DAYS = 7` for the gateway's own `_unrouted` bucket; `0` disables — via `CHAT_GATEWAY_INBOX_RETENTION_DAYS`. **The filename is the retention key**, so pruning is a directory listing and an `unlink`; nothing opens a file holding bodies to decide whether to delete it |
> | `state/deliveries/` | 🚫 **NO — by decision**, not omission | titles-only and permanent, **ADR-0002 D7**. CG-68 made it a code property too: the sweeper **refuses to boot** if its directory overlaps the state dir |
> | `state/quarantine/` | 🚫 **NO — deliberately** | it is what makes the sweep safe; skipped by name even when the overlap guard would allow it |
>
> **The window's numbers have ONE home — `retention.py`'s constants, quoted to
> consumers at `docs/integration-guide.md:366`.** They are named above only to
> mark which of three directories each rule applies to; do not treat this table as
> a second home for the values.

### G3′ · What is ACTUALLY left for this row

**The retention *mechanism* is not this row's question any more. Its *calibration*
is** — and that is a question only volume can answer, which is why it survived
into a soak.

| Question | Why the sweep did not settle it |
|---|---|
| **Is 30 days the right window?** | CG-68 picked a number **before any real volume existed**. The soak is the first opportunity to price it against measured bytes/day per app |
| **Is `state/deliveries/` growing forever acceptable on a host meant to run for years?** | ⚠ **D7 decided this on CONTENT grounds — titles only, no bodies — and never on SIZE.** That is a different argument, and it has never been tested against a rate. Measure the rate; if it is negligible, D7 is confirmed **for a reason it did not originally have** |
| **Does the sweeper's own bookkeeping stay clean over ≥2 sweeps?** | `files_deleted`, `delete_errors`, `sweep_failures` have never been read from a long-running deployment |

⚠ **`files_deleted: 0` across a 72 h soak is the EXPECTED result and proves
nothing about the sweeper working.** The window is **30 days** and the deployment
is days old, so **there is nothing old enough to delete.** A soak that reports
*"`files_deleted: 0` — retention verified"* would have inverted its own evidence.
**What a 72 h soak can establish is that the sweeper RUNS** — `last_sweep_at`
advancing ≥2 times with zero errors — which is a liveness claim, not a deletion
claim. Say which one the run has.

**Still: measure and propose, do not implement.** Unchanged and still right —
a retention decision belongs to the user (CG-68's own A2/A3/A5 sign-offs are the
precedent, not a counterexample). ⚠ **And do not "fix" `files_deleted: 0` by
shortening the window to make the soak produce a deletion.** Tuning an instrument
until it reports what an experiment wanted is not evidence.

> ⛔ **THERE IS NO 72 h SOAK TO READ THIS AGAINST — corrected 2026-08-11.** Both
> streams are dead and final at **24 h 12 m** (dev box) and **25.2 h** (NAS); see
> the correction at the head of this Part. **Every *"across a 72 h soak"* above is
> now describing a run that does not exist**, and the three calibration questions
> in the table are **still open**, not answered-and-negative. ⚠ **The reasoning is
> untouched and is why this is annotated rather than rewritten:** `files_deleted:
> 0` would still have been the expected result, the sweeper-RUNS claim would still
> have been the only one available, and the temptation to shorten the window to
> manufacture a deletion is if anything **stronger** now that a short run is the
> only run there is. ⚠ **A re-run needs CG-85 first** — the samplers died to their
> environment, not to their design, and re-running the same capture buys the same
> ending.

---

# Part H — CG-60 · Repo-wide correction of the one-space premise

⏸ **Merge gate: consumer contracts + the ledger's neighbourhood.**
**Sequenced FIRST** — docs-only, no dependencies, and it corrects a live-false
claim in a tenant's own contract.

## H0 · Re-derive before editing — do not trust the list

```bash
# The measured half. Reports NO space id and NO env value.
python - <<'PY'
import sys; sys.path.insert(0, "src")
from chat_gateway.registry import load_registry
r = load_registry("config/registry.yaml")          # the LIVE, gitignored file
spaces = {}
for n, i in sorted(r.identities.items()):
    if i.space:
        spaces.setdefault(i.space, []).append(n)
for idx, (sp, idents) in enumerate(sorted(spaces.items()), 1):
    owners = r.apps_for_space(sp)
    print(f"S{idx}: identities={idents} -> apps_for_space={owners} "
          f"allow_inbound={[r.apps[a].allow_inbound for a in owners]}")
PY
```

Expected (2026-07-31): four distinct spaces; two → `['aitrader']` with
`allow_inbound=False`; one → `['job-hunter']`; one → `['aiteam-harness']`.
**If it differs, stop — the premise moved again.**

Then locate the stale claims **by text, never by line number** (CG-52's rule):

```bash
grep -rn "Agent Comms" --include=*.md --include=*.py .
grep -rn "not in aitrader\|no Pub/Sub event originates" --include=*.md .
grep -rniE "jobhunt space only" --include=*.md .
```

## H1 · `docs/consumers/aitrader.md` — a promotion, not a retraction

The file already carries the prediction:

> So the safeguard is **one step away, not two.** … adding the Chat app to an
> aitrader space would be sufficient on its own, and it is a console action that
> leaves no trace in version control.

**It came true.** So:

- Change the existing table's tense from conditional to **present**: the live
  registry row's *"would increment `suppressed_opt_out`"* becomes *does*.
- Replace the falsified sentence — *"the Chat app is not in aitrader's spaces, so
  no Pub/Sub event originates from them"* — with the dated console fact.
- **State what has NOT changed, in the same breath**: hard rule #6 holds, the
  `continue` in `dispatch()` fires before any `inbox.put`, **nothing crosses to
  aitrader**, and `allow_inbound: false` is doing exactly its job. The change is
  that a *counter moves on an unauthenticated endpoint* — a volume signal, not a
  data path.
- Point at **D2 (spec §7)**: the exposure is not silently accepted — the drafted
  homelab tailnet ACL lands before the deploy. Name the residual too: the ACL
  governs the tailnet, not the LAN.

**Do not delete the prediction.** It is the most valuable paragraph in the file:
it named the trigger, the trigger fired, and leaving it visible is what makes the
next such warning believable.

## H2 · The console facts, recorded as a dated user statement

In `docs/google-cloud-setup.md`, in the voice that file already uses for its
existing dated observation:

- **"Agent Comms" is DEPRECATED** — it was workspace-specific.
- Replaced by an app named **"Chat Gateway"** — same functionality, better
  interaction support in the space.
- It participates in **four** spaces: FamilyWorkspace, Ai Trader, Ai Trader
  Reports, JobHunt.

Frame exactly as that file already teaches: **a fact about the Google Chat
console, readable nowhere in this repo**, dated, and stale the moment somebody
changes it. The registry's `space:` is a *posting target*, not a membership
record. **Do not present it as measured** — only the `apps_for_space`
re-derivation is.

Then sweep the live-identity references in `docs/integration-guide.md`,
`docs/consumers/jobhunt.md` and `docs/consumers/jobhunt-handoff.md`.

## H3 · ⚠ The historical observations are CORRECT — do not touch them

`CLAUDE.md`'s ledger row recording `sender: {displayName: "Agent Comms"}`, and
the identical sentences in `src/chat_gateway/adapters/chat_api.py`'s docstrings,
are **accurate observations of what happened on 2026-07-29**. They are evidence,
not claims about today.

- **Do not rewrite the observation.**
- **Do not clear, add or reword any ⚠ flag.** That needs the user's explicit
  sign-off naming hard rule #3, which this row does not have.
- Add a **dated note adjacent to** the observation that the app has since been
  replaced, leaving the observation intact.

**This is the CG-50 shape exactly**: the finding is kept, the currency pointer is
what changes, and the diff stays confined between untouched flag blocks.

## H4 · `docs/BUILDER_QUEUE.md` — judge claims vs records

Shipped rows are **history** and stay as written. Only correct text that asserts
something about the **present**. When in doubt, leave it: a queue entry describing
what was true when it shipped is a record, not a claim.

## H5 · Verify

```bash
python -m pytest -q                                  # expect 202; docs-only
grep -rn "not in aitrader\|JobHunt space only" --include=*.md .   # expect none
python -m pytest -q tests/test_fixtures_scrubbed.py  # CG-26 guard reads these files
```

- [ ] No ⚠ flag cleared, added or reworded — **verify with a diff**, not memory.
- [ ] No space id, email, `users/…` id or tenant value introduced.
- [ ] The aitrader prediction paragraph still present.

---

# Part I — CG-61 · Close `aiteam-harness`'s inbound path (D1)

⏸ **Merge gate: a live-config change narrowing a tenant's inbound surface.**
**Sequenced second, and it MUST land before Part C** — that Part streams the live
registry to the NAS.

Reasoning lives in spec §7 D1 and §4.0b. This Part is only the mechanics.

## I1 · `config/registry.example.yaml`

```yaml
  aiteam-harness:
    key_env: CHAT_GATEWAY_API_KEY__AITEAM_HARNESS
    identities: [pm-familyworkspace]
    # Inbound was on only because `true` is the DEFAULT — this app never asked
    # for it. It has no callback_url, no allowed_users, and CLAUDE.md describes
    # it as a notify.py OUTBOUND transport. Hard rule #6 is default-deny in
    # spirit; this makes it so in fact, and that space's content never reaches
    # disk (an opted-out owner's event is discarded entirely — it cannot even
    # land under `_unrouted`, because that fallback only fires for a space with
    # NO owner).
    #
    # A DEFAULT CORRECTED, NOT A VERDICT about this consumer. Reversible in this
    # one line if aiteam ever wants inbound.
    allow_inbound: false
```

## I2 · The live registry — an operator action, recorded

⚠ **`config/registry.yaml` is gitignored; a PR cannot change it.** Verified
2026-07-31 that it still reads `allow_inbound=True` for this app, so this is a
real edit and not a no-op. Make the same change on the dev box, then confirm:

> ✅ **DONE — the operator made this edit on 2026-08-03** (`config/registry.yaml`
> mtime `2026-08-03T20:34:06Z`), and `allow_inbound: false` is now **written
> explicitly** at line 38 rather than arriving as the loader default, which was
> D1's whole point. Re-measured through the real `load_registry` on 2026-08-05:
> `aiteam-harness allow_inbound=False`. Independently confirmed on the box by
> CG-55's fail-closed pre-flight (`nas.md:644`).
>
> ⚠ **The interesting part is the four days in between.** This step's *"Verified
> 2026-07-31"* measurement was superseded 78 minutes after a **later** measurement
> — taken 2026-08-03 at 19:15:56Z and quoted as current in the queue — and both
> went on describing the file as unedited until 2026-08-05. **So the correct fact
> was written down in this repo, in `nas.md`, on the day of the deploy, while
> three other files still called the edit outstanding.** That is not staleness; it
> is two homes for a moving fact, and this arc's most-repeated lesson.
>
> **The measurement above is left as written** — it was true on 2026-07-31 and a
> dated measurement is a record. Only the tense is corrected, here, once.

```bash
python - <<'PY'
import sys; sys.path.insert(0, "src")
from chat_gateway.registry import load_registry
r = load_registry("config/registry.yaml")
for aid, a in sorted(r.apps.items()):
    print(f"{aid}: allow_inbound={a.allow_inbound}")
PY
# expected: aiteam-harness False, aitrader False, job-hunter True
```

## I3 · The test that pins the property D1 rests on

Without this, a future refactor can quietly reintroduce the disk write.

```python
def test_an_opted_out_owner_reaches_neither_its_inbox_nor_unrouted(tmp_path):
    """D1's benefit, pinned.

    `dispatch()` discards an opted-out owner's event entirely: the
    `or [UNROUTED]` fallback CANNOT fire, because that only triggers for a space
    with NO owner and this space HAS one. So nothing reaches the app's inbox,
    nothing reaches `_unrouted`, and nothing reaches the JSONL audit on disk —
    only the counter moves. That last clause is the whole point of the decision.
    """
    inbox = Inbox(audit_dir=tmp_path)
    suppressed = []
    delivered = dispatch(EVENT_IN_THE_CLOSED_SPACE, registry, inbox,
                         on_suppressed=lambda app_id, reason: suppressed.append((app_id, reason)))
    assert delivered == []
    assert inbox.poll("aiteam-harness") == []
    assert inbox.poll(UNROUTED) == []
    assert list(tmp_path.glob("*.jsonl")) == []          # nothing on disk
    assert suppressed == [("aiteam-harness", REASON_OPT_OUT)]   # but it IS counted
```

Build the event from an existing classic fixture. ⚠ **Use a synthetic space id** —
never the real one.

## I4 · Docs

`CLAUDE.md`'s consumer list, and anywhere describing that app's inbound posture.
Keep it short: the reasoning belongs in one place, and that place is the spec.

## I5 · Verify

```bash
python -m pytest -q          # expect 202 + the new test
```

- [ ] Reversibility stated in the comment — a default corrected, not a verdict.
- [ ] `aitrader` untouched and still `allow_inbound: false`.
- [ ] No real space id introduced.

---

# Cross-cutting checks — every Part

Before opening any PR:

```bash
python -m pytest -q                 # take the real count; the baseline moves
python -m ruff check src tests      # if configured
git diff --stat                     # scope matches the row
```

- [ ] **No real identity literal anywhere in the diff** — no emails, `users/…`
      ids, `domainId`/`customer` values, tokens, space ids, webhook URLs, or
      homelab addressing values. CG-26's guard scans `docs/**/*.md`,
      `tests/**/*.py` and root `*.md`, **including this plan**.
- [ ] **No ⚠ flag cleared, added or reworded** (Parts F and G especially). Any
      such change needs the user's explicit sign-off naming hard rule #3.
- [ ] **`CLAUDE.md`'s verification ledger is LINKED, never restated.**
- [ ] `CLAUDE.md`'s test count updated if the suite moved.
- [ ] Merge gate observed: Parts A and C **pause and report before merging**.
- [ ] Nothing outside `D:\prj\chat-gateway` modified. jobhunt and homelab are
      **read-only**; their required changes are recorded for their own projects.
