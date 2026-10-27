"""Mana preferences: generic costs are distinct from required colorless mana."""
import re
from collections import Counter
from functools import lru_cache


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
    cost=catalog.cards[commander]['mana_cost']
    needed=Counter(re.findall(r'\{([WUBRG])\}',cost))
    if not needed:return dict(basics)
    fixed=[set(catalog.cards[n]['fixing']) for n in land_names]
    counts=Counter(color for land in fixed for color in land)
    if all(counts[c]+basics.get(c,0)>=n for c,n in needed.items()):return dict(basics)
    from .draft import affordable
    def sources(allocation):return fixed+[{c} for c,n in allocation.items() for _ in range(n)]
    current=Counter(basics);original_sources=sources(current)
    protected=[catalog.cards[n]['mana_cost'] for n in spells if affordable(catalog.cards[n]['mana_cost'],original_sources)]
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
