"""Public Oracle Taleo career-section listings and details.

Verified against standard ``*.taleo.net/careersection`` public boards. The adapter
uses the same public search endpoint loaded by the job-search page and never
submits applications, follows application links, sends cookies, or uses a login.
"""
from __future__ import annotations

from html.parser import HTMLParser
import json
import re
import sys
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from .ats import FetchError, HTTPResponse, Inventory, _base, _challenge, _json, _safe_api_url, text


HOST = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\.taleo\.net")
BOARD = re.compile(r"/careersection/([A-Za-z0-9][A-Za-z0-9_.-]{0,127})/(?:jobsearch|moresearch|jobdetail|jobapply)\.ftl", re.I)
SEARCH_PATH = "/careersection/rest/jobboard/searchjobs"
MAX_HTML_BYTES = 4 * 1024 * 1024
MAX_PAGES = 200
PAGE_SIZE = 25
MAX_JOBS = 5000


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inputs = []
        self.metas = []
        self.raw = ""
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style"}:
            self.skip += 1
        if tag == "input":
            self.inputs.append(attrs)
        if tag == "meta":
            self.metas.append(attrs)
        if tag in {"p", "br", "li", "div", "h1", "h2", "h3", "td", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1
        if tag in {"p", "li", "div", "td", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def is_taleo_host(host: str | None) -> bool:
    return bool(HOST.fullmatch(host or ""))


def _language(value: str | None) -> str:
    value = value or "en"
    if not re.fullmatch(r"[a-z]{2}(?:_[A-Z]{2}|-[A-Z]{2})?", value):
        raise ValueError("Unsupported Taleo language parameter; use the unfiltered public board URL.")
    return value


def _public_url(url: str):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not is_taleo_host(parsed.hostname) or parsed.username
            or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError("Provide a verified public Taleo HTTPS career-section URL.")
    return parsed


def _query(parsed, *, detail=False):
    values = {}
    for key, value in parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=30):
        if key.startswith("utm_") or key in {"src", "source", "ignoreSavedQuery", "radiusType"}:
            continue
        if key == "lang":
            values["lang"] = _language(value)
        elif detail and key == "job" and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value):
            values["job"] = value
        else:
            raise ValueError("Unsupported Taleo URL parameter or filter; verify the public job-search URL.")
    values.setdefault("lang", "en")
    return values


def resolve_taleo(ats: str, url: str):
    parsed = _public_url(url)
    match = BOARD.fullmatch(parsed.path)
    if not match:
        raise ValueError("Taleo requires a verified /careersection/BOARD/jobsearch.ftl public board URL.")
    detail = parsed.path.casefold().endswith(("/jobdetail.ftl", "/jobapply.ftl"))
    params = _query(parsed, detail=detail)
    configured = ats.casefold()
    if any(name in configured for name in ("greenhouse", "lever", "ashby", "workday", "icims", "adp", "paylocity")) and "taleo" not in configured:
        raise ValueError("ATS / Source disagrees with the verified ATS URL.")
    if any(marker in configured for marker in ("shared", "parent")):
        raise ValueError("Shared/parent Taleo board requires manual company scoping; filters are not supported.")
    board = match[1] + "/jobsearch.ftl"
    if params["lang"] != "en":
        board += "?" + urlencode({"lang": params["lang"]})
    return "Taleo", board, f"https://{parsed.hostname}/careersection/"


def safe_portal_path(parsed) -> bool:
    if parsed.fragment:
        return False
    if parsed.path == SEARCH_PATH:
        try:
            values = dict(parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=20))
            return (set(values) == {"lang", "portal"} and bool(re.fullmatch(r"[0-9]{1,32}", values.get("portal", "")))
                    and bool(_language(values.get("lang"))))
        except ValueError:
            return False
    match = BOARD.fullmatch(parsed.path)
    if not match:
        return False
    try:
        _query(parsed, detail=parsed.path.casefold().endswith(("/jobdetail.ftl", "/jobapply.ftl")))
        return True
    except ValueError:
        return False


def _html(url: str, transport) -> _Page:
    _safe_api_url(url)
    response = transport.get(url)
    if not isinstance(response, HTTPResponse):
        raise FetchError("failed", "Taleo transport must return HTTPResponse.")
    if response.status in (401, 403) or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Taleo HTTP {response.status}: access denied or human verification; manual review required.")
    if not 200 <= response.status < 300:
        raise FetchError("failed", f"Taleo HTTP {response.status}; inventory unavailable, not evidence of closure.")
    content_type = next((v for k, v in response.headers.items() if k.lower() == "content-type"), "text/html")
    if content_type.split(";", 1)[0].strip().lower() not in {"", "text/html", "application/xhtml+xml"}:
        raise FetchError("partial", "Taleo returned non-HTML data.")
    if len(response.body) > MAX_HTML_BYTES:
        raise FetchError("partial", "Taleo HTML exceeded the page size limit.")
    parser = _Page()
    parser.raw = response.body.decode("utf-8", "replace")
    parser.feed(parser.raw)
    parser.close()
    return parser


def _page_text(parser: _Page) -> str:
    return "\n".join(" ".join(line.split()) for line in "".join(parser.parts).splitlines() if line.strip())


def _meta(parser: _Page, name: str) -> str:
    for item in parser.metas:
        if item.get("property", "").casefold() == name.casefold() or item.get("name", "").casefold() == name.casefold():
            return item.get("content", "")
    return ""


def _portal(parser: _Page, expected_code: str):
    body = _page_text(parser)
    haystack = parser.raw + "\n" + body + "\n" + "\n".join(str(item) for item in parser.inputs)
    portal = re.search(r"portalNo\s*[:=]\s*['\"]?([0-9]{1,32})", haystack)
    url_code = re.search(r"urlCode\s*[:=]\s*['\"]?([A-Za-z0-9_.-]{1,128})", haystack)
    lang = re.search(r"lang(?:uage)?\s*[:=]\s*['\"]?([a-z]{2}(?:[_-][A-Z]{2})?)", haystack)
    if not portal:
        # Some fixtures and older pages expose the portal number as a hidden input.
        for item in parser.inputs:
            name = (item.get("name") or item.get("id") or "").casefold()
            value = item.get("value", "")
            if "portal" in name and re.fullmatch(r"[0-9]{1,32}", value):
                portal = re.match(r"(.*)", value)
                break
    if not portal:
        raise FetchError("partial", "Taleo search page did not expose its public portal number.")
    if url_code and url_code[1].casefold() != expected_code.casefold():
        raise FetchError("partial", "Taleo search page belongs to a different career section.")
    return portal[1], _language(lang[1] if lang else None)


def _search_payload(page_no: int) -> dict:
    return {
        "multilineEnabled": True,
        "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
        "fieldData": {"fields": {"KEYWORD": "", "LOCATION": "", "JOB_TITLE": ""}, "valid": True},
        "filterSelectionParam": {"searchFilterSelections": [
            {"id": "POSTING_DATE", "selectedValues": []},
            {"id": "LOCATION", "selectedValues": []},
            {"id": "JOB_FIELD", "selectedValues": []},
            {"id": "JOB_TYPE", "selectedValues": []},
            {"id": "JOB_SCHEDULE", "selectedValues": []},
        ]},
        "advancedSearchFiltersSelectionParam": {"searchFilterSelections": [
            {"id": "ORGANIZATION", "selectedValues": []},
            {"id": "LOCATION", "selectedValues": []},
            {"id": "JOB_FIELD", "selectedValues": []},
            {"id": "JOB_NUMBER", "selectedValues": []},
            {"id": "URGENT_JOB", "selectedValues": []},
            {"id": "EMPLOYEE_STATUS", "selectedValues": []},
            {"id": "STUDY_LEVEL", "selectedValues": []},
            {"id": "WILL_TRAVEL", "selectedValues": []},
            {"id": "JOB_SHIFT", "selectedValues": []},
        ]},
        "pageNo": page_no,
    }


def _entries(data: object, page_no: int):
    if not isinstance(data, dict) or not isinstance(data.get("requisitionList"), list) or not isinstance(data.get("pagingData"), dict):
        raise FetchError("partial", "Taleo returned an unexpected listing schema.")
    paging = data["pagingData"]
    total, page_size, current = paging.get("totalCount"), paging.get("pageSize"), paging.get("currentPageNo")
    if type(total) is not int or total < 0 or type(page_size) is not int or page_size <= 0 or type(current) is not int or current != page_no:
        raise FetchError("partial", "Taleo listing total, page size, or page number is missing or inconsistent.")
    if total > MAX_JOBS:
        raise FetchError("partial", "Taleo job limit reached; inventory incomplete.")
    return data["requisitionList"], total, page_size


def _column(item: dict, index: int) -> str:
    columns = item.get("column") or []
    if not isinstance(columns, list) or index >= len(columns):
        return ""
    value = columns[index]
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, list):
                return "; ".join(text(part) for part in decoded if text(part))
        except json.JSONDecodeError:
            pass
    return text(value)


def _detail_description(parser: _Page, title: str) -> str:
    body = _page_text(parser)
    for marker in ("Job Description", title, "Description"):
        pos = body.casefold().find(marker.casefold()) if marker else -1
        if pos >= 0:
            body = body[pos:]
            break
    for marker in ("Apply for this position online", "Refer a friend for this job", "Need help finding the right job"):
        pos = body.casefold().find(marker.casefold())
        if pos > 0:
            body = body[:pos]
    pieces = [body]
    # Taleo pages often carry a compact, encoded snapshot in initialHistory.
    # Add it as a fallback because some themes render little visible text server-side.
    for item in parser.inputs:
        key = (item.get("id") or item.get("name") or "").casefold()
        value = item.get("value") or ""
        if key == "initialhistory" and value:
            parts = [text(part) for part in value.split("!|!")]
            pieces.extend(part for part in parts if len(part) > 20)
    result = "\n".join(dict.fromkeys(part for part in pieces if part))
    return result.strip()


def _snapshot_description(parser: _Page, title: str, contest: str, job_id: str) -> str:
    """Read the verified Moxa Taleo requisition model, including qualifications.

    The visible document is an empty UI shell. Its initialHistory model has
    paired display/raw HTML fields, preceded by exact requisition identities.
    """
    histories = [item.get("value", "") for item in parser.inputs
                 if (item.get("id") or item.get("name") or "").casefold() == "initialhistory"]
    if len(histories) != 1:
        raise FetchError("partial", "Taleo detail lacks one complete requisition snapshot.")
    parts = [unquote(value).replace("\\:", ":") for value in histories[0].split("!|!")]
    if (len(parts) < 18 or parts[2] != "descRequisition" or not job_id
            or parts[5] != job_id or parts[13] != contest or text(parts[12]) != title
            or text(unquote(_meta(parser, "og:title"))) != title):
        raise FetchError("partial", "Taleo detail snapshot does not confirm requisition ID and title.")
    blocks = parts[14:18]
    if (blocks[0] != blocks[1] or blocks[2] != blocks[3]
            or any(not block.startswith("!*!") for block in blocks)):
        raise FetchError("partial", "Taleo detail description/qualification fields are incomplete or inconsistent.")
    bodies = [text(block[3:]) for block in (blocks[0], blocks[2])]
    if not all(bodies):
        raise FetchError("partial", "Taleo detail lacks full description or qualifications.")
    return "\n\n".join(bodies)


def _posting(item: dict, detail: _Page, code: str, lang: str, root: str, company_id: str, company: str) -> dict:
    if not isinstance(item, dict):
        raise FetchError("partial", "Taleo listing contains a malformed posting.")
    contest = str(item.get("contestNo") or item.get("jobNumber") or "").strip()
    job_id = str(item.get("jobId") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", contest):
        raise FetchError("partial", "Taleo listing lacks a valid public job number.")
    linked = item.get("linkedColumn")
    title = _column(item, linked if type(linked) is int else 0)
    detail_body = _page_text(detail)
    meta_title = text(_meta(detail, "og:title")).split("|", 1)[0].strip()
    if not title:
        title = meta_title
    if urlsplit(root).hostname == "tas-moxa.taleo.net":
        description = _snapshot_description(detail, title, contest, job_id)
    else:
        if title and title.casefold() not in detail_body.casefold() and title.casefold() not in meta_title.casefold():
            raise FetchError("partial", "Taleo detail page did not confirm the listing title.")
        description = _detail_description(detail, title)
    row = _base({"id": contest}, "Taleo", company_id, company)
    row.update(
        req_id=contest,
        title=title,
        url=root + code + "/jobdetail.ftl?" + urlencode({"job": contest, "lang": lang}),
        location=_column(item, 2) or _column(item, 1),
        work_arrangement="Remote" if "remote" in " ".join((_column(item, 1), _column(item, 2), description)).casefold() else "",
        description=description,
        department=_column(item, 3),
        created_at=text(item.get("postingDate") or item.get("postedDate") or ""),
    )
    if job_id:
        row["updated_at"] = "taleo-job-id:" + job_id
    missing = [field for field in ("posting_id", "title", "description") if not row[field]]
    if missing:
        raise FetchError("partial", "Taleo detail is missing required normalized fields: " + ", ".join(missing))
    return row


def _ids(entries):
    return [str(item.get("contestNo") or item.get("jobNumber") or "") for item in entries if isinstance(item, dict)]


def fetch_taleo(board: str, root: str, company_id: str, company: str, transport) -> Inventory:
    source = root + board
    parsed = urlsplit(source)
    match = BOARD.fullmatch(parsed.path)
    if not match:
        return Inventory("unsupported", reason="Taleo board identity is invalid.", source_url=source, ats="Taleo")
    code = match[1]
    try:
        lang_hint = _query(parsed).get("lang", "en")
        portal, lang = _portal(_html(source, transport), code)
        if lang_hint != "en":
            lang = lang_hint
        search_url = f"https://{parsed.hostname}{SEARCH_PATH}?" + urlencode({"lang": lang, "portal": portal})
        jobs, seen, issues = [], set(), []
        first_ids = None
        total = None
        snapshots = {}
        strict = parsed.hostname == "tas-moxa.taleo.net"
        for page_no in range(1, MAX_PAGES + 1):
            data = _json(search_url, transport, _search_payload(page_no))
            entries, total, page_size = _entries(data, page_no)
            if strict:
                if snapshots and (total, page_size) != (snapshots[1][1], snapshots[1][2]):
                    raise FetchError("partial", "Taleo listing changed during pagination.")
                if len(entries) != min(page_size, max(0, total - (page_no - 1) * page_size)):
                    raise FetchError("partial", "Taleo listing page is truncated or inconsistent with its total.")
                snapshots[page_no] = (entries, total, page_size)
            if page_no == 1:
                first_ids = _ids(entries)
            if not entries:
                break
            for index, item in enumerate(entries):
                contest = str(item.get("contestNo") or item.get("jobNumber") or "") if isinstance(item, dict) else ""
                if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", contest):
                    print(json.dumps({"event": "posting_skipped", "provider": "Taleo", "page": page_no,
                                      "item_on_page": index + 1, "posting_id": contest[:160],
                                      "reason": "Taleo listing lacks a valid public job number."}, ensure_ascii=True), file=sys.stderr)
                    issues.append("One or more malformed/incomplete postings were skipped.")
                    continue
                if contest in seen:
                    issues.append("Duplicate posting IDs or repeated pagination detected.")
                    continue
                detail_url = root + code + "/jobdetail.ftl?" + urlencode({"job": contest, "lang": lang})
                try:
                    row = _posting(item, _html(detail_url, transport), code, lang, root, company_id, company)
                except FetchError as exc:
                    print(json.dumps({"event": "posting_skipped", "provider": "Taleo", "page": page_no,
                                      "item_on_page": index + 1, "posting_id": contest[:160],
                                      "reason": exc.reason}, ensure_ascii=True), file=sys.stderr)
                    issues.append("One or more malformed/incomplete postings were skipped.")
                    continue
                seen.add(row["posting_id"])
                jobs.append(row)
            if len(jobs) >= total or len(entries) < page_size:
                break
        if total is None:
            raise FetchError("partial", "Taleo returned no listing data.")
        if len(seen) != total:
            issues.append(f"Taleo returned {len(seen)} unique postings out of reported total {total}.")
        if not issues and strict:
            for page_no, saved in snapshots.items():
                check = _json(search_url, transport, _search_payload(page_no))
                if _entries(check, page_no) != saved:
                    issues.append("Taleo board changed during the scan; retry for a complete inventory.")
                    break
        elif total > 0 and not issues:
            check = _json(search_url, transport, _search_payload(1))
            check_entries, check_total, _ = _entries(check, 1)
            if check_total != total or _ids(check_entries) != first_ids:
                issues.append("Taleo board changed during the scan; retry for a complete inventory.")
        status = "partial" if issues else "complete"
        reason = f"Taleo: retrieved {len(jobs)} full postings."
        if issues:
            reason = " ".join(dict.fromkeys(issues))
        return Inventory(status, jobs, reason, source, ats="Taleo")
    except FetchError as exc:
        return Inventory(exc.status, [], exc.reason, source, ats="Taleo")
    except (OSError, ValueError, TypeError, AttributeError):
        return Inventory("failed", [], "Unexpected Taleo transport or schema failure; inventory not complete.", source, ats="Taleo")
