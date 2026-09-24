#!/usr/bin/env python3
"""Regression guard for PARTENER.EU publication-trigger coverage.

Validated writer workflows may persist public artifacts to ``main`` with GITHUB_TOKEN.
GitHub deliberately suppresses most recursive workflow events from such token-authored
commits, so a writer can make repo truth newer than the public Pages deployment unless
there is an explicit handoff. This test keeps the AFIR coverage -> Pages handoff
fail-closed and auditable.
"""
from pathlib import Path

BRIDGE = Path('.github/workflows/partener-eu-afir-pages-bridge.yml')
PAGES = Path('.github/workflows/partener-eu-pages.yml')

bridge = BRIDGE.read_text(encoding='utf-8')
pages = PAGES.read_text(encoding='utf-8')

assert "- 'PARTENER.EU AFIR September Coverage'" in bridge, (
    'AFIR coverage writer must have an explicit publication handoff'
)
assert "github.event.workflow_run.conclusion == 'success'" in bridge, (
    'Bridge must not dispatch Pages after a failed upstream writer run'
)
assert "github.event.workflow_run.head_branch == 'main'" in bridge, (
    'Bridge must not publish PR/head-branch coverage runs'
)
assert 'actions: write' in bridge, 'Bridge needs bounded Actions dispatch permission'
assert 'contents: read' in bridge, 'Bridge must remain read-only for repository contents'
assert 'gh workflow run partener-eu-pages.yml --ref main' in bridge, (
    'Bridge must dispatch the canonical PARTENER.EU Pages workflow on main'
)
assert "- '.github/workflows/partener-eu-afir-pages-bridge.yml'" in bridge, (
    'Bridge installation itself must trigger one deployment so current persisted data is published'
)
assert 'workflow_dispatch:' in pages, 'Canonical Pages workflow must remain dispatchable'

print('PASS: AFIR writer -> Pages publication handoff is explicit, main-scoped and fail-closed.')
