"""Envelope, registry, auth, inbox — the offline core."""

import datetime as dt
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from chat_gateway.auth import AuthError, authenticate, mint_key
from chat_gateway.envelope import InboundReply, OutboundMessage
from chat_gateway.inbox import Inbox
from chat_gateway.registry import RegistryError, load_registry

REGISTRY_YAML = """
identities:
  pm-familyworkspace:
    display: "PM · familyworkspace"
    mode: webhook
    webhook_url_env: TEST_HOOK_FW
    space: "spaces/AAA"
  job-hunter:
    display: "Job Hunter"
    mode: webhook
    webhook_url_env: TEST_HOOK_JH
apps:
  aiteam-harness:
    key_env: TEST_KEY_AITEAM
    identities: [pm-familyworkspace]
  job-hunter:
    key_env: TEST_KEY_JH
    identities: [job-hunter]
"""


@pytest.fixture()
def registry(tmp_path):
    p = tmp_path / "registry.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    return load_registry(p)


def test_envelope_validation():
    ok = OutboundMessage(identity="x", text="hello", cards=[{"cardId": "c", "card": {}}],
                         thread_key="t-1")
    assert ok.thread_key == "t-1"
    with pytest.raises(ValidationError):
        OutboundMessage(identity="x", text="")
    with pytest.raises(ValidationError):
        OutboundMessage(identity="x", text="hi", cards=[{"nope": 1}])
    with pytest.raises(ValidationError):
        OutboundMessage(identity="x", text="hi", thread_key="   ")


def test_registry_validation_errors(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("identities:\n  a:\n    mode: webhook\napps: {}\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="webhook_url_env"):
        load_registry(bad)
    bad.write_text(
        "identities: {}\napps:\n  x:\n    key_env: K\n    identities: [ghost]\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryError, match="unknown identity"):
        load_registry(bad)


def test_identity_permissions(registry):
    ident = registry.identity_for("aiteam-harness", "pm-familyworkspace")
    assert ident.display.startswith("PM")
    with pytest.raises(RegistryError, match="may not send as"):
        registry.identity_for("job-hunter", "pm-familyworkspace")
    with pytest.raises(RegistryError, match="unknown app"):
        registry.identity_for("nope", "job-hunter")


def test_env_indirection_and_health(registry, monkeypatch):
    ident = registry.identities["pm-familyworkspace"]
    with pytest.raises(RegistryError, match="TEST_HOOK_FW"):
        ident.webhook_url()
    monkeypatch.setenv("TEST_HOOK_FW", "https://chat.googleapis.com/v1/spaces/AAA/messages?key=k")
    assert ident.webhook_url().endswith("key=k")
    health = registry.health()
    assert health["identities"]["pm-familyworkspace"]["env_resolved"] is True
    assert health["identities"]["job-hunter"]["env_resolved"] is False
    assert health["apps"]["aiteam-harness"]["key_configured"] is False


def test_space_routing(registry):
    assert registry.apps_for_space("spaces/AAA") == ["aiteam-harness"]
    assert registry.apps_for_space("spaces/ZZZ") == []
    assert registry.apps_for_space("") == []


def test_auth_constant_time_lookup(registry, monkeypatch):
    key = mint_key()
    assert key.startswith("cgk_") and len(key) > 30
    monkeypatch.setenv("TEST_KEY_AITEAM", key)
    assert authenticate(registry, f"Bearer {key}") == "aiteam-harness"
    with pytest.raises(AuthError):
        authenticate(registry, "Bearer wrong")
    with pytest.raises(AuthError):
        authenticate(registry, None)
    with pytest.raises(AuthError):
        authenticate(registry, "Basic abc")


def test_inbox_poll_clears_and_audits(tmp_path):
    inbox = Inbox(audit_dir=tmp_path / "audit")
    reply = InboundReply(app="aiteam-harness", space="spaces/AAA", text="ship it",
                         received_at=dt.datetime(2026, 7, 24, 1, 0, tzinfo=dt.timezone.utc))
    inbox.put(reply)
    inbox.put(reply.model_copy(update={"text": "second"}))
    assert inbox.pending_counts() == {"aiteam-harness": 2}
    polled = inbox.poll("aiteam-harness")
    assert [r.text for r in polled] == ["ship it", "second"]
    assert inbox.poll("aiteam-harness") == []
    audit_files = list((tmp_path / "audit").glob("aiteam-harness-*.jsonl"))
    assert len(audit_files) == 1
    assert audit_files[0].read_text(encoding="utf-8").count("\n") == 2


def test_inbox_overflow_drops_oldest():
    inbox = Inbox(max_pending=2)
    now = dt.datetime.now(dt.timezone.utc)
    for i in range(4):
        inbox.put(InboundReply(app="a", space="s", text=str(i), received_at=now))
    polled = inbox.poll("a")
    assert [r.text for r in polled] == ["2", "3"]
    assert inbox.dropped == 2


# --- reserved app ids (CG-8) --------------------------------------------------


def test_reserved_app_ids_are_rejected(tmp_path):
    """`_unrouted` is the audit bucket for unroutable and UNPARSEABLE events,
    and the paths that write to it bypass the per-app authorization block by
    design. An app registered under it would drain every one of them, from every
    space. Pre-existing hole; needs a misconfiguration; real in a multi-tenant
    transport."""
    from chat_gateway.registry import UNROUTED

    for bad_id in (UNROUTED, "_internal", "_"):
        p = tmp_path / "r.yaml"
        p.write_text(
            "identities:\n"
            "  pm:\n"
            "    display: PM\n"
            "    webhook_url_env: HOOK\n"
            "apps:\n"
            f"  {bad_id}:\n"
            "    key_env: KEY\n"
            "    identities: [pm]\n"
            "    allow_inbound: true\n",
            encoding="utf-8",
        )
        with pytest.raises(RegistryError) as exc:
            load_registry(p)
        assert "reserved" in str(exc.value)
        assert "hard rule #6" in str(exc.value)


def test_ordinary_app_ids_with_underscores_still_load(tmp_path):
    """Only the PREFIX is reserved — `aiteam_harness` must keep working."""
    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n"
        "  pm:\n"
        "    display: PM\n"
        "    webhook_url_env: HOOK\n"
        "apps:\n"
        "  aiteam_harness:\n"
        "    key_env: KEY\n"
        "    identities: [pm]\n",
        encoding="utf-8",
    )
    assert "aiteam_harness" in load_registry(p).apps


def test_unrouted_still_importable_from_the_adapter(tmp_path):
    """The constant moved to core; the adapter re-exports it. Existing call
    sites import it from the adapter and must not break."""
    from chat_gateway.adapters.pubsub import UNROUTED as from_adapter
    from chat_gateway.registry import UNROUTED as from_core

    assert from_adapter is from_core == "_unrouted"


def test_the_hole_CG8_closes_is_real_and_now_shut(tmp_path, monkeypatch):
    """Not just "the id is rejected" — prove WHAT it would have drained.

    The plan's tests assert the rejection. This one demonstrates the
    consequence, because a reader six months from now will want to know whether
    the guard is protecting against something real or is defensive noise.

    Registers `_unrouted` as a normal-looking tenant with allow_inbound: true,
    bypasses the registry guard to build it anyway, and shows that an
    UNPARSEABLE event from a space that tenant owns NOTHING in still lands in
    its inbox — with no hard-rule-#6 authorization check having run.
    """
    from chat_gateway.adapters.pubsub import UNROUTED, dispatch
    from chat_gateway.inbox import Inbox
    from chat_gateway.registry import App, Registry

    monkeypatch.setenv("KEY", "cgk_x")
    monkeypatch.setenv("HOOK", "https://x.example/h")

    # Construct what the registry now REFUSES to load, to show why it refuses.
    attacker = App(app_id=UNROUTED, key_env="KEY", identities=[],
                   allow_inbound=True)
    reg = Registry(identities={}, apps={UNROUTED: attacker})
    inbox = Inbox()

    # An event the gateway cannot parse — no space, so nothing to authorize on.
    dispatch({"totally": "unrecognized"}, reg, inbox)

    stolen = inbox.poll(UNROUTED)
    assert stolen, "the hole is not real — this test would be pointless"
    # It arrives as a pollable InboundReply attributed to this app, i.e. exactly
    # what GET /v1/inbox would hand a caller holding that app's key.
    assert stolen[0].app == UNROUTED
    assert stolen[0].event_type == "UNPARSEABLE"
    # ...and that is precisely why the id may no longer be registered:
    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n  pm:\n    display: PM\n    webhook_url_env: HOOK\n"
        f"apps:\n  {UNROUTED}:\n    key_env: KEY\n    identities: [pm]\n"
        "    allow_inbound: true\n", encoding="utf-8")
    with pytest.raises(RegistryError):
        load_registry(p)


def test_registry_ids_must_be_clean_strings(tmp_path):
    """A REGRESSION GUARD, and the regression was CG-8's own.

    CG-8 added `app_id.startswith(RESERVED_APP_ID_PREFIX)`. YAML coerces
    unquoted mapping keys, so `1:` is an int, `true:` a bool, `null:` a None and
    `1.5:` a float — and `.startswith` on any of those raises AttributeError,
    which escapes load_registry as an unhandled traceback rather than the config
    error an operator can act on. Adding a validation guard must not turn a
    tolerable misconfiguration into a crash at startup.

    Whitespace is checked in the same place for a related reason: `" aitrader"`
    is a different dict key from `"aitrader"` and looks identical in review, so
    it would silently fail to match the id the consuming app sends — a per-app
    allowlist that quietly matches nothing (hard rule #4).
    """
    head = ("identities:\n  pm:\n    display: PM\n    webhook_url_env: HOOK\n")
    coerced = ["  1:\n    key_env: KEY\n", "  true:\n    key_env: KEY\n",
               "  null:\n    key_env: KEY\n", "  1.5:\n    key_env: KEY\n"]
    for body in coerced:
        p = tmp_path / "r.yaml"
        p.write_text(head + "apps:\n" + body, encoding="utf-8")
        with pytest.raises(RegistryError) as exc:      # NOT AttributeError
            load_registry(p)
        assert "must be a string" in str(exc.value)

    for bad in (" _sneaky", "aitrader ", " pm"):
        p = tmp_path / "r.yaml"
        p.write_text(head + f'apps:\n  "{bad}":\n    key_env: KEY\n', encoding="utf-8")
        with pytest.raises(RegistryError) as exc:
            load_registry(p)
        assert "whitespace" in str(exc.value)

    # identities get the same treatment — they are cross-referenced by each
    # app's `identities:` list, so a coerced name breaks that lookup invisibly.
    p = tmp_path / "r.yaml"
    p.write_text("identities:\n  1:\n    display: X\n    webhook_url_env: H\napps: {}\n",
                 encoding="utf-8")
    with pytest.raises(RegistryError) as exc:
        load_registry(p)
    assert "identity id" in str(exc.value) and "must be a string" in str(exc.value)


HEAD_YAML = "identities:\n  pm:\n    display: PM\n    webhook_url_env: HOOK\n"

# Every way a registry file can be malformed that used to escape as something
# other than RegistryError. Two distinct causes: the coerced/odd keys reached
# CG-8's new prefix guard and died in `.startswith`, and the YAML-level failures
# escaped because only OSError was caught around `yaml.safe_load`.
MALFORMED_REGISTRIES = [
    pytest.param("apps:\n  ? [a, b]\n  : key_env: KEY\n", id="unhashable-seq-key"),
    pytest.param("apps:\n  ? {a: 1}\n  : key_env: KEY\n", id="unhashable-map-key"),
    pytest.param("apps:\n  2026-07-30:\n    key_env: KEY\n", id="yaml-date-key"),
    pytest.param('apps:\n  "":\n    key_env: KEY\n', id="empty-id"),
    pytest.param("apps:\n  1:\n    key_env: KEY\n", id="int-key"),
    pytest.param("apps:\n  true:\n    key_env: KEY\n", id="bool-key"),
    pytest.param("apps:\n  null:\n    key_env: KEY\n", id="null-key"),
    pytest.param('apps:\n  "\tx":\n    key_env: KEY\n', id="tab-padded-key"),
    pytest.param("apps:\n  x:\n   - [unclosed\n", id="unparseable-yaml"),
]


@pytest.mark.parametrize("body", MALFORMED_REGISTRIES)
def test_every_malformed_registry_arrives_as_RegistryError(tmp_path, body):
    """No config mistake may reach the operator as a raw traceback.

    Hard rule #5's spirit applied to startup: a gateway that dies with a yaml
    ScannerError, a ConstructorError or an AttributeError has told the operator
    almost nothing about which file is wrong or why. Parameterized so a future
    edge case gets ADDED to this list rather than handled somewhere new.
    """
    p = tmp_path / "r.yaml"
    p.write_text(HEAD_YAML + body, encoding="utf-8")
    with pytest.raises(RegistryError):
        load_registry(p)


def test_a_valid_registry_still_loads(tmp_path):
    """The control for the test above — it must discriminate, not just reject."""
    p = tmp_path / "r.yaml"
    p.write_text(HEAD_YAML + "apps:\n  aiteam_harness:\n    key_env: KEY\n"
                 "    identities: [pm]\n", encoding="utf-8")
    assert "aiteam_harness" in load_registry(p).apps


# ---------------------------------------------------------------------------
# CG-88 — `allow_inbound` defaults to DENY, and the DEFAULT is the guarantee
# ---------------------------------------------------------------------------
#
# Until 2026-08-31 the field defaulted to `True`: an app that never mentioned
# inbound HAD it. `aiteam-harness` ran open for its whole life for exactly that
# reason (CG-61), and `docs/consumers/aitrader.md` §8's no-inbound guarantee for
# a real-money tenant was held by ONE `allow_inbound: false` line in a file with
# three copies, only one of them in git.
#
# ⚠ EVERY CONTROL BELOW THAT CLAIMS TO BIND THE DEFAULT USES A FIXTURE THAT
# OMITS THE KEY. A test asserting `allow_inbound is False` against an entry that
# WROTE `false` passes identically under either default and binds nothing (0h) —
# which is why the first assertion in the first test is about the fixture's
# silence rather than about the registry.

COMMITTED_EXAMPLE = (Path(__file__).resolve().parents[1]
                     / "config" / "registry.example.yaml")


def test_allow_inbound_defaults_to_DENY_when_the_entry_says_nothing(registry):
    """The default itself, on a fixture that states no posture at all.

    `REGISTRY_YAML` at the top of this file deliberately writes no
    `allow_inbound` for either app, and that silence is what makes this a
    control rather than a restatement of a YAML line. It is asserted, so a
    future edit that "tidies" the fixture by writing the key explicitly turns
    this test red instead of quietly emptying it.
    """
    assert "allow_inbound" not in REGISTRY_YAML, (
        "this control binds only while the fixture stays silent — an explicit "
        "value here would make it pass under a permissive default too"
    )
    assert registry.apps["aiteam-harness"].allow_inbound is False
    assert registry.apps["job-hunter"].allow_inbound is False


def test_the_DATACLASS_default_denies_too_and_that_is_a_second_site(tmp_path):
    """The constructor default, which the loader no longer exercises.

    ⚠ MEASURED, and it is why this test exists: flipping
    `App.allow_inbound: bool = False` back to `True` left the entire suite
    GREEN. `load_registry` passes the field explicitly on every path, so the
    dataclass default governs only hand-built `App` objects — which
    `tests/test_core.py` and `tests/test_durability.py` both construct, and
    neither stated the field. Under 0h that default had not been shown to bind
    anything, so the flip was a free re-widening waiting for whoever writes the
    next in-process consumer.

    Two sites, two controls: the loader's is
    `test_allow_inbound_defaults_to_DENY_when_the_entry_says_nothing`, and this
    is the other one.
    """
    from chat_gateway.registry import App

    assert App(app_id="built-by-hand", key_env="K").allow_inbound is False


def test_the_reliance_is_REPORTED_and_a_written_value_is_not(tmp_path):
    """`inbound_defaulted` names the apps whose posture the loader chose.

    Two cases that are indistinguishable once loaded — an app that wrote
    `false` and an app that wrote nothing both end up `False` — and only the
    second is a reliance. Reporting it is the half of "make the key required"
    that cannot take a running gateway down; the other half was declined
    because the NAS registry copy cannot be read from here. (ONE copy, not two:
    the dev-box file is gitignored but present and readable on this machine.)
    """
    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n  pm:\n    display: PM\n    webhook_url_env: HOOK\n"
        "apps:\n"
        "  silent:\n    key_env: K1\n    identities: [pm]\n"
        "  wrote-false:\n    key_env: K2\n    identities: [pm]\n"
        "    allow_inbound: false\n"
        "  wrote-true:\n    key_env: K3\n    identities: [pm]\n"
        "    allow_inbound: true\n", encoding="utf-8")
    reg = load_registry(p)

    assert reg.apps["silent"].allow_inbound is False
    assert reg.apps["wrote-false"].allow_inbound is False
    assert reg.apps["wrote-true"].allow_inbound is True
    # Only the silent one, and the list is sorted so the report is stable.
    assert reg.inbound_defaulted == ["silent"]
    assert reg.health()["inbound_defaulted"] == ["silent"]


def test_an_explicit_null_states_no_posture_and_is_treated_as_absent(tmp_path):
    """`allow_inbound:` with nothing after it is silence, not a decision.

    YAML gives it `None`. Reading that as "written" would let an empty key
    stand in for a posture nobody chose, which is the defect one layer in.

    ⚠ THE FIRST ASSERTION BELOW DOES NOT DISCRIMINATE, AND SAYING SO IS THE
    POINT — found in pre-merge review, and MEASURED against the old loader
    rather than reasoned about. `bool(spec.get("allow_inbound", True))` returns
    the STORED value when the key is present, so an explicit null was already
    `bool(None)` = False before CG-88. What binds here is the second assertion:
    `inbound_defaulted` does not exist pre-CG-88 at all.

    ⚠ And the measurement found something worth keeping. The OLD loader denied
    an explicit null and GRANTED an absent key — two answers to one question,
    since neither states a posture. Nobody chose that; it fell out of
    `dict.get`'s two meanings for "missing". The new loader gives one answer to
    both, which is why they share this code path.
    """
    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n  pm:\n    display: PM\n    webhook_url_env: HOOK\n"
        "apps:\n  hollow:\n    key_env: K\n    identities: [pm]\n"
        "    allow_inbound:\n", encoding="utf-8")
    reg = load_registry(p)
    assert reg.apps["hollow"].allow_inbound is False
    assert reg.inbound_defaulted == ["hollow"]


@pytest.mark.parametrize("written", ['"false"', '"true"', "0", "1", '"yes"', "[]"])
def test_a_non_boolean_allow_inbound_is_REFUSED_rather_than_coerced(tmp_path, written):
    """The other half of the same fail-open, arriving through the VALUE.

    `bool("false")` is True, so the old `bool(spec.get(...))` would have granted
    inbound to an entry that spelled the refusal — the "reformatted away" case,
    since quoting a scalar is something a formatter or a templating pass does
    without asking. A default-deny a stray pair of quotes can flip is not a
    guarantee.

    Refusing rather than coercing is this file's existing treatment of YAML
    coercion traps: `_require_id_str` refuses a non-string key instead of
    calling `str()` on it.
    """
    assert bool("false") is True, "the coercion this refusal exists to prevent"
    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n  pm:\n    display: PM\n    webhook_url_env: HOOK\n"
        f"apps:\n  a:\n    key_env: K\n    identities: [pm]\n"
        f"    allow_inbound: {written}\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="must be a YAML boolean"):
        load_registry(p)


def test_an_unquoted_yaml_boolean_is_still_accepted_in_both_spellings(tmp_path):
    """The control for the test above: the refusal must DISCRIMINATE.

    PyYAML resolves `yes`/`no`/`on`/`off` to real booleans, so those are
    written values and not coercions. A refusal that also rejected them would
    be a refusal nobody could satisfy without knowing which spellings survived.
    """
    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n  pm:\n    display: PM\n    webhook_url_env: HOOK\n"
        "apps:\n"
        "  yes-app:\n    key_env: K1\n    identities: [pm]\n    allow_inbound: yes\n"
        "  no-app:\n    key_env: K2\n    identities: [pm]\n    allow_inbound: no\n",
        encoding="utf-8")
    reg = load_registry(p)
    assert reg.apps["yes-app"].allow_inbound is True
    assert reg.apps["no-app"].allow_inbound is False
    assert reg.inbound_defaulted == []


# --- the published guarantee, pinned against the one registry that is in git --

def _example_with_line_removed(app_id: str, key: str) -> tuple[str, int]:
    """Return the committed example minus one `key:` line from one app's block.

    Structural rather than a string replace, so it cannot silently match the
    same key under a different app. The count is returned and asserted by every
    caller: a helper that removed nothing would leave the test passing against
    the file it was supposed to have damaged.

    ⚠ Known and currently harmless (pre-merge review, 2026-08-31): the
    block-boundary test also fires on a 2-space-indented COMMENT ending in a
    colon, and the example file has one immediately above `aitrader:`. That
    transiently clears `in_app`, and the real header on the next line restores
    it. A comment of that shape landing BETWEEN an app header and the targeted
    key would suppress the removal — and `assert removed == 1` fails the test
    rather than passing it quietly, which is the property that makes leaving
    this alone acceptable.
    """
    text = COMMITTED_EXAMPLE.read_text(encoding="utf-8")
    out, removed, in_app, in_apps = [], 0, False, False
    for line in text.splitlines(keepends=True):
        if line.rstrip("\n") == "apps:":
            in_apps, in_app = True, False
        elif in_apps and line.startswith("  ") and not line.startswith("   ") \
                and line.strip().endswith(":"):
            in_app = line.strip() == f"{app_id}:"
        if in_app and line.strip().startswith(f"{key}:"):
            removed += 1
            continue
        out.append(line)
    return "".join(out), removed


def test_aitraders_no_inbound_guarantee_survives_losing_its_own_registry_line(tmp_path):
    """`docs/consumers/aitrader.md` §8, on its NEW basis.

    Before CG-88 that guarantee was one YAML line — in a file with three
    copies, only one of them in git, and whose install step overwrites the box's
    copy with this checkout's. Dropped, reformatted away or missing from a copy,
    its absence INVERTED the guarantee in silence. This deletes exactly that
    line from the committed template and asserts the answer does not move.
    """
    text, removed = _example_with_line_removed("aitrader", "allow_inbound")
    assert removed == 1, (
        "the fixture did not damage the file it claims to have damaged — "
        "either aitrader's entry moved or the helper stopped finding it"
    )
    assert "allow_inbound" not in text.split("  aitrader:")[1]

    p = tmp_path / "example-minus-one-line.yaml"
    p.write_text(text, encoding="utf-8")
    reg = load_registry(p)

    assert reg.apps["aitrader"].allow_inbound is False
    # ...and the loss is reported rather than merely survived, which is what an
    # operator diffing two registry copies needs to see.
    assert "aitrader" in reg.inbound_defaulted


def test_the_committed_example_states_every_apps_inbound_posture(tmp_path):
    """The belt beside CG-88's braces, and the template's own honesty.

    The default now makes silence safe; it does not make silence GOOD. The
    committed example is what a fresh deployment copies, so an app there that
    says nothing about inbound teaches the next operator to say nothing either —
    and `job-hunter` is a two-way tenant whose live entry writes `true`. An
    empty `inbound_defaulted` is the machine-checkable form of "this template
    states its own posture".
    """
    reg = load_registry(COMMITTED_EXAMPLE)
    assert reg.inbound_defaulted == [], (
        "these apps in registry.example.yaml leave their inbound posture to the "
        f"loader: {reg.inbound_defaulted}"
    )
    assert reg.apps["aitrader"].allow_inbound is False
    assert reg.apps["aiteam-harness"].allow_inbound is False
    assert reg.apps["agent-mcp"].allow_inbound is False
    assert reg.apps["job-hunter"].allow_inbound is True


def test_check_names_the_apps_that_relied_on_the_default_on_STDERR(tmp_path, monkeypatch, capsys):
    """The loud half, end to end through `main(["check"])`.

    stderr and not stdout, because `check`'s stdout is machine-readable JSON one
    branch later and a warning inside a `| jq` pipeline is a warning somebody
    silences. The JSON carries the same list on every run, so the always-on
    channel is the report and the console line is the prompt.
    """
    from chat_gateway.__main__ import main

    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n  pm:\n    display: PM\n    webhook_url_env: HOOK\n"
        "apps:\n"
        "  silent:\n    key_env: K1\n    identities: [pm]\n"
        "  stated:\n    key_env: K2\n    identities: [pm]\n"
        "    allow_inbound: false\n", encoding="utf-8")
    monkeypatch.setenv("CHAT_GATEWAY_REGISTRY", str(p))
    monkeypatch.setenv("CHAT_GATEWAY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHAT_GATEWAY_INBOX_DIR", str(tmp_path / "inbox-data"))
    monkeypatch.delenv("CHAT_GATEWAY_ENV_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("GATEWAY_ENABLE_PUBSUB", raising=False)

    assert main(["check"]) == 0
    captured = capsys.readouterr()
    assert "silent" in captured.err and "DENY" in captured.err
    assert "stated" not in captured.err, "an app that wrote its posture is not a reliance"
    assert "WARNING" not in captured.out, "the warning must not contaminate the JSON"
    assert json.loads(captured.out)["apps"]["silent"]["key_configured"] is False
    assert json.loads(captured.out)["inbound_defaulted"] == ["silent"]


def test_check_is_SILENT_when_every_app_states_its_own_posture(tmp_path, monkeypatch, capsys):
    """The control for the test above — the warning must discriminate.

    A line that prints on every boot is a line an operator stops reading, which
    is this repo's own recorded reason for not degrading `/healthz` on a
    guarantee that is working.
    """
    from chat_gateway.__main__ import main

    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n  pm:\n    display: PM\n    webhook_url_env: HOOK\n"
        "apps:\n  stated:\n    key_env: K\n    identities: [pm]\n"
        "    allow_inbound: false\n", encoding="utf-8")
    monkeypatch.setenv("CHAT_GATEWAY_REGISTRY", str(p))
    monkeypatch.setenv("CHAT_GATEWAY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHAT_GATEWAY_INBOX_DIR", str(tmp_path / "inbox-data"))
    monkeypatch.delenv("CHAT_GATEWAY_ENV_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("GATEWAY_ENABLE_PUBSUB", raising=False)

    assert main(["check"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["inbound_defaulted"] == []


def test_a_callback_url_with_no_allow_inbound_now_refuses_AND_says_what_changed(tmp_path):
    """CG-88's one realistic outage path, pinned with the mitigation.

    MEASURED against both loaders on 2026-08-31: this registry LOADED on `main`
    — inbound on, by the old default — and refuses here. `load_registry`
    raising means `build_runtime` raises and `main` exits 2, so the gateway does
    not start. Unlike a quoted boolean, this shape is producible by OMISSION.

    The refusal therefore has to name what changed under the operator's feet,
    because the unhinted message sends them looking for a flag that is not in
    the file.
    """
    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n  pm:\n    display: PM\n    webhook_url_env: HOOK\n"
        "apps:\n  two-way:\n    key_env: K\n    identities: [pm]\n"
        '    callback_url: "http://127.0.0.1:8710/chat-callback"\n',
        encoding="utf-8")
    with pytest.raises(RegistryError) as exc:
        load_registry(p)
    assert "callback_url requires allow_inbound: true" in str(exc.value)
    assert "not written for this app at all" in str(exc.value)
    assert "CG-88" in str(exc.value)


def test_the_hint_does_NOT_fire_for_a_tenant_that_wrote_its_refusal(tmp_path):
    """`docs/consumers/aitrader.md` §8 enforcement point 2 quotes this message
    verbatim, and that tenant WRITES `allow_inbound: false`.

    So the hint must be appended, never woven in: an entry that stated its
    posture is not a victim of the default change, and telling it about CG-88
    would be both wrong and a silent edit to a quoted published guarantee.
    """
    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n  pm:\n    display: PM\n    webhook_url_env: HOOK\n"
        "apps:\n  aitrader:\n    key_env: K\n    identities: [pm]\n"
        "    allow_inbound: false\n"
        '    callback_url: "http://127.0.0.1:8710/chat-callback"\n',
        encoding="utf-8")
    with pytest.raises(RegistryError) as exc:
        load_registry(p)
    assert str(exc.value) == (
        "app 'aitrader': callback_url requires allow_inbound: true — "
        "an opted-out tenant gets NO inbound path (hard rule #6)"
    )
    quoted = (Path(__file__).resolve().parents[1]
              / "docs" / "consumers" / "aitrader.md").read_text(encoding="utf-8")
    assert str(exc.value) in quoted, (
        "aitrader.md §8 quotes this message verbatim — the quotation and the "
        "code have to move together or the published guarantee cites bytes "
        "the gateway no longer emits"
    )


def test_the_directory_form_reports_reliance_and_refuses_a_non_boolean(tmp_path):
    """jobhunt R1's one-file-per-tenant form, which has its own loader branch.

    The per-app loop is shared, so this cannot diverge by construction — but
    "cannot diverge by construction" is the sentence that precedes a divergence,
    and the directory branch builds `data` itself. Named in pre-merge review as
    the one path with no coverage of CG-88's behaviour.
    """
    d = tmp_path / "reg"
    d.mkdir()
    (d / "a.yaml").write_text(
        "identities:\n  pm:\n    display: PM\n    webhook_url_env: HOOK\n"
        "apps:\n  silent-tenant:\n    key_env: K1\n    identities: [pm]\n",
        encoding="utf-8")
    (d / "b.yaml").write_text(
        "apps:\n  stated-tenant:\n    key_env: K2\n    identities: [pm]\n"
        "    allow_inbound: true\n", encoding="utf-8")
    reg = load_registry(d)
    assert reg.apps["silent-tenant"].allow_inbound is False
    assert reg.apps["stated-tenant"].allow_inbound is True
    assert reg.inbound_defaulted == ["silent-tenant"]

    (d / "c.yaml").write_text(
        "apps:\n  quoted-tenant:\n    key_env: K3\n    identities: [pm]\n"
        '    allow_inbound: "false"\n', encoding="utf-8")
    with pytest.raises(RegistryError, match="must be a YAML boolean"):
        load_registry(d)


def test_the_report_is_SORTED_and_health_hands_out_a_COPY(tmp_path):
    """Two properties of CG-88's own code that were claimed and unbound (0h).

    Found in pre-merge review by mutation: `sorted(inbound_defaulted)` →
    `list(...)` left the whole suite green, and so did dropping `health()`'s
    defensive `list(...)`. Both were invisible for the same reason — every other
    fixture has exactly ONE defaulted app, where sortedness and aliasing are
    equally unobservable. **A one-element fixture cannot fail an ordering
    claim**, which is the same shape as the repo's own note that a one-horizon
    fixture would silently un-bind a value-equality test.

    So this fixture has TWO silent apps, written in reverse-alphabetical order
    in the YAML so insertion order and sorted order genuinely differ.
    """
    p = tmp_path / "r.yaml"
    p.write_text(
        "identities:\n  pm:\n    display: PM\n    webhook_url_env: HOOK\n"
        "apps:\n"
        "  zzz-silent:\n    key_env: K1\n    identities: [pm]\n"
        "  aaa-silent:\n    key_env: K2\n    identities: [pm]\n"
        "  mmm-stated:\n    key_env: K3\n    identities: [pm]\n"
        "    allow_inbound: false\n", encoding="utf-8")
    reg = load_registry(p)

    assert reg.inbound_defaulted == ["aaa-silent", "zzz-silent"], (
        "the report is sorted, so two operators diffing two boxes compare two "
        "lists rather than two YAML orderings"
    )
    published = reg.health()["inbound_defaulted"]
    assert published == ["aaa-silent", "zzz-silent"]
    assert published is not reg.inbound_defaulted, (
        "health() hands out a copy — a caller that mutates the published list "
        "must not reach into the loaded registry"
    )
