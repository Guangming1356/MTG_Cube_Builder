import argparse
import json
from pathlib import Path
from .config import BuildSpec

def main():
    parser=argparse.ArgumentParser(description="Cube Atelier — 专用 Cube 构筑工作台")
    parser.add_argument("command",choices=["serve","build","analyze","repair","stress","train","evaluate","forge-setup","forge-status","forge-test","forge-optimize"])
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--spec",type=Path)
    parser.add_argument("--file",type=Path)
    parser.add_argument("--trials",type=int,default=100)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--pods",type=int,default=10)
    parser.add_argument("--games-per-pod",type=int,default=3)
    parser.add_argument("--clock",type=int,default=90)
    parser.add_argument("--workers",type=int,default=0,help='同时对局数；0 为自动，最多8')
    parser.add_argument("--training-pods",type=int,default=None)
    parser.add_argument("--profile",choices=['quick','standard','deep'],default='standard')
    parser.add_argument("--max-swaps",type=int,default=None)
    args=parser.parse_args()
    if args.command=="serve":
        from .server import serve
        return serve(args.port)
    if args.command=='forge-setup':
        from .forge_setup import install
        result=install(progress=lambda m:print(m,flush=True))
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if args.command=='forge-status':
        from .forge import status
        print(json.dumps(status(),ensure_ascii=False,indent=2));return
    if args.command=="evaluate":
        from .evaluate import offline_benchmark
        result=offline_benchmark()
    else:
        from .catalog import Catalog
        from .engine import audit,build,export_run
        from .draft import stress_test
        from .feedback import FeedbackStore
        catalog=Catalog();spec=BuildSpec.from_dict(json.loads(args.spec.read_text(encoding="utf-8")) if args.spec else None)
        rows=[];unknown=[]
        if args.file:rows,unknown=catalog.parse(args.file.read_text(encoding="utf-8-sig"))
        if spec.mode=='classic':
            for row in rows:
                if row['role']=='Commander':row['role']='Main'
        if args.command=="build":result=export_run(catalog,build(catalog,spec,progress=lambda m:print(m,flush=True)))
        elif args.command=="analyze":result=audit(catalog,rows,spec,unknown,strict=True)
        elif args.command=="repair":
            if unknown:parser.error("请先修正未知卡名: "+", ".join(unknown))
            if not rows:parser.error("repair 需要 --file")
            result=export_run(catalog,build(catalog,spec,rows,progress=lambda m:print(m,flush=True)))
        elif args.command=="stress":
            if unknown or not rows:parser.error("stress 需要合法、已确认的 --file")
            result=stress_test(catalog,rows,spec,args.trials,progress=lambda m:print(m,flush=True))
        elif args.command=='forge-test':
            from .forge import simulate
            if unknown or not rows:parser.error('forge-test 需要合法、已确认的 --file')
            result=simulate(catalog,rows,spec,args.pods,args.games_per_pod,args.clock,progress=lambda m:print(m,flush=True),workers=args.workers)
        elif args.command=='forge-optimize':
            from .optimize import optimize
            if unknown or not rows:parser.error('forge-optimize 需要合法、已确认的 --file')
            result=optimize(catalog,rows,spec,progress=lambda m:print(m,flush=True),workers=args.workers,clock=args.clock,
                training_pods=args.training_pods,profile=args.profile,max_swaps=args.max_swaps)
        else:
            store=FeedbackStore();result=store.train(catalog,store.context(spec))
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:args.output.write_text(text,encoding="utf-8")
    else:print(text)

if __name__=="__main__":main()
