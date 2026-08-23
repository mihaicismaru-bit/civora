from __future__ import annotations

import copy
import json
from hashlib import sha256
from pathlib import Path
from typing import Optional

from .editorial_gate import ConflictResolutionGate, EditorialGateError, EditorialGatePolicy
from .models import utc_now
from .persistence import AtomicJsonStore, AtomicJsonStoreError


class EditorialGateStoreError(RuntimeError):
    pass


class EditorialGateStore:
    """Durable editorial gate decisions bound to exact derived-report inputs."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path, *, policy: EditorialGatePolicy | None = None):
        self.path = path
        self.gate = ConflictResolutionGate(policy)
        self.store = AtomicJsonStore(
            path,
            schema_version=self.SCHEMA_VERSION,
            validator=self._validate_payload,
        )

    @staticmethod
    def default_payload() -> dict:
        return {"decisions": {}, "story_index": {}}

    @staticmethod
    def _stable_decision_id(result: dict) -> str:
        basis = {
            "story_id": result["story_id"],
            "kernel_semantic_hash": result["kernel_semantic_hash"],
            "inputs": result["inputs"],
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
    def _validate_decision(cls, decision_id: str, decision: dict) -> None:
        if decision.get("decision_id") != decision_id:
            raise EditorialGateStoreError("editorial decision key/id mismatch")
        for key in ("story_id", "kernel_id", "kernel_semantic_hash", "created_at"):
            if not isinstance(decision.get(key), str) or not decision[key]:
                raise EditorialGateStoreError(f"editorial decision {key} is invalid")
        if not isinstance(decision.get("kernel_revision"), int) or decision["kernel_revision"] < 1:
            raise EditorialGateStoreError("editorial decision kernel revision is invalid")
        if decision.get("decision") not in {"auto_draft", "review"}:
            raise EditorialGateStoreError("editorial decision outcome is invalid")
        if not isinstance(decision.get("reasons"), list):
            raise EditorialGateStoreError("editorial decision reasons are invalid")
        inputs = decision.get("inputs")
        if not isinstance(inputs, dict):
            raise EditorialGateStoreError("editorial decision inputs are invalid")
        for key in ("reconciliation_report_id", "contradiction_report_id"):
            if not isinstance(inputs.get(key), str) or not inputs[key]:
                raise EditorialGateStoreError("editorial decision report reference is invalid")

    @classmethod
    def _validate_payload(cls, payload: dict) -> None:
        decisions = payload.get("decisions")
        story_index = payload.get("story_index")
        if not isinstance(decisions, dict) or not isinstance(story_index, dict):
            raise EditorialGateStoreError("editorial gate store shape is invalid")
        for decision_id, decision in decisions.items():
            cls._validate_decision(decision_id, decision)
        for story_id, decision_id in story_index.items():
            if decision_id not in decisions or decisions[decision_id].get("story_id") != story_id:
                raise EditorialGateStoreError("editorial gate story index is invalid")

    def persist_reports(self, reconciliation_report: dict, contradiction_report: dict) -> dict:
        try:
            result = self.gate.evaluate(reconciliation_report, contradiction_report)
        except EditorialGateError as exc:
            raise EditorialGateStoreError("editorial gate evaluation failed") from exc

        decision_id = self._stable_decision_id(result)
        candidate = {
            "decision_id": decision_id,
            **copy.deepcopy(result),
            "created_at": utc_now(),
        }
        captured: dict[str, dict] = {}

        def mutate(payload: dict) -> None:
            decisions = payload.setdefault("decisions", {})
            story_index = payload.setdefault("story_index", {})
            existing = decisions.get(decision_id)
            if existing is not None:
                captured["decision"] = copy.deepcopy(existing)
                return
            decisions[decision_id] = copy.deepcopy(candidate)
            story_index[result["story_id"]] = decision_id
            captured["decision"] = copy.deepcopy(candidate)

        try:
            self.store.update(self.default_payload(), mutate)
        except AtomicJsonStoreError as exc:
            raise EditorialGateStoreError("editorial gate persistence failed") from exc
        return captured["decision"]

    def load_story(self, story_id: str) -> Optional[dict]:
        try:
            payload = self.store.load(self.default_payload())
        except AtomicJsonStoreError as exc:
            raise EditorialGateStoreError("editorial gate load failed") from exc
        decision_id = payload["story_index"].get(story_id)
        if decision_id is None:
            return None
        return copy.deepcopy(payload["decisions"][decision_id])

    def health(self) -> dict:
        try:
            payload = self.store.load(self.default_payload())
        except (AtomicJsonStoreError, EditorialGateStoreError) as exc:
            return {"status": "corrupt", "decision_count": 0, "review_count": 0, "details": [str(exc)]}
        review_count = sum(
            decision["decision"] == "review"
            for decision in payload["decisions"].values()
        )
        return {
            "status": "recovered_from_backup" if self.store.recovered_from_backup else "healthy",
            "decision_count": len(payload["decisions"]),
            "review_count": review_count,
            "details": [],
        }
