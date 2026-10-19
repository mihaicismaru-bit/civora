#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSS = ROOT / "web" / "assets" / "eucons.css"
DEFAULT_CONTRACT = ROOT / "web" / "jtbd_ux_contract.json"


class ValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rule_body(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css, flags=re.MULTILINE | re.DOTALL)
    require(match is not None, f"missing CSS rule for {selector}")
    return match.group(1)


def declaration(rule: str, name: str) -> str:
    match = re.search(r"(?:^|;)\s*" + re.escape(name) + r"\s*:\s*([^;]+)", rule)
    require(match is not None, f"missing {name} declaration")
    return match.group(1).strip()


def px_value(value: str, label: str) -> int:
    match = re.fullmatch(r"(\d+)px", value)
    require(match is not None, f"{label} must be an integer px value")
    return int(match.group(1))


def validate(css_path=DEFAULT_CSS, contract_path=DEFAULT_CONTRACT):
    css = Path(css_path).read_text(encoding="utf-8")
    contract = load_json(contract_path)
    acceptance = contract.get("accessibility_acceptance") or {}
    required_target = acceptance.get("minimum_touch_target_px")

    require(isinstance(required_target, int) and required_target >= 44, "canonical touch target must remain at least 44px")
    require(acceptance.get("mobile_single_column_actions") is True, "mobile actions must remain single-column")
    require(acceptance.get("reduced_motion_supported") is True, "reduced-motion support must remain enabled")

    checked_selectors = (".eu-wordmark", ".eu-nav a", ".eu-footer__links a")
    for selector in checked_selectors:
        body = rule_body(css, selector)
        min_height = px_value(declaration(body, "min-height"), f"{selector} min-height")
        require(min_height >= required_target, f"{selector} touch target is below the canonical minimum")
        require(declaration(body, "display") in {"inline-flex", "flex", "grid", "inline-grid"}, f"{selector} must expose a box-sized target")
        require(declaration(body, "align-items") == "center", f"{selector} target content must remain vertically centered")

    focus = rule_body(css, ":focus-visible")
    require("outline" in focus and "outline-offset" in focus, "keyboard focus indicator must remain visible")

    mobile_match = re.search(r"@media\s*\(max-width:\s*767px\)\s*\{(.*?)\n\}", css, flags=re.DOTALL)
    require(mobile_match is not None, "mobile breakpoint is missing")
    mobile_css = mobile_match.group(1)
    mobile_actions = rule_body(mobile_css, ".eu-actions .eu-button")
    require(declaration(mobile_actions, "flex") == "1 1 100%", "mobile primary actions must remain single-column/full-width")

    require("@media (prefers-reduced-motion: reduce)" in css, "reduced-motion media query is missing")
    reduced_match = re.search(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*)\}\s*$", css, flags=re.DOTALL)
    require(reduced_match is not None and "transition-duration" in reduced_match.group(1), "reduced-motion transition suppression is missing")

    return {
        "status": "PASS",
        "surface": "EUCONS_PUBLIC_NAVIGATION",
        "minimum_touch_target_px": required_target,
        "selectors_checked": list(checked_selectors),
        "keyboard_focus": "VISIBLE",
        "mobile_actions": "SINGLE_COLUMN",
        "reduced_motion": "SUPPORTED",
    }


def main():
    print(json.dumps(validate(), ensure_ascii=False))


if __name__ == "__main__":
    main()
