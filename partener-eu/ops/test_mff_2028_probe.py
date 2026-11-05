#!/usr/bin/env python3
"""Hermetic October MFF evidence and non-authorizing stage regression."""
import hashlib
import importlib.util
import json
import tempfile
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("mff_2028_probe", ROOT / "partener-eu/ingest/mff_2028_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

SOURCE = {
    "id": "SRC-EU-MFF-CAP-PARTIAL-20261026",
    "tier": "T1",
    "class": "official_council_partial_negotiating_position",
    "stage": "COUNCIL_PARTIAL_CAP_POSITION",
    "url": "https://www.consilium.europa.eu/en/press/press-releases/2026/10/26/test/",
    "event_date": "2026-10-26",
    "updated_date": "2026-10-28",
    "source_family": "PROGRAMMING_PIPELINE_MFF_2028_2034",
    "programme": "MFF_2028_2034/CAP",
    "authority_class": "T1_COUNCIL_OFFICIAL",
    "open_call_authorized": False,
    "material_fact_publication_authorized": False,
}
REGISTRY = {
    "stage_policy": ["COMMISSION_PROPOSAL", "COUNCIL_PARTIAL_CAP_POSITION"],
    "sources": [SOURCE],
}
BODY = ("<html><body><h1>Council partial negotiating position</h1><p>" +
        ("This is a proposed partial negotiating stage, not an adopted budget or an open funding call. " * 10) +
        "</p></body></html>").encode("utf-8")


class Response:
    def __init__(self, body=BODY, final_url=SOURCE["url"]):
        self.body = body
        self.final_url = final_url
        self.headers = {"content-type": "text/html; charset=utf-8"}
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.final_url

    def read(self, limit):
        return self.body[:limit]


original_urlopen = probe.urllib.request.urlopen


def expect_bad_registry(payload, label):
    try:
        probe.validate_registry(payload)
    except ValueError:
        return
    raise AssertionError(label)


def run_tests():
    assert probe.official_https(SOURCE["url"])
    assert not probe.official_https("http://www.consilium.europa.eu/insecure")
    assert not probe.official_https("https://www.consilium.europa.eu.evil.example/test")
    assert not probe.official_https("https://evil.example/test")
    expect_bad_registry({**REGISTRY, "sources": [SOURCE, SOURCE]}, "duplicate ID accepted")
    expect_bad_registry({**REGISTRY, "stage_policy": ["OPEN_CALL"]}, "OPEN_CALL stage accepted")
    expect_bad_registry({**REGISTRY, "sources": [{**SOURCE, "open_call_authorized": True}]}, "call authority accepted")
    expect_bad_registry({**REGISTRY, "sources": [{**SOURCE, "stage": "ADOPTED_MFF"}]}, "adoption stage accepted")

    # The committed official-source registry, not just the synthetic fixture,
    # must preserve distinct October events and original update dates.
    actual = json.loads((ROOT / "partener-eu/ingest/mff_2028_source_registry.json").read_text(encoding="utf-8"))
    probe.validate_registry(actual)
    expected = {
        "SRC-EU-MFF-IRISH-NEGOTIATING-BOX-20261010": ("PRESIDENCY_NEGOTIATING_PROPOSAL", "2026-10-10", None),
        "SRC-EU-MFF-CMO-PARTIAL-20261019": ("COUNCIL_PARTIAL_CMO_POSITION", "2026-10-19", "2026-10-20"),
        "SRC-EU-MFF-CAP-PARTIAL-20261026": ("COUNCIL_PARTIAL_CAP_POSITION", "2026-10-26", "2026-10-28"),
    }
    entries = {s["id"]: s for s in actual["sources"]}
    assert len(entries) == len(actual["sources"])
    for sid, (stage, event_date, updated_date) in expected.items():
        source = entries[sid]
        assert source["stage"] == stage
        assert source["event_date"] == event_date
        assert source.get("updated_date") == updated_date
        assert source["open_call_authorized"] is False
        assert source["material_fact_publication_authorized"] is False

    with tempfile.TemporaryDirectory(prefix="mff-contract-") as directory:
        temp = Path(directory)
        reg = temp / "registry.json"
        state = temp / "state.json"
        evidence = temp / "evidence"
        reg.write_text(json.dumps(REGISTRY), encoding="utf-8")

        probe.urllib.request.urlopen = lambda *_args, **_kwargs: Response()
        first = probe.run(reg, state, evidence, "test-first")
        row = first["sources"][0]
        assert first["summary"] == {"total": 1, "pass": 1, "fail": 0, "review_required": 0}
        assert row["observation_state"] == "RAW_FETCHED_STAGE_UNRECONCILED"
        assert row["raw_sha256"] == hashlib.sha256(BODY).hexdigest()
        assert row["fetched_at_utc"] and row["run_id"] == "test-first"
        assert row["stage"] == "COUNCIL_PARTIAL_CAP_POSITION"
        assert row["event_date"] == "2026-10-26" and row["updated_date"] == "2026-10-28"
        assert row["publish_authorized"] is False and row["open_call_authorized"] is False
        assert (evidence / row["raw_evidence_file"]).read_bytes() == BODY
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["policy"] == "ACQUISITION_EVIDENCE_ONLY_NON_AUTHORIZING"
        assert manifest["sources"][0]["raw_sha256"] == row["raw_sha256"]

        changed = BODY.replace(b"partial negotiating position", b"changed negotiating position")
        probe.urllib.request.urlopen = lambda *_args, **_kwargs: Response(changed)
        second = probe.run(reg, state, evidence, "test-second")
        assert second["sources"][0]["semantic_hash_changed"] is True
        assert second["sources"][0]["review_required"] is True
        assert second["sources"][0]["publish_authorized"] is False

        def denied(*_args, **_kwargs):
            raise urllib.error.HTTPError(SOURCE["url"], 403, "Denied", {}, None)
        probe.urllib.request.urlopen = denied
        fail = probe.run(reg, state, evidence, "test-failed")
        row = fail["sources"][0]
        assert row["observation_state"] == "PROVISIONAL_FAIL_CLOSED"
        assert row["raw_sha256"] is None and row["fetched_at_utc"] is None
        assert row["last_known_semantic_sha256"] == second["sources"][0]["semantic_sha256"]
        assert row["publish_authorized"] is False and row["review_required"] is False

        # Refuse cross-domain redirects and partial/truncated body hashing.
        probe.urllib.request.urlopen = lambda *_args, **_kwargs: Response(BODY, "https://evil.example/fake")
        assert probe.run(reg, state, evidence, "test-redirect")["summary"]["fail"] == 1
        probe.urllib.request.urlopen = lambda *_args, **_kwargs: Response(b"x" * (probe.MAX_BYTES + 1))
        assert probe.run(reg, state, evidence, "test-oversized")["summary"]["fail"] == 1
        assert state.exists() and (evidence / "manifest.json").exists()
        print("PASS: official source taxonomy + raw SHA provenance + stage watch + 403/LKG + redirect/oversize fail-closed")


if __name__ == "__main__":
    try:
        run_tests()
    finally:
        probe.urllib.request.urlopen = original_urlopen
