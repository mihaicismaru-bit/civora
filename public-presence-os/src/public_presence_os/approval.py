from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from html import escape
import json
import re
import sqlite3
from pathlib import Path

from .control import EXPECTED_ACTIVE, canonical_json
from .qa import QA_ENGINE_VERSION, QA_MODEL_VERSION, VisualQAReport, VisualQAVerdict

APPROVAL_MODEL_VERSION = "PPOS_LOCAL_APPROVAL_V1"
APPROVAL_ENGINE_VERSION = "ppos-local-approval-v1.0.0"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


class ApprovalError(ValueError):
    pass


class ApprovalHold(ApprovalError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ReviewDecision(str, Enum):
    APPROVE_LOCAL = "APPROVE_LOCAL"
    REJECT_LOCAL = "REJECT_LOCAL"
    ACKNOWLEDGE_HOLD = "ACKNOWLEDGE_HOLD"
    DEFER_LOCAL = "DEFER_LOCAL"
    REOPEN_LOCAL = "REOPEN_LOCAL"


class ReviewState(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    HOLD_REVIEW = "HOLD_REVIEW"
    HOLD_ACKNOWLEDGED = "HOLD_ACKNOWLEDGED"
    APPROVED_LOCAL = "APPROVED_LOCAL"
    REJECTED_LOCAL = "REJECTED_LOCAL"
    DEFERRED_LOCAL = "DEFERRED_LOCAL"


@dataclass(frozen=True)
class ApprovalEvent:
    event_id: str
    event_hash: str
    model_version: str
    engine_version: str
    report_id: str
    report_hash: str
    sequence: int
    request_id: str
    decision: str
    previous_state: str
    resulting_state: str
    actor: str
    note: str
    decided_at_utc: str
    qa_holds: tuple[str, ...]
    state: str = "LOCAL_APPROVAL_EVENT_ONLY"
    local_review_authority: bool = True
    queue_authority: bool = False
    publish_authority: bool = False
    network_authority: bool = False
    account_connection_authority: bool = False
    deploy_authority: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalReviewReceipt:
    receipt_id: str
    receipt_hash: str
    model_version: str
    engine_version: str
    report_id: str
    report_hash: str
    asset_id: str
    platform: str
    mode: str
    qa_verdict: str
    qa_holds: tuple[str, ...]
    current_state: str
    last_event_id: str | None
    event_count: int
    local_approval_complete: bool
    queue_input_ready: bool
    state: str = "LOCAL_APPROVAL_REVIEW_ONLY"
    local_review_authority: bool = True
    queue_authority: bool = False
    publish_authority: bool = False
    publish_eligible: bool = False
    network_authority: bool = False
    account_connection_authority: bool = False
    deploy_authority: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalDashboard:
    dashboard_id: str
    dashboard_sha256: str
    report_id: str
    report_hash: str
    current_state: str
    html: str
    state: str = "LOCAL_STATIC_DASHBOARD_ONLY"
    network_authority: bool = False
    account_connection_authority: bool = False
    queue_authority: bool = False
    publish_authority: bool = False
    deploy_authority: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _iso(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ApprovalHold("HOLD_REVIEW_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None:
        raise ApprovalHold("HOLD_REVIEW_TIMESTAMP_INVALID")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_actor(value: str) -> str:
    actor = " ".join(str(value).split())
    if not actor or len(actor) > 120:
        raise ApprovalHold("HOLD_REVIEW_ACTOR_INVALID")
    return actor


def _clean_note(value: str) -> str:
    note = " ".join(str(value).split())
    if len(note) > 1000:
        raise ApprovalHold("HOLD_REVIEW_NOTE_TOO_LONG")
    return note


def _qa_report_body(report: VisualQAReport) -> dict:
    return {
        "schema_version": QA_MODEL_VERSION,
        "engine_version": report.engine_version,
        "asset_id": report.asset_id,
        "render_key": report.render_key,
        "platform": report.platform,
        "mode": report.mode,
        "bundle_id": report.bundle_id,
        "bundle_hash": report.bundle_hash,
        "adaptation_id": report.adaptation_id,
        "adaptation_hash": report.adaptation_hash,
        "svg_sha256": report.svg_sha256,
        "png_sha256": report.png_sha256,
        "width": report.width,
        "height": report.height,
        "integrity_status": report.integrity_status,
        "text_integrity_status": report.text_integrity_status,
        "svg_safety_status": report.svg_safety_status,
        "png_status": report.png_status,
        "rights_status": report.rights_status,
        "alt_text": report.alt_text,
        "alt_text_status": report.alt_text_status,
        "photo_relevance_status": report.photo_relevance_status,
        "subject_safe_zone_status": report.subject_safe_zone_status,
        "identity_equivalence_status": report.identity_equivalence_status,
        "holds": tuple(report.holds),
        "verdict": report.verdict,
        "approval_input_ready": report.approval_input_ready,
        "state": "VISUAL_QA_ONLY",
        "visual_qa_authority": True,
        "queue_authority": False,
        "publish_authority": False,
        "publish_eligible": False,
        "network_fetch_performed": False,
        "real_account_connection_performed": False,
    }


def validate_qa_report(report: VisualQAReport) -> None:
    if not isinstance(report, VisualQAReport):
        raise ApprovalHold("HOLD_M07_REPORT_TYPE")
    if report.model_version != QA_MODEL_VERSION or report.engine_version != QA_ENGINE_VERSION:
        raise ApprovalHold("HOLD_M07_REPORT_VERSION")
    if report.state != "VISUAL_QA_ONLY" or not report.visual_qa_authority:
        raise ApprovalHold("HOLD_M07_REPORT_AUTHORITY_INVALID")
    if report.queue_authority or report.publish_authority or report.publish_eligible:
        raise ApprovalHold("HOLD_M07_REPORT_FORBIDDEN_AUTHORITY")
    if report.network_fetch_performed or report.real_account_connection_performed:
        raise ApprovalHold("HOLD_M07_REPORT_EXTERNAL_SIDE_EFFECT")
    if report.platform not in EXPECTED_ACTIVE:
        raise ApprovalHold("HOLD_M07_PLATFORM_NOT_ACTIVE")
    if not HEX64.fullmatch(report.report_hash):
        raise ApprovalHold("HOLD_M07_REPORT_HASH_INVALID")
    if _hash(_qa_report_body(report)) != report.report_hash:
        raise ApprovalHold("HOLD_M07_REPORT_HASH_MISMATCH")
    if report.report_id != "vqr_" + report.report_hash[:24]:
        raise ApprovalHold("HOLD_M07_REPORT_ID_MISMATCH")
    if tuple(report.holds) != tuple(sorted(set(report.holds))):
        raise ApprovalHold("HOLD_M07_HOLD_SET_NONCANONICAL")
    is_pass = report.verdict == VisualQAVerdict.PASS.value
    is_hold = report.verdict == VisualQAVerdict.HOLD.value
    if not (is_pass or is_hold):
        raise ApprovalHold("HOLD_M07_VERDICT_INVALID")
    if report.approval_input_ready != (is_pass and not report.holds):
        raise ApprovalHold("HOLD_M07_APPROVAL_READINESS_CONTRADICTION")
    if is_pass and report.holds:
        raise ApprovalHold("HOLD_M07_PASS_WITH_HOLDS")
    if is_hold and not report.holds:
        raise ApprovalHold("HOLD_M07_HOLD_WITHOUT_REASON")


def _initial_state(report: VisualQAReport) -> ReviewState:
    return ReviewState.HOLD_REVIEW if report.holds else ReviewState.PENDING_REVIEW


def _transition(report: VisualQAReport, current: ReviewState, decision: ReviewDecision) -> ReviewState:
    base = _initial_state(report)
    if decision is ReviewDecision.REOPEN_LOCAL:
        if current in {ReviewState.APPROVED_LOCAL, ReviewState.REJECTED_LOCAL, ReviewState.DEFERRED_LOCAL, ReviewState.HOLD_ACKNOWLEDGED}:
            return base
        raise ApprovalHold("HOLD_REOPEN_TRANSITION_INVALID")
    if decision is ReviewDecision.APPROVE_LOCAL:
        if report.holds or not report.approval_input_ready or report.verdict != VisualQAVerdict.PASS.value:
            raise ApprovalHold("HOLD_QA_BLOCKS_LOCAL_APPROVAL")
        if current not in {ReviewState.PENDING_REVIEW, ReviewState.DEFERRED_LOCAL}:
            raise ApprovalHold("HOLD_APPROVE_TRANSITION_INVALID")
        return ReviewState.APPROVED_LOCAL
    if decision is ReviewDecision.ACKNOWLEDGE_HOLD:
        if not report.holds:
            raise ApprovalHold("HOLD_ACK_REQUIRES_QA_HOLD")
        if current not in {ReviewState.HOLD_REVIEW, ReviewState.DEFERRED_LOCAL}:
            raise ApprovalHold("HOLD_ACK_TRANSITION_INVALID")
        return ReviewState.HOLD_ACKNOWLEDGED
    if decision is ReviewDecision.REJECT_LOCAL:
        if current not in {ReviewState.PENDING_REVIEW, ReviewState.HOLD_REVIEW, ReviewState.HOLD_ACKNOWLEDGED, ReviewState.DEFERRED_LOCAL}:
            raise ApprovalHold("HOLD_REJECT_TRANSITION_INVALID")
        return ReviewState.REJECTED_LOCAL
    if decision is ReviewDecision.DEFER_LOCAL:
        if current not in {ReviewState.PENDING_REVIEW, ReviewState.HOLD_REVIEW, ReviewState.HOLD_ACKNOWLEDGED}:
            raise ApprovalHold("HOLD_DEFER_TRANSITION_INVALID")
        return ReviewState.DEFERRED_LOCAL
    raise ApprovalHold("HOLD_DECISION_INVALID")


def _event_body(
    report: VisualQAReport,
    *,
    sequence: int,
    request_id: str,
    decision: ReviewDecision,
    previous_state: ReviewState,
    resulting_state: ReviewState,
    actor: str,
    note: str,
    decided_at_utc: str,
) -> dict:
    return {
        "schema_version": APPROVAL_MODEL_VERSION,
        "engine_version": APPROVAL_ENGINE_VERSION,
        "report_id": report.report_id,
        "report_hash": report.report_hash,
        "sequence": sequence,
        "request_id": request_id,
        "decision": decision.value,
        "previous_state": previous_state.value,
        "resulting_state": resulting_state.value,
        "actor": actor,
        "note": note,
        "decided_at_utc": decided_at_utc,
        "qa_holds": tuple(report.holds),
        "state": "LOCAL_APPROVAL_EVENT_ONLY",
        "local_review_authority": True,
        "queue_authority": False,
        "publish_authority": False,
        "network_authority": False,
        "account_connection_authority": False,
        "deploy_authority": False,
    }


class LocalApprovalStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    @classmethod
    def memory(cls) -> "LocalApprovalStore":
        return cls(sqlite3.connect(":memory:"))

    @classmethod
    def open(cls, path: str | Path) -> "LocalApprovalStore":
        return cls(sqlite3.connect(str(path)))

    def close(self) -> None:
        self.connection.close()

    def _init_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS qa_reports (
                report_hash TEXT PRIMARY KEY,
                report_id TEXT NOT NULL UNIQUE,
                asset_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                mode TEXT NOT NULL,
                qa_verdict TEXT NOT NULL,
                holds_json TEXT NOT NULL,
                report_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approval_events (
                event_id TEXT PRIMARY KEY,
                event_hash TEXT NOT NULL UNIQUE,
                report_hash TEXT NOT NULL REFERENCES qa_reports(report_hash),
                sequence INTEGER NOT NULL,
                request_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                previous_state TEXT NOT NULL,
                resulting_state TEXT NOT NULL,
                actor TEXT NOT NULL,
                note TEXT NOT NULL,
                decided_at_utc TEXT NOT NULL,
                event_json TEXT NOT NULL,
                UNIQUE(report_hash, sequence),
                UNIQUE(report_hash, request_id)
            );
            CREATE TRIGGER IF NOT EXISTS qa_reports_no_update
            BEFORE UPDATE ON qa_reports BEGIN SELECT RAISE(ABORT, 'qa_reports_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS qa_reports_no_delete
            BEFORE DELETE ON qa_reports BEGIN SELECT RAISE(ABORT, 'qa_reports_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS approval_events_no_update
            BEFORE UPDATE ON approval_events BEGIN SELECT RAISE(ABORT, 'approval_events_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS approval_events_no_delete
            BEFORE DELETE ON approval_events BEGIN SELECT RAISE(ABORT, 'approval_events_append_only'); END;
            """
        )
        self.connection.commit()

    def register_report(self, report: VisualQAReport) -> ApprovalReviewReceipt:
        validate_qa_report(report)
        report_json = canonical_json(report.to_dict())
        existing = self.connection.execute(
            "SELECT report_json FROM qa_reports WHERE report_hash=?", (report.report_hash,)
        ).fetchone()
        if existing is not None:
            if existing["report_json"] != report_json:
                raise ApprovalHold("HOLD_M07_REPORT_HASH_COLLISION_OR_DRIFT")
            return self.review_receipt(report)
        self.connection.execute(
            "INSERT INTO qa_reports(report_hash,report_id,asset_id,platform,mode,qa_verdict,holds_json,report_json) VALUES(?,?,?,?,?,?,?,?)",
            (
                report.report_hash,
                report.report_id,
                report.asset_id,
                report.platform,
                report.mode,
                report.verdict,
                canonical_json(tuple(report.holds)),
                report_json,
            ),
        )
        self.connection.commit()
        return self.review_receipt(report)

    def _events(self, report_hash: str) -> list[ApprovalEvent]:
        rows = self.connection.execute(
            "SELECT event_json FROM approval_events WHERE report_hash=? ORDER BY sequence", (report_hash,)
        ).fetchall()
        events: list[ApprovalEvent] = []
        for row in rows:
            data = json.loads(row["event_json"])
            data["qa_holds"] = tuple(data["qa_holds"])
            events.append(ApprovalEvent(**data))
        return events

    def apply_decision(
        self,
        report: VisualQAReport,
        *,
        decision: ReviewDecision | str,
        actor: str,
        note: str,
        decided_at_utc: str,
        request_id: str,
    ) -> ApprovalEvent:
        validate_qa_report(report)
        self.register_report(report)
        try:
            parsed_decision = decision if isinstance(decision, ReviewDecision) else ReviewDecision(str(decision))
        except ValueError as exc:
            raise ApprovalHold("HOLD_DECISION_INVALID") from exc
        if not REQUEST_ID_RE.fullmatch(str(request_id)):
            raise ApprovalHold("HOLD_REVIEW_REQUEST_ID_INVALID")
        clean_actor = _clean_actor(actor)
        clean_note = _clean_note(note)
        clean_time = _iso(decided_at_utc)

        existing = self.connection.execute(
            "SELECT event_json FROM approval_events WHERE report_hash=? AND request_id=?",
            (report.report_hash, request_id),
        ).fetchone()
        if existing is not None:
            data = json.loads(existing["event_json"])
            expected = {
                "decision": parsed_decision.value,
                "actor": clean_actor,
                "note": clean_note,
                "decided_at_utc": clean_time,
            }
            if any(data[key] != value for key, value in expected.items()):
                raise ApprovalHold("HOLD_REVIEW_REQUEST_ID_REUSE_MISMATCH")
            data["qa_holds"] = tuple(data["qa_holds"])
            return ApprovalEvent(**data)

        try:
            self.connection.execute("BEGIN IMMEDIATE")
            rows = self.connection.execute(
                "SELECT sequence,resulting_state FROM approval_events WHERE report_hash=? ORDER BY sequence",
                (report.report_hash,),
            ).fetchall()
            sequence = len(rows) + 1
            previous = ReviewState(rows[-1]["resulting_state"]) if rows else _initial_state(report)
            resulting = _transition(report, previous, parsed_decision)
            body = _event_body(
                report,
                sequence=sequence,
                request_id=request_id,
                decision=parsed_decision,
                previous_state=previous,
                resulting_state=resulting,
                actor=clean_actor,
                note=clean_note,
                decided_at_utc=clean_time,
            )
            event_hash = _hash(body)
            event = ApprovalEvent(
                event_id="are_" + event_hash[:24],
                event_hash=event_hash,
                model_version=APPROVAL_MODEL_VERSION,
                engine_version=APPROVAL_ENGINE_VERSION,
                report_id=report.report_id,
                report_hash=report.report_hash,
                sequence=sequence,
                request_id=request_id,
                decision=parsed_decision.value,
                previous_state=previous.value,
                resulting_state=resulting.value,
                actor=clean_actor,
                note=clean_note,
                decided_at_utc=clean_time,
                qa_holds=tuple(report.holds),
            )
            self.connection.execute(
                "INSERT INTO approval_events(event_id,event_hash,report_hash,sequence,request_id,decision,previous_state,resulting_state,actor,note,decided_at_utc,event_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.event_hash,
                    event.report_hash,
                    event.sequence,
                    event.request_id,
                    event.decision,
                    event.previous_state,
                    event.resulting_state,
                    event.actor,
                    event.note,
                    event.decided_at_utc,
                    canonical_json(event.to_dict()),
                ),
            )
            self.connection.commit()
            return event
        except Exception:
            self.connection.rollback()
            raise

    def review_receipt(self, report: VisualQAReport) -> ApprovalReviewReceipt:
        validate_qa_report(report)
        row = self.connection.execute(
            "SELECT report_json FROM qa_reports WHERE report_hash=?", (report.report_hash,)
        ).fetchone()
        if row is None:
            raise ApprovalHold("HOLD_REPORT_NOT_REGISTERED")
        if row["report_json"] != canonical_json(report.to_dict()):
            raise ApprovalHold("HOLD_REGISTERED_REPORT_DRIFT")
        events = self._events(report.report_hash)
        current = ReviewState(events[-1].resulting_state) if events else _initial_state(report)
        approval_complete = current is ReviewState.APPROVED_LOCAL and not report.holds and report.approval_input_ready
        body = {
            "schema_version": APPROVAL_MODEL_VERSION,
            "engine_version": APPROVAL_ENGINE_VERSION,
            "report_id": report.report_id,
            "report_hash": report.report_hash,
            "asset_id": report.asset_id,
            "platform": report.platform,
            "mode": report.mode,
            "qa_verdict": report.verdict,
            "qa_holds": tuple(report.holds),
            "current_state": current.value,
            "last_event_id": events[-1].event_id if events else None,
            "event_count": len(events),
            "local_approval_complete": approval_complete,
            "queue_input_ready": approval_complete,
            "state": "LOCAL_APPROVAL_REVIEW_ONLY",
            "local_review_authority": True,
            "queue_authority": False,
            "publish_authority": False,
            "publish_eligible": False,
            "network_authority": False,
            "account_connection_authority": False,
            "deploy_authority": False,
        }
        receipt_hash = _hash(body)
        return ApprovalReviewReceipt(
            receipt_id="arr_" + receipt_hash[:24],
            receipt_hash=receipt_hash,
            model_version=APPROVAL_MODEL_VERSION,
            engine_version=APPROVAL_ENGINE_VERSION,
            report_id=report.report_id,
            report_hash=report.report_hash,
            asset_id=report.asset_id,
            platform=report.platform,
            mode=report.mode,
            qa_verdict=report.verdict,
            qa_holds=tuple(report.holds),
            current_state=current.value,
            last_event_id=events[-1].event_id if events else None,
            event_count=len(events),
            local_approval_complete=approval_complete,
            queue_input_ready=approval_complete,
        )

    def render_dashboard(self, report: VisualQAReport) -> ApprovalDashboard:
        receipt = self.review_receipt(report)
        events = self._events(report.report_hash)
        hold_items = "".join(f"<li><code>{escape(reason)}</code></li>" for reason in report.holds)
        if not hold_items:
            hold_items = "<li>None</li>"
        event_rows = "".join(
            "<tr>"
            f"<td>{event.sequence}</td>"
            f"<td>{escape(event.decision)}</td>"
            f"<td>{escape(event.resulting_state)}</td>"
            f"<td>{escape(event.actor)}</td>"
            f"<td>{escape(event.decided_at_utc)}</td>"
            f"<td>{escape(event.note)}</td>"
            "</tr>"
            for event in events
        )
        if not event_rows:
            event_rows = '<tr><td colspan="6">No local review decisions recorded.</td></tr>'
        html = (
            '<section data-ppos="approval-dashboard-v1">'
            '<h1>PUBLIC PRESENCE OS — Local Approval Review</h1>'
            f'<p><strong>State:</strong> {escape(receipt.current_state)}</p>'
            f'<p><strong>Platform:</strong> {escape(report.platform)} · <strong>Mode:</strong> {escape(report.mode)}</p>'
            f'<p><strong>QA report:</strong> <code>{escape(report.report_id)}</code></p>'
            f'<p><strong>QA verdict:</strong> {escape(report.verdict)}</p>'
            '<h2>Blocking HOLD reasons</h2>'
            f'<ul>{hold_items}</ul>'
            '<h2>Local decision history</h2>'
            '<table><thead><tr><th>#</th><th>Decision</th><th>State</th><th>Actor</th><th>UTC</th><th>Note</th></tr></thead>'
            f'<tbody>{event_rows}</tbody></table>'
            '<p>Local review only. No queue, publisher, network, account-connection, public-publish, or deploy authority.</p>'
            '</section>'
        )
        digest = sha256(html.encode("utf-8")).hexdigest()
        return ApprovalDashboard(
            dashboard_id="ad_" + digest[:24],
            dashboard_sha256=digest,
            report_id=report.report_id,
            report_hash=report.report_hash,
            current_state=receipt.current_state,
            html=html,
        )
