from __future__ import annotations

import json
from pathlib import Path
import re

from public_presence_os.control import EXPECTED_ACTIVE
from public_presence_os.identity_v2 import (
    CANONICAL_FONT_HASHES,
    EXPECTED_FONT_BINDING_HASH,
    EXPECTED_IDENTITY_PROFILE_HASH,
    IDENTITY_NAME,
    expected_font_binding_hash,
    expected_identity_profile_hash,
    validate_contract,
    verify_local_font_paths,
)

ROOT = Path(__file__).resolve().parents[1]
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def load(name: str) -> dict:
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def test_cp48_contract_and_license_manifest_cross_validate():
    policy = load("visual_identity_v2_policy.json")
    licenses = load("font_license_manifest.json")
    assert validate_contract(policy, licenses) == ()
    assert policy["identity_name"] == IDENTITY_NAME == "EDITORIAL_LEDGER_V2"
    assert tuple(policy["active_platforms"]) == tuple(EXPECTED_ACTIVE)
    assert policy["decision_state"] == "CANONICAL_SUPERSESSION_ACCEPTED"
    assert policy["activation_state"] == "STAGED_FAIL_CLOSED_RUNTIME_ACTIVATION_REQUIRED"
    assert policy["historical_cp29_byte_equivalence_asserted"] is False


def test_cp48_exact_digests_are_deterministic_and_non_null():
    assert expected_font_binding_hash() == EXPECTED_FONT_BINDING_HASH
    assert expected_identity_profile_hash() == EXPECTED_IDENTITY_PROFILE_HASH
    assert HEX64.fullmatch(EXPECTED_FONT_BINDING_HASH)
    assert HEX64.fullmatch(EXPECTED_IDENTITY_PROFILE_HASH)
    assert set(CANONICAL_FONT_HASHES) == {"DISPLAY", "EDITORIAL", "EDITORIAL_ITALIC", "MARGINALIA"}
    assert all(HEX64.fullmatch(value) for value in CANONICAL_FONT_HASHES.values())


def test_cp48_font_licences_are_ofl_and_bound_to_exact_bytes():
    policy = load("visual_identity_v2_policy.json")
    licenses = load("font_license_manifest.json")
    by_role = {row["role"]: row for row in licenses["fonts"]}
    for role, digest in CANONICAL_FONT_HASHES.items():
        assert policy["font_roles"][role]["sha256"] == digest
        assert policy["font_roles"][role]["license_spdx"] == "OFL-1.1"
        assert by_role[role]["sha256"] == digest
        assert by_role[role]["license_spdx"] == "OFL-1.1"
        assert HEX64.fullmatch(by_role[role]["embedded_license_text_sha256"])
    assert licenses["font_bytes_packaged"] is False
    assert licenses["runtime_network_required"] is False


def test_cp48_repo_does_not_package_font_bytes():
    font_suffixes = {".ttf", ".otf", ".woff", ".woff2", ".eot"}
    packaged = [p for p in ROOT.rglob("*") if p.is_file() and p.suffix.lower() in font_suffixes]
    assert packaged == []


def test_cp48_local_verifier_fails_closed_on_wrong_bytes(tmp_path):
    paths = {}
    for role in CANONICAL_FONT_HASHES:
        p = tmp_path / f"{role.lower()}.font-fixture"
        p.write_bytes(("wrong-" + role).encode("utf-8"))
        paths[role] = p
    result = verify_local_font_paths(paths)
    assert result["verified"] is False
    assert result["state"].startswith("HOLD_FONT_HASH_MISMATCH_")


def test_cp48_has_no_runtime_publish_or_network_authority():
    policy = load("visual_identity_v2_policy.json")
    authority = policy["authority"]
    assert authority["identity_contract_authority"] is True
    for key in (
        "runtime_activation_authority",
        "queue_authority",
        "publish_authority",
        "network_fetch_allowed",
        "real_account_connection_allowed",
        "deploy_allowed",
    ):
        assert authority[key] is False
