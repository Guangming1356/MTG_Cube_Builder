"""Draft/deck construction and opening-hand readiness, never a game-win proxy."""
import math
import random
import re
from collections import Counter
from functools import lru_cache
from .config import GUILDS
from .brackets import DeckRules, card_reasons, deck_report

@lru_cache(maxsize=8192)
def _mana_requirements(cost):
    symbols=re.findall(r"\{([^}]+)\}",cost)
    generic=sum(int(s) for s in symbols if s.isdigit()) + int("X" in symbols)
    required=[]
    for s in symbols:
        if s in "WUBRGC" and len(s)==1:required.append(set(s))
        elif "/" in s and "P" not in s:
            opts=set(s.replace("/", "")) & set("WUBRGC")
            if opts:required.append(opts)
    required.sort(key=len)
    return generic,tuple(frozenset(colors) for colors in required)


def affordable(cost, lands, *, max_sources=None):
    generic,required=_mana_requirements(cost)
    available=len(lands) if max_sources is None else min(len(lands),max_sources)
    if generic+len(required)>available:return False
    def assign(index,used):
        if index==len(required):return True
        return any(assign(index+1,used|(1<<j)) for j,colors in enumerate(lands)
                   if not used&(1<<j) and colors & required[index])
    return assign(0,0)

def opening_test(catalog,spells,land_names,identity,deck_size,rng,hands=40,*,commander=None):
    pips=Counter()
    for n in spells:
        for p in re.findall(r"\{([WUBRG])\}",catalog.cards[n]["mana_cost"]):pips[p]+=1
    colors=list(identity) if identity!="C" else ["C"]
    missing=deck_size-len(spells)-len(land_names)
    basics=[];allocated=Counter()
    for _ in range(max(0,missing)):
        color=max(colors,key=lambda c:(pips[c]+1)/(allocated[c]+1))
        allocated[color]+=1;basics.append({"kind":"land","fixing":[color],"name":"基本地 "+color})
    if commander:
        from .mana import commander_basic_sources
        repaired=commander_basic_sources(catalog,spells,land_names,allocated,commander)
        if repaired!=dict(allocated):
            allocated=repaired
            basics=[{'kind':'land','fixing':[color],'name':'基本地 '+color} for color,n in allocated.items() for _ in range(n)]
    deck=[catalog.cards[n] for n in spells+land_names]+basics
    ready=Counter();landcounts=[]
    for _ in range(hands):
        sample=rng.sample(deck,len(deck));hand=sample[:7];landcounts.append(sum(c["kind"]=="land" for c in hand))
        for turn in range(1,5):
            hand.append(sample[6+turn]);lands=[set(c["fixing"]) for c in hand if c["kind"]=="land"]
            # Test feasible choices among every land seen, while respecting one
            # land drop per turn. The first lands in a shuffled hand need not be
            # the lands a player would actually choose to play.
            spells_here=[c for c in hand if c["kind"]!="land"]
            if any(affordable(c["mana_cost"],lands,max_sources=turn) for c in spells_here):ready[turn]+=1
    return dict(ready_by_turn={str(t):round(ready[t]/hands,3) for t in range(1,5)} if hands else {},
                opening_2_to_4_lands=round(sum(2<=x<=4 for x in landcounts)/hands,3) if hands else None,
                basics=dict(allocated), assumptions="每回合抽牌，每回合最多一地；在已见地牌中选择可行来源，以各回合最佳可行下地为上界。不结算法术力加速、进场横置、替代费用、调度、牌面效果或对手行为；复合法术力仅作近似处理。")

def deal(catalog,rows,spec,rng):
    count=spec.players*spec.rounds
    if count*spec.pack_size>len(rows):raise ValueError("Cube 张数不足以按当前规则开包")
    if not spec.discard_after_pass:
        if spec.pick_count!=1:raise ValueError("完整传包模式目前只支持每次抓 1 张")
        cards=list(rows);rng.shuffle(cards)
        return [cards[i*spec.pack_size:(i+1)*spec.pack_size] for i in range(count)]
    commanders=[r for r in rows if r["role"]=="Commander"]
    lands=[r for r in rows if r["role"]=="Land"]
    mains=[r for r in rows if r["role"]=="Main"]
    rng.shuffle(commanders);rng.shuffle(lands);rng.shuffle(mains)
    cslot=3 if spec.mode=="commander" else 0
    if len(commanders)<count*cslot or len(lands)<count:raise ValueError("当前牌表的指挥官/地槽位不足以生成均匀包")
    big=[r for r in mains if catalog.cards[r["name"]]["mv"]>=6]
    if len(big)<count:raise ValueError("6费以上咒语不足，不能保证每包一张")
    big=big[:count];big_names={r["name"] for r in big};mains=[r for r in mains if r["name"] not in big_names]
    rest=spec.pack_size-cslot-2
    if rest<0 or len(mains)<count*rest:raise ValueError("主牌槽位不足")
    packs=[]
    for i in range(count):
        pack=commanders[i*cslot:(i+1)*cslot]+[lands[i],big[i]]+mains[i*rest:(i+1)*rest]
        rng.shuffle(pack);packs.append(pack)
    return packs

def draft_pod(catalog,rows,spec,rng,preferred_guilds=None,readiness_hands=40,_packs=None):
    """A single table: decks, pools and packs are never mixed across tables."""
    packs=deal(catalog,rows,spec,rng) if _packs is None else _packs
    opened=[[r["name"] for r in p] for p in packs]
    decks=[]
    rules=DeckRules(catalog,spec)
    pools=[[] for _ in range(spec.players)]
    preferred=list(preferred_guilds) if preferred_guilds is not None else [rng.choice(GUILDS) for _ in pools]
    if len(preferred)!=spec.players or any(g not in GUILDS for g in preferred):raise ValueError('轮抓偏好色组必须与玩家数相同且均为有效双色')
    bucket_counts=[Counter() for _ in pools];land_counts=[0 for _ in pools];have_commanders=[False for _ in pools]
    themes_by_seat=[set(spec.pair_themes.get(g,[])) for g in preferred]
    for rd in range(spec.rounds):
        current=packs[rd*spec.players:(rd+1)*spec.players]
        steps=spec.players if spec.discard_after_pass else spec.pack_size
        for step in range(steps):
            for seat in range(spec.players):
                index=(seat+step*(1 if rd%2==0 else -1))%spec.players;pack=current[index]
                for _ in range(spec.pick_count):
                    if not pack:break
                    g=preferred[seat];pool=pools[seat]
                    have_cmd=have_commanders[seat]
                    def grade(r):
                        c=catalog.cards[r["name"]];fits=c["identity"]=="C" or set(c["identity"])<=set(g)
                        if c["kind"]=="land":return 3.0+.4*len(set(c["fixing"]) & set(g))-.4*land_counts[seat]
                        themes=themes_by_seat[seat]
                        signal=.18*len(themes & set(c["enablers"]+c["payoffs"]))
                        cmd=1.8 if spec.mode=="commander" and not have_cmd and c["commander"] and c["identity"]==g else 0
                        return c["quality"]+signal+cmd+(1.4 if fits else -2.5)-.1*bucket_counts[seat][c['bucket']]
                    card=max(pack,key=grade);pack.remove(card);pool.append(card)
                    selected=catalog.cards[card['name']];bucket_counts[seat][selected['bucket']]+=1
                    land_counts[seat]+=card['role']=='Land'
                    have_commanders[seat]|=bool(selected['commander'] and selected['identity']==g)
    for seat,pool in enumerate(pools):
        g=preferred[seat]
        commands=[catalog.cards[r["name"]] for r in pool if catalog.cards[r["name"]]["commander"] and catalog.cards[r["name"]]['identity']!='C'] if spec.mode=="commander" else [None]
        if spec.mode=='commander':commands=[c for c in commands if not card_reasons(c,spec)]
        power=rules.power
        if power:commands=[c for c in commands if c['quality']<=power['commander_ceiling']]
        target=60 if spec.mode=="commander" else 40
        best=None
        for commander in commands:
            identity=commander["identity"] if commander else g
            spells=[r["name"] for r in pool if catalog.cards[r["name"]]["kind"]!="land"
                and (catalog.cards[r["name"]]["identity"]=="C" or set(catalog.cards[r["name"]]["identity"])<=set(identity))
                and (not commander or r["name"]!=commander["name"])]
            spells.sort(key=lambda n:(-catalog.cards[n]["quality"],catalog.cards[n]["mv"],n))
            spells=rules.select([commander['name']] if commander else [],spells)
            # Free basic lands are unlimited. Land count is a deck-building decision,
            # not a requirement that 37 drafted spells must be available.
            sample=spells[:38 if target==60 else 23]
            avg=sum(catalog.cards[n]["mv"] for n in sample)/max(1,len(sample))
            cheap_ramp=sum(catalog.cards[n]["ramp"] and catalog.cards[n]["mv"]<=3 for n in sample)
            land_target=max(22,min(28,round(23+(avg-2.5)*2-min(cheap_ramp,6)*.25))) if target==60 else 17
            needed=min(len(spells),target-land_target-int(bool(commander)))
            score=sum(catalog.cards[n]["quality"] for n in spells[:needed])
            if not best or score>best[0]:best=(score,commander,identity,spells[:needed])
        if best is None:
            decks.append(dict(seat=seat,guild=g,buildable=False,drafted=[r["name"] for r in pool]));continue
        _,commander,identity,spells=best
        land_target=target-len(spells)-int(bool(commander))
        lands=[r["name"] for r in pool if catalog.cards[r["name"]]["kind"]=="land"
               and (catalog.cards[r["name"]]["identity"]=="C" or set(catalog.cards[r["name"]]["identity"])<=set(identity))
               and set(catalog.cards[r["name"]]["fixing"]) & set(identity)]
        lands=rules.select(([commander['name']] if commander else [])+spells,lands)[:land_target]
        # Commander is in the command zone, excluded from random opening hands.
        ready=opening_test(catalog,spells,lands,identity,target-int(bool(commander)),rng,hands=readiness_hands,commander=commander and commander['name'])
        decks.append(dict(seat=seat,guild=g,identity=identity,buildable=True,ready=ready,
            commander=commander and commander["name"],spells=spells,lands=lands,
            basics=ready["basics"],land_count=land_target,spell_count=len(spells),
            construction_warning="可用非地牌偏少，补地后合法但可能很弱" if land_target/target>.48 else None,
            drafted=[r["name"] for r in pool]))
    from .design import deck_design_report
    for deck in decks:
        if deck['buildable']:
            deck['design']=deck_design_report(catalog,deck)
            deck['bracket']=deck_report(catalog,deck,spec)
    return dict(decks=decks,packs=opened)

def stress_test(catalog,rows,spec,trials=100,progress=lambda x:None):
    if not 5<=trials<=500:raise ValueError("压力测试次数需在 5–500 之间")
    from .engine import audit
    report=audit(catalog,rows,spec)
    if report['hard_errors']:raise ValueError('牌表存在合法性、槽位或数量错误；请先审计并修复，再测试轮抓')
    rng=random.Random(spec.seed);examples=[];summary=[];sizes=Counter();guilds=Counter()
    first_packs=None
    for trial in range(trials):
        pod=draft_pod(catalog,rows,spec,rng)
        if first_packs is None:first_packs=pod["packs"]
        for deck in pod["decks"]:
            sizes[len(deck["drafted"])]+=1;guilds[deck["guild"]]+=1
            summary.append(deck)
            if deck["buildable"] and len(examples)<spec.players:
                examples.append({k:v for k,v in deck.items() if k not in {"ready","buildable"}})
        if trial%20==0:progress(f"完成 {trial+1}/{trials} 桌轮抓")
    valid=[x for x in summary if x["buildable"]]
    group_summary={}
    for g in GUILDS:
        all_g=[x for x in summary if x["guild"]==g];ok=[x for x in all_g if x["buildable"]]
        group_summary[g]=dict(decks=len(all_g),buildable_rate=round(len(ok)/max(1,len(all_g)),3),
            ready_by_turn={str(t):round(sum(x["ready"]["ready_by_turn"][str(t)] for x in ok)/max(1,len(ok)),3) for t in range(1,5)})
    return dict(trials=trials,players=spec.players,drafted_pool_sizes=dict(sizes),
                bracket_check=dict(target=spec.bracket,decks_checked=len(valid) if spec.bracket else 0,
                    violations=sum(bool(d['bracket'] and d['bracket']['violations']) for d in valid),
                    max_deck_game_changers=max((len(d['bracket']['game_changers']) for d in valid if d['bracket']),default=0),
                    certified=False),
                cards_opened=spec.players*spec.rounds*spec.pack_size,
                cards_discarded_per_pack=spec.pack_size-spec.players*spec.pick_count if spec.discard_after_pass else 0,
                buildable_rate=round(len(valid)/max(1,len(summary)),3),guilds=group_summary,
                examples=examples,packs=first_packs,seed=spec.seed,
                component_check=dict(decks=len(valid),decks_with_incomplete_packages=sum(bool(d['design']['incomplete_packages']) for d in valid),
                    note='实际入组牌的组件提示，不等于死牌率。'),
                limitation="只测试轮抓组牌和起手法术力准备度；没有结算牌效、战斗、胜负或政治互动，不能解释为实战胜率。")
