"""Provider profiles and per-installation private storage. Public views never contain keys."""
import ctypes
import json
import os
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit

from .config import ROOT

PROVIDERS = {
    'chatgpt': dict(label='ChatGPT 会员登录（官方预览）', base='https://api.openai.com/v1', model='', style='responses', format='json_schema', token_parameter='', key_required=False,
        help='符合资格的 Plus / Pro 账户可授权使用套餐额度。以官方授权结果为准，与其他接入应用共享用量限制。', docs='https://developers.openai.com/siwc/quickstart'),
    'openai': dict(label='OpenAI API', base='https://api.openai.com/v1', model='gpt-6.1-sol', style='responses', format='json_schema', token_parameter='max_completion_tokens', key_required=True,
        help='使用 OpenAI 平台 API Key，API 费用单独计算。', docs='https://developers.openai.com/api/docs/quickstart'),
    'deepseek': dict(label='DeepSeek', base='https://api.deepseek.com', model='deepseek-flash', style='chat', format='json_object', token_parameter='max_tokens', key_required=True,
        help='使用 DeepSeek 开放平台密钥；默认关闭思考模式以便稳定使用 JSON 与工具。', docs='https://api-docs.deepseek.com/'),
    'qwen': dict(label='通义千问 · 阿里云百炼', base='https://dashscope.aliyuncs.com/compatible-mode/v1', model='qwen-plus', style='chat', format='json_object', token_parameter='max_tokens', key_required=True,
        help='密钥与接口地域必须一致；北京兼容地址为默认值，可改为工作空间专属地址。', docs='https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope'),
    'gemini': dict(label='Google Gemini', base='https://generativelanguage.googleapis.com/v1beta/openai', model='gemini-3.8-flash', style='chat', format='json_schema', token_parameter='max_tokens', key_required=True,
        help='使用 Google AI Studio 的 Gemini API Key，注意账户及地区可用性。', docs='https://ai.google.dev/gemini-api/docs/openai'),
    'ollama': dict(label='Ollama · 本地模型', base='http://127.0.0.1:11434/v1', model='', style='chat', format='json_schema', token_parameter='max_tokens', key_required=False,
        help='需另行安装 Ollama 并下载支持工具调用的模型。先读取模型列表，再选择；本发布包不含模型。', docs='https://docs.ollama.com/api/openai-compatibility'),
    'custom': dict(label='其他 OpenAI 兼容服务', base='', model='', style='chat', format='json_object', token_parameter='max_tokens', key_required=True,
        help='填写服务商提供的兼容 API 地址与模型；模型须支持工具调用及 JSON 输出。密钥将发送到这里填写的地址。', docs=''),
    'offline': dict(label='只使用离线功能', base='', model='', style='chat', format='none', token_parameter='max_tokens', key_required=False,
        help='生成、审计、轮抓、Forge 和本地知识检索均可使用。', docs=''),
}
_locks = {}
_locks_guard = threading.Lock()


def validate_base(value):
    if not isinstance(value, str) or len(value) > 500: raise ValueError('接口地址无效')
    p = urlsplit(value)
    if p.username or p.password or p.query or p.fragment or not p.hostname:
        raise ValueError('接口地址不能包含账号、密钥、查询参数或片段')
    if p.scheme != 'https' and not (p.scheme == 'http' and p.hostname in {'127.0.0.1', 'localhost', '::1'}):
        raise ValueError('远程接口必须使用 HTTPS；本地模型可使用回环 HTTP 地址')
    try: p.port
    except ValueError: raise ValueError('接口端口无效') from None
    return value.rstrip('/')


def _dpapi(raw, decrypt=False):
    """Protect Windows secrets for the signed-in OS user, without machine-wide flags."""
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buf = ctypes.create_string_buffer(raw)
    src = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))); dst = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]; kernel.LocalFree.restype = ctypes.c_void_p
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dst)):
        raise ValueError('Windows 无法读取或保护 AI 设置；请使用保存它的 Windows 账户')
    try: return ctypes.string_at(dst.data, dst.size)
    finally: kernel.LocalFree(dst.data)


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else ROOT/'private'/'ai-settings.bin'
        with _locks_guard: self.lock = _locks.setdefault(str(self.path.resolve()), threading.RLock())

    def read(self):
        with self.lock:
            if not self.path.exists(): return dict(profiles={}, accounts={})
            try:
                raw = self.path.read_bytes()
                if raw.startswith(b'DPAPI1\n'): raw = _dpapi(raw[7:], True)
                elif raw.startswith(b'UNIX1\n') and os.name != 'nt': raw = raw[6:]
                else: raise ValueError('无法识别本地 AI 设置')
                return json.loads(raw)
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise ValueError('本地 AI 设置无法读取；请检查文件权限') from None

    def write(self, data):
        with self.lock:
            raw = json.dumps(data, ensure_ascii=False).encode('utf8')
            raw = b'DPAPI1\n'+_dpapi(raw) if os.name == 'nt' else b'UNIX1\n'+raw
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='ai-', suffix='.tmp', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'wb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
                if os.name != 'nt': os.chmod(name, 0o600)
                os.replace(name, self.path)
            finally:
                if os.path.exists(name): os.unlink(name)

    def config(self):
        data = self.read(); provider = data.get('provider')
        if provider is None:
            provider = 'openai'
            p = dict(PROVIDERS[provider], key=os.getenv('OPENAI_API_KEY', ''),
                model=os.getenv('OPENAI_MODEL', 'gpt-6-astra'), style=os.getenv('CUBE_API_STYLE', 'responses'),
                base=os.getenv('OPENAI_BASE_URL', PROVIDERS[provider]['base']).rstrip('/'))
            if p['style'] not in {'chat', 'responses'}: raise ValueError('CUBE_API_STYLE 应为 responses 或 chat')
        else: p = dict(PROVIDERS[provider], **data.get('profiles', {}).get(provider, {}))
        p['provider'] = provider
        p['account_id'] = data.get('active_account', '') if provider == 'chatgpt' else ''
        p.setdefault('key', '')
        return p

    def save(self, payload):
        if not isinstance(payload, dict): raise ValueError('AI 设置必须是对象')
        provider = payload.get('provider')
        if provider not in PROVIDERS: raise ValueError('请选择支持的 AI 服务')
        with self.lock:
            data = self.read(); defaults = PROVIDERS[provider]
            prev = data['profiles'].get(provider, {})
            if not prev and 'provider' not in data and provider=='openai':
                legacy=self.config()
                prev={k:legacy[k] for k in ('base','model','style','format','token_parameter','key')}
            cfg = {k: payload.get(k, prev.get(k, defaults[k])) for k in ('base', 'model', 'style', 'format', 'token_parameter')}
            if provider not in {'offline', 'chatgpt'}:
                cfg['base'] = validate_base(cfg['base'])
                if not isinstance(cfg['model'], str) or len(cfg['model']) > 150 or any(ord(x)<32 for x in cfg['model']):
                    raise ValueError('模型名称无效')
                cfg['model'] = cfg['model'].strip()
            elif provider == 'chatgpt':
                cfg['base'] = defaults['base']; cfg['style'] = 'responses'; cfg['format'] = 'json_schema'
                if not isinstance(cfg['model'], str) or len(cfg['model']) > 150: raise ValueError('模型名称无效')
            if cfg['style'] not in {'chat','responses'} or cfg['format'] not in {'none','json_object','json_schema'}:
                raise ValueError('接口或 JSON 输出模式无效')
            if cfg['token_parameter'] not in {'max_tokens','max_completion_tokens',''}: raise ValueError('输出长度参数无效')
            key = payload.get('key', '')
            if not isinstance(key, str) or len(key)>8000 or any(ord(x)<32 for x in key): raise ValueError('密钥格式无效')
            key = key.strip()
            if prev.get('key') and cfg['base'] != prev.get('base') and not key and not payload.get('clear_key'):
                raise ValueError('更换接口地址时请重新填写密钥，避免把原密钥发往新地址')
            cfg['key'] = '' if payload.get('clear_key') else key or prev.get('key', '')
            if provider in {'chatgpt','offline'}: cfg['key'] = ''
            data['profiles'][provider] = cfg; data['provider'] = provider
            self.write(data)
        return self.public()

    def public(self):
        data = self.read(); active = self.config()
        profiles = {}
        for name, defaults in PROVIDERS.items():
            p = dict(defaults, **data.get('profiles', {}).get(name, {}))
            if name == active['provider'] and 'provider' not in data: p.update(active)
            profiles[name] = {k: v for k,v in p.items() if k not in {'key','account_id','provider'}}
            profiles[name]['key_present'] = bool(p.get('key'))
        accounts = [dict(id=k, label=(v.get('email') or 'ChatGPT 账户')+' · '+v['client_id'][-8:],
                         connected=bool(v.get('refresh_token') or v.get('access_token')),
                         plan_enabled='chatgpt.tokens.use.direct' in v.get('scopes', []))
                    for k,v in data.get('accounts', {}).items()]
        return dict(provider=active['provider'], profiles=profiles, accounts=accounts,
                    active_account=data.get('active_account', ''), encrypted=os.name=='nt')

    def select_account(self, account_id):
        with self.lock:
            data = self.read()
            if account_id not in data['accounts']: raise ValueError('账户不存在')
            data['active_account'] = account_id; data['provider'] = 'chatgpt'
            # Never carry a model choice from a different account's catalog.
            data['profiles'].setdefault('chatgpt', {})['model'] = ''
            self.write(data)
        return self.public()
