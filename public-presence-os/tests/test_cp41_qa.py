from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import pytest
from PIL import Image, ImageFont

import public_presence_os.visual as visual
from public_presence_os.master_draft import build_master_draft_brief
from public_presence_os.native_adapt import build_native_adaptation_bundle
from public_presence_os.qa import (
    QA_MODEL_VERSION,
    VisualQAHold,
    VisualQARequest,
    audit_visual,
    build_photo_semantic_review,
)
from public_presence_os.radar import RadarKind, RadarObservation, RadarSourceClass, materialize_signal
from public_presence_os.research import EvidenceAuthority, EvidenceKind, ResearchEvidence, build_research_packet
from public_presence_os.rights import EvidenceSnapshot, RightsRegistry, UsageRequest, evidence_set_hash, terms_hash
from public_presence_os.scoring import score_research_packet
from public_presence_os.visual import FontBinding, FontBindingSet, RenderedVisual, VisualRenderRequest, render_visual

ROOT = Path(__file__).resolve().parents[1]
OBSERVED = "2026-09-06T08:30:00Z"
CAPTURED = "2026-09-06T08:40:00Z"
T0 = "2026-09-06T08:45:00Z"
T1 = "2026-09-06T09:00:00Z"


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def make_bundle(*, title="Local announcement", excerpt="Specific public detail."):
    source_url = "https://example.gov.ro/news/41"
    signal = materialize_signal(RadarObservation(
        external_ref="story-41",
        source_url=source_url,
        source_class=RadarSourceClass.PRIMARY_PUBLIC,
        kind=RadarKind.ANNOUNCEMENT,
        observed_at_utc=OBSERVED,
        title=title,
        excerpt=excerpt,
        topic="transport",
        locality="Valcea",
        synthetic=False,
    ))
    packet = build_research_packet(signal, [ResearchEvidence(
        evidence_id="ev41",
        source_url=source_url,
        authority=EvidenceAuthority.PRIMARY_SOURCE,
        kind=EvidenceKind.DETAIL_PAGE,
        captured_at_utc=CAPTURED,
        content_sha256=h("evidence-41"),
    )])
    scorecard = score_research_packet(packet)
    brief = build_master_draft_brief(packet, scorecard)
    return build_native_adaptation_bundle(brief)


def make_fonts(tmp_path: Path) -> FontBindingSet:
    rows = []
    for name in ("display", "editorial", "italic", "mono"):
        p = tmp_path / f"{name}.font-fixture"
        p.write_bytes((f"fixture-{name}-41").encode())
        rows.append((str(p), sha256(p.read_bytes()).hexdigest()))
    return FontBindingSet(
        display=FontBinding("DISPLAY", "Fixture Sans", "SemiBold", rows[0][0], rows[0][1]),
        editorial=FontBinding("EDITORIAL", "Fixture Serif", "Regular", rows[1][0], rows[1][1]),
        editorial_italic=FontBinding("EDITORIAL_ITALIC", "Fixture Serif", "Italic", rows[2][0], rows[2][1]),
        marginalia=FontBinding("MARGINALIA", "Fixture Mono", "Medium", rows[3][0], rows[3][1]),
    )


@pytest.fixture(autouse=True)
def default_font(monkeypatch):
    monkeypatch.setattr(visual, "_font", lambda binding, size: ImageFont.load_default(size=size))


def synthetic_png() -> bytes:
    img = Image.new("RGB", (640, 480), (205, 202, 194))
    out = BytesIO()
    img.save(out, format="PNG", compress_level=9, optimize=False)
    return out.getvalue()


def rights_binding(photo: bytes, platform="FACEBOOK_PAGE", *, attribution=False):
    reg = RightsRegistry.memory()
    source = reg.register_source_revision(
        source_id="SRC41", revision=1, source_class="FIRST_PARTY", display_name="Owner library",
        source_url="https://example.org/source", discovery_role="ACQUISITION", reuse_default="RIGHTS_RECORD_REQUIRED",
        license_or_basis="OWNER_ATTESTATION", restrictions={}, status="ACTIVE", verified_at=T0,
    )
    photo_hash = sha256(photo).hexdigest()
    original = reg.register_original(
        original_sha256=photo_hash, mime_type="image/png", byte_size=len(photo), media_class="CONTEXTUAL_PHOTO",
        creator_name="Owner", creator_identity_status="VERIFIED", acquisition_route="FIRST_PARTY_UPLOAD",
        acquisition_source_revision_id=source["source_revision_id"], source_url="https://example.org/photo.png",
        subject_clearance_status="CLEARED", metadata={"fixture": True},
    )
    snapshot = EvidenceSnapshot("OWNER_CONFIRMATION", h("rights-evidence-41"), 80, "https://example.org/rights", T0, "fixture")
    record = reg.register_rights_record(
        original_id=original["original_id"], revision=1, rights_status="OWNED", basis_type="OWNER_ATTESTATION",
        rights_holder="Owner", permitted_platforms=("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"),
        permitted_purposes=("SOCIAL_EDITORIAL",), territory="WORLDWIDE", commercial_use_allowed=True,
        modification_policy="ALLOWED", attribution_required=attribution,
        attribution_text="Photo: Owner" if attribution else None, share_alike_required=False,
        required_output_license=None, valid_from=T0, evidence_set_hash_value=evidence_set_hash([snapshot]),
        terms_hash_value=terms_hash({"v": 1}),
    )
    reg.register_evidence(record["rights_record_id"], snapshot)
    binding = reg.bind_visual_input(
        photo_hash, record["rights_record_id"],
        UsageRequest(platform=platform, purpose="SOCIAL_EDITORIAL", intended_at=T1,
                     modifications_required=True, commercial_context=True, territory="RO"),
    )
    return reg, binding


def test_text_card_qa_validates_bytes_text_and_alt_but_preserves_identity_hold(tmp_path):
    bundle = make_bundle()
    rendered = render_visual(VisualRenderRequest(bundle, "FACEBOOK_PAGE", "TEXT_CARD", make_fonts(tmp_path)))
    report = audit_visual(VisualQARequest(rendered=rendered, bundle=bundle))
    assert report.model_version == QA_MODEL_VERSION
    assert report.integrity_status == "PASS_EXACT_BYTE_BINDING"
    assert report.text_integrity_status == "PASS_EXACT_SOURCE_BOUND_DISPLAY_TEXT"
    assert report.alt_text == "Local announcement"
    assert report.alt_text_status == "PASS_DISPLAY_TEXT_EXACT"
    assert report.photo_relevance_status == "NOT_APPLICABLE"
    assert report.subject_safe_zone_status == "NOT_APPLICABLE"
    assert report.identity_equivalence_status == "HOLD_HISTORICAL_EXACT_FONT_HASHES_UNRECOVERED"
    assert report.holds == ("HOLD_IDENTITY_EQUIVALENCE",)
    assert report.approval_input_ready is False
    assert report.queue_authority is False and report.publish_authority is False and report.publish_eligible is False


def test_qa_rejects_png_byte_tamper(tmp_path):
    bundle = make_bundle()
    rendered = render_visual(VisualRenderRequest(bundle, "FACEBOOK_PAGE", "TEXT_CARD", make_fonts(tmp_path)))
    tampered = replace(rendered, png_bytes=rendered.png_bytes + b"x")
    with pytest.raises(VisualQAHold, match="HOLD_PNG_HASH_OR_SIZE_MISMATCH"):
        audit_visual(VisualQARequest(tampered, bundle))


def test_qa_rejects_svg_active_content_even_if_manifest_hash_is_forged(tmp_path):
    bundle = make_bundle()
    rendered = render_visual(VisualRenderRequest(bundle, "FACEBOOK_PAGE", "TEXT_CARD", make_fonts(tmp_path)))
    bad_svg = rendered.svg_bytes.replace(b"</svg>", b"<script>alert(1)</script></svg>")
    forged_manifest = replace(
        rendered.manifest,
        svg_sha256=sha256(bad_svg).hexdigest(),
        svg_size=len(bad_svg),
    )
    forged = RenderedVisual(forged_manifest, bad_svg, rendered.png_bytes)
    with pytest.raises(visual.VisualHold, match="HOLD_SVG_EXTERNAL_OR_ACTIVE_CONTENT"):
        audit_visual(VisualQARequest(forged, bundle))


def test_qa_rejects_manifest_binding_to_different_bundle(tmp_path):
    bundle = make_bundle()
    other = make_bundle(title="Different announcement")
    rendered = render_visual(VisualRenderRequest(bundle, "FACEBOOK_PAGE", "TEXT_CARD", make_fonts(tmp_path)))
    with pytest.raises(VisualQAHold, match="HOLD_M05_MANIFEST_BINDING_MISMATCH"):
        audit_visual(VisualQARequest(rendered, other))


def test_photo_frame_without_semantic_review_is_held(tmp_path):
    photo = synthetic_png()
    reg, binding = rights_binding(photo)
    try:
        bundle = make_bundle()
        rendered = render_visual(VisualRenderRequest(bundle, "FACEBOOK_PAGE", "PHOTO_FRAME", make_fonts(tmp_path), binding, photo))
        report = audit_visual(VisualQARequest(rendered, bundle, rights_input=binding))
        assert report.rights_status == "PASS_RIGHTS_BOUND"
        assert "HOLD_PHOTO_SEMANTIC_REVIEW_REQUIRED" in report.holds
        assert "HOLD_ALT_TEXT_MISSING" in report.holds
        assert "HOLD_IDENTITY_EQUIVALENCE" in report.holds
        assert report.approval_input_ready is False
    finally:
        reg.close()


def test_photo_frame_with_bound_semantic_review_passes_photo_gates(tmp_path):
    photo = synthetic_png()
    reg, binding = rights_binding(photo, attribution=True)
    try:
        bundle = make_bundle()
        rendered = render_visual(VisualRenderRequest(bundle, "FACEBOOK_PAGE", "PHOTO_FRAME", make_fonts(tmp_path), binding, photo))
        review = build_photo_semantic_review(
            rendered,
            relevance_status="CONFIRMED_RELEVANT",
            subject_safe_zone_status="PASS",
            alt_text="Contextual photograph illustrating the location named in the source.",
            reviewer_mode="LOCAL_VISION_REVIEW",
            reviewed_at_utc="2026-09-06T09:10:00Z",
            evidence_sha256=h("semantic-review-41"),
        )
        report = audit_visual(VisualQARequest(rendered, bundle, rights_input=binding, photo_review=review))
        assert report.rights_status == "PASS_RIGHTS_BOUND"
        assert report.alt_text_status == "PASS_REVIEW_BOUND"
        assert report.photo_relevance_status == "CONFIRMED_RELEVANT"
        assert report.subject_safe_zone_status == "PASS"
        assert report.holds == ("HOLD_IDENTITY_EQUIVALENCE",)
    finally:
        reg.close()


def test_photo_review_failures_remain_explicit_holds(tmp_path):
    photo = synthetic_png()
    reg, binding = rights_binding(photo)
    try:
        bundle = make_bundle()
        rendered = render_visual(VisualRenderRequest(bundle, "FACEBOOK_PAGE", "PHOTO_FRAME", make_fonts(tmp_path), binding, photo))
        review = build_photo_semantic_review(
            rendered,
            relevance_status="UNKNOWN",
            subject_safe_zone_status="FAIL",
            alt_text="A contextual photograph awaiting story-fit confirmation.",
            reviewer_mode="HUMAN_REVIEW",
            reviewed_at_utc="2026-09-06T09:10:00Z",
            evidence_sha256=h("semantic-review-41b"),
        )
        report = audit_visual(VisualQARequest(rendered, bundle, rights_input=binding, photo_review=review))
        assert "HOLD_PHOTO_RELEVANCE_NOT_CONFIRMED" in report.holds
        assert "HOLD_PHOTO_SUBJECT_SAFE_ZONE" in report.holds
    finally:
        reg.close()


def test_photo_review_hash_tamper_fails_closed(tmp_path):
    photo = synthetic_png()
    reg, binding = rights_binding(photo)
    try:
        bundle = make_bundle()
        rendered = render_visual(VisualRenderRequest(bundle, "FACEBOOK_PAGE", "PHOTO_FRAME", make_fonts(tmp_path), binding, photo))
        review = build_photo_semantic_review(
            rendered,
            relevance_status="CONFIRMED_RELEVANT",
            subject_safe_zone_status="PASS",
            alt_text="Contextual photograph.",
            reviewer_mode="HUMAN_REVIEW",
            reviewed_at_utc="2026-09-06T09:10:00Z",
            evidence_sha256=h("semantic-review-41c"),
        )
        forged = replace(review, alt_text="Forged description")
        with pytest.raises(VisualQAHold, match="HOLD_PHOTO_REVIEW_HASH_MISMATCH"):
            audit_visual(VisualQARequest(rendered, bundle, rights_input=binding, photo_review=forged))
    finally:
        reg.close()


def test_photo_rights_binding_platform_mismatch_fails_closed(tmp_path):
    photo = synthetic_png()
    reg, binding = rights_binding(photo, platform="INSTAGRAM_PROFESSIONAL")
    try:
        bundle = make_bundle()
        rendered = render_visual(VisualRenderRequest(bundle, "INSTAGRAM_PROFESSIONAL", "PHOTO_FRAME", make_fonts(tmp_path), binding, photo))
        forged_binding = replace(binding, platform="FACEBOOK_PAGE")
        with pytest.raises(VisualQAHold, match="HOLD_M13_USAGE_MISMATCH"):
            audit_visual(VisualQARequest(rendered, bundle, rights_input=forged_binding))
    finally:
        reg.close()


def test_qa_policy_is_nonpublishing_and_identity_fail_closed():
    policy = json.loads((ROOT / "config" / "qa_policy.json").read_text())
    assert policy["checkpoint"] == "CP41"
    assert policy["active_platforms"] == ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"]
    assert policy["photo_semantic_gate"]["relevance_pass"] == "CONFIRMED_RELEVANT"
    assert policy["photo_semantic_gate"]["subject_safe_zone_pass"] == "PASS"
    assert policy["identity_equivalence"]["state"] == "HOLD_HISTORICAL_EXACT_FONT_HASHES_UNRECOVERED"
    assert policy["authority"]["visual_qa_authority"] is True
    for key in ("approval_authority", "queue_authority", "publish_authority", "network_fetch_allowed", "real_account_connection_allowed", "deploy_allowed"):
        assert policy["authority"][key] is False
