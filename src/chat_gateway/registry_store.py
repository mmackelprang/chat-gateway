"""The only writer of registry.yaml (CG-90, spec §5).

Every mutation, under one lock: out-of-band check → edit → serialize → validate
with the REAL loader on the exact bytes → parser agreement → secrets → backup →
atomic write → swap. Any failure before the swap leaves the file, the secrets
and the live registry as they were. The caller audits after success.

ruamel.yaml writes (comments and key order survive — measured byte-identical on
a no-op round trip of both readable registries, 2026-10-15); PyYAML, via
`load_registry`, still reads. Step 5 proves the two agree on every write.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import os
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError as RuamelYAMLError

from .managed_secrets import ManagedSecrets, SecretsSnapshot
from .registry import Registry, RegistryError, load_registry
from .registry_holder import RegistryHolder


#: What `/healthz` may say about a refusal, by status, when the raiser names no
#: category. `/healthz` is UNAUTHENTICATED, and a refusal's full message can
#: carry admin-supplied text — `RegistryError` quotes the value it rejected —
#: so it publishes only one of these authored phrases. The authenticated
#: response keeps the full message (CG-90 Task 6 fix round, I2; hard rule #2).
_DEFAULT_CATEGORY = {
    403: "refused: inbound guard",
    404: "refused: unknown target",
    409: "refused: conflict",
    422: "refused: validation",
    428: "refused: confirmation required",
}


def category_for(status: int) -> str:
    return _DEFAULT_CATEGORY.get(status, "failed" if status >= 500 else "refused")


class StoreError(Exception):
    """A refused or failed console write. Messages are authored here and name
    ids and env-var NAMES only — never a value (hard rule #2). `category` is
    the short authored phrase `/healthz` publishes instead of the message."""

    def __init__(self, status: int, message: str, category: str | None = None):
        super().__init__(message)
        self.status = status
        self.category = category or category_for(status)


def flow_seq(items: list[str]) -> CommentedSeq:
    """A `[a, b]` list — the style every readable registry uses."""
    seq = CommentedSeq(items)
    seq.fa.set_flow_style()
    return seq


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _plain(node):
    if isinstance(node, dict):
        return {k: _plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_plain(v) for v in node]
    return node


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RegistryStore:
    def __init__(self, path: Path, holder: RegistryHolder, secrets: ManagedSecrets,
                 now_fn: Callable[[], dt.datetime] | None = None):
        self._path = Path(path)
        if self._path.is_dir():
            raise RegistryError(
                f"{self._path} is a directory registry; the admin console edits a "
                "single registry.yaml and cannot write the per-tenant directory form"
            )
        self._holder = holder
        self._secrets = secrets
        self._now = now_fn or (lambda: dt.datetime.now(dt.timezone.utc))
        self._lock = threading.Lock()
        self._sha = _sha(self._path.read_bytes())
        self.writes = 0
        self.refused = 0
        self.last_write_error: str | None = None
        self.memory_disk_diverged = False

    @property
    def sha256(self) -> str:
        return self._sha

    def note_refusal(self, category: str) -> None:
        """Count a refusal. `last_write_error` — published on the
        unauthenticated `/healthz` — gets the authored CATEGORY only; the
        message, which may quote admin-supplied text, never reaches this object
        (CG-90 fix round I2). It used to take the message and keep `[:300]` of
        it — truncate-and-hope, which put a webhook URL on `/healthz`."""
        self.refused += 1
        self.last_write_error = category

    def _refuse(self, status: int, message: str, category: str | None = None) -> StoreError:
        exc = StoreError(status, message, category)
        self.note_refusal(exc.category)
        return exc

    def _roll_back(self, snap: SecretsSnapshot, exc: BaseException) -> NoReturn:
        """Restore the secrets snapshot, then raise the 500. The registry file
        needs no restore: it is only ever replaced by the final `os.replace`, and
        nothing after that can fail. A failed restore is the one state this store
        cannot repair — file and environment may now disagree — so it is latched
        on `memory_disk_diverged` rather than reported once and forgotten."""
        try:
            self._secrets.restore(snap)
        except Exception:  # noqa: BLE001 — any failure here is divergence
            self.memory_disk_diverged = True
            raise self._refuse(
                500, f"write failed ({type(exc).__name__}) and the rollback of "
                     "managed secrets ALSO failed — restart the gateway",
                f"failed: rollback failed ({type(exc).__name__})") from exc
        # Exception TYPE only: an OSError's str() carries a path at best, and
        # this message reaches the browser (CG-29's rule, applied to CG-90).
        raise self._refuse(
            500, f"write failed and was rolled back ({type(exc).__name__})",
            f"failed: write rolled back ({type(exc).__name__})") from exc

    def apply(self, mutate: Callable[[CommentedMap], None] | None, *,
              secrets: dict[str, str | None] | None = None,
              expect_sha256: str | None = None) -> Registry:
        with self._lock:
            raw = self._path.read_bytes()
            # 1. out-of-band check — a hand edit since our last load/write would
            #    otherwise be silently overwritten by an edit made against the
            #    older tree.
            if _sha(raw) != self._sha:
                raise self._refuse(409, "registry.yaml was edited outside the console — "
                                        "reload from disk first",
                                   "refused: edited outside the console")
            if expect_sha256 is not None and expect_sha256 != self._sha:
                raise self._refuse(409, "the registry changed since this page loaded it — "
                                        "refresh and try again",
                                   "refused: conflict")
            crlf = b"\r\n" in raw
            text = raw.decode("utf-8").replace("\r\n", "\n")
            y = _yaml()
            try:
                tree = y.load(text)
            except RuamelYAMLError as exc:
                # PyYAML accepted this file (it is live), but ruamel is stricter —
                # duplicate keys, for one. Refuse rather than edit a tree that
                # does not mean what the gateway is running. Type only: a YAML
                # error message quotes the offending line.
                raise self._refuse(
                    422, f"the console cannot parse registry.yaml for editing "
                         f"({type(exc).__name__}); edit it by hand",
                    "refused: registry unparseable") from exc
            # 2. edit
            if mutate is not None:
                try:
                    mutate(tree)
                except StoreError as exc:
                    self.note_refusal(exc.category)
                    raise
            # 3. serialize, keeping the file's own line endings
            buf = io.StringIO()
            y.dump(tree, buf)
            out = buf.getvalue()
            if crlf:
                out = out.replace("\n", "\r\n")
            candidate = out.encode("utf-8")
            changed = candidate != raw
            # 4. validate with the real loader on the exact bytes that will be
            #    written — not on the tree, which is a different object from what
            #    the next boot will read.
            probe = self._path.with_name(f".{self._path.name}.candidate")
            try:
                probe.write_bytes(candidate)
                new = load_registry(probe)
            except RegistryError as exc:
                raise self._refuse(422, str(exc), "refused: registry validation") from exc
            except OSError as exc:
                raise self._refuse(
                    500, f"could not stage the candidate ({type(exc).__name__})",
                    f"failed: could not stage ({type(exc).__name__})") from exc
            finally:
                probe.unlink(missing_ok=True)
            # 5. parser agreement — ruamel wrote it, PyYAML reads it at boot; a
            #    value the two read differently would validate here and mean
            #    something else in production.
            if yaml.safe_load(candidate.decode("utf-8")) != _plain(tree):
                raise self._refuse(422, "the YAML writer and loader disagree on this edit; "
                                        "nothing was written",
                                   "refused: parser disagreement")
            # 6. secrets
            snap = self._secrets.snapshot((secrets or {}).keys())
            if secrets:
                try:
                    self._secrets.apply(secrets)
                except ValueError as exc:
                    # `ManagedSecrets.apply` validates every name and value BEFORE
                    # writing anything, so this refusal has nothing to roll back.
                    # Caught around `apply` ALONE: a ValueError from the registry
                    # write below must still roll the secrets back. A 422, not a
                    # 500; the message names the variable only.
                    raise self._refuse(422, str(exc), "refused: secret value") from exc
                except Exception as exc:  # noqa: BLE001 — partial write possible
                    self._roll_back(snap, exc)
            if changed:
                tmp = self._path.with_name(f".{self._path.name}.tmp")
                try:
                    # 7. backup  8. atomic write
                    self._backup()
                    with open(tmp, "wb") as fh:
                        fh.write(candidate)
                        fh.flush()
                        os.fsync(fh.fileno())
                    shutil.copymode(self._path, tmp)
                    os.replace(tmp, self._path)
                except Exception as exc:  # noqa: BLE001 — roll back, then report
                    tmp.unlink(missing_ok=True)
                    self._roll_back(snap, exc)
            # 9. swap
            self._holder.swap(new)
            self._sha = _sha(candidate)
            self.writes += 1
            self.last_write_error = None
            return new

    def probe_writable(self) -> None:
        """Boot check: can this store write where every write lands?

        CG-90 final review (minor). Every write stages a candidate, a temp file
        and a backup BESIDE registry.yaml and then `os.replace`s it, so the
        directory — not just the file — must be writable. A read-only mount
        (the NAS custom app's default for config) used to boot cleanly and then
        fail every console write with a 500; refusing at boot (exit 2) puts the
        error where the operator is looking. Create-and-remove a probe file,
        because a permission bit says nothing about a read-only mount."""
        probe = self._path.with_name(f".{self._path.name}.writable")
        try:
            probe.unlink(missing_ok=True)  # a stale probe from a crashed boot
            fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            probe.unlink()
        except OSError as exc:
            raise RegistryError(
                f"GATEWAY_ENABLE_ADMIN=1 but the registry directory {self._path.parent} is "
                f"not writable ({type(exc).__name__}): the console writes registry.yaml, its "
                "candidate and its backups there. Mount it read-write, or leave the "
                "console off (docs/deploy/nas.md)") from exc

    def reload(self) -> Registry:
        with self._lock:
            raw = self._path.read_bytes()
            try:
                new = load_registry(self._path)
            except RegistryError as exc:
                raise self._refuse(422, str(exc), "refused: registry validation") from exc
            self._holder.swap(new)
            # The hash of the bytes read BEFORE the load: if the file changes in
            # between, the next apply sees a mismatch and 409s, which is the safe
            # direction.
            self._sha = _sha(raw)
            return new

    def _backup(self) -> None:
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        dest = self._path.with_name(f"{self._path.name}.bak-{stamp}")
        n = 2
        while dest.exists():
            dest = self._path.with_name(f"{self._path.name}.bak-{stamp}-{n}")
            n += 1
        shutil.copy2(self._path, dest)
