#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import life_programme_intelligence as life


def _source_html(source_id: str, *, mutation: str = "") -> bytes:
    bodies = {
        "LIFE_CINEA_PROGRAMME": "<h1>LIFE</h1><p>Nature and Biodiversity</p><p>Clean Energy Transition</p>",
        "LIFE_CINEA_CALLS_2026_INDEX": "<h1>LIFE Calls for proposals 2026</h1><p>Funding & Tenders Portal</p><p>Open Closed deadlines budgets are discovery text only.</p>",
        "LIFE_CINEA_APPLICANT_SUPPORT": "<h1>Who can apply?</h1><p>a public or private legal entity registered in the EU</p>",
        "LIFE_CINEA_WORK_PROGRAMME_2025_2027": "<h1>LIFE Multiannual Work Programme 2025-2027</h1><p>English language version</p>",
    }
    return (bodies[source_id] + mutation).encode()


class _Headers:
    def get(self, key: str, default: str = "") -> str:
        return "text/html; charset=UTF-8" if key.lower() == "content-type" else default


class _Response:
    def __init__(self, *, raw: bytes, url: str):
        self.raw = raw
        self.url = url
        self.status = 200
        self.headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit: int | None = None) -> bytes:
        return self.raw if limit is None else self.raw[:limit]

    def geturl(self) -> str:
        return self.url


def main() -> int:
    registry, _ = life.load_registry()
    by_url = {row["authority_url"]: row for row in registry["sources"]}

    def make_urlopen(*, mutate_calls: bool = False):
        def fake_urlopen(request, timeout: float):
            del timeout
            url = request.full_url
            row = by_url[url]
            mutation = "<p>new bounded discovery wording</p>" if mutate_calls and row["id"] == "LIFE_CINEA_CALLS_2026_INDEX" else ""
            return _Response(raw=_source_html(row["id"], mutation=mutation), url=url)
        return fake_urlopen

    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = Path(tmpdir) / "registry.json"
        registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
        with patch("life_programme_intelligence.urlopen", make_urlopen()):
            result = life.acquire(
                run_id="synthetic-life-live",
                observed_at="2026-09-03T01:30:00Z",
                registry_path=registry_path,
                live=True,
            )

        assert result["schema"] == "PARTENER_EU_LIFE_PROGRAMME_INTELLIGENCE_V1"
        assert result["parser_version"] == "LIFE_PROGRAMME_INTELLIGENCE_V1_1"
        assert result["programme_id"] == "LIFE" and result["programme_family"] == "LIFE"
        assert result["source_family"] == "EU_DIRECT"
        assert result["programme_families"] == ["LIFE"]
        assert result["source_count"] == 4
        assert result["healthy_source_count"] == 4
        assert result["degraded_source_count"] == 0
        assert result["source_health_state"] == "HEALTHY"
        assert result["lkg_required"] is False
        assert result["market_intelligence_only"] is True
        assert result["fit_scores_are_not_eligibility"] is True
        assert len(result["semantic_fingerprint"]) == 64
        states = {row["source_id"]: row["observation_state"] for row in result["sources"]}
        assert states["LIFE_CINEA_CALLS_2026_INDEX"] == "CALL_INDEX_DISCOVERY"
        assert states["LIFE_CINEA_WORK_PROGRAMME_2025_2027"] == "PROGRAMMING_PIPELINE"
        for row in result["sources"]:
            assert len(row["normalized_visible_text_sha256"]) == 64
            assert len(row["source_semantic_fingerprint"]) == 64
            assert row["source_health"]["normalized_visible_text_sha256"] == row["normalized_visible_text_sha256"]
        for key in life.MATERIAL_FLAGS:
            assert result[key] is False
        assert result["publication_effect"] == "NONE"
        assert "exact_call_or_topic_identifier" in result["missing_for_open_confirmation"]
        assert "field_scoped_material_admission" in result["missing_for_open_confirmation"]
        fit = result["programme_intelligence"][0]
        assert fit["fit_score_is_not_eligibility"] is True
        assert "PUBLIC_BODY" in fit["applicant_fit_tags"]
        assert "PROGRAMME_BUDGET_ENVELOPES_NON_AUTHORIZING" in fit["pipeline_signals"]

        with patch("life_programme_intelligence.urlopen", make_urlopen(mutate_calls=True)):
            changed = life.acquire(
                run_id="synthetic-life-content-change",
                observed_at="2026-09-03T01:30:30Z",
                registry_path=registry_path,
                live=True,
            )
        assert changed["semantic_fingerprint"] != result["semantic_fingerprint"]
        before = next(row for row in result["sources"] if row["source_id"] == "LIFE_CINEA_CALLS_2026_INDEX")
        after = next(row for row in changed["sources"] if row["source_id"] == "LIFE_CINEA_CALLS_2026_INDEX")
        assert before["normalized_visible_text_sha256"] != after["normalized_visible_text_sha256"]
        assert before["source_semantic_fingerprint"] != after["source_semantic_fingerprint"]
        assert all(changed[key] is False for key in life.MATERIAL_FLAGS)

        authorizing = copy.deepcopy(registry)
        authorizing["policy"]["open_call_authorized"] = True
        bad_policy = Path(tmpdir) / "authorizing.json"
        bad_policy.write_text(json.dumps(authorizing), encoding="utf-8")
        try:
            life.load_registry(bad_policy)
        except ValueError:
            pass
        else:
            raise AssertionError("LIFE registry accepted OPEN authorization")

        bad_state = copy.deepcopy(registry)
        bad_state["sources"][1]["observation_state"] = "OPEN_CALL"
        bad_state_path = Path(tmpdir) / "bad-state.json"
        bad_state_path.write_text(json.dumps(bad_state), encoding="utf-8")
        try:
            life.load_registry(bad_state_path)
        except ValueError:
            pass
        else:
            raise AssertionError("LIFE registry accepted material OPEN_CALL observation state")

        call_index_url = next(row["authority_url"] for row in registry["sources"] if row["id"] == "LIFE_CINEA_CALLS_2026_INDEX")
        normal_urlopen = make_urlopen()

        def degraded_urlopen(request, timeout: float):
            if request.full_url == call_index_url:
                raise URLError("synthetic call-index outage")
            return normal_urlopen(request, timeout)

        with patch("life_programme_intelligence.urlopen", degraded_urlopen):
            degraded = life.acquire(
                run_id="synthetic-life-degraded",
                observed_at="2026-09-03T01:31:00Z",
                registry_path=registry_path,
                live=True,
            )
        assert degraded["source_health_state"] == "DEGRADED"
        assert degraded["lkg_required"] is True
        assert degraded["semantic_fingerprint"] is None
        call_index = next(row for row in degraded["sources"] if row["source_id"] == "LIFE_CINEA_CALLS_2026_INDEX")
        assert call_index["source_health"]["health_state"] == "DEGRADED_TRANSPORT"
        assert call_index["source_health"]["lkg_required"] is True
        assert call_index["source_semantic_fingerprint"] is None
        for key in life.MATERIAL_FLAGS:
            assert degraded[key] is False

    print({
        "status": "PASS",
        "adapter": "LIFE_PROGRAMME_INTELLIGENCE_V1_1",
        "official_source_count": 4,
        "content_sensitive_semantic_hash": True,
        "call_index_discovery_only": True,
        "programming_pipeline_non_authorizing": True,
        "fit_score_is_not_eligibility": True,
        "transport_failure_requires_lkg": True,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
