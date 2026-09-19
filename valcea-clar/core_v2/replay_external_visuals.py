from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from build_shadow_candidate_ledger import build
from visual_readback import read_visual


def _binding_context(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_site_visual_binding_state": row.get("canonical_site_visual_binding_state"),
        "canonical_site_image_bound": row.get("canonical_site_image_bound") is True,
        "canonical_site_expected_visual_filename": row.get("canonical_site_expected_visual_filename"),
        "canonical_site_observed_visual_filename": row.get("canonical_site_observed_visual_filename"),
        "canonical_site_visual_filename_match": row.get("canonical_site_visual_filename_match") is True,
        "canonical_site_visual_source_match": row.get("canonical_site_visual_source_match") is True,
        "canonical_site_visual_rights_match": row.get("canonical_site_visual_rights_match") is True,
        "canonical_site_visual_provenance_verified": row.get("canonical_site_visual_provenance_verified") is True,
    }


def replay(limit: int = 10) -> dict[str, Any]:
    ledger = build()
    candidate_ids = list(ledger.get("first_ten_candidate_ids") or [])[:limit]
    wanted = set(candidate_ids)
    rows = [row for row in ledger.get("rows") or [] if row.get("story_id") in wanted]
    results: list[dict[str, Any]] = []

    for row in rows:
        story_id = str(row.get("story_id") or "")
        article_url = str(row.get("canonical_url") or "")
        image_path = str(row.get("visual_image_path") or "")
        source_url = str(row.get("visual_source_url") or "")
        rights_basis = str(row.get("visual_rights_basis") or "")
        binding_context = _binding_context(row)
        if not article_url or not image_path or not source_url or not rights_basis:
            results.append(
                {
                    "story_id": story_id,
                    "status": "BLOCKED",
                    "reason": "missing_visual_provenance_fields",
                    "readback_ok": False,
                    "publication_authority": "NONE",
                    "visual_truth_state": "MISSING_VISUAL_PROVENANCE_FIELDS",
                    "failure_classification": "MISSING_VISUAL_PROVENANCE_FIELDS",
                    "failure_domain": "INTERNAL_GATE",
                    **binding_context,
                }
            )
            continue
        result = read_visual(
            article_url=article_url,
            image_path=image_path,
            source_url=source_url,
            direct_source_url=row.get("visual_direct_source_url"),
            rights_basis=rights_basis,
            internal_real_visual_evidence=row.get("real_visual_internal_evidence") is True,
        )
        results.append({"story_id": story_id, **binding_context, **result})

    passed = sum(1 for row in results if row.get("readback_ok") is True)
    canonical_consistent = sum(
        1 for row in results if row.get("canonical_site_visual_binding_state") == "CONSISTENT"
    )
    cross_surface_divergent = sum(
        1
        for row in results
        if row.get("canonical_site_visual_binding_state")
        not in {None, "CONSISTENT", "NOT_READY"}
    )
    failure_class_counts = dict(
        sorted(
            Counter(
                str(row.get("failure_classification"))
                for row in results
                if row.get("failure_classification")
            ).items()
        )
    )
    failure_domain_counts = dict(
        sorted(
            Counter(
                str(row.get("failure_domain"))
                for row in results
                if row.get("failure_domain")
            ).items()
        )
    )
    return {
        "schema_version": "1.2",
        "mode": "READ_ONLY_VISUAL_REPLAY",
        "publication_authority": "NONE",
        "truth_rule": "external public HTML/image/provenance readback remains authoritative; canonical cross-surface binding is reported independently and cannot manufacture a pass; site content absence is classified separately from site/provenance transport failure without changing acceptance semantics",
        "candidate_count": len(rows),
        "canonical_consistent_count": canonical_consistent,
        "cross_surface_divergent_count": cross_surface_divergent,
        "site_approved_visual_absent_count": int(failure_class_counts.get("SITE_APPROVED_VISUAL_ABSENT", 0)),
        "transport_failure_count": sum(
            count
            for domain, count in failure_domain_counts.items()
            if domain in {"SITE_TRANSPORT", "PROVENANCE_TRANSPORT"}
        ),
        "failure_class_counts": failure_class_counts,
        "failure_domain_counts": failure_domain_counts,
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only visual replay for Core v2 shadow candidates")
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    result = replay(max(0, min(args.limit, 10)))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "candidate_count": result["candidate_count"],
                "canonical_consistent_count": result["canonical_consistent_count"],
                "cross_surface_divergent_count": result["cross_surface_divergent_count"],
                "site_approved_visual_absent_count": result["site_approved_visual_absent_count"],
                "transport_failure_count": result["transport_failure_count"],
                "passed": result["passed"],
                "failed": result["failed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
