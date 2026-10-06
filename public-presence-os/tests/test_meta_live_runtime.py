from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError

import pytest

from public_presence_os.meta_live_runtime import (
    EXPECTED_APP_ID,
    EXPECTED_IG_ID,
    EXPECTED_NAME,
    EXPECTED_PAGE_ID,
    EXPECTED_THREADS_ID,
    EXPECTED_USERNAME,
    MetaEventStore,
    MetaLiveHold,
    MetaReadClient,
    MetaReadRuntime,
    MetaRuntimeConfig,
    preflight_report,
)


TOKEN_A = "A" * 40
TOKEN_B = "B" * 40
TOKEN_C = "C" * 40


def env(**overrides):
    values = {
        "META_APP_ID": EXPECTED_APP_ID,
        "META_USER_ACCESS_TOKEN": TOKEN_A,
        "META_PAGE_ACCESS_TOKEN": TOKEN_B,
        "META_PAGE_ID": EXPECTED_PAGE_ID,
        "META_IG_USER_ID": EXPECTED_IG_ID,
        "META_THREADS_USER_ID": EXPECTED_THREADS_ID,
        "META_THREADS_ACCESS_TOKEN": TOKEN_C,
        "KILL_SWITCH": "true",
        "LIVE_WRITE": "false",
    }
    values.update(overrides)
    return values


class Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit):
        return json.dumps(self.value).encode()


class Opener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return Response(outcome)


def test_runtime_config_is_redacted_and_identity_bound():
    config = MetaRuntimeConfig.from_env(env(META_APP_SECRET="S" * 16))
    text = repr(config) + json.dumps(config.redacted())
    assert TOKEN_A not in text
    assert TOKEN_B not in text
    assert TOKEN_C not in text
    assert config.redacted()["app_secret_present"] is True
    with pytest.raises(MetaLiveHold, match="HOLD_META_IDENTITY_MISMATCH_META_PAGE_ID"):
        MetaRuntimeConfig.from_env(env(META_PAGE_ID="wrong"))


def test_missing_credentials_fail_closed_without_value_disclosure(tmp_path):
    report = preflight_report(db_path=tmp_path / "events.sqlite3", values={})
    assert report["META APP"] == "FAIL"
    assert report["READ CAPABILITIES"] == "FAIL"
    assert report["WRITE CAPABILITIES"] == "LOCKED"
    assert report["KILL SWITCH"] == "ENGAGED"
    assert report["LIVE AUTHORITY"] == "NONE"
    assert report["EVENT LOG"] == "PASS"


def test_read_client_uses_authorization_header_and_bounded_retry():
    error = HTTPError("https://redacted.invalid", 429, "limited", {"Retry-After": "0"}, io.BytesIO())
    opener = Opener([error, {"id": "ok"}])
    sleeps = []
    client = MetaReadClient(opener=opener, sleeper=sleeps.append, max_attempts=2)
    assert client.get(host="graph.facebook.com", path="/v26.0/me", params={"fields": "id"}, token=TOKEN_A) == {"id": "ok"}
    assert len(opener.requests) == 2
    request = opener.requests[0][0]
    assert TOKEN_A not in request.full_url
    assert request.get_header("Authorization") == f"Bearer {TOKEN_A}"
    assert sleeps == [0.0]


def test_event_store_deduplicates_and_restores_cursor(tmp_path):
    path = tmp_path / "events.sqlite3"
    store = MetaEventStore(path)
    kwargs = {
        "platform": "FACEBOOK_PAGE",
        "object_type": "POST",
        "external_id": "post-1",
        "observed_at": "2026-10-03T00:00:00Z",
        "fetched_at": "2026-10-03T00:01:00Z",
        "provenance": "META_GRAPH_PAGE_POSTS",
        "normalized": {"id": "post-1", "message": "hello"},
        "cursor": "cursor-1",
    }
    first = store.ingest(**kwargs)
    second = MetaEventStore(path).ingest(**kwargs)
    assert first.action == "ACCEPTED"
    assert second.action == "DUPLICATE_NOOP"
    assert first.event_id == second.event_id
    assert store.cursor("FACEBOOK_PAGE:POST") == "cursor-1"
    assert len(store.events()) == 1


def test_event_store_rejects_secret_bearing_payload(tmp_path):
    store = MetaEventStore(tmp_path / "events.sqlite3")
    with pytest.raises(MetaLiveHold, match="HOLD_META_SECRET_BEARING_EVENT"):
        store.ingest(
            platform="FACEBOOK_PAGE",
            object_type="POST",
            external_id="post-1",
            observed_at="2026-10-03T00:00:00Z",
            fetched_at="2026-10-03T00:01:00Z",
            provenance="TEST",
            normalized={"id": "post-1", "access_token": TOKEN_A},
            cursor="cursor-1",
        )


class FakeClient:
    def __init__(self):
        self.calls = []

    def get(self, *, host, path, params, token):
        self.calls.append((host, path, params, token))
        if path.endswith("/me/accounts"):
            return {"data": [{
                "id": EXPECTED_PAGE_ID,
                "name": EXPECTED_NAME,
                "tasks": ["ANALYZE"],
                "instagram_business_account": {"id": EXPECTED_IG_ID},
            }]}
        if path.endswith(f"/{EXPECTED_PAGE_ID}"):
            return {"id": EXPECTED_PAGE_ID, "name": EXPECTED_NAME, "instagram_business_account": {"id": EXPECTED_IG_ID}}
        if path.endswith(f"/{EXPECTED_PAGE_ID}/posts"):
            return {"data": [{"id": "page_post_1", "message": "hello", "created_time": "2026-10-03T00:00:00Z"}], "paging": {"cursors": {"after": "p1"}}}
        if path.endswith("/page_post_1/comments"):
            return {"data": [{"id": "page_comment_1", "message": "useful question", "created_time": "2026-10-03T00:02:00Z"}]}
        if path.endswith(f"/{EXPECTED_IG_ID}"):
            return {"id": EXPECTED_IG_ID, "username": EXPECTED_USERNAME, "name": EXPECTED_NAME}
        if path.endswith(f"/{EXPECTED_IG_ID}/media"):
            return {"data": [{"id": "ig_media_1", "caption": "hello", "timestamp": "2026-10-03T00:00:00Z"}]}
        if path.endswith("/ig_media_1/comments"):
            return {"data": [{"id": "ig_comment_1", "text": "specific question", "timestamp": "2026-10-03T00:03:00Z"}]}
        if path.endswith("/me"):
            if host == "graph.facebook.com":
                return {"id": EXPECTED_PAGE_ID, "name": EXPECTED_NAME}
            return {"id": EXPECTED_THREADS_ID, "username": EXPECTED_USERNAME, "name": EXPECTED_NAME}
        if path.endswith("/me/threads"):
            return {"data": [{"id": "thread_1", "text": "hello", "timestamp": "2026-10-03T00:00:00Z", "has_replies": True}]}
        if path.endswith("/thread_1/replies"):
            return {"data": [{"id": "reply_1", "text": "context please", "timestamp": "2026-10-03T00:04:00Z"}]}
        raise AssertionError(path)


def test_cross_lane_sync_is_read_only_restart_safe_and_idempotent(tmp_path):
    config = MetaRuntimeConfig.from_env(env())
    client = FakeClient()
    store = MetaEventStore(tmp_path / "events.sqlite3")
    runtime = MetaReadRuntime(config, client, store)
    first = runtime.sync_once()
    second = runtime.sync_once()
    assert first.state == "READ_ONLY_REAL_SYNC_PASS"
    assert dict(first.identities) == {
        "FACEBOOK_PAGE": EXPECTED_PAGE_ID,
        "INSTAGRAM_PROFESSIONAL": EXPECTED_IG_ID,
        "THREADS": EXPECTED_THREADS_ID,
    }
    assert first.accepted == 6
    assert first.write_count == 0
    assert second.accepted == 0
    assert second.duplicates == 6
    assert [run["state"] for run in store.sync_runs()] == [
        "READ_ONLY_REAL_SYNC_PASS",
        "READ_ONLY_REAL_SYNC_PASS",
    ]
    assert all(call[1] and call[3] in {TOKEN_A, TOKEN_B, TOKEN_C} for call in client.calls)


def test_sync_refuses_safety_widening(tmp_path):
    config = MetaRuntimeConfig.from_env(env(KILL_SWITCH="false"))
    runtime = MetaReadRuntime(config, FakeClient(), MetaEventStore(tmp_path / "events.sqlite3"))
    with pytest.raises(MetaLiveHold, match="HOLD_META_READ_RUNTIME_SAFETY_STATE"):
        runtime.sync_once()



def test_preflight_exposes_only_secret_safe_hold_reason(tmp_path):
    class FailingClient(FakeClient):
        def get(self, **kwargs):
            raise MetaLiveHold("HOLD_META_HTTP_403")

    report = preflight_report(
        db_path=tmp_path / "events.sqlite3",
        values=env(META_THREADS_ENABLED="false"),
        run_live_read=True,
        client=FailingClient(),
    )
    assert report["HOLD REASON"] == "HOLD_META_HTTP_403"
    rendered = json.dumps(report, sort_keys=True)
    assert TOKEN_A not in rendered
    assert TOKEN_B not in rendered
    assert TOKEN_C not in rendered


def test_failed_sync_is_durably_recorded_without_secret_material(tmp_path):
    class FailingClient(FakeClient):
        def get(self, **kwargs):
            raise MetaLiveHold("HOLD_META_HTTP_403")

    store = MetaEventStore(tmp_path / "events.sqlite3")
    runtime = MetaReadRuntime(MetaRuntimeConfig.from_env(env()), FailingClient(), store)
    with pytest.raises(MetaLiveHold, match="HOLD_META_HTTP_403"):
        runtime.sync_once()
    run = store.sync_runs()[0]
    assert run["state"] == "HOLD"
    assert run["hold_reason"] == "HOLD_META_HTTP_403"
    assert TOKEN_A not in json.dumps(run)


def test_partial_sync_never_reports_read_capabilities_pass(tmp_path):
    class PartialClient(FakeClient):
        def get(self, **kwargs):
            if kwargs["path"].endswith("/ig_media_1/comments"):
                raise MetaLiveHold("HOLD_META_HTTP_403")
            return super().get(**kwargs)

    report = preflight_report(
        db_path=tmp_path / "events.sqlite3",
        values=env(),
        run_live_read=True,
        client=PartialClient(),
    )
    assert report["PAGE IDENTITY"] == "PASS"
    assert report["READ CAPABILITIES"] == "FAIL"
    assert report["LIVE AUTHORITY"] == "LIMITED"



def test_page_token_can_be_primary_authority_without_user_token(tmp_path):
    values = env(META_THREADS_ENABLED="false")
    values.pop("META_THREADS_ACCESS_TOKEN")
    values.pop("META_USER_ACCESS_TOKEN")
    config = MetaRuntimeConfig.from_env(values)
    assert config.user_token is None
    assert config.page_token == TOKEN_B

    client = FakeClient()
    store = MetaEventStore(tmp_path / "events.sqlite3")
    summary = MetaReadRuntime(config, client, store).sync_once()
    assert summary.state == "READ_ONLY_REAL_SYNC_PASS"
    assert dict(summary.identities) == {
        "FACEBOOK_PAGE": EXPECTED_PAGE_ID,
        "INSTAGRAM_PROFESSIONAL": EXPECTED_IG_ID,
    }
    assert summary.write_count == 0
    assert client.calls[0][1].endswith(f"/{EXPECTED_PAGE_ID}")
    assert client.calls[0][2]["fields"] == "id,name"
    assert all(call[3] == TOKEN_B for call in client.calls)


def test_threads_can_be_held_without_blocking_facebook_instagram_read_only(tmp_path):
    values = env(META_THREADS_ENABLED="false")
    values.pop("META_THREADS_ACCESS_TOKEN")
    config = MetaRuntimeConfig.from_env(values)
    assert config.threads_enabled is False
    assert config.threads_token is None
    assert config.redacted()["threads_token_present"] is False

    client = FakeClient()
    store = MetaEventStore(tmp_path / "events.sqlite3")
    summary = MetaReadRuntime(config, client, store).sync_once()
    assert summary.state == "READ_ONLY_REAL_SYNC_PASS"
    assert dict(summary.identities) == {
        "FACEBOOK_PAGE": EXPECTED_PAGE_ID,
        "INSTAGRAM_PROFESSIONAL": EXPECTED_IG_ID,
    }
    assert summary.accepted == 4
    assert summary.write_count == 0
    assert all(call[0] == "graph.facebook.com" for call in client.calls)

    report = preflight_report(
        db_path=tmp_path / "preflight.sqlite3",
        values=values,
        run_live_read=True,
        client=FakeClient(),
    )
    assert report["PAGE IDENTITY"] == "PASS"
    assert report["INSTAGRAM BINDING"] == "PASS"
    assert report["THREADS IDENTITY"] == "HOLD_EXTERNAL"
    assert report["READ CAPABILITIES"] == "PASS"
    assert report["WRITE CAPABILITIES"] == "LOCKED"


def test_cli_preflight_without_credentials_is_precise_and_secret_free(tmp_path):
    clean_env = os.environ.copy()
    for name in (
        "META_APP_ID", "META_APP_SECRET", "META_USER_ACCESS_TOKEN", "META_PAGE_ACCESS_TOKEN",
        "META_PAGE_ID", "META_IG_USER_ID", "META_THREADS_USER_ID", "META_THREADS_ACCESS_TOKEN",
    ):
        clean_env.pop(name, None)
    result = subprocess.run(
        [sys.executable, "-m", "public_presence_os.cli", "meta-preflight", "--db", str(tmp_path / "events.sqlite3")],
        capture_output=True,
        text=True,
        env=clean_env,
        check=False,
    )
    assert result.returncode == 0
    assert "META APP                 FAIL" in result.stdout
    assert "WRITE CAPABILITIES       LOCKED" in result.stdout
    assert "LIVE AUTHORITY           NONE" in result.stdout
    assert "MISSING:META_READ_TOKEN,META_THREADS_ACCESS_TOKEN" in result.stdout
    assert TOKEN_A not in result.stdout
