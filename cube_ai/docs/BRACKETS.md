# 用 Commander Bracket 控制 Cube

首页选择「强度目标」，再选「温和一点 / 均衡 / 强一点」。建议从 **3 · Upgraded、均衡**开始，想提高效率和强牌空间可选 **4 · Optimized**。无需 GPT。

## 官方分档与本项目的适配

| 目标 | 体验方向 | 每副组好的牌 Game Changers |
| --- | --- | --- |
| 1 · Exhibition | 主题、创意与有趣互动 | 默认 0；本工具保守预设不提供 Rule 0 例外 |
| 2 · Core | 休闲、可回应的场面与终结 | 0 |
| 3 · Upgraded | 好单卡、协同、资源积累后的爆发 | 最多 3 |
| 4 · Optimized | 效率、稳定性、高质量威胁与应对 | 不限 |
| 5 · cEDH | 竞技意图与环境适配 | 不限；本工具仅提供实验构筑目标 |

Bracket 是整副牌的构筑意图与体验指导，不是数值牌力评分。不能把平均单卡评价 3.5 解释为 Bracket 3.5，也不能通过 Game Changer 数量单独认定档位。官方回合预期是赛前讨论的参考；不能把 Forge 日志里的总回合数直接当成每位玩家自己的回合数。1 档的主题意图和 5 档的竞技环境适配需要另行确认。

官方标准面向 Commander；你的 60 张三人轮抓使用适配规则。轮抓得到 60 张后，选择任意部分并补基本地组成至少 60 张含指挥官的牌组。**3 档的 3 张上限针对组好的每副牌，包含指挥官和地牌；600 张 Cube 无须只含 3 张。** 自动组牌器会执行这个上限，实际游玩时也需要遵守。

## 已实现的控制

- 5 个档位 × 3 种同档单卡强度；另有 3 种指挥官强度选择。
- 生成器针对不同目标调整选牌分数，并约束主牌平均启发式评价区间、单卡上限、高评价牌密度和整个 Cube 的 Game Changer 数量。
- 高级页面可调整整个 Cube 的 Game Changer 数量预算；留空按 600 张时 0 / 0 / 18 / 36 / 54 张的项目预算。这些数字是上限，不是保证加入的数量，也不是官方 Cube 规则。
- 费用曲线、低费行动、互动、扫场、终结、颜色配额、色组平均评价差继续生效。提高强度不会主动增加高费牌比例。
- 所有档位默认保留原来的快法术力、无限组合、炸地排除偏好。4/5 档需要你主动勾选才开启。1–3 档采用保守策略，也排除额外回合和已知无限组合；额外回合全部排除比官方要求严格。
- 官方已取消导师数量限制。本项目不把导师数量上限当作官方规则。
- 手工替换、GPT 建议、轮抓组牌、Forge 导出和自动优化均检查或保留强度预算。结果报告列出目标、实际 GC 名单和构筑限制检查；不会认证实战档位。
- 旧方案自动保留「自定义 / 旧方案」。新功能不改写旧牌表。改选档位后可生成新版本；只给旧牌表切换标签不会改变卡牌。

## 参数示例

```json
{
  "bracket": 3,
  "power_tuning": "strong",
  "commander_tuning": "matched",
  "cube_gc_limit": 18,
  "exclude_game_changers": false,
  "allow_fast_mana": false,
  "allow_infinite_combos": false,
  "allow_mass_land_destruction": false,
  "allow_extra_turns": false
}
```

约束冲突会明确报错，不会静默放宽。评分来自当前启发式模型，较高档位不保证每次生成的平均分或实际胜率更高；尤其保留快法术力与组合限制时，4/5 档的牌表可能接近。5 档不能据此认定达到 cEDH。

## 来源与版本

2026-10-11 核验；冻结官方 2025-10-21 分档说明与 2026-02-09 Game Changers 更新。53 个 Game Changer 名称独立于本地快照标记存储，包含 Farewell 和 Biorhythm，双面牌按正面名称识别。未来官方变更需要更新策略文件，当前不会自动同步。

- [官方 Commander 页面](https://magic.wizards.com/en/formats/commander)
- [2025-10-21 分档更新](https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-october-21-2025)
- [2026-02-09 更新](https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-february-9-2026)

卡牌覆盖仍受本地快照限制；本功能不会补齐之前缺失的卡牌，也不替代禁牌表和资料更新。
