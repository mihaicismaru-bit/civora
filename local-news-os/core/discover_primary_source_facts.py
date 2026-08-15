#!/usr/bin/env python3
"""Instance-aware primary-source discovery compatibility adapter.

This moves source selection and publication identity into LOCAL NEWS OS instance
configuration while preserving the proven VÂLCEA CLAR zero-LLM crawler during
migration. The legacy crawler remains a TEMPORARY_COMPATIBILITY_ADAPTER; source
resolution is already generic through SOURCE_PACK_V1.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
CORE = Path(__file__).resolve().parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from resolve_source_pack import resolve  # noqa: E402

LEGACY_CRAWLER = ROOT / "valcea-clar" / "scripts" / "discover_news_facts.py"
DEFAULT_POLICY = {
    "automatic_publication_scope": "title_date_source_only",
    "material_detail_autopublish": False,
    "candidate_max_age_hours": 72,
    "min_title_chars": 24,
    "max_candidates_per_source": 12,
}


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def repo_file(raw: str) -> Path:
    if not raw or Path(raw).is_absolute():
        raise ValueError(f"invalid repository-relative path: {raw!r}")
    path = (ROOT / raw).resolve()
    path.relative_to(ROOT.resolve())
    return path


def load_legacy_module():
    spec = importlib.util.spec_from_file_location("local_news_legacy_discovery", LEGACY_CRAWLER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load legacy discovery adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_policy(resolved: dict) -> dict:
    policy = dict(DEFAULT_POLICY)
    origin = repo_file(str(resolved.get("source_origin", "")))
    if origin.is_file():
        upstream = load_json(origin).get("policy")
        if isinstance(upstream, dict):
            policy.update(upstream)
    policy["automatic_publication_scope"] = resolved.get(
        "automatic_publication_scope", policy["automatic_publication_scope"]
    )
    policy["material_detail_autopublish"] = bool(
        resolved.get("material_detail_autopublish", False)
    )
    return policy


def to_legacy_registry(instance_id: str, resolved: dict) -> dict:
    sources = []
    for source in resolved.get("sources", []):
        sources.append({
            "id": source["id"],
            "publisher": source["name"],
            "url": source["url"],
            "tier": source["source_tier"],
            "section": source["category"],
            "priority": source.get("priority") if source.get("priority") is not None else 75,
            "path_hints": source.get("path_hints", []),
            "generic_titles": source.get("generic_titles", []),
            "enabled": source.get("enabled", True),
        })
    return {
        "schema_version": "compatibility-source-pack-v1",
        "instance_id": instance_id,
        "policy": source_policy(resolved),
        "sources": [source for source in sources if source["enabled"]],
    }


def brand_output(path: Path, instance_id: str, brand_name: str) -> None:
    payload = load_json(path)
    payload["instance_id"] = instance_id
    payload["source_contract"] = "SOURCE_PACK_V1"
    payload["migration_adapter"] = "local_news_os_primary_source_compat_v1"
    for fact in payload.get("facts", []):
        if not isinstance(fact, dict):
            continue
        dek = fact.get("dek")
        if isinstance(dek, str):
            fact["dek"] = dek.replace("VÂLCEA CLAR", brand_name)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tag_state(path: Path, instance_id: str) -> None:
    payload = load_json(path)
    payload["instance_id"] = instance_id
    payload["source_contract"] = "SOURCE_PACK_V1"
    payload["migration_adapter"] = "local_news_os_primary_source_compat_v1"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_only(instance_id: str) -> dict:
    instance = load_json(ROOT / "local-news-os" / "instances" / instance_id / "instance.json")
    resolved = resolve(instance_id)
    registry = to_legacy_registry(instance_id, resolved)
    return {
        "status": "PASS",
        "instance_id": instance_id,
        "brand": instance["brand"]["name"],
        "source_contract": resolved["contract"],
        "source_count": resolved["source_count"],
        "enabled_source_count": resolved["enabled_source_count"],
        "compatibility_source_count": len(registry["sources"]),
        "zero_paid_dependency": instance["policies"]["zero_paid_dependency"],
        "llm_required": instance["policies"]["llm_required"],
    }


def run(instance_id: str, output: Path, state: Path) -> int:
    instance_path = ROOT / "local-news-os" / "instances" / instance_id / "instance.json"
    instance = load_json(instance_path)
    if instance.get("instance_id") != instance_id:
        raise ValueError("instance id mismatch")
    resolved = resolve(instance_id)
    registry = to_legacy_registry(instance_id, resolved)

    output.parent.mkdir(parents=True, exist_ok=True)
    state.parent.mkdir(parents=True, exist_ok=True)

    legacy = load_legacy_module()
    timezone = ZoneInfo(str(instance["timezone"]))
    canonical_domain = str(instance["canonical_domain"])
    brand_name = str(instance["brand"]["name"])

    with tempfile.TemporaryDirectory(prefix=f"local-news-os-{instance_id}-") as tmp:
        registry_path = Path(tmp) / "news_sources.json"
        registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        legacy.REGISTRY = registry_path
        legacy.OUT = output
        legacy.STATE = state
        legacy.TZ = timezone
        legacy.UA = f"Mozilla/5.0 LOCAL-NEWS-OS/{instance_id} (+https://{canonical_domain}/)"
        original_argv = sys.argv[:]
        try:
            sys.argv = [str(LEGACY_CRAWLER)]
            result = int(legacy.main())
        finally:
            sys.argv = original_argv

    if result != 0:
        return result
    brand_output(output, instance_id, brand_name)
    tag_state(state, instance_id)
    return 0


def self_test() -> int:
    valcea = validate_only("valcea")
    test = validate_only("test-local")
    assert valcea["source_contract"] == "SOURCE_PACK_V1"
    assert test["source_contract"] == "SOURCE_PACK_V1"
    assert valcea["source_count"] >= 16
    assert test["source_count"] == 2
    assert valcea["zero_paid_dependency"] is True
    assert test["zero_paid_dependency"] is True
    assert valcea["llm_required"] is False
    assert test["llm_required"] is False
    legacy = load_legacy_module()
    assert legacy.self_test() == 0
    print("LOCAL NEWS OS instance-aware discovery adapter self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", default="valcea")
    parser.add_argument("--output")
    parser.add_argument("--state")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.validate_only:
        print(json.dumps(validate_only(args.instance), ensure_ascii=False, indent=2))
        return 0
    if not args.output or not args.state:
        parser.error("--output and --state are required for discovery runs")
    return run(args.instance, Path(args.output), Path(args.state))


if __name__ == "__main__":
    raise SystemExit(main())
