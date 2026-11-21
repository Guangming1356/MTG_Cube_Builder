"""Offline deck evaluation using a pinned upstream MIT-licensed metric.

The upstream project normally relies on Scryfall function tags. This adapter
recognizes only explicit targeted removal in Oracle text; unknown effects stay
unscored, rather than being treated as weak cards or assigned invented tags.
"""
import re
from functools import lru_cache

from .mtg_draft_metrics import removal_kind,removal_quality

VERSION='mtg-draft-removal-1'
SOURCE='https://github.com/albertngo1/mtg-draft'
COMMIT='ac9bc2a8e73ffe0442726d29e087cfcd4a39c4a8'


@lru_cache(maxsize=8192)
def _evaluate(text,types,mv):
    pattern=r'\b(destroy|exile|return) target (?:up to one )?(nonland permanent|permanent|creature|planeswalker|artifact|enchantment)\b'
    match=re.search(pattern,text,re.I)
    attrs=set()
    if match:
        action,target=match.group(1).lower(),match.group(2).lower()
        if action=='return' and not re.search(r'to (?:its owner.s|their owner.s|your) hand',text[match.end():],re.I):return None
        attrs.add({'destroy':'removal-destroy','exile':'removal-exile','return':'removal-bounce'}[action])
        attrs.add({'nonland permanent':'removal-nonland','permanent':'removal-permanent',
                   'creature':'removal-creature','planeswalker':'removal-planeswalker',
                   'artifact':'removal-artifact','enchantment':'removal-enchantment'}[target])
        if target=='creature' and re.match(r'\s+or planeswalker\b',text[match.end():],re.I):attrs.add('removal-planeswalker')
    elif re.search(r'\bdeals? (?:\d+|x) damage to (?:any target|target creature)',text,re.I):
        attrs.update({'removal-creature','removal-burn'})
    else:return None
    record=dict(types=types.split(),keywords=['flash'] if re.search(r'\bflash\b',text,re.I) else [],cmc=mv)
    value,weights=removal_quality(record,attrs);kind=removal_kind(record,attrs)
    return value,tuple(weights.items()),tuple(kind.items())


def evaluate(cards):
    """Return interpretable upstream removal estimates, not win probabilities."""
    entries=[];unsupported=[];interactions=0
    for card in cards:
        if not card.get('interaction'):continue
        interactions+=1
        result=_evaluate(card.get('text',''),card.get('type','').split(' // ')[0],card.get('mv',0))
        if result is None:unsupported.append(card['name']);continue
        value,weights,kind=result
        entries.append(dict(name=card['name'],value=round(value,3),weights=dict(weights),kind=dict(kind)))
    return dict(version=VERSION,source=SOURCE,commit=COMMIT,license='MIT',
        removal_power=round(sum(item['value'] for item in entries),3),classified=len(entries),
        interactions=interactions,unclassified=unsupported,entries=entries,
        limitation='Only explicit targeted removal is classified from Oracle text; unclassified interaction is not scored. The upstream weights are judgments, not win rates.')
