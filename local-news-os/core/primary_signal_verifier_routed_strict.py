#!/usr/bin/env python3
"""Production primary verifier with boundary-safe routing and dedicated targets.

This adapter preserves the ranked strict corroboration gate and adds only a
config-driven primary-target registry. It grants no Fact Kernel or publication
authority.

Official primary listings sometimes carry the only trustworthy publication date
in the link label or in a dated accordion/button title while the linked primary
document omits machine-readable date metadata. This adapter may recover that
explicit date only from strict, unambiguous official-listing text and records the
provenance so the strict freshness gate remains fail-closed.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CORE = Path(__file__).resolve().parent
ROOT = CORE.parents[1]
import sys
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import primary_signal_verifier as base  # noqa: E402
import primary_signal_verifier_ranked as ranked  # noqa: E402
import primary_signal_verifier_strict as strict  # noqa: E402
import signal_radar as radar  # noqa: E402
import signal_routing_contract as routing  # noqa: E402

LEGACY_FETCH_PRIMARY_CANDIDATE = base.fetch_primary_candidate
LEGACY_BUILD_TARGET_CORPUS = base.build_target_corpus
LEGACY_VERIFY_TASK = base.verify_task
LISTING_DATE_DMY = re.compile(r"\((\d{1,2})[./](\d{1,2})[./](\d{4})\)\s*$")
LISTING_DATE_ISO = re.compile(r"\((\d{4})-(\d{2})-(\d{2})\)\s*$")


class DatedListingButtonParser(html.parser.HTMLParser):
    """Extract visible button labels without treating arbitrary page text as evidence."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._parts: list[str] = []
        self.labels: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() == "button":
            if self._depth == 0:
                self._parts = []
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "button" or self._depth == 0:
            return
        self._depth -= 1
        if self._depth == 0:
            value = radar.clean(" ".join(self._parts))
            if value:
                self.labels.append(value)
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._depth:
            value = radar.clean(data)
            if value:
                self._parts.append(value)


def listing_label_published_at(label: str, tz: ZoneInfo) -> datetime | None:
    """Return a date only when an official listing label ends in an explicit date."""
    clean = radar.clean(label)
    match = LISTING_DATE_DMY.search(clean)
    if match:
        day, month, year = (int(value) for value in match.groups())
    else:
        match = LISTING_DATE_ISO.search(clean)
        if not match:
            return None
        year, month, day = (int(value) for value in match.groups())
    try:
        return datetime(year, month, day, tzinfo=tz)
    except ValueError:
        return None


def dated_listing_button_documents(
    article: str,
    listing_url: str,
    tz: ZoneInfo,
    *,
    max_items: int = 80,
) -> list[dict[str, Any]]:
    """Turn explicit dated official-listing button titles into evidence-only documents."""
    parser = DatedListingButtonParser()
    parser.feed(article)
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in parser.labels:
        title = radar.clean(raw)
        published = listing_label_published_at(title, tz)
        identity = radar.norm_text(title)
        if published is None or not 20 <= len(title) <= 300 or identity in seen:
            continue
        seen.add(identity)
        digest = hashlib.sha256(f"{listing_url}\n{title}".encode("utf-8")).hexdigest()
        documents.append({
            "url": f"{listing_url}#official-listing-item-{digest[:16]}",
            "title": title,
            "published_at": published.isoformat(timespec="seconds"),
            "published_at_source": "official_listing_button",
            "listing_url": listing_url,
            "listing_label": title,
            "evidence_scope": "official_listing_item_title_date_only",
            "title_tokens": sorted(base.tokens(title)),
            "body_tokens": sorted(base.tokens(title)),
            "content_sha256": digest,
        })
        if len(documents) >= max_items:
            break
    return documents


def listing_date_aware_fetch_primary_candidate(
    url: str,
    fallback_title: str,
    tz: ZoneInfo,
) -> dict[str, Any] | None:
    doc = LEGACY_FETCH_PRIMARY_CANDIDATE(url, fallback_title, tz)
    if doc is None:
        return None
    if doc.get("published_at"):
        doc.setdefault("published_at_source", "primary_document_metadata")
        return doc

    published = listing_label_published_at(fallback_title, tz)
    if published is not None:
        doc["published_at"] = published.isoformat(timespec="seconds")
        doc["published_at_source"] = "official_listing_label"
        doc["listing_label"] = radar.clean(fallback_title)[:300]
    return doc


def listing_item_aware_build_target_corpus(
    target: dict[str, Any],
    tz: ZoneInfo,
    *,
    max_links: int,
    max_fetches: int,
) -> dict[str, Any]:
    corpus = LEGACY_BUILD_TARGET_CORPUS(
        target,
        tz,
        max_links=max_links,
        max_fetches=max_fetches,
    )
    if len(corpus.get("documents") or []) >= min(4, max(1, max_fetches)):
        return corpus

    try:
        listing, final = radar.fetch(str(target["url"]), max_bytes=2_000_000, timeout=14)
    except Exception:
        return corpus

    listing_docs = dated_listing_button_documents(listing, final, tz)
    if not listing_docs:
        return corpus

    existing = {
        (str(row.get("title") or ""), str(row.get("published_at") or ""))
        for row in corpus.get("documents") or []
        if isinstance(row, dict)
    }
    added = [
        row for row in listing_docs
        if (str(row.get("title") or ""), str(row.get("published_at") or "")) not in existing
    ]
    if not added:
        return corpus

    corpus["documents"] = list(corpus.get("documents") or []) + added
    corpus["status"] = "PASS"
    if corpus.get("error") == "no_primary_documents_retrieved":
        corpus["error"] = None
    corpus["official_listing_item_documents"] = len(added)
    return corpus


def listing_date_aware_verify_task(
    task: dict[str, Any],
    corpora: dict[tuple[str, str], dict[str, Any]],
    tz: ZoneInfo,
) -> dict[str, Any]:
    result = LEGACY_VERIFY_TASK(task, corpora, tz)
    evidence = result.get("primary_evidence")
    if result.get("status") != "PRIMARY_MATCH_FOUND" or not isinstance(evidence, dict):
        return result

    primary_url = str(evidence.get("primary_item_url") or "")
    for corpus in corpora.values():
        for doc in corpus.get("documents") or []:
            if not isinstance(doc, dict) or str(doc.get("url") or "") != primary_url:
                continue
            source = str(doc.get("published_at_source") or "").strip()
            if source:
                evidence["primary_published_at_source"] = source
            if doc.get("listing_label"):
                evidence["primary_listing_label"] = str(doc["listing_label"])[:300]
            if doc.get("listing_url"):
                evidence["primary_listing_url"] = str(doc["listing_url"])
            if doc.get("evidence_scope"):
                evidence["primary_evidence_scope"] = str(doc["evidence_scope"])
            return result
    return result


def extended_target_registry(config: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result = ranked.ranked_target_registry(config)
    for sid, row in routing.load_primary_targets(config).items():
        result[("primary_target_id", sid)] = {
            "ref_type": "primary_target_id",
            "id": sid,
            "name": str(row.get("publisher") or sid),
            "url": str(row["url"]),
            "tier": str(row.get("tier") or "T1"),
            "status": row.get("status"),
            "enabled": row.get("enabled", True),
            "path_hints": [str(value).casefold() for value in row.get("path_hints") or [] if str(value).strip()],
        }
    return result


def install(instance_id: str) -> None:
    routing.install()
    ranked.install_ranking()
    strict.install_strict_guard(instance_id)
    base.target_registry = extended_target_registry
    base.fetch_primary_candidate = listing_date_aware_fetch_primary_candidate
    base.build_target_corpus = listing_item_aware_build_target_corpus
    base.verify_task = listing_date_aware_verify_task


def validate(instance_id: str) -> dict[str, Any]:
    install(instance_id)
    report = base.validate(instance_id)
    config, _ = radar.load_config(instance_id)
    registry = base.target_registry(config)
    hinted = sum(1 for row in registry.values() if row.get("path_hints"))
    return {
        **report,
        "strict_false_positive_guard": True,
        "primary_published_at_required": True,
        "official_listing_label_date_fallback": True,
        "official_dated_button_evidence": True,
        "official_listing_evidence_is_title_date_only": True,
        "official_listing_label_date_must_be_explicit_terminal": True,
        "title_event_overlap_required": True,
        "candidate_ranking": "LISTING_PATH_THEN_SOURCE_HINTS_THEN_NEWS_STRUCTURE",
        "registered_targets": len(registry),
        "targets_with_path_hints": hinted,
        "dedicated_primary_targets": len(routing.load_primary_targets(config)),
        "publication_authority": "NONE",
    }


def run(instance_id: str, *, write: bool) -> dict[str, Any]:
    install(instance_id)
    state = base.run(instance_id, write=False)
    state["verification_policy"] = {
        "strict_false_positive_guard": True,
        "primary_published_at_required": True,
        "official_listing_label_date_fallback": True,
        "official_dated_button_evidence": True,
        "official_listing_evidence_is_title_date_only": True,
        "official_listing_label_date_must_be_explicit_terminal": True,
        "max_publication_time_delta_hours": 36,
        "title_event_overlap_required": True,
        "instance_identity_is_not_event_evidence": True,
        "body_only_similarity_rejected": True,
        "primary_candidate_ranking": "LISTING_PATH_THEN_SOURCE_HINTS_THEN_NEWS_STRUCTURE",
        "boundary_safe_signal_routing": True,
        "dedicated_primary_target_registry": True,
    }
    if write:
        config, _ = radar.load_config(instance_id)
        output = ROOT / str(config["primary_verification_state_path"])
        output.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state


def self_test() -> int:
    tz = ZoneInfo("Europe/Bucharest")
    dmy = listing_label_published_at(
        "APAVIL SA – concurs încasator-cititor, Sector Govora (18.08.2026)",
        tz,
    )
    assert dmy is not None and dmy.isoformat(timespec="seconds") == "2026-08-18T00:00:00+03:00"
    iso = listing_label_published_at("Comunicat oficial (2026-08-18)", tz)
    assert iso is not None and iso.date().isoformat() == "2026-08-18"
    assert listing_label_published_at("Comunicat oficial 18.08.2026", tz) is None
    assert listing_label_published_at("Comunicat (18.08.2026) actualizat", tz) is None
    assert listing_label_published_at("Comunicat oficial (31.02.2026)", tz) is None

    sample = """
    <div class="accordion">
      <button>Anunt privind scoaterea la concurs a unui post de incasator-cititor
      in cadrul Sectorului Govora, subzona Pietrari (17.08.2026)</button>
      <a href="/materiale/detalii.pdf">Detalii anunt</a>
      <button>Arhiva fara data verificabila</button>
    </div>
    """
    docs = dated_listing_button_documents(sample, "https://example.invalid/jobs", tz)
    assert len(docs) == 1, docs
    assert docs[0]["published_at"] == "2026-08-17T00:00:00+03:00"
    assert docs[0]["published_at_source"] == "official_listing_button"
    assert docs[0]["evidence_scope"] == "official_listing_item_title_date_only"
    assert docs[0]["url"].startswith("https://example.invalid/jobs#official-listing-item-")

    strict.install_strict_guard("valcea")
    derived_doc = {"published_at": dmy.isoformat(timespec="seconds")}
    assert strict.strict_date_compatible(
        {"published_at": "2026-08-18T12:30:00+03:00"},
        derived_doc,
        tz,
    ) is True
    assert strict.strict_date_compatible(
        {"published_at": "2026-08-20T12:30:00+03:00"},
        derived_doc,
        tz,
    ) is False

    assert routing.self_test() == 0
    assert ranked.self_test() == 0
    assert strict.self_test() == 0
    print("LOCAL NEWS OS routed ranked strict primary verifier self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.instance:
        parser.error("--instance is required")
    if args.validate_only:
        print(json.dumps(validate(args.instance), ensure_ascii=False))
        return 0
    state = run(args.instance, write=not args.no_write)
    print(json.dumps({
        "status": "PASS",
        "task_count": state["task_count"],
        "primary_match_count": state["primary_match_count"],
        "no_match_count": state["no_match_count"],
        "unrouted_count": state["unrouted_count"],
        "targets_ok": state["targets_ok"],
        "target_count": state["target_count"],
        "strict_false_positive_guard": True,
        "official_listing_label_date_fallback": True,
        "official_dated_button_evidence": True,
        "boundary_safe_signal_routing": True,
        "publication_authority": "NONE",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
