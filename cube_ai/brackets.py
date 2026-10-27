"""Versioned Commander intent guidelines plus explicit, separate Cube heuristics.

This module never assigns a certified official bracket from card scores or wins.
"""
import re
from datetime import date

VERSION = "commander-brackets-2026-02-09/cube-policy-1"
REVIEWED = "2026-10-11"
SOURCES = [
    "https://magic.wizards.com/en/formats/commander",
    "https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-october-21-2025",
    "https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-february-9-2026",
]
# October list, plus Farewell and Biorhythm added February 9. Front names
# deliberately resolve double-faced cards independently of snapshot flags.
GAME_CHANGERS = frozenset("""Drannith Magistrate|Humility|Serra's Sanctum|Smothering Tithe|Enlightened Tutor|Teferi's Protection|Consecrated Sphinx|Cyclonic Rift|Force of Will|Fierce Guardianship|Gifts Ungiven|Intuition|Mystical Tutor|Narset, Parter of Veils|Rhystic Study|Thassa's Oracle|Ad Nauseam|Bolas's Citadel|Braids, Cabal Minion|Demonic Tutor|Imperial Seal|Necropotence|Opposition Agent|Orcish Bowmasters|Tergrid, God of Fright|Vampiric Tutor|Gamble|Jeska's Will|Underworld Breach|Crop Rotation|Gaea's Cradle|Natural Order|Seedborn Muse|Survival of the Fittest|Worldly Tutor|Aura Shards|Coalition Victory|Grand Arbiter Augustin IV|Notion Thief|Ancient Tomb|Chrome Mox|Field of the Dead|Glacial Chasm|Grim Monolith|Lion's Eye Diamond|Mana Vault|Mishra's Workshop|Mox Diamond|Panoptic Mirror|The One Ring|The Tabernacle at Pendrell Vale|Farewell|Biorhythm""".split("|"))

PROFILES = {
    1: dict(name="Exhibition · 主题娱乐", description="围绕主题与有趣互动，降低强牌密度。主题意图仍需玩家确认。", own_turns=9, deck_gc=0, mean=[2.80,3.10], ceiling=3.80, commander_ceiling=3.45, gold_floor=2.65, top_rate=0, gc_rate=0),
    2: dict(name="Core · 休闲基础", description="清晰的铺场、资源积累与可回应的终结。", own_turns=8, deck_gc=0, mean=[3.10,3.38], ceiling=4.20, commander_ceiling=3.90, gold_floor=2.85, top_rate=.025, gc_rate=0),
    3: dict(name="Upgraded · 中上强度", description="更好的单卡、协同和互动，保留后期爆发终结。推荐你的娱乐轮抓使用。", own_turns=6, deck_gc=3, mean=[3.35,3.60], ceiling=4.65, commander_ceiling=4.65, gold_floor=3.05, top_rate=.085, gc_rate=.03),
    4: dict(name="Optimized · 高强度", description="优先效率、稳定性和高质量威胁与应对。", own_turns=4, deck_gc=None, mean=[3.42,3.85], ceiling=4.65, commander_ceiling=4.65, gold_floor=3.05, top_rate=.18, gc_rate=.06),
    5: dict(name="cEDH · 竞技构筑目标（实验）", description="以竞技对局为目标；轮抓环境与当前评估器不能认证 cEDH，须结合环境、获胜线和实战另行判断。", own_turns=None, deck_gc=None, mean=[3.42,3.90], ceiling=4.65, commander_ceiling=4.65, gold_floor=3.05, top_rate=.24, gc_rate=.09),
}
LIMITATION = "Bracket 是整副牌的意图与体验分档，不是单卡分数。这里检查可识别的构筑限制；主题、获胜速度、额外回合链和竞技环境适配仍需实战判断。60 张轮抓使用本项目的适配规则。"

def validate_spec(spec):
    if spec.bracket is not None and (type(spec.bracket) is not int or spec.bracket not in PROFILES):
        raise ValueError("bracket 必须为 1–5 或 null（自定义/旧方案）")
    if spec.bracket is not None and spec.mode != "commander":
        raise ValueError("Commander Bracket 只用于 Commander Cube；传统 Cube 请选自定义")
    if spec.power_tuning not in {"gentle","balanced","strong"}:
        raise ValueError("power_tuning 必须为 gentle/balanced/strong")
    if spec.commander_tuning not in {"gentle","matched","strong"}:
        raise ValueError("commander_tuning 必须为 gentle/matched/strong")
    if spec.allow_extra_turns is not None and type(spec.allow_extra_turns) is not bool:
        raise ValueError("allow_extra_turns 必须为 true/false 或 null（沿用旧方案）")
    if spec.cube_gc_limit is not None and (type(spec.cube_gc_limit) is not int or not 0 <= spec.cube_gc_limit <= spec.size):
        raise ValueError("cube_gc_limit 必须是 0–Cube 张数之间的整数或 null")
    if spec.bracket in (1,2) and spec.cube_gc_limit:
        raise ValueError("Bracket 1/2 的此预设不含 Game Changers")
    if spec.bracket in (1,2,3):
        if spec.allow_mass_land_destruction or spec.allow_infinite_combos or spec.allow_extra_turns:
            raise ValueError("Bracket 1–3 的保守轮抓预设排除炸地、已知无限组合和额外回合；需要这些内容请使用 4/5 档或自定义。额外回合全排除是项目偏好。")
    if spec.bracket is None and spec.cube_gc_limit is not None:
        raise ValueError("Cube Game Changer 数量上限需先选择 Bracket")

def profile(spec):
    if spec.bracket is None:return None
    p=dict(PROFILES[spec.bracket]);p['mean']=list(p['mean'])
    shift={'gentle':-.05,'balanced':0,'strong':.05}[spec.power_tuning]
    p['mean']=[round(x+shift,2) for x in p['mean']]
    if spec.power_tuning=='gentle' and spec.bracket>=3:
        p['mean'][1]=min(p['mean'][1],3.45 if spec.bracket==3 else 3.48)
    if spec.power_tuning=='strong' and spec.bracket>=4:
        p['mean'][0]=max(p['mean'][0],3.49)
    p['target']=sum(p['mean'])/2
    p['gc_limit']=spec.cube_gc_limit if spec.cube_gc_limit is not None else round(spec.size*p['gc_rate'])
    if spec.exclude_game_changers:p['gc_limit']=0
    p['top_limit']=round((spec.size-spec.commanders-spec.lands)*p['top_rate']*{'gentle':.65,'balanced':1,'strong':1.35}[spec.power_tuning])
    p['commander_target']=p['target']+{'gentle':-.25,'matched':0,'strong':.20}[spec.commander_tuning]
    return p

def is_gc(card):
    return card['name'].split(' // ')[0] in GAME_CHANGERS

def extra_turn(card):
    # Both singular and multiple extra turns; excludes skipping turns.
    return bool(re.search(r'\b(?:take|takes) (?:an?|one|two|three|\d+|X) extra turns?\b',card.get('text',''),re.I))

def card_reasons(card,spec,*,power=None):
    from .mana import requires_colorless_mana
    from .release_dates import paper_witness
    p=power or profile(spec)
    reasons=[]
    if not spec.allow_colorless_costs and requires_colorless_mana(card):reasons.append('项目偏好：排除需要支付无色法术力 {C} 的牌')
    if card.get('released','')>date.today().isoformat() and not paper_witness(card):reasons.append('尚未核实已发行的纸质印张')
    if not p:
        if spec.allow_extra_turns is False and extra_turn(card):reasons.append('项目偏好：排除额外回合')
        return reasons
    if is_gc(card) and (p['deck_gc']==0 or p['gc_limit']==0):reasons.append('该 Bracket/数量预算排除 Game Changers')
    if card['kind']!='land' and card['quality']>p['ceiling']+1e-6:reasons.append('超过该档项目单卡评价上限')
    if extra_turn(card) and not spec.allow_extra_turns:reasons.append('项目偏好：排除额外回合')
    return reasons

def score_adjustment(card,spec,role='Main'):
    p=profile(spec)
    if not p or card['kind']=='land':return 0
    target=p['commander_target'] if role=='Commander' else p['target']
    # Turn the existing monotonic quality objective into a target-band objective.
    coefficient=2.0 if spec.bracket<=2 or role=='Commander' else .35
    efficiency=(.10 if spec.bracket==4 else .18 if spec.bracket==5 else 0)*(card['mv']<=2)
    tuning={'gentle':-.45,'balanced':0,'strong':.45}[spec.power_tuning]*card['quality'] if role!='Commander' else 0
    return -coefficient*abs(card['quality']-target)+efficiency+tuning

def cube_report(catalog,rows,spec):
    p=profile(spec)
    if not p:return None
    known=[(r,catalog.cards[r['name']]) for r in rows if r['name'] in catalog.cards]
    main=[c for r,c in known if r['role']=='Main']
    commands=[c for r,c in known if r['role']=='Commander']
    gc=[c['name'] for _,c in known if is_gc(c)]
    top=[c['name'] for c in main if c['quality']>=4.0]
    mean=sum(c['quality'] for c in main)/max(1,len(main))
    violations=[]
    if not p['mean'][0]-1e-6<=mean<=p['mean'][1]+1e-6:violations.append('主牌平均启发式评价超出项目目标区间')
    if len(gc)>p['gc_limit']:violations.append('Cube Game Changer 数量超过项目预算')
    if len(top)>p['top_limit']:violations.append('主牌高评价牌数量超过项目预算')
    if any(c['quality']>p['commander_ceiling']+1e-6 for c in commands):violations.append('指挥官超过项目单卡评价上限')
    return dict(target=spec.bracket,name=p['name'],power_tuning=spec.power_tuning,commander_tuning=spec.commander_tuning,
        main_mean=round(mean,4),project_mean_band=p['mean'],project_card_ceiling=p['ceiling'],
        project_commander_ceiling=p['commander_ceiling'],commander_mean=round(sum(c['quality'] for c in commands)/max(1,len(commands)),4),
        game_changers=gc,cube_gc_limit=p['gc_limit'],official_deck_gc_limit=p['deck_gc'],
        high_quality_main=len(top),project_high_quality_limit=p['top_limit'],own_turns_expectation=p['own_turns'],
        violations=violations,certified=False,version=VERSION,reviewed=REVIEWED,sources=SOURCES,limitation=LIMITATION)

def may_add(catalog,names,name,spec):
    p=profile(spec)
    if not p:return not card_reasons(catalog.cards[name],spec)
    cards=[catalog.cards[n] for n in names+[name]]
    return not (p['deck_gc'] is not None and sum(is_gc(c) for c in cards)>p['deck_gc']) and not card_reasons(catalog.cards[name],spec)


class DeckRules:
    """Reuse immutable card checks within one table; count GC slots incrementally.

    The public may_add function remains the reference for one-off decisions.
    This object belongs to one draft/spec only, so edits never share stale rules.
    """
    def __init__(self,catalog,spec):
        self.catalog=catalog;self.spec=spec;self.power=profile(spec);self.checks={}

    def select(self,initial,candidates):
        if not self.power:return [n for n in candidates if not card_reasons(self.catalog.cards[n],self.spec)]
        cap=self.power['deck_gc']
        count=sum(is_gc(self.catalog.cards[n]) for n in initial) if cap is not None else 0
        selected=[]
        for name in candidates:
            if name not in self.checks:
                card=self.catalog.cards[name]
                self.checks[name]=(is_gc(card),not card_reasons(card,self.spec,power=self.power))
            gc,allowed=self.checks[name]
            if not allowed or (cap is not None and count+gc>cap):continue
            selected.append(name);count+=gc
        return selected

def deck_report(catalog,deck,spec):
    p=profile(spec)
    if not p:return None
    names=([deck['commander']] if deck.get('commander') else [])+deck.get('spells',[])+deck.get('lands',[])
    gc=[n for n in names if is_gc(catalog.cards[n])]
    violations=[n+': '+'; '.join(card_reasons(catalog.cards[n],spec)) for n in names if card_reasons(catalog.cards[n],spec)]
    if deck.get('commander') and catalog.cards[deck['commander']]['quality']>p['commander_ceiling']:
        violations.append('实际指挥官超过项目该档评价上限')
    if p['deck_gc'] is not None and len(gc)>p['deck_gc']:violations.append('整副牌含指挥官和地牌的 Game Changers 超过官方数量限制')
    from .features import COMBOS
    if not spec.allow_infinite_combos:
        violations.extend('已知组合: '+' + '.join(combo) for combo in COMBOS if set(combo)<=set(names))
    if not spec.allow_fast_mana and any(catalog.cards[n]['fast_mana'] for n in names):violations.append('包含项目排除的快法术力')
    if not spec.allow_mass_land_destruction and any(catalog.cards[n]['mld'] for n in names):violations.append('包含项目排除的炸地/封锁')
    return dict(target=spec.bracket,game_changers=gc,official_deck_gc_limit=p['deck_gc'],violations=violations,
                construction_checks_passed=not violations,certified=False,limitation=LIMITATION)

def public_profiles():
    return dict(version=VERSION,reviewed=REVIEWED,sources=SOURCES,profiles=[dict(bracket=k,**v) for k,v in PROFILES.items()],
        limitation=LIMITATION,project_policy='费用曲线、角色密度和色组平衡持续约束；平均评价区间、强牌密度、指挥官目标和 Cube GC 预算是项目实现参数。官方从 2025-10 起不限制导师数量。')
