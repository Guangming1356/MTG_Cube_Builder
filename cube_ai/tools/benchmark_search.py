"""Compare identical development workloads; screening quality is reported separately."""
import copy
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

from cube_ai.catalog import Catalog
from cube_ai.config import BuildSpec
from cube_ai.optimize import draft_evaluation,schedule,objective
from cube_ai.search import CandidateEvaluator
from cube_ai.sim_cache import DraftWorkspace


def main():
    c=Catalog();rows,unknown=c.parse((Path(__file__).parents[1]/'tests/fixtures/forge_cube.csv').read_text(encoding='utf-8-sig'));assert not unknown
    spec=BuildSpec();seeds,guilds=schedule(200,771342);present={r['name'] for r in rows};items=[]
    for i,row in enumerate(rows):
        if row['role']!='Main':continue
        old=c.cards[row['name']]
        for n,new in c.cards.items():
            if n not in present and new['identity']==old['identity'] and new['bucket']==old['bucket'] and new['kind']==old['kind'] and (new['mv']>=6)==(old['mv']>=6):
                trial=copy.deepcopy(rows);trial[i]['name']=n;items.append(dict(index=i,rows=trial,remove=old['name'],add=n));break
        if len(items)==8:break
    out=Path(__file__).parents[1]/'private/benchmarks'/('search_'+time.strftime('%Y%m%d_%H%M%S'));out.mkdir(parents=True)
    report=dict(pods=len(seeds),candidates=len(items),phases={},strength_claim=False)
    def save():
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    def run(label,fn):
        start=time.perf_counter();r=fn();seconds=time.perf_counter()-start
        report['phases'][label]=dict(seconds=seconds);print(label,round(seconds,3),flush=True);return r
    serial=run('serial_full',lambda:[draft_evaluation(c,item['rows'],spec,seeds,guilds) for item in items]);save()
    workspace=DraftWorkspace(c,spec)
    draft_evaluation(c,rows,spec,seeds,guilds,workspace=workspace)
    incremental=run('incremental_full',lambda:[draft_evaluation(c,item['rows'],spec,seeds,guilds,workspace=workspace) for item in items]);save()
    semantic=lambda r:{k:v for k,v in r.items() if k!='execution'}
    report['incremental_exact']=all(semantic(a)==semantic(b) for a,b in zip(serial,incremental))
    report['incremental_reused_tables']=sum(r['execution']['cache_hits'] for r in incremental)
    with CandidateEvaluator(c,spec,seeds,guilds,workers=2) as evaluator:
        parallel=run('parallel_full_cold',lambda:evaluator.batch(items,len(seeds)))
        report['parallel_exact']=all(semantic(a)==semantic(b) for a,b in zip(serial,parallel));report['fallback']=evaluator.fallback
    with CandidateEvaluator(c,spec,seeds,guilds,workers=2) as evaluator:
        surviving,rejected=run('adaptive_parallel_cold',lambda:evaluator.screen(copy.deepcopy(items),rows,lambda m:print(m,flush=True)))
        report['search']=evaluator.stats
    best=max(objective(r) for r in serial);selected=max(objective(item['evaluation']) for item in surviving)
    report['screening']=dict(best_full_objective=best,best_surviving_objective=selected,missed_best=selected<best-1e-10,
        note='只描述这批固定候选；分轮筛选可能遗漏其他好方案，最终仍需独立实战验收。')
    save();print(json.dumps(dict(path=str(out),exact=report['incremental_exact'] and report['parallel_exact'],screening=report['screening']),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
