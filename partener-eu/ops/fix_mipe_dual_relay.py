#!/usr/bin/env python3
"""Add fail-closed dual-relay access for otherwise unreachable MIPE pages.

A MIPE page may be extracted through Jina Reader only when a second independent
Google Translate fetch corroborates the same official page structure. The
canonical source remains mfe.gov.ro; both transport hashes and the shared
link-path evidence are persisted. No search snippet is accepted as a fact.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "ingest" / "mipe_resilient_ingest.py"
text = PATH.read_text(encoding="utf-8")
changed = False

helper = r'''def translate_original_url(url: str, base_canonical: str) -> str | None:
    """Map a Google Translate wrapper URL back to the official MIPE URL."""
    try:
        absolute = urllib.parse.urljoin(base_canonical, url)
        parsed = urllib.parse.urlparse(absolute)
        host = (parsed.hostname or "").lower()
        if host == "mfe-gov-ro.translate.goog":
            query = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if not k.startswith("_x_tr_")]
            candidate = urllib.parse.urlunparse(("https", "mfe.gov.ro", parsed.path or "/", "", urllib.parse.urlencode(query), ""))
            return canonicalize(candidate)
        return canonicalize(absolute)
    except Exception:
        return None


def google_translate_url(canonical: str) -> str | None:
    parsed = urllib.parse.urlparse(canonical)
    if (parsed.hostname or "").lower() not in {"mfe.gov.ro", "www.mfe.gov.ro"}:
        return None
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query += [("_x_tr_sl", "ro"), ("_x_tr_tl", "en"), ("_x_tr_hl", "en")]
    return urllib.parse.urlunparse(("https", "mfe-gov-ro.translate.goog", parsed.path or "/", "", urllib.parse.urlencode(query), ""))


def meaningful_official_paths(links: Iterable[tuple[str, str]], base: str, translated: bool = False) -> set[str]:
    paths: set[str] = set()
    for href, _label in links:
        official = translate_original_url(href, base) if translated else canonicalize(href, base)
        if not official:
            continue
        path = urllib.parse.urlparse(official).path.rstrip("/") or "/"
        if path in {"/", "/contact", "/despre-noi"}:
            continue
        if any(path.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".css", ".js")):
            continue
        paths.add(path)
    return paths


def fetch_dual_relay(canonical: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Retrieve a canonical MIPE page through two independent live relays.

    Jina supplies structured text and original official links. Google Translate
    supplies an independent live HTML fetch. Publication is allowed only when
    the Reader source URL is exact, the translated page has MIPE signatures,
    and the two views share meaningful official link paths.
    """
    translate_url = google_translate_url(canonical)
    if not translate_url:
        return None, {"target": canonical, "ok": False, "transport": "dual-relay", "error": "translate_mapping_unavailable"}

    reader_endpoint = "https://r.jina.ai/" + canonical
    reader = fetch(reader_endpoint, timeout=22, attempts=1, accept="text/plain,text/markdown,*/*")
    translated = fetch(translate_url, timeout=22, attempts=1, accept="text/html,application/xhtml+xml,*/*;q=0.7")
    evidence: dict[str, Any] = {
        "target": canonical,
        "ok": False,
        "transport": "canonical-dual-relay",
        "readerUrl": reader_endpoint,
        "translateUrl": translate_url,
        "readerError": reader.get("error"),
        "translateError": translated.get("error"),
    }
    if not reader.get("ok") or not translated.get("ok"):
        return None, evidence

    parsed_reader = parse_reader(reader["data"], canonical)
    parsed_translate = parse_html(translated["data"])
    if not parsed_reader or canonicalize(parsed_reader.get("canonical") or "") != canonical:
        evidence["error"] = "reader_source_mismatch"
        return None, evidence

    raw_translate = translated["data"].decode("utf-8", errors="ignore").lower()
    signatures = {
        "mipeHost": "mfe.gov.ro" in raw_translate,
        "ministry": ("ministerul investi" in raw_translate or "ministry of investment" in raw_translate),
        "wordpress": "wp-content" in raw_translate,
    }
    if sum(bool(value) for value in signatures.values()) < 2:
        evidence.update({"error": "translate_official_signature_insufficient", "signatures": signatures})
        return None, evidence

    reader_paths = meaningful_official_paths(parsed_reader.get("links", []), canonical)
    translate_paths = meaningful_official_paths(parsed_translate.get("links", []), canonical, translated=True)
    shared = sorted(reader_paths & translate_paths)
    target_path = urllib.parse.urlparse(canonical).path.rstrip("/") or "/"
    target_specific = [path for path in shared if path == target_path or path.startswith(target_path + "/") or path.lower().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".7z"))]

    # Template-heavy pages still share many official links. Require either one
    # target/document path or at least five independent shared official paths.
    if not target_specific and len(shared) < 5:
        evidence.update({
            "error": "dual_relay_link_consensus_insufficient",
            "sharedOfficialPathCount": len(shared),
            "sharedOfficialPaths": shared[:20],
            "signatures": signatures,
        })
        return None, evidence

    evidence.update({
        "ok": True,
        "transport": "canonical-dual-relay-corroborated",
        "verification": "CANONICAL_DUAL_RELAY_CORROBORATED",
        "readerSha256": hashlib.sha256(reader["data"]).hexdigest(),
        "translateSha256": hashlib.sha256(translated["data"]).hexdigest(),
        "readerBytes": len(reader["data"]),
        "translateBytes": len(translated["data"]),
        "sharedOfficialPathCount": len(shared),
        "sharedOfficialPaths": shared[:30],
        "targetSpecificPaths": target_specific[:20],
        "signatures": signatures,
    })
    parsed_reader["canonical"] = canonical
    return parsed_reader, evidence


'''

marker = "def reader_url(target: str) -> str:\n"
if "def fetch_dual_relay(" in text:
    print("MIPE dual relay helper: already applied")
elif marker in text:
    text = text.replace(marker, helper + marker, 1)
    changed = True
    print("MIPE dual relay helper: applied")
else:
    raise SystemExit("Reader helper marker missing; refusing blind dual-relay edit")

first_party_marker = "    relay = fetch_first_party_relay(canonical)\n"
dual_before_first_party = '''    dual_parsed, dual_evidence = fetch_dual_relay(canonical)
    if dual_parsed is not None:
        dual_evidence["directError"] = direct.get("error")
        return dual_parsed, dual_evidence

    relay = fetch_first_party_relay(canonical)
'''
direct_only_block = '''    return None, {
        "target": canonical,
        "ok": False,
        "transport": "direct-only",
        "directError": direct.get("error"),
        "policy": "search-discovery-only-when-direct-unavailable",
    }
'''
dual_direct_block = '''    dual_parsed, dual_evidence = fetch_dual_relay(canonical)
    if dual_parsed is not None:
        dual_evidence["directError"] = direct.get("error")
        return dual_parsed, dual_evidence

    return None, {
        "target": canonical,
        "ok": False,
        "transport": "direct+dual-relay",
        "directError": direct.get("error"),
        "dualRelayError": dual_evidence.get("error") or dual_evidence.get("readerError") or dual_evidence.get("translateError"),
        "dualRelayEvidence": dual_evidence,
        "policy": "fail-closed-when-direct-and-dual-corroborated-transports-unavailable",
    }
'''
if "dual_parsed, dual_evidence = fetch_dual_relay(canonical)" in text:
    print("MIPE dual relay fetch path: already applied")
elif first_party_marker in text:
    text = text.replace(first_party_marker, dual_before_first_party, 1)
    changed = True
    print("MIPE dual relay fetch path: inserted before first-party relay")
elif direct_only_block in text:
    text = text.replace(direct_only_block, dual_direct_block, 1)
    changed = True
    print("MIPE dual relay fetch path: applied")
else:
    raise SystemExit("No supported MIPE fetch fallback block found")

old_tier = '    tier = "T1_RELAY_ATTESTED" if "first-party-relay" in transport else ("T1" if transport.startswith("direct") else "T1_PROXY_TRANSPORT")'
plain_tier = '    tier = "T1" if transport.startswith("direct") else "T1_PROXY_TRANSPORT"'
new_tier = '    tier = "T1_DUAL_RELAY_CORROBORATED" if "dual-relay-corroborated" in transport else ("T1_RELAY_ATTESTED" if "first-party-relay" in transport else ("T1" if transport.startswith("direct") else "T1_PROXY_TRANSPORT"))'
if new_tier in text:
    print("MIPE dual relay tier: already applied")
elif old_tier in text:
    text = text.replace(old_tier, new_tier, 1); changed = True
elif plain_tier in text:
    text = text.replace(plain_tier, new_tier, 1); changed = True
else:
    raise SystemExit("MIPE tier assignment not found")

old_previous = '    return transport.startswith("direct")\n\n\ndef item_id'
new_previous = '    return transport.startswith("direct") or "dual-relay-corroborated" in transport\n\n\ndef item_id'
if new_previous in text:
    print("MIPE dual relay last-known-good: already applied")
elif old_previous in text:
    text = text.replace(old_previous, new_previous, 1); changed = True
else:
    raise SystemExit("MIPE previous-item provenance return not found")

old_direct_success = '    direct_success = any(str(result.get("transport", "")).startswith("direct") for result in successful)'
new_direct_success = '    direct_success = any(str(result.get("transport", "")).startswith("direct") or "dual-relay-corroborated" in str(result.get("transport", "")) for result in successful)'
if new_direct_success in text:
    print("MIPE dual relay health: already applied")
elif old_direct_success in text:
    text = text.replace(old_direct_success, new_direct_success, 1); changed = True
else:
    raise SystemExit("MIPE authoritative transport health expression not found")

if changed:
    PATH.write_text(text, encoding="utf-8")
