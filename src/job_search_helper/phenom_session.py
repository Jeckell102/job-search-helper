"""Anonymous, origin-pinned public Phenom search session."""
import http.cookiejar
import json
import time
import socket
import ssl
from http.client import HTTPSConnection
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor, ProxyHandler, HTTPSHandler
from .ats import FetchError, HTTPResponse, _NoRedirect, _challenge
from .discovery import _public_addresses, public_careers_url

class _PublicConnection(HTTPSConnection):
    def connect(self):
        # Resolve once and connect to that validated address, retaining TLS SNI.
        addresses = _public_addresses(self.host)
        last_error = None
        for family, kind, protocol, _, address in addresses[:4]:
            raw = socket.socket(family, kind, protocol)
            try:
                raw.settimeout(self.timeout)
                raw.connect(address)
                self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
                return
            except ssl.SSLError:
                raw.close()
                raise
            except OSError as error:
                raw.close()
                last_error = error
        raise last_error or OSError('No public address available')


class _PublicHTTPS(HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PublicConnection, req, context=self._context)


class PhenomSession:
    def __init__(self, source):
        self.host = urlsplit(public_careers_url(source)).hostname
        self.opener = build_opener(ProxyHandler({}), _PublicHTTPS(), _NoRedirect(), HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.last = 0

    def _request(self, url, payload=None, token=''):
        p = urlsplit(public_careers_url(url))
        if p.hostname != self.host or (payload is not None and (p.path != '/widgets' or p.query)):
            raise FetchError('unsupported', 'Phenom session request leaves its public employer scope.')
        time.sleep(max(0, .4 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        headers = {'User-Agent':'JobSearchHelper/1.0', 'Accept-Encoding':'identity'}
        data = None
        if payload is not None:
            if payload.get('ddoKey') != 'refineSearch':
                raise FetchError('unsupported', 'Only public Phenom job searches are allowed.')
            headers.update({'Content-Type':'application/json', 'X-CSRF-TOKEN':token})
            data = json.dumps(payload).encode()
        try:
            try:
                response = self.opener.open(Request(url, data=data, headers=headers), timeout=25)
            except HTTPError as error:
                response = error
            with response:
                body = response.read(4 * 1024 * 1024 + 1)
                if len(body) > 4 * 1024 * 1024:
                    raise FetchError('partial', 'Phenom response exceeds the size limit.')
                return HTTPResponse(response.code, body, dict(response.headers))
        except (URLError, OSError):
            raise FetchError('failed', 'Phenom public session network failure.') from None

    def get(self, url):
        return self._request(url)

    def search(self, app, params, offset):
        endpoint = app.get('widgetApiEndpoint')
        if endpoint != 'https://' + self.host + '/widgets':
            raise FetchError('unsupported', 'Phenom search endpoint is not the employer public widget route.')
        payload = {k: app.get(k) for k in ('deviceType','country','pageName','pageId')}
        payload.update(lang=app['locale'], ddoKey='refineSearch', jobs=True, counts=True,
                       size=50, keywords='', selected_fields={},
                       all_fields=['city','state','category','type','orgFunction','country'],
                       sortBy='Most recent', sort={'order':'desc','field':'postedDate'})
        payload.update({'from':offset, 'global':True})
        r = self._request(endpoint, payload, params.get('csrfToken',''))
        if r.status in (401,403,429) or _challenge(r):
            raise FetchError('blocked','Phenom public search denied access or requires human verification.')
        if r.status != 200:
            raise FetchError('failed',f'Phenom public search HTTP {r.status}.')
        try:
            result = json.loads(r.body)['refineSearch']
            data = result['data']
            if data.get('keywords') or data.get('ui_selections') or result.get('selected_fields'):
                raise FetchError('partial','Phenom search returned unexpected filters.')
            entries, total = data['jobs'], result['totalHits']
            if type(total) is not int or len(entries) != min(50, total-offset):
                raise FetchError('partial','Phenom widget page does not match the requested inventory slice.')
            return result
        except (ValueError, KeyError, TypeError):
            raise FetchError('partial','Phenom public search returned malformed data.') from None
