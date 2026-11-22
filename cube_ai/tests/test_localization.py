import json
import re
import threading
from http.server import ThreadingHTTPServer

import requests
import pytest

from cube_ai.ai_settings import SettingsStore
from cube_ai.catalog import Catalog
from cube_ai.config import BuildSpec
from cube_ai.engine import audit
from cube_ai.localization import audit_report_english,match_report_english,optimization_report_english,report_english,translate_text
from cube_ai.server import Application,handler_for
from cube_ai.vintage_data import reference


def test_ai_advisor_receives_selected_language():
    from cube_ai.llm import advise,plan
    class Capture(Exception):pass
    class Client:
        def request(self,messages,*args,**kwargs):
            self.messages=messages
            raise Capture()
    class Knowledge:
        def search(self,*args):return []
    client=Client();catalog=Catalog();spec=BuildSpec()
    with pytest.raises(Capture):advise(catalog,Knowledge(),spec,[], 'hello',client,language='en')
    assert 'Answer in English.' in client.messages[0]['content']
    assert '用中文回答。' not in client.messages[0]['content']
    with pytest.raises(Capture):plan('hello',spec,Knowledge(),client,language='en')
    assert 'explanation and unapplied_requests in English' in client.messages[0]['content']


def test_english_audit_report_preserves_data_and_translates_reference():
    catalog=Catalog();result=reference(catalog)
    result['audit']=audit(catalog,result['cards'],BuildSpec.from_dict(result['spec']),strict=True)
    result['spec']['name']='我的 Cube: Black Lotus'
    text=audit_report_english(result)
    assert text.startswith('# 我的 Cube: Black Lotus\n')
    assert 'Cards: 540;' in text and 'hard errors: 0' in text
    assert 'Board-wipe density is below the configured minimum.' in text
    assert not re.search('[\u4e00-\u9fff]',text.split('\n',1)[1])
    assert 'return to the spell' not in text.lower()


def test_generic_report_does_not_translate_names_or_code():
    report='# 我的 Cube\n\n## 审计发现\n\n`扫场密度低于设置的下限`\n'
    result=report_english(report)
    assert result.startswith('# 我的 Cube\n')
    assert '## Audit findings' in result
    assert '`扫场密度低于设置的下限`' in result
    assert 'Board-wipe density' in translate_text('扫场密度低于设置的下限')


def test_match_and_optimization_reports_keep_observed_values_and_names():
    match=dict(engine={'version':'2.0.15'},pods=1,games_per_pod=3,rules={'deck_total_exported':60,'starting_life':40},
        summary={'completed':1,'outcomes':{'win':1}},coverage={'supported':100,'total':101},skipped_pods=0,
        games=[{'pod':0,'game':0,'outcome':'win','winner':'Player 1','turns':9,'log':'game.log'}])
    text=match_report_english(match)
    assert '60 cards' in text and '1/1 games' in text and 'Player 1' in text and '[log](game.log)' in text
    opt=dict(status='experimental',swaps=[{'remove':'Black Lotus','add':'Island','identity':'U','reason':'扫场密度低于设置的下限'}],
        structural=dict(mean_before=.1,mean_after=.2,p10_before=.05,p10_after=.06,gap_before=.1,gap_after=.08,pod_bootstrap95=[-.01,.1]),
        training={'completed':2,'attempted':3},cross={'new_wins':1},forge_before={},forge_after={},gates={'hard_constraints':True})
    text=optimization_report_english(opt)
    assert 'Black Lotus' in text and 'Island' in text and '0.100000 → 0.200000' in text
    assert not re.search('[\u4e00-\u9fff]',text)


def test_report_download_language_keeps_original_file(tmp_path,monkeypatch):
    from cube_ai import server as module
    catalog=Catalog();result=reference(catalog)
    result['audit']=audit(catalog,result['cards'],BuildSpec.from_dict(result['spec']),strict=True)
    folder=tmp_path/'sample';folder.mkdir()
    original='# 原名称\n\n## 审计发现\n'
    (folder/'report.md').write_text(original,encoding='utf8')
    (folder/'cube.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf8')
    monkeypatch.setattr(module,'RUNS',tmp_path)
    app=Application(catalog=catalog,ai_store=SettingsStore(tmp_path/'settings.bin'),restore_history=False)
    server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        url=f'http://127.0.0.1:{server.server_port}/exports/sample/report.md'
        zh=requests.get(url,timeout=10);en=requests.get(url+'?lang=en',timeout=10)
        zh.raise_for_status();en.raise_for_status()
        assert zh.text.replace('\r\n','\n')==original and 'Cards: 540;' in en.text
        assert 'report.en.md' in en.headers['Content-Disposition']
        assert (folder/'report.md').read_text(encoding='utf8')==original
    finally:
        server.shutdown();server.server_close();app.shutdown();thread.join()
