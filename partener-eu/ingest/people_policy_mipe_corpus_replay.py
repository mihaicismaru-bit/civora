#!/usr/bin/env python3
"""Replay verified MIPE Windows corpus snapshots into decision-maker signals.

This is an acquisition fallback, not a substitute for direct MIPE source health.
Only byte-verified official MIPE snapshots produced by the canonical Windows/Edge
crawler are eligible. Replayed observations remain STATEMENT_SIGNAL records and
can never promote deadlines, budgets, eligibility, call opening or other
administrative facts.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import people_policy_official_ingest as collector

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "partener-eu" / "ingest" / "state" / "people_policy_official_sources.json"
REGISTRY = ROOT / "partener-eu" / "ingest" / "state" / "people_policy_registry.json"
SOURCE_REGISTRY = ROOT / "partener-eu" / "ingest" / "state" / "people_policy_source_registry.json"
CANONICAL_CALLS = ROOT / "partener-eu" / "ingest" / "state" / "mipe_canonical_calls.json"
MIPE_CORPUS = ROOT / "partener-eu" / "ingest" / "state" / "mipe_ro_corpus.json"

MIPE_SOURCE_ID = "MIPE_PRIMARY"
MIPE_HOSTS = {"mfe.gov.ro", "www.mfe.gov.ro"}
MIPE_TRANSPORT = "playwright-edge-direct-romania-v3"
MIPE_VERIFICATION = "CANONICAL_OFFICIAL_FETCH"
REPLAY_PATH = "PERSISTED_MIPE_WINDOWS_CORPUS_REPLAY"


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def iso_day(value: Any) -> str:
    match = re.match(r"^(20\d{2}-\d{2}-\d{2})", str(value or ""))
    return match.group(1) if match else ""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_corpus(corpus: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(corpus, dict):
        return False, "CORPUS_NOT_OBJECT"
    if int(corpus.get("schemaVersion") or 0) < 3:
        return False, "UNSUPPORTED_CORPUS_SCHEMA"
    if str(corpus.get("source") or "") != "MIPE":
        return False, "CORPUS_SOURCE_NOT_MIPE"
    hosts = {str(x).lower() for x in corpus.get("officialHosts") or []}
    if not hosts or not hosts <= MIPE_HOSTS or "mfe.gov.ro" not in hosts:
        return False, "CORPUS_OFFICIAL_HOSTS_INVALID"
    if not isinstance(corpus.get("pages"), list):
        return False, "CORPUS_PAGES_MISSING"
    return True, "OK"


def validate_page(page: dict[str, Any], source: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(page, dict):
        return False, "PAGE_NOT_OBJECT"
    url = str(page.get("url") or "")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = {str(x).lower() for x in source.get("allowedHosts") or []}
    if parsed.scheme != "https" or host not in MIPE_HOSTS or host not in allowed:
        return False, "PAGE_HOST_NOT_OFFICIAL_MIPE"
    if str(page.get("source") or "") != "MIPE":
        return False, "PAGE_SOURCE_NOT_MIPE"
    if str(page.get("tier") or "") != "T1":
        return False, "PAGE_TIER_NOT_T1"
    if str(page.get("verification") or "") != MIPE_VERIFICATION:
        return False, "PAGE_VERIFICATION_NOT_CANONICAL"
    if str(page.get("retrievalTransport") or "") != MIPE_TRANSPORT:
        return False, "PAGE_TRANSPORT_NOT_CANONICAL_WINDOWS_EDGE"
    observed = str(page.get("observedAt") or "")
    if not iso_day(observed):
        return False, "PAGE_OBSERVED_AT_MISSING"
    text = str(page.get("textPreview") or "")
    expected = str(page.get("contentHash") or "").lower()
    if not text or not re.fullmatch(r"[0-9a-f]{64}", expected):
        return False, "PAGE_CONTENT_PROOF_MISSING"
    actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if actual != expected:
        return False, "PAGE_CONTENT_HASH_MISMATCH"
    return True, "OK"


def role_valid_at_observation(role_snapshot: dict[str, Any], observed_at: str) -> bool:
    verified_day = iso_day(role_snapshot.get("verifiedAt"))
    observed_day = iso_day(observed_at)
    return bool(
        verified_day
        and observed_day
        and verified_day <= observed_day
        and str(role_snapshot.get("sourceTier") or "").startswith("T1")
        and str(role_snapshot.get("sourceUrl") or "").startswith("https://")
    )


def build_signal(
    page: dict[str, Any],
    source: dict[str, Any],
    registry: dict[str, Any],
    canonical: dict[str, Any],
    corpus_generated_at: str,
    replayed_at: str,
) -> tuple[dict[str, Any] | None, str]:
    valid, reason = validate_page(page, source)
    if not valid:
        return None, reason

    text = collector.clean(page.get("textPreview"))[:45_000]
    title = collector.clean(page.get("title"))
    if not collector.relevant(f"{title} {text}"):
        return None, "NOT_FUNDING_SIGNAL_RELEVANT"

    actor = collector.actor_statement_for(text[:30_000], registry)
    if not actor:
        return None, "NO_VERIFIED_ACTOR_STATEMENT_EVIDENCE"
    person, role_snapshot, evidence = actor
    observed_at = str(page.get("observedAt") or "")
    if not role_valid_at_observation(role_snapshot, observed_at):
        return None, "ROLE_NOT_VERIFIED_AT_OBSERVATION"

    statement = collector.clean(evidence["statement"])
    headline = title or statement[:220]
    content_hash = str(page["contentHash"]).lower()
    url = str(page["url"])
    date = collector.parse_date(text[:10_000]) or iso_day(observed_at)
    fingerprint = hashlib.sha256(f"{person['id']}|{url}|{content_hash}".encode("utf-8")).hexdigest()
    canonical_link = collector.canonical_link_for(f"{headline} {statement} {text[:12000]}", canonical)

    item: dict[str, Any] = {
        "id": "official-" + fingerprint[:18],
        "personId": person["id"],
        "person": person["name"],
        "role": role_snapshot["role"],
        "institution": role_snapshot["institution"],
        "roleVerification": role_snapshot,
        "date": date,
        "type": collector.classify(f"{headline} {statement}"),
        "signalKind": "STATEMENT_SIGNAL",
        "topic": page.get("programme") or source.get("institution") or "MIPE",
        "headline": headline[:220],
        "statement": statement[:600],
        "statementExtraction": {
            "status": "ACTOR_SPEECH_FUNDING_BOUND",
            "scope": evidence["scope"],
            "actorAlias": evidence["actorAlias"],
            "signalCue": evidence["signalCue"],
            "fundingCue": evidence["fundingCue"],
        },
        "officialFact": "Niciun efect administrativ nu este promovat din această declarație. Orice termen, buget, eligibilitate, deschidere sau modificare de apel cere dovadă T1/T1B separată în dosarul canonic.",
        "administrativeFact": {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True},
        "analysis": "Semnalul provine dintr-un snapshot MIPE oficial, verificat prin hash; impactul operațional se stabilește numai din documentul administrativ aplicabil.",
        "watch": "Ghidul, ordinul, corrigendumul, lista de rezultate sau actul administrativ care poate materializa semnalul.",
        "audiences": ["Beneficiari", "Consultanți"],
        "canonicalLink": canonical_link,
        "sources": [{"label": source["publisher"], "url": url, "tier": source["tier"]}],
        "sourceSnapshot": {
            "sourceId": source["id"],
            "publisher": source["publisher"],
            "tier": source["tier"],
            "url": url,
            "observedAt": observed_at,
            "contentHash": content_hash,
            "acquisitionPath": REPLAY_PATH,
            "retrievalTransport": page["retrievalTransport"],
            "verification": page["verification"],
            "corpusPageId": page.get("id"),
            "corpusGeneratedAt": corpus_generated_at,
            "replayedAt": replayed_at,
        },
        "priority": int(person.get("priority") or 50),
        "initials": "".join(x[0] for x in person["name"].split()[:2]).upper(),
        "whyItMatters": "Semnal oficial MIPE observat de crawlerul Windows și revalidat din corpusul persistent; efectul administrativ rămâne separat și fail-closed.",
        "autoGenerated": True,
        "officialIngested": True,
        "observedAt": observed_at,
        "replayedAt": replayed_at,
        "sourceId": source["id"],
        "fingerprint": fingerprint,
    }
    logical = collector.logical_signal_key(item)
    if logical:
        item["logicalSignalKey"] = logical
        item["id"] = "official-signal-" + logical[:18]
    item["observations"] = collector.observation_records(item)
    item["firstObservedAt"] = observed_at
    item["lastObservedAt"] = observed_at
    item["observationCount"] = 1
    return item, "ACCEPTED"


def replay_pages(
    corpus: dict[str, Any],
    source: dict[str, Any],
    registry: dict[str, Any],
    canonical: dict[str, Any],
    replayed_at: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ok, reason = validate_corpus(corpus)
    if not ok:
        return ({"status": "REPLAY_REJECTED_CORPUS_INTEGRITY", "reason": reason, "failClosed": True}, [])

    pages = corpus.get("pages") or []
    accepted: list[dict[str, Any]] = []
    rejection_counts: dict[str, int] = {}
    integrity_accepted = 0
    for page in pages:
        valid, validation_reason = validate_page(page, source)
        if valid:
            integrity_accepted += 1
        item, item_reason = build_signal(
            page, source, registry, canonical, str(corpus.get("generatedAt") or ""), replayed_at
        )
        if item:
            accepted.append(item)
        else:
            rejection_counts[item_reason or validation_reason] = rejection_counts.get(item_reason or validation_reason, 0) + 1

    status_name = "REPLAY_OK" if accepted else "REPLAY_NO_ACCEPTED_SIGNALS"
    if pages and integrity_accepted == 0:
        status_name = "REPLAY_REJECTED_ALL_PAGE_INTEGRITY"
    status = {
        "status": status_name,
        "acquisitionPath": REPLAY_PATH,
        "corpusSchemaVersion": corpus.get("schemaVersion"),
        "corpusGeneratedAt": corpus.get("generatedAt"),
        "corpusStatus": corpus.get("status"),
        "pagesSeen": len(pages),
        "pagesIntegrityAccepted": integrity_accepted,
        "pagesRejected": len(pages) - integrity_accepted,
        "acceptedItems": len(accepted),
        "rejections": rejection_counts,
        "retrievalTransportRequired": MIPE_TRANSPORT,
        "verificationRequired": MIPE_VERIFICATION,
        "failClosed": True,
    }
    return status, accepted


def apply_replay(
    ledger: dict[str, Any],
    corpus: dict[str, Any],
    source_registry: dict[str, Any],
    registry: dict[str, Any],
    canonical: dict[str, Any],
    replayed_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = copy.deepcopy(ledger)
    source = next((x for x in source_registry.get("sources") or [] if x.get("id") == MIPE_SOURCE_ID), None)
    if not source or not source.get("enabled", True):
        raise ValueError("MIPE_PRIMARY source registry entry is missing or disabled")

    direct_row = next((x for x in output.get("sources") or [] if x.get("id") == MIPE_SOURCE_ID), None)
    direct_status = str((direct_row or {}).get("status") or "MISSING")
    if not direct_status.startswith("SOURCE_UNAVAILABLE"):
        replay_status = {
            "status": "SKIPPED_DIRECT_SOURCE_HEALTHY",
            "directSourceStatus": direct_status,
            "directSourceHealthUnchanged": True,
            "failClosed": True,
        }
        output.setdefault("persistentReplays", {})[MIPE_SOURCE_ID] = replay_status
        return output, replay_status

    replay_status, fresh = replay_pages(corpus, source, registry, canonical, replayed_at)
    replay_status["directSourceStatus"] = direct_status
    replay_status["directSourceHealthUnchanged"] = True
    replay_status["replayedAt"] = replayed_at

    if replay_status["status"] in {"REPLAY_REJECTED_CORPUS_INTEGRITY", "REPLAY_REJECTED_ALL_PAGE_INTEGRITY"}:
        raise ValueError(f"MIPE persistent replay rejected: {replay_status['status']}: {replay_status.get('reason') or replay_status.get('rejections')}")

    output["generatedAt"] = replayed_at
    policy = output.setdefault("policy", {})
    policy["mipePersistentReplayRequiresOfficialHost"] = True
    policy["mipePersistentReplayRequiresContentHash"] = True
    policy["mipePersistentReplayRequiresCanonicalWindowsTransport"] = True
    policy["mipePersistentReplayRequiresRoleAtObservation"] = True
    policy["mipeDirectHealthIndependentFromPersistentReplay"] = True
    policy["administrativeFactsNeverPromotedFromSignals"] = True
    policy["failClosed"] = True
    output.setdefault("persistentReplays", {})[MIPE_SOURCE_ID] = replay_status
    output["items"] = sorted(
        collector.deduplicate_signal_history([*(output.get("items") or []), *fresh]),
        key=lambda x: (
            str(x.get("date") or ""),
            str(x.get("lastObservedAt") or x.get("observedAt") or ""),
            int(x.get("priority") or 0),
        ),
        reverse=True,
    )[:320]
    return output, replay_status


def main() -> int:
    ledger = load(STATE, {"schemaVersion": 2, "sources": [], "items": [], "quarantine": []})
    corpus = load(MIPE_CORPUS, {})
    source_registry = load(SOURCE_REGISTRY, {"sources": []})
    registry = load(REGISTRY, {"people": []})
    canonical = load(CANONICAL_CALLS, {"calls": []})
    replayed_at = now_iso()

    output, replay_status = apply_replay(
        ledger, corpus, source_registry, registry, canonical, replayed_at
    )
    STATE.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "sourceId": MIPE_SOURCE_ID,
        "status": replay_status.get("status"),
        "directSourceStatus": replay_status.get("directSourceStatus"),
        "pagesSeen": replay_status.get("pagesSeen", 0),
        "pagesIntegrityAccepted": replay_status.get("pagesIntegrityAccepted", 0),
        "acceptedItems": replay_status.get("acceptedItems", 0),
        "historyItems": len(output.get("items") or []),
        "directSourceHealthUnchanged": replay_status.get("directSourceHealthUnchanged"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
