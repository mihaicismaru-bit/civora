#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
INGEST = HERE.parent / "ingest"
sys.path.insert(0, str(INGEST))

from eu_direct_ft_programme_watch import build_watch, validate_watch  # noqa: E402


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def facet():
    return {
        "facets": [
            {
                "name": "frameworkProgramme",
                "values": [
                    {"rawValue": "43108390", "value": "Horizon Europe (HORIZON)", "count": 100},
                    {"rawValue": "CERV-CODE", "value": "Citizens, Equality, Rights and Values Programme (CERV)", "count": 20},
                ],
            },
            {
                "name": "status",
                "values": [
                    {"rawValue": "31094502", "value": "Open for submission"},
                    {"rawValue": "31094501", "value": "Forthcoming"},
                ],
            },
        ]
    }


def row(identifier, programme, *, status="31094502", row_type="1", title=None):
    return {
        "metadata": {
            "identifier": identifier,
            "callIdentifier": identifier.rsplit("-", 1)[0],
            "frameworkProgramme": programme,
            "status": status,
            "type": row_type,
            "title": title or f"Title for {identifier}",
        }
    }


def receipt(seed):
    return {"url": f"https://api.tech.ec.europa.eu/{seed}", "http_status": 200, "sha256": hashlib.sha256(seed.encode()).hexdigest()}


class ProgrammeWatchTests(unittest.TestCase):
    def build(self, pages):
        return build_watch(
            pages,
            facet(),
            fetched_at="2026-09-01T14:00:00+00:00",
            run_id="RUN-1",
            page_receipts=[receipt("p1")],
            facet_receipt=receipt("facet"),
        )

    def test_deduplicates_and_stays_non_authorizing(self):
        pages = [{"results": [
            row("HORIZON-EIC-2026-TEST-01", "43108390"),
            row("CERV-2026-CITIZENS-TEST", "CERV-CODE"),
            row("CERV-2026-CITIZENS-TEST", "CERV-CODE"),
            row("CERV-TYPE8", "CERV-CODE", row_type="8"),
        ]}]
        watch = self.build(pages)
        validate_watch(watch)
        self.assertEqual(watch["stats"]["accepted_candidates"], 2)
        self.assertEqual(watch["stats"]["exact_duplicates_removed"], 1)
        self.assertEqual(watch["stats"]["quarantined_records"], 1)
        self.assertEqual(watch["programme_family_counts"], {"CERV": 1, "HORIZON_EUROPE": 1})
        horizon = next(r for r in watch["records"] if r["identifier"].startswith("HORIZON"))
        self.assertEqual(horizon["instrument_family_candidate"], "EIC")
        self.assertEqual(horizon["status_label_candidate"], "Open")
        self.assertFalse(horizon["authority_url_verified"])
        self.assertFalse(horizon["open_call_authorized"])
        self.assertFalse(watch["open_call_authorized"])
        self.assertEqual(watch["publication_effect"], "NONE")
        self.assertFalse(watch["canonical_corpus_mutation"])

    def test_same_identifier_cross_programme_conflict_is_excluded(self):
        pages = [{"results": [
            row("SHARED-2026-01", "43108390"),
            row("SHARED-2026-01", "CERV-CODE"),
        ]}]
        watch = self.build(pages)
        self.assertEqual(watch["stats"]["accepted_candidates"], 0)
        self.assertEqual(watch["stats"]["conflict_groups_excluded"], 1)
        self.assertEqual(watch["conflicts"][0]["reason"], "CROSS_PROGRAMME_OR_SEMANTIC_IDENTITY_CONFLICT")
        self.assertFalse(watch["conflicts"][0]["open_call_authorized"])

    def test_materially_different_duplicate_is_conflict(self):
        pages = [{"results": [
            row("CERV-2026-01", "CERV-CODE", status="31094502", title="A"),
            row("CERV-2026-01", "CERV-CODE", status="31094501", title="A"),
        ]}]
        watch = self.build(pages)
        self.assertEqual(watch["stats"]["accepted_candidates"], 0)
        self.assertEqual(watch["stats"]["conflict_groups_excluded"], 1)

    def test_unresolved_programme_is_quarantined(self):
        pages = [{"results": [row("UNKNOWN-2026-01", "99999999")]}]
        watch = self.build(pages)
        self.assertEqual(watch["stats"]["accepted_candidates"], 0)
        self.assertEqual(watch["quarantined_records"][0]["reason"], "PROGRAMME_REFERENCE_UNRESOLVED_IN_OFFICIAL_FACET")

    def test_unresolved_status_is_quarantined(self):
        pages = [{"results": [row("CERV-2026-01", "CERV-CODE", status="99999999")]}]
        watch = self.build(pages)
        self.assertEqual(watch["stats"]["accepted_candidates"], 0)
        self.assertEqual(watch["quarantined_records"][0]["reason"], "STATUS_REFERENCE_UNRESOLVED_IN_OFFICIAL_FACET")

    def test_validator_rejects_self_authorization(self):
        watch = self.build([{"results": [row("CERV-2026-01", "CERV-CODE")]}])
        watch["records"][0]["open_call_authorized"] = True
        with self.assertRaisesRegex(ValueError, "attempted authorization"):
            validate_watch(watch)

    def test_pipeline_like_label_does_not_authorize_anything(self):
        custom = facet()
        custom["facets"][1]["values"].append({"rawValue": "777", "value": "Planned"})
        watch = build_watch(
            [{"results": [row("CERV-2027-PLANNED", "CERV-CODE", status="777")]}],
            custom,
            fetched_at="2026-09-01T14:00:00+00:00",
            run_id="RUN-2",
            page_receipts=[receipt("p2")],
            facet_receipt=receipt("facet2"),
        )
        validate_watch(watch)
        self.assertEqual(watch["records"][0]["status_label_candidate"], "Planned")
        self.assertFalse(watch["open_call_authorized"])
        self.assertFalse(watch["records"][0]["open_call_authorized"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
