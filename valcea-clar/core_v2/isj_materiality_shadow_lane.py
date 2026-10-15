from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any


SENSITIVE_TOPICS = {"EXAMS_RESULTS"}
STATIC_CATEGORY_LABELS = {
    "invatamant primar",
    "admitere in licee",
    "admitere profesional dual",
    "evaluare directori directori adjuncti",
    "posturi vacante",
    "definitivat",
    "inscriere invatamnt primar",
    "inscriere invatamant prescolar",
    "bani de liceu",
}


def _fold(value: Any) -> str:
    text = str(value or "").casefold()
    translate = str.maketrans("ăâîșţț", "aais tt".replace(" ", ""))
    text = text.translate(translate)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _parse_visible_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in (r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](20\d{2})$", r"^(20\d{2})[-/](\d{1,2})[-/](\d{1,2})$"):
        match = re.match(pattern, text)
        if not match:
            continue
        try:
            if pattern.startswith("^(20"):
                y, m, d = map(int, match.groups())
            else:
                d, m, y = map(int, match.groups())
            return date(y, m, d)
        except ValueError:
            return None
    return None


def _years(*values: Any) -> set[int]:
    out: set[int] = set()
    for value in values:
        for raw in re.findall(r"\b20\d{2}\b", str(value or "")):
            out.add(int(raw))
    return out


def _base(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_id": row.get("signal_id"),
        "evidence_id": row.get("evidence_id"),
        "topic_class": row.get("topic_class"),
        "label": row.get("label"),
        "detail_url": row.get("detail_url") or row.get("document_url"),
        "detail_sha256": row.get("detail_sha256"),
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "material_fact_use": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "sensitive_result_projection_allowed": False,
    }


def adjudicate_isj_detail(row: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    base = _base(row)
    if row.get("state") != "DETAIL_EVIDENCE_SHADOW":
        return {**base, "state": "BLOCKED", "reason": "detail_evidence_not_verified"}
    if str(row.get("publication_authority") or "NONE") != "NONE":
        return {**base, "state": "BLOCKED", "reason": "detail_publication_boundary_violation"}
    if row.get("material_fact_use") is True or row.get("fact_kernel_promotion_allowed") is True or row.get("writer_allowed") is True:
        return {**base, "state": "BLOCKED", "reason": "detail_promotion_boundary_violation"}
    if row.get("detail_readback_verified") is not True:
        return {**base, "state": "BLOCKED", "reason": "detail_readback_not_verified"}

    label = str(row.get("label") or "")
    visible_title = str(row.get("visible_title") or "")
    topic = str(row.get("topic_class") or "")
    explicit = _parse_visible_date(row.get("explicit_date_text"))
    years = _years(label, visible_title)
    folded = _fold(label)

    if explicit is not None and explicit > as_of + timedelta(days=180):
        return {**base, "state": "BLOCKED", "reason": "detail_date_implausibly_future", "explicit_date": explicit.isoformat()}

    if explicit is not None and explicit < as_of - timedelta(days=60):
        return {
            **base,
            "state": "NO_STORY",
            "reason": "stale_first_party_detail_page",
            "explicit_date": explicit.isoformat(),
            "currentness": "STALE_VISIBLE_DATE",
        }

    if years and max(years) < as_of.year:
        return {
            **base,
            "state": "NO_STORY",
            "reason": "historical_detail_label",
            "observed_years": sorted(years),
            "currentness": "HISTORICAL_LABEL",
        }

    if topic in SENSITIVE_TOPICS:
        return {
            **base,
            "state": "BLOCKED",
            "reason": "sensitive_exam_result_detail_requires_non_personal_field_level_review",
            "currentness": "NOT_ADJUDICATED",
        }

    if explicit is not None and explicit >= as_of - timedelta(days=60):
        return {
            **base,
            "state": "MATERIAL_DETAIL_CANDIDATE_SHADOW",
            "reason": "recent_first_party_detail_requires_field_level_materiality_extraction",
            "explicit_date": explicit.isoformat(),
            "explicit_date_is_event_time": False,
            "currentness": "RECENT_VISIBLE_DATE_ONLY",
            "field_level_evidence_required": True,
        }

    if as_of.year in years:
        return {
            **base,
            "state": "BLOCKED",
            "reason": "current_year_detail_without_explicit_material_event",
            "observed_years": sorted(years),
            "currentness": "UNPROVEN",
            "embedded_file_or_notice_evidence_required": True,
        }

    if folded in STATIC_CATEGORY_LABELS or not explicit:
        return {
            **base,
            "state": "NO_STORY",
            "reason": "navigation_or_category_detail_not_news_by_itself",
            "currentness": "REFERENCE_ONLY",
        }

    return {**base, "state": "BLOCKED", "reason": "detail_materiality_unresolved", "currentness": "UNPROVEN"}


def adjudicate_report(report: dict[str, Any], *, as_of: date | None = None) -> dict[str, Any]:
    current = as_of or date.today()
    rows = [adjudicate_isj_detail(row, as_of=current) for row in report.get("rows") or [] if isinstance(row, dict)]
    return {
        "schema_version": "1.0",
        "mode": "ISJ_DETAIL_MATERIALITY_SHADOW",
        "source_kind": "isj_valcea",
        "as_of_date": current.isoformat(),
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "material_fact_use": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "detail_row_count": len(rows),
        "material_detail_candidate_shadow_count": sum(row.get("state") == "MATERIAL_DETAIL_CANDIDATE_SHADOW" for row in rows),
        "no_story_count": sum(row.get("state") == "NO_STORY" for row in rows),
        "blocked_count": sum(row.get("state") == "BLOCKED" for row in rows),
        "rows": rows,
        "truth_rule": (
            "A verified ISJ category/detail page is evidence context, not a story. Stale or navigation-only detail pages terminate NO_STORY. "
            "A recent visible date may create only a field-level materiality candidate; it is never event time by inference. "
            "Sensitive exam/result surfaces stay blocked until non-personal field-level review. No output from this gate authorizes FactKernel, writer, site or social publication."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Adjudicate ISJ detail currentness/materiality in Core v2 shadow mode")
    parser.add_argument("--input", required=True)
    parser.add_argument("--as-of")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = json.loads(Path(args.input).read_text(encoding="utf-8"))
    current = date.fromisoformat(args.as_of) if args.as_of else date.today()
    result = adjudicate_report(report, as_of=current)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "detail_row_count": result["detail_row_count"],
        "material_detail_candidate_shadow_count": result["material_detail_candidate_shadow_count"],
        "no_story_count": result["no_story_count"],
        "blocked_count": result["blocked_count"],
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
