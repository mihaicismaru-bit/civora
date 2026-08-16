#!/usr/bin/env python3
"""Generate fail-closed robots.txt and sitemap.xml for a static LOCAL NEWS OS runtime.

The caller supplies canonical public routes. A route is admitted only when the
corresponding static index.html exists, so the sitemap cannot advertise a page
that the generated runtime does not actually contain. The module is instance-
agnostic; brand/domain/routes remain instance data.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit
from xml.sax.saxutils import escape


def _base_url(value: str) -> str:
    base = str(value or "").strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
        raise ValueError("base_url must be an HTTPS origin without a path")
    return base


def _route(value: str) -> str:
    route = str(value or "").strip()
    if not route.startswith("/") or "?" in route or "#" in route or "//" in route:
        raise ValueError(f"invalid canonical route: {route!r}")
    if route != "/" and not route.endswith("/"):
        route += "/"
    return route


def _index_for(runtime_dir: Path, route: str) -> Path:
    if route == "/":
        return runtime_dir / "index.html"
    return runtime_dir / route.strip("/") / "index.html"


def write_indexing_assets(runtime_dir: Path, base_url: str, routes: list[str]) -> dict:
    """Write robots.txt and sitemap.xml for verified static routes.

    Raises instead of silently emitting a broken sitemap when a requested route
    has no corresponding static page. Duplicate routes are collapsed while the
    first-seen order is preserved.
    """
    runtime = Path(runtime_dir).resolve()
    if not runtime.is_dir():
        raise RuntimeError(f"runtime directory missing: {runtime}")
    base = _base_url(base_url)

    admitted: list[str] = []
    seen: set[str] = set()
    for raw in routes:
        route = _route(raw)
        if route in seen:
            continue
        page = _index_for(runtime, route).resolve()
        if runtime != page and runtime not in page.parents:
            raise RuntimeError(f"route escapes runtime: {route}")
        if not page.is_file():
            raise RuntimeError(f"refusing sitemap route without static page: {route}")
        seen.add(route)
        admitted.append(route)

    if "/" not in seen:
        raise RuntimeError("refusing indexing assets without canonical homepage route")

    urls = "\n".join(
        f"  <url><loc>{escape(base + route)}</loc></url>" for route in admitted
    )
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n"
    )
    sitemap_path = runtime / "sitemap.xml"
    sitemap_path.write_text(sitemap, encoding="utf-8")

    robots = (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    robots_path = runtime / "robots.txt"
    robots_path.write_text(robots, encoding="utf-8")

    return {
        "status": "PASS",
        "routes": admitted,
        "route_count": len(admitted),
        "robots": robots_path.as_posix(),
        "sitemap": sitemap_path.as_posix(),
    }
