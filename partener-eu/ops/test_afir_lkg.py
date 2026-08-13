#!/usr/bin/env python3
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "ingest" / "afir_ingest.py"
spec = importlib.util.spec_from_file_location("afir_ingest", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def main() -> None:
    previous = {
        "schemaVersion": 1,
        "source": "AFIR",
        "generatedAt": "2026-08-12T08:00:00+00:00",
        "status": "PASS",
        "items": [{"url": f"https://www.afir.ro/item-{number}"} for number in range(3)],
        "policy": {"failClosed": True},
    }
    failed = mod.build_payload(previous, "2026-08-12T09:00:00+00:00", [], [{"error": "timeout"}])
    assert failed["status"] == "DEGRADED_LAST_KNOWN_GOOD_PRESERVED"
    assert failed["items"] == previous["items"]
    assert failed["generatedAt"] == previous["generatedAt"]
    assert failed["lastRun"]["observedAt"] == "2026-08-12T09:00:00+00:00"
    assert failed["policy"]["sourceFailure"] == "preserve-last-known-good-and-block-dependent-facts-only"

    fresh_items = [{"url": f"https://www.afir.ro/new-{number}"} for number in range(3)]
    succeeded = mod.build_payload(previous, "2026-08-12T10:00:00+00:00", fresh_items, [])
    assert succeeded["status"] == "PASS"
    assert succeeded["items"] == fresh_items
    assert succeeded["generatedAt"] == "2026-08-12T10:00:00+00:00"
    print("PASS AFIR last-known-good preservation")


if __name__ == "__main__":
    main()
