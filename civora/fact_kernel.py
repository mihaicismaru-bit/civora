from __future__ import annotations

import copy
import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Optional

from .models import Evidence, StoryObject, VerificationStatus, utc_now
from .persistence import AtomicJsonStore, AtomicJsonStoreError


class FactKernelStoreError(RuntimeError):
    pass


def normalize_statement(value: str) -> str:
    """Normalize a statement for deterministic identity and exact reconciliation."""
    value = value.casefold().strip()
    value = re.sub(r"\s+", " ", value)
    return value


def _stable_id(prefix: str, *parts: str) -> str:
    encoded = "\x1f".join([prefix, *parts]).encode("utf-8")
    return sha256(encoded).hexdigest()


class FactKernelStore:
    """Durable, revisioned Fact Kernel persistence.

    Version 1 deliberately uses conservative exact-normalized evidence matching.
    A confirmed statement with no matching evidence is preserved, but is marked
    ``unlinked`` and forces the kernel gate to ``needs_review``. This avoids
    silently manufacturing provenance while providing a durable base for later
    semantic claim/evidence reconciliation.
    """

    SCHEMA_VERSION = 1

    def __init__(self, path: Path):
        self.path = path
        self.store = AtomicJsonStore(
            path,
            schema_version=self.SCHEMA_VERSION,
            validator=self._validate_payload,
        )

    @staticmethod
    def default_payload() -> dict:
        return {
            "kernels": {},
            "story_index": {},
            "history": {},
        }

    @staticmethod
    def _evidence_record(evidence: Evidence) -> dict:
        normalized_claim = normalize_statement(evidence.claim)
        evidence_id = _stable_id(
            "evidence",
            str(evidence.source_id),
            normalized_claim,
            str(evidence.url or ""),
        )
        return {
            "evidence_id": evidence_id,
            "source_id": evidence.source_id,
            "claim": evidence.claim,
            "normalized_claim": normalized_claim,
            "url": evidence.url,
            "captured_at": evidence.captured_at,
            "confidence": float(evidence.confidence),
        }

    @staticmethod
    def _deduplicate_statements(values: list[str]) -> list[str]:
        seen = set()
        result = []
        for value in values:
            normalized = normalize_statement(value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(value.strip())
        return result

    def build_record(self, story: StoryObject) -> dict:
        evidence_records = [
            self._evidence_record(evidence)
            for evidence in story.fact_kernel.evidence
        ]
        evidence_records.sort(key=lambda item: item["evidence_id"])

        evidence_by_claim: dict[str, list[str]] = {}
        for evidence in evidence_records:
            evidence_by_claim.setdefault(
                evidence["normalized_claim"], []
            ).append(evidence["evidence_id"])

        confirmed_facts = []
        for statement in self._deduplicate_statements(
            story.fact_kernel.confirmed_facts
        ):
            normalized = normalize_statement(statement)
            evidence_ids = sorted(evidence_by_claim.get(normalized, []))
            confirmed_facts.append(
                {
                    "fact_id": _stable_id("fact", normalized),
                    "statement": statement,
                    "normalized_statement": normalized,
                    "evidence_ids": evidence_ids,
                    "provenance_status": (
                        "grounded" if evidence_ids else "unlinked"
                    ),
                }
            )

        uncertain_claims = []
        for statement in self._deduplicate_statements(
            story.fact_kernel.uncertain_claims
        ):
            normalized = normalize_statement(statement)
            uncertain_claims.append(
                {
                    "claim_id": _stable_id("claim", normalized),
                    "statement": statement,
                    "normalized_statement": normalized,
                    "evidence_ids": sorted(
                        evidence_by_claim.get(normalized, [])
                    ),
                }
            )

        grounded_count = sum(
            fact["provenance_status"] == "grounded"
            for fact in confirmed_facts
        )
        coverage = (
            grounded_count / len(confirmed_facts)
            if confirmed_facts
            else 0.0
        )
        source_ids = sorted(
            {record["source_id"] for record in evidence_records}
        )
        gate = (
            "grounded"
            if confirmed_facts and coverage == 1.0
            else "needs_review"
        )

        semantic_basis = {
            "story_id": story.id,
            "story_version": story.version,
            "verification_status": (
                story.fact_kernel.verification_status.value
            ),
            "confirmed_facts": confirmed_facts,
            "uncertain_claims": uncertain_claims,
            "affected_groups": sorted(
                self._deduplicate_statements(
                    story.fact_kernel.affected_groups
                ),
                key=normalize_statement,
            ),
            "next_expected_event": story.fact_kernel.next_expected_event,
            "evidence": evidence_records,
        }
        semantic_hash = sha256(
            json.dumps(
                semantic_basis,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        return {
            "kernel_id": _stable_id("kernel", story.id),
            **semantic_basis,
            "semantic_hash": semantic_hash,
            "provenance_coverage": round(coverage, 4),
            "independent_source_count": len(source_ids),
            "gate": gate,
        }

    @classmethod
    def _validate_kernel(cls, kernel_id: str, record: dict) -> None:
        if record.get("kernel_id") != kernel_id:
            raise FactKernelStoreError("Fact Kernel key/id mismatch")
        if not isinstance(record.get("story_id"), str) or not record[
            "story_id"
        ]:
            raise FactKernelStoreError("Fact Kernel story_id is invalid")
        if not isinstance(record.get("revision"), int) or record[
            "revision"
        ] < 1:
            raise FactKernelStoreError("Fact Kernel revision is invalid")
        if record.get("verification_status") not in {
            item.value for item in VerificationStatus
        }:
            raise FactKernelStoreError(
                "Fact Kernel verification status is invalid"
            )
        semantic_hash = record.get("semantic_hash")
        if not isinstance(semantic_hash, str) or len(semantic_hash) != 64:
            raise FactKernelStoreError("Fact Kernel semantic hash is invalid")
        if record.get("gate") not in {"grounded", "needs_review"}:
            raise FactKernelStoreError("Fact Kernel gate is invalid")
        coverage = record.get("provenance_coverage")
        if not isinstance(coverage, (int, float)) or not 0 <= coverage <= 1:
            raise FactKernelStoreError(
                "Fact Kernel provenance coverage is invalid"
            )

        evidence_ids = set()
        for evidence in record.get("evidence", []):
            evidence_id = evidence.get("evidence_id")
            if not isinstance(evidence_id, str) or not evidence_id:
                raise FactKernelStoreError("evidence_id is invalid")
            if evidence_id in evidence_ids:
                raise FactKernelStoreError("duplicate evidence_id")
            evidence_ids.add(evidence_id)
            confidence = evidence.get("confidence")
            if not isinstance(confidence, (int, float)) or not (
                0 <= confidence <= 1
            ):
                raise FactKernelStoreError(
                    "evidence confidence is invalid"
                )

        fact_ids = set()
        for fact in record.get("confirmed_facts", []):
            fact_id = fact.get("fact_id")
            if not isinstance(fact_id, str) or not fact_id:
                raise FactKernelStoreError("fact_id is invalid")
            if fact_id in fact_ids:
                raise FactKernelStoreError("duplicate fact_id")
            fact_ids.add(fact_id)
            if fact.get("provenance_status") not in {
                "grounded",
                "unlinked",
            }:
                raise FactKernelStoreError(
                    "fact provenance status is invalid"
                )
            refs = fact.get("evidence_ids", [])
            if any(ref not in evidence_ids for ref in refs):
                raise FactKernelStoreError(
                    "fact references unknown evidence"
                )
            if bool(refs) != (
                fact.get("provenance_status") == "grounded"
            ):
                raise FactKernelStoreError(
                    "fact provenance status does not match evidence refs"
                )

        claim_ids = set()
        for claim in record.get("uncertain_claims", []):
            claim_id = claim.get("claim_id")
            if not isinstance(claim_id, str) or not claim_id:
                raise FactKernelStoreError("claim_id is invalid")
            if claim_id in claim_ids:
                raise FactKernelStoreError("duplicate claim_id")
            claim_ids.add(claim_id)
            if any(
                ref not in evidence_ids
                for ref in claim.get("evidence_ids", [])
            ):
                raise FactKernelStoreError(
                    "claim references unknown evidence"
                )

    @classmethod
    def _validate_payload(cls, payload: dict) -> None:
        kernels = payload.get("kernels")
        story_index = payload.get("story_index")
        history = payload.get("history")
        if not isinstance(kernels, dict):
            raise FactKernelStoreError("Fact Kernel store kernels invalid")
        if not isinstance(story_index, dict):
            raise FactKernelStoreError(
                "Fact Kernel store story index invalid"
            )
        if not isinstance(history, dict):
            raise FactKernelStoreError("Fact Kernel history invalid")

        for kernel_id, record in kernels.items():
            cls._validate_kernel(kernel_id, record)
        for story_id, kernel_id in story_index.items():
            if kernel_id not in kernels:
                raise FactKernelStoreError(
                    "story index references missing kernel"
                )
            if kernels[kernel_id].get("story_id") != story_id:
                raise FactKernelStoreError(
                    "story index/kernel story mismatch"
                )
        for kernel_id, revisions in history.items():
            if kernel_id not in kernels:
                raise FactKernelStoreError(
                    "history references missing current kernel"
                )
            if not isinstance(revisions, list):
                raise FactKernelStoreError("kernel history must be a list")
            for record in revisions:
                cls._validate_kernel(kernel_id, record)

    def persist_story(self, story: StoryObject) -> dict:
        candidate = self.build_record(story)
        captured: dict[str, dict] = {}

        def mutate(payload: dict) -> None:
            kernels = payload.setdefault("kernels", {})
            story_index = payload.setdefault("story_index", {})
            history = payload.setdefault("history", {})

            kernel_id = candidate["kernel_id"]
            existing = kernels.get(kernel_id)
            if existing is not None and existing.get(
                "semantic_hash"
            ) == candidate["semantic_hash"]:
                captured["record"] = copy.deepcopy(existing)
                return

            revision = (
                int(existing["revision"]) + 1
                if existing is not None
                else 1
            )
            now = utc_now()
            record = {
                **copy.deepcopy(candidate),
                "revision": revision,
                "created_at": (
                    existing.get("created_at", now)
                    if existing is not None
                    else now
                ),
                "updated_at": now,
            }
            if existing is not None:
                history.setdefault(kernel_id, []).append(
                    copy.deepcopy(existing)
                )
            kernels[kernel_id] = record
            story_index[story.id] = kernel_id
            history.setdefault(kernel_id, history.get(kernel_id, []))
            captured["record"] = copy.deepcopy(record)

        try:
            self.store.update(self.default_payload(), mutate)
        except AtomicJsonStoreError as exc:
            raise FactKernelStoreError(
                "Fact Kernel persistence failed"
            ) from exc
        return captured["record"]

    def load_story(self, story_id: str) -> Optional[dict]:
        try:
            payload = self.store.load(self.default_payload())
        except AtomicJsonStoreError as exc:
            raise FactKernelStoreError("Fact Kernel load failed") from exc
        kernel_id = payload["story_index"].get(story_id)
        if kernel_id is None:
            return None
        return copy.deepcopy(payload["kernels"][kernel_id])

    def history_for_story(self, story_id: str) -> list[dict]:
        try:
            payload = self.store.load(self.default_payload())
        except AtomicJsonStoreError as exc:
            raise FactKernelStoreError("Fact Kernel load failed") from exc
        kernel_id = payload["story_index"].get(story_id)
        if kernel_id is None:
            return []
        return copy.deepcopy(payload["history"].get(kernel_id, []))

    def needs_review(self) -> list[dict]:
        try:
            payload = self.store.load(self.default_payload())
        except AtomicJsonStoreError as exc:
            raise FactKernelStoreError("Fact Kernel load failed") from exc
        return [
            copy.deepcopy(record)
            for record in payload["kernels"].values()
            if record.get("gate") == "needs_review"
        ]

    def health(self) -> dict:
        try:
            payload = self.store.load(self.default_payload())
        except (AtomicJsonStoreError, FactKernelStoreError) as exc:
            return {
                "status": "corrupt",
                "kernel_count": 0,
                "needs_review_count": 0,
                "details": [str(exc)],
            }
        needs_review_count = sum(
            record.get("gate") == "needs_review"
            for record in payload["kernels"].values()
        )
        return {
            "status": (
                "recovered_from_backup"
                if self.store.recovered_from_backup
                else "healthy"
            ),
            "kernel_count": len(payload["kernels"]),
            "needs_review_count": needs_review_count,
            "details": [],
        }
