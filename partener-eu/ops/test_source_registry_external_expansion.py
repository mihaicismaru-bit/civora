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

    print(
        "PASS external source expansion contract: "
        f"{len(REQUIRED)} roots; {len(DIRECT_PROGRAMME_FAMILIES)} direct programme families; "
        f"{len(pipeline)} programming-pipeline roots; all programmes data-plane classified; "
        "F&T/programme gateways/call indexes/guides, EEA Civil Society and Black Sea Basin indexes fail-closed behind dedicated adapters; "
        "MFF 2028-2034 remains proposal-only programming intelligence"
    )


if __name__ == "__main__":
    main()