"""Capture only public Breezy schema and one anchored failed-detail observation."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

PROJECT = Path('/home/chris/job-search-helper_old')
STAGE = Path(__file__).resolve().parent
sys.path[:0] = [str(PROJECT/'src'), str(STAGE.parent/'generic-qualification')]
from job_search_helper import ats, shared_boards as sb
from job_search_helper.shared_extended import Elements
from qualify_embraer_normal_dispatch import PacedTransport

BOARD = 'https://embraer.breezy.hr/'
REQUEST_SHA = '19e7af99bd90d243f9b9f7465d5b6c38455ef99208cade05b7e1cfe5ca7536d2'
OBSERVED_SHA = '399afce0bc247263f1501fff7466dc23a2aeb4a005185f54f4c6186a897ca1d6'
FILE_SHA = '83713b2eba3d53899f5c4aea4ed59a560b711eb69a7e64072d0d1dcaea54f89f'
LIMIT = 3


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def live_observation(transport):
    frozen = (PROJECT/'.state/operator-embraer-observations'/(REQUEST_SHA+'.json')).read_bytes()
    if sha256(frozen).hexdigest() != FILE_SHA:
        raise ValueError('Frozen original observation changed.')
    observation = json.loads(frozen)
    recorded = observation['inventory']
    typed = recorded['outcome_failure']['evidence']
    if (observation['state'] != 'FROZEN' or observation['sha256'] != OBSERVED_SHA
            or typed['board'] != BOARD or not typed['stable_listing']):
        raise ValueError('Original typed evidence does not own this board.')
    good_ids = {str(job['posting_id']) for job in recorded['jobs']}
    board = sb.board_link(BOARD)
    read_count = 0

    def read(url):
        nonlocal read_count
        if read_count >= LIMIT or not url.startswith(BOARD) or not sb.allowed(board, url):
            raise ValueError('Outside the bounded read-only Breezy evidence scope.')
        read_count += 1
        response = transport.get(url)
        return sb.checked(response, html=url != BOARD+'json')

    def listing():
        rows = sb.unique(json.loads(read(BOARD+'json')))
        values = {str(row['id']): row for row in rows}
        if any(row['company']['friendly_id'] != 'embraer'
               or not row['url'].startswith(BOARD)
               or sb.board_link(row['url']).ident != ident for ident, row in values.items()):
            raise ValueError('Public listing does not match exact employer scope.')
        return values

    first = listing()
    missing = sorted(first.keys() - good_ids)
    affected_hash = sha256('\n'.join(missing).encode()).hexdigest()
    if (len(first) != typed['advertised_total'] or not good_ids <= first.keys()
            or len(missing) != typed['detail_failure_count']
            or affected_hash != typed['affected_identity_sha256']):
        raise ValueError('The original affected subset is no longer matched by the live listing.')
    selected = first[missing[0]]
    detail_url, listing_title = selected['url'], ats.text(selected['name'])
    body = read(detail_url)
    description = Elements(body, {'description'}).values
    meta = sb.PublicMetadata()
    meta.feed(body)
    if (sb.Scripts(body).jobs() or len(description) != 1 or not description[0]
            or meta.urls != [detail_url] or not sb._embraer_brand_heading(body, listing_title)):
        raise ValueError('The exact sampled detail no longer shows the original typed condition.')
    if listing() != first:
        raise ValueError('Public listing changed during the diagnostic.')
    return {
        'board': BOARD, 'company_id': 'COMP-0634', 'observed_at': datetime.now(timezone.utc).isoformat(),
        'request_sha256': REQUEST_SHA, 'observation_sha256': OBSERVED_SHA,
        'listing_count': len(first), 'retained_detail_count': len(good_ids),
        'affected_count': len(missing), 'affected_identity_sha256': affected_hash,
        'listing_schema_fields': sorted(selected), 'company_schema_fields': sorted(selected['company']),
        'listing_sha256': digest(first), 'stable_reread': True, 'request_count': read_count,
        'sample': {'id': missing[0], 'public_url': detail_url, 'listing_title': listing_title,
                   'description_chars': len(description[0]), 'description_count': len(description),
                   'structured_job_present': False, 'metadata_url_matches': True,
                   'brand_heading_and_listing_title_banner': True,
                   'response_sha256': sha256(body.encode()).hexdigest()},
    }


if __name__ == '__main__':
    evidence = live_observation(PacedTransport(ats, sb))
    with (STAGE/'PUBLIC_SOURCE_FACTS.json').open('x', encoding='utf-8') as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write('\n')
    print(json.dumps({key:evidence[key] for key in (
        'company_id','listing_count','retained_detail_count','affected_count','stable_reread','request_count',
    )}, sort_keys=True))
