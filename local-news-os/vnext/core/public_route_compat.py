#!/usr/bin/env python3
"""Config-driven public route compatibility for LOCAL NEWS OS vNext.

This layer preserves public URL contracts without putting locality-specific
names or routes in generic core. Instance publication packs define any legacy
profile aliases and collection routes. Runtime content remains database-owned.
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

from knowledge_graph import (
    ensure_knowledge_schema,
    get_public_entity_by_path,
    list_entities,
    profile_path,
    project_public_profile,
)
from knowledge_runtime import KnowledgePublicApp
from runtime_store import connect
from site_publication import list_publications
from site_runtime import StartResponse


class PublicRouteCompatibilityError(RuntimeError):
    pass


def _clean_prefix(value: Any) -> str:
    prefix = str(value or "").strip()
    if not prefix.startswith("/") or prefix == "/" or "?" in prefix or "#" in prefix:
        raise PublicRouteCompatibilityError(f"invalid public route prefix: {prefix!r}")
    return prefix.rstrip("/")


def _clean_route(value: Any) -> str:
    route = str(value or "").strip()
    if not route.startswith("/") or "?" in route or "#" in route:
        raise PublicRouteCompatibilityError(f"invalid public route: {route!r}")
    if route == "/":
        return route
    return route.rstrip("/") + "/"


class RouteCompatiblePublicApp(KnowledgePublicApp):
    """Adds instance-configured legacy aliases and collection pages.

    No route name, entity name, locality, or domain is embedded here. This class
    can be reused by every publication instance with only publication-pack data.
    """

    def __init__(self, *, db_path: str | Path, instance_id: str, publication_pack: dict[str, Any]) -> None:
        super().__init__(db_path=db_path, instance_id=instance_id, publication_pack=publication_pack)
        public_runtime = publication_pack.get("public_runtime") or {}

        aliases = public_runtime.get("profile_route_aliases") or []
        if not isinstance(aliases, list):
            raise PublicRouteCompatibilityError("profile_route_aliases must be a list")
        self.profile_aliases: list[dict[str, str]] = []
        seen_types: set[str] = set()
        seen_prefixes: set[str] = set()
        for raw in aliases:
            if not isinstance(raw, dict):
                raise PublicRouteCompatibilityError("profile route alias must be an object")
            entity_type = str(raw.get("entity_type") or "").strip().upper()
            prefix = _clean_prefix(raw.get("path_prefix"))
            if not entity_type:
                raise PublicRouteCompatibilityError("profile alias entity_type is required")
            if entity_type in seen_types or prefix in seen_prefixes:
                raise PublicRouteCompatibilityError("duplicate profile route alias")
            seen_types.add(entity_type)
            seen_prefixes.add(prefix)
            self.profile_aliases.append({"entity_type": entity_type, "path_prefix": prefix})

        collections = public_runtime.get("collection_routes") or []
        if not isinstance(collections, list):
            raise PublicRouteCompatibilityError("collection_routes must be a list")
        self.collection_routes: list[dict[str, Any]] = []
        seen_collection_paths: set[str] = set()
        for raw in collections:
            if not isinstance(raw, dict):
                raise PublicRouteCompatibilityError("collection route must be an object")
            path = _clean_route(raw.get("path"))
            title = " ".join(str(raw.get("title") or "").split())
            entity_types = [str(v).strip().upper() for v in raw.get("entity_types") or [] if str(v).strip()]
            if not title or not entity_types:
                raise PublicRouteCompatibilityError("collection route requires title and entity_types")
            if path in seen_collection_paths:
                raise PublicRouteCompatibilityError("duplicate collection route")
            seen_collection_paths.add(path)
            self.collection_routes.append({"path": path, "title": title, "entity_types": entity_types})

        static_routes = public_runtime.get("sitemap_static_routes") or ["/"]
        if not isinstance(static_routes, list):
            raise PublicRouteCompatibilityError("sitemap_static_routes must be a list")
        self.sitemap_static_routes = [_clean_route(v) for v in static_routes]

    def _alias_profile(self, path: str, start_response: StartResponse) -> Iterable[bytes] | None:
        for spec in self.profile_aliases:
            prefix = spec["path_prefix"] + "/"
            if not path.startswith(prefix):
                continue
            slug = unquote(path[len(prefix):].strip("/"))
            if not slug or "/" in slug:
                return self._html(start_response, "404 Not Found", "<h1>Not found</h1>")
            conn = connect(self.db_path)
            try:
                ensure_knowledge_schema(conn)
                entity = get_public_entity_by_path(
                    conn,
                    instance_id=self.instance_id,
                    entity_type=spec["entity_type"],
                    slug=slug,
                )
                if entity is None:
                    return self._html(start_response, "404 Not Found", "<h1>Not found</h1>")
                profile = project_public_profile(conn, instance_id=self.instance_id, entity_id=entity["entity_id"])
                body = self._profile_html(profile)
                # The inherited renderer points canonical to the generic /profiles path.
                # Replace only that exact canonical href with the configured alias.
                generic_path = profile_path(entity, prefix=self.profile_path_prefix)
                alias_path = spec["path_prefix"] + "/" + str(entity["slug"]) + "/"
                body = body.replace(
                    f"https://{self.policy['canonical_domain']}{generic_path}",
                    f"https://{self.policy['canonical_domain']}{alias_path}",
                    1,
                )
                return self._html(start_response, "200 OK", body)
            finally:
                conn.close()
        return None

    def _collection(self, path: str, start_response: StartResponse) -> Iterable[bytes] | None:
        normalized = _clean_route(path)
        spec = next((item for item in self.collection_routes if item["path"] == normalized), None)
        if spec is None:
            return None
        conn = connect(self.db_path)
        try:
            ensure_knowledge_schema(conn)
            items: list[dict[str, Any]] = []
            for entity_type in spec["entity_types"]:
                items.extend(
                    list_entities(
                        conn,
                        instance_id=self.instance_id,
                        entity_type=entity_type,
                        public_only=True,
                        limit=1000,
                    )
                )
            items.sort(key=lambda item: (str(item.get("canonical_name") or "").casefold(), str(item.get("entity_id") or "")))
            cards = "".join(
                f"<article><h2>{html.escape(str(item['canonical_name']))}</h2>"
                f"<p>{html.escape(str(item.get('summary') or ''))}</p></article>"
                for item in items
            ) or "<p>Nu există înregistrări publice verificate.</p>"
            canonical = f"https://{html.escape(self.policy['canonical_domain'])}{html.escape(normalized)}"
            body = (
                "<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                f"<title>{html.escape(spec['title'])}</title><link rel=\"canonical\" href=\"{canonical}\"></head><body><main>"
                f"<h1>{html.escape(spec['title'])}</h1>{cards}</main></body></html>"
            )
            return self._html(start_response, "200 OK", body)
        finally:
            conn.close()

    def _compat_sitemap(self, start_response: StartResponse) -> Iterable[bytes]:
        conn = connect(self.db_path)
        try:
            ensure_knowledge_schema(conn)
            paths: set[str] = set(self.sitemap_static_routes)
            paths.update(
                item["canonical_path"]
                for item in list_publications(conn, instance_id=self.instance_id, limit=self.policy["sitemap_limit"])
            )
            alias_by_type = {item["entity_type"]: item["path_prefix"] for item in self.profile_aliases}
            for entity in list_entities(conn, instance_id=self.instance_id, public_only=True, limit=50000):
                entity_type = str(entity["entity_type"])
                prefix = alias_by_type.get(entity_type)
                if prefix:
                    paths.add(prefix + "/" + str(entity["slug"]) + "/")
                else:
                    paths.add(profile_path(entity, prefix=self.profile_path_prefix))
            paths.update(item["path"] for item in self.collection_routes)
            urls = "".join(
                f"<url><loc>https://{html.escape(self.policy['canonical_domain'])}{html.escape(path)}</loc></url>"
                for path in sorted(paths)
            )
            return self._xml(
                start_response,
                f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">{urls}</urlset>",
            )
        finally:
            conn.close()

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        path = str(environ.get("PATH_INFO") or "/")
        if method == "GET":
            if path == "/sitemap.xml":
                return self._compat_sitemap(start_response)
            profile = self._alias_profile(path, start_response)
            if profile is not None:
                return profile
            collection = self._collection(path, start_response)
            if collection is not None:
                return collection
        return super().__call__(environ, start_response)
