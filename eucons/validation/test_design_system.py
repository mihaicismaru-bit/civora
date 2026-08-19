#!/usr/bin/env python3
import copy
import json
from pathlib import Path

from validate_design_system import DesignSystemError, validate_design_system

ROOT = Path(__file__).resolve().parents[1]
DESIGN = json.loads((ROOT / "web" / "design_system.json").read_text(encoding="utf-8"))
CSS = (ROOT / "web" / "assets" / "eucons.css").read_text(encoding="utf-8")
PREVIEW = (ROOT / "web" / "design-system" / "index.html").read_text(encoding="utf-8")


def expect_failure(name, design=DESIGN, css=CSS, preview=PREVIEW, contains=""):
    try:
        validate_design_system(design, css, preview)
    except DesignSystemError as exc:
        if contains and contains not in str(exc):
            raise SystemExit(f"{name}: wrong failure: {exc}")
        return
    raise SystemExit(f"{name}: invalid design system unexpectedly passed")


def main():
    result = validate_design_system(DESIGN, CSS, PREVIEW)
    if result["card_variants"] != 6:
        raise SystemExit("canonical card variant count drift")

    low_contrast = copy.deepcopy(DESIGN)
    low_contrast["tokens"]["color"]["muted"] = "#B0B0B0"
    expect_failure("low contrast", design=low_contrast, contains="contrast pair muted/surface fails")

    tiny_touch = copy.deepcopy(DESIGN)
    tiny_touch["tokens"]["interaction"]["min_touch_target_px"] = 32
    expect_failure("tiny touch target", design=tiny_touch, contains="touch targets must be at least 44px")

    missing_case = copy.deepcopy(DESIGN)
    missing_case["components"]["card"]["variants"].remove("case")
    expect_failure("missing case card", design=missing_case, contains="card variants must cover")

    visible_unverified = copy.deepcopy(DESIGN)
    visible_unverified["content_presentation"]["unverified_claim_visualization"] = "SHOW"
    expect_failure("unverified claim leak", design=visible_unverified, contains="unverified claims must be omitted")

    visible_hold_person = copy.deepcopy(DESIGN)
    visible_hold_person["content_presentation"]["hold_people_visualization"] = "SHOW"
    expect_failure("HOLD person leak", design=visible_hold_person, contains="HOLD people must be omitted")

    numeric_marketing = copy.deepcopy(DESIGN)
    numeric_marketing["content_presentation"]["numbers_without_claim_reference_forbidden"] = False
    expect_failure("number without claim reference", design=numeric_marketing, contains="numbers_without_claim_reference_forbidden")

    invented_portraits = copy.deepcopy(DESIGN)
    invented_portraits["asset_policy"]["invented_real_person_portraits_forbidden"] = False
    expect_failure("invented portraits", design=invented_portraits, contains="invented_real_person_portraits_forbidden")

    remote_css = CSS + "\n@import url('https://example.invalid/theme.css');\n"
    expect_failure("remote runtime CSS", css=remote_css, contains="forbidden runtime dependency marker")

    no_focus = CSS.replace(":focus-visible", ":focus-never")
    expect_failure("focus visibility drift", css=no_focus, contains="CSS missing canonical marker :focus-visible")

    no_reduced_motion = CSS.replace("@media (prefers-reduced-motion: reduce)", "@media (prefers-reduced-motion: no-preference)")
    expect_failure("reduced motion drift", css=no_reduced_motion, contains="CSS missing canonical marker @media (prefers-reduced-motion: reduce)")

    indexed_preview = PREVIEW.replace('content="noindex,nofollow"', 'content="index,follow"')
    expect_failure("indexed development preview", preview=indexed_preview, contains="preview missing semantic/component marker")

    print("EUCONS E07 design regressions valid: contrast, touch targets, card coverage, claim/HOLD omission, proof references, portrait safety, runtime independence, focus, reduced motion and preview indexing are fail-closed")


if __name__ == "__main__":
    main()
