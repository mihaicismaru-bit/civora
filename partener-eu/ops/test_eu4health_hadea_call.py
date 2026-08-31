#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))

from eu4health_hadea_call import DEFAULT_REGISTRY, extract_call_evidence, load_registry, resolve  # noqa: E402

MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
)


def assert_raises(fn, message: str) -> None:
    try:
        fn()
    except (ValueError, json.JSONDecodeError):
        return
    raise AssertionError(message)


def write_registry(data: dict) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
    with tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
    return Path(tmp.name)


def main() -> None:
    registry, registry_sha = load_registry()
    assert len(registry_sha) == 64
    assert registry["authority"]["allowed_hosts"] == ["hadea.ec.europa.eu"]
    assert registry["admission"]["funding_tenders_exact_topic_required_for_material_admission"] is True
    for key in MATERIAL_FLAGS:
        assert registry["policy"][key] is False

    synthetic = b"""
    <html><body>
      <h1>Health data for biotech innovation leveraging the European Health Data Space</h1>
      <div>Call for proposals</div>
      <div>Status Closed</div>
      <div>Reference EU4H-2026-SANTE-PJ-08</div>
      <div>Publication date 23 September 2025</div>
      <div>Opening date 23 September 2025</div>
      <div>Deadline model Single-stage</div>
      <div>Deadline date 6 January 2026, 17:00 (CET)</div>
      <div>Funding programme EU4Health Programme (2021/2027)</div>
      <a href="https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/EU4H-2026-SANTE-PJ-08">Funding &amp; Tenders Portal</a>
    </body></html>
    """
    extracted = extract_call_evidence(synthetic, reference_patterns=registry["authority"]["reference_patterns"])
    assert extracted["page_kind"] == "CALL_FOR_PROPOSALS"
    assert extracted["call_reference"] == "EU4H-2026-SANTE-PJ-08"
    assert extracted["status_candidate"].lower().startswith("closed")
    assert extracted["programme_candidate"] == "EU4Health"
    assert extracted["funding_tenders_link_present"] is True
    assert extracted["funding_tenders_exact_topic_url"].endswith("EU4H-2026-SANTE-PJ-08")

    dry = resolve(
        call_url=registry["live_fixture"]["url"],
        run_id="test-dry",
        observed_at="2026-08-31T10:00:00Z",
        live=False,
    )
    assert dry["adapter_id"] == "EU4HEALTH_HADEA_CALLS_V1"
    assert dry["observation_state"] == "EXACT_CALL_EVIDENCE_UNRECONCILED"
    assert dry["source_family"] == "EU_DIRECT"
    assert dry["programme_family"] == "EU4Health"
    assert dry["funding_tenders_exact_topic_required"] is True
    assert dry["semantic_reconciliation_required"] is True
    assert dry["evidence_usable_for_reconciliation"] is False
    for key in MATERIAL_FLAGS:
        assert dry[key] is False
    assert dry["publication_effect"] == "NONE"
    missing = set(dry["missing_for_open_confirmation"])
    assert "exact_current_funding_tenders_topic_record" in missing
    assert "semantic_reconciliation" in missing

    assert_raises(
        lambda: resolve(call_url="http://hadea.ec.europa.eu/calls-proposals/example", run_id="bad-http"),
        "non-HTTPS HaDEA URL should fail closed",
    )
    assert_raises(
        lambda: resolve(call_url="https://example.com/calls-proposals/example", run_id="bad-host"),
        "non-HaDEA host should fail closed",
    )
    assert_raises(
        lambda: resolve(call_url="https://hadea.ec.europa.eu/calls-tenders/example", run_id="bad-path"),
        "calls-tenders path should fail closed in proposal adapter",
    )

    base = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    mutated = json.loads(json.dumps(base))
    mutated["policy"]["open_call_authorized"] = True
    path = write_registry(mutated)
    assert_raises(lambda: load_registry(path), "authorizing policy mutation should fail closed")

    mutated = json.loads(json.dumps(base))
    mutated["admission"]["semantic_reconciliation_required"] = False
    path = write_registry(mutated)
    assert_raises(lambda: load_registry(path), "semantic reconciliation relaxation should fail closed")

    mutated = json.loads(json.dumps(base))
    mutated["authority"]["allowed_path_prefixes"] = ["/programmes/eu4health/"]
    path = write_registry(mutated)
    assert_raises(lambda: load_registry(path), "generic programme path should not satisfy exact-call fixture boundary")

    print(json.dumps({
        "adapter_id": dry["adapter_id"],
        "registry_sha256": registry_sha,
        "synthetic_reference": extracted["call_reference"],
        "synthetic_status_candidate": extracted["status_candidate"],
        "funding_tenders_exact_topic_detected": bool(extracted["funding_tenders_exact_topic_url"]),
        "open_call_authorized": dry["open_call_authorized"],
        "publication_effect": dry["publication_effect"],
        "result": "PASS",
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
