# 连接 AI

核验日期：2026-10-15。离线构筑、审计、轮抓和 Forge 不需要连接 AI。

## 只有 ChatGPT Plus 怎么用

OpenAI 当前提供 **Sign in with ChatGPT** 的套餐使用通道：符合资格的 Plus / Pro 用户可以向参与应用授权使用套餐额度。本项目按官方开源客户端流程实现了此选项。它仍处于预览，账户、工作空间和地区权限以官方授权及接口返回为准，项目不能保证每个 Plus 账户都能开通。

1. 打开左侧 **AI 设置**，选择 **ChatGPT 会员登录（官方预览）**。
2. 点击 **Continue with ChatGPT**，在系统浏览器中的 OpenAI 官方页面完成登录及授权。
3. 返回助手，点击 **读取模型列表**，选择账户可用的模型。
4. 点击 **保存并使用**，然后可进入 **AI 顾问**。

已有账户可以重新登录、切换或退出，也能添加另一个账户 / 工作空间。切换账户后重新读取其模型列表。只有身份登录、没有授予套餐使用权限时，AI 顾问不会启用。

套餐通道有用量限制，并与其他使用该通道的应用共享额度。额度耗尽会提示重试或手动切换服务，**不会自动改用付费 API**。Plus 会员也不等于普通 OpenAI API 的充值余额。

官方来源：[快速开始](https://developers.openai.com/siwc/quickstart)、[开源应用注册与登录](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)、[模型与推理](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)、[预览限制](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)。

## 其他选择

| 选择 | 需要准备什么 | 说明 |
| --- | --- | --- |
| OpenAI API | 平台 API Key、可用模型 | API 单独计费，不消耗上述会员授权通道 |
| DeepSeek | DeepSeek 开放平台密钥 | 预设官方兼容地址，默认非思考模式 |
| 通义千问 | 阿里云百炼密钥 | 默认北京地址；密钥地域和工作空间地址应一致 |
| Gemini | Google AI Studio API Key | 使用官方 OpenAI 兼容接口 |
| Ollama | 已安装 Ollama、已下载模型 | 本地运行，无需 API Key；模型须支持工具调用和 JSON 输出 |
| 其他兼容服务 | 兼容地址、密钥和模型 | 支持 Chat Completions / Responses，可调整 JSON 输出方式 |

选择服务，填写密钥并保存，然后读取模型或手动填写模型名称。**测试连接**会发送一次小请求，消耗套餐或 API 额度；它检查连通性及 JSON 输出，工具调用能力还需实际顾问请求验证。不同厂商的计费、赠送额度及地区可用性以平台为准。

兼容性不等于所有模型都能使用。顾问需要工具调用与可靠的结构化输出。若模型返回无效 JSON、请求中断或输出截断，助手会显示错误。修改“兼容设置”不会绕过本地卡名及构筑检查。

官方来源：[DeepSeek](https://api-docs.deepseek.com/)、[千问兼容接口](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)、[Gemini 兼容接口](https://ai.google.dev/gemini-api/docs/openai)、[Ollama 兼容接口](https://docs.ollama.com/api/openai-compatibility)。预设模型名称不保证永久可用，可读取账户模型列表或按厂商说明修改。

## 保存、分享与数据发送

- 不再需要修改配置文件或重启；保存后新发起的任务使用新设置。已经开始的任务继续使用提交时选定的服务。
- 每个服务分别保存密钥，不借用其他厂商的密钥。更换接口地址后需要重新填写密钥。
- Windows 使用当前系统账户的 DPAPI 加密，文件位于 `cube_ai/private/ai-settings.bin`；其他系统使用仅当前用户可读写的文件权限。该目录不在网页下载范围内。
- 传给模型的内容包括用户需求、当前牌表、构筑参数及查询所得的卡牌 / 知识片段。密钥、授权码和登录令牌不放入模型提示词、网页状态或导出牌表。
- 分享请使用新构建的干净发布包，不要把自己已经登录的整个工作目录发给别人。发布脚本排除 `private`、`.env`、历史牌表、偏好库和对局记录。
- 退出 ChatGPT 会尝试向官方撤销会话，并清除本机令牌。如果网络不通，界面会说明远端撤销未确认，可在 ChatGPT 设置中断开应用。账户标签和注册编号保留以便重新登录。

## 实现与验证范围

会员通道使用官方 OAuth + PKCE、一次性 state / nonce、JWKS 身份签名验证、可轮换的刷新令牌以及公开 Responses SSE 接口。没有读取 ChatGPT 浏览器 Cookie、Codex 会话或第三方中转账号。

本次完整回归 183 项通过，包含连接测试 28 项和流式输出回归 16 项。自动测试使用本地模拟接口和合成签名验证协议、密钥隔离、工具调用及结构化构筑流程，不使用用户的真实登录或外网接口。

2026-10-15 已另行用 ChatGPT 会员通道的 gpt-6.1-sol 验证三类真实请求：600 张 Commander / Bracket 3 参数规划、360 张传统 Cube 参数规划，以及实际调用 lookup_card 查询 Sun Titan 和 Swords to Plowshares。其他厂商尚未逐一进行真实调用验证。

### r2 修复说明

修复“模型没有返回完整可用的构筑规划”：该通道可能在结束通知中返回空的 output 数组，实际正文和工具调用已经通过前面的完整输出项事件送达。现在会保留并按顺序组装这些输出，保留后续查牌需要的推理与工具调用信息；仍须收到成功结束事件才接受结果。空回复、截断、拒绝及 JSON 格式不完整会分别提示具体原因。


### r3 调试与可执行偏好

“多交互、更多扫场、加强终结、低费优先”现在会转换成真正参与选牌的参数。可在详细设置中调整互动、扫场和终结的主牌最低占比，以及均衡、低费、后期三种曲线。精确 curve 非空时优先于曲线风格；无法落实的要求会单独显示。

规划现在覆盖预算、年份、系列、色组主题与轮抓规则；切换玩法保留共同偏好并重置玩法相关默认值。替换应用前会重新检查整套牌，保存记录使用独立名称。损坏的牌库缓存会重建；AI 配置读取失败不会禁用离线功能，可在 AI 设置中备份并重置连接配置。

本次还验证了 8 个核心真实 AI 场景、额外的完整网页流程与预算保留检查、三种实际构筑、10 桌轮抓和 3 局 Forge 对局。范围和限制见 [本轮调试报告](DEBUG_REPORT.md)。
