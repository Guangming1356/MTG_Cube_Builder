"""Bounded, sourced design priors and component-chain diagnostics.

These are versioned design hypotheses, not labels of card power or game wins.
References never bypass the catalog's legalities and user exclusion filters.
"""
import json
import re
from functools import lru_cache
from .config import ROOT, GUILDS

VERSION = 'cube-design-1.0'
PACKAGE_LABELS = {
    'sacrifice': {'fodder':'牺牲材料','outlet':'牺牲出口','reward':'死亡回报'},
    'reanimator': {'entry':'送入坟场','return':'返场咒语','target':'大型返场目标'},
}

@lru_cache(maxsize=1)
def studies():
    return json.loads((ROOT/'data'/'cube_studies.json').read_text(encoding='utf-8'))

def reference_prior(card, spec):
    group='commander' if spec.mode=='commander' else 'fair'
    matches=[m['id'] for m in studies()['membership'].get(card['name'],[]) if m['group']==group]
    return min(.08,.04*len(matches)), matches

def design_bonus(card,spec):
    ref,_=reference_prior(card,spec)
    # Require both an independent role and different applicable themes; count themes,
    # not guilds (one generic cantrip does not become a bridge just by fitting ten guilds).
    themes=set(card.get('enablers',[])+card.get('payoffs',[])) - {'draw','control'}
    available=set()
    for g in GUILDS:
        if card['identity']=='C' or set(card['identity'])<=set(g):available.update(spec.pair_themes.get(g,[]))
    independent=card['quality']>=3 and any(card.get(k) for k in ['creature','interaction','draw','ramp','finisher'])
    bridge=.02*min(2,max(0,len(themes & available)-1)) if independent else 0
    return ref+bridge

def package_roles(card):
    return _package_roles(card.get('text','').lower(),bool(card.get('creature',False)),card.get('mv',0))

@lru_cache(maxsize=40000)
def _package_roles(t,creature,mv):
    # Conservative text matches. Incomplete recognition is reported, not asserted
    # to be definitive Oracle semantics. Treasure alone is not creature fodder.
    creature_token=bool(re.search(r'create[^.\n]*creature tokens?',t))
    reusable=bool(re.search(r'return [^.\n]*from your graveyard to (?:the battlefield|your hand)',t))
    outlet=bool(re.search(r'sacrifice (?:another |a |an |one or more )?creatures?[^.\n:]{0,100}:',t)
        or re.search(r'you may sacrifice (?:another |a |an )?creature',t))
    reward=bool(re.search(r'whenever [^.\n]*(?:creature|permanent)[^.\n]*(?:dies|die|is put into a graveyard)',t)
        or re.search(r'whenever you sacrifice (?:a |another |one or more )?(?:creature|permanent)',t))
    entry=bool(re.search(r'\b(?:mill|discard)\b',t))
    returning=bool(re.search(r'return [^.\n]*creature cards?[^.\n]*from [^.\n]*graveyard[^.\n]*to the battlefield',t)
        or re.search(r'put [^.\n]*creature cards?[^.\n]*from [^.\n]*graveyard[^.\n]*onto the battlefield',t))
    return {'sacrifice':dict(fodder=creature_token or (creature and reusable),outlet=outlet,reward=reward),
            'reanimator':dict(entry=entry,return_=returning,target=creature and mv>=5)}

def package_report(cards,themes=None):
    reports={}
    tags=set(themes or [])
    for package,labels in PACKAGE_LABELS.items():
        components={}
        for key,label in labels.items():
            role_key='return_' if key=='return' else key
            names=[c['name'] for c in cards if package_roles(c)[package][role_key]]
            components[key]=dict(label=label,count=len(names),examples=names[:6])
        # A token maker alone is not evidence of a sacrifice deck. Dedicated
        # reward / reanimation cards activate the diagnostic even without a preset.
        payoff_key='reward' if package=='sacrifice' else 'return'
        active=package in tags or components[payoff_key]['count']>0
        missing=[key for key,v in components.items() if not v['count']] if active else []
        reports[package]=dict(active=active,components=components,missing=missing,
            status='需检查配合' if missing else '识别到完整组件' if active else '未指定此思路')
    return reports

def deck_design_report(catalog,deck):
    names=deck.get('spells',[])+([deck['commander']] if deck.get('commander') else [])
    cards=[catalog.cards[n] for n in names if n in catalog.cards]
    packages=package_report(cards)
    return dict(version=VERSION,packages=packages,
        incomplete_packages=sum(bool(p['missing']) for p in packages.values()),
        limitation='检查最终选入的咒语及指挥官，不把整套 Cube 的支持当作已抓到；组件来自保守文本规则，需结合牌面与实战复核。')

def cube_design_report(catalog,rows,spec):
    cards=[catalog.cards[r['name']] for r in rows if r['name'] in catalog.cards]
    lands=[catalog.cards[r['name']] for r in rows if r['role']=='Land' and r['name'] in catalog.cards]
    guilds={}
    for g in GUILDS:
        accessible=[c for c in cards if c['kind']!='land' and (c['identity']=='C' or set(c['identity'])<=set(g))]
        guilds[g]=package_report(accessible,spec.pair_themes.get(g,[]))
    refs=[dict(name=c['name'],sources=reference_prior(c,spec)[1]) for c in cards if reference_prior(c,spec)[1]]
    slow=[c['name'] for c in lands if re.search(r'enters(?: the battlefield)? tapped',c['text'],re.I)]
    return dict(version=VERSION,study_version=studies()['version'],reference_group=spec.mode,
        reference_matches=refs,reference_count=len(refs),guild_packages=guilds,
        fixing=dict(land_slots=len(lands),tapped_text_slots=len(slow),examples=slow[:8],
            note='含进场横置字样的牌可能满足条件后不横置；这不是实际横置概率。'),
        limitation='案例经验与静态组件检查是设计假设；跨主题与终结标签可能误判，不证明颜色均衡或实战提升。')

def public_guide():
    d=studies()
    guide={k:d[k] for k in ['version','selection','methods','principles','cases']}
    extra=json.loads((ROOT/'data'/'learning_sources.json').read_text(encoding='utf-8'))
    guide.update(learning_version=extra['version'],websites=extra['websites'],sources=extra['sources'])
    return guide
