# CubeCobra 设计学习：有来源的 Cube 构筑路径

资料版本 cubecobra-studies-1.0；2026-10-11 检索九个目的性案例。点赞不等于质量；不同玩法的曲线和牌力不直接迁移到三人 EDH。

## 体验先于牌名

先决定人数、轮抓方式、速度、强度和不喜欢的玩法，再选择卡牌。三人弃九张的轮抓需要用实际可见的牌池验证。

config.BuildSpec → draft.deal / draft_pod

## 低费行动与后期终结同时保留

早期有生物、互动或选牌；后期有能推进胜利的威胁。费用分布不能只看平均值，也不能用高费牌数量代替终结能力。

engine.quotas / build → draft.opening_test → Forge 施放与终结记录

## 主题要有完整的组件链

牺牲需要材料、牺牲出口和死亡回报；返场需要送墓、返场和目标。检查实际组出来的牌，不只检查整个 Cube。

design.package_report → audit / draft / optimize

## 多用桥梁牌，避免孤立回报

优先自身好用、能连接多个宽泛思路的牌。先通过部族与禁牌过滤，再使用有限的参考加分；不为了主题名字塞进弱牌。

catalog.exclusion_reasons → design.design_bonus → engine / llm / optimize

## 修色也要考虑速度

十个色组都有修色来源，且前几回合能顺利展开。进场横置不是一律不好，但要统计占比，并用开手和实际对局检查。

engine 土地配额 → design.fixing → draft.opening_test

## 威胁与答案共同设计

保留高影响力威胁的同时配置互动与扫场，检查每个色组都能解场、补牌和终结。不要让绿色加速挤压其他颜色的行动。

engine 角色密度 / 色组约束 → audit → 独立轮抓

## 牌力均衡不等于颜色张数相等

静态评价只帮助排除明显落差；真正要看各色组的可组牌率、较弱牌组、节奏与对局结果，并保留样本和失败记录。

optimize.draft_evaluation → Forge → 独立保留桌 / 交叉对局

## 小步修改并保留证据

保存旧版，每次有限替换。参考列表提供设计经验，实战才提供行为证据；未施放不等于死牌，点赞也不等于胜率。

export_run → optimize 冻结候选 / adoption gates

## The Commander Cube 2024

先保证指挥官能抓到、颜色身份能组牌，再配置共享的主题组件。参考其分包思路；不采用其自定义拍档和免费非基本地规则。 来源：https://cubecobra.com/cube/overview/thecommandercube

## The Pauper Cube

常见牌也可以形成有互动、可重复游玩的环境。十个色组需要可靠的基础牌与清晰的组合方向。 来源：https://cubecobra.com/cube/overview/thepaupercube

## The Peasant Cube 2026

牌应独立好用，又能服务多个主题；修色地的选择应服务套牌节奏。检查牺牲、闪现和返场的完整组件链。 来源：https://cubecobra.com/cube/overview/thepeasantcube

## Bun Magic Cube

低费行动、互动和选牌让早期决策有意义。接近平坦的牌力和足够修色能增加有效选择；其重复找地／圈地不复制进单例 Cube。 来源：https://cubecobra.com/cube/overview/andymangold

## MTGO Vintage Cube

通过实际牌表观察高强度环境的费用与修色组成；这是公开的 MTGO Vintage 参考副本，不能把其禁牌与快法术力带进 EDH。 来源：https://cubecobra.com/cube/overview/modovintage

## wtwlf123's Cube

对照更大的高强度牌池，检查扩容后角色密度；其牌表中的高强度牌不等于本项目允许的候选牌。 来源：https://cubecobra.com/cube/overview/wtwlf123

## Beginner Micro Cube (Mostly Pauper)

新手环境应控制阅读负担，明确十个色组的方向；牌池大小和包数应适合实际人数，180 张配置不能直接放大成 EDH。 来源：https://cubecobra.com/cube/overview/5f5d4eacb1ca97104e8743be

## Regular Cube

优先连接多个思路的桥梁牌；主题不必各自填满整副套牌。减少没有用途的规则文字，并检查五色堆强牌是否挤压其他思路。 来源：https://cubecobra.com/cube/overview/regular

## JR 's Commander Cube (470 + 73 Commanders)

指挥官分包与每次拿两张是玩法的一部分。两色的互补主题可以汇成三色思路；这套作为规则对照，不作为热门质量标杆。 来源：https://cubecobra.com/cube/overview/th2h

## 组件与验证

牺牲：材料 / 出口 / 死亡回报。返场：送墓 / 返场 / 合适目标。闪现：闪现效果 / 有用的进场效果。资源与回报分别计数，既看整个 Cube，也看最终 60 张牌组。未抓到的支持不算配合。缺失组件先检查 Oracle，不凭正则直接判牌弱。

实现：合法性过滤 → 同玩法弱参考先验（最高 .08）与桥梁加分（最高 .04）→ 曲线、颜色、角色约束 → 组件链审计 → 三人弃九张规则轮抓 → 实际入组检查 → 原生 Forge 对局行为 → 小步替换 → 独立保留轮抓和交叉对局。

不复制 Vintage 禁牌、重复找地、自定义拍档和免费非基本地。先满足玩家限制。经验是可复核的假设，不是实战标签，也不宣称训练出胜过通用 GPT 的模型。