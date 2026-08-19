#!/usr/bin/env python3
"""Generic instance bootstrap for LOCAL NEWS OS vNext P17.

Creates one publication instance entirely from configuration, emits the eight
versioned instance packs plus instance.json, and can initialize a fresh
site-owned runtime database/release state. It never discovers or asserts
official authority on its own.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from distribution_engine import validate_channels_pack
from instance_model import REQUIRED_PACKS, REQUIRED_POLICIES, build_release_manifest, validate_instance
from release_control import initialize_release_state
from runtime_store import connect, initialize, register_instance
from source_adapters import SUPPORTED_ADAPTERS, validate_source_pack

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
DOMAIN_RE = re.compile(r"^(?=.{3,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
ALLOWED_ENVIRONMENTS = {"test", "staging", "production"}
ALLOWED_BACKENDS = {"sqlite", "postgresql", "database"}
DEFAULT_WEIGHTS = {
    "local_impact": 16,
    "public_utility": 18,
    "urgency": 12,
    "money": 10,
    "affected_people": 12,
    "novelty": 12,
    "accountability": 10,
    "proximity": 10,
}


class BootstrapError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BootstrapError(message)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def validate_bootstrap_spec(spec: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(spec, dict), "bootstrap spec must be an object")
    _require(spec.get("schema_version") == "1.0", "bootstrap schema_version must be 1.0")
    instance_id = _clean(spec.get("instance_id")).lower()
    _require(bool(ID_RE.fullmatch(instance_id)), "invalid instance_id")
    environment = _clean(spec.get("environment") or "test").lower()
    _require(environment in ALLOWED_ENVIRONMENTS, "invalid environment")

    publication = spec.get("publication")
    _require(isinstance(publication, dict), "publication must be an object")
    name = _clean(publication.get("name"))
    short_name = _clean(publication.get("short_name") or name)
    domain = _clean(publication.get("canonical_domain")).lower()
    _require(bool(name), "publication.name is required")
    _require(bool(DOMAIN_RE.fullmatch(domain)), "publication.canonical_domain is invalid")
    story_prefix = _clean(publication.get("story_path_prefix") or "/stiri")
    category_prefix = _clean(publication.get("category_path_prefix") or "/categorie")
    _require(story_prefix.startswith("/") and ".." not in story_prefix, "invalid story path prefix")
    _require(category_prefix.startswith("/") and ".." not in category_prefix, "invalid category path prefix")

    locale = _clean(spec.get("locale"))
    timezone = _clean(spec.get("timezone"))
    _require(bool(locale), "locale is required")
    _require(bool(timezone), "timezone is required")

    geography = spec.get("geography")
    _require(isinstance(geography, dict), "geography must be an object")
    country_code = _clean(geography.get("country_code")).upper()
    scope = geography.get("scope")
    _require(len(country_code) == 2 and country_code.isalpha(), "geography.country_code must be ISO alpha-2")
    _require(isinstance(scope, dict), "geography.scope must be an object")
    scope_type = _clean(scope.get("type")).lower()
    scope_name = _clean(scope.get("name"))
    _require(scope_type in {"county", "municipality", "city", "town", "commune", "region"}, "invalid geography scope type")
    _require(bool(scope_name), "geography.scope.name is required")
    settlements = geography.get("seed_settlements") or []
    _require(isinstance(settlements, list) and all(_clean(x) for x in settlements), "seed_settlements must be strings")

    brand = spec.get("brand") or {}
    _require(isinstance(brand, dict), "brand must be an object")
    brand_name = _clean(brand.get("name") or name)
    brand_short = _clean(brand.get("short_name") or short_name)
    _require(bool(brand_name) and bool(brand_short), "brand name is required")

    runtime = spec.get("runtime")
    _require(isinstance(runtime, dict), "runtime must be an object")
    backend_kind = _clean(runtime.get("backend_kind")).lower()
    connection_secret_ref = _clean(runtime.get("connection_secret_ref"))
    newsroom_secret_ref = _clean(runtime.get("newsroom_secret_ref"))
    _require(backend_kind in ALLOWED_BACKENDS, "invalid runtime backend_kind")
    _require(len(connection_secret_ref) >= 3 and "://" not in connection_secret_ref, "invalid connection_secret_ref")
    _require(len(newsroom_secret_ref) >= 3 and "://" not in newsroom_secret_ref, "invalid newsroom_secret_ref")
    public_base_url = _clean(runtime.get("public_base_url") or f"https://{domain}")
    _require(public_base_url.startswith("https://"), "public_base_url must use https")

    sources = spec.get("source_candidates") or []
    _require(isinstance(sources, list), "source_candidates must be an array")
    normalized_sources = []
    for raw in sources:
        _require(isinstance(raw, dict), "source candidate must be an object")
        sid = _clean(raw.get("source_id")).lower()
        adapter = _clean(raw.get("adapter")).upper()
        url = _clean(raw.get("url"))
        _require(bool(ID_RE.fullmatch(sid)), "invalid source candidate id")
        _require(adapter in SUPPORTED_ADAPTERS, "unsupported source candidate adapter")
        _require(url.startswith("https://") or url.startswith("http://"), "source candidate URL must be HTTP(S)")
        _require(_clean(raw.get("role") or "DISCOVERY").upper() == "DISCOVERY",
                 "bootstrap source candidates cannot assert PRIMARY authority")
        normalized_sources.append({
            "source_id": sid,
            "adapter": adapter,
            "role": "DISCOVERY",
            "url": url,
            "enabled": bool(raw.get("enabled", False)),
            "max_items": int(raw.get("max_items", 50)),
            "config": raw.get("config") if isinstance(raw.get("config"), dict) else {},
        })

    return {
        "schema_version": "1.0",
        "instance_id": instance_id,
        "environment": environment,
        "publication": {
            "name": name,
            "short_name": short_name,
            "canonical_domain": domain,
            "story_path_prefix": story_prefix,
            "category_path_prefix": category_prefix,
        },
        "locale": locale,
        "timezone": timezone,
        "geography": {
            "country_code": country_code,
            "scope": {"type": scope_type, "name": scope_name},
            "aliases": [_clean(x) for x in geography.get("aliases", []) if _clean(x)],
            "seed_settlements": [_clean(x) for x in settlements],
        },
        "brand": {
            "name": brand_name,
            "short_name": brand_short,
            "slogan": _clean(brand.get("slogan")),
        },
        "runtime": {
            "backend_kind": backend_kind,
            "connection_secret_ref": connection_secret_ref,
            "newsroom_secret_ref": newsroom_secret_ref,
            "public_base_url": public_base_url,
        },
        "source_candidates": normalized_sources,
    }


def build_instance_bundle(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    spec = validate_bootstrap_spec(spec)
    iid = spec["instance_id"]
    base = f"local-news-os/vnext/instances/{iid}/packs"
    pub = spec["publication"]
    geo = spec["geography"]
    runtime = spec["runtime"]
    instance = {
        "schema_version": "2.0",
        "instance_id": iid,
        "environment": spec["environment"],
        "publication": {"name": pub["name"], "canonical_domain": pub["canonical_domain"]},
        "locale": spec["locale"],
        "timezone": spec["timezone"],
        "runtime": {
            "owner": "site_application",
            "state_backend": {
                "kind": runtime["backend_kind"],
                "connection_secret_ref": runtime["connection_secret_ref"],
            },
            "repository_runtime_state_enabled": False,
            "public_base_url": runtime["public_base_url"],
            "newsroom": {
                "path": "/newsroom",
                "private": True,
                "auth_secret_ref": runtime["newsroom_secret_ref"],
            },
        },
        "packs": {name: f"{base}/{name}.json" for name in REQUIRED_PACKS},
        "policies": dict(REQUIRED_POLICIES),
    }
    packs = {
        "publication": {
            "schema_version": "2.0", "pack_type": "publication", "instance_id": iid,
            "name": pub["name"], "short_name": pub["short_name"],
            "canonical_domain": pub["canonical_domain"],
            "publication_model": "continuous_story_first",
            "public_runtime": {
                "story_path_prefix": pub["story_path_prefix"],
                "category_path_prefix": pub["category_path_prefix"],
                "homepage_limit": 12, "feed_limit": 25, "sitemap_limit": 1000,
            },
        },
        "geography": {
            "schema_version": "2.0", "pack_type": "geography", "instance_id": iid,
            "country_code": geo["country_code"], "scope": geo["scope"],
            "aliases": geo["aliases"], "seed_settlements": geo["seed_settlements"],
        },
        "brand": {
            "schema_version": "2.0", "pack_type": "brand", "instance_id": iid,
            **spec["brand"],
        },
        "sources": {
            "schema_version": "2.0", "pack_type": "sources", "instance_id": iid,
            "migration": {"status": "NONE"}, "sources": spec["source_candidates"],
        },
        "editorial": {
            "schema_version": "2.0", "pack_type": "editorial", "instance_id": iid,
            "auto_publish_classes": ["straight_news", "service_news"],
            "human_review_classes": ["reputational_claim", "investigation", "legal_ambiguity"],
            "rules": {
                "verified_facts_only": True,
                "title_only_publishable": False,
                "one_held_story_blocks_publication": False,
            },
            "newsworthiness": {
                "weights": dict(DEFAULT_WEIGHTS),
                "routing_thresholds": {"BUILD_PRIORITY": 75, "BUILD": 50, "MONITOR": 25},
            },
            "story_engine": {
                "default_section": "LOCAL",
                "max_headline_chars": 110,
                "max_dek_chars": 200,
                "section_by_claim_kind": {
                    "MONEY": "ECONOMY", "DATE": "LOCAL", "NUMBER": "LOCAL",
                    "PERCENT": "LOCAL", "HEADLINE_ASSERTION": "LOCAL",
                },
                "follow_up_label": "Ce urmărim",
            },
            "editorial_qa": {
                "default_editorial_class": "straight_news",
                "minimum_body_blocks": 2,
                "minimum_primary_sources": 1,
                "duplicate_headline_similarity_threshold": 0.9,
                "max_source_future_skew_hours": 4,
                "risk_term_classes": [
                    {"editorial_class": "reputational_claim", "terms": ["accused", "alleged", "fraud", "corruption"]},
                    {"editorial_class": "investigation", "terms": ["investigation", "raid", "prosecutor"]},
                    {"editorial_class": "legal_ambiguity", "terms": ["lawsuit", "court", "criminal case", "civil case"]},
                ],
            },
        },
        "channels": {
            "schema_version": "2.0", "pack_type": "channels", "instance_id": iid,
            "channels": [],
        },
        "entities": {
            "schema_version": "2.0", "pack_type": "entities", "instance_id": iid,
            "migration": {"status": "NONE"}, "seeds": [],
        },
        "photos": {
            "schema_version": "2.0", "pack_type": "photos", "instance_id": iid,
            "migration": {"status": "NONE"},
            "resolver_policy": {
                "allowed_usage_scopes": [
                    "ARCHIVE", "PROFILE", "SITE_CARD", "SITE_HERO",
                    "SOCIAL_FACEBOOK", "SOCIAL_INSTAGRAM",
                ],
                "allowed_rights_bases": [
                    "CC0", "CC_BY", "CC_BY_SA", "DOCUMENT_DERIVATIVE",
                    "EDITORIAL_CARD", "EXPLICIT_LICENSE", "OFFICIAL_PRESS_USE",
                    "PUBLIC_DOMAIN", "USER_OWNED",
                ],
                "specificity_order": [
                    "EVENT_DIRECT", "SUBJECT_DIRECT", "PLACE_DIRECT",
                    "CONTEXT_CURRENT", "CONTEXT_ARCHIVE", "DOCUMENT_VISUAL",
                ],
                "fallback": "EDITORIAL_CARD",
            },
            "assets": [],
        },
    }
    validate_instance(instance)
    validate_source_pack(packs["sources"], iid)
    validate_channels_pack(packs["channels"], instance_id=iid)
    return {"instance": instance, **packs}


def write_bundle(bundle: dict[str, dict[str, Any]], *, root: Path) -> Path:
    iid = bundle["instance"]["instance_id"]
    target = root / "local-news-os" / "vnext" / "instances" / iid
    _require(not target.exists(), f"target instance already exists: {target}")
    packs_dir = target / "packs"
    packs_dir.mkdir(parents=True)
    (target / "instance.json").write_text(
        json.dumps(bundle["instance"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name in REQUIRED_PACKS:
        (packs_dir / f"{name}.json").write_text(
            json.dumps(bundle[name], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return target


def initialize_runtime(bundle: dict[str, dict[str, Any]], *, db_path: Path, engine_version: str) -> dict[str, Any]:
    cfg = bundle["instance"]
    manifest = build_release_manifest(cfg)
    conn = connect(db_path)
    try:
        initialize(conn)
        register_instance(conn, manifest, engine_version=engine_version)
        release_state = initialize_release_state(
            conn, instance_id=cfg["instance_id"], current_engine_version=engine_version
        )
        row = conn.execute(
            "SELECT runtime_owner,engine_version FROM publication_instances WHERE instance_id=?",
            (cfg["instance_id"],),
        ).fetchone()
        _require(row is not None and row["runtime_owner"] == "site_application",
                 "runtime bootstrap did not preserve SITE_OWNS_RUNTIME")
        return {
            "instance_id": cfg["instance_id"],
            "runtime_owner": row["runtime_owner"],
            "engine_version": row["engine_version"],
            "release_current_engine_version": release_state["current_engine_version"],
        }
    finally:
        conn.close()


def self_test() -> None:
    spec = {
        "schema_version": "1.0",
        "instance_id": "neutral-county",
        "environment": "test",
        "publication": {
            "name": "NEUTRAL CLAR",
            "short_name": "Neutral",
            "canonical_domain": "neutral.invalid",
        },
        "locale": "en-US",
        "timezone": "UTC",
        "geography": {
            "country_code": "RO",
            "scope": {"type": "county", "name": "Neutral County"},
            "seed_settlements": ["Alpha City", "Beta Town"],
        },
        "brand": {"name": "NEUTRAL CLAR", "short_name": "Neutral"},
        "runtime": {
            "backend_kind": "sqlite",
            "connection_secret_ref": "NEUTRAL_DB",
            "newsroom_secret_ref": "NEUTRAL_NEWSROOM_TOKEN",
        },
        "source_candidates": [{
            "source_id": "candidate-feed",
            "adapter": "RSS_ATOM",
            "url": "https://example.test/feed",
            "enabled": False,
        }],
    }
    bundle = build_instance_bundle(spec)
    assert set(bundle) == {"instance", *REQUIRED_PACKS}
    assert bundle["instance"]["runtime"]["owner"] == "site_application"
    assert bundle["instance"]["runtime"]["repository_runtime_state_enabled"] is False
    assert bundle["sources"]["sources"][0]["role"] == "DISCOVERY"
    assert bundle["sources"]["sources"][0]["enabled"] is False
    assert bundle["channels"]["channels"] == []
    assert bundle["entities"]["seeds"] == []
    assert bundle["photos"]["assets"] == []
    neutral_text = json.dumps(bundle, ensure_ascii=False).lower()
    assert "repository_runtime_state_enabled" in neutral_text
    assert "neutral-county" in neutral_text
    assert "neutral.invalid" in neutral_text

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        target = write_bundle(bundle, root=root)
        assert (target / "instance.json").is_file()
        assert len(list((target / "packs").glob("*.json"))) == len(REQUIRED_PACKS)
        runtime = initialize_runtime(
            bundle, db_path=root / "runtime.sqlite3", engine_version="vnext-bootstrap-test"
        )
        assert runtime["runtime_owner"] == "site_application"
        assert runtime["release_current_engine_version"] == "vnext-bootstrap-test"

    bad = json.loads(json.dumps(spec))
    bad["source_candidates"][0]["role"] = "PRIMARY"
    try:
        build_instance_bundle(bad)
    except BootstrapError:
        pass
    else:
        raise AssertionError("bootstrap accepted asserted primary authority")
    print("LOCAL_NEWS_OS_VNEXT_P17_BOOTSTRAP_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--spec")
    parser.add_argument("--output-root")
    parser.add_argument("--db")
    parser.add_argument("--engine-version", default="vnext-dev")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.spec or not args.output_root:
        parser.error("--spec and --output-root are required")
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    bundle = build_instance_bundle(spec)
    target = write_bundle(bundle, root=Path(args.output_root))
    result = {"instance_path": str(target), "instance_id": bundle["instance"]["instance_id"]}
    if args.db:
        result["runtime"] = initialize_runtime(
            bundle, db_path=Path(args.db), engine_version=args.engine_version
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
