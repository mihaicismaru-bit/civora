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
from public_presence_os.radar import RadarKind, RadarObservation, RadarSourceClass, materialize_signal
from public_presence_os.research import EvidenceAuthority, EvidenceKind, ResearchEvidence, build_research_packet
from public_presence_os.rights import (
    EvidenceSnapshot,
    RightsRegistry,
    UsageRequest,
    evidence_set_hash,
    terms_hash,
)
from public_presence_os.scoring import score_research_packet
from public_presence_os.visual import (
    FontBinding,
    FontBindingSet,
    VisualHold,
    VisualRenderRequest,
    render_visual,
    validate_svg_self_contained,
    write_rendered_visual,
)

ROOT = Path(__file__).resolve().parents[1]
OBSERVED = "2026-09-06T07:30:00Z"
CAPTURED = "2026-09-06T07:40:00Z"
T0 = "2026-09-06T07:45:00Z"
T1 = "2026-09-06T08:00:00Z"


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def make_bundle(*, title="Local announcement", excerpt="Specific public detail."):
    source_url = "https://example.gov.ro/news/40"
    signal = materialize_signal(RadarObservation(
        external_ref="story-40",
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
    packet = build_research_packet(signal, [
        ResearchEvidence(
            evidence_id="ev40",
            source_url=source_url,
            authority=EvidenceAuthority.PRIMARY_SOURCE,
            kind=EvidenceKind.DETAIL_PAGE,
            captured_at_utc=CAPTURED,
            content_sha256=h("evidence-40"),
        )
    ])
    scorecard = score_research_packet(packet)
    brief = build_master_draft_brief(packet, scorecard)
    return build_native_adaptation_bundle(brief)


def make_fonts(tmp_path: Path) -> FontBindingSet:
    rows = []
    for name in ("display", "editorial", "italic", "mono"):
        p = tmp_path / f"{name}.font-fixture"
        p.write_bytes((f"fixture-{name}-40").encode())
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
    img = Image.new("RGB", (640, 480), (210, 205, 195))
    out = BytesIO()
    img.save(out, format="PNG", compress_level=9, optimize=False)
    return out.getvalue()


def rights_binding(photo: bytes, platform="FACEBOOK_PAGE", *, attribution=False):
    reg = RightsRegistry.memory()
    source = reg.register_source_revision(
        source_id="SRC40", revision=1, source_class="FIRST_PARTY", display_name="Owner library",
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
    snapshot = EvidenceSnapshot("OWNER_CONFIRMATION", h("rights-evidence-40"), 80, "https://example.org/rights", T0, "fixture")
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


def test_text_card_renders_deterministic_svg_png(tmp_path):
    bundle = make_bundle()
    fonts = make_fonts(tmp_path)
    req = VisualRenderRequest(bundle, "FACEBOOK_PAGE", "TEXT_CARD", fonts)
    a = render_visual(req)
    b = render_visual(req)
    assert a == b
    assert a.svg_bytes == b.svg_bytes and a.png_bytes == b.png_bytes
    assert a.manifest.width == 1080 and a.manifest.height == 1080
    assert a.manifest.state == "MEDIA_PREVIEW_READY"
    assert a.manifest.visual_qa_input_ready is True
    assert a.manifest.publish_eligible is False
    assert a.manifest.queue_authority is False and a.manifest.publish_authority is False
    assert a.manifest.canonical_identity_equivalent is False
    assert "Local announcement" in a.svg_bytes.decode("utf-8")
    validate_svg_self_contained(a.svg_bytes)


def test_instagram_and_threads_use_portrait_canvas(tmp_path):
    bundle = make_bundle()
    fonts = make_fonts(tmp_path)
    for platform in ("INSTAGRAM_PROFESSIONAL", "THREADS"):
        rendered = render_visual(VisualRenderRequest(bundle, platform, "TEXT_CARD", fonts))
        assert (rendered.manifest.width, rendered.manifest.height) == (1080, 1350)


def test_visual_refuses_non_active_platform(tmp_path):
    with pytest.raises(VisualHold, match="HOLD_PLATFORM_NOT_ACTIVE"):
        render_visual(VisualRenderRequest(make_bundle(), "LINKEDIN", "TEXT_CARD", make_fonts(tmp_path)))


def test_visual_refuses_m05_hash_tamper(tmp_path):
    bundle = make_bundle()
    forged = replace(bundle, topic="forged")
    with pytest.raises(VisualHold, match="HOLD_M05_BUNDLE_HASH_MISMATCH"):
        render_visual(VisualRenderRequest(forged, "FACEBOOK_PAGE", "TEXT_CARD", make_fonts(tmp_path)))


def test_font_binding_hash_mismatch_fails_closed(tmp_path):
    fonts = make_fonts(tmp_path)
    bad = replace(fonts, display=replace(fonts.display, expected_sha256="0" * 64))
    with pytest.raises(VisualHold, match="HOLD_FONT_HASH_MISMATCH"):
        render_visual(VisualRenderRequest(make_bundle(), "FACEBOOK_PAGE", "TEXT_CARD", bad))


def test_exact_text_is_not_truncated_to_fit(tmp_path):
    bundle = make_bundle(title="X" * 700)
    with pytest.raises(VisualHold, match="HOLD_GEOMETRY"):
        render_visual(VisualRenderRequest(bundle, "FACEBOOK_PAGE", "TEXT_CARD", make_fonts(tmp_path)))


def test_text_card_rejects_photo_inputs(tmp_path):
    photo = synthetic_png()
    reg, binding = rights_binding(photo)
    try:
        with pytest.raises(VisualHold, match="HOLD_TEXT_CARD_MUST_NOT_CONSUME_PHOTO"):
            render_visual(VisualRenderRequest(make_bundle(), "FACEBOOK_PAGE", "TEXT_CARD", make_fonts(tmp_path), binding, photo))
    finally:
        reg.close()


def test_photo_frame_requires_exact_m13_binding_and_source_hash(tmp_path):
    photo = synthetic_png()
    reg, binding = rights_binding(photo)
    try:
        rendered = render_visual(VisualRenderRequest(make_bundle(), "FACEBOOK_PAGE", "PHOTO_FRAME", make_fonts(tmp_path), binding, photo))
        assert rendered.manifest.rights_binding_hash == binding.binding_hash
        assert rendered.manifest.source_media_sha256 == sha256(photo).hexdigest()
        assert rendered.manifest.displayed_text_sha256 is None
        assert rendered.manifest.subject_safe_zone_status == "PENDING_VISUAL_QA"
        assert "Local announcement" not in rendered.svg_bytes.decode("utf-8")
        validate_svg_self_contained(rendered.svg_bytes)
        with pytest.raises(VisualHold, match="HOLD_SOURCE_MEDIA_HASH_MISMATCH"):
            render_visual(VisualRenderRequest(make_bundle(), "FACEBOOK_PAGE", "PHOTO_FRAME", make_fonts(tmp_path), binding, photo + b"x"))
    finally:
        reg.close()


def test_photo_frame_binding_platform_must_match(tmp_path):
    photo = synthetic_png()
    reg, binding = rights_binding(photo, platform="INSTAGRAM_PROFESSIONAL")
    try:
        with pytest.raises(VisualHold, match="HOLD_M13_USAGE_MISMATCH"):
            render_visual(VisualRenderRequest(make_bundle(), "FACEBOOK_PAGE", "PHOTO_FRAME", make_fonts(tmp_path), binding, photo))
    finally:
        reg.close()


def test_photo_credit_is_outside_image_and_only_when_rights_require(tmp_path):
    photo = synthetic_png()
    reg, binding = rights_binding(photo, attribution=True)
    try:
        rendered = render_visual(VisualRenderRequest(make_bundle(), "FACEBOOK_PAGE", "PHOTO_FRAME", make_fonts(tmp_path), binding, photo))
        assert "Photo: Owner" in rendered.svg_bytes.decode("utf-8")
        assert "Local announcement" not in rendered.svg_bytes.decode("utf-8")
    finally:
        reg.close()


def test_idempotent_write_and_tamper_conflict(tmp_path):
    rendered = render_visual(VisualRenderRequest(make_bundle(), "FACEBOOK_PAGE", "TEXT_CARD", make_fonts(tmp_path)))
    out = tmp_path / "out"
    first = write_rendered_visual(out, rendered)
    second = write_rendered_visual(out, rendered)
    assert first == second
    first[0].write_text("tampered", encoding="utf-8")
    with pytest.raises(VisualHold, match="HOLD_DETERMINISTIC_PATH_CONFLICT"):
        write_rendered_visual(out, rendered)


def test_policy_preserves_cp29_identity_and_font_hash_blocker():
    policy = json.loads((ROOT / "config" / "visual_identity_policy.json").read_text())
    assert policy["checkpoint"] == "CP40"
    assert policy["identity_name"] == "EDITORIAL_LEDGER_V1"
    assert policy["active_platforms"] == ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"]
    assert policy["palette"]["paper"] == "#F4F0E8" and policy["palette"]["signal"] == "#B33A2B"
    assert policy["font_binding_state"] == "HOLD_HISTORICAL_EXACT_FONT_HASHES_UNRECOVERED"
    assert policy["production_identity_equivalence_asserted"] is False
    assert all(v["canonical_sha256"] is None for v in policy["font_roles"].values())
    assert policy["font_bytes_packaged"] is False
    assert policy["photo_policy"]["factual_overlay_allowed"] is False
    assert policy["authority"]["visual_render_authority"] is True
    for key in ("visual_qa_authority", "queue_authority", "publish_authority", "network_fetch_allowed", "real_account_connection_allowed", "deploy_allowed"):
        assert policy["authority"][key] is False


def test_canonical_identity_equivalence_requires_all_exact_hashes(tmp_path):
    fonts = make_fonts(tmp_path)
    assert fonts.canonical_identity_equivalent({}) is False
    hashes = {row["role"]: row["sha256"] for row in fonts.verified_rows()}
    assert fonts.canonical_identity_equivalent(hashes) is False  # family names are fixtures, not CP29 canonical families
