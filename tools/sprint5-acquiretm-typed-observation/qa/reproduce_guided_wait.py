"""Offline reproduction of settled WRAP-9f416bbfab's browser predicate failure."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path('/tmp/jsh-s5-amphenol-guided.dev/tasks/WRAP-9f416bbfab/repo')
SOURCE = ROOT / 'src/job_search_helper/acquiretm.py'
EXPECTED = '652475bc73f07bddb3d782fbbfb3442b4a0054ee401d7dcbaf06ed9f81aecc4e'
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == EXPECTED, 'candidate changed'
sys.path.insert(0, str(ROOT / 'src'))
from job_search_helper.acquiretm import _wait_for_update
from job_search_helper.ats import FetchError


class BrowserJavaScriptPage:
    """Evaluate the actual callback in an isolated JS world with a DOM stand-in.

    Playwright's Python Page object is intentionally not a browser JS global.
    This runs no browser and makes no network request.
    """
    def wait_for_function(self, expression, *, arg, timeout):
        program = r'''
const vm = require('node:vm');
const input = JSON.parse(process.argv[1]);
const context = {document: {body: {innerHTML: '<p>Updated page</p>'},
  documentElement: {outerHTML: '<html><body><p>Updated page</p></body></html>'}},
  old: input.arg};
try {
  const result = vm.runInNewContext('(' + input.expression + ')(old)', context, {timeout: 1000});
  process.stdout.write(JSON.stringify({expression: input.expression, result}));
} catch (error) {
  process.stdout.write(JSON.stringify({expression: input.expression, name: error.name, message: error.message}));
  process.exitCode = 2;
}
'''
        result = subprocess.run(['/usr/bin/node', '-e', program,
                                 json.dumps({'expression': expression, 'arg': arg})],
                                capture_output=True, text=True, timeout=5, check=False)
        observed = json.loads(result.stdout)
        print(json.dumps({'javascript_evidence': observed}), flush=True)
        if result.returncode:
            raise RuntimeError(observed['name'] + ': ' + observed['message'])
        assert observed.get('result') is True, 'updated DOM did not satisfy wait predicate'


try:
    _wait_for_update(BrowserJavaScriptPage(), '<html><body><p>Old page</p></body></html>')
except FetchError as error:
    print(json.dumps({'verdict': 'REJECT', 'status': error.status, 'reason': str(error),
                      'cause': str(error.__cause__), 'source_sha256': EXPECTED}), flush=True)
    raise SystemExit(1)
raise SystemExit('Expected failure was not reproduced; re-review candidate.')
