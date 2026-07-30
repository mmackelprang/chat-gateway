"""Hard rule #2, enforced in the logging path: no credential-bearing URL is
ever emitted as a log record, whatever level the operator asked for.

WHY THIS EXISTS. `httpx` logs one line per request — success or failure — via a
module-level logger:

    logger.info('HTTP Request: %s %s "%s %d %s"', request.method, request.url, ...)

and `request.url` for a tier-1 send is the webhook URL, which embeds `key` AND
`token`. That URL IS a bearer credential for posting as that identity, and there
is no rotate-in-place: recovery is delete-and-recreate the webhook by hand in the
Chat UI. `docs/google-cloud-setup.md` §8a exists because one leaked already.

Unlike an error body, this fires on the HAPPY PATH — it would leak on every
notification the gateway ever sends, not only on failures.

It is not a leak in the default deployment: the root logger defaults to WARNING
and uvicorn's LOGGING_CONFIG configures only `uvicorn`, `uvicorn.error` and
`uvicorn.access`, never root, so the record is created and dropped. That defence
is one line deep. `logging.basicConfig(level=logging.INFO)` — the single most
common thing a Python service does when someone wants request logs — publishes
it. A guarantee that holds only until somebody adds a config line is not a
guarantee, which is why this is code and not a paragraph in the deploy doc.

WHAT IT DOES, AND WHAT IT DELIBERATELY DOES NOT DO. It redacts; it does not
silence. A `logging.Filter` on the `httpx` logger rewrites every URL in the
record so that query-parameter VALUES and any userinfo password become
`REDACTED`, and leaves everything else — method, scheme, host, path, status,
parameter NAMES — intact:

    HTTP Request: POST https://chat.googleapis.com/v1/spaces/A/messages
                  ?key=REDACTED&token=REDACTED&messageReplyOption=REDACTED
                  "HTTP/1.1 200 OK"

The rejected alternative was `getLogger("httpx").setLevel(WARNING)`. It is
cheaper and it works, but it silently fights an operator who deliberately asked
for DEBUG: they get no httpx logs and no explanation for their absence. It also
costs more than the problem requires — only the webhook URL carries a
credential; a `chat_api` URL carries a space id and a `pubsub` URL a subscription
name, both non-secret and both genuinely useful in a log. Redaction defends by
default AND leaves a deliberate operator their diagnostics.

VALUES, NOT NAMED PARAMETERS. Redacting only `key` and `token` would be a
denylist of secrets, and denylists of secrets fail open — the parameter this
repo has not thought of yet is exactly the one that leaks. Every query value
goes instead, and the measured cost of that is nil: the only query parameter the
gateway itself sends is `messageReplyOption`, a constant of our own choosing.
The generality is load-bearing rather than tidy, because the `httpx` logger also
carries `forwarder.py`'s POSTs to tenant `callback_url`s, whose shape the
gateway does not control and which may embed a credential under any name at all.

THE FRAGMENT COUNTS, and the first draft of this file got that wrong — it is
recorded rather than quietly corrected, because the mistake is the instructive
part. `?key=K#token=SECRET` came back as `?key=REDACTED#token=SECRET`: the
denylist argument above had been taken to heart for parameter NAMES and then not
applied to parameter LOCATION. It is a live shape rather than a hypothetical one
— an OAuth implicit-flow callback puts its token after the `#`, `httpx` really
does log the fragment (`str(request.url)` keeps it, verified), and a tenant
`callback_url` is exactly the unvalidated string that could be shaped that way.
Query and fragment are now redacted by the same rule. A fragment that is an
ordinary anchor has no `=` in it and passes through untouched.

The filter never needs to know what the secret IS. It holds no env var, reads no
registry, and compares against nothing — it redacts by POSITION in the URL, so
there is no path by which arming this guard puts a credential anywhere new.

SCOPE LINE, STATED RATHER THAN LEFT TO BE DISCOVERED. A credential embedded in a
URL *path* (`https://host/hooks/s3cr3t`) is NOT covered. Redacting paths would
destroy the diagnostic the redaction exists to preserve — `/v1/spaces/A/messages`
is the most useful thing in the line — and no URL the gateway constructs is
shaped that way. A tenant `callback_url` could be; that is a residue, it is the
ONLY residue in a URL's structure once query, fragment and userinfo are covered,
and it is named here rather than implied to be handled.

WHAT IS AND IS NOT FILTERED, MEASURED RATHER THAN ASSUMED. Driving a real
`WebhookAdapter` over real TCP at `basicConfig(level=DEBUG)` produced 13 records
and exactly ONE carried the credential: the `httpx` INFO line. `httpcore`'s DEBUG
traces do not carry it — a request appears as `<Request [b'POST']>` (method
only), `connect_tcp.started` carries host and port, and the header trace is of
the RESPONSE headers. So this filter is installed on the `httpx` logger and
nowhere else, deliberately. That is an observation about httpcore 1.0.9, not a
law, so `tests/test_log_redaction.py` asserts over records from EVERY logger, not
only httpx's: if a future httpcore starts emitting the target, the test fails and
names it rather than the guard quietly missing it.

A logger-level filter, not a handler-level one, and that is the mechanism that
makes it survive: `Logger.handle` runs the logger's own filters before any
handler is consulted, and ancestor handlers reached by propagation receive the
record this filter already rewrote. `basicConfig` and `dictConfig` both install
HANDLERS; neither removes a filter attached to a logger (`dictConfig` clears a
logger's handlers, never its filters). It can still be defeated by someone who
explicitly calls `removeFilter`, or who logs a webhook URL through some other
logger of their own — this closes the path the library takes, not every path
that exists.

There is deliberately NO env var to switch this off. Hard rule #2 has no
exceptions, and a flag that disables credential redaction is a footgun whose
best case is that nobody finds it.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit, urlunsplit

REDACTED = "REDACTED"

HTTPX_LOGGER = "httpx"

# Fallback only. httpx passes the URL as a lazy `%s` ARGUMENT today, so this
# never matches in practice — it exists so that an httpx that pre-formats its
# message is still covered rather than silently un-fixed. Excludes quotes and
# angle brackets so it stops at the closing quote of `... "HTTP/1.1 200 OK"`.
_URL_IN_TEXT = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s\"'<>]+")


def _redact_pairs(text: str) -> str:
    """Blank the value of every `name=value` pair, keeping the names.

    Names survive so a reader still sees THAT a `token` was sent and can tell a
    two-parameter URL from a three-parameter one. Anything with no `=` is left
    alone, which is what makes this safe to run over a fragment as well as a
    query: an ordinary anchor (`#results`, `#/route`) passes through untouched.

    Split by hand rather than through `urllib.parse.parse_qsl`, which drops
    parameters with empty values, percent-decodes what it returns, and would
    have this function re-encoding parts of a URL it has no business rewriting.
    """
    if not text:
        return text
    out = []
    for pair in text.split("&"):
        name, equals, _value = pair.partition("=")
        out.append(f"{name}={REDACTED}" if equals else name)
    return "&".join(out)


def redact_url(url: str) -> str:
    """Blank every query and fragment value, and any userinfo password.

    `urlsplit` rather than hand-rolled `partition` calls, because the ordering
    rules are the whole problem: RFC 3986 delimits the fragment at the FIRST
    `#` and the query only within what remains, and an authority ends at the
    first of `/`, `?` or `#`. Hand-rolling those got two shapes wrong —
    `?key=K#token=SECRET` left the fragment intact, and `https://host?key=K`
    (a query with no path) was not redacted at all, because the authority was
    taken as everything up to the first `/`. `urlsplit` also handles the IPv6
    literal authority that any such hand-rolled split mangles.

    `urlsplit` can raise on a malformed authority. That is deliberate here: the
    filter's `except` drops the record, so an unparseable URL costs a log line
    rather than leaking one.
    """
    if "://" not in url:
        return url
    parts = urlsplit(url)
    netloc = parts.netloc
    if "@" in netloc:
        userinfo, _, host = netloc.rpartition("@")
        user, has_password, _password = userinfo.partition(":")
        netloc = f"{user}:{REDACTED}@{host}" if has_password else f"{userinfo}@{host}"
    return urlunsplit((
        parts.scheme, netloc, parts.path,
        _redact_pairs(parts.query), _redact_pairs(parts.fragment),
    ))


def _redact_text(text: str) -> str:
    return _URL_IN_TEXT.sub(lambda m: redact_url(m.group(0)), text)


def _redact_arg(value: object) -> object:
    """Redact one `record.args` element, preserving its type where it matters.

    A non-string is only replaced when its `str()` contains a URL, so the `%d`
    slot in httpx's format string keeps its int and does not become a string
    that `%d` cannot render.
    """
    if isinstance(value, str):
        return _redact_text(value) if "://" in value else value
    text = str(value)
    return redact_url(text) if "://" in text else value


class RedactUrlCredentials(logging.Filter):
    """Rewrite URLs in a LogRecord in place; drop the record if that fails.

    Mutating the record is the documented use of a filter, and it is what makes
    every downstream handler see the redacted form rather than each having to
    redact for itself.

    The `except` returns False — the record is DISCARDED, not passed through.
    Failing open would leak the credential this exists to protect; failing loud
    (letting the exception escape) would be worse still, because a logger's
    filters run inside the caller's `logger.info(...)` call, so a raise here
    would propagate into `httpx._client` and break the send itself. Losing one
    diagnostic line is the only acceptable failure mode of the three.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str) and "://" in record.msg:
                record.msg = _redact_text(record.msg)
            if isinstance(record.args, tuple):
                record.args = tuple(_redact_arg(a) for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: _redact_arg(v) for k, v in record.args.items()}
        except Exception:
            return False
        return True


def install_url_redaction(logger_name: str = HTTPX_LOGGER) -> bool:
    """Arm the guard on `logger_name`. Idempotent; returns whether it installed.

    Called from `__main__.build_runtime` so the service is covered before it can
    make a request, and from `WebhookAdapter.__init__` so that CONSTRUCTING the
    object that resolves a webhook URL arms the guard — in tests, and in the
    ad-hoc verification scripts that are how this leak was found in the first
    place. Neither of those goes through the entrypoint.

    Deliberately NOT `client.py`, despite the name: that module is the gateway's
    HTTP client for consumers, it speaks to the gateway rather than to Google,
    and it is `urllib`-based, so it never touches the `httpx` logger at all.
    """
    logger = logging.getLogger(logger_name)
    if any(isinstance(f, RedactUrlCredentials) for f in logger.filters):
        return False
    logger.addFilter(RedactUrlCredentials())
    return True
