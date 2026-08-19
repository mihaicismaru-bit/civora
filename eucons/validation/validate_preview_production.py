#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    builder = load_module("e25_builder", EUCONS / "web" / "build_public_site.py")
    preview = load_module("e25_preview", EUCONS / "preview" / "preview_engine.py")
    contract = json.loads((EUCONS / "preview" / "preview_contract.json").read_text(encoding="utf-8"))

    if contract["engine_id"] != "EUCONS_E25_PREVIEW_PRODUCTION":
        raise SystemExit("E25 engine id drift")
    if contract["hosting_mode"] != "GITHUB_ACTIONS_ARTIFACT_LOCAL_HTTP_SMOKE":
        raise SystemExit("E25 must remain GitHub Actions artifact preview, not production hosting")
    if contract["production_deployment_enabled"] is not False or contract["external_credentials_required"] is not False:
        raise SystemExit("E25 activated production deployment or credentials prematurely")
    if not all(contract["forbidden"].values()):
        raise SystemExit("E25 forbidden-state contract incomplete")

    with tempfile.TemporaryDirectory() as td:
        build_dir = Path(td) / "site"
        pages = builder.build_site(build_dir)
        receipt = preview.build_preview_receipt(build_dir, contract)

        if receipt["static"]["route_count"] != len(pages) or len(pages) < 26:
            raise SystemExit("E25 complete route build mismatch")
        if receipt["http"]["probe_count"] != len(pages) + 3 or receipt["http"]["all_http_200"] is not True:
            raise SystemExit("E25 local HTTP smoke coverage mismatch")
        if len(receipt["static"]["route_hashes"]) != len(pages):
            raise SystemExit("E25 route hash manifest incomplete")
        if set(receipt["static"]["route_hashes"]) != set(pages):
            raise SystemExit("E25 route hash manifest route mismatch")
        for value in list(receipt["static"]["route_hashes"].values()) + [
            receipt["static"]["sitemap_sha256"], receipt["static"]["robots_sha256"], receipt["static"]["css_sha256"],
            receipt["commercial_journey_sha256"], receipt["distribution_journey_sha256"], receipt["receipt_hash"],
        ]:
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise SystemExit("E25 receipt/hash manifest contains invalid SHA-256")

        commercial = receipt["commercial"]
        if commercial["match_state"] != "MATCH_CANDIDATE" or commercial["crm_stage"] != "OFFER":
            raise SystemExit("E25 lead -> match -> CRM -> offer journey incomplete")
        if commercial["pricing_state"] != "HUMAN_REQUIRED" or commercial["automatic_send_allowed"] is not False:
            raise SystemExit("E25 offer pricing/send gate failed open")

        distribution = receipt["distribution"]
        if distribution["editorial_ready"] < 1:
            raise SystemExit("E25 editorial dry-run produced no READY content")
        if distribution["linkedin_items"] < 1 or distribution["facebook_items"] < 1:
            raise SystemExit("E25 social dry-run outboxes are empty")
        if distribution["linkedin_items"] != distribution["facebook_items"]:
            raise SystemExit("E25 social dry-run coverage mismatch")
        if distribution["email_decision"] != "READY" or distribution["email_dispatch_state"] != "EMAIL_OUTBOX_READY_MAILBOX_AUTH_REQUIRED":
            raise SystemExit("E25 email dry-run authorization gate mismatch")

        if receipt["production_deployment_enabled"] is not False or receipt["external_credentials_used"] is not False:
            raise SystemExit("E25 receipt falsely claims production activation")
        serialized = json.dumps(receipt, ensure_ascii=False).lower()
        if "example.invalid" in serialized or "synthetic preview person" in serialized:
            raise SystemExit("E25 receipt leaked synthetic PII instead of hashes")
        body = {key: value for key, value in receipt.items() if key != "receipt_hash"}
        if receipt["receipt_hash"] != preview.digest_json(body):
            raise SystemExit("E25 immutable receipt digest mismatch")

        if not (build_dir / "robots.txt").is_file() or not (build_dir / "sitemap.xml").is_file():
            raise SystemExit("E25 preview SEO support files missing")
        if "Disallow: /" not in (build_dir / "robots.txt").read_text(encoding="utf-8"):
            raise SystemExit("E25 preview robots failed open to indexing")

    print(json.dumps({
        "status": "PASS",
        "phase": "E25",
        "routes": receipt["static"]["route_count"],
        "http_probes": receipt["http"]["probe_count"],
        "commercial_journey": "PASS",
        "social_email_dry_run": "PASS",
        "production_deployment": "DISABLED",
        "external_credentials": "NOT_USED"
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
