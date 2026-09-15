#!/usr/bin/env python3
import eea_civil_society_fund_exact_common as _common

# Official RO index binds Call #3 to this exact current detail path.
_common.SPECS["3"] = _common.CallSpec(
    call_id="3",
    slug="call-3-community-driven-projects-human-rights-and-social-justice",
    title_ro="Apel #3 Proiecte comunitare pentru drepturile omului și justiție socială",
    title_en="Call #3 Community-Driven Projects for Human Rights and Social Justice",
    budget="EUR 6,300,000",
    grant_min="EUR 200,001",
    grant_max="EUR 350,000",
)

from eea_civil_society_fund_exact_common import (
    AUTHORITY_CLASS, CALL_IDENTIFIER_KIND, INDEX_URL, MATERIAL_FLAGS, OBSERVATION_STATE,
    PROGRAMME_FAMILY, PROGRAMME_ID, SOURCE_FAMILY, canonical_json, collect_exact as _collect,
    get_spec, main_for, sha256_json, validate_evidence as _validate,
)
SPEC = get_spec("3")
SCHEMA = SPEC.schema
PARSER_VERSION = SPEC.parser_version
OFFICIAL_CALL_IDENTIFIER = SPEC.call_id
EXACT_URL = SPEC.exact_url
EXPECTED_SLUG = SPEC.slug
EXPECTED_TITLE_MARKERS = (SPEC.title_ro, SPEC.title_en)

def collect_exact(**kwargs):
    return _collect("3", **kwargs)

def validate_evidence(evidence):
    return _validate("3", evidence)

def main() -> int:
    return main_for("3")

if __name__ == "__main__":
    raise SystemExit(main())
