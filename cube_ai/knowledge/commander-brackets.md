# Commander Bracket 强度目标：Cube 适配

核验日期：2026-10-11。官方依据：2025-10-21 分档更新、2026-02-09 更新和官方 Commander 页面。

Bracket 是整副牌的构筑意图与对局体验，不能把启发式单卡均分直接换算成官方档位。1 Exhibition 注重主题创意，2 Core 注重休闲场面，3 Upgraded 有较好的单卡、协同与回应，4 Optimized 注重效率稳定性，5 cEDH 需要竞技意图及环境适配。5 档预设不等于已认证 cEDH。

本项目 1/2 档保守预设不含 Game Changers；3 档每副组好的牌最多 3 张，指挥官和地牌也计数；4/5 档官方不限制这个数量。Cube 本身的 18/36/54 张默认上限是项目预算。GC 名单已更新 Farewell 和 Biorhythm，不沿用已移除的 Yuriko、Winota 等标记。官方已取消导师数量限制。

本项目按目标约束主牌均分区间、单卡上限、强牌密度、指挥官选择和 Cube GC 数量。仍保持原有曲线、低费行动、互动、扫场、后期终结与颜色平衡。1–3 档保守排除额外回合与已知无限组合；4/5 档默认也保留用户的快法术力、组合和炸地排除偏好，需要主动修改才开启。这些项目策略不能冒充官方全部禁令。

自动组牌适配三人轮抓，每人抓 60 张后选择任意部分并补基本地，组成至少 60 张含指挥官的牌组。压力测试报告和 Forge 导出分别复核实际牌组；总回合数不能直接用于判定官方自己的回合预期。实战还需确认获胜速度、额外回合链、主题意图与竞技环境。

详细实现和使用说明：cube_ai/docs/BRACKETS.md。旧方案保留自定义，不自动改写原牌表。

来源：
- https://magic.wizards.com/en/formats/commander
- https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-october-21-2025
- https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-february-9-2026
