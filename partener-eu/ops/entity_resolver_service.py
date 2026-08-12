#!/usr/bin/env python3
"""PARTENER.EU Universal Applicant Resolver provider-chain service.

Stdlib-only reference service. It exposes a deterministic resolver contract and
merges multiple configured public/official providers without allowing a weaker
source to overwrite a stronger one silently.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "entity_providers.json"
SOURCE_RANK = {"A": 100, "B": 70, "C": 40, "D": 10}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def clean_cui(value: str) -> str:
    cui = re.sub(r"\D", "", value or "")
    if not 2 <= len(cui) <= 10:
        raise ValueError("invalid_cui")
    return cui


def load_config() -> Dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def request_json(url: str, timeout: float = 8.0) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "PARTENER.EU-CIVORA/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def dig(obj: Dict[str, Any], dotted: str) -> Any:
    cur: Any = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def normalize(provider: Dict[str, Any], cui: str, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    mapping = provider.get("mapping", {})
    if provider.get("success_path"):
        success = dig(raw, provider["success_path"])
        if success is False:
            return None
    out: Dict[str, Any] = {"cui": cui}
    for target, source in mapping.items():
        value = dig(raw, source) if isinstance(source, str) else None
        if value not in (None, "", [], {}):
            out[target] = value
    if len(out) == 1:
        return None
    out["sourceFacts"] = [{
        "label": provider["label"],
        "url": provider.get("official_url", ""),
        "tier": provider.get("tier", "C"),
        "checkedAt": now_iso(),
        "provider": provider["id"],
    }]
    out["confidence"] = provider.get("confidence", 0.7)
    out["_provider"] = provider["id"]
    out["_tier"] = provider.get("tier", "C")
    return out


def resolve_provider(provider: Dict[str, Any], cui: str) -> Optional[Dict[str, Any]]:
    if provider.get("status") != "READY":
        return None
    endpoint_env = provider.get("endpoint_env")
    endpoint = os.getenv(endpoint_env, "") if endpoint_env else provider.get("endpoint", "")
    if not endpoint:
        return None
    url = endpoint.replace("{cui}", cui)
    raw = request_json(url, timeout=float(provider.get("timeout_seconds", 8)))
    if raw is None:
        return None
    return normalize(provider, cui, raw)


def merge_records(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    ordered = sorted(records, key=lambda r: SOURCE_RANK.get(r.get("_tier", "D"), 0), reverse=True)
    if not ordered:
        return {}
    merged: Dict[str, Any] = {}
    provenance: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    field_source: Dict[str, str] = {}
    for record in ordered:
        provider = record.get("_provider", "unknown")
        for fact in record.get("sourceFacts", []):
            if fact not in provenance:
                provenance.append(fact)
        for key, value in record.items():
            if key.startswith("_") or key in {"sourceFacts", "confidence"} or value in (None, "", [], {}):
                continue
            if key not in merged:
                merged[key] = value
                field_source[key] = provider
            elif merged[key] != value:
                conflicts.append({"field": key, "kept": merged[key], "rejected": value, "keptProvider": field_source[key], "rejectedProvider": provider})
    merged["sourceFacts"] = provenance
    merged["conflicts"] = conflicts
    merged["checkedAt"] = now_iso()
    merged["confidence"] = max((float(r.get("confidence", 0)) for r in ordered), default=0)
    merged["resolver"] = "official-provider-chain"
    return merged


def classify_entity(profile: Dict[str, Any]) -> Dict[str, Any]:
    text = " ".join(str(profile.get(k, "")) for k in ("name", "legalName", "legalForm", "institutionType")).lower()
    if any(x in text for x in ("primăria", "primaria", "orașul", "orasul", "municipiul", "comuna")):
        profile.setdefault("type", "municipality")
        profile.setdefault("entityClass", "UAT")
    elif any(x in text for x in ("s.r.l", "srl", "s.a.", " sa ", "societate")):
        profile.setdefault("type", "enterprise")
        profile.setdefault("entityClass", "COMPANY")
    return profile


def resolve(cui_raw: str) -> Dict[str, Any]:
    cui = clean_cui(cui_raw)
    cfg = load_config()
    records = []
    for provider in cfg.get("providers", []):
        item = resolve_provider(provider, cui)
        if item:
            records.append(item)
    profile = classify_entity(merge_records(records))
    if not profile:
        return {"ok": False, "cui": cui, "status": "UNRESOLVED", "reason": "no_ready_provider_returned_data", "checkedAt": now_iso()}
    return {"ok": True, **profile}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        match = re.fullmatch(r"/resolve/(\d{2,10})", self.path.split("?", 1)[0])
        if not match:
            self.send_json(404, {"ok": False, "error": "not_found"})
            return
        try:
            payload = resolve(match.group(1))
            self.send_json(200 if payload.get("ok") else 404, payload)
        except ValueError:
            self.send_json(400, {"ok": False, "error": "invalid_cui"})

    def send_json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", os.getenv("PARTENER_ALLOWED_ORIGIN", "*"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("entity-resolver: " + fmt % args + "\n")


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1].isdigit():
        print(json.dumps(resolve(sys.argv[1]), ensure_ascii=False, indent=2))
        return
    host = os.getenv("PARTENER_ENTITY_HOST", "127.0.0.1")
    port = int(os.getenv("PARTENER_ENTITY_PORT", "8787"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
