"""Transparent system evaluations. Offline popularity is NOT a generic GPT baseline."""
import argparse
import json
import random
import time
from collections import Counter
from pathlib import Path
from .catalog import Catalog, exclusion_reasons
from .config import BuildSpec, GUILDS, ROOT
from .draft import stress_test
from .engine import audit, build, export_run, quotas
from .features import VERSION

def metrics(catalog,rows,spec,unknown=None):
    a=audit(catalog,rows,spec,unknown,strict=True)
    main,_,curve=quotas(spec)
    mono=[a['quality_by_group'][g] for g in 'WUBRG']
    pair=[a['quality_by_group'][g] for g in GUILDS]
    return dict(hard_errors=a['hard_errors'],issues_by_code=dict(Counter(i['code'] for i in a['issues'])),
        curve_l1=sum(abs(a['curve'].get(k,0)-v) for k,v in curve.items()),
        color_l1=sum(abs(a['main_colors'].get(k,0)-v) for k,v in main.items()),
        mono_heuristic_gap=round(max(mono)-min(mono),3),guild_heuristic_gap=round(max(pair)-min(pair),3),
        roles=a['role_counts'],unknown_names=len(unknown or []))

def popularity_baseline(catalog,spec,specialized):
    # Hold commander and fixing slots constant, so the comparison isolates main selection.
    rows=[dict(r) for r in specialized if r['role']!='Main'];used={r['name'] for r in rows}
    targets,_,_=quotas(spec)
    for group,amount in targets.items():
        pool=[c for c in catalog.cards.values() if c['identity']==group and c['kind']!='land'
              and c['name'] not in used and not exclusion_reasons(c,spec)]
        pool.sort(key=lambda c:(c['rank'] or 100000,c['name']))
        if len(pool)<amount:raise ValueError('流行度基线候选不足')
        rows.extend(dict(name=c['name'],role='Main') for c in pool[:amount]);used.update(c['name'] for c in pool[:amount])
    return rows

def offline_benchmark():
    catalog=Catalog();cases=[]
    specs=[BuildSpec(),BuildSpec.from_dict(dict(mode='classic',seed=43))]
    for spec in specs:
        print('评测 '+spec.mode,flush=True)
        specialized=export_run(catalog,build(catalog,spec))
        base=popularity_baseline(catalog,spec,specialized['cards'])
        stress=stress_test(catalog,specialized['cards'],spec,100)
        from .config import RUNS
        (RUNS/specialized['run_id']/'stress.json').write_text(json.dumps(stress,ensure_ascii=False,indent=2),encoding='utf-8')
        cases.append(dict(spec=spec.to_dict(),run_id=specialized['run_id'],
            specialized=metrics(catalog,specialized['cards'],spec),popularity=metrics(catalog,base,spec),
            draft={k:stress[k] for k in ['trials','players','drafted_pool_sizes','buildable_rate','guilds']},
            solver=specialized['solver']))
    controls={}
    for name in ['Black Lotus','Lotus Petal','Chrome Mox','Elvish Warmaster','Coat of Arms','Armageddon']:
        n=catalog.resolve(name);controls[name]=dict(blocked=n is None or bool(exclusion_reasons(catalog.cards[n],specs[0])),
            reason='absent: unknown pins are rejected' if n is None else exclusion_reasons(catalog.cards[n],specs[0]))
    return dict(version=VERSION,snapshot=catalog.snapshot,catalog=catalog.signature,cases=cases,
        negative_controls=controls,generic_gpt_comparison='NOT RUN: requires an API key and separate live evaluation',
        limitation='流行度排序是弱基线，不能证明优于通用 GPT。曲线/数量由同一规则验收；牌力标签不是独立实战真值。草拟组牌不是对局模拟。')

def parse_model_cube(catalog,response,style):
    if response.get('status') in {'incomplete','failed'}:raise ValueError('模型输出不完整')
    if style=='responses':
        text=''.join(c.get('text','') for x in response.get('output',[]) for c in x.get('content',[]) if c.get('type')=='output_text')
    else:
        choice=response.get('choices',[{}])[0]
        if choice.get('finish_reason')=='length':raise ValueError('模型输出截断')
        text=choice.get('message',{}).get('content','')
    data=json.loads(text);rows=[];unknown=[]
    for r in data['cards']:
        n=catalog.resolve(r['name'])
        if not n:unknown.append(r['name']);continue
        rows.append(dict(name=n,role=r['role']))
    return rows,unknown

def live_comparison(spec,output):
    """Two equal model-call budgets; compare full specialized system vs generic one-call drafting.
    No automatic declaration of winner; blinded human review sheet is emitted.
    """
    from .llm import LLMClient, SYSTEM
    from .knowledge import Knowledge
    client=LLMClient()
    if not client.key:raise ValueError('live 评测需要 OPENAI_API_KEY；会调用模型两次并产生 API 费用')
    catalog=Catalog();knowledge=Knowledge();base=build(catalog,spec)
    # Both arms see the SAME Oracle catalog. Start from valid slots and add alternatives.
    names={r['name'] for r in base['cards']}
    for g in ['W','U','B','R','G',*GUILDS,'C']:
        extra=[c for c in catalog.cards.values() if c['identity']==g and not exclusion_reasons(c,spec) and c['name'] not in names]
        extra.sort(key=lambda c:(-c['quality'],c['name']));names.update(c['name'] for c in extra[:15])
    candidates=[dict(name=n,text=catalog.cards[n]['text'],identity=catalog.cards[n]['identity'],
                     mana_value=catalog.cards[n]['mv'],commander=catalog.cards[n]['commander'],kind=catalog.cards[n]['kind']) for n in sorted(names)]
    main,cmds,curve=quotas(spec)
    common=dict(request='按这些要求构筑可轮抓、可互动、有终结手段、色组均衡的 Cube，避免无法支持的部族或孤立回报。',
                spec=spec.to_dict(),slot_quotas=dict(main=main,commanders=cmds,curve=curve),cards=candidates)
    schema={'type':'object','properties':{'cards':{'type':'array','items':{'type':'object','properties':{
        'name':{'type':'string'},'role':{'type':'string','enum':['Commander','Main','Land']}},'required':['name','role'],'additionalProperties':False}}},
        'required':['cards'],'additionalProperties':False}
    arms={};order=['generic','specialized'];random.Random(spec.seed).shuffle(order)
    for arm in order:
        system='You are a helpful assistant. Build a Magic: The Gathering cube that meets the provided requirements.'
        if arm=='specialized':system=SYSTEM+'\n领域知识：'+json.dumps(knowledge.search('cube curve synergy finishers commander',4),ensure_ascii=False)
        started=time.monotonic()
        response=client.request([{'role':'system','content':system},{'role':'user','content':json.dumps(common,ensure_ascii=False)}],schema=schema,max_tokens=16000)
        rows,unknown=parse_model_cube(catalog,response,client.style)
        pre=metrics(catalog,rows,spec,unknown);repair=None
        if arm=='specialized':
            repair=build(catalog,spec,previous=rows);final=repair['cards'];final_unknown=[]
        else:final=rows;final_unknown=unknown
        outside=[r['name'] for r in rows if r['name'] not in names]
        arms[arm]=dict(model_raw_cards=rows,unknown=unknown,outside_supplied_candidates=outside,
            raw_metrics=pre,final_cards=final,final_metrics=metrics(catalog,final,spec,final_unknown),
            usage=response.get('usage',{}),seconds=round(time.monotonic()-started,2),solver=repair and repair['solver'])
    output.mkdir(parents=True,exist_ok=True)
    report=dict(model=client.model,style=client.style,spec=spec.to_dict(),snapshot=catalog.snapshot,catalog=catalog.signature,
                features=VERSION,llm_calls_per_arm=1,max_output_tokens_per_arm=16000,candidate_count=len(candidates),arms=arms,
                limitation='比较的是专用系统（知识+约束修复）和通用一次调用系统，不是基础模型智力。专用系统额外消耗求解器计算；启发式评价非独立真值。请重复种子并做盲评/真实游玩。')
    (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'input.json').write_text(json.dumps(common,ensure_ascii=False,indent=2),encoding='utf-8')
    mapping=dict(zip(['A','B'],order))
    for label,arm in mapping.items():
        (output/f'blind_{label}.txt').write_text('\n'.join(r['name'] for r in arms[arm]['final_cards']),encoding='utf-8')
    (output/'blind_mapping.json').write_text(json.dumps(mapping),encoding='utf-8')
    (output/'human_review.md').write_text('# 盲评记录\n\n先不要打开 blind_mapping.json。让玩家对 A、B 分别评估：\n\n- 单卡质量、低费行动、终结、互动各 1–5 分\n- 孤立回报与不受支持的牌，列具体卡名\n- 十个色组的游玩体验，记录多桌真实对局\n- 偏好 A / B / 无明显差异，附原因\n\n重复至少三个种子；统计样本和不确定性，不以单次结果宣布优于所有通用 AI。\n',encoding='utf-8')
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--spec',type=Path);p.add_argument('--output',type=Path,default=ROOT/'evaluation')
    a=p.parse_args()
    if a.live:
        spec=BuildSpec.from_dict(json.loads(a.spec.read_text(encoding='utf-8')) if a.spec else None)
        result=live_comparison(spec,a.output)
    else:
        result=offline_benchmark();a.output.mkdir(parents=True,exist_ok=True)
        (a.output/'offline.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='arms'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
