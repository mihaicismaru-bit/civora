from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

import pytest

from public_presence_os.radar import RadarKind, RadarObservation, RadarSourceClass, materialize_signal
from public_presence_os.research import EvidenceAuthority, EvidenceKind, ResearchEvidence, build_research_packet
from public_presence_os.scoring import score_research_packet
from public_presence_os.master_draft import build_master_draft_brief
from public_presence_os.native_adapt import build_native_adaptation_bundle
from public_presence_os.image_rights import *

ROOT = Path(__file__).resolve().parents[1]
OBSERVED = "2026-09-06T05:30:00Z"
CAPTURED = "2026-09-06T05:40:00Z"
INTENDED = "2026-09-06T06:00:00Z"


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def make_bundle(*, exact_primary=True):
    source_url = "https://example.gov.ro/news/39"
    signal = materialize_signal(RadarObservation(
        external_ref="story-39",
        source_url=source_url,
        source_class=RadarSourceClass.PRIMARY_PUBLIC,
        kind=RadarKind.ANNOUNCEMENT,
        observed_at_utc=OBSERVED,
        title="Local announcement",
        excerpt="Specific public detail.",
        topic="transport",
        locality="Valcea",
        synthetic=False,
    ))
    evidence_url = source_url if exact_primary else "https://example.gov.ro/detail/39"
    packet = build_research_packet(signal, [ResearchEvidence(
        evidence_id="ev39",
        source_url=evidence_url,
        authority=EvidenceAuthority.PRIMARY_SOURCE,
        kind=EvidenceKind.DETAIL_PAGE,
        captured_at_utc=CAPTURED,
        content_sha256=h("evidence-39"),
    )])
    return build_native_adaptation_bundle(
        build_master_draft_brief(packet, score_research_packet(packet))
    )


def make_source(registry: RightsRegistry, *, reuse="OWNED", source_id="local39"):
    return registry.register_source_revision(
        source_id=source_id,
        revision=1,
        source_class="LOCAL_LIBRARY",
        display_name="Local cleared library",
        source_url="https://local.invalid/assets/39",
        discovery_role="ACQUISITION",
        reuse_default=reuse,
        license_or_basis="OWNER_RECORD",
        status="ACTIVE",
        verified_at_utc=CAPTURED,
    )


def make_asset(
    registry: RightsRegistry,
    *,
    media_class=MediaClass.CONTEXTUAL_PHOTO.value,
    subject=SubjectClearanceStatus.CLEAR.value,
    source_reuse="OWNED",
    asset_bytes=b"image-39-original",
):
    source_id = make_source(registry, reuse=source_reuse)
    original_id = registry.register_original(
        asset_bytes,
        mime_type="image/jpeg",
        media_class=media_class,
        creator_name="Owner",
        acquisition_route="LOCAL_OWNED",
        acquisition_source_revision_id=source_id,
        source_url="https://local.invalid/assets/39.jpg",
        subject_clearance_status=subject,
        metadata={"fixture": True},
    )
    return original_id, registry.asset_sha256_for_original(original_id)


def add_rights(
    registry: RightsRegistry,
    original_id: str,
    *,
    status=RightsStatus.OWNED.value,
    platforms=ACTIVE_NATIVE_PLATFORMS,
    purposes=(SOCIAL_EDITORIAL_PURPOSE,),
    territory="RO",
    commercial=True,
    modification=ModificationPolicy.CROP_RESIZE_ONLY.value,
    attribution=False,
    attribution_text="",
    share_alike=False,
    output_license=None,
    expires=None,
    review=None,
    supersedes=None,
):
    return registry.register_rights_revision(
        original_id,
        rights_status=status,
        basis_type="OWNERSHIP" if status == RightsStatus.OWNED.value else "LICENSE_OR_REVIEW",
        rights_holder="Owner",
        permitted_platforms=platforms,
        permitted_purposes=purposes,
        territory=territory,
        commercial_use_allowed=commercial,
        modification_policy=modification,
        attribution_required=attribution,
        attribution_text=attribution_text,
        evidence=(EvidenceSnapshot(
            evidence_kind="OWNER_OR_LICENSE_RECORD",
            snapshot_bytes=b"rights-proof-39",
            canonical_uri="local://rights/39",
            acquired_at_utc=CAPTURED,
        ),) if status in AUTO_ELIGIBLE_RIGHTS else (),
        terms_hash=h("terms-39"),
        share_alike_required=share_alike,
        required_output_license=output_license,
        expires_at_utc=expires,
        review_at_utc=review,
        supersedes_rights_record_id=supersedes,
    )


def usage(platform="FACEBOOK_PAGE", **kwargs):
    return UsageRequest(
        platform=platform,
        purpose=SOCIAL_EDITORIAL_PURPOSE,
        intended_at_utc=kwargs.get("intended", INTENDED),
        modifications_required=kwargs.get("mods", ("CROP", "RESIZE")),
        commercial_context=kwargs.get("commercial", True),
        territory=kwargs.get("territory", "RO"),
        output_license=kwargs.get("output_license"),
    )


def test_owned_asset_binds_all_active_lanes_for_m06_input():
    registry = RightsRegistry()
    original_id, asset_sha = make_asset(registry)
    rights_id = add_rights(registry, original_id)
    bound = bind_rights_bound_visual_input(
        make_bundle(), registry,
        asset_sha256=asset_sha,
        rights_record_id=rights_id,
        intended_at_utc=INTENDED,
        territory="RO",
    )
    assert bound.status == VisualBindingStatus.READY_RIGHTS_BOUND_VISUAL_INPUT.value
    assert bound.visual_input_ready is True
    assert bound.eligible_platforms == ACTIVE_NATIVE_PLATFORMS
    assert bound.blocked_platforms == ()
    assert all(item.status == EligibilityStatus.ELIGIBLE_RENDER_QA.value for item in bound.eligibility)
    assert all(item.publish_eligible is False for item in bound.eligibility)


def test_platform_scope_missing_threads_fails_closed_for_common_visual_binding():
    registry = RightsRegistry()
    original_id, asset_sha = make_asset(registry)
    rights_id = add_rights(registry, original_id, platforms=("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL"))
    bound = bind_rights_bound_visual_input(
        make_bundle(), registry, asset_sha256=asset_sha, rights_record_id=rights_id,
        intended_at_utc=INTENDED, territory="RO",
    )
    assert bound.status == VisualBindingStatus.HOLD_RIGHTS.value
    assert bound.visual_input_ready is False
    assert bound.eligible_platforms == ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL")
    assert bound.blocked_platforms == ("THREADS",)
    threads = [x for x in bound.eligibility if x.platform == "THREADS"][0]
    assert "PLATFORM_NOT_GRANTED" in threads.reason_codes


def test_public_or_discovery_only_source_is_not_reuse_permission():
    registry = RightsRegistry()
    source = make_source(registry, reuse="PROHIBITED")
    with pytest.raises(ValueError, match="discovery-only|reuse-prohibited"):
        registry.register_original(
            b"public-visible-bytes",
            mime_type="image/jpeg",
            media_class=MediaClass.CONTEXTUAL_PHOTO.value,
            creator_name="Unknown",
            acquisition_route="LOCAL_OWNED",
            acquisition_source_revision_id=source,
            source_url="https://public.example/photo.jpg",
            subject_clearance_status=SubjectClearanceStatus.NOT_APPLICABLE.value,
        )


def test_uncleared_social_search_press_and_map_routes_are_rejected():
    for route in sorted(FORBIDDEN_ACQUISITION_ROUTES):
        registry = RightsRegistry()
        source = make_source(registry)
        with pytest.raises(ValueError, match="not authorized"):
            registry.register_original(
                b"bytes-" + route.encode(),
                mime_type="image/jpeg",
                media_class=MediaClass.CONTEXTUAL_PHOTO.value,
                creator_name="Unknown",
                acquisition_route=route,
                acquisition_source_revision_id=source,
                source_url="https://example.invalid/photo",
                subject_clearance_status=SubjectClearanceStatus.NOT_APPLICABLE.value,
            )


def test_unknown_fair_use_and_blocked_rights_do_not_auto_pass():
    expected = {
        RightsStatus.UNKNOWN.value: EligibilityStatus.HOLD_RIGHTS.value,
        RightsStatus.FAIR_USE_REVIEW.value: EligibilityStatus.HOLD_HUMAN_REVIEW.value,
        RightsStatus.BLOCKED.value: EligibilityStatus.BLOCKED.value,
    }
    for status, expected_status in expected.items():
        registry = RightsRegistry()
        original_id, asset_sha = make_asset(registry)
        rights_id = add_rights(registry, original_id, status=status, platforms=(), purposes=())
        result = registry.evaluate(asset_sha, rights_id, usage())
        assert result.status == expected_status
        assert result.eligible is False


def test_subject_clearance_pending_holds_and_blocked_stops():
    for subject, expected in (
        (SubjectClearanceStatus.PENDING.value, EligibilityStatus.HOLD_RIGHTS.value),
        (SubjectClearanceStatus.BLOCKED.value, EligibilityStatus.BLOCKED.value),
    ):
        registry = RightsRegistry()
        original_id, asset_sha = make_asset(registry, subject=subject)
        rights_id = add_rights(registry, original_id)
        assert registry.evaluate(asset_sha, rights_id, usage()).status == expected


def test_profile_photo_cannot_be_social_editorial_post_media():
    registry = RightsRegistry()
    original_id, asset_sha = make_asset(registry, media_class=MediaClass.PROFILE_PHOTO.value)
    rights_id = add_rights(registry, original_id)
    result = registry.evaluate(asset_sha, rights_id, usage())
    assert result.status == EligibilityStatus.BLOCKED.value
    assert "PROFILE_PHOTO_NOT_SOCIAL_EDITORIAL_MEDIA" in result.reason_codes


def test_attribution_and_sharealike_are_explicit_scope_gates():
    registry = RightsRegistry()
    original_id, asset_sha = make_asset(registry)
    rights_id = add_rights(
        registry, original_id,
        status=RightsStatus.LICENSED.value,
        attribution=True,
        attribution_text="Photo: Example Creator / CC BY-SA 4.0",
        share_alike=True,
        output_license="CC-BY-SA-4.0",
    )
    hold = registry.evaluate(asset_sha, rights_id, usage(output_license=None))
    assert hold.status == EligibilityStatus.HOLD_RIGHTS.value
    assert "SHAREALIKE_OUTPUT_LICENSE_MISMATCH" in hold.reason_codes
    passed = registry.evaluate(asset_sha, rights_id, usage(output_license="CC-BY-SA-4.0"))
    assert passed.eligible is True
    assert passed.attribution_text.startswith("Photo:")


def test_expired_and_overdue_review_rights_hold():
    for kwargs, reason in (
        ({"expires": "2026-09-05T00:00:00Z"}, "RIGHTS_EXPIRED"),
        ({"review": "2026-09-05T00:00:00Z"}, "RIGHTS_REVIEW_OVERDUE"),
    ):
        registry = RightsRegistry()
        original_id, asset_sha = make_asset(registry)
        rights_id = add_rights(registry, original_id, **kwargs)
        result = registry.evaluate(asset_sha, rights_id, usage())
        assert result.status == EligibilityStatus.HOLD_RIGHTS.value
        assert reason in result.reason_codes


def test_rights_revision_supersession_makes_old_record_stale_and_propagates_to_derivative():
    registry = RightsRegistry()
    original_id, asset_sha = make_asset(registry)
    rights_id = add_rights(registry, original_id)
    derivative_bytes = b"derived-image-39"
    registry.register_derivative(
        derivative_bytes,
        parent_sha256=asset_sha,
        rights_record_id_at_creation=rights_id,
        derivative_kind="CROP",
        transform={"crop": [0, 0, 100, 100]},
    )
    derivative_sha = sha256(derivative_bytes).hexdigest()
    revoke_id = registry.register_rights_revision(
        original_id,
        rights_status=RightsStatus.BLOCKED.value,
        basis_type="REVOCATION",
        rights_holder="Owner",
        permitted_platforms=(),
        permitted_purposes=(),
        territory="RO",
        commercial_use_allowed=False,
        modification_policy=ModificationPolicy.NO_MODIFICATIONS.value,
        attribution_required=False,
        attribution_text="",
        evidence=(),
        terms_hash=h("revocation-39"),
        supersedes_rights_record_id=rights_id,
    )
    stale = registry.evaluate(derivative_sha, rights_id, usage())
    blocked = registry.evaluate(derivative_sha, revoke_id, usage())
    assert stale.status == EligibilityStatus.HOLD_STALE_RIGHTS.value
    assert blocked.status == EligibilityStatus.BLOCKED.value


def test_append_only_triggers_block_direct_update_and_delete():
    registry = RightsRegistry()
    original_id, _ = make_asset(registry)
    rights_id = add_rights(registry, original_id)
    with pytest.raises(sqlite3.DatabaseError):
        registry.connection.execute(
            "UPDATE image_rights_records SET rights_holder='forged' WHERE rights_record_id=?", (rights_id,)
        )
    registry.connection.rollback()
    with pytest.raises(sqlite3.DatabaseError):
        registry.connection.execute("DELETE FROM image_rights_records WHERE rights_record_id=?", (rights_id,))
    registry.connection.rollback()
    assert registry.integrity_check() == "ok"


def test_m05_hold_stays_hold_before_rights_evaluation():
    registry = RightsRegistry()
    original_id, asset_sha = make_asset(registry)
    rights_id = add_rights(registry, original_id)
    bundle = make_bundle(exact_primary=False)
    assert bundle.rights_input_ready is False
    bound = bind_rights_bound_visual_input(
        bundle, registry, asset_sha256=asset_sha, rights_record_id=rights_id,
        intended_at_utc=INTENDED, territory="RO",
    )
    assert bound.status == VisualBindingStatus.HOLD_INPUT_NOT_READY.value
    assert bound.visual_input_ready is False
    assert bound.eligibility == ()


def test_m05_bundle_tampering_is_rejected():
    registry = RightsRegistry()
    original_id, asset_sha = make_asset(registry)
    rights_id = add_rights(registry, original_id)
    forged = replace(make_bundle(), topic="forged-topic")
    with pytest.raises(ValueError, match="integrity"):
        bind_rights_bound_visual_input(
            forged, registry, asset_sha256=asset_sha, rights_record_id=rights_id,
            intended_at_utc=INTENDED, territory="RO",
        )


def test_deterministic_replay_across_fresh_registries():
    def run_once():
        registry = RightsRegistry()
        original_id, asset_sha = make_asset(registry)
        rights_id = add_rights(registry, original_id)
        return bind_rights_bound_visual_input(
            make_bundle(), registry, asset_sha256=asset_sha, rights_record_id=rights_id,
            intended_at_utc=INTENDED, territory="RO",
        )
    a = run_once()
    b = run_once()
    assert a == b
    assert a.binding_hash == b.binding_hash
    assert [x.eligibility_hash for x in a.eligibility] == [x.eligibility_hash for x in b.eligibility]


def test_no_network_account_visual_queue_or_publish_authority():
    registry = RightsRegistry()
    original_id, asset_sha = make_asset(registry)
    rights_id = add_rights(registry, original_id)
    bound = bind_rights_bound_visual_input(
        make_bundle(), registry, asset_sha256=asset_sha, rights_record_id=rights_id,
        intended_at_utc=INTENDED, territory="RO",
    )
    assert bound.state == "RIGHTS_BOUND_VISUAL_INPUT_ONLY"
    assert bound.rights_authority is True
    assert bound.fact_authority is False
    assert bound.visual_authority is False
    assert bound.queue_authority is False
    assert bound.publish_authority is False
    assert bound.network_fetch_performed is False
    assert bound.real_account_connection_performed is False


def test_cp39_policy_matches_canon_and_is_fail_closed():
    policy = json.loads((ROOT / "config" / "image_rights_policy.json").read_text())
    assert policy["checkpoint"] == "CP39"
    assert policy["model_version"] == IMAGE_RIGHTS_MODEL_VERSION
    assert policy["active_platforms"] == list(ACTIVE_NATIVE_PLATFORMS)
    assert policy["auto_eligible_rights_statuses"] == ["OWNED", "LICENSED", "PUBLIC_DOMAIN"]
    assert policy["deferred_platforms"]["LINKEDIN"] == "PRODUCTION_API_ACCESS_REQUIRED"
    assert policy["deferred_platforms"]["X"] == "EXCLUDED_WHILE_API_PAID"
    assert policy["deferred_platforms"]["BLUESKY"] == "HOLD_ROI"
    assert policy["rules"]["public_visibility_is_reuse_permission"] is False
    assert policy["rules"]["rights_bound_visual_requires_all_active_lanes_eligible"] is True
    assert policy["authority"]["rights_authority"] is True
    assert policy["authority"]["visual_authority"] is False
    assert policy["authority"]["publish_authority"] is False
    assert policy["authority"]["network_fetch_allowed"] is False
    assert policy["authority"]["real_account_connection_allowed"] is False
    assert policy["authority"]["deploy_allowed"] is False
