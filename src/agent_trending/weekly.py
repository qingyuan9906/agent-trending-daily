from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from agent_trending.articles import ANTHROPIC_ENGINEERING_URL, OPENAI_BLOG_URL
from agent_trending.checkpoint import (
    WeeklyCheckpointStore,
    article_fingerprint,
    candidate_fingerprint,
)
from agent_trending.config import RelevanceConfig
from agent_trending.models import (
    ArticleAssessment,
    ArticleDocument,
    CandidateRecord,
    DailyObservation,
    EnrichedRepository,
    OfficialArticleRecord,
    ProjectBrief,
    RelevanceAnalysis,
    RuleEvidence,
    TokenUsage,
    TrendingRepository,
    WeeklyProjectRanking,
    WeeklySnapshot,
)
from agent_trending.observations import ObservationStore
from agent_trending.publish import AtomicPublisher
from agent_trending.render_weekly import render_weekly_html, render_weekly_report
from agent_trending.rules import evaluate_rules
from agent_trending.sources import TRENDING_URL, WEEKLY_TRENDING_URL


class TrendingProvider(Protocol):
    def fetch(self) -> list[TrendingRepository]: ...


class RepositoryProvider(Protocol):
    def enrich(self, trending: TrendingRepository) -> EnrichedRepository: ...


class ArticleProvider(Protocol):
    def fetch(self, period_start: date, period_end: date) -> list[ArticleDocument]: ...


class Analyzer(Protocol):
    def reset_usage(self) -> None: ...

    @property
    def token_usage(self) -> TokenUsage: ...

    def analyze(self, repository: EnrichedRepository, rule: RuleEvidence) -> RelevanceAnalysis: ...

    def create_brief(self, repository: EnrichedRepository, rule: RuleEvidence) -> ProjectBrief: ...

    def analyze_article(self, article: ArticleDocument) -> ArticleAssessment: ...


@dataclass(frozen=True)
class WeeklyRunResult:
    snapshot: WeeklySnapshot
    snapshot_json: str
    report: str
    html_report: str
    published: bool


class ObservationHistory:
    def __init__(self, metrics: dict[str, tuple[str, int]]) -> None:
        self.metrics = metrics

    def active_history(self, full_name: str, run_date: date) -> tuple[str, int]:
        return self.metrics.get(full_name.casefold(), (run_date.isoformat(), 0))


class WeeklyPipeline:
    def __init__(
        self,
        *,
        root: Path,
        config: RelevanceConfig,
        weekly_provider: TrendingProvider,
        repository_provider: RepositoryProvider,
        article_provider: ArticleProvider,
        analyzer: Analyzer,
        clock: Callable[[], datetime] | None = None,
        publisher: AtomicPublisher | None = None,
    ) -> None:
        self.root = root
        self.config = config
        self.weekly_provider = weekly_provider
        self.repository_provider = repository_provider
        self.article_provider = article_provider
        self.analyzer = analyzer
        timezone = ZoneInfo(config.timezone)
        self.clock = clock or (lambda: datetime.now(timezone))
        self.publisher = publisher or AtomicPublisher(root)

    def run(self, *, dry_run: bool = False) -> WeeklyRunResult:
        self.analyzer.reset_usage()
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("pipeline clock must return a timezone-aware datetime")
        local_now = now.astimezone(ZoneInfo(self.config.timezone))
        published_date = local_now.date() - timedelta(days=local_now.weekday())
        period_end = published_date - timedelta(days=1)
        period_start = period_end - timedelta(days=6)

        observation_store = ObservationStore(self.root)
        observations = observation_store.load_period(period_start, period_end)
        weekly = self.weekly_provider.fetch()
        documents = self.article_provider.fetch(period_start, period_end)
        candidates_input, weekly_ranks = merge_weekly_candidates(weekly, observations)
        history = ObservationHistory(
            observation_store.history_metrics(
                [candidate.full_name for candidate in candidates_input], period_end
            )
        )
        checkpoint = None
        if not dry_run:
            checkpoint = WeeklyCheckpointStore(
                root=self.root,
                published_date=published_date,
                period_start=period_start,
                period_end=period_end,
                config=self.config,
                initial_usage=self.analyzer.token_usage,
            )

        candidates: list[CandidateRecord] = []
        for item in candidates_input:
            enriched = self.repository_provider.enrich(item)
            rule = evaluate_rules(enriched, self.config)
            input_sha256 = candidate_fingerprint(enriched, rule)
            cached = (
                checkpoint.cached_candidate(
                    full_name=enriched.info.full_name, input_sha256=input_sha256
                )
                if checkpoint is not None
                else None
            )
            if cached is not None:
                candidates.append(cached)
                continue
            try:
                candidate = self._classify(enriched, history, period_end, rule)
            except Exception:
                if checkpoint is not None:
                    checkpoint.save_usage(self.analyzer.token_usage)
                raise
            candidates.append(candidate)
            if checkpoint is not None:
                checkpoint.save_candidate(
                    current_usage=self.analyzer.token_usage,
                    full_name=enriched.info.full_name,
                    input_sha256=input_sha256,
                    candidate=candidate,
                )

        articles: list[OfficialArticleRecord] = []
        for document in documents:
            input_sha256 = article_fingerprint(document)
            assessment = (
                checkpoint.cached_article(url=document.url, input_sha256=input_sha256)
                if checkpoint is not None
                else None
            )
            if assessment is None:
                try:
                    assessment = self.analyzer.analyze_article(document)
                except Exception:
                    if checkpoint is not None:
                        checkpoint.save_usage(self.analyzer.token_usage)
                    raise
                if checkpoint is not None:
                    checkpoint.save_article(
                        current_usage=self.analyzer.token_usage,
                        url=document.url,
                        input_sha256=input_sha256,
                        assessment=assessment,
                    )
            if assessment.is_relevant:
                articles.append(
                    OfficialArticleRecord(
                        source=document.source,
                        title=document.title,
                        url=document.url,
                        published_date=document.published_date,
                        summary_zh=assessment.summary_zh,
                        content_sha256=document.content_sha256,
                    )
                )
        articles = sorted(
            articles,
            key=lambda item: (-date.fromisoformat(item.published_date).toordinal(), item.url),
        )[:5]
        selected = rank_projects(candidates, weekly_ranks)
        token_usage = (
            checkpoint.state.token_usage if checkpoint is not None else self.analyzer.token_usage
        )
        snapshot = WeeklySnapshot(
            schema_version=3,
            published_date=published_date.isoformat(),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            generated_at=local_now.isoformat(timespec="seconds"),
            timezone="Asia/Shanghai",
            source_urls=[
                TRENDING_URL,
                WEEKLY_TRENDING_URL,
                OPENAI_BLOG_URL,
                ANTHROPIC_ENGINEERING_URL,
            ],
            model=self.config.model,
            token_usage=token_usage,
            candidate_count=len(candidates),
            relevant_count=sum(candidate.included for candidate in candidates),
            selected_count=len(selected),
            candidates=candidates,
            selected_projects=selected,
            articles=articles,
        )
        snapshot_json = (
            json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        )
        report = render_weekly_report(snapshot, self.config)
        html_report = render_weekly_html(snapshot, self.config)
        WeeklySnapshot.model_validate_json(snapshot_json, strict=True)
        if not dry_run:
            self.publisher.publish_weekly(
                published_date=snapshot.published_date,
                snapshot_json=snapshot_json,
                report=report,
                html_report=html_report,
            )
            if checkpoint is not None:
                checkpoint.clear()
        return WeeklyRunResult(
            snapshot=snapshot,
            snapshot_json=snapshot_json,
            report=report,
            html_report=html_report,
            published=not dry_run,
        )

    def _classify(
        self,
        repository: EnrichedRepository,
        history: ObservationHistory,
        period_end: date,
        rule: RuleEvidence,
    ) -> CandidateRecord:
        if rule.decision in {"force_exclude", "rule_exclude"}:
            reason = (
                "人工 denylist 强制排除。"
                if rule.decision == "force_exclude"
                else "未发现 Agent 应用相关信号，规则排除。"
            )
            return self._excluded(repository, rule, reason=reason, llm_output=None)
        if rule.decision == "force_include":
            output: RelevanceAnalysis | ProjectBrief = self.analyzer.create_brief(
                repository, rule
            )
        else:
            output = self.analyzer.analyze(repository, rule)
            if not output.is_relevant:
                return self._excluded(
                    repository, rule, reason=output.reason_zh, llm_output=output
                )
        first_seen, consecutive = history.active_history(
            repository.info.full_name, period_end
        )
        reason = (
            output.relevance_reason_zh
            if isinstance(output, ProjectBrief)
            else output.reason_zh
        )
        return CandidateRecord(
            repository=repository.info,
            rule=rule,
            llm_output=output,
            included=True,
            primary_category=output.primary_category,
            related_tags=output.related_tags,
            summary_zh=output.summary_zh,
            relevance_reason_zh=reason,
            highlights_zh=output.highlights_zh,
            first_seen_date=first_seen,
            consecutive_days=consecutive,
        )

    @staticmethod
    def _excluded(
        repository: EnrichedRepository,
        rule: RuleEvidence,
        *,
        reason: str,
        llm_output: RelevanceAnalysis | None,
    ) -> CandidateRecord:
        return CandidateRecord(
            repository=repository.info,
            rule=rule,
            llm_output=llm_output,
            included=False,
            primary_category="out_of_scope",
            related_tags=[],
            summary_zh="",
            relevance_reason_zh=reason,
            highlights_zh=[],
            first_seen_date=None,
            consecutive_days=0,
        )


def merge_weekly_candidates(
    weekly: list[TrendingRepository], observations: list[DailyObservation]
) -> tuple[list[TrendingRepository], dict[str, int]]:
    weekly_ranks = {item.full_name.casefold(): item.rank for item in weekly}
    last_day = {
        item.full_name.casefold(): item for item in observations[-1].repositories
    }
    merged: dict[str, TrendingRepository] = {}
    for item in weekly:
        daily = last_day.get(item.full_name.casefold())
        merged[item.full_name.casefold()] = item.model_copy(
            update={"stars_today": daily.stars_today if daily is not None else 0}
        )
    for observation in observations:
        for item in observation.repositories:
            merged.setdefault(item.full_name.casefold(), item)
    candidates = [
        item.model_copy(
            update={
                "rank": rank,
                "stars_today": last_day.get(key).stars_today if key in last_day else 0,
            }
        )
        for rank, (key, item) in enumerate(merged.items(), start=1)
    ]
    return candidates, weekly_ranks


def rank_projects(
    candidates: list[CandidateRecord], weekly_ranks: dict[str, int]
) -> list[WeeklyProjectRanking]:
    relevant = [candidate for candidate in candidates if candidate.included]
    if not relevant:
        return []
    streak_order = sorted(
        relevant,
        key=lambda item: (-item.consecutive_days, item.repository.full_name.casefold()),
    )
    star_order = sorted(
        relevant,
        key=lambda item: (-item.repository.stars_today, item.repository.full_name.casefold()),
    )
    streak_ranks = _competition_ranks(streak_order, lambda item: item.consecutive_days)
    star_ranks = _competition_ranks(star_order, lambda item: item.repository.stars_today)

    def ranking_key(candidate: CandidateRecord) -> tuple[int, int, int, int, int, str]:
        key = candidate.repository.full_name.casefold()
        streak_rank = streak_ranks[key]
        star_rank = star_ranks[key]
        return (
            min(streak_rank, star_rank),
            streak_rank + star_rank,
            -candidate.consecutive_days,
            -candidate.repository.stars_today,
            weekly_ranks.get(key, 1_000_000),
            key,
        )

    selected = sorted(relevant, key=ranking_key)[:5]
    return [
        WeeklyProjectRanking(
            full_name=candidate.repository.full_name,
            display_rank=index,
            consecutive_days=candidate.consecutive_days,
            stars_last_day=candidate.repository.stars_today,
            streak_rank=streak_ranks[candidate.repository.full_name.casefold()],
            star_rank=star_ranks[candidate.repository.full_name.casefold()],
            priority_rank=min(
                streak_ranks[candidate.repository.full_name.casefold()],
                star_ranks[candidate.repository.full_name.casefold()],
            ),
            weekly_rank=weekly_ranks.get(candidate.repository.full_name.casefold()),
        )
        for index, candidate in enumerate(selected, start=1)
    ]


def _competition_ranks(
    items: list[CandidateRecord], value: Callable[[CandidateRecord], int]
) -> dict[str, int]:
    ranks: dict[str, int] = {}
    previous_value: int | None = None
    current_rank = 0
    for position, item in enumerate(items, start=1):
        item_value = value(item)
        if item_value != previous_value:
            current_rank = position
            previous_value = item_value
        ranks[item.repository.full_name.casefold()] = current_rank
    return ranks
