from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FIELDS = {
    "facebook": "id,permalink_url,created_time",
    "instagram": "id,permalink,timestamp,media_type",
}


def parse_meta_object(channel: str, remote_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actual_id = str(payload.get("id") or "")
    permalink = payload.get("permalink_url") or payload.get("permalink")
    ok = bool(actual_id == remote_id and permalink)
    return {
        "channel": channel,
        "remote_id": remote_id,
        "observed_remote_id": actual_id or None,
        "permalink": permalink,
        "readback_ok": ok,
        "status": "PASS" if ok else "FAILED",
        "publication_authority": "NONE",
    }


def read_meta(channel: str, remote_id: str, token: str, graph_version: str = "v26.0", timeout: float = 12.0) -> dict[str, Any]:
    if channel not in FIELDS:
        raise ValueError(f"unsupported channel: {channel}")
    if not remote_id:
        raise ValueError("remote_id required")
    if not token:
        return {
            "channel": channel,
            "remote_id": remote_id,
            "status": "BLOCKED",
            "reason": "missing_readonly_meta_token",
            "readback_ok": False,
            "publication_authority": "NONE",
        }

    query = urlencode({"fields": FIELDS[channel], "access_token": token})
    url = f"https://graph.facebook.com/{graph_version}/{remote_id}?{query}"
    request = Request(url, headers={"User-Agent": "CIVORA-Core-v2-Auditor/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "channel": channel,
            "remote_id": remote_id,
            "status": "FAILED",
            "error": str(exc),
            "readback_ok": False,
            "publication_authority": "NONE",
        }
    return parse_meta_object(channel, remote_id, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Meta object auditor for Core v2")
    parser.add_argument("--channel", choices=sorted(FIELDS), required=True)
    parser.add_argument("--remote-id", required=True)
    parser.add_argument("--token-env", default="VALCEA_META_PAGE_ACCESS_TOKEN")
    parser.add_argument("--graph-version", default="v26.0")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = read_meta(args.channel, args.remote_id, os.getenv(args.token_env, ""), args.graph_version)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result.get("readback_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
