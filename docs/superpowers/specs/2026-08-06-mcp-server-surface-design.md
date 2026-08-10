# An MCP server surface for the gateway — design

**Date:** 2026-08-06 · **Planner** · branch `docs/cg-80-mcp-server-surface`
**Baseline:** `main` at `f4b9c99`, suite **390 passing** — re-measured here with
`python3 -m pytest -q` (`390 passed in 33.34s`), not copied from a queue row or
from `CLAUDE.md`.

**Rows this spec produces:** **CG-80** — the gateway speaks MCP over its
existing HTTP surface, send-only.
**Row this spec FILES but does not queue:** **CG-81** — an MCP `read_inbox`
tool. Designed here in full so the decision is informed; **not queued**, because
it needs the user's explicit hard-rule-#6 sign-off *and* a dependency that has
not shipped (CG-56). §7 is its whole design.

**No ⚠ verification-ledger flag is cleared, added or reworded by anything in
this document, and none may be by the PR it produces.** §11 states why in the
terms the ledger uses, rather than being silent — silence on that ledger has
shipped false claims here before.

⚠ **This spec was written by a Planner that could not ask questions.** Every
place a Planner would normally have stopped and asked is a numbered entry in
**§14, Decisions for the user**, with a recommendation and the reasoning behind
it. ~~Nothing in §14 is settled.~~ ✅ **EVERYTHING in §14 is now settled — all
eight signed off 2026-08-10 at the recommendation, D4a included.** The struck
sentence was true on 2026-08-06 and false four days later; it is corrected *here*,
at the top, because a reader meets it long before reaching §14 and this spec's own
§14 heading was already correct while this line was still lying. Three further
things were settled *before* this document was written — by the user, in the
brief — and they are marked as such in §14's preamble so they are not
re-litigated.

---

## 1. Where this came from, and the research verdict this section is the home of

The question that prompted this was the **opposite** one: *should chat-gateway
**consume** a third-party Google Chat MCP server?* Research answered no, and in
answering it established a set of facts about the MCP ecosystem that are worth
more than the answer. **This section is their one home.** Do not restate them in
`CLAUDE.md`, in the queue row, or in the integration guide — the queue row points
here, which is this repo's standing discipline for a fact that would otherwise
drift.

**The findings, as of 2026-08-06:**

| # | Finding | Confidence |
|---|---|---|
| 1 | **No Google Chat MCP server exists from Google.** Every official and every maintained third-party server is direction *agent → Chat* (`send_message`, `list_spaces`) | high — registry sweep |
| 2 | **Zero MCP servers subscribe to Chat events** over Pub/Sub or the Workspace Events API | high — one false positive checked and eliminated (`mehtaniravm/LogSentryMCPGoogleHangout` is a Cloud Logging sink plus an outbound alert sender) |
| 3 | ⚠ **The durable one. MCP servers cannot send requests, cannot send arbitrary notifications, and cannot cause an LLM turn.** There is no inbound-webhook story *in the protocol* | high — protocol-level, not implementation-level. ⚠ **And it got STRONGER, not weaker, on 2026-07-28** (§6.1): that revision removed server-initiated requests outright — *"The server **MUST NOT** send independent JSON-RPC requests on this stream … This is a change from … `2025-03-26` through `2025-11-25`, where servers could send such requests on SSE streams."* The GET endpoint that used to give a server a socket to write to unbidden was **deleted** |
| 4 | Three inbound "Google Chat channel" bridges exist, but all are zero-star single-commit repos riding a **Claude-Code-proprietary channel extension**, not standard MCP; none allowlisted. One has a `CARD_CLICKED` branch that replies *"Button clicks are not yet supported."* **None acts on one** | high — the exception that proves finding 3 |
| 5 | Registry sweep is a **confirmed negative** across `registry.modelcontextprotocol.io`, `modelcontextprotocol/servers` README, and PulseMCP | high |
| 6 | ⚠ **`mcp.so` returned HTTP 403 and remains unsearched** | **an open gap, recorded rather than papered over.** It does not change any decision below, because no decision here depends on the ecosystem being empty |
| 7 | ~12 long-tail repos were classified **from READMEs, not source** | **provisional.** The researcher's own absolute claims were corrected twice by source-reading, which is exactly why this row exists |

**Adjacent prior art, cited and deliberately NOT scoped in:**
`ikujyh/openclaw-gchat-router` (FastAPI, production since early 2026;
independently hit the add-ons envelope problem and documents it) and
`vercel/chat`'s `@chat-adapter/gchat` (Cards v2, dialogs, Workspace Events). Both
are worth reading if the gateway's Chat handling is ever revisited. Neither is
MCP, and neither is a dependency of this work.

**What finding 3 means for this project, stated once and relied on throughout.**
The gateway's *outbound* direction maps onto MCP cleanly — a tool call is a
request, a delivery is a response. Its *inbound* direction does not map at all:
there is no mechanism by which the gateway could tell an MCP client "a human
replied." An MCP inbound tool can only ever be **polling that an agent must
remember to do**. That asymmetry is not a limitation of our implementation and
cannot be engineered around; it is why §7 recommends what it recommends, and it
is why the gateway's real inbound story stays `callback_url` push and
`GET /v1/inbox`, both of which are better at it.

---

## 2. What this actually is

**An MCP server surface is another ingress to the send path the gateway already
has.** It is not a new capability, not a new tier, and not a new transport to
Google. Concretely:

```
existing:   consumer program ──HTTP──▶ POST /v1/messages ──▶ registry.identity_for ──▶ adapter.send
new:        MCP client       ──HTTP──▶ POST /mcp tools/call ──▶ registry.identity_for ──▶ adapter.send
                                        └── same authenticate(), same allowlist, same adapter
```

Everything below the second arrow is **unchanged code**. That is the entire
architectural claim of this design, and §12 measures it rather than asserting it.

**What an MCP caller inherits — precisely, because the loose version is wrong.**
The brief that commissioned this work said MCP callers would inherit "identity
allowlists, dedupe, durable retry, and audit journalling." Two of those four do
**not** live on `POST /v1/messages`:

| Property | `/v1/messages` (what `send_message` reuses) | `/v1/notify` |
|---|---|---|
| identity allowlist (rule #4) | ✅ `registry.identity_for` | ✅ |
| audit / delivery log | ✅ `DeliveryLog.record` | ✅ |
| **dedupe windows** | ❌ — no `Deduper` on this path | ✅ |
| **durable retry + journal replay** | ❌ — **synchronous, one attempt** | ✅ `Dispatcher.enqueue` |

So a `send_message` tool built on `/v1/messages` inherits **two** of the four.
This is not a defect to fix; §8 argues it is the right trade for an *interactive*
caller, and the reasoning turns on a point worth stating plainly: **durable retry
exists for unattended producers** — aitrader's 3 a.m. alert with nobody watching.
An LLM agent is attended by definition and is itself a retry mechanism: it sees a
502 synchronously and can act. What it cannot act on is a `202 enqueued`.

---

## 3. Hard rule #1 — is an MCP tool signature a schema the gateway must not own?

This is the sharpest question in the design and it deserves the full argument
rather than a reassurance.

### The case that it IS a violation

A tool's `inputSchema` is a JSON Schema the gateway publishes, and a tool's
`description` is a **prompt** — it is read by a model deciding when to call. Both
are places app-domain knowledge leaks in, and the leak is invisible in review
because it reads as helpfulness. A tool called `send_trade_alert(ticker, price,
action)` would be aitrader's domain schema living in the gateway. So would a
`description` reading *"use this when a position crosses a risk threshold."* Rule
#1 says the answer to both is no.

### The case that it is NOT

`OutboundMessage` is **already** a published schema. FastAPI serves it at
`/openapi.json` today, and `docs/integration-guide.md` documents it by example.
An MCP `inputSchema` that is *the same schema in a second serialization* adds no
new knowledge to the gateway. Rule #1's own text names `envelope.py` as "the only
shared shape"; re-rendering that shape is not owning a second one.

### The discriminating rule, and it is mechanical

The two cases differ by exactly one thing: **whether the schema was derived or
hand-authored.** A derived schema cannot drift into app domain, because its only
source is a model the gateway already owns. A hand-authored one has no such
floor, and *every* violation above requires someone to type a field name.

**So the rule this design adopts, and the plan enforces with a test:**

> The MCP tool's `inputSchema` is **generated** from
> `OutboundMessage.model_json_schema()`. No property is hand-written. The only
> permitted mutation is to narrow a field against data the gateway already owns
> — specifically, setting `identity.enum` from the registry's per-app allowlist.

Measured (§12.1): `OutboundMessage.model_json_schema()` emits a **flat** schema —
no `$defs`, no `$ref` — so it is usable as `inputSchema` verbatim, with no
flattening pass that could become a place to edit things.

**Two corollaries, both binding on the Builder:**

1. **`cards` is exposed verbatim, as `{"type":"array","items":{"type":"object"}}`,
   and stays that way.** The temptation this creates is specific and predictable:
   a model handed an untyped `cards` array will either ignore it or hallucinate,
   and the fix that suggests itself is to teach the gateway Cards v2 — a card
   *builder*, an `add_button` tool, a simplified card schema. **That is rule #1
   telling you no.** The gateway's total knowledge of card structure today is one
   validator asserting `"card" in entry` (`envelope.py::OutboundMessage._cards_shape`), and this row must not
   add a second byte to it. Trimming `cards` out of the schema is also refused,
   for a subtler reason: `del schema["properties"]["cards"]` is hand-authoring
   wearing a derivation's clothes, and it puts the first edit on the slope.
2. **Tool descriptions describe transport, not occasions.** *"Deliver a message to
   Google Chat as one of the identities your API key is allowed to send as"* is
   transport. *"Use this to notify the team when a build fails"* is an occasion,
   and an occasion is app domain. This one is not mechanically enforceable and is
   stated as a review rule, honestly labelled as weaker than the schema rule.

---

## 4. Decision D2 — process model

Three candidates were named in the brief. One is eliminated by measurement, one
is a genuinely good alternative, and one is recommended.

### (c) A separate container on the NAS — **eliminated**

`docs/deploy/nas.md` is unusually specific about what a second deploy artifact
costs on that box, and the total is disqualifying:

| Cost | Source |
|---|---|
| **No registry exists.** nas.md's own D4 chose local `docker build` on the box; `pull_policy: missing` means an image is never pulled. A second container means a second local build, or reopening D4 — which the doc frames as "reintroduces a credential and an external dependency into the deploy path" | nas.md §4, §9 |
| A **12th** `app.query` entry. §1's own cautionary story is about a stale stack count in a heading; this increments it again | nas.md §1, §7, §10 |
| Its own **measured-free port**, and its own LAN-bind demonstration — *"LAN-only is a property of the socket here, not a convention"* | nas.md §10 decision-1 probes |
| A `nas/compose/<app>.config.json` appears **automatically** in the homelab repo on the next capture — nobody opts in — under a redactor **measured broken for this project's key shapes** | nas.md §7; `env_file.py`'s docstring |
| Its own §9 artifact set: service doc, `SECRETS.template.md` rows, restore wrapper, DASHBOARDS entry, Homepage tile. Five artifacts, another homelab PR | nas.md §9 |
| ⚠ **The runbook has no guidance at all** on a second `services:` key, a sidecar, `networks:`, or `depends_on:` — there is no `networks:` key in §5's document at all. And a new app rooted outside `/mnt/datapool/apps/chat-gateway/**` may itself be a 🛑 handoff under the standing scope rules | nas.md — **stated absence**, §5, §2, §11 |

Against all of that, (c) buys nothing that (a) does not. It is not a close call.

### (b′) A stdio MCP mode of the existing CLI — **the real alternative**

Not the brief's option (b) exactly. The brief proposed "a separate stdio MCP
server **package** in-repo." The better form of the same idea is a **CLI verb on
the package that already exists**: `python3 -m chat_gateway mcp-stdio`, stdlib-only,
wrapping `GatewayClient` (which is already stdlib-only by design), reading
JSON-RPC from stdin. No new package, no new dependency, no new container, and
**no new route on the gateway at all**.

Its advantages are real and should not be talked past:

- **It requires no gateway change, therefore no rebuild, therefore no redeploy.**
  It could ship today, while CG-59's soak is still accruing uptime.
- **stdio is universally supported**; remote HTTP with custom headers is not.
- The rule #1 / #4 / #6 analysis collapses to *"it is a client of the published
  API"* — the gateway grows no authenticated surface whatsoever.

Its disadvantage is distribution: every machine running an MCP client needs the
package installed and configured, and the API key then lives in a second place.

### (a) An in-process route mounted on the existing FastAPI app — **recommended**

`POST /mcp` (and a `GET /mcp` that answers 405), in a new module, mounted by
`create_app`, behind the **existing** auth dependency.

**Why:**

1. **Zero new deploy artifact.** The NAS table above is the whole argument, and
   (a) is the only option that touches none of it. No new port, no new stack, no
   new capture file, no new homelab artifact, no new secret.
2. **Rule #4 is satisfied by reuse, not by new code** — the strongest available
   form. §12.2 measures the real `authenticate()` refusing an unkeyed MCP request
   with a 401 and the real `registry.identity_for` refusing a forbidden identity,
   through the real `create_app`. No second auth path exists to drift.
3. **It matches the user's settled decision 1** — *"arbitrary external agents get
   a registry identity like any tenant"*. A tenant connects to the gateway; it
   does not install a shim.
4. **It is the only option where the gateway can enforce anything MCP-specific** —
   a per-app tool list (§5), an `allow_mcp` opt-out if D7 wants one, a `/healthz`
   field that proves the deployed image has it (§10).
5. **Reach**: one config block on any LAN machine. No Python on the client, no
   install, no per-machine drift.

**What it costs, stated rather than argued away.** It requires a rebuild and
`app.redeploy`, which restarts the container — and *"the container's uninterrupted
uptime **is** the evidence CG-59's soak is accruing"* (nas.md §9 hazard 2). That
constraint has a **documented expiry**: the soak stops on its own 72 h after
`2026-08-05T16:34:10Z`, i.e. around **2026-08-08**, well before this row could be
specced, planned, built, reviewed and merged. So it is a **sequencing note in the
queue row, not a blocker** — and the row must say so explicitly rather than
leaving a Builder to discover it.

⚠ **CORRECTED 2026-08-10 — the paragraph above reasoned correctly to an answer
that was right for the wrong reason, and the difference is load-bearing.** It
predicted the constraint would expire *on schedule*. It did not expire; **it
broke** — the `/healthz` sampling stopped on `2026-08-06T21:02:42Z`, a day into a
three-day run (CG-82). The conclusion (*"sequencing note, not a blocker"*) survives
untouched. ⚠ **What does NOT survive is the implied safety of rebuilding freely:**
the container's `RestartCount: 0` since `2026-08-05T16:34:10Z` is now the **only**
long-run evidence that exists, it is ~5 days — longer than the soak ever asked for
— and this row's rebuild ends it. **Capture it first: CG-82 task 1, one `docker
inspect`.** The distinction that matters: what died was the *sampling*, not the
*uptime*, and a reader who collapses those two will throw the survivor away.

**Two things that fall out of that redeploy, and both are bonuses the row should
claim:**

- ⚠ **It is the vehicle that finally lands `/healthz?strict=1` on the box.** CG-59
  shipped `?strict=1` to `main` on 2026-08-05, but the running container predates
  it and answers **200** to `?strict=1` today, because FastAPI ignores an
  undeclared query parameter. nas.md §9 hazard 1 sets the order — *rebuild, verify
  503 on a degraded boot, then repoint the Homepage tile* — and deliberately does
  not schedule the rebuild. **CG-80's redeploy is that rebuild.** The row inherits
  the verification step and the homelab handoff.
- **It is the first real exercise of `app.redeploy`.** nas.md §10 deviation 6
  records that CG-55 used `docker kill` + `app.start` because fact 4 needed a
  crash, so *"`app.redeploy` remains the documented upgrade step and is **untested
  by this run**."* CG-80 tests it.

**What would flip this decision to (b′):** a target MCP client turning out not to
support HTTP transport with static headers. The tool definitions and the
`send_message` implementation are transport-agnostic in the plan's structure
precisely so that a later (b′) reuses them rather than forking them.

---

## 5. Auth (hard rule #4) and hard rule #2

### Rule #4 — per-app keys, no wildcards

An MCP HTTP request carries headers, so the credential is the one the gateway
already uses: `Authorization: Bearer <per-app key>`. **The MCP route depends on
the same `authenticate(registry, authorization)`** that every `/v1/` route
depends on. There is no MCP key, no shared key, no service token.

**Every MCP request is authenticated, including `initialize`.** The alternative —
letting `initialize` through unauthenticated so a client can discover the server
before presenting a key — was considered and rejected: it discloses the server's
existence and version to an unauthenticated LAN caller for no benefit, and a 401
at `initialize` is the earliest and most legible possible failure. Measured
(§12.2): missing key → `401` with `WWW-Authenticate: Bearer`.

**Is a static bearer conformant MCP?** The MCP authorization framework is built
on OAuth 2.1, and it is a **SHOULD** for HTTP transports, not a MUST — a server
may use another credential scheme. Client-side this is not a compatibility
question at all: Claude Code's HTTP transport takes static headers as a
first-class configuration, with `${VAR}` expansion so the key stays out of a
committed `.mcp.json`. ⚠ **These two claims are doc-derived, not measured by this
repo**, and the plan's UAT step is where a real client proves them. See §13.

**One rule-#4 strengthening this design gets for free, and it is worth having.**
Because every request is authenticated, `tools/list` knows *which app is asking* —
so `send_message`'s `identity` property carries an **`enum` of exactly the
identities the registry grants that app**. A model cannot form a call naming
another tenant's identity, because the schema it was given does not contain one.
This is defence in depth, not a replacement: `registry.identity_for` still runs
at `tools/call` and still refuses (§12.2 measures both). **Hiding is not
enforcing** — a client may call a tool it never listed.

### Rule #2 — env-var names only

**This row introduces no secret at all.** Its one new environment variable,
`GATEWAY_ENABLE_MCP` (D5), is a boolean feature flag with no credential value —
the same class as `GATEWAY_ENABLE_PUBSUB`, and like it, it belongs in the NAS
compose document's `environment:` block where it is non-secret and captured. So:

- no new `.env` key on the box,
- no new secret transport over stdin,
- **no new `SECRETS.template.md` row** (nas.md §6's three-row set is unchanged),
- nothing new for the homelab capture script's broken redactor to miss.

⚠ **One thing does not follow from that, and the row must not let it.** *Onboarding
an agent tenant* — registering a new app id so a Claude Code session has its own
key rather than borrowing jobhunt's — **is** a new `CHAT_GATEWAY_API_KEY__<APP>`
secret plus a live-registry edit, and `config/registry.yaml` is gitignored. **A PR
cannot do it.** That is CG-61's entire lesson, restated: *merged* and *in effect*
are two different facts here. See D8.

---

## 6. The protocol surface — and the era split that changes the shape of this row

### 6.1 The finding that arrived after the rest of this spec was drafted

**MCP revision `2026-07-28` is not a point release. It is the largest breaking
change since the protocol launched, and it deletes four things a naive
implementation assumes exist:** `initialize`, `notifications/initialized`, `ping`,
and `Mcp-Session-Id`. The `GET` SSE endpoint is gone too.

> "Make MCP stateless: remove the `initialize`/`notifications/initialized`
> handshake." — 2026-07-28 changelog, major change #2
>
> "Remove protocol-level sessions and the `Mcp-Session-Id` header from the
> Streamable HTTP transport." — major change #1
>
> "Add `server/discover`: servers **MUST** implement this RPC…" — major change #3

The spec's own terminology for the split: **"Modern"** = `2026-07-28` and later
(per-request `_meta`, no handshake); **"Legacy"** = `2025-11-25` and earlier
(`initialize` handshake); **"Dual-era"** = serves both.

⚠ **And the compatibility matrix has no mercy in either direction: modern client →
legacy server FAILS, and legacy client → modern server FAILS.** Picking one era
makes the gateway invisible to clients speaking the other. That is what turns
"which era" from an implementation detail into **D4a**, a decision the user should
see (§14).

⚠ **What this spec pins and what it refuses to pin.** `2025-11-25` and
`2026-07-28` are *dated, immutable revision identifiers* and are named here
because the design depends on them. **Which revision is "current" is a moving
external fact and gets no copy in this repo's prose** — `draft` is in progress,
and a sentence here claiming a latest would be the two-homes-for-a-moving-fact
drift `CLAUDE.md` opens with, against a fact that is not even ours. The plan's
Task 1 requires the Builder to re-read the revision list at implementation time.

### 6.2 What we implement

**A stateless, tools-only, JSON-only server, dual-era on one endpoint** — a shape
the spec explicitly sanctions: *"A dual-era server **MAY** serve both eras
concurrently on the same endpoint or process."* The discriminator is a single
branch at the top of the handler: a body carrying `_meta` with
`io.modelcontextprotocol/protocolVersion` is modern; a body whose `method` is
`initialize` is legacy.

| Aspect | Choice | Note |
|---|---|---|
| Transport | Streamable HTTP, single endpoint `POST /mcp` | the only remote transport with broad client support |
| SSE | **none.** `GET /mcp` → **405** | conformant in *both* eras — 2025-11-25 makes 405 the explicit alternative to an SSE stream, and 2026-07-28's backward-compat section says a modern-only server SHOULD answer GET and DELETE with 405 |
| Sessions | **none.** No `Mcp-Session-Id` issued; one **ignored** if a stale client sends it | required behaviour under modern; permitted under legacy |
| Capabilities | `{"tools": {}}` only | no resources, prompts, logging, completions. ⚠ `listChanged` **omitted**, which is what keeps `subscriptions/listen` and every notification stream out of scope |
| Legacy methods | `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call` | `notifications/initialized` → **202, empty body** |
| Modern methods | `server/discover`, `tools/list`, `tools/call` | `server/discover` is a **MUST** for a modern server |
| Batching | **refused** | removed from the protocol in `2025-06-18` and re-stated in `2026-07-28` as a transport MUST: the POST body "**MUST** be a single JSON-RPC request or notification" |
| Deprecated features | none implemented | sampling, roots and logging are all **Deprecated as of 2026-07-28**. Declining them is now aligned with the protocol's own direction, not merely YAGNI |

### 6.3 Modern-era requirements that a hand-rolled server will otherwise miss

These are the non-obvious ones. Each becomes a plan task and a test.

| # | Requirement | Consequence for us |
|---|---|---|
| 1 | **`Origin` MUST be validated**; if present and invalid → **HTTP 403**. When running locally a server SHOULD bind to loopback rather than all interfaces | A genuine security MUST, cheap to honour, and **it was missing from this spec's first draft.** Note the exact conditional: the MUST fires only when `Origin` **is present and invalid** — a missing `Origin` (normal for non-browser clients) is not covered. ⚠ The bind half is already satisfied one layer out and *better*: CG-55 publishes the container port on the **LAN address**, so `127.0.0.1` and the tailnet address both refuse (nas.md §10). `__main__.py::main`'s `uvicorn.run` binds `0.0.0.0` *inside* the container, which is correct — the Docker publish is the boundary |
| 2 | **Three headers are REQUIRED** on every modern POST: `MCP-Protocol-Version`, `Mcp-Method`, and `Mcp-Name` (for `tools/call`) — and the server **MUST** reject a mismatch against the body with **400** + `-32020` (`HeaderMismatch`). Base64 sentinel values (`=?base64?…?=`) MUST be decoded before comparing | The single largest chunk of incidental work in a modern implementation, with no legacy analogue. ✅ **One thing makes it cheaper for us:** our only tool name is `send_message`, which is inside the header-safe `[A-Za-z0-9_.-]` set, so no client ever needs the Base64 sentinel form for `Mcp-Name` — but the decoder is still implemented, because *the client* decides |
| 3 | **Unimplemented RPC method → HTTP 404 + `-32601`**, not the usual JSON-RPC reflex of 200-with-an-error-body | Gets `resources/list`, `prompts/list`, `subscriptions/listen` right. Dual-era client probes misclassify a server that returns 200 here |
| 4 | **Unsupported protocol version → 400 + `-32022`** with `data.supported` listing our versions; **missing required `_meta` → 400 + `-32602`** | Honest negotiation. A server that silently echoes back whatever version it was asked for is the failure this rule exists to stop |
| 5 | **`tools/list` results MUST carry `ttlMs` and `cacheScope`** | ⚠ **And ours MUST be `"private"`, not `"public"`.** `cacheScope: "public"` asserts the response contains no user-specific data and may be cached *across authorization contexts*. §5's per-app `identity.enum` means **our tool list varies by API key**, so `"public"` would let an intermediary serve one tenant's identity allowlist to another. **That is a hard-rule-#4 violation delivered by a cache header**, and it is the sharpest non-obvious correctness finding in this section |
| 6 | Every modern result MUST carry `resultType` (`"complete"` for us) | mechanical |
| 7 | `Accept` imposes **no** server obligation | We may ignore it and always return `application/json`. There is no `406` requirement in either revision. Recorded because the opposite is widely assumed |

### 6.4 Tool annotations — declared explicitly, not left to defaults

`send_message` will carry:

```
"annotations": {"readOnlyHint": false, "destructiveHint": true,
                "idempotentHint": false, "openWorldHint": true}
```

The spec's defaults would produce the same four values — `destructiveHint` and
`openWorldHint` both default to **`true`** — so this is redundant on the wire and
deliberate anyway. A tool that posts irreversibly into a human's chat space, twice
if called twice, should **say so** rather than have a reader derive it from a
default table. That is the same reasoning `thread_started` gets beside
`thread_alive` at `/healthz`.

### 6.5 Error mapping — five taxonomies, not one

MCP separates a *protocol* error (malformed request, unknown method — a JSON-RPC
`error`) from a *tool* error (the tool ran and refused — a normal `result` with
`isError: true`). The spec is unusually direct about why:

> "Any errors that originate from the tool **SHOULD** be reported inside the
> result object, with `isError` set to true, _not_ as an MCP protocol-level error
> response. **Otherwise, the LLM would not be able to see that an error occurred
> and self-correct.**"

| Condition | HTTP | Body |
|---|---|---|
| bad/absent bearer key | **401** | `WWW-Authenticate: Bearer` — **with no `resource_metadata` parameter** (§5) |
| `Origin` present and invalid | **403** | JSON-RPC error with no `id` |
| header/body mismatch, or missing required `_meta` | **400** | `-32020` / `-32602` |
| unsupported protocol version | **400** | `-32022` + `data.supported` |
| unimplemented RPC method | **404** | `-32601` |
| JSON-RPC batch array | 400 | `-32600` |
| **unknown tool name** | **200** | `-32602` — ⚠ *not* `-32601`; that code is reserved for an unimplemented **method** and now carries a 404 |
| **identity not granted to this app** (rule #4) | 200 | `result`, `isError: true`, carrying `registry.identity_for`'s own message |
| arguments fail `OutboundMessage` validation | 200 | `result`, `isError: true` |
| adapter raises (Google failed) | 200 | `result`, `isError: true` |

The rule-#4 refusal is deliberately a **tool** error: the model asked a legitimate
question and got a legitimate refusal naming what it *may* use, so it can correct
itself. Measured in §12.2 — the text it receives is the registry's own
`app 'X' may not send as 'Y' (allowed: …)`.

⚠ **One hard-rule-#2 constraint on the last row.** An adapter exception's message
must go through `errors.describe_exception` before it reaches an MCP response, on
exactly the CG-29 reasoning: *an exception message is printed in full only if this
repo wrote every byte of it.* **An MCP tool result is a print site — arguably the
most dangerous one this repo has**, because its destination is a model's context
window and, from there, a transcript that leaves the building. `describe_exception`
already exists and already knows which classes qualify; this row must use it and
must not grow a second allowlist.

### 6.6 Token passthrough — the one authorization MUST NOT that binds us

The authorization spec forbids "token passthrough" unconditionally:

> "MCP servers **MUST** only accept tokens that are valid for use with their own
> resources. **MCP servers MUST NOT accept or transit any other tokens.** … If the
> MCP server makes requests to upstream APIs … **The MCP server MUST NOT pass
> through the token it received from the MCP client.**"

**The gateway satisfies this structurally, and it is worth stating so nobody
"improves" it later.** The gateway mints its own per-app keys
(`auth.mint_key`) and validates them against its own registry, so it is
simultaneously issuer and audience. Its upstream credentials — a tier-1 webhook
URL, a tier-2 service-account token — are **the gateway's own**, resolved from the
env by `Identity.webhook_url()` and `GoogleServiceAccountTokens`, and no MCP
caller's credential has ever reached an adapter. Hard rule #2 is what keeps it
that way.

---

## 7. Decision D1 — inbound scope. Both are scoped; one is recommended.

The brief required both send-only and send + read-own-inbox to be scoped, the
rule-#6 analysis to be made explicit, and *"it is gated on the caller's own
`allow_inbound`"* to be treated as an argument rather than as self-evident. This
section does that.

### 7.1 The tempting argument, stated at its strongest

> A `read_inbox` tool is `GET /v1/inbox` through a different door. It runs
> `registry.apps[app_id].allow_inbound` exactly as the HTTP route does.
> `aitrader` is refused identically. **No tenant's authorization changes**, so
> rule #6 is untouched and no sign-off is needed.

Every sentence of that is true. It is still not sufficient, for three separate
reasons, and they are of three different kinds.

### 7.2 Hole 1 — a data-loss defect, and it is dispositive on its own

**`Inbox.poll` drains.** It clears the app's queue (`q.clear()`), closes the ids
in the journal, and compacts. At-most-once, by design and documented as such;
CG-56 is the queued row that would change it to ack-based at-least-once, and
**CG-56 has not shipped.**

So an MCP `read_inbox` tool and a tenant's production poller are **competing
destructive consumers of one queue**. A model calling `read_inbox` out of
curiosity would *silently delete* replies that jobhunt's poller was about to
collect, and jobhunt would have no way to detect it — the audit trail records
what **arrived**, never what left, which is `journal.py`'s own recorded point.

This is not a policy question and not a rule-#6 question. It is a defect, it is
in the class of failure this project has spent five rows closing, and it settles
the sequencing on its own: **`read_inbox` depends on CG-56.**

### 7.3 Hole 2 — the *consumer* of the data changes, even though the *authorization*
does not

Rule #6's mechanism is registry opt-in. Its **purpose** is a tenant controlling
where its inbound goes. Through MCP, the same bytes that today land in a program
the tenant wrote land instead in **a model's context window**, and from there in
whatever transcript that model's host keeps. The registry grants inbound to an
*app id*, and an app id is an API key — so if the user pastes jobhunt's key into
an MCP client config, jobhunt's inbound now flows somewhere its contract never
contemplated.

**The counter-argument is decent and must be recorded:** this was already
possible. Nothing stopped a tenant piping `GET /v1/inbox` into a model, and the
gateway never controlled that. True — but the gateway would now be **building the
pipe**, which is a different act from not preventing it. That is a judgment about
what this project is willing to make easy, and it is the user's to make, not a
Planner's.

### 7.4 Hole 3 — whether a third door changes the enumeration

Rule #6 is written as an enumeration: *"Two opt-in paths exist: passive inbox
polling, and per-tenant `callback_url` push."* Adding a third way into the same
room arguably changes that sentence even when the lock is identical — and
amending it is itself the sign-off trigger, since the rule closes with *"Do not
widen any tenant's inbound surface without explicit user sign-off naming this
rule."*

**The counter is also decent, and it is coupled to D2 in a way worth seeing.**
Under **(b′)**, a stdio shim calling `GET /v1/inbox` is unambiguously *not* a
third path — it is the first path with a different client library, exactly as
`client.py` is not a path. The gateway gains no inbound code at all. Under
**(a)**, the recommended option, the gateway grows a new authenticated route that
reads the inbox, and the enumeration argument bites harder. **Choosing (a) makes
the rule-#6 question sharper, not softer.**

### 7.5 What it means for `aitrader` specifically

Mechanically: nothing. `allow_inbound: false`, so under §7.6's per-app tool list
`read_inbox` would never appear in its `tools/list` at all, and calling it anyway
would be refused by the same check the HTTP route uses.

**Contractually: something.** `docs/consumers/aitrader.md` §8 is not a summary —
it is a four-row enumeration of *"the mechanism exists, and this app is locked out
of **every part of it** — at load time, at the door, and at dispatch"*, explicitly
framed as *"a stronger claim than 'no such mechanism exists', because it survives
the gateway growing more inbound features."* This is the gateway growing an
inbound feature. Shipping `read_inbox` obliges that table to gain a **fifth row**
and the surrounding prose to be re-verified against code. Per CG-69's category
(a), a live claim falsified by a later code change is *the* failure mode this repo
keeps rediscovering, and a real-money tenant's security table is the worst place
for it.

**Send-only leaves that table at four rows and unamended.** That is a concrete,
checkable benefit of the recommendation, not a rhetorical one.

⚠ **One thing send-only does NOT leave untouched, and it should be named rather
than skipped.** The MCP surface makes **every registered identity model-addressable
to whoever holds the key** — including `aitrader-alerts` and `aitrader-reports`.
That is strictly outbound and does not touch rule #6 or aitrader's §8 guarantee,
and it follows directly from the user's settled decision 1 ("one surface, no
distinction"). It is flagged here, not reopened, because a real-money tenant's
spaces acquiring a model-writable path is a new fact about that deployment even
when every rule holds. **D7 is the knob if the user wants one.**

### 7.6 Recommendation

**Send-only in CG-80. File `read_inbox` as CG-81, not queued.**

1. §7.2 is dispositive and is not a matter of taste.
2. §7.4's ambiguity is genuine, and rule #6's own text says the tie-break is the
   user's explicit sign-off. Shipping send-only lets the entire MCP surface land
   **without needing that sign-off**, which de-risks the whole arc.
3. Finding 3: MCP has no push. `read_inbox` can only be polling a model must
   remember to do — a weak product against `callback_url`, which already works and
   which jobhunt already uses.
4. It keeps `aitrader.md` §8 at four rows.

**CG-81's design, so the decision is informed rather than deferred blind.** If the
user signs off: one tool, `read_inbox`, no arguments; present in `tools/list` only
for apps with `allow_inbound: true`; `registry.apps[app_id].allow_inbound` re-checked
at `tools/call` regardless; returns the same `replies` payload `GET /v1/inbox`
returns; **must** use CG-56's non-draining read with an explicit `ack` tool, never
the draining default; `aitrader.md` §8 gains its fifth row **in the same PR**, not a
follow-up (CG-75's precedent: rule #5 does not permit leaving a false statement
standing for the duration of a second PR). Depends on **CG-56**. Merge gate: **yes**.

---

## 8. Decision D3 — how many tools

Three sizes were considered. Ruthless YAGNI applied.

| Tool | Verdict | Reasoning |
|---|---|---|
| **`send_message`** → `/v1/messages` | ✅ **ship** | the whole point. Synchronous, returns `delivered`/`failed` — an agent gets an answer it can act on |
| `list_identities` → `/v1/identities` | ❌ cut | **the `enum` makes it redundant.** §5's per-app `identity.enum`, rendered with each identity's `display`, `mode` and readiness (§12.1 shows the exact string), puts everything an agent needs to choose *inside the tool it is already looking at* — one round trip instead of two. The one thing it also publishes, `interaction.routing_target`, is only useful for building interactive cards, whose interactions come back through inbound, which we are deferring |
| `notify` → `/v1/notify` | ❌ cut | it returns `202 enqueued`, which an agent cannot act on, and it would need a paired `check_deliveries` tool to become honest. It also requires a `routes:` block two of the three registered consumers do not have. §2's table is the deeper reason: durable retry serves *unattended* producers, and an agent is attended |
| `check_deliveries` → `/v1/deliveries` | ❌ cut | exists only to make `notify` honest. `notify` is cut |
| `heartbeat` → `/v1/heartbeat` | ❌ cut — **and actively harmful** | a dead-man check registered by an ephemeral agent session goes missed the moment the session ends, and then **pages a human, daily**. This is the one omission that is a safety decision rather than a scope decision |
| `read_inbox` → `/v1/inbox` | ⏸ deferred | §7 |

**Recommendation: one tool.** Every additional tool is another thing a model can
pick wrongly, and the failure mode of picking wrongly here is a message arriving
in the wrong space under the wrong identity.

**The residual risk of one tool, recorded:** `tools/list` is fetched once per
session by most clients, so the `enum` is a snapshot. It can only go stale
relative to a registry change, and a registry change requires a gateway restart
(`load_registry` runs in `build_runtime`), which drops the session and forces a
re-list. Non-issue on today's architecture — recorded so a future change to
hot-reload the registry knows it invalidates this.

---

## 9. Decisions D4a and D4 — which era, and hand-rolled or the SDK?

### D4a — which era(s) to speak. **Recommendation: dual-era.**

§6.1's compatibility matrix makes this a real choice with a real failure mode:
pick one era and the gateway is **invisible** to clients speaking the other, with
no graceful degradation in either direction.

- **Legacy-only** (`2025-11-25`) is the cheapest and is what §12.2's prototype
  already does. It bets that the clients we care about have not moved. ⚠ **That
  bet is against the direction of travel** — the four Tier 1 SDKs already speak
  `2026-07-28`.
- **Modern-only** (`2026-07-28`) is correct-looking and the highest-risk: a
  client that has not upgraded simply cannot connect, and the revision is **nine
  days old** as of this spec.
- **Dual-era** costs one discriminator branch and one extra result shape, and it
  is the option the spec itself sanctions on a single endpoint. It is the only
  one whose failure mode is "some extra code" rather than "silently unreachable."

The dual-era cost is honest but bounded: the era branch, `server/discover`,
`resultType`/`ttlMs`/`cacheScope`, the three-header cross-check with Base64
sentinel decoding, and the 400/403/404 status mapping. **That is roughly 150–200
LOC on top of the legacy path, essentially all of it mechanical and all of it
offline-testable.**

### D4 — hand-rolled, or the `mcp` Python SDK?

**Recommendation: still hand-rolled, on `fastapi` + `pydantic`, no new package —
but D4a makes this closer than it looked, and that should be visible.**

**For hand-rolling:**

- Even dual-era, the surface is bounded and fully enumerable: §6.2's two method
  sets, §6.3's seven requirements, §6.5's ten error rows. Every one of them is a
  test.
- This repo has **seven runtime dependencies**, all boring, and a client that is
  **stdlib-only on purpose**. A stdio variant (b′, §4) would have to be
  stdlib-only too; an SDK-based server cannot be shared with one.
- The SDK's server wants to own an ASGI app or be mounted through its own session
  manager, bringing `anyio` task groups and a lifespan requirement into a process
  with **four daemon threads and a hand-ordered boot** (`journal replay → inbox
  restore → retention sweep → serve`).
- It brings its own authorization model, which we would bypass to reuse
  `authenticate()` — and §5's whole argument is that rule #4 is satisfied by
  **reuse**, not by a second implementation.
- The image is built on the box with **no registry** (nas.md §4). Every dependency
  is weight in a 174 MB image and in an offline suite.
- Culturally decisive: this repo's posture is that it owns every byte it emits —
  `errors.py`'s allowlist, hard rule #3's flag discipline, a stdlib-only client.
  A file it fully controls and fully pins with wire-shape tests is more in
  character than a dependency whose behaviour it would have to characterize.

**Against hand-rolling, stated honestly and NOT talked down:**

- A protocol that had its largest-ever breaking revision nine days ago will move
  again — `draft` is in progress. The SDK absorbs that; we would not.
- §6.3's header cross-check and status mapping are exactly the kind of incidental
  conformance work an SDK exists to remove.
- **The counter-risk is symmetric, which is why the recommendation survives:** an
  SDK upgrade can change wire behaviour without a line of our code changing, and
  this repo has no CI to the box and a manual rebuild (nas.md §4). A silent wire
  change arriving through a dependency bump is a worse failure here than an
  explicit one arriving through an edit.

⚠ **No ⚠ flag word is invented for any of this.** The temptation is obvious — an
MCP surface no real client has touched is exactly the epistemic state ⚠
LIVE-UNVERIFIED exists to mark. **Do not.** Hard rule #3 admits one further flag
word "and only one", and the ledger is specifically about *Google seams*. This is
not one. The "no client has connected yet" fact lives in the plan's UAT step and
in the queue row's exit condition, where it can be discharged, and **nowhere
else**.

---

## 10. Hard rule #5 — what `/healthz` gains, decided one field at a time

This repo has a standing requirement that every counter's degrade-or-not verdict
is reasoned individually. That requirement is met below — including by declining
to add counters, with the reasoning stated rather than the question skipped.

### No counters. Here is why, and it is not laziness

Rule #5 exists because of a **silent** failure: a background loop freezing at
plausible values while a hardcoded `OK` covered for it. Every counter this repo
has added since guards a loop, a thread, a queue or a disk write — something that
can fail while nobody is looking.

**The MCP route has none of those.** It is synchronous request/response inside
uvicorn: no thread, no queue, no journal, no timer, no retry ladder. If it breaks,
the caller gets an error **in the same round trip** — the loud direction. There is
no state in which it is quietly not working while `/healthz` says otherwise.

Adding an `mcp_calls` or `mcp_errors` counter would therefore publish traffic
volume on an **unauthenticated** endpoint for no diagnostic gain — the exact trade
CG-12 rejected when it refused to record suppressed inbound, and the exact
threshold-creep CG-12's comment closes with *"Do not add a threshold here."*

### One field, and it is a config echo: `mcp`

```
"mcp": {"enabled": <bool>, "tools": [<tool names>]}
```

**Why this one earns its place**, when the counters do not: the sharpest thing
this project learned in the last week is that **the deployed container is not
necessarily running the code you think it is**. CG-59 shipped `?strict=1` to
`main` and the box answered `200` to `?strict=1` anyway, because FastAPI ignores
an undeclared query parameter — *"repointing the tile before the image is rebuilt
changes nothing while looking exactly like the fix."* A `/healthz` field naming
the MCP surface lets an operator confirm a rebuild landed **by reading**, not by
inferring from behaviour that fails identically either way. `tools` is generated
from the tool registry, never a literal list.

**Its `status` interaction, decided explicitly: it is NOT an input to `status`
and adds no `reasons` entry, at any value.** A surface being switched off is a
configuration, not a fault — the same verdict `suppressed_opt_out` got, for the
same stated reason: degrading on a system working as designed teaches an operator
that `degraded` is the normal reading, which is the failure rule #5 was written
after. `subscriber.enabled` is the existing precedent for a config echo that
drives nothing.

**Its disclosure, decided explicitly.** `/healthz` is unauthenticated and, since
CG-55's LAN bind, reachable by anyone on the home LAN. This field tells such a
reader that a model-addressable send surface exists here. That is **strictly less**
than the endpoint already discloses: `registry.health()` publishes every **app
id** and every **identity name** on the same unauthenticated response. Publishing
`mcp.enabled` beside that changes nothing about the disclosure posture, and the
field is a bare boolean plus tool names — no app id, no key, no identity, no
count.

---

## 11. The verification ledger — explicitly nothing, and why the temptation exists

**No ⚠ LIVE-UNVERIFIED or ⚠ SHAPE-VERIFIED flag is cleared, added, re-priced or
reworded by this design or by the PR it produces.** Said explicitly rather than
by silence, because silence on that ledger has shipped false claims here before.

The reasoning, in the ledger's own terms:

- The MCP surface sits **above** `adapters/`. It makes no Google call of its own.
  `send_message` reaches `adapter.send` through the exact path `POST /v1/messages`
  already uses.
- It therefore exercises the same **already-cleared** surfaces (`webhook.send`
  cleared 2026-07-29 and re-confirmed 2026-07-30; `chat_api.send` cleared
  2026-07-29) and leaves the same **still-flagged** branches untouched — every
  adapter's non-200 branch, the `httpx.HTTPError` branches, `chat_api.send()`'s
  `thread.threadKey` branch. **Do not re-summarize that table here; it is in
  `CLAUDE.md`, which says so.**
- ⚠ **The temptation to guard against, named so a Builder recognizes it:** a live
  round-trip through the MCP tool will look like fresh Google evidence. **It is
  not.** It is the same bytes from a different caller, and a clear earned that way
  would be the same category error as claiming a clear from a shape-verified
  offline replay. If a Builder wants to move a ledger row, that is a hard-rule-#3
  question needing the user's explicit sign-off, and it does not belong in this
  row.
- Exposing `cards` touches **none** of the card-shape findings. `CLAUDE.md`'s
  outbound/inbound `parameters` table is a statement about Google's runtimes; this
  row passes `cards` through verbatim as `/v1/messages` already does and adds no
  card knowledge (§3 corollary 1).

---

## 12. What was measured

Both experiments ran on this machine against `f4b9c99`, offline, through the
repo's real classes. The harness is a scratchpad script; it is described
precisely enough to re-run, and the plan turns both into repo tests.

### 12.1 The derived schema is flat and usable verbatim

`OutboundMessage.model_json_schema()` emits **no `$defs` and no `$ref`** —
verified by serializing the result and searching it. Four properties, two
required (`identity`, `text`). `cards` renders as
`{"type":"array","items":{"type":"object","additionalProperties":true}}`.
`thread_key` renders as an `anyOf` with `null`.

This matters to §3: because the schema is already flat, using it as `inputSchema`
needs **no flattening pass** — and a flattening pass would be a place to edit
things, which is precisely the hand-authoring §3 forbids.

With the per-app `enum` applied (§5), `identity` renders as:

> `"enum": ["pm-familyworkspace", "agent-notes"]`, description: *"which registered
> identity to send as. Your key grants exactly these: pm-familyworkspace (PM ·
> familyworkspace; webhook; ready); agent-notes (Agent notes; webhook; NOT
> CONFIGURED)"*

The readiness rendering is live `Identity.env_resolved()`, not a literal — in that
run `SVC_HOOK_AGENT` was deliberately left unset, and the same unset var
independently drove `/healthz` to `degraded`. **The tool schema and `/healthz`
agree because they read the same function**, which is the property worth pinning.

### 12.2 A hand-rolled route mounts on the real `create_app` and drives the real send path

A ~90-line prototype router was mounted on an app built by the **real**
`create_app`, with the repo's own `FakeAdapter` idiom and a real `load_registry`.
Results:

| Probe | Result |
|---|---|
| `POST /mcp` with no `Authorization` | **401**, `WWW-Authenticate: Bearer`, via the real `authenticate()` |
| `initialize` | 200, `capabilities: {"tools": {}}`, `serverInfo` |
| `tools/list` | 200, one tool, schema as §12.1 |
| `tools/call` `send_message` | 200, `isError: false`; **the real `FakeAdapter` received `OutboundMessage(identity='pm-familyworkspace', text='hi', …)`** through the real `registry.identity_for` |
| `tools/call` with an identity the app is not granted | 200, `isError: true`, text = `app 'aiteam-harness' may not send as 'nope' (allowed: pm-familyworkspace, agent-notes)` — the registry's own message, from the real check |
| `GET /mcp` | **405** |
| `POST /v1/messages` afterwards | 200 `delivered` — the existing surface is unaffected by mounting the router |
| `GET /healthz` | 200 — see §12.1 on why `degraded` |

**What this establishes:** (a) the mount point works and does not disturb the
existing app; (b) rule #4 is enforced by the *existing* code on the MCP path, not
by a re-implementation; (c) the tool-error / protocol-error split of §6.5 is
expressible.

⚠ **What it does NOT establish, stated precisely because the prototype is
persuasive and narrower than it looks.** Three things:

1. **It implements the LEGACY era only** — `initialize`, `notifications/initialized`,
   `ping`. That is the era §6.1 discovered is *one of two*, and the prototype was
   written before that finding arrived. **None of §6.3's seven modern requirements
   is exercised by it**: no `server/discover`, no `_meta` validation, no header
   cross-check, no `resultType`/`ttlMs`/`cacheScope`, no 404/400/403 mapping, no
   `Origin` check. The `~90 lines` figure is therefore a **floor on the legacy
   half**, not an estimate of the row — §16 sizes the real thing.
2. **No real MCP client has connected to it.** A `TestClient` proves the server
   answers what we designed; it cannot prove a client accepts it.
3. **It ran against a synthetic registry**, not the live gitignored one — the
   distinction that has caught three people in this project already.

---

## 13. Test plan — the suite stays offline

Every test below runs with no network, in the existing `tests/` layout, using
`fastapi.testclient.TestClient` and the `FakeAdapter` idiom already in
`tests/test_service.py::FakeAdapter`.

**New file `tests/test_mcp.py`:**

1. **Auth**: no header → 401 with `WWW-Authenticate`; wrong key → 401; valid key →
   200. Applied to `initialize` specifically, pinning §5's "every request".
2. **Legacy handshake**: `initialize` returns a protocol version,
   `capabilities.tools`, and `serverInfo`; `notifications/initialized` returns 202
   **with an empty body**; `ping` returns an empty result.
3. **Modern handshake**: `server/discover` returns `resultType: "complete"`,
   `supportedVersions`, `capabilities.tools`, `ttlMs`, `cacheScope`, and
   `serverInfo` under result `_meta`.
4. ⚠ **Era isolation — the test that proves dual-era is real.** The same
   `tools/call` succeeds in both shapes against one endpoint: legacy (no `_meta`,
   no headers) and modern (`_meta` + `MCP-Protocol-Version` + `Mcp-Method` +
   `Mcp-Name`). A modern request missing `_meta` → **400** `-32602`; a legacy
   request is *not* held to the modern header rules.
5. **Modern conformance** (§6.3), one assertion each: `Mcp-Method` disagreeing
   with the body → **400** `-32020`; `Mcp-Name` disagreeing with `params.name` →
   400 `-32020`; a Base64-sentinel `Mcp-Name` decoding to the right value →
   accepted; an unknown protocol version → **400** `-32022` with `data.supported`;
   `resources/list` → **404** `-32601`; an `Origin` header that is present and
   invalid → **403**; a **missing** `Origin` → **not** 403.
6. ⚠ **`cacheScope` is `"private"`** on `tools/list`, in both eras where the field
   exists — pinned with the reasoning in the test name, because §6.3 row 5 makes
   `"public"` a hard-rule-#4 leak delivered by a cache header, and that is
   invisible in review.
7. **Transport shape**: `GET /mcp` → 405. `DELETE /mcp` → 405. A JSON-RPC array
   body → `-32600`. An unknown tool → `-32602` **with HTTP 200** (not 404 — the
   404 rule is for unimplemented *methods*).
8. **Annotations** (§6.4): `send_message` declares all four hints explicitly, and
   `destructiveHint` is `true`.
9. ⚠ **The rule #1 guard, and it is the most important test in the file.** A test
   that asserts the tool's `inputSchema`, with the `enum` and descriptions
   stripped, is **equal to** `OutboundMessage.model_json_schema()` with the same
   stripping. It fails the moment anyone hand-edits a property. This is the
   mechanical form of §3's rule, and it is the same idiom as
   `tests/test_error_surfaces.py` reading construction sites to guard a property
   that lives in prose.
10. **Rule #4, both layers**: the `enum` contains exactly the calling app's granted
    identities and nothing else (two apps in one registry, cross-checked); and a
    `tools/call` naming an ungranted identity is refused **even though the schema
    would have hidden it** — proving hiding is not the enforcement.
11. **Tool-vs-protocol error split**: an ungranted identity, a validation failure,
    and an adapter exception each produce `isError: true` with a JSON-RPC `result`,
    not a JSON-RPC `error`.
12. ⚠ **Rule #2 on the tool-result path**: an adapter raising an exception whose
    message contains a webhook-shaped URL must produce a tool result that does
    **not** contain it — `describe_exception`'s allowlist behaviour, asserted at
    this new print site (§6.5).
13. **`/healthz`**: `mcp.enabled` is `false` by default and `true` when mounted;
    `mcp.tools` lists the tool names; **and `reasons` is unchanged in both cases** —
    the explicit pin of §10's "not an input to `status`".
14. **Feature flag**: with `GATEWAY_ENABLE_MCP` unset, `POST /mcp` is a 404 and
    `/healthz` reports `enabled: false`.
15. **Non-regression**: the existing `/v1/` routes behave identically with the
    router mounted (§12.2's last two probes, as assertions).

**Out of the suite, into the plan's UAT step:** one real MCP client (Claude Code,
HTTP transport, static bearer header) completing a handshake, listing the tool,
and sending a message. This cannot be an offline test and must not be faked into
one. It is the row's exit condition.

---

## 14. Decisions for the user — ✅ ALL EIGHT SIGNED OFF 2026-08-10

⚠ **This heading read *"Decisions for the user"* with eight rows open, and the
queue row read *"⚠ 8 decisions open"*, until 2026-08-10.** The user signed off
every one **at the Planner's recommendation** — *"I'm fine with the defaults
above"* — **D4a included**, which is the one that resized this row (§16). The
three design calls made without asking (below) were presented in the same breath
and **none was overruled**.

**The table is kept exactly as written rather than collapsed into a verdict
column.** A Builder needs the *reasoning*, not the outcome; a row reduced to
"approved" strands the next reader with a decision and no argument.

**Settled earlier, by the user, in the brief — not reopened here:**
(i) audience is *both*, one surface, no distinction; (ii) inbound scope was
explicitly delegated to the Planner (D1 is the answer, not a re-ask); (iii)
process model was explicitly delegated to the Planner (D2 likewise).

⚠ **D7 is DECIDED, but its flagged consequence is not thereby retired — it
MOVES, onto the operator step in D8.** Accepting *no `allow_mcp` flag* means
`aitrader-alerts` and `aitrader-reports` become model-addressable the moment an
operator grants an agent tenant those identities (§7.5). Nobody has decided that
*about aitrader*; it would follow from a default — the same shape as CG-61's
`allow_inbound`, where a default nobody chose governed a live tenant for weeks.
Recorded here so that granting those two identities is a deliberate act with this
paragraph attached rather than a line in a YAML file.

| # | Decision | Recommendation | One-line reasoning |
|---|---|---|---|
| **D1** | **Inbound scope** — send-only, or send + `read_inbox`? | **Send-only.** Design `read_inbox` fully (§7.6) and file it as **CG-81**, not queued: needs explicit hard-rule-#6 sign-off **and** CG-56 | `Inbox.poll` drains, so until CG-56 an MCP reader silently deletes another consumer's replies (§7.2) — a defect, not a policy call |
| **D2** | **Process model** — mounted route / stdio CLI verb / second container | **(a) mounted route** on the existing FastAPI app | zero new deploy artifact on a NAS where a second one is expensive and under-specified (§4), and rule #4 is satisfied by reusing `authenticate()` rather than re-implementing it |
| **D3** | **How many tools** | **One: `send_message`** | the per-app `enum` makes `list_identities` redundant; `notify` returns a 202 an agent cannot act on; a `heartbeat` tool would page a human after an agent session ends (§8) |
| **D4a** | ⚠ **Which protocol era?** `2026-07-28` deleted `initialize`, `ping` and sessions, and **modern↔legacy fails in BOTH directions** (§6.1) | **Dual-era** on one endpoint | picking one era makes the gateway **silently unreachable** to clients speaking the other; dual-era's failure mode is "some extra code" instead. ⚠ **This finding arrived after the rest of this spec was drafted and it resized the row** — see §16 |
| **D4** | **Hand-rolled JSON-RPC, or the `mcp` Python SDK?** | **Hand-rolled** on `fastapi` + `pydantic`, no new dependency — ⚠ **but D4a makes this closer than it first looked** | an SDK brings its own ASGI/session/auth model into a process with four daemon threads and a hand-ordered boot, into a 174 MB image built on a box with no registry (§9). The honest counter — a protocol that broke nine days ago will move again — is answered by the symmetric risk: with no CI to that box, a silent wire change arriving via a dependency bump is worse here than an explicit one arriving via an edit |
| **D5** | **Feature flag** — on by default, or `GATEWAY_ENABLE_MCP`? | **`GATEWAY_ENABLE_MCP`, default OFF** | matches `GATEWAY_ENABLE_PUBSUB`'s posture for a new surface; pairs with §10's health field so "did the rebuild land" and "is it armed" are two separate readable facts |
| **D6** | **`/healthz`** — what, if anything, is added? | **`mcp: {enabled, tools}` and no counters.** Never an input to `status`, no `reasons` entry at any value | a synchronous route has no silent-failure mode for a counter to catch (§10); the config echo earns its place on CG-59's just-learned lesson that a deployed image may not be the one you think |
| **D7** | **A registry `allow_mcp: false` per-app opt-out?** | **No** — the key is the control | YAGNI, and an app that does not want MCP simply keeps its key out of an MCP client. ⚠ **But this is the knob for §7.5's flagged fact** — that `aitrader-alerts` and `aitrader-reports` become model-addressable. Under D2(a) such a flag *is* enforceable, since MCP is a distinguishable route. If the user wants belt-and-braces for a real-money tenant, this is cheap and this is the moment |
| **D8** | **Agent tenant onboarding** — does an agent get its own app id + identity, or reuse an existing tenant's key? | **Its own app id and its own identity** — but as a **documented operator action plus a `registry.example.yaml` example**, never as part of the PR | ⚠ `config/registry.yaml` is gitignored and a new key is a new secret: **a PR cannot do this.** CG-61's lesson exactly — *merged* and *in effect* are different facts. Until the operator acts, the surface ships with no caller, and the row must say so rather than read as done |

### Design calls made without asking — overrule if you disagree

Three smaller things were decided by reasoning rather than raised as decisions,
because a Planner would normally have settled them in the body. Flagged so they
are visible:

1. **`initialize` is authenticated** like every other MCP request (§5) — an
   unauthenticated discovery handshake buys nothing and discloses the server.
2. **`cards` is exposed verbatim** rather than trimmed (§3 corollary 1) — trimming
   is hand-authoring wearing a derivation's clothes.
3. **No new ⚠ flag word is invented** for "no MCP client has connected yet" (§9) —
   the ledger is about Google seams; this is not one.

---

## 15. Scope — what CG-80 does NOT do

Stated so a Builder does not helpfully add any of it:

- **No inbound tool of any kind.** §7. Not `read_inbox`, not a "check for replies"
  convenience, not a resource.
- **No card-building help.** §3 corollary 1. Not a builder tool, not a richer
  `cards` schema, not an example card in the tool description.
- **No MCP resources, prompts, logging, completion, sampling, roots or
  elicitation.** Capabilities declared are `{"tools": {}}` and nothing else — and
  four of those are **Deprecated as of 2026-07-28** anyway (§6.2).
- **No SSE, no sessions, no `Mcp-Session-Id`, no `subscriptions/listen`, no
  `listChanged`, no `list_changed` notifications.** Omitting `listChanged` is what
  keeps the whole notification-stream surface out of scope (§6.2).
- **No OAuth, and no `resource_metadata` parameter on the `WWW-Authenticate`
  header.** Static per-app bearer, which is the credential the gateway already has
  (§5). ⚠ Advertising `resource_metadata` would send a conformant client down an
  OAuth discovery path that dead-ends.
- **No new secret, no new `SECRETS.template.md` row, no new port, no new stack.**
- **No live-registry edit and no new tenant.** D8.
- **No ⚠ verification-ledger movement.** §11.
- **No change to `POST /v1/messages`, `client.py`, or any existing route's
  behaviour.** §13 test 10 pins it.

## 16. Sizing — one PR, and D4a is what makes that answer non-obvious

⚠ **This section was drafted as a confident "one PR, comfortably" before §6.1's
era finding arrived. That finding roughly doubles the protocol layer**, and the
honest thing is to say so rather than leave the original estimate standing —
which is exactly the failure mode CG-69 catalogues.

| Piece | Estimate |
|---|---|
| `mcp.py` — dual-era dispatch, both method sets, §6.3's seven requirements, §6.5's ten error rows | 400–500 LOC at this repo's comment density |
| tool definition + derived schema + per-app `enum` | ~80 LOC |
| router mount in `service.py`, `/healthz` field, `__main__` flag wiring | ~50 LOC |
| `tests/test_mcp.py` — §13's fifteen groups | ~350–400 LOC |
| docs: integration guide section, README API row, `.env.example`, `docs/deploy/nas.md` §5 compose, `registry.example.yaml` example app | — |

**Still one PR.** It is larger than CG-59 half 1 and comparable to CG-54, both of
which shipped as single rows. Splitting is worse than the size: a protocol layer
with no tool is unshippable and untestable in anger, and a legacy-only first PR
would ship a surface D4a says may be **silently unreachable** — the one outcome
this design is trying to avoid.

**If the user picks legacy-only or modern-only at D4a**, the protocol layer drops
back to roughly the original estimate (~250–300 LOC) and the row gets
correspondingly smaller. The plan is written so that the era branch is the
outermost seam, so dropping one era is deleting a branch rather than unpicking a
design.

**Rows:**

| Row | State |
|---|---|
| **CG-80** — the MCP server surface, send-only | **queued** by this spec |
| **CG-81** — an MCP `read_inbox` tool | **filed, not queued.** Needs explicit hard-rule-#6 sign-off (D1) and depends on **CG-56** |
