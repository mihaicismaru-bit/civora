from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import validate_shadow_runtime_legacy_snapshot as legacy

OLD_SCOPE_NOTE = (
    "Core v2 nu afirmă termenul de înscriere și nu normalizează intervalele calendaristice fără an explicit, "
    "deoarece aceste elemente nu sunt încă proiectate în articol printr-un gate independent claim↔evidence."
)
PROJECTED_SCOPE_NOTE = (
    "Core v2 afirmă numai termenul de înscriere 2 octombrie 2026, promovat prin lanțul independent "
    "FactKernel → writer-consumption → article-claim; celelalte intervale calendaristice fără an explicit "
    "rămân excluse până la validare separată."
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _legacy_compatible_article(doc: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(doc, ensure_ascii=False))
    out["article_contains_registration_deadline"] = False
    out.pop("canonical_promoted_claim_count", None)
    out.pop("shadow_article_projection_applied", None)
    out.pop("article_deadline_claim_evidence_id", None)
    articles = out.get("articles") or []
    assert len(articles) == 1 and isinstance(articles[0], dict)
    package = articles[0].get("article_package") or {}
    claims = package.get("claims") or []
    package["claims"] = [
        row for row in claims
        if not (isinstance(row, dict) and row.get("promoted_fact_field") == "registration_deadline")
    ]
    segments = package.get("body_segments") or []
    package["body_segments"] = [
        row for row in segments
        if not (isinstance(row, dict) and row.get("kind") == "promoted_fact_claim")
    ]
    for row in package["body_segments"]:
        if isinstance(row, dict) and row.get("kind") == "scope_note":
            row["text"] = OLD_SCOPE_NOTE
            row["evidence_ids"] = []
    package["body"] = "\n\n".join(_norm(row.get("text")) for row in package["body_segments"] if isinstance(row, dict))
    package["article_contains_registration_deadline"] = False
    package.pop("canonical_promoted_claim_count", None)
    package.pop("promoted_claims_projected_shadow", None)
    package.setdefault("excluded_unverified_or_non_normalized_fields", [])
    excluded = list(package.get("excluded_unverified_or_non_normalized_fields") or [])
    if "registration_deadline" not in excluded:
        excluded.insert(0, "registration_deadline")
    package["excluded_unverified_or_non_normalized_fields"] = excluded
    return out


def _legacy_compatible_integrity(doc: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(doc, ensure_ascii=False))
    if out.get("status") == "PASS_SHADOW":
        out["verified_claim_count"] = 2
        out["projected_deadline_verified"] = False
        out["article_contains_registration_deadline"] = False
        out["canonical_promoted_claim_count"] = 0
        out["article_deadline_claim_evidence_id"] = None
        for row in out.get("verified_candidates") or []:
            if isinstance(row, dict):
                row.pop("article_deadline_claim_evidence_id", None)
                row.pop("registration_deadline", None)
    return out


def _validate_projected_truth(base: Path) -> None:
    fact_kernel = load(base / "valcea-core-v2-isj-fact-kernel-shadow.json")
    fact_integrity = load(base / "valcea-core-v2-isj-fact-kernel-integrity-shadow.json")
    article = load(base / "valcea-core-v2-isj-article-shadow.json")
    integrity = load(base / "valcea-core-v2-isj-article-integrity-shadow.json")

    assert fact_kernel.get("publication_authority") == "NONE"
    assert fact_integrity.get("publication_authority") == "NONE"
    assert article.get("publication_authority") == "NONE"
    assert integrity.get("publication_authority") == "NONE"
    assert article.get("acceptance_ready") is False
    assert integrity.get("acceptance_ready") is False

    assert article.get("state") == "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY"
    assert article.get("shadow_writer_executed") is True
    assert article.get("article_contains_registration_deadline") is True
    assert article.get("shadow_article_projection_applied") is True
    assert int(article.get("canonical_promoted_claim_count") or 0) == 1
    gate_id = _norm(article.get("article_deadline_claim_evidence_id"))
    assert gate_id.startswith("isj-article-deadline-claim-")

    kernels = fact_kernel.get("kernels") or []
    assert len(kernels) == 1 and isinstance(kernels[0], dict)
    promoted = kernels[0].get("promoted_fact_claims") or []
    assert int(fact_kernel.get("promoted_fact_claim_count") or 0) == 1
    assert len(promoted) == 1 and isinstance(promoted[0], dict)
    promoted_claim = promoted[0]
    assert promoted_claim.get("field") == "registration_deadline"
    assert _norm(promoted_claim.get("value")) == "2026-10-02"
    claim_text = _norm(promoted_claim.get("claim"))
    claim_evidence = [_norm(v) for v in promoted_claim.get("claim_evidence_ids") or [] if _norm(v)]
    assert claim_text and claim_evidence
    assert int(fact_integrity.get("promoted_fact_verified_count") or 0) == 1

    articles = article.get("articles") or []
    assert len(articles) == 1 and isinstance(articles[0], dict)
    package = articles[0].get("article_package") or {}
    assert package.get("publication_authority") == "NONE"
    assert package.get("site_publish_allowed") is False
    assert package.get("social_publish_allowed") is False
    assert package.get("article_projection_allowed") is False
    assert package.get("article_contains_registration_deadline") is True
    assert int(package.get("canonical_promoted_claim_count") or 0) == 1
    assert not (package.get("rendered_promoted_claims_pending_integrity") or [])

    claims = package.get("claims") or []
    assert len(claims) == 3
    promoted_rows = [row for row in claims if isinstance(row, dict) and row.get("promoted_fact_field") == "registration_deadline"]
    assert len(promoted_rows) == 1
    row = promoted_rows[0]
    assert _norm(row.get("text")) == claim_text
    assert [_norm(v) for v in row.get("field_evidence_ids") or [] if _norm(v)] == claim_evidence
    assert _norm(row.get("article_deadline_claim_evidence_id")) == gate_id
    assert _norm(row.get("writer_consumption_evidence_id")).startswith("isj-writer-deadline-consumption-")
    assert _norm(row.get("writer_projection_evidence_id")).startswith("isj-writer-deadline-projection-")
    assert _norm(row.get("fact_kernel_promotion_evidence_id")) == _norm(promoted_claim.get("fact_kernel_promotion_evidence_id"))
    assert _norm(row.get("upstream_materiality_promotion_evidence_id")) == _norm(promoted_claim.get("upstream_materiality_promotion_evidence_id"))
    assert _norm(row.get("page_text_sha256")) == _norm(promoted_claim.get("page_text_sha256"))
    assert int(row.get("page_number") or 0) == int(promoted_claim.get("page_number") or 0)
    assert _norm(row.get("excerpt")) == _norm(promoted_claim.get("excerpt"))

    segments = package.get("body_segments") or []
    promoted_segments = [
        seg for seg in segments
        if isinstance(seg, dict) and seg.get("kind") == "promoted_fact_claim"
        and seg.get("promoted_fact_field") == "registration_deadline"
    ]
    assert len(promoted_segments) == 1
    assert _norm(promoted_segments[0].get("text")) == claim_text
    assert _norm(promoted_segments[0].get("article_deadline_claim_evidence_id")) == gate_id
    assert "2 octombrie 2026" in _norm(package.get("body"))
    scope_rows = [row for row in segments if isinstance(row, dict) and row.get("kind") == "scope_note"]
    assert len(scope_rows) == 1
    assert _norm(scope_rows[0].get("text")) == _norm(PROJECTED_SCOPE_NOTE)

    excluded = {_norm(v) for v in package.get("excluded_unverified_or_non_normalized_fields") or [] if _norm(v)}
    assert "registration_deadline" not in excluded
    assert {"interview_window_text", "appointment_decision_deadline_text"}.issubset(excluded)

    assert integrity.get("status") == "PASS_SHADOW"
    assert integrity.get("article_truth_state") == "VERIFIED_WRITTEN_SHADOW"
    assert integrity.get("article_integrity_verified") is True
    assert integrity.get("projected_deadline_verified") is True
    assert integrity.get("article_contains_registration_deadline") is True
    assert int(integrity.get("canonical_promoted_claim_count") or 0) == 1
    assert _norm(integrity.get("article_deadline_claim_evidence_id")) == gate_id
    assert int(integrity.get("verified_claim_count") or 0) == 3
    assert int(integrity.get("fabricated_claim_count") or 0) == 0
    verified = integrity.get("verified_candidates") or []
    assert len(verified) == 1
    assert _norm(verified[0].get("article_deadline_claim_evidence_id")) == gate_id
    assert _norm(verified[0].get("registration_deadline")) == "2026-10-02"


def _validate_independent_external_auditor(base: Path) -> dict[str, Any]:
    from promoted_claim_auditor import audit_documents

    candidates = load(base / "valcea-core-v2-shadow-candidates.json")
    site = load(base / "valcea-core-v2-site-readback.json")
    visual = load(base / "valcea-core-v2-visual-readback.json")
    meta = load(base / "valcea-core-v2-meta-readback.json")
    identity = load(base / "valcea-core-v2-instagram-visual-identity.json")
    transactions = load(base / "valcea-core-v2-shadow-transactions.json")
    receipts = load(base / "valcea-core-v2-shadow-receipts.json")
    gate = load(base / "valcea-core-v2-gate-report.json")

    report = audit_documents(candidates, site, visual, meta, identity, transactions)
    metrics = report.get("metrics") or {}
    receipt_rows = [row for row in receipts.get("rows") or [] if isinstance(row, dict)]
    canonical_projection = {
        "stories_published": sum(
            1 for row in receipt_rows
            if ((row.get("receipts") or {}).get("site") or {}).get("status") == "DELIVERED"
            and ((row.get("receipts") or {}).get("site") or {}).get("readback_ok") is True
        ),
        "photo_verified_count": sum(
            1 for row in receipt_rows
            if ((row.get("receipts") or {}).get("visual") or {}).get("status") == "VERIFIED"
            and ((row.get("receipts") or {}).get("visual") or {}).get("readback_ok") is True
            and ((row.get("receipts") or {}).get("visual") or {}).get("canonical_site_visual_binding_state") == "CONSISTENT"
        ),
        "facebook_delivered_receipt_bound": sum(
            1 for row in receipt_rows
            if ((row.get("receipts") or {}).get("facebook") or {}).get("status") == "DELIVERED"
            and ((row.get("receipts") or {}).get("facebook") or {}).get("readback_ok") is True
            and ((row.get("receipts") or {}).get("facebook") or {}).get("remote_id")
            and ((row.get("receipts") or {}).get("facebook") or {}).get("receipt_id")
        ),
        "instagram_delivered_receipt_bound": sum(
            1 for row in receipt_rows
            if ((row.get("receipts") or {}).get("instagram") or {}).get("status") == "DELIVERED"
            and ((row.get("receipts") or {}).get("instagram") or {}).get("readback_ok") is True
            and ((row.get("receipts") or {}).get("instagram") or {}).get("remote_id")
            and ((row.get("receipts") or {}).get("instagram") or {}).get("receipt_id")
            and ((row.get("receipts") or {}).get("instagram") or {}).get("remote_visual_readback_ok") is True
            and ((row.get("receipts") or {}).get("instagram") or {}).get("remote_visual_identity_bound") is True
            and ((row.get("receipts") or {}).get("visual") or {}).get("canonical_site_visual_binding_state") == "CONSISTENT"
        ),
        "truth_complete_transactions": int(gate.get("truth_complete_count") or 0),
    }
    auditor_projection = {key: metrics.get(key) for key in canonical_projection}
    if auditor_projection != canonical_projection:
        raise RuntimeError(
            f"independent_external_auditor_semantic_projection_drifted:{auditor_projection!r}!={canonical_projection!r}"
        )
    if report.get("publication_authority") != "NONE" or report.get("cutover_authority") != "NONE":
        raise RuntimeError("independent_external_auditor_authority_boundary_changed")
    if report.get("retirement_authority") != "NONE" or report.get("acceptance_ready") is not False:
        raise RuntimeError("independent_external_auditor_acceptance_or_retirement_boundary_changed")

    output = base / "valcea-core-v2-independent-auditor.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def validate(base: Path, repo: Path) -> None:
    article_path = base / "valcea-core-v2-isj-article-shadow.json"
    article = load(article_path)
    if article.get("article_contains_registration_deadline") is not True:
        legacy.validate(base, repo)
        return

    with tempfile.TemporaryDirectory(prefix="valcea-core-v2-runtime-compat-") as td:
        compat = Path(td)
        for source in base.iterdir():
            if not source.is_file():
                continue
            target = compat / source.name
            if source.name == "valcea-core-v2-isj-article-shadow.json":
                target.write_text(
                    json.dumps(_legacy_compatible_article(load(source)), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            elif source.name == "valcea-core-v2-isj-article-integrity-shadow.json":
                target.write_text(
                    json.dumps(_legacy_compatible_integrity(load(source)), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            else:
                os.symlink(source.resolve(), target)
        legacy.validate(compat, repo)

    _validate_projected_truth(base)

    # Independent CI-only regressions are validators, never runtime stages.
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        import validate_fact_kernel_definition_equivalence_runtime as fact_equivalence

        report = fact_equivalence.validate(base)
        if report.get("status") != "PASS_SHADOW":
            raise RuntimeError("fact_kernel_definition_equivalence_not_pass_shadow")
        print(json.dumps({
            "ci_only_fact_kernel_definition_equivalence": report.get("status"),
            "canonical_stage_count": report.get("canonical_stage_count"),
            "projection_evidence_id": report.get("projection_evidence_id"),
            "consumption_evidence_id": report.get("consumption_evidence_id"),
            "article_claim_evidence_id": report.get("article_claim_evidence_id"),
            "promoted_claim_contract_id": report.get("promoted_claim_contract_id"),
            "tamper_regressions": report.get("tamper_regressions"),
            "verified_article_claim_count": report.get("verified_article_claim_count"),
            "fabricated_claim_count": report.get("fabricated_claim_count"),
            "publication_authority": "NONE",
            "acceptance_ready": False,
        }, ensure_ascii=False, sort_keys=True))

        external = _validate_independent_external_auditor(base)
        print(json.dumps({
            "ci_only_independent_external_auditor": external.get("status"),
            "external_truth_complete": external.get("external_truth_complete"),
            "external_blocked_story_count": external.get("external_blocked_story_count"),
            "metrics": external.get("metrics"),
            "publication_authority": external.get("publication_authority"),
            "acceptance_ready": external.get("acceptance_ready"),
            "cutover_authority": external.get("cutover_authority"),
            "retirement_authority": external.get("retirement_authority"),
        }, ensure_ascii=False, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate all Core v2 live shadow artifacts remain non-authoritative")
    parser.add_argument("--base", default="/tmp")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    validate(Path(args.base), Path(args.repo))
    print("Core v2 shadow runtime invariants: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
