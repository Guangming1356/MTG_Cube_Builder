"""Experimental spell selection; drafted pool, commander and lands remain fixed."""
from collections import Counter
import random

from .brackets import card_reasons,deck_report,is_gc,profile
from .design import deck_design_report,package_roles
from .draft import opening_test

VARIANTS={
    'conservative':dict(low=10,high=8,swaps=4),
    'balanced':dict(low=12,high=6,swaps=6),
    'protected':dict(low=12,high=6,swaps=6,preserve_finishers=True),
    'tempo':dict(low=14,high=4,swaps=8),
}


def roles(card):
    result={key:int(bool(card[key])) for key in ['creature','interaction','draw','finisher']}
    result.update(low=int(card['mv']<=2),high=int(card['mv']>=6))
    packages=package_roles(card)
    for package,values in packages.items():
        for key,value in values.items():result[package+':'+key]=int(bool(value))
    return result


def revise(catalog,deck,spec,variant='balanced'):
    if not deck['buildable']:return dict(deck)
    options=VARIANTS[variant];cards=catalog.cards
    selected=list(deck['spells']);commander=deck.get('commander');power=profile(spec)
    prefix=([commander] if commander else [])+deck['lands']
    candidates=[name for name in deck['drafted'] if name not in prefix and cards[name]['kind']!='land'
                and (cards[name]['identity']=='C' or set(cards[name]['identity'])<=set(deck['identity']))
                and (not power or not card_reasons(cards[name],spec,power=power))]
    vectors={name:roles(cards[name]) for name in candidates}
    counts=Counter()
    for name in selected:counts.update(vectors[name])
    # Never trade away baseline supply below these floors. Package components
    # also count the always-available commander, as the existing design audit does.
    floors={key:min(counts[key],target) for key,target in [('creature',12),('interaction',6),('draw',4),('finisher',2)]}
    package_counts=Counter(counts)
    commander_roles=roles(cards[commander]) if commander else {}
    if commander:package_counts.update(commander_roles)
    for package,keys in [('sacrifice',['fodder','outlet','reward']),('reanimator',['entry','return_','target'])]:
        if all(package_counts[package+':'+key]>0 for key in keys):
            for key in keys:floors[package+':'+key]=max(0,1-commander_roles.get(package+':'+key,0))
    gc=sum(is_gc(cards[name]) for name in prefix+selected)
    changes=[]
    def exchange(incoming,outgoing):
        nonlocal gc
        if options.get('preserve_finishers') and cards[outgoing]['finisher']:return False
        add=vectors[incoming];remove=vectors[outgoing]
        if cards[incoming]['quality']<cards[outgoing]['quality']-.75:return False
        if any(counts[key]-remove.get(key,0)+add.get(key,0)<floor for key,floor in floors.items()):return False
        delta=int(is_gc(cards[incoming]))-int(is_gc(cards[outgoing]))
        if power and power['deck_gc'] is not None and gc+delta>power['deck_gc']:return False
        selected[selected.index(outgoing)]=incoming;counts.subtract(remove);counts.update(add);gc+=delta
        changes.append(dict(remove=outgoing,add=incoming));return True
    for _ in range(options['swaps']):
        low_need=counts['low']<min(options['low'],len(selected))
        high_need=counts['high']>options['high']
        if not (low_need or high_need):break
        swapped=False
        for goal in (['low'] if low_need else [])+(['high'] if high_need else []):
            incoming=sorted((name for name in candidates if name not in selected and (vectors[name]['low'] if goal=='low' else not vectors[name]['high'])),
                            key=lambda name:(-cards[name]['quality'],cards[name]['mv'],name))
            outgoing=sorted((name for name in selected if not vectors[name]['low'] and (True if goal=='low' else vectors[name]['high'])),
                            key=lambda name:(not vectors[name]['high'],cards[name]['quality'],-cards[name]['mv'],name))
            for add in incoming:
                if any(exchange(add,remove) for remove in outgoing):swapped=True;break
            if swapped:break
        if not swapped:break
    selected.sort(key=lambda name:(-cards[name]['quality'],cards[name]['mv'],name))
    result=dict(deck,spells=selected)
    target=60 if spec.mode=='commander' else 40
    result['ready']=opening_test(catalog,selected,deck['lands'],deck['identity'],target-int(bool(commander)),random.Random(0),hands=0,commander=commander)
    result['basics']=result['ready']['basics'];result['design']=deck_design_report(catalog,result)
    result['bracket']=deck_report(catalog,result,spec)
    result['research_changes']=changes
    assert len(selected)==len(deck['spells']) and set(selected)<=set(deck['drafted'])
    assert len(selected)+len(result['lands'])+sum(result['basics'].values())+int(bool(commander))==target
    assert not result['bracket'] or not result['bracket']['violations']
    return result
