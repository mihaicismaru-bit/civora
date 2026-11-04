#!/usr/bin/env python3
"""Reject AFIR projections that would overwrite a newer/broader public LKG."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

AFIR_SOURCE_TYPES = {"AFIR_INGESTED_PROVISIONAL"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def instant(value: Any) -> dt.datetime:
    text = str(value or "").replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def raw_public_value(value: Any) -> bool:
    if isinstance(value, (dict, list, tuple)):
        return True
    text = str(value or "").lstrip()
    return text.startswith(("{", "[")) or "{'" in text or "':" in text


def validate(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    baseline_rows = baseline.get("dossiers") or []
    candidate_rows = candidate.get("dossiers") or []
    baseline_protected = {
        str(row.get("id"))
        for row in baseline_rows
        if row.get("id") and row.get("sourceType") not in AFIR_SOURCE_TYPES
    }
    candidate_ids = {str(row.get("id")) for row in candidate_rows if row.get("id")}
    missing = sorted(baseline_protected - candidate_ids)
    if missing:
        raise AssertionError(
            f"candidate drops {len(missing)} non-AFIR LKG dossiers: {missing[:12]}"
        )

    baseline_time = instant(baseline.get("generatedAt"))
    candidate_time = instant(candidate.get("generatedAt"))
    if candidate_time < baseline_time:
        raise AssertionError(
            f"candidate is older than LKG: {candidate_time.isoformat()} < {baseline_time.isoformat()}"
        )

    policy = candidate.get("policy") or {}
    assert policy.get("romanianPublicLanguage") is True, "Romanian public-language gate missing"
    assert policy.get("rawStructuredObjectsVisible") is False, "raw-object policy is not fail-closed"

    raw_locations: list[str] = []
    for dossier in candidate_rows:
        dossier_id = str(dossier.get("id") or "UNKNOWN")
        for fact in dossier.get("quickFacts") or []:
            if raw_public_value(fact.get("value")):
                raw_locations.append(f"{dossier_id}:quickFacts:{fact.get('label')}")
        for section in dossier.get("sections") or []:
            for index, item in enumerate(section.get("items") or []):
                if raw_public_value(item):
                    raw_locations.append(f"{dossier_id}:section:{section.get('title')}:{index}")
    if raw_locations:
        raise AssertionError(f"raw structured public values: {raw_locations[:12]}")

    return {
        "status": "PASS",
        "baselineGeneratedAt": baseline.get("generatedAt"),
        "candidateGeneratedAt": candidate.get("generatedAt"),
        "protectedDossiers": len(baseline_protected),
        "candidateDossiers": len(candidate_rows),
        "rawStructuredValues": 0,
    }


# The AFIR publisher may replace only the six exact official AFIR dossiers and
# their dated news events. No AFIR refresh may delete/change other programmes'
# LKG dossier or news bodies, even if upstream discovery returned fewer rows.
AFIR_OVERLAY_IDS = {
    "afir-dr12-2026", "afir-dr14-2026", "afir-dr18-2026",
    "afir-dr31-2026-2027",
    "afir-fm-public-autoconsum-2026", "afir-fm-public-storage-2026",
}
AFIR_OVERLAY_NEWS = {
    "news-afir-dr14-dr18-extended-2026-10-30",
    "news-afir-dr14-dr18-open-2026-09-01",
    "news-afir-dr31-consultation-2026-08-28",
}


def validate_afir_source_scope(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    protected = 0
    for key, allowlist in (("dossiers", AFIR_OVERLAY_IDS), ("news", AFIR_OVERLAY_NEWS)):
        original = {str(x.get("id")): x for x in baseline.get(key) or [] if x.get("id")}
        latest = {str(x.get("id")): x for x in candidate.get(key) or [] if x.get("id")}
        unexpected = sorted(
            i for i in original.keys() | latest.keys()
            if i not in allowlist and original.get(i) != latest.get(i)
        )
        if unexpected:
            raise AssertionError(f"AFIR-only projection mutated {key} outside source scope: {unexpected[:12]}")
        protected += len(set(original) - allowlist)
    return {"afirOnlySourceScope": "PASS", "unmodifiedOtherDossiersAndNews": protected}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--afir-source-scoped", action="store_true")
    args = parser.parse_args()
    baseline, candidate = load(args.baseline), load(args.candidate)
    result = validate(baseline, candidate)
    if args.afir_source_scoped:
        result.update(validate_afir_source_scope(baseline, candidate))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
