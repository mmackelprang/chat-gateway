"""The MCP server surface, end to end, with a fake delivery adapter.

Offline: no network, no Google. Same idiom as tests/test_service.py.
"""

import asyncio
import json

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


def _registry_of(env):
    """The Registry the fixture's app was built from."""
    client, _ = env
    return client.app.state.registry


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
    r = client.post("/mcp", headers={**AUTH, "Content-Type": "application/json"},
                    content=b"{not json")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32700


# ---------------------------------------------------------- Origin (§6.3) ---
def test_a_request_with_no_origin_header_is_NOT_refused(env):
    """The spec's MUST fires only when Origin is PRESENT and invalid. A
    non-browser MCP client sends none, and refusing those would lock out
    every client we care about.

    ⚠ Asserts 200, not `!= 403` (CG-80 pre-merge review, test gap 4). The
    negative form passes on a 500 and on a 401 — i.e. it stays green in exactly
    the states where the client is still locked out, just for a different
    reason. What has to hold is that the request WORKED."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 200
    assert r.json()["result"] == {}


def test_a_present_origin_is_refused_when_no_allowlist_is_configured(env):
    """Fail closed. We serve no browser client, and DNS-rebinding protection
    is a MUST — so an unrecognised Origin is 403 rather than waved through."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_an_allowlisted_origin_is_accepted(env, monkeypatch):
    """200, not `!= 403` — same reasoning as the no-Origin test above."""
    client, _ = env
    monkeypatch.setenv("CHAT_GATEWAY_MCP_ALLOWED_ORIGINS",
                       "https://ok.example, https://also-ok.example")
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Origin": "https://also-ok.example"})
    assert r.status_code == 200
    assert r.json()["result"] == {}


# ---------------------------------------------------------- groups 9, 10 ----
from chat_gateway.envelope import OutboundMessage  # noqa: E402
from chat_gateway.mcp import send_message_schema, tools_for  # noqa: E402


NARROWED_PROPERTY = "identity"


def _strip(schema):
    """Remove exactly the two things we are allowed to narrow — and ONLY on the
    one property we are allowed to narrow them on.

    ⚠ THIS FUNCTION IS THE RULE #1 GUARD, and until CG-80's pre-merge review it
    was blind everywhere except `identity` (finding M4). It dropped `enum` and
    `description` from EVERY property, so the guard the file calls its most
    important test could not see the textbook leak: hand-writing
    `schema["properties"]["text"]["enum"] = ["build failed", "deploy ok"]` —
    the gateway learning an app's occasions, in the one field a model reads
    most closely — left it green. Measured, then fixed, then re-measured; see
    `test_the_rule_1_guard_CATCHES_a_hand_written_enum_on_a_non_identity_property`
    below, which exists solely to keep this honest.

    What is dropped now: the top-level `title`/`description` (the tool carries
    its own, and showing a model two competing descriptions of the same thing
    is what `send_message_schema_base` strips them for), and `enum` +
    `description` on `identity` alone. EVERYTHING else — including each
    property's own `title` — is compared byte for byte, because both sides come
    from the same `model_json_schema()` call and any difference between them is
    a human having typed something.
    """
    out = {k: v for k, v in schema.items() if k not in ("title", "description")}
    props = {}
    for name, prop in out["properties"].items():
        drop = ("enum", "description") if name == NARROWED_PROPERTY else ()
        props[name] = {k: v for k, v in prop.items() if k not in drop}
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


def test_the_rule_1_guard_CATCHES_a_hand_written_enum_on_a_non_identity_property():
    """⚠ A TEST OF THE TEST ABOVE, and it is not ceremony — it is the finding.

    A guard that cannot fail is worth nothing, and this one could not: `_strip`
    dropped `enum` from every property, so the single most likely rule #1
    breach — an `enum` of app-domain occasions bolted onto `text` — sailed
    through. Measured on the pre-fix guard: green. This simulates exactly that
    hand-edit against the repaired `_strip` and asserts it is now red.

    Simulated rather than performed on the real `send_message_schema`, because
    the point is to prove the COMPARISON detects the leak; a monkeypatched
    producer would prove the same thing with more machinery.
    """
    generated = OutboundMessage.model_json_schema()
    poisoned = json.loads(json.dumps(generated))  # deep copy, no aliasing
    poisoned["properties"]["text"]["enum"] = ["build failed", "deploy ok"]
    assert _strip(poisoned) != _strip(generated)


def test_every_non_identity_property_is_byte_identical_to_the_generated_one(env):
    """The same guarantee stated positively, and independent of `_strip`.

    `_strip` is test-file machinery and could itself drift; this reads the
    shipped schema directly. Only `identity` may differ from the generator's
    output, and only in `enum` and `description`.
    """
    generated = OutboundMessage.model_json_schema()["properties"]
    shipped = send_message_schema(_registry_of(env),
                                  "aiteam-harness")["properties"]
    assert set(shipped) == set(generated)
    for name, prop in shipped.items():
        if name == NARROWED_PROPERTY:
            continue
        assert prop == generated[name], name
    narrowed = shipped[NARROWED_PROPERTY]
    assert {k: v for k, v in narrowed.items()
            if k not in ("enum", "description")} == {
        k: v for k, v in generated[NARROWED_PROPERTY].items()
        if k not in ("enum", "description")}


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


def test_legacy_initialize_with_an_unknown_version_answers_with_the_LEGACY_one(env):
    """⚠ THE PINNED VALUE CHANGED, and the reason is worth more than the assert.

    This test asserted `MODERN_PROTOCOL_VERSION` until CG-80's pre-merge review
    (finding M3), because `SUPPORTED_PROTOCOL_VERSIONS[0]` is the modern
    revision and the spec's words are "SHOULD be the latest version supported
    by the server". Both halves were true and the result was still wrong:
    `initialize` was DELETED by `2026-07-28`, so the only client that can ever
    send it is a legacy one — and the legacy spec says a client SHOULD
    disconnect when it cannot support the version it is handed. Answering
    `2026-07-28` therefore told exactly the clients this server can serve to go
    away, which is the D4a failure mode dual-era exists to prevent, produced by
    the dual-era code itself.

    So the SHOULD is read as "the latest version supported IN THE ERA THIS
    HANDSHAKE BELONGS TO", and it is subordinate to the design's own
    reachability goal — a SHOULD, not a MUST, which is what makes that reading
    conformant rather than convenient. Nothing is concealed either way:
    `server/discover` publishes `supportedVersions` verbatim.
    """
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "1900-01-01",
                                "capabilities": {}}})
    assert r.json()["result"]["protocolVersion"] == LEGACY_PROTOCOL_VERSION
    assert r.json()["result"]["protocolVersion"] != MODERN_PROTOCOL_VERSION


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


def test_an_mcp_send_is_written_to_the_delivery_log(env):
    """⚠ DEVIATION FROM THE PLAN, and this test is why it was needed.

    The spec's §2 table lists exactly two properties an MCP `send_message`
    inherits from `POST /v1/messages`, and the second is *audit / delivery
    log — ✅ `DeliveryLog.record`*. The plan's `call_tool` took no log and
    recorded nothing, so that claim — and the plan's own Goal line, and the
    UAT step that asks for "the `/v1/deliveries` row" as proof a message
    arrived — would all have been untrue of the shipped code: an MCP send
    would have left no trace in the delivery log or the on-disk audit trail.

    Driven end to end through the HTTP surface rather than against
    `call_tool`, because what has to hold is that the log the ROUTER was
    built with is the one `GET /v1/deliveries` reads.
    """
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                     "params": {"name": "send_message",
                                "arguments": {"identity": "pm-familyworkspace",
                                              "text": "audited"}}})
    assert r.json()["result"]["isError"] is False
    rows = client.get("/v1/deliveries", headers=AUTH).json()["deliveries"]
    assert [(row["source"], row["kind"], row["title"], row["status"])
            for row in rows] == [("aiteam-harness", "message", "audited",
                                  "delivered")]


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


def test_a_modern_request_missing_meta_clientCapabilities_is_400(env):
    """Renamed from `..._missing_required_meta_fields_is_400` (CG-80 pre-merge
    review, test gap 1): it deletes ONE key and keeps `protocolVersion`, so it
    never tested a missing `_meta` at all. The real one is directly below."""
    client, _ = env
    body = modern("tools/list")
    del body["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"]
    r = rpc(client, body, headers=modern_headers("tools/list"))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32602


def test_a_modern_request_with_NO_meta_at_all_is_400(env):
    """§6.3 requirement 4's other half — and it was UNREACHABLE until H3.

    With the era discriminator keyed only on `params._meta`, a modern request
    that omitted `_meta` was indistinguishable from a legacy one and was served
    as legacy: HTTP 200, a legacy-shaped body, the modern header MUSTs skipped.
    The requirement could neither fail nor pass. The widened discriminator sees
    the `Mcp-Method` header — which has no legacy analogue — so the request now
    lands on the modern branch and gets the -32602 the spec specifies.
    """
    client, _ = env
    body = modern("tools/list")
    del body["params"]["_meta"]
    r = rpc(client, body, headers=modern_headers("tools/list"))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32602
    assert "_meta" in r.json()["error"]["message"]


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


# ============================================================================
# CG-80 pre-merge review regressions. Every test below pins a defect that was
# MEASURED on the first cut of this surface, not a hypothetical.
# ============================================================================
from pathlib import Path  # noqa: E402

import chat_gateway.__main__ as cg_main  # noqa: E402
from chat_gateway.mcp import _McpRequestError  # noqa: E402


# ------------------------------------------------------------------- H1 -----
@pytest.mark.parametrize("method,params", [
    ("tools/call", "notadict"),
    ("initialize", "notadict"),
    ("tools/list", ["a"]),
    ("ping", 42),
])
def test_a_non_object_params_is_400_minus_32602_for_EVERY_method(env, method,
                                                                 params):
    """H1. A non-dict `params` used to reach `params.get(...)` and 500 with a
    traceback — `_era_of` guarded with `isinstance(params, dict)` and then fell
    through to the legacy branch, which did `payload.get("params") or {}`, and a
    non-empty string or list is TRUTHY so the guard never fired.

    It was inconsistent as well as wrong: the same body on `tools/list` answered
    200, because that branch never reads `params`. Answered once, centrally, so
    every method gives the same loud answer — and NOT coerced to `{}`, which
    would hide a malformed request behind a success."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": method,
                     "params": params})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32602
    assert "params must be an object" in r.json()["error"]["message"]


def test_a_null_params_is_treated_as_ABSENT_rather_than_refused(env):
    """⚠ The one deliberate narrowing of H1's rule, recorded so it is a decision
    rather than an oversight. JSON-RPC says `params` MAY be omitted, and `null`
    is how a great many serializers omit it; a string, a number or an array is a
    genuinely malformed frame. Refusing `null` would make this gateway
    unreachable to conformant-enough clients for no safety gain — the silent
    unreachability this module exists to avoid, delivered loudly instead."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "ping",
                     "params": None})
    assert r.status_code == 200
    assert r.json()["result"] == {}


# ------------------------------------------------------------------- H2 -----
class ThreadProbeAdapter(FakeAdapter):
    """Records whether `send` ran on a thread with a RUNNING event loop."""

    def __init__(self):
        super().__init__()
        self.on_event_loop = None

    def send(self, identity, message):
        try:
            asyncio.get_running_loop()
            self.on_event_loop = True
        except RuntimeError:
            self.on_event_loop = False
        return super().send(identity, message)


def test_the_blocking_send_does_NOT_run_on_the_asyncio_event_loop(env, tmp_path):
    """H2, and it is a hard rule #5 control rather than a performance note.

    `mcp_post` is `async def` because it must `await request.body()`. Everything
    after that blocks: `adapter.send` is a SYNCHRONOUS `httpx.Client` with a 30s
    timeout and `DeliveryLog.record` writes a file. Run on the loop thread they
    stall EVERY concurrent request in the process — including the
    unauthenticated `/healthz`, whose whole purpose is answering honestly while
    something else is broken. An honest health endpoint nobody can reach is
    worth exactly what the hardcoded OK rule #5 was written after was worth.

    `POST /v1/messages` gets this free by being declared `def`; this route buys
    it with `run_in_threadpool`. Measured both ways before the fix: via
    `/v1/messages` the send ran on an AnyIO worker thread, via `/mcp` it ran on
    the thread with the running loop. This asserts the asymmetry is closed.
    """
    p = tmp_path / "probe.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    probe = ThreadProbeAdapter()
    client = TestClient(create_app(load_registry(p), Inbox(),
                                   {"webhook": probe}, mcp_enabled=True))
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": "send_message",
                                "arguments": {"identity": "pm-familyworkspace",
                                              "text": "off the loop"}}})
    assert r.json()["result"]["isError"] is False
    assert probe.on_event_loop is False

    # The comparison that makes the claim meaningful: the route that already
    # got this right, measured the same way.
    probe.on_event_loop = None
    client.post("/v1/messages", headers=AUTH,
                json={"identity": "pm-familyworkspace", "text": "sibling"})
    assert probe.on_event_loop is False


# ------------------------------------------------------------------- H3 -----
def test_a_modern_tools_list_with_NO_params_is_served_as_MODERN(env):
    """H3, and this is the silent one.

    `tools/list` takes no arguments, so a modern client sends no `params` at
    all — and the discriminator keyed only on `params._meta` therefore served
    every one of them as LEGACY: HTTP 200, a legacy-shaped body, no
    `resultType`, no `ttlMs`, no `cacheScope`, and not one word saying so. The
    direction of the misclassification is modern→legacy, which is precisely the
    outcome this module's docstring says the dual-era design exists to avoid.

    `Mcp-Method` is what saves it: the header has no legacy analogue, so its
    presence is a modern signal with no false positives.
    """
    client, _ = env
    # A modern client calling a no-argument method: no `params` member at all,
    # all three modern headers correct. It used to answer 200 with a legacy body.
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers=modern_headers("tools/list"))
    assert r.status_code == 400, "the modern branch demands _meta; legacy does not"
    assert r.json()["error"]["code"] == -32602

    # ...and the same method WITH `_meta` gets the modern-shaped result, which
    # is what "served as modern" positively looks like.
    ok = rpc(client, modern("tools/list"), headers=modern_headers("tools/list"))
    assert ok.json()["result"]["resultType"] == "complete"
    assert ok.json()["result"]["cacheScope"] == "private"


def test_the_protocol_version_header_alone_classifies_a_request_as_modern(env):
    """The third signal. Compared for EQUALITY with the modern revision, never
    for presence: `MCP-Protocol-Version` was introduced by `2025-06-18`, so a
    conformant LEGACY client sends it too — carrying a legacy revision."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"MCP-Protocol-Version": MODERN_PROTOCOL_VERSION})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32602

    # ...and the legacy revision in the same header does NOT flip the era.
    ok = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
             headers={"MCP-Protocol-Version": LEGACY_PROTOCOL_VERSION})
    assert ok.status_code == 200
    assert "resultType" not in ok.json()["result"]


def test_a_modern_tools_call_with_no_meta_is_REFUSED_not_silently_delivered(env):
    """H3's sharpest measurement: this body, with deliberately MISMATCHED
    `Mcp-Method` and `Mcp-Name` headers, used to be served as legacy — so §6.3
    requirement 2's header MUST was skipped entirely and THE MESSAGE WAS
    DELIVERED. Nothing about the response said an era had been chosen."""
    client, adapter = env
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "send_message",
                       "arguments": {"identity": "pm-familyworkspace",
                                     "text": "must not arrive"}}}
    r = rpc(client, body, headers=modern_headers("tools/list", "something_else"))
    assert r.status_code == 400
    assert adapter.sent == []


# ------------------------------------------------------------------- M1 -----
def test_the_jsonrpc_id_is_echoed_on_a_MODERN_era_error(env):
    """M1. The `except _McpRequestError` handler built `jsonrpc_error(None,...)`,
    so every error raised out of the modern branch answered `id: null`. Measured:
    an unimplemented method in the LEGACY branch echoed `id: 42` correctly
    (it returns rather than raises), the same thing in the modern branch did
    not. JSON-RPC permits a null id only when it could not be determined; here
    it was parsed fine, and a client correlating concurrent requests by id
    cannot match the response."""
    client, _ = env
    r = rpc(client, modern("resources/list", rid=42),
            headers=modern_headers("resources/list"))
    assert r.status_code == 404
    assert r.json()["id"] == 42


@pytest.mark.parametrize("body,headers,code", [
    (modern("tools/list", version="1900-01-01", rid=77),
     modern_headers("tools/list", version="1900-01-01"), -32022),
    (modern("tools/list", rid=77), {"Mcp-Method": "tools/list"}, -32020),
])
def test_the_id_is_echoed_on_the_other_modern_error_codes_too(env, body,
                                                              headers, code):
    client, _ = env
    r = rpc(client, body, headers=headers)
    assert r.json()["error"]["code"] == code
    assert r.json()["id"] == 77


@pytest.mark.parametrize("post", [
    lambda c: rpc(c, {"jsonrpc": "2.0", "id": 5, "method": "ping"},
                  headers={"Origin": "https://evil.example"}),
    lambda c: c.post("/mcp", headers={**AUTH, "Content-Type": "application/json"},
                     content=b"{not json"),
    lambda c: rpc(c, [{"jsonrpc": "2.0", "id": 5, "method": "ping"}]),
    lambda c: c.post("/mcp", headers={**AUTH, "Content-Type": "application/json"},
                     content=b"42"),
])
def test_the_id_stays_NULL_where_it_genuinely_could_not_be_determined(env, post):
    """⚠ The other half of M1, and the reason "always echo the id" is the WRONG
    generalisation. In these four cases the id is not knowable: the Origin 403
    fires before the body is read at all, and the other three are bodies that
    never parsed into a JSON-RPC object. JSON-RPC's null id means exactly
    that — do not "fix" these to echo something."""
    client, _ = env
    r = post(client)
    assert r.json()["id"] is None


# ------------------------------------------------------------------- M2 -----
@pytest.mark.parametrize("body,headers", [
    ({"jsonrpc": "2.0", "method": "ping"}, None),
    ({"jsonrpc": "2.0", "method": "notifications/initialized"}, None),
    ({"jsonrpc": "2.0", "method": "notifications/cancelled",
      "params": {"requestId": 1}}, None),
    ({"jsonrpc": "2.0", "method": "tools/list", "params": {"_meta": {
        "io.modelcontextprotocol/protocolVersion": MODERN_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {}}}},
     {"MCP-Protocol-Version": MODERN_PROTOCOL_VERSION,
      "Mcp-Method": "tools/list"}),
])
def test_any_notification_is_202_with_an_empty_body_in_either_era(env, body,
                                                                  headers):
    """M2. Notification-ness is the ABSENCE OF AN `id`, never a method name.

    Measured on the first cut, all four of these: legacy `ping` with no id
    answered `200 {"id": null, "result": {}}`; modern `tools/list` with no id
    answered a full result body — responses to messages that MUST NOT get one —
    and `notifications/cancelled`, which real clients emit on a cancellation or
    a timeout, fell through to the unimplemented-method rule and got a 404 with
    a JSON-RPC error body in BOTH eras. The 404 rule is for an unimplemented
    REQUEST."""
    client, _ = env
    r = rpc(client, body, headers=headers)
    assert r.status_code == 202
    assert r.content == b""


def test_a_notification_method_carrying_an_id_is_ANSWERED_not_dropped(env):
    """⚠ A deliberate deviation from "any `notifications/*` gets 202", and it is
    the reviewer's own complaint taken to its conclusion: 202-with-no-body
    leaves a client that asked a question waiting forever. The frame is
    malformed — a notification method sent as a request — so it earns an
    Invalid Request WITH ITS ID ECHOED, and never the -32601 that would send the
    client looking for a method name it did send."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 8,
                     "method": "notifications/initialized"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32600
    assert r.json()["id"] == 8


# ------------------------------------------------------------------- M5 -----
def test_a_validation_failure_NAMES_THE_FIELD_so_a_model_can_self_correct(env):
    """M5. Every bad-argument shape used to collapse to
    `invalid arguments for send_message: ValidationError` — strictly less than
    "something was wrong". Spec §6.5 quotes the protocol at length on exactly
    this ("Otherwise, the LLM would not be able to see that an error occurred
    and self-correct") and `call_tool`'s docstring repeats it, so the emitted
    text was contradicting the reasoning printed directly above it."""
    client, adapter = env
    result, err = call_tool(_registry_of(env), {"webhook": adapter},
                            "aiteam-harness", "send_message",
                            {"identity": "pm-familyworkspace"})
    assert err is None
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "text" in text
    assert "missing" in text


def test_a_validation_failure_NEVER_echoes_a_value_the_caller_supplied(env):
    """The hard rule #2 half, and the reason this narrow exception is safe.

    `exc.errors(include_input=False, ...)` is what keeps the offending VALUE
    out — `input_value=...` is the member `errors.py`'s docstring names in its
    first paragraph as the reason a ValidationError may not be printed. What is
    emitted is `type` (pydantic's own literal), `loc` (OUR field names) and
    `msg` (pydantic's rendering, or a validator authored in `envelope.py`).
    """
    client, adapter = env
    secret = "SEKRIT-CALLER-BYTES"
    result, err = call_tool(_registry_of(env), {"webhook": adapter},
                            "aiteam-harness", "send_message",
                            {"identity": "pm-familyworkspace",
                             "text": secret * 400,
                             "cards": [{"nope": secret}]})
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert secret not in text
    assert "text" in text and "cards" in text


def test_a_NON_validation_argument_error_still_gets_the_type_name_only(env):
    """The allowlist is unchanged everywhere else. A non-mapping `arguments`
    raises a TypeError out of `OutboundMessage(**...)`, and that is not the one
    class the narrow exception covers."""
    client, adapter = env
    result, err = call_tool(_registry_of(env), {"webhook": adapter},
                            "aiteam-harness", "send_message", "not-a-mapping")
    assert result["isError"] is True
    assert "TypeError" in result["content"][0]["text"]


# ------------------------------------------------------------------- M6 -----
def test_deeply_nested_json_is_a_parse_error_not_a_500(env):
    """M6. `json.loads` raises `RecursionError` on deep nesting — a
    `RuntimeError`, NOT a `ValueError` — so `except (ValueError,
    UnicodeDecodeError)` missed it and 30 000 levels produced a 500 with a
    traceback."""
    client, _ = env
    r = client.post("/mcp", headers={**AUTH, "Content-Type": "application/json"},
                    content=b"[" * 30_000 + b"]" * 30_000)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32700


# ------------------------------------------------------------------- L1 -----
@pytest.mark.parametrize("body", [
    {"id": 1, "method": "ping"},
    {"jsonrpc": "1.0", "id": 1, "method": "ping"},
    {"jsonrpc": 2.0, "id": 1, "method": "ping"},
])
def test_a_missing_or_wrong_jsonrpc_member_is_minus_32600(env, body):
    """L1. Both of the first two returned 200 before this. This module's whole
    point is conformance, so accepting a frame that names a protocol we do not
    speak is the one thing it must not do."""
    client, _ = env
    r = rpc(client, body)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32600


# ------------------------------------------------------------------- L2 -----
@pytest.mark.parametrize("body", [
    {"jsonrpc": "2.0", "id": 1},
    {"jsonrpc": "2.0", "id": 1, "method": None},
    {"jsonrpc": "2.0", "id": 1, "method": 7},
    {"jsonrpc": "2.0", "id": 1, "method": ["tools/list"]},
])
def test_a_missing_or_non_string_method_is_INVALID_REQUEST_not_METHOD_NOT_FOUND(
        env, body):
    """L2. These answered -32601 "method not found: None" — but a missing member
    is a malformed REQUEST, not a request for a method that happens not to
    exist, and a client told -32601 goes looking for a method name it never
    sent."""
    client, _ = env
    r = rpc(client, body)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32600
    assert "method must be a string" in r.json()["error"]["message"]


def test_an_unknown_method_name_is_echoed_TRUNCATED(env):
    """L2's other half. Not a rule #2 issue — a method name is the caller's own
    bytes coming back to the caller — but an unbounded echo of client input into
    a response body turns a small request into a large one for nothing."""
    client, _ = env
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "x" * 5_000})
    assert r.status_code == 404
    assert len(r.json()["error"]["message"]) < 200
    assert "truncated" in r.json()["error"]["message"]


# ------------------------------------------------------------------- L3 -----
@pytest.mark.parametrize("raw", [b"null", b"42", b'"hi"'])
def test_a_scalar_body_is_NOT_blamed_on_batching(env, raw):
    """L3. A body of `null`, `42` or `"hi"` was told batching had been removed
    from the protocol, which sends a reader after a bug they do not have.

    Posted as RAW BYTES rather than through `json=`: httpx reads `json=None` as
    "send no JSON body at all", which would test an empty body (-32700) instead
    of the JSON literal `null` this is about.
    """
    client, _ = env
    r = client.post("/mcp", headers={**AUTH, "Content-Type": "application/json"},
                    content=raw)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32600
    assert "batching" not in r.json()["error"]["message"]
    # ...and the array case still says exactly that, because for an array it
    # is the true diagnosis.
    arr = rpc(client, [{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
    assert "batching" in arr.json()["error"]["message"]


# ------------------------------------------------------- modern-era gaps ----
def test_an_unimplemented_method_in_the_MODERN_era_is_404_with_minus_32601(env):
    """Test gap 2. The existing unimplemented-method test drives the LEGACY
    branch — the modern branch raises rather than returning, through an entirely
    different code path, and nothing exercised it."""
    client, _ = env
    r = rpc(client, modern("resources/list"),
            headers=modern_headers("resources/list"))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == -32601


def test_an_unknown_tool_in_the_MODERN_era_is_200_with_minus_32602(env):
    """Test gap 5. `tools/call` IS implemented; only the name is wrong."""
    client, adapter = env
    r = rpc(client, modern("tools/call", {"name": "nope", "arguments": {}}),
            headers=modern_headers("tools/call", "nope"))
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32602
    assert adapter.sent == []


def test_a_MODERN_era_send_is_also_written_to_the_delivery_log(env):
    """Test gap 5. The delivery-log write was only ever asserted through the
    legacy branch, and the two branches call `call_tool` from different places
    — the spec's §2 table claim is about the SURFACE, not about one era."""
    client, _ = env
    r = rpc(client, modern("tools/call",
                           {"name": "send_message",
                            "arguments": {"identity": "pm-familyworkspace",
                                          "text": "modern audited"}}),
            headers=modern_headers("tools/call", "send_message"))
    assert r.json()["result"]["isError"] is False
    rows = client.get("/v1/deliveries", headers=AUTH).json()["deliveries"]
    assert [(row["kind"], row["title"], row["status"]) for row in rows] == [
        ("message", "modern audited", "delivered")]


def test_a_FAILED_send_reaches_the_delivery_log_with_the_TYPE_NAME_only(env):
    """Test gap 5, and it is the rule #2 half that had no test at all: only the
    `delivered` row was asserted. This row is persisted to disk AND served back
    over `GET /v1/deliveries`, so `describe_exception` governs it exactly as it
    governs the tool result."""
    client, adapter = env
    adapter.raises = _LeakyError(
        "https://chat.googleapis.com/v1/spaces/X?key=SEKRIT&token=NOPE")
    r = rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": "send_message",
                                "arguments": {"identity": "pm-familyworkspace",
                                              "text": "will fail"}}})
    assert r.json()["result"]["isError"] is True
    rows = client.get("/v1/deliveries", headers=AUTH).json()["deliveries"]
    assert [(row["kind"], row["title"], row["status"]) for row in rows] == [
        ("message", "will fail", "failed")]
    detail = rows[0]["detail"]
    assert detail == "_LeakyError"
    assert "SEKRIT" not in detail and "chat.googleapis" not in detail


# --------------------------------------------------- header sentinel gap ----
def test_a_base64_sentinel_that_does_not_decode_is_400_minus_32020(env):
    """Test gap 5: `decode_header_value`'s failure path, which nothing reached.
    Driven end to end AND directly, because the raise is what a client sees and
    the exception's code is what the response is built from."""
    client, adapter = env
    r = rpc(client, modern("tools/call",
                           {"name": "send_message",
                            "arguments": {"identity": "pm-familyworkspace",
                                          "text": "x"}}),
            headers=modern_headers("tools/call", "=?base64?!!!!?="))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32020
    assert adapter.sent == []

    with pytest.raises(_McpRequestError) as caught:
        decode_header_value("=?base64?!!!!?=")
    assert caught.value.code == -32020
    assert caught.value.http_status == 400


# ------------------------------------------------------- GATEWAY_ENABLE_MCP -
class _FakeSweeper:
    days = 0
    started = False

    def sweep(self):
        return 0

    def start(self):
        self.started = True


def _drive_serve(monkeypatch, tmp_path, env_value):
    """Run `__main__.main(["serve"])` far enough to capture `create_app`'s
    kwargs, with uvicorn and the runtime build stubbed out.

    Test gap 3. Nothing exercised `os.environ.get("GATEWAY_ENABLE_MCP", "0") ==
    "1"`, so a typo there would ship a permanently-off surface with a green
    suite — the whole point of the flag, silently absent. Driven through `main`
    rather than against a helper, because what has to hold is that THIS
    process's env reaches THAT keyword argument.
    """
    # Not the `env` fixture: this drives `main`, which builds its own app, so
    # the keys have to be resolvable in THIS process's environment too.
    monkeypatch.setenv("SVC_KEY_AITEAM", "cgk_test_key")
    monkeypatch.setenv("SVC_KEY_JOBHUNT", "cgk_other_key")
    monkeypatch.setenv("SVC_HOOK_FW", "https://x.example/hook")
    monkeypatch.setenv("SVC_HOOK_OTHER", "https://y.example/hook")
    p = tmp_path / "main.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    registry = load_registry(p)
    monkeypatch.setattr(cg_main, "build_runtime",
                        lambda: (registry, Inbox(), {"webhook": FakeAdapter()},
                                 None, str(tmp_path / "state"), _FakeSweeper()))
    captured = {}

    def fake_create_app(*a, **kw):
        captured.update(kw)
        app = create_app(*a, **kw)
        captured["_app"] = app
        # Swapped AFTER construction so `main`'s two `.start()` calls do not
        # spawn real background threads in an offline suite.
        app.state.dispatcher = _FakeSweeper()
        app.state.monitor = _FakeSweeper()
        return app

    monkeypatch.setattr("chat_gateway.service.create_app", fake_create_app)
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)
    if env_value is None:
        monkeypatch.delenv("GATEWAY_ENABLE_MCP", raising=False)
    else:
        monkeypatch.setenv("GATEWAY_ENABLE_MCP", env_value)
    assert cg_main.main(["serve"]) == 0
    return captured


@pytest.mark.parametrize("value,expected", [
    ("1", True),
    ("0", False),
    (None, False),
    ("true", False),
    ("", False),
])
def test_GATEWAY_ENABLE_MCP_maps_to_the_create_app_flag(monkeypatch, tmp_path,
                                                        value, expected):
    """Default OFF, and ONLY the literal "1" turns it on — the same posture
    GATEWAY_ENABLE_PUBSUB takes. `"true"` is included deliberately: it is the
    most likely operator typo, and it must read as OFF rather than as a
    surprise surface."""
    captured = _drive_serve(monkeypatch, tmp_path, value)
    assert captured["mcp_enabled"] is expected


@pytest.mark.parametrize("value,mounted", [("1", True), ("0", False)])
def test_the_serve_path_mounts_the_REAL_endpoint_per_the_env_var(
        monkeypatch, tmp_path, value, mounted):
    """The flag reaching `create_app` is half the claim; the endpoint existing
    on the app `main` hands to uvicorn is the other half. Without this, a
    correct flag and a broken mount look identical from the outside."""
    app = _drive_serve(monkeypatch, tmp_path, value)["_app"]
    r = TestClient(app).post("/mcp", headers=AUTH,
                             json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == (200 if mounted else 404)
