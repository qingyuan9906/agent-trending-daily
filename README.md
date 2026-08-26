# Agent Trending Daily

每天北京时间 09:00 获取 GitHub Trending Daily 页面当天返回的全部仓库，筛选与
Agent 应用生态相关的项目，并生成中文研究简报。

- [最新日报](reports/latest.md)
- [历史日报](reports/)
- [产品与技术规格](spec.md)

## 本地安装

项目固定使用 Python 3.13 和 `uv`：

```bash
uv sync
```

配置百炼华北 2（北京）业务空间：

```bash
export DASHSCOPE_API_KEY="..."
export DASHSCOPE_WORKSPACE_ID="..."
export GITHUB_TOKEN="..."  # 本地可选，GitHub Actions 会自动提供
```

## 使用

```bash
uv run agent-trending validate-config
uv run agent-trending run --dry-run
uv run agent-trending run
uv run agent-trending render data/YYYY-MM-DD.json
```

`run` 只获取当前 GitHub Trending Daily 页面，不支持伪造历史日期。正式运行成功后写入：

- `data/YYYY-MM-DD.json`：当天页面全部候选及完整判定链路；
- `reports/YYYY-MM-DD.md`：当日中文研究简报；
- `reports/latest.md`：与当日日报内容一致的最新入口。

## 配置

相关词、排除词、分类标签、`allowlist` 和 `denylist` 位于
[`config/relevance.yaml`](config/relevance.yaml)。名单只会影响当天 Daily 页面实际返回的
候选，不能引入页面之外的项目。

## 测试

```bash
uv run pytest
uv run ruff check .
```

测试默认完全离线。真实抓取和 Qwen 调用只在显式运行 `agent-trending run` 时发生。

## GitHub Actions 部署

1. 将仓库推送到 GitHub，并在 Actions 设置中允许工作流写入仓库内容。
2. 新建 Actions Secret `DASHSCOPE_API_KEY`。
3. 新建 Actions Variable `DASHSCOPE_WORKSPACE_ID`，填写百炼华北 2（北京）业务空间 ID。
4. 在 **Actions → Daily Agent Trending Report → Run workflow** 手动验收一次。

定时工作流每天北京时间 09:00 运行。候选数量完全由当天 Daily 页面决定；例如页面
返回 16 个仓库，就从这 16 个仓库中筛选。页面没有任何仓库卡片或卡片结构损坏时，
任务才会失败并保留上一份日报。
