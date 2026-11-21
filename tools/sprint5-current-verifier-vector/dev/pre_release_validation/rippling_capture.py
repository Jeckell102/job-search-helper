"""Read captured Rippling authority, pagination, and details independently."""

from html import unescape
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit
from uuid import UUID


class CaptureError(ValueError):
    """The capture cannot establish the requested public evidence."""


_BOARD = re.compile(r"https://ats\.rippling\.com/([A-Za-z0-9][A-Za-z0-9_-]{0,99})/jobs")
_RIPPLING_HOSTS = {"ats.rippling.com", "ats.us1.rippling.com"}
_PAGE_SIZE = 20
_MAX_ITEMS = 10_000


def _board_slug(board_url):
    match = _BOARD.fullmatch(board_url) if isinstance(board_url, str) else None
    if match is None:
        raise CaptureError("Expected a canonical Rippling jobs board URL")
    return match[1]


class _EmployerLinks(HTMLParser):
    _INACTIVE = {"template", "noscript", "script", "style"}

    def __init__(self):
        super().__init__()
        self.targets = set()
        self.inactive = []

    def handle_starttag(self, tag, attrs):
        if tag in self._INACTIVE:
            self.inactive.append(tag)
        if self.inactive:
            return
        if tag == "iframe" and any(key == "srcdoc" for key, _ in attrs):
            return
        field = {"a": "href", "iframe": "src"}.get(tag)
        if field is None:
            return
        urls = [value for key, value in attrs if key == field and value]
        for url in urls:
            host = urlsplit(url).hostname
            if host and host.rstrip(".") in _RIPPLING_HOSTS:
                if len(urls) != 1:
                    raise CaptureError("An employer board link has multiple targets")
                self.targets.add(url)

    def handle_endtag(self, tag):
        if self.inactive and tag == self.inactive[-1]:
            self.inactive.pop()


def check_authority(employer_url, board_url, body: str):
    """Require the reviewed employer-page capture to link the exact board."""
    _board_slug(board_url)
    if (not isinstance(employer_url, str) or not employer_url.startswith("https://")
            or not isinstance(body, str)):
        raise CaptureError("Expected an official HTTPS employer page and text capture")
    try:
        employer = urlsplit(employer_url)
        if (not employer.hostname
                or employer.netloc != employer.hostname or employer.fragment
                or employer.hostname.rstrip(".") in _RIPPLING_HOSTS
                or any(character.isspace() for character in employer_url)):
            raise CaptureError("Expected a separate official HTTPS employer page")
        links = _EmployerLinks()
        links.feed(body)
        links.close()
    except (TypeError, ValueError) as error:
        raise CaptureError("Malformed employer-page evidence") from error
    if links.targets != {board_url}:
        raise CaptureError("Employer page does not establish a single exact Rippling board")


class _Hydration(HTMLParser):
    _INACTIVE = {"template", "noscript"}

    def __init__(self):
        super().__init__()
        self.scripts = []
        self.current = None
        self.inactive = []

    def handle_starttag(self, tag, attrs):
        if tag in self._INACTIVE:
            self.inactive.append(tag)
        if self.inactive:
            return
        if tag == "script" and ("id", "__NEXT_DATA__") in attrs:
            for key, value in (("id", "__NEXT_DATA__"), ("type", "application/json")):
                if [entry for name, entry in attrs if name == key] != [value]:
                    raise CaptureError("Invalid Rippling hydration script attributes")
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if self.inactive:
            if tag == self.inactive[-1]:
                self.inactive.pop()
            return
        if tag == "script" and self.current is not None:
            self.scripts.append("".join(self.current))
            self.current = None


def _object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise CaptureError("Rippling hydration contains duplicate object keys")
    return result


def _page_props(body):
    if not isinstance(body, str):
        raise CaptureError("Rippling capture body must be text")
    parser = _Hydration()
    parser.feed(body)
    parser.close()
    if len(parser.scripts) != 1 or parser.current is not None:
        raise CaptureError("Expected one complete Rippling hydration script")
    try:
        return json.loads(parser.scripts[0], object_pairs_hook=_object)["props"]["pageProps"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise CaptureError("Missing or malformed Rippling page props") from error


def _identity(item):
    try:
        identifier, name = item["id"], item["name"]
        if (not isinstance(identifier, str) or str(UUID(identifier)) != identifier
                or not isinstance(name, str) or not name.strip()):
            raise ValueError("Invalid listing identity")
    except (KeyError, TypeError, ValueError) as error:
        raise CaptureError("Rippling listing needs a canonical UUID and a title") from error
    return identifier, name


def read_listing(board_url, page: int, body: str) -> tuple[int, list[dict]]:
    """Read one independently verified unfiltered page, including explicit zero."""
    tenant = _board_slug(board_url)
    if type(page) is not int or not 0 <= page < _MAX_ITEMS // _PAGE_SIZE:
        raise CaptureError("Rippling page number is out of range")
    props = _page_props(body)
    try:
        board = props["apiData"]
        if board["jobBoardSlug"] != tenant or board["jobBoard"]["slug"] != tenant:
            raise CaptureError("Rippling listing belongs to a different board")
        queries = props["dehydratedState"]["queries"]
        prefix = ["board", tenant, "job-posts"]
        matches = [query for query in queries if query["queryKey"][:3] == prefix]
        if len(matches) != 1:
            raise CaptureError("Expected one Rippling public jobs query")
        query = matches[0]
        key = query["queryKey"]
        data = query["state"]["data"]
        filters = {
            "city": "", "country": "", "departments": [], "page": page,
            "pageSize": _PAGE_SIZE, "searchQuery": "", "state": "", "workplaceType": None,
        }
        if (type(key[3]) is not bool
                or key[4:5] != [filters] or type(key[4]["page"]) is not int
                or type(key[4]["pageSize"]) is not int or key[5:] not in ([], ["en-US"])):
            raise CaptureError("Rippling query does not prove unfiltered public scope")
        total, items = data["totalItems"], data["items"]
        if type(total) is not int or not 0 <= total <= _MAX_ITEMS:
            raise CaptureError("Rippling listing has no explicit valid total")
        pages = (total + _PAGE_SIZE - 1) // _PAGE_SIZE
        metadata = (data["page"], data["pageSize"], data["totalPages"])
        if (any(type(value) is not int for value in metadata)
                or metadata != (page, _PAGE_SIZE, pages)
                or page >= max(1, pages)
                or not isinstance(items, list)
                or len(items) != min(_PAGE_SIZE, total - page * _PAGE_SIZE)):
            raise CaptureError("Rippling page count, size, or total is inconsistent")
    except (KeyError, IndexError, TypeError) as error:
        raise CaptureError("Rippling listing or pagination evidence is incomplete") from error
    for item in items:
        _identity(item)
    return total, items


class _VisibleText(HTMLParser):
    _BLOCKS = {"p", "br", "li", "div", "h1", "h2", "h3"}
    _HIDDEN = {"script", "style", "template", "noscript"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = []

    def handle_starttag(self, tag, attrs):
        if tag in self._HIDDEN:
            self.hidden.append(tag)
        if not self.hidden and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _visible(value):
    if not isinstance(value, str):
        raise CaptureError("Rippling visible text must be a string")
    parser = _VisibleText()
    parser.feed(unescape(unescape(value)))
    parser.close()
    return "\n".join(" ".join(line.split()) for line in "".join(parser.parts).splitlines()
                     if line.strip())


def read_detail(board_url, item: dict, body: str) -> dict:
    """Verify exact posting identity and extract both full description sections."""
    tenant = _board_slug(board_url)
    identifier, name = _identity(item)
    url = f"{board_url}/{identifier}"
    try:
        detail = _page_props(body)["apiData"]
        job = detail["jobPost"]
        if (detail["jobBoard"]["slug"] != tenant
                or ("jobBoardSlug" in detail and detail["jobBoardSlug"] != tenant)
                or job["uuid"] != identifier or job["url"] != url
                or job["name"] != name or job["unlistedFromSearch"] is not False):
            raise CaptureError("Rippling posting detail identity or visibility differs")
        sections = job["description"]
        if not isinstance(sections, dict) or set(sections) - {"company", "role"}:
            raise CaptureError("Unexpected Rippling description section structure")
        role = _visible(sections["role"])
        employer = _visible(sections["company"]) if sections.get("company") is not None else ""
    except (KeyError, TypeError) as error:
        raise CaptureError("Rippling posting detail or full description is missing") from error
    title = _visible(name)
    if not title or not role:
        raise CaptureError("Rippling posting title or role description has no visible text")
    return {
        "posting_id": identifier, "url": url, "title": title,
        "description": "\n\n".join(section for section in (employer, role) if section),
    }
