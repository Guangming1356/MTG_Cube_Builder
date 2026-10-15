"""Moving the assistant must preserve its bundled inputs and native runtime."""
import json
from pathlib import Path
import pytest

from cube_ai import forge, forge_setup
from cube_ai.config import WORKSPACE, LIBRARY, card_pool_path
from cube_ai.server import Application


def test_relative_runtime_paths_and_chinese_java_profile(tmp_path, monkeypatch):
    runtime = tmp_path / 'Cube助手' / 'runtime'
    home = runtime / 'forge-test'
    home.mkdir(parents=True)
    (home / 'forge.jar').touch()
    (home / '.installed').touch()
    (home / 'forge.profile.properties').write_text('userDir=old/location\n',encoding='ascii')
    (runtime / 'java.exe').touch()
    (runtime / 'forge.json').write_text(json.dumps(dict(
        home='forge-test', jar='forge-test/forge.jar', java='java.exe', version='test')))
    monkeypatch.setattr(forge, 'RUNTIME', runtime)
    monkeypatch.setattr(forge_setup, 'RUNTIME', runtime)
    monkeypatch.delenv('CUBE_FORGE_HOME', raising=False)
    monkeypatch.delenv('CUBE_FORGE_JAVA', raising=False)
    config = forge.configuration()
    assert Path(config['jar']) == home / 'forge.jar'
    assert Path(config['java']) == runtime / 'java.exe'
    assert 'old/location' not in (home / 'forge.profile.properties').read_text(encoding='ascii')
    forge_setup.write_profile(home)
    profile = (home / 'forge.profile.properties').read_text(encoding='ascii')
    decoded = profile.encode('ascii').decode('unicode_escape')
    assert f'userDir={(runtime / "userdata").as_posix()}' in decoded
    assert f'cacheDir={(runtime / "cache").as_posix()}' in decoded


@pytest.mark.parametrize('bundled_library',[True,False])
def test_standalone_library_and_pool(tmp_path,monkeypatch,bundled_library):
    assert card_pool_path().resolve().is_relative_to(WORKSPACE)
    import cube_ai.server as server
    workspace=tmp_path/'独立工作目录'
    library=workspace/'牌表资料'
    examples=library if bundled_library else workspace
    example=examples/'commander_cube_600_fixture'/'cube_600.csv'
    example.parent.mkdir(parents=True)
    fixture=(Path(__file__).parent/'fixtures/forge_cube.csv').read_bytes()
    example.write_bytes(fixture)
    (workspace/'ref_thecommandercube.csv').write_bytes(fixture)
    monkeypatch.setattr(server,'WORKSPACE',workspace)
    monkeypatch.setattr(server,'LIBRARY',library)
    app = Application()
    try:
        expected = {p.parent.name for p in examples.glob('commander_cube_600*/cube_600.csv')}
        assert expected and expected <= app.examples.keys()
        assert 'reference_commandercube' in app.examples
        assert all(p.resolve().is_relative_to(workspace) for p in app.examples.values())
    finally:
        app.executor.shutdown()
