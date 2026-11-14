#!/usr/bin/env python3
"""Hermetic T1 MIPE original-byte capture/replay tests: absolutely no call admission."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu/ingest"))
import pddtj_t1_primary_acquire as m  # noqa: E402


def fail(fn, reason):
    try:
        fn()
    except (OSError, ValueError):
        return
    raise AssertionError("T1 primary fail-open: " + reason)


def original():
    body = ("Ministerul Investitiilor si Proiectelor Europene: Ordinul 1794/2026 "
            "actualizeaza ghidul pentru parcuri industriale, Sprijin pentru "
            "infrastructura de afaceri. Fara lansarea unui nou apel. " * 5)
    return ("<html><head><title>Ghid</title></head><body>"
            "<article><h1>Actualizare oficiala</h1><p>" + body +
            "</p></article></body></html>").encode("utf-8")


def sealed(manifest):
    copy_of = copy.deepcopy(manifest)
    copy_of["handoff_sha256"] = m.oi.digest(m.oi.canonical({
        k: v for k, v in copy_of.items() if k != "handoff_sha256"
    }))
    return copy_of


def main():
    reg = m.oi.strict_load(m.REGISTRY.read_text(encoding="utf-8"))
    url, witness = m.identity(reg)
    assert url.startswith("https://mfe.gov.ro/")
    assert witness.startswith("https://www.cjgorj.ro/")
    stamp = "2026-11-10T12:00:00Z"

    def good(request):
        assert request == url
        return original(), "text/html", url, 200

    with TemporaryDirectory() as temp:
        path = Path(temp) / "raw"
        manifest = m.acquire(reg, path, "hermetic-t1-1", good, stamp)
        assert manifest["fetch_pass"] == 1 and manifest["fetch_fail"] == 0
        row = manifest["rows"][0]
        assert row["raw_sha256"] == m.oi.digest(original())
        assert row["parser_version"] == m.VERSION
        assert row["observation_state"] == "GUIDE_AMENDMENT_DISCOVERED_RAW_PENDING"
        assert row["t1_primary_reconciled"] is False
        assert all(manifest.get(k) == v for k, v in m.OFF.items())
        assert m.validate_replay(manifest, path, reg)
        for key, bad in [
            ("open_call_authorized", True),
            ("publish_authorized", True),
            ("t1_primary_reconciled", True),
            ("effective_date_verified", True),
            ("order_attachment_verified", True),
            ("observation_state", "OPEN_CALL"),
            ("raw_sha256", "0" * 64),
            ("requested_url", "https://attacker.example"),
            ("parser_version", "rewritten"),
            ("source_family", ["ROMANIA", "OPEN_CALL"]),
            ("http_status", 201),
            ("attempted_at", "2026-11-10T13:00:00"),
        ]:
            forged = copy.deepcopy(manifest)
            forged["rows"][0][key] = bad
            fail(lambda forged=forged: m.validate_replay(sealed(forged), path, reg), key)
        invalid_run = copy.deepcopy(manifest)
        invalid_run["run_id"] = "../path"
        invalid_run["rows"][0]["run_id"] = "../path"
        fail(lambda: m.validate_replay(sealed(invalid_run), path, reg),
             "unsafe forged replay run id")
        altered_bytes = path / m.RAW_NAME
        altered_bytes.write_bytes(original() + b" changed")
        fail(lambda: m.validate_replay(manifest, path, reg), "modified original bytes")

    for issue in ["403", "timeout", "wrong", "redirect", "media", "hidden"]:
        def broken(request):
            if issue == "403":
                raise HTTPError(url, 403, "Forbidden", {}, None)
            if issue == "timeout":
                raise OSError("timeout")
            if issue == "wrong":
                return b"<html><body>Another ministry story</body></html>", "text/html", url, 200
            if issue == "redirect":
                return original(), "text/html", "https://example.org/spoof", 200
            if issue == "media":
                return original(), "application/pdf", url, 200
            if issue == "hidden":
                return (b"<html><body><div hidden>" + original() +
                        b"</div>short shell</body></html>"), "text/html", url, 200
            raise AssertionError("missing scenario")
        with TemporaryDirectory() as temp:
            path = Path(temp) / "raw"
            receipt = m.acquire(reg, path, "hermetic-t1-2", broken, stamp)
            assert receipt["fetch_pass"] == 0 and receipt["fetch_fail"] == 1
            row = receipt["rows"][0]
            assert row["fetched_at"] is None and row["raw_sha256"] is None
            assert row["attempted_at"] == stamp
            assert row["source_health"] == (
                "HTTP_FAILURE" if issue == "403" else
                "TRANSPORT_FAILURE" if issue == "timeout" else
                "IDENTITY_OR_CONTENT_REVIEW")
            assert row["http_status"] == (403 if issue == "403" else None)
            assert m.validate_replay(receipt, path, reg)
            forged = copy.deepcopy(receipt)
            forged["rows"][0]["fetched_at"] = stamp
            fail(lambda: m.validate_replay(sealed(forged), path, reg),
                 "fabricated successful fetched_at")
            forged = copy.deepcopy(receipt)
            forged["rows"][0]["http_status"] = 200
            fail(lambda: m.validate_replay(sealed(forged), path, reg),
                 "forged HTTP success on failure")

    registry_drift = copy.deepcopy(reg)
    row = next(x for x in registry_drift["sources"] if x["id"] == m.SOURCE_ID)
    row["primary_t1_link_candidate"] = "https://example.com/other"
    fail(lambda: m.identity(registry_drift), "untrusted original endpoint")
    row["primary_t1_link_candidate"] = url
    row["material_fact_use"] = True
    fail(lambda: m.identity(registry_drift), "unreviewed source promotion")
    print(json.dumps({
        "test": "PDDTJ MIPE T1 candidate non-admitting original-byte handoff",
        "positive": 1, "failure_modes": 6, "tamper_checks": 27,
        "result": "PASS", "publication_effect": "NONE",
    }))


if __name__ == "__main__":
    main()
