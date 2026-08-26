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

ADULT_Q08 = {"costul", "lipsa timpului", "program incompatibil", "lipsa unei oferte relevante", "distanța/deplasarea", "lipsa informației", "lipsa sprijinului angajatorului", "nu am considerat necesar", "altul"}
ADULT_Q09 = {"rezultate factual greșite", "rezultate greu de verificat", "probleme privind datele/confidențialitatea", "nu am știut cum să formulez cererea", "integrare dificilă în aplicațiile/procesele folosite", "nu am putut evalua calitatea rezultatului", "nu am întâlnit probleme", "nu am folosit AI"}
ADULT_Q11 = {"adaptare mai bună la postul actual", "acces la un loc de muncă nou", "schimbare de ocupație", "productivitate/calitate mai bună", "altul"}
ADULT_Q10_KEYS = {"utilizare_digitala_functionala", "utilizarea_instrumentelor_AI", "verificarea_rezultatelor_AI", "protectia_datelor_confidentialitate", "integrarea_AI_in_flux_de_lucru"}

EMPLOYER_E01 = {"da, în producție/activitate curentă", "pilot/test", "intenție în următoarele 12 luni", "nu", "nu știu"}
EMPLOYER_E02 = {"redactare/comunicare", "analiză date", "suport clienți", "marketing/vânzări", "programare/IT", "operațiuni/producție", "HR", "documente/compliance", "automatizare fluxuri", "altul"}
EMPLOYER_E03_KEYS = {"formularea_cerintelor", "verificarea_calitatii", "protectia_datelor", "limitele_si_riscurile_AI", "integrarea_in_procese", "definirea_fluxului_asistat_AI", "competente_digitale_generale"}
EMPLOYER_E04 = {"da", "nu", "nu este relevant"}
EMPLOYER_E05 = {"da, intern", "da, extern", "ambele", "nu"}
EMPLOYER_E06 = {"cost", "timp disponibil", "lipsa furnizorilor/ofertei potrivite", "conținut prea general", "schimbare tehnologică rapidă", "dificultate de măsurare a rezultatelor", "lipsă interes intern", "lipsa unei politici clare privind AI", "altul"}
EMPLOYER_E07 = {"semnificativ", "moderat", "puțin", "deloc", "nu putem estima"}
EMPLOYER_E08 = {"formularea și rafinarea instrucțiunilor", "verificarea factuală/calității", "analiză și interpretare de date", "protecția datelor", "securitate digitală", "automatizarea unor pași de lucru", "integrarea AI în aplicații/procese", "documentarea și trasabilitatea rezultatelor", "supraveghere umană/decizie", "altul"}
EMPLOYER_E10 = {"da", "posibil", "nu"}

TOP_LEVEL_FIELDS = {"form_id", "notice_read_and_voluntary_participation", "profile", "answers"}
FORBIDDEN_KEY_TOKENS = {"name", "surname", "cnp", "email", "phone", "address", "organisation_name", "organization_name", "employer_name", "cui", "ip", "user_agent", "cookie", "marketing_id", "account_id"}
PII_PATTERNS = {
    "email": re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    "phone": re.compile(r"(?<!\d)(?:\+?40|0)\s?7(?:[ .-]?\d){8}(?!\d)"),
    "cnp_like": re.compile(r"(?<!\d)[1-8]\d{12}(?!\d)"),
    "url": re.compile(r"(?i)\b(?:https?://|www\.)\S+"),
}


class ResearchValidationError(ValueError):
    pass


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(value: Any, limit: int) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        raise ResearchValidationError(f"text exceeds {limit} characters")
    return text


def reject_forbidden_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_l = str(key).lower()
            if key_l in FORBIDDEN_KEY_TOKENS:
                raise ResearchValidationError(f"forbidden identifier field at {path}.{key}")
            reject_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            reject_forbidden_keys(child, f"{path}[{idx}]")


def scan_text_for_pii(text: str) -> list[str]:
    return [label for label, pattern in PII_PATTERNS.items() if pattern.search(text)]


def safe_free_text(value: Any, limit: int) -> str:
    text = normalize_text(value, limit)
    hits = scan_text_for_pii(text)
    if hits:
        raise ResearchValidationError(f"free text contains prohibited identifier-like data: {sorted(hits)}")
    return text


def require_int(value: Any, low: int, high: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ResearchValidationError(f"{field} must be integer {low}..{high}")
    return value


def enum(value: Any, allowed: set[str], field: str) -> str:
    text = normalize_text(value, 160)
    if text not in allowed:
        raise ResearchValidationError(f"invalid {field}")
    return text


def string_list(value: Any, allowed: set[str], field: str, max_items: int | None = None) -> list[str]:
    if not isinstance(value, list):
        raise ResearchValidationError(f"{field} must be a list")
    if max_items is not None and len(value) > max_items:
        raise ResearchValidationError(f"{field} allows at most {max_items} selections")
    result: list[str] = []
    for raw in value:
        item = enum(raw, allowed, field)
        if item not in result:
            result.append(item)
    return result


def rating_map(value: Any, keys: set[str], field: str) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ResearchValidationError(f"{field} must contain exactly {sorted(keys)}")
    return {key: require_int(value[key], 1, 5, f"{field}.{key}") for key in sorted(keys)}


def validate_profile(profile: Any, form_id: str) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise ResearchValidationError("profile must be an object")
    if form_id == "AI4WORK_ADULTS_V1":
        allowed = {"region", "status", "age_band", "occupational_family"}
        if set(profile) - allowed:
            raise ResearchValidationError("adult profile contains unsupported fields")
        return {
            "region": enum(profile.get("region"), REGIONS, "profile.region"),
            "status": enum(profile.get("status"), ADULT_STATUS, "profile.status"),
            "age_band": enum(profile.get("age_band"), AGE_BANDS, "profile.age_band"),
            "occupational_family": safe_free_text(profile.get("occupational_family"), 80),
        }
    allowed = {"region", "sector_aggregated", "size_band", "respondent_role"}
    if set(profile) - allowed:
        raise ResearchValidationError("employer profile contains unsupported fields")
    return {
        "region": enum(profile.get("region"), REGIONS, "profile.region"),
        "sector_aggregated": safe_free_text(profile.get("sector_aggregated"), 80),
        "size_band": enum(profile.get("size_band"), EMPLOYER_SIZE, "profile.size_band"),
        "respondent_role": enum(profile.get("respondent_role"), EMPLOYER_ROLE, "profile.respondent_role"),
    }


def validate_adult_answers(answers: Any) -> dict[str, Any]:
    if not isinstance(answers, dict):
        raise ResearchValidationError("answers must be an object")
    allowed = {"Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q07_topic", "Q08", "Q09", "Q10", "Q11", "Q12"}
    unknown = set(answers) - allowed
    if unknown:
        raise ResearchValidationError(f"unsupported adult answers: {sorted(unknown)}")
    required = {"Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q08", "Q09", "Q10", "Q11", "Q12"}
    missing = required - set(answers)
    if missing:
        raise ResearchValidationError(f"missing adult answers: {sorted(missing)}")
    if not isinstance(answers["Q07"], bool):
        raise ResearchValidationError("Q07 must be boolean")
    normalized = {
        "Q01": require_int(answers["Q01"], 1, 5, "Q01"),
        "Q02": require_int(answers["Q02"], 0, 4, "Q02"),
        "Q03": require_int(answers["Q03"], 1, 5, "Q03"),
        "Q04": require_int(answers["Q04"], 1, 5, "Q04"),
        "Q05": require_int(answers["Q05"], 1, 5, "Q05"),
        "Q06": require_int(answers["Q06"], 1, 5, "Q06"),
        "Q07": answers["Q07"],
        "Q07_topic": safe_free_text(answers.get("Q07_topic"), 120) if answers["Q07"] else "",
        "Q08": string_list(answers["Q08"], ADULT_Q08, "Q08", 3),
        "Q09": string_list(answers["Q09"], ADULT_Q09, "Q09"),
        "Q10": rating_map(answers["Q10"], ADULT_Q10_KEYS, "Q10"),
        "Q11": enum(answers["Q11"], ADULT_Q11, "Q11"),
        "Q12": safe_free_text(answers["Q12"], 500),
    }
    return normalized


def validate_employer_answers(answers: Any) -> dict[str, Any]:
    if not isinstance(answers, dict):
        raise ResearchValidationError("answers must be an object")
    allowed = {"E01", "E02", "E03", "E04", "E04_detail", "E05", "E06", "E07", "E08", "E09", "E10"}
    unknown = set(answers) - allowed
    if unknown:
        raise ResearchValidationError(f"unsupported employer answers: {sorted(unknown)}")
    required = {"E01", "E02", "E03", "E04", "E05", "E06", "E07", "E08", "E09", "E10"}
    missing = required - set(answers)
    if missing:
        raise ResearchValidationError(f"missing employer answers: {sorted(missing)}")
    e04 = enum(answers["E04"], EMPLOYER_E04, "E04")
    return {
        "E01": enum(answers["E01"], EMPLOYER_E01, "E01"),
        "E02": string_list(answers["E02"], EMPLOYER_E02, "E02"),
        "E03": rating_map(answers["E03"], EMPLOYER_E03_KEYS, "E03"),
        "E04": e04,
        "E04_detail": safe_free_text(answers.get("E04_detail"), 350) if e04 == "da" else "",
        "E05": enum(answers["E05"], EMPLOYER_E05, "E05"),
        "E06": string_list(answers["E06"], EMPLOYER_E06, "E06", 3),
        "E07": enum(answers["E07"], EMPLOYER_E07, "E07"),
        "E08": string_list(answers["E08"], EMPLOYER_E08, "E08", 5),
        "E09": safe_free_text(answers["E09"], 500),
        "E10": enum(answers["E10"], EMPLOYER_E10, "E10"),
    }


def validate_submission(payload: Any, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract()
    if contract.get("crm_integration") != "FORBIDDEN":
        raise ResearchValidationError("research contract must forbid CRM integration")
    if not isinstance(payload, dict):
        raise ResearchValidationError("payload must be an object")
    if set(payload) != TOP_LEVEL_FIELDS:
        raise ResearchValidationError(f"top-level fields must be exactly {sorted(TOP_LEVEL_FIELDS)}")
    reject_forbidden_keys(payload)
    if payload.get("notice_read_and_voluntary_participation") is not True:
        raise ResearchValidationError("voluntary participation acknowledgement is required")
    form_id = payload.get("form_id")
    if form_id not in {"AI4WORK_ADULTS_V1", "AI4WORK_EMPLOYERS_V1"}:
        raise ResearchValidationError("unknown form_id")
    profile = validate_profile(payload.get("profile"), form_id)
    answers = validate_adult_answers(payload.get("answers")) if form_id == "AI4WORK_ADULTS_V1" else validate_employer_answers(payload.get("answers"))
    return {
        "schema_version": 1,
        "research_id": contract["research_id"],
        "form_id": form_id,
        "form_version": 1,
        "response_id": str(uuid.uuid4()),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "answers": answers,
        "synthetic": false if False else False
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Validate one AI4WORK research submission and emit the canonical analytical record.")
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
