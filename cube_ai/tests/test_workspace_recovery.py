from pathlib import Path
import shutil
import subprocess

import pytest


def test_delayed_workspace_recovery_preserves_user_navigation_and_new_cube():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is only needed for this developer browser-state regression')
    script=Path(__file__).parent/'js/test_workspace_recovery.cjs'
    result=subprocess.run([node,str(script)],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
    assert '"passed":4' in result.stdout


def test_workspace_preserves_unsaved_controls_and_partial_recipe_edits():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed for the browser-state regression')
    script=Path(__file__).parent/'js/test_workspace_drafts.cjs'
    result=subprocess.run([node,str(script)],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
    assert '"passed":10' in result.stdout


def test_stress_report_distinguishes_missing_observations_from_zero_success():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed for the browser rendering regression')
    script=Path(__file__).parent/'js/test_stress_rendering.cjs'
    result=subprocess.run([node,str(script)],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
    assert '"passed":2' in result.stdout
