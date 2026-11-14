"""Reproductions for preference filtering and early native-result recording."""
import copy
from types import SimpleNamespace

import pytest

from cube_ai.catalog import Catalog
from cube_ai.config import BuildSpec
from cube_ai.deck_building import revise
from cube_ai.task_control import TaskControl


@pytest.mark.parametrize('future,allow_colorless,allowed',[(False,False,False),(False,True,True),(True,False,False)])
def test_custom_policy_does_not_reinsert_excluded_drafted_spells(future,allow_colorless,allowed):
    real=Catalog();cards={}
    for i in range(36):
        name=f'Expensive fixture {i:02d}'
        cards[name]=dict(real.cards['Wurmcoil Engine'],name=name,quality=3.0)
    commander='Gonti, Lord of Luxury';cards[commander]=real.cards[commander]
    blocked='Future cheap fixture' if future else 'Warping Wail'
    cards[blocked]=dict(real.cards['Warping Wail'],name=blocked,quality=3.0)
    if future:cards[blocked].update(mana_cost='{2}',released='2999-01-01',text='')
    names=[n for n in cards if n not in {commander,blocked}]
    deck=dict(buildable=True,spells=names,commander=commander,lands=[],identity='B',
              land_count=23,basics={'B':23},drafted=names+[commander,blocked])
    before=copy.deepcopy(deck)
    revised=revise(SimpleNamespace(cards=cards),deck,BuildSpec(allow_colorless_costs=allow_colorless),'balanced')
    assert (blocked in revised['spells']) is allowed
    assert deck==before


def test_native_result_can_be_recorded_before_any_progress_message(tmp_path):
    folder=tmp_path/'new-job'/'control';control=TaskControl(folder)
    control.record(dict(outcome='win',winner='fixture'),tmp_path/'logs')
    assert (folder/'completed-games.jsonl').is_file()
