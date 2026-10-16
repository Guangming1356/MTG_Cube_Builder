"""Task subprocess bootstrap. The parent owns its complete process tree."""
import json
from pathlib import Path
import sys
import time


def main():
    folder=Path(sys.argv[1]);deadline=time.monotonic()+20
    while not (folder/'start').exists():
        if time.monotonic()>deadline:return 2
        time.sleep(.05)
    from .task_control import TaskControl,bind,atomic_json,TaskStopped
    control=TaskControl(folder);bind(control)
    try:
        control.progress('正在准备任务')
        from .server import Application,execute_operation
        from .config import BuildSpec
        from .ai_settings import SettingsStore
        source=json.loads((folder/'input.json').read_text(encoding='utf8'));data=source['request']
        catalog=None
        if data.get('operation') in {'stress','forge','calibrate','deck-study','diagnose-game'} and source.get('catalog'):
            from .catalog import Catalog
            snapshot=source['catalog']
            catalog=Catalog.from_records(snapshot['cards'],snapshot['snapshot'],snapshot['signature'])
        app=Application(catalog=catalog,ai_store=SettingsStore(Path(source['settings_path'])) if source.get('settings_path') else None,isolated_jobs=False)
        try:
            rows,unknown=app.rows(data)
            if unknown:raise ValueError('任务包含未确认的牌名')
            value=execute_operation(app,data.get('operation','build'),BuildSpec.from_dict(data.get('spec')),rows,data,control.progress)
            control.checkpoint();result=dict(state='done',progress='完成',result=value)
        finally:app.executor.shutdown(wait=False,cancel_futures=True)
    except TaskStopped:result=dict(state='cancelled',progress='已强制结束')
    except Exception as error:result=dict(state='failed',progress='任务未完成',error=str(error))
    atomic_json(folder/'result.json',result)
    # The parent needs only lifecycle state. Full tables/traces stay on disk and
    # are loaded only when a user opens this result, including before a restart.
    atomic_json(folder/'completion.json',{k:v for k,v in result.items() if k!='result'})
    return 0


if __name__=='__main__':raise SystemExit(main())
