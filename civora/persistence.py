from __future__ import annotations

import copy
import json
import os
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Callable, Optional

from .locking import ProcessFileLock


class AtomicJsonStoreError(RuntimeError):
    pass


class AtomicJsonStore:
    def __init__(
        self,
        path: Path,
        *,
        schema_version: int,
        validator: Optional[Callable[[dict], None]] = None,
        lock_timeout: float = 10.0,
        stale_lock_after: float = 300.0,
    ):
        self.path = path
        self.backup_path = path.with_suffix(path.suffix + ".bak")
        self.lock_path = path.with_suffix(path.suffix + ".lock")
        self.schema_version = schema_version
        self.validator = validator
        self.lock_timeout = lock_timeout
        self.stale_lock_after = stale_lock_after
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.recovered_from_backup = False

    def _lock(self) -> ProcessFileLock:
        return ProcessFileLock(
            self.lock_path,
            timeout=self.lock_timeout,
            stale_after=self.stale_lock_after,
        )

    @staticmethod
    def checksum(payload: dict) -> str:
        basis = copy.deepcopy(payload)
        basis.pop("checksum", None)
        encoded = json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(encoded).hexdigest()

    def validate(self, payload: dict) -> None:
        if payload.get("schema_version") != self.schema_version:
            raise AtomicJsonStoreError("unsupported JSON-store schema")
        if payload.get("checksum") != self.checksum(payload):
            raise AtomicJsonStoreError("JSON-store checksum mismatch")
        if self.validator is not None:
            self.validator(payload)

    def read_validated(self, path: Path) -> dict:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise AtomicJsonStoreError(f"cannot read JSON store: {path.name}") from exc
        self.validate(payload)
        return payload

    @staticmethod
    def _atomic_write(path: Path, payload: dict) -> None:
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def _load_unlocked(self, default: dict) -> dict:
        self.recovered_from_backup = False
        if not self.path.exists() and not self.backup_path.exists():
            return copy.deepcopy(default)
        try:
            return self.read_validated(self.path)
        except AtomicJsonStoreError as primary_error:
            if not self.backup_path.exists():
                raise primary_error
            try:
                payload = self.read_validated(self.backup_path)
            except AtomicJsonStoreError as backup_error:
                raise AtomicJsonStoreError("primary and backup JSON-store generations are invalid") from backup_error
            self._atomic_write(self.path, payload)
            self.recovered_from_backup = True
            return payload

    def load(self, default: dict) -> dict:
        with self._lock():
            return self._load_unlocked(default)

    def save(self, payload: dict) -> dict:
        with self._lock():
            committed = copy.deepcopy(payload)
            committed["schema_version"] = self.schema_version
            committed["checksum"] = self.checksum(committed)
            self.validate(committed)
            if self.path.exists():
                current = self.read_validated(self.path)
                self._atomic_write(self.backup_path, current)
            self._atomic_write(self.path, committed)
            return committed
