#!/usr/bin/env python3
"""Make MIPE health telemetry distinguish direct and corroborated relay access."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "ingest" / "mipe_resilient_ingest.py"
text = PATH.read_text(encoding="utf-8")
changed = False

replacements = [
    (
        '    direct_success = any(str(result.get("transport", "")).startswith("direct") or "dual-relay-corroborated" in str(result.get("transport", "")) for result in successful)\n    proxy_success = any("jina-reader" in str(result.get("transport", "")) for result in successful)\n\n    if current and direct_success:\n        status = "OK"\n        transport_mode = "direct"\n    elif items and direct_success:\n        status = "OK_NO_NEW_RELEVANT_ITEMS"\n        transport_mode = "direct"\n    elif items:\n        status = "DEGRADED_LAST_KNOWN_GOOD_PRESERVED"\n        transport_mode = "direct-unavailable"\n    else:\n        status = "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED"\n        transport_mode = "direct-unavailable"\n',
        '    direct_success = any(str(result.get("transport", "")).startswith("direct") for result in successful)\n    dual_success = any("dual-relay-corroborated" in str(result.get("transport", "")) for result in successful)\n    first_party_relay_success = any("first-party-relay" in str(result.get("transport", "")) for result in successful)\n    authoritative_access = direct_success or dual_success or first_party_relay_success\n\n    if current and authoritative_access:\n        status = "OK"\n        transport_mode = "direct" if direct_success else ("first-party-relay-attested" if first_party_relay_success else "dual-relay-corroborated")\n    elif items and authoritative_access:\n        status = "OK_NO_NEW_RELEVANT_ITEMS"\n        transport_mode = "direct" if direct_success else ("first-party-relay-attested" if first_party_relay_success else "dual-relay-corroborated")\n    elif items:\n        status = "DEGRADED_LAST_KNOWN_GOOD_PRESERVED"\n        transport_mode = "authoritative-transports-unavailable"\n    else:\n        status = "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED"\n        transport_mode = "authoritative-transports-unavailable"\n',
        "transport-mode classification",
    ),
    (
        '        "directSuccessCount": sum(1 for result in successful if str(result.get("transport", "")).startswith("direct")),\n        "proxySuccessCount": sum(1 for result in successful if "jina-reader" in str(result.get("transport", ""))),\n',
        '        "directSuccessCount": sum(1 for result in successful if str(result.get("transport", "")).startswith("direct")),\n        "dualRelaySuccessCount": sum(1 for result in successful if "dual-relay-corroborated" in str(result.get("transport", ""))),\n        "firstPartyRelaySuccessCount": sum(1 for result in successful if "first-party-relay" in str(result.get("transport", ""))),\n        "discoveryOnlyTransportCount": sum(1 for result in successful if "jina-search" in str(result.get("transport", ""))),\n',
        "transport counters",
    ),
]

for old, new, label in replacements:
    if new in text:
        print(f"MIPE reporting {label}: already applied")
    elif old in text:
        text = text.replace(old, new, 1)
        changed = True
        print(f"MIPE reporting {label}: applied")
    else:
        raise SystemExit(f"Expected MIPE reporting pattern not found for {label}; refusing blind edit")

if changed:
    PATH.write_text(text, encoding="utf-8")
