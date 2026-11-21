"""Additional paper card records needed by the MTGO Vintage Cube reference."""
import json
from pathlib import Path

from .config import DATA

ASSET=DATA/'vintage_supplement.json'
REFERENCE=DATA/'vintage_reference.json'


def load(path=ASSET):
    data=json.loads(Path(path).read_text(encoding='utf8'))
    cards=data['cards']
    if not isinstance(cards,list) or any(not isinstance(c,dict) or not c.get('name') for c in cards):
        raise ValueError('Vintage card supplement is invalid')
    return cards


def bundle_asset(path=ASSET, reference_path=REFERENCE):
    load(path)
    reference=json.loads(Path(reference_path).read_text(encoding='utf8'))
    if len(reference.get('entries',[]))!=540:raise ValueError('Vintage reference is incomplete')
    return {'cube_ai/data/vintage_supplement.json':Path(path).read_bytes(),
            'cube_ai/data/vintage_reference.json':Path(reference_path).read_bytes()}


def reference(catalog, path=REFERENCE):
    """Resolve the official snapshot against the active catalog without guessing."""
    from .config import BuildSpec
    data=json.loads(Path(path).read_text(encoding='utf8'))
    entries=data['entries'];rows=[];unknown=[]
    for entry in entries:
        name=catalog.resolve(entry['name'])
        if not name:unknown.append(entry['name']);continue
        rows.append(dict(name=name,role='Land' if catalog.cards[name]['kind']=='land' else 'Main'))
    if unknown:raise ValueError('Vintage 参考牌表缺少牌张：'+', '.join(unknown))
    if len(rows)!=540 or len({r['name'] for r in rows})!=540:raise ValueError('Vintage 参考牌表不完整或有重复')
    lands=sum(r['role']=='Land' for r in rows)
    spec=BuildSpec.from_dict(dict(name='MTGO Vintage Cube · 2026-10-07',mode='classic',size=540,lands=lands,
        legality_format='vintage',exclude_game_changers=False,allow_fast_mana=True,allow_colorless_costs=True,
        allow_extra_turns=True,allow_infinite_combos=True,avoid_tribal=False,allow_mass_land_destruction=True,
        audit_profile='open',pack_collation='random'))
    return dict(spec=spec.to_dict(),cards=rows,source=data['source'],fetched=data['fetched'],description=data['description'])
