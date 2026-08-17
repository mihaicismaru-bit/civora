#!/usr/bin/env python3
"""INSTANCE_BOOTSTRAP_V1 for LOCAL NEWS OS.

Bootstraps one configured publication instance into an isolated, reversible,
network-free runtime namespace. This tool never publishes, deploys, spends,
or materializes credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import unicodedata
from pathlib import Path

from build_instance_manifest import build as build_manifest, load as load_json
from resolve_source_pack import resolve as resolve_source_pack
from validate_instance_config import validate_one

ROOT = Path(__file__).resolve().parents[2]
INSTANCES_ROOT = ROOT / "local-news-os" / "instances"
CONTRACT = "INSTANCE_BOOTSTRAP_V1"
BOOTSTRAP_FILES = (
    "bootstrap_manifest.json",
    "project_state.json",
    "health.json",
    "backlog.json",
    "site_config.json",
    "social_config.json",
)


def stable_hash(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_instance(instance_id: str) -> tuple[Path, dict]:
    path = INSTANCES_ROOT / instance_id / "instance.json"
    if not path.is_file():
        raise ValueError(f"unknown instance: {instance_id}")
    cfg = load_json(path)
    errors = validate_one(path, cfg)
    if errors:
        raise ValueError("; ".join(errors))
    if cfg.get("instance_id") != instance_id:
        raise ValueError("instance id mismatch")
    return path, cfg


def workspace_for(cfg: dict, override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    raw = str(cfg["runtime"]["state_root"])
    candidate = (ROOT / raw).resolve()
    candidate.relative_to(ROOT.resolve())
    return candidate / "bootstrap_v1"


def pack_hashes(cfg: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, raw in sorted(cfg["packs"].items()):
        path = (ROOT / str(raw)).resolve()
        path.relative_to(ROOT.resolve())
        if not path.is_file():
            raise ValueError(f"missing pack {key}: {raw}")
        result[key] = file_hash(path)
    return result


def identity(cfg: dict, manifest: dict, sources: dict) -> dict:
    base = {
        "instance_id": cfg["instance_id"],
        "canonical_domain": cfg["canonical_domain"],
        "environment": cfg["environment"],
        "state_root": cfg["runtime"]["state_root"],
        "output_root": cfg["runtime"]["output_root"],
        "config_sha256": manifest["config_sha256"],
        "source_pack_sha256": sources["resolved_sha256"],
        "pack_file_sha256": pack_hashes(cfg),
    }
    return {**base, "identity_sha256": stable_hash(base)}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def normalized_tokens(value: object) -> set[str]:
    raw = str(value or "").strip().lower()
    if not raw:
        return set()
    ascii_form = "".join(
        ch for ch in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(ch)
    )
    return {token for token in (raw, ascii_form) if len(token) >= 5}


def production_identity_tokens() -> set[str]:
    tokens: set[str] = set()
    for path in sorted(INSTANCES_ROOT.glob("*/instance.json")):
        cfg = load_json(path)
        if cfg.get("environment") != "production":
            continue
        tokens.update(normalized_tokens(cfg.get("instance_id")))
        tokens.update(normalized_tokens(cfg.get("canonical_domain")))
        brand = cfg.get("brand") or {}
        for key in ("name", "short_name", "slogan"):
            tokens.update(normalized_tokens(brand.get(key)))
        geography = cfg.get("geography") or {}
        for key in ("primary_name", "county"):
            tokens.update(normalized_tokens(geography.get(key)))
        for key in ("settlements", "aliases"):
            for item in geography.get(key) or []:
                tokens.update(normalized_tokens(item))
    return tokens


def initial_artifacts(
    cfg: dict, manifest: dict, sources: dict, ident: dict
) -> dict[str, dict]:
    iid = str(cfg["instance_id"])
    namespace = f"instance:{iid}"
    return {
        "bootstrap_manifest.json": {
            "schema_version": "1.0",
            "contract": CONTRACT,
            "instance_id": iid,
            "persistence_namespace": namespace,
            "lifecycle_state": "BOOTSTRAPPED",
            "transition_seq": 0,
            "resume_count": 0,
            "identity": ident,
            "manifest": manifest,
            "source_contract": {
                "contract": sources["contract"],
                "source_count": sources["source_count"],
                "resolved_sha256": sources["resolved_sha256"],
            },
            "external_mutations_enabled": False,
            "network_required": False,
            "credentials_materialized": False,
        },
        "project_state.json": {
            "schema_version": "1.0",
            "instance_id": iid,
            "persistence_namespace": namespace,
            "state": "BOOTSTRAPPED",
            "transition_seq": 0,
            "resume_count": 0,
            "last_known_good_state": "BOOTSTRAPPED",
            "identity_sha256": ident["identity_sha256"],
        },
        "health.json": {
            "schema_version": "1.0",
            "instance_id": iid,
            "persistence_namespace": namespace,
            "health": "BOOTSTRAP_READY",
            "external_state": "UNCONFIRMED",
            "network_checks_run": 0,
            "identity_sha256": ident["identity_sha256"],
        },
        "backlog.json": {
            "schema_version": "1.0",
            "instance_id": iid,
            "persistence_namespace": namespace,
            "items": [
                {"id": "bootstrap-validate-source-pack", "state": "DONE"},
                {"id": "bootstrap-runtime-dry-run", "state": "TODO"},
                {"id": "bootstrap-external-readback", "state": "BLOCKED_EXTERNAL"},
            ],
        },
        "site_config.json": {
            "schema_version": "1.0",
            "instance_id": iid,
            "canonical_domain": cfg["canonical_domain"],
            "brand_name": cfg["brand"]["name"],
            "runtime": manifest["runtime"],
            "continuous_story_first": True,
            "external_publish_enabled": False,
        },
        "social_config.json": {
            "schema_version": "1.0",
            "instance_id": iid,
            "channels": list(cfg["social_channels"]),
            "external_publish_enabled": False,
            "credentials_materialized": False,
            "fail_closed": True,
        },
    }


def verify_workspace(workspace: Path, expected_identity: str | None = None) -> dict:
    missing = [name for name in BOOTSTRAP_FILES if not (workspace / name).is_file()]
    if missing:
        raise ValueError(f"incomplete bootstrap workspace: {', '.join(missing)}")
    manifest = read_json(workspace / "bootstrap_manifest.json")
    project = read_json(workspace / "project_state.json")
    if manifest.get("contract") != CONTRACT:
        raise ValueError("bootstrap contract mismatch")
    identity_hash = str((manifest.get("identity") or {}).get("identity_sha256") or "")
    if not identity_hash or project.get("identity_sha256") != identity_hash:
        raise ValueError("bootstrap identity mismatch")
    if expected_identity and identity_hash != expected_identity:
        raise ValueError("cold-resume identity drift")
    if manifest.get("instance_id") != project.get("instance_id"):
        raise ValueError("workspace cross-instance contamination")
    return {"manifest": manifest, "project": project, "identity_sha256": identity_hash}


def bootstrap(instance_id: str, override: str | None = None) -> dict:
    _, cfg = load_instance(instance_id)
    manifest = build_manifest(cfg)
    sources = resolve_source_pack(instance_id)
    ident = identity(cfg, manifest, sources)
    workspace = workspace_for(cfg, override)
    if workspace.exists():
        try:
            current = verify_workspace(workspace, ident["identity_sha256"])
        except Exception as exc:
            raise ValueError(f"existing bootstrap workspace is not reusable: {exc}") from exc
        return {
            "status": "PASS",
            "action": "bootstrap",
            "result": "IDEMPOTENT_REUSE",
            "instance_id": instance_id,
            "workspace": str(workspace),
            "lifecycle_state": current["project"]["state"],
            "identity_sha256": ident["identity_sha256"],
        }

    workspace.mkdir(parents=True, exist_ok=False)
    for name, payload in initial_artifacts(cfg, manifest, sources, ident).items():
        write_json(workspace / name, payload)
    verify_workspace(workspace, ident["identity_sha256"])
    return {
        "status": "PASS",
        "action": "bootstrap",
        "result": "CREATED",
        "instance_id": instance_id,
        "workspace": str(workspace),
        "lifecycle_state": "BOOTSTRAPPED",
        "identity_sha256": ident["identity_sha256"],
    }


def transition(instance_id: str, action: str, override: str | None = None) -> dict:
    _, cfg = load_instance(instance_id)
    manifest = build_manifest(cfg)
    sources = resolve_source_pack(instance_id)
    ident = identity(cfg, manifest, sources)
    workspace = workspace_for(cfg, override)
    current = verify_workspace(workspace, ident["identity_sha256"])
    bootstrap_doc = current["manifest"]
    project = current["project"]
    old = str(project["state"])

    allowed = {
        "start": {"BOOTSTRAPPED", "STOPPED"},
        "stop": {"RUNNING"},
        "resume": {"STOPPED"},
    }
    if old not in allowed[action]:
        raise ValueError(f"cannot {action} from {old}")

    new = "RUNNING" if action in {"start", "resume"} else "STOPPED"
    seq = int(project.get("transition_seq", 0)) + 1
    resume_count = int(project.get("resume_count", 0)) + (1 if action == "resume" else 0)
    project.update(
        state=new,
        transition_seq=seq,
        resume_count=resume_count,
        last_known_good_state=new,
    )
    bootstrap_doc.update(
        lifecycle_state=new,
        transition_seq=seq,
        resume_count=resume_count,
    )
    write_json(workspace / "project_state.json", project)
    write_json(workspace / "bootstrap_manifest.json", bootstrap_doc)
    health = read_json(workspace / "health.json")
    health["health"] = "RUNNING_LOCAL" if new == "RUNNING" else "STOPPED_CLEAN"
    write_json(workspace / "health.json", health)
    verify_workspace(workspace, ident["identity_sha256"])
    return {
        "status": "PASS",
        "action": action,
        "instance_id": instance_id,
        "workspace": str(workspace),
        "from": old,
        "to": new,
        "transition_seq": seq,
        "resume_count": resume_count,
        "identity_sha256": ident["identity_sha256"],
    }


def self_test() -> dict:
    instance_id = "test-local"
    cfg_path, cfg = load_instance(instance_id)
    tracked = [cfg_path] + [(ROOT / str(v)).resolve() for v in cfg["packs"].values()]
    before = {str(p): file_hash(p) for p in tracked}
    with tempfile.TemporaryDirectory(prefix="civora-instance-bootstrap-") as td:
        workspace = str(Path(td) / "test-local")
        first = bootstrap(instance_id, workspace)
        second = bootstrap(instance_id, workspace)
        started = transition(instance_id, "start", workspace)
        stopped = transition(instance_id, "stop", workspace)
        # Cold resume: all state is re-read from disk and identity is recomputed.
        resumed = transition(instance_id, "resume", workspace)
        snapshot = verify_workspace(Path(workspace), resumed["identity_sha256"])
        serialized = json.dumps(snapshot, ensure_ascii=False).lower()
        ascii_serialized = "".join(
            ch
            for ch in unicodedata.normalize("NFKD", serialized)
            if not unicodedata.combining(ch)
        )
        for forbidden in production_identity_tokens():
            if forbidden in serialized or forbidden in ascii_serialized:
                raise AssertionError("test instance contains production identity")
        if first["result"] != "CREATED" or second["result"] != "IDEMPOTENT_REUSE":
            raise AssertionError("bootstrap idempotency failed")
        if (started["to"], stopped["to"], resumed["to"]) != (
            "RUNNING",
            "STOPPED",
            "RUNNING",
        ):
            raise AssertionError("lifecycle transition failed")
        if resumed["resume_count"] != 1:
            raise AssertionError("cold resume count failed")
    after = {str(p): file_hash(p) for p in tracked}
    if before != after:
        raise AssertionError("bootstrap mutated instance config or packs")
    return {
        "status": "PASS",
        "contract": CONTRACT,
        "instance_id": instance_id,
        "idempotent_bootstrap": True,
        "lifecycle": ["BOOTSTRAPPED", "RUNNING", "STOPPED", "RUNNING"],
        "cold_resume": True,
        "cross_instance_contamination": False,
        "external_mutations": 0,
        "network_calls": 0,
        "source_files_unchanged": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("instance", nargs="?")
    parser.add_argument(
        "action", nargs="?", choices=("bootstrap", "start", "stop", "resume", "status")
    )
    parser.add_argument("--workspace")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    try:
        if args.self_test:
            result = self_test()
        else:
            if not args.instance or not args.action:
                parser.error("instance and action are required unless --self-test is used")
            if args.action == "bootstrap":
                result = bootstrap(args.instance, args.workspace)
            elif args.action == "status":
                _, cfg = load_instance(args.instance)
                manifest = build_manifest(cfg)
                sources = resolve_source_pack(args.instance)
                ident = identity(cfg, manifest, sources)
                workspace = workspace_for(cfg, args.workspace)
                current = verify_workspace(workspace, ident["identity_sha256"])
                result = {
                    "status": "PASS",
                    "action": "status",
                    "instance_id": args.instance,
                    "workspace": str(workspace),
                    "lifecycle_state": current["project"]["state"],
                    "transition_seq": current["project"]["transition_seq"],
                    "resume_count": current["project"]["resume_count"],
                    "identity_sha256": current["identity_sha256"],
                }
            else:
                result = transition(args.instance, args.action, args.workspace)
    except Exception as exc:
        result = {"status": "FAIL", "contract": CONTRACT, "error": str(exc)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
