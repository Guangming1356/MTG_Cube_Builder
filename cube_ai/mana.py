"""Mana preferences: generic costs are distinct from required colorless mana."""
import re
from collections import Counter
from functools import lru_cache
from .casting_costs import mana_cost as casting_mana_cost

MODEL_VERSION='printed-cost-2'
MANA_BITS={color:1<<i for i,color in enumerate('WUBRGCS')}
MANA_TYPES=frozenset('WUBRGC')


@lru_cache(maxsize=1024)
def _source_mask(colors):
    # Snow is provenance, not a seventh mana type. Nonproducing snow lands
    # must not acquire a mana ability merely through their supertype.
    mask=sum(MANA_BITS[c] for c in colors if c in MANA_TYPES)
    return mask|(MANA_BITS['S'] if mask and 'S' in colors else 0)


def land_source_mask(card):
    mask=_source_mask(frozenset(card.get('fixing',())))
    return mask|(MANA_BITS['S'] if mask and 'Snow' in card.get('type','').split() else 0)


@lru_cache(maxsize=4096)
def _matching_constraints(pips):
    """Hall's condition grouped by interchangeable requirement masks.

    For each union of mana options, enough distinct sources must intersect
    it. All requirements contained in that union give its strongest demand.
    Checking these neighborhoods avoids enumerating land permutations.
    """
    counts=Counter(pips);unions={0}
    for mask in counts:unions|={prior|mask for prior in unions}
    return tuple(sorted(((union,sum(n for mask,n in counts.items() if mask&union==mask))
                         for union in unions if union),key=lambda item:(item[0].bit_count(),-item[1],item[0])))


@lru_cache(maxsize=8192)
def _payment_plans(cost):
    if not isinstance(cost,str) or not cost:return ()
    tokens=re.findall(r'\{([^}]+)\}',cost)
    if not tokens or ''.join('{'+token+'}' for token in tokens)!=cost:return ()
    states={(0,0,())}
    for token in tokens:
        if token.isdigit():choices=[(int(token),0,0)]
        elif token=='X':choices=[(1,0,0)]
        elif token in MANA_BITS:choices=[(0,0,MANA_BITS[token])]
        elif re.fullmatch(r'2/[WUBRG]',token):choices=[(2,0,0),(0,0,MANA_BITS[token[-1]])]
        elif re.fullmatch(r'[WUBRGC]/[WUBRGC]',token):choices=[(0,0,MANA_BITS[token[0]]|MANA_BITS[token[-1]])]
        elif re.fullmatch(r'[WUBRG](?:/[WUBRG])?/P',token):
            choices=[(0,2,0),(0,0,sum(MANA_BITS[c] for c in set(token.split('/')[:-1])))]
        else:return ()
        states={(generic+extra,life+payment,tuple(sorted(pips+((mask,) if mask else ()))))
                for generic,life,pips in states for extra,payment,mask in choices}
    return tuple(sorted((generic+len(pips),life,_matching_constraints(pips)) for generic,life,pips in states))


def _affordable_masks(cost,sources,*,max_sources=None,life_budget=0):
    """Internal hot path; sources are nonzero, one-mana land option masks."""
    available=len(sources) if max_sources is None else min(len(sources),max_sources)
    for total,life,constraints in _payment_plans(cost):
        if total>available or life>life_budget:continue
        for mask,needed in constraints:
            for source in sources:
                if source&mask:
                    needed-=1
                    if needed==0:break
            else:break
        else:return True
    return False


def affordable(cost,lands,*,max_sources=None,life_budget=0):
    """Pay a printed cost with distinct one-mana sources and explicit life.

    Each source lists possible mana types; add 'S' for snow provenance.
    Empty sets produce no mana. Each X is 1. Alternative/additional costs,
    taxes, restricted mana and casting permission are outside this model.
    """
    sources=tuple(mask for colors in lands if (mask:=_source_mask(frozenset(colors))))
    return _affordable_masks(cost,sources,max_sources=max_sources,life_budget=life_budget)


def readiness_assumptions(starting_life):
    return (f'每回合抽牌、最多下一张地，在已见地牌中选择来源；每张产法术力地只计一点，雪境来源单独检查。'
            f'每个 X 按 1；非瑞克西亚费用按起始 {starting_life} 生命、至少保留 1 点生命分别测试一张牌，'
            '不累计此前生命付款或受到的伤害。没有法术力费用不等于 {0}。'
            '已识别的强制附加法术力和资源/法术力二选一费用按纯法术力分支计算，waterbend 不使用横置协助。'
            '不结算加速、进场横置、条件产费、费用增减、其它附加/替代费用、调度、合法目标或牌效；费用可支付不代表一定能行动。')


@lru_cache(maxsize=4096)
def _requires_colorless(cost,text):
    if '{C}' in cost:return True
    if '{C}' not in text:return False
    for line in re.split(r'\n|(?<=[.;])\s+',text):
        # Activated costs precede the colon. Producing {C} after it is not a
        # payment requirement (Mind Stone, pain lands and Scion tokens remain).
        if ':' in line and '{C}' in line.split(':',1)[0].rsplit('.',1)[-1]:return True
        if re.search(r'\bpay\s+(?:\{[^}]+\}\s*)*\{C\}',line,re.I):return True
        if re.search(r'^(?:ward|(?:multi)?kicker|flashback|escape|cycling|equip|unearth|embalm|eternalize|'
                     r'bestow|buyback|replicate|overload|surge|spectacle|evoke|emerge|foretell|disturb|'
                     r'cleave|prototype|disguise|morph|megamorph|plot|offspring)\s+(?:\{[^}]+\}\s*)*\{C\}',line,re.I):return True
    return False


def requires_colorless_mana(card):
    """Recognize printed casting, activated, pay and keyword costs with {C}.

    This is a construction preference, not an Oracle rules interpreter. Hybrid
    {C/W} can be paid with white and is deliberately not treated as mandatory C.
    """
    cost=card.get('mana_cost','');text=card.get('text','')
    return '{C}' in cost or '{C}' in text and _requires_colorless(cost,text)


def commander_basic_sources(catalog,spells,land_names,basics,commander=None):
    """Repair only a commander's missing colored sources with free basic swaps.

    Keep the original allocation if already payable or a full repair cannot be
    made without losing a previously payable spell. Do not create a C/Wastes
    strategy; nonbasic source limitations are the same as the readiness model.
    """
    if not commander:return dict(basics)
    cost=casting_mana_cost(catalog.cards[commander])
    needed=Counter(re.findall(r'\{([WUBRG])\}',cost))
    if not needed:return dict(basics)
    fixed=[set(catalog.cards[n]['fixing'])|({'S'} if 'Snow' in catalog.cards[n].get('type','').split() else set()) for n in land_names]
    counts=Counter(color for land in fixed for color in land)
    if all(counts[c]+basics.get(c,0)>=n for c,n in needed.items()):return dict(basics)
    def sources(allocation):return fixed+[{c} for c,n in allocation.items() for _ in range(n)]
    current=Counter(basics);original_sources=sources(current)
    protected=[casting_mana_cost(catalog.cards[n]) for n in spells if affordable(casting_mana_cost(catalog.cards[n]),original_sources)]
    for color in 'WUBRG':
        for _ in range(max(0,needed[color]-counts[color]-current[color])):
            donors=sorted((c for c,n in current.items() if c!=color and n>0 and counts[c]+n>needed[c]),
                          key=lambda c:(-current[c],c))
            for donor in donors:
                trial=Counter(current);trial[donor]-=1;trial[color]+=1
                if all(affordable(spell,sources(trial)) for spell in protected):current=trial;break
            else:return dict(basics)
    if not affordable(cost,sources(current)):return dict(basics)
    return {c:n for c,n in current.items() if n}
