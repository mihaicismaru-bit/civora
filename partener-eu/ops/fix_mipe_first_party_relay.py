#!/usr/bin/env python3
"""Add an attested first-party raw-byte relay to MIPE ingestion.

The relay is transport only: the canonical factual source remains the official
MIPE URL. The client validates target, final host, raw body SHA-256, upstream
status and response size before the content can enter the extraction pipeline.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "ingest" / "mipe_resilient_ingest.py"
text = PATH.read_text(encoding="utf-8")
changed = False

replacements = [
    (
        "import datetime as dt\nimport hashlib",
        "import base64\nimport datetime as dt\nimport hashlib",
        "base64 import",
    ),
    (
        "import json\nimport re",
        "import json\nimport os\nimport re",
        "os import",
    ),
    (
        'INDEX_PATH = ROOT / "partener-eu" / "web" / "index.html"',
        'INDEX_PATH = ROOT / "partener-eu" / "web" / "index.html"\nMIPE_RELAY_URL = os.getenv("MIPE_RELAY_URL", "https://partener-mipe-relay-mihaicismaru-6634s-projects.vercel.app/api/mipe").strip()',
        "relay URL",
    ),
    (
        '''def reader_url(target: str) -> str:\n''',
        '''def fetch_first_party_relay(canonical: str) -> dict[str, Any]:\n    """Fetch raw official bytes through a controlled PARTENER.EU relay.\n\n    The relay cannot turn a third-party page into an official source. Both the\n    requested canonical URL and the relay-reported final URL must remain on the\n    official allowlist, and the body hash is recomputed locally.\n    """\n    if not MIPE_RELAY_URL:\n        return {"ok": False, "error": "relay_disabled"}\n    relay_target = MIPE_RELAY_URL + ("&" if "?" in MIPE_RELAY_URL else "?") + urllib.parse.urlencode({"url": canonical})\n    response = fetch(relay_target, timeout=30, attempts=1, accept="application/json")\n    if not response.get("ok"):\n        return {"ok": False, "error": response.get("error", "relay_unavailable"), "relay": MIPE_RELAY_URL}\n    try:\n        payload = json.loads(response["data"].decode("utf-8", errors="strict"))\n        requested = canonicalize(str(payload.get("canonicalUrl") or ""))\n        final_url = canonicalize(str(payload.get("finalUrl") or payload.get("canonicalUrl") or ""))\n        upstream_status = int(payload.get("upstreamStatus") or payload.get("status") or 0)\n        encoded = str(payload.get("bodyBase64") or "")\n        body = base64.b64decode(encoded, validate=True)\n        claimed_hash = str(payload.get("sha256") or "").lower()\n        local_hash = hashlib.sha256(body).hexdigest()\n        if requested != canonical:\n            raise ValueError("relay_canonical_mismatch")\n        if not final_url or not is_official(final_url):\n            raise ValueError("relay_final_url_not_official")\n        if not 200 <= upstream_status < 400:\n            raise ValueError(f"relay_upstream_status_{upstream_status}")\n        if not body or len(body) > MAX_BYTES:\n            raise ValueError("relay_body_size_invalid")\n        if not claimed_hash or claimed_hash != local_hash:\n            raise ValueError("relay_sha256_mismatch")\n        return {\n            "ok": True,\n            "status": upstream_status,\n            "url": final_url,\n            "content_type": str(payload.get("contentType") or "application/octet-stream"),\n            "data": body,\n            "relay": MIPE_RELAY_URL,\n            "relay_region": payload.get("relayRegion"),\n            "relay_fetched_at": payload.get("fetchedAt"),\n            "relay_sha256": local_hash,\n        }\n    except Exception as exc:  # noqa: BLE001 - persisted as transport evidence\n        return {"ok": False, "error": f"relay_validation:{type(exc).__name__}:{exc}", "relay": MIPE_RELAY_URL}\n\n\ndef reader_url(target: str) -> str:\n''',
        "relay validator",
    ),
    (
        '''    return None, {\n        "target": canonical,\n        "ok": False,\n        "transport": "direct-only",\n        "directError": direct.get("error"),\n        "policy": "search-discovery-only-when-direct-unavailable",\n    }\n''',
        '''    relay = fetch_first_party_relay(canonical)\n    if relay.get("ok"):\n        content_type = str(relay.get("content_type", "")).lower()\n        evidence = {\n            "target": canonical,\n            "ok": True,\n            "transport": "direct-canonical-via-first-party-relay",\n            "directError": direct.get("error"),\n            "relay": relay.get("relay"),\n            "relayRegion": relay.get("relay_region"),\n            "relayFetchedAt": relay.get("relay_fetched_at"),\n            "sha256": relay.get("relay_sha256"),\n        }\n        try:\n            if "json" in content_type:\n                return {"json": json.loads(relay["data"].decode("utf-8", errors="replace")), "canonical": canonical}, evidence\n            if "xml" in content_type or relay["data"].lstrip().startswith(b"<?xml"):\n                return {"xml": relay["data"], "canonical": canonical}, evidence\n            parsed = parse_html(relay["data"])\n            parsed["canonical"] = canonicalize(relay.get("url") or canonical) or canonical\n            return parsed, evidence\n        except Exception as exc:  # noqa: BLE001\n            relay = {"ok": False, "error": f"relay_parse:{type(exc).__name__}:{exc}", "relay": relay.get("relay")}\n\n    return None, {\n        "target": canonical,\n        "ok": False,\n        "transport": "direct+first-party-relay",\n        "directError": direct.get("error"),\n        "relayError": relay.get("error"),\n        "relay": relay.get("relay"),\n        "policy": "search-discovery-only-when-official-byte-transports-unavailable",\n    }\n''',
        "relay fallback",
    ),
    (
        '    tier = "T1" if transport.startswith("direct") else "T1_PROXY_TRANSPORT"',
        '    tier = "T1_RELAY_ATTESTED" if "first-party-relay" in transport else ("T1" if transport.startswith("direct") else "T1_PROXY_TRANSPORT")',
        "relay provenance tier",
    ),
]

for old, new, label in replacements:
    if new in text:
        print(f"MIPE first-party relay {label}: already applied")
    elif old in text:
        text = text.replace(old, new, 1)
        changed = True
        print(f"MIPE first-party relay {label}: applied")
    else:
        raise SystemExit(f"Expected MIPE relay pattern not found for {label}; refusing blind edit")

if changed:
    PATH.write_text(text, encoding="utf-8")
