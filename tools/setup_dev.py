"""Restore only release dependencies into a source checkout."""
import argparse,hashlib,json,zipfile
from pathlib import Path,PurePosixPath
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--zip',required=True,type=Path);args=p.parse_args()
expected=json.loads((root/'distribution/archive.json').read_text(encoding='utf8'))
with args.zip.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
if actual!=expected['sha256']:raise SystemExit('压缩包不是当前标签对应版本，或校验失败。请下载 README 中对应版本。')
count=0
with zipfile.ZipFile(args.zip) as z:
 for entry in z.infolist():
  path=PurePosixPath(entry.filename)
  if path.is_absolute() or '..' in path.parts:raise SystemExit('压缩包路径无效')
  if not path.parts or path.parts[0]!='Cube助手':continue
  rel=PurePosixPath(*path.parts[1:])
  chosen=rel.as_posix()=='cube_ai/data/card_pool.json' or rel.as_posix().startswith('cube_ai/runtime/')
  if not chosen or entry.is_dir():continue
  if any(s in {'private','cache','userdata','entrance.json','launcher.log','forge.profile.properties'} for s in rel.parts):continue
  target=root/Path(*rel.parts)
  if not target.resolve().is_relative_to(root.resolve()):raise SystemExit('目标路径无效')
  if target.exists() and rel.as_posix()=='cube_ai/data/card_pool.json':
   with z.open(entry) as f:source_hash=hashlib.file_digest(f,'sha256').hexdigest()
   with target.open('rb') as f:target_hash=hashlib.file_digest(f,'sha256').hexdigest()
   if source_hash!=target_hash:raise SystemExit('现有牌库与发布版不同，请先备份现有牌库后再初始化。')
  target.parent.mkdir(parents=True,exist_ok=True)
  with z.open(entry) as f,target.open('wb') as out:
   import shutil;shutil.copyfileobj(f,out,1024*1024)
  count+=1
print('运行依赖已准备：',count,'个文件。运行 python -X utf8 -m cube_ai serve')
