#!/usr/bin/env python3
"""Regression gate: both MIPE replays must retain AFIR and STEP authoritative dossiers."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
PIPELINES = {
    "partener-eu-mipe-engine-v3.yml": (
        "      - name: Canonicalize evidence and construct deep dossiers",
        "      - name: Validate canonical pipeline, dossier depth and lifecycle",
    ),
    "partener-eu-mipe-final-cleanup-qa.yml": (
        "      - name: Replay current MIPE corpus through PARTENER engine pipeline",
        "      - name: Assert cleanup remains immutable after replay",
    ),
}
REQUIRED = (
    "refine_afir_public_dossiers.py",
    "apply_afir_current_authoritative_dossiers.py",
    "apply_step_lll_authoritative_dossier.py",
    "score_dossier_depth.py",
    "sync_decision_products_projection.py",
    "build_mipe_enrichment_seeds.py",
    "build_call_lifecycle.py",
)

for filename, (begin, end) in PIPELINES.items():
    workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")
    assert workflow.count(begin) == 1 and workflow.count(end) == 1, filename
    block = workflow.split(begin, 1)[1].split(end, 1)[0]
    commands = re.findall(
        r"(?m)^\s*python partener-eu/ingest/([\w-]+\.py)\s*$", block
    )
    positions = []
    for script in REQUIRED:
        assert commands.count(script) == 1, (filename, script, commands)
        positions.append(commands.index(script))
    assert positions == sorted(positions), (filename, commands)
    for test in ("test_afir_current_dossiers.py", "test_step_lll_dossier.py",
                 "test_sync_decision_products_projection.py", "test_mipe_engine_overlay_retention.py"):
        assert f"python partener-eu/ops/{test}" in workflow, (filename, test)
print("PASS: MIPE replay overlay retention and downstream projection gates")
