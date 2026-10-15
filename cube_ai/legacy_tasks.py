"""Explicit stop bridge for an older server belonging to this exact workspace."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.request
from .launcher import PORTS,health,port_free

_lock=threading.Lock();_cached=(0,[])


def discover():
    global _cached
    with _lock:
        if time.monotonic()-_cached[0]<3:return list(_cached[1])
        found=[]
        for port in PORTS:
            if port_free(port):continue
            data=health(port)
            if not data or data['pid']==os.getpid() or data.get('task_controls'):continue
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/jobs',timeout=.5) as response:jobs=json.loads(response.read(128000))
                active=[j for j in jobs if j.get('state') in {'queued','running'}]
                if active:found.append(dict(id=f'legacy_{port}',operation='legacy',state='running',legacy=True,controllable=True,
                    progress=f'旧后台有 {len(active)} 个任务：'+str(active[-1].get('progress','运行中')),
                    note='旧后台不支持暂停。强制结束会关闭这个旧后台及其全部任务，已保存的文件保留。'))
            except (OSError,ValueError,TypeError):continue
        _cached=(time.monotonic(),found);return list(found)


def stop(id_):
    global _cached
    try:port=int(id_.removeprefix('legacy_'))
    except (ValueError,AttributeError):raise ValueError('旧任务编号无效')
    if port not in PORTS:raise ValueError('旧任务入口无效')
    data=health(port)
    if not data or data.get('task_controls') or data['pid']==os.getpid():raise ValueError('旧后台已退出或身份不符，未结束任何进程')
    if os.name!='nt':raise ValueError('旧版任务结束入口当前仅支持 Windows')
    # Pin the original process handle while validating its executable identity.
    import ctypes,sys
    from ctypes import wintypes as w
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];api.OpenProcess.restype=w.HANDLE
    api.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
    api.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)];api.CloseHandle.argtypes=[w.HANDLE]
    handle=api.OpenProcess(0x1000,False,data['pid'])
    if not handle:raise ValueError('无法确认旧后台身份')
    try:
        buffer=ctypes.create_unicode_buffer(32768);size=w.DWORD(len(buffer));exit_code=w.DWORD()
        if not api.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):raise ValueError('无法确认旧后台程序')
        expected=Path(sys.executable).resolve()
        if expected.name.lower()=='pythonw.exe':expected=expected.with_name('python.exe')
        if Path(buffer.value).resolve()!=expected:raise ValueError('旧后台的运行环境不同，未结束任何程序')
        if not api.GetExitCodeProcess(handle,ctypes.byref(exit_code)) or exit_code.value!=259:raise ValueError('旧后台已结束')
        subprocess.run(['taskkill.exe','/PID',str(data['pid']),'/T','/F'],check=True,capture_output=True,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=15)
    finally:api.CloseHandle(handle)
    _cached=(0,[])
    return dict(id=id_,state='cancelled',progress='旧后台任务已结束；已保存的文件保留，可以在当前页面开始新任务')
