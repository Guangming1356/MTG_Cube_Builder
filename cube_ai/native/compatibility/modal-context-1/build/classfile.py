# SPDX-License-Identifier: GPL-3.0-or-later
"""Inspect class structure and raw method attributes, without executing Forge."""
import struct


class Reader:
    def __init__(self,data):self.data=data;self.offset=0
    def take(self,n):
        result=self.data[self.offset:self.offset+n];self.offset+=n
        if len(result)!=n:raise ValueError('Truncated class')
        return result
    def u1(self):return self.take(1)[0]
    def u2(self):return struct.unpack('>H',self.take(2))[0]
    def u4(self):return struct.unpack('>I',self.take(4))[0]

def parse(data):
    r=Reader(data);assert r.u4()==0xcafebabe
    version=r.take(4);count=r.u2();pool=[None]*count;index=1;pool_start=r.offset
    widths={3:4,4:4,5:8,6:8,7:2,8:2,9:4,10:4,11:4,12:4,15:3,16:2,17:4,18:4,19:2,20:2}
    while index<count:
        tag=r.u1()
        if tag==1:pool[index]=r.take(r.u2()).decode('utf8',errors='replace')
        else:r.take(widths[tag])
        index+=2 if tag in {5,6} else 1
    pool_bytes=data[pool_start:r.offset]
    def attributes():return tuple((pool[r.u2()],r.take(r.u4())) for _ in range(r.u2()))
    header=r.take(6);interfaces=r.take(r.u2()*2)
    fields=[]
    for _ in range(r.u2()):fields.append((r.take(6),attributes()))
    methods={}
    for _ in range(r.u2()):
        access=r.u2();name=pool[r.u2()];descriptor=pool[r.u2()]
        methods[(name,descriptor)]=(access,attributes())
    tail_offset=r.offset;tail=attributes();assert r.offset==len(data)
    return dict(version=version,header=header,interfaces=interfaces,fields=fields,methods=methods,tail=tail,
                tail_offset=tail_offset,pool_bytes=pool_bytes)

