from __future__ import annotations

import html

from agent_trending.config import RelevanceConfig
from agent_trending.models import CandidateRecord, DailySnapshot


def render_report(snapshot: DailySnapshot, config: RelevanceConfig) -> str:
    lines = [
        f"# GitHub Agent Trending 日报 · {snapshot.run_date}",
        "",
        f"> 生成时间：{_safe(snapshot.generated_at)}  ",
        f"> 数据源：[GitHub Trending Daily]({snapshot.source_url})  ",
        f"> 候选：{snapshot.candidate_count} 个 · 入选：{snapshot.included_count} 个 · "
        f"模型：`{_safe(snapshot.model)}`",
        "",
    ]
    included = [candidate for candidate in snapshot.candidates if candidate.included]
    if not included:
        lines.extend(
            [
                "## 今日结论",
                "",
                f"今日 Daily 页面 {snapshot.candidate_count} 个候选中无符合筛选范围的项目。",
                "",
            ]
        )
    else:
        for candidate in included:
            lines.extend(_render_candidate(candidate, config))
    lines.extend(
        [
            "---",
            "",
            "筛选范围聚焦 Agent 应用生态；模型训练、微调、推理引擎、量化与部署类项目不纳入。",
            "",
        ]
    )
    return "\n".join(lines)


def _render_candidate(candidate: CandidateRecord, config: RelevanceConfig) -> list[str]:
    repository = candidate.repository
    category_labels = [config.categories[tag] for tag in candidate.related_tags]
    history = (
        f"首次上榜（{candidate.first_seen_date}）"
        if candidate.consecutive_days == 1
        else f"连续上榜 {candidate.consecutive_days} 天（首次：{candidate.first_seen_date}）"
    )
    description = _safe(repository.description) or "暂无原始描述"
    license_name = _safe(repository.license) if repository.license else "未声明"
    language = _safe(repository.language) if repository.language else "未知"
    lines = [
        f"## #{repository.rank} [{_safe(repository.full_name)}]({repository.url})",
        "",
        f"**原始描述：** {description}",
        "",
        f"**中文摘要：** {_safe(candidate.summary_zh)}",
        "",
        f"**分类：** {' · '.join(_safe(label) for label in category_labels)}",
        "",
        f"**入选理由：** {_safe(candidate.relevance_reason_zh)}",
        "",
        "**核心亮点：**",
        "",
    ]
    lines.extend(f"- {_safe(highlight)}" for highlight in candidate.highlights_zh)
    lines.extend(
        [
            "",
            f"**数据：** {language} · ⭐ {repository.stars_total:,} · "
            f"今日 +{repository.stars_today:,} · Fork {repository.forks:,} · "
            f"License {license_name}",
            "",
            f"**上榜记录：** {history}",
            "",
        ]
    )
    return lines


def _safe(value: str | None) -> str:
    if value is None:
        return ""
    normalized = " ".join(value.split()).replace("\\", "\\\\")
    for character in "`*_[]":
        normalized = normalized.replace(character, f"\\{character}")
    return html.escape(normalized, quote=False)
