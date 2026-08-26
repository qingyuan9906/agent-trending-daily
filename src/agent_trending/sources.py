from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from bs4 import BeautifulSoup

from agent_trending.models import EnrichedRepository, RepositoryInfo, TrendingRepository

TRENDING_URL = "https://github.com/trending?since=daily"
GITHUB_API_URL = "https://api.github.com"
USER_AGENT = "agent-trending-daily/0.1 (+https://github.com/)"


class SourceError(RuntimeError):
    """Raised when a remote source cannot satisfy the daily data contract."""


class HttpRequester:
    def __init__(
        self,
        client: httpx.Client,
        *,
        attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.attempts = attempts
        self.sleeper = sleeper

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        accepted_statuses: set[int] | None = None,
    ) -> httpx.Response:
        accepted = accepted_statuses or {200}
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            response: httpx.Response | None = None
            try:
                response = self.client.request(method, url, headers=headers)
            except httpx.HTTPError as error:
                last_error = error
            else:
                if response.status_code in accepted:
                    return response
                retryable = response.status_code == 429 or response.status_code >= 500
                retryable = retryable or (
                    response.status_code == 403
                    and response.headers.get("x-ratelimit-remaining") == "0"
                )
                if not retryable:
                    raise SourceError(f"request failed with HTTP {response.status_code}: {url}")
                last_error = SourceError(f"retryable HTTP {response.status_code} from {url}")

            if attempt + 1 < self.attempts:
                delay = self._retry_delay(response, attempt)
                self.sleeper(delay)

        raise SourceError(f"request failed after {self.attempts} attempts: {url}") from last_error

    @staticmethod
    def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    return max(0.0, float(retry_after))
                except ValueError:
                    pass
        return float(2**attempt)


class TrendingSource:
    def __init__(self, requester: HttpRequester) -> None:
        self.requester = requester

    def fetch(self) -> list[TrendingRepository]:
        response = self.requester.request(
            "GET",
            TRENDING_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        return parse_trending_html(response.text)


def parse_trending_html(html: str) -> list[TrendingRepository]:
    soup = BeautifulSoup(html, "html.parser")
    articles = soup.select("article.Box-row")
    repositories: list[TrendingRepository] = []
    for article in articles:
        link = article.select_one("h2 a[href]")
        if link is None:
            raise SourceError("trending repository card is missing its repository link")
        href = str(link.get("href", "")).strip()
        parts = [part for part in href.split("/") if part]
        if len(parts) != 2:
            raise SourceError(f"invalid repository link in trending page: {href}")
        full_name = f"{parts[0]}/{parts[1]}"
        description_node = article.select_one("p")
        language_node = article.select_one('[itemprop="programmingLanguage"]')
        card_text = article.get_text(" ", strip=True)
        stars_match = re.search(r"([\d,.]+)\s+stars?\s+today", card_text, re.IGNORECASE)
        if stars_match is None:
            raise SourceError(f"trending repository card is missing daily stars: {full_name}")
        stars_today = _parse_count(stars_match.group(1))
        repositories.append(
            TrendingRepository(
                rank=len(repositories) + 1,
                full_name=full_name,
                url=f"https://github.com/{full_name}",
                page_description=(
                    description_node.get_text(" ", strip=True) if description_node else ""
                ),
                language=(language_node.get_text(strip=True) if language_node else None),
                stars_today=stars_today,
            )
        )
    if not repositories:
        raise SourceError("daily trending page contains no repository cards")
    return repositories


def _parse_count(value: str) -> int:
    normalized = value.replace(",", "").strip().casefold()
    multiplier = 1
    if normalized.endswith("k"):
        multiplier = 1_000
        normalized = normalized[:-1]
    return int(float(normalized) * multiplier)


class GitHubClient:
    def __init__(
        self,
        requester: HttpRequester,
        *,
        token: str | None,
        readme_char_limit: int = 12_000,
    ) -> None:
        self.requester = requester
        self.token = token
        self.readme_char_limit = readme_char_limit

    def enrich(self, trending: TrendingRepository) -> EnrichedRepository:
        metadata_response = self.requester.request(
            "GET",
            f"{GITHUB_API_URL}/repos/{trending.full_name}",
            headers=self._headers("application/vnd.github+json"),
        )
        metadata = self._metadata_object(metadata_response.json(), trending.full_name)
        readme_response = self.requester.request(
            "GET",
            f"{GITHUB_API_URL}/repos/{trending.full_name}/readme",
            headers=self._headers("application/vnd.github.raw+json"),
            accepted_statuses={200, 404},
        )
        readme = "" if readme_response.status_code == 404 else readme_response.text
        excerpt = readme[: self.readme_char_limit]
        license_data = metadata.get("license")
        license_name = None
        if isinstance(license_data, dict):
            license_name = license_data.get("spdx_id") or license_data.get("name")
            if license_name == "NOASSERTION":
                license_name = None
        topics = metadata.get("topics") or []
        if not isinstance(topics, list) or not all(isinstance(topic, str) for topic in topics):
            raise SourceError(f"invalid topics from GitHub API for {trending.full_name}")
        info = RepositoryInfo(
            rank=trending.rank,
            full_name=trending.full_name,
            url=trending.url,
            description=str(metadata.get("description") or trending.page_description),
            language=metadata.get("language") or trending.language,
            stars_total=self._nonnegative_int(metadata, "stargazers_count", trending.full_name),
            stars_today=trending.stars_today,
            forks=self._nonnegative_int(metadata, "forks_count", trending.full_name),
            license=str(license_name) if license_name else None,
            topics=topics,
            readme_sha256=hashlib.sha256(readme.encode("utf-8")).hexdigest(),
        )
        return EnrichedRepository(info=info, readme_excerpt=excerpt)

    def _headers(self, accept: str) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @staticmethod
    def _metadata_object(value: Any, full_name: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise SourceError(f"invalid repository metadata for {full_name}")
        return value

    @staticmethod
    def _nonnegative_int(metadata: dict[str, Any], key: str, full_name: str) -> int:
        value = metadata.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise SourceError(f"invalid {key} from GitHub API for {full_name}")
        return value
