#!/usr/bin/env python3
from eea_civil_society_fund_exact_common import (
    AUTHORITY_CLASS, CALL_IDENTIFIER_KIND, INDEX_URL, MATERIAL_FLAGS, OBSERVATION_STATE,
    PROGRAMME_FAMILY, PROGRAMME_ID, SOURCE_FAMILY, canonical_json, collect_exact as _collect,
    get_spec, main_for, sha256_json, validate_evidence as _validate,
)
SPEC = get_spec("2")
SCHEMA = SPEC.schema
PARSER_VERSION = SPEC.parser_version
OFFICIAL_CALL_IDENTIFIER = SPEC.call_id
EXACT_URL = SPEC.exact_url
EXPECTED_SLUG = SPEC.slug
EXPECTED_TITLE_MARKERS = (SPEC.title_ro, SPEC.title_en)

def collect_exact(**kwargs):
    return _collect("2", **kwargs)

def validate_evidence(evidence):
    return _validate("2", evidence)

def main() -> int:
    return main_for("2")

if __name__ == "__main__":
    raise SystemExit(main())
