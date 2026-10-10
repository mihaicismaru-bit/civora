from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SOURCE_IDS = {
    "ipj_valcea",
    "isu_valcea",
    "apavil",
    "primaria_ramnicu_valcea",
    "cj_valcea",
    "eta",
    "isj_valcea",
    "filarmonica_valcea",
}


def validate_registry(path: Path) -> dict[str, object]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if doc.get("mode") != "shadow_only":
        errors.append("pilot_not_shadow_only")
    if doc.get("publication_authority") != "NONE":
        errors.append("pilot_has_publication_authority")
    if doc.get("source_expansion_forbidden_during_pilot") is not True:
        errors.append("source_expansion_not_forbidden")
    if doc.get("no_material_signal_terminal") != "NO_STORY":
        errors.append("no_material_signal_not_no_story")

    rows = doc.get("sources") or []
    enabled = [row for row in rows if isinstance(row, dict) and row.get("enabled") is True]
    ids = [str(row.get("source_id") or "") for row in enabled]
    if set(ids) != EXPECTED_SOURCE_IDS or len(ids) != len(EXPECTED_SOURCE_IDS):
        errors.append(f"pilot_source_set_mismatch:{sorted(ids)}")
    if len(ids) != len(set(ids)):
        errors.append("duplicate_source_id")

    adapters: list[str] = []
    for row in enabled:
        source_id = str(row.get("source_id") or "")
        adapter = str(row.get("adapter") or "")
        if not adapter:
            errors.append(f"{source_id}:adapter_missing")
            continue
        adapters.append(adapter)
        candidate = ROOT / adapter
        if not candidate.is_file():
            errors.append(f"{source_id}:adapter_not_found:{adapter}")
        if not adapter.startswith("valcea-clar/scripts/") or not adapter.endswith(".py"):
            errors.append(f"{source_id}:adapter_outside_bounded_script_surface")
    if len(adapters) != len(set(adapters)):
        errors.append("duplicate_adapter_path")

    return {
        "status": "PASS" if not errors else "FAILED",
        "enabled_source_count": len(enabled),
        "source_ids": sorted(ids),
        "errors": errors,
        "publication_authority": "NONE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate bounded Core v2 shadow pilot source registry")
    parser.add_argument("--registry", default="valcea-clar/core_v2/pilot_sources.json")
    args = parser.parse_args()
    result = validate_registry(ROOT / args.registry)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
