"""VideoRay's local careers role plus its attributed AVAV Workday cohort."""

from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from .ats import FetchError, HTTPTransport, Inventory, _base, text
from .workday import fetch_workday


SOURCE = "https://avav.wd1.myworkdayjobs.com/en-US/AVAV?q=VideoRay"
LOCAL_SOURCE = "https://videoray.com/about-us/careers/"
LOCAL_HOST = "videoray.com"
ROOT = "https://avav.wd1.myworkdayjobs.com/wday/cxs/avav/"
BOARD = "AVAV?q=VideoRay"
HOST = "avav.wd1.myworkdayjobs.com"
COMPANY_ID = "COMP-0348"
COMPANY = "VideoRay"


class _LocalPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.title = []
        self.body = []
        self._href = ""
        self._in_title = 0
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self._href = attrs.get("href", "")
        if tag in {"script", "style", "nav", "header", "footer"}:
            self._skip += 1
        if tag in {"h1", "h2", "h3", "p", "li", "div"} and not self._skip:
            self.body.append("\n")
        if tag == "h1":
            self._in_title += 1

    def handle_endtag(self, tag):
        if tag == "a":
            if self._href:
                self.links.append(self._href)
            self._href = ""
        if tag == "h1" and self._in_title:
            self._in_title -= 1
        if tag in {"script", "style", "nav", "header", "footer"} and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.body.append(data)


def _local_url(raw):
    parsed = urlsplit(raw)
    if parsed.scheme == "" and parsed.path.startswith("/"):
        parsed = urlsplit("https://videoray.com" + parsed.path)
    if (parsed.scheme != "https" or parsed.hostname != LOCAL_HOST or parsed.query
            or parsed.fragment or parsed.username or parsed.password
            or parsed.port not in (None, 443)):
        return ""
    if not re.fullmatch(r"/about-us/careers/[a-z0-9-]+/", parsed.path, re.I):
        return ""
    return f"https://{LOCAL_HOST}{parsed.path}"


def _response_body(response):
    if getattr(response, "status", 0) != 200:
        raise FetchError("partial", f"VideoRay source returned HTTP {getattr(response, 'status', 0)}.")
    body = getattr(response, "body", b"")
    if not isinstance(body, bytes):
        raise FetchError("partial", "VideoRay source returned a malformed body.")
    return body.decode("utf-8", "replace")


def _local_jobs(transport):
    page = _LocalPage()
    page.feed(_response_body(transport.get(LOCAL_SOURCE)))
    urls = []
    for raw in page.links:
        url = _local_url(raw)
        if url and url not in urls:
            urls.append(url)
    jobs = []
    for url in urls:
        detail = _LocalPage()
        detail.feed(_response_body(transport.get(url)))
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        title = text(" ".join(detail.title) or slug.replace("-", " "))
        description = text(" ".join(detail.body))
        if not title or not description:
            raise FetchError("partial", "VideoRay local role is missing its title or full description.")
        row = _base({"id": f"videoray-local:{slug}"}, "VideoRay local careers", COMPANY_ID, COMPANY)
        row.update(title=title, description=description, url=url, location="Pottstown, PA")
        jobs.append(row)
    if not jobs:
        raise FetchError("partial", "VideoRay local careers page exposed no canonical role links.")
    return jobs


def _attributed_parent(row):
    values = [row.get(key, "") for key in ("employer", "legal_entity", "organization")]
    joined = " ".join(text(value) for value in values).casefold()
    if "videoray" in joined:
        return True
    # AVAV currently omits employer/legal-entity metadata from this tenant's
    # public details.  Accept only explicit segment/product ownership text; a
    # free-text mention of VideoRay alone is not attribution.
    description = text(row.get("description", "")).casefold()
    return any(marker in description for marker in ("videoray segment", "videoray products"))


def _deduplicate(local_jobs, parent_jobs):
    combined = []
    seen_urls = set()
    fingerprints = {}
    for row in [*parent_jobs, *local_jobs]:
        url = row.get("url", "")
        fingerprint = (text(row.get("title")).casefold(), text(row.get("location")).casefold())
        # The local WordPress role and its AV Workday mirror can carry
        # different markup/boilerplate while describing the same opening.
        # Title + normalized location is the conservative overlap key; the
        # parent row wins so its Workday canonical ID is preserved.
        if url in seen_urls or fingerprint in fingerprints:
            continue
        seen_urls.add(url)
        fingerprints[fingerprint] = True
        combined.append(row)
    return combined


def _is_videoray_source(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == HOST
        and parsed.path.rstrip("/") in {"/en-US/AVAV", "/wday/cxs/avav/AVAV"}
        and parsed.query == "q=VideoRay"
        and not parsed.fragment
    )


def fetch_videoray(careers_url, company_id, company, transport=None, discovery_transport=None):
    """Fetch local VideoRay roles and explicitly attributed AVAV roles."""
    if company_id != COMPANY_ID or company.casefold() != COMPANY.casefold():
        return Inventory("unsupported", reason="VideoRay adapter received the wrong company identity.", source_url=careers_url)
    if not _is_videoray_source(careers_url):
        return Inventory("unsupported", reason="VideoRay source is not the verified AVAV Workday VideoRay search.", source_url=careers_url)
    transport = transport or HTTPTransport()
    discovery_transport = discovery_transport or transport
    try:
        local_jobs = _local_jobs(discovery_transport)
        parent = fetch_workday(BOARD, ROOT, company_id, company, transport)
        if parent.status != "complete":
            return Inventory("partial", jobs=local_jobs, reason="AVAV parent board could not be completely verified: " + parent.reason,
                             source_url=careers_url, ats="VideoRay local + AVAV Workday")
        unattributed = [job for job in parent.jobs if not _attributed_parent(job)]
        if unattributed:
            return Inventory("partial", jobs=local_jobs, reason="AVAV returned roles without VideoRay employer/legal-entity attribution.",
                             source_url=careers_url, ats="VideoRay local + AVAV Workday")
        jobs = _deduplicate(local_jobs, parent.jobs)
        result = Inventory("complete", jobs=jobs, source_url=careers_url, ats="VideoRay local + AVAV Workday")
        return result
    except FetchError as exc:
        return Inventory(exc.status, reason=exc.reason, source_url=careers_url, ats="VideoRay local + AVAV Workday")
