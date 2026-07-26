"""Per-app API keys. Keys live in the env (registry names the var); requests
carry `Authorization: Bearer <key>`; comparison is constant-time."""

from __future__ import annotations

import hmac
import os
import secrets

from .registry import Registry


class AuthError(Exception):
    pass


def mint_key() -> str:
    """Generate a new app key (CLI: python3 -m chat_gateway mint-key)."""
    return "cgk_" + secrets.token_urlsafe(32)


def authenticate(registry: Registry, authorization: str | None) -> str:
    """Resolve a Bearer token to an app_id or raise AuthError.

    Iterates registered apps and constant-time-compares against each
    configured key — fine at this scale (tens of apps), and it avoids a
    key→app lookup table that would have to be rebuilt on env changes.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("missing bearer token")
    presented = authorization.removeprefix("Bearer ").strip()
    if not presented:
        raise AuthError("empty bearer token")
    for app_id, app in registry.apps.items():
        expected = os.environ.get(app.key_env, "")
        if expected and hmac.compare_digest(presented, expected):
            return app_id
    raise AuthError("unknown API key")
