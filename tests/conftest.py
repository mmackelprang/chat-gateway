import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def assert_owner_only(path: Path) -> None:
    """CG-65: the file is `0600` — asserted on POSIX, relaxed on Windows.

    Deliberately not a bare `== 0o600`. `chmod_owner_only` promises owner-only
    **best effort** and says in its own docstring that it is a no-op on a
    filesystem that cannot express the mode; `journal.py`'s `_FILE_MODE` comment
    says the same. `CLAUDE.md` documents `python -m pytest` on the Windows dev
    box as a supported run, where `os.chmod` only toggles the read-only bit and
    `S_IMODE` reads `0o666` — so an exact-mode assertion would turn the suite red
    there for behaviour this repo explicitly declines to promise.

    One home for the check, so the POSIX assertion cannot be quietly weakened in
    one test file and not the other.
    """
    mode = stat.S_IMODE(path.stat().st_mode)
    if os.name == "nt":  # pragma: no cover — the deploy target is Linux
        assert path.exists(), path
        return
    assert mode == 0o600, f"{path} is {oct(mode)}, expected 0o600"
