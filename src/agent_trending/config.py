from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import Field, field_validator, model_validator

from agent_trending.models import StrictModel


class ConfigurationError(ValueError):
    """Raised when repository or environment configuration is invalid."""


class RelevanceConfig(StrictModel):
    candidate_limit: int = Field(ge=1)
    readme_char_limit: int = Field(ge=1)
    timezone: str
    model: str = Field(min_length=1)
    categories: dict[str, str]
    positive_terms: list[str]
    generic_ai_terms: list[str]
    excluded_focus_terms: list[str]
    allowlist: list[str]
    denylist: list[str]

    @field_validator(
        "positive_terms", "generic_ai_terms", "excluded_focus_terms", "allowlist", "denylist"
    )
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().casefold() for value in values if value.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("configuration lists cannot contain duplicates")
        return normalized

    @model_validator(mode="after")
    def validate_contract(self) -> RelevanceConfig:
        if self.candidate_limit != 20:
            raise ValueError("candidate_limit must be 20")
        if self.readme_char_limit != 12_000:
            raise ValueError("readme_char_limit must be 12000")
        if self.timezone != "Asia/Shanghai":
            raise ValueError("timezone must be Asia/Shanghai")
        if self.model != "qwen3.7-plus":
            raise ValueError("model must be qwen3.7-plus")
        if not self.categories:
            raise ValueError("categories cannot be empty")
        if "out_of_scope" in self.categories:
            raise ValueError("out_of_scope is reserved and must not be a report category")
        for key, label in self.categories.items():
            if not key.replace("_", "").isalnum() or not key[0].isalpha() or key != key.casefold():
                raise ValueError(f"invalid category key: {key}")
            if not label.strip():
                raise ValueError(f"category label cannot be empty: {key}")
        unknown_generic_terms = set(self.generic_ai_terms) - set(self.positive_terms)
        if unknown_generic_terms:
            names = ", ".join(sorted(unknown_generic_terms))
            raise ValueError(f"generic_ai_terms must also be positive_terms: {names}")
        overlap = set(self.allowlist) & set(self.denylist)
        if overlap:
            names = ", ".join(sorted(overlap))
            raise ValueError(f"allowlist and denylist overlap: {names}")
        for name in [*self.allowlist, *self.denylist]:
            if name.count("/") != 1:
                raise ValueError(f"invalid repository name in override list: {name}")
        return self

    @property
    def category_keys(self) -> set[str]:
        return set(self.categories)


def load_config(path: Path) -> RelevanceConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ConfigurationError(f"cannot load config {path}: {error}") from error
    try:
        return RelevanceConfig.model_validate(raw, strict=True)
    except ValueError as error:
        raise ConfigurationError(str(error)) from error


def validate_environment(*, require_github_token: bool = False) -> None:
    required = ["DASHSCOPE_API_KEY", "DASHSCOPE_WORKSPACE_ID"]
    if require_github_token:
        required.append("GITHUB_TOKEN")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ConfigurationError(f"missing environment variables: {', '.join(missing)}")
