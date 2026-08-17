#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
products = json.loads((ROOT / "partener-eu/ingest/state/decision_products.json").read_text(encoding="utf-8"))
queue = json.loads((ROOT / "partener-eu/ingest/state/dossier_enrichment_queue.json").read_text(encoding="utf-8"))
canonical = json.loads((ROOT / "partener-eu/ingest/state/mipe_canonical_calls.json").read_text(encoding="utf-8"))
lifecycle_source = (ROOT / "partener-eu/ingest/build_call_lifecycle.py").read_text(encoding="utf-8")

assert products.get("policy", {}).get("autonomousDossierConstruction") is True
assert products.get("policy", {}).get("dossierDepthIsNotApprovalProbability") is True
assert queue.get("policy", {}).get("officialEvidenceOnly") is True
assert queue.get("policy", {}).get("failClosed") is True
assert canonical.get("policy", {}).get("deepDossierFactExtraction") is True
assert canonical.get("policy", {}).get("documentTextFeedsDossiers") is True

for token in ('"EVALUATION_UPDATE": "EVALUATION"', '"CONTRACTING_UPDATE": "CONTRACTING"', '"DEADLINE_EXTENDED": "OPEN"'):
    assert token in lifecycle_source, f"missing lifecycle alias {token}"

for dossier in products.get("dossiers") or []:
    q = dossier.get("quality") or {}
    assert isinstance(q.get("depthCompleteness"), int)
    assert 0 <= q["depthCompleteness"] <= 100
    assert q.get("dossierLevel") in {"DOSAR COMPLET", "DOSAR AVANSAT", "DOSAR ÎN CONSTRUCȚIE", "DOSAR DE IDENTIFICARE"}
    assert isinstance(q.get("missingDepthClasses"), list)
    assert dossier.get("dossierConstruction", {}).get("autonomous") is True

for row in queue.get("queue") or []:
    assert row.get("dossierId")
    assert row.get("missing")
    assert row.get("officialSources") is not None

summary = products.get("summary") or {}
assert summary.get("needsEnrichmentCount") == queue.get("summary", {}).get("queued")
print(json.dumps({
    "dossiers": summary.get("dossierCount"),
    "complete": summary.get("completeDossierCount"),
    "advanced": summary.get("advancedDossierCount"),
    "queued": summary.get("needsEnrichmentCount"),
    "mipeDeepStructured": canonical.get("summary", {}).get("deepStructured"),
}, ensure_ascii=False, indent=2))
