from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from typing import Any

import adversarial_qa as QA
import disclosure_control as DISCLOSURE
import need_ranking_engine as ENGINE
import nf06_preingest as NF06
from render_needs_analysis_docx import render_needs_analysis_docx
from research_storage import RESEARCH_ID, canonical_json_bytes

SCHEMA = "eucons.ai4work_final_needs_package_gate.v0.1"
ANALYSIS_SCHEMA = "eucons.ai4work_needs_analysis.v0.1"
SOURCE_REGISTER_SCHEMA = "eucons.ai4work_source_register_snapshot.v0.1"
PROD_MODE = "PROD_REAL_EVIDENCE"
TEST_MODE = "TEST_TWIN_NON_EVIDENCE"
FIXED_ZIP_TIME = (2026, 8, 31, 0, 0, 0)

FORBIDDEN_PERSISTED_KEYS = {
    "name",
    "full_name",
    "first_name",
    "last_name",
    "cnp",
    "email",
    "phone",
    "telephone",
    "address",
    "exact_address",
    "exact_locality",
    "employer_name",
    "company_name",
    "ip",
    "ip_address",
    "user_agent",
    "device_id",
    "advertising_id",
    "cookie_id",
}


class FinalNeedsPackageError(ValueError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).strip().lower())
            keys.update(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_walk_keys(child))
    return keys


def _assert_no_forbidden_persisted_fields(records: list[dict[str, Any]]) -> None:
    found = sorted(_walk_keys(records) & FORBIDDEN_PERSISTED_KEYS)
    if found:
        raise FinalNeedsPackageError(
            "respondent records contain forbidden identifier/tracking fields: " + ", ".join(found)
        )


def _source_export_sha(records: list[dict[str, Any]], *, evidence_mode: str) -> str:
    if evidence_mode == PROD_MODE:
        return hashlib.sha256(NF06.canonical_export_bytes(records)).hexdigest()
    return _sha(records)


def _assert_records(records: list[dict[str, Any]], *, evidence_mode: str) -> str:
    if not isinstance(records, list) or not records:
        raise FinalNeedsPackageError("non-empty response batch required")
    _assert_no_forbidden_persisted_fields(records)
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise FinalNeedsPackageError(f"record[{index}] must be an object")
        if record.get("research_id") != RESEARCH_ID:
            raise FinalNeedsPackageError(f"record[{index}] research mismatch")
        if record.get("form_id") not in {ENGINE.ADULT_FORM, ENGINE.EMPLOYER_FORM}:
            raise FinalNeedsPackageError(f"record[{index}] unsupported form")
        profile = record.get("profile")
        if not isinstance(profile, dict) or profile.get("region") not in ENGINE.TARGET_REGIONS:
            raise FinalNeedsPackageError(f"record[{index}] target region missing/invalid")
        if evidence_mode == PROD_MODE and record.get("synthetic") is not False:
            raise FinalNeedsPackageError("PROD final package accepts only synthetic=false real records")
    return _source_export_sha(records, evidence_mode=evidence_mode)


def _assert_source_register(source_register: dict[str, Any], *, evidence_mode: str) -> str:
    if not isinstance(source_register, dict):
        raise FinalNeedsPackageError("source-register snapshot required")
    if source_register.get("schema_version") != SOURCE_REGISTER_SCHEMA:
        raise FinalNeedsPackageError("unsupported source-register snapshot schema")
    if source_register.get("research_id") != RESEARCH_ID:
        raise FinalNeedsPackageError("source-register research mismatch")
    if evidence_mode == PROD_MODE:
        if source_register.get("status") != "VERIFIED_FOR_FINAL_PACKAGE":
            raise FinalNeedsPackageError("PROD source register must be VERIFIED_FOR_FINAL_PACKAGE")
        if source_register.get("test_twin_evidence_eligible") is not False:
            raise FinalNeedsPackageError("source register must explicitly reject TEST TWIN evidence eligibility")
    elif source_register.get("status") != TEST_MODE:
        raise FinalNeedsPackageError("TEST TWIN source register must be marked NON-EVIDENCE")

    entries = source_register.get("entries")
    if not isinstance(entries, list) or not entries:
        raise FinalNeedsPackageError("source register must contain at least one source")
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise FinalNeedsPackageError(f"source[{index}] must be an object")
        source_id = entry.get("source_id")
        if not isinstance(source_id, str) or re.fullmatch(r"S\d{2,}", source_id) is None:
            raise FinalNeedsPackageError(f"source[{index}] invalid source_id")
        if source_id in seen:
            raise FinalNeedsPackageError("duplicate source_id in source register")
        seen.add(source_id)
        for field in ("publisher", "title", "publication_date", "url", "evidence_role"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise FinalNeedsPackageError(f"source[{index}] missing {field}")
        if evidence_mode == PROD_MODE and not entry["url"].startswith("https://"):
            raise FinalNeedsPackageError("PROD source URL must use HTTPS")
        if entry.get("h1_h5_numeric_points") != 0:
            raise FinalNeedsPackageError("secondary/source-register material cannot add H1-H5 numeric points")
        if entry.get("project_activity_as_need_evidence") is not False:
            raise FinalNeedsPackageError("project activity must not be treated as evidence of need")
        if entry.get("numeric_rank_eligible") is not False:
            raise FinalNeedsPackageError("source-register entries must be non-numeric for H1-H5 ranking")
    return _sha(source_register)


def _assert_prod_analysis_bindings(
    records: list[dict[str, Any]],
    *,
    ranking_result: dict[str, Any],
    adversarial_qa_result: dict[str, Any],
    source_export_sha256: str,
) -> None:
    if ranking_result.get("schema_version") != ENGINE.ENGINE_SCHEMA:
        raise FinalNeedsPackageError("unsupported ranking schema")
    if ranking_result.get("research_id") != RESEARCH_ID:
        raise FinalNeedsPackageError("ranking research mismatch")
    if ranking_result.get("evidence_class") != "PROD_DERIVED_ANALYSIS":
        raise FinalNeedsPackageError("ranking must be PROD_DERIVED_ANALYSIS")
    if ranking_result.get("source_evidence_class") != PROD_MODE:
        raise FinalNeedsPackageError("ranking must derive from PROD_REAL_EVIDENCE")
    if ranking_result.get("source_export_sha256") != source_export_sha256:
        raise FinalNeedsPackageError("ranking source-export binding mismatch")
    if ranking_result.get("representativeness_claim_allowed") is not False:
        raise FinalNeedsPackageError("ranking representativeness boundary missing")
    if ranking_result.get("causal_claim_allowed") is not False:
        raise FinalNeedsPackageError("ranking causal boundary missing")
    if ranking_result.get("respondent_weighting_applied") is not False:
        raise FinalNeedsPackageError("respondent weighting is forbidden")
    if ranking_result.get("secondary_evidence_numeric_points") != 0:
        raise FinalNeedsPackageError("secondary evidence cannot alter H1-H5 rank")
    if ranking_result.get("project_activity_numeric_points") != 0:
        raise FinalNeedsPackageError("project activity cannot alter H1-H5 rank")

    if adversarial_qa_result.get("schema_version") != QA.SCHEMA:
        raise FinalNeedsPackageError("unsupported adversarial-QA schema")
    if adversarial_qa_result.get("research_id") != RESEARCH_ID:
        raise FinalNeedsPackageError("adversarial-QA research mismatch")
    if adversarial_qa_result.get("source_evidence_class") != PROD_MODE:
        raise FinalNeedsPackageError("adversarial QA must bind PROD_REAL_EVIDENCE")
    if adversarial_qa_result.get("source_export_sha256") != source_export_sha256:
        raise FinalNeedsPackageError("adversarial-QA source-export binding mismatch")
    if adversarial_qa_result.get("ranking_result_sha256") != _sha(ranking_result):
        raise FinalNeedsPackageError("adversarial-QA ranking binding mismatch")
    if adversarial_qa_result.get("qa_completed") is not True:
        raise FinalNeedsPackageError("adversarial QA is incomplete")
    if adversarial_qa_result.get("collection_must_continue") is not False:
        raise FinalNeedsPackageError("adversarial QA requires collection to continue")
    if adversarial_qa_result.get("needs_analysis_may_proceed") is not True:
        raise FinalNeedsPackageError("adversarial QA does not permit NEEDS_ANALYSIS")
    if adversarial_qa_result.get("automatic_record_exclusion_applied") is not False:
        raise FinalNeedsPackageError("automatic record exclusion is forbidden")
    if adversarial_qa_result.get("respondent_weighting_applied") is not False:
        raise FinalNeedsPackageError("adversarial QA cannot apply respondent weights")
    if adversarial_qa_result.get("identity_or_device_linkage_used") is not False:
        raise FinalNeedsPackageError("identity/device linkage is forbidden")
    if adversarial_qa_result.get("secondary_evidence_numeric_points") != 0:
        raise FinalNeedsPackageError("QA secondary evidence numeric points must remain zero")
    if adversarial_qa_result.get("project_activity_numeric_points") != 0:
        raise FinalNeedsPackageError("QA project activity numeric points must remain zero")
    if adversarial_qa_result.get("representativeness_claim_allowed") is not False:
        raise FinalNeedsPackageError("QA representativeness boundary missing")
    if adversarial_qa_result.get("causal_claim_allowed") is not False:
        raise FinalNeedsPackageError("QA causal boundary missing")

    adult_n = sum(record.get("form_id") == ENGINE.ADULT_FORM for record in records)
    employer_n = sum(record.get("form_id") == ENGINE.EMPLOYER_FORM for record in records)
    if ranking_result.get("adult_n") != adult_n or ranking_result.get("employer_n") != employer_n:
        raise FinalNeedsPackageError("ranking population counts do not reconcile with source records")


def _assert_test_twin_bindings(
    *,
    ranking_result: dict[str, Any],
    adversarial_qa_result: dict[str, Any],
) -> None:
    if ranking_result.get("evidence_class") != TEST_MODE:
        raise FinalNeedsPackageError("TEST TWIN ranking fixture must be explicitly NON-EVIDENCE")
    if adversarial_qa_result.get("evidence_class") != TEST_MODE:
        raise FinalNeedsPackageError("TEST TWIN QA fixture must be explicitly NON-EVIDENCE")
    if ranking_result.get("public_release_authorized") is not False:
        raise FinalNeedsPackageError("TEST TWIN ranking cannot authorize public release")
    if adversarial_qa_result.get("public_release_authorized") is not False:
        raise FinalNeedsPackageError("TEST TWIN QA cannot authorize public release")
    if adversarial_qa_result.get("qa_completed") is not True:
        raise FinalNeedsPackageError("TEST TWIN QA mechanics must be complete")


def _public_sample_tables(records: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        {
            "population": "adults" if record["form_id"] == ENGINE.ADULT_FORM else "employers",
            "region": record["profile"]["region"],
        }
        for record in records
    ]
    tables: dict[str, Any] = {}
    for table_id, dimensions in (
        ("population", ["population"]),
        ("region", ["region"]),
        ("population_region", ["population", "region"]),
    ):
        cells = DISCLOSURE.build_public_count_table(
            rows,
            dimensions=dimensions,
            minimum_n=DISCLOSURE.MIN_PUBLIC_CELL_N,
            protect_grand_total=True,
        )
        DISCLOSURE.assert_public_table_safe(
            cells,
            minimum_n=DISCLOSURE.MIN_PUBLIC_CELL_N,
            protect_grand_total=True,
        )
        tables[table_id] = {
            "dimensions": dimensions,
            "minimum_public_cell_n": DISCLOSURE.MIN_PUBLIC_CELL_N,
            "cells": cells,
        }
    return tables


def _sanitised_source_register(source_register: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": source_register["schema_version"],
        "status": source_register["status"],
        "entries": [
            {
                "source_id": item["source_id"],
                "publisher": item["publisher"],
                "title": item["title"],
                "publication_date": item["publication_date"],
                "url": item["url"],
                "evidence_role": item["evidence_role"],
                "h1_h5_numeric_points": 0,
            }
            for item in source_register["entries"]
        ],
    }


def _assemble_needs_analysis(
    records: list[dict[str, Any]],
    *,
    ranking_result: dict[str, Any],
    adversarial_qa_result: dict[str, Any],
    source_register: dict[str, Any],
    source_export_sha256: str,
    source_register_sha256: str,
    evidence_mode: str,
) -> dict[str, Any]:
    adults = [record for record in records if record["form_id"] == ENGINE.ADULT_FORM]
    employers = [record for record in records if record["form_id"] == ENGINE.EMPLOYER_FORM]
    competing = bool(adversarial_qa_result.get("competing_orders_required"))
    single_definitive = bool(adversarial_qa_result.get("single_definitive_rank_allowed"))
    if competing and single_definitive:
        raise FinalNeedsPackageError("QA cannot require competing orders and allow a single definitive rank")

    return {
        "schema_version": ANALYSIS_SCHEMA,
        "research_id": RESEARCH_ID,
        "stage": "NEEDS_ANALYSIS_ASSEMBLED",
        "evidence_mode": evidence_mode,
        "evidence_class": "PROD_DERIVED_ANALYSIS" if evidence_mode == PROD_MODE else TEST_MODE,
        "source_export_sha256": source_export_sha256,
        "ranking_result_sha256": _sha(ranking_result),
        "adversarial_qa_result_sha256": _sha(adversarial_qa_result),
        "source_register_sha256": source_register_sha256,
        "scope_statement": (
            "Rezultatele descriu exclusiv lotul eligibil de răspunsuri reale care a trecut controalele "
            "NF06 și QA; nu reprezintă o estimare de prevalență pentru populația regională."
            if evidence_mode == PROD_MODE
            else "TEST TWIN NON-EVIDENCE: documentul exercită exclusiv mecanica de asamblare și nu descrie persoane, firme sau nevoi reale."
        ),
        "methodology_statement": (
            "Ierarhia H1–H5 folosește numai indicatorii direcți preînregistrați din răspunsurile adulților și angajatorilor, "
            "cu componente populaționale egale 0,5/0,5, aritmetică rațională exactă și fără ponderare a respondenților. "
            "Cercetarea secundară contextualizează rezultatele, dar contribuția sa numerică la H1–H5 este zero."
        ),
        "sample": {
            "adult_n": len(adults),
            "employer_n": len(employers),
            "total_n": len(records),
            "public_disclosure_controlled_tables": _public_sample_tables(records),
        },
        "ranking": {
            "dimensions": ranking_result.get("dimensions", {}),
            "pooled_equal_population_rank": ranking_result.get("pooled_equal_population_rank", []),
            "adult_component_rank": ranking_result.get("adult_component_rank", []),
            "employer_component_rank": ranking_result.get("employer_component_rank", []),
            "regional_equal_population_views": ranking_result.get("regional_equal_population_views", {}),
            "single_definitive_rank_allowed": single_definitive,
            "competing_orders_required": competing,
            "rank_basis": ranking_result.get("rank_basis"),
            "tie_rule": ranking_result.get("tie_rule"),
        },
        "adversarial_qa": {
            "overall_stability_label": adversarial_qa_result.get("overall_stability_label"),
            "qa_completed": adversarial_qa_result.get("qa_completed"),
            "collection_must_continue": adversarial_qa_result.get("collection_must_continue"),
            "needs_analysis_may_proceed": adversarial_qa_result.get("needs_analysis_may_proceed"),
            "competing_orders_required": competing,
            "single_definitive_rank_allowed": single_definitive,
            "dominant_channel_triggered": bool(adversarial_qa_result.get("dominant_channel_triggered")),
            "repeated_signature_triggered": bool(adversarial_qa_result.get("repeated_signature_triggered")),
            "sparse_profile_triggered": bool(adversarial_qa_result.get("sparse_profile_triggered")),
            "zero_profile_cell_caveat_count": len(adversarial_qa_result.get("zero_profile_cell_caveats", [])),
        },
        "source_register": _sanitised_source_register(source_register),
        "secondary_evidence_numeric_points": 0,
        "project_activity_numeric_points": 0,
        "representativeness_claim_allowed": False,
        "causal_claim_allowed": False,
        "respondent_level_records_in_public_artifacts": False,
        "commercial_tracking_data_in_public_artifacts": False,
        "limitations": [
            "Rezultatele numerice H1–H5 sunt legate de lotul eligibil și nu autorizează o afirmație de reprezentativitate populațională.",
            "Activitățile, finanțările și oferta de formare ale proiectelor nu sunt utilizate ca dovadă a existenței unei nevoi.",
            "Cercetarea secundară poate contextualiza sau contesta interpretarea, dar nu modifică numeric ordinea H1–H5.",
            "Celulele mici sunt suprimate conform controlului de divulgare; zero/sparse cells rămân limitări explicite.",
            "Dacă QA solicită ordine concurente, raportul nu poate prezenta o singură ierarhie drept definitivă.",
        ],
        "package_release_pending": True,
        "public_release_authorized": False,
        "test_twin_evidence_eligible": False,
    }


def _assert_docx_bound(docx_bytes: bytes, *, analysis_sha256: str) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as archive:
            names = set(archive.namelist())
            required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
            if not required.issubset(names):
                raise FinalNeedsPackageError("DOCX package is missing required parts")
            document_xml = archive.read("word/document.xml").decode("utf-8")
    except (zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise FinalNeedsPackageError("invalid DOCX package") from exc
    if analysis_sha256 not in document_xml:
        raise FinalNeedsPackageError("DOCX is not visibly bound to the exact NEEDS_ANALYSIS hash")


def _zip_write(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, payload)


def build_final_needs_package(
    records: list[dict[str, Any]],
    *,
    ranking_result: dict[str, Any],
    adversarial_qa_result: dict[str, Any],
    source_register: dict[str, Any],
    evidence_mode: str,
) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    """Build NEEDS_ANALYSIS + DOCX + source register + manifest as one bound package.

    PROD mode is fail-closed to the exact real source export, completed stable-enough
    adversarial QA, disclosure-controlled public sample tables, and a verified source
    register whose secondary/project material contributes zero H1-H5 numeric points.
    TEST TWIN mode exists only to exercise packaging mechanics and can never authorize
    release or promotion as evidence.
    """
    if evidence_mode not in {PROD_MODE, TEST_MODE}:
        raise FinalNeedsPackageError("unsupported evidence mode")
    source_export_sha = _assert_records(records, evidence_mode=evidence_mode)
    source_register_sha = _assert_source_register(source_register, evidence_mode=evidence_mode)

    if evidence_mode == PROD_MODE:
        _assert_prod_analysis_bindings(
            records,
            ranking_result=ranking_result,
            adversarial_qa_result=adversarial_qa_result,
            source_export_sha256=source_export_sha,
        )
    else:
        _assert_test_twin_bindings(
            ranking_result=ranking_result,
            adversarial_qa_result=adversarial_qa_result,
        )

    analysis = _assemble_needs_analysis(
        records,
        ranking_result=ranking_result,
        adversarial_qa_result=adversarial_qa_result,
        source_register=source_register,
        source_export_sha256=source_export_sha,
        source_register_sha256=source_register_sha,
        evidence_mode=evidence_mode,
    )
    analysis_bytes = canonical_json_bytes(analysis)
    analysis_sha = hashlib.sha256(analysis_bytes).hexdigest()
    docx_bytes = render_needs_analysis_docx(analysis)
    _assert_docx_bound(docx_bytes, analysis_sha256=analysis_sha)

    source_register_bytes = canonical_json_bytes(source_register)
    manifest = {
        "schema_version": SCHEMA,
        "research_id": RESEARCH_ID,
        "stage": "FINAL_NEEDS_PACKAGE_BOUND",
        "evidence_mode": evidence_mode,
        "evidence_class": "CONTROL_ARTIFACT_NOT_EVIDENCE" if evidence_mode == PROD_MODE else TEST_MODE,
        "source_export_sha256": source_export_sha,
        "needs_analysis_sha256": analysis_sha,
        "needs_analysis_docx_sha256": hashlib.sha256(docx_bytes).hexdigest(),
        "source_register_sha256": source_register_sha,
        "ranking_result_sha256": _sha(ranking_result),
        "adversarial_qa_result_sha256": _sha(adversarial_qa_result),
        "respondent_level_records_packaged": False,
        "automatic_record_exclusion_applied": False,
        "respondent_weighting_applied": False,
        "secondary_evidence_numeric_points": 0,
        "project_activity_numeric_points": 0,
        "representativeness_claim_allowed": False,
        "causal_claim_allowed": False,
        "test_twin_evidence_eligible": False,
        "prod_promotion_allowed": evidence_mode == PROD_MODE,
        "public_release_authorized": evidence_mode == PROD_MODE,
        "artifact_names": [
            "NEEDS_ANALYSIS.json",
            "NEEDS_ANALYSIS.docx",
            "SOURCE_REGISTER.json",
            "FINAL_PACKAGE_MANIFEST.json",
        ],
    }
    manifest_bytes = canonical_json_bytes(manifest)

    package = io.BytesIO()
    with zipfile.ZipFile(package, "w") as archive:
        _zip_write(archive, "NEEDS_ANALYSIS.json", analysis_bytes)
        _zip_write(archive, "NEEDS_ANALYSIS.docx", docx_bytes)
        _zip_write(archive, "SOURCE_REGISTER.json", source_register_bytes)
        _zip_write(archive, "FINAL_PACKAGE_MANIFEST.json", manifest_bytes)

    if evidence_mode == TEST_MODE:
        manifest["prod_promotion_allowed"] = False
        manifest["public_release_authorized"] = False
    return manifest, analysis, docx_bytes, package.getvalue()
