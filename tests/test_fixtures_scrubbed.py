"""Hard rule #2 guard: no fixture, doc or test may carry a live secret or real identity.

This is a TEST, not a scrub script, and it walks the whole structure rather
than named paths — on 2026-07-29 a path-guess scrub missed a live token in
`configCompleteRedirectUri` and briefly wrote it to disk. Path guessing is the
failure mode; recursion is the fix.

Two guards live here, and they are in ONE file on purpose (CG-26):

  1. the **fixture guard** — every `.json` under `tests/fixtures/`, walked leaf
     by leaf with its JSON path, one parametrized test per file;
  2. the **docs/tests scan** — every `docs/**/*.md`, every `tests/**/*.py`,
     every `tests/**/*.md`, every root-level `*.md`, and the two deploy-config
     files named in `SCANNED_FILES`, line by line, **including this file and the
     README that documents it**.

The second exists because the first was aimed at the wrong directory. Both of
this project's PII incidents landed outside `tests/fixtures/`: the first draft
of a plan document hardcoded a live capability-URL bearer token (caught before
push), and
`docs/superpowers/plans/2026-07-29-live-verification-followups.md:484` published
a real Workspace `domainId` and customer id — while *quoting a test in this very
file*, which had been using those same real values as negative-case bait since
CG-3. `TENANT_KEY` would have flagged either one instantly **in a fixture**.
Nothing read a `.md`, and nothing read a `.py`, so nothing ever read the guard
itself. That is the entire finding of incident 2, and it is why rule 2 above
ends with "including this file" rather than leaving it to be inferred —
`test_docs_scan_covers_this_file_and_the_plan_that_quotes_it` pins it.

**Same file rather than a sibling module.** The CG-26 row allowed either. One
file keeps a single rule vocabulary — a reader comparing `PII`'s user-id arm
with `DOC_USER_ID` sees them together, and the deliberate difference in
precision between them (below) is legible instead of scattered. It also puts
"the guard scans itself" at exactly the point where the leak was: the file that
leaked is now the file that scans.

**The file is NOT renamed**, although `test_fixtures_scrubbed.py` is now
narrower than its contents. `CLAUDE.md`, `tests/fixtures/README.md` and several
queue rows and plan documents name this path; a rename is churn across
documents for no safety gain. Recorded here so the mismatch reads as a decision
rather than an oversight.

**One convention holds the whole arrangement up: negative-case bait is composed
at runtime, never inlined.** Every value this file must *reject* is assembled
from fragments, so the source carries no matchable literal while the test still
sees a whole, unmarked, real-shaped value. Inlining one instead makes this file
fail its own scan — which is the feature, not a bug, and is pinned by
`test_an_inlined_tenant_literal_would_be_flagged_in_this_very_file`.
"""

import json
import re
import sys
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


# ---------------------------------------------------------------------------
# Negative-case bait, COMPOSED and never inlined.
#
# Every value here is invented, and every one is real-SHAPED: that is the whole
# job of bait. A test that feeds its guard an obviously-fake value proves the
# guard rejects obviously-fake values, which is not the property anyone cares
# about.
#
# They are assembled from fragments because this file is itself scanned, by the
# docs/tests guard at the bottom of this module. An inlined real-shaped tenant
# id sitting right here is *precisely* the leak that created that guard
# (CG-26, incident 2 — `test_guard_rejects_unmarked_tenant_identifiers` carried
# the real `domainId` and customer id from CG-3 until 2026-07-30). Splitting the
# literal keeps the SOURCE free of anything a rule can match while the TEST
# still sees a whole, unmarked value at runtime.
#
# Considered and rejected: an `# allow`-style annotation that exempts a line
# from the scan. It would have to be added to files this item does not own —
# `tests/test_adapters.py` is CG-23's and `tests/test_log_redaction.py` is
# CG-34's (PR #33, **merged** onto main during this cycle) — both carrying
# deliberately-fake credentials, so the scan has to tolerate those values *by
# design* rather than by annotation. The merge did not retire that argument, it
# strengthened the evidence for it: `test_log_redaction.py` now sits INSIDE the
# scanned trees, so the tolerance is re-proved by
# `test_docs_and_tests_carry_no_real_identity` on every run rather than by a
# side check taken on trust. Given the scan must work without annotations
# anyway, an annotation here would be a second mechanism doing a job the first
# already does, and an exemption marker is exactly the thing a future scrub
# forgets to remove. Composition needs no marker and cannot be forgotten: it
# either scans clean or it does not.
#
# One bait below is NOT invented and cannot be — see
# `test_guard_rejects_the_author_identity_literal`.
# ---------------------------------------------------------------------------
_TENANT_BAIT = "a1b2c3d4e5"
_CUSTOMER_ID_BAIT = "customers/C" + _TENANT_BAIT
_BAIT_USER_ID = "users/" + "112233445566"
_BAIT_MEMBER_ID = "members/" + "998877665544"
_BAIT_AVATAR = "https://lh3." + "googleusercontent.com/a-/INVENTEDNOTREAL"
_BAIT_PEM_HEADER = "-----BEGIN " + "RSA PRIVATE KEY-----"
_BAIT_PEM_BLOCK = _BAIT_PEM_HEADER + "MIIEvAIBADANBgkqINVENTED"
# 68 characters, three character classes, and deliberately carrying none of
# DECLARED_FAKE's marker words — it has to clear `_looks_machine_generated`
# AND fail the marker check, or it proves nothing about DOC_URL_CRED.
_BAIT_OPAQUE = "Qz7Rm2Kd9Vt4Xb1Nw6Hs3Lp8Jc5Yg0Ff2Dq7Za4Mv1Bn8Rk3Tw6Ye9Uh2Ix5Ol0Pc7Sd"
_BAIT_URL_CRED = "https://chat.googleapis.com/v1/spaces/AAAAroom?" + "token=" + _BAIT_OPAQUE
# Private-range bait, one per range `DOC_PRIVATE_IP` covers (CG-78). Composed
# for the same reason as everything else here — this file is scanned, and an
# inlined literal in the guard's own negative case is incident 2's shape exactly.
# Composition also happens to be free here: splitting after the network part
# leaves a `"` where the regex wants a digit, so no fragment matches on its own.
#
# Every value is INVENTED and none is this network's. That distinction matters
# more for this rule than for the others: the bait for a tenant id merely has to
# look real, whereas the bait for an address must not BE the address the row
# exists to remove — a guard whose negative case republishes the leak is worse
# than no guard.
_BAIT_HOST_OCTETS = ".100.7"
_BAIT_RFC1918 = ("192.168" + _BAIT_HOST_OCTETS,
                 "10.0" + _BAIT_HOST_OCTETS,
                 "172.16" + _BAIT_HOST_OCTETS)
_BAIT_CGNAT = "100.64" + _BAIT_HOST_OCTETS


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

    **The bait is composed, not inlined, and that is load-bearing** (CG-26).
    From CG-3 until 2026-07-30 these two lines held the *real* Workspace
    `domainId` and customer id off the buttonClicked capture — reaching for the
    actual value is the path of least resistance when a negative case needs
    something that looks real, and it is how a public repo acquires a tenant id
    nobody meant to publish. `_TENANT_BAIT` / `_CUSTOMER_ID_BAIT` are invented
    and assembled at import time (see the bait block above), so this file's
    source carries no literal any rule can match, while the guard under test
    still receives a whole, `example`-free, real-shaped value.

    If someone later inlines a literal here instead, the docs/tests scan at the
    bottom of this module fires **on this very file**. That is the feature, not
    a bug, and `test_an_inlined_tenant_literal_would_be_flagged_in_this_very_file`
    proves it rather than asserting it.
    """
    cases = {
        "domainId": {"chat": {"user": {"domainId": _TENANT_BAIT}}},
        "customer": {"chat": {"spaces": [{"customer": _CUSTOMER_ID_BAIT}]}},
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


def test_guard_rejects_a_real_google_user_id(tmp_path):
    """`PII`'s long-digit-id arm, rejecting AND discriminating.

    Every landed fixture uses a zero-padded synthetic id, so the arm's PASS side
    has run on real bytes since CG-1. Its REJECT side never ran anywhere, which
    is the same asymmetry the capability-URL rule had: a rule that has only ever
    been fed values it accepts is a rule nobody has tested.

    Both spellings, because Chat spells the SAME id two ways — `users/<id>` in a
    sender or `user` block, `spaces/X/members/<id>` in a membership — and a
    guard that caught only the first would sail past a membership capture
    (CG-3's stated reason for the `members` alternation, never exercised until
    now). The `members/` case is nested in a LIST for the same reason the tenant
    test nests one: a rule that only reached top-level dict paths would miss the
    copy, and `_walk` is what makes that impossible.

    The discrimination side is the point of the `(?!0)` lookahead, and it is
    load-bearing in a way "does it reject?" cannot show. `(?!0)` is the entire
    reason this repo needs no path allowlist for user ids: a real Google user id
    is a long digit string that never starts with `0`, so a zero-padded
    synthetic one is structurally distinguishable. If the lookahead were dropped
    the guard would fire on every fixture in the directory and someone would
    weaken the rule to make the suite green. Nothing proved it discriminated.
    """
    bad_user = tmp_path / "bad-user-id.json"
    bad_user.write_text(json.dumps({"user": {"name": _BAIT_USER_ID}}), encoding="utf-8")
    with pytest.raises(AssertionError, match="real identity"):
        test_fixture_contains_no_secrets(bad_user)

    bad_member = tmp_path / "bad-member-id.json"
    bad_member.write_text(json.dumps(
        {"memberships": [{"member": {"name": "spaces/AAAAtestRoom/" + _BAIT_MEMBER_ID}}]}),
        encoding="utf-8")
    with pytest.raises(AssertionError, match="real identity"):
        test_fixture_contains_no_secrets(bad_member)

    ok = tmp_path / "ok-user-id.json"
    ok.write_text(json.dumps(
        {"user": {"name": "users/000000000000000000001"},
         "memberships": [
             {"member": {"name": "spaces/AAAAtestRoom/members/000000000000000000002"}}]}),
        encoding="utf-8")
    test_fixture_contains_no_secrets(ok)


def test_guard_rejects_a_googleusercontent_avatar_url(tmp_path):
    """`PII`'s avatar-host arm — the near-miss the fixtures README remembers.

    The 2026-07-30 buttonClicked capture carried a `googleusercontent.com` proxy
    avatar in the **app's own sender block**, which no previous scrub had ever
    had to think about because the message capture had no bot sender at all. The
    scrub caught it; the guard's ability to catch it was never demonstrated.

    Inside a JSON fixture the rule is deliberately blunt: **any** mention of the
    host is a leak, because a proxy avatar URL is by construction a real
    person's, and no fixture has a reason to name that host at all. The prose
    rule (`DOC_AVATAR`, below) is deliberately NOT blunt in the same way — it
    demands a real `https://…googleusercontent.com/` URL — because prose
    mentions of the host already sat in the scanned trees when that rule was
    written, and a blunt port would have flagged every one of them on its first
    run. Same concern, two precisions, because the surrounding context differs.
    That asymmetry is recorded in `tests/fixtures/README.md`; this test is the
    fixture half of it.

    The pass side is the substitution the landed fixtures actually use, so this
    also pins that the anonymization convention and the guard agree.
    """
    # 4 such mentions existed in the scanned trees the day the prose rule was
    # written; 14 exist as of this commit, because a rule that has to be
    # documented gets named in its own documentation. The number only goes up,
    # and the breakdown — with why the previously-recorded nine and seventeen
    # were both overcounts — is at `DOC_AVATAR`.
    bad = tmp_path / "bad-avatar.json"
    bad.write_text(json.dumps({"user": {"avatarUrl": _BAIT_AVATAR}}), encoding="utf-8")
    with pytest.raises(AssertionError, match="real identity"):
        test_fixture_contains_no_secrets(bad)

    ok = tmp_path / "ok-avatar.json"
    ok.write_text(json.dumps({"user": {"avatarUrl": "https://example.com/avatar.png"}}),
                  encoding="utf-8")
    test_fixture_contains_no_secrets(ok)


def test_guard_rejects_the_author_identity_literal(tmp_path):
    """`PII`'s fourth arm — the literal author name — which the queue row missed.

    The CG-26 row's table lists three unproven rules and this is not among them.
    It should have been: `PII` is an alternation of THREE arms, and the row
    counts the id arm and the avatar arm and stops. The literal-name arm is the
    oldest rule in the file (CG-1) and had no test either. Recorded rather than
    quietly fixed, because "the table said three" is exactly how a fourth gap
    survives a cleanup item whose entire purpose is closing gaps.

    **Isolated on purpose.** The obvious bait — an `@mackelprang.com` address —
    would be caught by the `EMAIL` / `EXAMPLE_DOMAIN` rule as well, so a passing
    test would prove nothing about which rule fired, and deleting the name arm
    would leave the suite green. A **display name** has no `@`, matches no
    address shape, and reaches `EXAMPLE_DOMAIN` not at all: the only rule in
    this file that can reject it is the literal-name arm.

    This is the one bait in this module that is NOT invented, and it cannot be:
    the rule matches a specific surname, so any invented name would fail to fire
    and would prove the opposite of what is wanted. It costs nothing — the name
    is in the authorship metadata of every commit in this repo and is already a
    literal in `PII`'s own source thirty lines above. It is also exactly why the
    docs/tests scan below has **no** name rule: a rule that fires on a value
    present in every commit gets disabled within a week.

    The pass side is the substitution the landed fixtures use. It doubles as the
    limit statement: `"Test User"` and a real name are indistinguishable to a
    regex, so display-name anonymization is a REVIEW obligation, not a guarded
    one — the guard protects exactly one human by name and no others.
    """
    bad = tmp_path / "bad-display-name.json"
    bad.write_text(json.dumps({"user": {"displayName": "Mark Mackelprang"}}),
                   encoding="utf-8")
    with pytest.raises(AssertionError, match="real identity"):
        test_fixture_contains_no_secrets(bad)

    ok = tmp_path / "ok-display-name.json"
    ok.write_text(json.dumps({"user": {"displayName": "Test User"}}), encoding="utf-8")
    test_fixture_contains_no_secrets(ok)


def test_guard_rejects_an_unscrubbed_private_key_block(tmp_path):
    """`SUSPECT_VALUE`'s `BEGIN … PRIVATE KEY` arm, isolated from `SUSPECT_KEY`.

    A service-account key file is the one credential in this project that would
    be catastrophic in a fixture — `chat-gateway-sa-gw.json` is the live tier-2
    identity — and the arm that catches its PEM header had never been fed one.

    **Isolated the same way the capability-URL test's third case is**, and for
    the same reason. Put the block under `privateKey` and `SUSPECT_KEY` catches
    it too, so deleting the value arm leaves the suite green and the test proves
    nothing about which rule works. `note` matches no `SUSPECT_KEY` alternative,
    so the value rule is the only thing that can fire — which is also the
    property that matters in practice: a leaked key does not arrive under a
    helpfully-named field, it arrives pasted into a text leaf.

    The base64 is INVENTED and short. A real key must never be committed, not
    even inside a test that rejects it, and twenty characters of obvious filler
    exercises the identical code path — the rule matches the HEADER, so the
    body's realism buys no coverage and only risk.

    The pass side is the `PLACEHOLDER` discrimination, and it is the half that
    matters most here. Rejecting is easy; the rule has to let a scrubbed value
    through, because the landed `classic-added-to-space-event.json` depends on
    exactly that behaviour for its `configCompleteRedirectUrl`. A guard that
    rejected placeholders too would be indistinguishable from a broken one until
    the day someone scrubbed a fixture and could not make the suite pass.
    """
    bad = tmp_path / "bad-private-key.json"
    bad.write_text(json.dumps({"note": _BAIT_PEM_BLOCK}), encoding="utf-8")
    with pytest.raises(AssertionError, match="looks like a credential"):
        test_fixture_contains_no_secrets(bad)

    ok = tmp_path / "ok-private-key.json"
    ok.write_text(json.dumps({"note": _BAIT_PEM_HEADER + "<SCRUBBED>"}), encoding="utf-8")
    test_fixture_contains_no_secrets(ok)


def test_fixture_files_refuses_to_pass_vacuously(tmp_path, monkeypatch):
    """The assertion that protects every other assertion in this file.

    `fixture_files()` is the parametrize source. If it ever returned nothing —
    a moved directory, a renamed extension, a `rglob` typo, a packaging change
    that drops `tests/fixtures/` — pytest generates **zero** cases and the whole
    fixture guard reports success by collecting nothing. `assert files` exists
    to make that impossible, and it had never executed. A guard whose
    fail-safe is untested has a fail-safe nobody has tested; the file's own
    opening argument applies to its own scaffolding.

    **Monkeypatching the module global rather than adding a `root` parameter is
    deliberate.** A parameter would be a second, test-only code path: the suite
    would exercise `fixture_files(tmp_path)` while production runs
    `fixture_files()`, and a defect in the default — which is the only form
    anything actually calls — would stay invisible. Rebinding `FIXTURES` leaves
    exactly one code path and points it somewhere empty. `monkeypatch` restores
    it at teardown, so collection-time state is not disturbed for other tests.

    The discrimination half is not decoration: an assertion that fires on an
    empty directory but also on a full one would be a guard that can never pass,
    and the failure mode of THAT is someone deleting the assertion.
    """
    monkeypatch.setattr(sys.modules[__name__], "FIXTURES", tmp_path)
    with pytest.raises(AssertionError, match="never pass vacuously"):
        fixture_files()

    landed = tmp_path / "one-fixture.json"
    landed.write_text("{}", encoding="utf-8")
    assert fixture_files() == [landed]


# ===========================================================================
# The widened scan — `docs/**/*.md` and `tests/**/*.py`, INCLUDING THIS FILE.
#
# Everything above this line guards `tests/fixtures/`. Neither of this
# project's two PII incidents was in a fixture, so everything above this line
# was, for both of them, pointed at the wrong directory. See the module
# docstring for the incidents; what follows is the correction.
# ===========================================================================

REPO_ROOT = Path(__file__).parent.parent

# The trees, and the absences, are each deliberate. `docs/**/*.md` because both
# incidents landed in a plan document. `tests/**/*.py` because incident 2's
# ORIGINAL — the thing the plan document was quoting — was a test file, and
# that is not bad luck: a negative case NEEDS a value that looks real, so
# reaching for the actual capture is the path of least resistance, which makes
# `tests/` the single most likely place in the repo to hold a real value on
# purpose. `src/` is absent because hard rule #2 keeps secrets in the
# environment and the committed registry holds env-var NAMES; `iac/` and
# `.env` are gitignored or hold names too. Scanning trees no incident has ever
# touched buys coverage of an unmeasured risk while widening the
# false-positive surface — and a guard that cries wolf is a guard that gets
# disabled, which is the one failure mode this whole file exists to avoid.
#
# `tests/**/*.md` and the root `*.md` were the two markdown holes those two
# trees left, and both hold documents nobody would call peripheral: the root
# glob is what puts `CLAUDE.md` — this repo's most-edited public document,
# carrying live operational detail on every session — inside the guard, and
# `tests/**/*.md` is what puts `tests/fixtures/README.md`, the document that
# EXPLAINS this guard, inside it. Neither cost anything to add: all three files
# scanned zero findings on the day they were added, so the widening is
# measured, not hopeful.
SCANNED_TREES = (("docs", "*.md"), ("tests", "*.py"), ("tests", "*.md"))

# Root-level markdown, and **non-recursive on purpose** — `REPO_ROOT.glob`, not
# `rglob`. A recursive root pattern would subsume every tree above and then keep
# walking into `.claude/worktrees/`, where other Builders' checkouts of this
# same repo live: a finding reported at a path that is not in this working tree
# is unfixable and unreproducible, which is precisely how a guard earns the
# reputation that gets it disabled.
SCANNED_ROOT_GLOB = "*.md"

# Two deploy-config files, named one at a time rather than by a tree, because
# the reason for each is specific (CG-78).
#
# `docker-compose.yml` is where a LAN address would land if one landed anywhere
# outside prose: CG-55's own decision table specifies the published-port form as
# `"<LAN-IP>:8085:8085"`, so the compose file is the documented destination of
# the exact literal `DOC_PRIVATE_IP` hunts. A guard that covered `docs/` and not
# this file would have been blind at precisely the spot the next one lands —
# which is the CG-69 failure mode wearing the opposite mask: not a guard that
# cries wolf, a guard that looks like coverage and is not.
#
# `.env.example` is here for a bigger reason than IPs, and it is worth stating
# because it was found rather than intended: it is the file in this repo most
# likely to receive a pasted **real credential** — an operator opens it first,
# fills it in, and the copy on disk is one `git add` from the remote — and until
# CG-78 it sat outside the credential rules entirely, not just the address one.
#
# NOT widened to `src/` or `iac/`, and that is a scope decision rather than a
# measurement gap: all seven rules over both trees measured **0** findings, so
# there is nothing there to catch today, and pulling 28 more files under six
# credential rules buys nothing now while adding a surface that has to stay
# green forever. Revisit if an address ever needs to live in `iac/`.
#
# Measured on the day it went in, the same standard the tree widenings above
# were held to: all seven rules over both files, zero findings.
SCANNED_FILES = ("docker-compose.yml", ".env.example")

# Same shape as `PII`'s id arm, `(?!0)` lookahead included, so a document may
# quote the synthetic `users/000…001` the fixtures use — and the docs quote it
# constantly, in anonymization tables and scrub notes.
DOC_USER_ID = re.compile(r"(?:users|members)/(?!0)\d{10,}")

# Deliberately NARROWER than `PII`'s avatar arm, which flags the bare host.
# In a JSON fixture any mention of `googleusercontent.com` is a leak: a proxy
# avatar URL is by construction some real person's, and no fixture has a reason
# to name that host at all. In prose the host is a legitimate SUBJECT, and the
# counts below are re-measured rather than inherited, because the first pair
# written down were both wrong. **4** such mentions sat in the scanned trees on
# the day this rule was written — all four in `docs/`, none in `tests/`. **14**
# sit in them as of this commit: 4 in `docs/`, 6 in this module, 4 in
# `tests/fixtures/README.md`, which the widened trees above have just brought
# inside the guard. The figures this replaces — nine,
# then seventeen — counted the bare token `googleusercontent`, which sweeps up
# regex-source spellings that a blunt rule could not match, and so overstated
# the exact quantity the number exists to size. Documenting a rule means naming
# what it hunts, so the count only goes up. A blunt port would still have been a
# false-positive storm on the guard's first run and a worse one now, and the fix
# a reader reaches for at that point is to delete the rule. So prose must carry
# an actual URL — scheme, host, path separator — before this fires. Same
# concern, two precisions, because the surrounding context differs.
DOC_AVATAR = re.compile(r"https?://[\w.-]*googleusercontent\.com/", re.I)

# The `-----` armour, not the bare words. `SUSPECT_VALUE`'s fixture form matches
# `BEGIN [A-Z ]*PRIVATE KEY` with no armour, which is right for a JSON leaf and
# wrong for prose: this repo discusses that rule in three documents already, and
# this comment is a fourth. Stated precisely, because the tempting version of
# this sentence overclaims — every one of those three writes the header
# ELIDED or BRACKETED (`BEGIN … PRIVATE KEY`, `BEGIN [A-Z ]*PRIVATE KEY`), which
# even the blunt form would miss, so the armour is not what saves them today.
# What it defends against is the natural unelided prose one keystroke away —
# "a key file begins with the line BEGIN RSA PRIVATE KEY" — which the blunt form
# WOULD flag. Prophylactic, in other words, and pinned as such by
# `test_docs_guard_tolerates_what_this_repo_publishes_on_purpose`, whose sample
# carries all three spellings. It also does not fire on its own source, because
# `[A-Z ]*` cannot match `[`.
DOC_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")

# Private-range address literals — RFC1918 plus the CGNAT block Tailscale hands
# out. CG-78, after CG-55's planning prose put this homelab's real LAN address
# and its subnet into `docs/BUILDER_QUEUE.md` on a public repo.
#
# **Scoped to the private ranges, deliberately, and never "any dotted quad".**
# That single decision is what separates this rule from a wolf-crier, because
# this repo argues about addresses constantly and every address it argues about
# is public or reserved:
#
#   - `0.0.0.0` — the bind form `docker-compose.yml` and CG-55's bind decision
#     both discuss at length. Not private; no match.
#   - `127.0.0.1` — the smoke-curl vantage point, in the runbook and two specs.
#     Loopback is not RFC1918; no match.
#   - netmasks (`255.255.255.0`) and the RFC 5737 documentation nets
#     (`192.0.2.x`, `198.51.100.x`, `203.0.113.x`) — reserved *for* writing
#     examples, which is the opposite of a leak. None is in a private range.
#     Note `192.0.2.x` in particular: one careless `192\.` prefix would flag the
#     very range the RFCs reserve for documentation.
#   - version strings and section numbers — `10.2.1`, `3.13.7`, "line 10.4".
#     A full four octets are required, with `10` as its own first octet, so
#     three-part versions cannot match however they start.
#
# The `(?<![\w.])` / `(?![\w.])` boundaries are what make that last one hold:
# without the trailing one, `10.2.1.4.7` (a plausible OID or outline number)
# would match its first four parts.
#
# **Measured before it was written, not after** — the CG-69 lesson. Across the
# scanned set: **3** findings before CG-78's scrub, all three in
# `docs/BUILDER_QUEUE.md`, and **0** after. Zero residue means no future editor
# ever meets this rule as an obstacle to routine work, which is the only
# condition under which a guard survives.
#
# ⚠ **What this rule cannot do, stated here because the queue row's checkbox
# reads stronger than the truth:** it guards the working tree, not the published
# history. The literals it was written for are still in this repo's commits and
# a `git log -S` finds them; removing those needs a history rewrite, which was
# considered and rejected (CG-78). This stops the NEXT one.
DOC_PRIVATE_IP = re.compile(
    r"(?<![\w.])(?:"
    r"10(?:\.\d{1,3}){3}"
    r"|192\.168(?:\.\d{1,3}){2}"
    r"|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
    r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2}"
    r")(?![\w.])"
)

# A Workspace customer id has no structure to key off — the same problem
# `TENANT_KEY` has, and the same answer: the RFC 2606 marker. `customers/C`
# followed by a real alnum run is a finding unless the match carries `example`.
# The `{3,}` floor is what lets a document write an ELIDED reference —
# `customers/C0…` — which the docs do when they need to point at the incident
# without reprinting it.
DOC_CUSTOMER = re.compile(r"customers/C[A-Za-z0-9]{3,}")

# The assignment form, because incident 2 was an assignment: a `domainId` or
# `customer` key, then a separator, then a quoted opaque value. `[:=,]` covers
# all three spellings this repo actually writes — JSON/YAML `key: value`,
# Python `key=value`, and the tuple form `("domainId", "…")` that incident 2
# was literally written in. The trailing quote is required, which is why the
# composed bait in this file does not match itself: a value assembled across a
# `+` has a quote where the regex wants an identifier character.
#
# `(?<!\w)` is the left boundary, and it was added after measurement rather
# than by foresight — without it the key alternation matches as a SUFFIX of any
# identifier, so a Python variable merely ENDING in `customer` (or `domainId`),
# followed by a comma and a quoted string, is a finding. It fired twice on this
# item's own source; see the naming note in
# `test_an_inlined_tenant_literal_would_be_flagged_in_this_very_file`. Every
# real target shape survives the boundary, which is why it is safe: `"domainId":
# "…"`, `domainId: …` and `("domainId", "…")` all carry a quote, a punctuation
# mark, whitespace or line-start before the key, and none of those is `\w`.
DOC_TENANT_ASSIGN = re.compile(
    r"""(?<!\w)(?:domainId|customers?)["'`]?\s*[:=,]\s*["'`]([A-Za-z0-9][\w./-]{3,})["'`]""",
    re.I)

# The table-cell form, because incident 1 hid there. `DOC_TENANT_ASSIGN` cannot
# see a markdown mapping row — the separator is `|`, not `[:=,]` — and this
# repo's scrub plans document every anonymization as exactly such a row — a
# JSON path, the raw value, the replacement, each in its own backticked cell.
# That is the most likely place in this repo for a real tenant id to sit in
# prose, because writing the row is the LAST step of a scrub, when the raw value
# is still on screen. Measured against a reconstruction of incident 1: the
# shipped rules caught five of its seven leaked classes, and this row was one of
# the two they missed.
#
# The backtick around the value is REQUIRED, and that requirement is the whole
# precision argument: this repo always backticks a literal in a table cell, so
# demanding one costs no detection, while an unbackticked cell is prose — and
# prose beside these two field names is common enough to matter. A decision row
# whose middle cell names both fields and whose NEXT cell is a sentence
# ("Path allowlist for those two fields") captures the word `Path` without it;
# that exact row is in the tolerance sample below. An unbackticked raw value in
# a table cell is therefore a documented miss, not an oversight — it is what the
# repo-wide sweep of this rule costs to keep at zero.
DOC_TENANT_TABLE = re.compile(
    r"(?<!\w)(?:domainId|customers?)`?\s*\|\s*`([A-Za-z0-9][\w./-]{3,})`", re.I)

# The narrowed replacement for `SUSPECT_KEY` / `SUSPECT_VALUE`. Those key off a
# JSON path, and prose has no JSON path; a naive port fires on dozens of lines
# across the scanned trees, every one a false positive and most of them
# documentation OF the rule — so the count climbs each time somebody explains
# it. The measured figure and the method that produced it live in
# `tests/fixtures/README.md`, once: a second copy here would be a number that
# drifts in two places instead of one, which is how the 28 this comment used to
# carry outlived the measurement behind it. What survives the narrowing is the
# shape that actually leaked: a credential in a URL query or fragment. Fragment
# (`#`) included because an OAuth implicit-flow token arrives there and
# `tests/test_log_redaction.py` (CG-34, PR #33, merged) redacts it there.
DOC_URL_CRED = re.compile(
    r"""[?&#][\w.-]*(?:token|key|secret|password|auth|sig|credential)[\w.-]*"""
    r"""=([^&#\s"'`<>)\]}\\]+)""", re.I)

_PCT = re.compile(r"%[0-9A-Fa-f]{2}")

# The vocabulary is generous ON PURPOSE. This is the escape hatch for the
# false-positive direction — a genuinely fake value that happens to be long,
# mixed-case and marker-free WILL be flagged, and the fix is to add a marker
# word, so the words a person would naturally reach for all have to be here.
# `your` earns its place from `?token=YOUR_TOKEN_HERE`-style doc placeholders.
DECLARED_FAKE = re.compile(
    r"example|test|fake|dummy|sample|placeholder|scrubbed|redacted|notreal"
    r"|changeme|your", re.I)


def _looks_machine_generated(value: str) -> bool:
    """Is this value opaque enough to be a real credential rather than a stand-in?

    Two signals, both cheap and both about the VALUE alone — no annotation, no
    path allowlist, nothing a scrub can forget to update.

    `%XX` escapes are stripped FIRST. A URL-encoded value is padded by its own
    encoding (`%3D%3D` is six characters of two), and counting the padding
    toward the length threshold would let a short secret hide behind its
    escaping.

    The thresholds are stated as limits in `tests/fixtures/README.md` rather
    than defended as sufficient, because they are not: a real credential shorter
    than 24 characters, or drawn from a single character class, passes this
    function and is therefore never reported. That is the accepted cost of
    tolerating `?key=K&token=T` and `?key=SECRETKEYVALUE&…`, which are the
    literal deliberately-fake values `tests/test_adapters.py` (CG-23) and
    `tests/test_log_redaction.py` (CG-34, PR #33, merged during this cycle) are
    built on — files this item does not own and cannot annotate. Both now sit
    inside the scanned trees, so that tolerance is re-proved by the aggregate
    scan on every run instead of being asserted here.
    """
    core = _PCT.sub("", value)
    if len(core) < 24:
        return False
    classes = sum(bool(re.search(p, core)) for p in (r"[a-z]", r"[A-Z]", r"\d"))
    return classes >= 3


def _scan_line(line):
    """Yield `(rule_name, matched_text)` for one line of prose or source."""
    for rule, rx in (("DOC_USER_ID", DOC_USER_ID),
                     ("DOC_AVATAR", DOC_AVATAR),
                     ("DOC_PEM", DOC_PEM),
                     ("DOC_PRIVATE_IP", DOC_PRIVATE_IP)):
        for m in rx.finditer(line):
            yield rule, m.group(0)

    # The RFC 2606 marker, the same convention `TENANT_KEY` enforces on
    # fixtures — read here rather than required, because a document is allowed
    # to say nothing about tenants at all. Suppression is keyed on the whole
    # MATCH, not the captured value, so `"customer": "customers/Cexample1"`
    # clears on either half carrying the marker.
    for rule, rx in (("DOC_CUSTOMER", DOC_CUSTOMER),
                     ("DOC_TENANT_ASSIGN", DOC_TENANT_ASSIGN),
                     ("DOC_TENANT_TABLE", DOC_TENANT_TABLE)):
        for m in rx.finditer(line):
            if "example" not in m.group(0).lower():
                yield rule, m.group(0)

    for m in DOC_URL_CRED.finditer(line):
        value = m.group(1)
        if DECLARED_FAKE.search(value) or not _looks_machine_generated(value):
            continue
        yield "DOC_URL_CRED", m.group(0)


def scan_text_for_real_identity(text, source="<sample>"):
    """Scan `text` LINE BY LINE, returning `(source, lineno, rule, matched)`.

    Line by line, not whole-text: it makes a finding reportable as `path:line`,
    which is what a scrub actually needs, and it removes a class of phantom
    match that spans two unrelated lines. Nothing real is lost — every rule here
    matches within one line by construction, including `DOC_PEM`, whose armoured
    header is always on a line of its own.
    """
    return [(source, lineno, rule, matched)
            for lineno, line in enumerate(text.splitlines(), start=1)
            for rule, matched in _scan_line(line)]


def docs_and_tests_files():
    files = sorted(
        {p
         for subdir, pattern in SCANNED_TREES
         for p in (REPO_ROOT / subdir).rglob(pattern)}
        | set(REPO_ROOT.glob(SCANNED_ROOT_GLOB))
        # `.exists()` rather than a bare join: the vacuity test below points
        # `REPO_ROOT` at an empty tmp_path, and a non-existent path yielded here
        # would make the walker return names it cannot read.
        | {p for p in (REPO_ROOT / name for name in SCANNED_FILES) if p.exists()}
    )
    assert files, "no docs or tests found — this scan must never pass vacuously"
    return files


def scan_docs_and_tests():
    return [finding
            for path in docs_and_tests_files()
            for finding in scan_text_for_real_identity(
                path.read_text(encoding="utf-8"),
                path.relative_to(REPO_ROOT).as_posix())]


def test_docs_and_tests_carry_no_real_identity():
    """The guard the two incidents earned. One aggregate test, every offender named.

    **Aggregate rather than parametrized per file, and that is a decision, not
    an inconsistency** — the fixture guard twenty lines up IS parametrized per
    file. Two reasons, and both are about what happens to the suite over time:

    1. `docs/**/*.md` grows with every session. A per-file parametrization would
       make the suite's total case count drift with documentation volume, and
       every queue row in this project reports its work as "suite N -> M". That
       signal is load-bearing — it is how a reviewer sees at a glance whether a
       PR added the tests it claimed — and tying it to how many plan documents
       happen to exist would destroy it. `tests/fixtures/` does not have that
       problem: fixtures are landed deliberately, one at a time, and a new one
       SHOULD move the count.
    2. A scrub is done in one pass. When this fires you want the whole list, not
       the first file alphabetically, then a re-run, then the next. The
       assertion message is therefore built to be pasted into a scrub: every
       offender, as `path:line  RULE  matched-text`.

    The matched text is included in the failure message deliberately, even
    though the matched text is by definition the thing that should not be
    published. It is already committed at that path — that is what the finding
    IS — and a report that says "something on line 484" makes the reader open
    the file and find it themselves, which is strictly worse.
    """
    findings = scan_docs_and_tests()
    assert not findings, (
        f"{len(findings)} real-looking identity/credential value(s) in "
        f"{len({f[0] for f in findings})} file(s) — this repo is public:\n"
        + "\n".join(f"  {src}:{lineno}  {rule}  {matched!r}"
                    for src, lineno, rule, matched in findings)
    )


def test_docs_scan_refuses_to_pass_vacuously(tmp_path, monkeypatch):
    """Same fail-safe, same argument, as `test_fixture_files_refuses_to_pass_vacuously`.

    This one matters more than the fixture version, because this walker's inputs
    are two hardcoded directory names. Rename `docs/`, restructure the tests
    tree, run the suite from a packaging layout that ships neither — and a scan
    over nothing reports success. The single aggregate test above cannot notice:
    zero files produce zero findings, which is exactly what passing looks like.

    Monkeypatching `REPO_ROOT` rather than parameterizing the walker, for the
    reason spelled out in the fixture version: one code path, and it is the one
    production uses.
    """
    monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
    with pytest.raises(AssertionError, match="never pass vacuously"):
        docs_and_tests_files()

    (tmp_path / "docs").mkdir()
    landed = tmp_path / "docs" / "note.md"
    landed.write_text("nothing here\n", encoding="utf-8")
    assert docs_and_tests_files() == [landed]


def test_docs_scan_covers_this_file_and_the_plan_that_quotes_it():
    """The self-scan property — the entire finding of incident 2.

    The guard had never scanned itself. Not as an oversight in one rule, but
    structurally: it walked `tests/fixtures/*.json` and this file is neither in
    that directory nor of that type, so the real tenant id sitting in its own
    negative-case bait since CG-3 was invisible to it, and stayed invisible
    while the plan document quoted it into `docs/` and out to the public remote.

    Both halves of that are asserted by name. Without this test the walker could
    silently stop yielding `tests/**/*.py` — a typo in `SCANNED_TREES`, a
    refactor that scopes it to `docs/` "because that is where the incidents
    were" — and everything else in this module would stay green while the one
    file most likely to carry a real value on purpose went unread again.

    The last two names are the markdown holes the original two trees left, and
    each reaches the walker by a DIFFERENT mechanism — `CLAUDE.md` only through
    the non-recursive root glob, `tests/fixtures/README.md` only through
    `tests/**/*.md`. Naming both is what makes a partial revert visible: drop
    either mechanism and the aggregate scan still passes, because fewer files
    produce fewer findings, which is exactly what passing looks like.
    """
    scanned = {p.relative_to(REPO_ROOT).as_posix() for p in docs_and_tests_files()}
    assert "tests/test_fixtures_scrubbed.py" in scanned, (
        "the docs/tests scan no longer reads itself — that is incident 2 exactly"
    )
    assert (
        "docs/superpowers/plans/2026-07-29-live-verification-followups.md"
        in scanned
    ), "the docs/tests scan no longer reads the plan document that leaked"
    for widened, mechanism in (("CLAUDE.md", "the root glob"),
                               ("tests/fixtures/README.md", "tests/**/*.md"),
                               ("docker-compose.yml", "SCANNED_FILES"),
                               (".env.example", "SCANNED_FILES")):
        assert widened in scanned, (
            f"{widened} is no longer scanned — {mechanism} has been dropped, and "
            "with it the guard's coverage of a document nobody would call peripheral"
        )


def test_docs_guard_rejects_a_private_lan_address():
    """`DOC_PRIVATE_IP` fires on every private range, and on none of the near-misses.

    Both directions in one test, on purpose. This rule's entire value proposition
    is its **scoping** — CG-78 shipped it only because the false-positive half
    could be measured, and a fire-only test would leave the half that decides
    whether the guard survives contact with this repo unasserted.

    The near-miss list is not hypothetical. Every entry below is a shape that
    already appears in the scanned trees, some of them dozens of times: this repo
    argues about `0.0.0.0` versus a LAN bind across a runbook, a spec and two
    queue rows, quotes a `127.0.0.1` smoke curl, and carries version numbers on
    nearly every page. `192.0.2.x` is included because it is the sharpest trap —
    a rule written as "starts with 192" would flag the range the RFCs reserve
    *for writing documentation*, i.e. the very thing a scrub replaces a real
    address WITH.
    """
    for bait in (*_BAIT_RFC1918, _BAIT_CGNAT):
        fired = {rule for _, _, rule, _ in
                 scan_text_for_real_identity("published on " + bait + ":8085")}
        assert "DOC_PRIVATE_IP" in fired, (
            f"DOC_PRIVATE_IP did not fire on the private address {bait!r}; "
            f"rules that did fire: {sorted(fired) or 'none'}"
        )

    for benign in (
        "ports 8085:8085 binds 0.0.0.0, every interface",
        "curl 127.0.0.1:8085/healthz on the NAS, over SSH",
        "netmask 255.255.255.0",
        "RFC 5737 reserves 192.0.2.1, 198.51.100.7 and 203.0.113.9",
        "httpx 10.2.1 on python 3.13.7",
        # Five dotted parts starting `10.` — an OID or an outline number. This
        # is what the TRAILING boundary defends: without it the rule matches the
        # first four parts and reports a leak in a section reference.
        "see line 10.4, and object 10.2.1.4.7 of the outline",
        "published on <LAN-IP>:8085 and routed via <LAN-subnet>",
    ):
        findings = scan_text_for_real_identity(benign)
        assert not findings, (
            f"DOC_PRIVATE_IP flagged something this repo writes on purpose "
            f"({benign!r}) — that is how guards get disabled: {findings}"
        )


def test_docs_guard_rejects_each_leak_shape():
    """Seven shapes, seven rules, each proven to fire — bait invented and composed.

    Seven of the scan's **eight** rules. `DOC_PRIVATE_IP` is proven in its own
    test rather than added as an eighth tuple here, and the split is deliberate:
    that rule's whole justification is what it does NOT match, so a fire-only
    case would assert the half that does not decide whether it survives. It gets
    both directions in one place — see
    `test_docs_guard_rejects_a_private_lan_address`.

    These are the shapes the two incidents were made of, plus the two that would
    make a third one worse. Every value is invented; every one is assembled from
    fragments at import time, because writing any of them as a literal here
    would make this file fail `test_docs_and_tests_carry_no_real_identity`
    above. That is the convention working, not a workaround for it.

    The last case is a markdown TABLE ROW, and it is here because a
    reconstruction of incident 1 — the plan draft that leaked a live capability
    token — was run against the shipped rules and this was one of two classes
    they missed. A scrub plan records every anonymization as a mapping row, and
    the raw value is still on screen when that row gets written, so the table
    cell is not an exotic hiding place; it is the ordinary one. Its third cell
    carries the `example` marker deliberately: the replacement column of a real
    mapping row does, and suppression keys on the MATCH rather than the line, so
    a rule that read the whole row would clear a leak that sits two cells to the
    left of a marker.

    Asserted by RULE NAME rather than by "some finding was produced". A bait
    string can trip the wrong rule — a `customers/C…` value inside a
    `"customer": "…"` assignment trips two — and a test that only checks the
    count would keep passing after the rule it names had been deleted.
    """
    for bait, expected_rule in (
        ("the sender arrived as " + _BAIT_USER_ID, "DOC_USER_ID"),
        ("avatar was " + _BAIT_AVATAR, "DOC_AVATAR"),
        (_BAIT_PEM_BLOCK, "DOC_PEM"),
        ("the space belongs to " + _CUSTOMER_ID_BAIT, "DOC_CUSTOMER"),
        ('    "domainId": "' + _TENANT_BAIT + '",', "DOC_TENANT_ASSIGN"),
        ("| `$.chat.user.domainId` | `" + _TENANT_BAIT + "` | `example1` |",
         "DOC_TENANT_TABLE"),
        ("curl " + _BAIT_URL_CRED, "DOC_URL_CRED"),
    ):
        fired = {rule for _, _, rule, _ in scan_text_for_real_identity(bait)}
        assert expected_rule in fired, (
            f"{expected_rule} did not fire on a real-shaped value; rules that "
            f"did fire: {sorted(fired) or 'none'}"
        )


# Every class of value the scan must NOT flag, in one sample.
#
# It is written INLINE, unlike every bait value in this module, and that is the
# point rather than an inconsistency: this constant is by definition the set of
# things no rule matches, so it is safe in the source of a file that scans
# itself. If a future rule change breaks that, this file stops passing its own
# scan and the breakage is unmissable.
PUBLISHED_ON_PURPOSE = """
Space, message and thread ids are classified NON-SECRET by
docs/google-cloud-setup.md step 8, and they are all over the committed docs and
fixtures: spaces/AAQAgjGR7J4, spaces/AAQAgjGR7J4/threads/_CWBxuQ8MlU and
spaces/AAAAtestRoom/messages/MSG2.

The author's own name and email are in the authorship metadata of every commit
in this repository and cannot be removed by scrubbing prose:
Mark Mackelprang <mark@mackelprang.com>. Google's own service accounts are
published constants, named in the IaC and in this project's setup doc:
chat-api-push@system.gserviceaccount.com and
service-<PROJECT_NUMBER>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com.

Deliberately-fake credentials, exactly as CG-23 and PR #33 (CG-34) write them:
    ?key=SECRETKEYVALUE&token=SECRETTOKENVALUE
    https://chat.googleapis.com/v1/spaces/A/messages?key=K&token=T
    https://h/cb?key=K#access_token=T&scope=s
    https://chat.google.com/bot_config_complete?token=LIVE
    https://x/y?token=ya29.REALLOOKING
    https://chat.google.com/api/bot_config_complete?token=AAAAtestNotARealTokenAAAAtestNotARealTokenAAAAtestNotARealToken%3D%3D

Prose and regex source may name the hosts and headers the rules look for. The
buttonClicked capture carried a googleusercontent.com proxy avatar URL.
SUSPECT_VALUE's second arm is BEGIN [A-Z ]*PRIVATE KEY, the CG-26 queue row
writes the same thing as BEGIN … PRIVATE KEY, and a service-account key file
begins with the line BEGIN RSA PRIVATE KEY. None of those is a leaked key.

Synthetic and elided identifiers: users/000000000000000000001,
customers/Cexample1, domainId "example1", and the elided reference
customers/C0… that the docs use to point at incident 2 without reprinting it.

A scrub plan's mapping rows, marked in the replacement column exactly as
docs/superpowers/plans/2026-07-30-classic-fixtures-cg22-cg9.md writes them:
| `$.user.domainId` | `example1` | `TENANT_KEY` marker |
| `$.space.customer` | `customers/Cexample1` | `TENANT_KEY` marker |

...and a decision row naming both tenant fields, whose next cell is a sentence
rather than a backticked value:
| DEC-6 | `example`-marker guard for `domainId` / `customer` | Path allowlist for those two fields | rejected |

Addresses this repo argues about on purpose, none of them in a private range:
"8085:8085" binds 0.0.0.0; the smoke curl reads 127.0.0.1:8085/healthz; a
netmask is 255.255.255.0; and RFC 5737 reserves 192.0.2.1, 198.51.100.7 and
203.0.113.9 for exactly this kind of writing. Version numbers and outline
references are not addresses either: httpx 10.2.1, python 3.13.7, object
10.2.1.4.7. The scrubbed forms are <LAN-IP>, <tailnet-IP> and <LAN-subnet>.
"""


def test_docs_guard_tolerates_what_this_repo_publishes_on_purpose():
    """The most important test here: what the scan must NEVER flag.

    A guard that fires on values this repo publishes deliberately gets disabled
    within a week, and a disabled guard protects nothing. The CG-26 queue row
    names this as the failure mode to design against rather than an oversight to
    fix later, so it gets a test with a zero assertion, not a paragraph.

    Every class below is here for a measured reason:

    - **Space / message / thread ids** — `docs/google-cloud-setup.md` step 8
      classifies them non-secret. A high-entropy-segment rule would flag every
      one of them, and a guard that contradicts our own published classification
      loses that argument, correctly.
    - **The author's name and email** — in the authorship metadata of every
      commit. Scrubbing prose cannot remove them, so a rule against them could
      never reach zero findings, and a guard that can never be satisfied is a
      guard that gets deleted. This is also why `PII`'s name arm is deliberately
      NOT ported down here.
    - **Google service-account addresses** — published constants, in the IaC and
      in the setup doc.
    - **Deliberately-fake credentials, as CG-23 and CG-34 write them** — and
      these are the load-bearing ones. `tests/test_adapters.py` is CG-23's and
      `tests/test_log_redaction.py` is CG-34's (PR #33, **merged** onto main
      during this cycle); neither is a file this item may edit, so the scan has
      to tolerate their values BY DESIGN rather than by annotation. The merge
      made that argument better-evidenced rather than moot: both files now sit
      inside the scanned trees, so `test_docs_and_tests_carry_no_real_identity`
      re-proves the tolerance on every run — 26 files, zero findings — where it
      previously rested on a side check. And it would be worse than
      inconvenient if it broke: those files are the tests that PROVE hard rule
      #2 holds — that a webhook URL's key and token never reach a log. Breaking
      them to satisfy this guard would trade a real control for a cosmetic one.
    - **Prose and regex-source mentions of the hosts and headers the rules hunt**
      — 14 `googleusercontent.com` mentions sit in the scanned trees as of this
      commit, 6 of them in this module, and a blunt port would flag every one of
      them. That figure is re-measured, not inherited: the seventeen recorded
      here before counted the bare token and overstated it, as `DOC_AVATAR` now
      explains. The PEM header is discussed
      in three documents, all of them elided or bracketed, so there the armour
      requirement is prophylactic rather than load-bearing (spelled out at
      `DOC_PEM`). Both rules are narrowed — scheme-and-path, `-----` armour — so
      that discussing a rule is not a violation of it. The sample carries all
      three PEM spellings, including the unelided prose form, because that is
      the one a blunt port would actually catch.
    - **Synthetic and elided identifiers** — `users/000…001` clears on `(?!0)`,
      `customers/Cexample1` on the RFC 2606 marker, `customers/C0…` on the
      `{3,}` floor. Each is a different mechanism, and each is used by real
      committed documents.
    - **Addresses, versions and outline numbers** — added with `DOC_PRIVATE_IP`
      (CG-78), and the largest tolerance class of the seven by raw frequency.
      This repo argues about `0.0.0.0` versus a LAN bind across a runbook, a
      spec and two queue rows; quotes a `127.0.0.1` smoke curl; and carries
      version numbers on nearly every page. The RFC 5737 nets are the sharpest
      entry — `192.0.2.x` is what a scrub replaces a real address *with*, so a
      rule that flagged it would fire on its own remedy. All of it clears
      structurally, on the private-range scoping, with no marker word and no
      allowlist. The fire-and-near-miss pairs are asserted directly in
      `test_docs_guard_rejects_a_private_lan_address`; the sample here is what
      proves they also survive the other six rules.
    - **Markdown table rows about tenant fields** — the class `DOC_TENANT_TABLE`
      was added for, sampled in BOTH directions because the rule's precision
      lives entirely in one required backtick. The two mapping rows clear on the
      marker in their replacement cell, which is how every scrub plan in `docs/`
      already writes them. The `DEC-6` row is the false-positive trap: its middle
      cell names both tenant fields and its next cell is a sentence, so a rule
      that did not require the value to be backticked would report the word
      `Path` as a leaked tenant id. Both rows are copied from shapes this repo
      actually commits, not invented for the sample.

    Zero findings, asserted as a whole rather than class by class. A per-class
    version would let a new rule fire on a class nobody thought to enumerate;
    this way the sample is the enumeration, and anything it does not cover shows
    up in the aggregate scan of the repo instead.
    """
    findings = scan_text_for_real_identity(PUBLISHED_ON_PURPOSE, "PUBLISHED_ON_PURPOSE")
    assert not findings, (
        "the scan flagged something this repo publishes on purpose — that is "
        "how guards get disabled:\n"
        + "\n".join(f"  line {lineno}  {rule}  {matched!r}"
                    for _, lineno, rule, matched in findings)
    )


def test_an_inlined_tenant_literal_would_be_flagged_in_this_very_file():
    """Proves the claim `test_guard_rejects_unmarked_tenant_identifiers` makes.

    That test's docstring says: if someone later inlines a real-shaped literal
    instead of composing the bait, the docs/tests scan fires on this very file,
    and that is the feature. An unproven claim in a docstring is a comment, so
    here are the two lines as they read TODAY and as they would read if inlined,
    fed to the same scanner the aggregate test uses.

    This is what incident 2 looked like in source, reconstructed with invented
    values: not an exotic mistake, just the two most natural lines anyone would
    write when a negative case needs something that looks real.
    """
    composed_today = [
        '        "domainId": {"chat": {"user": {"domainId": _TENANT_BAIT}}},',
        '        "customer": {"chat": {"spaces": [{"customer": _CUSTOMER_ID_BAIT}]}},',
    ]
    assert not scan_text_for_real_identity("\n".join(composed_today)), (
        "the composed form is supposed to scan clean — if this fires, the bait "
        "convention has stopped working and this file leaks by construction"
    )

    # Naming note, and the measurement that changed a rule. The obvious name for
    # the second variable below ends in `customer` — and mentioning it in the
    # loop tuple, followed by a comma and the quoted rule name, WAS a
    # DOC_TENANT_ASSIGN match: an identifier ending in a tenant key, then a
    # separator, then a quoted string is precisely the assignment shape the rule
    # hunts, and the rule could not tell a variable name from a JSON key. It
    # fired twice on this item's own source — once on a variable, once on the
    # first draft of THIS comment — and firing twice on one PR is what turns
    # "unlucky names" into "the rule is too wide".
    #
    # So it was narrowed rather than worked around. `DOC_TENANT_ASSIGN` now
    # carries a `(?<!\w)` left boundary: the key must START an identifier, not
    # merely end one. Measured before the change went in — across every scanned
    # file, not one existing finding moved, because every real target shape has
    # a quote, punctuation, whitespace or line-start in front of the key. The
    # variables keep their current names; churning them back would prove
    # nothing.
    #
    # The residual blind spot, stated rather than left to be discovered: a
    # COMPOUND identifier assignment — `tenantDomainId = "<opaque>"` — is now
    # matched by nothing here. For the customer form that is mitigated by
    # `DOC_CUSTOMER`, which needs no lookbehind of its own because its
    # eleven-character literal prefix makes a suffix collision implausible. For
    # a bare `domainId` value it is genuinely uncovered, and that is the price
    # paid for the false-positive class above being gone.
    inlined_domain_line = '        "domainId": {"chat": {"user": {"domainId": "' + _TENANT_BAIT + '"}}},'
    inlined_customer_line = ('        "customer": {"chat": {"spaces": [{"customer": "'
                             + _CUSTOMER_ID_BAIT + '"}]}},')
    for inlined, expected_rule in ((inlined_domain_line, "DOC_TENANT_ASSIGN"),
                                   (inlined_customer_line, "DOC_CUSTOMER")):
        fired = {rule for _, _, rule, _ in scan_text_for_real_identity(inlined)}
        assert expected_rule in fired, (
            f"inlining the bait was supposed to trip {expected_rule} and did "
            f"not; rules that fired: {sorted(fired) or 'none'}"
        )
