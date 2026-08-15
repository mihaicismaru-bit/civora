#!/usr/bin/env python3
"""Make PARTENER.EU decision-product timestamps deterministic.

The editorial pipeline is triggered by source changes, validation and schedules.
Using wall-clock time as the product version would create a new commit even when
no source changed and could form workflow/deploy loops. The generated timestamp
must therefore be the newest authoritative source snapshot time.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "ingest" / "build_decision_products.py"
text = PATH.read_text(encoding="utf-8")
changed = False

old = '''def main() -> int:
    generated_at = utc_now()
    p11 = load_p11()
    mipe = read_json(MIPE_PATH, {"items": []})
    afir = read_json(AFIR_PATH, {"items": []})
'''
new = '''def stable_generated_at(p11: dict[str, Any], mipe: dict[str, Any], afir: dict[str, Any]) -> str:
    """Return a deterministic product version from source snapshot times."""
    candidates = [
        p11.get("asOf"),
        (mipe.get("lastRun") or {}).get("observedAt"),
        mipe.get("observedAt"),
        afir.get("observedAt"),
    ]
    for item in mipe.get("items") or []:
        candidates.append(item.get("observedAt") or item.get("date"))
    for item in afir.get("items") or []:
        candidates.append(item.get("observedAt"))

    parsed: list[dt.datetime] = []
    for value in candidates:
        if not value:
            continue
        try:
            stamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=dt.timezone.utc)
            parsed.append(stamp.astimezone(dt.timezone.utc))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return "1970-01-01T00:00:00Z"
    return max(parsed).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    p11 = load_p11()
    mipe = read_json(MIPE_PATH, {"items": []})
    afir = read_json(AFIR_PATH, {"items": []})
    generated_at = stable_generated_at(p11, mipe, afir)
'''

if new in text:
    print("Decision products are already deterministic")
elif old in text:
    PATH.write_text(text.replace(old, new, 1), encoding="utf-8")
    changed = True
    print("Decision-product source timestamp determinism applied")
else:
    raise SystemExit("Expected decision-product main block not found; refusing blind edit")

if not changed:
    raise SystemExit(0)
