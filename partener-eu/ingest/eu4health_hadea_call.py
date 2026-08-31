#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PARSER_VERSION = "EU4HEALTH_HADEA_CALLS_V1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "partener-eu" / "ingest" / "eu4health_hadea_call_registry.json"
TRANSIENT_HTTP_STATUSES = frozenset({202, 408, 425, 429, 500, 502, 503, 504})
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
)
MISSING_FOR_OPEN_CONFIRMATION = [
    "exact_current_funding_tenders_topic_record",
    "same_call_reference_match_hadea_to_funding_tenders",
    "explicit_current_funding_tenders_topic_status",
    "call_specific_deadline_budget_eligibility_and_participation_rules",
    "semantic_reconciliation",
]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _fingerprint(value: Any) -> str:
    return _sha256(_canonical_json(value))


def _parse_observed_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    if not value.endswith("Z"):
        raise ValueError("observed_at must be RFC3339 UTC-Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _validate_https_url(url: str, *, hosts: list[str], path_prefixes: list[str]) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise ValueError(f"non-HTTPS official URL: {url}")
    if host not in {str(item).lower() for item in hosts}:
        raise ValueError(f"official host not allowlisted: {host}")
    path = parsed.path or "/"
    if path_prefixes and not any(path.startswith(prefix) for prefix in path_prefixes):
        raise ValueError(f"official path outside allowlist: {path}")


def load_registry(path: Path = DEFAULT_REGISTRY) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if data.get("schema_version") != "1.0":
        raise ValueError("unsupported EU4Health HaDEA registry schema")
    if data.get("registry_id") != "EU4HEALTH_HADEA_CALL_REGISTRY_V1":
        raise ValueError("unexpected EU4Health HaDEA registry id")
    if data.get("programme_family") != "EU4Health" or data.get("source_family") != "EU_DIRECT":
        raise ValueError("EU4Health programme/source boundary drift")
    checked = date.fromisoformat(str(data.get("evidence_checked_date") or ""))
    if checked > datetime.now(timezone.utc).date():
        raise ValueError("registry evidence_checked_date is in the future")

    policy = data.get("policy") or {}
    if policy.get("market_intelligence_only") is not True or policy.get("publication_effect") != "NONE":
        raise ValueError("EU4Health HaDEA policy drift")
    for key in MATERIAL_FLAGS:
        if policy.get(key) is not False:
            raise ValueError(f"EU4Health HaDEA registry became authorizing: {key}")

    authority = data.get("authority") or {}
    if authority.get("authority_class") != "OFFICIAL_EXECUTIVE_AGENCY_EXACT_CALL_EVIDENCE":
        raise ValueError("HaDEA authority class drift")
    groups = authority.get("required_marker_groups") or []
    if not groups or any(not isinstance(group, list) or not group for group in groups):
        raise ValueError("HaDEA required marker groups missing")
    patterns = authority.get("reference_patterns") or []
    if not patterns:
        raise ValueError("EU4Health reference patterns missing")
    for pattern in patterns:
        re.compile(str(pattern))

    admission = data.get("admission") or {}
    for required_true in (
        "exact_hadea_call_page_required",
        "exact_call_reference_required",
        "funding_tenders_exact_topic_required_for_material_admission",
        "semantic_reconciliation_required",
    ):
        if admission.get(required_true) is not True:
            raise ValueError(f"EU4Health admission requirement relaxed: {required_true}")
    for required_false in ("generic_programme_page_authorizes_open", "call_index_authorizes_open"):
        if admission.get(required_false) is not False:
            raise ValueError(f"EU4Health unsafe admission policy: {required_false}")

    fixture = data.get("live_fixture") or {}
    _validate_https_url(
        str(fixture.get("url") or ""),
        hosts=list(authority.get("allowed_hosts") or []),
        path_prefixes=list(authority.get("allowed_path_prefixes") or []),
    )
    if not fixture.get("expected_reference"):
        raise ValueError("live fixture exact reference missing")
    return data, _sha256(raw)


def _html_to_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="ignore")
    text = re.sub(r"(?is)<script\b.*?</script>", " ", text)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_reference(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0).upper()
    return None


def _extract_label_value(text: str, label: str, stop_labels: tuple[str, ...]) -> str | None:
    stop = "|".join(re.escape(item) for item in stop_labels)
    match = re.search(
        rf"\b{re.escape(label)}\b\s+(.+?)(?=\s+(?:{stop})\b|$)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip(" :-")
    return value[:240] if value else None


def _extract_ft_links(raw: bytes) -> list[str]:
    source = html.unescape(raw.decode("utf-8", errors="ignore"))
    links: list[str] = []
    for match in re.finditer(r'''href=["']([^"']+)["']''', source, flags=re.IGNORECASE):
        url = match.group(1).strip()
        if url.startswith("https://") and "funding-tenders" in url.lower():
            if url not in links:
                links.append(url)
    return links


def extract_call_evidence(raw: bytes, *, reference_patterns: list[str]) -> dict[str, Any]:
    text = _html_to_text(raw)
    folded = text.casefold()
    reference = _extract_reference(text, reference_patterns)
    status = _extract_label_value(
        text,
        "Status",
        ("Reference", "Publication date", "Opening date", "Deadline model", "Deadline date", "Funding programme", "Programme Sector", "Programme", "Tags", "Description"),
    )
    publication_date = _extract_label_value(
        text,
        "Publication date",
        ("Opening date", "Deadline model", "Deadline date", "Funding programme", "Programme Sector", "Programme", "Tags", "Description"),
    )
    opening_date = _extract_label_value(
        text,
        "Opening date",
        ("Deadline model", "Deadline date", "Funding programme", "Programme Sector", "Programme", "Tags", "Description"),
    )
    deadline = _extract_label_value(
        text,
        "Deadline date",
        ("Funding programme", "Programme Sector", "Programme", "Tags", "Description"),
    )
    ft_links = _extract_ft_links(raw)
    exact_ft_topic = next((url for url in ft_links if "topic-details" in url.lower()), None)
    page_kind = "CALL_FOR_PROPOSALS" if "call for proposals" in folded else "UNKNOWN"
    programme_match = "EU4Health" if "eu4health" in folded else None
    return {
        "page_kind": page_kind,
        "call_reference": reference,
        "status_candidate": status,
        "publication_date_candidate": publication_date,
        "opening_date_candidate": opening_date,
        "deadline_candidate": deadline,
        "programme_candidate": programme_match,
        "funding_tenders_link_present": bool(ft_links),
        "funding_tenders_links": ft_links[:10],
        "funding_tenders_exact_topic_url": exact_ft_topic,
    }


def _degraded(
    *,
    requested_url: str,
    health_state: str,
    attempt_count: int,
    error: str | None,
    final_url: str | None = None,
    http_status: int | None = None,
    content_type: str | None = None,
    raw: bytes | None = None,
    missing_marker_groups: list[list[str]] | None = None,
) -> dict[str, Any]:
    return {
        "health_state": health_state,
        "lkg_required": True,
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": http_status,
        "content_type": content_type,
        "raw_sha256": _sha256(raw) if raw is not None else None,
        "raw_size_bytes": len(raw) if raw is not None else 0,
        "missing_marker_groups": missing_marker_groups or [],
        "attempt_count": attempt_count,
        "error": error,
    }


def _probe(url: str, authority: dict[str, Any], *, timeout: float, max_attempts: int) -> tuple[dict[str, Any], bytes | None]:
    if max_attempts < 1 or max_attempts > 4:
        raise ValueError("max_attempts must be between 1 and 4")
    _validate_https_url(
        url,
        hosts=list(authority.get("allowed_hosts") or []),
        path_prefixes=list(authority.get("allowed_path_prefixes") or []),
    )
    request = Request(
        url,
        headers={
            "User-Agent": "PARTENER.EU-EU4HealthHaDEA/1.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
        },
        method="GET",
    )
    for attempt in range(1, max_attempts + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = int(getattr(response, "status", 200))
                final_url = str(response.geturl())
                content_type = str(response.headers.get("Content-Type", ""))
            _validate_https_url(
                final_url,
                hosts=list(authority.get("allowed_hosts") or []),
                path_prefixes=list(authority.get("allowed_path_prefixes") or []),
            )
            if status in TRANSIENT_HTTP_STATUSES and attempt < max_attempts:
                time.sleep(0.25 * (2 ** (attempt - 1)))
                continue
            if status != 200:
                return _degraded(
                    requested_url=url,
                    health_state="DEGRADED_TRANSIENT_EXHAUSTED" if status in TRANSIENT_HTTP_STATUSES else "DEGRADED",
                    attempt_count=attempt,
                    error=f"unexpected HTTP status {status}",
                    final_url=final_url,
                    http_status=status,
                    content_type=content_type,
                    raw=raw,
                ), raw
            text = _html_to_text(raw).casefold()
            missing: list[list[str]] = []
            for group in authority.get("required_marker_groups") or []:
                if not any(str(marker).casefold() in text for marker in group):
                    missing.append(group)
            if missing:
                return _degraded(
                    requested_url=url,
                    health_state="DEGRADED_MARKER_MISMATCH",
                    attempt_count=attempt,
                    error=None,
                    final_url=final_url,
                    http_status=status,
                    content_type=content_type,
                    raw=raw,
                    missing_marker_groups=missing,
                ), raw
            return {
                "health_state": "HEALTHY",
                "lkg_required": False,
                "requested_url": url,
                "final_url": final_url,
                "http_status": status,
                "content_type": content_type,
                "raw_sha256": _sha256(raw),
                "raw_size_bytes": len(raw),
                "missing_marker_groups": [],
                "attempt_count": attempt,
                "error": None,
            }, raw
        except HTTPError as exc:
            status = int(exc.code)
            if status in TRANSIENT_HTTP_STATUSES and attempt < max_attempts:
                time.sleep(0.25 * (2 ** (attempt - 1)))
                continue
            return _degraded(
                requested_url=url,
                health_state="DEGRADED_TRANSIENT_EXHAUSTED" if status in TRANSIENT_HTTP_STATUSES else "DEGRADED",
                attempt_count=attempt,
                error=f"HTTPError: {exc}",
                http_status=status,
            ), None
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            return _degraded(
                requested_url=url,
                health_state="DEGRADED",
                attempt_count=attempt,
                error=f"{type(exc).__name__}: {exc}",
            ), None
    raise AssertionError("bounded HaDEA probe loop exited unexpectedly")


def resolve(
    *,
    call_url: str,
    run_id: str,
    observed_at: str | None = None,
    registry_path: Path = DEFAULT_REGISTRY,
    live: bool = False,
    timeout: float = 12.0,
    max_attempts: int = 3,
) -> dict[str, Any]:
    registry, registry_sha256 = load_registry(registry_path)
    now = _parse_observed_at(observed_at)
    authority = registry["authority"]
    _validate_https_url(
        call_url,
        hosts=list(authority.get("allowed_hosts") or []),
        path_prefixes=list(authority.get("allowed_path_prefixes") or []),
    )

    if live:
        health, raw = _probe(call_url, authority, timeout=timeout, max_attempts=max_attempts)
    else:
        health = {
            "health_state": "NOT_PROBED",
            "lkg_required": False,
            "requested_url": call_url,
            "final_url": None,
            "http_status": None,
            "content_type": None,
            "raw_sha256": None,
            "raw_size_bytes": 0,
            "missing_marker_groups": [],
            "attempt_count": 0,
            "error": None,
        }
        raw = None

    extracted = extract_call_evidence(raw, reference_patterns=list(authority["reference_patterns"])) if raw else {
        "page_kind": None,
        "call_reference": None,
        "status_candidate": None,
        "publication_date_candidate": None,
        "opening_date_candidate": None,
        "deadline_candidate": None,
        "programme_candidate": None,
        "funding_tenders_link_present": False,
        "funding_tenders_links": [],
        "funding_tenders_exact_topic_url": None,
    }
    evidence_usable = health["health_state"] == "HEALTHY" and bool(extracted.get("call_reference"))
    if health["health_state"] == "HEALTHY" and not extracted.get("call_reference"):
        health = dict(health)
        health["health_state"] = "DEGRADED_REFERENCE_MISSING"
        health["lkg_required"] = True
        evidence_usable = False

    semantic_payload = {
        "authority_url": health.get("final_url") or call_url,
        "page_kind": extracted.get("page_kind"),
        "call_reference": extracted.get("call_reference"),
        "status_candidate": extracted.get("status_candidate"),
        "publication_date_candidate": extracted.get("publication_date_candidate"),
        "opening_date_candidate": extracted.get("opening_date_candidate"),
        "deadline_candidate": extracted.get("deadline_candidate"),
        "programme_candidate": extracted.get("programme_candidate"),
        "funding_tenders_exact_topic_url": extracted.get("funding_tenders_exact_topic_url"),
    }

    return {
        "schema_version": "1.0",
        "adapter_id": PARSER_VERSION,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "fetched_at": now.isoformat().replace("+00:00", "Z"),
        "registry_sha256": registry_sha256,
        "registry_evidence_checked_date": registry["evidence_checked_date"],
        "source_family": "EU_DIRECT",
        "programme_family": "EU4Health",
        "authority_class": authority["authority_class"],
        "observation_state": "EXACT_CALL_EVIDENCE_UNRECONCILED",
        "requested_url": call_url,
        "source_health": health,
        "evidence_usable_for_reconciliation": evidence_usable,
        "extracted": extracted,
        "semantic_fingerprint": _fingerprint(semantic_payload),
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "publication_effect": "NONE",
        "funding_tenders_exact_topic_required": True,
        "semantic_reconciliation_required": True,
        "missing_for_open_confirmation": list(MISSING_FOR_OPEN_CONFIRMATION),
        "note": (
            "An exact official HaDEA call page is captured as evidence only. Its status/deadline/reference candidates "
            "remain non-authorizing until the same call is bound to a current exact Funding & Tenders topic record "
            "and semantic reconciliation passes."
        ),
        "rollback": "Discard this evidence receipt; no canonical call state is mutated.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture an exact EU4Health HaDEA call page without authorizing material call facts.")
    parser.add_argument("--call-url", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--observed-at")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = resolve(
        call_url=args.call_url,
        run_id=args.run_id,
        observed_at=args.observed_at,
        registry_path=args.registry,
        live=args.live,
        timeout=args.timeout,
        max_attempts=args.max_attempts,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
