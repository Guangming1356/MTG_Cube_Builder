# MTG_Cube_Builder · 万智牌 Cube 助手

用中文界面构筑 Cube，检查费用曲线、互动、终结与指挥官支持，再用自动轮抓、组牌和 Forge AI 实战提出改进。

## 普通玩家从这里开始

1. 打开 [最新版本下载](https://github.com/Guangming1356/MTG_Cube_Builder/releases/latest)。
2. 在 **Assets** 中下载 `MTG_Cube_Builder-Windows-x64-*.zip`。
3. 完整解压后，双击 **启动Cube助手.exe**。
4. 选择玩法、Bracket 强度和偏好，生成或载入牌表。

**请下载 Windows 便携包。GitHub 自动提供的 Source code 压缩包是开发源码，不含运行环境和完整卡牌数据。**

便携包支持 Windows 10/11 64 位，内置 Python、Java、Forge 与卡牌快照，无需自行安装运行环境。离线可生成、审计、轮抓及实战；AI 服务按各用户自己的账户配置。

推荐最新的 **v2026.10.15-r7**。本标签对应的应用快照为 **20261015-r6**。

## 功能

- Commander / EDH 与传统 Cube 构筑，Bracket 1–5 和同档强度微调。
- 检查指挥官、颜色身份、角色密度、费用曲线、修色与终结手段。
- 三人 EDH：每组 15 张，每人依次取 2 张，三人取过后弃 9 张；每人抓 60 张。自选抓到的牌并自由补基本地，实战导出 60 张含指挥官。
- Forge 原生 AI 对局，保留真实引擎日志，按训练、候选选择与独立验证推进。
- 较新版本提供并行、常驻引擎、缓存、阶段计时、暂停/继续/强制结束，以及按剩余内存动态安排对局。具体功能以对应版本为准。
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
