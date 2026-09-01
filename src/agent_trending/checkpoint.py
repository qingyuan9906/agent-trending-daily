from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field

from agent_trending.config import RelevanceConfig
from agent_trending.models import (
    ArticleAssessment,
    ArticleDocument,
    CandidateRecord,
    EnrichedRepository,
    RuleEvidence,
    StrictModel,
    TokenUsage,
)

CHECKPOINT_SCHEMA_VERSION = 1
ANALYSIS_CONTRACT_VERSION = "2026-08-31-v1"


class CheckpointEntry(StrictModel):
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate: CandidateRecord


class RunCheckpoint(StrictModel):
    schema_version: Literal[1]
    analysis_contract_version: str
    run_date: str
    model: str
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    history_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    token_usage: TokenUsage
    candidates: dict[str, CheckpointEntry]


def config_fingerprint(config: RelevanceConfig) -> str:
    return _json_fingerprint(config.model_dump(mode="json"))


def history_fingerprint(data_dir: Path, run_date: date) -> str:
    digest = hashlib.sha256()
    for path in sorted(data_dir.glob("????-??-??.json")):
        if path.stem >= run_date.isoformat():
            continue
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def candidate_fingerprint(repository: EnrichedRepository, rule: RuleEvidence) -> str:
    payload = {
        "repository": repository.info.model_dump(mode="json"),
        "readme_excerpt_sha256": hashlib.sha256(
            repository.readme_excerpt.encode("utf-8")
        ).hexdigest(),
        "rule": rule.model_dump(mode="json"),
    }
    return _json_fingerprint(payload)


def article_fingerprint(article: ArticleDocument) -> str:
    return _json_fingerprint(
        {
            "source": article.source,
            "title": article.title,
            "url": article.url,
            "published_date": article.published_date,
            "content_sha256": article.content_sha256,
        }
    )


def add_token_usage(first: TokenUsage, second: TokenUsage) -> TokenUsage:
    if first.pricing_basis != second.pricing_basis:
        raise ValueError("cannot combine token usage with different pricing basis")
    return TokenUsage(
        input_tokens=first.input_tokens + second.input_tokens,
        output_tokens=first.output_tokens + second.output_tokens,
        cached_input_tokens=first.cached_input_tokens + second.cached_input_tokens,
        total_tokens=first.total_tokens + second.total_tokens,
        estimated_cost_cny=round(first.estimated_cost_cny + second.estimated_cost_cny, 6),
        pricing_basis=first.pricing_basis,
    )


class CheckpointStore:
    def __init__(
        self,
        *,
        root: Path,
        run_date: date,
        config: RelevanceConfig,
        initial_usage: TokenUsage,
    ) -> None:
        self.path = root / ".state" / f"{run_date.isoformat()}.json"
        self._expected = {
            "analysis_contract_version": ANALYSIS_CONTRACT_VERSION,
            "run_date": run_date.isoformat(),
            "model": config.model,
            "config_sha256": config_fingerprint(config),
            "history_sha256": history_fingerprint(root / "data", run_date),
        }
        zero_usage = TokenUsage(
            input_tokens=0,
            output_tokens=0,
            cached_input_tokens=0,
            total_tokens=0,
            estimated_cost_cny=0,
            pricing_basis=initial_usage.pricing_basis,
        )
        self.state = self._load(zero_usage)
        self.prior_usage = self.state.token_usage

    def cached_candidate(
        self, *, full_name: str, input_sha256: str
    ) -> CandidateRecord | None:
        entry = self.state.candidates.get(full_name.casefold())
        if entry is None or entry.input_sha256 != input_sha256:
            return None
        return entry.candidate

    def save_progress(
        self,
        *,
        current_usage: TokenUsage,
        full_name: str | None = None,
        input_sha256: str | None = None,
        candidate: CandidateRecord | None = None,
    ) -> None:
        if candidate is not None:
            if full_name is None or input_sha256 is None:
                raise ValueError("candidate checkpoint requires a name and input fingerprint")
            self.state.candidates[full_name.casefold()] = CheckpointEntry(
                input_sha256=input_sha256,
                candidate=candidate,
            )
        self.state.token_usage = add_token_usage(self.prior_usage, current_usage)
        self._write()

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
        with suppress(OSError):
            self.path.parent.rmdir()

    def _load(self, initial_usage: TokenUsage) -> RunCheckpoint:
        try:
            state = RunCheckpoint.model_validate_json(
                self.path.read_text(encoding="utf-8"), strict=True
            )
        except (OSError, ValueError):
            return self._new(initial_usage)
        if any(getattr(state, key) != value for key, value in self._expected.items()):
            return self._new(initial_usage)
        if state.token_usage.pricing_basis != initial_usage.pricing_basis:
            return self._new(initial_usage)
        return state

    def _new(self, initial_usage: TokenUsage) -> RunCheckpoint:
        return RunCheckpoint(
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            token_usage=initial_usage,
            candidates={},
            **self._expected,
        )

    def _write(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = json.dumps(
            self.state.model_dump(mode="json"), ensure_ascii=False, indent=2
        ) + "\n"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                os.chmod(temporary_path, 0o600)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise


class ArticleCheckpointEntry(StrictModel):
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assessment: ArticleAssessment


class WeeklyRunCheckpoint(StrictModel):
    schema_version: Literal[2]
    analysis_contract_version: str
    published_date: str
    period_start: str
    period_end: str
    model: str
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    history_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    token_usage: TokenUsage
    candidates: dict[str, CheckpointEntry]
    articles: dict[str, ArticleCheckpointEntry]


class WeeklyCheckpointStore:
    def __init__(
        self,
        *,
        root: Path,
        published_date: date,
        period_start: date,
        period_end: date,
        config: RelevanceConfig,
        initial_usage: TokenUsage,
    ) -> None:
        self.path = root / ".state" / f"weekly-{published_date.isoformat()}.json"
        self._expected = {
            "analysis_contract_version": "2026-09-01-weekly-v1",
            "published_date": published_date.isoformat(),
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "model": config.model,
            "config_sha256": config_fingerprint(config),
            "history_sha256": _weekly_history_fingerprint(root, period_end),
        }
        zero_usage = TokenUsage(
            input_tokens=0,
            output_tokens=0,
            cached_input_tokens=0,
            total_tokens=0,
            estimated_cost_cny=0,
            pricing_basis=initial_usage.pricing_basis,
        )
        self.state = self._load(zero_usage)
        self.prior_usage = self.state.token_usage

    def cached_candidate(
        self, *, full_name: str, input_sha256: str
    ) -> CandidateRecord | None:
        entry = self.state.candidates.get(full_name.casefold())
        if entry is None or entry.input_sha256 != input_sha256:
            return None
        return entry.candidate

    def cached_article(self, *, url: str, input_sha256: str) -> ArticleAssessment | None:
        entry = self.state.articles.get(url)
        if entry is None or entry.input_sha256 != input_sha256:
            return None
        return entry.assessment

    def save_candidate(
        self,
        *,
        current_usage: TokenUsage,
        full_name: str,
        input_sha256: str,
        candidate: CandidateRecord,
    ) -> None:
        self.state.candidates[full_name.casefold()] = CheckpointEntry(
            input_sha256=input_sha256, candidate=candidate
        )
        self._save_usage_and_write(current_usage)

    def save_article(
        self,
        *,
        current_usage: TokenUsage,
        url: str,
        input_sha256: str,
        assessment: ArticleAssessment,
    ) -> None:
        self.state.articles[url] = ArticleCheckpointEntry(
            input_sha256=input_sha256, assessment=assessment
        )
        self._save_usage_and_write(current_usage)

    def save_usage(self, current_usage: TokenUsage) -> None:
        self._save_usage_and_write(current_usage)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
        with suppress(OSError):
            self.path.parent.rmdir()

    def _save_usage_and_write(self, current_usage: TokenUsage) -> None:
        self.state.token_usage = add_token_usage(self.prior_usage, current_usage)
        self._write()

    def _load(self, initial_usage: TokenUsage) -> WeeklyRunCheckpoint:
        try:
            state = WeeklyRunCheckpoint.model_validate_json(
                self.path.read_text(encoding="utf-8"), strict=True
            )
        except (OSError, ValueError):
            return self._new(initial_usage)
        if any(getattr(state, key) != value for key, value in self._expected.items()):
            return self._new(initial_usage)
        if state.token_usage.pricing_basis != initial_usage.pricing_basis:
            return self._new(initial_usage)
        return state

    def _new(self, initial_usage: TokenUsage) -> WeeklyRunCheckpoint:
        return WeeklyRunCheckpoint(
            schema_version=2,
            token_usage=initial_usage,
            candidates={},
            articles={},
            **self._expected,
        )

    def _write(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = json.dumps(
            self.state.model_dump(mode="json"), ensure_ascii=False, indent=2
        ) + "\n"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                os.chmod(temporary_path, 0o600)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise


def _weekly_history_fingerprint(root: Path, period_end: date) -> str:
    digest = hashlib.sha256()
    observation_dir = root / "data" / "observations"
    for path in sorted(observation_dir.glob("????-??-??.json")):
        if path.stem > period_end.isoformat():
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    for path in sorted((root / "data").glob("????-??-??.json")):
        if path.stem > period_end.isoformat():
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _json_fingerprint(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
