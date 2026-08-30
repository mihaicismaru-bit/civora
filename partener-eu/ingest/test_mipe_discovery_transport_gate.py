#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import mysmis_transport_handoff as HANDOFF  # noqa: E402

FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "mysmis_handoff_fixture", HERE / "test_mysmis_transport_handoff.py"
)
FIXTURE = importlib.util.module_from_spec(FIXTURE_SPEC)
assert FIXTURE_SPEC.loader is not None
FIXTURE_SPEC.loader.exec_module(FIXTURE)

INGEST_SPEC = importlib.util.spec_from_file_location(
    "mipe_discovery_ingest_under_test", HERE / "mipe_discovery_ingest.py"
)
INGEST = importlib.util.module_from_spec(INGEST_SPEC)
assert INGEST_SPEC.loader is not None
INGEST_SPEC.loader.exec_module(INGEST)


def valid_handoff(primary_ok: bool, resources_ok: bool, dwh_ok: bool) -> dict:
    return HANDOFF.build_handoff(
        FIXTURE.matrix(primary_ok, resources_ok, dwh_ok),
        observed_at="2026-08-30T08:10:00+00:00",
        run_id="mipe-discovery-gate-regression",
    )


def write_handoff(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parsed_rows() -> tuple[int, dict, list[str]]:
    return (
        1,
        {
            "fixture-call": {
                "programme": "Program Test",
                "type": "TEST",
                "call": "Apel test",
                "status": "FINALIZAT",
                "entities": "1",
                "drafts": "0",
                "submitted": "1",
                "contracts": "1",
                "withdrawn": "0",
                "callBudgetRon": "100",
                "totalProjectBudgetRon": "100",
                "submittedGrantBudgetRon": "100",
            }
        },
        ["FINALIZAT"],
    )


class MySMISDiscoveryTransportGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_state = INGEST.STATE
        self.original_fetch = INGEST.fetch
        self.original_parse = INGEST.parse_mysmis

    def tearDown(self) -> None:
        INGEST.STATE = self.original_state
        INGEST.fetch = self.original_fetch
        INGEST.parse_mysmis = self.original_parse

    def test_valid_canonical_handoff_allows_exactly_one_canonical_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff_path = root / "handoff.json"
            write_handoff(handoff_path, valid_handoff(True, True, True))
            INGEST.STATE = root / "state.json"
            INGEST.parse_mysmis = lambda raw: parsed_rows()
            calls: list[str] = []

            def fake_fetch(url: str, timeout=12, max_bytes=3_000_000):
                calls.append(url)
                return INGEST.MYSMIS, "fixture"

            INGEST.fetch = fake_fetch
            result = INGEST.ingest_mysmis(handoff_path)
            self.assertTrue(result["ok"])
            self.assertEqual(result["transportGate"], "CANONICAL_VALIDATED_HANDOFF")
            self.assertEqual(calls, [INGEST.MYSMIS])
            self.assertEqual(
                result["transportEvidence"]["handoffSha256"],
                valid_handoff(True, True, True)["handoffSha256"],
            )

    def test_alternate_only_never_calls_canonical_parser_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff_path = root / "handoff.json"
            write_handoff(handoff_path, valid_handoff(False, True, False))
            INGEST.STATE = root / "state.json"
            INGEST.fetch = lambda *args, **kwargs: self.fail("canonical fetch must stay closed")
            result = INGEST.ingest_mysmis(handoff_path)
            self.assertFalse(result["ok"])
            self.assertTrue(result["preserved"])
            self.assertEqual(result["transportGate"], "ALTERNATE_DISCOVERY_ONLY")

    def test_all_transports_unavailable_preserves_lkg_without_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff_path = root / "handoff.json"
            write_handoff(handoff_path, valid_handoff(False, False, False))
            INGEST.STATE = root / "state.json"
            INGEST.fetch = lambda *args, **kwargs: self.fail("canonical fetch must stay closed")
            result = INGEST.ingest_mysmis(handoff_path)
            self.assertFalse(result["ok"])
            self.assertTrue(result["preserved"])
            self.assertEqual(result["transportGate"], "NO_OFFICIAL_REPORT_TRANSPORT_AVAILABLE")

    def test_tampered_handoff_fails_closed_before_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff_path = root / "handoff.json"
            candidate = valid_handoff(True, False, False)
            candidate["canonicalPrimaryAvailable"] = False
            write_handoff(handoff_path, candidate)
            INGEST.STATE = root / "state.json"
            INGEST.fetch = lambda *args, **kwargs: self.fail("tampered evidence must not fetch")
            result = INGEST.ingest_mysmis(handoff_path)
            self.assertFalse(result["ok"])
            self.assertTrue(result["preserved"])
            self.assertEqual(result["transportGate"], "HANDOFF_INVALID_FAIL_CLOSED")

    def test_rehashed_origin_drift_still_fails_closed_before_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff_path = root / "handoff.json"
            candidate = copy.deepcopy(valid_handoff(True, False, False))
            candidate["transports"][0]["requestedUrl"] = (
                "https://example.com/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027"
            )
            candidate.pop("handoffSha256")
            candidate["handoffSha256"] = HANDOFF.sha256_json(candidate)
            write_handoff(handoff_path, candidate)
            INGEST.STATE = root / "state.json"
            INGEST.fetch = lambda *args, **kwargs: self.fail("origin drift must not fetch")
            result = INGEST.ingest_mysmis(handoff_path)
            self.assertFalse(result["ok"])
            self.assertEqual(result["transportGate"], "HANDOFF_INVALID_FAIL_CLOSED")

    def test_canonical_http_failure_preserves_lkg_without_alternate_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff_path = root / "handoff.json"
            write_handoff(handoff_path, valid_handoff(True, True, True))
            INGEST.STATE = root / "state.json"
            calls: list[str] = []

            def fail_fetch(url: str, timeout=12, max_bytes=3_000_000):
                calls.append(url)
                raise OSError("simulated canonical read failure")

            INGEST.fetch = fail_fetch
            result = INGEST.ingest_mysmis(handoff_path)
            self.assertFalse(result["ok"])
            self.assertTrue(result["preserved"])
            self.assertEqual(result["transportGate"], "CANONICAL_ACQUISITION_FAILED")
            self.assertEqual(calls, [INGEST.MYSMIS])

    def test_missing_handoff_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            INGEST.STATE = root / "state.json"
            INGEST.fetch = lambda *args, **kwargs: self.fail("missing handoff must not fetch")
            result = INGEST.ingest_mysmis(root / "missing.json")
            self.assertFalse(result["ok"])
            self.assertTrue(result["preserved"])
            self.assertEqual(result["transportGate"], "HANDOFF_INVALID_FAIL_CLOSED")


if __name__ == "__main__":
    unittest.main()
