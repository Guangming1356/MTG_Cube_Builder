"""Paired full-catalog vs incremental worker benchmark; no AI calls or game labels.

Run with the project's Python from any working directory. Reports contain only
fixture fingerprints, timing, memory and equivalence, not account information.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))


def full_catalog_initializer(spec_data,seeds,guilds,learned):
    """The previous worker loading strategy, with the same current evaluation."""
    from cube_ai import search
    from cube_ai.catalog import Catalog
    from cube_ai.config import BuildSpec
    from cube_ai.sim_cache import DraftWorkspace
    catalog=Catalog();spec=BuildSpec.from_dict(spec_data)
    search._state=(catalog,spec,seeds,guilds,learned,DraftWorkspace(catalog,spec))


def main():
    from cube_ai import search
    from cube_ai.catalog import Catalog
    from cube_ai.config import BuildSpec,ROOT
    from cube_ai.optimize import schedule
    from cube_ai.resources import process_memory
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pods',type=int,default=40)
    parser.add_argument('--workers',type=int,choices=[2,3,4],default=2)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    if not 10<=args.pods<=1000:parser.error('--pods must be between 10 and 1000')
    catalog=Catalog();fixture=ROOT/'tests/fixtures/forge_cube.csv'
    rows,unknown=catalog.parse(fixture.read_text(encoding='utf-8-sig'));assert not unknown
    spec=BuildSpec.from_dict({'bracket':3});seeds,guilds=schedule(args.pods,784152)
    present={r['name'] for r in rows};items=[]
    for index,row in enumerate(rows):
        old=catalog.cards[row['name']]
        if row['role']!='Main':continue
        new=next((c for c in catalog.cards.values() if c['name'] not in present and c['identity']==old['identity'] and c['kind']==old['kind'] and c['bucket']==old['bucket']),None)
        if not new:continue
        trial=copy.deepcopy(rows);trial[index]['name']=new['name']
        items.append(dict(rows=trial,add=new['name']))
        if len(items)>=6 and len({sum(x['add'].encode())%args.workers for x in items})==args.workers:break
    report=dict(pods=args.pods,candidates=len(items),workers=args.workers,
                fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),phases=[],strength_claim=False)
    output=args.out or ROOT/'private/benchmarks'/('hotpaths_'+time.strftime('%Y%m%d_%H%M%S')+'.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    initializer=search._initialize;expected=None
    try:
        for label in ['full_catalog','incremental','incremental','full_catalog']:
            search._initialize=full_catalog_initializer if label=='full_catalog' else initializer
            start=time.perf_counter()
            with search.CandidateEvaluator(catalog,spec,seeds,guilds,workers=args.workers) as evaluator:
                results=evaluator.batch(items,len(seeds));seconds=time.perf_counter()-start
                if evaluator.fallback:raise RuntimeError(evaluator.fallback)
                semantic=[{k:v for k,v in result.items() if k!='execution'} for result in results]
                fingerprint=hashlib.sha256(json.dumps(semantic,sort_keys=True).encode()).hexdigest()
                if expected is None:expected=fingerprint
                assert fingerprint==expected,'Parallel evaluation changed results'
                # Private executor state is used only by this diagnostic, never
                # by scheduling, termination or the application's resource policy.
                memory=[process_memory(pid) for pool in evaluator.pool for pid in pool._processes]
                phase=dict(strategy=label,seconds=seconds,equivalent=True,worker_memory=memory,
                           private_bytes=sum(m['private_bytes'] for m in memory if m),
                           working_set_bytes=sum(m['working_set'] for m in memory if m))
                report['phases'].append(phase);print(json.dumps(phase),flush=True)
            output.write_text(json.dumps(report,indent=2),encoding='utf8')
    finally:search._initialize=initializer
    report['summary']={label:{key:statistics.median(p[key] for p in report['phases'] if p['strategy']==label)
                              for key in ['seconds','private_bytes','working_set_bytes']} for label in ['full_catalog','incremental']}
    output.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(dict(report=str(output),summary=report['summary'])),flush=True)


if __name__=='__main__':main()
