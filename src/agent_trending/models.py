from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    summary_zh: str = Field(min_length=1, max_length=280)
    relevance_reason_zh: str = Field(min_length=1, max_length=240)
    related_tags: list[str] = Field(min_length=1, max_length=3)
    highlights_zh: list[str] = Field(min_length=1, max_length=3)


class CandidateRecord(StrictModel):
    repository: RepositoryInfo
    rule: RuleEvidence
    llm_output: RelevanceAnalysis | ProjectBrief | None
    included: bool
    primary_category: str
    related_tags: list[str]
    summary_zh: str
    relevance_reason_zh: str
    highlights_zh: list[str]
    first_seen_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    consecutive_days: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_final_decision(self) -> CandidateRecord:
        if self.included:
            if not self.summary_zh or not self.relevance_reason_zh:
                raise ValueError("included candidate requires summary and reason")
            if not self.related_tags or not self.highlights_zh:
                raise ValueError("included candidate requires tags and highlights")
            if self.first_seen_date is None or self.consecutive_days < 1:
                raise ValueError("included candidate requires history fields")
        else:
            if self.primary_category != "out_of_scope":
                raise ValueError("excluded candidate must use out_of_scope")
            if self.first_seen_date is not None or self.consecutive_days != 0:
                raise ValueError("excluded candidate cannot have active history")
        return self


class DailySnapshot(StrictModel):
    schema_version: Literal[1]
    run_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    generated_at: str
    timezone: Literal["Asia/Shanghai"]
    source_url: Literal["https://github.com/trending?since=daily"]
    model: str
    candidate_count: int = Field(ge=1)
    included_count: int = Field(ge=0)
    candidates: list[CandidateRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_counts_and_ranks(self) -> DailySnapshot:
        if self.candidate_count != len(self.candidates):
            raise ValueError("candidate_count does not match candidates")
        included_count = sum(candidate.included for candidate in self.candidates)
        if self.included_count != included_count:
            raise ValueError("included_count does not match candidates")
        ranks = [candidate.repository.rank for candidate in self.candidates]
        if ranks != sorted(ranks) or len(ranks) != len(set(ranks)):
            raise ValueError("candidate ranks must be unique and sorted")
        names = [candidate.repository.full_name.casefold() for candidate in self.candidates]
        if len(names) != len(set(names)):
            raise ValueError("candidate repository names must be unique")
        return self
