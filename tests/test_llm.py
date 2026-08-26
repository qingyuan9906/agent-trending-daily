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


def valid_analysis(**updates):
    value = {
        "is_relevant": True,
        "primary_category": "agent_framework",
        "related_tags": ["agent_framework", "mcp_tools"],
        "reason_zh": "项目主要提供 Agent 编排和工具调用能力。",
        "confidence": "high",
        "summary_zh": "一个面向工具调用的 Agent 编排框架。",
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
    analyzer, client = make_analyzer(relevance_config, [valid_analysis()])
    repository = make_repository(description="agent framework", readme="untrusted")
    rule = RuleEvidence(
        decision="llm_review",
        matched_positive_terms=["agent"],
        matched_excluded_terms=[],
        override=None,
    )

    result = analyzer.analyze(repository, rule)

    assert result.is_relevant is True
    call = client.endpoint.calls[0]
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["strict"] is True
    schema = call["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert "agent_framework" in schema["properties"]["primary_category"]["enum"]
    assert "max_tokens" not in call
    assert call["extra_body"] == {"enable_thinking": False}


def test_extra_field_is_rejected_then_retried(relevance_config):
    invalid = json.loads(valid_analysis())
    invalid["unexpected"] = "bad"
    analyzer, client = make_analyzer(
        relevance_config,
        [json.dumps(invalid, ensure_ascii=False), valid_analysis()],
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
    assert len(client.endpoint.calls) == 2
    assert "上次输出未通过校验" in client.endpoint.calls[1]["messages"][1]["content"]


def test_business_rule_failure_exhausts_three_attempts(relevance_config):
    invalid = valid_analysis(related_tags=["not_configured"])
    analyzer, client = make_analyzer(relevance_config, [invalid, invalid, invalid])

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

    assert len(client.endpoint.calls) == 3


def test_force_include_uses_project_brief_schema(relevance_config):
    content = json.dumps(
        {
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
