from collections import Counter
import pytest

from cube_ai.catalog import Catalog
from cube_ai.forge_classic import classic_min_games,classic_pairings,write_classic_deck


@pytest.mark.parametrize('players',[2,3,4,5,8,11,12])
def test_pairings_cover_every_player_and_reverse_seats(players):
    ids=[f'p{i}' for i in range(players)]
    games=classic_min_games(players);orders=classic_pairings(ids,games)
    assert len(orders)==games
    assert all(len(order)==2 and order[0]!=order[1] for order in orders)
    assert set().union(*(set(order) for order in orders))==set(ids)
    assert all(orders[i]==orders[i+1][::-1] for i in range(0,len(orders),2))
    first=Counter(x[0] for x in orders);second=Counter(x[1] for x in orders)
    assert first==second


def test_invalid_pairing_sizes_are_rejected():
    with pytest.raises(ValueError):classic_pairings(['a','b','c','d'],3)
    with pytest.raises(ValueError):classic_pairings(['a','a'],2)
    with pytest.raises(ValueError):classic_pairings(['a'],2)


def test_server_routes_classic_game_jobs_to_classic_engine(monkeypatch):
    from types import SimpleNamespace
    from cube_ai import forge_classic,server
    from cube_ai.config import BuildSpec
    seen={}
    def fake_simulate(catalog,rows,spec,pods,games,clock,progress,**kwargs):
        seen.update(mode=spec.mode,players=spec.players,pods=pods,games=games,kwargs=kwargs)
        return {'ok':True}
    monkeypatch.setattr(forge_classic,'simulate',fake_simulate)
    spec=BuildSpec.from_dict(dict(mode='classic',players=8))
    result=server.execute_operation(SimpleNamespace(catalog=object()),'forge',spec,[{'name':'card'}],{},lambda _:None)
    assert result=={'ok':True} and seen['mode']=='classic' and seen['games']==8


def test_write_classic_deck_preserves_actual_pool_and_basics(tmp_path):
    catalog=Catalog();names=['Kenrith, the Returned King','Prismatic Vista']
    deck=dict(commander=None,spells=names[:1],lands=names[1:],drafted=names,basics={'W':20,'U':18},deck_policy='quality')
    index={n.casefold():n for n in names+['Plains','Island']}
    path=tmp_path/'deck.dck';result=write_classic_deck(deck,path,index,catalog)
    content=path.read_text(encoding='utf8')
    assert result['total']==40 and result['commander']==0
    assert '[Commander]' not in content and '1 Kenrith, the Returned King' in content
    assert '20 Plains' in content and '18 Island' in content
    deck['drafted']=names[1:]
    with pytest.raises(ValueError,match='未抓到'):write_classic_deck(deck,path,index,catalog)


def test_cache_separates_classic_and_commander_games(tmp_path,monkeypatch):
    from cube_ai import forge,sim_cache
    jar=tmp_path/'engine.jar';java=tmp_path/'java';jar.write_bytes(b'jar');java.write_bytes(b'java')
    decks=tmp_path/'decks';decks.mkdir();(decks/'a.dck').write_text('deck',encoding='utf8')
    keys=[];monkeypatch.setattr(sim_cache,'get',lambda _key:None)
    monkeypatch.setattr(sim_cache,'put',lambda key,*_args:keys.append(key))
    def fake_run(config,_decks,order,seed,clock,out,log_name):
        (out/log_name).write_text('test',encoding='utf8')
        return dict(outcome='win',winner=order[0],wall_seconds=1)
    monkeypatch.setattr(forge,'_run_battle',fake_run)
    base=dict(java=str(java),jar=str(jar),version='fixture',backend='isolated')
    forge._cached_battle(base,decks,['a'],1,30,tmp_path,'first.log')
    forge._cached_battle(dict(base,game_format='Draft'),decks,['a'],1,30,tmp_path,'second.log')
    assert len(keys)==2 and keys[0]!=keys[1]


def test_classic_games_do_not_enter_commander_training(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from cube_ai import forge,surrogate
    folder=tmp_path/'match';folder.mkdir()
    (folder/'report.json').write_text(json.dumps(dict(spec={'mode':'classic'},tables=[],games=[{'outcome':'win'}])),encoding='utf8')
    monkeypatch.setattr(forge,'MATCHES',tmp_path)
    monkeypatch.setattr(surrogate,'engine_scope',lambda:['fixture'])
    result=surrogate.collect(SimpleNamespace(signature='fixture',cards={}))
    assert result['games']==0 and not result['sources'] and not result['groups']


def test_classic_games_do_not_enter_commander_only_entry_diagnostic(tmp_path,monkeypatch):
    import json
    from cube_ai import native_diagnostic
    folder=tmp_path/'matches'/'case';folder.mkdir(parents=True)
    (folder/'report.json').write_text(json.dumps(dict(spec={'mode':'classic'},games=[])),encoding='utf8')
    monkeypatch.setattr(native_diagnostic,'ROOT',tmp_path)
    with pytest.raises(ValueError,match='仅支持三人 Commander'):
        native_diagnostic.load_case('match','case',0)


def test_campaign_skips_only_pairings_with_unsupported_decks(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from cube_ai import forge,forge_classic
    from cube_ai.config import BuildSpec
    cards=['Missing','Swords to Plowshares','Lightning Bolt','Counterspell']
    decks=[dict(seat=i,guild='UW',identity='UW',buildable=True,commander=None,spells=[name],lands=[],
                drafted=[name],basics={'U':39},land_count=39,deck_policy='quality') for i,name in enumerate(cards)]
    monkeypatch.setattr(forge_classic,'audit',lambda *_a,**_k:{'hard_errors':0})
    monkeypatch.setattr(forge_classic,'draft_pod',lambda *_a,**_k:dict(decks=decks,packs=[]))
    monkeypatch.setattr(forge,'configuration',lambda:dict(version='test',backend='isolated'))
    monkeypatch.setattr(forge,'campaign_resources',lambda _workers:dict(workers=1,ceiling=1,dynamic=False))
    monkeypatch.setattr(forge,'card_index',lambda _cfg:{n.casefold():n for n in cards[1:]+['Island']})
    monkeypatch.setattr(forge,'coverage',lambda _rows,_cfg:dict(total=4,supported=3,missing=['Missing']))
    monkeypatch.setattr(forge,'engine_description',lambda _cfg:dict(version='test'))
    monkeypatch.setattr(forge_classic,'cube_report',lambda *_a:None)
    monkeypatch.setattr(forge,'MATCHES',tmp_path)
    def fake_game(_cfg,_deck_dir,order,seed,_clock,out,log):
        (out/log).write_text('fixture game',encoding='utf8')
        return dict(outcome='win',winner=order[0],order=order,seed=seed,log=log,turns=7,wall_seconds=.1,cache_hit=False,diagnostics=[])
    monkeypatch.setattr(forge,'run_battle',fake_game)
    spec=BuildSpec.from_dict(dict(mode='classic',players=4))
    result=forge_classic.simulate(SimpleNamespace(),[{'name':n} for n in cards],spec,pods=1,games_per_pod=4,workers=1)
    assert result['skipped_games']==2 and result['summary']['completed']==2
    assert result['tables'][0]['decks'][0]['unsupported']==['Missing']
    assert result['tables'][0]['decks'][0]['drafted']==['Missing']
    missing_id=result['tables'][0]['decks'][0]['id']
    assert all(missing_id not in r['order'] for r in result['games'])
    assert result['rules']['deck_total_exported']==40 and result['rules']['starting_life']==20
