"""Secrets the admin console mints or receives (CG-90, spec §4).

The hand-written env file is mounted read-only and stays the operator's. This
file is the gateway's: `<state_dir>/managed.env`, mode 0600, written atomically,
and loaded at boot BEFORE the hand-written file. `load_env_file` lets an
already-present value win (`env_file.py`), so loading this first is what makes
a console-rotated key survive a reboot. A name set in the real process
environment beats both, by the same rule — the console refuses to manage such a
name rather than write a value that would be ignored at the next boot.

Values are never returned, logged or interpolated. Names are non-secret — but a
REFUSED name is not echoed either, because a string that fails the name check
may be a value pasted into the wrong field.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .env_file import parse_env_file

# A name must survive `parse_env_file` unchanged: no `=`, no whitespace, no
# leading `#`, no `export ` prefix. The POSIX identifier shape is the narrowest
# rule that admits every name this project uses.
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# `os.open` on Windows opens in TEXT mode unless told otherwise, which would
# rewrite every "\n" as "\r\n" — and `restore` promises the snapshot's exact
# bytes. A no-op on POSIX.
_O_BINARY = getattr(os, "O_BINARY", 0)


@dataclass(frozen=True)
class SecretsSnapshot:
    """Opaque rollback token. Holds values, so it is never logged or returned
    across an API boundary — it lives only for one store transaction."""

    file_bytes: bytes | None
    environ: dict[str, str | None]

    def __repr__(self) -> str:  # hard rule #2: a stray repr must not leak values
        return f"SecretsSnapshot(names={sorted(self.environ)!r})"


class ManagedSecrets:
    def __init__(self, path: Path, *, process_env_names: frozenset[str],
                 hand_env_names: frozenset[str] = frozenset(),
                 environ: dict | None = None):
        self._path = Path(path)
        self._process = frozenset(process_env_names)
        # Public and assignable: boot sets it after the hand-written file loads,
        # which happens AFTER this object must already have applied its file.
        self.hand_env_names = frozenset(hand_env_names)
        self._environ = os.environ if environ is None else environ

    # -- reading ---------------------------------------------------------------
    def _entries(self) -> dict[str, str]:
        try:
            return parse_env_file(self._path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return {}

    def load_at_boot(self) -> int:
        """Apply the file over the environment, except real process names.

        Overwrites what is present (unlike `load_env_file`): at boot the only
        things present are the real process env — skipped by name — so this is
        what makes managed beat the hand-written file loaded after it."""
        applied = 0
        for name, value in self._entries().items():
            if name in self._process:
                continue
            self._environ[name] = value
            applied += 1
        return applied

    def blocked(self, name: str) -> bool:
        return name in self._process

    def source_of(self, name: str) -> str:
        if name in self._process:
            return "process"
        if name in self._entries():
            return "managed"
        if name in self.hand_env_names:
            return ".env"
        return "unset"

    def shadowed(self) -> list[str]:
        return sorted(set(self._entries()) & self.hand_env_names)

    # -- writing ---------------------------------------------------------------
    def snapshot(self, names: Iterable[str]) -> SecretsSnapshot:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            raw = None
        return SecretsSnapshot(raw, {n: self._environ.get(n) for n in names})

    def restore(self, snap: SecretsSnapshot) -> None:
        if snap.file_bytes is None:
            self._path.unlink(missing_ok=True)
        else:
            self._write_bytes(snap.file_bytes)
        for name, value in snap.environ.items():
            if value is None:
                self._environ.pop(name, None)
            else:
                self._environ[name] = value

    def apply(self, changes: dict[str, str | None]) -> None:
        """`None` removes. Validates EVERY change before writing ANYTHING — the
        store relies on a `ValueError` leaving file and environ untouched.

        Not thread-safe: callers must serialize `apply()`/`restore()` — the
        store holds a lock; this module does not."""
        for name, value in changes.items():
            if not isinstance(name, str) or not _NAME.fullmatch(name):
                raise ValueError("invalid variable name")
            if value is not None and parse_env_file(f'{name}="{value}"\n') != {name: value}:
                # Refused by ROUND-TRIP, not a denylist: `parse_env_file` has no
                # escape syntax and splits on `str.splitlines()`, which breaks on
                # \v, \f, \x1c-\x1e, \x85,   and   as well as \n/\r. A
                # denylist of `"`/\n/\r accepted those, and the credential
                # silently changed at the next boot (CG-90 review). The one parser
                # the boot path uses is the only authority on what survives. A
                # non-string value fails here too, as a ValueError. The value is
                # never echoed, so the message names only the variable.
                raise ValueError(f"{name}: value would not survive a reload of the file")
            if value is not None and "\x00" in value:
                # NUL round-trips through `parse_env_file` above, so that check
                # admits it — but `os.environ[name] = value` then refuses it with
                # "embedded null byte" AFTER the file below was written, which
                # breaks the promise the store relies on: a ValueError from here
                # means nothing changed (CG-90 Task 4 review). Ordered after the
                # round-trip check so a non-string value has already been refused.
                raise ValueError(f"{name}: value contains a NUL byte")
        entries = self._entries()
        for name, value in changes.items():
            if value is None:
                entries.pop(name, None)
            else:
                entries[name] = value
        if entries or self._path.exists():
            body = "".join(f'{n}="{v}"\n' for n, v in sorted(entries.items()))
            self._write_bytes(body.encode("utf-8"))
        for name, value in changes.items():
            if value is None:
                self._environ.pop(name, None)
            else:
                self._environ[name] = value

    def _write_bytes(self, data: bytes) -> None:
        """Atomic replace via a sibling temp file created 0600 from birth — the
        mode is set at `open`, never `chmod`ed after, so there is no window in
        which the secrets are readable by anyone else."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        # A stale temp from a crash keeps ITS mode under O_TRUNC; start fresh.
        tmp.unlink(missing_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY, 0o600)
        try:
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, self._path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
