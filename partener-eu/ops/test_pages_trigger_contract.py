#!/usr/bin/env python3
"""Regression guard for publication-trigger coverage.

PARTENER.EU contains writer workflows that persist validated public artifacts back to
main with GITHUB_TOKEN. Those bot-authored commits do not recursively emit ordinary
push-triggered Actions runs. The Pages workflow therefore must subscribe directly to
successful upstream writer workflow completions that can change public artifacts.
"""
from pathlib import Path

WORKFLOW = Path('.github/workflows/partener-eu-pages.yml')
text = WORKFLOW.read_text(encoding='utf-8')

required_workflow_run_sources = (
    'PARTENER.EU MIPE Ingestion',
    'PARTENER.EU MIPE Engine v3',
    'PARTENER.EU PEO Calendar',
    'PARTENER.EU Editorial Daily Products',
    'PARTENER.EU AFIR September Coverage',
)

missing = [name for name in required_workflow_run_sources if f"- '{name}'" not in text]
assert not missing, f'Pages workflow missing workflow_run sources: {missing}'
assert "github.event.workflow_run.conclusion == 'success'" in text, 'Pages must fail closed on upstream workflow failure'
assert "github.event.workflow_run.head_branch == 'main'" in text, 'Pages workflow_run must be main-scoped'

print('PASS: Pages trigger contract covers validated upstream public writers and remains fail-closed.')
