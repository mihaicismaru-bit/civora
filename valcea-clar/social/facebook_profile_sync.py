#!/usr/bin/env python3
"""Fail-safe VÂLCEA CLAR Facebook Page profile synchronizer.

Synchronizes only non-sensitive, already-canonical newsroom profile fields:
Facebook bio/about, website and editorial email. It deliberately never invents
or mutates phone, address, category, Page name, roles or permissions.

Each field is updated independently and verified by read-back. Unsupported or
permission-gated fields are recorded as manual requirements rather than guessed.
No token value is printed or persisted.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
SOCIAL = VC / "social"
sys.path.insert(0, str(SOCIAL))

import facebook_publish as legacy  # noqa: E402

PROFILE = SOCIAL / "profile_presence_system.json"
LEGAL = VC / "site" / "legal" / "legal_pages.json"
STATE = SOCIAL / "facebook_profile_state.json"
DEFAULT_PAGE_ID = "1234360446430980"
DEFAULT_GRAPH_VERSION = "v26.0"
LIVE_ENV = "VALCEA_FB_PROFILE_LIVE_ENABLED"


class ProfileSyncError(RuntimeError):
    pass


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProfileSyncError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def targets() -> dict[str, Any]:
    presence = load(PROFILE)
    legal = load(LEGAL)
    facebook = (presence.get("platforms") or {}).get("facebook") or {}
    site_url = str((presence.get("global_rules") or {}).get("site_url") or "").strip()
    email = str(legal.get("contact_email") or "").strip()
    if not site_url.startswith("https://valceaclar.ro"):
        raise ProfileSyncError("canonical Facebook website target is not valceaclar.ro")
    if not email.endswith("@valceaclar.ro"):
        raise ProfileSyncError("canonical editorial email target is not @valceaclar.ro")
    values = {
        "bio": str(facebook.get("short_bio") or "").strip(),
        "about": str(facebook.get("about") or "").strip(),
        "website": site_url,
        "emails": [email],
    }
    if not values["bio"] or not values["about"]:
        raise ProfileSyncError("Facebook canonical bio/about is missing")
    return values


def supplied_token() -> str:
    token = (
        os.environ.get("VALCEA_META_PAGE_ACCESS_TOKEN", "").strip()
        or os.environ.get("VALCEA_FB_PAGE_ACCESS_TOKEN", "").strip()
    )
    if not token:
        raise ProfileSyncError("Meta/Facebook Page access token is missing")
    return token


def graph_request(
    *,
    url: str,
    data: dict[str, Any] | None = None,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    encoded = None
    method = "GET"
    headers = {"User-Agent": "ValceaClar-Facebook-Profile/1.1"}
    if data is not None:
        encoded = urllib.parse.urlencode(data).encode("utf-8")
        method = "POST"
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=encoded, method=method, headers=headers)
    try:
        with request_fn(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ProfileSyncError(f"Graph HTTP {exc.code}: {detail[:800]}") from exc
    except urllib.error.URLError as exc:
        raise ProfileSyncError(f"Graph transport error: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise ProfileSyncError("Graph returned a non-object response")
    if payload.get("error"):
        raise ProfileSyncError(f"Graph error: {str(payload['error'])[:800]}")
    return payload


def read_field(
    *,
    page_id: str,
    token: str,
    version: str,
    field: str,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[bool, Any, str]:
    query = urllib.parse.urlencode({"fields": f"id,name,{field}", "access_token": token})
    try:
        payload = graph_request(
            url=f"https://graph.facebook.com/{version}/{page_id}?{query}",
            request_fn=request_fn,
        )
        if str(payload.get("id") or "") != page_id:
            return False, None, "page_identity_mismatch"
        return True, payload.get(field), "readable"
    except Exception as exc:
        return False, None, str(exc)[:800]


def encode_field_value(field: str, value: Any) -> str:
    if field == "emails":
        return json.dumps(list(value), ensure_ascii=False, separators=(",", ":"))
    return str(value)


def apply_field(
    *,
    page_id: str,
    token: str,
    version: str,
    field: str,
    value: Any,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[bool, str]:
    try:
        payload = graph_request(
            url=f"https://graph.facebook.com/{version}/{page_id}",
            data={field: encode_field_value(field, value), "access_token": token},
            request_fn=request_fn,
        )
    except Exception as exc:
        return False, str(exc)[:800]
    if payload.get("success") is True or str(payload.get("id") or "") == page_id:
        return True, "accepted"
    return False, f"unexpected_response:{str(payload)[:600]}"


def comparable(field: str, value: Any) -> Any:
    if field == "emails":
        if isinstance(value, list):
            return sorted(str(v).strip().casefold() for v in value if str(v).strip())
        if value is None:
            return []
        return [str(value).strip().casefold()]
    return " ".join(str(value or "").split()).strip().casefold()


def run(
    *,
    apply: bool,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
    token_resolver: Callable[[str, str, str], tuple[str, dict[str, Any]]] = legacy.resolve_page_token,
) -> dict[str, Any]:
    desired = targets()
    page_id = os.environ.get("VALCEA_FB_PAGE_ID", DEFAULT_PAGE_ID).strip() or DEFAULT_PAGE_ID
    version = os.environ.get("VALCEA_FB_GRAPH_VERSION", DEFAULT_GRAPH_VERSION).strip() or DEFAULT_GRAPH_VERSION
    supplied = supplied_token()

    if apply and os.environ.get(LIVE_ENV, "").strip().lower() != "true":
        raise ProfileSyncError(f"{LIVE_ENV} must be true for --apply")

    # The durable Meta secret can be a user/identity token. Publishing already
    # resolves it to the actual Page token; profile metadata mutations must do
    # the same or Meta correctly rejects them with OAuth error #210.
    try:
        page_token, identity = token_resolver(page_id, supplied, version)
    except Exception as exc:
        raise ProfileSyncError(f"Facebook Page identity/token validation failed: {exc}") from exc
    if not page_token:
        raise ProfileSyncError("Facebook Page token resolver returned an empty token")

    fields: dict[str, Any] = {}
    changed = 0
    verified = 0
    manual = 0

    for field, target in desired.items():
        readable, before, read_reason = read_field(
            page_id=page_id, token=page_token, version=version, field=field, request_fn=request_fn
        )
        row: dict[str, Any] = {
            "target": target,
            "readable": readable,
            "before": before if readable else None,
            "read_reason": read_reason,
            "mutation_attempted": False,
            "mutation_accepted": False,
            "verified": False,
        }
        if readable and comparable(field, before) == comparable(field, target):
            row["status"] = "ALREADY_CURRENT"
            row["verified"] = True
            verified += 1
            fields[field] = row
            continue
        if not apply:
            row["status"] = "DRY_RUN_CHANGE_REQUIRED" if readable else "DRY_RUN_MANUAL_OR_PERMISSION_CHECK"
            fields[field] = row
            continue

        row["mutation_attempted"] = True
        accepted, reason = apply_field(
            page_id=page_id,
            token=page_token,
            version=version,
            field=field,
            value=target,
            request_fn=request_fn,
        )
        row["mutation_accepted"] = accepted
        row["mutation_reason"] = reason
        if not accepted:
            row["status"] = "MANUAL_REQUIRED"
            manual += 1
            fields[field] = row
            continue

        readable_after, after, after_reason = read_field(
            page_id=page_id, token=page_token, version=version, field=field, request_fn=request_fn
        )
        row["after"] = after if readable_after else None
        row["verify_reason"] = after_reason
        if readable_after and comparable(field, after) == comparable(field, target):
            row["status"] = "UPDATED_AND_VERIFIED"
            row["verified"] = True
            verified += 1
            changed += 1
        else:
            row["status"] = "MANUAL_REQUIRED"
            manual += 1
        fields[field] = row

    if not apply:
        status = "DRY_RUN"
    elif manual:
        status = "PARTIAL_MANUAL_REQUIRED"
    else:
        status = "SYNCED"
    result = {
        "schema_version": "1.1",
        "status": status,
        "page_id": page_id,
        "page_name": identity.get("page_name"),
        "token_source": identity.get("source"),
        "graph_version": version,
        "fields": fields,
        "updated_fields": changed,
        "verified_fields": verified,
        "manual_fields": manual,
        "intentionally_untouched": ["name", "category", "phone", "location", "roles", "permissions", "cover"],
        "credentials_logged": False,
        "credentials_persisted": False,
    }
    return result


def self_test() -> int:
    assert comparable("bio", "  Știri   locale ") == "știri locale"
    assert comparable("emails", ["Redactie@ValceaClar.ro"]) == ["redactie@valceaclar.ro"]
    assert encode_field_value("emails", ["redactie@valceaclar.ro"]) == '["redactie@valceaclar.ro"]'

    calls: list[tuple[str, str, str]] = []
    values = {
        "bio": "old",
        "about": "old",
        "website": "https://example.invalid/",
        "emails": ["old@example.invalid"],
    }

    class FakeResponse:
        def __init__(self, payload: dict[str, Any]):
            self.payload = payload
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_open(request, timeout=0):
        if request.get_method() == "GET":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
            requested = query["fields"][0].split(",")[-1]
            return FakeResponse({"id": DEFAULT_PAGE_ID, "name": "Vâlcea Clar", requested: values[requested]})
        body = urllib.parse.parse_qs(request.data.decode("utf-8"))
        field = next(key for key in body if key != "access_token")
        raw = body[field][0]
        values[field] = json.loads(raw) if field == "emails" else raw
        calls.append((request.get_method(), field, raw))
        return FakeResponse({"success": True})

    old_env = dict(os.environ)
    try:
        os.environ["VALCEA_META_PAGE_ACCESS_TOKEN"] = "fixture-identity-token-never-logged"
        os.environ["VALCEA_FB_PAGE_ID"] = DEFAULT_PAGE_ID
        os.environ[LIVE_ENV] = "true"
        result = run(
            apply=True,
            request_fn=fake_open,
            token_resolver=lambda page_id, supplied, version: (
                "fixture-page-token-never-logged",
                {"page_name": "Vâlcea Clar", "source": "fixture_resolved_page"},
            ),
        )
    finally:
        os.environ.clear()
        os.environ.update(old_env)
    assert result["status"] == "SYNCED"
    assert result["verified_fields"] == 4
    assert len(calls) == 4
    assert result["credentials_logged"] is False
    assert result["token_source"] == "fixture_resolved_page"
    print("VÂLCEA CLAR Facebook profile sync self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            return self_test()
        result = run(apply=args.apply)
        write(STATE, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ProfileSyncError as exc:
        result = {
            "schema_version": "1.1",
            "status": "FAIL",
            "error": str(exc),
            "credentials_logged": False,
            "credentials_persisted": False,
        }
        write(STATE, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
