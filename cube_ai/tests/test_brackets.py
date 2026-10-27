import random
import pytest
from cube_ai.brackets import GAME_CHANGERS, profile, is_gc, public_profiles, deck_report, may_add
from cube_ai.catalog import Catalog, exclusion_reasons
from cube_ai.config import BuildSpec

@pytest.mark.parametrize('fields',[{'bracket':True},{'bracket':0},{'bracket':6},{'bracket':'3'},
    {'mode':'classic','bracket':3},{'power_tuning':'max'},{'commander_tuning':'max'},
    {'bracket':2,'cube_gc_limit':1},{'bracket':3,'cube_gc_limit':True},
    {'bracket':3,'allow_infinite_combos':True},{'bracket':3,'allow_extra_turns':True},
    {'bracket':2,'allow_mass_land_destruction':True},{'cube_gc_limit':4}])
def test_invalid_bracket_settings(fields):
    with pytest.raises(ValueError):BuildSpec.from_dict(fields)

def test_current_official_list_and_project_defaults():
    assert len(GAME_CHANGERS)==53
    assert {'Farewell','Biorhythm'}<=GAME_CHANGERS
    assert not {'Winota, Joiner of Forces','Yuriko, the Tiger\'s Shadow','Deflecting Swat'}&GAME_CHANGERS
    catalog=Catalog()
    assert is_gc(catalog.cards[catalog.resolve('Tergrid, God of Fright')])
    assert [p['deck_gc'] for p in public_profiles()['profiles']]==[0,0,3,None,None]
    for b in range(1,6):
        s=BuildSpec.from_dict({'bracket':b});p=profile(s)
        assert p['gc_limit']==[0,0,18,36,54][b-1]
        assert not s.allow_fast_mana and not s.allow_infinite_combos and not s.allow_mass_land_destruction
    assert BuildSpec.from_dict({}).bracket is None
    assert profile(BuildSpec()) is None

def test_gc_check_counts_commander_and_land_and_ignores_snapshot_flag():
    catalog=Catalog();s=BuildSpec.from_dict({'bracket':3})
    names=['Braids, Cabal Minion','Ancient Tomb','Rhystic Study']
    assert not may_add(catalog,names,'Demonic Tutor',s)
    deck=dict(commander=names[0],lands=[names[1]],spells=names[2:]+['Demonic Tutor'])
    r=deck_report(catalog,deck,s)
    assert len(r['game_changers'])==4 and r['violations'] and not r['certified']
    c=dict(catalog.cards['Farewell'],game_changer=False)
    assert exclusion_reasons(c,BuildSpec.from_dict({'bracket':2,'exclude_game_changers':False}))

def test_future_prints_without_paper_evidence_and_extra_turns_are_checked():
    catalog=Catalog();c=dict(catalog.cards['Lightning Bolt'],released='2099-01-01')
    assert '尚未核实已发行的纸质印张' in exclusion_reasons(c,BuildSpec.from_dict({'bracket':3}))
    assert '尚未核实已发行的纸质印张' in exclusion_reasons(c,BuildSpec())
    assert exclusion_reasons(catalog.cards['Time Warp'],BuildSpec.from_dict({'bracket':3}))
    assert not exclusion_reasons(catalog.cards['Time Warp'],BuildSpec.from_dict({'bracket':4,'allow_extra_turns':True}))

@pytest.mark.parametrize('bracket',range(1,6))
def test_real_generation_and_sixty_card_drafts(bracket,tmp_path):
    from cube_ai.engine import build, audit
    from cube_ai.draft import stress_test
    from cube_ai.feedback import FeedbackStore
    catalog=Catalog();spec=BuildSpec.from_dict({'bracket':bracket})
    result=build(catalog,spec,store=FeedbackStore(tmp_path/'prefs.db'))
    assert audit(catalog,result['cards'],spec,strict=True)['hard_errors']==0
    assert result['audit']['curve']=={'1':54,'2':156,'3':94,'4':61,'5+':75}
    assert result['audit']['role_counts']['finisher']>=38
    assert not result['audit']['bracket']['violations']
    stress=stress_test(catalog,result['cards'],spec,5)
    assert stress['buildable_rate']==1 and stress['drafted_pool_sizes']=={60:15}
    assert stress['bracket_check']['violations']==0
    for d in stress['examples']:
        assert len(d['spells'])+len(d['lands'])+sum(d['basics'].values())+1==60
        assert not d['bracket']['certified']

def test_forge_export_rejects_over_budget_before_running_engine(tmp_path):
    from cube_ai.forge import write_deck
    catalog=Catalog();deck=dict(commander='Braids, Cabal Minion',lands=['Ancient Tomb'],spells=['Demonic Tutor','Vampiric Tutor'])
    with pytest.raises(ValueError,match='Bracket'):
        write_deck(deck,tmp_path/'invalid.dck',{},catalog,BuildSpec.from_dict({'bracket':3}))

def test_announced_forge_timeout_with_cancelled_ai_future():
    from cube_ai.forge import parse_log
    cancelled='Stopping slow match as draw\njava.lang.InterruptedException\n\tat forge.ai.AiController.chooseSpellAbilityToPlayFromList(AiController.java:1686)'
    assert parse_log(cancelled)['outcome']=='engine_timeout'
    assert parse_log('IllegalStateException: real failure\n'+cancelled)['outcome']=='engine_error'
    assert parse_log(cancelled,returncode=1)['outcome']=='engine_error'
