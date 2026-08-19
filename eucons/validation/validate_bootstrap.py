#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"

REQUIRED = [
    EUCONS / "README.md",
    EUCONS / "EUCONS_PRODUCT_CANON.md",
    EUCONS / "EUCONS_ARCHITECTURE.md",
    EUCONS / "EUCONS_AUTONOMY_CONTRACT.md",
    EUCONS / "ROADMAP.md",
    EUCONS / "ops" / "checkpoint.json",
    EUCONS / "ops" / "artifact_registry.json",
    EUCONS / "ops" / "health.json",
    EUCONS / "web" / "index.html",
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED if not path.is_file()]
    assert not missing, f"missing bootstrap artifacts: {missing}"

    checkpoint = load_json(EUCONS / "ops" / "checkpoint.json")
    assert checkpoint["product"] == "EUCONS_COMMERCIAL_OS"
    assert checkpoint["terminal_target"] == "PRODUCTION_READY"
    assert checkpoint["autonomy"]["enabled"] is True
    assert checkpoint["autonomy"]["fail_closed"] is True
    assert checkpoint["external_handoff_allowed_only_after"] == "E28"

    registry = load_json(EUCONS / "ops" / "artifact_registry.json")
    ids = [item["id"] for item in registry["artifacts"]]
    assert len(ids) == len(set(ids)), "artifact IDs must be unique"
    paths = {item["path"] for item in registry["artifacts"]}
    for required in REQUIRED[:-1]:
        rel = str(required.relative_to(ROOT)).replace("\\", "/")
        assert rel in paths or rel.endswith("health.json"), f"unregistered artifact: {rel}"

    health = load_json(EUCONS / "ops" / "health.json")
    assert health["product"] == "EUCONS_COMMERCIAL_OS"
    assert not health["critical_failures"]

    preview = (EUCONS / "web" / "index.html").read_text(encoding="utf-8")
    assert 'name="robots" content="noindex,nofollow"' in preview
    assert "EUROCONSULT" in preview, "preview must remain visibly tied to the product"
    assert '<link rel="canonical" href="https://eucons.ro/">' in preview, "preview canonical drift"

    autonomy = (EUCONS / "EUCONS_AUTONOMY_CONTRACT.md").read_text(encoding="utf-8")
    assert "PRODUCTION_READY" in autonomy
    assert "BLOCKED_EXTERNAL_ONLY" in autonomy
    assert "No-owner-interruption rule" in autonomy

    print("EUCONS bootstrap validation: PASS")


if __name__ == "__main__":
    main()
