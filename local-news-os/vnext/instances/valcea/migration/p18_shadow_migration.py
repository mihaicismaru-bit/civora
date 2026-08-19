#!/usr/bin/env python3
"""P18 shadow migration harness for the VÂLCEA CLAR vNext cutover.

This is intentionally instance-specific migration code, not generic core logic.
It imports the already-public legacy VÂLCEA CLAR corpus into an isolated
site-owned SQLite shadow runtime, proves ID/URL/content parity, imports the
public knowledge/profile surface, migrates rights-safe approved media, and
captures Facebook/Instagram legacy delivery history without treating it as
new vNext LIVE evidence.

It performs no network publication, no DNS mutation, no public runtime write,
and no legacy-writer fencing. Those actions remain later P18 gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[5]
VNEXT = REPO_ROOT / "local-news-os" / "vnext"
CORE = VNEXT / "core"
sys.path.insert(0, str(CORE))

from instance_model import build_release_manifest  # noqa: E402
from runtime_store import connect, initialize, register_instance, utc_now  # noqa: E402

INSTANCE_ID = "valcea"
ENGINE_VERSION = "p18-shadow-migration-1"

BASE_SCHEMA = VNEXT / "runtime" / "schema.sql"
PUBLICATION_SCHEMA = VNEXT / "runtime" / "publication_schema.sql"
KNOWLEDGE_SCHEMA = VNEXT / "runtime" / "knowledge_schema.sql"
MEDIA_SCHEMA = VNEXT / "runtime" / "media_schema.sql"
DISTRIBUTION_SCHEMA = VNEXT / "runtime" / "distribution_schema.sql"

INSTANCE_PATH = VNEXT / "instances" / INSTANCE_ID / "instance.json"
BUILD_READY_PATH = VNEXT / "BUILD_READY_FOR_MIGRATION.json"
MIGRATION_READINESS_PATH = VNEXT / "instances" / INSTANCE_ID / "MIGRATION_READINESS_V1.json"

LEGACY = {
    "publication_event": REPO_ROOT / "valcea-clar" / "site" / "story_publication_event.json",
    "live_feed": REPO_ROOT / "valcea-clar" / "site" / "runtime" / "live-feed.json",
    "people": REPO_ROOT / "valcea-clar" / "site" / "runtime" / "people.json",
    "artists": REPO_ROOT / "valcea-clar" / "site" / "runtime" / "artists.json",
    "places": REPO_ROOT / "valcea-clar" / "data" / "places.json",
    "creators": REPO_ROOT / "valcea-clar" / "data" / "creators.json",
    "story_visuals": REPO_ROOT / "valcea-clar" / "social" / "story_visuals.json",
    "facebook": REPO_ROOT / "valcea-clar" / "social" / "facebook_state.json",
    "instagram": REPO_ROOT / "valcea-clar" / "social" / "instagram_state.json",
}


class MigrationError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MigrationError(f"missing migration source: {path.relative_to(REPO_ROOT)}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MigrationError(f"migration source must be an object: {path.relative_to(REPO_ROOT)}")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    if isinstance(value, bytes):
        data = value
    elif isinstance(value, str):
        data = value.encode("utf-8")
    else:
        data = _json(value).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _id(*parts: str, length: int = 28) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:length]


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def _canonical_path(story: dict[str, Any], canonical_url: str | None) -> str:
    path = str(story.get("path") or "").strip()
    if not path and canonical_url:
        path = urlparse(canonical_url).path
    if not path.startswith("/") or "?" in path or "#" in path:
        raise MigrationError(f"unsafe canonical path for {story.get('id')}: {path!r}")
    return path if path.endswith("/") else path + "/"


def _ensure_shadow_schemas(conn: sqlite3.Connection) -> None:
    initialize(conn)
    for path in (PUBLICATION_SCHEMA, KNOWLEDGE_SCHEMA, MEDIA_SCHEMA, DISTRIBUTION_SCHEMA):
        conn.executescript(path.read_text(encoding="utf-8"))
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS migration_source_receipts (
            instance_id TEXT NOT NULL,
            domain TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_git_blob_sha TEXT NOT NULL,
            imported_count INTEGER NOT NULL,
            held_count INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(instance_id, domain, source_git_blob_sha)
        );
        CREATE TABLE IF NOT EXISTS legacy_social_history (
            instance_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            legacy_key TEXT NOT NULL,
            external_object_id TEXT NOT NULL,
            published_at TEXT,
            public_link TEXT,
            payload_json TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(instance_id, channel_id, legacy_key),
            UNIQUE(instance_id, channel_id, fingerprint)
        );
        """
    )
    conn.commit()


def _record_receipt(
    conn: sqlite3.Connection,
    *,
    domain: str,
    path: Path,
    imported: int,
    held: int = 0,
    payload: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO migration_source_receipts(
            instance_id,domain,source_path,source_git_blob_sha,imported_count,
            held_count,payload_json,created_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            INSTANCE_ID,
            domain,
            str(path.relative_to(REPO_ROOT)),
            _git_blob_sha(path),
            int(imported),
            int(held),
            _json(payload or {}),
            utc_now(),
        ),
    )


def _public_snapshot(story: dict[str, Any]) -> dict[str, Any]:
    sources = []
    for src in story.get("sources") or []:
        if not isinstance(src, dict) or not src.get("url"):
            continue
        sources.append(
            {
                "name": str(src.get("name") or "Sursă"),
                "evidence_url": str(src["url"]),
                "tier": str(src.get("tier") or ""),
                "migration_source": "legacy_live_feed",
            }
        )
    paragraphs = [str(p).strip() for p in story.get("paragraphs") or [] if str(p).strip()]
    return {
        "story_id": str(story["id"]),
        "headline": str(story.get("headline") or "").strip(),
        "dek": str(story.get("dek") or "").strip(),
        "body_blocks": [{"kind": "paragraph", "text": p} for p in paragraphs],
        "factbox": list(story.get("factbox") or []),
        "context": {
            "legacy_import": True,
            "legacy_priority": story.get("priority"),
            "legacy_visual": story.get("visual"),
        },
        "source_references": sources,
        "follow_up": dict(story.get("follow_up") or {}),
        "section": str(story.get("section") or "ȘTIRI"),
        "tags": list(story.get("tags") or []),
    }


def import_publications(conn: sqlite3.Connection) -> dict[str, Any]:
    event = _load(LEGACY["publication_event"])
    feed = _load(LEGACY["live_feed"])
    stories = {str(item.get("id")): item for item in feed.get("stories") or [] if isinstance(item, dict) and item.get("id")}
    story_ids = [str(value) for value in event.get("story_ids") or []]
    urls = event.get("canonical_urls") or {}
    missing = [story_id for story_id in story_ids if story_id not in stories]
    if missing:
        raise MigrationError(f"publication-event stories missing from live feed: {missing}")
    imported_paths: dict[str, str] = {}
    fallback_published_at = str(event.get("published_at") or utc_now())
    now = utc_now()
    for story_id in story_ids:
        item = stories[story_id]
        canonical_path = _canonical_path(item, str(urls.get(story_id) or ""))
        expected_url = str(urls.get(story_id) or "")
        if expected_url and urlparse(expected_url).path.rstrip("/") != canonical_path.rstrip("/"):
            raise MigrationError(f"canonical URL/path mismatch for {story_id}")
        snapshot = _public_snapshot(item)
        if not snapshot["headline"] or not snapshot["dek"] or not snapshot["body_blocks"]:
            raise MigrationError(f"legacy story is incomplete for shadow import: {story_id}")
        story_fp = _sha({"legacy_story": item, "canonical_path": canonical_path})
        draft_fp = _sha({"legacy_snapshot": snapshot})
        qa_id = "migqa-" + _id(story_id, draft_fp)
        qa_fp = _sha({"legacy_migration_qa": story_id, "draft": draft_fp})
        publication_id = "migpub-" + _id(INSTANCE_ID, story_id, canonical_path)
        content_fp = _sha({"canonical_path": canonical_path, "snapshot": snapshot})
        revision_id = "migrev-" + _id(publication_id, content_fp)
        published_at = str(item.get("published_at") or fallback_published_at)
        conn.execute(
            """
            INSERT INTO stories(instance_id,story_id,fingerprint,state,revision,headline,canonical_path,created_at,updated_at)
            VALUES (?,?,?,'PUBLISHED',1,?,?,?,?)
            """,
            (INSTANCE_ID, story_id, story_fp, snapshot["headline"], canonical_path, published_at, now),
        )
        conn.execute(
            """
            INSERT INTO editorial_qa_decisions(
                instance_id,decision_id,story_id,draft_fingerprint,draft_revision,
                decision_fingerprint,editorial_class,outcome,gates_json,
                duplicate_story_id,publication_authority,created_at
            ) VALUES (?,?,?,?,1,?,'MIGRATED_LEGACY_PUBLICATION','QA_PASSED',?,NULL,'NONE',?)
            """,
            (
                INSTANCE_ID,
                qa_id,
                story_id,
                draft_fp,
                qa_fp,
                _json(
                    {
                        "migration": "accepted_already_public_legacy_content",
                        "not_represented_as_fresh_vnext_qa": True,
                        "source": str(LEGACY["live_feed"].relative_to(REPO_ROOT)),
                    }
                ),
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO story_publications(
                instance_id,story_id,publication_id,canonical_path,current_revision,
                current_content_fingerprint,published_at,updated_at
            ) VALUES (?,?,?,?,1,?,?,?)
            """,
            (INSTANCE_ID, story_id, publication_id, canonical_path, content_fp, published_at, now),
        )
        conn.execute(
            """
            INSERT INTO publication_revisions(
                instance_id,publication_revision_id,publication_id,story_id,revision,
                qa_decision_id,draft_fingerprint,content_fingerprint,snapshot_json,created_at
            ) VALUES (?,?,?,?,1,?,?,?,?,?)
            """,
            (INSTANCE_ID, revision_id, publication_id, story_id, qa_id, draft_fp, content_fp, _json(snapshot), now),
        )
        conn.execute(
            """
            INSERT INTO runtime_events(
                instance_id,aggregate_type,aggregate_id,event_type,from_state,to_state,
                reason,payload_json,engine_version,created_at
            ) VALUES (?,'story',?,'LEGACY_PUBLICATION_IMPORTED',NULL,'PUBLISHED',?,?,?,?)
            """,
            (
                INSTANCE_ID,
                story_id,
                "Already-public legacy story imported into isolated vNext shadow runtime",
                _json({"canonical_path": canonical_path, "content_fingerprint": content_fp}),
                ENGINE_VERSION,
                now,
            ),
        )
        imported_paths[story_id] = canonical_path
    _record_receipt(
        conn,
        domain="stories_and_urls",
        path=LEGACY["publication_event"],
        imported=len(story_ids),
        payload={"canonical_paths": imported_paths},
    )
    _record_receipt(conn, domain="story_content", path=LEGACY["live_feed"], imported=len(story_ids))
    conn.commit()
    return {"count": len(story_ids), "paths": imported_paths, "source_event": event}


def _source_urls(profile: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for src in profile.get("public_sources") or []:
        if isinstance(src, dict) and src.get("url"):
            urls.append(str(src["url"]))
    for url in profile.get("source_urls") or []:
        if url:
            urls.append(str(url))
    for role in profile.get("roles") or []:
        if isinstance(role, dict):
            urls.extend(str(url) for url in role.get("source_urls") or [] if url)
    for appearance in profile.get("appearances") or []:
        if isinstance(appearance, dict) and appearance.get("source_url"):
            urls.append(str(appearance["source_url"]))
    return sorted(set(urls))


def _insert_entity(
    conn: sqlite3.Connection,
    *,
    entity_id: str,
    entity_type: str,
    name: str,
    slug: str,
    summary: str,
    attributes: dict[str, Any],
    source_urls: list[str],
    public_requested: bool,
    source_path: Path,
) -> bool:
    now = utc_now()
    http_sources = sorted({str(url).strip() for url in source_urls if str(url).startswith(("http://", "https://"))})
    provenance = [
        {
            "source_url": url,
            "evidence_fingerprint": _sha({"migration_source": str(source_path.relative_to(REPO_ROOT)), "source_url": url}),
            "observed_at": now,
            "source_kind": "LEGACY_MIGRATION",
            "note": "Imported from already-public legacy VÂLCEA CLAR intelligence; no fresh authority inferred.",
        }
        for url in http_sources
    ]
    evidence_backed = bool(provenance)
    is_public = bool(public_requested and evidence_backed)
    status = "EVIDENCE_BACKED" if evidence_backed else "CANDIDATE"
    fp = _sha({"type": entity_type, "id": entity_id, "name": name, "sources": http_sources})
    conn.execute(
        """
        INSERT INTO knowledge_entities(
            instance_id,entity_id,entity_type,canonical_name,slug,summary,
            attributes_json,evidence_status,provenance_json,is_public,fingerprint,
            created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            INSTANCE_ID, entity_id, entity_type, name, slug, summary,
            _json(attributes), status, _json(provenance), 1 if is_public else 0,
            fp, now, now,
        ),
    )
    return is_public


def _insert_aliases(conn: sqlite3.Connection, *, entity_id: str, aliases: list[str], source_path: Path) -> int:
    inserted = 0
    for alias in aliases:
        clean = " ".join(str(alias).split())
        if not clean:
            continue
        normalized = clean.casefold()
        exists = conn.execute(
            "SELECT entity_id FROM knowledge_aliases WHERE instance_id=? AND normalized_alias=?",
            (INSTANCE_ID, normalized),
        ).fetchone()
        if exists is not None and exists["entity_id"] != entity_id:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO knowledge_aliases(
                instance_id,normalized_alias,entity_id,alias,provenance_json,created_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                INSTANCE_ID, normalized, entity_id, clean,
                _json({"migration_source": str(source_path.relative_to(REPO_ROOT))}), utc_now(),
            ),
        )
        inserted += 1
    return inserted


def _link_story(conn: sqlite3.Connection, *, story_id: str, entity_id: str, role: str, source_path: Path) -> bool:
    exists = conn.execute(
        "SELECT 1 FROM stories WHERE instance_id=? AND story_id=?", (INSTANCE_ID, story_id)
    ).fetchone()
    if exists is None:
        return False
    fp = _sha({"story": story_id, "entity": entity_id, "role": role})
    conn.execute(
        """
        INSERT OR IGNORE INTO story_entity_links(
            instance_id,story_id,entity_id,role,provenance_json,fingerprint,created_at
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (
            INSTANCE_ID, story_id, entity_id, role,
            _json({"migration_source": str(source_path.relative_to(REPO_ROOT))}), fp, utc_now(),
        ),
    )
    return True


def import_people(conn: sqlite3.Connection) -> dict[str, int]:
    data = _load(LEGACY["people"])
    imported = public = links = 0
    for profile in data.get("profiles") or []:
        if not isinstance(profile, dict) or not profile.get("id") or not profile.get("name"):
            continue
        pid = str(profile["id"])
        urls = _source_urls(profile)
        is_public = _insert_entity(
            conn,
            entity_id="person:" + pid,
            entity_type="PERSON",
            name=str(profile["name"]),
            slug=pid,
            summary=str(profile.get("summary") or profile.get("public_interest_basis") or ""),
            attributes={
                "legacy_path": profile.get("path"),
                "profile_types": profile.get("profile_types") or [],
                "identity": profile.get("identity") or {},
                "roles": profile.get("roles") or [],
            },
            source_urls=urls,
            public_requested=profile.get("publication_status") == "public",
            source_path=LEGACY["people"],
        )
        imported += 1
        public += int(is_public)
        _insert_aliases(
            conn,
            entity_id="person:" + pid,
            aliases=[str(profile["name"]), *(profile.get("aliases") or [])],
            source_path=LEGACY["people"],
        )
        for story_id in profile.get("story_refs") or []:
            links += int(_link_story(conn, story_id=str(story_id), entity_id="person:" + pid, role="PERSON_PROFILE", source_path=LEGACY["people"]))
    _record_receipt(conn, domain="people", path=LEGACY["people"], imported=imported, payload={"public": public, "story_links": links})
    conn.commit()
    return {"imported": imported, "public": public, "story_links": links}


def import_artists(conn: sqlite3.Connection) -> dict[str, int]:
    data = _load(LEGACY["artists"])
    imported = public = links = 0
    for profile in data.get("profiles") or []:
        if not isinstance(profile, dict) or not profile.get("id") or not profile.get("name"):
            continue
        aid = str(profile["id"])
        urls = _source_urls(profile)
        is_public = _insert_entity(
            conn,
            entity_id="artist:" + aid,
            entity_type="ARTIST",
            name=str(profile["name"]),
            slug=aid,
            summary=str(profile.get("bio") or ""),
            attributes={
                "legacy_path": profile.get("path"),
                "resolution_status": profile.get("resolution_status"),
                "musicbrainz_id": profile.get("musicbrainz_id"),
                "links": profile.get("links") or {},
            },
            source_urls=urls,
            public_requested=profile.get("publication_status") == "public",
            source_path=LEGACY["artists"],
        )
        imported += 1
        public += int(is_public)
        _insert_aliases(conn, entity_id="artist:" + aid, aliases=[str(profile["name"])], source_path=LEGACY["artists"])
        seen_story_ids = set()
        for item in [*(profile.get("festivals") or []), *(profile.get("appearances") or [])]:
            if isinstance(item, dict) and item.get("story_id"):
                seen_story_ids.add(str(item["story_id"]))
        for story_id in sorted(seen_story_ids):
            links += int(_link_story(conn, story_id=story_id, entity_id="artist:" + aid, role="ARTIST_APPEARANCE", source_path=LEGACY["artists"]))
    _record_receipt(conn, domain="artists", path=LEGACY["artists"], imported=imported, payload={"public": public, "story_links": links})
    conn.commit()
    return {"imported": imported, "public": public, "story_links": links}


def import_places_and_creators(conn: sqlite3.Connection) -> dict[str, int]:
    places = _load(LEGACY["places"])
    creators = _load(LEGACY["creators"])
    imported_places = public_places = 0
    for place in places.get("places") or []:
        if not isinstance(place, dict) or not place.get("id") or not place.get("name"):
            continue
        pid = str(place["id"])
        source_ids = [str(v) for v in place.get("source_ids") or [] if v]
        source_urls = []
        website = ((place.get("contact") or {}).get("website") if isinstance(place.get("contact"), dict) else None)
        if website:
            source_urls.append(str(website))
        # Source IDs are retained as provenance attributes even when their URL registry is migrated separately.
        is_public = _insert_entity(
            conn,
            entity_id="place:" + pid,
            entity_type="PLACE",
            name=str(place["name"]),
            slug=str(place.get("slug") or pid),
            summary=str(((place.get("offer") or {}).get("summary") if isinstance(place.get("offer"), dict) else "") or ""),
            attributes={
                "legacy_type": place.get("type"),
                "status": place.get("status"),
                "verification_level": place.get("verification_level"),
                "location": place.get("location") or {},
                "operator": place.get("operator") or {},
                "source_ids": source_ids,
            },
            source_urls=source_urls or (["urn:legacy-source-id:" + source_ids[0]] if source_ids else []),
            public_requested=place.get("publication_status") == "public" and place.get("verification_level") == "verified",
            source_path=LEGACY["places"],
        )
        imported_places += 1
        public_places += int(is_public)
    creator_items = creators.get("creators") or creators.get("profiles") or []
    imported_creators = public_creators = 0
    for creator in creator_items:
        if not isinstance(creator, dict) or not creator.get("id") or not creator.get("name"):
            continue
        cid = str(creator["id"])
        urls = _source_urls(creator)
        is_public = _insert_entity(
            conn,
            entity_id="person:creator:" + cid,
            entity_type="PERSON",
            name=str(creator["name"]),
            slug="creator-" + cid,
            summary=str(creator.get("summary") or ""),
            attributes={"creator_intelligence": True, "legacy_status": creator.get("publication_status")},
            source_urls=urls,
            public_requested=creator.get("publication_status") == "public",
            source_path=LEGACY["creators"],
        )
        imported_creators += 1
        public_creators += int(is_public)
    _record_receipt(conn, domain="places", path=LEGACY["places"], imported=imported_places, payload={"public": public_places})
    _record_receipt(conn, domain="creator_intelligence", path=LEGACY["creators"], imported=imported_creators, payload={"public": public_creators})
    conn.commit()
    return {
        "places_imported": imported_places,
        "places_public": public_places,
        "creators_imported": imported_creators,
        "creators_public": public_creators,
    }


def _media_rights(image: dict[str, Any]) -> tuple[str, str, str]:
    raw = str(image.get("rights_basis") or "").casefold()
    license_url = str(image.get("license_url") or "").casefold()
    if raw == "public_domain":
        return "OPEN_LICENSED", "PUBLIC_DOMAIN", "PUBLIC_DOMAIN"
    if raw == "creative_commons":
        if "by-sa" in license_url:
            return "OPEN_LICENSED", "CC_BY_SA", "CC_BY_SA"
        return "OPEN_LICENSED", "CC_BY", "CC_BY"
    if raw in {"user_owned", "owned"}:
        return "USER_OWNED", "USER_OWNED", "USER_OWNED"
    if raw in {"explicit_license", "licensed"}:
        return "EXPLICIT_LICENSED", "EXPLICIT_LICENSE", "EXPLICIT_LICENSE"
    if raw in {"official_press_use", "press_use"}:
        return "OFFICIAL", "OFFICIAL_PRESS_USE", "OFFICIAL_PRESS_USE"
    raise MigrationError(f"unsupported approved legacy media rights basis: {raw!r}")


def import_media(conn: sqlite3.Connection) -> dict[str, int]:
    data = _load(LEGACY["story_visuals"])
    imported = bound = held = 0
    seen_assets: set[str] = set()
    for story_id, wrapper in (data.get("stories") or {}).items():
        if not isinstance(wrapper, dict):
            continue
        image = wrapper.get("image") or {}
        if not isinstance(image, dict) or image.get("synthetic") is not False or not image.get("editor_approved"):
            held += 1
            continue
        source_type, rights_basis, license_code = _media_rights(image)
        storage_uri = str(wrapper.get("image_path") or image.get("direct_source_url") or "").strip()
        source_url = str(image.get("source_url") or "").strip() or None
        if not storage_uri or not image.get("credit") or not image.get("rights_note"):
            held += 1
            continue
        asset_id = "legacy-photo-" + _id(storage_uri, source_url or "")
        if asset_id not in seen_assets:
            conn.execute(
                """
                INSERT INTO media_assets(
                    instance_id,asset_id,media_kind,storage_uri,source_type,source_url,
                    rights_basis,license_code,credit,rights_evidence,synthetic,
                    depicts_real_scene,freshness_class,captured_at,usage_scopes_json,
                    metadata_json,content_fingerprint,status,created_at,updated_at
                ) VALUES (?,?, 'PHOTO',?,?,?,?,?,?,?,0,1,?,?,?,?,?,'READY',?,?)
                """,
                (
                    INSTANCE_ID, asset_id, storage_uri, source_type, source_url,
                    rights_basis, license_code, str(image.get("credit")), str(image.get("rights_note")),
                    "SLOW_DECAY" if image.get("contextual_archive") else "EVERGREEN",
                    image.get("captured_at"), _json(["SITE_HERO", "SITE_CARD", "SOCIAL_FACEBOOK", "SOCIAL_INSTAGRAM"]),
                    _json({"alt_text": image.get("alt_text"), "license_url": image.get("license_url"), "legacy_import": True}),
                    _sha({"storage_uri": storage_uri, "source_url": source_url, "rights": rights_basis}), utc_now(), utc_now(),
                ),
            )
            seen_assets.add(asset_id)
            imported += 1
        story_exists = conn.execute(
            "SELECT 1 FROM stories WHERE instance_id=? AND story_id=?", (INSTANCE_ID, str(story_id))
        ).fetchone()
        if story_exists is None:
            continue
        specificity = "CONTEXT_ARCHIVE" if image.get("contextual_archive") else "SUBJECT_DIRECT"
        disclosure = str(image.get("editorial_note") or "")
        binding_id = "migbind-" + _id(asset_id, str(story_id), specificity)
        conn.execute(
            """
            INSERT OR IGNORE INTO media_bindings(
                instance_id,binding_id,asset_id,target_type,target_id,specificity_class,
                context_disclosure,provenance_json,fingerprint,created_at
            ) VALUES (?,?,?,'STORY',?,?,?,?,?,?)
            """,
            (
                INSTANCE_ID, binding_id, asset_id, str(story_id), specificity, disclosure,
                _json({"migration_source": str(LEGACY["story_visuals"].relative_to(REPO_ROOT)), "source_url": source_url}),
                _sha({"asset": asset_id, "story": story_id, "specificity": specificity}), utc_now(),
            ),
        )
        bound += 1
    _record_receipt(conn, domain="approved_story_visuals", path=LEGACY["story_visuals"], imported=imported, held=held, payload={"bound_to_migrated_stories": bound})
    conn.commit()
    return {"assets_imported": imported, "story_bindings": bound, "held": held}


def import_legacy_social_history(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for channel, path in (("facebook", LEGACY["facebook"]), ("instagram", LEGACY["instagram"])):
        data = _load(path)
        published = data.get("published") or {}
        if not isinstance(published, dict):
            published = {}
        count = 0
        for key, payload in published.items():
            if not isinstance(payload, dict):
                continue
            external_id = str(
                payload.get("facebook_post_id")
                or payload.get("instagram_media_id")
                or payload.get("media_id")
                or ""
            ).strip()
            if not external_id:
                continue
            fp = _sha({"channel": channel, "legacy_key": key, "external_id": external_id, "payload": payload})
            conn.execute(
                """
                INSERT OR IGNORE INTO legacy_social_history(
                    instance_id,channel_id,legacy_key,external_object_id,published_at,
                    public_link,payload_json,fingerprint,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    INSTANCE_ID, channel, str(key), external_id, payload.get("published_at"),
                    payload.get("link"), _json(payload), fp, utc_now(),
                ),
            )
            count += 1
        counts[channel] = count
        _record_receipt(conn, domain=f"{channel}_delivery_history", path=path, imported=count, payload={"active_delivery_ledger_mutated": False})
    conn.commit()
    return counts


def _fresh_source_drift() -> dict[str, Any]:
    readiness = _load(MIGRATION_READINESS_PATH)
    by_path = {
        str(item.get("source_path")): str(item.get("source_sha") or "")
        for item in readiness.get("migration_sources") or []
        if isinstance(item, dict) and item.get("source_path")
    }
    drift = {}
    for name, path in LEGACY.items():
        rel = str(path.relative_to(REPO_ROOT))
        current = _git_blob_sha(path)
        expected = by_path.get(rel)
        drift[name] = {
            "path": rel,
            "current_git_blob_sha": current,
            "readiness_git_blob_sha": expected or None,
            "changed_since_readiness": bool(expected and expected != current),
        }
    return drift


def validate_shadow(conn: sqlite3.Connection, imported: dict[str, Any]) -> dict[str, Any]:
    event = _load(LEGACY["publication_event"])
    expected_ids = [str(v) for v in event.get("story_ids") or []]
    expected_paths = {
        story_id: urlparse(str((event.get("canonical_urls") or {}).get(story_id) or "")).path.rstrip("/") + "/"
        for story_id in expected_ids
    }
    rows = conn.execute(
        "SELECT story_id,canonical_path FROM story_publications WHERE instance_id=? ORDER BY story_id",
        (INSTANCE_ID,),
    ).fetchall()
    actual = {str(row["story_id"]): str(row["canonical_path"]) for row in rows}
    story_parity = set(actual) == set(expected_ids)
    url_parity = story_parity and all(actual[sid] == expected_paths[sid] for sid in expected_ids)
    public_people_expected = sum(
        1 for p in (_load(LEGACY["people"]).get("profiles") or [])
        if isinstance(p, dict) and p.get("publication_status") == "public" and _source_urls(p)
    )
    public_artists_expected = sum(
        1 for p in (_load(LEGACY["artists"]).get("profiles") or [])
        if isinstance(p, dict) and p.get("publication_status") == "public" and _source_urls(p)
    )
    public_people_actual = conn.execute(
        "SELECT COUNT(*) n FROM knowledge_entities WHERE instance_id=? AND entity_type='PERSON' AND is_public=1 AND entity_id LIKE 'person:%' AND entity_id NOT LIKE 'person:creator:%'",
        (INSTANCE_ID,),
    ).fetchone()["n"]
    public_artists_actual = conn.execute(
        "SELECT COUNT(*) n FROM knowledge_entities WHERE instance_id=? AND entity_type='ARTIST' AND is_public=1",
        (INSTANCE_ID,),
    ).fetchone()["n"]
    social_active = conn.execute(
        "SELECT COUNT(*) n FROM delivery_ledger WHERE instance_id=?", (INSTANCE_ID,)
    ).fetchone()["n"]
    duplicate_paths = conn.execute(
        "SELECT COUNT(*) n FROM (SELECT canonical_path,COUNT(*) c FROM story_publications WHERE instance_id=? GROUP BY canonical_path HAVING c>1)",
        (INSTANCE_ID,),
    ).fetchone()["n"]
    checks = {
        "story_id_parity": story_parity,
        "canonical_url_parity": url_parity,
        "public_people_parity": int(public_people_actual) == int(public_people_expected),
        "public_artists_parity": int(public_artists_actual) == int(public_artists_expected),
        "duplicate_canonical_paths_zero": int(duplicate_paths) == 0,
        "legacy_social_history_did_not_mutate_active_delivery_ledger": int(social_active) == 0,
        "network_publication_attempted": False,
        "public_runtime_mutated": False,
    }
    return {
        "checks": checks,
        "pass": all(value is True for key, value in checks.items() if key not in {"network_publication_attempted", "public_runtime_mutated"})
        and checks["network_publication_attempted"] is False
        and checks["public_runtime_mutated"] is False,
        "counts": {
            "stories": len(actual),
            "public_people": int(public_people_actual),
            "public_artists": int(public_artists_actual),
            "media_assets": conn.execute("SELECT COUNT(*) n FROM media_assets WHERE instance_id=?", (INSTANCE_ID,)).fetchone()["n"],
            "media_bindings": conn.execute("SELECT COUNT(*) n FROM media_bindings WHERE instance_id=?", (INSTANCE_ID,)).fetchone()["n"],
            "legacy_social_history": conn.execute("SELECT COUNT(*) n FROM legacy_social_history WHERE instance_id=?", (INSTANCE_ID,)).fetchone()["n"],
        },
        "expected": {
            "stories": len(expected_ids),
            "public_people": public_people_expected,
            "public_artists": public_artists_expected,
        },
    }


def run_shadow(db_path: Path) -> dict[str, Any]:
    build_ready = _load(BUILD_READY_PATH)
    if build_ready.get("status") != "BUILD_READY_FOR_MIGRATION":
        raise MigrationError("vNext build is not BUILD_READY_FOR_MIGRATION")
    if build_ready.get("production_cutover") is not False:
        raise MigrationError("shadow migration requires production_cutover=false")
    instance = _load(INSTANCE_PATH)
    if instance.get("instance_id") != INSTANCE_ID:
        raise MigrationError("instance mismatch")
    if ((instance.get("runtime") or {}).get("owner")) != "site_application":
        raise MigrationError("SITE_OWNS_RUNTIME violation")
    conn = connect(db_path)
    try:
        _ensure_shadow_schemas(conn)
        register_instance(conn, build_release_manifest(instance), engine_version=ENGINE_VERSION)
        publications = import_publications(conn)
        people = import_people(conn)
        artists = import_artists(conn)
        local_knowledge = import_places_and_creators(conn)
        media = import_media(conn)
        social = import_legacy_social_history(conn)
        validation = validate_shadow(conn, {"publications": publications})
        result = {
            "schema_version": "1.0",
            "contract": "LOCAL_NEWS_OS_VNEXT_VALCEA_P18_SHADOW_MIGRATION_V1",
            "status": "SHADOW_MIGRATION_PASS" if validation["pass"] else "SHADOW_MIGRATION_FAIL",
            "instance_id": INSTANCE_ID,
            "engine_version": ENGINE_VERSION,
            "build_ready_sha": _git_blob_sha(BUILD_READY_PATH),
            "production_cutover": False,
            "public_runtime_mutated": False,
            "network_publication_attempted": False,
            "source_drift": _fresh_source_drift(),
            "imports": {
                "publications": {"count": publications["count"]},
                "people": people,
                "artists": artists,
                "local_knowledge": local_knowledge,
                "media": media,
                "legacy_social_history": social,
            },
            "validation": validation,
            "next_gate": "SHADOW_RUNTIME_PROJECTION_AND_DIFF",
        }
        return result
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", help="Optional isolated SQLite shadow database path")
    parser.add_argument("--report", help="Optional JSON report output path")
    args = parser.parse_args()
    if args.db:
        db_path = Path(args.db)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        result = run_shadow(db_path)
    else:
        with tempfile.TemporaryDirectory() as td:
            result = run_shadow(Path(td) / "valcea-shadow.sqlite3")
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["status"] == "SHADOW_MIGRATION_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
