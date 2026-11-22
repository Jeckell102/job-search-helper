"""Measure one live or fixture-only Embraer pull through normal dispatch."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

COMPANY_ID = 'COMP-0634'
COMPANY = 'Embraer'
BOARD = 'https://embraer.breezy.hr/'
LISTING = BOARD + 'json'


class PacedTransport:
    """Make one request at a time to the approved public Breezy board."""

    def __init__(self, ats, shared_boards):
        self.response = ats.HTTPResponse
        self.opener = build_opener(shared_boards._NoRedirect())
        self.read_limit = shared_boards.MAX_RESPONSE_BYTES
        self.last_started = 0.0

    def get(self, url):
        sleep(max(0.0, 1.0 - (monotonic() - self.last_started)))
        request = Request(url, headers={
            'Accept-Encoding': 'identity',
            'User-Agent': 'JobSearchHelper/1.0 (public job-board inventory; read-only)',
        })
        self.last_started = monotonic()
        try:
            with self.opener.open(request, timeout=25) as response:
                return self.response(response.status, response.read(self.read_limit + 1), dict(response.headers))
        except HTTPError as error:
            with error:
                return self.response(error.code, b'', dict(error.headers))


class RecordingTransport:
    """Retain only measured listing identities and full-description fingerprints."""

    def __init__(self, inner, shared_boards, elements, text):
        self.inner = inner
        self.allowed = shared_boards.allowed
        self.board = shared_boards.board_link(BOARD)
        self.scripts = shared_boards.Scripts
        self.elements = elements
        self.text = text
        self.calls = []
        self.listings = []
        self.detail_hashes = {}

    def get(self, url):
        if (len(self.calls) >= 80 or any(status != 200 for _, status in self.calls)
                or urlsplit(url).netloc != 'embraer.breezy.hr'
                or not self.allowed(self.board, url) or url == BOARD):
            raise ValueError('The bounded Embraer capture stopped before another request.')
        response = self.inner.get(url)
        self.calls.append((url, response.status))
        if response.status != 200:
            return response
        if url == LISTING:
            rows = json.loads(response.body)
            self.listings.append(sorted((str(row['id']), row['url'], row['name'],
                                         row['company']['friendly_id']) for row in rows))
        else:
            body = response.body.decode('utf-8')
            structured = self.scripts(body).jobs()
            if structured:
                values = [self.text(record['description']) for record in structured]
            else:
                values = self.elements(body, {'description'}).values
            if len(values) != 1 or not values[0].strip() or url in self.detail_hashes:
                raise ValueError('The observed public detail is incomplete or repeated.')
            self.detail_hashes[url] = sha256(values[0].encode()).hexdigest()
        return response


def qualify(candidate_root, expected_pins, expected_source_tree, transport=None):
    root = Path(candidate_root).resolve(strict=True)
    sys.path.insert(0, str(root / 'src'))
    from job_search_helper import ats, shared_boards
    from job_search_helper.integration_release import source_tree_digest
    from job_search_helper.shared_extended import Elements

    if source_tree_digest(root) != expected_source_tree:
        raise ValueError("The frozen candidate source tree differs from the proposed release.")

    for module in (ats, shared_boards):
        name = module.__name__.rsplit('.', 1)[-1]
        path = root / 'src/job_search_helper' / (name + '.py')
        if (Path(module.__file__).resolve(strict=True) != path
                or sha256(path.read_bytes()).hexdigest() != expected_pins[name]):
            raise ValueError('Python did not load the exact candidate ' + name)

    observed = RecordingTransport(transport or PacedTransport(ats, shared_boards), shared_boards, Elements, ats.text)
    inventory = ats.fetch_inventory('Breezy HR', BOARD, COMPANY_ID, COMPANY, transport=observed)
    jobs = inventory.jobs
    if (inventory.status != 'complete' or inventory.ats != 'Breezy HR'
            or inventory.source_url != BOARD or inventory.outcome_failure is not None
            or not jobs or any(job.get('company_id') != COMPANY_ID or job.get('company') != COMPANY
                               or not job.get('description', '').strip() for job in jobs)):
        raise ValueError('Embraer inventory is not a complete exact-board full-description result.')
    if (len(observed.listings) != 2 or observed.listings[0] != observed.listings[1]
            or observed.calls[0] != (LISTING, 200) or observed.calls[-1] != (LISTING, 200)
            or any(status != 200 for _, status in observed.calls)):
        raise ValueError('Embraer did not give two stable listings around complete detail reads.')

    listing = observed.listings[-1]
    advertised = {(identity, url) for identity, url, _, employer in listing if employer == 'embraer'}
    actual = {(str(job['posting_id']), job['url']) for job in jobs}
    urls = {url for _, url in advertised}
    result_hashes = {job['url']: sha256(job['description'].encode()).hexdigest() for job in jobs}
    if (len(advertised) != len(listing) or len(urls) != len(listing) or len(jobs) != len(listing)
            or actual != advertised or result_hashes != observed.detail_hashes):
        raise ValueError('The complete descriptions do not exactly cover the advertised Embraer listing.')
    if source_tree_digest(root) != expected_source_tree:
        raise ValueError('The frozen candidate source tree changed during qualification.')
    return {
        'company_id': COMPANY_ID,
        'board': BOARD,
        'status': inventory.status,
        'advertised_total': len(listing),
        'full_description_count': len(jobs),
        'stable_final_listing': True,
        'cohort_sha256': sha256(json.dumps(listing, separators=(',', ':')).encode()).hexdigest(),
        'description_hashes_sha256': sha256(json.dumps(result_hashes, sort_keys=True).encode()).hexdigest(),
        'transport_call_count': len(observed.calls),
        'source_pins': expected_pins,
        'source_tree_sha256': expected_source_tree,
    }


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--source-tree-sha256', required=True)
    parser.add_argument('--ats-sha256', required=True)
    parser.add_argument('--shared-boards-sha256', required=True)
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null':
        raise ValueError('Use the installed Python with -I -B -X pycache_prefix=/dev/null.')
    pins = {'ats': args.ats_sha256, 'shared_boards': args.shared_boards_sha256}
    print(json.dumps(qualify(args.candidate_root, pins, args.source_tree_sha256), sort_keys=True))


if __name__ == '__main__':
    main()
