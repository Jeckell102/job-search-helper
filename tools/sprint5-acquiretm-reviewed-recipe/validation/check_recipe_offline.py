"""Independent offline source/actual-JS gate. No provider or model calls."""
import ast
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import subprocess
from urllib.parse import urljoin

STAGE = Path('/tmp/jsh-s5-acquiretm-membership-repair.20261121')
ROOT = Path('/tmp/jsh-s5-amphenol-recipe-live-candidate')
RAW = Path('/tmp/jsh-s5-amphenol-raw-fixture')
SOURCE = 'https://amphenol-aerospace.acquiretm.com/home.aspx'
PINS = {
    STAGE / 'repair_recipe/acquiretm_membership_recipe.py': 'd6465801a0932a85895441914170d11e0258e642927f2d3349e2d044dfebc377',
    STAGE / 'repair_recipe/test_acquiretm_membership_recipe.py': '5c8e73667ed66ad26a7c989ab3da9dc47bc6940210164c322499a9c6dd81e6f0',
    ROOT / 'src/job_search_helper/acquiretm.py': '895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d',
    ROOT / 'src/job_search_helper/ats.py': '111ccb9067402832ad96b798100dfca293668cf24830409874c1ab4d6eaac07e',
    RAW / 'result.json': 'acc0ba9b1fa8855dc588cc28d9911bf4ab6fa58816cba426e8ca9954437e4bdf',
    Path('/tmp/jsh-s5-amphenol-typed-live/result.json'): 'd10331c3e89b63ef00a8a26af7ac4c69f66beb95167e3b2005b4d9e101cd0602',
    ROOT / 'tests/test_acquiretm.py': '5bace6904b1630871477aa2b5b408a591813a834742a2bcca85c757c8dd5e908',
}


def require(value, message):
    if not value:
        raise AssertionError(message)


def preserved(tree):
    result = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            continue
        if node.name in ('_wait_for_update', '_wait_for_listing_membership_change'):
            continue
        if node.name == 'inventory':
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in ('_wait_for_update', '_wait_for_listing_membership_change'):
                    sub.func.id, sub.args = 'READINESS', []
        result[node.name] = ast.dump(node)
    return result


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and 'href' in attrs:
            self.links.append(urljoin(SOURCE, attrs['href']))


class FetchError(Exception):
    pass


class CapturePage:
    def wait_for_function(self, expression, *, arg, timeout):
        self.expression, self.arg, self.timeout = expression, arg, timeout


def main():
    for path, pin in PINS.items():
        require(hashlib.sha256(path.read_bytes()).hexdigest() == pin, str(path))
    spec = importlib.util.spec_from_file_location('recipe', STAGE / 'repair_recipe/acquiretm_membership_recipe.py')
    recipe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recipe)
    baseline = (STAGE / recipe.TARGET_PATH).read_bytes()
    witness = Path('/tmp/jsh-s5-amphenol-typed-live/result.json').read_bytes()
    result = recipe.build(baseline, recipe.SELECTION, witness)
    candidate = (ROOT / recipe.TARGET_PATH).read_bytes()
    require(result['source'].encode() == candidate, 'candidate differs from exact compiler output')
    require(preserved(ast.parse(baseline)) == preserved(ast.parse(candidate)), 'non-readiness guard changed')
    invalid = [({}, baseline, witness), ({**recipe.SELECTION, 'extra': True}, baseline, witness),
               ({'strategy': 'html_change', 'evidence': 'W1'}, baseline, witness),
               (recipe.SELECTION, baseline + b'\n', witness),
               (recipe.SELECTION, baseline, witness + b'\n')]
    for selection, source, evidence in invalid:
        try:
            recipe.build(source, selection, evidence)
        except ValueError:
            continue
        raise AssertionError('invalid compiler input accepted')
    raw = json.loads((RAW / 'result.json').read_bytes())
    snapshots = []
    for item in raw['snapshots']:
        content = (RAW / item['file']).read_bytes()
        require(hashlib.sha256(content).hexdigest() == item['sha256'], 'raw snapshot changed')
        snapshots.append(Links(content.decode()).links)
    ids = []
    from urllib.parse import urlsplit, parse_qs
    for href in snapshots[1]:
        url = urlsplit(href)
        if url.hostname == 'amphenol-aerospace.acquiretm.com' and url.path == '/job_details_clean.aspx':
            ids.extend(parse_qs(url.query).get('ID', []))
    require(len(ids) == 25 and len(set(ids)) == 25, 'old membership changed')
    tree = ast.parse(candidate)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_wait_for_listing_membership_change')
    ats_tree = ast.parse((ROOT / 'src/job_search_helper/ats.py').read_bytes())
    timeout = next(ast.literal_eval(n.value) for n in ats_tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'ACQUIRETM_REFRESH_TIMEOUT_MS' for t in n.targets))
    scope = {'ACQUIRETM_REFRESH_TIMEOUT_MS': timeout, 'DETAIL_PATH': '/job_details_clean.aspx', 'FetchError': FetchError}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / recipe.TARGET_PATH), 'exec'), scope)
    page = CapturePage()
    scope[node.name](page, dict.fromkeys(ids))
    require(page.arg == {'path': '/job_details_clean.aspx', 'seen': sorted(ids)}, 'actual callback args wrong')
    require(page.timeout == timeout == 12_000, 'normal readiness timeout changed')
    cases = [('old', snapshots[1], False), ('premature', snapshots[2], False), ('late', snapshots[3], True),
             ('foreign_origin', ['https://other.example/job_details_clean.aspx?ID=999999'], False),
             ('foreign_path', ['https://amphenol-aerospace.acquiretm.com/other.aspx?ID=999999'], False),
             ('nonnumeric', ['https://amphenol-aerospace.acquiretm.com/job_details_clean.aspx?ID=abc'], False)]
    program = "const vm=require('vm'); const x=JSON.parse(require('fs').readFileSync(0,'utf8')); const c={URL, location:{origin:'https://amphenol-aerospace.acquiretm.com'},document:{querySelectorAll:()=>x.links.map(href=>({href}))}}; const f=vm.runInNewContext('('+x.expression+')',c); console.log(JSON.stringify(f(x.arg)));"
    outputs = {}
    for name, links, expected in cases:
        run = subprocess.run(['/usr/bin/node', '-e', program], input=json.dumps({'expression': page.expression, 'arg': page.arg, 'links': links}), text=True, capture_output=True, timeout=5, check=True)
        actual = json.loads(run.stdout)
        require(actual is expected, name + ' actual callback failure')
        outputs[name] = actual
    class TimeoutPage:
        def wait_for_function(self, *_args, **_kwargs):
            raise TimeoutError('fixture timeout')
    try:
        scope[node.name](TimeoutPage(), dict.fromkeys(ids))
    except FetchError as error:
        require(error.args[0] == 'partial', 'timeout did not fail partial')
    else:
        raise AssertionError('timeout accepted')
    print(json.dumps({'verdict': 'ACCEPT_SOURCE_ONLY', 'fixed_build_equal': True, 'non_readiness_guards_unchanged': True, 'invalid_inputs_rejected': len(invalid), 'actual_callback': outputs, 'timeout': 'partial', 'original_six_test_file_unchanged': True, 'live_validation': 'NOT_RUN'}, sort_keys=True))


if __name__ == '__main__':
    main()
