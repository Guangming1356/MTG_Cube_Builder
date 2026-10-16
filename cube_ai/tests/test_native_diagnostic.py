import json
from pathlib import Path

import pytest

from cube_ai import native_diagnostic as diagnostic
from cube_ai.forge import diagnose_log

SYMPTOM='java.lang.NullPointerException: getActivatingPlayer() is null\n at forge.game.ability.effects.CharmEffect.makePossibleOptions(CharmEffect.java:44)'


@pytest.fixture
def saved_case(tmp_path,monkeypatch):
    from cube_ai import forge_worker,tuning
    monkeypatch.setattr(diagnostic,'ROOT',tmp_path)
    monkeypatch.setattr(diagnostic,'DIAGNOSTICS',tmp_path/'private/native-diagnostics')
    monkeypatch.setattr(diagnostic,'configuration',lambda:dict(version='test-fixture',backend='resident'))
    monkeypatch.setattr(tuning,'apply',lambda config:config)
    monkeypatch.setattr(tuning,'engine_key',lambda config:['test-fixture'])
    monkeypatch.setattr(forge_worker,'available',lambda:True)
    monkeypatch.setattr(forge_worker,'close_all',lambda:None)
    folder=tmp_path/'private/deck-studies/test_case';(folder/'decks').mkdir(parents=True)
    order=['a','b','c']
    for name in order:(folder/'decks'/(name+'.dck')).write_bytes(('original deck '+name).encode())
    (folder/'original.log').write_text(SYMPTOM,encoding='utf8')
    report=dict(clock_seconds=30,engine={'version':'fixture'},games=[dict(order=order,seed=1937,log='original.log',outcome='engine_error')])
    (folder/'report.json').write_text(json.dumps(report),encoding='utf8')
    return folder


@pytest.mark.parametrize('fallback',[False,True])
def test_replay_preserves_inputs_disables_cache_and_requires_distinct_real_entries(saved_case,monkeypatch,fallback):
    before=(saved_case/'report.json').read_bytes();calls=[]
    def replay(config,decks,order,seed,clock,out,log):
        assert config['cache'] is False and clock==30
        assert all((decks/(name+'.dck')).read_bytes()==(saved_case/'decks'/(name+'.dck')).read_bytes() for name in order)
        calls.append((config['backend'],list(order),seed))
        (out/log).write_text(SYMPTOM,encoding='utf8')
        return dict(outcome='engine_error',diagnostics=diagnose_log(SYMPTOM),log=log,
                    backend='resident-1' if config['backend']=='resident' and not fallback else 'isolated')
    monkeypatch.setattr(diagnostic,'run_battle',replay)
    result=diagnostic.compare_entries('study','test_case',0)
    assert calls==[('resident',['a','b','c'],1937),('isolated',['a','b','c'],1937)]
    assert result['training_samples_added']==0
    assert result['common_error_symptoms']==['null_modal_activator']
    assert result['reproduced_both']==(not fallback) and result['distinct_entries']==(not fallback)
    assert (saved_case/'report.json').read_bytes()==before
    out=diagnostic.DIAGNOSTICS/result['diagnostic_id']
    assert (out/'report.md').is_file() and (out/'evidence.zip').is_file()
    assert json.loads((out/'report.json').read_text(encoding='utf8'))['state']=='done'
    assert not (diagnostic.ROOT/'matches').exists()


@pytest.mark.parametrize('kind,id_,index',[
    ('other','test_case',0),('study','../test_case',0),('study','test_case',True),('study','test_case',-1),('study','test_case',3600)])
def test_replay_rejects_unknown_sources_paths_and_invalid_indices(kind,id_,index):
    with pytest.raises(ValueError):diagnostic.validate_case(kind,id_,index)


def test_replay_rejects_missing_or_unsafe_original_deck_identifiers(saved_case):
    path=saved_case/'report.json';report=json.loads(path.read_text())
    report['games'][0]['order'][0]='../a';path.write_text(json.dumps(report))
    with pytest.raises(ValueError,match='牌组标识'):diagnostic.load_case('study','test_case',0)


def test_modified_deck_cannot_masquerade_as_original_replay(saved_case):
    path=saved_case/'report.json';report=json.loads(path.read_text())
    report['tables']=[dict(policies={'quality':[dict(id='a',export={'sha256':'0'*64})]})]
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError,match='已发生变化'):diagnostic.compare_entries('study','test_case',0)
