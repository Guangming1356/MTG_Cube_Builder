"""Convert downloaded Scryfall JSON array / JSONL / gzipped JSONL into a reusable snapshot."""
import argparse
import gzip
import json
from pathlib import Path
from .config import DATA

def convert(source,destination,snapshot_date='用户导入（日期未知）'):
    source=Path(source)
    opener=gzip.open if source.suffix=='.gz' else open
    with opener(source,'rt',encoding='utf-8-sig') as f:
        head=f.readline();f.seek(0)
        if head.lstrip().startswith('['):raw=json.load(f);records=iter(raw)
        else:
            try:first=json.loads(head)
            except json.JSONDecodeError:
                raw=json.load(f);records=iter(raw['cards'].values());snapshot_date=raw.get('date',snapshot_date)
            else:
                if 'cards' in first:
                    records=iter(first['cards'].values());snapshot_date=first.get('date',snapshot_date)
                else:records=(json.loads(line) for line in f if line.strip())
        cards={}
        for card in records:
            if card.get('lang','en')!='en' or 'paper' not in card.get('games',['paper']):continue
            name=card.get('name')
            if not name or not card.get('type_line'):continue
            old=cards.get(name)
            if old is None or (not card.get('digital'),card.get('released_at',''))>(not old.get('digital'),old.get('released_at','')):
                cards[name]=card
    if len(cards)<100:raise ValueError('导入不足 100 张；请使用完整 Oracle / default cards bulk 数据')
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(dict(date=snapshot_date,source=str(source.name),cards=cards),ensure_ascii=False),encoding='utf-8')
    return dict(cards=len(cards),snapshot=snapshot_date,destination=str(destination))

def main():
    p=argparse.ArgumentParser();p.add_argument('file',type=Path);p.add_argument('--output',type=Path,default=DATA/'card_pool.json');p.add_argument('--snapshot-date',default='用户导入（日期未知）')
    a=p.parse_args();print(convert(a.file,a.output,a.snapshot_date))
if __name__=='__main__':main()
