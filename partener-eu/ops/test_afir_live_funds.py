#!/usr/bin/env python3
"""Regression tests for structured AFIR live-funds extraction."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "partener-eu" / "ingest" / "build_afir_live_funds.py"

FIXTURE = """<!doctype html><html><body>
<table>
<tr><th>Intervenția</th><th>Sector</th><th>Alocare sesiune/sector</th><th>Dată și oră lansare sesiune</th>
<th>Dată și oră închidere sesiune</th><th>Plafon depunere proiecte</th><th>Valoarea proiectelor depuse</th>
<th>Număr proiecte depuse</th><th>Fonduri disponibile</th></tr>
<tr><td colspan="9">Investiții în fermele de mici dimensiuni</td></tr>
<tr><td>DR-14</td><td><strong>Componenta LEGUMICULTURĂ</strong></td><td>30.000.000,00 EUR</td>
<td>01.09.2026 09:00:00</td><td>31.10.2026 15:59:59</td><td>45.000.000,00 EUR</td>
<td>143.545</td><td>3</td><td>44.856.455,00 EUR</td></tr>
<tr><td>DR-14</td><td>Componenta SECTOR ZOOTEHNIC</td><td>30.000.000,00 EUR</td>
<td>01.09.2026 09:00:00</td><td>31.10.2026 15:59:59</td><td>45.000.000,00 EUR</td>
<td>92.500</td><td>2</td><td>44.907.500,00 EUR</td></tr>
<tr><td>DR-18</td><td>Investiții în floricultură, plante medicinale și aromatice</td><td>5.000.000,00 EUR</td>
<td>01.09.2026 09:00:00</td><td>31.10.2026 15:59:59</td><td>7.500.000,00 EUR</td>
<td>190.863</td><td>2</td><td>7.309.137,00 EUR</td></tr>
</table></body></html>"""


def load_builder_module():
    sys.path.insert(0, str(BUILDER.parent))
    spec = importlib.util.spec_from_file_location("partener_afir_live_funds_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    fixture_bytes = FIXTURE.encode("utf-8")
    fingerprint = hashlib.sha256(fixture_bytes).hexdigest()
    corpus = {
        "schemaVersion": 2,
        "source": "AFIR",
        "generatedAt": "2026-09-22T16:29:38+00:00",
        "items": [
            {
                "url": "https://www.afir.ro/finantare/contor-fonduri-disponibile/",
                "title": "Contor fonduri disponibile",
                "sha256": fingerprint,
                "observedAt": "2026-09-22T16:29:26+00:00",
                "materialChangeCandidate": True,
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        corpus_path = tmp / "corpus.json"
        fixture_path = tmp / "counter.html"
        output_path = tmp / "snapshot.json"
        corpus_path.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
        fixture_path.write_text(FIXTURE, encoding="utf-8")
        command = [
            sys.executable, str(BUILDER),
            "--corpus", str(corpus_path),
            "--output", str(output_path),
            "--html-fixture", str(fixture_path),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        first = output_path.read_bytes()
        payload = json.loads(first)
        subprocess.run(command, check=True, capture_output=True, text=True)
        assert first == output_path.read_bytes(), "snapshot must be byte-deterministic for identical evidence"

        drifted = dict(corpus)
        drifted["items"] = [dict(corpus["items"][0], sha256="0" * 64)]
        corpus_path.write_text(json.dumps(drifted, ensure_ascii=False), encoding="utf-8")
        drift = subprocess.run(command, check=False, capture_output=True, text=True)
        drift_payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert drift.returncode == 2
        assert drift_payload["status"] == "DEGRADED_SOURCE_DRIFT"
        assert drift_payload["policy"]["publishableDedicatedSnapshot"] is False

        # Re-establish a validated PASS snapshot, then reproduce the production
        # TLS/transport outage. The LKG must remain byte-identical and the
        # builder must return the workflow's accepted fail-closed exit code 2.
        corpus_path.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
        subprocess.run(command, check=True, capture_output=True, text=True)
        lkg_bytes = output_path.read_bytes()
        builder = load_builder_module()
        original_fetch = builder.fetch
        try:
            builder.fetch = lambda _url: {
                "ok": False,
                "status": None,
                "error": "URLError: <urlopen error _ssl.c:983: The handshake operation timed out>",
            }
            transport_status = builder.run(corpus_path, output_path, None)
            assert transport_status == 2
            assert output_path.read_bytes() == lkg_bytes, "transport outage must preserve LKG byte-for-byte"
            preserved = json.loads(output_path.read_text(encoding="utf-8"))
            assert preserved["status"] == "PASS"
            assert preserved["policy"]["publishableDedicatedSnapshot"] is True

            # With no LKG there is still no invented snapshot: the resolver
            # remains fail-closed and does not create a replacement artifact.
            output_path.unlink()
            no_lkg_status = builder.run(corpus_path, output_path, None)
            assert no_lkg_status == 2
            assert not output_path.exists()
        finally:
            builder.fetch = original_fetch

    assert payload["status"] == "PASS"
    assert payload["sourceFingerprintMatchesCorpus"] is True
    assert payload["policy"]["publishableDedicatedSnapshot"] is True
    assert payload["policy"]["autoPromoteIntoDossierBudget"] is False
    assert payload["policy"]["callStatusInferenceAllowed"] is False
    assert payload["summary"]["rowCount"] == 3
    assert payload["summary"]["interventions"] == ["DR-14", "DR-18"]
    assert payload["summary"]["sessionAllocationTotalEur"] == "65000000.00"
    assert payload["summary"]["submissionCeilingTotalEur"] == "97500000.00"
    assert payload["summary"]["submittedPublicValueTotalEur"] == "426908.00"
    assert payload["summary"]["availableFundsTotalEur"] == "97073092.00"
    assert payload["summary"]["submittedProjectCount"] == 7

    dr14 = [row for row in payload["rows"] if row["interventionCode"] == "DR-14"]
    assert len(dr14) == 2
    assert dr14[0]["opensAtIso"].endswith("+03:00")
    assert dr14[0]["availableFundsEur"] in {"44856455.00", "44907500.00"}

    print("AFIR live-funds structured snapshot + transport fail-closed regression PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())