"""CG-34 — hard rule #2 in the logging path.

`httpx` logs the whole request URL on EVERY request, success included, and a
tier-1 webhook URL embeds `key` and `token`. These tests drive a real
`WebhookAdapter` with a real `httpx.Client` over real TCP, at
`logging.basicConfig(level=logging.DEBUG)` — the config the queue row names as
one line away — and assert the credential appears in NO emitted record.

Three deliberate choices about the evidence:

* The assertions run over records from EVERY logger, not just `httpx`. Only the
  `httpx` INFO line was observed to carry the URL (13 records, one leak); that is
  a measurement of httpcore 1.0.9 rather than a law, so if a future httpcore
  starts emitting the target these tests fail and name it.
* They assert on the RENDERED stream a `StreamHandler` produced, not only on
  LogRecord internals — the artifact an operator would actually see.
* One test deliberately removes the guard and asserts the credential IS present,
  so the suite proves these tests can detect the leak rather than passing
  vacuously.

Credential values here are obviously fake and belong to no webhook.
"""

import http.server
import io
import json
import logging
import threading

import httpx
import pytest

from chat_gateway.adapters.webhook import WebhookAdapter
from chat_gateway.envelope import OutboundMessage
from chat_gateway.log_redaction import (
    REDACTED, RedactUrlCredentials, install_url_redaction, redact_url,
)
from chat_gateway.registry import Identity

KEY = "SECRETKEYVALUE"
TOKEN = "SECRETTOKENVALUE"
MSG = OutboundMessage(identity="pm", text="Review needed", thread_key="review-1")


# --- a real HTTP server, so the whole client stack runs -----------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        body = b'{"name": "spaces/A/messages/1"}'
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass          # the stdlib server's own stderr logging is not under test


@pytest.fixture
def local_google():
    """A stand-in for Google on 127.0.0.1, so httpx really opens a socket.

    MockTransport would exercise the `httpx` log line but not httpcore's, and
    httpcore's traces are half of what this item claims to have checked.
    """
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def dangerous_logging():
    """`logging.basicConfig(level=DEBUG)` — the real call, faithfully.

    `force=True` because the suite already has root handlers and `basicConfig`
    is otherwise a silent no-op; the point is to reproduce what an operator gets
    when they add that line, not an approximation of it. Root's handlers and
    level are snapshotted and restored so the rest of the session is unaffected.

    Also strips any already-installed guard, because these tests must prove that
    the code under test installs one — the `httpx` logger is global and another
    test constructing a `WebhookAdapter` would otherwise arm it for us.
    """
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    httpx_logger = logging.getLogger("httpx")
    saved_filters = httpx_logger.filters[:]
    httpx_logger.filters = [
        f for f in httpx_logger.filters if not isinstance(f, RedactUrlCredentials)
    ]

    stream = io.StringIO()
    logging.basicConfig(level=logging.DEBUG, stream=stream, force=True)
    capture = _Capture()
    root.addHandler(capture)
    try:
        yield stream, capture
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        httpx_logger.filters = saved_filters


def _send(base_url: str, monkeypatch, adapter: WebhookAdapter | None = None):
    monkeypatch.setenv("HOOK", f"{base_url}/v1/spaces/AAA/messages?key={KEY}&token={TOKEN}")
    ident = Identity(name="pm", display="PM", webhook_url_env="HOOK")
    return (adapter or WebhookAdapter()).send(ident, MSG)


# --- the load-bearing test ----------------------------------------------------


def test_no_emitted_log_record_carries_the_webhook_credential(
    local_google, dangerous_logging, monkeypatch
):
    """The whole item, end to end: real adapter, real socket, DEBUG everywhere.

    Note the response is a 200. This fires on the HAPPY path — unlike CG-23's
    error-body leak it would have published the credential on every notification
    the gateway ever sent, which is why it was prioritised over the noisier but
    rarer failure paths.
    """
    stream, capture = dangerous_logging

    result = _send(local_google, monkeypatch)
    assert result.status == "delivered"          # the send still works

    rendered = stream.getvalue()
    messages = [r.getMessage() for r in capture.records]

    # The credential first, deliberately — as in CG-23's tests, the assertion
    # whose failure must name the leak goes ahead of the ones about formatting.
    assert KEY not in rendered
    assert TOKEN not in rendered
    for message in messages:
        assert KEY not in message, f"credential leaked via logger record: {message}"
        assert TOKEN not in message, f"credential leaked via logger record: {message}"

    # ...and this held across every logger, not only httpx's. httpcore's DEBUG
    # traces are in here too; that they carry no URL is measured, not assumed.
    assert len(capture.records) > 5, "DEBUG did not actually take effect"
    assert any(r.name.startswith("httpcore") for r in capture.records)


def test_the_redacted_line_is_still_worth_reading(
    local_google, dangerous_logging, monkeypatch
):
    """Redaction, not silencing — this is the difference from the rejected option.

    An operator who deliberately set DEBUG keeps method, scheme, host, path,
    status and the parameter NAMES. They lose only values. If this fix is ever
    swapped for `getLogger("httpx").setLevel(WARNING)`, this test fails, which
    is the point: that alternative silently removes an operator's diagnostics
    without telling them.
    """
    stream, _ = dangerous_logging
    _send(local_google, monkeypatch)
    line = next(ln for ln in stream.getvalue().splitlines() if "HTTP Request" in ln)

    assert "POST" in line and "127.0.0.1" in line
    assert "/v1/spaces/AAA/messages" in line          # path survives: it is not secret
    assert '200 OK"' in line                         # so does the status
    assert f"key={REDACTED}" in line and f"token={REDACTED}" in line

    # The collateral, pinned rather than left implicit: our own non-secret
    # parameter is redacted too, because the rule is on VALUES and not on a
    # denylist of parameter names. A change to name-matching fails here.
    assert f"messageReplyOption={REDACTED}" in line
    assert "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD" not in line


def test_the_test_above_can_actually_detect_the_leak(
    local_google, dangerous_logging, monkeypatch
):
    """The mutation, kept in the suite instead of being done once by hand.

    With the guard removed from the `httpx` logger the credential is right there
    in the rendered output — both halves of it. Without this, the assertions
    above would pass just as happily against a gateway that never made the
    request at all.
    """
    stream, _ = dangerous_logging
    adapter = WebhookAdapter()
    logging.getLogger("httpx").filters = [
        f for f in logging.getLogger("httpx").filters
        if not isinstance(f, RedactUrlCredentials)
    ]

    _send(local_google, monkeypatch, adapter=adapter)

    rendered = stream.getvalue()
    assert KEY in rendered and TOKEN in rendered
    assert "HTTP Request: POST" in rendered


def test_a_tenant_callback_url_is_covered_by_the_same_guard(
    local_google, dangerous_logging, monkeypatch
):
    """Not a webhook, and that is the point.

    `forwarder.py` POSTs to tenant `callback_url`s through an `httpx.Client` —
    the same module-level logger — and the gateway does not control that URL's
    shape. A credential there could sit under any parameter name at all, which
    is the concrete reason the redaction is on values rather than on a `key`/
    `token` denylist. Exercised through a plain `httpx.Client` rather than
    `CallbackForwarder` itself: what is under test is the shared logging path,
    not the forwarder's own retry machinery.
    """
    stream, _ = dangerous_logging
    install_url_redaction()

    client = httpx.Client(timeout=5)
    resp = client.post(
        f"{local_google}/hooks/inbound?access_token={TOKEN}&sig={KEY}",
        json={"dedupe_key": "d-1"},
    )
    assert resp.status_code == 200

    rendered = stream.getvalue()
    assert TOKEN not in rendered and KEY not in rendered
    assert f"access_token={REDACTED}" in rendered and f"sig={REDACTED}" in rendered
    assert "/hooks/inbound" in rendered


# --- the redaction rule itself ------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        # the shape this item exists for
        ("https://chat.googleapis.com/v1/spaces/A/messages?key=K&token=T",
         f"https://chat.googleapis.com/v1/spaces/A/messages?key={REDACTED}&token={REDACTED}"),
        # no query: untouched, so a chat_api or pubsub URL is fully readable
        ("https://chat.googleapis.com/v1/spaces/AAA/messages",
         "https://chat.googleapis.com/v1/spaces/AAA/messages"),
        ("https://pubsub.googleapis.com/v1/projects/p/subscriptions/s:pull",
         "https://pubsub.googleapis.com/v1/projects/p/subscriptions/s:pull"),
        # a valueless parameter keeps its name and gains no bogus `=`
        ("https://h/p?flag&key=K", f"https://h/p?flag&key={REDACTED}"),
        # a fragment is not swallowed into the last value
        ("https://h/p?key=K#frag", f"https://h/p?key={REDACTED}#frag"),
        # userinfo: `str(httpx.URL)` emits the password in full — only `repr`
        # masks it, and httpx logs with %s
        ("https://user:hunter2@h/p", f"https://user:{REDACTED}@h/p"),
        ("https://user@h/p?key=K", f"https://user@h/p?key={REDACTED}"),
        # not a URL at all
        ("just some text", "just some text"),
        ("spaces/AAA/messages/1", "spaces/AAA/messages/1"),
    ],
)
def test_redact_url_rule(url, expected):
    assert redact_url(url) == expected


def test_a_credential_in_the_PATH_is_out_of_scope_and_says_so():
    """The named residue, pinned so it stays a decision rather than a surprise.

    Redacting path segments would destroy the diagnostic the redaction exists to
    preserve — `/v1/spaces/AAA/messages` is the most useful thing in the line —
    and no URL the gateway constructs carries a secret there. A tenant
    `callback_url` could. Recorded in `log_redaction`'s docstring and here.
    """
    assert redact_url("https://host/hooks/s3cr3t") == "https://host/hooks/s3cr3t"


# --- the filter's own behaviour ----------------------------------------------


def test_install_is_idempotent():
    logger = logging.getLogger("cg34-idempotence-probe")
    logger.filters = []
    assert install_url_redaction(logger.name) is True
    assert install_url_redaction(logger.name) is False
    assert sum(isinstance(f, RedactUrlCredentials) for f in logger.filters) == 1
    logger.filters = []


def test_the_filter_fails_CLOSED_and_never_raises_into_the_caller():
    """If it cannot redact, the record is dropped — not passed through, not raised.

    Passing through would leak the credential this exists to protect. Raising
    would be worse: a logger's filters run inside the caller's `logger.info(...)`
    call, so an exception here would propagate into `httpx._client` and break the
    send itself. Losing one diagnostic line is the only acceptable failure.
    """
    class Hostile:
        def __str__(self):
            raise RuntimeError("boom")

    record = logging.LogRecord(
        "httpx", logging.INFO, __file__, 1, "HTTP Request: %s", (Hostile(),), None
    )
    assert RedactUrlCredentials().filter(record) is False


def test_the_filter_leaves_an_unrelated_record_alone():
    """It rewrites URLs, not messages. A `%d` slot keeps its int, so the
    format string still renders — replacing every arg with a string would
    have broken httpx's own `%d` status slot."""
    record = logging.LogRecord(
        "httpx", logging.INFO, __file__, 1,
        'HTTP Request: %s %s "%s %d %s"',
        ("POST", httpx.URL(f"https://h/p?key={KEY}"), "HTTP/1.1", 200, "OK"), None,
    )
    assert RedactUrlCredentials().filter(record) is True
    assert record.getMessage() == (
        f'HTTP Request: POST https://h/p?key={REDACTED} "HTTP/1.1 200 OK"'
    )


def test_a_preformatted_message_is_covered_too():
    """The version-drift hedge. httpx passes the URL as a lazy `%s` argument
    today; if a future httpx interpolates it into the message instead, the fix
    must not silently stop working. This is the branch that catches that."""
    record = logging.LogRecord(
        "httpx", logging.INFO, __file__, 1,
        f'HTTP Request: POST https://h/p?key={KEY}&token={TOKEN} "HTTP/1.1 200 OK"',
        None, None,
    )
    assert RedactUrlCredentials().filter(record) is True
    message = record.getMessage()
    assert KEY not in message and TOKEN not in message
    assert message.endswith('"HTTP/1.1 200 OK"')      # the regex stopped at the quote


def test_the_guard_survives_a_dictConfig_that_reconfigures_logging():
    """`dictConfig` clears a logger's HANDLERS, never its filters — which is why
    this is a logger-level filter and not a handler-level one. uvicorn applies
    exactly such a config at `run()`, after `__main__` has armed the guard."""
    import logging.config

    logger = logging.getLogger("cg34-dictconfig-probe")
    logger.filters = []
    install_url_redaction(logger.name)
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"h": {"class": "logging.NullHandler"}},
        "loggers": {logger.name: {"handlers": ["h"], "level": "DEBUG"}},
    })
    assert any(isinstance(f, RedactUrlCredentials) for f in logger.filters)
    logger.filters = []


def test_json_body_is_not_in_the_logging_path_at_all(local_google, dangerous_logging, monkeypatch):
    """Scope check, so a reader does not assume more than was fixed.

    httpx logs method, URL, version, status and reason phrase — never bodies or
    headers. The message text is therefore not in these records either, before
    or after this change, and this fix makes no claim about it.
    """
    stream, _ = dangerous_logging
    _send(local_google, monkeypatch)
    rendered = stream.getvalue()
    assert "Review needed" not in rendered
    assert json.dumps({"text": "Review needed"}) not in rendered
