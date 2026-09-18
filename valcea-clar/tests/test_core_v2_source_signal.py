import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from source_signal import normalize_canonical_candidate


class SourceSignalBoundaryTest(unittest.TestCase):
    def test_title_date_only_becomes_no_story(self):
        row = {
            "id": "sig-1",
            "headline": "Anunț",
            "paragraphs": [],
            "material_fact_gate": "HOLD_TITLE_DATE_ONLY",
            "reader_facing_copy_authorized": False,
            "sources": [{"name": "IPJ", "url": "https://example.org/x", "tier": "T1"}],
        }
        result = normalize_canonical_candidate("ipj_valcea", row)
        self.assertFalse(result.material_signal)
        self.assertEqual(result.terminal, "NO_STORY")
        self.assertIn("HOLD_TITLE_DATE_ONLY", result.reason)

    def test_full_material_candidate_crosses_signal_boundary_only(self):
        row = {
            "id": "sig-2",
            "headline": "Schimbare materială",
            "paragraphs": ["Detaliu verificat suficient pentru a continua spre kernel."],
            "material_fact_gate": "PASS",
            "reader_facing_copy_authorized": True,
            "confidence": 96,
            "sources": [{"name": "APAVIL", "url": "https://example.org/y", "tier": "T1"}],
        }
        result = normalize_canonical_candidate("apavil", row)
        self.assertTrue(result.material_signal)
        self.assertIsNone(result.terminal)
        self.assertEqual(result.confidence, 96)

    def test_nonpilot_source_fails_closed(self):
        row = {
            "id": "sig-x",
            "headline": "X",
            "paragraphs": ["x"],
            "material_fact_gate": "PASS",
            "sources": [{"url": "https://example.org/x"}],
        }
        with self.assertRaises(ValueError):
            normalize_canonical_candidate("unknown_source", row)


if __name__ == "__main__":
    unittest.main()
