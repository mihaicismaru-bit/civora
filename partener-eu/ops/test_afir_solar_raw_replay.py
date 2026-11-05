#!/usr/bin/env python3
"""Adversarial offline tests against one freshly captured AFIR original pair.

Mutates only temporary in-memory ZIP copies. Never modifies immutable evidence.
"""
import argparse
import copy
from io import BytesIO
import importlib.util
import json
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
import re
from zipfile import ZipFile

from afir_solar_raw_replay import ACQUIRE, OBS, replay, totals


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
    # A valid XLSX with an invented manifest must never be accepted as an
    # official observation. Copy the evidence first; never edit the original.
    proven = replay(root)
    assert proven['status'] == 'RAW_ROWS_REPLAYED_NOT_PUBLISHED'
    tamper_cases = (
        (('official_notice_url',), 'https://example.org/notice'),
        (('programme',), 'UNRELATED_PROGRAMME'),
        (('parser_version',), 'unreviewed-parser'),
        (('observation_state',), 'OPEN_CALL'),
        (('run_id',), ''),
        (('official_index', 'url'), 'https://example.org/index'),
        (('official_index', 'sha256'), '0' * 64),
        (('official_index', 'bytes'), 0),
        (('official_index', 'fetched_at'), '1990-01-01T00:00:00Z'),
        (('documents', 0, 'source_family'), 'MIPE'),
        (('documents', 0, 'authority_class'), 'SELF_DECLARED'),
        (('documents', 0, 'observation_state'), 'OPEN_CALL'),
        (('documents', 0, 'status'), 'RECONCILED'),
        (('documents', 0, 'parser_version'), 'unknown'),
        (('documents', 0, 'fetched_at'), '1990-01-01T00:00:00Z'),
    )
    with TemporaryDirectory(prefix='afir-solar-manifest-negative-') as temp:
        isolated = Path(temp)
        for file in ('manifest.json', 'afir-selection-index.raw.html',
                     'solar-3-2026-selectate.raw.xlsx', 'solar-3-2026-nefinantate.raw.xlsx'):
            copy2(root / file, isolated / file)
        original = json.loads((isolated / 'manifest.json').read_text(encoding='utf-8'))
        for keys, forged_value in tamper_cases:
            forged = copy.deepcopy(original)
            cursor = forged
            for key in keys[:-1]:
                cursor = cursor[key]
            cursor[keys[-1]] = forged_value
            (isolated / 'manifest.json').write_text(
                json.dumps(forged, ensure_ascii=False), encoding='utf-8')
            try:
                replay(isolated)
            except (ValueError, KeyError, TypeError):
                rejected += 1
            else:
                raise AssertionError(f'Forged original manifest admitted: {keys}')
    print(json.dumps({'status': 'PASS', 'independent_raw_negative_replays_rejected': rejected,
                      'original_artifacts_modified': False, 'publish_authorized': False}))


if __name__ == '__main__':
    main()
