#!/usr/bin/env python3
"""Hermetic adversarial Water4All 2026 Romania-only annex scope regressions."""
from __future__ import annotations
import importlib.util
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "ingest" / "water4all_2026_romania_rules.py"
spec = importlib.util.spec_from_file_location("romania_annex", FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def reject(pages, fragment):
    try:
        mod.extract_candidate(pages)
    except ValueError as exc:
        assert fragment.lower() in str(exc).lower(), str(exc)
    else:
        raise AssertionError("unverified Romanian fact was accepted")


def fixture():
    p = ["OTHER COUNTRY" for _ in range(72)]
    p[0] = "National/Regional Regulations 2026 Joint Transnational Call Version 8.0 (28.10.2026)"
    p[48] = """ROMANIA Funding Organisation: UEFISCDI
    Funded modalities Joint Transnational Call (JTC) Regular modality
    We do NOT fund the Early Career Researchers modality
    Eligible Institutions Topic 1: A Topic 2: B Topic 3: C Topic 4: D
    Funding Commitment 1,000,000 EUR
    Maximum Amount Per Proposal
    250,000 EUR for all romanian partners in case a Romanian institution is the Coordinator;
    200,000 EUR for all romanian partners in case a Romanian institution is not the Coordinator;"""
    p[49] = "Other Funding Criteria Relevant documents"
    p[50] = "SLOVAKIA"
    return p


def run():
    pages = fixture()
    data = mod.extract_candidate(pages)
    assert data["national_funder_candidate"] == "UEFISCDI"
    assert data["ecr_funded_candidate"] is False
    assert data["national_total_commitment_eur_candidate"] == 1000000
    assert data["romania_coordinator_ceiling_eur_candidate"] == 250000
    assert data["romania_noncoordinator_ceiling_eur_candidate"] == 200000
    assert data["romania_page_zero_based"] == 48
    assert len(mod.REQUIRED_FALSE) == 7
    p = fixture(); p[0] = p[0].replace("8.0", "7.0")
    reject(p, "identity/version")
    p = fixture(); p[48] = p[48].replace("ROMANIA", "POLAND", 1)
    reject(p, "section missing")
    p = fixture(); p[48] = p[48].replace("UEFISCDI", "NCBR")
    reject(p, "section missing")
    p = fixture(); p[48] = p[48].replace("We do NOT fund", "We fund")
    reject(p, "modality/topics")
    p = fixture(); p[48] = p[48].replace("250,000 EUR", "350,000 EUR")
    reject(p, "ceilings")
    p = fixture(); p[48] = p[48].replace("is not the Coordinator", "is the Coordinator")
    reject(p, "non-coordinator")
    p = fixture(); p[50] = "FRANCE"
    reject(p, "boundary")
    p = fixture(); p.insert(48, p[48])
    reject(p, "section")
    print("Water4All Romania national V8 PDF scope guards PASS (candidate-only, no OPEN/publication)")


if __name__ == "__main__":
    run()
