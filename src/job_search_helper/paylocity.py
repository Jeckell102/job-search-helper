"""Public Paylocity boards and HTML details, verified on 2026-09-23.

The public React listing uses window.pageData.Jobs as its entire inventory;
filtering and sorting are client-side. Listing descriptions are only excerpts.
"""
from __future__ import annotations

from html.parser import HTMLParser
import json
import re
import sys
from urllib.parse import parse_qsl, urljoin, urlsplit

from .ats import FetchError, HTTPResponse, Inventory, _base, _challenge, _safe_api_url, text


HOST = "recruiting.paylocity.com"
ROOT = f"https://{HOST}/Recruiting/Jobs/All/"
DETAIL = f"https://{HOST}/Recruiting/Jobs/Details/"
UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
BOARD_PATH = re.compile(r"/recruiting/jobs/all/(" + UUID + r")(?:/[a-z0-9_-]+)?/?", re.I)
DETAIL_PATH = re.compile(r"/recruiting/jobs/details/([1-9][0-9]{0,15})/?", re.I)
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_JOBS = 4000
VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})


def _public_url(url):
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname != HOST or p.username or p.password or p.port not in (None, 443):
        raise ValueError("Provide a verified public Paylocity HTTPS board URL.")
    if p.fragment:
        raise ValueError("Paylocity URL fragments/filters are unsupported; verify the unfiltered company board.")
    for key, _ in parse_qsl(p.query, keep_blank_values=True, max_num_fields=50):
        if not key.startswith("utm_"):
            raise ValueError("Unsupported Paylocity URL parameter; use the unfiltered public company board.")
    return p


def resolve_paylocity(ats, url):
    p = _public_url(url)
    match = BOARD_PATH.fullmatch(p.path)
    if not match:
        raise ValueError("Paylocity requires a verified /Recruiting/Jobs/All/COMPANY_UUID board, not an individual job or application URL.")
    configured = ats.casefold()
    if any(name in configured for name in ("greenhouse", "lever", "ashby", "workday", "icims", "adp")) and "paylocity" not in configured:
        raise ValueError("ATS / Source disagrees with the verified ATS URL.")
    if any(marker in configured for marker in ("shared", "parent")):
        raise ValueError("Shared/parent Paylocity board requires manual company scoping; filters are not supported.")
    return "Paylocity", match[1].lower(), ROOT


def safe_portal_path(parsed):
    return (not parsed.query and not parsed.fragment
            and bool(BOARD_PATH.fullmatch(parsed.path) or DETAIL_PATH.fullmatch(parsed.path)))


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.scripts, self.urls, self.links = [], [], []
        self.titles, self.locations, self.sections = [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        parent = self.stack[-1] if self.stack else {}
        state = {"tag": tag, "capture": parent.get("capture"), "skip": parent.get("skip", False),
                 "details": parent.get("details", False) or "job-preview-details" in classes}
        if tag == "meta" and attrs.get("property") == "og:url":
            self.urls.append(attrs.get("content", ""))
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in {"script", "style"}:
            state["skip"] = True
            if tag == "script" and not attrs.get("src"):
                self.scripts.append([])
                state.update(capture=self.scripts[-1], skip=False)
        for marker, collection in (("job-preview-title", self.titles), ("preview-location", self.locations)):
            if marker in classes:
                collection.append([])
                state["capture"] = collection[-1]
        if state["details"] and "job-listing-header" in classes:
            section = {"label": [], "value": None}
            self.sections.append(section)
            parent["pending"] = section
            state["capture"] = section["label"]
        elif tag == "div" and parent.get("pending") is not None:
            section = parent.pop("pending")
            section["value"] = []
            state["capture"] = section["value"]
        if state["capture"] is not None and tag in {"p", "br", "li", "div"}:
            state["capture"].append("\n")
        if tag not in VOID_TAGS:
            self.stack.append(state)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                state = self.stack[index]
                if state["capture"] is not None and tag in {"p", "li", "div"}:
                    state["capture"].append("\n")
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.stack and not self.stack[-1]["skip"] and self.stack[-1]["capture"] is not None:
            self.stack[-1]["capture"].append(data)


def _html(url, transport):
    _safe_api_url(url)
    response = transport.get(url)
    if not isinstance(response, HTTPResponse):
        raise FetchError("failed", "Paylocity transport must return HTTPResponse.")
    if response.status in (401, 403) or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Paylocity HTTP {response.status}: access denied or human verification; manual review required.")
    if not 200 <= response.status < 300:
        raise FetchError("failed", f"Paylocity HTTP {response.status}; inventory unavailable, not evidence of closure.")
    content_type = next((v for k, v in response.headers.items() if k.lower() == "content-type"), "text/html")
    if content_type.split(";", 1)[0].strip().lower() not in {"text/html", "application/xhtml+xml"}:
        raise FetchError("partial", "Paylocity returned non-HTML data.")
    if len(response.body) > MAX_HTML_BYTES:
        raise FetchError("partial", "Paylocity HTML exceeded the page size limit.")
    parser = _Page()
    parser.feed(response.body.decode("utf-8"))
    parser.close()
    return parser


def _listing(parser, board):
    data = []
    for parts in parser.scripts:
        script = "".join(parts)
        match = re.match(r"\s*window\.pageData\s*=\s*", script)
        if match:
            value, end = json.JSONDecoder().raw_decode(script, match.end())
            if script[end:].strip() not in {"", ";"}:
                raise FetchError("partial", "Paylocity listing data contains an unexpected script suffix.")
            data.append(value)
    if len(data) != 1 or not isinstance(data[0], dict):
        raise FetchError("partial", "Paylocity page is missing its full embedded job inventory.")
    data = data[0]
    if len(parser.urls) != 1 or resolve_paylocity("", parser.urls[0])[1] != board:
        raise FetchError("partial", "Paylocity listing belongs to a different company board.")
    if (data.get("ShowInternal") is not False or not isinstance(data.get("Jobs"), list)
            or not re.fullmatch(r"[1-9][0-9]*", str(data.get("ModuleId", "")))):
        raise FetchError("partial", "Paylocity public listing schema is missing or internal-only.")
    lead = urlsplit(urljoin(ROOT + board, data.get("LeadJoinUrl") or ""))
    if lead.scheme != "https" or lead.hostname != HOST or lead.path.casefold() != "/recruiting/publicleads/new/" + board:
        raise FetchError("partial", "Paylocity embedded inventory does not confirm the configured company UUID.")
    jobs, seen = data["Jobs"], set()
    if len(jobs) > MAX_JOBS:
        raise FetchError("partial", "Paylocity job limit reached; inventory incomplete.")
    for job in jobs:
        if (not isinstance(job, dict) or type(job.get("JobId")) is not int
                or not 0 < job["JobId"] < 10**16 or job.get("IsInternal") is not False
                or not isinstance(job.get("JobTitle"), str) or not job["JobTitle"].strip()):
            raise FetchError("partial", "Paylocity listing contains a malformed or internal-only posting.")
        if job["JobId"] in seen:
            raise FetchError("partial", "Paylocity listing repeats a posting ID.")
        seen.add(job["JobId"])
    return sorted(jobs, key=lambda job: job["JobId"])


def _joined(parts):
    # HTMLParser has already decoded entities; do not parse literal text as HTML again.
    return "\n".join(line.strip() for line in "".join(parts).splitlines() if line.strip())


def _posting(parser, listing, board, company_id, company):
    ident = str(listing["JobId"])
    if len(parser.urls) != 1:
        raise FetchError("partial", "Paylocity detail lacks its canonical posting identity.")
    p = _public_url(parser.urls[0])
    match = DETAIL_PATH.fullmatch(p.path)
    if not match or match[1] != ident:
        raise FetchError("partial", "Paylocity detail ID disagrees with its listing.")
    boards = set()
    for link in parser.links:
        target = urljoin(DETAIL + ident, link)
        if BOARD_PATH.fullmatch(urlsplit(target).path):
            boards.add(resolve_paylocity("", target)[1])
    if boards != {board}:
        raise FetchError("partial", "Paylocity detail does not confirm its company board.")
    sections = {}
    for section in parser.sections:
        label = _joined(section["label"])
        if label in sections or section["value"] is None:
            raise FetchError("partial", "Paylocity detail contains duplicate or incomplete sections.")
        sections[label] = _joined(section["value"])
    if len(parser.titles) != 1 or not sections.get("Description"):
        raise FetchError("partial", "Paylocity detail is missing its title or full description.")
    title = _joined(parser.titles[0])
    if " ".join(title.split()) != " ".join(text(listing["JobTitle"]).split()):
        raise FetchError("partial", "Paylocity title changed between listing and detail.")
    description = sections["Description"]
    if sections.get("Requirements"):
        description += "\n\nRequirements\n" + sections["Requirements"]
    row = _base({"id": ident}, "Paylocity", company_id, company)
    row.update(title=title, description=description, url=DETAIL + ident,
               location="; ".join(filter(None, (_joined(parts) for parts in parser.locations))) or text(listing.get("LocationName")),
               department=text(listing.get("HiringDepartment")), created_at=text(listing.get("PublishedDate")),
               compensation=sections.get("Salary Description", ""),
               work_arrangement="Remote" if listing.get("IsRemote") is True else "")
    return row


def fetch_paylocity(board, root, company_id, company, transport):
    source, jobs = root + board, []
    context = "Paylocity listing"
    try:
        entries = _listing(_html(source, transport), board)
        for entry in entries:
            context = f"Paylocity job detail {entry['JobId']}"
            jobs.append(_posting(_html(DETAIL + str(entry["JobId"]), transport), entry, board, company_id, company))
            print(json.dumps({"event": "inventory_page", "provider": "Paylocity", "company_id": company_id,
                              "postings_fetched": len(jobs), "total": len(entries)}), file=sys.stderr)
        context = "Paylocity final listing check"
        if _listing(_html(source, transport), board) != entries:
            raise FetchError("partial", "Paylocity board changed during the scan; retry for a complete inventory.")
        return Inventory("complete", jobs, f"Paylocity: retrieved {len(jobs)} full postings and rechecked the public inventory.", source)
    except FetchError as error:
        status = "blocked" if error.status == "blocked" else ("partial" if jobs else error.status)
        return Inventory(status, jobs, context + ": " + error.reason, source)
    except (ValueError, TypeError, AttributeError):
        return Inventory("partial", jobs, context + ": invalid or missing public page data; no complete inventory established.", source)
    except OSError:
        return Inventory("partial" if jobs else "failed", jobs, context + ": network failure; inventory incomplete.", source)
