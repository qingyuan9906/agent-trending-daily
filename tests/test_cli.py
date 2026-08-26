from pathlib import Path

from agent_trending.cli import main

PROJECT_ROOT = Path(__file__).parents[1]


def test_validate_config_checks_required_environment(monkeypatch, capsys):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "secret")
    monkeypatch.setenv("DASHSCOPE_WORKSPACE_ID", "workspace123")

    exit_code = main(["validate-config"], root=PROJECT_ROOT)

    assert exit_code == 0
    assert capsys.readouterr().out == "configuration is valid\n"
