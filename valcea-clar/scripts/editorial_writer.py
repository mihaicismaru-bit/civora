#!/usr/bin/env python3
"""VÂLCEA CLAR evidence-bound editorial writer.

The v1 writer is deliberately deterministic. It does not invent prose from a
web page or ask a remote model to fill gaps. New-style stories provide a
claim-level fact kernel; this module selects the journalistic form, orders the
verified claims, validates claim-to-source provenance and emits the canonical
reader-facing story product.

Legacy curated stories are validated and passed through without rewriting so
that activating the writer cannot silently alter already approved copy.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "editorial" / "facts_registry.json"
MANUAL = ROOT / "editorial" / "editorial_manual.json"
OUTPUT = ROOT / "editorial" / "editorial_products.json"
WRITER_ID = "manual_journalism_v1"
ELIGIBLE_SOURCE_TIERS = {"T1", "T1B", "T2", "T3"}


class EditorialHold(ValueError):
    pass


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def source_urls(item: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    for source in item.get("sources") or []:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        tier = str(source.get("tier") or "").strip()
        if url and tier in ELIGIBLE_SOURCE_TIERS:
            urls.add(url)
    return urls


def choose_format(item: dict[str, Any]) -> str:
    editorial_type = str(item.get("editorial_type") or "").strip().lower()
    section = str(item.get("section") or "").strip().upper()
    gate = str(item.get("material_fact_gate") or "").strip().upper()
    if section == "INVESTIGAȚII":
        return "investigation"
    if gate == "PASS_EXPLAINER_ONLY":
        return "explainer"
    if editorial_type == "service":
        return "service_news"
    if editorial_type == "analysis":
        return "analysis"
    return "straight_news"


def manual_format(manual: dict[str, Any], name: str) -> dict[str, Any]:
    formats = manual.get("formats") or {}
    spec = formats.get(name)
    if not isinstance(spec, dict):
        raise EditorialHold(f"unknown_editorial_format:{name}")
    return spec


def validate_manual(manual: dict[str, Any]) -> None:
    if manual.get("schema_version") != "1.0" or manual.get("writer_id") != WRITER_ID:
        raise EditorialHold("editorial_manual_identity_mismatch")
    principles = manual.get("principles") or {}
    required_true = {
        "fact_before_form",
        "claim_level_provenance_required_for_new_kernel_composition",
        "source_signal_is_not_fact",
        "headline_may_not_exceed_evidence",
        "dek_may_not_add_new_material_fact",
        "synthetic_quote_forbidden",
        "fabricated_scene_forbidden",
        "reputational_claims_fail_closed",
    }
    missing = sorted(key for key in required_true if principles.get(key) is not True)
    if missing:
        raise EditorialHold("manual_safety_rule_missing:" + ",".join(missing))
    for name in {"straight_news", "explainer", "service_news", "investigation", "analysis"}:
        manual_format(manual, name)


def validate_seed_block(block: dict[str, Any], *, name: str, valid_urls: set[str], min_chars: int, max_chars: int) -> tuple[str, list[str]]:
    if not isinstance(block, dict):
        raise EditorialHold(f"{name}_block_missing")
    text = str(block.get("text") or "").strip()
    refs = [str(url).strip() for url in block.get("source_urls") or [] if str(url).strip()]
    if len(text) < min_chars:
        raise EditorialHold(f"{name}_too_short")
    if len(text) > max_chars:
        raise EditorialHold(f"{name}_too_long")
    if not refs:
        raise EditorialHold(f"{name}_source_missing")
    unknown = sorted(set(refs) - valid_urls)
    if unknown:
        raise EditorialHold(f"{name}_unknown_source:" + ",".join(unknown))
    return text, refs


def validate_claim(claim: dict[str, Any], valid_urls: set[str], min_chars: int, allowed_kinds: set[str]) -> dict[str, Any]:
    if not isinstance(claim, dict):
        raise EditorialHold("claim_not_object")
    claim_id = str(claim.get("id") or "").strip()
    role = str(claim.get("role") or "").strip()
    text = str(claim.get("text") or "").strip()
    kind = str(claim.get("kind") or "").strip()
    refs = [str(url).strip() for url in claim.get("source_urls") or [] if str(url).strip()]
    if not claim_id:
        raise EditorialHold("claim_id_missing")
    if not role:
        raise EditorialHold(f"claim_role_missing:{claim_id}")
    if len(text) < min_chars:
        raise EditorialHold(f"claim_too_short:{claim_id}")
    if kind not in allowed_kinds:
        raise EditorialHold(f"claim_kind_invalid:{claim_id}")
    if not refs:
        raise EditorialHold(f"claim_source_missing:{claim_id}")
    unknown = sorted(set(refs) - valid_urls)
    if unknown:
        raise EditorialHold(f"claim_unknown_source:{claim_id}:" + ",".join(unknown))
    if kind == "attributed_statement" and not str(claim.get("attribution") or "").strip():
        raise EditorialHold(f"attribution_missing:{claim_id}")
    return {
        "id": claim_id,
        "role": role,
        "text": text,
        "kind": kind,
        "source_urls": refs,
        **({"attribution": str(claim.get("attribution")).strip()} if claim.get("attribution") else {}),
    }


def compose_from_kernel(item: dict[str, Any], manual: dict[str, Any]) -> dict[str, Any]:
    kernel = item.get("fact_kernel")
    if not isinstance(kernel, dict):
        raise EditorialHold("fact_kernel_missing")
    valid_urls = source_urls(item)
    if not valid_urls:
        raise EditorialHold("story_sources_missing")

    contract = manual.get("new_fact_kernel_contract") or {}
    headline_spec = contract.get("headline") or {}
    dek_spec = contract.get("dek") or {}
    claim_spec = contract.get("claim") or {}
    headline, headline_refs = validate_seed_block(
        kernel.get("headline") or {},
        name="headline",
        valid_urls=valid_urls,
        min_chars=int(headline_spec.get("min_chars") or 12),
        max_chars=int(headline_spec.get("max_chars") or 140),
    )
    dek, dek_refs = validate_seed_block(
        kernel.get("dek") or {},
        name="dek",
        valid_urls=valid_urls,
        min_chars=int(dek_spec.get("min_chars") or 35),
        max_chars=int(dek_spec.get("max_chars") or 300),
    )

    allowed_kinds = set(claim_spec.get("allowed_kinds") or [])
    min_claim_chars = int(claim_spec.get("minimum_text_chars") or 24)
    raw_claims = kernel.get("claims") or []
    claims = [validate_claim(row, valid_urls, min_claim_chars, allowed_kinds) for row in raw_claims]
    claim_ids = [row["id"] for row in claims]
    if len(claim_ids) != len(set(claim_ids)):
        raise EditorialHold("duplicate_claim_id")

    format_name = str(kernel.get("format_hint") or choose_format(item)).strip()
    spec = manual_format(manual, format_name)
    if len(claims) < int(spec.get("minimum_claims") or 1):
        raise EditorialHold("insufficient_claim_count")
    distinct_refs = {url for claim in claims for url in claim["source_urls"]}
    if len(distinct_refs) < int(spec.get("minimum_distinct_source_urls") or 1):
        raise EditorialHold("insufficient_source_diversity")

    role_order = [str(role) for role in spec.get("role_order") or []]
    rank = {role: index for index, role in enumerate(role_order)}
    ordered = sorted(enumerate(claims), key=lambda pair: (rank.get(pair[1]["role"], len(rank)), pair[0]))
    ordered_claims = [claim for _, claim in ordered]
    paragraphs = [claim["text"] for claim in ordered_claims]
    if not paragraphs:
        raise EditorialHold("no_body_claims")

    product = copy.deepcopy(item)
    product["headline"] = headline
    product["dek"] = dek
    product["paragraphs"] = paragraphs
    product["editorial_product"] = {
        "writer_id": WRITER_ID,
        "writer_mode": "FACT_KERNEL_COMPOSED",
        "format": format_name,
        "claim_trace_complete": True,
        "source_level_trace": True,
        "headline_source_urls": headline_refs,
        "dek_source_urls": dek_refs,
        "claim_trace": [
            {
                "claim_id": claim["id"],
                "role": claim["role"],
                "kind": claim["kind"],
                "text_sha256": hashlib.sha256(claim["text"].encode("utf-8")).hexdigest(),
                "source_urls": claim["source_urls"],
            }
            for claim in ordered_claims
        ],
        "auto_publish_eligible_by_format": bool(spec.get("auto_publish_eligible")),
        "additional_gate": spec.get("additional_gate"),
    }
    if spec.get("auto_publish_eligible") is not True:
        product["status"] = "editorial_hold"
        product["editorial_product"]["hold_reason"] = str(spec.get("additional_gate") or "EDITORIAL_REVIEW")
    product["editorial_product"]["product_fingerprint_sha256"] = canonical_digest({
        "id": product.get("id"),
        "headline": headline,
        "dek": dek,
        "paragraphs": paragraphs,
        "format": format_name,
        "claim_trace": product["editorial_product"]["claim_trace"],
    })
    return product


def validate_legacy(item: dict[str, Any]) -> dict[str, Any]:
    product = copy.deepcopy(item)
    headline = str(product.get("headline") or "").strip()
    dek = str(product.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in product.get("paragraphs") or [] if str(p).strip()]
    valid_urls = source_urls(product)
    if not headline or not dek or not paragraphs or not valid_urls:
        product["status"] = "editorial_hold"
        reason = "legacy_story_incomplete"
    else:
        reason = None
    product["editorial_product"] = {
        "writer_id": WRITER_ID,
        "writer_mode": "LEGACY_VERIFIED_PASSTHROUGH",
        "format": choose_format(product),
        "claim_trace_complete": False,
        "source_level_trace": True,
        "legacy_copy_rewritten": False,
        "auto_publish_eligible_by_format": True,
        **({"hold_reason": reason} if reason else {}),
    }
    product["editorial_product"]["product_fingerprint_sha256"] = canonical_digest({
        "id": product.get("id"),
        "headline": headline,
        "dek": dek,
        "paragraphs": paragraphs,
        "source_urls": sorted(valid_urls),
    })
    return product


def transform_item(item: dict[str, Any], manual: dict[str, Any]) -> dict[str, Any]:
    if item.get("fact_kernel") is None:
        return validate_legacy(item)
    try:
        return compose_from_kernel(item, manual)
    except EditorialHold as exc:
        product = copy.deepcopy(item)
        product["status"] = "editorial_hold"
        product["editorial_product"] = {
            "writer_id": WRITER_ID,
            "writer_mode": "FACT_KERNEL_REJECTED_FAIL_CLOSED",
            "format": choose_format(item),
            "claim_trace_complete": False,
            "source_level_trace": bool(source_urls(item)),
            "auto_publish_eligible_by_format": False,
            "hold_reason": str(exc),
        }
        return product


def materialize_curated_registry(*, write_output: bool = True) -> dict[str, Any]:
    manual = load(MANUAL)
    validate_manual(manual)
    source_doc = load(FACTS)
    products = [transform_item(item, manual) for item in source_doc.get("facts") or []]
    output = {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "product": "VÂLCEA CLAR editorial story products",
        "writer_id": WRITER_ID,
        "source_registry": "editorial/facts_registry.json",
        "manual": "editorial/editorial_manual.json",
        "facts": products,
        "stats": {
            "story_count": len(products),
            "fact_kernel_composed": sum(1 for row in products if (row.get("editorial_product") or {}).get("writer_mode") == "FACT_KERNEL_COMPOSED"),
            "legacy_passthrough": sum(1 for row in products if (row.get("editorial_product") or {}).get("writer_mode") == "LEGACY_VERIFIED_PASSTHROUGH"),
            "editorial_holds": sum(1 for row in products if row.get("status") == "editorial_hold"),
        },
        "policy": {
            "writer_may_add_unsupported_fact": False,
            "new_kernel_claim_level_provenance_required": True,
            "legacy_copy_rewritten": False,
            "reputational_formats_fail_closed": True,
            "satire_routed_separately": True,
        },
    }
    output["registry_fingerprint_sha256"] = canonical_digest({
        "writer_id": WRITER_ID,
        "facts": products,
        "policy": output["policy"],
    })
    if write_output:
        OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def self_test() -> int:
    manual = load(MANUAL)
    validate_manual(manual)
    source = {"name": "Primăria", "url": "https://example.test/h1", "tier": "T1"}
    base = {
        "id": "writer-test",
        "status": "verified",
        "section": "ADMINISTRAȚIE",
        "priority": 90,
        "confidence": 99,
        "material_fact_gate": "PASS",
        "headline": "Legacy headline remains unused for the kernel test",
        "dek": "Legacy dek remains unused when a valid claim-level fact kernel is supplied to the editorial writer.",
        "paragraphs": ["Legacy paragraph that must not leak into a kernel-composed product."],
        "sources": [source],
        "fact_kernel": {
            "headline": {"text": "Primăria aprobă proiectul verificat pentru centrul orașului", "source_urls": [source["url"]]},
            "dek": {"text": "Hotărârea publicată stabilește măsura, calendarul și cadrul necesar pentru implementarea proiectului.", "source_urls": [source["url"]]},
            "claims": [
                {"id": "c2", "role": "context", "kind": "documented_context", "text": "Documentul oficial include calendarul de implementare și responsabilitățile instituției locale.", "source_urls": [source["url"]]},
                {"id": "c1", "role": "material_change", "kind": "fact", "text": "Consiliul local a aprobat proiectul prin hotărârea publicată în registrul oficial al municipalității.", "source_urls": [source["url"]]}
            ]
        }
    }
    product = transform_item(base, manual)
    assert product["status"] == "verified"
    assert product["paragraphs"][0].startswith("Consiliul local")
    meta = product["editorial_product"]
    assert meta["writer_mode"] == "FACT_KERNEL_COMPOSED"
    assert meta["claim_trace_complete"] is True
    assert meta["format"] == "straight_news"

    bad = copy.deepcopy(base)
    bad["id"] = "writer-bad-source"
    bad["fact_kernel"]["claims"][0]["source_urls"] = ["https://unknown.test/"]
    held = transform_item(bad, manual)
    assert held["status"] == "editorial_hold"
    assert held["editorial_product"]["writer_mode"] == "FACT_KERNEL_REJECTED_FAIL_CLOSED"

    investigation = copy.deepcopy(base)
    investigation["id"] = "writer-investigation"
    investigation["section"] = "INVESTIGAȚII"
    investigation["sources"].append({"name": "Registru 2", "url": "https://example.test/h2", "tier": "T1"})
    investigation["fact_kernel"]["headline"]["source_urls"].append("https://example.test/h2")
    investigation["fact_kernel"]["dek"]["source_urls"].append("https://example.test/h2")
    investigation["fact_kernel"]["claims"] = [
        {"id": "i1", "role": "documented_finding", "kind": "fact", "text": "Două registre publice documentează aceeași modificare relevantă pentru proiectul urmărit.", "source_urls": ["https://example.test/h1", "https://example.test/h2"]},
        {"id": "i2", "role": "evidence", "kind": "documented_context", "text": "Primul registru consemnează hotărârea, iar al doilea documentează procedura asociată acesteia.", "source_urls": ["https://example.test/h1", "https://example.test/h2"]},
        {"id": "i3", "role": "what_is_unknown", "kind": "documented_context", "text": "Documentele disponibile nu permit încă atribuirea unei conduite nelegale unei persoane sau companii.", "source_urls": ["https://example.test/h1", "https://example.test/h2"]}
    ]
    inv = transform_item(investigation, manual)
    assert inv["status"] == "editorial_hold"
    assert inv["editorial_product"]["hold_reason"] == "REPUTATIONAL_EDITORIAL_REVIEW"

    legacy = dict(base)
    legacy.pop("fact_kernel")
    legacy_product = transform_item(legacy, manual)
    assert legacy_product["headline"] == legacy["headline"]
    assert legacy_product["editorial_product"]["legacy_copy_rewritten"] is False
    print("VÂLCEA CLAR editorial writer v1 self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    doc = materialize_curated_registry(write_output=not args.check)
    if args.check:
        assert doc.get("writer_id") == WRITER_ID
        assert (doc.get("policy") or {}).get("writer_may_add_unsupported_fact") is False
        assert all((row.get("editorial_product") or {}).get("writer_id") == WRITER_ID for row in doc.get("facts") or [])
        print(json.dumps({"status": "PASS", **doc["stats"]}, ensure_ascii=False))
        return 0
    print(json.dumps({"status": "PASS", **doc["stats"], "output": str(OUTPUT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
