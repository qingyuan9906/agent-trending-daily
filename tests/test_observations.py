from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from agent_trending.models import TrendingRepository
from agent_trending.observations import ObservationError, ObservationStore


def repository(rank: int, name: str, stars: int) -> TrendingRepository:
    return TrendingRepository(
        rank=rank,
        full_name=name,
        url=f"https://github.com/{name}",
        page_description="agent",
        language="Python",
        stars_today=stars,
    )


def test_observation_store_requires_all_seven_days_and_counts_cross_day_streak(tmp_path):
    store = ObservationStore(tmp_path)
    start = datetime(2026, 8, 24, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
    for offset in range(7):
        store.collect(
            [repository(1, "owner/always", 10 + offset)],
            now=start + timedelta(days=offset),
        )

    observations = store.load_period(start.date(), (start + timedelta(days=6)).date())
    metrics = store.history_metrics(
        ["owner/always", "owner/absent"], (start + timedelta(days=6)).date()
    )

    assert len(observations) == 7
    assert metrics["owner/always"] == ("2026-08-24", 7)
    assert metrics["owner/absent"] == ("2026-08-30", 0)


def test_observation_store_reports_missing_dates(tmp_path):
    store = ObservationStore(tmp_path)
    now = datetime(2026, 8, 24, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
    store.collect([repository(1, "owner/repo", 1)], now=now)

    with pytest.raises(ObservationError, match="2026-08-25"):
        store.load_period(now.date(), (now + timedelta(days=6)).date())
