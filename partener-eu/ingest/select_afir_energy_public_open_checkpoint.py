#!/usr/bin/env python3
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
rows=[]
for p in (ROOT/"partener-eu/ops/checkpoints").glob("AFIR_ENERGY_OPEN_EVIDENCE_*.json"):
    try:
        j=json.loads(p.read_text(encoding="utf-8")); rows.append((j["observedAt"],p,j))
    except Exception: pass
if not rows: raise SystemExit("no AFIR energy evidence checkpoint")
_,p,j=max(rows,key=lambda x:x[0])
out=ROOT/"partener-eu/ingest/state/afir_energy_public_open_evidence.json"
out.write_text(json.dumps(j,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"selected":p.name,"observedAt":j.get("observedAt")},ensure_ascii=False))
