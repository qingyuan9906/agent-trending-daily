# ruff: noqa: E501

from __future__ import annotations

import html

from agent_trending.config import RelevanceConfig
from agent_trending.models import CandidateRecord, WeeklyProjectRanking, WeeklySnapshot
from agent_trending.render import _safe, validate_snapshot_categories


def render_weekly_report(snapshot: WeeklySnapshot, config: RelevanceConfig) -> str:
    validate_snapshot_categories(snapshot, config)
    candidates = {
        candidate.repository.full_name.casefold(): candidate for candidate in snapshot.candidates
    }
    lines = [
        f"# GitHub Agent Trending 周报 · {snapshot.published_date}",
        "",
        f"> 统计周期：{snapshot.period_start} 至 {snapshot.period_end}（北京时间）  ",
        f"> 生成时间：{_safe(snapshot.generated_at)}  ",
        f"> 候选：{snapshot.candidate_count} 个 · 相关：{snapshot.relevant_count} 个 · "
        f"展示：{snapshot.selected_count} 个 · 模型：`{_safe(snapshot.model)}`",
        "",
        "## 本周项目",
        "",
    ]
    if not snapshot.selected_projects:
        lines.extend(["本周候选中没有符合筛选范围的项目。", ""])
    for ranking in snapshot.selected_projects:
        lines.extend(
            _render_project(candidates[ranking.full_name.casefold()], ranking, config)
        )
    lines.extend(["## 官方技术博客", ""])
    if not snapshot.articles:
        lines.extend(["本周 OpenAI Developer Blog 与 Anthropic Engineering 无相关文章。", ""])
    else:
        for article in snapshot.articles:
            lines.extend(
                [
                    f"### [{_safe(article.title)}]({article.url})",
                    "",
                    f"**来源：** {article.source} · **发布日期：** {article.published_date}",
                    "",
                    f"{_safe(article.summary_zh)}",
                    "",
                ]
            )
    lines.extend(
        [
            "---",
            "",
            "项目按连续入榜天数与统计周期最后一天的新增 Star 双通道择优，仅展示前 5 个。",
            "",
        ]
    )
    return "\n".join(lines)


def _render_project(
    candidate: CandidateRecord,
    ranking: WeeklyProjectRanking,
    config: RelevanceConfig,
) -> list[str]:
    repository = candidate.repository
    categories = " · ".join(_safe(config.categories[tag]) for tag in candidate.related_tags)
    description = _safe(repository.description) or "暂无原始描述"
    language = _safe(repository.language) if repository.language else "未知"
    license_name = _safe(repository.license) if repository.license else "未声明"
    lines = [
        f"### #{ranking.display_rank} [{_safe(repository.full_name)}]({repository.url})",
        "",
        f"**原始描述：** {description}",
        "",
        f"**中文摘要：** {_safe(candidate.summary_zh)}",
        "",
        f"**分类：** {categories}",
        "",
        f"**入选理由：** {_safe(candidate.relevance_reason_zh)}",
        "",
        "**核心亮点：**",
        "",
    ]
    lines.extend(f"- {_safe(item)}" for item in candidate.highlights_zh)
    lines.extend(
        [
            "",
            f"**数据：** {language} · ⭐ {repository.stars_total:,} · "
            f"周日新增 +{ranking.stars_last_day:,} · "
            f"Fork {repository.forks:,} · License {license_name}",
            "",
            f"**排序：** 连续入榜 {ranking.consecutive_days} 天（第 {ranking.streak_rank}） · "
            f"单日涨星第 {ranking.star_rank} · 综合优先级第 {ranking.priority_rank}",
            "",
        ]
    )
    return lines


def render_weekly_html(snapshot: WeeklySnapshot, config: RelevanceConfig) -> str:
    validate_snapshot_categories(snapshot, config)
    candidates = {
        candidate.repository.full_name.casefold(): candidate for candidate in snapshot.candidates
    }
    projects = "".join(
        _render_html_project(candidates[item.full_name.casefold()], item, config)
        for item in snapshot.selected_projects
    ) or '<p class="empty">本周候选中没有符合筛选范围的项目。</p>'
    articles = "".join(
        f'<article class="article"><p class="meta">{_e(item.source)} · {_e(item.published_date)}</p>'
        f'<h3><a href="{_e(item.url)}">{_e(item.title)}</a></h3>'
        f'<p>{_e(item.summary_zh)}</p></article>'
        for item in snapshot.articles
    ) or '<p class="empty">本周官方技术博客无相关文章。</p>'
    usage = snapshot.token_usage
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GitHub Agent Trending 周报 · {_e(snapshot.published_date)}</title>
<style>
:root{{--ink:#18231f;--muted:#64736d;--brand:#0f6b4d;--paper:#fffdf8;--line:#dce6df;--canvas:#f1f5ef;--accent:#d96b38}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--canvas);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;line-height:1.7}}
.page{{width:min(1080px,calc(100% - 28px));margin:auto;padding:32px 0 64px}}.hero{{padding:36px;border-radius:26px;color:#fff;background:linear-gradient(135deg,#153d31,#0f6b4d)}}
.hero h1{{margin:0;font-size:clamp(30px,5vw,50px)}}.hero p{{margin:8px 0 0;color:#d7e9e1}}.stats{{display:flex;flex-wrap:wrap;gap:10px;margin-top:22px}}.stat{{padding:10px 14px;border-radius:12px;background:#ffffff16}}
h2{{margin:34px 0 16px}}.card,.article{{margin:16px 0;padding:26px;border:1px solid var(--line);border-radius:20px;background:var(--paper)}}a{{color:var(--brand)}}.rank{{color:var(--accent);font-weight:800}}.tags span{{display:inline-block;margin:4px;padding:4px 9px;border-radius:999px;background:#e1f3e9;color:var(--brand)}}.reason{{padding:12px 15px;border-left:4px solid var(--accent);background:#fff3eb}}.meta,.metrics,.empty{{color:var(--muted)}}
</style></head><body><main class="page"><header class="hero"><p>WEEKLY RESEARCH DIGEST</p><h1>GitHub Agent Trending</h1>
<p>{_e(snapshot.period_start)} 至 {_e(snapshot.period_end)} · 发布于 {_e(snapshot.published_date)}</p><div class="stats">
<span class="stat">候选 {snapshot.candidate_count}</span><span class="stat">相关 {snapshot.relevant_count}</span><span class="stat">展示 {snapshot.selected_count}</span><span class="stat">Token {usage.total_tokens:,} · ¥{usage.estimated_cost_cny:.2f}</span></div></header>
<h2>本周项目</h2>{projects}<h2>官方技术博客</h2>{articles}
<p class="meta">来源：GitHub Trending Daily/Weekly、OpenAI Developer Blog、Anthropic Engineering</p></main></body></html>"""


def _render_html_project(
    candidate: CandidateRecord,
    ranking: WeeklyProjectRanking,
    config: RelevanceConfig,
) -> str:
    repository = candidate.repository
    tags = "".join(
        f"<span>{_e(config.categories[tag])}</span>" for tag in candidate.related_tags
    )
    highlights = "".join(f"<li>{_e(item)}</li>" for item in candidate.highlights_zh)
    return f"""<article class="card"><p class="rank">#{ranking.display_rank}</p>
<h3><a href="{_e(repository.url)}">{_e(repository.full_name)}</a></h3><p>{_e(repository.description or '暂无原始描述')}</p>
<div class="tags">{tags}</div><p>{_e(candidate.summary_zh)}</p><p class="reason"><strong>为什么入选</strong><br>{_e(candidate.relevance_reason_zh)}</p>
<ul>{highlights}</ul><p class="metrics">连续入榜 {ranking.consecutive_days} 天（第 {ranking.streak_rank}） · 周日新增 +{ranking.stars_last_day:,}（第 {ranking.star_rank}） · 总 Star {repository.stars_total:,}</p></article>"""


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
