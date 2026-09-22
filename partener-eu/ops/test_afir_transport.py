#!/usr/bin/env python3
"""Regression tests for the bounded AFIR transport layer."""
import importlib.util
import io
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "ingest" / "afir_ingest.py"
spec = importlib.util.spec_from_file_location("afir_ingest_transport_test", MODULE_PATH)
afir = importlib.util.module_from_spec(spec)
spec.loader.exec_module(afir)


class FakeHeaders(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeResponse:
    def __init__(self, data=b"ok", status=200, url="https://www.afir.ro/info-la-zi/", content_type="text/html; charset=utf-8"):
        self._data = data
        self.status = status
        self._url = url
        self.headers = FakeHeaders({"Content-Type": content_type})

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit=-1):
        return self._data[:limit] if limit >= 0 else self._data

    def geturl(self):
        return self._url


class AFIRTransportTests(unittest.TestCase):
    def test_success_uses_browser_compatible_explicit_headers(self):
        seen = {}

        def fake_open(request, **kwargs):
            seen["headers"] = {key.lower(): value for key, value in request.header_items()}
            return FakeResponse()

        with mock.patch.object(afir.urllib.request, "urlopen", side_effect=fake_open):
            result = afir.fetch("https://www.afir.ro/info-la-zi/", sleep=lambda _: None)

        self.assertTrue(result["ok"])
        self.assertEqual(result["attemptCount"], 1)
        self.assertIn("user-agent", seen["headers"])
        self.assertIn("partener.eu", seen["headers"]["user-agent"].lower())
        self.assertEqual(seen["headers"].get("accept-encoding"), "identity")
        self.assertIn("text/html", seen["headers"].get("accept", ""))
        self.assertIn("ro", seen["headers"].get("accept-language", "").lower())

    def test_retryable_http_error_retries_then_succeeds(self):
        calls = []
        sleeps = []
        error = urllib.error.HTTPError(
            "https://www.afir.ro/info-la-zi/",
            503,
            "Service Unavailable",
            {"Retry-After": "0"},
            io.BytesIO(b""),
        )

        def fake_open(request, **kwargs):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise error
            return FakeResponse()

        with mock.patch.object(afir.urllib.request, "urlopen", side_effect=fake_open):
            result = afir.fetch("https://www.afir.ro/info-la-zi/", sleep=sleeps.append)

        self.assertTrue(result["ok"])
        self.assertEqual(result["attemptCount"], 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [0.0])

    def test_non_retryable_http_error_fails_closed_without_retry(self):
        error = urllib.error.HTTPError(
            "https://www.afir.ro/missing/",
            404,
            "Not Found",
            {},
            io.BytesIO(b""),
        )
        with mock.patch.object(afir.urllib.request, "urlopen", side_effect=error) as opened:
            result = afir.fetch("https://www.afir.ro/missing/", sleep=lambda _: None)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 404)
        self.assertEqual(result["attemptCount"], 1)
        self.assertEqual(opened.call_count, 1)

    def test_network_failure_is_bounded_and_preserves_failure(self):
        sleeps = []
        with mock.patch.object(
            afir.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("temporary failure"),
        ) as opened:
            result = afir.fetch("https://www.afir.ro/info-la-zi/", sleep=sleeps.append)

        self.assertFalse(result["ok"])
        self.assertEqual(result["attemptCount"], afir.MAX_FETCH_ATTEMPTS)
        self.assertEqual(opened.call_count, afir.MAX_FETCH_ATTEMPTS)
        self.assertEqual(len(sleeps), afir.MAX_FETCH_ATTEMPTS - 1)
        self.assertIn("URLError", result["error"])

    def test_retry_after_and_backoff_are_bounded(self):
        self.assertEqual(afir._retry_delay(1, "99"), 8.0)
        self.assertEqual(afir._retry_delay(1, "0"), 0.0)
        self.assertEqual(afir._retry_delay(3, None), 4.0)
        self.assertEqual(afir._retry_delay(8, None), 4.0)


if __name__ == "__main__":
    unittest.main()
