"""Allowlisted, credential-free Windows distribution with vendored runtimes.

Run from the project with its development Python after fetching the official
embedded CPython archive, pinned wheels and corresponding GPL source archives.
Nothing from the user's result/state directories enters this package.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import zipfile

SOURCE=Path(__file__).resolve().parents[2]
RELEASES=SOURCE/'发布包'
CACHE=RELEASES/'构建缓存'
PYTHON_VERSION='3.13.16'
RELEASE_DATE='20261016'
RELEASE_TAG=RELEASE_DATE
PYTHON_SHA='97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297'
JAVA_SOURCE_SHA='573057d03584ae793fb7ec9a14c76d826d9187a53efeefd99da47403a5308234'
FORBIDDEN_NAMES={'.env','.git','__pycache__','.pytest_cache','preferences.sqlite','catalog.json',
    'entrance.json','launcher.log','forge.profile.properties','private','ai-settings.bin'}

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def copy_tree(src,dst):
    for p in src.rglob('*'):
        rel=p.relative_to(src)
        if not p.is_file() or any(x in FORBIDDEN_NAMES for x in rel.parts) or p.suffix in {'.pyc','.pyo','.lnk'}:continue
        to=dst/rel;to.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,to)

def unzip_checked(src,dst):
    with zipfile.ZipFile(src) as z:
        for item in z.infolist():
            if not (dst/item.filename).resolve().is_relative_to(dst.resolve()):raise ValueError('归档包含非法路径')
        z.extractall(dst)

def stage():
    required=[CACHE/f'python-{PYTHON_VERSION}-embed-amd64.zip',CACHE/'forge-2.0.15-sources.tar.gz',CACHE/'OpenJDK21U-jdk-sources_21.0.12.1_1.tar.gz']
    missing=[str(p.name) for p in required if not p.is_file()]
    if not list((CACHE/'wheels').glob('*.whl')):missing.append('wheels/*.whl')
    if missing:raise ValueError('缺少构建缓存：'+', '.join(missing)+'。请按 tools/README.md 准备；未创建构建目录。')
    from cube_ai.forge_compat import bundle_files,FORGE_SHA
    native=SOURCE/'cube_ai/native';assets=native/'compatibility/modal-context-1'
    compatibility=bundle_files(assets) if (assets/'manifest.json').is_file() else {}
    runtime_source=SOURCE/'cube_ai/runtime'
    forge_settings=json.loads((runtime_source/'forge.json').read_text(encoding='utf8'))
    for key in ['home','jar','java']:
        value=Path(forge_settings[key])
        if value.is_absolute() or not (runtime_source/value).resolve().is_relative_to(runtime_source.resolve()):
            raise ValueError('便携引擎设置必须使用包内相对路径')
    if compatibility and sha(runtime_source/forge_settings['jar'])!=FORGE_SHA:raise ValueError('Forge 引擎与兼容修复不匹配')
    target=RELEASES/'构建目录'/time.strftime('%Y%m%d_%H%M%S')/'Cube助手'
    target.mkdir(parents=True,exist_ok=False)
    app=target/'cube_ai';app.mkdir()
    for p in (SOURCE/'cube_ai').glob('*.py'):shutil.copyfile(p,app/p.name)
    for name in ('web','knowledge','profiles'):copy_tree(SOURCE/'cube_ai'/name,app/name)
    (app/'native').mkdir()
    for name in ['CubeWorker.java','LICENSE.txt','README.md']:shutil.copyfile(native/name,app/'native'/name)
    for name,data in compatibility.items():
        destination=app/'native/compatibility/modal-context-1'/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
    ui=app/'web/app.js'
    ui.write_text(ui.read_text(encoding='utf8').replace('重启 start.ps1','关闭并重新启动助手'),encoding='utf8')
    data=app/'data';data.mkdir()
    for name in ('card_pool.json','cube_studies.json','learning_sources.json','forge_name_aliases.json'):shutil.copyfile(SOURCE/'cube_ai/data'/name,data/name)
    docs=app/'docs';docs.mkdir()
    for name in ('BRACKETS.md','AI_CONNECTIONS.md','DEBUG_REPORT.md','PARALLEL_EVALUATION.md','SPEED_REPORT.md','SPEED_SEARCH_REPORT.md','DYNAMIC_RESOURCES.md','TASK_CONTROL.md','DECK_POLICY_STUDY.md','NATIVE_DIAGNOSTICS.md','FORGE_COMPATIBILITY.md'):shutil.copyfile(SOURCE/'cube_ai/docs'/name,docs/name)
    for path in (SOURCE/'cube_ai/docs').glob('OPTIMIZATION_*.md'):
        if re.fullmatch(r'OPTIMIZATION_20\d{6}\.md',path.name):shutil.copyfile(path,docs/path.name)
    for name in ('CUBECobra_DESIGN.md','MULTI_SITE_DESIGN.md'):
        to=app/'research'/name;to.parent.mkdir(exist_ok=True);shutil.copyfile(SOURCE/'cube_ai/research'/name,to)
    # The active generator uses only this legacy land recipe, not personal cubes.
    (target/'cube_generator').mkdir()
    land_recipe=json.loads((SOURCE/'cube_generator/edh_600_v4.json').read_text(encoding='utf8'))['lands']
    (target/'cube_generator/edh_600_v4.json').write_text(json.dumps({'lands':land_recipe},ensure_ascii=False,indent=2),encoding='utf8')
    for name in ('wiki','raw','skill','agent','schema'):copy_tree(SOURCE/'magic-skill'/name,target/'magic-skill'/name)
    for name in ('LICENSE','README.md','README_EN.md','AGENTS.md','CONSTITUTION.md'):
        shutil.copyfile(SOURCE/'magic-skill'/name,target/'magic-skill'/name)
    runtime=app/'runtime';runtime.mkdir()
    for name in ('forge-2.0.15','java21'):copy_tree(SOURCE/'cube_ai/runtime'/name,runtime/name)
    keys={'home','java','jar','version','archive_sha256','java_archive_sha256','jar_sha256','source','java_source'}
    (runtime/'forge.json').write_text(json.dumps(dict({k:v for k,v in forge_settings.items() if k in keys},compatibility_mode='auto'),indent=2),encoding='utf8')
    accelerator=runtime/'acceleration';accelerator.mkdir()
    copy_tree(SOURCE/'cube_ai/runtime/acceleration/classes',accelerator/'classes')
    for name in ['nvrtc64_120_0.dll','nvrtc-builtins64_124.dll','License.txt','dependencies.json','native-build.json']:
        shutil.copyfile(SOURCE/'cube_ai/runtime/acceleration'/name,accelerator/name)
    verified=json.loads((SOURCE/'cube_ai/runtime/acceleration/resident-validation.json').read_text(encoding='utf8'))
    verified={k:v for k,v in verified.items() if k not in {'benchmark','validation'}}
    (accelerator/'resident-validation.json').write_text(json.dumps(verified,indent=2),encoding='utf8')
    python=target/'运行环境/python';python.mkdir(parents=True)
    archive=CACHE/f'python-{PYTHON_VERSION}-embed-amd64.zip'
    if sha(archive)!=PYTHON_SHA:raise ValueError('CPython 官方校验值不符')
    unzip_checked(archive,python)
    packages=python/'site-packages';packages.mkdir()
    wheel_records=[]
    for wheel in sorted((CACHE/'wheels').glob('*.whl')):
        unzip_checked(wheel,packages);wheel_records.append(dict(file=wheel.name,sha256=sha(wheel)))
    (python/'python313._pth').write_text('python313.zip\n.\nsite-packages\n..\\..\\\nimport site\n',encoding='ascii')
    third=target/'第三方来源';third.mkdir()
    (target/'入口源码').mkdir()
    shutil.copyfile(SOURCE/'cube_ai/tools/PortableBootstrap.cs',target/'入口源码/PortableBootstrap.cs')
    shutil.copyfile(SOURCE/'cube_ai/tools/portable_entry.pyw',target/'启动.pyw')
    # Scan and normalize only our application text, never third-party licenses.
    for root in (app/'knowledge',app/'docs',app/'research'):
        for p in root.rglob('*.md'):
            text=p.read_text(encoding='utf8').replace('D:\\MTG\\Cube助手','本项目文件夹').replace('D:/MTG/Cube助手','本项目文件夹')
            p.write_text(text,encoding='utf8')
    (app/'requirements.txt').write_text('numpy==2.4.6\nscipy==1.18.0\nrequests==2.34.2\nPyJWT==2.13.0\ncryptography==49.0.0\n',encoding='ascii')
    (app/'.env.example').write_text('OPENAI_API_KEY=\nOPENAI_MODEL=gpt-6-astra\nOPENAI_BASE_URL=https://api.openai.com/v1\nCUBE_API_STYLE=responses\n',encoding='utf8')
    # No local cube copies, histories, preference DB, cached catalog, or .env.
    (target/'先看这里.txt').write_text(README,encoding='utf-8-sig')
    (target/'README.md').write_text(README,encoding='utf8')
    (app/'README.md').write_text('使用说明见上一层的「先看这里.txt」。本副本内置独立运行环境，无需安装 Python 或 Java。\n',encoding='utf8')
    (third/'说明.txt').write_text(NOTICES,encoding='utf-8-sig')
    manifest=dict(version=RELEASE_TAG+'-portable-ai',platform='Windows 10/11 x64',python=PYTHON_VERSION,
        python_sha256=PYTHON_SHA,wheels=wheel_records,
        sources=[dict(file=p.name,sha256=sha(p)) for p in third.glob('*.tar.gz')],
        privacy=dict(user_config_included=False,credentials_included=False,history_included=False,
                     user_cubes_included=False,preferences_included=False),
        card_snapshot=json.loads((data/'card_pool.json').read_text(encoding='utf8'))['date'])
    (target/'发布说明.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print('STAGE',target,flush=True)
    return target

README='''万智牌 Cube 助手 · Windows 便携版

适用于 Windows 10 / 11 的 64 位电脑。

怎么开始
1. 先把整个压缩包解压到一个普通、可写的文件夹。
2. 双击「启动Cube助手.exe」。网页会自动打开。
3. 选择玩法和 Bracket 强度，点击「生成我的 Cube」。

不需要安装 Python、Java、Forge，不需要管理员权限，也不需要配置 GPT。
生成、审计、知识检索、轮抓和 Forge 模拟可在离线状态使用。
首次启动需要解析本地牌库，通常需十几秒，请稍等。
生成的牌表和游戏记录保存在本副本的 cube_ai 文件夹中。

用完之后
关闭网页即可。再次双击会复用本副本的后台。
需要移动文件夹时，先等待生成或对局任务结束，再双击「关闭Cube助手.exe」。
保留整个文件夹移动，不能只复制其中的 EXE。

可选 AI
打开网页左侧「AI 设置」。支持 ChatGPT 会员官方登录预览，以及 OpenAI API、
DeepSeek、通义千问、Gemini、Ollama 和其他兼容服务。保存后立即生效。
Plus / Pro 套餐登录是否可用以官方账户授权为准；API 密钥按各厂商规则单独计费。
本地 Ollama 需要另行安装并下载支持工具调用的模型。本包不含模型权重。
密钥和登录状态仅在自己的电脑保存；分享请发送本压缩包，不要发送使用过的文件夹。
本发布包没有提供任何 API 密钥、旧牌表、旧对局日志或旧偏好数据。
详细操作见 cube_ai/docs/AI_CONNECTIONS.md。

运行加速
运行时页面顶部提供“暂停 / 继续 / 强制结束”。暂停等待当前步骤结束，强制结束回收该任务的计算进程。
刷新网页后仍可控制任务；已完成的记录会保留。用法见 cube_ai/docs/TASK_CONTROL.md。
已内置验证过的常驻 Forge、并行对局、结果缓存和批量评分。
自动对局数会根据剩余内存动态调整；内存紧张时等待在途比赛完成，回收多余的空闲引擎。
训练、独立验证与新旧交叉对局均采用同一资源策略。说明见 cube_ai/docs/DYNAMIC_RESOURCES.md。
新增候选方案多进程比较、未受影响轮抓桌复用、阶段耗时和一键机器测速。
默认完整比较候选；分轮预筛为可选实验方式，可能遗漏好方案。
点击“为这台电脑测速并自动设置”会重复运行固定比赛，需要额外时间。
只有事件一致且完成数量足够的配置才会用于后续任务；测速重复局不计为新增学习数据。
“检查与实战改进”可选快速、标准或深入评估，替换上限可选10/24/48/60张。
默认自动安排资源、选择较快的CPU/GPU计算方式；没有NVIDIA显卡也可正常使用。
GPU评分是可选加速，并不把Forge规则结算搬到GPU。首次编译评分内核会稍慢。
历史对局可训练专用评分模型；没有超过独立验证基准时继续使用固定评分。
学习模型、缓存和对局记录均在用户自己的副本内产生，本包不含旧模型或记录。
详细说明见 cube_ai/docs/SPEED_REPORT.md。
本次更新说明见 cube_ai/docs/SPEED_SEARCH_REPORT.md。

强度说明
Bracket 1–5 是构筑体验目标，每档可微调；详细设置可调整指挥官。
Bracket 3 每副组好的牌最多 3 张 Game Changers，含指挥官和地牌。
默认排除快法术力、已知无限组合和炸地。5 档为实验竞技目标，不认证 cEDH。
卡牌快照不保证完整或自动更新；Forge 也有不支持的牌和 AI 驾驶偏差。

其他系统
此包不支持 macOS、Linux 或 Windows 的 32 位环境。

项目源码在 cube_ai、入口源码与启动.pyw 中；第三方来源、源码和许可证随包保留。
详细强度说明：cube_ai/docs/BRACKETS.md。
'''

NOTICES='''第三方组件与资料

本应用与 Forge 是分别运行的程序。本包保留各组件原有许可证和版权声明。
Magic: The Gathering 名称、卡牌及规则文字属于其相应权利人。本项目不是官方产品。

CPython 3.13.16：运行环境/python/LICENSE.txt（或该目录中的原始许可证文件）。
官方发布页：https://www.python.org/downloads/release/python-31316/
Python 来源压缩包 SHA256 见发布说明.json。

NumPy、SciPy、Requests、PyJWT、Cryptography 与依赖：许可证保留在运行环境/python/site-packages 的各 .dist-info 目录中。
官方 Python 包索引：https://pypi.org/
NumPy / SciPy 所附 BLAS 等组件的声明随其原有文件保留。

Forge 2.0.15：cube_ai/runtime/forge-2.0.15/LICENSE.txt（GPLv3）。
完整对应上游源码：本文件夹中的 forge-2.0.15-sources.tar.gz。
上游及构建定义：https://github.com/Card-Forge/forge/tree/forge-2.0.15
原 Forge JAR 保持不变；安装器 SHA256 和来源见 cube_ai/runtime/forge.json。
可关闭的模式说明兼容覆盖类及完整构建源码：cube_ai/native/compatibility/modal-context-1，GPL-3.0-or-later；精确版本与实战检查范围见 manifest.json。
常驻桥接：cube_ai/native/CubeWorker.java，GPL-3.0-or-later；对应编译类随包提供。
构建来源与校验：cube_ai/runtime/acceleration/native-build.json。ECJ仅为构建依赖，本包不含编译器。

可选 NVIDIA Runtime Compilation 12.4.127：
cube_ai/runtime/acceleration/nvrtc64_120_0.dll、nvrtc-builtins64_124.dll。
完整许可证保留于同目录 License.txt；组件来源和 SHA256 见 dependencies.json。
NVIDIA驱动由用户电脑提供，本包不含驱动。没有兼容驱动时使用CPU。

Eclipse Temurin OpenJDK 21.0.12.1+1：cube_ai/runtime/java21 内的 legal 与 NOTICE。
完整对应官方源码：本文件夹中的 OpenJDK21U-jdk-sources_21.0.12.1_1.tar.gz。
来源：https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.12.1%2B1

magic-skill：MIT，版权与许可证见 magic-skill/LICENSE。
来源：https://github.com/Kuuusoda/magic-skill

本地牌库源自 Scryfall；学习资料的公开来源见网页设计指南和 cube_ai/data/learning_sources.json。
来源与许可证中的第三方作者署名是版权/研究引用，并非此包发送者的个人使用记录。
'''

def privacy_scan(target):
    bad=[];files=0
    # A bare numeric username is also common in public IDs and scientific DLLs.
    # Match its Windows home path rather than unrelated numeric constants.
    needles=[b'Anaconda2026',b'D:\\MTG',b'D:/MTG',b'C:\\Users\\32860',b'C:/Users/32860',b'sk-proj-']
    patterns=needles+[n.decode('ascii').encode('utf-16-le') for n in needles]
    credential=re.compile(rb'(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{25,}|gh[pousr]_[A-Za-z0-9]{25,})')
    for p in target.rglob('*'):
        if not p.is_file():continue
        files+=1
        rel=p.relative_to(target)
        if any(part in FORBIDDEN_NAMES for part in rel.parts) or p.suffix in {'.pyc','.lnk','.pdb'}:bad.append(str(rel));continue
        # Scan arbitrary bytes too, including both encodings used by Windows.
        text_file=p.suffix in {'.py','.md','.json','.txt','.cs','.html','.js','.example'}
        # Source archives and runtime DLLs can be hundreds of MB. Keep only a
        # bounded buffer; overlap covers every fixed needle and the shortest
        # credential match even when it straddles two reads.
        previous=b''
        with p.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):
                data=previous+block
                if any(n in data for n in patterns):
                    bad.append(str(rel)+': local path or credential prefix');break
                if text_file and credential.search(data):
                    bad.append(str(rel)+': credential-like string');break
                previous=data[-256:]
    if bad:raise ValueError('发布隐私扫描失败：'+str(bad[:20]))
    return dict(files=files,private_patterns_found=0,state_files_included=0)

def package(target):
    import gzip
    for name in ['启动Cube助手.exe','关闭Cube助手.exe']:
        if not (target/name).is_file() or (target/name).stat().st_size<4096:raise ValueError('缺少已编译的一键入口：'+name)
    third=target/'第三方来源'
    for name in ('forge-2.0.15-sources.tar.gz','OpenJDK21U-jdk-sources_21.0.12.1_1.tar.gz'):
        p=CACHE/name
        if not p.is_file() or p.stat().st_size<1000000:raise ValueError('缺少对应第三方源码：'+name)
        if name.startswith('OpenJDK') and sha(p)!=JAVA_SOURCE_SHA:raise ValueError('Java 源码校验失败')
        with gzip.open(p,'rb') as f:
            while f.read(1024*1024):pass
        shutil.copyfile(p,third/name)
    manifest=json.loads((target/'发布说明.json').read_text(encoding='utf8'))
    manifest['sources']=[dict(file=p.name,sha256=sha(p)) for p in third.glob('*.tar.gz')]
    (target/'发布说明.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    privacy=privacy_scan(target)
    (target/'隐私检查.json').write_text(json.dumps(privacy,ensure_ascii=False,indent=2),encoding='utf8')
    dest=RELEASES/('Cube助手-Windows64-便携版-'+RELEASE_TAG+'.zip')
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for p in sorted(target.rglob('*')):
            if p.is_file():
                item=zipfile.ZipInfo('Cube助手/'+p.relative_to(target).as_posix(),date_time=(int(RELEASE_DATE[:4]),int(RELEASE_DATE[4:6]),int(RELEASE_DATE[6:]),0,0,0))
                item.compress_type=zipfile.ZIP_STORED if p.suffix in {'.gz','.zip','.jar','.jpg','.png','.mp3','.ogg'} else zipfile.ZIP_DEFLATED
                with p.open('rb') as source,z.open(item,'w',force_zip64=True) as sink:shutil.copyfileobj(source,sink,1024*1024)
    digest=sha(dest)
    dest.with_suffix('.zip.sha256.txt').write_text(digest+'  '+dest.name+'\n',encoding='utf8')
    print(json.dumps(dict(zip=str(dest),bytes=dest.stat().st_size,sha256=digest,privacy=privacy),ensure_ascii=False),flush=True)
    return dest

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',required=True,help='YYYYMMDD or YYYYMMDD-rN; use a new version for every release')
    parser.add_argument('--package',type=Path,help='Package a previously staged and compiled directory')
    args=parser.parse_args()
    if not re.fullmatch(r'20\d{6}(?:-r[1-9]\d*)?',args.version):parser.error('版本需为 YYYYMMDD 或 YYYYMMDD-rN')
    RELEASE_TAG=args.version;RELEASE_DATE=args.version[:8]
    if args.package:package(args.package.resolve())
    else:stage()
