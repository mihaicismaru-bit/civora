from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from contracts import AuditResult, ContractViolation, FactKernel, PublicationReceipt, StoryTransaction, Visual


@dataclass(frozen=True)
class CycleStage:
    name: str
    argv: tuple[str, ...]
    output: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "argv": list(self.argv), "output": str(self.output) if self.output is not None else None}


def _kernel(doc: dict[str, Any]) -> FactKernel:
    return FactKernel(
        what=str(doc.get("what") or ""), who=str(doc.get("who") or ""), where=str(doc.get("where") or ""),
        when=str(doc.get("when") or ""), why_it_matters=str(doc.get("why_it_matters") or ""), source=str(doc.get("source") or ""),
        source_url=str(doc.get("source_url") or ""), claims=tuple(str(v) for v in doc.get("claims") or []),
        evidence_ids=tuple(str(v) for v in doc.get("evidence_ids") or []),
    )


def _visual(doc: dict[str, Any]) -> Visual:
    return Visual(
        kind=str(doc.get("kind") or ""), synthetic=bool(doc.get("synthetic")), source_url=str(doc.get("source_url") or ""),
        rights_basis=str(doc.get("rights_basis") or ""), semantic_relevance=str(doc.get("semantic_relevance") or ""),
        editor_approved=bool(doc.get("editor_approved")), contextual_archive=bool(doc.get("contextual_archive")),
        context_disclosure=doc.get("context_disclosure"), credit=doc.get("credit"),
    )


def _receipt(channel: str, doc: dict[str, Any]) -> PublicationReceipt:
    return PublicationReceipt(
        channel=channel, status=str(doc.get("status") or ""), canonical_url=doc.get("canonical_url"), remote_id=doc.get("remote_id"),
        receipt_id=doc.get("receipt_id"), readback_ok=bool(doc.get("readback_ok")),
        observed_at=str(doc.get("observed_at") or "") or PublicationReceipt(channel=channel, status="PENDING").observed_at,
    )


def run_shadow(payload: dict[str, Any]) -> StoryTransaction:
    story_id = str(payload.get("story_id") or "").strip()
    if not story_id:
        raise ContractViolation("story_id is required")
    tx = StoryTransaction(story_id=story_id, signal_id=payload.get("signal_id"))
    if payload.get("material_signal") is False:
        tx.no_story(str(payload.get("no_story_reason") or "no material signal"))
        return tx
    tx.verify(_kernel(payload.get("fact_kernel") or {}))
    tx.write(str(payload.get("article") or ""))
    if payload.get("visual"):
        tx.attach_visual(_visual(payload["visual"]))
    if payload.get("site_receipt"):
        tx.publish_site(_receipt("site", payload["site_receipt"]))
    for channel in ("facebook", "instagram"):
        row = (payload.get("social_receipts") or {}).get(channel)
        if not row:
            continue
        if str(row.get("status") or "").upper() == "FAILED":
            tx.fail_distribution(channel, str(row.get("reason") or "external delivery failed"))
            continue
        tx.deliver_social(_receipt(channel, row))
    audit_doc = payload.get("audit")
    if audit_doc:
        tx.audit_story(AuditResult(
            status=str(audit_doc.get("status") or ""), external_truth_ok=bool(audit_doc.get("external_truth_ok")),
            duplicates=int(audit_doc.get("duplicates") or 0), fabricated_claims=int(audit_doc.get("fabricated_claims") or 0),
            manual_intervention=int(audit_doc.get("manual_intervention") or 0), unresolved_material_signals=int(audit_doc.get("unresolved_material_signals") or 0),
            evidence=tuple(str(v) for v in audit_doc.get("evidence") or []),
        ))
    return tx


def bounded_cycle_plan(workdir: Path, *, live: bool) -> tuple[CycleStage, ...]:
    """Return the single ordered Core v2 read-only shadow execution plan."""
    py = sys.executable
    live_flag = ("--live",) if live else ()

    apavil = workdir / "valcea-core-v2-apavil-shadow.json"
    ipj = workdir / "valcea-core-v2-ipj-shadow.json"
    isu = workdir / "valcea-core-v2-isu-shadow.json"
    municipal_refs = workdir / "valcea-core-v2-municipal-shadow.json"
    municipal_docs = workdir / "valcea-core-v2-municipal-documents.json"
    municipal_materiality = workdir / "valcea-core-v2-municipal-materiality.json"
    municipal_kernels = workdir / "valcea-core-v2-municipal-fact-kernels.json"
    municipal_articles = workdir / "valcea-core-v2-municipal-articles.json"
    cj = workdir / "valcea-core-v2-cj-road-shadow.json"
    eta = workdir / "valcea-core-v2-eta-shadow.json"

    isj = workdir / "valcea-core-v2-isj-shadow.json"
    isj_detail = workdir / "valcea-core-v2-isj-detail-shadow.json"
    isj_materiality = workdir / "valcea-core-v2-isj-materiality-shadow.json"
    isj_embedded = workdir / "valcea-core-v2-isj-embedded-notice-shadow.json"
    isj_targets = workdir / "valcea-core-v2-isj-embedded-target-shadow.json"
    isj_content = workdir / "valcea-core-v2-isj-embedded-content-shadow.json"
    isj_fields = workdir / "valcea-core-v2-isj-field-evidence-shadow.json"
    isj_context = workdir / "valcea-core-v2-isj-context-documents-shadow.json"
    isj_calendar_fields = workdir / "valcea-core-v2-isj-calendar-field-evidence-shadow.json"
    isj_calendar_scope = workdir / "valcea-core-v2-isj-calendar-scope-binding-shadow.json"
    isj_calendar_scope_validation = workdir / "valcea-core-v2-isj-calendar-scope-validation.json"
    isj_deadline_promotion = workdir / "valcea-core-v2-isj-registration-deadline-promotion.json"
    isj_deadline_promotion_validation = workdir / "valcea-core-v2-isj-registration-deadline-promotion-validation.json"
    isj_field_materiality = workdir / "valcea-core-v2-isj-field-materiality-shadow.json"
    isj_fact_kernel_deadline_promotion = workdir / "valcea-core-v2-isj-fact-kernel-deadline-promotion.json"
    isj_fact_kernel_deadline_promotion_validation = workdir / "valcea-core-v2-isj-fact-kernel-deadline-promotion-validation.json"
    isj_fact_kernel = workdir / "valcea-core-v2-isj-fact-kernel-shadow.json"
    isj_fact_integrity = workdir / "valcea-core-v2-isj-fact-kernel-integrity-shadow.json"
    isj_writer_deadline_projection = workdir / "valcea-core-v2-isj-writer-deadline-projection.json"
    isj_writer_deadline_projection_validation = workdir / "valcea-core-v2-isj-writer-deadline-projection-validation.json"
    isj_writer_deadline_consumption = workdir / "valcea-core-v2-isj-writer-deadline-consumption.json"
    isj_writer_deadline_consumption_validation = workdir / "valcea-core-v2-isj-writer-deadline-consumption-validation.json"
    isj_article = workdir / "valcea-core-v2-isj-article-shadow.json"
    isj_article_deadline_claim = workdir / "valcea-core-v2-isj-article-deadline-claim.json"
    isj_article_deadline_claim_validation = workdir / "valcea-core-v2-isj-article-deadline-claim-validation.json"
    isj_article_integrity = workdir / "valcea-core-v2-isj-article-integrity-shadow.json"
    isj_promoted_claim_contract = workdir / "valcea-core-v2-isj-promoted-claim-contract.json"
    isj_promoted_claim_contract_validation = workdir / "valcea-core-v2-isj-promoted-claim-contract-validation.json"

    site_article_ledger = workdir / "valcea-core-v2-site-verified-article-ledger.json"
    photo = workdir / "valcea-core-v2-photo-truth.json"
    site_visual_registry = workdir / "valcea-core-v2-site-visual-runtime-registry.json"
    site_package = workdir / "valcea-core-v2-shadow-site-package.json"
    site_dir = workdir / "valcea-core-v2-shadow-site"

    return (
        CycleStage("apavil", (py, "valcea-clar/core_v2/apavil_shadow_lane.py", *live_flag, "--output", str(apavil)), apavil),
        CycleStage("ipj", (py, "valcea-clar/core_v2/public_safety_full_shadow_lane.py", "--source", "ipj", *live_flag, "--output", str(ipj)), ipj),
        CycleStage("isu", (py, "valcea-clar/core_v2/public_safety_full_shadow_lane.py", "--source", "isu", *live_flag, "--output", str(isu)), isu),
        CycleStage("municipal_reference", (py, "valcea-clar/core_v2/municipal_reference_shadow_lane.py", *live_flag, "--output", str(municipal_refs)), municipal_refs),
        CycleStage("municipal_document", (py, "valcea-clar/core_v2/municipal_document_shadow_lane.py", *live_flag, "--output", str(municipal_docs)), municipal_docs),
        CycleStage("municipal_materiality", (py, "valcea-clar/core_v2/municipal_materiality_shadow_lane.py", "--input", str(municipal_docs), "--output", str(municipal_materiality)), municipal_materiality),
        CycleStage("municipal_fact_kernel", (py, "valcea-clar/core_v2/municipal_fact_kernel_shadow_lane.py", "--documents", str(municipal_docs), "--materiality", str(municipal_materiality), "--output", str(municipal_kernels)), municipal_kernels),
        CycleStage("municipal_writer", (py, "valcea-clar/core_v2/municipal_writer_shadow_lane.py", "--fact-kernels", str(municipal_kernels), "--output", str(municipal_articles)), municipal_articles),
        CycleStage("cj_road", (py, "valcea-clar/core_v2/cj_road_shadow_lane.py", *live_flag, "--output", str(cj)), cj),
        CycleStage("eta", (py, "valcea-clar/core_v2/eta_shadow_lane.py", *live_flag, "--limit", "20", "--output", str(eta)), eta),
        CycleStage("isj", (py, "valcea-clar/core_v2/isj_shadow_lane.py", *live_flag, "--output", str(isj)), isj),
        CycleStage("isj_detail", (py, "valcea-clar/core_v2/isj_detail_shadow_lane.py", "--input", str(isj), *live_flag, "--output", str(isj_detail)), isj_detail),
        CycleStage("isj_materiality", (py, "valcea-clar/core_v2/isj_materiality_shadow_lane.py", "--input", str(isj_detail), "--output", str(isj_materiality)), isj_materiality),
        CycleStage("isj_embedded_notice", (py, "valcea-clar/core_v2/isj_embedded_notice_shadow_lane.py", "--details", str(isj_detail), "--materiality", str(isj_materiality), *live_flag, "--output", str(isj_embedded)), isj_embedded),
        CycleStage("isj_embedded_target", (py, "valcea-clar/core_v2/isj_embedded_target_shadow_lane.py", "--embedded", str(isj_embedded), *live_flag, "--output", str(isj_targets)), isj_targets),
        CycleStage("isj_embedded_content", (py, "valcea-clar/core_v2/isj_embedded_content_shadow_lane.py", "--targets", str(isj_targets), *live_flag, "--output", str(isj_content)), isj_content),
        CycleStage("isj_field_evidence", (py, "valcea-clar/core_v2/isj_field_evidence_shadow_lane.py", "--content", str(isj_content), "--output", str(isj_fields)), isj_fields),
        CycleStage("isj_context_documents", (py, "valcea-clar/core_v2/isj_context_documents_shadow_lane.py", "--targets", str(isj_targets), "--fields", str(isj_fields), "--year", "2026", *live_flag, "--output", str(isj_context)), isj_context),
        CycleStage("isj_calendar_field_evidence", (py, "valcea-clar/core_v2/isj_calendar_field_evidence_shadow_lane.py", "--context", str(isj_context), "--year", "2026", "--output", str(isj_calendar_fields)), isj_calendar_fields),
        CycleStage("isj_calendar_scope_binding", (py, "valcea-clar/core_v2/isj_calendar_scope_binding_shadow_lane.py", "--context", str(isj_context), "--calendar-fields", str(isj_calendar_fields), "--year", "2026", "--output", str(isj_calendar_scope)), isj_calendar_scope),
        CycleStage("isj_calendar_scope_validation", (py, "valcea-clar/core_v2/validate_isj_calendar_scope_truth.py", "--context", str(isj_context), "--calendar-fields", str(isj_calendar_fields), "--scope", str(isj_calendar_scope), "--year", "2026", "--prove-tamper", "--output", str(isj_calendar_scope_validation)), isj_calendar_scope_validation),
        CycleStage("isj_registration_deadline_promotion", (py, "valcea-clar/core_v2/isj_registration_deadline_promotion_shadow_lane.py", "--scope", str(isj_calendar_scope), "--scope-validation", str(isj_calendar_scope_validation), "--year", "2026", "--output", str(isj_deadline_promotion)), isj_deadline_promotion),
        CycleStage("isj_registration_deadline_promotion_validation", (py, "valcea-clar/core_v2/validate_isj_registration_deadline_promotion.py", "--scope", str(isj_calendar_scope), "--scope-validation", str(isj_calendar_scope_validation), "--promotion", str(isj_deadline_promotion), "--year", "2026", "--prove-tamper", "--output", str(isj_deadline_promotion_validation)), isj_deadline_promotion_validation),
        CycleStage("isj_field_materiality", (py, "valcea-clar/core_v2/isj_field_materiality_shadow_lane.py", "--fields", str(isj_fields), "--calendar-fields", str(isj_calendar_fields), "--deadline-promotion", str(isj_deadline_promotion), "--deadline-promotion-validation", str(isj_deadline_promotion_validation), "--year", "2026", "--output", str(isj_field_materiality)), isj_field_materiality),
        CycleStage("isj_fact_kernel_deadline_promotion", (py, "valcea-clar/core_v2/isj_fact_kernel_deadline_promotion_shadow_lane.py", "--materiality", str(isj_field_materiality), "--materiality-promotion", str(isj_deadline_promotion), "--materiality-promotion-validation", str(isj_deadline_promotion_validation), "--year", "2026", "--output", str(isj_fact_kernel_deadline_promotion)), isj_fact_kernel_deadline_promotion),
        CycleStage("isj_fact_kernel_deadline_promotion_validation", (py, "valcea-clar/core_v2/validate_isj_fact_kernel_deadline_promotion.py", "--materiality", str(isj_field_materiality), "--materiality-promotion", str(isj_deadline_promotion), "--materiality-promotion-validation", str(isj_deadline_promotion_validation), "--fact-promotion", str(isj_fact_kernel_deadline_promotion), "--year", "2026", "--prove-tamper", "--output", str(isj_fact_kernel_deadline_promotion_validation)), isj_fact_kernel_deadline_promotion_validation),
        CycleStage("isj_fact_kernel", (py, "valcea-clar/core_v2/isj_fact_kernel_shadow_lane.py", "--materiality", str(isj_field_materiality), "--fields", str(isj_fields), "--calendar-fields", str(isj_calendar_fields), "--output", str(isj_fact_kernel)), isj_fact_kernel),
        CycleStage("isj_fact_kernel_integrity", (py, "valcea-clar/core_v2/isj_fact_kernel_integrity.py", "--fact-kernel", str(isj_fact_kernel), "--output", str(isj_fact_integrity)), isj_fact_integrity),
        CycleStage("isj_writer_deadline_projection", (py, "valcea-clar/core_v2/isj_writer_deadline_projection_shadow_lane.py", "--fact-kernel", str(isj_fact_kernel), "--fact-kernel-integrity", str(isj_fact_integrity), "--year", "2026", "--output", str(isj_writer_deadline_projection)), isj_writer_deadline_projection),
        CycleStage("isj_writer_deadline_projection_validation", (py, "valcea-clar/core_v2/validate_isj_writer_deadline_projection.py", "--fact-kernel", str(isj_fact_kernel), "--fact-kernel-integrity", str(isj_fact_integrity), "--projection", str(isj_writer_deadline_projection), "--year", "2026", "--prove-tamper", "--output", str(isj_writer_deadline_projection_validation)), isj_writer_deadline_projection_validation),
        CycleStage("isj_writer_deadline_consumption", (py, "valcea-clar/core_v2/isj_writer_deadline_consumption_shadow_lane.py", "--fact-kernel", str(isj_fact_kernel), "--fact-kernel-integrity", str(isj_fact_integrity), "--projection", str(isj_writer_deadline_projection), "--projection-validation", str(isj_writer_deadline_projection_validation), "--year", "2026", "--output", str(isj_writer_deadline_consumption)), isj_writer_deadline_consumption),
        CycleStage("isj_writer_deadline_consumption_validation", (py, "valcea-clar/core_v2/validate_isj_writer_deadline_consumption.py", "--fact-kernel", str(isj_fact_kernel), "--fact-kernel-integrity", str(isj_fact_integrity), "--projection", str(isj_writer_deadline_projection), "--projection-validation", str(isj_writer_deadline_projection_validation), "--consumption", str(isj_writer_deadline_consumption), "--year", "2026", "--prove-tamper", "--output", str(isj_writer_deadline_consumption_validation)), isj_writer_deadline_consumption_validation),
        CycleStage("isj_writer", (py, "valcea-clar/core_v2/isj_writer_shadow_lane.py", "--fact-kernel", str(isj_fact_kernel), "--fact-kernel-integrity", str(isj_fact_integrity), "--output", str(isj_article)), isj_article),
        CycleStage("isj_article_deadline_claim_gate", (
            py, "valcea-clar/core_v2/isj_article_deadline_claim_gate.py",
            "--fact-kernel", str(isj_fact_kernel),
            "--fact-kernel-integrity", str(isj_fact_integrity),
            "--writer-consumption", str(isj_writer_deadline_consumption),
            "--writer-consumption-validation", str(isj_writer_deadline_consumption_validation),
            "--article", str(isj_article),
            "--output", str(isj_article_deadline_claim),
        ), isj_article_deadline_claim),
        CycleStage("isj_article_deadline_claim_validation", (
            py, "valcea-clar/core_v2/validate_isj_article_deadline_claim_gate.py",
            "--fact-kernel", str(isj_fact_kernel),
            "--fact-kernel-integrity", str(isj_fact_integrity),
            "--writer-consumption", str(isj_writer_deadline_consumption),
            "--writer-consumption-validation", str(isj_writer_deadline_consumption_validation),
            "--article", str(isj_article),
            "--gate", str(isj_article_deadline_claim),
            "--prove-tamper",
            "--output", str(isj_article_deadline_claim_validation),
        ), isj_article_deadline_claim_validation),
        CycleStage("isj_article_integrity", (py, "valcea-clar/core_v2/isj_article_integrity.py", "--fact-kernel", str(isj_fact_kernel), "--fact-kernel-integrity", str(isj_fact_integrity), "--article", str(isj_article), "--output", str(isj_article_integrity)), isj_article_integrity),
        CycleStage("isj_promoted_claim_contract", (
            py, "valcea-clar/core_v2/isj_promoted_claim_contract_shadow_lane.py",
            "--deadline-promotion-validation", str(isj_deadline_promotion_validation),
            "--fact-promotion-validation", str(isj_fact_kernel_deadline_promotion_validation),
            "--fact-kernel", str(isj_fact_kernel),
            "--fact-integrity", str(isj_fact_integrity),
            "--writer-projection-validation", str(isj_writer_deadline_projection_validation),
            "--writer-consumption-validation", str(isj_writer_deadline_consumption_validation),
            "--article-claim-gate", str(isj_article_deadline_claim),
            "--article-claim-validation", str(isj_article_deadline_claim_validation),
            "--article-integrity", str(isj_article_integrity),
            "--output", str(isj_promoted_claim_contract),
        ), isj_promoted_claim_contract),
        CycleStage("isj_promoted_claim_contract_validation", (
            py, "valcea-clar/core_v2/validate_isj_promoted_claim_contract_runtime.py",
            "--deadline-promotion-validation", str(isj_deadline_promotion_validation),
            "--fact-promotion-validation", str(isj_fact_kernel_deadline_promotion_validation),
            "--fact-kernel", str(isj_fact_kernel),
            "--fact-integrity", str(isj_fact_integrity),
            "--writer-projection-validation", str(isj_writer_deadline_projection_validation),
            "--writer-consumption-validation", str(isj_writer_deadline_consumption_validation),
            "--article-claim-gate", str(isj_article_deadline_claim),
            "--article-claim-validation", str(isj_article_deadline_claim_validation),
            "--article-integrity", str(isj_article_integrity),
            "--contract", str(isj_promoted_claim_contract),
            "--prove-tamper",
            "--output", str(isj_promoted_claim_contract_validation),
        ), isj_promoted_claim_contract_validation),
        CycleStage("site_verified_article_ledger", (py, "valcea-clar/core_v2/site_verified_article_ledger.py", "--ipj", str(ipj), "--isu", str(isu), "--municipal", str(municipal_articles), "--isj-article", str(isj_article), "--isj-integrity", str(isj_article_integrity), "--output", str(site_article_ledger)), site_article_ledger),
        CycleStage("photo_truth", (py, "valcea-clar/core_v2/photo_truth_gate.py", "--input", f"ipj={ipj}", "--input", f"isu={isu}", "--input", f"municipal={municipal_articles}", "--input", f"isj={isj_article_integrity}", "--visual-registry", "valcea-clar/core_v2/visual_registry.json", "--external-probe", "--output", str(photo)), photo),
        CycleStage("site_visual_runtime_registry", (py, "valcea-clar/core_v2/site_visual_runtime_path_hydrator.py", "--registry", "valcea-clar/core_v2/visual_registry.json", "--photo-truth", str(photo), "--output", str(site_visual_registry)), site_visual_registry),
        CycleStage("shadow_site_package", (py, "valcea-clar/core_v2/shadow_site_package.py", "--articles", str(site_article_ledger), "--photo-truth", str(photo), "--visual-registry", str(site_visual_registry), "--repo-root", ".", "--output-dir", str(site_dir), "--output", str(site_package)), site_package),
    )


def _stage_summary(stage: CycleStage, completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    output_doc: dict[str, Any] | None = None
    if stage.output is not None and stage.output.is_file():
        try:
            parsed = json.loads(stage.output.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                keys = (
                    "status", "mode", "state", "signal_count", "detail_count", "detail_row_count", "candidate_count", "selected_material_signal_count",
                    "detail_evidence_shadow_count", "material_detail_candidate_shadow_count", "embedded_notice_evidence_shadow_count",
                    "embedded_target_identity_shadow_count", "selected_document_count", "document_content_captured_shadow_count",
                    "document_text_extracted_shadow_count", "verified_document_count", "verified_calendar_document_count", "field_evidence_count", "material_candidate_shadow_count", "materiality_candidate_count", "fact_kernel_count", "verified_claim_count", "fact_kernel_integrity_verified", "writer_gate_status",
                    "article_count", "source_article_counts", "shadow_writer_executed", "article_truth_state", "verified_article_count", "article_integrity_verified", "photo_gate_status",
                    "contest_context_verified", "selected_context_document_count", "selected_roles", "same_document_year_scope_verified",
                    "registration_window_normalized", "registration_deadline_normalized", "registration_deadline", "promotion_evidence_id", "materiality_promotion_allowed", "registration_deadline_materiality_consumed",
                    "fact_kernel_promotion_evidence_id", "fact_kernel_promotion_allowed", "material_fact_use", "writer_projection_evidence_id", "writer_deadline_projection_allowed", "verified_projection_candidate_count",
                    "writer_consumption_evidence_id", "shadow_writer_consumption_allowed", "verified_consumption_candidate_count",
                    "article_deadline_claim_evidence_id", "shadow_article_claim_integrity_passed", "verified_claim_candidate_count",
                    "canonical_article_mutation_allowed", "article_projection_allowed", "article_contains_registration_deadline", "rendered_promoted_claim_count",
                    "promoted_claim_contract_id", "lineage_complete", "tamper_regressions_passed",
                    "verified_written_shadow_count", "visual_candidate_verified_shadow_count", "hydrated_story_count", "preserved_story_count", "package_image_bound_shadow_count", "blocked_count",
                    "no_story_count", "fabricated_claim_count", "publication_authority", "acceptance_ready",
                )
                output_doc = {key: parsed.get(key) for key in keys if key in parsed}
        except Exception:
            output_doc = {"parse_error": True}
    return {
        "name": stage.name,
        "returncode": completed.returncode,
        "output_exists": bool(stage.output is None or stage.output.is_file()),
        "output": str(stage.output) if stage.output is not None else None,
        "summary": output_doc,
        "stdout_tail": "\n".join((completed.stdout or "").splitlines()[-3:]),
        "stderr_tail": "\n".join((completed.stderr or "").splitlines()[-3:]),
    }


def _persisted_runtime_snapshots(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    names = {
        "isj_calendar_scope_binding",
        "isj_calendar_scope_validation",
        "isj_registration_deadline_promotion",
        "isj_registration_deadline_promotion_validation",
        "isj_fact_kernel_deadline_promotion",
        "isj_fact_kernel_deadline_promotion_validation",
        "isj_writer_deadline_projection",
        "isj_writer_deadline_projection_validation",
        "isj_writer_deadline_consumption",
        "isj_writer_deadline_consumption_validation",
        "isj_article_deadline_claim_gate",
        "isj_article_deadline_claim_validation",
        "isj_promoted_claim_contract",
        "isj_promoted_claim_contract_validation",
        "site_verified_article_ledger",
        "site_visual_runtime_registry",
    }
    snapshots: dict[str, Any] = {}
    for stage in plan:
        if stage.name not in names or stage.output is None or not stage.output.is_file():
            continue
        try:
            doc = json.loads(stage.output.read_text(encoding="utf-8"))
        except Exception:
            snapshots[stage.name] = {"parse_error": True, "path": str(stage.output)}
            continue
        snapshots[stage.name] = doc
    return snapshots


def run_bounded_shadow_cycle(*, repo_root: Path, workdir: Path, live: bool) -> dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    plan = bounded_cycle_plan(workdir, live=live)
    stages: list[dict[str, Any]] = []
    failed_stage = None
    for stage in plan:
        completed = subprocess.run(list(stage.argv), cwd=repo_root, capture_output=True, text=True, timeout=180, check=False)
        summary = _stage_summary(stage, completed)
        stages.append(summary)
        if completed.returncode != 0 or not summary["output_exists"]:
            failed_stage = stage.name
            break
    return {
        "schema_version": "2.1",
        "mode": "CORE_V2_BOUNDED_SHADOW_CYCLE",
        "shadow_mode": True,
        "publication_authority": "NONE",
        "production_write_authority": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "acceptance_ready": False,
        "live_read_only": live,
        "status": "PASS_SHADOW" if failed_stage is None else "BLOCKED",
        "failed_stage": failed_stage,
        "stage_count_planned": len(plan),
        "stage_count_completed": len(stages),
        "stages": stages,
        "runtime_artifact_snapshots": _persisted_runtime_snapshots(plan),
        "truth_rule": (
            "This orchestrator may read official sources and compose shadow evidence only. It has no publication, deploy, merge, "
            "workflow-dispatch or Meta-write authority. A successful shadow cycle is not production readiness."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="CIVORA Local News Core v2 shadow orchestrator")
    parser.add_argument("--input")
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-bounded-cycle", action="store_true")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--workdir", default="/tmp")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.run_bounded_cycle:
        report = run_bounded_shadow_cycle(repo_root=Path(args.repo_root), workdir=Path(args.workdir), live=args.live)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": report["status"],
            "stage_count_completed": report["stage_count_completed"],
            "failed_stage": report["failed_stage"],
            "publication_authority": "NONE",
            "acceptance_ready": False,
        }, ensure_ascii=False, sort_keys=True))
        return 0 if report["status"] == "PASS_SHADOW" else 1
    if not args.input:
        raise SystemExit("--input is required unless --run-bounded-cycle is used")
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    tx = run_shadow(payload)
    out = tx.as_dict()
    out["shadow_mode"] = True
    out["publication_authority"] = "NONE"
    output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"story_id": tx.story_id, "state": tx.state.value, "shadow_mode": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
