#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
INGEST = HERE.parent / "ingest"
sys.path.insert(0, str(INGEST))

from eu_direct_ft_programme_taxonomy import (  # noqa: E402
    build_taxonomy_receipt,
    normalize_programme_family,
    validate_taxonomy_receipt,
)


def source_watch():
    records = [
        ("HORIZON-EIC-2026-TEST-01", "Horizon Europe (HORIZON)"),
        ("LIFE-2026-TEST", "Programme for the Environment and Climate Action (LIFE)"),
        ("CEF-T-2026-TEST", "Connecting Europe Facility (CEF)"),
        ("DIGITAL-2026-TEST", "Digital Europe Programme (DIGITAL)"),
        ("SMP-2026-TEST", "Single Market Programme (SMP)"),
        ("RFCS-2026-TEST", "Research Fund for Coal & Steel (RFCS)"),
    ]
    return {
        "schema": "PARTENER_EU_FT_PROGRAMME_COVERAGE_WATCH_V1",
        "source_family": "EU_DIRECT",
        "programme_family": "BRUSSELS",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "fetched_at": "2026-09-01T15:00:00+00:00",
        "run_id": "RUN-1",
        "records": [
            {
                "identifier": identifier,
                "call_identifier": identifier.rsplit("-", 1)[0],
                "programme_reference": f"P-{idx}",
                "programme_label": label,
                "status_label_candidate": "Open",
                "authority_url_candidate": f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{identifier}",
                "semantic_fingerprint": str(idx) * 64,
                "dedup_key": str(idx + 1) * 64,
            }
            for idx, (identifier, label) in enumerate(records, start=1)
        ],
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "canonical_corpus_mutation": False,
        "publication_effect": "NONE",
    }


class ProgrammeTaxonomyTests(unittest.TestCase):
    def test_required_programme_labels_normalize(self):
        self.assertEqual(normalize_programme_family("Horizon Europe (HORIZON)"), "HORIZON_EUROPE")
        self.assertEqual(normalize_programme_family("Digital Europe Programme (DIGITAL)"), "DIGITAL_EUROPE")
        self.assertEqual(normalize_programme_family("Programme for the Environment and Climate Action (LIFE)"), "LIFE")
        self.assertEqual(normalize_programme_family("Citizens, Equality, Rights and Values Programme (CERV)"), "CERV")
        self.assertEqual(normalize_programme_family("Single Market Programme (SMP)"), "SINGLE_MARKET_PROGRAMME")
        self.assertEqual(normalize_programme_family("Connecting Europe Facility (CEF)"), "CEF")
        self.assertEqual(normalize_programme_family("Creative Europe Programme (CREA)"), "CREATIVE_EUROPE")
        self.assertEqual(normalize_programme_family("European Solidarity Corps (ESC)"), "EUROPEAN_SOLIDARITY_CORPS")

    def test_receipt_corrects_life_and_marks_eic_as_instrument(self):
        source = source_watch()
        receipt = build_taxonomy_receipt(source)
        validate_taxonomy_receipt(receipt, source)
        self.assertEqual(receipt["programme_family_counts"]["LIFE"], 1)
        self.assertEqual(receipt["programme_family_counts"]["HORIZON_EUROPE"], 1)
        self.assertEqual(receipt["instrument_family_counts"], {"EIC": 1})
        horizon = next(r for r in receipt["records"] if r["identifier"].startswith("HORIZON-EIC"))
        self.assertEqual(horizon["instrument_family_normalized"], "EIC")
        self.assertFalse(horizon["open_call_authorized"])

    def test_unmapped_official_programme_becomes_research_watch(self):
        source = source_watch()
        receipt = build_taxonomy_receipt(source)
        self.assertEqual(receipt["stats"]["other_eu_direct_count"], 1)
        self.assertEqual(receipt["stats"]["unmapped_official_programme_labels"], 1)
        self.assertEqual(receipt["research_watchlist"][0]["official_programme_label"], "Research Fund for Coal & Steel (RFCS)")
        self.assertEqual(receipt["research_watchlist"][0]["state"], "PROGRAMME_FIT_RESEARCH_WATCH_NON_AUTHORIZING")
        self.assertFalse(receipt["research_watchlist"][0]["open_call_authorized"])

    def test_receipt_remains_non_authorizing(self):
        source = source_watch()
        receipt = build_taxonomy_receipt(source)
        validate_taxonomy_receipt(receipt, source)
        for key in (
            "material_fact_use", "open_call_authorized", "deadline_authorized", "budget_authorized",
            "eligibility_authorized", "publish_authorized", "distribution_authorized", "call_alert_authorized",
            "canonical_corpus_mutation",
        ):
            self.assertFalse(receipt[key])
        self.assertEqual(receipt["publication_effect"], "NONE")

    def test_hash_binding_rejects_mutated_source(self):
        source = source_watch()
        receipt = build_taxonomy_receipt(source)
        mutated = json.loads(json.dumps(source))
        mutated["records"][0]["programme_label"] = "Something Else"
        with self.assertRaisesRegex(ValueError, "not bound"):
            validate_taxonomy_receipt(receipt, mutated)

    def test_upstream_self_authorization_fails_closed(self):
        source = source_watch()
        source["publish_authorized"] = True
        with self.assertRaisesRegex(ValueError, "unsafe upstream watch authorization"):
            build_taxonomy_receipt(source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
