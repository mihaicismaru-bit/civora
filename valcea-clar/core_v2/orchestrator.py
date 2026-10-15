from __future__ import annotations

import sys
from pathlib import Path

import orchestrator_run100_fix as _impl

# Canonical Core v2 orchestrator surface. Export private migration seams too,
# because CI regressions intentionally introspect them while the controlled
# rebuild is in progress.
globals().update({name: value for name, value in vars(_impl).items() if not name.startswith("__")})


def _arg_value(argv: list[str], name: str, default: str) -> str:
    try:
        index = argv.index(name)
    except ValueError:
        return default
    if index + 1 >= len(argv):
        return default
    return argv[index + 1]


def _run_orchestrator_owned_external_evidence(argv: list[str]) -> int:
    if "--run-bounded-cycle" not in argv or "--live" not in argv:
        return 0

    # Keep the 41-stage canonical cycle unchanged. External evidence generation
    # runs after that bounded cycle, in the same Core v2 orchestrator process,
    # and remains read-only / shadow-only. The independent auditor is NOT
    # inserted or executed here.
    from external_evidence_sequence import run_sequence

    repo_root = Path(_arg_value(argv, "--repo-root", "."))
    workdir = Path(_arg_value(argv, "--workdir", "/tmp"))
    run_sequence(
        repo_root=repo_root,
        workdir=workdir,
        limit=10,
        manifest_output=workdir / "valcea-core-v2-external-evidence-sequence.json",
    )
    return 0


if __name__ == "__main__":
    current_argv = sys.argv[1:]
    rc = main()
    if rc == 0:
        rc = _run_orchestrator_owned_external_evidence(current_argv)
    raise SystemExit(rc)
