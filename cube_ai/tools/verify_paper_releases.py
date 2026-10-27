"""Collect public print witnesses into a new folder; never updates runtime data."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import time
import urllib.parse

import requests


def witness(card,response,as_of):
    reviewed=date.fromisoformat(as_of)
    if response.get('object')!='list' or not isinstance(response.get('data'),list):raise ValueError('Invalid Scryfall response')
    records=response['data']
    if any(r.get('oracle_id')!=card['oracle_id'] or r.get('name')!=card['name'] for r in records):raise ValueError('Scryfall name/Oracle ID mismatch')
    paper=[r for r in records if 'paper' in r.get('games',[]) and r.get('lang')=='en'
           and not r.get('digital') and not r.get('oversized') and date.fromisoformat(r['released_at'])<=reviewed]
    if not paper:return None
    p=min(paper,key=lambda r:(r['released_at'],r['id']))
    return dict(name=card['name'],oracle_id=card['oracle_id'],print_id=p['id'],released_at=p['released_at'],
                set=p['set'],source='https://api.scryfall.com/cards/'+p['id'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    if out.exists():raise FileExistsError('Use a new evidence folder; prior results are preserved')
    from cube_ai.catalog import Catalog
    c=Catalog();today=date.today().isoformat();cases=[v for v in c.cards.values() if v.get('released','')>today and v.get('oracle_id')]
    out.mkdir(parents=True);results=[];entries=[];session=requests.Session()
    session.headers.update({'Accept':'application/json','User-Agent':'MTG-Cube-Builder paper release verification'})
    for card in cases:
        time.sleep(.15)
        url='https://api.scryfall.com/cards/search?'+urllib.parse.urlencode(dict(q='oracleid:'+card['oracle_id'],unique='prints',order='released',dir='asc'))
        response=session.get(url,timeout=30);raw=response.content
        (out/(card['oracle_id']+'.json')).write_bytes(raw)
        found=witness(card,response.json(),today) if response.status_code==200 else None
        if found:entries.append(found)
        results.append(dict(name=card['name'],oracle_id=card['oracle_id'],url=url,status=response.status_code,
                            sha256=hashlib.sha256(raw).hexdigest(),witness=found))
        (out/'results.json').write_bytes(json.dumps(results,ensure_ascii=False,indent=2).encode('utf8'))
    value=dict(version='paper-release-witness-1',reviewed=today,cards=sorted(entries,key=lambda r:r['name']))
    (out/'paper_release_witnesses.json').write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
    print(json.dumps(dict(cards=len(cases),verified=len(entries),output=str(out),runtime_updated=False)),flush=True)


if __name__=='__main__':main()
