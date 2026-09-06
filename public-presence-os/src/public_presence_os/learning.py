from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import sqlite3
from pathlib import Path

from .analytics import AnalyticsHold, LocalAnalyticsSnapshot, validate_analytics_snapshot
from .control import EXPECTED_ACTIVE, canonical_json

LEARNING_MODEL_VERSION = "PPOS_LOCAL_SHADOW_LEARNING_V1"
LEARNING_ENGINE_VERSION = "ppos-local-shadow-learning-v1.0.0"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


class LearningError(ValueError):
    pass


class LearningHold(LearningError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ShadowLearningRecord:
    record_id: str
    record_hash: str
    model_version: str
    engine_version: str
    snapshot_id: str
    snapshot_hash: str
    receipt_id: str
    receipt_hash: str
    platform: str
    request_id: str
    learned_at_utc: str
    source_observed_at_utc: str
    local_receipt_age_seconds: int
    observation_scope: str
    observations: tuple[str, ...]
    performance_evidence_state: str
    performance_conclusion: str
    optimization_recommendation: str
    experiment_input_ready: bool
    experiment_scope: str
    external_experiment_ready: bool
    aggregate_content_level_only: bool = True
    individual_profiling: bool = False
    demographic_dimensions: bool = False
    state: str = "LOCAL_SHADOW_LEARNING_RECORD_ONLY"
    local_learning_authority: bool = True
    performance_learning_authority: bool = False
    strategy_mutation_authority: bool = False
    experiment_execution_authority: bool = False
    network_authority: bool = False
    account_connection_authority: bool = False
    publish_authority: bool = False
    deploy_authority: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LearningEvent:
    event_id: str
    event_hash: str
    record_id: str
    record_hash: str
    snapshot_id: str
    snapshot_hash: str
    sequence: int
    event_type: str
    request_id: str
    event_at_utc: str
    outcome: str
    performance_evidence_state: str
    state: str = "LOCAL_LEARNING_EVENT_ONLY"
    performance_learning_authority: bool = False
    strategy_mutation_authority: bool = False
    experiment_execution_authority: bool = False
    network_authority: bool = False
    account_connection_authority: bool = False
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
        raise LearningHold("HOLD_LEARNING_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None:
        raise LearningHold("HOLD_LEARNING_TIMESTAMP_INVALID")
    return dt.astimezone(timezone.utc)


def _iso(value: str) -> str:
    return _parse_iso(value).isoformat().replace("+00:00", "Z")


def _record_from_json(payload: str) -> ShadowLearningRecord:
    data = json.loads(payload)
    data["observations"] = tuple(data["observations"])
    return ShadowLearningRecord(**data)


def validate_learning_input(snapshot: LocalAnalyticsSnapshot) -> None:
    if not isinstance(snapshot, LocalAnalyticsSnapshot):
        raise LearningHold("HOLD_M10_SNAPSHOT_TYPE")
    try:
        validate_analytics_snapshot(snapshot)
    except AnalyticsHold as exc:
        raise LearningHold(f"HOLD_M10_SNAPSHOT_INVALID:{exc.reason}") from exc
    if snapshot.platform not in EXPECTED_ACTIVE:
        raise LearningHold("HOLD_M10_PLATFORM_NOT_ACTIVE")
    if snapshot.state != "LOCAL_ANALYTICS_SNAPSHOT_ONLY":
        raise LearningHold("HOLD_M10_SNAPSHOT_STATE_INVALID")
    if not snapshot.learning_input_ready:
        raise LearningHold("HOLD_M10_LEARNING_INPUT_NOT_READY")
    if snapshot.learning_scope != "LOCAL_OPERATIONAL_TELEMETRY_ONLY":
        raise LearningHold("HOLD_M10_LEARNING_SCOPE_INVALID")
    if snapshot.performance_evidence_ready:
        raise LearningHold("HOLD_M10_UNEXPECTED_PERFORMANCE_EVIDENCE")
    if snapshot.external_analytics_state != "NOT_CONNECTED":
        raise LearningHold("HOLD_M10_EXTERNAL_ANALYTICS_STATE_INVALID")
    if snapshot.derived_metrics_state != "NOT_COMPUTABLE_NOT_CONNECTED":
        raise LearningHold("HOLD_M10_DERIVED_METRICS_STATE_INVALID")


def _expected_observations(age_seconds: int) -> tuple[str, ...]:
    return (
        "LOCAL_DRY_RUN_RECEIPT_TELEMETRY_PRESENT",
        f"LOCAL_RECEIPT_AGE_SECONDS:{age_seconds}",
        "REMOTE_ANALYTICS_NOT_CONNECTED",
        "PERFORMANCE_EVIDENCE_UNAVAILABLE",
    )


def _record_body(snapshot: LocalAnalyticsSnapshot, request_id: str, learned_at_utc: str) -> dict:
    observed = _parse_iso(snapshot.observed_at_utc)
    learned = _parse_iso(learned_at_utc)
    if learned < observed:
        raise LearningHold("HOLD_LEARNING_BEFORE_ANALYTICS_OBSERVATION")
    return {
        "schema_version": LEARNING_MODEL_VERSION,
        "engine_version": LEARNING_ENGINE_VERSION,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_hash": snapshot.snapshot_hash,
        "receipt_id": snapshot.receipt_id,
        "receipt_hash": snapshot.receipt_hash,
        "platform": snapshot.platform,
        "request_id": request_id,
        "learned_at_utc": learned.isoformat().replace("+00:00", "Z"),
        "source_observed_at_utc": observed.isoformat().replace("+00:00", "Z"),
        "local_receipt_age_seconds": snapshot.local_receipt_age_seconds,
        "observation_scope": "LOCAL_OPERATIONAL_TELEMETRY_ONLY",
        "observations": _expected_observations(snapshot.local_receipt_age_seconds),
        "performance_evidence_state": "UNAVAILABLE_NOT_CONNECTED",
        "performance_conclusion": "NO_PERFORMANCE_CONCLUSION",
        "optimization_recommendation": "NO_OPTIMIZATION_RECOMMENDATION",
        "experiment_input_ready": True,
        "experiment_scope": "LOCAL_CONTROL_VALIDATION_ONLY",
        "external_experiment_ready": False,
        "aggregate_content_level_only": True,
        "individual_profiling": False,
        "demographic_dimensions": False,
        "state": "LOCAL_SHADOW_LEARNING_RECORD_ONLY",
        "local_learning_authority": True,
        "performance_learning_authority": False,
        "strategy_mutation_authority": False,
        "experiment_execution_authority": False,
        "network_authority": False,
        "account_connection_authority": False,
        "publish_authority": False,
        "deploy_authority": False,
    }


def _record_body_from_record(record: ShadowLearningRecord) -> dict:
    data = record.to_dict()
    data.pop("record_id")
    data.pop("record_hash")
    data["schema_version"] = data.pop("model_version")
    return data


def validate_learning_record(record: ShadowLearningRecord) -> None:
    if not isinstance(record, ShadowLearningRecord):
        raise LearningHold("HOLD_LEARNING_RECORD_TYPE")
    if (record.model_version, record.engine_version) != (LEARNING_MODEL_VERSION, LEARNING_ENGINE_VERSION):
        raise LearningHold("HOLD_LEARNING_RECORD_VERSION")
    if record.platform not in EXPECTED_ACTIVE:
        raise LearningHold("HOLD_LEARNING_PLATFORM_NOT_ACTIVE")
    if record.state != "LOCAL_SHADOW_LEARNING_RECORD_ONLY" or not record.local_learning_authority:
        raise LearningHold("HOLD_LEARNING_RECORD_STATE_INVALID")
    if record.observation_scope != "LOCAL_OPERATIONAL_TELEMETRY_ONLY":
        raise LearningHold("HOLD_LEARNING_OBSERVATION_SCOPE_INVALID")
    if record.observations != _expected_observations(record.local_receipt_age_seconds):
        raise LearningHold("HOLD_LEARNING_OBSERVATIONS_INVALID")
    if record.performance_evidence_state != "UNAVAILABLE_NOT_CONNECTED":
        raise LearningHold("HOLD_LEARNING_FALSE_PERFORMANCE_EVIDENCE")
    if record.performance_conclusion != "NO_PERFORMANCE_CONCLUSION":
        raise LearningHold("HOLD_LEARNING_FALSE_PERFORMANCE_CONCLUSION")
    if record.optimization_recommendation != "NO_OPTIMIZATION_RECOMMENDATION":
        raise LearningHold("HOLD_LEARNING_FALSE_OPTIMIZATION_RECOMMENDATION")
    if not record.experiment_input_ready or record.experiment_scope != "LOCAL_CONTROL_VALIDATION_ONLY":
        raise LearningHold("HOLD_LEARNING_EXPERIMENT_HANDOFF_INVALID")
    if record.external_experiment_ready:
        raise LearningHold("HOLD_LEARNING_FALSE_EXTERNAL_EXPERIMENT_READY")
    if not record.aggregate_content_level_only or record.individual_profiling or record.demographic_dimensions:
        raise LearningHold("HOLD_LEARNING_PRIVACY_SCOPE_INVALID")
    if record.local_receipt_age_seconds < 0:
        raise LearningHold("HOLD_LEARNING_RECEIPT_AGE_INVALID")
    if _parse_iso(record.learned_at_utc) < _parse_iso(record.source_observed_at_utc):
        raise LearningHold("HOLD_LEARNING_TIMESTAMP_ORDER_INVALID")
    if any((record.performance_learning_authority, record.strategy_mutation_authority,
            record.experiment_execution_authority, record.network_authority,
            record.account_connection_authority, record.publish_authority, record.deploy_authority)):
        raise LearningHold("HOLD_LEARNING_EXTERNAL_AUTHORITY")
    if not HEX64.fullmatch(record.snapshot_hash) or not HEX64.fullmatch(record.receipt_hash):
        raise LearningHold("HOLD_LEARNING_BINDING_INVALID")
    if not REQUEST_ID_RE.fullmatch(record.request_id):
        raise LearningHold("HOLD_LEARNING_REQUEST_ID_INVALID")
    expected_hash = _hash(_record_body_from_record(record))
    if not HEX64.fullmatch(record.record_hash) or record.record_hash != expected_hash:
        raise LearningHold("HOLD_LEARNING_RECORD_HASH_MISMATCH")
    if record.record_id != "lrn_" + record.record_hash[:24]:
        raise LearningHold("HOLD_LEARNING_RECORD_ID_MISMATCH")


def _event_body(record: ShadowLearningRecord) -> dict:
    return {
        "schema_version": LEARNING_MODEL_VERSION,
        "engine_version": LEARNING_ENGINE_VERSION,
        "record_id": record.record_id,
        "record_hash": record.record_hash,
        "snapshot_id": record.snapshot_id,
        "snapshot_hash": record.snapshot_hash,
        "sequence": 1,
        "event_type": "LOCAL_SHADOW_LEARNING_RECORDED",
        "request_id": record.request_id,
        "event_at_utc": record.learned_at_utc,
        "outcome": "NO_PERFORMANCE_CONCLUSION",
        "performance_evidence_state": "UNAVAILABLE_NOT_CONNECTED",
        "state": "LOCAL_LEARNING_EVENT_ONLY",
        "performance_learning_authority": False,
        "strategy_mutation_authority": False,
        "experiment_execution_authority": False,
        "network_authority": False,
        "account_connection_authority": False,
        "publish_authority": False,
        "deploy_authority": False,
    }


def validate_learning_event(event: LearningEvent) -> None:
    if not isinstance(event, LearningEvent):
        raise LearningHold("HOLD_LEARNING_EVENT_TYPE")
    if event.sequence != 1 or event.event_type != "LOCAL_SHADOW_LEARNING_RECORDED":
        raise LearningHold("HOLD_LEARNING_EVENT_STATE_INVALID")
    if event.outcome != "NO_PERFORMANCE_CONCLUSION" or event.performance_evidence_state != "UNAVAILABLE_NOT_CONNECTED":
        raise LearningHold("HOLD_LEARNING_EVENT_FALSE_PERFORMANCE_STATE")
    if any((event.performance_learning_authority, event.strategy_mutation_authority,
            event.experiment_execution_authority, event.network_authority,
            event.account_connection_authority, event.publish_authority, event.deploy_authority)):
        raise LearningHold("HOLD_LEARNING_EVENT_EXTERNAL_AUTHORITY")
    body = event.to_dict()
    body.pop("event_id")
    body.pop("event_hash")
    body["schema_version"] = LEARNING_MODEL_VERSION
    body["engine_version"] = LEARNING_ENGINE_VERSION
    expected_hash = _hash(body)
    if not HEX64.fullmatch(event.event_hash) or event.event_hash != expected_hash:
        raise LearningHold("HOLD_LEARNING_EVENT_HASH_MISMATCH")
    if event.event_id != "lev_" + event.event_hash[:24]:
        raise LearningHold("HOLD_LEARNING_EVENT_ID_MISMATCH")


class LocalShadowLearningStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    @classmethod
    def memory(cls) -> "LocalShadowLearningStore":
        return cls(sqlite3.connect(":memory:"))

    @classmethod
    def open(cls, path: str | Path) -> "LocalShadowLearningStore":
        return cls(sqlite3.connect(str(path)))

    def close(self) -> None:
        self.connection.close()

    def _init_schema(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS learning_analytics_inputs (
                snapshot_hash TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL UNIQUE, snapshot_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS learning_records (
                record_hash TEXT PRIMARY KEY, record_id TEXT NOT NULL UNIQUE,
                snapshot_hash TEXT NOT NULL UNIQUE REFERENCES learning_analytics_inputs(snapshot_hash),
                request_id TEXT NOT NULL UNIQUE, learned_at_utc TEXT NOT NULL, record_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS learning_events (
                event_hash TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
                record_hash TEXT NOT NULL REFERENCES learning_records(record_hash),
                sequence INTEGER NOT NULL, event_type TEXT NOT NULL, event_at_utc TEXT NOT NULL,
                event_json TEXT NOT NULL, UNIQUE(record_hash, sequence)
            );
            CREATE TRIGGER IF NOT EXISTS learning_analytics_inputs_no_update BEFORE UPDATE ON learning_analytics_inputs BEGIN SELECT RAISE(ABORT, 'learning_analytics_inputs_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS learning_analytics_inputs_no_delete BEFORE DELETE ON learning_analytics_inputs BEGIN SELECT RAISE(ABORT, 'learning_analytics_inputs_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS learning_records_no_update BEFORE UPDATE ON learning_records BEGIN SELECT RAISE(ABORT, 'learning_records_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS learning_records_no_delete BEFORE DELETE ON learning_records BEGIN SELECT RAISE(ABORT, 'learning_records_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS learning_events_no_update BEFORE UPDATE ON learning_events BEGIN SELECT RAISE(ABORT, 'learning_events_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS learning_events_no_delete BEFORE DELETE ON learning_events BEGIN SELECT RAISE(ABORT, 'learning_events_append_only'); END;
        """)
        self.connection.commit()

    def register_snapshot(self, snapshot: LocalAnalyticsSnapshot) -> None:
        validate_learning_input(snapshot)
        payload = canonical_json(snapshot.to_dict())
        row = self.connection.execute(
            "SELECT snapshot_json FROM learning_analytics_inputs WHERE snapshot_hash=?", (snapshot.snapshot_hash,)
        ).fetchone()
        if row is not None:
            if row["snapshot_json"] != payload:
                raise LearningHold("HOLD_M10_SNAPSHOT_HASH_COLLISION_OR_DRIFT")
            return
        if self.connection.execute(
            "SELECT 1 FROM learning_analytics_inputs WHERE snapshot_id=?", (snapshot.snapshot_id,)
        ).fetchone() is not None:
            raise LearningHold("HOLD_M10_SNAPSHOT_ID_REUSE_MISMATCH")
        self.connection.execute(
            "INSERT INTO learning_analytics_inputs(snapshot_hash,snapshot_id,snapshot_json) VALUES(?,?,?)",
            (snapshot.snapshot_hash, snapshot.snapshot_id, payload),
        )

    def create_record(self, snapshot: LocalAnalyticsSnapshot, *, request_id: str, learned_at_utc: str) -> ShadowLearningRecord:
        validate_learning_input(snapshot)
        if not REQUEST_ID_RE.fullmatch(request_id):
            raise LearningHold("HOLD_LEARNING_REQUEST_ID_INVALID")
        learned_at = _iso(learned_at_utc)
        body = _record_body(snapshot, request_id, learned_at)
        digest = _hash(body)
        candidate = ShadowLearningRecord(
            record_id="lrn_" + digest[:24], record_hash=digest,
            model_version=LEARNING_MODEL_VERSION, engine_version=LEARNING_ENGINE_VERSION,
            **{k: v for k, v in body.items() if k not in {"schema_version", "engine_version"}},
        )
        validate_learning_record(candidate)

        row = self.connection.execute("SELECT record_json FROM learning_records WHERE request_id=?", (request_id,)).fetchone()
        if row is not None:
            existing = _record_from_json(row["record_json"])
            if existing == candidate:
                return existing
            raise LearningHold("HOLD_LEARNING_REQUEST_ID_REUSE_MISMATCH")
        row = self.connection.execute("SELECT record_json FROM learning_records WHERE snapshot_hash=?", (snapshot.snapshot_hash,)).fetchone()
        if row is not None:
            existing = _record_from_json(row["record_json"])
            if existing == candidate:
                return existing
            raise LearningHold("HOLD_M10_SNAPSHOT_ALREADY_LEARNED")

        event_body = _event_body(candidate)
        event_digest = _hash(event_body)
        event = LearningEvent(
            event_id="lev_" + event_digest[:24], event_hash=event_digest,
            **{k: v for k, v in event_body.items() if k not in {"schema_version", "engine_version"}},
        )
        validate_learning_event(event)
        try:
            self.connection.execute("BEGIN")
            self.register_snapshot(snapshot)
            self.connection.execute(
                "INSERT INTO learning_records(record_hash,record_id,snapshot_hash,request_id,learned_at_utc,record_json) VALUES(?,?,?,?,?,?)",
                (candidate.record_hash, candidate.record_id, candidate.snapshot_hash, candidate.request_id,
                 candidate.learned_at_utc, canonical_json(candidate.to_dict())),
            )
            self.connection.execute(
                "INSERT INTO learning_events(event_hash,event_id,record_hash,sequence,event_type,event_at_utc,event_json) VALUES(?,?,?,?,?,?,?)",
                (event.event_hash, event.event_id, candidate.record_hash, event.sequence, event.event_type,
                 event.event_at_utc, canonical_json(event.to_dict())),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return candidate

    def records(self) -> tuple[ShadowLearningRecord, ...]:
        rows = self.connection.execute("SELECT record_json FROM learning_records ORDER BY rowid").fetchall()
        return tuple(_record_from_json(row["record_json"]) for row in rows)

    def events_for(self, record: ShadowLearningRecord) -> tuple[LearningEvent, ...]:
        validate_learning_record(record)
        rows = self.connection.execute(
            "SELECT event_json FROM learning_events WHERE record_hash=? ORDER BY sequence", (record.record_hash,)
        ).fetchall()
        return tuple(LearningEvent(**json.loads(row["event_json"])) for row in rows)
