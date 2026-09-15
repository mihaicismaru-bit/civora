#!/usr/bin/env python3
from eea_civil_society_fund_reconcile_common import main_for, parser_version, reconcile as _reconcile, schema, validate_receipt as _validate
SCHEMA = schema("2")
PARSER_VERSION = parser_version("2")

def reconcile(current, previous=None):
    return _reconcile("2", current, previous)

def validate_receipt(receipt, *, current, previous=None):
    return _validate("2", receipt, current=current, previous=previous)

def main() -> int:
    return main_for("2")

if __name__ == "__main__":
    raise SystemExit(main())
