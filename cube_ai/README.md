# Cube Atelier

专用于万智牌 Cube 的本地 AI 构筑工作台。已接入真实卡牌快照和 `magic-skill`；支持构筑审计，以及“轮抓牌组 → Forge 实战 → 数据反馈替换 → 独立对比”的自动改进流程。人工偏好是可选输入。

## 立即使用

**双击桌面或 `本项目文件夹` 文件夹里的「万智牌 Cube 助手」快捷方式。** 后台会自动启动，网页自动打开；下次打开会复用本项目服务。不需要输入命令或配置 GPT。

首页三步：生成或打开牌表 → 检查轮抓与实战 → 下载、游玩并继续改进。原有版本保留；未通过全部测试的实验候选会明确标注。关闭网页即可，下次双击继续。

开始前可阅读项目根目录的 [先看这里](../先看这里.txt)。学习依据见 [九套 CubeCobra 案例研究](research/CUBECobra_DESIGN.md) 、[新增网站资料](research/MULTI_SITE_DESIGN.md) 与 [实现路径](docs/DESIGN_PATH.md)；网页中也有「好 Cube 怎么做」。

### 技术启动与移动项目

快捷方式针对这台电脑的项目位置。移动整个项目或更换 Python 后，在新项目目录重新运行 `cube_ai/install_shortcuts.ps1`。它仅建立快捷方式，不修改系统权限。依赖准备完毕后可用 `python -X utf8 -m cube_ai.launcher` 打开工作台；`--no-browser` 仅启动/检测后台，用于排查。入口日志在 `cube_ai/runtime/launcher.log`。

如需前台终端运行，在本项目目录 `本项目文件夹` 执行：

```powershell
.\cube_ai\start.ps1
```

打开 **http://127.0.0.1:8765**。若本机已经运行服务，直接打开即可。停止时在启动终端按 Ctrl+C。需要换端口：

```powershell
python -X utf8 -m cube_ai serve --port 8766
```

便携包自带运行环境。源码开发使用已验证的 Python 3.13 / 3.14、NumPy、SciPy、requests；测试使用 pytest。缺依赖时：

```powershell
python -m pip install -r cube_ai/requirements.txt
```

### 操作流程

1. **构筑方案**：选择 Commander 或传统 Cube，设置张数、槽位、保留和排除牌。高级 JSON 可修改系列、价格、主题和曲线。点击生成。
2. **旧牌表**：选择本项目已有的 Cube，或上传 CSV/TXT；先载入审计，再点击“改进当前牌表”。修复会尽量保留原有牌，另存新结果。
3. **牌表与替换**：按颜色/槽位筛选；查看真实 Oracle，寻找同身份、同槽位、主牌同费用档的替换。应用后重新审计，点击“保存为新版本”持久保存，导出 CSV/JSON 保留槽位。当前牌表在此浏览器保留，刷新后会重新审计并恢复；点击保存或下载完整备份，才能在其他浏览器或电脑继续。
4. **诊断与轮抓**：查看曲线、互动、扫场、终结、色组支持；运行模拟轮抓。示例组牌和抓牌包可追溯。
5. **AI 顾问**：在 AI 设置完成连接后，可把中文需求转换为参数，或让顾问查牌、检索技能、审计和提出经验证的替换。
6. **偏好学习**：至少 8 次人工比较后训练本地排序模型。记录应来自你真实的判断或游玩；不会自动给旧版本标“正确”。
7. **用实战数据改进 Cube**：在“检查与实战改进”选择快速排错、标准改进或深入评估。默认标准档训练 30 桌，开发比较 200 桌，新旧各 30 桌独立原生对局，另做独立结构检查与交叉对局；页面会展示完整预算。快速档只排错，不能据此确认更强。结果另存版本；未通过门槛标为实验候选，不自动替换原版。

命令行可重复运行同样流程，默认全自动，不需要人工评牌：

```powershell
python -X utf8 -m cube_ai forge-optimize --file cube_ai/runs/你的版本/cube.csv --spec cube_ai/runs/你的版本/spec.json --workers 3 --clock 120 --training-pods 10 --output cube_ai/data/optimization.json
```

数据、种子、前后牌表、替换原因、真实对局与决策报告位于 `cube_ai/optimizations/<id>/`。已有结果在“已有改进记录”中打开。详细方法见 [实战反馈改进](docs/FEEDBACK_LOOP.md)。

生成结果位于 `cube_ai/runs/<run_id>/`，包括 CSV、CubeCobra TXT、完整 JSON、参数、报告；轮抓测试会写入同目录的 `stress.json`。UTC 时间用于记录目录名。

## AI 接入

打开网页左侧 **AI 设置**，选择服务后保存即可，无需修改文件或重启：

- **ChatGPT 会员登录（官方预览）**：符合资格的 Plus / Pro 账户可通过官方授权使用套餐额度。完成登录后读取账户模型列表并选择模型；是否可用以官方权限为准。
- **OpenAI API、DeepSeek、通义千问、Gemini**：分别填写各平台的 API Key，按各厂商规则计费。
- **Ollama 本地模型**：需要另行安装及下载支持工具调用的模型，无需 API Key。
- **其他兼容服务**：可填写自己的兼容 API 地址，调整接口和 JSON 输出方式。

密钥按服务分开保存，Windows 使用系统账户加密。额度用尽不会自动改用收费接口。离线构筑、审计与 Forge 不需要连接 AI。详细步骤、官方来源、隐私与验证范围见 [连接 AI](docs/AI_CONNECTIONS.md)。

旧的 `.env` / 环境变量仍可作为首次 OpenAI 配置的后备；保存网页设置后，优先使用网页中的选择。ChatGPT 会员通道已进行真实请求与完整流程验证；其他服务商仍未逐一实测。自动回归与真实调用分开记录，详见 [本轮调试报告](docs/DEBUG_REPORT.md)。

## 默认 Commander 构筑

首页默认选择 Bracket 3；下列是基础配额，Bracket、曲线与高级参数会影响实际限制。最终以导出参数和审计报告为准。Game Changers 等规则见 [Bracket 说明](docs/BRACKETS.md)。

- 600 张单卡唯一：90 个指定指挥官槽位、70 地、440 主牌；主牌中的传奇生物仍可作为指挥官。
- 主牌颜色：五单色各 59、十双色各 9、无色 55。指挥官按单色、双色和三色覆盖。
- 主牌费用档：1 费及以下 54；2 费 156；3 费 94；4 费 61；5 费及以上 75。另有 6 费及以上保底。
- 生物、互动、扫场、抓牌、加速、终结各有密度约束；加速设上限，五单色和十双色各自的平均启发式评价差限制为 0.32。
- 排除赛制不合法牌、数字牌、部族依赖、指定牌名窄组件、合体结果面、未配置额外牌堆的 Attraction/贴纸/机关牌。Game Changers、快法术力、额外回合、法术力封锁和已列出的无限组合按所选 Bracket 与开关限制；不能把旧自定义预设的排除规则当作所有档位的统一规则。
- 十双色采用可交叉使用的主题，如墓地、牺牲、神器、非生物咒语、战斗、衍生物等，检查资源与回报的供给。

**上述牌力、角色和协同来自可解释启发式，不能保证所有卡牌语义被正确识别。** 复杂条件、无限组合和“虽不部族但很窄”的回报仍可能漏检，实际体验需要玩家反馈。启发式分数相近也不等于色组胜率相同。

### 你的三人轮抓规则

默认开 30 包，分 10 轮、每轮三人各一包。每包 15 张，每人见到该包取 2 张，传过三人后弃 9 张；每人最终 60 张。开包 450 张，实际被拿走 180 张。

为提高可组牌性，**工具额外采用配包约定**：每包 3 个指定指挥官槽、1 地、1 张 6 费及以上主牌，其余 10 张主牌。该配包约定可在 `draft.deal` 修改，不是用户规则原本强制要求。60 张套牌包含指挥官，基本地另行提供；这是 Commander Draft 家规，不能等同普通 EDH 的 100 张构筑。

**抓牌池与套牌分开计算**：每人抓完 60 张后，可以选用其中任意数量的牌，自由加入任意数量基本地，组成至少 60 张的套牌。当前机器人为便于比较，选择恰好 60 张（含指挥官）；按曲线及低费加速估算地数，非地牌不足时可以多补基本地，不再要求固定 22 地或必须抓到 37 张合色咒语。地过多的合法套牌另列构筑警告。

## 自动实战：Forge

已经接入 **Forge 官方命令行 AI 自战**，无需人工驾驶、无需 GPT 密钥。工作台「检查与实战改进」中的「三人实战模拟」可运行完整规则引擎对局、查看历史报告、下载三副牌及逐局日志。

```powershell
# 当前项目已经安装；迁移到另一台 Windows 机器时才需执行
python -X utf8 -m cube_ai forge-setup
python -X utf8 -m cube_ai forge-status
python -X utf8 -m cube_ai forge-test --file cube_ai/runs/20261011_062614_d09d78bb/cube.csv --spec cube_ai/profiles/commander600.json --pods 2 --games-per-pod 3 --clock 90 --output cube_ai/data/forge_evaluation.json
```

运行链：同桌轮抓 → 三人各自选牌并补基本地 → `.dck` 导出 → Forge Commander 规则、40 点生命 → 每三局轮换一次座位 → 实际胜者、回合数与原始日志。回合数统计 `Turn: Turn` 中的全局玩家回合，不等于每位玩家都行动一次的大轮。记录 Cube 哈希、JAR 哈希、牌组哈希、抓牌种子、Forge `-s` 种子及完整命令。

Forge 2.0.15 和 Temurin Java 21 从官方 GitHub 发布包下载，经 SHA256 校验后安装在 `cube_ai/runtime`，不会改系统 Java 或已有 Forge 配置。当前安装包在程序日志中自报 `2.0.15-SNAPSHOT-09.28`；发行标签为 `forge-2.0.15`。第三方运行时的许可证随原包保留（Forge GPL-3.0-or-later、Temurin OpenJDK 许可证），对应源代码可从官方发行页取得。本项目通过子进程调用引擎，原 JAR 保留。0.2 便携版另含可关闭、按精确哈希验证的模式说明兼容组件及完整对应源码，范围和已知边界见 [兼容修复说明](docs/FORGE_COMPATIBILITY.md)。其它系统或自有安装可用 `.env` 的 `CUBE_FORGE_HOME`、`CUBE_FORGE_JAVA` 配置。

牌张脚本覆盖在运行前检查。未实现牌明确列出；若被组入任一牌组，跳过整桌，保留失败原因及实际抓牌池，不偷换牌或拼接其它桌。引擎报错、引擎时限、进程超时、正常和局分别记录；前三者不进入正常胜率统计。证据保存在 `cube_ai/matches/<id>`，与原 Cube 文件独立。

初次验收完成 **2 桌、6 局三人自战，6 局均正常分出胜负**，详见 [Forge 实测](docs/FORGE.md)。随后实战反馈实验另外执行 **69 局**，结果与保留候选的理由见 [数据反馈改进](docs/FEEDBACK_LOOP.md)。目前由 Forge 原生启发式 AI 负责每一步操作，GPT 不参与驾驶。原生 AI 对控制、组合技和多人政治有偏差；自动实战能发现组牌、节奏、终结和色组失衡线索，小样本不能证明平衡或娱乐性。人工反馈是可选的口味信息，不是运行模拟的前提。

轮抓机器人起始偏好随机双色，按颜色、曲线和启发式选牌，最后可以选择已抓到的其他指挥官。统计中的色组是**起始偏好**，不一定是最终套牌颜色。起手测试只看手中咒语与抽到地牌的法术力是否匹配，不执行牌效、不移除已打出牌、不考虑横置地/条件产费/调度/政治互动。不能解释成“每回合必有行动”或胜率。

## 调整与复用

预设文件：`profiles/commander600.json`、`profiles/classic360.json`。可复制为新环境；可调整字段见 `config.BuildSpec`。主题名、双色身份采用内部排序，如蓝黑 `BU`、红蓝 `RU`。

```powershell
python -X utf8 -m cube_ai build --spec cube_ai/profiles/commander600.json --output cube_ai/data/result.json
python -X utf8 -m cube_ai analyze --spec cube_ai/profiles/commander600.json --file 你的牌表.csv --output cube_ai/data/audit.json
python -X utf8 -m cube_ai repair --spec cube_ai/profiles/commander600.json --file 你的牌表.csv --output cube_ai/data/repaired.json
python -X utf8 -m cube_ai stress --spec cube_ai/profiles/commander600.json --file 生成目录/cube.csv --trials 100 --output cube_ai/data/stress.json
```

自定义 `curve` 键为 `1,2,3,4,5+`，合计必须等于主牌槽数。过滤太窄、锁定牌冲突或指挥官槽位不足时会失败，不会静默放宽。`max_card_price` 为单卡美元价格上限，缺价格的牌会被排除；不是整套价格上限。系列/年份过滤使用当前快照的代表印张，不代表所有再版或首次印刷年份。

### 数据更新与移植

当前使用 `commander_cube_600_v4/research/card_pool.json`，31,070 张，快照 **2026-10-08**。本地构筑不查询当天禁牌变更，也不保证包含刚发布的牌。下载 [Scryfall Bulk Data](https://scryfall.com/docs/api/bulk-data) 后导入：

```powershell
python -X utf8 -m cube_ai.import_catalog 下载的oracle-cards.jsonl.gz --snapshot-date 2026-10-11
```

请填文件真实的快照日期。导入器接受 JSON 数组、JSONL、gzip JSONL、已有项目格式，写入 `cube_ai/data/card_pool.json`；重启服务重建特征缓存。也可设置 `CUBE_CARD_POOL` 指向项目格式的其他快照。

迁移到别的项目时复制 `cube_ai`，按上面方法提供快照，安装依赖即可运行。`magic-skill` 为可选知识扩充；缺少时仍能使用自带 `knowledge/cube-design.md`。跨机器/不同求解器版本可能得到不同但符合相同约束的牌表，运行记录保留数据签名、种子和特征版本。

## 评测与依据

```powershell
python -X utf8 -m pytest cube_ai/tests -q
python -X utf8 -m cube_ai.evaluate --output cube_ai/evaluation
# 配好 API 后：两次模型调用，会产生 API 费用
python -X utf8 -m cube_ai.evaluate --live --spec cube_ai/profiles/commander600.json --output cube_ai/evaluation/live42
```

[调研](research/RESEARCH.md) · [架构](ARCHITECTURE.md) · [已执行评测及其限制](EVALUATION.md)

本项目的特异性来自真实牌库、领域知识、约束求解、检验和可学习偏好；基础 GPT 没有经过本项目微调。已执行的流行度基线不是通用 AI。与通用 GPT 的比较脚本使用相同模型、输入卡池和一次调用预算，但专用系统另有领域知识与求解器修复；比较的是完整系统。最终质量需要多种子盲评与真实游玩确认。

## Commander Bracket 强度选项

首页支持 1–5 档及同档强度微调；详细设置还能调整指挥官与整个 Cube 的 Game Changer 预算。推荐 3 档娱乐轮抓；5 档为实验竞技目标，不认证 cEDH。完整规则与用法见 [强度设置说明](docs/BRACKETS.md)。


## 可执行的构筑偏好

详细设置现在可调整主牌互动、扫场与终结的最低占比，以及“均衡 / 低费行动更多 / 后期咒语更多”曲线。AI 的规划会直接填写这些字段；无法落实的要求会单独列出。生成器、审计和替换检查共同使用这些约束。

## 并行实战与评估规模

“检查与实战改进”支持自动安排同时对局数、快速/标准/深入三档评估，以及每轮最多10/24/48/60张替换。组好一桌就开始对局；标准档训练30桌，新旧独立测试各30桌，每桌3局，另做交叉验证。替换数是上限，样本不足或区间不支持时保留实验候选。详见 [并行与评估说明](docs/PARALLEL_EVALUATION.md)。

## 常驻引擎、GPU与实战学习

Forge 常驻进程已通过同种子游戏事件对照，默认复用牌库并有界并行。结构评估和相同比赛结果支持版本化缓存；候选批量评分自动比较CPU/GPU速度。专用行为模型从实战学习，并与简单基准做独立验证，合格后才用于下一轮。详见 [速度与学习验收](docs/SPEED_REPORT.md)。

## 动态安排内存与对局数

自动模式会持续检查剩余内存，逐步调整新开局数量；训练、独立验证、交叉对局都遵循原来的自动选择。已有引擎占用不再重复扣算，内存压力下只回收多余的空闲引擎。完整比赛与种子不变，报告单列新执行正常局数、复用数和主动暂停时间。详见 [动态资源说明](docs/DYNAMIC_RESOURCES.md)。

## 2026-10-16 优化

当前开发版为 0.2，进度与证据见 [优化记录](docs/OPTIMIZATION_20261016.md)。新任务的结果可在重启后找回，页面支持工作区恢复、分页、撤销和空闲退出。

## 当前版本与实测

[0.2 / v2026.10.21](https://github.com/Guangming1356/MTG_Cube_Builder/releases/tag/v2026.10.21) 已完成独立 Windows 便携验收。包括任务中断记录恢复、结果按需读取、牌表分页/撤销、空闲退出、缓存与进程内存优化、按本机实测选择 CPU/GPU 和对局配置。具体测量与边界见 [2026-10-16 记录](docs/OPTIMIZATION_20261016.md) 与 [2026-10-21 续报](docs/OPTIMIZATION_20261021.md)。

698 局正常比赛上的新活动模型未达到采用门槛，当前仍使用固定评分；性能提高不等于 Cube 实战强度或人类娱乐性已经提高。正在进行的新组牌实验与已发布版本分开记录，未自动改动默认组牌。
