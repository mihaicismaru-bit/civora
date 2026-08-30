#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

PARSER_VERSION = "EEA_ROMANIA_OPERATOR_WATCH_V1"
ADAPTER_ID = "EEA_ROMANIA_OPERATOR_WATCH_V1"
PROGRAMME_FAMILY = "EEA_NORWAY"
SOURCE_FAMILY = "EEA_NORWAY_OPERATOR_WATCH"
MAX_BYTES = 4 * 1024 * 1024
MAX_CANDIDATES = 100
USER_AGENT = "CIVORA-PARTENER-EU/1.0 (+https://civora.ro)"
ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
MISSING_FOR_OPEN = [
    "exact_call_or_topic_identifier",
    "current_official_exact_call_endpoint",
    "explicit_current_official_open_status",
    "semantic_reconciliation",
]
AUTHORIZATION_KEYS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_registry(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_registry(data)
    return data


def validate_registry(data: dict) -> None:
    if data.get("schema_version") != "1.0":
        raise ValueError("unexpected operator-watch registry schema")
    if data.get("programme_family") != PROGRAMME_FAMILY or data.get("source_family") != SOURCE_FAMILY:
        raise ValueError("operator-watch registry family drift")
    assignment = urllib.parse.urlparse(str(data.get("authority_assignment_source_url") or ""))
    if assignment.scheme != "https" or (assignment.hostname or "").lower() != "eeagrants.org":
        raise ValueError("operator assignment authority must remain the official FMO/EEA Grants host")
    policy = data.get("policy") or {}
    for key in AUTHORIZATION_KEYS:
        if policy.get(key) is not False:
            raise ValueError(f"registry policy {key} must remain false")
    routes = data.get("routes") or []
    if len(routes) < 2:
        raise ValueError("operator-watch registry must retain at least two official routes")
    seen: set[str] = set()
    for route in routes:
        route_id = str(route.get("route_id") or "")
        if not route_id or route_id in seen:
            raise ValueError("route_id must be present and unique")
        seen.add(route_id)
        if route.get("authority_class") not in {"T1_OFFICIAL_PROGRAMME_OPERATOR", "T1_OFFICIAL_FUND_OPERATOR"}:
            raise ValueError(f"unsupported authority class for {route_id}")
        if route.get("observation_state") not in {"OPERATOR_WATCH", "OPERATOR_WATCH_HISTORICAL_LANDING"}:
            raise ValueError(f"unsafe operator-watch observation state for {route_id}")
        if not route.get("programme_ids") or not route.get("candidate_keywords"):
            raise ValueError(f"route lacks programme mapping or bounded discovery keywords: {route_id}")
        validate_route_url(str(route.get("watch_url") or ""), route)


def allowed_hosts(route: dict) -> set[str]:
    return {str(host).lower() for host in route.get("allowed_hosts") or []}


def validate_route_url(url: str, route: dict, *, final: bool = False) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("operator-watch acquisition requires HTTPS")
    if (parsed.hostname or "").lower() not in allowed_hosts(route):
        raise ValueError(f"unexpected operator-watch host: {parsed.hostname!r}")
    if final:
        prefixes = tuple(str(p) for p in route.get("allowed_final_path_prefixes") or [])
        path = parsed.path or "/"
        if not prefixes or not any(path.startswith(prefix) for prefix in prefixes):
            raise ValueError(f"unexpected final operator-watch path: {path!r}")


class StrictRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, route: dict) -> None:
        super().__init__()
        self.route = route

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        absolute = urllib.parse.urljoin(req.full_url, newurl)
        validate_route_url(absolute, self.route, final=True)
        return super().redirect_request(req, fp, code, msg, headers, absolute)


class OperatorLinkParser(HTMLParser):
    def __init__(self, base_url: str, route: dict) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.route = route
        self._href: str | None = None
        self._text: list[str] = []
        self.rows: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        href = urllib.parse.urljoin(self.base_url, self._href)
        label = normalize_space(" ".join(self._text))
        self._href = None
        self._text = []
        parsed = urllib.parse.urlparse(href)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in allowed_hosts(self.route):
            return
        haystack = f"{label} {parsed.path} {parsed.query}".lower()
        keywords = [str(k).lower() for k in self.route.get("candidate_keywords") or []]
        if not any(keyword in haystack for keyword in keywords):
            return
        self.rows.append({
            "label_candidate": label or (parsed.path.rstrip("/").split("/")[-1] or parsed.hostname or "official operator link"),
            "url_candidate": href,
            "candidate_observation_state": "DISCOVERY_ONLY",
        })


def extract_candidates(raw: bytes, final_url: str, route: dict) -> list[dict[str, str]]:
    parser = OperatorLinkParser(final_url, route)
    parser.feed(raw.decode("utf-8", errors="replace"))
    unique: dict[str, dict[str, str]] = {}
    for row in parser.rows:
        unique.setdefault(row["url_candidate"], row)
    return [unique[url] for url in sorted(unique)[:MAX_CANDIDATES]]


def fetch_route(route: dict) -> tuple[bytes, str, int, str]:
    requested_url = str(route["watch_url"])
    validate_route_url(requested_url, route)
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        StrictRedirectHandler(route),
    )
    request = urllib.request.Request(
        requested_url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    try:
        with opener.open(request, timeout=30) as response:
            final_url = response.geturl()
            validate_route_url(final_url, route, final=True)
            status = int(getattr(response, "status", 200))
            content_type = response.headers.get_content_type().lower()
            if status != 200:
                raise RuntimeError(f"unexpected HTTP status {status}")
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise RuntimeError(f"unexpected content type {content_type!r}")
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise RuntimeError("operator-watch response exceeded bounded acquisition limit")
            return raw, final_url, status, content_type
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} while acquiring {route.get('route_id')}") from exc


def base_receipt(route: dict, *, run_id: str, fetched_at: str) -> dict:
    receipt = {
        "route_id": route["route_id"],
        "operator_name": route["operator_name"],
        "operator_role": route["operator_role"],
        "programme_ids": list(route["programme_ids"]),
        "programme_family": PROGRAMME_FAMILY,
        "source_family": SOURCE_FAMILY,
        "authority_class": route["authority_class"],
        "observation_state": route["observation_state"],
        "period_context": route["period_context"],
        "requested_url": route["watch_url"],
        "run_id": run_id,
        "fetched_at": fetched_at,
        "missing_for_open_confirmation": list(MISSING_FOR_OPEN),
    }
    for key in AUTHORIZATION_KEYS:
        receipt[key] = False
    return receipt


def build_healthy_receipt(raw: bytes, route: dict, *, final_url: str, status: int, content_type: str, run_id: str, fetched_at: str) -> dict:
    receipt = base_receipt(route, run_id=run_id, fetched_at=fetched_at)
    receipt.update({
        "health_state": "HEALTHY",
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "raw_sha256": sha256_bytes(raw),
        "candidate_count": 0,
        "candidates": [],
        "lkg_required": False,
    })
    candidates = extract_candidates(raw, final_url, route)
    receipt["candidate_count"] = len(candidates)
    receipt["candidates"] = candidates
    return receipt


def build_degraded_receipt(route: dict, *, run_id: str, fetched_at: str, error: Exception) -> dict:
    receipt = base_receipt(route, run_id=run_id, fetched_at=fetched_at)
    receipt.update({
        "health_state": "DEGRADED",
        "final_url": None,
        "http_status": None,
        "content_type": None,
        "raw_sha256": None,
        "candidate_count": 0,
        "candidates": [],
        "lkg_required": True,
        "error_class": type(error).__name__,
        "error_message": normalize_space(str(error))[:500],
    })
    return receipt


def validate_receipt(receipt: dict, route: dict) -> None:
    if receipt.get("route_id") != route.get("route_id"):
        raise ValueError("operator-watch route identity drift")
    if receipt.get("programme_family") != PROGRAMME_FAMILY or receipt.get("source_family") != SOURCE_FAMILY:
        raise ValueError("operator-watch receipt family drift")
    if receipt.get("authority_class") != route.get("authority_class") or receipt.get("observation_state") != route.get("observation_state"):
        raise ValueError("operator-watch authority/state drift")
    for key in AUTHORIZATION_KEYS:
        if receipt.get(key) is not False:
            raise ValueError(f"{key} must remain false for operator-watch evidence")
    if set(MISSING_FOR_OPEN) - set(receipt.get("missing_for_open_confirmation") or []):
        raise ValueError("operator-watch receipt is missing OPEN proof requirements")
    validate_route_url(str(receipt.get("requested_url") or ""), route)
    if receipt.get("health_state") == "HEALTHY":
        validate_route_url(str(receipt.get("final_url") or ""), route, final=True)
        digest = str(receipt.get("raw_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("healthy operator-watch receipt lacks a valid raw SHA-256")
        candidates = receipt.get("candidates") or []
        if len(candidates) != receipt.get("candidate_count"):
            raise ValueError("operator-watch candidate count mismatch")
        for candidate in candidates:
            if candidate.get("candidate_observation_state") != "DISCOVERY_ONLY":
                raise ValueError("operator candidate escaped discovery-only state")
            parsed = urllib.parse.urlparse(str(candidate.get("url_candidate") or ""))
            if parsed.scheme != "https" or (parsed.hostname or "").lower() not in allowed_hosts(route):
                raise ValueError("operator candidate escaped official route hosts")
    elif receipt.get("health_state") == "DEGRADED":
        if receipt.get("lkg_required") is not True or receipt.get("candidate_count") != 0:
            raise ValueError("degraded operator-watch route must require LKG and authorize no candidates")
    else:
        raise ValueError("unknown operator-watch health state")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded acquisition-only EEA Romania official operator watch")
    parser.add_argument("--registry", default="partener-eu/ingest/eea_romania_operator_watch_registry.json")
    parser.add_argument("--output-dir", default="partener-eu/ingest/evidence/eea-romania-operator-watch")
    parser.add_argument("--run-id", default="manual")
    args = parser.parse_args()

    registry_path = Path(args.registry)
    registry = load_registry(registry_path)
    fetched_at = utc_now_iso()
    out = Path(args.output_dir)
    raw_dir = out / "raw"
    handoff_dir = out / "handoff"
    raw_dir.mkdir(parents=True, exist_ok=True)
    handoff_dir.mkdir(parents=True, exist_ok=True)

    receipts: list[dict] = []
    healthy = 0
    for route in registry["routes"]:
        try:
            raw, final_url, status, content_type = fetch_route(route)
            receipt = build_healthy_receipt(
                raw,
                route,
                final_url=final_url,
                status=status,
                content_type=content_type,
                run_id=args.run_id,
                fetched_at=fetched_at,
            )
            raw_path = raw_dir / f"{route['route_id']}.html"
            raw_path.write_bytes(raw)
            receipt["raw_path"] = raw_path.as_posix()
            healthy += 1
        except Exception as exc:  # source failure is evidence; authority remains fail-closed
            receipt = build_degraded_receipt(route, run_id=args.run_id, fetched_at=fetched_at, error=exc)
        validate_receipt(receipt, route)
        receipts.append(receipt)

    evidence = {
        "schema_version": "1.0",
        "adapter_id": ADAPTER_ID,
        "parser_version": PARSER_VERSION,
        "run_id": args.run_id,
        "fetched_at": fetched_at,
        "programme_family": PROGRAMME_FAMILY,
        "source_family": SOURCE_FAMILY,
        "authority_assignment_source_url": registry["authority_assignment_source_url"],
        "observation_state": "OPERATOR_WATCH",
        "health_state": "HEALTHY" if healthy == len(receipts) else ("DEGRADED" if healthy else "UNAVAILABLE"),
        "route_count": len(receipts),
        "healthy_route_count": healthy,
        "routes": receipts,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "requires_semantic_reconciliation": True,
        "missing_for_open_confirmation": list(MISSING_FOR_OPEN),
    }
    evidence_path = handoff_dir / "eea_romania_operator_watch.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "adapter_id": ADAPTER_ID,
        "route_count": len(receipts),
        "healthy_route_count": healthy,
        "health_state": evidence["health_state"],
        "open_call_authorized": False,
        "evidence_path": evidence_path.as_posix(),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
