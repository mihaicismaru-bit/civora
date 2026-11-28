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
    "SRC-INTERREG-DANUBE-2028-2034": {"INTERREG", "TRANSNATIONAL", "PROGRAMMING_PIPELINE"},
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
    "SRC-INTERREG-DANUBE-2028-2034": "interreg-danube.eu",
    "SRC-INTERREG-EUROPE": "www.interregeurope.eu",
}

EEA_NON_CALL_ROOTS = {
    "SRC-EEA-GRANTS-ROMANIA-OVERVIEW",
    "SRC-EEA-GRANTS-ROMANIA-NATIONAL-DOCUMENTS",
    "SRC-EEA-GRANTS-ROMANIA-EEA-MOU-LEGAL",
    "SRC-EEA-GRANTS-ROMANIA-NORWAY-MOU-LEGAL",
    "SRC-MIPE-EEA-NORWAY-LANDING",
}

DUT_2026_OFFICIAL_PAIR = {
    "SRC-EU-DUT-2026-EXACT-CALL": {
        "url": "https://dutpartnership.eu/calls/dut-call-2026",
        "tier": "T1", "scope": "EXACT_CALL_DISCOVERY_ONLY",
        "state": "EXACT_CALL_DISCOVERED_RAW_PENDING",
        "paired": "SRC-RO-UEFISCDI-DUT-2026",
        "families": {"EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"},
    },
    "SRC-RO-UEFISCDI-DUT-2026": {
        "url": "https://uefiscdi.gov.ro/driving-urban-transitions-partnership-dut",
        "tier": "T1B", "scope": "NATIONAL_CALL_DISCOVERY_ONLY",
        "state": "NATIONAL_CALL_DISCOVERED_RAW_PENDING",
        "paired": "SRC-EU-DUT-2026-EXACT-CALL",
        "families": {"ROMANIA", "EU_DIRECT", "CALL_REGISTRY"},
    },
}

EPPERMED_2027_OFFICIAL_PAIR = {
    "SRC-EU-EPPERMED-2027-EXACT-CALL": {
        "url": "https://www.eppermed.eu/funding-projects/calls/jtc2027/",
        "tier": "T1", "scope": "EXACT_CALL_DISCOVERY_ONLY",
        "state": "EXACT_CALL_DISCOVERED_RAW_PENDING",
        "paired": "SRC-RO-UEFISCDI-EPPERMED-2027",
        "families": {"EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"},
    },
    "SRC-RO-UEFISCDI-EPPERMED-2027": {
        "url": "https://uefiscdi.gov.ro/european-partnership-for-personalised-medicine-ep-permed",
        "tier": "T1B", "scope": "NATIONAL_CALL_DISCOVERY_ONLY",
        "state": "NATIONAL_CALL_DISCOVERED_RAW_PENDING",
        "paired": "SRC-EU-EPPERMED-2027-EXACT-CALL",
        "families": {"ROMANIA", "EU_DIRECT", "RESEARCH", "CALL_REGISTRY"},
    },
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


def validate_impact_lot3_pair(by_id):
    """A Commission Lot 3-only extension must not reopen Romanian national intake."""
    notice_id = "SRC-MAI-AMIF-IMPACT-LOT3-20261110"
    pdf_id = "SRC-EC-AMIF-IMPACT-2026-51-PDF"
    notice_url = (
        "https://fed.mai.gov.ro/11719/clarificari-com-actiunea-specifica-impact-"
        "extindere-termen-limita-pentru-lotul-3-si-informatii-suplimentare-"
        "privind-modalitatea-de-distribuire-pentru-loturile-1-si-2/"
    )
    pdf_url = (
        "https://fed.mai.gov.ro/wp-content/uploads/2026/11/"
        "1.-IMPACT-extension-of-ddl-Lot-3-and-distrib-key-Note-to-the-Committee.pdf"
    )
    for source_id, url, peer, scope, state in (
        (notice_id, notice_url, pdf_id, "EXACT_CALL_AMENDMENT_DISCOVERY_ONLY",
         "LOT3_EXTENSION_DISCOVERED_RAW_PENDING"),
        (pdf_id, pdf_url, notice_id, "PRIMARY_DOCUMENT_DISCOVERY_ONLY",
         "OFFICIAL_PRIMARY_PDF_READBACK_RAW_PENDING"),
    ):
        source = by_id.get(source_id)
        if not source:
            fail(f"missing exact AMIF IMPACT official amendment source: {source_id}")
        expected = {
            "url": url,
            "paired_official_source_id": peer,
            "programmes": ["FAMI"],
            "call_identifier_discovery_hint": "AMIF/2026/SA/IMPACT",
            "commission_note_identifier": "HOME-Funds/2026/51",
            "affected_lot": "3",
            "event_date_discovery": "2026-11-10",
            "authority_scope": scope,
            "observation_state": state,
            "material_fact_use": False,
            "open_call_authorized": False,
            "material_fact_publication_authorized": False,
            "adapter_required": "AMIF_IMPACT_LOT_SPECIFIC_PRIMARY_AND_NATIONAL_RECONCILE",
        }
        for key, value in expected.items():
            if source.get(key) != value:
                fail(f"{source_id}: prohibited or missing {key} for Lot 3-only discovery")
        if any(key in source for key in (
            "status", "call_status", "open_at", "close_at", "deadline",
            "budget_eur", "eligibility", "fetched_at", "raw_sha256",
            "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
        )):
            fail(f"{source_id} invented material facts or immutable acquisition")
        if source.get("url", "").split("/")[2] != "fed.mai.gov.ro":
            fail(f"{source_id} lost exact official MAI host")
        note = source.get("note") or ""
        for required in (
            "Lot 3", "20 November 2026", "11 November", "2 November 2026",
            "Romania", "OPEN_CALL",
        ):
            # Both records must capture the national-vs-Commission scope.
            if required not in note and not (
                source_id == pdf_id and required == "2 November 2026"
            ):
                fail(f"{source_id}: missing lot-specific / national safety note: {required}")




def validate_thcs_2027_preannouncement(by_id, programme_domains):
    """The planned 16-November launch is never evidence of an already OPEN call."""
    ids = {
        "SRC-EU-THCS-2027-PREANNOUNCEMENT": (
            "https://www.thcspartnership.eu/funding/jtc-2027-pre-announcement.kl",
            "T1", "SRC-RO-UEFISCDI-THCS-2027",
            {"EU_DIRECT", "BRUSSELS", "PROGRAMMING_PIPELINE"}),
        "SRC-RO-UEFISCDI-THCS-2027": (
            "https://uefiscdi.gov.ro/transforming-health-and-care-systems-thcs",
            "T1B", "SRC-EU-THCS-2027-PREANNOUNCEMENT",
            {"ROMANIA", "EU_DIRECT", "PROGRAMMING_PIPELINE"}),
    }
    programme = "Horizon Europe / THCS Joint Transnational Call 2027"
    if set(programme_domains.get(programme, [])) != {"EU_DIRECT_FUNDING", "PROGRAMMING_FUTURE"}:
        fail("THCS 2027 planned programme lacks separated future-programming plane")
    for source_id, (url, tier, peer, families) in ids.items():
        row = by_id.get(source_id)
        if not row:
            fail(f"{source_id}: missing official paired preannouncement")
        expected = {
            "url": url, "tier": tier, "paired_official_source_id": peer,
            "programmes": [programme], "programme_family": programme,
            "authority_scope": "PROGRAMMING_FRAMEWORK",
            "observation_state": "PROGRAMMING_PIPELINE",
            "adapter_required": "THCS_2027_OFFICIAL_LAUNCH_NATIONAL_RULES_RECONCILE_V1",
            "material_fact_use": False, "credentials_required": False,
            "open_call_authorized": False, "material_fact_publication_authorized": False,
        }
        for key, value in expected.items():
            if row.get(key) != value:
                fail(f"{source_id}: prelaunch {key} is missing or dangerously promoted")
        if not families.issubset(set(row.get("source_families") or [])):
            fail(f"{source_id}: source taxonomy lost its future-programming gate")
        if any(k in row for k in (
            "status", "call_status", "deadline", "open_at", "close_at", "budget",
            "budget_eur", "eligibility", "fetched_at", "raw_sha256", "parser_version",
            "run_id", "handoff_sha256", "submission_live_authorized",
        )):
            fail(f"{source_id}: unacquired preannouncement invented material facts")
        note = row.get("note") or ""
        for marker in ("16 November 2026", "OPEN_CALL", "national", "reconcil"):
            if marker.lower() not in note.lower():
                fail(f"{source_id}: planned-stage or national-rule warning lost: {marker}")


def validate_water4all_2026_pair(by_id):
    """Water4All stage-1 expiry does not open uninvited stage-2 intake."""
    pair = {
        "SRC-EU-WATER4ALL-2026-JTC": {
            "url": "https://www.water4all-partnership.eu/joint-activities/water4all-2026-joint-transnational-call",
            "peer": "SRC-RO-UEFISCDI-WATER4ALL-2026",
            "state": "STAGE1_DEADLINE_PASSED_READBACK_RAW_PENDING",
            "scope": "EXACT_CALL_STAGE_DISCOVERY_ONLY",
            "authority": "T1_OFFICIAL_JOINT_CALL_OPERATOR",
            "families": {"EU_DIRECT", "BRUSSELS", "JOINT_TRANSNATIONAL_CALL", "CALL_REGISTRY"},
        },
        "SRC-RO-UEFISCDI-WATER4ALL-2026": {
            "url": "https://uefiscdi.gov.ro/water4all",
            "peer": "SRC-EU-WATER4ALL-2026-JTC",
            "state": "NATIONAL_STAGE1_DEADLINE_PASSED_READBACK_RAW_PENDING",
            "scope": "NATIONAL_2026_CALL_STAGE_DISCOVERY_ONLY",
            "authority": "T1B_ROMANIAN_NATIONAL_FUNDING_AGENCY",
            "families": {"ROMANIA", "EU_DIRECT", "RESEARCH", "CALL_REGISTRY"},
        },
    }
    for source_id, expected in pair.items():
        source = by_id.get(source_id)
        if not isinstance(source, dict):
            fail(f"{source_id}: missing official Water4All 2026 paired discovery")
        exact = {
            "url": expected["url"],
            "paired_official_source_id": expected["peer"],
            "observation_state": expected["state"],
            "authority_scope": expected["scope"],
            "authority_class": expected["authority"],
            "programme_family": "Horizon Europe / Water4All Joint Transnational Call 2026",
            "programmes": ["EU direct programmes"],
            "adapter_required": "WATER4ALL_2026_STAGE_SPECIFIC_PRIMARY_AND_ROMANIAN_RULES_RECONCILE_V1",
            "material_fact_use": False,
            "credentials_required": False,
            "open_call_authorized": False,
            "material_fact_publication_authorized": False,
        }
        for key, value in exact.items():
            if source.get(key) != value:
                fail(f"{source_id}: missing/bypassed paired Water4All {key}")
        if not expected["families"].issubset(set(source.get("source_families") or [])):
            fail(f"{source_id}: official Water4All source family was lost")
        if any(key in source for key in (
            "status", "call_status", "deadline", "deadline_at", "open_at", "close_at",
            "eligibility", "budget_eur", "romania_budget_eur", "fetched_at",
            "raw_sha256", "parser_version", "run_id", "handoff_sha256",
            "application_status", "submission_open", "stage2_open",
        )):
            fail(f"{source_id}: invented Water4All material fact or raw provenance")
        note = source.get("note") or ""
        for required in ("10 November 2026", "6 April 2027", "OPEN_CALL",
                         "original", "reconcil"):
            if required.casefold() not in note.casefold():
                fail(f"{source_id}: lost stage-specific safety note: {required}")
        if source_id.startswith("SRC-EU-"):
            if "23 October 2026" not in note or "EPSS" not in note:
                fail("Water4All changed submission endpoint must be reconciled")
        else:
            if source.get("exact_section_discovery_hint") != "Water4all-2026":
                fail("UEFISCDI mixed-year page cannot silently relabel 2025 or 2027")


def test_water4all_adversarial_pairs(by_id):
    """Negative in-memory replay ensures release-field and stage tampering fails."""
    from copy import deepcopy
    for source_id in ("SRC-EU-WATER4ALL-2026-JTC",
                      "SRC-RO-UEFISCDI-WATER4ALL-2026"):
        mutations = (
            ("open_call_authorized", True),
            ("material_fact_publication_authorized", True),
            ("material_fact_use", True),
            ("observation_state", "OPEN_CALL"),
            ("deadline", "2027-04-06T15:00:00"),
            ("fetched_at", "2026-11-11T10:00:00Z"),
            ("paired_official_source_id", source_id),
        )
        for field, invalid_value in mutations:
            tampered = deepcopy(by_id)
            tampered[source_id][field] = invalid_value
            try:
                validate_water4all_2026_pair(tampered)
            except SystemExit:
                pass
            else:
                fail(f"Water4All negative replay admitted {source_id}.{field}")

def main():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    plane = json.loads(DATA_PLANE.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in data.get("sources", [])}

    # Source-family lineage is mandatory for legacy and newly expanded roots.
    # This changes provenance taxonomy only; it must not imply OPEN_CALL,
    # successful official acquisition, or new material publication authority.
    if len(by_id) != len(data.get("sources", [])):
        fail("duplicate source identifiers in verified registry")
    for source in data.get("sources", []):
        families = source.get("source_families")
        if not isinstance(families, list) or not families or any(
            not isinstance(family, str) or not family.strip() for family in families
        ):
            fail("missing/invalid source-family provenance: " + source["id"])


    # 13-Nov PR Centru: consultation and exact-action guide revision remain
    # strictly discovery-only, regardless of upcoming ITI project intake.
    pr_centre_nov13 = {
        "SRC-PRC-151-INCUBATORS-RESIDENTS-CONSULT-20261113": (
            "https://www.regiocentru.ro/actiuni/1-5-1-interventia-1-5-1-incubatoare-si-acceleratoare-de-afaceri-etapa-2/",
            "CONSULTATION_DISCOVERY_ONLY",
            "PUBLIC_CONSULTATION_DISCOVERED_RAW_PENDING",
            None,
        ),
        "SRC-PRC-143-ITI-CORRIGENDUM2-20261113": (
            "https://www.regiocentru.ro/adr-centru-in-calitate-de-autoritate-de-management-pentru-programul-regiunea-centru-pr-centru-a-emis-corrigendum-ul-nr-2-la-ghidul-solicitantului-aferent-inter/",
            "GUIDE_CORRIGENDUM_DISCOVERY_ONLY",
            "GUIDE_CORRIGENDUM_2_DISCOVERED_RAW_PENDING",
            "SRC-PR-CENTRU-ITI-143-TWO-CALLS-2026",
        ),
    }
    for source_id, (url, scope, state, pair) in pr_centre_nov13.items():
        row = by_id.get(source_id)
        if row is None:
            fail(f"missing 13-Nov PR Centru exact official discovery {source_id}")
        if (row.get("url"), row.get("tier"), row.get("authority_scope"),
                row.get("observation_state"), row.get("event_date_discovery"),
                row.get("paired_official_source_id")) != (
                url, "T1", scope, state, "2026-11-13", pair):
            fail(f"{source_id}: consultation/revision identity or pairing drift")
        if row.get("programmes") != ["Programul Regiunea Centru 2021-2027"]:
            fail(f"{source_id}: wrong managing-authority programme")
        if any(row.get(key) is not False for key in (
                "material_fact_use", "open_call_authorized",
                "material_fact_publication_authorized")):
            fail(f"{source_id}: unreviewed material call admission")
        if any(key in row for key in (
                "status", "call_status", "deadline", "budget", "budget_eur",
                "eligibility", "fetched_at", "raw_sha256", "semantic_sha256",
                "parser_version", "run_id", "handoff_sha256")):
            fail(f"{source_id}: fabricated material fact or raw-source receipt")
        note = (row.get("note") or "").lower()
        if "open_call" not in note or not (
                "no open_call" in note or "cannot authorize open_call" in note):
            fail(f"{source_id}: lost explicit non-promotion boundary")
    families_151 = set(by_id["SRC-PRC-151-INCUBATORS-RESIDENTS-CONSULT-20261113"].get("source_families") or [])
    if "CONSULTATION" not in families_151 or "PROGRAMMING_PIPELINE" in families_151:
        fail("1.5.1 draft-guide consultation must be classified separately from future-programme pipeline")

    # Official 13-Nov ITI notice is a dated schedule witness only. The
    # 16-Nov noon boundary has passed, but source discovery does not prove
    # MySMIS is currently accepting either territorially distinct call.
    intake_notice = by_id.get("SRC-PRC-143-ITI-INTAKE-SCHEDULE-WITNESS-20261113")
    if not intake_notice:
        fail("missing official 13-Nov two-ITI intake schedule witness")
    if (intake_notice.get("url") !=
            "https://www.regiocentru.ro/sesiune-de-informare-pentru-lansarea-apelurilor-de-proiecte-pentru-dezvoltarea-imm-urilor-i-din-cele-2-iti-de-pe-raza-regiunii-centru/"
            or intake_notice.get("event_date_discovery") != "2026-11-13"
            or intake_notice.get("paired_official_source_id") !=
            "SRC-PR-CENTRU-ITI-143-TWO-CALLS-2026"):
        fail("two-ITI dated official notice identity/pairing drift")
    if intake_notice.get("mysmis_identifiers_discovery_hint") != {
        "ITI Microregiunea Tara Fagarasului": "PRC/1057/PRC_P1/OP1",
        "ITI Motii, Tara de Piatra": "PRC/1232/PRC_P1/OP1",
    }:
        fail("two different ITI MySMIS call identities were conflated")
    if (intake_notice.get("tier") != "T1"
            or intake_notice.get("authority_scope") !=
            "INTAKE_SCHEDULE_NOTICE_DISCOVERY_ONLY"
            or intake_notice.get("observation_state") !=
            "SCHEDULED_INTAKE_DISCOVERED_RAW_PENDING"
            or intake_notice.get("adapter_required") !=
            "REGIOCENTRU_TWO_TERRITORIAL_CALLS_MYSMIS_RECONCILE_V1"):
        fail("two-ITI schedule witness bypassed original/MySMIS reconciliation")
    if not {"ROMANIA", "ADR", "CALL_REGISTRY", "DISCOVERY"}.issubset(
            set(intake_notice.get("source_families") or [])):
        fail("two-ITI notice lost provenance/programme classification")
    if any(intake_notice.get(field) is not False for field in (
            "material_fact_use", "open_call_authorized",
            "material_fact_publication_authorized")):
        fail("elapsed ITI intake schedule was promoted to material OPEN_CALL")
    if any(field in intake_notice for field in (
            "status", "call_status", "deadline", "open_at", "close_at",
            "budget", "eligibility", "fetched_at", "raw_sha256",
            "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
            "submission_endpoint")):
        fail("two-ITI notice fabricated material fact or raw receipt")
    note = (intake_notice.get("note") or "").upper()
    if not all(term in note for term in (
            "16 NOVEMBER 2026", "12:00", "HTTP 403", "NOT_CAPTURED",
            "NO OPEN_CALL", "MYSMIS", "CORRIGENDUM 2")):
        fail("two-ITI witness lost dated schedule and review-only conditions")

    # EIT HEI 2026: official programme call operator + Romanian NCP information.
    # The NCP is NOT a national funder; web readback is NOT immutable source
    # acquisition. Exact 2026 call, application route and current call-text
    # receipt must reconcile before any canonical OPEN/deadline/budget facts.
    eit_pair = {
        "SRC-EU-EIT-HEI-2026-EXACT-CALL": (
            "https://eit-hei.eu/funding-support/funding-opportunities/open-calls/call-for-proposals-2026/",
            "T1", "EXACT_CALL_DISCOVERY_ONLY", "EXACT_CALL_DISCOVERED_RAW_PENDING",
            "SRC-RO-UEFISCDI-EIT-HEI-2026-NCP", {"EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"},
        ),
        "SRC-RO-UEFISCDI-EIT-HEI-2026-NCP": (
            "https://uefiscdi.gov.ro/news-apelul-2026-eit-higher-education-initiative-pana-la-1-25-milioane-eur-pe-proiect-depunere-pana-la-13-ianuarie-2027.-calenda",
            "T1B", "NATIONAL_INFORMATION_DISCOVERY_ONLY", "NATIONAL_INFO_READBACK_RAW_PENDING",
            "SRC-EU-EIT-HEI-2026-EXACT-CALL", {"ROMANIA", "EU_DIRECT", "CALL_REGISTRY"},
        ),
    }
    for source_id, (url, tier, scope, state, pair, families) in eit_pair.items():
        row = by_id.get(source_id)
        if row is None:
            fail(f"missing exact EIT HEI 2026 paired official discovery: {source_id}")
        if (row.get("url"), row.get("tier"), row.get("authority_scope"),
                row.get("observation_state"), row.get("paired_official_source_id")) != (
                url, tier, scope, state, pair):
            fail(f"{source_id} lost exact 2026 identity or raw-pending pairing")
        if row.get("programmes") != ["EIT Higher Education Initiative Call 2026"] or not families.issubset(
                set(row.get("source_families") or [])):
            fail(f"{source_id} mixed call generations or lost programme family")
        if row.get("adapter_required") != "EIT_HEI_2026_EXACT_CALL_SUBMISSION_RECONCILE_V1":
            fail(f"{source_id} bypassed exact-call/current-submission reconciliation")
        if (row.get("material_fact_use") is not False
                or row.get("credentials_required") is not False
                or row.get("open_call_authorized") is not False
                or row.get("material_fact_publication_authorized") is not False):
            fail(f"{source_id} unreviewed material fact or OPEN_CALL promotion")
        if any(key in row for key in (
            "status", "call_status", "deadline", "budget", "budget_eur",
            "eligibility", "open_at", "close_at", "fetched_at", "fetched_at_utc",
            "raw_sha256", "semantic_sha256", "parser_version", "run_id",
            "handoff_sha256", "application_deadline",
        )):
            fail(f"{source_id} fabricated material facts or successful raw provenance")
        note = (row.get("note") or "").lower()
        if ("no open_call" not in note and "does not authorize open_call" not in note) or "immutable" not in note:
            fail(f"{source_id} lost explicit provenance/open-state safety boundary")
        if source_id == "SRC-RO-UEFISCDI-EIT-HEI-2026-NCP":
            if "not a romanian national co-funding" not in note or "not_funder" not in (
                    row.get("authority_class") or "").lower():
                fail("UEFISCDI NCP information was wrongly elevated to a funding authority")
    if plane.get("programmeDomains", {}).get("EIT Higher Education Initiative Call 2026") != ["EU_DIRECT_FUNDING"]:
        fail("EIT HEI 2026 lost exact-call data-plane domain classification")

    # UEFISCDI and the DUT secretariat describe the same exact 2026 call.
    # Search/index readback cannot substitute for an immutable paired source
    # receipt, the Romanian National Annex and current submission evidence.
    for source_id, expected in DUT_2026_OFFICIAL_PAIR.items():
        row = by_id.get(source_id)
        if row is None:
            fail(f"missing paired official DUT 2026 source: {source_id}")
        if (row.get("url"), row.get("tier"), row.get("authority_scope"),
                row.get("observation_state"), row.get("paired_official_source_id")) != (
                expected["url"], expected["tier"], expected["scope"],
                expected["state"], expected["paired"]):
            fail(f"{source_id} lost official exact-call identity, pair or discovery state")
        if (row.get("adapter_required") !=
                "DUT_2026_EXACT_CALL_NATIONAL_ANNEX_RECONCILE_V1"):
            fail(f"{source_id} bypassed required national-annex reconciliation")
        if (row.get("programmes") != ["Horizon Europe / Driving Urban Transitions Call 2026"]
                or not expected["families"].issubset(set(row.get("source_families") or []))):
            fail(f"{source_id} lost programme or authority-family binding")
        if (row.get("material_fact_use") is not False
                or row.get("credentials_required") is not False
                or row.get("open_call_authorized") is not False
                or row.get("material_fact_publication_authorized") is not False):
            fail(f"{source_id} promoted DUT discovery to an authorizing source")
        if any(key in row for key in ("status", "deadline", "budget", "eligibility",
                                      "open_at", "close_at", "fetched_at", "raw_sha256",
                                      "parser_version", "run_id", "handoff_sha256")):
            fail(f"{source_id} invented material facts or unavailable provenance")


    # EP PerMed CGT4PM2027: official secretariat and Romanian agency must
    # remain a paired discovery until the revised 11-Nov guidelines, national
    # funder rules and the exact submission endpoint have immutable receipts.
    for source_id, expected in EPPERMED_2027_OFFICIAL_PAIR.items():
        row = by_id.get(source_id)
        if row is None:
            fail(f"missing paired official EP PerMed 2027 source: {source_id}")
        if (row.get("url"), row.get("tier"), row.get("authority_scope"),
                row.get("observation_state"), row.get("paired_official_source_id")) != (
                expected["url"], expected["tier"], expected["scope"],
                expected["state"], expected["paired"]):
            fail(f"{source_id} lost exact call, Romanian pair or raw-pending state")
        if row.get("adapter_required") != "EPPERMED_2027_EXACT_CALL_NATIONAL_RULES_RECONCILE_V1":
            fail(f"{source_id} bypassed exact call / updated national-rules reconciliation")
        if (row.get("programmes") != ["Horizon Europe / EP PerMed Joint Transnational Call 2027"]
                or not expected["families"].issubset(set(row.get("source_families") or []))):
            fail(f"{source_id} lost programme or official source-family binding")
        if (row.get("material_fact_use") is not False
                or row.get("credentials_required") is not False
                or row.get("open_call_authorized") is not False
                or row.get("material_fact_publication_authorized") is not False):
            fail(f"{source_id} promoted EP PerMed discovery to authorizing evidence")
        if any(key in row for key in (
            "status", "call_status", "deadline", "budget", "budget_eur",
            "eligibility", "open_at", "close_at", "fetched_at", "fetched_at_utc",
            "raw_sha256", "semantic_sha256", "parser_version", "run_id",
            "handoff_sha256", "application_deadline",
        )):
            fail(f"{source_id} invented material facts or an unreceived raw document")
        note = (row.get("note") or "").lower()
        if source_id == "SRC-EU-EPPERMED-2027-EXACT-CALL":
            if ("11 november 2026" not in note or "guidelines" not in note
                    or "annex iii" not in note or "immutable" not in note):
                fail("EP PerMed revised 11-Nov guidelines signal lost its raw/review gate")
            if "change_log_2026_11_11_discovery" not in (row.get("extract") or []):
                fail("EP PerMed current guidelines change log must remain discovery-only")
        elif "cgt4pm-2027" not in note or "multiple" not in note:
            fail("UEFISCDI EP PerMed mixed-generation page must be exact-section isolated")

    # National UEFISCDI competition index is a discovery router, NOT a call.
    # Mixed OPEN / PLANNED / CLOSED labels must never confer current call
    # authority; each target requires exact official detail + Romanian rules.
    transnational_id = "SRC-RO-UEFISCDI-TRANSNATIONAL-CALL-INDEX"
    transnational = by_id.get(transnational_id)
    if not transnational:
        fail("missing UEFISCDI cross-programme transnational market-intelligence root")
    if (transnational.get("url") != "https://uefiscdi.gov.ro/apeluri-transnationale"
            or transnational.get("tier") != "T1B"
            or transnational.get("class") != "official_national_transnational_call_index"):
        fail("UEFISCDI transnational authority/endpoint drift")
    if (transnational.get("authority_scope") != "NATIONAL_TRANSNATIONAL_CALL_INDEX_DISCOVERY"
            or transnational.get("observation_state") != "CURRENT_CALL_REGISTRY"
            or transnational.get("adapter_required") != "UEFISCDI_EXACT_CALL_NATIONAL_RULES_RECONCILE_V1"):
        fail("UEFISCDI mixed-state index escaped the exact-call reconcile gate")
    if transnational.get("programmes") != ["EU direct programmes"] or not {
        "ROMANIA", "EU_DIRECT", "RESEARCH", "CALL_REGISTRY",
    }.issubset(set(transnational.get("source_families") or [])):
        fail("UEFISCDI transnational index lost national programme discovery identity")
    if not {"open_competitions_discovery", "planned_competitions_discovery",
            "closed_competitions_discovery", "specific_call_detail_links",
            "national_annex_rules_candidates"}.issubset(set(transnational.get("extract") or [])):
        fail("UEFISCDI index lost future/open/closed market-intelligence coverage")
    if (transnational.get("material_fact_use") is not False
            or transnational.get("credentials_required") is not False
            or transnational.get("open_call_authorized") is not False
            or transnational.get("material_fact_publication_authorized") is not False):
        fail("UEFISCDI mixed-state index authorized unverified material facts")
    if any(field in transnational for field in (
            "status", "call_status", "deadline", "budget", "eligibility",
            "open_at", "close_at", "fetched_at", "raw_sha256",
            "parser_version", "run_id", "handoff_sha256")):
        fail("UEFISCDI index fabricated call-level data or raw provenance")
    index_note = (transnational.get("note") or "").lower()
    if not all(term in index_note for term in (
            "deschise", "în pregătire", "închise", "open_call",
            "exact call/topic identifier", "semantic reconciliation")):
        fail("UEFISCDI index lacks explicit mixed-stage and fail-closed warnings")

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
    # This exact MIPE endpoint is referenced by a dated official county-
    # authority notice (06 Nov); the primary HTML/PDF bytes remain UNFETCHED.
    # A discovered link is not a T1 receipt, an effective-date proof, a MySMIS
    # call, or permission to publish funding facts.
    parks = by_id["SRC-ADRVEST-PDDTJ-PARKS-1794-2026"]
    if (parks.get("primary_t1_link_candidate") !=
            "https://mfe.gov.ro/dgpddtj-actualizarea-ghidului-solicitantului-pentru-actiunea-dezvoltarea-intreprinderilor-si-a-antreprenoriatului-componenta-sprijin-pentru-infrastructura-de-afaceri/"
            or parks.get("primary_t1_link_witness") !=
            "https://www.cjgorj.ro/actualizarea-ghidului-solicitantului-pentru-actiunea-dezvoltarea-intreprinderilor-si-a-antreprenoriatului-componenta-sprijin-pentru-infrastructura-de-afaceri-parc/"
            or parks.get("primary_t1_raw_receipt_state") !=
            "PENDING_TRANSPORT_AND_CONTENT_VERIFICATION"):
        fail("PDDTJ parks exact T1 link lost its official discovery or raw-pending state")
    if any(key in parks for key in (
            "primary_t1_fetched_at", "primary_t1_raw_sha256",
            "primary_t1_parser_version", "primary_t1_run_id",
            "primary_t1_publication_effective_date")):
        fail("PDDTJ parks candidate invented successful T1 provenance or effect date")

    # 05 Nov AM corrigendum is a contract-annex update, not an OPEN call.
    # Search-index discovery is not an original-byte receipt for the notice/PDF.
    clusters = by_id.get("SRC-PR-CENTRU-CLUSTERS-122-CORRIGENDUM2-20261105")
    if not clusters:
        fail("missing official PR Centru Clustere 1.2.2 corrigendum 2 monitor")
    if (clusters.get("url") !=
            "https://www.regiocentru.ro/corrigendum-nr-2-aferent-interventiei-1-2-2-clustere-inovative/"
            or clusters.get("official_mirror_url") !=
            "https://www.adrcentru.ro/comunicare/corrigendum-nr-2-aferent-interventiei-1-2-2-clustere-inovative/"
            or clusters.get("exact_action_link_candidate") !=
            "https://www.regiocentru.ro/actiuni/clustere-inovative-1-2-2/"
            or clusters.get("event_date_discovery") != "2026-11-05"):
        fail("Clustere corrigendum 2 lost official notice/action identity or dated discovery")
    if (clusters.get("tier") != "T1"
            or clusters.get("authority_scope") != "GUIDE_CORRIGENDUM_DISCOVERY_ONLY"
            or clusters.get("observation_state") != "CORRIGENDUM_2_DISCOVERED_RAW_PENDING"
            or clusters.get("adapter_required") != "REGIOCENTRU_EXACT_ACTION_RECONCILE_V1"):
        fail("Clustere corrigendum 2 source escaped discovery-only review")
    if (clusters.get("programmes") != ["Programul Regiunea Centru 2021-2027"]
            or not {"ROMANIA", "ADR", "GUIDE_CORRIGENDUM"}.issubset(
                set(clusters.get("source_families") or []))):
        fail("Clustere corrigendum 2 source lost programme/provenance family")
    if (clusters.get("material_fact_use") is not False
            or clusters.get("open_call_authorized") is not False
            or clusters.get("material_fact_publication_authorized") is not False):
        fail("Clustere corrigendum 2 fabricated OPEN or material publication authority")
    if any(key in clusters for key in (
            "status", "call_status", "deadline", "open_at", "close_at",
            "budget", "eligibility", "fetched_at", "raw_sha256",
            "parser_version", "run_id", "handoff_sha256")):
        fail("Clustere corrigendum 2 invented call facts or unacquired raw receipt")


    # 09 Nov regional AM contract-annex corrigenda are official discovery,
    # NOT a current exact-call receipt, an extension, or permission for OPEN.
    nov9_corrigenda = {
        "SRC-PR-CENTRU-URBAN-MOBILITY-41-CORRIGENDUM2-20261109": (
            "4.1", "19",
            "https://www.regiocentru.ro/corrigendum-nr-2-la-ghidul-solicitantului-aferent-actiunii-4-1-dezvoltarea-mobilitatii-urbane-durabile-in-municipiile-regiunii-centru-inclusiv-zone-metropolitane-si-zone-functionale-urbane/",
        ),
        "SRC-PR-CENTRU-REGENERATION-81-CORRIGENDUM2-20261109": (
            "8.1", "17",
            "https://www.regiocentru.ro/corrigendum-nr-2-la-ghidul-solicitantului-aferent-actiunea-8-1-dezvoltare-urbana-integrata-prin-regenerarea-spatiilor-publice-punerea-in-valoare-a-patrimoniului-infrastructurii-culturale-s/",
        ),
    }
    for source_id, (action, annex, official_url) in nov9_corrigenda.items():
        row = by_id.get(source_id)
        if row is None:
            fail(f"missing Nov9 official ADR Centru corrigendum: {source_id}")
        if (row.get("url"), row.get("tier"), row.get("event_date_discovery"),
                row.get("action_identifier_discovery")) != (
                official_url, "T1", "2026-11-09", action):
            fail(f"{source_id} lost exact official dated identity")
        if (row.get("authority_scope") != "GUIDE_CORRIGENDUM_DISCOVERY_ONLY"
                or row.get("observation_state") != "CORRIGENDUM_2_DISCOVERED_RAW_PENDING"
                or row.get("adapter_required") != "REGIOCENTRU_EXACT_ACTION_RECONCILE_V1"):
            fail(f"{source_id} escaped raw-pending discovery gate")
        if (row.get("programmes") != ["Programul Regiunea Centru 2021-2027"]
                or not {"ROMANIA", "ADR", "GUIDE_CORRIGENDUM"}.issubset(
                    set(row.get("source_families") or []))):
            fail(f"{source_id} lost official programme and family provenance")
        if f"annex_{annex}_contract_amendment_notice" not in (row.get("extract") or []):
            fail(f"{source_id} lost precise Annex {annex} contract-change scope")
        if (row.get("material_fact_use") is not False
                or row.get("open_call_authorized") is not False
                or row.get("material_fact_publication_authorized") is not False):
            fail(f"{source_id} fabricated material publication or OPEN_CALL authority")
        if any(key in row for key in (
                "status", "call_status", "deadline", "budget", "eligibility",
                "open_at", "close_at", "fetched_at", "raw_sha256",
                "parser_version", "run_id", "handoff_sha256")):
            fail(f"{source_id} invented source facts or unacquired raw provenance")

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

    # The official Danube 2028+ Task Force report is future programming,
    # never call-opening evidence for the 2021-2027 programme or the future one.
    danube_future = by_id["SRC-INTERREG-DANUBE-2028-2034"]
    if (danube_future.get("url") !=
            "https://interreg-danube.eu/news/second-task-force-meeting-shapes-the-way-towards-interreg-danube-2028"):
        fail("Danube 2028+ Task Force source lost exact official MA/JS page")
    if danube_future.get("programmes") != ["Interreg Danube Region Programme 2028-2034"]:
        fail("Danube 2028+ programming identity mixed with current calls")
    if (danube_future.get("class") != "official_programming_pipeline"
            or danube_future.get("observation_state") != "PROGRAMMING_PIPELINE"
            or danube_future.get("authority_scope") != "PROGRAMMING_FRAMEWORK"
            or danube_future.get("material_fact_use") is not False
            or danube_future.get("open_call_authorized") is not False
            or danube_future.get("material_fact_publication_authorized") is not False):
        fail("Danube 2028+ Task Force discovery incorrectly authorized material facts")
    danube_note = danube_future.get("note") or ""
    if "14 October 2026" not in danube_note or "20 October 2026" not in danube_note:
        fail("Danube 2028+ source lacks official meeting/publication provenance")
    if "future country participation" not in danube_note or "no OPEN_CALL" not in danube_note:
        fail("Danube 2028+ source must preserve uncertain future coverage and no-OPEN rule")
    if any(key in danube_future for key in (
            "status", "call_status", "deadline", "budget", "eligibility",
            "fetched_at", "raw_sha256", "raw_hash", "parser_version", "run_id", "handoff_sha256")):
        fail("Danube 2028+ registry invented call facts or immutable raw provenance")

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

    # Smart-city 2.1.2 Apel 2 is a new exact official action discovery
    # surfaced by the November ADR catalogue, but the submission window is
    # FUTURE and the displayed MySMIS code is not independently reconciled.
    smart = by_id.get("SRC-PR-CENTRU-SMARTCITY-212-APEL2")
    smart_url = (
        "https://www.regiocentru.ro/actiuni/"
        "2-1-2-platforma-regionala-pilot-de-open-inovation-in-domeniul-smart-city-apel-2/"
    )
    if not smart or smart.get("url") != smart_url:
        fail("PR Centru 2.1.2 Apel 2 official exact action URL missing")
    if (smart.get("tier"), smart.get("authority_scope"),
            smart.get("observation_state"), smart.get("event_date_discovery")) != (
                "T1", "EXACT_ACTION_DISCOVERY_ONLY",
                "EXACT_ACTION_DISCOVERED_RAW_PENDING", "2026-10-29"):
        fail("Smart-city Apel 2 promoted or lost its source-discovery lifecycle")
    if (smart.get("action_identifier_discovery"),
            smart.get("mysmis_identifier_discovery_hint"),
            smart.get("mysmis_identifier_verification")) != (
                "2.1.2 / Apel 2", "PRC/1257/PRC_P2/OP1",
                "T1_DISPLAYED_ID_NOT_YET_RECONCILED_WITH_MYSMIS"):
        fail("Smart-city Apel 2 displayed MySMIS code laundered as verified system identity")
    if smart.get("adapter_required") != "REGIOCENTRU_EXACT_ACTION_RECONCILE_V1":
        fail("Smart-city Apel 2 omitted exact call/MySMIS semantic reconciliation")
    if not {"ROMANIA", "ADR", "CALL_REGISTRY"}.issubset(
            set(smart.get("source_families") or [])):
        fail("Smart-city Apel 2 official regional source family missing")
    if "future_submission_window_candidate" not in set(smart.get("extract") or []):
        fail("Smart-city Apel 2 missing future-window discriminator")
    if any(smart.get(field) is not False for field in (
            "material_fact_use", "open_call_authorized",
            "material_fact_publication_authorized")):
        fail("Smart-city Apel 2 unauthorized OPEN_CALL/material fact promotion")
    if any(field in smart for field in (
            "status", "call_status", "open_at", "close_at", "deadline",
            "budget", "budget_eur", "eligibility", "fetched_at", "raw_sha256",
            "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
            "http_status")):
        fail("Smart-city Apel 2 invented current facts or immutable raw receipt")
    if "NO OPEN_CALL" not in (smart.get("note") or "").upper():
        fail("Smart-city Apel 2 lost explicit non-OPEN gate")

    # Action 1.4.3 comprises TWO territorial ITI calls, not one generic
    # programme status. The official page labels the action active but the
    # published project-intake window is FUTURE as of 12 November 2026.
    # Indexed discovery (exact official route currently HTTP 403) is not a
    # canonical immutable raw receipt or independent MySMIS confirmation.
    iti = by_id.get("SRC-PR-CENTRU-ITI-143-TWO-CALLS-2026")
    if not iti or iti.get("url") != (
            "https://www.regiocentru.ro/actiuni/"
            "1-4-3-cresterea-competitivitatii-imm-din-cadrul-iti/"):
        fail("PR Centru ITI 1.4.3 exact official action URL missing")
    if (iti.get("tier"), iti.get("authority_scope"),
            iti.get("observation_state"), iti.get("event_date_discovery")) != (
                "T1", "EXACT_ACTION_DISCOVERY_ONLY",
                "EXACT_ACTION_DISCOVERED_RAW_PENDING", "2026-09-25"):
        fail("ITI 1.4.3 escaped pre-intake source-discovery quarantine")
    if iti.get("mysmis_identifiers_discovery_hint") != {
            "ITI Microregiunea Tara Fagarasului": "PRC/1057/PRC_P1/OP1",
            "ITI Motii, Tara de Piatra": "PRC/1232/PRC_P1/OP1",
    }:
        fail("ITI 1.4.3 lost separate territorial MySMIS call IDs")
    if iti.get("mysmis_identifier_verification") != (
            "T1_DISPLAYED_IDS_NOT_YET_RECONCILED_WITH_MYSMIS"):
        fail("ITI 1.4.3 laundered two indexed IDs as independently verified")
    if iti.get("adapter_required") != (
            "REGIOCENTRU_TWO_TERRITORIAL_CALLS_MYSMIS_RECONCILE_V1"):
        fail("ITI 1.4.3 must reconcile both calls and their application routes")
    if not {"ROMANIA", "ADR", "CALL_REGISTRY"}.issubset(
            set(iti.get("source_families") or [])):
        fail("ITI 1.4.3 lost official Romanian regional family")
    if "future_submission_window_candidate" not in (iti.get("extract") or []):
        fail("ITI 1.4.3 lost future-intake discriminator")
    if any(iti.get(field) is not False for field in (
            "material_fact_use", "open_call_authorized",
            "material_fact_publication_authorized")):
        fail("ITI 1.4.3 promoted planned intake to OPEN_CALL/material authority")
    if any(field in iti for field in (
            "status", "call_status", "open_at", "close_at", "deadline",
            "budget", "budget_eur", "eligibility", "fetched_at", "raw_sha256",
            "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
            "http_status")):
        fail("ITI 1.4.3 invented material call facts or immutable raw receipt")
    if not all(term in (iti.get("note") or "").upper() for term in (
            "16 NOVEMBER 2026", "HTTP 403", "NO OPEN_CALL", "MYSMIS")):
        fail("ITI 1.4.3 lost dated pre-intake and fail-closed proof gaps")
    if iti.get("official_launch_notice_url") != (
            "https://www.regiocentru.ro/lansare-apeluri-de-finantare-pentru-cresterea-competitivitatii-imm-din-cadrul-iti-microregiunea-tara-fagarasului-si-iti-motii-tara-de-piatra/"):
        fail("ITI 1.4.3 lost original official launch crosscheck")
    if iti.get("official_recent_information_notice_url") != (
            "https://www.regiocentru.ro/sesiune-online-de-informare-privind-apelurile-de-proiecte-aferente-interventiei-1-4-3-cresterea-competitivitatii-imm-din-cadrul-iti/"):
        fail("ITI 1.4.3 lost official November information event crosscheck")

    # 9 Nov ADR Centru 8.1 exact-action page is paired with the already
    # staged Annex 17 corrigendum, not promoted from an indexed window to OPEN.
    regen_id = "SRC-PR-CENTRU-REGENERATION-81-EXACT-ACTION-20261109"
    regen = by_id.get(regen_id)
    if regen is None:
        fail("missing ADR Centru 8.1 exact MySMIS action discovery")
    regen_expected = {
        "tier": "T1",
        "url": "https://www.regiocentru.ro/actiuni/8-1dezvoltare-urbana-integrata-prin-regenerarea-spatiilor-publice-punerea-in-valoare-a-patrimoniului-infrastructurii-culturale-si-a-potentialului-turistic-din-municipiile-regiunii-centru-a/",
        "authority_class": "T1_REGIONAL_MANAGING_AUTHORITY",
        "authority_scope": "EXACT_ACTION_DISCOVERY_ONLY",
        "observation_state": "EXACT_ACTION_DISCOVERED_RAW_PENDING",
        "event_date_discovery": "2026-11-09",
        "mysmis_identifier_discovery_hint": "PRC/1204/PRC_P8/OP5/RSO5.1/PRC_A44",
        "paired_official_source_id": "SRC-PR-CENTRU-REGENERATION-81-CORRIGENDUM2-20261109",
        "adapter_required": "REGIOCENTRU_EXACT_ACTION_RECONCILE_V1",
        "open_call_authorized": False,
        "material_fact_publication_authorized": False,
        "material_fact_use": False,
    }
    if any(regen.get(key) != expected for key, expected in regen_expected.items()):
        fail("ADR Centru 8.1 exact-action source identity/negative promotion gate changed")
    if not {"ROMANIA", "ADR", "CALL_REGISTRY", "DISCOVERY"}.issubset(
            set(regen.get("source_families") or [])):
        fail("ADR Centru 8.1 source taxonomy incomplete")
    forbidden = {
        "status", "call_status", "deadline", "budget", "eligibility",
        "fetched_at", "raw_sha256", "parser_version", "run_id",
        "submission_endpoint", "last_verified_open",
    }
    if forbidden.intersection(regen):
        fail("ADR Centru 8.1 discovery fabricated material facts or raw provenance")
    if by_id[regen["paired_official_source_id"]].get("action_identifier_discovery") != "8.1":
        fail("ADR Centru 8.1 pairing points to a different action")
    if not all(word in (regen.get("note") or "") for word in
               ("HTTP 403", "Annex 17", "MySMIS", "NO OPEN_CALL", "SHA-256")):
        fail("ADR Centru 8.1 current-status/raw-acquisition hold lost")

    # PR Centru 3.3 municipal exact action + Annex 17 corrigendum: official
    # indexed readback is discovery, not immutable acquisition or OPEN_CALL.
    green_blue_pair = {
        "SRC-PR-CENTRU-GREEN-BLUE-33-MUNICIPAL-CALL": (
            "https://www.regiocentru.ro/actiuni/3-3-investitii-in-infrastructura-verde-si-albastra-in-mediul-urban-regional-apel-competitiv-pentru-municipii/",
            "EXACT_ACTION_DISCOVERY", "EXACT_ACTION_DISCOVERED_RAW_PENDING",
            "SRC-PR-CENTRU-GREEN-BLUE-33-MUNICIPAL-CORRIGENDUM2-20261030",
        ),
        "SRC-PR-CENTRU-GREEN-BLUE-33-MUNICIPAL-CORRIGENDUM2-20261030": (
            "https://www.regiocentru.ro/corrigendum-nr-2-aferent-actiunii-3-3-investitii-in-infrastructura-verde-si-albastra-in-mediul-urban-regional-apel-competitiv-pentru-municipii/",
            "GUIDE_CORRIGENDUM_DISCOVERY_ONLY", "CORRIGENDUM_2_DISCOVERED_RAW_PENDING",
            "SRC-PR-CENTRU-GREEN-BLUE-33-MUNICIPAL-CALL",
        ),
    }
    for source_id, (url, scope, state, paired) in green_blue_pair.items():
        row = by_id.get(source_id)
        if row is None or (row.get("url"), row.get("authority_scope"),
                          row.get("observation_state"), row.get("paired_official_source_id")) != (
                              url, scope, state, paired):
            fail(f"{source_id} lost official exact-action/corrigendum discovery identity")
        if row.get("mysmis_identifier_discovery_hint") != "PRC/1189/PRC_P3/OP2/RSO2.7/PRC_A28":
            fail(f"{source_id} lost exact MySMIS identity hint")
        if row.get("event_date_discovery") != "2026-10-30":
            fail(f"{source_id} lost official publication-date discovery")
        if row.get("adapter_required") != "REGIOCENTRU_EXACT_ACTION_RECONCILE_V1":
            fail(f"{source_id} bypassed immutable exact-action reconciliation")
        if not {"ROMANIA", "ADR"}.issubset(set(row.get("source_families") or [])):
            fail(f"{source_id} lost Romanian regional authority provenance")
        if (row.get("material_fact_use") is not False
                or row.get("open_call_authorized") is not False
                or row.get("material_fact_publication_authorized") is not False):
            fail(f"{source_id} promoted unacquired discovery to material authority")
        if any(field in row for field in (
                "status", "call_status", "open_at", "close_at", "deadline",
                "budget_eur", "eligibility", "fetched_at", "raw_sha256",
                "semantic_sha256", "parser_version", "run_id", "handoff_sha256")):
            fail(f"{source_id} fabricated material facts or immutable raw receipt")
        if "HTTP 403" not in (row.get("note") or "") or "OPEN_CALL" not in (row.get("note") or ""):
            fail(f"{source_id} lost fail-closed transport and OPEN boundary")
    green_blue_monitor = next((row for row in legacy_monitor.get("sources", [])
                              if row.get("id") == "SRC-PR-CENTRU-GREEN-BLUE-33-MUNICIPAL-CALL"), None)
    if not green_blue_monitor or (
        green_blue_monitor.get("url"),
        green_blue_monitor.get("health_scope"),
        green_blue_monitor.get("material_facts_authority"),
    ) != ("https://www.regiocentru.ro/actiuni/3-3-investitii-in-infrastructura-verde-si-albastra-in-mediul-urban-regional-apel-competitiv-pentru-municipii/", "DISCOVERY_ONLY", False):
        fail("PR Centru 3.3 exact-action health probe must remain discovery-only")
    if by_id["SRC-PR-CENTRU-GREEN-BLUE-33-MUNICIPAL-CORRIGENDUM2-20261030"].get(
            "exact_action_link_candidate") != "https://www.regiocentru.ro/actiuni/3-3-investitii-in-infrastructura-verde-si-albastra-in-mediul-urban-regional-apel-competitiv-pentru-municipii/":
        fail("PR Centru 3.3 corrigendum lost its exact action link")


    # Keep monthly official *catalogue* issues distinct from exact T1 call authority.
    # The November edition must not rewrite the historical July record or
    # invent an immutable receipt from a search-index discovery / 403 response.
    july = by_id.get("SRC-ADRCENTRU-FUNDING-CATALOG")
    november = by_id.get("SRC-ADRCENTRU-FUNDING-CATALOG-202611")
    if not july or july.get("url") != (
            "https://www.adrcentru.ro/csf/catalogul-surselor-de-finantare-iulie-2026/"):
        fail("ADR Centru July 2026 historical catalogue must be retained")
    if not november or november.get("url") != (
            "https://www.adrcentru.ro/csf/catalogul-surselor-de-finantare-noiembrie-2026/"):
        fail("ADR Centru November 2026 issue lost exact official URL")
    expected_november = {
        "tier": "T2",
        "authority_class": "T2_OFFICIAL_REGIONAL_CATALOG",
        "authority_scope": "CATALOG_DISCOVERY_ONLY",
        "observation_state": "OFFICIAL_CATALOG_DISCOVERED_RAW_PENDING",
        "publication_date_discovery": "2026-11-11",
        "material_fact_use": False,
        "open_call_authorized": False,
        "material_fact_publication_authorized": False,
        "credentials_required": False,
        "adapter_required": "ADR_CENTRU_CATALOG_T1_EXACT_ACTION_AND_MYSMIS_RECONCILE",
    }
    for key, value in expected_november.items():
        if november.get(key) != value:
            fail(f"ADR November discovery elevated or lost {key}")
    if not {"ROMANIA", "ADR", "DISCOVERY"}.issubset(
            set(november.get("source_families") or [])):
        fail("ADR November official aggregator missing Romanian regional provenance")
    if urlparse(november["url"]).hostname != "www.adrcentru.ro":
        fail("ADR November catalogue lost the exact official host")
    if any(key in november for key in (
            "status", "call_status", "deadline", "budget", "budget_eur",
            "eligibility", "fetched_at", "raw_sha256", "semantic_sha256",
            "parser_version", "run_id", "handoff_sha256", "http_status")):
        fail("ADR November catalogue invented call facts or raw provenance")
    if "NO OPEN_CALL" not in (november.get("note") or "").upper():
        fail("ADR November catalogue must preserve the non-OPEN call boundary")
    if "RAW" not in (november.get("note") or "").upper():
        fail("ADR November catalogue failed to disclose raw acquisition pending")

    # Audience-specific monthly catalogues are independent discovery surfaces,
    # NOT independent proofs that the listed calls are open.  Exact T1/MIPE
    # call identifiers and current action pages remain mandatory for OPEN.
    audience_catalogues = {
        "BUSINESS": ("Societăți comerciale", "2026-11-10",
            "https://www.adrcentru.ro/csf/catalogul-surselor-de-finantare-societati-comerciale-noiembrie-2026/"),
        "UNIVERSITIES": ("Universități", "2026-11-10",
            "https://www.adrcentru.ro/csf/catalogul-surselor-de-finantare-universitati-noiembrie-2026/"),
        "PUBLIC": ("Autorități publice", "2026-11-10",
            "https://www.adrcentru.ro/csf/catalogul-surselor-de-finantare-autoritati-publice-noiembrie-2026/"),
        "NGO": ("ONG", "2026-11-11",
            "https://www.adrcentru.ro/csf/csf-ong-noiembrie-2026/"),
    }
    non_authorizing = (
        "status", "call_status", "deadline", "budget", "budget_eur",
        "eligibility", "fetched_at", "raw_sha256", "semantic_sha256",
        "parser_version", "run_id", "handoff_sha256", "http_status",
    )
    for sector, (audience, published, exact_url) in audience_catalogues.items():
        source_id = f"SRC-ADRCENTRU-FUNDING-CATALOG-202611-{sector}"
        page = by_id.get(source_id)
        if not page or page.get("url") != exact_url:
            fail(f"ADR November {sector} catalogue lost exact official URL")
        for key, value in expected_november.items():
            if key == "publication_date_discovery":
                value = published
            if page.get(key) != value:
                fail(f"ADR November {sector} catalogue elevated or lost {key}")
        if page.get("catalog_audience") != audience:
            fail(f"ADR November {sector} catalogue lost audience identity")
        if not {"ROMANIA", "ADR", "DISCOVERY"}.issubset(
                set(page.get("source_families") or [])):
            fail(f"ADR November {sector} catalogue missing discovery provenance")
        if urlparse(page["url"]).hostname != "www.adrcentru.ro":
            fail(f"ADR November {sector} catalogue lost exact official host")
        if any(key in page for key in non_authorizing):
            fail(f"ADR November {sector} catalogue invented raw or call facts")
        if not all(s in (page.get("note") or "").upper() for s in ("NO OPEN_CALL", "RAW", "T1")):
            fail(f"ADR November {sector} catalogue lost explicit fail-closed boundary")
    if len({url for _, _, url in audience_catalogues.values()}) != 4:
        fail("ADR November audience catalogues must have distinct exact URLs")

    # EUI autumn 2026 and the continuously available reviewer pool are
    # distinct NON-GRANT capacity-building opportunities. Neither can be
    # counted as a project-financing OPEN_CALL, nor can the permanent pool
    # extend the autumn city-under-review window.
    eui_roles = {
        "SRC-EU-EUI-PEER-REVIEWS-AUTUMN-2026": (
            "https://www.urban-initiative.eu/capacity-building/peer-reviews/call-autumn2026",
            "EXACT_CAPACITY_BUILDING_WINDOW_READBACK_RAW_PENDING",
            "SRC-EU-EUI-PEER-REVIEWERS-PERMANENT-2026",
            "https://connect.urban-initiative.eu/login",
        ),
        "SRC-EU-EUI-PEER-REVIEWERS-PERMANENT-2026": (
            "https://www.urban-initiative.eu/capacity-building/peer-reviews/ongoing-call-peer-reviews",
            "PERMANENT_PEER_REVIEWER_READBACK_RAW_PENDING",
            "SRC-EU-EUI-PEER-REVIEWS-AUTUMN-2026",
            "https://connect.urban-initiative.eu/capacity-building/peer-review-projectlist",
        ),
    }
    for source_id, (url, state, pair, app_hint) in eui_roles.items():
        row = by_id.get(source_id)
        if not row:
            fail(f"EUI capacity-building discovery missing: {source_id}")
        if (row.get("url"), row.get("observation_state"),
                row.get("paired_official_source_id"),
                row.get("application_endpoint_discovery_hint")) != (
                url, state, pair, app_hint):
            fail(f"{source_id}: EUI autumn/permanent role or exact endpoint drift")
        expected = {
            "tier": "T1",
            "class": "official_eui_capacity_building_application",
            "authority_class": "T1_OFFICIAL_EUI_SECRETARIAT",
            "authority_scope": "NON_GRANT_CAPACITY_BUILDING_APPLICATION_DISCOVERY_ONLY",
            "material_fact_use": False,
            "credentials_required": False,
            "open_call_authorized": False,
            "material_fact_publication_authorized": False,
            "adapter_required": "EUI_PEER_REVIEWS_AUTUMN_PERMANENT_DISTINCT_STAGE_RECONCILE_V1",
        }
        if any(row.get(k) != v for k, v in expected.items()):
            fail(f"{source_id}: EUI discovery promoted or bypassed reconciliation")
        if row.get("programmes") != ["EU direct programmes"] or not {
                "EU_DIRECT", "BRUSSELS", "CAPACITY_BUILDING", "NON_GRANT",
                "DISCOVERY"}.issubset(set(row.get("source_families") or [])):
            fail(f"{source_id}: EUI non-grant category/route was lost")
        if any(k in row for k in (
                "status", "call_status", "deadline", "budget", "budget_eur",
                "eligibility", "open_at", "close_at", "fetched_at",
                "raw_sha256", "semantic_sha256", "parser_version",
                "run_id", "handoff_sha256", "http_status")):
            fail(f"{source_id}: fabricated canonical fact or raw receipt")
        note = (row.get("note") or "").lower()
        if not all(s in note for s in ("not an investment grant", "immutable", "no open_call")):
            fail(f"{source_id}: missing grant/receipt/open boundary")
    if ("deadline_20261112_1200_CET_readback" not in
            by_id["SRC-EU-EUI-PEER-REVIEWS-AUTUMN-2026"].get("extract", [])):
        fail("EUI autumn 2026 call lost the specific 12-Nov CET distinction")
    if "continuous_peer_reviewer_pool_discovery" not in (
            by_id["SRC-EU-EUI-PEER-REVIEWERS-PERMANENT-2026"].get("extract", [])):
        fail("EUI permanent individual role was conflated with autumn city intake")


    # Horizon Cluster 4 topics listed FORTHCOMING on 14 November must not
    # become OPEN_CALL when a crawler sees an indicative 17-Nov opening date.
    # F&T Angular topic shells are navigational, not a verified raw receipt.
    horizon_topics = {
        "SRC-EU-HORIZON-CL4-2027-AI-ROBOTICS-FORTHCOMING":
            "HORIZON-CL4-2027-04-DIGITAL-EMERGING-05",
        "SRC-EU-HORIZON-CL4-2027-PHOTONICS-FORTHCOMING":
            "HORIZON-CL4-2027-05-DIGITAL-EMERGING-03",
    }
    for source_id, topic in horizon_topics.items():
        row = by_id.get(source_id)
        if not row:
            fail(f"Horizon forthcoming exact-topic discovery missing: {source_id}")
        expected_url = ("https://ec.europa.eu/info/funding-tenders/opportunities/"
                        "portal/screen/opportunities/topic-details/" + topic)
        expected = {
            "tier": "T1", "class": "official_eu_funding_tenders_exact_topic",
            "url": expected_url, "topic_identifier_discovery": topic,
            "authority_class": "T1_OFFICIAL_EC_FUNDING_TENDERS",
            "authority_scope": "EXACT_TOPIC_FORTHCOMING_DISCOVERY_ONLY",
            "observation_state": "FORTHCOMING_EXACT_TOPIC_DISCOVERED_RAW_PENDING",
            "material_fact_use": False, "credentials_required": False,
            "open_call_authorized": False,
            "material_fact_publication_authorized": False,
            "adapter_required": "EC_FT_EXACT_TOPIC_CURRENT_STATUS_AND_ENDPOINT_RECONCILE_V1",
        }
        if any(row.get(k) != v for k, v in expected.items()):
            fail(f"{source_id}: forthcoming topic identity/stage or authority was changed")
        if not {"EU_DIRECT", "BRUSSELS", "CALL_REGISTRY", "FORTHCOMING", "DISCOVERY"}.issubset(
                set(row.get("source_families") or [])):
            fail(f"{source_id}: topic missing programme/source taxonomy")
        if any(k in row for k in (
                "status", "call_status", "deadline", "budget", "budget_eur",
                "eligibility", "open_at", "close_at", "fetched_at",
                "raw_sha256", "semantic_sha256", "parser_version", "run_id",
                "handoff_sha256", "http_status", "submission_endpoint")):
            fail(f"{source_id}: fabricated original receipt or material call fact")
        note = (row.get("note") or "").lower()
        if not all(s in note for s in ("js-only", "sha-256", "no open_call", "semantic")):
            fail(f"{source_id}: missing exact-status/receipt/publication boundary")

    # The AFIR 11-Nov DR-12 exhaustion notice is component-specific:
    # ALTE SECTOARE has no bearing on the independent ZOOTEHNIC intake.
    dr12_pair = {
        "SRC-RO-AFIR-DR12-OTHER-EXHAUSTED-20261111": (
            "https://www.afir.ro/comunicate/fondurile-pentru-componenta-alte-sectoare-dr-12-au-fost-epuizate/",
            "EXACT_COMPONENT_LIFECYCLE_DISCOVERY_ONLY",
            "EXHAUSTION_NOTICE_DISCOVERED_RAW_PENDING",
            "SRC-RO-AFIR-DR12-COMPONENT-COUNTER"),
        "SRC-RO-AFIR-DR12-COMPONENT-COUNTER": (
            "https://www.afir.ro/finantare/contor-fonduri-disponibile/",
            "EXACT_COMPONENT_COUNTER_DISCOVERY_ONLY",
            "CURRENT_COUNTER_DISCOVERED_RAW_PENDING",
            "SRC-RO-AFIR-DR12-OTHER-EXHAUSTED-20261111"),
    }
    for source_id, (url, scope, stage, peer) in dr12_pair.items():
        row = by_id.get(source_id)
        if not row:
            fail(f"missing AFIR DR-12 component-specific official source: {source_id}")
        required = {
            "url": url, "tier": "T1", "authority_class": "T1_OFFICIAL_AGENCY",
            "authority_scope": scope, "observation_state": stage,
            "paired_official_source_id": peer,
            "component_identity_discovery": "DR-12 / ALTE SECTOARE",
            "adapter_required": "AFIR_DR12_COMPONENT_NOTICE_COUNTER_RAW_RECONCILE_V1",
            "material_fact_use": False, "open_call_authorized": False,
            "material_fact_publication_authorized": False,
        }
        if any(row.get(k) != v for k, v in required.items()):
            fail(f"{source_id}: DR-12 exact component/authority/negative gate changed")
        if not {"ROMANIA", "AFIR", "CALL_REGISTRY", "DISCOVERY"}.issubset(
                set(row.get("source_families") or [])):
            fail(f"{source_id}: AFIR source family missing")
        if any(k in row for k in (
                "status", "call_status", "deadline", "budget", "budget_eur",
                "eligibility", "open_at", "close_at", "fetched_at", "raw_sha256",
                "semantic_sha256", "parser_version", "run_id", "handoff_sha256")):
            fail(f"{source_id}: DR-12 discovery fabricated receipt/material state")
        note = (row.get("note") or "").upper()
        if not all(x in note for x in ("ZOOTEHNIC", "RAW", "RECONCIL", "NO OPEN_CALL")):
            fail(f"{source_id}: cannot separate DR-12 components or raw boundary")

    # AFIR's public application-system list is a distinct volatile witness,
    # not the immutable receipt or per-component application endpoint.
    dr12_live_id = "SRC-RO-AFIR-DR12-INTAKE-SESSION-LIST-20261121"
    dr12_live = by_id.get(dr12_live_id)
    if not dr12_live:
        fail("missing AFIR DR-12 official live-session discovery witness")

    def _check_dr12_live(row):
        expected = {
            "id": dr12_live_id,
            "tier": "T1",
            "url": "https://depunerepspac.afir.ro/Sesiune/Lista",
            "programme_family": "PS_PAC_2023_2027/DR12",
            "authority_class": "T1_OFFICIAL_AFIR_APPLICATION_SYSTEM",
            "authority_scope": "COMPONENT_SESSION_INDEX_DISCOVERY_ONLY_NOT_EXACT_LIVE_ACCEPTANCE",
            "observation_state": "ZOOTEHNIC_AND_OTHER_SECTORS_SEPARATELY_LISTED_RAW_PENDING",
            "readback_date_discovery": "2026-11-21",
            "source_snapshot_is_volatile": True,
            "component_identities_discovery": [
                "DR-12 / SECTOR ZOOTEHNIC", "DR-12 / ALTE SECTOARE"],
            "paired_official_source_id": "SRC-RO-AFIR-DR12-OTHER-EXHAUSTED-20261111",
            "corroborating_source_id": "SRC-RO-AFIR-DR12-COMPONENT-COUNTER",
            "adapter_required": "AFIR_DR12_COMPONENT_SESSION_LIST_SURFACEMC_IMMUTABLE_RECONCILE_V1",
            "material_fact_use": False,
            "credentials_required": False,
            "open_call_authorized": False,
            "material_fact_publication_authorized": False,
            "exact_call_identifier_verified": False,
            "exact_application_endpoint_verified": False,
        }
        for key, value in expected.items():
            if row.get(key) != value:
                fail("AFIR DR-12 session witness unsafe identity/gate: " + key)
        if not {"ROMANIA", "AFIR", "CALL_REGISTRY",
                "MARKET_INTELLIGENCE", "DISCOVERY"}.issubset(
                set(row.get("source_families") or [])):
            fail("AFIR DR-12 session witness lost official source family")
        if not {"other_sectors_exhausted_not_zootechnic",
                "current_exact_component_live_acceptance_unverified",
                "NO_OPEN_CALL"}.issubset(set(row.get("extract") or [])):
            fail("AFIR DR-12 live session list lost independent components/hold")
        forbidden = {
            "status", "call_status", "deadline", "budget", "budget_eur",
            "eligibility", "open_at", "close_at", "submission_endpoint",
            "exact_call_identifier", "final_url", "fetched_at",
            "raw_sha256", "semantic_sha256", "parser_version",
            "run_id", "handoff_sha256", "last_verified_open",
        }
        if forbidden.intersection(row):
            fail("AFIR DR-12 session discovery fabricated receipt/material fact")
        note = str(row.get("note") or "").upper()
        for key in ("SURFACEMC", "IMMUTABLE", "ZOOTEHNIC", "ALTE SECTOARE",
                    "VOLATILE", "RAW_SHA256", "PARSER_VERSION",
                    "RUN_ID", "LKG", "NO OPEN_CALL"):
            if key not in note:
                fail("AFIR DR-12 session witness missing provenance hold: " + key)

    _check_dr12_live(dr12_live)
    for mutation in (
        {"url": "https://example.com/afirmirror"},
        {"authority_scope": "LIVE_OPEN_CALL"},
        {"observation_state": "OPEN_CALL"},
        {"component_identities_discovery": ["DR-12"]},
        {"paired_official_source_id": "SRC-AFIR-OTHER"},
        {"source_families": ["ROMANIA", "AFIR"]},
        {"readback_date_discovery": "2026-11-11"},
        {"source_snapshot_is_volatile": False},
        {"open_call_authorized": True},
        {"material_fact_publication_authorized": True},
        {"exact_call_identifier_verified": True},
        {"exact_application_endpoint_verified": True},
        {"status": "OPEN"},
        {"deadline": "2026-12-02"},
        {"budget_eur": 84794823.5},
        {"eligibility": ["all farmers"]},
        {"fetched_at": "2026-11-21T09:00:00Z"},
        {"raw_sha256": "0" * 64},
        {"parser_version": "fabricated"},
        {"run_id": "fabricated"},
        {"submission_endpoint": "https://example.com/apply"},
        {"note": "Both calls confirmed OPEN"},
    ):
        try:
            _check_dr12_live(dict(dr12_live, **mutation))
        except SystemExit:
            pass
        else:
            fail("AFIR DR-12 volatile session witness mutation admitted: " + repr(mutation))

    # The exact IMREG-2026-INFOME topic and its dated official call fiche are
    # independent discovery inputs. An old indexed FORTHCOMING label or a
    # fiche's indicative opening date must never authorize OPEN_CALL.
    imreg_id = "IMREG-2026-INFOME"
    imreg_pair = {
        "SRC-EU-IMREG-2026-INFOME-EXACT-TOPIC": {
            "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/IMREG-2026-INFOME",
            "class": "official_eu_funding_tenders_exact_topic",
            "scope": "EXACT_TOPIC_DISCOVERY_ONLY",
            "state": "EXACT_TOPIC_STATUS_REVIEW_RAW_PENDING",
            "peer": "SRC-EU-IMREG-2026-INFOME-CALL-FICHE",
            "note_tokens": ("forthcoming", "indicative", "no open_call", "sha-256"),
        },
        "SRC-EU-IMREG-2026-INFOME-CALL-FICHE": {
            "url": "https://ec.europa.eu/info/funding-tenders/opportunities/docs/2021-2027/imreg/wp-call/2026/call-fiche_imreg-2026-infome_en.pdf",
            "class": "official_eu_funding_tenders_primary_call_document",
            "scope": "PRIMARY_CALL_DOCUMENT_DISCOVERY_ONLY",
            "state": "OFFICIAL_CALL_FICHE_RAW_PENDING",
            "peer": "SRC-EU-IMREG-2026-INFOME-EXACT-TOPIC",
            "note_tokens": ("v1.0", "indicative", "no open_call", "sha-256"),
        },
    }
    forbidden_imreg_claims = {
        "status", "call_status", "deadline", "budget", "budget_eur",
        "eligibility", "open_at", "close_at", "fetched_at",
        "raw_sha256", "semantic_sha256", "parser_version", "run_id",
        "handoff_sha256", "http_status", "submission_endpoint",
    }
    for source_id, expected in imreg_pair.items():
        row = by_id.get(source_id)
        if not row:
            fail(f"missing IMREG official topic/fiche pair: {source_id}")
        fields = {
            "url": expected["url"],
            "class": expected["class"],
            "tier": "T1",
            "topic_identifier_discovery": imreg_id,
            "authority_class": "T1_OFFICIAL_EC_FUNDING_TENDERS",
            "authority_scope": expected["scope"],
            "observation_state": expected["state"],
            "paired_official_source_id": expected["peer"],
            "material_fact_use": False,
            "credentials_required": False,
            "open_call_authorized": False,
            "material_fact_publication_authorized": False,
            "adapter_required": "EC_FT_EXACT_TOPIC_CURRENT_STATUS_AND_ENDPOINT_RECONCILE_V1",
        }
        if any(row.get(key) != value for key, value in fields.items()):
            fail(f"{source_id}: official IMREG identity/authority or fail-closed pairing drift")
        if not {"EU_DIRECT", "BRUSSELS", "CALL_REGISTRY", "DISCOVERY"}.issubset(
                set(row.get("source_families") or [])):
            fail(f"{source_id}: missing EU_DIRECT programme/source taxonomy")
        if forbidden_imreg_claims.intersection(row):
            fail(f"{source_id}: fabricated original evidence or material call facts")
        note = (row.get("note") or "").lower()
        if any(token not in note for token in expected["note_tokens"]):
            fail(f"{source_id}: missing indicative-calendar vs live-status guard")

    # Source discovery is not a verified call state. The official IMFV BV1B6
    # launch page has incompatible budget and deadline fields within itself.
    # Do not allow a source descriptor to launder either value into OPEN_CALL.
    bv1b6_id = "SRC-MAI-IMFV-BV1B6-LAUNCH-20261116"
    bv1b6 = by_id.get(bv1b6_id)
    if not bv1b6:
        fail("missing official IMFV BV1B6 exact-launch discovery")
    bv1b6_expected = {
        "tier": "T1",
        "url": "https://fed.mai.gov.ro/11756/bv1b6-actiuni-specifice-dotarea-politiei-de-frontiera-romane-pentru-cresterea-capacitatii-operationale-a-frontex2-lansare-apel-de-proiecte/",
        "call_identifier_discovery": "BV1B6",
        "authority_class": "T1_MANAGING_AUTHORITY_AFACERI_INTERNE",
        "authority_scope": "EXACT_CALL_LAUNCH_DISCOVERY_ONLY",
        "observation_state": "LAUNCH_ANNOUNCEMENT_DISCOVERED_RAW_PENDING",
        "adapter_required": "MAI_IMFV_EXACT_CALL_ROFED_RAW_RECONCILE_V1",
        "material_fact_use": False,
        "open_call_authorized": False,
        "material_fact_publication_authorized": False,
    }
    if any(bv1b6.get(k) != v for k, v in bv1b6_expected.items()):
        fail("BV1B6 discovery identity or fail-closed boundaries changed")
    if not {"ROMANIA", "MAI", "IMFV", "CALL_REGISTRY", "DISCOVERY"}.issubset(
            set(bv1b6.get("source_families") or [])):
        fail("BV1B6 programme/source families missing")
    if {
        "status", "call_status", "deadline", "budget", "budget_ron",
        "eligibility", "open_at", "close_at", "fetched_at", "raw_sha256",
        "semantic_sha256", "parser_version", "run_id", "submission_endpoint",
    }.intersection(bv1b6):
        fail("BV1B6 unacquired exact-call discovery fabricated material evidence")
    bv1b6_note = (bv1b6.get("note") or "").lower()
    if not all(token in bv1b6_note for token in (
            "112,226,000", "112226101", "12:00 am", "16:00",
            "rofed", "sha-256", "no open_call", "no distribution")):
        fail("BV1B6 conflicting official facts/raw-replay gate not documented")


    # The 16 Nov official BV23B launch is a distinct identifier and exact page.
    # The preceding consultation page says BV23A in body but BV23B in title
    # and attachment: no silent BV23A/B merge, OPEN_CALL or factual promotion.
    bv23b_id = "SRC-MAI-IMFV-BV23B-LAUNCH-20261116"
    bv23b = by_id.get(bv23b_id)
    if not bv23b:
        fail("missing official IMFV BV23B exact-launch discovery")
    bv23b_expected = {
        "tier": "T1",
        "url": "https://fed.mai.gov.ro/11749/bv23b-dezvoltarea-cooperarii-consulare-si-a-programelor-de-formare-lansare-apel-de-proiecte/",
        "call_identifier_discovery": "BV23B",
        "authority_class": "T1_MANAGING_AUTHORITY_AFACERI_INTERNE",
        "authority_scope": "EXACT_CALL_LAUNCH_DISCOVERY_ONLY",
        "observation_state": "LAUNCH_ANNOUNCEMENT_DISCOVERED_RAW_PENDING",
        "adapter_required": "MAI_IMFV_EXACT_CALL_ROFED_RAW_RECONCILE_V1",
        "material_fact_use": False,
        "open_call_authorized": False,
        "material_fact_publication_authorized": False,
    }
    if any(bv23b.get(k) != v for k, v in bv23b_expected.items()):
        fail("BV23B exact launch identity, source authority or negative gate changed")
    if not {"ROMANIA", "MAI", "IMFV", "CALL_REGISTRY", "DISCOVERY"}.issubset(
            set(bv23b.get("source_families") or [])):
        fail("BV23B source taxonomy missing")
    if {
        "status", "call_status", "deadline", "budget", "budget_ron",
        "eligibility", "open_at", "close_at", "fetched_at", "raw_sha256",
        "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
        "submission_endpoint",
    }.intersection(bv23b):
        fail("BV23B discovery fabricated material fact, exact endpoint or raw receipt")
    bv23b_note = (bv23b.get("note") or "").lower()
    if not all(token in bv23b_note for token in (
            "bv23a", "bv23b", "consultation", "450,000", "16:00",
            "rofed", "sha-256", "no open_call", "no distribution")):
        fail("BV23B distinct identity, official body/SUMAR or raw-evidence gate missing")
    if bv1b6.get("url") == bv23b.get("url") or bv1b6.get("call_identifier_discovery") == bv23b.get("call_identifier_discovery"):
        fail("BV1B6 and BV23B must remain distinct exact official calls")

    # 16 Nov official ADR Centru updates are NOT a submission-status signal.
    # A 23 Nov technical webinar and an extension for signing contracts
    # have different semantics from an open or extended funding application.
    prc_admin_notices = {
        "SRC-PRC-22-DIGITAL-APEL2-INFO-20261116": {
            "url": "https://www.regiocentru.ro/sesiune-online-de-informare-privind-apelul-de-proiecte-aferent-actiunii-2-2-intreprinderi-digitale-pentru-o-economie-avansata-apel-2/",
            "paired_official_source_id": "SRC-PR-CENTRU-DIGITAL-2",
            "authority_scope": "TECHNICAL_INFORMATION_SESSION_DISCOVERY_ONLY",
            "observation_state": "INFORMATION_SESSION_DISCOVERED_RAW_PENDING",
            "adapter_required": "REGIOCENTRU_INFORMATION_EVENT_RAW_PAIR_RECONCILE_V1",
            "event_terms": ("23 november 2026", "12:00", "information", "not the project application"),
            "family": "INFORMATION_EVENT",
        },
        "SRC-PRC-111-CDI-CONTRACT-SIGN-20261116": {
            "url": "https://www.regiocentru.ro/a-fost-prelungit-termenul-de-semnare-a-contractelor-de-finantare-pentru-cererile-de-finantare-depuse-in-cadrul-programului-regiunea-centru-interventia-1-1-1-dezvoltarea-cap/",
            "authority_scope": "CONTRACT_SIGNING_EXTENSION_DISCOVERY_ONLY",
            "observation_state": "CONTRACT_SIGNING_NOTICE_DISCOVERED_RAW_PENDING",
            "adapter_required": "REGIOCENTRU_CONTRACT_SIGNING_NOTICE_RAW_RECONCILE_V1",
            "event_terms": ("signing financing contracts", "not an extension", "does not reopen"),
            "family": "CONTRACTING_ADMINISTRATION",
        },
    }
    for source_id, expected in prc_admin_notices.items():
        row = by_id.get(source_id)
        if row is None:
            fail(f"missing 16-Nov PR Centru non-call source {source_id}")
        for field in ("url", "authority_scope", "observation_state", "adapter_required"):
            if row.get(field) != expected[field]:
                fail(f"{source_id}: {field} changed or confused with an OPEN call")
        if row.get("tier") != "T1" or row.get("event_date_discovery") != "2026-11-16":
            fail(f"{source_id}: official authority/date discovery drift")
        if row.get("material_fact_use") is not False or row.get("open_call_authorized") is not False or row.get("material_fact_publication_authorized") is not False:
            fail(f"{source_id}: administrative/event notice cannot authorize material call facts")
        if not {"ROMANIA", "ADR", "DISCOVERY", expected["family"]}.issubset(set(row.get("source_families") or [])):
            fail(f"{source_id}: source family missing or corrupted")
        if row.get("paired_official_source_id") != expected.get("paired_official_source_id"):
            fail(f"{source_id}: distinct call/event pairing missing or fabricated")
        if {
            "call_status", "status", "deadline", "close_at", "open_at",
            "budget", "eligibility", "submission_endpoint", "raw_sha256",
            "semantic_sha256", "fetched_at", "parser_version", "run_id",
        }.intersection(row):
            fail(f"{source_id}: administrative discovery fabricated raw receipt or application facts")
        note = (row.get("note") or "").lower()
        if not all(token in note for token in expected["event_terms"]):
            fail(f"{source_id}: missing explicit webinar vs application or contracting distinction")
        if "no open_call" not in note or "not_captured" not in note:
            fail(f"{source_id}: missing fail-closed status/provenance contract")

    # The September AFIR energy notice advertises two distinct public-entity
    # sessions that may terminate early as allocations are exhausted. An old
    # timetable and the generic application gateway never prove current OPEN.
    energy = by_id.get("SRC-RO-AFIR-ENERGY-PUBLIC-20260917")
    if energy is None:
        fail("missing AFIR 2026 public-energy exact source discovery")
    if energy.get("url") != "https://www.afir.ro/info-la-zi/comunicat-derulare-sesiune-autoconsum-si-stocare-energie-electrica-beneficiari-publici/":
        fail("AFIR energy notice official authority URL drift")
    if energy.get("application_gateway_discovery") != "https://depunerepspac.afir.ro/":
        fail("AFIR energy gateway must remain discovery, not a verified call submission endpoint")
    if energy.get("tier") != "T1" or energy.get("authority_class") != "T1_OFFICIAL_AGENCY":
        fail("AFIR energy discovery authority provenance drift")
    if not {"ROMANIA", "AFIR", "ENERGY", "CALL_REGISTRY", "DISCOVERY"}.issubset(set(energy.get("source_families") or [])):
        fail("AFIR energy source family drift")
    if energy.get("observation_state") != "SCHEDULE_NOTICE_DISCOVERED_LIVE_ENDPOINT_403_RAW_PENDING":
        fail("AFIR energy notice must remain raw-pending until immutable receipt")
    if any(energy.get(key) is not False for key in (
        "material_fact_use", "open_call_authorized",
        "material_fact_publication_authorized", "call_identifiers_verified",
        "current_application_endpoints_verified",
    )):
        fail("historical AFIR two-call schedule must never authorize OPEN or material facts")
    if energy.get("adapter_required") != "AFIR_ENERGY_2026_TWO_CALLS_CURRENT_ENDPOINT_RECONCILE_V1":
        fail("AFIR energy notice requires separate live call identifiers and reconciliation")
    if {"deadline", "open_at", "close_at", "budget", "eligibility", "status",
         "raw_sha256", "fetched_at", "parser_version", "run_id"}.intersection(energy):
        fail("AFIR energy historical discovery cannot fabricate canonical facts or raw evidence")
    if not all(token in (energy.get("note") or "").lower() for token in (
        "two distinct", "not proof of current open_call", "early exhaustion",
        "http 403", "no exact individual call identifier",
    )):
        fail("AFIR energy source must explicitly distinguish scheduled from current status")

    # AFIR's 30-Oct dated press notice supplies application-demand intelligence
    # for TWO distinct public-energy calls; historical demand is never proof
    # of current intake status, awards or exact gateway availability.
    demand_id = "SRC-RO-AFIR-ENERGY-PUBLIC-INTAKE-20261030"
    demand = by_id.get(demand_id)
    if demand is None:
        fail("missing AFIR 30-Oct public energy application-demand source")
    if demand.get("url") != (
        "https://www.afir.ro/info-la-zi/"
        "peste-760-de-milioane-solicitate-de-entit%C4%83%C8%9Bile-publice-"
        "pentru-producerea-%C8%99i-stocarea-energiei-regenerabile/"
    ):
        fail("AFIR energy-demand primary official URL drift")
    expected_demand = {
        "tier": "T1",
        "authority_class": "T1_OFFICIAL_AGENCY",
        "authority_scope": "TWO_DISTINCT_CALLS_HISTORICAL_SUBMISSION_DEMAND_INTELLIGENCE_ONLY",
        "observation_state": "HISTORICAL_SUBMISSION_VOLUME_DISCOVERED_RAW_PENDING",
        "event_date_discovery": "2026-10-30",
        "paired_official_source_id": "SRC-RO-AFIR-ENERGY-PUBLIC-20260917",
        "adapter_required": "AFIR_ENERGY_2026_APPLICATION_VOLUME_RAW_RECONCILE_V1",
        "material_fact_use": False,
        "open_call_authorized": False,
        "material_fact_publication_authorized": False,
        "call_identifiers_verified": False,
        "current_application_endpoints_verified": False,
    }
    if any(demand.get(key) != value for key, value in expected_demand.items()):
        fail("AFIR energy-demand identity, source authority or negative gate drift")
    if not {"ROMANIA", "AFIR", "ENERGY", "DISCOVERY"}.issubset(
            set(demand.get("source_families") or [])):
        fail("AFIR energy-demand provenance taxonomy missing")
    disallowed = {
        "status", "call_status", "deadline", "close_at", "open_at", "budget",
        "eligibility", "submission_endpoint", "raw_sha256", "semantic_sha256",
        "fetched_at", "parser_version", "run_id", "handoff_sha256",
    }
    if disallowed.intersection(demand):
        fail("AFIR energy-demand discovery invented live material fact or raw receipt")
    demand_obs = demand.get("discovery_only_submission_observation") or {}
    if demand_obs.get("as_of_date") != "2026-10-30":
        fail("AFIR demand as-of date cannot be replaced by the execution date")
    solar = demand_obs.get("solar_with_integrated_storage") or {}
    storage = demand_obs.get("standalone_storage") or {}
    if (solar.get("submitted_applications"), solar.get("requested_eur"),
            solar.get("announced_allocation_eur")) != (1520, 448675448, 500000000):
        fail("AFIR solar demand/allocation changed without official raw reconciliation")
    if (storage.get("submitted_applications"), storage.get("requested_eur"),
            storage.get("announced_allocation_eur")) != (925, 311690380, 150000000):
        fail("AFIR independent storage demand/allocation changed without raw reconciliation")
    if demand_obs.get("total_submitted_applications") != 2445 or (
            demand_obs.get("total_requested_eur") != 760365828 or
            demand_obs.get("aggregate_announced_allocations_eur") != 650000000):
        fail("AFIR aggregate demand is not grounded to the 30-Oct authority")
    if (solar["submitted_applications"] + storage["submitted_applications"] !=
            demand_obs["total_submitted_applications"] or
            solar["requested_eur"] + storage["requested_eur"] !=
            demand_obs["total_requested_eur"] or
            solar["announced_allocation_eur"] + storage["announced_allocation_eur"] !=
            demand_obs["aggregate_announced_allocations_eur"]):
        fail("AFIR per-call submission/allocations arithmetic mismatch")
    if demand_obs.get("raw_receipt_state") != "NOT_CAPTURED" or (
            demand_obs.get("observation_kind") !=
            "DEMAND_ONLY_NOT_APPROVAL_OR_LIVE_OPEN_STATUS"):
        fail("AFIR demand metadata fabricated immutable receipt or grants awarded")
    note = (demand.get("note") or "").lower()
    if not all(token in note for token in (
            "two distinct", "not prove current open_call", "not approved grants",
            "not_capture", "no open_call", "solar allocation itself")):
        fail("AFIR demand market-intelligence evidence and fail-closed caveats missing")

    validate_thcs_2027_preannouncement(by_id, programme_domains)
    validate_impact_lot3_pair(by_id)
    validate_water4all_2026_pair(by_id)
    test_water4all_adversarial_pairs(by_id)

    policy = data.get("policy") or {}
    if "OPEN_CALL" not in policy.get("programming_pipeline_rule", ""):
        fail("programming pipeline guard must explicitly prohibit OPEN_CALL promotion")
    direct_rule = policy.get("direct_funding_gateway_rule", "").lower()
    if "dedicated" not in direct_rule or "programme-specific" not in direct_rule or "call index" not in direct_rule:
        fail("direct funding policy must require programme-specific dedicated exact-call/action evidence and keep indexes/guides non-authorizing")


    # FutureFoodS 2026 GETS Third Joint Transnational Call: official 3-Nov
    # launch and the Romanian national co-funder form one *exact edition* pair.
    # The operator's generic index still labels the SECOND call Open; this
    # mixed-generation index must never authorize OPEN for the third call.
    futurefoods_pair = {
        "SRC-EU-FUTUREFOODS-2026-GETS-JTC3": (
            "https://www.futurefoodspartnership.eu/news/announcement-third-call",
            "T1", "EXACT_JTC3_LAUNCH_DISCOVERY_ONLY",
            "EXACT_THIRD_CALL_LAUNCH_DISCOVERED_RAW_PENDING",
            "SRC-RO-UEFISCDI-FUTUREFOODS-2026-JTC3",
            {"EU_DIRECT", "BRUSSELS", "JOINT_TRANSNATIONAL_CALL", "CALL_REGISTRY"},
        ),
        "SRC-RO-UEFISCDI-FUTUREFOODS-2026-JTC3": (
            "https://uefiscdi.gov.ro/future-of-food-systems-partnership-futurefoods",
            "T1B", "ROMANIA_JTC3_NATIONAL_RULES_DISCOVERY_ONLY",
            "NATIONAL_THIRD_CALL_REFERENCE_DISCOVERED_RAW_PENDING",
            "SRC-EU-FUTUREFOODS-2026-GETS-JTC3",
            {"ROMANIA", "EU_DIRECT", "JOINT_TRANSNATIONAL_CALL", "CALL_REGISTRY"},
        ),
    }
    for source_id, (url, tier, scope, state, pair, families) in futurefoods_pair.items():
        row = by_id.get(source_id)
        if not row:
            fail(f"missing FutureFoodS JTC3 national/partnership pair: {source_id}")
        if (row.get("url"), row.get("tier"), row.get("authority_scope"),
                row.get("observation_state"), row.get("paired_official_source_id")) != (
                url, tier, scope, state, pair):
            fail(f"{source_id} lost exact third-call edition or raw-pending pairing")
        if row.get("programme_family") != (
                "Horizon Europe / FutureFoodS / GETS Third Joint Transnational Call 2026"):
            fail(f"{source_id} mixed FutureFoodS calls or editions")
        if row.get("programmes") != ["EU direct programmes"] or not families.issubset(
                set(row.get("source_families") or [])):
            fail(f"{source_id} lost direct/national source taxonomy")
        if row.get("adapter_required") != (
                "FUTUREFOODS_2026_JTC3_EXACT_CALL_NATIONAL_RULES_RECONCILE_V1"):
            fail(f"{source_id} bypassed exact call, stage and Romanian annex reconciliation")
        if (row.get("material_fact_use") is not False
                or row.get("credentials_required") is not False
                or row.get("open_call_authorized") is not False
                or row.get("material_fact_publication_authorized") is not False):
            fail(f"{source_id} allowed premature material or OPEN_CALL promotion")
        if any(key in row for key in (
                "status", "call_status", "deadline", "application_deadline",
                "budget", "budget_eur", "eligibility", "open_at", "close_at",
                "submission_endpoint", "fetched_at", "fetched_at_utc",
                "raw_sha256", "semantic_sha256", "parser_version", "run_id",
                "handoff_sha256", "last_verified_open")):
            fail(f"{source_id} fabricated raw acquisition or material call fields")
        note = (row.get("note") or "").lower()
        if (not all(x in note for x in (
                "second call", "immutable", "no open_call", "national", "reconcil"))
                or not any(x in note for x in ("third call", "third joint call"))):
            fail(f"{source_id} lost old-index/non-authorizing and provenance gates")
    europe = by_id["SRC-EU-FUTUREFOODS-2026-GETS-JTC3"]
    romania = by_id["SRC-RO-UEFISCDI-FUTUREFOODS-2026-JTC3"]
    if europe.get("generic_index_conflict_witness") != (
            "https://www.futurefoodspartnership.eu/funding-opportunities"):
        fail("FutureFoodS old Second Call index conflict lost")
    if romania.get("news_url_discovery") != (
            "https://uefiscdi.gov.ro/news-parteneriatul-futurefoods-lanseaza-cel-de-al-treilea-apel-transnational-pentru-proiecte-de-cercetare-si-inovare"):
        fail("FutureFoodS Romanian co-funder 4 Nov launch corroboration lost")
    if "invitation_only_stage2_discriminator" not in europe.get("extract", []):
        fail("FutureFoodS stage-2 invitation is not a generic open-intake claim")

    # HaDEA agency reference drops a separator relative to the actual F&T topic URL.
    # A coarse agency "Open" label must never resolve exact F&T submission status.
    hadea = by_id.get("SRC-EU-HADEA-CL4-2027-PHOTONICS-ID-WITNESS") or {}
    ft_photonics = by_id.get("SRC-EU-HORIZON-CL4-2027-PHOTONICS-FORTHCOMING") or {}
    if not hadea or not ft_photonics:
        fail("HaDEA photonics identity witness and exact F&T topic source must be paired")
    if hadea.get("paired_official_source_id") != ft_photonics.get("id"):
        fail("HaDEA witness lost exact F&T pairing")
    if hadea.get("displayed_reference_discovery") == hadea.get("ft_exact_topic_identifier_discovery"):
        fail("HaDEA display-id separator drift no longer exposed for reconciliation")
    if hadea.get("ft_exact_topic_identifier_discovery") != ft_photonics.get("topic_identifier_discovery"):
        fail("HaDEA witness silently rewrote F&T exact topic identifier")
    if (hadea.get("material_fact_use") is not False or
            hadea.get("open_call_authorized") is not False or
            hadea.get("material_fact_publication_authorized") is not False or
            hadea.get("status_display_is_current_call_authority") is not False or
            hadea.get("observation_state") != "AGENCY_REFERENCE_FORMAT_AND_STATUS_WITNESS_RAW_PENDING"):
        fail("HaDEA readback cannot authorize OPEN_CALL or material publication")

    # ERA4Health JTC10: a date scheduled for publication is not proof that
    # the exact call endpoint is OPEN. On 17 November the operator's own
    # live-discovery page still self-identifies as a PRE-ANNOUNCEMENT.
    # The Romanian UEFISCDI calendar repeats that launch date; do not
    # silently promote either page, infer national eligibility, or alias JTC9.
    nanodiag_pair = {
        "SRC-EU-ERA4HEALTH-NANODIAGNCD-2027-JTC10": (
            "https://era4health.eu/calls/pre_NanoDiagNCD2027.php",
            "T1", "PREANNOUNCEMENT_AND_EXPECTED_LAUNCH_DISCOVERY_ONLY",
            "PREANNOUNCEMENT_STILL_DISPLAYED_ON_LAUNCH_DATE_RAW_PENDING",
            "SRC-RO-UEFISCDI-ERA4HEALTH-NANODIAGNCD-2027-JTC10",
            {"EU_DIRECT", "BRUSSELS", "JOINT_TRANSNATIONAL_CALL", "DISCOVERY"},
        ),
        "SRC-RO-UEFISCDI-ERA4HEALTH-NANODIAGNCD-2027-JTC10": (
            "https://uefiscdi.gov.ro/fostering-a-european-research-area-for-health-era4health",
            "T1B", "ROMANIAN_JTC10_REFERENCE_AND_NATIONAL_PACKAGE_DISCOVERY_ONLY",
            "NATIONAL_LAUNCH_DATE_LISTED_PARTNERSHIP_PREANNOUNCEMENT_RAW_PENDING",
            "SRC-EU-ERA4HEALTH-NANODIAGNCD-2027-JTC10",
            {"ROMANIA", "EU_DIRECT", "JOINT_TRANSNATIONAL_CALL", "DISCOVERY"},
        ),
    }
    for source_id, (url, tier, scope, state, paired, families) in nanodiag_pair.items():
        row = by_id.get(source_id)
        if not row:
            fail(f"ERA4Health NanoDiagNCD JTC10 official pair missing: {source_id}")
        if (row.get("url"), row.get("tier"), row.get("authority_scope"),
                row.get("observation_state"), row.get("paired_official_source_id")) != (
                url, tier, scope, state, paired):
            fail(f"{source_id}: preannouncement/launch identity or pairing drift")
        if row.get("programme_family") != (
                "Horizon Europe / ERA4Health / NanoDiagNCD 2027 JTC10"):
            fail(f"{source_id}: JTC10 mixed with historic JTC9/other editions")
        if row.get("programmes") != ["EU direct programmes"] or not families.issubset(
                set(row.get("source_families") or [])):
            fail(f"{source_id}: source family taxonomy missing")
        if "PROGRAMMING_PIPELINE" in (row.get("source_families") or []):
            fail(f"{source_id}: call preannouncement misclassified as future MFF programming")
        if row.get("event_date_discovery") != "2026-11-17":
            fail(f"{source_id}: launch-date witness silently shifted")
        if row.get("adapter_required") != (
                "ERA4HEALTH_NANODIAGNCD_2027_JTC10_LIVE_CALL_NATIONAL_RULES_RECONCILE_V1"):
            fail(f"{source_id}: live exact-call/national semantic gate missing")
        if any(row.get(key) is not False for key in (
                "material_fact_use", "credentials_required", "open_call_authorized",
                "material_fact_publication_authorized")):
            fail(f"{source_id}: premature OPEN_CALL or publication permission")
        if {"status", "call_status", "deadline", "application_deadline", "budget",
            "budget_eur", "eligibility", "submission_endpoint", "open_at", "close_at",
            "raw_sha256", "semantic_sha256", "fetched_at", "fetched_at_utc",
            "parser_version", "run_id", "handoff_sha256", "last_verified_open"
            }.intersection(row):
            fail(f"{source_id}: a discovery descriptor fabricated material data or raw provenance")
        note = (row.get("note") or "").lower()
        if not all(token in note for token in (
                "pre-announcement", "17 november", "not_captured",
                "open_call", "immutable", "national")):
            fail(f"{source_id}: historical schedule vs live status/fail-closed receipt distinction lost")
    nano_eu = by_id["SRC-EU-ERA4HEALTH-NANODIAGNCD-2027-JTC10"]
    nano_ro = by_id["SRC-RO-UEFISCDI-ERA4HEALTH-NANODIAGNCD-2027-JTC10"]
    if nano_eu.get("exact_edition_identifier_discovery") != (
            "NanoDiagNCD 2027 / ERA4Health JTC10"):
        fail("ERA4Health exact partnership JTC10 identifier mutated")
    if nano_ro.get("exact_edition_identifier_discovery") != (
            "ERA4Health NanoDiagNCD2027 / JTC10"):
        fail("ERA4Health exact national JTC10 identifier mutated")
    if "expected_launch_date_not_current_open_status" not in nano_eu.get("extract", []):
        fail("ERA4Health expected launch date cannot authorize OPEN_CALL")


    # ERA4HEALTH_JTC10_LAUNCH_WITNESS (17 Nov): the exact post-preannouncement
    # operator landing page is distinct, but says PT-Outline opens only
    # on 20 November; a national generic index "open" label cannot
    # authorize an exact OPEN_CALL before a live submission transaction.
    launch = by_id.get(
        "SRC-EU-ERA4HEALTH-NANODIAGNCD-2027-JTC10-LAUNCH-WITNESS")
    if not launch:
        fail("ERA4Health JTC10 exact launch landing witness missing")
    if (launch.get("url"), launch.get("tier"),
            launch.get("authority_scope"), launch.get("observation_state")) != (
            "https://era4health.eu/calls/NanoDiagNCD2027.php",
            "T1", "EXACT_JTC10_LAUNCH_PAGE_DISCOVERY_ONLY",
            "CALL_PAGE_LAUNCHED_SUBMISSION_GATEWAY_PLANNED_RAW_PENDING"):
        fail("JTC10 exact new launch page misidentified or premature OPEN status")
    if launch.get("linked_preannouncement_source_id") != (
            "SRC-EU-ERA4HEALTH-NANODIAGNCD-2027-JTC10"):
        fail("JTC10 launch must not overwrite its preannouncement")
    if launch.get("linked_national_source_id") != (
            "SRC-RO-UEFISCDI-ERA4HEALTH-NANODIAGNCD-2027-JTC10"):
        fail("JTC10 launch lacks national-reconciliation link")
    if (launch.get("programme_family") !=
            "Horizon Europe / ERA4Health / NanoDiagNCD 2027 JTC10"
            or launch.get("exact_edition_identifier_discovery") !=
            "NanoDiagNCD 2027 / ERA4Health JTC10"):
        fail("JTC10 launch accidentally aliased to other ERA4Health calls")
    if launch.get("event_date_discovery") != "2026-11-17":
        fail("JTC10 launch publication date changed without official evidence")
    if launch.get("adapter_required") != (
            "ERA4HEALTH_NANODIAGNCD_2027_JTC10_LIVE_CALL_NATIONAL_RULES_RECONCILE_V1"):
        fail("JTC10 exact gateway/national reconciliation gate removed")
    if not {"EU_DIRECT", "BRUSSELS", "CALL_REGISTRY", "DISCOVERY"}.issubset(
            set(launch.get("source_families") or [])):
        fail("JTC10 operator launch source taxonomy incomplete")
    if "PROGRAMMING_PIPELINE" in (launch.get("source_families") or []):
        fail("JTC10 published landing is not future MFF programming")
    for key in ("material_fact_use", "credentials_required",
                "open_call_authorized", "material_fact_publication_authorized"):
        if launch.get(key) is not False:
            fail(f"JTC10 launch bypassed fail-closed authorization: {key}")
    if {"status", "call_status", "deadline", "application_deadline", "budget",
        "budget_eur", "eligibility", "submission_endpoint", "open_at", "close_at",
        "raw_sha256", "semantic_sha256", "fetched_at", "fetched_at_utc",
        "final_url", "parser_version", "run_id", "handoff_sha256",
        "last_verified_open"}.intersection(launch):
        fail("JTC10 exact landing fabricated current OPEN/terms/raw receipt")
    expected_extracts = {
        "exact_jtc10_post_preannouncement_call_landing_discovery",
        "submission_platform_planned_20_nov_2026_not_yet_live_verified",
        "call_documents_links_still_blank_at_readback",
        "romanian_national_index_new_open_label_vs_operator_gateway_not_open",
    }
    if not expected_extracts.issubset(set(launch.get("extract") or [])):
        fail("JTC10 planned submission platform and blank documents gate lost")
    launch_note = (launch.get("note") or "").lower()
    if not all(word in launch_note for word in (
            "17 november", "20 november", "jtc10", "not_captured",
            "open_call", "pre-announcement", "national", "immutable")):
        fail("JTC10 launch status / national index conflict improperly resolved")

    # EIT_STEM_TALENT_2026_DEADLINE_CONFLICT: original operator call
    # (including its PDF) has 17:00 CET, but UEFISCDI NCP says 00:00 CET.
    # The divergent NCP time is never canonicalized by a registry descriptor.
    eit_stem_sources = {
        "SRC-EU-EIT-STEM-TALENT-2026-OPERATOR": (
            "https://eitstemtalent.eu/calls-and-opportunities/now-open-eit-stem-talent-call-for-proposals-2026/",
            "T1", "T1_OFFICIAL_EIT_DELEGATED_CALL_OPERATOR",
            "OFFICIAL_OPERATOR_1700_VS_NCP_0000_CET_DEADLINE_CONFLICT_RAW_PENDING",
            "SRC-RO-UEFISCDI-EIT-STEM-TALENT-2026-NCP",
            {"EU_DIRECT", "BRUSSELS", "EIT", "CALL_REGISTRY", "DISCOVERY"},
        ),
        "SRC-EU-EIT-STEM-TALENT-2026-CALL-TEXT": (
            "https://eitstemtalent.eu/wp-content/uploads/gb/2026/10/call_for_proposals_2026.pdf",
            "T1", "T1_OFFICIAL_DELEGATED_CALL_DOCUMENT",
            "OFFICIAL_PDF_1700_VS_NCP_0000_CET_DEADLINE_CONFLICT_RAW_PENDING",
            "SRC-EU-EIT-STEM-TALENT-2026-OPERATOR",
            {"EU_DIRECT", "BRUSSELS", "EIT", "CALL_DOCUMENT", "DISCOVERY"},
        ),
        "SRC-RO-UEFISCDI-EIT-STEM-TALENT-2026-NCP": (
            "https://uefiscdi.gov.ro/news-s-a-deschis-apelul-eit-stem-talent-2026",
            "T1B", "T1B_ROMANIAN_NCP_INFORMATION_NOT_CALL_OPERATOR",
            "NATIONAL_NCP_0000_VS_OPERATOR_1700_CET_DEADLINE_CONFLICT_RAW_PENDING",
            "SRC-EU-EIT-STEM-TALENT-2026-OPERATOR",
            {"ROMANIA", "EU_DIRECT", "EIT", "CALL_REGISTRY", "DISCOVERY"},
        ),
    }
    eit_stem_family = "EIT STEM Tech Talent Induction / Building Future-Ready STEM Talent / Call 2026"
    eit_stem_adapter = "EIT_STEM_TALENT_2026_OPERATOR_PDF_NCP_DEADLINE_RECONCILE_V1"
    for source_id, (url, tier, authority, state, paired, families) in eit_stem_sources.items():
        source = by_id.get(source_id)
        if not source:
            fail(f"EIT STEM Talent 2026 authority witness missing: {source_id}")
        expected = {
            "url": url, "tier": tier, "authority_class": authority,
            "observation_state": state,
            "paired_official_source_id": paired,
            "programme_family": eit_stem_family,
            "exact_edition_identifier_discovery": "EIT STEM Tech Talent Induction 2026 Call: Building Future-Ready STEM Talent",
            "adapter_required": eit_stem_adapter,
            "readback_date_discovery": "2026-11-17",
            "programmes": ["EU direct programmes"],
        }
        for key, value in expected.items():
            if source.get(key) != value:
                fail(f"{source_id}: operator/NCP deadline conflict identity drift: {key}")
        if not families.issubset(set(source.get("source_families") or [])):
            fail(f"{source_id}: missing official EIT or Romanian NCP discovery family")
        if "PROGRAMMING_PIPELINE" in (source.get("source_families") or []):
            fail(f"{source_id}: live call witness wrongly classified as future programming")
        for key in ("material_fact_use", "credentials_required",
                    "open_call_authorized", "material_fact_publication_authorized"):
            if source.get(key) is not False:
                fail(f"{source_id}: raw-pending source illegally authorized material facts: {key}")
        forbidden = {
            "status", "call_status", "deadline", "close_at", "budget",
            "eligibility", "submission_endpoint", "fetched_at", "raw_sha256",
            "parser_version", "run_id", "handoff_sha256",
        }
        if forbidden.intersection(source):
            fail(f"{source_id}: fabricated authoritative current call/receipt field")
        note = (source.get("note") or "").lower()
        if not all(token in note for token in (
                "14 december 2026", "17:00 cet", "00:00 cet", "not_captured")):
            fail(f"{source_id}: unacknowledged 17-hour NCP/operator discrepancy")
        if not any(token in note for token in ("no open_call", "no open_call,")):
            fail(f"{source_id}: missing fail-closed publication disclaimer")
    eit_stem_operator = by_id["SRC-EU-EIT-STEM-TALENT-2026-OPERATOR"]
    eit_stem_pdf = by_id["SRC-EU-EIT-STEM-TALENT-2026-CALL-TEXT"]
    eit_stem_ncp = by_id["SRC-RO-UEFISCDI-EIT-STEM-TALENT-2026-NCP"]
    if (eit_stem_operator["id"] == eit_stem_ncp["id"] or
            eit_stem_pdf["url"] == eit_stem_operator["url"] or
            eit_stem_operator["programme_family"] ==
            by_id["SRC-EU-EIT-HEI-2026-EXACT-CALL"].get("programme_family", "")):
        fail("EIT STEM Talent 2026 incorrectly aliased to EIT HEI or its NCP")
    if not ("1700_cet" in " ".join(eit_stem_pdf["extract"]) and
            "0000_cet" in " ".join(eit_stem_ncp["extract"])):
        fail("EIT STEM Talent 2026 exact call PDF / national time conflict lost")

    # EIT Community NEB 2027 has two DIFFERENT opportunities. The Enhance
    # source is corroborated by a Romanian informational notice; the Catalyse
    # accelerator is not an alternative name for Enhance. Neither registry
    # witness carries immutable original receipts or publication authority.
    # EIT_NEBS_2027_DISTINCT_DISCOVERY
    eit_neb_2027 = {
        "SRC-EU-EIT-NEB-ENHANCE-2027": (
            "https://www.eit.europa.eu/our-activities/opportunities/enhance-neb-open-call-2027",
            "T1", "Enhance NEB 2027",
            "EIT Community New European Bauhaus / Enhance NEB 2027",
            "ENHANCE_2027_EXACT_EDITION_DISCOVERY_ONLY",
            "EIT_ENHANCE_2027_OFFICIAL_PAGE_READBACK_RAW_PENDING",
            "SRC-RO-UEFISCDI-EIT-NEB-ENHANCE-2027",
            "EIT_NEB_ENHANCE_2027_EXACT_EDITION_RAW_AND_SUBMISSION_RECONCILE_V1",
            {"EU_DIRECT", "BRUSSELS", "EIT", "CALL_REGISTRY", "DISCOVERY"},
        ),
        "SRC-RO-UEFISCDI-EIT-NEB-ENHANCE-2027": (
            "https://uefiscdi.gov.ro/news-apel-enhance-neb-2027",
            "T1B", "Enhance NEB 2027",
            "EIT Community New European Bauhaus / Enhance NEB 2027",
            "ENHANCE_2027_ROMANIAN_INFORMATION_DISCOVERY_ONLY",
            "UEFISCDI_ENHANCE_2027_NATIONAL_NEWS_READBACK_RAW_PENDING",
            "SRC-EU-EIT-NEB-ENHANCE-2027",
            "EIT_NEB_ENHANCE_2027_EXACT_EDITION_RAW_AND_SUBMISSION_RECONCILE_V1",
            {"ROMANIA", "EU_DIRECT", "EIT", "CALL_REGISTRY", "DISCOVERY"},
        ),
        "SRC-EU-EIT-NEB-CATALYSE-2027": (
            "https://www.eit.europa.eu/our-activities/opportunities/catalyse-neb-2027-open-call",
            "T1", "Catalyse NEB 2027",
            "EIT Community New European Bauhaus / Catalyse NEB 2027",
            "CATALYSE_2027_EXACT_EDITION_DISCOVERY_ONLY",
            "EIT_CATALYSE_2027_OFFICIAL_PAGE_READBACK_RAW_PENDING",
            None,
            "EIT_NEB_CATALYSE_2027_EXACT_EDITION_RAW_AND_SUBMISSION_RECONCILE_V1",
            {"EU_DIRECT", "BRUSSELS", "EIT", "CALL_REGISTRY", "DISCOVERY"},
        ),
    }
    for source_id, (url, tier, edition, family, scope, state, paired,
                    adapter, families) in eit_neb_2027.items():
        source = by_id.get(source_id)
        if not source:
            fail(f"EIT NEB 2027 official discovery source missing: {source_id}")
        expected = {
            "url": url, "tier": tier,
            "exact_edition_identifier_discovery": edition,
            "programme_family": family, "authority_scope": scope,
            "observation_state": state, "adapter_required": adapter,
            "readback_date_discovery": "2026-11-17",
            "programmes": ["EU direct programmes"],
        }
        for key, value in expected.items():
            if source.get(key) != value:
                fail(f"{source_id}: official EIT edition or non-authorizing readback drift: {key}")
        if source.get("paired_official_source_id") != paired:
            fail(f"{source_id}: wrong paired information witness or identity alias")
        if not families.issubset(set(source.get("source_families") or [])):
            fail(f"{source_id}: missing EU/RO discovery taxonomy")
        if "PROGRAMMING_PIPELINE" in (source.get("source_families") or []):
            fail(f"{source_id}: application-opportunity discovery is not MFF programming")
        if any(source.get(k) is not False for k in (
                "material_fact_use", "credentials_required",
                "open_call_authorized", "material_fact_publication_authorized")):
            fail(f"{source_id}: unacquired readback illegally authorized a material call")
        forbidden = {
            "status", "call_status", "open_at", "close_at", "deadline",
            "application_deadline", "budget", "budget_eur", "eligibility",
            "submission_endpoint", "fetched_at", "fetched_at_utc",
            "raw_sha256", "semantic_sha256", "parser_version", "run_id",
            "handoff_sha256", "last_verified_open",
        }
        if forbidden.intersection(source):
            fail(f"{source_id}: fabricated current call fields or immutable receipt")
        note = (source.get("note") or "").lower()
        if not all(token in note for token in (
                "not_captured", "no open_call", "immutable", "2027")):
            fail(f"{source_id}: raw-pending or no-OPEN provenance disclaimer missing")
    enhance = by_id["SRC-EU-EIT-NEB-ENHANCE-2027"]
    catalyse = by_id["SRC-EU-EIT-NEB-CATALYSE-2027"]
    national = by_id["SRC-RO-UEFISCDI-EIT-NEB-ENHANCE-2027"]
    if (enhance["programme_family"] == catalyse["programme_family"] or
            enhance["exact_edition_identifier_discovery"] ==
            catalyse["exact_edition_identifier_discovery"] or
            catalyse.get("paired_official_source_id") == national["id"]):
        fail("EIT NEB Catalyse startup track was aliased to restricted Enhance call")
    if not ("17_november" in " ".join(enhance["extract"]) and
            "15_january" in " ".join(catalyse["extract"])):
        fail("EIT NEB edition-specific observed cutoff dates were conflated")
    if national.get("authority_class") != "T1B_ROMANIAN_NCP_INFORMATION_NOT_FUNDER":
        fail("UEFISCDI EIT NEB information was falsely upgraded to Romanian operator")

    # IF26_FIVE_PLANNED_CALLS_FAIL_CLOSED: official CINEA 17 Nov 2026 news
    # only announces five calls PLANNED for 3 Dec (three grants, two
    # auctions). Neither the Info Days nor a programme envelope opens them.
    if26_id = "SRC-EU-CINEA-IF26-20261117-FIVE-PLANNED-CALLS"
    if26 = by_id.get(if26_id)
    if not if26:
        fail("CINEA IF26 17 November five-call programming witness missing")
    if if26.get("url") != (
        "https://cinea.ec.europa.eu/news-events/news/"
        "registrations-open-innovation-fund-2026-info-days-2026-11-17_en"
    ):
        fail("IF26 exact official news endpoint lost")
    expected_if26 = {
        "tier": "T1",
        "authority_class": "T1_OFFICIAL_CINEA_COMMISSION_CALL_PROGRAMMING_ANNOUNCEMENT",
        "authority_scope": "PROGRAMMING_FRAMEWORK",
        "observation_state": "PROGRAMMING_PIPELINE",
        "programme_family": "Innovation Fund / IF26 planned grant calls and auctions / December 2026",
        "adapter_required": "IF26_DECEMBER_2026_CALL_IDENTIFIERS_FT_ORIGINALS_RECONCILE_V1",
        "readback_date_discovery": "2026-11-18",
        "event_date_discovery": "2026-11-17",
        "programmes": ["Innovation Fund / IF26 planned grant calls and auctions / December 2026"],
    }
    for key, expected in expected_if26.items():
        if if26.get(key) != expected:
            fail(f"IF26 programming date/authority/adapter drift: {key}")
    if not {"EU_DIRECT", "BRUSSELS", "INNOVATION_FUND",
            "PROGRAMMING_PIPELINE", "DISCOVERY"}.issubset(
                set(if26.get("source_families") or [])):
        fail("IF26 is programming-only; call family taxonomy missing")
    if "CALL_REGISTRY" in (if26.get("source_families") or []):
        fail("IF26 planned call families conflated with a live call registry")
    for key in ("material_fact_use", "credentials_required", "open_call_authorized",
                "material_fact_publication_authorized"):
        if if26.get(key) is not False:
            fail(f"IF26 planning announcement illegally authorizes OPEN_CALL: {key}")
    forbidden_if26 = {
        "status", "call_status", "open_at", "close_at", "deadline",
        "application_deadline", "budget", "budget_eur", "eligibility",
        "exact_call_identifier", "exact_topic_identifier", "submission_endpoint",
        "fetched_at", "fetched_at_utc", "final_url", "raw_sha256",
        "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
        "last_verified_open",
    }
    if forbidden_if26.intersection(if26):
        fail("IF26 programme announcement fabricated call facts or raw receipt")
    notes = (if26.get("note") or "").lower()
    if not all(token in notes for token in (
            "plans", "3 december 2026", "five", "three grants",
            "two auctions", "up to eur 5.2 billion", "not_captured",
            "no open_call", "immutable")):
        fail("IF26 planned rather than open/five distinct calls distinction lost")
    extracts = set(if26.get("extract") or [])
    if not {
        "three_planned_grants_net_zero_sme_maritime_distinct",
        "two_planned_auctions_hydrogen_industrial_heat_distinct",
        "future_exact_funding_and_tenders_call_identifiers_missing",
        "four_december_information_sessions_not_application_windows",
        "up_to_5_2bn_eur_portfolio_envelope_not_per_call_award",
    }.issubset(extracts):
        fail("IF26 planned grant/auction/Info Day details promoted or conflated")


    # PR_CENTRU_CM_20261112_MARKET_PROGRAMMING_FAIL_CLOSED.
    # One official article reports historical programme-level volumes and only
    # an aspiration for six future launches. It is NOT six executable calls.
    cm = by_id.get("SRC-PRC-20261112-CM-ABSORPTION-SIX-PLANNED-LAUNCHES")
    if cm is None:
        fail("PR Centru 12 November Monitoring Committee market signal missing")
    if (cm.get("url") !=
            "https://www.regiocentru.ro/tinta-de-absorbtie-a-fondurilor-europene-nerambursabile-stabilita-pentru-anul-2026-in-cadrul-programului-regiunea-centru-a-fost-deja-depasita/"
            or cm.get("tier") != "T1"
            or cm.get("event_date_discovery") != "2026-11-12"
            or cm.get("observation_state") != "PROGRAMMING_PIPELINE"
            or cm.get("authority_scope") != "PROGRAMMING_FRAMEWORK"):
        fail("PR Centru CM historic demand or planned launches identity drift")
    cm_program = "PR Centru / November 2026 committee market and planned launches"
    if (cm.get("programmes") != [cm_program] or
            set(programme_domains.get(cm_program, [])) !=
            {"COHESION_CROSS_PROGRAMME", "PROGRAMMING_FUTURE"}):
        fail("PR Centru CM programme market/planning plane not explicit")
    if not {"ROMANIA", "ADR", "MARKET_INTELLIGENCE", "PROGRAMMING_PIPELINE", "DISCOVERY"}.issubset(
            set(cm.get("source_families") or [])):
        fail("PR Centru six planned launches not separated as non-OPEN programming")
    for row in (cm, by_id.get("SRC-PRC-WEEKLY-SUBMITTED-PROJECTS-INDEX-20261117")):
        if row is None:
            fail("PR Centru dated weekly document index discovery missing")
        if any(row.get(key) is not False for key in (
                "material_fact_use", "credentials_required", "open_call_authorized",
                "material_fact_publication_authorized")):
            fail("PR Centru unacquired market source promoted material or OPEN_CALL")
        if any(key in row for key in (
                "status", "call_status", "deadline", "application_deadline",
                "budget", "budget_eur", "eligibility", "submission_endpoint",
                "fetched_at", "final_url", "raw_sha256", "semantic_sha256",
                "parser_version", "run_id", "handoff_sha256", "exact_call_identifier")):
            fail("PR Centru market/index discovery fabricated call fact or raw receipt")
        note = (row.get("note") or "").lower()
        if not all(token in note for token in ("403", "not_captured", "open_call")):
            fail("PR Centru source lost 403/raw-pending/non-OPEN boundary")
    note_cm = cm["note"].lower()
    if not all(token in note_cm for token in (
            "1,837", "1,037", "315m", "six", "33m", "aspiration", "not six identified calls")):
        fail("PR Centru dated factual vs aspirational quantities conflated")
    weekly = by_id["SRC-PRC-WEEKLY-SUBMITTED-PROJECTS-INDEX-20261117"]
    if (weekly.get("url") != "https://www.regiocentru.ro/situatie-proiecte-depuse/"
            or weekly.get("tier") != "T1"
            or weekly.get("readback_date_discovery") != "2026-11-17"
            or weekly.get("latest_indexed_attachment_date_discovery") != "2026-11-09"
            or weekly.get("observation_state") != "SOURCE_INDEX_READBACK_RAW_PENDING"):
        fail("PR Centru week-index date provenance blurred with report date")
    if ("PROGRAMMING_PIPELINE" in (weekly.get("source_families") or []) or
            "dated child documents" not in weekly["note"].lower()):
        fail("PR Centru weekly evidence index conflated with future launch programme")

    # Cluster 5 Commission CCSE is 7+10 PLANNED topic discovery, not a live topic.
    cl5_id = "SRC-EU-EC-CCSE-CL5-2027-01-02-PLANNED-TOPICS"
    cl5 = by_id.get(cl5_id)
    if cl5 is None:
        fail("Cluster 5 future-topic official source missing")
    if cl5.get("url") != "https://research-and-innovation.ec.europa.eu/strategy/strategy-research-and-innovation/europe-world/international-cooperation/regional-dialogues-and-international-organisations/eu-africa-cooperation/partnership-climate-change-and-sustainable-energy-ccse_en":
        fail("Cluster 5 Commission official source URL drift")
    if cl5.get("observation_state") != "PROGRAMMING_PIPELINE":
        fail("Cluster 5 search-index readback wrong state")
    if cl5.get("index_readback_state_discovery") != "OFFICIAL_EC_FUTURE_TOPIC_SCHEDULE_SEARCH_INDEX_READBACK_RAW_PENDING":
        fail("Cluster 5 original-unacquired index readback warning lost")
    if cl5.get("authority_scope") != "PROGRAMMING_FRAMEWORK":
        fail("Cluster 5 programming authority scope expanded")
    if set(programme_domains.get("Horizon Europe / Cluster 5 / 2027-01 and 2027-02 planned topic sets", [])) != {"EU_DIRECT_FUNDING", "PROGRAMMING_FUTURE"}:
        fail("Cluster 5 future-topic programming not registered in data plane")
    if cl5.get("adapter_required") != "HORIZON_CL5_2027_EXACT_TOPIC_FT_CURRENT_GATEWAY_RECONCILE_V1":
        fail("Cluster 5 independent live topic reconciliation missing")
    if not {"EU_DIRECT", "BRUSSELS", "HORIZON_EUROPE", "PROGRAMMING_PIPELINE", "DISCOVERY"}.issubset(set(cl5.get("source_families") or [])):
        fail("Cluster 5 future topic must remain programming intelligence")
    if "CALL_REGISTRY" in (cl5.get("source_families") or []):
        fail("Cluster 5 future topic misclassified live call")
    for key in ("material_fact_use", "credentials_required", "open_call_authorized", "material_fact_publication_authorized"):
        if cl5.get(key) is not False:
            fail("Cluster 5 programming witness illegally authorized material fact: " + key)
    forbidden = {"status", "call_status", "deadline", "budget", "eligibility", "submission_endpoint", "fetched_at", "final_url", "raw_sha256", "parser_version", "run_id", "handoff_sha256", "exact_topic_identifier"}
    if forbidden.intersection(cl5):
        fail("Cluster 5 programme discovery fabricated topic/receipt authority")
    climate = {"HORIZON-CL5-2027-01-D1-" + f"{i:02d}" for i in range(7, 14)}
    energy = {"HORIZON-CL5-2027-02-" + suffix for suffix in (
        "D2-05", "D2-06", "D3-07", "D3-08", "D3-09", "D3-10", "D3-15", "D3-24", "D3-30", "D3-31")}
    topics = cl5.get("planned_topic_identifiers_discovery") or []
    if len(topics) != 17 or set(topics) != (climate | energy):
        fail("Cluster 5 seven-plus-ten exact topic grouping misidentified")
    note_cl5 = (cl5.get("note") or "").lower()
    if not all(token in note_cl5 for token in ("17 november 2026", "3 december 2026", "http 429", "not_captured", "open_call", "immutable")):
        fail("Cluster 5 pending raw/OPEN_CALL warning missing")

    # 16-Nov-2026 Danube MA/JS consultation: a deadline for responding to
    # a TERRITORIAL ANALYSIS survey is never a funding application deadline.
    # Register only the distinct primary article; original PDF/HTML receipts
    # and adoption of the future programme remain review-gated.
    danube_consult_id = "SRC-INTERREG-DANUBE-2028-2034-TERRITORIAL-CONSULT-20261116"
    danube_consult = by_id.get(danube_consult_id)
    if danube_consult is None:
        fail("missing Danube 2028-2034 draft Territorial Analysis consultation")

    def _check_danube_consultation(row):
        exact = {
            "id": danube_consult_id,
            "url": "https://interreg-danube.eu/news/help-shape-the-future-of-the-danube-region",
            "linked_programming_source_id": "SRC-INTERREG-DANUBE-2028-2034",
            "tier": "T1",
            "class": "official_programming_pipeline_consultation",
            "programmes": ["Interreg Danube Region Programme 2028-2034"],
            "programme_family": "Interreg Danube Region Programme 2028-2034",
            "authority_scope": "PROGRAMMING_FRAMEWORK",
            "observation_state": "PROGRAMMING_PIPELINE",
            "event_date_discovery": "2026-11-16",
            "readback_date_discovery": "2026-11-17",
            "consultation_response_deadline_discovery": "2027-01-15",
            "adapter_required": "INTERREG_DANUBE_DRAFT_TERRITORIAL_ANALYSIS_CONSULTATION_RAW_RECONCILE_V1",
        }
        for key, expected in exact.items():
            if row.get(key) != expected:
                fail("Danube future consultation source identity drift: " + key)
        required_families = {"INTERREG", "TRANSNATIONAL", "PROGRAMMING_PIPELINE", "CONSULTATION", "DISCOVERY"}
        if not required_families.issubset(set(row.get("source_families") or [])):
            fail("Danube consultation lost non-call programme source taxonomy")
        if not {"future_programming_consultations", "future_programming_updates"}.issubset(
                set(row.get("extract") or [])):
            fail("Danube consultation missing acquisition-only programming extraction")
        for key in ("material_fact_use", "credentials_required",
                    "open_call_authorized", "material_fact_publication_authorized"):
            if row.get(key) is not False:
                fail("Danube consultation illegally authorized material funding fact: " + key)
        prohibited = {
            "status", "call_status", "deadline", "budget", "budget_eur", "eligibility",
            "submission_endpoint", "exact_call_identifier", "fetched_at",
            "final_url", "raw_sha256", "semantic_sha256", "parser_version",
            "run_id", "handoff_sha256",
        }
        if prohibited.intersection(row):
            fail("Danube consultation fabricated current call or immutable raw receipt")
        note = row.get("note") or ""
        for token in ("16 November 2026", "15 January 2027", "CONSULTATION RESPONSES",
                      "OPEN_CALL", "NOT_CAPTURED", "SURFACEMC"):
            if token not in note:
                fail("Danube consultation lacks provenance/non-call warning: " + token)

    _check_danube_consultation(danube_consult)
    # Negative replay: a future-programme consultation must remain held even
    # if a later operator or source changes one of its sensitive fields.
    for change in (
        {"observation_state": "OPEN_CALL"},
        {"open_call_authorized": True},
        {"material_fact_use": True},
        {"material_fact_publication_authorized": True},
        {"deadline": "2027-01-15"},
        {"run_id": "invented"},
        {"consultation_response_deadline_discovery": "2026-11-17"},
        {"url": "https://example.com/danube-opens"},
    ):
        tampered = dict(danube_consult, **change)
        try:
            _check_danube_consultation(tampered)
        except SystemExit:
            pass
        else:
            fail("Danube consultation negative replay admitted " + repr(change))

    # MPF_INFORMATION_SESSION_DISCOVERY_FAIL_CLOSED
    # A national public body's 17-Nov webinar relay is NOT an exact operator
    # call, submission endpoint, or grant application deadline.
    mpf_id = "SRC-RO-MAI-MPF-INFORMATION-SESSION-20261117"
    mpf = by_id.get(mpf_id)
    if mpf is None:
        fail("17 November MAI/DG HOME MPF official briefing discovery missing")

    def _check_mpf_briefing(row):
        expected = {
            "id": mpf_id,
            "url": "https://fed.mai.gov.ro/11767/11767/",
            "tier": "T2",
            "class": "official_public_body_information_event_relay",
            "authority_class": "T2_NATIONAL_PUBLIC_BODY_RELAY_OF_DG_HOME_MPF_INFORMATION_EVENT",
            "authority_scope": "INFORMATION_EVENT_DISCOVERY_NOT_APPLICATION_AUTHORITY",
            "observation_state": "OFFICIAL_INFORMATION_EVENT_DISCOVERED_RAW_PENDING",
            "event_announcement_date_discovery": "2026-11-17",
            "event_date_discovery": "2026-11-27",
            "event_time_discovery": "13:00-14:30 CET",
            "readback_date_discovery": "2026-11-19",
            "article_edit_date_discovery": "2026-11-18",
            "redirect_target_browser_observed_discovery": "https://fed.mai.gov.ro/11767/facilitatea-pentru-parteneriate-in-domeniul-migratiei-sesiune-informare-ce/",
            "adapter_required": "MPF_2026_ORGANISER_EXACT_CALL_ID_AND_GATEWAY_RECONCILE_V1",
            "programmes": ["EU direct programmes"],
        }
        for field, value in expected.items():
            if row.get(field) != value:
                fail("MAI MPF briefing identity drift: " + field)
        required_families = {"ROMANIA", "MAI", "EU_DIRECT", "BRUSSELS", "INFORMATION_EVENT", "DISCOVERY"}
        if not required_families.issubset(set(row.get("source_families") or [])):
            fail("MAI MPF event lost cross-border discovery family")
        if set(programme_domains.get("EU direct programmes", [])) != {"EU_DIRECT_FUNDING"}:
            fail("MAI MPF event lost explicit EU-direct programme domain")
        for field in ("material_fact_use", "credentials_required", "open_call_authorized",
                      "material_fact_publication_authorized"):
            if row.get(field) is not False:
                fail("MAI MPF information session illegally promoted: " + field)
        forbidden = {
            "status", "call_status", "deadline", "application_deadline",
            "budget", "budget_eur", "eligibility", "submission_endpoint",
            "exact_call_identifier", "fetched_at", "final_url", "raw_sha256",
            "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
        }
        if forbidden.intersection(row):
            fail("MAI MPF briefing fabricated exact call or original raw provenance")
        note = row.get("note", "")
        for token in ("17 November 2026", "27 November 2026",
                      "13:00–14:30 CET", "AMIF", "BMVI", "ISF",
                      "NOT exact call/topic identifiers",
                      "NOT an application deadline", "NOT_CAPTURED",
                      "SURFACEMC", "OPEN_CALL"):
            if token not in note:
                fail("MAI MPF briefing lost stage/authority warning: " + token)

    _check_mpf_briefing(mpf)
    # Negative semantic/provenance replay must fail for every forged promotion.
    for change in (
        {"observation_state": "OPEN_CALL"},
        {"open_call_authorized": True},
        {"material_fact_use": True},
        {"material_fact_publication_authorized": True},
        {"deadline": "2026-11-27"},
        {"eligibility": ["Romanian NGOs"]},
        {"fetched_at": "2026-11-17T19:00:00Z"},
        {"exact_call_identifier": "AMIF"},
        {"event_date_discovery": "2026-11-17"},
        {"url": "https://example.com/fictional-mpf-call"},
    ):
        tampered = dict(mpf, **change)
        try:
            _check_mpf_briefing(tampered)
        except SystemExit:
            pass
        else:
            fail("MAI MPF negative replay admitted " + repr(change))

    # DGCONNECT_CL4_2027_DIGITAL_LAUNCH_FAIL_CLOSED
    # Commission's 17-Nov official programme launch announcement describes 2 calls
    # and 12 digital topics. It does NOT replace an original, live exact-topic
    # Funding & Tenders status and accepting application endpoint.
    cl4_id = "SRC-EU-DGCONNECT-HORIZON-CL4-2027-DIGITAL-LAUNCH-20261117"
    cl4 = by_id.get(cl4_id)
    if cl4 is None:
        fail("DG CONNECT 17 Nov Horizon Cluster 4 digital announcement missing")

    def _check_cl4_news(row):
        fixed = {
            "id": cl4_id,
            "tier": "T1",
            "url": "https://digital-strategy.ec.europa.eu/en/news/commission-launches-over-eu290-million-boost-eu-tech-sovereignty-and-beyond",
            "class": "official_european_commission_dg_connect_horizon_digital_launch_announcement",
            "authority_class": "T1_OFFICIAL_EUROPEAN_COMMISSION_DG_CONNECT_PROGRAMME_ANNOUNCEMENT",
            "authority_scope": "PROGRAMME_LAUNCH_ANNOUNCEMENT_NOT_EXACT_TOPIC_GATEWAY",
            "observation_state": "OFFICIAL_COMMISSION_LAUNCH_ANNOUNCEMENT_RAW_PENDING",
            "event_date_discovery": "2026-11-17",
            "readback_date_discovery": "2026-11-18",
            "source_last_updated_date_discovery": "2026-11-18",
            "programmes": ["EU direct programmes"],
            "announced_call_count_discovery": 2,
            "announced_topic_count_discovery": 12,
            "adapter_required": "HORIZON_CL4_DIGITAL_2027_DG_CONNECT_NEWS_EXACT_FT_TOPIC_RAW_RECONCILE_V1",
        }
        for key, expected in fixed.items():
            if row.get(key) != expected:
                fail("DG CONNECT launch discovery identity/status drift: " + key)
        if not {"EU_DIRECT", "BRUSSELS", "HORIZON_EUROPE",
                "CALL_LAUNCH_ANNOUNCEMENT", "DISCOVERY"}.issubset(
                set(row.get("source_families") or [])):
            fail("DG CONNECT digital announcement incorrectly classified")
        if "PROGRAMMING_PIPELINE" in (row.get("source_families") or []):
            fail("DG CONNECT official launch wrongly rewound to pre-announcement")
        if set(programme_domains.get("EU direct programmes", [])) != {"EU_DIRECT_FUNDING"}:
            fail("DG CONNECT EU-direct programme plane missing")
        extracts = set(row.get("extract") or [])
        if not {
            "commission_17_november_2026_digital_launch_announcement_two_calls_12_topics",
            "announced_297m_eur_total_envelope_not_topic_or_applicant_budget",
            "announced_18_march_2027_programme_level_end_not_exact_topic_submission_deadline",
            "live_ft_topic_status_and_exact_application_endpoint_independently_required",
            "original_dgconnect_and_ft_topic_receipts_not_yet_acquired",
        }.issubset(extracts):
            fail("DG CONNECT launch announcement count/envelope/deadline distinctions lost")
        for key in ("material_fact_use", "credentials_required",
                    "open_call_authorized", "material_fact_publication_authorized"):
            if row.get(key) is not False:
                fail("DG CONNECT unacquired launch promoted material status: " + key)
        forbidden = {
            "status", "call_status", "deadline", "application_deadline",
            "budget", "budget_eur", "eligibility", "exact_call_identifier",
            "exact_topic_identifier", "submission_endpoint", "fetched_at",
            "final_url", "raw_sha256", "semantic_sha256", "parser_version",
            "run_id", "handoff_sha256",
        }
        if forbidden.intersection(row):
            fail("DG CONNECT announcement fabricated exact-topic or immutable receipt")
        note = row.get("note") or ""
        for token in ("17 November 2026", "12 topics", "EUR 297 million",
                      "18 March 2027", "Forthcoming", "NOT_CAPTURED",
                      "SURFACEMC", "OPEN_CALL", "exact current Funding & Tenders"):
            if token not in note:
                fail("DG CONNECT announcement lost provenance/semantic hold: " + token)

    _check_cl4_news(cl4)
    # Adversarial replay: new launched programme != confirmed exact OPEN_CALL.
    for change in (
        {"observation_state": "OPEN_CALL"},
        {"open_call_authorized": True},
        {"material_fact_use": True},
        {"material_fact_publication_authorized": True},
        {"announced_topic_count_discovery": 11},
        {"readback_date_discovery": "2026-11-17"},
        {"source_last_updated_date_discovery": "2026-11-17"},
        {"deadline": "2027-03-18"},
        {"budget_eur": 297000000},
        {"eligibility": ["all SMEs"]},
        {"exact_topic_identifier": "HORIZON-CL4-2027-04-ASSUMED"},
        {"submission_endpoint": "https://example.com/submit"},
        {"fetched_at": "2026-11-17T20:00:00Z"},
        {"url": "https://example.com/unverified-news"},
    ):
        tampered = dict(cl4, **change)
        try:
            _check_cl4_news(tampered)
        except SystemExit:
            pass
        else:
            fail("DG CONNECT launch negative replay illegally admitted " + repr(change))

    # EIC_2027_ADOPTED_WP_PIPELINE_FAIL_CLOSED
    # An adopted annual Work Programme and an Info Day are not equivalent to
    # accepting individual 2027 Funding & Tenders submission endpoints.
    eic27_id = "SRC-EU-EIC-WP-2027-ADOPTED-20261105"
    eic27 = by_id.get(eic27_id)
    if eic27 is None:
        fail("EIC 2027 adopted work-programme programme-intelligence source missing")

    def _check_eic27(row):
        expected = {
            "id": eic27_id,
            "tier": "T1",
            "url": "https://eic.ec.europa.eu/eic-funding-opportunities/eic-funding-opportunities-2027_en",
            "linked_official_info_event_url_discovery": "https://eic.ec.europa.eu/events/online-information-day-eic-funding-opportunities-2027-2026-11-19_en",
            "class": "official_eic_adopted_2027_work_programme_pipeline",
            "programmes": ["European Innovation Council / adopted Work Programme 2027"],
            "programme_family": "European Innovation Council",
            "authority_class": "T1_OFFICIAL_EIC_EISMEA_ADOPTED_WORK_PROGRAMME",
            "authority_scope": "PROGRAMME_FRAMEWORK",
            "observation_state": "PROGRAMMING_PIPELINE",
            "event_date_discovery": "2026-11-05",
            "readback_date_discovery": "2026-11-18",
            "adapter_required": "EIC_2027_WP_PDF_AND_EXACT_FT_TOPIC_RECONCILE_V1",
        }
        for key, value in expected.items():
            if row.get(key) != value:
                fail("EIC 2027 WP identity/stage drift: " + key)
        if not {"EU_DIRECT", "BRUSSELS", "EIC", "PROGRAMMING_PIPELINE",
                "DISCOVERY"}.issubset(set(row.get("source_families") or [])):
            fail("EIC 2027 source taxonomy must remain programme planning")
        extracts = set(row.get("extract") or [])
        if not {
            "adopted_eic_2027_work_programme_5_november_2026",
            "over_1_8bn_eur_eic_2027_programme_envelope_not_individual_call_budget",
            "19_november_2026_eic_work_programme_info_day_not_funding_application",
            "18_november_2026_0930_cet_info_day_registration_cutoff_not_funding_deadline",
            "current_eic_2027_pdf_original_hash_not_yet_acquired",
            "individual_2027_ft_topic_identifiers_and_live_endpoints_unverified",
        }.issubset(extracts):
            fail("EIC 2027 work-programme or info-day source distinctions lost")
        for key in ("material_fact_use", "credentials_required",
                    "open_call_authorized", "material_fact_publication_authorized"):
            if row.get(key) is not False:
                fail("EIC 2027 programme observation promoted: " + key)
        if any(key in row for key in (
            "status", "call_status", "deadline", "submission_deadline",
            "budget", "budget_eur", "eligibility", "exact_call_identifier",
            "exact_topic_identifier", "submission_endpoint", "fetched_at",
            "final_url", "raw_sha256", "semantic_sha256", "parser_version",
            "run_id", "handoff_sha256",
        )):
            fail("EIC 2027 source invented individual funding terms or immutable receipt")
        note = row.get("note") or ""
        for token in ("ADOPTED", "over EUR 1.8 billion", "19 November 2026",
                      "18 November 2026 09:30 CET", "NOT_CAPTURED",
                      "NOT_RECONCILED", "SURFACEMC", "OPEN_CALL"):
            if token not in note:
                fail("EIC 2027 source missing hard fail-closed warning: " + token)

    if set(programme_domains.get("European Innovation Council / adopted Work Programme 2027", [])) != {"EU_DIRECT_FUNDING", "PROGRAMMING_FUTURE"}:
        fail("EIC 2027 work-programme must stay in the future-programming data plane")
    _check_eic27(eic27)
    for changed in (
        {"observation_state": "OPEN_CALL"},
        {"open_call_authorized": True},
        {"material_fact_use": True},
        {"material_fact_publication_authorized": True},
        {"budget_eur": 1800000000},
        {"deadline": "2026-11-18"},
        {"submission_deadline": "2026-11-19"},
        {"eligibility": ["all EU SMEs"]},
        {"exact_topic_identifier": "EIC-2027-ASSUMED"},
        {"submission_endpoint": "https://example.com/fake-eic-submit"},
        {"raw_sha256": "0" * 64},
        {"fetched_at": "2026-11-18T03:00:00Z"},
        {"linked_official_info_event_url_discovery": "https://example.com/unverified-eic-event"},
    ):
        altered = dict(eic27, **changed)
        try:
            _check_eic27(altered)
        except SystemExit:
            pass
        else:
            fail("EIC 2027 negative mutation admitted " + repr(changed))


    # ERASMUS_EUR_UNIV_2027_ANNOUNCEMENT_FAIL_CLOSED
    # Official Erasmus+ landing says OPEN, but exact-topic F&T API and the
    # accepting live application route have not been acquired as immutable raws.
    erasmus_id = "SRC-EU-ERASMUS-EUR-UNIV-2027-ANNOUNCEMENT"
    erasmus = by_id.get(erasmus_id)
    if not erasmus:
        fail("Erasmus 2027 European Universities official discovery missing")

    def _check_erasmus(row):
        expected = {
            "id": erasmus_id,
            "tier": "T1",
            "url": "https://education.ec.europa.eu/education-levels/higher-education/european-universities-initiative/funding",
            "linked_official_erasmus_listing_url_discovery": "https://erasmus-plus.ec.europa.eu/funding-opportunities/european-universities",
            "linked_official_funding_tenders_topic_url_discovery": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/ERASMUS-EDU-2027-EUR-UNIV",
            "topic_identifier_discovery": "ERASMUS-EDU-2027-EUR-UNIV",
            "programme_family": "Erasmus+ / European Universities / 2027",
            "programmes": ["EU direct programmes"],
            "authority_class": "T1_OFFICIAL_EUROPEAN_COMMISSION_DG_EAC_ERASMUS_ANNOUNCEMENT",
            "authority_scope": "EXACT_TOPIC_LINKED_PROGRAMME_ANNOUNCEMENT_NOT_LIVE_TOPIC_API",
            "observation_state": "OFFICIAL_CALL_ANNOUNCEMENT_EXACT_TOPIC_DISCOVERED_RAW_PENDING",
            "landing_last_updated_date_discovery": "2026-11-12",
            "readback_date_discovery": "2026-11-18",
            "adapter_required": "ERASMUS_EUR_UNIV_2027_OFFICIAL_RAW_FT_TOPIC_APPLICATION_RECONCILE_V1",
        }
        for key, value in expected.items():
            if row.get(key) != value:
                fail("Erasmus 2027 exact-source identity/authority drift: " + key)
        if not {"EU_DIRECT", "BRUSSELS", "ERASMUS_PLUS",
                "CALL_REGISTRY", "DISCOVERY"}.issubset(
                set(row.get("source_families") or [])):
            fail("Erasmus 2027 incorrectly classified")
        if "PROGRAMMING_PIPELINE" in (row.get("source_families") or []):
            fail("Erasmus 2027 published announcement misclassified as MFF pipeline")
        if set(programme_domains.get("EU direct programmes", [])) != {"EU_DIRECT_FUNDING"}:
            fail("Erasmus 2027 programme data plane not isolated")
        extracts = set(row.get("extract") or [])
        if not {
            "commission_european_universities_2027_open_wording_as_announcement_only",
            "official_erasmus_reference_erasmus_edu_2027_eur_univ",
            "announced_4_march_2027_1700_cet_deadline_NOT_exact_live_topic_receipt",
            "17_november_2026_info_session_not_submission_deadline",
            "2021_2027_european_universities_programme_envelope_not_2027_topic_budget",
            "ft_topic_page_js_shell_no_current_machine_readable_topic_status_or_application_endpoint",
        }.issubset(extracts):
            fail("Erasmus 2027 announced date/budget conflated with current topic facts")
        for key in ("material_fact_use", "credentials_required",
                    "open_call_authorized", "material_fact_publication_authorized"):
            if row.get(key) is not False:
                fail("Erasmus 2027 unverified source authorized material fact: " + key)
        if {"status", "call_status", "deadline", "application_deadline",
            "budget", "budget_eur", "eligibility", "exact_call_identifier",
            "exact_topic_identifier", "submission_endpoint", "open_at", "close_at",
            "final_url", "fetched_at", "raw_sha256", "semantic_sha256",
            "parser_version", "run_id", "handoff_sha256", "last_verified_open"
            }.intersection(row):
            fail("Erasmus 2027 invented raw receipt or material OPEN fact")
        note = row.get("note") or ""
        for token in ("12 November 2026", "4 March 2027 17:00 CET",
                      "ERASMUS-EDU-2027-EUR-UNIV", "Funding & Tenders",
                      "NOT_CAPTURED", "SURFACEMC", "OPEN_CALL",
                      "LKG", "application endpoint"):
            if token not in note:
                fail("Erasmus 2027 source missing evidence boundary: " + token)

    _check_erasmus(erasmus)
    # Adversarial replay: never let a programme announcement become a current
    # call without fresh exact-topic original and application-receipt review.
    for change in (
        {"observation_state": "OPEN_CALL"},
        {"open_call_authorized": True},
        {"material_fact_use": True},
        {"material_fact_publication_authorized": True},
        {"deadline": "2027-03-04"},
        {"budget_eur": 1200000000},
        {"eligibility": ["all Romanian organisations"]},
        {"exact_topic_identifier": "ERASMUS-EDU-2027-EUR-UNIV"},
        {"submission_endpoint": "https://example.com/apply"},
        {"raw_sha256": "0" * 64},
        {"fetched_at": "2026-11-18T04:30:00Z"},
        {"linked_official_funding_tenders_topic_url_discovery": "https://example.com/topic"},
        {"topic_identifier_discovery": "ERASMUS-EDU-2026-EUR-UNIV"},
        {"readback_date_discovery": "2026-11-19"},
    ):
        tampered = dict(erasmus, **change)
        try:
            _check_erasmus(tampered)
        except SystemExit:
            pass
        else:
            fail("Erasmus 2027 adversarial mutation admitted " + repr(change))


    # BMVI_EES_2026_47_MEMBER_STATE_ONLY_NEGATIVE
    # MAI hosts a signed DG HOME Member State-only invitation, NOT a
    # Romanian public beneficiary call; discover both sources without
    # inventing a current status, deadline, budget or live submission.
    bmvi_47_index_id = "SRC-MAI-IMFV-BMVI-EES-2026-47-INDEX"
    bmvi_47_pdf_id = "SRC-EC-DG-HOME-BMVI-EES-2026-47-PRIMARY"

    def _check_bmvi_47(row, source_id):
        index = source_id == bmvi_47_index_id
        expected = {
            "id": source_id,
            "tier": "T1",
            "url": (
                "https://fed.mai.gov.ro/fed-2021-2027/documentatii-as-2021-2027/actiuni-specifice-imfv-2021-2027/"
                if index else
                "https://fed.mai.gov.ro/wp-content/uploads/2026/11/Call-for-interest_BMVI_2026_SA_1.5.3_EES.pdf"
            ),
            "commission_note_identifier": "HOME-Funds/2026/47",
            "call_identifier_discovery": "BMVI/2026/SA/1.5.3",
            "programme_family": "BMVI 2021-2027 / specific actions / automated EES registration at land and sea borders",
            "programmes": ["IMFV"],
            "readback_date_discovery": "2026-11-19",
            "adapter_required": "BMVI_EES_2026_47_MEMBER_STATE_PRIMARY_AND_MAI_RAW_RECONCILE_V1",
            "observation_state": (
                "MAI_DG_HOME_EES_PRIMARY_LINK_DISCOVERED_RAW_PENDING" if index
                else "EC_DG_HOME_SIGNED_EES_2026_47_PDF_READBACK_RAW_PENDING"
            ),
            "authority_scope": (
                "EC_SPECIFIC_ACTION_DOCUMENT_INDEX_DISCOVERY_NOT_ROMANIAN_PUBLIC_APPLICANT_CALL"
                if index else
                "PRIMARY_SIGNED_MEMBER_STATE_SPECIFIC_ACTION_NOTE_DISCOVERY_NOT_PUBLIC_BENEFICIARY_CALL"
            ),
            "authority_class": (
                "T1_MANAGING_AUTHORITY_AFACERI_INTERNE"
                if index else
                "T1_OFFICIAL_EC_DG_HOME_SIGNED_PRIMARY_NOTE_HOSTED_MAI"
            ),
            ("linked_primary_source_id" if index else "paired_official_source_id"):
                bmvi_47_pdf_id if index else bmvi_47_index_id,
        }
        for field, expected_value in expected.items():
            if row.get(field) != expected_value:
                fail(f"BMVI EES source identity/authority drift: {source_id} / {field}")
        if not {"ROMANIA", "MAI", "IMFV", "CALL_REGISTRY", "DISCOVERY"}.issubset(
                set(row.get("source_families") or [])):
            fail("BMVI EES discovery missing exact source family")
        if not index and not {"EU_DIRECT", "BRUSSELS"}.issubset(
                set(row.get("source_families") or [])):
            fail("DG HOME signed primary must be EU DIRECT primary discovery")
        if not index and row.get("document_signed_date_discovery") != "2026-10-28":
            fail("DG HOME primary signature must not be mistaken for MAI readback date")
        for field in ("material_fact_use", "credentials_required",
                      "open_call_authorized", "material_fact_publication_authorized"):
            if row.get(field) is not False:
                fail("BMVI EES member-state document authorized a call: " + field)
        forbidden = {
            "status", "call_status", "open_at", "close_at", "deadline",
            "application_deadline", "budget", "budget_eur", "eligibility",
            "exact_topic_identifier", "submission_endpoint",
            "fetched_at", "final_url", "raw_sha256", "semantic_sha256",
            "parser_version", "run_id", "handoff_sha256",
        }
        if forbidden.intersection(row):
            fail("BMVI EES doc fabricated canonical facts/provenance")
        note = (row.get("note") or "").upper()
        for marker in ("MEMBER STATE", "NOT_CAPTURED", "OPEN_CALL",
                       "SURFACEMC", "NO", "DISTRIBUTION"):
            if marker not in note:
                fail("BMVI EES non-promotion warning missing: " + marker)

    for row_id in (bmvi_47_index_id, bmvi_47_pdf_id):
        row = by_id.get(row_id)
        if row is None:
            fail("missing exact BMVI EES national+Commission source pair: " + row_id)
        _check_bmvi_47(row, row_id)

    for mutated_field in (
        {"open_call_authorized": True},
        {"material_fact_use": True},
        {"material_fact_publication_authorized": True},
        {"call_status": "OPEN_CALL"},
        {"observation_state": "OPEN_CALL"},
        {"deadline": "2027-01-15"},
        {"budget_eur": 37000000},
        {"eligibility": ["Romanian companies"]},
        {"submission_endpoint": "https://example.com/submit"},
        {"raw_sha256": "0" * 64},
        {"fetched_at": "2026-11-19T04:26:00Z"},
        {"parser_version": "unknown"},
        {"call_identifier_discovery": "BMVI/2026/SA/1.5.2"},
        {"linked_primary_source_id": "SRC-UNVERIFIED"},
    ):
        row = dict(by_id[bmvi_47_index_id], **mutated_field)
        try:
            _check_bmvi_47(row, bmvi_47_index_id)
        except SystemExit:
            pass
        else:
            fail("BMVI EES index negative mutation admitted: " + repr(mutated_field))
    for change in (
        {"open_call_authorized": True},
        {"material_fact_use": True},
        {"deadline": "2027-01-15"},
        {"budget_eur": 37000000},
        {"submission_endpoint": "mailto:assumed@example.com"},
        {"raw_sha256": "0" * 64},
        {"document_signed_date_discovery": "2026-11-19"},
        {"paired_official_source_id": "SRC-UNVERIFIED"},
    ):
        row = dict(by_id[bmvi_47_pdf_id], **change)
        try:
            _check_bmvi_47(row, bmvi_47_pdf_id)
        except SystemExit:
            pass
        else:
            fail("BMVI EES PDF negative mutation admitted: " + repr(change))


    # ERC_POC_2027_STRICT_ENDPOINT_HOLD: official scheme page can show
    # an "Open call" label while the exact Funding & Tenders accepting
    # endpoint has NOT been acquired. Keep the call-level market signal
    # without authorizing OPEN_CALL or a material funding fact.
    erc_id = "SRC-EU-ERC-POC-2027-OPEN-LABEL-20261119"
    erc = by_id.get(erc_id)
    if erc is None:
        fail("missing official ERC PoC 2027 source discovery")

    def _check_erc_poc_2027(row):
        expected = {
            "id": erc_id,
            "tier": "T1",
            "url": "https://erc.europa.eu/apply-grant/proof-concept",
            "owner": "European Research Council / European Commission",
            "readback_date_discovery": "2026-11-19",
            "funding_tenders_query_key_discovery": "ERC-2027-POC",
            "authority_class": "T1_OFFICIAL_ERC_COMMISSION",
            "authority_scope": "OFFICIAL_SCHEME_PAGE_OPEN_LABEL_NOT_EXACT_LIVE_TOPIC_SUBMISSION_ENDPOINT_PROOF",
            "observation_state": "ERC_POC_2027_OPEN_LABEL_DISCOVERED_EXACT_ENDPOINT_RAW_PENDING",
            "adapter_required": "ERC_POC_2027_EXACT_FT_TOPIC_SURFACEMC_RECONCILE_V1",
            "programme_family": "Horizon Europe / ERC Proof of Concept 2027",
        }
        for key, value in expected.items():
            if row.get(key) != value:
                fail("ERC PoC 2027 identity/scope drift: " + key)
        if not {"EU_DIRECT", "BRUSSELS", "HORIZON_EUROPE", "ERC",
                "CALL_REGISTRY", "DISCOVERY"}.issubset(set(row.get("source_families") or [])):
            fail("ERC PoC 2027 must remain EU_DIRECT discovery")
        if not {"current_exact_topic_identifier_and_accepting_submission_endpoint_unverified",
                "NO_OPEN_CALL"}.issubset(set(row.get("extract") or [])):
            fail("ERC PoC 2027 missing strict endpoint hold")
        for key in ("material_fact_use", "credentials_required",
                    "open_call_authorized", "material_fact_publication_authorized"):
            if row.get(key) is not False:
                fail("ERC PoC 2027 unauthorized material/open promotion: " + key)
        forbidden = {
            "status", "call_status", "deadline", "application_deadline",
            "budget", "budget_eur", "eligibility", "exact_call_identifier",
            "exact_topic_identifier", "submission_endpoint", "open_at",
            "close_at", "final_url", "fetched_at", "raw_sha256",
            "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
            "last_verified_open",
        }
        if forbidden.intersection(row):
            fail("ERC PoC 2027 fabricated call fact or raw receipt")
        note = str(row.get("note") or "").upper()
        for marker in ("12 NOVEMBER 2026", "10 MARCH", "16 SEPTEMBER",
                       "NOT_CAPTURED", "SURFACEMC", "EXACT", "OPEN_CALL",
                       "LKG", "NO DISTRIBUTION"):
            if marker not in note:
                fail("ERC PoC 2027 missing provenance/authority warning: " + marker)

    _check_erc_poc_2027(erc)
    for mutation in (
        {"tier": "T3"},
        {"url": "https://example.com/erc"},
        {"authority_class": "T3_DISCOVERY"},
        {"authority_scope": "CURRENT_OPEN_CALL"},
        {"observation_state": "OPEN_CALL"},
        {"funding_tenders_query_key_discovery": "ERC-2026-POC"},
        {"adapter_required": "NO_ADAPTER"},
        {"readback_date_discovery": "2026-11-12"},
        {"source_families": ["EU_DIRECT", "CALL_REGISTRY"]},
        {"extract": ["NO_OPEN_CALL"]},
        {"material_fact_use": True},
        {"credentials_required": True},
        {"open_call_authorized": True},
        {"material_fact_publication_authorized": True},
        {"status": "OPEN"},
        {"call_status": "OPEN_CALL"},
        {"deadline": "2027-03-10"},
        {"budget_eur": 150000},
        {"eligibility": ["all universities"]},
        {"exact_topic_identifier": "ERC-2027-POC"},
        {"submission_endpoint": "https://example.com/apply"},
        {"fetched_at": "2026-11-19T21:28:00Z"},
        {"raw_sha256": "0" * 64},
        {"semantic_sha256": "0" * 64},
        {"parser_version": "unverified"},
        {"run_id": "fabricated"},
        {"handoff_sha256": "0" * 64},
        {"note": "Open call, all confirmed"},
    ):
        try:
            _check_erc_poc_2027(dict(erc, **mutation))
        except SystemExit:
            pass
        else:
            fail("ERC PoC 2027 negative mutation admitted " + repr(mutation))

    print(
        "PASS external source expansion contract: "
        f"{len(REQUIRED)} roots; {len(DIRECT_PROGRAMME_FAMILIES)} direct programme families; "
        f"{len(pipeline)} programming-pipeline roots; all programmes data-plane classified; "
        "F&T/programme gateways/call indexes/guides, EEA Civil Society and Black Sea Basin indexes fail-closed behind dedicated adapters; "
        "MFF 2028-2034 remains proposal-only programming intelligence"
    )


if __name__ == "__main__":
    main()