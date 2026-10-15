"""No paid requests: real local HTTP, real signatures and encrypted-store round trips."""
import base64
import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from unittest.mock import Mock, patch

import jwt
import pytest
import requests
from cryptography.hazmat.primitives.asymmetric import rsa

from cube_ai.ai_settings import SettingsStore, PROVIDERS, validate_base
from cube_ai.chatgpt_auth import ChatGPTAuth, ISSUER, PLAN_SCOPE
from cube_ai.llm import LLMClient, ANSWER_SCHEMA, TOOLS, advise, plan
from cube_ai.catalog import Catalog
from cube_ai.knowledge import Knowledge
from cube_ai.config import BuildSpec
from cube_ai.server import Application, handler_for


@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    return SettingsStore(tmp_path/'private'/'ai-settings.bin')


def test_keys_are_private_and_provider_scoped(store):
    assert not store.path.exists()
    store.save(dict(provider='deepseek',key='unit-test-private-value'))
    assert 'unit-test-private-value' not in json.dumps(store.public())
    if os.name=='nt': assert b'unit-test-private-value' not in store.path.read_bytes()
    assert SettingsStore(store.path).config()['key']=='unit-test-private-value'
    store.save(dict(provider='qwen'))
    assert store.config()['key']=='' and not LLMClient(store).status()['configured']
    store.save(dict(provider='deepseek'))
    assert store.config()['key']=='unit-test-private-value'
    with pytest.raises(ValueError,match='重新填写密钥'):
        store.save(dict(provider='deepseek',base='https://different.example/v1'))
    store.save(dict(provider='deepseek',clear_key=True))
    assert not store.config()['key']


@pytest.mark.parametrize('url',['http://example.com/v1','https://name:secret@example.com','https://example.com?key=abc','https://example.com/#x','file:///tmp','https://example.com:bad'])
def test_reject_unsafe_api_address(url):
    with pytest.raises(ValueError):validate_base(url)


def begin(auth,account_id=''):
    urls=[]
    status=auth.begin(12345,account_id,opener=lambda url:urls.append(url) or True)
    assert status['phase']=='pending' and 'url' not in status
    return parse_qs(urlsplit(urls[0]).query)


@pytest.fixture(scope='module')
def signing_key():return rsa.generate_private_key(public_exponent=65537,key_size=2048)


def signed_identity(auth,key,**changes):
    claims=dict(iss=ISSUER,sub='test-subject',aud='oaiapp_test',iat=int(time.time()),exp=int(time.time())+3600,
                nonce=auth.pending['nonce'] if auth.pending else 'unused',email='test@example.invalid')
    claims.update(changes)
    return jwt.encode(claims,key,algorithm='RS256',headers={'kid':'test-key'})


def install_jwks(auth,key):
    jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()));jwk['kid']='test-key'
    auth.jwks_cache=({'keys':[jwk]},time.time())


def complete(auth,key,scope=PLAN_SCOPE,**claims):
    encoded=signed_identity(auth,key,**claims)
    payload=dict(id_token=encoded,access_token='test-access',refresh_token='test-refresh',expires_in=3600,token_type='Bearer',scope=scope)
    state=auth.pending['state']
    with patch('cube_ai.chatgpt_auth._json_request',return_value=payload) as call:
        result=auth.callback(dict(state=[state],code=['test-code'],client_id=['oaiapp_test']))
    assert call.call_args.kwargs['data']['client_id']=='oaiapp_test'
    assert call.call_args.kwargs['data']['redirect_uri']=='http://127.0.0.1:12345/auth/callback'
    return result


def test_pkce_stable_host_and_one_time_callback(store,signing_key):
    auth=ChatGPTAuth(store);install_jwks(auth,signing_key)
    query=begin(auth)
    assert query['client_id']==['dynamic_agent_client'] and query['agent_name_hint']==['Cube Atelier']
    expected=base64.urlsafe_b64encode(hashlib.sha256(auth.pending['verifier'].encode()).digest()).decode().rstrip('=')
    assert query['code_challenge']==[expected]
    with patch('cube_ai.chatgpt_auth._json_request') as http:
        with pytest.raises(ValueError):auth.callback({'state':['wrong'],'code':['test']})
        http.assert_not_called()
    assert auth.pending is not None
    complete(auth,signing_key)
    first=store.read();account_id=first['active_account']
    assert auth.pending is None and first['accounts'][account_id]['subject']=='test-subject'
    with pytest.raises(ValueError):auth.callback(dict(state=query['state'],code=['test']))
    again=begin(auth,account_id)
    assert again['client_id']==['oaiapp_test'] and 'agent_name_hint' not in again and 'id_token_hint' in again
    assert again['ext_agent_host_id']==query['ext_agent_host_id'] and again['state']!=query['state']
    assert not LLMClient(store,auth).status()['configured']  # requires an account model choice


@pytest.mark.parametrize('changes',[{'aud':'wrong'},{'nonce':'wrong'},{'iss':'https://wrong.example'},{'exp':1}])
def test_identity_checks(store,signing_key,changes):
    auth=ChatGPTAuth(store);install_jwks(auth,signing_key);begin(auth)
    with pytest.raises(ValueError,match='身份'):complete(auth,signing_key,**changes)
    assert not store.read()['accounts']


def test_signature_forgery_rejected(store,signing_key):
    auth=ChatGPTAuth(store);install_jwks(auth,signing_key);begin(auth)
    forged=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    with pytest.raises(ValueError):complete(auth,forged)
    assert not store.read()['accounts']


def test_missing_issued_id_and_oauth_denial_never_exchange(store):
    auth=ChatGPTAuth(store)
    for extra in ({'error':['access_denied']},{'code':['test']}):
        begin(auth)
        with patch('cube_ai.chatgpt_auth._json_request') as http:
            with pytest.raises(ValueError):auth.callback(dict(state=[auth.pending['state']],**extra))
            http.assert_not_called()


def test_identity_only_cannot_infer(store,signing_key):
    auth=ChatGPTAuth(store);install_jwks(auth,signing_key);begin(auth);complete(auth,signing_key,scope='openid email profile')
    store.save(dict(provider='chatgpt',model='test-model'))
    assert not LLMClient(store,auth).status()['configured']
    with pytest.raises(ValueError,match='套餐'):auth.access_token(store.read()['active_account'])


def test_returning_account_cannot_be_replaced(store,signing_key):
    auth=ChatGPTAuth(store);install_jwks(auth,signing_key);begin(auth);complete(auth,signing_key)
    original=store.read();begin(auth,original['active_account'])
    with pytest.raises(ValueError,match='账户'):complete(auth,signing_key,sub='someone-else')
    assert store.read()==original


def test_refresh_rotates_atomically_and_logout_clears_secrets(store,signing_key):
    auth=ChatGPTAuth(store);install_jwks(auth,signing_key);begin(auth);complete(auth,signing_key)
    data=store.read();aid=data['active_account'];data['accounts'][aid]['expires_at']=0;store.write(data)
    with patch('cube_ai.chatgpt_auth._json_request',return_value=dict(access_token='new-access',refresh_token='new-refresh',expires_in=3600)) as call:
        assert auth.access_token(aid)=='new-access'
        assert auth.access_token(aid)=='new-access'
        assert call.call_count==1 and 'scope' not in call.call_args.kwargs['data']
    assert store.read()['accounts'][aid]['refresh_token']=='new-refresh'
    with patch.object(auth,'discovery',return_value={'revocation_endpoint':ISSUER+'/oauth/revoke'}),patch('cube_ai.chatgpt_auth.requests.post',side_effect=requests.ConnectionError()):
        result=auth.logout(aid)
    assert not result['revoked'] and '未能确认' in result['message']
    saved=store.read()['accounts'][aid]
    assert saved['client_id']=='oaiapp_test' and not any(k in saved for k in ('id_token','refresh_token','access_token'))


@pytest.mark.parametrize('provider',['openai','deepseek','qwen','gemini','ollama','custom'])
def test_provider_request_dialects(store,provider):
    store.save(dict(provider=provider,key='private-test-value',model='test-model',base='http://127.0.0.1:34567/v1'))
    client=LLMClient(store)
    with patch('cube_ai.llm.requests.post') as post:
        post.return_value.status_code=200;post.return_value.json.return_value={}
        client.request([dict(role='user',content='test')],TOOLS,ANSWER_SCHEMA)
        body=post.call_args.kwargs['json']
        assert post.call_args.kwargs['allow_redirects'] is False
        if provider=='openai':assert body['store'] is False and 'max_output_tokens' in body
        else:
            assert body['max_tokens']==3500 and body['tools'][0]['function']['name']=='search_cards'
            assert body['response_format']['type']==PROVIDERS[provider]['format']
            if provider in {'deepseek','qwen','custom'}:assert 'JSON Schema' in body['messages'][0]['content']
        assert 'private-test-value' not in json.dumps(client.status())


def sse(*events):
    response=Mock(status_code=200)
    response.iter_lines.return_value=[line for e in events for line in [('data: '+json.dumps(e)).encode(),b'']]
    return response


def plan_client(store,signing_key):
    auth=ChatGPTAuth(store);install_jwks(auth,signing_key);begin(auth);complete(auth,signing_key)
    store.save(dict(provider='chatgpt',model='test-model'))
    return LLMClient(store,auth)


def test_plan_wire_stream_and_models(store,signing_key):
    client=plan_client(store,signing_key)
    complete_event={'type':'response.completed','response':{'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{}'}]}]}}
    with patch('cube_ai.llm.requests.post',return_value=sse(complete_event)) as post:
        assert client.request([dict(role='system',content='rules')],TOOLS,ANSWER_SCHEMA)['status']=='completed'
        body=post.call_args.kwargs['json']
        assert body['stream'] is True and body['store'] is False and 'max_output_tokens' not in body
        assert body['input'][0]['role']=='developer' and body['tools'][0]['type']=='namespace'
        assert post.call_args.args[0]=='https://api.openai.com/v1/responses'
    result=Mock(status_code=200);result.json.return_value={'models':[{'slug':'hidden','visibility':'hidden'},{'slug':'b','display_name':'B','visibility':'list'},{'slug':'a','visibility':'list'}]}
    with patch('cube_ai.llm.requests.get',return_value=result):assert client.models()==[{'id':'b','label':'B'},{'id':'a','label':'a'}]


@pytest.mark.parametrize('events',[
    [{'type':'response.output_text.delta','delta':'partial'}],
    [{'type':'response.failed','response':{'error':{'code':'subscription_sharing_usage_limit_exceeded'}}}],
    [{'type':'response.incomplete','response':{'error':None}}],
])
def test_stream_needs_terminal_success(store,signing_key,events):
    client=plan_client(store,signing_key)
    with patch('cube_ai.llm.requests.post',return_value=sse(*events)) as call:
        with pytest.raises(ValueError):client.request([dict(role='user',content='test')])
        assert call.call_count==1  # no hidden retries or paid fallback


def test_real_local_http_settings_tool_roundtrip_and_plan(store):
    captured=[]
    class FakeAI(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));captured.append(body)
            if body.get('tools') and not any(m.get('role')=='tool' for m in body['messages']):
                msg=dict(role='assistant',content=None,tool_calls=[dict(id='call1',type='function',function=dict(name='lookup_card',arguments='{"name":"Sun Titan"}'))])
            elif body.get('tools'):
                msg=dict(role='assistant',content=json.dumps(dict(answer='已查到真实 Oracle',swaps=[],cautions=[])))
            else:
                msg=dict(role='assistant',content=json.dumps(dict(BuildSpec().to_dict(),explanation='沿用参数',unapplied_requests=[])))
            raw=json.dumps({'choices':[dict(message=msg,finish_reason='stop')]}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    remote=ThreadingHTTPServer(('127.0.0.1',0),FakeAI);threading.Thread(target=remote.serve_forever,daemon=True).start()
    catalog=Catalog();app=Application(catalog,store)
    local=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app));threading.Thread(target=local.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{local.server_port}'
    try:
        payload=dict(provider='custom',base=f'http://127.0.0.1:{remote.server_port}/v1',model='fake-test-model',key='local-test-secret')
        public=requests.post(url+'/api/ai/settings',json=payload).json()
        assert public['status']['configured'] and 'local-test-secret' not in json.dumps(public)
        assert requests.get(url+'/api/ai/settings',headers={'Host':'evil.example'}).status_code==403
        assert requests.post(url+'/api/ai/settings',json=payload,headers={'Origin':'https://evil.example'}).status_code==403
        assert requests.get(url+'/private/ai-settings.bin').status_code==404
        client=LLMClient(store)
        result=advise(catalog,Knowledge(),BuildSpec(),[],'查看 Sun Titan',client)
        assert result['tools'][0]['name']=='lookup_card' and result['answer']=='已查到真实 Oracle'
        tool_msg=next(m for m in captured[-1]['messages'] if m.get('role')=='tool')
        assert json.loads(tool_msg['content'])['card']['name']=='Sun Titan'
        result=plan('保持配置',BuildSpec(),Knowledge(),client)
        assert result['spec']['size']==600 and result['explanation']=='沿用参数'
    finally:
        local.shutdown();local.server_close();remote.shutdown();remote.server_close();app.executor.shutdown(wait=True)
