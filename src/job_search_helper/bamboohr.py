"""Public BambooHR careers feeds, verified against employer boards 2026-10-08.

GET /careers/list advertises totalCount; GET /careers/{id}/detail provides
the full public jobOpening. No authenticated HR API or application requests.
Employer pages linking a subset of a shared board retain that subset.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import sys
from urllib.parse import parse_qsl, urljoin, urlsplit

from .ats import FetchError, HTTPResponse, HTTPTransport, Inventory, _base, _challenge, _json, text
from .discovery import (CareersTransport, MAX_DISCOVERY_PAGES, MAX_HTML_BYTES,
                        MAX_REDIRECTS, _BoardLinks, _cta_candidates, _same_public_host,
                        public_careers_url)


MAX_JOBS = 10000
ID = re.compile(r"[1-9][0-9]{0,15}")
HOST = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\.bamboohr\.com")
RESERVED = {"www", "api", "app", "documentation", "staticfe", "help"}
BOARD_PATHS = {"/careers", "/jobs", "/jobs/embed.php", "/jobs/embed2.php", "/js/jobs.php", "/js/jobs2.php", "/js/embed.js"}


def is_bamboohr_host(host):
    return bool(HOST.fullmatch(host or "")) and host.split(".")[0] not in RESERVED


def safe_api_path(parsed):
    return (not parsed.query and not parsed.fragment and
            (parsed.path == "/careers/list" or bool(re.fullmatch(r"/careers/[1-9][0-9]{0,15}/detail", parsed.path))))


def _link(url):
    """Return tenant root and optional linked posting ID; never drop filters."""
    p = urlsplit(url)
    if (p.scheme != "https" or not is_bamboohr_host(p.hostname) or p.username or p.password
            or p.port not in (None, 443) or p.fragment or "\\" in url
            or any(ord(c) <= 32 or ord(c) == 127 for c in url)):
        raise ValueError("Provide a verified public BambooHR HTTPS careers URL.")
    params = {}
    for key, value in parse_qsl(p.query, keep_blank_values=True, max_num_fields=30):
        if key.startswith("utm_") or key == "source":
            continue
        if key in params:
            raise ValueError("Duplicate BambooHR URL filter; verify company scope.")
        params[key] = value
    path = p.path.rstrip("/")
    detail = re.fullmatch(r"/careers/([1-9][0-9]{0,15})", path)
    ident = detail[1] if detail else None
    if path == "/jobs/view.php" and set(params) == {"id"} and ID.fullmatch(params["id"]):
        ident = params.pop("id")
    elif not detail and path not in BOARD_PATHS:
        raise ValueError("BambooHR requires a public careers board or posting link.")
    if params:
        raise ValueError("BambooHR URL filters are unsupported; preserve and verify the employer scope.")
    return f"https://{p.hostname}", ident


def _configuration(ats):
    configured = ats.casefold()
    others = ("greenhouse", "lever", "ashby", "workday", "icims", "adp", "paylocity", "taleo", "phenom")
    if "bamboohr" not in configured and any(name in configured for name in others):
        raise ValueError("ATS / Source disagrees with the verified BambooHR URL.")


def resolve_bamboohr(ats, url):
    _configuration(ats)
    root, _ = _link(url)
    # Discovery groups multiple job links from one tenant. fetch_bamboohr
    # re-reads the employer page and retains its linked-job scope.
    return "BambooHR", "/careers", root


@dataclass(frozen=True)
class Scope:
    root: str
    ids: frozenset[str] | None
    source: str


def _discover(url, transport):
    origin = public_careers_url(url)
    queue, visited = [(origin, 0)], set()
    while queue and len(visited) < MAX_DISCOVERY_PAGES:
        page_url, redirects = queue.pop(0)
        if page_url in visited:
            continue
        visited.add(page_url)
        response = transport.get(page_url)
        if not isinstance(response, HTTPResponse):
            raise FetchError("failed", "BambooHR discovery transport must return HTTPResponse.")
        if response.status in (401, 403) or _challenge(response, expect_html=True):
            raise FetchError("blocked", "Employer careers page denied access or requested human verification.")
        headers = {k.lower(): v for k, v in response.headers.items()}
        if response.status in (301, 302, 303, 307, 308):
            if not headers.get("location"):
                raise FetchError("failed", "Employer careers redirect has no destination.")
            target = public_careers_url(urljoin(page_url, headers["location"]))
            if is_bamboohr_host(urlsplit(target).hostname):
                root, ident = _link(target)
                return Scope(root, frozenset({ident}) if ident else None, origin if ident else root + "/careers")
            if not _same_public_host(page_url, target):
                raise FetchError("unsupported", "Employer careers page redirects to an unverified host; verify its destination.")
            if target in visited or redirects >= MAX_REDIRECTS:
                raise FetchError("failed", "Employer careers redirect loop or limit reached.")
            queue.insert(0, (target, redirects + 1))
            continue
        if not 200 <= response.status < 300:
            raise FetchError("failed", f"Employer careers HTTP {response.status}; discovery incomplete.")
        if len(response.body) > MAX_HTML_BYTES:
            raise FetchError("partial", "Employer careers page exceeds the bounded discovery size limit.")
        if headers.get("content-type", "text/html").split(";", 1)[0].strip().lower() not in {"text/html", "application/xhtml+xml"}:
            raise FetchError("partial", "Employer careers discovery expected HTML.")
        parser = _BoardLinks(page_url)
        parser.feed(response.body.decode("utf-8"))
        parser.close()
        roots = {}
        for link in parser.links:
            candidate = urljoin(parser.base_url, link)
            if not is_bamboohr_host(urlsplit(candidate).hostname):
                continue
            # Non-careers assets on the tenant host are not board evidence.
            path = urlsplit(candidate).path
            if not path.startswith(("/careers", "/jobs", "/js/jobs", "/js/embed")):
                continue
            root, ident = _link(candidate)
            roots.setdefault(root, set())
            if ident:
                roots[root].add(ident)
        if len(roots) > 1:
            raise FetchError("unsupported", "Multiple BambooHR tenants linked; select the employer's board explicitly.")
        if roots:
            root, ids = next(iter(roots.items()))
            # Specific job links constrain the scope even if a generic parent
            # board link also appears elsewhere on the employer page.
            return Scope(root, frozenset(ids) if ids else None, origin if ids else root + "/careers")
        for candidate in _cta_candidates(parser, origin):
            if candidate not in visited and all(candidate != item[0] for item in queue):
                queue.append((candidate, 0))
    raise FetchError("partial", "No verified BambooHR board found within the bounded employer-page discovery.")


def _listing(root, transport):
    data = _json(root + "/careers/list", transport)
    if not isinstance(data, dict) or not isinstance(data.get("meta"), dict) or not isinstance(data.get("result"), list):
        raise FetchError("partial", "BambooHR public list is missing its inventory metadata.")
    entries, total = data["result"], data["meta"].get("totalCount")
    if type(total) is not int or not 0 <= total <= MAX_JOBS or len(entries) != total:
        raise FetchError("partial", "BambooHR totalCount does not match the full public list or exceeds the job limit.")
    # The observed feed returns its whole inventory. If it starts paginating,
    # a cursor/next link must never be silently treated as a complete list.
    if any(data["meta"].get(k) for k in ("next", "nextPage", "nextCursor", "hasMore")):
        raise FetchError("partial", "BambooHR reports additional pages; inventory incomplete.")
    seen = set()
    for item in entries:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str) or not ID.fullmatch(item["id"])
                or not isinstance(item.get("jobOpeningName"), str) or not item["jobOpeningName"].strip()):
            raise FetchError("partial", "BambooHR list contains invalid posting identity or title.")
        if item["id"] in seen:
            raise FetchError("partial", "BambooHR list contains duplicate posting IDs.")
        seen.add(item["id"])
    return sorted(entries, key=lambda item: int(item["id"]))


def _location(job):
    parts = []
    for name, fields in (("location", ("city", "state", "province", "addressCountry")),
                         ("atsLocation", ("city", "state", "province", "country"))):
        location = job.get(name) or {}
        if not isinstance(location, dict):
            raise FetchError("partial", "BambooHR job has malformed location data.")
        for field in fields:
            value = location.get(field)
            if value is not None and not isinstance(value, str):
                raise FetchError("partial", "BambooHR job has malformed location fields.")
            if value and value.strip() and value not in parts:
                parts.append(value)
    return ", ".join(parts)


def _posting(root, entry, transport, company_id, company):
    ident = entry["id"]
    data = _json(root + "/careers/" + ident + "/detail", transport)
    job = data.get("result", {}).get("jobOpening", {}) if isinstance(data, dict) else {}
    if not isinstance(job, dict):
        raise FetchError("partial", "BambooHR public job detail is missing.")
    try:
        detail_root, detail_id = _link(job.get("jobOpeningShareUrl", ""))
    except (ValueError, TypeError):
        raise FetchError("partial", "BambooHR detail has no valid public posting identity.") from None
    if (detail_root != root or detail_id != ident or job.get("jobOpeningStatus") != "Open"
            or text(job.get("jobOpeningName")) != text(entry["jobOpeningName"])):
        raise FetchError("partial", "BambooHR detail identity, title, or open status disagrees with its listing.")
    if not isinstance(job.get("description"), str) or not text(job["description"]).strip():
        raise FetchError("partial", "BambooHR detail is missing its full job description.")
    location_type = str(job.get("locationType", ""))
    if location_type not in {"0", "1", "2", "", "None"}:
        raise FetchError("partial", "BambooHR detail has an unknown work-location type.")
    row = _base({"id": ident}, "BambooHR", company_id, company)
    row.update(title=text(job["jobOpeningName"]), description=text(job["description"]),
               url=root + "/careers/" + ident, location=_location(job),
               department=text(job.get("departmentLabel")), compensation=text(job.get("compensation")),
               work_arrangement={"0": "On-site", "1": "Remote", "2": "Hybrid"}.get(location_type, ""),
               created_at=str(job.get("datePosted") or ""))
    return row


def fetch_bamboohr(ats, careers_url, company_id, company, transport=None, discovery_transport=None):
    transport = transport or HTTPTransport()
    pages = discovery_transport or CareersTransport()
    jobs, source, context = [], careers_url, "BambooHR board discovery"
    try:
        _configuration(ats)
        configured = public_careers_url(careers_url)
        direct = is_bamboohr_host(urlsplit(configured).hostname)
        if direct:
            root, ident = _link(careers_url)
            if ident:
                raise FetchError("unsupported", "A single BambooHR posting cannot establish company inventory; use its verified /careers board.")
            if any(k in ats.casefold() for k in ("shared", "parent")):
                raise FetchError("unsupported", "Shared/parent BambooHR board needs the employer's scoped careers page.")
            scope = Scope(root, None, root + "/careers")
        else:
            if urlsplit(careers_url).fragment or urlsplit(careers_url).query:
                raise FetchError("unsupported", "Employer-page query/fragment filters require verified BambooHR scope.")
            scope = _discover(configured, pages)
            if scope.ids is None and any(k in ats.casefold() for k in ("shared", "parent")):
                raise FetchError("unsupported", "Shared/parent BambooHR page does not establish a company-specific posting scope.")
        source = scope.source
        context = "BambooHR public inventory"
        entries = _listing(scope.root, transport)
        board_ids = {item["id"] for item in entries}
        selected = entries if scope.ids is None else [item for item in entries if item["id"] in scope.ids]
        issues = []
        # Safran Federal's official page explicitly embeds its openings
        # from a shared tenant board that also carries other Safran
        # entities.  The employer page is the authoritative company scope.
        saf_fs_scoped = (
            company_id == "COMP-0263"
            and company.casefold() == "safran federal systems"
            and configured.rstrip("/") == "https://www.safranfederalsystems.com/open-roles"
            and scope.root.rstrip("/") == "https://safransed.bamboohr.com"
            and scope.source.rstrip("/") == configured.rstrip("/")
            and bool(scope.ids)
            and scope.ids <= board_ids
        )
        if scope.ids is not None and scope.ids != board_ids and not saf_fs_scoped:
            issues.append("Employer page links a subset or stale postings on the BambooHR board; only its listed open jobs were retrieved, and company inventory completeness is unverified.")
        for item in selected:
            context = f"BambooHR job detail {item['id']}"
            jobs.append(_posting(scope.root, item, transport, company_id, company))
            print(json.dumps({"event": "inventory_page", "provider": "BambooHR", "company_id": company_id,
                              "postings_fetched": len(jobs), "total": len(selected)}), file=sys.stderr)
        if saf_fs_scoped and any("safran federal systems" not in " ".join(job["description"].split()).casefold() for job in jobs):
            issues.append("A corporate-linked posting does not identify Safran Federal Systems; company scope requires review.")
        context = "BambooHR final inventory check"
        if _listing(scope.root, transport) != entries:
            raise FetchError("partial", "BambooHR public inventory changed during the scan; retry to establish completeness.")
        if not direct and _discover(configured, pages) != scope:
            raise FetchError("partial", "Employer careers-page scope changed during the scan.")
        reason = f"BambooHR: retrieved {len(jobs)} full postings and rechecked the public inventory."
        if not direct:
            reason += f" Discovered tenant {scope.root} from the configured employer careers page."
        return Inventory("partial" if issues else "complete", jobs, reason + (" " + " ".join(issues) if issues else ""), source, "BambooHR")
    except FetchError as error:
        status = "blocked" if error.status == "blocked" else ("partial" if jobs else error.status)
        return Inventory(status, jobs, context + ": " + error.reason, source, "BambooHR")
    except (ValueError, TypeError, AttributeError, KeyError):
        return Inventory("partial" if jobs else "unsupported", jobs,
                         context + ": invalid URL/configuration or malformed public data; no complete inventory established.", source, "BambooHR")
    except OSError:
        return Inventory("partial" if jobs else "failed", jobs, context + ": network failure; inventory incomplete.", source, "BambooHR")
