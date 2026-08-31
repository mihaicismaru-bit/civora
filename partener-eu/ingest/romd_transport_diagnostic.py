#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ADAPTER_ID = "INTERREG_ROMD_TRANSPORT_DIAGNOSTIC_V1"
ALLOWED_HOSTS = {"ro-md.net", "www.ro-md.net"}
ALLOWED_PATH_PREFIXES = (
    "/en/news-2021-2027/",
    "/en/programme-2021-2027",
)
MARKER_GROUPS = (
    ("2028",),
    ("2034",),
    ("consultation",),
    ("romania", "românia"),
    ("moldova",),
)
CANDIDATES = (
    {
        "id": "EXACT_NON_WWW",
        "url": "https://ro-md.net/en/news-2021-2027/public-consultation-on-the-future-interreg-romania-moldova-chapter-2028-2034",
        "authority_role": "EXACT_PROGRAMME_ARTICLE",
    },
    {
        "id": "EXACT_WWW",
        "url": "https://www.ro-md.net/en/news-2021-2027/public-consultation-on-the-future-interreg-romania-moldova-chapter-2028-2034",
        "authority_role": "EXACT_PROGRAMME_ARTICLE_ALIAS",
    },
    {
        "id": "NEWS_INDEX_WWW",
        "url": "https://www.ro-md.net/en/news-2021-2027",
        "authority_role": "PROGRAMME_NEWS_INDEX",
    },
    {
        "id": "PROGRAMME_HOME_WWW",
        "url": "https://www.ro-md.net/en/programme-2021-2027",
        "authority_role": "PROGRAMME_HOME",
    },
    {
        "id": "PROGRAMME_HOME_NON_WWW",
        "url": "https://ro-md.net/en/programme-2021-2027",
        "authority_role": "PROGRAMME_HOME_ALIAS",
    },
)
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
    "registry_mutation_authorized",
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def validate_candidate_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise ValueError("ROMD diagnostic requires HTTPS")
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"ROMD diagnostic host outside allowlist: {host}")
    if not any((parsed.path or "/").startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES):
        raise ValueError(f"ROMD diagnostic path outside allowlist: {parsed.path}")
    if parsed.username or parsed.password:
        raise ValueError("ROMD diagnostic URL cannot contain userinfo")


def marker_report(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="ignore")
    folded = re.sub(r"\s+", " ", text).casefold()
    missing: list[list[str]] = []
    for group in MARKER_GROUPS:
        if not any(marker.casefold() in folded for marker in group):
            missing.append(list(group))
    return {
        "all_required_markers_present": not missing,
        "missing_marker_groups": missing,
    }


def classify_probe(*, status: int | None, raw: bytes | None, error_kind: str | None) -> dict[str, Any]:
    if error_kind == "CERTIFICATE_VERIFY_FAILED":
        return {"health_state": "DEGRADED_CERTIFICATE_VERIFY_FAILED", "marker_report": None}
    if error_kind:
        return {"health_state": "DEGRADED_TRANSPORT", "marker_report": None}
    if status != 200 or raw is None:
        return {"health_state": "DEGRADED_HTTP", "marker_report": None}
    markers = marker_report(raw)
    return {
        "health_state": "HEALTHY_PROGRAMMING_MARKERS" if markers["all_required_markers_present"] else "HEALTHY_DISCOVERY_ONLY",
        "marker_report": markers,
    }


def _certificate_failure(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return "certificate verify failed" in text or "certificate_verify_failed" in text


def probe_candidate(candidate: dict[str, str], *, timeout: float) -> dict[str, Any]:
    requested_url = candidate["url"]
    validate_candidate_url(requested_url)
    request = Request(
        requested_url,
        headers={
            "User-Agent": "PARTENER.EU-ROMDTransportDiagnostic/1.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
        },
        method="GET",
    )
    status: int | None = None
    final_url: str | None = None
    content_type: str | None = None
    raw: bytes | None = None
    error_kind: str | None = None
    error: str | None = None
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            final_url = response.geturl()
            status = int(getattr(response, "status", 200))
            content_type = str(response.headers.get("Content-Type", ""))
        validate_candidate_url(final_url)
    except HTTPError as exc:
        status = int(exc.code)
        error_kind = "HTTP_ERROR"
        error = f"{type(exc).__name__}: {exc}"
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        error_kind = "CERTIFICATE_VERIFY_FAILED" if _certificate_failure(exc) else type(exc).__name__.upper()
        error = f"{type(exc).__name__}: {exc}"

    classification = classify_probe(status=status, raw=raw, error_kind=error_kind)
    return {
        "candidate_id": candidate["id"],
        "authority_role": candidate["authority_role"],
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "raw_sha256": _sha256(raw) if raw is not None else None,
        "raw_size_bytes": len(raw) if raw is not None else 0,
        "error_kind": error_kind,
        "error": error,
        **classification,
    }


def build_diagnostic(*, run_id: str, timeout: float, observed_at: str | None = None) -> dict[str, Any]:
    if not run_id:
        raise ValueError("run_id is required")
    fetched_at = observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    probes = [probe_candidate(candidate, timeout=timeout) for candidate in CANDIDATES]
    healthy = [row for row in probes if row["health_state"] == "HEALTHY_PROGRAMMING_MARKERS"]
    exact_healthy = [row for row in healthy if row["authority_role"].startswith("EXACT_PROGRAMME_ARTICLE")]
    preferred = (exact_healthy or healthy)
    recommendation = preferred[0]["requested_url"] if preferred else None
    out: dict[str, Any] = {
        "adapter_id": ADAPTER_ID,
        "run_id": run_id,
        "fetched_at": fetched_at,
        "source_family": "INTERREG",
        "programme_family": "INTERREG_NEXT_RO_MD",
        "programme_period": "2028-2034",
        "authority_class": "T1_OFFICIAL_PROGRAMME_TRANSPORT_DIAGNOSTIC",
        "observation_state": "SOURCE_HEALTH_DIAGNOSTIC",
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "registry_mutation_authorized": False,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "tls_verification_disabled": False,
        "proxy_used": False,
        "candidate_count": len(probes),
        "healthy_programming_marker_count": len(healthy),
        "healthy_exact_article_count": len(exact_healthy),
        "recommended_primary_url_candidate": recommendation,
        "recommendation_semantics": "TRANSPORT_CANDIDATE_ONLY_REQUIRES_SEPARATE_REGISTRY_REVIEW",
        "probes": probes,
    }
    return out


def validate_output(data: dict[str, Any]) -> None:
    if data.get("adapter_id") != ADAPTER_ID or data.get("observation_state") != "SOURCE_HEALTH_DIAGNOSTIC":
        raise ValueError("ROMD diagnostic identity drift")
    if data.get("market_intelligence_only") is not True or data.get("publication_effect") != "NONE":
        raise ValueError("ROMD diagnostic policy drift")
    if data.get("tls_verification_disabled") is not False or data.get("proxy_used") is not False:
        raise ValueError("ROMD diagnostic transport safety drift")
    for key in MATERIAL_FLAGS:
        if data.get(key) is not False:
            raise ValueError(f"ROMD diagnostic became authorizing: {key}")
    probes = data.get("probes") or []
    if len(probes) != len(CANDIDATES):
        raise ValueError("ROMD diagnostic candidate inventory drift")
    for row in probes:
        validate_candidate_url(str(row.get("requested_url") or ""))
        raw_hash = row.get("raw_sha256")
        if row.get("health_state", "").startswith("HEALTHY") and (not raw_hash or len(str(raw_hash)) != 64):
            raise ValueError(f"healthy ROMD probe missing raw hash: {row.get('candidate_id')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--observed-at")
    parser.add_argument("--output")
    args = parser.parse_args()
    data = build_diagnostic(run_id=args.run_id, timeout=args.timeout, observed_at=args.observed_at)
    validate_output(data)
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
