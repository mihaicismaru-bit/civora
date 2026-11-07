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
                        "owner": "Interreg Romania-Hungary Joint Secretariat",
                        "tier": "T1",
                        "url": "https://interreg-rohu.eu/en/",
                        "programmes": ["Interreg Romania-Hungary 2028-2034"],
                        "material_fact_use": True,
                        "source_families": ["INTERREG", "CBC"],
                        "extract": ["calls", "future_programming_consultations"],
                    },
                    {
                        "id": "SRC-INTERREG-ROMD-2028-2034",
                        "owner": "Interreg Romania-Moldova Joint Secretariat",
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

        # Every original must map to exactly one canonical registry entry.
        # Duplicate IDs previously survived selection and could collapse the
        # replay lookup dictionary, or collide on one immutable .raw.html name.
        # Broken metadata must fail before fetch, not silently shrink coverage.
        registry_baseline = json.loads(registry.read_text(encoding="utf-8"))
        malformed_cases = (
            ("duplicate", "duplicate Interreg registry source_id",
             lambda sources: sources.append(dict(sources[1], id=sources[0]["id"]))),
            ("missing id", "missing or unsafe Interreg registry source_id",
             lambda sources: sources[0].pop("id")),
            ("unsafe id", "missing or unsafe Interreg registry source_id",
             lambda sources: sources[0].update(id="../shadow")),
            ("family string", "invalid Interreg registry source_families",
             lambda sources: sources[0].update(source_families="INTERREG")),
            ("extract string", "invalid Interreg registry extract",
             lambda sources: sources[0].update(extract="future_programming_consultations")),
            ("missing programme", "invalid Interreg programming programme",
             lambda sources: sources[0].update(programmes=[])),
            ("missing owner", "missing Interreg programming source owner",
             lambda sources: sources[0].update(owner="")),
            ("off-authority URL", "untrusted Interreg source/redirect URL",
             lambda sources: sources[0].update(url="https://example.invalid/false-official")),
        )
        bad_registry = Path(tmp) / "malformed-registry.json"
        for label, expected, mutate in malformed_cases:
            source_copy = json.loads(json.dumps(registry_baseline["sources"]))
            mutate(source_copy)
            bad_registry.write_text(json.dumps({"sources": source_copy}), encoding="utf-8")
            try:
                live._programming_sources(live._load_registry(bad_registry))
            except ValueError as exc:
                assert expected in str(exc), (label, exc)
            else:
                raise AssertionError(f"unverified Interreg registry admitted: {label}")

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
            capture_times = iter((
                "2026-08-28T01:51:17Z",  # run started
                "2026-08-28T01:51:19Z",  # first original fetched
                "2026-08-28T01:51:23Z",  # second original fetched
                "2026-08-28T01:51:24Z",  # receipt finalized
            ))
            live._utc_now = lambda: next(capture_times)
            original_dir = Path(tmp) / "immutable-originals"
            envelope = live.build_live_evidence(registry, run_id="TEST-INTERREG-LIVE", raw_dir=original_dir)
        finally:
            live._fetch = original_fetch
            live._utc_now = original_now

        live.validate_envelope(envelope)
        assert envelope["created_at"] == "2026-08-28T01:51:24Z"
        assert [row["fetched_at"] for row in envelope["rows"]] == [
            "2026-08-28T01:51:19Z", "2026-08-28T01:51:23Z"
        ], "per-source acquisition must not inherit a stale run-start timestamp"
        assert live.replay_live_evidence(envelope, original_dir, registry) == 2
        # A forged completion time or an out-of-order/stale source timestamp
        # cannot survive raw replay, even if all source hashes are unchanged.
        for index, forged_time, expected in (
            (0, "2026-08-28T01:51:25Z", "chronology"),
            (1, "2026-08-28T01:51:18Z", "chronology"),
            (0, "2026-08-28T02:51:19+01:00", "UTC receipt timestamp"),
            (0, "", "UTC receipt timestamp"),
        ):
            tampered = json.loads(json.dumps(envelope))
            tampered["rows"][index]["fetched_at"] = forged_time
            try:
                live.replay_live_evidence(tampered, original_dir, registry)
            except ValueError as exc:
                assert expected in str(exc), (index, forged_time, exc)
            else:
                raise AssertionError(f"tampered Interreg source time admitted: {forged_time}")
        tampered = json.loads(json.dumps(envelope))
        tampered["created_at"] = "2026-08-28T01:51:22Z"
        try:
            live.replay_live_evidence(tampered, original_dir, registry)
        except ValueError as exc:
            assert "chronology" in str(exc), exc
        else:
            raise AssertionError("backdated Interreg manifest completion admitted")
        # A symlinked directory may hide substituted original files even when
        # every child path appears to be a regular file. Reject at the root.
        linked_dir = Path(tmp) / "redirected-originals"
        linked_dir.symlink_to(original_dir, target_is_directory=True)
        try:
            live.replay_live_evidence(envelope, linked_dir, registry)
        except ValueError as exc:
            assert "symlinked" in str(exc), exc
        else:
            raise AssertionError("symlinked Interreg evidence root admitted")
        linked_dir.unlink()

        # Neither an unknown top-level field nor a forged row-level claim can
        # bypass the non-authorizing source-to-programming boundary.
        for field, value in (
            ("open_call_status", "OPEN_CALL"),
            ("deadline_authorized", True),
            ("eligibility_authorized", True),
        ):
            for location in ("envelope", "row"):
                forged = json.loads(json.dumps(envelope))
                target = forged if location == "envelope" else forged["rows"][0]
                target[field] = value
                try:
                    live.replay_live_evidence(forged, original_dir, registry)
                except ValueError as exc:
                    assert "keys" in str(exc), (field, location, exc)
                else:
                    raise AssertionError(f"forged Interreg authority accepted: {field}/{location}")
        attempted_publish = json.loads(json.dumps(envelope))
        attempted_publish["rows"][0]["publication_effect"] = "PUBLISH"
        try:
            live.validate_envelope(attempted_publish)
        except ValueError as exc:
            assert "attempted publication" in str(exc)
        else:
            raise AssertionError("row-level Interreg publication override admitted")

        # json.loads normally accepts the last duplicate key; neither a raw
        # receipt nor the source registry may use that ambiguous representation.
        for duplicate in (
            '{"run_id":"official","run_id":"forged"}',
            '{"nested":{"open_call_status":"PLANNED","open_call_status":"OPEN_CALL"}}',
        ):
            try:
                live._load_strict_json(duplicate)
            except ValueError as exc:
                assert "duplicate Interreg JSON key" in str(exc)
            else:
                raise AssertionError("duplicate-key Interreg receipt admitted")
        # Python's permissive json.loads accepts NaN/Infinity by default.
        # These are not valid immutable evidence values at any nesting level.
        for nonfinite in ("NaN", "Infinity", "-Infinity"):
            for forged_json in (
                '{"source_count":' + nonfinite + '}',
                '{"rows":[{"normalized":{"confidence":' + nonfinite + '}}]}',
            ):
                try:
                    live._load_strict_json(forged_json)
                except ValueError as exc:
                    assert "non-finite Interreg JSON number" in str(exc), exc
                else:
                    raise AssertionError("non-finite Interreg receipt admitted")

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
            partial_times = iter((
                "2026-08-28T01:51:17Z",  # run start
                "2026-08-28T01:51:19Z",  # first source succeeds
                "2026-08-28T01:52:00Z",  # second source times out
                "2026-08-28T01:52:01Z",  # manifest completed
            ))
            live._utc_now = lambda: next(partial_times)
            partial = live.build_live_evidence(registry, run_id="TEST-INTERREG-PARTIAL", raw_dir=partial_dir)
        finally:
            live._fetch = original_fetch
            live._utc_now = original_now
        assert partial["fetch_pass"] == 1 and partial["fetch_fail"] == 1
        assert [row["fetched_at"] for row in partial["rows"]] == [
            "2026-08-28T01:51:19Z", "2026-08-28T01:52:00Z"
        ], "failed Interreg acquisition must carry its own failure-observed time"
        assert partial["observation_states"] == {"CONSULTATION_CLOSED": 1, "FETCH_FAILED": 1}
        assert live.replay_live_evidence(partial, partial_dir, registry) == 1
        for tamper in ("raw_hash", "final_url", "bytes"):
            downgraded = json.loads(json.dumps(partial))
            failed_row = next(r for r in downgraded["rows"] if r["fetch_status"] == "FAIL")
            failed_row[tamper] = "forged evidence"
            try:
                live.replay_live_evidence(downgraded, partial_dir, registry)
            except ValueError as exc:
                assert ("unexpected Interreg source row keys" in str(exc)
                        or "cannot have promoted original" in str(exc))
            else:
                raise AssertionError(f"failed source concealed PASS field: {tamper}")
        for missing_error in ("error", "error_type"):
            downgraded = json.loads(json.dumps(partial))
            failed_row = next(r for r in downgraded["rows"] if r["fetch_status"] == "FAIL")
            failed_row.pop(missing_error)
            try:
                live.replay_live_evidence(downgraded, partial_dir, registry)
            except ValueError as exc:
                assert ("unexpected Interreg source row keys" in str(exc)
                        or "missing explicit error receipt" in str(exc))
            else:
                raise AssertionError(f"failed source lost error provenance: {missing_error}")

    # A generic 200 HTML page on the right host must not impersonate the
    # exact 16 October 2026 ROHU 2028-2034 workshops announcement.
    with tempfile.TemporaryDirectory() as workshop_tmp:
        workshop_root = Path(workshop_tmp)
        article_id = live.WORKSHOPS_SOURCE_ID
        article_url = (
            "https://interreg-rohu.eu/ro/participati-la-atelierele-transfrontaliere-"
            "si-contribuiti-la-definirea-capitolului-interreg-2028-2034/"
        )
        article_text = (
            "Participați la atelierele transfrontaliere pentru Capitolul Interreg 2028-2034. "
            "Atelier la 17 noiembrie 2026 Debrecen și la 20 noiembrie 2026 online. "
            "Înscrierea s-a încheiat pe 28 octombrie 2026. "
            "Aceste evenimente țin doar de programarea viitoare, nu de apeluri deschise."
        )
        article_html = ("<html><body><h1>" + article_text + "</h1></body></html>").encode("utf-8")
        article_registry = workshop_root / "registry.json"
        article_registry.write_text(json.dumps({"sources": [{
            "id": article_id,
            "owner": "Interreg ROHU Official",
            "url": article_url,
            "programmes": ["Interreg Romania-Hungary 2028-2034"],
            "source_families": ["INTERREG", "CBC", "PROGRAMMING_PIPELINE"],
            "extract": ["consultation_events"],
            "material_fact_use": False,
        }]}), encoding="utf-8")
        live._assert_registered_article_identity(article_id, article_url, article_url, article_text)

        # A generic 200 page must not borrow its workshop identity from
        # non-visible head/template/hidden markup, even on the exact URL.
        decoy_html = None
        for opening, closing in (
            ("<head>", "</head>"),
            ("<template>", "</template>"),
            ("<div hidden>", "</div>"),
            ("<section aria-hidden='true'>", "</section>"),
            ("<div style='display: none'>", "</div>"),
            ("<section style='visibility: hidden'>", "</section>"),
            ("<div inert>", "</div>"),
            ("<svg>", "</svg>"),
            ("<dialog>", "</dialog>"),
            ("<datalist>", "</datalist>"),
            ("<select><option>", "</option></select>"),
            ("<textarea>", "</textarea>"),
            ("<canvas>", "</canvas>"),
            ("<iframe>", "</iframe>"),
            ("<details><summary>More information</summary>", "</details>"),
            ("<p style='content-visibility: hidden'>", "</p>"),
        ):
            decoy_html = (
                "<html><body><main><p>" + "Generic index without a workshop. " * 8
                + "</p>" + opening + "<p><span>" + article_text
                + "</span></p>" + closing + "<p>Index footer</p></main></body></html>"
            ).encode("utf-8")
            extracted = live._visible_text(decoy_html, "text/html; charset=utf-8")
            assert "17 noiembrie 2026" not in extracted, (opening, extracted)
            assert "Index footer" in extracted, opening
            try:
                live._assert_registered_article_identity(article_id, article_url, article_url, extracted)
            except ValueError as exc:
                assert "identity/schedule unverified" in str(exc), (opening, exc)
            else:
                raise AssertionError(f"hidden workshop terms accepted: {opening}")

        # An explicitly opened details panel is readable; closing it cannot
        # launder identity terms, while neighbouring visible text survives.
        open_details = ("<html><body><details open><p>" + article_text
                        + "</p></details><p>Visible footer</p></body></html>").encode("utf-8")
        open_text = live._visible_text(open_details, "text/html; charset=utf-8")
        assert "17 noiembrie 2026" in open_text and "Visible footer" in open_text
        live._assert_registered_article_identity(article_id, article_url, article_url, open_text)

        # Exercise the acquisition and immutable replay boundary, not just
        # the HTML parser in isolation. A failed decoy has no promoted raw.
        hidden_raw = (
            "<html><body>" + "Generic programme index. " * 10
            + "<div hidden><span>" + article_text
            + "</span></div></body></html>"
        ).encode("utf-8")
        hidden_dir = workshop_root / "hidden-decoy-originals"
        saved_fetch = live._fetch
        try:
            live._fetch = lambda url: (hidden_raw, url, 200, "text/html; charset=utf-8")
            rejected = live.build_live_evidence(
                article_registry, run_id="TEST-HIDDEN-IDENTITY", raw_dir=hidden_dir
            )
        finally:
            live._fetch = saved_fetch
        assert rejected["fetch_pass"] == 0 and rejected["fetch_fail"] == 1
        assert "identity/schedule unverified" in rejected["rows"][0]["error"]
        assert live.replay_live_evidence(rejected, hidden_dir, article_registry) == 0

        for wrong_url, wrong_text in (
            ("https://interreg-rohu.eu/ro/", article_text),
            (article_url, article_text.replace("17 noiembrie", "16 noiembrie")),
            (article_url, "Atelierele Interreg 2028-2034 programare viitoare"),
        ):
            try:
                live._assert_registered_article_identity(article_id, article_url, wrong_url, wrong_text)
            except ValueError as exc:
                assert "workshop" in str(exc).lower()
            else:
                raise AssertionError("wrong official workshop page or schedule admitted")

        previous_fetch, previous_now = live._fetch, live._utc_now
        original_dir = workshop_root / "originals"
        try:
            live._fetch = lambda url: (article_html, url, 200, "text/html; charset=utf-8")
            live._utc_now = lambda: "2026-11-06T23:34:07Z"
            capture = live.build_live_evidence(
                article_registry, run_id="TEST-ROHU-WORKSHOPS", raw_dir=original_dir
            )
        finally:
            live._fetch, live._utc_now = previous_fetch, previous_now
        assert capture["fetch_pass"] == 1 and capture["fetch_fail"] == 0
        assert capture["rows"][0]["normalized"]["open_call_authorized"] is False
        assert live.replay_live_evidence(capture, original_dir, article_registry) == 1

        # Even a fully rehashed and re-normalized forged article without the
        # verified schedule must fail raw-to-semantic replay.
        bad_html = article_html.replace(b"17 noiembrie 2026", b"16 noiembrie 2026")
        original_file = original_dir / (article_id + ".raw.html")
        original_file.write_bytes(bad_html)
        forged = json.loads(json.dumps(capture))
        forged_row = forged["rows"][0]
        forged_row["raw_hash"] = live._sha256(bad_html)
        forged_row["bytes"] = len(bad_html)
        forged_row["normalized"] = live.normalize_programming_observation({
            "programme": forged_row["programme"],
            "title": forged_row["source_owner"],
            "text": live._visible_text(bad_html, forged_row["content_type"]),
            "authority_url": article_url,
        }, fetched_at=forged_row["fetched_at"],
           raw_hash=forged_row["raw_hash"], run_id=forged_row["run_id"])
        try:
            live.replay_live_evidence(forged, original_dir, article_registry)
        except ValueError as exc:
            assert "identity/schedule unverified" in str(exc), exc
        else:
            raise AssertionError("rehashed wrong ROHU workshop schedule admitted")
        original_file.write_bytes(article_html)
        assert live.replay_live_evidence(capture, original_dir, article_registry) == 1

    # The official October-November ROHU survey is a FUTURE-PROGRAMMING
    # consultation. A homepage, changed date or forged raw receipt cannot
    # impersonate its exact official article even with a valid source hash.
    with tempfile.TemporaryDirectory() as survey_tmp:
        survey_root = Path(survey_tmp)
        survey_id = live.ROHU_SURVEY_SOURCE_ID
        survey_url = (
            "https://interreg-rohu.eu/ro/"
            "contribuiti-la-definirea-viitorului-cooperarii-transfrontaliere/"
        )
        survey_text = (
            "Contribuiți la definirea viitorului cooperării transfrontaliere. "
            "Pregătirea Capitolului Interreg pentru 2028–2034 și Analiza Teritorială. "
            "Vă invităm să completați sondajul online privind cooperarea. "
            "Sondajul este deschis în perioada 5 octombrie – 30 noiembrie 2026. "
            "Acesta este un proces de programare, nu un apel deschis."
        )
        survey_html = ("<html><body><h1>" + survey_text + "</h1></body></html>").encode("utf-8")
        survey_registry = survey_root / "registry.json"
        survey_registry.write_text(json.dumps({"sources": [{
            "id": survey_id,
            "owner": "Interreg ROHU Official",
            "url": survey_url,
            "programmes": ["Interreg Romania-Hungary 2028-2034"],
            "source_families": ["INTERREG", "CBC", "PROGRAMMING_PIPELINE"],
            "extract": ["stakeholder_consultations", "programming_updates"],
            "material_fact_use": False,
        }]}), encoding="utf-8")
        live._assert_registered_article_identity(survey_id, survey_url, survey_url, survey_text)
        for wrong_url, wrong_text in (
            ("https://interreg-rohu.eu/ro/", survey_text),
            (survey_url + "?fallback=1", survey_text),
            (survey_url, survey_text.replace("30 noiembrie 2026", "29 noiembrie 2026")),
            (survey_url, "Programare Interreg 2028-2034 actualizare generica " * 5),
        ):
            try:
                live._assert_registered_article_identity(survey_id, survey_url, wrong_url, wrong_text)
            except ValueError as exc:
                assert "survey" in str(exc).lower(), exc
            else:
                raise AssertionError("wrong ROHU survey endpoint/schedule admitted")

        previous_fetch, previous_now = live._fetch, live._utc_now
        originals = survey_root / "originals"
        try:
            live._fetch = lambda url: (survey_html, url, 200, "text/html; charset=utf-8")
            live._utc_now = lambda: "2026-11-07T01:20:00Z"
            receipt = live.build_live_evidence(
                survey_registry, run_id="TEST-ROHU-SURVEY", raw_dir=originals
            )
        finally:
            live._fetch, live._utc_now = previous_fetch, previous_now
        assert receipt["fetch_pass"] == 1 and receipt["fetch_fail"] == 0
        observation = receipt["rows"][0]["normalized"]
        assert observation["observation_state"] == "CONSULTATION"
        assert observation["not_a_call"] is True
        assert observation["open_call_authorized"] is False
        assert observation["publish_authorized"] is False
        assert live.replay_live_evidence(receipt, originals, survey_registry) == 1

        # A new semantic hash and matching SHA cannot legitimate a forged
        # survey end date: identity is checked independently of both hashes.
        altered = survey_html.replace(b"30 noiembrie 2026", b"29 noiembrie 2026")
        raw_path = originals / (survey_id + ".raw.html")
        raw_path.write_bytes(altered)
        forged = json.loads(json.dumps(receipt))
        row = forged["rows"][0]
        row["raw_hash"] = live._sha256(altered)
        row["bytes"] = len(altered)
        row["normalized"] = live.normalize_programming_observation({
            "programme": row["programme"],
            "title": row["source_owner"],
            "text": live._visible_text(altered, row["content_type"]),
            "authority_url": survey_url,
        }, fetched_at=row["fetched_at"], raw_hash=row["raw_hash"], run_id=row["run_id"])
        try:
            live.replay_live_evidence(forged, originals, survey_registry)
        except ValueError as exc:
            assert "survey official article identity/schedule unverified" in str(exc), exc
        else:
            raise AssertionError("rehashed false ROHU survey deadline admitted")
        raw_path.write_bytes(survey_html)
        assert live.replay_live_evidence(receipt, originals, survey_registry) == 1

    print("PASS Interreg live programming evidence: exact official bytes remain non-authorizing")


if __name__ == "__main__":
    main()
