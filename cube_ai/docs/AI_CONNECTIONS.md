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

本次完整回归 131 项通过，其中新增连接测试 28 项。自动测试使用本地模拟接口和合成签名验证协议、密钥隔离、工具调用及结构化构筑流程。自动测试未使用真实账户或产生厂商付费请求；各账户的权限和各模型的行为需要用户在完成配置后验证。
