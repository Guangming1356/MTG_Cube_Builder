"""A stable candidate cannot repair an unstable calibration control."""
import json
from pathlib import Path
import pytest

from cube_ai import tuning


def test_unstable_control_stops_before_other_settings_and_keeps_profile(tmp_path,monkeypatch):
    from cube_ai import forge,experiment
    from cube_ai.catalog import Catalog
    from cube_ai.config import BuildSpec
    decks=tmp_path/'decks';decks.mkdir()
    for name in ['a','b','c']:(decks/(name+'.dck')).write_text(name)
    monkeypatch.setattr(experiment,'execution_resources',lambda:dict(maximum=2))
    monkeypatch.setattr(forge,'configuration',lambda:dict(backend='resident'))
    monkeypatch.setattr(forge,'card_index',lambda config:{})
    monkeypatch.setattr(tuning,'engine_key',lambda config:['fixture-engine'])
    monkeypatch.setattr(tuning,'profile_choices',lambda requested,best,jvm,snapshot=None:(list(requested),dict(capacity=2)))
    calls=[]
    def battle(config,folder,order,seed,clock,out,log):
        calls.append((out.name,seed))
        # A later setting matches the first control perfectly; it must not be
        # adopted when the repeated unchanged control itself deals other damage.
        amount=4 if out.name=='default_1_1' and seed==0 else 3
        (out/log).write_text(f'Turn: Turn 1\nDamage: Elf (1) deals {amount} damage to Bear (2).\n',encoding='utf8')
        return dict(outcome='win',winner='a',log=log,backend='resident-test')
    monkeypatch.setattr(forge,'run_battle',battle)
    tuning.PROFILE.write_text('{"keep":"existing measured settings"}',encoding='utf8');before=tuning.PROFILE.read_bytes()
    report=tuning.calibrate(Catalog(),[],BuildSpec(),worker_choices=[1,2],jvm_choices=['default'],
                           fixtures=(decks,[dict(order=['a','b','c'],seed=i) for i in range(6)]))
    assert not report['adopted'] and not report.get('recommendation')
    assert len(calls)==12 and len(report['phases'])==1
    assert report['reference_check']['status']=='unstable' and report['reference_check']['unstable_games']==[0]
    assert report['stopped_early'] and tuning.PROFILE.read_bytes()==before


@pytest.mark.parametrize('change,status',[
    ('consistent','consistent'),('one','insufficient_repetitions'),
    ('abnormal','abnormal'),('fallback','backend_mismatch'),
    ('memory','incomplete'),('empty','incomplete'),('cache','backend_mismatch'),
])
def test_reference_check_distinguishes_unusable_controls(change,status):
    normal=dict(outcome='win',winner='a',events_sha256='same')
    phase=dict(workers=1,jvm_profile='default',same_native_backend=True,runs=[[dict(normal)],[dict(normal)]])
    if change=='one':phase['runs'].pop()
    elif change=='abnormal':phase['runs'][1][0]['outcome']='engine_error'
    elif change=='fallback':phase['same_native_backend']=False
    elif change=='memory':phase['resource_interrupted']=True
    elif change=='empty':phase['runs']=[[],[]]
    elif change=='cache':phase['runs'][1][0]['cache_hit']=True
    assert tuning.baseline_check(phase)['status']==status
