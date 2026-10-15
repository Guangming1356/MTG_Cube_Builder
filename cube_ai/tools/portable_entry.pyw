"""Portable Windows entrance; all configuration belongs to the extracted copy."""
import ctypes
import json
import os
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
os.chdir(BASE)
sys.path.insert(0,str(BASE))
# Avoid silently borrowing credentials/data/runtimes from another installation.
for key in ('OPENAI_API_KEY','OPENAI_MODEL','OPENAI_BASE_URL','CUBE_API_STYLE',
            'CUBE_CARD_POOL','CUBE_FORGE_HOME','CUBE_FORGE_JAVA'):
    os.environ.pop(key,None)

def message(text,error=False):
    ctypes.windll.user32.MessageBoxW(None,text,'万智牌 Cube 助手',0x10 if error else 0x40)

def stop():
    from cube_ai.launcher import find_server
    found=find_server()
    if not found:return
    _,data=found
    from ctypes import wintypes
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];api.OpenProcess.restype=wintypes.HANDLE
    api.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    api.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT];api.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=api.OpenProcess(0x1001,False,int(data['pid']))
    if not handle:raise RuntimeError('无法关闭本副本的后台。请先完成或停止正在运行的任务。')
    try:
        buffer=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(buffer))
        if not api.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):
            raise RuntimeError('无法确认后台程序身份，未关闭任何程序。')
        expected=(BASE/'运行环境/python/python.exe').resolve()
        if Path(buffer.value).resolve()!=expected:raise RuntimeError('后台不属于本便携副本，未关闭任何程序。')
        if not api.TerminateProcess(handle,0):raise RuntimeError('后台未能关闭。')
    finally:api.CloseHandle(handle)

def main():
    try:
        if '--stop' in sys.argv:
            stop();return 0
        from cube_ai.launcher import LaunchLock,launch
        with LaunchLock():result=launch(open_browser='--no-browser' not in sys.argv,timeout=90)
        if sys.stdout:print(json.dumps(result,ensure_ascii=False))
        return 0
    except Exception as error:
        message('Cube 助手暂时没有打开\n\n'+str(error)+'\n\n请先把压缩包完整解压到一个可写文件夹，再双击启动入口。',True)
        return 1

if __name__=='__main__':raise SystemExit(main())
