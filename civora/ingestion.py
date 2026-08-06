from __future__ import annotations
from dataclasses import dataclass, asdict
from hashlib import sha256
from pathlib import Path
from typing import Dict, Iterable, List
import copy
import json
import os
import re
import tempfile

from .models import Signal


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def signal_fingerprint(title: str, summary: str, geography: Iterable[str]) -> str:
    canonical = "|".join([
        _normalize_text(title),
        _normalize_text(summary),
        ",".join(sorted(_normalize_text(x) for x in geography)),
    ])
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class IngestResult:
    accepted: List[Signal]
    duplicate_ids: List[str]
    rejected: List[Dict[str, str]]


class SignalStoreError(RuntimeError):
    """Raised when the persistent signal store cannot be validated safely."""


class SignalStore:
    """Crash-safe persistent signal store with semantic deduplication.

    Every committed payload contains a checksum. Writes use fsync plus atomic
    replacement, while the previous valid generation is retained as a backup.
    A corrupt primary file is restored from the backup; if neither generation
    validates, startup fails closed instead of silently losing evidence.
    """

    SCHEMA_VERSION = 2

    def __init__(self, path: Path):
        self.path = path
        self.backup_path = path.with_suffix(path.suffix + ".bak")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.records: Dict[str, dict] = {}
        self.fingerprints: Dict[str, str] = {}
        self.recovered_from_backup = False
        self.load()

    @staticmethod
    def _checksum(payload: dict) -> str:
        basis = copy.deepcopy(payload)
        basis.pop("checksum", None)
        encoded = json.dumps(
            basis,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    @classmethod
    def _validate_payload(cls, payload: dict) -> None:
        if payload.get("schema_version") != cls.SCHEMA_VERSION:
            raise SignalStoreError("unsupported signal-store schema")
        if not isinstance(payload.get("signals"), dict):
            raise SignalStoreError("signal records must be an object")
        if not isinstance(payload.get("fingerprints"), dict):
            raise SignalStoreError("fingerprint index must be an object")
        if payload.get("checksum") != cls._checksum(payload):
            raise SignalStoreError("signal-store checksum mismatch")

        signal_ids = set(payload["signals"])
        for fingerprint, signal_id in payload["fingerprints"].items():
            if not isinstance(fingerprint, str) or not isinstance(signal_id, str):
                raise SignalStoreError("invalid fingerprint index entry")
            if signal_id not in signal_ids:
                raise SignalStoreError("fingerprint references an unknown signal")

    @classmethod
    def _read_validated(cls, path: Path) -> dict:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SignalStoreError(f"cannot read signal store: {path.name}") from exc
        cls._validate_payload(payload)
        return payload

    @staticmethod
    def _atomic_write(path: Path, payload: dict) -> None:
        fd, temporary = tempfile.mkstemp(
            prefix=path.name + ".",
            suffix=".tmp",
            dir=path.parent,
        )
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

    def load(self) -> None:
        self.records = {}
        self.fingerprints = {}
        self.recovered_from_backup = False

        if not self.path.exists() and not self.backup_path.exists():
            return

        try:
            payload = self._read_validated(self.path)
        except SignalStoreError as primary_error:
            if not self.backup_path.exists():
                raise primary_error
            try:
                payload = self._read_validated(self.backup_path)
            except SignalStoreError as backup_error:
                raise SignalStoreError(
                    "primary and backup signal-store generations are invalid"
                ) from backup_error
            self._atomic_write(self.path, payload)
            self.recovered_from_backup = True

        self.records = payload["signals"]
        self.fingerprints = payload["fingerprints"]

    def save(self) -> None:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "signals": self.records,
            "fingerprints": self.fingerprints,
        }
        payload["checksum"] = self._checksum(payload)
        self._validate_payload(payload)

        if self.path.exists():
            current = self._read_validated(self.path)
            self._atomic_write(self.backup_path, current)

        self._atomic_write(self.path, payload)

    def ingest(self, raw_items: Iterable[dict]) -> IngestResult:
        accepted: List[Signal] = []
        duplicate_ids: List[str] = []
        rejected: List[Dict[str, str]] = []

        original_records = copy.deepcopy(self.records)
        original_fingerprints = copy.deepcopy(self.fingerprints)

        for raw in raw_items:
            try:
                required = ["title", "summary", "geography", "source_ids"]
                missing = [key for key in required if not raw.get(key)]
                if missing:
                    raise ValueError(f"missing required fields: {', '.join(missing)}")

                fp = signal_fingerprint(raw["title"], raw["summary"], raw["geography"])
                if fp in self.fingerprints:
                    duplicate_ids.append(self.fingerprints[fp])
                    continue

                signal = Signal(
                    title=raw["title"],
                    summary=raw["summary"],
                    geography=list(raw["geography"]),
                    source_ids=list(raw["source_ids"]),
                    public_interest=float(raw.get("public_interest", 0.5)),
                    impact=float(raw.get("impact", 0.5)),
                    novelty=float(raw.get("novelty", 0.5)),
                    utility=float(raw.get("utility", 0.5)),
                    factual_risk=float(raw.get("factual_risk", 0.5)),
                )
                self.records[signal.id] = asdict(signal)
                self.fingerprints[fp] = signal.id
                accepted.append(signal)
            except Exception as exc:
                rejected.append({"item": repr(raw), "reason": str(exc)})

        try:
            self.save()
        except Exception:
            self.records = original_records
            self.fingerprints = original_fingerprints
            raise

        return IngestResult(accepted, duplicate_ids, rejected)
