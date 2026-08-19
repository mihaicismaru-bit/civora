#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "eucons" / "ops" / "persistence.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("eucons_persistence", ENGINE)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load E23 persistence engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expect_value_error(label: str, fn) -> None:
    try:
        fn()
    except ValueError:
        return
    raise SystemExit(f"{label}: expected fail-closed ValueError")


def main() -> None:
    engine = load_engine()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        target = root / "state.json"
        payload = {"state": "GOOD"}
        first = engine.atomic_write_json(target, payload, validator=lambda value: None, version=1)
        original_bytes = target.read_bytes()

        expect_value_error(
            "stale compare-and-swap",
            lambda: engine.atomic_write_json(target, {"state": "STALE"}, validator=lambda value: None, expected_hash="0" * 64, version=2),
        )
        if target.read_bytes() != original_bytes:
            raise SystemExit("stale compare-and-swap modified canonical state")

        def reject(_: dict) -> None:
            raise ValueError("synthetic validation rejection")

        expect_value_error(
            "validation rejection",
            lambda: engine.atomic_write_json(target, {"state": "INVALID"}, validator=reject, expected_hash=first["postimage_hash"], version=2),
        )
        if target.read_bytes() != original_bytes:
            raise SystemExit("validation rejection modified canonical state")
        if engine.find_orphan_prepare_files(root):
            raise SystemExit("failed persistence attempt left orphan prepare file")

        receipt_path = root / "receipt.json"
        engine.append_only_receipt(receipt_path, {"status": "PASS"})
        expect_value_error("receipt overwrite", lambda: engine.append_only_receipt(receipt_path, {"status": "CHANGED"}))

        expect_value_error("invalid version", lambda: engine.atomic_write_json(root / "new.json", {}, validator=lambda value: None, version=0))

    print("EUCONS E23 Persistence fail-closed: PASS")


if __name__ == "__main__":
    main()
