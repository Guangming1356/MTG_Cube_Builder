"""Malformed/old game labels must not hide failures in raw native evidence."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from cube_ai import forge, sim_cache, surrogate

WIN = 'Game Result: Game 1 ended in 10 ms. Ai(1)-a has won!'
DRAW = 'Game Result: Game 1 ended in a Draw! Took 10 ms.'


@pytest.mark.parametrize('header', [
    'java.util.concurrent.TimeoutException',
    'java.lang.OutOfMemoryError',
    'java.lang.IllegalStateException: original cause',
    'Exception',
    'Error',
    'Caused by: java.util.concurrent.TimeoutException',
    '\tSuppressed: java.lang.IllegalStateException',
    'Exception in thread "AI worker" java.lang.OutOfMemoryError',
])
@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_bare_exception_overrides_trailing_winner(header, newline):
    result = forge.parse_log(header + newline + WIN)
    assert result['outcome'] == 'engine_error'
    assert result['winner'] is None
    assert result['error'] == header.strip()


def test_announced_time_limit_keeps_expected_interruptions_separate():
    stopped = 'Stopping slow match as draw\njava.lang.InterruptedException\n' + DRAW
    assert forge.parse_log(stopped)['outcome'] == 'engine_timeout'
    assert not forge.diagnose_log(stopped)
    failed = 'java.util.concurrent.TimeoutException\n' + stopped
    result = forge.parse_log(failed)
    assert result['outcome'] == 'engine_error'
    assert result['diagnostics'][0]['code'] == 'ai_choice_timeout'


def test_non_exception_game_text_is_not_an_exception_header():
    text = 'Resolve Stack: Error\nAdd To Stack: a cast Experimental Synthesizer\n' + WIN
    assert forge.parse_log(text)['outcome'] == 'win'


@pytest.mark.parametrize('log,stored_outcome,stored_winner,should_reuse', [
    (WIN, 'win', 'a', True),
    (DRAW, 'draw', None, True),
    ('java.util.concurrent.TimeoutException\n' + WIN, 'win', 'a', False),
    ('java.lang.OutOfMemoryError\n' + WIN, 'win', 'a', False),
    ('Stopping slow match as draw\n' + DRAW, 'draw', None, False),
    (WIN, 'win', 'b', False),
    (WIN.replace('Ai(1)-a', 'Ai(1)-unknown'), 'win', 'unknown', False),
    ('incomplete output', 'win', 'a', False),
])
def test_cached_result_is_revalidated_against_raw_log(tmp_path, monkeypatch,
        log, stored_outcome, stored_winner, should_reuse):
    for name in ('jar', 'java', 'a.dck', 'b.dck', 'c.dck'):
        (tmp_path / name).write_text(name)
    record = dict(outcome=stored_outcome, winner=stored_winner,
                  wall_seconds=2, turns=999, returncode=0)
    cached = dict(record=record, log=log)
    monkeypatch.setattr(sim_cache, 'get', lambda key: cached)
    writes = []
    monkeypatch.setattr(sim_cache, 'put', lambda *args: writes.append(args))
    calls = []

    def fresh(*args):
        calls.append(True)
        (tmp_path / 'out.log').write_text(WIN)
        return dict(forge.parse_log(WIN), wall_seconds=1)

    monkeypatch.setattr(forge, '_run_battle', fresh)
    config = dict(jar=str(tmp_path / 'jar'), java=str(tmp_path / 'java'))
    result = forge._cached_battle(config, tmp_path, ['a', 'b', 'c'], 42, 90, tmp_path, 'out.log')
    assert result['cache_hit'] is should_reuse
    assert len(calls) == (0 if should_reuse else 1)
    if should_reuse:
        assert result['turns'] is None  # Parsed raw facts override stale metadata.
        assert not writes
    else:
        assert result['outcome'] == 'win' and result['winner'] == 'a'
        assert len(writes) == 1
    assert cached == dict(record=record, log=log)  # Historical evidence stays intact.


def test_training_rechecks_saved_labels_before_extracting_any_features(tmp_path, monkeypatch):
    matches=tmp_path/'matches';folder=matches/'old';folder.mkdir(parents=True)
    scope=['jar','java','resident','bridge']
    monkeypatch.setattr(forge,'MATCHES',matches)
    monkeypatch.setattr(surrogate,'engine_scope',lambda:scope)
    decks=[dict(id=n,commander='cmd',spells=[],lands=[],basics={'U':59},buildable=True) for n in 'abc']
    records=[]
    logs=[WIN,'java.util.concurrent.TimeoutException\n'+WIN,'java.lang.OutOfMemoryError\n'+WIN,WIN]
    for i,log in enumerate(logs):
        name=f'{i}.log';(folder/name).write_text(log)
        records.append(dict(pod=0,order=list('abc'),seed=i,outcome='win',winner='b' if i==3 else 'a',log=name,backend='resident-1'))
    report=dict(match_id='old',cube_sha256='cube',engine=dict(fingerprint=scope,jar_sha256='jar'),
                tables=[dict(pod=0,decks=decks)],games=records)
    raw=json.dumps(report);(folder/'report.json').write_text(raw)
    calls=[]

    def trace(*args,**kwargs):
        calls.append(True)
        return dict(players={n:dict(complete_early_cycles=4,no_action_cycle_rate=.25,
                    spellcasts=5,own_turns=5,finisher_casts=1) for n in 'abc'})

    from cube_ai import optimize
    monkeypatch.setattr(optimize,'game_trace',trace)
    monkeypatch.setattr(surrogate,'deck_vector',lambda *args:np.zeros(18))
    result=surrogate.collect(SimpleNamespace(signature='catalog'))
    assert result['games']==1 and result['excluded_evidence_games']==3
    assert result['x'].shape==(3,54) and result['y'].shape==(3,3)
    assert len(calls)==1
    assert (folder/'report.json').read_text()==raw


@pytest.mark.parametrize('report_catalog',[None,'different'])
def test_report_for_unknown_or_different_catalog_is_not_compatible(report_catalog,monkeypatch):
    scope=['engine'];monkeypatch.setattr(surrogate,'engine_scope',lambda:scope)
    folder=surrogate.MODELS/'old';folder.mkdir(parents=True)
    (folder/'report.json').write_text(json.dumps(dict(id='old',version=surrogate.VERSION,engine=scope,catalog=report_catalog)))
    status=surrogate.status(SimpleNamespace(signature='current'))
    assert status['latest']['id']=='old' and status['latest_compatible'] is False


def test_newer_report_from_another_catalog_does_not_hide_current_report(monkeypatch):
    scope=['engine'];monkeypatch.setattr(surrogate,'engine_scope',lambda:scope)
    for name,catalog in [('20260101_current','current'),('20260102_other','other')]:
        folder=surrogate.MODELS/name;folder.mkdir(parents=True)
        (folder/'report.json').write_text(json.dumps(dict(id=name,version=surrogate.VERSION,engine=scope,catalog=catalog)))
    status=surrogate.status(SimpleNamespace(signature='current'))
    assert status['latest']['id']=='20260101_current' and status['latest_compatible']
