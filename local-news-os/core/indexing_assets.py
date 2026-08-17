#!/usr/bin/env python3
"""Generate fail-closed robots.txt and sitemap.xml for a static LOCAL NEWS OS runtime.

The caller supplies canonical dynamic/public routes. An instance may also keep a
`site/indexing_routes.json` contract next to its runtime directory for durable
static routes (legal pages, venue guides, future section landings).

Dynamic routes supplied by the caller are always strict: a missing page raises.
Configured static routes are also strict at finalization time, but an early
story-render pass may legitimately run before those independent static products
have been materialized. In that case this module returns an explicit DEFERRED
state and writes no new indexing assets, rather than emitting a broken sitemap
or blocking the remaining deterministic export steps.
"""
from __future__ import annotations

import json
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


def _configured_static_routes(runtime_dir: Path) -> list[str]:
    """Read optional instance-level routes that every indexing refresh preserves."""
    contract = runtime_dir.parent / "indexing_routes.json"
    if not contract.is_file():
        return []
    try:
        doc = json.loads(contract.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"invalid indexing route contract: {contract}: {exc}") from exc
    routes = doc.get("routes")
    if not isinstance(routes, list):
        raise RuntimeError("indexing route contract requires a routes list")
    policy = doc.get("policy") or {}
    if policy.get("require_static_index_html") is not True:
        raise RuntimeError("indexing route contract must require static index.html")
    return [str(route) for route in routes]


def write_indexing_assets(runtime_dir: Path, base_url: str, routes: list[str]) -> dict:
    """Write robots.txt and sitemap.xml for verified dynamic + static routes.

    Caller-owned routes must already exist and remain fail-closed. Instance-level
    configured static routes are appended after caller routes. If one of those
    configured routes is not materialized yet, indexing is explicitly deferred
    and existing robots/sitemap files are left untouched. A later finalization
    pass must call this function again after all static products exist.
    """
    runtime = Path(runtime_dir).resolve()
    if not runtime.is_dir():
        raise RuntimeError(f"runtime directory missing: {runtime}")
    base = _base_url(base_url)

    caller_routes = [_route(raw) for raw in routes]
    caller_set = set(caller_routes)
    configured_raw = _configured_static_routes(runtime)
    configured_routes = [_route(raw) for raw in configured_raw]
    configured_set = set(configured_routes)

    requested = caller_routes + configured_routes
    admitted: list[str] = []
    seen: set[str] = set()
    missing_configured: list[str] = []

    for route in requested:
        if route in seen:
            continue
        page = _index_for(runtime, route).resolve()
        if runtime != page and runtime not in page.parents:
            raise RuntimeError(f"route escapes runtime: {route}")
        if not page.is_file():
            if route in configured_set and route not in caller_set:
                missing_configured.append(route)
                seen.add(route)
                continue
            raise RuntimeError(f"refusing sitemap route without static page: {route}")
        seen.add(route)
        admitted.append(route)

    if "/" not in admitted:
        raise RuntimeError("refusing indexing assets without canonical homepage route")

    if missing_configured:
        return {
            "status": "DEFERRED_CONFIGURED_STATIC_MISSING",
            "routes": admitted,
            "route_count": len(admitted),
            "configured_static_routes": configured_raw,
            "missing_configured_static_routes": missing_configured,
            "robots": (runtime / "robots.txt").as_posix(),
            "sitemap": (runtime / "sitemap.xml").as_posix(),
            "indexing_assets_written": False,
        }

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
        "configured_static_routes": configured_raw,
        "missing_configured_static_routes": [],
        "robots": robots_path.as_posix(),
        "sitemap": sitemap_path.as_posix(),
        "indexing_assets_written": True,
    }
