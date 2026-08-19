#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

Validator = Callable[[dict[str, Any]], None]


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return digest_bytes(canonical_bytes(value))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def current_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return digest_bytes(path.read_bytes())


def atomic_write_json(
    path: Path,
    payload: dict[str, Any],
    *,
    validator: Validator,
    expected_hash: str | None = None,
    version: int,
) -> dict[str, Any]:
    if version < 1:
        raise ValueError("version must be positive")
    validator(payload)
    before = current_hash(path)
    if expected_hash is not None and before != expected_hash:
        raise ValueError("stale expected hash")

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".prepare", dir=path.parent)
    temp = Path(temp_name)
    committed = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        prepared_hash = digest_bytes(temp.read_bytes())
        if prepared_hash != digest_bytes(encoded):
            raise ValueError("prepared file checksum mismatch")
        os.replace(temp, path)
        committed = True
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if not committed and temp.exists():
            temp.unlink()

    after = current_hash(path)
    receipt = {
        "protocol": ["PREPARE", "VALIDATE", "ATOMIC_COMMIT", "RECEIPT"],
        "state_path": str(path),
        "version": version,
        "preimage_hash": before,
        "postimage_hash": after,
        "payload_hash": digest_json(payload),
        "committed": True,
    }
    receipt["receipt_hash"] = digest_json(receipt)
    return receipt


def append_only_receipt(path: Path, receipt: dict[str, Any]) -> None:
    if path.exists():
        raise ValueError("receipt overwrite forbidden")
    atomic_write_json(path, receipt, validator=lambda value: None, version=1)


def find_orphan_prepare_files(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(path.name for path in directory.glob(".*.prepare"))
