from pathlib import Path


def test_installer_replaces_complete_program_arguments_array():
    root = Path(__file__).parents[1]
    installer = (root / "scripts" / "install_macos_launch_agent.sh").read_text(encoding="utf-8")

    assert "-replace ProgramArguments.1" not in installer
    assert "-replace ProgramArguments" in installer
    assert "/bin/zsh" in installer
    assert "run_daily_macos.sh" in installer
