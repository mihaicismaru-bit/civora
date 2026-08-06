from __future__ import annotations
from dataclasses import dataclass, asdict
from hashlib import sha256
from pathlib import Path
from typing import Dict, Iterable, List
import json
import re

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


class SignalStore:
    """Persistent signal store with exact semantic fingerprint deduplication."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.records: Dict[str, dict] = {}
        self.fingerprints: Dict[str, str] = {}
        self.load()

    def load(self) -> None:
        self.records = {}
        self.fingerprints = {}
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.records = payload.get("signals", {})
        self.fingerprints = payload.get("fingerprints", {})

    def save(self) -> None:
        payload = {
            "schema_version": 1,
            "signals": self.records,
            "fingerprints": self.fingerprints,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def ingest(self, raw_items: Iterable[dict]) -> IngestResult:
        accepted: List[Signal] = []
        duplicate_ids: List[str] = []
        rejected: List[Dict[str, str]] = []

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

        self.save()
        return IngestResult(accepted, duplicate_ids, rejected)
