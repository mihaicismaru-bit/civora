from __future__ import annotations

import copy
import json
from hashlib import sha256
from pathlib import Path
from typing import Optional

from .models import utc_now
from .persistence import AtomicJsonStore, AtomicJsonStoreError
from .reconciliation import ClaimEvidenceReconciler, ReconciliationPolicy


class FactReconciliationStoreError(RuntimeError):
    pass


class FactReconciliationStore:
    """Durable reconciliation reports derived from immutable Fact Kernel revisions."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        path: Path,
        *,
        policy: ReconciliationPolicy | None = None,
    ):
        self.path = path
        self.reconciler = ClaimEvidenceReconciler(policy)
        self.store = AtomicJsonStore(
            path,
            schema_version=self.SCHEMA_VERSION,
            validator=self._validate_payload,
        )

    @staticmethod
    def default_payload() -> dict:
        return {
            "reports": {},
            "kernel_index": {},
            "story_index": {},
        }

    @staticmethod
    def _stable_report_id(kernel_record: dict, result: dict) -> str:
        basis = {
            "kernel_id": kernel_record["kernel_id"],
            "kernel_semantic_hash": kernel_record["semantic_hash"],
            "policy": result["policy"],
        }
        encoded = json.dumps(
            basis,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    @classmethod
    def _validate_report(cls, report_id: str, report: dict) -> None:
        if report.get("report_id") != report_id:
            raise FactReconciliationStoreError(
                "reconciliation report key/id mismatch"
            )
        for key in (
            "kernel_id",
            "story_id",
            "kernel_semantic_hash",
            "created_at",
        ):
            if not isinstance(report.get(key), str) or not report[key]:
                raise FactReconciliationStoreError(
                    f"reconciliation report {key} is invalid"
                )
        if not isinstance(report.get("kernel_revision"), int) or report[
            "kernel_revision"
        ] < 1:
            raise FactReconciliationStoreError(
                "reconciliation kernel revision is invalid"
            )
        result = report.get("result")
        if not isinstance(result, dict):
            raise FactReconciliationStoreError(
                "reconciliation result is invalid"
            )
        if result.get("gate") not in {
            "corroborated",
            "review_support_strength",
            "needs_review",
        }:
            raise FactReconciliationStoreError(
                "reconciliation gate is invalid"
            )
        for assessment in [
            *result.get("fact_assessments", []),
            *result.get("claim_assessments", []),
        ]:
            confidence = assessment.get("confidence")
            if not isinstance(confidence, (int, float)) or not (
                0 <= confidence <= 1
            ):
                raise FactReconciliationStoreError(
                    "reconciliation confidence is invalid"
                )
            if not isinstance(
                assessment.get("independent_source_count"), int
            ):
                raise FactReconciliationStoreError(
                    "reconciliation source count is invalid"
                )

    @classmethod
    def _validate_payload(cls, payload: dict) -> None:
        reports = payload.get("reports")
        kernel_index = payload.get("kernel_index")
        story_index = payload.get("story_index")
        if not isinstance(reports, dict):
            raise FactReconciliationStoreError(
                "reconciliation reports store is invalid"
            )
        if not isinstance(kernel_index, dict) or not isinstance(
            story_index, dict
        ):
            raise FactReconciliationStoreError(
                "reconciliation indexes are invalid"
            )
        for report_id, report in reports.items():
            cls._validate_report(report_id, report)
        for kernel_id, report_id in kernel_index.items():
            if report_id not in reports:
                raise FactReconciliationStoreError(
                    "kernel index references missing report"
                )
            if reports[report_id]["kernel_id"] != kernel_id:
                raise FactReconciliationStoreError(
                    "kernel index/report mismatch"
                )
        for story_id, report_id in story_index.items():
            if report_id not in reports:
                raise FactReconciliationStoreError(
                    "story index references missing report"
                )
            if reports[report_id]["story_id"] != story_id:
                raise FactReconciliationStoreError(
                    "story index/report mismatch"
                )

    def persist_kernel(self, kernel_record: dict) -> dict:
        result = self.reconciler.reconcile(
            confirmed_facts=kernel_record["confirmed_facts"],
            uncertain_claims=kernel_record["uncertain_claims"],
            evidence=kernel_record["evidence"],
        )
        report_id = self._stable_report_id(kernel_record, result)
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
            kernel_index = payload.setdefault("kernel_index", {})
            story_index = payload.setdefault("story_index", {})
            existing = reports.get(report_id)
            if existing is not None:
                captured["report"] = copy.deepcopy(existing)
                return
            reports[report_id] = copy.deepcopy(candidate)
            kernel_index[kernel_record["kernel_id"]] = report_id
            story_index[kernel_record["story_id"]] = report_id
            captured["report"] = copy.deepcopy(candidate)

        try:
            self.store.update(self.default_payload(), mutate)
        except AtomicJsonStoreError as exc:
            raise FactReconciliationStoreError(
                "Fact reconciliation persistence failed"
            ) from exc
        return captured["report"]

    def load_story(self, story_id: str) -> Optional[dict]:
        try:
            payload = self.store.load(self.default_payload())
        except AtomicJsonStoreError as exc:
            raise FactReconciliationStoreError(
                "Fact reconciliation load failed"
            ) from exc
        report_id = payload["story_index"].get(story_id)
        if report_id is None:
            return None
        return copy.deepcopy(payload["reports"][report_id])

    def health(self) -> dict:
        try:
            payload = self.store.load(self.default_payload())
        except (AtomicJsonStoreError, FactReconciliationStoreError) as exc:
            return {
                "status": "corrupt",
                "report_count": 0,
                "needs_review_count": 0,
                "details": [str(exc)],
            }
        needs_review = sum(
            report["result"]["gate"] != "corroborated"
            for report in payload["reports"].values()
        )
        return {
            "status": (
                "recovered_from_backup"
                if self.store.recovered_from_backup
                else "healthy"
            ),
            "report_count": len(payload["reports"]),
            "needs_review_count": needs_review,
            "details": [],
        }
