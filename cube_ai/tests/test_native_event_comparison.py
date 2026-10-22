import itertools

import pytest

from cube_ai.tuning import _canonical,canonical_attackers

PREFIX='Combat: Ai(3)-p000_s2_BR assigned '
TARGET=' to attack Ai(1)-p000_s0_UW.'
CARDS=['Elemental Token (518)','Elemental Token (517)','Jaws, Relentless Predator (178)']


def line(cards):return PREFIX+', '.join(cards[:-1])+' and '+cards[-1]+TARGET


def test_unordered_attacker_printing_with_commas_and_instance_ids_is_stable():
    normalized={canonical_attackers(line(list(order))) for order in itertools.permutations(CARDS)}
    assert len(normalized)==1
    canonical=normalized.pop()
    assert canonical_attackers(canonical)==canonical
    assert all(card in canonical for card in CARDS)
    assert canonical.endswith(TARGET)


@pytest.mark.parametrize('changed',[
    line(CARDS).replace('(518)','(519)'),
    line(CARDS).replace('p000_s0_UW','p000_s1_BU'),
    line(CARDS[1:]),
    line(CARDS+['Elemental Token (518)']),
    line(CARDS).replace('Jaws, Relentless Predator','Anax and Cymede'),
])
def test_identity_target_missing_or_duplicate_attacker_is_not_hidden(changed):
    assert canonical_attackers(changed)!=canonical_attackers(line(CARDS))


@pytest.mark.parametrize('event',[
    'Combat: Ai(1)-a assigned Goblin and Elf to attack Ai(2)-b.',
    'Combat: Ai(1)-a assigned Goblin (1), unfinished to attack Ai(2)-b.',
    'Combat: Ai(1)-a assigned Goblin (1) and Elf (2) to block Bear (3).',
    'Combat: Ai(1)-a assigned Goblin (1) to attack Ai(2)-b. Ai(1)-a assigned Elf (2) to attack Ai(3)-c.',
])
def test_unrecognized_layouts_and_blocker_order_are_left_exact(event):
    assert canonical_attackers(event)==event


def test_damage_and_distinct_event_order_are_still_compared_exactly():
    attack=line(CARDS)
    damage='Damage: Jaws, Relentless Predator (178) deals 3 combat damage to Ai(1)-p000_s0_UW.'
    assert _canonical(attack+'\n'+damage)!=_canonical(damage+'\n'+attack)
    assert _canonical(attack+'\n'+damage)!=_canonical(attack+'\n'+damage.replace('deals 3','deals 4'))
