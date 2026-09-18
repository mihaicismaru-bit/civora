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
        tx.no_story(str(payload.get("no_story_reason") or "no material signal")); return tx
    tx.verify(_kernel(payload.get("fact_kernel") or {})); tx.write(str(payload.get("article") or ""))
    if payload.get("visual"):
        tx.attach_visual(_visual(payload["visual"]))
    if payload.get("site_receipt"):
        tx.publish_site(_receipt("site", payload["site_receipt"]))
    for channel in ("facebook", "instagram"):
        row = (payload.get("social_receipts") or {}).get(channel)
        if not row: continue
        if str(row.get("status") or "").upper() == "FAILED":
            tx.fail_distribution(channel, str(row.get("reason") or "external delivery failed")); continue
        tx.deliver_social(_receipt(channel, row))
    audit_doc = payload.get("audit")
    if audit_doc:
        tx.audit_story(AuditResult(
            status=str(audit_doc.get("status") or ""), external_truth_ok=bool(audit_doc.get("external_truth_ok")),
            duplicates=int(audit_doc.get("duplicates") or 0), fabricated_claims=int(audit_doc.get("fabricated_claims") or 0),
            manual_intervention=int(audit_doc.get("manual_intervention") or 0),
            unresolved_material_signals=int(audit_doc.get("unresolved_material_signals") or 0),
            evidence=tuple(str(v) for v in audit_doc.get("evidence") or []),
        ))
    return tx


def bounded_cycle_plan(workdir: Path, *, live: bool) -> tuple[CycleStage, ...]:
    """Return the single ordered Core v2 read-only shadow execution plan."""
    py = sys.executable
    live_flag = ("--live",) if live else ()
    apavil = workdir / "valcea-core-v2-apavil-shadow.json"; ipj = workdir / "valcea-core-v2-ipj-shadow.json"; isu = workdir / "valcea-core-v2-isu-shadow.json"
    municipal_refs = workdir / "valcea-core-v2-municipal-shadow.json"; municipal_docs = workdir / "valcea-core-v2-municipal-documents.json"
    municipal_materiality = workdir / "valcea-core-v2-municipal-materiality.json"; municipal_kernels = workdir / "valcea-core-v2-municipal-fact-kernels.json"
    municipal_articles = workdir / "valcea-core-v2-municipal-articles.json"; cj = workdir / "valcea-core-v2-cj-road-shadow.json"; eta = workdir / "valcea-core-v2-eta-shadow.json"
    isj = workdir / "valcea-core-v2-isj-shadow.json"; isj_detail = workdir / "valcea-core-v2-isj-detail-shadow.json"; isj_materiality = workdir / "valcea-core-v2-isj-materiality-shadow.json"
    isj_embedded = workdir / "valcea-core-v2-isj-embedded-notice-shadow.json"; isj_targets = workdir / "valcea-core-v2-isj-embedded-target-shadow.json"
    isj_content = workdir / "valcea-core-v2-isj-embedded-content-shadow.json"; isj_fields = workdir / "valcea-core-v2-isj-field-evidence-shadow.json"
    isj_context = workdir / "valcea-core-v2-isj-context-documents-shadow.json"
    photo = workdir / "valcea-core-v2-photo-truth.json"; site_package = workdir / "valcea-core-v2-shadow-site-package.json"; site_dir = workdir / "valcea-core-v2-shadow-site"
    return (
        CycleStage("apavil", (py,"valcea-clar/core_v2/apavil_shadow_lane.py",*live_flag,"--output",str(apavil)), apavil),
        CycleStage("ipj", (py,"valcea-clar/core_v2/public_safety_full_shadow_lane.py","--source","ipj",*live_flag,"--output",str(ipj)), ipj),
        CycleStage("isu", (py,"valcea-clar/core_v2/public_safety_full_shadow_lane.py","--source","isu",*live_flag,"--output",str(isu)), isu),
        CycleStage("municipal_reference", (py,"valcea-clar/core_v2/municipal_reference_shadow_lane.py",*live_flag,"--output",str(municipal_refs)), municipal_refs),
        CycleStage("municipal_document", (py,"valcea-clar/core_v2/municipal_document_shadow_lane.py",*live_flag,"--output",str(municipal_docs)), municipal_docs),
        CycleStage("municipal_materiality", (py,"valcea-clar/core_v2/municipal_materiality_shadow_lane.py","--input",str(municipal_docs),"--output",str(municipal_materiality)), municipal_materiality),
        CycleStage("municipal_fact_kernel", (py,"valcea-clar/core_v2/municipal_fact_kernel_shadow_lane.py","--documents",str(municipal_docs),"--materiality",str(municipal_materiality),"--output",str(municipal_kernels)), municipal_kernels),
        CycleStage("municipal_writer", (py,"valcea-clar/core_v2/municipal_writer_shadow_lane.py","--fact-kernels",str(municipal_kernels),"--output",str(municipal_articles)), municipal_articles),
        CycleStage("cj_road", (py,"valcea-clar/core_v2/cj_road_shadow_lane.py",*live_flag,"--output",str(cj)), cj),
        CycleStage("eta", (py,"valcea-clar/core_v2/eta_shadow_lane.py",*live_flag,"--limit","20","--output",str(eta)), eta),
        CycleStage("isj", (py,"valcea-clar/core_v2/isj_shadow_lane.py",*live_flag,"--output",str(isj)), isj),
        CycleStage("isj_detail", (py,"valcea-clar/core_v2/isj_detail_shadow_lane.py","--input",str(isj),*live_flag,"--output",str(isj_detail)), isj_detail),
        CycleStage("isj_materiality", (py,"valcea-clar/core_v2/isj_materiality_shadow_lane.py","--input",str(isj_detail),"--output",str(isj_materiality)), isj_materiality),
        CycleStage("isj_embedded_notice", (py,"valcea-clar/core_v2/isj_embedded_notice_shadow_lane.py","--details",str(isj_detail),"--materiality",str(isj_materiality),*live_flag,"--output",str(isj_embedded)), isj_embedded),
        CycleStage("isj_embedded_target", (py,"valcea-clar/core_v2/isj_embedded_target_shadow_lane.py","--embedded",str(isj_embedded),*live_flag,"--output",str(isj_targets)), isj_targets),
        CycleStage("isj_embedded_content", (py,"valcea-clar/core_v2/isj_embedded_content_shadow_lane.py","--targets",str(isj_targets),*live_flag,"--output",str(isj_content)), isj_content),
        CycleStage("isj_field_evidence", (py,"valcea-clar/core_v2/isj_field_evidence_shadow_lane.py","--content",str(isj_content),"--output",str(isj_fields)), isj_fields),
        CycleStage("isj_context_documents", (py,"valcea-clar/core_v2/isj_context_documents_shadow_lane.py","--targets",str(isj_targets),"--fields",str(isj_fields),"--year","2026",*live_flag,"--output",str(isj_context)), isj_context),
        CycleStage("photo_truth", (py,"valcea-clar/core_v2/photo_truth_gate.py","--input",f"ipj={ipj}","--input",f"isu={isu}","--input",f"municipal={municipal_articles}","--visual-registry","valcea-clar/core_v2/visual_registry.json","--external-probe","--output",str(photo)), photo),
        CycleStage("shadow_site_package", (py,"valcea-clar/core_v2/shadow_site_package.py","--articles",str(municipal_articles),"--photo-truth",str(photo),"--visual-registry","valcea-clar/core_v2/visual_registry.json","--repo-root",".","--output-dir",str(site_dir),"--output",str(site_package)), site_package),
    )


def _stage_summary(stage: CycleStage, completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    output_doc: dict[str, Any] | None = None
    if stage.output is not None and stage.output.is_file():
        try:
            parsed = json.loads(stage.output.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                keys = (
                    "status","mode","signal_count","detail_count","detail_row_count","candidate_count","selected_material_signal_count",
                    "detail_evidence_shadow_count","material_detail_candidate_shadow_count","embedded_notice_evidence_shadow_count",
                    "embedded_target_identity_shadow_count","selected_document_count","document_content_captured_shadow_count",
                    "document_text_extracted_shadow_count","verified_document_count","field_evidence_count","material_candidate_shadow_count",
                    "contest_context_verified","selected_context_document_count","selected_roles",
                    "verified_written_shadow_count","visual_candidate_verified_shadow_count","package_image_bound_shadow_count","blocked_count",
                    "no_story_count","fabricated_claim_count","publication_authority","acceptance_ready"
                )
                output_doc = {key: parsed.get(key) for key in keys if key in parsed}
        except Exception:
            output_doc = {"parse_error": True}
    return {"name":stage.name,"returncode":completed.returncode,"output_exists":bool(stage.output is None or stage.output.is_file()),"output":str(stage.output) if stage.output is not None else None,"summary":output_doc,"stdout_tail":"\n".join((completed.stdout or "").splitlines()[-3:]),"stderr_tail":"\n".join((completed.stderr or "").splitlines()[-3:])}


def run_bounded_shadow_cycle(*, repo_root: Path, workdir: Path, live: bool) -> dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True); plan = bounded_cycle_plan(workdir, live=live); stages=[]; failed_stage=None
    for stage in plan:
        completed = subprocess.run(list(stage.argv), cwd=repo_root, capture_output=True, text=True, timeout=180, check=False)
        summary = _stage_summary(stage, completed); stages.append(summary)
        if completed.returncode != 0 or not summary["output_exists"]:
            failed_stage = stage.name; break
    return {"schema_version":"1.2","mode":"CORE_V2_BOUNDED_SHADOW_CYCLE","shadow_mode":True,"publication_authority":"NONE","production_write_authority":False,"site_publish_allowed":False,"social_publish_allowed":False,"acceptance_ready":False,"live_read_only":live,"status":"PASS_SHADOW" if failed_stage is None else "BLOCKED","failed_stage":failed_stage,"stage_count_planned":len(plan),"stage_count_completed":len(stages),"stages":stages,"truth_rule":"This orchestrator may read official sources and compose shadow evidence only. It has no publication, deploy, merge, workflow-dispatch or Meta-write authority. A successful shadow cycle is not production readiness."}


def main() -> int:
    parser=argparse.ArgumentParser(description="CIVORA Local News Core v2 shadow orchestrator"); parser.add_argument("--input"); parser.add_argument("--output",required=True); parser.add_argument("--run-bounded-cycle",action="store_true"); parser.add_argument("--repo-root",default="."); parser.add_argument("--workdir",default="/tmp"); parser.add_argument("--live",action="store_true"); args=parser.parse_args()
    output=Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    if args.run_bounded_cycle:
        report=run_bounded_shadow_cycle(repo_root=Path(args.repo_root),workdir=Path(args.workdir),live=args.live); output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"status":report["status"],"stage_count_completed":report["stage_count_completed"],"failed_stage":report["failed_stage"],"publication_authority":"NONE","acceptance_ready":False},ensure_ascii=False,sort_keys=True)); return 0 if report["status"]=="PASS_SHADOW" else 1
    if not args.input: raise SystemExit("--input is required unless --run-bounded-cycle is used")
    payload=json.loads(Path(args.input).read_text(encoding="utf-8")); tx=run_shadow(payload); out=tx.as_dict(); out["shadow_mode"]=True; out["publication_authority"]="NONE"; output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"story_id":tx.story_id,"state":tx.state.value,"shadow_mode":True},ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
