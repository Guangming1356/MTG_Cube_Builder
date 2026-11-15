"""Draft/deck construction and opening-hand readiness, never a game-win proxy."""
import math
import random
import re
from collections import Counter
from .config import GUILDS
from .brackets import DeckRules, card_reasons, deck_report
from .commander_rules import automatic as automatic_commander,messages as commander_messages
from .mana import affordable,_affordable_masks,land_source_mask,readiness_assumptions,MODEL_VERSION
from .casting_costs import curve_value,mana_cost as casting_mana_cost,VERSION as CASTING_VERSION

READINESS_STREAM='readiness-fork-1'
OPENING_SAMPLER='ordered-prefix-11-v1'


def _readiness_rng(rng,seat):
    """Derive a per-seat generator without advancing the caller's draft RNG."""
    child=random.Random(0);child.setstate(rng.getstate())
    child.seed(f'{READINESS_STREAM}:{seat}:{child.getrandbits(128)}')
    return child

def opening_test(catalog,spells,land_names,identity,deck_size,rng,hands=40,*,commander=None,starting_life=40):
    if type(hands) is not int or hands<0:raise ValueError('起手抽样次数必须为非负整数')
    pips=Counter()
    for n in spells:
        for p in re.findall(r"\{([WUBRG])\}",casting_mana_cost(catalog.cards[n])):pips[p]+=1
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
    # Payment-only copies keep the catalog's printed cost and mana value intact.
    deck=[dict(c,mana_cost=casting_mana_cost(c)) if c.get('casting_requirements') else c for c in deck]
    if hands and len(deck)<11:raise ValueError('起手与前四回合抽牌测试至少需要 11 张牌')
    land_masks={card['name']:land_source_mask(card) for card in deck if card['kind']=='land'}
    ready=Counter();landcounts=[];life_budget=max(0,starting_life-1)
    for _ in range(hands):
        # An ordered sample of eleven has the same distribution as the first
        # eleven cards of a full shuffle; the unseen tail is never inspected.
        sample=rng.sample(deck,11);hand=sample[:7];landcounts.append(sum(c["kind"]=="land" for c in hand))
        sources=[land_masks[c['name']] for c in hand if c['kind']=='land' and land_masks[c['name']]]
        costs=[c['mana_cost'] for c in hand if c['kind']!='land']
        for turn in range(1,5):
            drawn=sample[6+turn]
            if drawn['kind']=='land':
                if land_masks[drawn['name']]:sources.append(land_masks[drawn['name']])
            else:costs.append(drawn['mana_cost'])
            # Test feasible choices among every land seen, while respecting one
            # land drop per turn. The first lands in a shuffled hand need not be
            # the lands a player would actually choose to play.
            if any(_affordable_masks(cost,sources,max_sources=turn,life_budget=life_budget) for cost in costs):
                # The cards and usable sources seen only grow, and the land-drop
                # limit increases, so affordability persists in this model.
                for later in range(turn,5):ready[later]+=1
                break
    return dict(ready_by_turn={str(t):round(ready[t]/hands,3) for t in range(1,5)} if hands else {},
                opening_2_to_4_lands=round(sum(2<=x<=4 for x in landcounts)/hands,3) if hands else None,
                basics=dict(allocated),model_version=MODEL_VERSION,starting_life=starting_life,assumptions=readiness_assumptions(starting_life),
                sampling_version=OPENING_SAMPLER,hands=hands,cards_per_hand=11,casting_version=CASTING_VERSION)

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
                        cmd=1.8 if spec.mode=="commander" and not have_cmd and automatic_commander(c,spec) and c["identity"]==g else 0
                        return c["quality"]+signal+cmd+(1.4 if fits else -2.5)-.1*bucket_counts[seat][c['bucket']]
                    card=max(pack,key=grade);pack.remove(card);pool.append(card)
                    selected=catalog.cards[card['name']];bucket_counts[seat][selected['bucket']]+=1
                    land_counts[seat]+=card['role']=='Land'
                    have_commanders[seat]|=bool(automatic_commander(selected,spec) and selected['identity']==g)
    decks=[build_deck(catalog,[r['name'] for r in pool],spec,rng,preferred[seat],seat,
                      readiness_hands=readiness_hands,_rules=rules) for seat,pool in enumerate(pools)]
    return dict(decks=decks,packs=opened,deck_policy=spec.deck_policy)

def build_deck(catalog,names,spec,rng,guild,seat=0,*,readiness_hands=40,_rules=None):
    """Build from the actual picked pool; basics are free and commander counts in 60."""
    if guild not in GUILDS:raise ValueError('无效的轮抓偏好色组')
    unknown=[name for name in names if name not in catalog.cards]
    if unknown:raise ValueError('抓牌池含未知牌名：'+', '.join(unknown))
    pool=[dict(name=name) for name in names];g=guild;rules=(_rules or DeckRules(catalog,spec)).ensure_scope(catalog,spec)
    legal_commands=[catalog.cards[r['name']] for r in pool if catalog.cards[r['name']]['commander'] and catalog.cards[r['name']]['identity']!='C'] if spec.mode=='commander' else []
    commands=[c for c in legal_commands if automatic_commander(c,spec)] if spec.mode=='commander' else [None]
    if spec.mode=='commander':commands=[c for c in commands if rules.allowed(c['name'])]
    power=rules.power
    if power:commands=[c for c in commands if c['quality']<=power['commander_ceiling']]
    target=60 if spec.mode=="commander" else 40
    best=None
    for commander in commands:
        identity=commander["identity"] if commander else g
        spells=[r["name"] for r in pool if catalog.cards[r["name"]]["kind"]!="land"
            and (catalog.cards[r["name"]]["identity"]=="C" or set(catalog.cards[r["name"]]["identity"])<=set(identity))
            and (not commander or r["name"]!=commander["name"])]
        spells.sort(key=lambda n:(-catalog.cards[n]["quality"],curve_value(catalog.cards[n]),n))
        spells=rules.select([commander['name']] if commander else [],spells)
        # Free basic lands are unlimited. Land count is a deck-building decision,
        # not a requirement that 37 drafted spells must be available.
        sample=spells[:38 if target==60 else 23]
        avg=sum(curve_value(catalog.cards[n]) for n in sample)/max(1,len(sample))
        cheap_ramp=sum(catalog.cards[n]["ramp"] and curve_value(catalog.cards[n])<=3 for n in sample)
        land_target=max(22,min(28,round(23+(avg-2.5)*2-min(cheap_ramp,6)*.25))) if target==60 else 17
        needed=min(len(spells),target-land_target-int(bool(commander)))
        commander_quality=commander['quality'] if commander else 0
        score=(round(sum(catalog.cards[n]["quality"] for n in spells[:needed])+commander_quality,6),commander_quality)
        if not best or score>best[0]:best=(score,commander,identity,spells[:needed])
    if best is None:
        return dict(seat=seat,guild=g,buildable=False,deck_policy=spec.deck_policy,deck_policy_changes=[],
            construction_warning='抓到的指挥官需要专门施放配合，当前未允许自动选择' if legal_commands and not any(automatic_commander(c,spec) for c in legal_commands) else '抓牌池没有可按当前设置使用的指挥官',
            drafted=[r["name"] for r in pool])
    _,commander,identity,spells=best
    land_target=target-len(spells)-int(bool(commander))
    lands=[r["name"] for r in pool if catalog.cards[r["name"]]["kind"]=="land"
           and (catalog.cards[r["name"]]["identity"]=="C" or set(catalog.cards[r["name"]]["identity"])<=set(identity))
           and set(catalog.cards[r["name"]]["fixing"]) & set(identity)]
    lands=rules.select(([commander['name']] if commander else [])+spells,lands)[:land_target]
    deck=dict(seat=seat,guild=g,identity=identity,buildable=True,
        commander=commander and commander["name"],spells=spells,lands=lands,
        land_count=land_target,spell_count=len(spells),deck_policy=spec.deck_policy,deck_policy_changes=[],
        construction_warning="可用非地牌偏少，补地后合法但可能很弱" if land_target/target>.48 else None,
        drafted=[r["name"] for r in pool])
    if spec.deck_policy=='balanced':
        from .deck_building import revise
        deck=revise(catalog,deck,spec,'balanced',evaluate=False,_rules=rules)
        deck.pop('research_changes',None)
    # Evaluate only the final spells. Commander stays outside opening hands.
    # Readiness is an observation, not part of dealing the next table. Its
    # sample count and the selected policy must never consume the draft RNG.
    ready_rng=_readiness_rng(rng,seat) if readiness_hands else rng
    ready=opening_test(catalog,deck['spells'],lands,identity,target-int(bool(commander)),ready_rng,hands=readiness_hands,commander=deck['commander'],starting_life=40 if spec.mode=='commander' else 20)
    ready['stream_version']=READINESS_STREAM
    deck.update(ready=ready,basics=ready['basics'])
    if commander and commander.get('commander_setup'):deck['commander_setup_notes']=commander_messages(commander)
    from .design import deck_design_report
    deck['design']=deck_design_report(catalog,deck)
    deck['bracket']=deck_report(catalog,deck,spec,_rules=rules)
    return deck

def stress_test(catalog,rows,spec,trials=100,progress=lambda x:None):
    if not 5<=trials<=500:raise ValueError("压力测试次数需在 5–500 之间")
    from .engine import audit
    report=audit(catalog,rows,spec)
    if report['hard_errors']:raise ValueError('牌表存在合法性、槽位或数量错误；请先审计并修复，再测试轮抓')
    rng=random.Random(spec.seed);examples=[];sizes=Counter();first_packs=None
    groups={g:dict(decks=0,buildable=0,ready=Counter()) for g in GUILDS}
    total_decks=valid_count=bracket_violations=max_deck_gc=incomplete_packages=0
    for trial in range(trials):
        pod=draft_pod(catalog,rows,spec,rng)
        if first_packs is None:first_packs=pod["packs"]
        for deck in pod["decks"]:
            sizes[len(deck['drafted'])]+=1;total_decks+=1
            group=groups[deck['guild']];group['decks']+=1
            if not deck['buildable']:continue
            valid_count+=1;group['buildable']+=1
            for turn in range(1,5):group['ready'][str(turn)]+=deck['ready']['ready_by_turn'][str(turn)]
            bracket=deck['bracket'];bracket_violations+=bool(bracket and bracket['violations'])
            if bracket:max_deck_gc=max(max_deck_gc,len(bracket['game_changers']))
            incomplete_packages+=bool(deck['design']['incomplete_packages'])
            if len(examples)<spec.players:examples.append({k:v for k,v in deck.items() if k not in {'ready','buildable'}})
        if trial%20==0:progress(f"完成 {trial+1}/{trials} 桌轮抓")
    group_summary={}
    for g in GUILDS:
        group=groups[g]
        group_summary[g]=dict(decks=group['decks'],buildable_rate=round(group['buildable']/max(1,group['decks']),3),
            ready_by_turn={str(t):round(group['ready'][str(t)]/max(1,group['buildable']),3) for t in range(1,5)})
    return dict(trials=trials,players=spec.players,deck_policy=spec.deck_policy,drafted_pool_sizes=dict(sizes),
                bracket_check=dict(target=spec.bracket,decks_checked=valid_count if spec.bracket else 0,
                    violations=bracket_violations,max_deck_game_changers=max_deck_gc,
                    certified=False),
                cards_opened=spec.players*spec.rounds*spec.pack_size,
                cards_discarded_per_pack=spec.pack_size-spec.players*spec.pick_count if spec.discard_after_pass else 0,
                buildable_rate=round(valid_count/max(1,total_decks),3),guilds=group_summary,
                examples=examples,packs=first_packs,seed=spec.seed,
                mana_model=dict(version=MODEL_VERSION,starting_life=40 if spec.mode=='commander' else 20,assumptions=readiness_assumptions(40 if spec.mode=='commander' else 20),
                    stream_version=READINESS_STREAM,sampling_version=OPENING_SAMPLER,hands_per_deck=40,cards_per_hand=11,casting_version=CASTING_VERSION),
                component_check=dict(decks=valid_count,decks_with_incomplete_packages=incomplete_packages,
                    note='实际入组牌的组件提示，不等于死牌率。'),
                limitation="只测试轮抓组牌和起手法术力准备度；没有结算牌效、战斗、胜负或政治互动，不能解释为实战胜率。")
