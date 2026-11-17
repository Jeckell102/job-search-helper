"""Authenticated loopback bridge for source-only wrapper development."""
import hmac
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import coding_tools
import public_tools
from coordinator import Coordinator

BASE = Path(__file__).resolve().parent.parent
TOKEN = (BASE / 'bridge-token').read_text().strip()
SLOTS = threading.BoundedSemaphore(4)
COORDINATOR = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log submitted code, tokens, or conversation content.

    def reply(self, status, value):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.connection.settimeout(120)
        if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + TOKEN):
            return self.reply(403, {'ok': False, 'error': 'Unauthorized'})
        if self.path not in ('/execute', '/coordinator'):
            return self.reply(404, {'ok': False, 'error': 'Unknown endpoint'})
        if not SLOTS.acquire(blocking=False):
            return self.reply(429, {'ok': False, 'error': 'Development tools are busy'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 400000:
                raise ValueError('Invalid request size')
            body = json.loads(self.rfile.read(length))
            if self.path == '/coordinator':
                if not isinstance(body, dict):
                    raise ValueError('Invalid coordinator request.')
                return self.reply(200, COORDINATOR.command(body))
            if not isinstance(body, dict) or set(body) != {'name', 'args', 'names'}:
                raise ValueError('Invalid request')
            names = body['names']
            if not isinstance(names, list) or any(not isinstance(n, str) or n not in coding_tools.NAMES | public_tools.NAMES for n in names):
                raise ValueError('Invalid allowed tools')
            if not isinstance(body['name'], str):
                raise ValueError('Invalid tool name')
            executor = public_tools.execute if body['name'] in public_tools.NAMES else coding_tools.execute
            mutation = body['name'] in ('code_edit', 'code_create', 'code_commit', 'code_test')
            acquired = not mutation or COORDINATOR.workspace_lock.acquire(blocking=False)
            if not acquired:
                return self.reply(200, {'ok': False, 'error': 'A coordinator worker owns the development workspace. Pause it and wait for PAUSED before manual edits or tests.'})
            try:
                result = executor(body['name'], body['args'], set(names))
            finally:
                if mutation:
                    COORDINATOR.workspace_lock.release()
            result['workspace_location'] = 'scraper computer: Job Search Helper dev/wrapper-coder/repo'
            self.reply(200, result)
        except (ValueError, TypeError, OSError) as exc:
            self.reply(200 if self.path == '/coordinator' else 400,
                       {'ok': False, 'error': str(exc)[:350]})
        finally:
            SLOTS.release()


if __name__ == '__main__':
    os.umask(0o077)
    server = ThreadingHTTPServer(('127.0.0.1', 18789), Handler)
    COORDINATOR = Coordinator()
    COORDINATOR.start()
    server.serve_forever()
