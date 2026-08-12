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

dependency = afir_ingest.auth_link_dependency(
    "/umbraco/surface/authentication/LogIn?redirectUrl=%2Ffinantare%2F",
    "https://www.afir.ro/info-la-zi/",
)
assert dependency and dependency["status"] == "AUTH_OR_ACCESS_DEPENDENT"
assert dependency["materialFactAction"] == "NONE"
print("PASS AFIR auth-boundary regression")
