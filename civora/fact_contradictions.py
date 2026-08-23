from __future__ import annotations

import copy
import json
from hashlib import sha256
from pathlib import Path
from typing import Optional

from .contradictions import ContradictionPolicy, ExplicitContradictionEngine
from .models import EvidenceRelation, utc_now
from .persistence import AtomicJsonStore, AtomicJsonStoreError


class FactContradictionStoreError(RuntimeError):
    pass


class FactContradictionStore:
    """Durable contradiction reports bound to one Fact Kernel semantic revision."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        path: Path,
        *,
        policy: ContradictionPolicy | None = None,
    ):
        self.path = path
        self.engine = ExplicitContradictionEngine(policy)
        self.store = AtomicJsonStore(
            path,
            schema_version=self.SCHEMA_VERSION,
            validator=self._validate_payload,
        )

    @staticmethod
    def default_payload() -> dict:
        return {"reports": {}, "story_index": {}}

    @staticmethod
    def _relation_basis(relations: list[EvidenceRelation]) -> list[dict]:
        basis = [
            {
                "target_statement": relation.target_statement,
                "source_id": relation.source_id,
                "evidence_claim": relation.evidence_claim,
                "polarity": relation.polarity.value,
            }
            for relation in relations
        ]
        basis.sort(
            key=lambda item: (
                item["target_statement"].casefold().strip(),
                item["source_id"],
                item["evidence_claim"].casefold().strip(),
                item["polarity"],
            )
        )
        return basis

    @classmethod
    def _stable_report_id(cls, kernel_record: dict, relations: list[EvidenceRelation], result: dict) -> str:
        basis = {
            "kernel_id": kernel_record["kernel_id"],
            "kernel_semantic_hash": kernel_record["semantic_hash"],
            "relations": cls._relation_basis(relations),
            "policy": result["policy"],
        }
        return sha256(
            json.dumps(
                basis,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _validate_report(cls, report_id: str, report: dict) -> None:
        if report.get("report_id") != report_id:
            raise FactContradictionStoreError("contradiction report key/id mismatch")
        for key in ("kernel_id", "story_id", "kernel_semantic_hash", "created_at"):
            if not isinstance(report.get(key), str) or not report[key]:
                raise FactContradictionStoreError(f"contradiction report {key} is invalid")
        if not isinstance(report.get("kernel_revision"), int) or report["kernel_revision"] < 1:
            raise FactContradictionStoreError("contradiction kernel revision is invalid")
        result = report.get("result")
        if not isinstance(result, dict) or result.get("gate") not in {"clear", "conflict_review"}:
            raise FactContradictionStoreError("contradiction result is invalid")
        for assessment in result.get("assessments", []):
            if assessment.get("status") not in {"uncontested", "disputed", "contradicted", "unresolved"}:
                raise FactContradictionStoreError("contradiction status is invalid")
            for key in ("support_confidence", "contradiction_confidence"):
                value = assessment.get(key)
                if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                    raise FactContradictionStoreError("contradiction confidence is invalid")

    @classmethod
    def _validate_payload(cls, payload: dict) -> None:
        reports = payload.get("reports")
        story_index = payload.get("story_index")
        if not isinstance(reports, dict) or not isinstance(story_index, dict):
            raise FactContradictionStoreError("contradiction store shape is invalid")
        for report_id, report in reports.items():
            cls._validate_report(report_id, report)
        for story_id, report_id in story_index.items():
            if report_id not in reports or reports[report_id].get("story_id") != story_id:
                raise FactContradictionStoreError("contradiction story index is invalid")

    def persist_kernel(self, kernel_record: dict, relations: list[EvidenceRelation]) -> dict:
        try:
            result = self.engine.evaluate(kernel_record, relations)
        except ValueError as exc:
            raise FactContradictionStoreError("contradiction evaluation failed") from exc
        report_id = self._stable_report_id(kernel_record, relations, result)
        candidate = {
            "report_id": report_id,
            "kernel_id": kernel_record["kernel_id"],
            "story_id": kernel_record["story_id"],
            "kernel_revision": kernel_record["revision"],
            "kernel_semantic_hash": kernel_record["semantic_hash"],
            "created_at": utc_now(),
            "result": result,
        }
        captured: dict[str, dict] = {}

        def mutate(payload: dict) -> None:
            reports = payload.setdefault("reports", {})
            story_index = payload.setdefault("story_index", {})
            existing = reports.get(report_id)
            if existing is not None:
                captured["report"] = copy.deepcopy(existing)
                return
            reports[report_id] = copy.deepcopy(candidate)
            story_index[kernel_record["story_id"]] = report_id
            captured["report"] = copy.deepcopy(candidate)

        try:
            self.store.update(self.default_payload(), mutate)
        except AtomicJsonStoreError as exc:
            raise FactContradictionStoreError("Fact contradiction persistence failed") from exc
        return captured["report"]

    def load_story(self, story_id: str) -> Optional[dict]:
        try:
            payload = self.store.load(self.default_payload())
        except AtomicJsonStoreError as exc:
            raise FactContradictionStoreError("Fact contradiction load failed") from exc
        report_id = payload["story_index"].get(story_id)
        if report_id is None:
            return None
        return copy.deepcopy(payload["reports"][report_id])

    def health(self) -> dict:
        try:
            payload = self.store.load(self.default_payload())
        except (AtomicJsonStoreError, FactContradictionStoreError) as exc:
            return {"status": "corrupt", "report_count": 0, "conflict_count": 0, "details": [str(exc)]}
        conflict_count = sum(
            report["result"]["gate"] == "conflict_review"
            for report in payload["reports"].values()
        )
        return {
            "status": "recovered_from_backup" if self.store.recovered_from_backup else "healthy",
            "report_count": len(payload["reports"]),
            "conflict_count": conflict_count,
            "details": [],
        }
