# agent-trending-daily 产品与技术规格

## 1. 项目目标

每天北京时间 09:00 获取 GitHub Trending Daily 全语言页面当天返回的全部仓库，筛选
与 Agent 应用生态相关的项目，生成可公开的中文 Markdown 研究简报并由 GitHub
Actions 直接提交到默认分支。

入选数量允许为 0 到当天候选总数，不从页面之外补足。每个结论必须能追溯到 GitHub
原始数据、确定性规则、人工名单和（如有）Qwen 结构化判定。任一必要步骤失败时不得
发布不完整结果，同日成功重跑原子覆盖已有文件。

## 2. 范围

纳入 Agent 应用、框架与编排、LLM 应用 SDK、MCP、工具调用、RAG、知识检索、
Agent Memory、应用评测与可观测性、Prompt/Context Engineering 和面向 Agent 的开发
基础设施。

排除以模型训练、预训练、微调、推理引擎、量化、Serving 或部署为主要目标的项目，
与 Agent 应用无直接关系的通用 AI 项目，以及没有 Agent 应用实现价值的文章、论文或
资源集合。首版不包含网页看板、消息推送、数据库、多模型提供方或历史榜单回填。

## 3. 判定与数据流

1. 请求 `https://github.com/trending?since=daily` 并按页面顺序解析当天返回的全部仓库；
   只有页面没有仓库卡片或任一卡片结构不完整时才失败。
2. 使用 GitHub REST API 补充描述、Topics、主语言、总 Star、Fork、License 和 README。
3. `denylist` 强制排除，`allowlist` 强制纳入；名单冲突属于配置错误。名单只能作用于
   当天页面实际返回的候选，不能引入页面之外的项目。
4. 使用仓库名、描述、Topics 和 README 前 12,000 个字符匹配版本化词表。没有任何
   Agent 应用信号的项目由规则排除，其余项目逐个交给 Qwen 判断主要用途。
5. 对所有入选项目生成中文摘要、相关理由、分类和 1–3 条亮点。
6. 从历史 JSON 快照计算首次上榜日期；只有前一自然日也入选时才增加连续上榜天数。
7. 完整校验 JSON 与 Markdown 后一次性发布。零入选属于有效日报。

README 等外部文本是不可执行、不可信的引用数据。提示词必须禁止遵循其中的指令，
模型不得生成输入证据无法支持的事实。

## 4. LLM 契约

- Provider：阿里云百炼华北 2（北京）
- Model：`qwen3.7-plus`
- API：OpenAI-compatible Chat Completions
- Base URL：`https://${DASHSCOPE_WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`
- 配置：`DASHSCOPE_API_KEY`、`DASHSCOPE_WORKSPACE_ID`

所有模型调用使用原生 JSON Schema Structured Outputs：`type=json_schema`、
`strict=true`、`additionalProperties=false`，且不设置 `max_tokens`。先用封闭的
`RelevanceDecision` 契约只判定相关性；仅对入选项目再用封闭的 `ProjectBrief` 生成
分类与简报，二者确定性合成为 `RelevanceAnalysis`。每次返回后都执行
`model_validate_json(..., strict=True)` 和业务校验。

入选项目必须包含非空摘要、理由和 1–3 条亮点；排除项目由程序确定性归一为
`out_of_scope` 且不调用简报模型；分类与标签必须来自配置枚举。简报文本必须是无
Markdown 标记、列表符号和换行的完整纯文本，摘要、理由和单条亮点分别限制为 220、
180 和 120 字。失败时最多调用三次，重试请求只增加精简校验反馈。禁止以 JSON Mode、
Prompt-only JSON、手工截取或 `json_repair` 降级。

## 5. 公开接口与产物

CLI：

- `agent-trending run`：执行当前日期的完整流程并发布。
- `agent-trending run --dry-run`：完成抓取、模型调用、构建和校验，但不写正式产物。
- `agent-trending validate-config`：校验配置、人工名单及必要环境变量。
- `agent-trending render data/YYYY-MM-DD.json`：仅从已验证快照重新生成 Markdown。

不提供历史日期参数，因为 Trending 页面不能按任意日期回溯。

`data/YYYY-MM-DD.json` 永久保存 schema 版本、北京时间运行信息、来源、模型、当天
全部候选的排名和 GitHub 元数据、README 哈希、规则证据、人工/LLM/最终判定及历史
统计；不保存完整 README。

`reports/YYYY-MM-DD.md` 展示入选项目的原始排名、链接、原始描述、中文摘要、分类、
相关理由、亮点、语言、总/当日 Star、Fork、License 和上榜历史。
`reports/latest.md` 与当日日报内容相同。零结果日报必须明确说明当日没有符合项目。

## 6. 自动化与可靠性

本机 macOS `launchd` 任务每天本地时间 09:00 运行完整流程，成功后弹出可直接打开日报
的窗口，失败则提示查看本地日志且不覆盖旧日报。百炼凭据存放在当前用户的 macOS
Keychain 中，不写入 plist、日志或报告。GitHub Actions 保留 `workflow_dispatch` 手动
备用路径。相同并发组内串行执行。`GITHUB_TOKEN` 只授予
`contents: write`；第三方 Action 固定到 commit SHA。

网络请求最多尝试三次，尊重 `Retry-After` 并指数退避。任何抓取、补充、模型、校验或
渲染错误都以非零状态结束且不修改正式产物。成功后从同文件系统暂存文件原子替换日报
和快照；Action 只提交 `data/`、`reports/` 的差异，无差异时不创建空提交。Commit
subject 为 `chore(report): update YYYY-MM-DD trending digest`。Secret、Token、
Workspace ID 和完整模型请求不得进入日志或产物。

## 7. 测试与验收

`pytest` 测试默认完全离线，覆盖：

- Trending HTML 顺序、动态候选数量、字段缺失和空页面；
- GitHub 元数据、README、License、重试与限流；
- Agent/MCP/RAG/Memory/评测正例和训练/推理/部署反例；
- 人工名单优先级、冲突和榜单边界；
- Qwen 严格 Schema、额外字段、错误类型、非法枚举、业务错误和三次重试；
- 正常/零结果日报、同日覆盖、连续上榜、日期中断和快照重新渲染；
- 中间失败不改变已有日报、报告与快照一致、产物不泄露 Secret。

首版验收要求手动 Action 对当天页面返回的全部候选产生判定；日报只展示
`included=true` 项并保持原始排名；同日只有一个归档版本；失败重跑不改变旧内容；
零入选正常发布；离线测试、静态检查和真实网络 smoke test 全部通过。
