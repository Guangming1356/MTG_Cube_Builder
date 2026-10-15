import gzip
import json
import random
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import pytest
import requests
from cube_ai.catalog import Catalog, exclusion_reasons
from cube_ai.config import BuildSpec
from cube_ai.draft import affordable, deal, stress_test
from cube_ai.engine import audit, build, completes_combo, quotas
from cube_ai.features import extract, tribal_requirements
from cube_ai.feedback import FeedbackStore
from cube_ai.knowledge import Knowledge
from cube_ai.llm import advise, LLMClient, plan
from cube_ai.server import Application, handler_for

@pytest.fixture(scope='session')
def catalog():return Catalog()

@pytest.fixture(scope='session')
def generated(catalog,tmp_path_factory):
    store=FeedbackStore(tmp_path_factory.mktemp('preferences')/'prefs.sqlite')
    return build(catalog,BuildSpec(),store=store)

@pytest.mark.parametrize('fields',[{'size':True},{'commanders':-1},{'mode':'other'},{'players':1},
    {'unknown':1},{'curve':{'1':-1}},{'max_card_price':float('nan')},{'pair_themes':{'UW':'blink'}},
    {'allow_fast_mana':'false'},{'min_year':'2020'},{'name':''}])
def test_invalid_spec(fields):
    with pytest.raises(ValueError):BuildSpec.from_dict(fields)

def test_classic_defaults():
    s=BuildSpec.from_dict({'mode':'classic'})
    assert (s.commanders,s.players,s.rounds,s.pick_count,s.discard_after_pass)==(0,8,3,1,False)

@pytest.mark.parametrize('name',['Chrome Mox','Elvish Warmaster','Coat of Arms','Armageddon',
    'Sidar Jabari of Zhalfir','Mishra, Lost to Phyrexia','Dee Kay, Finder of the Lost',
    'Throne of the Grim Captain // The Grim Captain','Diviner\'s Wand','Kassandra, Eagle Bearer'])
def test_exclusions(catalog,name):
    assert exclusion_reasons(catalog.cards[name],BuildSpec())

@pytest.mark.parametrize('name',['Black Lotus','Lotus Petal','Definitely Invented Card'])
def test_forbidden_or_unknown_pin(catalog,name):
    with pytest.raises(ValueError):build(catalog,BuildSpec.from_dict({'pins':[name]}))

def test_case_insensitive_exclusion(catalog):
    assert '用户排除' in exclusion_reasons(catalog.cards['Lightning Bolt'],BuildSpec.from_dict({'exclude':['lightning bolt']}))

def test_plural_dependencies():
    assert tribal_requirements('Other Elves you control get +1/+1.',{'elf','human'})==['elf']
    assert tribal_requirements('Whenever another Elf enters, create a 1/1 Elf token.',{'elf'})==['elf']
    assert tribal_requirements('Create two 1/1 Elf tokens.',{'elf'})==[]
    assert tribal_requirements('Create a Survivor token. All Survivors you control gain haste.',{'survivor'})==[]

def test_artifact_land_and_noncreature_commander():
    land=extract({'name':'Test land','cmc':0,'type_line':'Artifact Land','oracle_text':'{T}: Add {U}.'},set())
    cmd=extract({'name':'Test walker','cmc':5,'type_line':'Legendary Planeswalker','oracle_text':'This can be your commander.'},set())
    assert land['kind']=='land' and not land['ramp']
    assert cmd['commander']

def test_severe_drawback_is_penalized(catalog):
    assert catalog.cards['Eater of Days']['quality']<2.7
    assert catalog.cards['Mishra, Lost to Phyrexia']['commander'] is False

def test_parser_alias_duplicate_unknown(catalog):
    rows,unknown=catalog.parse('2 Lightning Bolt\nNot A Real Card\n1x Sun Titan')
    assert [r['name'] for r in rows]==['Lightning Bolt','Lightning Bolt','Sun Titan']
    assert unknown==['Not A Real Card']
    a=audit(catalog,rows,BuildSpec(),unknown)
    assert {'unknown','duplicate'}<={i['code'] for i in a['issues']}
    n=next(n for n in catalog.cards if ' // ' in n)
    assert catalog.resolve(n.split(' // ')[0])==n

def test_csv_roundtrip_roles(catalog,generated):
    rows,unknown=catalog.parse('name,role\n"Sun Titan",Main\n"Command Tower",Land\n')
    assert not unknown and [r['role'] for r in rows]==['Main','Land']

def test_generation_constraints(catalog,generated):
    a=audit(catalog,generated['cards'],BuildSpec(),strict=True)
    assert a['total']==600 and a['hard_errors']==0
    assert a['roles']=={'Commander':90,'Land':70,'Main':440}
    assert a['curve']=={'1':54,'2':156,'3':94,'4':61,'5+':75}
    assert len({r['name'] for r in generated['cards']})==600
    assert not any(catalog.cards[r['name']]['tribal'] for r in generated['cards'])
    assert max(a['quality_by_group'][g] for g in 'WUBRG')-min(a['quality_by_group'][g] for g in 'WUBRG')<=.321
    assert a['role_counts']['finisher']>=38
    assert not completes_combo(r['name'] for r in generated['cards'])

def test_impossible_curve_not_silently_relaxed(catalog):
    s=BuildSpec.from_dict({'curve':{'1':440,'2':0,'3':0,'4':0,'5+':0}})
    with pytest.raises(ValueError):build(catalog,s)

def test_repair_removes_forbidden_card(catalog,generated,tmp_path):
    rows=[dict(r) for r in generated['cards']]
    index=next(i for i,r in enumerate(rows) if r['role']=='Main' and catalog.cards[r['name']]['identity']=='C')
    rows[index]={'name':'Chrome Mox','role':'Main'}
    repaired=build(catalog,BuildSpec(),rows,store=FeedbackStore(tmp_path/'prefs.db'))
    assert 'Chrome Mox' in repaired['changes']['removed']
    assert repaired['audit']['hard_errors']==0
    assert len(set(r['name'] for r in generated['cards'])&set(r['name'] for r in repaired['cards']))>500

def test_draft_refuses_invalid_card_pool(catalog,generated):
    rows=[dict(r) for r in generated['cards']];rows[0]={'name':'Chrome Mox','role':'Main'}
    with pytest.raises(ValueError,match='先审计'):stress_test(catalog,rows,BuildSpec(),5)

def test_deal_and_draft_rules(catalog,generated):
    s=BuildSpec();packs=deal(catalog,generated['cards'],s,random.Random(42))
    assert len(packs)==30 and all(len(p)==15 for p in packs)
    assert len({r['name'] for p in packs for r in p})==450
    assert all(sum(r['role']=='Commander' for r in p)==3 for p in packs)
    stress=stress_test(catalog,generated['cards'],s,5)
    assert stress['drafted_pool_sizes']=={60:15} and stress['cards_discarded_per_pack']==9
    assert 'win_rate' not in stress
    for deck in stress['examples']:
        assert len(deck['spells'])+len(deck['lands'])+sum(deck['basics'].values())+1==60
        identity=catalog.cards[deck['commander']]['identity']
        assert all(catalog.cards[n]['identity']=='C' or set(catalog.cards[n]['identity'])<=set(identity) for n in deck['spells']+deck['lands'])

def test_cost_pips_unique_land_usage():
    assert not affordable('{W}{W}',[{'W','U'},{'U'}])
    assert affordable('{1}{W/U}',[{'W'},{'U'}])
    assert not affordable('{X}{R}',[{'R'}])

def test_combo_pin_rejected(catalog):
    s=BuildSpec.from_dict({'pins':['Exquisite Blood','Sanguine Bond'],'exclude_game_changers':False})
    with pytest.raises(ValueError,match='无限'):build(catalog,s)

def model_message(data):
    return {'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(data)}]}]}

class FakeClient:
    style='responses';model='test-model'
    def __init__(self,responses):self.responses=iter(responses);self.messages=[]
    def request(self,messages,*args,**kwargs):self.messages.append(list(messages));return next(self.responses)

def test_grounded_tools_and_hallucination_rejection(catalog,generated):
    cmd=next(r['name'] for r in generated['cards'] if r['role']=='Commander')
    responses=[{'output':[{'type':'function_call','name':'lookup_card','arguments':json.dumps({'name':cmd}),'call_id':'1'}]},
        model_message({'answer':'已核对','swaps':[{'remove':cmd,'add':'Fake Dragon 9000','reason':'更强'}],'cautions':[]})]
    c=FakeClient(responses);a=advise(catalog,Knowledge(),BuildSpec(),generated['cards'],'检查指挥官',c)
    assert not a['swaps'] and a['rejected'][0]['reason']=='未确认卡名'
    assert any(m.get('type')=='function_call_output' for m in c.messages[1])
    assert a['tools'][0]['name']=='lookup_card'

def test_incomplete_model_response(catalog):
    with pytest.raises(ValueError,match='未完成'):advise(catalog,Knowledge(),BuildSpec(),[],'x',FakeClient([{'status':'incomplete'}]))

def test_api_wire_and_key_not_status(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-secret');monkeypatch.setenv('CUBE_API_STYLE','responses')
    client=LLMClient()
    with patch('cube_ai.llm.requests.post') as post:
        post.return_value.status_code=200;post.return_value.json.return_value={'output':[]}
        client.request([{'role':'user','content':'test'}],schema={'type':'object'})
        kwargs=post.call_args.kwargs
        assert kwargs['json']['text']['format']['type']=='json_schema' and kwargs['json']['store'] is False
        assert kwargs['headers']['Authorization']=='Bearer test-secret'
    assert 'test-secret' not in json.dumps(client.status())

def test_chat_adapter(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-secret');monkeypatch.setenv('CUBE_API_STYLE','chat')
    with patch('cube_ai.llm.requests.post') as post:
        post.return_value.status_code=200;post.return_value.json.return_value={}
        LLMClient().request([{'role':'user','content':'x'}])
        assert post.call_args.args[0].endswith('/chat/completions')

def test_real_label_learning_is_bounded(catalog,tmp_path):
    s=FeedbackStore(tmp_path/'prefs.db');context=s.context(BuildSpec())
    with pytest.raises(ValueError,match='8'):s.train(catalog,context)
    for _ in range(8):s.add('Sun Titan','Serra Angel',context,'test-only artificial labels')
    result=s.train(catalog,context)
    assert result['train_rows']==7 and result['holdout_rows']==1
    score,_=s.scorer(BuildSpec());assert abs(score(catalog.cards['Sun Titan']))<=.5

def test_http_boundaries(catalog,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    app=Application(catalog);server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url=f'http://127.0.0.1:{server.server_port}'
    try:
        assert requests.get(url+'/').status_code==200
        assert requests.get(url+'/api/status').json()['gpt']['configured'] is False
        a=requests.post(url+'/api/analyze',json={'text':'1 Fake Card','spec':BuildSpec().to_dict()}).json()
        assert a['audit']['hard_errors']>0
        assert requests.post(url+'/api/tasks',json={'operation':'chat'}).status_code==400
        assert requests.post(url+'/api/analyze',json={},headers={'Origin':'https://evil.example'}).status_code==403
        assert requests.get(url+'/%2e%2e/server.py').status_code==404
        assert requests.get(url+'/exports/../../config.py').status_code==404
        a=requests.post(url+'/api/analyze',json={'text':'Sun Titan','spec':{'mode':'classic'}}).json()
        assert a['cards'][0]['role']=='Main'
        # Saving an edited list must preserve designated slots instead of inferring all legends.
        with patch('cube_ai.server.export_run',side_effect=lambda c,r:dict(r,run_id='test_saved')):
            saved=requests.post(url+'/api/save',json={'spec':BuildSpec().to_dict(),'cards':[{'name':'Sun Titan','role':'Main'}]}).json()
        assert saved['cards'][0]['role']=='Main' and saved['run_id']=='test_saved'
    finally:server.shutdown();server.server_close();app.executor.shutdown(wait=True)

def test_jsonl_gzip_import(tmp_path):
    from cube_ai.import_catalog import convert
    source=tmp_path/'cards.jsonl.gz';records=[dict(name=f'Test card {i}',type_line='Creature',games=['paper'],lang='en') for i in range(101)]
    with gzip.open(source,'wt',encoding='utf-8') as f:
        for r in records:f.write(json.dumps(r)+'\n')
    target=tmp_path/'pool.json';result=convert(source,target,'2026-01-01')
    assert result['cards']==101 and json.loads(target.read_text(encoding='utf-8'))['date']=='2026-01-01'

def test_knowledge_has_citable_sources():
    hits=Knowledge().search('Commander Cube 轮抓 终结',3)
    assert hits and all(h['source'] and h['text'] for h in hits)
