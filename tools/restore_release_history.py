"""One-time exact reconstruction of approved, sanitized historical packages.

Runs only on manual workflow dispatch. The base, input bundle, each delta and
each reconstructed archive are verified. No user secrets or AI services used.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile


def run(args,timeout=300):
    result=subprocess.run(args,capture_output=True,text=True,encoding='utf8',timeout=timeout)
    if result.returncode:raise RuntimeError(result.stderr[-2000:])
    return result.stdout.strip()


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def release(repo,tag):
    pages=json.loads(run(['gh','api',f'repos/{repo}/releases?per_page=100','--paginate','--slurp']))
    return next(r for page in pages for r in page if r['tag_name']==tag)


def main():
    repo=os.environ['GH_REPO'];expected_bundle=os.environ['RESTORE_INPUT_SHA256']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('Repository name invalid')
    if json.loads(run(['gh','api',f'repos/{repo}']))['private'] is not True:raise ValueError('Repository must remain private')
    base_tag='v2026.10.15-r7';bundle_name='cloud-restore-inputs.tar.gz'
    with tempfile.TemporaryDirectory(prefix='cube-release-') as folder:
        folder=Path(folder)
        run(['gh','release','download',base_tag,'--repo',repo,'--pattern',bundle_name,'--dir',str(folder)])
        bundle=folder/bundle_name
        if sha(bundle)!=expected_bundle:raise ValueError('Restore inputs checksum mismatch')
        with tarfile.open(bundle,'r:gz') as tar:
            for entry in tar.getmembers():
                if not entry.isfile() or '/' in entry.name or '\\' in entry.name or entry.name in {'.','..'}:
                    raise ValueError('Unsafe restoration input')
                with tar.extractfile(entry) as stream:(folder/entry.name).write_bytes(stream.read())
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf8'))
        if manifest['repository']!=repo or manifest['base']['tag']!=base_tag:raise ValueError('Manifest repository mismatch')
        base=manifest['base'];base_path=folder/base['asset']
        run(['gh','release','download',base_tag,'--repo',repo,'--pattern',base['asset'],'--dir',str(folder)])
        if sha(base_path)!=base['sha256']:raise ValueError('Base package checksum mismatch')
        verified=[]
        for item in manifest['releases']:
            if not re.fullmatch(r'MTG_Cube_Builder-Windows-x64-\d{8}(?:-r\d+)?\.zip',item['asset']):
                raise ValueError('Unexpected asset filename')
            patch=folder/item['patch']
            if patch.parent!=folder or sha(patch)!=item['patch_sha256']:raise ValueError('Delta checksum mismatch')
            current=release(repo,item['tag'])
            existing=next((a for a in current['assets'] if a['name']==item['asset']),None)
            if not existing or existing.get('digest')!='sha256:'+item['sha256'] or existing['size']!=item['bytes']:
                output=folder/item['asset']
                run(['zstd','-d','--patch-from='+str(base_path),'-M2048','--no-progress','-o',str(output),str(patch)])
                if output.stat().st_size!=item['bytes'] or sha(output)!=item['sha256']:
                    raise ValueError('Reconstructed package differs from the original')
                run(['gh','release','upload',item['tag'],str(output),'--repo',repo,'--clobber'],timeout=600)
                output.unlink()
            current=release(repo,item['tag'])
            uploaded=next(a for a in current['assets'] if a['name']==item['asset'])
            if uploaded.get('digest')!='sha256:'+item['sha256']:raise ValueError('GitHub stored digest mismatch')
            if {a['name'] for a in current['assets']}!={item['asset'],'SHA256SUMS.txt','release-info.json'}:
                raise ValueError('Release metadata incomplete')
            run(['gh','release','edit',item['tag'],'--repo',repo,'--draft=false','--latest=false'])
            verified.append(dict(tag=item['tag'],sha256=item['sha256']))
            print('Restored, verified and published: '+item['tag'],flush=True)
        if len(verified)!=7:raise ValueError('Expected seven historical packages')
        # Delete only this task's verified temporary input, retaining all final
        # assets and all original local archives.
        temporary=next(a for a in release(repo,base_tag)['assets'] if a['name']==bundle_name)
        if temporary.get('digest')!='sha256:'+expected_bundle:raise ValueError('Temporary asset identity changed')
        run(['gh','api','-X','DELETE',f"repos/{repo}/releases/assets/{temporary['id']}"])
        run(['gh','release','edit',base_tag,'--repo',repo,'--latest=true'])
        print(json.dumps(dict(private=True,verified=verified),indent=2),flush=True)


if __name__=='__main__':main()
