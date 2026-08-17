#!/usr/bin/env python3
"""Regression gate for automated PARTENER.EU decision products."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
JS = ROOT / "partener-eu" / "web" / "decision-products.js"
UI = ROOT / "partener-eu" / "web" / "decision-intelligence-v2.js"
CSS = ROOT / "partener-eu" / "web" / "decision-intelligence-v2.css"
P11 = ROOT / "partener-eu" / "web" / "p11-public-data.js"
CRITICAL = {"status", "deadline", "beneficiaries", "eligibility", "grant", "budget", "scoring"}
GENERIC_TITLES = {
    "arhiva anunturilor de primire a proiectelor aferente perioadei 2023 2027",
    "sesiuni primire proiecte",
    "contor fonduri disponibile",
}
NON_APPLICANT_MARKERS = (
    "target scope",
    "target group",
    "grup tinta",
    "public tinta",
    "beneficiari finali",
    "persoane vizate",
    "excluded",
    "excluderi",
    "ineligible",
    "neeligibil",
    "nu sunt eligibile",
    "nu este eligibil",
    "nu pot aplica",
)


def norm(value: object) -> str:
    text = "".join(ch for ch in unicodedata.normalize("NFKD", str(value or "")) if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9]+", " ", text).lower()).strip()


def collect_strings(value: Any) -> list[str]:
    out: list[str] = []

    def walk(node: Any) -> None:
        if node in (None, "", [], {}):
            return
        if isinstance(node, str):
            text = re.sub(r"\s+", " ", node).strip()
            if text:
                out.append(text)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if isinstance(node, dict):
            for item in node.values():
                walk(item)

    walk(value)
    return out


def fact_authorized(item: dict[str, Any], fact: str) -> bool:
    if fact not in set(item.get("verifiedFactClasses") or []):
        return False
    return any(
        fact in set(row.get("supportedFactClasses") or []) and row.get("sourceUrl")
        for row in item.get("verificationEvidence") or []
        if isinstance(row, dict)
    )


def non_applicant(value: str) -> bool:
    folded = norm(value)
    return any(norm(marker) in folded for marker in NON_APPLICANT_MARKERS)


def expected_applicants(item: dict[str, Any] | None) -> list[str]:
    if not item or not fact_authorized(item, "beneficiaries"):
        return []
    rows = collect_strings((item.get("materialFacts") or {}).get("beneficiaries"))
    return [row for row in rows if not non_applicant(row)]


def entity_key(value: str) -> str:
    text = norm(value)
    prefixes = (
        "solicitanti eligibili",
        "solicitant eligibil",
        "eligible applicants",
        "eligible applicant",
        "partener institutional obligatoriu",
        "mandatory institutional partner",
        "partener institutional",
        "institutional partner",
        "solicitanti",
        "solicitant",
        "applicants",
        "applicant",
    )
    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


assert DATA.exists(), "decision_products.json missing"
assert JS.exists(), "decision-products.js missing"
assert UI.exists(), "decision-intelligence-v2.js missing"
assert CSS.exists(), "decision-intelligence-v2.css missing"

payload = json.loads(DATA.read_text(encoding="utf-8"))
assert payload.get("schemaVersion") == 1
policy = payload.get("policy", {})
assert policy.get("rawIngestionRowsAreNews") is False
assert policy.get("everyIdentifiedCallGetsDossier") is True
assert policy.get("failClosed") is True
assert policy.get("whoCanApplyOfficialGuideOnly") is True
assert policy.get("executiveSummaryRequiredForEveryDossier") is True
assert policy.get("executiveSummarySchemaVersion") == 1
assert policy.get("unknownExecutiveFactsRemainVisible") is True

dossiers = payload.get("dossiers") or []
news = payload.get("news") or []
assert dossiers, "no dossiers generated"
assert len({row["id"] for row in dossiers}) == len(dossiers), "duplicate dossier IDs"
assert not ({norm(row.get("title")) for row in dossiers} & GENERIC_TITLES), "generic AFIR source/index page published as funding dossier"

# The generic AFIR intervention label must be merged into the canonical energy
# opportunity instead of creating a competing dossier with the same meaning.
schema_energy = [row for row in dossiers if norm(row.get("title")) == "schema de energie"]
assert not schema_energy, "generic Schema de Energie duplicate was not merged into the canonical dossier"

match = re.search(r"window\.PARTENER_P11\s*=\s*(\{.*\})\s*;?\s*$", P11.read_text(encoding="utf-8"), re.S)
assert match, "cannot parse P11 projection"
p11 = json.loads(match.group(1))
p11_rows = {row["id"]: row for row in p11.get("opportunities") or [] if row.get("id")}
p11_ids = set(p11_rows)
dossier_ids = {row["id"] for row in dossiers}
missing = sorted(p11_ids - dossier_ids)
assert not missing, f"P11 opportunities without dossiers: {missing[:10]}"

for dossier in dossiers:
    assert dossier.get("title"), dossier.get("id")
    assert dossier.get("decision"), dossier.get("id")
    assert dossier.get("decisionAction"), dossier.get("id")
    assert dossier.get("standfirst"), dossier.get("id")
    assert len(dossier.get("quickFacts") or []) >= 5, dossier.get("id")
    assert len(dossier.get("sections") or []) >= 10, dossier.get("id")

    sections = dossier.get("sections") or []
    assert sections[0].get("title") == "Rezumat executiv", f"executive summary is not first in {dossier.get('id')}"
    assert sections[0].get("schemaVersion") == 1, dossier.get("id")
    executive = dossier.get("executiveSummary") or {}
    for key in (
        "status", "opens", "closes", "applicants", "targetGroup", "activities",
        "callBudget", "projectValue", "cofinancing", "region", "sourcePolicy",
    ):
        assert key in executive, f"executive summary missing {key}: {dossier.get('id')}"
    assert executive.get("sourcePolicy") == "GUIDE_EXPLICIT_ONLY", dossier.get("id")
    summary_text = "\n".join(sections[0].get("items") or [])
    for token in (
        "Deschidere:", "Închidere:", "Cine poate aplica:", "Activități finanțate:",
        "Valoarea apelului:", "Valoarea proiectului individual:",
        "Cofinanțare / contribuție proprie:",
    ):
        assert token in summary_text, f"executive summary missing {token}: {dossier.get('id')}"

    who = next((row for row in sections if row.get("title") == "Cine poate aplica"), None)
    assert who, f"who-can-apply section missing: {dossier.get('id')}"
    assert who.get("policy") == "GUIDE_EXPLICIT_ONLY", dossier.get("id")
    who_items = [str(row) for row in who.get("items") or []]
    actual_applicants = [row for row in who_items if not norm(row).startswith("neconfirmat")]
    for row in actual_applicants:
        assert not non_applicant(row), f"non-applicant leaked into who-can-apply: {dossier.get('id')} -> {row}"
    if actual_applicants:
        assert {entity_key(row) for row in actual_applicants} == {
            entity_key(row) for row in dossier.get("audience") or []
        }, f"audience diverges from strict applicant list: {dossier.get('id')}"
    else:
        assert not dossier.get("audience"), f"unverified audience exposed on card: {dossier.get('id')}"

    source = p11_rows.get(dossier.get("id"))
    if source is not None:
        expected = expected_applicants(source)
        if expected:
            assert {entity_key(row) for row in actual_applicants} == {
                entity_key(row) for row in expected
            }, f"who-can-apply is not guide-only for {dossier.get('id')}"
            assert {entity_key(row) for row in executive.get("applicants") or []} == {
                entity_key(row) for row in expected
            }, f"executive applicant list diverges from guide for {dossier.get('id')}"
        elif not fact_authorized(source, "beneficiaries"):
            assert not actual_applicants, f"beneficiaries published without authorized evidence: {dossier.get('id')}"

    quality = dossier.get("quality") or {}
    assert quality.get("failClosed") is True
    assert quality.get("applicantListPolicy") == "GUIDE_EXPLICIT_ONLY"
    assert quality.get("executiveSummaryPresent") is True
    assert 0 <= quality.get("completeness", -1) <= 100

    sources = dossier.get("sources") or []
    verified = set(quality.get("verifiedFactClasses") or [])
    blocked = set(quality.get("blockedFactClasses") or [])
    if sources:
        for source_row in sources:
            assert source_row.get("url"), f"source without URL in {dossier.get('id')}"
    else:
        # A dossier may still exist as an explicit fail-closed shell when the
        # public projection does not expose its evidence links. In that state
        # no material fact may be presented as verified or actionable.
        assert dossier.get("publicationState") != "PUBLISHABLE", f"publishable dossier without provenance: {dossier.get('id')}"
        assert dossier.get("status") != "OPEN", f"OPEN dossier without provenance: {dossier.get('id')}"
        assert not (verified & CRITICAL), f"verified material facts without provenance: {dossier.get('id')}"
        assert blocked or quality.get("completeness", 100) == 0, f"unexplained provenance gap: {dossier.get('id')}"

    if dossier.get("status") == "OPEN":
        source_type = dossier.get("sourceType", "")
        assert sources, f"OPEN dossier without sources: {dossier.get('id')}"
        assert "status" in verified or source_type.endswith("PROVISIONAL"), f"OPEN without status evidence: {dossier.get('id')}"
    if dossier.get("sourceType", "").endswith("PROVISIONAL"):
        # Provisional source extraction may help preparation, but it is not
        # permitted to silently become an actionable OPEN verdict.
        assert dossier.get("status") != "OPEN", f"heuristic provisional dossier promoted to OPEN: {dossier.get('id')}"
        if quality.get("extractionMode"):
            assert quality.get("requiresMaterialFactReconciliation") is True
    for section in dossier.get("sections") or []:
        assert section.get("title")
        assert section.get("items"), f"empty section in {dossier.get('id')}: {section.get('title')}"

for story in news:
    assert story.get("headline")
    assert story.get("standfirst")
    assert story.get("meaning")
    assert story.get("actions"), story.get("id")
    assert story.get("source", {}).get("url"), story.get("id")
    assert story.get("utilityScore", 0) >= 60, story.get("id")
    assert not re.fullmatch(r".*actualizare oficială.*", story.get("headline", ""), re.I), story.get("headline")
    assert len(story.get("standfirst", "")) >= 60, f"thin news standfirst: {story.get('id')}"

coverage = payload.get("coverage") or {}
for source in ("p11", "mipe", "afir"):
    assert source in coverage
if coverage.get("mipe", {}).get("candidates", 0):
    assert coverage["mipe"].get("matched", 0) + coverage["mipe"].get("provisional", 0) == coverage["mipe"]["candidates"]
if coverage.get("afir", {}).get("candidates", 0):
    assert coverage["afir"].get("matched", 0) + coverage["afir"].get("provisional", 0) == coverage["afir"]["candidates"]
assert payload.get("qualityPass", {}).get("genericSourcePagesRemoved", 0) >= 0
assert payload.get("qualityPass", {}).get("executiveSummaryCoverage") == len(dossiers)
assert payload.get("qualityPass", {}).get("strictApplicantListCoverage") == len(dossiers)

js_text = JS.read_text(encoding="utf-8")
assert "window.PARTENER_DECISION_PRODUCTS=" in js_text
ui_text = UI.read_text(encoding="utf-8")
for token in ("Ce finanțare poți accesa", "Știri care explică", "Dosar complet", "Ce nu este confirmat"):
    assert token in ui_text, f"UI missing {token}"
css_text = CSS.read_text(encoding="utf-8")
for token in (".diDossierGrid", ".diNewsGrid", ".diDossierLayout", ".diQualityMeter"):
    assert token in css_text

print(json.dumps({
    "dossiers": len(dossiers),
    "news": len(news),
    "coverage": coverage,
    "qualityPass": payload.get("qualityPass"),
    "executiveSummaryCoverage": len(dossiers),
    "strictGuideOnlyApplicantLists": True,
}, ensure_ascii=False, indent=2))
