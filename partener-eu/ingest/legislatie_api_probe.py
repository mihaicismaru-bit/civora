#!/usr/bin/env python3
"""P10 no-credential health probe for the official Portal Legislativ SOAP API.

The official service exposes a temporary GetToken operation without user
credentials. This adapter uses it only as transport/availability evidence. It
never stores or logs the returned token and never derives or promotes material
funding facts from the service automatically.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "partener-eu" / "ingest" / "state" / "legislatie_api_health.json"
ENDPOINTS = [
    "https://legislatie.just.ro/apiws/FreeWebService.svc",
    "http://legislatie.just.ro/apiws/FreeWebService.svc",
]
ACTION = "http://tempuri.org/IFreeWebService/GetToken"
UA = "PARTENER.EU-CIVORA-P10-Legislatie-API-Probe/1.0"
SOAP_BODY = (
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
    '<s:Header><Action s:mustUnderstand="1" '
    'xmlns="http://schemas.microsoft.com/ws/2005/05/addressing/none">'
    f"{ACTION}</Action></s:Header>"
    '<s:Body><GetToken xmlns="http://tempuri.org/" /></s:Body>'
    "</s:Envelope>"
).encode("utf-8")


def nowz() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(path: pathlib.Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def atomic_json(path: pathlib.Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_error(exc: Exception | str) -> str:
    text = str(exc)
    # Defensive redaction: token values are never expected in errors, but redact
    # long opaque values before persistence if a remote stack echoes one.
    return re.sub(r"\b[A-Za-z0-9+/=_-]{32,}\b", "[REDACTED_OPAQUE_VALUE]", text)[:1200]


def request_get(url: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xml,text/xml,*/*;q=0.7",
            "Cache-Control": "no-cache",
            "Connection": "close",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25, context=ssl.create_default_context()) as r:
            body = r.read(1_000_000)
            text = body.decode("utf-8", "ignore")
            markers = [m for m in ("FreeWebService", "GetToken", "Service") if m.lower() in text.lower()]
            return {
                "ok": 200 <= getattr(r, "status", 200) < 400 and bool(markers),
                "http_status": getattr(r, "status", 200),
                "final_url": r.geturl(),
                "bytes": len(body),
                "body_sha256": sha256(body),
                "markers_found": markers,
                "transport": "urllib-get",
                "error": None,
            }
    except Exception as exc:
        return {
            "ok": False,
            "http_status": getattr(exc, "code", None),
            "final_url": None,
            "bytes": 0,
            "body_sha256": None,
            "markers_found": [],
            "transport": "urllib-get",
            "error": safe_error(exc),
        }


def token_evidence_from_xml(body: bytes) -> dict[str, Any]:
    """Return non-secret evidence only; the token value is never returned."""
    token = None
    try:
        root = ET.fromstring(body)
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] == "GetTokenResult" and (node.text or "").strip():
                token = (node.text or "").strip()
                break
    except Exception as exc:
        return {
            "token_received": False,
            "token_length": 0,
            "token_sha256": None,
            "xml_valid": False,
            "error": safe_error(exc),
        }
    return {
        "token_received": bool(token),
        "token_length": len(token or ""),
        "token_sha256": sha256((token or "").encode("utf-8")) if token else None,
        "xml_valid": True,
        "error": None if token else "GetTokenResult missing or empty",
    }


def urllib_soap(url: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=SOAP_BODY,
        method="POST",
        headers={
            "User-Agent": UA,
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{ACTION}"',
            "Accept": "text/xml,application/soap+xml,*/*;q=0.5",
            "Connection": "close",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
            body = r.read(1_000_000)
            evidence = token_evidence_from_xml(body)
            return {
                **evidence,
                "ok": bool(evidence.get("token_received")),
                "http_status": getattr(r, "status", 200),
                "final_url": r.geturl(),
                "response_bytes": len(body),
                "transport": "urllib-soap",
            }
    except Exception as exc:
        return {
            "ok": False,
            "token_received": False,
            "token_length": 0,
            "token_sha256": None,
            "xml_valid": False,
            "http_status": getattr(exc, "code", None),
            "final_url": None,
            "response_bytes": 0,
            "transport": "urllib-soap",
            "error": safe_error(exc),
        }


def curl_soap(url: str) -> dict[str, Any]:
    cmd = [
        "curl", "-4", "--http1.1", "--silent", "--show-error", "--location",
        "--max-time", "35", "--user-agent", UA,
        "--header", "Content-Type: text/xml; charset=utf-8",
        "--header", f'SOAPAction: "{ACTION}"',
        "--data-binary", "@-", url,
    ]
    try:
        proc = subprocess.run(cmd, input=SOAP_BODY, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
        if proc.returncode != 0:
            return {
                "ok": False,
                "token_received": False,
                "token_length": 0,
                "token_sha256": None,
                "xml_valid": False,
                "http_status": None,
                "final_url": None,
                "response_bytes": len(proc.stdout),
                "transport": "curl-ipv4-soap",
                "error": safe_error(proc.stderr.decode("utf-8", "replace")),
            }
        evidence = token_evidence_from_xml(proc.stdout)
        return {
            **evidence,
            "ok": bool(evidence.get("token_received")),
            "http_status": 200 if evidence.get("token_received") else None,
            "final_url": url,
            "response_bytes": len(proc.stdout),
            "transport": "curl-ipv4-soap",
        }
    except Exception as exc:
        return {
            "ok": False,
            "token_received": False,
            "token_length": 0,
            "token_sha256": None,
            "xml_valid": False,
            "http_status": None,
            "final_url": None,
            "response_bytes": 0,
            "transport": "curl-ipv4-soap",
            "error": safe_error(exc),
        }


def probe_endpoint(url: str) -> dict[str, Any]:
    landing = request_get(url)
    attempts = [urllib_soap(url)]
    if not attempts[0].get("ok"):
        attempts.append(curl_soap(url))
    best = next((x for x in attempts if x.get("ok")), attempts[-1])
    return {
        "endpoint": url,
        "landing": landing,
        "token_probe": best,
        "attempts": [
            {
                "transport": x.get("transport"),
                "ok": bool(x.get("ok")),
                "http_status": x.get("http_status"),
                "error": x.get("error"),
            }
            for x in attempts
        ],
        "ok": bool(best.get("token_received")),
        "degraded": bool(landing.get("ok")) and not bool(best.get("token_received")),
    }


def main() -> int:
    observed_at = nowz()
    previous = load(OUT, {}) or {}
    probes = [probe_endpoint(url) for url in ENDPOINTS]
    best = next((x for x in probes if x.get("ok")), None)
    landing = next((x for x in probes if x.get("landing", {}).get("ok")), None)

    if best:
        status = "PASS"
        chosen = best
    elif landing:
        status = "DEGRADED_SOAP_TOKEN_UNAVAILABLE"
        chosen = landing
    else:
        status = "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED"
        chosen = probes[0]

    capability = {
        "service": "FreeWebService",
        "operation": "GetToken",
        "action": ACTION,
        "endpoint": chosen.get("endpoint"),
        "token_received": bool((chosen.get("token_probe") or {}).get("token_received")),
    }
    semantic_sha = sha256(json.dumps(capability, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    previous_success_at = previous.get("last_success_at")
    last_success_at = observed_at if status == "PASS" else previous_success_at

    report = {
        "schema_version": "1.0",
        "id": "SRC-LEGISLATIE-API",
        "tier": "T1",
        "name": "Portal Legislativ — API SOAP oficial fără credențiale",
        "observed_at": observed_at,
        "status": status,
        "selected_endpoint": chosen.get("endpoint"),
        "semantic_sha256": semantic_sha,
        "last_success_at": last_success_at,
        "last_known_good_preserved": status == "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED" and bool(previous_success_at),
        "probes": probes,
        "policy": {
            "credentials_required": False,
            "temporary_token_persisted": False,
            "temporary_token_logged": False,
            "material_facts_auto_promoted": False,
            "use": "transport-health-and-source-capability-evidence-only",
            "hash_change_action": "RESOLUTION_TASK_ONLY",
        },
    }
    atomic_json(OUT, report)
    print(json.dumps({
        "id": report["id"],
        "status": status,
        "selected_endpoint": report["selected_endpoint"],
        "token_received": capability["token_received"],
        "last_known_good_preserved": report["last_known_good_preserved"],
    }, ensure_ascii=False))
    # Availability degradation is persisted fail-closed and does not make the
    # adapter workflow fail. Code or policy regressions are enforced separately.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
