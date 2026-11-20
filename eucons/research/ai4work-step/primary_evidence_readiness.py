from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from channel_provenance import ChannelProvenanceError, validate_recruitment_channel_id
from research_storage import RESEARCH_ID, canonical_json_bytes

PROD_EVIDENCE_CLASS = "PROD_REAL_EVIDENCE"
METHOD_EVIDENCE_CLASS = "METHOD_PLAN_NOT_EVIDENCE"
TARGET_REGIONS = ("Centru", "Sud-Muntenia", "Sud-Vest Oltenia")
ADULT_FORM = "AI4WORK_ADULTS_V1"
EMPLOYER_FORM = "AI4WORK_EMPLOYERS_V1"
FORM_AUDIENCE = {
    ADULT_FORM: "adults",
    EMPLOYER_FORM: "employers",
}
CHANNEL_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{2,48}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REGISTER_KEYS = {"schema_version", "research_id", "invitation_catalog", "entries"}
CATALOG_BINDING_KEYS = {"reference", "sha256"}
ENTRY_KEYS = {
    "channel_id",
    "channel_type",
    "region_scope",
    "audience_scope",
    "invitation_version",
    "opened_at",
    "closed_at",
    "distributor_role",
    "non_coercion_confirmed",
}


class PrimaryEvidenceReadinessError(ValueError):
    pass


def _parse_ts(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PrimaryEvidenceReadinessError(f"{field} must be a non-empty ISO timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PrimaryEvidenceReadinessError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise PrimaryEvidenceReadinessError(f"{field} must include timezone information")
    return parsed.astimezone(timezone.utc)


def _positive_int(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PrimaryEvidenceReadinessError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PrimaryEvidenceReadinessError(f"{field} must be a non-negative integer")
    return value


def _ratio(value: Any, *, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise PrimaryEvidenceReadinessError(f"{field} must be numeric")
    number = float(value)
    if not 0 < number <= 1:
        raise PrimaryEvidenceReadinessError(f"{field} must be in (0, 1]")
    return number


def _bounded_share(value: Any, *, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise PrimaryEvidenceReadinessError(f"{field} must be numeric")
    number = float(value)
    if not 0 <= number <= 1:
        raise PrimaryEvidenceReadinessError(f"{field} must be in [0, 1]")
    return number


def _validate_method_frame(frame: Any) -> dict[str, Any]:
    if not isinstance(frame, dict):
        raise PrimaryEvidenceReadinessError("method frame must be an object")
    if frame.get("research_id") != RESEARCH_ID:
        raise PrimaryEvidenceReadinessError("method frame research_id mismatch")
    if frame.get("frame_status") != "APPROVED_FOR_PROD":
        raise PrimaryEvidenceReadinessError("method frame must be APPROVED_FOR_PROD before primary synthesis readiness")
    if frame.get("evidence_class") != METHOD_EVIDENCE_CLASS:
        raise PrimaryEvidenceReadinessError("method frame must remain METHOD_PLAN_NOT_EVIDENCE")
    approval = frame.get("approval")
    if not isinstance(approval, dict) or approval.get("approved") is not True or approval.get("approved_for_prod") is not True:
        raise PrimaryEvidenceReadinessError("method frame approval is incomplete")
    handoff = frame.get("nf06_handoff")
    if not isinstance(handoff, dict) or handoff.get("eligible_now") is not True:
        raise PrimaryEvidenceReadinessError("method frame is not NF06-handoff eligible")
    thresholds = ((frame.get("sampling_design") or {}).get("provisional_readiness_thresholds"))
    if not isinstance(thresholds, dict) or thresholds.get("status") != "METHOD_RULE_NOT_EVIDENCE":
        raise PrimaryEvidenceReadinessError("method readiness thresholds are missing or not frozen as METHOD_RULE_NOT_EVIDENCE")
    return thresholds


def _validate_channel_register(register: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(register, dict) or set(register) != REGISTER_KEYS:
        raise PrimaryEvidenceReadinessError(f"channel register fields must be exactly {sorted(REGISTER_KEYS)}")
    if register.get("schema_version") != "eucons.ai4work_collection_channel_register.v0.2":
        raise PrimaryEvidenceReadinessError("unsupported collection-channel register schema")
    if register.get("research_id") != RESEARCH_ID:
        raise PrimaryEvidenceReadinessError("channel register research_id mismatch")

    catalog_binding = register.get("invitation_catalog")
    if not isinstance(catalog_binding, dict) or set(catalog_binding) != CATALOG_BINDING_KEYS:
        raise PrimaryEvidenceReadinessError(
            f"channel invitation_catalog fields must be exactly {sorted(CATALOG_BINDING_KEYS)}"
        )
    reference = catalog_binding.get("reference")
    if (
        not isinstance(reference, str)
        or not reference.strip()
        or "/" in reference
        or "\\" in reference
        or reference in {".", ".."}
    ):
        raise PrimaryEvidenceReadinessError("channel invitation catalog reference must be one local filename")
    digest = catalog_binding.get("sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise PrimaryEvidenceReadinessError("channel invitation catalog binding needs a lowercase SHA-256")

    entries = register.get("entries")
    if not isinstance(entries, list) or not entries:
        raise PrimaryEvidenceReadinessError("channel register must contain at least one entry")

    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise PrimaryEvidenceReadinessError(f"channel register entry fields must be exactly {sorted(ENTRY_KEYS)}")
        try:
            channel_id = validate_recruitment_channel_id(entry.get("channel_id"))
        except ChannelProvenanceError as exc:
            raise PrimaryEvidenceReadinessError(str(exc)) from exc
        if channel_id in by_id:
            raise PrimaryEvidenceReadinessError("duplicate channel_id in channel register")
        channel_type = entry.get("channel_type")
        if not isinstance(channel_type, str) or not CHANNEL_TYPE_RE.fullmatch(channel_type):
            raise PrimaryEvidenceReadinessError("channel_type must be a bounded lowercase code")
        region_scope = entry.get("region_scope")
        if not isinstance(region_scope, list) or not region_scope or any(region not in TARGET_REGIONS for region in region_scope):
            raise PrimaryEvidenceReadinessError("channel region_scope must contain only target regions")
        if len(region_scope) != len(set(region_scope)):
            raise PrimaryEvidenceReadinessError("channel region_scope contains duplicates")
        audience_scope = entry.get("audience_scope")
        if not isinstance(audience_scope, list) or not audience_scope or any(item not in {"adults", "employers"} for item in audience_scope):
            raise PrimaryEvidenceReadinessError("channel audience_scope must contain adults and/or employers")
        if len(audience_scope) != len(set(audience_scope)):
            raise PrimaryEvidenceReadinessError("channel audience_scope contains duplicates")
        for field in ("invitation_version", "distributor_role"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise PrimaryEvidenceReadinessError(f"channel {field} is required")
        opened = _parse_ts(entry.get("opened_at"), field="channel.opened_at")
        closed = _parse_ts(entry.get("closed_at"), field="channel.closed_at")
        if closed < opened:
            raise PrimaryEvidenceReadinessError("channel collection window is inverted")
        if entry.get("non_coercion_confirmed") is not True:
            raise PrimaryEvidenceReadinessError("channel non_coercion_confirmed must be true")
        by_id[channel_id] = entry
    return by_id


def _validate_sensitivity_artifact(value: Any, *, required_scopes: set[str]) -> None:
    if not isinstance(value, dict):
        raise PrimaryEvidenceReadinessError("dominant-channel sensitivity analysis is required")
    if value.get("status") != "PASS":
        raise PrimaryEvidenceReadinessError("dominant-channel sensitivity analysis must have PASS status")
    if not isinstance(value.get("reference"), str) or not value["reference"].strip():
        raise PrimaryEvidenceReadinessError("dominant-channel sensitivity analysis needs a documented reference")
    sha = value.get("sha256")
    if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
        raise PrimaryEvidenceReadinessError("dominant-channel sensitivity analysis needs a lowercase SHA-256")
    covered_scopes = value.get("covered_scopes")
    if not isinstance(covered_scopes, list) or len(covered_scopes) != len(set(covered_scopes)):
        raise PrimaryEvidenceReadinessError("dominant-channel sensitivity analysis covered_scopes must be a duplicate-free list")
    if set(covered_scopes) != required_scopes:
        raise PrimaryEvidenceReadinessError("dominant-channel sensitivity analysis must cover exactly every exceeded concentration scope")


def _validate_form_region_channel_provenance(
    value: Any,
    *,
    form_region_counts: dict[str, Any],
    region_channel_ids: dict[str, Any],
    register_by_id: dict[str, dict[str, Any]],
) -> None:
    if not isinstance(value, dict) or set(value) != set(FORM_AUDIENCE):
        raise PrimaryEvidenceReadinessError("manifest form_region_channel_ids must cover both frozen forms exactly")

    per_region_union: dict[str, set[str]] = {region: set() for region in TARGET_REGIONS}
    for form_id, audience in FORM_AUDIENCE.items():
        region_map = value.get(form_id)
        if not isinstance(region_map, dict) or set(region_map) != set(TARGET_REGIONS):
            raise PrimaryEvidenceReadinessError(f"form_region_channel_ids for {form_id} must cover all target regions exactly")
        for region in TARGET_REGIONS:
            used_ids = region_map.get(region)
            if not isinstance(used_ids, list) or len(used_ids) != len(set(used_ids)):
                raise PrimaryEvidenceReadinessError(f"form-region channel ids for {form_id}/{region} must be a duplicate-free list")
            if (form_region_counts.get(form_id) or {}).get(region, 0) > 0 and not used_ids:
                raise PrimaryEvidenceReadinessError(f"records exist for {form_id}/{region} but no form-specific channel provenance is present")
            for channel_id in used_ids:
                try:
                    channel_id = validate_recruitment_channel_id(channel_id)
                except ChannelProvenanceError as exc:
                    raise PrimaryEvidenceReadinessError(str(exc)) from exc
                entry = register_by_id.get(channel_id)
                if entry is None:
                    raise PrimaryEvidenceReadinessError(f"used channel {channel_id} is absent from frozen channel register")
                if region not in entry["region_scope"]:
                    raise PrimaryEvidenceReadinessError(f"used channel {channel_id} is not authorised for {region}")
                if audience not in entry["audience_scope"]:
                    raise PrimaryEvidenceReadinessError(
                        f"used channel {channel_id} is not authorised for {audience} audience in {region}"
                    )
                per_region_union[region].add(channel_id)

    for region in TARGET_REGIONS:
        region_ids = region_channel_ids.get(region)
        if not isinstance(region_ids, list) or set(region_ids) != per_region_union[region]:
            raise PrimaryEvidenceReadinessError(
                f"region_channel_ids for {region} do not reconcile with form-specific channel provenance"
            )


def _validated_count_map(
    value: Any,
    *,
    expected_ids: set[str],
    denominator: int,
    field: str,
) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != expected_ids:
        raise PrimaryEvidenceReadinessError(f"{field} keys must exactly match the used channel ids")
    counts: dict[str, int] = {}
    for channel_id, count in value.items():
        try:
            validate_recruitment_channel_id(channel_id)
        except ChannelProvenanceError as exc:
            raise PrimaryEvidenceReadinessError(str(exc)) from exc
        counts[channel_id] = _positive_int(count, field=f"{field}.{channel_id}")
    if sum(counts.values()) != denominator:
        raise PrimaryEvidenceReadinessError(f"{field} does not reconcile with its stratum denominator")
    return counts


def _share_from_counts(counts: dict[str, int], denominator: int) -> float:
    if denominator <= 0 or not counts:
        return 0.0
    return max(counts.values()) / denominator


def _validate_channel_concentration_aggregates(
    manifest: dict[str, Any],
    *,
    form_region_counts: dict[str, Any],
    region_channel_ids: dict[str, Any],
    form_region_channel_ids: dict[str, Any],
    channel_share_max: float,
) -> set[str]:
    region_counts = manifest.get("region_counts")
    if not isinstance(region_counts, dict) or set(region_counts) != set(TARGET_REGIONS):
        raise PrimaryEvidenceReadinessError("manifest region_counts must cover all target regions exactly")

    region_channel_counts = manifest.get("region_channel_counts")
    form_region_channel_counts = manifest.get("form_region_channel_counts")
    region_shares = manifest.get("region_dominant_channel_share")
    form_region_shares = manifest.get("form_region_dominant_channel_share")
    if not isinstance(region_channel_counts, dict) or set(region_channel_counts) != set(TARGET_REGIONS):
        raise PrimaryEvidenceReadinessError("manifest region_channel_counts must cover all target regions exactly")
    if not isinstance(form_region_channel_counts, dict) or set(form_region_channel_counts) != set(FORM_AUDIENCE):
        raise PrimaryEvidenceReadinessError("manifest form_region_channel_counts must cover both frozen forms exactly")
    if not isinstance(region_shares, dict) or set(region_shares) != set(TARGET_REGIONS):
        raise PrimaryEvidenceReadinessError("manifest region_dominant_channel_share must cover all target regions exactly")
    if not isinstance(form_region_shares, dict) or set(form_region_shares) != set(FORM_AUDIENCE):
        raise PrimaryEvidenceReadinessError("manifest form_region_dominant_channel_share must cover both frozen forms exactly")

    global_reconstructed: dict[str, int] = {}
    form_global_reconstructed: dict[str, int] = {}
    exceeded_scopes: set[str] = set()

    for region in TARGET_REGIONS:
        denominator = _nonnegative_int(region_counts.get(region), field=f"region_counts.{region}")
        expected_ids = set(region_channel_ids.get(region) or [])
        counts = _validated_count_map(
            region_channel_counts.get(region),
            expected_ids=expected_ids,
            denominator=denominator,
            field=f"region_channel_counts.{region}",
        )
        for channel_id, count in counts.items():
            global_reconstructed[channel_id] = global_reconstructed.get(channel_id, 0) + count
        recomputed_share = _share_from_counts(counts, denominator)
        declared_share = _bounded_share(
            region_shares.get(region),
            field=f"region_dominant_channel_share.{region}",
        )
        if abs(declared_share - recomputed_share) > 1e-12:
            raise PrimaryEvidenceReadinessError(f"region dominant-channel share does not reconcile in {region}")
        if recomputed_share > channel_share_max:
            exceeded_scopes.add(f"region:{region}")

    for form_id in FORM_AUDIENCE:
        counts_by_region = form_region_channel_counts.get(form_id)
        shares_by_region = form_region_shares.get(form_id)
        ids_by_region = form_region_channel_ids.get(form_id)
        if not isinstance(counts_by_region, dict) or set(counts_by_region) != set(TARGET_REGIONS):
            raise PrimaryEvidenceReadinessError(f"form_region_channel_counts for {form_id} must cover all target regions exactly")
        if not isinstance(shares_by_region, dict) or set(shares_by_region) != set(TARGET_REGIONS):
            raise PrimaryEvidenceReadinessError(f"form_region_dominant_channel_share for {form_id} must cover all target regions exactly")
        if not isinstance(ids_by_region, dict) or set(ids_by_region) != set(TARGET_REGIONS):
            raise PrimaryEvidenceReadinessError(f"form_region_channel_ids for {form_id} must cover all target regions exactly")
        for region in TARGET_REGIONS:
            denominator = _nonnegative_int(
                (form_region_counts.get(form_id) or {}).get(region),
                field=f"form_region_counts.{form_id}.{region}",
            )
            expected_ids = set(ids_by_region.get(region) or [])
            counts = _validated_count_map(
                counts_by_region.get(region),
                expected_ids=expected_ids,
                denominator=denominator,
                field=f"form_region_channel_counts.{form_id}.{region}",
            )
            for channel_id, count in counts.items():
                form_global_reconstructed[channel_id] = form_global_reconstructed.get(channel_id, 0) + count
            recomputed_share = _share_from_counts(counts, denominator)
            declared_share = _bounded_share(
                shares_by_region.get(region),
                field=f"form_region_dominant_channel_share.{form_id}.{region}",
            )
            if abs(declared_share - recomputed_share) > 1e-12:
                raise PrimaryEvidenceReadinessError(
                    f"form-region dominant-channel share does not reconcile for {form_id}/{region}"
                )
            if recomputed_share > channel_share_max:
                exceeded_scopes.add(f"form_region:{form_id}:{region}")

    manifest_channels = manifest.get("channel_counts")
    if not isinstance(manifest_channels, dict):
        raise PrimaryEvidenceReadinessError("manifest channel_counts must be an object")
    normalized_manifest_channels = {
        channel_id: _positive_int(count, field=f"channel_counts.{channel_id}")
        for channel_id, count in manifest_channels.items()
    }
    if normalized_manifest_channels != global_reconstructed:
        raise PrimaryEvidenceReadinessError("region_channel_counts do not reconcile with global channel_counts")
    if normalized_manifest_channels != form_global_reconstructed:
        raise PrimaryEvidenceReadinessError("form_region_channel_counts do not reconcile with global channel_counts")

    global_denominator = _positive_int(manifest.get("record_count"), field="record_count")
    recomputed_global_share = _share_from_counts(normalized_manifest_channels, global_denominator)
    declared_global_share = _bounded_share(
        manifest.get("dominant_channel_share"),
        field="dominant_channel_share",
    )
    if abs(declared_global_share - recomputed_global_share) > 1e-12:
        raise PrimaryEvidenceReadinessError("manifest dominant_channel_share does not reconcile with channel_counts")
    if recomputed_global_share > channel_share_max:
        exceeded_scopes.add("global")

    return exceeded_scopes


def assert_primary_evidence_ready_for_synthesis(
    manifest: Any,
    *,
    method_frame: dict[str, Any],
    channel_register: dict[str, Any],
    dominant_channel_sensitivity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed until a real NF06-preflight batch meets frozen method coverage.

    This is a PRE-SYNTHESIS method/provenance gate. Passing it does not make the
    non-probability sample representative and does not prove any need. It only
    establishes that the real PROD batch has enough frozen coverage to enter
    synthesis/adversarial QA under the approved method frame.
    """
    thresholds = _validate_method_frame(method_frame)
    if not isinstance(manifest, dict):
        raise PrimaryEvidenceReadinessError("NF06 pre-ingest manifest must be an object")
    if manifest.get("schema_version") != "eucons.ai4work_nf06_preingest_manifest.v0.6":
        raise PrimaryEvidenceReadinessError("unsupported NF06 pre-ingest manifest schema")
    if manifest.get("research_id") != RESEARCH_ID:
        raise PrimaryEvidenceReadinessError("manifest research_id mismatch")
    if manifest.get("evidence_class") != PROD_EVIDENCE_CLASS or manifest.get("non_evidence") is not False:
        raise PrimaryEvidenceReadinessError("TEST TWIN or non-PROD manifests cannot enter primary synthesis")
    if manifest.get("prod_promotion_eligible") is not True:
        raise PrimaryEvidenceReadinessError("NF06 pre-ingest manifest is not PROD-promotion eligible")
    if manifest.get("channel_concentration_aggregates_emitted") is not True:
        raise PrimaryEvidenceReadinessError("NF06 pre-ingest manifest lacks channel-concentration aggregates")

    register_by_id = _validate_channel_register(channel_register)
    register_sha = hashlib.sha256(canonical_json_bytes(channel_register)).hexdigest()
    if manifest.get("collection_channel_register_sha256") != register_sha:
        raise PrimaryEvidenceReadinessError("channel register bytes do not match the NF06-bound SHA-256")

    adult_min = _positive_int(thresholds.get("adults_total_valid_min"), field="adults_total_valid_min")
    adult_region_min = _positive_int(thresholds.get("adults_valid_min_per_region"), field="adults_valid_min_per_region")
    employer_min = _positive_int(thresholds.get("employers_total_valid_min"), field="employers_total_valid_min")
    employer_region_min = _positive_int(thresholds.get("employers_valid_min_per_region"), field="employers_valid_min_per_region")
    channel_types_min = _positive_int(thresholds.get("independent_recruitment_channels_min_per_region"), field="independent_recruitment_channels_min_per_region")
    channel_share_max = _ratio(thresholds.get("single_channel_share_max"), field="single_channel_share_max")

    form_counts = manifest.get("form_counts")
    form_region_counts = manifest.get("form_region_counts")
    region_channel_ids = manifest.get("region_channel_ids")
    if not isinstance(form_counts, dict) or not isinstance(form_region_counts, dict) or not isinstance(region_channel_ids, dict):
        raise PrimaryEvidenceReadinessError("manifest lacks method-coverage aggregates")
    if form_counts.get(ADULT_FORM, 0) < adult_min:
        raise PrimaryEvidenceReadinessError("adult total is below the frozen operational adequacy threshold")
    if form_counts.get(EMPLOYER_FORM, 0) < employer_min:
        raise PrimaryEvidenceReadinessError("employer total is below the frozen operational adequacy threshold")
    if manifest.get("record_count") != sum(int(form_counts.get(form, 0)) for form in (ADULT_FORM, EMPLOYER_FORM)):
        raise PrimaryEvidenceReadinessError("record_count does not reconcile with form_counts")

    for region in TARGET_REGIONS:
        if (form_region_counts.get(ADULT_FORM) or {}).get(region, 0) < adult_region_min:
            raise PrimaryEvidenceReadinessError(f"adult coverage below threshold in {region}")
        if (form_region_counts.get(EMPLOYER_FORM) or {}).get(region, 0) < employer_region_min:
            raise PrimaryEvidenceReadinessError(f"employer coverage below threshold in {region}")
        used_ids = region_channel_ids.get(region)
        if not isinstance(used_ids, list) or not used_ids:
            raise PrimaryEvidenceReadinessError(f"no recruitment-channel provenance for {region}")
        if len(used_ids) != len(set(used_ids)):
            raise PrimaryEvidenceReadinessError(f"duplicate recruitment-channel provenance for {region}")
        channel_types: set[str] = set()
        for channel_id in used_ids:
            try:
                channel_id = validate_recruitment_channel_id(channel_id)
            except ChannelProvenanceError as exc:
                raise PrimaryEvidenceReadinessError(str(exc)) from exc
            entry = register_by_id.get(channel_id)
            if entry is None:
                raise PrimaryEvidenceReadinessError(f"used channel {channel_id} is absent from frozen channel register")
            if region not in entry["region_scope"]:
                raise PrimaryEvidenceReadinessError(f"used channel {channel_id} is not authorised for {region}")
            channel_types.add(entry["channel_type"])
        if len(channel_types) < channel_types_min:
            raise PrimaryEvidenceReadinessError(
                f"{region} has {len(channel_types)} independent channel type(s), below frozen minimum {channel_types_min}"
            )

    form_region_channel_ids = manifest.get("form_region_channel_ids")
    _validate_form_region_channel_provenance(
        form_region_channel_ids,
        form_region_counts=form_region_counts,
        region_channel_ids=region_channel_ids,
        register_by_id=register_by_id,
    )

    manifest_channels = manifest.get("channel_counts")
    if not isinstance(manifest_channels, dict) or set(manifest_channels) - set(register_by_id):
        raise PrimaryEvidenceReadinessError("manifest contains channel ids absent from the frozen channel register")

    exceeded_scopes = _validate_channel_concentration_aggregates(
        manifest,
        form_region_counts=form_region_counts,
        region_channel_ids=region_channel_ids,
        form_region_channel_ids=form_region_channel_ids,
        channel_share_max=channel_share_max,
    )
    sensitivity_used = False
    if exceeded_scopes:
        _validate_sensitivity_artifact(
            dominant_channel_sensitivity,
            required_scopes=exceeded_scopes,
        )
        sensitivity_used = True

    return {
        "schema_version": "eucons.ai4work_primary_evidence_readiness.v0.3",
        "research_id": RESEARCH_ID,
        "stage": "PRE_SYNTHESIS_METHOD_COVERAGE",
        "evidence_class": "CONTROL_ARTIFACT_NOT_EVIDENCE",
        "source_evidence_class": PROD_EVIDENCE_CLASS,
        "ready_for_primary_synthesis": True,
        "representativeness_claim_allowed": False,
        "weighting_allowed": False,
        "thresholds_are_method_rules_not_evidence": True,
        "all_three_regions_meet_frozen_population_minima": True,
        "independent_channel_types_per_region_validated": True,
        "channel_register_sha256_validated": True,
        "invitation_catalog_binding_shape_validated": True,
        "form_audience_channel_scope_validated": True,
        "channel_concentration_scopes_validated": True,
        "dominant_channel_sensitivity_used": sensitivity_used,
        "dominant_channel_sensitivity_scopes": sorted(exceeded_scopes),
        "scope_boundary": "PASS authorises only entry into needs synthesis/adversarial QA for this real non-probability PROD batch. It does not establish population prevalence, causality, representativeness or any need conclusion.",
    }
