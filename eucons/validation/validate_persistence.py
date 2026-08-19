#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT = EUCONS / "ops" / "persistence_contract.json"
REGISTRY = EUCONS / "ops" / "artifact_registry.json"
CHECKPOINT = EUCONS / "ops" / "checkpoint.json"
ENGINE = EUCONS / "ops" / "persistence.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("eucons_persistence", ENGINE)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load E23 persistence engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    engine = load_engine()

    if contract["engine_id"] != "EUCONS_E23_PERSISTENCE":
        raise SystemExit("E23 engine id drift")
    if contract["production_database_enabled"] is not False:
        raise SystemExit("E23 cannot enable a production database")
    if contract["transaction_protocol"] != ["PREPARE", "VALIDATE", "ATOMIC_COMMIT", "RECEIPT"]:
        raise SystemExit("E23 transaction protocol drift")
    atomic = contract["atomic_commit"]
    if not all(atomic.values()):
        raise SystemExit("E23 atomic commit controls incomplete")
    if contract["integrity"]["hash_algorithm"] != "sha256":
        raise SystemExit("E23 checksum algorithm drift")
    if not all(contract["write_guards"].values()):
        raise SystemExit("E23 write guards incomplete")

    if registry["schema_version"] != 2 or registry["model"] != "RECEIPT_INDEXED_TRANSITIVE_ARTIFACTS":
        raise SystemExit("E23 artifact registry model not reconciled")
    entries = registry["artifacts"]
    ids = [row["id"] for row in entries]
    paths = [row["path"] for row in entries]
    if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
        raise SystemExit("E23 artifact registry duplicate id/path")
    for rel in paths:
        if not (ROOT / rel).is_file():
            raise SystemExit(f"E23 registered artifact missing: {rel}")

    receipt_entries = {row["path"] for row in entries if row["class"] == "acceptance-receipt"}
    completed = checkpoint["completed_phases"]
    for phase in completed:
        matching = sorted((EUCONS / "ops" / "receipts").glob(f"{phase}_*.json"))
        if len(matching) != 1:
            raise SystemExit(f"{phase}: expected exactly one acceptance receipt, found {len(matching)}")
        receipt_path = matching[0]
        rel = receipt_path.relative_to(ROOT).as_posix()
        if rel not in receipt_entries:
            raise SystemExit(f"{phase}: acceptance receipt not registered")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("phase") != phase or receipt.get("status") != "PASS":
            raise SystemExit(f"{phase}: acceptance receipt phase/status drift")
        for artifact in receipt.get("artifacts", []):
            if not (ROOT / artifact).exists():
                raise SystemExit(f"{phase}: transitive receipt artifact missing: {artifact}")

    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "state.json"
        first = {"version": 1, "state": "prepared"}
        receipt1 = engine.atomic_write_json(target, first, validator=lambda value: None, version=1)
        if not receipt1["committed"] or receipt1["postimage_hash"] != engine.current_hash(target):
            raise SystemExit("E23 atomic first write checksum mismatch")
        before = engine.current_hash(target)
        second = {"version": 2, "state": "committed"}
        receipt2 = engine.atomic_write_json(target, second, validator=lambda value: None, expected_hash=before, version=2)
        if receipt2["preimage_hash"] != before or receipt2["postimage_hash"] == before:
            raise SystemExit("E23 compare-and-swap lineage drift")
        if engine.find_orphan_prepare_files(target.parent):
            raise SystemExit("E23 successful atomic write left orphan prepare files")

    print(f"EUCONS E23 Persistence: PASS ({len(completed)} completed phase receipts reconciled; atomic CAS/checksum protocol verified)")


if __name__ == "__main__":
    main()
