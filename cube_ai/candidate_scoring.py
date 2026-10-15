"""Batch the existing utility exactly; optional GPU handles only dense products."""
import numpy as np
from .config import GUILDS
from .design import package_roles,design_bonus
from .brackets import score_adjustment
from .acceleration import linear

def batch_utility(cards,model,spec,opponent_gift,backend='auto'):
    if not cards:return {},dict(backend='cpu',rows=0)
    matrix=[];compatible=[]
    for card in cards:
        p=package_roles(card)
        matrix.append([card['mv']<=2,card['interaction'],card['draw'],card['finisher'],card['creature'],
            p['sacrifice']['fodder'],p['sacrifice']['outlet'],p['sacrifice']['reward'],
            p['reanimator']['entry'],p['reanimator']['return_'],p['reanimator']['target']])
        compatible.append([card['identity']=='C' or set(card['identity'])<=set(g) for g in GUILDS])
    weights=np.zeros((11,20),dtype=np.float32)
    for j,g in enumerate(GUILDS):
        need=model['guilds'][g];pressure=need['pressure']
        weights[:5,j]=[pressure*model['low_weight']*(1+need['low']),pressure*.18*(1+need['interaction']),
            pressure*.1*(1+need['draw']),pressure*model['finisher_weight']*(1+need['finisher']),pressure*.08*(1+need['creature'])]
        gaps=need.get('package_gaps',{})
        weights[5:,j+10]=[gaps.get(p+':'+k,0) for p,k in
            [('sacrifice','fodder'),('sacrifice','outlet'),('sacrifice','reward'),('reanimator','entry'),('reanimator','return'),('reanimator','target')]]
    values,meta=linear(np.asarray(matrix,dtype=np.float32),weights,backend)
    mask=np.asarray(compatible,dtype=np.float32);counts=np.maximum(1,mask.sum(axis=1))
    role=(values[:,:10]*mask).sum(axis=1)/counts
    support=(values[:,10:]*mask).sum(axis=1)/counts
    scores={c['name']:float(c['quality']+role[i]+min(.06,.03*support[i])+design_bonus(c,spec)+score_adjustment(c,spec)-.9*opponent_gift(c)) for i,c in enumerate(cards)}
    return scores,meta
