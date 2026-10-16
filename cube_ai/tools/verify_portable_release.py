"""Windows acceptance check for a fresh extracted portable release, without AI.

Always test a separate extraction, never repackage the used verification folder.
"""
import argparse
import ast
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request


def request(url,data=None):
    encoded=json.dumps(data).encode() if data is not None else None
    value=urllib.request.Request(url,encoded,{'Content-Type':'application/json'} if encoded is not None else {})
    with urllib.request.urlopen(value,timeout=15) as response:return json.load(response)


def wait_until(probe,timeout=90):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            if value:=probe():return value
        except (OSError,ValueError):pass
        time.sleep(.2)
    raise TimeoutError('便携版验收等待超时')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--fixture',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();root=args.root.resolve();python=root/'运行环境/python/python.exe'
    launch=root/'启动Cube助手.exe';url=None
    def start():
        subprocess.run([str(launch),'--no-browser'],cwd=root,check=True,capture_output=True,timeout=90)
        connection=json.loads((root/'cube_ai/runtime/entrance.json').read_text(encoding='utf8'))
        address=connection['url'];wait_until(lambda:request(address+'api/health'));return address
    try:
        url=start();status=request(url+'api/status')
        expected=next(ast.literal_eval(n.value) for n in ast.parse((root/'cube_ai/__init__.py').read_text(encoding='utf-8-sig')).body
                      if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__version__' for t in n.targets))
        assert status['version']==expected and status.get('workspace_id')
        assert not status['gpt']['configured'] and status['forge']['available']
        for asset in ['workspace.js','tasks-ui.js','deck-study-ui.js','style.css']:
            with urllib.request.urlopen(url+asset,timeout=10) as response:assert response.status==200
        code="from pathlib import Path;import json,sys;from cube_ai.catalog import Catalog;from cube_ai.config import BuildSpec;c=Catalog();rows,unknown=c.parse(Path(sys.argv[1]).read_text(encoding='utf-8-sig'));assert not unknown;print(json.dumps(dict(operation='stress',cards=rows,spec=BuildSpec().to_dict(),trials=5)))"
        prepared=subprocess.check_output([str(python),'-X','utf8','-c',code,str(args.fixture.resolve())],cwd=root,text=True,encoding='utf8',timeout=90)
        job=request(url+'api/tasks',json.loads(prepared))['job_id']
        request(url+'api/task/control',dict(id=job,action='pause'))
        wait_until(lambda:(j if (j:=request(url+'api/job?id='+job))['state']=='paused' else None))
        try:request(url+'api/shutdown',{})
        except urllib.error.HTTPError as error:assert error.code==400
        else:raise AssertionError('Paused work must block shutdown')
        request(url+'api/task/control',dict(id=job,action='resume'))
        result=wait_until(lambda:(j if (j:=request(url+'api/job?id='+job))['state'] in {'done','failed'} else None))
        assert result['state']=='done',result.get('error')
        assert result['result']['trials']==5 and result['result']['drafted_pool_sizes']=={'60':15}
        request(url+'api/shutdown',{});time.sleep(1);url=start()
        restored=request(url+'api/job?id='+job)
        assert restored['state']=='done' and restored['result']==result['result']
        report=dict(passed=True,application_version=expected,cards=status['cards'],offline_ai=True,forge_available=True,
                    embedded_runtime=True,task_pause_resume=True,shutdown_blocks_live_tasks=True,restart_recovers_result=True)
        args.out.write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report),flush=True)
    finally:
        if url:
            try:request(url+'api/shutdown',{})
            except (OSError,ValueError):
                subprocess.run([str(root/'关闭Cube助手.exe'),'--no-browser'],cwd=root,capture_output=True,timeout=30)


if __name__=='__main__':main()
