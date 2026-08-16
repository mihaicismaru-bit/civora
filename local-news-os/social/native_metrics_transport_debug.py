#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import native_metrics_transport as transport
import test_native_metrics_transport as suite

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    tests = [(name, value) for name, value in sorted(vars(suite).items()) if name.startswith('test_') and callable(value)]
    for name, test in tests:
        try:
            test()
        except Exception as exc:
            print(f'::error title={name}::{type(exc).__name__}: {exc!r}')
            raise
        print(f'PASS {name}')

    access = json.loads((ROOT / 'valcea-clar/social/meta_auth_state.json').read_text(encoding='utf-8'))
    for platform in ('facebook', 'instagram'):
        channel = json.loads((ROOT / f'valcea-clar/social/channels/{platform}.json').read_text(encoding='utf-8'))
        publication = {
            'instance_id': channel['instance_id'],
            'channel_id': channel['channel_id'],
            'platform': platform,
            'status': 'PUBLISHED',
            'publication_id': f'ci:{platform}',
            'remote_publication_id': f'ci_remote_{platform}',
            'story_id': 'ci:story',
            'product_id': f'ci:{platform}:product',
            'published_at': '2026-08-16T08:00:00Z',
            'native_format': 'single_photo',
            'topic_keys': ['service_journalism'],
            'series_id': None,
        }
        planned = transport.build_transport_plan(channel, publication, access)
        if planned.get('status') != 'TRANSPORT_PLANNED':
            print(f'::error title=valcea_{platform}_plan::{json.dumps(planned, ensure_ascii=False)}')
            raise AssertionError(planned)
        print(f'PASS valcea_{platform}_plan')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
