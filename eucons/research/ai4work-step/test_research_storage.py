import hashlib
import tempfile
import unittest
from pathlib import Path

from research_storage import ResearchStorageError, SQLiteResearchStorage, canonical_json_bytes


def opaque_receipt(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def record(response_id="r-1", form_id="AI4WORK_ADULTS_V1", synthetic=False, channel_id="CH-TEST0001"):
    return {
        "schema_version": 1,
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "form_id": form_id,
        "form_version": 1,
        "response_id": opaque_receipt(response_id),
        "received_at": "2026-08-26T14:00:00+00:00",
        "recruitment_channel_id": channel_id,
        "profile": {"region": "Sud-Vest Oltenia"},
        "answers": {"Q01": 3},
        "synthetic": synthetic,
    }


class StorageTests(unittest.TestCase):
    def test_roundtrip_hash_and_export(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "research.sqlite")
            item = record()
            raw = b'{"source":"eucons-runtime-envelope"}'
            digest = store.append(item, raw_bytes=raw)
            self.assertEqual(len(digest), 64)
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [item])

    def test_duplicate_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "research.sqlite")
            item = record()
            store.append(item, raw_bytes=b"one")
            with self.assertRaises(ResearchStorageError):
                store.append(item, raw_bytes=b"two")

    def test_synthetic_rejected_in_prod_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "research.sqlite")
            with self.assertRaises(ResearchStorageError):
                store.append(record(synthetic=True), raw_bytes=b"synthetic")

    def test_identifier_like_or_noncanonical_response_id_is_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "research.sqlite")
            for value in (
                "person@example.org",
                "+40722123456",
                "receipt-readable-label",
                "A" * 64,
                "f" * 63,
            ):
                item = record()
                item["response_id"] = value
                with self.subTest(value=value), self.assertRaisesRegex(
                    ResearchStorageError,
                    "opaque lowercase SHA-256 hex",
                ):
                    store.append(item, raw_bytes=b"must-not-persist")
            self.assertEqual(
                store.conn.execute("SELECT COUNT(*) FROM research_responses").fetchone()[0],
                0,
            )

    def test_invalid_or_missing_channel_provenance_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "research.sqlite")
            bad = record(channel_id="facebook-campaign-person@example.org")
            with self.assertRaises(ResearchStorageError):
                store.append(bad, raw_bytes=b"bad-channel")
            missing = record("r-2")
            del missing["recruitment_channel_id"]
            with self.assertRaises(ResearchStorageError):
                store.append(missing, raw_bytes=b"missing-channel")

    def test_form_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "research.sqlite")
            adult = record("a-1", "AI4WORK_ADULTS_V1")
            employer = record("e-1", "AI4WORK_EMPLOYERS_V1")
            store.append(adult, raw_bytes=canonical_json_bytes(adult))
            store.append(employer, raw_bytes=canonical_json_bytes(employer))
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [adult])
            self.assertEqual(store.export("AI4WORK_EMPLOYERS_V1"), [employer])


if __name__ == "__main__":
    unittest.main()
