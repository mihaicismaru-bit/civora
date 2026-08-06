import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.models import Source, Signal, FactKernel, StoryObject, StoryState
from civora.registry import SourceRegistry
from civora.ingestion import SignalStore
from civora.review import ReviewQueue
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

    def test_blocked_story_enters_review_queue(self):
        with TemporaryDirectory() as td:
            source = Source("Anonim", "social", ["Vâlcea"], .1, .1, .5, .2, .1, .9)
            signal = Signal("Zvon neverificat", "Afirmație fără dovezi.", ["Vâlcea"], [source.id], .7, .7, .8, .2, .95)
            kernel = FactKernel([], ["Afirmația principală"], [], None, [])
            story = StoryObject(signal=signal, fact_kernel=kernel)
            queue = ReviewQueue(Path(td) / "review.json")
            result = Orchestrator(Path(td) / "state", queue).run(story, {source.id: source})
            self.assertEqual(result.state, StoryState.BLOCKED)
            self.assertEqual(len(queue.pending()), 1)


if __name__ == "__main__":
    unittest.main()
