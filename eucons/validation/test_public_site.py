#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

import sys
sys.path.insert(0, str(WEB))
from build_public_site import (  # noqa: E402
    active_evidence_map,
    build,
    publishable_cases,
    publishable_people,
    publishable_service_ids,
    rel_asset,
    valid_claim,
)

EVIDENCE = json.loads((ROOT / "evidence" / "evidence_registry.json").read_text(encoding="utf-8"))
PEOPLE = json.loads((ROOT / "people" / "people_registry.json").read_text(encoding="utf-8"))
CASES = json.loads((ROOT / "cases" / "case_study_registry.json").read_text(encoding="utf-8"))
SITE = json.loads((WEB / "public_site.json").read_text(encoding="utf-8"))


def main():
    evidence_map = active_evidence_map(EVIDENCE)
    canonical_ids = publishable_service_ids(EVIDENCE)
    if len(canonical_ids) != 8:
        raise SystemExit(f"canonical E08 expected 8 evidence-backed services, got {len(canonical_ids)}")

    sample = next(claim for claim in EVIDENCE["claims"] if claim.get("claim_class") == "SERVICE_OFFERING")

    hold = copy.deepcopy(sample)
    hold["publication_state"] = "HOLD"
    if valid_claim(hold, evidence_map):
        raise SystemExit("HOLD service claim unexpectedly passed E08 claim gate")

    no_evidence = copy.deepcopy(sample)
    no_evidence["evidence_ids"] = []
    if valid_claim(no_evidence, evidence_map):
        raise SystemExit("service claim without evidence unexpectedly passed E08 claim gate")

    inactive_map = copy.deepcopy(evidence_map)
    inactive_map.pop(sample["evidence_ids"][0], None)
    if valid_claim(sample, inactive_map):
        raise SystemExit("service claim with unavailable evidence unexpectedly passed E08 claim gate")

    wrong_class_map = copy.deepcopy(evidence_map)
    evidence_id = sample["evidence_ids"][0]
    wrong_class_map[evidence_id]["allowed_claim_classes"] = ["PROJECT_RESULT"]
    if valid_claim(sample, wrong_class_map):
        raise SystemExit("service claim backed by wrong evidence class unexpectedly passed E08 claim gate")

    synthetic_people = {"people": [
        {"id":"hold-person","publication_state":"HOLD","display_name":"Never Public"},
        {"id":"public-person","publication_state":"PUBLISHABLE","display_name":"Allowed Person"},
    ]}
    if [item["id"] for item in publishable_people(synthetic_people)] != ["public-person"]:
        raise SystemExit("people projection does not fail closed")

    synthetic_cases = {"cases": [
        {"id":"hold-case","publication_state":"HOLD","title":"Never Public Case"},
        {"id":"public-case","publication_state":"PUBLISHABLE","title":"Allowed Case"},
    ]}
    if [item["id"] for item in publishable_cases(synthetic_cases)] != ["public-case"]:
        raise SystemExit("case projection does not fail closed")

    if rel_asset("/", "assets/eucons.css") != "assets/eucons.css":
        raise SystemExit("root asset path drift")
    if rel_asset("/servicii/", "assets/eucons.css") != "../assets/eucons.css":
        raise SystemExit("one-level asset path drift")
    if rel_asset("/servicii/test/", "assets/eucons.css") != "../../assets/eucons.css":
        raise SystemExit("two-level asset path drift")

    with tempfile.TemporaryDirectory(prefix="eucons-e08-regression-") as tmp:
        output = Path(tmp)
        manifest = build(output)
        if manifest["page_count"] != 26 or manifest["core_page_count"] != 18 or manifest["service_page_count"] != 8:
            raise SystemExit(f"canonical E08 route count drift: {manifest}")
        if manifest["publishable_people_count"] != 0 or manifest["publishable_case_count"] != 0:
            raise SystemExit("canonical empty people/case registries unexpectedly produced public proof")
        if manifest["funding_projection_active"] is not False:
            raise SystemExit("E09 funding projection was activated by E08")
        home = (output / "index.html").read_text(encoding="utf-8")
        if SITE["empty_states"]["team_index"]["body"] in home or SITE["empty_states"]["projects_index"]["body"] in home:
            raise SystemExit("homepage filled missing proof with empty-state placeholders")
        for path in ("evaluare-proiect/index.html", "solicita-oferta/index.html"):
            text = (output / path).read_text(encoding="utf-8")
            if 'data-eucons-dry-run="true"' not in text or 'type="submit" disabled aria-disabled="true"' not in text:
                raise SystemExit(f"E08 lead surface {path} is not fail-closed dry-run")

    print("EUCONS E08 public-site regressions valid: service evidence, HOLD people/cases, asset paths, route coverage, proof omission, funding isolation and dry-run lead surfaces fail closed")


if __name__ == "__main__":
    main()
