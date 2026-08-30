from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from collection_channel_register_control import (
    CollectionChannelRegisterError,
    validate_prod_binding,
    validate_register,
)

# TEST TWIN ONLY — NON-EVIDENCE. Synthetic channel fixtures below are engineering controls only.


def valid_register() -> dict:
    return {
        "schema_version": "eucons.ai4work_collection_channel_register.v0.1",
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "entries": [
            {
                "channel_id": "CH-TESTTWIN01",
                "channel_type": "institutional",
                "region_scope": ["Sud-Vest Oltenia"],
                "audience_scope": ["adults"],
                "invitation_version": "TEST_TWIN_V1_NON_EVIDENCE",
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
            "schema_version": "eucons.ai4work_collection_channel_register.v0.1",
            "research_id": "AI4WORK-STEP-NF-RUN-001",
            "entries": [],
        }
        self.assertEqual(validate_register(draft, require_nonempty=False), {})
        with self.assertRaisesRegex(CollectionChannelRegisterError, "at least one approved dissemination batch"):
            validate_register(draft, require_nonempty=True)

    def test_channel_scope_is_exactly_bounded(self):
        register = valid_register()
        entry = register["entries"][0]
        entry["region_scope"] = ["Sud-Vest Oltenia", "Outside scope"]
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

    def test_prod_binding_requires_exact_register_hash(self):
        register = valid_register()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "register.json"
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
        register = {
            "schema_version": "eucons.ai4work_collection_channel_register.v0.1",
            "research_id": "AI4WORK-STEP-NF-RUN-001",
            "entries": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "register.json"
            path.write_text(json.dumps(register) + "\n", encoding="utf-8")
            errors = validate_prod_binding(
                register_path=path,
                collection_frame={"approval": {"collection_channel_register_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}},
            )
            self.assertTrue(any(item.startswith("collection_channel_register_invalid:") for item in errors))


if __name__ == "__main__":
    unittest.main()
