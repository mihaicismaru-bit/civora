#!/usr/bin/env python3
"""Adversarial offline tests against one freshly captured AFIR original pair.

Mutates only temporary in-memory ZIP copies. Never modifies immutable evidence.
"""
import argparse
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import re
from zipfile import ZipFile

from afir_solar_raw_replay import ACQUIRE, OBS, totals


def modify_numeric_cell(original, cell):
    needle = rb'(<c r="' + cell.encode('ascii') + rb'"[^>]*><v>)(\d+)(</v></c>)'
    with ZipFile(BytesIO(original)) as src:
        xml = src.read('xl/worksheets/sheet1.xml')
        matches = list(re.finditer(needle, xml))
        if len(matches) != 1:
            raise AssertionError(f'Expected one original numeric cell {cell}')
        hit = matches[0]
        changed = xml[:hit.start(2)] + str(int(hit.group(2)) + 1).encode() + xml[hit.end(2):]
        out = BytesIO()
        with ZipFile(out, 'w') as dst:
            for member in src.infolist():
                dst.writestr(member, changed if member.filename == 'xl/worksheets/sheet1.xml' else src.read(member))
    return out.getvalue()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--evidence-dir', required=True)
    args = p.parse_args()
    root = Path(args.evidence_dir)
    obs = json.loads(OBS.read_text(encoding='utf-8'))
    module = importlib.util.spec_from_file_location('afir_acq_neg', ACQUIRE)
    acq = importlib.util.module_from_spec(module)
    module.loader.exec_module(acq)
    rejected = 0
    for category, filename, targets in (
        ('Selectate', 'solar-3-2026-selectate.raw.xlsx', ('B21', 'Z20', 'AA80')),
        ('Nefinanțate', 'solar-3-2026-nefinantate.raw.xlsx', ('B18', 'Y17', 'Y28')),
    ):
        raw = (root / filename).read_bytes()
        expected = obs['source_documents'][category]
        for cell in targets:
            changed = modify_numeric_cell(raw, cell)
            try:
                totals(changed, category, expected, obs, acq)
            except (ValueError, AssertionError):
                rejected += 1
            else:
                raise AssertionError(f'Altered {category} original cell {cell} was admitted')
    print(json.dumps({'status': 'PASS', 'independent_raw_xlsx_negative_replays_rejected': rejected,
                      'original_artifacts_modified': False, 'publish_authorized': False}))


if __name__ == '__main__':
    main()
