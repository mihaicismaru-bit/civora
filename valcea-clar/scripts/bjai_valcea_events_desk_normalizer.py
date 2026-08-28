#!/usr/bin/env python3
"""Fail-closed BJAI Vâlcea Events Desk normalizer (internal, non-persistent)."""
from __future__ import annotations

import argparse, hashlib, json, re
from datetime import date, datetime, time
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bucharest")
SOURCE_ID = "signal-bjai-valcea-events"
INPUT_PRODUCT = "VÂLCEA CLAR BJAI Vâlcea event signals"
OUTPUT_PRODUCT = "VÂLCEA CLAR internal Events Desk normalized BJAI events"
INPUT_LIFECYCLE = "SIGNAL_ONLY_NEEDS_EDITORIAL_VERIFICATION"
OUTPUT_LIFECYCLE = "INTERNAL_EVENTS_DESK_REVIEW_REQUIRED"
HOSTS = {"bjai.ro", "www.bjai.ro"}
SIGNAL_RE = re.compile(r"^bjai-event-[0-9a-f]{20}$", re.I)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
STATUSES = ("UPCOMING", "TODAY", "IN_PROGRESS", "ENDED", "DATE_UNKNOWN")
ENRICHMENT = {"NOT_FETCHED", "EXPLICIT_EVENT_TIME_EXTRACTED", "NO_EXPLICIT_EVENT_TIME_EXTRACTED", "HELD_ANTIBOT_OR_INTERSTITIAL", "HELD_FETCH_OR_STRUCTURE_ERROR"}
PRECISION = {"EXPLICIT_DATE", "EXPLICIT_DATE_TIME", "EXPLICIT_DATE_RANGE"}

INPUT_POLICY = {
    "signal_only": True, "reader_facing_eligible": False,
    "publication_authority": "NONE", "fact_kernel_authority": "NONE",
    "writer_authority": "NONE", "public_projection": False,
    "auto_publication": False, "persistence_authority": "NONE",
    "event_datetime_requires_explicit_visible_source_text": True,
    "cms_timestamp_never_substitutes_for_event_datetime": True,
    "source_media_does_not_imply_republication_rights": True,
    "generic_fallback_images_rejected": True,
    "anti_bot_or_fetch_failure_holds_enrichment": True,
}
OUTPUT_POLICY = {
    "reader_facing_eligible": False, "publication_authority": "NONE",
    "fact_kernel_authority": "NONE", "writer_authority": "NONE",
    "public_projection": False, "auto_publication": False,
    "persistence_authority": "NONE", "requires_editorial_verification": True,
    "schedule_state_semantics": "INTERNAL_TRIAGE_ONLY_FROM_EXPLICIT_EVENT_TIME_EVIDENCE",
    "cms_timestamp_never_substitutes_for_event_datetime": True,
    "visual_reuse_rights_never_escalated": True,
}
BOUNDARY = {
    "lifecycle": INPUT_LIFECYCLE, "publication_authority": "NONE",
    "fact_kernel_authority": "NONE", "writer_authority": "NONE",
    "public_projection": False, "auto_publication": False,
    "persistence_authority": "NONE",
}


def clean(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def as_of(v: Any) -> datetime:
    try: d = datetime.fromisoformat(clean(v))
    except ValueError as exc: raise ValueError("as_of requires ISO timestamp") from exc
    if d.tzinfo is None or d.utcoffset() is None: raise ValueError("as_of requires offset-aware timestamp")
    return d.astimezone(TZ)


def iso_date(v: Any, field: str) -> date:
    try: return date.fromisoformat(clean(v))
    except ValueError as exc: raise ValueError(f"{field} requires YYYY-MM-DD") from exc


def hhmm(v: Any, field: str) -> time | None:
    if v is None: return None
    text = clean(v)
    if not TIME_RE.fullmatch(text): raise ValueError(f"{field} requires HH:MM or null")
    h, m = map(int, text.split(":")); return time(h, m)


def official_url(v: Any, kind: str) -> str:
    p = urlsplit(clean(v))
    if p.scheme.lower() != "https" or not p.hostname or p.hostname.lower() not in HOSTS or p.username or p.password:
        raise ValueError(f"Events Desk requires official BJAI HTTPS {kind} URL")
    path = re.sub(r"/+", "/", p.path or "/")
    if kind == "event":
        if not path.endswith("/"): path += "/"
        if not re.fullmatch(r"/evenimente/[^/]+/", path) or "/page/" in path: raise ValueError("Events Desk requires direct event URL")
    elif kind == "archive":
        if path == "/evenimente": path += "/"
        if path != "/evenimente/" and not re.fullmatch(r"/evenimente/page/[1-9]\d*/", path): raise ValueError("Events Desk requires archive URL")
    else:
        if not path.startswith("/wp-content/uploads/"): raise ValueError("Events Desk requires BJAI upload image URL")
    return urlunsplit(("https", "www.bjai.ro", path, "", ""))


def period(v: Any) -> dict[str, Any] | None:
    if v is None: return None
    if not isinstance(v, dict) or set(v) != {"event_start_date", "event_end_date", "event_start_time", "event_end_time", "event_temporal_precision", "event_temporal_evidence"}:
        raise ValueError("event_period schema drift")
    start, end = iso_date(v["event_start_date"], "event_start_date"), iso_date(v["event_end_date"], "event_end_date")
    if end < start: raise ValueError("event date range reversed")
    st, et = hhmm(v["event_start_time"], "event_start_time"), hhmm(v["event_end_time"], "event_end_time")
    precision, evidence = clean(v["event_temporal_precision"]), clean(v["event_temporal_evidence"])
    if precision not in PRECISION or not evidence: raise ValueError("event period lacks explicit evidence")
    if precision == "EXPLICIT_DATE" and (start != end or st or et): raise ValueError("EXPLICIT_DATE shape drift")
    if precision == "EXPLICIT_DATE_TIME" and (start != end or st is None or (et and et < st)): raise ValueError("EXPLICIT_DATE_TIME shape drift")
    if precision == "EXPLICIT_DATE_RANGE" and (st or et): raise ValueError("EXPLICIT_DATE_RANGE cannot infer times")
    return {"event_start_date": start.isoformat(), "event_end_date": end.isoformat(), "event_start_time": st.strftime("%H:%M") if st else None, "event_end_time": et.strftime("%H:%M") if et else None, "event_temporal_precision": precision, "event_temporal_evidence": evidence}


def visual(v: Any, article: str) -> dict[str, Any]:
    required = {"source_image_url", "source_page_url", "visual_desk_candidate", "rights_state", "public_reuse_allowed", "generic_fallback_images_rejected", "image_semantics"}
    if not isinstance(v, dict) or set(v) != required: raise ValueError("visual schema drift")
    if official_url(v["source_page_url"], "event") != article: raise ValueError("visual page mismatch")
    image = official_url(v["source_image_url"], "image") if v["source_image_url"] else None
    if v["visual_desk_candidate"] is not bool(image): raise ValueError("visual candidate drift")
    expected_rights = "UNKNOWN_REUSE_REQUIRES_EDITORIAL_CLEARANCE" if image else "NO_EVENT_SPECIFIC_IMAGE_DISCOVERED"
    if v["rights_state"] != expected_rights or v["public_reuse_allowed"] is not False: raise ValueError("visual rights escalation")
    if v["generic_fallback_images_rejected"] is not True or v["image_semantics"] != "SOURCE_MEDIA_PROVENANCE_ONLY_NOT_A_REPUBLICATION_LICENSE": raise ValueError("visual semantics drift")
    return {**v, "source_image_url": image, "source_page_url": article, "requires_editorial_rights_clearance": bool(image)}


def validate_signal(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict): raise ValueError("signal must be object")
    for k, expected in BOUNDARY.items():
        if raw.get(k) != expected: raise ValueError(f"signal boundary drift: {k}")
    if raw.get("source_id") != SOURCE_ID or raw.get("source_tier") != "T1B" or raw.get("source_kind") != "CULTURE_LIBRARY_EVENTS": raise ValueError("source classification drift")
    if raw.get("cms_timestamp_is_event_time") is not False: raise ValueError("CMS timestamp cannot be event time")
    sid, title = clean(raw.get("signal_id")), clean(raw.get("title"))
    if not SIGNAL_RE.fullmatch(sid) or not title: raise ValueError("invalid signal identity")
    article, archive = official_url(raw.get("article_url"), "event"), official_url(raw.get("archive_page_url"), "archive")
    state = clean(raw.get("event_enrichment_state"))
    if state not in ENRICHMENT: raise ValueError("unknown enrichment state")
    p = period(raw.get("event_period"))
    if bool(p) != (state == "EXPLICIT_EVENT_TIME_EXTRACTED"): raise ValueError("event period/enrichment mismatch")
    if p and raw.get("event_date_semantics") != "EXPLICIT_VISIBLE_SOURCE_TEXT_ONLY_NOT_CMS_TIMESTAMP": raise ValueError("event date semantics drift")
    prov = raw.get("provenance")
    if not isinstance(prov, dict) or prov.get("authority") != "BJAI_VALCEA_OFFICIAL" or official_url(prov.get("discovery_surface"), "archive") != archive or prov.get("event_url_basis") != "OFFICIAL_ARCHIVE_LINK": raise ValueError("provenance drift")
    basis = prov.get("event_time_basis")
    if p and basis != "EXPLICIT_VISIBLE_SOURCE_TEXT": raise ValueError("event period lacks source-text basis")
    if not p and basis not in {None, "NONE"}: raise ValueError("event time basis without period")
    sha = prov.get("event_fetch_content_sha256")
    if sha is not None and not SHA_RE.fullmatch(clean(sha).lower()): raise ValueError("invalid event content sha")
    if p and prov.get("event_fetch_state") != "PASS": raise ValueError("event extraction requires PASS fetch")
    return {"signal_id": sid, "title": title, "article_url": article, "archive_page_url": archive, "cms_published_at": raw.get("cms_published_at"), "cms_timestamp_semantics": raw.get("cms_timestamp_semantics"), "event_enrichment_state": state, "event_period": p, "visual": visual(raw.get("visual"), article), "provenance": prov}


def validate_document(doc: Any) -> list[dict[str, Any]]:
    if not isinstance(doc, dict) or doc.get("schema_version") != "1.0" or doc.get("product") != INPUT_PRODUCT or doc.get("source_id") != SOURCE_ID: raise ValueError("unknown BJAI signal document")
    policy = doc.get("policy")
    if not isinstance(policy, dict): raise ValueError("missing upstream policy")
    for k, expected in INPUT_POLICY.items():
        if policy.get(k) != expected: raise ValueError(f"upstream policy drift: {k}")
    rows = doc.get("signals")
    if not isinstance(rows, list) or doc.get("signal_count") != len(rows): raise ValueError("signal_count drift")
    out, ids, urls = [], set(), set()
    for row in rows:
        s = validate_signal(row)
        if s["signal_id"] in ids or s["article_url"] in urls: raise ValueError("duplicate BJAI event evidence")
        ids.add(s["signal_id"]); urls.add(s["article_url"]); out.append(s)
    return out


def status(p: dict[str, Any] | None, now: datetime) -> tuple[str, str]:
    if not p: return "DATE_UNKNOWN", "NO_EXPLICIT_EVENT_PERIOD"
    start, end, today = date.fromisoformat(p["event_start_date"]), date.fromisoformat(p["event_end_date"]), now.date()
    if today < start: return "UPCOMING", "START_DATE_AFTER_AS_OF_DATE"
    if today > end: return "ENDED", "END_DATE_BEFORE_AS_OF_DATE"
    st, et, clock = hhmm(p["event_start_time"], "event_start_time"), hhmm(p["event_end_time"], "event_end_time"), now.timetz().replace(tzinfo=None)
    if start == end == today:
        if st and et:
            if clock < st: return "TODAY", "SAME_DAY_BEFORE_EXPLICIT_START_TIME"
            if clock > et: return "ENDED", "SAME_DAY_AFTER_EXPLICIT_END_TIME"
            return "IN_PROGRESS", "SAME_DAY_WITHIN_EXPLICIT_TIME_WINDOW"
        return "TODAY", "SAME_DAY_WITHOUT_COMPLETE_START_END_TIME"
    return "IN_PROGRESS", "AS_OF_DATE_INSIDE_EXPLICIT_DATE_RANGE"


def event_id(article: str) -> str:
    return "events-desk-bjai-" + hashlib.sha256((SOURCE_ID + "\0" + article).encode()).hexdigest()[:24]


def fingerprint(s: dict[str, Any]) -> str:
    payload = {"title": s["title"], "event_period": s["event_period"], "cms_published_at": s.get("cms_published_at"), "cms_modified_at": s["provenance"].get("cms_modified_at"), "event_fetch_content_sha256": s["provenance"].get("event_fetch_content_sha256"), "source_image_url": s["visual"].get("source_image_url")}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def normalize(s: dict[str, Any], now: datetime) -> dict[str, Any]:
    state, basis = status(s["event_period"], now); eid = event_id(s["article_url"])
    holds = {"HELD_ANTIBOT_OR_INTERSTITIAL": "SOURCE_ANTIBOT_OR_INTERSTITIAL_REQUIRES_RECHECK", "HELD_FETCH_OR_STRUCTURE_ERROR": "SOURCE_FETCH_OR_STRUCTURE_REQUIRES_RECHECK", "NOT_FETCHED": "DIRECT_EVENT_PAGE_NOT_FETCHED"}
    hold = None if state != "DATE_UNKNOWN" else holds.get(s["event_enrichment_state"], "NO_EXPLICIT_EVENT_DATE_TIME_EVIDENCE")
    return {"event_id": eid, "dedupe_key": eid, "source_signal_id": s["signal_id"], "title": s["title"], "article_url": s["article_url"], "temporal_status": state, "temporal_status_basis": basis, "event_period": s["event_period"], "editorial_hold_reason": hold, "source_revision_fingerprint": fingerprint(s), "visual": s["visual"], "provenance": {"authority": "BJAI_VALCEA_OFFICIAL", "discovery_surface": s["archive_page_url"], "article_url": s["article_url"], "cms_published_at": s.get("cms_published_at"), "cms_timestamp_semantics": s.get("cms_timestamp_semantics"), "cms_timestamp_is_event_time": False, "event_time_basis": s["provenance"].get("event_time_basis") or "NONE", "event_fetch_content_sha256": s["provenance"].get("event_fetch_content_sha256"), "event_fetch_state": s["provenance"].get("event_fetch_state"), "cms_modified_at": s["provenance"].get("cms_modified_at")}, "lifecycle": OUTPUT_LIFECYCLE, "requires_editorial_verification": True, "reader_facing_eligible": False, "publication_authority": "NONE", "fact_kernel_authority": "NONE", "writer_authority": "NONE", "public_projection": False, "auto_publication": False, "persistence_authority": "NONE"}


def build(doc: Any, at: Any) -> dict[str, Any]:
    now, signals = as_of(at), validate_document(doc); events = [normalize(s, now) for s in signals]
    events.sort(key=lambda e: (e["event_period"] is None, (e["event_period"] or {}).get("event_start_date") or "9999-12-31", (e["event_period"] or {}).get("event_start_time") or "99:99", e["title"].casefold()))
    counts = {s: sum(e["temporal_status"] == s for e in events) for s in STATUSES}
    return {"schema_version": "1.0", "product": OUTPUT_PRODUCT, "as_of": now.isoformat(), "source_id": SOURCE_ID, "event_count": len(events), "status_counts": counts, "events": events, "policy": dict(OUTPUT_POLICY)}


def _fixture(p=None, state="NO_EXPLICIT_EVENT_TIME_EXTRACTED", image=None) -> dict[str, Any]:
    article = "https://www.bjai.ro/evenimente/ziua-limbii-romane/"
    prov = {"authority": "BJAI_VALCEA_OFFICIAL", "discovery_surface": "https://www.bjai.ro/evenimente/", "event_url_basis": "OFFICIAL_ARCHIVE_LINK", "cms_time_basis": "EXPLICIT_VISIBLE_POST_DATE_DATE_ONLY", "event_time_basis": "EXPLICIT_VISIBLE_SOURCE_TEXT" if p else "NONE"}
    if state != "NOT_FETCHED": prov.update(event_fetch_content_sha256="a" * 64, event_fetch_state="PASS" if state in {"EXPLICIT_EVENT_TIME_EXTRACTED", "NO_EXPLICIT_EVENT_TIME_EXTRACTED"} else state)
    v = {"source_image_url": image, "source_page_url": article, "visual_desk_candidate": bool(image), "rights_state": "UNKNOWN_REUSE_REQUIRES_EDITORIAL_CLEARANCE" if image else "NO_EVENT_SPECIFIC_IMAGE_DISCOVERED", "public_reuse_allowed": False, "generic_fallback_images_rejected": True, "image_semantics": "SOURCE_MEDIA_PROVENANCE_ONLY_NOT_A_REPUBLICATION_LICENSE"}
    s = {"signal_id": "bjai-event-" + "1" * 20, "source_id": SOURCE_ID, "source_tier": "T1B", "source_kind": "CULTURE_LIBRARY_EVENTS", "title": "Ziua Limbii Române", "article_url": article, "archive_page_url": "https://www.bjai.ro/evenimente/", "cms_published_at": "2026-08-26", "cms_timestamp_semantics": "EXPLICIT_VISIBLE_POST_DATE_DATE_ONLY", "cms_timestamp_is_event_time": False, "event_period": p, "event_enrichment_state": state, "visual": v, **BOUNDARY, "provenance": prov}
    if p: s["event_date_semantics"] = "EXPLICIT_VISIBLE_SOURCE_TEXT_ONLY_NOT_CMS_TIMESTAMP"
    return s


def _doc(s: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "1.0", "product": INPUT_PRODUCT, "source_id": SOURCE_ID, "signal_count": 1, "signals": [s], "policy": dict(INPUT_POLICY)}


def self_test() -> int:
    day = {"event_start_date": "2026-08-31", "event_end_date": "2026-08-31", "event_start_time": None, "event_end_time": None, "event_temporal_precision": "EXPLICIT_DATE", "event_temporal_evidence": "31 august 2026"}
    timed = {**day, "event_start_time": "11:00", "event_end_time": "13:00", "event_temporal_precision": "EXPLICIT_DATE_TIME"}
    ranged = {**day, "event_start_date": "2026-08-29", "event_end_date": "2026-08-31", "event_temporal_precision": "EXPLICIT_DATE_RANGE"}
    s = _fixture(day, "EXPLICIT_EVENT_TIME_EXTRACTED"); assert build(_doc(s), "2026-08-29T01:00:00+03:00")["events"][0]["temporal_status"] == "UPCOMING"
    s = _fixture(timed, "EXPLICIT_EVENT_TIME_EXTRACTED"); assert build(_doc(s), "2026-08-31T12:00:00+03:00")["events"][0]["temporal_status"] == "IN_PROGRESS"; assert build(_doc(s), "2026-08-31T13:01:00+03:00")["events"][0]["temporal_status"] == "ENDED"
    s = _fixture(ranged, "EXPLICIT_EVENT_TIME_EXTRACTED"); assert build(_doc(s), "2026-08-30T12:00:00+03:00")["events"][0]["temporal_status"] == "IN_PROGRESS"
    s = _fixture(); out = build(_doc(s), "2026-08-31T12:00:00+03:00")["events"][0]; assert out["temporal_status"] == "DATE_UNKNOWN" and out["provenance"]["cms_timestamp_is_event_time"] is False
    image = "https://www.bjai.ro/wp-content/uploads/2026/08/limba-romana.jpg"; out = build(_doc(_fixture(day, "EXPLICIT_EVENT_TIME_EXTRACTED", image)), "2026-08-29T01:00:00+03:00")["events"][0]; assert out["visual"]["public_reuse_allowed"] is False and out["visual"]["requires_editorial_rights_clearance"] is True
    bad = _doc(_fixture(day, "EXPLICIT_EVENT_TIME_EXTRACTED")); bad["policy"]["reader_facing_eligible"] = True
    try: build(bad, "2026-08-29T01:00:00+03:00"); raise AssertionError("policy drift accepted")
    except ValueError: pass
    one = build(_doc(_fixture(day, "EXPLICIT_EVENT_TIME_EXTRACTED")), "2026-08-29T01:00:00+03:00")["events"][0]; two_s = _fixture(timed, "EXPLICIT_EVENT_TIME_EXTRACTED"); two = build(_doc(two_s), "2026-08-29T01:00:00+03:00")["events"][0]; assert one["event_id"] == two["event_id"] and one["source_revision_fingerprint"] != two["source_revision_fingerprint"]
    try: build(_doc(_fixture(day, "EXPLICIT_EVENT_TIME_EXTRACTED")), "2026-08-29T01:00:00"); raise AssertionError("naive as_of accepted")
    except ValueError: pass
    print("BJAI Events Desk regressions passed: 8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("input", nargs="?"); ap.add_argument("--as-of"); ap.add_argument("--output"); ap.add_argument("--self-test", action="store_true"); args = ap.parse_args()
    if args.self_test: return self_test()
    if not args.input or not args.as_of: ap.error("input and --as-of are required unless --self-test")
    with open(args.input, encoding="utf-8") as f: doc = json.load(f)
    rendered = json.dumps(build(doc, args.as_of), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f: f.write(rendered)
    else: print(rendered, end="")
    return 0

if __name__ == "__main__": raise SystemExit(main())
