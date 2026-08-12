#!/usr/bin/env python3
"""Regression guard for AFIR authentication boundaries."""
import pathlib
import sys

PARTENER = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PARTENER / "ingest"))
import afir_ingest  # noqa: E402

assert afir_ingest.norm(
    "https://www.afir.ro/umbraco/surface/authentication/LogIn?redirectUrl=%2Ffinantare%2F"
) is None
assert afir_ingest.is_auth_dependency(
    "https://www.afir.ro/finantare/",
    "https://www.afir.ro/umbraco/surface/authentication/LogIn?redirectUrl=%2Ffinantare%2F",
    "We can't sign you in",
    "",
)
assert not afir_ingest.is_auth_dependency(
    "https://www.afir.ro/info-la-zi/",
    "https://www.afir.ro/info-la-zi/",
    "Informații AFIR",
    "Comunicate și informații publice",
)
print("PASS AFIR auth-boundary regression")
