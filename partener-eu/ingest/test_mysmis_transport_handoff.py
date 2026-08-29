#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "mysmis_transport_handoff", HERE / "mysmis_transport_handoff.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def row(role: str, ok: bool, semantic: str = "a" * 64) -> dict:
    host = {
        "CANONICAL_PRIMARY": "reporting.mysmis2021.gov.ro",
        "OFFICIAL_RESOURCES": "resurse.mysmis2021.gov.ro",
        "OFFICIAL_DWH_LEGACY": "dwh4smis.fonduri-ue.ro",
    }[role]
    value = {
        "role": role,
        "requestedUrl": f"https://{host}/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027",
        "authorityClass": "T1_OFFICIAL_MYSMIS_REPORTING",
        "sourceFamily": "ROMANIA_MIPE_MYSMIS",
        "programmeFamily": "MULTI_PROGRAMME_2021_2027",
        "observationState": "REPORT_TRANSPORT_DIAGNOSTIC",
        "parserVersion": "MYSMIS_REPORTING_TRANSPORT_SCOUT_V2",
        "materialFactUse": False,
        "openCallAuthorized": False,
        "publishAuthorized": False,
        "deadlineAuthorized": False,
        "budgetAuthorized": False,
        "eligibilityAuthorized": False,
        "ok": ok,
        "fetchedAt": "2026-08-29T17:30:00+00:00",
    }
    if ok:
        value.update(
            {
                "finalUrl": value["requestedUrl"],
                "rawSha256": "b" * 64,
                "semanticSha256": semantic,
                "validatedCallCount": 909,
                "visibleRowCount": 49,
                "explicitStatuses": ["FINALIZAT"],
            }
        )
    else:
        value["error"] = "URLError: simulated canonical transport failure"
    return value


def matrix(primary_ok: bool, resources_ok: bool, dwh_ok: bool) -> dict:
    transports = [
        row("CANONICAL_PRIMARY", primary_ok),
        row("OFFICIAL_RESOURCES", resources_ok),
        row("OFFICIAL_DWH_LEGACY", dwh_ok),
    ]
    available_alternates = resources_ok or dwh_ok
    return {
        "schema": "CIVORA_MYSMIS_REPORTING_TRANSPORT_MATRIX_V2",
        "observedAt": "2026-08-29T17:30:00+00:00",
        "runId": "regression-run",
        "parserVersion": "MYSMIS_REPORTING_TRANSPORT_SCOUT_V2",
        "canonicalIdentity": MODULE.CANONICAL_IDENTITY,
        "authorityClass": "T1_OFFICIAL_MYSMIS_REPORTING",
        "sourceFamily": "ROMANIA_MIPE_MYSMIS",
        "programmeFamily": "MULTI_PROGRAMME_2021_2027",
        "observationState": "REPORT_TRANSPORT_DIAGNOSTIC",
        "materialFactUse": False,
        "openCallAuthorized": False,
        "publishAuthorized": False,
        "transports": transports,
        "comparison": {
            "state": "CANONICAL_PRIMARY_ONLY" if primary_ok else (
                "ALTERNATES_ONLY_DISCOVERY"
                if available_alternates
                else "NO_OFFICIAL_REPORT_TRANSPORT_AVAILABLE"
            ),
            "canonicalPrimaryAvailable": primary_ok,
            "alternateAvailability": {
                "OFFICIAL_RESOURCES": resources_ok,
                "OFFICIAL_DWH_LEGACY": dwh_ok,
            },
            "alignedWithCanonical": [],
            "divergentFromCanonical": [],
            "alternatePairSemanticallyAligned": resources_ok and dwh_ok,
            "alternateEligibleForDiscoveryOnly": available_alternates,
            "alternateAuthorizedForMaterialFacts": False,
            "openCallAuthorized": False,
            "publishAuthorized": False,
            "requiresSemanticReconciliation": available_alternates and not primary_ok,
            "missingForMaterialFallback": ["exact-call evidence", "semantic reconciliation"],
        },
    }


class MySMISTransportHandoffTests(unittest.TestCase):
    def test_alternate_only_is_evidence_not_material_fallback(self) -> None:
        handoff = MODULE.build_handoff(
            matrix(False, True, False),
            observed_at="2026-08-29T17:31:00+00:00",
            run_id="test-alternate-only",
        )
        self.assertFalse(handoff["canonicalPrimaryAvailable"])
        self.assertTrue(handoff["alternateEvidenceAvailable"])
        self.assertTrue(handoff["requiresSemanticReconciliation"])
        self.assertFalse(handoff["materialFactUse"])
        self.assertFalse(handoff["openCallAuthorized"])
        self.assertFalse(handoff["publishAuthorized"])
        self.assertEqual(handoff["materialChanges"], [])
        self.assertEqual(handoff["publicationEffect"], "NONE")
        self.assertEqual(handoff["canonicalIdentity"], MODULE.CANONICAL_IDENTITY)

    def test_primary_available_is_still_non_authorizing_transport_evidence(self) -> None:
        handoff = MODULE.build_handoff(
            matrix(True, True, True),
            observed_at="2026-08-29T17:31:00+00:00",
            run_id="test-primary",
        )
        self.assertTrue(handoff["canonicalPrimaryAvailable"])
        self.assertTrue(handoff["alternateEvidenceAvailable"])
        self.assertFalse(handoff["materialFactUse"])
        self.assertFalse(handoff["publishAuthorized"])
        MODULE.validate_handoff(handoff)

    def test_authority_escalation_in_matrix_is_rejected(self) -> None:
        candidate = matrix(False, True, False)
        candidate["comparison"]["alternateAuthorizedForMaterialFacts"] = True
        with self.assertRaises(ValueError):
            MODULE.build_handoff(candidate)

    def test_transport_row_authority_escalation_is_rejected(self) -> None:
        candidate = matrix(True, False, False)
        candidate["transports"][0]["openCallAuthorized"] = True
        with self.assertRaises(ValueError):
            MODULE.build_handoff(candidate)

    def test_external_https_requested_url_is_rejected(self) -> None:
        candidate = matrix(False, True, False)
        candidate["transports"][1]["requestedUrl"] = (
            "https://example.com/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027"
        )
        with self.assertRaises(ValueError):
            MODULE.build_handoff(candidate)

    def test_cross_role_official_host_swap_is_rejected(self) -> None:
        candidate = matrix(False, True, False)
        candidate["transports"][1]["requestedUrl"] = candidate["transports"][2]["requestedUrl"]
        with self.assertRaises(ValueError):
            MODULE.build_handoff(candidate)

    def test_successful_final_url_role_drift_is_rejected(self) -> None:
        candidate = matrix(False, True, False)
        candidate["transports"][1]["finalUrl"] = (
            "https://dwh4smis.fonduri-ue.ro"
            "/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027"
        )
        with self.assertRaises(ValueError):
            MODULE.build_handoff(candidate)

    def test_row_provenance_drift_is_rejected(self) -> None:
        candidate = matrix(False, True, False)
        candidate["transports"][1]["authorityClass"] = "T1_MATERIAL_CALL_AUTHORITY"
        with self.assertRaises(ValueError):
            MODULE.build_handoff(candidate)

    def test_top_level_provenance_drift_is_rejected(self) -> None:
        candidate = matrix(False, True, False)
        candidate["sourceFamily"] = "UNTRUSTED_SOURCE"
        with self.assertRaises(ValueError):
            MODULE.build_handoff(candidate)

    def test_comparison_availability_drift_is_rejected(self) -> None:
        candidate = matrix(False, True, False)
        candidate["comparison"]["alternateAvailability"]["OFFICIAL_RESOURCES"] = False
        with self.assertRaises(ValueError):
            MODULE.build_handoff(candidate)

    def test_non_hex_digest_is_rejected(self) -> None:
        candidate = matrix(True, False, False)
        candidate["transports"][0]["rawSha256"] = "z" * 64
        with self.assertRaises(ValueError):
            MODULE.build_handoff(candidate)

    def test_handoff_digest_detects_mutation(self) -> None:
        handoff = MODULE.build_handoff(
            matrix(False, True, False),
            observed_at="2026-08-29T17:31:00+00:00",
            run_id="test-digest",
        )
        mutated = copy.deepcopy(handoff)
        mutated["availableTransportRoles"].append("UNTRUSTED")
        with self.assertRaises(ValueError):
            MODULE.validate_handoff(mutated)

    def test_handoff_rejects_rehashed_role_origin_drift(self) -> None:
        handoff = MODULE.build_handoff(
            matrix(False, True, False),
            observed_at="2026-08-29T17:31:00+00:00",
            run_id="test-rehashed-origin-drift",
        )
        mutated = copy.deepcopy(handoff)
        mutated["transports"][1]["requestedUrl"] = (
            "https://example.com/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027"
        )
        mutated.pop("handoffSha256")
        mutated["handoffSha256"] = MODULE.sha256_json(mutated)
        with self.assertRaises(ValueError):
            MODULE.validate_handoff(mutated)

    def test_write_is_create_only_for_replay_evidence(self) -> None:
        handoff = MODULE.build_handoff(
            matrix(False, True, False),
            observed_at="2026-08-29T17:31:00+00:00",
            run_id="test-immutable",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "handoff.json"
            MODULE.write_immutable(path, handoff)
            self.assertTrue(path.exists())
            with self.assertRaises(FileExistsError):
                MODULE.write_immutable(path, handoff)


if __name__ == "__main__":
    unittest.main()
