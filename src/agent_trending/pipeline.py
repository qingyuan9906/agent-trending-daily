from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from agent_trending.config import RelevanceConfig
from agent_trending.history import HistoryIndex
from agent_trending.models import (
    CandidateRecord,
    DailySnapshot,
    EnrichedRepository,
    ProjectBrief,
    RelevanceAnalysis,
    RuleEvidence,
    TrendingRepository,
)
from agent_trending.publish import AtomicPublisher
from agent_trending.render import render_report
from agent_trending.rules import evaluate_rules
from agent_trending.sources import TRENDING_URL


class TrendingProvider(Protocol):
    def fetch(self) -> list[TrendingRepository]: ...


class RepositoryProvider(Protocol):
    def enrich(self, trending: TrendingRepository) -> EnrichedRepository: ...


class Analyzer(Protocol):
    def analyze(self, repository: EnrichedRepository, rule: RuleEvidence) -> RelevanceAnalysis: ...

    def create_brief(self, repository: EnrichedRepository, rule: RuleEvidence) -> ProjectBrief: ...


@dataclass(frozen=True)
class RunResult:
    snapshot: DailySnapshot
    snapshot_json: str
    report: str
    published: bool


class DailyPipeline:
    def __init__(
        self,
        *,
        root: Path,
        config: RelevanceConfig,
        trending_provider: TrendingProvider,
        repository_provider: RepositoryProvider,
        analyzer: Analyzer,
        clock: Callable[[], datetime] | None = None,
        publisher: AtomicPublisher | None = None,
    ) -> None:
        self.root = root
        self.config = config
        self.trending_provider = trending_provider
        self.repository_provider = repository_provider
        self.analyzer = analyzer
        timezone = ZoneInfo(config.timezone)
        self.clock = clock or (lambda: datetime.now(timezone))
        self.publisher = publisher or AtomicPublisher(root)

    def run(self, *, dry_run: bool = False) -> RunResult:
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("pipeline clock must return a timezone-aware datetime")
        local_now = now.astimezone(ZoneInfo(self.config.timezone))
        run_date = local_now.date()
        trending = self.trending_provider.fetch()
        if not trending:
            raise ValueError("daily trending source must provide at least one candidate")
        enriched = [self.repository_provider.enrich(item) for item in trending]
        history = HistoryIndex.load(self.root / "data", run_date)
        candidates = [self._classify(item, history, run_date) for item in enriched]
        snapshot = DailySnapshot(
            schema_version=1,
            run_date=run_date.isoformat(),
            generated_at=local_now.isoformat(timespec="seconds"),
            timezone="Asia/Shanghai",
            source_url=TRENDING_URL,
            model=self.config.model,
            candidate_count=len(candidates),
            included_count=sum(candidate.included for candidate in candidates),
            candidates=candidates,
        )
        snapshot_json = (
            json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        )
        report = render_report(snapshot, self.config)
        # Re-parse before any write so serialization is part of the contract.
        DailySnapshot.model_validate_json(snapshot_json, strict=True)
        if not dry_run:
            self.publisher.publish_daily(
                run_date=snapshot.run_date,
                snapshot_json=snapshot_json,
                report=report,
            )
        return RunResult(
            snapshot=snapshot,
            snapshot_json=snapshot_json,
            report=report,
            published=not dry_run,
        )

    def _classify(
        self,
        repository: EnrichedRepository,
        history: HistoryIndex,
        run_date: date,
    ) -> CandidateRecord:
        rule = evaluate_rules(repository, self.config)
        if rule.decision in {"force_exclude", "rule_exclude"}:
            reason = (
                "人工 denylist 强制排除。"
                if rule.decision == "force_exclude"
                else "未发现 Agent 应用相关信号，规则排除。"
            )
            return self._excluded(repository, rule, reason=reason, llm_output=None)

        if rule.decision == "force_include":
            brief = self.analyzer.create_brief(repository, rule)
            first_seen, consecutive = history.active_history(repository.info.full_name, run_date)
            return CandidateRecord(
                repository=repository.info,
                rule=rule,
                llm_output=brief,
                included=True,
                primary_category=brief.primary_category,
                related_tags=brief.related_tags,
                summary_zh=brief.summary_zh,
                relevance_reason_zh=brief.relevance_reason_zh,
                highlights_zh=brief.highlights_zh,
                first_seen_date=first_seen,
                consecutive_days=consecutive,
            )

        analysis = self.analyzer.analyze(repository, rule)
        if not analysis.is_relevant:
            return self._excluded(repository, rule, reason=analysis.reason_zh, llm_output=analysis)
        first_seen, consecutive = history.active_history(repository.info.full_name, run_date)
        return CandidateRecord(
            repository=repository.info,
            rule=rule,
            llm_output=analysis,
            included=True,
            primary_category=analysis.primary_category,
            related_tags=analysis.related_tags,
            summary_zh=analysis.summary_zh,
            relevance_reason_zh=analysis.reason_zh,
            highlights_zh=analysis.highlights_zh,
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
