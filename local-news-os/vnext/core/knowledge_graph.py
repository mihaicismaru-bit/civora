#!/usr/bin/env python3
"""Site-owned Local Knowledge Graph for LOCAL NEWS OS vNext.

The graph is generic and locality-blind. Verified entities, aliases and material
relationships require explicit provenance. Story enrichment can connect a
published story to an already verified entity only when the entity mention is
present in the verified public story snapshot. Unknown mentions are never
promoted into inferred people, organizations or relationships.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import hmac
import json
import re
import sqlite3
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Callable, Iterable

from runtime_store import connect, get_story, initialize, register_instance, utc_now
from site_publication import ensure_publication_schema, get_publication
from story_engine import get_story_draft

ROOT = Path(__file__).resolve().parents[3]
GRAPH_SCHEMA = ROOT / "local-news-os" / "vnext" / "runtime" / "knowledge_graph_schema.sql"
ENTITY_TYPES = {
    "person", "artist", "organization", "company", "institution", "event", "venue", "place",
    "project", "public_money_item", "document", "story", "media_asset",
}
RELATION_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


class KnowledgeGraphError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise KnowledgeGraphError(message)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize(value: str) -> str:
    return _clean(value).casefold()


def _slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", _clean(value)).encode("ascii", "ignore").decode("ascii")
    result = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
    return result or "entity"


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hash_id(*parts: str, length: int = 24) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:length]


def ensure_knowledge_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(GRAPH_SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


def validate_entity_pack(pack: dict[str, Any], *, instance_id: str) -> dict[str, Any]:
    _require(isinstance(pack, dict), "entity pack must be an object")
    _require(pack.get("schema_version") == "2.0", "entity pack schema mismatch")
    _require(pack.get("pack_type") == "entities", "not an entity pack")
    _require(pack.get("instance_id") == instance_id, "entity pack instance mismatch")
    cfg = pack.get("knowledge_graph")
    _require(isinstance(cfg, dict), "entity pack requires knowledge_graph policy")
    public_types = cfg.get("public_profile_types") or []
    _require(isinstance(public_types, list) and public_types, "public_profile_types must be non-empty")
    normalized_types = []
    for value in public_types:
        kind = _clean(value).lower()
        _require(kind in ENTITY_TYPES and kind not in {"story", "document", "media_asset"}, "unsupported public profile type")
        if kind not in normalized_types:
            normalized_types.append(kind)
    paths = cfg.get("profile_paths") or {}
    _require(isinstance(paths, dict), "profile_paths must be an object")
    normalized_paths: dict[str, str] = {}
    for kind in normalized_types:
        prefix = str(paths.get(kind) or "").strip()
        _require(prefix.startswith("/") and prefix != "/" and not prefix.endswith("/"), f"invalid profile path for {kind}")
        normalized_paths[kind] = prefix
    minimum = cfg.get("minimum_public_provenance", 1)
    _require(isinstance(minimum, int) and not isinstance(minimum, bool) and 1 <= minimum <= 10, "minimum_public_provenance out of range")
    return {"public_profile_types": normalized_types, "profile_paths": normalized_paths, "minimum_public_provenance": int(minimum)}


def _evidence(value: dict[str, Any] | None) -> dict[str, Any]:
    _require(isinstance(value, dict), "verified graph material requires provenance")
    source_url = _clean(value.get("source_url"))
    evidence_url = _clean(value.get("evidence_url"))
    fingerprint = _clean(value.get("evidence_fingerprint"))
    assertion = _clean(value.get("assertion"))
    _require(source_url.startswith(("http://", "https://")), "provenance source_url must be absolute")
    _require(evidence_url.startswith(("http://", "https://")), "provenance evidence_url must be absolute")
    _require(len(fingerprint) >= 16, "provenance evidence_fingerprint is required")
    _require(assertion, "provenance assertion is required")
    return {
        "source_url": source_url,
        "evidence_url": evidence_url,
        "evidence_fingerprint": fingerprint,
        "observed_at": _clean(value.get("observed_at")) or None,
        "assertion": assertion,
    }


def _validated_facts(facts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in facts or []:
        _require(isinstance(raw, dict), "entity fact must be an object")
        key = _clean(raw.get("key"))
        value = _clean(raw.get("value"))
        _require(key and value, "entity fact requires key and value")
        ev = _evidence(raw.get("provenance"))
        identity = (key.casefold(), value.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        output.append({"key": key, "value": value, "provenance": ev})
    return output


def _entity_row(conn: sqlite3.Connection, *, instance_id: str, entity_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM knowledge_entities WHERE instance_id=? AND entity_id=?",
        (instance_id, entity_id),
    ).fetchone()
    if row is None:
        raise KnowledgeGraphError("entity not found for instance")
    value = dict(row)
    value["facts"] = json.loads(value.pop("facts_json"))
    return value


def materialize_verified_entity(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    entity_type: str,
    canonical_name: str,
    external_key: str,
    provenance: dict[str, Any],
    entity_pack: dict[str, Any],
    aliases: list[str] | None = None,
    facts: list[dict[str, Any]] | None = None,
    engine_version: str,
) -> tuple[dict[str, Any], bool]:
    ensure_knowledge_schema(conn)
    policy = validate_entity_pack(entity_pack, instance_id=instance_id)
    kind = _clean(entity_type).lower()
    name = _clean(canonical_name)
    key = _clean(external_key)
    _require(kind in ENTITY_TYPES, "unsupported entity type")
    _require(name and key, "verified entity requires canonical_name and external_key")
    ev = _evidence(provenance)
    verified_facts = _validated_facts(facts)
    entity_id = f"ent-{_hash_id(instance_id, kind, key, length=20)}"
    slug = _slug(name)
    public_allowed = int(kind in policy["public_profile_types"])
    fingerprint = _stable_hash({"kind": kind, "name": name, "key": key, "facts": verified_facts})
    now = utc_now()
    existing = conn.execute(
        "SELECT fingerprint FROM knowledge_entities WHERE instance_id=? AND entity_id=?",
        (instance_id, entity_id),
    ).fetchone()
    created = existing is None
    try:
        conn.execute("BEGIN IMMEDIATE")
        if created:
            conn.execute(
                """
                INSERT INTO knowledge_entities(
                    instance_id,entity_id,entity_type,canonical_name,normalized_name,slug,external_key,
                    state,public_profile_allowed,facts_json,fingerprint,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,'VERIFIED',?,?,?,?,?)
                """,
                (
                    instance_id, entity_id, kind, name, _normalize(name), slug, key, public_allowed,
                    json.dumps(verified_facts, ensure_ascii=False, sort_keys=True), fingerprint, now, now,
                ),
            )
        elif existing["fingerprint"] != fingerprint:
            conn.execute(
                """
                UPDATE knowledge_entities SET canonical_name=?,normalized_name=?,slug=?,
                    public_profile_allowed=?,facts_json=?,fingerprint=?,updated_at=?
                WHERE instance_id=? AND entity_id=? AND state='VERIFIED'
                """,
                (
                    name, _normalize(name), slug, public_allowed,
                    json.dumps(verified_facts, ensure_ascii=False, sort_keys=True), fingerprint, now,
                    instance_id, entity_id,
                ),
            )
        provenance_id = f"prov-{_hash_id(instance_id, entity_id, ev['evidence_fingerprint'], ev['assertion'], length=20)}"
        conn.execute(
            """
            INSERT OR IGNORE INTO knowledge_entity_provenance(
                instance_id,provenance_id,entity_id,source_url,evidence_url,evidence_fingerprint,
                observed_at,assertion,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                instance_id, provenance_id, entity_id, ev["source_url"], ev["evidence_url"],
                ev["evidence_fingerprint"], ev["observed_at"], ev["assertion"], now,
            ),
        )
        for alias in [name, *(aliases or [])]:
            text = _clean(alias)
            if not text:
                continue
            normalized = _normalize(text)
            alias_id = f"alias-{_hash_id(instance_id, entity_id, normalized, length=20)}"
            conn.execute(
                """
                INSERT OR IGNORE INTO knowledge_aliases(
                    instance_id,alias_id,entity_id,alias_text,normalized_alias,evidence_url,evidence_fingerprint,created_at
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (instance_id, alias_id, entity_id, text, normalized, ev["evidence_url"], ev["evidence_fingerprint"], now),
            )
        if created:
            conn.execute(
                """
                INSERT INTO runtime_events(
                    instance_id,aggregate_type,aggregate_id,event_type,from_state,to_state,
                    reason,payload_json,engine_version,created_at
                ) VALUES (?,'knowledge_entity',?,'KNOWLEDGE_ENTITY_VERIFIED',NULL,'VERIFIED',?,?,?,?)
                """,
                (
                    instance_id, entity_id, "entity verified from explicit provenance",
                    json.dumps({"entity_type": kind, "evidence_fingerprint": ev["evidence_fingerprint"]}, sort_keys=True),
                    engine_version, now,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return _entity_row(conn, instance_id=instance_id, entity_id=entity_id), created


def resolve_entity_mention(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    mention: str,
    entity_type: str | None = None,
) -> dict[str, Any]:
    ensure_knowledge_schema(conn)
    normalized = _normalize(mention)
    _require(normalized, "mention is required")
    kind = _clean(entity_type).lower() if entity_type else None
    if kind and kind not in ENTITY_TYPES:
        kind = None
    params: list[Any] = [instance_id, normalized, instance_id, normalized]
    kind_sql = ""
    if kind:
        kind_sql = " AND e.entity_type=?"
        params.extend([kind, kind])
    rows = conn.execute(
        f"""
        SELECT DISTINCT e.* FROM knowledge_entities e
        LEFT JOIN knowledge_aliases a
          ON a.instance_id=e.instance_id AND a.entity_id=e.entity_id
        WHERE e.state='VERIFIED' AND (
            (e.instance_id=? AND e.normalized_name=?{kind_sql}) OR
            (a.instance_id=? AND a.normalized_alias=?{kind_sql})
        )
        ORDER BY e.entity_id
        """,
        tuple(params),
    ).fetchall()
    values = []
    for row in rows:
        value = dict(row)
        value["facts"] = json.loads(value.pop("facts_json"))
        values.append(value)
    if not values:
        return {"status": "UNRESOLVED", "mention": mention, "candidates": []}
    if len(values) > 1:
        return {"status": "AMBIGUOUS", "mention": mention, "candidates": [item["entity_id"] for item in values]}
    return {"status": "RESOLVED", "mention": mention, "entity": values[0]}


def materialize_verified_edge(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    from_entity_id: str,
    relationship: str,
    to_entity_id: str,
    provenance: dict[str, Any],
    engine_version: str,
    material: bool = True,
) -> tuple[dict[str, Any], bool]:
    ensure_knowledge_schema(conn)
    relation = _clean(relationship).upper()
    _require(RELATION_RE.fullmatch(relation) is not None, "invalid relationship")
    ev = _evidence(provenance)
    left = _entity_row(conn, instance_id=instance_id, entity_id=from_entity_id)
    right = _entity_row(conn, instance_id=instance_id, entity_id=to_entity_id)
    _require(left["state"] == right["state"] == "VERIFIED", "material edge requires verified entities")
    edge_id = f"edge-{_hash_id(instance_id, from_entity_id, relation, to_entity_id, ev['evidence_fingerprint'], length=20)}"
    fingerprint = _stable_hash({
        "from": from_entity_id, "relationship": relation, "to": to_entity_id,
        "evidence": ev["evidence_fingerprint"], "material": bool(material),
    })
    existing = conn.execute(
        "SELECT * FROM knowledge_edges WHERE instance_id=? AND edge_id=?",
        (instance_id, edge_id),
    ).fetchone()
    if existing is not None:
        _require(existing["fingerprint"] == fingerprint, "edge identity collision")
        return dict(existing), False
    now = utc_now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO knowledge_edges(
                instance_id,edge_id,from_entity_id,relationship,to_entity_id,material,
                public_claim_allowed,assertion_basis,evidence_url,evidence_fingerprint,
                observed_at,fingerprint,created_at
            ) VALUES (?,?,?,?,?,?,1,'DIRECT_EVIDENCE',?,?,?,?,?)
            """,
            (
                instance_id, edge_id, from_entity_id, relation, to_entity_id, int(bool(material)),
                ev["evidence_url"], ev["evidence_fingerprint"], ev["observed_at"], fingerprint, now,
            ),
        )
        conn.execute(
            """
            INSERT INTO runtime_events(
                instance_id,aggregate_type,aggregate_id,event_type,from_state,to_state,
                reason,payload_json,engine_version,created_at
            ) VALUES (?,'knowledge_edge',?,'KNOWLEDGE_EDGE_VERIFIED',NULL,'VERIFIED',?,?,?,?)
            """,
            (
                instance_id, edge_id, "relationship verified from direct evidence",
                json.dumps({"relationship": relation, "evidence_fingerprint": ev["evidence_fingerprint"]}, sort_keys=True),
                engine_version, now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    row = conn.execute("SELECT * FROM knowledge_edges WHERE instance_id=? AND edge_id=?", (instance_id, edge_id)).fetchone()
    return dict(row), True


def _public_story_text(snapshot: dict[str, Any]) -> str:
    parts = [_clean(snapshot.get("headline")), _clean(snapshot.get("dek"))]
    parts.extend(_clean(block.get("text")) for block in snapshot.get("body_blocks") or [])
    return "\n".join(part for part in parts if part).casefold()


def enrich_published_story(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
    canonical_domain: str,
    entity_pack: dict[str, Any],
    engine_version: str,
) -> dict[str, Any]:
    ensure_publication_schema(conn)
    ensure_knowledge_schema(conn)
    validate_entity_pack(entity_pack, instance_id=instance_id)
    story = get_story(conn, instance_id=instance_id, story_id=story_id)
    _require(story["state"] == "PUBLISHED", "knowledge enrichment requires PUBLISHED story")
    publication = get_publication(conn, instance_id=instance_id, story_id=story_id)
    draft = get_story_draft(conn, instance_id=instance_id, story_id=story_id)
    canonical_url = f"https://{_clean(canonical_domain)}{publication['canonical_path']}"
    story_evidence = {
        "source_url": canonical_url,
        "evidence_url": canonical_url,
        "evidence_fingerprint": publication["content_fingerprint"],
        "observed_at": publication["published_at"],
        "assertion": "published verified story snapshot",
    }
    story_entity, _ = materialize_verified_entity(
        conn,
        instance_id=instance_id,
        entity_type="story",
        canonical_name=publication["snapshot"]["headline"],
        external_key=story_id,
        provenance=story_evidence,
        entity_pack=entity_pack,
        engine_version=engine_version,
    )
    public_text = _public_story_text(publication["snapshot"])
    resolved = 0
    unresolved = 0
    for binding in draft.get("entity_bindings") or []:
        mention = _clean(binding.get("mention"))
        if not mention or mention.casefold() not in public_text:
            unresolved += 1
            continue
        raw_kind = _clean(binding.get("kind")).lower()
        kind = raw_kind if raw_kind in ENTITY_TYPES else None
        result = resolve_entity_mention(conn, instance_id=instance_id, mention=mention, entity_type=kind)
        if result["status"] != "RESOLVED":
            unresolved += 1
            continue
        entity = result["entity"]
        materialize_verified_edge(
            conn,
            instance_id=instance_id,
            from_entity_id=story_entity["entity_id"],
            relationship="MENTIONS",
            to_entity_id=entity["entity_id"],
            provenance={**story_evidence, "assertion": f"published story directly mentions {mention}"},
            engine_version=engine_version,
            material=False,
        )
        resolved += 1
    fingerprint = _stable_hash({
        "story_id": story_id,
        "publication": publication["content_fingerprint"],
        "resolved": resolved,
        "unresolved": unresolved,
    })
    now = utc_now()
    conn.execute(
        """
        INSERT OR IGNORE INTO knowledge_story_enrichments(
            instance_id,story_id,publication_content_fingerprint,story_entity_id,
            resolved_mentions,unresolved_mentions,fingerprint,created_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            instance_id, story_id, publication["content_fingerprint"], story_entity["entity_id"],
            resolved, unresolved, fingerprint, now,
        ),
    )
    conn.commit()
    return {
        "story_id": story_id,
        "story_entity_id": story_entity["entity_id"],
        "resolved_mentions": resolved,
        "unresolved_mentions": unresolved,
        "fingerprint": fingerprint,
    }


def knowledge_summary(conn: sqlite3.Connection, *, instance_id: str) -> dict[str, Any]:
    ensure_knowledge_schema(conn)
    entity_rows = conn.execute(
        "SELECT entity_type,COUNT(*) AS count FROM knowledge_entities WHERE instance_id=? GROUP BY entity_type ORDER BY entity_type",
        (instance_id,),
    ).fetchall()
    edge_rows = conn.execute(
        "SELECT relationship,COUNT(*) AS count FROM knowledge_edges WHERE instance_id=? GROUP BY relationship ORDER BY relationship",
        (instance_id,),
    ).fetchall()
    return {
        "entities": {row["entity_type"]: int(row["count"]) for row in entity_rows},
        "edges": {row["relationship"]: int(row["count"]) for row in edge_rows},
    }


def list_entities(conn: sqlite3.Connection, *, instance_id: str, limit: int = 100) -> list[dict[str, Any]]:
    ensure_knowledge_schema(conn)
    rows = conn.execute(
        "SELECT * FROM knowledge_entities WHERE instance_id=? ORDER BY updated_at DESC,entity_id LIMIT ?",
        (instance_id, max(1, min(500, int(limit)))),
    ).fetchall()
    output = []
    for row in rows:
        value = dict(row)
        value["facts"] = json.loads(value.pop("facts_json"))
        output.append(value)
    return output


def public_profile(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    entity_type: str,
    slug: str,
    entity_pack: dict[str, Any],
) -> dict[str, Any] | None:
    ensure_knowledge_schema(conn)
    policy = validate_entity_pack(entity_pack, instance_id=instance_id)
    kind = _clean(entity_type).lower()
    if kind not in policy["public_profile_types"]:
        return None
    row = conn.execute(
        """
        SELECT * FROM knowledge_entities
        WHERE instance_id=? AND entity_type=? AND slug=? AND state='VERIFIED' AND public_profile_allowed=1
        """,
        (instance_id, kind, slug),
    ).fetchone()
    if row is None:
        return None
    provenance_count = conn.execute(
        "SELECT COUNT(*) FROM knowledge_entity_provenance WHERE instance_id=? AND entity_id=?",
        (instance_id, row["entity_id"]),
    ).fetchone()[0]
    if int(provenance_count) < policy["minimum_public_provenance"]:
        return None
    value = dict(row)
    value["facts"] = json.loads(value.pop("facts_json"))
    value["provenance"] = [dict(item) for item in conn.execute(
        "SELECT source_url,evidence_url,evidence_fingerprint,observed_at,assertion FROM knowledge_entity_provenance WHERE instance_id=? AND entity_id=? ORDER BY created_at",
        (instance_id, row["entity_id"]),
    ).fetchall()]
    value["related_stories"] = [dict(item) for item in conn.execute(
        """
        SELECT sp.story_id,sp.canonical_path,pr.snapshot_json
        FROM knowledge_edges e
        JOIN knowledge_entities se ON se.instance_id=e.instance_id AND se.entity_id=e.from_entity_id AND se.entity_type='story'
        JOIN story_publications sp ON sp.instance_id=e.instance_id AND sp.story_id=se.external_key
        JOIN publication_revisions pr ON pr.instance_id=sp.instance_id AND pr.publication_id=sp.publication_id AND pr.revision=sp.current_revision
        WHERE e.instance_id=? AND e.to_entity_id=? AND e.relationship='MENTIONS'
        ORDER BY sp.published_at DESC
        LIMIT 50
        """,
        (instance_id, row["entity_id"]),
    ).fetchall()]
    for item in value["related_stories"]:
        item["snapshot"] = json.loads(item.pop("snapshot_json"))
    return value


def profile_path(entity: dict[str, Any], *, entity_pack: dict[str, Any], instance_id: str) -> str | None:
    policy = validate_entity_pack(entity_pack, instance_id=instance_id)
    prefix = policy["profile_paths"].get(entity["entity_type"])
    return f"{prefix}/{entity['slug']}/" if prefix else None


def render_public_profile(profile: dict[str, Any], *, canonical_domain: str, path: str) -> bytes:
    facts = "".join(
        f"<li><strong>{html.escape(str(item['key']))}</strong>: {html.escape(str(item['value']))}</li>"
        for item in profile.get("facts") or []
    ) or "<li>Profil verificat; nu există încă fapte structurate suplimentare.</li>"
    stories = "".join(
        f"<li><a href=\"{html.escape(item['canonical_path'])}\">{html.escape(item['snapshot']['headline'])}</a></li>"
        for item in profile.get("related_stories") or []
    ) or "<li>Niciun articol asociat.</li>"
    sources = "".join(
        f"<li><a rel=\"nofollow\" href=\"{html.escape(item['evidence_url'])}\">Sursă</a></li>"
        for item in profile.get("provenance") or []
    )
    document = (
        "<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{html.escape(profile['canonical_name'])}</title><link rel=\"canonical\" href=\"https://{html.escape(canonical_domain)}{html.escape(path)}\"></head><body>"
        f"<main><h1>{html.escape(profile['canonical_name'])}</h1><p>{html.escape(profile['entity_type'])}</p>"
        f"<h2>Date verificate</h2><ul>{facts}</ul><h2>Articole</h2><ul>{stories}</ul><h2>Surse</h2><ul>{sources}</ul></main></body></html>"
    )
    return document.encode("utf-8")


StartResponse = Callable[[str, list[tuple[str, str]]], Any]


class KnowledgeGraphSiteApp:
    """Mountable public-profile + private-newsroom WSGI surface."""

    def __init__(self, *, db_path: str | Path, instance_id: str, canonical_domain: str, entity_pack: dict[str, Any], newsroom_token: str | None) -> None:
        self.db_path = str(db_path)
        self.instance_id = instance_id
        self.canonical_domain = canonical_domain
        self.entity_pack = entity_pack
        self.policy = validate_entity_pack(entity_pack, instance_id=instance_id)
        self.newsroom_token = newsroom_token or None

    def _response(self, start_response: StartResponse, status: str, body: bytes, content_type: str, *, private: bool = False) -> Iterable[bytes]:
        headers = [("Content-Type", content_type), ("Content-Length", str(len(body))), ("X-Content-Type-Options", "nosniff")]
        if private:
            headers.extend([("Cache-Control", "no-store, private"), ("X-Robots-Tag", "noindex, nofollow, noarchive")])
        else:
            headers.append(("Cache-Control", "public, max-age=60"))
        start_response(status, headers)
        return [body]

    def _authorized(self, environ: dict[str, Any]) -> bool:
        header = str(environ.get("HTTP_AUTHORIZATION") or "")
        return bool(self.newsroom_token and header.startswith("Bearer ") and hmac.compare_digest(header[7:], self.newsroom_token))

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        if str(environ.get("REQUEST_METHOD") or "GET").upper() != "GET":
            return self._response(start_response, "405 Method Not Allowed", b"Method not allowed", "text/plain; charset=utf-8")
        path = str(environ.get("PATH_INFO") or "/")
        conn = connect(self.db_path)
        try:
            ensure_knowledge_schema(conn)
            if path == "/newsroom/knowledge" or path.startswith("/newsroom/api/knowledge/"):
                if not self._authorized(environ):
                    return self._response(start_response, "401 Unauthorized", b'{"error":"unauthorized"}', "application/json; charset=utf-8", private=True)
                if path == "/newsroom/knowledge":
                    payload = knowledge_summary(conn, instance_id=self.instance_id)
                elif path == "/newsroom/api/knowledge/entities":
                    payload = {"entities": list_entities(conn, instance_id=self.instance_id)}
                else:
                    rows = conn.execute("SELECT * FROM knowledge_edges WHERE instance_id=? ORDER BY created_at DESC LIMIT 200", (self.instance_id,)).fetchall()
                    payload = {"edges": [dict(row) for row in rows]}
                return self._response(start_response, "200 OK", json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"), "application/json; charset=utf-8", private=True)
            for kind, prefix in self.policy["profile_paths"].items():
                marker = prefix + "/"
                if path.startswith(marker) and path.endswith("/"):
                    slug = path[len(marker):].strip("/")
                    profile = public_profile(conn, instance_id=self.instance_id, entity_type=kind, slug=slug, entity_pack=self.entity_pack)
                    if profile is None:
                        break
                    return self._response(start_response, "200 OK", render_public_profile(profile, canonical_domain=self.canonical_domain, path=path), "text/html; charset=utf-8")
            return self._response(start_response, "404 Not Found", b"Not found", "text/plain; charset=utf-8")
        finally:
            conn.close()


def _manifest(instance_id: str, domain: str) -> dict[str, Any]:
    packs = {name: f"fixtures/{name}.json" for name in ("publication", "geography", "brand", "sources", "editorial", "channels", "entities", "photos")}
    return {"schema_version": "2.0", "instance_id": instance_id, "canonical_domain": domain, "runtime_owner": "site_application_database", "packs": packs}


def _pack(instance_id: str, *, people_prefix: str, org_prefix: str) -> dict[str, Any]:
    return {
        "schema_version": "2.0", "pack_type": "entities", "instance_id": instance_id, "migration": {"status": "NONE"}, "seeds": [],
        "knowledge_graph": {
            "public_profile_types": ["person", "organization"],
            "profile_paths": {"person": people_prefix, "organization": org_prefix},
            "minimum_public_provenance": 1,
        },
    }


def _evidence_fixture(url: str, assertion: str) -> dict[str, Any]:
    return {"source_url": url, "evidence_url": url, "evidence_fingerprint": hashlib.sha256((url + assertion).encode()).hexdigest(), "observed_at": "2026-08-19T12:00:00Z", "assertion": assertion}


def _wsgi_get(app: KnowledgeGraphSiteApp, path: str, *, token: str | None = None) -> tuple[str, bytes]:
    captured: dict[str, Any] = {}
    def start(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
    environ: dict[str, Any] = {"REQUEST_METHOD": "GET", "PATH_INFO": path}
    if token:
        environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    body = b"".join(app(environ, start))
    return str(captured["status"]), body


def self_test() -> None:
    from editorial_qa import _draft, _insert_fixture, _pack as editorial_pack, evaluate_story_draft
    from site_publication import _publication_pack, publish_story
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "knowledge.sqlite3"
        conn = connect(db)
        initialize(conn)
        ensure_publication_schema(conn)
        ensure_knowledge_schema(conn)
        engine = "vnext-knowledge-test"
        register_instance(conn, _manifest("alpha-local", "alpha.invalid"), engine_version=engine)
        register_instance(conn, _manifest("beta-local", "beta.invalid"), engine_version=engine)
        alpha_pack = _pack("alpha-local", people_prefix="/people", org_prefix="/organizations")
        beta_pack = _pack("beta-local", people_prefix="/residents", org_prefix="/groups")

        person_ev = _evidence_fixture("https://authority.invalid/person-1", "Alex Example holds the verified public role")
        person, created = materialize_verified_entity(
            conn, instance_id="alpha-local", entity_type="person", canonical_name="Alex Example", external_key="person-1",
            provenance=person_ev, entity_pack=alpha_pack, aliases=["A. Example"],
            facts=[{"key": "role", "value": "Director", "provenance": person_ev}], engine_version=engine,
        )
        assert created and person["state"] == "VERIFIED" and person["public_profile_allowed"] == 1
        again, created_again = materialize_verified_entity(
            conn, instance_id="alpha-local", entity_type="person", canonical_name="Alex Example", external_key="person-1",
            provenance=person_ev, entity_pack=alpha_pack, aliases=["A. Example"],
            facts=[{"key": "role", "value": "Director", "provenance": person_ev}], engine_version=engine,
        )
        assert not created_again and again["entity_id"] == person["entity_id"]
        assert resolve_entity_mention(conn, instance_id="alpha-local", mention="A. Example")["status"] == "RESOLVED"
        assert resolve_entity_mention(conn, instance_id="beta-local", mention="A. Example")["status"] == "UNRESOLVED"

        org_ev = _evidence_fixture("https://authority.invalid/org-1", "Example Office is a verified organization")
        org, _ = materialize_verified_entity(
            conn, instance_id="alpha-local", entity_type="organization", canonical_name="Example Office", external_key="org-1",
            provenance=org_ev, entity_pack=alpha_pack, engine_version=engine,
        )
        edge, edge_created = materialize_verified_edge(
            conn, instance_id="alpha-local", from_entity_id=person["entity_id"], relationship="MEMBER_OF",
            to_entity_id=org["entity_id"], provenance=_evidence_fixture("https://authority.invalid/relationship", "Alex Example is directly documented as member of Example Office"),
            engine_version=engine,
        )
        assert edge_created and edge["assertion_basis"] == "DIRECT_EVIDENCE"
        try:
            materialize_verified_edge(
                conn, instance_id="alpha-local", from_entity_id=person["entity_id"], relationship="MEMBER_OF",
                to_entity_id=org["entity_id"], provenance=None, engine_version=engine,
            )
            raise AssertionError("material edge without provenance was accepted")
        except KnowledgeGraphError:
            pass

        _insert_fixture(conn, instance_id="alpha-local", signal_id="s1", kernel_id="k1", headline="Alex Example confirms verified service changes", suffix="kg1")
        draft = _draft(conn, instance_id="alpha-local", kernel_id="k1", pack=editorial_pack("alpha-local", "fraud"), engine=engine)
        # Bind the verified name to the draft without asserting a public relationship.
        conn.execute(
            "UPDATE story_drafts SET entity_bindings_json=? WHERE instance_id=? AND story_id=?",
            (json.dumps([{"mention": "Alex Example", "kind": "person", "resolution_status": "UNRESOLVED", "public_claim_allowed": False}]), "alpha-local", draft["story_id"]),
        )
        conn.commit()
        qa, _ = evaluate_story_draft(conn, instance_id="alpha-local", story_id=draft["story_id"], editorial_pack=editorial_pack("alpha-local", "fraud"), engine_version=engine)
        assert qa["outcome"] == "QA_PASSED"
        pub_pack = _publication_pack("alpha-local", "alpha.invalid", "/stories", "/section")
        publication, _ = publish_story(conn, instance_id="alpha-local", story_id=draft["story_id"], publication_pack=pub_pack, engine_version=engine)
        enriched = enrich_published_story(
            conn, instance_id="alpha-local", story_id=draft["story_id"], canonical_domain="alpha.invalid", entity_pack=alpha_pack, engine_version=engine,
        )
        assert enriched["resolved_mentions"] == 1
        assert knowledge_summary(conn, instance_id="alpha-local")["edges"]["MENTIONS"] == 1
        profile = public_profile(conn, instance_id="alpha-local", entity_type="person", slug=person["slug"], entity_pack=alpha_pack)
        assert profile and len(profile["related_stories"]) == 1
        assert profile_path(person, entity_pack=alpha_pack, instance_id="alpha-local") == f"/people/{person['slug']}/"

        app = KnowledgeGraphSiteApp(db_path=db, instance_id="alpha-local", canonical_domain="alpha.invalid", entity_pack=alpha_pack, newsroom_token="secret")
        profile_route = f"/people/{person['slug']}/"
        assert _wsgi_get(app, profile_route)[0] == "200 OK"
        assert b"Alex Example" in _wsgi_get(app, profile_route)[1]
        assert _wsgi_get(app, "/newsroom/knowledge")[0] == "401 Unauthorized"
        assert _wsgi_get(app, "/newsroom/knowledge", token="secret")[0] == "200 OK"

        beta_ev = _evidence_fixture("https://beta.invalid/person", "Second instance evidence")
        beta_person, _ = materialize_verified_entity(
            conn, instance_id="beta-local", entity_type="person", canonical_name="Alex Example", external_key="person-1",
            provenance=beta_ev, entity_pack=beta_pack, engine_version=engine,
        )
        assert beta_person["entity_id"] != person["entity_id"]
        assert profile_path(beta_person, entity_pack=beta_pack, instance_id="beta-local").startswith("/residents/")

        provenance_id = conn.execute("SELECT provenance_id FROM knowledge_entity_provenance WHERE instance_id='alpha-local' LIMIT 1").fetchone()[0]
        try:
            conn.execute("UPDATE knowledge_entity_provenance SET assertion='changed' WHERE provenance_id=?", (provenance_id,))
            raise AssertionError("append-only provenance mutated")
        except sqlite3.IntegrityError:
            conn.rollback()
        conn.close()
    print("LOCAL_NEWS_OS_VNEXT_KNOWLEDGE_GRAPH_SELF_TEST_PASS")


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
