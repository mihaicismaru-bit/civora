from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Sequence


class PartenerCallError(ValueError):
    """Raised when PARTENER call intelligence lacks provenance or required domain fields."""


def _sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_call_intelligence(record: Mapping[str, Any]) -> Dict[str, Any]:
    required = ("call_code", "title", "specific_objective", "target_group", "indicators")
    failures: List[str] = []
    for field in required:
        value = record.get(field)
        if value in (None, "", [], {}):
            failures.append(f"missing_{field}")
    provenance = list(record.get("source_snapshot_ids") or [])
    if not provenance:
        failures.append("missing_source_snapshot_ids")
    if failures:
        raise PartenerCallError(",".join(failures))

    result = {
        "schema_version": "nf.call_intelligence.v0.1",
        "provider": "PARTENER.EU",
        "call_code": str(record["call_code"]),
        "title": str(record["title"]),
        "program": record.get("program"),
        "priority": record.get("priority"),
        "specific_objective": record["specific_objective"],
        "target_group": record["target_group"],
        "eligible_activities": list(record.get("eligible_activities") or []),
        "indicators": [dict(item) if isinstance(item, Mapping) else {"id": str(item)} for item in record.get("indicators", [])],
        "evaluation_criteria": [dict(item) if isinstance(item, Mapping) else {"text": str(item)} for item in record.get("evaluation_criteria", [])],
        "evidence_constructs": sorted({str(item) for item in (record.get("evidence_constructs") or [])}),
        "source_snapshot_ids": sorted({str(item) for item in provenance}),
        "guide_version": record.get("guide_version"),
        "guide_date": record.get("guide_date"),
        "correction_ids": sorted({str(item) for item in (record.get("correction_ids") or [])}),
    }
    result["call_intelligence_sha256"] = _sha256(result)
    return result


def validate_call_snapshot_lineage(call_intelligence: Mapping[str, Any], allowed_source_snapshot_ids: Sequence[str]) -> Dict[str, Any]:
    allowed = {str(item) for item in allowed_source_snapshot_ids}
    used = {str(item) for item in (call_intelligence.get("source_snapshot_ids") or [])}
    unknown = sorted(used - allowed)
    return {
        "valid": bool(used) and not unknown,
        "used_source_snapshot_ids": sorted(used),
        "unknown_source_snapshot_ids": unknown,
    }
