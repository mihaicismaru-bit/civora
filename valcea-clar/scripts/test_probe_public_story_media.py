"""Exercise the complete photo gate offline, including real HTTP on loopback."""
import copy
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import probe_public_story_media as probe

PHOTO = bytes.fromhex('89504e470d0a1a0a') + b'photo-fixture'
ORIGIN = 'https://canonical.example/photo.png'
VISUAL = {'public_url': ORIGIN, 'provenance_status': 'VERIFIED',
          'synthetic': False, 'contextual_archive': True,
          'editorial_note': 'Foto de context; nu surprinde evenimentul curent.'}


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.feed = {'generated_at': '2026-10-03T06:00:33.935057Z',
                     'stories': [{'id': 'current', 'path': '/stiri/current/', 'visual': None}]}
        self.manifest = {'stories': [{'id': 'archive', 'path': '/stiri/archive/',
                                     'public_ux_authorized': True, 'image': copy.deepcopy(VISUAL)}]}
        self.responses = {
            '/media/provenance.json': (200, 'application/json', json.dumps({'assets': {
                'photo.png': {'origin_url': ORIGIN, 'provenance_status': 'VERIFIED'}}}).encode()),
            '/stiri/archive/': (200, 'text/html', b'<figure><img src="/media/photo.png"></figure>'),
            '/media/photo.png': (200, 'image/png', PHOTO),
        }
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append(self.path)
                status, content_type, body = outer.responses.get(self.path, (404, 'text/plain', b'missing'))
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def evaluate(self, limit=None):
        root = Path(self.tmp.name)
        feed, manifest = root / 'feed.json', root / 'manifest.json'
        feed.write_text(json.dumps(self.feed))
        manifest.write_text(json.dumps(self.manifest))
        with patch.object(probe, 'FEED', feed), patch.object(probe, 'STORY_MANIFEST', manifest):
            return probe.evaluate(self.base, limit)

    def test_archived_photo_is_fetched_despite_text_only_live_feed(self):
        before = copy.deepcopy((self.feed, self.manifest))
        result = self.evaluate()
        self.assertTrue(result['ready'])
        self.assertEqual(result['checked_count'], 1)
        self.assertEqual(result['checks'][0]['delivery_mode'], 'verified_local_mirror')
        self.assertIn('/stiri/archive/', self.requests)
        self.assertIn('/media/photo.png', self.requests)
        self.assertEqual((self.feed, self.manifest), before)

    def test_canonical_delivery_requires_http_image_bytes(self):
        self.manifest['stories'][0]['image']['public_url'] = self.base + '/media/photo.png'
        self.assertTrue(self.evaluate()['ready'])
        self.assertIn('/media/photo.png', self.requests)

    def test_empty_candidates_stay_blocked(self):
        self.manifest['stories'] = []
        result = self.evaluate()
        self.assertFalse(result['ready'])
        self.assertEqual(result['blockers'], ['__no_verified_visuals_checked__'])

    def test_live_null_does_not_revive_obsolete_archive_image(self):
        self.feed['stories'][0].update(id='archive', path='/stiri/archive/')
        self.assertEqual(self.evaluate()['checked_count'], 0)

    def test_duplicate_route_is_checked_once(self):
        self.manifest['stories'].append({**self.manifest['stories'][0], 'id': 'duplicate'})
        self.assertEqual(self.evaluate()['checked_count'], 1)

    def test_unauthorized_or_ineligible_records_are_not_candidates(self):
        original = copy.deepcopy(self.manifest['stories'][0])
        variants = [dict(public_ux_authorized=False), dict(path='/editions/archive/')]
        for change in variants:
            with self.subTest(change=change):
                self.manifest['stories'] = [{**original, **change}]
                self.assertEqual(self.evaluate()['checked_count'], 0)
        for change in ({'synthetic': True}, {'provenance_status': 'UNVERIFIED'},
                       {'editorial_note': ''}, {'public_url': '/media/photo.png'},
                       {'media_role': 'social_card'}):
            with self.subTest(change=change):
                self.manifest['stories'] = [{**original, 'image': {**VISUAL, **change}}]
                self.assertEqual(self.evaluate()['checked_count'], 0)

    def test_metadata_only_missing_html_wrong_photo_and_invalid_bytes_block(self):
        cases = [('/stiri/archive/', (200, 'text/html', f'<meta property="og:image" content="{ORIGIN}">'.encode())),
                 ('/stiri/archive/', (404, 'text/html', b'missing')),
                 ('/stiri/archive/', (200, 'text/html', b'<img src="/media/unrelated.png">')),
                 ('/media/photo.png', (404, 'text/plain', b'missing')),
                 ('/media/photo.png', (200, 'text/html', b'<html>error</html>')),
                 ('/media/photo.png', (200, 'text/html', PHOTO))]
        original = copy.deepcopy(self.responses)
        for path, response in cases:
            with self.subTest(path=path, response=response[:2]):
                self.responses = {**original, path: response}
                result = self.evaluate()
                self.assertFalse(result['ready'])
                self.assertEqual(result['checked_count'], 1)
                self.assertIn('/stiri/archive/', result['blockers'])

    def test_missing_or_wrong_public_provenance_blocks(self):
        for doc in ({'assets': {}}, {'assets': {'photo.png': {'origin_url': 'https://wrong.example/p.png'}}},
                    {'assets': {'photo.png': {'origin_url': ORIGIN, 'provenance_status': 'UNVERIFIED'}}},
                    {'assets': {}, 'mirror_failures': ['failed']}):
            with self.subTest(doc=doc):
                self.responses['/media/provenance.json'] = (200, 'application/json', json.dumps(doc).encode())
                self.assertFalse(self.evaluate()['ready'])

    def test_zero_limit_cannot_pass_without_checks(self):
        result = self.evaluate(limit=0)
        self.assertEqual(result['eligible_verified_visual_count'], 1)
        self.assertEqual(result['checked_count'], 0)
        self.assertFalse(result['ready'])


if __name__ == '__main__':
    unittest.main()
