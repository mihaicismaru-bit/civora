#!/usr/bin/env python3
"""Make lifecycle stage progression monotonic and fail-closed."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "ingest" / "build_call_lifecycle.py"
text = PATH.read_text(encoding="utf-8")
needle = '''        if result_links and STAGE_RANK[stage] < STAGE_RANK["RESULTS"] and any(
            str(e.get("kind") or "").upper() == "RESULTS_PUBLISHED" for e in dossier.get("timeline") or []
        ):
            stage = "RESULTS"
        source_urls = [s.get("url") for s in dossier.get("sources") or [] if s.get("url")]
'''
replacement = '''        if result_links and STAGE_RANK[stage] < STAGE_RANK["RESULTS"] and any(
            str(e.get("kind") or "").upper() == "RESULTS_PUBLISHED" for e in dossier.get("timeline") or []
        ):
            stage = "RESULTS"
        prior_call = next((x for x in previous.get("calls") or [] if x.get("dossierId") == dossier.get("id")), None)
        prior_stage = str(prior_call.get("stage") or "") if prior_call else ""
        if prior_stage in STAGE_RANK and STAGE_RANK[prior_stage] > STAGE_RANK[stage]:
            stage_evidence.append({
                "type": "MONOTONIC_HISTORY_PRESERVED",
                "previousStage": prior_stage,
                "candidateStage": stage,
                "reason": "Lipsa unei evidențe în snapshotul curent nu retrage o etapă administrativă confirmată anterior.",
            })
            stage = prior_stage
        source_urls = [s.get("url") for s in dossier.get("sources") or [] if s.get("url")]
'''
if replacement in text:
    print("Call lifecycle monotonicity already applied")
elif needle in text:
    PATH.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
    print("Call lifecycle monotonicity applied")
else:
    raise SystemExit("Expected lifecycle stage block not found; refusing blind patch")
