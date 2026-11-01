"""Read public Phenom HTML inventories without executing page scripts.

Verified against employer search-results and job pages on 2026-10-08.
Public bootstrap data and the read-only refineSearch widget provide listings.
No login or application endpoint is used. Landing-page scopes remain unchanged.
"""
from __future__ import annotations

from html.parser import HTMLParser
import json
import re
import sys
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit

from .ats import FetchError, HTTPResponse, Inventory, _base, _challenge, text
from .discovery import CareersTransport, MAX_HTML_BYTES, public_careers_url


KNOWN_HOSTS = frozenset({
    "careers.kbr.com", "careers.serco-na.com", "careers.mitre.org",
    "jobs.baesystems.com", "careers.rtx.com", "careers.uk.leonardo.com",
    "careers.cisco.com", "careers.hpe.com", "careers.trinzic.com", "careers.geaerospace.com",
    "careers.abb",
})
MAX_PAGES = 500
MAX_RECONCILIATIONS = 3
MAX_JOBS = 10000
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}")
DIVISIONS = {
    "careers.rtx.com": {"raytheon", "collins aerospace"},
    "careers.hpe.com": {"hpe aruba networking", "juniper networks"},
}


def supports_phenom(ats, url):
    try:
        return "phenom" in ats.casefold() or urlsplit(url).hostname in KNOWN_HOSTS
    except (ValueError, AttributeError):
        return False


def _origin(url):
    p = urlsplit(public_careers_url(url))
    return p.hostname, p.port or 443


def _same_origin(url, origin):
    if _origin(url) != origin:
        raise FetchError("unsupported", "Phenom URL changes employer host; verify its official destination.")
    return url


def _source(url):
    # Do not silently discard a filter or resume from a partial result page.
    if urlsplit(url).fragment:
        raise FetchError("unsupported", "Phenom fragment filters are unsupported; provide a public scoped search URL.")
    p = urlsplit(public_careers_url(url))
    query = {}
    for key, value in parse_qsl(p.query, keep_blank_values=True, max_num_fields=30):
        if key.startswith("utm_"):
            continue
        if key in query or key not in {"keywords", "from", "s"}:
            raise FetchError("unsupported", "Unrecognized or duplicate Phenom filter; scope must be verified before scanning.")
        query[key] = value
    if query.get("from", "0") != "0" or query.get("s", "1") != "1":
        raise FetchError("unsupported", "Phenom inventory must start at the first results page.")
    query = {k: v for k, v in query.items() if k == "keywords" and v}
    return p._replace(query=urlencode(query), fragment="").geturl()


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "script" and not dict(attrs).get("src"):
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.scripts.append("".join(self.current))
            self.current = None


class _CanonicalLink(HTMLParser):
    """Read an explicit canonical link without relying on attribute order."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.casefold() != "link":
            return
        attrs = {str(k).casefold(): str(v or "") for k, v in attrs}
        if "canonical" in {part.casefold() for part in attrs.get("rel", "").split()}:
            # Preserve the raw attribute value so Raytheon validation can
            # reject leading/trailing ASCII controls or whitespace instead
            # of silently normalizing them away.
            self.hrefs.append(attrs.get("href", ""))


def _assignment(scripts, pattern, required=True):
    values = []
    for script in scripts:
        for match in re.finditer(pattern, script):
            value, end = json.JSONDecoder().raw_decode(script, match.end())
            if script[end:].lstrip()[:1] != ";" or not isinstance(value, dict):
                raise FetchError("partial", "Phenom bootstrap data is not a JSON object assignment.")
            values.append(value)
    if len(values) != 1:
        if not values and not required:
            return {}
        raise FetchError("partial", "Phenom page lacks unique public bootstrap data.")
    return values[0]


def _read(url, transport, origin):
    visited = set()
    for _ in range(5):
        _same_origin(url, origin)
        if url in visited:
            raise FetchError("failed", "Phenom careers redirect loop; verify the careers URL.")
        visited.add(url)
        response = transport.get(url)
        if not isinstance(response, HTTPResponse):
            raise FetchError("failed", "Phenom transport must return HTTPResponse.")
        if response.status in (401, 403, 429) or _challenge(response, expect_html=True):
            raise FetchError("blocked", "Phenom access denied, rate limited, or human verification; retry later or review access.")
        if response.status in (301, 302, 303, 307, 308):
            location = next((v for k, v in response.headers.items() if k.lower() == "location"), "")
            if not location:
                raise FetchError("failed", "Phenom redirect has no destination.")
            target = urljoin(url, location)
            if sorted(parse_qsl(urlsplit(target).query)) != sorted(parse_qsl(urlsplit(url).query)):
                raise FetchError("unsupported", "Phenom redirect changed search/page parameters; scope cannot be verified.")
            url = target
            continue
        if not 200 <= response.status < 300:
            raise FetchError("failed", f"Phenom HTTP {response.status}; inventory unavailable, not evidence of closure.")
        if len(response.body) > MAX_HTML_BYTES:
            raise FetchError("partial", "Phenom page exceeds the bounded HTML size limit.")
        content_type = next((v for k, v in response.headers.items() if k.lower() == "content-type"), "text/html")
        if content_type.split(";", 1)[0].lower().strip() not in {"text/html", "application/xhtml+xml"}:
            raise FetchError("partial", "Phenom expected public HTML page data.")
        html = response.body.decode("utf-8")
        parser = _Scripts()
        parser.feed(html)
        parser.close()
        app = _assignment(parser.scripts, r"\b(?:var\s+)?phApp\s*=\s*phApp\s*\|\|\s*")
        ddo = _assignment(parser.scripts, r"\bphApp\.ddo\s*=\s*")
        params = _assignment(parser.scripts, r"\bphApp\.sessionParams\s*=\s*", required=False)
        if (not IDENTIFIER.fullmatch(str(app.get("refNum", "")))
                or app.get("siteType") != "external"):
            raise FetchError("partial", "Phenom page does not identify a public employer board.")
        base = app.get("baseUrl", "")
        _same_origin(base, origin)
        base_parts = urlsplit(base)
        if not re.fullmatch(r"/[a-zA-Z-]+/[a-zA-Z-]+/", base_parts.path) or base_parts.query or base_parts.fragment:
            raise FetchError("partial", "Phenom page has an invalid locale base URL.")
        # Preserve the page's explicit canonical only as metadata. Providers
        # must still validate it against their own board/ID before use.
        canonical_parser = _CanonicalLink()
        canonical_parser.feed(html)
        canonical_parser.close()
        params = dict(params)
        # This private value is derived only from the current HTML response;
        # never let a session bootstrap field masquerade as a page canonical.
        params["_canonical_urls"] = list(canonical_parser.hrefs)
        return url, app, ddo, params
    raise FetchError("failed", "Phenom careers redirect limit reached.")


def _identity(app):
    return app["refNum"], app["baseUrl"], app.get("locale")


def _listing(page, offset, keywords):
    _, app, ddo, params = page
    keys = [k for k in ("eagerLoadRefineSearch", "targetedJobs") if k in ddo]
    if len(keys) != 1:
        raise FetchError("partial", "Phenom page lacks an unambiguous full search inventory.")
    key = keys[0]
    result = ddo[key]
    data = result.get("data")
    if result.get("status") != 200 or not isinstance(data, dict):
        raise FetchError("partial", "Phenom listing did not report a successful search.")
    entries, total, hits = data.get("jobs"), result.get("totalHits"), result.get("hits")
    if (not isinstance(entries, list) or type(total) is not int or not 0 <= total <= MAX_JOBS
            or type(hits) is not int or hits != len(entries) or offset + hits > total):
        raise FetchError("partial", "Phenom listing count/schema is inconsistent or exceeds the job limit.")
    if not entries and offset < total:
        raise FetchError("partial", "Phenom returned an empty page before the advertised inventory ended.")
    if key == "eagerLoadRefineSearch":
        # Filtered SSR searches honor `from` but may omit its session echo.
        # Their exact keyword echo, unique IDs and total still must reconcile.
        confirmed_offset = params.get("from")
        if ((confirmed_offset is not None or not keywords) and str(confirmed_offset) != str(offset)
                or (data.get("keywords") or "") != keywords):
            raise FetchError("partial", "Phenom did not confirm the requested page offset and keyword scope.")
    else:
        if keywords or not result.get("lpKey"):
            raise FetchError("unsupported", "Phenom landing page scope cannot be combined with unverified search filters.")
    eid = result.get("eid") or {}
    scope = (key, result.get("lpKey"), eid.get("searchType"), eid.get("query"), keywords)
    seen = set()
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get("jobId"), str)
                or not IDENTIFIER.fullmatch(entry["jobId"])
                or not isinstance(entry.get("jobSeqNo"), str)
                or not IDENTIFIER.fullmatch(entry["jobSeqNo"])
                or not entry["jobSeqNo"].startswith(app["refNum"])
                or not isinstance(entry.get("title"), str) or not entry["title"].strip()
                or entry.get("siteType") != "external"
                or "external" not in entry.get("jobVisibility", [])):
            raise FetchError("partial", "Phenom listing contains invalid or non-public posting identity.")
        if entry["jobId"] in seen:
            raise FetchError("partial", "Phenom listing repeats a posting ID.")
        seen.add(entry["jobId"])
    return entries, total, scope


def _fingerprint(entries):
    return sorted((j["jobId"], j["jobSeqNo"], j["title"]) for j in entries)


def _posting(page, entry, identity, company_id, company):
    url, app, ddo, _ = page
    if _identity(app) != identity:
        raise FetchError("partial", "Phenom detail belongs to a different employer board or locale.")
    result = ddo.get("jobDetail", {})
    job = result.get("data", {}).get("job", {})
    if (result.get("status") != 200 or not isinstance(job, dict)
            or job.get("jobId") != entry["jobId"] or job.get("jobSeqNo") != entry["jobSeqNo"]
            or job.get("refNum") != app["refNum"] or job.get("siteType") != "external"
            or "external" not in job.get("jobVisibility", [])
            or job.get("title") != entry["title"]):
        raise FetchError("partial", "Phenom detail identity/title no longer matches its public listing.")
    params = page[3] if isinstance(page[3], dict) else {}
    canonical_urls = params.get("_canonical_urls")
    canonical = canonical_urls[0] if isinstance(canonical_urls, list) and len(canonical_urls) == 1 else ""
    try:
        canonical_url = urlsplit(canonical) if isinstance(canonical, str) else urlsplit("")
        requested_url = urlsplit(url)
        base_url = urlsplit(app.get("baseUrl", ""))
        canonical_port = canonical_url.port
        requested_port = requested_url.port
        base_port = base_url.port
    except ValueError:
        canonical_url = requested_url = base_url = urlsplit("")
        canonical_port = requested_port = base_port = -1
    raytheon_guard = company_id == "COMP-0078" and company.casefold() == "raytheon"
    if raytheon_guard:
        if (app.get("refNum") != "RAYTGLOBAL" or app.get("siteType") != "external"
                or app.get("locale") != "en_global"
                or base_url.scheme != "https" or base_url.hostname != "careers.rtx.com"
                or base_port not in (None, 443) or base_url.username or base_url.password
                or base_url.path != "/global/en/" or base_url.query or base_url.fragment
                or requested_url.scheme != "https" or requested_url.hostname != "careers.rtx.com"
                or requested_port not in (None, 443) or requested_url.username or requested_url.password
                or job.get("businessUnit") != "Raytheon" or not isinstance(canonical_urls, list)
                or len(canonical_urls) != 1 or canonical_url.scheme != "https"
                or canonical_url.hostname != "careers.rtx.com" or canonical_port not in (None, 443)
                or canonical_url.username or canonical_url.password or canonical_url.query
                or canonical_url.fragment or canonical_url.path.split("/")[:4] != ["", "global", "en", "job"]):
            raise FetchError("partial", "Raytheon detail lacks a valid same-board canonical URL or business-unit identity.")
        # The official site derives slugs from titles and can emit Unicode
        # title characters (for example U+00A0). Validate the exact canonical
        # path without narrowing it to ASCII, while rejecting path escapes,
        # traversal, controls, and malformed percent-encoded UTF-8.
        raw_path = canonical_url.path
        if (any(ord(char) < 128 and (ord(char) < 32 or ord(char) == 127 or char.isspace())
                for char in canonical)
                or re.search(r"%(?![0-9A-Fa-f]{2})", raw_path)):
            raise FetchError("partial", "Raytheon detail canonical URL contains unsafe path data.")
        try:
            decoded_path = unquote(raw_path, errors="strict")
        except UnicodeDecodeError:
            raise FetchError("partial", "Raytheon detail canonical URL contains malformed UTF-8.")
        parts = decoded_path.split("/")
        slug = parts[5] if len(parts) > 5 else ""
        if (len(parts) not in (6, 7) or (len(parts) == 7 and parts[6] != "")
                or parts[4] != entry["jobId"] or not slug or slug in {".", ".."}
                or any(char in "/\\?#" or ord(char) < 32 or ord(char) == 127 for char in slug)):
            raise FetchError("partial", "Raytheon detail canonical URL does not match its public posting ID.")
    if any(str(job.get(k, "")).casefold() in {"closed", "deleted", "inactive", "filled"}
           for k in ("jobStatus", "postingStatus")):
        raise FetchError("partial", "Phenom posting closed during inventory retrieval.")
    if not isinstance(job.get("description"), str) or not text(job["description"]).strip():
        raise FetchError("partial", "Phenom detail is missing its full job description.")
    description = text(job["description"])
    for field, label in (("requiredSkillsEducation", "Required skills and education"),
                         ("preferredSkillsEducation", "Preferred skills and education")):
        value = text(job.get(field))
        if value and value not in description:
            description += "\n\n" + label + "\n" + value
    locations = job.get("multi_location") or [job.get("location", "")]
    if not isinstance(locations, list):
        raise FetchError("partial", "Phenom detail has malformed locations.")
    locations = [x.get("location") if isinstance(x, dict) else x for x in locations]
    if any(not isinstance(x, str) for x in locations):
        raise FetchError("partial", "Phenom detail has malformed locations.")
    row = _base({"id": job["jobId"]}, "Phenom", company_id, company)
    row.update(title=text(job["title"]), req_id=str(job.get("reqId") or job["jobId"]),
               url=canonical if raytheon_guard and canonical else url, description=description, location="; ".join(dict.fromkeys(filter(None, locations))),
               department=text(job.get("department") or job.get("category")),
               compensation=text(job.get("payRange") or job.get("compensation") or job.get("salary")),
               work_arrangement=text(job.get("RemoteType") or job.get("workLocationType") or job.get("hybridWork")),
               created_at=str(job.get("postedDate") or ""), updated_at=str(job.get("jobUpdatedDate") or ""))
    return row


def _consistent_search_mode(url):
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query))
    if parsed.path.rstrip('/').endswith('/search-results') and not query.get('keywords'):
        query['s'] = '1'
        return parsed._replace(query=urlencode(query)).geturl()
    return url


def fetch_phenom(ats, careers_url, company_id, company, transport=None, *, progress=None):
    from .phenom_session import PhenomSession
    transport = transport or PhenomSession(careers_url)
    jobs, source, context = [], careers_url, "Phenom careers page"
    try:
        source = _consistent_search_mode(_source(careers_url))
        origin = _origin(source)
        page = _read(source, transport, origin)
        source, app, ddo, _ = page
        # A custom landing page is a scope, never permission to scan the parent.
        path = urlsplit(source).path.rstrip("/")
        base_path = urlsplit(app["baseUrl"]).path.rstrip("/")
        standard = path in {"", base_path, base_path + "/home", base_path + "/search-results"}
        division = company.strip().casefold() in DIVISIONS.get(origin[0], set())
        if standard and (division or any(x in ats.casefold() for x in ("shared", "parent"))):
            raise FetchError("unsupported", "Phenom division/shared-parent row needs its verified company-specific landing page; parent inventory will not be assigned to this company.")
        if not any(k in ddo for k in ("eagerLoadRefineSearch", "targetedJobs")):
            if not standard:
                raise FetchError("unsupported", "Phenom custom careers page has no paginated inventory; verify its scoped search URL.")
            source = app["baseUrl"] + "search-results"
            query = urlsplit(careers_url).query
            source = _consistent_search_mode(_source(source + ("?" + query if query else "")))
            page = _read(source, transport, origin)
        source = _consistent_search_mode(_source(source))
        identity = _identity(page[1])
        keywords = dict(parse_qsl(urlsplit(source).query)).get("keywords", "")
        widget = standard and not keywords and hasattr(transport, 'search')
        session_params = page[3]
        def search_page(offset):
            result = transport.search(page[1], session_params, offset)
            return (source, page[1], {'eagerLoadRefineSearch': result}, {'from': str(offset)})
        if widget:
            page = search_page(0)
        _, _, scope = _listing(page, 0, keywords)
        completed = {}
        saved = progress._read('phenom_detail_v1') if progress is not None else {}
        def signature(entry):
            # Include public revision metadata, not just the title. Ordering of
            # the listing is immaterial; edits require a fresh detail request.
            return json.dumps(entry, sort_keys=True, separators=(',', ':'))

        def snapshot(first=None):
            nonlocal context
            current = first if first is not None else (search_page(0) if widget else _read(source, transport, origin))
            entries, total, current_scope = _listing(current, 0, keywords)
            queued, seen, sequences, offset, count = [], set(), set(), 0, 0
            try:
                while True:
                    count += 1
                    context = f"Phenom listing page {count}"
                    if _identity(current[1]) != identity:
                        raise FetchError('partial', 'Phenom employer board or locale changed during pagination.')
                    entries, page_total, page_scope = _listing(current, offset, keywords)
                    if page_total != total or page_scope != scope or current_scope != scope:
                        raise FetchError('partial', 'Phenom total or search scope changed during pagination.')
                    for entry in entries:
                        if entry['jobId'] in seen or entry['jobSeqNo'] in sequences:
                            raise FetchError('partial', 'Phenom repeated a posting/page; inventory incomplete.')
                        seen.add(entry['jobId']); sequences.add(entry['jobSeqNo'])
                        queued.append(entry)
                    offset += len(entries)
                    print(json.dumps({'event': 'inventory_page', 'provider': 'Phenom',
                                      'company_id': company_id, 'page': count,
                                      'postings_listed': len(queued), 'total': total}), file=sys.stderr)
                    if offset == total:
                        return queued, None
                    if count >= MAX_PAGES:
                        raise FetchError('partial', 'Phenom page limit reached; inventory incomplete.')
                    p = urlsplit(source)
                    query = dict(parse_qsl(p.query)); query['from'] = str(offset)
                    if standard and not keywords:
                        query['s'] = '1'
                    current = search_page(offset) if widget else _read(p._replace(query=urlencode(query)).geturl(), transport, origin)
            except FetchError as error:
                if error.status == 'blocked':
                    raise
                return queued, error

        queued, listing_error = snapshot(page)
        for attempt in range(MAX_RECONCILIATIONS + 1):
            failures = []
            for entry in queued:
                ident = entry['jobId']
                revision = signature(entry)
                context = f"Phenom job detail {ident}"
                cached = completed.get(ident) or saved.get(ident)
                if (isinstance(cached, dict) and not cached.get('retired') and cached.get('identity') == list(identity)
                        and cached.get('revision') == revision
                        and isinstance(cached.get('job'), dict)
                        and cached['job'].get('posting_id') == ident
                        and cached['job'].get('description')):
                    completed[ident] = cached
                    jobs = [item['job'] for item in completed.values()]
                    continue
                def record_failure(reason):
                    print(json.dumps({'event': 'posting_failed', 'provider': 'Phenom',
                                      'company_id': company_id, 'posting_id': ident,
                                      'attempt': attempt + 1, 'reason': reason}), file=sys.stderr)
                    if progress is not None:
                        progress._write('phenom_error_v1', ident,
                                        {'attempt': attempt + 1, 'reason': reason})
                try:
                    detail = _read(app['baseUrl'] + 'job/' + ident, transport, origin)
                    job = _posting(detail, entry, identity, company_id, company)
                    record = {'identity': list(identity), 'revision': revision, 'job': job}
                    completed[ident] = record
                    jobs = [item['job'] for item in completed.values()]
                    if progress is not None:
                        progress._write('phenom_detail_v1', ident, record)
                except FetchError as error:
                    if error.status == 'blocked':
                        # Keep rate-limit/access evidence even though further
                        # detail requests must stop.
                        record_failure(error.reason)
                        raise
                    failures.append((ident, error.reason))
                except (ValueError, TypeError, AttributeError, KeyError, RecursionError, OSError):
                    failures.append((ident, 'Malformed posting data or network failure.'))
                if failures and failures[-1][0] == ident:
                    record_failure(failures[-1][1])
                if len(jobs) and len(jobs) % 100 == 0:
                    print(json.dumps({'event': 'posting_progress', 'provider': 'Phenom',
                                      'company_id': company_id, 'postings_fetched': len(jobs),
                                      'total': len(queued)}), file=sys.stderr)
            if listing_error:
                raise FetchError('partial', 'Phenom listing incomplete: ' + listing_error.reason)
            context = 'Phenom full inventory reconciliation'
            current, error = snapshot()
            if error:
                raise error
            before = {e['jobId']: signature(e) for e in queued}
            after = {e['jobId']: signature(e) for e in current}
            stable = before == after
            if stable and not failures:
                # Only a second complete, matching snapshot permits excluding
                # jobs that disappeared in an earlier reconciliation round.
                jobs = [completed[e['jobId']]['job'] for e in current]
                if progress is not None:
                    # Preserve audit evidence, but require a fresh detail if a
                    # confirmed absent posting later reappears with the same ID.
                    for ident, record in {**saved, **completed}.items():
                        if ident not in after and isinstance(record, dict) and not record.get('retired'):
                            progress._write('phenom_detail_v1', ident, dict(record, retired=True))
                return Inventory('complete', jobs,
                                 f'Phenom: retrieved {len(jobs)} full postings; full inventory membership and revisions reconciled in {attempt + 1} rounds.',
                                 source, 'Phenom')
            print(json.dumps({'event': 'inventory_reconciliation', 'provider': 'Phenom',
                              'company_id': company_id, 'round': attempt + 1,
                              'added': len(after.keys() - before.keys()),
                              'removed': len(before.keys() - after.keys()),
                              'edited': sum(before[k] != after[k] for k in before.keys() & after.keys()),
                              'unresolved': len(failures)}), file=sys.stderr)
            if attempt == MAX_RECONCILIATIONS:
                detail_reason = '; '.join(f'job detail {i}: {reason}' for i, reason in failures[:3])
                raise FetchError('partial', 'Phenom bounded reconciliation exhausted; inventory remains incomplete. ' + detail_reason)
            queued = current
    except FetchError as error:
        status = "blocked" if error.status == "blocked" else ("partial" if jobs else error.status)
        return Inventory(status, jobs, context + ": " + error.reason, source, "Phenom")
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
        return Inventory("partial", jobs, context + ": malformed or missing public page data; no complete inventory established.", source, "Phenom")
    except OSError:
        return Inventory("partial" if jobs else "failed", jobs, context + ": network failure; inventory incomplete.", source, "Phenom")
