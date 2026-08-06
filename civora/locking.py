from __future__ import annotations

import json
import os
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class LockTimeoutError(TimeoutError):
    """Raised when a process cannot acquire a store lock within the configured timeout."""


@dataclass(frozen=True)
class LockOwner:
    token: str
    pid: int
    hostname: str
    acquired_at: float


class ProcessFileLock:
    """Portable lock based on exclusive lock-file creation.

    Recovery is conservative: a stale lock is removed only when it is older than
    ``stale_after`` and its owner is on this host with a PID that is no longer alive.
    Locks created on another host are never broken automatically.
    """

    def __init__(
        self,
        path: Path,
        *,
        timeout: float = 10.0,
        poll_interval: float = 0.05,
        stale_after: float = 300.0,
    ) -> None:
        if timeout < 0 or poll_interval <= 0 or stale_after <= 0:
            raise ValueError("invalid lock timing configuration")
        self.path = path
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.stale_after = stale_after
        self.owner: Optional[LockOwner] = None
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return True
        return True

    def _read_owner(self) -> Optional[LockOwner]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return LockOwner(
                token=str(payload["token"]),
                pid=int(payload["pid"]),
                hostname=str(payload["hostname"]),
                acquired_at=float(payload["acquired_at"]),
            )
        except Exception:
            return None

    def _break_abandoned_lock(self) -> bool:
        try:
            age = max(0.0, time.time() - self.path.stat().st_mtime)
        except FileNotFoundError:
            return True
        if age < self.stale_after:
            return False

        owner = self._read_owner()
        if owner is None:
            return False
        if owner.hostname != socket.gethostname():
            return False
        if self._pid_alive(owner.pid):
            return False

        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    def acquire(self) -> "ProcessFileLock":
        deadline = time.monotonic() + self.timeout
        owner = LockOwner(
            token=uuid.uuid4().hex,
            pid=os.getpid(),
            hostname=socket.gethostname(),
            acquired_at=time.time(),
        )
        encoded = json.dumps(owner.__dict__, sort_keys=True).encode("utf-8")

        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    os.write(fd, encoded)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                self.owner = owner
                return self
            except FileExistsError:
                self._break_abandoned_lock()
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(f"timed out acquiring lock: {self.path.name}")
                time.sleep(self.poll_interval)

    def release(self) -> None:
        if self.owner is None:
            return
        current = self._read_owner()
        try:
            if current is not None and current.token == self.owner.token:
                self.path.unlink(missing_ok=True)
        finally:
            self.owner = None

    def __enter__(self) -> "ProcessFileLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
