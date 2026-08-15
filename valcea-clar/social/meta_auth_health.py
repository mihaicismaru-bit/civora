#!/usr/bin/env python3
"""Fail-closed Meta credential health probe for VÂLCEA CLAR.

The probe never prints or persists access-token material. It accepts a preferred
shared durable Page token and falls back to the legacy Facebook Page token so the
site engine can migrate without downtime.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "valcea-clar" / "social" / "meta_auth_state.json"
DEFAULT_GRAPH_VERSION = "v26.0"


def request_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "ValceaClar-MetaAuth/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
        except Exception:
            parsed = {}
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, dict):
            code = error.get("code")
            subcode = error.get("error_subcode")
            message = str(error.get("message", ""))
            if code == 190 and (subcode == 463 or "expired" in message.lower()):
                raise RuntimeError("META_TOKEN_EXPIRED") from exc
            raise RuntimeError(f"META_OAUTH_ERROR:{code}:{subcode or ''}") from exc
        raise RuntimeError(f"META_HTTP_{exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("META_TRANSPORT_ERROR") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("META_UNEXPECTED_PAYLOAD")
    return payload


def graph_get(version: str, path: str, token: str, fields: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"fields": fields, "access_token": token})
    return request_json(f"https://graph.facebook.com/{version}/{path.lstrip('/')}?{query}")


def write_outputs(values: dict[str, str]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def persist(payload: dict[str, Any]) -> None:
    STATE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def self_test() -> int:
    assert "access_token" not in json.dumps({"status": "VALID", "token_source": "durable_page"})
    print("VÂLCEA CLAR Meta auth health self-test: PASS")
    return 0


def main() -> int:
    if "--self-test" in os.sys.argv:
        return self_test()

    page_id = os.getenv("VALCEA_FB_PAGE_ID", "").strip()
    durable = os.getenv("VALCEA_META_PAGE_ACCESS_TOKEN", "").strip()
    legacy = os.getenv("VALCEA_FB_PAGE_ACCESS_TOKEN", "").strip()
    token = durable or legacy
    token_source = "durable_page" if durable else "legacy_page" if legacy else "none"
    version = os.getenv("VALCEA_FB_GRAPH_VERSION", DEFAULT_GRAPH_VERSION).strip() or DEFAULT_GRAPH_VERSION

    base: dict[str, Any] = {
        "schema_version": "1.0",
        "execution_owner": "civora_site_engine",
        "token_source": token_source,
        "page_id": page_id or None,
        "facebook_ready": False,
        "instagram_ready": False,
        "instagram_account_id": None,
        "secret_material_persisted": False,
    }

    if not page_id or not token:
        payload = {**base, "status": "BLOCKED_MISSING_CREDENTIALS"}
        persist(payload)
        write_outputs({"facebook_ready": "false", "instagram_ready": "false", "ig_account_id": ""})
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    try:
        page = graph_get(version, page_id, token, "id,name,instagram_business_account")
    except RuntimeError as exc:
        reason = str(exc)
        status = "BLOCKED_EXPIRED_TOKEN" if reason == "META_TOKEN_EXPIRED" else "BLOCKED_META_AUTH"
        payload = {**base, "status": status, "reason": reason}
        persist(payload)
        write_outputs({"facebook_ready": "false", "instagram_ready": "false", "ig_account_id": ""})
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if str(page.get("id", "")) != page_id:
        payload = {**base, "status": "BLOCKED_WRONG_ASSET"}
        persist(payload)
        write_outputs({"facebook_ready": "false", "instagram_ready": "false", "ig_account_id": ""})
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    ig = page.get("instagram_business_account")
    ig_id = str(ig.get("id", "")).strip() if isinstance(ig, dict) else ""
    payload = {
        **base,
        "status": "VALID",
        "page_name": page.get("name"),
        "facebook_ready": True,
        "instagram_ready": bool(ig_id),
        "instagram_account_id": ig_id or None,
    }
    persist(payload)
    write_outputs({
        "facebook_ready": "true",
        "instagram_ready": "true" if ig_id else "false",
        "ig_account_id": ig_id,
    })
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
