"""Annapolis Micro Systems' published first-party careers pages.

These are ordinary WordPress pages, without an ATS or requisition numbers.
The inventory is the union of the careers page and its linked categories;
descriptions come only from each role's article, never the shared sidebar.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, HTTPResponse, HTTPTransport, Inventory, _base, _challenge, text
from .discovery import CareersTransport


SOURCE = "https://www.annapmicro.com/careers-at-annapolis-micro-systems/"
HOST = "www.annapmicro.com"
PREFIX = "/careers-at-annapolis-micro-systems/"
ATS = "Annapolis Micro careers"
COMPANY_ID = "COMP-0427"
MAX_PAGES = 128
MAX_REDIRECTS = 4

_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
})
_IGNORED_TAGS = frozenset({"script", "style", "noscript", "template", "form"})
_NON_JOB_SLUGS = frozenset({"apply-now", "feed", "comments"})
_APPLICATION_LINK = re.compile(
    r"\bapply now\b|\b(?:complete|submit|online)(?:\s+\w+){0,4}\s+application\b",
    re.IGNORECASE,
)
_LISTING_TITLE = re.compile(r"\b(?:careers?|jobs?|openings?|positions|co-op)\b", re.IGNORECASE)
_GENERIC_ROLE_TITLE = re.compile(
    r"(?:careers?|openings?|apply now|human resources|products|(?:.+ )?careers)",
    re.IGNORECASE,
)
_ZERO_OPENINGS = re.compile(
    r"\b(?:no (?:current |open |available )?(?:jobs|positions|openings|vacancies)"
    r"|(?:there are|we have) (?:currently )?no (?:open )?(?:positions|openings|jobs)"
    r"|not currently (?:hiring|recruiting))\b",
    re.IGNORECASE,
)


class _Transport(Protocol):
    def get(self, url: str) -> HTTPResponse: ...


@dataclass(frozen=True)
class _Context:
    tag: str
    ignored: bool = False
    main: bool = False
    article: bool = False
    title: bool = False
    content: bool = False
    location: bool = False


class _Page(HTMLParser):
    """Track actual element boundaries, including nested content ``div``s."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.canonicals: list[str] = []
        self.has_entry_content = False
        self._stack: list[_Context] = []
        self._title_parts: list[str] = []
        self._content_parts: list[str] = []
        self._location_parts: list[str] = []
        self._anchor: tuple[str, list[str]] | None = None

    @property
    def title(self) -> str:
        return text(" ".join(self._title_parts))

    @property
    def description(self) -> str:
        return text(" ".join(self._content_parts))

    @property
    def location(self) -> str:
        return text(" ".join(self._location_parts))

    @property
    def has_unclosed_content(self) -> bool:
        return self._anchor is not None or any(context.main or context.article for context in self._stack)

    def _finish_anchor(self) -> None:
        if self._anchor is not None:
            href, caption = self._anchor
            if not _APPLICATION_LINK.search(" ".join(caption)):
                self.links.append(href)
            self._anchor = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        parent = self._stack[-1] if self._stack else _Context("")
        classes = set((attributes.get("class") or "").split())
        ignored = parent.ignored or tag in _IGNORED_TAGS or "hidden" in attributes
        main = parent.main or tag == "main" or attributes.get("id") in {"main", "content", "primary"}
        article = parent.article or tag == "article"
        title = parent.title or (article and "entry-title" in classes)
        content = parent.content or (article and "entry-content" in classes)
        location = parent.location or (content and tag == "h4"
                                       and not any(part.strip() for part in self._content_parts))
        context = _Context(tag, ignored, main, article, title, content, location)

        if tag == "link" and "canonical" in (attributes.get("rel") or "").split():
            if attributes.get("href"):
                self.canonicals.append(attributes["href"])
        if main and not ignored and tag == "a" and attributes.get("href"):
            self._finish_anchor()
            self._anchor = (attributes["href"], [attributes.get("title") or ""])
        if article and "entry-content" in classes and not ignored:
            self.has_entry_content = True
        if not ignored and content and tag in {"br", "p", "li", "h2", "h3", "h4", "div"}:
            self._content_parts.append(" ")
        if tag not in _VOID_TAGS:
            self._stack.append(context)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._finish_anchor()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if not self._stack or self._stack[-1].ignored:
            return
        context = self._stack[-1]
        if self._anchor is not None:
            self._anchor[1].append(data)
        if context.title:
            self._title_parts.append(data)
        if context.content:
            self._content_parts.append(data)
        if context.location:
            self._location_parts.append(data)


def _scoped_url(value: str, base: str = SOURCE) -> str | None:
    """Normalize slash/fragment aliases without escaping the careers tree."""
    try:
        if not isinstance(value, str) or not value or any(ord(char) <= 32 for char in value):
            return None
        if "\\" in value:
            return None
        parsed = urlsplit(urljoin(base, value))
        in_tree = parsed.path.startswith(PREFIX) or parsed.path == PREFIX.rstrip("/")
        if (parsed.scheme != "https" or parsed.hostname != HOST or not in_tree
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.query):
            return None
        segments = parsed.path.strip("/").split("/")
        if any(not re.fullmatch(r"[A-Za-z0-9_-]+", segment) for segment in segments):
            return None
        return f"https://{HOST}/{'/'.join(segments)}/"
    except (TypeError, ValueError):
        return None


def _is_verified_source(url: str, company_id: str, company: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == "annapolis micro systems"
                and parsed.scheme == "https" and not parsed.fragment
                and _scoped_url(url) == SOURCE)
    except (TypeError, ValueError, AttributeError):
        return False


def _is_listing_url(url: str) -> bool:
    relative = urlsplit(url).path[len(PREFIX):].strip("/")
    segments = relative.split("/") if relative else []
    return (not segments or segments[-1].endswith("-careers")
            or segments[-1] == "co-op-program"
            or len(segments) >= 2 and segments[-2] == "page" and segments[-1].isdigit())


def _is_excluded(url: str) -> bool:
    segments = urlsplit(url).path.rstrip("/").casefold().split("/")
    return segments[-1] in _NON_JOB_SLUGS or any(segment.startswith("apply-now") for segment in segments)


def _read_page(client: _Transport, url: str) -> tuple[str, _Page]:
    current = url
    for attempt in range(MAX_REDIRECTS + 1):
        try:
            response = client.get(current)
        except (OSError, TypeError, ValueError):
            raise FetchError("partial", "Annapolis Micro careers page network or response validation failed.") from None
        if response.status in {301, 302, 303, 307, 308}:
            location = next((value for key, value in response.headers.items()
                             if key.casefold() == "location"), "")
            destination = _scoped_url(location, current)
            if not destination or attempt == MAX_REDIRECTS:
                raise FetchError("partial", "Annapolis Micro careers redirect left its verified scope or exceeded its limit.")
            current = destination
            continue
        if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
            raise FetchError("blocked", f"Annapolis Micro careers page blocked (HTTP {response.status}).")
        if response.status != 200:
            raise FetchError("partial", f"Annapolis Micro careers page HTTP {response.status}.")
        page = _Page()
        page.feed(response.body.decode("utf-8", "replace"))
        page.close()
        if page.has_unclosed_content:
            raise FetchError("partial", "Annapolis Micro careers HTML ended before its main content closed.")
        canonical_urls = {_scoped_url(href, current) for href in page.canonicals}
        if None in canonical_urls or len(canonical_urls) > 1:
            raise FetchError("partial", "Annapolis Micro page has an invalid or ambiguous canonical URL.")
        return next(iter(canonical_urls), current), page
    raise AssertionError("Redirect limit must terminate the reader.")


@dataclass
class _Discovery:
    roles: set[str] = field(default_factory=set)
    listings: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    explicit_zero: bool = False
    root_status: str = "partial"


def _discover(client: _Transport) -> _Discovery:
    result = _Discovery()
    pending = deque([SOURCE])
    visited: set[str] = set()
    while pending:
        requested = pending.popleft()
        if requested in visited:
            continue
        if len(visited) + len(result.roles) >= MAX_PAGES:
            result.errors.append("Careers discovery exceeded its bounded page limit.")
            break
        visited.add(requested)
        try:
            canonical, page = _read_page(client, requested)
            if (not _is_listing_url(canonical) or not _LISTING_TITLE.search(page.title)
                    or not page.has_entry_content or not page.description):
                raise FetchError("partial", "Annapolis Micro careers listing lacks its expected article content.")
            if requested == SOURCE:
                result.root_status = "complete"
                result.explicit_zero = bool(_ZERO_OPENINGS.search(page.description))
            if canonical in result.listings:
                continue
            result.listings.add(canonical)
            for href in page.links:
                candidate = _scoped_url(href, canonical)
                if candidate is None:
                    # A new query-based job URL must not silently disappear
                    # from an otherwise successful static-page inventory.
                    parsed = urlsplit(urljoin(canonical, href))
                    if parsed.hostname == HOST and parsed.path.startswith(PREFIX) and not _is_excluded(parsed.path):
                        result.errors.append("An in-scope careers link could not be resolved safely.")
                    continue
                if _is_excluded(candidate):
                    continue
                if len(visited) + len(result.roles) >= MAX_PAGES:
                    result.errors.append("Careers discovery exceeded its bounded page limit.")
                    break
                if _is_listing_url(candidate):
                    if candidate not in visited:
                        pending.append(candidate)
                else:
                    result.roles.add(candidate)
        except FetchError as error:
            if requested == SOURCE:
                result.root_status = error.status
            result.errors.append(error.reason)
        except (AttributeError, TypeError, ValueError, OSError):
            result.errors.append("Annapolis Micro careers listing response validation failed.")
    return result


def _description_valid(page: _Page) -> bool:
    # Completeness comes from the whole article, not optional posting dates
    # or requisition metadata. Reject empty application shells.
    return (bool(page.title) and page.has_entry_content and len(page.description) >= 100
            and not _GENERIC_ROLE_TITLE.fullmatch(page.title)
            and not page.title.casefold().startswith("apply now"))


def fetch_annapolis_micro(
    url: str,
    company_id: str,
    company: str,
    transport: _Transport | None = None,
) -> Inventory:
    """Return every published role, or retain valid jobs with partial status."""
    if not _is_verified_source(url, company_id, company):
        return Inventory("unsupported", reason="Annapolis Micro adapter requires its verified company and exact official careers source.",
                         source_url=SOURCE, ats=ATS)

    # This site's public pages intermittently reject the discovery client's
    # identifying User-Agent while serving the same pages to a browser UA.
    # Keep that compatibility choice local, and pace requests conservatively.
    # The generic API transport cannot fetch ordinary website URLs; preserve
    # every custom injectable transport for fixture replay and browser use.
    client = (CareersTransport(user_agent="Mozilla/5.0", interval=1.5)
              if transport is None or type(transport) is HTTPTransport else transport)
    jobs: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    errors: list[str] = []
    try:
        initial = _discover(client)
        errors.extend(initial.errors)
        for role_url in sorted(initial.roles):
            try:
                canonical, page = _read_page(client, role_url)
                if _is_listing_url(canonical) or _is_excluded(canonical) or not _description_valid(page):
                    raise FetchError("partial", "Annapolis Micro role lacks a complete title and article description.")
                aliases[role_url] = canonical
                aliases[canonical] = canonical
                if canonical in jobs:
                    if jobs[canonical]["title"] != page.title:
                        errors.append("Role aliases disagree on their canonical job title.")
                    continue
                posting_id = urlsplit(canonical).path[len(PREFIX):].rstrip("/")
                row = _base({"id": posting_id}, ATS, company_id, company)
                row.update(title=page.title, description=page.description, url=canonical,
                           location=page.location)
                jobs[canonical] = row
            except FetchError as error:
                errors.append(error.reason)
            except (AttributeError, TypeError, ValueError, OSError):
                errors.append("Annapolis Micro role response validation failed.")

        # Recheck categories too: root-only validation would miss category-only
        # jobs being added or removed while details were downloaded.
        reread = _discover(client)
        errors.extend(reread.errors)
        canonical_initial = {aliases.get(role, role) for role in initial.roles}
        canonical_reread = {aliases.get(role, role) for role in reread.roles}
        if canonical_initial != canonical_reread or initial.listings != reread.listings:
            errors.append("The published careers inventory changed during its reread.")
        if not initial.roles and not (initial.explicit_zero and reread.explicit_zero):
            errors.append("No role links found without an explicit no-openings statement.")
        if (initial.explicit_zero and initial.roles) or (reread.explicit_zero and reread.roles):
            errors.append("The no-openings statement conflicts with published role links.")
        rows = list(jobs.values())
        if errors:
            status = "blocked" if not rows and initial.root_status == "blocked" else "partial"
            reason = " ".join(dict.fromkeys(errors))
            return Inventory(status, rows, reason, SOURCE, ATS)
        return Inventory("complete", rows,
                         f"Annapolis Micro: retrieved {len(rows)} full published role pages and rechecked all careers categories.",
                         SOURCE, ATS)
    except (AttributeError, TypeError, ValueError, OSError):
        return Inventory("partial", list(jobs.values()),
                         "Annapolis Micro careers response or article validation failed.", SOURCE, ATS)
