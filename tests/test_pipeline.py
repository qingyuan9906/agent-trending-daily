from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import make_repository

from agent_trending.models import (
    EnrichedRepository,
    ProjectBrief,
    RelevanceAnalysis,
    TrendingRepository,
)
from agent_trending.pipeline import DailyPipeline


class FakeTrendingProvider:
    def fetch(self):
        return [
            TrendingRepository(
                rank=rank,
                full_name=f"owner/repo{rank:02d}",
                url=f"https://github.com/owner/repo{rank:02d}",
                page_description="",
                language="Python",
                stars_today=rank,
            )
            for rank in range(1, 21)
        ]


class FakeRepositoryProvider:
    def __init__(self, *, relevant_rank: int | None = 1):
        self.relevant_rank = relevant_rank

    def enrich(self, trending: TrendingRepository) -> EnrichedRepository:
        description = "agent framework" if trending.rank == self.relevant_rank else "plain utility"
        return make_repository(
            trending.rank,
            full_name=trending.full_name,
            description=description,
        )


class FakeAnalyzer:
    def __init__(self, *, summary: str = "Agent 编排框架"):
        self.summary = summary
        self.analysis_calls = 0

    def analyze(self, repository, rule):
        self.analysis_calls += 1
        return RelevanceAnalysis(
            is_relevant=True,
            primary_category="agent_framework",
            related_tags=["agent_framework"],
            reason_zh="主要提供 Agent 编排能力。",
            confidence="high",
            summary_zh=self.summary,
            highlights_zh=["支持 Agent 编排"],
        )

    def create_brief(self, repository, rule):
        return ProjectBrief(
            summary_zh=self.summary,
            relevance_reason_zh="人工确认相关。",
            related_tags=["agent_application"],
            highlights_zh=["面向 Agent 应用"],
        )


def clock(day: int):
    return lambda: datetime(2026, 8, day, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def make_pipeline(root: Path, config, *, day=26, relevant_rank=1, analyzer=None):
    return DailyPipeline(
        root=root,
        config=config,
        trending_provider=FakeTrendingProvider(),
        repository_provider=FakeRepositoryProvider(relevant_rank=relevant_rank),
        analyzer=analyzer or FakeAnalyzer(),
        clock=clock(day),
    )


def test_pipeline_publishes_snapshot_and_matching_report(tmp_path, relevance_config):
    result = make_pipeline(tmp_path, relevance_config).run()

    assert result.snapshot.candidate_count == 20
    assert result.snapshot.included_count == 1
    assert (tmp_path / "data" / "2026-08-26.json").read_text(
        encoding="utf-8"
    ) == result.snapshot_json
    dated = (tmp_path / "reports" / "2026-08-26.md").read_text(encoding="utf-8")
    latest = (tmp_path / "reports" / "latest.md").read_text(encoding="utf-8")
    assert dated == latest == result.report
    assert "## #1 [owner/repo01]" in dated
    assert "owner/repo02" not in dated


def test_zero_result_is_valid_and_does_not_call_llm(tmp_path, relevance_config):
    analyzer = FakeAnalyzer()

    result = make_pipeline(
        tmp_path,
        relevance_config,
        relevant_rank=None,
        analyzer=analyzer,
    ).run()

    assert result.snapshot.included_count == 0
    assert analyzer.analysis_calls == 0
    assert "今日总榜前 20 中无符合筛选范围的项目" in result.report


def test_dry_run_does_not_write_artifacts(tmp_path, relevance_config):
    result = make_pipeline(tmp_path, relevance_config).run(dry_run=True)

    assert result.published is False
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "reports").exists()


def test_failed_analysis_preserves_existing_artifacts(tmp_path, relevance_config):
    data_dir = tmp_path / "data"
    reports_dir = tmp_path / "reports"
    data_dir.mkdir()
    reports_dir.mkdir()
    data_file = data_dir / "2026-08-26.json"
    latest = reports_dir / "latest.md"
    data_file.write_text("old data", encoding="utf-8")
    latest.write_text("old report", encoding="utf-8")

    class FailingAnalyzer(FakeAnalyzer):
        def analyze(self, repository, rule):
            raise RuntimeError("model unavailable")

    with pytest.raises(RuntimeError, match="model unavailable"):
        make_pipeline(tmp_path, relevance_config, analyzer=FailingAnalyzer()).run()

    assert data_file.read_text(encoding="utf-8") == "old data"
    assert latest.read_text(encoding="utf-8") == "old report"


def test_history_counts_consecutive_days_and_keeps_first_seen(tmp_path, relevance_config):
    first = make_pipeline(tmp_path, relevance_config, day=24).run()
    second = make_pipeline(tmp_path, relevance_config, day=25).run()
    third_after_gap = make_pipeline(tmp_path, relevance_config, day=27).run()

    assert first.snapshot.candidates[0].consecutive_days == 1
    assert second.snapshot.candidates[0].consecutive_days == 2
    assert second.snapshot.candidates[0].first_seen_date == "2026-08-24"
    assert third_after_gap.snapshot.candidates[0].consecutive_days == 1
    assert third_after_gap.snapshot.candidates[0].first_seen_date == "2026-08-24"


def test_same_day_successfully_overwrites_single_version(tmp_path, relevance_config):
    make_pipeline(tmp_path, relevance_config, analyzer=FakeAnalyzer(summary="第一版")).run()
    second = make_pipeline(
        tmp_path, relevance_config, analyzer=FakeAnalyzer(summary="第二版")
    ).run()

    assert len(list((tmp_path / "data").glob("*.json"))) == 1
    assert "第二版" in (tmp_path / "reports" / "2026-08-26.md").read_text(encoding="utf-8")
    assert second.snapshot.candidates[0].consecutive_days == 1


def test_snapshot_does_not_persist_readme_content_or_secrets(tmp_path, relevance_config):
    class SecretRepositoryProvider(FakeRepositoryProvider):
        def enrich(self, trending):
            repository = super().enrich(trending)
            return repository.model_copy(
                update={"readme_excerpt": "DASHSCOPE_API_KEY=top-secret-value"}
            )

    pipeline = DailyPipeline(
        root=tmp_path,
        config=relevance_config,
        trending_provider=FakeTrendingProvider(),
        repository_provider=SecretRepositoryProvider(relevant_rank=1),
        analyzer=FakeAnalyzer(),
        clock=clock(26),
    )

    result = pipeline.run(dry_run=True)

    assert "top-secret-value" not in result.snapshot_json
    assert "readme_excerpt" not in result.snapshot_json


def test_report_escapes_untrusted_markdown_and_html(tmp_path, relevance_config):
    class UnsafeRepositoryProvider(FakeRepositoryProvider):
        def enrich(self, trending):
            repository = super().enrich(trending)
            if trending.rank == 1:
                info = repository.info.model_copy(
                    update={"description": "<script>[click](javascript:bad) *bold* agent"}
                )
                return repository.model_copy(update={"info": info})
            return repository

    pipeline = DailyPipeline(
        root=tmp_path,
        config=relevance_config,
        trending_provider=FakeTrendingProvider(),
        repository_provider=UnsafeRepositoryProvider(relevant_rank=1),
        analyzer=FakeAnalyzer(),
        clock=clock(26),
    )

    report = pipeline.run(dry_run=True).report

    assert "&lt;script&gt;" in report
    assert "\\[click\\]" in report
    assert "\\*bold\\*" in report
