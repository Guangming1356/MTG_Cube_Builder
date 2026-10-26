import itertools

import pytest

from cube_ai.tuning import _canonical,canonical_attackers,canonical_blockers

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


BLOCK="Ai(1)-p000_s0_W assigned Sunstar Expansionist (1) to block Ragavan, Nimble Pilferer (142)."
UNBLOCKED="Ai(1)-p000_s0_W didn't block Hulk, Always Angry (152)."


def test_block_target_display_order_keeps_complete_assignments():
    a='Combat: '+BLOCK+UNBLOCKED;b='Combat: '+UNBLOCKED+BLOCK
    assert canonical_blockers(a)==canonical_blockers(b)
    assert canonical_blockers(canonical_blockers(a))==canonical_blockers(a)
    assert _canonical(a)==_canonical(b)


@pytest.mark.parametrize('changed',[
    BLOCK.replace('(1)','(2)'),BLOCK.replace('(142)','(143)'),
    BLOCK.replace('Sunstar Expansionist','Anax and Cymede'),
    BLOCK.replace('p000_s0_W','p000_s1_U'),
    BLOCK.replace('Sunstar Expansionist (1)','Sunstar Expansionist (1) and Elf (9)'),
    UNBLOCKED,
])
def test_blocker_identity_assignment_controller_and_count_remain_differences(changed):
    assert canonical_blockers('Combat: '+changed+UNBLOCKED)!=canonical_blockers('Combat: '+BLOCK+UNBLOCKED)


def test_blocker_list_order_and_separate_event_order_remain_exact():
    a=BLOCK.replace('Sunstar Expansionist (1)','Sunstar Expansionist (1) and Elf (9)')
    b=BLOCK.replace('Sunstar Expansionist (1)','Elf (9) and Sunstar Expansionist (1)')
    assert canonical_blockers('Combat: '+a+UNBLOCKED)!=canonical_blockers('Combat: '+b+UNBLOCKED)
    damage='Damage: Ragavan, Nimble Pilferer (142) deals 2 damage to Sunstar Expansionist (1).'
    assert _canonical('Combat: '+BLOCK+UNBLOCKED+'\n'+damage)!=_canonical(damage+'\nCombat: '+BLOCK+UNBLOCKED)
    assert _canonical(damage)!=_canonical(damage.replace('(1)','(2)'))


@pytest.mark.parametrize('event',[
    'Combat: '+BLOCK+UNBLOCKED[:-1],
    'Combat: '+BLOCK+UNBLOCKED.replace('Ai(1)-p000_s0_W','Ai(2)-another'),
    'Combat: '+BLOCK.replace('Sunstar Expansionist (1)','missing instance')+UNBLOCKED,
    'Combat: '+BLOCK.replace(' to block ',' to attack ')+UNBLOCKED,
    'Combat: '+BLOCK+'unrecognized text.',
    'Combat: '+BLOCK.replace('Ai(1)-p000_s0_W','Human Player')+UNBLOCKED,
])
def test_ambiguous_blocker_layout_is_left_exact(event):
    assert canonical_blockers(event)==event
