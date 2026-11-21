"""Verify the two reviewed public employer authority shapes without executing them."""

from collections import Counter
from hashlib import sha256
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from rippling_capture import CaptureError


FORTERRA_CAREERS = 'https://www.forterra.com/careers'
FORTERRA_BOARD = 'https://ats.rippling.com/forterra/jobs'
PDW_CAREERS = 'https://www.pdw.ai/careers'
PDW_BOARD = 'https://ats.rippling.com/pdwcareers/jobs'
PDW_ALIAS = 'https://ats.rippling.com/pdwcareers'
PDW_LOCATION = '/pdwcareers/jobs'
FORTERRA_MOUNT = 'rr-job-board-forterra'
GOTENNA_MOUNT = 'rr-job-board-gotenna'
# Exact independently reviewed script bytes identify the mount/tenant pairs.
# A changed script is new evidence even if it repeats the same declarations.
FORTERRA_SCRIPTS = {
    '97ce81ad2c27efb55f0a94a3276b42c0d4c1b3b1c5de998629651f6bf05cfae0': FORTERRA_MOUNT,
    'e0ad0e4d271f34cba04c87d28ea5d85736ab6fa60af3cb788bb2fcc7f5b8fc79': GOTENNA_MOUNT,
}
FORTERRA_MOUNTS = {FORTERRA_MOUNT, GOTENNA_MOUNT}
VOID_ELEMENTS = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
                           'meta', 'param', 'source', 'track', 'wbr'})
INACTIVE_ELEMENTS = frozenset({'template', 'noscript', 'style', 'textarea', 'title', 'xmp', 'iframe',
                               'noembed', 'noframes', 'plaintext', 'select', 'svg', 'math', 'object', 'canvas'})
STATUS_LINE = re.compile(r'HTTP/(?:1\.1|2) ([1-5][0-9]{2})(?: [\x20-\x7e]*)?')
HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
INLINE_HIDING = re.compile(r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse)'
                           r'|content-visibility\s*:\s*hidden)\s*(?:!\s*important\s*)?(?:;|$)', re.I)
CSS_COMMENT = re.compile(r'/\*.*?\*/', re.S)
RIPPLING_SCRIPT_HINT = re.compile(r'rr-job-board-|ats(?:\.us1)?\.rippling\.com|\b(?:boardId|jobBoardSlug)\s*[:=]', re.I)


def require(condition, reason):
    if not condition:
        raise CaptureError(reason)


def exact_fields(value, fields):
    require(isinstance(value, dict) and set(value) == fields, 'Malformed public employer authority record')


def response_headers(raw, allowed_statuses, *, exact_refresh=None):
    """Read exact captured header blocks and reject ambiguous final responses."""
    require(isinstance(raw, str) and len(raw) <= 65536 and raw.endswith('\r\n\r\n'),
            'Malformed public HTTP response headers')
    blocks = raw[:-4].split('\r\n\r\n')
    statuses = []
    locations = []
    refreshes = []
    for block in blocks:
        first, *lines = block.split('\r\n')
        status = STATUS_LINE.fullmatch(first)
        require(status is not None, 'Malformed public HTTP response status')
        statuses.append(int(status[1]))
        for line in lines:
            name, separator, value = line.partition(':')
            require(separator and HEADER_NAME.fullmatch(name)
                    and not any(ord(char) < 32 and char != '\t' or ord(char) == 127 for char in value),
                    'Malformed public HTTP response header field')
            field = name.lower()
            if field == 'location':
                locations.append(value.strip(' \t'))
            elif field == 'refresh':
                refreshes.append(value.strip(' \t'))
    require(tuple(statuses) in allowed_statuses, 'Unexpected public HTTP response status or chain')
    require(not refreshes or exact_refresh is not None and refreshes == [exact_refresh],
            'Public HTTP response contains an unsupported refresh directive')
    return locations


def header_digest(raw):
    try:
        return sha256(raw.encode('latin-1')).hexdigest()
    except UnicodeEncodeError:
        raise CaptureError('Malformed public HTTP header octets') from None


def explicitly_hidden(tag, attributes):
    names = {key for key, _ in attributes}
    if names & {'hidden', 'inert', 'popover'} or tag in {'dialog', 'details'} and 'open' not in names:
        return True
    for key, value in attributes:
        if key == 'aria-hidden' and (value or '').strip().lower() == 'true':
            return True
        if key == 'style' and value:
            style = CSS_COMMENT.sub('', value)
            # A declaration containing CSS escapes or incomplete comments can
            # hide an ancestor in ways this narrow visibility check cannot read.
            if '\\' in style or '/*' in style or INLINE_HIDING.search(style):
                return True
    return False


class PublicEmployerPage(HTMLParser):
    def __init__(self, *, inspect_widgets):
        super().__init__()
        self.inspect_widgets = inspect_widgets
        self.stack = []
        self.mounts = Counter()
        self.scripts = Counter()
        self.targets = set()
        self.script = None

    def handle_starttag(self, tag, attrs):
        require(not (tag == 'meta' and any(key == 'http-equiv' and (value or '').strip().lower() == 'refresh'
                                          for key, value in attrs)), 'Public employer markup contains a refresh directive')
        active = not explicitly_hidden(tag, attrs) and not (self.stack and self.stack[-1][1])
        ids = [value for key, value in attrs if key == 'id']
        if FORTERRA_MOUNTS.intersection(ids):
            require(active and len(ids) == 1 and attrs == [('id', ids[0])] and tag == 'div',
                    'Forterra widget mount is hidden or malformed')
            self.mounts[ids[0]] += 1
        if active and tag in {'a', 'iframe'}:
            field = 'href' if tag == 'a' else 'src'
            targets = [value for key, value in attrs if key == field]
            for link in (value for value in targets if value):
                if 'rippling.com' in urlsplit(link).netloc.lower():
                    require(tag == 'a' and len(targets) == 1, 'Ambiguous public Rippling link or frame')
                    self.targets.add(link)
        if tag == 'script' and self.inspect_widgets:
            self.script = (active, attrs, [])
        if tag not in VOID_ELEMENTS:
            self.stack.append((tag, not active or tag in INACTIVE_ELEMENTS or tag == 'script'))

    def handle_startendtag(self, tag, attrs):
        if tag in VOID_ELEMENTS:
            self.handle_starttag(tag, attrs)
            return
        require(tag not in INACTIVE_ELEMENTS | {'script', 'a'} and not FORTERRA_MOUNTS.intersection(
            value for key, value in attrs if key == 'id'), 'Self-closing public authority markup is ambiguous')

    def handle_data(self, data):
        if self.script is not None:
            self.script[2].append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            active, attrs, chunks = self.script
            self.script = None
            body = ''.join(chunks)
            if active and (RIPPLING_SCRIPT_HINT.search(body) or any(
                    key == 'src' and RIPPLING_SCRIPT_HINT.search(value or '') for key, value in attrs)):
                digest = sha256(body.encode()).hexdigest()
                require(not attrs and digest in FORTERRA_SCRIPTS, 'Unreviewed active public widget script')
                require(self.mounts[FORTERRA_SCRIPTS[digest]] == 1, 'Reviewed widget script precedes its unique mount')
                self.scripts[digest] += 1
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def check_public_authority(company_id, board_url, authority):
    """Return a compact witness for the exact frozen employer-specific scope."""
    exact_fields(authority, {'url', 'headers', 'body', 'redirect'})
    routes = {
        'COMP-0066': (FORTERRA_CAREERS, FORTERRA_BOARD),
        'COMP-0178': (PDW_CAREERS, PDW_BOARD),
    }
    require((authority['url'], board_url) == routes.get(company_id), 'Unexpected public employer or board URL')
    body, headers, redirect = authority['body'], authority['headers'], authority['redirect']
    require(isinstance(body, str), 'Malformed public employer body')
    allowed_statuses = {(200,), (103, 200)} if company_id == 'COMP-0066' else {(200,)}
    require(not response_headers(headers, allowed_statuses), 'Public employer response contains a redirect claim')
    witness = {'url': authority['url'], 'status': 200, 'headers_sha256': header_digest(headers),
               'body_sha256': sha256(body.encode()).hexdigest()}
    page = PublicEmployerPage(inspect_widgets=company_id == 'COMP-0066')
    try:
        page.feed(body)
        page.close()
    except (ValueError, UnicodeError) as error:
        if isinstance(error, CaptureError):
            raise
        raise CaptureError('Malformed public employer markup') from None
    require(page.script is None, 'Incomplete public employer script markup')
    if company_id == 'COMP-0066':
        require(redirect is None and not page.targets, 'Unexpected Forterra redirect or static Rippling target')
        require(page.mounts == Counter(FORTERRA_MOUNTS) and page.scripts == Counter(FORTERRA_SCRIPTS.keys()),
                'Forterra employer lacks the unique reviewed widget pair')
        witnessed = {mount: digest for digest, mount in FORTERRA_SCRIPTS.items()}
        witness['widgets'] = {
            'approved': {'mount_id': FORTERRA_MOUNT, 'tenant': 'forterra', 'script_sha256': witnessed[FORTERRA_MOUNT]},
            'excluded': {'mount_id': GOTENNA_MOUNT, 'tenant': 'gotenna-inc', 'script_sha256': witnessed[GOTENNA_MOUNT]},
        }
    else:
        require(not (page.mounts or page.scripts) and page.targets == {PDW_BOARD, PDW_ALIAS},
                'PDW employer does not link the exact canonical and alias URLs')
        exact_fields(redirect, {'url', 'headers'})
        require(redirect['url'] == PDW_ALIAS, 'Unexpected PDW employer alias URL')
        # The observed Vercel response repeats the same exact relative target in Refresh.
        locations = response_headers(redirect['headers'], {(308,)}, exact_refresh=f'0;url={PDW_LOCATION}')
        require(locations == [PDW_LOCATION], 'PDW redirect target is absent, ambiguous, or outside exact scope')
        witness['redirect'] = {'url': PDW_ALIAS, 'status': 308, 'location': PDW_LOCATION,
                               'canonical_url': PDW_BOARD, 'headers_sha256': header_digest(redirect['headers'])}
    return witness
