from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any


ALLOWED_RIGHTS_BASES = {
    "creative_commons",
    "public_domain",
    "licensed",
    "owned",
    "staff",
    "official_press_with_reuse_rights",
    "reader_with_permission",
}


def _load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object document: {path}")
    return value


def _index(document: dict[str, Any], *, collection: str, key: str) -> dict[str, dict[str, Any]]:
    return {
        str(row.get(key) or ""): row
        for row in document.get(collection) or []
        if isinstance(row, dict) and str(row.get(key) or "").strip()
    }


def _meta_index(document: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(row.get("story_id") or ""), str(row.get("channel") or "")): row
        for row in document.get("results") or []
        if isinstance(row, dict)
        and str(row.get("story_id") or "").strip()
        and str(row.get("channel") or "").strip()
    }


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _latency_seconds(candidate: dict[str, Any], site: dict[str, Any]) -> float | None:
    discovered = next(
        (
            _parse_time(candidate.get(key))
            for key in ("discovered_at", "discovered_at_utc", "discovery_timestamp")
            if candidate.get(key)
        ),
        None,
    )
    published = next(
        (
            _parse_time(site.get(key))
            for key in ("date_published", "published_at", "observed_published_at")
            if site.get(key)
        ),
        None,
    )
    if discovered is None or published is None:
        return None
    try:
        seconds = (published - discovered).total_seconds()
    except TypeError:
        return None
    return seconds if seconds >= 0 else None


def _site_truth(row: dict[str, Any], story_id: str) -> tuple[bool, list[str]]:
    failures: list[str] = []
    expected = str(row.get("expected_story_id") or "")
    if expected != story_id:
        failures.append("SITE_STORY_ID_MISMATCH")
    if int(row.get("http_status") or 0) != 200:
        failures.append("SITE_HTTP_NOT_200")
    if row.get("route_match") is not True:
        failures.append("SITE_ROUTE_NOT_BOUND")
    if row.get("canonical_match") is not True:
        failures.append("SITE_CANONICAL_NOT_BOUND")
    if int(row.get("newsarticle_count") or 0) < 1:
        failures.append("SITE_JSONLD_NEWSARTICLE_MISSING")
    if row.get("newsarticle_story_match") is not True:
        failures.append("SITE_JSONLD_STORY_NOT_BOUND")
    if row.get("readback_ok") is not True:
        failures.append("SITE_READBACK_NOT_OK")
    return not failures, failures


def _visual_truth(candidate: dict[str, Any], row: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    rights_basis = str(row.get("rights_basis") or candidate.get("visual_rights_basis") or "")
    if candidate.get("real_visual_internal_evidence") is not True:
        failures.append("VISUAL_INTERNAL_REAL_PHOTO_GATE_FAILED")
    if rights_basis not in ALLOWED_RIGHTS_BASES:
        failures.append("VISUAL_RIGHTS_BASIS_NOT_ALLOWED")
    if candidate.get("canonical_site_visual_binding_state") != "CONSISTENT":
        failures.append("VISUAL_CANDIDATE_SITE_BINDING_NOT_CONSISTENT")
    if row.get("canonical_site_visual_binding_state") != "CONSISTENT":
        failures.append("VISUAL_READBACK_SITE_BINDING_NOT_CONSISTENT")
    for key in (
        "canonical_site_image_bound",
        "canonical_site_visual_filename_match",
        "canonical_site_visual_source_match",
        "canonical_site_visual_rights_match",
        "canonical_site_visual_provenance_verified",
    ):
        if row.get(key) is not True:
            failures.append(f"VISUAL_{key.upper()}_FAILED")
    if row.get("internal_truth_gate") is not True:
        failures.append("VISUAL_INTERNAL_TRUTH_GATE_FAILED")
    if ((row.get("article") or {}).get("readback_ok")) is not True:
        failures.append("VISUAL_ARTICLE_HTTP_READBACK_FAILED")
    if ((row.get("article_binding") or {}).get("article_image_bound")) is not True:
        failures.append("VISUAL_ARTICLE_IMAGE_NOT_BOUND")
    if ((row.get("public_image") or {}).get("readback_ok")) is not True:
        failures.append("VISUAL_PUBLIC_IMAGE_READBACK_FAILED")
    if ((row.get("provenance_source") or {}).get("readback_ok")) is not True:
        failures.append("VISUAL_PROVENANCE_SOURCE_READBACK_FAILED")
    provenance_asset = row.get("provenance_asset") or {}
    if provenance_asset.get("asset_identity_ok") is not True:
        failures.append("VISUAL_PROVENANCE_ASSET_IDENTITY_FAILED")
    if provenance_asset.get("license_present") is not True:
        failures.append("VISUAL_PROVENANCE_LICENSE_MISSING")
    if row.get("direct_source_effective_ok") is not True:
        failures.append("VISUAL_DIRECT_SOURCE_READBACK_FAILED")
    if row.get("readback_ok") is not True:
        failures.append("VISUAL_READBACK_NOT_OK")
    return not failures, failures


def _social_object_truth(
    channel: str,
    candidate: dict[str, Any],
    row: dict[str, Any],
    identity: dict[str, Any] | None,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    expected_remote_id = str(candidate.get(f"{channel}_remote_id_internal") or "")
    observed_remote_id = str(row.get("observed_remote_id") or "")
    requested_remote_id = str(row.get("remote_id") or "")
    if not expected_remote_id:
        failures.append(f"{channel.upper()}_EXPECTED_REMOTE_ID_MISSING")
    if observed_remote_id != expected_remote_id:
        failures.append(f"{channel.upper()}_REMOTE_ID_MISMATCH")
    if requested_remote_id and requested_remote_id != expected_remote_id:
        failures.append(f"{channel.upper()}_REQUESTED_REMOTE_ID_MISMATCH")
    if row.get("object_readback_ok") is not True:
        failures.append(f"{channel.upper()}_OBJECT_READBACK_FAILED")
    if row.get("readback_ok") is not True:
        failures.append(f"{channel.upper()}_READBACK_FAILED")
    if not str(row.get("permalink") or "").startswith("https://"):
        failures.append(f"{channel.upper()}_PERMALINK_MISSING")

    if channel == "instagram":
        if row.get("remote_visual_readback_ok") is not True:
            failures.append("INSTAGRAM_REMOTE_VISUAL_READBACK_FAILED")
        identity = identity or {}
        if identity.get("identity_bound") is not True:
            failures.append("INSTAGRAM_APPROVED_VISUAL_IDENTITY_UNBOUND")
        if int(identity.get("passing_candidate_count") or 0) != 1:
            failures.append("INSTAGRAM_VISUAL_IDENTITY_NOT_UNIQUE")
        if not str(identity.get("matched_remote_id") or "").strip():
            failures.append("INSTAGRAM_MATCHED_REMOTE_IMAGE_ID_MISSING")

    return not failures, failures


def _transaction_truth(row: dict[str, Any]) -> tuple[int, int, int]:
    integrity = row.get("integrity") if isinstance(row.get("integrity"), dict) else {}
    fabricated = int(integrity.get("fabricated_claims") or 0)
    manual = int(row.get("manual_intervention") or 0)
    terminal = str(row.get("terminal_reason") or "")
    unresolved = int(
        terminal
        in {
            "BLOCKED_FACT_KERNEL_EVIDENCE",
            "BLOCKED_INVALID_FACT_KERNEL",
            "BLOCKED_EXPLICIT_ARTICLE_CLAIMS_EVIDENCE",
            "BLOCKED_EDITORIAL_INTEGRITY",
        }
    )
    return fabricated, manual, unresolved


def audit_documents(
    candidates: dict[str, Any],
    site_readback: dict[str, Any],
    visual_readback: dict[str, Any],
    meta_readback: dict[str, Any],
    instagram_identity: dict[str, Any],
    transactions: dict[str, Any],
) -> dict[str, Any]:
    candidate_rows = [row for row in candidates.get("rows") or [] if isinstance(row, dict)]
    candidate_by_id = {
        str(row.get("story_id") or ""): row
        for row in candidate_rows
        if str(row.get("story_id") or "").strip()
    }
    requested_ids = [str(value) for value in candidates.get("first_ten_candidate_ids") or [] if str(value).strip()]
    site_by_id = _index(site_readback, collection="results", key="expected_story_id")
    visual_by_id = _index(visual_readback, collection="results", key="story_id")
    meta_by_key = _meta_index(meta_readback)
    identity_by_id = _index(instagram_identity, collection="results", key="story_id")
    transaction_by_id = _index(transactions, collection="rows", key="story_id")

    duplicate_count = max(0, len(requested_ids) - len(set(requested_ids)))
    rows: list[dict[str, Any]] = []
    published = 0
    photo_verified = 0
    fb_delivered = 0
    ig_delivered = 0
    fabricated_claims = 0
    manual_intervention = 0
    unresolved_material_signals = 0
    latencies: list[float] = []
    missing_latency_evidence = 0

    for story_id in requested_ids:
        candidate = candidate_by_id.get(story_id) or {}
        site = site_by_id.get(story_id) or {}
        visual = visual_by_id.get(story_id) or {}
        facebook = meta_by_key.get((story_id, "facebook")) or {}
        instagram = meta_by_key.get((story_id, "instagram")) or {}
        identity = identity_by_id.get(story_id) or {}
        transaction = transaction_by_id.get(story_id) or {}

        site_ok, site_failures = _site_truth(site, story_id)
        visual_ok, visual_failures = _visual_truth(candidate, visual)
        fb_ok, fb_failures = _social_object_truth("facebook", candidate, facebook, None)
        ig_ok, ig_failures = _social_object_truth("instagram", candidate, instagram, identity)
        fabricated, manual, unresolved = _transaction_truth(transaction)

        if site_ok:
            published += 1
            latency = _latency_seconds(candidate, site)
            if latency is None:
                missing_latency_evidence += 1
            else:
                latencies.append(latency)
            if visual_ok:
                photo_verified += 1
                if fb_ok:
                    fb_delivered += 1
                if ig_ok:
                    ig_delivered += 1
        fabricated_claims += fabricated
        manual_intervention += manual
        unresolved_material_signals += unresolved

        blockers = list(dict.fromkeys(site_failures + visual_failures + fb_failures + ig_failures))
        rows.append(
            {
                "story_id": story_id,
                "site_published_external": site_ok,
                "approved_photo_external": visual_ok,
                "facebook_delivered_receipt_bound": bool(site_ok and visual_ok and fb_ok),
                "instagram_delivered_receipt_bound": bool(site_ok and visual_ok and ig_ok),
                "fabricated_claims": fabricated,
                "manual_intervention": manual,
                "unresolved_material_signals": unresolved,
                "truth_complete": bool(site_ok and visual_ok and fb_ok and ig_ok and fabricated == 0 and unresolved == 0),
                "blockers": blockers,
            }
        )

    site_denominator = published
    photo_denominator = published
    social_denominator = photo_verified
    metrics = {
        "stories_published": published,
        "discovery_to_publish_latency_seconds_median": median(latencies) if latencies else None,
        "discovery_to_publish_latency_observed_count": len(latencies),
        "discovery_to_publish_latency_missing_evidence_count": missing_latency_evidence,
        "photo_coverage": 0.0 if photo_denominator == 0 else photo_verified / photo_denominator,
        "photo_verified_count": photo_verified,
        "facebook_delivered_receipt_bound": fb_delivered,
        "facebook_delivery_rate_receipt_bound": 0.0 if social_denominator == 0 else fb_delivered / social_denominator,
        "instagram_delivered_receipt_bound": ig_delivered,
        "instagram_delivery_rate_receipt_bound": 0.0 if social_denominator == 0 else ig_delivered / social_denominator,
        "duplicates": duplicate_count,
        "fabricated_claims": fabricated_claims,
        "unresolved_material_signals": unresolved_material_signals,
        "manual_intervention": manual_intervention,
        "truth_complete_transactions": sum(1 for row in rows if row["truth_complete"]),
        "candidate_count": len(requested_ids),
    }
    external_blocker_count = sum(1 for row in rows if row["blockers"])
    return {
        "schema_version": "core-v2-independent-auditor-shadow.v1",
        "mode": "SHADOW_EXTERNAL_TRUTH_AUDITOR",
        "status": "PASS_SHADOW" if requested_ids else "BLOCKED_NO_CANDIDATES",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "cutover_authority": "NONE",
        "retirement_authority": "NONE",
        "external_truth_complete": bool(requested_ids and external_blocker_count == 0 and metrics["truth_complete_transactions"] == len(requested_ids)),
        "external_blocked_story_count": external_blocker_count,
        "metrics": metrics,
        "rows": rows,
        "truth_rule": (
            "This auditor derives truth from raw public site HTTP/route/canonical/NewsArticle evidence, public approved-photo/provenance evidence, "
            "raw remote Meta object readback and independent Instagram pixel identity evidence. It does not use internal outbox/delivered flags, "
            "materialized receipt status, workflow success or gate-report status as external truth. Missing or contradictory evidence fails closed."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Source-neutral independent external-truth auditor for CIVORA Core v2 shadow evidence")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--site-readback", required=True)
    parser.add_argument("--visual-readback", required=True)
    parser.add_argument("--meta-readback", required=True)
    parser.add_argument("--instagram-identity", required=True)
    parser.add_argument("--transactions", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit_documents(
        _load(args.candidates),
        _load(args.site_readback),
        _load(args.visual_readback),
        _load(args.meta_readback),
        _load(args.instagram_identity),
        _load(args.transactions),
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "external_truth_complete": result["external_truth_complete"], **result["metrics"]}, sort_keys=True))
    return 0 if result["status"] == "PASS_SHADOW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
