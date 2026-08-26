#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

EXPECTED_SCHEMA_VERSION = "nf.primary_payload.v0.1"
ENVELOPE_KEYS = {"response_id", "received_at_utc", "schema_version", "form_version", "answers", "synthetic"}
FORBIDDEN_KEYS = {
    "name", "first_name", "last_name", "cnp", "national_id", "email", "phone", "telephone",
    "exact_address", "address", "exact_employer", "employer_name", "organisation_name",
    "organization_name", "cui", "ip", "ip_address", "user_agent", "cookie_id", "login_id",
    "device_fingerprint", "advertising_id",
}
FREE_TEXT_FIELDS = {"job_family", "Q07_topic", "Q08_other", "Q11_other", "Q12", "sector", "E04_detail", "E09"}
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?40[\s.-]?)?(?:0?7\d{2}|0?2\d{2}|0?3\d{2})[\s.-]?\d{3}[\s.-]?\d{3}(?!\d)")
CNP_RE = re.compile(r"(?<!\d)[1-8]\d{12}(?!\d)")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_records(raw: bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8-sig").strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("JSON top level must be an array")
        records = parsed
    else:
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not all(isinstance(row, dict) for row in records):
        raise ValueError("every record must be a JSON object")
    return records


def parse_utc(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        dt.datetime.fromisoformat(value[:-1] + "+00:00")
        return True
    except ValueError:
        return False


def find_forbidden_keys(value: Any, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            child_path = f"{path}.{key}"
            if normalized in FORBIDDEN_KEYS:
                hits.append(child_path)
            hits.extend(find_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(find_forbidden_keys(child, f"{path}[{index}]"))
    return hits


def pii_hits(field: str, value: Any) -> list[str]:
    if field not in FREE_TEXT_FIELDS or not isinstance(value, str):
        return []
    hits = []
    if EMAIL_RE.search(value):
        hits.append("email_address")
    if PHONE_RE.search(value):
        hits.append("romanian_phone_like")
    if CNP_RE.search(value):
        hits.append("cnp_like")
    return hits


def validate_scalar(field: str, value: Any, spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "enum" in spec and value not in spec["enum"]:
        errors.append(f"{field}: value is outside enum")
        return errors
    if "const" in spec and value != spec["const"]:
        errors.append(f"{field}: value must equal {spec['const']!r}")
        return errors
    expected = spec.get("type")
    if expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"{field}: expected integer")
        else:
            if "minimum" in spec and value < spec["minimum"]:
                errors.append(f"{field}: below minimum")
            if "maximum" in spec and value > spec["maximum"]:
                errors.append(f"{field}: above maximum")
    elif expected == "string":
        if not isinstance(value, str):
            errors.append(f"{field}: expected string")
        else:
            if "minLength" in spec and len(value.strip()) < spec["minLength"]:
                errors.append(f"{field}: below minLength")
            if "maxLength" in spec and len(value) > spec["maxLength"]:
                errors.append(f"{field}: above maxLength")
    elif expected == "array":
        if not isinstance(value, list):
            errors.append(f"{field}: expected array")
        else:
            if spec.get("uniqueItems") and len({json.dumps(x, ensure_ascii=False, sort_keys=True) for x in value}) != len(value):
                errors.append(f"{field}: duplicate array items")
            if "maxItems" in spec and len(value) > spec["maxItems"]:
                errors.append(f"{field}: above maxItems")
            item_spec = spec.get("items") or {}
            for index, item in enumerate(value):
                errors.extend(validate_scalar(f"{field}[{index}]", item, item_spec))
    return errors


def validate_answers(answers: Any, payload_schema: dict[str, Any]) -> list[str]:
    if not isinstance(answers, dict):
        return ["answers: expected object"]
    errors: list[str] = []
    allowed = set((payload_schema.get("properties") or {}).keys())
    unexpected = sorted(set(answers) - allowed)
    if unexpected:
        errors.append("answers: unexpected fields: " + ", ".join(unexpected))
    for field in payload_schema.get("required") or []:
        if field not in answers:
            errors.append(f"answers.{field}: required field missing")
    for field, value in answers.items():
        spec = (payload_schema.get("properties") or {}).get(field)
        if spec:
            errors.extend(validate_scalar(f"answers.{field}", value, spec))
        for hit in pii_hits(field, value):
            errors.append(f"answers.{field}: PII-like token detected ({hit})")
    return errors


def stratum_counts(records: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, int]]:
    output: dict[str, dict[str, int]] = {}
    for field in fields:
        counts = Counter(str(row["answers"].get(field, "<MISSING>")) for row in records)
        output[field] = dict(sorted(counts.items()))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed ingest validator for AI4WORK STEP primary responses")
    parser.add_argument("input", type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--stream", required=True, choices=["adults", "employers"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--mode", choices=["prod", "test-twin"], default="prod")
    args = parser.parse_args()

    raw = args.input.read_bytes()
    raw_hash = sha256_bytes(raw)
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    schema_key = "adult_payload" if args.stream == "adults" else "employer_payload"
    payload_schema = schema[schema_key]
    records = load_records(raw)

    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, record in enumerate(records):
        errors: list[str] = []
        unexpected_envelope = sorted(set(record) - ENVELOPE_KEYS)
        if unexpected_envelope:
            errors.append("envelope: unexpected fields: " + ", ".join(unexpected_envelope))
        for required in ("response_id", "received_at_utc", "schema_version", "form_version", "answers"):
            if required not in record:
                errors.append(f"envelope.{required}: required field missing")
        response_id = record.get("response_id")
        if not isinstance(response_id, str) or not response_id.strip():
            errors.append("envelope.response_id: non-empty opaque string required")
        elif response_id in seen_ids:
            errors.append("envelope.response_id: duplicate")
        else:
            seen_ids.add(response_id)
        if not parse_utc(record.get("received_at_utc")):
            errors.append("envelope.received_at_utc: RFC3339 UTC timestamp ending Z required")
        if record.get("schema_version") != EXPECTED_SCHEMA_VERSION:
            errors.append(f"envelope.schema_version: expected {EXPECTED_SCHEMA_VERSION}")
        if not isinstance(record.get("form_version"), str) or not record.get("form_version", "").strip():
            errors.append("envelope.form_version: non-empty string required")
        forbidden = find_forbidden_keys(record)
        if forbidden:
            errors.append("forbidden identifier fields: " + ", ".join(sorted(forbidden)))
        synthetic = record.get("synthetic")
        if args.mode == "prod" and synthetic is not None:
            errors.append("envelope.synthetic: marker is forbidden in PROD; synthetic records cannot enter PROD")
        if args.mode == "test-twin" and synthetic is not True:
            errors.append("envelope.synthetic: TEST TWIN requires synthetic=true")
        errors.extend(validate_answers(record.get("answers"), payload_schema))
        if errors:
            rejected.append({"index": index, "response_id": response_id if isinstance(response_id, str) else None, "errors": errors})
        else:
            valid.append(record)

    region_counts = Counter(str(row["answers"].get("region")) for row in valid)
    expected_regions = set((schema.get("common") or {}).get("regions") or [])
    missing_regions = sorted(expected_regions - set(region_counts))
    strata_fields = ["region", "status", "age_band"] if args.stream == "adults" else ["region", "sector", "size"]

    status = "PASS"
    gate = "THREE_REGION_COVERAGE_PASS"
    if rejected or not valid:
        status = "FAIL"
        gate = "INGEST_FAIL_CLOSED"
    elif missing_regions:
        status = "PASS_WITH_COVERAGE_GAP"
        gate = "THREE_REGION_COVERAGE_OPEN"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in valid:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    normalized_hash = sha256_bytes(args.output.read_bytes())
    report = {
        "schema_version": "nf.primary_ingest_report.v0.1",
        "run_id": "AI4WORK-STEP/NF-RUN-001",
        "mode": args.mode,
        "evidence_classification": "PROD_REAL_DATA_CANDIDATE" if args.mode == "prod" else "TEST_TWIN_NON_EVIDENCE",
        "stream": args.stream,
        "raw_file": args.input.name,
        "raw_sha256": raw_hash,
        "normalized_sha256": normalized_hash,
        "input_count": len(records),
        "valid_count": len(valid),
        "rejected_count": len(rejected),
        "region_counts": dict(sorted(region_counts.items())),
        "stratum_counts": stratum_counts(valid, strata_fields),
        "missing_regions": missing_regions,
        "errors": rejected,
        "status": status,
        "coverage_gate": gate,
        "promotion_allowed": args.mode == "prod" and status == "PASS",
        "promotion_note": "Even PASS requires documented recruitment frame/coverage metadata and raw-to-aggregate reconciliation before NF06 evidence promotion.",
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status != "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
