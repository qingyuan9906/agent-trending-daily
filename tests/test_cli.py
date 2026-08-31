import shutil
from pathlib import Path

from agent_trending.cli import main

PROJECT_ROOT = Path(__file__).parents[1]


def test_validate_config_checks_required_environment(monkeypatch, capsys):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "secret")
    monkeypatch.setenv("DASHSCOPE_WORKSPACE_ID", "workspace123")

    exit_code = main(["validate-config"], root=PROJECT_ROOT)

    assert exit_code == 0
    assert capsys.readouterr().out == "configuration is valid\n"


def test_rendering_older_snapshot_does_not_downgrade_latest(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "reports").mkdir()
    shutil.copyfile(
        PROJECT_ROOT / "config" / "relevance.yaml",
        tmp_path / "config" / "relevance.yaml",
    )
    for day in ("2026-08-26", "2026-08-27"):
        shutil.copyfile(
            PROJECT_ROOT / "data" / f"{day}.json",
            tmp_path / "data" / f"{day}.json",
        )
    latest_markdown = tmp_path / "reports" / "latest.md"
    latest_html = tmp_path / "reports" / "latest.html"
    latest_markdown.write_text("current markdown", encoding="utf-8")
    latest_html.write_text("current html", encoding="utf-8")

    exit_code = main(["render", "data/2026-08-26.json"], root=tmp_path)

    assert exit_code == 0
    assert (tmp_path / "reports" / "2026-08-26.md").exists()
    assert (tmp_path / "reports" / "2026-08-26.html").exists()
    assert latest_markdown.read_text(encoding="utf-8") == "current markdown"
    assert latest_html.read_text(encoding="utf-8") == "current html"


def test_rendering_latest_snapshot_updates_latest(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    shutil.copyfile(
        PROJECT_ROOT / "config" / "relevance.yaml",
        tmp_path / "config" / "relevance.yaml",
    )
    for day in ("2026-08-26", "2026-08-27"):
        shutil.copyfile(
            PROJECT_ROOT / "data" / f"{day}.json",
            tmp_path / "data" / f"{day}.json",
        )

    exit_code = main(["render", "data/2026-08-27.json"], root=tmp_path)

    assert exit_code == 0
    assert "2026-08-27" in (tmp_path / "reports" / "latest.md").read_text(encoding="utf-8")
    assert "2026-08-27" in (tmp_path / "reports" / "latest.html").read_text(
        encoding="utf-8"
    )
