"""One TLS tunnel authority and provider-side test limits."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import select
import socket
import socketserver
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

HOST = 'amphenol-aerospace.acquiretm.com'
SOURCE = f'https://{HOST}/home.aspx'
DETAIL = '/job_details_clean.aspx'
MAX_POSTINGS = 75


@contextmanager
def one_dispatch(acquiretm, patch, observation):
    from playwright import sync_api

    cutoff = time.monotonic() + 140
    lock = threading.Lock()
    observation.update(tunnels=0, foreign_tunnels_rejected=0, detail_requests=0, browser_closed=False)

    class Tunnel(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.settimeout(10)
            request = self.rfile.readline(4097).split()
            headers = self.rfile.readline(4097)
            while headers not in (b'\r\n', b'\n', b''):
                headers = self.rfile.readline(4097)
            if (len(request) != 3 or request[0] != b'CONNECT'
                    or request[1].lower() != (HOST + ':443').encode()):
                with lock:
                    observation['foreign_tunnels_rejected'] += 1
                self.wfile.write(b'HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n')
                return
            with lock:
                if observation['tunnels'] >= 120 or time.monotonic() >= cutoff:
                    self.wfile.write(b'HTTP/1.1 503 Budget closed\r\nConnection: close\r\n\r\n')
                    return
                observation['tunnels'] += 1
            try:
                with socket.create_connection((HOST, 443), timeout=15) as upstream:
                    self.wfile.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
                    peers = (self.request, upstream)
                    while time.monotonic() < cutoff:
                        readable, _, _ = select.select(peers, [], [], 0.4)
                        for current in readable:
                            chunk = current.recv(65_536)
                            if not chunk:
                                return
                            peers[current is self.request].sendall(chunk)
            except OSError:
                return

    class Proxy(socketserver.ThreadingTCPServer):
        daemon_threads = True

    original_playwright = sync_api.sync_playwright
    original_client = acquiretm._DetailClient
    original_listing = acquiretm.parse_listing

    def bounded_listing(body):
        total, rows, pages = original_listing(body)
        observation.setdefault('advertised_totals', []).append(total)
        if not 1 <= total <= MAX_POSTINGS or time.monotonic() >= cutoff:
            raise acquiretm.FetchError('partial', 'Rehearsal public inventory bound reached.')
        return total, rows, pages

    class DetailRequest:
        def __init__(self, request):
            self.request = request

        def get(self, url, **kwargs):
            parts = urlsplit(url)
            if (parts.scheme != 'https' or parts.netloc != HOST or parts.path != DETAIL or parts.fragment
                    or set(parse_qs(parts.query)) != {'ID'} or observation['detail_requests'] >= MAX_POSTINGS
                    or time.monotonic() >= cutoff):
                raise acquiretm.FetchError('partial', 'Detail left the exact approved scope or cap.')
            observation['detail_requests'] += 1
            return self.request.get(url, **kwargs)

    def detail_client(request):
        return original_client(DetailRequest(request), max_attempts=1)

    with Proxy(('127.0.0.1', 0), Tunnel) as gate:
        address = {'server': f'http://127.0.0.1:{gate.server_address[1]}'}
        server = threading.Thread(target=gate.serve_forever, daemon=True)
        server.start()

        class Browser:
            def __init__(self, browser):
                self.browser = browser

            def close(self):
                self.browser.close()
                observation['browser_closed'] = True

            def new_context(self):
                context = self.browser.new_context(proxy=address, service_workers='block')
                def guard(route):
                    req = route.request
                    parts = urlsplit(req.url)
                    allowed = (parts.scheme == 'https' and parts.netloc == HOST and not parts.fragment
                               and (req.method == 'GET' or req.method == 'POST' and req.url == SOURCE))
                    if not allowed or time.monotonic() >= cutoff:
                        route.abort()
                        return
                    route.continue_()
                context.route('**/*', guard)
                return context

        @contextmanager
        def playwright_context():
            with original_playwright() as playwright:
                def launch(**kwargs):
                    return Browser(playwright.chromium.launch(proxy=address, **kwargs))
                yield SimpleNamespace(chromium=SimpleNamespace(launch=launch))

        with patch.context() as active:
            active.setattr(sync_api, 'sync_playwright', playwright_context)
            active.setattr(acquiretm, '_DetailClient', detail_client)
            active.setattr(acquiretm, 'parse_listing', bounded_listing)
            try:
                yield
            finally:
                gate.shutdown()
                server.join(timeout=2)
