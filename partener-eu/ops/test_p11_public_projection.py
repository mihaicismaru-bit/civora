#!/usr/bin/env python3
import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("projection", ROOT / "p11" / "build_public_projection.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def main() -> None:
    bundle = json.loads((ROOT / "p11" / "opportunity_bundle.json").read_text(encoding="utf-8"))
    projection = mod.build(bundle)
    assert projection["summary"]["opportunityCount"] == 26
    assert projection["summary"]["openVerifiedCount"] >= 1
    step = next(row for row in projection["opportunities"] if row["id"] == "PEO-STEP-LLL-ADULTI-2026")
    assert step["status"] == "OPEN"
    assert {"status", "deadline"} <= set(step["verifiedFactClasses"])
    assert step["verifiedEvidenceCount"] == len(step["verificationEvidence"])
    assert all(item["sourceUrl"].startswith("https://") for item in step["verificationEvidence"])
    assert all(item["sourceHost"] for item in step["verificationEvidence"])
    assert all(isinstance(item["ageSecondsAtProjection"], int) for item in step["verificationEvidence"])
    assert step["verificationSourceCoverage"]["verifiedEvidenceLinkCount"] == step["verifiedEvidenceCount"]
    assert {
        fact_class
        for item in step["verificationEvidence"]
        for fact_class in item["supportedFactClasses"]
    } == set(step["verifiedFactClasses"])
    assert step["publicationDecision"] == {
        "decision": "ALLOW_VERIFIED_FACTS",
        "reasonCodes": ["PUBLICATION_STATE_PUBLISHABLE", "VERIFIED_FACTS_ONLY"],
        "blockedFactClasses": [],
        "activeResolutionTaskCount": 0,
    }
    regional = next(row for row in projection["opportunities"] if row["id"] == "pr-centru-digital-2")
    assert regional["status"] == "DISCOVERED"
    assert regional["materialFacts"] == {}
    assert regional["publicationDecision"]["decision"] == "BLOCK_MATERIAL_FACTS"
    assert "ACTIVE_RESOLUTION_TASK" in regional["publicationDecision"]["reasonCodes"]
    north_east = next(
        row for row in projection["opportunities"]
        if row["id"] == "pr-ne-energy-residential-towns-2026"
    )
    assert north_east["status"] == "EXPECTED"
    assert north_east["publicationState"] == "PUBLISHABLE"
    assert set(north_east["verifiedFactClasses"]) == {
        "status", "deadline", "budget", "grant", "eligibility", "scoring", "beneficiaries"
    }
    clusters = next(
        row for row in projection["opportunities"]
        if row["id"] == "pr-centru-clusters-122"
    )
    assert clusters["status"] == "OPEN"
    assert clusters["publicationState"] == "PUBLISHABLE"
    assert clusters["materialFacts"]["budget"]["total_eur"] == 11664904
    assert clusters["materialFacts"]["grant"]["maximum_eur"] == 3500000
    pids = next(
        row for row in projection["opportunities"]
        if row["id"] == "pids-supported-decision"
    )
    assert pids["status"] == "OPEN"
    assert pids["publicationState"] == "PUBLISHABLE"
    assert pids["materialFacts"]["budget"]["total_eur"] == 11804343
    assert pids["materialFacts"]["grant"]["form"] == "grant nerambursabil"
    assert pids["materialFacts"]["scoring"]["minimum_total_points"] == 70
    assert set(pids["verifiedFactClasses"]) == {
        "status", "deadline", "budget", "grant", "eligibility", "scoring", "beneficiaries"
    }
    step_edu = next(
        row for row in projection["opportunities"]
        if row["id"] == "peo-step-edu-adulti"
    )
    assert step_edu["status"] == "DISCOVERED"
    assert step_edu["publicationState"] == "QUARANTINED"
    assert step_edu["materialFacts"] == {}
    assert step_edu["verifiedFactClasses"] == []
    assert step_edu["publicationDecision"]["decision"] == "BLOCK_MATERIAL_FACTS"
    assert "PUBLICATION_STATE_QUARANTINED" in step_edu["publicationDecision"]["reasonCodes"]
    assert projection["schemaVersion"] == 5
    assert projection["policy"]["decisionReasonsVisible"] is True
    assert projection["policy"]["verificationProvenanceVisible"] is True
    assert projection["policy"]["freshnessReference"] == "PROJECTION_AS_OF"
    assert projection["policy"]["freshnessTelemetryAuthorizesPublication"] is False
    assert projection["policy"]["sourceCoverageTelemetryAuthorizesPublication"] is False
    assert projection["summary"]["verificationFreshness"]["verifiedEvidenceLinkCount"] == 17
    assert projection["summary"]["verificationSourceCoverage"]["verifiedEvidenceLinkCount"] == 17
    adapter_path = json.dumps(str(ROOT / "web" / "p11-public-adapter.js"))
    adapter_result = subprocess.run(
        ["node", "-e", f"""
global.window={{
  PARTENER_DATA:{{calls:[{{id:'test-call',title:'Test',status:'DISCOVERED',sourceFacts:[{{url:'https://legacy.test'}}]}}]}},
  PARTENER_P11:{{asOf:'2026-08-14T00:00:00Z',summary:{{}},opportunities:[{{
    id:'test-call',title:'Test',status:'OPEN',publicationState:'PUBLISHABLE',
    verifiedFactClasses:['status'],materialFacts:{{status:'OPEN'}},
    verificationSourceCoverage:{{verifiedEvidenceLinkCount:1,uniqueSourceHostCount:1,sourceHosts:['official.test'],sourceTierCounts:{{T1:1,T1B:0}}}},
    verificationEvidence:[{{evidenceId:'EV-1',sourceTier:'T1',sourceUrl:'https://official.test/call',sourceHost:'official.test',observedAt:'2026-08-14T00:00:00Z',ageSecondsAtProjection:0,supportedFactClasses:['status']}}]
  }}]}}
}};
require({adapter_path});
const call=window.PARTENER_DATA.calls[0];
if(call.sourceFacts.length!==1||call.sourceFacts[0].url!=='https://official.test/call'||call.sourceFacts[0].sourceHost!=='official.test'||call.sourceFacts[0].tier!=='T1'||call.sourceFacts[0].ageSecondsAtProjection!==0||!call.sourceFacts[0].label.includes('official.test')||!call.sourceFacts[0].label.includes('2026-08-14'))process.exit(2);
"""],
        text=True,
        capture_output=True,
    )
    assert adapter_result.returncode == 0, adapter_result.stderr
    print("PASS P11 public projection")


if __name__ == "__main__":
    main()
