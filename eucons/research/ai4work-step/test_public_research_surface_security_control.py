from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from public_research_surface_security_control import (
    PublicSurfaceSecurityError,
    evaluate,
    validate_header_set,
)

HERE = Path(__file__).resolve().parent


def good_test_twin_headers() -> dict[str, str]:
    return {
        "Content-Security-Policy": (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
            "connect-src https://api.eucons.ro; form-action 'none'; base-uri 'none'; "
            "object-src 'none'; frame-ancestors 'none'; frame-src 'none'; worker-src 'none'; "
            "manifest-src 'none'; media-src 'none'"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cache-Control": "no-store, max-age=0",
    }


class PublicResearchSurfaceSecurityControlTests(unittest.TestCase):
    def test_current_repository_binding_is_fail_closed_not_prod_evidence(self) -> None:
        result = evaluate()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["state"], "DRAFT_FAIL_CLOSED")
        self.assertEqual(result["classification"], "CONTROL_ONLY_NOT_EVIDENCE")
        self.assertFalse(result["production_enabled"])
        self.assertFalse(result["live_provider_readback_verified"])
        self.assertFalse(result["test_twin_evidence_eligible"])

    def test_production_flag_cannot_bypass_missing_live_provider_readback(self) -> None:
        contract = json.loads((HERE / "form_contract.json").read_text(encoding="utf-8"))
        binding = json.loads(
            (HERE / "PUBLIC_RESEARCH_SURFACE_SECURITY_BINDING_DRAFT.json").read_text(encoding="utf-8")
        )
        contract["production_enabled"] = True
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "contract.json"
            binding_path = root / "binding.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            binding_path.write_text(json.dumps(binding), encoding="utf-8")
            with self.assertRaises(PublicSurfaceSecurityError):
                evaluate(contract_path=contract_path, binding_path=binding_path)

    def test_header_policy_accepts_only_strict_test_twin_mechanics(self) -> None:
        # Synthetic mechanics only. This dictionary is TEST TWIN / NON-EVIDENCE
        # and never satisfies the live-provider readback gate.
        validate_header_set(good_test_twin_headers())

    def test_missing_frame_ancestors_fails_closed(self) -> None:
        headers = good_test_twin_headers()
        headers["Content-Security-Policy"] = headers["Content-Security-Policy"].replace(
            "frame-ancestors 'none'; ", ""
        )
        with self.assertRaises(PublicSurfaceSecurityError):
            validate_header_set(headers)

    def test_unsafe_csp_token_fails_closed(self) -> None:
        headers = good_test_twin_headers()
        headers["Content-Security-Policy"] += "; script-src 'self' 'unsafe-inline'"
        with self.assertRaises(PublicSurfaceSecurityError):
            validate_header_set(headers)

    def test_test_twin_can_never_satisfy_live_readback(self) -> None:
        contract = json.loads((HERE / "form_contract.json").read_text(encoding="utf-8"))
        binding = json.loads(
            (HERE / "PUBLIC_RESEARCH_SURFACE_SECURITY_BINDING_DRAFT.json").read_text(encoding="utf-8")
        )
        binding["test_twin"]["can_satisfy_live_readback"] = True
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "contract.json"
            binding_path = root / "binding.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            binding_path.write_text(json.dumps(binding), encoding="utf-8")
            with self.assertRaises(PublicSurfaceSecurityError):
                evaluate(contract_path=contract_path, binding_path=binding_path)


if __name__ == "__main__":
    unittest.main()
