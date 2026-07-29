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
        if TENANT_KEY.search(json_path):
            assert "example" in value.lower(), (
                f"{path.name}{json_path} = {value!r} looks like a real Google "
                "domain/customer id — fixtures must use an `example`-marked "
                "synthetic value (RFC 2606); this repo is public"
            )


def test_guard_rejects_unmarked_tenant_identifiers(tmp_path):
    """A guard that has never failed is a guard nobody has tested.

    Both spellings, because the buttonClicked capture carries both and a scrub
    that fixed only one would still ship a real tenant id.
    """
    for key, value in (("domainId", "29vd573"), ("customer", "customers/C029vd573")):
        bad = tmp_path / f"bad-{key}.json"
        bad.write_text(json.dumps({"chat": {"user": {key: value}}}), encoding="utf-8")
        data = json.loads(bad.read_text(encoding="utf-8"))
        offenders = [p for p, v in _walk(data)
                     if TENANT_KEY.search(p) and "example" not in v.lower()]
        assert offenders, f"guard failed to flag a real {key}"
