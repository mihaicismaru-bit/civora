from __future__ import annotations

import unittest

from disclosure_control import (
    DisclosureControlError,
    assert_public_table_safe,
    build_public_count_table,
)


class DisclosureControlTests(unittest.TestCase):
    def test_small_cells_are_suppressed_without_exact_count(self):
        records = [
            {"region": "Centru"},
            {"region": "Centru"},
            {"region": "Centru"},
            {"region": "Sud-Muntenia"},
            {"region": "Sud-Muntenia"},
            {"region": "Sud-Muntenia"},
            {"region": "Sud-Muntenia"},
            {"region": "Sud-Muntenia"},
        ]

        cells = build_public_count_table(records, dimensions=["region"])
        self.assertEqual(
            cells,
            [
                {
                    "region": "Centru",
                    "status": "SUPPRESSED_SMALL_CELL",
                    "n": None,
                    "display_n": "<5",
                    "minimum_n": 5,
                },
                {
                    "region": "Sud-Muntenia",
                    "status": "RELEASABLE",
                    "n": 5,
                    "display_n": "5",
                    "minimum_n": 5,
                },
            ],
        )
        assert_public_table_safe(cells)

    def test_multi_dimension_cells_apply_same_threshold(self):
        records = [
            {"region": "Centru", "size_band": "1-9"},
            {"region": "Centru", "size_band": "1-9"},
            {"region": "Centru", "size_band": "1-9"},
            {"region": "Centru", "size_band": "1-9"},
            {"region": "Centru", "size_band": "1-9"},
            {"region": "Centru", "size_band": "10-49"},
        ]

        cells = build_public_count_table(records, dimensions=["region", "size_band"])
        by_size = {cell["size_band"]: cell for cell in cells}
        self.assertEqual(by_size["1-9"]["status"], "RELEASABLE")
        self.assertEqual(by_size["1-9"]["n"], 5)
        self.assertEqual(by_size["10-49"]["status"], "SUPPRESSED_SMALL_CELL")
        self.assertIsNone(by_size["10-49"]["n"])
        assert_public_table_safe(cells)

    def test_threshold_cannot_be_weakened_below_contract_floor(self):
        with self.assertRaisesRegex(DisclosureControlError, "cannot be lower than 5"):
            build_public_count_table([{"region": "Centru"}], dimensions=["region"], minimum_n=4)
        with self.assertRaisesRegex(DisclosureControlError, "cannot be lower than 5"):
            assert_public_table_safe([], minimum_n=4)

    def test_missing_or_non_scalar_dimensions_fail_closed(self):
        with self.assertRaisesRegex(DisclosureControlError, "missing disclosure dimension"):
            build_public_count_table([{"region": "Centru"}], dimensions=["region", "status"])
        with self.assertRaisesRegex(DisclosureControlError, "non-scalar disclosure dimension"):
            build_public_count_table([{"region": ["Centru"]}], dimensions=["region"])

    def test_mutated_suppressed_or_releasable_cells_fail_closed(self):
        with self.assertRaisesRegex(DisclosureControlError, "suppressed cell exposes exact n"):
            assert_public_table_safe(
                [
                    {
                        "region": "Centru",
                        "status": "SUPPRESSED_SMALL_CELL",
                        "n": 3,
                        "display_n": "<5",
                    }
                ]
            )
        with self.assertRaisesRegex(DisclosureControlError, "releasable cell is below minimum_n"):
            assert_public_table_safe(
                [
                    {
                        "region": "Centru",
                        "status": "RELEASABLE",
                        "n": 4,
                        "display_n": "4",
                    }
                ]
            )

    def test_no_automatic_semantic_combining_occurs(self):
        records = [
            {"region": "Centru", "occupational_family": "IT/date"},
            {"region": "Centru", "occupational_family": "IT/date"},
            {"region": "Centru", "occupational_family": "administrativ/back-office"},
            {"region": "Centru", "occupational_family": "administrativ/back-office"},
            {"region": "Centru", "occupational_family": "administrativ/back-office"},
        ]
        cells = build_public_count_table(records, dimensions=["region", "occupational_family"])
        self.assertEqual(len(cells), 2)
        self.assertTrue(all(cell["status"] == "SUPPRESSED_SMALL_CELL" for cell in cells))
        self.assertTrue(all(cell["n"] is None for cell in cells))


if __name__ == "__main__":
    unittest.main()
