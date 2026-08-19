#!/usr/bin/env python3
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "web" / "design_system.json"
CSS_PATH = ROOT / "web" / "assets" / "eucons.css"
PREVIEW_PATH = ROOT / "web" / "design-system" / "index.html"


class DesignSystemError(ValueError):
    pass


def fail(message: str) -> None:
    raise DesignSystemError(message)


def load(path: Path):
    if not path.exists():
        fail(f"missing {path.relative_to(ROOT)}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path.relative_to(ROOT)}: {exc}")


def srgb_channel(value: int) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    if not isinstance(hex_color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", hex_color):
        fail(f"invalid color token {hex_color!r}")
    values = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    r, g, b = (srgb_channel(v) for v in values)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    a, b = luminance(foreground), luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def validate_design_system(design, css_text: str, preview_text: str):
    if design.get("product") != "EUCONS_COMMERCIAL_OS" or design.get("phase") != "E07":
        fail("wrong product or phase")
    if design.get("status") != "CANONICAL":
        fail("status must be CANONICAL")

    principles = set(design.get("principles") or [])
    required_principles = {
        "commercial_clarity_before_decoration",
        "evidence_first_presentation",
        "mobile_first",
        "accessible_by_default",
        "provider_independent_assets",
        "no_external_font_runtime_dependency",
    }
    if not required_principles.issubset(principles):
        fail("design principles missing commercial/evidence/mobile/accessibility/independence rules")

    tokens = design.get("tokens") or {}
    colors = tokens.get("color") or {}
    required_colors = {
        "ink", "ink_soft", "muted", "navy", "brand", "brand_strong", "success", "warning",
        "danger", "background", "surface", "surface_subtle", "border", "focus"
    }
    if set(colors) != required_colors:
        fail("color token set differs from canonical E07 palette")
    for value in colors.values():
        luminance(value)

    font = tokens.get("font") or {}
    if font.get("body_min_px", 0) < 16:
        fail("body font size must be at least 16px")
    if font.get("body_line_height", 0) < 1.5:
        fail("body line height must be at least 1.5")
    if font.get("measure_ch", 999) > 75:
        fail("reading measure must not exceed 75ch")
    if "system-ui" not in str(font.get("sans", "")):
        fail("font stack must include system-ui fallback")

    layout = tokens.get("layout") or {}
    if not (960 <= layout.get("content_max_px", 0) <= 1440):
        fail("content max width outside commercial layout guardrail")
    if layout.get("gutter_mobile_px", 0) < 16:
        fail("mobile gutter must be at least 16px")
    if layout.get("reading_max_ch", 999) > 75:
        fail("layout reading measure must not exceed 75ch")

    interaction = tokens.get("interaction") or {}
    if interaction.get("min_touch_target_px", 0) < 44:
        fail("touch targets must be at least 44px")
    if interaction.get("focus_ring_px", 0) < 2:
        fail("focus ring must be at least 2px")
    if interaction.get("focus_offset_px", 0) < 2:
        fail("focus offset must be at least 2px")
    if interaction.get("reduced_motion_supported") is not True:
        fail("reduced motion support must be enabled")

    breakpoints = design.get("responsive_breakpoints_px") or {}
    required_breakpoints = ["sm", "md", "lg", "xl"]
    if list(breakpoints) != required_breakpoints:
        fail("responsive breakpoints must be ordered sm/md/lg/xl")
    values = [breakpoints[key] for key in required_breakpoints]
    if not all(isinstance(value, int) for value in values) or not values == sorted(values) or len(set(values)) != len(values):
        fail("responsive breakpoints must be strictly increasing integers")
    if breakpoints["md"] != 768:
        fail("md breakpoint must remain aligned with canonical mobile navigation transition")

    pairs = design.get("required_contrast_pairs") or []
    if len(pairs) < 8:
        fail("insufficient contrast pair coverage")
    for pair in pairs:
        foreground = pair.get("foreground")
        background = pair.get("background")
        minimum = pair.get("minimum")
        if foreground not in colors or background not in colors:
            fail(f"contrast pair references unknown token: {foreground}/{background}")
        if not isinstance(minimum, (int, float)) or minimum < 4.5:
            fail(f"contrast pair {foreground}/{background} minimum below WCAG AA")
        actual = contrast_ratio(colors[foreground], colors[background])
        if actual + 1e-9 < minimum:
            fail(f"contrast pair {foreground}/{background} fails: {actual:.2f} < {minimum:.2f}")

    components = design.get("components") or {}
    required_components = {"button", "link", "card", "form_control", "badge", "alert", "header", "footer"}
    if set(components) != required_components:
        fail("component family set must exactly match canonical E07 contract")

    button = components["button"]
    if button.get("minimum_height_px", 0) < 44:
        fail("button minimum height must be at least 44px")
    for state in ("focus-visible", "disabled", "loading"):
        if state not in (button.get("states") or []):
            fail(f"button missing {state} state")

    link = components["link"]
    if link.get("underline_or_noncolor_cue_required") is not True or "focus-visible" not in (link.get("states") or []):
        fail("links require focus-visible and a non-color cue")

    card = components["card"]
    required_card_variants = {"service", "opportunity", "person", "case", "knowledge", "metric"}
    if set(card.get("variants") or []) != required_card_variants:
        fail("card variants must cover service/opportunity/person/case/knowledge/metric")
    if card.get("clickable_card_requires_single_primary_link") is not True:
        fail("clickable cards must enforce a single primary link")

    form = components["form_control"]
    if set(form.get("types") or []) != {"input", "textarea", "select", "checkbox", "radio"}:
        fail("form control type coverage incomplete")
    if form.get("visible_label_required") is not True or form.get("error_message_id_required") is not True:
        fail("forms require visible labels and addressable error messages")
    if "invalid" not in (form.get("states") or []):
        fail("form controls require invalid state")

    badge = components["badge"]
    if badge.get("color_only_meaning_forbidden") is not True:
        fail("badge meaning cannot rely on color alone")

    if components["alert"].get("semantic_role_required") is not True:
        fail("alerts require a semantic role")
    if components["header"].get("skip_link_required") is not True:
        fail("header requires skip link")
    if components["header"].get("desktop_navigation") is not True or components["header"].get("mobile_navigation") is not True:
        fail("header must support desktop and mobile navigation")
    if components["footer"].get("legal_links_required") is not True:
        fail("footer must support legal links")

    presentation = design.get("content_presentation") or {}
    if presentation.get("unverified_claim_visualization") != "OMIT":
        fail("unverified claims must be omitted")
    if presentation.get("hold_people_visualization") != "OMIT":
        fail("HOLD people must be omitted")
    if presentation.get("hold_cases_visualization") != "OMIT":
        fail("HOLD cases must be omitted")
    for key in (
        "opportunity_maturity_label_required",
        "service_primary_cta_required",
        "evidence_source_area_supported",
        "numbers_without_claim_reference_forbidden",
    ):
        if presentation.get(key) is not True:
            fail(f"content_presentation.{key} must be true")

    asset = design.get("asset_policy") or {}
    for key in ("remote_font_urls_forbidden", "remote_css_urls_forbidden", "invented_real_person_portraits_forbidden"):
        if asset.get(key) is not True:
            fail(f"asset_policy.{key} must be true")
    if asset.get("logo_source_state") != "PENDING_VERIFIED_ASSET":
        fail("logo source must remain pending until a verified asset is available")
    if asset.get("logo_fallback") != "EUROCONSULT_WORDMARK_TEXT":
        fail("logo fallback must be the canonical text wordmark")

    css_lower = css_text.lower()
    for forbidden in ("@import", "wp-content", "wp-json", "chatgpt-sites", "fonts.googleapis", "http://", "https://"):
        if forbidden in css_lower:
            fail(f"CSS contains forbidden runtime dependency marker: {forbidden}")
    for marker in (
        ":focus-visible", "min-height: 44px", ".eu-button", ".eu-card", ".eu-form", ".eu-badge",
        ".eu-alert", ".eu-header", ".eu-footer", "@media (max-width: 767px)",
        "@media (min-width: 768px)", "@media (prefers-reduced-motion: reduce)"
    ):
        if marker not in css_text:
            fail(f"CSS missing canonical marker {marker}")

    for marker in (
        'name="robots" content="noindex,nofollow"', 'class="eu-skip-link"', "<header", "<nav",
        'id="main-content"', "<main", "<footer", "eu-button--primary", "eu-card",
        "eu-badge", "eu-form", 'aria-invalid="true"', 'role="alert"',
        'rel="stylesheet" href="../assets/eucons.css"'
    ):
        if marker not in preview_text:
            fail(f"preview missing semantic/component marker {marker}")
    for forbidden in ("wp-content", "wp-json", "chatgpt-sites"):
        if forbidden in preview_text.lower():
            fail(f"preview contains forbidden dependency marker: {forbidden}")

    return {
        "contrast_pairs": len(pairs),
        "component_families": len(components),
        "card_variants": len(card["variants"]),
        "breakpoints": len(breakpoints),
    }


def main():
    try:
        result = validate_design_system(
            load(DESIGN_PATH),
            CSS_PATH.read_text(encoding="utf-8"),
            PREVIEW_PATH.read_text(encoding="utf-8"),
        )
    except (DesignSystemError, OSError) as exc:
        raise SystemExit(f"EUCONS E07 design system validation failed: {exc}")
    print(
        "EUCONS E07 design system valid: "
        f"{result['contrast_pairs']} contrast pairs, {result['component_families']} component families, "
        f"{result['card_variants']} commercial card variants, {result['breakpoints']} breakpoints"
    )


if __name__ == "__main__":
    main()
