from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re

from .control import EXPECTED_ACTIVE, canonical_json, sha256_file

IDENTITY_CONTRACT_VERSION = "PPOS_VISUAL_IDENTITY_V2"
IDENTITY_CHECKPOINT = "CP48"
IDENTITY_NAME = "EDITORIAL_LEDGER_V2"
SUPERSEDES_IDENTITY = "EDITORIAL_LEDGER_V1"
SUPERSEDES_CHECKPOINT = "CP29"
FONT_PROFILE_SCOPE = "EDITORIAL_LEDGER_V2_EXACT_LOCAL"
VISUAL_RENDER_SCHEMA_VERSION = "PPOS_VISUAL_RENDER_V1"

CANONICAL_FONT_ROWS = (
    {
        "role": "DISPLAY",
        "family": "Inter Display",
        "style": "SemiBold",
        "sha256": "991234562ac06b47aefa2ca4d4ff74360a164a5653ec05357816fc4ffe3ca8a2",
    },
    {
        "role": "EDITORIAL",
        "family": "Noto Serif",
        "style": "Regular",
        "sha256": "9d7583b7dc9e812afd32a14280c5cac3160012efe50c8d08938f4fea266ff67f",
    },
    {
        "role": "EDITORIAL_ITALIC",
        "family": "Noto Serif",
        "style": "Italic",
        "sha256": "bc25600aa27cd409e1e5b3d86340df3a329bb860fcfbe57a03a95070b229e1b0",
    },
    {
        "role": "MARGINALIA",
        "family": "Noto Sans Mono",
        "style": "Medium",
        "sha256": "c6107a9c14e9d33db347299fc467fb52c473919050d1be7c661869107eeffc06",
    },
)

CANONICAL_FONT_HASHES = {row["role"]: row["sha256"] for row in CANONICAL_FONT_ROWS}

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

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def expected_font_binding_hash() -> str:
    return _hash({
        "schema_version": VISUAL_RENDER_SCHEMA_VERSION,
        "profile_scope": FONT_PROFILE_SCOPE,
        "fonts": CANONICAL_FONT_ROWS,
    })


def expected_identity_profile_hash() -> str:
    return _hash({
        "identity_name": IDENTITY_NAME,
        "palette": PALETTE,
        "grid": GRID,
        "font_binding_hash": expected_font_binding_hash(),
        "marginalia_hooks": MARGINALIA_HOOKS,
        "microcopy_allowlist": PROCEDURAL_MICROCOPY,
        "corners": 0,
        "spacing": (8, 12, 16, 24, 32, 48, 64, 96),
        "strokes": (2, 4, 8),
    })


EXPECTED_FONT_BINDING_HASH = "a3edbdb93a494a9dcac436e3395be078d746a731c1fbb75caad7300d65c7d4af"
EXPECTED_IDENTITY_PROFILE_HASH = "8678c85bb7addc1c1d4ccabf9c6116c2a1f74a89c8146d240b877a9b86eb90bf"


def validate_contract(policy: dict, license_manifest: dict) -> tuple[str, ...]:
    errors: list[str] = []
    if expected_font_binding_hash() != EXPECTED_FONT_BINDING_HASH:
        errors.append("FONT_BINDING_DIGEST_CONSTANT_DRIFT")
    if expected_identity_profile_hash() != EXPECTED_IDENTITY_PROFILE_HASH:
        errors.append("IDENTITY_PROFILE_DIGEST_CONSTANT_DRIFT")
    if policy.get("checkpoint") != IDENTITY_CHECKPOINT:
        errors.append("POLICY_CHECKPOINT_MISMATCH")
    if policy.get("identity_name") != IDENTITY_NAME:
        errors.append("POLICY_IDENTITY_NAME_MISMATCH")
    if policy.get("supersedes", {}).get("identity_name") != SUPERSEDES_IDENTITY:
        errors.append("POLICY_SUPERSESSION_MISMATCH")
    if policy.get("supersedes", {}).get("checkpoint") != SUPERSEDES_CHECKPOINT:
        errors.append("POLICY_SUPERSESSION_CHECKPOINT_MISMATCH")
    if tuple(policy.get("active_platforms", ())) != tuple(EXPECTED_ACTIVE):
        errors.append("ACTIVE_PLATFORM_DRIFT")
    if policy.get("font_profile_scope") != FONT_PROFILE_SCOPE:
        errors.append("FONT_PROFILE_SCOPE_MISMATCH")
    if policy.get("expected_font_binding_hash") != EXPECTED_FONT_BINDING_HASH:
        errors.append("POLICY_FONT_BINDING_HASH_MISMATCH")
    if policy.get("expected_identity_profile_hash") != EXPECTED_IDENTITY_PROFILE_HASH:
        errors.append("POLICY_IDENTITY_PROFILE_HASH_MISMATCH")
    roles = policy.get("font_roles", {})
    for row in CANONICAL_FONT_ROWS:
        current = roles.get(row["role"], {})
        for key in ("family", "style", "sha256"):
            if current.get(key) != row[key]:
                errors.append(f"POLICY_FONT_{row['role']}_{key.upper()}_MISMATCH")
    if policy.get("historical_cp29_byte_equivalence_asserted") is not False:
        errors.append("HISTORICAL_EQUIVALENCE_MUST_BE_FALSE")
    if policy.get("font_bytes_packaged") is not False:
        errors.append("FONT_BYTES_MUST_NOT_BE_PACKAGED")
    if policy.get("activation_state") != "STAGED_FAIL_CLOSED_RUNTIME_ACTIVATION_REQUIRED":
        errors.append("ACTIVATION_STATE_MISMATCH")
    authority = policy.get("authority", {})
    for key in ("runtime_activation_authority", "queue_authority", "publish_authority", "network_fetch_allowed", "real_account_connection_allowed", "deploy_allowed"):
        if authority.get(key) is not False:
            errors.append(f"AUTHORITY_{key.upper()}_MUST_BE_FALSE")

    if license_manifest.get("checkpoint") != IDENTITY_CHECKPOINT:
        errors.append("LICENSE_CHECKPOINT_MISMATCH")
    license_rows = {row.get("role"): row for row in license_manifest.get("fonts", [])}
    if set(license_rows) != set(CANONICAL_FONT_HASHES):
        errors.append("LICENSE_ROLE_SET_MISMATCH")
    for row in CANONICAL_FONT_ROWS:
        lic = license_rows.get(row["role"], {})
        if lic.get("sha256") != row["sha256"]:
            errors.append(f"LICENSE_FONT_{row['role']}_HASH_MISMATCH")
        if lic.get("license_spdx") != "OFL-1.1":
            errors.append(f"LICENSE_FONT_{row['role']}_SPDX_MISMATCH")
        if not HEX64.fullmatch(str(lic.get("embedded_license_text_sha256", ""))):
            errors.append(f"LICENSE_FONT_{row['role']}_EVIDENCE_HASH_INVALID")
    if license_manifest.get("font_bytes_packaged") is not False:
        errors.append("LICENSE_MANIFEST_FONT_BYTES_MUST_NOT_BE_PACKAGED")
    return tuple(sorted(set(errors)))


def verify_local_font_paths(paths_by_role: dict[str, str | Path]) -> dict:
    if set(paths_by_role) != set(CANONICAL_FONT_HASHES):
        return {
            "checkpoint": IDENTITY_CHECKPOINT,
            "identity_name": IDENTITY_NAME,
            "state": "HOLD_FONT_ROLE_SET_MISMATCH",
            "verified": False,
            "rows": (),
        }
    rows = []
    for row in CANONICAL_FONT_ROWS:
        role = row["role"]
        path = Path(paths_by_role[role]).expanduser()
        if not path.is_file():
            return {
                "checkpoint": IDENTITY_CHECKPOINT,
                "identity_name": IDENTITY_NAME,
                "state": f"HOLD_FONT_FILE_MISSING_{role}",
                "verified": False,
                "rows": tuple(rows),
            }
        actual = sha256_file(path)
        rows.append({"role": role, "path": str(path), "sha256": actual})
        if actual != row["sha256"]:
            return {
                "checkpoint": IDENTITY_CHECKPOINT,
                "identity_name": IDENTITY_NAME,
                "state": f"HOLD_FONT_HASH_MISMATCH_{role}",
                "verified": False,
                "rows": tuple(rows),
            }
    return {
        "checkpoint": IDENTITY_CHECKPOINT,
        "identity_name": IDENTITY_NAME,
        "state": "PASS_CP48_EXACT_LOCAL_FONT_BINDING",
        "verified": True,
        "font_binding_hash": EXPECTED_FONT_BINDING_HASH,
        "identity_profile_hash": EXPECTED_IDENTITY_PROFILE_HASH,
        "rows": tuple(rows),
        "network_attempted": False,
        "account_connected": False,
        "publish_performed": False,
        "deploy_performed": False,
    }
