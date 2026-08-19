#!/usr/bin/env python3
"""LOCAL NEWS OS vNext tenant/instance contract.

The generic engine knows only configuration structure. Local publication names,
geographies, sources and accounts are instance data and must never be embedded
here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
VNEXT_ROOT = ROOT / "local-news-os" / "vnext"
REQUIRED_PACKS = (
    "publication",
    "geography",
    "brand",
    "sources",
    "editorial",
    "channels",
    "entities",
    "photos",
)
REQUIRED_POLICIES = {
    "verified_facts_only": True,
    "title_only_publishable": False,
    "held_story_blocks_publication": False,
    "development_gate_may_stop_validated_runtime": False,
}


class InstanceContractError(ValueError):
    pass


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InstanceContractError(message)


def validate_instance(cfg: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(cfg, dict), "instance must be an object")
    _require(cfg.get("schema_version") == "2.0", "schema_version must be 2.0")

    instance_id = cfg.get("instance_id")
    _require(isinstance(instance_id, str) and len(instance_id) >= 2, "invalid instance_id")
    _require(
        all(ch.islower() or ch.isdigit() or ch == "-" for ch in instance_id),
        "instance_id must contain only lowercase letters, digits and hyphens",
    )
    _require(instance_id[0].isalnum(), "instance_id must start with an alphanumeric character")

    _require(cfg.get("environment") in {"test", "staging", "production"}, "invalid environment")

    publication = cfg.get("publication")
    _require(isinstance(publication, dict), "publication must be an object")
    _require(bool(publication.get("name")), "publication.name is required")
    domain = publication.get("canonical_domain")
    _require(isinstance(domain, str) and "." in domain, "publication.canonical_domain is invalid")

    _require(isinstance(cfg.get("locale"), str) and cfg["locale"], "locale is required")
    _require(isinstance(cfg.get("timezone"), str) and cfg["timezone"], "timezone is required")

    runtime = cfg.get("runtime")
    _require(isinstance(runtime, dict), "runtime must be an object")
    _require(runtime.get("owner") == "site_application", "SITE_OWNS_RUNTIME violation: owner")
    _require(
        runtime.get("repository_runtime_state_enabled") is False,
        "SITE_OWNS_RUNTIME violation: repository runtime state must be disabled",
    )
    backend = runtime.get("state_backend")
    _require(isinstance(backend, dict), "runtime.state_backend must be an object")
    _require(
        backend.get("kind") in {"postgresql", "sqlite", "database"},
        "runtime.state_backend.kind must be database-backed",
    )
    secret_ref = backend.get("connection_secret_ref")
    _require(isinstance(secret_ref, str) and len(secret_ref) >= 3, "connection_secret_ref is required")
    _require("//" not in secret_ref and "://" not in secret_ref, "connection_secret_ref must not contain a credential URL")

    public_base_url = runtime.get("public_base_url")
    _require(
        isinstance(public_base_url, str) and public_base_url.startswith("https://"),
        "runtime.public_base_url must use https",
    )
    newsroom = runtime.get("newsroom")
    _require(isinstance(newsroom, dict), "runtime.newsroom must be an object")
    _require(newsroom.get("path") == "/newsroom", "runtime.newsroom.path must be /newsroom")
    _require(newsroom.get("private") is True, "runtime.newsroom must be private")

    forbidden_legacy_runtime_keys = {
        "state_root",
        "output_root",
        "current_edition",
        "live_feed",
        "repository_path",
        "git_state_path",
    }
    overlap = forbidden_legacy_runtime_keys.intersection(runtime)
    _require(not overlap, f"legacy repository-owned runtime keys forbidden: {sorted(overlap)}")

    packs = cfg.get("packs")
    _require(isinstance(packs, dict), "packs must be an object")
    missing_packs = [name for name in REQUIRED_PACKS if not packs.get(name)]
    _require(not missing_packs, f"missing instance packs: {missing_packs}")
    extra_packs = sorted(set(packs) - set(REQUIRED_PACKS))
    _require(not extra_packs, f"unknown instance packs: {extra_packs}")

    for name, rel in packs.items():
        _require(isinstance(rel, str) and rel, f"pack path must be a string: {name}")
        path = Path(rel)
        _require(not path.is_absolute(), f"pack path must be repository-relative: {name}")
        _require(".." not in path.parts, f"pack path must not traverse parents: {name}")

    policies = cfg.get("policies")
    _require(isinstance(policies, dict), "policies must be an object")
    for key, expected in REQUIRED_POLICIES.items():
        _require(policies.get(key) is expected, f"policy invariant failed: {key}")

    return cfg


def validate_pack_bindings(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate that every configured pack exists and belongs to this instance."""
    instance_id = cfg["instance_id"]
    loaded: dict[str, dict[str, Any]] = {}
    root_resolved = ROOT.resolve()
    for pack_type, rel in cfg["packs"].items():
        path = (ROOT / rel).resolve()
        _require(path == root_resolved or root_resolved in path.parents, f"pack escapes repository: {pack_type}")
        _require(path.is_file(), f"pack file missing: {pack_type}: {rel}")
        value = json.loads(path.read_text(encoding="utf-8"))
        _require(isinstance(value, dict), f"pack must be an object: {pack_type}")
        _require(value.get("schema_version") == "2.0", f"pack schema mismatch: {pack_type}")
        _require(value.get("pack_type") == pack_type, f"pack type mismatch: {pack_type}")
        _require(value.get("instance_id") == instance_id, f"pack instance mismatch: {pack_type}")
        loaded[pack_type] = value
    return loaded


def build_release_manifest(cfg: dict[str, Any]) -> dict[str, Any]:
    validate_instance(cfg)
    return {
        "schema_version": "2.0",
        "contract": "LOCAL_NEWS_OS_VNEXT_INSTANCE_RELEASE_MANIFEST_V1",
        "instance_id": cfg["instance_id"],
        "environment": cfg["environment"],
        "publication": cfg["publication"],
        "locale": cfg["locale"],
        "timezone": cfg["timezone"],
        "runtime": {
            "owner": "site_application",
            "state_backend_kind": cfg["runtime"]["state_backend"]["kind"],
            "public_base_url": cfg["runtime"]["public_base_url"],
            "newsroom": cfg["runtime"]["newsroom"],
            "repository_runtime_state_enabled": False,
        },
        "packs": dict(cfg["packs"]),
        "policies": dict(cfg["policies"]),
        "config_sha256": _stable_hash(cfg),
        "generator": "local_news_os_vnext_instance_model_v1",
    }


def load_instance(instance_id: str) -> dict[str, Any]:
    path = VNEXT_ROOT / "instances" / instance_id / "instance.json"
    if not path.is_file():
        raise InstanceContractError(f"unknown instance: {instance_id}")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    _require(cfg.get("instance_id") == instance_id, "instance directory/id mismatch")
    validate_instance(cfg)
    validate_pack_bindings(cfg)
    return cfg


def _fixture(instance_id: str, domain: str, secret_ref: str) -> dict[str, Any]:
    base = f"local-news-os/vnext/instances/{instance_id}/packs"
    return {
        "schema_version": "2.0",
        "instance_id": instance_id,
        "environment": "test",
        "publication": {"name": "Example Publication", "canonical_domain": domain},
        "locale": "en-US",
        "timezone": "UTC",
        "runtime": {
            "owner": "site_application",
            "state_backend": {"kind": "sqlite", "connection_secret_ref": secret_ref},
            "repository_runtime_state_enabled": False,
            "public_base_url": f"https://{domain}",
            "newsroom": {"path": "/newsroom", "private": True},
        },
        "packs": {name: f"{base}/{name}.json" for name in REQUIRED_PACKS},
        "policies": dict(REQUIRED_POLICIES),
    }


def self_test() -> None:
    first = _fixture("alpha-local", "alpha.invalid", "ALPHA_DB")
    second = _fixture("beta-local", "beta.invalid", "BETA_DB")
    first_manifest = build_release_manifest(first)
    second_manifest = build_release_manifest(second)
    assert first_manifest["config_sha256"] != second_manifest["config_sha256"]
    assert first_manifest["runtime"]["owner"] == "site_application"
    assert first_manifest["runtime"]["repository_runtime_state_enabled"] is False

    bad_runtime = json.loads(json.dumps(first))
    bad_runtime["runtime"]["owner"] = "repository"
    try:
        validate_instance(bad_runtime)
    except InstanceContractError:
        pass
    else:
        raise AssertionError("repository-owned runtime was accepted")

    bad_legacy = json.loads(json.dumps(first))
    bad_legacy["runtime"]["live_feed"] = "runtime/live-feed.json"
    try:
        validate_instance(bad_legacy)
    except InstanceContractError:
        pass
    else:
        raise AssertionError("legacy repository runtime path was accepted")

    bad_pack = json.loads(json.dumps(first))
    del bad_pack["packs"]["photos"]
    try:
        validate_instance(bad_pack)
    except InstanceContractError:
        pass
    else:
        raise AssertionError("missing instance pack was accepted")

    print("LOCAL_NEWS_OS_VNEXT_INSTANCE_MODEL_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("instance", nargs="?", help="instance id")
    parser.add_argument("--output", help="optional release manifest output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.instance:
        parser.error("instance is required unless --self-test is used")

    manifest = build_release_manifest(load_instance(args.instance))
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
