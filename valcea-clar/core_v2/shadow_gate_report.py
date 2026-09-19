from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _load(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object document: {path}")
    return value


def _rows_by_story(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("story_id") or ""): row
        for row in document.get("rows") or []
        if isinstance(row, dict) and str(row.get("story_id") or "").strip()
    }


def _facebook_blockers(receipt: dict[str, Any]) -> tuple[list[str], str | None]:
    if receipt.get("status") == "DELIVERED" and receipt.get("readback_ok") is True:
        return [], None
    error = receipt.get("error") if isinstance(receipt.get("error"), dict) else {}
    message = str(error.get("message") or receipt.get("error_message") or "")
    code = error.get("code") if error else receipt.get("error_code")
    if code == 10 and (
        "pages_read_engagement" in message
        or "Page Public Content Access" in message
    ):
        return ["FACEBOOK_READBACK_PERMISSION_MISSING"], "META_READ_PERMISSION_CONFIGURATION_REQUIRED"
    return ["FACEBOOK_READBACK_FAILED"], None


def _instagram_blockers(receipt: dict[str, Any]) -> list[str]:
    if not (receipt.get("status") == "DELIVERED" and receipt.get("readback_ok") is True):
        return ["INSTAGRAM_READBACK_FAILED"]
    if receipt.get("remote_visual_readback_ok") is not True:
        return ["INSTAGRAM_REMOTE_VISUAL_READBACK_FAILED"]
    if receipt.get("remote_visual_identity_bound") is not True:
        return ["INSTAGRAM_VISUAL_IDENTITY_UNBOUND"]
    return []


_VISUAL_FAILURE_TO_BLOCKER = {
    "INTERNAL_VISUAL_GATE_FAILED": "VISUAL_INTERNAL_GATE_FAILED",
    "SITE_ARTICLE_TRANSPORT_FAILURE": "SITE_VISUAL_ARTICLE_TRANSPORT_FAILED",
    "SITE_APPROVED_VISUAL_ABSENT": "SITE_APPROVED_VISUAL_ABSENT",
    "SITE_APPROVED_VISUAL_TRANSPORT_FAILURE": "SITE_APPROVED_VISUAL_TRANSPORT_FAILED",
    "PROVENANCE_SOURCE_TRANSPORT_FAILURE": "VISUAL_PROVENANCE_TRANSPORT_FAILED",
    "PROVENANCE_DIRECT_ASSET_TRANSPORT_FAILURE": "VISUAL_PROVENANCE_TRANSPORT_FAILED",
    "MISSING_VISUAL_PROVENANCE_FIELDS": "VISUAL_PROVENANCE_FIELDS_MISSING",
    "VISUAL_TRUTH_UNCLASSIFIED_FAILURE": "VISUAL_READBACK_FAILED",
}


def _visual_blockers(receipt: dict[str, Any]) -> list[str]:
    if receipt.get("status") == "VERIFIED" and receipt.get("readback_ok") is True:
        return []
    failure_classification = str(receipt.get("failure_classification") or "").strip()
    if failure_classification in _VISUAL_FAILURE_TO_BLOCKER:
        return [_VISUAL_FAILURE_TO_BLOCKER[failure_classification]]

    # Backward-compatible fail-closed fallback for receipts created before the
    # explicit visual failure taxonomy existed.
    blockers: list[str] = []
    if receipt.get("article_image_bound") is False:
        blockers.append("VISUAL_ARTICLE_BINDING_FAILED")
    elif receipt.get("public_image_readback_ok") is False:
        blockers.append("VISUAL_PUBLIC_IMAGE_FAILED")
    if (
        receipt.get("provenance_source_readback_ok") is False
        or receipt.get("direct_source_readback_ok") is False
    ):
        blockers.append("VISUAL_PROVENANCE_FAILED")
    if not blockers:
        blockers.append("VISUAL_READBACK_FAILED")
    return blockers


def _cross_surface_visual_blockers(candidate: dict[str, Any], visual_receipt: dict[str, Any]) -> list[str]:
    """Keep cross-surface divergence explicit and cross-artifact fail-closed."""
    blockers: list[str] = []
    candidate_state = str(candidate.get("canonical_site_visual_binding_state") or "").strip()
    receipt_state = str(visual_receipt.get("canonical_site_visual_binding_state") or "").strip()
    if candidate_state != receipt_state:
        blockers.append("CROSS_SURFACE_VISUAL_BINDING_STATE_MISMATCH")

    if candidate_state == "CONSISTENT":
        return blockers
    if not candidate_state:
        blockers.append("CROSS_SURFACE_VISUAL_BINDING_UNKNOWN")
    elif candidate_state == "NOT_READY":
        blockers.append("CROSS_SURFACE_VISUAL_BINDING_NOT_READY")
    else:
        blockers.append("CROSS_SURFACE_VISUAL_BINDING_DIVERGENCE")
    return blockers


def _transaction_blockers(transaction: dict[str, Any]) -> list[str]:
    reason = str(transaction.get("terminal_reason") or "")
    mapping = {
        "BLOCKED_FACT_KERNEL_EVIDENCE": "FACT_KERNEL_EVIDENCE_MISSING",
        "BLOCKED_INVALID_FACT_KERNEL": "FACT_KERNEL_INVALID",
        "BLOCKED_EXPLICIT_ARTICLE_CLAIMS_EVIDENCE": "ARTICLE_CLAIMS_EVIDENCE_MISSING",
        "BLOCKED_EDITORIAL_INTEGRITY": "EDITORIAL_INTEGRITY_FAILED",
    }
    if reason in mapping:
        return [mapping[reason]]
    if reason == "BLOCKED_EXTERNAL_DELIVERY_EVIDENCE":
        return ["EXTERNAL_DELIVERY_BLOCKED"]
    if reason and reason != "AUDIT_REPLAY_READY":
        return ["TRANSACTION_REPLAY_BLOCKED"]
    return []


def build_report(
    candidates: dict[str, Any],
    receipts: dict[str, Any],
    transactions: dict[str, Any],
) -> dict[str, Any]:
    candidate_rows = _rows_by_story(candidates)
    receipt_rows = _rows_by_story(receipts)
    transaction_rows = _rows_by_story(transactions)
    story_ids = [str(value) for value in candidates.get("first_ten_candidate_ids") or []]

    rows: list[dict[str, Any]] = []
    blocker_counts: Counter[str] = Counter()
    truth_complete = 0
    explicit_external_blockers = {
        "SITE_READBACK_FAILED",
        "VISUAL_ARTICLE_BINDING_FAILED",
        "VISUAL_PUBLIC_IMAGE_FAILED",
        "VISUAL_PROVENANCE_FAILED",
        "VISUAL_READBACK_FAILED",
        "VISUAL_INTERNAL_GATE_FAILED",
        "SITE_VISUAL_ARTICLE_TRANSPORT_FAILED",
        "SITE_APPROVED_VISUAL_ABSENT",
        "SITE_APPROVED_VISUAL_TRANSPORT_FAILED",
        "VISUAL_PROVENANCE_TRANSPORT_FAILED",
        "VISUAL_PROVENANCE_FIELDS_MISSING",
        "FACEBOOK_READBACK_PERMISSION_MISSING",
        "FACEBOOK_READBACK_FAILED",
        "INSTAGRAM_READBACK_FAILED",
        "INSTAGRAM_REMOTE_VISUAL_READBACK_FAILED",
        "INSTAGRAM_VISUAL_IDENTITY_UNBOUND",
    }
    for story_id in story_ids:
        candidate = candidate_rows.get(story_id) or {}
        receipt_row = receipt_rows.get(story_id) or {}
        transaction = transaction_rows.get(story_id) or {}
        channel_receipts = receipt_row.get("receipts") if isinstance(receipt_row.get("receipts"), dict) else {}
        blockers: list[str] = []
        owner_actions: list[str] = []

        visual = channel_receipts.get("visual") if isinstance(channel_receipts.get("visual"), dict) else {}
        blockers.extend(_cross_surface_visual_blockers(candidate, visual))

        site = channel_receipts.get("site") if isinstance(channel_receipts.get("site"), dict) else {}
        if not (site.get("status") == "DELIVERED" and site.get("readback_ok") is True):
            blockers.append("SITE_READBACK_FAILED")

        blockers.extend(_visual_blockers(visual))

        facebook = channel_receipts.get("facebook") if isinstance(channel_receipts.get("facebook"), dict) else {}
        fb_blockers, fb_owner_action = _facebook_blockers(facebook)
        blockers.extend(fb_blockers)
        if fb_owner_action:
            owner_actions.append(fb_owner_action)

        instagram = channel_receipts.get("instagram") if isinstance(channel_receipts.get("instagram"), dict) else {}
        blockers.extend(_instagram_blockers(instagram))

        transaction_blockers = _transaction_blockers(transaction)
        if "EXTERNAL_DELIVERY_BLOCKED" in transaction_blockers and any(
            value in explicit_external_blockers for value in blockers
        ):
            transaction_blockers = [value for value in transaction_blockers if value != "EXTERNAL_DELIVERY_BLOCKED"]
        blockers.extend(transaction_blockers)

        blockers = list(dict.fromkeys(blockers))
        owner_actions = list(dict.fromkeys(owner_actions))
        blocker_counts.update(blockers)
        if not blockers:
            truth_complete += 1

        candidate_state = candidate.get("canonical_site_visual_binding_state")
        receipt_state = visual.get("canonical_site_visual_binding_state")
        rows.append(
            {
                "story_id": story_id,
                "publication_authority": "NONE",
                "truth_state": "REPLAY_TRUTH_COMPLETE" if not blockers else "BLOCKED",
                "blockers": blockers,
                "owner_actions": owner_actions,
                "canonical_site_visual_binding_state": candidate_state,
                "receipt_canonical_site_visual_binding_state": receipt_state,
                "canonical_site_visual_binding_state_match": candidate_state == receipt_state,
                "canonical_site_visual_filename_match": candidate.get("canonical_site_visual_filename_match"),
                "canonical_site_visual_source_match": candidate.get("canonical_site_visual_source_match"),
                "canonical_site_visual_rights_match": candidate.get("canonical_site_visual_rights_match"),
                "canonical_site_visual_provenance_verified": candidate.get("canonical_site_visual_provenance_verified"),
                "site_status": site.get("status"),
                "visual_status": visual.get("status"),
                "visual_truth_state": visual.get("visual_truth_state"),
                "visual_failure_classification": visual.get("failure_classification"),
                "visual_failure_domain": visual.get("failure_domain"),
                "facebook_status": facebook.get("status"),
                "instagram_status": instagram.get("status"),
                "instagram_remote_visual_readback_ok": instagram.get("remote_visual_readback_ok"),
                "instagram_remote_visual_identity_bound": instagram.get("remote_visual_identity_bound"),
                "transaction_terminal_reason": transaction.get("terminal_reason"),
            }
        )

    return {
        "schema_version": "1.4",
        "mode": "SHADOW_TRUTH_GATE_REPORT",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "candidate_count": len(story_ids),
        "truth_complete_count": truth_complete,
        "blocked_count": len(story_ids) - truth_complete,
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "rows": rows,
        "truth_rule": "A green workflow, internal ID, outbox item, legacy published flag or internal visual assignment never satisfies external truth; replay candidates require a CONSISTENT canonical social-visual/site-manifest binding, receipt state must preserve that binding, visual failures preserve explicit content-versus-transport classification, and Instagram requires both remote image readback and explicit identity binding to the approved visual.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify Core v2 shadow truth blockers")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--receipts", required=True)
    parser.add_argument("--transactions", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build_report(_load(args.candidates), _load(args.receipts), _load(args.transactions))
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "candidate_count": report["candidate_count"],
                "truth_complete_count": report["truth_complete_count"],
                "blocker_counts": report["blocker_counts"],
                "acceptance_ready": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
