"""Build a clean portable update from a verified previous release.

Application Python, web assets, selected public docs and reviewed compatibility
bytes with their complete build sources are overlaid. The
existing embedded Python, wheels, Forge, Java, licenses and corresponding source
archives are retained. A changed Java bridge requires a full rebuild instead.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import shutil
import subprocess
import tempfile
import zipfile

REPOSITORY='Guangming1356/MTG_Cube_Builder'
DOCS={'BRACKETS.md','AI_CONNECTIONS.md','DEBUG_REPORT.md','PARALLEL_EVALUATION.md',
      'SPEED_REPORT.md','SPEED_SEARCH_REPORT.md','DYNAMIC_RESOURCES.md','TASK_CONTROL.md','DECK_POLICY_STUDY.md','NATIVE_DIAGNOSTICS.md','FORGE_COMPATIBILITY.md'}
SECRET=re.compile(rb'(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{25,}|gh[pousr]_[A-Za-z0-9]{25,})')
LOCAL_PROFILE=re.compile(rb'[A-Za-z]:[/\\]+Users[/\\]+[^/\\\s"\']+',re.I)
PRIVATE_NAMES={'.env','.git','__pycache__','.pytest_cache','preferences.sqlite','catalog.json','ai-settings.bin','entrance.json','launcher.log','forge.profile.properties'}


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def tag(version):
    if not re.fullmatch(r'20\d{6}(?:-r[1-9]\d*)?',version):raise ValueError('版本需为 YYYYMMDD 或 YYYYMMDD-rN')
    return 'v'+version[:4]+'.'+version[4:6]+'.'+version[6:]


def safe_name(name):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or not path.parts or path.parts[0]!='Cube助手':raise ValueError('基包路径无效：'+name)
    if any(p in PRIVATE_NAMES for p in path.parts):raise ValueError('发布包包含本机状态：'+name)
    if len(path.parts)>2 and path.parts[1]=='cube_ai' and path.parts[2] in {'private','runs','matches','optimizations','cache','models','tests','tools'}:raise ValueError('发布包包含使用或开发数据：'+name)


def scan_overlay(name,data):
    if name.endswith('.py'):ast.parse(data.decode('utf-8-sig'),filename=name)
    if SECRET.search(data):raise ValueError('应用文件包含疑似凭据：'+name)
    if LOCAL_PROFILE.search(data):raise ValueError('应用文件包含本机路径：'+name)
    for value in ['Anaconda2026','D:\\MTG','D:/MTG']:
        if value.encode() in data or value.encode('utf-16-le') in data:raise ValueError('应用文件包含本机路径：'+name)


def overlay_files(source):
    app=source/'cube_ai';files={}
    for path in app.glob('*.py'):files['cube_ai/'+path.name]=path.read_bytes()
    for path in (app/'web').rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts:files['cube_ai/web/'+path.relative_to(app/'web').as_posix()]=path.read_bytes()
    if (app/'forge_card_names.py').is_file():
        from cube_ai.forge_card_names import bundle_alias_asset
        files.update(bundle_alias_asset(app/'data/forge_name_aliases.json'))
    public_docs=DOCS|{p.name for p in (app/'docs').glob('OPTIMIZATION_*.md') if re.fullmatch(r'OPTIMIZATION_20\d{6}\.md',p.name)}
    for name in public_docs:
        path=app/'docs'/name
        if path.is_file():
            text=path.read_text(encoding='utf-8-sig').replace('D:\\MTG\\Cube助手','本项目文件夹').replace('D:/MTG/Cube助手','本项目文件夹')
            files['cube_ai/docs/'+name]=text.encode('utf8')
    assets=app/'native/compatibility/modal-context-1'
    if (assets/'manifest.json').is_file():
        from cube_ai.forge_compat import bundle_files
        for name,data in bundle_files(assets).items():files['cube_ai/native/compatibility/modal-context-1/'+name]=data
    for name,data in files.items():scan_overlay(name,data)
    return files


def repackage(base,source,output,version,expected_sha256,commit='unknown'):
    release_tag=tag(version)
    if not re.fullmatch(r'[a-fA-F0-9]{64}',expected_sha256) or sha(base)!=expected_sha256.lower():raise ValueError('基包 SHA256 校验失败')
    output.mkdir(parents=True,exist_ok=True)
    destination=output/f'MTG_Cube_Builder-Windows-x64-{version}.zip'
    if destination.exists():raise FileExistsError('目标版本已存在，请使用新版本号')
    replacements=overlay_files(source)
    with zipfile.ZipFile(base) as archive:
        entries=archive.infolist();names=[entry.filename for entry in entries]
        if len(names)!=len(set(names)):raise ValueError('基包有重复路径')
        for name in names:safe_name(name)
        required=['启动Cube助手.exe','关闭Cube助手.exe','启动.pyw','发布说明.json']
        if any('Cube助手/'+name not in names for name in required):raise ValueError('基包缺少便携入口或清单')
        requirements=source/'cube_ai/requirements.txt'
        if requirements.is_file() and 'Cube助手/cube_ai/requirements.txt' in names:
            normalized=lambda text:[line.strip() for line in text.splitlines() if line.strip() and not line.startswith('#')]
            if normalized(requirements.read_text(encoding='utf8'))!=normalized(archive.read('Cube助手/cube_ai/requirements.txt').decode('utf8')):
                raise ValueError('运行依赖已改变，需要完整构建运行环境，不能复用旧基包')
        for path in (source/'cube_ai/native').glob('*.java'):
            name='Cube助手/cube_ai/native/'+path.name
            if name not in names or archive.read(name)!=path.read_bytes():raise ValueError('Java 桥接源码已改变，需要完整编译并验证，不能复用旧二进制')
        if 'cube_ai/native/compatibility/modal-context-1/manifest.json' in replacements:
            from cube_ai.forge_compat import FORGE_SHA
            jars=[name for name in names if name.endswith('/forge-gui-desktop-2.0.15-jar-with-dependencies.jar')]
            if len(jars)!=1:raise ValueError('基包缺少兼容修复对应的唯一 Forge 引擎')
            with archive.open(jars[0]) as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=FORGE_SHA:raise ValueError('基包 Forge 引擎与兼容修复不匹配')
        manifest=json.loads(archive.read('Cube助手/发布说明.json'))
        application_version='unknown'
        for node in ast.parse(replacements.get('cube_ai/__init__.py',b'').decode('utf-8-sig')).body:
            if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='__version__' for target in node.targets):application_version=ast.literal_eval(node.value)
        manifest.update(version=version+'-portable-ai',application_version=application_version,source_commit=commit,base_archive_sha256=expected_sha256.lower())
        replacements['发布说明.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf8')
        notes=source/'distribution/notes.md'
        update='\n\n本版更新 · '+version+'\n'+(notes.read_text(encoding='utf8') if notes.is_file() else '更新内容见对应 GitHub Release 的发布说明。\n')
        for name in ['README.md','先看这里.txt']:
            full='Cube助手/'+name
            if full in names:replacements[name]=(archive.read(full).decode('utf-8-sig')+update).encode('utf8')
        hashes={name:hashlib.sha256(data).hexdigest() for name,data in replacements.items() if name.startswith('cube_ai/')}
        replacements['隐私检查.json']=json.dumps(dict(files_overlaid=len(hashes),private_patterns_found=0,state_files_included=0,base_archive_verified=True),ensure_ascii=False,indent=2).encode('utf8')
        with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as target:
            written=set()
            for entry in entries:
                if entry.is_dir():continue
                relative=PurePosixPath(*PurePosixPath(entry.filename).parts[1:]).as_posix()
                if relative in replacements:
                    target.writestr(entry,replacements[relative]);written.add(relative)
                else:
                    with archive.open(entry) as stream,target.open(entry,'w',force_zip64=True) as sink:shutil.copyfileobj(stream,sink,128*1024)
            for name,data in sorted(replacements.items()):
                if name not in written:target.writestr('Cube助手/'+name,data)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:raise ValueError('输出压缩包完整性校验失败')
        for name in archive.namelist():safe_name(name)
        for name,digest in hashes.items():
            if hashlib.sha256(archive.read('Cube助手/'+name)).hexdigest()!=digest:raise ValueError('应用文件校验失败：'+name)
        count=len(archive.infolist())
    record=dict(version=version,tag=release_tag,asset=destination.name,original_file=destination.name,
                sha256=sha(destination),bytes=destination.stat().st_size,files=count,private_findings=0,
                application_source_sha256=hashes,source_commit=commit,base_archive_sha256=expected_sha256.lower(),application_version=application_version)
    (output/'release-info.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    (output/'SHA256SUMS.txt').write_text(record['sha256']+'  '+destination.name+'\n',encoding='ascii')
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',required=True);parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--commit',default='unknown')
    parser.add_argument('--base-zip',type=Path);parser.add_argument('--base-sha256')
    parser.add_argument('--base-tag',default='v2026.10.15-r7')
    args=parser.parse_args();tag(args.version)
    if args.base_zip:
        if not args.base_sha256:parser.error('--base-zip requires --base-sha256')
        record=repackage(args.base_zip,args.source,args.out,args.version,args.base_sha256,args.commit)
    else:
        if not re.fullmatch(r'v20\d{2}\.\d{2}\.\d{2}(?:-r[1-9]\d*)?',args.base_tag):parser.error('Invalid base tag')
        release=json.loads(subprocess.check_output(['gh','api',f'repos/{REPOSITORY}/releases/tags/{args.base_tag}'],text=True,encoding='utf8'))
        assets=[asset for asset in release['assets'] if re.fullmatch(r'MTG_Cube_Builder-Windows-x64-20\d{6}(?:-r[1-9]\d*)?\.zip',asset['name']) and asset['state']=='uploaded']
        if len(assets)!=1 or not assets[0].get('digest','').startswith('sha256:'):raise ValueError('基版本附件不唯一或缺少 GitHub 校验值')
        asset=assets[0]
        with tempfile.TemporaryDirectory(prefix='cube-release-base-') as folder:
            subprocess.run(['gh','release','download',args.base_tag,'--repo',REPOSITORY,'--pattern',asset['name'],'--dir',folder],check=True)
            record=repackage(Path(folder)/asset['name'],args.source,args.out,args.version,asset['digest'][7:],args.commit)
    print(json.dumps(record,ensure_ascii=True),flush=True)


if __name__=='__main__':main()
