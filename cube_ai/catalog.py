import csv
import hashlib
import io
import json
import re
import os
import tempfile
from collections import OrderedDict
from heapq import nsmallest
from pathlib import Path
from .config import DATA, WORKSPACE, card_pool_path
from .features import VERSION, extract, oracle, tribes_from_cards

FETCHES = dict(zip(
    ["Flooded Strand", "Polluted Delta", "Bloodstained Mire", "Wooded Foothills", "Windswept Heath", "Marsh Flats", "Scalding Tarn", "Verdant Catacombs", "Arid Mesa", "Misty Rainforest"],
    ["UW", "BU", "BR", "GR", "GW", "BW", "RU", "BG", "RW", "GU"]))


class ReadOnlyLegalities(dict):
    """JSON/pickle-compatible immutable values shared across card records."""
    __slots__=('_sealed',)
    def __init__(self,values=()):
        if hasattr(self,'_sealed'):self._readonly()
        value=dict(values)
        if not all(isinstance(k,str) and isinstance(v,str) for k,v in value.items()):raise TypeError('合法性记录只接受字符串')
        dict.__init__(self,value);object.__setattr__(self,'_sealed',True)
    def _readonly(self,*args,**kwargs):raise TypeError('牌库合法性只读；请用 dict(legalities) 创建独立副本')
    __setitem__=__delitem__=__setattr__=clear=pop=popitem=setdefault=update=__ior__=_readonly
    def __copy__(self):return self
    def __deepcopy__(self,memo):return self
    def __reduce__(self):return (type(self),(dict(self),))


def _legality_pool():
    values={}
    def compact(record):
        legalities=record.get('legalities')
        if isinstance(legalities,dict) and all(isinstance(k,str) and isinstance(v,str) for k,v in legalities.items()):
            # Keep the original key order as well as values; public JSON output
            # remains identical while repeated per-card maps become shared.
            token=tuple(legalities.items())
            existing=values.get(token)
            if existing is None:existing=values[token]=ReadOnlyLegalities(legalities)
            record['legalities']=existing
        return record
    return compact


def _read_catalog_json(path):
    # Intern during decoding rather than retaining thousands of full maps until
    # after construction; reduces steady memory without duplicating their peak.
    return json.loads(path.read_text(encoding='utf8'),object_hook=_legality_pool())

CATALOG_CACHE_FORMAT = 2


def _decode_catalog_cache(value):
    if not isinstance(value,dict) or '_catalog_cache_format' not in value:return value
    if type(value['_catalog_cache_format']) is not int or value['_catalog_cache_format']!=CATALOG_CACHE_FORMAT:
        raise ValueError('不支持的牌库缓存格式')
    pool=value.get('_legalities_pool');cards=value.get('cards')
    if not isinstance(pool,list) or not isinstance(cards,list):raise ValueError('牌库缓存结构无效')
    maps=[];known={}
    for item in pool:
        if not isinstance(item,dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in item.items()):
            raise ValueError('牌库缓存合法性记录无效')
        token=tuple(item.items());shared=known.get(token)
        if shared is None:shared=known[token]=ReadOnlyLegalities(item)
        maps.append(shared)
    for card in cards:
        index=card.get('legalities') if isinstance(card,dict) else None
        if type(index) is not int or not 0<=index<len(maps):raise ValueError('牌库缓存合法性引用无效')
        card['legalities']=maps[index]
    del value['_catalog_cache_format'];del value['_legalities_pool']
    return value


def _write_catalog_cache(value,path):
    # Keep only one temporary card copy: large normalized records are not cloned
    # as a second full list. The small reference list shares integer pool indices.
    pool=[];known={};references=[]
    for card in value['cards']:
        item=card.get('legalities')
        if not isinstance(item,dict):raise ValueError('牌库缓存缺少合法性记录')
        token=tuple(item.items())
        if token not in known:
            if not all(isinstance(k,str) and isinstance(v,str) for k,v in item.items()):
                raise ValueError('牌库缓存合法性记录无效')
            known[token]=len(pool);pool.append(item)
        references.append(known[token])
    header=dict(_catalog_cache_format=CATALOG_CACHE_FORMAT,_legalities_pool=pool)
    header.update((k,v) for k,v in value.items() if k not in {'cards','_catalog_cache_format','_legalities_pool'})
    fd,tmp=tempfile.mkstemp(prefix='catalog-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as file:
            file.write(json.dumps(header,ensure_ascii=False)[:-1]+', "cards": [')
            for i,(card,index) in enumerate(zip(value['cards'],references)):
                packed=dict(card);packed['legalities']=index
                if i:file.write(', ')
                file.write(json.dumps(packed,ensure_ascii=False))
            file.write(']}')
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


class Catalog:
    def __init__(self, source=None, use_cache=True):
        self.source = Path(source or card_pool_path())
        DATA.mkdir(exist_ok=True)
        stat = self.source.stat()
        signature = f"{self.source.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{VERSION}"
        cache = DATA / "catalog.json"
        j = None;cache_legacy=False
        if use_cache and cache.exists():
            try:
                cached = _read_catalog_json(cache)
                cache_legacy=isinstance(cached,dict) and '_catalog_cache_format' not in cached
                cached=_decode_catalog_cache(cached)
                if isinstance(cached,dict) and cached.get('signature')==signature and isinstance(cached.get('cards'),list) and cached['cards'] and 'snapshot' in cached:
                    if all(isinstance(c,dict) and isinstance(c.get('legalities'),ReadOnlyLegalities) and all(k in c for k in ['name','text','identity','quality','kind']) for c in cached['cards']):j=cached
            except (OSError,ValueError):pass
        if j is None:
            raw = _read_catalog_json(self.source)
            cards = list(raw["cards"].values())
            tribes = tribes_from_cards(cards)
            records = []
            for c in cards:
                f = extract(c, tribes)
                front = (c.get("card_faces") or [c])[0]
                image = c.get("image_uris", front.get("image_uris", {})).get("normal", "")
                prices = c.get("prices", {})
                value = prices.get("usd") or prices.get("usd_foil")
                records.append(dict(name=c["name"], oracle_id=c.get("oracle_id"), text=oracle(c),
                    type=c["type_line"], identity="".join(sorted(c.get("color_identity", []))) or "C",
                    legalities=c.get("legalities", {}), game_changer=bool(c.get("game_changer")),
                    digital=bool(c.get("digital")), released=c.get("released_at", ""), set=c.get("set", ""),
                    rank=c.get("edhrec_rank"), price=float(value) if value else None,
                    fixing=list(FETCHES.get(c["name"], c.get("produced_mana", []))),
                    image=image, url=c.get("scryfall_uri", ""), **f))
            j = dict(signature=signature, snapshot=raw.get("date"), version=VERSION, cards=records)
            _write_catalog_cache(j,cache)
        elif cache_legacy:
            # A readable legacy cache remains usable on read-only installations.
            try:_write_catalog_cache(j,cache)
            except OSError:pass
        self.snapshot = j["snapshot"]
        self.signature = hashlib.sha256(signature.encode()).hexdigest()[:16]
        self.cards = {c["name"]: c for c in j["cards"]}
        self.aliases = {n.casefold(): n for n in self.cards}
        self._search_cache = OrderedDict()
        for n in self.cards:
            if " // " in n:
                self.aliases.setdefault(n.split(" // ")[0].casefold(), n)
        from .forge_card_names import add_catalog_aliases
        add_catalog_aliases(self.aliases)
        self.reference = set()
        reference = WORKSPACE / "ref_thecommandercube.csv"
        if reference.is_file():
            for row in csv.DictReader(reference.read_text(encoding="utf-8-sig").splitlines()):
                n = self.resolve(row.get("name", ""))
                if n: self.reference.add(n)

    def resolve(self, name):
        if not isinstance(name,str):return None
        return self.aliases.get(name.strip().casefold())

    @classmethod
    def from_records(cls,records,snapshot,signature):
        """A trusted, read-only task snapshot; never writes the full catalog cache.

        Used only by operations that evaluate an already validated card list.
        Construction/search/AI operations still receive the complete catalog.
        """
        value=cls.__new__(cls);value.source=None;value.snapshot=snapshot;value.signature=signature
        compact=_legality_pool()
        value.cards={card['name']:compact(dict(card)) for card in records};value.reference=set()
        value.aliases={name.casefold():name for name in value.cards};value._search_cache=OrderedDict()
        for name in value.cards:
            if ' // ' in name:value.aliases.setdefault(name.split(' // ')[0].casefold(),name)
        from .forge_card_names import add_catalog_aliases
        add_catalog_aliases(value.aliases)
        return value

    def search(self, query="", identity=None, limit=30):
        query=query.casefold();limit=min(100,max(1,limit));token=(query,identity,limit)
        if token in self._search_cache:
            names=self._search_cache[token];self._search_cache.move_to_end(token)
            return [self.cards[n] for n in names]
        words = query.split()
        cards=[]
        for card in self.cards.values():
            if identity and card['identity']!=identity:continue
            if words:
                text=(card['name']+' '+card['text']+' '+card['type']).casefold()
                if not all(word in text for word in words):continue
            cards.append(card)
        result=nsmallest(limit,cards,key=lambda c:(not c['name'].casefold().startswith(query),-c['quality'],c['name']))
        self._search_cache[token]=tuple(c['name'] for c in result)
        if len(self._search_cache)>64:self._search_cache.popitem(last=False)
        return result

    def parse(self, text):
        if not isinstance(text,str):raise ValueError('牌表内容必须是文本')
        text = text.lstrip("\ufeff").strip()
        rows = []
        errors = []
        if not text: return rows, errors
        first = text.splitlines()[0]
        if "," in first and re.search(r"(?:name|card|名称)", first, re.I):
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                lower = {k.strip().casefold(): v or '' for k, v in row.items() if k is not None}
                if lower.get('board','').strip().lower() not in {'','main','mainboard'}:continue
                if lower.get('maybeboard','').strip().lower() in {'true','1'}:continue
                name = lower.get("name") or lower.get("card") or lower.get("名称") or ""
                role = lower.get("role") or ("Commander" if "commander" in lower.get("tags", "").lower() else None)
                count=lower.get('count') or lower.get('quantity') or '1'
                try:amount=int(count)
                except ValueError:raise ValueError('CSV 数量必须是 1–100 的整数') from None
                if not 1<=amount<=100:raise ValueError('CSV 单行数量必须为 1–100')
                if len(rows)+amount>900:raise ValueError('本项目单套牌表最多支持 900 张')
                rows.extend([(name,role)]*amount)
        else:
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "//")): continue
                count = re.match(r"^(\d+)\s*[xX]?\s+(.+)$", line)
                if count:
                    amount, name = int(count[1]), count[2]
                    if not 1<=amount<=100: raise ValueError("单行数量必须为 1–100")
                else: amount, name = 1, line
                name = re.sub(r"\s+\([A-Za-z0-9]+\)\s+\S+.*$", "", name)
                if len(rows)+amount>900:raise ValueError('本项目单套牌表最多支持 900 张')
                rows.extend([(name, None)] * amount)
        result = []
        for name, role in rows:
            canonical = self.resolve(name)
            if not canonical:
                errors.append(name)
                continue
            c = self.cards[canonical]
            role = role or ("Land" if c["kind"] == "land" else "Commander" if c["commander"] else "Main")
            role={'land':'Land','commander':'Commander','main':'Main'}.get(str(role).strip().casefold())
            if not role:raise ValueError('CSV role 必须为 Main、Land 或 Commander')
            result.append({"name": canonical, "role": role})
        return result, errors

def exclusion_reasons(c, spec, *, power=None):
    from .brackets import card_reasons, is_gc
    reasons = []
    if c["legalities"].get(spec.legality_format) != "legal": reasons.append("该赛制不合法/受限")
    if c["digital"]: reasons.append("数字专属")
    if c.get('front_unusable'):reasons.append('合体结果面不能作为独立牌张/指挥官')
    if c.get('extra_deck'):reasons.append('需要额外 Attraction/贴纸/机关组件；当前环境未配置')
    if "Basic Land" in c["type"]: reasons.append("基本地另行提供")
    if spec.exclude_game_changers and (is_gc(c) if spec.bracket is not None else c["game_changer"]): reasons.append("Game Changer")
    reasons.extend(card_reasons(c,spec,power=power))
    if c["tribal"] and spec.avoid_tribal: reasons.append("部族依赖: " + ", ".join(c["tribal"]))
    if c.get('narrow_subtypes') and spec.avoid_tribal:reasons.append('窄副类别依赖: '+', '.join(c['narrow_subtypes']))
    if c.get('named_dependency') and spec.avoid_tribal:reasons.append('指定牌名配合依赖；默认排除窄组件')
    if c["fast_mana"] and not spec.allow_fast_mana: reasons.append("爆发快法术力")
    if c["mld"] and not spec.allow_mass_land_destruction: reasons.append("大规模炸地/法术力封锁")
    if spec.exclude and c["name"].casefold() in {n.strip().casefold() for n in spec.exclude}: reasons.append("用户排除")
    if spec.max_card_price is not None and (c["price"] is None or c["price"] > spec.max_card_price): reasons.append("价格未知/超过单卡上限")
    if spec.sets and c["set"] not in spec.sets: reasons.append("不在指定快照印张系列")
    year = int(c["released"][:4] or 0)
    if spec.min_year and year < spec.min_year or spec.max_year and year > spec.max_year: reasons.append("印张年份不符")
    return reasons
