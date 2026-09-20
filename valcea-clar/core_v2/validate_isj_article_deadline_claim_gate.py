from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


IDENTITY_KEYS = (
    "field_evidence_id",
    "scope_field_evidence_id",
    "source_registration_window_field_evidence_id",
    "document_text_evidence_id",
    "upstream_materiality_promotion_evidence_id",
    "fact_kernel_promotion_evidence_id",
    "page_text_sha256",
)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _claim_gate_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"isj-article-deadline-claim-{digest[:24]}"


def _require_shadow_boundary(doc: dict[str, Any], label: str) -> None:
    assert doc.get("publication_authority") == "NONE", f"{label}:publication_authority"
    assert doc.get("acceptance_ready") is False, f"{label}:acceptance_ready"
    assert doc.get("site_publish_allowed") is False, f"{label}:site_publish_allowed"
    assert doc.get("social_publish_allowed") is False, f"{label}:social_publish_allowed"


def validate(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    article_report: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, Any]:
    for label, doc in (
        ("fact_kernel", fact_kernel),
        ("fact_integrity", fact_integrity),
        ("writer_consumption", writer_consumption),
        ("writer_consumption_validation", writer_consumption_validation),
        ("article_report", article_report),
        ("gate", gate),
    ):
        _require_shadow_boundary(doc, label)

    assert fact_kernel.get("state") == "FACT_KERNEL_VERIFIED_SHADOW"
    assert fact_kernel.get("writer_allowed") is False
    assert int(fact_kernel.get("promoted_fact_claim_count") or 0) == 1
    kernels = fact_kernel.get("kernels") or []
    assert len(kernels) == 1 and isinstance(kernels[0], dict)
    promoted_rows = kernels[0].get("promoted_fact_claims") or []
    assert len(promoted_rows) == 1 and isinstance(promoted_rows[0], dict)
    promoted = promoted_rows[0]
    assert promoted.get("field") == "registration_deadline"

    assert fact_integrity.get("status") == "PASS_SHADOW"
    assert fact_integrity.get("fact_kernel_integrity_verified") is True
    assert int(fact_integrity.get("promoted_fact_verified_count") or 0) == 1
    assert int(fact_integrity.get("fabricated_claim_count") or 0) == 0

    assert writer_consumption.get("state") == "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW"
    assert writer_consumption.get("shadow_writer_consumption_allowed") is True
    assert writer_consumption.get("writer_allowed") is False
    assert writer_consumption.get("article_projection_allowed") is False
    assert int(writer_consumption.get("consumption_candidate_count") or 0) == 1
    consumption_id = _norm(writer_consumption.get("writer_consumption_evidence_id"))
    assert consumption_id

    assert writer_consumption_validation.get("status") == "PASS_SHADOW"
    assert writer_consumption_validation.get("writer_consumption_evidence_id") == consumption_id
    assert writer_consumption_validation.get("shadow_writer_consumption_allowed") is True
    assert writer_consumption_validation.get("article_projection_allowed") is False
    assert int(writer_consumption_validation.get("verified_consumption_candidate_count") or 0) == 1
    assert int(writer_consumption_validation.get("fabricated_claim_count") or 0) == 0
    assert int(writer_consumption_validation.get("tamper_regressions_passed") or 0) >= 4

    consumption_rows = writer_consumption.get("consumption_candidates") or []
    assert len(consumption_rows) == 1 and isinstance(consumption_rows[0], dict)
    consumption_candidate = consumption_rows[0]
    assert consumption_candidate.get("state") == "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW"
    assert _norm(consumption_candidate.get("writer_consumption_evidence_id")) == consumption_id

    assert article_report.get("state") == "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY"
    assert article_report.get("shadow_writer_executed") is True
    assert article_report.get("writer_consumes_deadline_projection") is True
    assert int(article_report.get("rendered_promoted_claim_count") or 0) == 1
    assert article_report.get("article_contains_registration_deadline") is False
    articles = article_report.get("articles") or []
    assert len(articles) == 1 and isinstance(articles[0], dict)
    package = articles[0].get("article_package") or {}
    assert isinstance(package, dict)
    assert package.get("publication_authority") == "NONE"
    assert package.get("article_projection_allowed") is False
    assert package.get("site_publish_allowed") is False
    assert package.get("social_publish_allowed") is False
    assert package.get("writer_consumes_deadline_projection") is True
    assert package.get("article_contains_registration_deadline") is False

    pending_rows = package.get("rendered_promoted_claims_pending_integrity") or []
    assert len(pending_rows) == 1 and isinstance(pending_rows[0], dict)
    pending = pending_rows[0]
    assert pending.get("state") == "WRITER_RENDERED_SHADOW_PENDING_ARTICLE_CLAIM_INTEGRITY"
    assert pending.get("field") == "registration_deadline"
    assert pending.get("article_projection_allowed") is False
    assert pending.get("publication_authority") == "NONE"
    assert _norm(pending.get("writer_consumption_evidence_id")) == consumption_id

    deadline = _norm(pending.get("value"))
    claim = _norm(pending.get("text"))
    assert deadline and claim
    assert deadline == _norm(writer_consumption.get("registration_deadline"))
    assert deadline == _norm(writer_consumption_validation.get("registration_deadline"))
    assert deadline == _norm(consumption_candidate.get("value"))
    assert deadline == _norm(promoted.get("value"))
    assert claim == _norm(consumption_candidate.get("claim"))
    assert claim == _norm(promoted.get("claim"))

    projection_id = _norm(pending.get("writer_projection_evidence_id"))
    assert projection_id
    assert projection_id == _norm(writer_consumption.get("writer_projection_evidence_id"))
    assert projection_id == _norm(consumption_candidate.get("writer_projection_evidence_id"))

    claim_evidence_ids = [_norm(v) for v in pending.get("claim_evidence_ids") or [] if _norm(v)]
    assert claim_evidence_ids
    assert claim_evidence_ids == [_norm(v) for v in consumption_candidate.get("claim_evidence_ids") or [] if _norm(v)]
    assert claim_evidence_ids == [_norm(v) for v in promoted.get("claim_evidence_ids") or [] if _norm(v)]
    supporting_ids = [_norm(v) for v in pending.get("supporting_field_evidence_ids") or [] if _norm(v)]
    assert supporting_ids == [_norm(v) for v in consumption_candidate.get("supporting_field_evidence_ids") or [] if _norm(v)]
    assert supporting_ids == [_norm(v) for v in promoted.get("supporting_field_evidence_ids") or [] if _norm(v)]

    identities = {key: _norm(pending.get(key)) for key in IDENTITY_KEYS}
    assert all(identities.values())
    for key, value in identities.items():
        assert value == _norm(consumption_candidate.get(key)), key
        assert value == _norm(promoted.get(key)), key

    page_number = int(pending.get("page_number") or 0)
    excerpt = _norm(pending.get("excerpt"))
    assert page_number > 0 and excerpt
    assert page_number == int(consumption_candidate.get("page_number") or 0)
    assert excerpt == _norm(consumption_candidate.get("excerpt"))
    assert page_number == int(promoted.get("page_number") or 0)
    assert excerpt == _norm(promoted.get("excerpt"))

    article_id = _norm(package.get("article_id"))
    assert article_id
    canonical_claim_texts = [_norm(row.get("text")) for row in package.get("claims") or [] if isinstance(row, dict)]
    assert claim not in canonical_claim_texts
    body = _norm(package.get("body"))
    assert deadline not in body
    assert claim not in body

    expected_gate_id = _claim_gate_id(
        article_id,
        consumption_id,
        projection_id,
        deadline,
        claim,
        *claim_evidence_ids,
        identities["upstream_materiality_promotion_evidence_id"],
        identities["fact_kernel_promotion_evidence_id"],
        identities["page_text_sha256"],
        str(page_number),
        excerpt,
    )

    assert gate.get("state") == "ARTICLE_DEADLINE_CLAIM_EVIDENCE_VERIFIED_SHADOW"
    assert gate.get("shadow_article_claim_integrity_passed") is True
    assert gate.get("canonical_article_mutation_allowed") is False
    assert gate.get("article_projection_allowed") is False
    assert gate.get("article_id") == article_id
    assert gate.get("registration_deadline") == deadline
    assert gate.get("writer_projection_evidence_id") == projection_id
    assert gate.get("writer_consumption_evidence_id") == consumption_id
    assert gate.get("article_deadline_claim_evidence_id") == expected_gate_id
    assert int(gate.get("claim_candidate_count") or 0) == 1
    assert int(gate.get("fabricated_claim_count") or 0) == 0

    candidates = gate.get("claim_candidates") or []
    assert len(candidates) == 1 and isinstance(candidates[0], dict)
    out = candidates[0]
    assert out.get("article_id") == article_id
    assert out.get("field") == "registration_deadline"
    assert out.get("value") == deadline
    assert _norm(out.get("claim")) == claim
    assert out.get("state") == "ARTICLE_DEADLINE_CLAIM_EVIDENCE_VERIFIED_SHADOW"
    assert out.get("writer_projection_evidence_id") == projection_id
    assert out.get("writer_consumption_evidence_id") == consumption_id
    assert out.get("article_deadline_claim_evidence_id") == expected_gate_id
    assert out.get("shadow_article_claim_integrity_passed") is True
    assert out.get("canonical_article_mutation_allowed") is False
    assert out.get("article_projection_allowed") is False
    for key, value in identities.items():
        assert _norm(out.get(key)) == value, key
    assert [_norm(v) for v in out.get("claim_evidence_ids") or [] if _norm(v)] == claim_evidence_ids
    assert [_norm(v) for v in out.get("supporting_field_evidence_ids") or [] if _norm(v)] == supporting_ids
    assert int(out.get("page_number") or 0) == page_number
    assert _norm(out.get("excerpt")) == excerpt

    return {
        "status": "PASS_SHADOW",
        "article_id": article_id,
        "registration_deadline": deadline,
        "writer_projection_evidence_id": projection_id,
        "writer_consumption_evidence_id": consumption_id,
        "article_deadline_claim_evidence_id": expected_gate_id,
        "shadow_article_claim_integrity_passed": True,
        "verified_claim_candidate_count": 1,
        "fabricated_claim_count": 0,
        "canonical_article_mutation_allowed": False,
        "article_projection_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }


def prove_tamper_regressions(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    article_report: dict[str, Any],
    gate: dict[str, Any],
) -> int:
    cases: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    detached_consumption = copy.deepcopy(article_report)
    detached_consumption["articles"][0]["article_package"]["rendered_promoted_claims_pending_integrity"][0][
        "writer_consumption_evidence_id"
    ] = "isj-writer-deadline-consumption-tampered"
    cases.append(("pending consumption identity detached", detached_consumption, gate))

    detached_evidence = copy.deepcopy(article_report)
    detached_evidence["articles"][0]["article_package"]["rendered_promoted_claims_pending_integrity"][0][
        "claim_evidence_ids"
    ] = ["tampered-evidence-id"]
    cases.append(("pending claim evidence detached", detached_evidence, gate))

    detached_hash = copy.deepcopy(article_report)
    detached_hash["articles"][0]["article_package"]["rendered_promoted_claims_pending_integrity"][0][
        "page_text_sha256"
    ] = "0" * 64
    cases.append(("pending page hash detached", detached_hash, gate))

    premature_body = copy.deepcopy(article_report)
    pending = premature_body["articles"][0]["article_package"]["rendered_promoted_claims_pending_integrity"][0]
    premature_body["articles"][0]["article_package"]["body"] += "\n\n" + str(pending["text"])
    cases.append(("pending claim prematurely inserted into article body", premature_body, gate))

    detached_gate = copy.deepcopy(gate)
    detached_gate["article_deadline_claim_evidence_id"] = "isj-article-deadline-claim-tampered"
    cases.append(("article claim gate identity detached", article_report, detached_gate))

    passed = 0
    for label, article_case, gate_case in cases:
        try:
            validate(
                fact_kernel,
                fact_integrity,
                writer_consumption,
                writer_consumption_validation,
                article_case,
                gate_case,
            )
        except AssertionError:
            passed += 1
            continue
        raise AssertionError(f"ISJ article deadline claim validator accepted tamper: {label}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently validate ISJ article registration-deadline claim evidence")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--writer-consumption", required=True)
    parser.add_argument("--writer-consumption-validation", required=True)
    parser.add_argument("--article", required=True)
    parser.add_argument("--gate", required=True)
    parser.add_argument("--prove-tamper", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    fact_kernel = json.loads(Path(args.fact_kernel).read_text(encoding="utf-8"))
    fact_integrity = json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8"))
    writer_consumption = json.loads(Path(args.writer_consumption).read_text(encoding="utf-8"))
    writer_consumption_validation = json.loads(Path(args.writer_consumption_validation).read_text(encoding="utf-8"))
    article_report = json.loads(Path(args.article).read_text(encoding="utf-8"))
    gate = json.loads(Path(args.gate).read_text(encoding="utf-8"))

    summary = validate(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        article_report,
        gate,
    )
    tamper_passed = prove_tamper_regressions(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        article_report,
        gate,
    ) if args.prove_tamper else 0
    report = {
        "schema_version": "1.0",
        "mode": "ISJ_ARTICLE_DEADLINE_CLAIM_VALIDATION",
        **summary,
        "tamper_regressions_requested": bool(args.prove_tamper),
        "tamper_regressions_passed": tamper_passed,
        "truth_rule": (
            "This independent validator reproduces the exact article deadline-claim evidence identity from the writer-consumption "
            "and promoted FactKernel evidence chain, while proving that the claim is still absent from canonical article claims/body. "
            "PASS_SHADOW grants no article mutation, publication, delivery or acceptance authority."
        ),
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "registration_deadline": report["registration_deadline"],
        "shadow_article_claim_integrity_passed": report["shadow_article_claim_integrity_passed"],
        "tamper_regressions_passed": report["tamper_regressions_passed"],
        "canonical_article_mutation_allowed": False,
        "article_projection_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
