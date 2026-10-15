"""Versioned Oracle-text ontology. Scores are expert heuristics, not win rates."""
import math
import re
from functools import lru_cache

VERSION = "ontology-1.3"
FAST_MANA = set("Black Lotus|Lotus Petal|Mana Crypt|Mana Vault|Sol Ring|Chrome Mox|Mox Diamond|Mox Opal|Mox Amber|Mox Jasper|Lion's Eye Diamond|Jeweled Lotus|Grim Monolith|Simian Spirit Guide|Elvish Spirit Guide".split("|"))
LOCKS = {"Stasis", "Winter Orb", "Static Orb", "Armageddon", "Ravages of War", "Jokulhaups", "Worldfire"}
COMBOS = [
    ["Exquisite Blood", "Sanguine Bond"], ["Exquisite Blood", "Vito, Thorn of the Dusk Rose"],
    ["Dualcaster Mage", "Twinflame"], ["Dualcaster Mage", "Heat Shimmer"],
    ["Kiki-Jiki, Mirror Breaker", "Zealous Conscripts"], ["Kiki-Jiki, Mirror Breaker", "Felidar Guardian"],
    ["Splinter Twin", "Deceiver Exarch"], ["Thassa's Oracle", "Demonic Consultation"],
    ["Thassa's Oracle", "Tainted Pact"], ["Heliod, Sun-Crowned", "Walking Ballista"],
    ["Peregrine Drake", "Deadeye Navigator"], ["Isochron Scepter", "Dramatic Reversal"],
    ["Karmic Guide", "Reveillark", "Ashnod's Altar"],
]
# Explicit, editable starting calibration. This is not claimed to be a trained model.
CALIBRATION = {
    "Swords to Plowshares": 4.3, "Path to Exile": 4.15, "Generous Gift": 3.8,
    "Counterspell": 4.0, "Arcane Denial": 3.8, "Pongify": 3.8, "Rapid Hybridization": 3.8,
    "Beast Within": 3.9, "Chaos Warp": 3.8, "Abrade": 3.65, "Lightning Bolt": 3.75,
    "Damnation": 4.05, "Wrath of God": 4.05, "Austere Command": 4.1,
    "Blasphemous Act": 4.2, "Firespout": 3.8, "Fracturing Gust": 3.75,
    "Oversimplify": 3.9, "Sun Titan": 4.05, "Grave Titan": 4.15, "Inferno Titan": 4.05,
    "Titan of Industry": 4.25, "Archon of Cruelty": 4.4, "Angel of Despair": 3.9,
    "Torrential Gearhulk": 4.1, "Mulldrifter": 3.7, "Baleful Strix": 3.9,
    "Mystic Snake": 3.8, "Frilled Mystic": 3.85, "Hydroid Krasis": 4.0,
    "Progenitor Mimic": 3.95, "Doppelgang": 4.05, "Shark Typhoon": 4.2,
    "Overwhelming Stampede": 4.0, "Craterhoof Behemoth": 4.65,
    "The Immortal Sun": 4.1, "Myr Battlesphere": 3.95, "Wurmcoil Engine": 4.3,
    "Stonecoil Serpent": 3.7, "Managorger Hydra": 3.95, "Soulquake": 3.7,
    "Birds of Paradise": 3.95, "Cultivate": 3.7, "Rampant Growth": 3.6,
    "Farseek": 3.65, "Arcane Signet": 3.9, "Mind Stone": 3.7,
    "Liquimetal Torque": 3.65, "Solemn Simulacrum": 3.8, "Wayfarer's Bauble": 3.6,
    "Blood Artist": 3.75, "Zulaport Cutthroat": 3.8, "Morbid Opportunist": 3.9,
    "Reassembling Skeleton": 3.3, "Victimize": 3.9, "Living Death": 4.3,
    "Eternal Witness": 4.0, "Reclamation Sage": 3.7, "Broken Bond": 3.45,
    "Frenzied Tilling": 2.7, "Coral Sword": 2.55, "Fire Sages": 2.5,
    "Grizzly Bears": 1.7, "Hill Giant": 1.4, "Scathe Zombies": 1.4,
    "Runeclaw Bear": 1.7, "Colossal Dreadmaw": 2.3,
}

def match(pattern, text):
    return bool(re.search(pattern, text, re.I | re.S))

def oracle(raw):
    return raw.get("oracle_text") or "\n".join(f.get("oracle_text", "") for f in raw.get("card_faces", []))

def tribes_from_cards(cards):
    types = set()
    for c in cards:
        for front in c.get("type_line", "").split(" // "):
            if "Creature" in front and "—" in front:
                types.update(front.split("—", 1)[1].lower().split())
    return types

@lru_cache(maxsize=4)
def tribal_pattern(tribes):
    irregular = {"elf": "elves", "dwarf": "dwarves", "wolf": "wolves", "mouse": "mice"}
    mapping = {}
    for t in tribes:
        mapping[t] = t; mapping[irregular.get(t,t+"s")] = t
    noun = "(?:"+"|".join(re.escape(t) for t in sorted(mapping,key=len,reverse=True))+")"
    pattern = re.compile(rf"\b(?:other|each|all|another|one or more|a|an|target|control) (?P<before>{noun})(?: creatures?| cards?)?\b|\b(?P<after>{noun}) (?:creatures?|spells you cast|you control)",re.I)
    return pattern,mapping

def tribal_requirements(text, tribes):
    # Token production is an enabler. A demanded subtype is a dependency.
    found = []
    pattern,mapping=tribal_pattern(tuple(sorted(tribes)))
    for hit in pattern.finditer(text):
        noun=next(x for x in hit.groups() if x)
        t=mapping[noun.lower()]
        variants='(?:'+'|'.join(re.escape(k) for k,v in mapping.items() if v==t)+')'
        self_supply=match(rf"create[^.]*\b{variants}\b",text)
        conditional=match(rf"whenever[^.]*\b{variants}\b[^.]*create",text)
        if not self_supply or conditional:found.append(t)
    if match(r"choose a creature type|of the chosen type|shares? (?:at least one )?creature type", text):
        found.append("chosen_type")
    return sorted(set(found))

def extract(raw, tribes):
    text = oracle(raw)
    front = (raw.get("card_faces") or [raw])[0]
    typ = front.get("type_line", raw["type_line"])
    mv = float(raw.get("cmc", 0))
    name = raw["name"]
    is_land = "Land" in typ
    creature = "Creature" in typ
    commander = ("Legendary" in typ and creature) or "can be your commander" in text.lower()
    mana_cost = front.get("mana_cost", raw.get("mana_cost", ""))
    interaction = match(r"counter target (?:spell|activated|triggered)|(?:destroy|exile|return) (?:another )?target (?:[^.]{0,35})?(?:creature|artifact|enchantment|permanent|planeswalker)|target creature gets -|deals? (?:\d+|x) damage to (?:any target|target creature)|(?:each|target) (?:opponent|player) sacrifices", text)
    wipe = match(r"(?:destroy|exile) all (?:[^.]{0,20})?(?:creatures|artifacts|enchantments|nonland permanents)|(?:each|all) creatures? (?:gets?|get) -|(?:return|exile) all (?:[^.]{0,20})?creatures|damage to each creature|each creature deals", text)
    ramp = not is_land and match(r"add \{|add (?:one|two|three) mana|search your library for[^.]{0,120}land|additional land|create[^.]*treasure token", text)
    draw = match(r"draw (?:a|two|three|four|five|six|seven|x|that many|cards? equal)|exile the top [^.]*may (?:play|cast)", text)
    evasive = match(r"\bflying\b|\btrample\b|\bmenace\b|can't be blocked", text)
    etb = match(r"when (?:this|~|" + re.escape(name.split(",")[0]) + r")[^.]{0,50} enters", text)
    enablers, payoffs = set(), set()
    rules = {
        "tokens": (r"create[^.]{0,140}tokens?", r"tokens? (?:you control|would be created)|whenever[^.]*tokens?[^.]*enters|populate"),
        "sacrifice": (r"sacrifice (?:a|another|an|any number of) (?:creature|permanent|artifact)|creature tokens?|returns?[^.]*graveyard", r"whenever[^.]{0,90}(?:dies|sacrifice)|whenever[^.]*leaves the battlefield"),
        "graveyard": (r"\bmill\b|discard (?:a|two|your)|surveil|dies|sacrifice a creature", r"(?:return|cast|play|exile)[^.]{0,100}(?:from|in) (?:your|a) graveyard|flashback|escape|delve"),
        "blink": (r"exile[^.]{0,100}return[^.]*battlefield|return target[^.]*you control[^.]*hand", r"when[^.]{0,80}enters|whenever[^.]*enters"),
        "counters": (r"(?:put|enters with)[^.]*\+1/\+1 counter|proliferate", r"(?:with|has|have|each)[^.]{0,45}\+1/\+1 counter|modified creatures|would be put"),
        "lifegain": (r"(?:gain|gains) (?:\d+|x|that much) life|lifelink", r"whenever you gain life|if you gained life|life you gained"),
        "spells": (r"instant|sorcery|noncreature|prowess", r"whenever you cast[^.]*(?:instant|sorcery|noncreature)|magecraft|prowess|copy target[^.]*spell"),
        "artifacts": (r"artifact|treasure|clue|food|blood token", r"whenever[^.]*artifact|artifacts you control|artifact spells|affinity for artifacts|metalcraft"),
        "lands": (r"additional land|search your library for[^.]*land|return[^.]*land[^.]*graveyard", r"landfall|whenever a land[^.]*enters|lands you control"),
        "equipment": (r"equipment|equip \{|attach[^.]*equipment", r"equipped|equipment you control|whenever[^.]*equipment"),
        "combat": (r"haste|trample|double strike|first strike|can't be blocked|menace", r"whenever[^.]*attacks|combat damage|extra combat|additional combat"),
        "control": (r"counter target|destroy target|exile target|return target", r"whenever[^.]*opponent|at the beginning of your upkeep"),
        "draw": (r"draw|investigate", r"whenever you draw|second card|cards in your hand"),
    }
    for theme, (supply, demand) in rules.items():
        if match(supply, text): enablers.add(theme)
        if match(demand, text): payoffs.add(theme)
    # Self references are not demands for the card's creature subtype.
    dependency_text=text.replace(name,'').replace(name.split(' // ')[0],'')
    subtype_dependencies = tribal_requirements(dependency_text, tribes)
    front_unusable = raw.get('layout')=='meld' and not mana_cost
    if front_unusable:commander=False
    extra_deck = match(r'\battractions?\b|\bstickers?\b|\bcontraptions?\b',text)
    named_dependency = match(r'(?:card|cards) named [^.]{2,100}',text) and match(r'search[^.]*named|control[^.]*named|exile[^.]*named',text)
    if extra_deck:score_penalty=.7
    else:score_penalty=0
    if match(r'skip your next (?:two|three) turns',text):score_penalty+=1.2
    if named_dependency:score_penalty+=.45
    fast = name in FAST_MANA or (not is_land and mv == 0 and match(r"add \{", text)
        and not match(r"multikicker|suspend|pay [^.]*life|remove[^.]*charge counter", text))
    mld = name in LOCKS or match(r"destroy all lands|sacrifices? all lands|lands don't untap", text)
    finisher = not is_land and (
        creature and mv >= 6 and (evasive or etb or match(r"whenever[^.]*attacks|destroy|exile|create[^.]*tokens",text))
        or "Planeswalker" in typ and mv >= 5
        or mv >= 4 and match(r"creatures you control get \+[^.]*until end of turn|each opponent loses (?:x|half|\d{2})|additional combat",text)
        or mv >= 5 and "Enchantment" in typ and match(r"whenever[^.]*damage|create[^.]*tokens|return[^.]*battlefield",text))
    rank = raw.get("edhrec_rank") or 50000
    popularity = max(-.35, min(.4, .22 * (3.3 - math.log10(max(rank, 10)))))
    try:
        body = (float(front.get("power", 0)) + float(front.get("toughness", 0))) / max(1, mv)
    except (ValueError, TypeError):
        body = 1.5
    score = 2.7 + popularity
    score += .35 * interaction + .35 * wipe + .35 * draw + .25 * etb
    score += .25 * (ramp and mv <= 3) + .18 * evasive + .2 * finisher
    score += .17 * min(3, len(enablers & payoffs))
    if creature: score += max(-.3, min(.35, .25 * (body - 1.6)))
    if not text.strip(): score -= .9
    if mv > 7: score -= .13 * (mv - 7)
    if subtype_dependencies: score -= .45
    score = CALIBRATION.get(name, max(1.0, min(4.65, score)))
    score=max(1.0,score-score_penalty)
    kind = "land" if is_land else next((k.lower() for k in ["Creature", "Planeswalker", "Instant", "Sorcery", "Enchantment", "Artifact"] if k in typ), "other")
    if kind in {"instant","sorcery"}:enablers.add("spells")
    if "Artifact" in typ:enablers.add("artifacts")
    if "Equipment" in typ:enablers.add("equipment")
    bucket = str(max(1, int(mv))) if mv < 5 else "5+"
    vector = [1, min(mv, 10) / 10, float(creature), float(interaction), float(wipe), float(ramp),
              float(draw), float(finisher), float(evasive), float(etb), float(commander),
              len(enablers) / 10, len(payoffs) / 10, float(bool(subtype_dependencies)),
              popularity, min(body, 5) / 5, float("{X}" in mana_cost)]
    return dict(mv=mv, bucket=bucket, kind=kind, commander=bool(commander), creature=creature,
                interaction=interaction, wipe=wipe, ramp=ramp, draw=draw, finisher=bool(finisher),
                enablers=sorted(enablers), payoffs=sorted(payoffs), tribal=subtype_dependencies,
                fast_mana=bool(fast), mld=mld, quality=round(score, 3), vector=vector,
                front_unusable=bool(front_unusable),extra_deck=extra_deck,named_dependency=bool(named_dependency),
                calibrated=name in CALIBRATION, mana_cost=mana_cost)
