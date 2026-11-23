"""Format-scoped, versioned draft priorities from public pick data.

CubeCobra Elo describes aggregate draft picks across many Cubes, not Vintage
game outcomes. The modest blend is a prior, not a claim of card win rate.
"""
import json
import math
from functools import lru_cache
from pathlib import Path
from .config import DATA

VERSION='vintage-pick-prior-1'
PRIOR=DATA/'vintage_pick_prior.json'


@lru_cache(maxsize=1)
def vintage_prior():
    return json.loads(PRIOR.read_text(encoding='utf8'))


def bundle_asset(path=PRIOR):
    data=Path(path).read_bytes();prior=json.loads(data)
    elos=prior.get('elos')
    if not isinstance(elos,dict) or len(elos)!=prior.get('count') or not elos:
        raise ValueError('Vintage draft prior is incomplete')
    if any(not isinstance(k,str) or not isinstance(v,(int,float)) or not math.isfinite(v) for k,v in elos.items()):
        raise ValueError('Vintage draft prior has invalid values')
    return {'cube_ai/data/vintage_pick_prior.json':data}


def draft_score(card,spec):
    base=card['quality']
    if spec.mode!='classic' or spec.legality_format!='vintage':return base
    prior=vintage_prior();elo=prior['elos'].get(card['name'])
    if elo is None:return base
    # Bounded to prevent one aggregate statistic from fully replacing the
    # local role/quality model or inventing win rates for unsupported cards.
    return base+max(-.8,min(3.5,(elo-prior['median'])/300))


def report(rows,spec):
    if spec.mode!='classic' or spec.legality_format!='vintage':return None
    prior=vintage_prior();covered=sum(r['name'] in prior['elos'] for r in rows)
    return dict(version=VERSION,source=prior['source'],retrieved=prior['retrieved'],
        source_last_modified=prior['source_last_modified'],covered=covered,total=len(rows),
        limitation='全站 CubeCobra 选牌 Elo 是有限的轮抓偏好先验，非 Vintage 专属数据，也不是实战胜率；未收录的牌沿用项目评分。')
