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
    """The named env file could not be used. Names the PATH, never a value."""


def parse_env_file(text: str) -> dict[str, str]:
    """`KEY=VALUE` lines. Honours `#` comments, blanks, `export `, and ONE layer
    of matching surrounding quotes.

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
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
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
        text = p.read_text(encoding="utf-8")
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
