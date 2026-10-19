from __future__ import annotations

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.canonical: str | None = None
        self._in_ld_json = False
        self._buffer: list[str] = []
        self.json_ld: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {k.lower(): v for k, v in attrs}
        if tag.lower() == "link" and (data.get("rel") or "").lower() == "canonical":
            self.canonical = data.get("href")
        if tag.lower() == "script" and (data.get("type") or "").lower() == "application/ld+json":
            self._in_ld_json = True
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._in_ld_json:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_ld_json:
            raw = "".join(self._buffer).strip()
            self._in_ld_json = False
            self._buffer = []
            if raw:
                try:
                    self.json_ld.append(json.loads(raw))
                except json.JSONDecodeError:
                    self.json_ld.append({"_invalid_json_ld": raw[:200]})


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def inspect_html(html: str, *, requested_url: str, final_url: str, expected_story_id: str) -> dict[str, Any]:
    parser = _PageParser()
    parser.feed(html)
    news_articles = []
    for root in parser.json_ld:
        for obj in _walk_json(root):
            typ = obj.get("@type") if isinstance(obj, dict) else None
            types = {typ} if isinstance(typ, str) else set(typ or []) if isinstance(typ, list) else set()
            if "NewsArticle" in types:
                news_articles.append(obj)

    normalized_final = final_url.rstrip("/") + "/"
    expected_fragment = f"/stiri/{expected_story_id}/"
    canonical = (parser.canonical or "").rstrip("/") + "/" if parser.canonical else None
    route_match = expected_fragment in normalized_final
    canonical_match = bool(canonical and expected_fragment in canonical)
    article_match = any(
        expected_story_id in str(obj.get("url") or "")
        or expected_story_id in str(obj.get("mainEntityOfPage") or "")
        for obj in news_articles
    )
    return {
        "requested_url": requested_url,
        "final_url": final_url,
        "canonical_url": parser.canonical,
        "expected_story_id": expected_story_id,
        "route_match": route_match,
        "canonical_match": canonical_match,
        "newsarticle_count": len(news_articles),
        "newsarticle_story_match": article_match,
        "readback_ok": bool(route_match and canonical_match and news_articles and article_match),
    }


def read_site(url: str, expected_story_id: str, timeout: float = 12.0) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "CIVORA-Core-v2-Auditor/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or 0)
            final_url = response.geturl()
            html = response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        return {
            "requested_url": url,
            "expected_story_id": expected_story_id,
            "status": "FAILED",
            "error": str(exc),
            "readback_ok": False,
            "publication_authority": "NONE",
        }

    result = inspect_html(html, requested_url=url, final_url=final_url, expected_story_id=expected_story_id)
    result["http_status"] = status
    result["readback_ok"] = bool(status == 200 and result["readback_ok"])
    result["status"] = "PASS" if result["readback_ok"] else "FAILED"
    result["publication_authority"] = "NONE"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only public site auditor for Core v2")
    parser.add_argument("--url", required=True)
    parser.add_argument("--story-id", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = read_site(args.url, args.story_id)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["readback_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
