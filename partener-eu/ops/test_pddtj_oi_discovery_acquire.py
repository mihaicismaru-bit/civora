#!/usr/bin/env python3
"""Hermetic original-byte/replay/authority tests for PDDTJ delegated OI acquisition."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu/ingest"))
import pddtj_oi_discovery_acquire as m  # noqa: E402


def must_fail(fn, message):
    try:
        fn()
    except (ValueError, OSError):
        return
    raise AssertionError("FAIL open on " + message)


def html(sid, hidden=False):
    spec = m.PINNED[sid]
    terms = " ".join(spec["words"])
    body = ("Actul oficial de informare al organismului intermediar privind " +
            terms + ". " + "Acest material este doar informativ si nu reprezinta "
            "autorizarea unui nou apel de finantare. " * 5)
    if hidden:
        return (f'<html><head><title>{terms}</title></head>'
                f'<body><div hidden>{body}</div>Un mesaj generic</body></html>').encode()
    return (f'<html><head><title>generic</title></head><body>'
            f'<article><h1>{terms}</h1><p>{body}</p></article></body></html>').encode()


def registry():
    return m.strict_load(m.REGISTRY.read_text(encoding="utf-8"))


def fresh(data):
    value = copy.deepcopy(data)
    value["handoff_sha256"] = m.digest(m.canonical({
        k: v for k, v in value.items() if k != "handoff_sha256"
    }))
    return value


def main():
    sources = registry()
    stamp = "2026-11-10T11:00:00Z"
    raws = {spec["url"]: html(sid) for sid, spec in m.PINNED.items()}

    def good(url):
        return raws[url], "text/html", url, 200

    with TemporaryDirectory() as temp:
        root = Path(temp)
        output = root / "raw"
        manifest = m.capture(sources, output, "hermetic-123", good, stamp)
        assert manifest["fetch_pass"] == 2 and manifest["fetch_fail"] == 0
        assert m.validate_replay(manifest, output, sources)
        assert manifest["publication_effect"] == "NONE"
        assert manifest["t1_primary_reconciled"] is False
        assert all(x["open_call_authorized"] is False and
                   x["material_fact_use"] is False and
                   x["fetched_at"] == stamp and len(x["raw_sha256"]) == 64
                   for x in manifest["rows"])

        # Modified original bytes must never pass an otherwise valid handoff.
        first = next(iter(m.PINNED.values()))["raw"]
        path = output / first
        original = path.read_bytes()
        path.write_bytes(original + b"\nchanged after observation")
        must_fail(lambda: m.validate_replay(manifest, output, sources),
                  "raw content modified after capture")
        path.write_bytes(original)

        # A hash-only rewritten manifest cannot promote OI to MIPE/OPEN.
        bad = copy.deepcopy(manifest)
        bad["rows"][0]["observation_state"] = "OPEN_CALL"
        must_fail(lambda: m.validate_replay(fresh(bad), output, sources),
                  "forged OPEN state")
        bad = copy.deepcopy(manifest)
        bad["rows"][0]["authority_class"] = "T1_MIPE"
        must_fail(lambda: m.validate_replay(fresh(bad), output, sources),
                  "forged primary authority")
        bad = copy.deepcopy(manifest)
        bad["publish_authorized"] = True
        must_fail(lambda: m.validate_replay(fresh(bad), output, sources),
                  "forged publication")
        bad = copy.deepcopy(manifest)
        bad["rows"][0]["source_id"] = manifest["rows"][1]["source_id"]
        must_fail(lambda: m.validate_replay(fresh(bad), output, sources),
                  "duplicate source substitution")
        bad = copy.deepcopy(manifest)
        bad["rows"][0]["fetched_at"] = "2026-11-10T11:00:00"
        must_fail(lambda: m.validate_replay(fresh(bad), output, sources),
                  "zoneless receipt")
        bad = copy.deepcopy(manifest)
        bad["rows"][0]["final_url"] = "https://other.example/article/"
        must_fail(lambda: m.validate_replay(fresh(bad), output, sources),
                  "wrong final endpoint")
        bad = copy.deepcopy(manifest)
        bad["rows"][0]["raw_sha256"] = "0" * 64
        must_fail(lambda: m.validate_replay(fresh(bad), output, sources),
                  "fake original hash")
        bad = copy.deepcopy(manifest)
        bad["rows"][0]["call_deadline"] = "2026-11-24"
        must_fail(lambda: m.validate_replay(fresh(bad), output, sources),
                  "invented call deadline field")
        bad = copy.deepcopy(manifest)
        bad["rows"][0]["raw_file"] = "../other.json"
        must_fail(lambda: m.validate_replay(fresh(bad), output, sources),
                  "path traversal")

    # Wrong article, hidden identity and fake HTML shell may be fetched,
    # but MUST have only explicit FAIL_REVIEW without raw receipts.
    for issue in ["wrong", "hidden", "redirect", "media", "403"]:
        with TemporaryDirectory() as temp:
            def fail_one(url):
                sid = next(k for k, v in m.PINNED.items() if v["url"] == url)
                spec = m.PINNED[sid]
                if sid == next(iter(m.PINNED)):
                    if issue == "403":
                        raise OSError("403 Forbidden")
                    if issue == "wrong":
                        return b"<html><body>Unrelated grant index</body></html>", "text/html", url, 200
                    if issue == "hidden":
                        return html(sid, hidden=True), "text/html", url, 200
                    if issue == "redirect":
                        return html(sid), "text/html", "https://untrusted.example/notice", 200
                    if issue == "media":
                        return html(sid), "application/pdf", url, 200
                return html(sid), "text/html", url, 200
            receipt = m.capture(sources, Path(temp) / "raw", "hermetic-124",
                                fail_one, stamp)
            assert receipt["fetch_pass"] == 1 and receipt["fetch_fail"] == 1, issue
            rejected = [x for x in receipt["rows"] if x["fetch_status"] == "FAIL_REVIEW"]
            assert rejected[0]["raw_sha256"] is None
            assert rejected[0]["fetched_at"] is None
            assert rejected[0]["open_call_authorized"] is False
            assert m.validate_replay(receipt, Path(temp) / "raw", sources)

    # Registry id/authority cannot be silently rebound to an attacker endpoint.
    altered = copy.deepcopy(sources)
    target = next(x for x in altered["sources"] if x["id"] in m.PINNED)
    target["url"] = "https://untrusted.example/replacement"
    must_fail(lambda: m.source_rows(altered), "registry source URL substitution")
    altered = copy.deepcopy(sources)
    target = next(x for x in altered["sources"] if x["id"] in m.PINNED)
    target["material_fact_use"] = True
    must_fail(lambda: m.source_rows(altered), "registry material promotion")
    must_fail(lambda: m.capture(sources, Path("/tmp/no-run-used"), "", good, stamp),
              "missing acquisition run ID")

    print(json.dumps({"test": "PDDTJ OI acquisition + immutable replay",
                      "positive": 2, "failure_classes": 5,
                      "tamper_gates": 10, "result": "PASS",
                      "open_call_authorized": False, "publication_effect": "NONE"}))


if __name__ == "__main__":
    main()
