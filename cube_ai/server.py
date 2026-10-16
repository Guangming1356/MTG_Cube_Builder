import json
import mimetypes
import re
import threading
import uuid
import os
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .catalog import Catalog
from .config import BuildSpec, ROOT, RUNS, WORKSPACE, LIBRARY, THEME_NAMES
from .engine import audit, build, export_run
from .draft import stress_test
from .forge import MATCHES, simulate as forge_simulate, status as forge_status
from .optimize import OPTIMIZATIONS, optimize
from .feedback import FeedbackStore
from .features import VERSION
from .knowledge import Knowledge
from .llm import LLMClient, advise, plan, replacements
from .ai_settings import SettingsStore,PROVIDERS
from .chatgpt_auth import ChatGPTAuth
from .design import public_guide
from .brackets import public_profiles
from .launcher import APP_ID, WORKSPACE_ID
from .experiment import PROFILES, execution_resources, experiment_budget
from . import acceleration,sim_cache,surrogate,tuning
from .task_process import TaskProcess,ACTIVE

def example_label(name):
    if name=='reference_commandercube':return 'CubeCobra 指挥官参考牌表（仅供学习）'
    match=re.search(r'_v(\d+)',name)
    if match:return f'原有第 {match[1]} 套 Commander Cube'+('（技能评估修订版）' if name.endswith('_reviewed') else '（原版）')
    return '原有 Commander Cube · '+name.replace('commander_cube_600','基础版')

def library(app):
    saved=[]
    for folder in sorted(RUNS.glob('*'),reverse=True):
        try:
            result=json.loads((folder/'cube.json').read_text(encoding='utf-8'))
            # Keep generated verification fixtures out of the beginner's library.
            if 'bracket_validation' in result:continue
            assessment=result.get('assessment',{})
            if isinstance(assessment,str):assessment={'status':assessment}
            status=assessment.get('status') or result.get('provenance',{}).get('validation_status') or 'saved'
            if not isinstance(status,str):status='saved'
            name=result['spec']['name']
            try:stamp=datetime.strptime(folder.name[:15],'%Y%m%d_%H%M%S').replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime('%Y年%m月%d日 %H:%M:%S')
            except ValueError:stamp=folder.name[:15]
            saved.append(dict(id=folder.name,name=name,label=f'{name} · {stamp}',
                count=len(result['cards']),status=status,hard_errors=result.get('audit',{}).get('hard_errors'),
                superseded_by=result.get('provenance',{}).get('superseded_assessment_by')))
        except (OSError,ValueError,KeyError,TypeError):continue
        if len(saved)>=60:break
    return dict(saved=saved,examples=[dict(id=n,label=example_label(n)) for n in sorted(app.examples)])

def execute_operation(app,operation,spec,rows,data,progress):
    client=LLMClient(app.ai_store,app.auth) if operation in {"chat","plan"} else None
    if operation in {"build","repair"}:
        value=export_run(app.catalog,build(app.catalog,spec,rows if operation=="repair" else None,progress,app.feedback));value=app.present(value)
    elif operation=="stress":
        value=stress_test(app.catalog,rows,spec,int(data.get("trials",100)),progress)
        run_id=data.get("run_id")
        if run_id and re.fullmatch(r"[A-Za-z0-9_]+",run_id) and (RUNS/run_id).is_dir():
            (RUNS/run_id/"stress.json").write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    elif operation=='calibrate':
        options=dict(mode=data.get('mode','quick'))
        if 'goal' in data:options['goal']=data['goal']
        value=tuning.calibrate(app.catalog,rows,spec,progress,**options)
    elif operation=="forge":
        value=forge_simulate(app.catalog,rows,spec,data.get('pods',10),data.get('games_per_pod',3),data.get('clock_seconds',90),progress,workers=data.get('workers',0))
    elif operation=="optimize":
        value=optimize(app.catalog,rows,spec,progress,workers=data.get('workers',0),clock=data.get('clock_seconds',120),
            profile=data.get('profile','standard'),max_swaps=data.get('max_swaps'),training_pods=data.get('training_pods'),
            scoring_backend=data.get('scoring_backend','auto'),search_mode=data.get('search_mode','full'))
        value['revision']=app.present(value['revision'])
    elif operation=='learn-games':value=surrogate.train(app.catalog,progress)
    elif operation=="chat":
        progress("AI 正在检索牌库、技能与构筑审计")
        value=advise(app.catalog,app.knowledge,spec,rows,data.get("message",""),client)
    else:
        progress("AI 将需求转换为构筑参数")
        value=plan(data.get("message",""),spec,app.knowledge,client)
    return value

DEFAULT_ISOLATED_JOBS=True

class Application:
    def __init__(self,catalog=None,ai_store=None,isolated_jobs=None):
        self.catalog=catalog or Catalog();self._knowledge=None;self._feedback=None;self._service_lock=threading.Lock()
        self.ai_store=ai_store or SettingsStore();self.auth=ChatGPTAuth(self.ai_store)
        self.jobs={};self.lock=threading.Lock();self.executor=ThreadPoolExecutor(max_workers=2);self.closing=False
        self.isolated_jobs=DEFAULT_ISOLATED_JOBS if isolated_jobs is None else isolated_jobs;self.controls={};self.job_paths={}
        self.restore_jobs()
        example_root = LIBRARY if LIBRARY.is_dir() else WORKSPACE
        self.examples={p.parent.name:p for p in example_root.glob("commander_cube_600*/cube_600.csv")}
        ref=WORKSPACE/"ref_thecommandercube.csv"
        if ref.exists():self.examples["reference_commandercube"]=ref

    @property
    def knowledge(self):
        with self._service_lock:
            if self._knowledge is None:self._knowledge=Knowledge()
            return self._knowledge

    @property
    def feedback(self):
        with self._service_lock:
            if self._feedback is None:self._feedback=FeedbackStore()
            return self._feedback

    def restore_jobs(self):
        from . import task_process
        paths=sorted(task_process.JOBS.glob('*/summary.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:30]
        for path in reversed(paths):
            try:
                job=json.loads(path.read_text(encoding='utf8'));id_=path.parent.name
                if not re.fullmatch(r'[a-f0-9]{16}',id_) or job.get('id')!=id_ or job.get('state') not in {'done','failed','cancelled'}:continue
                job.pop('result',None);job.pop('worker_pid',None)
                self.jobs[id_]=job;self.job_paths[id_]=path.parent
            except (OSError,ValueError,AttributeError):continue

    def get_job(self,id_):
        with self.lock:
            value=dict(self.jobs[id_]) if id_ in self.jobs else None
            path=self.job_paths.get(id_)
        if value and value['state']=='done' and 'result' not in value and path:
            try:
                saved=json.loads((path/'result.json').read_text(encoding='utf8'))
                value['result']=saved['result']
            except (OSError,ValueError,KeyError):raise FileNotFoundError('任务结果暂时无法读取，原有生成与实战记录仍保留') from None
        return value

    def update_job(self,id_,state):
        with self.lock:
            job=self.jobs[id_]
            if job['state'] not in ACTIVE:return
            if job['state']=='cancelling':return
            if job['state']=='pausing' and state.get('state')=='running':
                job['progress']=state['progress'];return
            if state.get('state')=='paused' and self.controls[id_].action!='pause':return
            job.update(state);job['updated_at']=time.time()

    def public_jobs(self):
        with self.lock:
            jobs=[dict({k:v for k,v in job.items() if k!='result'},controllable=id_ in self.controls) for id_,job in self.jobs.items()]
        from .legacy_tasks import discover
        return jobs+discover()

    def control(self,id_,action):
        if action not in {'pause','resume','cancel'}:raise ValueError('任务操作需为暂停、继续或结束')
        if isinstance(id_,str) and id_.startswith('legacy_'):
            from .legacy_tasks import stop
            if action!='cancel':raise ValueError('旧后台无法加入暂停功能；可结束后使用新版')
            return stop(id_)
        with self.lock:
            job=self.jobs.get(id_)
            if not job:raise ValueError('任务不存在或已过期')
            if job['state'] not in ACTIVE:return dict(job)
            runner=self.controls.get(id_)
            if not runner:raise ValueError('此任务由旧方式启动，暂不能控制')
            runner.command({'pause':'pause','resume':'run','cancel':'cancel'}[action])
            if action=='pause':job.update(state='pausing',progress='等待当前对局或计算步骤结束后暂停')
            elif action=='resume':job.update(state='running' if runner.process else 'queued',progress='正在继续')
            else:job.update(state='cancelling' if runner.process else 'cancelled',progress='正在结束任务并回收子进程' if runner.process else '已结束排队任务')
            return dict(job)

    def shutdown(self):
        for id_,runner in list(self.controls.items()):
            if self.jobs[id_]['state'] in ACTIVE:runner.command('cancel')
        self.executor.shutdown(wait=False,cancel_futures=True)

    def ai_status(self):
        try:return LLMClient(self.ai_store,self.auth).status()
        except (ValueError,TypeError,KeyError,OSError):return dict(configured=False,connected=False,provider='offline',label='AI 设置需要恢复',model='',style='chat',configuration_error='已有 AI 设置无法读取；离线功能仍可使用。可先备份并重置连接设置。')

    def rows(self,data):
        if "text" in data:
            if not isinstance(data['text'],str):raise ValueError('导入牌表必须是文本')
            rows,unknown=self.catalog.parse(data["text"])
            if (data.get("spec") or {}).get("mode")=="classic":
                for row in rows:
                    if row['role']=='Commander':row['role']='Main'
            return rows,unknown
        rows=[];unknown=[]
        entries=data.get('cards',[])
        if not isinstance(entries,list) or len(entries)>900:raise ValueError('cards 必须是最多 900 张牌的列表')
        for row in entries:
            if not isinstance(row,dict) or not isinstance(row.get('name'),str):raise ValueError('每张牌需要 name 名称和有效 role 槽位')
            n=self.catalog.resolve(row.get("name",""))
            if not n:unknown.append(row.get("name",""));continue
            role=row.get("role","Main")
            if role not in {"Main","Land","Commander"}:raise ValueError("无效牌张角色")
            rows.append(dict(name=n,role=role))
        return rows,unknown

    def present(self,result):
        result=dict(result)
        if "cards" in result:
            result["cards"]=[dict(r,mv=self.catalog.cards[r["name"]]["mv"],
                identity=self.catalog.cards[r["name"]]["identity"],quality=self.catalog.cards[r["name"]]["quality"],
                themes=self.catalog.cards[r["name"]]["enablers"],tribal=self.catalog.cards[r["name"]]["tribal"])
                for r in result["cards"]]
        return result

    def submit(self,data):
        operation=data.get("operation","build");spec=BuildSpec.from_dict(data.get("spec"))
        rows,unknown=self.rows(data)
        if unknown:raise ValueError("这些牌名未被确认: "+", ".join(unknown[:10]))
        if operation not in {"build","repair","stress","forge","optimize","chat","plan","learn-games","calibrate"}:raise ValueError("未知操作")
        if operation in {"repair","stress","forge","optimize","calibrate"} and not rows:raise ValueError("请先载入牌表")
        if operation in {'chat','plan'}:
            message=data.get('message','')
            if not isinstance(message,str) or not message.strip():raise ValueError('请先输入具体需求或问题')
            if len(message)>12000:raise ValueError('单次 AI 需求请控制在 12000 字以内')
        client=LLMClient(self.ai_store,self.auth) if operation in {'chat','plan'} else None
        if client and not client.status()['configured']:raise ValueError('AI 尚未就绪，请在“AI 设置”中连接服务并选择模型。离线功能可直接使用。')
        native_operations={'forge','optimize','calibrate'}
        if operation in native_operations:
            from .legacy_tasks import discover
            if discover():raise ValueError('旧后台仍有任务，请先在任务控制区结束旧任务，再开始实战')
        job_id=uuid.uuid4().hex[:16]
        with self.lock:
            if self.closing:raise ValueError('助手正在退出，请重新双击入口后再使用')
            if operation in native_operations and any(j['operation'] in native_operations and j['state'] in ACTIVE for j in self.jobs.values()):
                raise ValueError('已有实战或改进任务，请先继续或结束它')
            if sum(j["state"] in ACTIVE for j in self.jobs.values())>=4:raise ValueError("已有 4 个任务，请等待其中一个完成")
            self.jobs[job_id]=dict(id=job_id,operation=operation,state="queued",progress="等待运行",
                                  created_at=time.time(),updated_at=time.time(),cube_name=spec.name)
            completed=[k for k,j in self.jobs.items() if j["state"] in {"done","failed","cancelled"}]
            for k in completed[:-30]:
                del self.jobs[k]
                self.controls.pop(k,None)
                self.job_paths.pop(k,None)
        if self.isolated_jobs:
            allowed={'operation','message','trials','run_id','pods','games_per_pod','clock_seconds','workers','profile','max_swaps','training_pods','scoring_backend','search_mode','mode','goal'}
            request={k:v for k,v in data.items() if k in allowed};request.update(spec=spec.to_dict(),cards=rows)
            snapshot=None
            if operation in {'stress','forge','calibrate'}:
                snapshot=dict(snapshot=self.catalog.snapshot,signature=self.catalog.signature,
                              cards=[self.catalog.cards[name] for name in sorted({row['name'] for row in rows})])
            self.controls[job_id]=TaskProcess(job_id,request,getattr(self.ai_store,'path',None),catalog_data=snapshot)
            self.job_paths[job_id]=self.controls[job_id].folder
        def progress(message):
            with self.lock:self.jobs[job_id].update(progress=message,updated_at=time.time())
        def execute():
            with self.lock:
                if self.jobs[job_id]["state"]=="queued":self.jobs[job_id].update(state="running",started_at=time.time())
            try:
                if self.isolated_jobs:
                    value=self.controls[job_id].run(lambda state:self.update_job(job_id,state))
                    with self.lock:
                        self.jobs[job_id].update(value)
                        self.jobs[job_id]['checkpoint']=self.controls[job_id].checkpoint_summary()
                    return
                value=execute_operation(self,operation,spec,rows,data,progress)
                with self.lock:self.jobs[job_id].update(state="done",progress="完成",result=value)
            except Exception as e:
                with self.lock:self.jobs[job_id].update(state="failed",progress="任务未完成",error=str(e))
            finally:
                with self.lock:
                    if job_id in self.jobs:
                        self.jobs[job_id].update(finished_at=time.time(),updated_at=time.time())
                        if job_id in self.job_paths:
                            from .task_control import atomic_json
                            summary={k:v for k,v in self.jobs[job_id].items() if k not in {'result','worker_pid'}}
                            try:atomic_json(self.job_paths[job_id]/'summary.json',summary)
                            except OSError:pass
        self.executor.submit(execute)
        return {"job_id":job_id}

def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def local_host(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        def ai_public(self):
            status=app.ai_status()
            if status.get('configuration_error'):
                return dict(provider='offline',profiles={k:dict(v,key_present=False) for k,v in PROVIDERS.items()},accounts=[],active_account='',status=status,auth=app.auth.status())
            return dict(app.ai_store.public(),status=status,auth=app.auth.status())
        def json(self,status,data):
            raw=json.dumps(data,ensure_ascii=False).encode("utf-8")
            self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(raw)));self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff");self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if not self.local_host():return self.json(403,{'error':'只接受本地工作台请求'})
            path=urlparse(self.path);params=parse_qs(path.query);q=lambda key,default="":params.get(key,[default])[0]
            try:
                if path.path=='/api/ai/settings':return self.json(200,self.ai_public())
                if path.path=='/api/jobs':
                    return self.json(200,app.public_jobs())
                if path.path=='/auth/callback':
                    try:app.auth.callback(params);message='授权处理完成。请返回 Cube 助手的“AI 设置”，读取模型列表并选择模型。'
                    except ValueError:message='此次登录没有完成。请返回 Cube 助手的“AI 设置”查看提示并重试。'
                    raw=('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="referrer" content="no-referrer"><title>Cube 助手 · 登录</title><body><h1>'+message+'</h1><p>可以关闭此窗口。</p></body></html>').encode('utf8')
                    self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(raw);return
                if path.path=='/api/health':return self.json(200,dict(app=APP_ID,workspace=WORKSPACE_ID,pid=os.getpid(),version=__version__,task_controls=True))
                if path.path=='/api/library':return self.json(200,library(app))
                if path.path=='/api/design-guide':return self.json(200,public_guide())
                if path.path=='/api/brackets':return self.json(200,public_profiles())
                if path.path=='/api/performance':return self.json(200,dict(gpu=acceleration.status(),cache=sim_cache.status(),learning=surrogate.status(app.catalog),forge=forge_status(),tuning=tuning.status()))
                if path.path=="/api/status":
                    with app.lock:active_jobs=sum(j['state'] in ACTIVE for j in app.jobs.values())
                    return self.json(200,dict(version=__version__,workspace_id=WORKSPACE_ID,cards=len(app.catalog.cards),snapshot=app.catalog.snapshot,
                        active_jobs=active_jobs,speed_version=2,task_controls=True,
                        experiments=dict(profiles={k:experiment_budget(k) for k in PROFILES},resources=execution_resources()),
                        knowledge_chunks=len(app.knowledge.chunks),gpt=app.ai_status(),themes=THEME_NAMES,
                        presets={"commander":BuildSpec.from_dict({'bracket':3}).to_dict(),"classic":BuildSpec.from_dict({"mode":"classic"}).to_dict()},brackets=public_profiles(),
                        feedback=app.feedback.status("commander:commander"),forge=forge_status()))
                if path.path=="/api/forge/status":return self.json(200,forge_status())
                if path.path=='/api/optimizations':
                    return self.json(200,[p.name for p in sorted(OPTIMIZATIONS.glob('*'),reverse=True) if (p/'report.json').is_file()][:30])
                if path.path.startswith('/optimizations/'):
                    parts=path.path.split('/')
                    if len(parts)!=4 or not re.fullmatch(r'[A-Za-z0-9_]+',parts[2]):raise FileNotFoundError()
                    if parts[3] not in {'report.json','report.md','swaps.csv','evidence.zip','protocol.json'}:raise FileNotFoundError()
                    if parts[3]=='report.json':
                        result=json.loads((OPTIMIZATIONS/parts[2]/parts[3]).read_text(encoding='utf-8'))
                        result['revision']=app.present(result['revision'])
                        return self.json(200,result)
                    return self.file(OPTIMIZATIONS/parts[2]/parts[3],True)
                if path.path=="/api/forge/matches":
                    return self.json(200,[p.name for p in sorted(MATCHES.glob('*'),reverse=True) if (p/'report.json').is_file()][:30])
                if path.path.startswith('/matches/'):
                    parts=path.path.split('/')
                    if len(parts)!=4 or not re.fullmatch(r'[A-Za-z0-9_]+',parts[2]):raise FileNotFoundError()
                    if parts[3] not in {'report.json','report.md','evidence.zip','games.json','cube.json'} and not re.fullmatch(r'pod[0-9]{3}_game[0-9]{3}\.log',parts[3]):raise FileNotFoundError()
                    return self.file(MATCHES/parts[2]/parts[3],True)
                if path.path=="/api/examples":return self.json(200,[{"id":n,"label":example_label(n)} for n in sorted(app.examples)])
                if path.path=="/api/example":
                    example=app.examples.get(q("id"))
                    if not example:raise FileNotFoundError("示例牌表不存在")
                    return self.json(200,{"text":example.read_text(encoding="utf-8-sig")})
                if path.path=="/api/cards":return self.json(200,app.catalog.search(q("q"),q("identity") or None,int(q("limit","30"))))
                if path.path=="/api/card":
                    n=app.catalog.resolve(q("name"))
                    if not n:raise FileNotFoundError("未确认的牌名")
                    return self.json(200,{k:v for k,v in app.catalog.cards[n].items() if k!="vector"})
                if path.path=="/api/knowledge":return self.json(200,app.knowledge.search(q("q")))
                if path.path=="/api/job":
                    job=app.get_job(q('id'))
                    if not job:raise FileNotFoundError("任务已过期或不存在")
                    return self.json(200,job)
                if path.path=='/api/job/checkpoint':
                    with app.lock:runner=app.controls.get(q('id'))
                    if not runner:
                        folder=app.job_paths.get(q('id'))
                        if not folder:raise FileNotFoundError('任务不存在')
                        runner=TaskProcess.__new__(TaskProcess);runner.folder=folder
                    return self.json(200,runner.checkpoint_records())
                if path.path=="/api/runs":
                    return self.json(200,[p.name for p in sorted(RUNS.glob("*"),reverse=True) if p.is_dir()][:30])
                if path.path.startswith("/exports/"):
                    parts=path.path.split("/")
                    if len(parts)!=4 or not re.fullmatch(r"[A-Za-z0-9_]+",parts[2]):raise FileNotFoundError()
                    if parts[3] not in {"cube.json","cube.csv","cubecobra.txt","report.md","spec.json","stress.json"}:raise FileNotFoundError()
                    target=RUNS/parts[2]/parts[3]
                    return self.file(target,True)
                target=ROOT/"web"/("index.html" if path.path=="/" else unquote(path.path).lstrip("/"))
                if not target.resolve().is_relative_to((ROOT/"web").resolve()):raise FileNotFoundError()
                return self.file(target)
            except (ValueError,TypeError) as e:self.json(400,{"error":str(e)})
            except FileNotFoundError:self.json(404,{"error":"找不到该资源"})
            except Exception:self.json(500,{"error":"请求处理失败"})
        def file(self,target,download=False):
            if not target.is_file():raise FileNotFoundError()
            with target.open('rb') as source:
                stat=os.fstat(source.fileno());etag=f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
                if not download and self.headers.get('If-None-Match')==etag:
                    self.send_response(304);self.send_header('ETag',etag)
                    self.send_header('Cache-Control','no-cache');self.end_headers();return
                content_type=mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
                if content_type.startswith('text/') or content_type in {'application/json','application/javascript','image/svg+xml'}:content_type+='; charset=utf-8'
                self.send_response(200);self.send_header('Content-Type',content_type)
                self.send_header('Content-Length',str(stat.st_size));self.send_header('Cache-Control','no-cache')
                self.send_header('X-Content-Type-Options','nosniff')
                if not download:self.send_header('ETag',etag)
                if download:self.send_header('Content-Disposition',f'attachment; filename="{target.name}"')
                self.end_headers()
                remaining=stat.st_size
                try:
                    while remaining:
                        chunk=source.read(min(128*1024,remaining))
                        if not chunk:break
                        self.wfile.write(chunk);remaining-=len(chunk)
                except (BrokenPipeError,ConnectionResetError):return
        def do_POST(self):
            try:
                if not self.local_host():return self.json(403,{'error':'只接受本地工作台请求'})
                origin=self.headers.get("Origin")
                if origin and origin not in {f"http://127.0.0.1:{self.server.server_port}",f"http://localhost:{self.server.server_port}"}:
                    return self.json(403,{"error":"只接受本地工作台请求"})
                if not self.headers.get("Content-Type","").startswith("application/json"):
                    return self.json(415,{"error":"请求需要 application/json"})
                length=int(self.headers.get("Content-Length","0"))
                if not 0<length<=2_000_000:return self.json(413,{"error":"请求大小必须在 1–2,000,000 字节之间"})
                data=json.loads(self.rfile.read(length));path=urlparse(self.path).path
                if not isinstance(data,dict):raise ValueError('请求内容必须是对象')
                if path=='/api/shutdown':
                    with app.lock:
                        if any(job['state'] in ACTIVE for job in app.jobs.values()):raise ValueError('还有运行或暂停中的任务，请先继续完成或强制结束，再退出助手。')
                        app.closing=True
                    self.json(200,dict(closing=True,message='助手已退出。牌表与记录已保留，重新双击入口即可继续。'))
                    threading.Thread(target=self.server.shutdown,daemon=True).start()
                    return
                if path=='/api/ai/settings':
                    app.ai_store.save(data);return self.json(200,self.ai_public())
                if path=='/api/ai/reset':
                    with app.auth.lock:
                        app.auth.pending=None;app.auth.generation+=1;app.auth.phase='idle';app.auth.message=''
                        app.ai_store.reset()
                    return self.json(200,dict(self.ai_public(),message='原连接文件已在本机备份，现可重新配置。需要撤销旧授权时，请到 ChatGPT 设置中断开应用。'))
                if path=='/api/ai/models':return self.json(200,{'models':LLMClient(app.ai_store,app.auth).models()})
                if path=='/api/ai/test':return self.json(200,LLMClient(app.ai_store,app.auth).test())
                if path=='/api/ai/chatgpt/login':return self.json(200,app.auth.begin(self.server.server_port,data.get('account_id','')))
                if path=='/api/ai/chatgpt/select':
                    app.ai_store.select_account(data.get('account_id',''));return self.json(200,self.ai_public())
                if path=='/api/ai/chatgpt/logout':return self.json(200,app.auth.logout(data.get('account_id','')))
                if path=='/api/task/control':return self.json(200,app.control(data.get('id'),data.get('action')))
                if path=="/api/tasks":return self.json(202,app.submit(data))
                spec=BuildSpec.from_dict(data.get("spec"))
                if path=='/api/save':
                    rows,unknown=app.rows(data)
                    if unknown or not rows:raise ValueError('请先确认并载入牌表')
                    result=dict(cards=rows,spec=spec.to_dict(),audit=audit(app.catalog,rows,spec,strict=True),
                        solver=None,changes=None,provenance=dict(snapshot=app.catalog.snapshot,catalog=app.catalog.signature,features=VERSION,source='manual-save'))
                    if data.get('require_valid') and result['audit']['hard_errors']:
                        raise ValueError('当前参数下牌表未通过检查，请先重新构筑或处理报告中的错误')
                    return self.json(200,app.present(export_run(app.catalog,result)))
                if path=="/api/analyze":
                    rows,unknown=app.rows(data)
                    return self.json(200,app.present(dict(cards=rows,spec=spec.to_dict(),audit=audit(app.catalog,rows,spec,unknown,strict=True))))
                if path=="/api/recommend":
                    rows,unknown=app.rows(data)
                    if unknown:raise ValueError("请先确认所有牌名")
                    return self.json(200,replacements(app.catalog,spec,rows,data.get("name","")))
                if path=='/api/apply-swap':
                    rows,unknown=app.rows(data)
                    if unknown or not rows:raise ValueError('请先载入并确认当前牌表')
                    remove=app.catalog.resolve(data.get('remove',''));add=app.catalog.resolve(data.get('add',''))
                    if not remove or not add:raise ValueError('替换牌名未被真实牌库确认')
                    if not any(r['name']==remove for r in rows) or any(r['name']==add for r in rows):raise ValueError('当前牌表已变化，请重新获取替换建议')
                    if app.catalog.cards[remove]['identity']!=app.catalog.cards[add]['identity']:raise ValueError('替换不能改变颜色身份配额')
                    updated=[dict(r,name=add) if r['name']==remove else r for r in rows]
                    assessment=audit(app.catalog,updated,spec,strict=True)
                    errors=[i['message'] for i in assessment['issues'] if i['severity']=='error']
                    if errors:raise ValueError('未应用替换：'+'；'.join(errors[:4]))
                    return self.json(200,app.present(dict(cards=updated,spec=spec.to_dict(),audit=assessment)))
                if path=="/api/feedback":
                    a=app.catalog.resolve(data.get("winner",""));b=app.catalog.resolve(data.get("loser",""))
                    if not a or not b:raise ValueError("比较中的卡名未确认")
                    return self.json(200,app.feedback.add(a,b,app.feedback.context(spec),data.get("note","")))
                if path=="/api/train":return self.json(200,app.feedback.train(app.catalog,app.feedback.context(spec)))
                return self.json(404,{"error":"没有该接口"})
            except (ValueError,TypeError,KeyError) as e:self.json(400,{"error":str(e)})
            except Exception:self.json(500,{"error":"请求处理失败"})
    return Handler

def serve(port=8765):
    print("载入真实牌库和构筑知识…",flush=True)
    app=Application();server=ThreadingHTTPServer(("127.0.0.1",port),handler_for(app))
    print(f"Cube Atelier http://127.0.0.1:{server.server_port} · {len(app.catalog.cards)} 张牌 · 快照 {app.catalog.snapshot}",flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.shutdown()
