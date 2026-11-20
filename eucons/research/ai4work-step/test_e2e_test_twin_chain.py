from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
import uuid
from pathlib import Path

import nf06_preingest as NF06
from http_endpoint import handle_request
from research_storage import SQLiteResearchStorage
from runtime import load_contract
from test_runtime import adult_payload, employer_payload


SUBMIT_PATH = "/research/ai4work/v1/submit"
ADULT_CHANNEL = "CH-ADULT001"
EMPLOYER_CHANNEL = "CH-EMPLOY01"
CHANNEL_REGISTER_SHA = "b" * 64


def enabled_reference_contract() -> dict:
    """Enable only the transport-neutral reference adapter inside this test.

    The committed production contract remains disabled. This helper never binds
    a web server, provider account, production credential or CRM.
    """
    contract = dict(load_contract())
    contract["production_enabled"] = True
    return contract


def browser_like_body(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def browser_like_headers(key: str, channel_id: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json; charset=utf-8",
        "X-AI4WORK-Idempotency-Key": key,
        "X-AI4WORK-Recruitment-Channel": channel_id,
    }


def submit(payload: dict, store: SQLiteResearchStorage, channel_id: str) -> tuple[int, dict[str, str], bytes]:
    return handle_request(
        method="POST",
        path=SUBMIT_PATH,
        headers=browser_like_headers(str(uuid.uuid4()), channel_id),
        body=browser_like_body(payload),
        store=store,
        contract=enabled_reference_contract(),
    )


def test_twin_frame(records: list[dict]) -> tuple[dict, bytes]:
    source_bytes = NF06.canonical_export_bytes(records)
    received_at = sorted(record["received_at"] for record in records)
    frame = {
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "collection_frame_id": "AI4WORK-CF-TEST-E2E-001",
        "frame_status": "TEST_TWIN_ONLY",
        "evidence_class": "TEST_TWIN_NON_EVIDENCE",
        "instrument_versions": {
            "AI4WORK_ADULTS_V1": 1,
            "AI4WORK_EMPLOYERS_V1": 1,
        },
        **NF06.instrument_definition_hashes(),
        "collection_started_at": received_at[0],
        "collection_closed_at": received_at[-1],
        "collection_channels": [ADULT_CHANNEL, EMPLOYER_CHANNEL],
        "collection_channel_register_sha256": CHANNEL_REGISTER_SHA,
        "source_system": "eucons.ro",
        "source_export_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "direct_identifiers_collected": False,
        "crm_linkage": "FORBIDDEN",
        "commercial_tracking": "FORBIDDEN",
        "storage_class": "RESEARCH_ONLY_SEPARATE_FROM_CRM",
    }
    return frame, source_bytes


class EndToEndTestTwinChain(unittest.TestCase):
    def test_browser_http_isolated_store_export_to_nf06_test_twin_is_non_evidence(self):
        """Exercise the complete repository-level chain without creating evidence.

        The HTTP/store portion runs only through the local reference adapter and
        isolated SQLite test store. Its exported normalized records are copied
        into a separately labelled synthetic TEST TWIN batch before NF06
        pre-ingest. Rights-held records must be absent from export. The synthetic
        batch remains permanently NON_EVIDENCE and must fail PROD promotion.
        """
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "ai4work-test-twin-chain.sqlite")

            adult_response = submit(adult_payload(), store, ADULT_CHANNEL)
            employer_response = submit(employer_payload(), store, EMPLOYER_CHANNEL)
            self.assertEqual(adult_response[0], 201)
            self.assertEqual(employer_response[0], 201)

            adult_receipt = json.loads(adult_response[2].decode("utf-8"))["response_id"]
            self.assertTrue(store.set_analysis_hold(adult_receipt, "OBJECTED_PENDING_REVIEW"))
            held_export = (
                store.export("AI4WORK_ADULTS_V1")
                + store.export("AI4WORK_EMPLOYERS_V1")
            )
            self.assertEqual(len(held_export), 1)
            self.assertEqual(held_export[0]["form_id"], "AI4WORK_EMPLOYERS_V1")
            self.assertNotEqual(held_export[0]["response_id"], adult_receipt)

            self.assertTrue(store.clear_analysis_hold(adult_receipt))
            exported_real_shape = (
                store.export("AI4WORK_ADULTS_V1")
                + store.export("AI4WORK_EMPLOYERS_V1")
            )
            self.assertEqual(len(exported_real_shape), 2)
            self.assertTrue(all(record["synthetic"] is False for record in exported_real_shape))
            self.assertEqual(
                {record["recruitment_channel_id"] for record in exported_real_shape},
                {ADULT_CHANNEL, EMPLOYER_CHANNEL},
            )

            # TEST TWIN is a distinct derived fixture, never the stored reference rows.
            test_twin_records = copy.deepcopy(exported_real_shape)
            for record in test_twin_records:
                record["synthetic"] = True

            frame, source_bytes = test_twin_frame(test_twin_records)
            manifest = NF06.build_preingest_manifest(
                test_twin_records,
                collection_frame=frame,
                source_bytes=source_bytes,
                prod=False,
            )

            self.assertEqual(manifest["handoff_stage"], "NF06_SOURCE_PREFLIGHT")
            self.assertEqual(manifest["evidence_class"], "TEST_TWIN_NON_EVIDENCE")
            self.assertTrue(manifest["non_evidence"])
            self.assertFalse(manifest["prod_promotion_eligible"])
            self.assertEqual(manifest["record_count"], 2)
            self.assertEqual(manifest["form_counts"]["AI4WORK_ADULTS_V1"], 1)
            self.assertEqual(manifest["form_counts"]["AI4WORK_EMPLOYERS_V1"], 1)
            self.assertEqual(manifest["channel_counts"], {ADULT_CHANNEL: 1, EMPLOYER_CHANNEL: 1})
            self.assertEqual(manifest["dominant_channel_share"], 0.5)
            self.assertEqual(manifest["source_export_sha256"], hashlib.sha256(source_bytes).hexdigest())
            self.assertTrue(manifest["instrument_content_hashes_validated"])
            self.assertEqual(manifest["form_contract_sha256"], frame["form_contract_sha256"])
            self.assertEqual(manifest["forms_definition_sha256"], frame["forms_definition_sha256"])

            rendered_manifest = NF06.manifest_json_bytes(manifest).decode("utf-8")
            self.assertNotIn("Pregătirea rapidă", rendered_manifest)
            self.assertNotIn("Lipsa unei metode", rendered_manifest)

            # The exact same synthetic batch must never cross the PROD gate.
            prod_like_frame = dict(frame)
            prod_like_frame.update(
                {
                    "collection_frame_id": "AI4WORK-CF-INVALID-PROD-FROM-TWIN",
                    "frame_status": "APPROVED_FOR_PROD",
                    "evidence_class": "PROD_REAL_EVIDENCE",
                    "privacy_notice_version": "INVALID-TEST-ONLY",
                    "controller_determination_reference": "INVALID-TEST-ONLY",
                    "controller_approval_reference": "INVALID-TEST-ONLY",
                    "processor_binding_reference": "INVALID-TEST-ONLY",
                    "server_log_profile_reference": "INVALID-TEST-ONLY",
                    "retention_schedule_reference": "INVALID-TEST-ONLY",
                    "production_store_binding_reference": "INVALID-TEST-ONLY",
                }
            )
            with self.assertRaises(NF06.NF06PreingestError):
                NF06.build_preingest_manifest(
                    test_twin_records,
                    collection_frame=prod_like_frame,
                    source_bytes=source_bytes,
                    prod=True,
                )


if __name__ == "__main__":
    unittest.main()