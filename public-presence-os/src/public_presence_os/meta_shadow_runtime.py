from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from .control import canonical_json
from .meta_live_runtime import MetaEventStore
from .pilot_growth_operations import (
    ManualActionPacket,
    ShadowObservation,
    ShadowRecommendation,
    load_policy,
    recommend_from_shadow_observation,
)


MODEL_VERSION = "PPOS_META_SHADOW_REAL_V1"
EVALUATION_FIELDS = (
    "relevance",
    "specificity",
    "usefulness",
    "voice",
    "repetition",
    "false_positive",
    "false_negative",
    "spam_risk",
    "conversation_value",
    "brand_fit",
    "rights_provenance",
    "factual_grounding",
)


class MetaShadowHold(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ShadowDecision:
    decision_id: str
    evidence_event_id: str
    platform: str
    action: str
    risk_class: str
    rationale: str
    state: str
    evidence_sha256: str
    external_write_allowed: bool = False
    social_api_call_allowed: bool = False
    kill_switch_required: bool = True


def _event_type(object_type: str, text: str) -> str:
    lowered = text.casefold()
    if any(term in lowered for term in ("spam", "crypto giveaway", "dm me", "click here")):
        return "ABUSE_SPAM"
    if "?" in text:
        return "QUESTION"
    if any(term in lowered for term in ("corect", "greșit", "gresit", "incorrect", "de fapt")):
        return "CORRECTION"
    if object_type in {"COMMENT", "REPLY"}:
        return "LOW_VALUE" if len(text.strip()) < 24 else "COUNTERPOINT"
    return "EXPERT_LEAD"


def _text(event: Mapping[str, Any]) -> str:
    normalized = event.get("normalized")
    if not isinstance(normalized, Mapping):
        return "Observed public event"
    for key in ("message", "text", "caption"):
        value = normalized.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Observed public event"


def _action(value: ShadowRecommendation | ManualActionPacket) -> tuple[str, str, str]:
    if isinstance(value, ManualActionPacket):
        return "MANUAL_ACTION_PACKET", "GREEN", value.state
    mapping = {
        "DRAFT_INBOUND_REPLY": "REPLY",
        "DRAFT_CORRECTION_RESPONSE": "REPLY",
        "DRAFT_RESPECTFUL_COUNTERPOINT": "REPLY",
        "ESCALATE_EXPERT_LEAD": "FOLLOW_UP",
        "REVIEW_MENTION": "COMMENT",
        "NO_ENGAGEMENT": "IGNORE",
    }
    action = mapping.get(value.recommendation_type, "MANUAL_ACTION_PACKET")
    risk = "GREEN" if action in {"IGNORE", "MANUAL_ACTION_PACKET"} else "AMBER"
    return action, risk, value.state


class MetaShadowStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta_shadow_decisions (
                    decision_id TEXT PRIMARY KEY,
                    evidence_event_id TEXT NOT NULL UNIQUE,
                    platform TEXT NOT NULL,
                    action TEXT NOT NULL,
                    risk_class TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    state TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    decision_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta_shadow_evaluations (
                    decision_id TEXT PRIMARY KEY,
                    evaluation_json TEXT NOT NULL,
                    FOREIGN KEY(decision_id) REFERENCES meta_shadow_decisions(decision_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def persist(self, decision: ShadowDecision) -> str:
        payload = canonical_json(asdict(decision))
        evaluation = canonical_json({field: "UNKNOWN" for field in EVALUATION_FIELDS})
        with self._connect() as connection:
            accepted = connection.execute(
                """INSERT OR IGNORE INTO meta_shadow_decisions
                (decision_id,evidence_event_id,platform,action,risk_class,rationale,state,evidence_sha256,decision_json)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    decision.decision_id,
                    decision.evidence_event_id,
                    decision.platform,
                    decision.action,
                    decision.risk_class,
                    decision.rationale,
                    decision.state,
                    decision.evidence_sha256,
                    payload,
                ),
            ).rowcount == 1
            if accepted:
                connection.execute(
                    "INSERT INTO meta_shadow_evaluations(decision_id,evaluation_json) VALUES(?,?)",
                    (decision.decision_id, evaluation),
                )
        return "ACCEPTED" if accepted else "DUPLICATE_NOOP"

    def evaluate(self, decision_id: str, ratings: Mapping[str, str]) -> None:
        if set(ratings) != set(EVALUATION_FIELDS):
            raise MetaShadowHold("HOLD_SHADOW_EVALUATION_FIELDS")
        allowed = {"PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"}
        if any(value not in allowed for value in ratings.values()):
            raise MetaShadowHold("HOLD_SHADOW_EVALUATION_VALUE")
        with self._connect() as connection:
            if connection.execute(
                "UPDATE meta_shadow_evaluations SET evaluation_json=? WHERE decision_id=?",
                (canonical_json(dict(ratings)), decision_id),
            ).rowcount != 1:
                raise MetaShadowHold("HOLD_SHADOW_DECISION_NOT_FOUND")

    def report(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT action,risk_class,evaluation_json FROM meta_shadow_decisions JOIN meta_shadow_evaluations USING(decision_id)"
            ).fetchall()
        actions = Counter(row[0] for row in rows)
        risks = Counter(row[1] for row in rows)
        evaluated = sum(
            1 for _, _, raw in rows
            if all(value != "UNKNOWN" for value in json.loads(raw).values())
        )
        return {
            "sample_size": len(rows),
            "evaluated_count": evaluated,
            "actions": dict(sorted(actions.items())),
            "risk_classes": dict(sorted(risks.items())),
            "target_sample_size": 100,
            "sample_target_met": len(rows) >= 100,
            "calibration_complete": len(rows) >= 100 and evaluated == len(rows),
            "external_write_count": 0,
            "live_authority": "NONE",
        }


def compile_shadow_decision(event: Mapping[str, Any], *, policy: Mapping[str, Any]) -> ShadowDecision:
    required = {"event_id", "platform", "object_type", "external_id", "normalized"}
    if not required.issubset(event):
        raise MetaShadowHold("HOLD_SHADOW_EVENT_SHAPE")
    text = _text(event)
    observation = ShadowObservation(
        observation_ref=str(event["event_id"]),
        platform=str(event["platform"]),
        event_type=_event_type(str(event["object_type"]), text),
        public_context=text,
        capability_state="PASS_OFFLINE_CONTRACT",
        source_mode="REAL_READ_ONLY_EVENT",
        metric_value=None,
    )
    recommendation = recommend_from_shadow_observation(policy, observation)
    action, risk, state = _action(recommendation)
    evidence_hash = sha256(canonical_json(event).encode("utf-8")).hexdigest()
    stable = {
        "model_version": MODEL_VERSION,
        "evidence_event_id": event["event_id"],
        "evidence_sha256": evidence_hash,
        "action": action,
        "risk_class": risk,
    }
    rationale = recommendation.state if isinstance(recommendation, ManualActionPacket) else recommendation.rationale
    return ShadowDecision(
        decision_id="msd_" + sha256(canonical_json(stable).encode("utf-8")).hexdigest()[:28],
        evidence_event_id=str(event["event_id"]),
        platform=str(event["platform"]),
        action=action,
        risk_class=risk,
        rationale=rationale,
        state=state,
        evidence_sha256=evidence_hash,
    )


def run_shadow(
    event_store: MetaEventStore,
    shadow_store: MetaShadowStore,
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    selected_policy = load_policy() if policy is None else policy
    accepted = duplicates = 0
    for event in event_store.events():
        result = shadow_store.persist(compile_shadow_decision(event, policy=selected_policy))
        if result == "ACCEPTED":
            accepted += 1
        else:
            duplicates += 1
    report = shadow_store.report()
    report.update({"accepted_this_run": accepted, "duplicates_this_run": duplicates})
    return report
