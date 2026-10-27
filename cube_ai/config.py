from dataclasses import asdict, dataclass, field
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
LIBRARY = WORKSPACE / "牌表资料"
DATA = ROOT / "data"
RUNS = ROOT / "runs"
GUILDS = ["UW", "BU", "BR", "GR", "GW", "BW", "RU", "BG", "RW", "GU"]
TRIPLES = ["GUW", "BUW", "BRU", "BGR", "GRW", "RUW", "BGU", "BGW", "GRU", "BRW"]
PAIR_THEMES = {
    "UW": ["blink", "artifacts"], "BU": ["graveyard", "control"],
    "BR": ["sacrifice", "tokens"], "GR": ["combat", "lands"],
    "GW": ["tokens", "counters"], "BW": ["sacrifice", "lifegain"],
    "RU": ["spells", "artifacts"], "BG": ["graveyard", "counters"],
    "RW": ["combat", "equipment"], "GU": ["counters", "draw"],
}

@dataclass
class BuildSpec:
    name: str = "我的 Commander Cube"
    mode: str = "commander"
    size: int = 600
    legality_format: str = "commander"
    commanders: int = 90
    lands: int = 70
    seed: int = 42
    avoid_tribal: bool = True
    exclude_game_changers: bool = True
    allow_fast_mana: bool = False
    allow_infinite_combos: bool = False
    allow_mass_land_destruction: bool = False
    allow_colorless_costs: bool = False
    # None preserves historical/custom recipes; Commander presets explicitly use 3.
    bracket: int | None = None
    power_tuning: str = "balanced"
    commander_tuning: str = "matched"
    cube_gc_limit: int | None = None
    allow_extra_turns: bool | None = None
    interaction_min_ratio: float = .18
    wipe_min_ratio: float = .035
    finisher_min_ratio: float = .085
    curve_profile: str = 'balanced'
    max_card_price: float | None = None
    exclude: list[str] = field(default_factory=list)
    pins: list[str] = field(default_factory=list)
    sets: list[str] = field(default_factory=list)
    min_year: int | None = None
    max_year: int | None = None
    pair_themes: dict[str, list[str]] = field(default_factory=lambda: dict(PAIR_THEMES))
    curve: dict[str, int] | None = None
    players: int = 3
    rounds: int = 10
    pack_size: int = 15
    pick_count: int = 2
    discard_after_pass: bool = True

    @classmethod
    def from_dict(cls, data=None):
        if data is not None and not isinstance(data,dict):raise ValueError('构筑参数必须是对象')
        data = dict(data or {})
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError("未知构筑参数: " + ", ".join(sorted(unknown)))
        mode = data.get("mode", "commander")
        if data.get("bracket") is not None:
            data.setdefault("exclude_game_changers", data["bracket"] in (1, 2))
            data.setdefault("allow_extra_turns",False)
        if mode == "classic":
            defaults = dict(name="我的普通 Cube", mode=mode, size=360,
                            commanders=0, lands=45, legality_format="legacy",
                            players=8, rounds=3, pick_count=1, discard_after_pass=False)
            defaults.update(data)
            data = defaults
        obj = cls(**data)
        obj.validate()
        return obj

    def validate(self):
        from .brackets import validate_spec
        validate_spec(self)
        if not isinstance(self.name,str) or not self.name.strip():raise ValueError("name 必须是非空字符串")
        for key in ["size","commanders","lands","seed","players","rounds","pack_size","pick_count"]:
            if type(getattr(self,key)) is not int:raise ValueError(key+" 必须是整数")
        for key in ["avoid_tribal","exclude_game_changers","allow_fast_mana","allow_infinite_combos","allow_mass_land_destruction","allow_colorless_costs","discard_after_pass"]:
            if type(getattr(self,key)) is not bool:raise ValueError(key+" 必须为 true/false")
        for key in ["exclude","pins","sets"]:
            if not isinstance(getattr(self,key),list) or any(not isinstance(n,str) for n in getattr(self,key)):
                raise ValueError(key+" 必须是字符串列表")
        if self.mode not in {"commander", "classic"}:
            raise ValueError("mode 必须是 commander 或 classic")
        if self.legality_format not in {"commander", "legacy", "modern", "pauper", "vintage"}:
            raise ValueError("不支持的合法性赛制")
        if not 90 <= self.size <= 900:
            raise ValueError("Cube 张数必须在 90–900 之间")
        if not 0 <= self.commanders <= self.size * .3 or not 0 <= self.lands <= self.size * .3:
            raise ValueError("指挥官/地牌数量超出合理范围")
        if self.mode == "classic" and self.commanders:
            raise ValueError("普通 Cube 的专用指挥官槽位应为 0")
        if self.mode == "commander" and self.commanders < 10:
            raise ValueError("Commander Cube 至少预留 10 个指挥官槽位")
        main=self.size-self.commanders-self.lands
        if main<40:raise ValueError('至少需要 40 个主牌槽位')
        if self.curve_profile not in {'balanced','low','late'}:raise ValueError('curve_profile 必须为 balanced/low/late')
        for key,low,high in [('interaction_min_ratio',.10,.30),('wipe_min_ratio',.01,.08),('finisher_min_ratio',.06,.20)]:
            value=getattr(self,key)
            if type(value) not in {int,float} or not low<=value<=high:raise ValueError(f'{key} 必须在 {low}–{high} 之间')
        if self.players < 2 or self.players > 12 or self.rounds < 1 or self.rounds > 30:
            raise ValueError("轮抽人数或轮数无效")
        if not 1 <= self.pick_count <= self.pack_size or not 5<=self.pack_size<=60:
            raise ValueError("每次抓牌数/包大小无效")
        if self.discard_after_pass and self.pack_size <= self.players * self.pick_count:
            raise ValueError("该规则下每包需要能留下弃牌")
        if self.max_card_price is not None and (type(self.max_card_price) not in {int,float} or not 0<self.max_card_price<1e9):
            raise ValueError("单卡价格上限必须大于 0")
        for key in ['min_year','max_year']:
            value=getattr(self,key)
            if value is not None and (type(value) is not int or not 1993<=value<=2100):raise ValueError(key+" 必须是有效年份")
        if self.curve is not None and (not isinstance(self.curve,dict) or any(type(v) is not int or v<0 for v in self.curve.values())):
            raise ValueError("curve 必须是非负整数的字典")
        if self.curve is not None and (set(self.curve)!={'1','2','3','4','5+'} or sum(self.curve.values())!=main):
            raise ValueError('自定义曲线必须包含 1、2、3、4、5+，且合计等于主牌张数')
        if self.min_year and self.max_year and self.min_year > self.max_year:
            raise ValueError("起始年份不能晚于结束年份")
        if not isinstance(self.pair_themes,dict):raise ValueError("pair_themes 必须为字典")
        for g, themes in self.pair_themes.items():
            if not isinstance(themes,list):raise ValueError("每个色组的主题必须为列表")
            if g not in GUILDS or any(t not in THEME_NAMES for t in themes):
                raise ValueError("未知色组或协同主题")

    def to_dict(self):
        return asdict(self)

THEME_NAMES = {
    "blink": "闪现/进场", "artifacts": "神器", "graveyard": "墓地/再利用",
    "control": "控制", "sacrifice": "牺牲", "tokens": "衍生物", "combat": "战斗",
    "lands": "地/额外地", "counters": "+1/+1 指示物", "lifegain": "回血",
    "spells": "非生物咒语", "equipment": "装备", "draw": "抓牌",
}

def card_pool_path():
    choices = [Path(os.environ["CUBE_CARD_POOL"])] if os.getenv("CUBE_CARD_POOL") else [
        DATA / "card_pool.json", WORKSPACE / "commander_cube_600_v4/research/card_pool.json"]
    for p in choices:
        if p.is_file():
            return p
    raise FileNotFoundError("找不到牌库。设置 CUBE_CARD_POOL 或把 Scryfall 快照放入 cube_ai/data/card_pool.json")
