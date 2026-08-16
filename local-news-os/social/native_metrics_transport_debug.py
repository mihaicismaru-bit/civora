#!/usr/bin/env python3
from __future__ import annotations

import test_native_metrics_transport as suite


def main() -> int:
    tests = [(name, value) for name, value in sorted(vars(suite).items()) if name.startswith('test_') and callable(value)]
    for name, test in tests:
        try:
            test()
        except Exception as exc:
            print(f'::error title={name}::{type(exc).__name__}: {exc!r}')
            raise
        print(f'PASS {name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
