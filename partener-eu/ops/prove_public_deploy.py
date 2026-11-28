#!/usr/bin/env python3
"""Fail-closed proof that the newly deployed PARTENER.EU projection is publicly readable.

The proof compares the public static manifest with the exact local manifest used for
this Pages deployment and verifies the three decision-critical listing routes expose
the expected number of dossier cards. It never alters canonical funding data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Independent public readback check: reuse only the strict clock parser, not
# the renderer's OPEN decision. Manifest parity cannot prove current validity.
from build_public_static_pages import has_explicit_open_deadline_clock, parse_date

DEFAULT_BASE_URL = "https://partener.eu/"
DEFAULT_MANIFEST = "partener-eu/web/static-public-manifest.json"
DEFAULT_OUTPUT = "/tmp/partener-pages-readback.json"
CARD_RE = re.compile(r"\bdata-dossier-id\s*=\s*[\"']", re.IGNORECASE)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cache_busted(url: str, token: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query.append(("partener_readback", token))
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment))


def fetch_bytes(url: str, *, timeout: float, token: str) -> tuple[int, bytes, str]:
    target = cache_busted(url, token)
    req = urllib.request.Request(
        target,
        headers={
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
            "User-Agent": "PARTENER.EU-Pages-Public-Readback/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return int(getattr(response, "status", 200)), response.read(), response.geturl()


def same_public_route(requested: str, resolved: str) -> bool:
    """Reject redirects off the exact public HTTPS origin or route.

    A matching manifest/card payload served from another host or route is not
    evidence that the intended public deployment is live. Query parameters
    (including the readback cache buster) do not change route identity.
    """
    expected, actual = urllib.parse.urlsplit(requested), urllib.parse.urlsplit(resolved)
    return (
        expected.scheme.lower() == actual.scheme.lower() == "https"
        and bool(expected.hostname)
        and expected.netloc.lower() == actual.netloc.lower()
        and (expected.path.rstrip("/") or "/") == (actual.path.rstrip("/") or "/")
    )


def parse_json_bytes(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8"))


def count_cards(raw: bytes) -> int:
    return len(CARD_RE.findall(raw.decode("utf-8", "replace")))


def consultation_semantics_ok(raw: bytes) -> bool:
    """Active consultation hub must not expose unverified deadline copy."""
    text = raw.decode("utf-8", "replace")
    return (
        "Termen:</b> Neconfirmat" not in text
        and "Termen:</b> Necunoscut" not in text
        and "UNKNOWN" not in text
    )



CARD_BLOCK_RE = re.compile(
    r"""<article\b[^>]*\bdata-dossier-id\s*=\s*["'][^"']+["'][^>]*>.*?</article>""",
    re.IGNORECASE | re.DOTALL,
)
CARD_ID_RE = re.compile(r"""\bdata-dossier-id\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
STATIC_CARD_RE = re.compile(
    r"""<article\b[^>]*\bclass\s*=\s*["'][^"']*\bstaticCard\b[^"']*["'][^>]*>""",
    re.IGNORECASE,
)
DEADLINE_TEXT_RE = re.compile(r"""<b>\s*Termen:\s*</b>\s*([^<]*?)\s*</span>""", re.IGNORECASE)
# Four known P0 source-OPEN dossiers warrant independent live detail checks.
# This catches a mixed Pages release where the OPEN hub is fresh but details
# remain stale. These URLs are verification targets, not authority/proofs.
PRIORITY_DETAIL_ROUTES = {
    "pr-centru-clusters-122": "dosare/pr-centru-clusters-122-clustere-inovative/",
    "afir-fm-public-autoconsum-2026": "dosare/afir-fm-public-autoconsum-2026/",
    "afir-fm-public-storage-2026": "dosare/afir-fm-public-storage-2026/",
    "afir-dr12-2026": "dosare/afir-dr12-2026/",
}
DETAIL_STATUS_RE = re.compile(r'<span class="status status-([a-z_-]+)">', re.IGNORECASE)
DETAIL_DEADLINE_RE = re.compile(
    r'<div class="detailFact">\s*<small>Termen</small>\s*<b>([^<]*)</b>',
    re.IGNORECASE,
)


def open_listing_semantics(raw: bytes, clock: dt.datetime) -> tuple[bool, list[str]]:
    """Do not accept a matching-but-stale OPEN listing as a successful release.

    This is a negative publication gate only. It never promotes a call to OPEN,
    infers CLOSED, changes source evidence, or uses a source label as proof.
    """
    source = raw.decode("utf-8", "replace")
    blocks = CARD_BLOCK_RE.findall(source)
    if len(blocks) != count_cards(raw) or len(STATIC_CARD_RE.findall(source)) != len(blocks):
        return False, ["unparseable_or_unidentified_dossier_card_markup"]
    failures: list[str] = []
    seen_ids: set[str] = set()
    for block in blocks:
        match_id = CARD_ID_RE.search(block)
        dossier_id = match_id.group(1) if match_id else "unknown"
        if dossier_id in seen_ids:
            failures.append(f"{dossier_id}:duplicate_dossier_card_id")
        # The DR-12 aggregate is not an independently accepting component.
        # AFIR's 11 Nov official notice closes 'alte sectoare'; zootehnic is
        # separately assessed. This is a *negative* release gate, not CLOSED.
        if dossier_id == "afir-dr12-2026":
            failures.append("afir-dr12-2026:aggregate_open_without_component_reconciliation")
        seen_ids.add(dossier_id)
        # The /deschise/ surface must carry an explicit OPEN badge per card.
        if not re.search(r'\bstatus-open\b', block, re.IGNORECASE):
            failures.append(f"{dossier_id}:non_open_badge")
            continue
        deadlines = DEADLINE_TEXT_RE.findall(block)
        if len(deadlines) != 1:
            failures.append(f"{dossier_id}:missing_or_conflicting_exact_deadline")
            continue
        deadline_text = html.unescape(deadlines[0]).strip()
        if not has_explicit_open_deadline_clock(deadline_text):
            failures.append(f"{dossier_id}:unverified_deadline_clock")
            continue
        deadline = parse_date(deadline_text)
        if deadline is None or deadline <= clock:
            failures.append(f"{dossier_id}:expired_or_invalid_deadline")
    return not failures, failures

def priority_detail_semantics(raw: bytes, clock: dt.datetime) -> tuple[bool, str, list[str]]:
    """Negative gate for P0 detail: no stale OPEN or contradictory REVIEW copy.

    An exact future clock alone never constitutes new OPEN authorization; that
    belongs to the canonical source reconciler. This function only vetoes unsafe
    public readback and never changes the source status.
    """
    source = raw.decode("utf-8", "replace")
    statuses = DETAIL_STATUS_RE.findall(source)
    if len(statuses) != 1:
        return False, "", ["detail_missing_or_ambiguous_status"]
    status = statuses[0].lower()
    failures: list[str] = []
    if status == "open":
        deadlines = DETAIL_DEADLINE_RE.findall(source)
        if len(deadlines) != 1:
            failures.append("detail_missing_or_ambiguous_deadline")
        else:
            deadline_text = html.unescape(deadlines[0]).strip()
            if not has_explicit_open_deadline_clock(deadline_text):
                failures.append("detail_unverified_deadline_clock")
            else:
                when = parse_date(deadline_text)
                if when is None or when <= clock:
                    failures.append("detail_expired_or_invalid_deadline")
    elif status == "review":
        # A REVIEW badge is ineffective if the crawlable decision body still
        # tells the reader that the call is open or to submit immediately.
        if re.search(r'<strong>\s*ACȚIONEAZĂ\s*</strong>', source, re.IGNORECASE):
            failures.append("review_still_actionable")
        if re.search(r'<li>\s*Stare apel:\s*(?:OPEN|DESCHIS)\s*\.?\s*</li>', source, re.IGNORECASE):
            failures.append("review_still_claims_open")
        # A mixed/cached release can carry a REVIEW badge but keep an old
        # standfirst or decision action. Only check decision-bearing surfaces,
        # not historical provenance or the official source transcript.
        if re.search(
            r"""<p\s+class=["']standfirst["'][^>]*>[^<]*Sunt\s+confirmate:\s*(?:OPEN|DESCHIS)\b""",
            source, re.IGNORECASE,
        ):
            failures.append("review_stale_open_standfirst")
        for decision in re.findall(
            r"""<div\s+class=["']decisionBox["'][^>]*>(.*?)</div>""",
            source, re.IGNORECASE | re.DOTALL,
        ):
            visible = html.unescape(re.sub(r"<[^>]+>", " ", decision))
            import unicodedata
            plain = "".join(
                ch for ch in unicodedata.normalize("NFKD", visible.casefold())
                if not unicodedata.combining(ch)
            )
            if re.search(
                r"\b(?:depunerea\s+(?:este|ramane)\s+deschisa"
                r"|(?<!nu\s)(?<!nu mai\s)depune\s+(?:acum|inainte|cererea)"
                r"|incepe\s+screeningul\s+si\s+planul\s+de\s+depunere)\b",
                plain,
            ):
                failures.append("review_still_invites_submission")
                break
        # REVIEW must also neutralize the actionable "Ce trebuie făcut acum"
        # and "Decizia rapidă" section lists. A mixed deployment can preserve
        # old <li> advice even after the badge, standfirst and decisionBox
        # were replaced. Restrict checks to advice sections, not provenance.
        for section_title, section_body in re.findall(
            r"""<section\b[^>]*\bclass=["'][^"']*\bdetailSection\b[^"']*["'][^>]*>\s*<h2>(.*?)</h2>(.*?)</section>""",
            source, re.IGNORECASE | re.DOTALL,
        ):
            import unicodedata
            title_text = html.unescape(re.sub(r"<[^>]+>", " ", section_title))
            title_plain = "".join(
                ch for ch in unicodedata.normalize("NFKD", title_text.casefold())
                if not unicodedata.combining(ch)
            ).strip()
            if title_plain not in {"ce trebuie facut acum", "decizia rapida"}:
                continue
            for advice in re.findall(r"<li\b[^>]*>(.*?)</li>", section_body, re.IGNORECASE | re.DOTALL):
                visible = html.unescape(re.sub(r"<[^>]+>", " ", advice))
                plain = "".join(
                    ch for ch in unicodedata.normalize("NFKD", visible.casefold())
                    if not unicodedata.combining(ch)
                ).strip()
                if re.search(
                    r"\b(?:incepe\s+screeningul\s+si\s+planul\s+de\s+depunere"
                    r"|planifica\s+depunerea\s+pornind\s+de\s+la\s+termenul\s+confirmat"
                    r"|depunerea\s+este\s+deschisa"
                    r"|(?<!nu\s)(?<!nu mai\s)depune\s+acum)\b",
                    plain,
                ):
                    failures.append("review_still_invites_submission_in_advice_section")
                    break
            if "review_still_invites_submission_in_advice_section" in failures:
                break
    return not failures, status, failures


def compare_manifest(expected: dict[str, Any], observed: dict[str, Any]) -> tuple[bool, list[str]]:
    if expected == observed:
        return True, []
    keys = sorted(set(expected) | set(observed))
    mismatches = [key for key in keys if expected.get(key) != observed.get(key)]
    return False, mismatches


def self_test() -> int:
    sample = {
        "schemaVersion": 1,
        "generatedAt": "2026-09-24T10:22:01Z",
        "currentOpen": 11,
        "prepare": 25,
        "consultations": 5,
        "policy": {"materialFactsInvented": False},
    }
    same = json.loads(json.dumps(sample))
    ok, mismatches = compare_manifest(sample, same)
    assert ok and not mismatches
    changed = json.loads(json.dumps(sample))
    changed["prepare"] = 24
    ok, mismatches = compare_manifest(sample, changed)
    assert not ok and mismatches == ["prepare"]
    assert count_cards(b'<article data-dossier-id="a"></article><div data-dossier-id=\'b\'></div>') == 2
    assert count_cards(b"<article></article>") == 0
    assert consultation_semantics_ok(b"<article><b>Termen:</b> 29 septembrie 2026</article>")
    clock = dt.datetime(2026, 11, 19, 22, 30, tzinfo=dt.timezone.utc)
    def card(dossier_id: str, deadline: str, status: str = "open") -> bytes:
        return (
            f'<article class="staticCard" data-dossier-id="{dossier_id}">'
            f'<span class="status status-{status}">DESCHIS</span>'
            f'<span><b>Termen:</b> {deadline}</span></article>'
        ).encode("utf-8")
    future = card("afir-autoconsum", "20 noiembrie 2026, 23:59")
    expired = card("pr-centru-clusters-122", "2026-11-06T12:00:00+02:00")
    assert open_listing_semantics(future, clock) == (True, [])
    assert not open_listing_semantics(expired, clock)[0]
    assert not open_listing_semantics(future + expired, clock)[0]
    # Duplicate or unidentified cards must not bypass priority list/detail parity.
    assert not open_listing_semantics(future + future, clock)[0]
    # The global DR-12 2 Dec deadline cannot reopen the exhausted component.
    # An exact component identity and current official endpoint are prerequisites.
    dr12_aggregate = card("afir-dr12-2026", "2 decembrie 2026, 16:00")
    assert "afir-dr12-2026:aggregate_open_without_component_reconciliation" in open_listing_semantics(
        dr12_aggregate, clock
    )[1]
    assert not open_listing_semantics(
        b'<article class="staticCard"><span class="status status-open">DESCHIS</span>'
        b'<span><b>Termen:</b> 20 noiembrie 2026, 23:59</span></article>', clock
    )[0]
    assert not open_listing_semantics(card("no-clock", "2 decembrie 2026"), clock)[0]
    assert not open_listing_semantics(card("no-offset", "2026-12-02T16:00"), clock)[0]
    assert not open_listing_semantics(card("dst-ambiguous", "25 octombrie 2026, 03:30"), clock)[0]
    assert not open_listing_semantics(card("wrong-badge", "2 decembrie 2026, 16:00", "review"), clock)[0]
    assert not open_listing_semantics(card("missing-deadline", ""), clock)[0]
    assert open_listing_semantics(future, dt.datetime(2026, 11, 20, 21, 59, 1, tzinfo=dt.timezone.utc))[0] is False
    def detail(status: str, deadline: str, action: str = "VERIFICĂ STAREA", claim: str = "") -> bytes:
        return (
            f'<div class="detailMeta"><span class="status status-{status}">STARE</span></div>'
            f'<div class="detailFact"><small>Termen</small><b>{deadline}</b><span>CONFIRMED</span></div>'
            f'<div class="decisionBox"><strong>{action}</strong></div>'
            f'<ul><li>{claim}</li></ul>'
        ).encode("utf-8")
    exact = detail("open", "20 noiembrie 2026, 23:59")
    before = dt.datetime(2026, 11, 20, 21, 58, 59, tzinfo=dt.timezone.utc)
    after = dt.datetime(2026, 11, 20, 21, 59, 1, tzinfo=dt.timezone.utc)
    assert priority_detail_semantics(exact, before) == (True, "open", [])
    assert not priority_detail_semantics(exact, after)[0]
    assert not priority_detail_semantics(detail("open", "20 noiembrie 2026"), before)[0]
    assert priority_detail_semantics(detail("review", "20 noiembrie 2026, 23:59"), after) == (True, "review", [])
    assert not priority_detail_semantics(detail("review", "20 noiembrie 2026, 23:59", "ACȚIONEAZĂ"), after)[0]
    assert not priority_detail_semantics(detail("review", "20 noiembrie 2026, 23:59", claim="Stare apel: OPEN."), after)[0]
    # Regression: badge-only REVIEW does not authorize positive OPEN copy.
    review = detail("review", "20 noiembrie 2026, 23:59")
    stale_standfirst = b'<p class="standfirst">Sunt confirmate: open; termen expirat.</p>'
    assert "review_stale_open_standfirst" in priority_detail_semantics(
        review + stale_standfirst, after
    )[2]
    assert "review_still_invites_submission" in priority_detail_semantics(
        detail("review", "20 noiembrie 2026, 23:59", "Depunerea este deschisă. Depune acum."), after
    )[2]
    assert "review_still_invites_submission" in priority_detail_semantics(
        detail("review", "20 noiembrie 2026, 23:59", "Începe screeningul și planul de depunere."), after
    )[2]
    assert priority_detail_semantics(
        detail("review", "20 noiembrie 2026, 23:59", "Nu depune înainte de reconcilierea oficială."), after
    )[0]
    # Badge-only REVIEW cannot mask old actionable checklist copy in a mixed deployment.
    stale_advice = (
        '<section class="detailSection"><h2>Ce trebuie făcut acum</h2><ul>'
        '<li>Planifică depunerea pornind de la termenul confirmat: 6 noiembrie 2026.</li>'
        '</ul></section>'
    ).encode("utf-8")
    assert "review_still_invites_submission_in_advice_section" in priority_detail_semantics(
        review + stale_advice, after
    )[2]
    protective_advice = (
        '<section class="detailSection"><h2>Ce trebuie făcut acum</h2><ul>'
        '<li>Nu depune înainte de reconcilierea oficială.</li>'
        '</ul></section>'
    ).encode("utf-8")
    assert priority_detail_semantics(review + protective_advice, after)[0]
    assert not priority_detail_semantics(b"<html>missing lifecycle</html>", after)[0]
    assert not consultation_semantics_ok(b"<article><b>Termen:</b> Neconfirmat</article>")
    assert same_public_route(
        "https://partener.eu/finantari/deschise/",
        "https://partener.eu/finantari/deschise/?partener_readback=x",
    )
    assert not same_public_route(
        "https://partener.eu/finantari/deschise/",
        "https://partener.eu/finantari/in-pregatire/",
    )
    assert not same_public_route(
        "https://partener.eu/finantari/deschise/",
        "https://offsite.example/finantari/deschise/",
    )
    assert not same_public_route(
        "https://partener.eu/finantari/deschise/",
        "http://partener.eu/finantari/deschise/",
    )
    busted = cache_busted("https://partener.eu/consultari/?x=1", "abc")
    assert "x=1" in busted and "partener_readback=abc" in busted
    print("PASS public deploy readback proof self-test")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--delay-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.attempts < 1:
        parser.error("--attempts must be >= 1")

    manifest_path = pathlib.Path(args.manifest)
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    required_counts = {
        "finantari/deschise/": int(expected.get("currentOpen", -1)),
        "finantari/in-pregatire/": int(expected.get("prepare", -1)),
        "consultari/": int(expected.get("consultations", -1)),
    }
    if any(value < 0 for value in required_counts.values()):
        raise SystemExit("Manifest missing one of currentOpen/prepare/consultations")

    base_url = args.base_url.rstrip("/") + "/"
    manifest_url = urllib.parse.urljoin(base_url, "static-public-manifest.json")
    expected_hash = sha256_bytes(canonical_bytes(expected))
    attempts_log: list[dict[str, Any]] = []
    final_observed: dict[str, Any] | None = None
    final_routes: dict[str, Any] = {}
    final_priority_details: dict[str, Any] = {}
    final_hash: str | None = None
    final_mismatches: list[str] = []
    passed = False

    for attempt in range(1, args.attempts + 1):
        token = f"{expected.get('generatedAt', 'unknown')}-{attempt}-{int(time.time())}"
        record: dict[str, Any] = {"attempt": attempt, "errors": []}
        try:
            code, raw, resolved = fetch_bytes(manifest_url, timeout=args.timeout_seconds, token=token)
            if not same_public_route(manifest_url, resolved):
                raise ValueError("manifest_redirected_off_canonical_origin_or_route")
            observed = parse_json_bytes(raw)
            if not isinstance(observed, dict):
                raise ValueError("public manifest is not a JSON object")
            same, mismatches = compare_manifest(expected, observed)
            observed_hash = sha256_bytes(canonical_bytes(observed))
            record["manifest"] = {
                "http_status": code,
                "resolved_url": resolved,
                "matches": same,
                "mismatch_keys": mismatches,
                "sha256": observed_hash,
            }
            final_observed = observed
            final_hash = observed_hash
            final_mismatches = mismatches

            route_results: dict[str, Any] = {}
            routes_ok = True
            open_listing_ids: set[str] = set()
            for route, expected_count in required_counts.items():
                route_url = urllib.parse.urljoin(base_url, route)
                r_code, r_raw, r_resolved = fetch_bytes(route_url, timeout=args.timeout_seconds, token=token)
                observed_count = count_cards(r_raw)
                semantic_ok = True
                semantic_failures: list[str] = []
                if route == "consultari/":
                    semantic_ok = consultation_semantics_ok(r_raw)
                elif route == "finantari/deschise/":
                    semantic_ok, semantic_failures = open_listing_semantics(
                        r_raw, dt.datetime.now(dt.timezone.utc)
                    )
                    open_listing_ids = set(CARD_ID_RE.findall(r_raw.decode("utf-8", "replace")))
                if not same_public_route(route_url, r_resolved):
                    semantic_failures.append("route_redirected_off_canonical_origin_or_path")
                    semantic_ok = False
                route_ok = r_code == 200 and observed_count == expected_count and semantic_ok
                route_results[route] = {
                    "http_status": r_code,
                    "resolved_url": r_resolved,
                    "expected_cards": expected_count,
                    "observed_cards": observed_count,
                    "matches": route_ok,
                    "semantic_freshness_ok": semantic_ok,
                    "semantic_failures": semantic_failures,
                }
                routes_ok = routes_ok and route_ok
            record["routes"] = route_results
            final_routes = route_results
            # Independent P0 dossier readback. A fresh listing and matching
            # manifest cannot mask a stale detail, nor the reverse.
            detail_results: dict[str, Any] = {}
            details_ok = True
            for dossier_id, route in PRIORITY_DETAIL_ROUTES.items():
                detail_url = urllib.parse.urljoin(base_url, route)
                d_code, d_raw, d_resolved = fetch_bytes(
                    detail_url, timeout=args.timeout_seconds, token=token
                )
                detail_ok, detail_status, failures = priority_detail_semantics(
                    d_raw, dt.datetime.now(dt.timezone.utc)
                )
                if (dossier_id in open_listing_ids) != (detail_status == "open"):
                    failures.append("open_listing_detail_state_disagreement")
                if dossier_id == "afir-dr12-2026" and detail_status == "open":
                    # Until source-scoped, per-component acceptance is verified,
                    # a generic DR-12 OPEN dossier is misleading even if its
                    # aggregate 2 December calendar clock is in the future.
                    failures.append("dr12_aggregate_open_without_component_reconciliation")
                # Matching path alone is insufficient: identical HTML from
                # an unrelated origin is not proof of our actual deployment.
                if not same_public_route(detail_url, d_resolved):
                    failures.append("detail_redirected_off_canonical_origin_or_path")
                detail_ok = d_code == 200 and detail_ok and not failures
                detail_results[dossier_id] = {
                    "http_status": d_code,
                    "resolved_url": d_resolved,
                    "lifecycle": detail_status,
                    "semantic_freshness_ok": detail_ok,
                    "semantic_failures": failures,
                }
                details_ok = details_ok and detail_ok
            record["priority_details"] = detail_results
            final_priority_details = detail_results
            passed = same and routes_ok and details_ok
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError, OSError) as exc:
            record["errors"].append(f"{type(exc).__name__}: {exc}")
            passed = False
        attempts_log.append(record)
        if passed:
            break
        if attempt < args.attempts:
            time.sleep(args.delay_seconds)

    result = {
        "status": "PASS" if passed else "FAIL",
        "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_url": base_url,
        "expected_manifest_sha256": expected_hash,
        "observed_manifest_sha256": final_hash,
        "manifest_matches": bool(final_observed is not None and not final_mismatches and final_hash == expected_hash),
        "manifest_mismatch_keys": final_mismatches,
        "expected_counts": {
            "currentOpen": expected.get("currentOpen"),
            "prepare": expected.get("prepare"),
            "consultations": expected.get("consultations"),
        },
        "observed_counts": {
            route: details.get("observed_cards") for route, details in final_routes.items()
        },
        "routes": final_routes,
        "priority_details": final_priority_details,
        "attempts_used": len(attempts_log),
        "attempts": attempts_log,
        "fail_closed": True,
    }
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "attempts"}, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
