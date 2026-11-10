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
    "SRC-EEA-GRANTS-ROMANIA-OVERVIEW": {"EEA_NORWAY", "PROGRAMMING_PIPELINE"},
    "SRC-EEA-GRANTS-ROMANIA-NATIONAL-DOCUMENTS": {"EEA_NORWAY", "NATIONAL_FOCAL_POINT"},
    "SRC-EEA-GRANTS-ROMANIA-EEA-MOU-LEGAL": {"EEA_NORWAY", "LEGAL_FRAMEWORK"},
    "SRC-EEA-GRANTS-ROMANIA-NORWAY-MOU-LEGAL": {"EEA_NORWAY", "LEGAL_FRAMEWORK"},
    "SRC-MIPE-EEA-NORWAY-LANDING": {"EEA_NORWAY", "NATIONAL_FOCAL_POINT"},
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
    "SRC-INTERREG-NEXT-BSB": {"INTERREG", "NEXT", "TRANSNATIONAL", "BLACK_SEA_BASIN", "CALL_REGISTRY"},
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
    "SRC-EU-EUI-CALLS": "portico.urban-initiative.eu",
    "SRC-EU-SOLIDARITY-CALL-2026": "youth.europa.eu",
    "SRC-EU-JUSTICE-GATEWAY": "commission.europa.eu",
    "SRC-EU-MFF-2028-2034": "commission.europa.eu",
    "SRC-EEA-GRANTS-ROMANIA-OVERVIEW": "eeagrants.org",
    "SRC-EEA-GRANTS-ROMANIA-NATIONAL-DOCUMENTS": "www.eeagrants.ro",
    "SRC-EEA-GRANTS-ROMANIA-EEA-MOU-LEGAL": "legislatie.just.ro",
    "SRC-EEA-GRANTS-ROMANIA-NORWAY-MOU-LEGAL": "legislatie.just.ro",
    "SRC-MIPE-EEA-NORWAY-LANDING": "mfe.gov.ro",
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
    "SRC-INTERREG-NEXT-BSB": "www.blacksea-cbc.net",
    "SRC-INTERREG-DANUBE": "interreg-danube.eu",
    "SRC-INTERREG-EUROPE": "www.interregeurope.eu",
}

EEA_NON_CALL_ROOTS = {
    "SRC-EEA-GRANTS-ROMANIA-OVERVIEW",
    "SRC-EEA-GRANTS-ROMANIA-NATIONAL-DOCUMENTS",
    "SRC-EEA-GRANTS-ROMANIA-EEA-MOU-LEGAL",
    "SRC-EEA-GRANTS-ROMANIA-NORWAY-MOU-LEGAL",
    "SRC-MIPE-EEA-NORWAY-LANDING",
}

RCH_2027_SOURCE_ROOTS = {
    "SRC-EU-RCH-2027-CALL1": {
        "host": "www.heritageresearch-hub.eu",
        "tier": "T1B",
        "scope": "EXACT_CALL_DISCOVERY",
        "state": "OFFICIAL_CALL_DETAIL_READBACK_RAW_PENDING",
        "family": {"EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"},
    },
    "SRC-RO-MCUMP-RCH-2027": {
        "host": "www.umpcultura.ro",
        "tier": "T1B",
        "scope": "NATIONAL_CALL_DISCOVERY",
        "state": "OFFICIAL_NATIONAL_CONFIRMATION_READBACK_RAW_PENDING",
        "family": {"ROMANIA", "EU_DIRECT", "CALL_REGISTRY"},
    },
}

RCH_2027_DISCOVERY = ROOT / "partener-eu" / "validation" / "discovery" / "rch-2027-call1-20261108.json"

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


PDDTJ_OI_DISCOVERIES = {
    "SRC-ADRVEST-PDDTJ-PARKS-1794-2026": {
        "url": "https://adrvest.ro/parcuri-industriale-si-tehnologice/",
        "state": "GUIDE_AMENDMENT_DISCOVERED_RAW_PENDING",
        "scope": "GUIDE_AMENDMENT_DISCOVERY_ONLY",
        "adapter": "PDDTJ_T1_PRIMARY_ORDER_AND_MYSMIS_RECONCILE",
        "family": "GUIDE_AMENDMENT",
    },
    "SRC-ADRCENTRU-PDDTJ-DISABILITY-HOUSING-CONSULT-20261106": {
        "url": "https://www.adrcentru.ro/comunicare/consultare-publica-pddtj-ghidul-solicitantului-actiunea-2-locuinte-sociale-din-cadrul-programului-dezvoltare-durabila-si-tranzitie-justa/",
        "state": "PUBLIC_CONSULTATION_DISCOVERED_RAW_PENDING",
        "scope": "CONSULTATION_DISCOVERY_ONLY",
        "adapter": "PDDTJ_T1_PRIMARY_GUIDE_DATE_RECONCILE",
        "family": "CONSULTATION",
    },
}


def main():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    plane = json.loads(DATA_PLANE.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in data.get("sources", [])}

    # The exact delegated-OI documents are monitored as discovery-only sources.
    # Raw originals from MIPE and MySMIS must be reconciled before any material
    # fact or publication; neither a new guide annex nor a draft opens a call.
    for source_id, expected in PDDTJ_OI_DISCOVERIES.items():
        row = by_id.get(source_id)
        if row is None:
            fail(f"missing PDDTJ OI exact-source monitor: {source_id}")
        if (row.get("tier"), row.get("url"), row.get("observation_state"),
                row.get("authority_scope"), row.get("adapter_required")) != (
                "T1B", expected["url"], expected["state"],
                expected["scope"], expected["adapter"]):
            fail(f"{source_id} lost exact OI identity, stage or T1 reconciliation gate")
        if row.get("programmes") != ["PDDTJ"] or not {
            "ROMANIA", "MIPE_OI", expected["family"],
        }.issubset(set(row.get("source_families") or [])):
            fail(f"{source_id} missing programme or source-family identity")
        if (row.get("material_fact_use") is not False
                or row.get("open_call_authorized") is not False
                or row.get("material_fact_publication_authorized") is not False):
            fail(f"{source_id} illegally promotes a draft/guide amendment into material facts")
        if row.get("credentials_required") is not False:
            fail(f"{source_id} must be a public official OI observation")
        if any(key in row for key in (
                "status", "deadline", "budget", "eligibility",
                "open_at", "close_at", "fetched_at", "raw_sha256",
                "parser_version", "run_id", "handoff_sha256")):
            fail(f"{source_id} inserted invented facts or missing raw provenance")
    programme_domains = plane.get("programmeDomains") or {}

    missing = sorted(set(REQUIRED) - set(by_id))
    if missing:
        fail(f"missing external source roots: {missing}")

    # A new official joint-call readback is source discovery until immutable original
    # bytes, exact submission identifier and Romanian national annex are reconciled.
    # Never let announcement / national summary silently become OPEN_CALL.
    for source_id, expected in RCH_2027_SOURCE_ROOTS.items():
        row = by_id.get(source_id)
        if not row:
            fail(f"missing RCH 2027 official source: {source_id}")
        if row.get("tier") != expected["tier"] or row.get("authority_scope") != expected["scope"]:
            fail(f"{source_id} lost its bounded delegated authority")
        if row.get("observation_state") != expected["state"]:
            fail(f"{source_id} unreviewed call lifecycle promotion")
        if (urlparse(row.get("url") or "").hostname or "").lower() != expected["host"]:
            fail(f"{source_id} official host drift")
        if not expected["family"].issubset(set(row.get("source_families") or [])):
            fail(f"{source_id} missing source-family classification")
        if row.get("material_fact_use") is not False or row.get("credentials_required") is not False:
            fail(f"{source_id} unreviewed material facts or inaccessible gateway")
        if row.get("open_call_authorized") is not False or row.get("material_fact_publication_authorized") is not False:
            fail(f"{source_id} wrongly authorized OPEN_CALL or public fact")
        if row.get("adapter_required") != "RCH_2027_EXACT_CALL_NATIONAL_ANNEX_RECONCILE":
            fail(f"{source_id} missing independent exact-call/national-annex adapter gate")
        if any(k in row for k in ("status", "deadline", "budget", "eligibility", "open_at", "close_at")):
            fail(f"{source_id} contains inadmissible material facts in discovery registry")

    rch = json.loads(RCH_2027_DISCOVERY.read_text(encoding="utf-8"))
    if rch.get("observation_state") != "OFFICIAL_MULTI_SOURCE_READBACK_RAW_PENDING":
        fail("RCH 2027 discovery escaped raw-pending gate")
    if rch.get("material_fact_action") != "NONE" or rch.get("publish_authorized") is not False:
        fail("RCH 2027 readback attempted material publication")
    for key in ("fetched_at_utc", "raw_sha256", "parser_version", "run_id", "handoff_sha256"):
        if rch.get(key) is not None:
            fail(f"RCH 2027 web readback falsely claims raw receipt: {key}")
    if set(rch.get("source_ids") or []) != set(RCH_2027_SOURCE_ROOTS):
        fail("RCH 2027 source-id discovery mismatch")
    if rch.get("independent_call_identifier_verified") is not False or rch.get("national_annex_reconciled") is not False:
        fail("RCH 2027 exact call/national annex wrongly reconciled")

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

    for source_id in EEA_NON_CALL_ROOTS:
        row = by_id[source_id]
        if row.get("material_fact_use") is not False:
            fail(f"{source_id} framework/discovery root cannot authorize material call facts")
        if row.get("observation_state") in {"OPEN_CALL", "CURRENT_CALL_REGISTRY"}:
            fail(f"{source_id} non-call root escaped into call state: {row.get('observation_state')}")
        note = (row.get("note") or "").lower()
        if "call" not in note:
            fail(f"{source_id} note must preserve the call-level authority boundary")

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

    bsb = by_id["SRC-INTERREG-NEXT-BSB"]
    if bsb.get("material_fact_use") is not False:
        fail("Black Sea Basin call index must remain non-authorizing discovery evidence")
    if bsb.get("authority_scope") != "CALL_INDEX_DISCOVERY" or bsb.get("observation_state") != "CURRENT_CALL_REGISTRY":
        fail("Black Sea Basin source must remain a current call-index discovery surface")
    if bsb.get("adapter_required") != "INTERREG_CALL_V1":
        fail("Black Sea Basin source must require INTERREG_CALL_V1 before exact-call promotion")
    expected_ro = {"Braila", "Buzau", "Constanta", "Galati", "Tulcea", "Vrancea"}
    if set(bsb.get("eligible_territories_romania") or []) != expected_ro:
        fail("Black Sea Basin Romania eligibility must remain limited to the verified South-East counties")
    bsb_note = (bsb.get("note") or "").lower()
    if "exact call identifier" not in bsb_note or "semantic reconciliation" not in bsb_note:
        fail("Black Sea Basin source must state exact-call and reconcile requirements")

    # ADR Centre exact digital action source contract: a current official
    # action URL may be discovered without laundering its future submission
    # window or stale prior consultation into an OPEN_CALL fact.
    digital_id = "SRC-PR-CENTRU-DIGITAL-2"
    digital_url = (
        "https://www.regiocentru.ro/actiuni/"
        "2-2-intreprinderi-digitale-pentru-o-economie-avansata-apel-2/"
    )
    digital = by_id.get(digital_id)
    legacy_monitor = json.loads(
        (ROOT / "partener-eu" / "ops" / "sources.json").read_text(encoding="utf-8")
    )
    legacy = next((row for row in legacy_monitor.get("sources", [])
                   if row.get("id") == digital_id), None)
    if not digital or not legacy or digital.get("url") != digital_url or legacy.get("url") != digital_url:
        fail("ADR Centre digital 2 exact source and legacy discovery monitor must agree")
    if urlparse(digital_url).hostname != "www.regiocentru.ro":
        fail("ADR Centre digital source lost its exact official programme authority")
    if digital.get("mysmis_identifier_discovery_hint") != "PRC/1059/PRC_P2/OP1/RSO1.2/PRC_A32":
        fail("ADR Centre digital 2 exact-call discovery ID drift")
    if digital.get("authority_scope") != "EXACT_ACTION_DISCOVERY" or digital.get("observation_state") != "EXACT_ACTION_DISCOVERY":
        fail("ADR Centre digital source may not claim OPEN_CALL from an unverified action page")
    if digital.get("adapter_required") != "REGIOCENTRU_EXACT_ACTION_RECONCILE_V1":
        fail("ADR Centre digital exact-action semantic reconcile is mandatory")
    if not {"ROMANIA", "ADR", "CALL_REGISTRY"}.issubset(set(digital.get("source_families") or [])):
        fail("ADR Centre digital source lost official regional provenance")
    if "future_submission_window_candidate" not in set(digital.get("extract") or []):
        fail("ADR Centre digital source must distinguish future window from OPEN")
    if (digital.get("material_fact_use") is not False
            or digital.get("open_call_authorized") is not False
            or digital.get("material_fact_publication_authorized") is not False
            or legacy.get("material_facts_authority") is not False
            or legacy.get("health_scope") != "DISCOVERY_ONLY"):
        fail("ADR Centre digital discovery attempted material authority")
    if any(field in digital for field in (
        "status", "call_status", "open_at", "close_at", "deadline", "budget_eur", "eligibility",
    )):
        fail("ADR Centre digital discovery smuggled unverified material fields")
    if "HTTP 403" not in (legacy.get("note") or "") or "MySMIS" not in (digital.get("note") or ""):
        fail("ADR Centre digital source must retain raw acquisition and review blockers")

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
        "F&T/programme gateways/call indexes/guides, EEA Civil Society and Black Sea Basin indexes fail-closed behind dedicated adapters; "
        "MFF 2028-2034 remains proposal-only programming intelligence"
    )


if __name__ == "__main__":
    main()