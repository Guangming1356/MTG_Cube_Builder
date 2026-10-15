import json
import mimetypes
import re
import threading
import uuid
import os
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
from .ai_settings import SettingsStore
from .chatgpt_auth import ChatGPTAuth
from .design import public_guide
from .brackets import public_profiles
from .launcher import APP_ID, WORKSPACE_ID

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

class Application:
    def __init__(self,catalog=None,ai_store=None):
        self.catalog=catalog or Catalog();self.knowledge=Knowledge();self.feedback=FeedbackStore()
        self.ai_store=ai_store or SettingsStore();self.auth=ChatGPTAuth(self.ai_store)
        self.jobs={};self.lock=threading.Lock();self.executor=ThreadPoolExecutor(max_workers=2)
        example_root = LIBRARY if LIBRARY.is_dir() else WORKSPACE
        self.examples={p.parent.name:p for p in example_root.glob("commander_cube_600*/cube_600.csv")}
        ref=WORKSPACE/"ref_thecommandercube.csv"
        if ref.exists():self.examples["reference_commandercube"]=ref

    def rows(self,data):
        if "text" in data:
            rows,unknown=self.catalog.parse(data["text"])
            if data.get("spec",{}).get("mode")=="classic":
                for row in rows:
                    if row['role']=='Commander':row['role']='Main'
            return rows,unknown
        rows=[];unknown=[]
        for row in data.get("cards",[]):
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
        if operation not in {"build","repair","stress","forge","optimize","chat","plan"}:raise ValueError("未知操作")
        if operation in {"repair","stress","forge","optimize"} and not rows:raise ValueError("请先载入牌表")
        client=LLMClient(self.ai_store,self.auth) if operation in {'chat','plan'} else None
        if client and not client.status()['configured']:raise ValueError('AI 尚未就绪，请在“AI 设置”中连接服务并选择模型。离线功能可直接使用。')
        job_id=uuid.uuid4().hex[:16]
        with self.lock:
            if sum(j["state"] in {"queued","running"} for j in self.jobs.values())>=4:raise ValueError("已有 4 个任务，请等待其中一个完成")
            self.jobs[job_id]=dict(id=job_id,state="queued",progress="等待运行")
            completed=[k for k,j in self.jobs.items() if j["state"] in {"done","failed"}]
            for k in completed[:-30]:del self.jobs[k]
        def progress(message):
            with self.lock:self.jobs[job_id]["progress"]=message
        def execute():
            with self.lock:self.jobs[job_id]["state"]="running"
            try:
                if operation in {"build","repair"}:
                    value=export_run(self.catalog,build(self.catalog,spec,rows if operation=="repair" else None,progress,self.feedback));value=self.present(value)
                elif operation=="stress":
                    value=stress_test(self.catalog,rows,spec,int(data.get("trials",100)),progress)
                    run_id=data.get("run_id")
                    if run_id and re.fullmatch(r"[A-Za-z0-9_]+",run_id) and (RUNS/run_id).is_dir():
                        (RUNS/run_id/"stress.json").write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
                elif operation=="forge":
                    value=forge_simulate(self.catalog,rows,spec,data.get('pods',2),data.get('games_per_pod',3),data.get('clock_seconds',90),progress)
                elif operation=="optimize":
                    value=optimize(self.catalog,rows,spec,progress,workers=3,clock=data.get('clock_seconds',120))
                    value['revision']=self.present(value['revision'])
                elif operation=="chat":
                    progress("AI 正在检索牌库、技能与构筑审计")
                    value=advise(self.catalog,self.knowledge,spec,rows,data.get("message",""),client)
                else:
                    progress("AI 将需求转换为构筑参数")
                    value=plan(data.get("message",""),spec,self.knowledge,client)
                with self.lock:self.jobs[job_id].update(state="done",progress="完成",result=value)
            except Exception as e:
                with self.lock:self.jobs[job_id].update(state="failed",progress="任务未完成",error=str(e))
        self.executor.submit(execute)
        return {"job_id":job_id}

def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def local_host(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        def ai_public(self):
            return dict(app.ai_store.public(),status=LLMClient(app.ai_store,app.auth).status(),auth=app.auth.status())
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
                if path.path=='/auth/callback':
                    try:app.auth.callback(params);message='授权处理完成。请返回 Cube 助手的“AI 设置”，读取模型列表并选择模型。'
                    except ValueError:message='此次登录没有完成。请返回 Cube 助手的“AI 设置”查看提示并重试。'
                    raw=('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="referrer" content="no-referrer"><title>Cube 助手 · 登录</title><body><h1>'+message+'</h1><p>可以关闭此窗口。</p></body></html>').encode('utf8')
                    self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(raw);return
                if path.path=='/api/health':return self.json(200,dict(app=APP_ID,workspace=WORKSPACE_ID,pid=os.getpid(),version=__version__))
                if path.path=='/api/library':return self.json(200,library(app))
                if path.path=='/api/design-guide':return self.json(200,public_guide())
                if path.path=='/api/brackets':return self.json(200,public_profiles())
                if path.path=="/api/status":
                    return self.json(200,dict(version=__version__,cards=len(app.catalog.cards),snapshot=app.catalog.snapshot,
                        knowledge_chunks=len(app.knowledge.chunks),gpt=LLMClient(app.ai_store,app.auth).status(),themes=THEME_NAMES,
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
                    with app.lock:job=app.jobs.get(q("id"));job=dict(job) if job else None
                    if not job:raise FileNotFoundError("任务已过期或不存在")
                    return self.json(200,job)
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
            raw=target.read_bytes();self.send_response(200)
            self.send_header("Content-Type",(mimetypes.guess_type(str(target))[0] or "application/octet-stream")+"; charset=utf-8")
            self.send_header("Content-Length",str(len(raw)))
            if download:self.send_header("Content-Disposition",f'attachment; filename="{target.name}"')
            self.end_headers();self.wfile.write(raw)
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
                if path=='/api/ai/settings':
                    app.ai_store.save(data);return self.json(200,self.ai_public())
                if path=='/api/ai/models':return self.json(200,{'models':LLMClient(app.ai_store,app.auth).models()})
                if path=='/api/ai/test':return self.json(200,LLMClient(app.ai_store,app.auth).test())
                if path=='/api/ai/chatgpt/login':return self.json(200,app.auth.begin(self.server.server_port,data.get('account_id','')))
                if path=='/api/ai/chatgpt/select':
                    app.ai_store.select_account(data.get('account_id',''));return self.json(200,self.ai_public())
                if path=='/api/ai/chatgpt/logout':return self.json(200,app.auth.logout(data.get('account_id','')))
                if path=="/api/tasks":return self.json(202,app.submit(data))
                spec=BuildSpec.from_dict(data.get("spec"))
                if path=='/api/save':
                    rows,unknown=app.rows(data)
                    if unknown or not rows:raise ValueError('请先确认并载入牌表')
                    result=dict(cards=rows,spec=spec.to_dict(),audit=audit(app.catalog,rows,spec,strict=True),
                        solver=None,changes=None,provenance=dict(snapshot=app.catalog.snapshot,catalog=app.catalog.signature,features=VERSION,source='manual-save'))
                    return self.json(200,app.present(export_run(app.catalog,result)))
                if path=="/api/analyze":
                    rows,unknown=app.rows(data)
                    return self.json(200,app.present(dict(cards=rows,spec=spec.to_dict(),audit=audit(app.catalog,rows,spec,unknown,strict=True))))
                if path=="/api/recommend":
                    rows,unknown=app.rows(data)
                    if unknown:raise ValueError("请先确认所有牌名")
                    return self.json(200,replacements(app.catalog,spec,rows,data.get("name","")))
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
    finally:server.server_close();app.executor.shutdown(wait=False,cancel_futures=True)
