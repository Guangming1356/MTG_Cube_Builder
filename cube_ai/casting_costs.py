"""Narrow additional casting costs, separate from printed mana value.

The estimate pays recognized additional costs with mana. It does not assume
creatures/artifacts for waterbend or the resources of an optional mana fallback.
"""
import re

VERSION='additional-casting-1'
PREFIX='As an additional cost to cast this spell, '
MANA=r'(?:\{[^{}\s]+\})+'
DIRECT=re.compile(rf'(?P<kind>waterbend|pay) (?P<cost>{MANA})\.',re.I)
FALLBACK=re.compile(rf'(?P<support>.+) or pay (?P<cost>{MANA})\.',re.I)
REVERSE=re.compile(rf'pay (?P<cost>{MANA}) or (?P<support>.+)\.',re.I)
RESOURCE=re.compile(r'^(?:reveal|behold|sacrifice|discard|tap|exile|blight)\b',re.I)
SYMBOL=re.compile(r'\d+|X|[WUBRGCS]|2/[WUBRG]|[WUBRGC]/[WUBRGC]|[WUBRG](?:/[WUBRG])?/P')


def _value(cost):
    tokens=re.findall(r'\{([^}]+)\}',cost)
    if not tokens or ''.join('{'+s+'}' for s in tokens)!=cost or any(not SYMBOL.fullmatch(s) for s in tokens):return None
    return sum(int(s) if s.isdigit() else 2 if s.startswith('2/') else 1 for s in tokens)


def extract(text,mana_cost,mv):
    if not mana_cost or 'additional cost to cast this spell' not in text.lower():return {}
    requirements=[]
    for line in text.splitlines():
        if not line.lower().startswith(PREFIX.lower()):continue
        body=line[len(PREFIX):].strip()
        body=re.sub(r'\s+\([^\n]*\)$','',body).strip()
        if hit:=DIRECT.fullmatch(body):
            item=dict(kind='waterbend' if hit['kind'].lower()=='waterbend' else 'mana',cost=hit['cost'])
        elif (hit:=FALLBACK.fullmatch(body)) or (hit:=REVERSE.fullmatch(body)):
            support=hit['support']
            if not RESOURCE.search(support) or re.search(r'\b(?:may|if|unless)\b',support,re.I):continue
            item=dict(kind='mana_fallback',cost=hit['cost'],support=support)
        else:continue
        value=_value(item['cost'])
        if value is None:continue
        item['value']=value;requirements.append(item)
    if not requirements:return {}
    extra=''.join(item['cost'] for item in requirements)
    return dict(cast_mv=mv+sum(item['value'] for item in requirements),cast_mana_cost=mana_cost+extra,
                casting_requirements=requirements)


def curve_value(card):return card.get('cast_mv',card['mv'])


def mana_cost(card):return card.get('cast_mana_cost',card.get('mana_cost',''))


def messages(card):
    notes=[]
    for item in card.get('casting_requirements',[]):
        if item['kind']=='waterbend':notes.append('额外需 waterbend '+item['cost']+'；估算不使用生物或神器横置协助')
        elif item['kind']=='mana':notes.append('施放时还需支付 '+item['cost'])
        else:notes.append('可选择资源方式「'+item['support']+'」或额外支付 '+item['cost']+'；估算使用法术力分支')
        if '{X}' in item['cost']:notes.append('附加费用中的每个 X 按 1 估算，实际可依牌面选择数值')
    return notes


def report(cards):
    return [dict(name=c['name'],printed_mv=c['mv'],estimated_cast_mv=curve_value(c),notes=messages(c)) for c in cards if c.get('casting_requirements')]
