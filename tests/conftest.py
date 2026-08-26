from pathlib import Path

import pytest

from agent_trending.config import RelevanceConfig, load_config
from agent_trending.models import EnrichedRepository, RepositoryInfo

PROJECT_ROOT = Path(__file__).parents[1]


@pytest.fixture
def relevance_config() -> RelevanceConfig:
    return load_config(PROJECT_ROOT / "config" / "relevance.yaml")


def make_repository(
    rank: int = 1,
    *,
    full_name: str | None = None,
    description: str = "",
    topics: list[str] | None = None,
    readme: str = "",
) -> EnrichedRepository:
    name = full_name or f"owner/repo{rank:02d}"
    return EnrichedRepository(
        info=RepositoryInfo(
            rank=rank,
            full_name=name,
            url=f"https://github.com/{name}",
            description=description,
            language="Python",
            stars_total=1000 + rank,
            stars_today=rank,
            forks=100 + rank,
            license="MIT",
            topics=topics or [],
            readme_sha256="0" * 64,
        ),
        readme_excerpt=readme,
    )
