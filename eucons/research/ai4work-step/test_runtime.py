#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ai4work_research_runtime", HERE / "runtime.py")
RUNTIME = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RUNTIME)


def adult_payload():
    return {
        "form_id": "AI4WORK_ADULTS_V1",
        "notice_read_and_voluntary_participation": True,
        "profile": {
            "region": "Sud-Vest Oltenia",
            "status": "persoană ocupată potențial eligibilă",
            "age_band": "40-49",
            "occupational_family": "administrativ",
        },
        "answers": {
            "Q01": 3,
            "Q02": 2,
            "Q03": 2,
            "Q04": 2,
            "Q05": 3,
            "Q06": 2,
            "Q07": False,
            "Q08": ["lipsa timpului"],
            "Q09": ["nu am folosit AI"],
            "Q10": {
                "utilizare_digitala_functionala": 3,
                "utilizarea_instrumentelor_AI": 5,
                "verificarea_rezultatelor_AI": 5,
                "protectia_datelor_confidentialitate": 4,
                "integrarea_AI_in_flux_de_lucru": 5,
            },
            "Q11": "adaptare mai bună la postul actual",
            "Q12": "Pregătirea rapidă a unor documente și verificarea informațiilor.",
        },
    }


def employer_payload():
    return {
        "form_id": "AI4WORK_EMPLOYERS_V1",
        "notice_read_and_voluntary_participation": True,
        "profile": {
            "region": "Centru",
            "sector_aggregated": "servicii profesionale",
            "size_band": "10-49",
            "respondent_role": "management",
        },
        "answers": {
            "E01": "pilot/test",
            "E02": ["redactare/comunicare", "analiză date"],
            "E03": {
                "formularea_cerintelor": 4,
                "verificarea_calitatii": 5,
                "protectia_datelor": 4,
                "limitele_si_riscurile_AI": 4,
                "integrarea_in_procese": 5,
                "definirea_fluxului_asistat_AI": 5,
                "competente_digitale_generale": 3,
            },
            "E04": "da",
            "E04_detail": "Verificarea rezultatelor și integrarea instrumentelor în procese.",
            "E05": "nu",
            "E06": ["timp disponibil", "conținut prea general"],
            "E07": "moderat",
            "E08": ["verificarea factuală/calității", "protecția datelor"],
            "E09": "Lipsa unei metode unitare de verificare limitează folosirea instrumentelor.",
            "E10": "posibil",
        },
    }


class ResearchRuntimeTests(unittest.TestCase):
    def test_valid_adult_record_matches_nf06_envelope(self):
        record = RUNTIME.validate_submission(adult_payload())
        self.assertEqual(set(record), {"schema_version", "research_id", "form_id", "form_version", "response_id", "received_at", "profile", "answers", "synthetic"})
        self.assertEqual(record["form_id"], "AI4WORK_ADULTS_V1")
        self.assertFalse(record["synthetic"])

    def test_valid_employer_record_has_no_org_identity(self):
        record = RUNTIME.validate_submission(employer_payload())
        self.assertEqual(record["form_id"], "AI4WORK_EMPLOYERS_V1")
        self.assertNotIn("organisation_name", str(record))
        self.assertNotIn("cui", str(record).lower())

    def test_expanded_direct_identifier_alias_is_rejected(self):
        payload = adult_payload()
        payload["profile"]["first_name"] = "Test"
        with self.assertRaises(RUNTIME.ResearchValidationError):
            RUNTIME.validate_submission(payload)

    def test_identifier_like_free_text_is_rejected(self):
        payload = adult_payload()
        payload["answers"]["Q12"] = "Contactați-mă la test@example.org"
        with self.assertRaises(RUNTIME.ResearchValidationError):
            RUNTIME.validate_submission(payload)

    def test_acknowledgement_is_required(self):
        payload = adult_payload()
        payload["notice_read_and_voluntary_participation"] = False
        with self.assertRaises(RUNTIME.ResearchValidationError):
            RUNTIME.validate_submission(payload)

    def test_region_outside_scope_is_rejected(self):
        payload = employer_payload()
        payload["profile"]["region"] = "București-Ilfov"
        with self.assertRaises(RUNTIME.ResearchValidationError):
            RUNTIME.validate_submission(payload)

    def test_rating_out_of_range_is_rejected(self):
        payload = adult_payload()
        payload["answers"]["Q04"] = 6
        with self.assertRaises(RUNTIME.ResearchValidationError):
            RUNTIME.validate_submission(payload)

    def test_unsupported_option_is_rejected_not_just_length_checked(self):
        payload = employer_payload()
        payload["answers"]["E07"] = "foarte mult"
        with self.assertRaises(RUNTIME.ResearchValidationError):
            RUNTIME.validate_submission(payload)

    def test_selection_limit_is_enforced(self):
        payload = employer_payload()
        payload["answers"]["E08"] = [
            "formularea și rafinarea instrucțiunilor",
            "verificarea factuală/calității",
            "analiză și interpretare de date",
            "protecția datelor",
            "securitate digitală",
            "automatizarea unor pași de lucru",
        ]
        with self.assertRaises(RUNTIME.ResearchValidationError):
            RUNTIME.validate_submission(payload)

    def test_duplicate_multi_selection_is_rejected(self):
        payload = adult_payload()
        payload["answers"]["Q08"] = ["lipsa timpului", "lipsa timpului"]
        with self.assertRaises(RUNTIME.ResearchValidationError):
            RUNTIME.validate_submission(payload)

    def test_inactive_conditional_field_must_be_empty(self):
        payload = adult_payload()
        payload["answers"]["Q07_topic"] = "AI"
        with self.assertRaises(RUNTIME.ResearchValidationError):
            RUNTIME.validate_submission(payload)

    def test_collection_remains_disabled_by_contract(self):
        self.assertFalse(RUNTIME.collection_enabled())


if __name__ == "__main__":
    unittest.main()
