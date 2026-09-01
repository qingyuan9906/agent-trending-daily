from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from agent_trending.models import ArticleDocument
from agent_trending.sources import USER_AGENT, HttpRequester, SourceError

OPENAI_BLOG_URL = "https://developers.openai.com/blog/"
ANTHROPIC_ENGINEERING_URL = "https://www.anthropic.com/engineering"


@dataclass(frozen=True)
class BlogDefinition:
    source: str
    index_url: str
    path_prefix: str


BLOGS = (
    BlogDefinition("OpenAI", OPENAI_BLOG_URL, "/blog/"),
    BlogDefinition("Anthropic", ANTHROPIC_ENGINEERING_URL, "/engineering/"),
)


class OfficialBlogSource:
    def __init__(self, requester: HttpRequester, *, content_char_limit: int = 16_000) -> None:
        self.requester = requester
        self.content_char_limit = content_char_limit

    def fetch(self, period_start: date, period_end: date) -> list[ArticleDocument]:
        documents: list[ArticleDocument] = []
        for blog in BLOGS:
            documents.extend(self._fetch_blog(blog, period_start, period_end))
        return sorted(
            documents,
            key=lambda item: (
                -date.fromisoformat(item.published_date).toordinal(),
                item.url,
            ),
        )

    def _fetch_blog(
        self, blog: BlogDefinition, period_start: date, period_end: date
    ) -> list[ArticleDocument]:
        response = self.requester.request(
            "GET",
            blog.index_url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        candidates = parse_blog_index(response.text, blog=blog, reference_date=period_end)
        if not candidates:
            raise SourceError(f"official blog index contains no article cards: {blog.index_url}")
        documents: list[ArticleDocument] = []
        for title, url, published_date in candidates:
            if not period_start <= published_date <= period_end:
                continue
            article_response = self.requester.request(
                "GET", url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}
            )
            article_title, article_date, content = parse_article_page(
                article_response.text,
                fallback_title=title,
                fallback_date=published_date,
            )
            if article_date != published_date:
                raise SourceError(f"article date disagrees with official index: {url}")
            content = content[: self.content_char_limit]
            documents.append(
                ArticleDocument(
                    source=blog.source,
                    title=article_title,
                    url=url,
                    published_date=published_date.isoformat(),
                    content=content,
                    content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                )
            )
        return documents


def parse_blog_index(
    html: str, *, blog: BlogDefinition, reference_date: date
) -> list[tuple[str, str, date]]:
    soup = BeautifulSoup(html, "html.parser")
    results: dict[str, tuple[str, str, date]] = {}
    expected_host = urlparse(blog.index_url).netloc
    for link in soup.select("a[href]"):
        href = str(link.get("href", "")).strip()
        url = urljoin(blog.index_url, href).rstrip("/")
        parsed = urlparse(url)
        if parsed.netloc != expected_host or not parsed.path.startswith(blog.path_prefix):
            continue
        if parsed.path.rstrip("/") == blog.path_prefix.rstrip("/"):
            continue
        card = link.find_parent("article") or link
        title_node = card.find(["h1", "h2", "h3"]) if isinstance(card, Tag) else None
        title = " ".join((title_node or link).get_text(" ", strip=True).split())
        published_date = _parse_card_date(card.get_text(" ", strip=True), reference_date)
        if title and published_date is not None:
            results[url] = (title, url, published_date)
    return list(results.values())


def parse_article_page(
    html: str, *, fallback_title: str, fallback_date: date
) -> tuple[str, date, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = fallback_title
    title_meta = soup.select_one('meta[property="og:title"], meta[name="twitter:title"]')
    if title_meta and title_meta.get("content"):
        title = " ".join(str(title_meta["content"]).split())
    published_date = _metadata_date(soup) or fallback_date
    content_node = soup.find("article") or soup.find("main")
    if content_node is None:
        raise SourceError("official article page contains no article or main content")
    for node in content_node.select("script, style, nav, footer"):
        node.decompose()
    content = " ".join(content_node.get_text(" ", strip=True).split())
    if not content:
        raise SourceError("official article page contains no readable content")
    return title, published_date, content


def _metadata_date(soup: BeautifulSoup) -> date | None:
    node = soup.select_one(
        'meta[property="article:published_time"], meta[name="date"], time[datetime]'
    )
    if node is not None:
        raw = node.get("content") or node.get("datetime")
        parsed = _parse_iso_date(str(raw or ""))
        if parsed is not None:
            return parsed
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.string or "")
        except (TypeError, json.JSONDecodeError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict):
                parsed = _parse_iso_date(str(item.get("datePublished") or ""))
                if parsed is not None:
                    return parsed
    return None


def _parse_card_date(text: str, reference_date: date) -> date | None:
    iso_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    if iso_match:
        return date.fromisoformat(iso_match.group(0))
    match = re.search(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
        r"(\d{1,2})(?:,\s*(\d{4}))?\b",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    year = int(match.group(3)) if match.group(3) else reference_date.year
    parsed = datetime.strptime(f"{match.group(1)} {match.group(2)} {year}", "%b %d %Y").date()
    if match.group(3) is None and parsed > reference_date:
        parsed = parsed.replace(year=year - 1)
    return parsed


def _parse_iso_date(value: str) -> date | None:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", value)
    return date.fromisoformat(match.group(1)) if match else None
