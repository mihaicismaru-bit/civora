from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from contracts import FactKernel
from editorial_integrity import validate_editorial_package

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "valcea-clar" / "scripts"

SOURCE_PROFILES = {
    "ipj": {
        "module": "ipj_valcea_public_safety_detail_evidence",
        "institution": "Inspectoratul de Poliție Județean Vâlcea",
        "short_name": "IPJ Vâlcea",
        "authority_class": "FIRST_PARTY_COUNTY_POLICE_ARTICLE_DETAIL_EVIDENCE",
        "observation_state": "POLICE_SOURCE_DETAIL_EVIDENCE_NON_AUTHORIZING",
        "source_scope": "POLICE_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
        "verification_state": "POLICE_SOURCE_TEXT_EVIDENCE_CAPTURED_NON_AUTHORIZING",
        "allowed_tags": {
            "POLICE_REPORTED_OBSERVATION",
            "PROCEDURAL_MEASURE",
            "ALLEGATION_OR_SUSPICION",
            "ROAD_OR_PUBLIC_SAFETY_MEASURE",
        },
    },
    "isu": {
        "module": "isu_valcea_emergency_detail_evidence",
        "institution": "Inspectoratul pentru Situații de Urgență Vâlcea",
        "short_name": "ISU Vâlcea",
        "authority_class": "FIRST_PARTY_COUNTY_EMERGENCY_ARTICLE_DETAIL_EVIDENCE",
        "observation_state": "ISU_SOURCE_DETAIL_EVIDENCE_NON_AUTHORIZING",
        "source_scope": "ISU_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
        "verification_state": "ISU_SOURCE_TEXT_EVIDENCE_CAPTURED_NON_AUTHORIZING",
        "allowed_tags": {
            "ISU_REPORTED_OBSERVATION",
            "RESPONSE_ACTION",
            "REPORTED_AFFECTED_OR_CASUALTY",
            "REPORTED_CAUSE_OR_ORIGIN",
            "PUBLIC_PROTECTION_WARNING_OR_RESTRICTION",
            "REPORTED_NUMERIC_COUNT",
        },
    },
}

ROMANIAN_MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}

KNOWN_VALCEA_PLACES = (
    "Râmnicu Vâlcea",
    "Drăgășani",
    "Băile Olănești",
    "Băile Govora",
    "Călimănești",
    "Horezu",
    "Brezoi",
    "Bălcești",
    "Ocnele Mari",
    "Berbești",
    "Băbeni",
    "Bujoreni",
    "Dăești",
    "Ionești",
    "Lădești",
    "Măciuca",
    "Păușești-Măglași",
    "Pietrari",
    "Budești",
    "Vlădești",
    "Voineasa",
    "Malaia",
    "Costești",
    "Vaideeni",
    "Mihăești",
    "Șirineasa",
    "Frâncești",
    "Orlești",
    "Prundeni",
    "Galicea",
    "Mădulari",
    "Lăpușata",
    "județul Vâlcea",
)

PLACE_MARKER_RE = re.compile(
    r"\b(?:municipiul|municipiului|orașul|orașului|orasul|orasului|localitatea|localității|localitatii|comuna|comunei|satul|satului)\s+"
    r"([^,.;:()\n]{2,90})"
)
PLACE_STOPWORDS = {
    "din", "de", "pentru", "unde", "care", "iar", "și", "si", "în", "in", "cu", "la", "al", "a", "ale", "ai",
}


def _today_bucharest() -> date:
    return datetime.now(ZoneInfo("Europe/Bucharest")).date()


def _fold(value: Any) -> str:
    text = str(value or "").casefold().replace("ş", "ș").replace("ţ", "ț")
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def _parse_visible_date(value: Any) -> date | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    for pattern, order in (
        (r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/]([0-3]?\d)\b", "ymd"),
        (r"\b([0-3]?\d)[.\-/](0?[1-9]|1[0-2])[.\-/](20\d{2})\b", "dmy"),
    ):
        match = re.search(pattern, text)
        if match:
            try:
                if order == "ymd":
                    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
            except ValueError:
                return None
    folded = _fold(text)
    months = "|".join(ROMANIAN_MONTHS)
    match = re.search(rf"\b([0-3]?\d)\s+({months})\s+(20\d{{2}})\b", folded)
    if match:
        try:
            return date(int(match.group(3)), ROMANIAN_MONTHS[match.group(2)], int(match.group(1)))
        except ValueError:
            return None
    return None


def _clean_marker_candidate(value: str) -> str | None:
    words = [word.strip("'\"„”«»[]{}") for word in value.split()]
    accepted: list[str] = []
    for word in words[:4]:
        if not word:
            continue
        if _fold(word) in {_fold(v) for v in PLACE_STOPWORDS}:
            break
        first = word[0]
        if not (first.isupper() or first.isdigit()):
            break
        if accepted and len(word) > 2 and word.isupper():
            break
        accepted.append(word)
    candidate = " ".join(accepted).strip(" ,.;:()")
    return candidate or None


def _places_in_text(text: str) -> list[str]:
    candidates: list[tuple[int, str]] = []
    folded = _fold(text)
    for place in KNOWN_VALCEA_PLACES:
        pos = folded.find(_fold(place))
        if pos >= 0:
            candidates.append((pos, place))
    for match in PLACE_MARKER_RE.finditer(text):
        candidate = _clean_marker_candidate(match.group(1))
        if candidate:
            candidates.append((match.start(1), candidate))
    candidates.sort(key=lambda item: item[0])
    seen: set[str] = set()
    ordered: list[str] = []
    for _pos, place in candidates:
        key = _fold(place)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(place)
    return ordered


def _explicit_places(detail: dict[str, Any]) -> list[str]:
    index_title = str(detail.get("index_title") or "").strip()
    if index_title:
        places = _places_in_text(index_title)
        if places:
            return places
    visible_title = str(detail.get("visible_title") or "").strip()
    if visible_title:
        places = _places_in_text(visible_title)
        if places:
            return places
    evidence_parts: list[str] = []
    for field in detail.get("field_evidence") or []:
        if isinstance(field, dict):
            excerpt = str(field.get("excerpt") or "").strip()
            if excerpt:
                evidence_parts.append(excerpt)
    return _places_in_text(" ".join(evidence_parts))


def _evidence_ids(detail: dict[str, Any]) -> list[str]:
    values: list[str] = []
    index_sha = str(detail.get("index_evidence_sha256") or "").strip()
    detail_sha = str(detail.get("detail_sha256") or "").strip()
    if index_sha:
        values.append(f"index:{index_sha}")
    if detail_sha:
        values.append(f"detail:{detail_sha}")
    for field in detail.get("field_evidence") or []:
        if isinstance(field, dict):
            sha = str(field.get("evidence_sha256") or "").strip()
            if sha:
                values.append(f"field:{sha}")
    return list(dict.fromkeys(values))


def _observed_tags(detail: dict[str, Any], allowed: set[str]) -> list[str]:
    values: list[str] = []
    for field in detail.get("field_evidence") or []:
        if not isinstance(field, dict):
            continue
        for tag in field.get("epistemic_tags") or []:
            tag_text = str(tag)
            if tag_text in allowed and tag_text not in values:
                values.append(tag_text)
    return values


def _semantic_claims(source: str, tags: Iterable[str]) -> list[str]:
    claims: list[str] = []
    tag_set = set(tags)
    if source == "ipj":
        if "POLICE_REPORTED_OBSERVATION" in tag_set:
            claims.append("IPJ Vâlcea relatează în material o observație sau o acțiune atribuită polițiștilor.")
        if "ROAD_OR_PUBLIC_SAFETY_MEASURE" in tag_set:
            claims.append("Materialul IPJ descrie o măsură de siguranță rutieră sau de ordine publică.")
        if "ALLEGATION_OR_SUSPICION" in tag_set:
            claims.append("Materialul IPJ formulează o suspiciune sau acuzație; aceasta rămâne atribuită sursei și nu este tratată ca fapt independent verificat.")
        if "PROCEDURAL_MEASURE" in tag_set:
            claims.append("Materialul IPJ menționează o măsură procedurală; Core v2 nu o echivalează cu o constatare de vinovăție.")
    else:
        if "ISU_REPORTED_OBSERVATION" in tag_set:
            claims.append("ISU Vâlcea relatează în material o observație sau situație consemnată de inspectorat.")
        if "RESPONSE_ACTION" in tag_set:
            claims.append("Materialul ISU descrie o acțiune de intervenție raportată de inspectorat.")
        if "REPORTED_AFFECTED_OR_CASUALTY" in tag_set:
            claims.append("Materialul ISU conține informații despre persoane afectate sau victime raportate; Core v2 nu extinde aceste informații dincolo de formularea sursei.")
        if "REPORTED_CAUSE_OR_ORIGIN" in tag_set:
            claims.append("Materialul ISU menționează o cauză sau origine raportată; Core v2 nu o tratează ca determinare independentă.")
        if "PUBLIC_PROTECTION_WARNING_OR_RESTRICTION" in tag_set:
            claims.append("Materialul ISU include o avertizare, restricție sau măsură de protecție publică raportată de inspectorat.")
        if "REPORTED_NUMERIC_COUNT" in tag_set:
            claims.append("Materialul ISU conține un număr raportat; Core v2 nu îl transformă în capacitate sau stare live fără verificare separată.")
    return claims


def _block(detail_id: str, reason: str) -> dict[str, Any]:
    return {
        "detail_id": detail_id,
        "state": "BLOCKED",
        "reason": reason,
        "publication_authority": "NONE",
    }


def _no_story(detail_id: str, reason: str) -> dict[str, Any]:
    return {
        "detail_id": detail_id,
        "state": "NO_STORY",
        "reason": reason,
        "publication_authority": "NONE",
    }


def promote_detail(source: str, detail: dict[str, Any], *, as_of: date, max_age_days: int = 7) -> dict[str, Any]:
    profile = SOURCE_PROFILES[source]
    detail_sha = str(detail.get("detail_sha256") or "").strip()
    detail_id = detail_sha[:24] if detail_sha else str(detail.get("detail_url") or "UNKNOWN")

    if str(detail.get("authority_class") or "") != profile["authority_class"]:
        return _block(detail_id, "authority_class_mismatch")
    if str(detail.get("observation_state") or "") != profile["observation_state"]:
        return _block(detail_id, "observation_state_mismatch")
    if str(detail.get("source_assertion_scope") or "") != profile["source_scope"]:
        return _block(detail_id, "source_assertion_scope_mismatch")
    if str(detail.get("verification_state") or "") != profile["verification_state"]:
        return _block(detail_id, "verification_state_mismatch")

    detail_url = str(detail.get("detail_url") or "").strip()
    if not detail_url.startswith("https://"):
        return _block(detail_id, "first_party_detail_url_missing")
    title = str(detail.get("index_title") or detail.get("visible_title") or "").strip()
    if len(title) < 12:
        return _block(detail_id, "source_title_insufficient")

    visible_date = _parse_visible_date(detail.get("explicit_date_text"))
    if visible_date is None:
        return _no_story(detail_id, "explicit_source_date_missing")
    if visible_date < as_of - timedelta(days=max_age_days):
        return _no_story(detail_id, "stale_first_party_detail")
    if visible_date > as_of + timedelta(days=1):
        return _block(detail_id, "future_source_date_anomaly")

    places = _explicit_places(detail)
    if not places:
        return _block(detail_id, "explicit_geography_missing")
    if len(places) > 1:
        return _block(detail_id, "ambiguous_multiple_geographies")
    place = places[0]

    allowed_tags = set(profile["allowed_tags"])
    tags = _observed_tags(detail, allowed_tags)
    if not tags:
        return _no_story(detail_id, "no_material_tagged_field_evidence")

    evidence_ids = _evidence_ids(detail)
    if len(evidence_ids) < 3:
        return _block(detail_id, "evidence_chain_incomplete")

    institution = str(profile["institution"])
    short_name = str(profile["short_name"])
    date_claim = (
        f"Pagina oficială {short_name} afișează data {detail.get('explicit_date_text')}; "
        "Core v2 tratează această dată ca dată vizibilă a materialului, nu ca moment confirmat al incidentului."
    )
    place_claim = f"Localizarea identificată explicit în material este {place}."
    content_claims = _semantic_claims(source, tags)
    if not content_claims:
        return _no_story(detail_id, "material_semantics_not_safely_promotable")

    claims = [
        f"{institution} a publicat pe domeniul său oficial materialul «{title}».",
        date_claim,
        place_claim,
        *content_claims,
    ]
    kernel = FactKernel(
        what=title,
        who=institution,
        where=place,
        when=f"data vizibilă a materialului oficial: {detail.get('explicit_date_text')}",
        why_it_matters=(
            "Materialul conține informații de siguranță publică provenite dintr-o sursă instituțională primară; "
            "Core v2 păstrează explicit limitele epistemice ale sursei și nu transformă raportarea instituției în verificare independentă."
        ),
        source=f"{institution} — material oficial",
        source_url=detail_url,
        claims=tuple(claims),
        evidence_ids=tuple(evidence_ids),
    )
    kernel.validate()

    if source == "ipj":
        epistemic_note = (
            "Orice suspiciune, acuzație ori măsură procedurală rămâne atribuită IPJ Vâlcea. "
            "Core v2 nu prezintă o reținere, un arest, o percheziție sau o cercetare drept constatare de vinovăție."
        )
    else:
        epistemic_note = (
            "Cauzele, numărul persoanelor afectate și valorile numerice rămân raportări ale ISU Vâlcea. "
            "Core v2 nu le extinde la cauze stabilite independent, stare live ori capacitate operațională fără verificare separată."
        )

    body = (
        f"{institution} a publicat pe site-ul oficial materialul «{title}». "
        f"Pagina sursă afișează data {detail.get('explicit_date_text')}; această dată este tratată aici ca data vizibilă a materialului, nu ca moment confirmat al evenimentului. "
        f"Localizarea identificată explicit în text este {place}.\n\n"
        f"Din câmpurile de evidență extrase strict din corpul paginii oficiale rezultă că materialul include următoarele tipuri de informații: {', '.join(tags)}. "
        f"{epistemic_note}\n\n"
        "Această ieșire este un produs editorial de tip shadow pentru verificarea contractelor Core v2. "
        "Nu acordă autoritate de publicare, nu afirmă stare curentă și nu folosește textele legacy ca sursă de adevăr."
    )
    package = {
        "headline": title,
        "body": body,
        "writer_id": "shadow_attribution_writer_v1",
        "production_writer_ready": False,
        "claims": [
            {
                "text": claim,
                "kernel_claim_index": index,
                "evidence_ids": evidence_ids,
            }
            for index, claim in enumerate(claims)
        ],
    }
    integrity = validate_editorial_package(kernel, package)
    if not integrity.pass_gate:
        return _block(detail_id, "deterministic_article_integrity_failed")

    return {
        "detail_id": detail_id,
        "state": "VERIFIED_WRITTEN_SHADOW",
        "publication_authority": "NONE",
        "source_kind": source,
        "fact_kernel": {
            "what": kernel.what,
            "who": kernel.who,
            "where": kernel.where,
            "when": kernel.when,
            "why_it_matters": kernel.why_it_matters,
            "source": kernel.source,
            "source_url": kernel.source_url,
            "claims": list(kernel.claims),
            "evidence_ids": list(kernel.evidence_ids),
        },
        "article_package": package,
        "epistemic_tags": tags,
        "integrity": {
            "status": integrity.status,
            "fabricated_claims": integrity.fabricated_claims,
            "bound_claims": integrity.bound_claims,
            "errors": list(integrity.errors),
        },
        "production_writer_ready": False,
    }


def verify_receipt(source: str, receipt: dict[str, Any], *, as_of: date | None = None) -> dict[str, Any]:
    if source not in SOURCE_PROFILES:
        raise ValueError(f"unsupported public-safety source: {source}")
    as_of = as_of or _today_bucharest()
    profile = SOURCE_PROFILES[source]

    if str(receipt.get("status") or "") != "PASS":
        return {
            "schema_version": "1.0",
            "mode": "PUBLIC_SAFETY_SHADOW_VERIFICATION",
            "source_kind": source,
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "status": "BLOCKED_SOURCE_RECEIPT",
            "reason": str(receipt.get("status") or "missing_status"),
            "rows": [],
        }
    if str(receipt.get("authority_class") or "") != profile["authority_class"]:
        return {
            "schema_version": "1.0",
            "mode": "PUBLIC_SAFETY_SHADOW_VERIFICATION",
            "source_kind": source,
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "status": "BLOCKED_SOURCE_CONTRACT",
            "rows": [],
        }
    if str(receipt.get("observation_state") or "") != profile["observation_state"]:
        return {
            "schema_version": "1.0",
            "mode": "PUBLIC_SAFETY_SHADOW_VERIFICATION",
            "source_kind": source,
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "status": "BLOCKED_SOURCE_CONTRACT",
            "rows": [],
        }
    if str(receipt.get("source_assertion_scope") or "") != profile["source_scope"]:
        return {
            "schema_version": "1.0",
            "mode": "PUBLIC_SAFETY_SHADOW_VERIFICATION",
            "source_kind": source,
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "status": "BLOCKED_SOURCE_CONTRACT",
            "rows": [],
        }
    if receipt.get("material_fact_use") is not False or receipt.get("fact_kernel_write_authorized") is not False:
        return {
            "schema_version": "1.0",
            "mode": "PUBLIC_SAFETY_SHADOW_VERIFICATION",
            "source_kind": source,
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "status": "BLOCKED_UPSTREAM_AUTHORITY_CHANGED",
            "rows": [],
        }

    rows = [promote_detail(source, row, as_of=as_of) for row in receipt.get("details") or [] if isinstance(row, dict)]
    verified = sum(row.get("state") == "VERIFIED_WRITTEN_SHADOW" for row in rows)
    no_story = sum(row.get("state") == "NO_STORY" for row in rows)
    blocked = sum(row.get("state") == "BLOCKED" for row in rows)
    fabricated = sum(int((row.get("integrity") or {}).get("fabricated_claims") or 0) for row in rows)
    return {
        "schema_version": "1.0",
        "mode": "PUBLIC_SAFETY_SHADOW_VERIFICATION",
        "source_kind": source,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "as_of_date": as_of.isoformat(),
        "detail_count": len(rows),
        "verified_written_shadow_count": verified,
        "no_story_count": no_story,
        "blocked_count": blocked,
        "fabricated_claim_count": fabricated,
        "rows": rows,
        "truth_rule": (
            "Non-authorizing first-party detail evidence may be promoted only through the Core v2 gate; "
            "all material claims remain attributed, source-date is not event-time, and police procedural/allegation language or ISU cause/count language keeps explicit epistemic limits."
        ),
    }


def _live_receipt(source: str) -> dict[str, Any]:
    sys.path.insert(0, str(SCRIPTS))
    module = importlib.import_module(str(SOURCE_PROFILES[source]["module"]))
    return module.build_live_receipt()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Core v2 IPJ/ISU first-party evidence promotion in shadow mode")
    parser.add_argument("--source", required=True, choices=sorted(SOURCE_PROFILES))
    parser.add_argument("--input")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if bool(args.input) == bool(args.live):
        raise SystemExit("provide exactly one of --input or --live")

    try:
        receipt = _live_receipt(args.source) if args.live else json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = verify_receipt(args.source, receipt)
    except Exception as exc:
        result = {
            "schema_version": "1.0",
            "mode": "PUBLIC_SAFETY_SHADOW_VERIFICATION",
            "source_kind": args.source,
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "status": "BLOCKED_SOURCE_UNAVAILABLE",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "rows": [],
        }

    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result.get("status", "PASS_SHADOW"),
        "source_kind": args.source,
        "detail_count": result.get("detail_count", 0),
        "verified_written_shadow_count": result.get("verified_written_shadow_count", 0),
        "no_story_count": result.get("no_story_count", 0),
        "blocked_count": result.get("blocked_count", 0),
        "fabricated_claim_count": result.get("fabricated_claim_count", 0),
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
