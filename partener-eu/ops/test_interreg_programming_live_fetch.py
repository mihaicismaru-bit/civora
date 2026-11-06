#!/usr/bin/env python3
from pathlib import Path
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))

import interreg_programming_live_fetch as live  # noqa: E402


def _registry(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "SRC-INTERREG-ROHU",
                        "tier": "T1",
                        "url": "https://interreg-rohu.eu/en/",
                        "programmes": ["Interreg Romania-Hungary 2028-2034"],
                        "material_fact_use": True,
                        "source_families": ["INTERREG", "CBC"],
                        "extract": ["calls", "future_programming_consultations"],
                    },
                    {
                        "id": "SRC-INTERREG-ROMD-2028-2034",
                        "tier": "T1",
                        "url": "https://ro-md.net/en/news-2021-2027/public-consultation-on-the-future-interreg-romania-moldova-chapter-2028-2034",
                        "programmes": ["Interreg Romania-Republic of Moldova 2028-2034"],
                        "material_fact_use": False,
                        "source_families": ["INTERREG", "CBC", "NEXT", "PROGRAMMING_PIPELINE"],
                        "extract": ["stakeholder_consultations", "programming_updates"],
                    },
                    {
                        "id": "SRC-INTERREG-ROHU-CALLS",
                        "tier": "T1",
                        "url": "https://interreg-rohu.eu/en/calls/",
                        "programmes": ["Interreg VI-A Romania-Hungary 2021-2027"],
                        "material_fact_use": True,
                        "source_families": ["INTERREG", "CBC"],
                        "extract": ["calls"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def main():
    with tempfile.TemporaryDirectory() as tmp:
        registry = Path(tmp) / "registry.json"
        _registry(registry)
        selected = live._programming_sources(live._load_registry(registry))
        assert [row["id"] for row in selected] == ["SRC-INTERREG-ROHU", "SRC-INTERREG-ROMD-2028-2034"]

        html = b"""<!doctype html><html><head><title>Programming 2027+</title></head>
        <body><h1>STAKEHOLDER SURVEY NOW OPEN</h1>
        <p>The preparation of the future Interreg Programme between Romania and Hungary
        for the 2028-2034 period has officially started.</p>
        <p>Stakeholder consultation survey open from 08.06.2026 to 01.08.2026.</p>
        <script>OPEN CALL fake javascript content</script></body></html>"""
        text = live._visible_text(html, "text/html; charset=utf-8")
        assert "STAKEHOLDER SURVEY NOW OPEN" in text
        assert "fake javascript" not in text

        # Registry T1 authority is per source, not any host on the broad T1 list.
        # www transport normalization is fine; off-programme redirects are not.
        live._assert_official_source_origin(
            "https://www.interreg-rohu.eu/ro/programare-2027/",
            "https://interreg-rohu.eu/ro/programare-2027/",
        )
        for requested, resolved in (
            ("https://interreg-rohu.eu/ro/", "https://ro-md.net/en/"),
            ("https://interreg-rohu.eu/ro/", "http://interreg-rohu.eu/ro/"),
            ("https://interreg-rohu.eu/ro/", "https://evil.invalid/ro/"),
            ("https://interreg-rohu.eu/ro/", "https://user@interreg-rohu.eu/ro/"),
            ("https://interreg-rohu.eu/ro/", "https://interreg-rohu.eu:444/ro/"),
        ):
            try:
                live._assert_official_source_origin(requested, resolved)
            except ValueError:
                pass
            else:
                raise AssertionError("registered Interreg origin must not change")

        # Every redirect hop must be checked *before* urllib follows it.
        # A hostile intermediate that redirects back to the original host
        # cannot be legitimized by an otherwise benign final response URL.
        from urllib.request import Request

        redirect = live._RegisteredOriginRedirect("https://interreg-rohu.eu/ro/")
        allowed = redirect.redirect_request(
            Request("https://interreg-rohu.eu/ro/"),
            None, 302, "Found", {},
            "https://www.interreg-rohu.eu/ro/consultation",
        )
        assert allowed.full_url == "https://www.interreg-rohu.eu/ro/consultation"
        for unsafe_hop in (
            "https://ro-md.net/en/",
            "https://evil.invalid/intermediate",
            "http://interreg-rohu.eu/ro/",
            "https://user@interreg-rohu.eu/ro/",
            "https://interreg-rohu.eu:444/ro/",
        ):
            try:
                redirect.redirect_request(
                    Request("https://interreg-rohu.eu/ro/"),
                    None, 302, "Found", {}, unsafe_hop,
                )
            except ValueError:
                pass
            else:
                raise AssertionError(f"untrusted redirect hop followed: {unsafe_hop}")
        try:
            redirect.redirect_request(
                Request("https://ro-md.net/en/off-programme-hop"),
                None, 302, "Found", {}, "https://interreg-rohu.eu/ro/",
            )
        except ValueError:
            pass
        else:
            raise AssertionError("trusted final URL masked an untrusted prior hop")

        # A successful status/HTML type alone cannot authorize raw receipt.
        # Exercise the actual transport without network dependencies.
        class RawResponse:
            def __init__(self, *, declared=None, encoding=None):
                self.headers = {"Content-Type": "text/html; charset=utf-8"}
                if declared is not None:
                    self.headers["Content-Length"] = str(declared)
                if encoding is not None:
                    self.headers["Content-Encoding"] = encoding

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def geturl(self):
                return "https://interreg-rohu.eu/en/"

            def getcode(self):
                return 200

            def read(self, limit):
                return html[:limit]

        class RawOpener:
            def __init__(self, response):
                self.response = response

            def open(self, request, timeout):
                return self.response

        original_build_opener = live.urllib.request.build_opener
        try:
            def fetch_raw_response(**kwargs):
                live.urllib.request.build_opener = lambda *_args, **_kw: RawOpener(RawResponse(**kwargs))
                return live._fetch("https://interreg-rohu.eu/en/")

            assert fetch_raw_response(declared=len(html))[0] == html
            assert fetch_raw_response(encoding="identity")[0] == html
            for kwargs, expected in (
                ({"encoding": "gzip"}, "unsupported encoded"),
                ({"encoding": "br"}, "unsupported encoded"),
                ({"declared": len(html) + 9}, "Content-Length"),
                ({"declared": len(html) - 1}, "Content-Length"),
                ({"declared": "invalid"}, "Content-Length"),
            ):
                try:
                    fetch_raw_response(**kwargs)
                except ValueError as exc:
                    assert expected in str(exc), (kwargs, exc)
                else:
                    raise AssertionError(f"unverified Interreg raw response accepted: {kwargs}")
        finally:
            live.urllib.request.build_opener = original_build_opener

        original_fetch = live._fetch
        original_now = live._utc_now
        try:
            live._fetch = lambda url: (html, url, 200, "text/html; charset=utf-8")
            live._utc_now = lambda: "2026-08-28T01:51:17Z"
            original_dir = Path(tmp) / "immutable-originals"
            envelope = live.build_live_evidence(registry, run_id="TEST-INTERREG-LIVE", raw_dir=original_dir)
        finally:
            live._fetch = original_fetch
            live._utc_now = original_now

        live.validate_envelope(envelope)
        assert live.replay_live_evidence(envelope, original_dir, registry) == 2
        for field, forged_value in (
            ("source_count", 3),
            ("fetch_pass", 1),
            ("fetch_fail", 1),
            ("observation_states", {"CONSULTATION": 2}),
        ):
            forged_summary = json.loads(json.dumps(envelope))
            forged_summary[field] = forged_value
            try:
                live.replay_live_evidence(forged_summary, original_dir, registry)
            except ValueError as exc:
                assert "summary differs" in str(exc)
            else:
                raise AssertionError(f"forged Interreg summary admitted: {field}")
        assert envelope["source_count"] == 2
        assert envelope["fetch_pass"] == 2
        assert envelope["fetch_fail"] == 0
        rows = {row["source_id"]: row for row in envelope["rows"]}
        row = rows["SRC-INTERREG-ROHU"]
        assert row["raw_hash"]
        normalized = row["normalized"]
        assert normalized["observation_state"] == "CONSULTATION_CLOSED", normalized
        assert normalized["stale_open_copy"] is True
        assert normalized["not_a_call"] is True
        assert normalized["open_call_authorized"] is False
        assert normalized["publish_authorized"] is False
        assert normalized["material_fact_use"] is False

        romd = rows["SRC-INTERREG-ROMD-2028-2034"]["normalized"]
        assert romd["programme_family"] == "Interreg Romania-Republic of Moldova 2028-2034"
        assert romd["not_a_call"] is True
        assert romd["open_call_authorized"] is False
        assert romd["publish_authorized"] is False
        assert romd["material_fact_use"] is False


        # The manifest/hash alone is not replayable provenance; the original
        # article bytes must exist and match the exact source registry.
        original = original_dir / "SRC-INTERREG-ROHU.raw.html"
        saved = original.read_bytes()
        original.write_bytes(saved.replace(b"STAKEHOLDER", b"COUNTERFEIT"))
        try:
            live.replay_live_evidence(envelope, original_dir, registry)
        except ValueError as exc:
            assert "SHA mismatch" in str(exc)
        else:
            raise AssertionError("tampered original must be rejected")
        original.write_bytes(saved)
        assert live.replay_live_evidence(envelope, original_dir, registry) == 2
        for key, value in (
            ("raw_hash", "0" * 64),
            ("raw_evidence_file", "../untrusted.html"),
            ("run_id", "forged-run"),
            ("registered_url", "https://example.invalid/mirror"),
        ):
            bad = json.loads(json.dumps(envelope))
            bad["rows"][0][key] = value
            try:
                live.replay_live_evidence(bad, original_dir, registry)
            except ValueError:
                pass
            else:
                raise AssertionError(f"forged raw manifest admitted: {key}")
        bad = json.loads(json.dumps(envelope))
        bad["rows"][0]["normalized"]["observation_state"] = "PLANNED"
        try:
            live.replay_live_evidence(bad, original_dir, registry)
        except ValueError:
            pass
        else:
            raise AssertionError("semantic state detached from original raw bytes")
        # Even a re-normalized receipt backed by the same original HTML must
        # fail if its final URL is a *different* official Interreg authority.
        forged = json.loads(json.dumps(envelope))
        forged_row = next(row for row in forged["rows"] if row["source_id"] == "SRC-INTERREG-ROHU")
        forged_row["final_url"] = "https://ro-md.net/en/"
        forged_row["normalized"] = live.normalize_programming_observation(
            {
                "programme": forged_row["programme"],
                "title": forged_row["source_owner"],
                "text": live._visible_text(saved, forged_row["content_type"]),
                "authority_url": forged_row["final_url"],
            },
            fetched_at=forged_row["fetched_at"],
            raw_hash=forged_row["raw_hash"],
            run_id=forged_row["run_id"],
        )
        live.validate_envelope(forged)
        try:
            live.replay_live_evidence(forged, original_dir, registry)
        except ValueError as exc:
            assert "crossed registered official source origin" in str(exc)
        else:
            raise AssertionError("cross-programme official redirect must fail replay")

        extra = original_dir / "unclaimed.raw.html"
        extra.write_bytes(saved)
        try:
            live.replay_live_evidence(envelope, original_dir, registry)
        except ValueError as exc:
            assert "orphaned" in str(exc)
        else:
            raise AssertionError("unclaimed raw file admitted")
        extra.unlink()
        assert live.replay_live_evidence(envelope, original_dir, registry) == 2
        try:
            live.build_live_evidence(registry, run_id="second-run", raw_dir=original_dir)
        except ValueError as exc:
            assert "already exists" in str(exc)
        else:
            raise AssertionError("immutable raw directory overwritten")

        unsafe = json.loads(json.dumps(envelope))
        unsafe["rows"][0]["normalized"]["open_call_authorized"] = True
        try:
            live.validate_envelope(unsafe)
        except ValueError as exc:
            assert "authorized OPEN" in str(exc)
        else:
            raise AssertionError("unsafe programming envelope must fail closed")

        # A live 403/timeout must remain a genuine non-authorizing failure,
        # with self-consistent summary counts; no phantom raw file is allowed.
        def partial_fetch(url):
            if "ro-md.net" in url:
                raise TimeoutError("official source temporarily unavailable")
            return html, url, 200, "text/html; charset=utf-8"

        partial_dir = Path(tmp) / "partial-originals"
        try:
            live._fetch = partial_fetch
            live._utc_now = lambda: "2026-08-28T01:51:17Z"
            partial = live.build_live_evidence(registry, run_id="TEST-INTERREG-PARTIAL", raw_dir=partial_dir)
        finally:
            live._fetch = original_fetch
            live._utc_now = original_now
        assert partial["fetch_pass"] == 1 and partial["fetch_fail"] == 1
        assert partial["observation_states"] == {"CONSULTATION_CLOSED": 1, "FETCH_FAILED": 1}
        assert live.replay_live_evidence(partial, partial_dir, registry) == 1
        for tamper in ("raw_hash", "final_url", "bytes"):
            downgraded = json.loads(json.dumps(partial))
            failed_row = next(r for r in downgraded["rows"] if r["fetch_status"] == "FAIL")
            failed_row[tamper] = "forged evidence"
            try:
                live.replay_live_evidence(downgraded, partial_dir, registry)
            except ValueError as exc:
                assert "cannot have promoted original" in str(exc)
            else:
                raise AssertionError(f"failed source concealed PASS field: {tamper}")
        for missing_error in ("error", "error_type"):
            downgraded = json.loads(json.dumps(partial))
            failed_row = next(r for r in downgraded["rows"] if r["fetch_status"] == "FAIL")
            failed_row.pop(missing_error)
            try:
                live.replay_live_evidence(downgraded, partial_dir, registry)
            except ValueError as exc:
                assert "missing explicit error receipt" in str(exc)
            else:
                raise AssertionError(f"failed source lost error provenance: {missing_error}")

    print("PASS Interreg live programming evidence: exact official bytes remain non-authorizing")


if __name__ == "__main__":
    main()
