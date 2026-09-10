from __future__ import annotations

import unittest

import nf06_preingest as NF06
from test_nf06_preingest import ADULT_CHANNEL, EMPLOYER_CHANNEL, collection_frame, normalized_records


class NF06MethodCoverageIntegrationTests(unittest.TestCase):
    def test_preingest_emits_internal_region_and_channel_coverage_without_answers(self):
        records = normalized_records()
        frame, source_bytes = collection_frame(records, prod=True)
        manifest = NF06.build_preingest_manifest(
            records,
            collection_frame=frame,
            source_bytes=source_bytes,
            prod=True,
        )
        self.assertEqual(
            manifest["region_counts"],
            {"Centru": 1, "Sud-Muntenia": 0, "Sud-Vest Oltenia": 1},
        )
        self.assertEqual(
            manifest["form_region_counts"]["AI4WORK_ADULTS_V1"],
            {"Centru": 0, "Sud-Muntenia": 0, "Sud-Vest Oltenia": 1},
        )
        self.assertEqual(
            manifest["form_region_counts"]["AI4WORK_EMPLOYERS_V1"],
            {"Centru": 1, "Sud-Muntenia": 0, "Sud-Vest Oltenia": 0},
        )
        self.assertEqual(manifest["region_channel_ids"]["Centru"], [EMPLOYER_CHANNEL])
        self.assertEqual(manifest["region_channel_ids"]["Sud-Muntenia"], [])
        self.assertEqual(manifest["region_channel_ids"]["Sud-Vest Oltenia"], [ADULT_CHANNEL])
        self.assertEqual(
            manifest["form_region_channel_ids"]["AI4WORK_ADULTS_V1"],
            {"Centru": [], "Sud-Muntenia": [], "Sud-Vest Oltenia": [ADULT_CHANNEL]},
        )
        self.assertEqual(
            manifest["form_region_channel_ids"]["AI4WORK_EMPLOYERS_V1"],
            {"Centru": [EMPLOYER_CHANNEL], "Sud-Muntenia": [], "Sud-Vest Oltenia": []},
        )
        self.assertTrue(manifest["method_coverage_aggregates_emitted"])
        self.assertTrue(manifest["form_audience_channel_provenance_emitted"])
        rendered = NF06.manifest_json_bytes(manifest).decode("utf-8")
        self.assertNotIn("redactare și documente", rendered)
        self.assertNotIn("compliance/verificare documente", rendered)


if __name__ == "__main__":
    unittest.main()
