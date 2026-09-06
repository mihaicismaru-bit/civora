from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import sqlite3
from pathlib import Path

from .control import EXPECTED_ACTIVE, canonical_json
from .learning import LearningHold, ShadowLearningRecord, validate_learning_record

EXPERIMENT_MODEL_VERSION = "PPOS_LOCAL_CONTROL_EXPERIMENT_V1"
EXPERIMENT_ENGINE_VERSION = "ppos-local-control-experiment-v1.0.0"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
CONTROL_CHECKS = (
    "LEARNING_RECORD_HASH_BOUND",
    "NO_PERFORMANCE_EVIDENCE",
    "NO_CONTENT_VARIANTS",
    "ZERO_EXTERNAL_AUTHORITY",
)


class ExperimentError(ValueError):
    pass


class ExperimentHold(ExperimentError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LocalControlExperimentPlan:
    plan_id: str
    plan_hash: str
    model_version: str
    engine_version: str
    learning_record_id: str
    learning_record_hash: str
    snapshot_hash: str
    receipt_hash: str
    platform: str
    request_id: str
    created_at_utc: str
    source_learned_at_utc: str
    mode: str
    control_checks: tuple[str, ...]
    performance_evidence_state: str
    performance_hypothesis: str
    optimization_recommendation: str
    content_variant_count: int
    performance_metric: str | None
    audience_segment: str | None
    local_control_validation_ready: bool
    external_experiment_ready: bool
    aggregate_content_level_only: bool = True
    individual_profiling: bool = False
    demographic_dimensions: bool = False
    state: str = "LOCAL_CONTROL_EXPERIMENT_PLAN_ONLY"
    local_experiment_ledger_authority: bool = True
    local_control_plan_authority: bool = True
    performance_experiment_authority: bool = False
    content_mutation_authority: bool = False
    strategy_mutation_authority: bool = False
    network_authority: bool = False
    account_connection_authority: bool = False
    queue_authority: bool = False
    publish_authority: bool = False
    deploy_authority: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ExperimentEvent:
    event_id: str
    event_hash: str
    plan_id: str
    plan_hash: str
    learning_record_id: str
    learning_record_hash: str
    sequence: int
    event_type: str
    request_id: str
    event_at_utc: str
    outcome: str
    state: str = "LOCAL_EXPERIMENT_EVENT_ONLY"
    performance_experiment_authority: bool = False
    content_mutation_authority: bool = False
    strategy_mutation_authority: bool = False
    network_authority: bool = False
    account_connection_authority: bool = False
    queue_authority: bool = False
    publish_authority: bool = False
    deploy_authority: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _parse_iso(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ExperimentHold("HOLD_EXPERIMENT_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None:
        raise ExperimentHold("HOLD_EXPERIMENT_TIMESTAMP_INVALID")
    return dt.astimezone(timezone.utc)


def _iso(value: str) -> str:
    return _parse_iso(value).isoformat().replace("+00:00", "Z")


def _plan_from_json(payload: str) -> LocalControlExperimentPlan:
    data = json.loads(payload)
    data["control_checks"] = tuple(data["control_checks"])
    return LocalControlExperimentPlan(**data)


def _event_from_json(payload: str) -> ExperimentEvent:
    return ExperimentEvent(**json.loads(payload))


def validate_experiment_input(record: ShadowLearningRecord) -> None:
    if not isinstance(record, ShadowLearningRecord):
        raise ExperimentHold("HOLD_M11_LEARNING_RECORD_TYPE")
    try:
        validate_learning_record(record)
    except LearningHold as exc:
        raise ExperimentHold(f"HOLD_M11_LEARNING_RECORD_INVALID:{exc.reason}") from exc
    if record.platform not in EXPECTED_ACTIVE:
        raise ExperimentHold("HOLD_M11_PLATFORM_NOT_ACTIVE")
    if record.state != "LOCAL_SHADOW_LEARNING_RECORD_ONLY":
        raise ExperimentHold("HOLD_M11_LEARNING_STATE_INVALID")
    if not record.experiment_input_ready:
        raise ExperimentHold("HOLD_M11_EXPERIMENT_INPUT_NOT_READY")
    if record.experiment_scope != "LOCAL_CONTROL_VALIDATION_ONLY":
        raise ExperimentHold("HOLD_M11_EXPERIMENT_SCOPE_INVALID")
    if record.external_experiment_ready:
        raise ExperimentHold("HOLD_M11_FALSE_EXTERNAL_EXPERIMENT_READY")
    if record.performance_evidence_state != "UNAVAILABLE_NOT_CONNECTED":
        raise ExperimentHold("HOLD_M11_FALSE_PERFORMANCE_EVIDENCE")
    if record.performance_conclusion != "NO_PERFORMANCE_CONCLUSION":
        raise ExperimentHold("HOLD_M11_FALSE_PERFORMANCE_CONCLUSION")
    if record.optimization_recommendation != "NO_OPTIMIZATION_RECOMMENDATION":
        raise ExperimentHold("HOLD_M11_FALSE_OPTIMIZATION_RECOMMENDATION")
    if any((
        record.performance_learning_authority,
        record.strategy_mutation_authority,
        record.experiment_execution_authority,
        record.network_authority,
        record.account_connection_authority,
        record.publish_authority,
        record.deploy_authority,
    )):
        raise ExperimentHold("HOLD_M11_EXTERNAL_AUTHORITY")


def _plan_body(record: ShadowLearningRecord, request_id: str, created_at_utc: str) -> dict:
    learned = _parse_iso(record.learned_at_utc)
    created = _parse_iso(created_at_utc)
    if created < learned:
        raise ExperimentHold("HOLD_EXPERIMENT_BEFORE_LEARNING_RECORD")
    return {
        "schema_version": EXPERIMENT_MODEL_VERSION,
        "engine_version": EXPERIMENT_ENGINE_VERSION,
        "learning_record_id": record.record_id,
        "learning_record_hash": record.record_hash,
        "snapshot_hash": record.snapshot_hash,
        "receipt_hash": record.receipt_hash,
        "platform": record.platform,
        "request_id": request_id,
        "created_at_utc": created.isoformat().replace("+00:00", "Z"),
        "source_learned_at_utc": learned.isoformat().replace("+00:00", "Z"),
        "mode": "LOCAL_CONTROL_VALIDATION_ONLY",
        "control_checks": CONTROL_CHECKS,
        "performance_evidence_state": "UNAVAILABLE_NOT_CONNECTED",
        "performance_hypothesis": "NO_PERFORMANCE_HYPOTHESIS",
        "optimization_recommendation": "NO_OPTIMIZATION_RECOMMENDATION",
        "content_variant_count": 0,
        "performance_metric": None,
        "audience_segment": None,
        "local_control_validation_ready": True,
        "external_experiment_ready": False,
        "aggregate_content_level_only": True,
        "individual_profiling": False,
        "demographic_dimensions": False,
        "state": "LOCAL_CONTROL_EXPERIMENT_PLAN_ONLY",
        "local_experiment_ledger_authority": True,
        "local_control_plan_authority": True,
        "performance_experiment_authority": False,
        "content_mutation_authority": False,
        "strategy_mutation_authority": False,
        "network_authority": False,
        "account_connection_authority": False,
        "queue_authority": False,
        "publish_authority": False,
        "deploy_authority": False,
    }


def _plan_body_from_plan(plan: LocalControlExperimentPlan) -> dict:
    data = plan.to_dict()
    data.pop("plan_id")
    data.pop("plan_hash")
    data["schema_version"] = data.pop("model_version")
    return data


def validate_experiment_plan(plan: LocalControlExperimentPlan) -> None:
    if not isinstance(plan, LocalControlExperimentPlan):
        raise ExperimentHold("HOLD_EXPERIMENT_PLAN_TYPE")
    if (plan.model_version, plan.engine_version) != (EXPERIMENT_MODEL_VERSION, EXPERIMENT_ENGINE_VERSION):
        raise ExperimentHold("HOLD_EXPERIMENT_PLAN_VERSION")
    if plan.platform not in EXPECTED_ACTIVE:
        raise ExperimentHold("HOLD_EXPERIMENT_PLATFORM_NOT_ACTIVE")
    if plan.state != "LOCAL_CONTROL_EXPERIMENT_PLAN_ONLY":
        raise ExperimentHold("HOLD_EXPERIMENT_PLAN_STATE_INVALID")
    if plan.mode != "LOCAL_CONTROL_VALIDATION_ONLY":
        raise ExperimentHold("HOLD_EXPERIMENT_MODE_INVALID")
    if plan.control_checks != CONTROL_CHECKS:
        raise ExperimentHold("HOLD_EXPERIMENT_CONTROL_CHECKS_INVALID")
    if plan.performance_evidence_state != "UNAVAILABLE_NOT_CONNECTED":
        raise ExperimentHold("HOLD_EXPERIMENT_FALSE_PERFORMANCE_EVIDENCE")
    if plan.performance_hypothesis != "NO_PERFORMANCE_HYPOTHESIS":
        raise ExperimentHold("HOLD_EXPERIMENT_FALSE_PERFORMANCE_HYPOTHESIS")
    if plan.optimization_recommendation != "NO_OPTIMIZATION_RECOMMENDATION":
        raise ExperimentHold("HOLD_EXPERIMENT_FALSE_OPTIMIZATION_RECOMMENDATION")
    if plan.content_variant_count != 0 or plan.performance_metric is not None or plan.audience_segment is not None:
        raise ExperimentHold("HOLD_EXPERIMENT_VARIANT_OR_TARGETING_NOT_ALLOWED")
    if not plan.local_control_validation_ready or plan.external_experiment_ready:
        raise ExperimentHold("HOLD_EXPERIMENT_READINESS_INVALID")
    if not plan.aggregate_content_level_only or plan.individual_profiling or plan.demographic_dimensions:
        raise ExperimentHold("HOLD_EXPERIMENT_PRIVACY_SCOPE_INVALID")
    if not plan.local_experiment_ledger_authority or not plan.local_control_plan_authority:
        raise ExperimentHold("HOLD_EXPERIMENT_LOCAL_AUTHORITY_INVALID")
    if any((
        plan.performance_experiment_authority,
        plan.content_mutation_authority,
        plan.strategy_mutation_authority,
        plan.network_authority,
        plan.account_connection_authority,
        plan.queue_authority,
        plan.publish_authority,
        plan.deploy_authority,
    )):
        raise ExperimentHold("HOLD_EXPERIMENT_EXTERNAL_AUTHORITY")
    if _parse_iso(plan.created_at_utc) < _parse_iso(plan.source_learned_at_utc):
        raise ExperimentHold("HOLD_EXPERIMENT_TIMESTAMP_ORDER_INVALID")
    if not all(HEX64.fullmatch(value) for value in (plan.learning_record_hash, plan.snapshot_hash, plan.receipt_hash)):
        raise ExperimentHold("HOLD_EXPERIMENT_BINDING_INVALID")
    if not REQUEST_ID_RE.fullmatch(plan.request_id):
        raise ExperimentHold("HOLD_EXPERIMENT_REQUEST_ID_INVALID")
    expected_hash = _hash(_plan_body_from_plan(plan))
    if not HEX64.fullmatch(plan.plan_hash) or plan.plan_hash != expected_hash:
        raise ExperimentHold("HOLD_EXPERIMENT_PLAN_HASH_MISMATCH")
    if plan.plan_id != "exp_" + plan.plan_hash[:24]:
        raise ExperimentHold("HOLD_EXPERIMENT_PLAN_ID_MISMATCH")


def _event_body(plan: LocalControlExperimentPlan) -> dict:
    return {
        "schema_version": EXPERIMENT_MODEL_VERSION,
        "engine_version": EXPERIMENT_ENGINE_VERSION,
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "learning_record_id": plan.learning_record_id,
        "learning_record_hash": plan.learning_record_hash,
        "sequence": 1,
        "event_type": "LOCAL_CONTROL_EXPERIMENT_PLANNED",
        "request_id": plan.request_id,
        "event_at_utc": plan.created_at_utc,
        "outcome": "CONTROL_PLAN_RECORDED_NOT_EXTERNALLY_EXECUTED",
        "state": "LOCAL_EXPERIMENT_EVENT_ONLY",
        "performance_experiment_authority": False,
        "content_mutation_authority": False,
        "strategy_mutation_authority": False,
        "network_authority": False,
        "account_connection_authority": False,
        "queue_authority": False,
        "publish_authority": False,
        "deploy_authority": False,
    }


def validate_experiment_event(event: ExperimentEvent) -> None:
    if not isinstance(event, ExperimentEvent):
        raise ExperimentHold("HOLD_EXPERIMENT_EVENT_TYPE")
    if event.sequence != 1 or event.event_type != "LOCAL_CONTROL_EXPERIMENT_PLANNED":
        raise ExperimentHold("HOLD_EXPERIMENT_EVENT_STATE_INVALID")
    if event.outcome != "CONTROL_PLAN_RECORDED_NOT_EXTERNALLY_EXECUTED":
        raise ExperimentHold("HOLD_EXPERIMENT_EVENT_OUTCOME_INVALID")
    if any((
        event.performance_experiment_authority,
        event.content_mutation_authority,
        event.strategy_mutation_authority,
        event.network_authority,
        event.account_connection_authority,
        event.queue_authority,
        event.publish_authority,
        event.deploy_authority,
    )):
        raise ExperimentHold("HOLD_EXPERIMENT_EVENT_EXTERNAL_AUTHORITY")
    body = event.to_dict()
    body.pop("event_id")
    body.pop("event_hash")
    body["schema_version"] = EXPERIMENT_MODEL_VERSION
    body["engine_version"] = EXPERIMENT_ENGINE_VERSION
    expected_hash = _hash(body)
    if not HEX64.fullmatch(event.event_hash) or event.event_hash != expected_hash:
        raise ExperimentHold("HOLD_EXPERIMENT_EVENT_HASH_MISMATCH")
    if event.event_id != "eev_" + event.event_hash[:24]:
        raise ExperimentHold("HOLD_EXPERIMENT_EVENT_ID_MISMATCH")


class LocalControlExperimentLedger:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    @classmethod
    def memory(cls) -> "LocalControlExperimentLedger":
        return cls(sqlite3.connect(":memory:"))

    @classmethod
    def open(cls, path: str | Path) -> "LocalControlExperimentLedger":
        return cls(sqlite3.connect(str(path)))

    def close(self) -> None:
        self.connection.close()

    def _init_schema(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS experiment_learning_inputs (
                learning_record_hash TEXT PRIMARY KEY,
                learning_record_id TEXT NOT NULL UNIQUE,
                learning_record_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS experiment_plans (
                plan_hash TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL UNIQUE,
                learning_record_hash TEXT NOT NULL UNIQUE REFERENCES experiment_learning_inputs(learning_record_hash),
                request_id TEXT NOT NULL UNIQUE,
                created_at_utc TEXT NOT NULL,
                plan_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS experiment_events (
                event_hash TEXT PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                plan_hash TEXT NOT NULL REFERENCES experiment_plans(plan_hash),
                sequence INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                event_at_utc TEXT NOT NULL,
                event_json TEXT NOT NULL,
                UNIQUE(plan_hash, sequence)
            );
            CREATE TRIGGER IF NOT EXISTS experiment_learning_inputs_no_update BEFORE UPDATE ON experiment_learning_inputs BEGIN SELECT RAISE(ABORT, 'experiment_learning_inputs_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS experiment_learning_inputs_no_delete BEFORE DELETE ON experiment_learning_inputs BEGIN SELECT RAISE(ABORT, 'experiment_learning_inputs_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS experiment_plans_no_update BEFORE UPDATE ON experiment_plans BEGIN SELECT RAISE(ABORT, 'experiment_plans_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS experiment_plans_no_delete BEFORE DELETE ON experiment_plans BEGIN SELECT RAISE(ABORT, 'experiment_plans_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS experiment_events_no_update BEFORE UPDATE ON experiment_events BEGIN SELECT RAISE(ABORT, 'experiment_events_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS experiment_events_no_delete BEFORE DELETE ON experiment_events BEGIN SELECT RAISE(ABORT, 'experiment_events_append_only'); END;
        """)
        self.connection.commit()

    def _register_learning_record(self, record: ShadowLearningRecord) -> None:
        validate_experiment_input(record)
        payload = canonical_json(record.to_dict())
        row = self.connection.execute(
            "SELECT learning_record_json FROM experiment_learning_inputs WHERE learning_record_hash=?",
            (record.record_hash,),
        ).fetchone()
        if row is not None:
            if row["learning_record_json"] != payload:
                raise ExperimentHold("HOLD_M11_LEARNING_RECORD_HASH_COLLISION_OR_DRIFT")
            return
        if self.connection.execute(
            "SELECT 1 FROM experiment_learning_inputs WHERE learning_record_id=?",
            (record.record_id,),
        ).fetchone() is not None:
            raise ExperimentHold("HOLD_M11_LEARNING_RECORD_ID_REUSE_MISMATCH")
        self.connection.execute(
            "INSERT INTO experiment_learning_inputs(learning_record_hash,learning_record_id,learning_record_json) VALUES(?,?,?)",
            (record.record_hash, record.record_id, payload),
        )

    def create_plan(
        self,
        record: ShadowLearningRecord,
        *,
        request_id: str,
        created_at_utc: str,
    ) -> LocalControlExperimentPlan:
        validate_experiment_input(record)
        if not REQUEST_ID_RE.fullmatch(request_id):
            raise ExperimentHold("HOLD_EXPERIMENT_REQUEST_ID_INVALID")
        created_at = _iso(created_at_utc)
        body = _plan_body(record, request_id, created_at)
        digest = _hash(body)
        candidate = LocalControlExperimentPlan(
            plan_id="exp_" + digest[:24],
            plan_hash=digest,
            model_version=EXPERIMENT_MODEL_VERSION,
            engine_version=EXPERIMENT_ENGINE_VERSION,
            learning_record_id=record.record_id,
            learning_record_hash=record.record_hash,
            snapshot_hash=record.snapshot_hash,
            receipt_hash=record.receipt_hash,
            platform=record.platform,
            request_id=request_id,
            created_at_utc=body["created_at_utc"],
            source_learned_at_utc=body["source_learned_at_utc"],
            mode=body["mode"],
            control_checks=CONTROL_CHECKS,
            performance_evidence_state=body["performance_evidence_state"],
            performance_hypothesis=body["performance_hypothesis"],
            optimization_recommendation=body["optimization_recommendation"],
            content_variant_count=0,
            performance_metric=None,
            audience_segment=None,
            local_control_validation_ready=True,
            external_experiment_ready=False,
        )
        validate_experiment_plan(candidate)

        request_row = self.connection.execute(
            "SELECT plan_json FROM experiment_plans WHERE request_id=?", (request_id,)
        ).fetchone()
        if request_row is not None:
            existing = _plan_from_json(request_row["plan_json"])
            if existing == candidate:
                return existing
            raise ExperimentHold("HOLD_EXPERIMENT_REQUEST_ID_REUSE_MISMATCH")

        record_row = self.connection.execute(
            "SELECT plan_json FROM experiment_plans WHERE learning_record_hash=?",
            (record.record_hash,),
        ).fetchone()
        if record_row is not None:
            existing = _plan_from_json(record_row["plan_json"])
            if existing == candidate:
                return existing
            raise ExperimentHold("HOLD_M11_LEARNING_RECORD_ALREADY_PLANNED")

        event_body = _event_body(candidate)
        event_hash = _hash(event_body)
        event = ExperimentEvent(
            event_id="eev_" + event_hash[:24],
            event_hash=event_hash,
            plan_id=candidate.plan_id,
            plan_hash=candidate.plan_hash,
            learning_record_id=candidate.learning_record_id,
            learning_record_hash=candidate.learning_record_hash,
            sequence=1,
            event_type="LOCAL_CONTROL_EXPERIMENT_PLANNED",
            request_id=request_id,
            event_at_utc=candidate.created_at_utc,
            outcome="CONTROL_PLAN_RECORDED_NOT_EXTERNALLY_EXECUTED",
        )
        validate_experiment_event(event)

        with self.connection:
            self._register_learning_record(record)
            self.connection.execute(
                "INSERT INTO experiment_plans(plan_hash,plan_id,learning_record_hash,request_id,created_at_utc,plan_json) VALUES(?,?,?,?,?,?)",
                (
                    candidate.plan_hash,
                    candidate.plan_id,
                    candidate.learning_record_hash,
                    candidate.request_id,
                    candidate.created_at_utc,
                    canonical_json(candidate.to_dict()),
                ),
            )
            self.connection.execute(
                "INSERT INTO experiment_events(event_hash,event_id,plan_hash,sequence,event_type,event_at_utc,event_json) VALUES(?,?,?,?,?,?,?)",
                (
                    event.event_hash,
                    event.event_id,
                    event.plan_hash,
                    event.sequence,
                    event.event_type,
                    event.event_at_utc,
                    canonical_json(event.to_dict()),
                ),
            )
        return candidate

    def plans(self) -> tuple[LocalControlExperimentPlan, ...]:
        rows = self.connection.execute(
            "SELECT plan_json FROM experiment_plans ORDER BY created_at_utc, plan_id"
        ).fetchall()
        return tuple(_plan_from_json(row["plan_json"]) for row in rows)

    def events_for(self, plan: LocalControlExperimentPlan) -> tuple[ExperimentEvent, ...]:
        rows = self.connection.execute(
            "SELECT event_json FROM experiment_events WHERE plan_hash=? ORDER BY sequence",
            (plan.plan_hash,),
        ).fetchall()
        return tuple(_event_from_json(row["event_json"]) for row in rows)
