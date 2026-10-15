"""Official Sign in with ChatGPT public-client flow. Never reads browser/Codex credentials."""
import base64
import hashlib
import json
import secrets
import threading
import time
import uuid
import webbrowser
from urllib.parse import urlencode, urlsplit

import jwt
import requests

from .ai_settings import SettingsStore

ISSUER = 'https://auth.openai.com'
AUTHORIZE = ISSUER+'/api/accounts/authorize'
TOKEN = ISSUER+'/api/accounts/oauth/token'
RESOURCE = 'https://api.openai.com/v1'
SCOPES = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
PLAN_SCOPE = 'chatgpt.tokens.use.direct'
_refresh_locks = {}
_guard = threading.Lock()


def _official_url(value):
    p = urlsplit(value)
    if p.scheme != 'https' or p.netloc != 'auth.openai.com' or p.fragment or p.username:
        raise ValueError('官方登录端点校验失败')
    return value


def _json_request(method, url, **kwargs):
    try:
        response = getattr(requests, method)(url, timeout=(15,45), allow_redirects=False, **kwargs)
        if not 200 <= response.status_code < 300:
            raise ValueError(f'ChatGPT 授权接口返回 HTTP {response.status_code}；请重新登录或检查账户权限')
        data = response.json()
        if not isinstance(data, dict): raise ValueError('ChatGPT 授权响应格式无效')
        return data
    except (requests.RequestException, json.JSONDecodeError):
        raise ValueError('无法连接 ChatGPT 官方授权服务，请检查网络后重试') from None


class ChatGPTAuth:
    def __init__(self, store=None):
        self.store = store or SettingsStore(); self.lock = threading.RLock()
        self.pending = None; self.message = ''; self.phase = 'idle'; self.generation = 0
        self.discovery_cache = None; self.jwks_cache = None
        with _guard: self.refresh_lock = _refresh_locks.setdefault(str(self.store.path.resolve()), threading.RLock())

    def status(self):
        with self.lock:
            if self.pending and time.time() > self.pending['expires_at']:
                self.pending = None; self.phase = 'failed'; self.message = '登录已超时，请重新点击登录'
            return dict(phase=self.phase, message=self.message)

    def begin(self, port, account_id='', opener=None):
        with self.lock, self.store.lock:
            if self.phase=='exchanging': raise ValueError('正在处理登录回调，请等待完成后重试')
            data = self.store.read(); account = data['accounts'].get(account_id) if account_id else None
            if account_id and not account: raise ValueError('请选择已有账户或添加新账户')
            host = data.setdefault('ext_agent_host_id', 'urn:uuid:'+str(uuid.uuid4()))
            self.store.write(data)
            verifier = secrets.token_urlsafe(64); state = secrets.token_urlsafe(32); nonce = secrets.token_urlsafe(32)
            redirect = f'http://127.0.0.1:{int(port)}/auth/callback'
            client_id = account['client_id'] if account else 'dynamic_agent_client'
            self.generation += 1
            self.pending = dict(state=state, nonce=nonce, verifier=verifier, redirect_uri=redirect,
                client_id=client_id, account_id=account_id, expires_at=time.time()+600, generation=self.generation)
            params = dict(client_id=client_id, ext_agent_host_id=host, response_type='code', redirect_uri=redirect,
                scope=SCOPES, resource=RESOURCE, state=state, nonce=nonce, code_challenge_method='S256',
                code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('='))
            if not account: params['agent_name_hint'] = 'Cube Atelier'
            elif account.get('id_token'): params['id_token_hint'] = account['id_token']
            self.phase = 'pending'; self.message = '请在打开的官方网页中登录并授权，完成后返回这里'
            # The authorization URL may contain an identity hint. Keep it off the local API and logs.
            try: opened = (opener or webbrowser.open)(AUTHORIZE+'?'+urlencode(params))
            except Exception: opened = False
            if opened is False:
                self.pending = None; self.phase = 'failed'; self.message = '无法打开系统浏览器，请检查默认浏览器后重试'
            return self.status()

    def discovery(self):
        if not self.discovery_cache:
            doc = _json_request('get', ISSUER+'/.well-known/openid-configuration')
            if doc.get('issuer') != ISSUER: raise ValueError('ChatGPT 登录发行方校验失败')
            _official_url(doc['jwks_uri'])
            self.discovery_cache = doc
        return self.discovery_cache

    def verify_identity(self, encoded, client_id, nonce=None):
        try:
            header = jwt.get_unverified_header(encoded)
            if header.get('alg') not in {'RS256','RS384','RS512','ES256','ES384','ES512'}: raise ValueError()
            for refresh in (False, True):
                if refresh or not self.jwks_cache:
                    self.jwks_cache = (_json_request('get', _official_url(self.discovery()['jwks_uri'])), time.time())
                keys, saved = self.jwks_cache
                if time.time()-saved > 3600 and not refresh: continue
                candidates = [k for k in keys.get('keys', []) if k.get('kid') == header.get('kid') and k.get('use','sig')=='sig']
                if not candidates: continue
                key = jwt.PyJWK.from_dict(candidates[0], algorithm=header['alg']).key
                claims = jwt.decode(encoded, key, algorithms=[header['alg']], audience=client_id, issuer=ISSUER,
                    leeway=5, options={'require':['sub','exp','iat','iss','aud']})
                if not isinstance(claims['sub'],str) or not claims['sub']: raise ValueError()
                if nonce is not None and not secrets.compare_digest(str(claims.get('nonce','')), nonce): raise ValueError()
                return claims
        except (jwt.PyJWTError, KeyError, TypeError, ValueError): pass
        raise ValueError('ChatGPT 身份签名、账户或登录随机数校验失败；请重新登录')

    @staticmethod
    def token_fields(tokens, previous=None):
        previous = previous or {}
        scope = tokens.get('scope')
        scopes = scope.split() if isinstance(scope,str) else previous.get('scopes', [])
        expiry = tokens.get('expires_in', 3600)
        if type(expiry) not in {int,float} or not 0 < expiry < 365*86400: raise ValueError('授权有效期无效')
        if tokens.get('token_type','Bearer').lower() != 'bearer': raise ValueError('不支持的授权令牌类型')
        access = tokens.get('access_token', '')
        refresh = tokens.get('refresh_token', previous.get('refresh_token',''))
        if not isinstance(access,str) or not isinstance(refresh,str): raise ValueError('授权令牌格式无效')
        if PLAN_SCOPE in scopes and not access: raise ValueError('未收到可调用模型的授权，请重新登录')
        return dict(access_token=access, refresh_token=refresh, scopes=scopes, expires_in=expiry,
                    expires_at=time.time()+expiry, token_type='Bearer', saved_at=time.time())

    def callback(self, params):
        # Consume a matching transaction once. A stray callback cannot erase a valid pending attempt.
        with self.lock:
            attempt = self.pending
            values = lambda k: params.get(k, [''])[0] if len(params.get(k, ['']))==1 else ''
            if not attempt or not secrets.compare_digest(values('state'), attempt['state']) or time.time()>attempt['expires_at']:
                raise ValueError('登录回调已过期或校验失败，请重新登录')
            self.pending = None; self.phase = 'exchanging'; self.message = '正在验证官方授权'
        try:
            if values('error'): raise ValueError('未获得授权；请确认账户资格并在官方页面允许使用套餐额度')
            client_id = values('client_id') or (attempt['client_id'] if attempt['account_id'] else '')
            if not client_id or client_id == 'dynamic_agent_client' or len(client_id)>250:
                raise ValueError('注册未完成：官方回调未提供应用编号，请重新登录')
            if attempt['account_id'] and client_id != attempt['client_id']: raise ValueError('登录返回了不同的应用编号')
            if not values('code'): raise ValueError('官方回调没有授权码')
            tokens = _json_request('post', TOKEN, data=dict(grant_type='authorization_code', client_id=client_id,
                code=values('code'), code_verifier=attempt['verifier'], redirect_uri=attempt['redirect_uri'], resource=RESOURCE))
            claims = self.verify_identity(tokens.get('id_token',''), client_id, attempt['nonce'])
            fields = self.token_fields(tokens)
            with self.lock, self.store.lock:
                if self.generation != attempt['generation']:raise ValueError('此登录已取消，请重新发起登录')
                data = self.store.read(); old = data['accounts'].get(attempt['account_id'])
                if old and (old['subject'] != claims['sub'] or old['issuer'] != claims['iss']):
                    raise ValueError('此次登录账户与所选账户不同，请用“添加账户”重新登录')
                account_id = hashlib.sha256((ISSUER+'\0'+client_id+'\0'+claims['sub']).encode()).hexdigest()[:32]
                data['accounts'][account_id] = dict(fields, client_id=client_id, issuer=claims['iss'], subject=claims['sub'],
                    email=claims.get('email',''), id_token=tokens['id_token'], ext_agent_host_id=data['ext_agent_host_id'])
                data['active_account'] = account_id; data['provider'] = 'chatgpt'
                data['profiles'].setdefault('chatgpt', {})['model'] = ''
                self.store.write(data)
            with self.lock:
                self.phase = 'done'
                self.message = '登录完成，请读取模型列表并选择模型' if PLAN_SCOPE in fields['scopes'] else '已确认身份，但未获准使用套餐额度；请重新授权或选择其他服务'
            return self.status()
        except Exception as e:
            with self.lock: self.phase = 'failed'; self.message = str(e) if isinstance(e,ValueError) else '登录验证失败，请重试'
            if isinstance(e,ValueError): raise
            raise ValueError('登录验证失败，请重试') from None

    def access_token(self, account_id):
        with self.refresh_lock:
            data = self.store.read(); account = data['accounts'].get(account_id)
            if not account or PLAN_SCOPE not in account.get('scopes', []): raise ValueError('请先登录并授权 ChatGPT 套餐使用权限')
            if account.get('access_token') and account.get('expires_at',0)>time.time()+90: return account['access_token']
            if not account.get('refresh_token'): raise ValueError('ChatGPT 登录已过期，请重新登录')
            tokens = _json_request('post', TOKEN, data=dict(grant_type='refresh_token', client_id=account['client_id'],
                refresh_token=account['refresh_token'], resource=RESOURCE))
            fields = self.token_fields(tokens, account)
            if PLAN_SCOPE not in fields['scopes']: raise ValueError('ChatGPT 套餐使用权限已失效，请重新授权')
            if tokens.get('id_token'):
                claims = self.verify_identity(tokens['id_token'], account['client_id'])
                if claims['sub'] != account['subject']: raise ValueError('刷新令牌的账户不一致，请重新登录')
                fields['id_token'] = tokens['id_token']
            with self.store.lock:
                fresh = self.store.read()
                if fresh['accounts'].get(account_id, {}).get('refresh_token') != account['refresh_token']:
                    raise ValueError('登录状态已变化，请重新发起请求')
                fresh['accounts'][account_id].update(fields); self.store.write(fresh)
            return fields['access_token']

    def logout(self, account_id):
        with self.lock, self.refresh_lock:
            self.pending = None; self.phase = 'idle'; self.message = ''; self.generation += 1
            data = self.store.read(); account = data['accounts'].get(account_id)
            if not account: raise ValueError('请选择要退出的账户')
            revoked = False
            try:
                endpoint = _official_url(self.discovery().get('revocation_endpoint',''))
                token = account.get('refresh_token') or account.get('access_token')
                if token:
                    response = requests.post(endpoint, data=dict(token=token, token_type_hint='refresh_token' if account.get('refresh_token') else 'access_token', client_id=account['client_id']), timeout=(15,30), allow_redirects=False)
                    revoked = 200 <= response.status_code < 300
            except (ValueError,KeyError,requests.RequestException): pass
            with self.store.lock:
                data = self.store.read()
                for key in ('access_token','refresh_token','id_token','expires_at','scopes'):
                    data['accounts'][account_id].pop(key, None)
                self.store.write(data)
            return dict(message='已退出登录并撤销授权' if revoked else '已清除本机登录。远端撤销未能确认，可到 ChatGPT 设置中断开此应用。', revoked=revoked)
