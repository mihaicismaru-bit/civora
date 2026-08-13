#!/usr/bin/env python3
"""One deterministic release gate for the PARTENER.EU production candidate."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKS = [
    ("recovery", [sys.executable, str(ROOT / "ops" / "test_recovery.py")]),
    ("frontend", [sys.executable, str(ROOT / "ops" / "test_frontend_regression.py")]),
    ("p10_policy", [sys.executable, str(ROOT / "ops" / "test_p10_policy_regression.py")]),
    ("afir_policy", [sys.executable, str(ROOT / "ops" / "test_afir_ingest_policy.py")]),
    ("afir_lkg", [sys.executable, str(ROOT / "ops" / "test_afir_lkg.py")]),
    ("entity_resolver", [sys.executable, str(ROOT / "ops" / "test_entity_resolver.py")]),
    ("transport", [sys.executable, str(ROOT / "ops" / "test_public_site_transport.py")]),
    ("data_plane_tests", [sys.executable, str(ROOT / "ops" / "test_intelligence_index.py")]),
    ("data_plane_runtime", [sys.executable, str(ROOT / "ingest" / "intelligence_index.py"), "--check"]),
    ("p11_tests", [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "p11"), "-p", "test_*.py"]),
    ("p11_corpus", [sys.executable, str(ROOT / "p11" / "validate_corpus.py")]),
    ("p11_admission", [sys.executable, str(ROOT / "p11" / "validate_admission_batch.py")]),
    ("p11_resolution_replay", [sys.executable, str(ROOT / "p11" / "apply_resolutions.py"), "--check"]),
    ("p11_projection_replay", [sys.executable, str(ROOT / "p11" / "build_public_projection.py"), "--check"]),
    ("p11_projection", [sys.executable, str(ROOT / "ops" / "test_p11_public_projection.py")]),
    ("app_syntax", ["node", "--check", str(ROOT / "web" / "app.js")]),
    ("adapter_syntax", ["node", "--check", str(ROOT / "web" / "p11-public-adapter.js")]),
    ("projection_syntax", ["node", "--check", str(ROOT / "web" / "p11-public-data.js")]),
]


def main() -> int:
    results = []
    for name, command in CHECKS:
        completed = subprocess.run(command, cwd=ROOT.parent, text=True, capture_output=True)
        output = ((completed.stdout or "") + (completed.stderr or "")).strip()
        results.append({"check": name, "pass": completed.returncode == 0, "output": output[-1200:]})
    failed = [row for row in results if not row["pass"]]
    report = {"status": "PASS" if not failed else "FAIL", "passed": len(results) - len(failed), "total": len(results), "checks": results}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
