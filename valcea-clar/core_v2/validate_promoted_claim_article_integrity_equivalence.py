from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from isj_article_integrity import verify_isj_article_integrity
from orchestrator import bounded_cycle_plan, _article_integrity_stage_ownership_snapshot
from promoted_claim_article_integrity import verify_promoted_claim_article_integrity


SOURCE_NEUTRAL_FACADE = "valcea-clar/core_v2/promoted_claim_article_integrity.py"
RETAINED_IMPLEMENTATION = "valcea-clar/core_v2/isj_article_integrity.py"
INTEGRITY_STAGE = "isj_article_integrity"
INTEGRITY_ARTIFACT = "valcea-core-v2-isj-article-integrity-shadow.json"
EXPECTED_ARTICLE_CLAIM_ID = "isj-article-deadline-claim-cc6330d494a44bd79c5340d5"
EXTRACTED_STAGE = "isj_promoted_claim_contract_validation"


def _semantic_sha(doc: dict[str, Any]) -> str:
    payload = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _assert_non_authorizing(doc: dict[str, Any], label: str) -> None:
    assert doc.get("publication_authority") == "NONE", f"{label}:publication_authority"
    assert doc.get("acceptance_ready") is False, f"{label}:acceptance_ready"
    assert doc.get("production_writer_ready") is False, f"{label}:production_writer_ready"
    assert doc.get("site_publish_allowed") is False, f"{label}:site_publish_allowed"
    assert doc.get("social_publish_allowed") is False, f"{label}:social_publish_allowed"


def _tamper_cases(article: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    cases: list[tuple[str, dict[str, Any]]] = []
    headline = copy.deepcopy(article)
    headline["articles"][0]["article_package"]["headline"] = "TAMPERED HEADLINE"
    cases.append(("headline", headline))

    claim_id = copy.deepcopy(article)
    package = claim_id["articles"][0]["article_package"]
    promoted = package["claims"][-1]
    promoted["article_deadline_claim_evidence_id"] = "tampered-article-claim-id"
    for segment in package.get("body_segments") or []:
        if isinstance(segment, dict) and segment.get("kind") == "promoted_fact_claim":
            segment["article_deadline_claim_evidence_id"] = "tampered-article-claim-id"
    claim_id["article_deadline_claim_evidence_id"] = "tampered-article-claim-id"
    cases.append(("article_claim_evidence_id", claim_id))

    extra_claim = copy.deepcopy(article)
    extra_claim["articles"][0]["article_package"]["claims"].append({
        "text": "Claim never present in the verified FactKernel.",
        "field_evidence_ids": [],
    })
    cases.append(("extra_claim", extra_claim))
    return cases


def _validate_plan_switched() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="core-v2-article-integrity-plan-") as raw_tmp:
        plan = bounded_cycle_plan(Path(raw_tmp), live=False)
    by_name = {stage.name: stage for stage in plan}
    names = [stage.name for stage in plan]
    integrity = by_name[INTEGRITY_STAGE]
    validation_index = names.index("isj_article_deadline_claim_validation")
    integrity_index = names.index(INTEGRITY_STAGE)

    assert len(plan) == 41
    assert EXTRACTED_STAGE not in by_name
    assert "core_v2_external_audit" not in by_name
    assert integrity_index == validation_index + 1
    assert len(integrity.argv) > 1 and integrity.argv[1] == SOURCE_NEUTRAL_FACADE
    assert integrity.output is not None and integrity.output.name == INTEGRITY_ARTIFACT
    joined = "\n".join(" ".join(stage.argv) for stage in plan)
    assert SOURCE_NEUTRAL_FACADE in joined
    assert RETAINED_IMPLEMENTATION not in joined
    assert "validate_isj_promoted_claim_contract_runtime.py" not in joined
    assert "valcea-core-v2-isj-promoted-claim-contract-validation.json" not in joined

    ownership = _article_integrity_stage_ownership_snapshot(plan)
    assert ownership.get("status") == "PASS_SHADOW"
    assert ownership.get("canonical_stage_count") == 41
    assert ownership.get("canonical_runtime_switched") is True
    assert ownership.get("source_neutral_facade_present_in_canonical_plan") is True
    assert ownership.get("retained_integrity_runtime_dependency") is False
    assert ownership.get("retained_integrity_regression_component") is True
    assert ownership.get("retained_integrity_retirement_eligible") is False
    assert ownership.get("publication_authority") == "NONE"
    assert ownership.get("acceptance_ready") is False

    return {
        "canonical_stage_count": len(plan),
        "ci_only_contract_validation_extracted": True,
        "external_auditor_inserted": False,
        "canonical_integrity_stage_name": integrity.name,
        "canonical_integrity_module": integrity.argv[1],
        "canonical_integrity_artifact": integrity.output.name,
        "canonical_order_validation_integrity_preserved": True,
        "source_neutral_facade_present_in_canonical_plan": True,
        "canonical_runtime_switched": True,
        "retained_implementation_runtime_dependency": False,
        "retained_implementation_regression_only": True,
        "retained_implementation_retirement_eligible": False,
    }


def validate_equivalence(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projected_article: dict[str, Any],
    canonical_integrity: dict[str, Any],
) -> dict[str, Any]:
    retained = verify_isj_article_integrity(fact_kernel, fact_integrity, projected_article)
    facade = verify_promoted_claim_article_integrity(fact_kernel, fact_integrity, projected_article)

    assert facade == retained
    assert retained == canonical_integrity
    _assert_non_authorizing(facade, "facade")
    _assert_non_authorizing(retained, "retained")
    _assert_non_authorizing(canonical_integrity, "canonical")

    assert facade.get("status") == "PASS_SHADOW"
    assert facade.get("article_integrity_verified") is True
    assert int(facade.get("verified_article_count") or 0) == 1
    assert int(facade.get("verified_claim_count") or 0) == 3
    assert int(facade.get("fabricated_claim_count") or 0) == 0
    assert facade.get("projected_deadline_verified") is True
    assert facade.get("article_contains_registration_deadline") is True
    assert int(facade.get("canonical_promoted_claim_count") or 0) == 1
    assert facade.get("article_deadline_claim_evidence_id") == EXPECTED_ARTICLE_CLAIM_ID

    tamper_results: list[dict[str, Any]] = []
    for name, tampered in _tamper_cases(projected_article):
        retained_block = verify_isj_article_integrity(fact_kernel, fact_integrity, tampered)
        facade_block = verify_promoted_claim_article_integrity(fact_kernel, fact_integrity, tampered)
        assert facade_block == retained_block
        assert facade_block.get("status") == "BLOCKED"
        assert facade_block.get("article_integrity_verified") is False
        assert int(facade_block.get("fabricated_claim_count") or 0) > 0
        _assert_non_authorizing(facade_block, f"tamper:{name}")
        tamper_results.append({
            "case": name,
            "status": facade_block.get("status"),
            "fabricated_claim_count": int(facade_block.get("fabricated_claim_count") or 0),
            "failures": list(facade_block.get("failures") or []),
        })

    plan = _validate_plan_switched()
    return {
        "schema_version": "core-v2-promoted-claim-article-integrity-post-extraction-equivalence-shadow.v3",
        "status": "PASS_SHADOW",
        "source_neutral_facade": SOURCE_NEUTRAL_FACADE,
        "retained_implementation": RETAINED_IMPLEMENTATION,
        "facade_json_semantic_sha256": _semantic_sha(facade),
        "retained_json_semantic_sha256": _semantic_sha(retained),
        "canonical_json_semantic_sha256": _semantic_sha(canonical_integrity),
        "json_semantic_equivalent": True,
        "article_deadline_claim_evidence_id": facade.get("article_deadline_claim_evidence_id"),
        "verified_article_count": int(facade.get("verified_article_count") or 0),
        "verified_claim_count": int(facade.get("verified_claim_count") or 0),
        "fabricated_claim_count": int(facade.get("fabricated_claim_count") or 0),
        "projected_deadline_verified": facade.get("projected_deadline_verified") is True,
        "fail_closed_tamper_regressions_passed": len(tamper_results),
        "tamper_results": tamper_results,
        **plan,
        "retirement_authority": "NONE",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "truth_rule": (
            "The canonical 41-stage runtime executes the source-neutral promoted_claim_article_integrity facade one-for-one. "
            "Its artifact remains JSON-semantically identical to the retained deterministic ISJ verifier, preserves the same "
            "article-claim evidence identity and 3 verified / 0 fabricated claims, and fails closed under headline, evidence-identity "
            "and extra-claim tampering. The unrelated promoted-claim contract validator remains CI-only and the external auditor "
            "is not inserted. No publication, acceptance, merge, deploy, cutover or retirement authority is granted."
        ),
    }


def _load(path: str) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise TypeError(f"expected_json_object:{path}")
    return doc


def _prove_cli_parity(fact_kernel_path: str, fact_integrity_path: str, article_path: str, expected: dict[str, Any]) -> str:
    with tempfile.TemporaryDirectory(prefix="core-v2-article-integrity-cli-") as raw_tmp:
        out = Path(raw_tmp) / "integrity.json"
        completed = subprocess.run([
            sys.executable, SOURCE_NEUTRAL_FACADE,
            "--fact-kernel", fact_kernel_path,
            "--fact-kernel-integrity", fact_integrity_path,
            "--article", article_path,
            "--output", str(out),
        ], check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"article_integrity_facade_cli_failed:{completed.stderr.strip()}")
        actual = _load(str(out))
        assert actual == expected
        return _semantic_sha(actual)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove post-extraction source-neutral article-integrity runtime parity")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--article", required=True)
    parser.add_argument("--canonical-integrity", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    fact_kernel = _load(args.fact_kernel)
    fact_integrity = _load(args.fact_kernel_integrity)
    article = _load(args.article)
    canonical = _load(args.canonical_integrity)
    report = validate_equivalence(fact_kernel, fact_integrity, article, canonical)
    report["facade_cli_json_semantic_sha256"] = _prove_cli_parity(args.fact_kernel, args.fact_kernel_integrity, args.article, canonical)
    report["facade_cli_parity"] = True

    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "json_semantic_equivalent": True,
        "facade_cli_parity": True,
        "canonical_runtime_switched": True,
        "canonical_stage_count": report["canonical_stage_count"],
        "ci_only_contract_validation_extracted": True,
        "article_deadline_claim_evidence_id": report["article_deadline_claim_evidence_id"],
        "verified_claim_count": report["verified_claim_count"],
        "fabricated_claim_count": report["fabricated_claim_count"],
        "fail_closed_tamper_regressions_passed": report["fail_closed_tamper_regressions_passed"],
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
