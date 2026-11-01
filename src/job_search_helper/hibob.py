"""Primer's public HiBob inventory, with employer and full-payload reconciliation."""
from __future__ import annotations

import json
from urllib.parse import urlsplit
from uuid import UUID

from .ats import FetchError, HTTPTransport, Inventory, _base, text

HOST = 'primertechnology.careers.hibob.com'
SOURCE = 'https://' + HOST + '/'
HEADERS = {'companyIdentifier': 'primertechnology'}
PATHS = {'/api/career-site', '/api/job-ad'}
MAX_JOBS = 5000
BODY_FIELDS = ('description', 'requirements', 'responsibilities', 'benefits',
               'payTransparencySalaryAdditionalInfo')
SALARY_FIELDS = (('payTransparencyMinSalary', 'Salary minimum'),
                 ('payTransparencyMaxSalary', 'Salary maximum'),
                 ('payTransparencySalaryCurrency', 'Salary currency'),
                 ('payTransparencySalaryPayPeriod', 'Salary pay period'))


def safe_api_path(parsed):
    return (parsed.hostname == HOST and parsed.path in PATHS
            and not parsed.query and not parsed.fragment)


def _get(client, path):
    # companyIdentifier is the public tenant selector used by the careers
    # client. It carries no user identity, secret, cookie or authentication.
    response = client.get_with_headers(SOURCE.rstrip('/') + path, HEADERS)
    if response.status != 200:
        raise FetchError('blocked' if response.status in (401, 403, 429) else 'partial',
                         f'HiBob public inventory HTTP {response.status}.')
    value = json.loads(response.body)
    if not isinstance(value, dict):
        raise ValueError('HiBob response must be an object.')
    return value


def _site(client):
    value = _get(client, '/api/career-site')
    if value.get('companyName') != 'Primer Technology' or value.get('isBobCareerSite') is not True:
        raise ValueError('HiBob public employer identity changed.')
    return value


def _list(client):
    value = _get(client, '/api/job-ad')
    entries = value.get('jobAdDetails')
    if not isinstance(entries, list) or len(entries) > MAX_JOBS:
        raise ValueError('HiBob full inventory list is missing or exceeds the bound.')
    # The published careers client fetches this single unfiltered endpoint.
    # Fail closed if the service begins advertising pagination or truncation.
    if any(key in value for key in ('next', 'nextPage', 'nextPageToken', 'hasMore', 'offset', 'limit')):
        raise ValueError('HiBob introduced unsupported inventory pagination.')
    for key in ('total', 'totalCount', 'count'):
        if key in value and (type(value[key]) is not int or value[key] != len(entries)):
            raise ValueError('HiBob reported count differs from the full list.')
    if not isinstance(value.get('filterGroups'), dict):
        raise ValueError('HiBob listing metadata is missing.')
    return value, entries


def _row(entry, company_id, company):
    if not isinstance(entry, dict):
        raise ValueError('HiBob posting is not an object.')
    ident = entry.get('id')
    if not isinstance(ident, str) or str(UUID(ident)) != ident:
        raise ValueError('HiBob posting ID is not a canonical UUID.')
    title, description = text(entry.get('title')), text(entry.get('description'))
    if not isinstance(entry.get('title'), str) or not isinstance(entry.get('description'), str) or not title or not description:
        raise ValueError('HiBob posting lacks a title or full description.')
    parts = []
    for field in BODY_FIELDS:
        value = entry.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError('HiBob published content field changed type.')
        if text(value):
            parts.append(text(value))
    for field, label in SALARY_FIELDS:
        value = entry.get(field)
        if value is not None:
            if isinstance(value, (dict, list, bool)):
                raise ValueError('HiBob salary field changed type.')
            if text(value):
                parts.append(label + ': ' + text(value))
    row = _base({'id': ident}, 'HiBob', company_id, company)
    row.update(title=title, description='\n\n'.join(parts), url=SOURCE + 'jobs/' + ident,
               location=', '.join(text(entry.get(k)) for k in ('site', 'country') if text(entry.get(k))),
               department=text(entry.get('department')), employment_type=text(entry.get('employmentType')),
               work_arrangement=text(entry.get('workspaceType')), updated_at=text(entry.get('publishedAt')))
    return row


def fetch_hibob(url, company_id, company, transport=None):
    if url != SOURCE or company_id != 'COMP-0456' or company != 'Primer':
        return Inventory('unsupported', reason='HiBob requires the verified Primer company and board.', source_url=url, ats='HiBob')
    client, jobs = transport or HTTPTransport(), []
    try:
        site = _site(client)
        original, entries = _list(client)
        seen, invalid = set(), 0
        for entry in entries:
            try:
                row = _row(entry, company_id, company)
                if row['posting_id'] in seen:
                    raise ValueError('HiBob repeated a posting ID.')
                seen.add(row['posting_id'])
                jobs.append(row)
            except (ValueError, TypeError, AttributeError):
                invalid += 1
        if invalid:
            raise FetchError('partial', f'HiBob saved {len(jobs)} full jobs; {invalid} invalid or duplicate postings remain incomplete.')
        check, _ = _list(client)
        if check != original or _site(client) != site:
            raise FetchError('partial', 'HiBob public inventory changed during retrieval.')
        return Inventory('complete', jobs, f'HiBob: retrieved all {len(jobs)} full public jobs and reconciled the complete inventory.', SOURCE, 'HiBob')
    except FetchError as exc:
        return Inventory('partial' if jobs else exc.status, jobs, exc.reason, SOURCE, 'HiBob')
    except (ValueError, TypeError, KeyError, AttributeError):
        return Inventory('partial', jobs, 'HiBob public identity, count or full-content schema validation failed.', SOURCE, 'HiBob')
