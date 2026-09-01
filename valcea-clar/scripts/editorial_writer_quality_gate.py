#!/usr/bin/env python3
"""Bind canonical VÂLCEA CLAR Editorial Writer output to writing-quality checks.

The canonical writer and the writing-quality validator intentionally remain
separate concerns. This adapter verifies the writer's claim trace, maps only
explicit evidence-bound fields into the quality contract, and emits a
read-only quality receipt. It never rewrites copy, adds facts, changes source
provenance, authorizes publication, or mutates the Fact Kernel.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import editorial_writer

ROOT = Path(__file__).resolve().parents[1]
QUALITY_PATH = ROOT / "editorial" / "editorial_writing_quality.py"
CONTRACT = "VALCEA_CLAR_EDITORIAL_WRITER_QUALITY_ADAPTER_V1"
WRITER_ID = "manual_journalism_v1"
QUALITY_CONTRACT = "VALCEA_CLAR_EDITORIAL_WRITING_QUALITY_V1"

FORMAT_MAP = {
    "straight_news": "REPORT",
    "explainer": "EXPLAINER",
    "service_news": "SERVICE",
}
EXPLICIT_STRAIGHT_NEWS_TYPES = {
    "update": "UPDATE",
    "breaking": "BREAKING",
    "feature": "FEATURE",
}
REVIEW_ONLY_FORMATS = {"investigation", "analysis"}


def _load_quality_module():
    spec = importlib.util.spec_from_file_location("valcea_clar_editorial_writing_quality", QUALITY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("quality_module_load_failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if getattr(module, "CONTRACT", None) != QUALITY_CONTRACT:
        raise RuntimeError("quality_contract_mismatch")
    return module


quality = _load_quality_module()


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _base_receipt(product: dict[str, Any]) -> dict[str, Any]:
    editorial = product.get("editorial_product") or {}
    return {
        "contract": CONTRACT,
        "writer_id": editorial.get("writer_id"),
        "writer_mode": editorial.get("writer_mode"),
        "canonical_format": editorial.get("format"),
        "story_id": product.get("id"),
        "writer_product_fingerprint_sha256": editorial.get("product_fingerprint_sha256"),
        "quality_contract": QUALITY_CONTRACT,
        "quality_gate_passed": False,
        "capabilities": {
            "publication_authorized": False,
            "automatic_rewrite_authorized": False,
            "fact_inference_authorized": False,
            "fact_kernel_mutation_authorized": False,
            "source_provenance_mutation_authorized": False,
            "breaking_promotion_authorized": False,
            "writer_output_mutation_authorized": False,
        },
    }


def _hold(product: dict[str, Any], status: str, reason: str, **details: Any) -> dict[str, Any]:
    receipt = _base_receipt(product)
    receipt.update(
        {
            "status": status,
            "quality_gate_passed": False,
            "hold_reason": reason,
            "details": details or {},
        }
    )
    return receipt


def _story_type(product: dict[str, Any]) -> str | None:
    editorial = product.get("editorial_product") or {}
    canonical_format = _text(editorial.get("format")).lower()
    if canonical_format == "straight_news":
        explicit = _text(product.get("editorial_type")).lower()
        return EXPLICIT_STRAIGHT_NEWS_TYPES.get(explicit, "REPORT")
    return FORMAT_MAP.get(canonical_format)


def _source_rows(product: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in product.get("sources") or []:
        if not isinstance(source, dict):
            continue
        url = _text(source.get("url"))
        tier = _text(source.get("tier"))
        if url and tier in editorial_writer.ELIGIBLE_SOURCE_TIERS:
            rows.append({"url": url, "tier": tier, "name": _text(source.get("name"))})
    return rows


def _join_roles(claims: list[dict[str, Any]], roles: set[str]) -> str:
    return " ".join(_text(claim.get("text")) for claim in claims if _text(claim.get("role")) in roles).strip()


def _verified_claims(product: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    editorial = product.get("editorial_product") or {}
    kernel = product.get("fact_kernel")
    if not isinstance(kernel, dict):
        return [], "fact_kernel_missing"
    raw_claims = kernel.get("claims") or []
    if not isinstance(raw_claims, list) or not raw_claims:
        return [], "fact_kernel_claims_missing"
    by_id: dict[str, dict[str, Any]] = {}
    for raw in raw_claims:
        if not isinstance(raw, dict):
            return [], "fact_kernel_claim_not_object"
        claim_id = _text(raw.get("id"))
        if not claim_id or claim_id in by_id:
            return [], "fact_kernel_claim_identity_invalid"
        by_id[claim_id] = raw

    trace = editorial.get("claim_trace") or []
    paragraphs = [_text(value) for value in product.get("paragraphs") or [] if _text(value)]
    if editorial.get("claim_trace_complete") is not True or not isinstance(trace, list) or not trace:
        return [], "writer_claim_trace_incomplete"
    if len(trace) != len(paragraphs):
        return [], "writer_claim_trace_paragraph_count_mismatch"

    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    valid_source_urls = {row["url"] for row in _source_rows(product)}
    for index, trace_row in enumerate(trace):
        if not isinstance(trace_row, dict):
            return [], "writer_claim_trace_not_object"
        claim_id = _text(trace_row.get("claim_id"))
        if not claim_id or claim_id in seen or claim_id not in by_id:
            return [], "writer_claim_trace_identity_invalid"
        seen.add(claim_id)
        claim = by_id[claim_id]
        text = _text(claim.get("text"))
        if not text or text != paragraphs[index]:
            return [], f"writer_claim_text_mismatch:{claim_id}"
        if _text(trace_row.get("text_sha256")) != _sha256(text):
            return [], f"writer_claim_hash_mismatch:{claim_id}"
        claim_urls = [_text(url) for url in claim.get("source_urls") or [] if _text(url)]
        trace_urls = [_text(url) for url in trace_row.get("source_urls") or [] if _text(url)]
        if not claim_urls or sorted(set(claim_urls)) != sorted(set(trace_urls)):
            return [], f"writer_claim_source_trace_mismatch:{claim_id}"
        if not set(claim_urls).issubset(valid_source_urls):
            return [], f"writer_claim_source_outside_story:{claim_id}"
        ordered.append(
            {
                "id": claim_id,
                "role": _text(claim.get("role")),
                "kind": _text(claim.get("kind")),
                "text": text,
                "source_urls": claim_urls,
            }
        )
    if len(seen) != len(by_id):
        return [], "writer_claim_trace_does_not_cover_kernel"
    return ordered, None


def _quality_input(product: dict[str, Any], claims: list[dict[str, Any]], story_type: str) -> dict[str, Any]:
    paragraphs = [_text(value) for value in product.get("paragraphs") or [] if _text(value)]
    lead = paragraphs[0] if paragraphs else ""
    body = "\n\n".join(paragraphs[1:])
    return {
        "story_type": story_type,
        "headline": _text(product.get("headline")),
        "lead": lead,
        "body": body,
        "provenance": _source_rows(product),
        "confirmed_facts": [
            {
                "id": claim["id"],
                "text": claim["text"],
                "source_urls": claim["source_urls"],
                "kind": claim["kind"],
            }
            for claim in claims
        ],
        "locality_context": product.get("locality_context"),
        "why_it_matters": _join_roles(claims, {"consequence", "meaning"}),
        "unknowns": _join_roles(claims, {"what_is_unknown", "uncertainty"}),
        "next_steps": _join_roles(claims, {"reader_action", "next_watch"}),
        "what_changed": _join_roles(claims, {"material_change"}),
    }


def evaluate_writer_product(product: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(product, dict):
        return _hold({}, "FAIL", "writer_product_not_object")
    editorial = product.get("editorial_product") or {}
    if not isinstance(editorial, dict):
        return _hold(product, "FAIL", "editorial_product_missing")
    if editorial.get("writer_id") != WRITER_ID:
        return _hold(product, "FAIL", "writer_identity_mismatch")
    mode = _text(editorial.get("writer_mode"))
    if mode == "LEGACY_VERIFIED_PASSTHROUGH":
        return _hold(
            product,
            "NOT_EVALUABLE_LEGACY",
            "legacy_copy_has_no_claim_level_fact_kernel",
            human_editorial_review_required=True,
        )
    if mode != "FACT_KERNEL_COMPOSED":
        return _hold(product, "FAIL", "writer_product_not_composed", writer_mode=mode)
    if editorial.get("source_level_trace") is not True:
        return _hold(product, "FAIL", "writer_source_trace_incomplete")

    canonical_format = _text(editorial.get("format")).lower()
    if canonical_format in REVIEW_ONLY_FORMATS:
        return _hold(
            product,
            "REVIEW_REQUIRED_CANONICAL_FORMAT",
            "canonical_format_requires_human_editorial_review",
            canonical_format=canonical_format,
        )
    story_type = _story_type(product)
    if story_type is None:
        return _hold(product, "FAIL", "canonical_format_has_no_quality_mapping", canonical_format=canonical_format)

    claims, claim_error = _verified_claims(product)
    if claim_error:
        return _hold(product, "FAIL", claim_error)
    quality_input = _quality_input(product, claims, story_type)
    result = quality.evaluate(quality_input)
    receipt = _base_receipt(product)
    receipt.update(
        {
            "status": result.get("status"),
            "story_type": story_type,
            "quality_gate_passed": result.get("status") == "PASS",
            "quality_result": result,
            "mapping_semantics": {
                "lead_from_first_verified_writer_claim": True,
                "body_from_remaining_verified_writer_claims": True,
                "confirmed_facts_from_fact_kernel_claims_only": True,
                "provenance_from_writer_eligible_story_sources_only": True,
                "context_fields_from_explicit_claim_roles_only": True,
                "dek_treated_as_lead": False,
                "copy_or_fact_inference": False,
            },
        }
    )
    return receipt


def evaluate_source_item(item: dict[str, Any], manual: dict[str, Any] | None = None) -> dict[str, Any]:
    active_manual = manual or editorial_writer.load(editorial_writer.MANUAL)
    editorial_writer.validate_manual(active_manual)
    product = editorial_writer.transform_item(item, active_manual)
    return evaluate_writer_product(product)


def _source(name: str, suffix: str = "official") -> dict[str, Any]:
    return {"name": name, "url": f"https://example.test/{suffix}", "tier": "T1"}


def _fact(*, editorial_type: str | None = None, format_hint: str = "straight_news", first_text: str | None = None) -> dict[str, Any]:
    source = _source("Primăria Râmnicu Vâlcea")
    item: dict[str, Any] = {
        "id": "quality-writer-report",
        "status": "verified",
        "section": "ADMINISTRAȚIE",
        "priority": 90,
        "confidence": 99,
        "material_fact_gate": "PASS",
        "sources": [source],
        "fact_kernel": {
            "format_hint": format_hint,
            "headline": {
                "text": "Râmnicu Vâlcea aprobă lucrări pentru zona centrală",
                "source_urls": [source["url"]],
            },
            "dek": {
                "text": "Hotărârea publicată de municipalitate stabilește lucrările și cadrul administrativ pentru proiect.",
                "source_urls": [source["url"]],
            },
            "claims": [
                {
                    "id": "c1",
                    "role": "material_change",
                    "kind": "fact",
                    "text": first_text or "Primăria Râmnicu Vâlcea a aprobat lucrările prevăzute pentru zona centrală a municipiului.",
                    "source_urls": [source["url"]],
                },
                {
                    "id": "c2",
                    "role": "consequence",
                    "kind": "documented_context",
                    "text": "Documentația oficială arată că intervenția privește spațiul public folosit zilnic de locuitorii din centru.",
                    "source_urls": [source["url"]],
                },
                {
                    "id": "c3",
                    "role": "next_watch",
                    "kind": "documented_context",
                    "text": "Următorul reper verificabil este publicarea calendarului de execuție de către administrația locală.",
                    "source_urls": [source["url"]],
                },
            ],
        },
    }
    if editorial_type:
        item["editorial_type"] = editorial_type
    return item


def self_test() -> int:
    manual = editorial_writer.load(editorial_writer.MANUAL)
    editorial_writer.validate_manual(manual)

    report = evaluate_source_item(_fact(), manual)
    assert report["status"] == "PASS", report
    assert report["quality_gate_passed"] is True
    assert report["story_type"] == "REPORT"
    assert report["mapping_semantics"]["confirmed_facts_from_fact_kernel_claims_only"] is True
    assert report["capabilities"]["publication_authorized"] is False

    update = evaluate_source_item(_fact(editorial_type="update"), manual)
    assert update["status"] == "PASS", update
    assert update["story_type"] == "UPDATE"
    assert update["quality_gate_passed"] is True

    mechanical = evaluate_source_item(
        _fact(first_text="În cadrul unei ședințe organizate la Râmnicu Vâlcea, municipalitatea a aprobat lucrările pentru zona centrală."),
        manual,
    )
    assert mechanical["status"] == "WARN", mechanical
    assert mechanical["quality_gate_passed"] is False
    assert "BUREAUCRATIC_LEAD" in {row["code"] for row in mechanical["quality_result"]["diagnostics"]}

    service_source = _source("Operatorul regional", "service")
    service_item = {
        "id": "quality-writer-service",
        "status": "verified",
        "section": "SERVICII",
        "editorial_type": "service",
        "priority": 92,
        "confidence": 99,
        "material_fact_gate": "PASS",
        "sources": [service_source],
        "fact_kernel": {
            "format_hint": "service_news",
            "headline": {"text": "Râmnicu Vâlcea: lucrări programate la rețeaua de apă", "source_urls": [service_source["url"]]},
            "dek": {"text": "Operatorul regional anunță lucrări programate și indică zona în care furnizarea serviciului va fi afectată.", "source_urls": [service_source["url"]]},
            "claims": [
                {"id": "s1", "role": "material_change", "kind": "reader_service", "text": "Operatorul regional anunță lucrări programate la rețeaua de apă din Râmnicu Vâlcea.", "source_urls": [service_source["url"]]},
                {"id": "s2", "role": "reader_action", "kind": "reader_service", "text": "Locuitorii din zona indicată sunt sfătuiți să își asigure necesarul de apă înainte de începerea lucrărilor.", "source_urls": [service_source["url"]]},
                {"id": "s3", "role": "who_what_when_where", "kind": "fact", "text": "Anunțul oficial identifică zona centrală din Râmnicu Vâlcea drept aria vizată de intervenție.", "source_urls": [service_source["url"]]},
            ],
        },
    }
    service = evaluate_source_item(service_item, manual)
    assert service["status"] == "PASS", service
    assert service["story_type"] == "SERVICE"

    product = editorial_writer.transform_item(_fact(), manual)
    product["paragraphs"][0] += " modificat"
    tampered = evaluate_writer_product(product)
    assert tampered["status"] == "FAIL"
    assert tampered["hold_reason"].startswith("writer_claim_text_mismatch")

    legacy = editorial_writer.transform_item(
        {
            "id": "legacy",
            "status": "verified",
            "headline": "Titlu verificat",
            "dek": "Subtitlu verificat suficient de lung pentru povestea existentă.",
            "paragraphs": ["Text existent verificat, păstrat fără rescriere automată."],
            "sources": [_source("Sursă oficială", "legacy")],
        },
        manual,
    )
    legacy_receipt = evaluate_writer_product(legacy)
    assert legacy_receipt["status"] == "NOT_EVALUABLE_LEGACY"
    assert legacy_receipt["quality_gate_passed"] is False

    source_a = _source("Sursa A", "investigation-a")
    source_b = _source("Sursa B", "investigation-b")
    investigation_item = {
        "id": "investigation",
        "status": "verified",
        "section": "INVESTIGAȚII",
        "sources": [source_a, source_b],
        "fact_kernel": {
            "format_hint": "investigation",
            "headline": {"text": "Documente publice despre un proiect local verificat", "source_urls": [source_a["url"]]},
            "dek": {"text": "Documentele oficiale oferă date verificabile care necesită revizuire editorială înainte de publicare.", "source_urls": [source_a["url"], source_b["url"]]},
            "claims": [
                {"id": "i1", "role": "documented_finding", "kind": "fact", "text": "Primul document oficial consemnează existența proiectului local analizat în această verificare.", "source_urls": [source_a["url"]]},
                {"id": "i2", "role": "evidence", "kind": "documented_context", "text": "Al doilea document oferă o evidență independentă care trebuie confruntată editorial cu primul document.", "source_urls": [source_b["url"]]},
                {"id": "i3", "role": "context", "kind": "documented_context", "text": "Contextul disponibil rămâne limitat la faptele documentate și nu autorizează inferențe suplimentare.", "source_urls": [source_a["url"], source_b["url"]]},
            ],
        },
    }
    investigation = evaluate_source_item(investigation_item, manual)
    assert investigation["status"] == "REVIEW_REQUIRED_CANONICAL_FORMAT"
    assert investigation["quality_gate_passed"] is False

    print("editorial writer -> writing quality adapter self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--input", type=Path, help="Read a canonical Editorial Writer product JSON and print a quality receipt.")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.input:
        parser.error("--input or --self-test is required")
    product = json.loads(args.input.read_text(encoding="utf-8"))
    print(json.dumps(evaluate_writer_product(product), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
