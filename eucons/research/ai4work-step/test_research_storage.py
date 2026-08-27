import tempfile
import unittest
from pathlib import Path

from research_storage import ResearchStorageError, SQLiteResearchStorage, canonical_json_bytes


def record(response_id="r-1", form_id="AI4WORK_ADULTS_V1", synthetic=False):
    return {
        "schema_version": 1,
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "form_id": form_id,
        "form_version": 1,
        "response_id": response_id,
        "received_at": "2026-08-26T14:00:00+00:00",
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
