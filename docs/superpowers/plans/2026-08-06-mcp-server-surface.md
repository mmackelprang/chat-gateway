# MCP server surface (CG-80) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The gateway speaks MCP over its existing HTTP surface, send-only, so an
MCP-speaking agent sends through the gateway and inherits its identity
allowlists and audit journalling.

**Architecture:** One new module, `src/chat_gateway/mcp.py`, exposing an
`APIRouter` that `create_app` mounts when `GATEWAY_ENABLE_MCP=1`. It is a
stateless, tools-only, JSON-only MCP server on `POST /mcp`, **dual-era** — it
serves both the legacy handshake protocol (`2025-11-25` and earlier) and the
modern stateless protocol (`2026-07-28`) on the same endpoint. Authentication is
the **existing** `authenticate()`; the single tool's `inputSchema` is
**generated** from `OutboundMessage.model_json_schema()`; the send path is the
one `POST /v1/messages` already uses. Nothing below the tool call is new code.

**Tech Stack:** Python 3.10+, FastAPI, pydantic v2, pytest. **No new dependency.**

**Spec:** [`docs/superpowers/specs/2026-08-06-mcp-server-surface-design.md`](../specs/2026-08-06-mcp-server-surface-design.md).
Read §3, §6 and §7 before Task 1. Section references below are to that spec.

**Baseline:** `main` at `f4b9c99`, suite **390 passing**. Re-measure with
`python3 -m pytest -q` before Task 1 and record the number you actually get —
do not copy `390` forward if your run disagrees.

---

## Global Constraints

Every task's requirements implicitly include all of these.

1. **Hard rule #1 — transport, never schemas.** The tool's `inputSchema` is
   **generated** from `OutboundMessage.model_json_schema()`. **No property is
   hand-written.** The only permitted mutation is narrowing `identity` against
   registry data (its `enum` and `description`). Do not add a card-builder tool,
   do not enrich the `cards` schema, do not put an example card in a description.
   Tool descriptions describe **transport, not occasions**.
2. **Hard rule #2 — secrets are env-only.** Any exception message reaching an MCP
   tool result goes through `errors.describe_exception`. An MCP tool result is a
   print site whose destination is a model's context window. Never build a second
   allowlist. Committed files carry env-var **NAMES** only.
3. **Hard rule #3 — Google-facing code lives only in `adapters/`.** This row adds
   no `adapters/` code and makes no Google call of its own. **No ⚠
   LIVE-UNVERIFIED or ⚠ SHAPE-VERIFIED flag may be cleared, added, re-priced or
   reworded.** Verify before opening the PR:
   `git diff main -- src/ | grep -c "LIVE-UNVERIFIED\|SHAPE-VERIFIED"` → **0**.
   ⚠ A live round-trip through the MCP tool will *look* like fresh Google
   evidence. **It is not** — same bytes, different caller (§11).
4. **Hard rule #4 — per-app auth + identity allowlists.** No new key, no shared
   key, no identity wildcard. Reuse `authenticate()` and `registry.identity_for`;
   do not re-implement either. The per-app `enum` is defence in depth and **never
   a substitute** for the `identity_for` check at call time.
5. **Hard rule #5 — `/healthz` stays honest.** Exactly one new field,
   `mcp: {"enabled", "tools"}`. **No counters.** It is **never** an input to
   `status` and adds **no** `reasons` entry at any value (§10).
6. **Hard rule #6 — inbound.** **No inbound tool of any kind.** Not `read_inbox`,
   not a "check for replies" convenience, not a resource. That is CG-81 and it
   needs the user's explicit sign-off naming rule #6 (§7).
7. **`cacheScope` is `"private"`.** Never `"public"`. The per-app `enum` makes the
   tool list vary by API key, and `"public"` lets an intermediary serve one
   tenant's identity allowlist to another — a rule-#4 leak delivered by a cache
   header (§6.3 row 5).
8. **No new runtime dependency.** `pyproject.toml`'s `dependencies` list is
   unchanged.
9. **The suite stays offline.** No network in any test. Use the `FakeAdapter`
   idiom from `tests/test_service.py::FakeAdapter`.
10. **Test command:** `python3 -m pytest` on POSIX, `python -m pytest` on the
    Windows dev box (its msys `python3` has no pytest).
11. **Branch policy:** all work on `feat/cg-80-mcp-server-surface`. Never commit
    to `main`.
12. ⚠ **Protocol revisions are dated immutable identifiers; "which is latest" is
    not.** `2025-11-25` and `2026-07-28` are pinned in code as constants. Before
    Task 1, **re-read** the revision list at
    `https://modelcontextprotocol.io/specification/versioning` and report to the
    user if a newer revision has landed — do **not** silently retarget.

---

## File Structure

| File | Responsibility |
|---|---|
| **Create** `src/chat_gateway/mcp.py` | Everything MCP: protocol constants, the era discriminator, header/`_meta` validation, both eras' method dispatch, the tool definition and its derived schema, and the tool executor. One module because these change together and are meaningless apart. |
| **Create** `tests/test_mcp.py` | All fifteen test groups from spec §13. |
| **Modify** `src/chat_gateway/service.py` | Two edits only: mount the router when enabled, and add the `mcp` field to `/healthz`. |
| **Modify** `src/chat_gateway/__main__.py` | Read `GATEWAY_ENABLE_MCP` and pass it to `create_app`. Docstring env list. |
| **Modify** `.env.example`, `config/registry.example.yaml`, `README.md`, `docs/integration-guide.md`, `docs/deploy/nas.md` | Documentation and the example agent tenant. |

---

## Task 1: The endpoint skeleton — auth and the transport-level guards

**Files:**
- Create: `src/chat_gateway/mcp.py`
- Create: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `chat_gateway.auth.authenticate`, `chat_gateway.registry.Registry`.
- Produces: `build_router(registry, adapters) -> APIRouter`;
  constants `LEGACY_PROTOCOL_VERSION`, `MODERN_PROTOCOL_VERSION`,
  `SUPPORTED_PROTOCOL_VERSIONS`, `TOOL_NAMES`, `ALLOWED_ORIGINS_ENV`;
  helpers `jsonrpc_error(rid, code, message, data=None) -> dict`,
  `jsonrpc_result(rid, result) -> dict`.

- [x] **Step 1: Write the failing tests**

Create `tests/test_mcp.py`:

```python
"""The MCP server surface, end to end, with a fake delivery adapter.

Offline: no network, no Google. Same idiom as tests/test_service.py.
"""

import pytest
from fastapi.testclient import TestClient

from chat_gateway.envelope import DeliveryResult
from chat_gateway.inbox import Inbox
from chat_gateway.registry import load_registry
from chat_gateway.service import create_app

REGISTRY_YAML = """
identities:
  pm-familyworkspace:
    display: "PM · familyworkspace"
    mode: webhook
    webhook_url_env: SVC_HOOK_FW
    space: "spaces/AAA"
  agent-notes:
    display: "Agent notes"
    mode: webhook
    webhook_url_env: SVC_HOOK_AGENT
    space: "spaces/AAA"
  other-only:
    display: "Someone else's identity"
    mode: webhook
    webhook_url_env: SVC_HOOK_OTHER
    space: "spaces/BBB"
apps:
  aiteam-harness:
    key_env: SVC_KEY_AITEAM
    identities: [pm-familyworkspace, agent-notes]
  job-hunter:
    key_env: SVC_KEY_JOBHUNT
    identities: [other-only]
"""

AUTH = {"Authorization": "Bearer cgk_test_key"}
OTHER_AUTH = {"Authorization": "Bearer cgk_other_key"}


class FakeAdapter:
    """Records sends; can be told to raise. Mirrors tests/test_service.py::FakeAdapter."""

    def __init__(self):
        self.sent = []
        self.raises = None

    def send(self, identity, message):
        if self.raises is not None:
            raise self.raises
        self.sent.append((identity.name, message))
        return DeliveryResult(status="delivered", channel="google_chat",
                              identity=identity.name, mode=identity.mode,
                              thread_key=message.thread_key)


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SVC_KEY_AITEAM", "cgk_test_key")
    monkeypatch.setenv("SVC_KEY_JOBHUNT", "cgk_other_key")
    monkeypatch.setenv("SVC_HOOK_FW", "https://x.example/hook")
    monkeypatch.setenv("SVC_HOOK_OTHER", "https://y.example/hook")
    # SVC_HOOK_AGENT deliberately unset: it drives the readiness rendering in
    # the tool schema AND /healthz's `reasons`, from the same env_resolved().
    monkeypatch.delenv("SVC_HOOK_AGENT", raising=False)
    monkeypatch.delenv("CHAT_GATEWAY_MCP_ALLOWED_ORIGINS", raising=False)
    p = tmp_path / "r.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    registry = load_registry(p)
    inbox = Inbox()
    adapter = FakeAdapter()
    app = create_app(registry, inbox, {"webhook": adapter}, mcp_enabled=True)
    return TestClient(app), adapter


def rpc(client, body, headers=None, **kw):
    """POST one JSON-RPC message with the default auth header."""
    h = dict(AUTH)
    h.update(headers or {})
    return client.post("/mcp", headers=h, json=body, **kw)


# ---------------------------------------------------------------- group 1 ---
def test_mcp_requires_a_bearer_key_on_every_request_including_the_handshake(env):
    client, _ = env
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_mcp_rejects_an_unknown_key(env):
    client, _ = env
    r = client.post("/mcp", headers={"Authorization": "Bearer nope"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r.status_code == 401


def test_the_www_authenticate_header_does_NOT_advertise_resource_metadata(env):
    """Spec §5. A `resource_metadata` pointer would send a conformant client
    down an OAuth discovery path that dead-ends here — we mint our own keys."""
    client, _ = env
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert "resource_metadata" not in r.headers["www-authenticate"]


# ---------------------------------------------------------------- group 7 ---
def test_get_and_delete_on_the_mcp_endpoint_are_405(env):
    """Conformant in BOTH eras: 2025-11-25 makes 405 the explicit alternative
    to offering an SSE stream, and 2026-07-28 says a modern-only server SHOULD
    answer GET and DELETE with 405. We have nothing to stream."""
    client, _ = env
    assert client.get("/mcp", headers=AUTH).status_code == 405
    assert client.delete("/mcp", headers=AUTH).status_code == 405


def test_a_jsonrpc_batch_array_is_refused(env):
    """Batching was removed in 2025-06-18 and 2026-07-28 re-states it as a
    transport MUST: the POST body MUST be a single request or notification."""
    client, _ = env
    r = rpc(client, [{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32600


def test_an_unparseable_body_is_a_parse_error(env):
    client, _ = env
    r = client.post("/mcp", headers=AUTH, content=b"{not json",
                    headers_extra=None) if False else client.post(
        "/mcp", headers={**AUTH, "Content-Type": "application/json"},
        content=b"{not json")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32700


# ---------------------------------------------------------- Origin (§6.3) ---
def test_a_request_with_no_origin_header_is_NOT_refused(env):
    """The spec's MUST fires only when Origin is PRESENT and invalid. A
    non-browser MCP client sends none, and refusing those would lock out
    every client we care about."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code != 403


def test_a_present_origin_is_refused_when_no_allowlist_is_configured(env):
    """Fail closed. We serve no browser client, and DNS-rebinding protection
    is a MUST — so an unrecognised Origin is 403 rather than waved through."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_an_allowlisted_origin_is_accepted(env, monkeypatch):
    client, _ = env
    monkeypatch.setenv("CHAT_GATEWAY_MCP_ALLOWED_ORIGINS",
                       "https://ok.example, https://also-ok.example")
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Origin": "https://also-ok.example"})
    assert r.status_code != 403
```

⚠ **Delete the dead ternary in `test_an_unparseable_body_is_a_parse_error`** —
it is written above only to show the shape; the working form is:

```python
def test_an_unparseable_body_is_a_parse_error(env):
    client, _ = env
    r = client.post("/mcp", headers={**AUTH, "Content-Type": "application/json"},
                    content=b"{not json")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32700
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_mcp.py -q`
Expected: FAIL — `create_app() got an unexpected keyword argument 'mcp_enabled'`.

- [x] **Step 3: Create `src/chat_gateway/mcp.py`**

```python
"""The MCP (Model Context Protocol) server surface — another ingress to the
send path, not a new capability.

WHAT THIS IS. `POST /mcp` speaks MCP's Streamable HTTP transport as a
stateless, tools-only, JSON-only server, and its one tool reaches
`adapter.send` through the same `registry.identity_for` that `POST
/v1/messages` uses. Everything below the tool call is unchanged code. That is
the whole architectural claim, and it is what makes hard rule #4 hold here by
REUSE rather than by a second implementation that could drift.

WHY IT IS DUAL-ERA, which is most of this module's size. MCP revision
`2026-07-28` is a breaking stateless overhaul: it DELETED `initialize`,
`notifications/initialized`, `ping` and `Mcp-Session-Id`, and added
`server/discover`, per-request `_meta`, three required headers and
`resultType`/`ttlMs`/`cacheScope`. The compatibility matrix has no mercy in
either direction — a modern client cannot talk to a legacy server and a legacy
client cannot talk to a modern one. Serving one era would make this gateway
SILENTLY UNREACHABLE to clients speaking the other, which is the one outcome
the design was trying to avoid. The spec sanctions serving both on one
endpoint; `_era_of` is the discriminator and it is the outermost seam in this
file, so dropping an era later is deleting a branch rather than unpicking a
design.

WHAT THIS MODULE MUST NEVER LEARN (hard rule #1). A tool's `inputSchema` is a
schema and its `description` is a PROMPT, so both are places app-domain
knowledge leaks in — invisibly, because it reads as helpfulness. The rule that
keeps it out is mechanical rather than tasteful: the schema is GENERATED from
`OutboundMessage.model_json_schema()` and no property is hand-written. The only
permitted mutation narrows `identity` against the registry's own allowlist,
which is data this gateway definitively owns. `tests/test_mcp.py` pins the
derivation, so a hand-edit turns the suite red. In particular: `cards` stays an
opaque array of objects. A model handed an untyped `cards` array will ignore it
or hallucinate, and the fix that suggests itself — a card builder, an
`add_button` tool, a simplified card schema — is rule #1 saying no. This
gateway's total knowledge of Cards v2 is one validator asserting `"card" in
entry` (`envelope.py`), and this module adds no second byte to it.

WHAT IT DOES NOT DO. No inbound tool of any kind. MCP has no server push at
all — a server cannot send a request, cannot send an unsolicited notification,
and cannot cause an LLM turn — so an inbound tool could only ever be polling a
model must remember to do, which is strictly worse than the `callback_url` push
this gateway already has. It is also blocked on `Inbox.poll` draining: until
CG-56 lands ack-based reads, an MCP reader and a tenant's production poller are
competing DESTRUCTIVE consumers of one queue. The full argument, both ways, has
one home and it is not here:
`docs/superpowers/specs/2026-08-06-mcp-server-surface-design.md` §7.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from typing import Any

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse

from . import __version__
from .auth import AuthError, authenticate
from .envelope import OutboundMessage
from .errors import describe_exception
from .registry import Registry, RegistryError

# --- protocol revisions ------------------------------------------------------
#
# DATED, IMMUTABLE identifiers — safe to pin. "Which revision is current" is a
# moving external fact and deliberately has NO copy in this repo: see the spec's
# §6.1. Ordered newest first; `server/discover` publishes this list verbatim.
LEGACY_PROTOCOL_VERSION = "2025-11-25"
MODERN_PROTOCOL_VERSION = "2026-07-28"
SUPPORTED_PROTOCOL_VERSIONS = [MODERN_PROTOCOL_VERSION, LEGACY_PROTOCOL_VERSION]

# --- modern-era `_meta` keys -------------------------------------------------
META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

# --- JSON-RPC and MCP error codes -------------------------------------------
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
HEADER_MISMATCH = -32020
UNSUPPORTED_PROTOCOL_VERSION = -32022

#: How long a client may cache `tools/list`. Five minutes: long enough to be
#: worth having, short enough that an operator who edits the registry and
#: restarts is not fighting a stale tool list for an hour.
TOOLS_TTL_MS = 300_000

#: ⚠ ALWAYS "private", NEVER "public", and this is a hard rule #4 control rather
#: than a performance knob. "public" asserts the response carries no
#: user-specific data and MAY be cached ACROSS authorization contexts — and this
#: server's tool list DOES vary by API key, because `identity`'s enum is that
#: app's allowlist. "public" would therefore let an intermediary serve one
#: tenant's identity allowlist to another: a rule #4 violation delivered by a
#: cache header, and invisible in a code review that is looking at the auth
#: check. `server/discover` does not vary by caller and could be "public", but
#: uses this same constant: one home for the value beats two that can drift, and
#: "private" is never incorrect.
CACHE_SCOPE = "private"

#: Comma-separated allowlist of acceptable `Origin` values. Names the var only
#: (hard rule #2 style, though this holds no secret).
ALLOWED_ORIGINS_ENV = "CHAT_GATEWAY_MCP_ALLOWED_ORIGINS"

#: The tool names this server exposes. Module-level because `/healthz` publishes
#: them and they do NOT vary by caller — only the identity enum inside
#: `send_message`'s schema does.
TOOL_NAMES = ("send_message",)

_SENTINEL_PREFIX = "=?base64?"
_SENTINEL_SUFFIX = "?="


class _McpRequestError(Exception):
    """A malformed MCP request, carrying the status and JSON-RPC code to answer.

    Deliberately NOT a `GatewayAuthoredError`. That marker is a claim that
    `describe_exception` may print the message in full, and this exception is
    never printed anywhere — it is caught in `_handle` and rendered into a
    response body assembled from literals in this file. Marking it would enrol
    its raise sites in `tests/test_error_surfaces.py` for no benefit and would
    imply a print site that does not exist.
    """

    def __init__(self, http_status: int, code: int, message: str,
                 data: dict | None = None):
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.message = message
        self.data = data


def jsonrpc_error(rid: Any, code: int, message: str,
                  data: dict | None = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": err}


def jsonrpc_result(rid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _check_origin(origin: str | None) -> None:
    """DNS-rebinding protection. The spec makes this a MUST.

    Note the exact conditional it states: the 403 fires only when `Origin` is
    PRESENT and invalid. A missing `Origin` — which is what every non-browser
    MCP client sends — is not covered, and refusing those would lock out every
    client this row exists for.

    With no allowlist configured, ANY present `Origin` is invalid. That is the
    fail-closed direction and it is correct here: this server has no browser
    client, so a browser presenting itself is either a mistake or the attack the
    rule describes.
    """
    if origin is None:
        return
    allowed = [o.strip() for o in os.environ.get(ALLOWED_ORIGINS_ENV, "").split(",")
               if o.strip()]
    if origin not in allowed:
        raise _McpRequestError(403, INVALID_REQUEST,
                               "origin not allowed")


def build_router(registry: Registry, adapters: dict[str, Any]) -> APIRouter:
    router = APIRouter()

    @router.post("/mcp")
    async def mcp_post(request: Request,
                       authorization: str | None = Header(default=None),
                       origin: str | None = Header(default=None)):
        try:
            _check_origin(origin)
            try:
                app_id = authenticate(registry, authorization)
            except AuthError as exc:
                # Bare `Bearer`, with NO `resource_metadata` parameter. That
                # parameter is how an OAuth-protected resource points a client at
                # its authorization server; we mint and validate our own per-app
                # keys, so advertising it would send a conformant client down a
                # discovery path that dead-ends.
                return JSONResponse(
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                    content=jsonrpc_error(None, INVALID_REQUEST, str(exc)))
            try:
                payload = json.loads(await request.body())
            except (ValueError, UnicodeDecodeError):
                raise _McpRequestError(400, PARSE_ERROR, "invalid JSON")
            if not isinstance(payload, dict):
                raise _McpRequestError(
                    400, INVALID_REQUEST,
                    "the POST body must be a single JSON-RPC request or "
                    "notification; batching was removed from the protocol")
            return await _handle(registry, adapters, app_id, payload, request)
        except _McpRequestError as exc:
            return JSONResponse(
                status_code=exc.http_status,
                content=jsonrpc_error(None, exc.code, exc.message, exc.data))

    @router.get("/mcp")
    @router.delete("/mcp")
    async def mcp_no_stream():
        """No SSE stream and no session to delete.

        Conformant in both eras: `2025-11-25` makes 405 the explicit alternative
        to returning `text/event-stream`, and `2026-07-28`'s backward-compat
        section says a modern-only server SHOULD answer GET and DELETE with 405.
        We have nothing to stream — MCP gives a server no way to push, which is
        the finding the whole design rests on.
        """
        return Response(status_code=405)

    return router


async def _handle(registry: Registry, adapters: dict[str, Any], app_id: str,
                  payload: dict, request: Request) -> JSONResponse:
    """Placeholder dispatch — Tasks 4 and 5 fill in the two eras."""
    return JSONResponse(
        content=jsonrpc_error(payload.get("id"), METHOD_NOT_FOUND,
                              f"method not found: {payload.get('method')}"),
        status_code=404)
```

- [x] **Step 4: Mount it behind the flag in `service.py`**

In `src/chat_gateway/service.py`, add `mcp_enabled` to `create_app`'s signature.
Modify the signature block (currently ending `monitor_interval: float = 60.0`):

```python
               sweeper: Any | None = None,
               # CG-80. Default OFF, the same posture GATEWAY_ENABLE_PUBSUB
               # takes for a new surface: an operator arms it deliberately, and
               # /healthz then says whether the running image both HAS it and
               # HAS IT ON — two separate facts, which is the lesson CG-59 paid
               # for when a deployed container answered 200 to a query parameter
               # it did not have.
               mcp_enabled: bool = False,
               monitor_interval: float = 60.0) -> FastAPI:
```

Then, immediately after the `app.state.sweeper = sweeper` line, add:

```python
    # CG-80. Mounted, not always-on: `/mcp` is a new authenticated surface and
    # this repo's posture on those is conservative. The router depends on the
    # SAME authenticate() every /v1/ route depends on — hard rule #4 satisfied
    # by reuse rather than by a second implementation that could drift.
    app.state.mcp_enabled = mcp_enabled
    if mcp_enabled:
        from .mcp import build_router

        app.include_router(build_router(registry, adapters))
```

- [x] **Step 5: Run the tests**

Run: `python3 -m pytest tests/test_mcp.py -q`
Expected: PASS (9 tests). The `ping` calls land on the placeholder `_handle` and
return 404, which none of Task 1's assertions contradict — they assert on 401,
403, 405, and 400 only.

- [x] **Step 6: Run the whole suite**

Run: `python3 -m pytest -q`
Expected: **399 passed** (390 baseline + 9). Record the real number.

- [x] **Step 7: Commit**

```bash
git add src/chat_gateway/mcp.py src/chat_gateway/service.py tests/test_mcp.py
git commit -m "feat(CG-80): the MCP endpoint skeleton — auth, Origin, 405, no batching

POST /mcp authenticates through the EXISTING authenticate() on every request
including the handshake, so hard rule #4 holds by reuse. GET and DELETE are
405 (conformant in both protocol eras; we have nothing to stream). A batch
array is refused — batching was removed in 2025-06-18.

Origin validation is a spec MUST and was missing from the design's first
draft. It fires only when Origin is PRESENT and invalid, because every
non-browser MCP client sends none. With no allowlist configured any present
Origin is refused: this server has no browser client, so a browser presenting
itself is either a mistake or the attack the rule describes.

WWW-Authenticate carries no resource_metadata parameter — we mint our own
keys, and advertising it would send a conformant client down an OAuth
discovery path that dead-ends."
```

---

## Task 2: The tool definition — a derived schema, and the guard that keeps it derived

**Files:**
- Modify: `src/chat_gateway/mcp.py`
- Modify: `tests/test_mcp.py`

**Interfaces:**
- Consumes: Task 1's module and constants.
- Produces: `send_message_schema(registry, app_id) -> dict`;
  `tools_for(registry, app_id) -> list[dict]`.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_mcp.py`:

```python
# ---------------------------------------------------------- groups 9, 10 ----
from chat_gateway.envelope import OutboundMessage  # noqa: E402
from chat_gateway.mcp import send_message_schema, tools_for  # noqa: E402


def _strip(schema):
    """Remove exactly the two things we are allowed to narrow, so the rest can
    be compared for equality against the generated schema."""
    out = {k: v for k, v in schema.items() if k not in ("title", "description")}
    props = {}
    for name, prop in out["properties"].items():
        props[name] = {k: v for k, v in prop.items()
                       if k not in ("enum", "description", "title")}
    out["properties"] = props
    return out


def test_the_tool_schema_is_GENERATED_not_hand_written(env):
    """Hard rule #1, mechanically.

    A tool inputSchema is a schema and a tool description is a prompt, so both
    are places app-domain knowledge leaks in. What separates a legitimate
    re-serialization of `OutboundMessage` from the gateway owning a second
    schema is exactly one thing: whether a human typed a property name. This
    test fails the moment one does.

    Same idiom as tests/test_error_surfaces.py — guard a property that
    otherwise lives only in prose.
    """
    registry_schema = OutboundMessage.model_json_schema()
    tool_schema = send_message_schema(_registry_of(env), "aiteam-harness")
    assert _strip(tool_schema) == _strip(registry_schema)


def test_cards_stays_an_opaque_array_of_objects(env):
    """Rule #1 corollary. The gateway's total knowledge of Cards v2 is one
    validator asserting `"card" in entry`. A richer cards schema here would be
    the gateway learning a channel's content format."""
    schema = send_message_schema(_registry_of(env), "aiteam-harness")
    assert schema["properties"]["cards"]["items"] == {
        "additionalProperties": True, "type": "object"}


def test_the_identity_enum_is_exactly_this_apps_allowlist(env):
    """Rule #4, defence in depth: a model cannot even FORM a call naming
    another tenant's identity, because the schema it was given lacks one."""
    reg = _registry_of(env)
    mine = send_message_schema(reg, "aiteam-harness")["properties"]["identity"]
    theirs = send_message_schema(reg, "job-hunter")["properties"]["identity"]
    assert mine["enum"] == ["pm-familyworkspace", "agent-notes"]
    assert theirs["enum"] == ["other-only"]
    assert "other-only" not in mine["enum"]


def test_the_identity_description_reports_live_readiness(env):
    """The tool schema and /healthz must agree, and they do because they read
    the same Identity.env_resolved(). SVC_HOOK_AGENT is unset in the fixture."""
    d = send_message_schema(_registry_of(env),
                            "aiteam-harness")["properties"]["identity"]["description"]
    assert "pm-familyworkspace" in d and "ready" in d
    assert "agent-notes" in d and "NOT CONFIGURED" in d


def test_the_tool_declares_all_four_annotations_explicitly(env):
    """The spec's defaults would produce these same values. Declaring them is
    deliberate: a tool that posts irreversibly into a human's chat space, twice
    if called twice, should SAY so rather than have a reader derive it from a
    default table."""
    tool = tools_for(_registry_of(env), "aiteam-harness")[0]
    assert tool["annotations"] == {"readOnlyHint": False, "destructiveHint": True,
                                   "idempotentHint": False, "openWorldHint": True}


def test_the_tool_name_needs_no_base64_sentinel_in_a_header(env):
    """Modern MCP requires an `Mcp-Name` header matching params.name. A name
    outside the header-safe set forces clients into the base64 sentinel form;
    ours does not."""
    import re
    for name in [t["name"] for t in tools_for(_registry_of(env), "aiteam-harness")]:
        assert re.fullmatch(r"[A-Za-z0-9_.\-]{1,128}", name), name


def test_narrowing_the_schema_cannot_poison_the_envelope_for_everyone_else(env):
    """⚠ A pydantic implementation detail this code DEPENDS on, pinned because
    its failure mode is silent and global.

    `send_message_schema` mutates the dict `model_json_schema()` hands back. If
    pydantic ever returned a CACHED dict instead of a fresh one, that mutation
    would persist — one app's identity enum would leak into the next caller's
    schema (a hard rule #4 breach), and into `/openapi.json`, which serves the
    same model to every unauthenticated reader of `/docs`.

    Measured on pydantic v2 today: each call returns a fresh, deeply
    independent dict. This test is what notices if an upgrade changes that.
    """
    reg = _registry_of(env)
    send_message_schema(reg, "aiteam-harness")
    send_message_schema(reg, "job-hunter")
    fresh = OutboundMessage.model_json_schema()
    assert "enum" not in fresh["properties"]["identity"]
    assert fresh["properties"]["identity"]["description"] == (
        "registered identity to send as (e.g. pm-familyworkspace)")
```

Add this helper near the top of the file, under the `env` fixture:

```python
def _registry_of(env):
    """The Registry the fixture's app was built from."""
    client, _ = env
    return client.app.state.registry
```

And expose it: in `create_app`, beside the other `app.state` assignments, add
`app.state.registry = registry`.

- [x] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_mcp.py -q`
Expected: FAIL — `cannot import name 'send_message_schema'`.

- [x] **Step 3: Implement**

Add to `src/chat_gateway/mcp.py`, after `_check_origin`:

```python
def send_message_schema(registry: Registry, app_id: str) -> dict:
    """The tool's `inputSchema` — GENERATED, never hand-written (hard rule #1).

    Two mutations are applied to the generated schema and only two, both
    narrowing `identity` against data this gateway definitively owns:

    * `enum` — exactly the identities the registry grants this app. Defence in
      depth, not enforcement: `registry.identity_for` still runs at call time
      and still refuses, because a client may call a tool it never listed.
      Hiding is not enforcing.
    * `description` — each identity's display name, mode and live readiness,
      rendered from `Identity.env_resolved()`. That is the SAME function
      `/healthz` reads, which is why the tool schema and the health endpoint
      cannot disagree about whether an identity works.

    `title` and the model's docstring are dropped because the tool carries its
    own `title` and `description`; keeping both would show a model two
    competing descriptions of the same thing.

    ⚠ Do not add, remove or rewrite any other property. The generated schema is
    measurably FLAT — no `$defs`, no `$ref` — so no flattening pass is needed,
    and a flattening pass is precisely where hand-editing would start.
    """
    schema = send_message_schema_base()
    app = registry.apps[app_id]
    granted = [n for n in app.identities if n in registry.identities]
    rows = []
    for name in granted:
        ident = registry.identities[name]
        rows.append(f"{name} ({ident.display}; {ident.mode}; "
                    f"{'ready' if ident.env_resolved() else 'NOT CONFIGURED'})")
    schema["properties"]["identity"]["enum"] = granted
    schema["properties"]["identity"]["description"] = (
        "which registered identity to send as. Your API key grants exactly "
        "these: " + "; ".join(rows))
    return schema


def send_message_schema_base() -> dict:
    """The generated schema, with the envelope's own titles stripped."""
    schema = OutboundMessage.model_json_schema()
    schema.pop("title", None)
    schema.pop("description", None)
    return schema


def tools_for(registry: Registry, app_id: str) -> list[dict]:
    """The tool list for one authenticated app.

    Varies by caller — which is exactly why `CACHE_SCOPE` is "private"; read
    that constant's comment before changing anything here.

    The `description` describes TRANSPORT, not occasions. "Deliver a message to
    Google Chat as one of the identities your API key allows" is transport;
    "use this to notify the team when a build fails" would be an occasion, and
    an occasion is app domain (hard rule #1).
    """
    return [{
        "name": "send_message",
        "title": "Send a Google Chat message",
        "description": (
            "Deliver a message to Google Chat as one of the identities your "
            "API key is allowed to send as. You supply the rendered content; "
            "this gateway owns identity, delivery and threading."
        ),
        "inputSchema": send_message_schema(registry, app_id),
        # The spec's defaults would give these same four values —
        # `destructiveHint` and `openWorldHint` both default to true. Declared
        # anyway: a tool that posts irreversibly into a human's chat space, and
        # posts twice if called twice, should say so rather than have a reader
        # derive it from a default table. Same reasoning as `thread_started`
        # sitting beside `thread_alive` at /healthz.
        "annotations": {"readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": False, "openWorldHint": True},
    }]
```

- [x] **Step 4: Run the tests**

Run: `python3 -m pytest tests/test_mcp.py -q`
Expected: PASS (16 tests).

- [x] **Step 5: Commit**

```bash
git add src/chat_gateway/mcp.py src/chat_gateway/service.py tests/test_mcp.py
git commit -m "feat(CG-80): the tool schema is generated, and a test keeps it that way

Hard rule #1's answer is mechanical rather than tasteful. A tool inputSchema
is a schema and a tool description is a prompt, so both are places app-domain
knowledge leaks in — invisibly, because it reads as helpfulness. What
separates re-serializing OutboundMessage from the gateway owning a second
schema is exactly one thing: whether a human typed a property name.

So the schema is GENERATED from OutboundMessage.model_json_schema(), and
test_the_tool_schema_is_GENERATED_not_hand_written compares it for equality
against a fresh generation. It fails the moment anyone hand-edits a property.
Same idiom as test_error_surfaces.py: guard a property that otherwise lives
only in prose.

Two narrowings are permitted, both against registry data the gateway owns:
identity gains an enum of exactly that app's allowlist, and a description
rendered from the same env_resolved() /healthz reads — so the tool schema and
the health endpoint cannot disagree about whether an identity works.

cards stays an opaque array of objects. A model handed one will ignore it or
hallucinate, and the fix that suggests itself — a card builder — is rule #1
saying no."
```

---

## Task 3: The tool executor — the send path and the error taxonomy

**Files:**
- Modify: `src/chat_gateway/mcp.py`
- Modify: `tests/test_mcp.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: `call_tool(registry, adapters, app_id, name, arguments) -> tuple[dict | None, dict | None]`
  returning `(call_tool_result, protocol_error_fields)` — exactly one is non-`None`.
  `protocol_error_fields` is `{"code": int, "message": str}`.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_mcp.py`:

```python
# --------------------------------------------------------- groups 11, 12 ----
from chat_gateway.errors import GatewayAuthoredError  # noqa: E402
from chat_gateway.mcp import call_tool  # noqa: E402


class _LeakyError(Exception):
    """Unmarked, so describe_exception must print its TYPE only."""


def test_a_successful_call_reaches_the_real_adapter(env):
    client, adapter = env
    result, err = call_tool(_registry_of(env), {"webhook": adapter},
                            "aiteam-harness", "send_message",
                            {"identity": "pm-familyworkspace", "text": "hi"})
    assert err is None
    assert result["isError"] is False
    assert adapter.sent[0][0] == "pm-familyworkspace"
    assert adapter.sent[0][1].text == "hi"


def test_an_ungranted_identity_is_a_TOOL_error_not_a_protocol_error(env):
    """The model asked a legitimate question and got a legitimate refusal
    naming what it MAY use, so it can self-correct. A protocol error would be
    invisible to it. Note this fires even though the enum would have hidden the
    name: hiding is not enforcing."""
    client, adapter = env
    result, err = call_tool(_registry_of(env), {"webhook": adapter},
                            "aiteam-harness", "send_message",
                            {"identity": "other-only", "text": "hi"})
    assert err is None
    assert result["isError"] is True
    assert "may not send as" in result["content"][0]["text"]
    assert adapter.sent == []


def test_invalid_arguments_are_a_tool_error(env):
    client, adapter = env
    result, err = call_tool(_registry_of(env), {"webhook": adapter},
                            "aiteam-harness", "send_message",
                            {"identity": "pm-familyworkspace", "text": ""})
    assert err is None
    assert result["isError"] is True


def test_an_unknown_tool_is_a_PROTOCOL_error(env):
    """-32602 (invalid params), NOT -32601. That code is reserved for an
    unimplemented RPC method and now carries an HTTP 404."""
    client, adapter = env
    result, err = call_tool(_registry_of(env), {"webhook": adapter},
                            "aiteam-harness", "no_such_tool", {})
    assert result is None
    assert err["code"] == -32602


def test_an_unmarked_adapter_exception_never_leaks_its_message(env):
    """Hard rule #2 at a NEW print site, and the most dangerous one this repo
    has: an MCP tool result lands in a model's context window and, from there,
    in a transcript that leaves the building. describe_exception prints an
    unmarked exception by TYPE alone."""
    client, adapter = env
    adapter.raises = _LeakyError("https://chat.googleapis.com/v1/spaces/X?key=SEKRIT&token=NOPE")
    result, err = call_tool(_registry_of(env), {"webhook": adapter},
                            "aiteam-harness", "send_message",
                            {"identity": "pm-familyworkspace", "text": "hi"})
    assert err is None
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "SEKRIT" not in text and "token=" not in text and "chat.googleapis" not in text
    assert "_LeakyError" in text


def test_a_marked_adapter_exception_keeps_its_message(env):
    """The other half of the allowlist: a class this repo authored every byte
    of prints in full, which is what makes the refusal legible."""
    class _Authored(GatewayAuthoredError, RuntimeError):
        pass

    client, adapter = env
    adapter.raises = _Authored("webhook returned HTTP 403 Forbidden")
    result, err = call_tool(_registry_of(env), {"webhook": adapter},
                            "aiteam-harness", "send_message",
                            {"identity": "pm-familyworkspace", "text": "hi"})
    assert result["isError"] is True
    assert "403 Forbidden" in result["content"][0]["text"]


def test_a_mode_with_no_adapter_is_a_tool_error(env):
    client, adapter = env
    result, err = call_tool(_registry_of(env), {}, "aiteam-harness",
                            "send_message",
                            {"identity": "pm-familyworkspace", "text": "hi"})
    assert err is None
    assert result["isError"] is True
    assert "no adapter" in result["content"][0]["text"]
```

- [x] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_mcp.py -q`
Expected: FAIL — `cannot import name 'call_tool'`.

- [x] **Step 3: Implement**

Add to `src/chat_gateway/mcp.py`, after `tools_for`:

```python
def _text_result(text: str, is_error: bool) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def call_tool(registry: Registry, adapters: dict[str, Any], app_id: str,
              name: str, arguments: dict) -> tuple[dict | None, dict | None]:
    """Execute one tool call. Returns `(result, protocol_error)`; exactly one
    is non-None.

    THE SPLIT IS THE POINT, and the spec is unusually direct about why: "Any
    errors that originate from the tool SHOULD be reported inside the result
    object, with isError set to true, not as an MCP protocol-level error
    response. Otherwise, the LLM would not be able to see that an error
    occurred and self-correct."

    So an identity refusal is a TOOL error carrying the registry's own message —
    the model asked a legitimate question, got a legitimate refusal naming what
    it MAY use, and can correct itself. Only "which tool?" is a protocol error,
    because no rewording of the arguments fixes it.

    ⚠ Every exception message that reaches the returned text goes through
    `describe_exception` (hard rule #2, CG-29's allowlist). This is a print site
    and arguably the most dangerous one in this repo: its destination is a
    model's context window and, from there, a transcript. Do not build a second
    allowlist here, and do not interpolate `str(exc)` directly — that is exactly
    the `resp.text[:200]` shape CG-23 removed from two adapters after a real 403
    put a webhook's key and token into three artifacts.
    """
    if name not in TOOL_NAMES:
        return None, {"code": INVALID_PARAMS, "message": f"unknown tool: {name}"}
    try:
        message = OutboundMessage(**(arguments or {}))
    except Exception as exc:  # noqa: BLE001 — pydantic ValidationError and friends
        # ValidationError embeds the offending INPUT, which is the caller's own
        # bytes rather than a credential — but it is not a class this repo
        # authored, so it goes through the same allowlist as everything else.
        return _text_result(
            f"invalid arguments for send_message: {describe_exception(exc)}",
            True), None
    try:
        identity = registry.identity_for(app_id, message.identity)
    except RegistryError as exc:
        # Hard rule #4's refusal. RegistryError is not marked, so the message is
        # rebuilt here from the registry's own allowlist rather than printed —
        # the app's granted identities are what it is already being told in the
        # tool schema, so this discloses nothing new.
        allowed = ", ".join(registry.apps[app_id].identities) or "(none)"
        return _text_result(
            f"app {app_id!r} may not send as {message.identity!r} "
            f"(allowed: {allowed})", True), None
    adapter = adapters.get(identity.mode)
    if adapter is None:
        return _text_result(
            f"no adapter for mode {identity.mode!r} — that tier is not enabled "
            "on this deployment", True), None
    try:
        result = adapter.send(identity, message)
    except Exception as exc:  # noqa: BLE001
        return _text_result(f"delivery failed: {describe_exception(exc)}",
                            True), None
    return _text_result(json.dumps(result.model_dump(mode="json")), False), None
```

- [x] **Step 4: Run the tests**

Run: `python3 -m pytest tests/test_mcp.py -q`
Expected: PASS (23 tests).

- [x] **Step 5: Commit**

```bash
git add src/chat_gateway/mcp.py tests/test_mcp.py
git commit -m "feat(CG-80): the tool executor — and rule #2 at the most dangerous print site yet

call_tool drives the same registry.identity_for and adapter.send that
POST /v1/messages uses. Nothing below the tool call is new code.

Two taxonomies, not one. An identity refusal is a TOOL error carrying the
registry's own allowlist, because the spec is explicit that a protocol error
is invisible to the model: 'Otherwise, the LLM would not be able to see that
an error occurred and self-correct.' Only 'which tool?' is a protocol error,
because no rewording of the arguments fixes it. It is -32602, not -32601 —
that code is reserved for an unimplemented METHOD and now carries a 404.

Every exception message reaching a tool result goes through
describe_exception. An MCP tool result is a print site whose destination is a
model's context window and, from there, a transcript that leaves the
building — the same shape CG-23 removed from two adapters after a real 403
put a webhook's key and token into three artifacts. Pinned both ways: an
unmarked exception carrying a webhook URL prints its type alone, and a marked
one keeps its message.

The refusal fires even though the enum would have hidden the name: hiding is
not enforcing, because a client may call a tool it never listed."
```

---

## Task 4: The legacy era — `initialize`, `ping`, `tools/list`, `tools/call`

**Files:**
- Modify: `src/chat_gateway/mcp.py`
- Modify: `tests/test_mcp.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: `_era_of(payload) -> str` returning `"modern"` or `"legacy"`;
  `_handle_legacy(registry, adapters, app_id, payload) -> JSONResponse`.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_mcp.py`:

```python
# ---------------------------------------------------------------- group 2 ---
from chat_gateway.mcp import LEGACY_PROTOCOL_VERSION, MODERN_PROTOCOL_VERSION  # noqa: E402


def test_legacy_initialize_returns_a_version_capabilities_and_serverinfo(env):
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": LEGACY_PROTOCOL_VERSION,
                                "capabilities": {},
                                "clientInfo": {"name": "t", "version": "1"}}})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["protocolVersion"] == LEGACY_PROTOCOL_VERSION
    assert res["capabilities"] == {"tools": {}}
    assert res["serverInfo"]["name"] == "chat-gateway"


def test_legacy_initialize_with_an_unknown_version_answers_with_ours(env):
    """The spec: if the server does not support the requested version it MUST
    respond with one it does, and that SHOULD be its latest. Echoing back
    whatever was asked for is the dishonest negotiation this rule prevents."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "1900-01-01",
                                "capabilities": {}}})
    assert r.json()["result"]["protocolVersion"] == MODERN_PROTOCOL_VERSION


def test_notifications_initialized_is_202_with_an_EMPTY_body(env):
    """A notification has no id and MUST NOT get a response. 202 + empty, not
    202 + `null` — a JSON `null` body is a response."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202
    assert r.content == b""


def test_legacy_ping_returns_an_empty_result(env):
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 9, "method": "ping"})
    assert r.status_code == 200
    assert r.json()["result"] == {}


def test_legacy_tools_list_returns_the_one_tool(env):
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert [t["name"] for t in tools] == ["send_message"]


def test_legacy_tools_call_delivers(env):
    client, adapter = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "send_message",
                                "arguments": {"identity": "pm-familyworkspace",
                                              "text": "from legacy"}}})
    assert r.status_code == 200
    assert r.json()["result"]["isError"] is False
    assert adapter.sent[0][1].text == "from legacy"


def test_legacy_tools_call_with_an_unknown_tool_is_200_with_a_protocol_error(env):
    """HTTP 200, not 404. The 404 rule is for an unimplemented METHOD;
    `tools/call` IS implemented, the tool name is just wrong."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                     "params": {"name": "nope", "arguments": {}}})
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32602


def test_an_unimplemented_method_is_404_with_minus_32601(env):
    """Unusual — JSON-RPC's reflex is 200 with an error body. 2026-07-28 makes
    it a 404 specifically so a dual-era client probe can tell a modern server
    from a legacy HTTP+SSE one."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 5, "method": "resources/list"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == -32601
```

- [x] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_mcp.py -q`
Expected: FAIL — `initialize` currently returns 404 from the placeholder.

- [x] **Step 3: Implement**

Replace the placeholder `_handle` in `src/chat_gateway/mcp.py` with:

```python
def _era_of(payload: dict) -> str:
    """Which protocol era this single request belongs to.

    THE OUTERMOST SEAM IN THIS FILE, and deliberately so: if an era is ever
    dropped, that is deleting a branch rather than unpicking a design.

    Per-request rather than per-connection, which is safe because modern MCP is
    stateless by definition and legacy's era is already established by its own
    handshake. A legacy client's post-handshake `tools/list` carries no `_meta`
    and lands on the legacy branch; a modern client's carries one and does not.
    """
    params = payload.get("params")
    if isinstance(params, dict):
        meta = params.get("_meta")
        if isinstance(meta, dict) and META_PROTOCOL_VERSION in meta:
            return "modern"
    return "legacy"


def _server_info() -> dict:
    return {"name": "chat-gateway", "version": __version__}


async def _handle(registry: Registry, adapters: dict[str, Any], app_id: str,
                  payload: dict, request: Request) -> JSONResponse | Response:
    if _era_of(payload) == "modern":
        return _handle_modern(registry, adapters, app_id, payload, request)
    return _handle_legacy(registry, adapters, app_id, payload)


def _handle_legacy(registry: Registry, adapters: dict[str, Any], app_id: str,
                   payload: dict) -> JSONResponse | Response:
    """The handshake era (`2025-11-25` and earlier)."""
    rid = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}

    if method == "initialize":
        requested = params.get("protocolVersion")
        # "If the server supports the requested protocol version, it MUST
        # respond with the same version. Otherwise, the server MUST respond
        # with another protocol version it supports. This SHOULD be the latest
        # version supported by the server." Echoing back whatever was asked for
        # is the dishonest negotiation that rule exists to prevent.
        version = (requested if requested in SUPPORTED_PROTOCOL_VERSIONS
                   else SUPPORTED_PROTOCOL_VERSIONS[0])
        return JSONResponse(jsonrpc_result(rid, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": _server_info(),
            "instructions": _INSTRUCTIONS,
        }))

    if method == "notifications/initialized":
        # A notification has no id and MUST NOT get a response. 202 with an
        # EMPTY body — a JSON `null` body would be a response.
        return Response(status_code=202)

    if method == "ping":
        return JSONResponse(jsonrpc_result(rid, {}))

    if method == "tools/list":
        return JSONResponse(jsonrpc_result(
            rid, {"tools": tools_for(registry, app_id)}))

    if method == "tools/call":
        result, err = call_tool(registry, adapters, app_id,
                                params.get("name"), params.get("arguments") or {})
        if err is not None:
            # HTTP 200: `tools/call` IS implemented; only the tool name is
            # wrong. The 404 rule below is for an unimplemented METHOD.
            return JSONResponse(jsonrpc_error(rid, err["code"], err["message"]))
        return JSONResponse(jsonrpc_result(rid, result))

    # 404, not the JSON-RPC reflex of 200-with-an-error-body. `2026-07-28` makes
    # this a MUST so a dual-era client probe can tell a modern server from a
    # legacy HTTP+SSE one, and answering 200 here misclassifies us.
    return JSONResponse(
        status_code=404,
        content=jsonrpc_error(rid, METHOD_NOT_FOUND,
                              f"method not found: {method}"))
```

And add the instructions constant beside the other module constants:

```python
#: Optional natural-language guidance published on the handshake. TRANSPORT
#: ONLY — it says what this server is and how identity works, never when to use
#: it. "Use this to notify the team when a build fails" would be an occasion,
#: and an occasion is app domain (hard rule #1).
_INSTRUCTIONS = (
    "This server delivers messages to Google Chat as pre-registered "
    "identities. Your API key determines which identities you may send as; "
    "the send_message tool's schema lists exactly those and reports whether "
    "each is configured."
)
```

- [x] **Step 4: Run the tests**

Run: `python3 -m pytest tests/test_mcp.py -q`
Expected: PASS (31 tests).

- [x] **Step 5: Commit**

```bash
git add src/chat_gateway/mcp.py tests/test_mcp.py
git commit -m "feat(CG-80): the legacy protocol era, and the era discriminator

_era_of is the outermost seam in this module on purpose: if an era is ever
dropped, that is deleting a branch rather than unpicking a design. It keys on
whether params carries _meta, which is safe because modern MCP is stateless
by definition and legacy's era is established by its own handshake.

initialize negotiates honestly — an unsupported requested version gets our
latest, not an echo of whatever was asked for, which is the dishonest
negotiation that MUST exists to prevent.

notifications/initialized is 202 with an EMPTY body, not 202 with a JSON
null: a null body is a response, and a notification MUST NOT get one.

An unimplemented method is 404 + -32601, which is unusual enough to be worth
saying twice — JSON-RPC's reflex is 200 with an error body, and 2026-07-28
makes it a 404 specifically so a dual-era client probe can tell a modern
server from a legacy HTTP+SSE one. An unknown TOOL is different: 200 with
-32602, because tools/call is implemented and only the name is wrong."
```

---

## Task 5: The modern era — `server/discover`, headers, `_meta`, `ttlMs`/`cacheScope`

**Files:**
- Modify: `src/chat_gateway/mcp.py`
- Modify: `tests/test_mcp.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `decode_header_value(raw) -> str`;
  `_handle_modern(registry, adapters, app_id, payload, request) -> JSONResponse`.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_mcp.py`:

```python
# --------------------------------------------------------- groups 3, 4, 5, 6 -
import base64  # noqa: E402

from chat_gateway.mcp import CACHE_SCOPE, decode_header_value  # noqa: E402


def modern(method, params=None, version=MODERN_PROTOCOL_VERSION, rid=1):
    """A modern-era request body: _meta is REQUIRED on every request."""
    p = dict(params or {})
    p["_meta"] = {"io.modelcontextprotocol/protocolVersion": version,
                  "io.modelcontextprotocol/clientCapabilities": {}}
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": p}


def modern_headers(method, name=None, version=MODERN_PROTOCOL_VERSION):
    h = {"MCP-Protocol-Version": version, "Mcp-Method": method}
    if name is not None:
        h["Mcp-Name"] = name
    return h


def test_server_discover_carries_every_required_field(env):
    client, _ = env
    r = rpc(client, modern("server/discover"),
            headers=modern_headers("server/discover"))
    assert r.status_code == 200
    res = r.json()["result"]
    for field in ("resultType", "supportedVersions", "capabilities",
                  "ttlMs", "cacheScope"):
        assert field in res, field
    assert res["resultType"] == "complete"
    assert res["capabilities"] == {"tools": {}}
    assert MODERN_PROTOCOL_VERSION in res["supportedVersions"]
    assert res["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "chat-gateway"


def test_modern_tools_list_carries_resulttype_ttl_and_cachescope(env):
    client, _ = env
    r = rpc(client, modern("tools/list"), headers=modern_headers("tools/list"))
    res = r.json()["result"]
    assert res["resultType"] == "complete"
    assert isinstance(res["ttlMs"], int)
    assert [t["name"] for t in res["tools"]] == ["send_message"]


def test_cachescope_is_private_because_the_tool_list_varies_by_api_key(env):
    """⚠ Hard rule #4 delivered by a cache header. `public` asserts the
    response carries no user-specific data and MAY be cached ACROSS
    authorization contexts — and this tool list DOES vary by key, because
    identity's enum is that app's allowlist. `public` would let an
    intermediary serve one tenant's allowlist to another, and that is
    invisible to a review looking at the auth check."""
    client, _ = env
    assert CACHE_SCOPE == "private"
    for method in ("tools/list", "server/discover"):
        r = rpc(client, modern(method), headers=modern_headers(method))
        assert r.json()["result"]["cacheScope"] == "private", method


def test_the_same_tools_call_works_in_BOTH_eras_on_one_endpoint(env):
    """The test that proves dual-era is real rather than aspirational."""
    client, adapter = env
    legacy = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "send_message",
                                     "arguments": {"identity": "pm-familyworkspace",
                                                   "text": "legacy"}}})
    mod = rpc(client, modern("tools/call",
                             {"name": "send_message",
                              "arguments": {"identity": "pm-familyworkspace",
                                            "text": "modern"}}),
              headers=modern_headers("tools/call", "send_message"))
    assert legacy.json()["result"]["isError"] is False
    assert mod.json()["result"]["isError"] is False
    assert "resultType" not in legacy.json()["result"]
    assert mod.json()["result"]["resultType"] == "complete"
    assert [m.text for _, m in adapter.sent] == ["legacy", "modern"]


def test_a_modern_request_missing_required_meta_fields_is_400(env):
    client, _ = env
    body = modern("tools/list")
    del body["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"]
    r = rpc(client, body, headers=modern_headers("tools/list"))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32602


def test_a_legacy_request_is_NOT_held_to_the_modern_header_rules(env):
    """Era isolation in the other direction: a legacy client sends none of
    these headers and must not be 400'd for it."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 200


def test_a_missing_protocol_version_header_on_a_modern_request_is_400(env):
    client, _ = env
    r = rpc(client, modern("tools/list"), headers={"Mcp-Method": "tools/list"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32020


def test_mcp_method_header_disagreeing_with_the_body_is_400(env):
    client, _ = env
    r = rpc(client, modern("tools/list"), headers=modern_headers("tools/call"))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32020


def test_mcp_name_header_disagreeing_with_params_name_is_400(env):
    client, _ = env
    r = rpc(client, modern("tools/call",
                           {"name": "send_message",
                            "arguments": {"identity": "pm-familyworkspace",
                                          "text": "x"}}),
            headers=modern_headers("tools/call", "something_else"))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32020


def test_protocol_version_header_disagreeing_with_meta_is_400(env):
    client, _ = env
    r = rpc(client, modern("tools/list", version=MODERN_PROTOCOL_VERSION),
            headers=modern_headers("tools/list", version=LEGACY_PROTOCOL_VERSION))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32020


def test_a_base64_sentinel_header_value_is_decoded_before_comparison(env):
    client, adapter = env
    encoded = ("=?base64?" + base64.b64encode(b"send_message").decode() + "?=")
    r = rpc(client, modern("tools/call",
                           {"name": "send_message",
                            "arguments": {"identity": "pm-familyworkspace",
                                          "text": "sentinel"}}),
            headers=modern_headers("tools/call", encoded))
    assert r.status_code == 200
    assert r.json()["result"]["isError"] is False


def test_decode_header_value_passes_a_plain_value_through(env):
    assert decode_header_value("send_message") == "send_message"


def test_an_unsupported_protocol_version_is_400_with_the_supported_list(env):
    client, _ = env
    r = rpc(client, modern("tools/list", version="1900-01-01"),
            headers=modern_headers("tools/list", version="1900-01-01"))
    assert r.status_code == 400
    body = r.json()["error"]
    assert body["code"] == -32022
    assert MODERN_PROTOCOL_VERSION in body["data"]["supported"]
    assert body["data"]["requested"] == "1900-01-01"
```

- [x] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_mcp.py -q`
Expected: FAIL — `cannot import name 'decode_header_value'`.

- [x] **Step 3: Implement**

Add to `src/chat_gateway/mcp.py`, after `_handle_legacy`:

```python
def decode_header_value(raw: str) -> str:
    """Decode MCP's base64 sentinel form, `=?base64?<b64>?=`, if present.

    Clients use it for header values outside the header-safe character set.
    Our only tool name is `send_message`, which never needs it — but the CLIENT
    decides, so the decoder exists regardless. A comparison against the raw
    sentinel string would reject a perfectly conformant request.
    """
    if raw.startswith(_SENTINEL_PREFIX) and raw.endswith(_SENTINEL_SUFFIX):
        payload = raw[len(_SENTINEL_PREFIX):-len(_SENTINEL_SUFFIX)]
        try:
            return base64.b64decode(payload, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            raise _McpRequestError(
                400, HEADER_MISMATCH,
                "a base64 sentinel header value did not decode") from None
    return raw


def _require_header(request: Request, name: str, expected: Any,
                    label: str) -> None:
    """One header, cross-checked against the body it duplicates.

    The duplication is the protocol's, not ours: `Mcp-Method` and `Mcp-Name`
    exist so an intermediary can route without parsing a body. That makes a
    MISMATCH a real hazard — the router and the executor would disagree about
    what is being called — which is why the spec makes rejecting one a MUST
    rather than a preference.
    """
    raw = request.headers.get(name)
    if raw is None:
        raise _McpRequestError(400, HEADER_MISMATCH,
                               f"required header {name} is missing")
    if decode_header_value(raw) != expected:
        raise _McpRequestError(
            400, HEADER_MISMATCH,
            f"header {name} does not match the request's {label}")


def _handle_modern(registry: Registry, adapters: dict[str, Any], app_id: str,
                   payload: dict, request: Request) -> JSONResponse:
    """The stateless era (`2026-07-28`).

    Everything the legacy branch gets from a handshake, this branch gets from
    the request in front of it — which is the whole point of the revision:
    "A server processes each request independently; no state should be inferred
    from previous requests, even those on the same connection or stream."
    """
    rid = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    meta = params.get("_meta") or {}

    version = meta.get(META_PROTOCOL_VERSION)
    if META_CLIENT_CAPABILITIES not in meta:
        raise _McpRequestError(
            400, INVALID_PARAMS,
            f"_meta.{META_CLIENT_CAPABILITIES} is required on every request")
    _require_header(request, "MCP-Protocol-Version", version,
                    "_meta protocol version")
    _require_header(request, "Mcp-Method", method, "method")
    if version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise _McpRequestError(
            400, UNSUPPORTED_PROTOCOL_VERSION, "unsupported protocol version",
            {"supported": SUPPORTED_PROTOCOL_VERSIONS, "requested": version})

    if method == "server/discover":
        return JSONResponse(jsonrpc_result(rid, {
            "resultType": "complete",
            "supportedVersions": SUPPORTED_PROTOCOL_VERSIONS,
            "capabilities": {"tools": {}},
            "instructions": _INSTRUCTIONS,
            "ttlMs": TOOLS_TTL_MS,
            "cacheScope": CACHE_SCOPE,
            "_meta": {META_SERVER_INFO: _server_info()},
        }))

    if method == "tools/list":
        return JSONResponse(jsonrpc_result(rid, {
            "resultType": "complete",
            "tools": tools_for(registry, app_id),
            "ttlMs": TOOLS_TTL_MS,
            "cacheScope": CACHE_SCOPE,
            "_meta": {META_SERVER_INFO: _server_info()},
        }))

    if method == "tools/call":
        name = params.get("name")
        _require_header(request, "Mcp-Name", name, "params.name")
        result, err = call_tool(registry, adapters, app_id, name,
                                params.get("arguments") or {})
        if err is not None:
            return JSONResponse(jsonrpc_error(rid, err["code"], err["message"]))
        return JSONResponse(jsonrpc_result(rid, {"resultType": "complete",
                                                 **result}))

    raise _McpRequestError(404, METHOD_NOT_FOUND, f"method not found: {method}")
```

⚠ **One wiring detail.** `_handle_modern` raises `_McpRequestError`, which is
caught by the `except` block in `mcp_post` from Task 1 — verify that block still
wraps the `await _handle(...)` call. It does, as written.

- [x] **Step 4: Run the tests**

Run: `python3 -m pytest tests/test_mcp.py -q`
Expected: PASS (44 tests).

- [x] **Step 5: Run the whole suite**

Run: `python3 -m pytest -q`
Expected: **434 passed**. Record the real number.

- [x] **Step 6: Commit**

```bash
git add src/chat_gateway/mcp.py tests/test_mcp.py
git commit -m "feat(CG-80): the modern stateless era — headers, _meta, and cacheScope: private

2026-07-28 deleted the handshake, so everything the legacy branch gets from
initialize this branch gets from the request in front of it. server/discover
replaces it and is a MUST.

Three required headers, each cross-checked against the body it duplicates.
The duplication is the protocol's — Mcp-Method and Mcp-Name exist so an
intermediary can route without parsing a body — which is what makes a
MISMATCH a real hazard rather than a formality: the router and the executor
would disagree about what is being called. Base64 sentinel values are decoded
before comparison; our own tool name never needs that form, but the CLIENT
decides.

⚠ cacheScope is 'private', and this is a hard rule #4 control rather than a
performance knob. 'public' asserts the response carries no user-specific data
and MAY be cached ACROSS authorization contexts — and this tool list DOES
vary by API key, because identity's enum is that app's allowlist. 'public'
would let an intermediary serve one tenant's identity allowlist to another: a
rule #4 violation delivered by a cache header, invisible to a review that is
looking at the auth check.

Dual-era is pinned by a test that runs the SAME tools/call both ways against
one endpoint and asserts the legacy result has no resultType while the modern
one does — and by its mirror, that a legacy request is not held to the modern
header rules."
```

---

## Task 6: Wiring — the feature flag and the `/healthz` field

**Files:**
- Modify: `src/chat_gateway/__main__.py`
- Modify: `src/chat_gateway/service.py` — `create_app::healthz`'s `body` dict
- Modify: `tests/test_mcp.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: `/healthz` field `mcp: {"enabled": bool, "tools": list[str]}`;
  env var `GATEWAY_ENABLE_MCP`.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_mcp.py`:

```python
# ------------------------------------------------------- groups 13, 14, 15 --
def test_healthz_publishes_the_mcp_surface_when_it_is_on(env):
    """CG-59's lesson, one turn later: the deployed container is not
    necessarily running the code you think. A container answered 200 to
    `?strict=1` because FastAPI ignores an undeclared query parameter, so
    'repointing the tile before the image is rebuilt changes nothing while
    looking exactly like the fix.' This field lets an operator confirm a
    rebuild landed by READING rather than by inferring from behaviour that
    fails identically either way."""
    client, _ = env
    body = client.get("/healthz").json()
    assert body["mcp"] == {"enabled": True, "tools": ["send_message"]}


def test_the_mcp_field_is_NOT_an_input_to_status(env, monkeypatch, tmp_path):
    """Rule #5, decided explicitly per this repo's standing requirement. A
    surface being on or off is a CONFIGURATION, not a fault — the verdict
    suppressed_opt_out got, for the same stated reason: degrading on a system
    working as designed teaches an operator that 'degraded' is the normal
    reading, and an ignored warning is the failure rule #5 was written after."""
    client, _ = env
    on = client.get("/healthz").json()

    monkeypatch.setenv("SVC_KEY_AITEAM", "cgk_test_key")
    monkeypatch.setenv("SVC_KEY_JOBHUNT", "cgk_other_key")
    monkeypatch.setenv("SVC_HOOK_FW", "https://x.example/hook")
    monkeypatch.setenv("SVC_HOOK_OTHER", "https://y.example/hook")
    monkeypatch.delenv("SVC_HOOK_AGENT", raising=False)
    p = tmp_path / "r2.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    off_app = create_app(load_registry(p), Inbox(), {"webhook": FakeAdapter()})
    off = TestClient(off_app).get("/healthz").json()

    assert off["mcp"] == {"enabled": False, "tools": []}
    # Turning the surface on or off moves NOTHING else about health.
    assert on["reasons"] == off["reasons"]
    assert on["status"] == off["status"]


def test_the_endpoint_is_absent_when_the_surface_is_off(env, tmp_path,
                                                        monkeypatch):
    monkeypatch.setenv("SVC_KEY_AITEAM", "cgk_test_key")
    monkeypatch.setenv("SVC_KEY_JOBHUNT", "cgk_other_key")
    monkeypatch.setenv("SVC_HOOK_FW", "https://x.example/hook")
    monkeypatch.setenv("SVC_HOOK_OTHER", "https://y.example/hook")
    p = tmp_path / "r3.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    app = create_app(load_registry(p), Inbox(), {"webhook": FakeAdapter()})
    c = TestClient(app)
    assert c.post("/mcp", headers=AUTH,
                  json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 404


def test_mounting_the_router_does_not_disturb_the_existing_surface(env):
    """Non-regression. The MCP surface is another ingress to the send path,
    not a change to it."""
    client, adapter = env
    r = client.post("/v1/messages", headers=AUTH,
                    json={"identity": "pm-familyworkspace", "text": "still works"})
    assert r.status_code == 200
    assert r.json()["status"] == "delivered"
    assert client.get("/v1/identities", headers=AUTH).status_code == 200
    assert client.get("/healthz").status_code == 200
```

- [x] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_mcp.py -q`
Expected: FAIL — `KeyError: 'mcp'`.

- [x] **Step 3: Add the `/healthz` field**

In `src/chat_gateway/service.py`, inside `healthz`, the `body` dict currently
begins:

```python
        body = {
            "version": __version__,
            "registry": registry.health(),
```

Insert the new key between those two lines:

```python
        body = {
            "version": __version__,
            # CG-80. A CONFIG ECHO, not a counter — and the distinction is
            # decided rather than assumed, per this repo's standing requirement
            # that every /healthz field's degrade-or-not verdict is reasoned one
            # at a time.
            #
            # NOT an input to `status` and never a `reasons` entry, at any
            # value: a surface being switched off is a configuration, not a
            # fault. That is the verdict `suppressed_opt_out` got, for the same
            # reason — degrading on a system working as designed teaches an
            # operator that "degraded" is the normal reading, and an ignored
            # warning is the failure this endpoint exists because of.
            #
            # And NO counters at all. Every counter here guards a loop, a
            # thread, a queue or a disk write — something that can fail while
            # nobody is looking. `/mcp` is synchronous request/response: if it
            # breaks, the caller learns in the same round trip. There is no
            # state in which it is quietly not working while this endpoint says
            # otherwise, so a counter would publish traffic volume on an
            # UNAUTHENTICATED endpoint for no diagnostic gain — the trade CG-12
            # already rejected.
            #
            # What it IS for: CG-59 shipped `?strict=1` and the deployed
            # container went on answering 200 to it, because FastAPI ignores an
            # undeclared query parameter. An operator could not tell a rebuilt
            # image from a stale one by probing. This field says so in words.
            #
            # Disclosure: strictly LESS than this endpoint already publishes —
            # `registry.health()` two lines down carries every app id and every
            # identity name on the same unauthenticated response.
            "mcp": {"enabled": bool(getattr(app.state, "mcp_enabled", False)),
                    "tools": list(MCP_TOOL_NAMES)
                             if getattr(app.state, "mcp_enabled", False) else []},
            "registry": registry.health(),
```

Add the import at the top of `service.py`, beside the other relative imports:

```python
from .mcp import TOOL_NAMES as MCP_TOOL_NAMES
```

⚠ **Import at module scope is safe here and the `build_router` import inside
`create_app` must STAY lazy.** `mcp.py` imports from `auth`, `envelope`,
`errors` and `registry` — all core, no cycle. `service.py` importing `mcp.py` at
module scope is therefore fine, and importing only the name constant keeps
`/healthz` honest on a build where the router was never mounted.

- [x] **Step 4: Wire the env flag in `__main__.py`**

In `src/chat_gateway/__main__.py`, in the `serve` branch, change the
`create_app(...)` call to pass the flag:

```python
        app = create_app(
            registry, inbox, adapters, subscriber,
            delivery_log=log,
            dispatcher=dispatcher,
            heartbeats=HeartbeatStore(Path(state_dir) / "heartbeats.json"),
            sweeper=sweeper,
            # CG-80. Default OFF, the posture GATEWAY_ENABLE_PUBSUB set for a
            # new surface. Unlike that flag this one has NO companion
            # requirement — it needs no credential, so there is nothing to fail
            # closed on and no startup check to add.
            mcp_enabled=os.environ.get("GATEWAY_ENABLE_MCP", "0") == "1",
        )
```

And add it to the module docstring's env list, which currently reads
`CHAT_GATEWAY_STATE_DIR, GATEWAY_ENABLE_PUBSUB,`:

```
CHAT_GATEWAY_STATE_DIR, GATEWAY_ENABLE_PUBSUB, GATEWAY_ENABLE_MCP,
CHAT_GATEWAY_MCP_ALLOWED_ORIGINS,
```

- [x] **Step 5: Run the tests**

Run: `python3 -m pytest tests/test_mcp.py -q`
Expected: PASS (48 tests).

- [x] **Step 6: Run the whole suite**

Run: `python3 -m pytest -q`
Expected: **438 passed**. Record the real number.

⚠ If any existing `/healthz` test asserts an exact set of body keys, it will
fail here. Fix the test by adding `mcp`, not by removing the field — and note
which test it was in the PR body, because a body-shape assertion catching this
is that test working.

- [x] **Step 7: Commit**

```bash
git add src/chat_gateway/service.py src/chat_gateway/__main__.py tests/test_mcp.py
git commit -m "feat(CG-80): GATEWAY_ENABLE_MCP, and one honest /healthz field

Default OFF, the posture GATEWAY_ENABLE_PUBSUB set for a new surface — with
one difference recorded in the comment: this flag has no companion
requirement, because it needs no credential, so there is nothing to fail
closed on.

One field, `mcp: {enabled, tools}`, and NO counters. The verdict is reasoned
rather than reflexive, per this repo's standing requirement. Every counter
here guards a loop, a thread, a queue or a disk write — something that can
fail while nobody is looking. /mcp is synchronous: if it breaks, the caller
learns in the same round trip. A counter would publish traffic volume on an
unauthenticated endpoint for no diagnostic gain, which is the trade CG-12
already rejected.

The field is never an input to status and never adds a reasons entry, at any
value — a surface being off is a configuration, not a fault, and degrading on
a system working as designed teaches an operator that 'degraded' is the
normal reading. Pinned by a test that builds the app both ways and asserts
reasons and status are byte-identical.

What it IS for: CG-59 shipped ?strict=1 and the deployed container went on
answering 200 to it, because FastAPI ignores an undeclared query parameter —
so an operator could not tell a rebuilt image from a stale one by probing.
This field says so in words. It discloses strictly less than
registry.health() two lines below it already does."
```

---

## Task 7: Documentation, and the example agent tenant

**Files:**
- Modify: `.env.example`
- Modify: `config/registry.example.yaml`
- Modify: `README.md`
- Modify: `docs/integration-guide.md`
- Modify: `docs/deploy/nas.md` (§5 compose only)
- Modify: `CLAUDE.md`

- [x] **Step 1: `.env.example`**

Add a new block after the tier-2 block, before `GATEWAY_GCP_BILLING`:

```
# --- MCP server surface (CG-80) ---
# `POST /mcp` — a Model Context Protocol server, so an MCP-speaking agent sends
# through this gateway and inherits its identity allowlists and audit trail.
# Send-only: there is no inbound tool, and MCP has no server push at all.
# Default OFF; no credential of its own — an MCP client authenticates with an
# ordinary per-app key from the block above.
GATEWAY_ENABLE_MCP=0                         # 1 to mount POST /mcp
# Comma-separated `Origin` allowlist for DNS-rebinding protection (a protocol
# MUST). Empty means ANY present Origin is refused — the fail-closed direction,
# and correct here because no browser client exists. A non-browser MCP client
# sends no Origin at all and is unaffected.
CHAT_GATEWAY_MCP_ALLOWED_ORIGINS=
```

- [x] **Step 2: `config/registry.example.yaml` — the example agent tenant**

Add an app entry, using whatever identity the example file already defines for
FamilyWorkspace. Copy the surrounding block's comment style:

```yaml
  # An "agent" tenant: an ordinary registered app whose key lives in an MCP
  # client's config rather than in a program. It is a tenant like any other —
  # per-app key, explicit identity allowlist, hard rule #4 unchanged.
  #
  # `allow_inbound: false` and it is WRITTEN, not defaulted (CG-61's lesson).
  # There is no MCP inbound tool, so inbound would be unreachable through that
  # surface anyway; saying it explicitly means the registry states the intent
  # rather than leaving it to a loader default.
  #
  # ⚠ REGISTERING THIS FOR REAL IS AN OPERATOR ACTION, NOT A PR. The live
  # `config/registry.yaml` is gitignored and the key is a new secret, so this
  # example is a template and nothing more. Until an operator mints a key,
  # writes the entry and restarts, the MCP surface has no caller.
  agent-mcp:
    key_env: CHAT_GATEWAY_API_KEY__AGENT_MCP
    identities: [pm-familyworkspace]
    allow_inbound: false
```

✅ **DISCHARGED 2026-08-11 — the block above is left byte-for-byte as it shipped,
and its last sentence is no longer true of the live box.** An operator minted the
key (over stdin, never argv) and wrote an `agent-mcp` entry into the gitignored
`config/registry.yaml` with **one** identity, `pm-familyworkspace`; the surface has
a caller. ⚠ **This is an annotation, not an edit to the shipped file** — the
committed `config/registry.example.yaml` is being corrected separately, and this
plan records what Task 7 *shipped*, so the two must not be silently reconciled by
rewriting history here. ⚠ **The warning it carries is still correct and must stay
in the example file:** registering a tenant for real remains an operator action a
PR cannot perform. What changed is only that the action was taken —
`docs/deploy/nas.md` §10's **2026-08-11** entry is its one home.

Add the matching name-only line to `.env.example`'s per-app key block:

```
CHAT_GATEWAY_API_KEY__AGENT_MCP=
```

- [x] **Step 3: `README.md` — one API-table row**

After the `GET /v1/identities` row, add:

```markdown
| `POST /mcp` | **MCP server surface** (opt-in, `GATEWAY_ENABLE_MCP=1`): a Model Context Protocol endpoint so agents send through the gateway with the same per-app key, identity allowlist and audit trail. Send-only — one `send_message` tool, whose schema is generated from the envelope and whose `identity` enum is exactly your key's allowlist. Dual-era (`2025-11-25` + `2026-07-28`) |
```

- [x] **Step 4: `docs/integration-guide.md` — a new section**

Insert after the `## Identities + health` section:

````markdown
## MCP server surface — `POST /mcp` (opt-in)

The gateway is also a Model Context Protocol server, so an MCP-speaking agent
sends through it with the same per-app key, the same identity allowlist and the
same delivery log as any other consumer. Off unless the operator sets
`GATEWAY_ENABLE_MCP=1`.

**One tool, `send_message`.** Its `inputSchema` is generated from the same
envelope `POST /v1/messages` takes, and its `identity` property carries an
`enum` of exactly the identities your key is allowed to use — so an agent
cannot form a call naming someone else's identity. That is defence in depth:
the same `identity_for` check still runs at call time.

Claude Code, project scope (`.mcp.json`) — keep the key in the environment,
not in the file:

```json
{
  "mcpServers": {
    "chat-gateway": {
      "type": "http",
      "url": "http://<gateway-host>:8085/mcp",
      "headers": {"Authorization": "Bearer ${CHAT_GATEWAY_API_KEY}"}
    }
  }
}
```

Or by hand:

```bash
curl -s $GW/mcp -H "$AUTH" -H "$JSON" -d '{
  "jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### What it does NOT do, and why

**There is no inbound tool, and there will not be one that works the way you
would want.** MCP gives a server no way to push: a server cannot send a request,
cannot send an unsolicited notification, and cannot cause a model turn. An
inbound MCP tool could only ever be polling that an agent remembers to do. If
you need to react to a human's reply, use the per-tenant `callback_url` push or
`GET /v1/inbox` — both are better at it, and both are covered above.

**It is send-only in another sense too:** no `notify`, no `heartbeat`, no
delivery-log tool. `POST /v1/messages` is synchronous, so an agent gets an
answer it can act on; `POST /v1/notify` returns `202 enqueued`, which it cannot.
Dead-man checks are deliberately absent — a check registered by an agent session
goes missed the moment that session ends, and then pages a human daily.

### Protocol notes

Streamable HTTP on a single endpoint, stateless, tools-only, JSON only —
`GET /mcp` and `DELETE /mcp` are `405`, because there is no stream and no
session. **Dual-era**: both the `2025-11-25` handshake protocol and the
`2026-07-28` stateless one are served on the same URL, because a client
speaking one cannot talk to a server speaking only the other. Authentication is
a static per-app bearer key, not OAuth; a `401` carries a bare
`WWW-Authenticate: Bearer` with no `resource_metadata` pointer, because there is
no authorization server to discover.
````

- [x] **Step 5: `docs/deploy/nas.md` §5 — the compose `environment:` block**

Add one key to the compose document in §5, and one line of prose beneath it:

```
    "GATEWAY_ENABLE_MCP": "1",
```

Prose to add under the existing `GATEWAY_ENABLE_PUBSUB` note:

> `GATEWAY_ENABLE_MCP` sits in the compose for the same reason its sibling does:
> it is **non-secret and captured**, so a stale `.env` cannot leave the surface
> silently in the wrong state. It differs in one way worth naming — it has **no
> companion credential**, so there is nothing for it to fail closed on, and
> adding it changes **nothing** about the secret set: no new `.env` key, no new
> stdin transport, and **no new `SECRETS.template.md` row** (§6's three-row set
> is unchanged).

- [x] **Step 6: `CLAUDE.md` — one bullet, pointing rather than restating**

Add to the status section, after the `__cg_action__` bullet:

```markdown
- **The gateway is an MCP server too, since CG-80 — send-only, and that is a
  decision rather than a stage.** `POST /mcp` is another ingress to the path
  `POST /v1/messages` already uses: same `authenticate()`, same
  `registry.identity_for`, same adapter. **Hard rule #1 holds mechanically, not
  by taste** — the one tool's `inputSchema` is GENERATED from
  `OutboundMessage.model_json_schema()` and a test compares it for equality, so
  a hand-edited property turns the suite red. `cards` stays an opaque array; a
  card-builder tool is the thing rule #1 exists to refuse.
  **There is no inbound tool and the reason is protocol-level, not a backlog
  item:** MCP servers cannot send requests, cannot send unsolicited
  notifications and cannot cause a model turn, so an inbound tool could only be
  polling. It is also blocked on `Inbox.poll` draining — until CG-56, an MCP
  reader and a tenant's poller are competing DESTRUCTIVE consumers of one queue.
  **Do not restate the rule #6 argument here; it is argued both ways in
  `docs/superpowers/specs/2026-08-06-mcp-server-surface-design.md` §7**, and
  `read_inbox` is filed as CG-81 needing the user's explicit sign-off.
  ⚠ **Dual-era, and that is load-bearing rather than belt-and-braces.** Revision
  `2026-07-28` deleted `initialize`, `ping` and sessions; a modern client cannot
  talk to a legacy server and a legacy client cannot talk to a modern one, so
  serving one era would make this endpoint **silently unreachable** to the other.
  ⚠ **`CACHE_SCOPE` is `"private"` and it is a hard rule #4 control, not a
  performance knob** — the tool list varies by API key, so `"public"` would let
  an intermediary serve one tenant's identity allowlist to another. Reasoning
  has one home, that constant's own comment.
  **No ⚠ verification-ledger flag moved.** This sits above `adapters/` and makes
  no Google call of its own; a live round-trip through the tool is the same
  bytes from a different caller and clears nothing.
```

- [x] **Step 7: Verify no secret value landed anywhere**

Run:

```bash
git diff main -- .env.example config/registry.example.yaml docs/ README.md CLAUDE.md \
  | grep -nE 'cgk_|https://chat\.googleapis|token=|key=|private_key|BEGIN [A-Z ]*PRIVATE'
```

Expected: **no output.** Every added line names an env var, never a value.

- [x] **Step 8: Run the whole suite and commit**

Run: `python3 -m pytest -q` — expected unchanged from Task 6.

```bash
git add .env.example config/registry.example.yaml README.md docs/ CLAUDE.md
git commit -m "docs(CG-80): the MCP surface, and what it deliberately cannot do

The integration guide gets a section that leads with the limitation rather
than burying it: there is no inbound tool and there will not be one that
works the way a reader would want, because MCP gives a server no way to push.
An inbound MCP tool could only ever be polling an agent remembers to do —
callback_url and GET /v1/inbox are both better at it.

registry.example.yaml gains an `agent-mcp` tenant with allow_inbound WRITTEN
rather than defaulted (CG-61's lesson), and a warning that registering it for
real is an OPERATOR action: the live registry is gitignored and the key is a
new secret, so until someone mints and writes it the surface has no caller.

nas.md §5 gains GATEWAY_ENABLE_MCP in the compose, with the one way it
differs from its sibling stated: no companion credential, so nothing to fail
closed on, and NO new SECRETS.template.md row — §6's three-row set is
unchanged.

CLAUDE.md's bullet points rather than restates: the rule #6 argument has one
home in the spec, and CACHE_SCOPE's reasoning has one home in its own
comment."
```

⚠ **The commit message above is a historical artifact and is NOT edited — but one
of its sentences stopped being true on 2026-08-11.** *"until someone mints and
writes it the surface has no caller"* described the world for five days; an
operator has since minted the key and written the entry (Step 2's annotation
above), so `agent-mcp` is a live tenant on the box with a single identity,
`pm-familyworkspace`. A commit message cannot be corrected in place, which is
exactly why the correction is recorded beside it rather than by rewording the
quote — and why the shipped `.env.example` / `registry.example.yaml` copies of
that sentence are being amended in the files themselves.

---

## Task 8: UAT against a real MCP client, and the deploy handoff

**No code.** This task is the row's exit condition and cannot be faked into an
offline test.

⚠ **STATUS 2026-08-11 — this task stood entirely unticked while every other task
in the plan read `[x]`, and that was ACCURATE at the merge**, not an oversight:
CG-80 shipped its code on 2026-08-10 (PR #72) and **deliberately stopped short of
the box**. The boxes below are now resolved one at a time against what was actually
done, on the box, on 2026-08-11. **Nothing here is ticked from inference**, one
step is ticked with its scope narrowed in the annotation, and the sub-item that was
*not* performed — `?strict=1` returning **503** — is called out rather than swept
into a neighbouring tick. Every measurement has one home and it is not this file:
`docs/deploy/nas.md` §10's **2026-08-11** entry.

- [x] **Step 1: Full suite, clean**

Run: `python3 -m pytest -q`. Record the number. It is the number that goes in the
PR body — **measured, not copied from this plan.**

  ✅ **Discharged by PR #72, merged 2026-08-10** — the row shipped, so the suite ran.
  The number belongs to that PR body and is deliberately **not** transcribed here:
  the step's own instruction (*measured, not copied from this plan*) is the same
  rule read in the other direction, and a suite count with two homes is the exact
  failure `CLAUDE.md` keeps as its standing example.

- [x] **Step 2: Prove no ledger flag moved (global constraint 3)**

```bash
git diff main -- src/ | grep -c "LIVE-UNVERIFIED\|SHAPE-VERIFIED"
```

Expected: **0**. If it is not 0, stop — that is a hard-rule-#3 question for the
user, not something to resolve in this PR.

  ✅ **Held at the merge, 2026-08-10 — and held again on 2026-08-11, which is the
  harder test.** The grep guards the *code*; what happened on the box a day later
  is the thing it could not guard: a real message **delivered** through the tool,
  which looks like fresh Google evidence and is not. No flag was cleared, added,
  re-priced or reworded then either. **The step is a floor, not the guarantee** —
  the guarantee is the reasoning in spec §11, written before the round trip.

- [x] **Step 3: Run the gateway locally and connect a real MCP client**

```bash
GATEWAY_ENABLE_MCP=1 python3 -m chat_gateway serve
```

Then, from a Claude Code session, add the server and confirm all four:

```bash
claude mcp add --transport http chat-gateway http://localhost:8085/mcp \
  --header "Authorization: Bearer $CHAT_GATEWAY_API_KEY"
```

Record, as evidence in the PR body:

| # | Check | Evidence to capture |
|---|---|---|
| 1 | The client completes a handshake | which era it negotiated — `initialize` or `server/discover`. ⚠ **This is the single most valuable thing this task produces**, because it is the only measurement that tells us whether the legacy branch, the modern branch, or both are actually load-bearing |
| 2 | `send_message` appears in the client's tool list | the tool name and title as the client renders them |
| 3 | The `identity` enum shows **only** your key's identities | the rendered enum |
| 4 | A message actually arrives in Google Chat | the space it landed in, and the `/v1/deliveries` row |

✅ **ANSWERED 2026-08-11 — and the answer to row 1 is BOTH, asymmetrically.** This
is the most important line in the task and it is no longer an open question. Driven
live over real HTTP against the **deployed** box:

- **Legacy `2025-11-25`** negotiated from a **bare `initialize`** and nothing else;
  `ping` **200**; `tools/list` → `['send_message']` with the `identity` enum
  narrowed to `['pm-familyworkspace']` — **per-app narrowing works on the wire**,
  not only in tests (rows 2 and 3, on the wire rather than as a client renders
  them).
- **Modern `2026-07-28`** will not move without **all five** of: `params._meta`
  carrying both `io.modelcontextprotocol/protocolVersion` and
  `io.modelcontextprotocol/clientCapabilities`, plus the headers
  `MCP-Protocol-Version`, `Mcp-Method` (cross-checked against the body's method)
  and `Mcp-Name` (against `params.name`, `tools/call` only). **Each omission
  produced a distinct, specific 400.** `server/discover` → **200**, result keys
  `_meta, cacheScope, capabilities, instructions, resultType, supportedVersions,
  ttlMs`, with **`cacheScope: 'private'` confirmed on the wire** —
  `resultType: 'complete'`, `ttlMs: 300000`.
- **Row 4: a real message was DELIVERED** through `tools/call` over the **modern**
  era — `{"status": "delivered", "channel": "google_chat", "identity":
  "pm-familyworkspace", "mode": "webhook", "thread_key": null}` — and the
  `GET /v1/deliveries` audit row is present: **1 row**, `source: agent-mcp`,
  `kind: message`, `status: delivered`, title truncated to 80 chars.

⚠ **What this buys, stated as the plan asked rather than as a verdict: D4a's
dual-era decision is vindicated by MEASUREMENT, not by argument.** A server that
had picked one era would have been **silently unreachable** to the other's clients
— reachable-with-nothing on one side, refusing-without-five-pieces on the other.
**Stop carrying "which era is load-bearing" as an open question.**

⚠ **Scope of the tick, because the step's heading promises something slightly
different from what was done.** The gateway was exercised **on the deployed NAS
box, over direct HTTP**, not on `localhost:8085`. So rows 1, 3 and 4 are answered
**on the wire**; the *rendering* half of rows 2 and 3 — how a packaged MCP client
**displays** the tool and its enum — is **not** established by this, and spec
§12.2 bullet 2's distinction (*a `TestClient` cannot prove a client accepts it*)
survives in that narrower form.

⚠ **A client WAS registered, and that is a third thing again — do not collapse it
into either of the two above.** `claude mcp add --scope local --transport http
chat-gateway <url>/mcp --header "Authorization: Bearer <key>"` was run on
2026-08-11 and wrote the server into `~/.claude.json` for this project. **That is
a configuration written, not a handshake observed:** no client session's rendered
tool list or rendered enum was captured, so it discharges the *setup* half of this
step's heading and none of its evidence table. Recorded because *"a client is
configured"* and *"a client connected"* are exactly the two facts this step exists
to keep apart.

⚠ **`--scope local` was deliberate and is the reason no credential shipped.**
Project scope writes `.mcp.json` **into the repository**, and `claude mcp add`
stores the `--header` value **verbatim** — so the same command at project scope
would have put a live key on a branch. Verified afterwards that no `.mcp.json`
exists in the repo. **The correct wiring, and this hazard, now have a consumer-
facing home in `docs/integration-guide.md`** — a step in a plan is read once by
one Builder, and this is a mistake every future tenant can make.

⚠ **This is NOT a verification-ledger event.** It sends through
`webhook.send` / `chat_api.send`, both of which cleared their flags in July
2026. The same bytes from a different caller is not new evidence about Google,
and claiming a clear here would be the same category error as claiming one from
an offline replay. **Move no flag.**

✅ **Obeyed on the day, 2026-08-11: no flag moved.** ⚠ **The reason that decline is
worth anything is that this paragraph was written on 2026-08-06, five days BEFORE
the `delivered` it refuses to bank** — a refusal composed after the fact reads
identically and proves nothing.

- [x] **Step 4: Try one thing that should fail, and confirm the model can read it**

Ask the agent to send as an identity its key does **not** grant. Confirm the
refusal comes back as tool text the model can act on — naming what it *may* use —
rather than as a protocol error it cannot see. That round trip is the entire
justification for spec §6.5's split; if it does not behave that way, the split is
wrong and the row is not done.

  ✅ **Done live 2026-08-11, in production, against the real registry.** A
  `tools/call` naming `aitrader-alerts` came back `isError: true` with the text
  *"app 'agent-mcp' may not send as 'aitrader-alerts' (allowed:
  pm-familyworkspace)"* — the registry's own message, naming what the caller **may**
  use, as tool text rather than a protocol error. **Hard rule #4 enforced on the
  wire**, and §6.5's split behaves exactly as the step demanded. ✅ **And the
  refusal created NO `/v1/deliveries` row**, which is correct — an attempt that
  never reached an adapter is not a delivery — and it is the first production
  evidence for CG-80's build-time `DeliveryLog` fix, whose absence would have made
  every MCP send invisible in the audit trail.

- [x] **Step 5: Open the PR**

Branch `feat/cg-80-mcp-server-surface` → `main`. The body must carry:

- the measured suite number at both ends;
- the Step 2 grep result, and the sentence **"No ⚠ verification-ledger flag was
  cleared, added or reworded"**;
- Step 3's era finding, stated plainly;
- a **Docs Impact** section listing every file Task 7 touched;
- ⚠ **the two open handoffs below, which the PR does NOT close.**

  ✅ **PR #72, merged 2026-08-10.** ⚠ **The third bullet could not be honoured as
  written and that is worth saying rather than glossing:** the PR shipped a day
  before the box was reachable, so *"Step 3's era finding"* did not exist when the
  body was composed. It exists now (Step 3 above), and it did **not** come from the
  PR. ⚠ **Both handoffs the last bullet required the body to carry have since been
  discharged — see Step 6** — which does not retroactively make the merge close
  them; it means someone else closed them four and five days later, on a box.

- [x] **Step 6: Record the two handoffs the merge does not discharge**

Neither is work this PR can do. Both belong in the queue row's exit notes.

  ✅ **Recorded at the merge, and BOTH DISCHARGED 2026-08-11** — see the per-handoff
  annotations below. ⚠ **The step itself was right and stays ticked on its own
  terms:** its job was to make sure a merged row did not read as a finished one,
  and for five days that is exactly what it did.

1. ⚠ **The surface has no caller until an operator acts.** `config/registry.yaml`
   is gitignored, so the `agent-mcp` tenant exists only in the example file. An
   operator must mint a key, add the app entry, add
   `CHAT_GATEWAY_API_KEY__AGENT_MCP` to the box `.env`, and restart. **CG-61's
   lesson exactly: merged and in effect are two different facts here.**

   ✅ **DISCHARGED 2026-08-11 — the operator did precisely this.** A key was minted
   **over stdin, never argv** (hard rule #2), an `agent-mcp` entry was written into
   the gitignored `config/registry.yaml` with **one** identity,
   `pm-familyworkspace`, and `GATEWAY_ENABLE_MCP` was set via `app.update`;
   `/healthz` now reports `mcp: {"enabled": true, "tools": ["send_message"]}`.
   *(Job ids and the commit range are not repeated here — one home,
   `docs/deploy/nas.md` §10's 2026-08-11 entry.)* ⚠ **Kept in full rather than struck, because it was right
   for five days and nothing about the discharge came from this repo** — that was
   its whole claim. ⚠ **One thing it did NOT say, and the day supplied it:** which
   identities get granted is itself a decision with consequences (spec §14's D7
   note) — `aitrader-alerts` and `aitrader-reports` were deliberately **not**
   granted, which the live rule-#4 refusal in Step 4 then demonstrated.

2. ⚠ **The redeploy that carries this to the NAS also carries CG-59's
   `?strict=1`, and the ORDER is set by `docs/deploy/nas.md` §9 hazard 1.**
   The running container predates `?strict=1` and answers **200** to it, because
   FastAPI ignores an undeclared query parameter — *"repointing the tile before
   the image is rebuilt changes nothing while looking exactly like the fix."*
   So: rebuild and `app.redeploy` → verify `?strict=1` returns **503** on a
   degraded boot → **only then** repoint the Homepage tile (a homelab change).
   Two things to note in the row while doing it: this is the **first real
   exercise of `app.redeploy`**, which nas.md §10 deviation 6 records as
   documented-but-untested; and ⚠ **CAPTURE `docker inspect`'s `StartedAt` and
   `RestartCount` BEFORE the rebuild** — CG-82 task 1.

   ⚠ **CORRECTED 2026-08-10, and this clause is why the correction matters.** It
   read: *"the rebuild must not happen until **CG-59's soak has finished**, because
   the container's uninterrupted uptime is the evidence that soak is accruing."*
   **That is an instruction which can never be satisfied** — the soak stopped on
   `2026-08-06T21:02:42Z` and will not finish (CG-82). A Builder following this
   plan literally, as a Builder should, would have waited forever or quietly
   decided the instruction was stale — and this repo has a commit named for exactly
   that failure (`613e372`, *"a plan telling its executor to claim what the deploy
   disproved"*). ⚠ **Do not read the correction as "the constraint is gone":** the
   *uptime* is real, is ~5 days, is longer than the soak ever asked for, and the
   rebuild spends it. What died was the **sampling**. Capture first, then rebuild.

   ⛔ **THE CORRECTION ABOVE IS ITSELF FALSIFIED — 2026-08-11 — and its final four
   words are now an instruction nobody can follow.** There was no uptime left to
   capture. `dockerd` on the NAS was SIGKILLed on **2026-08-10**, cause
   unexplained, and the container did not survive it. The last moment the streak
   was ever **observed** alive is the NAS soak stream's final sample,
   **`2026-08-06T22:29:53Z`** — roughly **25 h witnessed**, with nothing watching
   the four days between that sample and the outage. **The "~5 days" repeated
   above was arithmetic on a start timestamp, never an observation**, which is how
   it survived being corrected once already. **`CG-82 task 1` is therefore MOOT: it
   cannot be discharged.** ⚠ **LOST, not SPENT — and that distinction is the entire
   reason the task existed.** Spent would have bought a deploy, which is the bargain
   this handoff was written to price; lost bought nothing. ⚠ **Do not resurrect
   "capture first" from this paragraph** — there is nothing to capture, and the
   redeploy has since happened. New baselines and the outage timeline have one home:
   `docs/deploy/nas.md` §10's **2026-08-11** entry.

   ✅ **AND THE HANDOFF ITSELF IS DISCHARGED 2026-08-11, in the order it
   prescribed.** `docker build`, then `sudo midclt call app.redeploy
   chat-gateway`, succeeded — **the first real exercise of `app.redeploy`**, which
   nas.md §10 deviation 6 had recorded as documented-but-untested: **it works.**
   *(Job ids, image digest and commit range: `docs/deploy/nas.md` §10's
   2026-08-11 entry, their one home.)* CG-59's `?strict=1` rode the same
   redeploy and is live: before, `?strict=1` → **200** with no `mcp` field; after,
   `?strict=banana` → **422** and `?strict=1` → **200** while healthy. ⚠ **The 422
   is a tool nobody planned for** — the old handler did not declare `strict` so it
   answered 200 to any value; the new one declares it a bool, so a
   deliberately-invalid value identifies the live image in **one request, without
   degrading production**. ⛔ **What was NOT done, stated plainly rather than folded
   into the tick: `?strict=1` returning 503 has still never been seen on the box.**
   A genuine transient degraded window did occur after the restart and cleared
   before a `?strict=1` sample could be taken, so this handoff's middle step —
   *verify 503 on a degraded boot* — is **undischarged**, and the 503 path is proven
   only in CG-59's driven local test. The tile step went ahead regardless.

---

## Self-review

**Spec coverage.** Every section of the design maps to a task:

| Spec | Task |
|---|---|
| §3 rule #1, derived schema, `cards` corollary, description rule | 2 |
| §4 D2 mounted route | 1, 6 |
| §5 rule #4 auth, `enum`, rule #2 no new secret | 1, 2, 7 |
| §6.2 dual-era method sets, no SSE, no sessions, no batching | 1, 4, 5 |
| §6.3 rows 1–7 (Origin, headers, 404, 400s, `ttlMs`/`cacheScope`, `resultType`, `Accept`) | 1, 5 |
| §6.4 annotations | 2 |
| §6.5 error mapping, `describe_exception` | 3, 4, 5 |
| §6.6 token passthrough | structural — asserted in Task 3's comment; no code needed, because no caller credential ever reaches an adapter |
| §7 no inbound tool | global constraint 6; enforced by absence, and by `TOOL_NAMES` being a one-element tuple that Task 3 checks membership against |
| §8 one tool | 2 |
| §9 D4a dual-era / D4 hand-rolled | 4, 5 |
| §10 `/healthz` | 6 |
| §11 ledger | global constraint 3; Task 8 Step 2 |
| §13 test groups 1–15 | 1 (1, 7, Origin), 2 (9, 10), 3 (11, 12), 4 (2), 5 (3, 4, 5, 6), 6 (13, 14, 15) |
| §14 D5 flag, D6 healthz, D8 onboarding | 6, 7, 8 |
| §15 scope exclusions | global constraints 1, 5, 6, 8 |

**Placeholder scan.** No `TBD`, no "add appropriate error handling", no "similar
to Task N". One deliberate marker: Task 1 Step 1 shows a broken ternary and then
gives the working replacement immediately below with an explicit instruction to
delete it — that is a warning about a real pytest gotcha (`headers` cannot be
passed twice), not a placeholder.

**Type consistency.** `send_message_schema(registry, app_id) -> dict`,
`tools_for(registry, app_id) -> list[dict]`,
`call_tool(registry, adapters, app_id, name, arguments) -> tuple[dict|None, dict|None]`,
`decode_header_value(raw) -> str`, `_era_of(payload) -> str`,
`jsonrpc_result(rid, result)`, `jsonrpc_error(rid, code, message, data=None)` —
each used in later tasks exactly as defined. `TOOL_NAMES` is a tuple in `mcp.py`
and `list(...)`-ed at the `/healthz` boundary because JSON has no tuple.
`mcp_enabled` is the keyword in `create_app`, in `__main__.py`, and in every
test fixture.

**One gap found and closed during review:** Task 2's tests need
`client.app.state.registry`, which `create_app` did not set. Task 2 Step 3 now
adds `app.state.registry = registry` beside the other `app.state` assignments.
