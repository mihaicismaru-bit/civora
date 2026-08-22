#!/usr/bin/env python3
"""Repository-local caller audit for legacy MIPE modules and source fixers.

The audit is deliberately conservative. A file can become a deletion candidate
only after a full-checkout scan finds no executable/import caller outside that
file. Documentation and path-trigger mentions are reported separately so code
cleanup stays fail-closed, reproducible and evidence-backed.
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
    "partener-eu/ingest/mipe_browser_ingest.py",
    "partener-eu/ingest/mipe_browser_ingest_v2.py",
    "partener-eu/ingest/mipe_direct_only_ingest.py",
    "partener-eu/ingest/mipe_discovery_ingest.py",
    "partener-eu/ingest/mipe_dual_cache.py",
    "partener-eu/ingest/mipe_ingest.py",
    "partener-eu/ingest/mipe_ingest_ipv4.py",
    "partener-eu/ingest/mipe_known_seed_ingest.py",
    "partener-eu/ingest/mipe_pdds_ingest.py",
    "partener-eu/ingest/mipe_resilient_ingest.py",
    "partener-eu/ingest/mipe_transport_scout.py",
    "partener-eu/ingest/mipe_windows_crawl_v3.py",
    "partener-eu/ingest/mipe_windows_crawl_v3_entry.py",
    "partener-eu/ops/fix_mipe_content_quality.py",
    "partener-eu/ops/fix_mipe_decision_extraction.py",
    "partener-eu/ops/fix_mipe_dual_relay.py",
    "partener-eu/ops/fix_mipe_dual_reporting.py",
    "partener-eu/ops/fix_mipe_first_party_relay.py",
    "partener-eu/ops/fix_mipe_resilient_classifier.py",
    "partener-eu/ops/fix_mipe_resilient_runtime.py",
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
        if not path.is_file() or path.resolve() in {SELF, OUT.resolve()}:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield path


def yaml_executes(stripped: str, basename: str) -> bool:
    if basename not in stripped:
        return False
    if "PYTHON_EXE" in stripped:
        return True
    return bool(
        re.search(
            r"(?:^|\brun:\s*|[;&|]\s*)(?:python(?:3)?(?:\.exe)?|py(?:\.exe)?)(?:\s|$)",
            stripped,
            re.I,
        )
    )


def classify_line(path: Path, line: str, basename: str, stem: str) -> str:
    stripped = line.strip()
    if path.suffix == ".py" and re.search(rf"\b(?:from|import)\s+{re.escape(stem)}\b", stripped):
        return "PYTHON_IMPORT"
    if path.suffix in {".yml", ".yaml"}:
        if yaml_executes(stripped, basename):
            return "WORKFLOW_EXECUTION"
        if basename in stripped and stripped.startswith("-"):
            return "WORKFLOW_PATH_TRIGGER_OR_LIST"
        return "WORKFLOW_REFERENCE"
    if path.suffix == ".py" and basename in stripped:
        if re.search(r"subprocess|run\(|Popen|os\.system|exec", stripped):
            return "PYTHON_EXECUTION_REFERENCE"
        return "PYTHON_REFERENCE"
    if path.suffix in {".sh", ".ps1"} and basename in stripped:
        if re.search(r"python|PYTHON_EXE|(?:^|\s)py(?:\.exe)?(?:\s|$)", stripped, re.I):
            return "SHELL_EXECUTION"
        return "SHELL_REFERENCE"
    if path.suffix in {".md", ".txt"}:
        return "DOCUMENTATION_REFERENCE"
    return "OTHER_REFERENCE"


def audit_candidate(candidate: str, files: list[Path]) -> dict:
    target = ROOT / candidate
    basename = target.name
    stem = target.stem
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

    strong_kinds = {
        "PYTHON_IMPORT",
        "WORKFLOW_EXECUTION",
        "PYTHON_EXECUTION_REFERENCE",
        "SHELL_EXECUTION",
    }
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
        "file": candidate,
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
    rows = [audit_candidate(candidate, files) for candidate in CANDIDATES]
    payload = {
        "schema": "PARTENER_MIPE_LEGACY_CALLER_AUDIT_V2",
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
