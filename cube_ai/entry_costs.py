"""Conservative recognition of severe mandatory costs on a creature's entry.

These flags describe printed burdens, not legality or a complete synergy check.
Only whole, unconditional trigger bodies qualify; optional kicker and ordinary
sacrifice/discard outlets are outside this correction.
"""
import re

ENTRY=re.compile(r'when(?:ever)? (this (?:creature|permanent)|this|~|[^.\n,]{1,60}) enters(?: the battlefield)?(?: or attacks)?,\s*(.+)',re.I)
POWER=re.compile(r'^sacrifice (?:it|this creature) unless you sacrifice any number of creatures with total power (\d+) or greater\.?$',re.I)
LANDS=re.compile(r'^sacrifice (?:it|this creature) unless you sacrifice (two|three|four|five|six|\d+) (?:lands?|Forests?|Swamps?|Islands?|Mountains?|Plains)\.?$',re.I)
LIBRARY=re.compile(r'^exile all cards from your library(?: face down)?(?:\.|, then shuffle all cards from your graveyard into your library\.)$',re.I)
BOARD=re.compile(r'^target opponent gains control of all (?:other )?permanents you control\.?$',re.I)
SKIP=re.compile(r'^(?:you )?skip your next (?:(two|three) )?turns?\.?$',re.I)
WORDS={'two':2,'three':3,'four':4,'five':5,'six':6}
LABELS={
    'sacrifice_large_power':'进场需额外牺牲高总力量的生物',
    'sacrifice_multiple_lands':'进场需额外牺牲多张地',
    'exile_own_library':'进场会放逐自己的整个牌库',
    'give_away_board':'进场会把自己的其它永久物交给对手',
    'skip_own_turns':'进场会略过自己的回合',
}


def entry_burden(text,name=''):
    risks=[];penalty=0.;entry_lines=[];bad_lines=[]
    if 'enters' not in text.lower():return dict(risks=risks,penalty=penalty,negative_only=False)
    for line in text.splitlines():
        trigger=ENTRY.fullmatch(line.strip())
        if not trigger:continue
        subject=trigger.group(1).casefold()
        if subject not in {'this creature','this permanent','this','~',name.casefold(),name.split(',')[0].casefold()}:continue
        entry_lines.append(line);body=trigger.group(2).strip()
        if (hit:=POWER.fullmatch(body)) and int(hit[1])>=8:
            risks.append('sacrifice_large_power');penalty+=1.25;bad_lines.append(line)
        elif hit:=LANDS.fullmatch(body):
            amount=WORDS.get(hit[1].lower(),int(hit[1]) if hit[1].isdigit() else 0)
            if amount>=2:risks.append('sacrifice_multiple_lands');penalty+=.75 if amount==2 else 1.;bad_lines.append(line)
        elif LIBRARY.fullmatch(body):
            risks.append('exile_own_library');penalty+=.75 if 'then shuffle' in body.lower() else 1.25;bad_lines.append(line)
        elif BOARD.fullmatch(body):
            risks.append('give_away_board');penalty+=1.25;bad_lines.append(line)
        elif hit:=SKIP.fullmatch(body):
            # The existing ontology already deducts 1.2 for skipping 2/3 turns.
            risks.append('skip_own_turns');penalty+=.5 if not hit[1] else 0.;bad_lines.append(line)
    return dict(risks=risks,penalty=penalty,negative_only=bool(bad_lines) and len(bad_lines)==len(entry_lines))


def messages(card):
    return [LABELS[code] for code in card.get('entry_risks',[]) if code in LABELS]


def report(cards):
    return [dict(name=card['name'],costs=messages(card)) for card in cards if card.get('entry_risks')]
