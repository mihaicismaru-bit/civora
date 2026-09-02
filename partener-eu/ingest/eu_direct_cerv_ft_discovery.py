#!/usr/bin/env python3
"""Bounded official Funding & Tenders identity discovery for CERV.

This lane is market-intelligence only. It queries the official EC Search/Facet
APIs for CERV identities, proves programme membership from Facet evidence, and
produces a deterministic exact-recheck pointer when one safe identity exists.
It never authorizes OPEN/CLOSED status, deadline, budget, eligibility,
publication, distribution, or alerts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

import funding_tenders_fetch as ft

SCHEMA = "PARTENER_EU_CERV_FT_DISCOVERY_V1"
PARSER_VERSION = "EU_DIRECT_CERV_FT_DISCOVERY_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "CERV"
AUTHORITY_CLASS = "EU_COMMISSION_FUNDING_TENDERS"
DISCOVERED_STATE = "OFFICIAL_STRUCTURED_CERV_IDENTITY_DISCOVERED_NON_AUTHORIZING"
OMITTED_STATE = "OFFICIAL_STRUCTURED_QUERY_NO_SAFE_CERV_IDENTITY_NON_AUTHORIZING"
REF_RE = re.compile(r"^CERV-[A-Z0-9]+(?:-[A-Z0-9]+)+$", re.IGNORECASE)
DIRECT_TYPES = {"1", "2"}
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
    "canonical_corpus_mutation",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def validate_reference(reference: str) -> str:
    value = str(reference or "").strip().upper()
    if not REF_RE.fullmatch(value):
        raise ValueError(f"not an explicit CERV reference: {reference!r}")
    return value


def _scalar(value: Any) -> str | None:
    return ft._scalar(value)


def _record_type(record: Mapping[str, Any]) -> str | None:
    return _scalar(record.get("type"))


def _record_programme_reference(record: Mapping[str, Any]) -> str | None:
    for key in ("frameworkProgramme", "programme", "programmeReference"):
        value = _scalar(record.get(key))
        if value:
            return value
    return None


def _first_scalar(record: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _scalar(record.get(key))
        if value:
            return value
    return None


def _framework_programme_map(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("official Facet response must be an object")
    facets = payload.get("facets")
    if not isinstance(facets, list):
        raise ValueError("official Facet response is missing facets")
    matches = [f for f in facets if isinstance(f, dict) and f.get("name") == "frameworkProgramme"]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one frameworkProgramme facet, found {len(matches)}")
    values = matches[0].get("values")
    if not isinstance(values, list) or not values:
        raise ValueError("frameworkProgramme facet has no values")
    result: dict[str, str] = {}
    for row in values:
        if not isinstance(row, dict):
            continue
        code = _scalar(row.get("rawValue"))
        label = _scalar(row.get("value"))
        if not code or not label or label == code or label.isdigit():
            continue
        previous = result.get(code)
        if previous and previous != label:
            raise ValueError(f"ambiguous official programme label for {code}: {previous!r} vs {label!r}")
        result[code] = label
    if not result:
        raise ValueError("frameworkProgramme facet yielded no human-readable labels")
    return result


def _is_cerv_label(label: str) -> bool:
    token = re.sub(r"[^a-z0-9]+", " ", str(label).casefold()).strip()
    return (
        "citizens equality rights and values" in token
        or token == "cerv"
        or token.endswith(" cerv")
    )


def discovery_query() -> dict[str, Any]:
    return {
        "bool": {
            "must": [
                {"terms": {"type": list(ft.CALL_TYPES)}},
                {"term": {"programmePeriod": "2021 - 2027"}},
            ]
        }
    }


def _priority(status_label: str | None) -> int:
    token = str(status_label or "").strip().casefold()
    if token == "open":
        return 0
    if token in {"forthcoming", "upcoming"}:
        return 1
    return 2


def collect(
    *,
    run_id: str,
    fetched_at: str | None = None,
    output_dir: pathlib.Path | None = None,
    query_text: str = "CERV-2026",
    page_size: int = 25,
    post_func: Callable[..., tuple[Any, bytes, dict[str, Any]]] = ft._safe_json_post,
) -> dict[str, Any]:
    fetched_at = fetched_at or utc_now()
    if page_size < 1 or page_size > 25:
        raise ValueError("page_size must be between 1 and 25")
    parts = {"query": discovery_query(), "languages": ["en"]}
    search_payload, search_raw, search_receipt = post_func(
        ft.SEARCH_ENDPOINT,
        text=query_text,
        page_size=page_size,
        page_number=1,
        parts=parts,
    )
    facet_payload, facet_raw, facet_receipt = post_func(
        ft.FACET_ENDPOINT,
        text=query_text,
        page_size=page_size,
        page_number=1,
        parts=parts,
    )
    labels = _framework_programme_map(facet_payload)
    rows = ft.flatten_search_payload(search_payload)
    direct_rows: list[dict[str, Any]] = []
    linked_type8 = 0
    rejected_non_cerv = 0
    for row in rows:
        identifier_raw = ft._record_identifier(row)
        if not identifier_raw:
            continue
        try:
            identifier = validate_reference(identifier_raw)
        except ValueError:
            continue
        record_type = _record_type(row)
        if record_type == "8":
            linked_type8 += 1
            continue
        if record_type not in DIRECT_TYPES:
            continue
        programme_ref = _record_programme_reference(row)
        programme_label = labels.get(programme_ref or "")
        if not programme_label or not _is_cerv_label(programme_label):
            rejected_non_cerv += 1
            continue
        status_code = ft._record_status_code(row)
        status_label = ft.resolve_reference_label([facet_payload], status_code or "") if status_code else None
        semantics = {
            "identifier": identifier,
            "record_type": record_type,
            "programme_reference": programme_ref,
            "programme_label": programme_label,
            "call_identifier": _first_scalar(row, "callIdentifier", "callId", "callReference"),
            "status_code": status_code,
            "status_label_candidate": status_label,
            "title": _first_scalar(row, "title", "topicTitle", "name"),
            "authority_url_candidate": ft.topic_url(identifier),
        }
        direct_rows.append({
            **semantics,
            "semantic_fingerprint": sha256_json(semantics),
            "authority_url_verified": False,
            "market_intelligence_only": True,
            "material_fact_use": False,
            "open_call_authorized": False,
        })

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in direct_rows:
        grouped.setdefault(row["identifier"], []).append(row)
    candidates: list[dict[str, Any]] = []
    conflict_identifiers: list[str] = []
    duplicate_rows_removed = 0
    for identifier, group in sorted(grouped.items()):
        variants: dict[str, dict[str, Any]] = {}
        for row in group:
            variants.setdefault(row["semantic_fingerprint"], row)
        duplicate_rows_removed += max(0, len(group) - len(variants))
        if len(variants) != 1:
            conflict_identifiers.append(identifier)
            continue
        candidates.append(next(iter(variants.values())))
    candidates.sort(key=lambda row: (_priority(row.get("status_label_candidate")), row["identifier"]))
    selected = candidates[0] if candidates else None
    observation_state = DISCOVERED_STATE if selected else OMITTED_STATE

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": observation_state,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "query_text": query_text,
        "page_size": page_size,
        "search_receipt": dict(search_receipt),
        "facet_receipt": dict(facet_receipt),
        "search_raw_sha256": sha256_bytes(search_raw),
        "facet_raw_sha256": sha256_bytes(facet_raw),
        "raw_search_record_count": len(rows),
        "cerv_direct_record_count": len(direct_rows),
        "linked_type8_count": linked_type8,
        "rejected_non_cerv_count": rejected_non_cerv,
        "duplicate_rows_removed": duplicate_rows_removed,
        "conflict_identifiers": conflict_identifiers,
        "candidates": candidates,
        "selected_candidate": selected,
        "selected_reference": selected["identifier"] if selected else None,
        "selected_authority_url_candidate": selected["authority_url_candidate"] if selected else None,
        "exact_current_recheck_required": bool(selected),
        "bounded_discovery_absence_is_material_fact": False,
        "closure_inference_authorized": False,
        "market_intelligence_only": True,
        "missing_for_open_call_confirmation": [
            "fresh exact current structured F&T identity/status readback",
            "current official Funding & Tenders topic endpoint verification",
            "exact semantic reconciliation",
            "field-scoped material admission",
        ],
        "publication_effect": "NONE",
    }
    for key in MATERIAL_FLAGS:
        receipt[key] = False
    receipt["semantic_fingerprint"] = sha256_json({
        "query_text": query_text,
        "candidates": candidates,
        "selected_reference": receipt["selected_reference"],
        "conflict_identifiers": conflict_identifiers,
        "source_hashes": [receipt["search_raw_sha256"], receipt["facet_raw_sha256"]],
    })
    validate_receipt(receipt)
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "ft-cerv-discovery-search-response.json").write_bytes(search_raw)
        (output_dir / "ft-cerv-discovery-facet-response.json").write_bytes(facet_raw)
        (output_dir / "ft-cerv-discovery.json").write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    return receipt


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError("CERV F&T discovery schema/parser drift")
    if receipt.get("source_family") != SOURCE_FAMILY or receipt.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("CERV F&T discovery family drift")
    if receipt.get("authority_class") != AUTHORITY_CLASS:
        raise ValueError("CERV F&T discovery authority drift")
    if receipt.get("observation_state") not in {DISCOVERED_STATE, OMITTED_STATE}:
        raise ValueError("CERV F&T discovery state unsupported")
    if receipt.get("market_intelligence_only") is not True:
        raise ValueError("CERV F&T discovery left market-intelligence boundary")
    if receipt.get("bounded_discovery_absence_is_material_fact") is not False or receipt.get("closure_inference_authorized") is not False:
        raise ValueError("CERV F&T discovery attempted absence/closure inference")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"CERV F&T discovery attempted authorization: {key}")
    if receipt.get("publication_effect") != "NONE":
        raise ValueError("CERV F&T discovery attempted publication effect")

    for key, endpoint in (("search_receipt", ft.SEARCH_ENDPOINT), ("facet_receipt", ft.FACET_ENDPOINT)):
        source = receipt.get(key)
        if not isinstance(source, Mapping):
            raise ValueError(f"CERV F&T discovery missing {key}")
        final_url = str(source.get("final_url") or source.get("url") or "")
        parsed = urlparse(final_url)
        expected = urlparse(endpoint)
        if parsed.scheme != "https" or parsed.hostname != expected.hostname or parsed.path != expected.path:
            raise ValueError(f"CERV F&T discovery left official API authority in {key}")
        digest = str(source.get("sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"CERV F&T discovery missing immutable {key} hash")
    if receipt.get("search_raw_sha256") != (receipt.get("search_receipt") or {}).get("sha256"):
        raise ValueError("CERV F&T discovery search hash binding mismatch")
    if receipt.get("facet_raw_sha256") != (receipt.get("facet_receipt") or {}).get("sha256"):
        raise ValueError("CERV F&T discovery facet hash binding mismatch")

    candidates = receipt.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("CERV F&T discovery candidates malformed")
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("CERV F&T discovery candidate malformed")
        validate_reference(str(candidate.get("identifier") or ""))
        if not _is_cerv_label(str(candidate.get("programme_label") or "")):
            raise ValueError("CERV F&T discovery candidate lost programme proof")
        if candidate.get("authority_url_candidate") != ft.topic_url(str(candidate.get("identifier"))):
            raise ValueError("CERV F&T discovery candidate authority URL drift")
        if candidate.get("authority_url_verified") is not False:
            raise ValueError("CERV F&T discovery candidate self-verified authority")
        if candidate.get("material_fact_use") is not False or candidate.get("open_call_authorized") is not False:
            raise ValueError("CERV F&T discovery candidate attempted material use")
        semantics = {
            key: candidate.get(key)
            for key in (
                "identifier", "record_type", "programme_reference", "programme_label",
                "call_identifier", "status_code", "status_label_candidate", "title",
                "authority_url_candidate",
            )
        }
        if candidate.get("semantic_fingerprint") != sha256_json(semantics):
            raise ValueError("CERV F&T discovery candidate semantic fingerprint mismatch")

    selected = receipt.get("selected_candidate")
    selected_reference = receipt.get("selected_reference")
    if selected is None:
        if selected_reference is not None or receipt.get("exact_current_recheck_required") is not False:
            raise ValueError("CERV F&T discovery omission attempted exact handoff")
        if receipt.get("observation_state") != OMITTED_STATE:
            raise ValueError("CERV F&T discovery omission state mismatch")
    else:
        if not isinstance(selected, Mapping) or selected not in candidates:
            raise ValueError("CERV F&T discovery selected candidate is not bound to candidate set")
        if selected_reference != selected.get("identifier") or receipt.get("exact_current_recheck_required") is not True:
            raise ValueError("CERV F&T discovery selected reference mismatch")
        if receipt.get("observation_state") != DISCOVERED_STATE:
            raise ValueError("CERV F&T discovery selected state mismatch")

    expected = sha256_json({
        "query_text": receipt.get("query_text"),
        "candidates": candidates,
        "selected_reference": selected_reference,
        "conflict_identifiers": receipt.get("conflict_identifiers") or [],
        "source_hashes": [receipt.get("search_raw_sha256"), receipt.get("facet_raw_sha256")],
    })
    if receipt.get("semantic_fingerprint") != expected:
        raise ValueError("CERV F&T discovery semantic fingerprint mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--run-id", default="cerv-ft-discovery-live")
    parser.add_argument("--query-text", default="CERV-2026")
    parser.add_argument("--page-size", type=int, default=25)
    args = parser.parse_args()
    receipt = collect(
        run_id=args.run_id,
        output_dir=args.output_dir,
        query_text=args.query_text,
        page_size=args.page_size,
    )
    print(json.dumps({
        "observation_state": receipt["observation_state"],
        "candidate_count": len(receipt["candidates"]),
        "selected_reference": receipt["selected_reference"],
        "exact_current_recheck_required": receipt["exact_current_recheck_required"],
        "open_call_authorized": receipt["open_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
