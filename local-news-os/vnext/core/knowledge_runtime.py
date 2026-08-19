#!/usr/bin/env python3
"""Private newsroom and public profile projections for the vNext knowledge graph.

This module extends the existing site-owned WSGI runtimes. It never reads
repository editorial state and contains no locality-specific routes or data.
"""
from __future__ import annotations

import argparse
import html
import json
import tempfile
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote

from knowledge_graph import (
    KnowledgeGraphError,
    ensure_knowledge_schema,
    get_entity,
    get_public_entity_by_path,
    list_entities,
    profile_path,
    project_public_profile,
    upsert_entity,
)
from runtime_store import connect, initialize, list_events, register_instance
from site_publication import PublicSiteApp
from site_runtime import SiteRuntimeApp, StartResponse, _safe_int


class KnowledgeNewsroomApp(SiteRuntimeApp):
    """Adds knowledge visibility to the private newsroom without changing auth."""

    def _entity_record(self, conn, entity_id: str) -> dict[str, Any]:
        entity = get_entity(conn, instance_id=self.instance_id, entity_id=entity_id)
        relations = [
            dict(row)
            for row in conn.execute(
                """
                SELECT edge_id,subject_entity_id,predicate,object_entity_id,relation_basis,
                       valid_from,valid_to,created_at,updated_at
                FROM knowledge_edges
                WHERE instance_id=? AND (subject_entity_id=? OR object_entity_id=?)
                ORDER BY predicate,edge_id
                """,
                (self.instance_id, entity_id, entity_id),
            ).fetchall()
        ]
        story_links = [
            dict(row)
            for row in conn.execute(
                """
                SELECT story_id,role,created_at FROM story_entity_links
                WHERE instance_id=? AND entity_id=? ORDER BY created_at DESC,story_id
                """,
                (self.instance_id, entity_id),
            ).fetchall()
        ]
        money = [
            dict(row)
            for row in conn.execute(
                """
                SELECT money_item_id,payer_entity_id,beneficiary_entity_id,amount_minor,currency,purpose,
                       effective_date,created_at
                FROM public_money_items
                WHERE instance_id=? AND (payer_entity_id=? OR beneficiary_entity_id=?)
                ORDER BY COALESCE(effective_date,'') DESC,money_item_id
                """,
                (self.instance_id, entity_id, entity_id),
            ).fetchall()
        ]
        timeline = [
            dict(row)
            for row in conn.execute(
                """
                SELECT timeline_event_id,event_date,event_kind,title,summary,story_id,created_at
                FROM knowledge_timeline_events
                WHERE instance_id=? AND entity_id=? ORDER BY event_date DESC,timeline_event_id
                """,
                (self.instance_id, entity_id),
            ).fetchall()
        ]
        return {
            "entity": entity,
            "relations": relations,
            "story_links": story_links,
            "public_money": money,
            "timeline": timeline,
            "events": list_events(
                conn,
                instance_id=self.instance_id,
                aggregate_type="knowledge_entity",
                aggregate_id=entity_id,
            ),
        }

    def _render_knowledge(self, entities: list[dict[str, Any]]) -> bytes:
        rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(item['entity_type']))}</td>"
            f"<td><a href=\"/newsroom/api/entities/{html.escape(str(item['entity_id']))}\">{html.escape(str(item['canonical_name']))}</a></td>"
            f"<td>{html.escape(str(item['evidence_status']))}</td>"
            f"<td>{'yes' if item['is_public'] else 'no'}</td>"
            f"<td>{html.escape(str(item['updated_at']))}</td>"
            "</tr>"
            for item in entities
        ) or '<tr><td colspan="5">No knowledge entities yet</td></tr>'
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Knowledge · Newsroom</title><style>body{font-family:system-ui,sans-serif;max-width:1180px;margin:2rem auto;padding:0 1rem;color:#171717}"
            "table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #ddd;text-align:left;padding:.65rem;vertical-align:top}a{color:inherit}</style></head><body>"
            "<p><a href=\"/newsroom\">← Newsroom</a></p><h1>Local Knowledge Graph</h1>"
            "<table><thead><tr><th>Type</th><th>Entity</th><th>Evidence</th><th>Public</th><th>Updated</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></body></html>"
        ).encode("utf-8")

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        path = str(environ.get("PATH_INFO") or "/")
        knowledge_route = path == "/newsroom/knowledge" or path == "/newsroom/api/entities" or path.startswith("/newsroom/api/entities/")
        if not knowledge_route:
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
            ensure_knowledge_schema(conn)
            if path == "/newsroom/knowledge":
                return self._response(
                    start_response,
                    "200 OK",
                    self._render_knowledge(list_entities(conn, instance_id=self.instance_id, limit=500)),
                    content_type="text/html; charset=utf-8",
                    private=True,
                )
            if path == "/newsroom/api/entities":
                query = parse_qs(str(environ.get("QUERY_STRING") or ""))
                entity_type = (query.get("type") or [None])[0]
                public_only = str((query.get("public_only") or [""])[0]).lower() in {"1", "true", "yes"}
                limit = _safe_int((query.get("limit") or [None])[0], default=100, minimum=1, maximum=1000)
                return self._json_response(
                    start_response,
                    "200 OK",
                    {"entities": list_entities(conn, instance_id=self.instance_id, entity_type=entity_type, public_only=public_only, limit=limit)},
                    private=True,
                )
            prefix = "/newsroom/api/entities/"
            entity_id = unquote(path[len(prefix) :])
            try:
                record = self._entity_record(conn, entity_id)
            except KnowledgeGraphError:
                return self._json_response(start_response, "404 Not Found", {"error": "entity_not_found"}, private=True)
            return self._json_response(start_response, "200 OK", record, private=True)
        finally:
            conn.close()


class KnowledgePublicApp(PublicSiteApp):
    """Adds evidence-backed public entity profiles to the public site."""

    def __init__(self, *, db_path: str | Path, instance_id: str, publication_pack: dict[str, Any]) -> None:
        super().__init__(db_path=db_path, instance_id=instance_id, publication_pack=publication_pack)
        public_runtime = publication_pack.get("public_runtime") or {}
        prefix = str(public_runtime.get("profile_path_prefix") or "/profiles").strip()
        if not prefix.startswith("/") or prefix.endswith("/"):
            raise KnowledgeGraphError("profile_path_prefix must start with / and not end with /")
        self.profile_path_prefix = prefix

    def _profile_html(self, profile: dict[str, Any]) -> str:
        entity = profile["entity"]
        aliases = "".join(f"<li>{html.escape(str(item['alias']))}</li>" for item in profile["aliases"])
        relations = "".join(
            f"<li>{html.escape(str(item['subject_name']))} — {html.escape(str(item['predicate']))} — {html.escape(str(item['object_name']))}</li>"
            for item in profile["relations"]
        )
        timeline = "".join(
            f"<li><strong>{html.escape(str(item['event_date']))}</strong> · {html.escape(str(item['title']))}</li>"
            for item in profile["timeline"]
        )
        money = "".join(
            f"<li>{html.escape(str(item['purpose']))}: {int(item['amount_minor'])} minor units {html.escape(str(item['currency']))}</li>"
            for item in profile["public_money"]
        )
        stories = "".join(
            f"<li><a href=\"{html.escape(str(item['canonical_path']))}\">{html.escape(str(item['story_id']))}</a></li>"
            for item in profile["stories"]
        )
        sources = "".join(
            f"<li><a rel=\"nofollow\" href=\"{html.escape(str(item['source_url']))}\">Sursă</a></li>"
            for item in entity["provenance"]
        )
        canonical = profile_path(entity, prefix=self.profile_path_prefix)
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{html.escape(str(entity['canonical_name']))}</title><link rel=\"canonical\" href=\"https://{html.escape(self.policy['canonical_domain'])}{html.escape(canonical)}\"></head><body><main>"
            f"<article><p>{html.escape(str(entity['entity_type']))}</p><h1>{html.escape(str(entity['canonical_name']))}</h1>"
            f"<p>{html.escape(str(entity['summary']))}</p>"
            f"<h2>Aliasuri</h2><ul>{aliases}</ul><h2>Relații documentate</h2><ul>{relations}</ul>"
            f"<h2>Cronologie</h2><ul>{timeline}</ul><h2>Bani publici</h2><ul>{money}</ul>"
            f"<h2>Articole</h2><ul>{stories}</ul><h2>Surse</h2><ul>{sources}</ul></article></main></body></html>"
        )

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        path = str(environ.get("PATH_INFO") or "/")
        prefix = self.profile_path_prefix + "/"
        if method == "GET" and path.startswith(prefix):
            parts = [unquote(item) for item in path[len(prefix) :].strip("/").split("/") if item]
            if len(parts) != 2:
                return self._html(start_response, "404 Not Found", "<h1>Not found</h1>")
            conn = connect(self.db_path)
            try:
                ensure_knowledge_schema(conn)
                entity = get_public_entity_by_path(
                    conn,
                    instance_id=self.instance_id,
                    entity_type=parts[0],
                    slug=parts[1],
                )
                if entity is None:
                    return self._html(start_response, "404 Not Found", "<h1>Not found</h1>")
                profile = project_public_profile(conn, instance_id=self.instance_id, entity_id=entity["entity_id"])
                return self._html(start_response, "200 OK", self._profile_html(profile))
            finally:
                conn.close()
        return super().__call__(environ, start_response)


def _manifest(instance_id: str, domain: str, marker: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": marker * 64,
        "runtime": {"owner": "site_application", "repository_runtime_state_enabled": False},
    }


def _source(label: str) -> list[dict[str, str]]:
    import hashlib

    return [{
        "source_url": f"https://example.invalid/{label}",
        "evidence_fingerprint": hashlib.sha256(label.encode("utf-8")).hexdigest(),
        "observed_at": "2026-08-19T12:00:00Z",
    }]


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
        ensure_knowledge_schema(conn)
        register_instance(conn, _manifest("alpha-local", "alpha.invalid", "a"), engine_version="p12-web-test")
        entity, _ = upsert_entity(
            conn,
            instance_id="alpha-local",
            entity_type="ARTIST",
            canonical_name="Example Artist",
            provenance=_source("artist"),
            engine_version="p12-web-test",
            summary="Evidence-backed profile.",
            is_public=True,
        )
        conn.close()

        newsroom = KnowledgeNewsroomApp(
            db_path=db,
            instance_id="alpha-local",
            engine_version="p12-web-test",
            newsroom_token="secret-token",
        )
        status, headers, _ = _call(newsroom, "/newsroom/api/entities")
        assert status.startswith("401") and "no-store" in headers["Cache-Control"]
        status, headers, body = _call(newsroom, "/newsroom/api/entities", token="secret-token")
        assert status.startswith("200") and "noindex" in headers["X-Robots-Tag"]
        payload = json.loads(body)
        assert payload["entities"][0]["entity_id"] == entity["entity_id"]
        status, _, body = _call(newsroom, "/newsroom/knowledge", token="secret-token")
        assert status.startswith("200") and b"Local Knowledge Graph" in body

        pack = {
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
        public = KnowledgePublicApp(db_path=db, instance_id="alpha-local", publication_pack=pack)
        path = profile_path(entity)
        status, headers, body = _call(public, path)
        assert status.startswith("200") and headers["Cache-Control"].startswith("public")
        assert b"Example Artist" in body
        status, _, _ = _call(public, "/profiles/artist/not-evidence-backed/")
        assert status.startswith("404")
    print("VNEXT_KNOWLEDGE_RUNTIME_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("use --self-test or mount the application classes from the site deployment")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
