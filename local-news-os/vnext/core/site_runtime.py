#!/usr/bin/env python3
"""Generic site-owned WSGI runtime and private newsroom for LOCAL NEWS OS vNext.

The application reads editorial runtime state only from the configured database.
It contains no locality-specific routing or repository-state dependency.
"""
from __future__ import annotations

import argparse
import html
import hmac
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, quote, unquote
from wsgiref.simple_server import make_server

from runtime_store import (
    connect,
    create_story,
    get_story,
    initialize,
    list_events,
    register_instance,
    transition_story,
)
from signal_engine import get_signal, list_signals, materialize_source_item
from source_adapters import SourceDefinition, SourceItem

StartResponse = Callable[[str, list[tuple[str, str]]], Any]


class SiteRuntimeConfigError(RuntimeError):
    pass


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _safe_int(raw: str | None, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw or default)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


class SiteRuntimeApp:
    def __init__(
        self,
        *,
        db_path: str | Path,
        instance_id: str,
        engine_version: str,
        newsroom_token: str | None,
    ) -> None:
        if not instance_id or not engine_version:
            raise SiteRuntimeConfigError("instance_id and engine_version are required")
        self.db_path = str(db_path)
        self.instance_id = instance_id
        self.engine_version = engine_version
        self.newsroom_token = newsroom_token or None

    def _connect(self):
        return connect(self.db_path)

    def _response(
        self,
        start_response: StartResponse,
        status: str,
        body: bytes,
        *,
        content_type: str,
        private: bool = False,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> Iterable[bytes]:
        headers = [
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
            ("X-Content-Type-Options", "nosniff"),
        ]
        if private:
            headers.extend(
                [
                    ("Cache-Control", "no-store, private"),
                    ("X-Robots-Tag", "noindex, nofollow, noarchive"),
                    ("Referrer-Policy", "no-referrer"),
                    (
                        "Content-Security-Policy",
                        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
                    ),
                ]
            )
        if extra_headers:
            headers.extend(extra_headers)
        start_response(status, headers)
        return [body]

    def _json_response(
        self,
        start_response: StartResponse,
        status: str,
        payload: Any,
        *,
        private: bool = False,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> Iterable[bytes]:
        return self._response(
            start_response,
            status,
            _json_bytes(payload),
            content_type="application/json; charset=utf-8",
            private=private,
            extra_headers=extra_headers,
        )

    def _authorized(self, environ: dict[str, Any]) -> bool:
        if not self.newsroom_token:
            return False
        header = str(environ.get("HTTP_AUTHORIZATION") or "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        candidate = header[len(prefix) :]
        return hmac.compare_digest(candidate, self.newsroom_token)

    def _require_newsroom_auth(
        self, environ: dict[str, Any], start_response: StartResponse
    ) -> Iterable[bytes] | None:
        if not self.newsroom_token:
            return self._json_response(
                start_response,
                "503 Service Unavailable",
                {"error": "newsroom_auth_not_configured"},
                private=True,
            )
        if not self._authorized(environ):
            return self._json_response(
                start_response,
                "401 Unauthorized",
                {"error": "unauthorized"},
                private=True,
                extra_headers=[("WWW-Authenticate", 'Bearer realm="newsroom"')],
            )
        return None

    def _instance_row(self, conn) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM publication_instances WHERE instance_id=?",
            (self.instance_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def _summary(self, conn) -> dict[str, Any]:
        instance = self._instance_row(conn)
        if instance is None:
            raise SiteRuntimeConfigError("instance is not registered in runtime database")
        state_rows = conn.execute(
            """
            SELECT state, COUNT(*) AS count
            FROM stories
            WHERE instance_id=?
            GROUP BY state
            ORDER BY state
            """,
            (self.instance_id,),
        ).fetchall()
        story_counts = {str(row["state"]): int(row["count"]) for row in state_rows}
        story_total = sum(story_counts.values())
        signal_rows = conn.execute(
            """
            SELECT state, COUNT(*) AS count
            FROM signals
            WHERE instance_id=?
            GROUP BY state
            ORDER BY state
            """,
            (self.instance_id,),
        ).fetchall()
        signal_counts = {str(row["state"]): int(row["count"]) for row in signal_rows}
        signal_total = sum(signal_counts.values())
        recent_events = conn.execute(
            """
            SELECT event_id, aggregate_type, aggregate_id, event_type,
                   from_state, to_state, reason, engine_version, created_at
            FROM runtime_events
            WHERE instance_id=?
            ORDER BY event_id DESC
            LIMIT 20
            """,
            (self.instance_id,),
        ).fetchall()
        return {
            "instance": instance,
            "story_counts": story_counts,
            "story_total": story_total,
            "signal_counts": signal_counts,
            "signal_total": signal_total,
            "recent_events": [dict(row) for row in recent_events],
        }

    def _list_stories(self, conn, *, state: str | None, limit: int) -> list[dict[str, Any]]:
        if state:
            rows = conn.execute(
                """
                SELECT * FROM stories
                WHERE instance_id=? AND state=?
                ORDER BY updated_at DESC, story_id ASC
                LIMIT ?
                """,
                (self.instance_id, state, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM stories
                WHERE instance_id=?
                ORDER BY updated_at DESC, story_id ASC
                LIMIT ?
                """,
                (self.instance_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_signals(self, conn, *, state: str | None, limit: int) -> list[dict[str, Any]]:
        return list_signals(
            conn,
            instance_id=self.instance_id,
            state=state,
            limit=limit,
        )

    def _render_newsroom(
        self,
        summary: dict[str, Any],
        stories: list[dict[str, Any]],
        signals: list[dict[str, Any]],
    ) -> bytes:
        instance = summary["instance"]
        counts = summary["story_counts"]
        count_items = "".join(
            f"<li><strong>{html.escape(state)}</strong>: {count}</li>"
            for state, count in sorted(counts.items())
        ) or "<li>No stories yet</li>"
        signal_count_items = "".join(
            f"<li><strong>{html.escape(state)}</strong>: {count}</li>"
            for state, count in sorted(summary["signal_counts"].items())
        ) or "<li>No signals yet</li>"
        story_rows = "".join(
            "<tr>"
            f"<td><a href=\"/newsroom/stories/{quote(str(story['story_id']), safe='')}\">{html.escape(str(story['story_id']))}</a></td>"
            f"<td>{html.escape(str(story.get('state') or ''))}</td>"
            f"<td>{html.escape(str(story.get('headline') or ''))}</td>"
            f"<td>{html.escape(str(story.get('updated_at') or ''))}</td>"
            "</tr>"
            for story in stories
        ) or '<tr><td colspan="4">No stories yet</td></tr>'
        signal_rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(signal['signal_id']))}</td>"
            f"<td>{html.escape(str(signal.get('state') or ''))}</td>"
            f"<td>{html.escape(str(signal.get('source_id') or ''))}</td>"
            f"<td>{html.escape(str(signal.get('source_title') or ''))}</td>"
            f"<td>{html.escape(str(signal.get('publication_authority') or ''))}</td>"
            f"<td>{html.escape(str(signal.get('updated_at') or ''))}</td>"
            "</tr>"
            for signal in signals
        ) or '<tr><td colspan="6">No signals yet</td></tr>'
        document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Newsroom</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#171717}}
header{{display:flex;justify-content:space-between;gap:1rem;align-items:baseline}}
small{{color:#666}} table{{width:100%;border-collapse:collapse;margin-top:1.5rem}}
th,td{{border-bottom:1px solid #ddd;text-align:left;padding:.65rem;vertical-align:top}}
ul{{display:flex;flex-wrap:wrap;gap:1rem;list-style:none;padding:0}} a{{color:inherit}}
</style>
</head>
<body>
<header><h1>Newsroom</h1><small>{html.escape(str(instance['canonical_domain']))}</small></header>
<p>Runtime owner: <strong>{html.escape(str(instance['runtime_owner']))}</strong> · Engine: {html.escape(str(instance['engine_version']))}</p>
<h2>Signals</h2><ul>{signal_count_items}</ul>
<table><thead><tr><th>ID</th><th>State</th><th>Source</th><th>Title</th><th>Authority</th><th>Updated</th></tr></thead><tbody>{signal_rows}</tbody></table>
<h2>Story lifecycle</h2><ul>{count_items}</ul>
<h2>Recent stories</h2>
<table><thead><tr><th>ID</th><th>State</th><th>Headline</th><th>Updated</th></tr></thead><tbody>{story_rows}</tbody></table>
</body></html>"""
        return document.encode("utf-8")

    def _render_story_detail(self, story: dict[str, Any], events: list[dict[str, Any]]) -> bytes:
        event_rows = "".join(
            "<tr>"
            f"<td>{event['event_id']}</td>"
            f"<td>{html.escape(str(event['event_type']))}</td>"
            f"<td>{html.escape(str(event.get('from_state') or ''))}</td>"
            f"<td>{html.escape(str(event.get('to_state') or ''))}</td>"
            f"<td>{html.escape(str(event.get('reason') or ''))}</td>"
            f"<td>{html.escape(str(event.get('created_at') or ''))}</td>"
            "</tr>"
            for event in events
        ) or '<tr><td colspan="6">No events</td></tr>'
        document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Story · Newsroom</title><style>
body{{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#171717}}
table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #ddd;text-align:left;padding:.65rem;vertical-align:top}}
code{{overflow-wrap:anywhere}}
</style></head><body>
<p><a href="/newsroom">← Newsroom</a></p>
<h1>{html.escape(str(story.get('headline') or story['story_id']))}</h1>
<p><strong>State:</strong> {html.escape(str(story['state']))} · <strong>Revision:</strong> {story['revision']}</p>
<p><strong>Story ID:</strong> <code>{html.escape(str(story['story_id']))}</code></p>
<h2>Lifecycle events</h2><table><thead><tr><th>#</th><th>Event</th><th>From</th><th>To</th><th>Reason</th><th>At</th></tr></thead><tbody>{event_rows}</tbody></table>
</body></html>"""
        return document.encode("utf-8")

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        path = str(environ.get("PATH_INFO") or "/")
        if method != "GET":
            return self._json_response(
                start_response,
                "405 Method Not Allowed",
                {"error": "method_not_allowed"},
                extra_headers=[("Allow", "GET")],
            )

        if path == "/healthz":
            conn = self._connect()
            try:
                instance = self._instance_row(conn)
            finally:
                conn.close()
            if instance is None:
                return self._json_response(
                    start_response,
                    "503 Service Unavailable",
                    {"status": "not_ready", "instance_id": self.instance_id},
                )
            return self._json_response(
                start_response,
                "200 OK",
                {
                    "status": "ok",
                    "instance_id": self.instance_id,
                    "runtime_owner": instance["runtime_owner"],
                    "engine_version": instance["engine_version"],
                },
            )

        if path == "/newsroom" or path.startswith("/newsroom/"):
            denied = self._require_newsroom_auth(environ, start_response)
            if denied is not None:
                return denied

            conn = self._connect()
            try:
                if path == "/newsroom":
                    summary = self._summary(conn)
                    stories = self._list_stories(conn, state=None, limit=100)
                    signals = self._list_signals(conn, state=None, limit=100)
                    return self._response(
                        start_response,
                        "200 OK",
                        self._render_newsroom(summary, stories, signals),
                        content_type="text/html; charset=utf-8",
                        private=True,
                    )

                if path == "/newsroom/api/summary":
                    return self._json_response(
                        start_response,
                        "200 OK",
                        self._summary(conn),
                        private=True,
                    )

                if path == "/newsroom/api/signals":
                    query = parse_qs(str(environ.get("QUERY_STRING") or ""))
                    state = (query.get("state") or [None])[0]
                    limit = _safe_int((query.get("limit") or [None])[0], default=100, minimum=1, maximum=500)
                    return self._json_response(
                        start_response,
                        "200 OK",
                        {"signals": self._list_signals(conn, state=state, limit=limit)},
                        private=True,
                    )

                signal_api_prefix = "/newsroom/api/signals/"
                if path.startswith(signal_api_prefix):
                    signal_id = unquote(path[len(signal_api_prefix) :])
                    try:
                        signal = get_signal(conn, instance_id=self.instance_id, signal_id=signal_id)
                    except Exception:
                        return self._json_response(
                            start_response,
                            "404 Not Found",
                            {"error": "signal_not_found"},
                            private=True,
                        )
                    events = list_events(
                        conn,
                        instance_id=self.instance_id,
                        aggregate_type="signal",
                        aggregate_id=signal_id,
                    )
                    return self._json_response(
                        start_response,
                        "200 OK",
                        {"signal": signal, "events": events},
                        private=True,
                    )

                if path == "/newsroom/api/stories":
                    query = parse_qs(str(environ.get("QUERY_STRING") or ""))
                    state = (query.get("state") or [None])[0]
                    limit = _safe_int((query.get("limit") or [None])[0], default=100, minimum=1, maximum=500)
                    return self._json_response(
                        start_response,
                        "200 OK",
                        {"stories": self._list_stories(conn, state=state, limit=limit)},
                        private=True,
                    )

                api_prefix = "/newsroom/api/stories/"
                if path.startswith(api_prefix):
                    story_id = unquote(path[len(api_prefix) :])
                    try:
                        story = get_story(conn, instance_id=self.instance_id, story_id=story_id)
                    except Exception:
                        return self._json_response(
                            start_response,
                            "404 Not Found",
                            {"error": "story_not_found"},
                            private=True,
                        )
                    events = list_events(
                        conn,
                        instance_id=self.instance_id,
                        aggregate_type="story",
                        aggregate_id=story_id,
                    )
                    return self._json_response(
                        start_response,
                        "200 OK",
                        {"story": story, "events": events},
                        private=True,
                    )

                detail_prefix = "/newsroom/stories/"
                if path.startswith(detail_prefix):
                    story_id = unquote(path[len(detail_prefix) :])
                    try:
                        story = get_story(conn, instance_id=self.instance_id, story_id=story_id)
                    except Exception:
                        return self._response(
                            start_response,
                            "404 Not Found",
                            b"Story not found",
                            content_type="text/plain; charset=utf-8",
                            private=True,
                        )
                    events = list_events(
                        conn,
                        instance_id=self.instance_id,
                        aggregate_type="story",
                        aggregate_id=story_id,
                    )
                    return self._response(
                        start_response,
                        "200 OK",
                        self._render_story_detail(story, events),
                        content_type="text/html; charset=utf-8",
                        private=True,
                    )
            finally:
                conn.close()

        return self._json_response(start_response, "404 Not Found", {"error": "not_found"})


def create_app_from_env() -> SiteRuntimeApp:
    db_path = os.environ.get("LOCAL_NEWS_RUNTIME_DB")
    instance_id = os.environ.get("LOCAL_NEWS_INSTANCE_ID")
    engine_version = os.environ.get("LOCAL_NEWS_ENGINE_VERSION") or "vnext-dev"
    if not db_path or not instance_id:
        raise SiteRuntimeConfigError(
            "LOCAL_NEWS_RUNTIME_DB and LOCAL_NEWS_INSTANCE_ID are required"
        )
    return SiteRuntimeApp(
        db_path=db_path,
        instance_id=instance_id,
        engine_version=engine_version,
        newsroom_token=os.environ.get("LOCAL_NEWS_NEWSROOM_TOKEN"),
    )


def _invoke(app: SiteRuntimeApp, path: str, *, token: str | None = None, query: str = ""):
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ: dict[str, Any] = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": query,
    }
    if token is not None:
        environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    body = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], body


def _manifest(instance_id: str, domain: str, config_sha: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": config_sha,
        "runtime": {"owner": "site_application", "repository_runtime_state_enabled": False},
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "site.sqlite3"
        conn = connect(db)
        initialize(conn)
        register_instance(conn, _manifest("alpha-local", "alpha.invalid", "a" * 64), engine_version="2.0.0-test")
        register_instance(conn, _manifest("beta-local", "beta.invalid", "b" * 64), engine_version="2.0.0-test")
        create_story(
            conn,
            instance_id="alpha-local",
            story_id="alpha-story",
            fingerprint="alpha-fp",
            engine_version="2.0.0-test",
            headline="Alpha public-interest story",
        )
        transition_story(
            conn,
            instance_id="alpha-local",
            story_id="alpha-story",
            to_state="VERIFIED",
            engine_version="2.0.0-test",
            reason="primary evidence passed",
            expected_revision=1,
        )
        create_story(
            conn,
            instance_id="beta-local",
            story_id="beta-story",
            fingerprint="beta-fp",
            engine_version="2.0.0-test",
            headline="Beta isolated story",
        )
        source = SourceDefinition.from_dict(
            {
                "source_id": "fixture-feed",
                "adapter": "RSS_ATOM",
                "role": "DISCOVERY",
                "url": "https://example.test/feed",
                "config": {},
            }
        )
        alpha_signal, _ = materialize_source_item(
            conn,
            instance_id="alpha-local",
            source=source,
            item=SourceItem(
                source_id="fixture-feed",
                external_id="alpha-signal",
                url="https://example.test/alpha",
                title="Alpha signal headline",
                fingerprint="alpha-signal-fingerprint",
            ),
            engine_version="2.0.0-test",
        )
        materialize_source_item(
            conn,
            instance_id="beta-local",
            source=source,
            item=SourceItem(
                source_id="fixture-feed",
                external_id="beta-signal",
                url="https://example.test/beta",
                title="Beta isolated signal",
                fingerprint="beta-signal-fingerprint",
            ),
            engine_version="2.0.0-test",
        )
        conn.close()

        app = SiteRuntimeApp(
            db_path=db,
            instance_id="alpha-local",
            engine_version="2.0.0-test",
            newsroom_token="test-secret",
        )

        status, _, body = _invoke(app, "/healthz")
        assert status.startswith("200")
        health = json.loads(body)
        assert health["runtime_owner"] == "site_application"
        assert health["instance_id"] == "alpha-local"

        status, headers, body = _invoke(app, "/newsroom")
        assert status.startswith("401")
        assert json.loads(body)["error"] == "unauthorized"
        assert headers["Cache-Control"] == "no-store, private"
        assert headers["X-Robots-Tag"].startswith("noindex")

        status, headers, body = _invoke(app, "/newsroom", token="test-secret")
        assert status.startswith("200")
        text = body.decode("utf-8")
        assert "Alpha public-interest story" in text
        assert "Beta isolated story" not in text
        assert "Alpha signal headline" in text
        assert "Beta isolated signal" not in text
        assert headers["Cache-Control"] == "no-store, private"

        status, _, body = _invoke(app, "/newsroom/api/summary", token="test-secret")
        assert status.startswith("200")
        summary = json.loads(body)
        assert summary["story_total"] == 1
        assert summary["story_counts"] == {"VERIFIED": 1}
        assert summary["signal_total"] == 1
        assert summary["signal_counts"] == {"DISCOVERED": 1}
        assert summary["instance"]["runtime_owner"] == "site_application"

        status, _, body = _invoke(app, "/newsroom/api/signals", token="test-secret", query="state=DISCOVERED")
        assert status.startswith("200")
        signals = json.loads(body)["signals"]
        assert [item["signal_id"] for item in signals] == [alpha_signal["signal_id"]]
        assert signals[0]["publication_authority"] == "NONE"
        assert signals[0]["material_fact_ready"] is False
        assert signals[0]["fact_kernel_ready"] is False

        status, _, body = _invoke(
            app,
            f"/newsroom/api/signals/{alpha_signal['signal_id']}",
            token="test-secret",
        )
        assert status.startswith("200")
        signal_detail = json.loads(body)
        assert signal_detail["signal"]["source_title"] == "Alpha signal headline"
        assert [event["event_type"] for event in signal_detail["events"]] == ["SIGNAL_DISCOVERED"]

        status, _, body = _invoke(app, "/newsroom/api/stories", token="test-secret", query="state=VERIFIED")
        assert status.startswith("200")
        stories = json.loads(body)["stories"]
        assert [item["story_id"] for item in stories] == ["alpha-story"]

        status, _, body = _invoke(app, "/newsroom/api/stories/alpha-story", token="test-secret")
        assert status.startswith("200")
        detail = json.loads(body)
        assert detail["story"]["revision"] == 2
        assert [event["event_type"] for event in detail["events"]] == [
            "STORY_CREATED",
            "STORY_STATE_CHANGED",
        ]

        fail_closed = SiteRuntimeApp(
            db_path=db,
            instance_id="alpha-local",
            engine_version="2.0.0-test",
            newsroom_token=None,
        )
        status, _, body = _invoke(fail_closed, "/newsroom")
        assert status.startswith("503")
        assert json.loads(body)["error"] == "newsroom_auth_not_configured"

    print("LOCAL_NEWS_OS_VNEXT_SITE_RUNTIME_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.serve:
        app = create_app_from_env()
        with make_server(args.host, args.port, app) as server:
            server.serve_forever()
        return 0
    parser.error("use --self-test or --serve")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
