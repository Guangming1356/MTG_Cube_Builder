import copy
import hashlib
import json
from pathlib import Path

import pytest

from cube_ai import forge,forge_compat as compat


@pytest.fixture
def bundle(tmp_path,monkeypatch):
    folder=tmp_path/'overlay';folder.mkdir();monkeypatch.setattr(compat,'ASSETS',folder)
    data=b'fixture-class-not-executed';class_sha=hashlib.sha256(data).hexdigest();monkeypatch.setattr(compat,'CLASS_SHA',class_sha)
    target=folder/compat.CLASS_PATH;target.parent.mkdir(parents=True);target.write_bytes(data)
    manifest=dict(id=compat.ID,validated=True,forge_sha256=compat.FORGE_SHA,patched_class_sha256=class_sha,
        identity_byte_equal=True,other_methods_byte_equal=True,native_main_class='forge.view.Main',native_add_opens=['java.base/java.lang'])
    raw=json.dumps(manifest).encode();(folder/'manifest.json').write_bytes(raw)
    monkeypatch.setattr(compat,'MANIFEST_SHA',hashlib.sha256(raw).hexdigest())
    jar=tmp_path/'forge.jar';jar.write_bytes(b'fixture')
    config=dict(jar=str(jar),backend='resident',extra_classpath=['stale-unmanaged-path'])
    monkeypatch.setattr(forge,'_file_hash',lambda *args:compat.FORGE_SHA)
    return config,folder


def test_reviewed_overlay_requires_exact_manifest_class_and_jar_without_mutating_config(bundle):
    config,folder=bundle;before=copy.deepcopy(config)
    applied=compat.apply(config,mode='auto')
    assert config==before and applied['compatibility']['active']
    assert applied['extra_classpath']==[str((folder/'classes').resolve())]
    assert compat.signature(applied)==compat.CLASS_SHA
    disabled=compat.apply(config,mode='off')
    assert not disabled['compatibility']['active'] and 'extra_classpath' not in disabled and compat.signature(disabled)==''


def test_wrong_or_unreviewed_assets_are_inert(bundle,monkeypatch):
    config,folder=bundle
    monkeypatch.setattr(compat,'MANIFEST_SHA',None)
    assert compat.apply(config,mode='auto')['compatibility']['reason']=='pending_validation'
    monkeypatch.setattr(compat,'MANIFEST_SHA','0'*64)
    assert compat.apply(config,mode='auto')['compatibility']['reason']=='asset_verification_failed'
    monkeypatch.setattr(compat,'MANIFEST_SHA',hashlib.sha256((folder/'manifest.json').read_bytes()).hexdigest())
    (folder/compat.CLASS_PATH).write_bytes(b'modified')
    assert compat.apply(config,mode='auto')['compatibility']['reason']=='asset_verification_failed'
    assert 'extra_classpath' not in compat.apply(config,mode='auto')


def test_overlay_cannot_be_applied_to_another_forge_build(bundle,monkeypatch):
    config,_=bundle;monkeypatch.setattr(forge,'_file_hash',lambda *args:'another-jar')
    result=compat.apply(config,mode='auto')
    assert not result['compatibility']['active'] and result['compatibility']['reason']=='different_engine'
    assert 'extra_classpath' not in result


def test_compatibility_mode_preserves_other_runtime_settings(tmp_path,monkeypatch):
    from cube_ai import forge_setup
    monkeypatch.setattr(forge_setup,'RUNTIME',tmp_path);monkeypatch.delenv('CUBE_FORGE_COMPAT',raising=False)
    path=tmp_path/'forge.json';path.write_text(json.dumps(dict(home='engine',custom='preserved')))
    compat.set_mode('off');assert json.loads(path.read_text())==dict(home='engine',custom='preserved',compatibility_mode='off')
    with pytest.raises(ValueError):compat.set_mode('unknown')
    monkeypatch.setenv('CUBE_FORGE_COMPAT','off')
    with pytest.raises(ValueError,match='环境变量'):compat.set_mode('auto')


def test_switch_refuses_running_paused_and_learning_tasks_before_writing_settings(monkeypatch):
    from cube_ai import server
    import threading
    from types import SimpleNamespace
    calls=[];monkeypatch.setattr(compat,'set_mode',calls.append)
    app=SimpleNamespace(lock=threading.RLock(),closing=False,jobs={})
    for operation,state in [('forge','running'),('deck-study','paused'),('learn-games','queued'),('optimize','pausing')]:
        app.jobs={'one':dict(operation=operation,state=state)}
        with pytest.raises(ValueError,match='实战或学习任务'):server.Application.set_engine_mode(app,'off')
    assert calls==[]
    app.jobs={};monkeypatch.setattr(server,'forge_status',lambda:dict(available=True))
    assert server.Application.set_engine_mode(app,'off')==dict(available=True) and calls==['off']


def test_patch_is_part_of_worker_calibration_and_game_cache_identities(tmp_path,monkeypatch):
    from cube_ai import forge_worker,tuning
    for name in ['jar','java','a.dck']:(tmp_path/name).write_text(name)
    original=dict(jar=str(tmp_path/'jar'),java=str(tmp_path/'java'),home=str(tmp_path),backend='resident')
    fixed=dict(original,compatibility=dict(active=True,sha256='reviewed-overlay'),extra_classpath=['managed-classes'])
    assert tuning.engine_key(original)!=tuning.engine_key(fixed)
    assert forge_worker.worker_key(original)!=forge_worker.worker_key(fixed)
    calls=[]
    def battle(config,decks,order,seed,clock,out,log):
        calls.append(bool(config.get('extra_classpath')));(out/log).write_text('Game Result: Game 1 ended in 1000 ms. Ai(1)-a has won!')
        return dict(outcome='win',winner='a',wall_seconds=1,log=log)
    monkeypatch.setattr(forge,'_run_battle',battle)
    for config in [original,fixed,original,fixed]:forge.run_battle(config,tmp_path,['a'],42,30,tmp_path,'test.log')
    assert calls==[False,True]
    unmanaged=dict(original,extra_classpath=['unmanaged-classes'])
    for _ in range(2):forge.run_battle(unmanaged,tmp_path,['a'],42,30,tmp_path,'test.log')
    assert calls==[False,True,True,True]


def test_distribution_requires_corresponding_source_and_ignores_unlisted_files(bundle,monkeypatch):
    config,folder=bundle
    manifest=json.loads((folder/'manifest.json').read_text());hashes={}
    for name in compat.SOURCE_FILES:
        path=folder/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'# fixture source\n')
        hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest['source_sha256']=hashes;raw=json.dumps(manifest).encode();(folder/'manifest.json').write_bytes(raw)
    monkeypatch.setattr(compat,'MANIFEST_SHA',hashlib.sha256(raw).hexdigest())
    (folder/'scratch-private.json').write_text('must not ship')
    files=compat.bundle_files(folder)
    assert set(files)==compat.SOURCE_FILES|{'manifest.json',compat.CLASS_PATH}
    (folder/'build/ModalDescriptionPatch.java').write_text('changed')
    with pytest.raises(ValueError,match='源码或二进制校验'):compat.bundle_files(folder)


def test_native_cli_overlay_preserves_manifest_opens_and_original_jar_entry(tmp_path,monkeypatch):
    from types import SimpleNamespace
    calls=[]
    def run(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=b'Game Result: Game 1 ended in 25 ms. Ai(1)-a has won!',returncode=0)
    monkeypatch.setattr(forge.subprocess,'run',run);monkeypatch.setattr(forge,'worker_home',lambda config,out:tmp_path)
    config=dict(java='java',jar='forge.jar',backend='isolated')
    forge._run_battle(config,tmp_path,['a','b','c'],42,30,tmp_path,'original.log')
    fixed=dict(config,extra_classpath=['reviewed-classes'],native_main_class='forge.view.Main',native_add_opens=['java.base/java.lang'])
    forge._run_battle(fixed,tmp_path,['a','b','c'],42,30,tmp_path,'fixed.log')
    assert '-jar' in calls[0] and '-cp' not in calls[0]
    assert '-jar' not in calls[1] and '--add-opens=java.base/java.lang=ALL-UNNAMED' in calls[1]
    import os
    assert calls[1][calls[1].index('-cp')+1]=='reviewed-classes'+os.pathsep+'forge.jar'
    assert calls[0][calls[0].index('sim'):]==calls[1][calls[1].index('sim'):]
