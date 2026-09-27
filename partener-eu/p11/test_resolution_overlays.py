#!/usr/bin/env python3
import copy
import importlib.util
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("apply_resolutions", ROOT / "apply_resolutions.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

FAMI_BUDGETS_RON = {
    "AM41D": 5_000_000,
    "AM22M": 4_430_000,
    "AM22L": 4_430_000,
    "AM22N": 2_000_000,
    "AM11I": 5_250_000,
    "AM11H": 5_250_000,
    "AM2A1G": 3_922_800,
}
FAMI_ADDITIONAL_DEADLINES = {
    "AM1A1A": "2026-10-22T16:00:00+03:00",
    "AM10B": "2027-08-27T16:00:00+03:00",
}
IMFV_ADDITIONAL = {
    "BV1A10": ("2027-07-31T16:00:00+03:00", 283_500_000),
    "BV13C": ("2027-05-29T16:00:00+03:00", 51_422_789),
    "BV20B": ("2027-05-29T16:00:00+03:00", 6_550_000),
}


class ResolutionOverlayTests(unittest.TestCase):
    def test_verified_overlays_preserve_existing_identities_and_add_verified_fami_calls(self):
        base = mod.load(ROOT / "opportunity_bundle.json")
        # Remove already persisted application metadata to make replay explicit.
        base.pop("resolution_application", None)
        resolutions = [mod.load(path) for path in sorted((ROOT / "resolutions").glob("*_resolution.json"))]
        merged = mod.apply(base, resolutions)
        self.assertEqual(
            [row["opportunity_id"] for row in base["opportunities"]],
            [row["opportunity_id"] for row in merged["opportunities"]][: len(base["opportunities"])],
        )
        # Five new verified MAI/FED calls are additive; AM41D v2 replaces the same identity.
        self.assertEqual(len(merged["opportunities"]), 40)
        step = next(row for row in merged["opportunities"] if row["opportunity_id"] == "PEO-STEP-LLL-ADULTI-2026")
        self.assertEqual(step["status"], "OPEN")
        self.assertEqual(step["deadline_at"], "2026-09-30T16:00:00+03:00")
        afir = next(row for row in merged["opportunities"] if row["opportunity_id"] == "afir-energy-2026")
        self.assertEqual(afir["publication_state"], "PUBLISHABLE")
        self.assertEqual(afir["material_facts"]["eligibility"]["technical_scope"]["self_consumption"], "minimum 70% din producția anuală a centralei, utilizată exclusiv de solicitant pentru activități CAEN 01, 10 sau 11 ori de OUAI/FOUAI")
        self.assertNotIn("candidate_material_facts", afir)
        afir_task = next(row for row in merged["resolution_tasks"] if row["resolution_task_id"] == "RT-AFIR-ENERGY-2026-MATERIAL")
        self.assertEqual(afir_task["status"], "RESOLVED")
        regional = next(row for row in merged["opportunities"] if row["opportunity_id"] == "pr-centru-digital-2")
        self.assertEqual(regional["status"], "DISCOVERED")
        self.assertEqual(regional["material_facts"], {})
        self.assertEqual(regional["candidate_material_facts"]["deadline"]["planning_only"]["opens"], "November 2026")
        regional_task = next(row for row in merged["resolution_tasks"] if row["resolution_task_id"] == "RT-PR-CENTRU-DIGITAL-2-MATERIAL")
        self.assertEqual(regional_task["status"], "IN_REVIEW")
        self.assertEqual(set(regional_task["blocked_fact_classes"]), {"status", "deadline", "budget", "grant", "eligibility", "scoring", "beneficiaries"})
        fami = [row for row in merged["opportunities"] if row["opportunity_id"].startswith("mai-fami-")]
        self.assertEqual(len(fami), 9)
        fami_by_code = {row["code"]: row for row in fami}
        for code, budget in FAMI_BUDGETS_RON.items():
            item = fami_by_code[code]
            self.assertEqual(item["status"], "OPEN")
            self.assertEqual(item["publication_state"], "PUBLISHABLE")
            self.assertEqual(item["material_facts"]["deadline"]["closes"], "2026-10-16T16:00:00+03:00")
            self.assertEqual(
                item["material_facts"]["budget"],
                {"amount": budget, "currency": "RON", "basis": "FEN_AVAILABLE_CALL_ALLOCATION"},
            )
            self.assertFalse(item.get("candidate_material_facts"))

        for code, deadline in FAMI_ADDITIONAL_DEADLINES.items():
            item = fami_by_code[code]
            self.assertEqual(item["status"], "OPEN")
            self.assertEqual(item["publication_state"], "PUBLISHABLE")
            self.assertEqual(item["material_facts"]["deadline"]["closes"], deadline)
            self.assertEqual(item["material_facts"]["beneficiaries"], ["Autoritate publică centrală"])
            self.assertNotIn("budget", item["material_facts"])

        imfv_by_code = {
            row["code"]: row
            for row in merged["opportunities"]
            if row["opportunity_id"].startswith("mai-imfv-")
        }
        for code, (deadline, budget) in IMFV_ADDITIONAL.items():
            item = imfv_by_code[code]
            self.assertEqual(item["status"], "OPEN")
            self.assertEqual(item["publication_state"], "PUBLISHABLE")
            self.assertEqual(item["material_facts"]["deadline"]["closes"], deadline)
            self.assertEqual(item["material_facts"]["beneficiaries"], ["Autoritate publică centrală"])
            self.assertEqual(
                item["material_facts"]["budget"],
                {"amount": budget, "currency": "RON", "basis": "FEN_AVAILABLE_CALL_ALLOCATION"},
            )

        am41d = fami_by_code["AM41D"]
        self.assertEqual(am41d["evidence_refs"], ["EV-MAI-FED-AM41D-SIGNED-GUIDE-V2-20260927"])
        self.assertEqual(am41d["material_facts"]["budget"]["cofinancing_rate_percent"], 100)
        self.assertEqual(am41d["material_facts"]["budget"]["fen_percent"], 75)
        self.assertEqual(am41d["material_facts"]["budget"]["fnn_percent"], 25)
        self.assertEqual(
            am41d["material_facts"]["budget"]["maximum_total_eligible_cost_per_operation"],
            {"amount": 6_666_666, "currency": "RON"},
        )
        self.assertEqual(am41d["material_facts"]["scoring"]["minimum_quality_score"], 70)
        self.assertIn("Instituții publice din România", am41d["material_facts"]["beneficiaries"])

        fami_change = next(row for row in merged["changesets"] if row["changeset_id"] == "CS-MAI-FED-FAMI-OPEN-CALLS-20260923")
        self.assertEqual(fami_change["resolution_state"], "VERIFIED")
        self.assertEqual({row["fact_class"] for row in fami_change["changes"]}, {"status", "deadline", "budget"})

    def test_replay_is_deterministic(self):
        base = mod.load(ROOT / "opportunity_bundle.json")
        base.pop("resolution_application", None)
        resolutions = [mod.load(path) for path in sorted((ROOT / "resolutions").glob("*_resolution.json"))]
        one = mod.apply(copy.deepcopy(base), resolutions)
        two = mod.apply(copy.deepcopy(base), resolutions)
        self.assertEqual(one, two)


if __name__ == "__main__":
    unittest.main()
