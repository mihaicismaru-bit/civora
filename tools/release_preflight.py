from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "README.md",
    "CHANGELOG.md",
    "pyproject.toml",
    "civora/__init__.py",
    ".github/workflows/test.yml",
    "docs/runbooks/operator-remediation.md",
    "docs/checkpoints/0074-production-readiness-audit.md",
    "docs/checkpoints/0075-release-blocker-remediation.md",
    "docs/release/v1.0-release-checklist.md",
    "docs/release/v1.0-release-manifest.json",
]

FORBIDDEN_RELEASE_FILENAMES = {
    ".env",
    "sources.json",
    "signals.json",
    "review_queue.json",
    "transactions.json",
    "recovery_events.json",
    "fact_kernels.json",
    "fact_reconciliation.json",
    "fact_contradictions.json",
    "editorial_gate.json",
    "editorial_approval.json",
}

IGNORED_DIRS = {".git", ".venv", "venv", "build", "dist", "__pycache__", ".release-smoke"}


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def extract_version(text: str, pattern: str, label: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ValueError(f"cannot determine {label} version")
    return match.group(1)


def tracked_tree_forbidden_files() -> list[str]:
    found: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            continue
        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        if path.name in FORBIDDEN_RELEASE_FILENAMES:
            found.append(relative.as_posix())
    return sorted(found)


def main() -> int:
    checks: list[dict] = []
    project_version: str | None = None

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "status": "pass" if passed else "fail", "detail": detail})

    missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
    record("required_release_files", not missing, "all required files present" if not missing else f"missing: {missing}")

    try:
        pyproject = read("pyproject.toml")
        init_py = read("civora/__init__.py")
        project_version = extract_version(pyproject, r'^version\s*=\s*"([^"]+)"', "project")
        runtime_version = extract_version(init_py, r'^__version__\s*=\s*"([^"]+)"', "runtime")
        record(
            "version_metadata_sync",
            project_version == runtime_version,
            f"pyproject={project_version}, runtime={runtime_version}",
        )
        record(
            "python_lower_bound",
            bool(re.search(r'^requires-python\s*=\s*">=3\.10"', pyproject, re.MULTILINE)),
            "requires-python must remain >=3.10 unless release policy is explicitly changed",
        )
    except Exception as exc:
        record("version_metadata_sync", False, str(exc))
        record("python_lower_bound", False, str(exc))

    workflow = read(".github/workflows/test.yml") if (ROOT / ".github/workflows/test.yml").is_file() else ""
    record("ci_python_3_10", '"3.10"' in workflow, "declared lower bound must be represented in CI")
    record("ci_windows_native", "windows-native:" in workflow, "Windows-native job required")
    record("ci_package_smoke", "package-smoke:" in workflow and "python -m build" in workflow,
           "built-distribution smoke job required")
    record("ci_installed_entrypoints", ".release-smoke/bin/civora --help" in workflow and
           ".release-smoke/bin/civora-remediation --help" in workflow,
           "installed console entrypoints must be smoke-tested")

    readme = read("README.md") if (ROOT / "README.md").is_file() else ""
    record("readme_release_closure", "v1.0 release-closure mode" in readme,
           "README must describe the current release-closure baseline")

    changelog = read("CHANGELOG.md") if (ROOT / "CHANGELOG.md").is_file() else ""
    if project_version:
        release_heading = rf'^## \[{re.escape(project_version)}\](?:\s+-\s+\d{{4}}-\d{{2}}-\d{{2}})?\s*$'
        record(
            "changelog_release_version",
            bool(re.search(release_heading, changelog, re.MULTILINE)),
            f"CHANGELOG must contain a release section for declared version {project_version}",
        )
    else:
        record("changelog_release_version", False, "project version unavailable")

    forbidden = tracked_tree_forbidden_files()
    record("no_durable_state_in_release_tree", not forbidden,
           "no runtime state files found" if not forbidden else f"forbidden files: {forbidden}")

    report = {
        "preflight": "CIVORA v1.0",
        "status": "pass" if all(item["status"] == "pass" for item in checks) else "fail",
        "checks": checks,
    }
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
