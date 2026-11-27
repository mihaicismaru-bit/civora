#!/usr/bin/env python3
"""Hermetic retry, exact-name, rejection and fail-closed coverage."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('gate', Path(__file__).with_name('wait_pages_artifact.py'))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

NAME = 'github-pages-1'
GOOD = {'artifacts': [{'name': NAME, 'id': 123, 'size_in_bytes': 300, 'expired': False}]}


class PagesArtifactGateTest(unittest.TestCase):
    def test_immediate(self):
        self.assertEqual(gate.wait_visible(lambda: GOOD, lambda _: None, NAME, 3, 0), 1)

    def test_eventual_consistency(self):
        responses = iter([{'artifacts': []}, {'artifacts': []}, GOOD])
        delays = []
        self.assertEqual(gate.wait_visible(lambda: next(responses), delays.append, NAME, 3, 2), 3)
        self.assertEqual(delays, [2, 2])

    def test_wrong_artifact_name_not_accepted(self):
        self.assertIsNone(gate.wait_visible(lambda: GOOD, lambda _: None, 'github-pages-2', 2, 0))

    def test_expired_or_zero_byte_or_missing_id_never_pass(self):
        for patch in ({'expired': True}, {'size_in_bytes': 0}, {'id': 0}, {'expired': None}):
            item = dict(GOOD['artifacts'][0], **patch)
            self.assertFalse(gate.exact_visible({'artifacts': [item]}, NAME))

    def test_malformed_data_never_pass(self):
        for body in ({}, [], {'artifacts': {}}, {'artifacts': [{}]}):
            self.assertFalse(gate.exact_visible(body, NAME))

    def test_transient_errors_bounded_and_fail_closed(self):
        count = [0]
        def fetch():
            count[0] += 1
            raise OSError('transient')
        delays = []
        self.assertIsNone(gate.wait_visible(fetch, delays.append, NAME, 3, 1))
        self.assertEqual(count[0], 3)
        self.assertEqual(delays, [1, 1])

    def test_invalid_retry_budget(self):
        with self.assertRaises(ValueError):
            gate.wait_visible(lambda: GOOD, lambda _: None, NAME, 0, 1)


if __name__ == '__main__':
    unittest.main()
