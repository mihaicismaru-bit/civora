#!/usr/bin/env python3
"""Build the fail-closed browser projection from the canonical P11 bundle."""
from __future__ import annotations

import json
import os
import pathlib
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "p11" / "opportunity_bundle.json"
OUTPUT = ROOT / "web" / "p11-public-data.js"


def atomic_text(path: pathlib.Path, value: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build(bundle: dict) -> dict:
    evidence = {row["evidence_id"]: row for row in bundle["evidence"]}
    projected = []
    for opportunity in bundle["opportunities"]:
        fact_evidence = opportunity.get("fact_evidence") or {}
        verified_fact_classes = sorted(
            fact_class for fact_class, refs in fact_evidence.items()
            if any(
                evidence.get(ref, {}).get("semantic_verdict") == "VERIFIED"
                and evidence.get(ref, {}).get("source_tier") in {"T1", "T1B"}
                and fact_class in evidence.get(ref, {}).get("supports_fact_classes", [])
                for ref in refs
            )
        )
        projected.append({
            "id": opportunity["opportunity_id"],
            "title": opportunity["title"],
            "programme": opportunity.get("programme"),
            "code": opportunity.get("code"),
            "status": opportunity["status"],
            "publicationState": opportunity["publication_state"],
            "materialFacts": opportunity.get("material_facts") or {},
            "verifiedFactClasses": verified_fact_classes,
            "evidenceCount": len(opportunity.get("evidence_refs") or []),
        })
    return {
        "schemaVersion": 1,
        "asOf": bundle.get("as_of"),
        "policy": {
            "unverifiedMaterialFactsVisible": False,
            "automaticPublication": False,
        },
        "summary": {
            "opportunityCount": len(projected),
            "openVerifiedCount": sum(
                1 for row in projected
                if row["status"] == "OPEN" and {"status", "deadline"} <= set(row["verifiedFactClasses"])
            ),
            "publishableCount": sum(1 for row in projected if row["publicationState"] == "PUBLISHABLE"),
            "reviewCount": sum(1 for row in projected if row["publicationState"] != "PUBLISHABLE"),
        },
        "opportunities": projected,
    }


def main() -> int:
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    projection = build(bundle)
    payload = "window.PARTENER_P11=" + json.dumps(projection, ensure_ascii=False, separators=(",", ":")) + ";\n"
    atomic_text(OUTPUT, payload)
    print(json.dumps(projection["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
