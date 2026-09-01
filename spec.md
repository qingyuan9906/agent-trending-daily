# agent-trending-weekly 产品与技术规格

## 1. 目标与周期

本机每天北京时间 09:00 保存 GitHub Trending Daily 原始观测。每周一发布上一完整自然周的
中文 Agent 趋势周报，仅展示相关项目综合排名前 5，并附最多 5 篇 OpenAI、Anthropic
官方技术博客摘要。

周报使用周一发布日期 `YYYY-MM-DD` 命名，同时在 Schema 中保存 `published_date`、
`period_start` 和 `period_end`。历史日报保持原文件和 Schema，不批量迁移。

## 2. 数据流与排序

1. `collect` 请求 `https://github.com/trending?since=daily`，按页面顺序保存完整仓库列表、
   原始名次和 `stars today`，不调用 GitHub API 或 LLM。
2. 周报必须具备统计周期七天的有效观测；缺一天即失败。候选池由七天观测与
   `https://github.com/trending?since=weekly` 合并去重。
3. 对全部候选补充 GitHub 元数据及 README 哈希，执行人工名单、规则与严格 LLM 判定；
   只有判定相关的项目参与最终排序。
4. 分别按截至周日的连续入榜天数和周日新增 Star 计算竞争排名，综合优先级取两个名次的
   最小值；再按名次和、连续天数、周日新增 Star、周榜名次、仓库名稳定破同分。
5. 正式 Markdown、HTML 只展示前 5 个；JSON 保留全部候选审计链路和最终排序指标。

连续入榜依据原始 Daily 观测，而不是模型是否曾将项目选入报告；缺失观测不能解释为未入榜。

## 3. 官方文章

只抓取 `https://developers.openai.com/blog/` 与
`https://www.anthropic.com/engineering` 的官方文章。索引与正文发布日期必须一致，链接
必须仍位于对应官方路径。正文只在内存中截断后送入模型，正式快照仅保存正文 SHA-256。

模型输出 `is_relevant` 和 `summary_zh`，不包含入选理由。相关范围为 Agent、Claude Code、
大模型能力与应用开发、工具调用、MCP、RAG、Memory、Agent 评测和上下文工程。相关文章按
发布日期倒序、规范链接破同分，两家合计最多 5 篇。零篇是合法结果；任一来源无法可靠解析
则整期失败。

## 4. Schema、LLM 与产物

- `DailyObservation`：schema v1，写入 `data/observations/YYYY-MM-DD.json`。
- `DailySnapshot`：schema v1/v2，只读兼容历史日报。
- `WeeklySnapshot`：schema v3，写入 `data/YYYY-MM-DD.json`，保存周期、全部候选、前 5 排序、
  官方文章和 Token 用量。
- 周报写入 `reports/YYYY-MM-DD.md/.html` 并原子更新 `reports/latest.md/.html`。

Qwen 继续使用 OpenAI-compatible Chat Completions 的原生 `json_schema`、`strict=true`、封闭
Schema，随后执行 Pydantic `strict=True` 与业务校验。内容错误最多三次反馈重试；SDK 负责
连接、超时、429 和 5xx 重试。禁止 JSON Mode、Prompt-only JSON、手工截取和 `json_repair`。

任一步骤失败不得更新正式周报。`.state/weekly-YYYY-MM-DD.json` 只保存已验证项目、文章判定、
指纹和累计 Token，不保存正文、README、凭据、完整请求或原始模型响应。

## 5. CLI 与自动化

- `agent-trending collect [--dry-run]`：采集当天 Daily 观测。
- `agent-trending publish-weekly [--dry-run]`：发布当前周一所代表的上一完整自然周。
- `agent-trending run [--dry-run]`：兼容入口，每日采样、周一继续发布。
- `agent-trending render data/YYYY-MM-DD.json`：严格验证后重建新旧报告。
- `agent-trending validate-config`：验证配置和周报所需环境变量。

LaunchAgent 仍每天 09:00 运行，技术标识和包名保持兼容。每日观测独立提交推送；周一周报
失败后等待五分钟补跑一次，只有最终失败才通知且旧周报不变。GitHub Actions 保留纯手动
备用路径，不增加 cron。

## 6. 验收

离线测试覆盖七日完整性、跨周连续入榜、双通道排序、稳定破同分、前 5 限制、日期命名、
官方索引/正文解析、文章严格 Schema、零文章、来源失败、断点恢复、日志脱敏、旧日报兼容和
原子发布。提交前执行 `pytest`、`ruff check .` 与两个 zsh 脚本的语法检查。
