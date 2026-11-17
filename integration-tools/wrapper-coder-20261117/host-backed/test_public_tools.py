import json
import socket
import unittest
from unittest.mock import patch
import public_tools as tools
import public_web as web
from public_web_types import PageText


class PublicToolsTests(unittest.TestCase):
    def test_scope_and_arguments(self):
        for name, args, names in [
            ('web_read', {'url': 'https://example.com'}, set()),
            ('web_read', {'url': 3}, {'web_read'}),
            ('web_read', {'url': 'https://example.com', 'headers': {}}, {'web_read'}),
            ('code_create', {}, {'code_create'}),
        ]:
            self.assertFalse(tools.execute(name, args, names)['ok'])

    def test_reads_and_searches_execute_on_host(self):
        for name, key, method in [('web_read', 'url', 'read_page'), ('web_search', 'query', 'search')]:
            with patch.object(web, method, return_value={'text': 'public result'}) as call:
                result = tools.execute(name, {key: 'example'}, {name})
                self.assertTrue(result['ok'])
                self.assertEqual(result['execution_location'], 'scraper computer')
                call.assert_called_once_with('example')

    def test_private_and_credential_urls_are_denied(self):
        for url in ['file:///etc/passwd', 'http://localhost/', 'https://a:b@example.com/', 'https://example.com:8443/']:
            with self.assertRaises(ValueError):
                web.destination(url)

    def test_private_or_mixed_dns_is_denied(self):
        for ips in [('127.0.0.1',), ('93.184.216.34', '10.0.0.1')]:
            entries = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in ips]
            with patch.object(web.socket, 'getaddrinfo', return_value=entries):
                with self.assertRaises(ValueError):
                    web.destination('https://example.com/')

    def test_parser_omits_scripts_and_styles(self):
        p = PageText()
        p.feed('<style>secret style</style><script>script()</script><p>Public job</p>')
        self.assertEqual(''.join(p.parts), 'Public job')

    def test_network_error_is_reported(self):
        with patch.object(web, 'read_page', side_effect=OSError('unavailable')):
            result = tools.execute('web_read', {'url': 'https://example.com'}, {'web_read'})
            self.assertFalse(result['ok'])
            self.assertEqual(result['execution_location'], 'scraper computer')


if __name__ == '__main__':
    unittest.main()
