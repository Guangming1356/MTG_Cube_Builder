"""Windows acceptance check for a fresh extracted portable release, without AI.

Always test a separate extraction, never repackage the used verification folder.
"""
import argparse
import ast
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request


def request(url,data=None):
    encoded=json.dumps(data).encode() if data is not None else None
    value=urllib.request.Request(url,encoded,{'Content-Type':'application/json'} if encoded is not None else {})
    with urllib.request.urlopen(value,timeout=15) as response:return json.load(response)


def wait_until(probe,timeout=90):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            if value:=probe():return value
        except (OSError,ValueError):pass
        time.sleep(.2)
    raise TimeoutError('便携版验收等待超时')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--fixture',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();root=args.root.resolve();python=root/'运行环境/python/python.exe'
    launch=root/'启动Cube助手.exe';url=None
    def start():
        subprocess.run([str(launch),'--no-browser'],cwd=root,check=True,capture_output=True,timeout=90)
        connection=json.loads((root/'cube_ai/runtime/entrance.json').read_text(encoding='utf8'))
        address=connection['url'];wait_until(lambda:request(address+'api/health'));return address
    try:
        url=start();status=request(url+'api/status')
        expected=next(ast.literal_eval(n.value) for n in ast.parse((root/'cube_ai/__init__.py').read_text(encoding='utf-8-sig')).body
                      if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__version__' for t in n.targets))
        assert status['version']==expected and status.get('workspace_id')
        assert not status['gpt']['configured'] and status['forge']['available']
        assert status['feedback']['comparisons']==0 and status['feedback']['model'] is None
        assert status['feedback']['model_compatible'] is False and status['feedback']['model_reason']=='not_trained'
        assert status['features']['feedback_scope'] is True
        assert request(url+'api/feedback/status?context=legacy%3Aclassic')['comparisons']==0
        for asset in ['workspace.js','tasks-ui.js','deck-study-ui.js','style.css']:
            with urllib.request.urlopen(url+asset,timeout=10) as response:assert response.status==200
        names_code='''import json,sys
from cube_ai.catalog import Catalog
from cube_ai.forge import configuration,card_index,engine_name,parse_log,verified_game_result
from cube_ai.forge_card_names import name_pairs,trace_name_pairs,ASSET,bundle_alias_asset
from cube_ai.cube_family import pool_counts,group_cubes
from cube_ai.surrogate import split_groups,VERSION as ACTIVITY_VERSION
from cube_ai.tuning import canonical_attackers,canonical_blockers,baseline_check
from cube_ai.config import BuildSpec
from cube_ai.mana import requires_colorless_mana,commander_basic_sources
assert not any(n=='scipy' or n.startswith('scipy.') for n in sys.modules)
c=Catalog();pairs=name_pairs();index=card_index(configuration())
assert ACTIVITY_VERSION=='activity-6'
assert not BuildSpec().allow_colorless_costs
assert requires_colorless_mana(c.cards['Warping Wail'])
assert requires_colorless_mana(c.cards['Eldrazi Displacer'])
assert not requires_colorless_mana(c.cards['Mind Stone'])
assert commander_basic_sources(c,[],[],dict(B=23),'Grist, Voracious Larva // Grist, the Plague Swarm')==dict(B=22,G=1)
pool=pool_counts([dict(name='Plains',role='Land')])
families,_=group_cubes(dict(a=pool,b=pool))
assert families['a']==families['b']
labels,method=split_groups(['ga','gb'],['a','b'],['one','one'])
assert method=='insufficient_cube_families' and set(labels)=={'train'}
attack='Combat: Ai(1)-a assigned Goblin (1) and Elf (2) to attack Ai(2)-b.'
swapped='Combat: Ai(1)-a assigned Elf (2) and Goblin (1) to attack Ai(2)-b.'
assert canonical_attackers(attack)==canonical_attackers(swapped)
assert canonical_attackers(attack)!=canonical_attackers(swapped.replace('(2)','(3)',1))
block="Ai(1)-a assigned Elf (1) to block Bear (2)."
unblocked="Ai(1)-a didn't block Goblin (3)."
assert canonical_blockers('Combat: '+block+unblocked)==canonical_blockers('Combat: '+unblocked+block)
assert canonical_blockers('Combat: '+block+unblocked)!=canonical_blockers('Combat: '+block.replace('(1)','(4)')+unblocked)
control=dict(workers=1,jvm_profile='default',same_native_backend=True,runs=[
    [dict(outcome='win',winner='a',events_sha256='first')],
    [dict(outcome='win',winner='a',events_sha256='changed')]])
assert baseline_check(control)['status']=='unstable'
winner='Game Result: Game 1 ended in 10 ms. Ai(1)-a has won!'
for header in ('java.util.concurrent.TimeoutException','java.lang.OutOfMemoryError'):
    assert parse_log(header+'\\r\\n'+winner)['outcome']=='engine_error'
    assert verified_game_result(header+'\\n'+winner,dict(outcome='win',winner='a'),['a']) is None
assert len(pairs)==182 and len(trace_name_pairs())==189
assert all(engine_name(requested,index)==requested for requested,native in pairs)
assert c.resolve('Chief Jim Hopper')=='Sophina, Spearsage Deserter'
assert c.resolve('Dustin, Gadget Genius')=='Hargilde, Kindly Runechanter'
bundle_alias_asset(ASSET)
print(json.dumps(dict(front_aliases=len(pairs),trace_names=len(trace_name_pairs()),native_index_verified=True,catalog_aliases_verified=True)))
'''
        names=json.loads(subprocess.check_output([str(python),'-X','utf8','-c',names_code],cwd=root,text=True,encoding='utf8',timeout=90))
        build_job=request(url+'api/tasks',dict(operation='build',cards=[],spec=dict(bracket=3,seed=654,name='便携版构筑验收')))['job_id']
        built=wait_until(lambda:(j if (j:=request(url+'api/job?id='+build_job))['state'] in {'done','failed'} else None))
        assert built['state']=='done',built.get('error')
        assert len(built['result']['cards'])==600 and built['result']['audit']['hard_errors']==0
        assert built['result']['spec']['allow_colorless_costs'] is False
        card_check="import json,sys;from cube_ai.catalog import Catalog;from cube_ai.mana import requires_colorless_mana;c=Catalog();rows=json.loads(sys.stdin.read());assert not any(requires_colorless_mana(c.cards[r['name']]) for r in rows);assert not any(r['role']=='Commander' and c.cards[r['name']]['identity']=='C' for r in rows)"
        subprocess.run([str(python),'-X','utf8','-c',card_check],input=json.dumps(built['result']['cards']),cwd=root,text=True,encoding='utf8',check=True,capture_output=True,timeout=90)
        code="from pathlib import Path;import json,sys;from cube_ai.catalog import Catalog;from cube_ai.config import BuildSpec;c=Catalog();rows,unknown=c.parse(Path(sys.argv[1]).read_text(encoding='utf-8-sig'));assert not unknown;print(json.dumps(dict(operation='stress',cards=rows,spec=BuildSpec().to_dict(),trials=5)))"
        prepared=subprocess.check_output([str(python),'-X','utf8','-c',code,str(args.fixture.resolve())],cwd=root,text=True,encoding='utf8',timeout=90)
        job=request(url+'api/tasks',json.loads(prepared))['job_id']
        request(url+'api/task/control',dict(id=job,action='pause'))
        wait_until(lambda:(j if (j:=request(url+'api/job?id='+job))['state']=='paused' else None))
        try:request(url+'api/shutdown',{})
        except urllib.error.HTTPError as error:assert error.code==400
        else:raise AssertionError('Paused work must block shutdown')
        request(url+'api/task/control',dict(id=job,action='resume'))
        result=wait_until(lambda:(j if (j:=request(url+'api/job?id='+job))['state'] in {'done','failed'} else None))
        assert result['state']=='done',result.get('error')
        assert result['result']['trials']==5 and result['result']['drafted_pool_sizes']=={'60':15}
        request(url+'api/shutdown',{});time.sleep(1);url=start()
        restored=request(url+'api/job?id='+job)
        assert restored['state']=='done' and restored['result']==result['result']
        report=dict(passed=True,application_version=expected,cards=status['cards'],offline_ai=True,forge_available=True,
                    embedded_runtime=True,task_pause_resume=True,shutdown_blocks_live_tasks=True,restart_recovers_result=True,
                    native_name_compatibility=names,clean_preference_state=True,preference_scope_validation=True,
                    native_evidence_validation=True,cube_family_validation=True,native_event_comparison_validation=True,
                    lazy_solver_import=True,full_cube_generation=True,calibration_reference_validation=True,blocker_display_validation=True,
                    colorless_preference_validation=True,commander_mana_validation=True)
        args.out.write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report),flush=True)
    finally:
        if url:
            try:request(url+'api/shutdown',{})
            except (OSError,ValueError):
                subprocess.run([str(root/'关闭Cube助手.exe'),'--no-browser'],cwd=root,capture_output=True,timeout=30)


if __name__=='__main__':main()
