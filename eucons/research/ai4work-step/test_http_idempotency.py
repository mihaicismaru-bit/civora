import tempfile
import unittest
import uuid
from pathlib import Path

from http_idempotency import IdempotencyError, prepare_http_submission
from research_storage import ResearchStorageError, SQLiteResearchStorage
from runtime import ResearchValidationError
from test_runtime import adult_payload

CHANNEL_ID = "CH-TEST0001"
SECOND_CHANNEL_ID = "CH-TEST0002"


class HttpIdempotencyTests(unittest.TestCase):
    def test_same_key_same_body_replays_without_second_row(self):
        key = str(uuid.uuid4())
        payload = adult_payload()
        first_record, first_body_sha = prepare_http_submission(payload, key, CHANNEL_ID)
        second_record, second_body_sha = prepare_http_submission(payload, key, CHANNEL_ID)
        self.assertEqual(first_record["response_id"], second_record["response_id"])
        self.assertEqual(first_body_sha, second_body_sha)

        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "research.sqlite")
            first_digest, inserted = store.append_idempotent(
                first_record,
                raw_bytes=b"first transport attempt",
                body_sha256=first_body_sha,
            )
            replay_digest, replay_inserted = store.append_idempotent(
                second_record,
                raw_bytes=b"network retry",
                body_sha256=second_body_sha,
            )
            self.assertTrue(inserted)
            self.assertFalse(replay_inserted)
            self.assertEqual(first_digest, replay_digest)
            exported = store.export("AI4WORK_ADULTS_V1")
            self.assertEqual(len(exported), 1)
            self.assertEqual(exported[0]["recruitment_channel_id"], CHANNEL_ID)
            self.assertNotIn("idempotency", str(exported).lower())
            self.assertNotIn("body_sha256", str(exported))

    def test_same_key_different_body_fails_closed(self):
        key = str(uuid.uuid4())
        first_payload = adult_payload()
        second_payload = adult_payload()
        second_payload["answers"]["Q01"] = 4
        first_record, first_body_sha = prepare_http_submission(first_payload, key, CHANNEL_ID)
        second_record, second_body_sha = prepare_http_submission(second_payload, key, CHANNEL_ID)
        self.assertEqual(first_record["response_id"], second_record["response_id"])
        self.assertNotEqual(first_body_sha, second_body_sha)

        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "research.sqlite")
            store.append_idempotent(first_record, raw_bytes=b"first", body_sha256=first_body_sha)
            with self.assertRaises(ResearchStorageError):
                store.append_idempotent(second_record, raw_bytes=b"changed", body_sha256=second_body_sha)
            self.assertEqual(len(store.export("AI4WORK_ADULTS_V1")), 1)

    def test_same_key_different_channel_fails_closed(self):
        key = str(uuid.uuid4())
        first_record, first_body_sha = prepare_http_submission(adult_payload(), key, CHANNEL_ID)
        second_record, second_body_sha = prepare_http_submission(adult_payload(), key, SECOND_CHANNEL_ID)
        self.assertEqual(first_record["response_id"], second_record["response_id"])
        self.assertNotEqual(first_body_sha, second_body_sha)
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "research.sqlite")
            store.append_idempotent(first_record, raw_bytes=b"first", body_sha256=first_body_sha)
            with self.assertRaises(ResearchStorageError):
                store.append_idempotent(second_record, raw_bytes=b"changed-channel", body_sha256=second_body_sha)

    def test_two_keys_same_answers_create_two_distinct_rows(self):
        payload = adult_payload()
        first_record, first_body_sha = prepare_http_submission(payload, str(uuid.uuid4()), CHANNEL_ID)
        second_record, second_body_sha = prepare_http_submission(payload, str(uuid.uuid4()), CHANNEL_ID)
        self.assertNotEqual(first_record["response_id"], second_record["response_id"])
        self.assertEqual(first_body_sha, second_body_sha)

        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "research.sqlite")
            store.append_idempotent(first_record, raw_bytes=b"one", body_sha256=first_body_sha)
            store.append_idempotent(second_record, raw_bytes=b"two", body_sha256=second_body_sha)
            self.assertEqual(len(store.export("AI4WORK_ADULTS_V1")), 2)

    def test_missing_or_non_uuid4_key_is_rejected(self):
        with self.assertRaises(IdempotencyError):
            prepare_http_submission(adult_payload(), "", CHANNEL_ID)
        with self.assertRaises(IdempotencyError):
            prepare_http_submission(adult_payload(), str(uuid.uuid1()), CHANNEL_ID)

    def test_invalid_channel_is_rejected_before_storage(self):
        with self.assertRaises(ResearchValidationError):
            prepare_http_submission(adult_payload(), str(uuid.uuid4()), "utm_source=facebook")

    def test_synthetic_cannot_enter_prod_idempotent_store(self):
        record, body_sha = prepare_http_submission(adult_payload(), str(uuid.uuid4()), CHANNEL_ID)
        record["synthetic"] = True
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "research.sqlite")
            with self.assertRaises(ResearchStorageError):
                store.append_idempotent(record, raw_bytes=b"synthetic", body_sha256=body_sha)


if __name__ == "__main__":
    unittest.main()
