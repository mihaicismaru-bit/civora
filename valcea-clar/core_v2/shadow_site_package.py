from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import time
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from visual_readback import inspect_article_image


MODE = "SHADOW_SITE_PACKAGE_BINDING"
MAX_IMAGE_BYTES = 15 * 1024 * 1024
USER_AGENT = "CIVORA-Core-v2-shadow-package/1.1"
REMOTE_RETRY_DELAYS = (0.0, 2.0, 8.0)


def _article_index(documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for document in documents:
        for row in document.get("rows") or []:
            if row.get("state") != "VERIFIED_WRITTEN_SHADOW":
                continue
            articles = row.get("articles")
            if isinstance(articles, list):
                for article in articles:
                    if isinstance(article, dict) and article.get("article_id"):
                        result[str(article["article_id"])] = article
                continue
            article_id = row.get("article_id") or row.get("detail_id") or row.get("story_id")
            if article_id:
                result[str(article_id)] = row
    return result


def _paragraphs(text: str) -> str:
    parts = [part.strip() for part in str(text or "").split("\n\n") if part.strip()]
    return "\n".join(f"<p>{html.escape(part)}</p>" for part in parts)


def _read_existing_materialized(target: Path, *, filename: str, direct: str) -> dict[str, Any] | None:
    if not target.is_file() or target.stat().st_size <= 0:
        return None
    payload = target.read_bytes()
    return {
        "filename": filename,
        "path": str(target),
        "mode": "shadow_cache_reuse",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "source_url": direct,
    }


def _content_range_total(value: str | None) -> int | None:
    match = re.fullmatch(r"bytes\s+\d+-\d+/(\d+|\*)", str(value or "").strip(), re.IGNORECASE)
    if not match or match.group(1) == "*":
        return None
    return int(match.group(1))


def _download_remote_image(direct: str) -> tuple[bytes, str, int]:
    """Materialize one already-proven image with a bounded Range read.

    The photo truth gate performs a tiny external binary readback first. A second
    immediate unrestricted GET can be throttled by image CDNs (notably Commons),
    so this stage requests only the bounded byte range it is willing to accept.
    HTTP 429 remains fail-closed after a short bounded retry window.
    """
    last_error: Exception | None = None
    for attempt, delay in enumerate(REMOTE_RETRY_DELAYS, start=1):
        if delay:
            time.sleep(delay)
        request = Request(
            direct,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "image/*",
                "Range": f"bytes=0-{MAX_IMAGE_BYTES - 1}",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                status = int(getattr(response, "status", 0) or 0)
                content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
                if status not in {200, 206}:
                    raise ValueError(f"direct source returned unexpected HTTP status {status}")
                if not content_type.startswith("image/"):
                    raise ValueError("direct source did not return image content")
                total = _content_range_total(response.headers.get("Content-Range")) if status == 206 else None
                if total is not None and total > MAX_IMAGE_BYTES:
                    raise ValueError("direct image exceeds shadow materialization size cap")
                payload = response.read(MAX_IMAGE_BYTES + 1)
                if len(payload) > MAX_IMAGE_BYTES:
                    raise ValueError("direct image exceeds shadow materialization size cap")
                if not payload:
                    raise ValueError("direct image returned an empty payload")
                # A partial 206 whose total is larger than the bytes returned is not a complete image.
                if status == 206 and total is not None and len(payload) != total:
                    raise ValueError("bounded range did not return the complete image")
                return payload, content_type, attempt
        except HTTPError as exc:
            last_error = exc
            if exc.code != 429 or attempt == len(REMOTE_RETRY_DELAYS):
                raise
        except Exception as exc:
            last_error = exc
            raise
    if last_error is not None:
        raise last_error
    raise ValueError("remote image materialization exhausted without result")


def _materialize_image(
    visual_assignment: dict[str, Any],
    *,
    repo_root: Path,
    output_dir: Path,
    allow_remote_materialization: bool,
) -> dict[str, Any]:
    image = visual_assignment.get("image") or {}
    image_path = str(visual_assignment.get("image_path") or "").strip()
    if not image_path:
        raise ValueError("visual image_path missing")
    filename = PurePosixPath(image_path).name
    target_dir = output_dir / "media"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename

    local = repo_root / image_path
    if local.is_file() and local.stat().st_size > 0:
        shutil.copyfile(local, target)
        payload = target.read_bytes()
        return {
            "filename": filename,
            "path": str(target),
            "mode": "checkout_copy",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    if not allow_remote_materialization:
        raise ValueError("visual image file missing from checkout")

    direct = str(image.get("direct_source_url") or "").strip()
    if not direct.startswith("https://"):
        raise ValueError("verified direct_source_url required for shadow materialization")

    cached = _read_existing_materialized(target, filename=filename, direct=direct)
    if cached is not None:
        return cached

    payload, content_type, attempts = _download_remote_image(direct)
    target.write_bytes(payload)
    return {
        "filename": filename,
        "path": str(target),
        "mode": "verified_remote_bounded_read_only",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "source_url": direct,
        "content_type": content_type,
        "attempts": attempts,
    }


def render_shadow_article(article: dict[str, Any], *, visual_assignment: dict[str, Any], filename: str) -> str:
    package = article.get("article_package") or {}
    image = visual_assignment.get("image") or {}
    headline = str(package.get("headline") or "").strip()
    dek = str(package.get("dek") or "").strip()
    body = str(package.get("body") or "").strip()
    alt = str(image.get("alt_text") or "").strip()
    credit = str(image.get("credit") or "").strip()
    disclosure = str(image.get("editorial_note") or "").strip()
    source_url = str(image.get("source_url") or "").strip()

    if not headline or not body or not alt or not credit or not disclosure or not source_url:
        raise ValueError("article/visual package incomplete")

    return f"""<!doctype html>
<html lang="ro">
<head><meta charset="utf-8"><title>{html.escape(headline)}</title></head>
<body>
<article data-core-v2-shadow="true">
<h1>{html.escape(headline)}</h1>
<p class="dek">{html.escape(dek)}</p>
<figure>
<img src="/media/{html.escape(filename)}" alt="{html.escape(alt)}">
<figcaption>{html.escape(disclosure)} Credit: <a href="{html.escape(source_url)}">{html.escape(credit)}</a></figcaption>
</figure>
{_paragraphs(body)}
</article>
</body>
</html>
"""


def build_shadow_packages(
    article_documents: list[dict[str, Any]],
    *,
    photo_truth: dict[str, Any],
    visual_registry: dict[str, Any],
    repo_root: Path,
    output_dir: Path,
    allow_remote_materialization: bool = False,
) -> dict[str, Any]:
    articles = _article_index(article_documents)
    assignments = visual_registry.get("stories") or {}
    rows: list[dict[str, Any]] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for photo_row in photo_truth.get("rows") or []:
        if photo_row.get("status") != "VISUAL_CANDIDATE_VERIFIED_SHADOW":
            continue
        story_id = str(photo_row.get("story_id") or "").strip()
        row = {
            "story_id": story_id,
            "mode": MODE,
            "publication_authority": "NONE",
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "visual_ready": False,
            "public_article_binding_verified": False,
        }
        article = articles.get(story_id)
        assignment = assignments.get(story_id)
        if not isinstance(article, dict):
            rows.append({**row, "status": "BLOCKED", "reason": "written_article_not_found"})
            continue
        if not isinstance(assignment, dict):
            rows.append({**row, "status": "BLOCKED", "reason": "visual_assignment_not_found"})
            continue
        if not bool((photo_row.get("external_readback") or {}).get("readback_ok")):
            rows.append({**row, "status": "BLOCKED", "reason": "photo_external_readback_not_verified"})
            continue
        try:
            materialized = _materialize_image(
                assignment,
                repo_root=repo_root,
                output_dir=output_dir,
                allow_remote_materialization=allow_remote_materialization,
            )
            rendered = render_shadow_article(article, visual_assignment=assignment, filename=materialized["filename"])
        except Exception as exc:
            rows.append({**row, "status": "BLOCKED", "reason": str(exc)})
            continue

        article_dir = output_dir / story_id
        article_dir.mkdir(parents=True, exist_ok=True)
        article_path = article_dir / "index.html"
        article_path.write_text(rendered, encoding="utf-8")
        binding = inspect_article_image(
            rendered,
            article_url=f"https://shadow.invalid/stiri/{story_id}/",
            expected_filename=materialized["filename"],
        )
        if not binding.get("article_image_bound"):
            rows.append({**row, "status": "BLOCKED", "reason": "staged_html_image_binding_failed", "binding": binding})
            continue
        rows.append(
            {
                **row,
                "status": "PACKAGE_IMAGE_BOUND_SHADOW",
                "reason": None,
                "staged_package_binding_verified": True,
                "package_path": str(article_path),
                "expected_image_filename": materialized["filename"],
                "materialized_image": materialized,
                "binding": binding,
                "truth_note": "Internal staged HTML/image binding only; no public HTTP delivery or public article image readback has occurred.",
            }
        )

    passed = sum(row.get("status") == "PACKAGE_IMAGE_BOUND_SHADOW" for row in rows)
    blocked = sum(row.get("status") == "BLOCKED" for row in rows)
    return {
        "schema_version": "1.3",
        "mode": MODE,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "visual_ready": False,
        "public_article_binding_verified": False,
        "candidate_count": len(rows),
        "package_image_bound_shadow_count": passed,
        "blocked_count": blocked,
        "rows": rows,
        "truth_rule": (
            "A staged HTML package may prove that the intended real photograph is wired into the future article package. "
            "Verified remote materialization is read-only, byte-bounded and temporary; duplicate assignments reuse the staged byte copy, "
            "and transient HTTP 429 is retried only within a short bounded window. It never proves public delivery, public image binding or VISUAL_READY. "
            "Those require a later production-authorized public HTTP readback."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and verify non-public Core v2 article/image packages")
    parser.add_argument("--articles", action="append", default=[], required=True)
    parser.add_argument("--photo-truth", required=True)
    parser.add_argument("--visual-registry", default="valcea-clar/core_v2/visual_registry.json")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    article_documents = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.articles]
    report = build_shadow_packages(
        article_documents,
        photo_truth=json.loads(Path(args.photo_truth).read_text(encoding="utf-8")),
        visual_registry=json.loads(Path(args.visual_registry).read_text(encoding="utf-8")),
        repo_root=Path(args.repo_root),
        output_dir=Path(args.output_dir),
        allow_remote_materialization=True,
    )
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS_SHADOW",
        "candidate_count": report["candidate_count"],
        "package_image_bound_shadow_count": report["package_image_bound_shadow_count"],
        "blocked_count": report["blocked_count"],
        "public_article_binding_verified": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
