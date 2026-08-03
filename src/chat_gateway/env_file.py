"""Load a KEY=VALUE file into the environment — the deployment's rule-#2 seam.

WHY THIS IS IN OUR CODE rather than compose's `env_file:`. The deploy target is
a TrueNAS custom app: its compose document is submitted over an API and then
CAPTURED into a sibling repo by a script whose secret detection is an
upper-cased SUFFIX match. That match does not fire on this project's shapes —
`CHAT_GATEWAY_API_KEY__<APP>` ends with the app id and
`GOOGLE_CHAT_WEBHOOK_URL__<IDENTITY>` ends with the identity name. Secrets placed
in `environment:` would therefore be captured in PLAINTEXT under a script that
prints "clean. safe to commit."

RE-MEASURED 2026-08-03 (the premise lives in a repo this one does not control,
so it is checked rather than quoted): still true, and RENAMING IS NOT AN ESCAPE
HATCH. Running that repo's real `is_secret_key` over this project's real key
names, all seven credential vars miss; `GOOGLE_APPLICATION_CREDENTIALS` (a path,
not a credential) is the only one caught. The two families fail for DIFFERENT
reasons, which the one-line version of this hides: bare `CHAT_GATEWAY_API_KEY`
IS caught, so the `__<APP>` suffix is what defeats it there — but bare
`GOOGLE_CHAT_WEBHOOK_URL` is MISSED TOO, because that list has no `URL` entry
(only `DATABASE_URL`). The webhook family would leak under any naming scheme.
Nor does any value-based rule save it: a webhook URL carries `key`/`token` as
QUERY PARAMETERS, not `user:pass@`, so the URL-credential regex does not match
either. End to end through the real redactor and the real scan gate: the
credentials survive verbatim and the gate exits 0.

Keeping every secret in a file the compose document only NAMES makes that capture
clean by construction, and puts a hard-rule-#2 guarantee on code this repo tests
rather than on an unverified property of someone else's compose renderer.

No dependency: `python-dotenv` is not worth one for twenty lines, and the same
call is made for the delivery journal's persistence (Part B).
"""

from __future__ import annotations

import os
from pathlib import Path


class EnvFileError(RuntimeError):
    """The named env file could not be used. Names the PATH, never a value.

    ⚠ Deliberately NOT a `GatewayAuthoredError`, for exactly the reasons
    `retention.py`'s `RetentionConfigError` docstring already sets out at length
    — it is raised at boot and printed by `main`'s `config error:` path rather
    than through `describe_exception`, and CG-29's marker set is a deliberately
    short allowlist. That precedent is the one home for the argument; if review
    wants these classes marked, it is a change to the allowlist and its own
    decision, not a thing to fold into a loader row.
    """


def _clean_value(raw: str) -> str:
    """The post-`=` text of one line → the value. See `parse_env_file`."""
    s = raw.strip()
    if s and s[0] in ("'", '"'):
        close = s.find(s[0], 1)
        if close != -1:
            # Quoted: the content is the value and ANYTHING after the closing
            # quote is discarded. Not `.strip()`ed — a deliberate leading or
            # trailing space is the whole reason an operator quoted it, and this
            # is byte-for-byte what this parser did before inline comments
            # existed. An UNTERMINATED quote falls through to the rule below
            # rather than being guessed at.
            return s[1:close]
    for i, ch in enumerate(raw):
        if ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i].strip()
    return s


def parse_env_file(text: str) -> dict[str, str]:
    """`KEY=VALUE` lines. Honours blanks, `export `, ONE layer of matching
    surrounding quotes, and `#` comments — **whole-line AND INLINE**.

    THE INLINE RULE, AND WHY IT IS COMPOSE'S RULE. A `#` ends the value when it
    is preceded by a space or a tab, or when it is the first non-whitespace
    character after the `=`. A `#` with a non-space to its left is part of the
    value (`K=abc#def` → `abc#def`), because a credential may legitimately
    contain one. **Quoting is how a value keeps a literal ` #`**:
    `K="a # b"  # note` → `a # b`, with everything after the closing quote
    discarded.

    This matches `docker-compose`'s documented rule ON PURPOSE, and the reason
    is not tidiness: the SAME FILE is read by both. Compose parses it via
    `env_file: .env` on the dev box, and this loader parses it on the NAS
    (`docs/deploy/nas.md` §5/§6, which tells the operator to copy that very
    file to the box). A parser that disagreed with Compose would make a working
    file CHANGE MEANING at the destination — silently, since the difference is
    a trailing comment nobody looks at twice.

    Swallowing inline comments was not hypothetical: measured over this repo's
    own `.env.example`, **11 of 18 keys** came back with the trailing comment
    inside the value. Two of them are why this is not cosmetic —
    `GOOGLE_APPLICATION_CREDENTIALS` and `CHAT_GATEWAY_PUBSUB_SUBSCRIPTION`
    parsed to a NON-EMPTY string, so `__main__`'s fail-closed
    `if not sub or not creds` guard did not fire and `registry.health()`, which
    tests `bool(os.environ.get(...))`, reported the credential resolvable. The
    gateway boots, looks alive on an unauthenticated `/healthz`, and cannot
    talk to Google — the outcome this module's "a missing file is FATAL" rule
    exists to prevent, reached by a path that never raises (hard rule #5).
    `test_the_repos_own_env_example_parses_with_no_comment_inside_a_value` is
    what stops it coming back.

    A line with no `=` is ignored rather than guessed at: this file is written by
    an operator under time pressure during a deploy, and inventing a meaning for
    a malformed line is how a credential ends up half-set.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        out[key] = _clean_value(value)
    return out


def load_env_file(path: str | Path, environ: dict | None = None) -> int:
    """Load `path` into `environ` (default `os.environ`). Returns keys APPLIED.

    THE ENVIRONMENT WINS. A key already present is left alone, so an operator's
    explicit override is never silently replaced by the file — and so this is a
    no-op in every existing test and on the dev box.

    A MISSING FILE RAISES. A gateway that boots with no credentials answers
    `degraded` on an UNAUTHENTICATED endpoint and otherwise looks alive; refusing
    to start names the fault while it can still be fixed. That is the same
    reasoning rule #5 rests on.

    Values are never returned, logged or interpolated — only a COUNT. Key names
    are non-secret (they are in the committed `.env.example`); values are the
    entire point of this module.
    """
    environ = os.environ if environ is None else environ
    p = Path(path)
    try:
        # `utf-8-sig`, not `utf-8`: a UTF-8 BOM is not whitespace to Python, so
        # `.strip()` leaves it attached and the FIRST key silently becomes
        # `﻿KEY` — a credential dropped without a word. Windows editors
        # write one by default, and the dev box is a Windows box.
        text = p.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise EnvFileError(
            f"CHAT_GATEWAY_ENV_FILE={p} could not be read: {type(exc).__name__}"
        ) from exc
    applied = 0
    for key, value in parse_env_file(text).items():
        if key in environ:
            continue
        environ[key] = value
        applied += 1
    return applied
