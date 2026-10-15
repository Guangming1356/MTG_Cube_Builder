"""Isolated, checksum-verified installation of official Forge and Java binaries."""
import hashlib
import json
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path
from .config import ROOT

RUNTIME=ROOT/'runtime'
VERSION='2.0.15'
FORGE_URL=f'https://github.com/Card-Forge/forge/releases/download/forge-{VERSION}/forge-installer-{VERSION}.tar.bz2'
FORGE_SHA='4468f182b60f6ca62d89697baa208981085af744f116781af751c611826db600'
JAVA_URL='https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/OpenJDK21U-jre_x64_windows_hotspot_21.0.12.1_1.zip'
JAVA_SHA='d35f31e712f0fcf6ac5a093edc90204fbff22f720ba3950bd09d331d5e621636'

def sha256(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def download(url,path,checksum,progress):
    if path.is_file() and sha256(path)==checksum:return
    progress('下载官方运行时：'+path.name)
    curl=shutil.which('curl.exe') or shutil.which('curl')
    if not curl:raise ValueError('请安装 curl，或将官方压缩包放入 cube_ai/runtime/downloads')
    args=[curl,'--fail','--location','--silent','--show-error','--retry','3','--max-time','2400']
    if Path(curl).name.lower()=='curl.exe':args+=['--ssl-no-revoke']
    subprocess.run(args+[url,'--output',str(path)],check=True,timeout=2500)
    if sha256(path)!=checksum:raise ValueError('运行时 SHA256 不符；未执行或解压该文件')

def write_profile(home):
    # Java Properties reads Unicode through escapes, including Chinese folder names.
    def escaped(path):
        return ''.join(c if ord(c)<128 else f'\\u{ord(c):04x}' for c in path.as_posix())
    profile = home/'forge.profile.properties'
    content = f'userDir={escaped(RUNTIME / "userdata")}\ncacheDir={escaped(RUNTIME / "cache")}\n'
    if not profile.exists() or profile.read_bytes() != content.encode('ascii'):
        profile.write_text(content,encoding='ascii')

def install(progress=print):
    if __import__('sys').platform!='win32':raise ValueError('自动安装支持 Windows；其它平台请配置 CUBE_FORGE_HOME 与 CUBE_FORGE_JAVA')
    downloads=RUNTIME/'downloads';downloads.mkdir(parents=True,exist_ok=True)
    forge_file=downloads/f'forge-installer-{VERSION}.tar.bz2';java_file=downloads/'java21.zip'
    download(FORGE_URL,forge_file,FORGE_SHA,progress)
    download(JAVA_URL,java_file,JAVA_SHA,progress)
    forge=RUNTIME/f'forge-{VERSION}';java=RUNTIME/'java21'
    if not (forge/'.installed').is_file():
        progress('校验完成，解压 Forge（无需牌图下载）')
        forge.mkdir(exist_ok=True)
        with tarfile.open(forge_file,'r:bz2') as archive:archive.extractall(forge,filter='data')
        (forge/'.installed').write_text(FORGE_SHA,encoding='ascii')
    if not (java/'.installed').is_file():
        java.mkdir(exist_ok=True)
        with zipfile.ZipFile(java_file) as archive:
            for item in archive.infolist():
                if not (java/item.filename).resolve().is_relative_to(java.resolve()):raise ValueError('Java 压缩包路径非法')
            archive.extractall(java)
        (java/'.installed').write_text(JAVA_SHA,encoding='ascii')
    java_exe=next(java.rglob('java.exe'))
    jars=list(forge.rglob('forge-gui-desktop-*.jar'))
    if not jars:raise ValueError('官方压缩包未包含 Forge Desktop jar；请检查安装包布局')
    jar=next((p for p in jars if 'jar-with-dependencies' in p.name),jars[0])
    home=jar.parent
    # Configure only our new checkout; the user's existing Forge profile is untouched.
    profile=home/'forge.profile.properties'
    if not profile.exists():write_profile(home)
    config=dict(home=home.relative_to(RUNTIME).as_posix(),java=java_exe.relative_to(RUNTIME).as_posix(),jar=jar.relative_to(RUNTIME).as_posix(),version=VERSION,
        archive_sha256=FORGE_SHA,java_archive_sha256=JAVA_SHA,jar_sha256=sha256(jar),
        source=FORGE_URL,java_source=JAVA_URL)
    (RUNTIME/'forge.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    progress('Forge 与 Java 已安装，配置保存在 cube_ai/runtime/forge.json')
    return config
