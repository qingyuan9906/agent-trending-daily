from pathlib import Path

import pytest
from conftest import make_repository

from agent_trending.config import ConfigurationError, load_config
from agent_trending.rules import evaluate_rules


def test_agent_signal_is_sent_to_llm(relevance_config):
    repository = make_repository(description="An agentic RAG assistant")

    evidence = evaluate_rules(repository, relevance_config)

    assert evidence.decision == "llm_review"
    assert "agentic" in evidence.matched_positive_terms
    assert "rag" in evidence.matched_positive_terms


def test_unrelated_repository_is_excluded_by_rule(relevance_config):
    repository = make_repository(description="A fast CSS formatter")

    evidence = evaluate_rules(repository, relevance_config)

    assert evidence.decision == "rule_exclude"
    assert evidence.matched_positive_terms == []


def test_short_term_uses_word_boundaries(relevance_config):
    repository = make_repository(description="A storage engine")

    evidence = evaluate_rules(repository, relevance_config)

    assert "rag" not in evidence.matched_positive_terms


def test_allowlist_forces_only_existing_candidate(relevance_config):
    configured = relevance_config.model_copy(update={"allowlist": ["owner/repo01"]})
    repository = make_repository(full_name="OWNER/Repo01", description="plain project")

    evidence = evaluate_rules(repository, configured)

    assert evidence.decision == "force_include"
    assert evidence.override == "allowlist"


def test_denylist_has_force_exclude(relevance_config):
    configured = relevance_config.model_copy(update={"denylist": ["owner/repo01"]})
    repository = make_repository(description="agent framework")

    evidence = evaluate_rules(repository, configured)

    assert evidence.decision == "force_exclude"
    assert evidence.matched_positive_terms


def test_config_rejects_override_overlap(tmp_path: Path):
    config = tmp_path / "relevance.yaml"
    config.write_text(
        """
candidate_limit: 20
readme_char_limit: 12000
timezone: Asia/Shanghai
model: qwen3.7-plus
categories: {agent_application: Agent 应用}
positive_terms: [agent]
generic_ai_terms: []
excluded_focus_terms: [training]
allowlist: [owner/repo]
denylist: [owner/repo]
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="overlap"):
        load_config(config)


def test_training_only_llm_project_is_excluded_without_model(relevance_config):
    repository = make_repository(description="LLM model training and quantization toolkit")

    evidence = evaluate_rules(repository, relevance_config)

    assert evidence.decision == "rule_exclude"
    assert evidence.matched_positive_terms == ["llm"]
    assert set(evidence.matched_excluded_terms) == {"model training", "quantization"}
