#!/usr/bin/env python3
"""e-DRIVE consultation discovery is not an application call or official source receipt."""
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
p = ROOT / "partener-eu/validation/discovery/edrive-guides-consultation-20261109.json"
d = json.loads(p.read_text(encoding="utf-8"))

assert d["candidate_lifecycle"] == "CONSULTATION"
assert d["observation_state"] == "SECONDARY_DISCOVERY_OFFICIAL_RAW_UNAVAILABLE"
assert d["publication_effect"] == "NONE"
assert d["publish_authorized"] is False
assert d["open_call_authorized"] is False
assert d["official_application_window_verified"] is False
assert d["official_call_topic_identifier_verified"] is False
assert d["material_fact_action"] == "NONE"

assert d["unadmitted_secondary_claims"]["application_deadline"] is None
assert d["unadmitted_secondary_claims"]["call_opening_date"] is None
assert d["unadmitted_secondary_claims"]["feedback_deadline_candidate"] == "2026-11-18"

official = d["official_candidate_sources"]
assert len(official) == 2
assert all(urlsplit(x["url"]).scheme == "https" and
           urlsplit(x["url"]).hostname in {"www.mt.ro", "mt.ro"} for x in official)
assert all(x[k] is None for x in official for k in
           ("fetched_at_utc", "raw_sha256", "parser_version", "run_id"))
assert len(d["discovery_sources"]) >= 2
assert all(x["class"] == "SECONDARY_DISCOVERY_NOT_AUTHORITY"
           for x in d["discovery_sources"])
assert any("original MTI" in s or "MTI announcement" in s
           for s in d["required_next_gate"])
assert "1392" in d["historical_backlog_reference"]
print("PASS e-DRIVE M1/M2 consultation discovery remains unverified and non-authorizing")
