from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from io import BytesIO
import base64
import html
import json
import platform as py_platform
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from .control import EXPECTED_ACTIVE, canonical_json, sha256_bytes, sha256_file
from .native_adapt import (
    NATIVE_ADAPT_MODEL_VERSION,
    NativeAdaptation,
    NativeAdaptationBundle,
    NativeAdaptationStatus,
)
from .rights import RIGHTS_BOUND_VISUAL_INPUT_VERSION, RightsBoundVisualInput

try:
    from PIL import Image, ImageDraw, ImageFont, __version__ as PILLOW_VERSION
except Exception:  # pragma: no cover - import error is reported fail-closed at render time
    Image = ImageDraw = ImageFont = None
    PILLOW_VERSION = None

VISUAL_MODEL_VERSION = "PPOS_VISUAL_RENDER_V1"
RENDERER_VERSION = "ppos-visual-v1.0.0"
IDENTITY_NAME = "EDITORIAL_LEDGER_V1"

PALETTE = {
    "paper": "#F4F0E8",
    "ink": "#171717",
    "muted_ink": "#62605B",
    "signal": "#B33A2B",
    "note_blue": "#2F5D8A",
    "rule": "#A79F93",
    "photo_matte": "#E3DDD2",
}

GRID = {
    "outer_margin": 0.06,
    "text_inset": 0.10,
    "marginalia_rail_width": 0.08,
    "photo_subject_inset": 0.06,
    "caption_band_max_height": 0.22,
}

CANVAS = {
    "FACEBOOK_PAGE": (1080, 1080),
    "INSTAGRAM_PROFESSIONAL": (1080, 1350),
    "THREADS": (1080, 1350),
}

MARGINALIA_HOOKS = (
    "RAIL_RULE",
    "FOLIO_MARK",
    "SOURCE_TICK",
    "ANNOTATION_BRACKET",
    "SOURCE_LABEL",
    "UPDATE_MARK",
)

PROCEDURAL_MICROCOPY = (
    "SURSA",
    "CONTEXT",
    "DE URMARIT",
    "CE NU STIM",
    "DETALIU",
    "DOCUMENT",
    "CIFRA",
    "LOC",
    "DATA",
    "UPDATE",
)

FONT_ROLE_CONTRACT = {
    "DISPLAY": ("Inter Display", "SemiBold"),
    "EDITORIAL": ("Noto Serif", "Regular"),
    "EDITORIAL_ITALIC": ("Noto Serif", "Italic"),
    "MARGINALIA": ("Noto Sans Mono", "Medium"),
}

MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_DECODED_PIXELS = 40_000_000
SUPPORTED_PHOTO_FORMATS = {"PNG", "JPEG", "WEBP"}


class VisualError(ValueError):
    pass


class VisualHold(VisualError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class FontBinding:
    role: str
    family: str
    style: str
    path: str
    expected_sha256: str

    def verified(self) -> dict:
        role = self.role.upper()
        if role not in FONT_ROLE_CONTRACT:
            raise VisualHold("HOLD_FONT_ROLE_UNKNOWN")
        p = Path(self.path)
        if not p.is_file():
            raise VisualHold("HOLD_FONT_FILE_MISSING")
        actual = sha256_file(p)
        if actual != self.expected_sha256:
            raise VisualHold("HOLD_FONT_HASH_MISMATCH")
        return {
            "role": role,
            "family": self.family,
            "style": self.style,
            "sha256": actual,
        }


@dataclass(frozen=True)
class FontBindingSet:
    display: FontBinding
    editorial: FontBinding
    editorial_italic: FontBinding
    marginalia: FontBinding
    profile_scope: str = "LOCAL_HASH_BOUND_PREVIEW"

    def verified_rows(self) -> tuple[dict, ...]:
        rows = tuple(binding.verified() for binding in (
            self.display,
            self.editorial,
            self.editorial_italic,
            self.marginalia,
        ))
        roles = tuple(row["role"] for row in rows)
        if roles != ("DISPLAY", "EDITORIAL", "EDITORIAL_ITALIC", "MARGINALIA"):
            raise VisualHold("HOLD_FONT_ROLE_ORDER_INVALID")
        return rows

    @property
    def binding_hash(self) -> str:
        rows = self.verified_rows()
        return _hash({
            "schema_version": VISUAL_MODEL_VERSION,
            "profile_scope": self.profile_scope,
            "fonts": rows,
        })

    def canonical_identity_equivalent(self, expected_hashes: dict[str, str | None]) -> bool:
        rows = self.verified_rows()
        for row in rows:
            expected = expected_hashes.get(row["role"])
            if not expected or expected != row["sha256"]:
                return False
            family, style = FONT_ROLE_CONTRACT[row["role"]]
            if row["family"] != family or row["style"] != style:
                return False
        return True


@dataclass(frozen=True)
class VisualAssetManifest:
    asset_id: str
    render_key: str
    model_version: str
    renderer_version: str
    renderer_env_hash: str
    identity_name: str
    identity_profile_hash: str
    canonical_identity_equivalent: bool
    font_binding_hash: str
    platform: str
    mode: str
    width: int
    height: int
    bundle_id: str
    bundle_hash: str
    adaptation_id: str
    adaptation_hash: str
    source_url: str
    displayed_text_sha256: str | None
    rights_binding_id: str | None
    rights_binding_hash: str | None
    source_media_sha256: str | None
    source_media_normalized_sha256: str | None
    svg_sha256: str
    png_sha256: str
    svg_size: int
    png_size: int
    alt_text_status: str
    subject_safe_zone_status: str
    state: str
    visual_qa_input_ready: bool
    publish_eligible: bool = False
    queue_authority: bool = False
    publish_authority: bool = False
    network_fetch_performed: bool = False
    real_account_connection_performed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RenderedVisual:
    manifest: VisualAssetManifest
    svg_bytes: bytes
    png_bytes: bytes


@dataclass(frozen=True)
class VisualRenderRequest:
    bundle: NativeAdaptationBundle
    platform: str
    mode: str
    fonts: FontBindingSet
    rights_input: RightsBoundVisualInput | None = None
    source_media: bytes | None = None
    expected_canonical_font_hashes: dict[str, str | None] | None = None



def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()



def _color(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))



def _adaptation_body(item: NativeAdaptation) -> dict:
    return {
        "schema_version": NATIVE_ADAPT_MODEL_VERSION,
        "brief_id": None,  # filled by bundle validation
        "brief_hash": None,
        "platform": item.platform,
        "status": item.status,
        "text": item.text,
        "char_count": item.char_count,
        "house_max_chars": item.house_max_chars,
        "content_surface": item.content_surface,
        "visual_requirement": item.visual_requirement,
        "source_url": item.source_url,
        "evidence_ids": item.evidence_ids,
        "support_kinds": item.support_kinds,
        "unknowns": item.unknowns,
        "constraints": item.constraints,
        "adaptation_ready": item.adaptation_ready,
        "api_write_allowed": False,
        "queue_authority": False,
        "publish_authority": False,
        "network_fetch_performed": False,
        "real_account_connection_performed": False,
    }



def _validate_bundle(bundle: NativeAdaptationBundle) -> None:
    if not isinstance(bundle, NativeAdaptationBundle):
        raise VisualHold("HOLD_M05_BUNDLE_TYPE")
    if bundle.model_version != NATIVE_ADAPT_MODEL_VERSION:
        raise VisualHold("HOLD_M05_MODEL_VERSION")
    if tuple(bundle.active_platforms) != tuple(EXPECTED_ACTIVE):
        raise VisualHold("HOLD_ACTIVE_PLATFORM_DRIFT")
    if bundle.state != "NATIVE_ADAPTATION_ONLY" or not bundle.native_adaptation_authority:
        raise VisualHold("HOLD_M05_AUTHORITY_INVALID")
    if bundle.fact_authority or bundle.visual_authority or bundle.queue_authority or bundle.publish_authority:
        raise VisualHold("HOLD_M05_FORBIDDEN_AUTHORITY")
    if bundle.network_fetch_performed or bundle.real_account_connection_performed:
        raise VisualHold("HOLD_M05_EXTERNAL_SIDE_EFFECT")
    body = {
        "schema_version": NATIVE_ADAPT_MODEL_VERSION,
        "brief_id": bundle.brief_id,
        "brief_hash": bundle.brief_hash,
        "source_url": bundle.source_url,
        "source_class": bundle.source_class,
        "topic": bundle.topic,
        "locality": bundle.locality,
        "adaptations": [item.to_dict() for item in bundle.adaptations],
        "unknowns": bundle.unknowns,
        "status": bundle.status,
        "rights_input_ready": bundle.rights_input_ready,
        "active_platforms": tuple(EXPECTED_ACTIVE),
        "state": "NATIVE_ADAPTATION_ONLY",
        "native_adaptation_authority": True,
        "fact_authority": False,
        "visual_authority": False,
        "queue_authority": False,
        "publish_authority": False,
        "network_fetch_performed": False,
        "real_account_connection_performed": False,
    }
    if _hash(body) != bundle.bundle_hash:
        raise VisualHold("HOLD_M05_BUNDLE_HASH_MISMATCH")
    for item in bundle.adaptations:
        raw = _adaptation_body(item)
        raw["brief_id"] = bundle.brief_id
        raw["brief_hash"] = bundle.brief_hash
        if _hash(raw) != item.adaptation_hash:
            raise VisualHold("HOLD_M05_ADAPTATION_HASH_MISMATCH")



def _select_adaptation(bundle: NativeAdaptationBundle, platform: str) -> NativeAdaptation:
    if platform not in EXPECTED_ACTIVE:
        raise VisualHold("HOLD_PLATFORM_NOT_ACTIVE")
    rows = [item for item in bundle.adaptations if item.platform == platform]
    if len(rows) != 1:
        raise VisualHold("HOLD_M05_PLATFORM_CARDINALITY")
    item = rows[0]
    if item.status != NativeAdaptationStatus.READY.value or not item.adaptation_ready:
        raise VisualHold("HOLD_M05_ADAPTATION_NOT_READY")
    return item



def _validate_rights_binding(binding: RightsBoundVisualInput, platform: str) -> None:
    if not isinstance(binding, RightsBoundVisualInput):
        raise VisualHold("HOLD_M13_BINDING_TYPE")
    if binding.model_version != RIGHTS_BOUND_VISUAL_INPUT_VERSION:
        raise VisualHold("HOLD_M13_MODEL_VERSION")
    if binding.state != "RIGHTS_BOUND_VISUAL_INPUT_ONLY" or not binding.visual_render_input_authority:
        raise VisualHold("HOLD_M13_AUTHORITY_INVALID")
    if binding.story_fit_authority or binding.queue_authority or binding.publish_authority or binding.publish_eligible:
        raise VisualHold("HOLD_M13_FORBIDDEN_AUTHORITY")
    if binding.network_fetch_performed or binding.real_account_connection_performed:
        raise VisualHold("HOLD_M13_EXTERNAL_SIDE_EFFECT")
    if binding.platform != platform or binding.purpose != "SOCIAL_EDITORIAL":
        raise VisualHold("HOLD_M13_USAGE_MISMATCH")
    body = {
        "schema_version": RIGHTS_BOUND_VISUAL_INPUT_VERSION,
        "asset_sha256": binding.asset_sha256,
        "root_original_id": binding.root_original_id,
        "original_sha256": binding.original_sha256,
        "provenance_hash": binding.provenance_hash,
        "source_revision_id": binding.source_revision_id,
        "source_hash": binding.source_hash,
        "source_url": binding.source_url,
        "creator_name": binding.creator_name,
        "media_class": binding.media_class,
        "rights_record_id": binding.rights_record_id,
        "rights_record_hash": binding.rights_record_hash,
        "rights_status": binding.rights_status,
        "evidence_set_hash": binding.evidence_set_hash,
        "eligibility_hash": binding.eligibility_hash,
        "platform": binding.platform,
        "purpose": binding.purpose,
        "territory": binding.territory,
        "attribution_required": binding.attribution_required,
        "attribution_text": binding.attribution_text,
        "license_name": binding.license_name,
        "license_version": binding.license_version,
        "license_url": binding.license_url,
        "state": "RIGHTS_BOUND_VISUAL_INPUT_ONLY",
        "visual_render_input_authority": True,
        "story_fit_authority": False,
        "queue_authority": False,
        "publish_authority": False,
        "publish_eligible": False,
        "network_fetch_performed": False,
        "real_account_connection_performed": False,
    }
    if _hash(body) != binding.binding_hash:
        raise VisualHold("HOLD_M13_BINDING_HASH_MISMATCH")



def _identity_profile_hash(fonts: FontBindingSet) -> str:
    return _hash({
        "identity_name": IDENTITY_NAME,
        "palette": PALETTE,
        "grid": GRID,
        "font_binding_hash": fonts.binding_hash,
        "marginalia_hooks": MARGINALIA_HOOKS,
        "microcopy_allowlist": PROCEDURAL_MICROCOPY,
        "corners": 0,
        "spacing": (8, 12, 16, 24, 32, 48, 64, 96),
        "strokes": (2, 4, 8),
    })



def _renderer_env_hash(fonts: FontBindingSet) -> str:
    if PILLOW_VERSION is None:
        raise VisualHold("HOLD_PILLOW_NOT_AVAILABLE")
    return _hash({
        "renderer_version": RENDERER_VERSION,
        "python": py_platform.python_version(),
        "implementation": py_platform.python_implementation(),
        "pillow": PILLOW_VERSION,
        "font_binding_hash": fonts.binding_hash,
    })



def _title_from_adaptation(item: NativeAdaptation) -> str:
    for line in item.text.splitlines():
        clean = line.strip()
        if clean:
            return clean
    raise VisualHold("HOLD_DISPLAY_TEXT_EMPTY")



def _safe_source_label(source_url: str) -> str:
    host = (urlparse(source_url).hostname or "").lower()
    if not host:
        raise VisualHold("HOLD_SOURCE_URL_INVALID")
    return host



def _font(binding: FontBinding, size: int):
    if ImageFont is None:
        raise VisualHold("HOLD_PILLOW_NOT_AVAILABLE")
    binding.verified()
    return ImageFont.truetype(binding.path, size=size)



def _wrap(draw, text: str, font, max_width: int, max_lines: int) -> tuple[str, ...]:
    words = text.split()
    if not words:
        raise VisualHold("HOLD_DISPLAY_TEXT_EMPTY")
    lines: list[str] = []
    current = words[0]
    if draw.textlength(current, font=font) > max_width:
        raise VisualHold("HOLD_GEOMETRY_UNBREAKABLE_TOKEN")
    for word in words[1:]:
        candidate = current + " " + word
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
            if draw.textlength(current, font=font) > max_width:
                raise VisualHold("HOLD_GEOMETRY_UNBREAKABLE_TOKEN")
    lines.append(current)
    if len(lines) > max_lines:
        raise VisualHold("HOLD_GEOMETRY_TEXT_OVERFLOW")
    return tuple(lines)



def _text_geometry(width: int, height: int) -> dict:
    outer = round(width * GRID["outer_margin"])
    rail = round(width * GRID["marginalia_rail_width"])
    left = round(width * GRID["text_inset"]) + rail
    right = width - round(width * GRID["text_inset"])
    top = round(height * 0.18)
    bottom = height - round(height * 0.16)
    return {"outer": outer, "rail": rail, "left": left, "right": right, "top": top, "bottom": bottom}



def _draw_marginalia(draw, width: int, height: int, fonts: FontBindingSet, folio: str) -> None:
    outer = round(width * GRID["outer_margin"])
    rail_x = outer + round(width * GRID["marginalia_rail_width"] * 0.45)
    draw.line((rail_x, outer, rail_x, height - outer), fill=_color(PALETTE["rule"]), width=2)
    draw.line((rail_x - 14, round(height * 0.18), rail_x + 14, round(height * 0.18)), fill=_color(PALETTE["signal"]), width=4)
    micro = _font(fonts.marginalia, 22 if width <= 1080 else 24)
    draw.text((outer, height - outer - 28), folio, font=micro, fill=_color(PALETTE["muted_ink"]))
    draw.text((outer, outer), "SURSA", font=micro, fill=_color(PALETTE["note_blue"]))



def _svg_text_card(width: int, height: int, title: str, source_host: str, fonts: FontBindingSet, lines: tuple[str, ...], folio: str) -> bytes:
    g = _text_geometry(width, height)
    family = html.escape(fonts.display.family, quote=True)
    mono = html.escape(fonts.marginalia.family, quote=True)
    y = g["top"]
    line_gap = 88 if height <= 1080 else 94
    tspans = "".join(
        f'<tspan x="{g["left"]}" y="{y + i * line_gap}">{html.escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    outer = g["outer"]
    rail_x = outer + round(width * GRID["marginalia_rail_width"] * 0.45)
    source = html.escape(source_host)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="{PALETTE["paper"]}"/>'
        f'<line x1="{rail_x}" y1="{outer}" x2="{rail_x}" y2="{height-outer}" stroke="{PALETTE["rule"]}" stroke-width="2"/>'
        f'<line x1="{rail_x-14}" y1="{round(height*0.18)}" x2="{rail_x+14}" y2="{round(height*0.18)}" stroke="{PALETTE["signal"]}" stroke-width="4"/>'
        f'<text x="{outer}" y="{outer+22}" font-family="{mono}" font-size="22" fill="{PALETTE["note_blue"]}">SURSA</text>'
        f'<text x="{g["left"]}" y="{g["top"]}" font-family="{family}" font-size="72" font-weight="600" fill="{PALETTE["ink"]}">{tspans}</text>'
        f'<text x="{g["left"]}" y="{height-outer-34}" font-family="{mono}" font-size="20" fill="{PALETTE["muted_ink"]}">{source}</text>'
        f'<text x="{outer}" y="{height-outer}" font-family="{mono}" font-size="20" fill="{PALETTE["muted_ink"]}">{html.escape(folio)}</text>'
        '</svg>'
    )
    return svg.encode("utf-8")



def _render_text_card(item: NativeAdaptation, fonts: FontBindingSet) -> tuple[bytes, bytes, str, str | None]:
    if Image is None or ImageDraw is None:
        raise VisualHold("HOLD_PILLOW_NOT_AVAILABLE")
    width, height = CANVAS[item.platform]
    title = _title_from_adaptation(item)
    source_host = _safe_source_label(item.source_url)
    image = Image.new("RGB", (width, height), _color(PALETTE["paper"]))
    draw = ImageDraw.Draw(image)
    display = _font(fonts.display, 72 if height <= 1080 else 76)
    g = _text_geometry(width, height)
    lines = _wrap(draw, title, display, g["right"] - g["left"], 6 if height <= 1080 else 7)
    _draw_marginalia(draw, width, height, fonts, "FOLIO " + item.adaptation_id[:6].upper())
    y = g["top"]
    line_gap = 88 if height <= 1080 else 94
    for idx, line in enumerate(lines):
        draw.text((g["left"], y + idx * line_gap), line, font=display, fill=_color(PALETTE["ink"]))
    micro = _font(fonts.marginalia, 20)
    draw.text((g["left"], height - g["outer"] - 34), source_host, font=micro, fill=_color(PALETTE["muted_ink"]))
    if y + len(lines) * line_gap > g["bottom"]:
        raise VisualHold("HOLD_GEOMETRY_TEXT_OVERFLOW")
    out = BytesIO()
    image.save(out, format="PNG", compress_level=9, optimize=False)
    png = out.getvalue()
    svg = _svg_text_card(width, height, title, source_host, fonts, lines, "FOLIO " + item.adaptation_id[:6].upper())
    return svg, png, sha256_bytes(title.encode("utf-8")), None



def _normalized_photo(source_media: bytes, binding: RightsBoundVisualInput) -> tuple[Image.Image, bytes]:
    if Image is None:
        raise VisualHold("HOLD_PILLOW_NOT_AVAILABLE")
    if not source_media or len(source_media) > MAX_SOURCE_BYTES:
        raise VisualHold("HOLD_SOURCE_MEDIA_SIZE")
    if sha256_bytes(source_media) != binding.asset_sha256:
        raise VisualHold("HOLD_SOURCE_MEDIA_HASH_MISMATCH")
    try:
        with Image.open(BytesIO(source_media)) as probe:
            fmt = (probe.format or "").upper()
            if fmt not in SUPPORTED_PHOTO_FORMATS:
                raise VisualHold("HOLD_SOURCE_MEDIA_FORMAT")
            width, height = probe.size
            if width <= 0 or height <= 0 or width * height > MAX_DECODED_PIXELS:
                raise VisualHold("HOLD_SOURCE_MEDIA_PIXEL_CAP")
            probe.load()
            normalized = probe.convert("RGB")
    except VisualHold:
        raise
    except Exception as exc:
        raise VisualHold("HOLD_SOURCE_MEDIA_DECODE") from exc
    out = BytesIO()
    normalized.save(out, format="PNG", compress_level=9, optimize=False)
    return normalized, out.getvalue()



def _fit_crop(image: Image.Image, target_w: int, target_h: int) -> Image.Image:
    ratio = max(target_w / image.width, target_h / image.height)
    w, h = round(image.width * ratio), round(image.height * ratio)
    resized = image.resize((w, h), Image.Resampling.LANCZOS)
    left = max(0, (w - target_w) // 2)
    top = max(0, (h - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))



def _render_photo_frame(item: NativeAdaptation, fonts: FontBindingSet, binding: RightsBoundVisualInput, source_media: bytes) -> tuple[bytes, bytes, None, str]:
    width, height = CANVAS[item.platform]
    normalized, normalized_png = _normalized_photo(source_media, binding)
    outer = round(width * GRID["outer_margin"])
    rail = round(width * GRID["marginalia_rail_width"])
    left = outer + rail + 24
    right = width - outer
    top = outer
    caption_h = min(round(height * 0.16), round(height * GRID["caption_band_max_height"]))
    bottom = height - outer - caption_h
    frame_w, frame_h = right - left, bottom - top
    if frame_w <= 0 or frame_h <= 0:
        raise VisualHold("HOLD_GEOMETRY_INVALID")
    crop = _fit_crop(normalized, frame_w, frame_h)
    image = Image.new("RGB", (width, height), _color(PALETTE["paper"]))
    image.paste(crop, (left, top))
    draw = ImageDraw.Draw(image)
    _draw_marginalia(draw, width, height, fonts, "FOLIO " + item.adaptation_id[:6].upper())
    micro = _font(fonts.marginalia, 20)
    if binding.attribution_required:
        credit = (binding.attribution_text or "").strip()
        if not credit:
            raise VisualHold("HOLD_ATTRIBUTION_TEXT_MISSING")
        if draw.textlength(credit, font=micro) > frame_w:
            raise VisualHold("HOLD_ATTRIBUTION_OVERFLOW")
        draw.text((left, bottom + 32), credit, font=micro, fill=_color(PALETTE["muted_ink"]))
    out = BytesIO()
    image.save(out, format="PNG", compress_level=9, optimize=False)
    png = out.getvalue()
    embedded = base64.b64encode(crop_to_png(crop)).decode("ascii")
    family = html.escape(fonts.marginalia.family, quote=True)
    credit_svg = ""
    if binding.attribution_required:
        credit_svg = (
            f'<text x="{left}" y="{bottom+52}" font-family="{family}" font-size="20" fill="{PALETTE["muted_ink"]}">'
            f'{html.escape((binding.attribution_text or "").strip())}</text>'
        )
    rail_x = outer + round(width * GRID["marginalia_rail_width"] * 0.45)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="{PALETTE["paper"]}"/>'
        f'<image x="{left}" y="{top}" width="{frame_w}" height="{frame_h}" href="data:image/png;base64,{embedded}"/>'
        f'<line x1="{rail_x}" y1="{outer}" x2="{rail_x}" y2="{height-outer}" stroke="{PALETTE["rule"]}" stroke-width="2"/>'
        f'<line x1="{rail_x-14}" y1="{round(height*0.18)}" x2="{rail_x+14}" y2="{round(height*0.18)}" stroke="{PALETTE["signal"]}" stroke-width="4"/>'
        f'<text x="{outer}" y="{outer+22}" font-family="{family}" font-size="22" fill="{PALETTE["note_blue"]}">SURSA</text>'
        f'{credit_svg}'
        f'<text x="{outer}" y="{height-outer}" font-family="{family}" font-size="20" fill="{PALETTE["muted_ink"]}">FOLIO {item.adaptation_id[:6].upper()}</text>'
        '</svg>'
    ).encode("utf-8")
    return svg, png, None, sha256_bytes(normalized_png)



def crop_to_png(image: Image.Image) -> bytes:
    out = BytesIO()
    image.save(out, format="PNG", compress_level=9, optimize=False)
    return out.getvalue()



def render_visual(request: VisualRenderRequest) -> RenderedVisual:
    _validate_bundle(request.bundle)
    item = _select_adaptation(request.bundle, request.platform)
    if request.mode not in {"TEXT_CARD", "PHOTO_FRAME"}:
        raise VisualHold("HOLD_VISUAL_MODE_UNSUPPORTED")
    fonts = request.fonts
    fonts.verified_rows()
    expected = request.expected_canonical_font_hashes or {}
    canonical_equivalent = fonts.canonical_identity_equivalent(expected) if expected else False
    identity_hash = _identity_profile_hash(fonts)
    env_hash = _renderer_env_hash(fonts)

    binding = request.rights_input
    normalized_sha = None
    if request.mode == "TEXT_CARD":
        if binding is not None or request.source_media is not None:
            raise VisualHold("HOLD_TEXT_CARD_MUST_NOT_CONSUME_PHOTO")
        svg, png, displayed_sha, normalized_sha = _render_text_card(item, fonts)
        rights_id = rights_hash = source_sha = None
        subject_state = "NOT_APPLICABLE"
    else:
        if binding is None or request.source_media is None:
            raise VisualHold("HOLD_PHOTO_FRAME_REQUIRES_M13_AND_BYTES")
        _validate_rights_binding(binding, request.platform)
        svg, png, displayed_sha, normalized_sha = _render_photo_frame(item, fonts, binding, request.source_media)
        rights_id = binding.binding_id
        rights_hash = binding.binding_hash
        source_sha = binding.asset_sha256
        subject_state = "PENDING_VISUAL_QA"

    render_key = _hash({
        "renderer_version": RENDERER_VERSION,
        "model_version": VISUAL_MODEL_VERSION,
        "bundle_hash": request.bundle.bundle_hash,
        "adaptation_hash": item.adaptation_hash,
        "platform": request.platform,
        "mode": request.mode,
        "identity_profile_hash": identity_hash,
        "renderer_env_hash": env_hash,
        "rights_binding_hash": rights_hash,
        "source_media_sha256": source_sha,
    })
    asset_id = "ma_" + render_key[:24]
    svg_hash = sha256_bytes(svg)
    png_hash = sha256_bytes(png)
    width, height = CANVAS[request.platform]
    manifest = VisualAssetManifest(
        asset_id=asset_id,
        render_key=render_key,
        model_version=VISUAL_MODEL_VERSION,
        renderer_version=RENDERER_VERSION,
        renderer_env_hash=env_hash,
        identity_name=IDENTITY_NAME,
        identity_profile_hash=identity_hash,
        canonical_identity_equivalent=canonical_equivalent,
        font_binding_hash=fonts.binding_hash,
        platform=request.platform,
        mode=request.mode,
        width=width,
        height=height,
        bundle_id=request.bundle.bundle_id,
        bundle_hash=request.bundle.bundle_hash,
        adaptation_id=item.adaptation_id,
        adaptation_hash=item.adaptation_hash,
        source_url=item.source_url,
        displayed_text_sha256=displayed_sha,
        rights_binding_id=rights_id,
        rights_binding_hash=rights_hash,
        source_media_sha256=source_sha,
        source_media_normalized_sha256=normalized_sha,
        svg_sha256=svg_hash,
        png_sha256=png_hash,
        svg_size=len(svg),
        png_size=len(png),
        alt_text_status="REQUIRED_AFTER_RENDER",
        subject_safe_zone_status=subject_state,
        state="MEDIA_PREVIEW_READY",
        visual_qa_input_ready=True,
    )
    return RenderedVisual(manifest=manifest, svg_bytes=svg, png_bytes=png)



def write_rendered_visual(output_dir: str | Path, rendered: RenderedVisual) -> tuple[Path, Path, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    aid = rendered.manifest.asset_id
    svg_path = root / f"{aid}.svg"
    png_path = root / f"{aid}.png"
    manifest_path = root / f"{aid}.manifest.json"
    manifest_bytes = (json.dumps(rendered.manifest.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    targets = (
        (svg_path, rendered.svg_bytes),
        (png_path, rendered.png_bytes),
        (manifest_path, manifest_bytes),
    )
    for path, payload in targets:
        if path.exists():
            if path.read_bytes() != payload:
                raise VisualHold("HOLD_DETERMINISTIC_PATH_CONFLICT")
        else:
            path.write_bytes(payload)
    return svg_path, png_path, manifest_path



def validate_svg_self_contained(svg_bytes: bytes) -> None:
    text = svg_bytes.decode("utf-8")
    lowered = text.lower()
    for forbidden in ("<script", "<iframe", "<foreignobject", "http://", "https://", "file://"):
        if forbidden in lowered:
            if forbidden == "http://" and 'xmlns="http://www.w3.org/2000/svg"' in lowered:
                lowered = lowered.replace('xmlns="http://www.w3.org/2000/svg"', "")
                continue
            raise VisualHold("HOLD_SVG_EXTERNAL_OR_ACTIVE_CONTENT")
    if "<svg" not in text or "</svg>" not in text:
        raise VisualHold("HOLD_SVG_INVALID")



def render_batch(requests: Iterable[VisualRenderRequest]) -> tuple[RenderedVisual, ...]:
    by_key: dict[str, RenderedVisual] = {}
    for request in tuple(requests):
        rendered = render_visual(request)
        by_key.setdefault(rendered.manifest.render_key, rendered)
    return tuple(sorted(by_key.values(), key=lambda item: (item.manifest.platform, item.manifest.mode, item.manifest.asset_id)))
