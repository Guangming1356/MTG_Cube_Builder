import json
import random
import zipfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch
import pytest
from cube_ai.catalog import Catalog
from cube_ai.config import ROOT, BuildSpec
from cube_ai.draft import draft_pod
from cube_ai.forge import BASICS, card_index, engine_name, parse_log, summarize, write_deck

@pytest.fixture(scope='module')
def real_pod():
    c=Catalog()
    rows,unknown=c.parse((Path(__file__).parent/'fixtures'/'forge_cube.csv').read_text(encoding='utf-8-sig'))
    assert not unknown
    return c,rows,draft_pod(c,rows,BuildSpec(),random.Random(42))

def test_same_table_and_free_basics(real_pod):
    c,rows,pod=real_pod
    assert len(pod['packs'])==30
    pools=[set(d['drafted']) for d in pod['decks']]
    assert all(len(p)==60 for p in pools)
    assert len(set.union(*pools))==180
    for d in pod['decks']:
        assert d['buildable']
        assert len(d['spells'])+len(d['lands'])+sum(d['basics'].values())+1==60
        assert d['land_count']>=22
        assert not set(d['spells']+d['lands']+[d['commander']])-set(d['drafted'])

def test_deck_file_sections_and_any_number_of_basics(real_pod,tmp_path):
    c,_,pod=real_pod;d=dict(pod['decks'][0])
    index={n.casefold():n for n in c.cards};index.update({n.casefold():n for n in BASICS.values()})
    d['spells']=d['spells'][:4];d['lands']=[];d['basics']={d['identity'][0]:55}
    p=tmp_path/'test.dck';v=write_deck(d,p,index,c)
    assert v['main']==59 and v['total']==60
    text=p.read_text();assert '[Commander]\n1 '+d['commander'] in text
    assert '55 '+BASICS[d['identity'][0]] in text
    d['basics']={d['identity'][0]:54}
    with pytest.raises(ValueError,match='60'):write_deck(d,p,index,c)

def test_missing_engine_card_never_substituted(real_pod,tmp_path):
    c,_,pod=real_pod
    with pytest.raises(ValueError,match='Forge 不支持'):write_deck(pod['decks'][0],tmp_path/'none.dck',{},c)

def test_missing_drafted_card_rejected(real_pod,tmp_path):
    c,_,pod=real_pod;d=dict(pod['decks'][0]);d['drafted']=[]
    with pytest.raises(ValueError,match='未抓到'):write_deck(d,tmp_path/'none.dck',{},c)

def test_packaged_card_scripts(tmp_path):
    p=tmp_path/'res'/'cardsfolder';p.mkdir(parents=True)
    with zipfile.ZipFile(p/'cardsfolder.zip','w') as z:z.writestr('a/test.txt','Name:Front\nALTERNATE\nName:Back\n')
    index=card_index(dict(home=str(tmp_path)))
    assert engine_name('Front // Back',index)=='Front'
    assert engine_name('Invented',index) is None

@pytest.mark.parametrize('log,code,timeout,outcome',[
    ('Turn 1\nTurn 38\nGame Result: Game 1 ended in 5000 ms. Ai(2)-p000_s1_BU has won!',0,False,'win'),
    ('Game Result: Game 1 ended in a Draw! Took 900 ms.',0,False,'draw'),
    ('Stopping slow match as draw\nGame Result: Game 1 ended in a Draw! Took 900 ms.',0,False,'engine_timeout'),
    ('java.lang.NullPointerException: test\nGame Result: Game 1 ended in a Draw! Took 900 ms.',0,False,'engine_error'),
    ('Could not load deck - test',0,False,'engine_error'),
    ('startup',1,False,'engine_error'),
    ('startup',0,False,'unrecognized'),
    ('Turn 8',-1,True,'process_timeout'),
])
def test_outcome_parser(log,code,timeout,outcome):
    r=parse_log(log,code,timeout);assert r['outcome']==outcome
    if outcome=='win':assert r['winner']=='p000_s1_BU' and r['engine_seat']==1 and r['turns']==38

def test_failures_excluded_from_observed_win_rates():
    pods=[{'decks':[dict(id='a',identity='UW',buildable=True),dict(id='b',identity='BR',buildable=True),dict(id='c',identity='BG',buildable=True)]}]
    records=[dict(outcome='win',order=['a','b','c'],winner='a',turns=30),
             dict(outcome='engine_timeout',order=['a','b','c'],winner=None,turns=2)]
    s=summarize(records,pods)
    assert s['completed']==1 and s['games']==2 and s['guilds']['UW']['appearances']==1
    assert s['guilds']['UW']['win_rate']==1


def test_engine_diagnostics_explain_failures_without_reclassifying_games_or_blame():
    from cube_ai.forge import diagnose_log
    null='java.lang.NullPointerException: getActivatingPlayer() is null\n at forge.game.ability.effects.CharmEffect.makePossibleOptions(CharmEffect.java:44)'
    result=parse_log(null+'\nGame Result: Game 1 ended in 5000 ms. Ai(1)-a has won!')
    assert result['outcome']=='engine_error' and result['diagnostics'][0]['code']=='null_modal_activator'
    warning='No AI assigned for API: Empower\nNo AI assigned for API: Empower\nGame Result: Game 1 ended in 5000 ms. Ai(1)-a has won!'
    result=parse_log(warning)
    assert result['outcome']=='win' and len(result['diagnostics'])==1 and result['diagnostics'][0]['severity']=='warning'
    assert diagnose_log('java.lang.OutOfMemoryError: Java heap space')[0]['code']=='engine_memory'
    assert diagnose_log('java.util.concurrent.TimeoutException')[0]['code']=='ai_choice_timeout'
    assert not diagnose_log('Stopping slow match as draw\njava.util.concurrent.TimeoutException')
