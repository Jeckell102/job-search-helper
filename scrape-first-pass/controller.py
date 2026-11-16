#!/usr/bin/env python3
"""Scrape, verify publication, and run title review with Codex Luna Medium.

Only existing managed commands change job data. This controller owns its own
workflow journal and model input/output files, never the scraper's databases.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

MODEL = 'gpt-5.6-luna'
EFFORT = 'medium'
PROMPT_ID = '1bcv5MMcCySGDzolaFyZYQZYOvaMZEdqTQV6a8KnTMxA'
FINISHED = {'Complete', 'Complete with exceptions'}
DRAINED = {'DRAINED', 'DRAINED_WITH_EXCEPTIONS'}
HERE = Path(__file__).resolve().parent


class Blocked(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


@contextmanager
def exclusive(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Blocked('Another pipeline controller is active. Use status; do not remove locks.') from exc
        try:
            yield handle
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def parse_json_file(path):
    # Managed commands sometimes print progress before their final JSON object.
    raw = path.read_text(encoding='utf-8')
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != '{' or (index and raw[index - 1] != '\n'):
            continue
        try:
            value, end = decoder.raw_decode(raw[index:])
            if isinstance(value, dict) and not raw[index + end:].strip():
                return value
        except ValueError:
            pass
    raise Blocked(f'No complete JSON receipt in {path}')


def extract_prompt(events):
    """Use actual successful connector bytes, never a model's summary of policy."""
    documents = []

    def collect_text(node):
        if isinstance(node, dict):
            if isinstance(node.get('textRun'), dict):
                return node['textRun'].get('content', '')
            if isinstance(node.get('text'), str) and ('startIndex' in node or 'endIndex' in node):
                return node['text'] + '\n'
            return ''.join(collect_text(v) for v in node.values())
        if isinstance(node, list):
            return ''.join(collect_text(v) for v in node)
        return ''

    for event in events:
        item = event.get('item', {})
        if event.get('type') != 'item.completed' or item.get('type') != 'mcp_tool_call':
            continue
        if item.get('status') != 'completed' or item.get('error'):
            continue
        if not any(name in item.get('tool', '') for name in ('get_document', 'fetch')):
            continue
        result = item.get('result') or {}
        if result.get('isError'):
            continue
        data = result.get('structured_content') or result.get('structuredContent') or {}
        found_id = data.get('documentId') or data.get('document_id')
        url = data.get('document_url', '')
        if found_id != PROMPT_ID and f'/document/d/{PROMPT_ID}' not in url:
            continue
        # Prefer body/paragraphs over duplicate tab representations.
        content = data.get('paragraphs') or data.get('body') or data.get('tabs') or data
        value = collect_text(content)
        if len(value) > 1000 and 'FIRST PASS' in value and 'RESCUE' in value and 'PASS' in value:
            documents.append(value)
    if not documents:
        raise Blocked('Live AI Prompt was not returned by Google Drive. No review may start.')
    return documents[-1]


def read_events(path):
    events = []
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass  # A killed process may leave a partial final line.
    return events


def session_id(events):
    ids = {e.get('thread_id') for e in events if e.get('type') == 'thread.started'}
    ids.discard(None)
    if len(ids) != 1:
        raise Blocked('No unique Codex session receipt; inspect the log before restarting.')
    return ids.pop()


def verify_completion(result, ownership, proof, workflow_id, started_at):
    if result.get('state') not in DRAINED:
        raise Blocked('The AI task reports incomplete work: ' + result.get('summary', 'see task logs'))
    run_id = result.get('run_id')
    if not run_id or ownership != {'workflow_id': workflow_id, 'run_id': run_id}:
        raise Blocked("The AI result does not match this workflow's saved run ownership.")
    run = proof.get('run', {})
    checkpoint = proof.get('checkpoint', {})
    counts = checkpoint.get('passes', {}).get('1', {})
    if (run.get('run_id') != run_id or run.get('stage') != 1 or run.get('state') != 'drained'
            or proof.get('started_at', 0) < started_at
            or checkpoint.get('run_id') != run_id
            or checkpoint.get('run', {}).get('state') != 'drained'):
        raise Blocked("Managed runtime does not verify completion of this AI task's run.")
    if any(counts.get(k) != 0 for k in ('ready', 'claimed', 'pending_writeback', 'pending_publication')):
        raise Blocked('The managed finish checkpoint still has unfinished review or delivery work.')
    if counts.get('upstream_active') != []:
        raise Blocked('The managed finish checkpoint has unverified upstream work.')
    exceptions = counts.get('conflicts', 0) or counts.get('deferred', 0) or counts.get('publication', {}).get('Conflict', 0)
    if exceptions and result['state'] != 'DRAINED_WITH_EXCEPTIONS':
        raise Blocked('The AI result omitted exceptions recorded by the managed reviewer.')
    return result['state']


def publication_ready(status):
    return (status.get('configured_backend') == 'sqlite' and status.get('ready') is True
            and status.get('pending_cells') == 0 and status.get('pending_rows') == 0
            and not status.get('last_error'))


class Controller:
    def __init__(self, args):
        self.args = args
        self.project = Path(args.project).expanduser().resolve()
        self.python = self.project / '.venv/bin/python'
        self.codex = shutil.which(args.codex)
        if not self.codex or not self.python.is_file():
            raise Blocked('Codex or the scraper Python environment is unavailable.')
        self.env = {**os.environ, 'PYTHONPATH': str(self.project / 'src'), 'PYTHONUNBUFFERED': '1'}
        self.state = None
        self.work = None
        self.sequence = 0
        self.controller_lock = None
        self.heartbeat_at = time.monotonic()

    def announce(self, text):
        print(f'[{now()}] {text}', flush=True)

    def save(self, **changes):
        self.state.update(changes, updated_at=now())
        atomic(self.work / 'workflow.json', self.state)

    def command(self, argv, name, *, input_text=None, timeout=1800, heartbeat=False,
                check=True, fixed_output=None):
        self.sequence += 1
        stamp = f'{time.time_ns()}-{self.sequence}-{name}'
        out = fixed_output or self.work / (stamp + '.stdout')
        err = self.work / (stamp + '.stderr')
        self.announce(f'{name}; log: {out.name}')
        started = time.monotonic()
        next_progress = started + 60
        stdin_file = None
        if input_text is not None:
            input_path = self.work / (stamp + '.input.txt')
            input_path.write_text(input_text, encoding='utf-8')
            stdin_file = input_path.open('r', encoding='utf-8')
        try:
            with out.open('w', encoding='utf-8') as stdout, err.open('w', encoding='utf-8') as stderr:
                process = subprocess.Popen(argv, cwd=self.project, env=self.env,
                    stdin=stdin_file or subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                    start_new_session=True,
                    pass_fds=(() if self.controller_lock is None else (self.controller_lock.fileno(),)))
                try:
                    while process.poll() is None:
                        elapsed = time.monotonic() - started
                        if elapsed > timeout:
                            raise Blocked(f'{name} exceeded its timeout. See {out} and {err}.')
                        if time.monotonic() >= next_progress:
                            self.announce(f'{name} still running ({int(elapsed)} seconds); logs are updating.')
                            next_progress = time.monotonic() + 60
                        if heartbeat and time.monotonic() - self.heartbeat_at > 240:
                            self.review_command('heartbeat')
                            self.heartbeat_at = time.monotonic()
                        time.sleep(0.5)
                except BaseException:
                    os.killpg(process.pid, signal.SIGINT)
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                    raise
        finally:
            if stdin_file:
                stdin_file.close()
        if check and process.returncode:
            raise Blocked(f'{name} exited {process.returncode}. See {out} and {err}.')
        return process.returncode, out

    def probe(self):
        # Read-only compact output: avoid dumping all historical company records.
        result = subprocess.run([str(self.python), str(HERE / 'probe.py')], cwd=self.project,
                                env=self.env, text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise Blocked('Cannot inspect installed scraper state: ' + result.stderr[-1000:])
        return json.loads(result.stdout)

    def helper(self, *args, timeout=1800):
        _, path = self.command([str(self.project / 'job-search-scraper'), *args],
                               '-'.join(args[:2]), timeout=timeout)
        return parse_json_file(path)

    def review_command(self, action, *args, fixed_output=None):
        argv = [str(self.project / 'job-search-reviewer'), action, '--pass', '1']
        if self.state.get('review_run_id'):
            argv += ['--run-id', self.state['review_run_id']]
        elif action != 'start':
            raise Blocked('Missing this controller\'s managed review run ID.')
        _, path = self.command([*argv, *args], 'review-' + action, fixed_output=fixed_output)
        result = parse_json_file(path)
        if action == 'status':
            if result.get('run', {}).get('run_id') != self.state.get('review_run_id'):
                raise Blocked('Status receipt does not identify this managed run.')
            return result
        if result.get('pass') != 1 or not result.get('run_id'):
            raise Blocked('Managed reviewer returned no FIRST PASS identity receipt.')
        if self.state.get('review_run_id') and result['run_id'] != self.state['review_run_id']:
            raise Blocked('Managed reviewer returned a different run ID; preserve its receipt.')
        return result

    def codex_command(self, prompt, name, *, schema=None, connectors=False, heartbeat=False):
        argv = [self.codex, 'exec', '--sandbox', 'read-only', '--skip-git-repo-check',
                '--ephemeral', '-m', MODEL, '-c', f'model_reasoning_effort="{EFFORT}"', '--json']
        if not connectors:
            argv += ['--ignore-user-config']
        response = self.work / (uuid.uuid4().hex + '-model-response.json')
        argv += ['-o', str(response)]
        if schema is not None:
            schema_path = self.work / (uuid.uuid4().hex + '-schema.json')
            atomic(schema_path, schema)
            argv += ['--output-schema', str(schema_path)]
        _, log = self.command([*argv, '-'], name, input_text=prompt, timeout=1200, heartbeat=heartbeat)
        events = []
        for line in log.read_text(encoding='utf-8').splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        if not any(e.get('type') == 'turn.completed' for e in events):
            raise Blocked(f'Codex did not complete normally; inspect {log}.')
        return response, events

    def fetch_prompt(self):
        _, events = self.codex_command(
            'Read-only policy fetch. Use the connected Google Drive get_document or get_document_text '
            f'tool to read the entire native Google Doc {PROMPT_ID}, titled AI Prompt. '
            'Do not start reviews, inspect jobs, or change anything. Do not use shell or browser. '
            'If the connector is unavailable, report BLOCKED. After a successful read say PROMPT_READ_OK.',
            'read-live-ai-prompt', connectors=True)
        text = extract_prompt(events)
        digest = hashlib.sha256(text.encode()).hexdigest()
        (self.work / f'ai-prompt-{digest}.txt').write_text(text, encoding='utf-8')
        return text, digest

    def preflight(self):
        self.command([self.codex, 'login', 'status'], 'codex-login', timeout=60)
        info = self.probe()
        if info['backend'] != 'sqlite':
            raise Blocked('This controller requires the existing SQLite storage backend.')
        self.helper('preflight')
        self.command([str(self.python), str(HERE / 'probe.py'), 'remote-preflight'],
                     'google-sheets-preflight', timeout=180)
        self.fetch_prompt()
        response, _ = self.codex_command('Do not use tools or read files. Reply exactly MODEL_CHECK_OK.', 'model-check')
        if response.read_text(encoding='utf-8').strip() != 'MODEL_CHECK_OK':
            raise Blocked('The requested model did not acknowledge the availability check.')
        storage = self.helper('storage', 'status')
        result = {'model': MODEL, 'reasoning_effort': EFFORT, 'scraper_busy': info['scraper_busy'],
                  'pending_cells': storage['pending_cells'], 'conflicts': storage['conflicts'],
                  'handoff_ready_now': publication_ready(storage)}
        atomic(self.work / 'preflight.json', result)
        self.announce(json.dumps(result))
        return info

    def select_cycle(self, info):
        expected = self.state.get('cycle_id')
        if expected:
            matches = [c for c in info['cycles'] if c['id'] == expected]
        else:
            before = set(self.state['before_cycles'])
            matches = [c for c in info['cycles'] if c['id'] not in before]
        if len(matches) != 1:
            raise Blocked('Cannot identify exactly one controller-owned scrape cycle; no review started.')
        if info['cycles'][-1]['id'] != matches[0]['id']:
            raise Blocked('A newer scrape exists. Preserve this workflow and reconcile before resuming.')
        return matches[0]

    def scrape(self):
        info = self.probe()
        if info['scraper_busy']:
            raise Blocked('A scraper is already running. No duplicate scraper was launched.')
        resume = self.state['stage'] == 'SCRAPING'
        if not resume and any(c['id'] not in self.state['before_cycles'] for c in info.get('cycles', [])):
            raise Blocked('Another scrape was created after preflight. No additional scan was started.')
        if resume:
            new = [c for c in info['cycles'] if c['id'] not in self.state['before_cycles']]
            if new:
                current = self.select_cycle(info)
                self.save(cycle_id=current['id'])
                if current['status'] in FINISHED:
                    self.save(stage='PUBLISHING', scrape_status=current['status'])
                    return
            else:
                resume = False  # Earlier attempt failed before creating any cycle.
        self.save(stage='SCRAPING')
        argv = [str(self.project / 'job-search-scraper'), 'start', '--fetch-workers', str(self.args.fetch_workers)]
        if resume:
            argv.append('--resume')
        rc, _ = self.command(argv, 'scrape', timeout=self.args.scrape_timeout, check=False)
        info = self.probe()
        current = self.select_cycle(info)
        self.save(cycle_id=current['id'], scrape_exit_code=rc, scrape_status=current['status'])
        if rc or current['status'] not in FINISHED or info['scraper_busy']:
            raise Blocked('Scrape did not finish successfully. Resume this workflow; FIRST PASS was not started.')
        self.save(stage='PUBLISHING')

    def publish_gate(self):
        info = self.probe()
        current = self.select_cycle(info)
        if info['scraper_busy'] or current['status'] not in FINISHED:
            raise Blocked('Scrape completion gate failed.')
        for attempt in range(3):
            status = self.helper('storage', 'status')
            if publication_ready(status):
                self.save(stage='REVIEWING', scrape_publication=status)
                return
            self.announce(f'Publication pending: {status.get("pending_cells")} cells, {status.get("conflicts")} conflicts.')
            if attempt == 2:
                break
            self.helper('storage', 'once', '--max-batches', '100', '--interval', '60')
            time.sleep(10)
        raise Blocked('Scrape uploads are pending or unhealthy. Conflicts were preserved; review has not started.')

    def handoff_prompt(self):
        ownership = self.work / 'review-owner.json'
        return (
            'Read "AI Prompt" in my Google Drive and do a FIRST PASS, following its current instructions. '
            f'The document is https://docs.google.com/document/d/{PROMPT_ID}/edit. '
            'Use the connected Google Drive get_document or get_document_text tool to read the full '
            'current document immediately before starting or resuming review. '
            'Use GPT-5.6 Luna with medium reasoning. FIRST PASS only. '
            f'The scraper has completed and its publication gate passed. Work in {self.project}. '
            'You manage the review yourself using the installed managed reviewer and the live AI Prompt. '
            'Python does not supply batches or make decisions. Do not modify source code, settings, '
            'the AI Prompt, other passes, or the title blacklist. Do not use other agents. '
            f'Your workflow ID is {self.state["workflow_id"]}. '
            f'Persist your managed run ownership in {ownership} as exactly '
            '{"workflow_id": "' + self.state['workflow_id'] + '", "run_id": "YOUR_ACTUAL_MANAGED_RUN_ID"}. '
            'If that file exists, validate its workflow ID and resume that same managed run. '
            'If it does not exist, recover any run you already started in this Codex conversation; '
            'only when none exists start a new FIRST PASS run and save its actual ID immediately '
            "before claiming work. Never borrow another task's run or create a replacement for uncertain work. "
            'Keep assessments and receipts in this workflow directory. Follow the live document for '
            'claims, assessment, submission, heartbeat, delivery, and completion. '
            'Continue through the entire eligible first-pass queue. If blocked, pause your own managed run '
            'when safe and report the blocker. Return your actual run_id (empty if never started), state '
            '(DRAINED, DRAINED_WITH_EXCEPTIONS, PAUSED_NOT_COMPLETE, or BLOCKED_NOT_COMPLETE), '
            'and a concise summary with outcomes, delivery and exceptions. '
            'Claim completion only after the managed live finish returns a drained state.'
        )

    def agent_argv(self, response, schema, session=None):
        argv = [self.codex, 'exec', '--sandbox', 'workspace-write',
                '-c', 'sandbox_workspace_write.network_access=true',
                '-c', 'approval_policy="never"']
        if session:
            argv += ['resume']
        argv += ['-m', MODEL, '-c', f'model_reasoning_effort="{EFFORT}"',
                 '--skip-git-repo-check', '--json', '--output-schema', str(schema),
                 '-o', str(response)]
        if session:
            argv += [session]
        return [*argv, '-']

    def recover_agent(self):
        if self.state.get('agent_log'):
            events = read_events(Path(self.state['agent_log']))
            self.save(codex_session_id=session_id(events))
        ownership_path = self.work / 'review-owner.json'
        if ownership_path.exists():
            owner = json.loads(ownership_path.read_text())
            if owner.get('workflow_id') != self.state['workflow_id'] or not owner.get('run_id'):
                raise Blocked('Invalid review ownership receipt; preserve it for inspection.')
            self.save(review_run_id=owner['run_id'])

    def review(self):
        if self.state.get('agent_log'):
            self.recover_agent()
        response = self.work / (uuid.uuid4().hex + '-ai-result.json')
        log = self.work / (uuid.uuid4().hex + '-ai-task.jsonl')
        schema = self.work / 'ai-result-schema.json'
        atomic(schema, {'type': 'object', 'additionalProperties': False,
                        'properties': {'run_id': {'type': 'string'},
                                       'state': {'type': 'string', 'enum': sorted(DRAINED | {'PAUSED_NOT_COMPLETE', 'BLOCKED_NOT_COMPLETE'})},
                                       'summary': {'type': 'string'}},
                        'required': ['run_id', 'state', 'summary']})
        self.save(agent_started_at=self.state.get('agent_started_at', time.time()),
                  agent_log=str(log), agent_result=str(response), handoff_version=2)
        self.announce('Launching AI task: Read AI Prompt in Google Drive and do FIRST PASS.')
        argv = self.agent_argv(response, schema, self.state.get('codex_session_id'))
        try:
            self.command(argv, 'codex-first-pass', input_text=self.handoff_prompt(),
                         timeout=self.args.review_timeout, fixed_output=log)
        finally:
            # The durable session and ownership receipt allow the same task to resume.
            self.recover_agent()
        events = read_events(log)
        if not any(e.get('type') == 'turn.completed' for e in events):
            raise Blocked('The Codex task did not complete normally; resume its saved session.')
        extract_prompt(events)  # Require a real live Doc read in this start/resume.
        result = json.loads(response.read_text())
        self.save(ai_summary=result.get('summary'), ai_result=result)
        if result.get('state') not in DRAINED:
            raise Blocked('AI task remains incomplete: ' + result.get('summary', 'see logs'))
        owner = json.loads((self.work / 'review-owner.json').read_text())
        _, proof_path = self.command([str(self.python), str(HERE / 'probe.py'),
                                     'review-proof', owner['run_id']], 'verify-ai-finish')
        proof = parse_json_file(proof_path)
        status = verify_completion(result, owner, proof, self.state['workflow_id'], self.state['agent_started_at'])
        self.save(status=status, stage='COMPLETE', completed_at=now(), last_finish=proof,
                  ai_summary=result['summary'])
        self.announce(f'FIRST PASS {status}: {result["summary"]}')

    def run(self):
        info = self.probe()
        root = Path(info['state_dir']) / 'scrape-first-pass'
        latest = root / 'latest.json'
        if self.args.command == 'status':
            state = None
            if latest.exists():
                state = json.loads(Path(json.loads(latest.read_text())['workflow']).read_text())
            print(json.dumps({'workflow': state, 'scraper_busy': info['scraper_busy'],
                              'latest_cycle': info['cycles'][-1] if info['cycles'] else None}, indent=2))
            return 0
        with exclusive(root / 'controller.lock') as lock:
            self.controller_lock = lock
            if self.args.command == 'check':
                self.work = root / ('check-' + uuid.uuid4().hex)
                self.work.mkdir(mode=0o700)
                self.preflight()
                return 0
            previous = None
            if latest.exists():
                previous_path = Path(json.loads(latest.read_text())['workflow'])
                previous = json.loads(previous_path.read_text())
            if self.args.resume:
                if not previous:
                    raise Blocked('No pipeline workflow exists to resume.')
                if previous['stage'] == 'COMPLETE':
                    self.announce('This workflow already completed; no duplicate review was launched.')
                    return 0
                self.state, self.work = previous, previous_path.parent
            else:
                if previous and previous['stage'] != 'COMPLETE':
                    raise Blocked('An unfinished workflow exists. Use run --resume.')
                if info['scraper_busy']:
                    raise Blocked('A scraper is already active; no duplicate run was started.')
                self.work = root / ('run-' + uuid.uuid4().hex)
                self.work.mkdir(mode=0o700)
                self.state = {'workflow_id': self.work.name, 'created_at': now(), 'stage': 'PREFLIGHT',
                              'status': 'RUNNING', 'project': str(self.project),
                              'model': MODEL, 'reasoning_effort': EFFORT,
                              'before_cycles': [c['id'] for c in info['cycles']]}
                self.save()
                atomic(latest, {'workflow': str(self.work / 'workflow.json')})
            if self.state.get('model') != MODEL or self.state.get('reasoning_effort') != EFFORT:
                raise Blocked('Saved workflow model differs from GPT-5.6 Luna Medium.')
            try:
                self.save(status='RUNNING', error=None)
                if self.state['stage'] == 'PREFLIGHT':
                    self.preflight()
                    self.save(stage='SCRAPE_PENDING')
                if self.state['stage'] in {'SCRAPE_PENDING', 'SCRAPING'}:
                    self.scrape()
                if self.state['stage'] == 'PUBLISHING':
                    self.publish_gate()
                if self.state['stage'] == 'REVIEWING':
                    self.review()
                return 0
            except BaseException as exc:
                self.save(status='PAUSED_NOT_COMPLETE', error=f'{type(exc).__name__}: {exc}')
                if self.state.get('review_run_id'):
                    try:
                        self.review_command('pause')
                    except Exception as pause_error:
                        self.save(pause_error=str(pause_error))
                raise


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'run', 'status'))
    parser.add_argument('--project', default=str(HERE.parent))
    parser.add_argument('--codex', default='codex')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--fetch-workers', type=int, choices=range(1, 51), default=5)
    parser.add_argument('--review-timeout', type=int, default=172800)
    parser.add_argument('--scrape-timeout', type=int, default=172800)
    args = parser.parse_args(argv)
    if args.resume and args.command != 'run':
        parser.error('--resume applies only to run')
    if args.review_timeout < 1 or args.scrape_timeout < 1:
        parser.error('timeouts and wait counts must be positive')
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        return Controller(args).run()
    except KeyboardInterrupt:
        print('PAUSED_NOT_COMPLETE: interrupted; use run --resume.', file=sys.stderr)
        return 130
    except (Blocked, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'BLOCKED_NOT_COMPLETE: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
