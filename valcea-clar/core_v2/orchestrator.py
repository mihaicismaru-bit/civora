from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from contracts import (
    AuditResult,
    ContractViolation,
    FactKernel,
    PublicationReceipt,
    StoryTransaction,
    Visual,
)


def _kernel(doc: dict[str, Any]) -> FactKernel:
    return FactKernel(
        what=str(doc.get("what") or ""),
        who=str(doc.get("who") or ""),
        where=str(doc.get("where") or ""),
        when=str(doc.get("when") or ""),
        why_it_matters=str(doc.get("why_it_matters") or ""),
        source=str(doc.get("source") or ""),
        source_url=str(doc.get("source_url") or ""),
        claims=tuple(str(v) for v in doc.get("claims") or []),
        evidence_ids=tuple(str(v) for v in doc.get("evidence_ids") or []),
    )


def _visual(doc: dict[str, Any]) -> Visual:
    return Visual(
        kind=str(doc.get("kind") or ""),
        synthetic=bool(doc.get("synthetic")),
        source_url=str(doc.get("source_url") or ""),
        rights_basis=str(doc.get("rights_basis") or ""),
        semantic_relevance=str(doc.get("semantic_relevance") or ""),
        editor_approved=bool(doc.get("editor_approved")),
        contextual_archive=bool(doc.get("contextual_archive")),
        context_disclosure=doc.get("context_disclosure"),
        credit=doc.get("credit"),
    )


def _receipt(channel: str, doc: dict[str, Any]) -> PublicationReceipt:
    return PublicationReceipt(
        channel=channel,
        status=str(doc.get("status") or ""),
        canonical_url=doc.get("canonical_url"),
        remote_id=doc.get("remote_id"),
        receipt_id=doc.get("receipt_id"),
        readback_ok=bool(doc.get("readback_ok")),
        observed_at=str(doc.get("observed_at") or "") or PublicationReceipt(channel=channel, status="PENDING").observed_at,
    )


def run_shadow(payload: dict[str, Any]) -> StoryTransaction:
    """Evaluate one evidence transaction without performing any external write."""
    story_id = str(payload.get("story_id") or "").strip()
    if not story_id:
        raise ContractViolation("story_id is required")

    tx = StoryTransaction(story_id=story_id, signal_id=payload.get("signal_id"))
    if payload.get("material_signal") is False:
        tx.no_story(str(payload.get("no_story_reason") or "no material signal"))
        return tx

    tx.verify(_kernel(payload.get("fact_kernel") or {}))
    tx.write(str(payload.get("article") or ""))

    visual_doc = payload.get("visual")
    if visual_doc:
        tx.attach_visual(_visual(visual_doc))

    site_doc = payload.get("site_receipt")
    if site_doc:
        tx.publish_site(_receipt("site", site_doc))

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
        result = AuditResult(
            status=str(audit_doc.get("status") or ""),
            external_truth_ok=bool(audit_doc.get("external_truth_ok")),
            duplicates=int(audit_doc.get("duplicates") or 0),
            fabricated_claims=int(audit_doc.get("fabricated_claims") or 0),
            manual_intervention=int(audit_doc.get("manual_intervention") or 0),
            unresolved_material_signals=int(audit_doc.get("unresolved_material_signals") or 0),
            evidence=tuple(str(v) for v in audit_doc.get("evidence") or []),
        )
        tx.audit_story(result)

    return tx


def main() -> int:
    parser = argparse.ArgumentParser(description="CIVORA Local News Core v2 shadow orchestrator")
    parser.add_argument("--input", required=True, help="JSON evidence fixture")
    parser.add_argument("--output", required=True, help="Output transaction JSON")
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    tx = run_shadow(payload)
    out = tx.as_dict()
    out["shadow_mode"] = True
    out["publication_authority"] = "NONE"
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"story_id": tx.story_id, "state": tx.state.value, "shadow_mode": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
