#!/usr/bin/env python3
"""Fail-closed X publishing adapter for VÂLCEA CLAR.

The adapter is credential-aware but billing-gated. Default mode performs no
network request. It can verify that the four OAuth 1.0a credential values are
present without printing them, capture an activation baseline so historical
outbox items cannot be replayed, and prepare a future paid write path.

Live writes require all of the following explicit runtime flags:
- VALCEA_X_BILLING_APPROVED=true
- VALCEA_X_LIVE_ENABLED=true
- VALCEA_X_DIRECT_PUBLISHING_ENABLED=true

No workflow in the current zero-paid configuration sets those flags.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from social_common import utc_now

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
OUTBOX = VC / "social" / "x_outbox.json"
STATE = VC / "social" / "x_state.json"
EVENT = VC / "site" / "story_publication_event.json"
API_BASE = "https://api.x.com"
CREATE_POST_URL = API_BASE + "/2/tweets"
MAX_POSTS_PER_THREAD = 4
MAX_CHARS_PER_POST = 260
CREDENTIAL_ENVS = (
    "VALCEA_X_API_KEY",
    "VALCEA_X_API_SECRET",
    "VALCEA_X_ACCESS_TOKEN",
    "VALCEA_X_ACCESS_TOKEN_SECRET",
)
BILLING_BLOCKER = "x_api_pay_per_use_requires_explicit_credit_purchase_zero_paid_policy_keeps_direct_disabled"


class XPublishError(RuntimeError):
    pass


def load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default
        raise XPublishError(f"missing required file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise XPublishError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() == "true"


def credential_values() -> dict[str, str]:
    values = {name: os.environ.get(name, "").strip() for name in CREDENTIAL_ENVS}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise XPublishError("missing X OAuth credential references: " + ", ".join(missing))
    return values


def credential_check() -> dict[str, Any]:
    values = credential_values()
    return {
        "status": "PASS",
        "platform": "x",
        "oauth": "1.0a_user_context",
        "credential_references_present": list(CREDENTIAL_ENVS),
        "credential_values_logged": False,
        "credential_value_count": len(values),
        "network_calls": False,
        "billing_charge_possible": False,
    }


def pct(value: Any) -> str:
    return urllib.parse.quote(str(value), safe="~-._")


def oauth_header(
    method: str,
    url: str,
    credentials: dict[str, str],
    *,
    query: dict[str, Any] | None = None,
    nonce: str | None = None,
    timestamp: str | None = None,
) -> str:
    """Build an OAuth 1.0a HMAC-SHA1 Authorization header.

    For JSON requests, body fields are intentionally not included in the OAuth
    signature parameter set. Query parameters and OAuth parameters are included.
    """
    params: dict[str, str] = {
        "oauth_consumer_key": credentials["VALCEA_X_API_KEY"],
        "oauth_nonce": nonce or secrets.token_urlsafe(18),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": credentials["VALCEA_X_ACCESS_TOKEN"],
        "oauth_version": "1.0",
    }
    pairs: list[tuple[str, str]] = [(pct(k), pct(v)) for k, v in params.items()]
    for key, value in (query or {}).items():
        if isinstance(value, (list, tuple)):
            pairs.extend((pct(key), pct(item)) for item in value)
        else:
            pairs.append((pct(key), pct(value)))
    pairs.sort()
    normalized = "&".join(f"{k}={v}" for k, v in pairs)
    base_url = urllib.parse.urlsplit(url)
    canonical_url = urllib.parse.urlunsplit((base_url.scheme, base_url.netloc, base_url.path, "", ""))
    base_string = "&".join((method.upper(), pct(canonical_url), pct(normalized)))
    signing_key = pct(credentials["VALCEA_X_API_SECRET"]) + "&" + pct(credentials["VALCEA_X_ACCESS_TOKEN_SECRET"])
    signature = base64.b64encode(
        hmac.new(signing_key.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")
    params["oauth_signature"] = signature
    return "OAuth " + ", ".join(f'{pct(key)}="{pct(value)}"' for key, value in sorted(params.items()))


def request_json(method: str, url: str, credentials: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": oauth_header(method, url, credentials),
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "valcea-clar-x-engine/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise XPublishError(f"X API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise XPublishError(f"X API transport error: {exc.reason}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise XPublishError("X API returned non-JSON data") from exc
    if not isinstance(value, dict):
        raise XPublishError("X API returned a non-object response")
    if value.get("errors") and not value.get("data"):
        raise XPublishError("X API returned errors without a created Post")
    return value


def validate_item(item: dict[str, Any]) -> list[str]:
    if item.get("status") != "outbox_ready":
        raise XPublishError("item is not outbox_ready")
    if item.get("source_preserving") is not True:
        raise XPublishError("X source-preserving gate failed")
    if item.get("verbatim_cross_platform_reuse_allowed") is not False:
        raise XPublishError("X verbatim cross-platform reuse guard failed")
    if item.get("fake_urgency_forbidden") is not True or item.get("engagement_bait_forbidden") is not True:
        raise XPublishError("X anti-bait editorial guard failed")
    identity = item.get("identity")
    if not isinstance(identity, dict) or identity.get("channel_id") != "valcea-x":
        raise XPublishError("X canonical identity is missing")
    posts = item.get("posts")
    if not isinstance(posts, list) or not 1 <= len(posts) <= MAX_POSTS_PER_THREAD:
        raise XPublishError("X post sequence must contain 1-4 posts")
    clean: list[str] = []
    for raw in posts:
        text = str(raw).strip()
        if not text or len(text) > MAX_CHARS_PER_POST:
            raise XPublishError("X post is empty or exceeds the internal 260-character budget")
        clean.append(text)
    return clean


def configure() -> dict[str, Any]:
    credential_check()
    event = load(EVENT)
    event_fp = str(event.get("fingerprint") or "").strip()
    if not event_fp:
        raise XPublishError("story publication event fingerprint is missing")
    state = load(STATE, {
        "schema_version": "1.1",
        "platform": "x",
        "execution_owner": "civora_site_engine",
        "published": {},
        "failures": {},
    })
    state["schema_version"] = "1.1"
    state["platform"] = "x"
    state["execution_owner"] = "civora_site_engine"
    state["publication_model"] = "continuous_story_first"
    state["identity_source"] = "valcea-clar/social/native_platform_identity_system.json"
    state["identity_channel_id"] = "valcea-x"
    state["credential_contract"] = "oauth1_user_context_four_secret_refs"
    state["credential_references"] = list(CREDENTIAL_ENVS)
    state["credential_presence_verified"] = True
    state["credential_presence_verified_at"] = utc_now()
    state["network_identity_verified"] = False
    state["network_identity_verification_deferred_reason"] = "avoid_paid_api_call_before_explicit_billing_approval"
    state["direct_publication_enabled"] = False
    state["billing_approved"] = False
    state["blocker"] = BILLING_BLOCKER
    state.setdefault("published", {})
    state.setdefault("failures", {})
    if not state.get("credential_link_activation_baseline_event_fingerprint"):
        state["credential_link_activation_baseline_event_fingerprint"] = event_fp
        state["credential_link_activation_baselined_at"] = utc_now()
    write(STATE, state)
    return {
        "status": "CONFIGURED_BILLING_GATED",
        "platform": "x",
        "credential_presence_verified": True,
        "network_calls": False,
        "billing_charge_possible": False,
        "activation_baseline_present": True,
        "direct_publication_enabled": False,
        "blocker": BILLING_BLOCKER,
    }


def eligible_items(outbox: dict[str, Any], state: dict[str, Any], event: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if outbox.get("platform") != "x" or outbox.get("publication_model") != "continuous_story_first":
        raise XPublishError("X outbox identity/publication model mismatch")
    event_fp = str(event.get("fingerprint") or "").strip()
    if not event_fp:
        raise XPublishError("story publication event fingerprint is missing")
    baseline = str(state.get("credential_link_activation_baseline_event_fingerprint") or "").strip()
    if not baseline:
        return "CONFIGURATION_BASELINE_REQUIRED", []
    if event_fp == baseline:
        return "ACTIVATION_BASELINE", []
    new_ids = event.get("new_story_ids")
    if not isinstance(new_ids, list) or not new_ids:
        return "NO_NEW_STORIES", []
    wanted = {str(value) for value in new_ids if str(value).strip()}
    published = state.get("published") if isinstance(state.get("published"), dict) else {}
    failures = state.get("failures") if isinstance(state.get("failures"), dict) else {}
    result: list[dict[str, Any]] = []
    for item in outbox.get("items", []):
        if not isinstance(item, dict) or str(item.get("story_id")) not in wanted:
            continue
        if item.get("status") != "outbox_ready":
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id or item_id in published:
            continue
        failure = failures.get(item_id)
        if isinstance(failure, dict) and failure.get("manual_reconciliation_required") is True:
            continue
        validate_item(item)
        result.append(item)
    return "READY_AFTER_BILLING_APPROVAL" if result else "NO_ELIGIBLE_ITEMS", result


def preview() -> dict[str, Any]:
    outbox = load(OUTBOX)
    state = load(STATE)
    event = load(EVENT)
    reason, items = eligible_items(outbox, state, event)
    return {
        "status": "PREVIEW",
        "platform": "x",
        "reason": reason,
        "eligible_after_billing_approval": [str(item.get("id")) for item in items],
        "network_calls": False,
        "billing_charge_possible": False,
        "direct_publication_enabled": False,
        "blocker": state.get("blocker") or BILLING_BLOCKER,
    }


def publish_post(credentials: dict[str, str], text: str, reply_to_id: str | None = None) -> str:
    payload: dict[str, Any] = {"text": text}
    if reply_to_id:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to_id}
    value = request_json("POST", CREATE_POST_URL, credentials, payload)
    data = value.get("data") if isinstance(value.get("data"), dict) else {}
    remote_id = str(data.get("id") or "").strip()
    if not remote_id:
        raise XPublishError("X create-post response contained no Post id")
    return remote_id


def apply(max_items: int) -> dict[str, Any]:
    for flag in ("VALCEA_X_BILLING_APPROVED", "VALCEA_X_LIVE_ENABLED", "VALCEA_X_DIRECT_PUBLISHING_ENABLED"):
        if not env_true(flag):
            raise XPublishError(f"{flag}=true is required for paid X publication")
    credentials = credential_values()
    outbox = load(OUTBOX)
    state = load(STATE)
    event = load(EVENT)
    if state.get("credential_presence_verified") is not True:
        raise XPublishError("X credential-link configuration has not been persisted")
    reason, items = eligible_items(outbox, state, event)
    items = items[:max(0, max_items)]
    if not items:
        return {"status": "NOOP", "published": [], "reason": reason}
    event_fp = str(event.get("fingerprint") or "").strip()
    published = state.setdefault("published", {})
    failures = state.setdefault("failures", {})
    completed: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item["id"])
        posts = validate_item(item)
        remote_ids: list[str] = []
        previous_id: str | None = None
        try:
            for text in posts:
                remote_id = publish_post(credentials, text, previous_id)
                remote_ids.append(remote_id)
                previous_id = remote_id
        except Exception as exc:
            failures[item_id] = {
                "failed_at": utc_now(),
                "story_id": item.get("story_id"),
                "event_fingerprint": event_fp,
                "remote_ids_observed": remote_ids,
                "manual_reconciliation_required": True,
                "automatic_retry_forbidden": True,
                "reason": str(exc)[:1000],
            }
            write(STATE, state)
            raise XPublishError(
                f"X item {item_id} entered manual reconciliation after a partial/uncertain paid publish"
            ) from exc
        published[item_id] = {
            "published_at": utc_now(),
            "story_id": item.get("story_id"),
            "event_fingerprint": event_fp,
            "root_remote_id": remote_ids[0],
            "remote_ids": remote_ids,
            "posts": len(posts),
        }
        failures.pop(item_id, None)
        completed.append({"id": item_id, "remote_ids": remote_ids})
        write(STATE, state)
    state["last_successful_event_fingerprint"] = event_fp
    state["billing_approved"] = True
    state["direct_publication_enabled"] = True
    state["blocker"] = None
    write(STATE, state)
    return {"status": "PUBLISHED", "published": completed}


def self_test() -> int:
    fixture = {
        "VALCEA_X_API_KEY": "consumer-key",
        "VALCEA_X_API_SECRET": "consumer-secret",
        "VALCEA_X_ACCESS_TOKEN": "access-token",
        "VALCEA_X_ACCESS_TOKEN_SECRET": "access-secret",
    }
    first = oauth_header("POST", CREATE_POST_URL, fixture, nonce="fixed-nonce", timestamp="1700000000")
    second = oauth_header("POST", CREATE_POST_URL, fixture, nonce="fixed-nonce", timestamp="1700000000")
    assert first == second and "oauth_signature=" in first
    assert "consumer-secret" not in first and "access-secret" not in first
    item = {
        "id": "x-story-new",
        "story_id": "new",
        "status": "outbox_ready",
        "source_preserving": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "fake_urgency_forbidden": True,
        "engagement_bait_forbidden": True,
        "identity": {"channel_id": "valcea-x"},
        "posts": ["Fapt verificat.", "Context și sursă."],
    }
    outbox = {"platform": "x", "publication_model": "continuous_story_first", "items": [item]}
    state = {
        "credential_link_activation_baseline_event_fingerprint": "old",
        "published": {},
        "failures": {},
    }
    reason, items = eligible_items(outbox, state, {"fingerprint": "new", "new_story_ids": ["new"]})
    assert reason == "READY_AFTER_BILLING_APPROVAL" and [row["id"] for row in items] == ["x-story-new"]
    reason, items = eligible_items(outbox, state, {"fingerprint": "old", "new_story_ids": ["new"]})
    assert reason == "ACTIVATION_BASELINE" and not items
    state["failures"] = {"x-story-new": {"manual_reconciliation_required": True}}
    reason, items = eligible_items(outbox, state, {"fingerprint": "new", "new_story_ids": ["new"]})
    assert reason == "NO_ELIGIBLE_ITEMS" and not items
    print("VÂLCEA CLAR X billing-gated publisher self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--credential-check", action="store_true")
    parser.add_argument("--configure", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-items", type=int, default=int(os.environ.get("VALCEA_X_MAX_PER_RUN", "1")))
    args = parser.parse_args()
    try:
        if args.self_test:
            return self_test()
        if args.credential_check:
            result = credential_check()
        elif args.configure:
            result = configure()
        elif args.apply:
            result = apply(args.max_items)
        else:
            result = preview()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except XPublishError as exc:
        print(json.dumps({"status": "FAIL", "platform": "x", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
