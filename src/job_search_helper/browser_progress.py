"""Per-job browser checkpoints, isolated by cycle, company and source URL."""
import json


SCHEMA = """CREATE TABLE IF NOT EXISTS browser_progress (
    cycle TEXT, company TEXT, source TEXT, kind TEXT, key TEXT, payload TEXT NOT NULL,
    PRIMARY KEY(cycle, company, source, kind, key))"""


class BrowserProgress:
    def __init__(self, inbox=None, cycle='', company='', source=''):
        self.inbox = inbox
        self.scope = (cycle, company, source)
        self.memory = {}
        self._entries = None

    def _read(self, kind):
        if self.inbox is None:
            return {k: json.loads(v) for (t, k), v in self.memory.items() if t == kind}
        with self.inbox.lock:
            rows = self.inbox.connection.execute(
                'SELECT key,payload FROM browser_progress WHERE cycle=? AND company=? AND source=? AND kind=?',
                (*self.scope, kind)).fetchall()
        return {key: json.loads(payload) for key, payload in rows}

    def _write(self, kind, key, value):
        payload = json.dumps(value, ensure_ascii=False)
        if self.inbox is None:
            self.memory[kind, key] = payload
            return
        with self.inbox.lock, self.inbox.connection:
            self.inbox.connection.execute(
                'INSERT INTO browser_progress VALUES (?,?,?,?,?,?) '
                'ON CONFLICT(cycle,company,source,kind,key) DO UPDATE SET payload=excluded.payload',
                (*self.scope, kind, key, payload))

    def entries(self):
        if self._entries is None:
            self._entries = self._read('job')
        return self._entries

    def discover(self, links):
        known = self.entries()
        for link in links:
            if link['url'] not in known:
                entry = {'link': link, 'job': None, 'attempts': 0, 'error': ''}
                self._write('job', link['url'], entry)
                known[link['url']] = entry

    def save_job(self, url, job):
        entry = dict(self.entries()[url], job=job, error='')
        self._write('job', url, entry)
        self._entries[url] = entry

    def failed(self, url, error):
        previous = self.entries()[url]
        entry = dict(previous, attempts=previous['attempts'] + 1, error=error)
        self._write('job', url, entry)
        self._entries[url] = entry

    def listing(self, source):
        return self._read('listing').get('state', {'queue': [source], 'visited': [], 'complete': False})

    def save_listing(self, state):
        self._write('listing', 'state', state)
