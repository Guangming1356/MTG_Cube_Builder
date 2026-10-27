# MTG_Cube_Builder · 万智牌 Cube 助手

用中文界面构筑 Cube，检查费用曲线、互动、终结与指挥官支持，再用自动轮抓、组牌和 Forge AI 实战提出改进。

## 普通玩家从这里开始

1. 打开 [最新版本下载](https://github.com/Guangming1356/MTG_Cube_Builder/releases/latest)。
2. 在 **Assets** 中下载 `MTG_Cube_Builder-Windows-x64-*.zip`。
3. 完整解压后，双击 **启动Cube助手.exe**。
4. 选择玩法、Bracket 强度和偏好，生成或载入牌表。

**请下载 Windows 便携包。GitHub 自动提供的 Source code 压缩包是开发源码，不含运行环境和完整卡牌数据。**

便携包支持 Windows 10/11 64 位，内置 Python、Java、Forge 与卡牌快照，无需自行安装运行环境。离线可生成、审计、轮抓及实战；AI 服务按各用户自己的账户配置。

请通过上方“最新版本下载”获取已完成便携验收的版本。主分支可能包含后续开发代码；源码对应的依赖包校验值见 `distribution/archive.json`。

## 功能

- Commander / EDH 与传统 Cube 构筑，Bracket 1–5 和同档强度微调。
- 检查指挥官、颜色身份、角色密度、费用曲线、修色与终结手段。
- 三人 EDH：每组 15 张，每人依次取 2 张，三人取过后弃 9 张；每人抓 60 张。自选抓到的牌并自由补基本地，实战导出 60 张含指挥官。
- Forge 原生 AI 对局，保留真实引擎日志，按训练、候选选择与独立验证推进。
- 较新版本提供并行、常驻引擎、缓存、阶段计时、暂停/继续/强制结束，以及按剩余内存动态安排对局。具体功能以对应版本为准。
- 0.2 便携版提供可关闭的 Forge 模式说明兼容修复，按引擎版本隔离缓存、测速和学习；构建源码、许可证及验证范围见兼容说明。
- 0.2.1 增加经过原生解析检查的同名替代牌支持、较小内存测速配置，以及保留终结牌的实验组牌对照；详情见 [本轮优化记录](cube_ai/docs/OPTIMIZATION_20261022.md)。
- 0.2.2 改善工作区恢复、部族依赖显示和并行内存说明；个人偏好模型按特征版本与目标牌库检查后使用。角色识别研究尚未切换默认生成器，详见 [优化与实验记录](cube_ai/docs/OPTIMIZATION_20261023.md)。
- 0.2.3 修正无正文 Java 异常的胜负判定，比赛缓存和实战学习核验原始日志，历史报告同时检查牌库；旧数据保留。
- 0.2.4 将高度相近的牌池与重复牌组隔离，按来源验证实战模型，并逐轮核对测速内存预算；详情见 [来源分组说明](cube_ai/docs/CUBE_FAMILY_VALIDATION.md)。
- 0.2.5 延后加载求解库，减少主服务内存；地牌预算统计避免重复扫描。本机固定条件首次构筑约快 19.8%，完整选牌保持一致；测量范围见优化记录。
- 0.2.6 修复测速参考自身不稳定时仍可能采用配置的问题；页面显示提前停止原因，区分阻挡声明显示顺序与真实事件变化。详见 [实测与修复记录](cube_ai/docs/OPTIMIZATION_20261027.md)。
- 0.2.7 默认排除需要支付 {C} 的牌，保留普通通用费用神器和无色法术力生产者，不单设无色指挥官色组；补地时检查指挥官缺少的五色来源。详见 [偏好与实测](cube_ai/docs/OPTIMIZATION_20261027_COLOR_POLICY.md)。
- 0.2.8 修复未来再版印张导致旧牌被误排的问题；使用固定、离线的纸质发行依据，保留其他构筑限制。详见 [日期修复与验证](cube_ai/docs/OPTIMIZATION_20261027.md)。
- 可选多厂商 AI 接入；不要求配置 GPT 才能使用本地构筑功能。

## 历史版本

| 版本 | 主要变化 |
|---|---|
| [20261011](https://github.com/Guangming1356/MTG_Cube_Builder/releases/tag/v2026.10.11) | 首个 Windows 便携版本 |
| [20261015](https://github.com/Guangming1356/MTG_Cube_Builder/releases/tag/v2026.10.15) | 多服务 AI 接入版本 |
| [20261015-r2](https://github.com/Guangming1356/MTG_Cube_Builder/releases/tag/v2026.10.15-r2) | AI 接入与构筑规划修复 |
| [20261015-r3](https://github.com/Guangming1356/MTG_Cube_Builder/releases/tag/v2026.10.15-r3) | 并行实战与评估规模设置 |
| [20261015-r4](https://github.com/Guangming1356/MTG_Cube_Builder/releases/tag/v2026.10.15-r4) | 常驻 Forge、结果缓存、批量评分与实战学习 |
| [20261015-r5](https://github.com/Guangming1356/MTG_Cube_Builder/releases/tag/v2026.10.15-r5) | 候选并行比较、轮抓复用、阶段计时与机器测速 |
| [20261015-r6](https://github.com/Guangming1356/MTG_Cube_Builder/releases/tag/v2026.10.15-r6) | 暂停、继续、强制结束与任务记录 |
| [20261015-r7](https://github.com/Guangming1356/MTG_Cube_Builder/releases/tag/v2026.10.15-r7) | 按剩余内存动态安排对局、资源统计与并行上限修复 |
| [20261021 / 0.2](https://github.com/Guangming1356/MTG_Cube_Builder/releases/tag/v2026.10.21) | 完整牌库与候选内存优化、牌表分页和撤销、任务中断恢复、精确版本 Forge 兼容修复、实测资源配置与 GPU 清理 |

每个 Release 提供完整 Windows 便携包、`SHA256SUMS.txt` 和 `release-info.json`。每个标签的应用模块从对应原始便携包提取，并记录来源校验；版本历史为本次整理导入，不冒充原开发时期的 Git 提交。

## 开发者

仓库保存应用源码、知识库、文档和最新版本的测试/构建辅助工具。大型运行环境、完整卡牌快照和个人使用数据不进入 Git。

使用 Python 3.13 或 3.14：

```powershell
python -m pip install -r requirements-dev.txt
python tools/setup_dev.py --zip <下载的对应版本便携包.zip>
python -X utf8 -m cube_ai serve
python -m pytest cube_ai/tests -q
```

`setup_dev.py` 校验对应版本的压缩包，并只提取牌库及 Forge/Java 运行环境。不会导入 AI 账户、密钥、偏好、牌表或旧对局。历史标签未补写不存在的早期测试，最新标签包含当前测试集。

## 使用与评估边界

卡牌快照和 Forge 实现不保证覆盖所有新牌。Forge AI 对多人政治、组合技及控制有驾驶偏差；少量机器人胜率不等于娱乐性或人类实战强度。Bracket 是构筑体验目标；项目不认证 cEDH。

## 来源与隐私

分享包和 Git 源码不含个人 AI 配置、登录状态、密钥、原有牌表或对局历史。使用后的副本会产生本机数据；分享时使用 Releases 原始压缩包。

第三方来源、许可及完整对应源码在便携包内保留，仓库摘要见 [第三方说明](THIRD_PARTY_NOTICES.md)。本仓库的默认访问权限为私人；是否公开由仓库所有者决定。

## 维护整理

历史版本的便携包继续保留在 Releases。主分支已移除完成任务的一次性迁移工作流、迁移脚本、硬编码旧任务的排错脚本；应用模块与历史标签不受影响。开发辅助工具及重新构建所需依赖见 [工具说明](cube_ai/tools/README.md)。

## 0.2 发布与后续实测

本轮包括刷新恢复、任务结果恢复、牌表分页与撤销、空闲退出，以及轮抓、缓存和任务进程的速度/内存改进。方法、数据与边界见 [持续优化记录](cube_ai/docs/OPTIMIZATION_20261016.md)。另有均衡候选分配、长日志分析和任务状态内存优化；组牌策略已完成两组冻结对照，但未达采用门槛，默认组牌保留。可用[组牌方式对照](cube_ai/docs/DECK_POLICY_STUDY.md)和[异常复现](cube_ai/docs/NATIVE_DIAGNOSTICS.md)自行检查，重复诊断不会当作新学习样本。性能变化不等于证明新 Cube 更强。

0.2 源码回归 321 项通过，独立 Windows 便携包完成启动、离线轮抓、暂停/继续和重启恢复验收；报告见 [便携验收](docs/PORTABLE_VERIFICATION.json)。新引擎获得 698 局正常比赛，候选活动模型仍未超过原采用门槛，保留固定评分；最新方法、原生测速及发布核对见 [10 月 21 日续报](cube_ai/docs/OPTIMIZATION_20261021.md)。后续实验保持默认组牌与原有 Cube 不变。
