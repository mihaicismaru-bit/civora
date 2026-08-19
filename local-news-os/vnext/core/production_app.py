#!/usr/bin/env python3
"""Deployable composite site application for LOCAL NEWS OS vNext.

This is the production composition boundary: public publication routes, private
newsroom, scheduler health and release health share one durable site-owned
database. GitHub remains code/deployment only; no repository runtime state is
read or written here.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Iterable

from database_backend import backend_name, resolve_runtime_database_target
from distribution_engine import ensure_distribution_schema
from instance_model import build_release_manifest, load_instance, validate_pack_bindings
from knowledge_graph import ensure_knowledge_schema
from media_intelligence import ensure_media_schema
from release_control import ensure_release_schema, initialize_release_state
from release_runtime import ReleaseNewsroomApp
from runtime_store import connect, initialize, register_instance
from scheduler_engine import ensure_scheduler_schema
from scheduler_runtime import SchedulerNewsroomApp
from site_publication import PublicSiteApp, ensure_publication_schema
from site_runtime import SiteRuntimeApp

StartResponse = Callable[[str, list[tuple[str, str]]], Any]


class ProductionAppError(RuntimeError):
    pass


def _required_env(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise ProductionAppError(f"missing required environment variable: {name}")
    return value


def _ensure_all_schemas(conn) -> None:
    initialize(conn)
    ensure_publication_schema(conn)
    ensure_knowledge_schema(conn)
    ensure_media_schema(conn)
    ensure_distribution_schema(conn)
    ensure_scheduler_schema(conn)
    ensure_release_schema(conn)


def bootstrap_runtime(*, instance_id: str, engine_version: str, newsroom_token: str) -> dict[str, Any]:
    cfg = load_instance(instance_id)
    packs = validate_pack_bindings(cfg)
    if len(newsroom_token) < 32:
        raise ProductionAppError("LOCAL_NEWS_NEWSROOM_TOKEN must contain at least 32 characters")
    target = resolve_runtime_database_target(instance_cfg=cfg)
    expected_backend = str(cfg["runtime"]["state_backend"]["kind"])
    actual_backend = backend_name(target)
    if expected_backend == "postgresql" and actual_backend != "postgresql":
        raise ProductionAppError("configured production instance is not bound to PostgreSQL")

    conn = connect(target)
    try:
        _ensure_all_schemas(conn)
        register_instance(conn, build_release_manifest(cfg), engine_version=engine_version)
        initialize_release_state(conn, instance_id=instance_id, current_engine_version=engine_version)
        ping = conn.execute("SELECT 1 AS ok").fetchone()
        if ping is None or int(ping["ok"]) != 1:
            raise ProductionAppError("runtime database ping failed")
    finally:
        conn.close()
    return {
        "cfg": cfg,
        "packs": packs,
        "database_target": target,
        "database_backend": actual_backend,
    }


def deployment_readiness(*, instance_id: str, engine_version: str, newsroom_token: str) -> dict[str, Any]:
    boot = bootstrap_runtime(
        instance_id=instance_id,
        engine_version=engine_version,
        newsroom_token=newsroom_token,
    )
    target = boot["database_target"]
    cfg = boot["cfg"]
    conn = connect(target)
    try:
        instance = conn.execute(
            "SELECT instance_id, canonical_domain, engine_version, runtime_owner FROM publication_instances WHERE instance_id=?",
            (instance_id,),
        ).fetchone()
        if instance is None:
            raise ProductionAppError("instance registration readback failed")
        if instance["runtime_owner"] != "site_application":
            raise ProductionAppError("SITE_OWNS_RUNTIME readback failed")
        if boot["database_backend"] == "postgresql":
            rows = conn.execute(
                "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public'"
            ).fetchall()
            tables = {str(row["tablename"]) for row in rows}
            trigger_rows = conn.execute(
                """
                SELECT tgname FROM pg_catalog.pg_trigger
                WHERE NOT tgisinternal
                  AND tgname IN ('runtime_events_no_update','runtime_events_no_delete')
                """
            ).fetchall()
            triggers = {str(row["tgname"]) for row in trigger_rows}
        else:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            tables = {str(row["name"]) for row in rows}
            trigger_rows = conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
            triggers = {str(row["name"]) for row in trigger_rows}
    finally:
        conn.close()

    required_tables = {
        "publication_instances",
        "stories",
        "signals",
        "verification_tasks",
        "verification_results",
        "fact_kernels",
        "runtime_events",
        "story_drafts",
        "editorial_qa_decisions",
        "story_publications",
        "publication_revisions",
        "knowledge_entities",
        "media_assets",
        "channel_products",
        "scheduler_jobs",
        "release_state",
    }
    missing = sorted(required_tables - tables)
    if missing:
        raise ProductionAppError(f"runtime schema readback missing tables: {missing}")
    required_triggers = {"runtime_events_no_update", "runtime_events_no_delete"}
    if not required_triggers.issubset(triggers):
        raise ProductionAppError("runtime event append-only trigger readback failed")

    return {
        "status": "PASS",
        "instance_id": instance_id,
        "canonical_domain": cfg["publication"]["canonical_domain"],
        "runtime_owner": "site_application",
        "database_backend": boot["database_backend"],
        "database_bound": True,
        "newsroom_auth_configured": True,
        "repository_runtime_state_enabled": False,
        "required_tables_present": True,
        "append_only_event_ledger_verified": True,
        "engine_version": engine_version,
    }


class ProductionWSGIApp:
    def __init__(self, *, instance_id: str, engine_version: str, newsroom_token: str) -> None:
        boot = bootstrap_runtime(
            instance_id=instance_id,
            engine_version=engine_version,
            newsroom_token=newsroom_token,
        )
        target = boot["database_target"]
        packs = boot["packs"]
        self.instance_id = instance_id
        self.engine_version = engine_version
        self.newsroom_token = newsroom_token
        self.database_backend = boot["database_backend"]
        self.site = SiteRuntimeApp(
            db_path=target,
            instance_id=instance_id,
            engine_version=engine_version,
            newsroom_token=newsroom_token,
        )
        self.scheduler = SchedulerNewsroomApp(
            db_path=target,
            instance_id=instance_id,
            newsroom_token=newsroom_token,
        )
        self.releases = ReleaseNewsroomApp(
            db_path=target,
            instance_id=instance_id,
            newsroom_token=newsroom_token,
        )
        self.public = PublicSiteApp(
            db_path=target,
            instance_id=instance_id,
            publication_pack=packs["publication"],
        )

    @staticmethod
    def _json(start_response: StartResponse, status: str, payload: dict[str, Any]) -> Iterable[bytes]:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        start_response(
            status,
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
            ],
        )
        return [body]

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        path = str(environ.get("PATH_INFO") or "/")
        if path == "/healthz":
            try:
                readiness = deployment_readiness(
                    instance_id=self.instance_id,
                    engine_version=self.engine_version,
                    newsroom_token=self.newsroom_token,
                )
            except Exception as exc:
                return self._json(
                    start_response,
                    "503 Service Unavailable",
                    {
                        "status": "not_ready",
                        "instance_id": self.instance_id,
                        "database_backend": self.database_backend,
                        "reason": type(exc).__name__,
                    },
                )
            return self._json(start_response, "200 OK", readiness)
        if path in {"/newsroom/scheduler", "/newsroom/api/scheduler"}:
            return self.scheduler(environ, start_response)
        if path in {"/newsroom/releases", "/newsroom/api/releases"}:
            return self.releases(environ, start_response)
        if path == "/newsroom" or path.startswith("/newsroom/"):
            return self.site(environ, start_response)
        return self.public(environ, start_response)


def create_production_app_from_env() -> ProductionWSGIApp:
    instance_id = _required_env("LOCAL_NEWS_INSTANCE_ID")
    engine_version = _required_env("LOCAL_NEWS_ENGINE_VERSION")
    newsroom_token = _required_env("LOCAL_NEWS_NEWSROOM_TOKEN")
    return ProductionWSGIApp(
        instance_id=instance_id,
        engine_version=engine_version,
        newsroom_token=newsroom_token,
    )
