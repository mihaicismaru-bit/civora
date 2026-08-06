from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Dict, Iterable, List

from .models import Signal
from .persistence import AtomicJsonStore, AtomicJsonStoreError


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
    """Atomic, checksum-protected signal store with semantic deduplication."""

    SCHEMA_VERSION = 2

    def __init__(self, path: Path):
        self.path = path
        self.records: Dict[str, dict] = {}
        self.fingerprints: Dict[str, str] = {}
        self.store = AtomicJsonStore(
            path,
            schema_version=self.SCHEMA_VERSION,
            validator=self._validate_payload,
        )
        self.recovered_from_backup = False
        self.load()

    @staticmethod
    def _checksum(payload: dict) -> str:
        """Compatibility helper retained for validation tests and tooling."""
        return AtomicJsonStore.checksum(payload)

    @staticmethod
    def _validate_payload(payload: dict) -> None:
        signals = payload.get("signals")
        fingerprints = payload.get("fingerprints")
        if not isinstance(signals, dict):
            raise AtomicJsonStoreError("signal records must be an object")
        if not isinstance(fingerprints, dict):
            raise AtomicJsonStoreError("fingerprint index must be an object")

        signal_ids = set(signals)
        for signal_id, item in signals.items():
            if not isinstance(signal_id, str) or not signal_id:
                raise AtomicJsonStoreError("signal id must be a non-empty string")
            if not isinstance(item, dict) or item.get("id") != signal_id:
                raise AtomicJsonStoreError("signal record id does not match its key")
            try:
                Signal(**item)
            except Exception as exc:
                raise AtomicJsonStoreError("signal record is invalid") from exc

        for fingerprint, signal_id in fingerprints.items():
            if not isinstance(fingerprint, str) or not fingerprint:
                raise AtomicJsonStoreError("invalid fingerprint key")
            if not isinstance(signal_id, str) or signal_id not in signal_ids:
                raise AtomicJsonStoreError("fingerprint references an unknown signal")

    def load(self) -> None:
        self.records = {}
        self.fingerprints = {}
        default = {"signals": {}, "fingerprints": {}}
        try:
            payload = self.store.load(default)
        except AtomicJsonStoreError as exc:
            raise SignalStoreError(str(exc)) from exc
        self.recovered_from_backup = self.store.recovered_from_backup
        self.records = payload.get("signals", {})
        self.fingerprints = payload.get("fingerprints", {})

    def save(self) -> None:
        payload = {
            "signals": self.records,
            "fingerprints": self.fingerprints,
        }
        try:
            self.store.save(payload)
        except AtomicJsonStoreError as exc:
            raise SignalStoreError(str(exc)) from exc

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
