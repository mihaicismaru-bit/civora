#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "validation" / "validate_mobile_navigation_accessibility.py"
CSS_PATH = ROOT / "web" / "assets" / "eucons.css"
CONTRACT_PATH = ROOT / "web" / "jtbd_ux_contract.json"


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_mobile_navigation_accessibility", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def expect_failure(validator, css: str, label: str):
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "eucons.css"
        path.write_text(css, encoding="utf-8")
        try:
            validator.validate(path, CONTRACT_PATH)
        except validator.ValidationError:
            return
        raise AssertionError(f"fail-closed regression accepted: {label}")


def main():
    validator = load_validator()
    canonical = CSS_PATH.read_text(encoding="utf-8")
    validator.validate(CSS_PATH, CONTRACT_PATH)

    broken = canonical.replace(
        ".eu-wordmark {\n  min-height: 44px;",
        ".eu-wordmark {\n  min-height: 32px;",
        1,
    )
    expect_failure(validator, broken, "undersized wordmark target")

    broken = canonical.replace(
        ".eu-nav a {\n  min-height: 44px;",
        ".eu-nav a {\n  min-height: 36px;",
        1,
    )
    expect_failure(validator, broken, "undersized primary navigation target")

    broken = canonical.replace(
        ".eu-footer__links a {\n  min-height: 44px;",
        ".eu-footer__links a {\n  min-height: 40px;",
        1,
    )
    expect_failure(validator, broken, "undersized footer navigation target")

    broken = canonical.replace(":focus-visible {", ":focus-hidden {", 1)
    expect_failure(validator, broken, "keyboard focus indicator removed")

    broken = canonical.replace(
        ".eu-actions .eu-button { flex: 1 1 100%; }",
        ".eu-actions .eu-button { flex: 0 1 auto; }",
        1,
    )
    expect_failure(validator, broken, "mobile actions no longer full width")

    broken = canonical.replace(
        "@media (prefers-reduced-motion: reduce)",
        "@media (prefers-reduced-motion: no-preference)",
        1,
    )
    expect_failure(validator, broken, "reduced-motion support removed")

    print('{"status":"PASS","surface":"EUCONS_PUBLIC_NAVIGATION","negative_cases":6}')


if __name__ == "__main__":
    main()
