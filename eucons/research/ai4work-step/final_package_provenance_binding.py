from __future__ import annotations

import hashlib
import io
import json
import zipfile
from typing import Any, Mapping

import final_needs_package_gate as FINAL
import source_register_provenance_control as PROVENANCE
from research_storage import RESEARCH_ID, canonical_json_bytes

SCHEMA = "eucons.ai4work_final_package_provenance_binding.v0.1"
PROD_MODE = "PROD_REAL_EVIDENCE"
TEST_MODE = "TEST_TWIN_NON_EVIDENCE"
FIXED_ZIP_TIME = (2026, 9, 1, 0, 0, 0)


class FinalPackageProvenanceBindingError(ValueError):
    pass


def _json_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _bytes_sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _zip_write(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, payload)


def build_provenance_bound_final_package(
    records: list[dict[str, Any]],
    *,
    ranking_result: dict[str, Any],
    adversarial_qa_result: dict[str, Any],
    source_register: dict[str, Any],
    source_provenance_manifest: dict[str, Any],
    source_snapshot_bytes_by_source_id: Mapping[str, bytes],
    evidence_mode: str,
) -> tuple[dict[str, Any], bytes]:
    """Build the only release-eligible outer package for AI4WORK final analysis.

    The existing final package remains the deterministic analysis/DOCX assembler. This
    outer control makes byte-verified source provenance inseparable from any PROD
    release decision by binding the exact base package, source register, provenance
    manifest, provenance verification result and source export. TEST TWIN follows the
    same mechanics but remains permanently NON-EVIDENCE and non-promotable.
    """
    if evidence_mode not in {PROD_MODE, TEST_MODE}:
        raise FinalPackageProvenanceBindingError("unsupported evidence mode")
    if not isinstance(source_provenance_manifest, dict):
        raise FinalPackageProvenanceBindingError("source provenance manifest is required")
    if not isinstance(source_snapshot_bytes_by_source_id, Mapping) or not source_snapshot_bytes_by_source_id:
        raise FinalPackageProvenanceBindingError("captured source snapshot bytes are required")

    try:
        provenance_verification = PROVENANCE.verify_source_register_provenance(
            source_register,
            source_provenance_manifest,
            snapshot_bytes_by_source_id=source_snapshot_bytes_by_source_id,
            evidence_mode=evidence_mode,
        )
    except PROVENANCE.SourceRegisterProvenanceError as exc:
        raise FinalPackageProvenanceBindingError(
            f"source provenance verification failed: {exc}"
        ) from exc

    source_register_sha256 = _json_sha(source_register)
    if provenance_verification.get("source_register_sha256") != source_register_sha256:
        raise FinalPackageProvenanceBindingError("source-register provenance binding mismatch")

    if evidence_mode == PROD_MODE:
        if provenance_verification.get("verification_status") != "PASS":
            raise FinalPackageProvenanceBindingError("PROD source provenance must verify PASS")
        if provenance_verification.get("prod_promotion_allowed") is not True:
            raise FinalPackageProvenanceBindingError("PROD source provenance is not promotion-eligible")
    else:
        if provenance_verification.get("verification_status") != TEST_MODE:
            raise FinalPackageProvenanceBindingError("TEST TWIN provenance must remain NON-EVIDENCE")
        if provenance_verification.get("prod_promotion_allowed") is not False:
            raise FinalPackageProvenanceBindingError("TEST TWIN provenance cannot permit PROD promotion")

    base_manifest, analysis, docx_bytes, base_package_bytes = FINAL.build_final_needs_package(
        records,
        ranking_result=ranking_result,
        adversarial_qa_result=adversarial_qa_result,
        source_register=source_register,
        evidence_mode=evidence_mode,
    )

    if base_manifest.get("research_id") != RESEARCH_ID:
        raise FinalPackageProvenanceBindingError("base package research mismatch")
    if base_manifest.get("evidence_mode") != evidence_mode:
        raise FinalPackageProvenanceBindingError("base package evidence-mode mismatch")
    if base_manifest.get("source_register_sha256") != source_register_sha256:
        raise FinalPackageProvenanceBindingError("base package source-register hash mismatch")
    if analysis.get("source_register_sha256") != source_register_sha256:
        raise FinalPackageProvenanceBindingError("NEEDS_ANALYSIS source-register hash mismatch")
    if analysis.get("source_export_sha256") != base_manifest.get("source_export_sha256"):
        raise FinalPackageProvenanceBindingError("source-export hash drift between analysis and base manifest")

    provenance_manifest_sha256 = _json_sha(source_provenance_manifest)
    provenance_verification_sha256 = _json_sha(provenance_verification)
    base_package_sha256 = _bytes_sha(base_package_bytes)

    release_authorized = (
        evidence_mode == PROD_MODE
        and base_manifest.get("public_release_authorized") is True
        and provenance_verification.get("verification_status") == "PASS"
        and provenance_verification.get("prod_promotion_allowed") is True
    )

    binding_manifest = {
        "schema_version": SCHEMA,
        "research_id": RESEARCH_ID,
        "stage": "FINAL_PACKAGE_SOURCE_PROVENANCE_BOUND",
        "evidence_mode": evidence_mode,
        "evidence_class": "CONTROL_ARTIFACT_NOT_EVIDENCE" if evidence_mode == PROD_MODE else TEST_MODE,
        "base_final_package_sha256": base_package_sha256,
        "source_export_sha256": base_manifest.get("source_export_sha256"),
        "source_register_sha256": source_register_sha256,
        "source_provenance_manifest_sha256": provenance_manifest_sha256,
        "source_provenance_verification_sha256": provenance_verification_sha256,
        "needs_analysis_sha256": base_manifest.get("needs_analysis_sha256"),
        "needs_analysis_docx_sha256": base_manifest.get("needs_analysis_docx_sha256"),
        "verified_source_count": provenance_verification.get("verified_source_count"),
        "secondary_evidence_numeric_points": 0,
        "project_activity_numeric_points": 0,
        "respondent_level_records_packaged_in_outer_package": False,
        "captured_source_snapshot_bytes_packaged": False,
        "test_twin_evidence_eligible": False,
        "prod_promotion_allowed": release_authorized,
        "public_release_authorized": release_authorized,
        "direct_base_package_release_without_this_binding_forbidden": True,
        "artifact_names": [
            "BASE_FINAL_NEEDS_PACKAGE.zip",
            "SOURCE_REGISTER_PROVENANCE.json",
            "SOURCE_REGISTER_PROVENANCE_VERIFICATION.json",
            "FINAL_PACKAGE_PROVENANCE_BINDING.json",
        ],
    }

    if evidence_mode == TEST_MODE:
        binding_manifest["prod_promotion_allowed"] = False
        binding_manifest["public_release_authorized"] = False

    binding_bytes = canonical_json_bytes(binding_manifest)
    provenance_manifest_bytes = canonical_json_bytes(source_provenance_manifest)
    provenance_verification_bytes = canonical_json_bytes(provenance_verification)

    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as archive:
        _zip_write(archive, "BASE_FINAL_NEEDS_PACKAGE.zip", base_package_bytes)
        _zip_write(archive, "SOURCE_REGISTER_PROVENANCE.json", provenance_manifest_bytes)
        _zip_write(archive, "SOURCE_REGISTER_PROVENANCE_VERIFICATION.json", provenance_verification_bytes)
        _zip_write(archive, "FINAL_PACKAGE_PROVENANCE_BINDING.json", binding_bytes)

    package_bytes = outer.getvalue()
    with zipfile.ZipFile(io.BytesIO(package_bytes), "r") as archive:
        embedded = json.loads(archive.read("FINAL_PACKAGE_PROVENANCE_BINDING.json"))
        if embedded != binding_manifest:
            raise FinalPackageProvenanceBindingError("embedded provenance-binding manifest mismatch")
        if _bytes_sha(archive.read("BASE_FINAL_NEEDS_PACKAGE.zip")) != base_package_sha256:
            raise FinalPackageProvenanceBindingError("embedded base-package SHA-256 mismatch")
        if _bytes_sha(archive.read("SOURCE_REGISTER_PROVENANCE.json")) != provenance_manifest_sha256:
            raise FinalPackageProvenanceBindingError("embedded provenance-manifest SHA-256 mismatch")
        if _bytes_sha(archive.read("SOURCE_REGISTER_PROVENANCE_VERIFICATION.json")) != provenance_verification_sha256:
            raise FinalPackageProvenanceBindingError("embedded provenance-verification SHA-256 mismatch")

    return binding_manifest, package_bytes
