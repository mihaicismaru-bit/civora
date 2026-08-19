#!/usr/bin/env python3
"""Private newsroom and public media projections for LOCAL NEWS OS vNext."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import tempfile
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote

from knowledge_runtime import KnowledgeNewsroomApp, KnowledgePublicApp
from media_intelligence import (
    DEFAULT_USAGE_SCOPES,
    RIGHTS_BASES,
    SPECIFICITY_ORDER,
    bind_media_asset,
    ensure_media_schema,
    list_media_assets,
    list_media_debt,
    project_story_media,
    register_media_asset,
    resolve_story_media,
)
from runtime_store import connect, create_story, initialize, register_instance, utc_now
from site_publication import ensure_publication_schema
from site_runtime import StartResponse, _safe_int


class MediaNewsroomApp(KnowledgeNewsroomApp):
    """Adds Photo Atlas, media selection and photo-debt visibility to /newsroom."""

    def _render_media(self, assets: list[dict[str, Any]], debt: list[dict[str, Any]]) -> bytes:
        asset_rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(item['media_kind']))}</td>"
            f"<td>{html.escape(str(item['asset_id']))}</td>"
            f"<td>{html.escape(str(item['rights_basis']))}</td>"
            f"<td>{html.escape(str(item['freshness_class']))}</td>"
            f"<td>{html.escape(str(item['credit']))}</td>"
            "</tr>"
            for item in assets
        ) or '<tr><td colspan="5">No media assets yet</td></tr>'
        debt_rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(item['story_id']))}</td>"
            f"<td>{html.escape(str(item['usage_scope']))}</td>"
            f"<td>{html.escape(str(item['reason']))}</td>"
            f"<td>{html.escape(str(item['updated_at']))}</td>"
            "</tr>"
            for item in debt
        ) or '<tr><td colspan="4">No open photo debt</td></tr>'
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Media · Newsroom</title><style>body{font-family:system-ui,sans-serif;max-width:1180px;margin:2rem auto;padding:0 1rem;color:#171717}"
            "table{width:100%;border-collapse:collapse;margin-bottom:2rem}th,td{border-bottom:1px solid #ddd;text-align:left;padding:.65rem;vertical-align:top}</style></head><body>"
            "<p><a href=\"/newsroom\">← Newsroom</a></p><h1>Photo Atlas / Media Intelligence</h1>"
            "<h2>Assets</h2><table><thead><tr><th>Kind</th><th>Asset</th><th>Rights</th><th>Freshness</th><th>Credit</th></tr></thead>"
            f"<tbody>{asset_rows}</tbody></table>"
            "<h2>Open photo debt</h2><table><thead><tr><th>Story</th><th>Usage</th><th>Reason</th><th>Updated</th></tr></thead>"
            f"<tbody>{debt_rows}</tbody></table></body></html>"
        ).encode("utf-8")

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        path = str(environ.get("PATH_INFO") or "/")
        media_route = (
            path == "/newsroom/media"
            or path == "/newsroom/api/media"
            or path == "/newsroom/api/media/debt"
            or path.startswith("/newsroom/api/media/story/")
        )
        if not media_route:
            return super().__call__(environ, start_response)
        if method != "GET":
            return self._json_response(
                start_response,
                "405 Method Not Allowed",
                {"error": "method_not_allowed"},
                private=True,
                extra_headers=[("Allow", "GET")],
            )
        denied = self._require_newsroom_auth(environ, start_response)
        if denied is not None:
            return denied
        conn = self._connect()
        try:
            ensure_media_schema(conn)
            if path == "/newsroom/media":
                return self._response(
                    start_response,
                    "200 OK",
                    self._render_media(
                        list_media_assets(conn, instance_id=self.instance_id, limit=500),
                        list_media_debt(conn, instance_id=self.instance_id, status="OPEN", limit=500),
                    ),
                    content_type="text/html; charset=utf-8",
                    private=True,
                )
            if path == "/newsroom/api/media":
                query = parse_qs(str(environ.get("QUERY_STRING") or ""))
                status = (query.get("status") or [None])[0]
                limit = _safe_int((query.get("limit") or [None])[0], default=100, minimum=1, maximum=1000)
                return self._json_response(
                    start_response,
                    "200 OK",
                    {"assets": list_media_assets(conn, instance_id=self.instance_id, status=status, limit=limit)},
                    private=True,
                )
            if path == "/newsroom/api/media/debt":
                query = parse_qs(str(environ.get("QUERY_STRING") or ""))
                status = str((query.get("status") or ["OPEN"])[0]).upper()
                limit = _safe_int((query.get("limit") or [None])[0], default=100, minimum=1, maximum=1000)
                return self._json_response(
                    start_response,
                    "200 OK",
                    {"debt": list_media_debt(conn, instance_id=self.instance_id, status=status, limit=limit)},
                    private=True,
                )
            story_id = unquote(path[len("/newsroom/api/media/story/") :]).strip("/")
            projection = project_story_media(conn, instance_id=self.instance_id, story_id=story_id, usage_scope="SITE_HERO")
            if projection is None:
                return self._json_response(start_response, "404 Not Found", {"error": "media_selection_not_found"}, private=True)
            return self._json_response(start_response, "200 OK", projection, private=True)
        finally:
            conn.close()


class MediaPublicApp(KnowledgePublicApp):
    """Binds site-owned media selections into public story rendering."""

    def _media_fragment(self, story_id: str) -> str:
        conn = connect(self.db_path)
        try:
            ensure_media_schema(conn)
            projection = project_story_media(conn, instance_id=self.instance_id, story_id=story_id, usage_scope="SITE_HERO")
        finally:
            conn.close()
        if projection is None:
            return ""
        selection = projection["selection"]
        if selection["selection_kind"] == "ASSET" and projection.get("asset"):
            asset = projection["asset"]
            derivatives = projection.get("derivatives") or []
            preferred = next((item for item in derivatives if str(item.get("variant")) == "SITE_HERO_1600X900"), None)
            uri = str((preferred or {}).get("storage_uri") or asset.get("metadata", {}).get("public_url") or asset.get("storage_uri") or "")
            if not uri.startswith(("http://", "https://")):
                return ""
            alt = html.escape(str(asset.get("metadata", {}).get("alt") or "Imagine editorială verificată"))
            credit = html.escape(str(asset.get("credit") or ""))
            license_code = html.escape(str(asset.get("license_code") or ""))
            disclosure = html.escape(str(selection.get("context_disclosure") or ""))
            caption_parts = [part for part in (credit, license_code, disclosure) if part]
            caption = " · ".join(caption_parts)
            return (
                f"<figure data-specificity=\"{html.escape(str(selection.get('specificity_class') or ''))}\">"
                f"<img src=\"{html.escape(uri)}\" alt=\"{alt}\" loading=\"eager\">"
                f"<figcaption>{caption}</figcaption></figure>"
            )
        if selection["selection_kind"] == "EDITORIAL_CARD":
            payload = selection.get("fallback_payload") or {}
            return (
                "<aside class=\"editorial-fact-card\" data-depicts-real-scene=\"false\">"
                f"<strong>{html.escape(str(payload.get('headline') or ''))}</strong>"
                f"<p>{html.escape(str(payload.get('dek') or ''))}</p>"
                "<small>Card editorial · nu reprezintă o fotografie a evenimentului</small></aside>"
            )
        return ""

    def _story_html(self, item: dict[str, Any]) -> str:
        base = super()._story_html(item)
        story_id = str((item.get("snapshot") or {}).get("story_id") or item.get("story_id") or "")
        if not story_id:
            return base
        fragment = self._media_fragment(story_id)
        return base.replace("<h2>Surse</h2>", fragment + "<h2>Surse</h2>", 1) if fragment else base


def _manifest(instance_id: str, domain: str, marker: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": marker * 64,
        "runtime": {"owner": "site_application", "repository_runtime_state_enabled": False},
    }


def _source(label: str) -> list[dict[str, str]]:
    return [{
        "source_url": f"https://example.invalid/{label}",
        "evidence_fingerprint": hashlib.sha256(label.encode("utf-8")).hexdigest(),
        "observed_at": "2026-08-19T12:00:00Z",
    }]


def _policy(instance_id: str) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "pack_type": "photos",
        "instance_id": instance_id,
        "resolver_policy": {
            "allowed_usage_scopes": sorted(DEFAULT_USAGE_SCOPES),
            "allowed_rights_bases": sorted(RIGHTS_BASES),
            "specificity_order": list(SPECIFICITY_ORDER),
            "fallback": "EDITORIAL_CARD",
        },
        "assets": [],
    }


def _publish_fixture(conn, *, instance_id: str, story_id: str, headline: str) -> None:
    create_story(conn, instance_id=instance_id, story_id=story_id, fingerprint=hashlib.sha256(story_id.encode()).hexdigest(), engine_version="p13-web-test", headline=headline)
    now = utc_now()
    conn.execute("UPDATE stories SET state='PUBLISHED',canonical_path=?,updated_at=? WHERE instance_id=? AND story_id=?", (f"/story/{story_id}/", now, instance_id, story_id))
    conn.execute(
        """
        INSERT INTO story_publications(instance_id,story_id,publication_id,canonical_path,current_revision,current_content_fingerprint,published_at,updated_at)
        VALUES (?,?,?,?,1,?,?,?)
        """,
        (instance_id, story_id, f"pub-{story_id}", f"/story/{story_id}/", hashlib.sha256((story_id+"pub").encode()).hexdigest(), now, now),
    )
    conn.commit()


def _call(app, path: str, *, token: str | None = None) -> tuple[str, dict[str, str], bytes]:
    captured: dict[str, Any] = {}
    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)
    environ: dict[str, Any] = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": ""}
    if token is not None:
        environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    body = b"".join(app(environ, start_response))
    return str(captured["status"]), dict(captured["headers"]), body


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "runtime.sqlite3"
        conn = connect(db)
        initialize(conn)
        ensure_publication_schema(conn)
        ensure_media_schema(conn)
        register_instance(conn, _manifest("alpha-local", "alpha.invalid", "a"), engine_version="p13-web-test")
        _publish_fixture(conn, instance_id="alpha-local", story_id="story-one", headline="Verified local story")
        asset, _ = register_media_asset(
            conn,
            instance_id="alpha-local",
            asset={
                "asset_id": "hero-photo",
                "media_kind": "PHOTO",
                "storage_uri": "https://media.invalid/hero.jpg",
                "source_type": "USER_OWNED",
                "rights_basis": "USER_OWNED",
                "license_code": "OWNED",
                "credit": "Example newsroom",
                "rights_evidence": "OWNERSHIP:ledger-1",
                "synthetic": False,
                "depicts_real_scene": True,
                "freshness_class": "EVERGREEN",
                "usage_scopes": ["SITE_HERO"],
                "metadata": {"alt": "Verified scene"},
                "content_fingerprint": hashlib.sha256(b"hero-photo").hexdigest(),
                "status": "READY",
                "provenance": _source("hero-photo"),
            },
            media_policy=_policy("alpha-local"),
            engine_version="p13-web-test",
        )
        bind_media_asset(conn, instance_id="alpha-local", asset_id=asset["asset_id"], target_type="STORY", target_id="story-one", specificity_class="SUBJECT_DIRECT", provenance=_source("hero-binding"), engine_version="p13-web-test")
        resolve_story_media(conn, instance_id="alpha-local", story_id="story-one", usage_scope="SITE_HERO", media_policy=_policy("alpha-local"), engine_version="p13-web-test")
        conn.close()

        newsroom = MediaNewsroomApp(db_path=db, instance_id="alpha-local", engine_version="p13-web-test", newsroom_token="secret-token")
        status, headers, _ = _call(newsroom, "/newsroom/api/media")
        assert status.startswith("401") and "no-store" in headers["Cache-Control"]
        status, headers, body = _call(newsroom, "/newsroom/api/media", token="secret-token")
        assert status.startswith("200") and "noindex" in headers["X-Robots-Tag"]
        assert json.loads(body)["assets"][0]["asset_id"] == "hero-photo"
        status, _, body = _call(newsroom, "/newsroom/media", token="secret-token")
        assert status.startswith("200") and b"Photo Atlas / Media Intelligence" in body

        publication_pack = {
            "schema_version": "2.0",
            "pack_type": "publication",
            "instance_id": "alpha-local",
            "name": "Alpha Publication",
            "canonical_domain": "alpha.invalid",
            "publication_model": "continuous_story_first",
            "public_runtime": {
                "story_path_prefix": "/story",
                "category_path_prefix": "/category",
                "profile_path_prefix": "/profiles",
                "homepage_limit": 20,
                "feed_limit": 50,
                "sitemap_limit": 10000,
            },
        }
        public = MediaPublicApp(db_path=db, instance_id="alpha-local", publication_pack=publication_pack)
        rendered = public._story_html({
            "canonical_path": "/story/story-one/",
            "snapshot": {
                "story_id": "story-one",
                "headline": "Verified local story",
                "dek": "Grounded summary.",
                "body_blocks": [{"text": "Verified fact."}],
                "source_references": [],
                "section": "LOCAL",
            },
        })
        assert "https://media.invalid/hero.jpg" in rendered and "Example newsroom" in rendered
    print("LOCAL_NEWS_OS_VNEXT_MEDIA_RUNTIME_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("use --self-test; production invocation is owned by the site runtime")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
