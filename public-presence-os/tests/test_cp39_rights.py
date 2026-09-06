from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

from public_presence_os.radar import RadarKind, RadarObservation, RadarSourceClass, materialize_signal
from public_presence_os.research import EvidenceAuthority, EvidenceKind, ResearchEvidence, build_research_packet
from public_presence_os.scoring import score_research_packet
from public_presence_os.master_draft import build_master_draft_brief
from public_presence_os.native_adapt import build_native_adaptation_bundle
from public_presence_os.rights import *

ROOT = Path(__file__).resolve().parents[1]
OBSERVED = "2026-09-06T06:00:00Z"
CAPTURED = "2026-09-06T06:05:00Z"
ACQUIRED = "2026-09-06T06:10:00Z"
INTENDED = "2026-09-06T07:00:00Z"


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def make_bundle():
    url = "https://authority.example/news/39"
    signal = materialize_signal(RadarObservation(
        external_ref="story-39",
        source_url=url,
        source_class=RadarSourceClass.PRIMARY_PUBLIC,
        kind=RadarKind.ANNOUNCEMENT,
        observed_at_utc=OBSERVED,
        title="Local public update",
        excerpt="Exact primary-source context.",
        topic="local",
        locality="Valcea",
    ))
    packet = build_research_packet(signal, [ResearchEvidence(
        evidence_id="ev39",
        source_url=url,
        authority=EvidenceAuthority.PRIMARY_SOURCE,
        kind=EvidenceKind.DETAIL_PAGE,
        captured_at_utc=CAPTURED,
        content_sha256=h("research evidence"),
    )])
    brief = build_master_draft_brief(packet, score_research_packet(packet))
    bundle = build_native_adaptation_bundle(brief)
    assert bundle.rights_input_ready is True
    return bundle


def make_original(
    *,
    route=AcquisitionRoute.OWNED_CAPTURE,
    media_class=MediaClass.CONTEXTUAL_PHOTO,
    clearance=SubjectClearance.NOT_APPLICABLE,
):
    source = "local://photo/original-39" if route == AcquisitionRoute.OWNED_CAPTURE else "https://images.example/original-39.jpg"
    return materialize_image_original(ImageOriginalSpec(
        original_sha256=h("image bytes"),
        mime_type="image/jpeg",
        byte_size=4096,
        media_class=media_class,
        creator_name="Rights test creator",
        creator_identity_status="VERIFIED",
        acquisition_route=route,
        acquisition_source_url=source,
        acquired_at_utc=ACQUIRED,
        discovery_source_url="https://discovery.example/item/39",
        subject_clearance_status=clearance,
        metadata_sha256=h("metadata"),
    ))


def make_evidence(eid="rights-ev-39", payload="license snapshot"):
    return materialize_rights_evidence(RightsEvidenceSpec(
        evidence_id=eid,
        evidence_kind="RIGHTS_PROOF_SNAPSHOT",
        snapshot_sha256=h(payload),
        snapshot_size=1024,
        canonical_uri=f"local://rights/{eid}",
        acquired_at_utc=ACQUIRED,
        note="Exact snapshot evidence",
    ))


def owned_record(original, evidence, *, revision=1, supersedes="", platforms=ACTIVE_NATIVE_PLATFORMS):
    return materialize_rights_record(original, RightsRecordSpec(
        revision=revision,
        rights_status=RightsStatus.OWNED,
        basis_type=RightsBasis.OWNERSHIP,
        rights_holder="Owner",
        permitted_platforms=tuple(platforms),
        permitted_purposes=("SOCIAL_EDITORIAL",),
        territory="WORLDWIDE",
        commercial_use_allowed=True,
        modification_policy=ModificationPolicy.ALLOWED,
        attribution_required=False,
        attribution_text="",
        valid_from_utc=ACQUIRED,
        supersedes_rights_record_id=supersedes,
    ), evidence)


def licensed_record(original, evidence, *, platforms=ACTIVE_NATIVE_PLATFORMS, modification=ModificationPolicy.ALLOWED, share_alike=False):
    return materialize_rights_record(original, RightsRecordSpec(
        revision=1,
        rights_status=RightsStatus.LICENSED,
        basis_type=RightsBasis.LICENSE_GRANT,
        rights_holder="Photographer",
        license_name="Example Commercial License",
        license_version="1.0",
        license_url="https://license.example/terms/1",
        permitted_platforms=tuple(platforms),
        permitted_purposes=("SOCIAL_EDITORIAL",),
        territory="WORLDWIDE",
        commercial_use_allowed=True,
        modification_policy=modification,
        attribution_required=True,
        attribution_text="Photo: Rights test creator",
        share_alike_required=share_alike,
        required_output_license="CC-BY-SA-4.0" if share_alike else "",
        valid_from_utc=ACQUIRED,
    ), evidence)


def requests(record_id, *, output_license="", modifications=True, commercial=True, intended=INTENDED):
    return tuple(UsageRequest(
        platform=platform,
        purpose="SOCIAL_EDITORIAL",
        intended_at_utc=intended,
        rights_record_id=record_id,
        modifications_required=modifications,
        commercial_context=commercial,
        territory="RO",
        output_license=output_license,
    ) for platform in ACTIVE_NATIVE_PLATFORMS)


def package(original, evidence, records, usage):
    return build_rights_bound_visual_input(make_bundle(), original, evidence, records, usage)


def test_owned_exact_asset_is_rights_bound_for_all_active_lanes():
    original = make_original()
    evidence = (make_evidence(),)
    record = owned_record(original, evidence)
    result = package(original, evidence, (record,), requests(record.rights_record_id))
    assert result.visual_input_ready is True
    assert result.package_status == RightsPackageStatus.READY_REQUIRED_VISUAL_LANES.value
    assert tuple(d.platform for d in result.lane_decisions) == ACTIVE_NATIVE_PLATFORMS
    assert all(d.status == RightsDecisionStatus.ELIGIBLE_RENDER_QA.value for d in result.lane_decisions)


def test_exact_original_identity_and_provenance_are_deterministic():
    a = make_original()
    b = make_original()
    assert a == b
    assert a.original_sha256 == h("image bytes")
    assert a.original_id == b.original_id
    assert a.provenance_hash == b.provenance_hash


def test_uncleared_discovery_route_cannot_be_used_as_acquisition_route():
    spec = ImageOriginalSpec(
        original_sha256=h("x"), mime_type="image/jpeg", byte_size=1,
        media_class=MediaClass.CONTEXTUAL_PHOTO, creator_name="Creator", creator_identity_status="VERIFIED",
        acquisition_route="SEARCH_ENGINE_DOWNLOAD", acquisition_source_url="https://search.example/x",
        acquired_at_utc=ACQUIRED,
    )
    with pytest.raises(ValueError, match="uncleared discovery route"):
        materialize_image_original(spec)


def test_external_direct_acquisition_requires_https():
    spec = ImageOriginalSpec(
        original_sha256=h("x"), mime_type="image/jpeg", byte_size=1,
        media_class=MediaClass.CONTEXTUAL_PHOTO, creator_name="Creator", creator_identity_status="VERIFIED",
        acquisition_route=AcquisitionRoute.LICENSED_DIRECT_DOWNLOAD, acquisition_source_url="local://bad/x",
        acquired_at_utc=ACQUIRED,
    )
    with pytest.raises(ValueError):
        materialize_image_original(spec)


def test_url_alone_is_not_rights_evidence():
    with pytest.raises(ValueError):
        materialize_rights_evidence(RightsEvidenceSpec(
            evidence_id="ev", evidence_kind="URL_ONLY", snapshot_sha256="", snapshot_size=0,
            canonical_uri="https://license.example/page", acquired_at_utc=ACQUIRED,
        ))


def test_evidence_set_is_deterministic_and_exact():
    a = make_evidence("a", "a")
    b = make_evidence("b", "b")
    assert evidence_set_hash((a, b)) == evidence_set_hash((b, a))
    assert evidence_set_hash((a, a, b)) == evidence_set_hash((a, b))


def test_conflicting_evidence_id_is_rejected():
    a = make_evidence("same", "a")
    b = make_evidence("same", "b")
    with pytest.raises(ValueError):
        evidence_set_hash((a, b))


def test_licensed_asset_requires_explicit_license_identity_and_scope():
    original = make_original(route=AcquisitionRoute.LICENSED_DIRECT_DOWNLOAD)
    evidence = (make_evidence(),)
    bad = RightsRecordSpec(
        revision=1, rights_status=RightsStatus.LICENSED, basis_type=RightsBasis.LICENSE_GRANT,
        rights_holder="Photographer", permitted_platforms=ACTIVE_NATIVE_PLATFORMS,
        permitted_purposes=("SOCIAL_EDITORIAL",), territory="WORLDWIDE", commercial_use_allowed=None,
        modification_policy=ModificationPolicy.UNKNOWN, attribution_required=False, attribution_text="",
        valid_from_utc=ACQUIRED,
    )
    with pytest.raises(ValueError):
        materialize_rights_record(original, bad, evidence)


def test_licensed_asset_with_explicit_grant_is_eligible():
    original = make_original(route=AcquisitionRoute.LICENSED_DIRECT_DOWNLOAD)
    evidence = (make_evidence(),)
    record = licensed_record(original, evidence)
    result = package(original, evidence, (record,), requests(record.rights_record_id))
    assert result.visual_input_ready is True
    assert all(d.eligible_render_qa for d in result.lane_decisions)


def test_public_domain_requires_pd_or_cc0_basis():
    original = make_original(route=AcquisitionRoute.PUBLIC_DOMAIN_DIRECT_DOWNLOAD)
    evidence = (make_evidence(),)
    bad = RightsRecordSpec(
        revision=1, rights_status=RightsStatus.PUBLIC_DOMAIN, basis_type=RightsBasis.UNKNOWN,
        rights_holder="Public domain determination", permitted_platforms=ACTIVE_NATIVE_PLATFORMS,
        permitted_purposes=("SOCIAL_EDITORIAL",), territory="WORLDWIDE", commercial_use_allowed=True,
        modification_policy=ModificationPolicy.ALLOWED, attribution_required=False, attribution_text="",
        valid_from_utc=ACQUIRED,
    )
    with pytest.raises(ValueError):
        materialize_rights_record(original, bad, evidence)


def test_cc0_public_domain_with_snapshot_evidence_is_eligible():
    original = make_original(route=AcquisitionRoute.PUBLIC_DOMAIN_DIRECT_DOWNLOAD)
    evidence = (make_evidence(),)
    record = materialize_rights_record(original, RightsRecordSpec(
        revision=1, rights_status=RightsStatus.PUBLIC_DOMAIN, basis_type=RightsBasis.CC0_DEDICATION,
        rights_holder="Creator", permitted_platforms=ACTIVE_NATIVE_PLATFORMS,
        permitted_purposes=("SOCIAL_EDITORIAL",), territory="WORLDWIDE", commercial_use_allowed=True,
        modification_policy=ModificationPolicy.ALLOWED, attribution_required=False, attribution_text="",
        valid_from_utc=ACQUIRED,
    ), evidence)
    assert package(original, evidence, (record,), requests(record.rights_record_id)).visual_input_ready is True


def test_fair_use_never_auto_passes():
    original = make_original()
    evidence = (make_evidence(),)
    record = materialize_rights_record(original, RightsRecordSpec(
        revision=1, rights_status=RightsStatus.FAIR_USE_REVIEW, basis_type=RightsBasis.FAIR_USE_REVIEW,
        rights_holder="Unknown", permitted_platforms=ACTIVE_NATIVE_PLATFORMS,
        permitted_purposes=("SOCIAL_EDITORIAL",), territory="RO", commercial_use_allowed=None,
        modification_policy=ModificationPolicy.UNKNOWN, attribution_required=False, attribution_text="",
        valid_from_utc=ACQUIRED,
    ), evidence)
    result = package(original, evidence, (record,), requests(record.rights_record_id))
    assert result.visual_input_ready is False
    assert all(d.status == RightsDecisionStatus.HOLD_HUMAN_REVIEW.value for d in result.lane_decisions)


def test_unknown_rights_hold():
    original = make_original()
    evidence = (make_evidence(),)
    record = materialize_rights_record(original, RightsRecordSpec(
        revision=1, rights_status=RightsStatus.UNKNOWN, basis_type=RightsBasis.UNKNOWN,
        rights_holder="Unknown", permitted_platforms=(), permitted_purposes=(), territory="",
        commercial_use_allowed=None, modification_policy=ModificationPolicy.UNKNOWN,
        attribution_required=False, attribution_text="", valid_from_utc=ACQUIRED,
    ), evidence)
    result = package(original, evidence, (record,), requests(record.rights_record_id))
    assert result.visual_input_ready is False
    assert all(d.status == RightsDecisionStatus.HOLD_RIGHTS.value for d in result.lane_decisions)


def test_subject_clearance_pending_holds_for_human_review():
    original = make_original(clearance=SubjectClearance.PENDING)
    evidence = (make_evidence(),)
    record = owned_record(original, evidence)
    result = package(original, evidence, (record,), requests(record.rights_record_id))
    assert all(d.status == RightsDecisionStatus.HOLD_HUMAN_REVIEW.value for d in result.lane_decisions)


def test_subject_clearance_blocked_is_hard_stop():
    original = make_original(clearance=SubjectClearance.BLOCKED)
    evidence = (make_evidence(),)
    record = owned_record(original, evidence)
    result = package(original, evidence, (record,), requests(record.rights_record_id))
    assert result.package_status == RightsPackageStatus.BLOCKED_REQUIRED_VISUAL_LANES.value
    assert all(d.status == RightsDecisionStatus.BLOCKED.value for d in result.lane_decisions)


def test_profile_photo_cannot_be_social_editorial_media():
    original = make_original(media_class=MediaClass.PROFILE_PHOTO)
    evidence = (make_evidence(),)
    record = owned_record(original, evidence)
    result = package(original, evidence, (record,), requests(record.rights_record_id))
    assert all(d.status == RightsDecisionStatus.BLOCKED.value for d in result.lane_decisions)


def test_expired_rights_hold():
    original = make_original()
    evidence = (make_evidence(),)
    record = materialize_rights_record(original, RightsRecordSpec(
        revision=1, rights_status=RightsStatus.OWNED, basis_type=RightsBasis.OWNERSHIP,
        rights_holder="Owner", permitted_platforms=ACTIVE_NATIVE_PLATFORMS,
        permitted_purposes=("SOCIAL_EDITORIAL",), territory="WORLDWIDE", commercial_use_allowed=True,
        modification_policy=ModificationPolicy.ALLOWED, attribution_required=False, attribution_text="",
        valid_from_utc=ACQUIRED, expires_at_utc="2026-09-06T06:30:00Z",
    ), evidence)
    result = package(original, evidence, (record,), requests(record.rights_record_id))
    assert all("RIGHTS_EXPIRED" in d.reasons for d in result.lane_decisions)


def test_overdue_review_holds():
    original = make_original()
    evidence = (make_evidence(),)
    record = materialize_rights_record(original, RightsRecordSpec(
        revision=1, rights_status=RightsStatus.OWNED, basis_type=RightsBasis.OWNERSHIP,
        rights_holder="Owner", permitted_platforms=ACTIVE_NATIVE_PLATFORMS,
        permitted_purposes=("SOCIAL_EDITORIAL",), territory="WORLDWIDE", commercial_use_allowed=True,
        modification_policy=ModificationPolicy.ALLOWED, attribution_required=False, attribution_text="",
        valid_from_utc=ACQUIRED, review_at_utc="2026-09-06T06:30:00Z",
    ), evidence)
    result = package(original, evidence, (record,), requests(record.rights_record_id))
    assert all("RIGHTS_REVIEW_OVERDUE" in d.reasons for d in result.lane_decisions)


def test_modification_not_granted_holds():
    original = make_original(route=AcquisitionRoute.LICENSED_DIRECT_DOWNLOAD)
    evidence = (make_evidence(),)
    record = licensed_record(original, evidence, modification=ModificationPolicy.NOT_ALLOWED)
    result = package(original, evidence, (record,), requests(record.rights_record_id, modifications=True))
    assert all("MODIFICATIONS_NOT_GRANTED" in d.reasons for d in result.lane_decisions)


def test_share_alike_requires_compatible_output_license():
    original = make_original(route=AcquisitionRoute.LICENSED_DIRECT_DOWNLOAD)
    evidence = (make_evidence(),)
    record = licensed_record(original, evidence, share_alike=True)
    hold = package(original, evidence, (record,), requests(record.rights_record_id))
    assert all("SHARE_ALIKE_OUTPUT_LICENSE_MISMATCH" in d.reasons for d in hold.lane_decisions)
    passed = package(original, evidence, (record,), requests(record.rights_record_id, output_license="CC-BY-SA-4.0"))
    assert passed.visual_input_ready is True


def test_superseded_record_is_stale_for_new_usage():
    original = make_original()
    evidence = (make_evidence(),)
    first = owned_record(original, evidence)
    second = owned_record(original, evidence, revision=2, supersedes=first.rights_record_id)
    result = package(original, evidence, (first, second), requests(first.rights_record_id))
    assert result.visual_input_ready is False
    assert all(d.status == RightsDecisionStatus.HOLD_STALE_RIGHTS.value for d in result.lane_decisions)


def test_revocation_blocks_usage_bound_to_prior_rights():
    original = make_original()
    evidence = (make_evidence(),)
    first = owned_record(original, evidence)
    revoked = materialize_rights_record(original, RightsRecordSpec(
        revision=2, rights_status=RightsStatus.BLOCKED, basis_type=RightsBasis.REVOCATION,
        rights_holder="Owner", permitted_platforms=(), permitted_purposes=(), territory="",
        commercial_use_allowed=False, modification_policy=ModificationPolicy.NOT_ALLOWED,
        attribution_required=False, attribution_text="", valid_from_utc=ACQUIRED,
        supersedes_rights_record_id=first.rights_record_id,
    ), evidence)
    result = package(original, evidence, (first, revoked), requests(first.rights_record_id))
    assert result.package_status == RightsPackageStatus.BLOCKED_REQUIRED_VISUAL_LANES.value
    assert all(d.status == RightsDecisionStatus.BLOCKED.value for d in result.lane_decisions)


def test_optional_lane_rights_failure_does_not_grant_it_or_block_required_instagram():
    original = make_original()
    evidence = (make_evidence(),)
    record = owned_record(original, evidence, platforms=("INSTAGRAM_PROFESSIONAL",))
    result = package(original, evidence, (record,), requests(record.rights_record_id))
    lanes = {d.platform: d for d in result.lane_decisions}
    assert result.visual_input_ready is True
    assert lanes["INSTAGRAM_PROFESSIONAL"].eligible_render_qa is True
    assert lanes["FACEBOOK_PAGE"].eligible_render_qa is False
    assert lanes["THREADS"].eligible_render_qa is False


def test_usage_requests_must_cover_active_platforms_exactly_once():
    original = make_original()
    evidence = (make_evidence(),)
    record = owned_record(original, evidence)
    with pytest.raises(ValueError):
        package(original, evidence, (record,), requests(record.rights_record_id)[:-1])


def test_m05_bundle_tampering_is_rejected():
    bundle = replace(make_bundle(), topic="forged")
    original = make_original()
    evidence = (make_evidence(),)
    record = owned_record(original, evidence)
    with pytest.raises(ValueError):
        build_rights_bound_visual_input(bundle, original, evidence, (record,), requests(record.rights_record_id))


def test_deterministic_replay_and_no_downstream_authority():
    original = make_original()
    evidence = (make_evidence(),)
    record = owned_record(original, evidence)
    a = package(original, evidence, (record,), requests(record.rights_record_id))
    b = package(original, evidence, (record,), requests(record.rights_record_id))
    assert a == b
    assert a.rights_input_hash == b.rights_input_hash
    assert a.state == "RIGHTS_BOUND_VISUAL_INPUT_ONLY"
    assert a.rights_authority is True
    assert not any((a.fact_authority, a.visual_authority, a.approval_authority, a.queue_authority, a.publish_authority, a.api_write_allowed, a.network_fetch_performed, a.real_account_connection_performed))
    assert all(d.publish_eligible is False for d in a.lane_decisions)


def test_json_deduplicates_and_prioritizes_ready_inputs():
    original = make_original()
    evidence = (make_evidence(),)
    record = owned_record(original, evidence)
    ready = package(original, evidence, (record,), requests(record.rights_record_id))
    held_record = owned_record(original, evidence, platforms=("FACEBOOK_PAGE",))
    held = package(original, evidence, (held_record,), requests(held_record.rights_record_id))
    payload = json.loads(rights_bound_visual_inputs_json((held, ready, ready)))
    assert len(payload) == 2
    assert payload[0]["visual_input_ready"] is True
    assert payload[1]["visual_input_ready"] is False


def test_policy_preserves_platform_and_fail_closed_canon():
    policy = json.loads((ROOT / "config" / "image_rights_policy.json").read_text())
    assert policy["checkpoint"] == "CP39"
    assert policy["model_version"] == RIGHTS_MODEL_VERSION
    assert policy["active_platforms"] == list(ACTIVE_NATIVE_PLATFORMS)
    assert policy["deferred_platforms"]["LINKEDIN"] == "PRODUCTION_API_ACCESS_REQUIRED"
    assert policy["deferred_platforms"]["X"] == "EXCLUDED_WHILE_API_PAID"
    assert policy["deferred_platforms"]["BLUESKY"] == "HOLD_ROI"
    assert policy["input_contract"]["url_alone_is_evidence"] is False
    assert set(policy["rights"]["auto_eligible_statuses"]) == AUTO_ELIGIBLE
    assert policy["visual_handoff"]["required_visual_platforms"] == list(REQUIRED_VISUAL_PLATFORMS)
    assert policy["visual_handoff"]["publish_eligible"] is False


def test_cp39_does_not_claim_missing_historical_db_source_or_persistence():
    policy = json.loads((ROOT / "config" / "image_rights_policy.json").read_text())
    persistence = policy["persistence"]
    assert persistence["historical_cp13_sqlite_source_bytes_available"] is False
    assert persistence["persistent_append_only_db_store_claimed_by_cp39"] is False
    assert persistence["db_and_event_log"] == "DEFERRED_TO_SEPARATE_EXECUTABLE_UNIT"
    authority = policy["authority"]
    assert authority["rights_authority"] is True
    assert not any((authority["fact_authority"], authority["visual_authority"], authority["approval_authority"], authority["queue_authority"], authority["publish_authority"], authority["api_write_allowed"], authority["network_fetch_allowed"], authority["real_account_connection_allowed"]))
