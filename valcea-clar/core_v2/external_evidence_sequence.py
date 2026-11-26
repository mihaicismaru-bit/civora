from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SEQUENCE_SCHEMA = "core-v2-external-evidence-sequence.v1"
PUBLICATION_AUTHORITY = "NONE"
AUDIT_INPUT_NAMES = (
    "candidate_ledger",
    "site_readback",
    "visual_provenance_readback",
    "meta_readback",
    "instagram_visual_identity",
    "bound_transactions",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"external_evidence_output_missing:{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"external_evidence_output_invalid_json:{path}:{exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"external_evidence_output_not_object:{path}")
    if value.get("publication_authority") not in {None, PUBLICATION_AUTHORITY}:
        raise RuntimeError(f"external_evidence_publication_authority_violation:{path}")
    if value.get("acceptance_ready") is True:
        raise RuntimeError(f"external_evidence_acceptance_escalation_violation:{path}")
    return value


def _run(repo_root: Path, argv: list[str]) -> None:
    completed = subprocess.run(
        argv,
        cwd=repo_root,
        env=os.environ.copy(),
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "external_evidence_subprocess_failed:"
            + Path(argv[1]).name
            + f":exit_{completed.returncode}"
        )


def _contract_fields(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != SEQUENCE_SCHEMA:
        raise RuntimeError("external_evidence_manifest_schema_drift")
    if manifest.get("mode") != "SHADOW_READ_ONLY":
        raise RuntimeError("external_evidence_manifest_mode_drift")
    if manifest.get("publication_authority") != PUBLICATION_AUTHORITY:
        raise RuntimeError("external_evidence_manifest_publication_authority_violation")
    if manifest.get("acceptance_ready") is not False:
        raise RuntimeError("external_evidence_manifest_acceptance_boundary_violation")
    if manifest.get("production_write_authority") is not False:
        raise RuntimeError("external_evidence_manifest_write_authority_violation")
    if manifest.get("external_auditor_inserted") is not False:
        raise RuntimeError("external_evidence_manifest_auditor_boundary_violation")
    if manifest.get("audit_input_names") != list(AUDIT_INPUT_NAMES):
        raise RuntimeError("external_evidence_manifest_input_order_drift")
    if int(manifest.get("audit_input_count") or -1) != len(AUDIT_INPUT_NAMES):
        raise RuntimeError("external_evidence_manifest_input_count_drift")


def _validate_manifest_files(manifest: dict[str, Any]) -> None:
    _contract_fields(manifest)
    outputs = manifest.get("audit_inputs")
    if not isinstance(outputs, dict) or set(outputs) != set(AUDIT_INPUT_NAMES):
        raise RuntimeError("external_evidence_manifest_input_map_drift")
    for name in AUDIT_INPUT_NAMES:
        row = outputs.get(name)
        if not isinstance(row, dict):
            raise RuntimeError(f"external_evidence_manifest_input_row_missing:{name}")
        snapshot = Path(str(row.get("snapshot_path") or ""))
        expected_sha = str(row.get("sha256") or "")
        if not snapshot.is_file():
            raise RuntimeError(f"external_evidence_snapshot_missing:{name}")
        if not expected_sha or _sha256(snapshot) != expected_sha:
            raise RuntimeError(f"external_evidence_snapshot_hash_mismatch:{name}")
        _read_json_object(snapshot)


def _run_fail_closed_regressions(manifest: dict[str, Any]) -> int:
    cases: list[dict[str, Any]] = []

    case = copy.deepcopy(manifest)
    case["publication_authority"] = "PUBLISH"
    cases.append(case)

    case = copy.deepcopy(manifest)
    case["external_auditor_inserted"] = True
    cases.append(case)

    case = copy.deepcopy(manifest)
    case["audit_input_names"] = list(reversed(AUDIT_INPUT_NAMES))
    cases.append(case)

    case = copy.deepcopy(manifest)
    case["audit_input_count"] = 5
    cases.append(case)

    case = copy.deepcopy(manifest)
    first = case["audit_inputs"][AUDIT_INPUT_NAMES[0]]
    first["sha256"] = "0" * 64
    cases.append(case)

    passed = 0
    for index, candidate in enumerate(cases, 1):
        rejected = False
        try:
            _validate_manifest_files(candidate)
        except RuntimeError:
            rejected = True
        if not rejected:
            raise RuntimeError(f"external_evidence_fail_closed_regression_not_rejected:{index}")
        passed += 1
    return passed


def run_sequence(
    *,
    repo_root: Path,
    workdir: Path,
    limit: int = 10,
    manifest_output: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    workdir = workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = workdir / "valcea-core-v2-shadow-site" / "external-evidence"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    core = repo_root / "valcea-clar" / "core_v2"
    outputs = {
        "candidate_ledger": workdir / "valcea-core-v2-shadow-candidates.json",
        "site_readback": workdir / "valcea-core-v2-site-readback.json",
        "visual_provenance_readback": workdir / "valcea-core-v2-visual-readback.json",
        "meta_readback": workdir / "valcea-core-v2-meta-readback.json",
        "instagram_visual_identity": workdir / "valcea-core-v2-instagram-visual-identity.json",
        "bound_transactions": workdir / "valcea-core-v2-shadow-transactions.json",
    }
    receipts = workdir / "valcea-core-v2-shadow-receipts.json"
    kernels = workdir / "valcea-core-v2-historical-fact-kernels.json"
    articles = workdir / "valcea-core-v2-historical-article-claims.json"

    steps: list[tuple[str, list[str]]] = [
        (
            "candidate_ledger",
            [
                sys.executable,
                str(core / "build_shadow_candidate_ledger.py"),
                "--output",
                str(outputs["candidate_ledger"]),
            ],
        ),
        (
            "site_readback",
            [
                sys.executable,
                str(core / "replay_external_site.py"),
                "--output",
                str(outputs["site_readback"]),
                "--limit",
                str(limit),
            ],
        ),
        (
            "visual_provenance_readback",
            [
                sys.executable,
                str(core / "replay_external_visuals.py"),
                "--output",
                str(outputs["visual_provenance_readback"]),
                "--limit",
                str(limit),
            ],
        ),
        (
            "meta_readback",
            [
                sys.executable,
                str(core / "replay_external_meta.py"),
                "--output",
                str(outputs["meta_readback"]),
                "--limit",
                str(limit),
            ],
        ),
        (
            "instagram_visual_identity",
            [
                sys.executable,
                str(core / "instagram_visual_identity.py"),
                "--candidates",
                str(outputs["candidate_ledger"]),
                "--meta-readback",
                str(outputs["meta_readback"]),
                "--repo-root",
                str(repo_root),
                "--output",
                str(outputs["instagram_visual_identity"]),
            ],
        ),
        (
            "receipt_binding",
            [
                sys.executable,
                str(core / "materialize_shadow_receipts.py"),
                "--candidates",
                str(outputs["candidate_ledger"]),
                "--site-readback",
                str(outputs["site_readback"]),
                "--visual-readback",
                str(outputs["visual_provenance_readback"]),
                "--meta-readback",
                str(outputs["meta_readback"]),
                "--instagram-identity",
                str(outputs["instagram_visual_identity"]),
                "--output",
                str(receipts),
            ],
        ),
        (
            "instagram_identity_validation",
            [
                sys.executable,
                str(core / "validate_instagram_visual_identity_runtime.py"),
                "--candidates",
                str(outputs["candidate_ledger"]),
                "--meta-readback",
                str(outputs["meta_readback"]),
                "--identity",
                str(outputs["instagram_visual_identity"]),
                "--receipts",
                str(receipts),
            ],
        ),
        (
            "bound_transactions",
            [
                sys.executable,
                str(core / "historical_transaction_binding.py"),
                "--candidates",
                str(outputs["candidate_ledger"]),
                "--receipts",
                str(receipts),
                "--evidence",
                str(repo_root / "valcea-clar" / "editorial" / "fact_kernel_registry.json"),
                "--evidence",
                str(repo_root / "valcea-clar" / "editorial" / "facts_registry.json"),
                "--evidence",
                str(repo_root / "valcea-clar" / "editorial" / "editorial_products.json"),
                "--output",
                str(outputs["bound_transactions"]),
                "--kernels-output",
                str(kernels),
                "--articles-output",
                str(articles),
            ],
        ),
        (
            "historical_binding_validation",
            [
                sys.executable,
                str(core / "validate_historical_article_claims_runtime.py"),
                "--candidates",
                str(outputs["candidate_ledger"]),
                "--kernels",
                str(kernels),
                "--articles",
                str(articles),
                "--transactions",
                str(outputs["bound_transactions"]),
            ],
        ),
    ]

    executed: list[str] = []
    for name, argv in steps:
        _run(repo_root, argv)
        executed.append(name)

    audit_inputs: dict[str, dict[str, Any]] = {}
    for name in AUDIT_INPUT_NAMES:
        source = outputs[name]
        doc = _read_json_object(source)
        snapshot = snapshot_dir / source.name
        shutil.copyfile(source, snapshot)
        audit_inputs[name] = {
            "source_path": str(source),
            "snapshot_path": str(snapshot),
            "sha256": _sha256(snapshot),
            "schema_version": doc.get("schema_version"),
            "publication_authority": doc.get("publication_authority"),
        }

    for extra in (receipts, kernels, articles):
        _read_json_object(extra)
        shutil.copyfile(extra, snapshot_dir / extra.name)

    manifest: dict[str, Any] = {
        "schema_version": SEQUENCE_SCHEMA,
        "mode": "SHADOW_READ_ONLY",
        "publication_authority": PUBLICATION_AUTHORITY,
        "acceptance_ready": False,
        "production_write_authority": False,
        "external_auditor_inserted": False,
        "external_auditor_executed": False,
        "golden_path_stage_inserted": False,
        "github_actions_orchestration_retirement_performed": False,
        "truth_rule": (
            "The Core v2 orchestrator owns generation and binding of independent external evidence inputs. "
            "No workflow status, internal outbox state, exit code or locally generated receipt can substitute "
            "for public readback or remote receipt evidence."
        ),
        "audit_input_names": list(AUDIT_INPUT_NAMES),
        "audit_input_count": len(AUDIT_INPUT_NAMES),
        "audit_inputs": audit_inputs,
        "intermediate_artifacts": {
            "receipt_ledger": str(snapshot_dir / receipts.name),
            "historical_fact_kernels": str(snapshot_dir / kernels.name),
            "historical_article_claims": str(snapshot_dir / articles.name),
        },
        "sequence_steps": executed,
        "meta_token_present": bool(
            os.getenv("VALCEA_META_PAGE_ACCESS_TOKEN")
            or os.getenv("VALCEA_FB_PAGE_ACCESS_TOKEN")
        ),
        "fail_closed_regressions_passed": 0,
    }

    _validate_manifest_files(manifest)
    manifest["fail_closed_regressions_passed"] = _run_fail_closed_regressions(manifest)
    _validate_manifest_files(manifest)

    output = manifest_output or (workdir / "valcea-core-v2-external-evidence-sequence.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shadow_copy = snapshot_dir / output.name
    if shadow_copy != output:
        shutil.copyfile(output, shadow_copy)

    print(
        json.dumps(
            {
                "status": "PASS_SHADOW",
                "audit_input_count": manifest["audit_input_count"],
                "fail_closed_regressions_passed": manifest["fail_closed_regressions_passed"],
                "meta_token_present": manifest["meta_token_present"],
                "external_auditor_inserted": manifest["external_auditor_inserted"],
                "publication_authority": manifest["publication_authority"],
            },
            sort_keys=True,
        )
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Core v2 orchestrator-owned read-only external evidence sequence"
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--workdir", default="/tmp")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    run_sequence(
        repo_root=Path(args.repo_root),
        workdir=Path(args.workdir),
        limit=max(0, min(args.limit, 10)),
        manifest_output=Path(args.output) if args.output else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
