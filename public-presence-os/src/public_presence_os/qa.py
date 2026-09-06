from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from io import BytesIO
import re
import xml.etree.ElementTree as ET

from .control import EXPECTED_ACTIVE, canonical_json, sha256_bytes
from .native_adapt import NATIVE_ADAPT_MODEL_VERSION, NativeAdaptationBundle, NativeAdaptationStatus
from .rights import AUTO_ELIGIBLE_RIGHTS, RIGHTS_BOUND_VISUAL_INPUT_VERSION, RightsBoundVisualInput
from .visual import (
    CANVAS,
    RENDERER_VERSION,
    VISUAL_MODEL_VERSION,
    RenderedVisual,
    validate_svg_self_contained,
)

try:
    from PIL import Image
except Exception:  # pragma: no cover - reported fail-closed at QA time
    Image = None

QA_MODEL_VERSION = "PPOS_VISUAL_QA_V1"
QA_ENGINE_VERSION = "ppos-visual-qa-v1.0.0"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

PHOTO_RELEVANCE_PASS = "CONFIRMED_RELEVANT"
PHOTO_SAFE_ZONE_PASS = "PASS"
PHOTO_REVIEW_MODES = {"HUMAN_REVIEW", "LOCAL_VISION_REVIEW"}


class VisualQAError(ValueError):
    pass


class VisualQAHold(VisualQAError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class VisualQAVerdict(str, Enum):
    PASS = "PASS_VISUAL_QA"
    HOLD = "HOLD_VISUAL_QA"


@dataclass(frozen=True)
class PhotoSemanticReview:
    review_id: str
    review_hash: str
    model_version: str
    asset_id: str
    png_sha256: str
    source_media_sha256: str
    relevance_status: str
    subject_safe_zone_status: str
    alt_text: str
    reviewer_mode: str
    reviewed_at_utc: str
    evidence_sha256: str
    notes: str = ""
    state: str = "PHOTO_SEMANTIC_QA_EVIDENCE_ONLY"
    story_fit_review_authority: bool = True
    queue_authority: bool = False
    publish_authority: bool = False
    network_fetch_performed: bool = False
    real_account_connection_performed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class VisualQAReport:
    report_id: str
    report_hash: str
    model_version: str
    engine_version: str
    asset_id: str
    render_key: str
    platform: str
    mode: str
    bundle_id: str
    bundle_hash: str
    adaptation_id: str
    adaptation_hash: str
    svg_sha256: str
    png_sha256: str
    width: int
    height: int
    integrity_status: str
    text_integrity_status: str
    svg_safety_status: str
    png_status: str
    rights_status: str
    alt_text: str
    alt_text_status: str
    photo_relevance_status: str
    subject_safe_zone_status: str
    identity_equivalence_status: str
    holds: tuple[str, ...]
    verdict: str
    approval_input_ready: bool
    state: str = "VISUAL_QA_ONLY"
    visual_qa_authority: bool = True
    queue_authority: bool = False
    publish_authority: bool = False
    publish_eligible: bool = False
    network_fetch_performed: bool = False
    real_account_connection_performed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class VisualQARequest:
    rendered: RenderedVisual
    bundle: NativeAdaptationBundle
    rights_input: RightsBoundVisualInput | None = None
    photo_review: PhotoSemanticReview | None = None


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _iso(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VisualQAHold("HOLD_PHOTO_REVIEW_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None:
        raise VisualQAHold("HOLD_PHOTO_REVIEW_TIMESTAMP_INVALID")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _review_body(review: PhotoSemanticReview) -> dict:
    return {
        "schema_version": QA_MODEL_VERSION,
        "asset_id": review.asset_id,
        "png_sha256": review.png_sha256,
        "source_media_sha256": review.source_media_sha256,
        "relevance_status": review.relevance_status,
        "subject_safe_zone_status": review.subject_safe_zone_status,
        "alt_text": review.alt_text,
        "reviewer_mode": review.reviewer_mode,
        "reviewed_at_utc": _iso(review.reviewed_at_utc),
        "evidence_sha256": review.evidence_sha256,
        "notes": review.notes,
        "state": "PHOTO_SEMANTIC_QA_EVIDENCE_ONLY",
        "story_fit_review_authority": True,
        "queue_authority": False,
        "publish_authority": False,
        "network_fetch_performed": False,
        "real_account_connection_performed": False,
    }


def build_photo_semantic_review(
    rendered: RenderedVisual,
    *,
    relevance_status: str,
    subject_safe_zone_status: str,
    alt_text: str,
    reviewer_mode: str,
    reviewed_at_utc: str,
    evidence_sha256: str,
    notes: str = "",
) -> PhotoSemanticReview:
    if not isinstance(rendered, RenderedVisual) or rendered.manifest.mode != "PHOTO_FRAME":
        raise VisualQAHold("HOLD_PHOTO_REVIEW_REQUIRES_PHOTO_FRAME")
    if reviewer_mode not in PHOTO_REVIEW_MODES:
        raise VisualQAHold("HOLD_PHOTO_REVIEW_MODE_INVALID")
    if not HEX64.fullmatch(evidence_sha256):
        raise VisualQAHold("HOLD_PHOTO_REVIEW_EVIDENCE_HASH_INVALID")
    clean_alt = " ".join(alt_text.split())
    if not clean_alt:
        raise VisualQAHold("HOLD_ALT_TEXT_MISSING")
    if len(clean_alt) > 500:
        raise VisualQAHold("HOLD_ALT_TEXT_LENGTH")
    source_sha = rendered.manifest.source_media_sha256
    if not source_sha:
        raise VisualQAHold("HOLD_PHOTO_SOURCE_BINDING_MISSING")
    body = {
        "schema_version": QA_MODEL_VERSION,
        "asset_id": rendered.manifest.asset_id,
        "png_sha256": rendered.manifest.png_sha256,
        "source_media_sha256": source_sha,
        "relevance_status": relevance_status,
        "subject_safe_zone_status": subject_safe_zone_status,
        "alt_text": clean_alt,
        "reviewer_mode": reviewer_mode,
        "reviewed_at_utc": _iso(reviewed_at_utc),
        "evidence_sha256": evidence_sha256,
        "notes": notes,
        "state": "PHOTO_SEMANTIC_QA_EVIDENCE_ONLY",
        "story_fit_review_authority": True,
        "queue_authority": False,
        "publish_authority": False,
        "network_fetch_performed": False,
        "real_account_connection_performed": False,
    }
    review_hash = _hash(body)
    return PhotoSemanticReview(
        review_id="pqr_" + review_hash[:24],
        review_hash=review_hash,
        model_version=QA_MODEL_VERSION,
        asset_id=rendered.manifest.asset_id,
        png_sha256=rendered.manifest.png_sha256,
        source_media_sha256=source_sha,
        relevance_status=relevance_status,
        subject_safe_zone_status=subject_safe_zone_status,
        alt_text=clean_alt,
        reviewer_mode=reviewer_mode,
        reviewed_at_utc=body["reviewed_at_utc"],
        evidence_sha256=evidence_sha256,
        notes=notes,
    )


def _validate_bundle_binding(bundle: NativeAdaptationBundle, rendered: RenderedVisual):
    manifest = rendered.manifest
    if not isinstance(bundle, NativeAdaptationBundle) or bundle.model_version != NATIVE_ADAPT_MODEL_VERSION:
        raise VisualQAHold("HOLD_M05_BUNDLE_TYPE_OR_VERSION")
    if tuple(bundle.active_platforms) != tuple(EXPECTED_ACTIVE):
        raise VisualQAHold("HOLD_ACTIVE_PLATFORM_DRIFT")
    if bundle.state != "NATIVE_ADAPTATION_ONLY" or not bundle.native_adaptation_authority:
        raise VisualQAHold("HOLD_M05_AUTHORITY_INVALID")
    if bundle.fact_authority or bundle.visual_authority or bundle.queue_authority or bundle.publish_authority:
        raise VisualQAHold("HOLD_M05_FORBIDDEN_AUTHORITY")
    if bundle.network_fetch_performed or bundle.real_account_connection_performed:
        raise VisualQAHold("HOLD_M05_EXTERNAL_SIDE_EFFECT")
    if bundle.bundle_id != manifest.bundle_id or bundle.bundle_hash != manifest.bundle_hash:
        raise VisualQAHold("HOLD_M05_MANIFEST_BINDING_MISMATCH")
    rows = [item for item in bundle.adaptations if item.adaptation_id == manifest.adaptation_id]
    if len(rows) != 1:
        raise VisualQAHold("HOLD_M05_ADAPTATION_CARDINALITY")
    item = rows[0]
    if item.platform != manifest.platform or item.adaptation_hash != manifest.adaptation_hash:
        raise VisualQAHold("HOLD_M05_ADAPTATION_BINDING_MISMATCH")
    if item.status != NativeAdaptationStatus.READY.value or not item.adaptation_ready:
        raise VisualQAHold("HOLD_M05_ADAPTATION_NOT_READY")
    if item.source_url != manifest.source_url:
        raise VisualQAHold("HOLD_SOURCE_URL_BINDING_MISMATCH")
    return item


def _validate_manifest_and_bytes(rendered: RenderedVisual) -> None:
    if not isinstance(rendered, RenderedVisual):
        raise VisualQAHold("HOLD_M06_RENDER_TYPE")
    manifest = rendered.manifest
    if manifest.model_version != VISUAL_MODEL_VERSION or manifest.renderer_version != RENDERER_VERSION:
        raise VisualQAHold("HOLD_M06_VERSION_MISMATCH")
    if manifest.platform not in EXPECTED_ACTIVE or manifest.mode not in {"TEXT_CARD", "PHOTO_FRAME"}:
        raise VisualQAHold("HOLD_M06_PLATFORM_OR_MODE")
    if manifest.state != "MEDIA_PREVIEW_READY" or not manifest.visual_qa_input_ready:
        raise VisualQAHold("HOLD_M06_NOT_QA_READY")
    if manifest.publish_eligible or manifest.queue_authority or manifest.publish_authority:
        raise VisualQAHold("HOLD_M06_FORBIDDEN_AUTHORITY")
    if manifest.network_fetch_performed or manifest.real_account_connection_performed:
        raise VisualQAHold("HOLD_M06_EXTERNAL_SIDE_EFFECT")
    expected_dims = CANVAS[manifest.platform]
    if (manifest.width, manifest.height) != expected_dims:
        raise VisualQAHold("HOLD_M06_DIMENSION_MANIFEST_MISMATCH")
    if sha256_bytes(rendered.svg_bytes) != manifest.svg_sha256 or len(rendered.svg_bytes) != manifest.svg_size:
        raise VisualQAHold("HOLD_SVG_HASH_OR_SIZE_MISMATCH")
    if sha256_bytes(rendered.png_bytes) != manifest.png_sha256 or len(rendered.png_bytes) != manifest.png_size:
        raise VisualQAHold("HOLD_PNG_HASH_OR_SIZE_MISMATCH")
    expected_render_key = _hash({
        "renderer_version": manifest.renderer_version,
        "model_version": manifest.model_version,
        "bundle_hash": manifest.bundle_hash,
        "adaptation_hash": manifest.adaptation_hash,
        "platform": manifest.platform,
        "mode": manifest.mode,
        "identity_profile_hash": manifest.identity_profile_hash,
        "renderer_env_hash": manifest.renderer_env_hash,
        "rights_binding_hash": manifest.rights_binding_hash,
        "source_media_sha256": manifest.source_media_sha256,
    })
    if expected_render_key != manifest.render_key or manifest.asset_id != "ma_" + expected_render_key[:24]:
        raise VisualQAHold("HOLD_RENDER_KEY_OR_ASSET_ID_MISMATCH")


def _validate_svg(rendered: RenderedVisual) -> None:
    try:
        validate_svg_self_contained(rendered.svg_bytes)
        root = ET.fromstring(rendered.svg_bytes)
    except VisualQAHold:
        raise
    except Exception as exc:
        raise VisualQAHold("HOLD_SVG_PARSE") from exc
    manifest = rendered.manifest
    width = root.attrib.get("width")
    height = root.attrib.get("height")
    view_box = root.attrib.get("viewBox")
    if width != str(manifest.width) or height != str(manifest.height):
        raise VisualQAHold("HOLD_SVG_DIMENSION_MISMATCH")
    if view_box != f"0 0 {manifest.width} {manifest.height}":
        raise VisualQAHold("HOLD_SVG_VIEWBOX_MISMATCH")


def _validate_png(rendered: RenderedVisual) -> None:
    if Image is None:
        raise VisualQAHold("HOLD_PILLOW_NOT_AVAILABLE")
    try:
        with Image.open(BytesIO(rendered.png_bytes)) as image:
            if (image.format or "").upper() != "PNG":
                raise VisualQAHold("HOLD_PNG_FORMAT")
            if image.size != (rendered.manifest.width, rendered.manifest.height):
                raise VisualQAHold("HOLD_PNG_DIMENSION_MISMATCH")
            if getattr(image, "n_frames", 1) != 1:
                raise VisualQAHold("HOLD_PNG_ANIMATED")
            image.verify()
    except VisualQAHold:
        raise
    except Exception as exc:
        raise VisualQAHold("HOLD_PNG_DECODE") from exc


def _validate_rights(binding: RightsBoundVisualInput, rendered: RenderedVisual) -> None:
    manifest = rendered.manifest
    if not isinstance(binding, RightsBoundVisualInput) or binding.model_version != RIGHTS_BOUND_VISUAL_INPUT_VERSION:
        raise VisualQAHold("HOLD_M13_BINDING_TYPE_OR_VERSION")
    if binding.state != "RIGHTS_BOUND_VISUAL_INPUT_ONLY" or not binding.visual_render_input_authority:
        raise VisualQAHold("HOLD_M13_AUTHORITY_INVALID")
    if binding.story_fit_authority or binding.queue_authority or binding.publish_authority or binding.publish_eligible:
        raise VisualQAHold("HOLD_M13_FORBIDDEN_AUTHORITY")
    if binding.network_fetch_performed or binding.real_account_connection_performed:
        raise VisualQAHold("HOLD_M13_EXTERNAL_SIDE_EFFECT")
    if binding.rights_status not in AUTO_ELIGIBLE_RIGHTS:
        raise VisualQAHold("HOLD_M13_RIGHTS_NOT_AUTO_ELIGIBLE")
    if binding.platform != manifest.platform or binding.purpose != "SOCIAL_EDITORIAL":
        raise VisualQAHold("HOLD_M13_USAGE_MISMATCH")
    if binding.binding_id != manifest.rights_binding_id or binding.binding_hash != manifest.rights_binding_hash:
        raise VisualQAHold("HOLD_M13_MANIFEST_BINDING_MISMATCH")
    if binding.asset_sha256 != manifest.source_media_sha256:
        raise VisualQAHold("HOLD_M13_SOURCE_HASH_MISMATCH")
    if binding.attribution_required:
        credit = (binding.attribution_text or "").strip()
        if not credit:
            raise VisualQAHold("HOLD_M13_ATTRIBUTION_MISSING")
        if credit not in rendered.svg_bytes.decode("utf-8"):
            raise VisualQAHold("HOLD_M13_ATTRIBUTION_NOT_RENDERED")


def _validate_photo_review(review: PhotoSemanticReview, rendered: RenderedVisual) -> tuple[str, str, str, list[str]]:
    if not isinstance(review, PhotoSemanticReview) or review.model_version != QA_MODEL_VERSION:
        raise VisualQAHold("HOLD_PHOTO_REVIEW_TYPE_OR_VERSION")
    if review.reviewer_mode not in PHOTO_REVIEW_MODES:
        raise VisualQAHold("HOLD_PHOTO_REVIEW_MODE_INVALID")
    if review.state != "PHOTO_SEMANTIC_QA_EVIDENCE_ONLY" or not review.story_fit_review_authority:
        raise VisualQAHold("HOLD_PHOTO_REVIEW_AUTHORITY_INVALID")
    if review.queue_authority or review.publish_authority or review.network_fetch_performed or review.real_account_connection_performed:
        raise VisualQAHold("HOLD_PHOTO_REVIEW_FORBIDDEN_AUTHORITY")
    if not HEX64.fullmatch(review.evidence_sha256):
        raise VisualQAHold("HOLD_PHOTO_REVIEW_EVIDENCE_HASH_INVALID")
    if _hash(_review_body(review)) != review.review_hash or review.review_id != "pqr_" + review.review_hash[:24]:
        raise VisualQAHold("HOLD_PHOTO_REVIEW_HASH_MISMATCH")
    manifest = rendered.manifest
    if review.asset_id != manifest.asset_id or review.png_sha256 != manifest.png_sha256:
        raise VisualQAHold("HOLD_PHOTO_REVIEW_ASSET_BINDING_MISMATCH")
    if review.source_media_sha256 != manifest.source_media_sha256:
        raise VisualQAHold("HOLD_PHOTO_REVIEW_SOURCE_BINDING_MISMATCH")
    alt = " ".join(review.alt_text.split())
    if not alt or len(alt) > 500:
        raise VisualQAHold("HOLD_ALT_TEXT_INVALID")
    holds: list[str] = []
    if review.relevance_status != PHOTO_RELEVANCE_PASS:
        holds.append("HOLD_PHOTO_RELEVANCE_NOT_CONFIRMED")
    if review.subject_safe_zone_status != PHOTO_SAFE_ZONE_PASS:
        holds.append("HOLD_PHOTO_SUBJECT_SAFE_ZONE")
    return alt, review.relevance_status, review.subject_safe_zone_status, holds


def audit_visual(request: VisualQARequest) -> VisualQAReport:
    _validate_manifest_and_bytes(request.rendered)
    _validate_svg(request.rendered)
    _validate_png(request.rendered)
    item = _validate_bundle_binding(request.bundle, request.rendered)
    manifest = request.rendered.manifest
    holds: list[str] = []

    if manifest.mode == "TEXT_CARD":
        if request.rights_input is not None or request.photo_review is not None:
            raise VisualQAHold("HOLD_TEXT_CARD_QA_MUST_NOT_CONSUME_PHOTO_EVIDENCE")
        title = next((line.strip() for line in item.text.splitlines() if line.strip()), "")
        if not title:
            raise VisualQAHold("HOLD_DISPLAY_TEXT_EMPTY")
        if manifest.displayed_text_sha256 != sha256_bytes(title.encode("utf-8")):
            raise VisualQAHold("HOLD_DISPLAY_TEXT_HASH_MISMATCH")
        rights_status = "NOT_APPLICABLE"
        alt_text = title
        alt_status = "PASS_DISPLAY_TEXT_EXACT"
        relevance_status = "NOT_APPLICABLE"
        safe_zone_status = "NOT_APPLICABLE"
        text_status = "PASS_EXACT_SOURCE_BOUND_DISPLAY_TEXT"
    else:
        if request.rights_input is None:
            raise VisualQAHold("HOLD_PHOTO_QA_REQUIRES_M13")
        _validate_rights(request.rights_input, request.rendered)
        if manifest.displayed_text_sha256 is not None:
            raise VisualQAHold("HOLD_PHOTO_FRAME_FACTUAL_OVERLAY_PRESENT")
        rights_status = "PASS_RIGHTS_BOUND"
        text_status = "PASS_NO_FACTUAL_OVERLAY"
        if request.photo_review is None:
            alt_text = ""
            alt_status = "HOLD_REVIEW_REQUIRED"
            relevance_status = "UNKNOWN"
            safe_zone_status = "UNKNOWN"
            holds.extend(("HOLD_PHOTO_SEMANTIC_REVIEW_REQUIRED", "HOLD_ALT_TEXT_MISSING"))
        else:
            alt_text, relevance_status, safe_zone_status, photo_holds = _validate_photo_review(request.photo_review, request.rendered)
            holds.extend(photo_holds)
            alt_status = "PASS_REVIEW_BOUND" if alt_text else "HOLD_ALT_TEXT_MISSING"

    # CP40 explicitly preserves this as a global production hold until exact CP29 font hashes are recovered
    # or a later versioned identity decision supersedes that requirement. M07 therefore does not trust a
    # mutable manifest boolean as sufficient authority for pilot identity equivalence.
    identity_status = "HOLD_HISTORICAL_EXACT_FONT_HASHES_UNRECOVERED"
    holds.append("HOLD_IDENTITY_EQUIVALENCE")

    holds = sorted(set(holds))
    verdict = VisualQAVerdict.HOLD.value if holds else VisualQAVerdict.PASS.value
    approval_ready = verdict == VisualQAVerdict.PASS.value
    body = {
        "schema_version": QA_MODEL_VERSION,
        "engine_version": QA_ENGINE_VERSION,
        "asset_id": manifest.asset_id,
        "render_key": manifest.render_key,
        "platform": manifest.platform,
        "mode": manifest.mode,
        "bundle_id": manifest.bundle_id,
        "bundle_hash": manifest.bundle_hash,
        "adaptation_id": manifest.adaptation_id,
        "adaptation_hash": manifest.adaptation_hash,
        "svg_sha256": manifest.svg_sha256,
        "png_sha256": manifest.png_sha256,
        "width": manifest.width,
        "height": manifest.height,
        "integrity_status": "PASS_EXACT_BYTE_BINDING",
        "text_integrity_status": text_status,
        "svg_safety_status": "PASS_SELF_CONTAINED_INACTIVE",
        "png_status": "PASS_STATIC_DIMENSIONS",
        "rights_status": rights_status,
        "alt_text": alt_text,
        "alt_text_status": alt_status,
        "photo_relevance_status": relevance_status,
        "subject_safe_zone_status": safe_zone_status,
        "identity_equivalence_status": identity_status,
        "holds": tuple(holds),
        "verdict": verdict,
        "approval_input_ready": approval_ready,
        "state": "VISUAL_QA_ONLY",
        "visual_qa_authority": True,
        "queue_authority": False,
        "publish_authority": False,
        "publish_eligible": False,
        "network_fetch_performed": False,
        "real_account_connection_performed": False,
    }
    report_hash = _hash(body)
    return VisualQAReport(
        report_id="vqr_" + report_hash[:24],
        report_hash=report_hash,
        model_version=QA_MODEL_VERSION,
        engine_version=QA_ENGINE_VERSION,
        asset_id=manifest.asset_id,
        render_key=manifest.render_key,
        platform=manifest.platform,
        mode=manifest.mode,
        bundle_id=manifest.bundle_id,
        bundle_hash=manifest.bundle_hash,
        adaptation_id=manifest.adaptation_id,
        adaptation_hash=manifest.adaptation_hash,
        svg_sha256=manifest.svg_sha256,
        png_sha256=manifest.png_sha256,
        width=manifest.width,
        height=manifest.height,
        integrity_status="PASS_EXACT_BYTE_BINDING",
        text_integrity_status=text_status,
        svg_safety_status="PASS_SELF_CONTAINED_INACTIVE",
        png_status="PASS_STATIC_DIMENSIONS",
        rights_status=rights_status,
        alt_text=alt_text,
        alt_text_status=alt_status,
        photo_relevance_status=relevance_status,
        subject_safe_zone_status=safe_zone_status,
        identity_equivalence_status=identity_status,
        holds=tuple(holds),
        verdict=verdict,
        approval_input_ready=approval_ready,
    )
