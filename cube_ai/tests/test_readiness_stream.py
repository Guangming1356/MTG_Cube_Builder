"""Readiness observations must not change drafts, and need only eleven cards."""
import math,random
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from cube_ai.config import BuildSpec,GUILDS
from cube_ai.draft import (READINESS_STREAM,OPENING_SAMPLER,_readiness_rng,
    deal,draft_pod,opening_test,stress_test)


@pytest.fixture(scope='module')
def fixture(tmp_path_factory):
    from pathlib import Path
    from cube_ai.catalog import Catalog
    from cube_ai.engine import build
    from cube_ai.feedback import FeedbackStore
    catalog=Catalog();rows,unknown=catalog.parse((Path(__file__).parent/'fixtures/forge_cube.csv').read_text(encoding='utf-8-sig'))
    assert not unknown
    classic=build(catalog,BuildSpec.from_dict(dict(mode='classic')),store=FeedbackStore(tmp_path_factory.mktemp('stream')/'preferences.sqlite'))['cards']
    return catalog,rows,classic


def physical(pod):
    keys=['seat','guild','buildable','commander','identity','drafted','spells','lands','basics','land_count']
    return dict(packs=pod['packs'],decks=[{key:d.get(key) for key in keys} for d in pod['decks']])


@pytest.mark.parametrize('mode',['commander','classic'])
def test_changing_readiness_sample_count_preserves_sequential_tables(fixture,mode):
    catalog,commander,classic=fixture;rows=commander if mode=='commander' else classic
    spec=BuildSpec.from_dict(dict(mode=mode,deck_policy='balanced'));results={};states={}
    for hands in [0,1,40,400]:
        rng=random.Random(378822);results[hands]=[];states[hands]=[]
        for _ in range(3):
            results[hands].append(physical(draft_pod(catalog,rows,spec,rng,readiness_hands=hands)))
            states[hands].append(rng.getstate())
    for hands in [1,40,400]:
        assert results[hands]==results[0] and states[hands]==states[0]


@pytest.mark.parametrize('mode',['commander','classic'])
def test_readiness_does_not_advance_beyond_dealing_when_preferences_are_fixed(fixture,mode):
    catalog,commander,classic=fixture;rows=commander if mode=='commander' else classic;spec=BuildSpec.from_dict(dict(mode=mode))
    before=random.Random(37);actual=random.Random(37);deal(catalog,rows,spec,before)
    prefs=[GUILDS[i%len(GUILDS)] for i in range(spec.players)]
    draft_pod(catalog,rows,spec,actual,prefs,readiness_hands=100)
    assert actual.getstate()==before.getstate()


def test_readiness_generators_are_reproducible_and_separate_by_seat():
    rng=random.Random(3737);before=rng.getstate()
    a=_readiness_rng(rng,0);b=_readiness_rng(rng,0);other=_readiness_rng(rng,1)
    assert a.getstate()==b.getstate() and a.getstate()!=other.getstate() and rng.getstate()==before
    assert [a.random() for _ in range(8)]==[b.random() for _ in range(8)]


def test_opening_samples_only_the_observed_prefix_and_excludes_commander(fixture):
    catalog,rows,_=fixture;deck=draft_pod(catalog,rows,BuildSpec(),random.Random(1937),readiness_hands=0)['decks'][0]
    class Recording(random.Random):
        def __init__(self):super().__init__(37);self.calls=[]
        def sample(self,population,k):
            self.calls.append((len(population),k));assert all(c['name']!=deck['commander'] for c in population)
            return super().sample(population,k)
    rng=Recording();result=opening_test(catalog,deck['spells'],deck['lands'],deck['identity'],59,rng,hands=5,commander=deck['commander'])
    assert rng.calls==[(59,11)]*5
    assert result['sampling_version']==OPENING_SAMPLER and result['cards_per_hand']==11 and result['hands']==5


def test_uniform_prefix_agrees_with_exact_hypergeometric_readiness():
    # Twenty distinct cards: four Islands, four Forests, twelve {U}{U} spells.
    cards={f'Spell {i}':dict(name=f'Spell {i}',kind='sorcery',mana_cost='{U}{U}') for i in range(12)}
    lands=[]
    for i in range(8):
        name=f'Land {i}';lands.append(name);cards[name]=dict(name=name,kind='land',fixing=['U' if i<4 else 'G'])
    result=opening_test(SimpleNamespace(cards=cards),[f'Spell {i}' for i in range(12)],lands,'GU',20,random.Random(37037),hands=20000)
    for turn in range(2,5):
        seen=7+turn
        expected=sum(math.comb(4,k)*math.comb(16,seen-k) for k in range(2,5))/math.comb(20,seen)
        assert abs(result['ready_by_turn'][str(turn)]-expected)<.015
    opening=sum(math.comb(8,k)*math.comb(12,7-k) for k in range(2,5))/math.comb(20,7)
    assert result['ready_by_turn']['1']==0 and abs(result['opening_2_to_4_lands']-opening)<.015


@pytest.mark.parametrize('hands',[-1,None,1.5,True,'40'])
def test_invalid_sample_counts_have_a_clear_error(hands):
    with pytest.raises(ValueError,match='非负整数'):opening_test(SimpleNamespace(cards={}),[],[],'U',20,random.Random(0),hands=hands)


def test_empty_sampling_keeps_basics_without_needing_an_eleven_card_deck():
    result=opening_test(SimpleNamespace(cards={}),[],[],'U',5,random.Random(0),hands=0)
    assert result['basics']=={'U':5} and result['ready_by_turn']=={} and result['hands']==0
    with pytest.raises(ValueError,match='11 张'):opening_test(SimpleNamespace(cards={}),[],[],'U',5,random.Random(0),hands=1)


def test_streamed_report_counts_failed_decks_violations_and_components():
    spec=BuildSpec.from_dict(dict(bracket=3));pods=[]
    for table in range(5):
        decks=[]
        for seat,guild in enumerate(['UW','BR','UW']):
            good=not (table==0 and seat==0)
            d=dict(seat=seat,guild=guild,buildable=good,drafted=['card']*60,commander=f'Commander {table}-{seat}')
            if good:d.update(ready=dict(ready_by_turn={'1':.25,'2':.5,'3':.75,'4':1.}),
                bracket=dict(violations=['problem'] if table==1 and seat==1 else [],game_changers=['a','b'] if seat==1 else []),
                design=dict(incomplete_packages=['package'] if table==2 and seat==2 else []))
            decks.append(d)
        pods.append(dict(packs=[[f'table {table}']],decks=decks))
    with patch('cube_ai.engine.audit',return_value=dict(hard_errors=0)),patch('cube_ai.draft.draft_pod',side_effect=pods):
        result=stress_test(None,[],spec,trials=5)
    assert result['buildable_rate']==round(14/15,3) and result['drafted_pool_sizes']=={60:15}
    assert result['guilds']['UW']['decks']==10 and result['guilds']['UW']['buildable_rate']==.9
    assert result['guilds']['UW']['ready_by_turn']=={'1':.25,'2':.5,'3':.75,'4':1.}
    assert result['guilds']['BR']['decks']==5 and result['guilds']['GU']['decks']==0
    assert result['bracket_check']['decks_checked']==14 and result['bracket_check']['violations']==1
    assert result['bracket_check']['max_deck_game_changers']==2
    assert result['component_check']['decks_with_incomplete_packages']==1 and result['component_check']['decks']==14
    assert result['packs']==[['table 0']] and len(result['examples'])==3
    assert result['examples'][0]['commander']=='Commander 0-1' and all('ready' not in d for d in result['examples'])
    assert result['mana_model']['stream_version']==READINESS_STREAM and result['mana_model']['sampling_version']==OPENING_SAMPLER
