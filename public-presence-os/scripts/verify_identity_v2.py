from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from public_presence_os.identity_v2 import verify_local_font_paths  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify EDITORIAL_LEDGER_V2 exact local font bytes without network access.")
    parser.add_argument("--display", required=True)
    parser.add_argument("--editorial", required=True)
    parser.add_argument("--editorial-italic", required=True)
    parser.add_argument("--marginalia", required=True)
    args = parser.parse_args()
    result = verify_local_font_paths({
        "DISPLAY": args.display,
        "EDITORIAL": args.editorial,
        "EDITORIAL_ITALIC": args.editorial_italic,
        "MARGINALIA": args.marginalia,
    })
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
