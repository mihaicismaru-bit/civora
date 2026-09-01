#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))


def load(name: str):
    path = INGEST / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


watch = load("creative_europe_ft_watch")
watch_reconcile = load("creative_europe_ft_watch_reconcile")
handoff = load("creative_europe_ft_handoff")

REFERENCE = "CREA-CULT-2026-PERFORM-EU"
STATUS = "31094502"


def fake_post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
    if "search" in endpoint and "facet" not in endpoint:
        payload = {
            "results": [{
                "metadata": {
                    "identifier": [REFERENCE],
                    "callIdentifier": ["CREA-CULT-2026"],
                    "status": [STATUS],
                    "programAbbreviation": ["CREA"],
                    "programmePeriod": ["2021 - 2027"],
                    "deadlineDate": ["2026-09-15"],
                },
                "content": "Perform Europe fixture",
            }]
        }
    else:
        payload = {
            "facets": [{
                "name": "status",
                "values": [{"rawValue": STATUS, "value": "Open for submission"}],
            }]
        }
    raw = json.dumps(payload, sort_keys=True).encode()
    return payload, raw, {"url": endpoint, "http_status": 200, "sha256": "a" * 64}


def fake_topic(url: str):
    return {
        "url": url,
        "verified": True,
        "http_status": 200,
        "body_sha256": "b" * 64,
    }


def make_watch(run_id: str, fetched_at: str):
    return watch.collect_watch(
        run_id=run_id,
        fetched_at=fetched_at,
        text="CREA-",
        page_size=50,
        max_pages=1,
        post_func=fake_post,
    )


previous_watch = make_watch("previous-watch", "2026-08-31T20:00:00+00:00")
previous_receipt = watch_reconcile.reconcile_watch(
    previous_watch,
    reconciled_at="2026-08-31T20:01:00Z",
)
assert previous_receipt["exact_verification_queue_count"] == 1
assert previous_receipt["exact_verification_queue"][0]["reference"] == REFERENCE

current_watch = make_watch("current-watch", "2026-08-31T21:00:00+00:00")
current_receipt = watch_reconcile.reconcile_watch(
    current_watch,
    previous_watch,
    reconciled_at="2026-08-31T21:01:00Z",
)
assert current_receipt["reconciliation_state"] == "NO_CHANGE"
assert current_receipt["exact_verification_queue"] == []

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    history = root / "history" / "download-previous" / "watch-reconciliation"
    history.mkdir(parents=True)
    (history / "ft-programme-watch-reconciliation.json").write_text(
        json.dumps(previous_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    selected, source, source_receipt = handoff.select_handoff(
        current_receipt,
        history_root=root / "history",
    )
    assert selected is not None and selected["reference"] == REFERENCE
    assert source == handoff.SELECTION_PREVIOUS
    assert source_receipt is not None

    output = root / "output"
    summary = handoff.execute_handoff(
        current_receipt,
        run_id="fixture-handoff",
        output_dir=output,
        history_root=root / "history",
        post_func=fake_post,
        topic_func=fake_topic,
    )
    assert summary["observation_state"] == handoff.EXECUTED_STATE
    assert summary["selected_reference"] == REFERENCE
    assert summary["selection_source"] == handoff.SELECTION_PREVIOUS
    assert summary["exact_candidate_observation_state"] == "OPEN_CALL"
    assert summary["exact_authority_url_verified"] is True
    assert summary["exact_semantic_reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert summary["material_admission_ready_for_downstream_review"] is True
    assert summary["open_call_authorized"] is False
    assert summary["call_alert_authorized"] is False
    assert (output / "current" / "ft-exact-evidence.json").is_file()
    assert (output / "reconciliation" / "ft-reconciliation.json").is_file()

    completed = root / "history" / "download-completed" / "handoff" / "current"
    completed.mkdir(parents=True)
    shutil.copyfile(output / "current" / "ft-exact-evidence.json", completed / "ft-exact-evidence.json")
    selected2, source2, _ = handoff.select_handoff(
        current_receipt,
        history_root=root / "history",
    )
    assert selected2 is None and source2 is None

bad = copy.deepcopy(current_receipt)
bad["open_call_authorized"] = True
try:
    handoff.select_handoff(bad)
except ValueError:
    pass
else:
    raise AssertionError("exact-handoff executor accepted authorizing watch reconciliation")

print("PASS Creative Europe bounded exact-handoff execution stays non-authorizing")
