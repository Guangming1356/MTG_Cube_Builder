import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import Mock

import pytest
import requests

from cube_ai.ai_settings import SettingsStore
from cube_ai.catalog import Catalog
from cube_ai.config import BuildSpec
from cube_ai.engine import build,audit,quotas,density_minima,export_run
from cube_ai.feedback import FeedbackStore
from cube_ai.knowledge import Knowledge
from cube_ai.llm import plan,plan_schema,response_text,validate_output,replacements
from cube_ai.server import Application,handler_for


@pytest.mark.parametrize('data',[
    {'interaction_min_ratio':float('nan')},{'interaction_min_ratio':True},
    {'interaction_min_ratio':.31},{'wipe_min_ratio':0},{'finisher_min_ratio':.5},
    {'curve_profile':'unsupported'},{'curve':{}},{'curve':{'1':440}},
    {'pack_size':61},{'pick_count':16},[],42,
])
def test_invalid_new_inputs_are_rejected_early(data):
    with pytest.raises(ValueError):BuildSpec.from_dict(data)


def test_curve_profiles_and_precise_override():
    normal=quotas(BuildSpec())[2];low=quotas(BuildSpec(curve_profile='low'))[2];late=quotas(BuildSpec(curve_profile='late'))[2]
    assert low['1']+low['2']>normal['1']+normal['2'] and late['5+']>normal['5+']
    assert quotas(BuildSpec.from_dict({'curve_profile':'low','curve':normal}))[2]==normal
    assert all(sum(c.values())==440 for c in [normal,low,late])


def test_planner_schema_reaches_all_build_fields_and_reports_unapplied():
    data=BuildSpec.from_dict({'bracket':3}).to_dict()
    assert set(plan_schema()['properties'])-{'explanation','unapplied_requests'}==set(data)
    data.update(interaction_min_ratio=.24,curve_profile='low',explanation='增加互动、低费优先',unapplied_requests=['无法保证每个颜色绝对相同胜率'])
    client=Mock(style='responses',model='test');client.request.return_value={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(data)}]}]}
    result=plan('多互动，低费',BuildSpec.from_dict({'bracket':3}),Knowledge(),client)
    assert result['spec']['interaction_min_ratio']==.24 and result['unapplied_requests']
    assert {'interaction_min_ratio','curve_profile'}<={x['field'] for x in result['changes']}


def test_planning_a_mode_switch_keeps_returned_custom_draft_rules():
    fields=BuildSpec.from_dict({'mode':'classic','players':3,'rounds':8}).to_dict()
    reply=dict(fields,explanation='三人传统 Cube',unapplied_requests=[])
    client=Mock(style='responses',model='test');client.request.return_value={'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(reply)}]}]}
    result=plan('三人传统轮抓',BuildSpec(),Knowledge(),client)
    assert result['spec']['players']==3 and result['spec']['rounds']==8 and result['spec']['pack_size']==15


def test_final_answer_not_commentary_is_parsed():
    response={'output':[dict(type='message',phase='commentary',content=[dict(type='output_text',text='正在检查')]),dict(type='message',phase='final_answer',content=[dict(type='output_text',text='{"ok":true}')])]}
    assert response_text(response,'responses')=='{"ok":true}'


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-.1,1.1])
def test_json_numeric_constraints(value):
    with pytest.raises(ValueError):validate_output(value,{'type':'number','minimum':0,'maximum':1})


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    catalog=Catalog();spec=BuildSpec.from_dict({'bracket':3,'interaction_min_ratio':.24,'wipe_min_ratio':.05,'finisher_min_ratio':.11,'curve_profile':'low'})
    store=FeedbackStore(tmp_path_factory.mktemp('new-policy')/'prefs.sqlite')
    return catalog,spec,build(catalog,spec,store=store)


def test_preferences_are_satisfied_by_real_selected_cards_and_audit_detects_stricter_target(built):
    catalog,spec,result=built
    assert result['audit']['hard_errors']==0 and len(result['cards'])==600
    actual=result['audit']['role_counts'];targets=density_minima(spec,440)
    assert all(actual[k]>=v for k,v in targets.items())
    assert result['audit']['curve']==quotas(spec)[2]
    # A later higher terminal target must be audited, rather than reusing old labels.
    stronger=BuildSpec.from_dict(dict(spec.to_dict(),finisher_min_ratio=.20))
    assert any(i['code']=='density' for i in audit(catalog,result['cards'],stronger,strict=True)['issues'])


def test_repeated_identical_saves_are_unique_and_keep_spec(built,tmp_path,monkeypatch):
    import cube_ai.engine as engine
    catalog,spec,result=built;monkeypatch.setattr(engine,'RUNS',tmp_path/'runs')
    a=export_run(catalog,{k:v for k,v in result.items() if k!='run_id'})
    b=export_run(catalog,{k:v for k,v in result.items() if k!='run_id'})
    assert a['run_id']!=b['run_id']
    saved=json.loads((engine.RUNS/a['run_id']/'cube.json').read_text(encoding='utf8'))
    assert BuildSpec.from_dict(saved['spec'])==spec and saved['audit']['hard_errors']==0


def test_process_lock_prevents_lost_updates(tmp_path):
    target=tmp_path/'private'/'settings.bin';store=SettingsStore(target);store.write(dict(profiles={},accounts={},counter=0))
    script='''import sys;from cube_ai.ai_settings import SettingsStore
s=SettingsStore(sys.argv[1])
for i in range(15):
 with s.lock:
  data=s.read();data['counter']+=1;s.write(data)
'''
    env=dict(os.environ);env.pop('OPENAI_API_KEY',None)
    children=[subprocess.Popen([sys.executable,'-X','utf8','-c',script,str(target)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
    try:
        for process in children:
            out,err=process.communicate(timeout=20);assert process.returncode==0,err.decode('utf8')
    finally:
        for process in children:
            if process.poll() is None:process.terminate();process.wait(timeout=5)
    assert store.read()['counter']==30


def test_http_swap_rechecks_current_constraints_and_invalid_input_is_400(built,tmp_path,monkeypatch):
    catalog,spec,result=built;app=Application(catalog,SettingsStore(tmp_path/'settings.bin'))
    server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app));threading.Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_port}'
    rows=result['cards'];main=next(r['name'] for r in rows if r['role']=='Main' and catalog.cards[r['name']]['identity']=='W')
    try:
        for payload in [{'cards':'bad'},{'cards':[{}]},{'text':[]},{'text':'Sun Titan','spec':None,'cards':[]}]:
            response=requests.post(url+'/api/analyze',json=payload)
            assert response.status_code==400 if not isinstance(payload.get('text'),str) else response.status_code==200
        for message in ['',None,[],123]:
            assert requests.post(url+'/api/tasks',json=dict(operation='plan',message=message)).status_code==400
        wrong=requests.post(url+'/api/apply-swap',json=dict(spec=spec.to_dict(),cards=rows,remove=main,add='Lightning Bolt'))
        assert wrong.status_code==400
        pool=replacements(catalog,spec,rows,main,limit=2)
        assert pool
        valid=requests.post(url+'/api/apply-swap',json=dict(spec=spec.to_dict(),cards=rows,remove=main,add=pool[0]['name']))
        assert valid.status_code==200 and valid.json()['audit']['hard_errors']==0
        assert rows==result['cards']  # requests and failed mutations never alter the original list
        # A changed form may invalidate an existing cube. Do not export it as ready to play.
        monkeypatch.setattr('cube_ai.server.export_run',lambda *args:pytest.fail('invalid cube was exported'))
        bad_spec=dict(spec.to_dict(),finisher_min_ratio=.20)
        assert requests.post(url+'/api/save',json=dict(spec=bad_spec,cards=rows,require_valid=True)).status_code==400
    finally:server.shutdown();server.server_close();app.executor.shutdown(wait=True)


@pytest.mark.parametrize('broken',['{truncated','[]','{"signature":"bad","cards":[]}'])
def test_bad_catalog_cache_recovers(tmp_path,monkeypatch,broken):
    import cube_ai.catalog as module
    monkeypatch.setattr(module,'DATA',tmp_path)
    source=tmp_path/'pool.json'
    source.write_text(json.dumps({'date':'2026-10-15','cards':{'Sun Titan':{'name':'Sun Titan','type_line':'Creature — Giant','mana_cost':'{4}{W}{W}','oracle_text':'Vigilance','color_identity':['W'],'legalities':{'commander':'legal'}}}}),encoding='utf8')
    (tmp_path/'catalog.json').write_text(broken,encoding='utf8')
    assert 'Sun Titan' in Catalog(str(source)).cards
    assert isinstance(json.loads((tmp_path/'catalog.json').read_text(encoding='utf8')),dict)


def test_csv_handles_missing_cells_normalizes_roles_and_preserves_counts():
    catalog=Catalog()
    rows,unknown=catalog.parse('name,role,count,maybeboard\n"Sun Titan", main ,2,\n')
    assert not unknown and len(rows)==2 and all(r['role']=='Main' for r in rows)
    assert catalog.resolve(None) is None
    with pytest.raises(ValueError):catalog.parse('name,role\n"Sun Titan",misspelled\n')
    with pytest.raises(ValueError):catalog.parse('name,count\n"Sun Titan",-3\n')


@pytest.mark.parametrize('style,reply',[
 ('responses',{'output':[None]}),('responses',{'output':{}}),('responses',{'output':[{'type':'message','content':None}]}),
 ('responses',{'output':[{'type':'message','content':[{'type':'output_text','text':3}]}]}),
 ('chat',{'choices':{'message':'wrong'}}),('chat',{'choices':[{'message':'wrong'}]}),
])
def test_malformed_provider_messages_raise_readable_errors(style,reply):
    with pytest.raises(ValueError):response_text(reply,style)


def test_import_limits_and_zero_counts():
    catalog=Catalog()
    with pytest.raises(ValueError,match='900'):catalog.parse('100 Lightning Bolt\n'*10)
    with pytest.raises(ValueError):catalog.parse('0 Lightning Bolt')


def test_unreadable_ai_settings_do_not_disable_offline_work_and_can_be_backed_up(tmp_path):
    store=SettingsStore(tmp_path/'private/settings.bin');store.path.parent.mkdir();store.path.write_bytes(b'damaged-settings')
    app=Application(Catalog(),store);server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app))
    threading.Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_port}'
    try:
        status=requests.get(url+'/api/status').json()
        assert status['presets'] and not status['gpt']['configured'] and status['gpt']['configuration_error']
        assert requests.get(url+'/api/ai/settings').json()['status']['configuration_error']
        assert requests.post(url+'/api/analyze',json={'text':'Sun Titan'}).status_code==200
        reset=requests.post(url+'/api/ai/reset',json={})
        assert reset.status_code==200 and reset.json()['provider']=='offline'
        assert len(list(store.path.parent.glob('settings.bin.backup-*')))==1
        assert 'configuration_error' not in requests.get(url+'/api/status').json()['gpt']
    finally:server.shutdown();server.server_close();app.executor.shutdown(wait=True)
