#!/usr/bin/env python3
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu" / "ingest" / "source_registry.json"
DATA_PLANE = ROOT / "partener-eu" / "ingest" / "data_plane_contract.json"

REQUIRED = {
    "SRC-EU-FUNDING-TENDERS-GATEWAY": {"EU_DIRECT", "BRUSSELS"},
    "SRC-EU-MFF-2028-2034": {"EU_DIRECT", "BRUSSELS", "PROGRAMMING_PIPELINE"},
    "SRC-EEA-GRANTS-ROMANIA-EEA-MOU": {"EEA_NORWAY", "PROGRAMMING_PIPELINE"},
    "SRC-EEA-GRANTS-ROMANIA-NORWAY-MOU": {"EEA_NORWAY", "PROGRAMMING_PIPELINE"},
    "SRC-EEA-CSF-ROMANIA-CALLS": {"EEA_NORWAY", "CALL_REGISTRY"},
    "SRC-INTERREG-ROBG": {"INTERREG", "CBC"},
    "SRC-INTERREG-ROBG-POST2027": {"INTERREG", "CBC", "PROGRAMMING_PIPELINE"},
    "SRC-INTERREG-ROHU": {"INTERREG", "CBC"},
    "SRC-INTERREG-RORS": {"INTERREG", "CBC"},
    "SRC-INTERREG-RORS-2028-2034": {"INTERREG", "CBC", "PROGRAMMING_PIPELINE"},
    "SRC-INTERREG-ROUA": {"INTERREG", "CBC", "NEXT"},
    "SRC-INTERREG-ROMD": {"INTERREG", "CBC", "NEXT"},
    "SRC-INTERREG-DANUBE": {"INTERREG", "TRANSNATIONAL"},
    "SRC-INTERREG-EUROPE": {"INTERREG", "INTERREGIONAL"},
}

OFFICIAL_HOSTS = {
    "SRC-EU-FUNDING-TENDERS-GATEWAY": "ec.europa.eu",
    "SRC-EU-MFF-2028-2034": "commission.europa.eu",
    "SRC-EEA-GRANTS-ROMANIA-EEA-MOU": "eeagrants.org",
    "SRC-EEA-GRANTS-ROMANIA-NORWAY-MOU": "eeagrants.org",
    "SRC-EEA-CSF-ROMANIA-CALLS": "eeagrants.org",
    "SRC-INTERREG-ROBG": "www.interregviarobg.eu",
    "SRC-INTERREG-ROBG-POST2027": "www.interregviarobg.eu",
    "SRC-INTERREG-ROHU": "interreg-rohu.eu",
    "SRC-INTERREG-RORS": "romania-serbia.net",
    "SRC-INTERREG-RORS-2028-2034": "romania-serbia.net",
    "SRC-INTERREG-ROUA": "ro-ua.net",
    "SRC-INTERREG-ROMD": "www.ro-md.net",
    "SRC-INTERREG-DANUBE": "interreg-danube.eu",
    "SRC-INTERREG-EUROPE": "www.interregeurope.eu",
}

PIPELINE_SCOPES = {"PROGRAMMING_FRAMEWORK", "PROGRAMME_FRAMEWORK"}


def fail(msg):
    raise SystemExit(f"FAIL: {msg}")


def main():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    plane = json.loads(DATA_PLANE.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in data.get("sources", [])}
    programme_domains = plane.get("programmeDomains") or {}

    missing = sorted(set(REQUIRED) - set(by_id))
    if missing:
        fail(f"missing external source roots: {missing}")

    for source_id, families in REQUIRED.items():
        row = by_id[source_id]
        actual = set(row.get("source_families") or [])
        if not families.issubset(actual):
            fail(f"{source_id} missing source families {sorted(families - actual)}")
        if row.get("tier") != "T1":
            fail(f"{source_id} must remain T1 official authority")
        if row.get("credentials_required") is not False:
            fail(f"{source_id} must be publicly observable without credentials")
        host = (urlparse(row.get("url") or "").hostname or "").lower()
        if host != OFFICIAL_HOSTS[source_id]:
            fail(f"{source_id} host drift: {host!r} != {OFFICIAL_HOSTS[source_id]!r}")
        for programme in row.get("programmes") or []:
            domains = programme_domains.get(programme) or []
            if not domains or "UNCLASSIFIED_PROGRAMME" in domains:
                fail(f"{source_id} programme lacks data-plane domain mapping: {programme}")

    pipeline = [row for row in by_id.values() if "PROGRAMMING_PIPELINE" in set(row.get("source_families") or [])]
    if not pipeline:
        fail("no programming-pipeline sources registered")
    for row in pipeline:
        if row.get("material_fact_use") is not False:
            fail(f"pipeline source can authorize material facts: {row['id']}")
        if row.get("observation_state") != "PROGRAMMING_PIPELINE":
            fail(f"pipeline source lacks explicit PROGRAMMING_PIPELINE state: {row['id']}")
        if row.get("authority_scope") not in PIPELINE_SCOPES:
            fail(f"pipeline source has unsafe authority scope: {row['id']}")
        mapped = {domain for programme in row.get("programmes") or [] for domain in programme_domains.get(programme, [])}
        if "PROGRAMMING_FUTURE" not in mapped and row["id"] != "SRC-EU-MFF-2028-2034":
            fail(f"pipeline source lacks PROGRAMMING_FUTURE data-plane classification: {row['id']}")

    gateway = by_id["SRC-EU-FUNDING-TENDERS-GATEWAY"]
    if gateway.get("material_fact_use") is not False:
        fail("Funding & Tenders generic gateway must not authorize call facts")
    if gateway.get("adapter_required") != "FUNDING_TENDERS_STRUCTURED":
        fail("Funding & Tenders gateway must require the structured adapter")
    if gateway.get("observation_state") != "GATEWAY_ONLY":
        fail("Funding & Tenders generic gateway must remain GATEWAY_ONLY")

    eea_calls = by_id["SRC-EEA-CSF-ROMANIA-CALLS"]
    if eea_calls.get("material_fact_use") is not False:
        fail("EEA Civil Society call index must remain discovery-only for material facts")
    if eea_calls.get("adapter_required") != "EEA_CSF_ROMANIA_CALLS_V1":
        fail("EEA Civil Society call index must require the dedicated call adapter")
    if eea_calls.get("authority_scope") != "CALL_INDEX_DISCOVERY":
        fail("EEA Civil Society call index must remain CALL_INDEX_DISCOVERY")
    if eea_calls.get("observation_state") != "CURRENT_CALL_REGISTRY":
        fail("EEA Civil Society call index must identify itself as a current call registry")

    policy = data.get("policy") or {}
    if "OPEN_CALL" not in policy.get("programming_pipeline_rule", ""):
        fail("programming pipeline guard must explicitly prohibit OPEN_CALL promotion")
    if "dedicated" not in policy.get("direct_funding_gateway_rule", "").lower():
        fail("direct funding gateway policy must require a dedicated structured adapter")

    print(
        "PASS external source expansion contract: "
        f"{len(REQUIRED)} roots; {len(pipeline)} programming-pipeline roots; "
        "all programmes data-plane classified; F&T gateway and EEA Civil Society call index fail-closed behind dedicated adapters"
    )


if __name__ == "__main__":
    main()
