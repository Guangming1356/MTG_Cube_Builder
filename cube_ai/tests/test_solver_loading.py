"""Public boundaries for the deferred solver and shared land/commander budget."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_server_audit_import_without_scipy_and_first_solve():
    code = '''
import importlib.abc,sys
class BlockSolver(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='scipy' or fullname.startswith('scipy.'):
            raise AssertionError('Importing the server must not load the solver')
guard=BlockSolver();sys.meta_path.insert(0,guard)
from cube_ai import server
from cube_ai.engine import ConstraintSet
assert not any(n=='scipy' or n.startswith('scipy.') for n in sys.modules)
sys.meta_path.remove(guard)
choices=ConstraintSet([{'name':'first'},{'name':'second'}])
choices.add('exactly one',[1,1],1,1)
selected,info=choices.solve([.1,.2])
assert selected==[{'name':'second'}] and info['status']==0
assert 'scipy.optimize' in sys.modules
'''
    env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    result=subprocess.run([sys.executable,'-X','utf8','-c',code],cwd=Path(__file__).resolve().parents[2],
                          env=env,capture_output=True,text=True,encoding='utf8',timeout=60,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('pins',[
    ['Rhystic Study','Field of the Dead'],
    ['Rhystic Study','Field of the Dead','Grand Arbiter Augustin IV'],
])
def test_pinned_gc_budget_shared_by_main_land_and_commander(pins,tmp_path):
    from cube_ai.catalog import Catalog
    from cube_ai.config import BuildSpec
    from cube_ai.engine import build,audit
    from cube_ai.feedback import FeedbackStore
    from cube_ai.brackets import is_gc
    catalog=Catalog()
    spec=BuildSpec.from_dict(dict(bracket=3,cube_gc_limit=len(pins),pins=pins,seed=2003))
    output=build(catalog,spec,store=FeedbackStore(tmp_path/'prefs.db'))
    assert audit(catalog,output['cards'],spec,strict=True)['hard_errors']==0
    strong=[row for row in output['cards'] if is_gc(catalog.cards[row['name']])]
    assert {r['name'] for r in strong}==set(pins)
    roles={r['name']:r['role'] for r in strong}
    assert roles['Rhystic Study']=='Main' and roles['Field of the Dead']=='Land'
    if 'Grand Arbiter Augustin IV' in pins:assert roles['Grand Arbiter Augustin IV']=='Commander'
