# 好 Cube 如何做出来：CubeCobra 案例研究

研究与检索日期：2026-10-11。资料版本：cubecobra-studies-1.0。

## 选择与证据

选取九套公开牌表，覆盖指挥官、平民、稀有度限制、无 Power 协同、新手与高强度环境。多套关注较多，但网站点赞不是质量或胜率；这不是全站排行榜、系统综述或随机抽样。JR Commander 用作不同分包规则的对照。

读取 CubeCobra 的公开简介与 CSV 导出。来源 URL、作者用户名、检索时间、原始导出 SHA-256、主牌/侧牌划分和未知牌名保存在 `data/cube_studies.json` 与 `research/cubecobra/`。仅保留主牌槽位；重复牌按物理数量统计，但每个案例对参考加分只投一次。未知牌不猜测。角色和费用指标按本地 Oracle 可识别牌计算，尤其两套 Vintage 覆盖较低，不宜跨环境直接比较。

## 核心结论

**好的 Cube 是围绕目标体验设计并迭代的有限环境。** 高牌力、颜色张数均分或热门列表都不能单独保证它好玩。以下是本项目从案例归纳的设计假设，具体密度由你的玩法约束与测试决定，未冒充作者统一推荐比例。

### 1. 体验先于牌名

先决定人数、轮抓方式、速度、强度和不喜欢的玩法，再选择卡牌。三人弃九张的轮抓需要用实际可见的牌池验证。

实现：`config.BuildSpec → draft.deal / draft_pod`。

### 2. 低费行动与后期终结同时保留

早期有生物、互动或选牌；后期有能推进胜利的威胁。费用分布不能只看平均值，也不能用高费牌数量代替终结能力。

实现：`engine.quotas / build → draft.opening_test → Forge 施放与终结记录`。

### 3. 主题要有完整的组件链

牺牲需要材料、牺牲出口和死亡回报；返场需要送墓、返场和目标。检查实际组出来的牌，不只检查整个 Cube。

实现：`design.package_report → audit / draft / optimize`。

### 4. 多用桥梁牌，避免孤立回报

优先自身好用、能连接多个宽泛思路的牌。先通过部族与禁牌过滤，再使用有限的参考加分；不为了主题名字塞进弱牌。

实现：`catalog.exclusion_reasons → design.design_bonus → engine / llm / optimize`。

### 5. 修色也要考虑速度

十个色组都有修色来源，且前几回合能顺利展开。进场横置不是一律不好，但要统计占比，并用开手和实际对局检查。

实现：`engine 土地配额 → design.fixing → draft.opening_test`。

### 6. 威胁与答案共同设计

保留高影响力威胁的同时配置互动与扫场，检查每个色组都能解场、补牌和终结。不要让绿色加速挤压其他颜色的行动。

实现：`engine 角色密度 / 色组约束 → audit → 独立轮抓`。

### 7. 牌力均衡不等于颜色张数相等

静态评价只帮助排除明显落差；真正要看各色组的可组牌率、较弱牌组、节奏与对局结果，并保留样本和失败记录。

实现：`optimize.draft_evaluation → Forge → 独立保留桌 / 交叉对局`。

### 8. 小步修改并保留证据

保存旧版，每次有限替换。参考列表提供设计经验，实战才提供行为证据；未施放不等于死牌，点赞也不等于胜率。

实现：`export_run → optimize 冻结候选 / adoption gates`。

## 九个案例与取舍

| 案例 | 主牌槽位 | 本地识别 | 地牌* | 0–2 费非地* | 6+ 费非地* |
|---|---:|---:|---:|---:|---:|
| [The Commander Cube 2024](https://cubecobra.com/cube/overview/thecommandercube) | 840 | 825 (98.2%) | 100 | 207 | 114 |
| [The Pauper Cube](https://cubecobra.com/cube/overview/thepaupercube) | 450 | 440 (97.8%) | 54 | 216 | 29 |
| [The Peasant Cube 2026](https://cubecobra.com/cube/overview/thepeasantcube) | 540 | 531 (98.3%) | 50 | 231 | 44 |
| [Bun Magic Cube](https://cubecobra.com/cube/overview/andymangold) | 360 | 355 (98.6%) | 79 | 197 | 10 |
| [MTGO Vintage Cube](https://cubecobra.com/cube/overview/modovintage) | 540 | 478 (88.5%) | 77 | 216 | 32 |
| [wtwlf123's Cube](https://cubecobra.com/cube/overview/wtwlf123) | 720 | 635 (88.2%) | 106 | 296 | 45 |
| [Beginner Micro Cube (Mostly Pauper)](https://cubecobra.com/cube/overview/5f5d4eacb1ca97104e8743be) | 180 | 180 (100.0%) | 11 | 74 | 7 |
| [Regular Cube](https://cubecobra.com/cube/overview/regular) | 454 | 452 (99.6%) | 63 | 234 | 12 |
| [JR 's Commander Cube (470 + 73 Commanders)](https://cubecobra.com/cube/overview/th2h) | 543 | 541 (99.6%) | 60 | 117 | 82 |

*数量只统计本地可识别的牌，费用采用 Oracle 法术力值；含双面牌时不等于实际施放费用。简介卡数与导出主牌数量均另行保存，不混用。

### [The Commander Cube 2024](https://cubecobra.com/cube/overview/thecommandercube)

先保证指挥官能抓到、颜色身份能组牌，再配置共享的主题组件。参考其分包思路；不采用其自定义拍档和免费非基本地规则。

作者用户名：MatEffect；当日点赞 79；未识别 15 张。

### [The Pauper Cube](https://cubecobra.com/cube/overview/thepaupercube)

常见牌也可以形成有互动、可重复游玩的环境。十个色组需要可靠的基础牌与清晰的组合方向。

作者用户名：thepaupercube；当日点赞 3402；未识别 10 张。

### [The Peasant Cube 2026](https://cubecobra.com/cube/overview/thepeasantcube)

牌应独立好用，又能服务多个主题；修色地的选择应服务套牌节奏。检查牺牲、闪现和返场的完整组件链。

作者用户名：MatEffect；当日点赞 1513；未识别 9 张。

### [Bun Magic Cube](https://cubecobra.com/cube/overview/andymangold)

低费行动、互动和选牌让早期决策有意义。接近平坦的牌力和足够修色能增加有效选择；其重复找地／圈地不复制进单例 Cube。

作者用户名：andymangold；当日点赞 1607；未识别 5 张。

### [MTGO Vintage Cube](https://cubecobra.com/cube/overview/modovintage)

通过实际牌表观察高强度环境的费用与修色组成；这是公开的 MTGO Vintage 参考副本，不能把其禁牌与快法术力带进 EDH。

作者用户名：Dekkaru；当日点赞 4054；未识别 62 张。

### [wtwlf123's Cube](https://cubecobra.com/cube/overview/wtwlf123)

对照更大的高强度牌池，检查扩容后角色密度；其牌表中的高强度牌不等于本项目允许的候选牌。

作者用户名：wtwlf123；当日点赞 1332；未识别 85 张。

### [Beginner Micro Cube (Mostly Pauper)](https://cubecobra.com/cube/overview/5f5d4eacb1ca97104e8743be)

新手环境应控制阅读负担，明确十个色组的方向；牌池大小和包数应适合实际人数，180 张配置不能直接放大成 EDH。

作者用户名：Char7；当日点赞 67；未识别 0 张。

### [Regular Cube](https://cubecobra.com/cube/overview/regular)

优先连接多个思路的桥梁牌；主题不必各自填满整副套牌。减少没有用途的规则文字，并检查五色堆强牌是否挤压其他思路。

作者用户名：anthonymattox；当日点赞 1167；未识别 2 张。

### [JR 's Commander Cube (470 + 73 Commanders)](https://cubecobra.com/cube/overview/th2h)

指挥官分包与每次拿两张是玩法的一部分。两色的互补主题可以汇成三色思路；这套作为规则对照，不作为热门质量标杆。

作者用户名：Djr067；当日点赞 1；未识别 2 张。

## 对三人 600 张 EDH 的实际采用

- 保留既定 90 个指挥官槽、70 个地槽、440 个主牌槽与第二版风格的低费曲线：0–1 / 2 / 3 / 4 / 5+ 为 54 / 156 / 94 / 61 / 75。主牌至少 9% 为 6+ 费；终结另有角色密度要求。这些是项目当前参数，不是 CubeCobra 推荐公式。
- 先过滤禁牌、快法术力、部族依赖与其他限制。同玩法参考成员获得每个案例 0.04、总计最高 0.08 的弱先验；能支持多个适用宽主题且有独立作用的牌，桥梁加分最高 0.04。Vintage 参考不给默认 EDH/传统构筑加分。新牌未出现过不会被扣分。
- 不复制自定义单色拍档、免费 Command Tower、重复找地、部族或无限组合。指挥官获取按本项目的分包规则验证。
- 对各色可用牌和实际最终组牌，列出牺牲材料/出口/回报、送墓/返场/目标；缺口是诊断提示，不把正则识别冒充完整规则结算。实际组件缺口作为新版 Forge 反馈策略的有限选牌信号，不改写之前实战报告的分数。
- 互动、扫场、终结、颜色平均评价差等仍用整数规划及独立审计验收。颜色是否真平衡必须通过保留轮抓桌与 Forge 对局检查。
- 所有新版另存；研究融入构筑路径不等于对基础模型做了训练，也不能证明新版本的实战胜率提高。

## 更新与复现

技术用户从项目根目录执行 `python -m cube_ai.research.fetch_cube_studies`（默认复用快照），再执行 `python -m cube_ai.research.analyze_cube_studies` 和 `python -m cube_ai.research.write_study_report`。要重新抓取，应先另存旧快照，再刷新对应案例；不要将旧测试结果套到新的资料版本。离线构筑无需访问网站。

## 补充交叉核对

平民 Cube 的定位与维护方式另核对了作者网站 [The Pauper Cube](https://thepaupercube.com/)；Bun Magic 的轮抓思路核对了创作者节目 [Lucky Paper Radio 167](https://luckypaper.co/podcast/167-bun-magic-cube-draft-primer/)。上述数值均来自当日 CubeCobra 导出，非这些网页的统计。
