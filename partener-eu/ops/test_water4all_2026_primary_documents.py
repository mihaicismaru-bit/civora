#!/usr/bin/env python3
"""Water4All 2026 primary PDF immutable handoff adversarial tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "water4all_docs", ROOT / "partener-eu/ingest/water4all_2026_primary_documents.py")
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

PDF = b"%PDF-1.7\n" + b"original-official-PDF-fixture" * 90 + b"\n%%EOF\n"
STAMP = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
DOCS = {name: (PDF + name.encode("ascii") + b"\n%%EOF\n",
               "application/pdf", STAMP) for name in mod.DOCUMENTS}


def reject(fn, marker):
    try:
        fn()
    except (ValueError, OSError, TypeError, KeyError) as exc:
        assert marker in str(exc), (marker, str(exc))
        return
    raise AssertionError("unsafe PDF evidence was accepted")


def run():
    for name in mod.DOCUMENTS:
        url = mod.DOCUMENTS[name]["url"]
        mod.exact_url(name, url)
        for altered in (url.replace("https:", "http:", 1), url + "?open=true",
                        url.replace("www.water4all-partnership.eu", "evil.invalid"),
                        url + "#latest"):
            reject(lambda u=altered, n=name: mod.exact_url(n, u), "URL")
    for original in DOCS.values():
        mod.pdf_ok(original[0], original[1])
        for mime in ("text/html", "application/pdf-fake", "application/octet-stream"):
            reject(lambda m=mime, b=original[0]: mod.pdf_ok(b, m), "MIME")
        reject(lambda b=original[0]: mod.pdf_ok(b.replace(b"%%EOF", b"NOEOF"), "application/pdf"), "trailer")
        reject(lambda b=original[0]: mod.pdf_ok(b"NO" + b[2:], "application/pdf"), "magic")
    reject(lambda: mod.build({}, "qa"), "exact official")
    reject(lambda: mod.build({"FAKE": next(iter(DOCS.values()))}, "qa"), "exact official")
    reject(lambda: mod.build(DOCS, "../evil"), "run_id")
    reject(lambda: mod.stamp_ok("2026-11-09T12:00:00Z"), "period")
    reject(lambda: mod.stamp_ok("2026-11-11T12:00:00+00:00"), "UTC seconds")

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        path = root / "docs"
        expected = mod.seal(path, DOCS, "water4all-docs-test")
        assert expected["status"] == "BOTH_PDFS_RAW_REPLAY_VERIFIED_NOT_RECONCILED"
        assert expected["document_count"] == 2
        assert expected["open_call_authorized"] is False
        assert mod.replay(path) == expected
        reject(lambda: mod.seal(path, DOCS, "again"), "immutable")
        manifest = path / "handoff.json"
        raw = path / "raw" / "CALL_ANNOUNCEMENT.pdf"
        clean_pdf = raw.read_bytes()
        raw.write_bytes(clean_pdf + b"untrusted")
        reject(lambda: mod.replay(path), "mismatch")
        raw.write_bytes(clean_pdf)

        manifest_clean = manifest.read_bytes()
        forged = json.loads(manifest_clean)
        forged["open_call_authorized"] = True
        forged["handoff_sha256"] = mod.sha256(mod.canonical({
            k: v for k, v in forged.items() if k != "handoff_sha256"}))
        manifest.write_bytes(mod.canonical(forged))
        reject(lambda: mod.replay(path), "mismatch")
        manifest.write_bytes(manifest_clean.replace(b'"schema":', b'"schema":"evil","schema":'))
        reject(lambda: mod.replay(path), "duplicate")
        manifest.write_bytes(manifest_clean)
        (path / "raw" / "unlisted.pdf").write_bytes(PDF)
        reject(lambda: mod.replay(path), "file-set")
        (path / "raw" / "unlisted.pdf").unlink()
        assert mod.replay(path) == expected

        half = root / "one"
        first = "CALL_ANNOUNCEMENT"
        result = mod.seal(half, {first: DOCS[first]}, "water4all-docs-partial")
        assert result["status"] == "PARTIAL_PDFS_RAW_REPLAY_VERIFIED_NOT_RECONCILED"
        assert result["documents_missing"] == ["NATIONAL_REGULATIONS"]
        assert mod.replay(half) == result
        partial_manifest = half / "handoff.json"
        clean = partial_manifest.read_bytes()
        fake = json.loads(clean)
        fake["documents_complete"] = True
        fake["documents_missing"] = []
        fake["handoff_sha256"] = mod.sha256(mod.canonical({
            k: v for k, v in fake.items() if k != "handoff_sha256"}))
        partial_manifest.write_bytes(mod.canonical(fake))
        reject(lambda: mod.replay(half), "mismatch")
    print("Water4All 2026 original-PDF handoff/replay PASS; all publication/OPEN permissions locked")


if __name__ == "__main__":
    run()
