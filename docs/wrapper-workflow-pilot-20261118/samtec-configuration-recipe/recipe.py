"""Host-written trusted recipe; AI selects evidence IDs, never supplies Python."""
import difflib
import hashlib
import json
from pathlib import Path

VERSION = 'samtec-public-html-v1'
SOURCE_SHA256 = 'f14ccecd76181d183f29c46e281514f6606cc17e1d3b892323cc36850c6924ab'
SELECTIONS = {'listing':'full_search','container':'job_list','pagination':'next_link','range':'displayed_range'}
BINDING = {'company_id':'COMP-0739','company':'Samtec','ats':'Jobvite','host':'jobs.jobvite.com','slug':'samtec'}
TARGET_PATH = 'src/job_search_helper/shared_boards.py'
OLD_ALLOWED = "    if b.name=='Jobvite':return payload is None and bool(re.fullmatch('/'+re.escape(b.slug)+r'/(?:jobs|job/[A-Za-z0-9]+)',p.path)) and not p.query\n"
NEW_ALLOWED = """    if b.name=='Jobvite' and b.slug=='samtec' and b.root=='https://jobs.jobvite.com' and p.hostname=='jobs.jobvite.com' and p.path in {'/samtec/search','/samtec/search/'}:
        return payload is None and (not p.query or bool(re.fullmatch(r'p=[0-9]+',p.query)))
""" + OLD_ALLOWED
ROUTE = """        name,slug='Jobvite',parts[0];path='/'+slug+'/jobs'
        if slug=='samtec':
            path='/'+slug+'/search'
        if len(parts)==3 and parts[1]=='job':ident=parts[2]
        elif len(parts)>1 and parts[1:] not in (['jobs'],['search']):raise ValueError('Invalid Jobvite scope.')
"""
ENTRY = 'def html_listing(b,t):\n'
DISPATCH = "def html_listing(b,t):\n    if b.name=='Jobvite' and b.slug=='samtec':\n        return _samtec_html_listing(b,t)\n"
HELPER_SHA256 = 'dd4482b25bc02b9d6b8e3ac6031162912b00ab16c8a2d1459f0efc8f02117487'


def validate_selection(selection):
    if not isinstance(selection, dict) or set(selection) != set(SELECTIONS):
        raise ValueError('Recipe requires exactly listing, container, pagination and range evidence IDs.')
    if any(type(selection[key]) is not str or selection[key] != expected for key, expected in SELECTIONS.items()):
        raise ValueError('Unsupported or unverified evidence selection; no fallback is permitted.')
    return dict(selection)


def read_selection(raw):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate selection key.')
            result[key] = value
        return result
    if not isinstance(raw, str) or len(raw) > 4096:
        raise ValueError('Selection must be a bounded JSON string.')
    return validate_selection(json.loads(raw, object_pairs_hook=unique_keys))


def build(source, selection):
    """Return content and reviewable diff. Never write to source or install."""
    selected = validate_selection(selection)
    if not isinstance(source, bytes) or hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('Source differs from the independently approved route candidate.')
    original = source.decode('utf-8')
    if any(original.count(snippet) != 1 for snippet in (OLD_ALLOWED, ROUTE, ENTRY)):
        raise ValueError('Known source anchors are not unique.')
    helper = Path(__file__).with_name('samtec_helper.py.txt').read_bytes()
    if hashlib.sha256(helper).hexdigest() != HELPER_SHA256:
        raise ValueError('Trusted recipe helper hash mismatch.')
    result = original.replace(OLD_ALLOWED, NEW_ALLOWED, 1).replace(ENTRY, helper.decode() + DISPATCH, 1)
    compile(result, TARGET_PATH, 'exec')
    if result.count(ROUTE) != 1:
        raise ValueError('Accepted AI-authored route was changed.')
    diff = ''.join(difflib.unified_diff(original.splitlines(True), result.splitlines(True),
                                      fromfile='a/'+TARGET_PATH, tofile='b/'+TARGET_PATH))
    return {'content': result, 'patch': diff, 'receipt': {
        'recipe_version':VERSION, 'authorship':'Python recipe and listing/transport implementation are host-written. AI selected bounded evidence IDs; the previously approved route patch remains AI-authored.',
        'binding':dict(BINDING), 'selected_evidence':selected,
        'selection_sha256':hashlib.sha256(json.dumps(selected,sort_keys=True).encode()).hexdigest(),
        'source_sha256':SOURCE_SHA256, 'helper_sha256':HELPER_SHA256,
        'output_sha256':hashlib.sha256(result.encode()).hexdigest(),
        'target_path':TARGET_PATH, 'installed':False, 'live_validated':False}}
