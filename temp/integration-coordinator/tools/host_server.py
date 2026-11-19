"""Authenticated loopback bridge for source-only wrapper development."""
import hmac
import json
import os
from pathlib import Path
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import sqlite3
import coding_tools
import public_tools
from coordinator import Coordinator
from coordinator_supervision import (CoordinatorSupervision,
                                     external_retention_snapshot as retention_counts,
                                     watchdog)

BASE = Path(__file__).resolve().parent.parent
JOB_SEARCH_ROOT = BASE.parent.parent
if str(JOB_SEARCH_ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(JOB_SEARCH_ROOT / 'src'))
TOKEN = (BASE / 'bridge-token').read_text().strip()
SLOTS = threading.BoundedSemaphore(4)
COORDINATOR = None
SUPERVISION = None
SCRAPE_OUTCOME_CONSUMER = 'wrapper-coordinator'


def host_external_retention_snapshot():
    """Count scraper/release evidence that supervision must never discard."""
    from job_search_helper.cli import job_database_path, load_environment, storage_backend
    from job_search_helper.company_events import BRIDGE_CONSUMER
    load_environment(JOB_SEARCH_ROOT / '.env')
    if storage_backend() != 'sqlite':
        raise ValueError('External retention snapshot requires local SQLite storage.')
    return retention_counts(
        job_database_path(), company_consumer=BRIDGE_CONSUMER,
        outcome_consumer=SCRAPE_OUTCOME_CONSUMER)


def build_supervision(coordinator, catch_up=None):
    """Wire the real host's zero-argument probes into maintenance supervision."""
    if catch_up is None:
        catch_up = lambda: drain_scrape_outcomes(limit=20)
    return CoordinatorSupervision(
        coordinator, catch_up,
        retention_probe=host_external_retention_snapshot)


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


def current_company_repair_snapshot(company_id):
    """Read one local Company profile-binding snapshot without Google access."""
    try:
        from job_search_helper.cli import (job_database_path, load_environment,
                                           storage_backend)
        from job_search_helper.company_events import current_company_repair_snapshot as snapshot
        from job_search_helper.sqlite_repository import SQLiteRepository
        load_environment(JOB_SEARCH_ROOT / '.env')
        if storage_backend() != 'sqlite':
            return None
        spreadsheet_id = os.environ.get('SPREADSHEET_ID', '').strip()
        if not spreadsheet_id:
            return None
        repository = SQLiteRepository(job_database_path(), spreadsheet_id, readonly=True)
        try:
            return snapshot(repository, company_id)
        finally:
            repository.close()
    except (ImportError, OSError, ValueError, sqlite3.Error):
        return None


def select_repair_profile(held_repair):
    """Build a task only from a reviewed profile and fresh local Company fact."""
    try:
        from coordinator_repair_profiles import select_profile
        identity = held_repair.get('outcome', {}).get('identity', {})
        company_id = identity.get('company_id')
        return select_profile(held_repair, current_company_repair_snapshot(company_id))
    except (AttributeError, ImportError, TypeError, ValueError):
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
                if body.get('action') == 'supervision-status':
                    if set(body) != {'action'}:
                        raise ValueError('Supervision status has unsupported fields.')
                    return self.reply(200, {'ok': True, 'supervision': SUPERVISION.status()})
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
    COORDINATOR = Coordinator(company_revision_resolver=current_company_revision,
                              repair_profile_selector=select_repair_profile)
    COORDINATOR.start()
    SUPERVISION = build_supervision(COORDINATOR)
    SUPERVISION.start()

    def shutdown(signum, frame):
        SUPERVISION.shutdown('Service signal ' + str(signum))
        # HTTPServer.shutdown must run outside the serve_forever thread.
        threading.Thread(target=server.shutdown, name='coordinator-http-shutdown', daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    threading.Thread(target=watchdog, args=(COORDINATOR, SUPERVISION),
                     kwargs={'exit_process': os._exit},
                     name='coordinator-supervisor', daemon=True).start()
    try:
        server.serve_forever()
    finally:
        if SUPERVISION.status() is None or SUPERVISION.status().get('state') != 'SHUTDOWN_PAUSED':
            SUPERVISION.shutdown('HTTP service stopped')
        server.server_close()
