#!/usr/bin/env python3
"""Resolve any LOCAL NEWS OS SOURCE_PACK_V1 to one canonical source list.

Supports both native inline packs and reversible compatibility registries so the
pilot can migrate without duplicating or breaking its live source registry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be a JSON object")
    return value


def repo_file(raw: str) -> Path:
    if not raw or Path(raw).is_absolute():
        raise ValueError(f"invalid repository-relative path: {raw!r}")
    candidate = (ROOT / raw).resolve()
    candidate.relative_to(ROOT.resolve())
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalize_source(raw: dict, *, compatibility: bool) -> dict:
    if compatibility:
        source = {
            "id": raw.get("id"),
            "name": raw.get("publisher"),
            "category": raw.get("section"),
            "url": raw.get("url"),
            "source_tier": raw.get("tier"),
            "enabled": raw.get("enabled", True),
            "priority": raw.get("priority"),
            "path_hints": raw.get("path_hints", []),
            "generic_titles": raw.get("generic_titles", []),
        }
    else:
        source = {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "category": raw.get("category"),
            "url": raw.get("url"),
            "source_tier": raw.get("source_tier"),
            "enabled": raw.get("enabled", True),
            "priority": raw.get("priority"),
            "path_hints": raw.get("path_hints", []),
            "generic_titles": raw.get("generic_titles", []),
        }

    for key in ("id", "name", "category", "url", "source_tier"):
        if not str(source.get(key, "")).strip():
            raise ValueError(f"source missing {key}: {raw!r}")
    parsed = urllib.parse.urlparse(str(source["url"]))
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"source URL must be HTTPS: {source['url']}")
    if source["enabled"] is not True and source["enabled"] is not False:
        raise ValueError(f"source enabled must be boolean: {source['id']}")
    return source


def resolve(instance_id: str) -> dict:
    instance_path = ROOT / "local-news-os" / "instances" / instance_id / "instance.json"
    instance = load(instance_path)
    if instance.get("instance_id") != instance_id:
        raise ValueError("instance id mismatch")

    pack_path = repo_file(str(instance["packs"]["source_pack"]))
    pack = load(pack_path)
    if pack.get("instance_id") != instance_id:
        raise ValueError("source pack instance_id mismatch")

    mode = str(pack.get("mode") or ("inline" if isinstance(pack.get("sources"), list) else ""))
    compatibility = mode == "compatibility_registry"
    if compatibility:
        registry_path = repo_file(str(pack.get("registry_path", "")))
        registry = load(registry_path)
        raw_sources = registry.get("sources")
        source_origin = str(registry_path.relative_to(ROOT))
        upstream_policy = registry.get("policy", {})
    elif mode == "inline":
        raw_sources = pack.get("sources")
        source_origin = str(pack_path.relative_to(ROOT))
        upstream_policy = pack.get("policy", {})
    else:
        raise ValueError(f"unsupported source pack mode: {mode!r}")

    if not isinstance(raw_sources, list):
        raise ValueError("resolved source registry must contain a sources array")

    sources: list[dict] = []
    seen: set[str] = set()
    for raw in raw_sources:
        if not isinstance(raw, dict):
            raise ValueError("source records must be JSON objects")
        source = normalize_source(raw, compatibility=compatibility)
        source_id = str(source["id"])
        if source_id in seen:
            raise ValueError(f"duplicate source id: {source_id}")
        seen.add(source_id)
        sources.append(source)

    categories = sorted({str(s["category"]) for s in sources if s["enabled"]})
    resolved = {
        "schema_version": "1.0",
        "contract": "SOURCE_PACK_V1",
        "instance_id": instance_id,
        "mode": mode,
        "source_origin": source_origin,
        "source_count": len(sources),
        "enabled_source_count": sum(1 for s in sources if s["enabled"]),
        "categories": categories,
        "automatic_publication_scope": pack.get(
            "automatic_publication_scope",
            upstream_policy.get("automatic_publication_scope", "candidate_only"),
        ),
        "material_detail_autopublish": bool(
            pack.get("material_detail_autopublish", False)
        ),
        "sources": sources,
        "resolver": "local_news_os_source_pack_resolver_v1",
    }
    resolved["resolved_sha256"] = stable_hash(resolved)
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("instance", help="LOCAL NEWS OS instance id")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = resolve(args.instance)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
