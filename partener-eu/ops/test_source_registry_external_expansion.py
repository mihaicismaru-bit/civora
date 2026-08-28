#!/usr/bin/env python3
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu" / "ingest" / "source_registry.json"
DATA_PLANE = ROOT / "partener-eu" / "ingest" / "data_plane_contract.json"

REQUIRED = {
    "SRC-EU-FUNDING-TENDERS-GATEWAY": {"EU_DIRECT", "BRUSSELS"},
    "SRC-EU-HORIZON-EUROPE": {"EU_DIRECT", "BRUSSELS"},
    "SRC-EU-EIC-WP-2026": {"EU_DIRECT", "BRUSSELS", "PROGRAMMING_PIPELINE"},
    "SRC-EU-LIFE-CALLS-2026": {"EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"},
    "SRC-EU-DIGITAL-WORK-PROGRAMMES": {"EU_DIRECT", "BRUSSELS", "PROGRAMMING_PIPELINE"},
    "SRC-EU-CEF-GATEWAY": {"EU_DIRECT", "BRUSSELS"},
    "SRC-EU-INNOVATION-FUND-CALLS": {"EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"},
    "SRC-EU-EU4HEALTH-GATEWAY": {"EU_DIRECT", "BRUSSELS"},
    "SRC-EU-CERV-GATEWAY": {"EU_DIRECT", "BRUSSELS"},
    "SRC-EU-SMP-CALLS": {"EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"},
    "SRC-EU-ERASMUS-GUIDE-2026": {"EU_DIRECT", "BRUSSELS"},
    "SRC-EU-CREATIVE-EUROPE-CALLS": {"EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"},
    "SRC-EU-EUI-CALLS": {"EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"},
    "SRC-EU-SOLIDARITY-CALL-2026": {"EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"},
    "SRC-EU-JUSTICE-GATEWAY": {"EU_DIRECT", "BRUSSELS"},
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
    "SRC-INTERREG-ROMD-2028-2034": {"INTERREG", "CBC", "NEXT", "PROGRAMMING_PIPELINE"},
    "SRC-INTERREG-DANUBE": {"INTERREG", "TRANSNATIONAL"},
    "SRC-INTERREG-EUROPE": {"INTERREG", "INTERREGIONAL"},
}

OFFICIAL_HOSTS = {
    "SRC-EU-FUNDING-TENDERS-GATEWAY": "ec.europa.eu",
    "SRC-EU-HORIZON-EUROPE": "research-and-innovation.ec.europa.eu",
    "SRC-EU-EIC-WP-2026": "eic.ec.europa.eu",
    "SRC-EU-LIFE-CALLS-2026": "cinea.ec.europa.eu",
    "SRC-EU-DIGITAL-WORK-PROGRAMMES": "digital-strategy.ec.europa.eu",
    "SRC-EU-CEF-GATEWAY": "cinea.ec.europa.eu",
    "SRC-EU-INNOVATION-FUND-CALLS": "climate.ec.europa.eu",
    "SRC-EU-EU4HEALTH-GATEWAY": "health.ec.europa.eu",
    "SRC-EU-CERV-GATEWAY": "commission.europa.eu",
    "SRC-EU-SMP-CALLS": "commission.europa.eu",
    "SRC-EU-ERASMUS-GUIDE-2026": "erasmus-plus.ec.europa.eu",
    "SRC-EU-CREATIVE-EUROPE-CALLS": "culture.ec.europa.eu",
    "SRC-EU-EUI-CALLS": "www.urban-initiative.eu",
    "SRC-EU-SOLIDARITY-CALL-2026": "youth.europa.eu",
    "SRC-EU-JUSTICE-GATEWAY": "commission.europa.eu",
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
    "SRC-INTERREG-ROMD-2028-2034": "ro-md.net",
    "SRC-INTERREG-DANUBE": "interreg-danube.eu",
    "SRC-INTERREG-EUROPE": "www.interregeurope.eu",
}

DIRECT_PROGRAMME_FAMILIES = {
    "SRC-EU-FUNDING-TENDERS-GATEWAY": "EU Direct Funding",
    "SRC-EU-HORIZON-EUROPE": "Horizon Europe",
    "SRC-EU-EIC-WP-2026": "European Innovation Council",
    "SRC-EU-LIFE-CALLS-2026": "LIFE",
    "SRC-EU-DIGITAL-WORK-PROGRAMMES": "Digital Europe",
    "SRC-EU-CEF-GATEWAY": "Connecting Europe Facility",
    "SRC-EU-INNOVATION-FUND-CALLS": "Innovation Fund",
    "SRC-EU-EU4HEALTH-GATEWAY": "EU4Health",
    "SRC-EU-CERV-GATEWAY": "Citizens Equality Rights and Values",
    "SRC-EU-SMP-CALLS": "Single Market Programme",
    "SRC-EU-ERASMUS-GUIDE-2026": "Erasmus+",
    "SRC-EU-CREATIVE-EUROPE-CALLS": "Creative Europe",
    "SRC-EU-EUI-CALLS": "European Urban Initiative",
    "SRC-EU-SOLIDARITY-CALL-2026": "European Solidarity Corps",
    "SRC-EU-JUSTICE-GATEWAY": "Justice Programme",
}

STRUCTURED_FT_REQUIRED = {
    "SRC-EU-FUNDING-TENDERS-GATEWAY",
    "SRC-EU-HORIZON-EUROPE",
    "SRC-EU-LIFE-CALLS-2026",
    "SRC-EU-CEF-GATEWAY",
    "SRC-EU-INNOVATION-FUND-CALLS",
    "SRC-EU-CERV-GATEWAY",
    "SRC-EU-SMP-CALLS",
    "SRC-EU-JUSTICE-GATEWAY",
}

DEDICATED_ADAPTER_REQUIRED = {
    "SRC-EU-EU4HEALTH-GATEWAY": "EU4HEALTH_HADEA_CALLS_V1",
    "SRC-EU-ERASMUS-GUIDE-2026": "ERASMUS_ACTION_ROUTER_V1",
    "SRC-EU-CREATIVE-EUROPE-CALLS": "CREATIVE_EUROPE_CALLS_V1",
    "SRC-EU-EUI-CALLS": "EUI_CALLS_V1",
    "SRC-EU-SOLIDARITY-CALL-2026": "ESC_ACTION_ROUTER_V1",
}

DIRECT_PIPELINE = {
    "SRC-EU-EIC-WP-2026",
    "SRC-EU-DIGITAL-WORK-PROGRAMMES",
}

MFF_REQUIRED_EXTRACT = {
    "commission_proposals",
    "sectoral_proposals",
    "national_regional_partnership_plans",
    "proposed_programme_architecture",
    "member_state_allocation_signals",
    "future_funding_architecture",
    "programming_updates",
}

SAFE_DIRECT_SCOPES = {"GATEWAY_ONLY", "PROGRAMME_GATEWAY", "PROGRAMME_GUIDE", "CALL_INDEX_DISCOVERY"}
SAFE_DIRECT_STATES = {"GATEWAY_ONLY", "CURRENT_CALL_REGISTRY"}
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

    for source_id, expected_family in DIRECT_PROGRAMME_FAMILIES.items():
        row = by_id[source_id]
        if row.get("programme_family") != expected_family:
            fail(f"{source_id} programme family drift: {row.get('programme_family')!r} != {expected_family!r}")
        if row.get("material_fact_use") is not False:
            fail(f"{source_id} generic programme/index/guide source cannot authorize material call facts")
        if source_id not in DIRECT_PIPELINE:
            if row.get("authority_scope") not in SAFE_DIRECT_SCOPES:
                fail(f"{source_id} has unsafe direct-funding authority scope: {row.get('authority_scope')}")
            if row.get("observation_state") not in SAFE_DIRECT_STATES:
                fail(f"{source_id} has unsafe direct-funding observation state: {row.get('observation_state')}")

    for source_id in STRUCTURED_FT_REQUIRED:
        row = by_id[source_id]
        if row.get("adapter_required") != "FUNDING_TENDERS_STRUCTURED":
            fail(f"{source_id} must require the dedicated Funding & Tenders structured adapter")

    for source_id, adapter in DEDICATED_ADAPTER_REQUIRED.items():
        row = by_id[source_id]
        if row.get("adapter_required") != adapter:
            fail(f"{source_id} must require {adapter}")
        if row.get("material_fact_use") is not False:
            fail(f"{source_id} dedicated-adapter source cannot authorize material facts before adapter evidence")

    for source_id in DIRECT_PIPELINE:
        row = by_id[source_id]
        if row.get("observation_state") != "PROGRAMMING_PIPELINE":
            fail(f"{source_id} work-programme source must remain PROGRAMMING_PIPELINE")
        if row.get("authority_scope") != "PROGRAMME_FRAMEWORK":
            fail(f"{source_id} work-programme source must remain PROGRAMME_FRAMEWORK")
        if row.get("material_fact_use") is not False:
            fail(f"{source_id} work-programme source cannot authorize material facts")

    mff = by_id["SRC-EU-MFF-2028-2034"]
    if mff.get("material_fact_use") is not False or mff.get("observation_state") != "PROGRAMMING_PIPELINE":
        fail("MFF 2028-2034 must remain non-authorizing PROGRAMMING_PIPELINE")
    missing_mff_extract = sorted(MFF_REQUIRED_EXTRACT - set(mff.get("extract") or []))
    if missing_mff_extract:
        fail(f"MFF 2028-2034 missing programming-intelligence fields: {missing_mff_extract}")
    mff_note = (mff.get("note") or "").lower()
    if "proposal" not in mff_note or "open_call" not in mff_note:
        fail("MFF 2028-2034 note must explicitly preserve proposal-only/non-OPEN semantics")

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
        if "PROGRAMMING_FUTURE" not in mapped and row["id"] not in ({"SRC-EU-MFF-2028-2034"} | DIRECT_PIPELINE):
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
    direct_rule = policy.get("direct_funding_gateway_rule", "").lower()
    if "dedicated" not in direct_rule or "programme-specific" not in direct_rule or "call index" not in direct_rule:
        fail("direct funding policy must require programme-specific dedicated exact-call/action evidence and keep indexes/guides non-authorizing")

    print(
        "PASS external source expansion contract: "
        f"{len(REQUIRED)} roots; {len(DIRECT_PROGRAMME_FAMILIES)} direct programme families; "
        f"{len(pipeline)} programming-pipeline roots; all programmes data-plane classified; "
        "F&T/programme gateways/call indexes/guides and EEA Civil Society call index fail-closed behind dedicated adapters; "
        "MFF 2028-2034 remains proposal-only programming intelligence"
    )


if __name__ == "__main__":
    main()