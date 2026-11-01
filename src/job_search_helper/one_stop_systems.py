"""One Stop Systems' first-party Shopify careers pages."""
from __future__ import annotations

import json
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, HTTPTransport, Inventory, _base, text


SOURCE = "https://onestopsystems.com/pages/open-positions"
HOST = "onestopsystems.com"
ROLE_PREFIX = "/pages/"
ATS = "Shopify careers"


class _Discovery(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.main_depth = 0
        self.anchor: dict[str, str] | None = None
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "main":
            self.main_depth += 1
        if tag == "a":
            self.anchor = {"href": attrs.get("href", ""), "text": ""}

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            self.links.append((self.anchor["href"], self.anchor["text"]))
            self.anchor = None
        if tag == "main" and self.main_depth:
            self.main_depth -= 1

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor["text"] += data


class _Detail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.main_depth = 0
        self.skip = 0
        self.parts: list[str] = []
        self.title = ""
        self.in_h1 = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1
        if tag == "main":
            self.main_depth += 1
        if tag == "h1":
            self.in_h1 = True
        if not self.skip and tag in {"p", "br", "li", "h2", "h3", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "h1":
            self.in_h1 = False
        if tag == "main" and self.main_depth:
            self.main_depth -= 1
        if tag in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1
        if not self.skip and tag in {"p", "li", "div"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_h1 and not self.skip:
            self.title += data
        if not self.skip:
            self.parts.append(data)


def _response(client, url):
    response = client.get(url)
    if response.status in {401, 403, 429}:
        raise FetchError("blocked", f"One Stop Systems public careers page returned HTTP {response.status}.")
    if response.status != 200:
        raise FetchError("partial", "One Stop Systems public careers page was unavailable.")
    # Shopify returns a JSON page envelope when the installed transport asks
    # for application/json.  Normalize it to the embedded first-party HTML;
    # this is still the same public page and avoids requiring cookies.
    try:
        payload = json.loads(response.body.decode("utf-8"))
        body_html = payload.get("page", {}).get("body_html") if isinstance(payload, dict) else None
        if isinstance(body_html, str) and body_html:
            response.body = body_html.encode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError):
        pass
    return response


def _role_urls(body: bytes):
    parser = _Discovery()
    parser.feed(body.decode("utf-8", "replace"))
    parser.close()
    roles = {}
    ignored = {"open-positions", "contact-hr", "contact-us", "careers"}
    for href, label in parser.links:
        absolute = urljoin(SOURCE, href.strip())
        parsed = urlsplit(absolute)
        slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if (parsed.scheme != "https" or parsed.hostname != HOST or parsed.path.count("/") != 2
                or not parsed.path.startswith(ROLE_PREFIX) or parsed.query or parsed.fragment
                or slug in ignored or not label.strip()):
            continue
        roles[slug] = absolute
    return roles


def _job(client, url, company_id, company, slug):
    response = _response(client, url)
    parser = _Detail()
    parser.feed(response.body.decode("utf-8", "replace"))
    parser.close()
    title = text(parser.title)
    description = text("".join(parser.parts))
    if not title or not description or len(description) < 100:
        raise ValueError("One Stop Systems role page lacks a full description.")
    if "one stop systems" not in description.casefold() and "oss" not in description.casefold():
        raise ValueError("One Stop Systems role page lacks employer identity.")
    row = _base({"id": slug}, ATS, company_id, company)
    row.update(title=title, url=url, description=description)
    return row


def fetch_one_stop_systems(careers_url, company_id, company, transport=None):
    if careers_url.rstrip("/") != SOURCE or company_id != "COMP-0287" or company.casefold() != "one stop systems":
        return Inventory("unsupported", reason="One Stop Systems adapter requires its verified open-positions page.",
                         source_url=careers_url, ats=ATS)
    client = transport or HTTPTransport()
    jobs = []
    try:
        first = _response(client, SOURCE)
        first_roles = _role_urls(first.body)
        if not first_roles:
            raise FetchError("partial", "One Stop Systems careers page exposed no verifiable role links.")
        for slug, url in first_roles.items():
            jobs.append(_job(client, url, company_id, company, slug))
        reread = _response(client, SOURCE)
        second_roles = _role_urls(reread.body)
        if set(first_roles) != set(second_roles):
            raise FetchError("partial", "One Stop Systems careers inventory changed during the scan.")
        return Inventory("complete", jobs, f"Shopify careers: retrieved {len(jobs)} complete postings and rechecked the public inventory.", SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, SOURCE, ATS)
    except (AttributeError, KeyError, TypeError, ValueError):
        return Inventory("partial", jobs, "One Stop Systems careers schema validation failed.", SOURCE, ATS)
