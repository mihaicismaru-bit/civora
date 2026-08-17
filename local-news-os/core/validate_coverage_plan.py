#!/usr/bin/env python3
"""Validate a LOCAL NEWS OS instance coverage plan against the generic taxonomy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be an object")
    return value


def repo_file(raw: str) -> Path:
    if not raw or Path(raw).is_absolute():
        raise ValueError(f"invalid repository-relative path: {raw!r}")
    candidate = (ROOT / raw).resolve()
    candidate.relative_to(ROOT.resolve())
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def validate_signal_registry(path: Path) -> list[str]:
    errors: list[str] = []
    data = load(path)
    if data.get("publication_authority") not in (None, "NONE"):
        errors.append(f"{path}: signal registry must have publication_authority NONE")
    defaults = data.get("defaults") or {}
    if defaults and defaults.get("auto_publication") is not False:
        errors.append(f"{path}: signal registry defaults.auto_publication must be false")
    if defaults and defaults.get("public_projection") is not False:
        errors.append(f"{path}: signal registry defaults.public_projection must be false")
    return errors


def validate(instance_id: str) -> dict:
    instance_path = ROOT / "local-news-os" / "instances" / instance_id / "instance.json"
    instance = load(instance_path)
    if instance.get("instance_id") != instance_id:
        raise ValueError("instance id mismatch")

    source_pack_path = repo_file(str(instance.get("packs", {}).get("source_pack", "")))
    source_pack = load(source_pack_path)
    coverage_raw = str(source_pack.get("coverage_plan") or "").strip()
    if not coverage_raw:
        return {
            "status": "SKIP",
            "instance_id": instance_id,
            "reason": "coverage_plan_not_configured",
            "errors": [],
        }

    coverage_path = repo_file(coverage_raw)
    coverage = load(coverage_path)
    errors: list[str] = []
    if coverage.get("contract") != "LOCAL_NEWS_OS_INSTANCE_COVERAGE_PLAN_V1":
        errors.append(f"{coverage_path}: invalid coverage contract")
    if coverage.get("instance_id") != instance_id:
        errors.append(f"{coverage_path}: instance_id mismatch")

    taxonomy_path = repo_file(str(coverage.get("taxonomy") or ""))
    taxonomy = load(taxonomy_path)
    if taxonomy.get("contract") != "LOCAL_NEWS_OS_EDITORIAL_COVERAGE_TAXONOMY_V1":
        errors.append(f"{taxonomy_path}: invalid taxonomy contract")
    if taxonomy.get("scope") != "CORE_GENERIC":
        errors.append(f"{taxonomy_path}: taxonomy scope must be CORE_GENERIC")

    topics = taxonomy.get("topics") or []
    topic_ids = [str(row.get("id")) for row in topics if isinstance(row, dict) and row.get("id")]
    if len(topic_ids) != len(set(topic_ids)):
        errors.append(f"{taxonomy_path}: duplicate topic ids")
    active_topics = coverage.get("active_topics") or []
    unknown = sorted(set(map(str, active_topics)) - set(topic_ids))
    if unknown:
        errors.append(f"{coverage_path}: unknown active topics: {', '.join(unknown)}")

    taxonomy_layers = {
        str(row.get("id")): str(row.get("authority"))
        for row in taxonomy.get("source_layers") or []
        if isinstance(row, dict) and row.get("id")
    }
    coverage_layers = coverage.get("source_layers") or {}
    if not isinstance(coverage_layers, dict):
        errors.append(f"{coverage_path}: source_layers must be an object")
        coverage_layers = {}

    registry_count = 0
    for layer_id, layer in coverage_layers.items():
        if layer_id not in taxonomy_layers:
            errors.append(f"{coverage_path}: unknown source layer {layer_id}")
            continue
        if not isinstance(layer, dict):
            errors.append(f"{coverage_path}: source layer {layer_id} must be object")
            continue
        if str(layer.get("authority")) != taxonomy_layers[layer_id]:
            errors.append(f"{coverage_path}: authority mismatch for {layer_id}")
        target = layer.get("minimum_target")
        if not isinstance(target, int) or target <= 0:
            errors.append(f"{coverage_path}: {layer_id}.minimum_target must be positive integer")
        paths = layer.get("registry_paths") or []
        if not isinstance(paths, list) or not paths:
            errors.append(f"{coverage_path}: {layer_id}.registry_paths must be non-empty array")
            continue
        for raw in paths:
            try:
                path = repo_file(str(raw))
                registry_count += 1
                if layer_id == "SIGNAL_RADAR":
                    errors.extend(validate_signal_registry(path))
            except Exception as exc:
                errors.append(f"{coverage_path}: invalid registry path {raw!r}: {exc}")

    required_layers = set(taxonomy_layers)
    missing_layers = sorted(required_layers - set(coverage_layers))
    if missing_layers:
        errors.append(f"{coverage_path}: missing source layers: {', '.join(missing_layers)}")

    territorial = coverage.get("territorial_scope") or {}
    uat_target = territorial.get("uat_target")
    if uat_target is not None and (not isinstance(uat_target, int) or uat_target <= 0):
        errors.append(f"{coverage_path}: territorial_scope.uat_target must be positive integer")

    evidence_rules = coverage.get("evidence_rules") or {}
    for key in (
        "t2_t3_never_become_material_fact_without_higher_authority",
        "community_signal_never_fact",
        "durable_copy_absolute_dates_only",
    ):
        if evidence_rules.get(key) is not True:
            errors.append(f"{coverage_path}: evidence_rules.{key} must be true")

    return {
        "status": "PASS" if not errors else "FAIL",
        "instance_id": instance_id,
        "taxonomy_topics": len(topic_ids),
        "active_topics": len(active_topics),
        "source_layers": len(coverage_layers),
        "registry_paths": registry_count,
        "errors": errors,
    }


def self_test() -> int:
    report = validate("valcea")
    assert report["status"] == "PASS", report
    assert report["taxonomy_topics"] >= 20
    assert report["source_layers"] == 3
    print("LOCAL NEWS OS coverage plan self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("instance", nargs="?")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.instance:
        parser.error("instance id is required")
    report = validate(args.instance)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"PASS", "SKIP"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
