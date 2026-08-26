from __future__ import annotations

import re

from agent_trending.config import RelevanceConfig
from agent_trending.models import EnrichedRepository, RuleEvidence


def evaluate_rules(repository: EnrichedRepository, config: RelevanceConfig) -> RuleEvidence:
    full_name = repository.info.full_name.casefold()
    text = "\n".join(
        [
            repository.info.full_name,
            repository.info.description,
            " ".join(repository.info.topics),
            repository.readme_excerpt,
        ]
    ).casefold()
    positive = [term for term in config.positive_terms if _contains_term(text, term)]
    excluded = [term for term in config.excluded_focus_terms if _contains_term(text, term)]

    if full_name in config.denylist:
        decision = "force_exclude"
        override = "denylist"
    elif full_name in config.allowlist:
        decision = "force_include"
        override = "allowlist"
    elif not positive or (excluded and set(positive).issubset(set(config.generic_ai_terms))):
        decision = "rule_exclude"
        override = None
    else:
        decision = "llm_review"
        override = None
    return RuleEvidence(
        decision=decision,
        matched_positive_terms=positive,
        matched_excluded_terms=excluded,
        override=override,
    )


def _contains_term(text: str, term: str) -> bool:
    escaped = re.escape(term.casefold())
    if term.replace("-", "").isalnum() and len(term) <= 4:
        return re.search(rf"(?<![\w]){escaped}(?![\w])", text) is not None
    return term.casefold() in text
