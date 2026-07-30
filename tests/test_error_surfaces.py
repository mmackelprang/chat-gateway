"""What the gateway is allowed to PRINT about a failure (CG-29, hard rule #2).

Three things are pinned here, and they are three different kinds of claim:

1. **the membership of the marked set** — which exception classes claim
   `GatewayAuthoredError`, repo-wide, and (since CG-33) that `PubSubError` is
   one of them because the wire value it used to carry is gone;
2. **the messages those classes are built from** — a structural guard over
   every construction site, because the whole design rests on those
   constructors STAYING names-and-statuses-only, and a docstring saying so
   would rot;
3. **what `poll_once` actually prints** — the defect CG-29 was filed for, on
   the real R4 path, for a marked exception and for a foreign one.

**A marked class assembles its message in one of two shapes, and the guard in
part 2 reads both.** `ChatApiError(f"...")` takes the finished message as its
single argument, so the construction site IS the message. `PubSubError(verb,
status_code, reason)` takes three fields and builds the f-string inside
`__init__` — the literal text lives in the class and the values live at every
call site, so reading either half alone reads nothing useful. CG-33 is what
taught the guard the second shape; before that it would have reported
`PubSubError` as "expected exactly one message argument".

What is deliberately NOT re-tested here: that each individual message is clean
of response bytes. CG-23 already drives `webhook.send`, `chat_api.send` and
`chat_api.send_text` against hostile bodies and hostile status lines
(`test_webhook_error_names_the_identity_and_never_the_url`,
`test_reason_phrase_is_looked_up_locally_not_read_off_the_wire`,
`test_send_text_failure_strings_are_unchanged_by_cg_23` in `test_adapters.py`).
Those are the behavioural half; this file is the structural half, and its job is
the construction site those tests do not reach — including the one nobody has
written yet.
"""

import ast
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


_PARSED: dict[Path, ast.Module] = {}


def _tree(py: Path) -> ast.Module:
    """Parse each module once.

    Not premature: `_literal_parameters` re-reads the WHOLE package for every
    scope it is asked about, so the naive version parses the package's largest
    file a dozen times per test.
    """
    if py not in _PARSED:
        _PARSED[py] = ast.parse(py.read_text(encoding="utf-8"))
    return _PARSED[py]


# --------------------------------------------------------------------------
# 1. Who is in the set
# --------------------------------------------------------------------------

# Pinned by NAME and location. Adding a fifth is not forbidden — it is
# forbidden to add one silently, because membership is what entitles a message
# to be printed in full. `PubSubError` is the worked example of that being a
# deliberate act: CG-29 measured it out of the set, CG-33 removed the wire value
# that kept it out, and both edits had to come through this dict.
MARKED = {
    "ChatApiError": "adapters/chat_api.py",
    "PubSubError": "adapters/pubsub.py",
    "UnrecognizedEventError": "adapters/pubsub.py",
    "WebhookDeliveryError": "adapters/webhook.py",
}


def _declared_marked_classes() -> dict[str, str]:
    """Every class the marker reaches, TRANSITIVELY.

    Direct bases are not enough: `describe_exception` asks `isinstance`, which
    is MRO-aware, so `class ChatApiTimeoutError(ChatApiError)` is marked as
    surely as its parent — and a guard that only looked for a literal
    `GatewayAuthoredError` base would print that subclass's messages while
    reporting the set unchanged. Fixed point over the package's own
    inheritance graph.
    """
    classes = []
    for py in _modules():
        for node in ast.walk(_tree(py)):
            if isinstance(node, ast.ClassDef):
                bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
                classes.append((node.name, _rel(py), bases))

    found: dict[str, str] = {}
    reached = {"GatewayAuthoredError"}
    changed = True
    while changed:
        changed = False
        for name, module, bases in classes:
            if name not in found and bases & reached:
                found[name] = module
                reached.add(name)
                changed = True
    return found


def test_the_marked_set_is_exactly_these_four_classes():
    """Source-level, so a fifth cannot arrive by import-order accident.

    `GatewayAuthoredError.__subclasses__()` would only see classes some test
    happened to import; this reads every module in the package whether or not
    anything imports it.
    """
    assert _declared_marked_classes() == MARKED
    for cls in (ChatApiError, PubSubError, UnrecognizedEventError,
                WebhookDeliveryError):
        assert issubclass(cls, GatewayAuthoredError)
    # ...and the builtin stayed second, so existing handlers still catch these
    assert issubclass(ChatApiError, RuntimeError)
    assert issubclass(PubSubError, RuntimeError)
    assert issubclass(WebhookDeliveryError, RuntimeError)
    assert issubclass(UnrecognizedEventError, ValueError)


def test_pubsub_error_no_longer_carries_wire_bytes_which_is_why_it_is_marked():
    """The measurement that decides `PubSubError`'s membership, run both ways.

    This test used to assert the leak EXISTED. That was CG-29's whole point:
    `_post` passed `resp.reason_phrase`, httpcore fills
    `extensions["reason_phrase"]` from the literal HTTP/1.1 status line, so a
    server chose part of the message and the class could not be marked. The
    assertion was written to be UNCOMFORTABLE — CG-33's author had to come here
    and flip it by hand rather than inherit an assumption.

    It is flipped. `_post` looks the phrase up in `httpx.codes` (CG-23's fix,
    applied to the third adapter), so the same hostile status line is now
    discarded and the message is verb + status + a local-table phrase — which is
    what entitles `PubSubError` to the marker and to being printed in full.

    Still driven through the real `PubSubPuller._post`, deliberately: a
    hand-constructed `PubSubError("pull", 403, "Forbidden")` would pass this
    while the adapter kept handing the wire value in, which is exactly the
    defect. The exception has to come out of the code path under test.
    """
    smuggled = "Forbidden key=FAKEKEYVALUE&token=FAKETOKENVALUE"

    def hostile_status_line(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="denied",
                              extensions={"reason_phrase": smuggled.encode()})

    puller = PubSubPuller(
        "projects/p/subscriptions/s", lambda: "tok",
        httpx.Client(transport=httpx.MockTransport(hostile_status_line)),
    )
    with pytest.raises(PubSubError) as exc:
        puller.pull()

    assert "FAKETOKENVALUE" not in str(exc.value)
    # exact, not a substring check: "Forbidden" here is the LOCAL table's phrase
    # for 403 and not the wire's, and only an equality can tell those apart —
    # the hostile status line above starts with the same word on purpose.
    assert str(exc.value) == "pubsub pull failed: HTTP 403 Forbidden"
    # ...and the consequence, which is the half CG-33 actually changed
    assert isinstance(exc.value, GatewayAuthoredError)
    assert describe_exception(exc.value) == (
        "PubSubError: pubsub pull failed: HTTP 403 Forbidden")
    assert "FAKETOKENVALUE" not in describe_exception(exc.value)


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
# Compared by parsed AST (`_key`), not by source text. Both sides are parsed on
# the SAME interpreter, so `ast`'s cross-version formatting differences cancel —
# which matters at `requires-python = ">=3.10"` — and unlike normalizing the
# text there is no way for two different expressions to collide into one key.
APPROVED_INTERPOLATIONS = {
    "identity.name",                    # non-secret; registry.health() publishes it
    "resp.status_code",                 # an int
    "type(exc).__name__",               # a type name, by construction
    "type(event).__name__",
    "httpx.codes.get_reason_phrase(resp.status_code)",   # local table, never the wire
    "sorted(chat)[:10]",                # inbound field NAMES, never values
    "sorted(k for k in event if not k.startswith('_'))[:10]",
}

# `f"...".rstrip()` is the only wrapper any construction site uses. Listed
# rather than assumed so that `.format(resp.text)` — which would smuggle a
# value past a guard that only inspects f-string slots — is rejected as an
# unknown shape.
APPROVED_WRAPPERS = {"rstrip", "strip", "lstrip"}


def _key(node: ast.AST) -> str:
    """A structural identity for an expression. No formatting, no collisions."""
    return ast.dump(node)


APPROVED = {_key(ast.parse(t, mode="eval").body) for t in APPROVED_INTERPOLATIONS}


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


_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                  ast.ClassDef, ast.GeneratorExp, ast.ListComp, ast.SetComp,
                  ast.DictComp)


def _single_assignments(scope: ast.AST) -> dict[str, ast.AST]:
    """`name -> value node` for names bound exactly once in THIS lexical block.

    Two construction sites read a local `reason`; without this the guard could
    not tell `httpx.codes.get_reason_phrase(...)` (a local table) from
    `resp.reason_phrase` (the wire). Bound more than once → not resolvable →
    rejected, which is the safe direction.

    Nested functions, lambdas and comprehensions are NOT descended into: a name
    bound in an inner scope is a different binding, and resolving through one
    could attribute the wrong expression to the message in either direction.
    """
    seen: dict[str, list[ast.AST]] = {}

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Assign) and len(child.targets) == 1 and \
                    isinstance(child.targets[0], ast.Name):
                seen.setdefault(child.targets[0].id, []).append(child.value)
            if not isinstance(child, _NESTED_SCOPES):
                walk(child)

    walk(scope)
    return {k: v[0] for k, v in seen.items() if len(v) == 1}


def _parameters(scope: ast.AST) -> set[str]:
    """Every name `scope` binds as a parameter, `self` included."""
    if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return set()
    a = scope.args
    names = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
    if a.vararg:
        names.add(a.vararg.arg)
    if a.kwarg:
        names.add(a.kwarg.arg)
    return names


def _literal_parameters(scope: ast.AST, trees=None) -> dict[str, ast.AST]:
    """`param -> ast.Constant` for parameters that are a string LITERAL at every
    in-package call of `scope`.

    `_single_assignments` cannot see a parameter — nothing in the body assigns
    it — so `PubSubError(verb, ...)` inside `_post` had no resolvable expression
    at all, and the only way to green it would have been to approve the bare
    name `verb` in APPROVED_INTERPOLATIONS. That is a hole, not a shortcut: a
    bare name approved once matches any later `verb = resp.text` two frames up,
    and `_single_assignments` deliberately gives up on twice-bound names, so the
    unresolvable case and the approved case would be the same case. This
    resolves the parameter to what the CALLERS pass instead — `_post("pull",
    ...)` and `_post("acknowledge", ...)` make `verb` a literal; one
    `self._post(str(max_messages), ...)` makes it unresolvable and the slot is
    rejected.

    Matched by NAME, loose in the same way `_construction_sites` documents for
    class names: an unrelated `_post` on some other class is counted as a call
    here. **Both directions of that looseness fail SAFE.** A same-named function
    passing a non-literal only makes this STRICTER — the parameter stops
    resolving and the slot is rejected. And finding zero calls rejects too, so a
    function this guard cannot locate never resolves by default.

    That safety argument covers the name matching. It does NOT cover the scan
    scope, and the two must not be run together: `_modules()` walks
    `src/chat_gateway/` only, so "every in-package call" is only "every call"
    for a function nothing outside the package calls. **Restricted to
    underscore-private names for exactly that reason** — `_post` qualifies; a
    public method's callers live in consumer code this guard has never seen, and
    proving its parameter constant here would prove nothing about them. A
    non-private scope resolves nothing and its slots are rejected, which is the
    same safe direction as every other giving-up branch above. Widening this to
    public methods needs a different proof, not a bigger glob.

    `trees` overrides the package for the one test that drives this directly.
    The privacy rule is the only branch here with no observable effect on the
    real tree — `_post` is the sole scope that reaches it — so without a seam it
    would be a comment, and this file's whole argument is that comments rot.
    """
    positional = [a.arg for a in scope.args.posonlyargs + scope.args.args] \
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) else []
    if not positional or not scope.name.startswith("_"):
        return {}
    # A method is called as `x.<name>(...)` and its first parameter is bound by
    # the call itself, so every positional index shifts by one.
    is_method = positional[0] in ("self", "cls")

    calls = []
    for tree in (trees if trees is not None else [_tree(py) for py in _modules()]):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if is_method:
                if isinstance(node.func, ast.Attribute) and node.func.attr == scope.name:
                    calls.append(node)
            elif isinstance(node.func, ast.Name) and node.func.id == scope.name:
                calls.append(node)
    if not calls:
        return {}

    out: dict[str, ast.AST] = {}
    for index, name in enumerate(positional):
        if is_method and index == 0:
            continue
        pos = index - 1 if is_method else index
        literals = []
        for call in calls:
            if pos < len(call.args):
                arg = call.args[pos]          # ast.Starred lands here and fails
            else:
                arg = next((k.value for k in call.keywords if k.arg == name), None)
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                literals = None               # one non-literal caller is enough
                break
            literals.append(arg)
        if literals:
            out[name] = literals[0]
    return out


class _Scope:
    """The three ways a bare name inside one function becomes an expression.

    Built once per scope because `_literal_parameters` re-reads the package.
    """

    def __init__(self, node: ast.AST):
        self.name = getattr(node, "name", "<module>")
        self.assigned = _single_assignments(node)
        self.literal_params = _literal_parameters(node)
        self.params = _parameters(node)


def _unapproved(value: ast.AST, scope: _Scope) -> str | None:
    """Source text of `value` if it may not reach a printed message, else None."""
    if isinstance(value, ast.Name):
        resolved = scope.assigned.get(value.id)
        if resolved is None:
            resolved = scope.literal_params.get(value.id)
        if resolved is not None:
            value = resolved                  # `reason` -> what it was set to
        elif value.id in scope.params:
            return (f"{value.id} — a parameter of {scope.name}() that is not a "
                    f"string literal at every in-package call")
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return None       # a literal, no different from literal f-string text
    if _key(value) in APPROVED:
        return None
    return ast.unparse(value)


def _super_init_calls(init: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(init)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "__init__"
            and isinstance(n.func.value, ast.Call)
            and isinstance(n.func.value.func, ast.Name)
            and n.func.value.func.id == "super"]


def _message_assemblers() -> tuple[dict[str, dict], list[str]]:
    """The marked classes that build their own message, and their `__init__` half.

    The second of the two shapes described at the top of this file. For each
    marked class that defines `__init__`, the single `super().__init__(<expr>)`
    argument IS the message: its slots are checked here, and every slot that is
    a bare parameter name is recorded so the construction sites can be made to
    account for what they bind to it. A class with no `__init__` is not an
    assembler and keeps the original rule.
    """
    assemblers: dict[str, dict] = {}
    complaints: list[str] = []
    for py in _modules():
        for cls in ast.walk(_tree(py)):
            if not (isinstance(cls, ast.ClassDef) and cls.name in MARKED):
                continue
            inits = [n for n in cls.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == "__init__"]
            if not inits:
                continue
            init = inits[0]
            where = f"{_rel(py)}:{init.lineno} {cls.name}.__init__"
            calls = _super_init_calls(init)
            if len(calls) != 1:
                complaints.append(
                    f"{where}: expected exactly one super().__init__(...) call, "
                    f"found {len(calls)} — this guard reads the message there")
                continue
            call = calls[0]
            if len(call.args) != 1 or call.keywords:
                complaints.append(
                    f"{where}: expected exactly one message argument to "
                    f"super().__init__()")
                continue
            msg = _unwrap(call.args[0])
            if msg is None:
                complaints.append(
                    f"{where}: unrecognized message shape "
                    f"{ast.unparse(call.args[0])!r} — a literal, an f-string, or "
                    f"one of {sorted(APPROVED_WRAPPERS)} on either")
                continue

            positional = [a.arg for a in init.args.posonlyargs + init.args.args][1:]
            own = _parameters(init) - {"self"}
            scope, slot_params = _Scope(init), set()
            for slot in ast.walk(msg):
                if not isinstance(slot, ast.FormattedValue):
                    continue
                if isinstance(slot.value, ast.Name) and slot.value.id in own:
                    slot_params.add(slot.value.id)   # checked at every call site
                    continue
                bad = _unapproved(slot.value, scope)
                if bad is not None:
                    complaints.append(f"{where}: interpolates {bad!r}")
            assemblers[cls.name] = {"positional": positional,
                                    "slot_params": slot_params}
    return assemblers, complaints


def _bind(call: ast.Call, positional: list[str]) -> tuple[dict[str, ast.AST], str | None]:
    """Call arguments -> parameter names (`self` already dropped), or a complaint.

    `*args` / `**kwargs` at a construction site defeat this. They are a
    complaint rather than a pass: a guard that goes quiet on a shape it cannot
    read is worse than no guard, because it still looks green.
    """
    bound: dict[str, ast.AST] = {}
    for i, arg in enumerate(call.args):
        if isinstance(arg, ast.Starred):
            return {}, "passes *args, which this guard cannot bind to parameters"
        if i >= len(positional):
            return {}, (f"passes {len(call.args)} positional arguments to a "
                        f"constructor taking {len(positional)}")
        bound[positional[i]] = arg
    for kw in call.keywords:
        if kw.arg is None:
            return {}, "passes **kwargs, which this guard cannot bind to parameters"
        bound[kw.arg] = kw.value
    return bound, None


def _construction_sites():
    """Every `<marked class>(...)` CALL in the package, wherever it appears.

    Construction sites, not `raise` statements: `err = ChatApiError(f"...")`
    followed by `raise err` builds exactly the same message and `poll_once`
    prints exactly the same string, but the `raise` node's `.exc` is a bare
    Name and a raise-shaped guard would never look at it. The message is made
    at construction, so that is what gets read.

    Matched by class NAME. An import alias would slip past — noted rather than
    defended against, because nothing in this repo aliases an exception import
    and the guard would have to become a type checker to catch it.
    """
    for py in _modules():
        tree = _tree(py)
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                child.parent = node
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in MARKED):
                yield _rel(py), node.lineno, node


def test_every_marked_message_interpolates_only_names_and_statuses():
    """The test the design asks for instead of a comment.

    `poll_once` prints these messages in full. That is only safe while every
    one of them is assembled from literals plus the expressions in
    APPROVED_INTERPOLATIONS — a property of the construction sites, not of the
    classes, and therefore one that a future edit can quietly remove. This
    reads them.

    Both assembly shapes (see this file's docstring). For a class whose
    `__init__` builds the message, the f-string's slots are read inside
    `__init__` AND every construction site is made to account for what it binds
    to each parameter that reaches one — because half of `PubSubError`'s message
    is chosen three call frames away from the class that owns the literal text.
    """
    assemblers, complaints = _message_assemblers()
    for module, lineno, call in _construction_sites():
        where = f"{module}:{lineno} {call.func.id}"
        scope = _Scope(_enclosing_scope(call))
        spec = assemblers.get(call.func.id)

        if spec is None:
            # Shape 1: the construction site IS the message.
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
            for slot in ast.walk(msg):
                if not isinstance(slot, ast.FormattedValue):
                    continue
                bad = _unapproved(slot.value, scope)
                if bad is not None:
                    complaints.append(f"{where}: interpolates {bad!r}")
            continue

        # Shape 2: the class assembles it; this site supplies the values.
        bound, shape = _bind(call, spec["positional"])
        if shape is not None:
            complaints.append(f"{where}: {shape}")
            continue
        for param in sorted(spec["slot_params"]):
            if param not in bound:
                complaints.append(
                    f"{where}: does not bind {param!r}, which reaches the "
                    f"message — a constructor default is not readable from here")
                continue
            bad = _unapproved(bound[param], scope)
            if bad is not None:
                complaints.append(f"{where}: binds {param}={bad!r}")

    assert not complaints, (
        "A gateway-authored exception message changed shape.\n\n"
        + "\n".join(f"  - {c}" for c in complaints)
        + "\n\nSubscriberLoop.poll_once PRINTS these in full (CG-29). Confirm "
          "the new expression carries a NAME or an HTTP STATUS and never a "
          "response body, a request URL or an inbound payload value (hard rule "
          "#2), then add it to APPROVED_INTERPOLATIONS. If it carries a value, "
          "the fix is the construction site, not this list.\n\n"
          "A 'binds x=...' complaint is the second message shape: the class "
          "builds its own f-string in __init__ and this call site chose what "
          "goes in a slot, so the fix is here even though the literal text is "
          "in the class. A 'not a string literal at every in-package call' "
          "complaint means a parameter stopped being constant — some CALLER of "
          "the enclosing function now passes an expression, and that expression "
          "is what would reach the message.")


def test_the_guard_above_actually_finds_the_construction_sites():
    """A guard that inspects nothing passes everything.

    Pins the count so a refactor that moves these behind a factory cannot
    silently empty the guard while leaving it green.
    """
    per_class: dict[str, int] = {}
    for _, _, call in _construction_sites():
        per_class[call.func.id] = per_class.get(call.func.id, 0) + 1
    assert per_class == {
        "ChatApiError": 5, "PubSubError": 1, "UnrecognizedEventError": 4,
        "WebhookDeliveryError": 2,
    }


def test_a_parameter_only_resolves_for_a_scope_whose_callers_are_all_in_package():
    """`_literal_parameters` proves a parameter constant by reading its CALLERS.

    That proof is only as wide as the scan, and the scan is `src/chat_gateway/`.
    For an underscore-private function that is the whole population; for a
    public one the callers that matter are in consumer code nobody here has
    read, so the same evidence proves nothing and the parameter must not
    resolve. Identical sources but for the leading underscore, so the underscore
    is demonstrably what decides it — and `verb` is checked on the real `_post`
    as well, because a rule that only ever fires on a synthetic tree is not
    known to fire at all.
    """
    def scope_of(src, name):
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        return fn, [tree]

    private, trees = scope_of(
        "class C:\n"
        "    def _helper(self, verb): pass\n"
        "    def go(self): self._helper('pull')\n", "_helper")
    assert "verb" in _literal_parameters(private, trees)

    public, trees = scope_of(
        "class C:\n"
        "    def helper(self, verb): pass\n"
        "    def go(self): self.helper('pull')\n", "helper")
    assert _literal_parameters(public, trees) == {}

    # ...and one non-literal caller is enough to un-resolve the private case
    mixed, trees = scope_of(
        "class C:\n"
        "    def _helper(self, verb): pass\n"
        "    def go(self, x): self._helper('pull'); self._helper(x)\n", "_helper")
    assert _literal_parameters(mixed, trees) == {}

    # the real one, so this is not purely a test of synthetic input
    post = next(n for n in ast.walk(_tree(SRC / "adapters" / "pubsub.py"))
                if isinstance(n, ast.FunctionDef) and n.name == "_post")
    assert sorted(_literal_parameters(post)) == ["verb"]


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
    """`_run` keeps its own format, and this pins why (CG-29, narrowed by CG-33).

    ONE reason now, and it is sufficient alone: `last_poll_error` is published
    at `/healthz`, `/healthz` is unauthenticated, and its audience is not the
    console's — so the field format is a published surface rather than a log
    line, pinned as an exact string in `test_adapters.py` and `test_service.py`.

    CG-29 gave a second reason and CG-33 removed it. That one was "`PubSubError`
    is unmarked, so `describe_exception` would drop the HTTP status"; the class
    is marked now and the helper renders it in full, status included. The last
    line below is that format — asserted so the contrast is explicit: it is a
    perfectly good console line and `_run` still deliberately does not use it.
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
    # the format `_run` deliberately does NOT use — not a fallback, a choice
    assert describe_exception(PubSubError("pull", 403, "Forbidden")) == (
        "PubSubError: pubsub pull failed: HTTP 403 Forbidden")


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
