#!/usr/bin/env python3
"""Private scheduler/health newsroom surface for LOCAL NEWS OS vNext P15."""
from __future__ import annotations

import argparse
import html
import hmac
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable

from runtime_store import connect, initialize, register_instance
from scheduler_engine import SchedulerPolicy, ensure_scheduler_schema, enqueue_job, record_health, scheduler_snapshot

StartResponse = Callable[[str, list[tuple[str, str]]], Any]


class SchedulerRuntimeError(RuntimeError):
    pass


class SchedulerNewsroomApp:
    """Mountable site-runtime handler for /newsroom/scheduler and its JSON API."""

    def __init__(self, *, db_path: str | Path, instance_id: str, newsroom_token: str | None) -> None:
        if not instance_id:
            raise SchedulerRuntimeError("instance_id is required")
        self.db_path = str(db_path)
        self.instance_id = instance_id
        self.newsroom_token = newsroom_token or None

    def _response(self, start_response: StartResponse, status: str, body: bytes, content_type: str) -> Iterable[bytes]:
        start_response(
            status,
            [
                ("Content-Type", content_type),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store, private"),
                ("X-Robots-Tag", "noindex, nofollow, noarchive"),
                ("X-Content-Type-Options", "nosniff"),
                ("Referrer-Policy", "no-referrer"),
            ],
        )
        return [body]

    def _json(self, start_response: StartResponse, status: str, payload: Any) -> Iterable[bytes]:
        return self._response(
            start_response,
            status,
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _authorized(self, environ: dict[str, Any]) -> bool:
        if not self.newsroom_token:
            return False
        header = str(environ.get("HTTP_AUTHORIZATION") or "")
        if not header.startswith("Bearer "):
            return False
        return hmac.compare_digest(header[7:], self.newsroom_token)

    @staticmethod
    def _render(snapshot: dict[str, Any]) -> bytes:
        count_items = "".join(
            f"<li><strong>{html.escape(status)}</strong>: {count}</li>"
            for status, count in sorted(snapshot["job_counts"].items())
        ) or "<li>No scheduler jobs</li>"
        jobs = "".join(
            "<tr>"
            f"<td>{html.escape(str(job['stage']))}</td>"
            f"<td>{html.escape(str(job['aggregate_type']))}</td>"
            f"<td>{html.escape(str(job['aggregate_id']))}</td>"
            f"<td>{html.escape(str(job['status']))}</td>"
            f"<td>{job['attempts']}/{job['max_attempts']}</td>"
            f"<td>{html.escape(str(job.get('next_attempt_at') or ''))}</td>"
            f"<td>{html.escape(str(job.get('last_error') or ''))}</td>"
            "</tr>"
            for job in snapshot["jobs"]
        ) or '<tr><td colspan="7">No jobs</td></tr>'
        health = "".join(
            "<tr>"
            f"<td>{html.escape(str(item['component']))}</td>"
            f"<td>{html.escape(str(item['status']))}</td>"
            f"<td>{html.escape(str(item['observed_at']))}</td>"
            f"<td><code>{html.escape(json.dumps(item['detail'], ensure_ascii=False, sort_keys=True))}</code></td>"
            "</tr>"
            for item in snapshot["health"]
        ) or '<tr><td colspan="4">No health observations</td></tr>'
        doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scheduler · Newsroom</title><style>body{{font-family:system-ui,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #ddd;padding:.6rem;text-align:left;vertical-align:top}}ul{{display:flex;gap:1rem;flex-wrap:wrap;list-style:none;padding:0}}code{{overflow-wrap:anywhere}}</style></head><body>
<p><a href="/newsroom">← Newsroom</a></p><h1>Scheduler & self-heal</h1><p>Instance: <strong>{html.escape(snapshot['instance_id'])}</strong></p>
<h2>Job state</h2><ul>{count_items}</ul><table><thead><tr><th>Stage</th><th>Aggregate</th><th>ID</th><th>Status</th><th>Attempts</th><th>Next attempt</th><th>Last error</th></tr></thead><tbody>{jobs}</tbody></table>
<h2>Health</h2><table><thead><tr><th>Component</th><th>Status</th><th>Observed</th><th>Detail</th></tr></thead><tbody>{health}</tbody></table>
</body></html>"""
        return doc.encode("utf-8")

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        path = str(environ.get("PATH_INFO") or "")
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        if path not in {"/newsroom/scheduler", "/newsroom/api/scheduler"}:
            return self._json(start_response, "404 Not Found", {"error": "not_found"})
        if method != "GET":
            return self._json(start_response, "405 Method Not Allowed", {"error": "method_not_allowed"})
        if not self.newsroom_token:
            return self._json(start_response, "503 Service Unavailable", {"error": "newsroom_auth_not_configured"})
        if not self._authorized(environ):
            return self._json(start_response, "401 Unauthorized", {"error": "unauthorized"})
        conn = connect(self.db_path)
        try:
            ensure_scheduler_schema(conn)
            snapshot = scheduler_snapshot(conn, instance_id=self.instance_id)
        finally:
            conn.close()
        if path == "/newsroom/api/scheduler":
            return self._json(start_response, "200 OK", snapshot)
        return self._response(start_response, "200 OK", self._render(snapshot), "text/html; charset=utf-8")


def _invoke(app: SchedulerNewsroomApp, path: str, token: str | None = None) -> tuple[str, dict[str, str], bytes]:
    captured: dict[str, Any] = {}
    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)
    environ: dict[str, Any] = {"REQUEST_METHOD": "GET", "PATH_INFO": path}
    if token is not None:
        environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    body = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], body


def _manifest(instance_id: str, domain: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": "a" * 64,
        "runtime": {"owner": "site_application", "repository_runtime_state_enabled": False},
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "scheduler-runtime.sqlite3"
        conn = connect(db)
        initialize(conn)
        register_instance(conn, _manifest("alpha-local", "alpha.invalid"), engine_version="p15-runtime-test")
        ensure_scheduler_schema(conn)
        enqueue_job(
            conn,
            instance_id="alpha-local",
            stage="VERIFY_SIGNAL",
            aggregate_type="signal",
            aggregate_id="signal-a",
            desired_fingerprint="signal-fp",
            payload={},
            policy=SchedulerPolicy(),
        )
        record_health(conn, instance_id="alpha-local", component="newsroom_scheduler", status="DEGRADED", detail={"retry": 1})
        conn.close()
        app = SchedulerNewsroomApp(db_path=db, instance_id="alpha-local", newsroom_token="secret-token")
        status, headers, body = _invoke(app, "/newsroom/scheduler", "secret-token")
        assert status == "200 OK" and b"Scheduler &amp; self-heal" not in body and b"Scheduler & self-heal" in body
        assert headers["Cache-Control"] == "no-store, private" and headers["X-Robots-Tag"].startswith("noindex")
        status, _, body = _invoke(app, "/newsroom/api/scheduler", "secret-token")
        assert status == "200 OK" and json.loads(body)["job_counts"]["PENDING"] == 1
        status, _, _ = _invoke(app, "/newsroom/api/scheduler", "wrong")
        assert status == "401 Unauthorized"
        noauth = SchedulerNewsroomApp(db_path=db, instance_id="alpha-local", newsroom_token=None)
        status, _, _ = _invoke(noauth, "/newsroom/scheduler")
        assert status == "503 Service Unavailable"
        print("LOCAL_NEWS_OS_VNEXT_P15_NEWSROOM_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    db = os.environ.get("LOCAL_NEWS_RUNTIME_DB")
    instance = os.environ.get("LOCAL_NEWS_INSTANCE_ID")
    if not db or not instance:
        raise SchedulerRuntimeError("LOCAL_NEWS_RUNTIME_DB and LOCAL_NEWS_INSTANCE_ID are required")
    raise SchedulerRuntimeError("scheduler newsroom is a mountable WSGI component; mount it in the site application")


if __name__ == "__main__":
    raise SystemExit(main())
