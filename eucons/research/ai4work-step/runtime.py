#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "form_contract.json"

REGIONS = {"Sud-Vest Oltenia", "Sud-Muntenia", "Centru"}
ADULT_STATUS = {"șomer înregistrat", "persoană ocupată potențial eligibilă", "alt statut / de verificat"}
AGE_BANDS = {"30-39", "40-49", "50-59", "60+"}
EMPLOYER_SIZE = {"1-9", "10-49", "50-249", "250+"}
EMPLOYER_ROLE = {"management", "HR", "operațional/tehnic", "altul"}
TOP_LEVEL = {"form_id", "notice_read_and_voluntary_participation", "profile", "answers"}
FORBIDDEN_KEYS = {"name", "surname", "cnp", "email", "phone", "address", "exact_address", "organisation_name", "organization_name", "employer_name", "cui", "ip", "user_agent", "cookie_id", "marketing_id", "account_id"}
PII_PATTERNS = {
    "email": re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    "phone": re.compile(r"(?<!\d)(?:\+?40|0)\s?7(?:[ .-]?\d){8}(?!\d)"),
    "cnp_like": re.compile(r"(?<!\d)[1-8]\d{12}(?!\d)"),
    "url": re.compile(r"(?i)\b(?:https?://|www\.)\S+"),
}

ADULT_REQUIRED = {"Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q08", "Q09", "Q10", "Q11", "Q12"}
ADULT_ALLOWED = ADULT_REQUIRED | {"Q07_topic"}
EMPLOYER_REQUIRED = {"E01", "E02", "E03", "E04", "E05", "E06", "E07", "E08", "E09", "E10"}
EMPLOYER_ALLOWED = EMPLOYER_REQUIRED | {"E04_detail"}
ADULT_RATINGS = {"Q01", "Q03", "Q04", "Q05", "Q06"}
ADULT_Q10_KEYS = {"utilizare_digitala_functionala", "utilizarea_instrumentelor_AI", "verificarea_rezultatelor_AI", "protectia_datelor_confidentialitate", "integrarea_AI_in_flux_de_lucru"}
EMPLOYER_E03_KEYS = {"formularea_cerintelor", "verificarea_calitatii", "protectia_datelor", "limitele_si_riscurile_AI", "integrarea_in_procese", "definirea_fluxului_asistat_AI", "competente_digitale_generale"}


class ResearchValidationError(ValueError):
    pass


def load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def clean_text(value: Any, limit: int) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        raise ResearchValidationError(f"text exceeds {limit} characters")
    return text


def safe_text(value: Any, limit: int) -> str:
    text = clean_text(value, limit)
    hits = [label for label, pattern in PII_PATTERNS.items() if pattern.search(text)]
    if hits:
        raise ResearchValidationError(f"free text contains identifier-like data: {sorted(hits)}")
    return text


def reject_forbidden_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise ResearchValidationError(f"forbidden field at {path}.{key}")
            reject_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            reject_forbidden_keys(child, f"{path}[{idx}]")


def rating(value: Any, low: int, high: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ResearchValidationError(f"{field} must be integer {low}..{high}")
    return value


def exact_rating_map(value: Any, keys: set[str], field: str) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ResearchValidationError(f"{field} must contain exactly {sorted(keys)}")
    return {key: rating(value[key], 1, 5, f"{field}.{key}") for key in sorted(keys)}


def bounded_list(value: Any, field: str, maximum: int | None = None) -> list[str]:
    if not isinstance(value, list):
        raise ResearchValidationError(f"{field} must be a list")
    if maximum is not None and len(value) > maximum:
        raise ResearchValidationError(f"{field} allows at most {maximum} selections")
    out: list[str] = []
    for raw in value:
        item = safe_text(raw, 160)
        if item and item not in out:
            out.append(item)
    return out


def validate_profile(profile: Any, form_id: str) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise ResearchValidationError("profile must be an object")
    if form_id == "AI4WORK_ADULTS_V1":
        required = {"region", "status", "age_band", "occupational_family"}
        if set(profile) != required:
            raise ResearchValidationError(f"adult profile fields must be exactly {sorted(required)}")
        if profile["region"] not in REGIONS or profile["status"] not in ADULT_STATUS or profile["age_band"] not in AGE_BANDS:
            raise ResearchValidationError("invalid adult profile category")
        return {
            "region": profile["region"],
            "status": profile["status"],
            "age_band": profile["age_band"],
            "occupational_family": safe_text(profile["occupational_family"], 80),
        }
    required = {"region", "sector_aggregated", "size_band", "respondent_role"}
    if set(profile) != required:
        raise ResearchValidationError(f"employer profile fields must be exactly {sorted(required)}")
    if profile["region"] not in REGIONS or profile["size_band"] not in EMPLOYER_SIZE or profile["respondent_role"] not in EMPLOYER_ROLE:
        raise ResearchValidationError("invalid employer profile category")
    return {
        "region": profile["region"],
        "sector_aggregated": safe_text(profile["sector_aggregated"], 80),
        "size_band": profile["size_band"],
        "respondent_role": profile["respondent_role"],
    }


def validate_adult_answers(answers: Any) -> dict[str, Any]:
    if not isinstance(answers, dict) or not ADULT_REQUIRED.issubset(answers) or set(answers) - ADULT_ALLOWED:
        raise ResearchValidationError("adult answer schema mismatch")
    out = dict(answers)
    for field in ADULT_RATINGS:
        out[field] = rating(answers[field], 1, 5, field)
    out["Q02"] = rating(answers["Q02"], 0, 4, "Q02")
    if not isinstance(answers["Q07"], bool):
        raise ResearchValidationError("Q07 must be boolean")
    out["Q07_topic"] = safe_text(answers.get("Q07_topic"), 120) if answers["Q07"] else ""
    out["Q08"] = bounded_list(answers["Q08"], "Q08", 3)
    out["Q09"] = bounded_list(answers["Q09"], "Q09")
    out["Q10"] = exact_rating_map(answers["Q10"], ADULT_Q10_KEYS, "Q10")
    out["Q11"] = safe_text(answers["Q11"], 160)
    out["Q12"] = safe_text(answers["Q12"], 500)
    return out


def validate_employer_answers(answers: Any) -> dict[str, Any]:
    if not isinstance(answers, dict) or not EMPLOYER_REQUIRED.issubset(answers) or set(answers) - EMPLOYER_ALLOWED:
        raise ResearchValidationError("employer answer schema mismatch")
    out = dict(answers)
    out["E01"] = safe_text(answers["E01"], 160)
    out["E02"] = bounded_list(answers["E02"], "E02")
    out["E03"] = exact_rating_map(answers["E03"], EMPLOYER_E03_KEYS, "E03")
    out["E04"] = safe_text(answers["E04"], 80)
    out["E04_detail"] = safe_text(answers.get("E04_detail"), 350) if answers["E04"] == "da" else ""
    out["E05"] = safe_text(answers["E05"], 80)
    out["E06"] = bounded_list(answers["E06"], "E06", 3)
    out["E07"] = safe_text(answers["E07"], 80)
    out["E08"] = bounded_list(answers["E08"], "E08", 5)
    out["E09"] = safe_text(answers["E09"], 500)
    out["E10"] = safe_text(answers["E10"], 80)
    return out


def validate_submission(payload: Any, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract()
    if contract.get("crm_integration") != "FORBIDDEN" or contract.get("commercial_analytics") != "FORBIDDEN":
        raise ResearchValidationError("research isolation contract is not fail-closed")
    if not isinstance(payload, dict) or set(payload) != TOP_LEVEL:
        raise ResearchValidationError(f"top-level fields must be exactly {sorted(TOP_LEVEL)}")
    reject_forbidden_keys(payload)
    if payload["notice_read_and_voluntary_participation"] is not True:
        raise ResearchValidationError("voluntary participation acknowledgement is required")
    form_id = payload["form_id"]
    if form_id not in {"AI4WORK_ADULTS_V1", "AI4WORK_EMPLOYERS_V1"}:
        raise ResearchValidationError("unknown form_id")
    profile = validate_profile(payload["profile"], form_id)
    answers = validate_adult_answers(payload["answers"]) if form_id == "AI4WORK_ADULTS_V1" else validate_employer_answers(payload["answers"])
    return {
        "schema_version": 1,
        "research_id": contract["research_id"],
        "form_id": form_id,
        "form_version": 1,
        "response_id": str(uuid.uuid4()),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "answers": answers,
        "synthetic": False,
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Validate one AI4WORK research submission and emit a research-only analytical record.")
    parser.add_argument("payload", type=Path)
    args = parser.parse_args()
    try:
        record = validate_submission(json.loads(args.payload.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ResearchValidationError) as exc:
        raise SystemExit(f"REJECTED: {exc}")
    print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
