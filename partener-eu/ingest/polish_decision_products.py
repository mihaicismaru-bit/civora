#!/usr/bin/env python3
"""Editorial quality pass for generated PARTENER.EU decision products.

This pass runs entirely in the site engine. It removes generic source-index
pages from the opportunity layer, merges duplicate ingested pages into their
canonical dossiers, and turns official page text into structured, explicitly
labelled dossier evidence. It never upgrades status, deadline or eligibility
without authoritative evidence.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
AFIR = ROOT / "partener-eu" / "ingest" / "state" / "afir_corpus.json"
MIPE = ROOT / "partener-eu" / "ingest" / "state" / "mipe_state.json"
OUT_JS = ROOT / "partener-eu" / "web" / "decision-products.js"

GENERIC_SOURCE_TITLES = (
    "arhiva anunturilor de primire",
    "sesiuni primire proiecte",
    "contor fonduri disponibile",
    "detalii mentiuni si informatii derulare sesiuni",
    "info la zi",
    "finantare portalul afir",
)

CUES = {
    "Cine poate aplica": (
        "beneficiar", "beneficiari", "solicitant", "solicitanți", "solicitanti",
        "eligibil", "pot depune", "se adresează", "se adreseaza", "fermieri",
        "întreprinderi", "intreprinderi", "organizații", "organizatii",
    ),
    "Ce finanțează și în ce condiții": (
        "se finanțează", "se finanteaza", "investiții", "investitii", "activități",
        "activitati", "sprijin pentru", "obiectivul intervenției", "obiectivul interventiei",
        "operațiuni", "operatiuni", "achiziția", "achizitia", "modernizarea",
    ),
    "Costuri, cofinanțare și ajutor de stat": (
        "euro", " eur", "lei", "ron", "intensitate", "cofinanț", "cofinant",
        "contribuție proprie", "contributie proprie", "ajutor de stat", "de minimis",
        "valoarea sprijinului", "procent",
    ),
    "Documente de pregătit": (
        "document", "anexa", "anexă", "adeverință", "adeverinta", "certificat",
        "declarație", "declaratie", "studiu", "proiecții financiare", "proiect tehnic",
    ),
    "Cum se punctează": (
        "punctaj", "criteriu", "criterii", "prag de calitate", "selecție", "selectie",
        "departajare", "grila de evaluare", "fișa de evaluare", "fisa de evaluare",
    ),
    "Indicatori și obligații": (
        "indicator", "durabilitate", "sustenabilitate", "obligația", "obligatia",
        "trebuie menținut", "trebuie mentinut", "implementare", "monitorizare",
        "locuri de muncă", "locuri de munca", "termen de execuție", "termen de executie",
    ),
    "Riscuri de respingere sau implementare": (
        "nu sunt eligibile", "nu este eligibil", "resping", "exclud", "condiții artificiale",
        "conditii artificiale", "risc", "interzis", "incompatibil", "dublă finanțare",
        "dubla finantare", "nerespectarea",
    ),
}

DATE_RE = re.compile(
    r"\b(?:[0-3]?\d[./-][01]?\d[./-]20\d{2}|[0-3]?\d\s+(?:ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+20\d{2})\b",
    re.I,
)
MONEY_RE = re.compile(r"\b(?:\d[\d .,'’]*)(?:\s*)(?:euro|eur|lei|ron)\b", re.I)
PERCENT_RE = re.compile(r"\b\d{1,3}(?:[.,]\d+)?\s*%")


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def norm(value: Any) -> str:
    text = "".join(ch for ch in unicodedata.normalize("NFKD", str(value or "")) if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).lower()
    return re.sub(r"\s+", " ", text).strip()


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def section_map(dossier: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row.get("title"): row for row in dossier.get("sections") or [] if row.get("title")}


def sentences(text: str) -> list[str]:
    value = clean(text)
    if not value:
        return []
    # Official pages often flatten headings and bullets. Split on punctuation,
    # bullet glyphs and repeated heading separators, then retain decision-useful
    # chunks rather than navigation fragments.
    chunks = re.split(r"(?<=[.!?;])\s+|\s*[•●▪►]\s*|\s{2,}|\s+\|\s+", value)
    out: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        chunk = clean(chunk).strip(" -–—:;")
        normalized = norm(chunk)
        if len(chunk) < 45 or len(chunk) > 650:
            continue
        if any(token in normalized[:120] for token in ("acasa minister despre minister", "cookie", "politica de confidentialitate", "meniu principal")):
            continue
        key = normalized[:260]
        if key in seen:
            continue
        seen.add(key)
        out.append(chunk)
    return out


def cue_extract(text: str, cues: Iterable[str], limit: int = 8) -> list[str]:
    normalized_cues = [norm(cue) for cue in cues]
    scored: list[tuple[int, str]] = []
    for sentence in sentences(text):
        value = norm(sentence)
        hits = sum(1 for cue in normalized_cues if cue in value)
        if not hits:
            continue
        # Prefer sentences that contain a number, a legal condition or a strong
        # eligibility/action verb; these are more decision-useful than headings.
        bonus = 2 if re.search(r"\d", sentence) else 0
        bonus += 1 if any(token in value for token in ("trebuie", "obligator", "minimum", "maximum", "exclus", "eligibil")) else 0
        scored.append((hits * 10 + bonus, sentence))
    scored.sort(key=lambda row: (-row[0], len(row[1])))
    return [sentence for _score, sentence in scored[:limit]]


def source_item_for(dossier: dict[str, Any], source_by_url: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for source in dossier.get("sources") or []:
        item = source_by_url.get(source.get("url"))
        if item:
            return item
    return None


def source_urls(dossier: dict[str, Any]) -> set[str]:
    return {source.get("url") for source in dossier.get("sources") or [] if source.get("url")}


def explicit_code(dossier: dict[str, Any]) -> str:
    code = norm(dossier.get("code"))
    return "" if code in {"", "—"} else code


def likely_duplicate(provisional: dict[str, Any], canonical: dict[str, Any]) -> bool:
    if provisional.get("sourceType", "").endswith("PROVISIONAL") is False:
        return False
    if source_urls(provisional) & source_urls(canonical):
        return True
    code_a, code_b = explicit_code(provisional), explicit_code(canonical)
    if code_a and code_b and code_a == code_b:
        return True
    a, b = norm(provisional.get("title")), norm(canonical.get("title"))
    if a == "schema de energie" and "energie electrica" in b and "autoconsum" in b:
        return True
    if "investalim" in a and "investalim" in b:
        return True
    return False


def merge_dossier(target: dict[str, Any], source: dict[str, Any]) -> None:
    existing = source_urls(target)
    for item in source.get("sources") or []:
        if item.get("url") and item.get("url") not in existing:
            target.setdefault("sources", []).append(item)
            existing.add(item["url"])
    timeline_keys = {(row.get("date"), row.get("kind"), row.get("text")) for row in target.get("timeline") or []}
    for row in source.get("timeline") or []:
        key = (row.get("date"), row.get("kind"), row.get("text"))
        if key not in timeline_keys:
            target.setdefault("timeline", []).append(row)
            timeline_keys.add(key)
    target.setdefault("sourceLinks", []).extend(source.get("sourceLinks") or [])


def generic_source_page(dossier: dict[str, Any]) -> bool:
    if not dossier.get("sourceType", "").endswith("PROVISIONAL"):
        return False
    title = norm(dossier.get("title"))
    return any(token in title for token in GENERIC_SOURCE_TITLES)


def update_fact(dossier: dict[str, Any], label: str, value: str, confidence: str) -> None:
    if not value:
        return
    for row in dossier.get("quickFacts") or []:
        if row.get("label") == label and row.get("value") in {None, "", "Neconfirmat", "În verificare"}:
            row["value"] = value[:240]
            row["confidence"] = confidence
            return


def enrich_provisional(dossier: dict[str, Any], item: dict[str, Any]) -> None:
    text = clean(item.get("textPreview") or item.get("summary"))
    docs = item.get("documentLinks") or item.get("documents") or []
    sections = section_map(dossier)
    filled_categories = 0

    for title, cues in CUES.items():
        extracted = cue_extract(text, cues)
        if title == "Documente de pregătit":
            extracted = [clean(doc.get("name") or doc.get("url")) for doc in docs if isinstance(doc, dict)] + extracted
        extracted = list(dict.fromkeys(row for row in extracted if row))[:12]
        if not extracted:
            continue
        filled_categories += 1
        target = sections.get(title)
        if not target:
            continue
        target["items"] = [f"Extras din sursa oficială: {row}" for row in extracted]
        target["empty"] = False

    meaningful = [row for row in sentences(text) if any(token in norm(row) for token in ("finant", "eligibil", "beneficiar", "investit", "sprijin"))]
    if meaningful:
        dossier["standfirst"] = f"{dossier.get('title')}. {meaningful[0][:720]}"

    date_rows = [row for row in sentences(text) if DATE_RE.search(row) and any(token in norm(row) for token in ("depun", "sesiun", "termen", "incep", "final"))]
    money_rows = [row for row in sentences(text) if MONEY_RE.search(row) and any(token in norm(row) for token in ("sprijin", "finant", "valoare", "buget", "euro", "lei"))]
    percent_rows = [row for row in sentences(text) if PERCENT_RE.search(row) and any(token in norm(row) for token in ("intensitate", "cofinant", "contribut", "sprijin"))]
    if date_rows:
        update_fact(dossier, "Termen", date_rows[0], "EXTRACTED_OFFICIAL_SOURCE_REQUIRES_RECONCILIATION")
    if money_rows:
        update_fact(dossier, "Grant", money_rows[0], "EXTRACTED_OFFICIAL_SOURCE_REQUIRES_RECONCILIATION")
    if percent_rows:
        update_fact(dossier, "Contribuție proprie", percent_rows[0], "EXTRACTED_OFFICIAL_SOURCE_REQUIRES_RECONCILIATION")
    update_fact(dossier, "Documente găsite", str(len(docs)), "SYSTEM")

    # A provisional dossier may become rich enough for preparation, but never
    # publishable/OPEN solely because text was heuristically extracted.
    completeness = min(68, 14 + filled_categories * 8 + min(12, len(docs)))
    dossier.setdefault("quality", {})["completeness"] = max(dossier.get("quality", {}).get("completeness", 0), completeness)
    dossier["quality"]["extractionMode"] = "OFFICIAL_SOURCE_SEMANTIC_EXTRACTION"
    dossier["quality"]["requiresMaterialFactReconciliation"] = True
    dossier["status"] = "REVIEW" if dossier.get("status") == "OPEN" else dossier.get("status", "REVIEW")
    dossier["statusLabel"] = "ÎN VERIFICARE" if dossier.get("status") == "REVIEW" else dossier.get("statusLabel")
    dossier["decision"] = "VERIFY"
    dossier["decisionAction"] = "Folosește informațiile extrase pentru pregătire, dar confirmă faptele materiale în ghidul și anunțul oficial aplicabile."


def main() -> int:
    products = load(PRODUCTS, {})
    afir = load(AFIR, {"items": []})
    mipe = load(MIPE, {"items": []})
    source_by_url = {
        item.get("url"): item
        for item in [*(afir.get("items") or []), *(mipe.get("items") or [])]
        if item.get("url")
    }

    dossiers = products.get("dossiers") or []
    canonicals = [row for row in dossiers if not row.get("sourceType", "").endswith("PROVISIONAL")]
    provisional = [row for row in dossiers if row.get("sourceType", "").endswith("PROVISIONAL")]
    removed_generic: list[str] = []
    merged_duplicates: list[str] = []
    retained: list[dict[str, Any]] = []

    for dossier in provisional:
        if generic_source_page(dossier):
            removed_generic.append(dossier.get("id"))
            continue
        duplicate = next((candidate for candidate in canonicals if likely_duplicate(dossier, candidate)), None)
        if duplicate:
            merge_dossier(duplicate, dossier)
            merged_duplicates.append(dossier.get("id"))
            continue
        item = source_item_for(dossier, source_by_url)
        if item:
            enrich_provisional(dossier, item)
        retained.append(dossier)

    dossiers = [*canonicals, *retained]
    rank = {"OPEN": 0, "EXPECTED": 1, "PUBLIC_CONSULTATION": 2, "REVIEW": 3, "CLOSED": 6}
    dossiers.sort(key=lambda row: (rank.get(row.get("status"), 4), -(row.get("quality", {}).get("completeness") or 0), row.get("title") or ""))
    valid_ids = {row.get("id") for row in dossiers}
    news = [row for row in products.get("news") or [] if not row.get("dossierId") or row.get("dossierId") in valid_ids]

    products["dossiers"] = dossiers
    products["news"] = news
    products.setdefault("qualityPass", {}).update({
        "genericSourcePagesRemoved": len(removed_generic),
        "duplicateDossiersMerged": len(merged_duplicates),
        "semanticProvisionalDossiers": sum(1 for row in retained if row.get("quality", {}).get("extractionMode")),
        "removedIds": removed_generic,
        "mergedIds": merged_duplicates,
    })
    products.setdefault("coverage", {}).setdefault("afir", {})["excludedSourcePages"] = len(removed_generic)
    products["coverage"]["afir"]["mergedDuplicates"] = len(merged_duplicates)
    products["coverage"]["afir"]["publishedDossiers"] = sum(1 for row in dossiers if row.get("sourceType", "").startswith("AFIR_") or any("afir.ro" in str(source.get("url")) for source in row.get("sources") or []))
    products.setdefault("summary", {}).update({
        "dossierCount": len(dossiers),
        "openCount": sum(1 for row in dossiers if row.get("status") == "OPEN"),
        "prepareCount": sum(1 for row in dossiers if row.get("status") in {"EXPECTED", "PUBLIC_CONSULTATION", "REVIEW"}),
        "newsCount": len(news),
        "highCompletenessCount": sum(1 for row in dossiers if row.get("quality", {}).get("completeness", 0) >= 70),
    })
    products["home"] = {
        "openDossierIds": [row["id"] for row in dossiers if row.get("status") == "OPEN" and row.get("quality", {}).get("completeness", 0) >= 40][:8],
        "prepareDossierIds": [row["id"] for row in dossiers if row.get("status") in {"EXPECTED", "PUBLIC_CONSULTATION", "REVIEW"}][:8],
        "changeNewsIds": [row["id"] for row in news[:8]],
    }

    PRODUCTS.write_text(json.dumps(products, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text(
        "window.PARTENER_DECISION_PRODUCTS="
        + json.dumps(products, ensure_ascii=False, separators=(",", ":"))
        + ";\nwindow.PARTENER_DATA=window.PARTENER_DATA||{};\n"
        + "window.PARTENER_DATA.decisionProducts=window.PARTENER_DECISION_PRODUCTS;\n",
        encoding="utf-8",
    )
    print(json.dumps({"summary": products["summary"], "qualityPass": products["qualityPass"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
