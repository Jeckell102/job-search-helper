#!/usr/bin/env python3
"""Jetson Home: key-free home-network API and durable agent workers."""
import contextlib
import ipaddress
import fcntl
import json
import logging
import logging.handlers
import math
import os
import secrets
import signal
import socket
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,unquote,parse_qs
import storage as store
import cluster
from inference_control_store import InferenceControlStore
import jobs
import benchlog
from engine import Engine,BackendError,InputError,Cancelled
from routing import route
from assistant_tools import SCHEMAS, request_scope, schemas_for
import local_tools
import re
from profile_policy import PROFILES,VISIBLE_PROFILES,LEGACY_ALIASES,resolve_profile,resolve_output_limit

STOP=threading.Event(); WAKE=threading.Event(); STARTED=time.monotonic()
MODEL_ID='Instant'
VISIBLE_MODEL_IDS=tuple(VISIBLE_PROFILES)
MODEL_IDS=VISIBLE_MODEL_IDS+tuple(PROFILES)+tuple(LEGACY_ALIASES)

def worker(engine, wrapper_control=None):
    while not STOP.is_set():
        try: store.schedule_tick()
        except ValueError: pass  # A full task queue must still be allowed to drain.
        except Exception as exc: logging.error('scheduler_error type=%s',type(exc).__name__)
        # A lost wrapper transport may leave the backend executing.  This
        # ordinary local worker must not bypass that durable one-turn hold.
        if wrapper_control and wrapper_control.lane_blocked():
            WAKE.wait(3); WAKE.clear(); continue
        current=None
        try:
            current=store.claim()
            if current:
                checked=[0,False]
                def abort():
                    if STOP.is_set(): return True
                    if time.monotonic()-checked[0]>1:
                        row=store.task(current['id']); checked[:]=[time.monotonic(),not row or row['status']=='cancelled']
                    return checked[1]
                result=engine.generate(current['prompt'],current['agent'],abort)
                store.finish(current['id'],result)
                continue
        except Cancelled:
            if current and STOP.is_set(): store.failed(current['id'],'service_stopping')
        except (InputError,ValueError) as exc:
            if current: store.failed(current['id'],'input_budget_or_configuration',retryable=False)
            logging.warning('task_input_rejected id=%s',current['id'] if current else 'none')
        except BackendError as exc:
            code=str(exc)
            if current: store.failed(current['id'],code,retryable=code not in ('generation_truncated','generation_no_answer'))
            logging.warning('backend_error id=%s code=%s',current['id'] if current else 'none',code)
        except Exception as exc:
            if current:
                with contextlib.suppress(Exception): store.failed(current['id'],'internal_'+type(exc).__name__)
            logging.error('worker_error type=%s',type(exc).__name__)
        WAKE.wait(3); WAKE.clear()

def compute_worker(engine):
    while not STOP.is_set():
        current=None
        try:
            current=cluster.claim()
            if current:
                if current['kind']=='system.benchmark':
                    with engine.gate.hold(False): result=benchlog.run()
                else: result=jobs.run(current['kind'],current['payload'])
                cluster.complete('jetson',current['id'],current['lease_token'],result)
                continue
        except Exception as exc:
            logging.warning('compute_failed type=%s',type(exc).__name__)
            if current:
                error=('benchmark_deferred' if isinstance(exc,benchlog.Deferred) else 'benchmark_failed') if current['kind']=='system.benchmark' else 'document_processing_failed'
                cluster.complete('jetson',current['id'],current['lease_token'],error=error)
        STOP.wait(2)

def number(value,default,minimum,maximum):
    if value is None: return default
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not minimum<=value<=maximum:
        raise ValueError('Numeric option outside supported bounds.')
    return value

class Server(ThreadingHTTPServer):
    daemon_threads=True; block_on_close=False; allow_reuse_address=True
    def __init__(self,address,handler,engine):
        self.engine=engine; self.slots=threading.BoundedSemaphore(8)
        self.wrapper_control=InferenceControlStore(store.ROOT/'data/wrapper-inference-control.sqlite3')
        super().__init__(address,handler)
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            with contextlib.suppress(OSError): request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
            self.shutdown_request(request); return
        try: super().process_request(request,address)
        except BaseException: self.slots.release(); raise
    def process_request_thread(self,request,address):
        try: super().process_request_thread(request,address)
        finally: self.slots.release()
    def handle_error(self,request,address): logging.error('request_handler_failed')

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'; server_version='LocalAI/0.2.2'
    def setup(self):
        super().setup(); self.connection.settimeout(10)
    def log_message(self,*args): pass
    def response(self,status,payload):
        body=json.dumps(payload,ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store')
        self.send_header('Connection','close'); self.end_headers(); self.wfile.write(body); self.close_connection=True
    def worker_auth(self):
        supplied=self.headers.get('Authorization','')
        key=(store.ROOT/'config/worker-key').read_text().strip()
        if not secrets.compare_digest(supplied.encode(),('Bearer '+key).encode()):
            self.response(401,{'error':{'message':'A paired worker key is required.'}}); return False
        return True
    def wrapper_auth(self):
        key=json.loads((store.ROOT/'config/wrapper-host.json').read_text())['token']
        return secrets.compare_digest(self.headers.get('Authorization',''), 'Bearer '+key)
    def wrapper_control_binding(self):
        """Read the per-request proof without ever reflecting it in a reply."""
        return (self.headers.get('X-Wrapper-Request-Fingerprint'),
                self.headers.get('X-Wrapper-Owner-Generation'))
    def static(self,path):
        cfg=store.settings()
        if path=='/' and cfg.get('webui_port') is not None:
            port=cfg['webui_port']
            if isinstance(port,bool) or not isinstance(port,int) or not 1<=port<=65535:
                raise ValueError('webui_port must be a valid port number.')
            self.send_response(302)
            self.send_header('Location','http://'+cfg['listen_host']+':'+str(port)+'/')
            self.send_header('Content-Length','0'); self.send_header('Cache-Control','no-store')
            self.send_header('Connection','close'); self.end_headers(); self.close_connection=True
            return True
        selected={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}.get(path)
        if not selected: return False
        payload=(Path(__file__).resolve().parent/'static'/selected[0]).read_bytes()
        self.send_response(200); self.send_header('Content-Type',selected[1]+'; charset=utf-8')
        self.send_header('Content-Length',str(len(payload))); self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Connection','close'); self.end_headers(); self.wfile.write(payload); self.close_connection=True
        return True
    def body(self):
        if self.headers.get('Transfer-Encoding'): raise ValueError('Chunked request bodies are not supported.')
        size=int(self.headers.get('Content-Length','0'))
        if not 1<=size<=400000: raise ValueError('Request body must be 1..400000 bytes.')
        data=self.rfile.read(size)
        if len(data)!=size: raise ValueError('Incomplete request body.')
        def invalid(_): raise ValueError('Non-finite JSON numbers are not accepted.')
        value=json.loads(data,parse_constant=invalid)
        if not isinstance(value,dict): raise ValueError('JSON body must be an object.')
        return value
    def do_GET(self): self.dispatch('GET')
    def do_POST(self): self.dispatch('POST')
    def do_DELETE(self): self.dispatch('DELETE')
    def dispatch(self,method):
        try:
            path=urlsplit(self.path).path
            if method=='GET' and self.static(path): return
            if path=='/healthz' and method=='GET':
                self.response(200,{'status':'ok','version':store.VERSION}); return
            if path == '/api/wrapper-turn' and method == 'POST':
                if not self.wrapper_auth():
                    self.response(403, {'error':'Unauthorized'}); return
                from wrapper_inference import infer
                self.response(200, infer(self.server.engine, self.body(), self.server.wrapper_control)); return
            if path.startswith('/api/wrapper-control/'):
                if not self.wrapper_auth():
                    self.response(403, {'error':'Unauthorized'}); return
                request_id=path.rsplit('/',1)[-1]
                if method=='GET':
                    fingerprint, owner_generation=self.wrapper_control_binding()
                    value=self.server.wrapper_control.owned_status(request_id, fingerprint, owner_generation)
                    self.response(200 if value else 404, value or {'error':'Unknown inference request.'}); return
                if method=='DELETE':
                    data=self.body()
                    value=self.server.wrapper_control.cancel(request_id, data.get('request_fingerprint'), data.get('owner_generation'))
                    if value:
                        value=self.server.wrapper_control.owned_status(request_id, data.get('request_fingerprint'), data.get('owner_generation'))
                    self.response(200 if value else 404, value or {'error':'Unknown inference request.'}); return
                self.response(405, {'error':'Wrapper control requires GET or DELETE.'}); return
            if path.startswith('/api/worker/'):
                if method!='POST': self.response(405,{'error':'Worker endpoints require POST.'}); return
                if not self.worker_auth(): return
                data=self.body(); action=path.rsplit('/',1)[-1]
                if action=='heartbeat': result=cluster.heartbeat(data)
                elif action=='claim': result={'task':cluster.claim(data.get('id'))} if data.get('id') else {'task':None}
                elif action=='renew': result={'renewed':cluster.renew(data.get('id'),data.get('task_id'),data.get('lease_token'))}
                elif action=='complete': result={'accepted':cluster.complete(data.get('id'),data.get('task_id'),data.get('lease_token'),data.get('result'),data.get('error'))}
                else: self.response(404,{'error':'Unknown worker endpoint.'}); return
                self.response(200,result); return
            # Home-network access deliberately needs no sign-in or API key.
            # Existing clients may still send their old Authorization header.
            if method=='GET' and path=='/v1/models':
                self.response(200,{'object':'list','data':[{'id':mid,'name':mid,'object':'model','created':int(time.time()),'owned_by':'jetson'} for mid in VISIBLE_MODEL_IDS]}); return
            if method=='GET' and path=='/api/status':
                backend='unavailable'
                try:
                    with urllib.request.urlopen(store.settings()['ollama_url']+'/api/version',timeout=3) as r:
                        backend=json.load(r).get('version','reachable')
                except Exception: pass
                with store.db() as c:
                    counts={r[0]:r[1] for r in c.execute('SELECT status,count(*) FROM tasks GROUP BY status')}
                    integrity=c.execute('PRAGMA quick_check').fetchone()[0]
                rss=None
                with open('/proc/self/status') as handle:
                    for line in handle:
                        if line.startswith('VmRSS:'): rss=int(line.split()[1])*1024
                self.response(200,{'version':store.VERSION,'host':socket.gethostname(),'role':'jetson-core','backend':backend,'model':store.settings()['model'],
                                   'model_busy':self.server.engine.gate.busy,'foreground_waiting':self.server.engine.gate.foreground_waiting,
                                   'tasks':counts,'integrity':integrity,'uptime_seconds':round(time.monotonic()-STARTED,1),
                                   'rss_bytes':rss,'ordinary_chat_stored':False,'external_action_tools_enabled':True,
                                   'network_tools':{'names':['network_probe','http_get','ssh_status'],'profiles':list(VISIBLE_PROFILES),'scope':'user-named home-LAN IPv4 devices','mode':'read-only'},
                                   'assistant_tools':{'names':[s['function']['name'] for s in SCHEMAS],'profiles':list(VISIBLE_PROFILES)},'workers':cluster.workers(),'core_requires_mulelab':False}); return
            if method=='GET' and path=='/api/notifications':
                after=int(parse_qs(urlsplit(self.path).query).get('after',['0'])[0])
                self.response(200,local_tools.notifications(after)); return
            if method=='GET' and path.startswith('/api/artifacts/'):
                name=path.rsplit('/',1)[-1]
                if not re.fullmatch(r'[a-f0-9]{32}\.(md|txt|csv)',name): raise ValueError('Invalid artifact name.')
                selected=local_tools.resolve_file('workspace/reports/'+name)
                payload=selected.read_bytes()
                if len(payload)>30000: raise ValueError('Artifact exceeds download bound.')
                self.send_response(200); self.send_header('Content-Type','text/plain; charset=utf-8')
                self.send_header('Content-Disposition','attachment; filename="'+name+'"')
                self.send_header('Content-Length',str(len(payload))); self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(payload); return
            if method=='GET' and path=='/api/workers': self.response(200,cluster.workers()); return
            if method=='POST' and path=='/api/compute':
                data=self.body(); tid=cluster.enqueue(data.get('kind'),data.get('payload'),data.get('label'))
                self.response(202,{'id':tid,'status':'queued'}); return
            if method=='GET' and path=='/api/changes': self.response(200,benchlog.changes()); return
            if method=='POST' and path=='/api/changes': self.response(201,{'id':benchlog.note(self.body().get('note'))}); return
            if method=='GET' and path=='/api/benchmarks': self.response(200,benchlog.history()); return
            if method=='POST' and path=='/api/benchmark-run': self.response(202,{'id':cluster.enqueue('system.benchmark',{})}); return
            if method=='GET' and path=='/api/agents': self.response(200,store.agents()); return
            if method=='GET' and path=='/api/tasks': self.response(200,store.task_list()); return
            if path.startswith('/api/tasks/'):
                tid=unquote(path[len('/api/tasks/'):])
                if method=='GET':
                    row=store.task(tid); self.response(200 if row else 404,row or {'error':'Task not found.'}); return
                if method=='DELETE': self.response(200,{'cancelled':store.cancel(tid)}); return
            if method=='POST' and path=='/api/tasks':
                data=self.body(); tid=store.enqueue(data.get('prompt'),data.get('agent','assistant'))
                WAKE.set(); self.response(202,{'id':tid,'status':'queued'}); return
            if method=='GET' and path=='/api/schedules': self.response(200,store.schedule_list()); return
            if method=='POST' and path=='/api/schedules':
                data=self.body(); interval=data.get('interval_seconds'); when=data.get('run_at')
                if interval is not None: interval=int(number(interval,None,60,31536000))
                if when is not None: when=number(when,None,time.time()+1,time.time()+315360000)
                sid=store.schedule(data.get('prompt'),data.get('agent','assistant'),interval,when,data.get('name'))
                WAKE.set(); self.response(201,{'id':sid}); return
            if method=='DELETE' and path.startswith('/api/schedules/'):
                self.response(200,{'disabled':store.schedule_disable(unquote(path[len('/api/schedules/'):]))}); return
            if method=='GET' and path=='/api/memory': self.response(200,store.recall(parse_qs(urlsplit(self.path).query).get('q',[''])[0])); return
            if method=='POST' and path=='/api/memory':
                data=self.body(); store.remember(data.get('key'),data.get('value')); self.response(201,{'saved':True}); return
            if method=='DELETE' and path.startswith('/api/memory/'):
                self.response(200,{'hidden':store.forget(unquote(path[len('/api/memory/'):]))}); return
            if method=='POST' and path=='/v1/chat/completions': self.chat(self.body()); return
            self.response(404,{'error':{'message':'Endpoint not found.','type':'not_found'}})
        except (BrokenPipeError,ConnectionResetError): pass
        except (ValueError,TypeError,KeyError) as exc:
            self.response(400,{'error':{'message':str(exc),'type':'invalid_request_error'}})
        except BackendError as exc:
            self.response(503,{'error':{'message':str(exc),'type':'backend_unavailable'}})
        except Cancelled:
            self.response(503,{'error':{'message':'Service is stopping.','type':'service_unavailable'}})
        except Exception as exc:
            logging.error('api_error type=%s',type(exc).__name__)
            self.response(500,{'error':{'message':'Internal service error. Check local service health.','type':'server_error'}})
    def chat(self,data):
        model_id=data.get('model',MODEL_ID)
        if model_id not in MODEL_IDS: raise ValueError('Unknown local AI model profile.')
        profile=resolve_profile(model_id)
        stream=data.get('stream',False)
        if not isinstance(stream,bool): raise ValueError('stream must be boolean.')
        if data.get('stream_options') is not None and not isinstance(data['stream_options'],dict): raise ValueError('stream_options must be an object.')
        messages=data.get('messages')
        if not isinstance(messages,list) or not messages: raise ValueError('messages must be a nonempty array.')
        if not isinstance(messages[-1],dict) or messages[-1].get('role')!='user' or not isinstance(messages[-1].get('content'),str):
            raise ValueError('The last message must be a text user message.')
        # Only the current explicit user command can create state; never an earlier turn or model output.
        if profile.model_id == 'qwen-wrapper:4b' and messages[-1]['content'].strip().lower().startswith('/wrapper'):
            from wrapper_commands import command
            direct=command(messages[-1]['content'])
        else:
            direct=route(messages[-1]['content'])
        if profile.model_id == 'qwen-wrapper:4b' and messages[-1]['content'].strip().lower() == '/tools':
            direct=('For automatic continuation use /wrapper help. /wrapper start <objective including tests/test_company.py> runs a persistent MuleLab task with sequential Jetson workers. '
                    'Wrapper Coder: source search/read, guarded edits, new files, offline tests, diffs, and explicitly requested local commits. '
                    'Use src/, tests/, and docs/ paths in Job Search Helper dev/wrapper-coder/repo on the scraper computer. Files, tests and temporary work stay there; the Jetson only runs the AI. The scraper computer must be online. Public web search, raw page read, and bounded JavaScript-rendered page read are available when requested. '
                    'Tests run offline with filesystem, network, memory, process and time limits. No production installation, Sheets writes or GitHub push. '
                    'Example: Read the Bosch Rexroth wrapper and run tests/test_bosch_rexroth.py. Context: 12,288 tokens; work on one small change at a time.')
        if direct is not None:
            WAKE.set(); chunks=iter([{'text':direct},{'done':True,'input_tokens':0,'output_tokens':0}])
        else:
            # Some frontends attach tool/function definitions to every ordinary chat.
            # Frontend tools are not executable here. A fixed built-in registry
            # is offered directly to Ollama; tool results originate on this host.
            # User-supplied tool-role messages remain rejected.
            raw_limit=data.get('max_tokens',data.get('max_completion_tokens'))
            if raw_limit is not None:
                raw_limit=number(raw_limit,None,1,profile.max_output_tokens)
                if not float(raw_limit).is_integer(): raise ValueError('max_tokens must be integral.')
                raw_limit=int(raw_limit)
            temp=number(data.get('temperature'),profile.temperature,0,2)
            override=data.get('think')
            if override is not None and not isinstance(override,bool): raise ValueError('think must be boolean.')
            prepared=self.server.engine.messages(
                messages,max_tokens=1,profile_id=profile.model_id,think_override=override
            )
            limit=resolve_output_limit(
                prepared,profile,raw_limit,thinking_override=override,
                tools=(__import__("coding_tools").schemas_for(prepared) if profile.model_id == "qwen-wrapper:4b" else schemas_for(prepared)) or None
            )
            chunks=self.server.engine.stream(prepared,max_tokens=limit,temperature=temp,profile_id=profile.model_id,think_override=override,network_enabled=True)
        cid='chatcmpl-'+str(uuid.uuid4()); created=int(time.time())
        base={'id':cid,'object':'chat.completion.chunk','created':created,'model':model_id}
        usage={}; parts=[]
        if not stream:
            for chunk in chunks:
                if chunk.get('text'): parts.append(chunk['text'])
                if chunk.get('done'): usage=chunk
            if not usage.get('done'):
                raise BackendError('backend_stream_incomplete')
            self.response(200,{'id':cid,'object':'chat.completion','created':created,'model':model_id,
                               'choices':[{'index':0,'message':{'role':'assistant','content':''.join(parts)},'finish_reason':usage.get('finish_reason','stop')}],
                               'usage':self.usage(usage), 'network_tool_results':[r for r in usage.get('network_tool_results',[]) if r['name'] in ('network_probe','http_get','ssh_status')], 'tool_results':usage.get('network_tool_results',[]),
                               'tool_context_checks':usage.get('context_checks',[])}); return
        # Detect upstream/queue errors before committing the HTTP 200 SSE response.
        first=next(chunks)
        self.send_response(200); self.send_header('Content-Type','text/event-stream')
        self.send_header('Cache-Control','no-cache'); self.send_header('Connection','close'); self.end_headers()
        self.close_connection=True
        def send(delta,finish=None):
            self.wfile.write(('data: '+json.dumps({**base,'choices':[{'index':0,'delta':delta,'finish_reason':finish}]})+'\n\n').encode()); self.wfile.flush()
        try:
            send({'role':'assistant'})
            import itertools
            for chunk in itertools.chain([first],chunks):
                if chunk.get('text'): send({'content':chunk['text']})
                if chunk.get('done'): usage=chunk
            if not usage.get('done'):
                raise BackendError('backend_stream_incomplete')
            send({},usage.get('finish_reason','stop'))
            if (data.get('stream_options') or {}).get('include_usage'):
                self.wfile.write(('data: '+json.dumps({**base,'choices':[],'usage':self.usage(usage)})+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError): pass
        except Exception as exc:
            code=str(exc) if isinstance(exc,BackendError) else type(exc).__name__
            with contextlib.suppress(OSError):
                self.wfile.write(('data: '+json.dumps({'error':{'message':code,'type':'stream_error'}})+'\n\ndata: [DONE]\n\n').encode()); self.wfile.flush()
        finally:
            if hasattr(chunks,'close'): chunks.close()
    @staticmethod
    def usage(data):
        a=data.get('input_tokens') or 0; b=data.get('output_tokens') or 0
        return {'prompt_tokens':a,'completion_tokens':b,'total_tokens':a+b}

def main():
    store.initialize(); cfg=store.settings()
    if cfg.get('role','core')!='core': raise SystemExit('This node is an optional worker, not the core server.')
    address=ipaddress.ip_address(cfg['listen_host'])
    if not address.is_private or address.is_unspecified: raise SystemExit('Bind to a specific private or loopback address, never a public/wildcard address.')
    lock_handle=open(store.ROOT/'data/service.lock','a')
    try: fcntl.flock(lock_handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: raise SystemExit('An orchestrator already owns this data directory.')
    handler=logging.handlers.RotatingFileHandler(store.ROOT/'logs/orchestrator.log',maxBytes=cfg['log_max_bytes'],backupCount=cfg['log_backup_count'])
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',handlers=[handler])
    store.recover(); engine=Engine(STOP)
    server=Server((cfg['listen_host'],cfg['listen_port']),Handler,engine)
    thread=threading.Thread(target=worker,args=(engine,server.wrapper_control),name='agent-worker',daemon=True); thread.start()
    compute=threading.Thread(target=compute_worker,args=(engine,),name='compute-worker',daemon=True); compute.start()
    def stop(*_):
        STOP.set(); WAKE.set(); threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
    logging.info('started version=%s host=%s port=%s',store.VERSION,cfg['listen_host'],cfg['listen_port'])
    try: server.serve_forever(poll_interval=.5)
    finally:
        STOP.set(); WAKE.set(); server.server_close(); thread.join(timeout=3); compute.join(timeout=3)
        with contextlib.suppress(Exception):
            with store.db() as c: store.event(c,'service_stopping')
        lock_handle.close()

if __name__=='__main__': main()
