from __future__ import annotations

from pathlib import Path
import json

from public_presence_os.preflight import preflight_report


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = preflight_report(root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
