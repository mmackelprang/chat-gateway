"""Append-only record of admin console writes (CG-90). Names only — the
action, the app or identity id, and the FIELD NAMES changed. Never a value,
never a URL (hard rule #2). Mode 0600, like every other audit trail here."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

# `os.open` on Windows opens in TEXT mode unless told otherwise — the same
# trap `managed_secrets` guards. A no-op on POSIX.
_O_BINARY = getattr(os, "O_BINARY", 0)


class AdminAudit:
    def __init__(self, path: Path):
        self._path = Path(path)

    def record(self, action: str, target: str, fields: list[str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat(),
                           "actor": "admin", "action": action, "target": target,
                           "fields": sorted(fields)}) + "\n"
        # 0600 at CREATE, never chmod'ed after — no window in which the trail
        # is readable by anyone else (the posture CG-65 set for every audit file).
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | _O_BINARY, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
