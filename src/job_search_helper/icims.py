"""Read public iCIMS portal listings and JobPosting JSON-LD, without a login."""
from __future__ import annotations

from html.parser import HTMLParser
import json
import re
import sys
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit

from .ats import FetchError, HTTPResponse, Inventory, _base, _challenge, _safe_api_url, is_icims_host, text


MAX_PAGES = 200
MAX_HTML_BYTES = 2 * 1024 * 1024
FILTERS = frozenset({"searchKeyword", "searchRelation", "searchCategory", "searchPositionType",
                     "searchLocation", "searchCompany", "searchZip", "searchRadius"})
DISPLAY_PARAMS = frozenset({"in_iframe", "ss", "pr", "mobile", "needsRedirect", "bga", "width",
                            "height", "jan1offset", "jun1offset", "hashed", "schemaId", "o", "iis", "iisn"})
VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                       "param", "source", "track", "wbr"})
EMPTY_MESSAGE = "Sorry, no jobs were found that match your search criteria. Please try other selections."


def _job_id(path):
    match = re.fullmatch(r"/jobs/([0-9]+)/([^/]+)/job/?", path)
    if not match:
        raise ValueError("iCIMS posting URL is not a public job detail.")
    slug = unquote(match[2])
    if (slug in {".", ".."} or any(c in slug for c in "/\\?#") or any(ord(c) < 32 for c in slug)
            or re.search(r"%[0-9A-Fa-f]{2}", slug)):
        raise ValueError("iCIMS posting URL has an invalid path.")
    return match[1]


def _scope(query):
    scope = {}
    for key, value in parse_qsl(query, keep_blank_values=True, max_num_fields=80):
        if key in DISPLAY_PARAMS or key.startswith("utm_"):
            continue
        if key == "mode" and value in ("", "redo"):
            continue
        if key not in FILTERS or len(value) > 512 or any(ord(c) < 32 for c in value):
            raise ValueError("Unsupported iCIMS URL parameter; verify the public search URL and filters.")
        if not value.strip():
            continue
        if key in scope and scope[key] != value.strip():
            raise ValueError("Conflicting iCIMS search filters; select one value per filter.")
        scope[key] = value.strip()
    if "searchKeyword" in scope:
        scope.setdefault("searchRelation", "keyword_all")
        if scope["searchRelation"] not in {"keyword_all", "keyword_any"}:
            raise ValueError("Unsupported iCIMS keyword search mode.")
    else:
        scope.pop("searchRelation", None)
    return dict(sorted(scope.items()))


def safe_portal_path(parsed):
    try:
        if parsed.fragment:
            return False
        if parsed.path == "/jobs/search":
            _scope(parsed.query)
            return True
        _job_id(parsed.path)
        return all(key == "in_iframe" and value == "1" for key, value in parse_qsl(parsed.query, keep_blank_values=True))
    except ValueError:
        return False


def resolve_icims(ats, url):
    p = urlsplit(url)
    if (p.scheme != "https" or not is_icims_host(p.hostname) or p.username or p.password
            or p.port not in (None, 443)):
        raise ValueError("Provide a verified public iCIMS HTTPS board URL.")
    if p.path.rstrip("/") not in {"", "/jobs", "/jobs/search", "/jobs/intro"}:
        _job_id(p.path)
    scope = _scope(p.query)
    configured = ats.casefold()
    if any(name in configured for name in ("greenhouse", "lever", "ashby", "workday", "adp", "paylocity")) and "icims" not in configured:
        raise ValueError("ATS / Source disagrees with the verified ATS URL.")
    if any(marker in configured for marker in ("shared", "parent")) and not scope:
        raise ValueError("Shared/parent iCIMS board requires an explicit company search or filter.")
    query = urlencode(scope)
    return "iCIMS", "search" + ("?" + query if query else ""), f"https://{p.hostname}/jobs/"


class _Portal(HTMLParser):
    """Collect only portal markers, result-card links and structured job data."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.listing = False
        self.search_form = False
        self.headers = []
        self.messages = []
        self.cards = []
        self.canonical = []
        self.next_links = []
        self.jsonld = []
        self.options = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        parent = self.stack[-1] if self.stack else {}
        state = {"tag": tag, "capture": parent.get("capture"), "card": parent.get("card"),
                 "select": parent.get("select"), "skip": parent.get("skip", False)}
        self.listing |= "iCIMS_ListingsPage" in classes
        self.search_form |= tag == "form" and attrs.get("id") == "searchForm"
        if classes & {"iCIMS_JobCardItem", "iCIMS_JobListingRow"}:
            self.cards.append([])
            state["card"] = self.cards[-1]
        if "iCIMS_SubHeader_Jobs" in classes:
            self.headers.append([])
            state["capture"] = self.headers[-1]
        if "iCIMS_GenericMessage" in classes:
            self.messages.append([])
            state["capture"] = self.messages[-1]
        if tag in {"script", "style"}:
            state["skip"] = True
            if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
                self.jsonld.append([])
                state["capture"] = self.jsonld[-1]
                state["skip"] = False
        if tag == "a" and state["card"] is not None and attrs.get("href"):
            state["card"].append(attrs["href"])
        if tag == "link":
            rel = attrs.get("rel", "").lower().split()
            if "canonical" in rel:
                self.canonical.append(attrs.get("href", ""))
            if "next" in rel:
                self.next_links.append(attrs.get("href", ""))
        if tag == "select":
            state["select"] = attrs.get("name")
        if tag == "option" and state["select"]:
            self.options.setdefault(state["select"], set()).add(attrs.get("value", ""))
        if tag not in VOID_TAGS:
            self.stack.append(state)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.stack and not self.stack[-1]["skip"] and self.stack[-1]["capture"] is not None:
            self.stack[-1]["capture"].append(data)


def _html(url, transport):
    _safe_api_url(url)
    response = transport.get(url)
    if not isinstance(response, HTTPResponse):
        raise FetchError("failed", "iCIMS transport must return HTTPResponse.")
    if response.status in (401, 403) or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"iCIMS HTTP {response.status}: access denied or human verification; manual review required.")
    if not 200 <= response.status < 300:
        raise FetchError("failed", f"iCIMS HTTP {response.status}; inventory unavailable, not evidence of closure.")
    headers = {k.lower(): v for k, v in response.headers.items()}
    if headers.get("content-type", "text/html").split(";", 1)[0].lower() not in {"text/html", "application/xhtml+xml"}:
        raise FetchError("partial", "iCIMS returned non-HTML data; inventory is incomplete.")
    if len(response.body) > MAX_HTML_BYTES:
        raise FetchError("partial", "iCIMS HTML exceeded the page size limit.")
    parser = _Portal()
    parser.feed(response.body.decode("utf-8"))
    parser.close()
    return parser


def _detail_url(link, source):
    p = urlsplit(urljoin(source, link))
    host = urlsplit(source).hostname
    if (p.scheme != "https" or p.hostname != host or p.username or p.password or p.port not in (None, 443)):
        raise ValueError("iCIMS posting link leaves its configured public board.")
    ident = _job_id(p.path)
    return ident, f"https://{host}{p.path.rstrip('/')}"


def _listing(parser, source, page_number):
    if not parser.listing or not parser.search_form:
        raise FetchError("partial", "iCIMS page is missing its public listing/search markers.")
    requested = _scope(urlsplit(source).query)
    if requested:
        expected = resolve_icims("", source)
        if len(parser.canonical) != 1 or resolve_icims("", urljoin(source, parser.canonical[0])) != expected:
            raise FetchError("partial", "iCIMS did not confirm the requested search scope in its canonical URL.")
        for key, value in requested.items():
            if key not in {"searchKeyword", "searchRelation", "searchZip"} and value not in parser.options.get(key, set()):
                raise FetchError("unsupported", "iCIMS search filter is unavailable; verify the filtered board URL.")
    pages = [re.search(r"\bPage\s+(\d+)\s+of\s+(\d+)\b", " ".join(parts)) for parts in parser.headers]
    pages = [match for match in pages if match]
    empty = any(EMPTY_MESSAGE in " ".join("".join(parts).split()) for parts in parser.messages)
    if empty:
        if parser.cards or parser.next_links or pages or page_number != 1:
            raise FetchError("partial", "iCIMS returned conflicting or prematurely empty search results.")
        return 0, []
    if len(pages) != 1 or int(pages[0][1]) != page_number or int(pages[0][2]) < page_number:
        raise FetchError("partial", "iCIMS pagination is missing or inconsistent.")
    total = int(pages[0][2])
    if bool(parser.next_links) != (page_number < total) or not parser.cards:
        raise FetchError("partial", "iCIMS result cards or next-page evidence are inconsistent.")
    if parser.next_links:
        target = urljoin(source, parser.next_links[0])
        next_page = dict(parse_qsl(urlsplit(target).query)).get("pr")
        if (len(parser.next_links) != 1 or resolve_icims("", target) != resolve_icims("", source)
                or next_page != str(page_number)):
            raise FetchError("partial", "iCIMS next-page link changed the board, filters, or page sequence.")
    entries = []
    for card in parser.cards:
        links = set()
        for href in card:
            # Ignore unrelated category links, but reject malformed job links.
            if re.search(r"/jobs/[0-9]+/", urlsplit(urljoin(source, href)).path):
                links.add(_detail_url(href, source))
        if len(links) != 1:
            raise FetchError("partial", "iCIMS result card does not identify exactly one public posting.")
        entries.append(next(iter(links)))
    return total, entries


def _job_objects(value):
    if isinstance(value, list):
        for item in value:
            yield from _job_objects(item)
    elif isinstance(value, dict):
        kinds = value.get("@type", [])
        if kinds == "JobPosting" or isinstance(kinds, list) and "JobPosting" in kinds:
            yield value
        yield from _job_objects(value.get("@graph"))


def _posting(parser, ident, url, company_id, company):
    candidates = []
    for script in parser.jsonld:
        candidates.extend(_job_objects(json.loads("".join(script))))
    if len(candidates) != 1:
        raise FetchError("partial", "iCIMS detail must contain exactly one structured JobPosting.")
    item = candidates[0]
    if not isinstance(item.get("url"), str) or not item["url"] or _detail_url(item["url"], url)[0] != ident:
        raise FetchError("partial", "iCIMS structured posting URL disagrees with its listing.")
    if any(not isinstance(item.get(key), str) or not item[key].strip() for key in ("title", "description")):
        raise FetchError("partial", "iCIMS structured posting lacks a title or full description.")
    locations = item.get("jobLocation", [])
    if isinstance(locations, dict):
        locations = [locations]
    if not isinstance(locations, list):
        raise FetchError("partial", "iCIMS structured posting has malformed locations.")
    places = []
    for location in locations:
        address = location.get("address", {}) if isinstance(location, dict) else None
        if not isinstance(address, dict):
            raise FetchError("partial", "iCIMS structured posting has malformed locations.")
        places.append(", ".join(text(address.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry")
                                if address.get(k) and address[k] != "UNAVAILABLE"))
    identifier = item.get("identifier")
    req = identifier.get("value", "") if isinstance(identifier, dict) else identifier
    row = _base({"id": ident}, "iCIMS", company_id, company)
    row.update(title=text(item["title"]), description=text(item["description"]), req_id=text(req or ident),
               url=url, location="; ".join(dict.fromkeys(filter(None, places))),
               department=text(item.get("occupationalCategory")), compensation=text(item.get("baseSalary")),
               work_arrangement="Remote" if item.get("jobLocationType") == "TELECOMMUTE" else "",
               created_at=text(item.get("datePosted")))
    if not row["title"] or not row["description"]:
        raise FetchError("partial", "iCIMS structured posting has empty normalized content.")
    return row


def fetch_icims(board, root, company_id, company, transport):
    source = root + board
    query = dict(parse_qsl(urlsplit(source).query))
    endpoint = source.split("?", 1)[0]
    jobs, seen = [], set()
    expected_pages, first_entries = None, []
    context = "iCIMS listing"
    try:
        for page in range(MAX_PAGES):
            context = f"iCIMS listing page {page + 1}"
            url = endpoint + "?" + urlencode({**query, "ss": "1", "in_iframe": "1", "pr": page})
            total, entries = _listing(_html(url, transport), source, page + 1)
            if expected_pages is None:
                expected_pages, first_entries = total, entries
            elif total != expected_pages:
                raise FetchError("partial", "iCIMS page count changed during the scan.")
            for ident, url in entries:
                if ident in seen:
                    raise FetchError("partial", "iCIMS repeated a posting or results page.")
                seen.add(ident)
                context = "iCIMS job detail " + url
                jobs.append(_posting(_html(url + "?in_iframe=1", transport), ident, url, company_id, company))
            print(json.dumps({"event": "inventory_page", "provider": "iCIMS", "company_id": company_id,
                              "page": page + 1, "pages": total, "postings_fetched": len(jobs)}), file=sys.stderr)
            if page + 1 >= total:
                break
        else:
            raise FetchError("partial", "iCIMS page cap reached before the inventory ended.")
        if expected_pages > 1:
            context = "iCIMS final listing check"
            url = endpoint + "?" + urlencode({**query, "ss": "1", "in_iframe": "1", "pr": 0})
            total, entries = _listing(_html(url, transport), source, 1)
            if total != expected_pages or entries != first_entries:
                raise FetchError("partial", "iCIMS board changed during the scan; retry for a complete inventory.")
        return Inventory("complete", jobs, f"iCIMS: retrieved {len(jobs)} full postings across {expected_pages} results pages.", source)
    except FetchError as error:
        status = "blocked" if error.status == "blocked" else ("partial" if jobs else error.status)
        return Inventory(status, jobs, context + ": " + error.reason, source)
    except (ValueError, TypeError, AttributeError):
        return Inventory("partial", jobs, context + ": invalid or missing portal data; no complete inventory established.", source)
    except OSError:
        return Inventory("partial" if jobs else "failed", jobs, context + ": network failure; inventory incomplete.", source)
