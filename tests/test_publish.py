import os
import stat

import pytest

from agent_trending.publish import AtomicPublisher, PublishError


def test_report_publish_can_preserve_latest_and_uses_readable_permissions(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    latest_markdown = reports / "latest.md"
    latest_html = reports / "latest.html"
    latest_markdown.write_text("current markdown", encoding="utf-8")
    latest_html.write_text("current html", encoding="utf-8")

    AtomicPublisher(tmp_path).publish_reports(
        run_date="2026-08-26",
        report="old markdown",
        html_report="old html",
        update_latest=False,
    )

    dated_markdown = reports / "2026-08-26.md"
    assert dated_markdown.read_text(encoding="utf-8") == "old markdown"
    assert stat.S_IMODE(dated_markdown.stat().st_mode) == 0o644
    assert latest_markdown.read_text(encoding="utf-8") == "current markdown"
    assert latest_html.read_text(encoding="utf-8") == "current html"


def test_group_publish_rolls_back_if_promotion_fails(tmp_path, monkeypatch):
    data = tmp_path / "data" / "2026-08-26.json"
    dated = tmp_path / "reports" / "2026-08-26.md"
    latest = tmp_path / "reports" / "latest.md"
    dated_html = tmp_path / "reports" / "2026-08-26.html"
    latest_html = tmp_path / "reports" / "latest.html"
    data.parent.mkdir()
    dated.parent.mkdir()
    data.write_text("old data", encoding="utf-8")
    dated.write_text("old dated", encoding="utf-8")
    latest.write_text("old latest", encoding="utf-8")
    dated_html.write_text("old dated html", encoding="utf-8")
    latest_html.write_text("old latest html", encoding="utf-8")

    real_replace = os.replace
    calls = 0

    def fail_once(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated failure")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_once)

    with pytest.raises(PublishError):
        AtomicPublisher(tmp_path).publish_daily(
            run_date="2026-08-26",
            snapshot_json="new data",
            report="new report",
            html_report="new html report",
        )

    assert data.read_text(encoding="utf-8") == "old data"
    assert dated.read_text(encoding="utf-8") == "old dated"
    assert latest.read_text(encoding="utf-8") == "old latest"
    assert dated_html.read_text(encoding="utf-8") == "old dated html"
    assert latest_html.read_text(encoding="utf-8") == "old latest html"
