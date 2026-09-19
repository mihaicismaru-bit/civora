from __future__ import annotations

import json
import time
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


ALLOWED_RIGHTS_BASES = {
    "creative_commons",
    "public_domain",
    "licensed",
    "owned",
    "staff",
    "official_press_with_reuse_rights",
    "reader_with_permission",
}


class _ImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        data = {k.lower(): v for k, v in attrs}
        self.images.append({"src": data.get("src"), "alt": data.get("alt")})


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capturing = False
        self._chunks: list[str] = []
        self.documents: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        data = {k.lower(): v for k, v in attrs}
        if str(data.get("type") or "").lower() == "application/ld+json":
            self._capturing = True
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or not self._capturing:
            return
        raw = "".join(self._chunks).strip()
        self._capturing = False
        self._chunks = []
        if not raw:
            return
        try:
            self.documents.append(json.loads(raw))
        except json.JSONDecodeError:
            return


def _filename(url_or_path: str | None) -> str:
    if not url_or_path:
        return ""
    parsed = urlparse(url_or_path)
    path = parsed.path if parsed.scheme else url_or_path
    return PurePosixPath(path).name


def inspect_article_image(html: str, *, article_url: str, expected_filename: str) -> dict[str, Any]:
    parser = _ImageParser()
    parser.feed(html)
    matches = []
    for image in parser.images:
        src = image.get("src") or ""
        if _filename(src) == expected_filename:
            matches.append({"url": urljoin(article_url, src), "alt": image.get("alt")})
    return {
        "expected_filename": expected_filename,
        "matching_image_count": len(matches),
        "matching_images": matches,
        "article_image_bound": bool(matches),
    }


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_json(nested)


def inspect_provenance_asset(html: str, *, expected_direct_url: str | None) -> dict[str, Any]:
    expected_filename = _filename(expected_direct_url)
    parser = _JsonLdParser()
    parser.feed(html)
    matches: list[dict[str, Any]] = []
    if expected_filename:
        for document in parser.documents:
            for node in _walk_json(document):
                raw_type = node.get("@type")
                types = {str(item) for item in raw_type} if isinstance(raw_type, list) else {str(raw_type or "")}
                if "ImageObject" not in types:
                    continue
                content_url = str(node.get("contentUrl") or "").strip()
                if _filename(content_url) != expected_filename:
                    continue
                license_url = str(node.get("license") or "").strip()
                matches.append(
                    {
                        "content_url": content_url,
                        "license": license_url or None,
                        "name": str(node.get("name") or "").strip() or None,
                    }
                )
    return {
        "expected_filename": expected_filename,
        "matching_imageobject_count": len(matches),
        "matching_imageobjects": matches,
        "asset_identity_ok": bool(matches),
        "license_present": bool(matches and all(str(item.get("license") or "").startswith("https://") for item in matches)),
    }


def _read_text(url: str, timeout: float = 12.0) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "CIVORA-Core-v2-Auditor/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or 0)
            final_url = response.geturl()
            content_type = str(response.headers.get("Content-Type") or "")
            body = response.read(1_500_000).decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        return {"status": "FAILED", "error": str(exc), "http_status": getattr(exc, "code", None), "readback_ok": False}
    return {
        "status": "PASS" if status == 200 else "FAILED",
        "http_status": status,
        "final_url": final_url,
        "content_type": content_type,
        "body": body,
        "readback_ok": status == 200,
    }


def _retry_delay(exc: HTTPError, attempt: int) -> float:
    raw = None
    try:
        raw = exc.headers.get("Retry-After") if exc.headers else None
    except Exception:
        raw = None
    if raw:
        try:
            return max(0.0, min(float(raw), 1.0))
        except (TypeError, ValueError):
            pass
    return min(0.25 * attempt, 1.0)


def _read_binary_head(url: str, timeout: float = 12.0, *, max_attempts: int = 3) -> dict[str, Any]:
    attempts = max(1, int(max_attempts))
    for attempt in range(1, attempts + 1):
        request = Request(url, headers={"User-Agent": "CIVORA-Core-v2-Auditor/1.0", "Range": "bytes=0-1023"})
        try:
            with urlopen(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 0) or 0)
                final_url = response.geturl()
                content_type = str(response.headers.get("Content-Type") or "")
                response.read(1024)
        except HTTPError as exc:
            if getattr(exc, "code", None) == 429 and attempt < attempts:
                time.sleep(_retry_delay(exc, attempt))
                continue
            return {
                "status": "FAILED",
                "error": str(exc),
                "http_status": getattr(exc, "code", None),
                "readback_ok": False,
                "attempts": attempt,
                "rate_limited": getattr(exc, "code", None) == 429,
            }
        except (URLError, TimeoutError) as exc:
            return {
                "status": "FAILED",
                "error": str(exc),
                "http_status": getattr(exc, "code", None),
                "readback_ok": False,
                "attempts": attempt,
                "rate_limited": False,
            }
        image_type = content_type.lower().startswith("image/")
        return {
            "status": "PASS" if status in {200, 206} and image_type else "FAILED",
            "http_status": status,
            "final_url": final_url,
            "content_type": content_type,
            "readback_ok": bool(status in {200, 206} and image_type),
            "attempts": attempt,
            "rate_limited": False,
        }
    return {"status": "FAILED", "error": "binary_readback_attempts_exhausted", "http_status": None, "readback_ok": False, "attempts": attempts, "rate_limited": False}


def _effective_direct_source_status(
    *,
    source_url: str,
    direct_source_url: str | None,
    direct_source: dict[str, Any],
    provenance_asset: dict[str, Any],
) -> tuple[bool, str | None]:
    if direct_source.get("readback_ok") is True:
        return True, None
    source_host = (urlparse(source_url).hostname or "").lower()
    direct_host = (urlparse(str(direct_source_url or "")).hostname or "").lower()
    bounded_wikimedia_rate_limit_fallback = bool(
        direct_source_url
        and direct_source.get("rate_limited") is True
        and direct_source.get("http_status") == 429
        and source_host == "commons.wikimedia.org"
        and direct_host == "upload.wikimedia.org"
        and provenance_asset.get("asset_identity_ok") is True
        and provenance_asset.get("license_present") is True
    )
    if bounded_wikimedia_rate_limit_fallback:
        return True, "wikimedia_commons_source_page_identity_fallback_for_direct_429"
    return False, None


def read_visual(
    *,
    article_url: str,
    image_path: str,
    source_url: str,
    direct_source_url: str | None,
    rights_basis: str,
    internal_real_visual_evidence: bool,
    timeout: float = 12.0,
) -> dict[str, Any]:
    expected_filename = _filename(image_path)
    internal_gate = bool(
        internal_real_visual_evidence
        and expected_filename
        and rights_basis in ALLOWED_RIGHTS_BASES
        and source_url.startswith("https://")
    )
    article = _read_text(article_url, timeout)
    article_binding = (
        inspect_article_image(article.get("body") or "", article_url=article_url, expected_filename=expected_filename)
        if article.get("readback_ok")
        else {"expected_filename": expected_filename, "matching_image_count": 0, "matching_images": [], "article_image_bound": False}
    )
    public_image = {"status": "BLOCKED", "readback_ok": False, "reason": "article_image_not_bound"}
    if article_binding.get("matching_images"):
        public_image = _read_binary_head(str(article_binding["matching_images"][0]["url"]), timeout)

    provenance_source = _read_text(source_url, timeout)
    provenance_asset = (
        inspect_provenance_asset(provenance_source.get("body") or "", expected_direct_url=direct_source_url)
        if provenance_source.get("readback_ok")
        else {
            "expected_filename": _filename(direct_source_url),
            "matching_imageobject_count": 0,
            "matching_imageobjects": [],
            "asset_identity_ok": False,
            "license_present": False,
        }
    )
    direct_source = {"status": "NOT_REQUIRED", "readback_ok": True, "attempts": 0, "rate_limited": False}
    if direct_source_url:
        direct_source = _read_binary_head(direct_source_url, timeout)
    direct_source_effective_ok, direct_source_fallback_reason = _effective_direct_source_status(
        source_url=source_url,
        direct_source_url=direct_source_url,
        direct_source=direct_source,
        provenance_asset=provenance_asset,
    )

    ok = bool(
        internal_gate
        and article.get("readback_ok")
        and article_binding.get("article_image_bound")
        and public_image.get("readback_ok")
        and provenance_source.get("readback_ok")
        and direct_source_effective_ok
    )
    article.pop("body", None)
    provenance_source.pop("body", None)
    return {
        "status": "PASS" if ok else "FAILED",
        "readback_ok": ok,
        "publication_authority": "NONE",
        "internal_truth_gate": internal_gate,
        "rights_basis": rights_basis,
        "article": article,
        "article_binding": article_binding,
        "public_image": public_image,
        "provenance_source": provenance_source,
        "provenance_asset": provenance_asset,
        "direct_source": direct_source,
        "direct_source_effective_ok": direct_source_effective_ok,
        "direct_source_fallback_reason": direct_source_fallback_reason,
    }


def main() -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Read-only visual/provenance auditor for Core v2")
    parser.add_argument("--article-url", required=True)
    parser.add_argument("--image-path", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--direct-source-url")
    parser.add_argument("--rights-basis", required=True)
    parser.add_argument("--internal-real-visual-evidence", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = read_visual(
        article_url=args.article_url,
        image_path=args.image_path,
        source_url=args.source_url,
        direct_source_url=args.direct_source_url,
        rights_basis=args.rights_basis,
        internal_real_visual_evidence=args.internal_real_visual_evidence,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["readback_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
