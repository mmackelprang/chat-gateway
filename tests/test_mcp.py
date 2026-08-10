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
