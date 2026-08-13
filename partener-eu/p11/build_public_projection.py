#!/usr/bin/env python3
"""Build the fail-closed browser projection from the canonical P11 bundle."""
from __future__ import annotations

import argparse
import hashlib
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


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def render(projection: dict) -> str:
    return "window.PARTENER_P11=" + json.dumps(projection, ensure_ascii=False, separators=(",", ":")) + ";\n"


def parse_payload(value: str) -> dict:
    prefix = "window.PARTENER_P11="
    stripped = value.strip()
    if not stripped.startswith(prefix) or not stripped.endswith(";"):
        raise ValueError("public projection wrapper is invalid")
    parsed = json.loads(stripped[len(prefix):-1])
    if not isinstance(parsed, dict):
        raise ValueError("public projection object required")
    return parsed


def assert_artifact_current(path: pathlib.Path, expected: str) -> None:
    actual = path.read_text(encoding="utf-8")
    expected_projection = parse_payload(expected)
    actual_projection = parse_payload(actual)
    if actual_projection != expected_projection:
        raise ValueError(
            f"public projection drift: {path} "
            f"actual_sha256={digest(render(actual_projection))} "
            f"expected_sha256={digest(render(expected_projection))}"
        )


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    projection = build(bundle)
    payload = render(projection)
    if args.check:
        assert_artifact_current(OUTPUT, payload)
    else:
        atomic_text(OUTPUT, payload)
    print(json.dumps({**projection["summary"], "mode": "CHECK" if args.check else "WRITE"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
