# CIVORA Checkpoint 0040 — CI package discovery fix

Status: `CODE_COMPLETE_CI_RUNNING`

## Trigger

GitHub Actions became operational and the Python 3.12 job failed during `python -m pip install -e .` before tests could run.

## Root cause

Setuptools automatic flat-layout discovery detected two top-level directories, `civora` and `schemas`, and refused to build the editable package because package inclusion was ambiguous.

## Fix

Updated `pyproject.toml` to:

- declare the setuptools build backend explicitly;
- require a modern setuptools version;
- restrict package discovery to `civora*`;
- explicitly exclude `schemas*`, `tests*`, and `docs*` from Python package discovery.

The JSON schema directory remains repository data and is not treated as a Python package.

## Gates

- `CI_TRIGGERING`: PASS
- `CI_ROOT_CAUSE_IDENTIFIED`: PASS
- `PACKAGE_DISCOVERY_EXPLICIT`: PASS_IMPLEMENTATION_REVIEW
- `EDITABLE_INSTALL`: PENDING_CI
- `UNIT_TESTS_PY311`: PENDING_CI
- `UNIT_TESTS_PY312`: PENDING_CI
- `UNIT_TESTS_PY313`: PENDING_CI

## Next action

Observe the new workflow run. If installation succeeds, inspect all matrix test results. If tests expose runtime defects, fix the failing behavior before advancing persistence work.
