"""Authenticated loopback bridge for source-only wrapper development."""
import hmac
import json
import os
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import sqlite3
import time
import coding_tools
import public_tools
from coordinator import Coordinator

BASE = Path(__file__).resolve().parent.parent
JOB_SEARCH_ROOT = BASE.parent.parent
if str(JOB_SEARCH_ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(JOB_SEARCH_ROOT / 'src'))
TOKEN = (BASE / 'bridge-token').read_text().strip()
SLOTS = threading.BoundedSemaphore(4)
COORDINATOR = None
SCRAPE_OUTCOME_CONSUMER = 'wrapper-coordinator'


def current_company_revision(company_id):
    """Read one local, eligible Company revision without contacting Google.

    The coordinator uses this only to reject stale promoted repairs.  Any
    missing configuration, non-local storage, or database error is a safe
    ``None`` result, which keeps the repair paused.
    """
    try:
        from job_search_helper.cli import (job_database_path, load_environment,
                                           storage_backend)
        from job_search_helper.company_events import current_company_source_revision
        from job_search_helper.sqlite_repository import SQLiteRepository
        load_environment(JOB_SEARCH_ROOT / '.env')
        if storage_backend() != 'sqlite':
            return None
        spreadsheet_id = os.environ.get('SPREADSHEET_ID', '').strip()
        if not spreadsheet_id:
            return None
        repository = SQLiteRepository(job_database_path(), spreadsheet_id, readonly=True)
        try:
            return current_company_source_revision(repository, company_id)
        finally:
            repository.close()
    except (ImportError, OSError, ValueError, sqlite3.Error):
        return None


def drain_scrape_outcomes(*, limit=20):
    """Deliver durable scraper outcomes into held-only coordinator intake."""
    from coordinator_outcome_delivery import drain
    from job_search_helper.cli import job_database_path, load_environment, storage_backend
    from job_search_helper.sqlite_repository import SQLiteRepository
    load_environment(JOB_SEARCH_ROOT / '.env')
    if storage_backend() != 'sqlite':
        raise ValueError('Scrape outcome delivery requires local SQLite storage.')
    spreadsheet_id = os.environ.get('SPREADSHEET_ID', '').strip()
    if not spreadsheet_id:
        raise ValueError('Scrape outcome delivery requires a configured spreadsheet ID.')
    repository = SQLiteRepository(job_database_path(), spreadsheet_id)
    try:
        return drain(repository, COORDINATOR, consumer=SCRAPE_OUTCOME_CONSUMER, limit=limit)
    finally:
        repository.close()


def execute_manual(name, args, names):
    """Authenticated manual requests grant only their exact shared-checkout path.

    The caller retains the existing tool-name authorization and workspace lock.
    No task scope or isolated workspace can be inherited by this compatibility path.
    """
    if coding_tools.WORKSPACE.get() is not None:
        raise ValueError('Manual edits cannot inherit a task workspace.')
    paths = [args.get('path')] if isinstance(args, dict) and name in ('code_edit', 'code_create') else []
    token = coding_tools.EDIT_SCOPE.set(paths)
    try:
        return coding_tools.execute(name, args, names)
    finally:
        coding_tools.EDIT_SCOPE.reset(token)


def supervise(coordinator, exit_process=os._exit, interval=1):
    """A dead scheduler must fail the service so Restart=on-failure can recover it."""
    while True:
        if not coordinator.thread.is_alive():
            exit_process(75)
            return
        time.sleep(interval)


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
                if body.get('action') == 'drain-scrape-outcomes':
                    if set(body) - {'action', 'limit'}:
                        raise ValueError('Scrape outcome drain has unsupported fields.')
                    return self.reply(200, drain_scrape_outcomes(limit=body.get('limit', 20)))
                return self.reply(200, COORDINATOR.command(body))
            if not isinstance(body, dict) or set(body) != {'name', 'args', 'names'}:
                raise ValueError('Invalid request')
            names = body['names']
            if not isinstance(names, list) or any(not isinstance(n, str) or n not in coding_tools.NAMES | public_tools.NAMES for n in names):
                raise ValueError('Invalid allowed tools')
            if not isinstance(body['name'], str):
                raise ValueError('Invalid tool name')
            executor = public_tools.execute if body['name'] in public_tools.NAMES else execute_manual
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
        except sqlite3.Error:
            self.reply(503, {'ok': False, 'error': 'Task database unavailable. No action was replayed; check coordinator health.'})
        except (ValueError, TypeError, OSError) as exc:
            self.reply(200 if self.path == '/coordinator' else 400,
                       {'ok': False, 'error': str(exc)[:350]})
        finally:
            SLOTS.release()


if __name__ == '__main__':
    os.umask(0o077)
    server = ThreadingHTTPServer(('127.0.0.1', 18789), Handler)
    COORDINATOR = Coordinator(company_revision_resolver=current_company_revision)
    COORDINATOR.start()
    threading.Thread(target=supervise, args=(COORDINATOR,), name='coordinator-supervisor', daemon=True).start()
    server.serve_forever()
