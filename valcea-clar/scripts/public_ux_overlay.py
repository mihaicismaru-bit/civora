#!/usr/bin/env python3
"""Run the existing Sites overlay without replacing canonical UX pages from DIST."""
from __future__ import annotations

import shutil

import overlay_runtime_export as base


def materialize_without_overwrite() -> list[str]:
    materialized: list[str] = []
    for route in base.configured_static_routes():
        target = base.route_index(base.RUNTIME, route)
        # The public UX renderer owns any page already materialized in runtime.
        # DIST is a base export and must never overwrite a newer canonical page.
        if target.is_file():
            materialized.append(route)
            continue
        source = base.route_index(base.DIST, route)
        if not source.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        materialized.append(route)
    return materialized


base.materialize_static_runtime_routes = materialize_without_overwrite

if __name__ == "__main__":
    raise SystemExit(base.main())
