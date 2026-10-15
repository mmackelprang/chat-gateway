"""Append-only record of admin console writes (CG-90). Names only — the
action, the app or identity id, and the FIELD NAMES changed. Never a value,
never a URL (hard rule #2). Mode 0600, like every other audit trail here."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

# `os.open` on Windows opens in TEXT mode unless told otherwise — the same
# trap `managed_secrets` guards. A no-op on POSIX.
_O_BINARY = getattr(os, "O_BINARY", 0)


class AdminAudit:
    def __init__(self, path: Path):
        self._path = Path(path)
        self.write_errors = 0

    def record(self, action: str, target: str, fields: list[str]) -> None:
        """Never raises (CG-90 fix round, M3). It runs AFTER the store applied
        the write, so the change is already live — and for a create or a rotate,
        the response it would abort is the ONLY copy of the minted key. Losing
        the audit line is recoverable; losing the key is a re-rotation the
        operator does not know they need. Counted, and published on /healthz as
        `admin.audit_write_errors` (not a `status` input: the console still
        works), and named on stderr — type and ids only, never a value."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat(),
                               "actor": "admin", "action": action, "target": target,
                               "fields": sorted(fields)}) + "\n"
            # 0600 at CREATE, never chmod'ed after — no window in which the
            # trail is readable by anyone else (CG-65's posture for audit files).
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | _O_BINARY,
                         0o600)
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)
        except Exception as exc:  # noqa: BLE001 — the write already happened
            self.write_errors += 1
            print(f"admin audit: write FAILED ({type(exc).__name__}); "
                  f"{action} on {target!r} is applied but not recorded",
                  file=sys.stderr, flush=True)
