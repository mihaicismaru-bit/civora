#!/usr/bin/env python3
"""Apply verified P11 resolution bundles to the canonical opportunity corpus.

Resolution files are overlays: they may replace evidence, an opportunity,
changesets, and resolution tasks only for identities explicitly contained in
the overlay. The remaining 25-opportunity corpus is preserved byte-for-byte at
the object level. Nothing is published automatically by this operation.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import tempfile
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_BUNDLE = ROOT / "opportunity_bundle.json"
DEFAULT_RESOLUTIONS = ROOT / "resolutions"


def load(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: object required")
    return value


def atomic(path: pathlib.Path, value: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def keyed(rows: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.get(field)
        if not isinstance(key, str) or not key:
            raise ValueError(f"missing {field}")
        if key in output:
            raise ValueError(f"duplicate {field}: {key}")
        output[key] = row
    return output


def merge_rows(
    base: list[dict[str, Any]], overlays: list[dict[str, Any]], field: str
) -> list[dict[str, Any]]:
    replacements = keyed(overlays, field)
    result = [replacements.pop(row[field], row) for row in base]
    result.extend(replacements.values())
    return result


def apply(bundle: dict[str, Any], resolutions: list[dict[str, Any]]) -> dict[str, Any]:
    result = json.loads(json.dumps(bundle))
    initial_ids = [row["opportunity_id"] for row in result.get("opportunities", [])]
    for resolution in resolutions:
        result["evidence"] = merge_rows(
            result.get("evidence", []), resolution.get("evidence", []), "evidence_id"
        )
        result["opportunities"] = merge_rows(
            result.get("opportunities", []), resolution.get("opportunities", []), "opportunity_id"
        )
        result["changesets"] = merge_rows(
            result.get("changesets", []), resolution.get("changesets", []), "changeset_id"
        )
        result["resolution_tasks"] = merge_rows(
            result.get("resolution_tasks", []), resolution.get("resolution_tasks", []), "resolution_task_id"
        )

    final_ids = [row["opportunity_id"] for row in result.get("opportunities", [])]
    if final_ids[: len(initial_ids)] != initial_ids:
        raise ValueError("resolution overlays changed existing canonical identities or order")
    if len(final_ids) < 25 or len(final_ids) != len(set(final_ids)):
        raise ValueError(f"canonical corpus must retain at least 25 unique identities, got {len(final_ids)}")
    result["as_of"] = max(
        [str(result.get("as_of") or ""), *[str(r.get("resolved_at") or "") for r in resolutions]]
    )
    result["resolution_application"] = {
        "mode": "EXPLICIT_VERIFIED_OVERLAY",
        "automatic_publication": False,
        "applied_resolution_ids": [r["resolution_id"] for r in resolutions],
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=pathlib.Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--resolution-dir", type=pathlib.Path, default=DEFAULT_RESOLUTIONS)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    paths = sorted(args.resolution_dir.glob("*_resolution.json"))
    resolutions = [load(path) for path in paths]
    merged = apply(load(args.bundle), resolutions)
    if not args.check:
        atomic(args.bundle, merged)
    print(json.dumps({
        "opportunities": len(merged["opportunities"]),
        "resolutions": len(resolutions),
        "resolved_tasks": sum(1 for row in merged["resolution_tasks"] if row["status"] == "RESOLVED"),
        "publication_effect": "NONE",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
