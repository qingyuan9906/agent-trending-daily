from pathlib import Path

import yaml


def test_daily_workflow_limits_credentials_to_required_steps():
    root = Path(__file__).parents[1]
    workflow = yaml.safe_load((root / ".github" / "workflows" / "daily.yml").read_text())
    job = workflow["jobs"]["report"]
    steps = {step["name"]: step for step in job["steps"]}

    assert "env" not in job
    assert steps["Check out repository"]["with"]["persist-credentials"] is False
    assert "env" not in steps["Sync locked environment"]
    assert "env" not in steps["Run tests and lint"]
    assert set(steps["Generate daily report"]["env"]) == {
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_WORKSPACE_ID",
        "GITHUB_TOKEN",
    }
    assert set(steps["Commit generated artifacts"]["env"]) == {"GH_TOKEN"}
