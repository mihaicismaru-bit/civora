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

PROJECTED_SCOPE_NOTE = (
    "Core v2 afirmă numai termenul de înscriere 2 octombrie 2026, promovat prin lanțul independent "
    "FactKernel → writer-consumption → article-claim; celelalte intervale calendaristice fără an explicit "
    "rămân excluse până la validare separată."
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


def _source_chain(
    fact_kernel: dict[str, Any],
    writer_consumption: dict[str, Any],
    article_report: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    kernels = fact_kernel.get("kernels") or []
    assert len(kernels) == 1 and isinstance(kernels[0], dict)
    promoted_rows = kernels[0].get("promoted_fact_claims") or []
    assert len(promoted_rows) == 1 and isinstance(promoted_rows[0], dict)
    promoted = promoted_rows[0]
    assert promoted.get("field") == "registration_deadline"

    consumption_rows = writer_consumption.get("consumption_candidates") or []
    assert len(consumption_rows) == 1 and isinstance(consumption_rows[0], dict)
    consumption_candidate = consumption_rows[0]

    articles = article_report.get("articles") or []
    assert len(articles) == 1 and isinstance(articles[0], dict)
    package = articles[0].get("article_package") or {}
    assert isinstance(package, dict)
    return kernels[0], promoted, consumption_candidate, package


def _verify_gate_candidate_against_chain(
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
    assert _norm(writer_consumption_validation.get("writer_consumption_evidence_id")) == consumption_id
    assert writer_consumption_validation.get("shadow_writer_consumption_allowed") is True
    assert writer_consumption_validation.get("article_projection_allowed") is False
    assert int(writer_consumption_validation.get("verified_consumption_candidate_count") or 0) == 1
    assert int(writer_consumption_validation.get("fabricated_claim_count") or 0) == 0
    assert int(writer_consumption_validation.get("tamper_regressions_passed") or 0) >= 4

    _, promoted, consumption_candidate, package = _source_chain(
        fact_kernel, writer_consumption, article_report
    )
    assert consumption_candidate.get("state") == "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW"
    assert _norm(consumption_candidate.get("writer_consumption_evidence_id")) == consumption_id

    assert gate.get("state") == "ARTICLE_DEADLINE_CLAIM_EVIDENCE_VERIFIED_SHADOW"
    assert gate.get("shadow_article_claim_integrity_passed") is True
    assert gate.get("canonical_article_mutation_allowed") is False
    assert gate.get("article_projection_allowed") is False
    assert int(gate.get("claim_candidate_count") or 0) == 1
    assert int(gate.get("fabricated_claim_count") or 0) == 0

    candidates = gate.get("claim_candidates") or []
    assert len(candidates) == 1 and isinstance(candidates[0], dict)
    out = candidates[0]
    assert out.get("state") == "ARTICLE_DEADLINE_CLAIM_EVIDENCE_VERIFIED_SHADOW"
    assert out.get("field") == "registration_deadline"
    assert out.get("shadow_article_claim_integrity_passed") is True
    assert out.get("canonical_article_mutation_allowed") is False
    assert out.get("article_projection_allowed") is False

    article_id = _norm(package.get("article_id"))
    assert article_id and _norm(out.get("article_id")) == article_id
    deadline = _norm(out.get("value"))
    claim = _norm(out.get("claim"))
    assert deadline and claim
    assert deadline == _norm(promoted.get("value"))
    assert deadline == _norm(consumption_candidate.get("value"))
    assert deadline == _norm(writer_consumption.get("registration_deadline"))
    assert deadline == _norm(writer_consumption_validation.get("registration_deadline"))
    assert claim == _norm(promoted.get("claim"))
    assert claim == _norm(consumption_candidate.get("claim"))

    projection_id = _norm(out.get("writer_projection_evidence_id"))
    assert projection_id
    assert projection_id == _norm(writer_consumption.get("writer_projection_evidence_id"))
    assert projection_id == _norm(consumption_candidate.get("writer_projection_evidence_id"))
    assert _norm(out.get("writer_consumption_evidence_id")) == consumption_id

    claim_evidence_ids = [_norm(v) for v in out.get("claim_evidence_ids") or [] if _norm(v)]
    assert claim_evidence_ids
    assert claim_evidence_ids == [_norm(v) for v in promoted.get("claim_evidence_ids") or [] if _norm(v)]
    assert claim_evidence_ids == [_norm(v) for v in consumption_candidate.get("claim_evidence_ids") or [] if _norm(v)]

    supporting_ids = [_norm(v) for v in out.get("supporting_field_evidence_ids") or [] if _norm(v)]
    assert supporting_ids == [_norm(v) for v in promoted.get("supporting_field_evidence_ids") or [] if _norm(v)]
    assert supporting_ids == [_norm(v) for v in consumption_candidate.get("supporting_field_evidence_ids") or [] if _norm(v)]

    identities = {key: _norm(out.get(key)) for key in IDENTITY_KEYS}
    assert all(identities.values())
    for key, value in identities.items():
        assert value == _norm(promoted.get(key)), key
        assert value == _norm(consumption_candidate.get(key)), key

    page_number = int(out.get("page_number") or 0)
    excerpt = _norm(out.get("excerpt"))
    assert page_number > 0 and excerpt
    assert page_number == int(promoted.get("page_number") or 0)
    assert page_number == int(consumption_candidate.get("page_number") or 0)
    assert excerpt == _norm(promoted.get("excerpt"))
    assert excerpt == _norm(consumption_candidate.get("excerpt"))

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
    assert _norm(gate.get("article_deadline_claim_evidence_id")) == expected_gate_id
    assert _norm(out.get("article_deadline_claim_evidence_id")) == expected_gate_id
    assert _norm(gate.get("writer_consumption_evidence_id")) == consumption_id
    assert _norm(gate.get("writer_projection_evidence_id")) == projection_id
    assert _norm(gate.get("registration_deadline")) == deadline

    return {
        "article_id": article_id,
        "deadline": deadline,
        "claim": claim,
        "projection_id": projection_id,
        "consumption_id": consumption_id,
        "claim_evidence_ids": claim_evidence_ids,
        "supporting_ids": supporting_ids,
        "identities": identities,
        "page_number": page_number,
        "excerpt": excerpt,
        "gate_id": expected_gate_id,
        "candidate": copy.deepcopy(out),
        "package": package,
    }


def validate(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    article_report: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, Any]:
    chain = _verify_gate_candidate_against_chain(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        article_report,
        gate,
    )
    package = chain["package"]
    assert article_report.get("state") == "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY"
    assert article_report.get("shadow_writer_executed") is True
    assert article_report.get("writer_consumes_deadline_projection") is True
    assert int(article_report.get("rendered_promoted_claim_count") or 0) == 1
    assert article_report.get("article_contains_registration_deadline") is False
    assert package.get("writer_consumes_deadline_projection") is True
    assert package.get("article_contains_registration_deadline") is False
    assert package.get("article_projection_allowed") is False

    pending_rows = package.get("rendered_promoted_claims_pending_integrity") or []
    assert len(pending_rows) == 1 and isinstance(pending_rows[0], dict)
    pending = pending_rows[0]
    assert pending.get("state") == "WRITER_RENDERED_SHADOW_PENDING_ARTICLE_CLAIM_INTEGRITY"
    assert pending.get("field") == "registration_deadline"
    assert _norm(pending.get("text")) == chain["claim"]
    assert _norm(pending.get("value")) == chain["deadline"]
    assert _norm(pending.get("writer_consumption_evidence_id")) == chain["consumption_id"]
    assert _norm(pending.get("writer_projection_evidence_id")) == chain["projection_id"]
    assert [_norm(v) for v in pending.get("claim_evidence_ids") or [] if _norm(v)] == chain["claim_evidence_ids"]

    canonical_claim_texts = [_norm(row.get("text")) for row in package.get("claims") or [] if isinstance(row, dict)]
    assert chain["claim"] not in canonical_claim_texts
    body = _norm(package.get("body"))
    assert chain["deadline"] not in body
    assert chain["claim"] not in body

    return {
        "status": "PASS_SHADOW",
        "article_id": chain["article_id"],
        "registration_deadline": chain["deadline"],
        "writer_projection_evidence_id": chain["projection_id"],
        "writer_consumption_evidence_id": chain["consumption_id"],
        "article_deadline_claim_evidence_id": chain["gate_id"],
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


def project_validated_deadline_claim(
    article_report: dict[str, Any],
    gate: dict[str, Any],
    validation_summary: dict[str, Any],
) -> dict[str, Any]:
    assert validation_summary.get("status") == "PASS_SHADOW"
    assert validation_summary.get("publication_authority") == "NONE"
    assert validation_summary.get("canonical_article_mutation_allowed") is False
    assert validation_summary.get("article_projection_allowed") is False
    assert _norm(validation_summary.get("article_deadline_claim_evidence_id")) == _norm(
        gate.get("article_deadline_claim_evidence_id")
    )

    projected = copy.deepcopy(article_report)
    articles = projected.get("articles") or []
    assert len(articles) == 1 and isinstance(articles[0], dict)
    package = articles[0].get("article_package") or {}
    assert isinstance(package, dict)

    candidates = gate.get("claim_candidates") or []
    assert len(candidates) == 1 and isinstance(candidates[0], dict)
    candidate = copy.deepcopy(candidates[0])
    claim = _norm(candidate.get("claim"))
    deadline = _norm(candidate.get("value"))
    gate_id = _norm(candidate.get("article_deadline_claim_evidence_id"))
    assert claim and deadline and gate_id

    existing_claims = package.get("claims") or []
    assert all(_norm(row.get("text")) != claim for row in existing_claims if isinstance(row, dict))

    promoted_claim = {
        "text": claim,
        "promoted_fact_field": "registration_deadline",
        "field_evidence_ids": list(candidate.get("claim_evidence_ids") or []),
        "article_deadline_claim_evidence_id": gate_id,
        "writer_projection_evidence_id": _norm(candidate.get("writer_projection_evidence_id")),
        "writer_consumption_evidence_id": _norm(candidate.get("writer_consumption_evidence_id")),
        "upstream_materiality_promotion_evidence_id": _norm(candidate.get("upstream_materiality_promotion_evidence_id")),
        "fact_kernel_promotion_evidence_id": _norm(candidate.get("fact_kernel_promotion_evidence_id")),
        "page_text_sha256": _norm(candidate.get("page_text_sha256")),
        "page_number": int(candidate.get("page_number") or 0),
        "excerpt": _norm(candidate.get("excerpt")),
        "state": "ARTICLE_DEADLINE_CLAIM_PROJECTED_SHADOW_PENDING_GLOBAL_INTEGRITY",
    }
    package["claims"] = [*existing_claims, promoted_claim]

    segments = [copy.deepcopy(row) for row in package.get("body_segments") or [] if isinstance(row, dict)]
    insert_at = next((i for i, row in enumerate(segments) if row.get("kind") == "kernel_when"), len(segments))
    promoted_segment = {
        "kind": "promoted_fact_claim",
        "promoted_fact_field": "registration_deadline",
        "text": claim,
        "field_evidence_ids": list(candidate.get("claim_evidence_ids") or []),
        "article_deadline_claim_evidence_id": gate_id,
        "writer_consumption_evidence_id": _norm(candidate.get("writer_consumption_evidence_id")),
        "fact_kernel_promotion_evidence_id": _norm(candidate.get("fact_kernel_promotion_evidence_id")),
    }
    segments.insert(insert_at, promoted_segment)
    for row in segments:
        if row.get("kind") == "scope_note":
            row["text"] = PROJECTED_SCOPE_NOTE
            row["evidence_ids"] = []
    package["body_segments"] = segments
    package["body"] = "\n\n".join(_norm(row.get("text")) for row in segments)
    package["rendered_promoted_claims_pending_integrity"] = []
    package["promoted_claims_projected_shadow"] = [copy.deepcopy(candidate)]
    package["writer_consumes_deadline_projection"] = True
    package["article_contains_registration_deadline"] = True
    package["canonical_promoted_claim_count"] = 1
    package["article_projection_allowed"] = False
    package["publication_authority"] = "NONE"
    excluded = [
        _norm(v)
        for v in package.get("excluded_unverified_or_non_normalized_fields") or []
        if _norm(v) and _norm(v) != "registration_deadline"
    ]
    package["excluded_unverified_or_non_normalized_fields"] = excluded

    projected["article_contains_registration_deadline"] = True
    projected["canonical_promoted_claim_count"] = 1
    projected["shadow_article_projection_applied"] = True
    projected["article_deadline_claim_evidence_id"] = gate_id
    projected["publication_authority"] = "NONE"
    projected["acceptance_ready"] = False
    projected["article_projection_allowed"] = False
    projected["site_publish_allowed"] = False
    projected["social_publish_allowed"] = False
    return projected


def validate_projected_article(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    article_report: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, Any]:
    chain = _verify_gate_candidate_against_chain(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        article_report,
        gate,
    )
    package = chain["package"]
    assert article_report.get("article_contains_registration_deadline") is True
    assert article_report.get("shadow_article_projection_applied") is True
    assert int(article_report.get("canonical_promoted_claim_count") or 0) == 1
    assert _norm(article_report.get("article_deadline_claim_evidence_id")) == chain["gate_id"]
    assert package.get("article_contains_registration_deadline") is True
    assert int(package.get("canonical_promoted_claim_count") or 0) == 1
    assert package.get("article_projection_allowed") is False
    assert package.get("publication_authority") == "NONE"
    assert not (package.get("rendered_promoted_claims_pending_integrity") or [])

    claims = package.get("claims") or []
    assert len(claims) >= 3
    promoted_rows = [row for row in claims if isinstance(row, dict) and row.get("promoted_fact_field") == "registration_deadline"]
    assert len(promoted_rows) == 1
    row = promoted_rows[0]
    assert _norm(row.get("text")) == chain["claim"]
    assert _norm(row.get("article_deadline_claim_evidence_id")) == chain["gate_id"]
    assert _norm(row.get("writer_consumption_evidence_id")) == chain["consumption_id"]
    assert _norm(row.get("writer_projection_evidence_id")) == chain["projection_id"]
    assert [_norm(v) for v in row.get("field_evidence_ids") or [] if _norm(v)] == chain["claim_evidence_ids"]
    assert _norm(row.get("fact_kernel_promotion_evidence_id")) == chain["identities"]["fact_kernel_promotion_evidence_id"]
    assert _norm(row.get("upstream_materiality_promotion_evidence_id")) == chain["identities"]["upstream_materiality_promotion_evidence_id"]
    assert _norm(row.get("page_text_sha256")) == chain["identities"]["page_text_sha256"]
    assert int(row.get("page_number") or 0) == chain["page_number"]
    assert _norm(row.get("excerpt")) == chain["excerpt"]

    segments = package.get("body_segments") or []
    promoted_segments = [
        seg for seg in segments
        if isinstance(seg, dict) and seg.get("kind") == "promoted_fact_claim"
        and seg.get("promoted_fact_field") == "registration_deadline"
    ]
    assert len(promoted_segments) == 1
    segment = promoted_segments[0]
    assert _norm(segment.get("text")) == chain["claim"]
    assert _norm(segment.get("article_deadline_claim_evidence_id")) == chain["gate_id"]
    assert _norm(segment.get("writer_consumption_evidence_id")) == chain["consumption_id"]
    assert [_norm(v) for v in segment.get("field_evidence_ids") or [] if _norm(v)] == chain["claim_evidence_ids"]

    body = _norm(package.get("body"))
    assert chain["claim"] in body
    assert chain["deadline"] not in body
    assert "2 octombrie 2026" in body
    scope_rows = [row for row in segments if isinstance(row, dict) and row.get("kind") == "scope_note"]
    assert len(scope_rows) == 1 and _norm(scope_rows[0].get("text")) == _norm(PROJECTED_SCOPE_NOTE)

    excluded = {_norm(v) for v in package.get("excluded_unverified_or_non_normalized_fields") or [] if _norm(v)}
    assert "registration_deadline" not in excluded
    assert {"interview_window_text", "appointment_decision_deadline_text"}.issubset(excluded)

    return {
        "status": "PASS_SHADOW",
        "article_id": chain["article_id"],
        "registration_deadline": chain["deadline"],
        "article_deadline_claim_evidence_id": chain["gate_id"],
        "canonical_claim_count": len(claims),
        "canonical_promoted_claim_count": 1,
        "article_contains_registration_deadline": True,
        "shadow_article_projection_applied": True,
        "fabricated_claim_count": 0,
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


def prove_projected_tamper_regressions(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    projected_article: dict[str, Any],
    gate: dict[str, Any],
) -> int:
    cases: list[tuple[str, dict[str, Any]]] = []

    detached_gate_id = copy.deepcopy(projected_article)
    promoted = detached_gate_id["articles"][0]["article_package"]["claims"][-1]
    promoted["article_deadline_claim_evidence_id"] = "isj-article-deadline-claim-detached"
    cases.append(("projected gate identity detached", detached_gate_id))

    detached_writer = copy.deepcopy(projected_article)
    detached_writer["articles"][0]["article_package"]["claims"][-1]["writer_consumption_evidence_id"] = (
        "isj-writer-deadline-consumption-detached"
    )
    cases.append(("projected writer-consumption identity detached", detached_writer))

    detached_body = copy.deepcopy(projected_article)
    segments = detached_body["articles"][0]["article_package"]["body_segments"]
    segments = [seg for seg in segments if seg.get("kind") != "promoted_fact_claim"]
    detached_body["articles"][0]["article_package"]["body_segments"] = segments
    detached_body["articles"][0]["article_package"]["body"] = "\n\n".join(_norm(seg.get("text")) for seg in segments)
    cases.append(("promoted claim removed from canonical body", detached_body))

    passed = 0
    for label, article_case in cases:
        try:
            validate_projected_article(
                fact_kernel,
                fact_integrity,
                writer_consumption,
                writer_consumption_validation,
                article_case,
                gate,
            )
        except AssertionError:
            passed += 1
            continue
        raise AssertionError(f"Projected ISJ article validator accepted tamper: {label}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Independently validate and shadow-project the verified ISJ registration-deadline claim"
    )
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
    writer_consumption_validation = json.loads(
        Path(args.writer_consumption_validation).read_text(encoding="utf-8")
    )
    article_path = Path(args.article)
    article_report = json.loads(article_path.read_text(encoding="utf-8"))
    gate = json.loads(Path(args.gate).read_text(encoding="utf-8"))

    summary = validate(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        article_report,
        gate,
    )
    preprojection_tamper = (
        prove_tamper_regressions(
            fact_kernel,
            fact_integrity,
            writer_consumption,
            writer_consumption_validation,
            article_report,
            gate,
        )
        if args.prove_tamper
        else 0
    )

    projected = project_validated_deadline_claim(article_report, gate, summary)
    projected_summary = validate_projected_article(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        projected,
        gate,
    )
    projected_tamper = (
        prove_projected_tamper_regressions(
            fact_kernel,
            fact_integrity,
            writer_consumption,
            writer_consumption_validation,
            projected,
            gate,
        )
        if args.prove_tamper
        else 0
    )

    article_path.write_text(json.dumps(projected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out = {
        **summary,
        "status": "PASS_SHADOW",
        "shadow_article_projection_applied": True,
        "article_contains_registration_deadline": True,
        "canonical_claim_count": projected_summary["canonical_claim_count"],
        "canonical_promoted_claim_count": 1,
        "tamper_regressions_passed": preprojection_tamper,
        "projected_tamper_regressions_passed": projected_tamper,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_article_mutation_allowed": False,
        "article_projection_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "truth_rule": (
            "The independent validator first rebinds the pending writer-rendered deadline claim to the exact "
            "writer-consumption and promoted FactKernel evidence chain, then applies only a shadow canonical "
            "article projection. The projected article is independently revalidated, remains non-authorizing, "
            "and cannot imply site/social delivery, merge, deployment or acceptance."
        ),
    }
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": out["status"],
                "article_deadline_claim_evidence_id": out["article_deadline_claim_evidence_id"],
                "canonical_claim_count": out["canonical_claim_count"],
                "article_contains_registration_deadline": True,
                "tamper_regressions_passed": preprojection_tamper,
                "projected_tamper_regressions_passed": projected_tamper,
                "publication_authority": "NONE",
                "acceptance_ready": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
