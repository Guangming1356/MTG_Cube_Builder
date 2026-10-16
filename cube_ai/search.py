"""Development-only successive screening; final adoption always uses full seeds."""
import math
import multiprocessing
import os
import statistics
from concurrent.futures import ProcessPoolExecutor

_state=None


def _initialize(spec_data,seeds,guilds,learned):
    global _state
    from types import SimpleNamespace
    from .config import BuildSpec
    from .sim_cache import DraftWorkspace
    # Evaluation only reads cards in the candidate rows. Loading all 31k Oracle
    # records in every spawned process wastes memory and startup I/O.
    catalog=SimpleNamespace(cards={});spec=BuildSpec.from_dict(spec_data)
    _state=(catalog,spec,seeds,guilds,learned,DraftWorkspace(catalog,spec))


def _evaluate(payload):
    from .optimize import draft_evaluation
    rows,count,additions=payload;catalog,spec,seeds,guilds,learned,workspace=_state
    catalog.cards.update(additions)
    return draft_evaluation(catalog,rows,spec,seeds[:count],guilds[:count],learned=learned,workspace=workspace)


def stages(count):
    # Every prefix >=10 tables covers each of the ten guilds equally.
    return sorted({min(count,10),min(count,30),count})


def screening_window(report,baseline):
    """A conservative heuristic tolerance, NOT a confidence interval for objective.

    The objective includes nonlinear tails/guild gaps. Whole-table mean fluctuation
    only widens an engineering safety margin; it cannot certify significance.
    """
    base={(m['pod'],m['seat']):m['strength'] for m in baseline['observations']}
    by_pod={}
    for m in report['observations']:
        by_pod.setdefault(m['pod'],[]).append(m['strength']-base[(m['pod'],m['seat'])])
    differences=[statistics.mean(values) for values in by_pod.values()]
    return max(.0005,2*statistics.stdev(differences)/math.sqrt(len(differences))) if len(differences)>1 else 1.


class CandidateEvaluator:
    def __init__(self,catalog,spec,seeds,guilds,learned=None,workers=None,adaptive=True):
        from .sim_cache import DraftWorkspace
        self.catalog=catalog;self.spec=spec;self.seeds=seeds;self.guilds=guilds;self.learned=learned
        from .experiment import memory_available
        available=memory_available()
        limit=max(1,min(4,(os.cpu_count() or 1)//2,int((available/2**30-3)//.75) if available else 1))
        if workers is not None and (type(workers)!=int or not 1<=workers<=4):raise ValueError('候选评估进程数需为 1–4')
        self.workers=min(limit,workers) if workers is not None else limit
        self.workspace=DraftWorkspace(catalog,spec);self.pool=None;self.fallback=None;self.use_full=False
        self._worker_names=None
        self.stats=dict(proposals=0,full_evaluations=0,table_evaluations=0,full_table_budget=0,
            reused_tables=0,redrafted_tables=0,uncertain_batches=0,stage_runs=[],stages=stages(len(seeds)) if adaptive else [len(seeds)],workers=self.workers)

    def __enter__(self):return self

    def __exit__(self,*args):
        self.close()

    def close(self):
        if self.pool:
            for executor in self.pool:executor.shutdown(wait=True,cancel_futures=True)
            self.pool=None;self._worker_names=None

    def evaluate(self,rows,count):
        from .optimize import draft_evaluation
        return draft_evaluation(self.catalog,rows,self.spec,self.seeds[:count],self.guilds[:count],learned=self.learned,workspace=self.workspace)

    def batch(self,items,count):
        if self.workers>1 and len(items)>1 and not self.fallback:
            try:
                if self.pool is None:
                    self.pool=[ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn'),
                        initializer=_initialize,initargs=(self.spec.to_dict(),self.seeds,self.guilds,self.learned)) for _ in range(self.workers)]
                    self._worker_names=[set() for _ in self.pool]
                # Stable affinity preserves each candidate's workspace across rounds.
                # Result order remains the input order regardless of completion order.
                futures=[]
                for item in items:
                    slot=sum(item['add'].encode('utf8'))%self.workers
                    missing={row['name'] for row in item['rows']}-self._worker_names[slot]
                    additions={name:self.catalog.cards[name] for name in missing}
                    futures.append(self.pool[slot].submit(_evaluate,(item['rows'],count,additions)))
                    self._worker_names[slot].update(missing)
                return [future.result() for future in futures]
            except (OSError,RuntimeError) as error:
                self.fallback=type(error).__name__+': '+str(error)
                self.close()
        return [self.evaluate(item['rows'],count) for item in items]

    def screen(self,items,base_rows,progress=lambda x:None):
        from .optimize import objective
        survivors=list(items);rejected=[];self.stats['proposals']+=len(items)
        self.stats['full_table_budget']+=len(items)*len(self.seeds)
        skip_intermediate=False
        for count in ([len(self.seeds)] if self.use_full else self.stats['stages']):
            if skip_intermediate and count!=len(self.seeds):continue
            progress(f'并行筛选 {len(survivors)} 个替换：每个 {count} 桌开发轮抓')
            self.stats['stage_runs'].append(dict(pods=count,candidates=len(survivors)))
            baseline=self.evaluate(base_rows,count)
            reports=self.batch(survivors,count);self.stats['table_evaluations']+=count*len(survivors)
            self.stats['reused_tables']+=sum(r['execution']['cache_hits'] for r in reports)
            self.stats['redrafted_tables']+=sum(r['execution']['cache_misses'] for r in reports)
            for item,report in zip(survivors,reports):
                item['evaluation']=report;item['development_delta']=objective(report)-objective(baseline)
                item['screening_window']=screening_window(report,baseline)
            if count==len(self.seeds):
                self.stats['full_evaluations']+=len(survivors);break
            # Screening is an approximate search choice, never a strength claim.
            survivors.sort(key=lambda item:(-item['development_delta'],item['index'],item['add']))
            keep=max(1,math.ceil(len(survivors)/2))
            best_lower=survivors[0]['development_delta']-survivors[0]['screening_window']
            promoted=[item for rank,item in enumerate(survivors) if rank<keep or item['development_delta']+item['screening_window']>=best_lower]
            for item in survivors:
                if any(item is p for p in promoted):continue
                rejected.append(dict(remove=item['remove'],add=item['add'],stage_pods=count,
                    development_delta=item['development_delta'],accepted=False,status='screened_out'))
            survivors=promoted
            if len(promoted)>=len(items)*.75:
                # Weak early separation makes more screening counterproductive.
                # Complete this batch and switch subsequent batches to full mode.
                skip_intermediate=True;self.use_full=True;self.stats['uncertain_batches']+=1
        return survivors,rejected
