from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from isj_detail_shadow_lane import _is_first_party_https, _load_legacy_detail_module
from isj_embedded_notice_shadow_lane import _fold

MAX_ROWS = 4
MAX_LABELS = 32
MAX_TARGETS = 64
MAX_EVENT_GAP = 8
_DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx")
_GOOGLE_RESOURCE_ID = re.compile(r"^[A-Za-z0-9_-]{10,}$")


class _ResourceEventParser(HTMLParser):
    """Capture visible text and URL-bearing HTML attributes in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.event_index = 0
        self.text_events: list[dict[str, Any]] = []
        self.url_events: list[dict[str, Any]] = []

    def _advance(self) -> int:
        self.event_index += 1
        return self.event_index

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        idx = self._advance()
        if name in {"script", "style", "noscript", "svg"}:
            self.skip += 1
            return
        for attr_name, raw_value in attrs:
            if not raw_value:
                continue
            attr = (attr_name or "").lower()
            if not (
                attr in {"href", "src", "data-url", "data-href", "data-src"}
                or attr.startswith("data-")
                or "url" in attr
                or "href" in attr
                or "src" in attr
            ):
                continue
            value = html.unescape(str(raw_value))
            for match in re.finditer(r"https://[^\s\"'<>]+", value, flags=re.IGNORECASE):
                candidate = match.group(0).rstrip("),.;]")
                self.url_events.append(
                    {"event_index": idx, "tag": name, "attribute": attr, "url": candidate}
                )
                if len(self.url_events) >= MAX_TARGETS:
                    return

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        self._advance()
        if name in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        text = " ".join(data.split()).strip()
        if not text:
            return
        idx = self._advance()
        self.text_events.append({"event_index": idx, "text": text})


def _resource_id_from_google_url(url: str) -> tuple[str | None, str | None]:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    segments = [segment for segment in parts.path.split("/") if segment]
    if host == "drive.google.com":
        if len(segments) >= 3 and segments[0] == "file" and segments[1] == "d":
            resource_id = segments[2]
            if _GOOGLE_RESOURCE_ID.fullmatch(resource_id):
                return "GOOGLE_DRIVE_FILE", resource_id
        query_id = (parse_qs(parts.query).get("id") or [None])[0]
        if query_id and _GOOGLE_RESOURCE_ID.fullmatch(query_id):
            return "GOOGLE_DRIVE_FILE", query_id
    if host == "docs.google.com" and len(segments) >= 3 and segments[1] == "d":
        kind = segments[0]
        resource_id = segments[2]
        if kind in {"document", "spreadsheets", "presentation"} and _GOOGLE_RESOURCE_ID.fullmatch(resource_id):
            return f"GOOGLE_{kind.upper()}", resource_id
    if host == "drive.usercontent.google.com":
        query_id = (parse_qs(parts.query).get("id") or [None])[0]
        if query_id and _GOOGLE_RESOURCE_ID.fullmatch(query_id):
            return "GOOGLE_DRIVE_CONTENT", query_id
    return None, None


def _target_identity(url: str) -> dict[str, Any] | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password or parts.port not in (None, 443):
        return None
    if host in {"isjvalcea.ro", "www.isjvalcea.ro"} and parts.path.lower().endswith(_DOCUMENT_EXTENSIONS):
        return {
            "target_url": url,
            "target_host": host,
            "target_class": "FIRST_PARTY_DOCUMENT",
            "resource_id": hashlib.sha256(url.encode("utf-8")).hexdigest()[:24],
            "target_identity_verified": True,
            "future_content_fetch_eligible": True,
        }
    target_class, resource_id = _resource_id_from_google_url(url)
    if target_class and resource_id:
        return {
            "target_url": url,
            "target_host": host,
            "target_class": target_class,
            "resource_id": resource_id,
            "target_identity_verified": True,
            "future_content_fetch_eligible": True,
        }
    return None


def _parse_resource_events(body: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parser = _ResourceEventParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    identities: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in parser.url_events:
        identity = _target_identity(str(event.get("url") or ""))
        if not identity:
            continue
        key = (str(identity["target_class"]), str(identity["resource_id"]))
        if key in seen:
            continue
        seen.add(key)
        identities.append({**event, **identity})
    return parser.text_events, identities


def _label_event_indices(label: str, text_events: list[dict[str, Any]]) -> list[int]:
    needle = _fold(label)
    if not needle:
        return []
    indices: list[int] = []
    for event in text_events:
        haystack = _fold(event.get("text"))
        if needle == haystack or needle in haystack or haystack in needle:
            indices.append(int(event["event_index"]))
    return indices


def _bind_label_target(
    label: str,
    text_events: list[dict[str, Any]],
    targets: list[dict[str, Any]],
) -> dict[str, Any]:
    label_indices = _label_event_indices(label, text_events)
    if not label_indices:
        return {
            "label": label,
            "state": "BLOCKED",
            "reason": "embedded_label_not_located_in_current_parent_html",
            "target_identity_verified": False,
        }
    nearby: list[dict[str, Any]] = []
    for target in targets:
        distance = min(abs(int(target["event_index"]) - idx) for idx in label_indices)
        if distance <= MAX_EVENT_GAP:
            nearby.append({**target, "event_distance": distance})
    distinct: dict[tuple[str, str], dict[str, Any]] = {}
    for target in sorted(nearby, key=lambda item: (int(item["event_distance"]), str(item["target_class"]), str(item["resource_id"]))):
        distinct.setdefault((str(target["target_class"]), str(target["resource_id"])), target)
    candidates = list(distinct.values())
    if not candidates:
        return {
            "label": label,
            "state": "BLOCKED",
            "reason": "no_trustworthy_document_target_near_label",
            "target_identity_verified": False,
        }
    min_distance = min(int(item["event_distance"]) for item in candidates)
    nearest = [item for item in candidates if int(item["event_distance"]) == min_distance]
    if len(nearest) != 1:
        return {
            "label": label,
            "state": "BLOCKED",
            "reason": "ambiguous_document_target_near_label",
            "target_identity_verified": False,
            "candidate_target_count": len(candidates),
            "nearest_target_count": len(nearest),
        }
    target = nearest[0]
    return {
        "label": label,
        "state": "TARGET_IDENTITY_BOUND_SHADOW",
        "reason": "official_parent_html_uniquely_binds_visible_label_to_document_target_identity",
        "target_identity_verified": True,
        "target_url": target["target_url"],
        "target_host": target["target_host"],
        "target_class": target["target_class"],
        "resource_id": target["resource_id"],
        "event_distance": target["event_distance"],
        "future_content_fetch_eligible": bool(target["future_content_fetch_eligible"]),
        "discovery_method": "first_party_parent_html_nearest_document_target",
        "content_fetched": False,
        "content_verified": False,
        "material_fact_use": False,
    }


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


def resolve_embedded_target_identities(
    embedded_report: dict[str, Any],
    *,
    allow_network: bool,
    current_year: int,
    fetcher: Callable[[str], tuple[bytes, str, str]] | None = None,
) -> dict[str, Any]:
    if str(embedded_report.get("publication_authority") or "NONE") != "NONE":
        raise ValueError("embedded_publication_boundary_violation")
    if embedded_report.get("fact_kernel_promotion_allowed") is True or embedded_report.get("writer_allowed") is True:
        raise ValueError("embedded_promotion_boundary_violation")

    candidates = [
        row for row in embedded_report.get("rows") or []
        if isinstance(row, dict) and row.get("state") == "EMBEDDED_NOTICE_EVIDENCE_SHADOW"
    ][:MAX_ROWS]
    rows: list[dict[str, Any]] = []
    loader_ready = False
    for row in candidates:
        base = _non_authorizing_base(row)
        target = str(row.get("detail_url") or "")
        if not _is_first_party_https(target):
            rows.append({**base, "state": "BLOCKED", "reason": "parent_not_first_party_https", "network_fetch_attempted": False})
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
                rows.append({**base, "state": "BLOCKED", "reason": "parent_not_text", "network_fetch_attempted": True, "content_type": content_type})
                continue
            text_events, target_identities = _parse_resource_events(body)
            labels = [str(v) for v in (row.get("embedded_file_labels") or []) if str(v).strip()][:MAX_LABELS]
            current_year_labels = {
                str(v) for v in (row.get("current_year_embedded_labels") or []) if str(v).strip()
            }
            bindings = [_bind_label_target(label, text_events, target_identities) for label in labels]
            for binding in bindings:
                binding["current_year_label"] = binding["label"] in current_year_labels or str(current_year) in _fold(binding["label"])
            bound = [binding for binding in bindings if binding.get("state") == "TARGET_IDENTITY_BOUND_SHADOW"]
            bound_current = [binding for binding in bound if binding.get("current_year_label") is True]
            blocked = [binding for binding in bindings if binding.get("state") == "BLOCKED"]
            state = "EMBEDDED_TARGET_IDENTITY_SHADOW" if bound_current else "BLOCKED"
            reason = (
                "current_year_document_target_identity_bound_non_authorizing"
                if state == "EMBEDDED_TARGET_IDENTITY_SHADOW"
                else "no_current_year_document_target_identity_bound"
            )
            rows.append({
                **base,
                "state": state,
                "reason": reason,
                "network_fetch_attempted": True,
                "parent_final_url": final_url,
                "parent_content_type": content_type,
                "parent_sha256": hashlib.sha256(body).hexdigest(),
                "document_target_candidate_count": len(target_identities),
                "label_count": len(labels),
                "target_identity_bound_count": len(bound),
                "current_year_target_identity_bound_count": len(bound_current),
                "blocked_label_count": len(blocked),
                "bindings": bindings,
                "embedded_targets_fetched": False,
                "embedded_document_content_verified": False,
            })
        except Exception as exc:
            rows.append({
                **base,
                "state": "BLOCKED",
                "reason": "parent_fetch_or_target_parse_failed",
                "network_fetch_attempted": True,
                "error_type": type(exc).__name__,
                "error": str(exc)[:400],
            })

    return {
        "schema_version": "1.0",
        "mode": "ISJ_EMBEDDED_TARGET_IDENTITY_SHADOW",
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
        "embedded_target_identity_shadow_count": sum(row.get("state") == "EMBEDDED_TARGET_IDENTITY_SHADOW" for row in rows),
        "blocked_count": sum(row.get("state") == "BLOCKED" for row in rows),
        "rows": rows,
        "truth_rule": "A visible filename is not a document. This gate only binds a filename to a unique trustworthy document target identity when that target is observed in the same fresh first-party parent HTML within a bounded document-order neighborhood. It never fetches the embedded document and never infers deadlines, vacancies, event times or facts from filenames or target URLs.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind ISJ embedded document labels to auditable target identities without fetching document contents")
    parser.add_argument("--embedded", required=True)
    parser.add_argument("--year", type=int)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    embedded = json.loads(Path(args.embedded).read_text(encoding="utf-8"))
    from datetime import date
    result = resolve_embedded_target_identities(
        embedded,
        allow_network=args.live,
        current_year=args.year or date.today().year,
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidate_count": result["candidate_count"],
        "embedded_target_identity_shadow_count": result["embedded_target_identity_shadow_count"],
        "blocked_count": result["blocked_count"],
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
