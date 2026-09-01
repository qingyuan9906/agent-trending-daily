# Agent Trending Weekly

每天北京时间 09:00 轻量采集 GitHub Trending Daily；每周一汇总上一个完整自然周，
从全部相关候选中按连续入榜天数与周日新增 Star 双通道择优展示前 5 个项目，并总结
OpenAI、Anthropic 官方技术博客中本周与 Agent 或大模型相关的文章。

- [最新周报](reports/latest.md)
- [历史报告](reports/)
- [产品与技术规格](spec.md)

## 本地安装

项目固定使用 Python 3.13 和 `uv`：

```bash
uv sync
```

周报发布需要百炼华北 2（北京）业务空间：

```bash
export DASHSCOPE_API_KEY="..."
export DASHSCOPE_WORKSPACE_ID="..."
export GITHUB_TOKEN="..."  # 本地可选，GitHub Actions 会自动提供
```

## 使用

```bash
uv run agent-trending validate-config
uv run agent-trending collect --dry-run
uv run agent-trending collect
uv run agent-trending publish-weekly --dry-run
uv run agent-trending publish-weekly
uv run agent-trending run
uv run agent-trending render data/YYYY-MM-DD.json
```

- `collect` 将当天完整 Daily 榜单写入 `data/observations/YYYY-MM-DD.json`，不调用模型。
- `publish-weekly` 使用当前周一作为发布日期，汇总此前周一至周日；缺少任一天观测时
  拒绝发布，避免伪造连续入榜天数。
- `run` 是兼容调度入口：每天采样，仅在周一继续发布周报。
- `render` 同时支持历史 `DailySnapshot` 和新的 `WeeklySnapshot`。

正式周报直接按周一发布日期命名。例如 `data/2026-08-31.json`、
`reports/2026-08-31.md` 和 `reports/2026-08-31.html` 对应 `2026-08-24` 至
`2026-08-30` 的完整统计周期；不使用 ISO 周编号。`reports/latest.md` 与
`reports/latest.html` 始终指向最近一次成功周报。

## 周报内容

项目候选由一周七份 Daily 观测与实时 `since=weekly` 榜单合并去重。全部候选先执行规则、
GitHub 元数据补充和严格 LLM 相关性校验，再按以下优先级取前 5 个：

1. 分别计算截至周日的连续入榜天数排名和周日 `stars today` 排名；
2. 取两项中的最佳名次作为综合优先级；
3. 依次按两项名次之和、连续天数、周日涨星、周榜名次和仓库名破同分。

文章只来自 [OpenAI Developer Blog](https://developers.openai.com/blog/) 和
[Anthropic Engineering](https://www.anthropic.com/engineering)。仅纳入统计周期内与 Agent、
Claude Code 或大模型相关的文章，两家合计最多 5 篇。文章区只展示来源、标题、发布日期、
中文摘要和官方链接，不生成入选理由。任一官网抓取失败时整期周报不发布。

## 严格校验与断点

项目和文章模型调用均使用原生严格 JSON Schema Structured Outputs，再执行 Pydantic
`strict=True` 和业务校验；不使用 JSON 修复、宽松解析或部分发布。完整候选审计链路保存在
周报 JSON 中，README 正文、凭据、完整请求和未经验证的模型输出不会落盘。

失败运行将已严格验证的项目、文章和累计 Token 用量原子保存到权限为 `0600` 的
`.state/weekly-YYYY-MM-DD.json`。只有周期、配置、提示合同、历史观测和输入指纹全部匹配
才会复用；正式发布成功后删除断点。

## 测试

```bash
uv run pytest
uv run ruff check .
zsh -n scripts/run_daily_macos.sh scripts/install_macos_launch_agent.sh
```

测试默认完全离线。真实官网抓取、GitHub API 和 Qwen 调用只在显式发布周报时发生。

## GitHub Actions 备用路径

在仓库中配置 Secret `DASHSCOPE_API_KEY` 和 Variable `DASHSCOPE_WORKSPACE_ID`，然后从
**Actions → Weekly Agent Trending Report → Run workflow** 手动触发。Actions 不配置 cron，
避免与本机定时任务重复调用模型；它使用仓库中已提交的每日观测恢复周统计。

## macOS 自动运行

为避免 macOS TCC 阻止后台进程访问 `Documents`，运行副本推荐放在：

```bash
git clone https://github.com/qingyuan9906/agent-trending-daily.git \
  ~/.local/share/agent-trending-daily
cd ~/.local/share/agent-trending-daily
./scripts/install_macos_launch_agent.sh
```

LaunchAgent 标识继续使用 `com.lxy.agent-trending-daily`，每天 09:00 运行。任务每天提交并
推送一份轻量观测；仅周一读取百炼凭据、生成周报并弹出成功窗口。代理优先、直连兜底、
睡眠唤醒网络等待、Git/依赖/流水线独立重试、五分钟自动补跑和日志脱敏策略保持不变。
