#!/usr/bin/env python3
"""Site-owned publication engine and public projections for LOCAL NEWS OS vNext.

Only a QA_PASSED story may become public. Publication state, immutable revision
snapshots, homepage/category/feed/sitemap projections and public story rendering
are derived directly from the site runtime database. No repository runtime state
or network transport is used here.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote, unquote

from editorial_qa import get_latest_qa_decision
from runtime_store import connect, get_story, initialize, register_instance, utc_now
from story_engine import get_story_draft

ROOT = Path(__file__).resolve().parents[3]
PUBLICATION_SCHEMA = ROOT / "local-news-os" / "vnext" / "runtime" / "publication_schema.sql"
PUBLIC_EVENT = "STORY_PUBLISHED"


class SitePublicationError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SitePublicationError(message)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hash_id(*parts: str, length: int = 24) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:length]


def ensure_publication_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(PUBLICATION_SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


def validate_publication_policy(pack: dict[str, Any], *, instance_id: str) -> dict[str, Any]:
    _require(isinstance(pack, dict), "publication pack must be an object")
    _require(pack.get("schema_version") == "2.0", "publication pack schema mismatch")
    _require(pack.get("pack_type") == "publication", "not a publication pack")
    _require(pack.get("instance_id") == instance_id, "publication pack instance mismatch")
    _require(pack.get("publication_model") == "continuous_story_first", "unsupported publication model")
    domain = _clean(pack.get("canonical_domain"))
    _require(domain and "/" not in domain and "://" not in domain, "canonical_domain must be a host")
    public = pack.get("public_runtime")
    _require(isinstance(public, dict), "publication pack requires public_runtime policy")
    story_prefix = str(public.get("story_path_prefix") or "").strip()
    category_prefix = str(public.get("category_path_prefix") or "").strip()
    _require(story_prefix.startswith("/") and not story_prefix.endswith("/"), "invalid story path prefix")
    _require(category_prefix.startswith("/") and not category_prefix.endswith("/"), "invalid category path prefix")
    _require(story_prefix != category_prefix, "story and category prefixes must differ")
    limits: dict[str, int] = {}
    for key, default, maximum in (("homepage_limit", 20, 100), ("feed_limit", 50, 200), ("sitemap_limit", 10000, 50000)):
        raw = public.get(key, default)
        _require(isinstance(raw, int) and not isinstance(raw, bool) and 1 <= raw <= maximum, f"{key} out of range")
        limits[key] = int(raw)
    return {
        "canonical_domain": domain,
        "name": _clean(pack.get("name")) or domain,
        "story_path_prefix": story_prefix,
        "category_path_prefix": category_prefix,
        **limits,
    }


def _decode_revision(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["snapshot"] = json.loads(value.pop("snapshot_json"))
    return value


def get_publication(conn: sqlite3.Connection, *, instance_id: str, story_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT p.*, r.qa_decision_id, r.draft_fingerprint, r.content_fingerprint,
               r.snapshot_json, r.created_at AS revision_created_at
        FROM story_publications p
        JOIN publication_revisions r
          ON r.instance_id=p.instance_id AND r.publication_id=p.publication_id
         AND r.revision=p.current_revision
        WHERE p.instance_id=? AND p.story_id=?
        """,
        (instance_id, story_id),
    ).fetchone()
    if row is None:
        raise SitePublicationError("publication not found for instance")
    return _decode_revision(row)


def get_publication_by_path(conn: sqlite3.Connection, *, instance_id: str, canonical_path: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT p.*, r.qa_decision_id, r.draft_fingerprint, r.content_fingerprint,
               r.snapshot_json, r.created_at AS revision_created_at
        FROM story_publications p
        JOIN publication_revisions r
          ON r.instance_id=p.instance_id AND r.publication_id=p.publication_id
         AND r.revision=p.current_revision
        WHERE p.instance_id=? AND p.canonical_path=?
        """,
        (instance_id, canonical_path),
    ).fetchone()
    return _decode_revision(row) if row is not None else None


def list_publications(
    conn: sqlite3.Connection, *, instance_id: str, section: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    bounded = max(1, min(50000, int(limit)))
    rows = conn.execute(
        """
        SELECT p.*, r.qa_decision_id, r.draft_fingerprint, r.content_fingerprint,
               r.snapshot_json, r.created_at AS revision_created_at
        FROM story_publications p
        JOIN publication_revisions r
          ON r.instance_id=p.instance_id AND r.publication_id=p.publication_id
         AND r.revision=p.current_revision
        WHERE p.instance_id=?
        ORDER BY p.published_at DESC, p.story_id ASC
        LIMIT ?
        """,
        (instance_id, bounded),
    ).fetchall()
    values = [_decode_revision(row) for row in rows]
    if section is not None:
        wanted = _clean(section).casefold()
        values = [item for item in values if _clean(item["snapshot"].get("section")).casefold() == wanted]
    return values


def _allocate_path(story: dict[str, Any], *, policy: dict[str, Any]) -> str:
    existing = str(story.get("canonical_path") or "").strip()
    if existing:
        _require(existing.startswith("/") and "?" not in existing and "#" not in existing, "unsafe existing canonical path")
        return existing if existing.endswith("/") else existing + "/"
    story_id = _clean(story.get("story_id"))
    _require(story_id, "story id is required")
    safe_id = quote(story_id, safe="-._~")
    return f"{policy['story_path_prefix']}/{safe_id}/"


def _public_snapshot(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "story_id": str(draft["story_id"]),
        "headline": str(draft["headline"]),
        "dek": str(draft["dek"]),
        "body_blocks": list(draft.get("body_blocks") or []),
        "factbox": list(draft.get("factbox") or []),
        "context": dict(draft.get("context") or {}),
        "source_references": list(draft.get("source_references") or []),
        "follow_up": dict(draft.get("follow_up") or {}),
        "section": str(draft["section"]),
        "tags": list(draft.get("tags") or []),
    }


def publish_story(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
    publication_pack: dict[str, Any],
    engine_version: str,
) -> tuple[dict[str, Any], bool]:
    policy = validate_publication_policy(publication_pack, instance_id=instance_id)
    ensure_publication_schema(conn)
    story = get_story(conn, instance_id=instance_id, story_id=story_id)
    _require(story["state"] in {"QA_PASSED", "PUBLISHED"}, "site publication requires QA_PASSED story")
    draft = get_story_draft(conn, instance_id=instance_id, story_id=story_id)
    qa = get_latest_qa_decision(conn, instance_id=instance_id, story_id=story_id)
    _require(qa is not None and qa["outcome"] == "QA_PASSED", "latest Editorial QA must be QA_PASSED")
    _require(qa["draft_fingerprint"] == draft["fingerprint"], "QA decision is stale for draft")
    _require(int(qa["draft_revision"]) == int(draft["revision"]), "QA decision revision mismatch")
    _require(draft["publication_authority"] == "NONE", "draft unexpectedly carries publication authority")

    canonical_path = _allocate_path(story, policy=policy)
    snapshot = _public_snapshot(draft)
    content_fingerprint = _stable_hash(
        {"canonical_path": canonical_path, "draft_fingerprint": draft["fingerprint"], "snapshot": snapshot}
    )
    existing = conn.execute(
        "SELECT current_content_fingerprint FROM story_publications WHERE instance_id=? AND story_id=?",
        (instance_id, story_id),
    ).fetchone()
    if existing is not None:
        _require(existing["current_content_fingerprint"] == content_fingerprint, "P11 refuses unreviewed publication revision")
        _require(story["state"] == "PUBLISHED", "publication record exists for non-published story")
        return get_publication(conn, instance_id=instance_id, story_id=story_id), False
    _require(story["state"] == "QA_PASSED", "new publication requires QA_PASSED story")

    publication_id = _hash_id(instance_id, story_id, canonical_path)
    revision_id = _hash_id(instance_id, publication_id, "1", content_fingerprint)
    now = utc_now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT state, revision, canonical_path FROM stories WHERE instance_id=? AND story_id=?",
            (instance_id, story_id),
        ).fetchone()
        _require(current is not None and current["state"] == "QA_PASSED", "story changed during publication")
        story_revision = int(current["revision"])
        if current["canonical_path"]:
            _require(_allocate_path(dict(current) | {"story_id": story_id}, policy=policy) == canonical_path, "canonical path changed during publication")
        conn.execute(
            """
            INSERT INTO story_publications(
                instance_id,story_id,publication_id,canonical_path,current_revision,
                current_content_fingerprint,published_at,updated_at
            ) VALUES (?,?,?,?,1,?,?,?)
            """,
            (instance_id, story_id, publication_id, canonical_path, content_fingerprint, now, now),
        )
        conn.execute(
            """
            INSERT INTO publication_revisions(
                instance_id,publication_revision_id,publication_id,story_id,revision,
                qa_decision_id,draft_fingerprint,content_fingerprint,snapshot_json,created_at
            ) VALUES (?,?,?,?,1,?,?,?,?,?)
            """,
            (
                instance_id, revision_id, publication_id, story_id, qa["decision_id"], draft["fingerprint"],
                content_fingerprint, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now,
            ),
        )
        cursor = conn.execute(
            """
            UPDATE stories SET state='PUBLISHED', canonical_path=?, revision=revision+1, updated_at=?
            WHERE instance_id=? AND story_id=? AND state='QA_PASSED' AND revision=?
            """,
            (canonical_path, now, instance_id, story_id, story_revision),
        )
        _require(cursor.rowcount == 1, "story changed while publishing")
        conn.execute(
            """
            INSERT INTO runtime_events(
                instance_id,aggregate_type,aggregate_id,event_type,from_state,to_state,
                reason,payload_json,engine_version,created_at
            ) VALUES (?,'story',?,?,'QA_PASSED','PUBLISHED',?,?,?,?,?)
            """,
            (
                instance_id, story_id, PUBLIC_EVENT, "QA-passed story published by site runtime",
                json.dumps({
                    "publication_id": publication_id,
                    "publication_revision_id": revision_id,
                    "canonical_path": canonical_path,
                    "content_fingerprint": content_fingerprint,
                    "qa_decision_id": qa["decision_id"],
                }, ensure_ascii=False, sort_keys=True),
                engine_version, now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_publication(conn, instance_id=instance_id, story_id=story_id), True


StartResponse = Callable[[str, list[tuple[str, str]]], Any]


class PublicSiteApp:
    def __init__(self, *, db_path: str | Path, instance_id: str, publication_pack: dict[str, Any]) -> None:
        self.db_path = str(db_path)
        self.instance_id = instance_id
        self.policy = validate_publication_policy(publication_pack, instance_id=instance_id)

    def _response(self, start_response: StartResponse, status: str, body: bytes, content_type: str) -> Iterable[bytes]:
        start_response(status, [
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
            ("X-Content-Type-Options", "nosniff"),
            ("Cache-Control", "public, max-age=60"),
        ])
        return [body]

    def _html(self, start_response: StartResponse, status: str, text: str) -> Iterable[bytes]:
        return self._response(start_response, status, text.encode("utf-8"), "text/html; charset=utf-8")

    def _xml(self, start_response: StartResponse, text: str) -> Iterable[bytes]:
        return self._response(start_response, "200 OK", text.encode("utf-8"), "application/xml; charset=utf-8")

    def _story_html(self, item: dict[str, Any]) -> str:
        s = item["snapshot"]
        paragraphs = "".join(f"<p>{html.escape(str(b.get('text') or ''))}</p>" for b in s.get("body_blocks") or [])
        sources = "".join(
            f"<li><a rel=\"nofollow\" href=\"{html.escape(str(src.get('evidence_url') or ''))}\">Sursă primară</a></li>"
            for src in s.get("source_references") or []
        )
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{html.escape(s['headline'])}</title><link rel=\"canonical\" href=\"https://{html.escape(self.policy['canonical_domain'])}{html.escape(item['canonical_path'])}\"></head><body>"
            f"<main><article><p>{html.escape(s['section'])}</p><h1>{html.escape(s['headline'])}</h1><p>{html.escape(s['dek'])}</p>{paragraphs}"
            f"<h2>Surse</h2><ul>{sources}</ul></article></main></body></html>"
        )

    def _listing_html(self, items: list[dict[str, Any]], *, title: str) -> str:
        cards = "".join(
            f"<article><h2><a href=\"{html.escape(item['canonical_path'])}\">{html.escape(item['snapshot']['headline'])}</a></h2>"
            f"<p>{html.escape(item['snapshot']['dek'])}</p></article>"
            for item in items
        ) or "<p>Nu există articole publicate.</p>"
        return f"<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{html.escape(title)}</title></head><body><main><h1>{html.escape(title)}</h1>{cards}</main></body></html>"

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        if str(environ.get("REQUEST_METHOD") or "GET").upper() != "GET":
            return self._html(start_response, "405 Method Not Allowed", "Method not allowed")
        path = str(environ.get("PATH_INFO") or "/")
        conn = connect(self.db_path)
        try:
            ensure_publication_schema(conn)
            if path == "/":
                items = list_publications(conn, instance_id=self.instance_id, limit=self.policy["homepage_limit"])
                return self._html(start_response, "200 OK", self._listing_html(items, title=self.policy["name"]))
            if path == "/feed.xml":
                items = list_publications(conn, instance_id=self.instance_id, limit=self.policy["feed_limit"])
                entries = "".join(
                    f"<entry><id>https://{html.escape(self.policy['canonical_domain'])}{html.escape(i['canonical_path'])}</id>"
                    f"<title>{html.escape(i['snapshot']['headline'])}</title><link href=\"https://{html.escape(self.policy['canonical_domain'])}{html.escape(i['canonical_path'])}\"/>"
                    f"<updated>{html.escape(i['published_at'])}</updated></entry>" for i in items
                )
                return self._xml(start_response, f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><feed xmlns=\"http://www.w3.org/2005/Atom\"><title>{html.escape(self.policy['name'])}</title>{entries}</feed>")
            if path == "/sitemap.xml":
                items = list_publications(conn, instance_id=self.instance_id, limit=self.policy["sitemap_limit"])
                urls = "".join(f"<url><loc>https://{html.escape(self.policy['canonical_domain'])}{html.escape(i['canonical_path'])}</loc></url>" for i in items)
                return self._xml(start_response, f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">{urls}</urlset>")
            category_prefix = self.policy["category_path_prefix"] + "/"
            if path.startswith(category_prefix):
                section = unquote(path[len(category_prefix):].strip("/"))
                items = list_publications(conn, instance_id=self.instance_id, section=section, limit=self.policy["homepage_limit"])
                return self._html(start_response, "200 OK", self._listing_html(items, title=section or self.policy["name"]))
            item = get_publication_by_path(conn, instance_id=self.instance_id, canonical_path=path)
            if item is not None:
                return self._html(start_response, "200 OK", self._story_html(item))
            return self._html(start_response, "404 Not Found", "Not found")
        finally:
            conn.close()


def _publication_pack(instance_id: str, domain: str, story_prefix: str, category_prefix: str) -> dict[str, Any]:
    return {
        "schema_version": "2.0", "pack_type": "publication", "instance_id": instance_id,
        "name": instance_id, "short_name": instance_id, "canonical_domain": domain,
        "publication_model": "continuous_story_first",
        "public_runtime": {"story_path_prefix": story_prefix, "category_path_prefix": category_prefix, "homepage_limit": 20, "feed_limit": 50, "sitemap_limit": 1000},
    }


def _wsgi_get(app: PublicSiteApp, path: str) -> tuple[str, bytes]:
    captured: dict[str, Any] = {}
    def start(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = headers
    body = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": path}, start))
    return str(captured["status"]), body


def self_test() -> None:
    from editorial_qa import _draft, _insert_fixture, _manifest, _pack, evaluate_story_draft
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "publication.sqlite3"
        conn = connect(db)
        initialize(conn)
        ensure_publication_schema(conn)
        engine = "vnext-publication-test"
        register_instance(conn, _manifest("alpha-local", "alpha.invalid"), engine_version=engine)
        register_instance(conn, _manifest("beta-local", "beta.invalid"), engine_version=engine)
        editorial_alpha = _pack("alpha-local", "fraud")
        editorial_beta = _pack("beta-local", "allegation")
        pub_alpha = _publication_pack("alpha-local", "alpha.invalid", "/stories", "/section")
        pub_beta = _publication_pack("beta-local", "beta.invalid", "/reports", "/topic")

        _insert_fixture(conn, instance_id="alpha-local", signal_id="s1", kernel_id="k1", headline="Verified service changes start Monday", suffix="p1")
        draft = _draft(conn, instance_id="alpha-local", kernel_id="k1", pack=editorial_alpha, engine=engine)
        qa, _ = evaluate_story_draft(conn, instance_id="alpha-local", story_id=draft["story_id"], editorial_pack=editorial_alpha, engine_version=engine)
        assert qa["outcome"] == "QA_PASSED"
        published, created = publish_story(conn, instance_id="alpha-local", story_id=draft["story_id"], publication_pack=pub_alpha, engine_version=engine)
        assert created and published["canonical_path"].startswith("/stories/")
        assert get_story(conn, instance_id="alpha-local", story_id=draft["story_id"])["state"] == "PUBLISHED"
        again, created_again = publish_story(conn, instance_id="alpha-local", story_id=draft["story_id"], publication_pack=pub_alpha, engine_version=engine)
        assert not created_again and again["content_fingerprint"] == published["content_fingerprint"]

        _insert_fixture(conn, instance_id="alpha-local", signal_id="s2", kernel_id="k2", headline="Official notice contains fraud allegation", suffix="p2")
        risky = _draft(conn, instance_id="alpha-local", kernel_id="k2", pack=editorial_alpha, engine=engine)
        risk_qa, _ = evaluate_story_draft(conn, instance_id="alpha-local", story_id=risky["story_id"], editorial_pack=editorial_alpha, engine_version=engine)
        assert risk_qa["outcome"] == "HUMAN_REVIEW"
        try:
            publish_story(conn, instance_id="alpha-local", story_id=risky["story_id"], publication_pack=pub_alpha, engine_version=engine)
            raise AssertionError("human-review story published")
        except SitePublicationError:
            pass

        _insert_fixture(conn, instance_id="beta-local", signal_id="s3", kernel_id="k3", headline="Neutral verified community update", suffix="p3")
        beta_draft = _draft(conn, instance_id="beta-local", kernel_id="k3", pack=editorial_beta, engine=engine)
        beta_qa, _ = evaluate_story_draft(conn, instance_id="beta-local", story_id=beta_draft["story_id"], editorial_pack=editorial_beta, engine_version=engine)
        assert beta_qa["outcome"] == "QA_PASSED"
        beta_pub, _ = publish_story(conn, instance_id="beta-local", story_id=beta_draft["story_id"], publication_pack=pub_beta, engine_version=engine)
        assert beta_pub["canonical_path"].startswith("/reports/")
        assert len(list_publications(conn, instance_id="alpha-local")) == 1
        assert len(list_publications(conn, instance_id="beta-local")) == 1

        app = PublicSiteApp(db_path=db, instance_id="alpha-local", publication_pack=pub_alpha)
        assert _wsgi_get(app, "/")[0] == "200 OK"
        assert _wsgi_get(app, published["canonical_path"])[0] == "200 OK"
        assert b"Verified service changes start Monday" in _wsgi_get(app, published["canonical_path"])[1]
        assert _wsgi_get(app, "/feed.xml")[0] == "200 OK"
        assert _wsgi_get(app, "/sitemap.xml")[0] == "200 OK"
        assert _wsgi_get(app, "/reports/not-alpha/")[0] == "404 Not Found"

        revision_id = conn.execute("SELECT publication_revision_id FROM publication_revisions WHERE instance_id='alpha-local'").fetchone()[0]
        try:
            conn.execute("UPDATE publication_revisions SET revision=2 WHERE publication_revision_id=?", (revision_id,))
            raise AssertionError("immutable publication revision mutated")
        except sqlite3.IntegrityError:
            conn.rollback()
        conn.close()
    print("LOCAL_NEWS_OS_VNEXT_SITE_PUBLICATION_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("use --self-test")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
