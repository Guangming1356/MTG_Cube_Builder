"""Tests must never load the user's saved AI sessions or reach paid providers."""
from urllib.parse import urlsplit

import pytest
import requests


@pytest.fixture(autouse=True)
def isolate_ai_credentials(tmp_path,monkeypatch):
    from cube_ai import ai_settings
    from cube_ai import sim_cache
    from cube_ai import surrogate
    from cube_ai import tuning
    from cube_ai import server,task_process,legacy_tasks
    monkeypatch.setattr(ai_settings,'ROOT',tmp_path/'test-installation')
    monkeypatch.setattr(sim_cache,'CACHE',tmp_path/'simulation.sqlite')
    monkeypatch.setattr(surrogate,'MODELS',tmp_path/'models')
    monkeypatch.setattr(tuning,'PROFILE',tmp_path/'performance-profile.json')
    monkeypatch.setattr(tuning,'RUNS',tmp_path/'tuning')
    monkeypatch.setattr(server,'DEFAULT_ISOLATED_JOBS',False)
    monkeypatch.setattr(task_process,'JOBS',tmp_path/'jobs')
    monkeypatch.setattr(legacy_tasks,'discover',lambda:[])
    for name in ('OPENAI_API_KEY','OPENAI_MODEL','OPENAI_BASE_URL','CUBE_API_STYLE'):
        monkeypatch.delenv(name,raising=False)
    original=requests.sessions.Session.request
    def local_only(session,method,url,*args,**kwargs):
        if urlsplit(url).hostname not in {'127.0.0.1','localhost','::1'}:
            raise AssertionError('自动测试禁止访问真实 AI 或其他外网接口；请使用本地服务器或模拟响应')
        return original(session,method,url,*args,**kwargs)
    monkeypatch.setattr(requests.sessions.Session,'request',local_only)
