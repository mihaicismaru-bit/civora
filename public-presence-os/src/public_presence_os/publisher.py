from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import sqlite3
from pathlib import Path

from .control import EXPECTED_ACTIVE, canonical_json
from .queue import LocalOutboxItem, QueueHold, validate_outbox_item

PUBLISHER_MODEL_VERSION = "PPOS_LOCAL_DRY_RUN_PUBLISHER_V1"
PUBLISHER_ENGINE_VERSION = "ppos-local-dry-run-publisher-v1.0.0"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


class PublisherError(ValueError):
    pass


class PublisherHold(PublisherError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DryRunPublishReceipt:
    receipt_id: str
    receipt_hash: str
    model_version: str
    engine_version: str
    outbox_item_id: str
    outbox_item_hash: str
    approval_receipt_hash: str
    report_hash: str
    asset_id: str
    platform: str
    mode: str
    request_id: str
    attempted_at_utc: str
    execution_mode: str
    publisher_state: str
    analytics_input_ready: bool
    network_attempted: bool = False
    external_write_performed: bool = False
    account_connected: bool = False
    delivered: bool = False
    external_post_id: str | None = None
    state: str = "LOCAL_DRY_RUN_PUBLISH_RECEIPT_ONLY"
    local_dry_run_publisher_authority: bool = True
    external_publisher_authority: bool = False
    publish_authority: bool = False
    network_authority: bool = False
    account_connection_authority: bool = False
    deploy_authority: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PublishAttemptEvent:
    event_id: str
    event_hash: str
    receipt_id: str
    receipt_hash: str
    outbox_item_id: str
    outbox_item_hash: str
    sequence: int
    event_type: str
    request_id: str
    event_at_utc: str
    outcome: str
    network_attempted: bool = False
    external_write_performed: bool = False
    delivered: bool = False
    external_post_id: str | None = None
    state: str = "LOCAL_PUBLISH_ATTEMPT_EVENT_ONLY"
    external_publisher_authority: bool = False
    publish_authority: bool = False
    network_authority: bool = False
    account_connection_authority: bool = False
    deploy_authority: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _iso(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise PublisherHold("HOLD_PUBLISHER_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None:
        raise PublisherHold("HOLD_PUBLISHER_TIMESTAMP_INVALID")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_publisher_input(item: LocalOutboxItem) -> None:
    if not isinstance(item, LocalOutboxItem):
        raise PublisherHold("HOLD_M08_OUTBOX_TYPE")
    try:
        validate_outbox_item(item)
    except QueueHold as exc:
        raise PublisherHold(f"HOLD_M08_OUTBOX_INVALID:{exc.reason}") from exc
    if item.platform not in EXPECTED_ACTIVE:
        raise PublisherHold("HOLD_M08_PLATFORM_NOT_ACTIVE")
    if item.state != "LOCAL_OUTBOX_ONLY" or item.queue_state != "QUEUED_LOCAL":
        raise PublisherHold("HOLD_M08_OUTBOX_STATE_INVALID")
    if not item.publisher_input_ready:
        raise PublisherHold("HOLD_M08_PUBLISHER_INPUT_NOT_READY")
    if item.publisher_authority or item.publish_authority or item.public_publish_eligible:
        raise PublisherHold("HOLD_M08_OUTBOX_FORBIDDEN_AUTHORITY")
    if item.network_authority or item.account_connection_authority or item.deploy_authority:
        raise PublisherHold("HOLD_M08_OUTBOX_EXTERNAL_AUTHORITY")


def _receipt_body(item: LocalOutboxItem, request_id: str, attempted_at_utc: str) -> dict:
    return {
        "schema_version": PUBLISHER_MODEL_VERSION,
        "engine_version": PUBLISHER_ENGINE_VERSION,
        "outbox_item_id": item.item_id,
        "outbox_item_hash": item.item_hash,
        "approval_receipt_hash": item.approval_receipt_hash,
        "report_hash": item.report_hash,
        "asset_id": item.asset_id,
        "platform": item.platform,
        "mode": item.mode,
        "request_id": request_id,
        "attempted_at_utc": attempted_at_utc,
        "execution_mode": "LOCAL_DRY_RUN",
        "publisher_state": "DRY_RUN_RECORDED",
        "analytics_input_ready": True,
        "network_attempted": False,
        "external_write_performed": False,
        "account_connected": False,
        "delivered": False,
        "external_post_id": None,
        "state": "LOCAL_DRY_RUN_PUBLISH_RECEIPT_ONLY",
        "local_dry_run_publisher_authority": True,
        "external_publisher_authority": False,
        "publish_authority": False,
        "network_authority": False,
        "account_connection_authority": False,
        "deploy_authority": False,
    }


def _receipt_body_from_receipt(receipt: DryRunPublishReceipt) -> dict:
    data = receipt.to_dict()
    data.pop("receipt_id")
    data.pop("receipt_hash")
    data["schema_version"] = data.pop("model_version")
    return data


def validate_publish_receipt(receipt: DryRunPublishReceipt) -> None:
    if not isinstance(receipt, DryRunPublishReceipt):
        raise PublisherHold("HOLD_PUBLISHER_RECEIPT_TYPE")
    if receipt.model_version != PUBLISHER_MODEL_VERSION or receipt.engine_version != PUBLISHER_ENGINE_VERSION:
        raise PublisherHold("HOLD_PUBLISHER_RECEIPT_VERSION")
    if receipt.state != "LOCAL_DRY_RUN_PUBLISH_RECEIPT_ONLY" or not receipt.local_dry_run_publisher_authority:
        raise PublisherHold("HOLD_PUBLISHER_RECEIPT_STATE_INVALID")
    if receipt.execution_mode != "LOCAL_DRY_RUN" or receipt.publisher_state != "DRY_RUN_RECORDED":
        raise PublisherHold("HOLD_PUBLISHER_RECEIPT_MODE_INVALID")
    if receipt.platform not in EXPECTED_ACTIVE or not receipt.analytics_input_ready:
        raise PublisherHold("HOLD_PUBLISHER_RECEIPT_ANALYTICS_INPUT_INVALID")
    if not HEX64.fullmatch(receipt.outbox_item_hash) or not HEX64.fullmatch(receipt.approval_receipt_hash) or not HEX64.fullmatch(receipt.report_hash):
        raise PublisherHold("HOLD_PUBLISHER_RECEIPT_BINDING_INVALID")
    if not REQUEST_ID_RE.fullmatch(receipt.request_id):
        raise PublisherHold("HOLD_PUBLISHER_REQUEST_ID_INVALID")
    _iso(receipt.attempted_at_utc)
    if any((receipt.network_attempted, receipt.external_write_performed, receipt.account_connected, receipt.delivered)):
        raise PublisherHold("HOLD_PUBLISHER_FALSE_EXTERNAL_STATE")
    if receipt.external_post_id is not None:
        raise PublisherHold("HOLD_PUBLISHER_EXTERNAL_POST_ID_FORBIDDEN")
    if any((receipt.external_publisher_authority, receipt.publish_authority, receipt.network_authority,
            receipt.account_connection_authority, receipt.deploy_authority)):
        raise PublisherHold("HOLD_PUBLISHER_EXTERNAL_AUTHORITY")
    expected_hash = _hash(_receipt_body_from_receipt(receipt))
    if not HEX64.fullmatch(receipt.receipt_hash) or receipt.receipt_hash != expected_hash:
        raise PublisherHold("HOLD_PUBLISHER_RECEIPT_HASH_MISMATCH")
    if receipt.receipt_id != "dpr_" + receipt.receipt_hash[:24]:
        raise PublisherHold("HOLD_PUBLISHER_RECEIPT_ID_MISMATCH")


def _event_body(receipt: DryRunPublishReceipt) -> dict:
    return {
        "schema_version": PUBLISHER_MODEL_VERSION,
        "engine_version": PUBLISHER_ENGINE_VERSION,
        "receipt_id": receipt.receipt_id,
        "receipt_hash": receipt.receipt_hash,
        "outbox_item_id": receipt.outbox_item_id,
        "outbox_item_hash": receipt.outbox_item_hash,
        "sequence": 1,
        "event_type": "DRY_RUN_ATTEMPT_RECORDED",
        "request_id": receipt.request_id,
        "event_at_utc": receipt.attempted_at_utc,
        "outcome": "NOT_DELIVERED_LOCAL_DRY_RUN",
        "network_attempted": False,
        "external_write_performed": False,
        "delivered": False,
        "external_post_id": None,
        "state": "LOCAL_PUBLISH_ATTEMPT_EVENT_ONLY",
        "external_publisher_authority": False,
        "publish_authority": False,
        "network_authority": False,
        "account_connection_authority": False,
        "deploy_authority": False,
    }


def validate_attempt_event(event: PublishAttemptEvent) -> None:
    if not isinstance(event, PublishAttemptEvent):
        raise PublisherHold("HOLD_PUBLISHER_EVENT_TYPE")
    if event.sequence != 1 or event.event_type != "DRY_RUN_ATTEMPT_RECORDED" or event.outcome != "NOT_DELIVERED_LOCAL_DRY_RUN":
        raise PublisherHold("HOLD_PUBLISHER_EVENT_STATE_INVALID")
    if any((event.network_attempted, event.external_write_performed, event.delivered)) or event.external_post_id is not None:
        raise PublisherHold("HOLD_PUBLISHER_EVENT_FALSE_EXTERNAL_STATE")
    if any((event.external_publisher_authority, event.publish_authority, event.network_authority,
            event.account_connection_authority, event.deploy_authority)):
        raise PublisherHold("HOLD_PUBLISHER_EVENT_EXTERNAL_AUTHORITY")
    body = event.to_dict()
    body.pop("event_id")
    body.pop("event_hash")
    body["schema_version"] = PUBLISHER_MODEL_VERSION
    body["engine_version"] = PUBLISHER_ENGINE_VERSION
    expected_hash = _hash(body)
    if not HEX64.fullmatch(event.event_hash) or event.event_hash != expected_hash:
        raise PublisherHold("HOLD_PUBLISHER_EVENT_HASH_MISMATCH")
    if event.event_id != "pae_" + event.event_hash[:24]:
        raise PublisherHold("HOLD_PUBLISHER_EVENT_ID_MISMATCH")


class LocalDryRunPublisherStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    @classmethod
    def memory(cls) -> "LocalDryRunPublisherStore":
        return cls(sqlite3.connect(":memory:"))

    @classmethod
    def open(cls, path: str | Path) -> "LocalDryRunPublisherStore":
        return cls(sqlite3.connect(str(path)))

    def close(self) -> None:
        self.connection.close()

    def _init_schema(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS publisher_outbox_inputs (
                item_hash TEXT PRIMARY KEY, item_id TEXT NOT NULL UNIQUE,
                item_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dry_run_publish_receipts (
                receipt_hash TEXT PRIMARY KEY, receipt_id TEXT NOT NULL UNIQUE,
                item_hash TEXT NOT NULL UNIQUE REFERENCES publisher_outbox_inputs(item_hash),
                request_id TEXT NOT NULL UNIQUE, attempted_at_utc TEXT NOT NULL,
                receipt_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS publish_attempt_events (
                event_hash TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
                receipt_hash TEXT NOT NULL REFERENCES dry_run_publish_receipts(receipt_hash),
                sequence INTEGER NOT NULL, event_type TEXT NOT NULL,
                event_at_utc TEXT NOT NULL, event_json TEXT NOT NULL,
                UNIQUE(receipt_hash, sequence)
            );
            CREATE TRIGGER IF NOT EXISTS publisher_outbox_inputs_no_update BEFORE UPDATE ON publisher_outbox_inputs BEGIN SELECT RAISE(ABORT, 'publisher_outbox_inputs_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS publisher_outbox_inputs_no_delete BEFORE DELETE ON publisher_outbox_inputs BEGIN SELECT RAISE(ABORT, 'publisher_outbox_inputs_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS dry_run_publish_receipts_no_update BEFORE UPDATE ON dry_run_publish_receipts BEGIN SELECT RAISE(ABORT, 'dry_run_publish_receipts_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS dry_run_publish_receipts_no_delete BEFORE DELETE ON dry_run_publish_receipts BEGIN SELECT RAISE(ABORT, 'dry_run_publish_receipts_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS publish_attempt_events_no_update BEFORE UPDATE ON publish_attempt_events BEGIN SELECT RAISE(ABORT, 'publish_attempt_events_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS publish_attempt_events_no_delete BEFORE DELETE ON publish_attempt_events BEGIN SELECT RAISE(ABORT, 'publish_attempt_events_append_only'); END;
        """)
        self.connection.commit()

    def register_outbox_item(self, item: LocalOutboxItem) -> None:
        validate_publisher_input(item)
        payload = canonical_json(item.to_dict())
        row = self.connection.execute("SELECT item_json FROM publisher_outbox_inputs WHERE item_hash=?", (item.item_hash,)).fetchone()
        if row is not None:
            if row["item_json"] != payload:
                raise PublisherHold("HOLD_M08_OUTBOX_HASH_COLLISION_OR_DRIFT")
            return
        self.connection.execute(
            "INSERT INTO publisher_outbox_inputs(item_hash,item_id,item_json) VALUES(?,?,?)",
            (item.item_hash, item.item_id, payload),
        )
        self.connection.commit()

    def dry_run_publish(self, item: LocalOutboxItem, *, request_id: str, attempted_at_utc: str) -> DryRunPublishReceipt:
        validate_publisher_input(item)
        if not REQUEST_ID_RE.fullmatch(str(request_id)):
            raise PublisherHold("HOLD_PUBLISHER_REQUEST_ID_INVALID")
        clean_time = _iso(attempted_at_utc)
        self.register_outbox_item(item)

        row = self.connection.execute("SELECT receipt_json FROM dry_run_publish_receipts WHERE request_id=?", (request_id,)).fetchone()
        if row is not None:
            receipt = DryRunPublishReceipt(**json.loads(row["receipt_json"]))
            if receipt.outbox_item_hash != item.item_hash or receipt.attempted_at_utc != clean_time:
                raise PublisherHold("HOLD_PUBLISHER_REQUEST_ID_REUSE_MISMATCH")
            validate_publish_receipt(receipt)
            return receipt

        row = self.connection.execute("SELECT receipt_json FROM dry_run_publish_receipts WHERE item_hash=?", (item.item_hash,)).fetchone()
        if row is not None:
            raise PublisherHold("HOLD_M08_OUTBOX_ALREADY_DRY_RUN_RECORDED")

        body = _receipt_body(item, request_id, clean_time)
        receipt_hash = _hash(body)
        receipt = DryRunPublishReceipt(
            receipt_id="dpr_" + receipt_hash[:24], receipt_hash=receipt_hash,
            model_version=PUBLISHER_MODEL_VERSION, engine_version=PUBLISHER_ENGINE_VERSION,
            outbox_item_id=item.item_id, outbox_item_hash=item.item_hash,
            approval_receipt_hash=item.approval_receipt_hash, report_hash=item.report_hash,
            asset_id=item.asset_id, platform=item.platform, mode=item.mode,
            request_id=request_id, attempted_at_utc=clean_time,
            execution_mode="LOCAL_DRY_RUN", publisher_state="DRY_RUN_RECORDED",
            analytics_input_ready=True,
        )
        validate_publish_receipt(receipt)

        event_body = _event_body(receipt)
        event_hash = _hash(event_body)
        event = PublishAttemptEvent(
            event_id="pae_" + event_hash[:24], event_hash=event_hash,
            receipt_id=receipt.receipt_id, receipt_hash=receipt.receipt_hash,
            outbox_item_id=receipt.outbox_item_id, outbox_item_hash=receipt.outbox_item_hash,
            sequence=1, event_type="DRY_RUN_ATTEMPT_RECORDED", request_id=receipt.request_id,
            event_at_utc=receipt.attempted_at_utc, outcome="NOT_DELIVERED_LOCAL_DRY_RUN",
        )
        validate_attempt_event(event)

        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(
                "INSERT INTO dry_run_publish_receipts(receipt_hash,receipt_id,item_hash,request_id,attempted_at_utc,receipt_json) VALUES(?,?,?,?,?,?)",
                (receipt.receipt_hash, receipt.receipt_id, receipt.outbox_item_hash, receipt.request_id,
                 receipt.attempted_at_utc, canonical_json(receipt.to_dict())),
            )
            self.connection.execute(
                "INSERT INTO publish_attempt_events(event_hash,event_id,receipt_hash,sequence,event_type,event_at_utc,event_json) VALUES(?,?,?,?,?,?,?)",
                (event.event_hash, event.event_id, event.receipt_hash, event.sequence, event.event_type,
                 event.event_at_utc, canonical_json(event.to_dict())),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return receipt

    def receipts(self) -> tuple[DryRunPublishReceipt, ...]:
        rows = self.connection.execute("SELECT receipt_json FROM dry_run_publish_receipts ORDER BY attempted_at_utc,receipt_id").fetchall()
        receipts = tuple(DryRunPublishReceipt(**json.loads(row["receipt_json"])) for row in rows)
        for receipt in receipts:
            validate_publish_receipt(receipt)
        return receipts

    def events_for(self, receipt: DryRunPublishReceipt) -> tuple[PublishAttemptEvent, ...]:
        validate_publish_receipt(receipt)
        rows = self.connection.execute(
            "SELECT event_json FROM publish_attempt_events WHERE receipt_hash=? ORDER BY sequence", (receipt.receipt_hash,)
        ).fetchall()
        events = tuple(PublishAttemptEvent(**json.loads(row["event_json"])) for row in rows)
        for event in events:
            validate_attempt_event(event)
        return events
