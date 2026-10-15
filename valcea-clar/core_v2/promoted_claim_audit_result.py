from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from audit_result_contract import AuditResult
from promoted_claim_auditor import audit_documents


def _load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object document: {path}")
    return value


def build_audit_result(
    candidates: dict[str, Any],
    site_readback: dict[str, Any],
    visual_readback: dict[str, Any],
    meta_readback: dict[str, Any],
    instagram_identity: dict[str, Any],
    transactions: dict[str, Any],
) -> dict[str, Any]:
    external = audit_documents(
        candidates,
        site_readback,
        visual_readback,
        meta_readback,
        instagram_identity,
        transactions,
    )
    return AuditResult.from_external_auditor_document(external).as_dict()


def main() -> int:
    parser = argparse.ArgumentParser(description="Canonical source-neutral Core v2 AuditResult shadow projection")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--site-readback", required=True)
    parser.add_argument("--visual-readback", required=True)
    parser.add_argument("--meta-readback", required=True)
    parser.add_argument("--instagram-identity", required=True)
    parser.add_argument("--transactions", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build_audit_result(
        _load(args.candidates),
        _load(args.site_readback),
        _load(args.visual_readback),
        _load(args.meta_readback),
        _load(args.instagram_identity),
        _load(args.transactions),
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metrics = result["metrics"]
    print(json.dumps({
        "status": result["status"],
        "external_truth_complete": result["external_truth_complete"],
        "candidate_count": metrics["candidate_count"],
        "truth_complete_transactions": metrics["truth_complete_transactions"],
        "publication_authority": result["publication_authority"],
        "acceptance_ready": result["acceptance_ready"],
    }, sort_keys=True))
    return 0 if result["status"] == "PASS_SHADOW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
