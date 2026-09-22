#!/usr/bin/env python3
"""Regression guard for executable Python paths referenced by MIPE Engine v3."""

from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "partener-eu-mipe-engine-v3.yml"


def main() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    refs = sorted(
        set(
            re.findall(
                r"(?m)^\s*python(?:3)?\s+(partener-eu/[A-Za-z0-9_./-]+\.py)(?:\s|$)",
                text,
            )
        )
    )
    if not refs:
        raise AssertionError("MIPE Engine v3 contains no executable PARTENER Python paths")

    missing = [ref for ref in refs if not (ROOT / ref).is_file()]
    if missing:
        raise AssertionError(
            "MIPE Engine v3 references missing Python files: " + ", ".join(missing)
        )

    print(
        json.dumps(
            {
                "workflow": str(WORKFLOW.relative_to(ROOT)),
                "referencedPythonFiles": len(refs),
                "missing": missing,
                "status": "PASS",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
