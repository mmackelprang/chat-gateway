"""Hard rule #2 guard: no fixture may carry a live secret or real identity.

This is a TEST, not a scrub script, and it walks the whole structure rather
than named paths — on 2026-07-29 a path-guess scrub missed a live token in
`configCompleteRedirectUri` and briefly wrote it to disk. Path guessing is the
failure mode; recursion is the fix.
"""

import json
import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# A value under one of these keys MUST be a placeholder.
SUSPECT_KEY = re.compile(r"token|secret|password|credential|redirecturi|redirecturl|api_?key", re.I)
# ...and any value that looks like an embedded credential is rejected wherever it sits.
SUSPECT_VALUE = re.compile(
    r"(token|secret|password|bearer|api[_-]?key)\s*[=:]\s*\S|BEGIN [A-Z ]*PRIVATE KEY", re.I
)
PLACEHOLDER = re.compile(r"<(SCRUBBED|REDACTED|FAKE)[^>]*>", re.I)
# Real identities that must never reach a public repo via a fixture.
# A real Google user id is a long digit string that never starts with 0;
# fixtures use zero-padded synthetic ids (users/000...001) precisely so this
# guard can tell them apart without a path allowlist. Chat spells the SAME id
# two ways — `users/<id>` and `spaces/X/members/<id>` — and a membership
# capture (CG-3) will carry the latter.
PII = re.compile(
    r"mackelprang|(?:users|members)/(?!0)\d{10,}|googleusercontent\.com", re.I)

# Tenant identifiers. A real Google domainId / customer id is an opaque
# alphanumeric string with no structure to key off — unlike a user id, there is
# no "never starts with 0" trick available. So the fixture side carries the
# marker instead: the value must contain `example`, which RFC 2606 reserves and
# a real Workspace tenant id cannot contain. Structural, not a path allowlist —
# same reason as the zero-padded user ids above.
#
# These arrived with the 2026-07-29 buttonClicked capture, which carries
# `chat.user.domainId` and `<space>.customer` (the latter TWICE — once under the
# payload, once inside the message's echoed space object). Nothing in the
# previous guard would have caught either.
TENANT_KEY = re.compile(r"\.(domainId|customer)$")

# Email addresses — the same structural trick as TENANT_KEY, and it is here
# because PII above catches this author's address by LITERAL NAME
# (`mackelprang`), which protects exactly one human. Every classic capture
# carries `user.email`, and jobhunt R4 is explicitly a MULTI-USER authorization
# feature, so the next capture may well carry somebody else's address — which
# the literal would sail straight past. An email IS structurally detectable, so
# fixtures must use an RFC 2606 reserved domain and the guard enforces it.
#
# A display NAME is deliberately given no rule: "Test User" and a real name are
# indistinguishable to a regex, and a list of real names in a public repo is a
# worse artifact than the problem. That limit is recorded in fixtures/README.md
# rather than papered over.
# EXAMPLE_DOMAIN is matched with fullmatch against the WHOLE address, not
# searched inside it: `someone@example.com.realcorp.net` contains `@example.com`
# followed by a `.`, which satisfies a trailing `\b`, so a search-based check
# would wave a real domain through on a suffix.
EMAIL = re.compile(r"[\w.+%-]+@[\w-]+(?:\.[\w-]+)+")
EXAMPLE_DOMAIN = re.compile(r"[\w.+%-]+@(?:[\w-]+\.)*example\.(?:com|org|net)", re.I)


def _walk(node, path="$"):
    """Yield (json_path, value) for every string leaf."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


def fixture_files():
    files = sorted(FIXTURES.rglob("*.json"))   # rglob: subdirectories count too
    assert files, "no fixtures found — this guard must never pass vacuously"
    return files


@pytest.mark.parametrize("path", fixture_files(), ids=lambda p: p.name)
def test_fixture_contains_no_secrets(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    for json_path, value in _walk(data):
        # Match the WHOLE path, not just the leaf key: a credential nested
        # under a suspect key ({"token": {"value": "ya29..."}}) would otherwise
        # be judged as the innocent key `value` and walk straight through.
        if SUSPECT_KEY.search(json_path) or SUSPECT_VALUE.search(value):
            assert PLACEHOLDER.search(value), (
                f"{path.name}{json_path} looks like a credential and is not "
                f"scrubbed to a <SCRUBBED>/<REDACTED> placeholder"
            )
        assert not PII.search(value), (
            f"{path.name}{json_path} carries a real identity ({value[:40]}...) — "
            "anonymize it; this repo is public"
        )
        for addr in EMAIL.findall(value):
            assert EXAMPLE_DOMAIN.fullmatch(addr), (
                f"{path.name}{json_path} carries a real-looking email address "
                f"({addr}) — fixtures must use an RFC 2606 `example.*` domain; "
                "this repo is public"
            )
        if TENANT_KEY.search(json_path):
            assert "example" in value.lower(), (
                f"{path.name}{json_path} = {value!r} looks like a real Google "
                "domain/customer id — fixtures must use an `example`-marked "
                "synthetic value (RFC 2606); this repo is public"
            )


def test_guard_rejects_unmarked_tenant_identifiers(tmp_path):
    """A guard that has never failed is a guard nobody has tested.

    Both spellings, because the buttonClicked capture carries both and a scrub
    that fixed only one would still ship a real tenant id. The second value is
    nested inside a LIST, because the capture echoes its space object twice and
    a rule that only matched top-level dict paths would sail past the copy.

    This calls `test_fixture_contains_no_secrets` itself rather than re-deriving
    its predicate. Re-deriving would pass even if the real assertion were
    inverted, mistyped, or deleted — proving something about a copy of the guard
    instead of the guard, which is how a scrub looks complete and is not.
    """
    cases = {
        "domainId": {"chat": {"user": {"domainId": "29vd573"}}},
        "customer": {"chat": {"spaces": [{"customer": "customers/C029vd573"}]}},
    }
    for key, payload in cases.items():
        bad = tmp_path / f"bad-{key}.json"
        bad.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(AssertionError, match="domain/customer id"):
            test_fixture_contains_no_secrets(bad)

    # ...and it must still PASS once the value carries the RFC 2606 marker,
    # so the guard is proven to discriminate rather than merely to reject.
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"chat": {"user": {"domainId": "example1"},
                                       "spaces": [{"customer": "customers/Cexample1"}]}}),
                  encoding="utf-8")
    test_fixture_contains_no_secrets(ok)


# The real shape, from the 2026-07-30 ADDED_TO_SPACE capture: a `token=` query
# parameter carrying a long opaque bearer value. The value below is INVENTED —
# a real one must never be committed, not even inside a test that rejects it.
CAPABILITY_URL_SHAPE = (
    "https://chat.google.com/api/bot_config_complete?token="
    "AAAAtestNotARealTokenAAAAtestNotARealTokenAAAAtestNotARealToken%3D%3D"
)


def test_guard_rejects_an_unscrubbed_capability_url(tmp_path):
    """DEC-7 has been a documented rule since CG-1 and was never proven to fire.

    The tenant rule above got a regression test because a scrub had already
    missed a tenant id. The capability-URL rule — which exists because a
    path-guess scrub wrote a LIVE token to disk, the worse of the two incidents —
    got none.

    Be precise about WHICH half was untested, because the tempting summary
    ("no real fixture had ever carried one") is false: `addon-message-event.json`
    is a REAL capture and has carried a scrubbed `configCompleteRedirectUri`
    since 2026-07-29, so the rule's PASS side has run on real bytes every test
    run since. What had zero tests was the REJECT side — nothing anywhere proved
    the rule actually fires on an unscrubbed value. That is the half this closes.

    Three cases, and the third is the one that isolates the rules from each
    other. Both spellings, because Google uses `...Uri` in the add-ons envelope
    and `...Url` in the classic one, and the classic one is the one that has now
    actually arrived. Calls the real guard, for the reason in the docstring
    above.
    """
    for key, payload in (
        ("configCompleteRedirectUrl",
         {"type": "ADDED_TO_SPACE", "configCompleteRedirectUrl": CAPABILITY_URL_SHAPE}),
        ("configCompleteRedirectUri",
         {"chat": {"messagePayload": {"configCompleteRedirectUri": CAPABILITY_URL_SHAPE}}}),
        # Token in the URL PATH, with no `token=` anywhere — so SUSPECT_VALUE
        # cannot see it and only SUSPECT_KEY's `redirecturi|redirecturl` arm can
        # catch it. Without this case, deleting that arm leaves the whole suite
        # green, because the two cases above are each caught twice over. It also
        # pins the contrapositive of the limit stated in fixtures/README.md:
        # a path-borne token passes only when the KEY is innocent too.
        ("path-token",
         {"configCompleteRedirectUrl":
          "https://chat.google.com/api/bot_config_complete/"
          "AAAAtestNotARealTokenAAAAtestNotARealToken"}),
    ):
        bad = tmp_path / f"bad-{key}.json"
        bad.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(AssertionError, match="looks like a credential"):
            test_fixture_contains_no_secrets(bad)

    ok = tmp_path / "ok-capability.json"
    ok.write_text(json.dumps({
        "configCompleteRedirectUrl":
            "https://chat.google.com/api/bot_config_complete?token=<SCRUBBED>"}),
        encoding="utf-8")
    test_fixture_contains_no_secrets(ok)


def test_guard_rejects_a_non_example_email_address(tmp_path):
    """The literal-name rule protects one human; this protects the next one.

    The second case is a free-text leaf rather than an `email` key, because an
    address can ride in message text and the guard keys off value shape, not
    field name.

    The third pins why EXAMPLE_DOMAIN is fullmatched rather than searched: an
    RFC 2606 domain used as a SUFFIX (`…@example.com.realcorp.net`) is a real
    domain wearing a reserved one as camouflage, and a substring search waves
    it through.
    """
    bad = tmp_path / "bad-email.json"
    bad.write_text(json.dumps(
        {"user": {"email": "someone@realcorp.io"},
         "message": {"text": "ping alice.smith@partner.co.uk about this"}}),
        encoding="utf-8")
    with pytest.raises(AssertionError, match="real-looking email"):
        test_fixture_contains_no_secrets(bad)

    suffixed = tmp_path / "bad-email-suffix.json"
    suffixed.write_text(json.dumps(
        {"user": {"email": "someone@example.com.realcorp.net"}}), encoding="utf-8")
    with pytest.raises(AssertionError, match="real-looking email"):
        test_fixture_contains_no_secrets(suffixed)

    ok = tmp_path / "ok-email.json"
    ok.write_text(json.dumps(
        {"user": {"email": "agent-user@example.com"},
         "message": {"text": "cc test@sub.example.org"}}), encoding="utf-8")
    test_fixture_contains_no_secrets(ok)
