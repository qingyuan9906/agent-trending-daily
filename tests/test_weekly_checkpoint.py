import stat
from datetime import date

from agent_trending.checkpoint import WeeklyCheckpointStore, article_fingerprint
from agent_trending.models import ArticleAssessment, ArticleDocument, TokenUsage


def usage(tokens=0):
    return TokenUsage(
        input_tokens=tokens,
        output_tokens=0,
        cached_input_tokens=0,
        total_tokens=tokens,
        estimated_cost_cny=tokens / 1_000_000,
        pricing_basis="test/checked-2026-09-01",
    )


def test_weekly_checkpoint_reuses_matching_article_and_invalidates_history(
    tmp_path, relevance_config
):
    observation_dir = tmp_path / "data" / "observations"
    observation_dir.mkdir(parents=True)
    observation = observation_dir / "2026-08-30.json"
    observation.write_text("first history", encoding="utf-8")
    article = ArticleDocument(
        source="Anthropic",
        title="Managed agents",
        url="https://www.anthropic.com/engineering/managed-agents",
        published_date="2026-08-25",
        content="Validated content",
        content_sha256="0" * 64,
    )
    fingerprint = article_fingerprint(article)

    store = WeeklyCheckpointStore(
        root=tmp_path,
        published_date=date(2026, 8, 31),
        period_start=date(2026, 8, 24),
        period_end=date(2026, 8, 30),
        config=relevance_config,
        initial_usage=usage(),
    )
    assessment = ArticleAssessment(is_relevant=True, summary_zh="介绍托管 Agent 架构。")
    store.save_article(
        current_usage=usage(10),
        url=article.url,
        input_sha256=fingerprint,
        assessment=assessment,
    )

    resumed = WeeklyCheckpointStore(
        root=tmp_path,
        published_date=date(2026, 8, 31),
        period_start=date(2026, 8, 24),
        period_end=date(2026, 8, 30),
        config=relevance_config,
        initial_usage=usage(),
    )
    assert resumed.cached_article(url=article.url, input_sha256=fingerprint) == assessment
    assert stat.S_IMODE(resumed.path.stat().st_mode) == 0o600
    assert "Validated content" not in resumed.path.read_text(encoding="utf-8")

    observation.write_text("changed history", encoding="utf-8")
    invalidated = WeeklyCheckpointStore(
        root=tmp_path,
        published_date=date(2026, 8, 31),
        period_start=date(2026, 8, 24),
        period_end=date(2026, 8, 30),
        config=relevance_config,
        initial_usage=usage(),
    )
    assert invalidated.cached_article(url=article.url, input_sha256=fingerprint) is None
