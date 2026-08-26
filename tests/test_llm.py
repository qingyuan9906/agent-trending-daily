import json
from types import SimpleNamespace

import pytest
from conftest import make_repository

from agent_trending.llm import DashScopeAnalyzer, LLMError
from agent_trending.models import RuleEvidence


class FakeCompletions:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        value = self.contents.pop(0)
        if isinstance(value, Exception):
            raise value
        message = SimpleNamespace(content=value)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    def __init__(self, contents):
        self.endpoint = FakeCompletions(contents)
        self.chat = SimpleNamespace(completions=self.endpoint)


def valid_decision(**updates):
    value = {
        "is_relevant": True,
        "reason_zh": "项目主要提供 Agent 编排和工具调用能力。",
        "confidence": "high",
    }
    value.update(updates)
    return json.dumps(value, ensure_ascii=False)


def valid_brief(**updates):
    value = {
        "primary_category": "agent_framework",
        "summary_zh": "一个面向工具调用的 Agent 编排框架。",
        "relevance_reason_zh": "项目主要提供 Agent 编排和工具调用能力。",
        "related_tags": ["agent_framework", "mcp_tools"],
        "highlights_zh": ["支持工具调用", "提供 Agent 编排"],
    }
    value.update(updates)
    return json.dumps(value, ensure_ascii=False)


def make_analyzer(relevance_config, contents):
    client = FakeClient(contents)
    analyzer = DashScopeAnalyzer(
        api_key="secret",
        workspace_id="workspace123",
        config=relevance_config,
        client=client,
    )
    return analyzer, client


def test_analysis_uses_native_strict_json_schema(relevance_config):
    analyzer, client = make_analyzer(relevance_config, [valid_decision(), valid_brief()])
    repository = make_repository(description="agent framework", readme="untrusted")
    rule = RuleEvidence(
        decision="llm_review",
        matched_positive_terms=["agent"],
        matched_excluded_terms=[],
        override=None,
    )

    result = analyzer.analyze(repository, rule)

    assert result.is_relevant is True
    decision_call, brief_call = client.endpoint.calls
    assert decision_call["response_format"]["type"] == "json_schema"
    assert decision_call["response_format"]["json_schema"]["strict"] is True
    decision_schema = decision_call["response_format"]["json_schema"]["schema"]
    assert decision_schema["additionalProperties"] is False
    brief_schema = brief_call["response_format"]["json_schema"]["schema"]
    assert "agent_framework" in brief_schema["properties"]["primary_category"]["enum"]
    assert "max_tokens" not in decision_call
    assert decision_call["extra_body"] == {"enable_thinking": False}


def test_extra_field_is_rejected_then_retried(relevance_config):
    invalid = json.loads(valid_decision())
    invalid["unexpected"] = "bad"
    analyzer, client = make_analyzer(
        relevance_config,
        [json.dumps(invalid, ensure_ascii=False), valid_decision(), valid_brief()],
    )

    result = analyzer.analyze(
        make_repository(description="agent framework"),
        RuleEvidence(
            decision="llm_review",
            matched_positive_terms=["agent"],
            matched_excluded_terms=[],
            override=None,
        ),
    )

    assert result.is_relevant
    assert len(client.endpoint.calls) == 3
    assert "上次输出未通过校验" in client.endpoint.calls[1]["messages"][1]["content"]


def test_business_rule_failure_exhausts_three_attempts(relevance_config):
    invalid = valid_brief(related_tags=["not_configured"])
    analyzer, client = make_analyzer(
        relevance_config, [valid_decision(), invalid, invalid, invalid]
    )

    with pytest.raises(LLMError, match="after 3 attempts"):
        analyzer.analyze(
            make_repository(description="agent framework"),
            RuleEvidence(
                decision="llm_review",
                matched_positive_terms=["agent"],
                matched_excluded_terms=[],
                override=None,
            ),
        )

    assert len(client.endpoint.calls) == 4


def test_markdown_highlight_is_rejected_then_retried(relevance_config):
    invalid = valid_brief(highlights_zh=["**核心能力**：支持工具调用"])
    analyzer, client = make_analyzer(relevance_config, [valid_decision(), invalid, valid_brief()])

    result = analyzer.analyze(
        make_repository(description="agent framework"),
        RuleEvidence(
            decision="llm_review",
            matched_positive_terms=["agent"],
            matched_excluded_terms=[],
            override=None,
        ),
    )

    assert result.is_relevant is True
    assert result.highlights_zh == ["支持工具调用", "提供 Agent 编排"]
    assert len(client.endpoint.calls) == 3


def test_excluded_decision_is_normalized_without_brief_call(relevance_config):
    analyzer, client = make_analyzer(
        relevance_config,
        [valid_decision(is_relevant=False, reason_zh="主要用于模型预训练。")],
    )

    result = analyzer.analyze(
        make_repository(description="LLM pretraining framework"),
        RuleEvidence(
            decision="llm_review",
            matched_positive_terms=["llm"],
            matched_excluded_terms=["pretraining"],
            override=None,
        ),
    )

    assert result.is_relevant is False
    assert result.primary_category == "out_of_scope"
    assert result.summary_zh == ""
    assert len(client.endpoint.calls) == 1


def test_force_include_uses_project_brief_schema(relevance_config):
    content = json.dumps(
        {
            "primary_category": "agent_application",
            "summary_zh": "一个受人工确认的 Agent 项目。",
            "relevance_reason_zh": "提供 Agent 工具调用能力。",
            "related_tags": ["agent_application"],
            "highlights_zh": ["支持工具调用"],
        },
        ensure_ascii=False,
    )
    analyzer, client = make_analyzer(relevance_config, [content])

    brief = analyzer.create_brief(
        make_repository(description="project"),
        RuleEvidence(
            decision="force_include",
            matched_positive_terms=[],
            matched_excluded_terms=[],
            override="allowlist",
        ),
    )

    assert brief.related_tags == ["agent_application"]
    assert client.endpoint.calls[0]["response_format"]["json_schema"]["name"] == "project_brief"
