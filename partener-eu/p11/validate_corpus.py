#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re

from opportunity_contract import validate_bundle

ROOT = pathlib.Path(__file__).resolve().parent
PUBLIC_DATA = ROOT.parent / "web" / "data.js"
BUNDLE = ROOT / "opportunity_bundle.json"


def admitted_opportunity_ids() -> list[str]:
    result: list[str] = []
    for path in sorted(ROOT.glob("admission_batch_*.json")):
        result.extend(json.loads(path.read_text(encoding="utf-8"))["opportunity_ids"])
    return result


def public_opportunity_ids(bundle: dict | None = None) -> list[str]:
    if not PUBLIC_DATA.exists():
        if bundle is None:
            bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
        return list((bundle.get("source_snapshot") or {}).get("expected_public_ids") or [])
    text = PUBLIC_DATA.read_text(encoding="utf-8")
    calls = text.split("clients:", 1)[0]
    return re.findall(r"\bid:'([^']+)'", calls)


def main() -> int:
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    counts = validate_bundle(bundle)
    public_ids = public_opportunity_ids(bundle)
    canonical_ids = [x["opportunity_id"] for x in bundle["opportunities"]]
    admitted_ids = admitted_opportunity_ids()
    if canonical_ids[: len(public_ids)] != public_ids:
        raise SystemExit(f"canonical/public identity prefix mismatch: {canonical_ids!r} != {public_ids!r}")
    admitted_end = len(public_ids) + len(admitted_ids)
    if canonical_ids[len(public_ids) : admitted_end] != admitted_ids:
        raise SystemExit(f"canonical/admission suffix mismatch: {canonical_ids!r} != {admitted_ids!r}")
    resolved_ids = canonical_ids[admitted_end:]
    publishable = [x["opportunity_id"] for x in bundle["opportunities"] if x["publication_state"] == "PUBLISHABLE"]
    if set(publishable) - set(resolved_ids):
        raise SystemExit("only explicit resolution overlays may promote PUBLISHABLE opportunities")
    print(json.dumps({**counts, "static_public_identity_match": True, "admitted_batch_count": len(admitted_ids), "resolved_additions": resolved_ids, "publishable": len(publishable)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
