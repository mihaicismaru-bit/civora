#!/usr/bin/env python3
# Import exact wrapper first so its bounded official Call #3 authority binding
# is active in the shared validation module in this subprocess as well.
import eea_civil_society_fund_call3_exact  # noqa: F401
from eea_civil_society_fund_reconcile_common import main_for, parser_version, reconcile as _reconcile, schema, validate_receipt as _validate
SCHEMA = schema("3")
PARSER_VERSION = parser_version("3")

def reconcile(current, previous=None):
    return _reconcile("3", current, previous)

def validate_receipt(receipt, *, current, previous=None):
    return _validate("3", receipt, current=current, previous=previous)

def main() -> int:
    return main_for("3")

if __name__ == "__main__":
    raise SystemExit(main())
