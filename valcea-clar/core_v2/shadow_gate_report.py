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


def _visual_blockers(receipt: dict[str, Any]) -> list[str]:
    if receipt.get("status") == "VERIFIED" and receipt.get("readback_ok") is True:
        return []
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


def _cross_surface_visual_blockers(candidate: dict[str, Any]) -> list[str]:
    """Keep internal cross-surface divergence explicit and fail-closed.

    This does not replace external visual readback. It prevents a real visual
    approved in the social registry from becoming audit-complete when the
    canonical site manifest binds a different asset, no asset, different
    provenance, or when the binding state is absent entirely.
    """
    state = str(candidate.get("canonical_site_visual_binding_state") or "").strip()
    if state == "CONSISTENT":
        return []
    if not state:
        return ["CROSS_SURFACE_VISUAL_BINDING_UNKNOWN"]
    if state == "NOT_READY":
        return ["CROSS_SURFACE_VISUAL_BINDING_NOT_READY"]
    return ["CROSS_SURFACE_VISUAL_BINDING_DIVERGENCE"]


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
    for story_id in story_ids:
        candidate = candidate_rows.get(story_id) or {}
        receipt_row = receipt_rows.get(story_id) or {}
        transaction = transaction_rows.get(story_id) or {}
        channel_receipts = receipt_row.get("receipts") if isinstance(receipt_row.get("receipts"), dict) else {}
        blockers: list[str] = []
        owner_actions: list[str] = []

        blockers.extend(_cross_surface_visual_blockers(candidate))

        site = channel_receipts.get("site") if isinstance(channel_receipts.get("site"), dict) else {}
        if not (site.get("status") == "DELIVERED" and site.get("readback_ok") is True):
            blockers.append("SITE_READBACK_FAILED")

        visual = channel_receipts.get("visual") if isinstance(channel_receipts.get("visual"), dict) else {}
        blockers.extend(_visual_blockers(visual))

        facebook = channel_receipts.get("facebook") if isinstance(channel_receipts.get("facebook"), dict) else {}
        fb_blockers, fb_owner_action = _facebook_blockers(facebook)
        blockers.extend(fb_blockers)
        if fb_owner_action:
            owner_actions.append(fb_owner_action)

        instagram = channel_receipts.get("instagram") if isinstance(channel_receipts.get("instagram"), dict) else {}
        if not (instagram.get("status") == "DELIVERED" and instagram.get("readback_ok") is True):
            blockers.append("INSTAGRAM_READBACK_FAILED")

        transaction_blockers = _transaction_blockers(transaction)
        if "EXTERNAL_DELIVERY_BLOCKED" in transaction_blockers and any(
            value in blockers
            for value in (
                "SITE_READBACK_FAILED",
                "VISUAL_ARTICLE_BINDING_FAILED",
                "VISUAL_PUBLIC_IMAGE_FAILED",
                "VISUAL_PROVENANCE_FAILED",
                "VISUAL_READBACK_FAILED",
                "FACEBOOK_READBACK_PERMISSION_MISSING",
                "FACEBOOK_READBACK_FAILED",
                "INSTAGRAM_READBACK_FAILED",
            )
        ):
            transaction_blockers = [value for value in transaction_blockers if value != "EXTERNAL_DELIVERY_BLOCKED"]
        blockers.extend(transaction_blockers)

        blockers = list(dict.fromkeys(blockers))
        owner_actions = list(dict.fromkeys(owner_actions))
        blocker_counts.update(blockers)
        if not blockers:
            truth_complete += 1

        rows.append(
            {
                "story_id": story_id,
                "publication_authority": "NONE",
                "truth_state": "REPLAY_TRUTH_COMPLETE" if not blockers else "BLOCKED",
                "blockers": blockers,
                "owner_actions": owner_actions,
                "canonical_site_visual_binding_state": candidate.get("canonical_site_visual_binding_state"),
                "canonical_site_visual_filename_match": candidate.get("canonical_site_visual_filename_match"),
                "canonical_site_visual_source_match": candidate.get("canonical_site_visual_source_match"),
                "canonical_site_visual_rights_match": candidate.get("canonical_site_visual_rights_match"),
                "canonical_site_visual_provenance_verified": candidate.get("canonical_site_visual_provenance_verified"),
                "site_status": site.get("status"),
                "visual_status": visual.get("status"),
                "facebook_status": facebook.get("status"),
                "instagram_status": instagram.get("status"),
                "transaction_terminal_reason": transaction.get("terminal_reason"),
            }
        )

    return {
        "schema_version": "1.1",
        "mode": "SHADOW_TRUTH_GATE_REPORT",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "candidate_count": len(story_ids),
        "truth_complete_count": truth_complete,
        "blocked_count": len(story_ids) - truth_complete,
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "rows": rows,
        "truth_rule": "A green workflow, internal ID, outbox item, legacy published flag or internal visual assignment never satisfies external truth; replay candidates also require a CONSISTENT canonical social-visual/site-manifest binding.",
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
