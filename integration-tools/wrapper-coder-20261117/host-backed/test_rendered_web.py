import unittest
from unittest.mock import patch

import rendered_web


class RenderedWebPolicyTests(unittest.TestCase):
    def test_allows_public_navigation_and_same_host_reads(self):
        allowed = set()
        with patch.object(rendered_web.public_web, 'destination', return_value=(None, 'example.com', 443, '93.184.216.34')):
            self.assertTrue(rendered_web.request_allowed('https://example.com/', 'GET', 'document', True, allowed))
            self.assertEqual(allowed, {'example.com'})
            self.assertTrue(rendered_web.request_allowed('https://example.com/app.js', 'GET', 'script', False, allowed))

    def test_blocks_writes_and_unneeded_resources(self):
        allowed = {'example.com'}
        self.assertFalse(rendered_web.request_allowed('https://example.com/api', 'POST', 'xhr', False, allowed))
        self.assertFalse(rendered_web.request_allowed('https://example.com/logo.png', 'GET', 'image', False, allowed))

    def test_blocks_third_party_subresources(self):
        allowed = {'example.com'}
        with patch.object(rendered_web.public_web, 'destination', return_value=(None, 'tracker.example', 443, '93.184.216.34')):
            self.assertFalse(rendered_web.request_allowed('https://tracker.example/a.js', 'GET', 'script', False, allowed))


if __name__ == '__main__':
    unittest.main()
