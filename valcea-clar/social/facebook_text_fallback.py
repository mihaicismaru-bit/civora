#!/usr/bin/env python3
"""Fail-closed Facebook text+link fallback for VÂLCEA CLAR.

Facebook is photo-first. Missing story-specific media is a HOLD by default and
must not silently degrade to a text+link post. A text fallback can run only when
both the runtime env and the individual outbox item explicitly opt in, and only
after a live public readback proves that the canonical story URL is HTTP 200 and
exposes article-specific canonical/OpenGraph metadata matching the newsroom
headline. The adapter also refuses RSS-like category-prefixed copy. This prevents
Facebook from caching a stale/wrong card or publishing non-canonical social copy.

A transient ``new_story_ids`` marker is preferred for the first delivery attempt.
If that marker has already been cleared, the adapter may recover only current
edition stories that are still newsroom-publishable, have a verified/PASS fact
kernel, and entered their validity window within the bounded retry horizon. This
keeps failed social delivery retryable without reopening the legacy backlog.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
from html.parser import HTMLParser
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

import facebook_publish as legacy
from social_common import is_socially_held

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
OUTBOX = VC / "social" / "facebook_outbox.json"
STATE = VC / "social" / "facebook_state.json"
EVENT = VC / "site" / "story_publication_event.json"
DECISION = VC / "site" / "newsroom_decision.json"
CURRENT = VC / "site" / "current_edition.json"
DEFAULT_GRAPH_VERSION = "v26.0"
ADAPTER = "facebook-text-fallback-v1.1"
MISSING_PHOTO_REASON = "story_specific_approved_photo_required"
CANONICAL_HOSTS = {"valceaclar.ro", "www.valceaclar.ro"}
ENABLE_ENV = "VALCEA_FB_TEXT_FALLBACK_ENABLED"
PUBLIC_UA = "facebookexternalhit/1.1 (+https://www.facebook.com/externalhit_uatext.php)"
PUBLIC_PAGE_MAX_BYTES = 750_000
OG_TITLE_SUFFIX = " — VÂLCEA CLAR"
RECOVERY_WINDOW = dt.timedelta(hours=48)
CLOCK_SKEW = dt.timedelta(minutes=5)
GITHUB_404_MARKERS = (
    "page not found · github pages",
    "page not found - github pages",
    "there isn't a github pages site here",
    "file not found",
)


class SocialMetaParser(HTMLParser):
    """Collect only metadata needed by the Facebook preflight contract."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.canonical = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        if tag.lower() == "meta":
            key = values.get("property") or values.get("name")
            if key:
                self.meta[key.lower()] = values.get("content", "").strip()
        elif tag.lower() == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonical = values.get("href", "").strip()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_timestamp(value: object) -> dt.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def recoverable_recent_story_ids(
    snapshot: dict[str, Any],
    decision: dict[str, Any],
    *,
    now: dt.datetime | None = None,
) -> list[str]:
    """Bound retries to recent, currently publishable verified stories.

    This is deliberately narrower than the full current edition. It exists only
    to recover a missed/failed Facebook attempt after ``new_story_ids`` has been
    consumed. Legacy inventory cannot become eligible merely because it remains
    in the edition.
    """
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        raise ValueError("retry recovery clock must be timezone-aware")
    current = current.astimezone(dt.timezone.utc)
    publishable = {
        str(value) for value in decision.get("publishable_story_ids") or [] if str(value)
    }
    recovered: list[str] = []
    for item in snapshot.get("items") or []:
        if not isinstance(item, dict):
            continue
        story_id = str(item.get("id") or "").strip()
        if not story_id or story_id not in publishable or is_socially_held(story_id):
            continue
        if item.get("material_fact_gate") != "PASS":
            continue
        if str(item.get("lifecycle_status") or "").strip().lower() != "verified":
            continue
        observed = _parse_timestamp(item.get("valid_from"))
        if observed is None:
            continue
        age = current - observed
        if age < -CLOCK_SKEW or age > RECOVERY_WINDOW:
            continue
        recovered.append(story_id)
    return recovered


def _current_edition_snapshot() -> dict[str, Any]:
    pointer = load(CURRENT, {})
    source = str(pointer.get("json_source") or "").strip()
    if not source or not source.startswith("editions/") or ".." in Path(source).parts:
        return {}
    return load(VC / source, {})


def latest_new_story_ids() -> list[str]:
    event = load(EVENT, {})
    ids = [str(value) for value in event.get("new_story_ids") or [] if str(value)]
    if ids:
        return ids
    decision = load(DECISION, {})
    ids = [str(value) for value in decision.get("new_story_ids") or [] if str(value)]
    if ids:
        return ids
    return recoverable_recent_story_ids(_current_edition_snapshot(), decision)


def canonical_link_ok(value: str) -> bool:
    parsed = urllib.parse.urlparse(str(value or "").strip())
    return parsed.scheme == "https" and parsed.hostname in CANONICAL_HOSTS and parsed.path.startswith("/stiri/")


def text_fallback_enabled() -> bool:
    return str(os.getenv(ENABLE_ENV) or "").strip().lower() == "true"


def _normal_url(value: str) -> str:
    normalized = html.unescape(str(value or "").strip()).rstrip("/")
    return normalized.replace("https://www.valceaclar.ro", "https://valceaclar.ro", 1)


def _normal_text(value: str) -> str:
    return " ".join(html.unescape(str(value or "")).split()).casefold()


def _og_title_matches(value: str, expected_headline: str) -> bool:
    actual = _normal_text(value)
    expected = _normal_text(expected_headline)
    branded = _normal_text(f"{expected_headline}{OG_TITLE_SUFFIX}")
    return bool(expected) and actual in {expected, branded}


def native_copy_ok(message: str) -> bool:
    """Require platform-native copy and reject the legacy category masthead."""
    blocks = [block.strip() for block in str(message or "").split("\n\n") if block.strip()]
    if not blocks:
        return False
    first = " ".join(blocks[0].split()).casefold()
    if first.endswith("| vâlcea clar"):
        return False
    return True


def public_story_ready(
    url: str,
    expected_headline: str,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[bool, str]:
    """Require a real public story with exact story-specific OG metadata."""
    if not canonical_link_ok(url):
        return False, "non_canonical_story_url"
    if not str(expected_headline or "").strip():
        return False, "expected_headline_missing"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": PUBLIC_UA,
            "Accept": "text/html,application/xhtml+xml",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with request_fn(request, timeout=30) as response:
            status = int(getattr(response, "status", 0) or response.getcode() or 0)
            body = response.read(PUBLIC_PAGE_MAX_BYTES).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except urllib.error.URLError as exc:
        return False, f"network_{getattr(exc, 'reason', 'error')}"
    except Exception as exc:
        return False, f"readback_{type(exc).__name__}"
    if status != 200:
        return False, f"http_{status}"
    lower = body.lower()
    if any(marker in lower for marker in GITHUB_404_MARKERS):
        return False, "github_pages_404_body"

    parser = SocialMetaParser()
    try:
        parser.feed(body)
    except Exception:
        return False, "public_html_parse"

    if _normal_url(parser.canonical) != _normal_url(url):
        return False, "canonical_mismatch"
    if parser.meta.get("og:type", "").casefold() != "article":
        return False, "og_type_not_article"
    if _normal_url(parser.meta.get("og:url", "")) != _normal_url(url):
        return False, "og_url_mismatch"
    if not _og_title_matches(parser.meta.get("og:title", ""), expected_headline):
        return False, "og_title_mismatch"
    if not _normal_text(parser.meta.get("og:description", "")):
        return False, "og_description_missing"
    return True, "ready"


def eligible_items(outbox: dict[str, Any], state: dict[str, Any], new_story_ids: list[str]) -> list[dict[str, Any]]:
    # Photo-first default: the global runtime switch is deliberately OFF unless
    # an operator explicitly enables the exceptional fallback path.
    if not text_fallback_enabled():
        return []
    wanted = set(new_story_ids)
    published = state.get("published") if isinstance(state.get("published"), dict) else {}
    result: list[dict[str, Any]] = []
    for item in outbox.get("items") or []:
        if not isinstance(item, dict):
            continue
        story_id = str(item.get("source_story_id") or "").strip()
        item_id = str(item.get("id") or "").strip()
        if not story_id or story_id not in wanted or not item_id:
            continue
        if item_id in published or is_socially_held(story_id):
            continue
        if item.get("status") != "hold" or item.get("hold_reason") != MISSING_PHOTO_REASON:
            continue
        platforms = item.get("platforms") if isinstance(item.get("platforms"), dict) else {}
        facebook = platforms.get("facebook") if isinstance(platforms.get("facebook"), dict) else {}
        if facebook.get("status") != "hold" or facebook.get("reason") != MISSING_PHOTO_REASON:
            continue
        if facebook.get("text_link_fallback_allowed_for_new_story") is not True:
            continue
        message = str(item.get("message") or "").strip()
        link = str(item.get("link") or "").strip()
        headline = str(item.get("canonical_headline") or "").strip()
        if not message or not native_copy_ok(message) or not canonical_link_ok(link) or not headline:
            continue
        result.append(item)
    return result


def graph_feed_post(
    *,
    page_id: str,
    token: str,
    version: str,
    item: dict[str, Any],
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    link = str(item["link"]).strip()
    headline = str(item.get("canonical_headline") or "").strip()
    message = str(item.get("message") or "").strip()
    if not native_copy_ok(message):
        raise RuntimeError("facebook text fallback rejected non-canonical copy")
    ready, reason = public_story_ready(link, headline, request_fn=request_fn)
    if not ready:
        raise RuntimeError(f"public story route not ready for Facebook fallback: {reason}")
    payload = urllib.parse.urlencode({
        "message": message,
        "link": link,
        "access_token": token,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://graph.facebook.com/{version}/{page_id}/feed",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "ValceaClar-Facebook-Text-Fallback/1.1"},
    )
    try:
        with request_fn(request, timeout=45) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Meta text-link POST HTTP {exc.code}: {detail[:1000]}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Meta text-link POST returned unexpected payload")
    post_id = str(value.get("id") or value.get("post_id") or "").strip()
    if not post_id:
        raise RuntimeError(f"Meta text-link POST returned no post id: {value}")
    return post_id


def record_publication(state: dict[str, Any], item: dict[str, Any], post_id: str) -> None:
    published = state.setdefault("published", {})
    if not isinstance(published, dict):
        raise ValueError("facebook_state.published must be an object")
    item_id = str(item["id"])
    story_id = str(item["source_story_id"])
    published[item_id] = {
        "facebook_post_id": post_id,
        "published_at": utc_now(),
        "link": str(item["link"]),
        "publication_product": ADAPTER,
        "native_format": "text_link",
        "visual_used": False,
        "synthetic_media_used": False,
        "source_story_id": story_id,
        "fallback_reason": MISSING_PHOTO_REASON,
        "replacement_cleanup": {},
    }
    state["last_text_fallback_attempt"] = {
        "at": utc_now(), "status": "published", "story_id": story_id,
        "state_key": item_id, "publication_product": ADAPTER,
    }


def credentials() -> tuple[str, str, str]:
    page_id = str(os.getenv("VALCEA_FB_PAGE_ID") or "1234360446430980").strip()
    token = str(os.getenv("VALCEA_META_PAGE_ACCESS_TOKEN") or os.getenv("VALCEA_FB_PAGE_ACCESS_TOKEN") or "").strip()
    version = str(os.getenv("VALCEA_FB_GRAPH_VERSION") or DEFAULT_GRAPH_VERSION).strip()
    return page_id, token, version


def self_test() -> int:
    previous = os.getenv(ENABLE_ENV)
    os.environ[ENABLE_ENV] = "true"
    sample = {
        "id": "story-test-new", "source_story_id": "test-new", "status": "hold",
        "hold_reason": MISSING_PHOTO_REASON,
        "message": "Meciul se joacă sâmbătă, de la ora 11:00.\n\nDetalii, context și surse verificate în articol.",
        "canonical_headline": "SCM Râmnicu Vâlcea caută prima victorie acasă",
        "link": "https://valceaclar.ro/stiri/test-new/",
        "platforms": {"facebook": {
            "status": "hold", "reason": MISSING_PHOTO_REASON,
            "text_link_fallback_allowed_for_new_story": True,
        }},
    }
    try:
        fixed_now = dt.datetime(2026, 9, 12, 7, 0, tzinfo=dt.timezone.utc)
        recent_snapshot = {
            "items": [
                {
                    "id": "test-new", "material_fact_gate": "PASS", "lifecycle_status": "verified",
                    "valid_from": "2026-09-11T00:00:00+03:00",
                },
                {
                    "id": "test-old", "material_fact_gate": "PASS", "lifecycle_status": "verified",
                    "valid_from": "2026-09-08T00:00:00+03:00",
                },
                {
                    "id": "test-title-only", "material_fact_gate": "HOLD_TITLE_DATE_ONLY",
                    "lifecycle_status": "verified", "valid_from": "2026-09-11T00:00:00+03:00",
                },
            ]
        }
        recent_decision = {"publishable_story_ids": ["test-new", "test-old", "test-title-only"]}
        assert recoverable_recent_story_ids(recent_snapshot, recent_decision, now=fixed_now) == ["test-new"]

        assert native_copy_ok(sample["message"])
        assert not native_copy_ok("SPORT | VÂLCEA CLAR\n\nInformare verificată.")
        assert eligible_items({"items": [sample]}, {"published": {}}, ["test-new"])[0]["id"] == sample["id"]
        old_style = json.loads(json.dumps(sample))
        old_style["message"] = "SPORT | VÂLCEA CLAR\n\nInformare verificată."
        assert eligible_items({"items": [old_style]}, {"published": {}}, ["test-new"]) == []
        no_headline = json.loads(json.dumps(sample))
        no_headline["canonical_headline"] = ""
        assert eligible_items({"items": [no_headline]}, {"published": {}}, ["test-new"]) == []
        no_opt_in = json.loads(json.dumps(sample))
        no_opt_in["platforms"]["facebook"]["text_link_fallback_allowed_for_new_story"] = False
        assert eligible_items({"items": [no_opt_in]}, {"published": {}}, ["test-new"]) == []
        assert eligible_items({"items": [sample]}, {"published": {sample["id"]: {}}}, ["test-new"]) == []
        assert canonical_link_ok(sample["link"])
        assert not canonical_link_ok("https://example.com/stiri/test/")

        class FakePublicResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, exc_type, exc, tb): return False
            def getcode(self): return 200
            def read(self, *args):
                url = sample["link"]
                title = sample["canonical_headline"]
                return (
                    f'<html><head><link rel="canonical" href="{url}">'
                    f'<meta property="og:type" content="article">'
                    f'<meta property="og:url" content="{url}">'
                    f'<meta property="og:title" content="{title}">'
                    f'<meta property="og:description" content="Descriere verificată"></head></html>'
                ).encode()

        class WrongTitleResponse(FakePublicResponse):
            def read(self, *args):
                url = sample["link"]
                return (
                    f'<html><head><link rel="canonical" href="{url}">'
                    f'<meta property="og:type" content="article">'
                    f'<meta property="og:url" content="{url}">'
                    f'<meta property="og:title" content="Titlu vechi din sursă">'
                    f'<meta property="og:description" content="Descriere verificată"></head></html>'
                ).encode()

        class BrandedTitleResponse(FakePublicResponse):
            def read(self, *args):
                url = sample["link"]
                title = sample["canonical_headline"] + OG_TITLE_SUFFIX
                return (
                    f'<html><head><link rel="canonical" href="{url}">'
                    f'<meta property="og:type" content="article">'
                    f'<meta property="og:url" content="{url}">'
                    f'<meta property="og:title" content="{title}">'
                    f'<meta property="og:description" content="Descriere verificată"></head></html>'
                ).encode()

        class FakeGraphResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, exc_type, exc, tb): return False
            def getcode(self): return 200
            def read(self, *args): return b'{"id":"123_page_456"}'

        captured: dict[str, Any] = {}
        def fake_open(request, timeout=0):
            captured.setdefault("urls", []).append(request.full_url)
            if request.full_url.startswith("https://valceaclar.ro/"):
                return FakePublicResponse()
            captured["method"] = request.get_method()
            captured["data"] = urllib.parse.parse_qs(request.data.decode("utf-8"))
            return FakeGraphResponse()

        assert public_story_ready(sample["link"], sample["canonical_headline"], request_fn=fake_open) == (True, "ready")
        assert public_story_ready(sample["link"], sample["canonical_headline"], request_fn=lambda request, timeout=0: BrandedTitleResponse()) == (True, "ready")
        assert public_story_ready(sample["link"], sample["canonical_headline"], request_fn=lambda request, timeout=0: WrongTitleResponse()) == (False, "og_title_mismatch")
        post_id = graph_feed_post(page_id="123", token="fixture-token", version="v26.0", item=sample, request_fn=fake_open)
        assert post_id == "123_page_456"
        assert captured["method"] == "POST"
        assert captured["data"]["link"] == [sample["link"]]
        assert captured["data"]["message"] == [sample["message"]]
        state = {"published": {}}
        record_publication(state, sample, post_id)
        assert state["published"][sample["id"]]["visual_used"] is False
        assert state["published"][sample["id"]]["publication_product"] == ADAPTER
    finally:
        if previous is None:
            os.environ.pop(ENABLE_ENV, None)
        else:
            os.environ[ENABLE_ENV] = previous
    assert eligible_items({"items": [sample]}, {"published": {}}, ["test-new"]) == []
    print("VÂLCEA CLAR Facebook text fallback fail-closed self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    outbox = load(OUTBOX, {"schema_version": "4.0", "items": []})
    state = load(STATE, {"schema_version": "3.0", "published": {}})
    new_ids = latest_new_story_ids()
    plan = eligible_items(outbox, state, new_ids)
    max_per_run = max(1, min(int(os.getenv("VALCEA_FB_TEXT_FALLBACK_MAX_PER_RUN") or "2"), 4))
    plan = plan[:max_per_run]

    if not args.apply:
        print(json.dumps({
            "status": "DRY_RUN", "adapter": ADAPTER, "enabled": text_fallback_enabled(),
            "new_story_ids": new_ids,
            "eligible": [{"id": item.get("id"), "source_story_id": item.get("source_story_id"), "link": item.get("link")} for item in plan],
        }, ensure_ascii=False, indent=2))
        return 0
    if not plan:
        print(json.dumps({"status": "NO_ELIGIBLE_TEXT_FALLBACK", "adapter": ADAPTER, "enabled": text_fallback_enabled(), "new_story_ids": new_ids}, ensure_ascii=False))
        return 0

    page_id, supplied_token, version = credentials()
    if not supplied_token:
        state["last_text_fallback_attempt"] = {"at": utc_now(), "status": "blocked_missing_meta_token", "publication_product": ADAPTER}
        write(STATE, state)
        print(json.dumps({"status": "BLOCKED_MISSING_META_TOKEN", "adapter": ADAPTER}, ensure_ascii=False))
        return 2
    try:
        page_token, identity = legacy.resolve_page_token(page_id, supplied_token, version)
    except Exception as exc:
        reason = legacy.classify_auth_error(exc)
        state["last_text_fallback_attempt"] = {"at": utc_now(), "status": "blocked_meta_auth", "publication_product": ADAPTER, "reason": reason}
        write(STATE, state)
        print(json.dumps({"status": "BLOCKED_META_AUTH", "reason": reason}, ensure_ascii=False))
        return 2

    published_now: list[dict[str, str]] = []
    for item in plan:
        post_id = graph_feed_post(page_id=page_id, token=page_token, version=version, item=item)
        record_publication(state, item, post_id)
        write(STATE, state)
        published_now.append({"story_id": str(item["source_story_id"]), "state_key": str(item["id"]), "facebook_post_id": post_id})

    state["last_text_fallback_identity"] = {
        "verified_at": utc_now(), "page_id": page_id, "page_name": identity.get("page_name"),
        "token_source": identity.get("source"), "token_value_logged": False,
    }
    write(STATE, state)
    print(json.dumps({"status": "PUBLISHED", "adapter": ADAPTER, "published": published_now}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
