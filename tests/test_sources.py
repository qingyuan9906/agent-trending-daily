from pathlib import Path

import httpx
import pytest

from agent_trending.models import TrendingRepository
from agent_trending.sources import GitHubClient, HttpRequester, SourceError, parse_trending_html

FIXTURE = Path(__file__).parent / "fixtures" / "trending.html"


def test_parse_trending_preserves_top_twenty_order():
    repositories = parse_trending_html(FIXTURE.read_text(encoding="utf-8"))

    assert len(repositories) == 20
    assert repositories[0].full_name == "owner/repo01"
    assert repositories[-1].rank == 20
    assert repositories[0].stars_today == 1001
    assert repositories[1].language == "TypeScript"


def test_parse_trending_rejects_partial_page():
    html = (
        "<article class='Box-row'><h2><a href='/owner/repo'>repo</a></h2>"
        "<span>10 stars today</span></article>"
    )

    with pytest.raises(SourceError, match="expected at least 20"):
        parse_trending_html(html)


def test_parse_trending_rejects_card_without_daily_stars():
    html = "<article class='Box-row'><h2><a href='/owner/repo'>repo</a></h2></article>"

    with pytest.raises(SourceError, match="missing daily stars"):
        parse_trending_html(html)


def test_requester_retries_server_error_and_honors_retry_after():
    responses = [
        httpx.Response(503, headers={"Retry-After": "0"}),
        httpx.Response(200, text="ok"),
    ]
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        response = responses.pop(0)
        response.request = request
        return response

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = HttpRequester(client, sleeper=sleeps.append).request("GET", "https://x.test")

    assert response.text == "ok"
    assert sleeps == [0.0]


def test_github_client_enriches_metadata_and_hashes_readme():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/readme"):
            return httpx.Response(200, text="# Agent README", request=request)
        return httpx.Response(
            200,
            json={
                "description": "Agent framework",
                "language": "Python",
                "stargazers_count": 1234,
                "forks_count": 42,
                "license": {"spdx_id": "MIT"},
                "topics": ["agent", "mcp"],
            },
            request=request,
        )

    trending = TrendingRepository(
        rank=1,
        full_name="owner/repo",
        url="https://github.com/owner/repo",
        page_description="fallback",
        language=None,
        stars_today=99,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        enriched = GitHubClient(
            HttpRequester(client, sleeper=lambda _: None), token="token"
        ).enrich(trending)

    assert enriched.info.description == "Agent framework"
    assert enriched.info.topics == ["agent", "mcp"]
    assert enriched.info.readme_sha256 != "0" * 64
    assert enriched.readme_excerpt == "# Agent README"


def test_github_client_allows_missing_readme():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/readme"):
            return httpx.Response(404, request=request)
        return httpx.Response(
            200,
            json={
                "description": None,
                "language": None,
                "stargazers_count": 1,
                "forks_count": 0,
                "license": None,
                "topics": [],
            },
            request=request,
        )

    trending = TrendingRepository(
        rank=1,
        full_name="owner/repo",
        url="https://github.com/owner/repo",
        page_description="fallback",
        language="Go",
        stars_today=1,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        enriched = GitHubClient(HttpRequester(client, sleeper=lambda _: None), token=None).enrich(
            trending
        )

    assert enriched.info.description == "fallback"
    assert enriched.info.language == "Go"
    assert enriched.readme_excerpt == ""
