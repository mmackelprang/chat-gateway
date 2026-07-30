"""What the gateway is allowed to PRINT about a failure (CG-29, hard rule #2).

Three things are pinned here, and they are three different kinds of claim:

1. **the membership of the marked set** — which exception classes claim
   `GatewayAuthoredError`, repo-wide, and that `PubSubError` is not one of them;
2. **the messages those classes are built from** — a structural guard over
   every raise site, because the whole design rests on those constructors
   STAYING names-and-statuses-only and a docstring saying so would rot;
3. **what `poll_once` actually prints** — the defect CG-29 was filed for, on
   the real R4 path, for a marked exception and for a foreign one.

What is deliberately NOT re-tested here: that each individual message is clean
of response bytes. CG-23 already drives `webhook.send`, `chat_api.send` and
`chat_api.send_text` against hostile bodies and hostile status lines
(`test_webhook_error_names_the_identity_and_never_the_url`,
`test_reason_phrase_is_looked_up_locally_not_read_off_the_wire`,
`test_send_text_failure_strings_are_unchanged_by_cg_23` in `test_adapters.py`).
Those are the behavioural half; this file is the structural half, and its job is
the raise site those tests do not reach — including the one nobody has written
yet.
"""

import ast
import datetime as dt
import re
from pathlib import Path

import httpx
import pytest

from chat_gateway.adapters.chat_api import ChatApiAdapter, ChatApiError
from chat_gateway.adapters.pubsub import (
    PubSubError, PubSubPuller, SubscriberLoop, UnrecognizedEventError,
)
from chat_gateway.adapters.webhook import WebhookDeliveryError
from chat_gateway.errors import GatewayAuthoredError, describe_exception
from chat_gateway.inbox import Inbox
from chat_gateway.registry import load_registry

SRC = Path(__file__).resolve().parents[1] / "src" / "chat_gateway"


def _modules():
    return sorted(SRC.rglob("*.py"))


def _rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


# --------------------------------------------------------------------------
# 1. Who is in the set
# --------------------------------------------------------------------------

# Pinned by NAME and location. Adding a fourth is not forbidden — it is
# forbidden to add one silently, because membership is what entitles a message
# to be printed in full.
MARKED = {
    "ChatApiError": "adapters/chat_api.py",
    "UnrecognizedEventError": "adapters/pubsub.py",
    "WebhookDeliveryError": "adapters/webhook.py",
}


def _declared_marked_classes() -> dict[str, str]:
    found = {}
    for py in _modules():
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                isinstance(b, ast.Name) and b.id == "GatewayAuthoredError"
                for b in node.bases
            ):
                found[node.name] = _rel(py)
    return found


def test_the_marked_set_is_exactly_these_three_classes():
    """Source-level, so a fourth cannot arrive by import-order accident.

    `GatewayAuthoredError.__subclasses__()` would only see classes some test
    happened to import; this reads every module in the package whether or not
    anything imports it.
    """
    assert _declared_marked_classes() == MARKED
    for cls in (ChatApiError, UnrecognizedEventError, WebhookDeliveryError):
        assert issubclass(cls, GatewayAuthoredError)
    # ...and the builtin stayed second, so existing handlers still catch these
    assert issubclass(ChatApiError, RuntimeError)
    assert issubclass(WebhookDeliveryError, RuntimeError)
    assert issubclass(UnrecognizedEventError, ValueError)


def test_pubsub_error_is_excluded_and_this_is_the_measurement_that_excludes_it():
    """`PubSubError` is out of the set because its `str()` carries WIRE BYTES.

    Driven through the real `PubSubPuller._post`, not by constructing the
    exception by hand: httpcore populates `extensions["reason_phrase"]` from
    the literal HTTP/1.1 status line, `_post` passes `resp.reason_phrase`
    straight in, and so a server chooses part of the message. Its docstring
    claims the opposite ("a fixed HTTP string") — that contradiction is CG-33.

    **When CG-33 lands, the first assertion below flips.** That is the point:
    whoever fixes it must come here and decide, in the open, whether
    `PubSubError` now qualifies for the marked set. It is not a test that
    quietly keeps passing either way.
    """
    smuggled = "Forbidden key=SECRETKEYVALUE"

    def hostile_status_line(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="denied",
                              extensions={"reason_phrase": smuggled.encode()})

    puller = PubSubPuller(
        "projects/p/subscriptions/s", lambda: "tok",
        httpx.Client(transport=httpx.MockTransport(hostile_status_line)),
    )
    with pytest.raises(PubSubError) as exc:
        puller.pull()

    # the leak this exclusion exists for — assert it EXISTS, so the exclusion
    # is justified by a measurement rather than by a comment
    assert "SECRETKEYVALUE" in str(exc.value), (
        "PubSubError no longer carries wire bytes — CG-33 has presumably "
        "landed. Re-decide whether it belongs in MARKED, then update this test."
    )
    # ...and the fail-closed consequence: nothing this gateway prints shows it
    assert not isinstance(exc.value, GatewayAuthoredError)
    assert describe_exception(exc.value) == "PubSubError"
    assert "SECRETKEYVALUE" not in describe_exception(exc.value)


def test_describe_exception_fails_closed_on_a_class_it_has_never_seen():
    """The allowlist property itself, stated as a test rather than a docstring.

    A denylist would print this in full — nobody added it to the list of known
    dangers — and that is the whole reason the shape is an allowlist.
    """
    class SomethingNobodyAnticipated(Exception):
        pass

    exc = SomethingNobodyAnticipated("token=SECRETKEYVALUE")
    assert describe_exception(exc) == "SomethingNobodyAnticipated"
    assert "SECRETKEYVALUE" not in describe_exception(exc)
    # and the marked case does the opposite, on the same input
    assert describe_exception(ChatApiError("in-thread reply failed: ConnectError")) == (
        "ChatApiError: in-thread reply failed: ConnectError")


# --------------------------------------------------------------------------
# 2. What the marked classes are allowed to be built from
# --------------------------------------------------------------------------

# Every expression a marked exception's message may interpolate, as source
# text. An ALLOWLIST: an expression that is not here fails the test, so
# `{resp.text}` or `{event['message']}` turns the suite red the moment it is
# written rather than the first time it is printed.
#
# Compared after `_norm` strips whitespace and parentheses, which makes the
# comparison independent of `ast.unparse`'s formatting across Python versions
# while keeping `resp.status_code` and `resp.text` distinct.
APPROVED_INTERPOLATIONS = {
    "identity.name",                    # non-secret; registry.health() publishes it
    "resp.status_code",                 # an int
    "type(exc).__name__",               # a type name, by construction
    "type(event).__name__",
    "httpx.codes.get_reason_phrase(resp.status_code)",   # local table, never the wire
    "sorted(chat)[:10]",                # inbound field NAMES, never values
    "sorted(k for k in event if not k.startswith('_'))[:10]",
}

# `f"...".rstrip()` is the only wrapper any raise site uses. Listed rather than
# assumed so that `.format(resp.text)` — which would smuggle a value past a
# guard that only inspects f-string slots — is rejected as an unknown shape.
APPROVED_WRAPPERS = {"rstrip", "strip", "lstrip"}


def _norm(text: str) -> str:
    return re.sub(r"[\s()]", "", text)


APPROVED = {_norm(t) for t in APPROVED_INTERPOLATIONS}


def _unwrap(node: ast.AST) -> ast.AST | None:
    """The message expression, or None if the shape itself is unrecognized."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node
    if isinstance(node, ast.JoinedStr):
        return node
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in APPROVED_WRAPPERS
            and not node.args and not node.keywords):
        return _unwrap(node.func.value)
    return None


def _enclosing_scope(node: ast.AST) -> ast.AST:
    cur = node
    while (parent := getattr(cur, "parent", None)) is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            return parent
        cur = parent
    return cur


def _single_assignments(scope: ast.AST) -> dict[str, str]:
    """`name -> source` for names bound exactly once in this scope.

    Two raise sites read a local `reason`; without this the guard could not
    tell `httpx.codes.get_reason_phrase(...)` (a local table) from
    `resp.reason_phrase` (the wire). Bound more than once → not resolvable →
    rejected, which is the safe direction.
    """
    seen: dict[str, list[str]] = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                isinstance(node.targets[0], ast.Name):
            seen.setdefault(node.targets[0].id, []).append(ast.unparse(node.value))
    return {k: v[0] for k, v in seen.items() if len(v) == 1}


def _raise_sites():
    """Every `raise <marked class>(...)` in the package, with its message AST.

    Matched by class NAME. An import alias would slip past — noted rather than
    defended against, because nothing in this repo aliases an exception import
    and the guard would have to become a type checker to catch it.
    """
    for py in _modules():
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                child.parent = node
        for node in ast.walk(tree):
            if (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
                    and isinstance(node.exc.func, ast.Name)
                    and node.exc.func.id in MARKED):
                yield _rel(py), node.lineno, node.exc


def test_every_marked_raise_site_interpolates_only_names_and_statuses():
    """The test the design asks for instead of a comment.

    `poll_once` prints these messages in full. That is only safe while every
    one of them is assembled from literals plus the expressions in
    APPROVED_INTERPOLATIONS — a property of the raise sites, not of the classes,
    and therefore one that a future edit can quietly remove. This reads them.
    """
    complaints = []
    for module, lineno, call in _raise_sites():
        where = f"{module}:{lineno} {call.func.id}"
        if len(call.args) != 1 or call.keywords:
            complaints.append(f"{where}: expected exactly one message argument")
            continue
        msg = _unwrap(call.args[0])
        if msg is None:
            complaints.append(
                f"{where}: unrecognized message shape "
                f"{ast.unparse(call.args[0])!r} — a literal, an f-string, or "
                f"one of {sorted(APPROVED_WRAPPERS)} on either")
            continue
        resolvable = _single_assignments(_enclosing_scope(call))
        for slot in ast.walk(msg):
            if not isinstance(slot, ast.FormattedValue):
                continue
            expr = ast.unparse(slot.value)
            if isinstance(slot.value, ast.Name) and expr in resolvable:
                expr = resolvable[expr]        # `reason` -> what it was set to
            if _norm(expr) not in APPROVED:
                complaints.append(f"{where}: interpolates {expr!r}")

    assert not complaints, (
        "A gateway-authored exception message changed shape.\n\n"
        + "\n".join(f"  - {c}" for c in complaints)
        + "\n\nSubscriberLoop.poll_once PRINTS these in full (CG-29). Confirm "
          "the new expression carries a NAME or an HTTP STATUS and never a "
          "response body, a request URL or an inbound payload value (hard rule "
          "#2), then add it to APPROVED_INTERPOLATIONS. If it carries a value, "
          "the fix is the raise site, not this list.")


def test_the_guard_above_actually_finds_the_raise_sites():
    """A guard that inspects nothing passes everything.

    Pins the count so a refactor that moves these out of `raise X(...)` form —
    into a factory, say — cannot silently empty the guard while leaving it green.
    """
    sites = list(_raise_sites())
    per_class = {}
    for _, _, call in sites:
        per_class[call.func.id] = per_class.get(call.func.id, 0) + 1
    assert per_class == {
        "ChatApiError": 5, "UnrecognizedEventError": 4, "WebhookDeliveryError": 2,
    }


# --------------------------------------------------------------------------
# 3. What poll_once prints — the defect itself
# --------------------------------------------------------------------------

CHAT_EVENT = {
    "type": "MESSAGE",
    "space": {"name": "spaces/AAA"},
    "message": {
        "text": "approved — ship it",
        "thread": {"name": "spaces/AAA/threads/T", "threadKey": "review-PC-12"},
        "sender": {"displayName": "Mark", "email": "mark@mackelprang.com"},
    },
}

# A sender NOT on `allowed_users`, which is what makes reply_fn fire: jobhunt
# R4's authorization refusal, the path CG-25's UAT measured this on.
STRANGER = {**CHAT_EVENT,
            "user": {"displayName": "Eve", "email": "eve@example.com"},
            "message": {**CHAT_EVENT["message"],
                        "sender": {"displayName": "Eve", "email": "eve@example.com"}}}

GUARDED_REGISTRY_YAML = """
identities:
  guarded:
    display: "Guarded"
    mode: app
    space: "spaces/AAA"
apps:
  guarded-app:
    key_env: K
    identities: [guarded]
    allow_inbound: true
    allowed_users: [mark@mackelprang.com]
"""


class _OneBatch:
    def __init__(self, events):
        self._events = [(f"ack-{i}", e) for i, e in enumerate(events)]
        self.acked: list[str] = []

    def pull(self, max_messages: int = 10):
        batch, self._events = self._events, []
        return batch

    def acknowledge(self, ack_ids):
        self.acked.extend(ack_ids)


def _loop(tmp_path, reply_fn):
    p = tmp_path / "guarded.yaml"
    p.write_text(GUARDED_REGISTRY_YAML, encoding="utf-8")
    return _OneBatch([STRANGER]), load_registry(p), Inbox(), reply_fn


def test_poll_once_prints_the_gateway_authored_detail(tmp_path, capsys):
    """CG-29. Reached down the real R4 path, with the real adapter raising.

    `reply_fn` is `ChatApiAdapter.send_text` in production (`__main__.py` wires
    it), and CG-25 made both of its failure branches raise `ChatApiError` — so
    after CG-25 the TYPE no longer distinguishes a transport failure from a
    non-200 and only the message does. This line used to discard the message.
    """
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    adapter = ChatApiAdapter(lambda: "tok",
                             httpx.Client(transport=httpx.MockTransport(unreachable)))
    puller, reg, inbox, reply_fn = _loop(tmp_path, adapter.send_text)
    loop = SubscriberLoop(puller, reg, inbox, reply_fn=reply_fn)

    assert loop.poll_once() == 1
    assert loop.dispatch_errors == 1
    out = capsys.readouterr().out
    assert "subscriber: dispatch failed, event acked and dropped: " \
           "ChatApiError: in-thread reply failed: ConnectError" in out
    # the type name did not go away — it gained a message, it did not swap for one
    assert "ChatApiError" in out


def test_poll_once_distinguishes_the_two_failures_cg_25_created(tmp_path, capsys):
    """The measurement CG-29 was filed on: two lines, not one.

    Transport failure and non-200 both arrive as `ChatApiError` after CG-25.
    Before this fix both printed `ChatApiError` and nothing else.
    """
    lines = []
    for handler in (
        lambda request: (_ for _ in ()).throw(
            httpx.ConnectError("connection refused", request=request)),
        lambda request: httpx.Response(403, text="denied"),
    ):
        adapter = ChatApiAdapter(
            lambda: "tok", httpx.Client(transport=httpx.MockTransport(handler)))
        puller, reg, inbox, reply_fn = _loop(tmp_path, adapter.send_text)
        SubscriberLoop(puller, reg, inbox, reply_fn=reply_fn).poll_once()
        lines.append(capsys.readouterr().out.strip())

    assert lines[0] != lines[1]
    assert lines[0].endswith("ChatApiError: in-thread reply failed: ConnectError")
    assert lines[1].endswith("ChatApiError: in-thread reply failed: HTTP 403")


class _RefreshError(Exception):
    """Stands in for `google.auth.exceptions.RefreshError`.

    Not a hypothetical: `send_text` evaluates `self._tokens()` inside its
    `try`, and a google.auth failure is not an `httpx.HTTPError`, so it escapes
    UNTYPED into poll_once. CG-25's row records that hole deliberately. Defined
    locally because google-auth is lazily imported and is not a test dependency.
    """


def test_poll_once_never_prints_a_foreign_exceptions_message(tmp_path, capsys):
    """The other half, and the one that must not regress: a FOREIGN exception.

    Its message is chosen by somebody else — here a credential-shaped value in
    a refresh failure — so it is named by type and nothing more (hard rule #2).
    """
    def cannot_mint(*_args, **_kwargs):
        raise _RefreshError(
            "invalid_grant fetching https://oauth2.googleapis.com/token"
            "?key=SECRETKEYVALUE&token=SECRETTOKENVALUE")

    adapter = ChatApiAdapter(cannot_mint, httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))))
    puller, reg, inbox, reply_fn = _loop(tmp_path, adapter.send_text)
    loop = SubscriberLoop(puller, reg, inbox, reply_fn=reply_fn)

    assert loop.poll_once() == 1          # still acked: no poison-pill wedge
    assert puller.acked == ["ack-0"]
    assert loop.dispatch_errors == 1
    out = capsys.readouterr().out
    assert "SECRETKEYVALUE" not in out
    assert "SECRETTOKENVALUE" not in out
    assert "oauth2.googleapis.com" not in out
    assert "invalid_grant" not in out
    assert out.strip().endswith(
        "subscriber: dispatch failed, event acked and dropped: _RefreshError")


def test_poll_once_never_prints_a_pydantic_validation_error_message(tmp_path, capsys):
    """The exact threat the comment above that line names, driven for real.

    `dispatch` builds an `InboundReply` outside any try, so a validation
    failure lands in poll_once — and pydantic embeds the offending
    `input_value` in its message. Here the offending value is a capability URL,
    which is what these events actually carry.
    """
    bad = {**CHAT_EVENT, "message": {**CHAT_EVENT["message"],
                                     "text": {"configCompleteRedirectUrl":
                                              "https://chat.google.com/?token=SECRETKEYVALUE"}}}
    p = tmp_path / "guarded.yaml"
    p.write_text(GUARDED_REGISTRY_YAML, encoding="utf-8")
    puller = _OneBatch([bad])
    loop = SubscriberLoop(puller, load_registry(p), Inbox())

    assert loop.poll_once() == 1
    assert loop.dispatch_errors == 1
    out = capsys.readouterr().out
    assert "SECRETKEYVALUE" not in out
    assert "input_value" not in out
    assert out.strip().endswith(
        "subscriber: dispatch failed, event acked and dropped: ValidationError")


def test_dispatch_unparseable_line_keeps_its_detail_through_the_shared_helper(
        tmp_path, capsys):
    """The other print site, unified onto `describe_exception` (CG-29).

    It already printed `UnrecognizedEventError` in full via its own inline
    `isinstance` ternary; the second copy of that ternary is what forgot the
    rule. Behaviour is unchanged and this says so.
    """
    p = tmp_path / "guarded.yaml"
    p.write_text(GUARDED_REGISTRY_YAML, encoding="utf-8")
    puller = _OneBatch([{"nothing": "recognizable",
                         "leaked": "https://chat.google.com/?token=SECRETKEYVALUE"}])
    loop = SubscriberLoop(puller, load_registry(p), Inbox())

    assert loop.poll_once() == 1
    assert loop.unparseable_seen == 1
    out = capsys.readouterr().out
    assert "UnrecognizedEventError: unrecognized Chat envelope" in out
    assert "'leaked'" in out and "'nothing'" in out        # field NAMES
    assert "SECRETKEYVALUE" not in out                     # never the VALUE


def test_healthz_last_poll_error_is_deliberately_not_describe_exception():
    """`_run` keeps its own format, and this pins why (CG-29).

    Two reasons, either sufficient: `PubSubError` is not marked, so
    `describe_exception` would drop the HTTP status — the one actionable fact
    in a poll failure — and `last_poll_error` is published at `/healthz`, which
    is unauthenticated, so its format is a surface rather than a log line.
    """
    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="denied")

    real = PubSubPuller("projects/p/subscriptions/s", lambda: "tok",
                        httpx.Client(transport=httpx.MockTransport(denied)))

    class _StopsAfterOne:
        """Runs `_run`'s body exactly once — the real 403 still comes from
        `PubSubPuller._post`, only the loop's continuation is short-circuited."""

        def pull(self, max_messages: int = 10):
            loop._stop.set()
            return real.pull(max_messages)

        def acknowledge(self, ack_ids):        # pragma: no cover - never reached
            real.acknowledge(ack_ids)

    loop = SubscriberLoop(_StopsAfterOne(), None, Inbox(), interval_seconds=0.001)
    loop._run()

    assert loop.poll_failures == 1
    assert loop.last_poll_error == "PubSubError HTTP 403"
    assert describe_exception(PubSubError("pull", 403, "Forbidden")) == "PubSubError"


def test_describe_exception_is_the_only_discriminator_left_in_the_subscriber():
    """No third hand-rolled copy of the rule (CG-29 is what the second one cost).

    Reads the source rather than trusting the diff. Scoped to `pubsub.py`,
    where both print sites live: every remaining `type(exc).__name__` in that
    module must sit inside `_run`, the one place the test above pins as
    deliberately different. Anywhere else it is somebody re-deriving the rule
    by hand, which is exactly how a print site ends up discarding a message it
    was allowed to show. (Elsewhere the same expression is legitimate — the
    adapters' raise sites BUILD messages out of it, and `describe_exception` is
    the rule itself.)
    """
    py = SRC / "adapters" / "pubsub.py"
    tree = ast.parse(py.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node

    scopes = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr == "__name__"
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "type"
                and [ast.unparse(a) for a in node.value.args] == ["exc"]):
            scopes.append(getattr(_enclosing_scope(node), "name", "<module>"))

    assert scopes == ["_run", "_run"], scopes      # the one ternary, and only it
