from __future__ import annotations

import sqlite3
import pytest

from public_presence_os.rights import *

T0="2026-09-06T08:00:00Z"
T1="2026-09-06T09:00:00Z"
SHA_A="a"*64
SHA_B="b"*64
SHA_C="c"*64
SHA_D="d"*64
SHA_E="e"*64


def evidence(uri="https://example.org/license"):
    return EvidenceSnapshot("LICENSE_TERMS_SNAPSHOT", SHA_C, 100, uri, T0, "snapshot")


def source(reg, *, role="ACQUISITION", reuse="RIGHTS_RECORD_REQUIRED"):
    return reg.register_source_revision(
        source_id="SRC1", revision=1, source_class="FIRST_PARTY", display_name="Owner library",
        source_url="https://example.org/source", discovery_role=role, reuse_default=reuse,
        license_or_basis="OWNER_ATTESTATION", restrictions={}, status="ACTIVE", verified_at=T0,
    )


def original(reg, src, *, media="CONTEXTUAL_PHOTO", clearance="CLEARED", route="FIRST_PARTY_UPLOAD"):
    return reg.register_original(
        original_sha256=SHA_A, mime_type="image/jpeg", byte_size=1234, media_class=media,
        creator_name="Owner", creator_identity_status="VERIFIED", acquisition_route=route,
        acquisition_source_revision_id=src["source_revision_id"], source_url="https://example.org/photo.jpg",
        subject_clearance_status=clearance, metadata={"camera":"fixture"},
    )


def rights(reg, orig, snap, *, status="OWNED", basis="OWNER_ATTESTATION", platforms=None,
           purposes=("SOCIAL_EDITORIAL",), territory="WORLDWIDE", commercial=True, modification="ALLOWED",
           attribution=False, attribution_text=None, share=False, output_license=None,
           expires=None, review=None, revision=1, supersedes=None, license_name=None, license_url=None):
    platforms = platforms or ("FACEBOOK_PAGE","INSTAGRAM_PROFESSIONAL","THREADS")
    r=reg.register_rights_record(
        original_id=orig["original_id"], revision=revision, rights_status=status, basis_type=basis,
        rights_holder="Owner", permitted_platforms=platforms, permitted_purposes=purposes,
        territory=territory, commercial_use_allowed=commercial, modification_policy=modification,
        attribution_required=attribution, attribution_text=attribution_text, share_alike_required=share,
        required_output_license=output_license, valid_from=T0, expires_at=expires, review_at=review,
        revocable=True, evidence_set_hash_value=evidence_set_hash([snap]), terms_hash_value=terms_hash({"v":1}),
        supersedes_rights_record_id=supersedes, license_name=license_name, license_url=license_url,
    )
    reg.register_evidence(r["rights_record_id"], snap)
    return r


def usage(platform="FACEBOOK_PAGE", **kw):
    return UsageRequest(platform=platform, purpose=kw.pop("purpose","SOCIAL_EDITORIAL"), intended_at=kw.pop("intended_at",T1),
                        modifications_required=kw.pop("modifications_required",True), commercial_context=kw.pop("commercial_context",True),
                        territory=kw.pop("territory","RO"), output_license=kw.pop("output_license",None), **kw)


def ready_registry(**orig_kw):
    reg=RightsRegistry.memory(); s=source(reg); o=original(reg,s,**orig_kw); snap=evidence(); r=rights(reg,o,snap)
    return reg,s,o,snap,r


def test_migration_idempotent_and_integrity():
    reg=RightsRegistry.memory(); reg.migrate(); reg.migrate(); assert reg.integrity_check()=="ok"


def test_prohibited_acquisition_routes_fail_closed():
    reg=RightsRegistry.memory(); s=source(reg)
    for route in PROHIBITED_ACQUISITION_ROUTES:
        with pytest.raises(RightsError): original(reg,s,route=route)


def test_discovery_only_source_cannot_acquire_original():
    reg=RightsRegistry.memory(); s=source(reg,role="DISCOVERY_ONLY")
    with pytest.raises(RightsError): original(reg,s)


def test_append_only_tables_reject_update_and_delete():
    reg,s,o,snap,r=ready_registry()
    for table in ("image_source_revisions","image_originals","image_rights_records","image_rights_evidence"):
        with pytest.raises(sqlite3.IntegrityError): reg.db.execute(f"UPDATE {table} SET rowid=rowid")
        with pytest.raises(sqlite3.IntegrityError): reg.db.execute(f"DELETE FROM {table}")
        reg.db.rollback()


def test_owned_rights_are_render_qa_eligible_only():
    reg,s,o,snap,r=ready_registry(); result=reg.evaluate(SHA_A,r["rights_record_id"],usage())
    assert result.status=="ELIGIBLE_RENDER_QA" and result.render_qa_eligible
    assert not result.publish_eligible and not result.queue_authority and not result.publish_authority
    assert not result.network_fetch_performed and not result.real_account_connection_performed


def test_only_active_platforms_can_pass():
    reg,s,o,snap,r=ready_registry(); result=reg.evaluate(SHA_A,r["rights_record_id"],usage("LINKEDIN"))
    assert result.status=="HOLD_RIGHTS" and "PLATFORM_NOT_ACTIVE" in result.reasons


def test_evidence_is_snapshot_bound_not_url_only():
    reg=RightsRegistry.memory(); s=source(reg); o=original(reg,s); snap=evidence()
    r=reg.register_rights_record(original_id=o["original_id"],revision=1,rights_status="OWNED",basis_type="OWNER_ATTESTATION",
        rights_holder="Owner",permitted_platforms=("FACEBOOK_PAGE",),permitted_purposes=("SOCIAL_EDITORIAL",),territory="WORLDWIDE",
        commercial_use_allowed=True,modification_policy="ALLOWED",attribution_required=False,attribution_text=None,
        share_alike_required=False,required_output_license=None,valid_from=T0,evidence_set_hash_value=evidence_set_hash([snap]),
        terms_hash_value=terms_hash({"v":1}))
    result=reg.evaluate(SHA_A,r["rights_record_id"],usage())
    assert result.status=="HOLD_RIGHTS" and "EVIDENCE_SET_HASH_MISMATCH" in result.reasons


def test_fair_use_is_always_human_review():
    reg=RightsRegistry.memory(); s=source(reg); o=original(reg,s); snap=evidence(); r=rights(reg,o,snap,status="FAIR_USE_REVIEW",basis="FAIR_USE_REVIEW")
    result=reg.evaluate(SHA_A,r["rights_record_id"],usage()); assert result.status=="HOLD_HUMAN_REVIEW"


def test_unknown_and_blocked_are_never_eligible():
    for st,expected in (("UNKNOWN","HOLD_RIGHTS"),("BLOCKED","BLOCKED")):
        reg=RightsRegistry.memory(); s=source(reg); o=original(reg,s); snap=evidence(); r=rights(reg,o,snap,status=st,basis="UNKNOWN" if st=="UNKNOWN" else "REVOCATION")
        assert reg.evaluate(SHA_A,r["rights_record_id"],usage()).status==expected


def test_subject_pending_requires_human_review():
    reg,s,o,snap,r=ready_registry(clearance="PENDING"); assert reg.evaluate(SHA_A,r["rights_record_id"],usage()).status=="HOLD_HUMAN_REVIEW"


def test_subject_blocked_is_hard_stop():
    reg,s,o,snap,r=ready_registry(clearance="BLOCKED"); assert reg.evaluate(SHA_A,r["rights_record_id"],usage()).status=="BLOCKED"


def test_profile_photo_cannot_be_editorial_post_media():
    reg,s,o,snap,r=ready_registry(media="PROFILE_PHOTO"); result=reg.evaluate(SHA_A,r["rights_record_id"],usage())
    assert result.status=="BLOCKED" and "PROFILE_PHOTO_NOT_EDITORIAL_MEDIA" in result.reasons


@pytest.mark.parametrize("kwargs,reason",[
    ({"platforms":("INSTAGRAM_PROFESSIONAL",)},"PLATFORM_NOT_GRANTED"),
    ({"purposes":("PROFILE_DISPLAY",)},"PURPOSE_NOT_GRANTED"),
    ({"territory":"IT"},"TERRITORY_NOT_GRANTED"),
    ({"commercial":False},"COMMERCIAL_USE_NOT_GRANTED"),
    ({"modification":"NO_DERIVATIVES"},"MODIFICATION_NOT_GRANTED"),
])
def test_license_scope_is_fail_closed(kwargs,reason):
    reg=RightsRegistry.memory(); s=source(reg); o=original(reg,s); snap=evidence(); r=rights(reg,o,snap,**kwargs)
    result=reg.evaluate(SHA_A,r["rights_record_id"],usage()); assert result.status=="HOLD_RIGHTS" and reason in result.reasons


def test_attribution_text_required_at_registration():
    reg=RightsRegistry.memory(); s=source(reg); o=original(reg,s); snap=evidence()
    with pytest.raises(RightsError): rights(reg,o,snap,attribution=True,attribution_text=None)


def test_share_alike_requires_compatible_output_license():
    reg=RightsRegistry.memory(); s=source(reg); o=original(reg,s); snap=evidence(); r=rights(reg,o,snap,share=True,output_license="CC-BY-SA-4.0")
    assert reg.evaluate(SHA_A,r["rights_record_id"],usage()).status=="HOLD_RIGHTS"
    assert reg.evaluate(SHA_A,r["rights_record_id"],usage(output_license="CC-BY-SA-4.0")).status=="ELIGIBLE_RENDER_QA"


def test_expired_and_overdue_review_hold():
    reg=RightsRegistry.memory(); s=source(reg); o=original(reg,s); snap=evidence(); r=rights(reg,o,snap,expires="2026-09-06T08:30:00Z")
    assert reg.evaluate(SHA_A,r["rights_record_id"],usage()).status=="HOLD_RIGHTS"
    reg2=RightsRegistry.memory(); s=source(reg2); o=original(reg2,s); snap=evidence(); r=rights(reg2,o,snap,review="2026-09-06T08:30:00Z")
    assert reg2.evaluate(SHA_A,r["rights_record_id"],usage()).status=="HOLD_STALE_RIGHTS"


def test_public_domain_basis_is_explicit():
    reg=RightsRegistry.memory(); s=source(reg); o=original(reg,s); snap=evidence()
    with pytest.raises(RightsError): rights(reg,o,snap,status="PUBLIC_DOMAIN",basis="PUBLICLY_VISIBLE")
    r=rights(reg,o,snap,status="PUBLIC_DOMAIN",basis="CC0_DEDICATION")
    assert reg.evaluate(SHA_A,r["rights_record_id"],usage()).status=="ELIGIBLE_RENDER_QA"


def test_licensed_requires_license_identity():
    reg=RightsRegistry.memory(); s=source(reg); o=original(reg,s); snap=evidence()
    with pytest.raises(RightsError): rights(reg,o,snap,status="LICENSED",basis="CC_BY_4_0")


def test_derivative_lineage_is_root_bound():
    reg,s,o,snap,r=ready_registry(); d=reg.register_derivative(derivative_sha256=SHA_B,parent_sha256=SHA_A,
        rights_record_id_at_creation=r["rights_record_id"],derivative_kind="SOCIAL_CROP",transform={"crop":"4:5"})
    result=reg.evaluate(SHA_B,r["rights_record_id"],usage()); assert result.status=="ELIGIBLE_RENDER_QA" and result.root_original_id==o["original_id"]
    assert d["derivation_hash"]


def test_revocation_supersedes_and_blocks_root_and_derivative():
    reg,s,o,snap,r1=ready_registry(); reg.register_derivative(derivative_sha256=SHA_B,parent_sha256=SHA_A,
        rights_record_id_at_creation=r1["rights_record_id"],derivative_kind="SOCIAL_CROP",transform={"crop":"4:5"})
    snap2=EvidenceSnapshot("REVOCATION_SNAPSHOT",SHA_D,90,"https://example.org/revoke",T1,"revoked")
    r2=rights(reg,o,snap2,status="BLOCKED",basis="REVOCATION",revision=2,supersedes=r1["rights_record_id"])
    assert reg.evaluate(SHA_A,r1["rights_record_id"],usage()).status=="BLOCKED"
    assert reg.evaluate(SHA_B,r1["rights_record_id"],usage()).status=="BLOCKED"
    assert reg.evaluate(SHA_A,r2["rights_record_id"],usage()).status=="BLOCKED"


def test_nonrevoked_supersession_makes_old_record_stale():
    reg,s,o,snap,r1=ready_registry(); snap2=EvidenceSnapshot("OWNER_CONFIRMATION",SHA_D,90,"https://example.org/v2",T1,"v2")
    r2=rights(reg,o,snap2,revision=2,supersedes=r1["rights_record_id"])
    assert reg.evaluate(SHA_A,r1["rights_record_id"],usage()).status=="HOLD_STALE_RIGHTS"
    assert reg.evaluate(SHA_A,r2["rights_record_id"],usage()).status=="ELIGIBLE_RENDER_QA"


def test_rights_bound_visual_input_is_deterministic_and_nonpublishing():
    reg,s,o,snap,r=ready_registry(); u=usage()
    a=reg.bind_visual_input(SHA_A,r["rights_record_id"],u); b=reg.bind_visual_input(SHA_A,r["rights_record_id"],u)
    assert a==b and a.binding_hash==b.binding_hash
    assert a.visual_render_input_authority and not a.story_fit_authority
    assert not a.queue_authority and not a.publish_authority and not a.publish_eligible
    assert not a.network_fetch_performed and not a.real_account_connection_performed
    assert a.platform=="FACEBOOK_PAGE" and a.rights_status=="OWNED"


def test_bind_rejects_hold():
    reg,s,o,snap,r=ready_registry();
    with pytest.raises(RightsError): reg.bind_visual_input(SHA_A,r["rights_record_id"],usage("LINKEDIN"))


def test_evidence_and_terms_hashes_are_deterministic():
    a=evidence(); b=evidence(); assert a.evidence_hash==b.evidence_hash
    assert evidence_set_hash([a])==evidence_set_hash([b])
    assert terms_hash({"b":2,"a":1})==terms_hash({"a":1,"b":2})
