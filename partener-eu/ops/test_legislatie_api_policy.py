#!/usr/bin/env python3
"""Regression guard for Portal Legislativ SOAP adapter token handling."""
import json
import pathlib
import sys

PARTENER = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PARTENER / "ingest"))
import legislatie_api_probe as adapter  # noqa: E402

sample = b'''<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
<s:Body><GetTokenResponse xmlns="http://tempuri.org/"><GetTokenResult>temporary-secret-value-1234567890</GetTokenResult></GetTokenResponse></s:Body>
</s:Envelope>'''
evidence = adapter.token_evidence_from_xml(sample)
assert evidence["token_received"] is True
assert evidence["token_length"] > 0
assert evidence["token_sha256"]
serialized = json.dumps(evidence)
assert "temporary-secret-value-1234567890" not in serialized
assert "SOAP_BODY" in adapter.__dict__
assert b"GetToken" in adapter.SOAP_BODY
print("PASS Portal Legislativ API token-handling regression")
