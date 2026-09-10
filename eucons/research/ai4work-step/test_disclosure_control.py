from __future__ import annotations

import unittest

from disclosure_control import (
    DisclosureControlError,
    assert_public_table_safe,
    build_public_count_table,
)


class DisclosureControlTests(unittest.TestCase):
    def test_single_small_cell_triggers_complementary_suppression(self):
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
                    "status": "SUPPRESSED_COMPLEMENTARY",
                    "n": None,
                    "display_n": "SUPPRESSED",
                    "minimum_n": 5,
                },
            ],
        )
        assert_public_table_safe(cells)

    def test_multiple_primary_suppressions_do_not_need_secondary_for_grand_total(self):
        records = [
            {"region": "Centru"},
            {"region": "Centru"},
            {"region": "Sud-Muntenia"},
            {"region": "Sud-Muntenia"},
            {"region": "Sud-Muntenia"},
            {"region": "Sud-Vest Oltenia"},
            {"region": "Sud-Vest Oltenia"},
            {"region": "Sud-Vest Oltenia"},
            {"region": "Sud-Vest Oltenia"},
            {"region": "Sud-Vest Oltenia"},
        ]
        cells = build_public_count_table(records, dimensions=["region"])
        by_region = {cell["region"]: cell for cell in cells}
        self.assertEqual(by_region["Centru"]["status"], "SUPPRESSED_SMALL_CELL")
        self.assertEqual(by_region["Sud-Muntenia"]["status"], "SUPPRESSED_SMALL_CELL")
        self.assertEqual(by_region["Sud-Vest Oltenia"]["status"], "RELEASABLE")
        self.assertEqual(by_region["Sud-Vest Oltenia"]["n"], 5)
        assert_public_table_safe(cells)

    def test_multi_dimension_cells_apply_same_threshold_and_secondary_suppression(self):
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
        self.assertEqual(by_size["1-9"]["status"], "SUPPRESSED_COMPLEMENTARY")
        self.assertIsNone(by_size["1-9"]["n"])
        self.assertEqual(by_size["10-49"]["status"], "SUPPRESSED_SMALL_CELL")
        self.assertIsNone(by_size["10-49"]["n"])
        assert_public_table_safe(cells)

    def test_secondary_suppression_prefers_smallest_releasable_cell(self):
        records = (
            [{"region": "Centru"}] * 2
            + [{"region": "Sud-Muntenia"}] * 5
            + [{"region": "Sud-Vest Oltenia"}] * 9
        )
        cells = build_public_count_table(records, dimensions=["region"])
        by_region = {cell["region"]: cell for cell in cells}
        self.assertEqual(by_region["Centru"]["status"], "SUPPRESSED_SMALL_CELL")
        self.assertEqual(by_region["Sud-Muntenia"]["status"], "SUPPRESSED_COMPLEMENTARY")
        self.assertEqual(by_region["Sud-Vest Oltenia"]["status"], "RELEASABLE")
        self.assertEqual(by_region["Sud-Vest Oltenia"]["n"], 9)
        assert_public_table_safe(cells)

    def test_single_populated_small_cell_fails_closed_if_grand_total_is_protected(self):
        with self.assertRaisesRegex(DisclosureControlError, "grand-total-safe release impossible"):
            build_public_count_table([{"region": "Centru"}] * 3, dimensions=["region"])

        cells = build_public_count_table(
            [{"region": "Centru"}] * 3,
            dimensions=["region"],
            protect_grand_total=False,
        )
        self.assertEqual(cells[0]["status"], "SUPPRESSED_SMALL_CELL")
        assert_public_table_safe(cells, protect_grand_total=False)

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

    def test_mutated_suppressed_releasable_or_complementary_cells_fail_closed(self):
        with self.assertRaisesRegex(DisclosureControlError, "suppressed cell exposes exact n"):
            assert_public_table_safe(
                [
                    {
                        "region": "Centru",
                        "status": "SUPPRESSED_SMALL_CELL",
                        "n": 3,
                        "display_n": "<5",
                    },
                    {
                        "region": "Sud-Muntenia",
                        "status": "SUPPRESSED_COMPLEMENTARY",
                        "n": None,
                        "display_n": "SUPPRESSED",
                    },
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
        with self.assertRaisesRegex(DisclosureControlError, "complementary suppressed cell exposes exact n"):
            assert_public_table_safe(
                [
                    {
                        "region": "Centru",
                        "status": "SUPPRESSED_SMALL_CELL",
                        "n": None,
                        "display_n": "<5",
                    },
                    {
                        "region": "Sud-Muntenia",
                        "status": "SUPPRESSED_COMPLEMENTARY",
                        "n": 5,
                        "display_n": "SUPPRESSED",
                    },
                ]
            )

    def test_single_primary_suppression_without_complementary_is_rejected(self):
        with self.assertRaisesRegex(DisclosureControlError, "reconstructable"):
            assert_public_table_safe(
                [
                    {
                        "region": "Centru",
                        "status": "SUPPRESSED_SMALL_CELL",
                        "n": None,
                        "display_n": "<5",
                    },
                    {
                        "region": "Sud-Muntenia",
                        "status": "RELEASABLE",
                        "n": 10,
                        "display_n": "10",
                    },
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
