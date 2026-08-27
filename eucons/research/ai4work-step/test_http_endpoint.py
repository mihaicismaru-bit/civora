from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from http_endpoint import handle_request
from research_storage import SQLiteResearchStorage
from runtime import load_contract
from test_runtime import adult_payload, employer_payload


def enabled_contract():
    contract = dict(load_contract())
    contract["production_enabled"] = True
    return contract


def request_body(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def headers(key: str):
    return {
        "Content-Type": "application/json; charset=utf-8",
        "X-AI4WORK-Idempotency-Key": key,
    }


def response_json(response):
    return json.loads(response[2].decode("utf-8"))


class HttpEndpointTests(unittest.TestCase):
    def make_store(self, td):
        return SQLiteResearchStorage(Path(td) / "research.sqlite")

    def test_default_contract_fails_closed_before_storage(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(td)
            response = handle_request(
                method="POST",
                path="/research/ai4work/v1/submit",
                headers=headers(str(uuid.uuid4())),
                body=request_body(adult_payload()),
                store=store,
            )
            self.assertEqual(response[0], 503)
            self.assertEqual(response_json(response)["error"], "research_collection_disabled")
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [])

    def test_real_adult_submission_reaches_isolated_reference_store(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(td)
            response = handle_request(
                method="POST",
                path="/research/ai4work/v1/submit",
                headers=headers(str(uuid.uuid4())),
                body=request_body(adult_payload()),
                store=store,
                contract=enabled_contract(),
            )
            payload = response_json(response)
            self.assertEqual(response[0], 201)
            self.assertTrue(payload["accepted"])
            self.assertTrue(payload["inserted"])
            exported = store.export("AI4WORK_ADULTS_V1")
            self.assertEqual(len(exported), 1)
            self.assertFalse(exported[0]["synthetic"])
            self.assertEqual(exported[0]["response_id"], payload["response_id"])
            self.assertEqual(response[1]["Cache-Control"], "no-store")

    def test_real_employer_submission_is_form_isolated(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(td)
            response = handle_request(
                method="POST",
                path="/research/ai4work/v1/submit",
                headers=headers(str(uuid.uuid4())),
                body=request_body(employer_payload()),
                store=store,
                contract=enabled_contract(),
            )
            self.assertEqual(response[0], 201)
            self.assertEqual(len(store.export("AI4WORK_EMPLOYERS_V1")), 1)
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [])

    def test_retry_same_key_same_body_is_exactly_once(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(td)
            key = str(uuid.uuid4())
            body = request_body(adult_payload())
            first = handle_request(
                method="POST",
                path="/research/ai4work/v1/submit",
                headers=headers(key),
                body=body,
                store=store,
                contract=enabled_contract(),
            )
            second = handle_request(
                method="POST",
                path="/research/ai4work/v1/submit",
                headers=headers(key),
                body=body,
                store=store,
                contract=enabled_contract(),
            )
            first_body = response_json(first)
            second_body = response_json(second)
            self.assertEqual(first[0], 201)
            self.assertEqual(second[0], 200)
            self.assertTrue(first_body["inserted"])
            self.assertFalse(second_body["inserted"])
            self.assertEqual(first_body["response_id"], second_body["response_id"])
            self.assertEqual(first_body["normalized_sha256"], second_body["normalized_sha256"])
            self.assertEqual(len(store.export("AI4WORK_ADULTS_V1")), 1)

    def test_retry_same_key_different_analytical_body_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(td)
            key = str(uuid.uuid4())
            first_payload = adult_payload()
            changed_payload = adult_payload()
            changed_payload["answers"]["Q01"] = 4
            first = handle_request(
                method="POST",
                path="/research/ai4work/v1/submit",
                headers=headers(key),
                body=request_body(first_payload),
                store=store,
                contract=enabled_contract(),
            )
            second = handle_request(
                method="POST",
                path="/research/ai4work/v1/submit",
                headers=headers(key),
                body=request_body(changed_payload),
                store=store,
                contract=enabled_contract(),
            )
            self.assertEqual(first[0], 201)
            self.assertEqual(second[0], 409)
            self.assertEqual(response_json(second)["error"], "idempotency_conflict")
            self.assertEqual(len(store.export("AI4WORK_ADULTS_V1")), 1)

    def test_direct_identifier_is_rejected_before_storage(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(td)
            payload = adult_payload()
            payload["answers"]["Q12"] = "Scrieți-mi la persoana@example.org"
            response = handle_request(
                method="POST",
                path="/research/ai4work/v1/submit",
                headers=headers(str(uuid.uuid4())),
                body=request_body(payload),
                store=store,
                contract=enabled_contract(),
            )
            self.assertEqual(response[0], 422)
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [])

    def test_test_twin_form_cannot_enter_prod_route(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(td)
            payload = adult_payload()
            payload["form_id"] = "AI4WORK_TEST_TWIN"
            response = handle_request(
                method="POST",
                path="/research/ai4work/v1/submit",
                headers=headers(str(uuid.uuid4())),
                body=request_body(payload),
                store=store,
                contract=enabled_contract(),
            )
            self.assertEqual(response[0], 422)
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [])

    def test_missing_or_invalid_transport_contracts_fail_without_storage(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(td)
            body = request_body(adult_payload())
            wrong_method = handle_request(
                method="GET", path="/research/ai4work/v1/submit", headers={}, body=body, store=store,
                contract=enabled_contract(),
            )
            wrong_type = handle_request(
                method="POST", path="/research/ai4work/v1/submit", headers={"Content-Type": "text/plain"},
                body=body, store=store, contract=enabled_contract(),
            )
            missing_key = handle_request(
                method="POST", path="/research/ai4work/v1/submit", headers={"Content-Type": "application/json"},
                body=body, store=store, contract=enabled_contract(),
            )
            self.assertEqual(wrong_method[0], 405)
            self.assertEqual(wrong_type[0], 415)
            self.assertEqual(missing_key[0], 400)
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [])


if __name__ == "__main__":
    unittest.main()
