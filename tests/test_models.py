import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_trending.config import load_config
from agent_trending.models import DailySnapshot
from agent_trending.render import render_report

PROJECT_ROOT = Path(__file__).parents[1]
SNAPSHOT_PATH = PROJECT_ROOT / "data" / "2026-08-27.json"


def load_snapshot_data():
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def test_snapshot_rejects_final_fields_that_disagree_with_llm_output():
    raw = load_snapshot_data()
    candidate = next(item for item in raw["candidates"] if item["included"])
    candidate["summary_zh"] = "与模型输出不一致"

    with pytest.raises(ValidationError, match="must match llm_output"):
        DailySnapshot.model_validate(raw, strict=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [("run_date", "2026-99-99"), ("generated_at", "not-a-datetime")],
)
def test_snapshot_rejects_invalid_dates(field, value):
    raw = load_snapshot_data()
    raw[field] = value

    with pytest.raises(ValidationError):
        DailySnapshot.model_validate(raw, strict=True)


def test_render_rejects_categories_missing_from_current_config():
    raw = load_snapshot_data()
    candidate = next(item for item in raw["candidates"] if item["included"])
    candidate["primary_category"] = "not_configured"
    candidate["related_tags"] = ["not_configured"]
    candidate["llm_output"]["primary_category"] = "not_configured"
    candidate["llm_output"]["related_tags"] = ["not_configured"]
    snapshot = DailySnapshot.model_validate(raw, strict=True)

    with pytest.raises(ValueError, match="unknown categories"):
        render_report(snapshot, load_config(PROJECT_ROOT / "config" / "relevance.yaml"))
