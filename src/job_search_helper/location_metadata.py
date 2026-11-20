"""Country eligibility from complete official JobPosting structured addresses."""
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit

from .core import plain_text
from .locations import COUNTRY_CODES, LocationCheck, check_location


class _Schemas(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active, self.buffer, self.documents = False, '', []

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('type', '').casefold() == 'application/ld+json':
            self.active, self.buffer = True, ''

    def handle_data(self, data):
        if self.active:
            self.buffer += data

    def handle_endtag(self, tag):
        if tag == 'script' and self.active:
            try:
                self.documents.append(json.loads(self.buffer))
            except ValueError:
                pass
            self.active = False


def _jobs(value):
    if isinstance(value, list):
        for item in value:
            yield from _jobs(item)
    elif isinstance(value, dict):
        kind = value.get('@type', [])
        if kind == 'JobPosting' or isinstance(kind, list) and 'JobPosting' in kind:
            yield value
        yield from _jobs(value.get('@graph', []))


def _country(value):
    if isinstance(value, dict):
        value = value.get('name') or value.get('addressCountry') or ''
    value = str(value or '').strip()
    result = check_location(value)
    # An addressCountry field is a country, so CA/IN/DE cannot mean a state.
    if result.status == 'unknown' and value.upper() in COUNTRY_CODES:
        return LocationCheck('non_us', value)
    return result


def _same_url(left, right):
    a, b = urlsplit(left), urlsplit(right)
    def path(p):
        return re.sub(r'^/[a-z]{2}-[A-Z]{2}/', '/', p).rstrip('/')
    return a.scheme == b.scheme == 'https' and a.hostname == b.hostname and path(a.path) == path(b.path)


def structured_location(html, title, official_url):
    parser = _Schemas()
    parser.feed(html)
    matches = [job for document in parser.documents for job in _jobs(document)
               if plain_text(job.get('title', '')).casefold() == plain_text(title).casefold()
               and (not job.get('url') or _same_url(str(job['url']), official_url))]
    if len(matches) != 1:
        return LocationCheck('unknown', 'No unique matching official structured job address')
    job = matches[0]
    locations = job.get('jobLocation') or []
    locations = locations if isinstance(locations, list) else [locations]
    countries = []
    for place in locations:
        if not isinstance(place, dict) or not isinstance(place.get('address'), dict):
            return LocationCheck('unknown', 'Incomplete structured address')
        value = place['address'].get('addressCountry')
        if not value:
            return LocationCheck('unknown', 'Structured address has no country')
        countries.append(_country(value))
    applicants = job.get('applicantLocationRequirements') or []
    applicants = applicants if isinstance(applicants, list) else [applicants]
    for place in applicants:
        if not isinstance(place, dict) or place.get('@type') not in ('Country', 'AdministrativeArea'):
            return LocationCheck('unknown', 'Unclear remote applicant geography')
        countries.append(_country(place))
    if any(c.status == 'us' for c in countries):
        return LocationCheck('us', 'Official structured country includes United States')
    if countries and all(c.status == 'non_us' for c in countries):
        return LocationCheck('non_us', 'Official structured countries: ' + '; '.join(c.evidence for c in countries))
    return LocationCheck('unknown', 'Structured country coverage is incomplete or ambiguous')
