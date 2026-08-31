"""Identity + app registry: parse, validate, and resolve env-indirected secrets.

The committed registry holds environment-variable NAMES; values (webhook URLs
embed key+token; API keys are credentials) live only in the runtime env.
Resolution is lazy and per-use, so `healthz` can report which identities are
resolvable without ever exposing values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CHANNELS = ["google_chat"]
MODES = ["webhook", "app"]

# App ids the gateway reserves for its own audit buckets. `_unrouted` is where
# unroutable and UNPARSEABLE events are filed, and the paths that write to it —
# the except branch in dispatch(), and the `or [UNROUTED]` fallback — bypass the
# per-app authorization block BY DESIGN, because an unparseable event has no
# space and cannot be authorized against anything. An app registered under that
# id with allow_inbound: true would therefore drain every unroutable and every
# UNPARSEABLE event from every space through /v1/inbox, with no hard-rule-#6
# check ever running.
#
# The whole `_` prefix is reserved, not just the one literal, so the next
# internal bucket is safe without anyone remembering to add it here.
#
# This constant lives in core, not in adapters/pubsub.py where it started:
# registry.py must not import from an adapter (hard rule #3 puts Google-facing
# code in adapters/, and core reaching into it inverts the layering). The
# adapter imports it from here, which is the direction that already exists.
UNROUTED = "_unrouted"
RESERVED_APP_ID_PREFIX = "_"


class RegistryError(ValueError):
    pass


def _require_id_str(kind: str, value) -> None:
    """Registry keys must be clean strings, and say so as a config error.

    Two failure modes, both invisible in a YAML diff and neither worth debugging
    twice:

    * **Not a string.** YAML coerces unquoted keys, so `1:` is an `int`, `true:`
      a `bool`, `null:` a `None`, `1.5:` a `float`. Every id is compared as text
      — against an API key's owner, against reserved prefixes, against an app's
      identity allowlist — so a non-string id cannot be validated at all.
    * **Surrounding whitespace.** `" aitrader"` is a different key from
      `"aitrader"` and looks identical in review. It would silently fail to match
      the id the consuming app sends, and a per-app allowlist that quietly
      matches nothing is precisely the shape hard rule #4 exists to prevent.
    """
    if isinstance(value, str) and not value:
        raise RegistryError(
            f"{kind} id is the empty string. Every id is a name something else "
            "refers to — an API key's owner, an app's identity allowlist — and "
            "nothing can refer to an unnamed entry."
        )
    if not isinstance(value, str):
        raise RegistryError(
            f"{kind} id {value!r} must be a string, not {type(value).__name__} — "
            "YAML coerces unquoted keys (`1:`, `true:`, `null:`), so quote it. "
            "Ids are matched as text everywhere, including against the reserved "
            "prefix and each app's identity allowlist."
        )
    if value != value.strip():
        raise RegistryError(
            f"{kind} id {value!r} has leading or trailing whitespace. It is a "
            "different key from the trimmed form and identical in review, so it "
            "would silently fail to match the id the app actually sends."
        )


def _require_bool(app_id: str, key: str, value) -> None:
    """A security boolean is never coerced, because coercion inverts it.

    `bool("false")` is **True**. YAML gives an unquoted `false` a real `bool`,
    but a quoted one — `allow_inbound: "false"` — is a three-character string,
    and every truthiness test in Python says yes to it. The old loader did
    `bool(spec.get("allow_inbound", True))`, so a registry that SPELLED the
    refusal would have opened the path anyway, silently, with the file reading
    exactly as its author intended.

    That is the same defect the default carried (CG-88), arriving through the
    value rather than through its absence, and it is the "reformatted away"
    half: quoting a scalar is the kind of thing a YAML formatter or a
    templating pass does without asking. A default-deny that a stray pair of
    quotes can still flip is not a guarantee.

    Refusing rather than coercing is this file's existing treatment of YAML's
    coercion traps — `_require_id_str` above refuses a non-string key instead
    of calling `str()` on it, for the same reason. The cost is stated where it
    is taken: a live registry carrying a quoted boolean stops loading, which
    under PR 4's R1-B is a supported steady state on this gateway (reads serve,
    nothing crosses) and prints `config error:` naming the app and the fix.
    """
    if not isinstance(value, bool):
        raise RegistryError(
            f"app {app_id!r}: {key} must be a YAML boolean (true/false), not "
            f"{type(value).__name__} {value!r}. Refused rather than coerced, "
            f'because coercion inverts it: `{key}: "false"` is a non-empty '
            "STRING, which is truthy — it would grant what it appears to refuse."
        )


@dataclass
class Identity:
    name: str
    display: str
    channel: str = "google_chat"
    mode: str = "webhook"
    webhook_url_env: str | None = None
    space: str = ""

    def webhook_url(self) -> str:
        if not self.webhook_url_env:
            raise RegistryError(f"identity {self.name!r} has no webhook_url_env")
        url = os.environ.get(self.webhook_url_env, "")
        if not url:
            raise RegistryError(
                f"env var {self.webhook_url_env} (webhook for identity {self.name!r}) is not set"
            )
        return url

    def env_resolved(self) -> bool:
        if self.mode == "webhook":
            return bool(self.webhook_url_env and os.environ.get(self.webhook_url_env))
        return bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))


SEVERITIES = ["alert", "warning", "info"]


@dataclass
class App:
    app_id: str
    key_env: str
    identities: list[str] = field(default_factory=list)
    # CG-88. DEFAULT-DENY, and the default is the guarantee — not the YAML line.
    #
    # This defaulted to `True` until 2026-08-31, so an app that never mentioned
    # inbound HAD it: `aiteam-harness` ran open for its whole life for exactly
    # that reason, which is why CG-61 exists. Hard rule #6 says inbound crosses
    # "only by that consumer's explicit registry opt-in"; with a permissive
    # default that sentence was aspirational, and it is now mechanical.
    #
    # It matters most where a guarantee is published. `docs/consumers/aitrader.md`
    # §8 promises a real-money tenant NO inbound path; before this that promise
    # was held by one `allow_inbound: false` line in a file with THREE copies,
    # only one of them in git (`docs/consumers/pmtrader-registration-handoff.md`
    # §6). Dropped, reformatted, or missing from a copy, the line's absence used
    # to INVERT the guarantee in silence. Absence is now the safe answer.
    #
    # NOT made required-with-no-default, which is the stronger shape this repo
    # family usually reaches for: a registry omitting the key would then refuse
    # to load, and `docs/deploy/nas.md`'s install step overwrites the box's
    # registry with this checkout's copy. Neither of the two off-repo copies is
    # readable from here, so that trade was refused rather than taken blind.
    # What replaces it is `Registry.inbound_defaulted` below — the reliance is
    # reported instead of being fatal.
    allow_inbound: bool = False
    routes: dict[str, str] = field(default_factory=dict)  # severity -> identity (/v1/notify)
    callback_url: str = ""            # inbound push (tenant opt-in; requires allow_inbound)
    allowed_users: list[str] = field(default_factory=list)  # emails; empty = no restriction
    unreachable_message: str = ""     # in-thread text when the callback is down (R7)

    def key_configured(self) -> bool:
        return bool(os.environ.get(self.key_env))

    def resolved_callback_url(self) -> str:
        url = self.callback_url
        if url.startswith("${") and url.endswith("}"):
            url = os.environ.get(url[2:-1], "")
        return url


@dataclass
class Registry:
    identities: dict[str, Identity]
    apps: dict[str, App]
    #: App ids whose entry said nothing about `allow_inbound` and therefore
    #: inherited the default (CG-88). Empty is the correct state; a non-empty
    #: list is a registry whose inbound posture is held by a loader default
    #: rather than by anything an author wrote — which is what made
    #: `aiteam-harness` open for its whole life.
    #:
    #: Reported, never enforced: it is the half of "make it required" that
    #: cannot take a gateway down. It is DERIVED AT LOAD, so a `Registry`
    #: built by hand (tests do this) reports `[]` — truthfully, because such a
    #: registry has no YAML to have omitted anything, and its `App` objects
    #: state `allow_inbound` in Python or take the deny default.
    inbound_defaulted: list[str] = field(default_factory=list)

    def identity_for(self, app_id: str, identity_name: str) -> Identity:
        app = self.apps.get(app_id)
        if app is None:
            raise RegistryError(f"unknown app {app_id!r}")
        if identity_name not in app.identities:
            allowed = ", ".join(app.identities) or "(none)"
            raise RegistryError(
                f"app {app_id!r} may not send as {identity_name!r} (allowed: {allowed})"
            )
        ident = self.identities.get(identity_name)
        if ident is None:
            raise RegistryError(f"identity {identity_name!r} is not registered")
        return ident

    def route_for(self, app_id: str, severity: str) -> Identity:
        """Resolve /v1/notify routing: (source app, severity) -> identity."""
        app = self.apps.get(app_id)
        if app is None:
            raise RegistryError(f"unknown app {app_id!r}")
        name = app.routes.get(severity) or app.routes.get("default")
        if not name:
            raise RegistryError(
                f"app {app_id!r} has no notify route for severity {severity!r} "
                "(add routes: {severity: identity} to the registry)"
            )
        return self.identity_for(app_id, name)

    def apps_for_space(self, space: str) -> list[str]:
        """Inbound routing: every app that owns an identity homed in `space`."""
        if not space:
            return []
        owners = []
        for app_id, app in sorted(self.apps.items()):
            for name in app.identities:
                ident = self.identities.get(name)
                if ident and ident.space and ident.space == space:
                    owners.append(app_id)
                    break
        return owners

    def health(self) -> dict:
        """Honest health material (values never included). The claude-mem
        pilot's hardcoded /healthz hid 11 days of silent failure — this one
        reports what is actually resolvable."""
        return {
            "identities": {
                name: {"mode": i.mode, "env_resolved": i.env_resolved(), "space_set": bool(i.space)}
                for name, i in sorted(self.identities.items())
            },
            "apps": {
                app_id: {"key_configured": a.key_configured(), "identities": a.identities}
                for app_id, a in sorted(self.apps.items())
            },
            # CG-88, hard rule #5. Empty on a registry that states its own
            # inbound posture; an app id appears here only while its entry
            # leaves that posture to a loader default.
            #
            # NOT an input to `status` and never a `reasons` entry, decided
            # explicitly per this repo's standing per-field requirement: the
            # gateway is DENYING, which is the safe answer, so a `degraded`
            # here would report a configuration smell as a fault and teach an
            # operator that `degraded` is the normal reading — the verdict
            # `suppressed_opt_out` and `files_deleted` both got.
            #
            # Disclosure on an UNAUTHENTICATED endpoint, weighed rather than
            # assumed: this publishes app ids, which `health()` already
            # publishes two lines above, and the fact it adds about one is
            # "this app is inbound-CLOSED and nobody wrote that down" — which
            # is only sayable at all because the default now denies. Under the
            # old default the same field would have named every open tenant,
            # and it would not have been shipped.
            "inbound_defaulted": list(self.inbound_defaulted),
        }


def load_registry(path: str | Path) -> Registry:
    """Load from one YAML file, or a DIRECTORY of per-tenant files (jobhunt
    R1: one config file per tenant) — every ``*.yaml`` in the directory is
    merged; duplicate identity/app names across files are an error."""
    p = Path(path)
    if p.is_dir():
        data: dict = {"identities": {}, "apps": {}}
        for f in sorted(p.glob("*.yaml")):
            try:
                part = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                raise RegistryError(f"cannot parse {f.name}: {exc}") from exc
            for section in ("identities", "apps"):
                for name, spec in (part.get(section) or {}).items():
                    if name in data[section]:
                        raise RegistryError(f"{f.name}: duplicate {section[:-1]} {name!r}")
                    data[section][name] = spec
    else:
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        # yaml.YAMLError is caught alongside OSError deliberately: malformed YAML
        # is a CONFIG error, and letting a ScannerError or ConstructorError escape
        # raw means the gateway dies at startup with a parser traceback instead of
        # a message naming the file. Same reasoning as _require_id_str above —
        # every way a registry can be wrong should arrive as RegistryError.
        except (OSError, yaml.YAMLError) as exc:
            raise RegistryError(f"cannot read registry: {exc}") from exc
    if not isinstance(data, dict) or "identities" not in data or "apps" not in data:
        raise RegistryError(f"{path}: registry needs top-level 'identities' and 'apps' maps")

    identities: dict[str, Identity] = {}
    for name, spec in (data["identities"] or {}).items():
        # Same coercion trap as app ids below. An identity name is cross-referenced
        # from each app's `identities:` list, so a coerced or whitespace-padded name
        # fails that lookup for a reason nobody can see in the file.
        _require_id_str("identity", name)
        spec = spec or {}
        ident = Identity(
            name=name,
            display=spec.get("display", name),
            channel=spec.get("channel", "google_chat"),
            mode=spec.get("mode", "webhook"),
            webhook_url_env=spec.get("webhook_url_env"),
            space=spec.get("space") or "",
        )
        if ident.channel not in CHANNELS:
            raise RegistryError(f"identity {name!r}: unknown channel {ident.channel!r}")
        if ident.mode not in MODES:
            raise RegistryError(f"identity {name!r}: mode must be one of {MODES}")
        if ident.mode == "webhook" and not ident.webhook_url_env:
            raise RegistryError(f"identity {name!r}: mode webhook requires webhook_url_env")
        if ident.mode == "app" and not ident.space:
            raise RegistryError(f"identity {name!r}: mode app requires a space (spaces/XXXX)")
        identities[name] = ident

    apps: dict[str, App] = {}
    # CG-88. Collected here rather than derived from the App objects, because
    # by then the two cases are indistinguishable: an app that WROTE
    # `allow_inbound: false` and one that wrote nothing both end up `False`,
    # and only the second is a reliance worth reporting.
    inbound_defaulted: list[str] = []
    for app_id, spec in (data["apps"] or {}).items():
        # Type-check BEFORE the prefix check, because YAML coerces unquoted keys:
        # `1:`, `true:`, `null:` and `1.5:` arrive as int / bool / None / float,
        # and calling .startswith on any of them raises AttributeError — which
        # escapes load_registry as an unhandled traceback instead of the config
        # error an operator can act on. Found by adversarially testing the prefix
        # guard this function gained in CG-8; the guard introduced the crash.
        _require_id_str("app", app_id)
        if app_id.startswith(RESERVED_APP_ID_PREFIX):
            raise RegistryError(
                f"app id {app_id!r} is reserved: ids beginning with "
                f"{RESERVED_APP_ID_PREFIX!r} are gateway-internal audit buckets "
                f"(e.g. {UNROUTED!r}). An app registered under one would receive "
                "every unroutable and every UNPARSEABLE event from every space, "
                "bypassing the per-app inbound authorization check (hard rule #6)."
            )
        spec = spec or {}
        if not spec.get("key_env"):
            raise RegistryError(f"app {app_id!r}: key_env is required")
        # CG-88. Absence is DENY and is recorded as reliance; a written value
        # must be a real boolean. `None` covers both "key absent" and an
        # explicit `allow_inbound:` with nothing after it — a key that states
        # no posture is not a statement of posture, so it is treated as absent
        # and reported the same way.
        #
        # There is deliberately NO `bool(...)` call left on this path. The old
        # one read `bool(spec.get("allow_inbound", True))` and was wrong twice
        # over — a permissive default AND a coercion that made `"false"` true.
        # A later edit cannot re-widen a coercion site that does not exist.
        raw_inbound = spec.get("allow_inbound")
        allow_inbound = False
        if raw_inbound is None:
            inbound_defaulted.append(app_id)
        else:
            _require_bool(app_id, "allow_inbound", raw_inbound)
            allow_inbound = raw_inbound
        app = App(app_id=app_id, key_env=spec["key_env"],
                  identities=list(spec.get("identities") or []),
                  allow_inbound=allow_inbound,
                  routes=dict(spec.get("routes") or {}),
                  callback_url=str(spec.get("callback_url") or ""),
                  allowed_users=[str(u).lower() for u in (spec.get("allowed_users") or [])],
                  unreachable_message=str(spec.get("unreachable_message") or ""))
        if app.callback_url and not app.allow_inbound:
            raise RegistryError(
                f"app {app_id!r}: callback_url requires allow_inbound: true — "
                "an opted-out tenant gets NO inbound path (hard rule #6)"
            )
        for name in app.identities:
            if name not in identities:
                raise RegistryError(f"app {app_id!r} references unknown identity {name!r}")
        for severity, name in app.routes.items():
            if severity != "default" and severity not in SEVERITIES:
                raise RegistryError(f"app {app_id!r}: unknown route severity {severity!r}")
            if name not in app.identities:
                raise RegistryError(
                    f"app {app_id!r}: route {severity!r} -> {name!r} must point at one of "
                    "the app's own identities"
                )
        apps[app_id] = app

    if not apps:
        raise RegistryError("registry defines no apps")
    return Registry(identities=identities, apps=apps,
                    inbound_defaulted=sorted(inbound_defaulted))
