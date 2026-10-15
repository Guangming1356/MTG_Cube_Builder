import json
import random
import threading
import time
import requests
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from cube_ai.catalog import Catalog, exclusion_reasons
from cube_ai.config import BuildSpec, ROOT
from cube_ai.design import studies, reference_prior, design_bonus, package_report, deck_design_report
from cube_ai.draft import draft_pod
from cube_ai.launcher import APP_ID, WORKSPACE_ID, health, find_server, launch
from cube_ai.server import example_label, Application, handler_for

def test_references_are_format_matched_and_bounded():
    catalog=Catalog();commander=BuildSpec();classic=BuildSpec.from_dict({'mode':'classic'})
    data=studies();assert len(data['cases'])==9
    assert all(c['stats']['known_slots']<=c['stats']['main_slots'] for c in data['cases'])
    for name,matches in data['membership'].items():
        card=catalog.cards[name]
        for spec,group in [(commander,'commander'),(classic,'fair')]:
            bonus,sources=reference_prior(card,spec)
            assert 0<=bonus<=.08
            assert set(sources)=={m['id'] for m in matches if m['group']==group}
            assert design_bonus(card,spec)<=.12+1e-8
    # A public-list membership cannot make a prohibited card selectable.
    lotus=catalog.cards[catalog.resolve('Chrome Mox')]
    assert exclusion_reasons(lotus,commander)

def test_component_check_uses_actual_selected_deck():
    catalog=Catalog()
    deck={'spells':['Blood Artist'],'commander':None}
    result=deck_design_report(catalog,deck)
    assert set(result['packages']['sacrifice']['missing'])=={'fodder','outlet'}
    complete=package_report([catalog.cards[n] for n in ['Blood Artist','Viscera Seer','Bitterblossom']])
    assert not complete['sacrifice']['missing']
    # Treasure is not a creature that can die for Blood Artist.
    c={'name':'Treasure test','text':'Create two Treasure tokens.','creature':False,'mv':2}
    assert package_report([catalog.cards['Blood Artist'],c])['sacrifice']['components']['fodder']['count']==0

def test_health_rejects_other_project_and_foreign_web_app():
    class Response:
        def __init__(self,value):self.value=value
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return json.dumps(self.value).encode()
    for payload,accepted in [(dict(app=APP_ID,workspace=WORKSPACE_ID,pid=123),True),
                            (dict(app=APP_ID,workspace='another project'),False),
                            (dict(app='other service',workspace=WORKSPACE_ID),False)]:
        with patch('cube_ai.launcher.urllib.request.urlopen',return_value=Response(payload)):
            assert bool(health(8765))==accepted
    with patch('cube_ai.launcher.PORTS',[8765,8766]),patch('cube_ai.launcher.port_free',return_value=False),patch('cube_ai.launcher.health',side_effect=[None,{'pid':2}]):
        assert find_server()==(8766,{'pid':2})

def test_launcher_reuses_server_without_spawning(tmp_path):
    with patch('cube_ai.launcher.ROOT',tmp_path),patch('cube_ai.launcher.load_env'),patch('cube_ai.launcher.find_server',return_value=(8765,{'pid':123,'task_controls':True})),patch('cube_ai.launcher.start_server') as spawn,patch('cube_ai.launcher.webbrowser.open') as browser:
        result=launch(False)
        assert result['reused'] and result['pid']==123
        spawn.assert_not_called();browser.assert_not_called()

def test_labels_and_offline_research_retrieval():
    from cube_ai.knowledge import Knowledge
    assert '第 7 套' in example_label('commander_cube_600_v7_reviewed')
    hits=Knowledge().search('CubeCobra 桥梁牌 牺牲出口',8)
    assert any('cube-design-studies' in h['source'] for h in hits)

def test_new_endpoints_and_async_execution_are_reachable():
    app=Application();server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app))
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        h=requests.get(base+'/api/health',timeout=3);assert h.status_code==200
        assert h.json()['workspace']==WORKSPACE_ID
        lib=requests.get(base+'/api/library',timeout=3).json();assert 'examples' in lib
        guide=requests.get(base+'/api/design-guide',timeout=3).json();assert len(guide['cases'])==9
        with patch('cube_ai.server.stress_test',return_value={'verified_async_execution':True}):
            response=requests.post(base+'/api/tasks',json=dict(operation='stress',cards=[{'name':'Lightning Bolt','role':'Main'}]),timeout=3)
            assert response.status_code==202
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                job=requests.get(base+'/api/job?id='+response.json()['job_id'],timeout=3).json()
                if job['state'] in {'done','failed'}:break
                time.sleep(.01)
            assert job['state']=='done',job
            assert job['result']['verified_async_execution']
    finally:
        server.shutdown();server.server_close();app.executor.shutdown();worker.join()

def test_cubecobra_import_excludes_non_drafted_boards():
    rows,unknown=Catalog().parse('name,board,maybeboard\nLightning Bolt,mainboard,false\nBlack Lotus,maybeboard,true\nIsland,basics,false\n')
    assert not unknown
    assert rows==[{'name':'Lightning Bolt','role':'Main'}]
