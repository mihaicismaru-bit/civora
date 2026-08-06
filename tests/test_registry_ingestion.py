import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.models import Source, Signal, FactKernel, StoryObject, StoryState
from civora.registry import SourceRegistry, SourceRegistryError
from civora.ingestion import SignalStore, SignalStoreError
from civora.review import ReviewQueue, ReviewQueueError
from civora.orchestrator import Orchestrator


class RegistryIngestionTests(unittest.TestCase):
    def test_registry_persists_and_reloads(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "sources.json"
            registry = SourceRegistry(path)
            source = Source("ISU", "official", ["Vâlcea"], .98, .95, .95, .90, .95, .05)
            registry.upsert(source)
            reloaded = SourceRegistry(path)
            self.assertEqual(reloaded.get(source.id).name, "ISU")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 2)
            self.assertIn("checksum", payload)

    def test_registry_recovers_from_backup(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "sources.json"
            registry = SourceRegistry(path)
            first = Source("ISU", "official", ["Vâlcea"], .98, .95, .95, .90, .95, .05)
            second = Source("Primărie", "official", ["Brezoi"], .95, .90, .90, .85, .90, .08)
            registry.upsert(first)
            registry.upsert(second)
            path.write_text("{corrupt", encoding="utf-8")
            recovered = SourceRegistry(path)
            self.assertTrue(recovered.recovered_from_backup)
            self.assertIsNotNone(recovered.get(first.id))
            self.assertIsNone(recovered.get(second.id))

    def test_registry_fails_closed_when_both_generations_invalid(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "sources.json"
            backup = path.with_suffix(path.suffix + ".bak")
            path.write_text("{}", encoding="utf-8")
            backup.write_text("{}", encoding="utf-8")
            with self.assertRaises(SourceRegistryError):
                SourceRegistry(path)

    def test_ingestion_deduplicates_and_rejects_invalid(self):
        with TemporaryDirectory() as td:
            store = SignalStore(Path(td) / "signals.json")
            raw = {
                "title": "Restricție trafic",
                "summary": "Circulația este restricționată temporar.",
                "geography": ["Râmnicu Vâlcea"],
                "source_ids": ["s1"],
                "public_interest": .8,
            }
            result = store.ingest([raw, dict(raw), {"title": "incomplet"}])
            self.assertEqual(len(result.accepted), 1)
            self.assertEqual(len(result.duplicate_ids), 1)
            self.assertEqual(len(result.rejected), 1)

    def test_signal_store_payload_has_valid_checksum(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "signals.json"
            store = SignalStore(path)
            store.ingest([{
                "title": "Alertă meteo",
                "summary": "Cod galben temporar.",
                "geography": ["Vâlcea"],
                "source_ids": ["s1"],
            }])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(payload["checksum"], SignalStore._checksum(payload))

    def test_corrupt_primary_recovers_from_valid_backup(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "signals.json"
            store = SignalStore(path)
            first = {
                "title": "Prima știre",
                "summary": "Prima versiune.",
                "geography": ["Vâlcea"],
                "source_ids": ["s1"],
            }
            second = {
                "title": "A doua știre",
                "summary": "A doua versiune.",
                "geography": ["Brezoi"],
                "source_ids": ["s2"],
            }
            store.ingest([first])
            store.ingest([second])
            path.write_text("{corrupt", encoding="utf-8")
            recovered = SignalStore(path)
            self.assertTrue(recovered.recovered_from_backup)
            self.assertEqual(len(recovered.records), 1)
            self.assertEqual(next(iter(recovered.records.values()))["title"], "Prima știre")

    def test_corrupt_primary_and_backup_fail_closed(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "signals.json"
            backup = path.with_suffix(path.suffix + ".bak")
            path.write_text("{}", encoding="utf-8")
            backup.write_text("{}", encoding="utf-8")
            with self.assertRaises(SignalStoreError):
                SignalStore(path)

    def test_fingerprint_index_must_reference_existing_signal(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "signals.json"
            payload = {
                "schema_version": 2,
                "signals": {},
                "fingerprints": {"fp": "missing"},
            }
            payload["checksum"] = SignalStore._checksum(payload)
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(SignalStoreError):
                SignalStore(path)

    def test_blocked_story_enters_review_queue(self):
        with TemporaryDirectory() as td:
            source = Source("Anonim", "social", ["Vâlcea"], .1, .1, .5, .2, .1, .9)
            signal = Signal("Zvon neverificat", "Afirmație fără dovezi.", ["Vâlcea"], [source.id], .7, .7, .8, .2, .95)
            kernel = FactKernel([], ["Afirmația principală"], [], None, [])
            story = StoryObject(signal=signal, fact_kernel=kernel)
            queue_path = Path(td) / "review.json"
            queue = ReviewQueue(queue_path)
            result = Orchestrator(Path(td) / "state", queue).run(story, {source.id: source})
            self.assertEqual(result.state, StoryState.BLOCKED)
            self.assertEqual(len(queue.pending()), 1)
            payload = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 2)
            self.assertIn("checksum", payload)

    def test_review_queue_recovers_from_backup(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "review.json"
            queue = ReviewQueue(path)
            source = Source("Anonim", "social", ["Vâlcea"], .1, .1, .5, .2, .1, .9)
            signal = Signal("Zvon", "Afirmație.", ["Vâlcea"], [source.id], .7, .7, .8, .2, .95)
            kernel = FactKernel([], ["Afirmația"], [], None, [])
            first = StoryObject(signal=signal, fact_kernel=kernel)
            second = StoryObject(signal=signal, fact_kernel=kernel)
            queue.enqueue(first, "first")
            queue.enqueue(second, "second")
            path.write_text("{corrupt", encoding="utf-8")
            recovered = ReviewQueue(path)
            self.assertTrue(recovered.recovered_from_backup)
            self.assertEqual(len(recovered.pending()), 1)

    def test_review_queue_fails_closed_when_both_generations_invalid(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "review.json"
            backup = path.with_suffix(path.suffix + ".bak")
            path.write_text("{}", encoding="utf-8")
            backup.write_text("{}", encoding="utf-8")
            with self.assertRaises(ReviewQueueError):
                ReviewQueue(path)


if __name__ == "__main__":
    unittest.main()
