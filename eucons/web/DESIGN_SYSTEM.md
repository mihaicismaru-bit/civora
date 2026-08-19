# EUCONS Design System — E07

## Role

This is the canonical visual and interaction contract for EUCONS Commercial OS. It is provider-independent and must remain usable on the GitHub preview and any future production host without a Sites or WordPress runtime dependency.

## Direction

Euroconsult is presented as a calm, rigorous consultancy: commercial clarity before decoration, institutional trust without bureaucratic visual weight, evidence before claims, and an obvious next action. The interface must not resemble a news portal, generic theme, or speculative startup dashboard.

## Fail-closed presentation

- Unverified claims are omitted.
- People or case records in `HOLD` are omitted.
- Funding opportunity maturity must be visible before a commercial CTA is shown.
- Numeric proof must reference a verified claim; otherwise the value stays withheld.
- Missing verified portraits never trigger an invented real-person image.
- The verified logo asset is currently pending, so the canonical fallback is the text wordmark `EUROCONSULT`.

## Accessibility

The implementation targets WCAG 2.2 AA behavior: minimum 44px interactive targets, visible keyboard focus, semantic alerts, visible form labels, addressable error messages, mobile navigation, a skip link, and reduced-motion support.

## Canonical artifacts

- `web/design_system.json` — tokens, component families, responsive rules, content-presentation and asset policy.
- `web/assets/eucons.css` — local provider-neutral CSS implementation.
- `web/design-system/index.html` — noindex semantic component showcase with synthetic content only.
- `validation/validate_design_system.py` — acceptance validator.
- `validation/test_design_system.py` — fail-closed regressions.

## Acceptance

E07 closes only when `EUCONS Quality` validates contrast, component coverage, accessibility states, fail-closed content presentation, asset safety, provider independence and the noindex design preview.
