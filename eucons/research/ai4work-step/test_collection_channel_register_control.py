from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from collection_channel_register_control import (
    CollectionChannelRegisterError,
    validate_invitation_catalog,
    validate_prod_binding,
    validate_register,
)

# TEST TWIN ONLY — NON-EVIDENCE. Synthetic channel/catalog fixtures below are engineering controls only.


def valid_catalog(*, approved: bool) -> dict:
    status = "APPROVED_FOR_PROD" if approved else "DRAFT_CONTROLLER_REVIEW_REQUIRED"
    return {
        "schema_version": "eucons.ai4work_research_invitation_catalog.v0.1",
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "status": status,
        "evidence_class": "CONTROL_ARTIFACT_NOT_EVIDENCE",
        "approved_for_prod": approved,
        "purpose": "TEST TWIN catalog for engineering control coverage only. NON-EVIDENCE and never a real dissemination artifact.",
        "entries": [
            {
                "invitation_version": "TEST_TWIN_ADULTS_V1",
                "audience_scope": ["adults"],
                "invitation_text": (
                    "TEST TWIN NON-EVIDENCE invitation copy. Participation is voluntary, there is no disadvantage "
                    "for refusal, no project enrolment condition, no commercial marketing, no direct identifier "
                    "request, no conditional incentive, the privacy notice appears before the form, and one response "
                    "is requested. This is synthetic engineering text only."
                ),
                "required_safeguards": {
                    "voluntary_participation": True,
                    "no_disadvantage": True,
                    "no_project_enrolment_condition": True,
                    "no_commercial_marketing": True,
                    "no_direct_identifier_request": True,
                    "no_incentive_condition": True,
                    "privacy_notice_before_form": True,
                    "one_response_request": True,
                },
            },
            {
                "invitation_version": "TEST_TWIN_EMPLOYERS_V1",
                "audience_scope": ["employers"],
                "invitation_text": (
                    "TEST TWIN NON-EVIDENCE employer invitation copy. Participation is voluntary, there is no "
                    "disadvantage for refusal, no project enrolment condition, no commercial marketing, no direct "
                    "identifier request, no conditional incentive, the privacy notice appears before the form, and "
                    "one response is requested. This is synthetic engineering text only."
                ),
                "required_safeguards": {
                    "voluntary_participation": True,
                    "no_disadvantage": True,
                    "no_project_enrolment_condition": True,
                    "no_commercial_marketing": True,
                    "no_direct_identifier_request": True,
                    "no_incentive_condition": True,
                    "privacy_notice_before_form": True,
                    "one_response_request": True,
                },
            },
        ],
        "transport_policy": {
            "channel_identifier_mode": "OPAQUE_URL_FRAGMENT_ONLY",
            "channel_identifier_format": "CH-[A-Z0-9]{8,32}",
            "query_tracking_parameters_allowed": False,
            "commercial_tracking_allowed": False,
            "crm_identifier_allowed": False,
            "referrer_derived_channel_allowed": False,
        },
        "approval": {
            "approved_for_prod": approved,
            "approver_name_or_role": "TEST_TWIN_NON_EVIDENCE" if approved else None,
            "approval_date": "2026-08-31" if approved else None,
            "notes": "Synthetic test fixture only; this does not approve any real dissemination.",
        },
        "test_twin_policy": "TEST_TWIN_NON_EVIDENCE_PERMANENTLY_NON_PROMOTABLE",
        "merge_authorized": False,
        "deploy_authorized": False,
        "real_dissemination_authorized": False,
    }


def write_catalog(directory: Path, *, approved: bool) -> tuple[str, str]:
    catalog = valid_catalog(approved=approved)
    text = json.dumps(catalog, ensure_ascii=False, sort_keys=True) + "\n"
    path = directory / "invitation_catalog.json"
    path.write_text(text, encoding="utf-8")
    return path.name, hashlib.sha256(path.read_bytes()).hexdigest()


def valid_register(*, catalog_reference: str = "invitation_catalog.json", catalog_sha256: str = "0" * 64) -> dict:
    return {
        "schema_version": "eucons.ai4work_collection_channel_register.v0.2",
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "invitation_catalog": {
            "reference": catalog_reference,
            "sha256": catalog_sha256,
        },
        "entries": [
            {
                "channel_id": "CH-TESTTWIN01",
                "channel_type": "institutional",
                "region_scope": ["Sud-Vest Oltenia"],
                "audience_scope": ["adults"],
                "invitation_version": "TEST_TWIN_ADULTS_V1",
                "opened_at": "2026-08-30T00:00:00Z",
                "closed_at": "2026-09-30T00:00:00Z",
                "distributor_role": "TEST_TWIN_NON_EVIDENCE",
                "non_coercion_confirmed": True,
            }
        ],
    }


class CollectionChannelRegisterControlTests(unittest.TestCase):
    def test_draft_empty_register_is_valid_structure_but_not_prod_eligible(self):
        draft = {
            "schema_version": "eucons.ai4work_collection_channel_register.v0.2",
            "research_id": "AI4WORK-STEP-NF-RUN-001",
            "invitation_catalog": {
                "reference": "RESEARCH_INVITATION_CATALOG_DRAFT.json",
                "sha256": "0" * 64,
            },
            "entries": [],
        }
        self.assertEqual(validate_register(draft, require_nonempty=False), {})
        with self.assertRaisesRegex(CollectionChannelRegisterError, "at least one approved dissemination batch"):
            validate_register(draft, require_nonempty=True)

    def test_channel_scope_is_exactly_bounded(self):
        register = valid_register()
        register["entries"][0]["region_scope"] = ["Sud-Vest Oltenia", "Outside scope"]
        with self.assertRaisesRegex(CollectionChannelRegisterError, "target regions"):
            validate_register(register, require_nonempty=True)

    def test_audience_scope_and_non_coercion_are_required(self):
        register = valid_register()
        register["entries"][0]["audience_scope"] = ["marketing"]
        with self.assertRaisesRegex(CollectionChannelRegisterError, "adults and/or employers"):
            validate_register(register, require_nonempty=True)

        register = valid_register()
        register["entries"][0]["non_coercion_confirmed"] = False
        with self.assertRaisesRegex(CollectionChannelRegisterError, "non_coercion_confirmed"):
            validate_register(register, require_nonempty=True)

    def test_duplicate_channel_ids_fail_closed(self):
        register = valid_register()
        register["entries"].append(copy.deepcopy(register["entries"][0]))
        with self.assertRaisesRegex(CollectionChannelRegisterError, "duplicate channel_id"):
            validate_register(register, require_nonempty=True)

    def test_invitation_catalog_requires_all_safeguards_and_no_tracking_tokens(self):
        catalog = valid_catalog(approved=False)
        catalog["entries"][0]["required_safeguards"]["no_commercial_marketing"] = False
        with self.assertRaisesRegex(CollectionChannelRegisterError, "all invitation safeguards must be true"):
            validate_invitation_catalog(catalog, require_approved=False)

        catalog = valid_catalog(approved=False)
        catalog["entries"][0]["invitation_text"] += " https://example.test/?utm_source=bad"
        with self.assertRaisesRegex(CollectionChannelRegisterError, "forbidden tracking"):
            validate_invitation_catalog(catalog, require_approved=False)

    def test_draft_invitation_catalog_cannot_satisfy_prod_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            reference, digest = write_catalog(directory, approved=False)
            register = valid_register(catalog_reference=reference, catalog_sha256=digest)
            path = directory / "register.json"
            path.write_text(json.dumps(register, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            frame = {
                "approval": {
                    "collection_channel_register_sha256": hashlib.sha256(path.read_bytes()).hexdigest()
                }
            }
            errors = validate_prod_binding(register_path=path, collection_frame=frame)
            self.assertTrue(
                any(
                    item.startswith("invitation_catalog_binding_invalid:")
                    and "not approved for PROD" in item
                    for item in errors
                )
            )

    def test_invitation_catalog_hash_and_scope_are_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            reference, digest = write_catalog(directory, approved=True)
            register = valid_register(catalog_reference=reference, catalog_sha256=digest)
            path = directory / "register.json"
            path.write_text(json.dumps(register, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            frame = {
                "approval": {
                    "collection_channel_register_sha256": hashlib.sha256(path.read_bytes()).hexdigest()
                }
            }
            self.assertEqual(validate_prod_binding(register_path=path, collection_frame=frame), [])

            register["invitation_catalog"]["sha256"] = "f" * 64
            path.write_text(json.dumps(register, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            frame["approval"]["collection_channel_register_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertTrue(
                any(
                    item.startswith("invitation_catalog_binding_invalid:")
                    and "sha256 mismatch" in item
                    for item in validate_prod_binding(register_path=path, collection_frame=frame)
                )
            )

            reference, digest = write_catalog(directory, approved=True)
            register = valid_register(catalog_reference=reference, catalog_sha256=digest)
            register["entries"][0]["audience_scope"] = ["employers"]
            path.write_text(json.dumps(register, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            frame["approval"]["collection_channel_register_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertTrue(
                any(
                    item.startswith("invitation_catalog_binding_invalid:")
                    and "exceeds invitation catalog scope" in item
                    for item in validate_prod_binding(register_path=path, collection_frame=frame)
                )
            )

    def test_prod_binding_requires_exact_register_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            reference, digest = write_catalog(directory, approved=True)
            register = valid_register(catalog_reference=reference, catalog_sha256=digest)
            path = directory / "register.json"
            path.write_text(json.dumps(register, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            frame = {"approval": {"collection_channel_register_sha256": actual}}
            self.assertEqual(validate_prod_binding(register_path=path, collection_frame=frame), [])

            frame["approval"]["collection_channel_register_sha256"] = "0" * 64
            self.assertIn(
                "collection_channel_register_sha256_mismatch",
                validate_prod_binding(register_path=path, collection_frame=frame),
            )

    def test_empty_repository_style_register_cannot_be_bound_for_prod(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            reference, digest = write_catalog(directory, approved=True)
            register = {
                "schema_version": "eucons.ai4work_collection_channel_register.v0.2",
                "research_id": "AI4WORK-STEP-NF-RUN-001",
                "invitation_catalog": {"reference": reference, "sha256": digest},
                "entries": [],
            }
            path = directory / "register.json"
            path.write_text(json.dumps(register) + "\n", encoding="utf-8")
            errors = validate_prod_binding(
                register_path=path,
                collection_frame={
                    "approval": {
                        "collection_channel_register_sha256": hashlib.sha256(path.read_bytes()).hexdigest()
                    }
                },
            )
            self.assertTrue(any(item.startswith("collection_channel_register_invalid:") for item in errors))


if __name__ == "__main__":
    unittest.main()
