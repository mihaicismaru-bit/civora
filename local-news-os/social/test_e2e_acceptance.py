#!/usr/bin/env python3
"""Acceptance assertions for the end-to-end LOCAL NEWS OS social runtime harness."""
from __future__ import annotations

from pathlib import Path

import e2e_acceptance as harness


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    report = harness.run_acceptance(repo_root)

    checks = [
        (report["status"] == "PASS", "harness status"),
        (report["website_sibling"]["independent_publication"] is True, "website sibling independence"),
        (len(report["social_publications"]) == 3, "three social publications"),
        (report["distinctness"]["distinct_hook_count"] == 3, "channel-native hooks"),
        (set(report["distinctness"]["native_formats"]) == {"single_photo", "carousel", "short"}, "native formats"),
        (report["distinctness"]["distinct_publication_state_count"] == 3, "independent publication state"),
        (all(item["provenance_complete"] and item["reuse_rights_complete"] for item in report["social_publications"].values()), "visual provenance and rights"),
        (all(item["publication_status"] == "PUBLISHED" for item in report["social_publications"].values()), "confirmed fixture publications"),
        (all(item["learning_status"] == "READY" and item["learning_samples"] == 3 for item in report["social_publications"].values()), "observed learning"),
        (report["correction_propagation"]["native_action_count"] == 3, "correction propagation"),
        (report["multi_instance_isolation"]["positive_status"] == "PASS", "positive instance isolation"),
        (report["multi_instance_isolation"]["negative_collision_probe_status"] == "BLOCKED", "negative isolation probe"),
        (report["guards"]["zero_paid_dependency"] is True, "zero paid dependency"),
        (report["guards"]["credential_values_exposed"] is False, "no credential values"),
        (report["guards"]["network_calls_performed"] is False, "offline deterministic harness"),
    ]
    failed = [label for ok, label in checks if not ok]
    if failed:
        raise SystemExit("E2E acceptance failed: " + ", ".join(failed))
    print(f"Social runtime E2E acceptance: PASS ({len(checks)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
