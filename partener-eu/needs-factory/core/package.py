from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence

from .engine import NeedsFactoryValidationError, sha256_json


def build_narrative_ready_pack(
    project_input: Mapping[str, Any],
    ranked_needs: Mapping[str, Any],
    needs_by_id: Mapping[str, Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    causal_validation: Mapping[str, Any],
    traceability_validation: Mapping[str, Any],
    release_gate: Mapping[str, Any],
) -> Dict[str, Any]:
    if not release_gate.get("ready_for_narrative"):
        raise NeedsFactoryValidationError("release gate is not ready for narrative")
    if not causal_validation.get("valid"):
        raise NeedsFactoryValidationError("causal graph is not valid")
    if not traceability_validation.get("valid"):
        raise NeedsFactoryValidationError("traceability is not valid")
    if ranked_needs.get("blocked"):
        raise NeedsFactoryValidationError("one or more needs are not rankable")

    claim_ledger = []
    for ranked in ranked_needs.get("ranked", []):
        need_id = str(ranked["need_id"])
        need = needs_by_id.get(need_id)
        if not need:
            raise NeedsFactoryValidationError(f"ranked need missing from needs registry: {need_id}")
        evidence_refs = []
        for evidence_id in need.get("evidence_ids", []):
            evidence = evidence_by_id.get(evidence_id)
            if not evidence:
                raise NeedsFactoryValidationError(f"unknown evidence in narrative pack: {evidence_id}")
            evidence_refs.append({
                "evidence_id": evidence_id,
                "source": evidence.get("source"),
                "source_url": evidence.get("source_url"),
                "territory": evidence.get("territory"),
                "period": evidence.get("period") or evidence.get("source_date") or evidence.get("publication_date"),
                "tier": evidence.get("tier"),
            })
        claim_ledger.append({
            "need_id": need_id,
            "rank": ranked.get("rank"),
            "score": ranked.get("score"),
            "confidence_used": ranked.get("confidence_used"),
            "title": need.get("title"),
            "statement": need.get("statement"),
            "scope": need.get("scope"),
            "evidence_refs": evidence_refs,
            "prohibited_overclaim": need.get("prohibited_overclaim"),
        })

    pack = {
        "schema_version": "nf.narrative_ready_pack.v0.1",
        "project_id": project_input.get("project_id") or project_input.get("project_code"),
        "territory": project_input.get("territory"),
        "target_group": project_input.get("target_group"),
        "claim_ledger": claim_ledger,
        "causal_validation": causal_validation,
        "traceability_validation": traceability_validation,
        "release_gate": release_gate,
        "narrative_policy": {
            "generate_only_from_claim_ledger": True,
            "preserve_evidence_scope": True,
            "preserve_period_and_measure_semantics": True,
            "do_not_fill_evidence_gaps": True,
            "do_not_convert_association_to_causality": True,
            "do_not_promote_compliance_to_empirical_need": True,
        },
    }
    pack["pack_sha256"] = sha256_json(pack)
    return pack
