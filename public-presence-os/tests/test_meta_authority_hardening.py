from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from public_presence_os.meta_live_runtime import (
    EXPECTED_PAGE_ID, MetaLiveHold, MetaReadClient, classify_meta_hold, preflight_report,
)
from test_meta_live_runtime import FakeClient, Opener, TOKEN_B, env


@pytest.mark.parametrize("binding", [None, {}, {"id": "wrong"}])
def test_binding_must_match_before_content_reads(tmp_path, binding):
    class Client(FakeClient):
        def get(self, **kwargs):
            result = super().get(**kwargs)
            if kwargs["params"].get("fields") == "id,name,instagram_business_account":
                result["instagram_business_account"] = binding
            return result

    client = Client()
    report = preflight_report(db_path=tmp_path / "events.db", values=env(META_THREADS_ENABLED="false"),
                              run_live_read=True, client=client)
    assert report["HOLD REASON"] == "HOLD_META_INSTAGRAM_BINDING_MISMATCH"
    assert report["INSTAGRAM BINDING"] == "FAIL"
    assert report["READ CAPABILITIES"] == "FAIL"
    assert not any(call[1].endswith("/posts") for call in client.calls)


def test_user_credential_in_page_slot_fails_closed(tmp_path):
    class Client(FakeClient):
        def get(self, **kwargs):
            result = super().get(**kwargs)
            if kwargs["path"].endswith("/me"):
                result["id"] = "user-subject"
            return result

    client = Client()
    report = preflight_report(db_path=tmp_path / "events.db", values=env(META_THREADS_ENABLED="false"),
                              run_live_read=True, client=client)
    assert report["HOLD CLASSIFICATION"] == "PAGE_TOKEN_SUBJECT_MISMATCH"
    assert report["READ CAPABILITIES"] == "FAIL"
    assert len(client.calls) == 2
    assert client.calls[0][1].endswith("/" + EXPECTED_PAGE_ID)
    assert all(call[2] == {"fields": "id,name"} for call in client.calls)
    assert TOKEN_B not in json.dumps(report)


def test_graph_100_is_ambiguous_secret_free_and_never_retried():
    body = {"error": {"code": 100, "message": TOKEN_B, "fbtrace_id": TOKEN_B}}
    opener = Opener([HTTPError("https://redacted.invalid", 400, TOKEN_B, {},
                              io.BytesIO(json.dumps(body).encode()))])
    sleeps = []
    with pytest.raises(MetaLiveHold) as caught:
        MetaReadClient(opener=opener, sleeper=sleeps.append).get(
            host="graph.facebook.com", path="/v26.0/me", params={"fields": "id,name"}, token=TOKEN_B)
    assert caught.value.reason == "HOLD_META_HTTP_400_GRAPH_100"
    assert classify_meta_hold(caught.value.reason) == "PAGE_READ_AUTHORITY_TOKEN_TYPE_OR_PERMISSION_CONTEXT_UNRESOLVED"
    assert TOKEN_B not in str(caught.value)
    assert len(opener.requests) == 1
    assert sleeps == []


@pytest.mark.parametrize("header", ["bad", "-1", "nan", "inf", "999"])
def test_retry_after_cannot_break_bounded_retry(header):
    opener = Opener([HTTPError("https://redacted.invalid", 429, "limited", {"Retry-After": header},
                              io.BytesIO()), {"id": "ok"}])
    sleeps = []
    MetaReadClient(opener=opener, sleeper=sleeps.append).get(
        host="graph.facebook.com", path="/v26.0/me", params={}, token=TOKEN_B)
    assert len(opener.requests) == 2
    assert sleeps == [30.0 if header == "999" else 1.0]


def test_shadow_workflow_requires_explicit_material_change_and_has_no_push_trigger():
    workflow = (Path(__file__).parents[2] / ".github/workflows/public-presence-shadow.yml").read_text()
    triggers = workflow.split("permissions:", 1)[0]
    assert "workflow_dispatch:" in triggers
    assert "material_change_reference:" in triggers
    assert "required: true" in triggers
    assert "push:" not in triggers
    assert "schedule:" not in triggers
    assert "PPOS_SHADOW_MATERIAL_CHANGE_REFERENCE_REQUIRED" in workflow
    assert 'KILL_SWITCH: "true"' in workflow
    assert 'LIVE_WRITE: "false"' in workflow
    assert 'META_THREADS_ENABLED: "false"' in workflow
