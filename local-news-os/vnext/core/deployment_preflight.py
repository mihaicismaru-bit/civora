#!/usr/bin/env python3
"""Fail-closed deployability checks for LOCAL NEWS OS vNext."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from database_backend import backend_name, translate_schema_for_postgres
from instance_model import load_instance
from production_app import deployment_readiness

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "local-news-os" / "vnext" / "runtime"
SCHEMA_FILES = (
    "schema.sql",
    "publication_schema.sql",
    "knowledge_schema.sql",
    "media_schema.sql",
    "distribution_schema.sql",
    "scheduler_schema.sql",
    "release_schema.sql",
)


class DeploymentPreflightError(RuntimeError):
    pass


def static_contract(instance_id: str) -> dict[str, object]:
    cfg = load_instance(instance_id)
    translated = {}
    for name in SCHEMA_FILES:
        path = RUNTIME / name
        if not path.is_file():
            raise DeploymentPreflightError(f"missing runtime schema: {name}")
        value = translate_schema_for_postgres(path.read_text(encoding="utf-8"))
        upper = value.upper()
        if any(token in upper for token in ("PRAGMA ", "AUTOINCREMENT", "RAISE(ABORT")):
            raise DeploymentPreflightError(f"SQLite-only syntax survived translation: {name}")
        translated[name] = len(value)
    state_backend = cfg["runtime"]["state_backend"]
    if cfg["environment"] == "production" and state_backend["kind"] != "postgresql":
        raise DeploymentPreflightError("production instance must declare PostgreSQL")
    return {
        "status": "STATIC_PASS",
        "instance_id": instance_id,
        "schema_files": translated,
        "state_backend_kind": state_backend["kind"],
        "database_secret_ref": state_backend["connection_secret_ref"],
        "repository_runtime_state_enabled": False,
        "integration_gate": "UNVERIFIED_UNTIL_REAL_DATABASE_BINDING",
    }


def real_binding(instance_id: str) -> dict[str, object]:
    cfg = load_instance(instance_id)
    secret_ref = cfg["runtime"]["state_backend"]["connection_secret_ref"]
    target = os.environ.get(secret_ref)
    if not target:
        raise DeploymentPreflightError(f"missing database binding: {secret_ref}")
    if cfg["runtime"]["state_backend"]["kind"] == "postgresql" and backend_name(target) != "postgresql":
        raise DeploymentPreflightError("bound runtime database is not PostgreSQL")
    engine_version = str(os.environ.get("LOCAL_NEWS_ENGINE_VERSION") or "").strip()
    newsroom_token = str(os.environ.get("LOCAL_NEWS_NEWSROOM_TOKEN") or "")
    if not engine_version:
        raise DeploymentPreflightError("LOCAL_NEWS_ENGINE_VERSION is required")
    if len(newsroom_token) < 32:
        raise DeploymentPreflightError("LOCAL_NEWS_NEWSROOM_TOKEN is missing or too short")
    return deployment_readiness(
        instance_id=instance_id,
        engine_version=engine_version,
        newsroom_token=newsroom_token,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", required=True)
    parser.add_argument("--static", action="store_true")
    args = parser.parse_args()
    payload = static_contract(args.instance) if args.static else real_binding(args.instance)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
