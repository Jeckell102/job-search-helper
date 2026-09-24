"""Find a supported ATS board linked from the configured public careers page."""
from __future__ import annotations

from html.parser import HTMLParser
from http.client import HTTPException, HTTPSConnection
import ipaddress
import socket
import ssl
import time
from urllib.parse import urldefrag, urljoin, urlsplit

from .ats import FetchError, HTTPResponse, _challenge, resolve_board


MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 4


def public_careers_url(url: str) -> str:
    try:
        if not isinstance(url, str) or len(url) > 4096:
            raise ValueError
        url = url.strip()
        if not url or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
            raise ValueError
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (parsed.scheme != "https" or not host or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)
                or "." not in host or host.endswith((".localhost", ".local", ".internal"))):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError
        return urldefrag(url)[0]
    except (ValueError, TypeError):
        raise FetchError("unsupported", "Careers discovery requires a public HTTPS URL without credentials or a custom port.") from None


def _public_addresses(host):
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise FetchError("unsupported", "Careers hostname does not resolve exclusively to public addresses.")
    return addresses


class CareersTransport:
    """Fetch public HTML without cookies, proxies, automatic redirects or credentials."""

    def __init__(self, timeout=15, interval=0.4, sleep=time.sleep):
        self.timeout = timeout
        self.interval = interval
        self.sleep = sleep
        self.last_request = 0.0
        self.context = ssl.create_default_context()

    def get(self, url):
        parsed = urlsplit(public_careers_url(url))
        try:
            addresses = _public_addresses(parsed.hostname)
            self.sleep(max(0.0, self.interval - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            # Connect to a validated address while retaining the hostname for
            # Host/SNI/certificate verification; do not resolve DNS a second time.
            for family, kind, protocol, _, address in addresses[:4]:
                connection = HTTPSConnection(parsed.hostname, timeout=self.timeout)
                raw = socket.socket(family, kind, protocol)
                try:
                    raw.settimeout(self.timeout)
                    raw.connect(address)
                    connection.sock = self.context.wrap_socket(raw, server_hostname=parsed.hostname)
                    target = parsed.path or "/"
                    if parsed.query:
                        target += "?" + parsed.query
                    connection.request("GET", target, headers={
                        "User-Agent": "JobSearchHelper/1.0 (public careers-board discovery; read-only)",
                        "Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "identity",
                    })
                    response = connection.getresponse()
                    body = response.read(MAX_HTML_BYTES + 1)
                    if len(body) > MAX_HTML_BYTES:
                        raise FetchError("unsupported", "Careers page exceeds the discovery size limit; provide its ATS board URL.")
                    return HTTPResponse(response.status, body, dict(response.getheaders()))
                except ssl.SSLError:
                    raise FetchError("failed", "Careers page TLS verification or connection failed.") from None
                except (OSError, HTTPException):
                    continue
                finally:
                    connection.close()
                    raw.close()
        except (OSError, HTTPException):
            pass
        raise FetchError("failed", "Careers page network/timeout failure; board discovery did not complete.")


class _BoardLinks(HTMLParser):
    def __init__(self, page_url):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.base_url = page_url
        self.base_seen = False
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "base" and attrs.get("href") and not self.base_seen:
            self.base_url = urljoin(self.page_url, attrs["href"])
            self.base_seen = True
        field = {"a": "href", "iframe": "src", "script": "src"}.get(tag)
        if field and attrs.get(field):
            self.links.append(attrs[field])


def _board_candidates(links, base_url):
    boards = set()
    for link in links:
        try:
            url = urljoin(base_url, link)
            boards.add(resolve_board("", url))
        except (ValueError, TypeError):
            continue
    return boards


def _select_board(ats, boards):
    if len(boards) > 1:
        raise FetchError("unsupported", "Multiple ATS boards linked by careers page; select the company's board explicitly.")
    if not boards:
        raise FetchError("unsupported", "No supported ATS link found on careers page; it may use another ATS or require JavaScript. Provide a direct Greenhouse, Lever, Ashby, Workday, iCIMS, ADP Workforce Now, or Paylocity board URL.")
    name, board, root = next(iter(boards))
    try:
        resolve_board(ats, root + board)
    except (ValueError, TypeError):
        raise FetchError("unsupported", "Discovered board disagrees with ATS / Source; verify the company configuration.") from None
    return name, board, root


def discover_board(ats, careers_url, transport=None):
    if any(marker in ats.casefold() for marker in ("shared", "parent")):
        raise FetchError("unsupported", "Shared/parent board requires an explicit company scope; automatic discovery cannot assign all parent-company jobs.")
    transport = transport or CareersTransport()
    url = public_careers_url(careers_url)
    visited = set()
    for hop in range(MAX_REDIRECTS + 1):
        if url in visited:
            raise FetchError("failed", "Careers redirect loop; verify Official Careers URL.")
        visited.add(url)
        response = transport.get(url)
        if not isinstance(response, HTTPResponse):
            raise FetchError("failed", "Careers transport must return HTTPResponse.")
        if _challenge(response, expect_html=True) or response.status in (401, 403):
            raise FetchError("blocked", f"Careers page HTTP {response.status}: access denied or human verification; manual review required.")
        headers = {key.lower(): value for key, value in response.headers.items()}
        if response.status in (301, 302, 303, 307, 308):
            location = headers.get("location", "")
            if not location:
                raise FetchError("failed", "Careers redirect has no destination.")
            target = public_careers_url(urljoin(url, location))
            candidates = _board_candidates([target], url)
            if candidates:
                board = _select_board(ats, candidates)
                return board, url
            current_host = urlsplit(url).hostname.removeprefix("www.")
            target_host = urlsplit(target).hostname.removeprefix("www.")
            if current_host != target_host:
                raise FetchError("unsupported", "Careers page redirects to another host without a supported board URL; verify and record its destination.")
            if hop == MAX_REDIRECTS:
                raise FetchError("failed", "Careers redirect limit reached; verify Official Careers URL.")
            url = target
            continue
        if not 200 <= response.status < 300:
            raise FetchError("failed", f"Careers page HTTP {response.status}; board discovery did not complete.")
        if len(response.body) > MAX_HTML_BYTES:
            raise FetchError("unsupported", "Careers page exceeds the discovery size limit; provide its ATS board URL.")
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type and content_type not in ("text/html", "application/xhtml+xml"):
            raise FetchError("unsupported", "Careers discovery expected an HTML page; provide the ATS board URL.")
        parser = _BoardLinks(url)
        parser.feed(response.body.decode("utf-8", "replace"))
        parser.close()
        return _select_board(ats, _board_candidates(parser.links, parser.base_url)), url
    raise FetchError("failed", "Careers discovery did not complete.")
