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


class ResolutionOverlayTests(unittest.TestCase):
    def test_verified_overlays_preserve_25_identities(self):
        base = mod.load(ROOT / "opportunity_bundle.json")
        # Remove already persisted application metadata to make replay explicit.
        base.pop("resolution_application", None)
        resolutions = [mod.load(path) for path in sorted((ROOT / "resolutions").glob("*_resolution.json"))]
        merged = mod.apply(base, resolutions)
        self.assertEqual(
            [row["opportunity_id"] for row in base["opportunities"]],
            [row["opportunity_id"] for row in merged["opportunities"]][: len(base["opportunities"])],
        )
        self.assertEqual(len(merged["opportunities"]), 26)
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

    def test_replay_is_deterministic(self):
        base = mod.load(ROOT / "opportunity_bundle.json")
        base.pop("resolution_application", None)
        resolutions = [mod.load(path) for path in sorted((ROOT / "resolutions").glob("*_resolution.json"))]
        one = mod.apply(copy.deepcopy(base), resolutions)
        two = mod.apply(copy.deepcopy(base), resolutions)
        self.assertEqual(one, two)


if __name__ == "__main__":
    unittest.main()
