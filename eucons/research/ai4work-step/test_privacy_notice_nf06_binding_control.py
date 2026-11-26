from __future__ import annotations

import copy
import unittest

import privacy_notice_nf06_binding_control as CONTROL


class PrivacyNoticeNF06BindingControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = CONTROL._load(CONTROL.SNAPSHOT_PATH)
        self.frame = CONTROL._load(CONTROL.FRAME_PATH)
        self.manifest = CONTROL._load(CONTROL.MANIFEST_PATH)
        self.nf06 = CONTROL._load(CONTROL.NF06_CONTRACT_PATH)
        self.digest = CONTROL._snapshot_sha256()

    def errors(self, *, snapshot=None, frame=None, manifest=None, digest=None):
        return CONTROL.binding_errors(
            snapshot=copy.deepcopy(self.snapshot if snapshot is None else snapshot),
            collection_frame=copy.deepcopy(self.frame if frame is None else frame),
            manifest=copy.deepcopy(self.manifest if manifest is None else manifest),
            nf06_contract=copy.deepcopy(self.nf06),
            snapshot_sha256=self.digest if digest is None else digest,
        )

    def promoted_fixture(self):
        snapshot = copy.deepcopy(self.snapshot)
        frame = copy.deepcopy(self.frame)
        manifest = copy.deepcopy(self.manifest)
        snapshot["status"] = "APPROVED_FOR_PROD"
        snapshot["approved"] = True
        snapshot["collection_enabled"] = True
        snapshot["approval"] = {
            "controller_approved": True,
            "approved_by": "controller-review",
            "approved_at": "2026-08-31T09:00:00+03:00",
            "approval_reference": "CTRL-PRIVACY-001",
        }
        manifest["required_external_or_operational_evidence"]["privacy_notice"] = {
            "status": "APPROVED",
            "reference": CONTROL.SNAPSHOT_PATH.name,
            "sha256": self.digest,
        }
        frame["approval"]["privacy_notice_version"] = snapshot["schema_version"]
        return snapshot, frame, manifest

    def test_repository_draft_is_validly_fail_closed(self):
        valid, errors, promoted = CONTROL.evaluate_repository_binding()
        self.assertTrue(valid, errors)
        self.assertFalse(promoted)

    def test_promoted_binding_requires_exact_snapshot_hash(self):
        snapshot, frame, manifest = self.promoted_fixture()
        manifest["required_external_or_operational_evidence"]["privacy_notice"]["sha256"] = "0" * 64
        self.assertIn(
            "privacy_notice_sha256_mismatch",
            self.errors(snapshot=snapshot, frame=frame, manifest=manifest),
        )

    def test_promoted_binding_requires_exact_collection_frame_notice_version(self):
        snapshot, frame, manifest = self.promoted_fixture()
        frame["approval"]["privacy_notice_version"] = "wrong-version"
        self.assertIn(
            "collection_frame_privacy_notice_version_mismatch",
            self.errors(snapshot=snapshot, frame=frame, manifest=manifest),
        )

    def test_prod_activation_cannot_run_with_open_privacy_notice(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["collection_enabled"] = True
        self.assertIn(
            "privacy_notice_not_promoted_before_prod_activation",
            self.errors(manifest=manifest),
        )

    def test_promoted_binding_requires_controller_approved_snapshot(self):
        snapshot, frame, manifest = self.promoted_fixture()
        snapshot["approval"]["controller_approved"] = False
        self.assertIn(
            "privacy_notice_controller_approval_missing",
            self.errors(snapshot=snapshot, frame=frame, manifest=manifest),
        )

    def test_nf06_contract_must_keep_privacy_notice_requirement(self):
        nf06 = copy.deepcopy(self.nf06)
        nf06["prod_requirements"] = [
            item for item in nf06["prod_requirements"] if item != "privacy notice version is present"
        ]
        errors = CONTROL.binding_errors(
            snapshot=copy.deepcopy(self.snapshot),
            collection_frame=copy.deepcopy(self.frame),
            manifest=copy.deepcopy(self.manifest),
            nf06_contract=nf06,
            snapshot_sha256=self.digest,
        )
        self.assertIn("nf06_contract_privacy_notice_requirement_missing", errors)


if __name__ == "__main__":
    unittest.main()
