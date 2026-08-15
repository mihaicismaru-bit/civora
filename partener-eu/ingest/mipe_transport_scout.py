#!/usr/bin/env python3
"""Probe multiple independent transports to the official MIPE canonical host.

This does not publish content. It discovers a usable retrieval path and records
transport evidence so the production ingestion engine can select a verified
relay without weakening source provenance.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import http.client
import json
import os
import platform
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.getenv("MIPE_SCOUT_OUT", ROOT / "partener-eu" / "ingest" / "state" / f"mipe_transport_scout_{platform.system().lower()}.json"))
TARGET = "https://mfe.gov.ro/pdds/despre-program-programare/"
UA = "PARTENER.EU-CIVORA-MIPE-TransportScout/1.0 (+https://partener.eu)"
MAX_BYTES = 1_500_000

URL_PROBES = [
    ("direct_https", TARGET),
    ("direct_home", "https://mfe.gov.ro/"),
    ("direct_www", "https://www.mfe.gov.ro/"),
    ("direct_http", "http://mfe.gov.ro/pdds/despre-program-programare/"),
    ("wordpress_rest", "https://mfe.gov.ro/wp-json/wp/v2/posts?per_page=3&_fields=link,date,modified,title,excerpt"),
    ("wordpress_feed", "https://mfe.gov.ro/feed/"),
    ("wordpress_sitemap", "https://mfe.gov.ro/wp-sitemap.xml"),
    ("known_static_pdf", "https://mfe.gov.ro/wp-content/uploads/2026/05/d83343bd5d614612898701c830d2a502.pdf"),
    ("official_opportunities", "https://oportunitati-ue.gov.ro/"),
    ("official_old_portal", "https://www.fonduri-ue.ro/"),
    ("jina_https", "https://r.jina.ai/https://mfe.gov.ro/pdds/despre-program-programare/"),
    ("jina_http", "https://r.jina.ai/http://mfe.gov.ro/pdds/despre-program-programare/"),
    ("google_translate", "https://mfe-gov-ro.translate.goog/pdds/despre-program-programare/?_x_tr_sl=ro&_x_tr_tl=en&_x_tr_hl=en"),
    ("vercel_relay", "https://partener-mipe-relay-mihaicismaru-6634s-projects.vercel.app/api/mipe?url=https%3A%2F%2Fmfe.gov.ro%2Fpdds%2Fdespre-program-programare%2F"),
]

DOH_ENDPOINTS = [
    ("google", "https://dns.google/resolve?name=mfe.gov.ro&type=A"),
    ("cloudflare", "https://cloudflare-dns.com/dns-query?name=mfe.gov.ro&type=A"),
]
KNOWN_IPS = ["193.151.29.21", "193.151.29.8"]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text_signature(data: bytes) -> dict[str, Any]:
    low = data[:MAX_BYTES].decode("utf-8", errors="ignore").lower()
    return {
        "hasMipe": "ministerul investi" in low or "mfe.gov.ro" in low,
        "hasPdds": "dezvoltare durabil" in low or "pdds" in low,
        "hasWordpress": "wp-content" in low or "wp-json" in low,
        "hasHtml": "<html" in low or "<!doctype" in low,
        "hasReaderSource": "url source:" in low,
        "preview": re.sub(r"\s+", " ", low[:350]),
    }


def fetch_url(name: str, url: str, timeout: int = 30) -> dict[str, Any]:
    started = time.monotonic()
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml,application/json,application/pdf,text/plain;q=0.9,*/*;q=0.5",
        "Accept-Language": "ro,en;q=0.7",
        "Cache-Control": "no-cache",
    }
    if "cloudflare-dns.com" in url:
        headers["Accept"] = "application/dns-json"
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
            data = response.read(MAX_BYTES)
            return {
                "name": name,
                "url": url,
                "ok": 200 <= getattr(response, "status", 200) < 400,
                "status": getattr(response, "status", 200),
                "finalUrl": response.geturl(),
                "contentType": response.headers.get("Content-Type", ""),
                "bytesRead": len(data),
                "sha256": digest(data),
                "elapsedMs": round((time.monotonic() - started) * 1000),
                "signature": text_signature(data),
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": name,
            "url": url,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsedMs": round((time.monotonic() - started) * 1000),
        }


def resolve_system() -> dict[str, Any]:
    started = time.monotonic()
    try:
        rows = socket.getaddrinfo("mfe.gov.ro", 443, type=socket.SOCK_STREAM)
        addresses = sorted({row[4][0] for row in rows})
        return {"ok": True, "addresses": addresses, "elapsedMs": round((time.monotonic() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "elapsedMs": round((time.monotonic() - started) * 1000)}


def parse_doh(result: dict[str, Any]) -> list[str]:
    if not result.get("ok"):
        return []
    try:
        req = urllib.request.Request(result["url"], headers={"User-Agent": UA, "Accept": "application/dns-json"})
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = json.loads(response.read(MAX_BYTES))
        return sorted({row.get("data") for row in payload.get("Answer", []) if row.get("type") == 1 and row.get("data")})
    except Exception:
        return []


def raw_tls_probe(ip: str, path: str = "/pdds/despre-program-programare/") -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {"ip": ip, "host": "mfe.gov.ro", "path": path}
    try:
        raw = socket.create_connection((ip, 443), timeout=12)
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(raw, server_hostname="mfe.gov.ro") as sock:
            cert = sock.getpeercert()
            request = (
                f"GET {path} HTTP/1.1\r\n"
                "Host: mfe.gov.ro\r\n"
                f"User-Agent: {UA}\r\n"
                "Accept: text/html,application/xhtml+xml,*/*;q=0.5\r\n"
                "Accept-Language: ro,en;q=0.7\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            sock.sendall(request)
            chunks = []
            total = 0
            while total < MAX_BYTES:
                block = sock.recv(min(65536, MAX_BYTES - total))
                if not block:
                    break
                chunks.append(block)
                total += len(block)
        wire = b"".join(chunks)
        header, _, body = wire.partition(b"\r\n\r\n")
        status_line = header.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
        m = re.match(r"HTTP/\S+\s+(\d+)", status_line)
        status = int(m.group(1)) if m else None
        result.update({
            "ok": status is not None and 200 <= status < 400,
            "status": status,
            "statusLine": status_line,
            "bytesRead": len(body),
            "sha256": digest(body),
            "signature": text_signature(body),
            "tlsSubject": cert.get("subject"),
            "tlsIssuer": cert.get("issuer"),
            "elapsedMs": round((time.monotonic() - started) * 1000),
        })
    except Exception as exc:  # noqa: BLE001
        result.update({"ok": False, "error": f"{type(exc).__name__}: {exc}", "elapsedMs": round((time.monotonic() - started) * 1000)})
    return result


def main() -> int:
    system = resolve_system()
    probes = [fetch_url(name, url) for name, url in URL_PROBES]
    doh_results = [fetch_url(f"doh_{name}", url, timeout=15) for name, url in DOH_ENDPOINTS]

    ips = set(KNOWN_IPS)
    ips.update(system.get("addresses", []) if system.get("ok") else [])
    for item in doh_results:
        ips.update(parse_doh(item))
    tls = [raw_tls_probe(ip) for ip in sorted(ip for ip in ips if ":" not in ip)]

    working = []
    for item in probes:
        sig = item.get("signature", {})
        if item.get("ok") and (sig.get("hasMipe") or sig.get("hasPdds") or item["name"] == "known_static_pdf"):
            working.append({"type": "url", "name": item["name"], "url": item["url"], "status": item.get("status"), "sha256": item.get("sha256")})
    for item in tls:
        sig = item.get("signature", {})
        if item.get("ok") and (sig.get("hasMipe") or sig.get("hasPdds")):
            working.append({"type": "raw_tls", "ip": item["ip"], "status": item.get("status"), "sha256": item.get("sha256")})

    payload = {
        "schema": "CIVORA_MIPE_TRANSPORT_SCOUT_V1",
        "observedAt": now(),
        "runner": {
            "os": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": sys.version,
            "githubRunnerName": os.getenv("RUNNER_NAME"),
            "githubRunnerEnvironment": os.getenv("RUNNER_ENVIRONMENT"),
        },
        "target": TARGET,
        "systemDns": system,
        "urlProbes": probes,
        "dohProbes": doh_results,
        "rawTlsProbes": tls,
        "workingTransports": working,
        "verdict": "WORKING_TRANSPORT_FOUND" if working else "NO_WORKING_TRANSPORT_ON_THIS_RUNNER",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
