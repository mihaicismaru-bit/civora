#!/usr/bin/env python3
"""PARTENER.EU local research acquisition agent.

Acquisition only. It cannot authorize call status, deadline, budget, eligibility,
publication, distribution, or canonical corpus mutation.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html as html_lib
import json
import mimetypes
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

AGENT_VERSION = "1.0.0"
SCHEMA = "PARTENER_EU_LOCAL_RESEARCH_AGENT_V1"
USER_AGENT = "PARTENER.EU-LocalResearchAgent/1.0 (+acquisition-only)"
AUTH_FLAGS = (
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
    "canonical_corpus_mutation",
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data and data.strip():
            self.parts.append(data)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_text(data: bytes, content_type: str | None) -> str:
    text = data.decode("utf-8", errors="replace")
    if content_type and "html" in content_type.casefold():
        parser = _TextExtractor()
        try:
            parser.feed(text)
            text = " ".join(parser.parts)
        except Exception:
            pass
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def semantic_hash(data: bytes, content_type: str | None) -> str:
    return hashlib.sha256(canonical_text(data, content_type).encode("utf-8")).hexdigest()


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")[:120]


def validate_source(source: dict[str, Any]) -> None:
    if not re.fullmatch(r"[A-Z0-9_.-]{3,100}", str(source.get("source_id") or "")):
        raise ValueError("invalid source_id")
    url = str(source.get("url") or "")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"source must be https: {url}")
    allowed = {str(x).casefold() for x in source.get("allow_hosts", [])}
    if not allowed or parsed.hostname.casefold() not in allowed:
        raise ValueError(f"host not allowlisted for {source['source_id']}")
    if source.get("observation_state") in {"OPEN_CALL", "CLOSED_CALL"}:
        raise ValueError("local research agent cannot be configured with material call states")


def _http_fetch(source: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        source["url"],
        headers={"User-Agent": USER_AGENT, "Accept": source.get("accept", "text/html,application/json;q=0.9,*/*;q=0.5")},
    )
    context = ssl.create_default_context()
    timeout = float(source.get("timeout_seconds", 45))
    max_bytes = int(source.get("max_bytes", 5_000_000))
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        final_url = resp.geturl()
        parsed = urllib.parse.urlparse(final_url)
        if parsed.scheme != "https" or parsed.hostname.casefold() not in {h.casefold() for h in source["allow_hosts"]}:
            raise RuntimeError("redirect escaped official authority allowlist")
        data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise RuntimeError("response exceeded bounded max_bytes")
        return {
            "data": data,
            "status": int(getattr(resp, "status", 200)),
            "content_type": resp.headers.get("Content-Type", "application/octet-stream"),
            "final_url": final_url,
            "strategy_used": "http",
        }


def _browser_fetch(source: dict[str, Any]) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("playwright is not installed") from exc
    timeout_ms = int(float(source.get("timeout_seconds", 60)) * 1000)
    wait_ms = int(source.get("browser_wait_ms", 1500))
    allowed = {h.casefold() for h in source["allow_hosts"]}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(ignore_https_errors=False, locale=source.get("locale", "ro-RO"))
            page = context.new_page()
            response = page.goto(source["url"], wait_until="domcontentloaded", timeout=timeout_ms)
            if wait_ms:
                page.wait_for_timeout(wait_ms)
            final_url = page.url
            parsed = urllib.parse.urlparse(final_url)
            if parsed.scheme != "https" or parsed.hostname.casefold() not in allowed:
                raise RuntimeError("browser redirect escaped official authority allowlist")
            content = page.content().encode("utf-8")
            max_bytes = int(source.get("max_bytes", 8_000_000))
            if len(content) > max_bytes:
                raise RuntimeError("rendered DOM exceeded bounded max_bytes")
            return {
                "data": content,
                "status": int(response.status if response else 200),
                "content_type": "text/html; charset=utf-8",
                "final_url": final_url,
                "strategy_used": "browser",
            }
        finally:
            browser.close()


def fetch_source(source: dict[str, Any]) -> dict[str, Any]:
    validate_source(source)
    strategy = source.get("strategy", "auto")
    errors: list[str] = []
    methods = [strategy] if strategy in {"http", "browser"} else ["http", "browser"]
    for method in methods:
        try:
            result = _http_fetch(source) if method == "http" else _browser_fetch(source)
            body = result["data"]
            ctype = result["content_type"]
            text = canonical_text(body, ctype)
            required_all = [str(x).casefold() for x in source.get("markers_all", [])]
            required_any = [str(x).casefold() for x in source.get("markers_any", [])]
            if required_all and not all(marker in text for marker in required_all):
                raise RuntimeError("required marker group ALL did not match")
            if required_any and not any(marker in text for marker in required_any):
                raise RuntimeError("required marker group ANY did not match")
            result["raw_sha256"] = sha256_bytes(body)
            result["semantic_fingerprint"] = semantic_hash(body, ctype)
            result["bytes"] = len(body)
            result["health_state"] = "HEALTHY"
            result["lkg_required"] = False
            result["errors"] = errors
            return result
        except Exception as exc:
            errors.append(f"{method}:{type(exc).__name__}:{exc}")
    return {
        "data": b"",
        "status": None,
        "content_type": None,
        "final_url": None,
        "strategy_used": None,
        "raw_sha256": None,
        "semantic_fingerprint": None,
        "bytes": 0,
        "health_state": "DEGRADED_TRANSPORT_OR_VALIDATION",
        "lkg_required": True,
        "errors": errors,
    }


def evidence_row(source: dict[str, Any], result: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if result["health_state"] == "HEALTHY":
        if previous and previous.get("semantic_fingerprint") == result["semantic_fingerprint"] and previous.get("health_state") == "HEALTHY":
            change_kind = "NO_CHANGE"
        elif previous and previous.get("health_state") == "HEALTHY":
            change_kind = "CONTENT_CHANGED_NON_AUTHORIZING"
        elif previous:
            change_kind = "SOURCE_HEALTH_RECOVERED_NON_AUTHORIZING"
        else:
            change_kind = "BASELINE_CAPTURED_NON_AUTHORIZING"
    else:
        change_kind = "SOURCE_DEGRADED_NON_AUTHORIZING"
    row = {
        "source_id": source["source_id"],
        "source_family": source.get("source_family"),
        "programme_family": source.get("programme_family"),
        "authority_class": source.get("authority_class"),
        "observation_state": source.get("observation_state", "SOURCE_DISCOVERY_ONLY"),
        "requested_url": source["url"],
        "final_url": result.get("final_url"),
        "fetched_at": utc_now(),
        "strategy_requested": source.get("strategy", "auto"),
        "strategy_used": result.get("strategy_used"),
        "http_status": result.get("status"),
        "content_type": result.get("content_type"),
        "bytes": result.get("bytes"),
        "raw_sha256": result.get("raw_sha256"),
        "semantic_fingerprint": result.get("semantic_fingerprint"),
        "health_state": result["health_state"],
        "lkg_required": result["lkg_required"],
        "change_kind": change_kind,
        "errors": result.get("errors", []),
        "market_intelligence_only": True,
        "publication_effect": "NONE",
        "missing_for_material_use": [
            "PARTENER_ENGINE_SEMANTIC_RECONCILIATION",
            "EXACT_CALL_OR_TOPIC_IDENTITY_WHEN_APPLICABLE",
            "FRESH_EXACT_OFFICIAL_ENDPOINT_WHEN_APPLICABLE",
            "FIELD_SCOPED_MATERIAL_ADMISSION",
        ],
    }
    row.update({flag: False for flag in AUTH_FLAGS})
    return row


def data_root(local_cfg: dict[str, Any]) -> Path:
    configured = local_cfg.get("data_root")
    if configured:
        return Path(os.path.expandvars(str(configured))).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        return base / "PARTENER.EU" / "research-agent"
    return Path.home() / ".local" / "share" / "partener-eu-research-agent"


def fetch_remote_json(repo: str, branch: str, path: str, token: str | None = None) -> Any:
    url = f"https://raw.githubusercontent.com/{repo}/{urllib.parse.quote(branch, safe='')}/{path}"
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as resp:
        return json.loads(resp.read(2_000_000).decode("utf-8"))


def github_api(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context()) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        payload_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {url} failed {exc.code}: {payload_text[:500]}") from exc


def ensure_evidence_branch(repo: str, branch: str, base_branch: str, token: str) -> None:
    api = f"https://api.github.com/repos/{repo}"
    try:
        github_api("GET", f"{api}/git/ref/heads/{urllib.parse.quote(branch, safe='')}", token)
        return
    except RuntimeError as exc:
        if "failed 404" not in str(exc):
            raise
    base = github_api("GET", f"{api}/git/ref/heads/{urllib.parse.quote(base_branch, safe='')}", token)
    sha = base["object"]["sha"]
    github_api("POST", f"{api}/git/refs", token, {"ref": f"refs/heads/{branch}", "sha": sha})


def upload_contents(repo: str, branch: str, path: str, data: bytes, token: str, message: str) -> None:
    api_url = f"https://api.github.com/repos/{repo}/contents/{'/'.join(urllib.parse.quote(x, safe='') for x in path.split('/'))}"
    existing_sha = None
    try:
        current = github_api("GET", f"{api_url}?ref={urllib.parse.quote(branch, safe='')}", token)
        existing_sha = current.get("sha")
    except RuntimeError as exc:
        if "failed 404" not in str(exc):
            raise
    payload = {"message": message, "content": base64.b64encode(data).decode("ascii"), "branch": branch}
    if existing_sha:
        payload["sha"] = existing_sha
    github_api("PUT", api_url, token, payload)


def publish_bundle(zip_path: Path, manifest: dict[str, Any], local_cfg: dict[str, Any]) -> dict[str, Any]:
    token = os.environ.get("PARTENER_RESEARCH_GITHUB_TOKEN")
    if not token:
        return {"published": False, "reason": "PARTENER_RESEARCH_GITHUB_TOKEN_NOT_SET"}
    repo = local_cfg["repository"]
    evidence_branch = local_cfg.get("evidence_branch", "partener-local-research-evidence")
    base_branch = local_cfg.get("evidence_base_branch", "main")
    ensure_evidence_branch(repo, evidence_branch, base_branch, token)
    day = manifest["started_at"][:10]
    run_id = manifest["run_id"]
    bundle_path = f"partener-eu/local-research-evidence/{day}/{run_id}.zip"
    latest_path = "partener-eu/local-research-evidence/latest.json"
    upload_contents(repo, evidence_branch, bundle_path, zip_path.read_bytes(), token, f"PARTENER local research evidence {run_id}")
    latest = {
        "schema": "PARTENER_EU_LOCAL_RESEARCH_LATEST_V1",
        "run_id": run_id,
        "bundle_path": bundle_path,
        "bundle_sha256": sha256_bytes(zip_path.read_bytes()),
        "created_at": utc_now(),
        "material_fact_use": False,
        "publication_effect": "NONE",
    }
    upload_contents(repo, evidence_branch, latest_path, (json.dumps(latest, sort_keys=True, indent=2) + "\n").encode("utf-8"), token, f"Update PARTENER local research latest {run_id}")
    return {"published": True, "branch": evidence_branch, "bundle_path": bundle_path, "latest_path": latest_path}


def read_requests(base_dir: Path, local_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    local = load_json(base_dir / "control" / "requests.json", {"requests": []}) or {"requests": []}
    token = os.environ.get("PARTENER_RESEARCH_GITHUB_TOKEN")
    try:
        remote = fetch_remote_json(local_cfg["repository"], local_cfg.get("code_branch", "main"), "partener-eu/local-research-agent/control/requests.json", token)
        return list(remote.get("requests") or [])
    except Exception:
        return list(local.get("requests") or [])


def run_agent(base_dir: Path, publish: bool = False, source_ids: set[str] | None = None) -> dict[str, Any]:
    local_cfg = load_json(base_dir / "agent.local.json", {}) or {}
    sources_doc = load_json(base_dir / "sources.json", {}) or {}
    sources = [dict(x) for x in sources_doc.get("sources", []) if x.get("enabled", True)]
    for source in sources:
        validate_source(source)
    root = data_root(local_cfg)
    state_path = root / "state.json"
    state = load_json(state_path, {"sources": {}, "completed_request_ids": []}) or {"sources": {}, "completed_request_ids": []}
    completed = set(state.get("completed_request_ids", []))
    request_ids: list[str] = []
    requested_sources: set[str] = set()
    for request in read_requests(base_dir, local_cfg):
        rid = str(request.get("request_id") or "")
        if not rid or rid in completed or request.get("enabled", True) is False:
            continue
        request_ids.append(rid)
        requested_sources.update(str(x) for x in request.get("source_ids", []))
    if source_ids:
        requested_sources.update(source_ids)
    if requested_sources:
        sources = [x for x in sources if x["source_id"] in requested_sources]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + hashlib.sha256(os.urandom(16)).hexdigest()[:8]
    run_dir = root / "runs" / run_id
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    new_state_sources = dict(state.get("sources", {}))
    for source in sources:
        sid = source["source_id"]
        result = fetch_source(source)
        previous = state.get("sources", {}).get(sid)
        row = evidence_row(source, result, previous)
        if result.get("data"):
            suffix = ".html" if "html" in str(result.get("content_type") or "").casefold() else mimetypes.guess_extension(str(result.get("content_type") or "").split(";", 1)[0]) or ".bin"
            raw_path = raw_dir / f"{safe_id(sid)}{suffix}"
            raw_path.write_bytes(result["data"])
            row["raw_path"] = str(raw_path.relative_to(run_dir)).replace("\\", "/")
        else:
            row["raw_path"] = None
        rows.append(row)
        new_state_sources[sid] = {
            "health_state": row["health_state"],
            "semantic_fingerprint": row["semantic_fingerprint"],
            "raw_sha256": row["raw_sha256"],
            "fetched_at": row["fetched_at"],
        }
    manifest = {
        "schema": SCHEMA,
        "agent_version": AGENT_VERSION,
        "run_id": run_id,
        "started_at": utc_now(),
        "source_registry_version": sources_doc.get("version"),
        "source_registry_sha256": sha256_bytes((base_dir / "sources.json").read_bytes()),
        "source_count": len(rows),
        "healthy_source_count": sum(1 for x in rows if x["health_state"] == "HEALTHY"),
        "degraded_source_count": sum(1 for x in rows if x["health_state"] != "HEALTHY"),
        "changed_source_count": sum(1 for x in rows if x["change_kind"] not in {"NO_CHANGE", "BASELINE_CAPTURED_NON_AUTHORIZING"}),
        "fulfilled_request_ids": request_ids,
        "evidence": rows,
        "market_intelligence_only": True,
        "publication_effect": "NONE",
        "semantic_reconciliation_required_by_partener_engine": True,
    }
    manifest.update({flag: False for flag in AUTH_FLAGS})
    write_json(run_dir / "manifest.json", manifest)
    zip_path = root / "bundles" / f"{run_id}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(run_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(run_dir).as_posix())
    manifest["bundle_sha256"] = sha256_bytes(zip_path.read_bytes())
    write_json(run_dir / "manifest.json", manifest)
    state["sources"] = new_state_sources
    state["completed_request_ids"] = sorted(completed.union(request_ids))[-500:]
    state["last_run_id"] = run_id
    state["last_run_at"] = utc_now()
    write_json(state_path, state)
    publish_result = publish_bundle(zip_path, manifest, local_cfg) if publish else {"published": False, "reason": "PUBLISH_DISABLED"}
    write_json(run_dir / "publish-result.json", publish_result)
    return {"manifest": manifest, "zip_path": str(zip_path), "publish": publish_result, "data_root": str(root)}


def doctor(base_dir: Path) -> int:
    issues: list[str] = []
    local_cfg = load_json(base_dir / "agent.local.json", {}) or {}
    try:
        sources = load_json(base_dir / "sources.json", {}) or {}
        for source in sources.get("sources", []):
            validate_source(source)
    except Exception as exc:
        issues.append(f"source_registry:{exc}")
    try:
        import playwright  # noqa: F401
    except Exception:
        issues.append("playwright_python_missing")
    if not local_cfg.get("repository"):
        issues.append("agent.local.json repository missing")
    if not os.environ.get("PARTENER_RESEARCH_GITHUB_TOKEN"):
        issues.append("PARTENER_RESEARCH_GITHUB_TOKEN not set; publishing/remote queue auth may be unavailable")
    print(json.dumps({"ok": not [x for x in issues if "TOKEN" not in x], "issues": issues, "data_root": str(data_root(local_cfg))}, indent=2))
    return 0 if not [x for x in issues if "TOKEN" not in x] else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    runp = sub.add_parser("run")
    runp.add_argument("--publish", action="store_true")
    runp.add_argument("--source-id", action="append", default=[])
    sub.add_parser("doctor")
    args = parser.parse_args()
    base_dir = Path(__file__).resolve().parent
    if args.cmd == "doctor":
        return doctor(base_dir)
    result = run_agent(base_dir, publish=args.publish, source_ids=set(args.source_id or []))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
