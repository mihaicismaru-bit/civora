#!/usr/bin/env python3
"""Private distribution ledger visibility for LOCAL NEWS OS vNext."""
from __future__ import annotations

import argparse
import html
import json
import tempfile
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote

from distribution_engine import delivery_record, ensure_distribution_schema, list_deliveries
from media_runtime import MediaNewsroomApp
from runtime_store import connect, initialize, register_instance
from site_runtime import StartResponse, _safe_int


class DistributionNewsroomApp(MediaNewsroomApp):
    """Adds per-channel product/delivery observability to the private newsroom."""

    def _render_distribution(self, deliveries: list[dict[str, Any]]) -> bytes:
        rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(item['story_id']))}</td>"
            f"<td>{html.escape(str(item['channel_id']))}</td>"
            f"<td>{html.escape(str(item['desired_revision']))}</td>"
            f"<td>{html.escape(str(item['status']))}</td>"
            f"<td>{html.escape(str(item['attempts']))}</td>"
            f"<td>{html.escape(str(item.get('external_object_id') or ''))}</td>"
            f"<td>{'yes' if item.get('remote_verified') else 'no'}</td>"
            f"<td>{html.escape(str(item.get('last_error') or ''))}</td>"
            "</tr>"
            for item in deliveries
        ) or '<tr><td colspan="8">No distribution deliveries yet</td></tr>'
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Distribution · Newsroom</title><style>body{font-family:system-ui,sans-serif;max-width:1280px;margin:2rem auto;padding:0 1rem;color:#171717}"
            "table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #ddd;text-align:left;padding:.6rem;vertical-align:top}</style></head><body>"
            "<p><a href=\"/newsroom\">← Newsroom</a></p><h1>Distribution</h1>"
            "<table><thead><tr><th>Story</th><th>Channel</th><th>Revision</th><th>Status</th><th>Attempts</th><th>External ID</th><th>Remote verified</th><th>Last error</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></body></html>"
        ).encode("utf-8")

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        path = str(environ.get("PATH_INFO") or "/")
        route = (
            path == "/newsroom/distribution"
            or path == "/newsroom/api/distribution"
            or path.startswith("/newsroom/api/distribution/delivery/")
            or path.startswith("/newsroom/api/distribution/story/")
        )
        if not route:
            return super().__call__(environ, start_response)
        if method != "GET":
            return self._json_response(
                start_response,
                "405 Method Not Allowed",
                {"error": "method_not_allowed"},
                private=True,
                extra_headers=[("Allow", "GET")],
            )
        denied = self._require_newsroom_auth(environ, start_response)
        if denied is not None:
            return denied
        conn = self._connect()
        try:
            ensure_distribution_schema(conn)
            if path == "/newsroom/distribution":
                return self._response(
                    start_response,
                    "200 OK",
                    self._render_distribution(list_deliveries(conn, instance_id=self.instance_id, limit=500)),
                    content_type="text/html; charset=utf-8",
                    private=True,
                )
            if path == "/newsroom/api/distribution":
                query = parse_qs(str(environ.get("QUERY_STRING") or ""))
                status = (query.get("status") or [None])[0]
                story_id = (query.get("story_id") or [None])[0]
                limit = _safe_int((query.get("limit") or [None])[0], default=100, minimum=1, maximum=1000)
                return self._json_response(
                    start_response,
                    "200 OK",
                    {"deliveries": list_deliveries(conn, instance_id=self.instance_id, status=status, story_id=story_id, limit=limit)},
                    private=True,
                )
            if path.startswith("/newsroom/api/distribution/story/"):
                story_id = unquote(path[len("/newsroom/api/distribution/story/") :]).strip("/")
                values = list_deliveries(conn, instance_id=self.instance_id, story_id=story_id, limit=100)
                if not values:
                    return self._json_response(start_response, "404 Not Found", {"error": "distribution_story_not_found"}, private=True)
                return self._json_response(start_response, "200 OK", {"deliveries": values}, private=True)
            delivery_id = unquote(path[len("/newsroom/api/distribution/delivery/") :]).strip("/")
            try:
                record = delivery_record(conn, instance_id=self.instance_id, delivery_id=delivery_id)
            except Exception:
                return self._json_response(start_response, "404 Not Found", {"error": "delivery_not_found"}, private=True)
            return self._json_response(start_response, "200 OK", record, private=True)
        finally:
            conn.close()


def _manifest(instance_id: str, domain: str, marker: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": marker * 64,
        "runtime": {"owner": "site_application", "repository_runtime_state_enabled": False},
    }


def _call(app, path: str, *, token: str | None = None) -> tuple[str, dict[str, str], bytes]:
    captured: dict[str, Any] = {}
    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)
    environ: dict[str, Any] = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": ""}
    if token:
        environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    body = b"".join(app(environ, start_response))
    return str(captured["status"]), dict(captured["headers"]), body


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "runtime.sqlite3"
        conn = connect(db)
        initialize(conn)
        ensure_distribution_schema(conn)
        register_instance(conn, _manifest("alpha-local", "alpha.invalid", "a"), engine_version="p14-web-test")
        conn.close()
        app = DistributionNewsroomApp(
            db_path=db,
            instance_id="alpha-local",
            engine_version="p14-web-test",
            newsroom_token="secret-token",
        )
        status, headers, _ = _call(app, "/newsroom/api/distribution")
        assert status.startswith("401") and "no-store" in headers["Cache-Control"]
        status, headers, body = _call(app, "/newsroom/api/distribution", token="secret-token")
        assert status.startswith("200") and "noindex" in headers["X-Robots-Tag"]
        assert json.loads(body)["deliveries"] == []
        status, _, body = _call(app, "/newsroom/distribution", token="secret-token")
        assert status.startswith("200") and b"Distribution" in body
    print("LOCAL_NEWS_OS_VNEXT_DISTRIBUTION_RUNTIME_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("use --self-test; production invocation is owned by the site runtime")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
