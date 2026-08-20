import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import engine


class EvidenceMatchingTests(unittest.TestCase):
    def test_school_offer_does_not_close_school_practice_quality_gap(self):
        claim = {
            "id": "C1",
            "scope": "school",
            "construct": "practice_quality",
            "requires_direct_local": True,
            "priority": True,
            "gap_type": "practice_quality",
            "evidence_ids": ["E-OFFER"],
        }
        evidence = {
            "E-OFFER": {
                "scope": "school",
                "constructs": ["qualification_offer"],
                "direct_measurement": True,
            }
        }
        gaps = engine.detect_evidence_gaps([claim], evidence)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["construct"], "practice_quality")

    def test_matching_direct_school_measurement_closes_gap(self):
        claim = {
            "id": "C1",
            "scope": "school",
            "construct": "career_intention",
            "requires_direct_local": True,
            "priority": True,
            "gap_type": "career_intention",
            "evidence_ids": ["E-SURVEY"],
        }
        evidence = {
            "E-SURVEY": {
                "scope": "school",
                "constructs": ["career_intention"],
                "direct_measurement": True,
            }
        }
        self.assertEqual(engine.detect_evidence_gaps([claim], evidence), [])

    def test_indirect_school_document_does_not_close_direct_gap(self):
        claim = {
            "id": "C1",
            "scope": "school",
            "construct": "skills_baseline",
            "requires_direct_local": True,
            "priority": True,
            "gap_type": "skills_baseline",
            "evidence_ids": ["E-DOC"],
        }
        evidence = {
            "E-DOC": {
                "scope": "school",
                "constructs": ["skills_baseline"],
                "direct_measurement": False,
            }
        }
        self.assertEqual(len(engine.detect_evidence_gaps([claim], evidence)), 1)


if __name__ == "__main__":
    unittest.main()
