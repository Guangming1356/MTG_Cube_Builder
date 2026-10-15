import csv
import hashlib
import io
import json
import re
from .config import DATA, WORKSPACE, card_pool_path
from .features import VERSION, extract, oracle, tribes_from_cards

FETCHES = dict(zip(
    ["Flooded Strand", "Polluted Delta", "Bloodstained Mire", "Wooded Foothills", "Windswept Heath", "Marsh Flats", "Scalding Tarn", "Verdant Catacombs", "Arid Mesa", "Misty Rainforest"],
    ["UW", "BU", "BR", "GR", "GW", "BW", "RU", "BG", "RW", "GU"]))

class Catalog:
    def __init__(self, source=None, use_cache=True):
        self.source = source or card_pool_path()
        DATA.mkdir(exist_ok=True)
        stat = self.source.stat()
        signature = f"{self.source.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{VERSION}"
        cache = DATA / "catalog.json"
        j = None
        if use_cache and cache.exists():
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if cached.get("signature") == signature: j = cached
        if j is None:
            raw = json.loads(self.source.read_text(encoding="utf-8"))
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
            tmp = cache.with_suffix(".tmp")
            tmp.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
            tmp.replace(cache)
        self.snapshot = j["snapshot"]
        self.signature = hashlib.sha256(signature.encode()).hexdigest()[:16]
        self.cards = {c["name"]: c for c in j["cards"]}
        self.aliases = {n.casefold(): n for n in self.cards}
        for n in self.cards:
            if " // " in n:
                self.aliases.setdefault(n.split(" // ")[0].casefold(), n)
        self.reference = set()
        reference = WORKSPACE / "ref_thecommandercube.csv"
        if reference.is_file():
            for row in csv.DictReader(reference.read_text(encoding="utf-8-sig").splitlines()):
                n = self.resolve(row.get("name", ""))
                if n: self.reference.add(n)

    def resolve(self, name):
        return self.aliases.get(name.strip().casefold())

    def search(self, query="", identity=None, limit=30):
        words = query.casefold().split()
        cards = [c for c in self.cards.values() if (not identity or c["identity"] == identity)
                 and all(w in (c["name"] + " " + c["text"] + " " + c["type"]).casefold() for w in words)]
        cards.sort(key=lambda c: (not c["name"].casefold().startswith(query.casefold()), -c["quality"], c["name"]))
        return cards[:min(100, max(1, limit))]

    def parse(self, text):
        text = text.lstrip("\ufeff").strip()
        rows = []
        errors = []
        if not text: return rows, errors
        first = text.splitlines()[0]
        if "," in first and re.search(r"(?:name|card|名称)", first, re.I):
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                lower = {k.casefold(): v for k, v in row.items() if k is not None}
                if lower.get('board','').strip().lower() not in {'','main','mainboard'}:continue
                if lower.get('maybeboard','').strip().lower() in {'true','1'}:continue
                name = lower.get("name") or lower.get("card") or lower.get("名称") or ""
                role = lower.get("role") or ("Commander" if "commander" in lower.get("tags", "").lower() else None)
                rows.append((name, role))
        else:
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "//")): continue
                count = re.match(r"^(\d+)\s*[xX]?\s+(.+)$", line)
                if count:
                    amount, name = int(count[1]), count[2]
                    if amount > 100: raise ValueError("单行数量超过 100")
                else: amount, name = 1, line
                name = re.sub(r"\s+\([A-Za-z0-9]+\)\s+\S+.*$", "", name)
                rows.extend([(name, None)] * amount)
        result = []
        for name, role in rows:
            canonical = self.resolve(name)
            if not canonical:
                errors.append(name)
                continue
            c = self.cards[canonical]
            role = role or ("Land" if c["kind"] == "land" else "Commander" if c["commander"] else "Main")
            if role not in {"Land", "Commander", "Main"}: role = "Main"
            result.append({"name": canonical, "role": role})
        return result, errors

def exclusion_reasons(c, spec):
    from .brackets import card_reasons, is_gc
    reasons = []
    if c["legalities"].get(spec.legality_format) != "legal": reasons.append("该赛制不合法/受限")
    if c["digital"]: reasons.append("数字专属")
    if c.get('front_unusable'):reasons.append('合体结果面不能作为独立牌张/指挥官')
    if c.get('extra_deck'):reasons.append('需要额外 Attraction/贴纸/机关组件；当前环境未配置')
    if "Basic Land" in c["type"]: reasons.append("基本地另行提供")
    if (is_gc(c) if spec.bracket is not None else c["game_changer"]) and spec.exclude_game_changers: reasons.append("Game Changer")
    reasons.extend(card_reasons(c,spec))
    if c["tribal"] and spec.avoid_tribal: reasons.append("部族依赖: " + ", ".join(c["tribal"]))
    if c.get('named_dependency') and spec.avoid_tribal:reasons.append('指定牌名配合依赖；默认排除窄组件')
    if c["fast_mana"] and not spec.allow_fast_mana: reasons.append("爆发快法术力")
    if c["mld"] and not spec.allow_mass_land_destruction: reasons.append("大规模炸地/法术力封锁")
    if c["name"].casefold() in {n.strip().casefold() for n in spec.exclude}: reasons.append("用户排除")
    if spec.max_card_price is not None and (c["price"] is None or c["price"] > spec.max_card_price): reasons.append("价格未知/超过单卡上限")
    if spec.sets and c["set"] not in spec.sets: reasons.append("不在指定快照印张系列")
    year = int(c["released"][:4] or 0)
    if spec.min_year and year < spec.min_year or spec.max_year and year > spec.max_year: reasons.append("印张年份不符")
    return reasons
