#!/usr/bin/env python3
"""Apply PARTENER.EU MIPE immutable-runtime cleanup on a development branch.

This migration is fail-closed: it edits only exact expected workflow fragments,
retire the redundant Access Bridge, proves no executable callers remain for the
five active source patchers, and only then removes those patchers. Canonical
hosted publication remains routed through mipe_direct_only_ingest.py.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()
SOURCE = ROOT / "partener-eu/ingest/mipe_resilient_ingest.py"
CANONICAL_SOURCE_SHA = "ad82649456a2aced555ffd43ae768ab275e4b02fb6a32acd6e152097280e500b"

VALIDATION = ROOT / ".github/workflows/partener-eu-validation.yml"
DUAL_RELAY = ROOT / ".github/workflows/partener-eu-mipe-dual-relay.yml"
ACCESS_BRIDGE = ROOT / ".github/workflows/partener-eu-mipe-access-bridge.yml"
CANONICAL_INGEST = ROOT / ".github/workflows/partener-eu-mipe-ingest.yml"
OUT = ROOT / "partener-eu/ops/mipe_immutable_runtime_cleanup.json"

FIXERS = (
    "partener-eu/ops/fix_mipe_resilient_classifier.py",
    "partener-eu/ops/fix_mipe_resilient_runtime.py",
    "partener-eu/ops/fix_mipe_content_quality.py",
    "partener-eu/ops/fix_mipe_first_party_relay.py",
    "partener-eu/ops/fix_mipe_dual_relay.py",
)

MIGRATION_ONLY = (
    "partener-eu/ops/audit_mipe_fixer_idempotence.py",
    "partener-eu/ops/materialize_mipe_fixer_state.py",
    "partener-eu/ops/audit_mipe_workflow_chain_equivalence.py",
    ".github/workflows/partener-eu-mipe-fixer-idempotence.yml",
    ".github/workflows/partener-eu-mipe-fixer-materialize.yml",
)

TEXT_CODE_SUFFIXES = {".py", ".yml", ".yaml", ".sh", ".ps1"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".next", "dist", "build"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def executable_references(names: tuple[str, ...]) -> list[dict]:
    refs: list[dict] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.resolve() == SELF:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_CODE_SUFFIXES:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in FIXERS:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            hits = [name for name in names if Path(name).name in line]
            if hits:
                refs.append({"path": rel, "line": number, "fixers": hits, "excerpt": line.strip()[:240]})
    return refs


def main() -> int:
    source_sha = sha(SOURCE)
    if source_sha != CANONICAL_SOURCE_SHA:
        raise SystemExit(f"materialized source hash mismatch: {source_sha}")

    canonical_text = CANONICAL_INGEST.read_text(encoding="utf-8")
    if "run: python partener-eu/ingest/mipe_direct_only_ingest.py" not in canonical_text:
        raise SystemExit("canonical hosted MIPE workflow is not routed through direct-only wrapper")
    for token in ("forbidden_transport_markers", "CANONICAL_DUAL_RELAY_CORROBORATED", "T1_DUAL_RELAY_CORROBORATED"):
        if token not in canonical_text:
            raise SystemExit(f"canonical direct-only provenance guard missing: {token}")

    before = {
        "validation": sha(VALIDATION),
        "dualRelay": sha(DUAL_RELAY),
        "accessBridge": sha(ACCESS_BRIDGE),
    }

    replace_once(
        VALIDATION,
        "          python partener-eu/ops/fix_mipe_resilient_classifier.py\n",
        "",
        "remove validation classifier patcher",
    )
    replace_once(
        VALIDATION,
        "            partener-eu/ingest/mipe_resilient_ingest.py \\\n",
        "",
        "stop validation from persisting source code",
    )

    patch_block = """      - name: Assemble ephemeral diagnostic runtime\n        run: |\n          python partener-eu/ops/fix_mipe_resilient_classifier.py\n          python partener-eu/ops/fix_mipe_resilient_runtime.py\n          python partener-eu/ops/fix_mipe_content_quality.py\n          python partener-eu/ops/fix_mipe_first_party_relay.py\n          python partener-eu/ops/fix_mipe_dual_relay.py\n\n"""
    replace_once(DUAL_RELAY, patch_block, "", "remove dual-relay runtime patch chain")
    replace_once(
        DUAL_RELAY,
        "      - name: Syntax and parser regression\n",
        "      - name: Validate immutable diagnostic runtime\n",
        "rename immutable dual-relay validation step",
    )

    if not ACCESS_BRIDGE.exists():
        raise SystemExit("Access Bridge already absent; refusing ambiguous cleanup")
    ACCESS_BRIDGE.unlink()

    for rel in MIGRATION_ONLY:
        path = ROOT / rel
        if not path.exists():
            raise SystemExit(f"expected phase-6 migration file missing: {rel}")
        path.unlink()

    refs = executable_references(FIXERS)
    if refs:
        OUT.write_text(json.dumps({
            "schema": "PARTENER_MIPE_IMMUTABLE_RUNTIME_CLEANUP_V1",
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "FAIL",
            "reason": "fixer_callers_remain",
            "references": refs,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(f"fixer callers remain: {refs}")

    removed_fixers = []
    for rel in FIXERS:
        path = ROOT / rel
        if not path.exists():
            raise SystemExit(f"expected active fixer missing: {rel}")
        path.unlink()
        removed_fixers.append(rel)

    validation_text = VALIDATION.read_text(encoding="utf-8")
    dual_text = DUAL_RELAY.read_text(encoding="utf-8")
    if "fix_mipe_resilient_classifier.py" in validation_text:
        raise SystemExit("validation still invokes MIPE source patcher")
    if "partener-eu/ingest/mipe_resilient_ingest.py \\" in validation_text:
        raise SystemExit("validation still persists MIPE source code")
    if "fix_mipe_" in dual_text:
        raise SystemExit("dual-relay diagnostic still invokes MIPE source patcher")
    if "workflow_dispatch:" not in dual_text or "permissions:\n  contents: read" not in dual_text:
        raise SystemExit("dual-relay diagnostic manual/read-only contract changed")

    payload = {
        "schema": "PARTENER_MIPE_IMMUTABLE_RUNTIME_CLEANUP_V1",
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS",
        "sourceSha256": source_sha,
        "canonicalHostedDirectOnlyGuardVerified": True,
        "accessBridgeRetired": True,
        "validationSourceMutationRemoved": True,
        "dualRelaySourceMutationRemoved": True,
        "remainingExecutableFixerReferencesBeforeDeletion": refs,
        "removedFixers": removed_fixers,
        "removedMigrationOnlyFiles": list(MIGRATION_ONLY),
        "beforeSha256": before,
        "afterSha256": {
            "validation": sha(VALIDATION),
            "dualRelay": sha(DUAL_RELAY),
        },
        "rollback": "Restore deleted/edited files from the parent commit; no state/feed facts are changed by this migration.",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
