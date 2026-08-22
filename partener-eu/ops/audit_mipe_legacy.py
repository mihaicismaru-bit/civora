#!/usr/bin/env python3
"""Repository-local caller audit for legacy MIPE ingestion modules.

This script is intentionally conservative: a module is a deletion candidate only
when the full checkout contains no executable/import caller outside the module
itself. Documentation/path-trigger mentions are reported separately so cleanup
can remain fail-closed and evidence-backed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()
OUT = ROOT / "partener-eu" / "ops" / "mipe_legacy_audit.json"

CANDIDATES = (
    "mipe_browser_ingest.py",
    "mipe_browser_ingest_v2.py",
    "mipe_direct_only_ingest.py",
    "mipe_discovery_ingest.py",
    "mipe_dual_cache.py",
    "mipe_ingest.py",
    "mipe_ingest_ipv4.py",
    "mipe_known_seed_ingest.py",
    "mipe_pdds_ingest.py",
    "mipe_resilient_ingest.py",
    "mipe_transport_scout.py",
    "mipe_windows_crawl_v3.py",
    "mipe_windows_crawl_v3_entry.py",
)

TEXT_SUFFIXES = {
    ".py", ".yml", ".yaml", ".json", ".md", ".txt", ".sh", ".ps1",
    ".js", ".mjs", ".cjs", ".html", ".toml", ".ini", ".cfg",
}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".next", "dist", "build"}


@dataclass(frozen=True)
class Ref:
    path: str
    line: int
    kind: str
    excerpt: str


def iter_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.resolve() == SELF or path.resolve() == OUT.resolve():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield path


def classify_line(path: Path, line: str, basename: str, stem: str) -> str:
    stripped = line.strip()
    if path.suffix == ".py" and re.search(rf"\b(?:from|import)\s+{re.escape(stem)}\b", stripped):
        return "PYTHON_IMPORT"
    if path.suffix in {".yml", ".yaml"}:
        executable = (
            re.search(r"\bpython(?:3)?\b", stripped, re.I)
            or "PYTHON_EXE" in stripped
            or re.search(r"\bpy(?:\.exe)?\b", stripped, re.I)
        )
        if basename in stripped and executable:
            return "WORKFLOW_EXECUTION"
        if basename in stripped and stripped.startswith("-"):
            return "WORKFLOW_PATH_TRIGGER_OR_LIST"
        return "WORKFLOW_REFERENCE"
    if path.suffix == ".py" and basename in stripped:
        if re.search(r"subprocess|run\(|Popen|os\.system|exec", stripped):
            return "PYTHON_EXECUTION_REFERENCE"
        return "PYTHON_REFERENCE"
    if path.suffix in {".md", ".txt"}:
        return "DOCUMENTATION_REFERENCE"
    return "OTHER_REFERENCE"


def audit_candidate(basename: str, files: list[Path]) -> dict:
    stem = basename[:-3]
    target = ROOT / "partener-eu" / "ingest" / basename
    refs: list[Ref] = []
    import_re = re.compile(rf"\b(?:from|import)\s+{re.escape(stem)}\b")

    for path in files:
        if path.resolve() == target.resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if basename not in text and stem not in text:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if basename not in line and not import_re.search(line):
                continue
            refs.append(
                Ref(
                    path=path.relative_to(ROOT).as_posix(),
                    line=number,
                    kind=classify_line(path, line, basename, stem),
                    excerpt=line.strip()[:240],
                )
            )

    strong_kinds = {"PYTHON_IMPORT", "WORKFLOW_EXECUTION", "PYTHON_EXECUTION_REFERENCE"}
    strong = [r for r in refs if r.kind in strong_kinds]
    workflow_refs = [r for r in refs if r.kind.startswith("WORKFLOW_")]
    docs = [r for r in refs if r.kind == "DOCUMENTATION_REFERENCE"]

    if not target.exists():
        status = "ABSENT"
    elif strong:
        status = "ACTIVE_CALLER_FOUND"
    elif refs:
        status = "NO_EXECUTABLE_CALLER_BUT_REFERENCED"
    else:
        status = "ZERO_CALLER_CANDIDATE"

    return {
        "file": target.relative_to(ROOT).as_posix(),
        "exists": target.exists(),
        "bytes": target.stat().st_size if target.exists() else 0,
        "status": status,
        "strongCallerCount": len(strong),
        "workflowReferenceCount": len(workflow_refs),
        "documentationReferenceCount": len(docs),
        "referenceCount": len(refs),
        "references": [r.__dict__ for r in refs],
    }


def main() -> int:
    files = list(iter_text_files())
    rows = [audit_candidate(name, files) for name in CANDIDATES]
    payload = {
        "schema": "PARTENER_MIPE_LEGACY_CALLER_AUDIT_V1",
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "root": ".",
        "scannedTextFiles": len(files),
        "policy": (
            "Deletion is fail-closed: ZERO_CALLER_CANDIDATE is necessary but not sufficient. "
            "Replay/rollback and workflow/product validation are still required before deletion."
        ),
        "summary": {
            "activeCallerFound": sum(r["status"] == "ACTIVE_CALLER_FOUND" for r in rows),
            "referencedWithoutExecutableCaller": sum(r["status"] == "NO_EXECUTABLE_CALLER_BUT_REFERENCED" for r in rows),
            "zeroCallerCandidates": sum(r["status"] == "ZERO_CALLER_CANDIDATE" for r in rows),
            "absent": sum(r["status"] == "ABSENT" for r in rows),
        },
        "candidates": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
