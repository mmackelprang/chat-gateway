"""The admin console's API (CG-90; spec docs/superpowers/specs/2026-10-15-admin-console-design.md).

Mounted only when `GATEWAY_ENABLE_ADMIN=1`. Authenticated by its OWN key
(`CHAT_GATEWAY_ADMIN_KEY`), never a tenant's (hard rule #4). Every write goes
through `RegistryStore.apply`, so validation, backup, atomic write and swap
have one home. A secret value leaves this module only in the response that
minted it (hard rule #2).
"""

from __future__ import annotations

import hmac
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from ruamel.yaml.comments import CommentedMap

from .admin_audit import AdminAudit
from .auth import mint_key
from .delivery import DeliveryLog
from .managed_secrets import ManagedSecrets
from .registry import ADMIN_KEY_ENV, SEVERITIES, App
from .registry_holder import RegistryHolder
from .registry_store import RegistryStore, StoreError, category_for, flow_seq

KEY_PREFIX = "CHAT_GATEWAY_API_KEY__"
WEBHOOK_PREFIX = "GOOGLE_CHAT_WEBHOOK_URL__"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_WEBHOOK_PATH = re.compile(r"^/v1/spaces/([A-Za-z0-9_-]+)/messages$")
RATE_LIMIT_FAILURES = 5
RATE_LIMIT_WINDOW_S = 60.0
STATIC_DIR = Path(__file__).parent / "static" / "admin"
RULE_6 = ("Inbound crosses to a consumer only by that consumer's explicit "
          "registry opt-in (hard rule #6).")


def env_name(prefix: str, ident: str) -> str:
    return prefix + ident.upper().replace("-", "_")


def parse_webhook_space(url: str) -> str:
    """Validate an incoming-webhook URL's SHAPE and return `spaces/<id>`.

    Messages never include the URL or any part of it — it embeds key+token.
    """
    u = urlparse(url.strip())
    m = _WEBHOOK_PATH.match(u.path)
    q = parse_qs(u.query)
    if u.scheme != "https" or u.hostname != "chat.googleapis.com" or not m:
        raise ValueError("not a Google Chat incoming-webhook URL "
                         "(https://chat.googleapis.com/v1/spaces/<id>/messages?key=…&token=…)")
    if not q.get("key") or not q.get("token"):
        raise ValueError("the webhook URL is missing its key or token parameter — "
                         "copy the whole URL from the Chat space's webhook settings")
    return f"spaces/{m.group(1)}"


def widening(old: App | None, new) -> list[str]:
    """Which parts of `new` widen inbound relative to `old` (spec §6.4).

    `new.callback_url is None` means "not sent, unchanged" (fix round I4), so
    it is compared as the old value — it cannot widen anything."""
    reasons: list[str] = []
    old_in = bool(old and old.allow_inbound)
    if new.allow_inbound and not old_in:
        reasons.append("allow_inbound")
    old_cb = old.callback_url if old else ""
    new_cb = old_cb if new.callback_url is None else new.callback_url
    if new_cb and new_cb != old_cb:
        reasons.append("callback_url")
    if new.allow_inbound:
        old_users = set(old.allowed_users) if old else set()
        new_users = {u.lower() for u in new.allowed_users}
        if old_users and not new_users:
            reasons.append("allowed_users emptied")
        elif old_users and new_users - old_users:
            reasons.append("allowed_users added")
    return reasons


def _node(tree: CommentedMap, section: str, key: str, kind: str) -> CommentedMap:
    """The `section[key]` mapping of the tree being edited, or a 404.

    CG-90 C4. The router's existence check reads the HOLDER; the mutator edits
    the FILE's tree, later, under the store lock. Those are different snapshots
    — a reload or a second writer can land between them — so a missing key here
    is an ordinary "unknown", never a KeyError surfacing as a bare 500.
    """
    try:
        node = (tree.get(section) or {})[key]
    except KeyError:
        raise StoreError(404, f"unknown {kind} {key!r}") from None
    if not isinstance(node, dict):
        raise StoreError(422, f"{kind} {key!r} is not a mapping in registry.yaml; "
                              "edit it by hand")
    return node


#: One app's inbound-relevant shape: (allow_inbound, inbound_locked, identities).
_AppShape = tuple[bool, bool, tuple[str, ...]]


def _shape(reg) -> tuple[dict[str, _AppShape], dict[str, str]]:
    """The parts of a registry the locked-space rule reads, as plain data, so a
    write's RESULT can be modelled by editing a copy before anything is applied."""
    apps = {a.app_id: (a.allow_inbound, a.inbound_locked, tuple(a.identities))
            for a in reg.apps.values()}
    spaces = {i.name: i.space for i in reg.identities.values()}
    return apps, spaces


def locked_space_violations(apps: dict[str, _AppShape],
                            spaces: dict[str, str]) -> set[tuple[str, str]]:
    """Every `(app, locked_app)` where `app` is inbound and posts in a space an
    `inbound_locked` app posts in (fix round I3).

    Inbound is routed BY SPACE (`Registry.apps_for_space`), so a lock that only
    guarded its own registry entry was bypassable: grant the locked tenant's
    identity — or any identity whose webhook sits in the same space — to a new
    inbound app, and that tenant's space traffic reaches a consumer. The lock
    is therefore a guarantee about SPACES. An identity with no `space` cannot
    match anything and is ignored.
    """
    locked: dict[str, str] = {}
    for app_id, (_, is_locked, idents) in sorted(apps.items()):
        if is_locked:
            for n in idents:
                if spaces.get(n):
                    locked.setdefault(spaces[n], app_id)
    out: set[tuple[str, str]] = set()
    for app_id, (inbound, is_locked, idents) in apps.items():
        if is_locked or not inbound:
            continue
        for n in idents:
            sp = spaces.get(n)
            if sp and sp in locked:
                out.add((app_id, locked[sp]))
    return out


def _section(tree: CommentedMap, section: str) -> CommentedMap:
    """`tree[section]`, created if the file left it empty (`apps:` with no body
    loads as None — `load_registry` accepts that, so the console must too)."""
    if tree.get(section) is None:
        tree[section] = CommentedMap()
    return tree[section]


@dataclass
class AdminWiring:
    store: RegistryStore
    secrets: ManagedSecrets
    audit: AdminAudit

    def health(self) -> dict:
        return {"enabled": True, "writes": self.store.writes,
                "refused": self.store.refused,
                # An authored CATEGORY, never a message: this lands on the
                # unauthenticated /healthz (fix round I2, hard rule #2).
                "last_write_error": self.store.last_write_error,
                "audit_write_errors": self.audit.write_errors,
                "shadowed_env_names": self.secrets.shadowed(),
                "memory_disk_diverged": self.store.memory_disk_diverged}


class _Limiter:
    def __init__(self, now_fn: Callable[[], float]):
        self._now = now_fn
        self._fails: dict[str, list[float]] = {}

    def _recent(self, host: str) -> list[float]:
        cutoff = self._now() - RATE_LIMIT_WINDOW_S
        recent = [t for t in self._fails.get(host, []) if t > cutoff]
        self._fails[host] = recent
        return recent

    def check(self, host: str) -> None:
        if len(self._recent(host)) >= RATE_LIMIT_FAILURES:
            raise HTTPException(429, "too many failed admin logins — wait a minute")

    def fail(self, host: str) -> None:
        self._recent(host).append(self._now())


# -- request bodies -----------------------------------------------------------
class _Guarded(BaseModel):
    registry_sha256: str | None = None


class AppFields(_Guarded):
    identities: list[str] = Field(default_factory=list)
    routes: dict[str, str] = Field(default_factory=dict)
    allow_inbound: bool = False
    # ⚠ Fix round I4. `None` (absent) = UNCHANGED, `""` = remove, else set.
    # `state()` deliberately shows only `callback_url_set` — the URL may carry
    # a token — so a page cannot echo back what it was never shown. Under the
    # old full-replace `""` default, ANY console edit of job-hunter silently
    # deleted its callback_url. The page sends these only when edited.
    callback_url: str | None = None
    allowed_users: list[str] = Field(default_factory=list)
    unreachable_message: str | None = None
    confirm_app_id: str = ""


class AppCreate(AppFields):
    app_id: str


# ⚠ Hard rule #2: every field that can carry a webhook URL DEFAULTS to "" and
# is checked by hand. FastAPI's 422 body echoes the offending `input`, and for
# a missing required field that input is the whole request body — webhook URL
# included. With defaults, a missing field never reaches pydantic's echo.
class IdentityCreate(_Guarded):
    name: str = ""
    display: str = ""
    webhook_url: str = ""


class DisplayIn(_Guarded):
    display: str = ""


class WebhookIn(_Guarded):
    webhook_url: str = ""


class ConfirmApp(_Guarded):
    confirm_app_id: str = ""


class ConfirmIdentity(_Guarded):
    confirm_name: str = ""


def build_admin_router(registry: RegistryHolder, wiring: AdminWiring, *,
                       delivery_log: DeliveryLog,
                       now_fn: Callable[[], float] | None = None) -> APIRouter:
    limiter = _Limiter(now_fn or time.monotonic)
    store, secrets, audit = wiring.store, wiring.secrets, wiring.audit
    router = APIRouter(prefix="/admin")

    def require_admin(request: Request, response: Response,
                      authorization: str | None = Header(default=None)) -> None:
        # no-store on every admin answer: two of them carry a freshly minted
        # key, and a cached copy of that response is a second home for it.
        response.headers["Cache-Control"] = "no-store"
        host = request.client.host if request.client else "?"
        limiter.check(host)
        # Read per request, not at mount: rotating the admin key is an env
        # change plus restart today, and an unset key must refuse EVERYTHING
        # rather than compare against "" (hmac of two empties is equal).
        expected = os.environ.get(ADMIN_KEY_ENV, "").encode("utf-8")
        presented = b""
        if authorization and authorization.startswith("Bearer "):
            presented = authorization.removeprefix("Bearer ").strip().encode("utf-8")
        # BYTES, not str (fix round M2): `hmac.compare_digest` raises TypeError
        # on a non-ASCII str, and Starlette decodes headers as latin-1 — so one
        # non-ASCII byte in the header was a 500 the limiter never counted, an
        # unthrottled probe. As bytes it is an ordinary, counted 401.
        if not expected or not presented or not hmac.compare_digest(presented, expected):
            limiter.fail(host)
            raise HTTPException(401, "admin key required", headers={"WWW-Authenticate": "Bearer"})
        # Hard rule #4: two credentials, never one. `load_registry` already
        # refuses an app whose key_env IS the admin variable; this catches the
        # same VALUE under a different name, which no file check can see.
        for app in registry.apps.values():
            v = os.environ.get(app.key_env, "").encode("utf-8")
            if v and hmac.compare_digest(v, expected):
                raise HTTPException(503, f"the admin key equals app {app.app_id!r}'s API key — "
                                         "mint a separate admin key (hard rule #4)")

    def refuse(status: int, message: str, category: str | None = None) -> HTTPException:
        # The store counts it and keeps the CATEGORY only (I2); the message goes
        # to the authenticated caller and nowhere else.
        store.note_refusal(category or category_for(status))
        return HTTPException(status, message)

    def run(mutate, secret_changes=None, *, sha=None):
        try:
            return store.apply(mutate, secrets=secret_changes, expect_sha256=sha)
        except StoreError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        except ValueError as exc:  # ManagedSecrets value refusal — names only
            raise refuse(422, str(exc), "refused: secret value") from exc

    def check_id(value: str, kind: str) -> None:
        if not ID_RE.match(value):
            raise refuse(422, f"{kind} id must match {ID_RE.pattern} "
                              "(lowercase letters, digits, hyphens; not starting with '_' or '-')")

    def managed_name(name: str) -> None:
        if secrets.blocked(name):
            raise refuse(409, f"{name} is set in the gateway's process environment, which "
                              "overrides managed.env at boot — change it there, not here")

    def check_refs(body: AppFields) -> None:
        """Every identity and route value names a registered identity; every
        route key is a known severity (fix round I2a; closes M5, which silently
        DROPPED an unknown key). Before apply, so admin-supplied junk never
        reaches `load_registry`'s messages. A value is quoted back only if it
        has the shape of an id — anything else may be a URL pasted into the
        wrong field, and is described rather than echoed (hard rule #2)."""
        known = registry.identities

        def ref(value: str, where: str) -> None:
            if not ID_RE.match(value):
                raise refuse(422, f"{where} contains a value that is not a registered "
                                  "identity id")
            if value not in known:
                raise refuse(422, f"{where}: unknown identity {value!r}")

        for n in body.identities:
            ref(n, "identities")
        allowed_keys = ["default", *SEVERITIES]
        for key, value in body.routes.items():
            if key not in allowed_keys:
                shown = f" {key!r}" if ID_RE.match(key) else ""
                raise refuse(422, f"routes key{shown} is not one of {', '.join(allowed_keys)}")
            ref(value, f"routes.{key}")

    def guard_inbound(old: App | None, body: AppFields, app_id: str) -> list[str]:
        """Raises StoreError — it runs INSIDE `mutate`, under the store lock,
        where `registry.current` agrees with the file being edited (fix round
        I3.3; closes M1, the guard evaluated against a snapshot that could be
        swapped before the write landed)."""
        reasons = widening(old, body)
        if not reasons:
            return []
        if old is not None and old.inbound_locked:
            raise StoreError(403, f"app {app_id!r} is inbound_locked: widening "
                                  f"({', '.join(reasons)}) is a registry file edit, not a "
                                  "console action. " + RULE_6)
        if body.confirm_app_id != app_id:
            raise StoreError(428, f"widening inbound ({', '.join(reasons)}) requires typing "
                                  f"the app id to confirm. {RULE_6}")
        return reasons

    def guard_locked_spaces(after: tuple[dict, dict], touched: set[str]) -> None:
        """Refuse a write whose RESULT routes a locked tenant's space to another
        inbound app (fix round I3.2). Inside `mutate`, like `guard_inbound`.

        A violation is refused if this write CREATES it, or if it involves an
        app this write touches. One that a hand edit already put in the file
        and this write does not touch is left alone: blocking every unrelated
        console write on it would make the console unusable without making the
        file any safer — the file edit is where it must be fixed."""
        before = locked_space_violations(*_shape(registry.current))
        bad = sorted(v for v in locked_space_violations(*after)
                     if v not in before or v[0] in touched)
        if bad:
            app_id, locked_app = bad[0]
            raise StoreError(403, f"app {app_id!r} would receive inbound from a space that "
                                  f"inbound_locked app {locked_app!r} posts in — a locked "
                                  "tenant's space is never routed to another consumer "
                                  "from the console. " + RULE_6)

    def after_app(app_id: str, body: AppFields) -> tuple[dict, dict]:
        apps, spaces = _shape(registry.current)
        old = apps.get(app_id)
        apps[app_id] = (bool(body.allow_inbound), bool(old and old[1]),
                        tuple(body.identities))
        return apps, spaces

    def app_map(target: CommentedMap, body: AppFields, key_env: str | None) -> list[str]:
        """Write `body` into `target` in place; returns the field names written.
        In place, so comments on untouched keys and the hand-only
        `inbound_locked` key survive."""
        written = ["identities", "allow_inbound", "routes", "allowed_users"]
        if key_env is not None:
            target["key_env"] = key_env
        target["identities"] = flow_seq(list(body.identities))
        target["allow_inbound"] = bool(body.allow_inbound)  # hard rule #7: always written
        routes = CommentedMap()
        for sev in ["default", *SEVERITIES]:
            if body.routes.get(sev):
                routes[sev] = body.routes[sev]
        if routes:
            target["routes"] = routes
        else:
            target.pop("routes", None)
        for key, value in (("callback_url", body.callback_url),
                           ("unreachable_message", body.unreachable_message)):
            if value is None:  # I4: not sent = unchanged
                continue
            written.append(key)
            if value:
                target[key] = value
            else:
                target.pop(key, None)
        if body.allowed_users:
            target["allowed_users"] = flow_seq([u.lower() for u in body.allowed_users])
        else:
            target.pop("allowed_users", None)
        return written

    def get_app(app_id: str) -> App:
        app = registry.apps.get(app_id)
        if app is None:
            raise HTTPException(404, f"unknown app {app_id!r}")
        return app

    # -- page ----------------------------------------------------------------
    page_headers = {
        "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self'; "
                                    "img-src 'self' data:; connect-src 'self'; "
                                    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }
    static_files = {"admin.js": "text/javascript", "admin.css": "text/css"}

    @router.get("", include_in_schema=False)
    def page():
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html",
                            headers=page_headers)

    @router.get("/static/{name}", include_in_schema=False)
    def static(name: str):
        if name not in static_files:
            raise HTTPException(404, "not found")
        return FileResponse(STATIC_DIR / name, media_type=static_files[name],
                            headers=page_headers)

    # -- read ------------------------------------------------------------------
    @router.get("/api/state", dependencies=[Depends(require_admin)])
    def state():
        reg = registry.current
        return {
            "registry_sha256": store.sha256,
            "apps": {
                a.app_id: {
                    "identities": a.identities, "routes": a.routes,
                    "allow_inbound": a.allow_inbound, "inbound_locked": a.inbound_locked,
                    "callback_url_set": bool(a.callback_url),
                    "allowed_users": a.allowed_users,
                    "unreachable_message_set": bool(a.unreachable_message),
                    "key_env": a.key_env, "key_configured": a.key_configured(),
                    "key_source": secrets.source_of(a.key_env),
                    "recent_deliveries": delivery_log.query(a.app_id, 5),
                } for a in sorted(reg.apps.values(), key=lambda a: a.app_id)
            },
            "identities": {
                i.name: {
                    "display": i.display, "mode": i.mode, "space": i.space,
                    "webhook_url_env": i.webhook_url_env, "env_resolved": i.env_resolved(),
                    "secret_source": (secrets.source_of(i.webhook_url_env)
                                      if i.webhook_url_env else None),
                } for i in sorted(reg.identities.values(), key=lambda i: i.name)
            },
            "shadowed_env_names": secrets.shadowed(),
            "inbound_defaulted": list(reg.inbound_defaulted),
        }

    # -- apps ------------------------------------------------------------------
    @router.post("/api/apps", status_code=201, dependencies=[Depends(require_admin)])
    def create_app_entry(body: AppCreate):
        check_id(body.app_id, "app")
        if body.app_id in registry.apps:
            raise refuse(409, f"app {body.app_id!r} already exists")
        check_refs(body)
        key_env = env_name(KEY_PREFIX, body.app_id)
        managed_name(key_env)
        key = mint_key()
        fields: list[str] = []
        widened: list[str] = []

        def mutate(tree):
            apps = _section(tree, "apps")
            # C4's other half: the holder said "absent", the file may disagree.
            if body.app_id in apps:
                raise StoreError(409, f"app {body.app_id!r} already exists")
            widened.extend(guard_inbound(None, body, body.app_id))
            guard_locked_spaces(after_app(body.app_id, body), {body.app_id})
            m = CommentedMap()
            fields.extend(app_map(m, body, key_env))
            apps[body.app_id] = m

        run(mutate, {key_env: key}, sha=body.registry_sha256)
        audit.record("app_created", body.app_id, ["key_env", *fields])
        if widened:
            audit.record("inbound_widened", body.app_id, widened)
        return {"app_id": body.app_id, "key_env": key_env, "key": key,
                "shadows_env_file": key_env in secrets.hand_env_names}

    @router.put("/api/apps/{app_id}", dependencies=[Depends(require_admin)])
    def update_app_entry(app_id: str, body: AppFields):
        get_app(app_id)
        check_refs(body)
        fields: list[str] = []
        widened: list[str] = []

        def mutate(tree):
            target = _node(tree, "apps", app_id, "app")
            # Re-read under the lock: the guard judges the app the file holds now.
            widened.extend(guard_inbound(registry.current.apps.get(app_id), body, app_id))
            guard_locked_spaces(after_app(app_id, body), {app_id})
            fields.extend(app_map(target, body, None))

        run(mutate, sha=body.registry_sha256)
        audit.record("app_updated", app_id, fields)
        if widened:
            audit.record("inbound_widened", app_id, widened)
        return {"app_id": app_id}

    @router.post("/api/apps/{app_id}/rotate-key", dependencies=[Depends(require_admin)])
    def rotate_key(app_id: str, body: _Guarded | None = None):
        app = get_app(app_id)
        managed_name(app.key_env)
        key = mint_key()
        run(None, {app.key_env: key}, sha=body.registry_sha256 if body else None)
        audit.record("key_rotated", app_id, [app.key_env])
        return {"app_id": app_id, "key_env": app.key_env, "key": key,
                "shadows_env_file": app.key_env in secrets.hand_env_names}

    @router.post("/api/apps/{app_id}/delete", dependencies=[Depends(require_admin)])
    def delete_app_entry(app_id: str, body: ConfirmApp):
        app = get_app(app_id)
        if body.confirm_app_id != app_id:
            raise refuse(428, "deleting an app requires typing its id to confirm")

        def mutate(tree):
            _node(tree, "apps", app_id, "app")
            # Fix round I3.1: delete-then-recreate was a two-step bypass of the
            # widening refusal. A locked app leaves the registry the way it
            # entered it — by a file edit.
            live = registry.current.apps.get(app_id)
            if live is not None and live.inbound_locked:
                raise StoreError(403, f"app {app_id!r} is inbound_locked: deleting it is a "
                                      "registry file edit, not a console action. " + RULE_6)
            tree["apps"].pop(app_id)

        remove = {app.key_env: None} if secrets.source_of(app.key_env) == "managed" else None
        run(mutate, remove, sha=body.registry_sha256)
        audit.record("app_deleted", app_id, [])
        return {"app_id": app_id}

    # -- identities ------------------------------------------------------------
    @router.post("/api/identities", status_code=201, dependencies=[Depends(require_admin)])
    def create_identity(body: IdentityCreate):
        if not body.display.strip() or not body.webhook_url.strip():
            raise refuse(422, "name, display and webhook_url are all required")
        check_id(body.name, "identity")
        if body.name in registry.identities:
            raise refuse(409, f"identity {body.name!r} already exists")
        try:
            space = parse_webhook_space(body.webhook_url)
        except ValueError as exc:
            raise refuse(422, str(exc)) from exc
        url_env = env_name(WEBHOOK_PREFIX, body.name)
        managed_name(url_env)

        def mutate(tree):
            identities = _section(tree, "identities")
            if body.name in identities:
                raise StoreError(409, f"identity {body.name!r} already exists")
            m = CommentedMap()
            m["display"] = body.display
            m["channel"] = "google_chat"
            m["mode"] = "webhook"
            m["webhook_url_env"] = url_env
            m["space"] = space
            identities[body.name] = m

        run(mutate, {url_env: body.webhook_url.strip()}, sha=body.registry_sha256)
        audit.record("identity_created", body.name, ["display", "webhook_url_env", "space"])
        return {"name": body.name, "webhook_url_env": url_env, "space": space}

    def get_identity(name: str):
        ident = registry.identities.get(name)
        if ident is None:
            raise HTTPException(404, f"unknown identity {name!r}")
        return ident

    @router.put("/api/identities/{name}", dependencies=[Depends(require_admin)])
    def update_identity(name: str, body: DisplayIn):
        get_identity(name)
        if not body.display.strip():
            # `load_registry` would accept "" and render a blank sender name.
            raise refuse(422, "display is required")

        def mutate(tree):
            _node(tree, "identities", name, "identity")["display"] = body.display

        run(mutate, sha=body.registry_sha256)
        audit.record("identity_updated", name, ["display"])
        return {"name": name}

    @router.post("/api/identities/{name}/webhook", dependencies=[Depends(require_admin)])
    def replace_webhook(name: str, body: WebhookIn):
        ident = get_identity(name)
        if ident.mode != "webhook" or not ident.webhook_url_env:
            raise refuse(409, f"identity {name!r} is not a webhook identity")
        try:
            space = parse_webhook_space(body.webhook_url)
        except ValueError as exc:
            raise refuse(422, str(exc)) from exc
        managed_name(ident.webhook_url_env)

        def mutate(tree):
            node = _node(tree, "identities", name, "identity")
            # Fix round I3.2: moving an identity's space moves every inbound app
            # that holds it — and, if a locked app holds it, moves the lock.
            apps, spaces = _shape(registry.current)
            spaces[name] = space
            guard_locked_spaces((apps, spaces),
                                {a for a, (_, _, ids) in apps.items() if name in ids})
            node["space"] = space

        run(mutate, {ident.webhook_url_env: body.webhook_url.strip()}, sha=body.registry_sha256)
        audit.record("webhook_replaced", name, [ident.webhook_url_env, "space"])
        return {"name": name, "space": space}

    @router.post("/api/identities/{name}/delete", dependencies=[Depends(require_admin)])
    def delete_identity(name: str, body: ConfirmIdentity):
        ident = get_identity(name)
        if body.confirm_name != name:
            raise refuse(428, "deleting an identity requires typing its name to confirm")
        users = sorted(a.app_id for a in registry.apps.values() if name in a.identities)
        if users:
            raise refuse(409, f"identity {name!r} is still granted to: {', '.join(users)} — "
                              "remove it from those apps first")

        def mutate(tree):
            _node(tree, "identities", name, "identity")
            tree["identities"].pop(name)

        env = ident.webhook_url_env
        remove = {env: None} if env and secrets.source_of(env) == "managed" else None
        run(mutate, remove, sha=body.registry_sha256)
        audit.record("identity_deleted", name, [])
        return {"name": name}

    # -- reload ----------------------------------------------------------------
    @router.post("/api/reload", dependencies=[Depends(require_admin)])
    def reload():
        try:
            store.reload()
        except StoreError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        audit.record("reloaded_from_disk", "registry.yaml", [])
        return {"registry_sha256": store.sha256}

    return router
