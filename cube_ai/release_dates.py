"""Offline paper-print witnesses, separate from legality and snapshot print data."""
import hashlib
import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from .config import ROOT

VERSION='paper-release-witness-1'
ASSET=ROOT/'data/paper_release_witnesses.json'
ASSET_SHA='43d55d254e78873ba1009e8ca7cb98281a14164798e5cdad3c878382d4250e64'


def _decode(raw):
    if hashlib.sha256(raw).hexdigest()!=ASSET_SHA:raise ValueError('Paper release evidence missing or modified')
    value=json.loads(raw)
    if value.get('version')!=VERSION or not isinstance(value.get('cards'),list):raise ValueError('Paper release evidence schema mismatch')
    reviewed=date.fromisoformat(value['reviewed']);records={}
    for row in value['cards']:
        if (not isinstance(row.get('name'),str) or not row['name'] or not isinstance(row.get('set'),str)
            or str(UUID(row['oracle_id']))!=row['oracle_id'] or str(UUID(row['print_id']))!=row['print_id']
            or row['source']!='https://api.scryfall.com/cards/'+row['print_id']
            or date.fromisoformat(row['released_at'])>reviewed or row['oracle_id'] in records):
            raise ValueError('Invalid paper release witness')
        records[row['oracle_id']]=row
    return records


@lru_cache(maxsize=1)
def _asset(path,size,modified):
    return _decode(Path(path).read_bytes())


def paper_witness(card,as_of=None):
    """Return a copy of a verified past paper print; unknown/corrupt data fails closed.

    A witness proves a prior printing, not first-ever release or current legality.
    The name and Oracle ID must both match. No network is used during building.
    """
    today=as_of or date.today().isoformat()
    try:
        stat=ASSET.stat();records=_asset(str(ASSET.resolve()),stat.st_size,stat.st_mtime_ns)
        row=records.get(card.get('oracle_id'))
        if row and row['name']==card.get('name') and row['released_at']<=today:return dict(row)
    except (OSError,ValueError,KeyError,TypeError,AttributeError):pass
    return None


def bundle_asset(path):
    raw=Path(path).read_bytes();_decode(raw)
    return {'cube_ai/data/paper_release_witnesses.json':raw}
