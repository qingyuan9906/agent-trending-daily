from pathlib import Path

import pytest
from conftest import make_repository

from agent_trending.config import ConfigurationError, load_config, validate_environment
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


def test_agent_term_does_not_match_reagent_or_plural(relevance_config):
    reagent = evaluate_rules(
        make_repository(description="A chemical reagent toolkit"), relevance_config
    )
    plural = evaluate_rules(make_repository(description="A toolkit for agents"), relevance_config)

    assert "agent" not in reagent.matched_positive_terms
    assert "agent" not in plural.matched_positive_terms
    assert "agents" in plural.matched_positive_terms


def test_agent_term_matches_next_to_chinese_text(relevance_config):
    repository = make_repository(description="面向Agent应用的开发工具")

    evidence = evaluate_rules(repository, relevance_config)

    assert "agent" in evidence.matched_positive_terms


def test_config_rejects_malformed_override_repository(tmp_path: Path):
    config = tmp_path / "relevance.yaml"
    config.write_text(
        """
readme_char_limit: 12000
timezone: Asia/Shanghai
model: qwen3.7-plus
categories: {agent_application: Agent 应用}
positive_terms: [agent]
generic_ai_terms: []
excluded_focus_terms: []
allowlist: [owner/]
denylist: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="invalid repository name"):
        load_config(config)


def test_environment_rejects_invalid_workspace_id(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "secret")
    monkeypatch.setenv("DASHSCOPE_WORKSPACE_ID", "invalid/workspace")

    with pytest.raises(ConfigurationError, match="invalid DASHSCOPE_WORKSPACE_ID"):
        validate_environment()
