#!/usr/bin/env python3
"""Exact official EUI Call 4 evidence, acquisition-only and fail-closed.

This adapter binds one explicit official human-readable call identity (EUI-IA
Call 4) to the dedicated European Urban Initiative call-detail page. It may
collect current status/deadline/budget/eligibility *candidates* from that exact
page, but it cannot authorize material facts, publication, distribution or
alerts. Semantic reconciliation and field-scoped material admission remain
mandatory downstream.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

SCHEMA = "PARTENER_EU_EUI_EXACT_EVIDENCE_V1"
PARSER_VERSION = "EU_DIRECT_EUI_EXACT_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "EUROPEAN_URBAN_INITIATIVE"
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "closed_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def load_registry(path: pathlib.Path) -> dict[str, Any]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry.get("registry_id") != "PARTENER_EU_EUI_EXACT_CALL_REGISTRY_V1":
        raise ValueError("EUI exact registry id drift")
    if registry.get("source_family") != SOURCE_FAMILY or registry.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("EUI exact registry family drift")
    calls = registry.get("calls")
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
        raise ValueError("EUI exact registry must contain exactly one bounded call")
    return registry


def _call_from_registry(registry: Mapping[str, Any], call_id: str) -> dict[str, Any]:
    matches = [row for row in registry.get("calls") or [] if isinstance(row, dict) and row.get("id") == call_id]
    if len(matches) != 1:
        raise ValueError(f"EUI exact call identity not uniquely registered: {call_id!r}")
    return dict(matches[0])


def _validate_exact_url(url: str, call: Mapping[str, Any]) -> str:
    parsed = urlparse(str(url or ""))
    hosts = {str(x).casefold() for x in call.get("allowed_hosts") or []}
    expected_path = str(call.get("allowed_path") or "")
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in hosts:
        raise ValueError("EUI exact authority escaped official HTTPS host allowlist")
    if (parsed.path or "/") != expected_path:
        raise ValueError("EUI exact authority escaped bounded call-detail path")
    if parsed.query or parsed.fragment:
        raise ValueError("EUI exact authority acquired unexpected query/fragment")
    return url


def _normalise_visible_text(raw: bytes) -> str:
    text = html.unescape(raw.decode("utf-8", errors="ignore"))
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _http_fetch(url: str, *, timeout: float = 30.0) -> tuple[bytes, int, str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": "PARTENER.EU-EUIExact/1.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.1",
            "Accept-Language": "en-US,en;q=0.8",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        return (
            response.read(),
            int(getattr(response, "status", 200)),
            str(response.geturl()),
            str(response.headers.get("Content-Type", "")),
        )


def _marker_groups_ok(text: str, groups: list[list[str]]) -> tuple[bool, list[dict[str, Any]]]:
    folded = text.casefold()
    results: list[dict[str, Any]] = []
    all_ok = True
    for group in groups:
        hits = [marker for marker in group if str(marker).casefold() in folded]
        ok = bool(hits)
        all_ok = all_ok and ok
        results.append({"markers": list(group), "verified": ok, "matched": hits})
    return all_ok, results


def _extract_material_candidates(text: str) -> dict[str, Any]:
    folded = text.casefold()
    closed = (
        "the call for proposals is closed" in folded
        or "fourth call for proposals (closed)" in folded
        or bool(re.search(r"\bclosed\s+on\s+15\s+june\s+2026\b", folded))
    )
    status_label = "Closed" if closed else None
    candidate_state = "CLOSED_CALL" if closed else "UNKNOWN"

    deadline_match = re.search(r"15\s+June\s+2026(?:\s+at\s+14[.:]00\s+CEST)?", text, flags=re.I)
    budget_match = re.search(r"EUR\s+60\s+million\s+ERDF", text, flags=re.I)
    contribution_match = re.search(r"(?:maximum\s+of\s+)?EUR\s+2\s+million\s+ERDF", text, flags=re.I)
    population_match = re.search(r"(?:above|at\s+least)\s+25\s*000\s+inhabitants", text, flags=re.I)

    return {
        "candidate_state": candidate_state,
        "status_label": status_label,
        "deadline_candidate": deadline_match.group(0) if deadline_match else None,
        "budget_candidate": budget_match.group(0) if budget_match else None,
        "max_erdf_contribution_candidate": contribution_match.group(0) if contribution_match else None,
        "urban_authority_population_threshold_candidate": population_match.group(0) if population_match else None,
    }


def _degraded_evidence(
    *,
    call: Mapping[str, Any],
    run_id: str,
    fetched_at: str,
    health_state: str,
    error: str,
    requested_url: str,
    final_url: str | None = None,
    http_status: int | None = None,
    content_type: str | None = None,
    raw_sha256: str | None = None,
    raw_size_bytes: int = 0,
    visible_text_sha256: str | None = None,
    marker_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": call.get("authority_class"),
        "observation_state": call.get("observation_state"),
        "call_id": call.get("id"),
        "official_identity_label": call.get("official_identity_label"),
        "official_title": call.get("official_title"),
        "identity_kind": call.get("identity_kind"),
        "authority_url": requested_url,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "source_health_state": health_state,
        "lkg_required": True,
        "evidence_usable_for_reconciliation": False,
        "current_material_truth_available": False,
        "material_admission_ready_for_downstream_review": False,
        "candidate_state": "UNKNOWN",
        "status_label": None,
        "deadline_candidate": None,
        "budget_candidate": None,
        "max_erdf_contribution_candidate": None,
        "urban_authority_population_threshold_candidate": None,
        "exact_semantics": None,
        "exact_semantic_fingerprint": None,
        "receipt": {
            "requested_url": requested_url,
            "final_url": final_url,
            "http_status": http_status,
            "content_type": content_type,
            "raw_sha256": raw_sha256,
            "raw_size_bytes": raw_size_bytes,
            "normalized_visible_text_sha256": visible_text_sha256,
            "marker_results": marker_results or [],
            "error": error,
        },
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        evidence[key] = False
    return evidence


def collect_exact(
    registry: Mapping[str, Any],
    *,
    call_id: str,
    run_id: str,
    fetched_at: str | None = None,
    output_dir: pathlib.Path | None = None,
    fetcher: Callable[..., tuple[bytes, int, str, str]] = _http_fetch,
) -> dict[str, Any]:
    call = _call_from_registry(registry, call_id)
    requested_url = _validate_exact_url(str(call.get("authority_url") or ""), call)
    fetched_at = fetched_at or utc_now()

    try:
        raw, status, final_url, content_type = fetcher(requested_url, timeout=30.0)
        _validate_exact_url(final_url, call)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        evidence = _degraded_evidence(
            call=call,
            run_id=run_id,
            fetched_at=fetched_at,
            health_state="DEGRADED_TRANSPORT",
            error=f"{type(exc).__name__}: {exc}",
            requested_url=requested_url,
            http_status=getattr(exc, "code", None),
        )
        validate_evidence(evidence, registry)
        _write_outputs(output_dir, evidence, None)
        return evidence

    visible = _normalise_visible_text(raw)
    raw_hash = sha256_bytes(raw)
    visible_hash = sha256_bytes(visible.encode("utf-8"))
    content_ok = "html" in content_type.casefold() or raw.lstrip().startswith(b"<")
    marker_ok, marker_results = _marker_groups_ok(visible, list(call.get("required_marker_groups") or []))
    application_pack_ok = all(str(marker).casefold() in visible.casefold() for marker in call.get("application_pack_markers") or [])
    healthy = status == 200 and content_ok and marker_ok and application_pack_ok

    if not healthy:
        evidence = _degraded_evidence(
            call=call,
            run_id=run_id,
            fetched_at=fetched_at,
            health_state="DEGRADED_MARKER_MISMATCH",
            error="official EUI exact call page failed status/content/identity/application-pack markers",
            requested_url=requested_url,
            final_url=final_url,
            http_status=status,
            content_type=content_type,
            raw_sha256=raw_hash,
            raw_size_bytes=len(raw),
            visible_text_sha256=visible_hash,
            marker_results=marker_results,
        )
        validate_evidence(evidence, registry)
        _write_outputs(output_dir, evidence, raw)
        return evidence

    candidates = _extract_material_candidates(visible)
    if candidates.get("candidate_state") != "CLOSED_CALL" or candidates.get("status_label") != "Closed":
        evidence = _degraded_evidence(
            call=call,
            run_id=run_id,
            fetched_at=fetched_at,
            health_state="DEGRADED_STATUS_UNRESOLVED",
            error="official EUI exact call page did not provide the expected explicit closed state",
            requested_url=requested_url,
            final_url=final_url,
            http_status=status,
            content_type=content_type,
            raw_sha256=raw_hash,
            raw_size_bytes=len(raw),
            visible_text_sha256=visible_hash,
            marker_results=marker_results,
        )
        validate_evidence(evidence, registry)
        _write_outputs(output_dir, evidence, raw)
        return evidence

    semantics = {
        "call_id": call.get("id"),
        "official_identity_label": call.get("official_identity_label"),
        "official_title": call.get("official_title"),
        "identity_kind": call.get("identity_kind"),
        "candidate_state": candidates.get("candidate_state"),
        "status_label": candidates.get("status_label"),
        "authority_url": final_url,
        "deadline_candidate": candidates.get("deadline_candidate"),
        "budget_candidate": candidates.get("budget_candidate"),
        "max_erdf_contribution_candidate": candidates.get("max_erdf_contribution_candidate"),
        "urban_authority_population_threshold_candidate": candidates.get("urban_authority_population_threshold_candidate"),
    }
    evidence: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": call.get("authority_class"),
        "observation_state": call.get("observation_state"),
        "call_id": call.get("id"),
        "official_identity_label": call.get("official_identity_label"),
        "official_title": call.get("official_title"),
        "identity_kind": call.get("identity_kind"),
        "authority_url": final_url,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "source_health_state": "HEALTHY",
        "lkg_required": False,
        "evidence_usable_for_reconciliation": True,
        "current_material_truth_available": False,
        "material_admission_ready_for_downstream_review": False,
        **candidates,
        "exact_semantics": semantics,
        "exact_semantic_fingerprint": sha256_json(semantics),
        "receipt": {
            "requested_url": requested_url,
            "final_url": final_url,
            "http_status": status,
            "content_type": content_type,
            "raw_sha256": raw_hash,
            "raw_size_bytes": len(raw),
            "normalized_visible_text_sha256": visible_hash,
            "marker_results": marker_results,
            "application_pack_markers_verified": True,
            "error": None,
        },
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        evidence[key] = False
    validate_evidence(evidence, registry)
    _write_outputs(output_dir, evidence, raw)
    return evidence


def validate_evidence(evidence: Mapping[str, Any], registry: Mapping[str, Any]) -> None:
    if evidence.get("schema") != SCHEMA or evidence.get("parser_version") != PARSER_VERSION:
        raise ValueError("EUI exact evidence schema/parser drift")
    if evidence.get("source_family") != SOURCE_FAMILY or evidence.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("EUI exact evidence family drift")
    call = _call_from_registry(registry, str(evidence.get("call_id") or ""))
    if evidence.get("official_identity_label") != call.get("official_identity_label"):
        raise ValueError("EUI exact official identity label drift")
    if evidence.get("official_title") != call.get("official_title"):
        raise ValueError("EUI exact official title drift")
    if evidence.get("identity_kind") != "OFFICIAL_HUMAN_READABLE_CALL_IDENTITY":
        raise ValueError("EUI exact identity kind drift")
    _validate_exact_url(str(evidence.get("authority_url") or call.get("authority_url") or ""), call)

    for key in MATERIAL_FLAGS:
        if evidence.get(key) is not False:
            raise ValueError(f"EUI exact evidence attempted material authorization: {key}")
    if evidence.get("publication_effect") != "NONE" or evidence.get("canonical_corpus_mutation") is not False:
        raise ValueError("EUI exact evidence crossed publication boundary")
    if evidence.get("semantic_reconciliation_required") is not True or evidence.get("field_scoped_material_admission_required") is not True:
        raise ValueError("EUI exact evidence skipped downstream gates")
    if evidence.get("current_material_truth_available") is not False:
        raise ValueError("EUI exact acquisition attempted to become current material truth")
    if evidence.get("material_admission_ready_for_downstream_review") is not False:
        raise ValueError("EUI exact acquisition bypassed semantic reconciliation")

    health = evidence.get("source_health_state")
    receipt = evidence.get("receipt")
    if not isinstance(receipt, dict):
        raise ValueError("EUI exact evidence receipt missing")
    if health == "HEALTHY":
        if evidence.get("lkg_required") is not False or evidence.get("evidence_usable_for_reconciliation") is not True:
            raise ValueError("healthy EUI exact evidence health flags drift")
        if evidence.get("candidate_state") != "CLOSED_CALL" or evidence.get("status_label") != "Closed":
            raise ValueError("healthy EUI exact evidence lost explicit closed candidate")
        semantics = evidence.get("exact_semantics")
        if not isinstance(semantics, dict) or sha256_json(semantics) != evidence.get("exact_semantic_fingerprint"):
            raise ValueError("EUI exact semantic fingerprint mismatch")
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("raw_sha256") or "")):
            raise ValueError("healthy EUI exact evidence missing raw hash")
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("normalized_visible_text_sha256") or "")):
            raise ValueError("healthy EUI exact evidence missing visible-text hash")
        if receipt.get("application_pack_markers_verified") is not True:
            raise ValueError("healthy EUI exact evidence lost application-pack marker proof")
        _validate_exact_url(str(receipt.get("final_url") or ""), call)
    elif isinstance(health, str) and health.startswith("DEGRADED_"):
        if evidence.get("lkg_required") is not True or evidence.get("evidence_usable_for_reconciliation") is not False:
            raise ValueError("degraded EUI exact evidence failed fail-closed health flags")
        if evidence.get("candidate_state") != "UNKNOWN" or evidence.get("status_label") is not None:
            raise ValueError("degraded EUI exact evidence retained material status candidate")
        for key in (
            "deadline_candidate",
            "budget_candidate",
            "max_erdf_contribution_candidate",
            "urban_authority_population_threshold_candidate",
            "exact_semantics",
            "exact_semantic_fingerprint",
        ):
            if evidence.get(key) is not None:
                raise ValueError(f"degraded EUI exact evidence retained {key}")
    else:
        raise ValueError(f"unsupported EUI exact source health state: {health!r}")


def _write_outputs(output_dir: pathlib.Path | None, evidence: Mapping[str, Any], raw: bytes | None) -> None:
    if not output_dir:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        (output_dir / "eui-call-4-exact.html").write_bytes(raw)
    (output_dir / "eui-call-4-exact-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=pathlib.Path, default=pathlib.Path(__file__).with_name("eu_direct_eui_exact_registry.json"))
    parser.add_argument("--call-id", default="EUI-IA-CALL-4-2026")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    args = parser.parse_args()
    registry = load_registry(args.registry)
    evidence = collect_exact(registry, call_id=args.call_id, run_id=args.run_id, output_dir=args.output_dir)
    print(json.dumps({
        "call_id": evidence.get("call_id"),
        "source_health_state": evidence.get("source_health_state"),
        "candidate_state": evidence.get("candidate_state"),
        "status_label": evidence.get("status_label"),
        "lkg_required": evidence.get("lkg_required"),
        "exact_semantic_fingerprint": evidence.get("exact_semantic_fingerprint"),
        "publication_effect": evidence.get("publication_effect"),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if evidence.get("source_health_state") == "HEALTHY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
