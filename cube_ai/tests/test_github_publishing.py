import hashlib
import zipfile

import pytest

from cube_ai.tools import publish_github_history as publisher


def archive(tmp_path,entries):
    path=tmp_path/'portable.zip'
    with zipfile.ZipFile(path,'w') as z:
        for name,data in entries.items():z.writestr('Cube助手/'+name,data)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix('.zip.sha256.txt').write_text(digest+'  portable.zip\n')
    return path


def test_public_vendor_example_is_not_workspace_data(monkeypatch,tmp_path):
    monkeypatch.setattr(publisher,'SOURCE',tmp_path/'project')
    monkeypatch.setattr(publisher,'run',lambda *a:'private@example.test')
    needles=publisher.private_needles()
    assert publisher.scan_data(b'# public example: D:/mtg-pics',needles) is None
    assert publisher.scan_data(str(tmp_path/'project/private/account').encode(),needles)=='personal_path_or_email'
    assert publisher.scan_data(b'private@example.test',needles)=='personal_path_or_email'


def test_private_state_and_real_looking_token_block_upload(tmp_path,monkeypatch):
    monkeypatch.setattr(publisher,'STATE',tmp_path/'state')
    path=archive(tmp_path,{'cube_ai/private/ai-settings.bin':b'opaque',
                          'cube_ai/leak.py':b'KEY="sk-'+b'A'*32+b'"'})
    with pytest.raises(ValueError,match='Archive privacy scan failed') as error:
        publisher.scan_archive(path,())
    assert 'A'*32 not in str(error.value)
    assert 'private_state' in str(error.value)


def test_binary_symbol_false_positive_ignored_but_private_paths_checked(tmp_path,monkeypatch):
    monkeypatch.setattr(publisher,'STATE',tmp_path/'state')
    path=archive(tmp_path,{'cube_ai/runtime/java/lib/modules':b'public_binary_symbol_sk-'+b'A'*32})
    assert publisher.scan_archive(path,())['private_findings']==0
    with pytest.raises(ValueError,match='personal_path_or_email'):
        publisher.scan_archive(path,(b'public_binary_symbol',))


def test_archive_checksum_and_traversal_are_checked(tmp_path):
    path=archive(tmp_path,{'cube_ai/safe.py':b'pass'})
    path.with_suffix('.zip.sha256.txt').write_text('0'*64+' portable.zip')
    with pytest.raises(ValueError,match='checksum'):publisher.scan_archive(path,())
    path=archive(tmp_path,{'../outside.py':b'pass'})
    with pytest.raises(ValueError,match='Unsafe ZIP path'):publisher.scan_archive(path,())


def test_source_export_excludes_runtime_card_database_and_state():
    for name in ['cube_ai/forge.py','cube_ai/web/app.js','cube_ai/data/learning_sources.json','magic-skill/LICENSE']:
        assert publisher.source_member(name)
    for name in ['cube_ai/runtime/java.exe','cube_ai/data/card_pool.json','cube_ai/data/preferences.sqlite',
                 'cube_ai/private/ai-settings.bin','cube_ai/.env']:
        assert not publisher.source_member(name)
    assert publisher.tag('20261015-r7')=='v2026.10.15-r7'
