from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import sqlite3
from pathlib import Path

from .approval import APPROVAL_ENGINE_VERSION, APPROVAL_MODEL_VERSION, ApprovalReviewReceipt, ReviewState
from .control import EXPECTED_ACTIVE, canonical_json

QUEUE_MODEL_VERSION = "PPOS_LOCAL_QUEUE_V1"
QUEUE_ENGINE_VERSION = "ppos-local-queue-v1.0.0"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
APPROVAL_EVENT_ID_RE = re.compile(r"^are_[0-9a-f]{24}$")


class QueueError(ValueError):
    pass


class QueueHold(QueueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LocalOutboxItem:
    item_id: str
    item_hash: str
    model_version: str
    engine_version: str
    approval_receipt_id: str
    approval_receipt_hash: str
    report_id: str
    report_hash: str
    asset_id: str
    platform: str
    mode: str
    request_id: str
    queued_at_utc: str
    queue_state: str
    publisher_input_ready: bool
    state: str = "LOCAL_OUTBOX_ONLY"
    local_queue_authority: bool = True
    publisher_authority: bool = False
    publish_authority: bool = False
    public_publish_eligible: bool = False
    network_authority: bool = False
    account_connection_authority: bool = False
    deploy_authority: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class QueueEvent:
    event_id: str
    event_hash: str
    item_id: str
    item_hash: str
    approval_receipt_hash: str
    sequence: int
    event_type: str
    request_id: str
    event_at_utc: str
    resulting_state: str
    state: str = "LOCAL_QUEUE_EVENT_ONLY"
    publisher_authority: bool = False
    publish_authority: bool = False
    network_authority: bool = False
    deploy_authority: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _iso(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise QueueHold("HOLD_QUEUE_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None:
        raise QueueHold("HOLD_QUEUE_TIMESTAMP_INVALID")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _approval_receipt_body(receipt: ApprovalReviewReceipt) -> dict:
    return {
        "schema_version": APPROVAL_MODEL_VERSION,
        "engine_version": receipt.engine_version,
        "report_id": receipt.report_id,
        "report_hash": receipt.report_hash,
        "asset_id": receipt.asset_id,
        "platform": receipt.platform,
        "mode": receipt.mode,
        "qa_verdict": receipt.qa_verdict,
        "qa_holds": tuple(receipt.qa_holds),
        "current_state": receipt.current_state,
        "last_event_id": receipt.last_event_id,
        "event_count": receipt.event_count,
        "local_approval_complete": receipt.local_approval_complete,
        "queue_input_ready": receipt.queue_input_ready,
        "state": "LOCAL_APPROVAL_REVIEW_ONLY",
        "local_review_authority": True,
        "queue_authority": False,
        "publish_authority": False,
        "publish_eligible": False,
        "network_authority": False,
        "account_connection_authority": False,
        "deploy_authority": False,
    }


def validate_approval_receipt(receipt: ApprovalReviewReceipt) -> None:
    if not isinstance(receipt, ApprovalReviewReceipt):
        raise QueueHold("HOLD_M12_RECEIPT_TYPE")
    if receipt.model_version != APPROVAL_MODEL_VERSION or receipt.engine_version != APPROVAL_ENGINE_VERSION:
        raise QueueHold("HOLD_M12_RECEIPT_VERSION")
    if receipt.state != "LOCAL_APPROVAL_REVIEW_ONLY" or not receipt.local_review_authority:
        raise QueueHold("HOLD_M12_RECEIPT_AUTHORITY_INVALID")
    if receipt.queue_authority or receipt.publish_authority or receipt.publish_eligible:
        raise QueueHold("HOLD_M12_RECEIPT_FORBIDDEN_AUTHORITY")
    if receipt.network_authority or receipt.account_connection_authority or receipt.deploy_authority:
        raise QueueHold("HOLD_M12_RECEIPT_EXTERNAL_AUTHORITY")
    if receipt.platform not in EXPECTED_ACTIVE:
        raise QueueHold("HOLD_M12_PLATFORM_NOT_ACTIVE")
    if not HEX64.fullmatch(receipt.receipt_hash) or _hash(_approval_receipt_body(receipt)) != receipt.receipt_hash:
        raise QueueHold("HOLD_M12_RECEIPT_HASH_MISMATCH")
    if receipt.receipt_id != "arr_" + receipt.receipt_hash[:24]:
        raise QueueHold("HOLD_M12_RECEIPT_ID_MISMATCH")
    if not HEX64.fullmatch(receipt.report_hash):
        raise QueueHold("HOLD_M12_REPORT_HASH_INVALID")
    if tuple(receipt.qa_holds) != tuple(sorted(set(receipt.qa_holds))):
        raise QueueHold("HOLD_M12_HOLD_SET_NONCANONICAL")
    if receipt.qa_holds:
        raise QueueHold("HOLD_M12_QA_HOLDS_PRESENT")
    if receipt.qa_verdict != "PASS":
        raise QueueHold("HOLD_M12_QA_NOT_PASS")
    if receipt.current_state != ReviewState.APPROVED_LOCAL.value:
        raise QueueHold("HOLD_M12_NOT_APPROVED_LOCAL")
    if not receipt.local_approval_complete or not receipt.queue_input_ready:
        raise QueueHold("HOLD_M12_QUEUE_INPUT_NOT_READY")
    if receipt.event_count < 1 or receipt.last_event_id is None or not APPROVAL_EVENT_ID_RE.fullmatch(receipt.last_event_id):
        raise QueueHold("HOLD_M12_APPROVAL_EVENT_BINDING_INVALID")


def _item_body(receipt: ApprovalReviewReceipt, request_id: str, queued_at_utc: str) -> dict:
    return {
        "schema_version": QUEUE_MODEL_VERSION,
        "engine_version": QUEUE_ENGINE_VERSION,
        "approval_receipt_id": receipt.receipt_id,
        "approval_receipt_hash": receipt.receipt_hash,
        "report_id": receipt.report_id,
        "report_hash": receipt.report_hash,
        "asset_id": receipt.asset_id,
        "platform": receipt.platform,
        "mode": receipt.mode,
        "request_id": request_id,
        "queued_at_utc": queued_at_utc,
        "queue_state": "QUEUED_LOCAL",
        "publisher_input_ready": True,
        "state": "LOCAL_OUTBOX_ONLY",
        "local_queue_authority": True,
        "publisher_authority": False,
        "publish_authority": False,
        "public_publish_eligible": False,
        "network_authority": False,
        "account_connection_authority": False,
        "deploy_authority": False,
    }


def validate_outbox_item(item: LocalOutboxItem) -> None:
    if not isinstance(item, LocalOutboxItem):
        raise QueueHold("HOLD_QUEUE_ITEM_TYPE")
    if item.model_version != QUEUE_MODEL_VERSION or item.engine_version != QUEUE_ENGINE_VERSION:
        raise QueueHold("HOLD_QUEUE_ITEM_VERSION")
    if item.state != "LOCAL_OUTBOX_ONLY" or not item.local_queue_authority:
        raise QueueHold("HOLD_QUEUE_ITEM_AUTHORITY_INVALID")
    if item.publisher_authority or item.publish_authority or item.public_publish_eligible:
        raise QueueHold("HOLD_QUEUE_ITEM_FORBIDDEN_AUTHORITY")
    if item.network_authority or item.account_connection_authority or item.deploy_authority:
        raise QueueHold("HOLD_QUEUE_ITEM_EXTERNAL_AUTHORITY")
    if item.platform not in EXPECTED_ACTIVE or item.queue_state != "QUEUED_LOCAL" or not item.publisher_input_ready:
        raise QueueHold("HOLD_QUEUE_ITEM_STATE_INVALID")
    if not REQUEST_ID_RE.fullmatch(item.request_id):
        raise QueueHold("HOLD_QUEUE_REQUEST_ID_INVALID")
    _iso(item.queued_at_utc)
    expected = _item_body_from_item(item)
    if not HEX64.fullmatch(item.item_hash) or _hash(expected) != item.item_hash:
        raise QueueHold("HOLD_QUEUE_ITEM_HASH_MISMATCH")
    if item.item_id != "obi_" + item.item_hash[:24]:
        raise QueueHold("HOLD_QUEUE_ITEM_ID_MISMATCH")


def _item_body_from_item(item: LocalOutboxItem) -> dict:
    data = item.to_dict()
    data.pop("item_id")
    data.pop("item_hash")
    data["schema_version"] = data.pop("model_version")
    return data


class LocalOutboxStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    @classmethod
    def memory(cls) -> "LocalOutboxStore":
        return cls(sqlite3.connect(":memory:"))

    @classmethod
    def open(cls, path: str | Path) -> "LocalOutboxStore":
        return cls(sqlite3.connect(str(path)))

    def close(self) -> None:
        self.connection.close()

    def _init_schema(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS approval_receipts (
                receipt_hash TEXT PRIMARY KEY, receipt_id TEXT NOT NULL UNIQUE,
                report_hash TEXT NOT NULL, receipt_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox_items (
                item_hash TEXT PRIMARY KEY, item_id TEXT NOT NULL UNIQUE,
                receipt_hash TEXT NOT NULL UNIQUE REFERENCES approval_receipts(receipt_hash),
                request_id TEXT NOT NULL UNIQUE, queued_at_utc TEXT NOT NULL, item_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS queue_events (
                event_hash TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
                item_hash TEXT NOT NULL REFERENCES outbox_items(item_hash), sequence INTEGER NOT NULL,
                event_type TEXT NOT NULL, request_id TEXT NOT NULL, event_at_utc TEXT NOT NULL,
                event_json TEXT NOT NULL, UNIQUE(item_hash, sequence)
            );
            CREATE TRIGGER IF NOT EXISTS approval_receipts_no_update BEFORE UPDATE ON approval_receipts BEGIN SELECT RAISE(ABORT, 'approval_receipts_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS approval_receipts_no_delete BEFORE DELETE ON approval_receipts BEGIN SELECT RAISE(ABORT, 'approval_receipts_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS outbox_items_no_update BEFORE UPDATE ON outbox_items BEGIN SELECT RAISE(ABORT, 'outbox_items_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS outbox_items_no_delete BEFORE DELETE ON outbox_items BEGIN SELECT RAISE(ABORT, 'outbox_items_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS queue_events_no_update BEFORE UPDATE ON queue_events BEGIN SELECT RAISE(ABORT, 'queue_events_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS queue_events_no_delete BEFORE DELETE ON queue_events BEGIN SELECT RAISE(ABORT, 'queue_events_append_only'); END;
        """)
        self.connection.commit()

    def register_receipt(self, receipt: ApprovalReviewReceipt) -> None:
        validate_approval_receipt(receipt)
        payload = canonical_json(receipt.to_dict())
        row = self.connection.execute("SELECT receipt_json FROM approval_receipts WHERE receipt_hash=?", (receipt.receipt_hash,)).fetchone()
        if row is not None:
            if row["receipt_json"] != payload:
                raise QueueHold("HOLD_M12_RECEIPT_HASH_COLLISION_OR_DRIFT")
            return
        self.connection.execute(
            "INSERT INTO approval_receipts(receipt_hash,receipt_id,report_hash,receipt_json) VALUES(?,?,?,?)",
            (receipt.receipt_hash, receipt.receipt_id, receipt.report_hash, payload),
        )
        self.connection.commit()

    def enqueue(self, receipt: ApprovalReviewReceipt, *, request_id: str, queued_at_utc: str) -> LocalOutboxItem:
        validate_approval_receipt(receipt)
        if not REQUEST_ID_RE.fullmatch(str(request_id)):
            raise QueueHold("HOLD_QUEUE_REQUEST_ID_INVALID")
        clean_time = _iso(queued_at_utc)
        self.register_receipt(receipt)

        row = self.connection.execute("SELECT item_json FROM outbox_items WHERE request_id=?", (request_id,)).fetchone()
        if row is not None:
            item = LocalOutboxItem(**json.loads(row["item_json"]))
            if item.approval_receipt_hash != receipt.receipt_hash or item.queued_at_utc != clean_time:
                raise QueueHold("HOLD_QUEUE_REQUEST_ID_REUSE_MISMATCH")
            validate_outbox_item(item)
            return item

        row = self.connection.execute("SELECT item_json FROM outbox_items WHERE receipt_hash=?", (receipt.receipt_hash,)).fetchone()
        if row is not None:
            raise QueueHold("HOLD_APPROVAL_RECEIPT_ALREADY_ENQUEUED")

        body = _item_body(receipt, request_id, clean_time)
        item_hash = _hash(body)
        item = LocalOutboxItem(
            item_id="obi_" + item_hash[:24], item_hash=item_hash,
            model_version=QUEUE_MODEL_VERSION, engine_version=QUEUE_ENGINE_VERSION,
            approval_receipt_id=receipt.receipt_id, approval_receipt_hash=receipt.receipt_hash,
            report_id=receipt.report_id, report_hash=receipt.report_hash, asset_id=receipt.asset_id,
            platform=receipt.platform, mode=receipt.mode, request_id=request_id,
            queued_at_utc=clean_time, queue_state="QUEUED_LOCAL", publisher_input_ready=True,
        )
        validate_outbox_item(item)
        event_body = {
            "schema_version": QUEUE_MODEL_VERSION, "engine_version": QUEUE_ENGINE_VERSION,
            "item_id": item.item_id, "item_hash": item.item_hash,
            "approval_receipt_hash": item.approval_receipt_hash, "sequence": 1,
            "event_type": "ENQUEUE_LOCAL", "request_id": item.request_id,
            "event_at_utc": item.queued_at_utc, "resulting_state": item.queue_state,
            "state": "LOCAL_QUEUE_EVENT_ONLY", "publisher_authority": False,
            "publish_authority": False, "network_authority": False, "deploy_authority": False,
        }
        event_hash = _hash(event_body)
        event = QueueEvent(event_id="qev_" + event_hash[:24], event_hash=event_hash,
                           item_id=item.item_id, item_hash=item.item_hash,
                           approval_receipt_hash=item.approval_receipt_hash, sequence=1,
                           event_type="ENQUEUE_LOCAL", request_id=item.request_id,
                           event_at_utc=item.queued_at_utc, resulting_state=item.queue_state)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(
                "INSERT INTO outbox_items(item_hash,item_id,receipt_hash,request_id,queued_at_utc,item_json) VALUES(?,?,?,?,?,?)",
                (item.item_hash, item.item_id, item.approval_receipt_hash, item.request_id, item.queued_at_utc, canonical_json(item.to_dict())),
            )
            self.connection.execute(
                "INSERT INTO queue_events(event_hash,event_id,item_hash,sequence,event_type,request_id,event_at_utc,event_json) VALUES(?,?,?,?,?,?,?,?)",
                (event.event_hash, event.event_id, event.item_hash, event.sequence, event.event_type, event.request_id, event.event_at_utc, canonical_json(event.to_dict())),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return item

    def pending_items(self) -> tuple[LocalOutboxItem, ...]:
        rows = self.connection.execute("SELECT item_json FROM outbox_items ORDER BY queued_at_utc,item_id").fetchall()
        items = tuple(LocalOutboxItem(**json.loads(row["item_json"])) for row in rows)
        for item in items:
            validate_outbox_item(item)
        return items

    def events_for(self, item: LocalOutboxItem) -> tuple[QueueEvent, ...]:
        validate_outbox_item(item)
        rows = self.connection.execute("SELECT event_json FROM queue_events WHERE item_hash=? ORDER BY sequence", (item.item_hash,)).fetchall()
        return tuple(QueueEvent(**json.loads(row["event_json"])) for row in rows)
