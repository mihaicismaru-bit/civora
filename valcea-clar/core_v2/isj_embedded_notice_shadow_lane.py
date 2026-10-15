from __future__ import annotations

import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from isj_detail_shadow_lane import _is_first_party_https, _load_legacy_detail_module

MAX_EMBEDDED_ROWS = 4
MAX_LABELS = 32


class _VisibleChunkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def _fold(value: Any) -> str:
    text = str(value or "").casefold()
    table = str.maketrans({"ă": "a", "â": "a", "î": "i", "ș": "s", "ş": "s", "ț": "t", "ţ": "t"})
    return " ".join(re.sub(r"[^a-z0-9.]+", " ", text.translate(table)).split())


def _visible_parts(body: bytes) -> list[str]:
    parser = _VisibleChunkParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    return parser.parts


def _extract_embedded_file_labels(parts: list[str]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    matcher = re.compile(r"\.(?:pdf|doc|docx|xls|xlsx)\b", re.IGNORECASE)
    for part in parts:
        if not matcher.search(part):
            continue
        normalized = " ".join(part.split()).strip()
        if not normalized or len(normalized) > 240:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        labels.append(normalized)
        if len(labels) >= MAX_LABELS:
            break
    return labels


def _non_authorizing_base(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_id": row.get("signal_id"),
        "evidence_id": row.get("evidence_id"),
        "topic_class": row.get("topic_class"),
        "label": row.get("label"),
        "detail_url": row.get("detail_url"),
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


def _classify_labels(labels: list[str], *, current_year: int) -> dict[str, Any]:
    folded = [_fold(label) for label in labels]
    current_year_token = str(current_year)
    current_year_labels = [
        labels[i] for i, text in enumerate(folded)
        if re.search(rf"\b{re.escape(current_year_token)}\b", text)
    ]
    registration_notice_present = any("inscriere" in text for text in folded)
    vacancy_list_present = any("lista posturi" in text for text in folded)
    calendar_document_present = any("calendar" in text and "concurs" in text for text in folded)
    methodology_present = any("metodolog" in text for text in folded)
    explicit_current_material_catalog = bool(
        current_year_labels and registration_notice_present and (vacancy_list_present or calendar_document_present)
    )
    return {
        "embedded_file_count": len(labels),
        "embedded_file_labels": labels,
        "current_year_embedded_label_count": len(current_year_labels),
        "current_year_embedded_labels": current_year_labels,
        "registration_notice_present": registration_notice_present,
        "vacancy_list_present": vacancy_list_present,
        "calendar_document_present": calendar_document_present,
        "methodology_present": methodology_present,
        "explicit_current_material_catalog": explicit_current_material_catalog,
        "event_time_verified": False,
        "deadline_verified": False,
        "vacancy_count_verified": False,
    }


def resolve_embedded_notice_evidence(
    detail_report: dict[str, Any],
    materiality_report: dict[str, Any],
    *,
    allow_network: bool,
    current_year: int,
    fetcher: Callable[[str], tuple[bytes, str, str]] | None = None,
) -> dict[str, Any]:
    if str(detail_report.get("publication_authority") or "NONE") != "NONE":
        raise ValueError("detail_publication_boundary_violation")
    if str(materiality_report.get("publication_authority") or "NONE") != "NONE":
        raise ValueError("materiality_publication_boundary_violation")
    if materiality_report.get("fact_kernel_promotion_allowed") is True or materiality_report.get("writer_allowed") is True:
        raise ValueError("materiality_promotion_boundary_violation")

    detail_by_evidence = {
        str(row.get("evidence_id")): row
        for row in detail_report.get("rows") or []
        if isinstance(row, dict) and row.get("evidence_id")
    }
    candidates = [
        row for row in materiality_report.get("rows") or []
        if isinstance(row, dict)
        and row.get("state") == "BLOCKED"
        and row.get("embedded_file_or_notice_evidence_required") is True
    ][:MAX_EMBEDDED_ROWS]

    rows: list[dict[str, Any]] = []
    loader_ready = False
    for row in candidates:
        base = _non_authorizing_base(row)
        evidence_id = str(row.get("evidence_id") or "")
        detail = detail_by_evidence.get(evidence_id)
        if not detail or detail.get("state") != "DETAIL_EVIDENCE_SHADOW" or detail.get("detail_readback_verified") is not True:
            rows.append({**base, "state": "BLOCKED", "reason": "verified_detail_evidence_missing"})
            continue
        target = str(detail.get("detail_url") or row.get("detail_url") or "")
        if not _is_first_party_https(target):
            rows.append({**base, "state": "BLOCKED", "reason": "embedded_catalog_parent_not_first_party_https", "network_fetch_attempted": False})
            continue
        if not allow_network:
            rows.append({**base, "state": "BLOCKED", "reason": "network_read_not_enabled", "network_fetch_attempted": False})
            continue
        if fetcher is None and not loader_ready:
            legacy = _load_legacy_detail_module()
            fetcher = legacy._fetch_detail
            loader_ready = True
        assert fetcher is not None
        try:
            body, final_url, content_type = fetcher(target)
            if content_type not in {"text/html", "text/plain"}:
                rows.append({**base, "state": "BLOCKED", "reason": "embedded_catalog_parent_not_text", "network_fetch_attempted": True, "content_type": content_type})
                continue
            observed_sha = hashlib.sha256(body).hexdigest()
            expected_sha = str(detail.get("detail_sha256") or "")
            parts = _visible_parts(body)
            visible_folded = _fold(" ".join(parts))
            identity_anchor = _fold(row.get("label") or detail.get("visible_title"))
            if not identity_anchor or identity_anchor not in visible_folded:
                rows.append({
                    **base,
                    "state": "BLOCKED",
                    "reason": "detail_identity_anchor_missing_after_refetch",
                    "network_fetch_attempted": True,
                    "prior_detail_sha256": expected_sha or None,
                    "observed_detail_sha256": observed_sha,
                    "parent_bytes_changed_since_detail_gate": bool(expected_sha and observed_sha != expected_sha),
                    "parent_identity_reverified": False,
                })
                continue
            labels = _extract_embedded_file_labels(parts)
            fields = _classify_labels(labels, current_year=current_year)
            parent_meta = {
                "network_fetch_attempted": True,
                "detail_url": final_url,
                "prior_detail_sha256": expected_sha or None,
                "observed_detail_sha256": observed_sha,
                "parent_bytes_changed_since_detail_gate": bool(expected_sha and observed_sha != expected_sha),
                "parent_identity_reverified": True,
                "parent_identity_anchor": row.get("label") or detail.get("visible_title"),
                "embedded_parent_evidence_id": f"isj-embedded-parent-{observed_sha[:24]}",
            }
            if not labels:
                rows.append({**base, **fields, **parent_meta, "state": "BLOCKED", "reason": "no_embedded_document_labels_observed"})
                continue
            state = "EMBEDDED_NOTICE_EVIDENCE_SHADOW" if fields["explicit_current_material_catalog"] else "BLOCKED"
            reason = "current_year_embedded_notice_catalog_verified_non_authorizing" if state == "EMBEDDED_NOTICE_EVIDENCE_SHADOW" else "embedded_catalog_present_but_current_materiality_unproven"
            rows.append({
                **base,
                **fields,
                **parent_meta,
                "state": state,
                "reason": reason,
                "embedded_targets_fetched": False,
                "embedded_document_content_verified": False,
            })
        except Exception as exc:
            rows.append({**base, "state": "BLOCKED", "reason": "embedded_catalog_parent_fetch_failed", "network_fetch_attempted": True, "error_type": type(exc).__name__, "error": str(exc)[:400]})

    return {
        "schema_version": "1.1",
        "mode": "ISJ_EMBEDDED_NOTICE_EVIDENCE_SHADOW",
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "material_fact_use": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "network_read_enabled": allow_network,
        "candidate_count": len(candidates),
        "embedded_notice_evidence_shadow_count": sum(row.get("state") == "EMBEDDED_NOTICE_EVIDENCE_SHADOW" for row in rows),
        "blocked_count": sum(row.get("state") == "BLOCKED" for row in rows),
        "rows": rows,
        "truth_rule": "Dynamic first-party page bytes may change between bounded reads, so raw-byte drift is recorded rather than treated as proof of semantic drift. The current read must independently preserve the page identity anchor and visibly list the embedded document labels. This gate never fetches embedded document targets and never infers their contents, deadlines, vacancy counts or event times from filenames. Even a current-year registration/calendar/post-list catalog remains non-authorizing until document content and field-level facts are independently verified.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve bounded embedded notice labels from verified first-party ISJ detail pages")
    parser.add_argument("--details", required=True)
    parser.add_argument("--materiality", required=True)
    parser.add_argument("--year", type=int)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    details = json.loads(Path(args.details).read_text(encoding="utf-8"))
    materiality = json.loads(Path(args.materiality).read_text(encoding="utf-8"))
    from datetime import date
    result = resolve_embedded_notice_evidence(details, materiality, allow_network=args.live, current_year=args.year or date.today().year)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_count": result["candidate_count"], "embedded_notice_evidence_shadow_count": result["embedded_notice_evidence_shadow_count"], "blocked_count": result["blocked_count"], "publication_authority": "NONE", "acceptance_ready": False}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
