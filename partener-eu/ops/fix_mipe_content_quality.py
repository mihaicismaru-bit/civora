#!/usr/bin/env python3
"""Enforce the automation's fail-closed MIPE publication policy.

Search/proxy transports may discover official canonical URLs, but only a direct
successful fetch from an official MIPE-managed host may create or refresh a
published MIPE fact. Existing items without direct provenance are removed from
the public feed on the next ingest. The directly verified MySMIS feed remains
eligible through its CANONICAL_OFFICIAL_FETCH marker.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "ingest" / "mipe_resilient_ingest.py"
text = PATH.read_text(encoding="utf-8")
original = text

# Fail closed if the editorial safeguards expected by the current runtime have
# disappeared. Do not silently patch an unknown/older parser into production.
for marker in ("def decision_useful(", "def is_boilerplate(", "def classify_tag("):
    if marker not in text:
        raise SystemExit(f"MIPE runtime missing required quality gate: {marker}")

# 1) Reader/search copies must never be used as the factual body of an item.
#    Direct failure returns source-unavailable. Search discovery remains in the
#    runtime and may only enqueue canonical official URLs for a later direct
#    fetch attempt.
proxy_pattern = re.compile(
    r"\n    proxy = fetch\(reader_url\(canonical\), timeout=18, attempts=1, accept=\"text/plain,text/markdown,\*/\*\"\).*?"
    r"\n\n\ndef candidates_from_json",
    re.S,
)
proxy_replacement = '''
    return None, {
        "target": canonical,
        "ok": False,
        "transport": "direct-only",
        "directError": direct.get("error"),
        "policy": "search-discovery-only-when-direct-unavailable",
    }


def candidates_from_json'''
text, proxy_count = proxy_pattern.subn(proxy_replacement, text, count=1)
if proxy_count == 0 and '"transport": "direct-only"' not in text:
    raise SystemExit("Could not enforce direct-only fetch policy")

# 2) Last-known-good means last DIRECTLY verified good. Proxy-derived items from
#    earlier runs are not grandfathered into News.
previous_pattern = re.compile(
    r"def previous_item_useful\(item: dict\[str, Any\]\) -> bool:\n.*?\n\n\ndef item_id",
    re.S,
)
previous_replacement = '''def previous_item_useful(item: dict[str, Any]) -> bool:
    verification = str(item.get("verification") or "")
    transport = str(item.get("retrievalTransport") or "")
    if verification == "CANONICAL_OFFICIAL_FETCH":
        return True
    return transport.startswith("direct")


def item_id'''
text, previous_count = previous_pattern.subn(previous_replacement, text, count=1)
if previous_count == 0 and 'verification == "CANONICAL_OFFICIAL_FETCH"' not in text:
    raise SystemExit("Could not enforce last-known-good provenance policy")

# Preserve an accurate transport marker for a directly verified item that was
# produced by the dedicated MySMIS ingestion before this runtime sees it.
legacy_line = '        normalized.setdefault("retrievalTransport", "legacy-preserved")\n'
legacy_replacement = legacy_line + '''        if normalized.get("verification") == "CANONICAL_OFFICIAL_FETCH" and normalized.get("retrievalTransport") == "legacy-preserved":
            normalized["retrievalTransport"] = "direct-canonical-preserved"
'''
if legacy_line in text and "direct-canonical-preserved" not in text:
    text = text.replace(legacy_line, legacy_replacement, 1)

# 3) A PDDS seed may only crawl PDDS descendants under mfe.gov.ro/pdds/.
linked_line = '        candidates.extend(candidate_links(parsed.get("links", []), canonical))\n'
linked_replacement = '''        linked_candidates = candidate_links(parsed.get("links", []), canonical)
        if canonicalize(target) == "https://mfe.gov.ro/pdds/despre-program-programare/":
            linked_candidates = [
                candidate for candidate in linked_candidates
                if urllib.parse.urlparse(candidate["url"]).hostname == "mfe.gov.ro"
                and urllib.parse.urlparse(candidate["url"]).path.startswith("/pdds/")
            ]
        candidates.extend(linked_candidates)
'''
if linked_line in text and "linked_candidates = candidate_links" not in text:
    text = text.replace(linked_line, linked_replacement, 1)

# 4) Proxy success can never make the ingestion healthy or verified.
status_pattern = re.compile(
    r"    if current and direct_success:\n        status = \"OK\"\n        transport_mode = \"direct\"\n"
    r"    elif current and proxy_success:\n        status = \"OK_PROXY_VERIFIED\"\n        transport_mode = \"official-canonical-via-proxy\"\n"
    r"    elif items and successful:\n        status = \"OK_NO_NEW_RELEVANT_ITEMS\"\n        transport_mode = \"mixed\"\n"
    r"    elif items:\n        status = \"DEGRADED_LAST_KNOWN_GOOD_PRESERVED\"\n        transport_mode = \"unavailable\"\n"
    r"    else:\n        status = \"SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED\"\n        transport_mode = \"unavailable\"",
    re.S,
)
status_replacement = '''    if current and direct_success:
        status = "OK"
        transport_mode = "direct"
    elif items and direct_success:
        status = "OK_NO_NEW_RELEVANT_ITEMS"
        transport_mode = "direct"
    elif items:
        status = "DEGRADED_LAST_KNOWN_GOOD_PRESERVED"
        transport_mode = "direct-unavailable"
    else:
        status = "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED"
        transport_mode = "direct-unavailable"'''
text, status_count = status_pattern.subn(status_replacement, text, count=1)
if status_count == 0 and 'transport_mode = "direct-unavailable"' not in text:
    raise SystemExit("Could not enforce fail-closed source-health policy")

# Make the runtime contract self-describing for future operators.
text = text.replace(
    "3. Jina Reader as a transport proxy for an official canonical URL;\n4. Jina Search only for discovery, followed by a Reader fetch of the official\n   canonical URL before publication.\n\nA third-party page is never published as a MIPE fact. Proxy/search transport is\nrecorded explicitly. Historical feed items are preserved on outage.",
    "3. search/index transports for discovery of official canonical URLs only.\n\nOnly a successful direct fetch from the official canonical host may create or\nrefresh a published MIPE fact. Search/proxy copies are never factual sources.\nHistorical DIRECTLY verified feed items are preserved on outage.",
)

PATH.write_text(text, encoding="utf-8")
print("MIPE direct-provenance policy:", "updated" if text != original else "already enforced")
