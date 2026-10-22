import json
from types import SimpleNamespace

import pytest

from cube_ai.cube_family import group_cubes,pool_counts
from cube_ai import surrogate


def rows(names,role='Main'):
    return [dict(name=n,role=role) for n in names]


def test_pool_identity_ignores_row_order_and_resolves_oracle_identity():
    catalog=SimpleNamespace(cards={'Name A':{'oracle_id':'one'},'Alias A':{'oracle_id':'one'}})
    a=pool_counts(rows(['Name A','Second']),catalog)
    b=pool_counts(list(reversed(rows(['Alias A','Second']))),catalog)
    families,report=group_cubes({'a':a,'b':b},threshold=1)
    assert a==b and families['a']==families['b']
    assert report['canonical_pools']==report['families']==1


def test_pool_roles_and_multiplicity_are_not_erased():
    a=pool_counts(rows(['A','A','B']))
    b=pool_counts(rows(['A','B','B']))
    c=pool_counts(rows(['A','A','B'],'Commander'))
    families,report=group_cubes({'a':a,'b':b,'c':c},threshold=1)
    assert len(set(families.values()))==3 and report['canonical_pools']==3


def test_similarity_chain_stays_one_family_even_when_endpoints_differ():
    pools={label:pool_counts(rows([str(n) for n in range(start,start+100)])) for label,start in [('a',0),('b',5),('c',10)]}
    families,report=group_cubes(pools)
    assert len(set(families.values()))==1
    assert {(p['a'],p['b']) for p in report['links']}=={('a','b'),('b','c')}


def test_bitset_similarity_matches_multiset_jaccard_with_duplicate_cards():
    a=pool_counts(rows(['A']*8+['B']*2));b=pool_counts(rows(['A']*7+['B']*3))
    _,report=group_cubes({'a':a,'b':b},threshold=.8)
    assert report['links'][0]['jaccard']==pytest.approx(9/11)
    families,_=group_cubes({'a':a,'b':b},threshold=.9)
    assert families['a']!=families['b']


@pytest.mark.parametrize('bad',[[],[{'name':'A'}],[{'name':'','role':'Main'}]])
def test_missing_or_invalid_pool_metadata_is_not_silently_a_new_family(bad):
    with pytest.raises((ValueError,KeyError)):pool_counts(bad)


def test_size_bound_does_not_merge_an_undersized_subset():
    a=pool_counts(rows([str(i) for i in range(100)]));b=pool_counts(rows([str(i) for i in range(80)]))
    families,report=group_cubes({'a':a,'b':b})
    assert families['a']!=families['b'] and not report['links']


def test_family_and_shared_individual_deck_do_not_cross_split_parts():
    groups=[f'g{i}' for i in range(20)];cubes=[f'c{i}' for i in range(20)]
    families=[f'f{i//2}' for i in range(20)]
    entities={'g0':['shared','left'],'g8':['shared','right']}
    labels,method=surrogate.split_groups(groups,cubes,families,entities)
    assert method=='cube_family_and_deck_group'
    assert labels[0]==labels[1]==labels[8]==labels[9]
    for family in set(families):assert len({labels[i] for i,f in enumerate(families) if f==family})==1


def test_insufficient_families_never_fall_back_to_splitting_the_same_pool():
    groups=[f'g{i}' for i in range(30)];cubes=[f'c{i}' for i in range(30)]
    labels,method=surrogate.split_groups(groups,cubes,['one-family']*30)
    assert method=='insufficient_cube_families' and set(labels)=={'train'}


def test_inconsistent_group_metadata_is_rejected():
    with pytest.raises(ValueError):surrogate.split_groups(['a'],['x'],[])


def test_missing_pool_provenance_never_overwrites_an_existing_model(monkeypatch):
    import numpy as np
    data=dict(x=np.zeros((60,54),dtype=np.float32),y=np.zeros((60,3),dtype=np.float32),
              groups=[f'g{i//3}' for i in range(60)],cubes=['unknown']*60,
              games=20,sources=['unverified'],family_scope_complete=False)
    surrogate.MODELS.mkdir();path=surrogate.MODELS/'active.json';saved=json.dumps(dict(version='legacy',active=True))
    path.write_text(saved)
    monkeypatch.setattr(surrogate,'collect',lambda *args:data)
    result=surrogate.train(SimpleNamespace(signature='fixture'))
    assert not result['active'] and '原始 Cube' in result['reason']
    assert not (surrogate.MODELS/result['id']/'model.json').exists()
    assert path.read_text()==saved
