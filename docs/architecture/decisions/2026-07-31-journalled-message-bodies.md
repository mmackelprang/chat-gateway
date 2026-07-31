# ADR-0002 — Journalled message bodies: what CG-54 put on disk, for how long, and the promise it broke

| | |
|---|---|
| **Date** | 2026-07-31 |
| **Status** | **ACCEPTED — `D + A`**, decided by the user 2026-07-31. Compact on drain, and correct the contract as a bounded retention rather than an absolute. §6 records the decision; §§2–5 are the evidence it was made from and are unchanged. |
| **Decides** | Whether the gateway keeps `aitrader`'s *"no body text of yours is ever written anywhere"* promise or the durability CG-54 paid for. **Answer: the durability**, with the exposure window collapsed from weeks to seconds |
| **Raised by** | `CG-65` item 3 — *"If you never call `/v1/messages`, no body text of yours is ever written anywhere"* (`docs/consumers/aitrader.md:217`) became false when #45 merged |
| **Unblocks** | `CG-65`'s correction of `aitrader.md` §6 and §8 (option A), and a new implementation row for option D. Neither is written here |
| **Relates to** | `CG-54` (#45, the change that caused this), `CG-67` (#48, which shipped the `.gitignore` half of §2.9 while this ADR was open), `CG-66` (`journal.py`'s citation of an unshipped runbook control), `CG-53`/`CG-55` (the deploy that would ship that control) |
| **Hard rules engaged** | #1 (transport, never schemas), #2 (secrets are env-only), #4 (per-app auth + allowlists), #5 (honest `/healthz`), #6 (inbound opt-in) |

> ## ✅ Status: DECIDED — `D + A`, 2026-07-31
>
> **This ADR was written not to decide.** It measured the exposure, costed seven
> options and marked one recommendation *as a recommendation*, in a section that
> existed to be overruled. **The user has now decided, the same day, and chose
> `D + A`** — the recommendation, on the recommendation's own reasoning plus one
> fact the ADR could not supply.
>
> | Item | Outcome |
> |---|---|
> | **§9 Q1 / Q2 — promise or durability?** | **Durability.** Options **D** (compact on drain) **+ A** (correct the contract) adopted. `aitrader.md:217` is rewritten as a bounded, stated retention, not restored as an absolute |
> | **§9 Q4 — is the state dataset snapshotted?** | **ANSWERED: no.** Plain ZFS dataset, no snapshots, no replication. **This is the fact that decided it** — see below |
> | **§9 Q3 — is a per-app `journal_payload` flag rule-#1-clean?** | **NOT REACHED.** Option C was not chosen, so the question does not arise. The argument is **kept on record, not resolved** — it will recur the next time a per-app flag is proposed, and §4.1 finds a place where it plausibly recurs immediately |
> | **§9 Q5 — the `0644` never-pruned `inbox-data/` files** | **ANSWERED: folded into CG-65's implementation scope**, not deferred to a separate row. **Both** exposures are fixed in one cycle. §4.1 gives the shape; §6 D5 records the decision |
> | **B and C** | **Rejected, on the record, as a choice about which failure is worse** — not dismissed. §6 D3 |
>
> ⚠ **The scope widened after the first decision, and that is recorded rather
> than smoothed over.** `D + A` was chosen while §9 Q5 was still open, on the
> understanding that it fixed the **smaller** of the two exposures this ADR
> measured. The user then read that framing and **widened the row rather than
> accepting the smaller fix**, so CG-65 now covers `inbox-data/` too. §4.1 is
> written *after* the option set and deliberately **not** lettered into it —
> A–G were written about the queue journal and none of them fits an audit trail.
>
> ⚠ **And fixing the second half surfaced a second contract question, which this
> ADR does NOT resolve.** `docs/integration-guide.md:366-367` promises every
> consumer that the audit trail is *"never pruned"*. Pruning it would breach a
> published guarantee **the same way #45 breached aitrader's** — in the opposite
> direction. §4.1 states it; §9 Q6 carries it as open.
>
> **The load-bearing consequence of Q4's answer.** §2.9 flagged that if the
> TrueNAS dataset were snapshotted or replicated, every retention figure in §2.2
> would be a **floor** rather than a ceiling, compaction would erase nothing that
> mattered, and the whole option ranking would shift toward E or B/C. It is not.
> So the measured windows are the **actual exposure**, an erase in the live file
> is an erase everywhere, and D's value is **confirmed rather than merely
> unrefuted**.
>
> **A decision changes the status, never the evidence.** Every measurement in §2
> stands byte-for-byte as taken on 2026-07-31 — the 500-notify arithmetic, the
> `0600`/`0755` modes, the aggregate-clock result, the `/v1/messages` inversion.
> §6's pre-decision recommendation is kept verbatim beneath the decision rather
> than rewritten into it.
>
> **No ⚠ flag is cleared, added or reworded here** — not by the ADR and not by
> the decision. The verification ledger lives in
> [`CLAUDE.md`](../../../CLAUDE.md) ("Verification ledger") and is **not**
> restated in this document; every attempt to restate it in this repo has drifted
> within two PRs. What changed on 2026-07-31 is what reaches **disk**, which is a
> different axis from what has met **Google**.
>
> **Nothing is implemented here.** A Builder ships D off §4's code shape and A
> off §5's list; this ADR touches no source and no consumer contract.

---

## 1. Context

`CG-54` (#45, merged 2026-07-31) made both queues durable. `Dispatcher.enqueue`
([`src/chat_gateway/delivery.py:188-192`](../../../src/chat_gateway/delivery.py))
now journals `message.model_dump(mode="json")` — **the whole `text` and the whole
`cards` array** — to append-only JSONL under `CHAT_GATEWAY_STATE_DIR/queue/` on
**every** `/v1/notify`. `Inbox.put` ([`inbox.py:74-75`](../../../src/chat_gateway/inbox.py))
does the same for whole inbound events, including `raw`.

That is not a slip. `journal.py`'s module docstring says it in capitals —
*"WHAT REACHES DISK, AND WHY THAT IS NOT A RULE #2 VIOLATION"* — and it is
correct: **a queue cannot be replayed without the payload.** Durability and
body-persistence are the same fact stated twice.

`docs/consumers/aitrader.md` promises that tenant something else:

> **`:217`** — *"If you never call `/v1/messages`, no body text of yours is ever
> written anywhere."*
>
> **`:219`** — *"Restart drops undelivered jobs. The queue is in-memory."*
>
> **`:418`** — *"Nothing about aitrader's traffic is persisted anywhere, in any
> configuration."*

**The first and second are causally linked: fixing `:219` is what broke `:217`.**
There was no world in which #45 landed and both stayed true. The contract was
written against a gateway that could not survive a restart, and it sold that
weakness as a privacy property.

`aitrader` is the `allow_inbound: false` tenant whose contract treats any two-way
path as a security hole in a real-money system. It is the tenant with the least
tolerance for a surprise on this axis, and the only one that was told this
particular thing.

---

## 2. Measured exposure — first-hand, 2026-07-31

**Everything in this section was measured by executing the shipped classes**
(`Journal`, `Dispatcher`, `Inbox`, `DeliveryLog`) against a temporary directory
on the WSL2 dev box, not reasoned about from the source. Where a number is read
from the code rather than executed, it says so. Reproducing it needs no Google
and no Cloud project.

### 2.1 What reaches disk, exactly

| Writer | File | Contents | Pruned? |
|---|---|---|---|
| `Dispatcher.enqueue` (**#45**) | `state/queue/delivery.jsonl` | `source`, `kind`, `identity` **name**, `title`, and `message` — **full `text` + full `cards`** | yes, by compaction |
| `Inbox.put` (**#45**) | `state/queue/inbox.jsonl` | the whole `InboundReply`, **including `raw`** | yes, by compaction |
| `Inbox._audit` (pre-existing) | `inbox-data/<app>-<date>.jsonl` | the whole `InboundReply`, **including `raw`** | **never** |
| `DeliveryLog.record` (pre-existing) | `state/deliveries/deliveries-<source>-<date>.jsonl` | seven fields: `id`, `ts`, `source`, `kind`, `title[:200]`, `status`, `detail[:300]` | **never** |

**No credential is in any of them.** The journal stores an identity *name* and
`Dispatcher.restore` re-resolves it through the registry at boot
(`delivery.py:283-284`), so no webhook URL — which embeds `key`+`token` — and no
per-app API key is written. `configCompleteRedirect*` is blanked to
`<redacted-by-gateway>` before anything is audited or forwarded
(`adapters/pubsub.py:150-159`). **Hard rule #2 is intact**, which is precisely
why this is a contract question and not an incident.

### 2.2 Lifetime — the headline, and it is not "seconds"

A `close` record **does not erase the payload.** It appends a line saying the id
is done; the `open` line carrying the body stays byte-for-byte where it was. The
body is removed only when the file is **compacted**, which rewrites survivors and
drops everything terminal.

Measured, delivering through a fake adapter that always succeeds:

| Measurement | Result |
|---|---|
| body present in `delivery.jsonl` after `enqueue` | **yes** |
| body present after the job is **`delivered` and closed** | **yes** — file is `['open','close']` |
| `/v1/notify` calls until inline compaction erased it | **500** |
| occurrences immediately after compaction | **0** (file: 0 lines) |
| ...then one more notify | body present again; the cycle restarts |

**500 is arithmetic, not a coincidence.** `DEFAULT_COMPACT_AFTER = 1000` counts
*appends*, and one successfully delivered notify costs two (`open` + `close`), so
inline compaction fires on the 500th. Retries make it fire sooner — each
reschedule appends an `update` — and `_maybe_compact_locked` is checked after
`update` and `close` but **not** after `open` (`journal.py:232-241`), so a
journal holding only opens never compacts.

**The unit is traffic, not time.** Absent a restart, a delivered body's residency
is `500 / (gateway-wide successful notifies per day)` days:

| Gateway-wide notifies/day | Residency of a delivered body |
|---|---|
| 5 | ~100 days |
| 10 | ~50 days |
| 20 | ~25 days |
| 50 | ~10 days |
| 200 | ~2.5 days |

`journal.py:16` sizes the design for *"tens of messages a day"*. Taken at its
word, **a delivered aitrader alert sits in `state/queue/delivery.jsonl` for
roughly three to eight weeks** — on a gateway that never restarts, indefinitely
longer at lower volume. That is the number the contract correction has to name,
and it is the reason this is a decision rather than a typo.

Storage is not the constraint. One representative record — an alert body plus a
small two-widget card — measured **551 bytes**. At 20/day the steady-state file
is a few hundred kilobytes on a 13 TB pool.

### 2.3 Boot compaction — what survives

`Dispatcher.restore` reads the journal, re-queues the survivors, and calls
`compact(survivors)` (`delivery.py:300-302`). Measured with 5 delivered-and-closed
jobs plus 1 still-open:

- before restart: **6 bodies** on disk
- after `restore()`: **1 body**, 1 line — the still-open job only

**Restart is currently the only *prompt* eraser.** Boot compaction removes every
terminal record's body, including jobs closed as `expired` and `unroutable`
during that same `restore` call. A gateway that is redeployed weekly therefore
has a weekly retention ceiling that no code enforces and no document states — and
the deploy target is `restart: unless-stopped` on a NAS, i.e. a process explicitly
designed *not* to restart.

### 2.4 The failure ladder, and the job that never finishes

Measured against an adapter that always raises, stepping a fake clock through
`BACKOFF_S = (0, 30, 120, 600, 3600)`:

- the file ends as `['open','update','update','update','update','close']`
- **the body is still present after the terminal `failed`** — same rule as
  `delivered`; only compaction erases

And measured separately: a job still pending at compaction time has its body
**rewritten into the new file** (`_compact_locked` re-emits each survivor's
`open`). That is required — it is what makes replay possible — and it means a
job that is stuck retrying keeps its body on disk for as long as it is stuck.

Two ceilings bound the *live* window, both read from the code: the ladder is five
attempts over **~1h13m** (`delivery.py:37`), and a job older than
`REPLAY_MAX_AGE_S = 86400` (**24h**) is closed as `expired` at boot rather than
sent (`delivery.py:41`). So a body belonging to a **live** job is on disk for
seconds normally, up to ~73 minutes on the ladder, and up to 24h across gateway
downtime. **The exposure this ADR is about is the other one** — the body of a job
that is *finished*, which has no replay value at all and is retained anyway.

### 2.5 On-disk posture — modes as actually applied today

Measured by creating the files through the shipped code at umask `022`:

| Path | Mode | Set by |
|---|---|---|
| `state/queue/delivery.jsonl` | **`0600`** | `journal._chmod_quietly`, on create |
| `state/queue/inbox.jsonl` | **`0600`** | same |
| `state/queue/` | **`0755`** | `Path.mkdir(parents=True, exist_ok=True)` — no mode argument |
| `state/` | **`0755`** | same |
| `state/deliveries/deliveries-*.jsonl` | **`0644`** | nothing — `DeliveryLog` never chmods |
| `state/deliveries/` | **`0755`** | `mkdir`, no mode |
| `inbox-data/<app>-<date>.jsonl` | **`0644`** | nothing — `Inbox._audit` never chmods |

**Three findings, and only one of them is a defect.**

1. **The journal's own file mode is correct and carefully done.** `0600` is
   applied *inside* the `open()` context and *before* the first write, in both
   `_append` and `close_many`, and on the `.tmp` before compaction writes into it
   (`journal.py:106-111`, `165-170`, `265-266`). There is no window in which
   payload bytes sit at `0644`. Do not "find" a bug here; there isn't one.
2. **`0750` is a forward-dated citation.** `journal.py:26` and `:290` say *"the
   deploy runbook puts the state dir at 0750"*. There is no `docs/deploy/` in
   this repo. The mode is specified — `install -d -m 0750 …/{config,secrets,state,inbox-data}`
   in [the production-readiness plan](../../superpowers/plans/2026-07-31-production-readiness-arc.md)
   line 68 — but that plan has not shipped. **CG-66 already flags this**; it is
   restated here only because it is the compensating control the durability
   design leans on. Note the interaction: `mkdir(exist_ok=True)` **preserves** a
   pre-created `0750`, so once CG-53 lands the runbook control does hold for
   `state/` — but `state/queue/` is created *by the code*, at `0755`, inside it.
   With `0600` files that is defence-in-depth rather than a hole.
3. ⚠ **The two never-pruned files are `0644`, and one of them holds whole
   inbound events including `raw`.** `inbox-data/<app>-<date>.jsonl` is
   world-readable, unbounded in time, and richer than the journal. It predates
   #45 by a long way and is **not** a regression — but any decision here that
   only hardens the journal will have hardened the *lesser* of the two files.

### 2.6 Blast radius — every tenant, one file, one clock

**There is one `delivery.jsonl` for the whole gateway** (`__main__.py:107-109`
constructs a single `Dispatcher` with a single `Journal`), and every tenant's
`/v1/notify` bodies go into it. `aitrader` is **not** special in what gets
written — it is special only in having been told otherwise.

Measured, and the consequence is counter-intuitive: one aitrader body, then 499
deliveries by `job-hunter` and nothing else — **the aitrader body was gone.**
The compaction clock is *aggregate*, so a busy tenant erases a quiet tenant's
bodies faster. Option F below inverts this, which is why it is on the list with a
warning rather than as an obvious win.

Two paths that do **not** write bodies, read from the code:

- **A deduped notify is never journalled.** `emit_notification` returns at
  `service.py:178-182`, before `enqueue`. aitrader's dedupe windows therefore
  reduce its write rate directly.
- **`CallbackForwarder` has no journal at all** (`forwarder.py:60-84`). *"Both
  queues durable"* means the two that were journalled; the callback queue is
  still in-memory. Relevant here only as a scope fact — it holds jobhunt's
  replies in RAM, writes no body to disk, and loses them on restart.

### 2.7 The inbox twin — and why jobhunt is a different case entirely

Measured with a jobhunt-shaped reply:

- after `put`: body in `state/queue/inbox.jsonl` — **yes**
- after `poll` (`close_many`, the "polled" close): body **still there**, same
  rule as outbound
- in `inbox-data/job-hunter-<date>.jsonl`: **yes, and that file is never pruned**

**So #45 added nothing durable to jobhunt's exposure.** Its inbound bodies were
already on disk permanently, at `0644`, in the audit trail — the journal is a
*bounded second copy* of an unbounded first one. The privacy delta of #45 is
essentially zero for jobhunt and essentially total for aitrader, and that
asymmetry is the whole reason this ADR exists.

`aitrader` never reaches the inbox journal at all: `dispatch` hits `continue` at
`adapters/pubsub.py:709` for an `allow_inbound: false` app, **before**
`inbox.put` at `:727`. Hard rule #6 is untouched by #45 in every direction.

⚠ **One narrow inbound path can put bytes from an Ai Trader space on disk, and it
predates #45.** An event that `normalize_event` cannot parse has no attributable
space, so it is audited under `_unrouted` via `inbox.put` (`pubsub.py:670`) with
its `raw` intact — permanently in `inbox-data/_unrouted-<date>.jsonl`, and since
#45 also in the bounded `inbox.jsonl`. It is not attributed to aitrader and
cannot be, which is the point. It matters only against the **literal** reading of
`aitrader.md:418`'s *"in any configuration"*, and any correction of that sentence
should account for it rather than leave a second absolute standing.

### 2.8 The inversion the scope note did not survive

`aitrader.md:213-217` carves out `/v1/messages` as the risky endpoint and
`/v1/notify` as the safe one. **Measured against the code, that is now backwards
in the dimension the note cares about:**

| Endpoint | What reaches disk | Lifetime |
|---|---|---|
| `/v1/messages` (`service.py:204-224`) | `text[:80]` as a delivery-log title. **Never journalled — it sends synchronously and never touches the Dispatcher.** | **permanent** (audit JSONL) |
| `/v1/notify` (`service.py:227-229`) | **entire `text` + entire `cards`** | bounded — §2.2 |

The endpoint the contract told aitrader to avoid writes 80 truncated characters
forever; the endpoint its contract is built on writes everything, for weeks. Any
correction that just deletes the word "anywhere" will leave this inversion
standing.

### 2.9 What erasure does *not* reach

Compaction is `os.replace` of a fresh file over the old inode
(`journal.py:283`). That is a **logical** delete:

- **Freed blocks are not overwritten.** Forensic recovery from free space is out
  of scope for a homelab NAS, and stating it is cheaper than implying otherwise.
- **Filesystem snapshots and backups.** ✅ **ANSWERED 2026-07-31 by the user, and
  the answer is no.** `/mnt/datapool/apps/chat-gateway/state` is a **plain ZFS
  dataset — no snapshots, no replication.**

  *The original wording is kept, because what it flagged is exactly what the
  answer resolves:* ⚠ *"If that dataset is snapshotted or replicated, the
  effective retention of a journalled body is the snapshot retention policy, not
  the compaction interval, and every number in §2.2 is a floor rather than a
  ceiling. Neither the arc plan nor the spec says one way or the other."*

  **It is not, so they are not floors — they are the actual windows,** and an
  erase in the live file is an erase everywhere. This is the fact that confirmed
  option D rather than merely leaving it unrefuted (§6). ⚠ **It is a property of
  today's dataset, not a guarantee**: adding a snapshot task to that dataset later
  would silently restore the floor and re-open this question. §6 D4 makes that a
  named revisit trigger rather than a footnote.
- **`.gitignore` did not ignore `state/`** while this ADR was being written —
  and `.env.example` defaults `CHAT_GATEWAY_STATE_DIR=state`, the repo root, so a
  local run left tenant bodies stageable by `git add -A`. `inbox-data/` *was*
  already ignored, which showed the rule was understood; `state/` did not need it
  before #45 and did after. ✅ **Fixed and merged as `CG-67` (#48, `1bd53a7`)**
  while this ADR was open — this ADR is based on that commit and `state/` is
  ignored on it. Recorded rather than deleted, because the *reason* it was
  missing is the finding: the ignore rule tracked where bodies used to be, and
  #45 moved them.

---

## 3. What is still TRUE — the breach must not be overstated

| Claim | Status |
|---|---|
| `DeliveryLog.record()` has no body or card parameter (`delivery.py:77-91`) | ✅ **still true, structurally.** There is nowhere to put a body. The *"not by convention"* framing at `aitrader.md:208-211` survives intact |
| No credential reaches any journal | ✅ **true** — identity NAMES, re-resolved through the registry (§2.1) |
| Hard rule #2 | ✅ **intact** |
| Hard rule #6, and aitrader's inbound lockout | ✅ **untouched by #45** (§2.7) |
| The `/v1/notify` path never logs a body *to the delivery log* | ✅ true — and now beside the point |

**What broke is one word: "anywhere."** CG-54 added a second writer the scope
note never contemplated. The paragraph walks the reader up a chain of true,
carefully-argued claims about `DeliveryLog` and then hands them a false absolute
about the whole system — which is exactly what makes it more dangerous than a
plainly wrong sentence would be.

---

## 4. Options

Costed against four axes each: **what it costs**, **what it buys**, **what it
breaks**, and **what it does to CG-54's durability guarantee — including the
mid-flight double-send answer** that `delivery.py:235-240` wrote down:

> *"the send has returned, the log record is written, and the `close` is not. A
> process killed here replays the job and delivers it TWICE. Deliberate — Chat
> gives us no idempotency key … and losing an alert is the worse failure."*

**That sentence is the load-bearing one.** It is the tie-break CG-54 already
made, and options B and C reverse it for one tenant.

### Option A — Accept, and correct the contract

Journalling is the price of durability and it applies uniformly. Rewrite
`aitrader.md` §6 and §8 to name the journal, its contents, its lifetime, its mode
and its erasure semantics — the numbers in §2, not a reassurance.

| | |
|---|---|
| **Costs** | One doc PR. Nothing in `src/`. And it hands a tenant a materially worse privacy posture than the one it signed up to, in writing, and asks it to live with it |
| **Buys** | Honesty at the earliest possible moment; zero new mechanism; zero new per-app branching; the durability guarantee survives untouched and uniform |
| **Breaks** | The promise, permanently and explicitly. `:217` cannot be repaired under A — it can only be replaced with a true, longer, less comfortable sentence |
| **Durability** | **Unchanged.** Mid-flight window still resolves as "deliver twice", which is the answer CG-54 chose |
| **Rule #1** | Clean. No per-app knowledge anywhere |

### Option B — Reference-only journal for flagged apps

Journal an id, a source, an identity name and a title — **no payload**. On
replay, a reference-only record cannot be re-sent; it is closed as
`unreplayable`, recorded in the delivery log, and counted at `/healthz`.

| | |
|---|---|
| **Costs** | A second record shape in `journal.py`; a `restore` branch; a new `/healthz` counter and `reasons` line; a new terminal status in the delivery log and in the contract's status table. **And an operator loses the thing #45 was built for**: a restart mid-ladder means an alert that was accepted with a 202 is *never delivered* and the gateway *knows* it |
| **Buys** | **The only option that makes `:217` true again as written.** No body text of that tenant is on disk in any file, in any state |
| **Breaks** | **CG-54's guarantee, for that tenant, deliberately.** Every stated benefit of the durable queue — surviving a deploy, surviving a crash mid-backoff, surviving a 3am NAS reboot — is withdrawn from the one tenant whose contract has no inbound fallback path and no second channel (`aitrader.md` §9) |
| **Durability** | ⚠ **Inverts the mid-flight answer.** Today a kill between send and close yields a **duplicate**. Under B it yields a **loss**, reported. CG-54 chose duplicate-over-loss explicitly *because losing an alert is worse*; B says the opposite for the tenant with the strongest claim to that reasoning. This contradiction is not resolvable by wording — it is a real trade and it must be made on purpose |
| **Rule #1** | Clean if the flag is transport-shaped (see C) |

**Honest operator cost, stated as asked:** on restart, an operator gets a
delivery log entry reading `unreplayable — body not journalled by policy` and a
`/healthz` reason. They know an alert was lost, which alert it was (by title),
and that they must go read the tenant's own fallback log. They cannot recover the
message from the gateway. The aitrader contract already assumes the consumer
keeps a local fallback log (`aitrader.md:221`), so B is survivable — but it moves
the gateway from *"we will deliver it eventually"* back to *"we will tell you we
didn't"*, which is where it was before #45.

### Option C — Per-app registry flag (the elective form of B)

`journal_payload: reference_only` (or `full`, the default) as a registry key on
`App`, beside `allow_inbound`, `allowed_users` and `callback_url`.

| | |
|---|---|
| **Costs** | Everything B costs, plus: registry schema, validation, `/healthz` surfacing, and a documented fork in the durability guarantee — the contract now differs by tenant and `docs/integration-guide.md` must say so |
| **Buys** | The tenant chooses its own trade instead of the gateway choosing for it — which is exactly what the aitrader contract is for. Other tenants keep full durability |
| **Breaks** | Uniformity. Two classes of tenant, two replay behaviours, two `/healthz` stories, and every future durability change must be reasoned about twice |
| **Durability** | Same as B, but scoped to whoever opts in |

**The hard-rule-#1 argument, made rather than assumed.**

*For* — the registry is **already** where per-app transport policy lives, and
hard rule #4 (*per-app auth + identity allowlists*) makes that mandatory rather
than incidental. `allow_inbound: false` is a per-app **privacy/security** flag
that the gateway honours without ever reading a message's meaning; it was
accepted, and hard rule #6 is built on it. A `journal_payload` flag is the same
shape: the gateway decides **whether to write bytes down**, never **what the
bytes mean**. No branch on content, no permitted-value enum, no tenant vocabulary
entering the gateway. On that reading it is transport policy, and rule #1 permits
it.

*Against* — rule #1's deeper intent is that gateway behaviour is uniform and
app-agnostic, and each per-app knob multiplies the state space every future
change must be reasoned about in. There is also a naming trap: `sensitive: true`
would be app-domain framing (the gateway asserting something about the *content*)
where `journal_payload: reference_only` is mechanical (the gateway describing its
own storage). **If C is chosen, the mechanical name is the one that keeps rule #1
clean**, and that distinction is not cosmetic.

*Unresolved either way* — this is the judgement the user is being asked for in
§10 question 3.

### Option D — Compact on drain (erase at terminal, not at 500)

Leave *what* is written alone; change *how long* it stays. Compact whenever the
live set drops to empty. Shape only:

```python
# delivery.py, at the end of _finish — shape, not implementation
if not self._jobs:                 # nothing left to replay
    self._journal_write(lambda: self._journal.compact([]), "compact")
```

Measured basis: compaction with an empty survivor set truncates the file to **0
lines** (§2.2), and `Journal.compact` is already public, already atomic, already
holds the right lock.

| | |
|---|---|
| **Costs** | One `os.replace` + `fsync` per drain — at *tens of messages a day*, tens per day. Two behavioural tests. `Inbox.poll` needs the mirror-image call. **And one real, non-obvious cost: a single stuck job pins every other tenant's delivered body on disk until it terminates**, because the set never drains. Worst case that is the ~73-minute ladder; across gateway downtime, up to the 24h ceiling |
| **Buys** | Residency of a *finished* body falls from **weeks** to **seconds**, without touching the payload, the replay path, the registry, or any per-app behaviour. Applies to every tenant at once. It also erases retroactively on first drain after deploy |
| **Breaks** | Nothing structural. `_maybe_compact_locked`'s 1000-append trigger stays as the backstop for a queue that never drains |
| **Durability** | ⚖ **Unchanged — and this is the point.** The body is on disk for exactly as long as a replay could need it and not one moment longer. The mid-flight double-send answer is untouched: a job killed between send and close is still live, still journalled, still replayed, still possibly duplicated |
| **Rule #1** | Clean. No per-app anything |

**What D does not do:** it does not make `:217` true. A body is still written and
still on disk while its job is live. D changes the magnitude by three or four
orders of magnitude; it does not change the kind.

### Option E — Encrypt the journal at rest

Encrypt payloads with a key from the environment; decrypt on replay.

| | |
|---|---|
| **Costs** | A crypto dependency (`cryptography`), a new **env secret** under hard rule #2, key rotation with a live journal, and a boot failure mode where the key is wrong and the whole queue is unreplayable. `tail`-ability during an incident — an explicit design goal at `journal.py:5-7` — is lost |
| **Buys** | Protection against an attacker with the file but not the env. On this deployment that is: a snapshot or backup copy read out of band, or a stray `git add -A` |
| **Breaks** | The debuggability the module was designed around; and it invites the belief that the problem is solved when the key sits on the same host, in the same `.env`, that the ciphertext does |
| **Durability** | Unchanged in principle; **adds a new way to lose the whole queue** (key loss = total unreplayability), which is a durability *regression* in the tail |
| **Rule #1** | Clean. **Rule #2** gains a new secret — the one direction that rule prefers not to move |

Weakest option on its own. Non-trivial *only* if the snapshot/backup answer in
§2.9 comes back "yes, replicated off-box", which would make the off-box copy the
real threat model rather than the local file.

> ✅ **That conditional resolved against E, 2026-07-31.** §2.9's question was
> answered *no* — plain dataset, no snapshots, no replication — so the off-box
> copy E was written to protect against does not exist, and E's only remaining
> buyer is a stray `git add -A`, which `CG-67` closed. **E is rejected**, and it
> is rejected because the fact came back, not because it was weak on paper.

### Option F — Per-app journal files

`state/queue/delivery-<app>.jsonl`, one per tenant.

| | |
|---|---|
| **Costs** | Multiple `Journal` instances, multi-file replay ordering, a per-file skipped-line count to aggregate at `/healthz` |
| **Buys** | Targeted deletion becomes possible (`rm` one tenant's file); one tenant's traffic stops erasing another's records |
| **Breaks** | ⚠ **It makes aitrader's exposure WORSE, not better** — measured in §2.6. Today `job-hunter`'s volume drives the shared clock and erases aitrader's bodies at 500 *gateway-wide* notifies. Split the files and aitrader's retention depends only on **aitrader's own** low volume: at 5 alerts/day, ~100 days |
| **Durability** | Unchanged |
| **Rule #1** | Clean |

Listed because it is an obvious-looking idea that the measurement falsifies.
**Only sound in combination with D or G**, never alone.

### Option G — Shorten the window (`compact_after`)

Lower `DEFAULT_COMPACT_AFTER` from 1000, and/or add a time-based trigger so the
journal compacts every N minutes regardless of volume.

| | |
|---|---|
| **Costs** | Nearly nothing — one constant, or a small timer. More rewrites per day |
| **Buys** | Retention becomes a stated, tunable number instead of an emergent one. A time-based trigger is what makes the number expressible **in hours** to a tenant rather than in appends |
| **Breaks** | Nothing. Lowering it too far on a busy queue is write amplification, self-limiting at this traffic shape |
| **Durability** | Unchanged |
| **Rule #1** | Clean |

The cheap partial. Strictly weaker than D — a timer erases on a schedule where D
erases on the event that makes the body worthless — but it is one line and it can
ship today if D is judged too clever.

### Composability

**A is not really an option; it is a floor.** Under *every* other option the
contract sentences at `:217`, `:219` and `:418` are still false as written and
still have to be rewritten. B and C alone can restore `:217`'s *property*; every
other option changes the sentence instead.

| Pair | Compose? |
|---|---|
| **A + anything** | **Required.** A is the floor, not an alternative |
| **B / C** | Mutually exclusive — C *is* B made elective |
| **D + G** | Yes, and well: event-driven erase with a time-based backstop for a queue that never drains |
| **F + D** | Yes. F alone is harmful (§4) |
| **B/C + D** | Yes but largely redundant — a tenant with no payload journalled has nothing for D to erase |
| **E + anything** | Orthogonal. It answers a different threat model (the off-box copy), and only earns its cost if §9 question 4 comes back "snapshotted" — ✅ **it came back "no"**, so E is rejected |

---

## 4.1 The second exposure — `inbox-data/`, and why no option above covers it

> **Added 2026-07-31, after the `D + A` decision, when the user folded §9 Q5 into
> CG-65's scope rather than deferring it.** This section is deliberately **not**
> lettered into §4. Options A–G were each written about the **queue journal**,
> and forcing an audit trail into one of them would be the kind of tidy-looking
> mistake this ADR exists to avoid. Said plainly, as asked.

### Why A–G do not apply

`journal.py:9-12` draws the distinction the whole repo rests on: *"NOT THE AUDIT
TRAIL, and not a replacement for it… they say what ARRIVED, never what LEFT."*
That is precisely why the option set does not transfer:

| Option | Why it does not fit `inbox-data/` |
|---|---|
| **D** (compact on drain) | **There is no drain.** A journal record becomes worthless the moment its job is terminal; an audit record is *born* terminal and is the artifact by design. "Compact when the live set empties" has no meaning where nothing is ever live |
| **B / C** (reference-only) | An audit trail whose payload is a reference is not an audit trail. Its entire value is the payload |
| **F** (per-app files) | **Already done** — `<app>-<date>.jsonl` is per-app *and* per-day. F's mechanism is the one thing this artifact already has |
| **G** (shorter compaction window) | Compaction is a journal concept. There are no superseded records to reclaim |
| **E** (encrypt) | Rejected for the journal on §2.9's answer; the same answer applies here |
| **A** (document it) | Necessary and insufficient — the same as for the journal |

**What the second half needs is a *retention policy*, which is a different kind
of object from anything §4 offers.** Shape only, at §4's altitude:

### Shape — three requirements and one trap

1. **Mode: `0600`, at create, before the first write.** `Inbox._audit`
   (`inbox.py:184-192`) never chmods; `journal.py` already has the exact
   primitive (`_chmod_quietly`) and already applies it in the right place —
   inside the `open()` context, before any payload byte is written (§2.5
   finding 1). This is the cheap half and it is a straight lift, not a design.
   The same applies to `DeliveryLog.record`'s `deliveries/*.jsonl` (also `0644`).

2. **Pruning: TIME-bounded, in days — never count-bounded.** ⚠ **This is the one
   place this ADR must not repeat its own finding as a mistake.** §2.2 measured
   that the journal's count-bound (`DEFAULT_COMPACT_AFTER`) yields a retention
   *nobody can convert to a date* — "500 gateway-wide notifies" is not a sentence
   that can go in a consumer contract, and turning it into one required a
   parameterised table and a paragraph of arithmetic. A retention policy on human
   message content has to be expressible as **"N days"** because that is the unit
   a contract, a privacy posture and a subject-access request are all written in.
   **The artifact is already sharded by exactly the right dimension** — the
   filename `<app>-<date>.jsonl` *is* the retention key, so pruning is a directory
   listing and an `unlink`, with no parsing and no rewrite. That is a genuine
   piece of luck and it should be spent, not designed around.

3. **A sweeper with no cron.** This deployment has one always-on process and no
   scheduler. Shape: a boot-time sweep plus a periodic one on an existing tick
   (`HeartbeatMonitor` or the dispatcher loop already wake up), counted at
   `/healthz` like every other quiet deletion in this system — hard rule #5 does
   not distinguish between work dropped and work deleted.

### What inbound human content has to answer that an outbound queue does not

The reason this is not simply "the same fix pointed at another directory":

- **It is a record of a *person*, not of a job.** `InboundReply` carries
  `sender_email`, `sender_display` and the user's own `text`
  (`envelope.py:91-106`). The outbound journal holds an application's rendered
  output. Deletion of the first has a justification and possibly an obligation
  that deletion of the second does not.
- ⚠ **It is the designated recovery artifact, by name, in two places.**
  `inbox.py:110-112` tells an operator that *"the per-app JSONL audit beside this
  queue is the recovery record"* when a journalled reply no longer parses, and
  `docs/integration-guide.md:382-383` says that in that case *"the audit file is
  then the only copy."* **A retention window is therefore also a recovery
  window**, and the two cannot be chosen independently. Prune to 7 days and the
  `unrevivable_at_boot` recovery path is 7 days deep.
- **Whose content is it?** jobhunt may have a legitimate need to reconstruct a
  user's decision history; aitrader has no stake in this directory at all
  (§2.7 — it never reaches `inbox.put`). A per-tenant retention window is the
  obvious answer and it lands **straight back on §9 Q3's hard-rule-#1 question**,
  which the journal decision left *not reached*. Noted, not answered: if
  retention becomes per-app registry policy, that question is live again, and it
  should be argued from §4 Option C's text rather than re-derived.
- **`_unrouted` has no owner and no consent.** §2.7's unparseable bucket
  accumulates whole `raw` events that are unattributable by construction. Its
  retention answers to no tenant, which is an argument for the *shortest* window
  in the directory, not the default one.
- **Delete or redact?** Unlinking the day-file loses the arrival record entirely;
  blanking `text` / `sender_email` in place keeps it. Two different products with
  two different contract stories, and this ADR does not pick.

### ⚠ The contract question — surfaced, NOT resolved

**`docs/integration-guide.md:366-367` promises every consumer, in the published
integration guide, that the per-app JSONL audit is written *"one file per app per
day, written before anything is queued, **never pruned**."***

**Pruning it breaches a published guarantee — the same defect as #45, in the
opposite direction.** The journal broke a *"never written"* promise by writing;
pruning breaks a *"never pruned"* promise by deleting. That symmetry is not a
rhetorical flourish, it is the reason to stop: this ADR exists because a
durability change silently invalidated a sentence in a consumer contract, and the
fix for it is now positioned to do the same thing to a different sentence in a
different document. **A second contract breach discovered while fixing the first
is worth halting for.**

Recorded as **§9 Q6, open**. It is not this ADR's to resolve and it is explicitly
**not** covered by the `D + A` decision. Note also that the promise is in the
*shared* integration guide, so it is owed to **every** consumer, not only
jobhunt — which makes it a wider question than CG-65's aitrader framing, and the
reason it is flagged here rather than absorbed.

---

## 5. Consequences that follow whichever option is chosen

Independent of the decision, these are already true and a Builder will hit them:

1. **`aitrader.md:219` and `:547` are false under every option.** The queue is
   durable. Both say it is in-memory, and `:547` says it under *"Accepted
   limitations, agreed in the contract"*, which reads as a negotiated term.
2. **`aitrader.md:442`'s `/healthz` guidance is now actively misleading** — it
   tells the operator only two fields gate their path and that `degraded` is a
   tier-2 concern leaving *"your alerting unaffected"*. Since #45, four
   outbound-queue reasons can degrade it (`service.py:451-490`) and every one of
   them means an aitrader alert was dropped or will be double-sent.
3. **The `/v1/messages` inversion (§2.8) must be corrected, not deleted.**
4. **`aitrader.md:418`'s absolute needs the `_unrouted` caveat** (§2.7) or it
   will be false for a second, narrower, pre-existing reason.
5. **CG-66's items stand on their own, and one of them has already shipped.**
   The `.gitignore` half was split out and merged as **CG-67** (#48) while this
   ADR was open — `state/` is ignored on this ADR's base commit. What remains in
   CG-66 is `journal.py:26`/`:290`'s present-tense citation of the unshipped
   `0750` runbook line. Neither is this ADR's to fix.
6. **One line-number citation in `aitrader.md` has itself drifted.** `:209`
   points at *"`delivery.py:44-50`"* for `DeliveryLog.record()`; on `e96e08d`
   that function is at **`delivery.py:77-91`**. The claim it supports is still
   correct (§3) — the pointer is not. Worth fixing in the same pass, because a
   reader who follows it lands in `_parse_ts` and concludes the doc is guessing.

---

## 6. Decision — `D + A`, adopted 2026-07-31

| | |
|---|---|
| **Decided by** | the user, **2026-07-31**, the same day the ADR was written |
| **Adopted** | **Option D** (compact on drain) **+ Option A** (correct the contract), **plus D5** below — the `inbox-data/` half, folded in by a second decision later the same day |
| **Rejected** | **B** and **C** (D3), and **E** (on §2.9's answer) |
| **Not reached** | **C's hard-rule-#1 question** — kept on record, not resolved (D6) |
| **Deliberately unchanged** | every measurement in §2 |

### D1 — Compact on drain

Adopt Option D as written in §4: compact whenever the live set drops to empty, with
`_maybe_compact_locked`'s 1000-append trigger retained as the backstop for a queue
that never drains. `Inbox.poll` takes the mirror-image call.

**The reasoning, in the user's terms:** a terminal job's payload has **no replay
value whatsoever**, so retaining it is not a trade between privacy and durability
— it is a cost with no matching benefit. D collapses a *finished* body's residency
from the measured weeks (§2.2) to seconds while leaving the payload, the replay
path, the registry and the mid-flight double-send answer untouched.

**The fact that confirmed it:** §9 Q4 came back **no snapshots, no replication**.
Had it come back the other way, D would have been shrinking a number that
snapshots put straight back, and the ranking would have moved toward E or B/C.
It did not, so **the measured windows are the real exposure and D's erase is a
real erase.** D was recommended before that answer arrived; it is *adopted*
because of it.

**The honest cost, restated so it is not lost in the adoption:** a single stuck
job pins every other tenant's delivered body on disk until it terminates —
bounded by the ~73-minute ladder, or by the 24h `REPLAY_MAX_AGE_S` ceiling across
downtime.

### D2 — Correct the contract as a bounded retention, not an absolute

Adopt Option A. `aitrader.md:217`'s *"no body text of yours is ever written
anywhere"* is **not** restored — it is replaced by a true, longer, less
comfortable sentence naming what is written, for how long, and at what mode. §5's
five consequences all land in the same pass, including the `/v1/messages`
inversion (§2.8) and `:418`'s `_unrouted` caveat (§2.7).

**A is a floor, not a co-equal choice.** Under every option in §4 those sentences
were still false; adopting D does not make them true, it makes the true
replacement short.

### D3 — B and C are rejected as a choice about which failure is worse

Recorded as a rejection with a reason, not a dismissal. **B and C were the only
options that could restore the literal promise**, and they buy it by reversing
CG-54's *"losing an alert is the worse failure"* for the one tenant with no
second channel and no inbound path. The user chose **durability over the
promise**: a duplicate alert to aitrader is preferable to a lost one, and the
privacy concern is addressed by shrinking the window rather than by refusing to
write.

**This is the decision.** Everything else in this ADR is implementation or
evidence.

### D4 — Revisit trigger: the dataset's snapshot posture

D1 rests on a **measured property of today's deployment**, not a guarantee.
**If a snapshot or replication task is ever added to the ZFS dataset holding
`/mnt/datapool/apps/chat-gateway/state`, D's erasure stops being an erasure** —
every §2.2 figure reverts to a floor and this ADR should be revisited, with E
back on the table. Named here so it is a trigger rather than a footnote, in the
same spirit as ADR-0001 §11.

### D5 — The `inbox-data/` half is IN SCOPE, by a second decision the same day

⚠ **This was decided after D1–D3, and the sequence matters.** `D + A` was chosen
while §9 Q5 was open, on the explicit understanding that it fixed the **smaller**
of the two exposures §2 measured. The user then **widened CG-65's implementation
scope to cover both** rather than accept the smaller fix. So:

- **`inbox-data/<app>-<date>.jsonl` — `0644`, never pruned, whole inbound events
  including `raw` — is fixed in the same cycle as the journal**, not deferred.
- **§4.1 carries the shape** and is deliberately *not* lettered into §4: options
  A–G were written about a queue journal, and none of them fits an audit trail.
  Saying so is the point (`journal.py:9-12` draws exactly this distinction).
- **The mode fix is a straight lift** of `journal.py`'s existing
  `_chmod_quietly`; the pruning half is a **time-bounded** policy in days, never
  count-bounded — §4.1 requirement 2 explains why repeating the journal's
  count-bound here would reproduce this ADR's own §2.2 finding as a defect.

### D6 — C's hard-rule-#1 question is NOT REACHED, and is kept

Option C was not chosen, so *"is a per-app privacy flag app-domain knowledge
leaking into the gateway, or is it transport policy?"* does not arise and is
**not resolved**. The argument in §4 Option C stays on the record in full.
**It will recur** — and §4.1 identifies a place it may recur immediately, since
a per-tenant *retention* window is per-app registry policy of exactly the same
shape. When it does, argue it from §4's text rather than re-deriving it.

### D7 — What `D + A + D5` still does not do

Stated so no reader infers more than was decided:

- **It does not make `aitrader.md:217` true.** A body is still written, and is on
  disk for as long as its job is live. D changes the magnitude by orders of
  magnitude, not the kind — which is why D2 is not optional.
- **It does not resolve §9 Q6**, the *"never pruned"* promise at
  `docs/integration-guide.md:366-367` that D5's pruning would breach. That is
  open, it is owed to **every** consumer rather than to jobhunt alone, and a
  Builder must not prune past it without an answer.
- **It does not touch `state/deliveries/*.jsonl`'s content** — the delivery log
  remains titles-only and permanent, which §3 confirms is still structurally
  true. Only its `0644` mode is in D5's scope.

---

### The pre-decision recommendation, kept verbatim

*This section was written before the decision, marked as a recommendation, in a
section that existed to be overruled. It was not overruled. It is kept unedited
rather than folded into D1–D3, so that what was recommended — and on what
reasoning, before §9 Q4's answer arrived — stays legible beside what was chosen.*

> If the user wants a starting position rather than a blank page:
>
> **D + A**, and explicitly **not** B or C unless the promise is judged worth
> more than the durability.
>
> **Why D:** it removes ~all of the measured exposure — the residency of a
> *finished* body drops from weeks to seconds — at **zero cost to the durability
> guarantee CG-54 just paid for**, zero new per-app surface, zero new secrets,
> and no change to the mid-flight double-send answer. It is the only option on
> the list where the privacy axis and the durability axis are not actually in
> tension, because a terminal job's payload has **no replay value whatsoever**.
> Retaining it for another 499 notifies buys nobody anything.
>
> **Why A regardless:** the sentence is false today and every option leaves it
> false. Under D the true replacement is short and defensible — *"the body is on
> disk only while the alert is undelivered, normally under a second, at most
> ~73 minutes on the retry ladder, and up to 24h if the gateway is down; it is
> erased when the queue drains; file mode 0600."*
>
> **Why not B/C as the first move:** they are the only options that restore the
> literal promise, and they buy it by reversing CG-54's *"losing an alert is the
> worse failure"* for the one tenant that has no second channel. That may still
> be the right call — it is a contract, and a real-money system's owner may
> genuinely prefer a lost alert to a written-down one — but it should be chosen
> on those terms and not slid into as a privacy fix. **If C is chosen, choose the
> mechanical flag name** (`journal_payload: reference_only`), for the rule #1
> reason in §4.
>
> **G is the fallback** if D's compact-on-drain is judged too clever for a
> durability path: one constant, most of the benefit, none of the elegance.
>
> ⚠ **This recommendation is worth less than the user's answer to §10 question 4
> (snapshots).** If `datapool` snapshots or replicates the state dataset, D's
> erasure never reaches those copies and the whole ranking shifts toward E or
> toward B/C.

---

## 7. Hard-rule audit

| Rule | Effect |
|---|---|
| **#1 transport, never schemas** | The live question, and it lands on **option C only**. Argued both ways in §4 rather than assumed. A/B/D/E/F/G introduce no per-app knowledge at all. Under C the gateway would decide *whether to write bytes*, never *what they mean* — the same shape as `allow_inbound`, which rule #6 is built on. Flagged for sign-off, not resolved here |
| **#2 secrets are env-only** | **Intact under A/B/C/D/F/G** — identity NAMES are journalled and re-resolved through the registry; `configCompleteRedirect*` redaction is untouched. **Option E moves it**: it introduces a new env secret whose loss makes the queue unreplayable. That is the one option that touches this rule, and it touches it in the wrong direction |
| **#3 adapters + flag discipline** | Untouched. Nothing here is Google-facing; no ⚠ flag is cleared, added or reworded, and the ledger in `CLAUDE.md` is linked rather than restated |
| **#4 per-app auth + allowlists** | Reinforced by the existing design and unchanged by every option: `restore` re-resolves identities through the registry, so a withdrawn grant closes the job `unroutable` rather than sending on a stale permission (`delivery.py:283-292`) |
| **#5 `/healthz` stays honest** | **Constrains B and C.** A tenant whose queue cannot replay must say so — a new terminal status and a `reasons` line, not a silent difference. It also constrains A: if the contract is corrected to name a retention window, `/healthz` should not contradict it. D and G need no new field |
| **#6 inbound opt-in, opt-out absolute** | **Untouched by #45 and by every option.** `dispatch` hits `continue` at `pubsub.py:709` before `inbox.put` at `:727`, so no opted-out tenant's inbound event is journalled, audited, or forwarded. Nothing here widens any tenant's inbound surface |

**Re-audited for D5 (`inbox-data/`), added 2026-07-31 with the widened scope:**

| Rule | Effect of D5 |
|---|---|
| **#1** | The mode fix is clean. **Pruning is clean only while the window is global.** A *per-tenant* retention window would be per-app registry policy of the same shape as Option C, so it re-opens D6's not-reached question — flagged in §4.1, not decided |
| **#2** | Unaffected. `configCompleteRedirect*` is already blanked before anything is audited (`pubsub.py:150-159`), so no capability URL is in these files to begin with. Deleting them removes no credential because none is there |
| **#5** | **Constrains D5.** A sweeper that deletes tenant content must be counted at `/healthz`. Rule #5 does not distinguish work *dropped* from work *deleted*, and a silent deletion path on an artifact two documents call "the only copy" is exactly the shape of failure that rule exists for |
| **#6** | Untouched. `aitrader` never reaches `inbox.put` (§2.7), so nothing in D5 concerns it. `_unrouted` is the gateway's own bucket, not a tenant's |

---

## 8. What this ADR could not verify

Recorded plainly, because an unrecorded gap becomes a silent assumption.

- ✅ **RESOLVED 2026-07-31 — the snapshot question.** This entry read: ⚠
  *"Whether the TrueNAS `datapool` dataset holding
  `/mnt/datapool/apps/chat-gateway/state` is snapshotted or replicated. Neither
  the arc plan nor the spec says. If it is, every retention number in §2.2 is a
  **floor**, compaction erases nothing that matters, and options D/F/G lose most
  of their value. This is the single highest-leverage unknown in the document and
  only the user can look."* **The user looked: it is a plain dataset — no
  snapshots, no replication.** So §2.2's numbers are ceilings, not floors, and
  this stopped being a gap. Kept in place rather than deleted, because it was the
  fact that decided §6 D1 and a reader of §6 should be able to find where it came
  from. ⚠ It is a **property, not a guarantee** — D4 makes a future snapshot task
  a named revisit trigger.
- **Real traffic volume.** §2.2's table is parameterised because the actual
  gateway-wide notify rate has never been measured — the gateway has not been
  deployed. `journal.py:16`'s *"tens of messages a day"* is a design assumption,
  not an observation.
- **Whether any of this has ever run in production.** It has not. There is no
  deployed gateway (CG-55 is queued), so no journal file containing a real
  tenant's body exists anywhere today. **Deciding before CG-55 deploys means
  deciding before any real body is ever written** — which is the cheapest moment
  this decision will ever be available, and an argument for settling it now
  rather than after.
- **Whether `0600` survives the container's user mapping.** The compose bind
  mounts `state:/data/state` and the files are created by the container's uid.
  Measured on the dev box, not in the deployment.
- **Nothing about Google.** No adapter, no envelope, no flag is engaged. See
  `CLAUDE.md`'s verification ledger for what is unexercised against Google; it is
  a different axis and is not restated here.

---

## 9. Open questions

> **Q1–Q5 are ANSWERED (2026-07-31). Q6 is NEW and OPEN.** The questions are kept
> in their original wording — a question is an artifact, and rewriting one to
> match its answer erases what was actually asked.

| # | Answer |
|---|---|
| **1** | **`D + A`**, plus D5's widening. §6 |
| **2** | **Durability.** The promise is rewritten, not restored. §6 D3 |
| **3** | **NOT REACHED** — C was not chosen. Kept unresolved on purpose. §6 D6 |
| **4** | **No snapshots, no replication.** §2.9, §8, §6 D1 |
| **5** | **Folded into CG-65's scope** — both exposures, one cycle. §6 D5, §4.1 |
| **6** | ⚠ **OPEN** — new, raised by Q5's answer |

1. **Which option, or which combination?** §4 costs seven; §6 recommends D + A
   and marks it as a recommendation.
   → ✅ **`D + A`.**
2. **Is the aitrader promise worth the durability?** Only B/C can restore
   `:217`'s property, and only by reversing CG-54's *"losing an alert is the
   worse failure"* for the tenant with no second channel. **This is the decision;
   everything else is implementation.**
   → ✅ **No — the durability is kept and the promise is rewritten.**
3. **If C: is a per-app `journal_payload` flag consistent with hard rule #1?**
   §4 argues both sides and does not resolve it. Precedent (`allow_inbound`)
   favours yes; the uniformity cost is real.
   → ⏸ **NOT REACHED, not resolved.** C was not chosen. Deliberately left open;
   §4.1 identifies where it may become live again (a per-tenant retention window
   is the same shape).
4. ⚠ **Is `/mnt/datapool/apps/chat-gateway/state` on a snapshotted or replicated
   ZFS dataset?** A one-line answer that re-ranks the whole option list (§8).
   → ✅ **No. Plain dataset.** This is the fact that confirmed D (§6 D1), and its
   future reversal is a named revisit trigger (§6 D4).
5. **Should the `0644` never-pruned files be brought into scope?**
   `inbox-data/<app>-<date>.jsonl` holds whole inbound events including `raw`,
   world-readable and unbounded in time — **a larger exposure than the journal,
   predating #45 by months, and outside CG-65's framing.** Fixing only the
   journal fixes the smaller half. Separate queue item, or part of this decision?
   → ✅ **Part of this decision.** CG-65's implementation scope now covers both.
   §6 D5; shape in §4.1.
6. ⚠ **NEW, and OPEN — raised by Q5's answer, not by the original ADR.** **Does
   pruning `inbox-data/` breach `docs/integration-guide.md:366-367`?** That
   published sentence tells **every** consumer the per-app audit is *"one file
   per app per day, written before anything is queued, **never pruned**"*, and
   `:382-383` says that when a journalled reply no longer parses *"the audit file
   is then the only copy"*. **Pruning breaks a promise by deleting, exactly as
   #45 broke one by writing.** This ADR surfaces it and does not resolve it. It
   needs its own answer before D5's pruning half ships — the mode half (`0600`)
   is unaffected and can proceed. Note the scope: this promise is in the shared
   integration guide, so it is owed to every tenant, not to jobhunt alone.

---

## 10. The question, stated crisply — ✅ **ANSWERED 2026-07-31**

> ### Answer: **keep the durability.** `D + A`.
>
> The promise is rewritten as a bounded, stated retention rather than restored as
> an absolute, and option D shrinks that bound from weeks to seconds at no
> durability cost. **The snapshot sub-question came back "no"**, which is what
> made D's shrink a real one.
>
> **The question below is kept exactly as it was asked.** It is the artifact —
> the thing this ADR was written to produce — and a decided ADR that deletes its
> own question leaves the next reader unable to see what was actually weighed.

> **CG-54 bought durability by writing every `/v1/notify` body to disk, where it
> stays for roughly 500 gateway-wide notifies — weeks, at the traffic shape the
> design assumes — after the message has already been delivered. `aitrader` was
> promised in writing that no body text of its would ever be written anywhere.
> Both cannot stand.**
>
> **Do you want the gateway to keep the promise, or keep the durability?**
>
> - **Keep the promise** → option B or C. aitrader's queue stops being
>   replayable; a restart mid-flight loses an alert instead of duplicating one,
>   for the one tenant with no fallback channel.
> - **Keep the durability** → option A alone, or A + D/G. The promise is
>   rewritten as a bounded, stated retention rather than an absolute; D shrinks
>   that bound from weeks to seconds at no durability cost.
>
> **And, before either: is the state directory snapshotted?** If it is, D and G
> shrink a number that the snapshots put straight back, and the answer changes.

---

## 11. Related decisions and handoff

- [ADR-0001 — Tier-2 interaction model](2026-07-29-tier2-interaction-model.md).
  Not relitigated and not affected. Its D2/D3 conclusions concern inbound action
  identity; nothing here touches the envelope, the card convention, or any flag.
- [`docs/consumers/aitrader.md`](../../consumers/aitrader.md) §6, §8, §9 —
  **this ADR's decision determines that file's correction, and this ADR does not
  edit it.** CG-65 is the queue item that will.
- ⚠ [`docs/integration-guide.md`](../../integration-guide.md) `:366-367` and
  `:382-383` — the *"never pruned"* / *"the only copy"* promises that D5's
  pruning half would breach. **§9 Q6, open.** Owed to every consumer, not to one
  tenant.
- [`docs/superpowers/specs/2026-07-31-production-readiness-arc-design.md`](../../superpowers/specs/2026-07-31-production-readiness-arc-design.md)
  §7 and its plan — D2 (the tailnet ACL before first deploy) and the
  `install -d -m 0750` line that `journal.py` cites in advance.
- `docs/BUILDER_QUEUE.md` — **CG-65** (unblocked by §6; scope now covers both
  exposures per D5), **CG-66** (`journal.py`'s forward-dated citation — its
  `.gitignore` half shipped separately as **CG-67**/#48), **CG-54** (the change
  that caused this), **CG-55** (the deploy that would make any of this reach a
  real body for the first time). **This ADR does not edit that file.**
- [`CLAUDE.md`](../../../CLAUDE.md) — the six hard rules, audited in §7, and the
  verification ledger, **linked and deliberately not summarized**.

**Handoff — the decision is made; the implementation is not written here.**

- **No Designer involvement.** There is no UX surface.
- **Planner** turns §6 into CG-65's scope: **(a)** option D's compact-on-drain
  off §4's code shape, **(b)** option A's contract correction off §5's five
  consequences, and **(c)** D5's `inbox-data/` half off §4.1 — mode first,
  pruning **gated on §9 Q6**.
- **Builder** ships from that plan. A Builder must not re-open §6, must not
  resolve §9 Q6, and must not prune `inbox-data/` until Q6 is answered.
- **This ADR touches no source, no consumer contract, and no queue file.**
