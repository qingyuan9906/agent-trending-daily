from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REPOSITORY_NAME_PATTERN = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrendingRepository(StrictModel):
    rank: int = Field(ge=1)
    full_name: str = Field(pattern=REPOSITORY_NAME_PATTERN)
    url: str = Field(pattern=r"^https://github\.com/")
    page_description: str = ""
    language: str | None = None
    stars_today: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_repository_url(self) -> TrendingRepository:
        if self.url != f"https://github.com/{self.full_name}":
            raise ValueError("repository URL does not match full_name")
        return self


class RepositoryInfo(StrictModel):
    rank: int = Field(ge=1)
    full_name: str = Field(pattern=REPOSITORY_NAME_PATTERN)
    url: str = Field(pattern=r"^https://github\.com/")
    description: str = ""
    language: str | None = None
    stars_total: int = Field(ge=0)
    stars_today: int = Field(ge=0)
    forks: int = Field(ge=0)
    license: str | None = None
    topics: list[str]
    readme_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_repository_url(self) -> RepositoryInfo:
        if self.url != f"https://github.com/{self.full_name}":
            raise ValueError("repository URL does not match full_name")
        return self


class EnrichedRepository(StrictModel):
    info: RepositoryInfo
    readme_excerpt: str


class RuleEvidence(StrictModel):
    decision: Literal["force_include", "force_exclude", "rule_exclude", "llm_review"]
    matched_positive_terms: list[str]
    matched_excluded_terms: list[str]
    override: Literal["allowlist", "denylist"] | None = None


class RelevanceDecision(StrictModel):
    is_relevant: bool
    reason_zh: str = Field(min_length=1, max_length=240)
    confidence: Literal["high", "medium", "low"]


class RelevanceAnalysis(StrictModel):
    is_relevant: bool
    primary_category: str = Field(min_length=1)
    related_tags: list[str] = Field(max_length=3)
    reason_zh: str = Field(min_length=1, max_length=240)
    confidence: Literal["high", "medium", "low"]
    summary_zh: str = Field(max_length=280)
    highlights_zh: list[str] = Field(max_length=3)

    @model_validator(mode="after")
    def validate_relevance_shape(self) -> RelevanceAnalysis:
        if self.is_relevant:
            if self.primary_category == "out_of_scope":
                raise ValueError("relevant project cannot use out_of_scope")
            if not self.summary_zh.strip():
                raise ValueError("relevant project requires summary_zh")
            if not 1 <= len(self.related_tags) <= 3:
                raise ValueError("relevant project requires 1-3 related_tags")
            if not 1 <= len(self.highlights_zh) <= 3:
                raise ValueError("relevant project requires 1-3 highlights_zh")
        else:
            if self.primary_category != "out_of_scope":
                raise ValueError("excluded project must use out_of_scope")
            if self.related_tags:
                raise ValueError("excluded project must use empty related_tags")
            if self.summary_zh:
                raise ValueError("excluded project must use empty summary_zh")
            if self.highlights_zh:
                raise ValueError("excluded project must use empty highlights_zh")
        return self


class ProjectBrief(StrictModel):
    primary_category: str = Field(min_length=1)
    summary_zh: str = Field(min_length=1, max_length=220)
    relevance_reason_zh: str = Field(min_length=1, max_length=180)
    related_tags: list[str] = Field(min_length=1, max_length=3)
    highlights_zh: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        min_length=1, max_length=3
    )


class CandidateRecord(StrictModel):
    repository: RepositoryInfo
    rule: RuleEvidence
    llm_output: RelevanceAnalysis | ProjectBrief | None
    included: bool
    primary_category: str = Field(min_length=1)
    related_tags: list[str]
    summary_zh: str
    relevance_reason_zh: str = Field(min_length=1)
    highlights_zh: list[str]
    first_seen_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    consecutive_days: int = Field(ge=0)

    @field_validator("first_seen_date")
    @classmethod
    def validate_first_seen_date(cls, value: str | None) -> str | None:
        if value is not None:
            date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def validate_final_decision(self) -> CandidateRecord:
        if self.included:
            if not self.summary_zh.strip() or not self.relevance_reason_zh.strip():
                raise ValueError("included candidate requires summary and reason")
            if not 1 <= len(self.related_tags) <= 3 or not 1 <= len(self.highlights_zh) <= 3:
                raise ValueError("included candidate requires 1-3 tags and highlights")
            if len(self.related_tags) != len(set(self.related_tags)):
                raise ValueError("included candidate tags must be unique")
            if self.primary_category == "out_of_scope":
                raise ValueError("included candidate cannot use out_of_scope")
            if self.primary_category not in self.related_tags:
                raise ValueError("included candidate primary category must appear in related_tags")
            if self.first_seen_date is None:
                raise ValueError("included candidate requires first_seen_date")
            if self.llm_output is None:
                raise ValueError("included candidate requires llm_output")
            if isinstance(self.llm_output, RelevanceAnalysis):
                if not self.llm_output.is_relevant:
                    raise ValueError("included candidate requires relevant llm_output")
                output_reason = self.llm_output.reason_zh
            else:
                output_reason = self.llm_output.relevance_reason_zh
            expected = (
                self.llm_output.primary_category,
                self.llm_output.related_tags,
                self.llm_output.summary_zh,
                output_reason,
                self.llm_output.highlights_zh,
            )
            actual = (
                self.primary_category,
                self.related_tags,
                self.summary_zh,
                self.relevance_reason_zh,
                self.highlights_zh,
            )
            if actual != expected:
                raise ValueError("included candidate fields must match llm_output")
        else:
            if self.primary_category != "out_of_scope":
                raise ValueError("excluded candidate must use out_of_scope")
            if self.related_tags or self.summary_zh or self.highlights_zh:
                raise ValueError("excluded candidate must not contain report content")
            if self.first_seen_date is not None or self.consecutive_days != 0:
                raise ValueError("excluded candidate cannot have active history")
            if isinstance(self.llm_output, ProjectBrief):
                raise ValueError("excluded candidate cannot use project brief output")
            if isinstance(self.llm_output, RelevanceAnalysis) and self.llm_output.is_relevant:
                raise ValueError("excluded candidate cannot use relevant llm_output")
        return self


class TokenUsage(StrictModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_cny: float = Field(ge=0, allow_inf_nan=False)
    pricing_basis: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_totals(self) -> TokenUsage:
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached_input_tokens cannot exceed input_tokens")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens plus output_tokens")
        return self


class DailySnapshot(StrictModel):
    schema_version: Literal[1, 2]
    run_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    generated_at: str
    timezone: Literal["Asia/Shanghai"]
    source_url: Literal["https://github.com/trending?since=daily"]
    model: str
    token_usage: TokenUsage | None = None
    candidate_count: int = Field(ge=1)
    included_count: int = Field(ge=0)
    candidates: list[CandidateRecord] = Field(min_length=1)

    @field_validator("run_date")
    @classmethod
    def validate_run_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("generated_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_counts_and_ranks(self) -> DailySnapshot:
        if (self.schema_version == 1) != (self.token_usage is None):
            raise ValueError("schema version 1 forbids token_usage and version 2 requires it")
        if self.candidate_count != len(self.candidates):
            raise ValueError("candidate_count does not match candidates")
        run_date = date.fromisoformat(self.run_date)
        generated_at = datetime.fromisoformat(self.generated_at)
        if generated_at.date() != run_date:
            raise ValueError("generated_at date must match run_date")
        for candidate in self.candidates:
            if candidate.first_seen_date is not None:
                first_seen = date.fromisoformat(candidate.first_seen_date)
                if first_seen > run_date:
                    raise ValueError("candidate first_seen_date cannot be after run_date")
            if candidate.included and candidate.consecutive_days < 1:
                raise ValueError("daily included candidate requires an active streak")
        included_count = sum(candidate.included for candidate in self.candidates)
        if self.included_count != included_count:
            raise ValueError("included_count does not match candidates")
        ranks = [candidate.repository.rank for candidate in self.candidates]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("candidate ranks must be contiguous and start at 1")
        names = [candidate.repository.full_name.casefold() for candidate in self.candidates]
        if len(names) != len(set(names)):
            raise ValueError("candidate repository names must be unique")
        return self


class DailyObservation(StrictModel):
    schema_version: Literal[1]
    observed_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    generated_at: str
    timezone: Literal["Asia/Shanghai"]
    source_url: Literal["https://github.com/trending?since=daily"]
    repositories: list[TrendingRepository] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_observation(self) -> DailyObservation:
        observed_date = date.fromisoformat(self.observed_date)
        generated_at = datetime.fromisoformat(self.generated_at)
        if generated_at.tzinfo is None or generated_at.date() != observed_date:
            raise ValueError("generated_at must be timezone-aware and match observed_date")
        ranks = [repository.rank for repository in self.repositories]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("observation ranks must be contiguous and start at 1")
        names = [repository.full_name.casefold() for repository in self.repositories]
        if len(names) != len(set(names)):
            raise ValueError("observation repository names must be unique")
        return self


class ArticleDocument(StrictModel):
    source: Literal["OpenAI", "Anthropic"]
    title: str = Field(min_length=1, max_length=240)
    url: str
    published_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    content: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_article_document(self) -> ArticleDocument:
        date.fromisoformat(self.published_date)
        allowed_prefix = {
            "OpenAI": "https://developers.openai.com/blog/",
            "Anthropic": "https://www.anthropic.com/engineering/",
        }[self.source]
        if not self.url.startswith(allowed_prefix):
            raise ValueError("article URL does not match its official source")
        return self


class ArticleAssessment(StrictModel):
    is_relevant: bool
    summary_zh: str = Field(max_length=320)

    @model_validator(mode="after")
    def validate_article_assessment(self) -> ArticleAssessment:
        if self.is_relevant != bool(self.summary_zh.strip()):
            raise ValueError("relevant article requires a summary and excluded article forbids one")
        return self


class OfficialArticleRecord(StrictModel):
    source: Literal["OpenAI", "Anthropic"]
    title: str = Field(min_length=1, max_length=240)
    url: str
    published_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    summary_zh: str = Field(min_length=1, max_length=320)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("summary_zh")
    @classmethod
    def validate_summary_plain_text(cls, value: str) -> str:
        if any(marker in value for marker in ("\n", "\r", "**", "__", "`", "[", "]")):
            raise ValueError("article summary must be plain text")
        return value

    @model_validator(mode="after")
    def validate_official_article(self) -> OfficialArticleRecord:
        document = ArticleDocument(
            source=self.source,
            title=self.title,
            url=self.url,
            published_date=self.published_date,
            content="validated separately",
            content_sha256=self.content_sha256,
        )
        del document
        return self


class WeeklyProjectRanking(StrictModel):
    full_name: str = Field(pattern=REPOSITORY_NAME_PATTERN)
    display_rank: int = Field(ge=1, le=5)
    consecutive_days: int = Field(ge=0)
    stars_last_day: int = Field(ge=0)
    streak_rank: int = Field(ge=1)
    star_rank: int = Field(ge=1)
    priority_rank: int = Field(ge=1)
    weekly_rank: int | None = Field(default=None, ge=1)


class WeeklySnapshot(StrictModel):
    schema_version: Literal[3]
    published_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    generated_at: str
    timezone: Literal["Asia/Shanghai"]
    source_urls: list[Literal[
        "https://github.com/trending?since=daily",
        "https://github.com/trending?since=weekly",
        "https://developers.openai.com/blog/",
        "https://www.anthropic.com/engineering",
    ]]
    model: str
    token_usage: TokenUsage
    candidate_count: int = Field(ge=1)
    relevant_count: int = Field(ge=0)
    selected_count: int = Field(ge=0, le=5)
    candidates: list[CandidateRecord] = Field(min_length=1)
    selected_projects: list[WeeklyProjectRanking] = Field(max_length=5)
    articles: list[OfficialArticleRecord] = Field(max_length=5)

    @model_validator(mode="after")
    def validate_weekly_snapshot(self) -> WeeklySnapshot:
        published = date.fromisoformat(self.published_date)
        period_start = date.fromisoformat(self.period_start)
        period_end = date.fromisoformat(self.period_end)
        generated_at = datetime.fromisoformat(self.generated_at)
        if published.weekday() != 0:
            raise ValueError("published_date must be a Monday")
        if period_start.weekday() != 0 or period_end != published - timedelta(days=1):
            raise ValueError("weekly period must end the Sunday before published_date")
        if period_end - timedelta(days=6) != period_start:
            raise ValueError("weekly period must contain exactly seven days")
        generated_date = generated_at.date()
        if generated_at.tzinfo is None or not (
            published <= generated_date <= published + timedelta(days=6)
        ):
            raise ValueError("generated_at must fall within the publication week")
        if self.candidate_count != len(self.candidates):
            raise ValueError("candidate_count does not match candidates")
        ranks = [candidate.repository.rank for candidate in self.candidates]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("weekly candidate ranks must be contiguous and start at 1")
        candidate_names = [
            candidate.repository.full_name.casefold() for candidate in self.candidates
        ]
        if len(candidate_names) != len(set(candidate_names)):
            raise ValueError("weekly candidate repository names must be unique")
        if any(
            candidate.first_seen_date is not None
            and date.fromisoformat(candidate.first_seen_date) > period_end
            for candidate in self.candidates
        ):
            raise ValueError("candidate first_seen_date cannot be after period_end")
        relevant = {
            item.repository.full_name.casefold(): item
            for item in self.candidates
            if item.included
        }
        if self.relevant_count != len(relevant):
            raise ValueError("relevant_count does not match candidates")
        if self.selected_count != len(self.selected_projects):
            raise ValueError("selected_count does not match selected_projects")
        if [item.display_rank for item in self.selected_projects] != list(
            range(1, len(self.selected_projects) + 1)
        ):
            raise ValueError("selected project display ranks must be contiguous")
        selected_names = [item.full_name.casefold() for item in self.selected_projects]
        if len(selected_names) != len(set(selected_names)) or not set(selected_names) <= set(
            relevant
        ):
            raise ValueError("selected projects must uniquely reference relevant candidates")
        for ranking in self.selected_projects:
            candidate = relevant[ranking.full_name.casefold()]
            if candidate.consecutive_days != ranking.consecutive_days:
                raise ValueError("selected project streak does not match candidate")
            if candidate.repository.stars_today != ranking.stars_last_day:
                raise ValueError("selected project daily stars do not match candidate")
        article_urls = [article.url for article in self.articles]
        if len(article_urls) != len(set(article_urls)):
            raise ValueError("article URLs must be unique")
        if article_urls != [
            article.url
            for article in sorted(
                self.articles,
                key=lambda item: (
                    -date.fromisoformat(item.published_date).toordinal(),
                    item.url,
                ),
            )
        ]:
            raise ValueError("articles must be sorted by published date and URL")
        if any(
            not period_start <= date.fromisoformat(article.published_date) <= period_end
            for article in self.articles
        ):
            raise ValueError("article published_date must fall within the weekly period")
        expected_sources = {
            "https://github.com/trending?since=daily",
            "https://github.com/trending?since=weekly",
            "https://developers.openai.com/blog/",
            "https://www.anthropic.com/engineering",
        }
        if set(self.source_urls) != expected_sources or len(self.source_urls) != len(
            expected_sources
        ):
            raise ValueError("weekly source_urls must list all configured sources once")
        return self
