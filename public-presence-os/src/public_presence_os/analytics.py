from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import sqlite3
from pathlib import Path

from .control import EXPECTED_ACTIVE, canonical_json
from .publisher import DryRunPublishReceipt, PublisherHold, validate_publish_receipt

ANALYTICS_MODEL_VERSION = "PPOS_LOCAL_RECEIPT_TELEMETRY_V1"
ANALYTICS_ENGINE_VERSION = "ppos-local-receipt-telemetry-v1.0.0"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")

REMOTE_METRICS = (
    "VIEWS",
    "REACH",
    "IMPRESSIONS",
    "LIKES",
    "REACTIONS",
    "COMMENTS",
    "REPLIES",
    "SHARES",
    "REPOSTS",
    "QUOTES",
    "SAVES",
    "CLICKS",
    "CONVERSIONS",
)


class AnalyticsError(ValueError):
    pass


class AnalyticsHold(AnalyticsError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LocalAnalyticsSnapshot:
    snapshot_id: str
    snapshot_hash: str
    model_version: str
    engine_version: str
    receipt_id: str
    receipt_hash: str
    outbox_item_id: str
    outbox_item_hash: str
    platform: str
    mode: str
    request_id: str
    observed_at_utc: str
    publisher_attempted_at_utc: str
    local_receipt_age_seconds: int
    publisher_state: str
    execution_mode: str
    external_analytics_state: str
    external_metrics: dict[str, dict[str, object]]
    derived_metrics_state: str
    performance_evidence_ready: bool
    learning_input_ready: bool
    learning_scope: str
    aggregate_content_level_only: bool = True
    individual_profiling: bool = False
    demographic_dimensions: bool = False
    state: str = "LOCAL_ANALYTICS_SNAPSHOT_ONLY"
    local_analytics_authority: bool = True
    external_analytics_authority: bool = False
    learning_write_authority: bool = False
    strategy_mutation_authority: bool = False
    network_authority: bool = False
    account_connection_authority: bool = False
    publish_authority: bool = False
    deploy_authority: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AnalyticsEvent:
    event_id: str
    event_hash: str
    snapshot_id: str
    snapshot_hash: str
    receipt_id: str
    receipt_hash: str
    sequence: int
    event_type: str
    request_id: str
    event_at_utc: str
    outcome: str
    external_analytics_state: str
    state: str = "LOCAL_ANALYTICS_EVENT_ONLY"
    external_analytics_authority: bool = False
    learning_write_authority: bool = False
    strategy_mutation_authority: bool = False
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
        raise AnalyticsHold("HOLD_ANALYTICS_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None:
        raise AnalyticsHold("HOLD_ANALYTICS_TIMESTAMP_INVALID")
    return dt.astimezone(timezone.utc)


def _iso(value: str) -> str:
    return _parse_iso(value).isoformat().replace("+00:00", "Z")


def validate_analytics_input(receipt: DryRunPublishReceipt) -> None:
    if not isinstance(receipt, DryRunPublishReceipt):
        raise AnalyticsHold("HOLD_M09_RECEIPT_TYPE")
    try:
        validate_publish_receipt(receipt)
    except PublisherHold as exc:
        raise AnalyticsHold(f"HOLD_M09_RECEIPT_INVALID:{exc.reason}") from exc
    if receipt.platform not in EXPECTED_ACTIVE:
        raise AnalyticsHold("HOLD_M09_PLATFORM_NOT_ACTIVE")
    if receipt.state != "LOCAL_DRY_RUN_PUBLISH_RECEIPT_ONLY":
        raise AnalyticsHold("HOLD_M09_RECEIPT_STATE_INVALID")
    if receipt.publisher_state != "DRY_RUN_RECORDED" or receipt.execution_mode != "LOCAL_DRY_RUN":
        raise AnalyticsHold("HOLD_M09_RECEIPT_MODE_INVALID")
    if not receipt.analytics_input_ready:
        raise AnalyticsHold("HOLD_M09_ANALYTICS_INPUT_NOT_READY")
    if any((receipt.network_attempted, receipt.external_write_performed, receipt.account_connected, receipt.delivered)):
        raise AnalyticsHold("HOLD_M09_FALSE_EXTERNAL_STATE")
    if receipt.external_post_id is not None:
        raise AnalyticsHold("HOLD_M09_EXTERNAL_POST_ID_FORBIDDEN")


def _not_connected_metrics() -> dict[str, dict[str, object]]:
    return {
        metric: {
            "availability": "NOT_CONNECTED",
            "value": None,
            "source_metric_name": None,
        }
        for metric in REMOTE_METRICS
    }


def _snapshot_body(receipt: DryRunPublishReceipt, request_id: str, observed_at_utc: str) -> dict:
    attempted = _parse_iso(receipt.attempted_at_utc)
    observed = _parse_iso(observed_at_utc)
    if observed < attempted:
        raise AnalyticsHold("HOLD_ANALYTICS_OBSERVED_BEFORE_PUBLISHER_ATTEMPT")
    age_seconds = int((observed - attempted).total_seconds())
    return {
        "schema_version": ANALYTICS_MODEL_VERSION,
        "engine_version": ANALYTICS_ENGINE_VERSION,
        "receipt_id": receipt.receipt_id,
        "receipt_hash": receipt.receipt_hash,
        "outbox_item_id": receipt.outbox_item_id,
        "outbox_item_hash": receipt.outbox_item_hash,
        "platform": receipt.platform,
        "mode": receipt.mode,
        "request_id": request_id,
        "observed_at_utc": observed.isoformat().replace("+00:00", "Z"),
        "publisher_attempted_at_utc": attempted.isoformat().replace("+00:00", "Z"),
        "local_receipt_age_seconds": age_seconds,
        "publisher_state": receipt.publisher_state,
        "execution_mode": receipt.execution_mode,
        "external_analytics_state": "NOT_CONNECTED",
        "external_metrics": _not_connected_metrics(),
        "derived_metrics_state": "NOT_COMPUTABLE_NOT_CONNECTED",
        "performance_evidence_ready": False,
        "learning_input_ready": True,
        "learning_scope": "LOCAL_OPERATIONAL_TELEMETRY_ONLY",
        "aggregate_content_level_only": True,
        "individual_profiling": False,
        "demographic_dimensions": False,
        "state": "LOCAL_ANALYTICS_SNAPSHOT_ONLY",
        "local_analytics_authority": True,
        "external_analytics_authority": False,
        "learning_write_authority": False,
        "strategy_mutation_authority": False,
        "network_authority": False,
        "account_connection_authority": False,
        "publish_authority": False,
        "deploy_authority": False,
    }


def _snapshot_body_from_snapshot(snapshot: LocalAnalyticsSnapshot) -> dict:
    data = snapshot.to_dict()
    data.pop("snapshot_id")
    data.pop("snapshot_hash")
    data["schema_version"] = data.pop("model_version")
    return data


def validate_analytics_snapshot(snapshot: LocalAnalyticsSnapshot) -> None:
    if not isinstance(snapshot, LocalAnalyticsSnapshot):
        raise AnalyticsHold("HOLD_ANALYTICS_SNAPSHOT_TYPE")
    if snapshot.model_version != ANALYTICS_MODEL_VERSION or snapshot.engine_version != ANALYTICS_ENGINE_VERSION:
        raise AnalyticsHold("HOLD_ANALYTICS_SNAPSHOT_VERSION")
    if snapshot.platform not in EXPECTED_ACTIVE:
        raise AnalyticsHold("HOLD_ANALYTICS_PLATFORM_NOT_ACTIVE")
    if snapshot.state != "LOCAL_ANALYTICS_SNAPSHOT_ONLY" or not snapshot.local_analytics_authority:
        raise AnalyticsHold("HOLD_ANALYTICS_SNAPSHOT_STATE_INVALID")
    if snapshot.publisher_state != "DRY_RUN_RECORDED" or snapshot.execution_mode != "LOCAL_DRY_RUN":
        raise AnalyticsHold("HOLD_ANALYTICS_PUBLISHER_BINDING_INVALID")
    if snapshot.external_analytics_state != "NOT_CONNECTED":
        raise AnalyticsHold("HOLD_ANALYTICS_FALSE_EXTERNAL_STATE")
    if snapshot.derived_metrics_state != "NOT_COMPUTABLE_NOT_CONNECTED":
        raise AnalyticsHold("HOLD_ANALYTICS_DERIVED_STATE_INVALID")
    if snapshot.performance_evidence_ready:
        raise AnalyticsHold("HOLD_ANALYTICS_FALSE_PERFORMANCE_EVIDENCE")
    if not snapshot.learning_input_ready or snapshot.learning_scope != "LOCAL_OPERATIONAL_TELEMETRY_ONLY":
        raise AnalyticsHold("HOLD_ANALYTICS_LEARNING_SCOPE_INVALID")
    if not snapshot.aggregate_content_level_only or snapshot.individual_profiling or snapshot.demographic_dimensions:
        raise AnalyticsHold("HOLD_ANALYTICS_PRIVACY_SCOPE_INVALID")
    if snapshot.local_receipt_age_seconds < 0:
        raise AnalyticsHold("HOLD_ANALYTICS_RECEIPT_AGE_INVALID")
    attempted = _parse_iso(snapshot.publisher_attempted_at_utc)
    observed = _parse_iso(snapshot.observed_at_utc)
    if int((observed - attempted).total_seconds()) != snapshot.local_receipt_age_seconds:
        raise AnalyticsHold("HOLD_ANALYTICS_RECEIPT_AGE_MISMATCH")
    if set(snapshot.external_metrics) != set(REMOTE_METRICS):
        raise AnalyticsHold("HOLD_ANALYTICS_REMOTE_METRIC_SET_INVALID")
    for metric in REMOTE_METRICS:
        evidence = snapshot.external_metrics[metric]
        if set(evidence) != {"availability", "value", "source_metric_name"}:
            raise AnalyticsHold("HOLD_ANALYTICS_REMOTE_METRIC_SCHEMA_INVALID")
        if evidence["availability"] != "NOT_CONNECTED" or evidence["value"] is not None or evidence["source_metric_name"] is not None:
            raise AnalyticsHold("HOLD_ANALYTICS_REMOTE_METRIC_FALSE_VALUE")
    if any((
        snapshot.external_analytics_authority,
        snapshot.learning_write_authority,
        snapshot.strategy_mutation_authority,
        snapshot.network_authority,
        snapshot.account_connection_authority,
        snapshot.publish_authority,
        snapshot.deploy_authority,
    )):
        raise AnalyticsHold("HOLD_ANALYTICS_EXTERNAL_AUTHORITY")
    if not HEX64.fullmatch(snapshot.receipt_hash) or not HEX64.fullmatch(snapshot.outbox_item_hash):
        raise AnalyticsHold("HOLD_ANALYTICS_BINDING_INVALID")
    if not REQUEST_ID_RE.fullmatch(snapshot.request_id):
        raise AnalyticsHold("HOLD_ANALYTICS_REQUEST_ID_INVALID")
    expected_hash = _hash(_snapshot_body_from_snapshot(snapshot))
    if not HEX64.fullmatch(snapshot.snapshot_hash) or snapshot.snapshot_hash != expected_hash:
        raise AnalyticsHold("HOLD_ANALYTICS_SNAPSHOT_HASH_MISMATCH")
    if snapshot.snapshot_id != "ans_" + snapshot.snapshot_hash[:24]:
        raise AnalyticsHold("HOLD_ANALYTICS_SNAPSHOT_ID_MISMATCH")


def _event_body(snapshot: LocalAnalyticsSnapshot) -> dict:
    return {
        "schema_version": ANALYTICS_MODEL_VERSION,
        "engine_version": ANALYTICS_ENGINE_VERSION,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_hash": snapshot.snapshot_hash,
        "receipt_id": snapshot.receipt_id,
        "receipt_hash": snapshot.receipt_hash,
        "sequence": 1,
        "event_type": "LOCAL_RECEIPT_TELEMETRY_RECORDED",
        "request_id": snapshot.request_id,
        "event_at_utc": snapshot.observed_at_utc,
        "outcome": "REMOTE_ANALYTICS_NOT_CONNECTED",
        "external_analytics_state": "NOT_CONNECTED",
        "state": "LOCAL_ANALYTICS_EVENT_ONLY",
        "external_analytics_authority": False,
        "learning_write_authority": False,
        "strategy_mutation_authority": False,
        "network_authority": False,
        "account_connection_authority": False,
        "publish_authority": False,
        "deploy_authority": False,
    }


def validate_analytics_event(event: AnalyticsEvent) -> None:
    if not isinstance(event, AnalyticsEvent):
        raise AnalyticsHold("HOLD_ANALYTICS_EVENT_TYPE")
    if event.sequence != 1 or event.event_type != "LOCAL_RECEIPT_TELEMETRY_RECORDED":
        raise AnalyticsHold("HOLD_ANALYTICS_EVENT_STATE_INVALID")
    if event.outcome != "REMOTE_ANALYTICS_NOT_CONNECTED" or event.external_analytics_state != "NOT_CONNECTED":
        raise AnalyticsHold("HOLD_ANALYTICS_EVENT_FALSE_EXTERNAL_STATE")
    if any((
        event.external_analytics_authority,
        event.learning_write_authority,
        event.strategy_mutation_authority,
        event.network_authority,
        event.account_connection_authority,
        event.publish_authority,
        event.deploy_authority,
    )):
        raise AnalyticsHold("HOLD_ANALYTICS_EVENT_EXTERNAL_AUTHORITY")
    body = event.to_dict()
    body.pop("event_id")
    body.pop("event_hash")
    body["schema_version"] = ANALYTICS_MODEL_VERSION
    body["engine_version"] = ANALYTICS_ENGINE_VERSION
    expected_hash = _hash(body)
    if not HEX64.fullmatch(event.event_hash) or event.event_hash != expected_hash:
        raise AnalyticsHold("HOLD_ANALYTICS_EVENT_HASH_MISMATCH")
    if event.event_id != "aev_" + event.event_hash[:24]:
        raise AnalyticsHold("HOLD_ANALYTICS_EVENT_ID_MISMATCH")


class LocalReceiptAnalyticsStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    @classmethod
    def memory(cls) -> "LocalReceiptAnalyticsStore":
        return cls(sqlite3.connect(":memory:"))

    @classmethod
    def open(cls, path: str | Path) -> "LocalReceiptAnalyticsStore":
        return cls(sqlite3.connect(str(path)))

    def close(self) -> None:
        self.connection.close()

    def _init_schema(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS analytics_receipt_inputs (
                receipt_hash TEXT PRIMARY KEY, receipt_id TEXT NOT NULL UNIQUE,
                receipt_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analytics_snapshots (
                snapshot_hash TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL UNIQUE,
                receipt_hash TEXT NOT NULL UNIQUE REFERENCES analytics_receipt_inputs(receipt_hash),
                request_id TEXT NOT NULL UNIQUE, observed_at_utc TEXT NOT NULL,
                snapshot_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analytics_events (
                event_hash TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
                snapshot_hash TEXT NOT NULL REFERENCES analytics_snapshots(snapshot_hash),
                sequence INTEGER NOT NULL, event_type TEXT NOT NULL,
                event_at_utc TEXT NOT NULL, event_json TEXT NOT NULL,
                UNIQUE(snapshot_hash, sequence)
            );
            CREATE TRIGGER IF NOT EXISTS analytics_receipt_inputs_no_update BEFORE UPDATE ON analytics_receipt_inputs BEGIN SELECT RAISE(ABORT, 'analytics_receipt_inputs_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS analytics_receipt_inputs_no_delete BEFORE DELETE ON analytics_receipt_inputs BEGIN SELECT RAISE(ABORT, 'analytics_receipt_inputs_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS analytics_snapshots_no_update BEFORE UPDATE ON analytics_snapshots BEGIN SELECT RAISE(ABORT, 'analytics_snapshots_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS analytics_snapshots_no_delete BEFORE DELETE ON analytics_snapshots BEGIN SELECT RAISE(ABORT, 'analytics_snapshots_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS analytics_events_no_update BEFORE UPDATE ON analytics_events BEGIN SELECT RAISE(ABORT, 'analytics_events_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS analytics_events_no_delete BEFORE DELETE ON analytics_events BEGIN SELECT RAISE(ABORT, 'analytics_events_append_only'); END;
        """)
        self.connection.commit()

    def register_receipt(self, receipt: DryRunPublishReceipt) -> None:
        validate_analytics_input(receipt)
        payload = canonical_json(receipt.to_dict())
        row = self.connection.execute(
            "SELECT receipt_json FROM analytics_receipt_inputs WHERE receipt_hash=?",
            (receipt.receipt_hash,),
        ).fetchone()
        if row is not None:
            if row["receipt_json"] != payload:
                raise AnalyticsHold("HOLD_M09_RECEIPT_HASH_COLLISION_OR_DRIFT")
            return
        self.connection.execute(
            "INSERT INTO analytics_receipt_inputs(receipt_hash,receipt_id,receipt_json) VALUES(?,?,?)",
            (receipt.receipt_hash, receipt.receipt_id, payload),
        )
        self.connection.commit()

    def ingest_receipt(
        self,
        receipt: DryRunPublishReceipt,
        *,
        request_id: str,
        observed_at_utc: str,
    ) -> LocalAnalyticsSnapshot:
        validate_analytics_input(receipt)
        if not REQUEST_ID_RE.fullmatch(str(request_id)):
            raise AnalyticsHold("HOLD_ANALYTICS_REQUEST_ID_INVALID")
        clean_time = _iso(observed_at_utc)
        self.register_receipt(receipt)

        row = self.connection.execute(
            "SELECT snapshot_json FROM analytics_snapshots WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if row is not None:
            snapshot = LocalAnalyticsSnapshot(**json.loads(row["snapshot_json"]))
            if snapshot.receipt_hash != receipt.receipt_hash or snapshot.observed_at_utc != clean_time:
                raise AnalyticsHold("HOLD_ANALYTICS_REQUEST_ID_REUSE_MISMATCH")
            validate_analytics_snapshot(snapshot)
            return snapshot

        row = self.connection.execute(
            "SELECT snapshot_json FROM analytics_snapshots WHERE receipt_hash=?",
            (receipt.receipt_hash,),
        ).fetchone()
        if row is not None:
            raise AnalyticsHold("HOLD_M09_RECEIPT_ALREADY_INGESTED")

        body = _snapshot_body(receipt, request_id, clean_time)
        snapshot_hash = _hash(body)
        snapshot = LocalAnalyticsSnapshot(
            snapshot_id="ans_" + snapshot_hash[:24],
            snapshot_hash=snapshot_hash,
            model_version=ANALYTICS_MODEL_VERSION,
            engine_version=ANALYTICS_ENGINE_VERSION,
            receipt_id=receipt.receipt_id,
            receipt_hash=receipt.receipt_hash,
            outbox_item_id=receipt.outbox_item_id,
            outbox_item_hash=receipt.outbox_item_hash,
            platform=receipt.platform,
            mode=receipt.mode,
            request_id=request_id,
            observed_at_utc=body["observed_at_utc"],
            publisher_attempted_at_utc=body["publisher_attempted_at_utc"],
            local_receipt_age_seconds=body["local_receipt_age_seconds"],
            publisher_state=receipt.publisher_state,
            execution_mode=receipt.execution_mode,
            external_analytics_state="NOT_CONNECTED",
            external_metrics=_not_connected_metrics(),
            derived_metrics_state="NOT_COMPUTABLE_NOT_CONNECTED",
            performance_evidence_ready=False,
            learning_input_ready=True,
            learning_scope="LOCAL_OPERATIONAL_TELEMETRY_ONLY",
        )
        validate_analytics_snapshot(snapshot)

        event_body = _event_body(snapshot)
        event_hash = _hash(event_body)
        event = AnalyticsEvent(
            event_id="aev_" + event_hash[:24],
            event_hash=event_hash,
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            receipt_id=snapshot.receipt_id,
            receipt_hash=snapshot.receipt_hash,
            sequence=1,
            event_type="LOCAL_RECEIPT_TELEMETRY_RECORDED",
            request_id=snapshot.request_id,
            event_at_utc=snapshot.observed_at_utc,
            outcome="REMOTE_ANALYTICS_NOT_CONNECTED",
            external_analytics_state="NOT_CONNECTED",
        )
        validate_analytics_event(event)

        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO analytics_snapshots(snapshot_hash,snapshot_id,receipt_hash,request_id,observed_at_utc,snapshot_json) VALUES(?,?,?,?,?,?)",
                    (
                        snapshot.snapshot_hash,
                        snapshot.snapshot_id,
                        snapshot.receipt_hash,
                        snapshot.request_id,
                        snapshot.observed_at_utc,
                        canonical_json(snapshot.to_dict()),
                    ),
                )
                self.connection.execute(
                    "INSERT INTO analytics_events(event_hash,event_id,snapshot_hash,sequence,event_type,event_at_utc,event_json) VALUES(?,?,?,?,?,?,?)",
                    (
                        event.event_hash,
                        event.event_id,
                        snapshot.snapshot_hash,
                        event.sequence,
                        event.event_type,
                        event.event_at_utc,
                        canonical_json(event.to_dict()),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise AnalyticsHold("HOLD_ANALYTICS_APPEND_CONFLICT") from exc
        return snapshot

    def snapshots(self) -> tuple[LocalAnalyticsSnapshot, ...]:
        rows = self.connection.execute(
            "SELECT snapshot_json FROM analytics_snapshots ORDER BY observed_at_utc,snapshot_hash"
        ).fetchall()
        snapshots = tuple(LocalAnalyticsSnapshot(**json.loads(row["snapshot_json"])) for row in rows)
        for snapshot in snapshots:
            validate_analytics_snapshot(snapshot)
        return snapshots

    def events_for(self, snapshot: LocalAnalyticsSnapshot) -> tuple[AnalyticsEvent, ...]:
        validate_analytics_snapshot(snapshot)
        rows = self.connection.execute(
            "SELECT event_json FROM analytics_events WHERE snapshot_hash=? ORDER BY sequence",
            (snapshot.snapshot_hash,),
        ).fetchall()
        events = tuple(AnalyticsEvent(**json.loads(row["event_json"])) for row in rows)
        for event in events:
            validate_analytics_event(event)
        return events
