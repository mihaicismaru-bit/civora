from __future__ import annotations

import base64
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

INGEST_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(INGEST_DIR))

import mipe_ingest_v2 as ingest  # noqa: E402
from mipe_core_v2 import (  # noqa: E402
    build_page_item,
    classify_event,
    extract_html_document,
    in_pdds_scope,
    iso_z,
    merge_feed_items,
    normalize_url,
    now_utc,
    parse_feed_js,
    render_feed_js,
    sign_snapshot,
    validate_item,
    verify_snapshot,
)


class URLPolicyTests(unittest.TestCase):
    def test_normalizes_only_reviewed_official_hosts(self) -> None:
        self.assertEqual(
            normalize_url("http://MFE.GOV.RO//pdds/noutati?utm_source=x&b=2&a=1#frag"),
            "https://mfe.gov.ro/pdds/noutati/?a=1&b=2",
        )
        self.assertIsNone(normalize_url("https://example.com/mfe.gov.ro/pdds/"))

    def test_priority_scope_is_strict(self) -> None:
        self.assertTrue(in_pdds_scope("https://mfe.gov.ro/pdds/noutati/"))
        self.assertFalse(in_pdds_scope("https://mfe.gov.ro/peo/noutati/"))
        self.assertFalse(in_pdds_scope("https://reporting.mysmis2021.gov.ro/pdds/"))


class ClassificationTests(unittest.TestCase):
    def test_generic_call_never_implies_open(self) -> None:
        kind, evidence = classify_event(
            "Apel de proiecte pentru infrastructură",
            "Programul are un buget important.",
            "Ghidul prezintă condițiile generale.",
        )
        self.assertEqual(kind, "OFFICIAL_UPDATE")
        self.assertIn("generic call wording; OPEN intentionally not inferred", evidence)

    def test_explicit_open_needs_launch_submission_and_date(self) -> None:
        kind, evidence = classify_event(
            "MIPE lansează apelul pentru investiții",
            "Perioada de depunere începe la 12 august 2026.",
            "Cererile se pot depune până la data de 30 septembrie 2026, ora 16:00.",
        )
        self.assertEqual(kind, "CALL_OPENED")
        self.assertIn("explicit date", evidence)

    def test_consultation_without_deadline_is_not_opened(self) -> None:
        kind, _ = classify_event(
            "Consultare publică pentru ghid",
            "MIPE publică documentul spre observații.",
            "Termenul va fi comunicat ulterior.",
        )
        self.assertEqual(kind, "OFFICIAL_UPDATE")


class PagePublicationTests(unittest.TestCase):
    @staticmethod
    def document() -> dict:
        raw = b"""<!doctype html><html><head>
        <title>MIPE lanseaza apelul PDDS</title>
        <link rel='canonical' href='https://mfe.gov.ro/pdds/apel-test/'>
        <meta property='article:published_time' content='2026-08-12T08:00:00Z'>
        </head><body><h1>MIPE lanseaza apelul PDDS</h1>
        <p>Perioada de depunere a cererilor incepe la 12 august 2026 si se incheie la 30 septembrie 2026, ora 16:00.</p>
        <p>Buget pentru beneficiari si proiecte de investitii.</p></body></html>"""
        return extract_html_document(raw, "https://mfe.gov.ro/pdds/apel-test/", {})

    def test_verified_page_can_publish_open(self) -> None:
        item = build_page_item(
            self.document(), fetched_at="2026-08-12T10:00:00Z",
            transport="curl-verified-tls", http_status=200, change_type="NEW",
            discovery={"scope": "PDDS"},
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["status"], "OPEN")
        self.assertTrue(validate_item(item))

    def test_open_without_required_evidence_is_rejected(self) -> None:
        item = build_page_item(
            self.document(), fetched_at="2026-08-12T10:00:00Z",
            transport="curl-verified-tls", http_status=200, change_type="NEW",
        )
        assert item is not None
        item["evidence"] = ["generic call wording"]
        self.assertFalse(validate_item(item))


class RegistryParserTests(unittest.TestCase):
    @staticmethod
    def registry_html(states: tuple[str, str] = ("IN PREGATIRE", "FINALIZAT")) -> bytes:
        return f"""<!doctype html><html><body>
        <table id='APELURI_data_panel'>
          <tr><th>Program operațional</th><th>Tip apel</th><th>Apel</th><th>Stare apel</th><th>Buget nerambursabil apel</th><th>Info</th></tr>
          <tr><td>Program Dezvoltare Durabilă</td><td>Competitiv</td><td>Investiții apă curată</td><td>{states[0]}</td><td>100000000</td><td><a href='/ords/repo_bo/r/mysmis-2021/apel/101'><span class='icon'></span></a></td></tr>
          <tr><td>Program Educație și Ocupare</td><td>Competitiv</td><td>Competențe pentru viitor</td><td>{states[1]}</td><td>25000000</td><td><a href='/ords/repo_bo/r/mysmis-2021/apel/102'><span class='icon'></span></a></td></tr>
        </table>
        <div class='a-IRR-pagination-label'>1 - 2 of 2</div>
        </body></html>""".encode("utf-8")

    def test_parses_complete_registry_and_icon_links(self) -> None:
        parsed = ingest.parse_registry_html(self.registry_html())
        self.assertTrue(parsed["complete"])
        self.assertEqual(parsed["total"], 2)
        self.assertEqual(len(parsed["rows"]), 2)
        self.assertEqual(
            parsed["rows"][0]["infoUrl"],
            "https://reporting.mysmis2021.gov.ro/ords/repo_bo/r/mysmis-2021/apel/101/",
        )

    def test_partial_registry_cannot_create_baseline(self) -> None:
        parsed = ingest.parse_registry_html(self.registry_html())
        parsed.update({"complete": False, "tlsVerified": True, "url": ingest.MYSMIS_REGISTRY_URL})
        state = {"registryRows": {}}
        items, summary, material = ingest.process_registry(parsed, state, "2026-08-12T10:00:00Z")
        self.assertEqual(items, [])
        self.assertFalse(summary["complete"])
        self.assertFalse(material)
        self.assertEqual(state["registryRows"], {})

    def test_complete_first_snapshot_is_baseline_only(self) -> None:
        parsed = ingest.parse_registry_html(self.registry_html())
        parsed.update({
            "tlsVerified": True, "url": ingest.MYSMIS_REGISTRY_URL,
            "transport": "playwright-verified-tls", "httpStatus": 200,
            "fetchedAt": "2026-08-12T10:00:00Z",
        })
        state = {"registryRows": {}}
        items, summary, material = ingest.process_registry(parsed, state, "2026-08-12T10:00:00Z")
        self.assertEqual(items, [])
        self.assertTrue(summary["baselineCreated"])
        self.assertTrue(material)
        self.assertEqual(len(state["registryRows"]), 2)

    def test_exact_structured_state_change_publishes_open(self) -> None:
        initial = ingest.parse_registry_html(self.registry_html())
        initial.update({
            "tlsVerified": True, "url": ingest.MYSMIS_REGISTRY_URL,
            "transport": "playwright-verified-tls", "httpStatus": 200,
            "fetchedAt": "2026-08-12T10:00:00Z",
        })
        state = {"registryRows": {}}
        ingest.process_registry(initial, state, "2026-08-12T10:00:00Z")

        changed = ingest.parse_registry_html(self.registry_html(("DESCHIS", "FINALIZAT")))
        changed.update({
            "tlsVerified": True, "url": ingest.MYSMIS_REGISTRY_URL,
            "transport": "playwright-verified-tls", "httpStatus": 200,
            "fetchedAt": "2026-08-12T11:00:00Z",
        })
        items, summary, material = ingest.process_registry(changed, state, "2026-08-12T11:00:00Z")
        self.assertTrue(material)
        self.assertEqual(summary["changedRows"], 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "CALL_OPENED")
        self.assertEqual(items[0]["status"], "OPEN")
        self.assertTrue(validate_item(items[0]))

    def test_multiple_registry_entities_survive_feed_merge(self) -> None:
        registry = {
            "url": ingest.MYSMIS_REGISTRY_URL, "transport": "playwright-verified-tls",
            "httpStatus": 200, "tlsVerified": True, "fetchedAt": "2026-08-12T11:00:00Z",
            "rawSha256": "a" * 64,
        }
        previous_a = {"id": "a", "program": "PDDS", "callName": "Apel investiții A", "state": "IN PREGATIRE"}
        current_a = dict(previous_a, state="DESCHIS")
        previous_b = {"id": "b", "program": "PEO", "callName": "Apel competențe B", "state": "IN PREGATIRE"}
        current_b = dict(previous_b, state="DESCHIS")
        first = ingest.registry_item(current_a, previous_a, "2026-08-12T11:00:00Z", registry, "CHANGED")
        second = ingest.registry_item(current_b, previous_b, "2026-08-12T11:00:01Z", registry, "CHANGED")
        self.assertEqual(len(merge_feed_items([], [first, second])), 2)


class RelayTests(unittest.TestCase):
    def test_signed_snapshot_must_keep_body_hash_and_signature(self) -> None:
        secret = "unit-test-secret"
        body = b"<html><title>Official</title></html>"
        snapshot = {
            "url": "https://mfe.gov.ro/pdds/test/",
            "finalUrl": "https://mfe.gov.ro/pdds/test/",
            "fetchedAt": iso_z(now_utc()),
            "httpStatus": 200,
            "tlsVerified": True,
            "contentType": "text/html",
            "bodyBase64": base64.b64encode(body).decode("ascii"),
            "bodySha256": hashlib.sha256(body).hexdigest(),
            "signatureAlgorithm": "HMAC-SHA256",
        }
        snapshot["signature"] = sign_snapshot(snapshot, secret)
        ok, reason, decoded = verify_snapshot(snapshot, secret)
        self.assertTrue(ok, reason)
        self.assertEqual(decoded, body)
        snapshot["httpStatus"] = 500
        ok, _, _ = verify_snapshot(snapshot, secret)
        self.assertFalse(ok)


class FailClosedIntegrationTests(unittest.TestCase):
    def test_total_source_failure_preserves_feed_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_dir = root / "state"
            state_dir.mkdir()
            web_dir = root / "web"
            web_dir.mkdir()
            feed_path = web_dir / "mipe-news.js"
            original = render_feed_js(
                {
                    "pipelineVersion": 2,
                    "status": "OK_NO_NEW_RELEVANT_ITEMS",
                    "prioritySeedAvailable": True,
                    "mysmisRegistryAvailable": True,
                    "mysmisRegistryComplete": True,
                    "itemCount": 0,
                    "provenancePolicy": "verified",
                },
                [],
            )
            feed_path.write_text(original, encoding="utf-8")
            failure = {
                "observations": [], "registry": None, "attemptedCount": 1,
                "sourceStates": [{
                    "url": ingest.PRIORITY_PDDS_SEED, "ok": False,
                    "failureClass": "CONNECT_TIMEOUT", "error": "timeout",
                }],
            }
            empty_relay = {"observations": [], "registry": None, "sourceStates": []}
            with (
                patch.object(ingest, "STATE_DIR", state_dir),
                patch.object(ingest, "STATE_PATH", state_dir / "mipe_state_v2.json"),
                patch.object(ingest, "HEALTH_PATH", state_dir / "mipe_health.json"),
                patch.object(ingest, "DISCOVERY_PATH", state_dir / "mipe_discovered_urls.json"),
                patch.object(ingest, "FEED_PATH", feed_path),
                patch.object(ingest, "load_candidates", return_value=[]),
                patch.object(ingest, "search_discover", return_value=([], [])),
                patch.object(ingest, "persist_discoveries", return_value=False),
                patch.object(ingest, "direct_collect", return_value=failure),
                patch.object(ingest, "relay_collect", return_value=empty_relay),
            ):
                result = ingest.run(enable_browser=False)
            self.assertEqual(result["status"], "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED")
            self.assertFalse(result["feedChanged"])
            self.assertEqual(feed_path.read_text(encoding="utf-8"), original)

    def test_feed_javascript_round_trip(self) -> None:
        text = render_feed_js({"status": "OK"}, [])
        meta, items = parse_feed_js(text)
        self.assertEqual(meta["status"], "OK")
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
