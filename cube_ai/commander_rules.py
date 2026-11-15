"""Commander type eligibility and narrow command-zone setup requirements.

CR 903.3 includes legendary Vehicles and Spacecraft with P/T boxes. Eligibility
is separate from legality filters and from the automatic builder's setup policy.
"""
import re

OUTSIDE_CREATURE=re.compile(r"as long as ([^.\n]{1,80}) isn't on the battlefield, (?:it's|it is) a [^.\n]{1,100} creature in addition to its other types\.",re.I)
HAND_LOSS=re.compile(r"when ([^.\n,]{1,80}) enters(?: the battlefield)?, if you (?:didn't|did not) cast (?:it|this card) from your hand, you lose the game\.",re.I)
GRAVEYARD_ONLY=re.compile(r"you may cast ([^.\n]{1,80}) from your graveyard, but not from anywhere else\.",re.I)
LABELS={
    'hand_cast_required':'从指挥区直接施放会触发自身败北，需要转入手牌或处理触发的专门配合',
    'graveyard_only':'只能从坟场施放，不能直接从指挥区施放',
    'conditional_alternative_cost':'没有通常法术力费用，需要满足替代施放费用的条件',
}


def _self_names(name):
    own={name.casefold(),name.split(',')[0].casefold(),'this creature','this permanent','this card'}
    first=name.split()[0].casefold() if name else ''
    if first and first not in {'the','a','an'}:own.add(first)
    return own


def eligible(raw):
    front=(raw.get('card_faces') or [raw])[0]
    typ=front.get('type_line',raw.get('type_line',''));text=front.get('oracle_text',raw.get('oracle_text',''))
    if 'can be your commander' in text.lower():return True
    if 'Legendary' not in typ:return False
    if 'Creature' in typ or 'Vehicle' in typ:return True
    if 'Spacecraft' in typ and front.get('power') not in (None,'') and front.get('toughness') not in (None,''):return True
    # Grist's first ability operates during construction as well as other
    # non-battlefield zones; this does not turn its battlefield role into a body.
    own=_self_names(front.get('name',raw.get('name','')))
    return any(match[1].casefold() in own for match in OUTSIDE_CREATURE.finditer(text.replace('’',"'")))


def setup_requirements(text,name,mana_cost):
    text=text.replace('’',"'");risks=[]
    own=_self_names(name)
    for trigger in HAND_LOSS.finditer(text):
        if trigger[1].casefold() in own:
            risks.append('hand_cast_required');break
    if any(match[1].casefold() in own for match in GRAVEYARD_ONLY.finditer(text)):risks.append('graveyard_only')
    if not mana_cost:risks.append('conditional_alternative_cost')
    return risks


def automatic(card,spec):
    return bool(card.get('commander') and card['identity']!='C'
        and (not card.get('commander_setup') or spec.allow_setup_commanders))


def messages(card):
    return [LABELS[key] for key in card.get('commander_setup',[]) if key in LABELS]
