#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import life_programme_intelligence as life
import life_programme_reconcile as rec


class _Headers:
    def get(self, key: str, default: str = "") -> str:
        return "text/html; charset=UTF-8" if key.lower() == "content-type" else default


class _Response:
    def __init__(self, raw: bytes, url: str):
        self.raw = raw; self.url = url; self.status = 200; self.headers = _Headers()
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False
    def read(self, limit=None): return self.raw if limit is None else self.raw[:limit]
    def geturl(self): return self.url


def html_for(source_id: str, mutation: str = "") -> bytes:
    base = {
        "LIFE_CINEA_PROGRAMME": "<h1>LIFE</h1><p>Nature and Biodiversity</p><p>Clean Energy Transition</p>",
        "LIFE_CINEA_CALLS_2026_INDEX": "<h1>LIFE Calls for proposals 2026</h1><p>Funding & Tenders Portal</p>",
        "LIFE_CINEA_APPLICANT_SUPPORT": "<h1>Who can apply</h1><p>public or private legal entity registered in the EU</p>",
        "LIFE_CINEA_WORK_PROGRAMME_2025_2027": "<h1>LIFE Multiannual Work Programme 2025-2027</h1><p>English language version</p>",
    }[source_id]
    return (base + mutation).encode()


def main() -> int:
    registry, _ = life.load_registry()
    by_url = {row["authority_url"]: row for row in registry["sources"]}
    def opener(mutation: str = ""):
        def fake(request, timeout):
            del timeout
            row = by_url[request.full_url]
            suffix = mutation if row["id"] == "LIFE_CINEA_CALLS_2026_INDEX" else ""
            return _Response(html_for(row["id"], suffix), request.full_url)
        return fake

    with tempfile.TemporaryDirectory() as td:
        rp = Path(td) / "registry.json"
        rp.write_text(json.dumps(registry), encoding="utf-8")
        with patch("life_programme_intelligence.urlopen", opener()):
            previous = life.acquire(run_id="prev", observed_at="2026-09-03T01:00:00Z", registry_path=rp, live=True)
            current = life.acquire(run_id="curr", observed_at="2026-09-03T02:00:00Z", registry_path=rp, live=True)
        no_change = rec.reconcile(current, previous)
        assert no_change["reconciliation_state"] == "NO_CHANGE"
        assert no_change["semantic_change_count"] == 0
        assert no_change["pipeline_watch_candidate"] is False
        assert no_change["material_admission_ready_for_downstream_review"] is False

        with patch("life_programme_intelligence.urlopen", opener("<p>new programming wording</p>")):
            changed = life.acquire(run_id="changed", observed_at="2026-09-03T03:00:00Z", registry_path=rp, live=True)
        semantic = rec.reconcile(changed, current)
        assert semantic["reconciliation_state"] == "LIFE_PROGRAMME_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
        assert semantic["semantic_change_count"] == 1
        assert semantic["pipeline_watch_candidate"] is True
        assert semantic["open_call_authorized"] is False

        legacy = copy.deepcopy(previous)
        legacy["parser_version"] = "LIFE_PROGRAMME_INTELLIGENCE_V1"
        legacy["adapter_id"] = "LIFE_PROGRAMME_INTELLIGENCE_V1"
        migrated = rec.reconcile(current, legacy)
        assert migrated["reconciliation_state"] == "PARSER_VERSION_CHANGED_BASELINE_REFRESH_NON_AUTHORIZING"
        assert migrated["semantic_change_count"] == 0
        assert migrated["pipeline_watch_candidate"] is False

        call_index_url = next(row["authority_url"] for row in registry["sources"] if row["id"] == "LIFE_CINEA_CALLS_2026_INDEX")
        normal = opener()
        def degraded_opener(request, timeout):
            if request.full_url == call_index_url:
                raise URLError("synthetic outage")
            return normal(request, timeout)
        with patch("life_programme_intelligence.urlopen", degraded_opener):
            degraded = life.acquire(run_id="degraded", observed_at="2026-09-03T04:00:00Z", registry_path=rp, live=True)
        fail_closed = rec.reconcile(degraded, current)
        assert fail_closed["reconciliation_state"] == "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED"
        assert fail_closed["semantic_reconciliation_passed"] is False
        assert fail_closed["semantic_change_count"] == 0
        assert fail_closed["pipeline_watch_candidate"] is False
        assert fail_closed["lkg_reference_required"] is True
        assert fail_closed["lkg_reference_available"] is True
        assert fail_closed["lkg_reference_is_current_truth"] is False

        with patch("life_programme_intelligence.urlopen", opener("<p>new programming wording</p>")):
            recovered_current = life.acquire(run_id="recovered", observed_at="2026-09-03T05:00:00Z", registry_path=rp, live=True)
        recovered = rec.reconcile(recovered_current, degraded)
        assert recovered["reconciliation_state"] == "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
        assert recovered["semantic_change_count"] == 0

        future = copy.deepcopy(previous)
        future["fetched_at"] = current["fetched_at"]
        try:
            rec.reconcile(current, future)
        except ValueError:
            pass
        else:
            raise AssertionError("equal-time previous LIFE snapshot accepted")

        drift = copy.deepcopy(previous)
        drift["sources"][0]["authority_url"] = "https://cinea.ec.europa.eu/programmes/not-life_en"
        try:
            rec.reconcile(current, drift)
        except ValueError:
            pass
        else:
            raise AssertionError("LIFE previous identity drift accepted")

        authorizing = copy.deepcopy(previous)
        authorizing["open_call_authorized"] = True
        try:
            rec.reconcile(current, authorizing)
        except ValueError:
            pass
        else:
            raise AssertionError("authorizing previous LIFE snapshot accepted")

    print({
        "status": "PASS", "reconciler": rec.RECONCILER_VERSION,
        "same_identity_no_change": True, "content_change_pipeline_watch_only": True,
        "parser_migration_baseline": True, "degraded_current_lkg_fail_closed": True,
        "health_recovery_baseline": True, "history_order_enforced": True,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
