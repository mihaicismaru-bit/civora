#!/usr/bin/env python3
"""Hermetic DR-12 dated clarification acquisition and replay; no publication."""
import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import urllib.parse
from pathlib import Path
from unittest.mock import patch

INGEST = Path(__file__).resolve().parents[1] / "ingest"
spec = importlib.util.spec_from_file_location("dr12_note", INGEST / "afir_dr12_clarification_acquire.py")
assert spec and spec.loader
note = importlib.util.module_from_spec(spec)
spec.loader.exec_module(note)

URL = "https://stportalafirprod.blob.core.windows.net/media/media/nzghktz5/nota-clarificare-dr12_06112026.pdf"
PDF = b"%PDF-1.7\n1 0 obj\n<</Type/Catalog>>\nendobj\n%%EOF\n"
PROXY = "/api/file/document?" + urllib.parse.urlencode({
    "filename": note.LINK_LABEL, "filetype": "pdf",
    "url": "/media/nzghktz5/nota-clarificare-dr12_06112026.pdf",
})


def html(href=PROXY, label=None):
    return ("<html><h1>DR 12</h1><a href=\"" + href.replace("&", "&amp;") + "\">"
            + (note.LINK_LABEL if label is None else label) + "</a></html>").encode("utf-8")


def refused(fn, marker=None):
    try:
        fn()
    except (ValueError, KeyError, TypeError) as exc:
        if marker:
            assert marker in str(exc), str(exc)
    else:
        raise AssertionError("Unsafe DR-12 evidence admitted")


def test_delegation():
    assert note.delegated_url(html()) == URL
    for bad in (
        b"<html>DR-12 notice without link</html>",
        html() + html(),
        html(label="Clarificare DR-12"),
        html(href="https://evil.example/api/file/document?" + PROXY.split("?")[1]),
        html(href=PROXY + "&filetype=html"),
        html(href=PROXY.replace("06112026", "05112026")),
        html(href=PROXY.replace("%2Fmedia%2F", "%2Fexternal%2F")),
        html(href=PROXY.replace("filetype=pdf", "filetype=html")),
    ):
        refused(lambda bad=bad: note.delegated_url(bad))
    refused(lambda: note.validate_pdf(b"<html>login</html>"))
    refused(lambda: note.validate_pdf(b"%PDF-1.7 only header"))


def test_transport():
    class Response:
        status = 200
        def __init__(self, url, content, *, kind, encoding="identity", length=None):
            self._url, self._content, self.reads = url, content, 0
            self.headers = {
                "Content-Type": "text/html" if kind == "index" else "application/pdf",
                "Content-Encoding": encoding,
                "Content-Length": str(len(content) if length is None else length),
            }

        def geturl(self):
            return self._url

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, n):
            self.reads += 1
            return self._content[:n]

    class Opener:
        def __init__(self, response):
            self.response = response

        def open(self, request, timeout):
            return self.response

    def fetch(r, kind, url):
        with patch.object(note.urllib.request, "build_opener", return_value=Opener(r)):
            return note.acquire_exact(url, kind, authorized_pdf=URL)

    a = Response(note.INDEX_URL, html(), kind="index")
    assert fetch(a, "index", note.INDEX_URL)[0] == html()
    p = Response(URL, PDF, kind="pdf")
    assert fetch(p, "pdf", URL)[0] == PDF
    refused(lambda: note.acquire_exact(URL, "pdf", authorized_pdf="https://example.com"))
    for r in (Response(URL, PDF, kind="pdf", encoding="gzip"),
              Response(URL, PDF, kind="pdf", length=len(PDF) + 2)):
        refused(lambda r=r: fetch(r, "pdf", URL))
    r = Response(URL, b"<html>access denied</html>", kind="pdf")
    refused(lambda: fetch(r, "pdf", URL))


def test_capture_replay():
    def fake_download(url, kind, *, authorized_pdf=None):
        if kind == "index":
            assert url == note.INDEX_URL
            return html(), "text/html; charset=utf-8"
        assert kind == "pdf" and url == authorized_pdf == URL
        return PDF, "application/pdf"

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "capture"
        with patch.object(note, "acquire_exact", side_effect=fake_download):
            assert note.run(target, "42299999999", "2026-11-06T18:30:00Z") == 0
        record = note.replay(target)
        assert record["document"]["sha256"] == hashlib.sha256(PDF).hexdigest()
        assert not any(record[k] for k in ("call_status_authorized", "eligibility_authorized",
                                           "publish_authorized", "distribution_authorized"))
        original = (target / "manifest.json").read_bytes()
        for k, value in (
            ("status", "OPEN_CALL"),
            ("source_url", "https://evil.example"),
            ("parser_version", "other"),
            ("run_id", ""),
            ("eligibility_authorized", True),
            ("publish_authorized", True),
            ("distribution_authorized", True),
            ("fetched_at", "2026-11-06T18:30:00"),
        ):
            altered = copy.deepcopy(record)
            altered[k] = value
            (target / "manifest.json").write_text(json.dumps(altered), encoding="utf-8")
            refused(lambda: note.replay(target))
        altered = copy.deepcopy(record)
        altered["document"]["sha256"] = "0" * 64
        (target / "manifest.json").write_text(json.dumps(altered), encoding="utf-8")
        refused(lambda: note.replay(target))
        altered = copy.deepcopy(record)
        altered["open_call_status"] = "OPEN_CALL"
        (target / "manifest.json").write_text(json.dumps(altered), encoding="utf-8")
        refused(lambda: note.replay(target))
        (target / "manifest.json").write_bytes(
            original.replace(b'"schema":', b'"schema":"OPEN_CALL","schema":', 1))
        refused(lambda: note.replay(target), "Duplicate")
        (target / "manifest.json").write_bytes(original)
        (target / "clarification.raw.pdf").write_bytes(PDF + b"corruption")
        refused(lambda: note.replay(target), "integrity")
        (target / "clarification.raw.pdf").write_bytes(PDF)
        (target / "unauthorized.txt").write_text("OPEN_CALL")
        refused(lambda: note.replay(target), "contaminated")
        (target / "unauthorized.txt").unlink()
        assert note.replay(target) == record

        failed = Path(tmp) / "failed"
        with patch.object(note, "acquire_exact", side_effect=ValueError("HTTP access denied")):
            assert note.run(failed, "42299999998", "2026-11-06T18:35:00Z") == 2
        assert json.loads((failed / "manifest.json").read_text())["status"] == "RAW_FETCH_FAILED"
        assert not (failed / "clarification.raw.pdf").exists()
        refused(lambda: note.replay(failed))
        refused(lambda: note.run(target, "999", "2026-11-06T18:40:00Z"), "exists")


if __name__ == "__main__":
    test_delegation()
    test_transport()
    test_capture_replay()
    print("DR-12 clarification: hermetic acquisition, delegation and replay checks passed")
