"""Execute the exact reviewed candidate callback on inert, captured listings."""
import ast
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import sync_playwright

stage = Path('/tmp/jsh-s5-acquiretm-membership-repair.20261121')
script = stage / 'repair_recipe' / 'acquiretm_membership_recipe.py'
raw = Path('/tmp/jsh-s5-amphenol-raw-fixture')
measure = json.loads((raw/'result.json').read_bytes())
witness = Path('/tmp/jsh-s5-amphenol-typed-live/result.json').read_bytes()
recipe_hash = 'd6465801a0932a85895441914170d11e0258e642927f2d3349e2d044dfebc377'
expected_candidate = '895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d'
assert sha256(script.read_bytes()).hexdigest() == recipe_hash
module_spec = importlib.util.spec_from_file_location('exact_acquiretm_recipe', script)
recipe = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(recipe)
for disallowed in ({'strategy': 'fixed_delay', 'evidence': 'W1'}, {'strategy': 'listing_membership_change','evidence': 'W2'}):
    try:
        recipe.validate_selection(disallowed)
    except ValueError:
        pass
    else:
        raise RuntimeError('Unreviewed model choice accepted')
fixed = recipe.build((stage/recipe.TARGET_PATH).read_bytes(), {'strategy':'listing_membership_change','evidence':'W1'}, witness)
assert sha256(fixed['source'].encode()).hexdigest() == expected_candidate
function = next(node for node in ast.parse(fixed['source']).body
                if isinstance(node, ast.FunctionDef) and node.name == '_wait_for_listing_membership_change')
wait = next(node for node in ast.walk(function) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute) and node.func.attr == 'wait_for_function')
predicate = ast.literal_eval(wait.args[0])

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors = []
    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get('href') if tag == 'a' else None
        if href:
            url = urlsplit(urljoin(measure['source'], href))
            if url.path == '/job_details_clean.aspx' and url.netloc == urlsplit(measure['source']).netloc:
                self.anchors.append(url.geturl())


def anchors(index):
    item = measure['snapshots'][index]
    body = (raw/item['file']).read_bytes()
    assert sha256(body).hexdigest() == item['sha256']
    parsed = Links()
    parsed.feed(body.decode())
    return parsed.anchors


def inert(links):
    return '<!doctype html><html><body>' + ''.join(f'<a href="{escape(url, quote=True)}">Role</a>' for url in links) + '</body></html>'


old, early, late = (anchors(i) for i in (0, 2, 3))
assert old == early and len(old) == 25 and len(late) == 14 and set(old).isdisjoint(late)
arguments = {'path': '/job_details_clean.aspx', 'seen': [urlsplit(url).query.removeprefix('ID=') for url in old]}
definition = measure['source']
with sync_playwright() as pw:
    with pw.chromium.launch(headless=True) as browser:
        page = browser.new_page()
        def offline(route):
            if route.request.url == definition:
                route.fulfill(status=200, content_type='text/html', body=inert(old))
            else:
                route.abort()
        page.route('**/*', offline)
        page.goto(definition)
        assert page.evaluate(predicate, arguments) is False
        page.set_content(inert(early) + '<div>Progress changed</div>')
        assert page.evaluate(predicate, arguments) is False
        page.set_content('<a href="https://outside.invalid/job_details_clean.aspx?ID=999">Foreign</a>')
        assert page.evaluate(predicate, arguments) is False
        page.set_content(inert(late))
        assert page.evaluate(predicate, arguments) is True
print('PASS: exact callback rejected old, premature and foreign listing data and accepted the observed late page')
