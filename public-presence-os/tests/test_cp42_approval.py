from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

import pytest

from public_presence_os.approval import (
    APPROVAL_MODEL_VERSION,
    ApprovalHold,
    LocalApprovalStore,
    ReviewDecision,
    ReviewState,
    _hash,
    _qa_report_body,
    validate_qa_report,
)
from public_presence_os.qa import QA_ENGINE_VERSION, QA_MODEL_VERSION, VisualQAReport, VisualQAVerdict

ROOT = Path(__file__).resolve().parents[1]
T0 = "2026-09-06T10:30:00Z"


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def report(*, holds=("HOLD_IDENTITY_EQUIVALENCE",), pass_ready=False, alt_text="Local notice") -> VisualQAReport:
    verdict = VisualQAVerdict.PASS.value if pass_ready else VisualQAVerdict.HOLD.value
    base = VisualQAReport(
        report_id="pending",
        report_hash="0" * 64,
        model_version=QA_MODEL_VERSION,
        engine_version=QA_ENGINE_VERSION,
        asset_id="ma_fixture42",
        render_key=h("render-key-42"),
        platform="FACEBOOK_PAGE",
        mode="TEXT_CARD",
        bundle_id="nab_fixture42",
        bundle_hash=h("bundle-42"),
        adaptation_id="na_fixture42",
        adaptation_hash=h("adapt-42"),
        svg_sha256=h("svg-42"),
        png_sha256=h("png-42"),
        width=1080,
        height=1080,
        integrity_status="PASS_EXACT_BYTE_BINDING",
        text_integrity_status="PASS_EXACT_SOURCE_BOUND_DISPLAY_TEXT",
        svg_safety_status="PASS_SELF_CONTAINED_INACTIVE",
        png_status="PASS_STATIC_DIMENSIONS",
        rights_status="NOT_APPLICABLE",
        alt_text=alt_text,
        alt_text_status="PASS_DISPLAY_TEXT_EXACT",
        photo_relevance_status="NOT_APPLICABLE",
        subject_safe_zone_status="NOT_APPLICABLE",
        identity_equivalence_status=(
            "PASS_VERSIONED_IDENTITY_EQUIVALENCE" if pass_ready else "HOLD_HISTORICAL_EXACT_FONT_HASHES_UNRECOVERED"
        ),
        holds=tuple(sorted(holds)),
        verdict=verdict,
        approval_input_ready=pass_ready,
    )
    digest = _hash(_qa_report_body(base))
    return replace(base, report_hash=digest, report_id="vqr_" + digest[:24])


def test_hash_bound_m07_report_registers_and_exposes_hold():
    qa = report()
    validate_qa_report(qa)
    store = LocalApprovalStore.memory()
    try:
        receipt = store.register_report(qa)
        assert receipt.model_version == APPROVAL_MODEL_VERSION
        assert receipt.current_state == ReviewState.HOLD_REVIEW.value
        assert receipt.qa_holds == ("HOLD_IDENTITY_EQUIVALENCE",)
        assert receipt.local_approval_complete is False
        assert receipt.queue_input_ready is False
        assert receipt.queue_authority is False and receipt.publish_authority is False
    finally:
        store.close()


def test_tampered_m07_report_fails_closed():
    qa = report()
    forged = replace(qa, alt_text="Forged text")
    with pytest.raises(ApprovalHold, match="HOLD_M07_REPORT_HASH_MISMATCH"):
        validate_qa_report(forged)


def test_hold_cannot_be_approved_or_overridden():
    qa = report()
    store = LocalApprovalStore.memory()
    try:
        store.register_report(qa)
        with pytest.raises(ApprovalHold, match="HOLD_QA_BLOCKS_LOCAL_APPROVAL"):
            store.apply_decision(
                qa,
                decision=ReviewDecision.APPROVE_LOCAL,
                actor="Local operator",
                note="Attempted approval",
                decided_at_utc=T0,
                request_id="cp42-approve-blocked",
            )
        assert store.review_receipt(qa).current_state == ReviewState.HOLD_REVIEW.value
    finally:
        store.close()


def test_hold_acknowledgement_is_append_only_and_idempotent():
    qa = report()
    store = LocalApprovalStore.memory()
    try:
        first = store.apply_decision(
            qa,
            decision="ACKNOWLEDGE_HOLD",
            actor="Local operator",
            note="Identity equivalence remains unresolved.",
            decided_at_utc=T0,
            request_id="cp42-hold-ack-001",
        )
        retry = store.apply_decision(
            qa,
            decision="ACKNOWLEDGE_HOLD",
            actor="Local operator",
            note="Identity equivalence remains unresolved.",
            decided_at_utc=T0,
            request_id="cp42-hold-ack-001",
        )
        assert first.event_id == retry.event_id
        assert first.resulting_state == ReviewState.HOLD_ACKNOWLEDGED.value
        receipt = store.review_receipt(qa)
        assert receipt.event_count == 1
        assert receipt.current_state == ReviewState.HOLD_ACKNOWLEDGED.value
        with pytest.raises(sqlite3.DatabaseError, match="append_only"):
            store.connection.execute("UPDATE approval_events SET note='x'")
    finally:
        store.close()


def test_request_id_reuse_with_different_payload_fails_closed():
    qa = report()
    store = LocalApprovalStore.memory()
    try:
        store.apply_decision(
            qa, decision="ACKNOWLEDGE_HOLD", actor="Operator", note="first",
            decided_at_utc=T0, request_id="cp42-request-001",
        )
        with pytest.raises(ApprovalHold, match="HOLD_REVIEW_REQUEST_ID_REUSE_MISMATCH"):
            store.apply_decision(
                qa, decision="ACKNOWLEDGE_HOLD", actor="Operator", note="different",
                decided_at_utc=T0, request_id="cp42-request-001",
            )
    finally:
        store.close()


def test_reject_then_reopen_returns_to_hold_state():
    qa = report()
    store = LocalApprovalStore.memory()
    try:
        rejected = store.apply_decision(
            qa, decision="REJECT_LOCAL", actor="Operator", note="not suitable",
            decided_at_utc=T0, request_id="cp42-reject-001",
        )
        assert rejected.resulting_state == ReviewState.REJECTED_LOCAL.value
        reopened = store.apply_decision(
            qa, decision="REOPEN_LOCAL", actor="Operator", note="review again",
            decided_at_utc="2026-09-06T10:31:00Z", request_id="cp42-reopen-001",
        )
        assert reopened.resulting_state == ReviewState.HOLD_REVIEW.value
        assert store.review_receipt(qa).event_count == 2
    finally:
        store.close()


def test_future_clean_m07_pass_can_be_locally_approved_without_queue_authority():
    qa = report(holds=(), pass_ready=True)
    store = LocalApprovalStore.memory()
    try:
        initial = store.register_report(qa)
        assert initial.current_state == ReviewState.PENDING_REVIEW.value
        event = store.apply_decision(
            qa, decision="APPROVE_LOCAL", actor="Operator", note="local review pass",
            decided_at_utc=T0, request_id="cp42-approve-001",
        )
        assert event.resulting_state == ReviewState.APPROVED_LOCAL.value
        receipt = store.review_receipt(qa)
        assert receipt.local_approval_complete is True
        assert receipt.queue_input_ready is True
        assert receipt.queue_authority is False
        assert receipt.publish_authority is False
        assert receipt.publish_eligible is False
    finally:
        store.close()


def test_static_dashboard_lists_every_hold_and_escapes_operator_text():
    qa = report(holds=("HOLD_IDENTITY_EQUIVALENCE", "HOLD_PHOTO_RELEVANCE_NOT_CONFIRMED"))
    store = LocalApprovalStore.memory()
    try:
        store.apply_decision(
            qa, decision="DEFER_LOCAL", actor="Operator <local>", note="Wait & verify",
            decided_at_utc=T0, request_id="cp42-defer-001",
        )
        dash = store.render_dashboard(qa)
        assert "HOLD_IDENTITY_EQUIVALENCE" in dash.html
        assert "HOLD_PHOTO_RELEVANCE_NOT_CONFIRMED" in dash.html
        assert "Operator &lt;local&gt;" in dash.html
        assert "Wait &amp; verify" in dash.html
        assert "<script" not in dash.html.lower()
        assert "http://" not in dash.html.lower() and "https://" not in dash.html.lower()
        assert dash.queue_authority is False and dash.publish_authority is False and dash.deploy_authority is False
    finally:
        store.close()


def test_report_registration_is_immutable_and_idempotent():
    qa = report()
    store = LocalApprovalStore.memory()
    try:
        first = store.register_report(qa)
        second = store.register_report(qa)
        assert first.receipt_id == second.receipt_id
        with pytest.raises(sqlite3.DatabaseError, match="append_only"):
            store.connection.execute("DELETE FROM qa_reports")
    finally:
        store.close()


def test_cp42_policy_is_local_only_fail_closed_and_advances_to_queue():
    policy = json.loads((ROOT / "config" / "approval_policy.json").read_text())
    assert policy["checkpoint"] == "CP42"
    assert policy["active_platforms"] == ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"]
    assert policy["input_contract"]["required_module"] == "M07_QA"
    assert policy["input_contract"]["qa_hold_can_be_overridden"] is False
    assert policy["storage"]["backend"] == "SQLITE_LOCAL"
    assert policy["storage"]["event_log_append_only"] is True
    assert policy["dashboard"]["external_scripts_allowed"] is False
    assert policy["dashboard"]["remote_assets_allowed"] is False
    assert policy["authority"]["local_review_authority"] is True
    for key in ("queue_authority", "publisher_authority", "publish_authority", "network_authority", "real_account_connection_authority", "deploy_authority"):
        assert policy["authority"][key] is False
    assert policy["next_dependency"] == "M08_QUEUE"
