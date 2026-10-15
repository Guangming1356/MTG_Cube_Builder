import math
import re
from collections import Counter, defaultdict
from .config import ROOT, WORKSPACE

def tokens(text):
    words=re.findall(r"[a-z][a-z0-9+/-]*",text.lower())
    for span in re.findall(r"[\u4e00-\u9fff]+",text):
        words.extend(span[i:i+2] for i in range(max(1,len(span)-1)))
    return words

class Knowledge:
    def __init__(self):
        paths=list((WORKSPACE/"magic-skill/wiki/concepts").glob("*.md"))
        paths+=list((ROOT/"knowledge").glob("*.md"))
        paths += [WORKSPACE/"magic-skill/skill/limited-master/SKILL.md",
                  WORKSPACE/"magic-skill/skill/limited-master/references/limited-playbook.md",
                  WORKSPACE/"magic-skill/wiki/synthesis/limited-learning-path.md"]
        self.chunks=[];self.df=Counter();self.index=defaultdict(list)
        for path in sorted(set(paths)):
            if not path.is_file():continue
            text=path.read_text(encoding="utf-8")
            for paragraph in re.split(r"\n(?=## )",text):
                for offset in range(0,len(paragraph),1600):
                    part=paragraph[offset:offset+1800]
                    if len(part.strip())<60:continue
                    tf=Counter(tokens(part));index=len(self.chunks)
                    self.chunks.append(dict(source=str(path.relative_to(WORKSPACE)).replace("\\","/"),text=part,tf=tf,length=sum(tf.values())))
                    self.df.update(tf.keys())
                    for term in tf:self.index[term].append(index)
        self.avg=sum(c["length"] for c in self.chunks)/max(1,len(self.chunks))

    def search(self,query,limit=5):
        scores=defaultdict(float);n=len(self.chunks)
        for term in set(tokens(query)):
            idf=math.log(1+(n-self.df[term]+.5)/(self.df[term]+.5))
            for i in self.index.get(term,[]):
                c=self.chunks[i];freq=c["tf"][term]
                scores[i]+=idf*(freq*2.2)/(freq+1.2*(.25+.75*c["length"]/max(1,self.avg)))
        return [dict(source=self.chunks[i]["source"],text=self.chunks[i]["text"],score=round(scores[i],2))
                for i in sorted(scores,key=scores.get,reverse=True)[:limit]]
