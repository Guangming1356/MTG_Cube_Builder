import copy
import json
from types import SimpleNamespace

import pytest

from cube_ai.config import BuildSpec
from cube_ai.feedback import FeedbackStore,FEATURE_VERSION


def setup(tmp_path):
    store=FeedbackStore(tmp_path/'preferences.sqlite');spec=BuildSpec();context=store.context(spec)
    catalog=SimpleNamespace(signature='pool-a',cards={'Example':dict(vector=[1.,1.,0.])})
    model=dict(weights=[.2,.1,0.],context=context,feature_version=FEATURE_VERSION,catalog=catalog.signature)
    return store,spec,context,catalog,model


def save(store,context,model):
    with store.connect() as db:db.execute('INSERT OR REPLACE INTO models(context,payload) VALUES(?,?)',(context,json.dumps(model)))


@pytest.mark.parametrize('changed,reason',[
    ({'feature_version':'earlier-ontology'},'feature_version_changed'),
    ({'catalog':'different-pool'},'catalog_changed'),
    ({'context':'legacy:classic'},'context_changed'),
    ({'weights':[.1]},'invalid_model'),
    ({'weights':[float('nan'),0.,0.]},'invalid_model'),
    ({'weights':[True,0.,0.]},'invalid_model'),
])
def test_incompatible_preference_weights_are_not_applied_or_deleted(tmp_path,changed,reason):
    store,spec,context,catalog,model=setup(tmp_path);model.update(changed);save(store,context,model)
    store.add('Unit test A','Unit test B',context,'test-only unit example',catalog)
    status=store.status(context,catalog);score,active=store.scorer(spec,catalog)
    assert not status['model_compatible'] and status['model_reason']==reason
    assert active is None and score(catalog.cards['Example'])==0
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM comparisons').fetchone()[0]==1
        assert db.execute('SELECT payload FROM models').fetchone()[0]==json.dumps(model)


def test_valid_scope_is_used_but_missing_scope_and_bad_card_vectors_are_not(tmp_path):
    store,spec,context,catalog,model=setup(tmp_path);save(store,context,model)
    score,active=store.scorer(spec,catalog)
    assert active==model and 0<score(catalog.cards['Example'])<=.5
    assert score(dict(vector=[1.]))==0
    assert score(dict(vector=[float('nan'),1.,0.]))==0
    assert store.scorer(spec)[1] is None
    assert store.status(context)['model_reason']=='catalog_unknown'
    legacy=copy.deepcopy(model);legacy.pop('feature_version');save(store,context,legacy)
    assert store.status(context,catalog)['model_reason']=='feature_version_changed'


def test_corrupt_model_json_does_not_hide_comparisons_or_crash_status(tmp_path):
    store,spec,context,catalog,_=setup(tmp_path)
    store.add('Unit A','Unit B',context,'test-only unit example')
    with store.connect() as db:db.execute('INSERT INTO models(context,payload) VALUES(?,?)',(context,'{"weights":'))
    status=store.status(context,catalog)
    assert status['comparisons']==1 and status['model_reason']=='invalid_model'
    assert not status['model_compatible'] and store.scorer(spec,catalog)[1] is None


def test_http_feedback_status_uses_requested_format_and_never_emits_nan(tmp_path):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from cube_ai.server import Application,handler_for
    catalog=SimpleNamespace(signature='fixture',cards={'Example':dict(vector=[1.,0.])})
    app=Application(catalog=catalog)
    for context in ['commander:commander','legacy:classic','legacy:classic']:
        app.feedback.add('Unit A','Unit B',context,'test-only unit example',catalog)
    server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    def read(context):
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/feedback/status?context={context}',timeout=5) as response:
            def refuse(value):raise AssertionError('Nonstandard JSON numeric token: '+value)
            return json.loads(response.read(),parse_constant=refuse)
    try:
        assert read('commander:commander')['comparisons']==1
        assert read('legacy:classic')['comparisons']==2
        payload=dict(context='legacy:classic',feature_version=FEATURE_VERSION,catalog='fixture',weights=[float('nan'),0.])
        save(app.feedback,'legacy:classic',payload)
        result=read('legacy:classic')
        assert result['comparisons']==2 and result['model'] is None
        assert result['model_reason']=='invalid_model' and not result['model_compatible']
        with app.feedback.connect() as db:
            assert 'NaN' in db.execute('SELECT payload FROM models WHERE context=?',('legacy:classic',)).fetchone()[0]
    finally:
        server.shutdown();server.server_close();app.executor.shutdown(wait=True);thread.join()
