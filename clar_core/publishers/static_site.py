from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from clar_core.contracts import PublicationReceipt, Story


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _safe_media(story: Story) -> dict | None:
    media = story.metadata.get("media") if story.metadata else None
    if not isinstance(media, dict):
        return None
    if media.get("rights_status") != "VERIFIED_REUSABLE":
        return None
    if not media.get("image_url") or not media.get("source_page"):
        return None
    return media


class StaticSitePublisher:
    """Materialize a Story as a static article route plus a tiny index.

    This publisher deliberately reports ``rendered`` even when ``base_url`` is
    configured. A configured public URL is an intended destination, not proof
    that the bytes are reachable over public HTTP. External/live verification
    is responsible for promoting publication truth.
    """

    def __init__(self, *, root: str | Path, product_name: str, base_url: str | None = None) -> None:
        self.root = Path(root)
        self.product_name = product_name
        self.base_url = base_url.rstrip("/") + "/" if base_url else None

    def __call__(self, story: Story) -> PublicationReceipt:
        route = f"stiri/{story.slug}/"
        article_dir = self.root / route
        article_dir.mkdir(parents=True, exist_ok=True)
        canonical = urljoin(self.base_url, route) if self.base_url else "/" + route
        source_links = "".join(
            f'<li><a href="{_esc(url)}" rel="noopener noreferrer">Sursa oficială</a></li>' for url in story.source_urls
        )
        paragraphs = "".join(f"<p>{_esc(p)}</p>" for p in story.paragraphs)
        media = _safe_media(story)
        media_html = ""
        og_image = ""
        if media:
            creator = _esc(media.get("creator") or "sursă indicată")
            license_name = _esc(media.get("license") or "licență verificată")
            license_url = media.get("license_url")
            license_html = (
                f'<a href="{_esc(license_url)}" rel="license noopener noreferrer">{license_name}</a>'
                if license_url
                else license_name
            )
            media_html = (
                '<figure class="story-media">'
                f'<img src="{_esc(media["image_url"])}" alt="{_esc(media.get("alt") or story.headline)}" '
                'loading="eager" decoding="async">'
                '<figcaption>'
                f'{_esc(media.get("caption") or "Imagine de context.")} '
                f'Foto: <a href="{_esc(media["source_page"])}" rel="noopener noreferrer">{creator}</a> · {license_html}.'
                '</figcaption></figure>'
            )
            og_image = f'<meta property="og:image" content="{_esc(media["image_url"])}">\n'

        schema = {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": story.headline,
            "datePublished": story.published_at.isoformat(),
            "dateModified": (story.updated_at or story.published_at).isoformat(),
            "mainEntityOfPage": canonical,
            "publisher": {"@type": "Organization", "name": self.product_name},
        }
        if media:
            schema["image"] = [media["image_url"]]
        document = f"""<!doctype html>
<html lang="ro">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(story.headline)} — {_esc(self.product_name)}</title>
<meta name="description" content="{_esc(story.dek)}">
<link rel="canonical" href="{_esc(canonical)}">
<meta property="og:type" content="article">
<meta property="og:title" content="{_esc(story.headline)}">
<meta property="og:description" content="{_esc(story.dek)}">
<meta property="og:url" content="{_esc(canonical)}">
{og_image}<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>
<style>
body{{font-family:Arial,sans-serif;margin:0;color:#171717;background:#fff}}main{{max-width:760px;margin:auto;padding:32px 20px 64px}}header.site{{border-bottom:1px solid #ddd;padding:18px 20px;font-weight:800;letter-spacing:.04em}}.section{{font-size:.78rem;font-weight:700;letter-spacing:.08em}}h1{{font-size:clamp(2rem,7vw,3.8rem);line-height:1.02;margin:.35em 0}}.dek{{font-size:1.2rem;line-height:1.5;color:#444}}article p{{font-size:1.08rem;line-height:1.7}}.meta,.sources{{color:#666;font-size:.9rem}}a{{color:inherit}}.story-media{{margin:24px 0}}.story-media img{{display:block;width:100%;height:auto;max-height:520px;object-fit:cover}}.story-media figcaption{{font-size:.82rem;line-height:1.45;color:#666;margin-top:8px}}
</style>
</head>
<body>
<header class="site">{_esc(self.product_name)}</header>
<main>
<div class="section">{_esc(story.section)}</div>
<h1>{_esc(story.headline)}</h1>
<p class="dek">{_esc(story.dek)}</p>
<p class="meta">Publicat: {_esc(story.published_at.isoformat())}</p>
{media_html}<article>{paragraphs}</article>
<section class="sources"><h2>Surse</h2><ul>{source_links}</ul></section>
</main>
</body>
</html>
"""
        (article_dir / "index.html").write_text(document, encoding="utf-8")

        manifest_path = self.root / "stories.json"
        manifest = {"stories": []}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                manifest = {"stories": []}
        rows = [row for row in manifest.get("stories", []) if row.get("story_id") != story.story_id]
        row = {
            "story_id": story.story_id,
            "slug": story.slug,
            "headline": story.headline,
            "dek": story.dek,
            "canonical_url": canonical,
            "published_at": story.published_at.isoformat(),
            "section": story.section,
        }
        if media:
            row["media"] = {
                "asset_id": media.get("asset_id"),
                "image_url": media.get("image_url"),
                "source_page": media.get("source_page"),
                "creator": media.get("creator"),
                "license": media.get("license"),
                "license_url": media.get("license_url"),
                "alt": media.get("alt"),
                "caption": media.get("caption"),
                "specificity": media.get("specificity"),
                "rights_status": media.get("rights_status"),
            }
        rows.append(row)
        rows.sort(key=lambda item: item.get("published_at", ""), reverse=True)
        previous_rows = manifest.get("stories", []) if isinstance(manifest, dict) else []
        generated_at = (
            manifest.get("generated_at")
            if isinstance(manifest, dict) and previous_rows == rows and manifest.get("generated_at")
            else datetime.now(timezone.utc).isoformat()
        )
        manifest = {"generated_at": generated_at, "stories": rows}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._write_index(manifest)
        return PublicationReceipt(
            story_id=story.story_id,
            canonical_url=canonical,
            published_at=datetime.now(timezone.utc),
            destination="static_site",
            status="rendered",
            metadata={"route": "/" + route, "public_url_candidate": canonical if self.base_url else None},
        )

    def _write_index(self, manifest: dict) -> None:
        cards = []
        for row in manifest.get("stories", [])[:20]:
            cards.append(
                f'<article><div class="section">{_esc(row.get("section", ""))}</div>'
                f'<h2><a href="/stiri/{_esc(row["slug"])}/">{_esc(row["headline"])}</a></h2>'
                f'<p>{_esc(row.get("dek", ""))}</p></article>'
            )
        index = f"""<!doctype html><html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_esc(self.product_name)}</title><style>body{{font-family:Arial,sans-serif;margin:0;color:#171717}}header,main{{max-width:900px;margin:auto;padding:24px}}header{{font-weight:900;font-size:1.5rem;border-bottom:1px solid #ddd}}article{{padding:24px 0;border-bottom:1px solid #ddd}}h2{{font-size:clamp(1.5rem,5vw,2.4rem);margin:.3em 0}}a{{color:inherit;text-decoration:none}}.section{{font-size:.78rem;font-weight:700;letter-spacing:.08em}}</style></head><body><header>{_esc(self.product_name)}</header><main>{''.join(cards)}</main></body></html>"""
        (self.root / "index.html").write_text(index, encoding="utf-8")
