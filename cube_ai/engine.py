import csv
import hashlib
import io
import json
import math
import random
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from .catalog import exclusion_reasons
from .config import GUILDS, TRIPLES, RUNS, WORKSPACE
from .features import COMBOS, VERSION
from .feedback import FeedbackStore
from .design import VERSION as DESIGN_VERSION, design_bonus, cube_design_report, studies
from .brackets import profile, is_gc, score_adjustment, cube_report, VERSION as BRACKET_VERSION

def apportion(total, weights):
    if total == 0: return {k:0 for k in weights}
    units = {k: total*v/sum(weights.values()) for k,v in weights.items()}
    result = {k:int(v) for k,v in units.items()}
    order = sorted(weights, key=lambda k: (-(units[k]-result[k]), k))
    for k in order[:total-sum(result.values())]: result[k] += 1
    return result

def quotas(spec):
    main = spec.size - spec.lands - spec.commanders
    if main < 40: raise ValueError("至少需要 40 个主牌槽位")
    groups = {c:59 for c in "WUBRG"}
    groups.update({g:9 for g in GUILDS});groups["C"] = 55
    cmds = {c:8 for c in "WUBRG"};cmds.update({g:4 for g in GUILDS});cmds.update({g:1 for g in TRIPLES})
    curve = spec.curve or apportion(main, {"1":54,"2":156,"3":94,"4":61,"5+":75})
    if set(curve) != {"1","2","3","4","5+"} or sum(curve.values()) != main:
        raise ValueError("curve 必须包含 1、2、3、4、5+，且合计等于主牌张数")
    return apportion(main,groups), apportion(spec.commanders,cmds), curve

def completes_combo(names):
    s = set(names)
    return [combo for combo in COMBOS if set(combo) <= s]

class ConstraintSet:
    def __init__(self, candidates):
        self.cards=candidates;self.rows=[];self.low=[];self.high=[];self.labels=[]
    def add(self, label, coefficients, lo=-np.inf, hi=np.inf):
        row = {i:float(v) for i,v in enumerate(coefficients) if v}
        if not row and (lo > 0 or hi < 0):
            raise ValueError(f"候选牌无法满足: {label}")
        self.rows.append(row);self.low.append(lo);self.high.append(hi);self.labels.append(label)
    def solve(self, scores):
        rowidx=[];colidx=[];values=[]
        for r,row in enumerate(self.rows):
            for col,val in row.items():rowidx.append(r);colidx.append(col);values.append(val)
        a=coo_matrix((values,(rowidx,colidx)),shape=(len(self.rows),len(self.cards))).tocsc()
        result=milp(-np.array(scores),integrality=np.ones(len(self.cards)),
                    bounds=Bounds(0,1),constraints=LinearConstraint(a,self.low,self.high),
                    options={"time_limit":35,"mip_rel_gap":.025})
        if result.x is None:
            raise ValueError("这些约束在候选池中无可行解。请检查锁定牌、系列/价格过滤或自定义曲线；程序没有静默放宽约束。")
        x=np.rint(result.x)
        vals=a@x
        bad=[self.labels[i] for i,v in enumerate(vals) if v < self.low[i]-1e-6 or v > self.high[i]+1e-6]
        if bad: raise ValueError("求解结果不满足约束: " + ", ".join(bad))
        return [self.cards[i] for i,v in enumerate(x) if v], dict(status=int(result.status),
            proven_optimal=result.status==0 and float(getattr(result,"mip_gap",0) or 0)<1e-8, gap=float(getattr(result,"mip_gap",0) or 0),
            candidates=len(self.cards), constraints=len(self.rows))

def theme_fit(card, themes):
    return len(set(card["enablers"]+card["payoffs"]) & set(themes))

def build(catalog, spec, previous=None, progress=lambda x:None, store=None):
    spec.validate()
    power=profile(spec)
    start=time.monotonic();progress("检索合法牌并解析依赖")
    main_targets,cmd_targets,curve=quotas(spec)
    store=store or FeedbackStore();learned,model=store.scorer(spec)
    pins=[]
    for name in spec.pins:
        n=catalog.resolve(name)
        if not n: raise ValueError(f"锁定牌不存在于牌库: {name}")
        if n in pins: raise ValueError(f"重复锁定牌: {n}")
        reasons=exclusion_reasons(catalog.cards[n],spec)
        if reasons: raise ValueError(f"锁定牌 {n} 与约束冲突: {'; '.join(reasons)}")
        pins.append(n)
    if not spec.allow_infinite_combos and completes_combo(pins):
        raise ValueError("锁定牌包含已知无限组合")
    if power and sum(is_gc(catalog.cards[n]) for n in pins)>power['gc_limit']:
        raise ValueError("锁定牌超过 Cube Game Changer 数量预算")
    eligible=[c for c in catalog.cards.values() if not exclusion_reasons(c,spec)]
    preferred={r["name"] for r in previous or []}
    def score(c, role="Main"):
        themes=spec.pair_themes.get(c["identity"], [])
        synergy=.1*min(3,theme_fit(c,themes))
        bonus=2.0 if c["name"] in preferred else 0
        return c["quality"] + synergy + learned(c) + design_bonus(c,spec) + bonus + score_adjustment(c,spec,role)

    selected=[];seen=set(); remaining_pins=set(pins)
    def gc_room(c,chosen=()):
        reserved=seen | remaining_pins | {c['name']} | {x['name'] for x in chosen}
        return not power or sum(is_gc(catalog.cards[n]) for n in reserved)<=power['gc_limit']
    progress("分配各色组指挥官和修色地")
    for group,amount in cmd_targets.items():
        if not amount: continue
        pool=[c for c in eligible if c["commander"] and c["kind"]!="land" and c["identity"]==group and (not power or c['quality']<=power['commander_ceiling'])]
        pool.sort(key=lambda c:(c["name"] not in remaining_pins,-score(c,'Commander')-.08*c["draw"]-.06*len(c["payoffs"]),c["name"]))
        chosen=[]
        for c in pool:
            if not gc_room(c,chosen):continue
            if not spec.allow_infinite_combos and completes_combo(seen|{c["name"]}): continue
            chosen.append(c)
            if len(chosen)==amount: break
        if len(chosen)<amount:raise ValueError(f"{group} 缺少合规且独立可用的指挥官，需 {amount} 位")
        for c in chosen:
            selected.append({"name":c["name"],"role":"Commander"});seen.add(c["name"]);remaining_pins.discard(c["name"])
    land_pool=[c for c in eligible if c["kind"]=="land"]
    preferred_lands=[]
    source=WORKSPACE/"cube_generator/edh_600_v4.json"
    if source.exists():preferred_lands=json.loads(source.read_text(encoding="utf-8"))["lands"]
    def land_score(c):
        return (100-len(preferred_lands[:preferred_lands.index(c["name"])])) if c["name"] in preferred_lands else 10+c["quality"]
    land_pool.sort(key=lambda c:(-land_score(c),c["name"]))
    land_chosen=[c for c in land_pool if c["name"] in remaining_pins]
    if len(land_chosen)>spec.lands: raise ValueError("锁定地牌超过地牌配额")
    pair_counts=Counter("".join(sorted(set(c["fixing"]) & set("WUBRG"))) for c in land_chosen)
    pair_goal=min(spec.lands,round(spec.lands*.72))
    while len(land_chosen)<pair_goal:
        options=[c for c in land_pool if c not in land_chosen and len(set(c["fixing"]) & set("WUBRG"))==2 and (not power or sum(is_gc(x) for x in land_chosen)+sum(is_gc(catalog.cards[n]) for n in seen|remaining_pins if catalog.cards[n]['kind']!='land')+int(is_gc(c))<=power['gc_limit'])]
        if not options:break
        c=min(options,key=lambda c:(pair_counts["".join(sorted(c["fixing"]))],-land_score(c)))
        land_chosen.append(c);pair_counts["".join(sorted(c["fixing"]))]+=1
    for c in land_pool:
        if len(land_chosen)>=spec.lands:break
        if c not in land_chosen and (not power or sum(is_gc(x) for x in land_chosen)+sum(is_gc(catalog.cards[n]) for n in seen|remaining_pins if catalog.cards[n]['kind']!='land')+int(is_gc(c))<=power['gc_limit']):land_chosen.append(c)
    if len(land_chosen)!=spec.lands:raise ValueError("合规地牌数量不足")
    for c in land_chosen:
        selected.append({"name":c["name"],"role":"Land"});seen.add(c["name"]);remaining_pins.discard(c["name"])
    if not spec.allow_infinite_combos and completes_combo(seen):raise ValueError("所选指挥官包含已知组合，请排除组合中的一张牌")

    progress("求解颜色、曲线、互动、扫场、终结和协同约束")
    candidates=[]
    for group,amount in main_targets.items():
        if not amount:continue
        pool=[c for c in eligible if c["kind"]!="land" and c["identity"]==group and c["name"] not in seen]
        pool.sort(key=lambda c:(c["name"] not in remaining_pins,-score(c),c["name"]))
        top={c["name"]:c for c in pool[:max(160,amount*4)]}
        for bucket in curve:
            for c in [c for c in pool if c["bucket"]==bucket][:max(18,amount//2)]:top[c["name"]]=c
        for c in pool:
            if c["name"] in remaining_pins:top[c["name"]]=c
        candidates.extend(top.values())
    absent=remaining_pins-{c["name"] for c in candidates}
    if absent:raise ValueError("锁定牌没有可用槽位: "+", ".join(absent))
    cons=ConstraintSet(candidates);nmain=sum(main_targets.values())
    if power:
        cons.add('项目主牌平均评价区间',[c['quality'] for c in candidates],nmain*power['mean'][0],nmain*power['mean'][1])
        cons.add('项目高评价主牌预算',[c['quality']>=4.0 for c in candidates],hi=power['top_limit'])
        cons.add('项目 Cube Game Changer 预算',[is_gc(c) for c in candidates],hi=power['gc_limit']-sum(is_gc(catalog.cards[n]) for n in seen))
    for group,amount in main_targets.items():
        cons.add(f"{group} 主牌配额",[c["identity"]==group for c in candidates],amount,amount)
    for bucket,amount in curve.items():
        cons.add(f"{bucket} 费曲线",[c["bucket"]==bucket for c in candidates],amount,amount)
    for name in remaining_pins:
        cons.add("锁定 "+name,[c["name"]==name for c in candidates],1,1)
    minima={"creature":math.ceil(nmain*.42),"interaction":math.ceil(nmain*.18),"wipe":max(2,math.ceil(nmain*.035)),
            "ramp":math.ceil(nmain*.065),"draw":math.ceil(nmain*.12),"finisher":math.ceil(nmain*.085)}
    for feature,count in minima.items():cons.add(feature+" 最低密度",[c[feature] for c in candidates],count)
    cons.add("加速上限",[c["ramp"] for c in candidates],hi=math.ceil(nmain*.15))
    cons.add("互动上限",[c["interaction"] for c in candidates],hi=math.ceil(nmain*.30))
    cons.add("抓牌引擎上限",[c["draw"] for c in candidates],hi=math.ceil(nmain*.45))
    cons.add("生物上限",[c["creature"] for c in candidates],hi=math.ceil(nmain*.62))
    cons.add("6费以上保底",[c["mv"]>=6 for c in candidates],math.ceil(nmain*.09))
    for group in "WUBRG":
        amount=main_targets[group]
        cons.add(group+" 低中费密度",[c["identity"]==group and c["mv"]<=3 for c in candidates],math.floor(amount*.57))
        cons.add(group+" 互动",[c["identity"]==group and c["interaction"] for c in candidates],max(2,math.floor(amount*.10)))
        cons.add(group+" 后期手段",[c["identity"]==group and c["finisher"] for c in candidates],max(1,math.floor(amount*.05)))
        cons.add(group+" 加速上限",[c["identity"]==group and c["ramp"] for c in candidates],hi=math.ceil(amount*.25))
    for a in "WUBRG":
        for b in "WUBRG":
            if a>=b:continue
            coeff=[c["quality"]*(int(c["identity"]==a)/main_targets[a]-int(c["identity"]==b)/main_targets[b]) for c in candidates]
            cons.add(a+b+" 单色平均评价差",coeff,-.32,.32)
    for g in GUILDS:
        amount=main_targets[g]
        if not amount:continue
        cons.add(g+" 多色牌最低评价",[c["quality"] if c["identity"]==g else 0 for c in candidates],amount*(power['gold_floor'] if power else 3.05))
        accessible=lambda c:set(c["identity"])<=set(g) or c["identity"]=="C"
        cons.add(g+" 可用互动",[accessible(c) and c["interaction"] for c in candidates],max(4,round(nmain*.035)))
        for theme in spec.pair_themes.get(g,[]):
            cons.add(g+" "+theme+" 支持",[accessible(c) and theme in c["enablers"] for c in candidates],max(2,round(nmain*.015)))
            # Not all themes need dedicated payoffs (draw/control are already roles).
            if theme not in {"control","draw"}:
                cons.add(g+" "+theme+" 回报",[accessible(c) and theme in c["payoffs"] for c in candidates],max(1,round(nmain*.005)))
    for i,a in enumerate(GUILDS):
        for b in GUILDS[i+1:]:
            if not main_targets[a] or not main_targets[b]:continue
            coeff=[c["quality"]*(int(c["identity"]==a)/main_targets[a]-int(c["identity"]==b)/main_targets[b]) for c in candidates]
            cons.add(a+"/"+b+" 多色平均评价差",coeff,-.32,.32)
    if not spec.allow_infinite_combos:
        for combo in COMBOS:
            fixed=len(set(combo)&seen)
            cons.add("禁止组合: "+" + ".join(combo),[c["name"] in combo for c in candidates],hi=len(combo)-1-fixed)
    rng=random.Random(spec.seed)
    chosen,solver=cons.solve([score(c)+rng.random()*.008 for c in candidates])
    selected.extend({"name":c["name"],"role":"Main"} for c in chosen)
    selected.sort(key=lambda r:(r["role"],catalog.cards[r["name"]]["identity"],catalog.cards[r["name"]]["mv"],r["name"]))
    report=audit(catalog,selected,spec,strict=True)
    errors=[i for i in report["issues"] if i["severity"]=="error"]
    if errors:raise ValueError("结果验证失败: "+"; ".join(i["message"] for i in errors))
    old={r["name"] for r in previous or []};new={r["name"] for r in selected}
    progress("独立审计和导出文件")
    result=dict(spec=spec.to_dict(),cards=selected,audit=report,solver=solver,
                changes={"removed":sorted(old-new),"added":sorted(new-old)} if previous else None,
                provenance={"snapshot":catalog.snapshot,"catalog":catalog.signature,"features":VERSION,
                            "design":DESIGN_VERSION,"studies":studies()['version'],
                            "brackets":BRACKET_VERSION if power else None,
                            "feedback_model":model and model["model_id"],"seed":spec.seed,
                            "engine":"scipy-milp + Oracle ontology","seconds":round(time.monotonic()-start,2)})
    return result

def audit(catalog,rows,spec,unresolved=None,strict=False):
    power=profile(spec)
    issues=[];names=[r["name"] for r in rows]
    def issue(severity,code,message,cards=None):issues.append(dict(severity=severity,code=code,message=message,cards=cards or []))
    if unresolved:issue("error","unknown","有无法确认的牌名，未猜测补全",unresolved)
    if len(rows)!=spec.size:issue("error","size",f"牌表 {len(rows)} 张，目标 {spec.size} 张")
    duplicates=[n for n,v in Counter(names).items() if v>1]
    if duplicates:issue("error","duplicate","单卡唯一性不满足",duplicates)
    cards=[];roles=Counter();main=[];colors=Counter()
    for r in rows:
        c=catalog.cards.get(r["name"])
        if c is None:issue("error","unknown",r["name"]);continue
        cards.append(c);roles[r["role"]]+=1
        errors=exclusion_reasons(c,spec)
        if errors:issue("error","excluded",c["name"]+": "+"; ".join(errors),[c["name"]])
        if r["role"]=="Commander" and not c["commander"]:issue("error","commander",c["name"]+" 不能作为指挥官",[c["name"]])
        if r["role"]=="Land" and c["kind"]!="land":issue("error","land_role",c["name"]+" 并非正面地牌",[c["name"]])
        if r["role"]!="Land" and c["kind"]=="land":issue("error","land_role",c["name"]+" 正面地牌应在地槽位",[c["name"]])
        if r["role"]=="Main":main.append(c);colors[c["identity"]]+=1
    expected={"Commander":spec.commanders,"Land":spec.lands,"Main":spec.size-spec.commanders-spec.lands}
    for role,count in expected.items():
        if roles[role]!=count:issue("error","roles",f"{role} {roles[role]} 张，目标 {count} 张")
    if not spec.allow_infinite_combos:
        for combo in completes_combo(names):issue("error","combo","已知无限组合: "+" + ".join(combo),combo)
    curve=Counter(c["bucket"] for c in main)
    role_counts={key:sum(c[key] for c in main) for key in ["creature","interaction","wipe","ramp","draw","finisher"]}
    bracket=cube_report(catalog,rows,spec)
    if bracket:
        for message in bracket['violations']:issue('error','bracket_budget',message)
    if strict:
        main_targets,cmd_targets,curve_targets=quotas(spec)
        cmd_colors=Counter(catalog.cards[r['name']]['identity'] for r in rows if r['role']=='Commander' and r['name'] in catalog.cards)
        for g,count in cmd_targets.items():
            if cmd_colors[g]!=count:issue('error','commander_coverage',f'{g} 指挥官 {cmd_colors[g]}，目标 {count}')
        for g,count in main_targets.items():
            if colors[g]!=count:issue("error","color_quota",f"{g} 主牌 {colors[g]}，配额 {count}")
        for bucket,count in curve_targets.items():
            if curve[bucket]!=count:issue("error","curve_quota",f"{bucket} 费 {curve[bucket]}，目标 {count}")
        for key,ratio in {"creature":.42,"interaction":.18,"wipe":.035,"ramp":.065,"draw":.12,"finisher":.085}.items():
            if role_counts[key]<math.ceil(len(main)*ratio):issue("error","density",key+" 未达到最低密度")
        if role_counts["ramp"]>math.ceil(len(main)*.15):issue("error","ramp_cap","加速超过上限")
        if role_counts["interaction"]>math.ceil(len(main)*.30):issue("error","interaction_cap","互动超过上限")
        if role_counts["draw"]>math.ceil(len(main)*.45):issue("error","draw_cap","抓牌超过上限")
        if role_counts['creature']>math.ceil(len(main)*.62):issue('error','creature_cap','生物超过上限')
        if sum(c['mv']>=6 for c in main)<math.ceil(len(main)*.09):issue('error','late_density','6 费以上密度不足')
        for g in 'WUBRG':
            own=[c for c in main if c['identity']==g];amount=main_targets[g]
            if sum(c['mv']<=3 for c in own)<math.floor(amount*.57):issue('error','mono_curve',g+' 低中费不足')
            if sum(c['interaction'] for c in own)<max(2,math.floor(amount*.10)):issue('error','mono_interaction',g+' 互动不足')
            if sum(c['finisher'] for c in own)<max(1,math.floor(amount*.05)):issue('error','mono_finisher',g+' 后期手段不足')
            if sum(c['ramp'] for c in own)>math.ceil(amount*.25):issue('error','mono_ramp',g+' 加速超过上限')
    pairs={};mean={}
    for g in [*"WUBRG",*GUILDS,"C"]:
        own=[c for c in main if c["identity"]==g]
        mean[g]=round(sum(c["quality"] for c in own)/max(1,len(own)),3)
    for g in GUILDS:
        accessible=[c for c in main if c["identity"]=="C" or set(c["identity"])<=set(g)]
        support={}
        for theme in spec.pair_themes.get(g,[]):
            en=[c["name"] for c in accessible if theme in c["enablers"]]
            pa=[c["name"] for c in accessible if theme in c["payoffs"]]
            support[theme]=dict(enablers=len(en),payoffs=len(pa),examples=(en[:3]+pa[:3]))
            if pa and len(en)<3:issue("warning","unsupported",f"{g} 的 {theme} 回报缺少支持",pa[:6])
        pairs[g]=dict(main_cards=len(accessible),interaction=sum(c["interaction"] for c in accessible),
                      wipes=sum(c["wipe"] for c in accessible),finishers=sum(c["finisher"] for c in accessible),themes=support)
        if strict and main_targets[g]:
            floor=power['gold_floor'] if power else 3.05
            if mean[g]<floor-.001:issue('error','guild_quality',g+f' 多色牌平均启发式评价不足 {floor}')
            if pairs[g]['interaction']<max(4,round(len(main)*.035)):issue('error','guild_interaction',g+' 可用互动不足')
            for theme,counts in support.items():
                if counts['enablers']<max(2,round(len(main)*.015)):issue('error','theme_supply',g+' '+theme+' 支持不足')
                if theme not in {'control','draw'} and counts['payoffs']<max(1,round(len(main)*.005)):issue('error','theme_payoffs',g+' '+theme+' 回报不足')
    if main:
        if role_counts["interaction"]<len(main)*.18:issue("warning","interaction","互动密度低于 18%")
        if role_counts["wipe"]<len(main)*.035:issue("warning","wipes","扫场密度偏低")
        if role_counts["finisher"]<len(main)*.085:issue("warning","finishers","终结手段密度偏低")
        if role_counts["ramp"]>math.ceil(len(main)*.15):issue("warning","ramp","加速密度过高，可能挤压互动和威胁")
        active=[mean[g] for g in "WUBRG" if colors[g]]
        if active and max(active)-min(active)>.321:issue('error' if strict else 'warning',"color_quality","单色平均启发式评价差超过 0.32")
        guild_mean=[mean[g] for g in GUILDS if colors[g]]
        if guild_mean and max(guild_mean)-min(guild_mean)>.321:issue('error' if strict else 'warning',"guild_quality","多色色组平均启发式评价差超过 0.32")
    fixing=Counter()
    for r in rows:
        c=catalog.cards.get(r["name"])
        if c and r["role"]=="Land":
            for color in set(c["fixing"]) & set("WUBRG"):fixing[color]+=1
    if spec.lands and fixing:
        values=[fixing[c] for c in "WUBRG"]
        if max(values)-min(values)>4:issue("warning","fixing","各色修色地来源差超过 4")
    return dict(total=len(rows),roles=dict(roles),main_colors=dict(colors),curve=dict(curve),
        role_counts=role_counts,quality_by_group=mean,pairs=pairs,fixing=dict(fixing),
        eligible_commanders=sum(c["commander"] for c in cards),issues=issues,
        hard_errors=sum(i["severity"]=="error" for i in issues),snapshot=catalog.snapshot,
        design=cube_design_report(catalog,rows,spec),bracket=bracket,
        limitation="牌力和协同由启发式规则估算，不是实战胜率；部族和组合识别不保证穷尽")

def export_run(catalog,result):
    RUNS.mkdir(exist_ok=True)
    payload=json.dumps(result,ensure_ascii=False,sort_keys=True)
    digest=hashlib.sha256(payload.encode()).hexdigest()[:8]
    run_id=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")+"_"+digest
    folder=RUNS/run_id;folder.mkdir()
    (folder/"cube.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    (folder/"cubecobra.txt").write_text("\n".join("1 "+r["name"] for r in result["cards"])+"\n",encoding="utf-8")
    with (folder/"cube.csv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f);w.writerow(["name","role","mana_value","identity","heuristic_quality","tags"])
        for r in result["cards"]:
            c=catalog.cards[r["name"]];w.writerow([c["name"],r["role"],c["mv"],c["identity"],c["quality"],"Commander" if r["role"]=="Commander" else ",".join(c["enablers"])])
    (folder/"spec.json").write_text(json.dumps(result["spec"],ensure_ascii=False,indent=2),encoding="utf-8")
    a=result["audit"]
    lines=[f"# {result['spec']['name']}","",f"张数 {a['total']}；结构 {a['roles']}；硬性错误 {a['hard_errors']}。",
           "",f"牌库快照：{a['snapshot']}。所有牌力值是启发式评价，不是真实胜率。","",
           "## 主牌曲线","",str(a["curve"]),"","## 角色密度","",str(a["role_counts"]),"","## 审计发现",""]
    lines.extend(f"- [{i['severity']}] {i['message']}" for i in a["issues"])
    if a.get('bracket'):
        b=a['bracket'];lines.extend(['','## Commander Bracket 构筑目标','',f"目标 {b['target']}：{b['name']}；核验 {b['reviewed']}；策略 {b['version']}。",
            f"项目主牌平均评价 {b['main_mean']}，区间 {b['project_mean_band']}；高评价主牌 {b['high_quality_main']}/{b['project_high_quality_limit']}。",
            f"Cube Game Changers {len(b['game_changers'])}/{b['cube_gc_limit']}；实际每副牌的官方上限：{b['official_deck_gc_limit'] if b['official_deck_gc_limit'] is not None else '不限'}（含指挥官与地）。",
            b['limitation'],'','官方来源：',*['- '+url for url in b['sources']]])
    if not a["issues"]:lines.append("未发现当前检查器覆盖的约束问题。")
    if 'design' in a:
        d=a['design'];lines.extend(['','## 有来源的设计检查','',
            f"策略 {d['version']}；资料 {d['study_version']}；同玩法参考牌 {d['reference_count']} 张。",'',d['limitation'],''])
        for g,packages in d['guild_packages'].items():
            for name,p in packages.items():
                if p['active']:lines.append(f"- {g} {name}: "+' / '.join(f"{v['label']} {v['count']}" for v in p['components'].values())+f"；{p['status']}")
    (folder/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    result["run_id"]=run_id
    return result
