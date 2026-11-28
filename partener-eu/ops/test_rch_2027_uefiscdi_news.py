#!/usr/bin/env python3
"""Hermetic UEFISCDI RCH secondary-source acquisition and replay regression."""
import json
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))
import rch_2027_raw_acquire as raw
import rch_2027_paired_handoff as pair
import rch_2027_uefiscdi_news as news

RUN = "rch-uefiscdi-fixture"
OFFICIAL = (
    "<!DOCTYPE html><html><body>"
    "<h1>Primul apel transnațional al Parteneriatului European "
    "„Resilient Cultural Heritage”</h1>"
    "<p>În România, apelul este gestionat de Ministerul Culturii, "
    "prin Unitatea de Management a Proiectului (MC-UMP).</p>"
    "<p>Universitățile și muzeele pot participa; eligibilitatea națională "
    "se verifică exclusiv în Anexa I.</p></body></html>"
).encode("utf-8")
SOURCE = (b"<!doctype html><html><body>First Joint Transnational Call: "
          b"Foundations for climate-resilient cultural heritage. "
          b"Primul apel de proiecte Resilient Cultural Heritage.</body></html>")
PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\nstartxref\n9\n%%EOF\n"


def reject(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except (ValueError, TypeError, KeyError, FileNotFoundError):
        return
    raise AssertionError(f"fail-closed rejection missing: {fn.__name__}")


def reseal(doc):
    doc = deepcopy(doc)
    doc.pop("handoff_sha256")
    doc["handoff_sha256"] = raw.sha256(raw.canonical_json(doc))
    return doc


def test_transport_and_identity():
    news.validate_url(news.URL)
    news.validate_url(news.URL.replace("uefiscdi.gov.ro", "www.uefiscdi.gov.ro"))
    for url in (
        news.URL.replace("https:", "http:", 1),
        news.URL.replace("uefiscdi.gov.ro", "uefiscdi.gov.ro.evil.example"),
        news.URL + "?fresh=true", news.URL + "#article",
        news.URL.replace("/news-", "/another-"),
        news.URL.replace("https://", "https://evil@"),
    ):
        reject(news.validate_url, url)
    news.validate_response(status=200, mime="text/html",
                           encoding="identity", declared_length=str(len(OFFICIAL)),
                           body=OFFICIAL)
    for params in (
        {"status": 403}, {"mime": "application/pdf"}, {"encoding": "gzip"},
        {"declared_length": "1"}, {"declared_length": "n/a"},
        {"body": b""}, {"body": b"<!doctype html><html><body>Maintenance</body></html>"},
        {"body": b"<!doctype html><html><script>" + OFFICIAL + b"</script></html>"},
        {"body": b"<!doctype html><html><body><div hidden>" + OFFICIAL + b"</div></body></html>"},
        {"body": b"<!doctype html><html><body><div style='display:none'>" + OFFICIAL + b"</div></body></html>"},
    ):
        args = dict(status=200, mime="text/html", encoding="identity",
                    declared_length=None, body=OFFICIAL)
        args.update(params)
        reject(news.validate_response, **args)


def test_bound_capture_and_fail_closed_replay():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        old_html, old_pdf, old_news = raw.fetch_raw, raw.fetch_document_raw, news.fetch_news
        try:
            raw.fetch_raw = lambda sid: (SOURCE, raw.SOURCE_SPECS[sid]["url"], "text/html")
            raw.fetch_document_raw = lambda sid: (PDF, raw.document_url(sid), "application/pdf")
            news.fetch_news = lambda: (OFFICIAL, news.URL, "text/html")
            raw.capture(root, RUN)
            raw.capture_documents(root, RUN)
            assert pair.seal(root)["original_count"] == 5
            result = news.capture(root, RUN)
            assert result["status"] == "SECONDARY_OFFICIAL_NEWS_RAW_REPLAY_VERIFIED_NOT_PUBLISHED"
        finally:
            raw.fetch_raw, raw.fetch_document_raw, news.fetch_news = old_html, old_pdf, old_news
        assert all(result[k] is False for k in (
            "open_call_authorized", "eligibility_authorized",
            "publish_authorized", "distribution_authorized"))
        assert result["paired_handoff_sha256"] == pair.replay(root)["paired_handoff_sha256"]
        reject(news.capture, root, "different-run")

        path = root / news.MANIFEST_PATH
        original = path.read_bytes()
        manifest = json.loads(original)
        for field, value in (
            ("paired_handoff_sha256", "f" * 64),
            ("run_id", "unrelated-run"),
            ("observation_state", "OPEN_CALL"),
            ("eligibility_authorized", True),
            ("distribution_authorized", True),
        ):
            bad = deepcopy(manifest)
            bad[field] = value
            path.write_text(json.dumps(reseal(bad)))
            reject(news.replay, root)
        for field, value in (
            ("raw_sha256", "f" * 64),
            ("authority_class", "T1B_NATIONAL_PARTNERSHIP_PARTICIPANT"),
            ("source_family", ["ROMANIA", "CALL_REGISTRY"]),
            ("observation_state", "OPEN_CALL"),
            ("run_id", "fake-run"),
            ("eligibility_authorized", True),
        ):
            bad = deepcopy(manifest)
            bad["receipt"][field] = value
            path.write_text(json.dumps(reseal(bad)))
            reject(news.replay, root)
        # Rehashing a receipt with the same run_id must not disguise a stale,
        # delayed or future secondary capture as part of the five-source batch.
        for bad_stamp in (
            "2000-01-01T00:00:00Z",
            "2099-01-01T00:00:00Z",
            (datetime.now(timezone.utc) + timedelta(minutes=25)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ):
            bad = deepcopy(manifest)
            bad["receipt"]["fetched_at_utc"] = bad_stamp
            path.write_text(json.dumps(reseal(bad)))
            reject(news.replay, root)
        bad = deepcopy(manifest)
        bad["publication_authorized"] = True
        path.write_text(json.dumps(reseal(bad)))
        reject(news.replay, root)
        bad = deepcopy(manifest)
        bad["receipt"]["unknown_authorization"] = True
        path.write_text(json.dumps(reseal(bad)))
        reject(news.replay, root)
        # Duplicate evidence keys with conflicting authorization must fail.
        path.write_text(original.decode("utf-8").replace('"schema_version":', '"schema_version":"evil","schema_version":'))
        reject(news.replay, root)
        path.write_bytes(original)
        body_path = root / news.RAW_PATH
        original_body = body_path.read_bytes()
        body_path.write_bytes(original_body + b" tampered")
        reject(news.replay, root)
        body_path.write_bytes(original_body)
        assert news.replay(root)["open_call_authorized"] is False


if __name__ == "__main__":
    test_transport_and_identity()
    test_bound_capture_and_fail_closed_replay()
    print("PASS RCH UEFISCDI secondary news raw bytes / paired five-original provenance / non-authorizing replay")
