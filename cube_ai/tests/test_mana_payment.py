"""Independent explicit-payment oracle and readiness integration boundaries."""
import itertools,random,re
from types import SimpleNamespace
import pytest
from cube_ai.mana import affordable,land_source_mask,MODEL_VERSION
from cube_ai.draft import opening_test


def reference(cost,sources,max_sources,life_budget):
    """Enumerate symbol payments then inject each mana unit into a source.

    This intentionally does not share the production mask/neighborhood logic.
    Small bounded inputs make a direct resource-assignment oracle practical.
    """
    if not cost:return False
    tokens=re.findall(r'\{([^}]+)\}',cost)
    if ''.join('{'+t+'}' for t in tokens)!=cost:return False
    choices=[]
    for token in tokens:
        if token.isdigit():choices.append([(tuple(['any']*int(token)),0)])
        elif token=='X':choices.append([(('any',),0)])
        elif token in 'WUBRGCS' and len(token)==1:choices.append([((token,),0)])
        else:
            parts=token.split('/')
            if parts[0]=='2' and len(parts)==2 and parts[1] in 'WUBRG':choices.append([(('any','any'),0),((parts[1],),0)])
            elif parts[-1]=='P' and all(p in 'WUBRG' and len(p)==1 for p in parts[:-1]) and len(parts) in {2,3}:
                choices.append([((),2)]+[((color,),0) for color in parts[:-1]])
            elif len(parts)==2 and all(p in 'WUBRGC' and len(p)==1 for p in parts):choices.append([((color,),0) for color in parts])
            else:return False
    usable=[set(s) for s in sources if set(s)&set('WUBRGC')]
    for payments in itertools.product(*choices):
        if sum(p[1] for p in payments)>life_budget:continue
        units=sum((p[0] for p in payments),())
        if len(units)>min(len(usable),max_sources):continue
        for assignment in itertools.permutations(range(len(usable)),len(units)):
            if all(unit=='any' or unit in usable[source] for unit,source in zip(units,assignment)):return True
    return False


@pytest.mark.parametrize('cost,sources,limit,life,expected',[
    ('',[],0,0,False),('{0}',[],0,0,True),('{1}',[set()],1,0,False),
    ('{2/W}',[{'U'},{'U'}],2,0,True),('{2/W}',[{'U'}],1,0,False),('{2/W}',[{'W'}],1,0,True),
    ('{2/W}{2/W}',[{'W'},{'U'},{'U'}],3,0,True),('{2/W}{2/W}',[{'U'},{'U'},{'U'}],3,0,False),
    ('{X}{X}',[{'U'}],1,0,False),('{X}{X}',[{'U'},{'U'}],2,0,True),
    ('{X}{X}{X}',[{'U'},{'U'}],2,0,False),
    ('{W}{U}',[{'W','U'}],2,0,False),('{W}{W}',[{'W','U'},{'U'}],2,0,False),
    ('{W}{U}',[{'W','U'},{'W','U'}],2,0,True),
    ('{W/U}{U}{U}',[{'W'},{'U'},{'G'},{'G'}],3,0,False),
    ('{C/W}',[{'C'}],1,0,True),('{C}',[{'W','U'}],1,0,False),
    ('{W/P}',[],0,0,False),('{W/P}',[],0,1,False),('{W/P}',[],0,2,True),
    ('{W/P}{W/P}',[{'W'}],1,2,True),('{W/P}{W/P}',[],0,3,False),
    ('{G/U/P}',[{'U'}],1,0,True),('{G/U/P}',[],0,2,True),
    ('{S}',[{'U'}],1,0,False),('{S}',[{'S'}],1,0,False),('{S}',[{'S','U'}],1,0,True),
    ('{S}{U}',[{'S','U'}],2,0,False),('{S}{U}',[{'S','W'},{'U'}],2,0,True),
    ('{S}{U}',[{'S','U'},{'W'}],2,0,False),('{1}',[{'S','U'}],1,0,True),
    ('{1}',[{'G'},{'G'}],0,0,False),('{Q}',[{'G'}],1,0,False),('1',[],0,0,False),
    ('{W}junk',[{'W'}],1,0,False),('{W/P}',[{'W'}],1,0,True),
])
def test_payment_boundaries(cost,sources,limit,life,expected):
    assert affordable(cost,sources,max_sources=limit,life_budget=life) is expected
    assert reference(cost,sources,limit,life) is expected


def test_seeded_small_payments_agree_with_independent_enumeration():
    rng=random.Random(36036)
    tokens=['0','1','2','W','U','B','R','G','C','S','X','W/U','U/B','C/W','2/W','2/B','W/P','G/U/P']
    types=[set(),{'W'},{'U'},{'B'},{'G'},{'C'},{'W','U'},{'U','B'},{'S','U'},{'S','W'},set('WUBRGC')]
    for _ in range(6000):
        cost=''.join('{'+rng.choice(tokens)+'}' for _ in range(rng.randint(1,4)))
        sources=[rng.choice(types) for _ in range(rng.randrange(6))];limit=rng.randrange(6);life=rng.randrange(7)
        assert affordable(cost,sources,max_sources=limit,life_budget=life)==reference(cost,sources,limit,life),(cost,sources,limit,life)


def test_snow_source_requires_both_snow_supertype_and_mana_production():
    regular=dict(type='Basic Land — Island',fixing=['U']);snow=dict(regular,type='Basic Snow Land — Island')
    assert land_source_mask(snow)!=land_source_mask(regular)
    assert land_source_mask(dict(type='Snow Land',fixing=[]))==0


def example_catalog(cost,land_type='Land',fixing=('U',)):
    return SimpleNamespace(cards={'Spell':dict(name='Spell',kind='sorcery',mana_cost=cost),
        'Land':dict(name='Land',kind='land',type=land_type,fixing=list(fixing))})


@pytest.mark.parametrize('cost,expected',[('',0),('{0}',1),('{S}',0),('{X}{X}{U}',None)])
def test_fixed_readiness_does_not_confuse_absent_free_and_snow_costs(cost,expected):
    catalog=example_catalog(cost)
    class Fixed:
        def sample(self,deck,count):return deck
    result=opening_test(catalog,['Spell']*7,['Land']*4,'U',11,Fixed(),hands=1)
    assert result['model_version']==MODEL_VERSION
    assert result['ready_by_turn']==({'1':0,'2':0,'3':1,'4':1} if expected is None else {str(t):expected for t in range(1,5)})


@pytest.mark.parametrize('cost,expected,calls',[
    ('{0}',{'1':1,'2':1,'3':1,'4':1},1),
    ('{X}{X}{U}',{'1':0,'2':0,'3':1,'4':1},15),
])
def test_readiness_stays_true_after_first_affordable_turn(monkeypatch,cost,expected,calls):
    import cube_ai.draft as draft
    catalog=example_catalog(cost)
    class Fixed:
        def sample(self,deck,count):return deck
    original=draft._affordable_masks
    observed=[]
    def counted(*args,**kwargs):
        observed.append(kwargs['max_sources'])
        return original(*args,**kwargs)
    monkeypatch.setattr(draft,'_affordable_masks',counted)
    result=opening_test(catalog,['Spell']*7,['Land']*4,'U',11,Fixed(),hands=1)
    assert result['ready_by_turn']==expected
    assert len(observed)==calls


def test_opening_uses_snow_provenance_and_explicit_starting_life():
    class Fixed:
        def sample(self,deck,count):return deck
    snow=example_catalog('{S}',land_type='Snow Land — Island')
    assert opening_test(snow,['Spell']*7,['Land']*4,'U',11,Fixed(),hands=1)['ready_by_turn']['1']==1
    phyrexian=example_catalog('{W/P}')
    assert opening_test(phyrexian,['Spell']*7,['Land']*4,'W',11,Fixed(),hands=1,starting_life=2)['ready_by_turn']['1']==0
    assert opening_test(phyrexian,['Spell']*7,['Land']*4,'W',11,Fixed(),hands=1,starting_life=3)['ready_by_turn']['1']==1


def test_nonmana_land_remains_a_land_draw_but_cannot_pay_generic():
    catalog=example_catalog('{1}',fixing=())
    class Fixed:
        def sample(self,deck,count):return [catalog.cards['Land']]*4+[catalog.cards['Spell']]*7
    result=opening_test(catalog,['Spell']*7,['Land']*4,'U',11,Fixed(),hands=1)
    assert result['opening_2_to_4_lands']==1 and not any(result['ready_by_turn'].values())


def test_commander_and_classic_report_their_own_life_assumptions(tmp_path):
    from pathlib import Path
    from cube_ai.catalog import Catalog
    from cube_ai.config import BuildSpec
    from cube_ai.draft import draft_pod,stress_test
    from cube_ai.engine import build
    from cube_ai.feedback import FeedbackStore
    catalog=Catalog();rows,unknown=catalog.parse((Path(__file__).parent/'fixtures/forge_cube.csv').read_text(encoding='utf-8-sig'))
    assert not unknown
    for mode,life in [('commander',40),('classic',20)]:
        spec=BuildSpec.from_dict(dict(mode=mode))
        actual=rows if mode=='commander' else build(catalog,spec,store=FeedbackStore(tmp_path/'preferences.sqlite'))['cards']
        pod=draft_pod(catalog,actual,spec,random.Random(1937),readiness_hands=0)
        assert all(d['ready']['starting_life']==life and d['ready']['model_version']==MODEL_VERSION for d in pod['decks'] if d['buildable'])
        report=stress_test(catalog,actual,spec,trials=5)
        assert report['mana_model']['starting_life']==life and str(life) in report['mana_model']['assumptions']
