from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from isj_writer_deadline_projection_comparator import compare_source_specific_projection
from isj_writer_shadow_lane import compose_isj_article
from promoted_claim_writer import compose_promoted_claim_article
from validate_shadow_runtime import validate


RUNTIME_FILES = (
    "valcea-core-v2-apavil-shadow.json",
    "valcea-core-v2-ipj-shadow.json",
    "valcea-core-v2-isu-shadow.json",
    "valcea-core-v2-municipal-shadow.json",
    "valcea-core-v2-municipal-documents.json",
    "valcea-core-v2-municipal-materiality.json",
    "valcea-core-v2-municipal-fact-kernels.json",
    "valcea-core-v2-municipal-articles.json",
    "valcea-core-v2-cj-road-shadow.json",
    "valcea-core-v2-eta-shadow.json",
    "valcea-core-v2-isj-shadow.json",
    "valcea-core-v2-isj-detail-shadow.json",
    "valcea-core-v2-isj-materiality-shadow.json",
    "valcea-core-v2-isj-embedded-notice-shadow.json",
    "valcea-core-v2-isj-fact-kernel-shadow.json",
    "valcea-core-v2-isj-fact-kernel-integrity-shadow.json",
    "valcea-core-v2-isj-article-shadow.json",
    "valcea-core-v2-isj-article-integrity-shadow.json",
    "valcea-core-v2-photo-truth.json",
    "valcea-core-v2-shadow-site-package.json",
    "valcea-core-v2-shadow-candidates.json",
    "valcea-core-v2-site-readback.json",
    "valcea-core-v2-visual-readback.json",
    "valcea-core-v2-meta-readback.json",
    "valcea-core-v2-shadow-receipts.json",
    "valcea-core-v2-shadow-transactions.json",
    "valcea-core-v2-gate-report.json",
)

EXPECTED_WRITER_PROJECTION_EVIDENCE_ID = "isj-writer-deadline-projection-d9ae7b38596fc02a6ee7524d"
EXPECTED_WRITER_CONSUMPTION_EVIDENCE_ID = "isj-writer-deadline-consumption-de8b3ece2713d4395a0c62d1"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _canonical_sha256(doc: dict[str, Any]) -> str:
    payload = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _assert_non_authorizing_tree(value: Any) -> None:
    if isinstance(value, dict):
        if "publication_authority" in value:
            assert value.get("publication_authority") == "NONE"
        for key in (
            "acceptance_ready",
            "production_writer_ready",
            "site_publish_allowed",
            "social_publish_allowed",
            "article_projection_allowed",
        ):
            if key in value:
                assert value.get(key) is False
        for child in value.values():
            _assert_non_authorizing_tree(child)
    elif isinstance(value, list):
        for child in value:
            _assert_non_authorizing_tree(child)


def _run_writer_facade_equivalence_regression(base: Path) -> dict[str, Any]:
    """Prove the source-neutral facade is semantically identical to the retained writer.

    The canonical runtime has already succeeded before this regression is called.
    This proof runs the facade and retained implementation independently over the
    same verified runtime inputs, compares exact JSON semantics, checks evidence
    identity and authority boundaries, and grants no publication authority.
    """
    fact_kernel = _load(base / "valcea-core-v2-isj-fact-kernel-shadow.json")
    fact_integrity = _load(base / "valcea-core-v2-isj-fact-kernel-integrity-shadow.json")
    writer_consumption = _load(base / "valcea-core-v2-promoted-claim-writer-consumption.json")
    writer_consumption_validation = _load(base / "valcea-core-v2-promoted-claim-writer-consumption-validation.json")

    assert writer_consumption.get("writer_projection_evidence_id") == EXPECTED_WRITER_PROJECTION_EVIDENCE_ID
    assert writer_consumption.get("writer_consumption_evidence_id") == EXPECTED_WRITER_CONSUMPTION_EVIDENCE_ID
    assert writer_consumption_validation.get("writer_projection_evidence_id") == EXPECTED_WRITER_PROJECTION_EVIDENCE_ID
    assert writer_consumption_validation.get("writer_consumption_evidence_id") == EXPECTED_WRITER_CONSUMPTION_EVIDENCE_ID

    facade = compose_promoted_claim_article(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
    )
    retained = compose_isj_article(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
    )

    assert isinstance(facade, dict) and isinstance(retained, dict)
    assert facade == retained, "writer facade and retained implementation diverged semantically"
    _assert_non_authorizing_tree(facade)
    _assert_non_authorizing_tree(retained)

    assert facade.get("state") == "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY"
    assert facade.get("shadow_writer_executed") is True
    assert int(facade.get("article_count") or 0) == 1
    assert int(facade.get("fabricated_claim_count") or 0) == 0
    assert facade.get("writer_consumes_deadline_projection") is True
    assert int(facade.get("rendered_promoted_claim_count") or 0) == 1

    articles = facade.get("articles") or []
    assert len(articles) == 1 and isinstance(articles[0], dict)
    package = articles[0].get("article_package") or {}
    base_claims = package.get("claims") or []
    pending = package.get("rendered_promoted_claims_pending_integrity") or []
    assert len(base_claims) == 2
    assert len(pending) == 1 and isinstance(pending[0], dict)
    pending_claim = pending[0]
    assert pending_claim.get("writer_projection_evidence_id") == EXPECTED_WRITER_PROJECTION_EVIDENCE_ID
    assert pending_claim.get("writer_consumption_evidence_id") == EXPECTED_WRITER_CONSUMPTION_EVIDENCE_ID

    semantic_sha = _canonical_sha256(facade)
    result = {
        "schema_version": "core-v2-writer-facade-equivalence-shadow.v1",
        "status": "PASS_SHADOW",
        "semantic_equivalent": True,
        "facade_module": "valcea-clar/core_v2/promoted_claim_writer.py",
        "retained_writer_module": "valcea-clar/core_v2/isj_writer_shadow_lane.py",
        "same_verified_runtime_inputs": True,
        "canonical_json_sha256": semantic_sha,
        "facade_json_sha256": semantic_sha,
        "retained_json_sha256": _canonical_sha256(retained),
        "writer_projection_evidence_id": EXPECTED_WRITER_PROJECTION_EVIDENCE_ID,
        "writer_consumption_evidence_id": EXPECTED_WRITER_CONSUMPTION_EVIDENCE_ID,
        "base_article_claim_count": len(base_claims),
        "pending_promoted_claim_count": len(pending),
        "fabricated_claim_count": 0,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "canonical_runtime_dependency": False,
        "execution": "INDEPENDENT_CI_REGRESSION_ONLY",
        "truth_rule": (
            "PASS_SHADOW requires exact JSON-semantic identity between the source-neutral writer facade and the retained writer on the same verified runtime inputs, exact writer projection/consumption evidence identities, and fail-closed publication/acceptance authority. This regression is not a canonical orchestrator stage and grants no merge, deployment, publication or acceptance authority."
        ),
    }
    _write(base / "valcea-core-v2-writer-facade-equivalence.json", result)
    print(
        "Independent writer facade equivalence: PASS_SHADOW "
        f"({semantic_sha}; projection={EXPECTED_WRITER_PROJECTION_EVIDENCE_ID}; "
        f"consumption={EXPECTED_WRITER_CONSUMPTION_EVIDENCE_ID})"
    )
    return result


def _case_base(source_base: Path, copied_file: str) -> tuple[tempfile.TemporaryDirectory, Path]:
    td = tempfile.TemporaryDirectory(prefix="valcea-core-v2-negative-")
    case_base = Path(td.name)
    for name in RUNTIME_FILES:
        source = source_base / name
        if not source.is_file():
            td.cleanup()
            raise FileNotFoundError(f"Missing runtime artifact required for negative regression: {source}")
        destination = case_base / name
        if name == copied_file:
            shutil.copy2(source, destination)
        else:
            os.symlink(source.resolve(), destination)
    return td, case_base


def _expect_fail_closed(
    source_base: Path,
    repo: Path,
    target_file: str,
    mutate: Callable[[dict], None],
    label: str,
) -> None:
    td, case_base = _case_base(source_base, target_file)
    try:
        target = case_base / target_file
        doc = _load(target)
        mutate(doc)
        _write(target, doc)
        try:
            validate(case_base, repo)
        except AssertionError:
            print(f"negative runtime regression PASS (fail-closed): {label}")
            return
        raise AssertionError(f"Canonical runtime validator accepted tampered cross-artifact truth: {label}")
    finally:
        td.cleanup()


def _run_independent_isj_projection_comparator(base: Path) -> None:
    """Keep retired source-specific semantics as CI regression only.

    This function runs after the canonical runtime has already validated. It is not
    imported by the canonical projection producer or orchestrator and therefore
    cannot determine whether the 42-stage Core v2 runtime succeeds.
    """
    projection = _load(base / "valcea-core-v2-promoted-claim-writer-projection.json")
    assert projection.get("source_specific_comparator_runtime_dependency") is False
    assert projection.get("source_specific_comparator_execution") == "INDEPENDENT_CI_REGRESSION_ONLY"
    assert projection.get("source_specific_comparator_status") == "NOT_RUN_CANONICAL_PATH"
    assert projection.get("canonical_writer_projection_stage") == "promoted_claim_writer_projection"
    assert projection.get("legacy_module_path_required_for_canonical_runtime") is False

    result = compare_source_specific_projection(
        _load(base / "valcea-core-v2-isj-fact-kernel-shadow.json"),
        _load(base / "valcea-core-v2-isj-fact-kernel-integrity-shadow.json"),
        projection,
        expected_year=2026,
    )
    assert result.get("status") == "PASS_SHADOW", result
    assert result.get("source_specific_identity_equivalent") is True
    assert result.get("source_specific_lineage_equivalent") is True
    assert result.get("source_specific_authority_flags_equivalent") is True
    assert result.get("writer_projection_evidence_id") == projection.get("writer_projection_evidence_id")
    assert result.get("publication_authority") == "NONE"
    assert result.get("acceptance_ready") is False
    print(
        "Independent retired ISJ writer-projection comparator: PASS_SHADOW "
        f"({result.get('writer_projection_evidence_id')}); canonical_runtime_dependency=false"
    )


def run(base: Path, repo: Path) -> None:
    # Establish that canonical runtime succeeds first, without the source-specific
    # projection comparator or historical ISJ projection module being executed by
    # the producer path.
    validate(base, repo)

    # Then run independent CI-only regressions. Failure here may fail CI, but these
    # regressions are not canonical orchestrator stages and cannot grant authority.
    _run_independent_isj_projection_comparator(base)
    _run_writer_facade_equivalence_regression(base)

    def mutate_article_kernel_source(doc: dict) -> None:
        doc["articles"][0]["fact_kernel"]["source_url"] = "https://invalid.example/isj-source-tamper"

    def mutate_article_claim_cardinality(doc: dict) -> None:
        claims = doc["articles"][0]["article_package"]["claims"]
        assert len(claims) >= 2
        claims.pop()

    def mutate_integrity_article_id(doc: dict) -> None:
        doc["verified_candidates"][0]["article_id"] = "tampered-isj-article-id"

    def mutate_integrity_source_binding(doc: dict) -> None:
        doc["verified_candidates"][0]["source_url"] = "https://invalid.example/isj-source-binding"

    def mutate_kernel_source_identity(doc: dict) -> None:
        doc["kernels"][0]["fact_kernel"]["source_url"] = "https://invalid.example/isj-kernel-source"

    _expect_fail_closed(
        base,
        repo,
        "valcea-core-v2-isj-article-shadow.json",
        mutate_article_kernel_source,
        "article embeds a fact kernel with a different source identity",
    )
    _expect_fail_closed(
        base,
        repo,
        "valcea-core-v2-isj-article-shadow.json",
        mutate_article_claim_cardinality,
        "article claim cardinality diverges from the verified FactKernel",
    )
    _expect_fail_closed(
        base,
        repo,
        "valcea-core-v2-isj-article-integrity-shadow.json",
        mutate_integrity_article_id,
        "article-integrity candidate points at a different article id",
    )
    _expect_fail_closed(
        base,
        repo,
        "valcea-core-v2-isj-article-integrity-shadow.json",
        mutate_integrity_source_binding,
        "article-integrity candidate points at a different source URL",
    )
    _expect_fail_closed(
        base,
        repo,
        "valcea-core-v2-isj-fact-kernel-shadow.json",
        mutate_kernel_source_identity,
        "FactKernel source identity is mutated away from the verified ISJ source",
    )

    print("Core v2 late-ISJ negative runtime regressions: PASS (5/5 fail-closed)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prove canonical Core v2 runtime validation rejects late-ISJ cross-artifact tampering"
    )
    parser.add_argument("--base", default="/tmp")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    run(Path(args.base).resolve(), Path(args.repo).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
