import subprocess
from pathlib import Path


def test_installer_replaces_complete_program_arguments_array():
    root = Path(__file__).parents[1]
    installer = (root / "scripts" / "install_macos_launch_agent.sh").read_text(encoding="utf-8")

    assert "-replace ProgramArguments.1" not in installer
    assert "-replace ProgramArguments" in installer
    assert "/bin/zsh" in installer
    assert "run_daily_macos.sh" in installer


def test_daily_runner_syncs_before_exporting_secrets_and_allows_missing_github_token():
    root = Path(__file__).parents[1]
    runner = (root / "scripts" / "run_daily_macos.sh").read_text(encoding="utf-8")

    assert runner.index("uv sync --locked") < runner.index("export DASHSCOPE_API_KEY")
    assert 'test -n "$GITHUB_TOKEN"' not in runner
    assert "git credential fill 2>/dev/null" in runner
    assert "|| true" in runner


def test_daily_runner_has_bounded_network_and_pipeline_retries():
    root = Path(__file__).parents[1]
    runner_path = root / "scripts" / "run_daily_macos.sh"
    runner = runner_path.read_text(encoding="utf-8")

    assert "network_preflight.py" in runner
    assert "retry_command git_pull 3 20" in runner
    assert "retry_command uv_sync 3 20" in runner
    assert "retry_command pipeline 2 300" in runner
    assert "retry_command git_push 3 20" in runner
    assert "git rev-list '@{upstream}..HEAD'" in runner
    subprocess.run(["zsh", "-n", runner_path], check=True)
