"""Read-only ATS Corporation qualification through one frozen normal-dispatch candidate."""

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import sys
from threading import Lock
from urllib.parse import urlsplit
from xml.etree import ElementTree


HOST = 'jobs.atsautomation.com'
SOURCE = 'https://' + HOST + '/'
BOARD = (
    SOURCE + 'search/?createNewAlert=false&q=&locationsearch=&optionsFacetsDD_brand=&optionsFacetsDD_country='
    '&optionsFacetsDD_location=&optionsFacetsDD_lang='
)
SITEMAP = SOURCE + 'sitemap.xml'
COMPANY_ID = 'COMP-0573'
COMPANY = 'ATS Corporation'
PROVIDER = 'SuccessFactors'
JOB_PATH = re.compile(r'/(?:(?:PA|Comecer)/)?job/[^/]+/(\d{4,24})/')
BASELINE_ADAPTER_PIN = '85e7e060243dbdbc95b4e6db48979a7f7ac26dd17458d26e173cffbcbaf3cf2a'


def posting_id(url):
    parts = urlsplit(url)
    match = JOB_PATH.fullmatch(parts.path)
    if parts.scheme == 'https' and parts.netloc == HOST and not parts.query and not parts.fragment and match:
        return match.group(1)
    return None


def membership(body):
    if re.search(rb'<!\s*(?:DOCTYPE|ENTITY)', body, re.IGNORECASE):
        raise ValueError('ATS Corporation sitemap contains a disallowed declaration.')
    root = ElementTree.fromstring(body)
    namespace = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
    if root.tag != namespace + 'urlset':
        raise ValueError('ATS Corporation did not publish a sitemap URL set.')
    result = {}
    for entry in root:
        node = entry.find(namespace + 'loc')
        url = (node.text or '').strip() if node is not None else None
        if entry.tag != namespace + 'url' or not url:
            raise ValueError('ATS Corporation sitemap contains a malformed URL entry.')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != HOST:
            raise ValueError('ATS Corporation sitemap crosses the exact employer boundary.')
        identity = posting_id(url)
        if identity is None:
            if '/job/' in parsed.path:
                raise ValueError('Unreviewed ATS Corporation job URL shape.')
            continue
        if identity in result:
            raise ValueError('ATS Corporation sitemap repeated a posting ID.')
        result[identity] = url
    if not 1 <= len(result) <= 2500:
        raise ValueError('ATS Corporation sitemap did not contain a bounded positive inventory.')
    return result


class RecordingTransport:
    """Serialize and record one bounded official-board verification."""

    def __init__(self, transport, page_parser, normalize):
        self.transport = transport
        self.page_parser = page_parser
        self.normalize = normalize
        self.lock = Lock()
        self.calls = []
        self.sitemaps = []
        self.descriptions = {}
        self.allowed = set()
        self.failed = False

    def get(self, url):
        with self.lock:
            if (self.failed or len(self.calls) >= 2510
                    or (url not in (BOARD, SITEMAP) and url not in self.allowed)):
                raise ValueError('ATS Corporation qualification stopped before an unqualified request.')
            identity = posting_id(url)
            if identity is not None and url in self.descriptions:
                raise ValueError('ATS Corporation requested one detail twice.')
            response = self.transport.get(url)
            self.calls.append((url, response.status))
            if response.status != 200:
                self.failed = True
                return response
            if url == SITEMAP:
                current = membership(response.body)
                if self.sitemaps and current != self.sitemaps[0][1]:
                    self.failed = True
                    raise ValueError('ATS Corporation sitemap membership changed.')
                self.sitemaps.append((len(self.calls), current))
                self.allowed = set(current.values())
            elif identity is not None:
                page = self.page_parser(response.body.decode('utf-8', 'replace'))
                description = self.normalize(''.join(page.description))
                if (page.canonicals != [url] or len(page.title) != 1 or not page.title[0].strip()
                        or page.description_count != 1 or page.depth or not description):
                    self.failed = True
                    raise ValueError('ATS Corporation public detail lacks an exact canonical description.')
                self.descriptions[url] = sha256(description.encode()).hexdigest()
            return response


def validate_result(inventory, observed):
    jobs = inventory.jobs
    if (inventory.status != 'complete' or inventory.ats != PROVIDER or inventory.source_url != BOARD
            or inventory.outcome_failure is not None or observed.failed
            or len(observed.sitemaps) < 2 or not observed.calls):
        raise ValueError('ATS Corporation did not produce a complete and stable official-board result.')
    first_index, expected = observed.sitemaps[0]
    final_index, final = observed.sitemaps[-1]
    detail_indexes = [index for index, (url, _) in enumerate(observed.calls, 1) if posting_id(url)]
    if (expected != final or not detail_indexes or first_index >= min(detail_indexes)
            or final_index <= max(detail_indexes)):
        raise ValueError('ATS Corporation did not recheck exact membership around the detail requests.')
    returned = {}
    descriptions = {}
    for job in jobs:
        identity, url = str(job['posting_id']), job['url']
        if (job['company_id'] != COMPANY_ID or job['company'] != COMPANY or identity in returned
                or not job['description'].strip()):
            raise ValueError('ATS Corporation output contains an incomplete or cross-company record.')
        returned[identity] = url
        descriptions[url] = sha256(job['description'].encode()).hexdigest()
    if returned != expected or descriptions != observed.descriptions:
        raise ValueError('ATS Corporation details do not exactly cover the stable sitemap with matching descriptions.')
    return {
        'company_id': COMPANY_ID,
        'board': BOARD,
        'complete_descriptions': len(returned),
        'stable_final_membership': True,
        'membership_sha256': sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest(),
        'descriptions_sha256': sha256(json.dumps(descriptions, sort_keys=True).encode()).hexdigest(),
        'request_count': len(observed.calls),
    }


def qualify(candidate, source_pin, ats_pin, adapter_pin, host_pin, parser_pin, baseline_adapter):
    sys.path.insert(0, str(candidate / 'src'))
    from job_search_helper import ats, ats_sitemap_parser, successfactors, successfactors_sitemap
    from job_search_helper.discovery import CareersTransport
    from job_search_helper.integration_release import source_tree_digest

    modules = (
        (ats, 'ats.py', ats_pin),
        (successfactors, 'successfactors.py', adapter_pin),
        (successfactors_sitemap, 'successfactors_sitemap.py', host_pin),
        (ats_sitemap_parser, 'ats_sitemap_parser.py', parser_pin),
    )
    if not ats_sitemap_parser.PARSER_READY or ats.ATS_CORPORATION_SOURCE != BOARD:
        raise ValueError('ATS candidate parser and board do not match the approved scope.')
    for module, name, pin in modules:
        path = candidate / 'src/job_search_helper' / name
        if Path(module.__file__).resolve(strict=True) != path or sha256(path.read_bytes()).hexdigest() != pin:
            raise ValueError('Runtime imported bytes outside the exact candidate.')
    if source_tree_digest(candidate) != source_pin or sha256(baseline_adapter.read_bytes()).hexdigest() != BASELINE_ADAPTER_PIN:
        raise ValueError('ATS Corporation qualification source identity changed.')
    spec = importlib.util.spec_from_file_location('job_search_helper._approved_ats_detail_parser', baseline_adapter)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    capture = RecordingTransport(CareersTransport(interval=0.8), baseline._Page, ats.text)
    inventory = ats.fetch_inventory(PROVIDER, SOURCE, COMPANY_ID, COMPANY, discovery_transport=capture)
    result = validate_result(inventory, capture)
    if source_tree_digest(candidate) != source_pin:
        raise ValueError('Candidate bytes changed during qualification.')
    return {
        **result,
        'source_tree_sha256': source_pin,
        'adapter_sha256': adapter_pin,
        'ats_sha256': ats_pin,
        'host_sitemap_sha256': host_pin,
        'parser_sha256': parser_pin,
    }


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--ats-sha256', required=True)
    parser.add_argument('--adapter-sha256', required=True)
    parser.add_argument('--host-sitemap-sha256', required=True)
    parser.add_argument('--parser-sha256', required=True)
    parser.add_argument('--baseline-adapter', type=Path, required=True)
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null':
        raise ValueError('Use the installed Python with -I -B -X pycache_prefix=/dev/null.')
    print(json.dumps(qualify(args.candidate.resolve(strict=True), args.source_sha256,
                            args.ats_sha256, args.adapter_sha256, args.host_sitemap_sha256, args.parser_sha256,
                            args.baseline_adapter.resolve(strict=True)), sort_keys=True))


if __name__ == '__main__':
    main()
