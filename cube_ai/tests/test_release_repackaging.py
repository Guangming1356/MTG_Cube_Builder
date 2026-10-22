import json
from pathlib import Path
import zipfile

import pytest

from cube_ai.tools.repackage_release import repackage,sha


def test_name_manifest_is_required_and_pinned_when_module_is_shipped(tmp_path):
    from cube_ai.tools.repackage_release import overlay_files
    from cube_ai.forge_card_names import ASSET
    app=tmp_path/'cube_ai';app.mkdir();(app/'forge_card_names.py').write_bytes(b'# module')
    with pytest.raises(FileNotFoundError):overlay_files(tmp_path)
    (app/'data').mkdir();target=app/'data/forge_name_aliases.json';target.write_bytes(ASSET.read_bytes())
    assert overlay_files(tmp_path)['cube_ai/data/forge_name_aliases.json']==ASSET.read_bytes()
    target.write_bytes(ASSET.read_bytes()+b' ')
    with pytest.raises(ValueError,match='modified'):overlay_files(tmp_path)


@pytest.fixture
def source(tmp_path):
    root=tmp_path/'source';(root/'cube_ai/web').mkdir(parents=True)
    (root/'cube_ai/__init__.py').write_text('__version__ = "0.2.0"\n',encoding='utf8')
    (root/'cube_ai/web/workspace.js').write_text('console.log("new UI");',encoding='utf8')
    (root/'cube_ai/private').mkdir();(root/'cube_ai/private/credentials').write_text('MUST NOT SHIP')
    (root/'cube_ai/tools').mkdir();(root/'cube_ai/tools/dev-only.py').write_text('MUST NOT SHIP')
    return root


def base_zip(tmp_path,extra=None):
    path=tmp_path/'base.zip'
    files={'启动Cube助手.exe':b'launcher-original','关闭Cube助手.exe':b'close-original','启动.pyw':b'# original bootstrap',
           '发布说明.json':json.dumps({'python':'3.13.16','sources':[{'sha256':'original-license-source'}]}).encode(),
           'cube_ai/__init__.py':b'__version__ = "0.1.0"','cube_ai/runtime/engine.jar':b'EXACT ENGINE BYTES',
           '运行环境/python/python.exe':b'EXACT PYTHON BYTES','第三方来源/source.tar.gz':b'EXACT SOURCE ARCHIVE'}
    files.update(extra or {})
    with zipfile.ZipFile(path,'w') as archive:
        for name,data in files.items():archive.writestr('Cube助手/'+name,data)
    return path


def test_portable_overlay_preserves_runtimes_and_sources_but_excludes_user_data(tmp_path,source):
    base=base_zip(tmp_path);out=tmp_path/'out'
    record=repackage(base,source,out,'20261016',sha(base),'source-commit')
    with zipfile.ZipFile(out/record['asset']) as archive:
        assert archive.read('Cube助手/cube_ai/runtime/engine.jar')==b'EXACT ENGINE BYTES'
        assert archive.read('Cube助手/第三方来源/source.tar.gz')==b'EXACT SOURCE ARCHIVE'
        assert archive.read('Cube助手/启动Cube助手.exe')==b'launcher-original'
        assert archive.read('Cube助手/cube_ai/__init__.py')==(source/'cube_ai/__init__.py').read_bytes()
        assert 'Cube助手/cube_ai/web/workspace.js' in archive.namelist()
        assert not any('/private/' in name or '/tools/' in name for name in archive.namelist())
    assert record['application_version']=='0.2.0' and record['tag']=='v2026.10.16'
    assert (out/'SHA256SUMS.txt').read_text().startswith(sha(out/record['asset']))


def test_repackaging_requires_verified_base_and_never_overwrites_version(tmp_path,source):
    base=base_zip(tmp_path)
    with pytest.raises(ValueError,match='SHA256'):repackage(base,source,tmp_path/'out','20261016','0'*64)
    repackage(base,source,tmp_path/'out','20261016',sha(base))
    with pytest.raises(FileExistsError):repackage(base,source,tmp_path/'out','20261016',sha(base))


@pytest.mark.parametrize('danger',['../outside','cube_ai/private/account.json','cube_ai/data/preferences.sqlite'])
def test_repackaging_rejects_unsafe_or_personal_base_entries(tmp_path,source,danger):
    base=base_zip(tmp_path,{danger:b'bad'})
    with pytest.raises(ValueError):repackage(base,source,tmp_path/'out','20261016',sha(base))


def test_changed_native_bridge_cannot_reuse_old_compiled_classes(tmp_path,source):
    base=base_zip(tmp_path,{'cube_ai/native/CubeWorker.java':b'old'})
    native=source/'cube_ai/native';native.mkdir();(native/'CubeWorker.java').write_text('changed')
    with pytest.raises(ValueError,match='Java'):repackage(base,source,tmp_path/'out','20261016',sha(base))


def test_overlay_with_credentials_or_new_dependencies_is_not_packaged(tmp_path,source):
    base=base_zip(tmp_path,{'cube_ai/requirements.txt':b'requests==1\n'})
    (source/'cube_ai/requirements.txt').write_text('requests==2\n')
    with pytest.raises(ValueError,match='运行依赖'):repackage(base,source,tmp_path/'out','20261016',sha(base))
    (source/'cube_ai/requirements.txt').write_text('requests==1\n')
    (source/'cube_ai/private_leak.py').write_text('key = "'+'sk-proj-'+'A'*40+'"')
    with pytest.raises(ValueError,match='凭据'):repackage(base,source,tmp_path/'out','20261016',sha(base))
    (source/'cube_ai/private_leak.py').write_text('location="C:/Users/example-private/AppData"')
    with pytest.raises(ValueError,match='本机路径'):repackage(base,source,tmp_path/'out','20261016',sha(base))


def test_missing_full_build_inputs_fail_before_creating_partial_runtime_copies(tmp_path,monkeypatch):
    from cube_ai.tools import build_portable
    releases=tmp_path/'releases'
    monkeypatch.setattr(build_portable,'RELEASES',releases)
    monkeypatch.setattr(build_portable,'CACHE',releases/'cache')
    with pytest.raises(ValueError,match='未创建构建目录'):build_portable.stage()
    assert not releases.exists()


@pytest.mark.parametrize('pattern',[b'D:/MTG',b'C:/Users/32860'.decode().encode('utf-16-le'),b'ghp_'+b'A'*40])
def test_full_build_privacy_scan_detects_patterns_crossing_buffer_boundaries(tmp_path,pattern):
    from cube_ai.tools.build_portable import privacy_scan
    (tmp_path/'example.txt').write_bytes(b'x'*(1024*1024-3)+pattern+b'x'*512)
    with pytest.raises(ValueError,match='隐私扫描失败'):privacy_scan(tmp_path)


def test_full_build_privacy_scan_has_bounded_memory_for_large_runtime_files(tmp_path):
    import tracemalloc
    from cube_ai.tools.build_portable import privacy_scan
    with (tmp_path/'runtime.bin').open('wb') as stream:
        for _ in range(16):stream.write(b'x'*(1024*1024))
    tracemalloc.start()
    try:
        assert privacy_scan(tmp_path)['files']==1
        _,peak=tracemalloc.get_traced_memory()
    finally:tracemalloc.stop()
    assert peak<5*1024*1024
