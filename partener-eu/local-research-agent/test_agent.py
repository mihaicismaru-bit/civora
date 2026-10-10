import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("partener_local_agent", HERE / "agent.py")
agent = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(agent)


class LocalResearchAgentTests(unittest.TestCase):
    def test_source_registry_is_https_and_non_authorizing(self):
        registry = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(registry["sources"]), 20)
        for source in registry["sources"]:
            agent.validate_source(source)
            self.assertNotIn(source.get("observation_state"), {"OPEN_CALL", "CLOSED_CALL"})
            self.assertTrue(source["url"].startswith("https://"))

    def test_http_source_rejected(self):
        source = {
            "source_id": "TEST_SOURCE",
            "url": "http://example.com/",
            "allow_hosts": ["example.com"],
            "observation_state": "SOURCE_DISCOVERY_ONLY",
        }
        with self.assertRaises(ValueError):
            agent.validate_source(source)

    def test_html_semantic_hash_ignores_spacing_markup(self):
        a = b"<html><body><h1>Hello</h1><p>World</p></body></html>"
        b = b"<html>\n<body> <h1>Hello</h1>   <p>World</p> </body></html>"
        self.assertEqual(agent.semantic_hash(a, "text/html"), agent.semantic_hash(b, "text/html"))

    def test_evidence_row_never_authorizes(self):
        source = {
            "source_id": "TEST_SOURCE",
            "source_family": "TEST",
            "programme_family": "TEST",
            "authority_class": "T1_OFFICIAL",
            "observation_state": "CALL_INDEX_DISCOVERY",
            "url": "https://example.com/",
        }
        result = {
            "health_state": "HEALTHY",
            "semantic_fingerprint": "a" * 64,
            "raw_sha256": "b" * 64,
            "final_url": "https://example.com/",
            "status": 200,
            "content_type": "text/html",
            "bytes": 12,
            "strategy_used": "http",
            "lkg_required": False,
            "errors": [],
        }
        row = agent.evidence_row(source, result, {"health_state": "HEALTHY", "semantic_fingerprint": "a" * 64})
        self.assertEqual(row["change_kind"], "NO_CHANGE")
        for key in agent.AUTH_FLAGS:
            self.assertIs(row[key], False)
        self.assertEqual(row["publication_effect"], "NONE")

    def test_degraded_source_requires_lkg_and_has_no_material_fields(self):
        source = {
            "source_id": "TEST_SOURCE",
            "source_family": "TEST",
            "programme_family": "TEST",
            "authority_class": "T1_OFFICIAL",
            "observation_state": "SOURCE_DISCOVERY_ONLY",
            "url": "https://example.com/",
        }
        result = {
            "health_state": "DEGRADED_TRANSPORT_OR_VALIDATION",
            "semantic_fingerprint": None,
            "raw_sha256": None,
            "final_url": None,
            "status": None,
            "content_type": None,
            "bytes": 0,
            "strategy_used": None,
            "lkg_required": True,
            "errors": ["http:test"],
        }
        row = agent.evidence_row(source, result, None)
        self.assertTrue(row["lkg_required"])
        self.assertIsNone(row["raw_sha256"])
        self.assertIsNone(row["semantic_fingerprint"])
        for key in agent.AUTH_FLAGS:
            self.assertIs(row[key], False)

    def test_run_manifest_is_non_authorizing_and_request_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "agent"
            base.mkdir()
            data = Path(tmp) / "data"
            (base / "control").mkdir()
            (base / "agent.local.json").write_text(json.dumps({
                "repository": "mihaicismaru-bit/civora",
                "code_branch": "test",
                "data_root": str(data),
            }), encoding="utf-8")
            sources = {
                "version": "test",
                "sources": [
                    {"source_id": "SOURCE_A", "url": "https://example.com/a", "allow_hosts": ["example.com"], "source_family": "TEST", "programme_family": "TEST", "authority_class": "T1", "observation_state": "CALL_INDEX_DISCOVERY"},
                    {"source_id": "SOURCE_B", "url": "https://example.com/b", "allow_hosts": ["example.com"], "source_family": "TEST", "programme_family": "TEST", "authority_class": "T1", "observation_state": "PROGRAMMING"},
                ],
            }
            (base / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
            (base / "control" / "requests.json").write_text(json.dumps({"requests": []}), encoding="utf-8")

            def fake_fetch(source):
                body = source["source_id"].encode()
                return {
                    "data": body,
                    "status": 200,
                    "content_type": "text/plain",
                    "final_url": source["url"],
                    "strategy_used": "http",
                    "raw_sha256": agent.sha256_bytes(body),
                    "semantic_fingerprint": agent.semantic_hash(body, "text/plain"),
                    "bytes": len(body),
                    "health_state": "HEALTHY",
                    "lkg_required": False,
                    "errors": [],
                }

            with mock.patch.object(agent, "fetch_source", side_effect=fake_fetch), mock.patch.object(agent, "read_requests", return_value=[]):
                result = agent.run_agent(base, publish=False, source_ids={"SOURCE_A"})
            manifest = result["manifest"]
            self.assertEqual(manifest["source_count"], 1)
            self.assertEqual(manifest["evidence"][0]["source_id"], "SOURCE_A")
            self.assertTrue(manifest["semantic_reconciliation_required_by_partener_engine"])
            for key in agent.AUTH_FLAGS:
                self.assertIs(manifest[key], False)

    def test_remote_request_completed_only_after_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "agent"
            base.mkdir()
            data = Path(tmp) / "data"
            (base / "control").mkdir()
            (base / "agent.local.json").write_text(json.dumps({"repository": "mihaicismaru-bit/civora", "code_branch": "test", "data_root": str(data)}), encoding="utf-8")
            (base / "sources.json").write_text(json.dumps({"version": "test", "sources": [{"source_id": "SOURCE_A", "url": "https://example.com/a", "allow_hosts": ["example.com"], "source_family": "TEST", "programme_family": "TEST", "authority_class": "T1", "observation_state": "SOURCE_DISCOVERY_ONLY"}]}), encoding="utf-8")
            (base / "control" / "requests.json").write_text(json.dumps({"requests": []}), encoding="utf-8")
            fake = {"data": b"ok", "status": 200, "content_type": "text/plain", "final_url": "https://example.com/a", "strategy_used": "http", "raw_sha256": agent.sha256_bytes(b"ok"), "semantic_fingerprint": agent.semantic_hash(b"ok", "text/plain"), "bytes": 2, "health_state": "HEALTHY", "lkg_required": False, "errors": []}
            requests = [{"request_id": "REQ-001", "source_ids": ["SOURCE_A"], "enabled": True}]
            with mock.patch.object(agent, "fetch_source", return_value=fake), mock.patch.object(agent, "read_requests", return_value=requests):
                first = agent.run_agent(base, publish=False)
            self.assertEqual(first["manifest"]["fulfilled_request_ids"], ["REQ-001"])
            state = json.loads((data / "state.json").read_text(encoding="utf-8"))
            self.assertIn("REQ-001", state["completed_request_ids"])


if __name__ == "__main__":
    unittest.main()
