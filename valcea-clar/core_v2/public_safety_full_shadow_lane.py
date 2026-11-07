from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from contracts import FactKernel
from editorial_integrity import validate_editorial_package
from public_safety_shadow_lane import (
    SOURCE_PROFILES,
    _live_receipt,
    _parse_visible_date,
    verify_receipt,
)


TAG_TO_FACT_TYPE = {
    "POLICE_REPORTED_OBSERVATION": "reported_observation",
    "ROAD_OR_PUBLIC_SAFETY_MEASURE": "public_safety_measure",
    "ALLEGATION_OR_SUSPICION": "allegation_or_suspicion",
    "PROCEDURAL_MEASURE": "procedural_measure",
    "ISU_REPORTED_OBSERVATION": "reported_observation",
    "RESPONSE_ACTION": "response_action",
    "REPORTED_AFFECTED_OR_CASUALTY": "reported_affected_or_casualty",
    "REPORTED_CAUSE_OR_ORIGIN": "reported_cause_or_origin",
    "PUBLIC_PROTECTION_WARNING_OR_RESTRICTION": "public_protection_warning_or_restriction",
    "REPORTED_NUMERIC_COUNT": "reported_numeric_count",
}

DATE_TOKEN = (
    r"(?:[0-3]?\d[.\-/](?:0?[1-9]|1[0-2])[.\-/]20\d{2}|"
    r"[0-3]?\d\s+(?:ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+20\d{2})"
)
EVENT_DATE_RE = re.compile(
    rf"\b(?:în|in|la)\s+(?:data|ziua)\s+(?:de\s+)?(?P<date>{DATE_TOKEN})\b",
    re.IGNORECASE,
)
EVENT_CLOCK_RE = re.compile(
    r"\b(?:ora|orei)\s+(?P<hour>[01]?\d|2[0-3])[:.]?(?P<minute>[0-5]\d)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EventTimeResult:
    status: str
    event_date: str | None
    event_time: str | None
    evidence_ids: tuple[str, ...]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "event_date": self.event_date,
            "event_time": self.event_time,
            "evidence_ids": list(self.evidence_ids),
            "reason": self.reason,
        }


def _detail_id(detail: dict[str, Any]) -> str:
    sha = str(detail.get("detail_sha256") or "").strip()
    return sha[:24] if sha else str(detail.get("detail_url") or "UNKNOWN")


def _field_evidence_id(field: dict[str, Any]) -> str | None:
    sha = str(field.get("evidence_sha256") or "").strip()
    return f"field:{sha}" if sha else None


def _normalize_excerpt(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def reconcile_event_time(detail: dict[str, Any], *, source_visible_date: date) -> EventTimeResult:
    candidates: dict[str, set[str]] = {}
    clocks: dict[str, set[str]] = {}
    for field in detail.get("field_evidence") or []:
        if not isinstance(field, dict):
            continue
        excerpt = _normalize_excerpt(field.get("excerpt"))
        evidence_id = _field_evidence_id(field)
        if not excerpt or not evidence_id:
            continue
        for match in EVENT_DATE_RE.finditer(excerpt):
            parsed = _parse_visible_date(match.group("date"))
            if parsed is not None:
                candidates.setdefault(parsed.isoformat(), set()).add(evidence_id)
        for match in EVENT_CLOCK_RE.finditer(excerpt):
            clock = f"{int(match.group('hour')):02d}:{int(match.group('minute')):02d}"
            clocks.setdefault(clock, set()).add(evidence_id)

    if not candidates:
        return EventTimeResult(
            status="UNKNOWN",
            event_date=None,
            event_time=None,
            evidence_ids=(),
            reason="no_explicit_event_role_date_in_field_evidence",
        )
    if len(candidates) > 1:
        evidence = sorted({eid for values in candidates.values() for eid in values})
        return EventTimeResult(
            status="AMBIGUOUS",
            event_date=None,
            event_time=None,
            evidence_ids=tuple(evidence),
            reason="multiple_explicit_event_dates",
        )

    event_date_text = next(iter(candidates))
    event_date = date.fromisoformat(event_date_text)
    evidence = set(candidates[event_date_text])
    if event_date > source_visible_date + timedelta(days=1):
        return EventTimeResult(
            status="ANOMALOUS_FUTURE",
            event_date=event_date_text,
            event_time=None,
            evidence_ids=tuple(sorted(evidence)),
            reason="explicit_event_date_after_visible_source_date",
        )

    event_clock: str | None = None
    if len(clocks) == 1:
        event_clock = next(iter(clocks))
        evidence.update(clocks[event_clock])
    elif len(clocks) > 1:
        evidence.update(eid for values in clocks.values() for eid in values)
        return EventTimeResult(
            status="AMBIGUOUS",
            event_date=event_date_text,
            event_time=None,
            evidence_ids=tuple(sorted(evidence)),
            reason="multiple_explicit_event_times",
        )

    return EventTimeResult(
        status="EXPLICIT_DATETIME" if event_clock else "EXPLICIT_DATE",
        event_date=event_date_text,
        event_time=event_clock,
        evidence_ids=tuple(sorted(evidence)),
        reason="explicit_event_role_marker_in_field_evidence",
    )


def extract_material_facts(source: str, detail: dict[str, Any]) -> list[dict[str, Any]]:
    profile = SOURCE_PROFILES[source]
    allowed_tags = set(profile["allowed_tags"])
    short_name = str(profile["short_name"])
    facts: list[dict[str, Any]] = []
    for field in detail.get("field_evidence") or []:
        if not isinstance(field, dict):
            continue
        excerpt = _normalize_excerpt(field.get("excerpt"))
        evidence_id = _field_evidence_id(field)
        tags = [str(tag) for tag in field.get("epistemic_tags") or [] if str(tag) in allowed_tags]
        if not excerpt or not evidence_id or not tags:
            continue
        fact_types = list(dict.fromkeys(TAG_TO_FACT_TYPE[tag] for tag in tags if tag in TAG_TO_FACT_TYPE))
        if not fact_types:
            continue
        claim = f"Potrivit {short_name}, sursa oficială consemnează: {excerpt}"
        facts.append(
            {
                "fact_types": fact_types,
                "claim": claim,
                "source_excerpt": excerpt,
                "attribution": short_name,
                "epistemic_status": "ATTRIBUTED_FIRST_PARTY_REPORT",
                "evidence_ids": [evidence_id],
            }
        )
    return facts


def _currentness_claim(short_name: str, source_visible_date: date, event: EventTimeResult) -> str:
    visible = source_visible_date.isoformat()
    if event.status == "EXPLICIT_DATETIME":
        return (
            f"{short_name} afișează data materialului {visible}; separat, câmpul de evidență marchează explicit "
            f"evenimentul la data {event.event_date}, ora {event.event_time}."
        )
    if event.status == "EXPLICIT_DATE":
        return (
            f"{short_name} afișează data materialului {visible}; separat, câmpul de evidență marchează explicit "
            f"evenimentul la data {event.event_date}."
        )
    if event.status == "AMBIGUOUS":
        return (
            f"{short_name} afișează data materialului {visible}, dar câmpurile de evidență conțin mai multe momente "
            "posibile ale evenimentului; Core v2 nu selectează unul prin inferență."
        )
    if event.status == "ANOMALOUS_FUTURE":
        return (
            f"{short_name} afișează data materialului {visible}, iar un câmp de evidență indică un moment al "
            "evenimentului ulterior acestei date; Core v2 marchează anomalia și nu folosește acel moment editorial."
        )
    return (
        f"{short_name} afișează data materialului {visible}; momentul evenimentului nu este confirmat separat "
        "printr-o dată cu rol explicit în câmpurile de evidență."
    )


def _epistemic_limit(source: str) -> str:
    if source == "ipj":
        return (
            "Suspiciunile, acuzațiile și măsurile procedurale rămân afirmații atribuite IPJ Vâlcea; "
            "ele nu sunt prezentate drept constatări independente de vinovăție."
        )
    return (
        "Cauzele, numărul persoanelor afectate și valorile numerice rămân informații atribuite ISU Vâlcea; "
        "ele nu sunt prezentate drept determinări independente sau stare operațională live."
    )


def compose_full_shadow_package(source: str, detail: dict[str, Any], base_row: dict[str, Any]) -> dict[str, Any]:
    base_kernel = dict(base_row.get("fact_kernel") or {})
    source_visible_date = _parse_visible_date(detail.get("explicit_date_text"))
    if source_visible_date is None:
        raise ValueError("source_visible_date_missing_after_base_verification")

    profile = SOURCE_PROFILES[source]
    institution = str(profile["institution"])
    short_name = str(profile["short_name"])
    title = str(detail.get("index_title") or detail.get("visible_title") or base_kernel.get("what") or "").strip()
    place = str(base_kernel.get("where") or "").strip()
    source_url = str(base_kernel.get("source_url") or detail.get("detail_url") or "").strip()
    evidence_universe = [str(value) for value in base_kernel.get("evidence_ids") or [] if str(value)]

    event = reconcile_event_time(detail, source_visible_date=source_visible_date)
    material_facts = extract_material_facts(source, detail)
    if not material_facts:
        raise ValueError("no_structured_material_facts")

    source_claim = f"{institution} a publicat pe domeniul său oficial materialul «{title}»."
    place_claim = f"Localizarea identificată explicit în material este {place}."
    currentness_claim = _currentness_claim(short_name, source_visible_date, event)
    limit_claim = _epistemic_limit(source)

    claim_rows: list[tuple[str, list[str]]] = [
        (source_claim, evidence_universe),
        (place_claim, evidence_universe),
        (currentness_claim, list(event.evidence_ids) or evidence_universe),
    ]
    for fact in material_facts:
        claim_rows.append((str(fact["claim"]), list(fact["evidence_ids"])))
    claim_rows.append((limit_claim, evidence_universe))

    claims = tuple(text for text, _evidence in claim_rows)
    when_value: str
    if event.status in {"EXPLICIT_DATE", "EXPLICIT_DATETIME"}:
        when_value = f"eveniment raportat: {event.event_date}"
        if event.event_time:
            when_value += f" {event.event_time}"
        when_value += f"; data vizibilă a materialului: {source_visible_date.isoformat()}"
    else:
        when_value = (
            "momentul evenimentului nu este confirmat separat; "
            f"data vizibilă a materialului: {source_visible_date.isoformat()}"
        )

    kernel = FactKernel(
        what=title,
        who=institution,
        where=place,
        when=when_value,
        why_it_matters=(
            "Materialul conține informații de siguranță publică dintr-o sursă instituțională primară; "
            "Core v2 păstrează separat data publicării, momentul evenimentului și limitele epistemice ale sursei."
        ),
        source=str(base_kernel.get("source") or f"{institution} — material oficial"),
        source_url=source_url,
        claims=claims,
        evidence_ids=tuple(evidence_universe),
    )
    kernel.validate()

    paragraphs = [
        f"{source_claim} {place_claim}",
        currentness_claim,
    ]
    paragraphs.extend(str(fact["claim"]) for fact in material_facts[:5])
    paragraphs.append(limit_claim)
    paragraphs.append(
        "Acest text este compus în shadow mode din fapte legate explicit de evidence IDs. "
        "Nu are autoritate de publicare și nu reutilizează proza legacy ca substitut pentru evidență."
    )
    body = "\n\n".join(paragraphs)

    package = {
        "headline": title,
        "dek": f"{short_name}: material de siguranță publică localizat explicit în {place}.",
        "body": body,
        "writer_id": "shadow_structured_editorial_v2",
        "production_writer_ready": False,
        "currentness": {
            "source_visible_date": source_visible_date.isoformat(),
            "event_time": event.as_dict(),
            "publication_date_is_event_time": False,
        },
        "material_facts": material_facts,
        "claims": [
            {
                "text": text,
                "kernel_claim_index": index,
                "evidence_ids": evidence_ids,
            }
            for index, (text, evidence_ids) in enumerate(claim_rows)
        ],
    }
    integrity = validate_editorial_package(kernel, package)
    if not integrity.pass_gate:
        raise ValueError(f"structured_editorial_integrity_failed:{','.join(integrity.errors)}")

    return {
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
        "material_facts": material_facts,
        "currentness": package["currentness"],
        "integrity": {
            "status": integrity.status,
            "fabricated_claims": integrity.fabricated_claims,
            "bound_claims": integrity.bound_claims,
            "errors": list(integrity.errors),
        },
        "production_writer_ready": False,
    }


def enrich_result(source: str, receipt: dict[str, Any], base_result: dict[str, Any]) -> dict[str, Any]:
    details = {
        _detail_id(detail): detail
        for detail in receipt.get("details") or []
        if isinstance(detail, dict)
    }
    rows: list[dict[str, Any]] = []
    for base_row in base_result.get("rows") or []:
        row = dict(base_row)
        if row.get("state") != "VERIFIED_WRITTEN_SHADOW":
            rows.append(row)
            continue
        detail = details.get(str(row.get("detail_id") or ""))
        if detail is None:
            rows.append({
                "detail_id": row.get("detail_id"),
                "state": "BLOCKED",
                "reason": "verified_detail_missing_for_editorial_composer",
                "publication_authority": "NONE",
            })
            continue
        try:
            row.update(compose_full_shadow_package(source, detail, row))
            row["writer_upgrade"] = "STRUCTURED_MATERIAL_FACTS_AND_CURRENTNESS_V2"
        except Exception as exc:
            row = {
                "detail_id": row.get("detail_id"),
                "state": "BLOCKED",
                "reason": "structured_editorial_composer_failed",
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
                "publication_authority": "NONE",
            }
        rows.append(row)

    result = dict(base_result)
    result["mode"] = "PUBLIC_SAFETY_FULL_EDITORIAL_SHADOW_VERIFICATION"
    result["rows"] = rows
    result["verified_written_shadow_count"] = sum(row.get("state") == "VERIFIED_WRITTEN_SHADOW" for row in rows)
    result["no_story_count"] = sum(row.get("state") == "NO_STORY" for row in rows)
    result["blocked_count"] = sum(row.get("state") == "BLOCKED" for row in rows)
    result["fabricated_claim_count"] = sum(int((row.get("integrity") or {}).get("fabricated_claims") or 0) for row in rows)
    result["structured_editorial_count"] = sum(
        row.get("writer_upgrade") == "STRUCTURED_MATERIAL_FACTS_AND_CURRENTNESS_V2" for row in rows
    )
    result["production_writer_ready"] = False
    result["publication_authority"] = "NONE"
    result["acceptance_ready"] = False
    result["truth_rule"] = (
        "The full shadow writer may use only structured first-party field evidence with explicit evidence IDs. "
        "Visible publication date and event time are separate fields; publication metadata is never silently promoted to incident time."
    )
    return result


def verify_full_receipt(source: str, receipt: dict[str, Any], *, as_of: date | None = None) -> dict[str, Any]:
    base = verify_receipt(source, receipt, as_of=as_of)
    if not base.get("rows"):
        result = dict(base)
        result["mode"] = "PUBLIC_SAFETY_FULL_EDITORIAL_SHADOW_VERIFICATION"
        result["structured_editorial_count"] = 0
        result["production_writer_ready"] = False
        return result
    return enrich_result(source, receipt, base)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Core v2 structured IPJ/ISU editorial composer in shadow mode")
    parser.add_argument("--source", required=True, choices=sorted(SOURCE_PROFILES))
    parser.add_argument("--input")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if bool(args.input) == bool(args.live):
        raise SystemExit("provide exactly one of --input or --live")

    try:
        receipt = _live_receipt(args.source) if args.live else json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = verify_full_receipt(args.source, receipt)
    except Exception as exc:
        result = {
            "schema_version": "1.0",
            "mode": "PUBLIC_SAFETY_FULL_EDITORIAL_SHADOW_VERIFICATION",
            "source_kind": args.source,
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "production_writer_ready": False,
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
        "structured_editorial_count": result.get("structured_editorial_count", 0),
        "no_story_count": result.get("no_story_count", 0),
        "blocked_count": result.get("blocked_count", 0),
        "fabricated_claim_count": result.get("fabricated_claim_count", 0),
        "publication_authority": "NONE",
        "production_writer_ready": False,
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
