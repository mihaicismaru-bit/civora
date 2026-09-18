from __future__ import annotations

import json
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


def _read_binary_head(url: str, timeout: float = 12.0) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "CIVORA-Core-v2-Auditor/1.0", "Range": "bytes=0-1023"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or 0)
            final_url = response.geturl()
            content_type = str(response.headers.get("Content-Type") or "")
            response.read(1024)
    except (HTTPError, URLError, TimeoutError) as exc:
        return {"status": "FAILED", "error": str(exc), "http_status": getattr(exc, "code", None), "readback_ok": False}
    image_type = content_type.lower().startswith("image/")
    return {
        "status": "PASS" if status in {200, 206} and image_type else "FAILED",
        "http_status": status,
        "final_url": final_url,
        "content_type": content_type,
        "readback_ok": bool(status in {200, 206} and image_type),
    }


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
    direct_source = {"status": "NOT_REQUIRED", "readback_ok": True}
    if direct_source_url:
        direct_source = _read_binary_head(direct_source_url, timeout)

    ok = bool(
        internal_gate
        and article.get("readback_ok")
        and article_binding.get("article_image_bound")
        and public_image.get("readback_ok")
        and provenance_source.get("readback_ok")
        and direct_source.get("readback_ok")
    )
    article.pop("body", None)
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
        "direct_source": direct_source,
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
