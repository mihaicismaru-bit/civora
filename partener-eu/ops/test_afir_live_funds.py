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
AFIR_INGEST = ROOT / "partener-eu" / "ingest" / "afir_ingest.py"

# Five-row fixture mirrors the live AFIR counter shape observed on 2026-09-24.
# It is a parser regression fixture only; it is not an authority/freshness
# substitute for the canonical AFIR fetch performed by the ingestion workflow.
FIXTURE = """<!doctype html><html><body>
<table>
<tr><th>Intervenția</th><th>Sector</th><th>Alocare sesiune/sector</th><th>Dată și oră lansare sesiune</th>
<th>Dată și oră închidere sesiune</th><th>Plafon depunere proiecte</th><th>Valoarea proiectelor depuse</th>
<th>Număr proiecte depuse</th><th>Fonduri disponibile</th></tr>
<tr><td colspan="9">Investiții în fermele de mici dimensiuni</td></tr>
<tr><td>DR-14</td><td><strong>Componenta LEGUMICULTURĂ</strong></td><td>30.000.000,00 EUR</td>
<td>01.09.2026 09:00:00</td><td>31.10.2026 15:59:59</td><td>45.000.000,00 EUR</td>
<td>283.310</td><td>6</td><td>44.716.690,00 EUR</td></tr>
<tr><td>DR-14</td><td>Componenta SECTOR ZOOTEHNIC</td><td>30.000.000,00 EUR</td>
<td>01.09.2026 09:00:00</td><td>31.10.2026 15:59:59</td><td>45.000.000,00 EUR</td>
<td>92.500</td><td>2</td><td>44.907.500,00 EUR</td></tr>
<tr><td>DR-14</td><td>Componenta ACHIZIȚII SIMPLE (INDIFERENT DE SECTOR)</td><td>18.000.000,00 EUR</td>
<td>01.09.2026 09:00:00</td><td>31.10.2026 15:59:59</td><td>27.000.000,00 EUR</td>
<td>8.166.102</td><td>173</td><td>18.833.898,00 EUR</td></tr>
<tr><td>DR-14</td><td>Componenta ALTE SECTOARE (PENTRU TOATE PROIECTELE CARE NU ÎNDEPLINESC CONDIȚIILE ÎNCADRĂRII ÎN CELELALTE COMPONENTE)</td><td>30.000.000,00 EUR</td>
<td>01.09.2026 09:00:00</td><td>31.10.2026 15:59:59</td><td>45.000.000,00 EUR</td>
<td>1.340.216</td><td>27</td><td>43.659.784,00 EUR</td></tr>
<tr><td>DR-18</td><td>Investiții în floricultură, plante medicinale și aromatice</td><td>5.000.000,00 EUR</td>
<td>01.09.2026 09:00:00</td><td>31.10.2026 15:59:59</td><td>7.500.000,00 EUR</td>
<td>190.863</td><td>2</td><td>7.309.137,00 EUR</td></tr>
</table></body></html>"""


EXHAUSTED_FIXTURE = """<!doctype html><html><body>
<table>
<tr><th>Intervenția</th><th>Sector</th><th>Alocare sesiune/sector</th><th>Dată și oră lansare sesiune</th>
<th>Dată și oră închidere sesiune</th><th>Plafon depunere proiecte</th><th>Valoarea proiectelor depuse</th>
<th>Număr proiecte depuse</th><th>Fonduri disponibile</th></tr>
<tr><td>DR-14</td><td>Componenta ACHIZIȚII SIMPLE (INDIFERENT DE SECTOR)</td><td>18.000.000,00 EUR</td>
<td>01.09.2026 09:00:00</td><td>06.10.2026 00:00:00</td><td>27.000.000,00 EUR</td>
<td>35.010.497</td><td>753</td><td>FONDURI EPUIZATE</td></tr>
</table></body></html>"""

def load_builder_module():
    sys.path.insert(0, str(BUILDER.parent))
    spec = importlib.util.spec_from_file_location("partener_afir_live_funds_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_ingest_module():
    spec = importlib.util.spec_from_file_location("partener_afir_ingest", AFIR_INGEST)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_afir_fetch_transport_provenance() -> None:
    """No redirected authority, TLS downgrade or truncated body becomes AFIR proof."""
    from unittest.mock import patch

    ingest = load_ingest_module()
    official = "https://www.afir.ro/info-la-zi/"
    class Response:
        def __init__(self, final_url, data=b"verified AFIR source bytes", status=200, declared_length=None):
            self.final_url, self.data, self.status = final_url, data, status
            self.headers = {"Content-Type": "text/html; charset=utf-8"}
            if declared_length is not None:
                self.headers["Content-Length"] = str(declared_length)
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def geturl(self):
            return self.final_url
        def read(self, n):
            assert n == 12_000_001, "must reject truncated fingerprint candidates"
            return self.data[:n]

    def probe(response, *, allowed):
        with patch.object(ingest.urllib.request, "urlopen", return_value=response):
            result = ingest.fetch(official, sleep=lambda _delay: None)
        assert result["ok"] is allowed, result
        if allowed:
            assert result["data"] == response.data
        else:
            assert "data" not in result, "rejected source must not expose publishable bytes"
        return result

    probe(Response(official), allowed=True)
    probe(Response(official, declared_length=len(b"verified AFIR source bytes")), allowed=True)
    probe(Response(official, declared_length=1), allowed=False)
    probe(Response(official, declared_length="not-a-number"), allowed=False)
    for final in (
        "https://untrusted.example/afir-copy",
        "http://www.afir.ro/info-la-zi/",
        "https://www.afir.ro/umbraco/surface/authentication/login",
        "https://user:pass@www.afir.ro/info-la-zi/",
    ):
        probe(Response(final), allowed=False)
    probe(Response(official, status=500), allowed=False)
    probe(Response(official, data=b""), allowed=False)
    probe(Response(official, data=b"x" * 12_000_001), allowed=False)


def test_extension_notice_raw_receipt() -> None:
    """Receipt is exact-byte acquisition evidence, never OPEN or publish proof."""
    from unittest.mock import patch

    ingest = load_ingest_module()
    body = b"<html><title>AFIR DR-14 DR-18 extension</title></html>"
    fetched = {
        "ok": True,
        "url": ingest.AFIR_EXTENSION_NOTICE,
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "data": body,
    }
    with tempfile.TemporaryDirectory() as tmp:
        environment = {
            "PARTENER_AFIR_EVIDENCE_DIR": tmp,
            "GITHUB_RUN_ID": "41999999999",
            "GITHUB_RUN_ATTEMPT": "1",
        }
        with patch.dict(ingest.os.environ, environment):
            manifest = ingest.capture_extension_notice_receipt(
                ingest.AFIR_EXTENSION_NOTICE, fetched, "2026-11-05T02:00:00+00:00"
            )
            assert manifest is not None
            persisted = json.loads((Path(tmp) / "manifest.json").read_text(encoding="utf-8"))
            assert persisted == manifest
            assert (Path(tmp) / manifest["raw_evidence_file"]).read_bytes() == body
            assert manifest["raw_sha256"] == hashlib.sha256(body).hexdigest()
            assert manifest["run_id"] == "41999999999"
            assert manifest["parser_version"] == ingest.AFIR_RECEIPT_PARSER_VERSION
            assert manifest["source_family"] == "AFIR"
            assert manifest["authority_class"] == "T1_OFFICIAL_AGENCY"
            assert manifest["observation_state"] == "RAW_FETCHED_PENDING_SEMANTIC_RECONCILIATION"
            assert manifest["publish_authorized"] is False
            assert manifest["material_fact_action"] == "NONE"
            assert ingest.capture_extension_notice_receipt(
                "https://www.afir.ro/unrelated/", fetched, "2026-11-05T02:00:00+00:00"
            ) is None
            for broken in (
                dict(fetched, url="http://www.afir.ro/info-la-zi/prelungire-sesiune-depunere-proiecte-de-investitii-aferente-dr-14-si-dr-18/"),
                dict(fetched, url="https://untrusted.example/"),
                dict(fetched, data=b""),
                dict(fetched, content_type="application/pdf"),
            ):
                try:
                    ingest.capture_extension_notice_receipt(
                        ingest.AFIR_EXTENSION_NOTICE, broken, "2026-11-05T02:00:00+00:00"
                    )
                except ValueError:
                    pass
                else:
                    raise AssertionError("invalid raw notice receipt must be rejected")
        with patch.dict(ingest.os.environ, environment | {"GITHUB_RUN_ID": ""}):
            try:
                ingest.capture_extension_notice_receipt(
                    ingest.AFIR_EXTENSION_NOTICE, fetched, "2026-11-05T02:00:00+00:00"
                )
            except ValueError:
                pass
            else:
                raise AssertionError("a receipt without real run ID is inadmissible")
    assert ingest.AFIR_EXTENSION_NOTICE in ingest.SEEDS


def main() -> int:
    fixture_bytes = FIXTURE.encode("utf-8")
    fingerprint = hashlib.sha256(fixture_bytes).hexdigest()
    corpus = {
        "schemaVersion": 2,
        "source": "AFIR",
        "generatedAt": "2026-09-24T07:30:00+00:00",
        "items": [
            {
                "url": "https://www.afir.ro/finantare/contor-fonduri-disponibile/",
                "title": "Contor fonduri disponibile",
                "sha256": fingerprint,
                "observedAt": "2026-09-24T07:30:00+00:00",
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

        # The real AFIR counter mutates while submissions arrive. A second
        # canonical production fetch may therefore have a different byte hash
        # from the corpus observation only seconds earlier. If that exact live
        # response is HTTP 200 HTML and the structured DR table still parses,
        # the dedicated snapshot may reconcile the race transparently. Static
        # fixture drift above remains fail-closed.
        builder = load_builder_module()
        original_load_source_bytes = builder.load_source_bytes
        try:
            builder.load_source_bytes = lambda _url, _fixture: (
                fixture_bytes,
                "text/html; charset=utf-8",
                200,
            )
            live_reconciled = builder.build_snapshot(drifted, None)
        finally:
            builder.load_source_bytes = original_load_source_bytes
        assert live_reconciled["status"] == "PASS"
        assert live_reconciled["sourceFingerprintMatchesCorpus"] is False
        assert live_reconciled["sourceFingerprintReconciledFromCanonicalLiveFetch"] is True
        assert live_reconciled["policy"]["publishableDedicatedSnapshot"] is True
        assert (
            live_reconciled["policy"]["dynamicCounterReconciliation"]
            == "exact-canonical-live-fetch-with-valid-structured-rows"
        )
        assert live_reconciled["provenance"]["corpusObservedAt"] == corpus["items"][0]["observedAt"]
        assert live_reconciled["sourceObservedAt"] != corpus["items"][0]["observedAt"]

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
    assert payload["summary"]["rowCount"] == 5
    assert payload["summary"]["interventions"] == ["DR-14", "DR-18"]
    assert payload["summary"]["sessionAllocationTotalEur"] == "113000000.00"
    assert payload["summary"]["submissionCeilingTotalEur"] == "169500000.00"
    assert payload["summary"]["submittedPublicValueTotalEur"] == "10072991.00"
    assert payload["summary"]["availableFundsTotalEur"] == "159427009.00"
    assert payload["summary"]["submittedProjectCount"] == 210

    builder = load_builder_module()
    exhausted_rows = builder.parse_rows(builder.parse_table(EXHAUSTED_FIXTURE.encode("utf-8")))
    assert len(exhausted_rows) == 1
    exhausted = exhausted_rows[0]
    assert exhausted["interventionCode"] == "DR-14"
    assert exhausted["closesAtLocal"] == "06.10.2026 00:00:00"
    assert exhausted["submittedPublicValueEur"] == "35010497.00"
    assert exhausted["submittedProjectCount"] == 753
    assert exhausted["availableFundsEur"] == "0.00"
    assert exhausted["availableFundsStatus"] == "EXHAUSTED"
    assert builder.parse_available_funds("FONDURI EPUIZATE") == ("0.00", "EXHAUSTED")
    assert builder.parse_available_funds("1.234,56 EUR") == ("1234.56", "REPORTED")
    try:
        builder.parse_eur("FONDURI EPUIZATE")
    except ValueError:
        pass
    else:
        raise AssertionError("generic EUR parser must remain strict for semantic status markers")

    for marker in ("-", "–", "—", "N/A", "N/D"):
        assert builder.parse_eur(marker) is None
    assert builder.parse_eur("1.234,56 EUR") == "1234.56"
    assert builder.decimal_total([{"amount": "1.00"}, {"amount": None}], "amount") is None
    assert builder.decimal_total([{"amount": "1.00"}, {"amount": "2.50"}], "amount") == "3.50"

    test_afir_fetch_transport_provenance()
    test_extension_notice_raw_receipt()
    ingest = load_ingest_module()
    normalized = ingest.norm(
        "https://www.afir.ro/api/file?filename=Anunț Cerere DR-12 – Investiții.pdf&download=1"
    )
    assert normalized is not None
    assert " " not in normalized
    assert "ț" not in normalized and "–" not in normalized
    assert "filename=Anun%C8%9B%20Cerere%20DR-12%20%E2%80%93%20Investi%C8%9Bii.pdf" in normalized
    assert normalized.endswith("&download=1")
    assert ingest.norm(
        "https://www.afir.ro/umbraco/surface/authentication/login?redirectUrl=/api/file"
    ) is None
    assert "https://www.afir.ro/comunicate/" in ingest.SEEDS
    assert "https://www.afir.ro/finantare/" not in ingest.SEEDS

    dr14 = [row for row in payload["rows"] if row["interventionCode"] == "DR-14"]
    assert len(dr14) == 4
    assert dr14[0]["opensAtIso"].endswith("+03:00")
    assert {row["availableFundsEur"] for row in dr14} == {
        "44716690.00",
        "44907500.00",
        "18833898.00",
        "43659784.00",
    }
    assert {row["availableFundsStatus"] for row in dr14} == {"REPORTED"}

    print("AFIR live-funds structured snapshot + current five-row counter + transport fail-closed regression PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
