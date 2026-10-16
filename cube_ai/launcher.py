"""Windows double-click entrance. No console, administrator rights or shell policy changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from .config import ROOT, WORKSPACE

APP_ID='mtg-cube-assistant'
WORKSPACE_ID=hashlib.sha256(str(WORKSPACE.resolve()).casefold().encode()).hexdigest()[:16]
PORTS=range(8765,8781)

def health(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=.6) as response:
            data=json.loads(response.read(4096))
        return data if data.get('app')==APP_ID and data.get('workspace')==WORKSPACE_ID else None
    except (OSError,ValueError,urllib.error.URLError):return None

def port_free(port):
    with socket.socket() as sock:
        try:sock.bind(('127.0.0.1',port));return True
        except OSError:return False

def find_server():
    # Reuse only the server belonging to this project, never an unrelated web app.
    older=None
    for port in PORTS:
        if port_free(port):continue
        if data:=health(port):
            if data.get('task_controls'):return port,data
            if older is None:older=(port,data)
    return older

def load_env():
    allowed={'OPENAI_API_KEY','OPENAI_MODEL','OPENAI_BASE_URL','CUBE_API_STYLE','CUBE_CARD_POOL','CUBE_FORGE_HOME','CUBE_FORGE_JAVA','CUBE_FORGE_COMPAT'}
    path=ROOT/'.env'
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' not in line or line.lstrip().startswith('#'):continue
            key,value=line.split('=',1);key=key.strip()
            if key in allowed:os.environ[key]=value.strip().strip('"').strip("'")

def start_server(port):
    runtime=ROOT/'runtime';runtime.mkdir(exist_ok=True)
    executable=Path(sys.executable)
    if executable.name.lower()=='pythonw.exe':executable=executable.with_name('python.exe')
    with (runtime/'launcher.log').open('a',encoding='utf-8') as log:
        log.write('\n启动 Cube 助手 '+time.strftime('%Y-%m-%d %H:%M:%S')+'\n');log.flush()
        process=subprocess.Popen([str(executable),'-X','utf8','-m','cube_ai','serve','--port',str(port)],
            cwd=str(WORKSPACE),stdin=subprocess.DEVNULL,stdout=log,stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    return process

def launch(open_browser=True,timeout=45):
    load_env()
    found=find_server()
    # Upgrade alongside a busy older server. Its tasks remain visible and can be
    # explicitly stopped from the new task panel; never kill them on launch.
    if found and not found[1].get('task_controls'):found=None
    reused=bool(found)
    if not found:
        port=next((p for p in PORTS if port_free(p)),None)
        if port is None:raise RuntimeError('可用入口正被其他程序占用。请稍后再试。')
        process=start_server(port);deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if data:=health(port):found=(port,data);break
            if process.poll() is not None:
                raise RuntimeError('后台未能启动。请保留 cube_ai\\runtime\\launcher.log，方便排查 Python 或依赖问题。')
            time.sleep(.3)
        if not found:raise RuntimeError('首次载入超过等待时间。请过一会儿再次双击入口；程序会尝试连接正在启动的服务。')
    port,data=found
    result=dict(url=f'http://127.0.0.1:{port}/',reused=reused,pid=data.get('pid'),workspace=WORKSPACE_ID)
    (ROOT/'runtime').mkdir(exist_ok=True)
    (ROOT/'runtime'/'entrance.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    if open_browser and not webbrowser.open(result['url']):
        raise RuntimeError('服务已启动，但浏览器未能自动打开。请在浏览器输入：'+result['url'])
    return result

class LaunchLock:
    """Serialize simultaneous double clicks using a per-workspace Windows mutex."""
    def __enter__(self):
        self.handle=None
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes
            self.api=ctypes.WinDLL('kernel32',use_last_error=True)
            self.api.CreateMutexW.argtypes=[wintypes.LPVOID,wintypes.BOOL,wintypes.LPCWSTR]
            self.api.CreateMutexW.restype=wintypes.HANDLE
            self.api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
            self.api.ReleaseMutex.argtypes=[wintypes.HANDLE];self.api.CloseHandle.argtypes=[wintypes.HANDLE]
            self.handle=self.api.CreateMutexW(None,False,'Local\\MTGCubeEntrance_'+WORKSPACE_ID)
            if not self.handle:raise RuntimeError('无法建立启动锁。请重新双击入口。')
            if self.api.WaitForSingleObject(self.handle,55000) not in {0,128}:
                self.api.CloseHandle(self.handle);self.handle=None
                raise RuntimeError('另一个入口正在启动，请稍后再试。')
        return self
    def __exit__(self,*args):
        if self.handle:self.api.ReleaseMutex(self.handle);self.api.CloseHandle(self.handle)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    try:
        with LaunchLock():result=launch(not args.no_browser)
        if args.no_browser:print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        message='Cube 助手暂时没有打开\n\n'+str(error)+'\n\n你的牌表与记录仍保存在项目文件夹。'
        if os.name=='nt' and not args.no_browser:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,message,'万智牌 Cube 助手',0x10)
        elif sys.stderr:print(message,file=sys.stderr)
        return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
