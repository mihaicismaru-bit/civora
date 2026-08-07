from __future__ import annotations

import copy
import json
from hashlib import sha256
from pathlib import Path
from typing import Optional

from .models import utc_now
from .persistence import AtomicJsonStore, AtomicJsonStoreError


class EditorialApprovalError(RuntimeError):
    pass


class EditorialApprovalStore:
    """Durable human/operator approval cases for stories blocked by editorial gate.

    Approval is bound to the exact immutable editorial gate decision. Cases are
    single-decision: pending may transition once to approved, rejected, or
    revision_required. A revised story must generate a new gate decision and
    therefore a new approval case; stale approvals cannot authorize new facts.
    """

    SCHEMA_VERSION = 1
    FINAL_STATES = {"approved", "rejected", "revision_required"}
    ALLOWED_STATES = {"pending", *FINAL_STATES}

    def __init__(self, path: Path):
        self.path = path
        self.store = AtomicJsonStore(
            path,
            schema_version=self.SCHEMA_VERSION,
            validator=self._validate_payload,
        )

    @staticmethod
    def default_payload() -> dict:
        return {"cases": {}, "story_index": {}, "gate_index": {}}

    @staticmethod
    def _case_id(editorial_decision: dict) -> str:
        basis = {
            "story_id": editorial_decision["story_id"],
            "decision_id": editorial_decision["decision_id"],
            "kernel_semantic_hash": editorial_decision["kernel_semantic_hash"],
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
    def _validate_case(cls, case_id: str, record: dict) -> None:
        if record.get("case_id") != case_id:
            raise EditorialApprovalError("approval case key/id mismatch")
        for key in (
            "story_id",
            "editorial_decision_id",
            "kernel_semantic_hash",
            "state",
            "created_at",
            "updated_at",
        ):
            if not isinstance(record.get(key), str) or not record[key]:
                raise EditorialApprovalError(f"approval case {key} is invalid")
        if record["state"] not in cls.ALLOWED_STATES:
            raise EditorialApprovalError("approval case state is invalid")
        history = record.get("history")
        if not isinstance(history, list) or not history:
            raise EditorialApprovalError("approval case history is invalid")
        if history[0].get("to") != "pending":
            raise EditorialApprovalError("approval case must begin pending")
        for event in history:
            if event.get("to") not in cls.ALLOWED_STATES:
                raise EditorialApprovalError("approval transition target is invalid")
            for key in ("at", "actor", "reason"):
                if not isinstance(event.get(key), str) or not event[key]:
                    raise EditorialApprovalError("approval transition audit is invalid")
        if history[-1].get("to") != record["state"]:
            raise EditorialApprovalError("approval history/state mismatch")

    @classmethod
    def _validate_payload(cls, payload: dict) -> None:
        cases = payload.get("cases")
        story_index = payload.get("story_index")
        gate_index = payload.get("gate_index")
        if not isinstance(cases, dict) or not isinstance(story_index, dict) or not isinstance(gate_index, dict):
            raise EditorialApprovalError("approval store shape is invalid")
        for case_id, record in cases.items():
            cls._validate_case(case_id, record)
        for story_id, case_id in story_index.items():
            if case_id not in cases or cases[case_id].get("story_id") != story_id:
                raise EditorialApprovalError("approval story index is invalid")
        for decision_id, case_id in gate_index.items():
            if case_id not in cases or cases[case_id].get("editorial_decision_id") != decision_id:
                raise EditorialApprovalError("approval gate index is invalid")

    @staticmethod
    def _validate_editorial_decision(editorial_decision: dict) -> None:
        if editorial_decision.get("decision") != "review":
            raise EditorialApprovalError("approval case requires a review editorial decision")
        for key in ("decision_id", "story_id", "kernel_semantic_hash"):
            if not isinstance(editorial_decision.get(key), str) or not editorial_decision[key]:
                raise EditorialApprovalError("editorial decision reference is invalid")

    def ensure_pending(self, editorial_decision: dict) -> dict:
        self._validate_editorial_decision(editorial_decision)
        case_id = self._case_id(editorial_decision)
        captured: dict[str, dict] = {}

        def mutate(payload: dict) -> None:
            cases = payload.setdefault("cases", {})
            story_index = payload.setdefault("story_index", {})
            gate_index = payload.setdefault("gate_index", {})
            existing = cases.get(case_id)
            if existing is not None:
                captured["case"] = copy.deepcopy(existing)
                return
            now = utc_now()
            record = {
                "case_id": case_id,
                "story_id": editorial_decision["story_id"],
                "editorial_decision_id": editorial_decision["decision_id"],
                "kernel_semantic_hash": editorial_decision["kernel_semantic_hash"],
                "state": "pending",
                "created_at": now,
                "updated_at": now,
                "history": [
                    {
                        "from": None,
                        "to": "pending",
                        "at": now,
                        "actor": "system",
                        "reason": "editorial_gate_review",
                    }
                ],
            }
            cases[case_id] = record
            story_index[record["story_id"]] = case_id
            gate_index[record["editorial_decision_id"]] = case_id
            captured["case"] = copy.deepcopy(record)

        try:
            self.store.update(self.default_payload(), mutate)
        except AtomicJsonStoreError as exc:
            raise EditorialApprovalError("approval persistence failed") from exc
        return captured["case"]

    def decide(self, case_id: str, *, action: str, actor: str, reason: str) -> dict:
        if action not in self.FINAL_STATES:
            raise EditorialApprovalError("invalid approval action")
        actor = actor.strip()
        reason = reason.strip()
        if not actor or not reason:
            raise EditorialApprovalError("approval decisions require actor and reason")
        captured: dict[str, dict] = {}

        def mutate(payload: dict) -> None:
            record = payload.setdefault("cases", {}).get(case_id)
            if record is None:
                raise EditorialApprovalError("unknown approval case")
            if record.get("state") != "pending":
                raise EditorialApprovalError("approval case is already resolved")
            now = utc_now()
            event = {
                "from": "pending",
                "to": action,
                "at": now,
                "actor": actor,
                "reason": reason,
            }
            record["state"] = action
            record["updated_at"] = now
            record.setdefault("history", []).append(event)
            captured["case"] = copy.deepcopy(record)

        try:
            self.store.update(self.default_payload(), mutate)
        except AtomicJsonStoreError as exc:
            raise EditorialApprovalError("approval persistence failed") from exc
        return captured["case"]

    def load_case(self, case_id: str) -> Optional[dict]:
        try:
            payload = self.store.load(self.default_payload())
        except AtomicJsonStoreError as exc:
            raise EditorialApprovalError("approval load failed") from exc
        record = payload["cases"].get(case_id)
        return copy.deepcopy(record) if record is not None else None

    def load_story(self, story_id: str) -> Optional[dict]:
        try:
            payload = self.store.load(self.default_payload())
        except AtomicJsonStoreError as exc:
            raise EditorialApprovalError("approval load failed") from exc
        case_id = payload["story_index"].get(story_id)
        if case_id is None:
            return None
        return copy.deepcopy(payload["cases"][case_id])

    def load_gate_decision(self, decision_id: str) -> Optional[dict]:
        try:
            payload = self.store.load(self.default_payload())
        except AtomicJsonStoreError as exc:
            raise EditorialApprovalError("approval load failed") from exc
        case_id = payload["gate_index"].get(decision_id)
        if case_id is None:
            return None
        return copy.deepcopy(payload["cases"][case_id])

    def health(self) -> dict:
        try:
            payload = self.store.load(self.default_payload())
        except (AtomicJsonStoreError, EditorialApprovalError) as exc:
            return {
                "status": "corrupt",
                "case_count": 0,
                "pending_count": 0,
                "details": [str(exc)],
            }
        return {
            "status": "recovered_from_backup" if self.store.recovered_from_backup else "healthy",
            "case_count": len(payload["cases"]),
            "pending_count": sum(case["state"] == "pending" for case in payload["cases"].values()),
            "details": [],
        }
