from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from isj_article_integrity import verify_isj_article_integrity as verify_retained_article_integrity


RETAINED_IMPLEMENTATION = "valcea-clar/core_v2/isj_article_integrity.py"
FACADE_MODE = "CORE_V2_SOURCE_NEUTRAL_PROMOTED_CLAIM_ARTICLE_INTEGRITY_FACADE"


def _require_non_authorizing(result: dict[str, Any]) -> None:
    if result.get("publication_authority") != "NONE":
        raise ValueError("article_integrity_facade_publication_boundary_violation")
    if result.get("acceptance_ready") is not False:
        raise ValueError("article_integrity_facade_acceptance_boundary_violation")
    if result.get("production_writer_ready") is not False:
        raise ValueError("article_integrity_facade_writer_boundary_violation")
    if result.get("site_publish_allowed") is not False or result.get("social_publish_allowed") is not False:
        raise ValueError("article_integrity_facade_delivery_boundary_violation")


def verify_promoted_claim_article_integrity(
    fact_kernel_report: dict[str, Any],
    fact_integrity: dict[str, Any],
    article_report: dict[str, Any],
) -> dict[str, Any]:
    """Source-neutral compatibility facade for the retained deterministic article-integrity gate.

    This migration layer deliberately returns the retained verifier document unchanged so the
    current evidence namespace, claim accounting and fail-closed semantics stay byte-for-byte
    JSON-semantic compatible. It grants no publication, delivery, acceptance, merge, deploy or
    retirement authority and is not the canonical runtime stage until a later separately proven
    switch.
    """
    result = verify_retained_article_integrity(fact_kernel_report, fact_integrity, article_report)
    if not isinstance(result, dict):
        raise TypeError("article_integrity_facade_retained_verifier_returned_non_object")
    _require_non_authorizing(result)

    if result.get("status") == "PASS_SHADOW":
        if result.get("article_integrity_verified") is not True:
            raise ValueError("article_integrity_facade_pass_without_integrity_verification")
        if int(result.get("verified_article_count") or 0) != 1:
            raise ValueError("article_integrity_facade_verified_article_count_mismatch")
        if int(result.get("verified_claim_count") or 0) != 3:
            raise ValueError("article_integrity_facade_verified_claim_count_mismatch")
        if int(result.get("fabricated_claim_count") or 0) != 0:
            raise ValueError("article_integrity_facade_fabricated_claim_count_nonzero")
        if result.get("article_contains_registration_deadline") is not True:
            raise ValueError("article_integrity_facade_projected_claim_marker_missing")
        if result.get("projected_deadline_verified") is not True:
            raise ValueError("article_integrity_facade_projected_claim_not_verified")
        if int(result.get("canonical_promoted_claim_count") or 0) != 1:
            raise ValueError("article_integrity_facade_promoted_claim_count_mismatch")
        if not str(result.get("article_deadline_claim_evidence_id") or "").strip():
            raise ValueError("article_integrity_facade_article_claim_evidence_id_missing")

    return result


def _load(path: str) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise TypeError(f"expected_json_object:{path}")
    return doc


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Source-neutral Core v2 article-integrity facade. The retained deterministic verifier "
            "remains the implementation during this migration increment; no publication authority is granted."
        )
    )
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--article", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = verify_promoted_claim_article_integrity(
        _load(args.fact_kernel),
        _load(args.fact_kernel_integrity),
        _load(args.article),
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "mode": FACADE_MODE,
        "status": result.get("status"),
        "article_truth_state": result.get("article_truth_state"),
        "verified_article_count": result.get("verified_article_count"),
        "verified_claim_count": result.get("verified_claim_count"),
        "fabricated_claim_count": result.get("fabricated_claim_count"),
        "article_deadline_claim_evidence_id": result.get("article_deadline_claim_evidence_id"),
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "PASS_SHADOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
