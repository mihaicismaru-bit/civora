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
    "instagram": "id,permalink,timestamp,media_type,media_url,children{id,media_type,media_url}",
}


def _image_response_ok(http_status: int | None, content_type: str | None) -> bool:
    return bool(
        http_status in {200, 206}
        and str(content_type or "").lower().startswith("image/")
    )


def _read_remote_image(url: str, timeout: float = 12.0) -> dict[str, Any]:
    if not str(url or "").startswith("https://"):
        return {
            "status": "BLOCKED",
            "reason": "missing_or_non_https_remote_media_url",
            "readback_ok": False,
        }
    request = Request(
        url,
        headers={
            "User-Agent": "CIVORA-Core-v2-Auditor/1.0",
            "Range": "bytes=0-1023",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            http_status = int(getattr(response, "status", 0) or 0)
            final_url = response.geturl()
            content_type = str(response.headers.get("Content-Type") or "")
            response.read(1024)
    except HTTPError as exc:
        return {
            "status": "FAILED",
            "http_status": exc.code,
            "error": str(exc),
            "readback_ok": False,
        }
    except (URLError, TimeoutError) as exc:
        return {
            "status": "FAILED",
            "error": str(exc),
            "readback_ok": False,
        }
    ok = _image_response_ok(http_status, content_type)
    return {
        "status": "PASS" if ok else "FAILED",
        "http_status": http_status,
        "final_url": final_url,
        "content_type": content_type,
        "readback_ok": ok,
    }


def _instagram_image_candidates(payload: dict[str, Any]) -> list[dict[str, str]]:
    media_type = str(payload.get("media_type") or "").upper()
    if media_type == "IMAGE":
        media_url = str(payload.get("media_url") or "").strip()
        if media_url.startswith("https://"):
            return [
                {
                    "remote_id": str(payload.get("id") or ""),
                    "media_type": "IMAGE",
                    "media_url": media_url,
                    "location": "parent",
                }
            ]
        return []

    if media_type != "CAROUSEL_ALBUM":
        return []

    children = payload.get("children")
    child_rows = children.get("data") if isinstance(children, dict) else None
    candidates: list[dict[str, str]] = []
    for child in child_rows or []:
        if not isinstance(child, dict):
            continue
        child_type = str(child.get("media_type") or "").upper()
        media_url = str(child.get("media_url") or "").strip()
        if child_type != "IMAGE" or not media_url.startswith("https://"):
            continue
        candidates.append(
            {
                "remote_id": str(child.get("id") or ""),
                "media_type": "IMAGE",
                "media_url": media_url,
                "location": "carousel_child",
            }
        )
        if len(candidates) >= 10:
            break
    return candidates


def parse_meta_object(channel: str, remote_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actual_id = str(payload.get("id") or "")
    permalink = payload.get("permalink_url") or payload.get("permalink")
    ok = bool(actual_id == remote_id and permalink)
    return {
        "channel": channel,
        "remote_id": remote_id,
        "observed_remote_id": actual_id or None,
        "permalink": permalink,
        "media_type": payload.get("media_type") if channel == "instagram" else None,
        "remote_media_url": payload.get("media_url") if channel == "instagram" else None,
        "object_readback_ok": ok,
        "readback_ok": ok,
        "status": "PASS" if ok else "FAILED",
        "publication_authority": "NONE",
    }


def parse_meta_error_body(raw: bytes | str | None) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = raw
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"error_body_excerpt": text[:500]}
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return {"error_body_excerpt": text[:500]}
    return {
        "error_code": error.get("code"),
        "error_subcode": error.get("error_subcode"),
        "error_type": error.get("type"),
        "error_message": error.get("message"),
        "error_user_title": error.get("error_user_title"),
        "error_user_msg": error.get("error_user_msg"),
        "fbtrace_id": error.get("fbtrace_id"),
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
    except HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        detail = parse_meta_error_body(body)
        return {
            "channel": channel,
            "remote_id": remote_id,
            "status": "FAILED",
            "http_status": exc.code,
            "error": str(exc),
            **detail,
            "readback_ok": False,
            "publication_authority": "NONE",
        }
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "channel": channel,
            "remote_id": remote_id,
            "status": "FAILED",
            "error": str(exc),
            "readback_ok": False,
            "publication_authority": "NONE",
        }

    result = parse_meta_object(channel, remote_id, payload)
    if channel != "instagram":
        result["remote_visual_readback_ok"] = None
        result["remote_visual_identity_bound"] = None
        return result

    candidates = _instagram_image_candidates(payload)
    remote_media_results: list[dict[str, Any]] = []
    for candidate in candidates:
        readback = _read_remote_image(candidate["media_url"], timeout)
        remote_media_results.append({**candidate, **readback})

    passed_count = sum(1 for row in remote_media_results if row.get("readback_ok") is True)
    object_ok = result.get("object_readback_ok") is True
    remote_visual_ok = passed_count >= 1
    result["remote_media_results"] = remote_media_results
    result["remote_image_candidate_count"] = len(candidates)
    result["remote_image_readback_passed_count"] = passed_count
    result["remote_visual_readback_ok"] = remote_visual_ok
    result["remote_visual_identity_bound"] = False
    result["remote_visual_identity_note"] = (
        "remote Instagram image presence is externally read back, but transformed CDN bytes are not yet identity-bound to the approved Core v2 visual"
    )
    result["readback_ok"] = bool(object_ok and remote_visual_ok)
    result["status"] = "PASS" if result["readback_ok"] else "FAILED"
    if object_ok and not remote_visual_ok:
        result["reason"] = "instagram_remote_visual_readback_failed"
    return result


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
