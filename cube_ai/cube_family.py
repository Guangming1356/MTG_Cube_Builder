"""Conservative, target-free grouping of identical and very similar Cube pools."""
from collections import Counter
import hashlib
import json

VERSION='cube-family-1'
SIMILARITY=.90


def pool_counts(rows,catalog=None):
    counts=Counter()
    for row in rows:
        name=row['name'];role=row['role']
        if not isinstance(name,str) or not name or not isinstance(role,str) or not role:
            raise ValueError('Cube 来源缺少有效卡名或槽位')
        card=catalog.cards.get(name,{}) if catalog is not None else {}
        identity='oracle:'+card['oracle_id'] if card.get('oracle_id') else 'name:'+name.casefold()
        counts[(identity,role)]+=1
    if not counts:raise ValueError('Cube 来源牌池为空')
    return counts


def group_cubes(pools,threshold=SIMILARITY):
    if not 0<threshold<=1:raise ValueError('牌池相似度阈值无效')
    names=sorted(pools);parent={n:n for n in names};tokens={};bits={};sizes={};canonical={}
    for name in names:
        entries=pools[name];mask=0;size=0
        if not entries:raise ValueError('Cube 来源牌池为空')
        for key,count in sorted(entries.items()):
            if type(count) is not int or count<1:raise ValueError('牌池卡张数量无效')
            for copy in range(count):
                token=(key,copy)
                if token not in tokens:tokens[token]=len(tokens)
                mask|=1<<tokens[token]
            size+=count
        bits[name]=mask;sizes[name]=size
        canonical[name]=hashlib.sha256(json.dumps(sorted(entries.items()),ensure_ascii=False).encode()).hexdigest()
    def find(name):
        while parent[name]!=name:parent[name]=parent[parent[name]];name=parent[name]
        return name
    links=[];checks=0
    for i,a in enumerate(names):
        for b in names[i+1:]:
            checks+=1
            if min(sizes[a],sizes[b])/max(sizes[a],sizes[b])<threshold:continue
            overlap=(bits[a]&bits[b]).bit_count();union=sizes[a]+sizes[b]-overlap
            if overlap/union>=threshold:
                x,y=find(a),find(b)
                if x!=y:parent[max(x,y)]=min(x,y)
                links.append(dict(a=a,b=b,shared=overlap,union=union,jaccard=overlap/union))
    families={name:find(name) for name in names}
    return families,dict(version=VERSION,threshold=threshold,pools=len(names),
        canonical_pools=len(set(canonical.values())),families=len(set(families.values())),
        pair_checks=checks,links=links,
        limitation='按卡张身份、槽位与数量合并高度相近的牌池；相似关系按连通分组。不能还原全部缺失的改版来源，也不证明不同组完全独立。')
