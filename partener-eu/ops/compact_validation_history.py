#!/usr/bin/env python3
"""Compact partener-eu/validation/history without losing P10 evidence.

The validator writes one JSON report per run (~25/day). p10_acceptance_sync only
needs, per UTC date, to know whether a qualifying live run exists; the integrity
monitor only needs the report mirrored from latest.json. So:

- every report from the last KEEP_FULL_DAYS UTC dates is kept;
- for each older date one report is kept: the last qualifying run of that date,
  or, if none qualified, the last run of that date;
- the report mirrored from latest.json is always kept.

Fail-closed: before deleting anything, the set of qualifying dates and the set
of covered dates are recomputed on the kept files and must be identical to the
originals; otherwise nothing is deleted and the script exits non-zero.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
HISTORY = ROOT / "validation" / "history"
LATEST = ROOT / "validation" / "latest.json"
KEEP_FULL_DAYS = 7


def _qualifies():
    spec = importlib.util.spec_from_file_location("p10_acceptance_sync", ROOT / "ops" / "p10_acceptance_sync.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.qualifies


def load(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def run_date(path: pathlib.Path, report: Any) -> str:
    started = (report or {}).get("run_started") if isinstance(report, dict) else None
    if started:
        return str(started)[:10]
    stem = path.stem  # e.g. 20260811T123536Z
    return f"{stem[0:4]}-{stem[4:6]}-{stem[6:8]}"


def latest_mirror() -> pathlib.Path | None:
    latest = load(LATEST)
    started = (latest or {}).get("run_started") if isinstance(latest, dict) else None
    if not started:
        return None
    return HISTORY / (str(started).replace(":", "").replace("-", "") + ".json")


def plan(qualifies) -> tuple[list[pathlib.Path], list[pathlib.Path], dict[str, Any]]:
    rows = []
    for path in sorted(HISTORY.glob("*.json")):
        report = load(path)
        rows.append((path, run_date(path, report), bool(qualifies(report))))

    dates = sorted({d for _, d, _ in rows})
    full_dates = set(dates[-KEEP_FULL_DAYS:])
    mirror = latest_mirror()

    keep: set[pathlib.Path] = set()
    by_date: dict[str, list[tuple[pathlib.Path, bool]]] = {}
    for path, date, ok in rows:
        by_date.setdefault(date, []).append((path, ok))
    for date, items in by_date.items():
        if date in full_dates:
            keep.update(p for p, _ in items)
            continue
        qualifying = [p for p, ok in items if ok]
        keep.add((qualifying or [p for p, _ in items])[-1])
    if mirror and mirror.exists():
        keep.add(mirror)

    delete = [p for p, _, _ in rows if p not in keep]
    kept_rows = [(p, d, ok) for p, d, ok in rows if p in keep]
    invariants = {
        "covered_dates_equal": {d for _, d, _ in rows} == {d for _, d, _ in kept_rows},
        "qualifying_dates_equal": {d for _, d, ok in rows if ok} == {d for _, d, ok in kept_rows if ok},
        "latest_mirror_kept": (mirror is None) or (not mirror.exists()) or (mirror in keep),
    }
    stats = {
        "files_before": len(rows),
        "files_after": len(keep),
        "dates": len(dates),
        "qualifying_dates": len({d for _, d, ok in rows if ok}),
        "invariants": invariants,
    }
    return sorted(keep), delete, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not HISTORY.is_dir():
        print("no history directory; nothing to compact")
        return 0
    _, delete, stats = plan(_qualifies())
    print(json.dumps(stats, indent=2, sort_keys=True))
    if not all(stats["invariants"].values()):
        print("FAIL: compaction would change P10 evidence; nothing deleted", file=sys.stderr)
        return 2
    if args.dry_run:
        print(f"dry run: would delete {len(delete)} files")
        return 0
    for path in delete:
        path.unlink()
    print(f"deleted {len(delete)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
