"""Conservative resource roles derived from Oracle instructions and type lines.

These are design heuristics, not a rules interpreter or a readiness estimate.
An action on an Adventure/transform face can qualify, but may require setup.
Tutors, attachment support and draw multipliers are kept distinct from pieces.
"""
import re


# CR 205.3, effective 2026-09-25. Other subtype families are also inferred from
# unmixed type lines in the supplied snapshot; never infer tribes from planes.
# Source: https://magic.wizards.com/en/rules
NONCREATURE_SUBTYPES=frozenset('''Attraction Blood Bobblehead Book Clue Contraption
Equipment Food Fortification Gold Heartwood Incubator Infinity Junk Lander Map
Mutagen Powerstone Spacecraft Stone Treasure Vehicle Vibranium Aura Background
Cartouche Case Class Curse Plan Role Room Rune Saga Shard Shrine Cave Desert
Forest Gate Island Lair Locus Mine Mountain Plains Planet Power-Plant Sphere
Swamp Tower Town Urza’s Adventure Arcane Lesson Omen Trap Siege'''.lower().split())


def creature_types(cards):
    creatures=set();other=set(NONCREATURE_SUBTYPES)
    for card in cards:
        for face in card.get('type_line','').split(' // '):
            head,dash,tail=face.partition('—')
            if not dash:continue
            # Time Lord is one creature type, not two independent demands.
            types={t.lower() for t in re.findall(r'Time Lord|[^\s]+',tail,flags=re.I)}
            kinds=set(head.split())
            if kinds & {'Creature','Kindred'}:creatures.update(types)
            elif kinds & {'Artifact','Enchantment','Land','Battle','Planeswalker','Instant','Sorcery'}:other.update(types)
    return creatures-other


_ACTION=re.compile(r',\s*(?:(?:you|each player|target player|that player|they|it|this [\w-]+)\s+)?(?:may\s+)?(?:draws?|creates?|puts?|returns?|gains?|loses?|deals?|adds?|exiles?|mills?|discards?|counters?|destroys?|taps?|untaps?|sacrifices?|pays?|scr(?:y|ies)|surveils?|investigate|choose)\b',re.I)
_DRAW=re.compile(r'\bdraws?\s+(?:(?:up to|an? additional)\s+)?(?:an?|one|two|three|four|five|six|seven|eight|nine|ten|x|\d+|that many|cards? equal)\b',re.I)


def _instructions(line):
    """Separate a leading trigger/condition from its body where identifiable."""
    text=line.strip().lstrip('• ')
    if re.match(r'(?:when(?:ever)?\b|at the beginning\b|if\b)',text,re.I):
        action=_ACTION.search(text)
        if action:return text[:action.start()+1],text[action.start()+1:]
        if re.match(r'when(?:ever)?\b|at the beginning\b',text,re.I):return text,''
    return '',text


def resource_roles(raw):
    text=raw.get('oracle_text') or '\n'.join(f.get('oracle_text','') for f in raw.get('card_faces',[]))
    typ=raw.get('type_line','')
    equipment=any('Equipment' in face.split('—')[-1].split() for face in typ.split(' // ') if '—' in face)
    draw=False;payoff=False;multiplier=False;effects=[]
    for line in text.splitlines():
        own_multiplier=bool(re.match(r'\s*if you would draw\b',line,re.I) and re.search(r'\binstead\b',line,re.I))
        header,body=_instructions(line)
        payoff |= bool(re.search(r'\bdraws?\b',header)) or own_multiplier
        multiplier |= own_multiplier
        if own_multiplier:continue
        effects.append(body)
        for hit in _DRAW.finditer(body):
            prefix=body[:hit.start()]
            context=re.split(r'[,;:\n.!?]',prefix)[-1].lower()
            if re.search(r"can't|cannot|can’t|\bnot to\b",context):continue
            if re.search(r'\bopponents?\b',context) and not re.search(r'\byou\b|each player|target player',context):continue
            if re.search(r'\bthat player\b',context) and re.search(r'\b(?:target|an|each|your) opponents?\b',prefix,re.I) and not re.search(r'\byou\b',context):continue
            draw=True
        if re.search(r'\binvestigate\b',body,re.I):draw=True
    effects='\n'.join(effects)
    if re.search(r'\bcycling\s+(?:\{|—)',text,re.I):draw=True
    if re.search(r'create[^.\n]{0,160}\bEquipment(?: artifact)? tokens?\b',effects,re.I):equipment=True
    # A token converter only supplies pieces if this card also creates those
    # tokens. Merely rewarding or converting someone else's tokens is support.
    for token in re.findall(r'\b([\w-]+) tokens? you control are Equipment\b',text,re.I):
        if re.search(r'create[^.\n]{0,160}\b'+re.escape(token)+r' tokens?\b',effects,re.I):equipment=True
    access=bool(re.search(r'(?:search your library|return|put)[^.\n]{0,180}\bEquipment\b',effects,re.I))
    attachment=bool(re.search(r'\b(?:attach|unattach|equip abilities|have equip)\b',effects,re.I))
    equipment_payoff=bool(re.search(r'\bequipped\b|Equipment (?:you control|attached)|whenever[^.\n]*Equipment',text,re.I)) or access or attachment
    return dict(draw_source=draw,draw_payoff=payoff or bool(re.search(r'cards in your hand',text,re.I)),draw_multiplier=multiplier,
        equipment_piece=equipment,equipment_access=access,equipment_attachment=attachment,equipment_payoff=equipment_payoff)
