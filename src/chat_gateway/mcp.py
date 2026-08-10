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
