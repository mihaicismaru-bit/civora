from __future__ import annotations

import argparse
import json
from pathlib import Path

from isj_writer_deadline_projection_comparator import compare_source_specific_projection


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the retired ISJ writer-projection logic only as an independent Core v2 regression comparator"
    )
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--projection", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    fact_kernel = json.loads(Path(args.fact_kernel).read_text(encoding="utf-8"))
    fact_integrity = json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8"))
    projection = json.loads(Path(args.projection).read_text(encoding="utf-8"))

    result = compare_source_specific_projection(
        fact_kernel,
        fact_integrity,
        projection,
        expected_year=args.year,
    )
    result.update({
        "canonical_runtime_dependency": False,
        "execution_role": "INDEPENDENT_CI_REGRESSION_ONLY",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "retirement_performed": False,
    })
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result.get("status"),
        "writer_projection_evidence_id": result.get("writer_projection_evidence_id"),
        "source_specific_identity_equivalent": result.get("source_specific_identity_equivalent", False),
        "source_specific_lineage_equivalent": result.get("source_specific_lineage_equivalent", False),
        "source_specific_authority_flags_equivalent": result.get("source_specific_authority_flags_equivalent", False),
        "canonical_runtime_dependency": False,
        "execution_role": "INDEPENDENT_CI_REGRESSION_ONLY",
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "PASS_SHADOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
