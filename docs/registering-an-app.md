# Registering an app — minting a key and wiring a tenant

The operator runbook for giving a new application its own identity in this
gateway. Written 2026-09-10, from the `rotaryphone` registration executed that
day; the steps below are the ones that were actually run, not a design.

**This is an operator action, not a PR.** The live registry is gitignored and
the key is a new secret, so nothing here can be discharged by merging a branch.
`config/registry.example.yaml` is a template and deliberately does **not** gain
an entry per real tenant — neither `pmtrader` (2026-09-01) nor `rotaryphone`
(2026-09-10) is in it.

**Not covered here:** the field-by-field registry schema, which has one home —
[`docs/consumers/pmtrader-registration-handoff.md`](consumers/pmtrader-registration-handoff.md)
§3, written against `registry.py`'s dataclasses rather than an example. That
file is a handoff for one tenant; this file is the procedure for any of them.

---

## 0. The key is inert on its own

`mint-key` prints a random string. Nothing knows it until three other things
are true, and the order below is the order they must happen in.

`authenticate` (`src/chat_gateway/auth.py:33-36`) iterates the **registered**
apps and constant-time-compares the presented bearer against
`os.environ.get(app.key_env, "")`, under an `if expected and …` guard. So:

- an unregistered app has nothing to compare against — the key is unknown;
- a registered app whose `key_env` variable is **unset** never matches, because
  the guard rejects the empty string before the comparison.

Treat mint + registry + env + restart as one unit of work. A key that exists in
only two of the three places fails closed and looks exactly like a typo.

---

## 1. Four decisions, before any command

None of these has a default, and two of them are not reversible by editing a
config file.

| Decision | What it costs to get wrong |
|---|---|
| **Identity / space** | A new space needs a Google Chat webhook, and **a webhook is created in the Chat UI by a person** — nothing in this repo can mint one. The identity's `display` name and avatar are fixed **at webhook creation**, not by the registry (`adapters/webhook.py:3-7`), so a rename means a new webhook. Reusing an existing identity is legal (two apps may list one) and fixes attribution, but leaves both tenants' traffic in one room. |
| **`routes:` per severity** | Omitting a route is a **loud** failure at two different times: `/v1/notify` returns **503** (`registry.py:241-245` → `service.py:332-334`) and registering a *new* heartbeat `check_id` with no `alert` route returns **422** (`service.py:519-529`). `routes: {default: <identity>}` covers every severity. ⚠️ Severity picks the **space**, not just the loudness (CG-86) — split routes put an all-clear in a different room from the alert it closes. |
| **`allow_inbound`** | Hard rule #6. **Write it explicitly**, unquoted. Since CG-88 the default is `false`, but a written value is what a reader can diff between the three registry copies, and the loader reports every app that left the decision to it (`inbound_defaulted`, on `/healthz` and in `check`). ⚠️ `allow_inbound: "false"` — quoted — was truthy before CG-88 and granted exactly what it spelled a refusal of; the loader now refuses a non-boolean rather than coercing. |
| **Env-var name** | Convention: the app id, uppercased, hyphens → underscores. `job-hunter` → `CHAT_GATEWAY_API_KEY__JOB_HUNTER`; `rotaryphone` → `CHAT_GATEWAY_API_KEY__ROTARYPHONE`. |

App ids beginning with `_` are **rejected at registry load** — they are reserved
for the gateway's own audit buckets (`_unrouted`), and registering one would
drain every unroutable event past hard rule #6's checks.

---

## 2. Mint the key

```bash
python3 -m chat_gateway mint-key      # -> cgk_<43 urlsafe chars>
```

`auth.py:17-19` — `"cgk_" + secrets.token_urlsafe(32)`. `main` handles
`mint-key` **before** `build_runtime()`, so it works with no registry, no env
file and no credentials present.

From a bare checkout the package is not installed; use
`PYTHONPATH=src python3 -m chat_gateway mint-key`.

---

## 3. Write the registry entry

**There are three registry files and only one is in git** — the drift table and
its reasoning are in the handoff, [§6](consumers/pmtrader-registration-handoff.md).
The short version: `config/registry.example.yaml` is the tracked template,
`config/registry.yaml` on the dev box is what a local `check` loads, and
`/mnt/datapool/apps/chat-gateway/config/registry.yaml` is what the running
service reads.

The shape a notify-plus-dead-man tenant takes, as written for `rotaryphone`:

```yaml
identities:
  rotaryphone-alerts:                  # single space: loud lane AND quiet lane
    display: "rotaryphone"
    channel: google_chat
    mode: webhook
    webhook_url_env: GOOGLE_CHAT_WEBHOOK_URL__ROTARYPHONE
    space: "spaces/…"

apps:
  rotaryphone:
    key_env: CHAT_GATEWAY_API_KEY__ROTARYPHONE
    identities: [rotaryphone-alerts]
    allow_inbound: false               # hard rule #6 — written, not defaulted
    routes:
      alert: rotaryphone-alerts
      warning: rotaryphone-alerts
      info: rotaryphone-alerts
```

⛔ **Do not install the box's registry by copying the dev box's over it.** The
runbook's transport step (`docs/deploy/nas.md` §6) is written as
`sudo tee … < ./config/registry.yaml`, which **overwrites** the box's file with
this checkout's. Measured 2026-09-10: the box carried `agent-mcp` and the dev
copy did not, so running that step verbatim would have **deleted a registered
app** — silently, since a smaller registry loads perfectly well.

**What to do instead, and what was actually done:** read the box's own copy
down, edit *that*, and push it back hash-verified.

```bash
# 1. take a backup ON THE BOX first
ssh <nas> 'sudo cp -p <registry> <registry>.bak-$(date +%Y%m%d-%H%M%S)'
# 2. read it down (base64 survives a noisy interactive shell intact)
ssh <nas> 'sudo base64 -w0 <registry>'
# 3. edit locally, diff, then validate the EXACT bytes you are about to install:
python3 -c "from chat_gateway.registry import load_registry; \
            r = load_registry('<edited copy>'); print(list(r.apps))"
# 4. push it back and compare sha256 in both directions
```

Step 3 is not optional. A registry that fails to load is not a degraded mode:
`main` prints `config error:` and exits **2**, and under
`restart: unless-stopped` that is a crash loop, not a stopped container.

---

## 4. Set the env vars

Two variables per identity-owning app: the webhook URL and the API key.

```
GOOGLE_CHAT_WEBHOOK_URL__ROTARYPHONE=https://chat.googleapis.com/v1/spaces/…
CHAT_GATEWAY_API_KEY__ROTARYPHONE=cgk_…
```

⚠️ **No inline comment on a value line.** `env_file.py`'s parser ends a value at
a `#` preceded by whitespace — deliberately, because Compose parses the same
file the same way and a parser that disagreed would make a working file change
meaning at the destination. Put comments on their own lines.

⚠️ **Secret material goes over stdin, never as an argument.** An argument lands
in local shell history, remote shell history, and `ps` on a box other people's
software runs on; `sudo` logs the command it ran, not what was piped into it.

```bash
ssh <nas> 'sudo install -m 0600 /dev/null <path>'   # create restrictive FIRST
ssh <nas> 'sudo tee -a <path> >/dev/null' < ./local-block.env
```

Verify by hash and mode — `sha256sum` both ends and `stat -c '%a %U:%G'`. **Never
`cat` these files to check them**: a hash proves the transfer with no secret byte
reaching a terminal, a log, or a transcript.

⚠️ If the transport is an **interactive** remote shell rather than a one-shot
`ssh <cmd>`, the command line lands in that shell's history file too. Disable it
(`unset HISTFILE; export SAVEHIST=0`) before sending anything secret, and pass
values to shell **builtins** (`printf`) piped into the consuming command, so no
real process ever carries them in `argv`.

---

## 5. Restart

```bash
ssh <nas> 'sudo midclt call app.redeploy chat-gateway'
```

The registry and the env file are read **at load**, so a running gateway keeps
the posture it booted with; merged is not in effect, and neither is edited.

⚠️ **`app.redeploy` does not rebuild the image.** It redeploys the image that is
already on the box. Measured 2026-09-10: a redeploy for a registry change left
the box running `chat-gateway:local` built **2026-08-11**, three merged commits
behind `main` — including CG-88, so hard rule #7's default-deny was *not* in
effect on the box even though it was in `main`. Rebuilding is `docs/deploy/nas.md`
§4, and it is a separate decision with its own costs (§9 hazard 2).

---

## 6. Verify — in this order

Three checks that send nothing, then one that does.

1. **It loads.** `python3 -m chat_gateway check` — six validation conditions
   (`registry.py:374-439`). A registry that loads has passed hard rule #4's
   shape.
2. **`GET /healthz`** — per app `key_configured`, per identity `env_resolved`
   and `space_set`, plus `inbound_defaulted`. Unauthenticated, so it carries no
   values and no URLs.
3. **`GET /v1/identities`** with the new key — a **200** proves the key resolves,
   and the body names the app id it resolved to and each identity's `ready` flag.
4. **A live send.** `POST /v1/notify`, then read `GET /v1/deliveries` and look
   for `delivered`. ⚠️ **`202 enqueued` is not delivery** — dispatch is async, and
   the three checks above prove resolvability, never that a webhook posts.
   `env_resolved` is exactly the boolean that says which of the two was checked.

Pass the key to `curl` without putting it in `argv`:

```bash
printf 'url = "%s"\nheader = "Authorization: Bearer %s"\nsilent\n' "$URL" "$KEY" \
  | curl --config -
```

⚠️ A live send exercises **one severity's render branch**. `alert` and `warning`
build cards; `info` returns plain text and references the app id nowhere. Routing
is proven per severity, not once.

---

## 7. Hand the key to the consumer

A change in *that* application's repo, not this one. Until it lands, the app
either cannot authenticate or is still sending under whatever identity it
borrowed before — registration alone changes nothing about what its messages
look like.

Then record the rotation procedure in the homelab repo's `SECRETS.template.md`
(three rows — per-app keys, webhook URLs, the service-account key JSON) per
`docs/deploy/nas.md` §9. ⚠️ **Do not enumerate the app roster there.** That list
went stale twice unnoticed; it has one home, the registry.

---

## Rotating, later

- **An API key** rotates cleanly: mint, update the env var, redeploy, re-point
  the one consumer. Keys are per-app and never shared, so rotating one strands
  exactly one consumer.
- **A webhook URL does not.** ⚠️ There is no regenerate button in Google Chat —
  recovery is delete-and-recreate by hand, per
  [`docs/google-cloud-setup.md`](google-cloud-setup.md) §8a, and the new webhook
  gets a new display name and avatar unless you set them again. Every webhook
  this project owns was burned once, on 2026-07-29, and each had to be recreated
  through the console.
