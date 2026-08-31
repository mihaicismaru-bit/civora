#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "romd_transport_diagnostic.py"
spec = importlib.util.spec_from_file_location("romd_transport_diagnostic", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def expect_error(fn, needle: str) -> None:
    try:
        fn()
    except Exception as exc:
        if needle.casefold() not in str(exc).casefold():
            raise AssertionError(f"expected error containing {needle!r}, got {exc!r}") from exc
        return
    raise AssertionError(f"expected failure containing {needle!r}")


# URL boundary: HTTPS + exact official ROMD hosts + bounded programme paths only.
mod.validate_candidate_url("https://ro-md.net/en/programme-2021-2027")
mod.validate_candidate_url("https://www.ro-md.net/en/news-2021-2027/example")
expect_error(lambda: mod.validate_candidate_url("http://ro-md.net/en/programme-2021-2027"), "HTTPS")
expect_error(lambda: mod.validate_candidate_url("https://example.com/en/programme-2021-2027"), "allowlist")
expect_error(lambda: mod.validate_candidate_url("https://ro-md.net/administrator"), "outside allowlist")
expect_error(lambda: mod.validate_candidate_url("https://user:pass@ro-md.net/en/programme-2021-2027"), "userinfo")

# Marker classification is deterministic and never equates transport health with call facts.
healthy_raw = b"Public consultation Romania Moldova Interreg chapter 2028 2034"
healthy = mod.classify_probe(status=200, raw=healthy_raw, error_kind=None)
assert healthy["health_state"] == "HEALTHY_PROGRAMMING_MARKERS", healthy
assert healthy["marker_report"]["all_required_markers_present"] is True

partial = mod.classify_probe(status=200, raw=b"Romania Moldova programme homepage", error_kind=None)
assert partial["health_state"] == "HEALTHY_DISCOVERY_ONLY", partial
assert partial["marker_report"]["all_required_markers_present"] is False

cert = mod.classify_probe(status=None, raw=None, error_kind="CERTIFICATE_VERIFY_FAILED")
assert cert["health_state"] == "DEGRADED_CERTIFICATE_VERIFY_FAILED", cert

transport = mod.classify_probe(status=None, raw=None, error_kind="URLERROR")
assert transport["health_state"] == "DEGRADED_TRANSPORT", transport

http = mod.classify_probe(status=503, raw=b"temporarily unavailable", error_kind=None)
assert http["health_state"] == "DEGRADED_HTTP", http

# Output policy remains non-authorizing even if a transport candidate is healthy.
synthetic = {
    "adapter_id": mod.ADAPTER_ID,
    "run_id": "synthetic",
    "fetched_at": "2026-08-31T23:50:00Z",
    "source_family": "INTERREG",
    "programme_family": "INTERREG_NEXT_RO_MD",
    "programme_period": "2028-2034",
    "authority_class": "T1_OFFICIAL_PROGRAMME_TRANSPORT_DIAGNOSTIC",
    "observation_state": "SOURCE_HEALTH_DIAGNOSTIC",
    "market_intelligence_only": True,
    "material_fact_use": False,
    "open_call_authorized": False,
    "deadline_authorized": False,
    "budget_authorized": False,
    "eligibility_authorized": False,
    "publish_authorized": False,
    "distribution_authorized": False,
    "call_alert_authorized": False,
    "registry_mutation_authorized": False,
    "publication_effect": "NONE",
    "canonical_corpus_mutation": False,
    "tls_verification_disabled": False,
    "proxy_used": False,
    "candidate_count": len(mod.CANDIDATES),
    "healthy_programming_marker_count": 1,
    "healthy_exact_article_count": 1,
    "recommended_primary_url_candidate": mod.CANDIDATES[0]["url"],
    "recommendation_semantics": "TRANSPORT_CANDIDATE_ONLY_REQUIRES_SEPARATE_REGISTRY_REVIEW",
    "probes": [],
}
for candidate in mod.CANDIDATES:
    synthetic["probes"].append({
        "candidate_id": candidate["id"],
        "authority_role": candidate["authority_role"],
        "requested_url": candidate["url"],
        "final_url": candidate["url"],
        "http_status": 200,
        "content_type": "text/html",
        "raw_sha256": "a" * 64,
        "raw_size_bytes": 123,
        "error_kind": None,
        "error": None,
        "health_state": "HEALTHY_PROGRAMMING_MARKERS",
        "marker_report": {"all_required_markers_present": True, "missing_marker_groups": []},
    })
mod.validate_output(synthetic)

for forbidden_key in mod.MATERIAL_FLAGS:
    bad = dict(synthetic)
    bad[forbidden_key] = True
    expect_error(lambda bad=bad: mod.validate_output(bad), "authorizing")

bad_tls = dict(synthetic)
bad_tls["tls_verification_disabled"] = True
expect_error(lambda: mod.validate_output(bad_tls), "transport safety")

bad_proxy = dict(synthetic)
bad_proxy["proxy_used"] = True
expect_error(lambda: mod.validate_output(bad_proxy), "transport safety")

print("PASS ROMD transport diagnostic remains bounded, TLS-verifying and non-authorizing")
