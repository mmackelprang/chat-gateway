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
design. ⚠ Read `_era_of`'s own docstring before touching it: MISCLASSIFYING A
MODERN CLIENT AS LEGACY reproduces the silent unreachability inside the module
that exists to prevent it, and CG-80's pre-merge review measured three ways it
did exactly that.

WHERE THE WORK RUNS. `POST /mcp` reads its body on the event loop and then
hands the whole of the rest to `run_in_threadpool` — `_serve` and everything
under it are PLAIN SYNC. That is a hard rule #5 control, not a style choice,
and `mcp_post`'s docstring is its one home.

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
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from . import __version__
from .auth import AuthError, authenticate
from .delivery import DeliveryLog
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


def _short(value: Any, limit: int = 60) -> str:
    """One caller-supplied scalar, rendered into an error message and BOUNDED.

    Not a hard rule #2 control — a `method` name is the caller's own bytes
    coming straight back to the caller, never a credential this gateway holds,
    so `describe_exception` is the wrong instrument here (it is for exceptions,
    and this is not one). It is a bound: a 4KB `method` string echoed verbatim
    into a response body turns a small request into a large one for no reason.
    CG-80 pre-merge review, L2.
    """
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "…(truncated)"


def _validate_envelope(payload: dict) -> None:
    """The JSON-RPC frame itself, checked ONCE for every method and every era.

    ⚠ CENTRAL ON PURPOSE (CG-80 pre-merge review, H1/L1/L2). Each of these three
    used to be either unchecked or checked per-branch, and the per-branch shape
    is what produced the measured inconsistency: `{"method": "tools/call",
    "params": "notadict"}` reached `params.get(...)` and 500'd with a traceback,
    while the same body on `tools/list` answered 200 because that branch never
    reads `params`. A malformed frame must get the same loud answer whatever
    method it names, and the only way to keep that true is to answer before any
    method branch exists.

    ⚠ `params: null` is treated as ABSENT rather than refused, and that is a
    deliberate narrowing of "present and not an object". JSON-RPC's `params`
    "MAY be omitted", and a null is how a great many serializers omit it; a
    string, a number or an array is a genuinely malformed frame. Refusing null
    would make this gateway unreachable to conformant-enough clients for no
    safety gain — the silent-unreachability failure this whole module exists to
    avoid, delivered loudly instead of silently.
    """
    if payload.get("jsonrpc") != "2.0":
        # L1. Unvalidated until CG-80's pre-merge review: a body with no
        # `jsonrpc` at all, and one claiming `"1.0"`, both answered 200. This
        # module's entire subject is conformance, so accepting a frame that
        # names a protocol we do not speak is the one thing it must not do.
        raise _McpRequestError(
            400, INVALID_REQUEST,
            'jsonrpc must be "2.0"; got '
            + _short(payload.get("jsonrpc")))
    method = payload.get("method")
    if not isinstance(method, str):
        # L2. This was reaching the unimplemented-method branch and answering
        # -32601 "method not found: None" — but a missing member is a malformed
        # REQUEST, not a request for a method that happens not to exist, and a
        # client told -32601 goes looking for a method name it never sent.
        raise _McpRequestError(400, INVALID_REQUEST,
                               "method must be a string; got " + _short(method))
    if "params" in payload and payload["params"] is not None \
            and not isinstance(payload["params"], dict):
        raise _McpRequestError(
            400, INVALID_PARAMS,
            "params must be an object; got " + _short(payload["params"]))


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


def _text_result(text: str, is_error: bool) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _validation_detail(exc: ValidationError) -> str:
    """Field-level argument errors, rendered for a model to SELF-CORRECT with.

    ⚠ THE ONE NARROW EXCEPTION TO "EVERY EXCEPTION GOES THROUGH
    `describe_exception`", and its narrowness is the whole of its safety (CG-80
    pre-merge review, M5). It applies to `pydantic.ValidationError` and to
    nothing else. It is not a second allowlist, it does not touch
    `errors.py`, and it is deliberately NOT reachable from the adapter path
    below — that is where the real credential hazard lives (CG-23's measured
    403 put a webhook's `key` and `token` into three artifacts), and it keeps
    `describe_exception` exactly as it was.

    WHY IT EARNS THE EXCEPTION. Spec §6.5 quotes the protocol at length on this
    one point — *"Otherwise, the LLM would not be able to see that an error
    occurred and self-correct"* — and `call_tool`'s docstring repeats it. But
    `describe_exception` prints an unmarked class by TYPE ALONE, so every bad
    argument shape, from a missing `text` to a malformed card, collapsed to the
    single string `invalid arguments for send_message: ValidationError`. That
    carries strictly less than "something was wrong": a model cannot tell which
    field to fix, and the self-correction the whole error taxonomy is built
    around cannot happen.

    WHY IT IS SAFE. Exactly three members are emitted, and none of them is the
    caller's data:

    * `type` — pydantic's own error-kind literal (`missing`, `string_too_short`);
    * `loc`  — OUR field names, from `OutboundMessage`;
    * `msg`  — pydantic's rendering of `type`, or, for a `value_error`, the text
      of a validator authored in `envelope.py`.

    `include_input=False` is what keeps the offending VALUE out — that member is
    the hard-rule-#2 hazard `errors.py`'s docstring names in its first paragraph
    — and `include_url=False` drops the docs link, which is noise in a context
    window.
    """
    parts = []
    for err in exc.errors(include_input=False, include_url=False):
        loc = ".".join(str(p) for p in err.get("loc", ())) or "(root)"
        parts.append(f"{loc}: {err.get('msg')} [{err.get('type')}]")
    return f"ValidationError: {'; '.join(parts)}"


def call_tool(registry: Registry, adapters: dict[str, Any], app_id: str,
              name: str, arguments: dict,
              delivery_log: DeliveryLog | None = None,
              ) -> tuple[dict | None, dict | None]:
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

    `delivery_log` is a KEYWORD ARGUMENT WITH A DEFAULT, and the default is what
    keeps every caller that does not have one — the unit tests that drive this
    function directly — working unchanged. When a router passes one, this path
    writes the same two rows `POST /v1/messages` writes; see the `record` call
    sites below for why that is not optional. ⚠ Both real call sites pass it BY
    KEYWORD, and that is the drift CG-80's pre-merge review closed (L5): they
    passed it positionally while this paragraph called it a keyword argument,
    which is exactly the comment/code disagreement this repo treats as a defect.
    """
    if name not in TOOL_NAMES:
        return None, {"code": INVALID_PARAMS,
                      "message": "unknown tool: " + _short(name)}
    try:
        message = OutboundMessage(**(arguments or {}))
    except ValidationError as exc:
        # ⚠ THE ONE NARROW EXCEPTION to "every exception reaching this text goes
        # through `describe_exception`" — for this class only, and for the
        # self-correction reason `_validation_detail` states in full. The
        # offending INPUT is what makes a ValidationError dangerous and
        # `include_input=False` is what removes it; nothing else about hard rule
        # #2 moves, and the adapter path below is untouched.
        return _text_result(
            f"invalid arguments for send_message: {_validation_detail(exc)}",
            True), None
    except Exception as exc:  # noqa: BLE001 — e.g. a non-mapping `arguments`
        # Everything that is NOT a ValidationError still gets the type name and
        # nothing else. The allowlist is unchanged and this is its default.
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
        # THIS PAIR OF `record` CALLS IS WHAT MAKES THE SPEC'S §2 TABLE TRUE.
        # That table lists exactly two properties `send_message` inherits from
        # `POST /v1/messages` — the rule #4 identity allowlist, and the audit /
        # delivery log — and the second one is not inherited by being on the
        # same code path, because `call_tool` is a second ingress rather than a
        # call into the route. Without these two lines an MCP send is invisible
        # in `GET /v1/deliveries` and in the on-disk audit trail: the row this
        # gateway's own UAT asks for as proof a message arrived would not exist.
        #
        # ⚠ `describe_exception`, NOT the `str(exc)[:200]` its `/v1/messages`
        # sibling uses. That sibling predates CG-29's allowlist and is
        # deliberately left alone here (out of scope), but this is a NEW write
        # site, and what it writes is persisted to disk AND served back over
        # `GET /v1/deliveries` — so hard rule #2 applies to it exactly as it
        # applies to the tool result three lines down. One allowlist, both
        # destinations.
        if delivery_log is not None:
            delivery_log.record(app_id, "message", message.text[:80], "failed",
                                describe_exception(exc))
        return _text_result(f"delivery failed: {describe_exception(exc)}",
                            True), None
    if delivery_log is not None:
        delivery_log.record(app_id, "message", message.text[:80], "delivered")
    return _text_result(json.dumps(result.model_dump(mode="json")), False), None


def build_router(registry: Registry, adapters: dict[str, Any],
                 delivery_log: DeliveryLog | None = None) -> APIRouter:
    router = APIRouter()

    @router.post("/mcp")
    async def mcp_post(request: Request,
                       authorization: str | None = Header(default=None),
                       origin: str | None = Header(default=None)):
        """Read the body on the loop, then leave the loop.

        ⚠ THE `run_in_threadpool` HOP IS NOT STYLE — IT IS HARD RULE #5 (CG-80
        pre-merge review, H2). Everything below this line can block: the send
        path ends in `adapter.send`, a SYNCHRONOUS `httpx.Client` with a 30s
        timeout, and `DeliveryLog.record` writes a file. Run those on the
        asyncio loop thread and a single hung webhook stalls EVERY concurrent
        request in the process — including `/healthz`, whose entire reason to
        exist is answering honestly while something else is broken. An honest
        health endpoint that cannot be reached is worth exactly as much as the
        hardcoded OK rule #5 was written after.

        `POST /v1/messages` gets this for free by being declared `def`, so
        Starlette hands it to the threadpool itself. This route cannot: it needs
        `await request.body()`. So it awaits the ONE thing that requires a loop
        and dispatches the rest explicitly — which makes the asymmetry between
        the two routes' declarations deliberate rather than an accident a reader
        is invited to "tidy up".

        `_handle`, `_handle_legacy` and `_handle_modern` are therefore PLAIN
        SYNC functions and must stay that way. `request` may be passed into
        them — headers are available synchronously — but nothing down there may
        `await`.
        """
        body = await request.body()
        return await run_in_threadpool(_serve, body, request, authorization,
                                       origin)

    def _serve(body: bytes, request: Request, authorization: str | None,
               origin: str | None) -> JSONResponse | Response:
        # ⚠ `rid` starts as None and is bound only once the body has parsed as a
        # JSON-RPC object (CG-80 pre-merge review, M1). Everything raised BEFORE
        # that point genuinely has no knowable id — the Origin 403, the parse
        # error, the batch array and the scalar body — and JSON-RPC permits a
        # null id in exactly that case. Everything raised AFTER it does have one,
        # and answering `id: null` there is a real defect: a client running
        # concurrent requests correlates by id and cannot match the response.
        # "Always echo the id" would be the wrong generalisation; this is why the
        # binding sits where it sits rather than at the top.
        rid: Any = None
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
                payload = json.loads(body)
            except (ValueError, UnicodeDecodeError, RecursionError):
                # ⚠ `RecursionError` is a `RuntimeError`, NOT a `ValueError`, so
                # the first two alone missed it (CG-80 pre-merge review, M6):
                # 30 000 levels of nesting produced a 500 with a traceback rather
                # than the -32700 that every other unparseable body gets.
                raise _McpRequestError(400, PARSE_ERROR, "invalid JSON")
            if isinstance(payload, list):
                raise _McpRequestError(
                    400, INVALID_REQUEST,
                    "the POST body must be a single JSON-RPC request or "
                    "notification; batching was removed from the protocol")
            if not isinstance(payload, dict):
                # SPLIT FROM THE ARRAY CASE (CG-80 pre-merge review, L3). A body
                # of `null`, `42` or `"hi"` used to be told batching had been
                # removed from the protocol, which sends a reader looking for a
                # batching bug they do not have.
                raise _McpRequestError(
                    400, INVALID_REQUEST,
                    "the POST body must be a JSON object carrying a single "
                    "JSON-RPC request or notification; got " + _short(payload))
            rid = payload.get("id")
            _validate_envelope(payload)
            if "id" not in payload or payload["method"].startswith("notifications/"):
                return _notification_response(payload)
            return _handle(registry, adapters, app_id, payload, request,
                           delivery_log)
        except _McpRequestError as exc:
            return JSONResponse(
                status_code=exc.http_status,
                content=jsonrpc_error(rid, exc.code, exc.message, exc.data))

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


def _notification_response(payload: dict) -> Response:
    """A JSON-RPC NOTIFICATION, answered the same way in either era.

    ⚠ NOTIFICATION-NESS IS THE ABSENCE OF AN `id`, NEVER A METHOD NAME (CG-80
    pre-merge review, M2). Keying on the name got three things wrong at once,
    all measured: legacy `ping` with no `id` answered `200 {"id": null,
    "result": {}}` and modern `tools/list` with no `id` answered a full result
    body — responses to messages that MUST NOT get one — while
    `notifications/cancelled`, which real clients emit on a cancellation or a
    timeout, fell through to the unimplemented-method rule and got a **404 with
    a JSON-RPC error body** in both eras. The 404 rule is for an unimplemented
    REQUEST; a notification we do not act on is not an error at all, it is a
    message we are entitled to ignore.

    So: no id, any method, either era → 202 and an EMPTY body. A JSON `null`
    body would itself be a response.

    The remaining case is a `notifications/*` method that DOES carry an id, and
    it is answered rather than dropped. That is a deviation from "any
    `notifications/*` gets 202", taken deliberately: 202-with-no-body leaves a
    client that asked a question waiting for an answer that will never come,
    which is the same hang the review flagged. It is a malformed frame — a
    notification method sent as a request — so it gets the Invalid Request its
    shape earns, WITH its id echoed, and never the -32601 that would send the
    client looking for a method name it did send.
    """
    if "id" not in payload:
        return Response(status_code=202)
    raise _McpRequestError(
        400, INVALID_REQUEST,
        f"{_short(payload['method'])} is a notification and MUST NOT carry an "
        "id; send it without one, or call a request method")


def _era_of(payload: dict, request: Request) -> str:
    """Which protocol era this single request belongs to.

    THE OUTERMOST SEAM IN THIS FILE, and deliberately so: if an era is ever
    dropped, that is deleting a branch rather than unpicking a design.

    Per-request rather than per-connection, which is safe because modern MCP is
    stateless by definition and legacy's era is already established by its own
    handshake.

    ⚠ IT KEYS ON THREE SIGNALS, NOT ONE, AND THE REASON IS THE DIRECTION OF THE
    MISTAKE (CG-80 pre-merge review, H3). This used to read `params._meta` and
    nothing else, which is fine for a modern `tools/call` and wrong for
    everything else a modern client sends:

    * a modern `tools/list` carries no `params` at all, so it was served as
      LEGACY — HTTP 200, a legacy-shaped body, no `resultType`/`ttlMs`/
      `cacheScope`, and not one word saying so;
    * a modern `tools/call` with its `_meta` omitted was likewise served as
      legacy, which meant §6.3 requirement 2's header MUST was skipped
      entirely — deliberately mismatched `Mcp-Method`/`Mcp-Name` headers
      DELIVERED THE MESSAGE — and §6.3 requirement 4's "missing `_meta` →
      -32602" could not exist at all, because a missing `_meta` was
      indistinguishable from a legacy request.

    Both failures point modern→legacy and both are SILENT, which is precisely
    the outcome this module's docstring says the dual-era design exists to
    avoid. So the discriminator now reads every modern-only signal actually on
    the wire, and a request only has to carry one of them.

    `Mcp-Method` is the strongest of the three because it has NO legacy
    analogue — it was added by `2026-07-28` — so keying on its presence yields
    no false positives. `MCP-Protocol-Version` is compared for EQUALITY with
    the modern revision rather than for presence, because that header does have
    a legacy analogue: `2025-06-18` introduced it, and a conformant legacy
    client sends it carrying a legacy revision.
    """
    params = payload.get("params")
    if isinstance(params, dict):
        meta = params.get("_meta")
        if isinstance(meta, dict) and META_PROTOCOL_VERSION in meta:
            return "modern"
    if request.headers.get("Mcp-Method") is not None:
        return "modern"
    if request.headers.get("MCP-Protocol-Version") == MODERN_PROTOCOL_VERSION:
        return "modern"
    return "legacy"


def _server_info() -> dict:
    return {"name": "chat-gateway", "version": __version__}


def _handle(registry: Registry, adapters: dict[str, Any], app_id: str,
            payload: dict, request: Request,
            delivery_log: DeliveryLog | None = None
            ) -> JSONResponse | Response:
    """⚠ PLAIN SYNC, deliberately — see `mcp_post`'s docstring. Everything below
    here may block (a 30s `httpx` send, a delivery-log file write) and is reached
    through `run_in_threadpool`; an `await` anywhere in this subtree would put it
    back on the loop thread and take `/healthz` down with the next hung webhook.
    `request` is read for HEADERS ONLY, which is synchronous.
    """
    if _era_of(payload, request) == "modern":
        return _handle_modern(registry, adapters, app_id, payload, request,
                              delivery_log)
    return _handle_legacy(registry, adapters, app_id, payload, delivery_log)


def _handle_legacy(registry: Registry, adapters: dict[str, Any], app_id: str,
                   payload: dict, delivery_log: DeliveryLog | None = None
                   ) -> JSONResponse | Response:
    """The handshake era (`2025-11-25` and earlier). Plain sync — `mcp_post`.

    Notifications never reach here: `_serve` answers anything without an `id`
    with 202 before the era is even decided (M2), which is why `ping` and
    `tools/list` below may assume they were asked a question.
    """
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
        #
        # ⚠ THE FALLBACK IS THE LEGACY REVISION, NOT `SUPPORTED_PROTOCOL_VERSIONS[0]`
        # (CG-80 pre-merge review, M3), and the SHOULD above is what is being
        # traded away on purpose. `initialize` exists in ONE era: only a legacy
        # client ever sends it, because `2026-07-28` deleted the method. Answering
        # it with the modern revision therefore hands a client a version it cannot
        # speak by construction — and the legacy spec says a client SHOULD
        # disconnect when it cannot support the version it was given. The server
        # would be telling exactly the clients it can serve to go away, which is
        # the D4a failure mode dual-era exists to prevent, produced by the
        # dual-era code itself.
        #
        # "SHOULD be the latest version supported by the server" is not a MUST,
        # and this reads it as the latest version supported IN THE ERA THIS
        # HANDSHAKE BELONGS TO — which is what makes the answer useful rather
        # than merely maximal. `server/discover` publishes the full list
        # verbatim, so nothing is hidden from a client that can ask.
        version = (requested if requested in SUPPORTED_PROTOCOL_VERSIONS
                   else LEGACY_PROTOCOL_VERSION)
        return JSONResponse(jsonrpc_result(rid, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": _server_info(),
            "instructions": _INSTRUCTIONS,
        }))

    if method == "ping":
        return JSONResponse(jsonrpc_result(rid, {}))

    if method == "tools/list":
        return JSONResponse(jsonrpc_result(
            rid, {"tools": tools_for(registry, app_id)}))

    if method == "tools/call":
        result, err = call_tool(registry, adapters, app_id,
                                params.get("name"), params.get("arguments") or {},
                                delivery_log=delivery_log)
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
                              "method not found: " + _short(method)))


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
                   payload: dict, request: Request,
                   delivery_log: DeliveryLog | None = None) -> JSONResponse:
    """The stateless era (`2026-07-28`). Plain sync — see `mcp_post`.

    Everything the legacy branch gets from a handshake, this branch gets from
    the request in front of it — which is the whole point of the revision:
    "A server processes each request independently; no state should be inferred
    from previous requests, even those on the same connection or stream."
    """
    rid = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    meta = params.get("_meta")

    # §6.3 requirement 4's other half: missing `_meta` → 400 + -32602. ⚠ THIS
    # BRANCH WAS UNREACHABLE UNTIL CG-80's pre-merge review fixed `_era_of`
    # (H3) — with the discriminator keyed only on `_meta`, a request without one
    # was indistinguishable from a legacy request and was quietly served as one,
    # so the requirement could not fail and could not pass either. Checked
    # SEPARATELY from the two keys below so the message names the thing that is
    # actually missing rather than blaming one member of a container that is not
    # there.
    if not isinstance(meta, dict):
        raise _McpRequestError(
            400, INVALID_PARAMS,
            "params._meta is required on every modern-era request")
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
                                params.get("arguments") or {},
                                delivery_log=delivery_log)
        if err is not None:
            return JSONResponse(jsonrpc_error(rid, err["code"], err["message"]))
        return JSONResponse(jsonrpc_result(rid, {"resultType": "complete",
                                                 **result}))

    raise _McpRequestError(404, METHOD_NOT_FOUND,
                           "method not found: " + _short(method))
