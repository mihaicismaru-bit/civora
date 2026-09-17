from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

import need_ranking_engine as ENGINE
import nf06_preingest as NF06
from research_storage import canonical_json_bytes

ROOT = Path(__file__).resolve().parent
UNIT_TEST_FIXTURE_NON_EVIDENCE = True


def approved_plan() -> dict:
    plan = json.loads((ROOT / "NEED_ANALYSIS_PLAN_DRAFT.json").read_text(encoding="utf-8"))
    plan["status"] = "APPROVED_FOR_PROD"
    plan["approval"] = {
        "approved": True,
        "approved_for_prod": True,
        "approved_at": "2026-08-19T11:00:00+00:00",
        "approver_reference": "UNIT-TEST-ONLY-NON-EVIDENCE",
    }
    return plan


def prod_shaped_records() -> list[dict]:
    records: list[dict] = []
    for index, region in enumerate(ENGINE.TARGET_REGIONS, start=1):
        records.append(
            {
                "research_id": "AI4WORK-STEP-NF-RUN-001",
                "form_id": ENGINE.ADULT_FORM,
                "response_id": hashlib.sha256(f"adult-{index}".encode()).hexdigest(),
                "received_at": "2026-08-23T12:00:00+00:00",
                "recruitment_channel_id": f"UNIT-TEST-CHANNEL-A-{index}",
                "profile": {"region": region},
                "answers": {
                    "Q10": {
                        "utilizare_digitala_functionala": 1,
                        "utilizarea_instrumentelor_AI": 5,
                        "verificarea_rezultatelor_AI": 4,
                        "protectia_datelor_confidentialitate": 3,
                        "integrarea_AI_in_flux_de_lucru": 2,
                    }
                },
                "synthetic": False,
            }
        )
        records.append(
            {
                "research_id": "AI4WORK-STEP-NF-RUN-001",
                "form_id": ENGINE.EMPLOYER_FORM,
                "response_id": hashlib.sha256(f"employer-{index}".encode()).hexdigest(),
                "received_at": "2026-08-23T12:00:00+00:00",
                "recruitment_channel_id": f"UNIT-TEST-CHANNEL-E-{index}",
                "profile": {"region": region},
                "answers": {
                    "E03": {
                        "formularea_cerintelor": 4,
                        "verificarea_calitatii": 4,
                        "protectia_datelor": 3,
                        "limitele_si_riscurile_AI": 5,
                        "integrarea_in_procese": 2,
                        "definirea_fluxului_asistat_AI": 4,
                        "competente_digitale_generale": 2,
                    }
                },
                "synthetic": False,
            }
        )
    return records


def gate_result(records: list[dict], plan: dict) -> dict:
    return {
        "schema_version": "eucons.ai4work_needs_synthesis_gate.v0.5",
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "source_evidence_class": "PROD_REAL_EVIDENCE",
        "ready_for_needs_synthesis": True,
        "source_export_sha256": hashlib.sha256(NF06.canonical_export_bytes(records)).hexdigest(),
        "collection_frame_sha256": "1" * 64,
        "method_frame_sha256": "2" * 64,
        "need_analysis_plan_sha256": hashlib.sha256(canonical_json_bytes(plan)).hexdigest(),
        "representativeness_claim_allowed": False,
        "weighting_allowed": False,
    }


class NeedRankingEngineTests(unittest.TestCase):
    def test_exact_prod_batch_rank_is_deterministic_and_uses_no_secondary_points(self):
        records = prod_shaped_records()
        plan = approved_plan()
        result = ENGINE.compute_core_need_ranking(records, synthesis_gate_result=gate_result(records, plan), need_analysis_plan=plan)
        self.assertEqual(result["schema_version"], "eucons.ai4work_need_ranking_engine.v0.1")
        self.assertEqual(result["source_evidence_class"], "PROD_REAL_EVIDENCE")
        self.assertEqual([row["need_id"] for row in result["pooled_equal_population_rank"]], ["H1", "H2", "H3", "H4", "H5"])
        self.assertEqual([row["rank"] for row in result["pooled_equal_population_rank"]], [1, 2, 3, 4, 5])
        self.assertEqual(result["dimensions"]["H1"]["combined_score_display_0_100"], "87.50")
        self.assertEqual(result["dimensions"]["H3"]["employer_score_display_0_100"], "75.00")
        self.assertEqual(result["dimensions"]["H4"]["combined_score_display_0_100"], "37.50")
        self.assertEqual(result["secondary_evidence_numeric_points"], 0)
        self.assertEqual(result["project_activity_numeric_points"], 0)
        self.assertFalse(result["representativeness_claim_allowed"])
        self.assertTrue(result["adversarial_qa_required"])
        self.assertEqual(set(result["regional_equal_population_views"]), set(ENGINE.TARGET_REGIONS))

    def test_source_export_drift_is_rejected(self):
        records = prod_shaped_records()
        plan = approved_plan()
        gate = gate_result(records, plan)
        tampered = copy.deepcopy(records)
        tampered[0]["answers"]["Q10"]["utilizarea_instrumentelor_AI"] = 1
        with self.assertRaisesRegex(ENGINE.NeedRankingEngineError, "source export"):
            ENGINE.compute_core_need_ranking(tampered, synthesis_gate_result=gate, need_analysis_plan=plan)

    def test_test_twin_or_synthetic_record_is_rejected_even_if_hash_is_rebound(self):
        records = prod_shaped_records()
        records[0]["synthetic"] = True
        plan = approved_plan()
        with self.assertRaisesRegex(ENGINE.NeedRankingEngineError, "NON-EVIDENCE"):
            ENGINE.compute_core_need_ranking(records, synthesis_gate_result=gate_result(records, plan), need_analysis_plan=plan)

    def test_missing_required_direct_rating_is_not_imputed(self):
        records = prod_shaped_records()
        del records[0]["answers"]["Q10"]["verificarea_rezultatelor_AI"]
        plan = approved_plan()
        with self.assertRaisesRegex(ENGINE.NeedRankingEngineError, "required direct matrix row missing"):
            ENGINE.compute_core_need_ranking(records, synthesis_gate_result=gate_result(records, plan), need_analysis_plan=plan)

    def test_exact_ties_share_competition_rank_and_need_id_only_orders_display(self):
        records = prod_shaped_records()
        for record in records:
            if record["form_id"] == ENGINE.ADULT_FORM:
                record["answers"]["Q10"]["verificarea_rezultatelor_AI"] = 5
            else:
                record["answers"]["E03"]["verificarea_calitatii"] = 4
        plan = approved_plan()
        result = ENGINE.compute_core_need_ranking(records, synthesis_gate_result=gate_result(records, plan), need_analysis_plan=plan)
        first_two = result["pooled_equal_population_rank"][:2]
        self.assertEqual([row["need_id"] for row in first_two], ["H1", "H2"])
        self.assertEqual([row["rank"] for row in first_two], [1, 1])
        self.assertEqual(first_two[0]["score_exact_fraction"], first_two[1]["score_exact_fraction"])


if __name__ == "__main__":
    unittest.main()
