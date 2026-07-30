"""Which exception messages this gateway may print in full, and which it may not.

Hard rule #2 is the constraint and it is not abstract here: an exception
message is a value-carrying surface. A pydantic `ValidationError` embeds the
offending INPUT (`input_value=...`) and inbound events carry capability URLs;
an `httpx` transport error embeds the request URL, and a tier-1 webhook URL IS
a bearer credential with no rotate-in-place (`docs/google-cloud-setup.md` §8a).
So the gateway names exceptions by TYPE — and CG-23 went further, stripping
`resp.text[:200]` out of two adapters after a real 403 put a webhook's `key`
and `token` into three artifacts.

That rule also threw away something CG-25 had just paid for. `send_text()`
gained a typed transport error, so a failure arrives as `ChatApiError` rather
than a raw `httpx` exception — and `SubscriberLoop.poll_once`, printing
`type(exc).__name__` and discarding the message, collapsed two distinguishable
console lines into one at the exact point an operator reads them (CG-29).

**The discrimination is by type and it is an ALLOWLIST**, because the two
shapes fail in opposite directions. A denylist of known-unsafe types fails
OPEN — the next exception class nobody thought about prints in full, once.
An allowlist fails CLOSED — an unfamiliar exception prints a bare type name,
which is precisely what an operator got before this module existed. The cost
of failing closed is a less informative console line; the cost of failing open
is a credential, and only one of those can be undone.

**Membership is earned per class, not extended to everything this repo
defines**, and `PubSubError` is now the worked example of the earning rather
than of the exclusion. It was OUT under CG-29 for a property of `_post`, not of
the class: `_post` passed `httpx.Response.reason_phrase`, which httpcore fills
from the literal HTTP status line, so the message carried server-controlled
bytes — measured, and the opposite of what its own docstring claimed. CG-33
replaced that with a local `httpx.codes` lookup and the class joined the set.
What makes membership *checkable* rather than asserted is the structural guard
in `tests/test_error_surfaces.py`, which reads every construction site of every
marked class: joining the set is how a class's raise sites get enrolled in it,
and leaving the set is how they stop being read.
"""

from __future__ import annotations


class GatewayAuthoredError(Exception):
    """Marker: every byte of this exception's message was written in this repo.

    Not a behaviour and not a base for convenience — a *claim*, and the only
    claim that makes `describe_exception` safe: that the message is assembled
    from string literals this repo controls plus names and HTTP statuses, and
    that nothing from a response body, a request URL or an inbound payload
    VALUE is interpolated into it.

    Mix it in beside the concrete builtin (`class X(GatewayAuthoredError,
    RuntimeError)`) so existing `except RuntimeError` / `except ValueError`
    handlers keep working.

    A comment asserting the claim would rot the first time somebody adds
    `{resp.text}` to a message. `tests/test_error_surfaces.py` pins every raise
    site of every marked class as source text, so changing one — or adding a
    new one — turns the suite red and forces the author to look at exactly the
    string that `poll_once` is about to print.
    """


def describe_exception(exc: BaseException) -> str:
    """Name an exception for an operator, safely (hard rule #2).

    Marked → type name AND message. Anything else → type name alone. One
    function rather than a ternary per print site, because CG-29 is what two
    hand-rolled discriminations in one file look like when a third print site
    forgets there was a rule.
    """
    if isinstance(exc, GatewayAuthoredError):
        return f"{type(exc).__name__}: {exc}"
    return type(exc).__name__
