#!/usr/bin/env python3
"""Build evidence-bound VÂLCEA CLAR fact kernels from Council Watch.

v1 handles one high-value, deterministic pattern from the Râmnicu Vâlcea
adopted-HCL register: clusters of annual gambling-operation authorizations.

The builder never equates an annual authorization with a newly opened venue.
It requires the official adopted-decision register AND the official HTML
content for every decision in the cluster before the kernel can become
`verified`. DocManager/Lotus may expose the decision either as a direct `$FILE`
HTML attachment or as an intermediate document page; both are resolved without
leaving the official host. Partial evidence is persisted as `candidate_hold`
for later completion, never as a publishable story.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import council_watch_rm_valcea as council

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "editorial" / "fact_kernel_registry.json"
SOURCE_STATE = ROOT / "editorial" / "council_watch_rm_valcea_state.json"
BUILDER_ID = "council_fact_kernel_v1"
TZ_RO_OFFSET = timezone(timedelta(hours=3))
GAMBLING_RE = re.compile(r"jocuri\s+de\s+noroc|slot[ -]?machine|pariuri", re.I)
ANNUAL_AUTH_RE = re.compile(r"autoriza(?:t|ț)ie\s+anual(?:a|ă)|autorizatie\s+anuala", re.I)
COMPANY_RE = re.compile(
    r"(?:JOCURI\s+DE\s+NOROC|PARIURI(?:\s+IN\s+COTA\s+FIXA)?|SLOT[ -]?MACHINE)\s*"
    r"(?:-\s*(?:PARIURI(?:\s+IN\s+COTA\s+FIXA)?|SLOT[ -]?MACHINE)\s*)?"
    r"([A-ZĂÂÎȘȚ0-9.&'’\-]+(?:\s+[A-ZĂÂÎȘȚ0-9.&'’\-]+){0,2}\s+(?:SRL|SA))\b",
    re.I,
)


def now_local() -> datetime:
    return datetime.now(TZ_RO_OFFSET)


def load_optional(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def gambling_authorization(row: dict[str, Any]) -> bool:
    title = str(row.get("title") or "")
    return bool(GAMBLING_RE.search(title) and ANNUAL_AUTH_RE.search(title))


def newest_cluster(rows: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        day = str(row.get("decision_date") or "").strip()
        if day and gambling_authorization(row):
            grouped.setdefault(day, []).append(row)
    if not grouped:
        return None, []
    newest = max(grouped)
    return newest, sorted(grouped[newest], key=lambda row: int(row.get("decision_number") or 0), reverse=True)


def company_names(rows: list[dict[str, Any]]) -> list[str]:
    found: dict[str, str] = {}
    for row in rows:
        title = str(row.get("title") or "")
        for match in COMPANY_RE.finditer(title.upper()):
            value = re.sub(r"\s+", " ", match.group(1)).strip(" -")
            if value:
                found[value.casefold()] = value
    return sorted(found.values())


def _decision_key(label: str) -> tuple[int, str] | None:
    match = council.ATTACHMENT_LABEL.search(urllib.parse.unquote(label))
    if not match:
        return None
    day = council.iso_date(int(match.group("day")), match.group("month"))
    if not day:
        return None
    return int(match.group("number")), day


def _normalized_title(value: str) -> str:
    value = urllib.parse.unquote(str(value or ""))
    value = re.sub(r"\s+", " ", value).strip(" -|\t\r\n")
    return value.casefold()


def decision_attachments(register_url: str, register_body: str, rows: list[dict[str, Any]]) -> dict[int, str]:
    """Resolve direct attachment URLs and intermediate DocManager document URLs.

    The Lotus view is allowed two exact identity routes only:
    1. number + date encoded in anchor text/URL;
    2. exact normalized official decision title matching a parsed register row.
    No fuzzy title matching is used.
    """
    wanted = {(int(row.get("decision_number") or 0), str(row.get("decision_date") or "")) for row in rows}
    title_to_number = {
        _normalized_title(str(row.get("title") or "")): int(row.get("decision_number") or 0)
        for row in rows
        if str(row.get("title") or "").strip()
    }
    out: dict[int, str] = {}

    # Fast path: direct `$FILE/*.htm` links exposed by the view.
    direct = council.attachment_index(register_url, register_body)
    for (number, day), url in direct.items():
        if (number, day) in wanted:
            out[number] = url

    # Lotus views can instead expose an intermediate document URL. Prefer the
    # explicit number/date identity; if those fields are absent from the anchor,
    # use only an exact normalized title match against the already parsed T1 row.
    for link in council.parse_links(register_url, register_body):
        label = f"{link.get('text') or ''} {link.get('url') or ''}"
        key = _decision_key(label)
        if key and key in wanted and key[0] not in out:
            out[key[0]] = str(link["url"])
            continue
        exact_title = _normalized_title(str(link.get("text") or ""))
        number = title_to_number.get(exact_title)
        if number and number not in out:
            out[number] = str(link["url"])
    return out


def _semantic_document(url: str, result: dict[str, Any]) -> dict[str, Any] | None:
    if not result.get("ok"):
        return None
    text = council.to_text(str(result.get("body") or ""))
    compact = re.sub(r"\s+", " ", text)
    has_authorization = bool(ANNUAL_AUTH_RE.search(compact))
    has_gambling = bool(GAMBLING_RE.search(compact))
    articles = council.operative_articles(text)
    if not (has_authorization and has_gambling and articles):
        return None
    return {
        "url": str(result.get("url") or url),
        "http_status": result.get("status"),
        "source_sha256": result.get("sha256"),
        "operative_article_count": len(articles),
        "operative_article_sha256": [hashlib.sha256(article.encode("utf-8")).hexdigest() for article in articles[:8]],
    }


def verify_document(row: dict[str, Any], url: str) -> dict[str, Any]:
    result = council.fetch(url, timeout=18)
    base = {
        "decision_number": int(row.get("decision_number") or 0),
        "decision_date": row.get("decision_date"),
        "title": row.get("title"),
        "candidate_url": url,
        "error": result.get("error"),
    }
    semantic = _semantic_document(url, result)
    if semantic:
        return {**base, **semantic, "verified": True, "reason": "PASS"}

    # Intermediate DocManager page: follow only official-host HTML `$FILE`
    # children. `parse_links` already applies council.canonical_url host/path
    # restrictions, so this cannot become an open crawler.
    if result.get("ok"):
        child_links: list[str] = []
        for link in council.parse_links(str(result.get("url") or url), str(result.get("body") or "")):
            low = urllib.parse.unquote(str(link.get("url") or "")).lower()
            if "$file" in low and low.endswith((".htm", ".html")):
                child_links.append(str(link["url"]))
        for child_url in list(dict.fromkeys(child_links))[:4]:
            child = council.fetch(child_url, timeout=18)
            semantic = _semantic_document(child_url, child)
            if semantic:
                return {**base, **semantic, "verified": True, "reason": "PASS_VIA_OFFICIAL_ATTACHMENT"}

    return {
        **base,
        "url": str(result.get("url") or url),
        "http_status": result.get("status"),
        "source_sha256": result.get("sha256"),
        "verified": False,
        "reason": "OFFICIAL_DOCUMENT_UNREACHABLE" if not result.get("ok") else "OFFICIAL_DOCUMENT_SEMANTICS_INCOMPLETE",
    }


def source_row(name: str, url: str, *, sha256: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"name": name, "url": url, "tier": "T1"}
    if sha256:
        row["sha256"] = sha256
    return row


def build_gambling_kernel(state: dict[str, Any], *, live: bool) -> dict[str, Any] | None:
    latest = [row for row in state.get("latest_decisions") or [] if isinstance(row, dict)]
    cluster_date, rows = newest_cluster(latest)
    if not cluster_date or len(rows) < 3:
        return None

    register_url = str((state.get("source") or {}).get("url") or council.ADOPTED_VIEW)
    register_sha = str((state.get("register_health") or {}).get("source_sha256") or "") or None
    attachments: dict[int, str] = {}
    verification: list[dict[str, Any]] = []
    register_fetch_error: str | None = None

    if live:
        register = council.fetch(register_url, timeout=18)
        if register.get("ok"):
            attachments = decision_attachments(str(register.get("url") or register_url), str(register.get("body") or ""), rows)
            register_sha = str(register.get("sha256") or "") or register_sha
        else:
            register_fetch_error = str(register.get("error") or "REGISTER_FETCH_FAILED")

        with ThreadPoolExecutor(max_workers=6) as pool:
            future_map = {
                pool.submit(verify_document, row, attachments[number]): row
                for row in rows
                for number in [int(row.get("decision_number") or 0)]
                if number in attachments
            }
            for future in as_completed(future_map):
                verification.append(future.result())
        verification.sort(key=lambda row: int(row.get("decision_number") or 0), reverse=True)

    total = len(rows)
    verified_docs = [row for row in verification if row.get("verified") is True]
    verified_numbers = {int(row["decision_number"]) for row in verified_docs}
    missing_attachment_numbers = sorted(
        int(row.get("decision_number") or 0) for row in rows
        if int(row.get("decision_number") or 0) not in attachments
    ) if live else [int(row.get("decision_number") or 0) for row in rows]
    failed_document_numbers = sorted(
        int(row.get("decision_number") or 0) for row in rows
        if int(row.get("decision_number") or 0) in attachments
        and int(row.get("decision_number") or 0) not in verified_numbers
    ) if live else []

    evidence_complete = live and total > 0 and len(verified_docs) == total and not register_fetch_error
    companies = company_names(rows)
    count = total
    source_urls = [register_url] + [row["url"] for row in verified_docs]
    source_urls = list(dict.fromkeys(source_urls))
    sources = [source_row("Primăria Municipiului Râmnicu Vâlcea — registrul HCL adoptate", register_url, sha256=register_sha)]
    sources.extend(
        source_row(f"HCL Râmnicu Vâlcea nr. {row['decision_number']}/{cluster_date}", row["url"], sha256=row.get("source_sha256"))
        for row in verified_docs
    )

    headline = f"{count} hotărâri pentru autorizații anuale de jocuri de noroc în cea mai recentă serie analizată a Consiliului Local Râmnicu Vâlcea"
    dek = (
        f"În registrul oficial, {count} dintre cele mai recente 25 de hotărâri din {datetime.fromisoformat(cluster_date).strftime('%d.%m.%Y')} "
        "privesc autorizații anuale de funcționare pentru jocuri de noroc; ele nu sunt tratate automat drept tot atâtea săli noi."
    )
    operators = ", ".join(companies) if companies else "mai mulți operatori economici nominalizați în hotărârile oficiale"
    claim_refs = source_urls if evidence_complete else [register_url]

    fact_kernel = {
        "format_hint": "explainer",
        "headline": {"text": headline, "source_urls": claim_refs},
        "dek": {"text": dek, "source_urls": claim_refs},
        "claims": [
            {
                "id": "hcl-gambling-count",
                "role": "material_change",
                "kind": "fact",
                "text": f"În grupul celor mai recente 25 de hotărâri afișate în registrul oficial, {count} acte din {datetime.fromisoformat(cluster_date).strftime('%d.%m.%Y')} au ca obiect acordarea unei autorizații anuale de funcționare pentru jocuri de noroc.",
                "source_urls": claim_refs,
            },
            {
                "id": "hcl-gambling-operators",
                "role": "context",
                "kind": "documented_context",
                "text": f"Hotărârile din acest grup nominalizează {operators}; fiecare act este urmărit separat prin documentul oficial al hotărârii, nu doar prin titlul din registru.",
                "source_urls": claim_refs,
            },
            {
                "id": "hcl-gambling-not-new-halls",
                "role": "meaning",
                "kind": "reader_service",
                "text": "O autorizație anuală de funcționare nu este clasificată de VÂLCEA CLAR drept dovadă a deschiderii unei săli noi; pentru această concluzie este necesar istoricul fiecărui punct de lucru și al autorizațiilor sale.",
                "source_urls": claim_refs,
            },
        ],
    }

    first_seen = datetime.fromisoformat(cluster_date).replace(tzinfo=TZ_RO_OFFSET)
    valid_until = first_seen + timedelta(days=45)
    status = "verified" if evidence_complete else "candidate_hold"
    return {
        "id": f"rm-valcea-gambling-authorizations-{cluster_date.replace('-', '')}",
        "status": status,
        "section": "ADMINISTRAȚIE",
        "editorial_type": "explainer",
        "priority": 91,
        "confidence": 98 if evidence_complete else 0,
        "valid_from": first_seen.isoformat(),
        "valid_until": valid_until.replace(hour=23, minute=59, second=59).isoformat(),
        "slots": ["morning", "evening"],
        "headline": headline,
        "dek": dek,
        "paragraphs": [claim["text"] for claim in fact_kernel["claims"]],
        "material_fact_gate": "PASS_EXPLAINER_ONLY" if evidence_complete else "HOLD_DOCUMENT_CHAIN_INCOMPLETE",
        "sources": sources,
        "fact_kernel": fact_kernel,
        "kernel_provenance": {
            "builder_id": BUILDER_ID,
            "source_monitor": "council-watch-rm-valcea",
            "cluster_date": cluster_date,
            "register_url": register_url,
            "register_sha256": register_sha,
            "latest_decision_window": 25,
            "matching_decisions": total,
            "verified_official_documents": len(verified_docs),
            "coverage": round(len(verified_docs) / total, 6) if total else 0,
            "evidence_complete": evidence_complete,
            "register_fetch_error": register_fetch_error,
            "missing_attachment_decision_numbers": missing_attachment_numbers,
            "failed_document_decision_numbers": failed_document_numbers,
            "decision_numbers": [int(row.get("decision_number") or 0) for row in rows],
            "verification": verification,
            "never_infer_new_venue_from_annual_authorization": True,
        },
    }


def build_registry(*, live: bool) -> dict[str, Any]:
    state = load_optional(SOURCE_STATE)
    if not state:
        state = council.build_state() if live else {}
    facts: list[dict[str, Any]] = []
    if state:
        gambling = build_gambling_kernel(state, live=live)
        if gambling:
            facts.append(gambling)
    document = {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "product": "VÂLCEA CLAR generated fact kernel registry",
        "builder_id": BUILDER_ID,
        "generated_at": now_local().isoformat(timespec="seconds"),
        "mode": "LIVE_DOCUMENT_VERIFICATION" if live else "OFFLINE_STATE_REVIEW",
        "facts": facts,
        "stats": {
            "kernel_count": len(facts),
            "verified": sum(1 for fact in facts if fact.get("status") == "verified"),
            "held": sum(1 for fact in facts if fact.get("status") != "verified"),
        },
        "policy": {
            "monitor_signal_is_not_fact": True,
            "official_decision_text_required_for_result_claim": True,
            "partial_document_coverage_publishable": False,
            "annual_authorization_is_new_venue": False,
            "writer_claim_level_provenance_required": True,
            "publication_authority": "ONLY_VERIFIED_KERNELS_THROUGH_NORMAL_STORY_GATE",
        },
    }
    document["registry_fingerprint_sha256"] = digest({"facts": facts, "policy": document["policy"]})
    return document


def self_test() -> int:
    sample = {
        "source": {"url": council.ADOPTED_VIEW, "tier": "T1"},
        "register_health": {"source_sha256": "abc"},
        "latest_decisions": [
            {"decision_number": 304, "decision_date": "2026-07-23", "title": "acordare autorizatie anuala de functionare slot machine pentru jocuri de noroc CARADUNE SRL strada Lucian Blaga nr 1A"},
            {"decision_number": 303, "decision_date": "2026-07-23", "title": "acordare autorizatie anuala de functionare pentru jocuri de noroc CARADUNE SRL strada Florilor nr 22"},
            {"decision_number": 302, "decision_date": "2026-07-23", "title": "acordare autorizatie anuala de functionare pentru jocuri de noroc SUPERBET RETAIL SA strada Test nr 1"},
            {"decision_number": 299, "decision_date": "2026-07-23", "title": "aprobare raport activitate"},
        ],
    }
    day, rows = newest_cluster(sample["latest_decisions"])
    assert day == "2026-07-23" and len(rows) == 3
    assert company_names(rows) == ["CARADUNE SRL", "SUPERBET RETAIL SA"]
    candidate = build_gambling_kernel(sample, live=False)
    assert candidate is not None
    assert candidate["status"] == "candidate_hold"
    assert candidate["kernel_provenance"]["evidence_complete"] is False
    assert candidate["material_fact_gate"] == "HOLD_DOCUMENT_CHAIN_INCOMPLETE"
    assert candidate["kernel_provenance"]["never_infer_new_venue_from_annual_authorization"] is True

    direct_title = sample["latest_decisions"][0]["title"]
    intermediate_title = sample["latest_decisions"][1]["title"]
    direct_html = (
        '<a href="/dm/2026/hotarari.nsf/x/$FILE/hotarirea%20304%20-%2023%20iulie%202026%20-%20test.htm">'
        'hotarirea 304 - 23 iulie 2026 - test</a>'
        '<a href="/dm/2026/hotarari.nsf/vwHotarariByAn/ABC?OpenDocument">'
        f'{intermediate_title}</a>'
    )
    resolved = decision_attachments(council.ADOPTED_VIEW, direct_html, sample["latest_decisions"])
    assert 304 in resolved and 303 in resolved
    assert _normalized_title(direct_title) in {_normalized_title(row["title"]) for row in sample["latest_decisions"]}
    print("VÂLCEA CLAR Council Fact Kernel v1 self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    doc = build_registry(live=args.live)
    if args.check:
        assert (doc.get("policy") or {}).get("partial_document_coverage_publishable") is False
        assert (doc.get("policy") or {}).get("annual_authorization_is_new_venue") is False
        for fact in doc.get("facts") or []:
            provenance = fact.get("kernel_provenance") or {}
            if fact.get("status") == "verified":
                assert provenance.get("evidence_complete") is True
                assert float(provenance.get("coverage") or 0) == 1.0
        print(json.dumps({"status": "PASS", **doc["stats"]}, ensure_ascii=False))
        return 0
    OUTPUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", **doc["stats"], "output": str(OUTPUT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
