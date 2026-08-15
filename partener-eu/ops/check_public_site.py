#!/usr/bin/env python3
"""Verify the deployed PARTENER.EU document and critical boot assets.

The probe distinguishes public-content availability from the HTTPS closure gate,
uses non-stale markers from the current fallback shell, and records legacy
WordPress routing separately instead of treating a title match as success.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import ssl
import tempfile
import urllib.parse
import urllib.request
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "validation" / "deployment.json"
ENDPOINTS = [
    ("custom_https", "https://partener.eu/"),
    ("custom_http", "http://partener.eu/"),
    ("pages_origin", "https://mihaicismaru-bit.github.io/civora/"),
]
REQUIRED_MARKERS = {
    "brand": "PARTENER.EU",
    "boot_fallback": 'id="boot-fallback"',
    "hero": "Ce finanțare poți accesa și ce trebuie să faci acum",
    "product_definition": "Apeluri, condiții, documente, schimbări și riscuri",
    "critical_data_ref": 'src="data.js',
    "critical_app_ref": 'src="app.js',
    "decision_data_ref": 'src="decision-products.js',
    "decision_ui_ref": 'src="decision-intelligence-v2.js',
}
LEGACY_MARKERS = ("wp-content/", "wp-includes/", "wordpress.org", "wp-json")
UA = "PARTENER.EU-CIVORA-P10-Deployment-Probe/1.5"


class RedirectAudit(urllib.request.HTTPRedirectHandler):
    """Follow redirects while retaining enough evidence to audit transport."""

    def __init__(self) -> None:
        super().__init__()
        self.chain: list[dict[str, Any]] = []

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        self.chain.append({
            "http_status": code,
            "from_url": req.full_url,
            "to_url": newurl,
        })
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def atomic(path: pathlib.Path, obj: Any) -> None:
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


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def nowz() -> str:
    return now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def cache_bust(url: str, stamp: str) -> str:
    p = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
    q.append(("p10_probe", stamp))
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), p.fragment))


def request(url: str, limit: int = 1_000_000) -> tuple[bytes, int, str, dict[str, str], list[dict[str, Any]]]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/javascript,text/css,*/*;q=0.8",
            "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.5",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
            "Connection": "close",
        },
    )
    context = ssl.create_default_context()
    redirect_audit = RedirectAudit()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), redirect_audit)
    with opener.open(req, timeout=30) as r:
        body = r.read(limit)
        return body, getattr(r, "status", 200), r.geturl(), dict(r.headers.items()), redirect_audit.chain


def extract_asset(text: str, name: str, base: str) -> str | None:
    m = re.search(rf'''(?is)<script[^>]+src=["']([^"']*{re.escape(name)}[^"']*)["']''', text)
    if not m:
        return None
    return urllib.parse.urljoin(base, m.group(1))


def probe_asset(url: str | None, expected: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {"url": url, "ok": False, "http_status": None, "final_url": None, "bytes": 0, "sha256": None, "error": None}
    if not url:
        result["error"] = "asset reference missing"
        return result
    try:
        body, code, final, _, _ = request(url, 600_000)
        text = body.decode("utf-8", "ignore")
        result.update({
            "http_status": code,
            "final_url": final,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "expected_marker_found": any(marker in text for marker in expected),
        })
        result["ok"] = 200 <= code < 400 and len(body) > 100 and bool(result["expected_marker_found"])
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def probe(endpoint_id: str, url: str, stamp: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": endpoint_id,
        "url": url,
        "requested_url": cache_bust(url, stamp),
        "ok": False,
        "content_verified": False,
        "http_status": None,
        "final_url": None,
        "final_scheme": None,
        "redirect_chain": [],
        "content_type": None,
        "bytes": 0,
        "body_sha256": None,
        "title": None,
        "markers": {key: False for key in REQUIRED_MARKERS},
        "marker_ok": False,
        "legacy_origin_detected": False,
        "critical_assets_ok": False,
        "assets": {},
        "error": None,
    }
    try:
        body, code, final, headers, redirect_chain = request(result["requested_url"])
        text = body.decode("utf-8", "ignore")
        result.update({
            "http_status": code,
            "final_url": final,
            "final_scheme": urllib.parse.urlsplit(final).scheme.lower(),
            "redirect_chain": redirect_chain,
            "content_type": headers.get("Content-Type") or headers.get("content-type"),
            "bytes": len(body),
            "body_sha256": hashlib.sha256(body).hexdigest(),
        })
        title = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
        if title:
            result["title"] = re.sub(r"\s+", " ", title.group(1)).strip()[:300]
        result["markers"] = {key: marker in text for key, marker in REQUIRED_MARKERS.items()}
        result["marker_ok"] = all(result["markers"].values())
        low = text.lower()
        result["legacy_origin_detected"] = any(marker in low for marker in LEGACY_MARKERS)
        data_url = extract_asset(text, "data.js", final)
        app_url = extract_asset(text, "app.js", final)
        decision_data_url = extract_asset(text, "decision-products.js", final)
        decision_ui_url = extract_asset(text, "decision-intelligence-v2.js", final)
        result["assets"] = {
            "data.js": probe_asset(data_url, ("PARTENER_DATA", "window.PARTENER_DATA")),
            "app.js": probe_asset(app_url, ("function render", "render();", "document.getElementById('app')", 'document.getElementById("app")')),
            "decision-products.js": probe_asset(decision_data_url, ("PARTENER_DECISION_PRODUCTS", "decisionProducts")),
            "decision-intelligence-v2.js": probe_asset(decision_ui_url, ("Știri care explică", "Dosar complet", "Ce nu este confirmat")),
        }
        result["critical_assets_ok"] = all(x.get("ok") for x in result["assets"].values())
        result["content_verified"] = (
            200 <= code < 400
            and result["marker_ok"]
            and result["critical_assets_ok"]
            and not result["legacy_origin_detected"]
        )
        result["ok"] = result["content_verified"]
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def has_https_downgrade(endpoint: dict[str, Any]) -> bool:
    """Return true when an HTTPS request is redirected onto cleartext HTTP."""
    for hop in endpoint.get("redirect_chain") or []:
        source_scheme = urllib.parse.urlsplit(str(hop.get("from_url") or "")).scheme.lower()
        target_scheme = urllib.parse.urlsplit(str(hop.get("to_url") or "")).scheme.lower()
        if source_scheme == "https" and target_scheme == "http":
            return True
    requested_scheme = urllib.parse.urlsplit(str(endpoint.get("requested_url") or endpoint.get("url") or "")).scheme.lower()
    return requested_scheme == "https" and endpoint.get("final_scheme") == "http"


def assess_transport(by_id: dict[str, dict[str, Any]]) -> dict[str, bool]:
    """Evaluate the complete HTTPS closure contract, not only one 200 response."""
    https = by_id["custom_https"]
    http = by_id["custom_http"]
    pages = by_id["pages_origin"]

    custom_https_verified = bool(
        https.get("content_verified")
        and https.get("final_scheme") == "https"
        and not https.get("error")
        and not has_https_downgrade(https)
    )
    http_redirects_to_https = bool(
        http.get("redirect_chain")
        and http.get("content_verified")
        and http.get("final_scheme") == "https"
        and not has_https_downgrade(http)
    )
    pages_https_preserved = bool(
        pages.get("content_verified")
        and pages.get("final_scheme") == "https"
        and not has_https_downgrade(pages)
    )
    secure_transport_verified = bool(
        custom_https_verified and http_redirects_to_https and pages_https_preserved
    )
    return {
        "custom_https_verified": custom_https_verified,
        "http_redirects_to_https": http_redirects_to_https,
        "pages_https_preserved": pages_https_preserved,
        "secure_transport_verified": secure_transport_verified,
    }


def main() -> int:
    observed_at = nowz()
    stamp = observed_at.replace(":", "").replace("-", "")
    endpoints = [probe(endpoint_id, url, stamp) for endpoint_id, url in ENDPOINTS]
    by_id = {x["id"]: x for x in endpoints}
    https = by_id["custom_https"]
    http = by_id["custom_http"]
    pages = by_id["pages_origin"]
    transport = assess_transport(by_id)

    public_content_verified = any(x.get("content_verified") for x in endpoints)
    https_verified = transport["custom_https_verified"]
    secure_transport_verified = transport["secure_transport_verified"]
    http_content_verified = bool(http.get("content_verified") or pages.get("content_verified"))

    status = "PASS" if public_content_verified and secure_transport_verified else "FAIL"
    result = {
        "schema_version": "1.5",
        "observed_at": observed_at,
        "status": status,
        "public_content_verified": public_content_verified,
        "https_verified": https_verified,
        "secure_transport_verified": secure_transport_verified,
        "http_redirects_to_https": transport["http_redirects_to_https"],
        "pages_https_preserved": transport["pages_https_preserved"],
        "http_content_verified": http_content_verified,
        "https_closure_gate": "PASS" if secure_transport_verified else "PENDING_HTTPS_ENFORCEMENT_AND_SECURE_REDIRECTS",
        "content_origin": next((x["id"] for x in endpoints if x.get("content_verified")), None),
        "old_origin_detected": any(x.get("legacy_origin_detected") for x in endpoints),
        "endpoints": endpoints,
        "url": https.get("url"),
        "http_status": https.get("http_status"),
        "marker_ok": https.get("marker_ok"),
        "markers": https.get("markers"),
        "final_url": https.get("final_url"),
        "content_type": https.get("content_type"),
        "bytes": https.get("bytes"),
        "body_sha256": https.get("body_sha256"),
        "title": https.get("title"),
        "critical_assets_ok": https.get("critical_assets_ok"),
        "error": None,
    }
    if not public_content_verified:
        failures = [f"{x['id']}: required content/assets missing" for x in endpoints if not x.get("content_verified")]
        result["error"] = "; ".join(failures)
    elif not secure_transport_verified:
        result["error"] = "public content is available but HTTPS closure is incomplete"

    atomic(OUT, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
