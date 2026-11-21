#!/usr/bin/env python3
"""Water4All 2026 Romania PDF semantic candidate; never an OPEN/publication writer.

Only reads a previously sealed Water4All original-PDF handoff. The official
multi-country annex is NOT a replacement for a verified Romanian national
information package. Candidate figures remain non-authorizing.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PRIMARY_PATH = ROOT / "partener-eu" / "ingest" / "water4all_2026_primary_documents.py"
PARSER = "WATER4ALL_2026_ROMANIA_ANNEX_CANDIDATE_V1"
SCHEMA = "PARTENER_WATER4ALL_ROMANIA_ANNEX_CANDIDATE_V1"
REQUIRED_FALSE = ("open_call_authorized", "publish_authorized", "distribution_authorized",
                  "eligibility_authorized", "budget_authorized",
                  "national_package_reconciled", "semantic_admission_authorized")


def primary_module():
    spec = importlib.util.spec_from_file_location("water4all_primary", PRIMARY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def extract_candidate(pages):
    """Bound extraction to an actual versioned PDF, not neighboring-country rows."""
    if not isinstance(pages, list) or not (50 <= len(pages) <= 150):
        raise ValueError("unexpected national-regulations PDF page count")
    cover = clean(pages[0])
    if not all(marker in cover for marker in
               ("National/Regional Regulations", "2026 Joint Transnational Call",
                "Version 8.0", "28.10.2026")):
        raise ValueError("official 2026 annex identity/version not confirmed")
    matches = []
    for index in range(45, min(52, len(pages) - 1)):
        text = clean(pages[index])
        if re.search(r"\bROMANIA\s+Funding Organisation\s*:?\s*UEFISCDI\b", text, re.I):
            matches.append(index)
    if len(matches) != 1:
        raise ValueError("Romanian national section missing/ambiguous")
    index = matches[0]
    romania = clean(pages[index] + " " + pages[index + 1])
    if not re.search(r"\bSLOVAKIA\b", clean(pages[index + 2])):
        raise ValueError("national-section boundary has drifted")
    # The next country's page may never contaminate Romania's ceilings.
    romania = re.split(r"\bSLOVAKIA\b", romania, maxsplit=1)[0]
    needed = ("Joint Transnational Call (JTC)", "We do NOT fund the Early Career",
              "Topic 1:", "Topic 2:", "Topic 3:", "Topic 4:",
              "Funding Commitment", "Funding Organisation")
    if any(marker not in romania for marker in needed):
        raise ValueError("Romania modality/topics/authority not confirmed")
    collapsed = romania.replace(",", "").replace(" ", "").lower()
    if not all(number in collapsed for number in ("1000000eur", "250000eur", "200000eur")):
        raise ValueError("national ceilings not all confirmed")
    if not re.search(r"250[,\s]*000\s*EUR.{0,180}Romanian institution is the", romania, re.I):
        raise ValueError("coordinator ceiling not anchored to Romanian row")
    if not re.search(r"200[,\s]*000\s*EUR.{0,180}Romanian institution is not", romania, re.I):
        raise ValueError("non-coordinator ceiling not anchored to Romanian row")
    # A negative funding modality is an important Romanian specificity; no
    # public eligibility inference from checked boxes is made here.
    return {
        "pdf_version_observed": "8.0",
        "pdf_version_date_observed": "2026-10-28",
        "romania_page_zero_based": index,
        "national_funder_candidate": "UEFISCDI",
        "ecr_funded_candidate": False,
        "regular_jtc_present_candidate": True,
        "topic_count_candidate": 4,
        "national_total_commitment_eur_candidate": 1000000,
        "romania_coordinator_ceiling_eur_candidate": 250000,
        "romania_noncoordinator_ceiling_eur_candidate": 200000,
    }


def observed_pages(pdf_raw):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("pypdf dependency unavailable; refuse semantic inference") from exc
    import io
    reader = PdfReader(io.BytesIO(pdf_raw), strict=True)
    if reader.is_encrypted:
        raise ValueError("encrypted national-regulations PDF")
    return [page.extract_text() or "" for page in reader.pages]


def build(source_dir):
    parent = primary_module()
    state = parent.replay(source_dir)
    if state["status"] != "BOTH_PDFS_RAW_REPLAY_VERIFIED_NOT_RECONCILED":
        raise ValueError("both immutable PDF originals required")
    handoff = parent.strict_json((source_dir / "handoff.json").read_bytes())
    row = next((r for r in handoff["receipts"]
                if r["document_id"] == "NATIONAL_REGULATIONS"), None)
    if not row or row["document_version_hint_unverified"] != "V8_2026-10-28":
        raise ValueError("expected unverified version hint missing")
    raw = (source_dir / "raw" / "NATIONAL_REGULATIONS.pdf").read_bytes()
    if digest(raw) != row["raw_sha256"]:
        raise ValueError("primary PDF SHA mismatch")
    candidate = extract_candidate(observed_pages(raw))
    payload = {
        "schema": SCHEMA, "parser_version": PARSER,
        "run_id": handoff["run_id"], "fetched_at": row["fetched_at"],
        "source_url": row["final_url"], "source_raw_sha256": row["raw_sha256"],
        "source_handoff_sha256": handoff["handoff_sha256"],
        "source_family": row["source_family"], "programme_family": row["programme_family"],
        "authority_class": row["authority_class"],
        "observation_state": "ROMANIA_V8_ANNEX_CANDIDATE_NATIONAL_PACKAGE_PENDING",
        "candidate": candidate,
        "requires": ["obtain_call_specific_romanian_information_package",
                     "validate_current_national_requirements_and_rates",
                     "reconcile_european_and_national_stages",
                     "independent_review_before_material_admission"],
        "publication_effect": "NONE",
        **{key: False for key in REQUIRED_FALSE},
    }
    payload["candidate_sha256"] = digest(canonical(payload))
    return payload


def replay(source_dir, out):
    if not out.is_dir() or out.is_symlink() or {p.name for p in out.iterdir()} != {"candidate.json"}:
        raise ValueError("candidate checkpoint fileset mismatch")
    path = out / "candidate.json"
    if path.is_symlink():
        raise ValueError("candidate symlink refused")
    parent = primary_module()
    recorded = parent.strict_json(path.read_bytes())
    expected = build(source_dir)
    if recorded != expected:
        raise ValueError("candidate source-bound replay mismatch")
    return {"status": "ROMANIA_PDF_RULES_CANDIDATE_REPLAY_VERIFIED_NOT_ADMITTED",
            "source_raw_sha256": expected["source_raw_sha256"],
            "open_call_authorized": False, "publication_effect": "NONE"}


def seal(source_dir, out):
    payload = build(source_dir)
    if out.exists() or out.is_symlink():
        raise ValueError("candidate destination already exists")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="partener-water4all-romania-", dir=out.parent) as temp:
        stage = Path(temp)
        (stage / "candidate.json").write_bytes(canonical(payload) + b"\n")
        stage.rename(out)
    return replay(source_dir, out)


def main():
    args_parser = argparse.ArgumentParser()
    args_parser.add_argument("--source-dir", type=Path, required=True)
    args_parser.add_argument("--out", type=Path)
    args_parser.add_argument("--replay-dir", type=Path)
    args = args_parser.parse_args()
    if bool(args.out) == bool(args.replay_dir):
        args_parser.error("exactly one of --out / --replay-dir required")
    result = replay(args.source_dir, args.replay_dir) if args.replay_dir else seal(args.source_dir, args.out)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
