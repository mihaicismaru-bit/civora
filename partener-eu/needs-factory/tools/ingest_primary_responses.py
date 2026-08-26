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

RESEARCH_ID = "AI4WORK-STEP-NF-RUN-001"
TARGET_SCHEMA_VERSION = "nf.primary_payload.v0.1"
RAW_KEYS = {
    "schema_version", "research_id", "form_id", "form_version", "response_id",
    "received_at", "profile", "answers", "synthetic",
}
FORBIDDEN_KEYS = {
    "name", "first_name", "last_name", "surname", "cnp", "national_id", "email", "phone",
    "telephone", "exact_address", "address", "exact_employer", "employer_name",
    "organisation_name", "organization_name", "cui", "ip", "ip_address", "user_agent",
    "cookie_id", "login_id", "account_id", "device_fingerprint", "advertising_id", "marketing_id",
}
FREE_TEXT_FIELDS = {
    "occupational_family", "sector_aggregated", "Q07_topic", "Q12", "E04_detail", "E09",
    "job_family", "sector", "Q08_other", "Q11_other",
}
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?40[\s.-]?)?(?:0?7\d{2}|0?2\d{2}|0?3\d{2})[\s.-]?\d{3}[\s.-]?\d{3}(?!\d)")
CNP_RE = re.compile(r"(?<!\d)[1-8]\d{12}(?!\d)")
URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+")


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


def normalize_utc(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    parsed = parsed.astimezone(dt.timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


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


def text_pii_hits(field: str, value: Any) -> list[str]:
    if field not in FREE_TEXT_FIELDS or not isinstance(value, str):
        return []
    hits = []
    if EMAIL_RE.search(value):
        hits.append("email_address")
    if PHONE_RE.search(value):
        hits.append("romanian_phone_like")
    if CNP_RE.search(value):
        hits.append("cnp_like")
    if URL_RE.search(value):
        hits.append("url_like")
    return hits


def scan_free_text(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            for hit in text_pii_hits(str(key), child):
                errors.append(f"{path}.{key}: PII-like token detected ({hit})")
            errors.extend(scan_free_text(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(scan_free_text(child, f"{path}[{index}]"))
    return errors


def transform_record(record: dict[str, Any], stream: str) -> dict[str, Any]:
    profile = record["profile"]
    answers = record["answers"]
    if stream == "adults":
        q10 = answers["Q10"]
        flat = {
            "region": profile["region"],
            "status": profile["status"],
            "age_band": profile["age_band"],
            "job_family": profile["occupational_family"],
            "Q01": answers["Q01"],
            "Q02": answers["Q02"],
            "Q03": answers["Q03"],
            "Q04": answers["Q04"],
            "Q05": answers["Q05"],
            "Q06": answers["Q06"],
            "Q07": "da" if answers["Q07"] else "nu",
            "Q08": answers["Q08"],
            "Q09": answers["Q09"],
            "Q10_digital": q10["utilizare_digitala_functionala"],
            "Q10_AI": q10["utilizarea_instrumentelor_AI"],
            "Q10_verification": q10["verificarea_rezultatelor_AI"],
            "Q10_privacy": q10["protectia_datelor_confidentialitate"],
            "Q10_workflow": q10["integrarea_AI_in_flux_de_lucru"],
            "Q11": answers["Q11"],
            "Q12": answers["Q12"],
            "privacy_ack": True,
        }
        if answers.get("Q07_topic"):
            flat["Q07_topic"] = answers["Q07_topic"]
    else:
        e03 = answers["E03"]
        flat = {
            "region": profile["region"],
            "sector": profile["sector_aggregated"],
            "size": profile["size_band"],
            "respondent_type": profile["respondent_role"],
            "E01": answers["E01"],
            "E02": answers["E02"],
            "E03_prompt": e03["formularea_cerintelor"],
            "E03_verification": e03["verificarea_calitatii"],
            "E03_privacy": e03["protectia_datelor"],
            "E03_limits": e03["limitele_si_riscurile_AI"],
            "E03_integration": e03["integrarea_in_procese"],
            "E03_workflow": e03["definirea_fluxului_asistat_AI"],
            "E03_general_digital": e03["competente_digitale_generale"],
            "E04": answers["E04"],
            "E05": answers["E05"],
            "E06": answers["E06"],
            "E07": answers["E07"],
            "E08": answers["E08"],
            "E09": answers["E09"],
            "E10": answers["E10"],
            "privacy_ack": True,
        }
        if answers.get("E04_detail"):
            flat["E04_detail"] = answers["E04_detail"]
    normalized = {
        "response_id": record["response_id"],
        "received_at_utc": normalize_utc(record["received_at"]),
        "schema_version": TARGET_SCHEMA_VERSION,
        "form_version": str(record["form_version"]),
        "answers": flat,
    }
    if record.get("synthetic") is True:
        normalized["synthetic"] = True
    return normalized


def validate_scalar(field: str, value: Any, spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "enum" in spec and value not in spec["enum"]:
        return [f"{field}: value is outside enum"]
    if "const" in spec and value != spec["const"]:
        return [f"{field}: value must equal {spec['const']!r}"]
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


def validate_normalized(record: dict[str, Any], payload_schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("received_at_utc") is None:
        errors.append("received_at: timezone-aware timestamp required")
    answers = record.get("answers")
    if not isinstance(answers, dict):
        return errors + ["answers: expected object"]
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
        for hit in text_pii_hits(field, value):
            errors.append(f"answers.{field}: PII-like token detected ({hit})")
    return errors


def stratum_counts(records: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, int]]:
    output: dict[str, dict[str, int]] = {}
    for field in fields:
        counts = Counter(str(row["answers"].get(field, "<MISSING>")) for row in records)
        output[field] = dict(sorted(counts.items()))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed NF06 ingest validator for EUCONS AI4WORK research exports")
    parser.add_argument("input", type=Path)
    parser.add_argument("--schema", required=True, type=Path, help="EUCONS_PRIMARY_DATA_SCHEMA.json")
    parser.add_argument("--stream", required=True, choices=["adults", "employers"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--mode", choices=["prod", "test-twin"], default="prod")
    args = parser.parse_args()

    raw = args.input.read_bytes()
    raw_hash = sha256_bytes(raw)
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    payload_schema = schema["adult_payload" if args.stream == "adults" else "employer_payload"]
    expected_form = "AI4WORK_ADULTS_V1" if args.stream == "adults" else "AI4WORK_EMPLOYERS_V1"
    records = load_records(raw)

    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, raw_record in enumerate(records):
        errors: list[str] = []
        unexpected = sorted(set(raw_record) - RAW_KEYS)
        if unexpected:
            errors.append("raw envelope: unexpected fields: " + ", ".join(unexpected))
        missing = sorted(RAW_KEYS - set(raw_record))
        if missing:
            errors.append("raw envelope: missing fields: " + ", ".join(missing))
        forbidden = find_forbidden_keys(raw_record)
        if forbidden:
            errors.append("forbidden identifier fields: " + ", ".join(sorted(forbidden)))
        errors.extend(scan_free_text(raw_record))
        if raw_record.get("schema_version") != 1:
            errors.append("raw schema_version must be 1")
        if raw_record.get("research_id") != RESEARCH_ID:
            errors.append(f"research_id must be {RESEARCH_ID}")
        if raw_record.get("form_id") != expected_form:
            errors.append(f"form_id must be {expected_form}")
        if raw_record.get("form_version") != 1:
            errors.append("form_version must be 1")
        response_id = raw_record.get("response_id")
        if not isinstance(response_id, str) or not response_id.strip():
            errors.append("response_id: non-empty opaque string required")
        elif response_id in seen_ids:
            errors.append("response_id: duplicate")
        else:
            seen_ids.add(response_id)
        if normalize_utc(raw_record.get("received_at")) is None:
            errors.append("received_at: timezone-aware ISO timestamp required")
        if args.mode == "prod" and raw_record.get("synthetic") is not False:
            errors.append("synthetic must be false in PROD")
        if args.mode == "test-twin" and raw_record.get("synthetic") is not True:
            errors.append("synthetic must be true in TEST TWIN")
        if not isinstance(raw_record.get("profile"), dict) or not isinstance(raw_record.get("answers"), dict):
            errors.append("profile and answers must be objects")
        if not errors:
            try:
                normalized = transform_record(raw_record, args.stream)
            except (KeyError, TypeError) as exc:
                errors.append(f"canonical transform failed: {exc}")
            else:
                errors.extend(validate_normalized(normalized, payload_schema))
        if errors:
            rejected.append({"index": index, "response_id": response_id if isinstance(response_id, str) else None, "errors": errors})
        else:
            valid.append(normalized)

    region_counts = Counter(str(row["answers"].get("region")) for row in valid)
    expected_regions = set((schema.get("common") or {}).get("regions") or [])
    missing_regions = sorted(expected_regions - set(region_counts))
    strata_fields = ["region", "status", "age_band"] if args.stream == "adults" else ["region", "sector", "size"]

    status = "PASS"
    coverage_gate = "THREE_REGION_COVERAGE_PASS"
    if rejected or not valid:
        status = "FAIL"
        coverage_gate = "INGEST_FAIL_CLOSED"
    elif missing_regions:
        status = "PASS_WITH_COVERAGE_GAP"
        coverage_gate = "THREE_REGION_COVERAGE_OPEN"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in valid:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    normalized_hash = sha256_bytes(args.output.read_bytes())
    report = {
        "schema_version": "nf.primary_ingest_report.v0.2",
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
        "coverage_gate": coverage_gate,
        "promotion_allowed": args.mode == "prod" and status == "PASS",
        "promotion_note": "PASS is only a technical ingest gate. NF06 promotion still requires documented recruitment frame/coverage, immutable raw export manifest, and raw-to-aggregate reconciliation.",
        "privacy_ack_derivation": "true is derived only from the EUCONS runtime acceptance invariant; the public submission is rejected unless voluntary participation acknowledgement is true."
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status != "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
