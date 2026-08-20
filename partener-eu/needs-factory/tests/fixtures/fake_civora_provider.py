#!/usr/bin/env python3
from __future__ import annotations

import json
import sys


payload = json.load(sys.stdin)
task = payload["task"]
if task.get("task_type") == "DISCOVERY_THEN_PRIMARY_IF_GAP":
    print(json.dumps({"schema_version": "nf.civora_discovery_response.v0.1", "receipts": []}))
    raise SystemExit(0)

measure_type = (task.get("allowed_measure_types") or ["count"])[0]
if measure_type == "rate":
    measure = {"name":"metric","measure_type":"rate","source_measure_type":"rate","value":0.2,"numerator":2,"denominator_universe":"synthetic source population","unit":"proportion","calculated":True}
elif measure_type == "share":
    measure = {"name":"metric","measure_type":"share","source_measure_type":"share","value":0.5,"numerator":5,"denominator_universe":"synthetic source population","unit":"proportion","calculated":True}
elif measure_type == "score":
    measure = {"name":"metric","measure_type":"score","value":4,"unit":"score","calculated":False}
elif measure_type == "qualitative":
    measure = {"name":"finding","measure_type":"qualitative","value":"synthetic documented finding","unit":None,"calculated":False}
else:
    measure = {"name":"metric","measure_type":"count","value":10,"unit":"persons","calculated":False}

scope = task["preferred_scopes"][0]
receipt = {
    "candidate_id": f"SYNTH-{task['requirement_id']}",
    "requirement_id": task["requirement_id"],
    "source": "Synthetic CIVORA provider fixture",
    "source_family": task["preferred_source_families"][0],
    "official": True,
    "tier": "A1",
    "final_url": f"https://example.test/{task['requirement_id'].lower()}",
    "source_document_id": f"SYNTH-DOC-{task['requirement_id']}",
    "health": "PASS",
    "quarantined": False,
    "raw_sha256": "r" * 64,
    "semantic_sha256": "s" * 64,
    "scope": scope,
    "territory": "Synthetic Technical School" if scope == "school" else "Synthetic County",
    "population": "synthetic source population",
    "constructs": [task["construct"]],
    "direct_measurement": bool(task.get("direct_local_required")),
    "publication_date": "2023-12-01",
    "period": "2023",
    "last_success": "2023-12-01T12:00:00Z",
    "material_fact_state": "STABLE_LAST_KNOWN_GOOD",
    "facts": [
        {
            "construct": task["construct"],
            "territory": "Synthetic Technical School" if scope == "school" else "Synthetic County",
            "scope": scope,
            "period": "2023",
            "measures": [measure]
        }
    ]
}
print(json.dumps({"schema_version": "nf.civora_discovery_response.v0.1", "receipts": [receipt]}, ensure_ascii=False))
