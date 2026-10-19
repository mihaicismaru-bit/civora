from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object document: {path}")
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _rows_by_story(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("story_id") or ""): row
        for row in document.get("rows") or []
        if isinstance(row, dict) and str(row.get("story_id") or "").strip()
    }


def _compose_body(kernel: dict[str, Any]) -> str:
    claims = [str(value).strip() for value in kernel.get("claims") or [] if str(value).strip()]
    parts = [
        str(kernel.get("what") or "").strip(),
        f"Informația verificată îi privește pe {str(kernel.get('who') or '').strip()} și se referă la {str(kernel.get('where') or '').strip()}, cu reperul temporal {str(kernel.get('when') or '').strip()}.",
        str(kernel.get("why_it_matters") or "").strip(),
        "Faptele materiale legate direct de dovezi sunt: " + " ".join(claims),
        f"Sursa factuală folosită pentru acest replay este {str(kernel.get('source') or '').strip()}.",
    ]
    return "\n\n".join(part for part in parts if part)


def build(candidates: dict[str, Any], kernels: dict[str, Any]) -> dict[str, Any]:
    story_ids = [str(value) for value in candidates.get("first_ten_candidate_ids") or []]
    kernel_rows = _rows_by_story(kernels)
    rows: list[dict[str, Any]] = []
    ready_count = 0

    for story_id in story_ids:
        source_row = kernel_rows.get(story_id) or {}
        row: dict[str, Any] = {
            "story_id": story_id,
            "publication_authority": "NONE",
            "live_promotion_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "article_claims_evidence_ready": False,
            "state": "BLOCKED_FACT_KERNEL_NOT_READY",
            "blockers": [],
        }

        if source_row.get("fact_kernel_evidence_ready") is not True:
            row["blockers"] = ["fact_kernel_evidence_not_ready"]
            rows.append(row)
            continue

        kernel = source_row.get("fact_kernel")
        if not isinstance(kernel, dict):
            row["blockers"] = ["fact_kernel_missing"]
            rows.append(row)
            continue

        kernel_claims = [str(value).strip() for value in kernel.get("claims") or [] if str(value).strip()]
        kernel_evidence_ids = {str(value) for value in kernel.get("evidence_ids") or [] if str(value)}
        evidence_index = {
            str(item.get("evidence_id")): item
            for item in source_row.get("evidence") or []
            if isinstance(item, dict) and str(item.get("evidence_id") or "").strip()
        }
        bindings = source_row.get("claim_evidence") or []
        binding_by_index: dict[int, list[dict[str, Any]]] = {}
        for binding in bindings:
            if not isinstance(binding, dict) or not isinstance(binding.get("claim_index"), int):
                continue
            binding_by_index.setdefault(int(binding["claim_index"]), []).append(binding)

        article_claims: list[dict[str, Any]] = []
        blockers: list[str] = []
        for claim_index, claim_text in enumerate(kernel_claims):
            matching = binding_by_index.get(claim_index) or []
            if len(matching) != 1:
                blockers.append(f"claim:{claim_index}:binding_cardinality")
                continue
            binding = matching[0]
            if str(binding.get("claim") or "").strip() != claim_text:
                blockers.append(f"claim:{claim_index}:binding_text_mismatch")
                continue

            evidence_ids = [str(value) for value in binding.get("evidence_ids") or [] if str(value)]
            if not evidence_ids:
                blockers.append(f"claim:{claim_index}:missing_evidence_ids")
                continue
            if not set(evidence_ids).issubset(kernel_evidence_ids):
                blockers.append(f"claim:{claim_index}:evidence_not_in_kernel")
                continue

            evidence_fingerprints: list[dict[str, Any]] = []
            evidence_valid = True
            for evidence_id in evidence_ids:
                evidence = evidence_index.get(evidence_id)
                if not isinstance(evidence, dict):
                    blockers.append(f"claim:{claim_index}:unknown_evidence:{evidence_id}")
                    evidence_valid = False
                    continue
                if evidence.get("verified") is not True:
                    blockers.append(f"claim:{claim_index}:unverified_evidence:{evidence_id}")
                    evidence_valid = False
                if evidence.get("kind") != "CLAIM_EVIDENCE":
                    blockers.append(f"claim:{claim_index}:wrong_evidence_kind:{evidence_id}")
                    evidence_valid = False
                if evidence.get("claim_index") != claim_index:
                    blockers.append(f"claim:{claim_index}:evidence_index_mismatch:{evidence_id}")
                    evidence_valid = False
                if str(evidence.get("claim") or "").strip() != claim_text:
                    blockers.append(f"claim:{claim_index}:evidence_text_mismatch:{evidence_id}")
                    evidence_valid = False
                evidence_fingerprints.append(
                    {
                        "evidence_id": evidence_id,
                        "source_url": evidence.get("source_url"),
                        "source_content_sha256": evidence.get("source_content_sha256"),
                    }
                )
            if not evidence_valid:
                continue

            article_claims.append(
                {
                    "text": claim_text,
                    "kernel_claim_index": claim_index,
                    "evidence_ids": evidence_ids,
                    "evidence_fingerprints": evidence_fingerprints,
                }
            )

        if len(article_claims) != len(kernel_claims):
            blockers.append("article_claim_count_mismatch")
        if blockers:
            row["state"] = "BLOCKED_CLAIM_EVIDENCE_BINDING"
            row["blockers"] = list(dict.fromkeys(blockers))
            rows.append(row)
            continue

        package = {
            "article_id": story_id,
            "writer_id": "historical_replay_shadow_editorial_v1",
            "body": _compose_body(kernel),
            "claims": article_claims,
            "source_url": kernel.get("source_url"),
            "kernel_fingerprint_sha256": _canonical_hash(kernel),
            "publication_authority": "NONE",
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        }
        if len(package["body"]) < 180:
            row["state"] = "BLOCKED_ARTICLE_BODY_TOO_SHORT"
            row["blockers"] = ["article_body_too_short"]
            rows.append(row)
            continue

        row["article_package"] = package
        row["kernel_fingerprint_sha256"] = package["kernel_fingerprint_sha256"]
        row["verified_claim_count"] = len(article_claims)
        row["article_claims_evidence_ready"] = True
        row["state"] = "ARTICLE_CLAIMS_EVIDENCE_READY_SHADOW"
        ready_count += 1
        rows.append(row)

    return {
        "schema_version": "1.0",
        "mode": "READ_ONLY_HISTORICAL_ARTICLE_CLAIMS_EVIDENCE",
        "publication_authority": "NONE",
        "live_promotion_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "candidate_count": len(rows),
        "article_claims_evidence_ready_count": ready_count,
        "truth_rule": "A historical replay article package may exist only when every article claim is an exact FactKernel claim and its claim_index/evidence_ids resolve to verified CLAIM_EVIDENCE from the same evidence-bound kernel. This artifact is shadow-only and grants no publication authority.",
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build claim-by-claim historical article packages for Core v2 shadow replay")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--kernels", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build(_load(args.candidates), _load(args.kernels))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "candidate_count": result["candidate_count"],
                "article_claims_evidence_ready_count": result["article_claims_evidence_ready_count"],
                "states": {row["story_id"]: row["state"] for row in result["rows"]},
                "publication_authority": "NONE",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
