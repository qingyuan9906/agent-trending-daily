# ruff: noqa: E501

from __future__ import annotations

import html

from agent_trending.config import RelevanceConfig
from agent_trending.models import CandidateRecord, DailySnapshot
from agent_trending.render import validate_snapshot_categories


def render_html_report(snapshot: DailySnapshot, config: RelevanceConfig) -> str:
    validate_snapshot_categories(snapshot, config)
    included = [candidate for candidate in snapshot.candidates if candidate.included]
    cards = "\n".join(_render_candidate(candidate, config) for candidate in included)
    if not cards:
        cards = (
            '<section class="empty"><h2>今日结论</h2>'
            f"<p>今日 Daily 页面 {_e(snapshot.candidate_count)} 个候选中无符合筛选范围的项目。"
            "</p></section>"
        )
    token_stat = _render_token_stat(snapshot)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>GitHub Agent Trending 日报 · {_e(snapshot.run_date)}</title>
  <style>
    :root {{
      --ink: #19231f;
      --muted: #60716a;
      --paper: #fffdf8;
      --canvas: #f1f5ef;
      --line: #dce6df;
      --brand: #0f6b4d;
      --brand-soft: #e1f3e9;
      --accent: #d96b38;
      --shadow: 0 16px 45px rgba(36, 59, 48, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 10% 0%, #dcefe2 0, transparent 30rem),
        var(--canvas);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      line-height: 1.72;
    }}
    a {{ color: inherit; }}
    .page {{ width: min(1100px, calc(100% - 32px)); margin: 0 auto; padding: 40px 0 72px; }}
    .hero {{
      overflow: hidden;
      position: relative;
      padding: clamp(28px, 6vw, 62px);
      border-radius: 28px;
      color: white;
      background: linear-gradient(135deg, #153d31, #0f6b4d 65%, #188462);
      box-shadow: var(--shadow);
    }}
    .hero::after {{
      content: "";
      position: absolute;
      width: 280px;
      height: 280px;
      right: -80px;
      top: -110px;
      border: 52px solid rgba(255, 255, 255, 0.08);
      border-radius: 50%;
    }}
    .eyebrow {{ margin: 0 0 8px; opacity: 0.72; font-size: 13px; letter-spacing: 0.16em; }}
    h1 {{ margin: 0; font-size: clamp(30px, 5vw, 52px); line-height: 1.12; }}
    .subtitle {{ margin: 14px 0 0; max-width: 720px; color: rgba(255, 255, 255, 0.8); }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-top: 30px; }}
    .stat {{ padding: 15px 18px; border: 1px solid rgba(255,255,255,.15); border-radius: 16px; background: rgba(255,255,255,.08); }}
    .stat strong {{ display: block; font-size: 25px; line-height: 1.2; }}
    .stat span {{ color: rgba(255,255,255,.7); font-size: 13px; }}
    .token-stat strong {{ overflow-wrap: anywhere; font-size: clamp(17px, 2vw, 23px); }}
    .source {{ display: flex; flex-wrap: wrap; gap: 10px 24px; margin: 18px 4px 32px; color: var(--muted); font-size: 13px; }}
    .source a {{ color: var(--brand); font-weight: 650; }}
    .projects {{ display: grid; gap: 22px; }}
    .project {{ padding: clamp(22px, 4vw, 38px); border: 1px solid var(--line); border-radius: 24px; background: var(--paper); box-shadow: var(--shadow); }}
    .project-head {{ display: flex; align-items: flex-start; gap: 14px; }}
    .rank {{ flex: 0 0 auto; min-width: 48px; padding: 8px 10px; border-radius: 13px; color: white; background: var(--accent); font-weight: 800; text-align: center; }}
    .repo {{ margin: 0; overflow-wrap: anywhere; font-size: clamp(21px, 3vw, 30px); line-height: 1.25; }}
    .repo a {{ color: var(--brand); text-decoration: none; }}
    .repo a:hover {{ text-decoration: underline; }}
    .description {{ margin: 7px 0 0; color: var(--muted); }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 20px 0; }}
    .tag {{ padding: 5px 11px; border-radius: 999px; color: var(--brand); background: var(--brand-soft); font-size: 13px; font-weight: 650; }}
    .section-title {{ margin: 24px 0 7px; font-size: 14px; color: var(--muted); letter-spacing: .08em; }}
    .summary {{ margin: 0; font-size: 17px; }}
    .reason {{ margin-top: 20px; padding: 16px 18px; border-left: 4px solid var(--accent); border-radius: 0 13px 13px 0; background: #fff3eb; }}
    .reason strong {{ display: block; margin-bottom: 3px; color: #9a4827; }}
    .highlights {{ margin: 8px 0 0; padding-left: 22px; }}
    .highlights li {{ margin: 6px 0; padding-left: 4px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 9px; margin-top: 24px; }}
    .metric {{ min-width: 0; padding: 12px; border: 1px solid var(--line); border-radius: 13px; background: #f8faf7; }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; }}
    .metric strong {{ display: block; overflow-wrap: anywhere; margin-top: 2px; font-size: 15px; }}
    .history {{ margin: 14px 0 0; color: var(--muted); font-size: 13px; }}
    .empty {{ padding: 48px; border-radius: 24px; background: var(--paper); text-align: center; box-shadow: var(--shadow); }}
    footer {{ margin-top: 30px; color: var(--muted); text-align: center; font-size: 13px; }}
    @media (max-width: 720px) {{
      .page {{ width: min(100% - 20px, 1100px); padding-top: 10px; }}
      .hero, .project {{ border-radius: 19px; }}
      .stats {{ grid-template-columns: 1fr; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .project-head {{ align-items: center; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <header class="hero">
      <p class="eyebrow">DAILY RESEARCH DIGEST</p>
      <h1>GitHub Agent Trending</h1>
      <p class="subtitle">从今日 GitHub Trending 全部项目中，筛选值得关注的大模型与 Agent 应用生态项目。</p>
      <div class="stats">
        <div class="stat"><strong>{_e(snapshot.run_date)}</strong><span>报告日期</span></div>
        <div class="stat"><strong>{_e(snapshot.candidate_count)}</strong><span>今日候选</span></div>
        <div class="stat"><strong>{_e(snapshot.included_count)}</strong><span>最终入选</span></div>
        {token_stat}
      </div>
    </header>
    <div class="source">
      <span>生成时间：{_e(snapshot.generated_at.replace("T", " "))}</span>
      <span>分析模型：{_e(snapshot.model)}</span>
      <a href="{_e(snapshot.source_url)}" target="_blank" rel="noopener noreferrer">查看 GitHub Trending 原榜</a>
    </div>
    <section class="projects" aria-label="入选项目">
      {cards}
    </section>
    <footer>聚焦 Agent 应用生态；模型训练、微调、推理引擎、量化与部署类项目不纳入。</footer>
  </main>
</body>
</html>
"""


def _render_token_stat(snapshot: DailySnapshot) -> str:
    usage = snapshot.token_usage
    if usage is None:
        return ""
    cost = (
        f"{usage.estimated_cost_cny:.4f}"
        if 0 < usage.estimated_cost_cny < 0.01
        else f"{usage.estimated_cost_cny:.2f}"
    )
    checked_at = usage.pricing_basis.rpartition("checked-")[2] or "未知日期"
    return (
        '<div class="stat token-stat">'
        f"<strong>token量{usage.total_tokens:,}折{cost}元</strong>"
        f"<span>按百炼华北2限时8折价格估算（价格核验：{_e(checked_at)}）</span>"
        "</div>"
    )


def _render_candidate(candidate: CandidateRecord, config: RelevanceConfig) -> str:
    repository = candidate.repository
    description = repository.description or "暂无原始描述"
    language = repository.language or "未知"
    license_name = repository.license or "未声明"
    history = (
        f"首次上榜（{candidate.first_seen_date}）"
        if candidate.consecutive_days == 1
        else f"连续上榜 {candidate.consecutive_days} 天（首次：{candidate.first_seen_date}）"
    )
    tags = "".join(
        f'<span class="tag">{_e(config.categories[tag])}</span>' for tag in candidate.related_tags
    )
    highlights = "".join(f"<li>{_e(item)}</li>" for item in candidate.highlights_zh)
    return f"""<article class="project">
  <div class="project-head">
    <span class="rank">#{_e(repository.rank)}</span>
    <div>
      <h2 class="repo"><a href="{_e(repository.url)}" target="_blank" rel="noopener noreferrer">{_e(repository.full_name)}</a></h2>
      <p class="description">{_e(description)}</p>
    </div>
  </div>
  <div class="tags">{tags}</div>
  <h3 class="section-title">中文摘要</h3>
  <p class="summary">{_e(candidate.summary_zh)}</p>
  <div class="reason"><strong>为什么入选</strong>{_e(candidate.relevance_reason_zh)}</div>
  <h3 class="section-title">核心亮点</h3>
  <ul class="highlights">{highlights}</ul>
  <div class="metrics">
    <div class="metric"><span>主语言</span><strong>{_e(language)}</strong></div>
    <div class="metric"><span>总 Star</span><strong>{repository.stars_total:,}</strong></div>
    <div class="metric"><span>今日新增</span><strong>+{repository.stars_today:,}</strong></div>
    <div class="metric"><span>Fork</span><strong>{repository.forks:,}</strong></div>
    <div class="metric"><span>License</span><strong>{_e(license_name)}</strong></div>
  </div>
  <p class="history">{_e(history)}</p>
</article>"""


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
