"""Company-scoped Taleo listings rendered on an employer careers page.

Some employers expose a scoped, paginated career search while linking each
posting to a shared Taleo parent board.  Following one of those links and then
inventorying the parent board loses the employer scope.  This adapter reads the
authoritative scoped listing instead.
"""
from __future__ import annotations

from html.parser import HTMLParser
import math
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

from .ats import FetchError, HTTPResponse, Inventory, _base, _challenge
from .posting import plain_text
from .taleo import BOARD, is_taleo_host


MAX_CAREERS_PAGES = 100
MAX_CAREERS_JOBS = 1000
COUNT = re.compile(r"\b([0-9][0-9,]*)\s+job\(s\)\s+match your search criteria\b", re.I)
FIELD_CLASSES = {
    "career-reference__city": "city",
    "career-reference__state": "state",
    "career-reference__country": "country",
    "career-reference__date": "date",
    "career-reference__reference-number": "reference",
    "accordion__content__inner": "description",
}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def supports_scoped_taleo_careers(ats: str, url: str) -> bool:
    """Return whether ``url`` is a verified scoped Taleo mirror we understand."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold().removeprefix("www.")
        configured = ats.casefold()
        return (
            parsed.scheme == "https"
            and host == "textronsystems.com"
            and parsed.path.rstrip("/") == "/careers/apply-today"
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and not parsed.fragment
            and (not configured or "taleo" in configured)
        )
    except (TypeError, ValueError):
        return False


class _ScopedPage(HTMLParser):
    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.depth = 0
        self.parts: list[str] = []
        self.links: list[str] = []
        self.cards: list[dict] = []
        self.card: dict | None = None
        self.anchor: dict | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in VOID_TAGS:
            self.depth += 1
        classes = set(str(attrs.get("class", "")).split())
        if tag == "div" and "career-reference-wrapper" in classes and self.card is None:
            self.card = {
                "depth": self.depth,
                "parts": [],
                "fields": {name: [] for name in FIELD_CLASSES.values()},
                "active_fields": [],
                "anchors": [],
            }
        if tag == "a" and attrs.get("href"):
            href = urljoin(self.page_url, attrs["href"])
            self.links.append(href)
            if self.card is not None:
                self.anchor = {"depth": self.depth, "href": href, "classes": classes, "parts": []}
        if self.card is not None:
            for class_name, field in FIELD_CLASSES.items():
                if class_name in classes:
                    self.card["active_fields"].append((self.depth, field))
            if tag in {"p", "br", "li", "div", "h1", "h2", "h3", "h4"}:
                self.card["parts"].append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        self.parts.append(data)
        if self.card is None:
            return
        self.card["parts"].append(data)
        for _, field in self.card["active_fields"]:
            self.card["fields"][field].append(data)
        if self.anchor is not None:
            self.anchor["parts"].append(data)

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if self.card is not None:
            if self.anchor is not None and self.anchor["depth"] == self.depth:
                self.card["anchors"].append(self.anchor)
                self.anchor = None
            self.card["active_fields"] = [
                item for item in self.card["active_fields"] if item[0] != self.depth
            ]
            if tag == "div" and self.card["depth"] == self.depth:
                self.cards.append(self.card)
                self.card = None
        self.depth = max(0, self.depth - 1)

    @property
    def total(self) -> int | None:
        match = COUNT.search(" ".join("".join(self.parts).split()))
        return int(match.group(1).replace(",", "")) if match else None


def _page(url: str, transport) -> _ScopedPage:
    response = transport.get(url)
    if not isinstance(response, HTTPResponse):
        raise FetchError("failed", "Careers transport must return HTTPResponse.")
    if response.status in (401, 403) or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Scoped careers page HTTP {response.status}: access denied or human verification.")
    if not 200 <= response.status < 300:
        raise FetchError("failed", f"Scoped careers page HTTP {response.status}; inventory unavailable.")
    content_type = next((v for k, v in response.headers.items() if k.casefold() == "content-type"), "text/html")
    if content_type.split(";", 1)[0].strip().casefold() not in {"", "text/html", "application/xhtml+xml"}:
        raise FetchError("partial", "Scoped careers page returned non-HTML data.")
    parser = _ScopedPage(url)
    parser.feed(response.body.decode("utf-8", "replace"))
    parser.close()
    return parser


def _job_link(anchor: dict) -> tuple[str, str] | None:
    parsed = urlsplit(anchor["href"])
    match = BOARD.fullmatch(parsed.path)
    if not is_taleo_host(parsed.hostname) or not match or not parsed.path.casefold().endswith("/jobdetail.ftl"):
        return None
    values = dict(parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=20))
    posting_id = values.get("job", "")
    if set(values) - {"job", "lang"} or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", posting_id):
        return None
    url = parsed._replace(query=urlencode({"job": posting_id}), fragment="").geturl()
    return posting_id, url


def _value(card: dict, field: str) -> str:
    return plain_text(" ".join(card["fields"][field]))


def _posting(card: dict, company_id: str, company: str) -> dict | None:
    choices = []
    for anchor in card["anchors"]:
        linked = _job_link(anchor)
        if linked:
            choices.append((anchor, linked))
    if not choices:
        return None
    anchor, (posting_id, url) = choices[0]
    title = plain_text(" ".join(anchor["parts"]))
    if not title or title.casefold() in {"learn more & apply", "apply", "learn more"}:
        title = next((plain_text(" ".join(item["parts"])) for item, linked in choices
                      if linked[0] == posting_id and plain_text(" ".join(item["parts"])).casefold()
                      not in {"learn more & apply", "apply", "learn more"}), "")
    description = _value(card, "description") or plain_text(" ".join(card["parts"]))
    if not title or not description:
        return None
    reference = _value(card, "reference")
    reference_match = re.search(r"([A-Za-z0-9_.-]{1,80})\s*$", reference)
    if reference_match and reference_match.group(1) != posting_id:
        return None
    location = ", ".join(part.rstrip(" ,") for part in (
        _value(card, "city"), _value(card, "state"), _value(card, "country")
    ) if part.rstrip(" ,"))
    created_at = re.sub(r"^Posted Date:\s*", "", _value(card, "date"), flags=re.I)
    row = _base({"id": posting_id}, "Taleo", company_id, company)
    row.update(
        req_id=posting_id,
        title=title,
        url=url,
        location=location,
        work_arrangement="Remote" if "remote" in f"{location} {description}".casefold() else "",
        description=description,
        department="",
        created_at=created_at,
        is_listed=True,
    )
    return row


def _pagination_links(parser: _ScopedPage, source: str) -> list[str]:
    origin = urlsplit(source)
    results = []
    for link in parser.links:
        parsed = urlsplit(link)
        if (parsed.scheme, parsed.hostname, parsed.path.rstrip("/")) != (
                origin.scheme, origin.hostname, origin.path.rstrip("/")) or parsed.fragment:
            continue
        try:
            values = dict(parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=10))
        except ValueError:
            continue
        page = values.get("page", "")
        if set(values) == {"page"} and page.isdigit() and int(page) < MAX_CAREERS_PAGES:
            results.append(source if int(page) == 0 else parsed._replace(
                query=urlencode({"page": int(page)}), fragment=""
            ).geturl())
    return results


def _numbered_page(source: str, number: int) -> str:
    if number == 0:
        return source
    return urlsplit(source)._replace(query=urlencode({"page": number}), fragment="").geturl()


def fetch_scoped_taleo_careers(careers_url: str, company_id: str, company: str, transport) -> Inventory:
    """Fetch every job from a verified employer-scoped Taleo mirror."""
    source = urlsplit(careers_url)._replace(query="", fragment="").geturl()
    jobs: list[dict] = []
    seen: set[str] = set()
    queue = [source]
    visited: set[str] = set()
    expected_total = None
    maximum_total = None
    first_ids: list[str] | None = None
    issues: list[str] = []
    try:
        while queue and len(visited) < MAX_CAREERS_PAGES and len(jobs) < MAX_CAREERS_JOBS:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            parser = _page(url, transport)
            if expected_total is None:
                expected_total = parser.total
            elif parser.total is not None and parser.total != expected_total:
                issues.append("Scoped careers listing count changed during pagination.")
            if parser.total is not None:
                maximum_total = max(maximum_total or 0, parser.total)
            page_ids = []
            for card in parser.cards:
                row = _posting(card, company_id, company)
                if row is None:
                    issues.append("One or more scoped careers postings were malformed or incomplete.")
                    continue
                page_ids.append(row["posting_id"])
                if row["posting_id"] in seen:
                    continue
                seen.add(row["posting_id"])
                jobs.append(row)
            if first_ids is None:
                first_ids = page_ids
            for link in _pagination_links(parser, source):
                if link not in visited and link not in queue:
                    queue.append(link)
            if maximum_total is not None and parser.cards:
                page_count = min(MAX_CAREERS_PAGES, math.ceil(maximum_total / len(parser.cards)))
                for number in range(page_count):
                    link = _numbered_page(source, number)
                    if link not in visited and link not in queue:
                        queue.append(link)
        if expected_total is None:
            issues.append("Scoped careers page did not expose a trustworthy listing total.")
        elif len(jobs) != maximum_total:
            issues.append(f"Scoped careers page returned {len(jobs)} unique postings out of maximum reported total {maximum_total}.")
        if queue and len(visited) >= MAX_CAREERS_PAGES:
            issues.append("Scoped careers pagination limit was reached.")
        if len(jobs) >= MAX_CAREERS_JOBS and expected_total != len(jobs):
            issues.append("Scoped careers job limit was reached.")
        if not issues and first_ids is not None:
            check = _page(source, transport)
            check_ids = [row["posting_id"] for row in (
                _posting(card, company_id, company) for card in check.cards
            ) if row is not None]
            if check.total != expected_total or check_ids != first_ids:
                issues.append("Scoped careers page changed during the scan; retry for a complete inventory.")
        status = "partial" if issues else "complete"
        reason = f"Scoped Taleo careers page: retrieved {len(jobs)} full postings."
        if issues:
            reason = " ".join(dict.fromkeys(issues))
        return Inventory(status, jobs, reason, source, ats="Taleo")
    except FetchError as exc:
        status = "partial" if jobs else exc.status
        reason = exc.reason + (f" Retained {len(jobs)} scoped postings fetched before the failure." if jobs else "")
        return Inventory(status, jobs, reason, source, ats="Taleo")
    except (OSError, ValueError, TypeError, AttributeError):
        return Inventory("partial" if jobs else "failed", jobs,
                         "Unexpected scoped Taleo careers-page failure; inventory is incomplete.", source, ats="Taleo")
