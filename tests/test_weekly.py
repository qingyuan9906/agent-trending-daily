import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import make_repository

from agent_trending.models import (
    ArticleAssessment,
    ArticleDocument,
    ProjectBrief,
    RelevanceAnalysis,
    TokenUsage,
    TrendingRepository,
)
from agent_trending.observations import ObservationStore
from agent_trending.weekly import WeeklyPipeline, merge_weekly_candidates


def trending(rank: int, name: str, stars: int) -> TrendingRepository:
    return TrendingRepository(
        rank=rank,
        full_name=name,
        url=f"https://github.com/{name}",
        page_description="agent framework",
        language="Python",
        stars_today=stars,
    )


class WeeklyProvider:
    def fetch(self):
        return [trending(index, f"owner/repo{index}", index) for index in range(1, 7)]


class RepositoryProvider:
    def enrich(self, item):
        repository = make_repository(
            item.rank,
            full_name=item.full_name,
            description="agent framework",
            readme="agent evidence",
        )
        return repository.model_copy(
            update={"info": repository.info.model_copy(update={"stars_today": item.stars_today})}
        )


class ArticleProvider:
    def fetch(self, period_start, period_end):
        return [
            ArticleDocument(
                source="OpenAI",
                title=f"Agent article {index}",
                url=f"https://developers.openai.com/blog/agent-article-{index}",
                published_date=(period_end - timedelta(days=index)).isoformat(),
                content=f"Official article {index} about long-running agents.",
                content_sha256=hashlib.sha256(
                    f"Official article {index} about long-running agents.".encode()
                ).hexdigest(),
            )
            for index in range(6)
        ]


class Analyzer:
    def reset_usage(self):
        pass

    @property
    def token_usage(self):
        return TokenUsage(
            input_tokens=100,
            output_tokens=20,
            cached_input_tokens=0,
            total_tokens=120,
            estimated_cost_cny=0.001,
            pricing_basis="test/checked-2026-09-01",
        )

    def analyze(self, repository, rule):
        return RelevanceAnalysis(
            is_relevant=True,
            primary_category="agent_framework",
            related_tags=["agent_framework"],
            reason_zh="提供 Agent 编排能力。",
            confidence="high",
            summary_zh="Agent 编排项目。",
            highlights_zh=["支持工具调用"],
        )

    def create_brief(self, repository, rule):
        return ProjectBrief(
            primary_category="agent_framework",
            related_tags=["agent_framework"],
            relevance_reason_zh="提供 Agent 编排能力。",
            summary_zh="Agent 编排项目。",
            highlights_zh=["支持工具调用"],
        )

    def analyze_article(self, article):
        return ArticleAssessment(is_relevant=True, summary_zh="介绍长时间运行 Agent 的工程方法。")


def seed_observations(root):
    store = ObservationStore(root)
    start = datetime(2026, 8, 24, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
    for offset in range(7):
        # Explicit streak lengths ending Sunday: repo1=7, repo2=6, ..., repo6=2.
        names = [index for index in range(1, 7) if offset >= index - 1]
        if offset == 6:
            names = list(range(1, 7))
        repositories = [
            trending(rank, f"owner/repo{index}", index * 100 if offset == 6 else index)
            for rank, index in enumerate(names, start=1)
        ]
        store.collect(repositories, now=start + timedelta(days=offset))


def test_weekly_pipeline_uses_monday_filename_and_selects_five(tmp_path, relevance_config):
    seed_observations(tmp_path)
    result = WeeklyPipeline(
        root=tmp_path,
        config=relevance_config,
        weekly_provider=WeeklyProvider(),
        repository_provider=RepositoryProvider(),
        article_provider=ArticleProvider(),
        analyzer=Analyzer(),
        clock=lambda: datetime(2026, 9, 1, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    ).run()

    assert result.snapshot.published_date == "2026-08-31"
    assert result.snapshot.period_start == "2026-08-24"
    assert result.snapshot.period_end == "2026-08-30"
    assert result.snapshot.selected_count == 5
    assert [item.full_name for item in result.snapshot.selected_projects] == [
        "owner/repo1",
        "owner/repo6",
        "owner/repo2",
        "owner/repo5",
        "owner/repo3",
    ]
    assert len(result.snapshot.articles) == 5
    assert "入选理由" not in result.snapshot.articles[0].model_dump()
    assert (tmp_path / "data" / "2026-08-31.json").exists()
    assert (tmp_path / "reports" / "2026-08-31.md").exists()
    assert "官方技术博客" in result.report
    assert "2026-08-24 至 2026-08-30" in result.report


def test_weekly_failure_preserves_existing_report(tmp_path, relevance_config):
    seed_observations(tmp_path)
    reports = tmp_path / "reports"
    reports.mkdir()
    latest = reports / "latest.md"
    latest.write_text("old weekly report", encoding="utf-8")

    class FailingArticleProvider:
        def fetch(self, period_start, period_end):
            raise RuntimeError("OpenAI source unavailable")

    pipeline = WeeklyPipeline(
        root=tmp_path,
        config=relevance_config,
        weekly_provider=WeeklyProvider(),
        repository_provider=RepositoryProvider(),
        article_provider=FailingArticleProvider(),
        analyzer=Analyzer(),
        clock=lambda: datetime(2026, 9, 1, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    with pytest.raises(RuntimeError, match="source unavailable"):
        pipeline.run()

    assert latest.read_text(encoding="utf-8") == "old weekly report"
    assert not (tmp_path / "data" / "2026-08-31.json").exists()


def test_daily_only_candidate_uses_sunday_stars(tmp_path):
    store = ObservationStore(tmp_path)
    start = datetime(2026, 8, 24, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
    for offset in range(7):
        store.collect(
            [trending(1, "owner/daily-only", 900 if offset == 6 else 10)],
            now=start + timedelta(days=offset),
        )
    observations = store.load_period(start.date(), (start + timedelta(days=6)).date())

    candidates, weekly_ranks = merge_weekly_candidates([], observations)

    assert candidates[0].stars_today == 900
    assert weekly_ranks == {}


def test_weekly_resume_skips_validated_candidates(tmp_path, relevance_config):
    seed_observations(tmp_path)

    class CountingAnalyzer(Analyzer):
        def __init__(self, fail_name=None):
            self.fail_name = fail_name
            self.called = []
            self.tokens = 0

        def reset_usage(self):
            self.tokens = 0

        @property
        def token_usage(self):
            return TokenUsage(
                input_tokens=self.tokens,
                output_tokens=0,
                cached_input_tokens=0,
                total_tokens=self.tokens,
                estimated_cost_cny=self.tokens / 1_000_000,
                pricing_basis="test/checked-2026-09-01",
            )

        def analyze(self, repository, rule):
            self.called.append(repository.info.full_name)
            self.tokens += 10
            if repository.info.full_name == self.fail_name:
                raise RuntimeError("model unavailable")
            return super().analyze(repository, rule)

        def analyze_article(self, article):
            self.tokens += 10
            return super().analyze_article(article)

    failing = CountingAnalyzer(fail_name="owner/repo2")
    first = WeeklyPipeline(
        root=tmp_path,
        config=relevance_config,
        weekly_provider=WeeklyProvider(),
        repository_provider=RepositoryProvider(),
        article_provider=ArticleProvider(),
        analyzer=failing,
        clock=lambda: datetime(2026, 9, 1, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    with pytest.raises(RuntimeError, match="model unavailable"):
        first.run()

    resumed_analyzer = CountingAnalyzer()
    resumed = WeeklyPipeline(
        root=tmp_path,
        config=relevance_config,
        weekly_provider=WeeklyProvider(),
        repository_provider=RepositoryProvider(),
        article_provider=ArticleProvider(),
        analyzer=resumed_analyzer,
        clock=lambda: datetime(2026, 9, 1, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    ).run()

    assert failing.called == ["owner/repo1", "owner/repo2"]
    assert resumed_analyzer.called == [
        "owner/repo2",
        "owner/repo3",
        "owner/repo4",
        "owner/repo5",
        "owner/repo6",
    ]
    assert resumed.snapshot.token_usage.total_tokens == 130
    assert not (tmp_path / ".state" / "weekly-2026-08-31.json").exists()
