"""Import sanitized portable snapshots into Git, then publish resumable Releases.

No tokens are read or stored by this tool: authenticated GitHub CLI handles Git
and API credentials. Deployment state and binaries stay outside the Git tree.
"""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile

SOURCE = Path(__file__).resolve().parents[2]
STATE = SOURCE/'cube_ai/private/github-publish'
OUTPUT = SOURCE/'发布包/GitHub发布'
CHECKOUT = SOURCE/'GitHub仓库/MTG_Cube_Builder'
GUARD = threading.RLock()
VERSIONS = ['20261011','20261015',*[f'20261015-r{i}' for i in range(2,8)]]
DESCRIPTIONS = [
    '首个 Windows 便携版本', '多服务 AI 接入版本', 'AI 接入与构筑规划修复',
    '并行实战与评估规模设置', '常驻 Forge、结果缓存、批量评分与实战学习',
    '候选并行比较、轮抓复用、阶段计时与机器测速', '暂停、继续、强制结束与任务记录',
    '按剩余内存动态安排对局、资源统计与并行上限修复']
PRIVATE_NAMES = {'.env','.git','private','ai-settings.bin','preferences.sqlite','catalog.json',
                 'entrance.json','launcher.log','forge.profile.properties','__pycache__'}
SECRET = re.compile(rb'(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{25,}|gh[pousr]_[A-Za-z0-9]{25,})')


def run(args, cwd=None, timeout=180, capture=True):
    result = subprocess.run([str(a) for a in args],cwd=cwd,timeout=timeout,
                            capture_output=capture,text=True,encoding='utf8',errors='replace')
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed ({result.returncode}): '+(result.stderr or result.stdout or '')[-1800:])
    return (result.stdout or '').strip()


def atomic(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    os.replace(tmp,path)


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def private_needles():
    # Match the actual workspace directory boundary, not public vendor examples
    # such as D:/mtg-pics, which are unrelated to the workspace.
    values={str(SOURCE),SOURCE.as_posix(),str(SOURCE.parent)+os.sep,SOURCE.parent.as_posix()+'/',
            str(Path.home()),Path.home().as_posix(),sys.prefix}
    email=run(['git','config','--get','user.email'])
    if email and not email.endswith('@users.noreply.github.com'):values.add(email)
    variants={v for value in values for v in (value,value.replace('\\','\\\\')) if len(v)>5}
    return tuple({data for v in variants for data in (v.encode(),v.encode('utf-16-le'))})


def scan_data(data, needles, scan_secrets=True):
    lower=data.lower()
    if any(n.lower() in lower for n in needles):return 'personal_path_or_email'
    for match in SECRET.finditer(data) if scan_secrets else ():
        if not any(word in match.group().lower() for word in (b'test',b'example',b'synthetic',b'dummy',b'fake')):
            return 'credential_like_string'
    return None


def scan_archive(path, needles):
    digest=sha(path)
    companion=path.with_suffix('.zip.sha256.txt')
    if not companion.is_file() or companion.read_text(encoding='utf8').split()[0]!=digest:
        raise ValueError('Local archive checksum does not match: '+path.name)
    count=0;findings=[]
    with zipfile.ZipFile(path) as z:
        for item in z.infolist():
            rel=PurePosixPath(item.filename)
            if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0]!='Cube助手':
                raise ValueError('Unsafe ZIP path')
            if item.is_dir():continue
            count+=1
            parts=rel.parts[1:]
            if any(p in PRIVATE_NAMES for p in parts) or any(p in {'runs','matches','optimizations','models'} for p in parts[:2]):
                findings.append(dict(file=rel.as_posix(),kind='private_state'))
            with z.open(item) as stream:
                tail=b''
                while chunk:=stream.read(1024*1024):
                    reason=scan_data(tail+chunk,needles,rel.suffix.lower() in
                                     {'.py','.pyw','.md','.json','.txt','.cs','.js','.html','.example','.yml','.yaml','.ps1','.properties'})
                    if reason:
                        findings.append(dict(file=rel.as_posix(),kind=reason));break
                    tail=chunk[-512:]
    if findings:
        atomic(STATE/('failed-scan-'+path.stem+'.json'),findings)
        raise ValueError('Archive privacy scan failed: '+json.dumps(findings[:8],ensure_ascii=False))
    return dict(sha256=digest,bytes=path.stat().st_size,files=count,private_findings=0)


def sanitize_legacy_example(original,version):
    """Change only a legacy illustrative path; retain the local original."""
    folder=OUTPUT/version;folder.mkdir(parents=True,exist_ok=True)
    target=folder/f'MTG_Cube_Builder-Windows-x64-{version}.zip'
    changed=[];original_digest=sha(original)
    with zipfile.ZipFile(original) as source,zipfile.ZipFile(target,'w',allowZip64=True) as dest:
        for item in source.infolist():
            replacement=None
            if item.filename.endswith('/forge.profile.properties.example'):
                replacement=b'# Optional example. The launcher generates the actual profile.\n# userDir=./userdata\n# cacheDir=./cache\n'
                changed.append(item.filename)
            elif item.filename=='Cube助手/发布说明.json':
                value=json.loads(source.read(item).decode('utf-8-sig'))
                value['privacy_cleanup']=dict(original_archive_sha256=original_digest,
                    note='Replaced an illustrative local filesystem path with a relative-path example; application modules and bundled dependencies are unchanged.')
                replacement=json.dumps(value,ensure_ascii=False,indent=2).encode()
            elif item.filename=='Cube助手/隐私检查.json':
                replacement=json.dumps(dict(private_patterns_found=0,state_files_included=0,
                    note='Rescanned before GitHub publication after normalizing a legacy example path.'),indent=2).encode()
            if replacement is not None:dest.writestr(item,replacement)
            else:
                with source.open(item) as inp,dest.open(item,'w',force_zip64=True) as out:shutil.copyfileobj(inp,out,1024*1024)
    digest=sha(target)
    target.with_suffix('.zip.sha256.txt').write_text(digest+'  '+target.name+'\n',encoding='ascii')
    return target,dict(original_sha256=original_digest,sanitized_members=changed)


def source_member(rel):
    p=PurePosixPath(rel);parts=p.parts
    if not parts:return False
    if parts[0]=='cube_ai':
        if len(parts)==2:return p.suffix=='.py' or p.name in {'requirements.txt','.env.example','README.md'}
        if parts[1] in {'web','knowledge','profiles','native','docs','research'}:return True
        return parts[1]=='data' and p.name in {'cube_studies.json','learning_sources.json'}
    return parts[0] in {'magic-skill','cube_generator','入口源码'} or p.name=='启动.pyw'


def clear_export():
    expected=(SOURCE/'GitHub仓库/MTG_Cube_Builder').resolve()
    if CHECKOUT.resolve()!=expected or not CHECKOUT.resolve().is_relative_to((SOURCE/'GitHub仓库').resolve()):
        raise ValueError('Unexpected export root')
    for child in CHECKOUT.iterdir():
        if child.name=='.git':continue
        if not child.resolve().is_relative_to(expected):raise ValueError('Export contains an external link')
        if child.is_dir():shutil.rmtree(child)
        else:child.unlink()


IGNORE = '''# Local configuration, credentials and generated results
.env
.env.local
.env.*.local
private/
ai-settings.bin
*.sqlite*
catalog.json
__pycache__/
.pytest_cache/
*.py[cod]
.venv/
venv/
runtime/
runs/
matches/
optimizations/
models/
cache/
cube_ai/data/card_pool.json
发布包/
GitHub仓库/
牌表资料/
*.lnk
*.zip
*.tar.gz
*.exe
*.dll
*.jar
'''


def readme(repo, current):
    rows='\n'.join(f'| [{v}](https://github.com/{repo}/releases/tag/{tag(v)}) | {description} |'
                   for v,description in zip(VERSIONS,DESCRIPTIONS))
    return f'''# MTG_Cube_Builder · 万智牌 Cube 助手

用中文界面构筑 Cube，检查费用曲线、互动、终结与指挥官支持，再用自动轮抓、组牌和 Forge AI 实战提出改进。

## 普通玩家从这里开始

1. 打开 [最新版本下载](https://github.com/{repo}/releases/latest)。
2. 在 **Assets** 中下载 `MTG_Cube_Builder-Windows-x64-*.zip`。
3. 完整解压后，双击 **启动Cube助手.exe**。
4. 选择玩法、Bracket 强度和偏好，生成或载入牌表。

**请下载 Windows 便携包。GitHub 自动提供的 Source code 压缩包是开发源码，不含运行环境和完整卡牌数据。**

便携包支持 Windows 10/11 64 位，内置 Python、Java、Forge 与卡牌快照，无需自行安装运行环境。离线可生成、审计、轮抓及实战；AI 服务按各用户自己的账户配置。

推荐最新的 **v2026.10.15-r7**。本标签对应的应用快照为 **{current}**。

## 功能

- Commander / EDH 与传统 Cube 构筑，Bracket 1–5 和同档强度微调。
- 检查指挥官、颜色身份、角色密度、费用曲线、修色与终结手段。
- 三人 EDH：每组 15 张，每人依次取 2 张，三人取过后弃 9 张；每人抓 60 张。自选抓到的牌并自由补基本地，实战导出 60 张含指挥官。
- Forge 原生 AI 对局，保留真实引擎日志，按训练、候选选择与独立验证推进。
- 较新版本提供并行、常驻引擎、缓存、阶段计时、暂停/继续/强制结束，以及按剩余内存动态安排对局。具体功能以对应版本为准。
- 可选多厂商 AI 接入；不要求配置 GPT 才能使用本地构筑功能。

## 历史版本

| 版本 | 主要变化 |
|---|---|
{rows}

每个 Release 提供完整 Windows 便携包、`SHA256SUMS.txt` 和 `release-info.json`。每个标签的应用模块从对应原始便携包提取，并记录来源校验；版本历史为本次整理导入，不冒充原开发时期的 Git 提交。

## 开发者

仓库保存应用源码、知识库、文档和最新版本的测试/构建辅助工具。大型运行环境、完整卡牌快照和个人使用数据不进入 Git。

使用 Python 3.13 或 3.14：

```powershell
python -m pip install -r requirements-dev.txt
python tools/setup_dev.py --zip <下载的对应版本便携包.zip>
python -X utf8 -m cube_ai serve
python -m pytest cube_ai/tests -q
```

`setup_dev.py` 校验对应版本的压缩包，并只提取牌库及 Forge/Java 运行环境。不会导入 AI 账户、密钥、偏好、牌表或旧对局。历史标签未补写不存在的早期测试，最新标签包含当前测试集。

## 使用与评估边界

卡牌快照和 Forge 实现不保证覆盖所有新牌。Forge AI 对多人政治、组合技及控制有驾驶偏差；少量机器人胜率不等于娱乐性或人类实战强度。Bracket 是构筑体验目标；项目不认证 cEDH。

## 来源与隐私

分享包和 Git 源码不含个人 AI 配置、登录状态、密钥、原有牌表或对局历史。使用后的副本会产生本机数据；分享时使用 Releases 原始压缩包。

第三方来源、许可及完整对应源码在便携包内保留，仓库摘要见 [第三方说明](THIRD_PARTY_NOTICES.md)。本仓库的默认访问权限为私人；是否公开由仓库所有者决定。
'''


SETUP = '''"""Restore only release dependencies into a source checkout."""
import argparse,hashlib,json,zipfile
from pathlib import Path,PurePosixPath
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--zip',required=True,type=Path);args=p.parse_args()
expected=json.loads((root/'distribution/archive.json').read_text(encoding='utf8'))
with args.zip.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
if actual!=expected['sha256']:raise SystemExit('压缩包不是当前标签对应版本，或校验失败。请下载 README 中对应版本。')
count=0
with zipfile.ZipFile(args.zip) as z:
 for entry in z.infolist():
  path=PurePosixPath(entry.filename)
  if path.is_absolute() or '..' in path.parts:raise SystemExit('压缩包路径无效')
  if not path.parts or path.parts[0]!='Cube助手':continue
  rel=PurePosixPath(*path.parts[1:])
  chosen=rel.as_posix()=='cube_ai/data/card_pool.json' or rel.as_posix().startswith('cube_ai/runtime/')
  if not chosen or entry.is_dir():continue
  if any(s in {'private','cache','userdata','entrance.json','launcher.log','forge.profile.properties'} for s in rel.parts):continue
  target=root/Path(*rel.parts)
  if not target.resolve().is_relative_to(root.resolve()):raise SystemExit('目标路径无效')
  if target.exists() and rel.as_posix()=='cube_ai/data/card_pool.json':
   with z.open(entry) as f:source_hash=hashlib.file_digest(f,'sha256').hexdigest()
   with target.open('rb') as f:target_hash=hashlib.file_digest(f,'sha256').hexdigest()
   if source_hash!=target_hash:raise SystemExit('现有牌库与发布版不同，请先备份现有牌库后再初始化。')
  target.parent.mkdir(parents=True,exist_ok=True)
  with z.open(entry) as f,target.open('wb') as out:
   import shutil;shutil.copyfileobj(f,out,1024*1024)
  count+=1
print('运行依赖已准备：',count,'个文件。运行 python -X utf8 -m cube_ai serve')
'''


def tag(version):return 'v'+version[:4]+'.'+version[4:6]+'.'+version[6:]


def export_snapshot(archive, repo, version, proof, needles, latest=False):
    clear_export();module_hashes={}
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            rel=PurePosixPath(item.filename).relative_to('Cube助手').as_posix()
            if item.is_dir() or not source_member(rel):continue
            data=z.read(item);destination=CHECKOUT/Path(rel)
            destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
            if rel.startswith('cube_ai/') and rel.count('/')==1 and rel.endswith('.py'):
                module_hashes[rel]=hashlib.sha256(data).hexdigest()
        distribution=CHECKOUT/'distribution';distribution.mkdir()
        (distribution/'manifest.json').write_bytes(z.read('Cube助手/发布说明.json'))
        docs=CHECKOUT/'docs';docs.mkdir()
        (docs/'PORTABLE_README.md').write_bytes(z.read('Cube助手/README.md'))
        (CHECKOUT/'THIRD_PARTY_NOTICES.md').write_text('# 第三方来源\n\n'+z.read('Cube助手/第三方来源/说明.txt').decode('utf-8-sig'),encoding='utf8')
    metadata=dict(version=version,tag=tag(version),original_file=archive.name,
                  asset=f'MTG_Cube_Builder-Windows-x64-{version}.zip',**proof,
                  application_source_sha256=module_hashes)
    atomic(distribution/'archive.json',metadata)
    (CHECKOUT/'README.md').write_text(readme(repo,version),encoding='utf8')
    (CHECKOUT/'.gitignore').write_text(IGNORE,encoding='utf8')
    (CHECKOUT/'.gitattributes').write_text('* -text\n*.py diff=python\n',encoding='utf8')
    (CHECKOUT/'requirements-dev.txt').write_text('-r cube_ai/requirements.txt\npytest>=8,<10\n',encoding='utf8')
    (CHECKOUT/'tools').mkdir()
    (CHECKOUT/'tools/setup_dev.py').write_text(SETUP,encoding='utf8')
    if latest:
        # Development-only files do not alter the application modules imported
        # from the release. Never copy local benchmark results or user Cubes.
        for path in (SOURCE/'cube_ai/tests').rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts:continue
            if path.suffix not in {'.py','.md','.csv'}:continue
            to=CHECKOUT/'cube_ai/tests'/path.relative_to(SOURCE/'cube_ai/tests')
            to.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,to)
        tools=CHECKOUT/'cube_ai/tools';tools.mkdir()
        for name in ['build_portable.py','compile_portable.ps1','portable_entry.pyw','PortableBootstrap.cs','publish_github_history.py']:
            source=SOURCE/'cube_ai/tools'/name
            text=source.read_text(encoding='utf8')
            if name=='build_portable.py':
                text=re.sub(r'    needles=\[.*?\]\n',
                    "    needles=[str(SOURCE.resolve()).encode(), str(Path.home()).encode(), b'sk-proj-']\n",text)
                line=next(line for line in text.splitlines() if "text=p.read_text(encoding='utf8').replace(" in line)
                text=text.replace(line,"            text=p.read_text(encoding='utf8').replace(str(SOURCE),'本项目文件夹').replace(SOURCE.as_posix(),'本项目文件夹')")
            (tools/name).write_text(text,encoding='utf8')
    files=0
    for path in CHECKOUT.rglob('*'):
        if not path.is_file() or '.git' in path.relative_to(CHECKOUT).parts:continue
        if path.stat().st_size>=50*2**20:raise ValueError('Oversized Git source file: '+path.name)
        data=path.read_bytes();reason=scan_data(data,needles)
        if reason:raise ValueError('Source privacy scan failed: '+str(path.relative_to(CHECKOUT))+' '+reason)
        if path.suffix in {'.py','.pyw'}:ast.parse(data.decode('utf-8-sig'),filename=str(path))
        files+=1
    return metadata,files


def prepare(repo):
    STATE.mkdir(parents=True,exist_ok=True);OUTPUT.mkdir(parents=True,exist_ok=True)
    user=json.loads(run(['gh','api','user']))
    CHECKOUT.mkdir(parents=True,exist_ok=True)
    if not (CHECKOUT/'.git').exists():
        if any(CHECKOUT.iterdir()):raise ValueError('Export directory is not empty')
        run(['git','init','-b','main'],CHECKOUT)
    run(['git','config','user.name',user['login']],CHECKOUT)
    run(['git','config','user.email',f"{user['id']}+{user['login']}@users.noreply.github.com"],CHECKOUT)
    run(['git','config','commit.gpgsign','false'],CHECKOUT)
    run(['git','config','credential.https://github.com.helper','!gh auth git-credential'],CHECKOUT)
    run(['git','config','--local','--replace-all','credential.helper',''],CHECKOUT)
    run(['git','config','--local','--add','credential.helper','!gh auth git-credential'],CHECKOUT)
    run(['git','config','credential.interactive','false'],CHECKOUT)
    if os.name=='nt':run(['git','config','http.sslBackend','schannel'],CHECKOUT)
    run(['git','config','http.version','HTTP/1.1'],CHECKOUT)
    needles=private_needles();releases=[]
    existing=set(run(['git','tag'],CHECKOUT).splitlines())
    for index,version in enumerate(VERSIONS):
        original=SOURCE/'发布包'/f'Cube助手-Windows64-便携版-{version}.zip'
        archive=original;cleanup={}
        print('Scanning '+archive.name,flush=True)
        scan_file=STATE/('scan-'+version+'.json')
        # Only reuse a completed scan if the full archive digest still matches.
        cached=json.loads(scan_file.read_text(encoding='utf8')) if scan_file.exists() else None
        if cached and cached['sha256']==sha(archive) and cached['private_findings']==0:proof=cached
        else:
            try:proof=scan_archive(archive,needles)
            except ValueError:
                findings_file=STATE/('failed-scan-'+archive.stem+'.json')
                findings=json.loads(findings_file.read_text(encoding='utf8')) if findings_file.exists() else []
                if not findings or any(f['kind']!='personal_path_or_email' or not f['file'].endswith('/forge.profile.properties.example') for f in findings):raise
                print('Normalizing legacy example path in upload copy: '+version,flush=True)
                archive,cleanup=sanitize_legacy_example(original,version)
                proof=scan_archive(archive,needles)
            atomic(scan_file,dict(proof,**cleanup))
        proof.update(cleanup)
        if tag(version) not in existing:
            metadata,files=export_snapshot(archive,repo,version,proof,needles,version==VERSIONS[-1])
            run(['git','add','--all'],CHECKOUT)
            run(['git','commit','-m',f'Import sanitized portable snapshot {tag(version)}'],CHECKOUT)
            run(['git','tag','-a',tag(version),'-m',f'Portable snapshot {tag(version)}; SHA256 {proof["sha256"]}'],CHECKOUT)
            print(f'Imported {tag(version)}: {files} source files, privacy scan passed',flush=True)
        else:
            metadata=json.loads(run(['git','show',f'{tag(version)}:distribution/archive.json'],CHECKOUT))
            if metadata['sha256']!=proof['sha256']:raise ValueError('Existing tag checksum differs')
        folder=OUTPUT/version;folder.mkdir(parents=True,exist_ok=True)
        asset=folder/metadata['asset']
        if not asset.exists():
            shutil.copyfile(archive,asset)
        if sha(asset)!=proof['sha256']:raise ValueError('Staged upload asset changed')
        (folder/'SHA256SUMS.txt').write_text(proof['sha256']+'  '+asset.name+'\n',encoding='ascii')
        atomic(folder/'release-info.json',metadata)
        notes=f'''## {DESCRIPTIONS[index]}

### 下载与启动
下载 **{asset.name}**，完整解压，双击 **启动Cube助手.exe**。不要将 GitHub 自动提供的 Source code 当作便携包。

### 对应版本
- 应用版本：`{version}`；源码标签：`{tag(version)}`。
- SHA256：`{proof['sha256']}`；可使用随附 `SHA256SUMS.txt` 校验。
- 这是历史便携包的原始内容，未改写包内版本日期。Git 提交为本次整理导入。
- 上传前重新扫描 {proof['files']} 个归档文件，未发现个人路径、个人邮箱、密钥或使用状态文件。
- 内置运行环境、卡牌快照和第三方许可/对应源码；不含用户 AI 账户、牌表、偏好或旧对局。

{'推荐使用此最新版。' if version==VERSIONS[-1] else '保留用于历史回溯，日常使用请优先下载 r7 或之后的最新版。'}

详细能力与限制见本标签 README 和包内说明。模型是否可用、API 费用按各用户自行配置的服务规则执行。
'''
        if metadata.get('sanitized_members'):
            notes=notes.replace('这是历史便携包的原始内容，未改写包内版本日期。',
                '此上传副本清理了配置示例中的本机路径，并更新隐私说明；应用程序与依赖未改动，包内版本日期保留。')
            notes+='\n### 历史包隐私清理\n原始本地包校验：`'+metadata['original_sha256']+'`。上传副本的校验以上方 SHA256 为准。\n'
        (folder/'notes.md').write_text(notes,encoding='utf8')
        releases.append(dict(version=version,tag=tag(version),title=f'{tag(version)} · {DESCRIPTIONS[index]}',
                             sha256=proof['sha256'],asset=asset.name,bytes=proof['bytes']))
        atomic(STATE/'prepared.json',dict(repository=repo,checkout=str(CHECKOUT),releases=releases))
    print('Prepared '+str(len(releases))+' releases at '+str(CHECKOUT),flush=True)


def private_repo(repo):
    data=json.loads(run(['gh','api',f'repos/{repo}']))
    if not data.get('private'):raise ValueError('Refusing to upload: repository is not private')
    return data


def get_release(repo,release_tag):
    # The tag endpoint omits draft releases. Authenticated listing includes
    # drafts, so an interrupted upload can safely resume before publication.
    pages=json.loads(run(['gh','api',f'repos/{repo}/releases?per_page=100','--paginate','--slurp']))
    for page in pages:
        for release in page:
            if release['tag_name']==release_tag:return release
    raise ValueError('Release not found: '+release_tag)


def publish(repo, workers):
    private_repo(repo)
    prepared=json.loads((STATE/'prepared.json').read_text(encoding='utf8'))
    if prepared['repository']!=repo or len(prepared['releases'])!=len(VERSIONS):raise ValueError('Preparation incomplete')
    if run(['git','status','--porcelain'],CHECKOUT):raise ValueError('Source checkout has uncommitted changes')
    remotes=run(['git','remote'],CHECKOUT).splitlines()
    url=f'https://github.com/{repo}.git'
    if 'origin' not in remotes:run(['git','remote','add','origin',url],CHECKOUT)
    elif run(['git','remote','get-url','origin'],CHECKOUT)!=url:raise ValueError('Unexpected origin URL')
    run(['git','push','--set-upstream','origin','main'],CHECKOUT,timeout=600)
    run(['git','push','origin','--tags'],CHECKOUT,timeout=600)
    state_path=STATE/'published.json'
    state=json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else dict(repository=repo,releases={})
    def update(version,**value):
        with GUARD:
            state['releases'].setdefault(version,{}).update(value)
            atomic(state_path,state)
    def api_release(release_tag):return get_release(repo,release_tag)
    def publish_one(release):
        version=release['version'];release_tag=release['tag'];folder=OUTPUT/version
        print('Uploading '+release_tag,flush=True);update(version,state='uploading',started=time.time())
        found=subprocess.run(['gh','release','view',release_tag,'--repo',repo],capture_output=True)
        if found.returncode:
            run(['gh','release','create',release_tag,'--repo',repo,'--verify-tag','--draft',
                 '--title',release['title'],'--notes-file',folder/'notes.md'])
        for name in [release['asset'],'SHA256SUMS.txt','release-info.json']:
            path=folder/name;digest=sha(path)
            if name==release['asset'] and (digest!=release['sha256'] or path.stat().st_size!=release['bytes']):
                raise ValueError('Prepared archive changed after the privacy scan')
            data=api_release(release_tag);existing=next((a for a in data['assets'] if a['name']==name),None)
            if existing and existing['state']=='uploaded' and existing['size']==path.stat().st_size and existing.get('digest')=='sha256:'+digest:
                print('Already verified '+release_tag+' '+name,flush=True);continue
            for attempt in range(3):
                try:
                    args=['gh','release','upload',release_tag,path,'--repo',repo]
                    if existing:args+=['--clobber']
                    run(args,timeout=7200)
                    break
                except RuntimeError:
                    if attempt==2:raise
                    time.sleep(3*(attempt+1))
                    data=api_release(release_tag);existing=next((a for a in data['assets'] if a['name']==name),None)
            uploaded=next(a for a in api_release(release_tag)['assets'] if a['name']==name)
            if uploaded['size']!=path.stat().st_size or uploaded['state']!='uploaded':raise ValueError('Incomplete upload')
            if uploaded.get('digest') and uploaded['digest']!='sha256:'+digest:raise ValueError('Remote SHA256 mismatch')
            update(version,last_asset=name,last_asset_digest=uploaded.get('digest'))
            print('Verified '+release_tag+' '+name,flush=True)
        run(['gh','release','edit',release_tag,'--repo',repo,'--draft=false',
             '--latest='+('true' if version==VERSIONS[-1] else 'false')])
        remote=api_release(release_tag)
        update(version,state='published',url=remote['html_url'],assets=remote['assets'])
        print('Published '+remote['html_url'],flush=True)
    order=[prepared['releases'][-1],*prepared['releases'][:-1]]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending={pool.submit(publish_one,r):r['tag'] for r in order}
        while pending:
            done,_=wait(pending,timeout=30,return_when=FIRST_COMPLETED)
            for future in done:
                release_tag=pending.pop(future)
                try:future.result()
                except Exception as error:
                    print('FAILED '+release_tag+': '+str(error),flush=True)
                    raise
            if not done:print('Uploads in progress: '+', '.join(pending.values()),flush=True)
    private_repo(repo)
    run(['gh','release','edit',tag(VERSIONS[-1]),'--repo',repo,'--latest=true'])
    verified=[]
    for r in prepared['releases']:
        remote=api_release(r['tag'])
        if remote['draft'] or len(remote['assets'])!=3:raise ValueError('Release is not complete')
        for a in remote['assets']:
            if a.get('digest')!='sha256:'+sha(OUTPUT/r['version']/a['name']):raise ValueError('Final remote digest verification failed')
        verified.append(dict(tag=r['tag'],url=remote['html_url'],assets=[dict(name=a['name'],size=a['size'],digest=a['digest']) for a in remote['assets']]))
    atomic(STATE/'verified.json',dict(repository=repo,private=True,releases=verified,latest=tag(VERSIONS[-1])))
    print('All eight releases published and verified; repository remains PRIVATE',flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['prepare','publish']);p.add_argument('--repo',required=True)
    p.add_argument('--workers',type=int,choices=[1,2],default=2);a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',a.repo):raise ValueError('Invalid repository name')
    if a.operation=='prepare':prepare(a.repo)
    else:publish(a.repo,a.workers)


if __name__=='__main__':main()
