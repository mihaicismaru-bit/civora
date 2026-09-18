from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any


MATERIAL_REFERENCE_CLASSES = {
    "PRESCHOOL_ENROLMENT_NOTICE",
    "SECONDARY_ADMISSION_NOTICE",
    "TEACHER_EXAM_NOTICE",
    "SCHOOL_MANAGEMENT_NOTICE",
    "MERIT_GRANT_NOTICE",
    "SCHOOL_CALENDAR_NOTICE",
    "SUMMER_PRESCHOOL_SERVICE_REFERENCE",
}

SENSITIVE_CLASSES = {"HOLD_SENSITIVE_EDUCATION_RESULT_REFERENCE"}

STATIC_REFERENCE_TERMS = (
    "cerere",
    "metodologie",
    "ghid",
    "brosura",
    "broșură",
    "ordin",
    "model",
    "declaratie",
    "declarație",
    "lista documentelor",
    "date de contact",
    "plan scolarizare",
    "plan școlarizare",
    "proiect plan",
    "procedura",
    "procedură",
)


def _parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _school_year_for(day: date) -> str:
    start = day.year if day.month >= 9 else day.year - 1
    return f"{start}-{start + 1}"


def _fold(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _static_reference(label: str) -> bool:
    folded = _fold(label)
    return any(term in folded for term in STATIC_REFERENCE_TERMS)


def _signal_id(signal: dict[str, Any]) -> str:
    seed = "|".join(
        [
            str(signal.get("document_url_sha256") or ""),
            str(signal.get("document_url") or ""),
            str(signal.get("source_url") or ""),
            str(signal.get("signal_class") or ""),
            str(signal.get("label") or signal.get("evidence_excerpt") or ""),
        ]
    )
    return "isj-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def adjudicate_isj_signal(signal: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    signal_class = str(signal.get("signal_class") or "HOLD")
    label = str(signal.get("label") or "").strip()
    hold_reason = str(signal.get("hold_reason") or "").strip() or None
    school_year = str(signal.get("school_year") or "").strip() or None
    explicit = _parse_iso_date(signal.get("explicit_date"))
    expected_school_year = _school_year_for(as_of)

    base = {
        "signal_id": _signal_id(signal),
        "source_kind": "isj_valcea",
        "signal_class": signal_class,
        "label": label or None,
        "source_url": str(signal.get("source_url") or "").strip(),
        "document_url": str(signal.get("document_url") or "").strip() or None,
        "document_url_sha256": signal.get("document_url_sha256"),
        "school_year": school_year,
        "explicit_date": explicit.isoformat() if explicit else None,
        "explicit_date_semantics": signal.get("explicit_date_semantics"),
        "publication_authority": "NONE",
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "person_fact_extraction_allowed": False,
        "sensitive_result_projection_allowed": False,
    }

    boundary_bools = (
        "current_status_claim_allowed",
        "freshness_claim_allowed",
        "person_fact_extraction_allowed",
        "sensitive_result_projection_allowed",
        "document_body_fetch_allowed",
        "inferred_photo_rights_allowed",
        "persistence_allowed",
        "fact_kernel_promotion_allowed",
        "writer_allowed",
        "public_projection_allowed",
    )
    if str(signal.get("publication_authority") or "NONE") != "NONE" or any(signal.get(key) is True for key in boundary_bools):
        return {**base, "state": "BLOCKED", "reason": "source_adapter_publication_boundary_violation"}

    if signal_class in SENSITIVE_CLASSES:
        return {
            **base,
            "state": "BLOCKED",
            "reason": "sensitive_or_person_level_education_result_requires_manual_review",
            "currentness": "NOT_ADJUDICATED",
        }

    if signal_class == "HOLD":
        if hold_reason == "NO_RELEVANT_EXPLICIT_NOTICE_LABELS":
            return {**base, "state": "NO_STORY", "reason": "no_relevant_explicit_notice_labels"}
        return {
            **base,
            "state": "BLOCKED",
            "reason": hold_reason or "source_signal_held_fail_closed",
            "currentness": "UNPROVEN",
        }

    if hold_reason:
        return {
            **base,
            "state": "BLOCKED",
            "reason": "official_document_reference_not_verified",
            "source_hold_reason": hold_reason,
            "currentness": "UNPROVEN",
        }

    if not base["document_url"]:
        return {
            **base,
            "state": "BLOCKED",
            "reason": "official_document_url_missing",
            "currentness": "UNPROVEN",
        }

    if _static_reference(label):
        return {
            **base,
            "state": "NO_STORY",
            "reason": "static_education_reference_not_news_by_itself",
            "currentness": "REFERENCE_ONLY",
        }

    if school_year and school_year != expected_school_year:
        return {
            **base,
            "state": "NO_STORY",
            "reason": "school_year_not_current",
            "currentness": "STALE_SCHOOL_YEAR",
            "expected_school_year": expected_school_year,
        }

    if signal_class == "SUMMER_PRESCHOOL_SERVICE_REFERENCE" and as_of.month >= 9:
        return {
            **base,
            "state": "NO_STORY",
            "reason": "seasonal_summer_service_reference_expired",
            "currentness": "SEASONALLY_EXPIRED",
        }

    if signal_class not in MATERIAL_REFERENCE_CLASSES:
        return {
            **base,
            "state": "NO_STORY",
            "reason": "unsupported_education_reference_class",
            "currentness": "REFERENCE_ONLY",
        }

    if explicit is not None:
        if explicit < as_of - timedelta(days=45):
            return {
                **base,
                "state": "NO_STORY",
                "reason": "explicit_label_date_stale_for_news",
                "currentness": "STALE_LABEL_DATE",
            }
        if explicit > as_of + timedelta(days=180):
            return {
                **base,
                "state": "BLOCKED",
                "reason": "explicit_label_date_too_far_for_currentness",
                "currentness": "UNPROVEN",
            }
        return {
            **base,
            "state": "MATERIAL_SIGNAL_SHADOW",
            "reason": "material_education_reference_with_bounded_label_date",
            "currentness": "RECENT_OR_UPCOMING_LABEL_DATE_ONLY",
            "document_body_required_for_fact_kernel": True,
            "label_date_is_event_time": False,
        }

    if school_year == expected_school_year:
        return {
            **base,
            "state": "BLOCKED",
            "reason": "current_school_year_reference_without_explicit_currentness",
            "currentness": "UNPROVEN",
            "expected_school_year": expected_school_year,
        }

    return {
        **base,
        "state": "BLOCKED",
        "reason": "education_reference_without_currentness_proof",
        "currentness": "UNPROVEN",
        "expected_school_year": expected_school_year,
    }


def verify_isj_signals(signals: list[dict[str, Any]], *, as_of: date | None = None, source_errors: list[dict[str, str]] | None = None) -> dict[str, Any]:
    current_date = as_of or date.today()
    rows = [adjudicate_isj_signal(signal, as_of=current_date) for signal in signals if isinstance(signal, dict)]
    return {
        "schema_version": "1.0",
        "mode": "ISJ_CURRENT_MATERIAL_SIGNAL_SHADOW",
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "as_of_date": current_date.isoformat(),
        "signal_count": len(rows),
        "material_signal_shadow_count": sum(row.get("state") == "MATERIAL_SIGNAL_SHADOW" for row in rows),
        "no_story_count": sum(row.get("state") == "NO_STORY" for row in rows),
        "blocked_count": sum(row.get("state") == "BLOCKED" for row in rows),
        "sensitive_blocked_count": sum(row.get("reason") == "sensitive_or_person_level_education_result_requires_manual_review" for row in rows),
        "source_errors": source_errors or [],
        "rows": rows,
        "truth_rule": (
            "ISJ labels and document references are discovery evidence, not articles. Sensitive/person-level results never auto-project. "
            "A school-year label does not prove operational freshness, an explicit label date is not event time, and no row may reach "
            "FactKernel or writer without bounded first-party document-body evidence plus a separate materiality adjudication."
        ),
    }


def _load_isj_adapter():
    path = Path(__file__).resolve().parents[1] / "scripts" / "isj_valcea_education_signal_adapter.py"
    module_name = "core_v2_isj_valcea_education_signal_adapter"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("isj_adapter_load_failed")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves postponed annotations through sys.modules during class creation.
    # Register the isolated legacy adapter before exec_module; otherwise Python 3.13 can
    # fail inside dataclasses with a None module namespace.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _live_signals() -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    adapter = _load_isj_adapter()
    signals: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for path in adapter.SURFACES:
        url = f"https://{adapter.CANONICAL_HOST}{path}"
        try:
            rows = adapter.run(url)
        except Exception as exc:
            errors.append({"source_url": url, "error_type": type(exc).__name__, "error": str(exc)[:300]})
            continue
        for item in rows:
            row = asdict(item)
            identity = (
                str(row.get("signal_class") or ""),
                str(row.get("document_url_sha256") or row.get("document_url") or ""),
                str(row.get("label") or row.get("evidence_excerpt") or ""),
            )
            if identity in seen:
                continue
            seen.add(identity)
            signals.append(row)
    return signals, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded ISJ education currentness/materiality gate in Core v2 shadow mode")
    parser.add_argument("--input")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--as-of")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if bool(args.input) == bool(args.live):
        raise SystemExit("provide exactly one of --input or --live")

    current_date = date.fromisoformat(args.as_of) if args.as_of else date.today()
    try:
        if args.live:
            signals, source_errors = _live_signals()
        else:
            loaded = json.loads(Path(args.input).read_text(encoding="utf-8"))
            if not isinstance(loaded, list):
                raise ValueError("ISJ input must be a list of signals")
            signals, source_errors = loaded, []
        result = verify_isj_signals(signals, as_of=current_date, source_errors=source_errors)
        if not signals and source_errors:
            result["status"] = "BLOCKED_SOURCE_UNAVAILABLE"
    except Exception as exc:
        result = {
            "schema_version": "1.0",
            "mode": "ISJ_CURRENT_MATERIAL_SIGNAL_SHADOW",
            "source_kind": "isj_valcea",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "production_writer_ready": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "status": "BLOCKED_SOURCE_UNAVAILABLE",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "rows": [],
        }

    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result.get("status", "PASS_SHADOW"),
        "signal_count": result.get("signal_count", 0),
        "material_signal_shadow_count": result.get("material_signal_shadow_count", 0),
        "no_story_count": result.get("no_story_count", 0),
        "blocked_count": result.get("blocked_count", 0),
        "source_error_count": len(result.get("source_errors") or []),
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
